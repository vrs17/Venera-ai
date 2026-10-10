"""Shikoyat ("Xabar berish"): tekshiruv, chegara, surat manbasi ustunligi va
egalik.

`api/v1/reports.py`, `services/reports.py`. Yuqoridagi xizmat SOXTA
(`FakeAssistant.get_chat`), savollar tarixi vaqtinchalik analitika omboriga
`TurnRecorder` bilan yoziladi - `chat.py` yozadigan AYNI yo'l.
"""

from __future__ import annotations

import json

import pytest

from app.schemas.auth import AuthUser
from app.services import analytics, reports
from app.services.analytics import TurnRecorder, get_db
from app.services.integrations.assistant import AssistantError
from tests.conftest import ADMIN, USER

REPORT_CREATED_FIELDS = {"id", "status", "createdAt"}          # types.ts: ReportCreated
MESSAGE_FIELDS = {"role", "content", "createdAt", "turnId", "sources"}  # types.ts: ReportMessage

DEMO = AuthUser(actorId=2, email=USER["email"], fullName="Demo Foydalanuvchi", roles=["USER"])
OTHER = AuthUser(actorId=1, email=ADMIN["email"], fullName="Administrator", roles=["ADMIN"])
CHAT = "5b0c7f0e-6a55-4c4a-9d7f-0d8c2b1e9a01"


class FakeAssistant:
    """`chat._assistant` o'rnida - faqat suhbat tarixi."""

    def __init__(self, reply=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.reply = reply if reply is not None else {
            "chat_id": CHAT, "title": "Ta'til", "messages": [
                {"role": "user", "content": "Ta'til necha kun?", "created_at": "2026-09-20T10:00:00Z"},
                {"role": "assistant", "content": "21 kun [1].", "created_at": "2026-09-20T10:00:04Z"},
            ]}

    def get_chat(self, chat_id, *, user_id, limit=200):
        self.calls.append((chat_id, user_id))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def upstream(monkeypatch):
    from app.api.v1 import chat as chat_api

    fake = FakeAssistant()
    monkeypatch.setattr(chat_api, "_assistant", fake)
    return fake


@pytest.fixture(autouse=True)
def _fresh_limiter():
    reports.limiter.reset()
    yield
    reports.limiter.reset()


@pytest.fixture
def demo(client) -> dict:
    token = client.post("/api/v1/auth/login", json=USER).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _turn(actor, question, answer, *, chat=CHAT, sources=None, error=False):
    rec = TurnRecorder(actor, "web", "chat", question, chat_id=chat)
    if sources:
        rec.observe({"type": "sources", "items": sources})
    if answer:
        rec.observe({"type": "token", "text": answer})
    if error:
        rec.observe({"type": "error", "code": "stream_broken", "text": "uzildi"})
    rec.observe({"type": "done", "route": "rules"})
    rec.finish()
    return rec.turn_id


def _post(client, headers, body, **extra_headers):
    return client.post("/api/v1/reports", headers={**headers, **extra_headers}, json=body)


def _row(report_id: str) -> dict:
    row = get_db().row("SELECT * FROM reports WHERE id = ?", (report_id,))
    assert row is not None
    row["snapshot"] = json.loads(row["snapshot"])
    return row


# --- yaratish ---------------------------------------------------------------------------


def test_201_shakl_va_saqlangan_qator(client, demo, upstream):
    response = _post(client, demo, {"chatId": CHAT, "reason": "wrong", "comment": "  Eski ma'lumot  "},
                     **{"X-Venera-Client": "web"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == REPORT_CREATED_FIELDS
    assert body["status"] == "new" and len(body["id"]) == 32 and body["createdAt"].endswith("Z")

    row = _row(body["id"])
    assert (row["actor_id"], row["user_name"], row["user_login"]) == (2, "Demo Foydalanuvchi",
                                                                     USER["email"])
    assert (row["channel"], row["chat_id"], row["reason"], row["status"]) == ("web", CHAT, "wrong", "new")
    assert row["comment"] == "Eski ma'lumot"
    assert row["snapshot"]["source"] == "upstream" and row["snapshot"]["title"] == "Ta'til"


def test_kanal_miniapp_referer_boyicha(client, demo, upstream):
    response = _post(client, demo, {"chatId": CHAT}, Referer="https://llm.test/tg/index.html")
    assert _row(response.json()["id"])["channel"] == "miniapp"


def test_sessiyasiz_401(client):
    assert client.post("/api/v1/reports", json={"chatId": CHAT}).status_code == 401


@pytest.mark.parametrize("body", [
    {},                                                           # nima haqida - noma'lum
    {"comment": "faqat izoh"},
    {"chatId": CHAT, "reason": "yomon"},                          # sabab ro'yxatda yo'q
    {"turnId": "not-hex"},
    {"chatId": "x" * 129},
    {"messages": [{"role": "system", "content": "x"}]},
    {"messages": [{"role": "user", "content": "x"}] * 201},
])
def test_notogri_tana_422(client, demo, upstream, body):
    response = _post(client, demo, body)
    assert response.status_code == 422, response.text
    assert get_db().scalar("SELECT COUNT(*) FROM reports") == 0


def test_izoh_va_matn_kesiladi(client, demo):
    response = _post(client, demo, {"comment": "a" * 2500, "messages": [
        {"role": "user", "content": "savol"},
        {"role": "assistant", "content": "b" * 25_000},
    ]})
    assert response.status_code == 201, response.text
    row = _row(response.json()["id"])
    assert len(row["comment"]) == 2000
    messages = row["snapshot"]["messages"]
    assert row["snapshot"]["source"] == "client" and len(messages[1]["content"]) == 20_000
    assert all(set(m) == MESSAGE_FIELDS for m in messages)


def test_bosh_izoh_null(client, demo):
    response = _post(client, demo, {"comment": "   ", "messages": [{"role": "user", "content": "x"}]})
    assert _row(response.json()["id"])["comment"] is None


# --- surat manbasi ------------------------------------------------------------------------


def test_telemetriya_birinchi_va_faqat_oz_savollari(client, demo, upstream):
    first = _turn(DEMO, "Ta'til necha kun?", "21 kun [1].", sources=[
        {"kind": "doc", "doc_id": "HR_045", "title": "Ichki mehnat tartibi", "page": 22,
         "citation_index": 1},
        {"kind": "hrm", "tool": "hrm_today_late", "status": "ok", "digest": "count=9"}])
    # Boshqa odamning savoli O'SHA chatId da (kalit to'qnashuvi yoki taxmin) - ilinmasligi kerak.
    _turn(OTHER, "Maxfiy savol", "Maxfiy javob")
    second = _turn(DEMO, "Mehnat ta'tili-chi?", "", error=True)

    response = _post(client, demo, {"chatId": CHAT, "turnId": second, "reason": "incomplete",
                                    "messages": [{"role": "user", "content": "klient nusxasi"}]})
    assert response.status_code == 201, response.text
    row = _row(response.json()["id"])
    snap = row["snapshot"]
    assert snap["source"] == "telemetry"
    assert upstream.calls == []                                   # xizmatga borilmadi
    assert [(m["role"], m["content"], m["turnId"]) for m in snap["messages"]] == [
        ("user", "Ta'til necha kun?", first), ("assistant", "21 kun [1].", first),
        ("user", "Mehnat ta'tili-chi?", second), ("assistant", "", second)]
    assert "Maxfiy" not in json.dumps(snap, ensure_ascii=False)
    assert snap["messages"][1]["status"] == "ok" and snap["messages"][3]["status"] == "error"
    assert snap["messages"][1]["sources"] == [
        {"kind": "doc", "ref": "HR_045", "title": "Ichki mehnat tartibi", "page": 22, "citation": 1},
        {"kind": "hrm", "ref": "hrm_today_late", "status": "ok"}]
    assert row["turn_id"] == second


def test_turn_id_orqali_suhbat_topiladi(client, demo, upstream):
    own = _turn(DEMO, "Savol", "Javob")
    response = _post(client, demo, {"turnId": own})
    row = _row(response.json()["id"])
    assert (row["chat_id"], row["turn_id"], row["snapshot"]["source"]) == (CHAT, own, "telemetry")


def test_boshqa_odamning_savoli_ilinmaydi(client, demo, upstream):
    foreign = _turn(OTHER, "Maxfiy savol", "Maxfiy javob", chat="admin-chat")
    response = _post(client, demo, {"turnId": foreign, "messages": [
        {"role": "user", "content": "mening savolim", "turnId": foreign}]})
    assert response.status_code == 201
    row = _row(response.json()["id"])
    assert row["turn_id"] is None and row["chat_id"] is None
    assert row["snapshot"]["source"] == "client"
    # Klient nusxasidagi begona `turnId` ham olib tashlandi.
    assert row["snapshot"]["messages"][0]["turnId"] is None
    assert "Maxfiy" not in json.dumps(row["snapshot"], ensure_ascii=False)
    assert upstream.calls == []


def test_telemetriya_yoq_bolsa_xizmat_tarixi_oz_kaliti_bilan(client, demo, upstream):
    response = _post(client, demo, {"chatId": CHAT, "messages": [{"role": "user", "content": "klient"}]})
    snap = _row(response.json()["id"])["snapshot"]
    assert upstream.calls == [(CHAT, "venera:2")]
    assert snap["source"] == "upstream"
    assert [(m["role"], m["content"], m["createdAt"]) for m in snap["messages"]] == [
        ("user", "Ta'til necha kun?", "2026-09-20T10:00:00Z"),
        ("assistant", "21 kun [1].", "2026-09-20T10:00:04Z")]


@pytest.mark.parametrize("failure", [AssistantError("topilmadi", status=404),
                                     AssistantError("band", status=503), RuntimeError("?")])
def test_xizmat_xatosi_shikoyatni_toxtatmaydi_klient_nusxasi(client, demo, upstream, failure):
    upstream.reply = failure
    turn = _turn(DEMO, "savol", "javob", chat="boshqa-suhbat")      # o'ziniki - qoladi
    response = _post(client, demo, {"chatId": CHAT, "messages": [
        {"role": "user", "content": "savol", "createdAt": "2026-09-20T10:00:00Z",
         "turnId": "b" * 32},                                     # tasdiqlanmagan - tashlanadi
        {"role": "assistant", "content": "javob", "turnId": turn.upper(), "sources": [
            {"kind": "doc", "doc_id": "HR_1", "title": "T", "page": 3, "url": "/ichki/havola",
             "nested": {"x": 1}}, "satr"]},
    ]})
    assert response.status_code == 201, response.text
    snap = _row(response.json()["id"])["snapshot"]
    assert snap["source"] == "client"
    assert snap["messages"][0]["createdAt"] == "2026-09-20T10:00:00Z"
    assert snap["messages"][0]["turnId"] is None
    answer = snap["messages"][1]
    assert answer["turnId"] == turn
    # Faqat tanish maydonlar saqlanadi - havola va ichma-ich obyekt tashlanadi.
    assert answer["sources"] == [{"kind": "doc", "doc_id": "HR_1", "title": "T", "page": 3}]


def test_xizmat_bosh_tarix_bersa_klient_nusxasi(client, demo, upstream):
    upstream.reply = {"chat_id": CHAT, "title": "", "messages": []}
    response = _post(client, demo, {"chatId": CHAT, "messages": [{"role": "user", "content": "x"}]})
    assert _row(response.json()["id"])["snapshot"]["source"] == "client"


# --- chegara ------------------------------------------------------------------------------


def test_soatiga_20_ta_keyin_429(client, demo, auth):
    body = {"messages": [{"role": "user", "content": "x"}]}
    for _ in range(20):
        assert _post(client, demo, body).status_code == 201
    response = _post(client, demo, body)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["error"] == "Too Many Requests"
    # Chegara odam bo'yicha - boshqasi yubora oladi.
    assert _post(client, auth, body).status_code == 201
    assert get_db().scalar("SELECT COUNT(*) FROM reports WHERE actor_id = 2") == 20


def test_saqlanmasa_503_va_joy_qaytadi(client, demo, monkeypatch):
    import sqlite3

    database = get_db()
    original = type(database).transaction

    def broken(self):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(type(database), "transaction", broken)
    response = _post(client, demo, {"messages": [{"role": "user", "content": "x"}]})
    assert response.status_code == 503
    monkeypatch.setattr(type(database), "transaction", original)
    assert reports.limiter.take(2) is None
    assert len(reports.limiter._hits[2]) == 1


def test_limiter_oyna_sirpanadi():
    limiter = reports.RateLimiter(limit=2, window=10)
    assert limiter.take("a", now=0) is None and limiter.take("a", now=1) is None
    assert limiter.take("a", now=2) == 9
    assert limiter.take("a", now=10.5) is None                    # birinchisi oynadan chiqdi


def test_surat_hajmi_chegaralanadi(monkeypatch):
    monkeypatch.setattr(reports, "SNAPSHOT_BYTES", 2000)
    snap = {"source": "client", "messages": [
        {"role": "user", "content": "q" * 400}, {"role": "assistant", "content": "a" * 400}] * 5}
    text = reports._fit(snap)
    assert len(text.encode()) <= 2000
    fitted = json.loads(text)
    assert fitted["truncated"] is True and fitted["messages"][0]["role"] == "user"


def test_analitika_ochirilgan_bolsa_ham_shikoyat_saqlanadi(client, demo, upstream, monkeypatch):
    monkeypatch.setattr(analytics.db, "analytics_enabled", lambda: False)
    response = _post(client, demo, {"chatId": CHAT})
    assert response.status_code == 201
    assert _row(response.json()["id"])["snapshot"]["source"] == "upstream"


def test_guruh_crm_suhbati_suratga_olinmaydi(client, demo, upstream):
    """2026-10-10: guruhdagi CRM suhbati (`tgcrm-`) - ichida guruhdagi boshqa odamlarning
    xabarlari: shikoyat suratiga ham, kaliti ham yozilmaydi, xizmatga borilmaydi."""
    response = _post(client, demo, {"chatId": "tgcrm-3f0c2b9e-8f6e-4d7a-9b1c-2a4e5d6f7a8b", "reason": "wrong"})
    assert response.status_code == 201
    assert upstream.calls == []
    row = _row(response.json()["id"])
    assert row["chat_id"] is None and row["snapshot"].get("source") != "upstream"

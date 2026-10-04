"""Birlashtirish (B2 audit): prod + SSO/"Pro" + `venera-admin-redesign` - qolgan
UCHRASHUV joylari.

`test_integration_merge.py` (prod + SSO) va `test_integration_admin.py` (birinchi
ulama) qoplamagan yo'llar. Har test ikki shoxning kodi BIRGA ishlaganda nima
bo'lishini sinaydi - bittasini alohida sinash boshqa fayllarda:

  * kanal: xodimlar ma'lumotnomasi javobi ham `X-Venera-Client` / `Referer`
    bo'yicha to'g'ri kanal bilan yoziladi (web, miniapp, soxta `bot` - `api`);
  * `open_stream` tartibi: kontakt javobida kutish rejasi (tasnif) BOSHLANMAYDI,
    yordamchi savolida esa boshlanadi (prod tartibi + redesign izi);
  * bot savoli `open_stream` dan o'tib `bot` kanali bilan yoziladi - tashqi
    chaqiruv hisobi (`api_calls`) ham shu savolga bog'lanadi; bloklangan odam
    ulanish muddatini UZAYTIRMAYDI, blok olinsa qayta ulanmasdan davom etadi;
  * "Pro": mini app kanali, ochilmagan oqim (`open_failed`) va byudjet so'rovi
    hisobda (`pro.quota`);
  * taklif holati: `ct_` (ma'lumotnoma) amallari - web va botda - yordamchi
    takliflarining `proposal_status` qoidasini buzmaydi (tasdiq, rad, 404);
  * samarali rollar: admin paneldan olingan ADMIN darhol va eski `ct_`
    taklifiga ham ta'sir qiladi; Keycloak `ADMIN` (ishonilmagan) botda ham
    o'tmaydi; `ADMIN_LOGINS` dagi SSO odam botda ham muharrir;
  * `/api/health/detail`: faqat SAMARALI ADMIN, ichida SSO `login` bloki va
    prod'ning `conflicts_10min` hisobi;
  * admin paneldagi bot rejimi botning o'zidan (prod'ning `webhook` i ham).

Tarmoqqa chiqilmaydi: Keycloak, HRM, Telegram va yordamchi - soxta.
"""

from __future__ import annotations

import json
import re

from types import SimpleNamespace

import pytest

import app.bot as bot_module
from app.api.deps import get_directory
from app.api.v1 import chat as chat_api
from app.bot.runner import _BLOCKED, Backend, VeneraBot
from app.core.config import settings
from app.services import analytics
from app.services import telegram_links as links_module
from app.services.integrations.assistant import AnswerStream, AssistantError
from app.services.telegram_links import LinkStore
from tests.test_contacts import people  # noqa: F401 - fikstura
from tests.test_integration_merge import (
    EDIT_Q,
    PERSON_Q,
    PHONE,
    _frames,
    _no_assistant,
    _sso_login,
    real_directory,  # noqa: F401 - fikstura
    telegram_api,  # noqa: F401 - fikstura
)
from tests.test_pro import PRO_BLOCK, api, assistant, server  # noqa: F401 - fikstura
from tests.test_sso_login import hub, net  # noqa: F401 - fikstura
from tests.test_telegram_bot import TG_ID, WEBHOOK_URL, _conflict, callback, text_update

TURN = re.compile(r"[0-9a-f]{32}")
#: `people` dagi boshqa to'qima odam - ikkinchi tahrir uchun.
EDIT_Q2 = "Isroilov Botirning telefonini +998901110000 ga o'zgartir"
#: Ma'lumotnomaga TEGMAYDIGAN savol - yordamchiga ketadi.
ASSIST_Q = "Yillik ta'til necha kun?"


@pytest.fixture
def db(_isolated_analytics):
    return _isolated_analytics


def rows(db, sql: str, params=()) -> list[dict]:
    analytics.flush()
    return db.rows(sql, params)


def event_names(db, turn_id: str) -> list[str]:
    return [e["name"] for e in rows(db, "SELECT name FROM turn_events WHERE turn_id=? ORDER BY seq",
                                    (turn_id,))]


def status_of(db, token: str) -> str | None:
    found = rows(db, "SELECT proposal_status FROM turns WHERE proposal_token=?", (token,))
    assert len(found) == 1, found
    return found[0]["proposal_status"]


def make_bot(telegram_api, directory) -> VeneraBot:
    return VeneraBot(telegram_api, bot_module.links, users=directory, backend=Backend(),
                     inline=True, typing_every=None)


def card_token(telegram_api) -> str:
    """Botning oxirgi taklif kartasidagi "Tasdiqlash" tugmasi kaliti."""
    for _, kw in reversed(telegram_api.calls):
        markup = kw.get("reply_markup")
        if not markup:
            continue
        for row in markup.get("inline_keyboard", []):
            for button in row:
                data = str(button.get("callback_data") or "")
                if data.startswith("a:c:"):
                    return data[4:]
    raise AssertionError("taklif kartasi yo'q")


class ProposalAssistant:
    """Yordamchi o'rnida: har savolga TAKLIF (kalit ketma-ket) va amallar
    natijasi. `results[token]` - lug'at yoki `AssistantError`."""

    configured = True

    def __init__(self) -> None:
        self.n = 0
        self.asked: list[dict] = []
        self.actions: list[tuple[str, str]] = []
        self.results: dict[str, object] = {}

    def stream(self, question, *, user_id, chat_id=None, tokens=None, max_chars=2000,
               mode="standard", **_):
        self.n += 1
        token = f"{self.n:x}" * 32
        token = token[:32]
        self.asked.append({"question": question, "mode": mode, "token": token})
        lines = [
            {"type": "token", "text": "Tasdiqlang."},
            {"type": "proposal", "proposal": {
                "token": token, "connector": "crm", "summary": "Yangi task",
                "target": {"kind": "new_issue", "key": None, "project": "DVSIB", "summary": "X"},
                "changes": [], "warnings": []}},
            {"type": "done", "route": "crm", "request_id": f"r-{self.n}"},
        ]
        return AnswerStream(request_id=f"r-{self.n}",
                            frames=iter(json.dumps(x).encode() + b"\n" for x in lines))

    def _act(self, verb, token):
        self.actions.append((verb, token))
        result = self.results.get(token, {"token": token, "status": "executed", "ok": True}
                                  if verb == "confirm" else {"token": token, "status": "cancelled"})
        if isinstance(result, BaseException):
            raise result
        return result

    def confirm_action(self, token, *, user_id, tokens=None):
        return self._act("confirm", token)

    def cancel_action(self, token, *, user_id, tokens=None):
        return self._act("cancel", token)

    def get_action(self, token):
        return {"token": token, "status": "pending"}


@pytest.fixture
def proposer(monkeypatch):
    fake = ProposalAssistant()
    monkeypatch.setattr(chat_api, "_assistant", fake)
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {})
    return fake


# --- kanal: ma'lumotnoma javobi ham to'g'ri kanal bilan -----------------------------


@pytest.mark.parametrize(("headers", "channel"), [
    ({"X-Venera-Client": "web"}, "web"),
    ({"X-Venera-Client": "miniapp"}, "miniapp"),
    # Eski mini app build (sarlavhasiz) - sahifa `/tg/` ostida.
    ({"Referer": "https://llm.brb-tech.uz/tg/index.html"}, "miniapp"),
    ({}, "api"),
    # `bot` sarlavha orqali QABUL QILINMAYDI - statistikani soxtalashtirmasin.
    ({"X-Venera-Client": "bot"}, "api"),
])
def test_kontakt_javobi_kanali_sarlavhadan(client, auth, people, db, monkeypatch, headers, channel):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    r = client.post("/api/v1/chat/stream", headers={**auth, **headers},
                    json={"question": PERSON_Q})
    assert r.status_code == 200 and PHONE in r.text, r.text
    [turn] = rows(db, "SELECT * FROM turns")
    assert turn["id"] == r.headers["X-Venera-Turn"]
    assert (turn["channel"], turn["kind"], turn["route"], turn["status"]) == (
        channel, "chat", "contacts", "ok")
    # Kontakt javobi yordamchiga bormaydi - hisobda ham yordamchi chaqiruvi yo'q.
    assert rows(db, "SELECT * FROM api_calls WHERE service='assistant'") == []


def test_kontakt_javobida_kutish_rejasi_boshlanmaydi(api, auth, server, people, db, monkeypatch):
    """Prod tartibi: ma'lumotnoma AVVAL, kutish rejasi (tasnif) faqat savol
    yordamchiga ketishi aniq bo'lganda (`before_upstream`). Redesign esa
    tasnifni izga yozadi (`hold.classify`) - shu bilan tartib ko'rinadi."""
    monkeypatch.setattr(settings, "hold_enabled", True)
    voice = {"voice": True, "locale": "uz"}

    r = api.post("/api/v1/chat/stream", headers=auth, json={"question": PERSON_Q, **voice})
    assert r.status_code == 200 and PHONE in r.text
    contact_turn = r.headers["X-Venera-Turn"]
    assert server.calls == []

    r = api.post("/api/v1/chat/stream", headers=auth, json={"question": ASSIST_Q, **voice})
    assert r.status_code == 200 and len(server.calls) == 1
    assistant_turn = r.headers["X-Venera-Turn"]

    assert "hold.classify" not in event_names(db, contact_turn)
    names = event_names(db, assistant_turn)
    assert "hold.classify" in names
    # Tasnif ulanishdan OLDIN boshlanadi (parallel) - izda ham shu tartib.
    assert names.index("hold.classify") < names.index("assistant.open")
    [turn] = rows(db, "SELECT input_mode FROM turns WHERE id=?", (contact_turn,))
    assert turn["input_mode"] == "voice"


# --- bot: `open_stream` -> `bot` kanali, hisob, blok --------------------------------


def test_bot_yordamchi_savoli_bot_kanali_va_hisob_bilan(
    api, server, client, hub, net, people, telegram_api, real_directory, db,
):
    actor, _ = _sso_login(client)
    bot_module.links.link(TG_ID, actor)
    bot = make_bot(telegram_api, real_directory)
    bot.handle_update(text_update(ASSIST_Q))
    assert "Javob" in telegram_api.texts()[-1]
    # Bot "Pro" so'ramaydi - rejim faqat veb klientdan keladi.
    assert "mode" not in server.calls[-1]["body"]

    [turn] = rows(db, "SELECT * FROM turns WHERE channel='bot'")
    assert (turn["kind"], turn["route"], turn["status"], turn["actor_id"]) == (
        "bot", "rules", "ok", actor)
    assert turn["request_id"] == "served-pro"
    names = event_names(db, turn["id"])
    assert "assistant.open" in names and "telegram.deliver" in names and "done" in names
    # Tashqi chaqiruv hisobi shu savolga, shu odamga va `bot` kanaliga bog'langan.
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    assert (call["op"], call["status"], call["channel"], call["actor_id"], call["turn_id"]) == (
        "stream", "ok", "bot", actor, turn["id"])


def test_bloklangan_odam_ulanish_muddatini_uzaytirmaydi_blok_olinsa_davom_etadi(
    client, auth, hub, net, people, telegram_api, real_directory, db, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, _ = _sso_login(client)
    bot_module.links.link(TG_ID, actor)
    seen = bot_module.links.lookup(TG_ID)[0].seen_at
    r = client.patch(f"/api/v1/admin/users/{actor}", headers=auth, json={"disabled": True})
    assert r.status_code == 200, r.text

    # Bir soatdan keyin yozadi - bloklangan: rad, muddat JOYIDA qoladi.
    later = seen + 3600
    # Faqat ulanishlar omborining soati - global `time.time` ga tegilmaydi.
    monkeypatch.setattr(links_module, "time", SimpleNamespace(time=lambda: later))
    bot = make_bot(telegram_api, real_directory)
    bot.handle_update(text_update(PERSON_Q))
    assert telegram_api.texts()[-1] == _BLOCKED
    link, state = bot_module.links.lookup(TG_ID)
    assert state == "linked" and link.seen_at == seen, "blok muddatni uzaytirmasligi kerak"

    # Blok olindi - mini app'ni qayta ochmasdan davom etadi, muddat yangilanadi.
    r = client.patch(f"/api/v1/admin/users/{actor}", headers=auth, json={"disabled": False})
    assert r.status_code == 200, r.text
    bot.handle_update(text_update(PERSON_Q, message_id=11))
    assert PHONE in telegram_api.texts()[-1]
    assert bot_module.links.lookup(TG_ID)[0].seen_at == later
    [turn] = rows(db, "SELECT * FROM turns WHERE channel='bot'")
    assert (turn["route"], turn["actor_id"]) == ("contacts", actor)


# --- "Pro": kanal, ochilmagan oqim, byudjet hisobi -----------------------------------


def test_pro_mini_appdan_va_ochilmagan_oqim_izda(api, auth, server, db):
    miniapp = {**auth, "X-Venera-Client": "miniapp"}
    r = api.post("/api/v1/chat/stream", headers=miniapp,
                 json={"question": ASSIST_Q, "mode": "pro"})
    assert r.status_code == 200 and server.calls[-1]["body"]["mode"] == "pro"
    [turn] = rows(db, "SELECT * FROM turns")
    assert (turn["channel"], turn["status"]) == ("miniapp", "ok")
    names = event_names(db, turn["id"])
    assert "pro.requested" in names and "pro" in names

    # Yuqoridagi xizmat ochilmadi (503): savol baribir izda - "Pro" so'ralgani,
    # `upstream_busy` (xizmatning O'ZI band - bizning navbat emas) va savol
    # kaliti javob sarlavhasida (shikoyat uchun).
    server.status = 503
    r = api.post("/api/v1/chat/stream", headers=miniapp,
                 json={"question": "Ikkinchi savol", "mode": "pro"})
    assert r.status_code == 503, r.text
    failed = r.headers["X-Venera-Turn"]
    assert TURN.fullmatch(failed)
    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (failed,))
    assert (turn["status"], turn["error_code"], turn["http_status"], turn["channel"]) == (
        "error", "upstream_busy", 503, "miniapp")
    names = event_names(db, failed)
    assert "pro.requested" in names and "pro" not in names
    assert server.calls[-1]["body"]["mode"] == "pro"


def test_pro_byudjeti_hisobda_kanali_bilan(api, auth, server, db):
    r = api.get("/api/v1/pro/quota", headers={**auth, "X-Venera-Client": "miniapp"})
    assert r.status_code == 200, r.text
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    assert (call["op"], call["status"], call["channel"], call["actor_id"]) == (
        "pro.quota", "ok", "miniapp", 1)


# --- taklif holati: `ct_` amallari yordamchi qoidasini buzmaydi ------------------------


def test_web_ct_amallari_yordamchi_taklif_holatiga_tegmaydi(
    client, auth, people, proposer, db,
):
    # Ma'lumotnoma taklifi (ct_) va yordamchi taklifi - bitta sessiyada.
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": EDIT_Q})
    ct = next(f["proposal"]["token"] for f in _frames(r.text) if f["type"] == "proposal")
    assert ct.startswith("ct_") and proposer.asked == []
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": ASSIST_Q})
    token = next(f["proposal"]["token"] for f in _frames(r.text) if f["type"] == "proposal")
    assert status_of(db, ct) == "pending" and status_of(db, token) == "pending"

    # ct_ tasdiq: Venera'ning o'zida bajariladi, yordamchiga bormaydi, holat
    # yozilmaydi; ikkinchi bosish - 404, lekin "muddati o'tgan" ham YOZILMAYDI.
    r = client.post(f"/api/v1/actions/{ct}/confirm", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert client.post(f"/api/v1/actions/{ct}/confirm", headers=auth).status_code == 404
    assert proposer.actions == []
    assert status_of(db, ct) == "pending"
    assert status_of(db, token) == "pending"

    # Yordamchi taklifi o'z qoidasi bilan: tasdiq -> `executed`.
    r = client.post(f"/api/v1/actions/{token}/confirm", headers=auth)
    assert r.status_code == 200, r.text
    assert proposer.actions == [("confirm", token)]
    assert status_of(db, token) == "executed" and status_of(db, ct) == "pending"

    # Rad etish va 404 (yordamchi tanimadi) -> `cancelled` / `expired`.
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": "Yana task"})
    second = next(f["proposal"]["token"] for f in _frames(r.text) if f["type"] == "proposal")
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": "Uchinchi task"})
    third = next(f["proposal"]["token"] for f in _frames(r.text) if f["type"] == "proposal")
    assert client.post(f"/api/v1/actions/{second}/cancel", headers=auth).status_code == 200
    proposer.results[third] = AssistantError("yo'q", status=404)
    assert client.post(f"/api/v1/actions/{third}/confirm", headers=auth).status_code == 404
    assert (status_of(db, second), status_of(db, third)) == ("cancelled", "expired")

    # ct_ rad etish ham holatga tegmaydi.
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": EDIT_Q2})
    ct2 = next(f["proposal"]["token"] for f in _frames(r.text) if f["type"] == "proposal")
    r = client.post(f"/api/v1/actions/{ct2}/cancel", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert status_of(db, ct2) == "pending"


def test_bot_ct_amallari_yordamchi_taklif_holatiga_tegmaydi(
    client, auth, people, proposer, telegram_api, real_directory, db,
):
    bot_module.links.link(TG_ID, 1)          # users.yaml dagi ADMIN - muharrir
    bot = make_bot(telegram_api, real_directory)

    bot.handle_update(text_update(EDIT_Q))
    ct = card_token(telegram_api)
    assert ct.startswith("ct_") and proposer.asked == []
    bot.handle_update(text_update(ASSIST_Q, message_id=11))
    token = card_token(telegram_api)
    assert not token.startswith("ct_")
    turns = rows(db, "SELECT channel, route, proposal_status FROM turns ORDER BY started_at")
    assert [(t["channel"], t["route"]) for t in turns] == [("bot", "contacts"), ("bot", "crm")]

    # ct_: tasdiq bajariladi, ikkinchi bosish 404 - holat baribir `pending`.
    bot.handle_update(callback(f"a:c:{ct}", message_id=50))
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998901234567"
    bot.handle_update(callback(f"a:c:{ct}", message_id=50))
    assert status_of(db, ct) == "pending"
    assert proposer.actions == []

    # Yordamchi taklifi: tasdiq -> `executed`; boshqasi 404 -> `expired`.
    bot.handle_update(callback(f"a:c:{token}", message_id=51))
    assert proposer.actions == [("confirm", token)]
    assert status_of(db, token) == "executed"
    bot.handle_update(text_update("Yana task", message_id=12))
    other = card_token(telegram_api)
    proposer.results[other] = AssistantError("yo'q", status=404)
    bot.handle_update(callback(f"a:c:{other}", message_id=52))
    assert status_of(db, other) == "expired" and status_of(db, ct) == "pending"


# --- samarali rollar: admin panel, Keycloak ADMIN, ADMIN_LOGINS --------------------------


def test_admin_roli_olinsa_eski_ct_taklifi_ham_bajarilmaydi(
    client, auth, hub, net, people, monkeypatch,
):
    """Rol TASDIQ paytida qayta tekshiriladi (`contacts_chat.act`) - va u endi
    SAMARALI rol: admin paneldan olingan ADMIN shu sessiyada darhol ishlamaydi."""
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, headers = _sso_login(client)
    r = client.patch(f"/api/v1/admin/users/{actor}", headers=auth,
                     json={"roles": ["employee", "crm-user", "ADMIN"]})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    ct = next(f["proposal"]["token"] for f in _frames(r.text) if f["type"] == "proposal")

    r = client.patch(f"/api/v1/admin/users/{actor}", headers=auth,
                     json={"roles": ["employee", "crm-user"]})
    assert r.status_code == 200 and "ADMIN" not in r.json()["roles"], r.text
    r = client.post(f"/api/v1/actions/{ct}/confirm", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "failed", r.text
    assert people.find("Nazarova Dilnoza")[0][0].phone == PHONE
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    assert "faqat administrator" in r.text and '"proposal"' not in r.text


def test_keycloak_admin_ishonilmasa_botda_ham_tahrir_yoq(
    client, hub, net, people, telegram_api, real_directory, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    net.roles = net.roles + ["ADMIN"]
    actor, headers = _sso_login(client)
    assert "ADMIN" not in client.get("/api/v1/auth/me", headers=headers).json()["roles"]
    bot_module.links.link(TG_ID, actor)
    bot = make_bot(telegram_api, real_directory)
    bot.handle_update(text_update(EDIT_Q))
    assert "faqat administrator" in telegram_api.texts()[-1]

    # Ishonilgan rollar ro'yxatida bo'lsa - botda ham muharrir.
    monkeypatch.setattr(settings, "sso_trusted_roles", "ADMIN")
    bot.handle_update(text_update(EDIT_Q, message_id=11))
    assert card_token(telegram_api).startswith("ct_")


def test_admin_logins_sso_odam_botda_ham_muharrir(
    client, hub, net, people, telegram_api, real_directory, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, _ = _sso_login(client)
    bot_module.links.link(TG_ID, actor)
    bot = make_bot(telegram_api, real_directory)
    bot.handle_update(text_update(EDIT_Q))
    assert "faqat administrator" in telegram_api.texts()[-1]

    # SSO hisobi LOGINI bilan (email emas) - bot ham loginni beradi.
    monkeypatch.setattr(settings, "admin_logins", "y.mamajonov")
    bot.handle_update(text_update(EDIT_Q, message_id=11))
    ct = card_token(telegram_api)
    bot.handle_update(callback(f"a:c:{ct}", message_id=60))
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998901234567"


# --- /api/health/detail: samarali ADMIN, SSO bloki va conflicts --------------------------


def test_health_detail_faqat_samarali_admin_sso_va_conflicts_bilan(
    client, auth, user_auth, hub, net, telegram_api, tmp_path, monkeypatch,
):
    actor, headers = _sso_login(client)
    bot = VeneraBot(telegram_api, LinkStore(tmp_path / "l.json"), users=get_directory,
                    inline=True, typing_every=None)
    bot.poll_error(_conflict(), 1.0)
    bot.poll_error(_conflict(), 1.0)
    monkeypatch.setattr(settings, "telegram_bot_enabled", True)
    monkeypatch.setattr(bot_module, "_bot", bot)

    assert client.get("/api/health/detail").status_code == 401
    assert client.get("/api/health/detail", headers=user_auth).status_code == 403
    assert client.get("/api/health/detail", headers=headers).status_code == 403

    # Admin paneldan ADMIN - o'sha SSO sessiya qayta kirmasdan ko'radi.
    r = client.patch(f"/api/v1/admin/users/{actor}", headers=auth,
                     json={"roles": ["employee", "crm-user", "ADMIN"]})
    assert r.status_code == 200, r.text
    r = client.get("/api/health/detail", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["login"] == {"sso": True, "local": True, "identities": 1}
    assert body["telegram"]["conflicts_10min"] == 2
    assert any("boshqa nusxa" in w and "2 marta" in w for w in body["warnings"]), body["warnings"]

    # Rol olindi - yana 403.
    client.patch(f"/api/v1/admin/users/{actor}", headers=auth,
                 json={"roles": ["employee", "crm-user"]})
    assert client.get("/api/health/detail", headers=headers).status_code == 403


# --- admin panel: botning HAQIQIY rejimi (prod webhook + redesign tizim sahifasi) --------


def test_admin_tizim_bot_rejimini_botning_ozidan_oladi(
    client, auth, telegram_api, tmp_path, monkeypatch,
):
    """Redesign tizim sahifasi "bot faqat polling" deb qotirgan edi; prod'da esa
    webhook rejimi va undan `polling` ga o'zi qaytish bor."""
    bot = VeneraBot(telegram_api, LinkStore(tmp_path / "l.json"), users=get_directory,
                    inline=True, typing_every=None, mode="webhook",
                    webhook_url=WEBHOOK_URL, webhook_secret="s" * 64)
    monkeypatch.setattr(settings, "telegram_bot_enabled", True)
    monkeypatch.setattr(bot_module, "_bot", bot)

    def mode() -> str:
        r = client.get("/api/v1/admin/system", headers=auth)
        assert r.status_code == 200, r.text
        return r.json()["config"]["telegramMode"]

    assert mode() == "webhook"
    # Webhook'ga yetib bora olmadi - bot `polling` ga qaytdi: panel ham shuni aytadi.
    bot.mode = "polling"
    assert mode() == "polling"
    # Bot hali ishga tushmagan (holatda rejim yo'q) - zaxira `polling`.
    monkeypatch.setattr(bot_module, "_bot", None)
    assert mode() == "polling"
    monkeypatch.setattr(settings, "telegram_bot_enabled", False)
    assert mode() == "off"

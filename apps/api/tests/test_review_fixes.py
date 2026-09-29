"""Backend tekshiruvida topilgan nosozliklar - har biriga regressiya testi.

  1. Kunlik/soatlik guruhlar ORALIQ BOSHIDAN (mahalliy yarim tun) kesiladi,
     UTC yarim tunidan emas (`queries.grid_origin`).
  2. `admin_logins`: SSO hisobi faqat LOGINI bilan - Keycloak emaili (odam uni
     o'zi o'zgartira oladi) ADMIN bermaydi (`admin_users.is_bootstrap`).
  3. `Database.transaction`: COMMIT yiqilsa tranzaksiya ochiq qolmaydi.
  4. Shikoyat: begona suhbat kaliti (`chatId`) saqlanmaydi; surat bir
     o'tishda qisqartiriladi (O(n²) emas).
  5. Testlar STT/TTS `/health` iga jonli tarmoq orqali chiqmaydi.

Hammasi OFLAYN, ombor har testda vaqtinchalik (`conftest.py`).
"""

from __future__ import annotations

import json
import sqlite3

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.schemas.auth import AuthUser
from app.services import admin_users
from app.services.analytics import get_db, queries
from tests.test_reports import (  # noqa: F401 - fiksturalar
    DEMO, OTHER, _fresh_limiter, _post, _row, _turn, demo, upstream,
)

H = 3600.0
D = 86400.0


def _ts(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def _iso(ts: float) -> str:
    return queries.iso(ts)


# --- 1. guruhlar mahalliy kundan ------------------------------------------------------------

#: Toshkent (UTC+5) 20-sentabr yarim tuni = 19-sentabr 19:00 UTC. Brauzer
#: `from` ni aynan shunday yuboradi (`useAdminFilters.toRangeParams`).
LOCAL_MIDNIGHT = _ts("2026-09-19T19:00:00Z")


def _insert_turn(db, key: str, started_at: float, channel: str = "web") -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO turns (id, started_at, actor_id, channel, kind, question, status, "
            "ttft_ms, total_ms) VALUES (?,?,?,?,?,?,?,?,?)",
            (key, started_at, 7, channel, "chat", "savol", "ok", 900, 3000))


def _insert_call(db, ts: float, service: str = "tts") -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO api_calls (ts, service, op, status, duration_ms, channel) "
            "VALUES (?,?,?,?,?,?)", (ts, service, "speak", "ok", 100, "web"))


def test_kunlik_guruh_mahalliy_yarim_tundan_boshlanadi():
    db = get_db()
    # Mahalliy 20-sentabr 00:30 va 23:30, 21-sentabr 01:00 (UTC da 20-sentabr 20:00 -
    # UTC bo'yicha kesilsa u 20-sentabrga, ya'ni NOTO'G'RI kunga tushardi).
    _insert_turn(db, "a" * 32, LOCAL_MIDNIGHT + 0.5 * H)
    _insert_turn(db, "b" * 32, LOCAL_MIDNIGHT + 23.5 * H)
    _insert_turn(db, "c" * 32, LOCAL_MIDNIGHT + 25 * H)
    for ts in (LOCAL_MIDNIGHT + 0.5 * H, LOCAL_MIDNIGHT + 25 * H):
        _insert_call(db, ts)

    start, end = LOCAL_MIDNIGHT, LOCAL_MIDNIGHT + 3 * D
    body = queries.overview(db, start=start, end=end)
    assert body["range"]["bucket"] == "day"
    # Uch mahalliy kun - uchta ustun (UTC bo'yicha kesilganda 4 ta chala ustun edi).
    assert [p["t"] for p in body["activity"]] == [_iso(start), _iso(start + D), _iso(start + 2 * D)]
    assert [p["web"] for p in body["activity"]] == [2, 1, 0]
    assert [p["t"] for p in body["latency"]] == [p["t"] for p in body["activity"]]

    usage = queries.usage(db, start=start, end=end)
    assert [p["t"] for p in usage["series"]["points"]] == [p["t"] for p in body["activity"]]
    assert [p["tts"] for p in usage["series"]["points"]] == [1, 1, 0]


def test_oraliq_boshi_ixtiyoriy_lahza_bolsa_utc_chegaralari():
    """`from` berilmagan ("hozirdan 7 kun oldin", sekundlari bilan) - odatdagi
    UTC soat/kun boshlari, g'alati 10:37:12 chegaralar emas."""
    start = _ts("2026-09-20T10:37:12.345Z")
    starts = queries.bucket_starts(start, start + 3 * D, "day")
    assert starts[0] == _ts("2026-09-20T00:00:00Z") and len(starts) == 4
    hours = queries.bucket_starts(start, start + 2 * H, "hour")
    assert hours == [_ts("2026-09-20T10:00:00Z"), _ts("2026-09-20T11:00:00Z"),
                     _ts("2026-09-20T12:00:00Z")]
    # Yarim soatli mintaqa (+05:30) - soatlar ham mahalliy soat boshidan.
    india = _ts("2026-09-19T18:30:00Z")
    assert queries.bucket_starts(india, india + 2 * H, "hour") == [india, india + H]


# --- 2. admin_logins: SSO faqat login bilan --------------------------------------------------


@pytest.fixture
def bootstrap(monkeypatch):
    def set_logins(value: str) -> None:
        monkeypatch.setattr(settings, "admin_logins", value, raising=False)

    return set_logins


def test_sso_emaili_admin_logins_bermaydi(bootstrap):
    """Ro'yxatdagi email hali hech kimning SSO hisobida bo'lmasa (masalan faqat
    `users.yaml` dagi zahira admin), xodim Keycloak'da emailini shunga
    o'zgartirib ADMIN bo'lib olardi - va blokdan ham o'tib ketardi."""
    bootstrap("boss@venera.uz, y.mamajonov")
    intruder = AuthUser(actorId=40, email="Boss@venera.uz", fullName="X", roles=["employee"])
    assert "ADMIN" not in admin_users.effective(intruder, login="x.xodimov").roles
    assert admin_users.is_bootstrap(intruder.email, "x.xodimov") is False
    # SSO login esa ishlaydi.
    real = AuthUser(actorId=41, email="yusuf@brb-tech.uz", fullName="Y", roles=["employee"])
    assert "ADMIN" in admin_users.effective(real, login="Y.Mamajonov").roles
    # Zahira hisob (`users.yaml`, login yo'q) - email loginning o'zi: ishlaydi.
    local = AuthUser(actorId=42, email="boss@venera.uz", fullName="B", roles=["USER"])
    assert "ADMIN" in admin_users.effective(local).roles


def test_sso_emaili_blokdan_ham_otkazmaydi(bootstrap):
    bootstrap("boss@venera.uz")
    db = get_db()
    with db.transaction() as conn:
        conn.execute("INSERT INTO user_admin (actor_id, disabled) VALUES (40, 1)")
    intruder = AuthUser(actorId=40, email="boss@venera.uz", fullName="X", roles=[])
    assert admin_users.access(intruder, login="x.xodimov").blocked is True
    # Panelda ham xuddi shunday: SSO odam - `rolesLocked` emas.
    person = admin_users.Person(actor_id=40, email="boss@venera.uz", sso=True,
                                sso_login="x.xodimov")
    assert person.bootstrap is False
    assert admin_users.Person(actor_id=42, email="boss@venera.uz", local=True).bootstrap is True


# --- 3. COMMIT yiqilsa ------------------------------------------------------------------------


class _CommitFails:
    """Haqiqiy ulanish ustidagi qobiq: faqat COMMIT xato beradi (disk to'la)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, *args):
        if sql.strip().upper() == "COMMIT":
            raise sqlite3.OperationalError("database or disk is full")
        return self._conn.execute(sql, *args)

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction


def test_commit_yiqilsa_tranzaksiya_ochiq_qolmaydi():
    db = get_db()
    real = db.connect()
    db.connect = lambda: _CommitFails(real)                  # faqat shu nusxada
    try:
        with pytest.raises(sqlite3.OperationalError):
            with db.transaction() as conn:
                conn.execute("INSERT INTO audit_log (ts, action) VALUES (1, 'x')")
    finally:
        del db.connect
    # Ulanish shu ipda qayta ishlatiladi: tranzaksiya ochiq qolsa yozuv qulfi
    # ushlanib turar va keyingi `BEGIN` "within a transaction" bilan yiqilardi.
    assert real.in_transaction is False
    assert db.scalar("SELECT COUNT(*) FROM audit_log") == 0
    with db.transaction() as conn:
        conn.execute("INSERT INTO audit_log (ts, action) VALUES (2, 'y')")
    assert db.scalar("SELECT COUNT(*) FROM audit_log") == 1


# --- 4. shikoyat: begona suhbat kaliti ---------------------------------------------------------


def test_begona_suhbat_kaliti_saqlanmaydi(client, demo, upstream):
    _turn(OTHER, "Maxfiy savol", "Maxfiy javob", chat="admin-chat")
    response = _post(client, demo, {"chatId": "admin-chat", "reason": "wrong",
                                    "messages": [{"role": "user", "content": "mening savolim"}]})
    assert response.status_code == 201, response.text
    row = _row(response.json()["id"])
    # Kalit saqlansa, admin panelda ADMIN ning suhbati "xabar berilgan" bo'lib
    # ko'rinar va uning izida bu shikoyat chiqardi.
    assert row["chat_id"] is None and row["turn_id"] is None
    assert row["snapshot"]["source"] == "client"
    assert "Maxfiy" not in json.dumps(row["snapshot"], ensure_ascii=False)
    assert upstream.calls == []
    reported = get_db().rows("SELECT id FROM turns WHERE chat_id = 'admin-chat'")
    detail = queries.turn_detail(get_db(), reported[0]["id"])
    assert detail["reported"] is False and detail["reports"] == []


def test_begona_kalit_bilan_oz_savoli_oz_suhbatiga_bogdanadi(client, demo, upstream):
    _turn(OTHER, "Maxfiy savol", "Maxfiy javob", chat="admin-chat")
    own = _turn(DEMO, "Mening savolim", "Javob", chat="demo-chat")
    response = _post(client, demo, {"chatId": "admin-chat", "turnId": own})
    row = _row(response.json()["id"])
    assert (row["chat_id"], row["turn_id"], row["snapshot"]["source"]) == ("demo-chat", own,
                                                                           "telemetry")
    assert "Maxfiy" not in json.dumps(row["snapshot"], ensure_ascii=False)


def test_telemetriyasiz_suhbat_kaliti_qoladi(client, demo, upstream):
    """Faqat IJOBIY dalil bilan tashlanadi: telemetriyada umuman yo'q suhbat
    (analitikadan oldingi) - odamniki deb qabul qilinadi."""
    upstream.reply = RuntimeError("yiqildi")
    response = _post(client, demo, {"chatId": "eski-suhbat",
                                    "messages": [{"role": "user", "content": "x"}]})
    assert _row(response.json()["id"])["chat_id"] == "eski-suhbat"


def test_surat_bir_otishda_qisqartiriladi(monkeypatch):
    """`_fit` har tashlashdan keyin butun suratni qayta yozardi (O(n²)): 200 ta
    uzun xabarda ~1.2 s GIL ushlab turilardi. Endi yozilgan jami hajm suratning
    o'zidan bir necha barobar ko'p emas - va natija AYNAN eskisidek."""
    from app.services import reports

    monkeypatch.setattr(reports, "SNAPSHOT_BYTES", 50_000)
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": "Ш" * 1000 + str(i),
                 "createdAt": None, "turnId": None, "sources": None} for i in range(200)]
    whole = len(json.dumps({"source": "client", "messages": messages}, ensure_ascii=False))

    written = []
    real_dumps = json.dumps

    def counting(value, *args, **kwargs):
        out = real_dumps(value, *args, **kwargs)
        written.append(len(out))
        return out

    monkeypatch.setattr(reports.json, "dumps", counting)
    text = reports._fit({"source": "client", "messages": [dict(m) for m in messages]})
    monkeypatch.setattr(reports.json, "dumps", real_dumps)

    assert sum(written) <= 3 * whole                      # eski yo'l: ~50 barobar
    fitted = json.loads(text)
    assert len(text.encode("utf-8")) <= 50_000 and fitted["truncated"] is True
    assert fitted["messages"][0]["role"] == "user"
    assert fitted["messages"][-1]["content"].endswith("199")
    # Eng ko'p xabar qoldi: yana ikkitasi sig'masdi.
    kept = len(fitted["messages"])
    bigger = json.dumps({"source": "client", "messages": messages[-(kept + 2):], "truncated": True},
                        ensure_ascii=False, separators=(",", ":"))
    assert len(bigger.encode("utf-8")) > 50_000


# --- 5. testlar oflayn -------------------------------------------------------------------------


def test_health_tekshiruvi_tarmoqqa_chiqmaydi(client, auth, monkeypatch):
    import urllib.request

    def forbidden(*args, **kwargs):
        raise AssertionError("test jonli tarmoqqa chiqdi")

    monkeypatch.setattr(urllib.request, "build_opener", forbidden)
    assert client.get("/health").status_code == 200
    assert client.get("/api/health/detail", headers=auth).status_code == 200

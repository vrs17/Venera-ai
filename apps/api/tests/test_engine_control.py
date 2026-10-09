"""Dvigatelni (yordamchi versiyasini) admin panel boshqaradi.

Tekshiriladi (`services/engine_control.py`):

  * tanlov tartibi - har bo'g'in alohida: klient tanlovi (faqat ruxsat
    bo'lsa), odamning default'i / yagona versiyasi, kanal siyosati, umumiy
    siyosat, `.env`, kod default'i;
  * kesh: admin yozuvi DARHOL ko'rinadi, chetdan yozilgani - 5 soniyada;
  * ombor nosoz bo'lsa - `.env`, xato yo'q;
  * web, Mini App, bot, `/chat/ask` va `/pro/quota` BITTA qoidadan;
  * admin API: shakllar, tekshiruv (422/404), USER uchun 403, audit;
  * `AdminUserDetail.engine`, sxema v3 migratsiyasi, izdagi dvigatel.

Tarmoqqa chiqilmaydi: yordamchi soxta (`build_opener`), ombor vaqtinchalik.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request

import pytest

from app.core.config import settings
from app.schemas.auth import AuthUser
from app.services import analytics
from app.services import engine_control as control
from app.services.analytics.db import MIGRATIONS, SCHEMA_VERSION, Database
from app.services.integrations.assistant import AssistantClient, AssistantError

BASE = "http://assistant.test"
STREAM_PATH = re.compile(r"/api/(?:(v[123])/)?chat/stream")
QUOTA = {"remaining": {"day": 9, "week": 19, "month": 49},
         "limits": {"day": 10, "week": 20, "month": 50},
         "used": {"day": 1, "week": 1, "month": 1}}
DEMO_ID = 2          # conftest: demo@venera.uz, faqat USER
ADMIN_ID = 1         # conftest: admin@venera.uz

# types.ts shartnomasi (frontend aynan shularga quriladi)
ADMIN_ENGINES_FIELDS = {"catalog", "policy", "envDefaults", "effective", "stats", "access"}
POLICY_FIELDS = {"default", "channels", "source", "updatedAt", "updatedBy"}
ACCESS_ROW_FIELDS = {"actorId", "name", "login", "engines", "defaultEngine", "note",
                     "updatedAt", "updatedBy"}
USAGE_FIELDS = {"engine", "turns", "errors", "medianTtftMs", "users"}
CHOICE_FIELDS = {"current", "selectable", "available", "catalog"}
CATALOG = [{"id": "v1", "pro": False, "law": False}, {"id": "v2", "pro": True, "law": True},
           {"id": "v3", "pro": True, "law": True}]
ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


# ================================================================ soxta yordamchi


def frame(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False).encode("utf-8") + b"\n"


class _Response:
    def __init__(self, lines) -> None:
        self._lines = list(lines)
        self.headers = {"X-Request-Id": "served"}
        self.status = 200

    def readline(self, limit: int = -1) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def read(self, size: int = -1) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def close(self) -> None:
        return None


class Upstream:
    """Soxta yordamchi: oqim (`/api[/vN]/chat/stream`) va "Pro" byudjeti."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def open(self, request, timeout=None):
        parts = urllib.parse.urlsplit(request.full_url)
        body = json.loads(request.data) if request.data else None
        self.calls.append({"path": parts.path, "body": body})
        if parts.path == "/api/pro/quota":
            return _Response([json.dumps(QUOTA).encode()])
        found = STREAM_PATH.fullmatch(parts.path)
        if found is None:
            raise AssertionError(f"kutilmagan yo'l: {parts.path}")
        done = {"type": "done", "route": "rules", "request_id": "r-1"}
        if found.group(1):
            done["engine"] = found.group(1)
        if found.group(1) == "v3":
            # "Venera Core": agent izi kaliti va vazifa holati (`meta` ichida).
            done["meta"] = {"trace_id": "tr-1", "task": {"intent": "crm.create_issue",
                                                         "state": "awaiting_confirm"}}
        return _Response([frame(type="token", text="Javob"), frame(**done)])

    def paths(self) -> list[str]:
        return [c["path"] for c in self.calls]


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    return fake


@pytest.fixture
def wired(monkeypatch, upstream, tmp_path):
    """`chat` moduli soxta yordamchi ustida; CRM sessiyasi va tokenlar yo'q."""
    import app.api.v1.chat as chat_module
    from app.services.integrations.crm_auth import CrmAuth

    monkeypatch.setattr(chat_module, "_assistant",
                        AssistantClient(BASE, "venera", "sir", timeout=5, max_concurrent=4))
    monkeypatch.setattr(chat_module, "_crm", CrmAuth("", "", "", tmp_path / "crm"))
    monkeypatch.setattr(chat_module, "platform_tokens", dict)
    return chat_module


@pytest.fixture
def api(wired, client):
    return client


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Kesh jarayon bo'yicha umumiy - har test toza boshlansin va toza qoldirsin."""
    control.invalidate()
    yield
    control.invalidate()


@pytest.fixture
def db(_isolated_analytics) -> Database:
    return _isolated_analytics


def set_env(monkeypatch, default: str = "v2", by_channel: str = "") -> None:
    monkeypatch.setattr(settings, "hrm_assistant_engine", default)
    monkeypatch.setattr(settings, "hrm_assistant_engine_by_channel", by_channel)


def put_policy_row(db: Database, key: str, value: str) -> None:
    """Chetdan yozish (admin API'siz) - `invalidate` CHAQIRILMAYDI."""
    db.execute("INSERT OR REPLACE INTO engine_policy (key, value, updated_at, updated_by) "
               "VALUES (?,?,?,?)", (key, value, time.time(), "test"))


def grant(db: Database, actor_id: int, engines: list[str], default: str | None = None, *,
          refresh: bool = True) -> None:
    db.execute("INSERT OR REPLACE INTO engine_access (actor_id, engines, default_engine, "
               "updated_at, updated_by) VALUES (?,?,?,?,?)",
               (actor_id, json.dumps(engines), default, time.time(), "test"))
    if refresh:
        control.invalidate()


def policy(db: Database, refresh: bool = True, **keys: str) -> None:
    for key, value in keys.items():
        put_policy_row(db, "default" if key == "default" else f"channel:{key}", value)
    if refresh:
        control.invalidate()


def person(actor_id: int) -> AuthUser:
    return AuthUser(actorId=actor_id, email=f"u{actor_id}@venera.uz", fullName=f"Xodim {actor_id}")


def turns(db: Database, sql: str = "SELECT * FROM turns ORDER BY started_at", params=()):
    assert analytics.flush(5.0)
    return db.rows(sql, params)


def audit(db: Database) -> list[dict]:
    rows = db.rows("SELECT action, target_type, target_id, detail, admin_actor_id "
                   "FROM audit_log ORDER BY id")
    for row in rows:
        row["detail"] = json.loads(row["detail"]) if row["detail"] else None
    return rows


def lines(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


# ================================================================ tanlov tartibi


def test_admin_saqlamaguncha_env_ishlaydi(db, monkeypatch):
    """5-bo'g'in: siyosat ham, ruxsat ham yo'q - `.env` (kanal istisnosi bilan)."""
    set_env(monkeypatch, default="v2", by_channel="miniapp=v1")
    assert control.effective_engine(None, "web") == "v2"
    assert control.effective_engine(person(5), "miniapp") == "v1"
    found = control.choose(person(5), "miniapp")
    assert (found.source, found.available, found.selectable) == ("env", ("v1",), False)


def test_env_notogri_bolsa_kod_defaulti(db, monkeypatch):
    """6-bo'g'in: `.env` dagi yozuv tanilmasa - kod default'i `v2`."""
    set_env(monkeypatch, default="v9")
    assert control.effective_engine(None, "web") == "v2"


def test_env_versiyasiz_yol_saqlanadi(db, monkeypatch):
    """`legacy` - faqat `.env` orqali; admin saqlamaguncha u ishlayveradi."""
    set_env(monkeypatch, default="")
    assert control.effective_engine(None, "web") == ""


def test_umumiy_siyosat_env_dan_ustun(db, monkeypatch):
    """4-bo'g'in `.env` ning KANAL istisnosidan ham ustun: admin saqlagach
    `.env` faqat admin aytmagan joyda ishlaydi."""
    set_env(monkeypatch, default="v2", by_channel="miniapp=v2,bot=v2")
    policy(db, default="v1")
    for channel in ("web", "miniapp", "bot", "api"):
        assert control.effective_engine(None, channel) == "v1"
    assert control.choose(None, "web").source == "default"


def test_kanal_siyosati_umumiydan_ustun(db, monkeypatch):
    policy(db, default="v2", bot="v1")
    assert control.effective_engine(None, "bot") == "v1"
    assert control.effective_engine(None, "web") == "v2"
    assert control.choose(None, "bot").source == "channel"
    # Kanal noma'lum bo'lsa - kanal bo'g'ini o'tkaziladi, umumiysi ishlaydi.
    assert control.effective_engine(None, "faks") == "v2"


def test_kanal_siyosati_umumiysiz_env_ga_tushadi(db, monkeypatch):
    set_env(monkeypatch, default="v2", by_channel="web=v1")
    policy(db, miniapp="v1")
    assert control.effective_engine(None, "miniapp") == "v1"     # siyosat
    assert control.effective_engine(None, "web") == "v1"         # .env kanal istisnosi
    assert control.effective_engine(None, "bot") == "v2"         # .env umumiy


def test_odam_defaulti_kanal_siyosatidan_ustun(db):
    policy(db, default="v2", web="v2")
    grant(db, 5, ["v1", "v2"], "v1")
    found = control.choose(person(5), "web")
    assert (found.engine, found.source) == ("v1", "user")
    assert found.available == ("v1", "v2") and found.selectable
    # Boshqa odam - siyosatda.
    assert control.effective_engine(person(6), "web") == "v2"


def test_yagona_versiya_default_hisoblanadi(db):
    """2-bo'g'in: bitta versiya berilgan (default'siz) - o'sha, tanlov yo'q."""
    policy(db, default="v2")
    grant(db, 5, ["v1"])
    found = control.choose(person(5), "miniapp")
    assert (found.engine, found.source, found.selectable) == ("v1", "user", False)
    assert found.available == ("v1",)


def test_soralgan_versiya_faqat_ruxsat_bolsa(db):
    policy(db, default="v2")
    grant(db, 5, ["v2", "v1"], "v1")               # tartib - katalognikidek saqlanadi
    found = control.choose(person(5), "web", "V2 ")
    assert (found.engine, found.source, found.ignored) == ("v2", "requested", False)
    # Ruxsat etilmagan / notanish / versiyasiz yo'l - jimgina e'tiborsiz.
    for wanted in ("v9", "legacy", "", "../v1", 42):
        assert control.effective_engine(person(5), "web", wanted) == "v1", wanted
    assert control.choose(person(5), "web", "v9").ignored
    # Ruxsati yo'q odam - so'ragani hisobga olinmaydi.
    found = control.choose(person(6), "web", "v1")
    assert (found.engine, found.ignored) == ("v2", True)
    # Bitta versiya berilgan odam boshqasini so'rasa ham - o'zinikida.
    grant(db, 7, ["v1"])
    assert control.effective_engine(person(7), "web", "v2") == "v1"


def test_defaultsiz_kop_versiya_siyosatga_ergashadi_lekin_ruxsat_ichida(db, monkeypatch):
    grant(db, 5, ["v1", "v2"])
    policy(db, default="v1")
    found = control.choose(person(5), "web")
    assert (found.engine, found.source, found.selectable) == ("v1", "default", True)
    # Siyosat ro'yxatda yo'q yo'lni bersa (`.env` dagi versiyasiz) - ro'yxat
    # birinchisi: `current` HAR DOIM `available` ichida.
    db.execute("DELETE FROM engine_policy")
    control.invalidate()
    set_env(monkeypatch, default="")
    found = control.choose(person(5), "web")
    assert (found.engine, found.available) == ("v1", ("v1", "v2"))


def test_buzilgan_qatorlar_etiborsiz(db, monkeypatch):
    """Qo'lda buzilgan qator taxmin bilan ishlatilmaydi - keyingi bo'g'in."""
    set_env(monkeypatch, default="v2")
    put_policy_row(db, "default", "v9")
    put_policy_row(db, "channel:faks", "v1")
    db.execute("INSERT INTO engine_access (actor_id, engines) VALUES (5, 'json emas')")
    db.execute("INSERT INTO engine_access (actor_id, engines, default_engine) "
               "VALUES (6, '[\"v7\"]', 'v7')")
    db.execute("INSERT INTO engine_access (actor_id, engines, default_engine) "
               "VALUES (7, '[\"v1\", \"v9\"]', 'v9')")
    control.invalidate()
    assert control.effective_engine(person(5), "web") == "v2"
    assert control.effective_engine(person(6), "web") == "v2"
    found = control.choose(person(7), "web")
    assert (found.engine, found.available) == ("v1", ("v1",))
    assert control.rules().policy == {}


# ================================================================ kesh


def test_admin_yozuvi_keshni_darhol_yangilaydi(api, auth, db, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(control, "_clock", lambda: now[0])
    assert control.effective_engine(None, "web") == "v2"          # keshga tushdi
    response = api.put("/api/v1/admin/engines/policy", headers=auth, json={"default": "v1"})
    assert response.status_code == 200, response.text
    assert control.effective_engine(None, "web") == "v1", "yozuvdan keyin darhol"

    # Chetdan (boshqa jarayon) yozilgani - kesh umri tugaguncha eski qiymat.
    put_policy_row(db, "default", "v2")
    now[0] += control.CACHE_TTL - 0.5
    assert control.effective_engine(None, "web") == "v1"
    now[0] += 1.0
    assert control.effective_engine(None, "web") == "v2"


def test_kesh_eskirgan_oqishni_qaytarib_qoymaydi(db, monkeypatch):
    """Yozuvdan OLDIN boshlangan o'qish natijasi keshga tushmaydi."""
    real_load = control.load

    def slow_load(database):
        found = real_load(database)
        # O'qish tugaguncha admin yozdi va keshni tozaladi.
        policy(database, default="v1")
        return found

    monkeypatch.setattr(control, "load", slow_load)
    assert control.effective_engine(None, "web") == "v2"           # eski o'qish
    monkeypatch.setattr(control, "load", real_load)
    assert control.effective_engine(None, "web") == "v1", "eski natija keshda qolmadi"


# ================================================================ ombor nosoz


class _BrokenDb:
    def rows(self, *a, **kw):
        raise sqlite3.OperationalError("disk I/O error")


def test_ombor_oqilmasa_env_xato_yoq(db, monkeypatch, caplog):
    set_env(monkeypatch, default="v2", by_channel="miniapp=v1")
    policy(db, default="v1")
    grant(db, 5, ["v1"])
    monkeypatch.setattr(control, "get_db", lambda: _BrokenDb())
    control.invalidate()
    assert control.effective_engine(person(5), "web") == "v2"
    assert control.effective_engine(person(5), "miniapp") == "v1"
    assert control.client_view(person(5), "web")["current"] == "v2"

    def no_db():
        raise RuntimeError("ombor ochilmadi")

    monkeypatch.setattr(control, "get_db", no_db)
    control.invalidate()
    assert control.effective_engine(person(5), "miniapp", "v1") == "v1"


def test_jadval_yoq_bolsa_chat_ishlaydi_admin_503(api, auth, upstream, db):
    db.execute("DROP TABLE engine_policy")
    control.invalidate()
    response = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                        json={"question": "savol"})
    assert response.status_code == 200, response.text
    assert upstream.paths() == ["/api/v2/chat/stream"]
    assert api.get("/api/v1/admin/engines", headers=auth).status_code == 503


# ================================================================ kanallar: web, Mini App, bot


def test_web_va_mini_app_odamning_versiyasida(api, auth, user_auth, upstream, db):
    policy(db, default="v2")
    grant(db, DEMO_ID, ["v1"])
    mini = api.post("/api/v1/chat/stream", headers={**user_auth, "X-Venera-Client": "miniapp"},
                    json={"question": "savol"})
    web = api.post("/api/v1/chat/stream", headers={**user_auth, "X-Venera-Client": "web"},
                   json={"question": "savol"})
    other = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "miniapp"},
                     json={"question": "savol"})
    assert mini.status_code == web.status_code == other.status_code == 200
    assert upstream.paths() == ["/api/v1/chat/stream", "/api/v1/chat/stream",
                                "/api/v2/chat/stream"]
    recorded = {(r["actor_id"], r["channel"]): r["engine"] for r in turns(db)}
    assert recorded == {(DEMO_ID, "miniapp"): "v1", (DEMO_ID, "web"): "v1",
                        (ADMIN_ID, "miniapp"): "v2"}


def test_klient_tanlovi_oqimda(api, user_auth, upstream, db):
    grant(db, DEMO_ID, ["v1", "v2"], "v1")
    headers = {**user_auth, "X-Venera-Client": "web"}
    picked = api.post("/api/v1/chat/stream", headers=headers,
                      json={"question": "savol", "engine": "v2", "mode": "pro"})
    plain = api.post("/api/v1/chat/stream", headers=headers, json={"question": "savol"})
    bogus = api.post("/api/v1/chat/stream", headers=headers,
                     json={"question": "savol", "engine": "v9"})
    assert picked.status_code == plain.status_code == bogus.status_code == 200
    assert upstream.paths() == ["/api/v2/chat/stream", "/api/v1/chat/stream",
                                "/api/v1/chat/stream"]
    # Tanlangan v2 da "Pro" yuqoriga ketadi.
    assert upstream.calls[0]["body"]["mode"] == "pro"
    assert lines(picked)[-1]["engine"] == "v2"
    recorded = turns(db)
    assert [r["engine"] for r in recorded] == ["v2", "v1", "v1"]
    # Rad etilgan tanlov izda ko'rinadi.
    [ignored] = db.rows("SELECT payload FROM turn_events WHERE turn_id=? AND name='engine.ignored'",
                        (bogus.headers["x-venera-turn"],))
    assert json.loads(ignored["payload"]) == {"requested": "v9", "used": "v1"}


def test_v3_alohida_berilgan_odamga_venera_core(api, auth, user_auth, upstream, db):
    """v3 ("Venera Core", API 3.3) avval odamga ALOHIDA beriladi: shu odamning savoli
    /api/v3/ ga ketadi va "Pro" ham o'tadi (v3 da bor); qolganlar umumiy siyosatda.
    Izda dvigatel, agent izi kaliti va vazifa holati yoziladi."""
    grant(db, DEMO_ID, ["v2", "v3"], "v3")
    mine = api.post("/api/v1/chat/stream", headers={**user_auth, "X-Venera-Client": "web"},
                    json={"question": "savol", "mode": "pro"})
    other = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                     json={"question": "savol"})
    assert mine.status_code == other.status_code == 200
    assert upstream.paths() == ["/api/v3/chat/stream", "/api/v2/chat/stream"]
    assert upstream.calls[0]["body"]["mode"] == "pro"
    assert lines(mine)[-1]["engine"] == "v3"
    assert [r["engine"] for r in turns(db)] == ["v3", "v2"]
    [done] = db.rows("SELECT payload FROM turn_events WHERE turn_id=? AND name='done'",
                     (mine.headers["x-venera-turn"],))
    payload = json.loads(done["payload"])
    assert payload["trace_id"] == "tr-1"
    assert payload["task"] == {"intent": "crm.create_issue", "state": "awaiting_confirm"}


def test_ruxsatsiz_tanlov_xato_bermaydi(api, auth, upstream, db):
    response = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                        json={"question": "savol", "engine": "v1"})
    assert response.status_code == 200
    assert upstream.paths() == ["/api/v2/chat/stream"]


def test_izdagi_dvigatel_siyosatdagisi(api, auth, upstream, db, monkeypatch):
    """Izga `.env` emas, HAQIQATDA tanlangani yoziladi."""
    set_env(monkeypatch, default="v2")
    policy(db, web="v1")
    response = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                        json={"question": "savol"})
    turn_id = response.headers["x-venera-turn"]
    [row] = turns(db, "SELECT engine FROM turns WHERE id=?", (turn_id,))
    assert row["engine"] == "v1"
    [opened] = db.rows("SELECT payload FROM turn_events WHERE turn_id=? AND "
                       "name='assistant.open'", (turn_id,))
    assert json.loads(opened["payload"])["engine"] == "v1"


def test_ask_yoli_ham_shu_qoidadan(api, auth, user_auth, db):
    grant(db, DEMO_ID, ["v1", "v2"], "v2")
    policy(db, default="v1")
    picked = api.post("/api/v1/chat/ask", headers=user_auth, json={"question": "salom",
                                                                    "engine": "v1"})
    own = api.post("/api/v1/chat/ask", headers=user_auth, json={"question": "salom"})
    public = api.post("/api/v1/chat/ask", headers=auth, json={"question": "salom",
                                                               "engine": "v2"})
    assert picked.status_code == own.status_code == public.status_code == 200
    engines_of = {r["id"]: r["engine"] for r in turns(db)}
    assert engines_of[picked.headers["x-venera-turn"]] == "v1"
    assert engines_of[own.headers["x-venera-turn"]] == "v2"
    assert engines_of[public.headers["x-venera-turn"]] == "v1"


def _bot(tmp_path, actor_id: int, backend):
    from test_telegram_bot import TG_ID, FakeTelegram

    from app.bot.runner import VeneraBot
    from app.core.security import hash_password
    from app.services.telegram_links import LinkStore
    from app.services.users import StoredUser, UserStore

    users = UserStore({"bot@venera.uz": StoredUser(
        actor_id=actor_id, email="bot@venera.uz", full_name="Bot Odam",
        password_hash=hash_password("x"))})
    tg, links = FakeTelegram(), LinkStore(tmp_path / "links.json")
    links.link(TG_ID, actor_id)
    bot = VeneraBot(tg, links, users=lambda: users, backend=backend,
                    webapp_url="https://llm.test/tg/", inline=True, typing_every=None)
    return bot, tg


def test_bot_odamning_versiyasida(wired, upstream, db, tmp_path):
    from test_telegram_bot import text_update

    from app.bot.runner import Backend

    policy(db, default="v2", bot="v2")
    grant(db, 3, ["v1"])
    bot, tg = _bot(tmp_path, 3, Backend())
    bot.handle_update(text_update("savol"))
    assert upstream.paths() == ["/api/v1/chat/stream"]
    [row] = turns(db)
    assert (row["channel"], row["engine"], row["status"]) == ("bot", "v1", "ok")
    assert Backend().engine(person(3)) == "v1"
    assert Backend().engine() == "v2", "odamsiz - bot kanalining siyosati"


def test_bot_ochilmagan_savolda_ham_odamning_versiyasi(wired, db, tmp_path):
    from test_telegram_bot import text_update

    from app.bot.runner import Backend

    class Failing(Backend):
        def stream(self, question, user, chat_id):
            raise AssistantError("navbat to'la", status=503, reason="queue_full")

    policy(db, default="v2")
    grant(db, 3, ["v1"])
    bot, _ = _bot(tmp_path, 3, Failing())
    bot.handle_update(text_update("savol"))
    [row] = turns(db)
    assert (row["engine"], row["error_code"]) == ("v1", "queue_full")


# ================================================================ "Pro" byudjeti


def test_pro_byudjeti_tanlangan_versiyaga_ergashadi(api, auth, user_auth, upstream, db):
    grant(db, DEMO_ID, ["v1", "v2"], "v1")
    own = api.get("/api/v1/pro/quota", headers=user_auth).json()
    assert (own["engine"], own["available"]) == ("v1", False)
    assert upstream.calls == [], "v1 da byudjet so'ralmaydi"
    picked = api.get("/api/v1/pro/quota", headers=user_auth, params={"engine": "v2"}).json()
    assert (picked["engine"], picked["available"]) == ("v2", True)
    assert picked["limits"] == QUOTA["limits"]
    assert upstream.paths() == ["/api/pro/quota"]
    # Ruxsatsiz odamning tanlovi e'tiborsiz - siyosatdagisi.
    other = api.get("/api/v1/pro/quota", headers=auth, params={"engine": "v1"}).json()
    assert (other["engine"], other["available"]) == ("v2", True)
    # Notanish qiymat ham xato emas.
    assert api.get("/api/v1/pro/quota", headers=user_auth,
                   params={"engine": "x" * 300}).status_code == 200


# ================================================================ GET /chat/engines


def test_klient_dvigatellar_royxati(api, auth, user_auth, db):
    body = api.get("/api/v1/chat/engines", headers=user_auth).json()
    assert set(body) == CHOICE_FIELDS
    assert body == {"current": "v2", "selectable": False, "available": ["v2"],
                    "catalog": CATALOG}
    grant(db, DEMO_ID, ["v2", "v1"], "v1")
    body = api.get("/api/v1/chat/engines", headers={**user_auth, "X-Venera-Client": "miniapp"})
    assert body.json() == {"current": "v1", "selectable": True, "available": ["v1", "v2"],
                           "catalog": CATALOG}
    # Kanal X-Venera-Client dan.
    policy(db, miniapp="v1")
    assert api.get("/api/v1/chat/engines",
                   headers={**auth, "X-Venera-Client": "miniapp"}).json()["current"] == "v1"
    assert api.get("/api/v1/chat/engines", headers=auth).json()["current"] == "v2"
    assert api.get("/api/v1/chat/engines").status_code == 401


# ================================================================ admin API


def test_admin_korinish_shakli(api, auth, monkeypatch):
    set_env(monkeypatch, default="v2", by_channel="miniapp=v1")
    response = api.get("/api/v1/admin/engines", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ADMIN_ENGINES_FIELDS
    assert body["catalog"] == CATALOG
    assert set(body["policy"]) == POLICY_FIELDS
    assert body["policy"] == {"default": None, "channels": {}, "source": "env",
                              "updatedAt": None, "updatedBy": None}
    assert body["envDefaults"] == {"default": "v2", "channels": {"miniapp": "v1"}}
    assert body["effective"] == {"web": "v2", "miniapp": "v1", "bot": "v2"}
    assert body["stats"] == [] and body["access"] == []


def test_admin_siyosat_qoshiladigan_ozgarish_va_audit(api, auth, db):
    put = api.put("/api/v1/admin/engines/policy", headers=auth,
                  json={"default": "v1", "channels": {"bot": "v2", "Web": "v1"}})
    assert put.status_code == 200, put.text
    body = put.json()
    assert set(body) == ADMIN_ENGINES_FIELDS
    policy_ = body["policy"]
    assert (policy_["default"], policy_["channels"], policy_["source"]) == (
        "v1", {"web": "v1", "bot": "v2"}, "admin")
    assert ISO.fullmatch(policy_["updatedAt"]) and policy_["updatedBy"] == "admin@venera.uz"
    assert body["effective"] == {"web": "v1", "miniapp": "v1", "bot": "v2"}

    # Yuborilmagan `default` o'zgarmaydi, `null` - kalitni o'chiradi.
    body = api.put("/api/v1/admin/engines/policy", headers=auth,
                   json={"channels": {"bot": None}}).json()
    assert (body["policy"]["default"], body["policy"]["channels"]) == ("v1", {"web": "v1"})
    # O'zgarishsiz so'rov - auditga yozilmaydi.
    api.put("/api/v1/admin/engines/policy", headers=auth, json={"default": "v1"})
    body = api.put("/api/v1/admin/engines/policy", headers=auth,
                   json={"default": None, "channels": {"web": None}}).json()
    assert body["policy"]["source"] == "env" and body["effective"]["web"] == "v2"

    rows = audit(db)
    assert [r["action"] for r in rows] == ["engine.policy"] * 3
    assert all((r["target_type"], r["target_id"], r["admin_actor_id"]) == (
        "engine", "policy", ADMIN_ID) for r in rows)
    assert rows[0]["detail"] == {"from": {"default": None, "channels": {}},
                                 "to": {"default": "v1", "channels": {"web": "v1", "bot": "v2"}}}
    assert rows[2]["detail"]["to"] == {"default": None, "channels": {}}


@pytest.mark.parametrize("body", [
    {"default": "v9"},
    {"default": ""},
    {"default": "legacy"},
    {"channels": {"faks": "v1"}},
    {"channels": {"bot": "v9"}},
    {"default": "v1", "channels": {"faks": "v1"}},     # hammasi yoki hech narsa
    {"channels": {"web": 5}},
])
def test_admin_siyosat_tekshiruvi_422(api, auth, db, body):
    response = api.put("/api/v1/admin/engines/policy", headers=auth, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["message"]
    assert db.rows("SELECT * FROM engine_policy") == []
    assert audit(db) == []


def test_admin_odamga_versiya_berish_va_olish(api, auth, db):
    put = api.put(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=auth,
                  json={"engines": ["v2", "v1", "V2"], "defaultEngine": "v1",
                        "note": "  sinovchi  "})
    assert put.status_code == 200, put.text
    row = put.json()
    assert set(row) == ACCESS_ROW_FIELDS
    assert {k: row[k] for k in ("actorId", "name", "login", "engines", "defaultEngine", "note",
                                "updatedBy")} == {
        "actorId": DEMO_ID, "name": "Demo Foydalanuvchi", "login": "demo@venera.uz",
        "engines": ["v1", "v2"], "defaultEngine": "v1", "note": "sinovchi",
        "updatedBy": "admin@venera.uz"}
    assert ISO.fullmatch(row["updatedAt"])
    assert control.effective_engine(DEMO_ID, "web") == "v1", "darhol kuchga kirdi"

    listed = api.get("/api/v1/admin/engines", headers=auth).json()["access"]
    assert listed == [row]

    # `note` yuborilmasa - eskisi qoladi.
    again = api.put(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=auth,
                    json={"engines": ["v1"]}).json()
    assert (again["engines"], again["defaultEngine"], again["note"]) == (["v1"], None, "sinovchi")

    removed = api.delete(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=auth)
    assert removed.status_code == 200 and removed.json() == {"removed": True}
    assert api.delete(f"/api/v1/admin/engines/access/{DEMO_ID}",
                      headers=auth).json() == {"removed": False}
    assert control.effective_engine(DEMO_ID, "web") == "v2"

    rows = audit(db)
    assert [r["action"] for r in rows] == ["engine.access.set", "engine.access.set",
                                           "engine.access.remove"]
    assert all((r["target_type"], r["target_id"]) == ("user", str(DEMO_ID)) for r in rows)
    assert rows[0]["detail"] == {"from": None,
                                 "to": {"engines": ["v1", "v2"], "defaultEngine": "v1"},
                                 "note": "sinovchi"}
    assert rows[1]["detail"] == {"from": {"engines": ["v1", "v2"], "defaultEngine": "v1"},
                                 "to": {"engines": ["v1"], "defaultEngine": None}}
    assert rows[2]["detail"] == {"from": {"engines": ["v1"], "defaultEngine": None}}


def test_admin_ozgarishsiz_ruxsat_auditga_yozilmaydi(api, auth, db):
    body = {"engines": ["v1", "v2"], "defaultEngine": "v2"}
    first = api.put(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=auth, json=body).json()
    second = api.put(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=auth, json=body).json()
    assert second == first
    assert len(audit(db)) == 1


@pytest.mark.parametrize(("body", "status"), [
    ({"engines": []}, 422),
    ({"engines": ["v9"]}, 422),
    ({"engines": ["legacy"]}, 422),
    ({"engines": ["v1"], "defaultEngine": "v2"}, 422),
    ({"engines": ["v1"], "defaultEngine": "v7"}, 422),
    ({"defaultEngine": "v1"}, 422),
    ({"engines": ["v1"], "note": "x" * 501}, 422),
])
def test_admin_ruxsat_tekshiruvi(api, auth, db, body, status):
    response = api.put(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=auth, json=body)
    assert response.status_code == status, response.text
    assert db.rows("SELECT * FROM engine_access") == []


def test_admin_notanish_odam_404(api, auth, db):
    response = api.put("/api/v1/admin/engines/access/999", headers=auth, json={"engines": ["v1"]})
    assert response.status_code == 404
    assert response.json()["message"] == "Foydalanuvchi topilmadi"
    assert db.rows("SELECT * FROM engine_access") == [] and audit(db) == []


def test_admin_katalogdan_ketgan_odam_qatorini_olib_tashlasa_boladi(api, auth, db):
    grant(db, 999, ["v1"])
    assert api.delete("/api/v1/admin/engines/access/999", headers=auth).json() == {"removed": True}
    # Ro'yxatda nomsiz odam `#id` bo'lib ko'rinardi - endi yo'q.
    assert api.get("/api/v1/admin/engines", headers=auth).json()["access"] == []


def test_admin_royxatda_katalogda_yoq_odam_raqami_bilan(api, auth, db):
    grant(db, 999, ["v2"])
    [row] = api.get("/api/v1/admin/engines", headers=auth).json()["access"]
    assert (row["actorId"], row["name"], row["login"]) == (999, "#999", None)


def test_admin_endpointlari_user_uchun_403(api, user_auth, db):
    calls = [
        api.get("/api/v1/admin/engines", headers=user_auth),
        api.put("/api/v1/admin/engines/policy", headers=user_auth, json={"default": "v1"}),
        api.put(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=user_auth,
                json={"engines": ["v1", "v2"]}),
        api.delete(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=user_auth),
    ]
    assert [r.status_code for r in calls] == [403] * 4
    assert api.get("/api/v1/admin/engines").status_code == 401
    assert db.rows("SELECT * FROM engine_policy") == [] == db.rows("SELECT * FROM engine_access")


def test_admin_statistika_oxirgi_7_kun(api, auth, db):
    now = time.time()
    rows = [
        ("a1", now - 100, 2, "v1", "ok", 300),
        ("a2", now - 200, 2, "v1", "error", None),
        ("a3", now - 300, 1, "v2", "ok", 500),
        ("a4", now - 400, 1, "v2", "ok", 700),
        ("a5", now - 50, 3, None, "ok", None),
        ("a6", now - 8 * 86400, 1, "v2", "ok", 100),      # 7 kundan eski - kirmaydi
    ]
    for turn_id, started, actor, engine, status, ttft in rows:
        db.execute("INSERT INTO turns (id, started_at, actor_id, channel, question, status, "
                   "engine, ttft_ms) VALUES (?,?,?,'web','savol',?,?,?)",
                   (turn_id, started, actor, status, engine, ttft))
    stats = api.get("/api/v1/admin/engines", headers=auth).json()["stats"]
    assert all(set(s) == USAGE_FIELDS for s in stats)
    assert stats == [
        {"engine": "v1", "turns": 2, "errors": 1, "medianTtftMs": 300, "users": 1},
        {"engine": "v2", "turns": 2, "errors": 0, "medianTtftMs": 600, "users": 1},
        {"engine": "default", "turns": 1, "errors": 0, "medianTtftMs": None, "users": 1},
    ]


def test_foydalanuvchi_varaginda_dvigatel(api, auth, db):
    body = api.get(f"/api/v1/admin/users/{DEMO_ID}", headers=auth).json()
    assert body["engine"] == {"effective": {"web": "v2", "miniapp": "v2", "bot": "v2"},
                              "access": None}
    api.put("/api/v1/admin/engines/policy", headers=auth, json={"channels": {"bot": "v1"}})
    api.put(f"/api/v1/admin/engines/access/{DEMO_ID}", headers=auth,
            json={"engines": ["v1", "v2"], "defaultEngine": "v2"})
    body = api.get(f"/api/v1/admin/users/{DEMO_ID}", headers=auth).json()
    assert body["engine"] == {"effective": {"web": "v2", "miniapp": "v2", "bot": "v2"},
                              "access": {"engines": ["v1", "v2"], "defaultEngine": "v2"}}
    # Odamga oid yozuv varaqdagi auditda ham.
    assert [a["action"] for a in body["audit"]] == ["engine.access.set"]
    # Boshqa odam (ruxsatsiz) - kanal siyosatida.
    admin = api.get(f"/api/v1/admin/users/{ADMIN_ID}", headers=auth).json()
    assert admin["engine"]["effective"]["bot"] == "v1" and admin["engine"]["access"] is None


def test_varaq_ombor_jadvalisiz_ham_ochiladi(api, auth, db):
    db.execute("DROP TABLE engine_access")
    body = api.get(f"/api/v1/admin/users/{DEMO_ID}", headers=auth)
    assert body.status_code == 200
    assert body.json()["engine"]["access"] is None


def test_health_detail_haqiqiy_holatni_korsatadi(api, auth, db, monkeypatch):
    """`.env` (`engine`) yonida HOZIR ishlaydigani (`policy`) - admin siyosat
    saqlagach `.env` dagi qiymat endi ishlamaydi, jurnal o'qiydigan buni ko'rsin."""
    set_env(monkeypatch, default="v2")
    state = api.get("/api/health/detail", headers=auth).json()["assistant"]
    assert state["policy"]["source"] == "env" and state["policy"]["byChannel"]["web"] == "v2"
    api.put("/api/v1/admin/engines/policy", headers=auth, json={"channels": {"web": "v1"}})
    grant(db, DEMO_ID, ["v1"])
    state = api.get("/api/health/detail", headers=auth).json()["assistant"]
    assert state["engine"]["default"] == "v2"
    assert state["policy"] == {"source": "admin", "loaded": True, "grants": 1,
                               "byChannel": {"web": "v1", "miniapp": "v2", "bot": "v2",
                                             "desktop": "v2", "api": "v2"}}


# ================================================================ sxema v3


def test_v2_ombor_v3_ga_otadi_malumot_joyida(tmp_path):
    """Prod fayli (sxema v2, ma'lumot bilan) yangi kod bilan ochilsa: ikki yangi
    jadval qo'shiladi, eski ma'lumot joyida, qarorlar bo'sh - ya'ni `.env`."""
    assert SCHEMA_VERSION == 3
    path = tmp_path / "prod" / "venera.db"
    path.parent.mkdir()
    old = sqlite3.connect(str(path), isolation_level=None)
    for step in MIGRATIONS[:2]:
        for statement in step:
            old.execute(statement)
    old.execute("PRAGMA user_version = 2")
    old.execute("INSERT INTO turns (id, started_at, channel, question, status, engine) "
                "VALUES ('t1', 1.0, 'web', 'eski savol', 'ok', 'v2')")
    old.execute("INSERT INTO user_admin (actor_id, disabled, token_version) VALUES (5, 1, 3)")
    old.close()

    database = Database(path)
    try:
        assert database.version() == 3
        assert [r["name"] for r in database.rows("PRAGMA table_info(engine_policy)")] == [
            "key", "value", "updated_at", "updated_by"]
        assert [r["name"] for r in database.rows("PRAGMA table_info(engine_access)")] == [
            "actor_id", "engines", "default_engine", "note", "updated_at", "updated_by"]
        assert database.row("SELECT question, engine FROM turns") == {
            "question": "eski savol", "engine": "v2"}
        assert database.row("SELECT disabled, token_version FROM user_admin") == {
            "disabled": 1, "token_version": 3}
        found = control.load(database)
        assert (dict(found.policy), dict(found.access), found.loaded) == ({}, {}, True)
        # Jadvallar yoziladigan holda.
        database.execute("INSERT INTO engine_policy (key, value) VALUES ('default', 'v1')")
        assert control.load(database).policy == {"default": "v1"}
    finally:
        database.close_all()


# ================================================================ sharh (2026-10-04): topilgan xatolar


def test_soralgani_ishlaganining_ozi_bolsa_rad_etilmagan(db, monkeypatch):
    """Yangi klient har savolda `current` ni yuborishi mumkin - bu rad etish
    emas. Ilgari ruxsati yo'q odamning HAR savolida yolg'on `engine.ignored`
    yozilardi."""
    set_env(monkeypatch, default="v2")
    assert not control.choose(person(6), "web", "v2").ignored
    assert not control.choose(person(6), "web", " V2").ignored
    assert control.choose(person(6), "web", "v1").ignored
    assert control.choose(person(6), "web", "legacy").ignored
    grant(db, 7, ["v1"])
    assert not control.choose(person(7), "web", "v1").ignored
    assert control.choose(person(7), "web", "v2").ignored
    grant(db, 8, ["v1", "v2"])                      # default'siz - siyosatga ergashadi
    assert not control.choose(person(8), "web", "v2").ignored
    assert control.choose(person(8), "web", "v9").ignored

    # Zahira yo'li (`resolve` yiqildi) ham shu qoida bilan.
    def broken(*a, **kw):
        raise RuntimeError("kutilmagan")

    monkeypatch.setattr(control, "resolve", broken)
    assert not control.choose(person(6), "web", "v2").ignored
    assert control.choose(person(6), "web", "v1").ignored


def test_oqimda_current_yuborilsa_izda_rad_etish_yoq(api, auth, upstream, db, monkeypatch):
    set_env(monkeypatch, default="v2")
    response = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                        json={"question": "savol", "engine": "v2"})
    assert response.status_code == 200
    turn_id = response.headers["x-venera-turn"]
    [row] = turns(db, "SELECT engine FROM turns WHERE id=?", (turn_id,))
    assert row["engine"] == "v2"
    assert db.rows("SELECT 1 FROM turn_events WHERE turn_id=? AND name='engine.ignored'",
                   (turn_id,)) == []


def test_siyosat_vaqti_kalit_faqat_olib_tashlanganda_ham_yangilanadi(db):
    """`policy.updatedAt/updatedBy` - oxirgi O'ZGARISH. Ilgari faqat kalit
    o'chirilsa, sahifa eski vaqtni va boshqa adminni ko'rsatardi."""
    from app.services.analytics.queries import iso

    first, second = person(1), person(9)
    control.put_policy(first, None, None, default="v1", channels={"web": "v2"}, now=1000.0)
    view = control.put_policy(second, None, None, channels={"web": None}, now=2000.0)
    assert (view["policy"]["default"], view["policy"]["channels"]) == ("v1", {})
    assert (view["policy"]["updatedAt"], view["policy"]["updatedBy"]) == (
        iso(2000.0), "u9@venera.uz")
    # O'zgarishsiz so'rov vaqtni ham, muallifni ham siljitmaydi.
    view = control.put_policy(first, None, None, default="v1", now=3000.0)
    assert (view["policy"]["updatedAt"], view["policy"]["updatedBy"]) == (
        iso(2000.0), "u9@venera.uz")
    assert [r["action"] for r in audit(db)] == ["engine.policy", "engine.policy"]


def test_buzuq_turdagi_ustun_hamma_qarorni_ochirmaydi(api, auth, db):
    """Qo'lda yozilgan matnli vaqt ilgari `load` ni `TypeError` bilan
    yiqitardi: HAMMA siyosat va HAMMA odamning ruxsati `.env` ga tushardi,
    admin sahifalari esa 500 berardi."""
    from app.services.analytics.queries import iso

    db.execute("INSERT INTO engine_policy (key, value, updated_at, updated_by) "
               "VALUES ('default', 'v1', 'kecha', 'qo''lda')")
    db.execute("INSERT INTO engine_policy (key, value, updated_at, updated_by) "
               "VALUES ('channel:bot', 'v2', 5.0, 'a@venera.uz')")
    db.execute("INSERT INTO engine_access (actor_id, engines, default_engine, note, updated_at, "
               "updated_by) VALUES (?, '[\"v1\", \"v2\"]', 'v2', x'41', 'bugun', 'b@venera.uz')",
               (DEMO_ID,))
    control.invalidate()
    found = control.rules()
    assert found.loaded and dict(found.policy) == {"default": "v1", "channel:bot": "v2"}
    assert control.effective_engine(DEMO_ID, "web") == "v2", "ruxsat joyida"
    assert control.effective_engine(None, "web") == "v1", "siyosat joyida"

    response = api.get("/api/v1/admin/engines", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["policy"]["updatedAt"], body["policy"]["updatedBy"]) == (iso(5.0), "a@venera.uz")
    [row] = body["access"]
    assert (row["engines"], row["updatedAt"], row["updatedBy"]) == (
        ["v1", "v2"], None, "b@venera.uz")
    assert isinstance(row["note"], str)
    assert api.get(f"/api/v1/admin/users/{DEMO_ID}", headers=auth).status_code == 200


def test_eski_kod_v3_omborni_ochsa_ishlaydi(tmp_path, monkeypatch):
    """Deploy orqaga qaytarilsa: v2 kodi v3 faylni ochadi - sxemani
    tushirmaydi, o'z jadvallari bilan ishlaydi; yangi kod qaytganda admin
    qarorlari joyida."""
    from app.services.analytics import db as db_module

    path = tmp_path / "v3" / "venera.db"
    path.parent.mkdir()
    new = Database(path)
    try:
        new.execute("INSERT INTO engine_policy (key, value) VALUES ('default', 'v1')")
    finally:
        new.close_all()

    monkeypatch.setattr(db_module, "MIGRATIONS", MIGRATIONS[:2])
    monkeypatch.setattr(db_module, "SCHEMA_VERSION", 2)
    old = Database(path)
    try:
        assert old.version() == 3
        old.execute("INSERT INTO turns (id, started_at, channel, question, status, engine) "
                    "VALUES ('t1', 1.0, 'web', 'savol', 'ok', 'v1')")
        assert old.scalar("SELECT COUNT(*) FROM turns") == 1
    finally:
        old.close_all()

    monkeypatch.undo()
    again = Database(path)
    try:
        assert again.version() == SCHEMA_VERSION == 3
        assert dict(control.load(again).policy) == {"default": "v1"}
    finally:
        again.close_all()

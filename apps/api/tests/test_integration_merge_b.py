"""Birlashtirish (B2 audit): prod + SSO/"Pro" + `venera-admin-redesign` - qolgan
UCHRASHUV joylari.

`test_integration_merge.py` (prod + SSO) va `test_integration_admin.py` (birinchi
ulama) qoplamagan yo'llar. Har test ikki shoxning kodi BIRGA ishlaganda nima
bo'lishini sinaydi - bittasini alohida sinash boshqa fayllarda:

  * kanal: savol `X-Venera-Client` / `Referer` bo'yicha to'g'ri kanal bilan
    yoziladi (web, miniapp, soxta `bot` - `api`);
  * bot savoli `open_stream` dan o'tib `bot` kanali bilan yoziladi - tashqi
    chaqiruv hisobi (`api_calls`) ham shu savolga bog'lanadi; bloklangan odam
    ulanish muddatini UZAYTIRMAYDI, blok olinsa qayta ulanmasdan davom etadi;
  * "Pro": mini app kanali, ochilmagan oqim (`open_failed`) va byudjet so'rovi
    hisobda (`pro.quota`);
  * `/api/health/detail`: faqat SAMARALI ADMIN, ichida SSO `login` bloki va
    prod'ning `conflicts_10min` hisobi;
  * admin paneldagi bot rejimi botning o'zidan (prod'ning `webhook` i ham).

Tarmoqqa chiqilmaydi: Keycloak, HRM, Telegram va yordamchi - soxta.
"""

from __future__ import annotations

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
from app.services.telegram_links import LinkStore
from tests.test_contacts import people  # noqa: F401 - fikstura
from tests.test_integration_merge import (
    ANSWER,
    PERSON_Q,
    _fixed_answer,
    _sso_login,
    real_directory,  # noqa: F401 - fikstura
    telegram_api,  # noqa: F401 - fikstura
)
from tests.test_pro import api, assistant, server  # noqa: F401 - fikstura
from tests.test_sso_login import hub, net  # noqa: F401 - fikstura
from tests.test_telegram_bot import TG_ID, WEBHOOK_URL, _conflict, text_update

TURN = re.compile(r"[0-9a-f]{32}")
#: Oddiy savol - yordamchiga ketadi.
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


def make_bot(telegram_api, directory) -> VeneraBot:
    return VeneraBot(telegram_api, bot_module.links, users=directory, backend=Backend(),
                     inline=True, typing_every=None)


# --- kanal: savol kanali sarlavhadan -----------------------------


@pytest.mark.parametrize(("headers", "channel"), [
    ({"X-Venera-Client": "web"}, "web"),
    ({"X-Venera-Client": "miniapp"}, "miniapp"),
    # Eski mini app build (sarlavhasiz) - sahifa `/tg/` ostida.
    ({"Referer": "https://llm.brb-tech.uz/tg/index.html"}, "miniapp"),
    ({}, "api"),
    # `bot` sarlavha orqali QABUL QILINMAYDI - statistikani soxtalashtirmasin.
    ({"X-Venera-Client": "bot"}, "api"),
])
def test_javob_kanali_sarlavhadan(client, auth, people, db, monkeypatch, headers, channel):
    monkeypatch.setattr(chat_api._assistant, "stream", _fixed_answer)
    r = client.post("/api/v1/chat/stream", headers={**auth, **headers},
                    json={"question": PERSON_Q})
    assert r.status_code == 200 and ANSWER in r.text, r.text
    [turn] = rows(db, "SELECT * FROM turns")
    assert turn["id"] == r.headers["X-Venera-Turn"]
    assert (turn["channel"], turn["kind"], turn["route"], turn["status"]) == (
        channel, "chat", "rules", "ok")


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
    monkeypatch.setattr(chat_api._assistant, "stream", _fixed_answer)
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
    assert ANSWER in telegram_api.texts()[-1]
    assert bot_module.links.lookup(TG_ID)[0].seen_at == later
    [turn] = rows(db, "SELECT * FROM turns WHERE channel='bot'")
    assert (turn["route"], turn["actor_id"]) == ("rules", actor)


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

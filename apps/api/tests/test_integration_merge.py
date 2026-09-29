"""Birlashtirish: prod o'zgarishlari + `venera-sso-login` UCHRASHADIGAN joylar.

Har shox o'z xususiyatini o'z testlarida sinaydi: kontaktlar, webhook va
ulanish muddati - `test_contacts.py`, `test_telegram_bot.py`; Keycloak va
"Pro" - `test_sso_login.py`, `test_pro.py`. Bu fayl faqat IKKALASI BIRGA
ishlaydigan yo'llarni sinaydi - birlashtirishdan keyin ularga hech bir test
tegmagan edi:

  * `bot.start()` - birlashtirishda QO'LDA hal qilingan yagona joy (SSO
    katalogi + webhook argumentlari). Testlarda bot o'chiq, ya'ni bu
    funksiya hech qachon chaqirilmasdi - xato faqat jonli ishga tushishda
    bilinardi;
  * SSO bilan kirgan odam: mini app'dan ulanish -> bot (polling va webhook)
    -> xodimlar ma'lumotnomasi, va ulanish muddatining siljishi;
  * "Pro" rejimidagi kontakt savoli yordamchiga (va byudjetga) bormaydi;
  * kontakt tahriri huquqi SSO rollaridan (`contacts_editor_roles`);
  * `/api/health/detail` da ikkala shoxning bloki birga.

Tarmoqqa chiqilmaydi: Keycloak, HRM, Telegram va yordamchi - soxta.
"""

from __future__ import annotations

import json
import time

import pytest

import app.bot as bot_module
from app.api.deps import get_directory, get_identity_store, get_user_store
from app.api.v1 import chat as chat_api
from app.bot.runner import Backend, VeneraBot
from app.core.config import settings
from app.services.telegram_links import LinkStore
from tests.test_contacts import people  # noqa: F401 - fikstura
from tests.test_pro import api, assistant, server  # noqa: F401 - fikstura
from tests.test_sso_login import LOGIN, hub, net  # noqa: F401 - fikstura
from tests.test_telegram_bot import (
    BOT_TOKEN,
    TG_ID,
    WEBHOOK_URL,
    FakeTelegram,
    WebhookTelegram,
    _conflict,
    sign_init,
    text_update,
)

#: `test_contacts.LIST` dagi to'qima odam va uning telefoni.
PERSON_Q = "Nazarova Dilnozaning telefoni?"
PHONE = "+998935554433"
EDIT_Q = "Nazarova Dilnozaning telefonini +998901234567 ga o'zgartir"


def _no_assistant(*args, **kwargs):
    raise AssertionError("kontakt savoli yuqoridagi xizmatga bormasligi kerak")


def _frames(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture
def real_directory(users_file, monkeypatch):
    """`get_directory` - bot ishlatadigan HAQIQIY funksiya. U `get_user_store`
    ni `Depends` siz chaqiradi, shuning uchun `client` fiksturasidagi
    almashtirish unga yetmaydi: fayl manzili vaqtinchalik faylga buriladi
    (mashinadagi `config/users.yaml` o'qilmasin)."""
    monkeypatch.setattr(settings, "users_file", users_file)
    get_user_store.cache_clear()
    yield get_directory
    get_user_store.cache_clear()


@pytest.fixture
def telegram_api(monkeypatch):
    fake = WebhookTelegram()
    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(bot_module, "api", fake)
    monkeypatch.setattr(bot_module, "welcome", lambda tg_id, user: None)
    return fake


def _sso_login(client) -> tuple[int, dict]:
    body = client.post("/api/v1/auth/login", json=LOGIN).json()
    return body["user"]["actorId"], {"Authorization": f"Bearer {body['token']}"}


# --- bot.start(): qo'lda hal qilingan joy -------------------------------------------


def test_bot_start_sso_katalogi_va_webhook_bilan_quriladi(tmp_path, monkeypatch, telegram_api):
    started: list[VeneraBot] = []
    monkeypatch.setattr(VeneraBot, "start", lambda self: started.append(self))
    monkeypatch.setattr(settings, "telegram_bot_enabled", True)
    monkeypatch.setattr(settings, "telegram_links_file", tmp_path / "telegram" / "links.json")
    monkeypatch.setattr(settings, "telegram_mode", "webhook")
    monkeypatch.setattr(settings, "telegram_webhook_url", WEBHOOK_URL)
    monkeypatch.setattr(bot_module, "_bot", None)
    monkeypatch.setattr(bot_module, "_lock_file", None)
    try:
        bot_module.start()
        assert len(started) == 1, bot_module._state
        made = started[0]
        # SSO shoxi: SSO bilan kirganlar ham topilsin.
        assert made.users is get_directory
        # Prod shoxi: webhook rejimi, manzil va sir.
        assert made.mode == "webhook" and made.webhook_url == WEBHOOK_URL
        assert made.webhook_secret == bot_module.webhook_secret() != ""
        assert bot_module.status()["mode"] == "webhook"
    finally:
        bot_module.stop()
        lock = bot_module._lock_file
        if lock is not None and hasattr(lock, "close"):
            lock.close()


# --- SSO odam: mini app -> bot -> ma'lumotnoma --------------------------------------


def test_sso_odam_ulanadi_botda_kontakt_soraydi_muddat_siljiydi(
    client, hub, net, people, telegram_api, real_directory, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, headers = _sso_login(client)
    assert get_identity_store().by_actor_id(actor) is not None, "SSO hisob identities.json da"
    assert get_user_store().by_actor_id(actor) is None, "users.yaml da YO'Q - faqat SSO"

    # Mini app ulaydi - SSO sessiyasi bilan.
    r = client.post("/api/v1/telegram/link", headers=headers,
                    json={"initData": sign_init({"id": TG_ID, "first_name": "Ali"})})
    assert r.status_code == 200 and r.json()["status"] == "new", r.text
    links = bot_module.links
    # Ulanish 29 kun oldin yangilangan bo'lsin: yana 2 kundan keyin tugardi.
    links.link(TG_ID, actor, now=time.time() - 29 * 86400)
    assert links.lookup(TG_ID, now=time.time() + 2 * 86400)[1] == "expired"

    bot = VeneraBot(telegram_api, links, users=real_directory, backend=Backend(),
                    inline=True, typing_every=None)
    bot.handle_update(text_update(PERSON_Q))
    assert PHONE in telegram_api.texts()[-1]
    # Savol muddatni yangiladi (prod: "oxirgi faollikdan 30 kun").
    assert links.lookup(TG_ID, now=time.time() + 2 * 86400)[1] == "linked"


def test_webhook_orqali_sso_odam_kontakt_javobini_oladi(
    client, hub, net, people, telegram_api, real_directory, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, _ = _sso_login(client)
    bot_module.links.link(TG_ID, actor)
    secret = bot_module.webhook_secret()
    bot = VeneraBot(telegram_api, bot_module.links, users=real_directory, backend=Backend(),
                    inline=True, typing_every=None, mode="webhook",
                    webhook_url=WEBHOOK_URL, webhook_secret=secret)
    monkeypatch.setattr(bot_module, "_bot", bot)

    update = dict(text_update(PERSON_Q), update_id=4242)
    r = client.post("/api/v1/telegram/webhook", json=update,
                    headers={"X-Telegram-Bot-Api-Secret-Token": secret})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert PHONE in telegram_api.texts()[-1]


# --- "Pro" + ma'lumotnoma -----------------------------------------------------------


def test_pro_rejimida_kontakt_savoli_yordamchiga_va_byudjetga_bormaydi(api, auth, server, people):
    r = api.post("/api/v1/chat/stream", headers=auth, json={"question": PERSON_Q, "mode": "pro"})
    assert r.status_code == 200, r.text
    frames = _frames(r.text)
    assert frames[-1] == {"type": "done", "route": "contacts"}, "pro bloki yo'q - byudjet yeyilmadi"
    assert PHONE in "".join(f.get("text", "") for f in frames if f["type"] == "token")
    assert server.calls == [], "yordamchi (va Pro) chaqirilmasligi kerak"

    # Kontakt bo'lmagan savol esa "Pro" bilan yordamchiga ketadi.
    r = api.post("/api/v1/chat/stream", headers=auth,
                 json={"question": "Yillik ta'til necha kun?", "mode": "pro"})
    assert r.status_code == 200
    assert server.calls[-1]["body"]["mode"] == "pro"
    assert _frames(r.text)[-1]["pro"]["used"] is True


# --- kontakt tahriri: huquq SSO rollaridan ------------------------------------------


def test_sso_odam_kontakt_tahriri_sozlangan_rol_bilan(client, hub, net, people, monkeypatch):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    _, headers = _sso_login(client)

    # Keycloak rollari (`employee`, `crm-user`) - muharrir emas: o'qiydi, o'zgartirmaydi.
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": PERSON_Q})
    assert PHONE in r.text
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    assert "faqat administrator" in r.text and '"proposal"' not in r.text

    # Keycloak roli `contacts_editor_roles` ga qo'shilsa - taklif va tasdiq SSO sessiyasi bilan.
    monkeypatch.setattr(settings, "contacts_editor_roles", ["ADMIN", "crm-user"])
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    proposal = next(f["proposal"] for f in _frames(r.text) if f["type"] == "proposal")
    assert proposal["token"].startswith("ct_")
    r = client.post(f"/api/v1/actions/{proposal['token']}/confirm", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998901234567"


def test_keycloak_admin_roli_kontakt_tahririga_yetadi(client, hub, net, people, monkeypatch):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    net.roles = net.roles + ["ADMIN"]
    _, headers = _sso_login(client)
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    assert '"proposal"' in r.text and "faqat administrator" not in r.text


# --- /api/health/detail: ikkala shox birga -------------------------------------------


def test_health_detail_sso_va_telegram_bloklari_birga(
    client, auth, hub, net, telegram_api, tmp_path, monkeypatch,
):
    _sso_login(client)
    bot = VeneraBot(telegram_api, LinkStore(tmp_path / "l.json"), users=get_directory,
                    inline=True, typing_every=None)
    bot.poll_error(_conflict(), 1.0)
    monkeypatch.setattr(settings, "telegram_bot_enabled", True)
    monkeypatch.setattr(bot_module, "_bot", bot)

    body = client.get("/api/health/detail", headers=auth).json()
    assert body["login"] == {"sso": True, "local": True, "identities": 1}
    assert body["telegram"]["conflicts_10min"] == 1
    assert any("boshqa nusxa" in w for w in body["warnings"]), body["warnings"]
    assert not any("kirish yo'li yo'q" in w for w in body["warnings"])

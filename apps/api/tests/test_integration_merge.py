"""Birlashtirish: prod o'zgarishlari + `venera-sso-login` UCHRASHADIGAN joylar.

Har shox o'z xususiyatini o'z testlarida sinaydi: webhook va ulanish muddati - `test_contacts.py`, `test_telegram_bot.py`; Keycloak va
"Pro" - `test_sso_login.py`, `test_pro.py`. Bu fayl faqat IKKALASI BIRGA
ishlaydigan yo'llarni sinaydi - birlashtirishdan keyin ularga hech bir test
tegmagan edi:

  * `bot.start()` - birlashtirishda QO'LDA hal qilingan yagona joy (SSO
    katalogi + webhook argumentlari). Testlarda bot o'chiq, ya'ni bu
    funksiya hech qachon chaqirilmasdi - xato faqat jonli ishga tushishda
    bilinardi;
  * SSO bilan kirgan odam: mini app'dan ulanish -> bot (polling va webhook)
    -> yordamchi javobi, va ulanish muddatining siljishi;
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
from app.services.integrations.assistant import AnswerStream
from app.services.telegram_links import LinkStore
from tests.test_contacts import people  # noqa: F401 - fikstura
from tests.test_sso_login import LOGIN, hub, net  # noqa: F401 - fikstura
from tests.test_telegram_bot import (
    BOT_TOKEN,
    TG_ID,
    WEBHOOK_URL,
    WebhookTelegram,
    _conflict,
    sign_init,
    text_update,
)

#: `test_contacts.LIST` dagi to'qima odam va uning telefoni.
PERSON_Q = "Nazarova Dilnozaning telefoni?"
PHONE = "+998935554433"


def _no_assistant(*args, **kwargs):
    raise AssertionError("bu savol yuqoridagi xizmatga bormasligi kerak")


#: Yuqoridagi xizmatning soxta javobi: bot, webhook va kanal yo'lini tekshirish
#: uchun (kontakt savollari ham endi yordamchiga ketadi - `contacts_chat` yo'q).
ANSWER = "Javob tayyor."


def _fixed_answer(question, **kwargs):
    lines = [{"type": "token", "text": ANSWER},
             {"type": "done", "route": "rules", "request_id": "r-fixed"}]
    return AnswerStream(request_id="r-fixed",
                        frames=iter(json.dumps(x).encode() + b"\n" for x in lines))


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


# --- SSO odam: mini app -> bot -> yordamchi -----------------------------------------


def test_sso_odam_ulanadi_botda_savol_beradi_muddat_siljiydi(
    client, hub, net, people, telegram_api, real_directory, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _fixed_answer)
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
    assert ANSWER in telegram_api.texts()[-1]
    # Savol muddatni yangiladi (prod: "oxirgi faollikdan 30 kun").
    assert links.lookup(TG_ID, now=time.time() + 2 * 86400)[1] == "linked"


def test_webhook_orqali_sso_odam_javob_oladi(
    client, hub, net, people, telegram_api, real_directory, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _fixed_answer)
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
    assert ANSWER in telegram_api.texts()[-1]


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

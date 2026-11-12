"""Telegram Mini App: BRB-Tech ID orqali birinchi kirish - brauzerda tasdiq (`api/v1/telegram.py`,
"BRB-Tech ID orqali ulash"; 2026-11-12, ega so'rovi).

Oqim: Mini App imzo bilan chipta oladi -> havola brauzerda ochiladi -> odam Barno'ga kiradi va
tasdiq sahifasida "Ulash" ni bosadi (ulanish shu yerda yoziladi) -> Mini App chiptani O'Z imzosi
bilan yig'ib oladi va sessiya oladi.

Va'dalar:
  * kirishning o'zi hech narsani ulamaydi - faqat tasdiq; sahifa Telegram ismi/@username'ni ko'rsatadi;
  * chiptani faqat uni yaratgan Telegram hisobi yig'ib oladi (boshqasi - eskirgan bilan bir xil 404);
  * chipta bir martalik; tasdiq ham bir martalik (ikkinchisi 404);
  * sessiya qoidalari `/telegram/session` niki: admin bloki - 403;
  * soxta/eskirgan imzo, sozlanmagan server, chegaralar.

Hammasi germetik: bot tokeni soxta, Telegram'ga chiqilmaydi.
"""

from __future__ import annotations

import time

from urllib.parse import parse_qs, urlsplit

import pytest

from app.api.v1 import telegram as telegram_api
from app.core.config import settings
from app.services import analytics
from app.services.analytics.db import get_db
from app.services.link_tickets import TicketStore
from tests.test_telegram_bot import TG_ID, sign_init

APP = "https://llm.test"
TICKET = "/api/v1/telegram/link-ticket"
MINIAPP = {"X-Venera-Client": "miniapp"}
LOGIN_FIELDS = {"token", "tokenType", "expiresAt", "passwordChangeRequired", "user"}
OTHER_TG = TG_ID + 1


@pytest.fixture
def tg(monkeypatch):
    import app.bot as bot_module
    from tests.test_telegram_bot import BOT_TOKEN

    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(settings, "sso_app_url", APP, raising=False)
    for limiter in (telegram_api._session_limiter, telegram_api._ticket_limiter, telegram_api._claim_limiter):
        limiter.reset()
    telegram_api.TICKETS.clear()
    yield bot_module.links
    telegram_api.TICKETS.clear()


def _init(tg_id: int = TG_ID, **kw) -> str:
    return sign_init({"id": tg_id, "first_name": "Ali", "last_name": "Valiyev", "username": "ali"}, **kw)


def _ticket(client, init: str | None = None):
    return client.post(TICKET, json={"initData": init or _init()}, headers=MINIAPP)


def _claim(client, ticket: str, init: str | None = None):
    return client.post(f"{TICKET}/claim", json={"ticket": ticket, "initData": init or _init()}, headers=MINIAPP)


def _new_ticket(client) -> str:
    response = _ticket(client)
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


# --- butun oqim --------------------------------------------------------------------------


def test_butun_oqim_brauzerda_tasdiq_va_sessiya(client, tg, user_auth):
    response = _ticket(client)
    assert response.status_code == 200, response.text
    body = response.json()
    ticket = body["ticket"]
    parsed = urlsplit(body["url"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{APP}/link/telegram"
    assert parse_qs(parsed.query) == {"t": [ticket]}, "havolada Telegram id yo'q - faqat chipta"
    assert body["expiresIn"] == int(telegram_api.LINK_TICKET_TTL)

    # Hali tasdiqlanmagan: Mini App kutadi, ulanish yo'q.
    assert _claim(client, ticket).json() == {"status": "pending", "session": None}
    assert tg.lookup(TG_ID)[0] is None

    # Tasdiq sahifasi: kirmagan - 401; kirgan - kim kimga ulanyapti (chiptani yoqmaydi).
    assert client.get(f"{TICKET}/{ticket}").status_code == 401
    info = client.get(f"{TICKET}/{ticket}", headers=user_auth)
    assert info.status_code == 200, info.text
    assert info.json()["telegramName"] == "Ali Valiyev" and info.json()["telegramUsername"] == "ali"
    assert info.json()["accountName"] == "Demo Foydalanuvchi"
    assert client.get(f"{TICKET}/{ticket}", headers=user_auth).status_code == 200

    done = client.post(f"{TICKET}/confirm", json={"ticket": ticket}, headers=user_auth)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "new"
    assert tg.lookup(TG_ID)[0].actor_id == 2, "ulanish tasdiqda yoziladi"
    # Tasdiqlangan chipta sahifa uchun endi yo'q, ikkinchi tasdiq - 404.
    assert client.get(f"{TICKET}/{ticket}", headers=user_auth).status_code == 404
    assert client.post(f"{TICKET}/confirm", json={"ticket": ticket}, headers=user_auth).status_code == 404

    claimed = _claim(client, ticket)
    assert claimed.status_code == 200, claimed.text
    result = claimed.json()
    assert result["status"] == "ready" and set(result["session"]) == LOGIN_FIELDS
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {result['session']['token']}"})
    assert me.status_code == 200 and me.json()["actorId"] == 2
    # Chipta bir martalik.
    assert _claim(client, ticket).status_code == 404

    analytics.flush()
    methods = [row["method"] for row in get_db().rows("SELECT * FROM auth_events ORDER BY id")]
    assert "tg_link" in methods and "telegram" in methods


def test_boshqa_telegram_hisobi_chiptani_ola_olmaydi(client, tg, user_auth):
    ticket = _new_ticket(client)
    client.post(f"{TICKET}/confirm", json={"ticket": ticket}, headers=user_auth)
    stranger = _claim(client, ticket, _init(OTHER_TG))
    assert stranger.status_code == 404, "boshqa odamning chiptasi - eskirgan bilan bir xil"
    assert tg.lookup(OTHER_TG)[0] is None
    assert _claim(client, ticket).json()["status"] == "ready", "egasi uchun chipta joyida"


def test_bloklangan_hisob_sessiya_olmaydi(client, tg, auth, user_auth):
    ticket = _new_ticket(client)
    assert client.post(f"{TICKET}/confirm", json={"ticket": ticket}, headers=user_auth).status_code == 200
    assert client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True}).status_code == 200
    assert _claim(client, ticket).status_code == 403


# --- imzo, sozlama, muddat, chegaralar ----------------------------------------------------


def test_soxta_va_eskirgan_imzo(client, tg):
    assert _ticket(client, _init(token="999:soxta-token")).status_code == 400
    stale = _init(auth_date=int(time.time()) - settings.telegram_init_max_age - 60)
    assert _ticket(client, stale).status_code == 400
    ticket = _new_ticket(client)
    assert _claim(client, ticket, stale).status_code == 400


def test_sozlanmagan_server_501(client, tg, monkeypatch):
    monkeypatch.setattr(settings, "sso_app_url", "", raising=False)
    assert _ticket(client).status_code == 501
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert _ticket(client).status_code == 501


def test_chipta_muddati_otadi(client, tg, user_auth, monkeypatch):
    ticket = _new_ticket(client)
    later = time.time() + telegram_api.LINK_TICKET_TTL + 1
    monkeypatch.setattr(telegram_api.time, "time", lambda: later)
    from app.services import link_tickets

    monkeypatch.setattr(link_tickets.time, "time", lambda: later)
    assert client.get(f"{TICKET}/{ticket}", headers=user_auth).status_code == 404
    assert client.post(f"{TICKET}/confirm", json={"ticket": ticket}, headers=user_auth).status_code == 404


def test_chipta_chegarasi(client, tg):
    for _ in range(10):
        assert _ticket(client).status_code == 200
    blocked = _ticket(client)
    assert blocked.status_code == 429 and blocked.headers.get("Retry-After")
    assert _ticket(client, _init(OTHER_TG)).status_code == 200, "chegara har Telegram hisobiga alohida"


def test_yaroqsiz_chipta_shakli(client, tg, user_auth):
    assert client.post(f"{TICKET}/confirm", json={"ticket": "../../x"}, headers=user_auth).status_code == 422
    assert client.post(f"{TICKET}/confirm", json={"ticket": "a" * 43}, headers=user_auth).status_code == 404
    assert _claim(client, "a" * 43).status_code == 404


def test_chiptalar_ombori_swap_bir_martalik():
    store: TicketStore = TicketStore(60)
    first = telegram_api.TgTicket(tg_id=1, name="", username="", created=time.time())
    value = store.new(first)
    confirmed = telegram_api.TgTicket(tg_id=1, name="", username="", created=first.created, actor_id=7)
    assert store.swap(value, first, confirmed) is True
    assert store.swap(value, first, confirmed) is False, "ikkinchi tasdiq o'tmaydi"
    assert store.replace("yo'q", first) is False and store.pop(value) == confirmed and store.peek(value) is None

"""Birlashtirish: prod + SSO/"Pro" + `venera-admin-redesign` UCHRASHADIGAN joylar.

Har shox o'zini o'z testlarida sinaydi (`test_contacts.py`, `test_pro.py`,
`test_capture.py`, `test_access_control.py`...). Bu fayl faqat birlashtirishda
QO'LDA ulangan yo'llarni sinaydi:

  * "Pro" rejimi izda: so'ralgani (`pro.requested`) va yuqoridagi xizmat
    bergan natija (`pro` kadri);
  * bloklangan odamni bot rad etadi.

Xodimlar ma'lumotnomasining chat javoblari va tahrirlari (`contacts_chat`)
2026-10-07 olib tashlandi - ularning testlari ham.

Tarmoqqa chiqilmaydi: Keycloak, HRM, Telegram va yordamchi - soxta.
"""

from __future__ import annotations

import json

import pytest

import app.bot as bot_module
from app.api.v1 import chat as chat_api
from app.bot.runner import _BLOCKED, Backend, VeneraBot
from app.services import analytics
from tests.test_contacts import people  # noqa: F401 - fikstura
from tests.test_integration_merge import (
    PERSON_Q,
    PHONE,
    _no_assistant,
    _sso_login,
    real_directory,  # noqa: F401 - fikstura
    telegram_api,  # noqa: F401 - fikstura
)
from tests.test_pro import PRO_BLOCK, api, assistant, server  # noqa: F401 - fikstura
from tests.sso_fake import hub, net  # noqa: F401 - fikstura
from tests.test_telegram_bot import TG_ID, text_update



@pytest.fixture
def db(_isolated_analytics):
    return _isolated_analytics


def rows(db, sql: str, params=()) -> list[dict]:
    analytics.flush()
    return db.rows(sql, params)


def events(db, turn_id: str) -> list[dict]:
    return rows(db, "SELECT * FROM turn_events WHERE turn_id=? ORDER BY seq", (turn_id,))


def payload(event: dict) -> dict:
    return json.loads(event["payload"]) if event["payload"] else {}


# --- "Pro" izda -------------------------------------------------------------------


def test_pro_rejimi_izda(api, auth, server, people, db):
    r = api.post("/api/v1/chat/stream", headers=auth,
                 json={"question": "Yillik ta'til necha kun?", "mode": "pro"})
    assert r.status_code == 200 and server.calls[-1]["body"]["mode"] == "pro"
    [turn] = rows(db, "SELECT * FROM turns")
    assert (turn["route"], turn["status"]) == ("rules", "ok")
    by_name = {e["name"]: e for e in events(db, turn["id"])}
    assert payload(by_name["pro.requested"]) == {"mode": "pro"}
    assert by_name["pro"]["type"] == "frame"
    assert payload(by_name["pro"]) == PRO_BLOCK
    assert {"tokens", "assistant.open"} <= set(by_name) and "contacts" not in by_name

    # Standart savolda "Pro" haqida hech narsa yo'q.
    api.post("/api/v1/chat/stream", headers=auth, json={"question": "Salom"})
    turn = rows(db, "SELECT * FROM turns WHERE question='Salom'")[0]
    assert not {"pro.requested", "pro"} & {e["name"] for e in events(db, turn["id"])}


# --- samarali rollar: admin panel, ADMIN_LOGINS, blok -----------------------------


def test_bloklangan_odam_botda_rad_etiladi_ulanish_qoladi(
    client, auth, hub, net, people, telegram_api, real_directory, db, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, headers = _sso_login(client)
    bot_module.links.link(TG_ID, actor)
    r = client.patch(f"/api/v1/admin/users/{actor}", headers=auth, json={"disabled": True})
    assert r.status_code == 200, r.text

    bot = VeneraBot(telegram_api, bot_module.links, users=real_directory, backend=Backend(),
                    inline=True, typing_every=None)
    bot.handle_update(text_update(PERSON_Q))
    assert telegram_api.texts()[-1] == _BLOCKED
    assert PHONE not in " ".join(telegram_api.texts())
    assert bot_module.links.lookup(TG_ID)[1] == "linked", "blokda ulanish UZILMAYDI"
    assert rows(db, "SELECT * FROM turns WHERE channel='bot'") == []
    # Veb sessiya ham to'xtaydi.
    assert client.post("/api/v1/chat/stream", headers=headers,
                       json={"question": PERSON_Q}).status_code == 401

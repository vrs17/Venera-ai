"""Birlashtirish: prod + SSO/"Pro" + `venera-admin-redesign` UCHRASHADIGAN joylar.

Har shox o'zini o'z testlarida sinaydi (`test_contacts.py`, `test_pro.py`,
`test_capture.py`, `test_access_control.py`...). Bu fayl faqat birlashtirishda
QO'LDA ulangan yo'llarni sinaydi:

  * xodimlar ma'lumotnomasi javobi ham savol izi (`turns`) bo'lib yoziladi -
    web, mini app va bot bitta `chat.open_stream` yo'lidan;
  * "Pro" rejimi izda: so'ralgani (`pro.requested`) va yuqoridagi xizmat
    bergan natija (`pro` kadri);
  * kontakt tahriri SAMARALI rollarga qaraydi: admin paneldan berilgan ADMIN
    va `ADMIN_LOGINS` ham yetadi, bloklangan odamni bot rad etadi;
  * kontakt taklifini tasdiqlash (`ct_`) yiqilmaydi va yordamchi takliflari
    holatiga (`turns.proposal_status`) tegmaydi.

Tarmoqqa chiqilmaydi: Keycloak, HRM, Telegram va yordamchi - soxta.
"""

from __future__ import annotations

import json
import re

import pytest

import app.bot as bot_module
from app.api.v1 import chat as chat_api
from app.bot.runner import _BLOCKED, Backend, VeneraBot
from app.core.config import settings
from app.services import analytics
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
from tests.test_telegram_bot import TG_ID, text_update

TURN = re.compile(r"[0-9a-f]{32}")


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


# --- ma'lumotnoma javobi - savol izida --------------------------------------------


def test_kontakt_javobi_savol_izida_kanali_bilan(client, auth, people, db, monkeypatch):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    r = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "miniapp"},
                    json={"question": PERSON_Q, "chatId": "c-1"})
    assert r.status_code == 200, r.text
    assert PHONE in r.text
    turn_id = r.headers["X-Venera-Turn"]
    assert TURN.fullmatch(turn_id)
    assert r.headers["X-Venera-Request-Id"]

    [turn] = rows(db, "SELECT * FROM turns")
    assert turn["id"] == turn_id
    assert (turn["channel"], turn["kind"], turn["status"], turn["route"]) == (
        "miniapp", "chat", "ok", "contacts")
    assert (turn["actor_id"], turn["chat_id"], turn["question"]) == (1, "c-1", PERSON_Q)
    assert PHONE in turn["answer"] and turn["ttft_ms"] is not None
    names = [(e["type"], e["name"]) for e in events(db, turn_id)]
    assert ("span", "contacts") in names and ("frame", "done") in names
    # Yordamchiga borilmadi: tokenlar ham, ulanish ham yo'q.
    assert ("span", "tokens") not in names and ("span", "assistant.open") not in names
    [lookup] = [e for e in events(db, turn_id) if e["name"] == "contacts"]
    assert payload(lookup) == {"answered": True}
    assert rows(db, "SELECT * FROM api_calls WHERE service='assistant'") == []


def test_kontakt_taklifi_izda_tasdiq_yiqilmaydi(client, auth, people, db, monkeypatch):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": EDIT_Q})
    proposal = next(f["proposal"] for f in _frames(r.text) if f["type"] == "proposal")
    assert proposal["token"].startswith("ct_")

    [turn] = rows(db, "SELECT * FROM turns")
    assert (turn["has_proposal"], turn["proposal_token"], turn["route"]) == (
        1, proposal["token"], "contacts")

    r = client.post(f"/api/v1/actions/{proposal['token']}/confirm", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert people.find("Nazarova Dilnoza")[0][0].phone == "+998901234567"
    # Holat faqat YORDAMCHI takliflari uchun yangilanadi (`actions._run`, `verb`).
    [turn] = rows(db, "SELECT proposal_status FROM turns")
    assert turn["proposal_status"] == "pending"


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
    assert {"tokens", "assistant.open", "contacts"} <= set(by_name)

    # Kontakt savoli "Pro" bilan: so'ralgani izda, lekin `pro` kadri yo'q -
    # yordamchiga ham, byudjetga ham borilmadi.
    calls = len(server.calls)
    r = api.post("/api/v1/chat/stream", headers=auth, json={"question": PERSON_Q, "mode": "pro"})
    assert r.status_code == 200 and len(server.calls) == calls
    turn = rows(db, "SELECT * FROM turns WHERE route='contacts'")[0]
    names = {e["name"] for e in events(db, turn["id"])}
    assert "pro.requested" in names and "pro" not in names

    # Standart savolda "Pro" haqida hech narsa yo'q.
    api.post("/api/v1/chat/stream", headers=auth, json={"question": "Salom"})
    turn = rows(db, "SELECT * FROM turns WHERE question='Salom'")[0]
    assert not {"pro.requested", "pro"} & {e["name"] for e in events(db, turn["id"])}


# --- bot: bitta yo'l, `bot` kanali ------------------------------------------------


def test_bot_kontakt_javobi_bot_kanali_bilan_yoziladi(
    client, hub, net, people, telegram_api, real_directory, db, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, _ = _sso_login(client)
    bot_module.links.link(TG_ID, actor)
    bot = VeneraBot(telegram_api, bot_module.links, users=real_directory, backend=Backend(),
                    inline=True, typing_every=None)
    bot.handle_update(text_update(PERSON_Q))
    assert PHONE in telegram_api.texts()[-1]

    [turn] = rows(db, "SELECT * FROM turns WHERE channel='bot'")
    assert (turn["kind"], turn["route"], turn["status"], turn["actor_id"]) == (
        "bot", "contacts", "ok", actor)
    assert PHONE in turn["answer"]


# --- samarali rollar: admin panel, ADMIN_LOGINS, blok -----------------------------


def test_admin_paneldan_berilgan_admin_kontaktni_tahrirlaydi(
    client, auth, hub, net, people, telegram_api, real_directory, monkeypatch,
):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    actor, headers = _sso_login(client)
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    assert "faqat administrator" in r.text

    # Admin panel: ADMIN rolini beradi - o'sha sessiya qayta kirmasdan muharrir.
    r = client.patch(f"/api/v1/admin/users/{actor}", headers=auth,
                     json={"roles": ["employee", "crm-user", "ADMIN"]})
    assert r.status_code == 200, r.text
    assert "ADMIN" in r.json()["roles"]
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    proposal = next(f["proposal"] for f in _frames(r.text) if f["type"] == "proposal")
    r = client.post(f"/api/v1/actions/{proposal['token']}/confirm", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text

    # Bot ham o'sha samarali rollar bilan (`admin_users.access`).
    bot_module.links.link(TG_ID, actor)
    bot = VeneraBot(telegram_api, bot_module.links, users=real_directory, backend=Backend(),
                    inline=True, typing_every=None)
    bot.handle_update(text_update("Isroilov Botirning telefonini +998901110000 ga o'zgartir"))
    assert "faqat administrator" not in " ".join(telegram_api.texts())
    # Taklif kartasi "Tasdiqlash" tugmasi bilan keldi - kalit `ct_`.
    buttons = [kw["reply_markup"] for _, kw in telegram_api.calls if kw.get("reply_markup")]
    assert any("a:c:ct_" in json.dumps(markup) for markup in buttons), buttons


def test_admin_logins_kontakt_tahririga_yetadi(client, hub, net, people, monkeypatch):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    monkeypatch.setattr(settings, "admin_logins", "y.mamajonov")
    _, headers = _sso_login(client)
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": EDIT_Q})
    assert '"proposal"' in r.text and "faqat administrator" not in r.text


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

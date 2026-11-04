"""Slack «🎙 Plaud» (`app/slack/home.py`): chatdagi xush kelibsiz xabari, oddiy matnga yo'riqnoma,
`/plaud`, tugma va "Home" varag'i."""

from __future__ import annotations

from app.slack import home, meeting
from slack_fakes import FakeSlack


def _text(text="salom", **extra):
    return {"type": "message", "channel_type": "im", "channel": "D1", "user": "U1", "text": text, "ts": "1.1", **extra}


def test_bosh_chat_ochilganda_xush_kelibsiz_tugma_bilan():
    client = FakeSlack()
    home.on_open(client, {"type": "app_home_opened", "user": "U1", "tab": "messages", "channel": "D1"})
    [sent] = client.posted
    assert sent["channel"] == "D1" and sent["text"].startswith("🎙 *Plaud*")
    [button] = next(b for b in sent["blocks"] if b["type"] == "actions")["elements"]
    assert button["action_id"] == home.PLAUD_ACTION and button["text"]["text"] == "🎙 Plaud"
    # Chat bo'sh emas - qayta yozilmaydi.
    client.history["D1"] = [sent]
    home.on_open(client, {"type": "app_home_opened", "user": "U1", "tab": "messages", "channel": "D1"})
    assert len(client.posted) == 1


def test_oddiy_matnga_yoriqnoma_bir_marta(monkeypatch):
    monkeypatch.setattr(home, "_hint_at", {})
    client = FakeSlack()
    event = _text()
    assert home.is_text(event) and not meeting.wants(event)
    assert not home.is_text(_text(thread_ts="0.5"))            # thread'dagi savol - `meeting`
    assert not home.is_text(_text(bot_id="B1")) and not home.is_text(_text(channel_type="channel"))
    home.on_text(client, event)
    home.on_text(client, event)
    assert len(client.posted) == 1 and client.posted[0]["text"].startswith("🎙 *Plaud*")
    assert any(b["type"] == "actions" for b in client.posted[0]["blocks"])


def test_plaud_buyrugi_va_tugma():
    client = FakeSlack()
    home.on_command(client, {"command": "/plaud", "channel_id": "D1", "user_id": "U1"})
    assert client.posted[-1]["channel"] == "D1" and client.posted[-1]["text"].startswith("🎙 *Plaud*")
    # Chatdagi tugma - faqat bosgan odamga eslatma; Home'dagi tugma - chatga xabar.
    body = {"user": {"id": "U1"}, "channel": {"id": "D1"}, "actions": [{"action_id": home.PLAUD_ACTION}]}
    assert home.is_plaud(body) and not home.is_plaud({"actions": [{"action_id": "barno_tasks"}]})
    home.on_plaud(client, body)
    assert client.ephemeral[-1]["user"] == "U1" and client.ephemeral[-1]["channel"] == "D1"
    home.on_plaud(client, {"user": {"id": "U1"}, "container": {"type": "view"}, "actions": [{"action_id": home.PLAUD_ACTION}]})
    assert client.posted[-1]["channel"] == "U1"


def test_home_varagi():
    client = FakeSlack()
    home.on_open(client, {"type": "app_home_opened", "user": "U1", "tab": "home"})
    [published] = client.published
    blocks = published["view"]["blocks"]
    assert published["user_id"] == "U1" and blocks[0]["text"]["text"] == "Barno AI" and home.TAGLINE in blocks[1]["text"]["text"]
    assert next(b for b in blocks if b["type"] == "actions")["elements"][0]["action_id"] == home.PLAUD_ACTION


def test_slack_xatosi_odamni_toxtatmaydi(monkeypatch):
    monkeypatch.setattr(home, "_hint_at", {})

    class Broken(FakeSlack):
        def views_publish(self, **kwargs):
            raise RuntimeError("tarmoq")

        def chat_postMessage(self, **kwargs):
            raise RuntimeError("tarmoq")

    client = Broken()
    home.on_open(client, {"user": "U1"})
    home.on_text(client, _text())
    home.on_command(client, {"channel_id": "D1"})
    home.on_plaud(client, {"user": {"id": "U1"}, "actions": [{"action_id": home.PLAUD_ACTION}]})

"""Slack App Home (`app/slack/home.py`): "Home" varag'i va «🎙 Plaud» tugmasi."""

from __future__ import annotations

from app.slack import home
from slack_fakes import FakeSlack


def test_home_varagi_yoziladi_va_plaud_tugmasi_bor():
    client = FakeSlack()
    home.on_open(client, {"type": "app_home_opened", "user": "U1", "tab": "home"})
    [published] = client.published
    assert published["user_id"] == "U1" and published["view"]["type"] == "home"
    blocks = published["view"]["blocks"]
    assert blocks[0]["text"]["text"] == "Barno AI" and home.TAGLINE in blocks[1]["text"]["text"]
    [button] = next(b for b in blocks if b["type"] == "actions")["elements"]
    assert button["action_id"] == home.PLAUD_ACTION and button["text"]["text"] == "🎙 Plaud"
    assert any("Nimalar qila oladi" in (b.get("text") or {}).get("text", "") for b in blocks)
    # "Messages" varag'i ochilsa - yozilmaydi.
    home.on_open(client, {"type": "app_home_opened", "user": "U1", "tab": "messages"})
    assert len(client.published) == 1


def test_plaud_tugmasi_chatga_yoriqnoma_yozadi():
    client = FakeSlack()
    body = {"type": "block_actions", "user": {"id": "U1"}, "container": {"type": "view"},
            "actions": [{"action_id": home.PLAUD_ACTION, "value": "plaud"}]}
    assert home.is_plaud(body) and not home.is_plaud({"actions": [{"action_id": "barno_tasks"}]})
    home.on_plaud(client, body)
    [sent] = client.posted
    assert sent["channel"] == "U1" and sent["text"].startswith("🎙 *Plaud*") and sent["blocks"]


def test_slack_xatosi_odamni_toxtatmaydi():
    class Broken(FakeSlack):
        def views_publish(self, **kwargs):
            raise RuntimeError("tarmoq")

        def chat_postMessage(self, **kwargs):
            raise RuntimeError("tarmoq")

    client = Broken()
    home.on_open(client, {"user": "U1"})
    home.on_plaud(client, {"user": {"id": "U1"}, "actions": [{"action_id": home.PLAUD_ACTION}]})

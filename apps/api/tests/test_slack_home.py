"""Slack «🎙 Plaud» (`app/slack/home.py`): chatdagi xush kelibsiz xabari, thread'dan tashqaridagi matnni ajratish
(`is_text` - HR/CRM yordamchisiga), `/plaud`, tugma va "Home" varag'i."""

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
    # Savol qoidasi (ega qarori 2026-11-13, "thread qoidasi"): yozuv haqida - o'sha xabarning thread'ida; chatning
    # o'ziga yozilgani - Barno AI yordamchisiga (HR, CRM).
    assert "o'sha yozuv xabarining thread'iga yozing" in sent["text"] and "suhbatni eslab qoladi" in sent["text"]
    assert "*Barno AI yordamchisi* — chatning o'ziga yozing" in sent["text"] and "CRM" in sent["text"]
    assert "oxirgi yuborilgan yozuv" not in sent["text"]
    button, voice_button = next(b for b in sent["blocks"] if b["type"] == "actions")["elements"]
    assert button["action_id"] == home.PLAUD_ACTION and button["text"]["text"] == "🎙 Plaud"
    # Yonida «🗣 Ovoz namunasi» (ega qarori 2026-11-18, `slack/voice.py`).
    assert voice_button["action_id"] == "barno_voice" and "Ovoz namunasi" in str(sent["blocks"])
    # Chat bo'sh emas - qayta yozilmaydi.
    client.history["D1"] = [sent]
    home.on_open(client, {"type": "app_home_opened", "user": "U1", "tab": "messages", "channel": "D1"})
    assert len(client.posted) == 1


def test_thread_tashqarisidagi_matn_ajratiladi():
    """`is_text` - shaxsiy chatda thread'dan tashqaridagi odam matni (dispetcher uni HR/CRM yordamchisiga beradi);
    thread'dagi savol - `meeting`, bot xabari va kanal - yo'q."""
    event = _text()
    assert home.is_text(event) and not meeting.wants(event)
    assert not home.is_text(_text(thread_ts="0.5"))            # thread'dagi savol - `meeting`
    assert not home.is_text(_text(bot_id="B1")) and not home.is_text(_text(channel_type="channel"))
    assert not home.is_text(_text(subtype="message_changed")) and not home.is_text(_text(text="   "))


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
    """Home varag'ida faqat shior: «🎙 Plaud» tugmasi, sarlavha va imkoniyatlar ro'yxati yo'q (ega so'rovi)."""
    client = FakeSlack()
    home.on_open(client, {"type": "app_home_opened", "user": "U1", "tab": "home"})
    [published] = client.published
    assert published["user_id"] == "U1"
    from app.slack import voice as slack_voice

    assert published["view"] == {"type": "home", "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": "BRB-TECHning foydali, aniq va xavfsiz AI yordamchisi"}},
        {"type": "divider"}, *slack_voice.home_blocks()]}


def test_slack_xatosi_odamni_toxtatmaydi():
    class Broken(FakeSlack):
        def views_publish(self, **kwargs):
            raise RuntimeError("tarmoq")

        def chat_postMessage(self, **kwargs):
            raise RuntimeError("tarmoq")

    client = Broken()
    home.on_open(client, {"user": "U1"})
    home.on_command(client, {"channel_id": "D1"})
    home.on_plaud(client, {"user": {"id": "U1"}, "actions": [{"action_id": home.PLAUD_ACTION}]})

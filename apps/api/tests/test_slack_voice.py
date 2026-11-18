"""Slack «🗣 Ovoz namunasi» (`app/slack/voice.py`): "Home" va Plaud yo'riqnomasidagi tugma, shaxsiy chatdagi
«ovoz namunasi» so'zi - tartib va matn, qurollanish; keyingi audio - namuna (Plaud yozuvi emas), natija thread'dagi
"⏳" o'rnida; faqat odamning O'Z hisobi; «🗑 Ovozimni o'chirish». Slack, GAPI - soxta."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.meetings import voice
from app.slack import home, link
from app.slack import voice as slack_voice
from slack_fakes import AUDIO, FakeSlack, setup
from test_slack_link import _linking_on
from test_voice_samples import FakeVoiceGapi, _Inline, result


@pytest.fixture
def vslack(users_file, monkeypatch, tmp_path, _isolated_meetings):
    setup(monkeypatch, users_file)
    _linking_on(monkeypatch, tmp_path)
    monkeypatch.setattr(slack_voice, "_armed", {})
    gapi = FakeVoiceGapi(accounts=(1,))
    _isolated_meetings.voice_gapi = gapi
    monkeypatch.setattr(voice, "_pool", _Inline())
    yield gapi, _isolated_meetings
    link.TICKETS.clear()


def _action(action_id, *, user="U2", channel=None):
    body = {"team": {"id": "T1"}, "user": {"id": user}, "actions": [{"action_id": action_id, "value": "x"}]}
    if channel:
        body["channel"] = {"id": channel}
    return body


def test_home_va_yoriqnomada_tugma():
    ids = [e.get("action_id") for b in home.view()["blocks"] for e in b.get("elements") or []]
    assert slack_voice.START_ACTION in ids
    prompt_ids = [e.get("action_id") for b in home.prompt_blocks() for e in b.get("elements") or []]
    assert prompt_ids == [home.PLAUD_ACTION, slack_voice.START_ACTION]


def test_ulanmagan_odamga_ulash_xabari(vslack):
    client = FakeSlack()
    slack_voice.on_action(client, _action(slack_voice.START_ACTION, channel="D1"))
    assert client.ephemeral and "Connect" in (client.ephemeral[-1].get("text") or "") + str(client.ephemeral[-1])
    assert not slack_voice.armed("T1", "U2")


def test_kalit_soz_tartib_va_namuna(vslack):
    gapi, rt = vslack
    link.store().link("T1", "U2", 2)
    client = FakeSlack(files={"F1": AUDIO})
    event = client.say("D1", "Ovoz namunasi", user="U2", team="T1")
    assert slack_voice.is_text(event)
    slack_voice.on_text(client, event)
    assert "O'qiladigan matn" in client.posted[-1]["text"] and slack_voice.armed("T1", "U2")
    audio = client.say("D1", files=[AUDIO], user="U2", team="T1")
    assert slack_voice.wants(audio) and not slack_voice.armed("T1", "U2")
    gapi.results = {1: [result("new", 100, "sp-a")]}
    slack_voice.on_audio(client, audio)
    assert client.posted[-1]["text"] == slack_voice.WAIT_TEXT and client.posted[-1]["thread_ts"] == audio["ts"]
    assert client.updated[-1]["text"] == voice.OK_TEXT
    row = rt.store.row("SELECT actor_id, channel, status FROM voice_samples")
    assert row == {"actor_id": 2, "channel": "slack", "status": "ok"}                # O'Z hisobi, umumiy emas
    assert rt.store.scalar("SELECT COUNT(*) FROM meetings", (), 0) == 0


def test_qurollanmagan_audio_plaud_ga_ketadi(vslack):
    client = FakeSlack(files={"F1": AUDIO})
    assert not slack_voice.wants(client.say("D1", files=[AUDIO], user="U2", team="T1"))


def test_rad_etilsa_qayta_qurollanadi_va_ochirish(vslack):
    gapi, rt = vslack
    link.store().link("T1", "U2", 2)
    client = FakeSlack(files={"F1": AUDIO})
    slack_voice.on_action(client, _action(slack_voice.START_ACTION))
    gapi.results = {1: [result(speech=7.0), result("new", 100, "sp-a")]}
    audio = client.say("D1", files=[AUDIO], user="U2", team="T1")
    assert slack_voice.wants(audio)
    slack_voice.on_audio(client, audio)
    assert client.updated[-1]["text"].startswith(voice.REASONS["too_short"]) and slack_voice.armed("T1", "U2")
    again = client.say("D1", files=[AUDIO], user="U2", team="T1")
    assert slack_voice.wants(again)
    slack_voice.on_audio(client, again)
    assert client.updated[-1]["text"] == voice.OK_TEXT
    slack_voice.on_action(client, _action(slack_voice.START_ACTION))
    blocks = client.posted[-1]["blocks"]
    delete = [e for b in blocks for e in b.get("elements") or [] if e.get("action_id") == slack_voice.DELETE_ACTION]
    assert delete and delete[0]["confirm"]["confirm"]["text"] == "Ha, o'chirish"
    slack_voice.on_action(client, _action(slack_voice.DELETE_ACTION))
    assert client.posted[-1]["text"] == voice.DELETED_TEXT and ("delete", 1, "sp-a") in gapi.calls


def test_dispetcher_namunani_plauddan_oldin_oladi(vslack, monkeypatch):
    from app import slack as slack_pkg

    submitted = []

    class Pool:
        def submit(self, fn, *args, **kwargs):
            submitted.append(fn.__name__)

    monkeypatch.setattr(slack_pkg, "_pool", Pool())
    slack_voice.arm("T1", "U2")
    client = FakeSlack(files={"F1": AUDIO})
    event = client.say("D1", files=[AUDIO], user="U2", team="T1")
    slack_pkg._on_message(event, client, {"team_id": "T1", "bot_user_id": "UBOT"})
    assert submitted[-1] == "on_audio" and client.posted == []          # til savoli (Plaud) chiqmadi
    text = client.say("D1", "ovoz namunasi", user="U2", team="T1")
    slack_pkg._on_message(text, client, {"team_id": "T1", "bot_user_id": "UBOT"})
    assert submitted[-1] == "on_text"

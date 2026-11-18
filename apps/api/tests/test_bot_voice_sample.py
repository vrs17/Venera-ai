"""Telegram «🗣 Ovoz namunasi» (`app/bot/voice_sample.py`): tugma va `/ovoz` - tartib, matn, qurollanish; keyingi
ovozli xabar - namuna (Plaud yozuvi ham, HR savoli ham emas); natija "⏳" o'rnida; rad etilsa qayta qurollanadi;
o'chirish - tasdiq bilan. Telegram, GAPI - soxta (`test_bot_plaud.world`, `test_voice_samples.FakeVoiceGapi`)."""

from __future__ import annotations

import pytest

from app.bot import plaud as plaud_mod
from app.bot.runner import COMMANDS
from app.bot.voice_sample import BTN_VOICE, WAIT_TEXT
from app.services.meetings import voice
from meetings_fakes import ogg_opus_bytes
from test_bot_plaud import PlaudTelegram, last_edit, voice as voice_update, world  # noqa: F401 - fixture
from test_telegram_bot import TG_ID, callback, text_update
from test_voice_samples import FakeVoiceGapi, _Inline, result


@pytest.fixture
def vworld(world, monkeypatch):
    bot, tg, rt, plaud = world
    gapi = FakeVoiceGapi(accounts=(1,))
    rt.voice_gapi = gapi
    monkeypatch.setattr(voice, "_pool", _Inline())
    tg.files["voice/s1.oga"] = ogg_opus_bytes(40.0)
    return bot, tg, rt, plaud, gapi


def test_tugma_tartib_matn_va_namuna_qabul(vworld):
    bot, tg, rt, plaud, gapi = vworld
    bot.handle_update(text_update(BTN_VOICE))
    shown = tg.sent()[-1]["text"]
    assert "Qanday yoziladi" in shown and "O'qiladigan matn" in shown and "<blockquote>" in shown
    gapi.results = {1: [result("new", 100, "sp-a")]}
    bot.handle_update(voice_update("s1", duration=40, message_id=41))
    assert tg.sent()[-1]["text"] == WAIT_TEXT
    assert last_edit(tg)["text"] == voice.OK_TEXT
    assert last_edit(tg)["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "v:del"
    assert rt.store.row("SELECT channel, status FROM voice_samples") == {"channel": "telegram", "status": "ok"}
    assert rt.store.scalar("SELECT COUNT(*) FROM meetings", (), 0) == 0              # Plaud yozuvi EMAS
    # Qurollanish sarflandi: keyingi qisqa ovozli xabar namuna emas.
    assert not plaud.voice.armed(TG_ID)


def test_ovoz_buyrugi_va_klaviatura(vworld):
    bot, tg, rt, plaud, gapi = vworld
    bot.handle_update(text_update("/ovoz"))
    assert "O'qiladigan matn" in tg.sent()[-1]["text"] and plaud.voice.armed(TG_ID)
    assert "ovoz" in [c["command"] for c in COMMANDS]
    assert [{"text": BTN_VOICE}] in plaud_mod.KEYBOARD["keyboard"]


def test_rad_etilsa_qayta_qurollanadi(vworld):
    bot, tg, rt, plaud, gapi = vworld
    bot.handle_update(text_update(BTN_VOICE))
    gapi.results = {1: [result(speech=6.0), result("new", 100, "sp-a")]}
    bot.handle_update(voice_update("s1", duration=40, message_id=41))
    assert last_edit(tg)["text"].startswith(voice.REASONS["too_short"]) and plaud.voice.armed(TG_ID)
    bot.handle_update(voice_update("s1", duration=40, message_id=42))
    assert last_edit(tg)["text"] == voice.OK_TEXT


def test_plaud_tugmasi_namunani_bekor_qiladi(vworld):
    bot, tg, rt, plaud, gapi = vworld
    bot.handle_update(text_update(BTN_VOICE))
    bot.handle_update(text_update(plaud_mod.BTN_PLAUD))
    assert not plaud.voice.armed(TG_ID)
    bot.handle_update(text_update(BTN_VOICE))
    assert plaud.voice.armed(TG_ID) and not plaud.wants(TG_ID, {"kind": "voice", "duration": 5})


def test_ochirish_tasdiq_bilan(vworld):
    bot, tg, rt, plaud, gapi = vworld
    bot.handle_update(text_update(BTN_VOICE))
    gapi.results = {1: [result("new", 100, "sp-a")]}
    bot.handle_update(voice_update("s1", duration=40, message_id=41))
    bot.handle_update(callback("v:del"))
    confirm = tg.sent()[-1]
    assert [b["callback_data"] for b in confirm["reply_markup"]["inline_keyboard"][0]] == ["v:del!", "v:no"]
    bot.handle_update(callback("v:del!", message_id=99))
    assert last_edit(tg)["text"] == voice.DELETED_TEXT
    assert ("delete", 1, "sp-a") in gapi.calls and rt.store.rows("SELECT * FROM voice_links") == []

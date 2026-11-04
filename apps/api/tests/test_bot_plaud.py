"""Telegram "🎙 Plaud" (`app/bot/plaud.py`): tugma, ovozli xabar/audio fayl -> transkript va
"Qisqa xulosa", tugmalar (vazifalar, shablon, eksport, boshqa til), javob (Reply) bilan savol.

Telegram ham, GAPI ham, model ham soxta (`test_telegram_bot.FakeTelegram`, `meetings_fakes`):
hech bir test tarmoqqa chiqmaydi. Fon ishchisi yo'q - kutish o'rniga navbat qo'lda yuritiladi.
"""

from __future__ import annotations

import pytest

from app.bot import plaud as plaud_mod
from app.bot.briefs import REPLY_KEYBOARD, REPLY_KEYBOARD_ADMIN
from app.bot.plaud import BTN_PLAUD, Plaud
from app.bot.runner import COMMANDS, VeneraBot
from app.core.config import settings
from app.core.security import hash_password
from app.services.meetings import intake
from app.services.telegram_links import LinkStore
from app.services.users import StoredUser, UserStore
from meetings_fakes import adts_bytes, enable, ogg_opus_bytes, run_all
from test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, callback, text_update

OTHER_TG = 5550002


@pytest.fixture
def world(tmp_path, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    users = UserStore({
        "a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali Valiyev", password_hash=hash_password("x")),
        "b@b.uz": StoredUser(actor_id=2, email="b@b.uz", full_name="Vali Aliyev", password_hash=hash_password("x")),
    })
    tg = FakeTelegram()
    tg.files["voice/v1.oga"] = ogg_opus_bytes(64.0)
    links = LinkStore(tmp_path / "links.json")
    links.link(TG_ID, 1)
    links.link(OTHER_TG, 2)
    rt = _isolated_meetings
    plaud = Plaud(tg, inline=True, sleep=lambda _sec: run_all(rt))
    bot = VeneraBot(tg, links, users=lambda: users, backend=FakeBackend(), webapp_url="https://llm.brb-tech.uz/tg/",
                    inline=True, typing_every=None, plaud=plaud)
    return bot, tg, rt, plaud


def voice(file_id="v1", *, duration=64, message_id=20, tg_id=TG_ID, reply_to=None):
    msg = {"message_id": message_id, "date": 1762250000, "from": {"id": tg_id, "is_bot": False},
           "chat": {"id": tg_id, "type": "private"},
           "voice": {"file_id": file_id, "file_unique_id": f"U{file_id}", "duration": duration,
                     "file_size": 4000, "mime_type": "audio/ogg"}}
    if reply_to:
        msg["reply_to_message"] = reply_to
    return {"update_id": 5, "message": msg}


def audio_file(file_id="a1", *, name="yigilish.aac", message_id=21, size=5000):
    return {"update_id": 6, "message": {
        "message_id": message_id, "date": 1762250000, "from": {"id": TG_ID, "is_bot": False},
        "chat": {"id": TG_ID, "type": "private"},
        "audio": {"file_id": file_id, "file_unique_id": f"U{file_id}", "duration": 64, "file_size": size,
                  "mime_type": "audio/aac", "file_name": name}}}


def reply(text, to, *, tg_id=TG_ID, message_id=30):
    update = text_update(text, tg_id=tg_id, message_id=message_id)
    update["message"]["reply_to_message"] = to
    return update


def card(tg):
    """Oxirgi "Qisqa xulosa" xabari (tugmalari bilan)."""
    return next(kw for kw in reversed(tg.sent()) if kw["text"].startswith("📋 <b>Qisqa xulosa</b>"))


def meeting_of(tg):
    return (card(tg)["reply_markup"]["inline_keyboard"][0][0]["callback_data"]).split(":")[2]


def test_tugma_va_buyruq_qurollantiradi_va_klaviatura_hammada(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update(BTN_PLAUD))
    assert tg.sent()[-1]["text"].startswith("🎙 <b>Plaud</b>") and tg.sent()[-1]["reply_markup"] == plaud_mod.KEYBOARD
    assert plaud.wants(TG_ID, {"kind": "voice", "duration": 5}) and not plaud.wants(TG_ID, {"kind": "voice", "duration": 5})
    bot.handle_update(text_update("/plaud"))
    assert plaud.wants(TG_ID, {"kind": "voice", "duration": 5})
    # Audio fayl va uzun ovozli xabar - qurollanmasdan ham.
    assert plaud.wants(TG_ID, {"kind": "audio"})
    assert plaud.wants(TG_ID, {"kind": "voice", "duration": settings.telegram_voice_max_sec + 1})
    assert [{"text": BTN_PLAUD}] in REPLY_KEYBOARD["keyboard"] and [{"text": BTN_PLAUD}] in REPLY_KEYBOARD_ADMIN["keyboard"]
    assert "plaud" in [c["command"] for c in COMMANDS]
    bot.handle_update(text_update("/start"))
    assert tg.sent()[-1]["reply_markup"] == plaud_mod.KEYBOARD          # oddiy xodimga - Plaud klaviaturasi


def test_ovozli_xabar_transkript_va_qisqa_xulosa(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    texts = tg.texts()
    assert any(t.startswith("⏳ Audio matnga") for t in texts)
    transcript = next(kw for kw in tg.sent() if kw["text"].startswith("🎙 <b>Transkript</b>"))
    assert "Assalomu alaykum" in transcript["text"]
    summary = card(tg)
    assert summary["text"].endswith(plaud_mod._HINT)
    rows = summary["reply_markup"]["inline_keyboard"]
    mid = meeting_of(tg)
    assert [b["callback_data"] for row in rows for b in row] == [f"p:t:{mid}", f"p:s:{mid}", f"p:e:{mid}", f"p:l:{mid}"]
    # Yozuv ODAMNING hisobida (actor 1), kanal `bot`, OGG sifatida.
    row = rt.store.meeting_any(mid)
    assert row["actor_id"] == 1 and row["channel"] == "bot" and row["content_type"] == "audio/ogg"
    assert row["title"].startswith("Telegram: ovozli xabar")
    holder = next(kw for kw in tg.sent() if kw["text"].startswith("⏳ Audio matnga"))
    assert holder["reply_to"] == 20
    assert ("delete_message", {"chat_id": TG_ID, "message_id": holder["message_id"]}) in tg.calls
    # Qurollanmagan qisqa ovozli xabar - avvalgidek HR savoli (chat STT).
    before = len(rt.gapi.submits)
    tg.files["voice/v9.oga"] = b"OggS-fake"
    bot.handle_update(voice("v9", duration=4))
    assert len(rt.gapi.submits) == before and bot.backend.audio


def test_bir_fayl_bir_yigilish_va_audio_fayl(world):
    bot, tg, rt, plaud = world
    tg.files["voice/a1.oga"] = adts_bytes(64.0)
    for _ in range(2):
        bot.handle_update(audio_file())
    assert len(rt.gapi.submits) == 1
    rows, total = rt.store.list_meetings(1, limit=10, offset=0)
    assert total == 1 and rows[0]["title"] == "Telegram: yigilish.aac" and rows[0]["content_type"] == "audio/aac"
    assert sum(1 for t in tg.texts() if t.startswith("🎙 <b>Transkript</b>")) == 2


def test_katta_fayl_va_yaroqsiz_format(world):
    bot, tg, rt, plaud = world
    bot.handle_update(audio_file("big", size=plaud_mod.MAX_FILE + 1))
    assert "20 MB" in tg.texts()[-1] and rt.gapi.submits == []
    tg.files["voice/x.oga"] = b"\x1aE\xdf\xa3" + b"\0" * 60          # webm
    bot.handle_update(audio_file("x"))
    assert tg.texts()[-1].startswith("Matnga o'girib bo'lmadi: Bu audio formati") and tg.sent()[-1]["reply_markup"] is None


def test_yuklab_bolmasa_qayta_urinish_tugmasi(world, monkeypatch):
    bot, tg, rt, plaud = world
    from app.services.integrations.telegram import TelegramError

    real = tg.download
    monkeypatch.setattr(tg, "download", lambda *a, **kw: (_ for _ in ()).throw(TelegramError("yo'q")))
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    failed = tg.sent()[-1]
    assert failed["text"].startswith("Matnga o'girib bo'lmadi")
    [[retry]] = failed["reply_markup"]["inline_keyboard"]
    assert retry["callback_data"] == "p:r:f:Uv1"
    monkeypatch.setattr(tg, "download", real)
    bot.handle_update(callback(retry["callback_data"], message_id=failed["message_id"]))
    assert "Assalomu alaykum" in card(tg)["text"] or any("Assalomu" in t for t in tg.texts())
    assert rt.store.list_meetings(1, limit=10, offset=0)[1] == 1


def test_savol_xulosa_xabariga_javob_bilan(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    summary = card(tg)
    bot.handle_update(reply("Kim hisobot yuboradi?", {"message_id": summary["message_id"], "from": {"is_bot": True}}))
    holder = tg.sent()[-1]
    assert holder["text"].startswith("⏳ Javob") and holder["reply_to"] == 30
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["message_id"] == holder["message_id"] and "📌 <b>Manbalar:</b>" in edited["text"]
    assert bot.backend.questions == []                                     # HR yordamchisiga ketmadi
    # Qayta ishga tushgandan keyin ham: xotira bo'sh, lekin xabar tugmalarida yig'ilish belgisi bor.
    plaud._messages.clear()
    bot.handle_update(reply("Yana?", {"message_id": summary["message_id"], "from": {"is_bot": True},
                                      "reply_markup": summary["reply_markup"]}, message_id=31))
    assert tg.sent()[-1]["text"].startswith("⏳ Javob")
    # O'z audio xabariga javob ham savol.
    bot.handle_update(reply("Qaror nima?", voice()["message"], message_id=32))
    assert tg.sent()[-1]["text"].startswith("⏳ Javob")
    # Begona odam shu xabarga javob yozsa - yig'ilish topilmaydi (404), oddiy savol bo'lib ketadi.
    bot.handle_update(reply("Nima?", {"message_id": summary["message_id"], "from": {"is_bot": True},
                                      "reply_markup": summary["reply_markup"]}, tg_id=OTHER_TG, message_id=33))
    assert bot.backend.questions and bot.backend.questions[-1][1] == 2
    # Oddiy HR javobiga javob - savol HR yordamchisiga.
    bot.handle_update(reply("salom", {"message_id": 999, "from": {"is_bot": True}}, message_id=34))
    assert bot.backend.questions[-1][0] == "salom"


def test_vazifalar_shablon_eksport(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    mid, summary_id = meeting_of(tg), card(tg)["message_id"]
    bot.handle_update(callback(f"p:t:{mid}", message_id=summary_id))
    assert tg.texts()[-1].startswith("✅ <b>Vazifalar</b>\n\n•")
    # Shablon menyusi - tugmalar almashadi; tanlov - yangi xulosa.
    bot.handle_update(callback(f"p:s:{mid}", message_id=summary_id))
    menu = [kw for n, kw in tg.calls if n == "edit_reply_markup"][-1]["reply_markup"]["inline_keyboard"]
    assert f"p:s:{mid}:minutes" in [b["callback_data"] for row in menu for b in row]
    assert f"p:s:{mid}:auto" not in [b["callback_data"] for row in menu for b in row]
    bot.handle_update(callback(f"p:s:{mid}:minutes", message_id=summary_id))
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["text"].startswith("🗂 <b>Xulosa: Bayonnoma</b>")
    # Eksport - fayl.
    bot.handle_update(callback(f"p:e:{mid}:txt", message_id=summary_id))
    bot.handle_update(callback(f"p:e:{mid}:docx", message_id=summary_id))
    txt, docx = tg.sent("send_document")
    assert txt["filename"].endswith(".txt") and docx["filename"].endswith(".docx") and docx["size"] > 0
    # Orqaga - asosiy tugmalar.
    bot.handle_update(callback(f"p:b:{mid}", message_id=summary_id))
    back = [kw for n, kw in tg.calls if n == "edit_reply_markup"][-1]["reply_markup"]
    assert back == plaud_mod.controls(mid, "uz")
    # Begona odam tugmani bossa - 404, hech narsa yuborilmaydi.
    before = len(tg.calls)
    bot.handle_update(callback(f"p:t:{mid}", message_id=summary_id, tg_id=OTHER_TG))
    assert [n for n, _ in tg.calls[before:]] == ["answer_callback"] and tg.calls[-1][1]["alert"]


def test_boshqa_tilda_qayta_ogirish_tasdiq_bilan(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    mid, summary_id = meeting_of(tg), card(tg)["message_id"]
    bot.handle_update(callback(f"p:l:{mid}", message_id=summary_id))
    menu = [kw for n, kw in tg.calls if n == "edit_reply_markup"][-1]["reply_markup"]["inline_keyboard"]
    assert [b["callback_data"] for row in menu for b in row] == [f"p:l:{mid}:ru", f"p:l:{mid}:en", f"p:b:{mid}"]
    bot.handle_update(callback(f"p:l:{mid}:ru", message_id=summary_id))
    confirm = [kw for n, kw in tg.calls if n == "edit_reply_markup"][-1]["reply_markup"]["inline_keyboard"]
    assert confirm[0][0]["callback_data"] == f"p:l:{mid}:ru:y" and "sarflanadi" in confirm[0][0]["text"]
    assert rt.router.calls == []
    bot.handle_update(callback(f"p:l:{mid}:ru:y", message_id=summary_id))
    assert [c["language"] for c in rt.router.calls] == ["ru"]
    assert any("Добрый день" in t for t in tg.texts())
    assert any(t == "✅ Audio rus tilida qayta o'girildi." for kw in tg.calls if kw[0] == "edit_message_text"
               for t in [kw[1]["text"]])
    last = card(tg)["reply_markup"]
    assert last == plaud_mod.controls(mid, "ru")


def test_kunlik_limit_tugasa_yozuv_ochiriladi(world, monkeypatch):
    bot, tg, rt, plaud = world
    monkeypatch.setattr(settings, "meetings_user_daily_minutes", 0, raising=False)
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    assert "limiti tugagan" in tg.texts()[-1] and rt.store.list_meetings(1, limit=10, offset=0)[1] == 0


def test_sof_funksiyalar():
    assert plaud_mod.title_of({"kind": "voice"}, 1762250000.0) == "Telegram: ovozli xabar 04.11.2025 14:53"
    assert plaud_mod.title_of({"kind": "audio", "file_name": "a.mp3"}, 0) == "Telegram: a.mp3"
    assert plaud_mod.html_of("## **Maqsad**\n- a\n| A | B |\n|---|---|\n| 1 | 2 |") == "<b>Maqsad</b>\n• a\nA | B\n1 | 2"
    assert plaud_mod.clock(3725) == "1:02:05" and plaud_mod.clock("x") == "0:00"
    assert Plaud.media({"document": {"file_id": "d", "file_name": "x.M4A"}})["kind"] == "document"
    assert Plaud.media({"document": {"file_id": "d", "file_name": "x.pdf"}}) is None
    assert intake.filename("attachment; filename=\"a.docx\"; filename*=UTF-8''b%20c.docx") == "b c.docx"

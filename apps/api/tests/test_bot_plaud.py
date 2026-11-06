"""Telegram "🎙 Plaud" (`app/bot/plaud.py`): tugma, ovozli xabar/audio fayl -> transkript va
"Qisqa xulosa", tugmalar (vazifalar, shablon, eksport, boshqa til), javob (Reply) bilan savol.

Telegram ham, GAPI ham, model ham soxta (`test_telegram_bot.FakeTelegram`, `meetings_fakes`):
hech bir test tarmoqqa chiqmaydi. Fon ishchisi yo'q - kutish o'rniga navbat qo'lda yuritiladi.
"""

from __future__ import annotations

import json

import pytest

from app.bot import plaud as plaud_mod
from app.bot.briefs import REPLY_KEYBOARD, REPLY_KEYBOARD_ADMIN
from app.bot.plaud import BTN_PLAUD, Plaud
from app.bot.runner import COMMANDS, VeneraBot
from app.core.config import settings
from app.core.security import hash_password
from app.services import archive
from app.services.meetings import export, intake, minutes
from app.services.telegram_links import LinkStore
from app.services.users import StoredUser, UserStore
from meetings_fakes import adts_bytes, enable, ogg_opus_bytes, run_all
from test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, callback, text_update
from app.services.integrations.telegram import TelegramError
from app.services.meetings.errors import MeetingProblem

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
    row = [{"text": BTN_PLAUD}, {"text": plaud_mod.BTN_APP}]                 # yonida - "📲 Ilovani yuklab olish"
    assert plaud_mod.KEYBOARD["keyboard"] == [row]
    assert row in REPLY_KEYBOARD["keyboard"] and row in REPLY_KEYBOARD_ADMIN["keyboard"]
    assert "plaud" in [c["command"] for c in COMMANDS]
    bot.handle_update(text_update("/start"))
    assert tg.sent()[-1]["reply_markup"] == plaud_mod.KEYBOARD          # oddiy xodimga - Plaud klaviaturasi


def test_ovozli_xabar_transkript_va_qisqa_xulosa(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    transcript = next(kw for kw in tg.sent() if kw["text"].startswith("🎙 <b>Transkript</b>"))
    assert "Assalomu alaykum" in transcript["text"]
    summary = card(tg)
    assert summary["text"].endswith(plaud_mod._HINT)
    rows = summary["reply_markup"]["inline_keyboard"]
    mid = meeting_of(tg)
    assert [b["callback_data"] for row in rows for b in row] == [f"p:t:{mid}", f"p:s:{mid}", f"p:e:{mid}", f"p:l:{mid}",
                                                               f"p:d:{mid}"]
    # Yozuv ODAMNING hisobida (actor 1), kanal `bot`, OGG sifatida.
    row = rt.store.meeting_any(mid)
    assert row["actor_id"] == 1 and row["channel"] == "bot" and row["content_type"] == "audio/ogg"
    assert row["title"].startswith("Telegram: ovozli xabar")
    # Jarayon xabari (ega talabi, 2026-11-05): ovozli xabarga javob qilib "qabul qilindi", bosqichlar
    # joyida yangilanadi; transkript ostida - xulosa bosqichi; natija chiqqach ikkalasi o'chadi.
    status = next(kw for kw in tg.sent() if kw["text"].startswith("🎙 Ovozli xabaringiz qabul qilindi."))
    assert status["reply_to"] == 20 and "\n\n⏳ Audio yuklanmoqda…\n◻️ Matnga o'girish\n" in status["text"]
    edits = [kw for n, kw in tg.calls if n == "edit_message_text" and kw["message_id"] == status["message_id"]]
    assert any("✅ Audio yuklandi (1 daq 4 s)\n⏳ Matnga o'girilmoqda…" in kw["text"] for kw in edits)
    waiting = next(kw for kw in tg.sent() if "⏳ Qisqa xulosa yozilmoqda…" in kw["text"])
    assert waiting["reply_to"] is None and "✅ Matnga o'girildi - matn yuqorida" in waiting["text"]
    order = [kw["message_id"] for kw in tg.sent()]
    assert order.index(transcript["message_id"]) < order.index(waiting["message_id"]) < order.index(summary["message_id"])
    deleted = [kw["message_id"] for n, kw in tg.calls if n == "delete_message"]
    assert deleted == [status["message_id"], waiting["message_id"]]
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
    # Yuklangan fayl - jarayon xabarida nomi bilan, fayl xabariga javob qilib.
    status = next(kw for kw in tg.sent() if kw["text"].startswith("📎 «yigilish.aac» qabul qilindi.\n\n⏳ Audio"))
    assert status["reply_to"] == 21


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
    status = next(kw for kw in tg.sent() if kw["text"].startswith("🎙 Ovozli xabaringiz qabul qilindi."))
    assert ("delete_message", {"chat_id": TG_ID, "message_id": status["message_id"]}) in tg.calls
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
    assert edited["text"].startswith("🗂 <b>Xulosa: Protokol</b>")
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


# --- 📄 Bayonnoma (ega qarori, 2026-11-04) ----------------------------------------------------------


def _minutes_view(**extra):
    view = {"id": "ab" * 16, "meetingId": "m", "language": "uz-cyrl", "status": "ready", "stale": False,
            "agendaCount": 2, "sectionCount": 2, "itemCount": 5,
            "notes": ["Muddat <aniq> emas", "Mas'ul aytilmagan"], "warnings": [], "error": None}
    view.update(extra)
    return view


def _minutes_export():
    calls = []

    def export_file(user, meeting_id, minutes_id, fmt):
        calls.append((meeting_id, minutes_id, fmt))
        media, ext = minutes.FORMATS[fmt]
        return fmt.encode(), media, export.content_disposition(
            *export.file_names("Баённома - Haftalik", 1762150000, ext))

    return export_file, calls


def _delivered(bot, tg):
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    return meeting_of(tg), card(tg)["message_id"]


def _last_markup(tg):
    return [kw for n, kw in tg.calls if n == "edit_reply_markup"][-1]["reply_markup"]


def test_bayonnoma_tugmasi_uchinchi_qatorda(world):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    rows = card(tg)["reply_markup"]["inline_keyboard"]
    assert rows[2] == [{"text": "📄 Bayonnoma", "callback_data": f"p:d:{mid}"}]
    # "Qayta urinish" qatori bo'lsa ham - u OXIRGI.
    retry_rows = plaud_mod.controls(mid, "uz", retry=f"p:r:m:{mid}")["inline_keyboard"]
    assert retry_rows[2][0]["callback_data"] == f"p:d:{mid}" and retry_rows[-1][0]["callback_data"] == f"p:r:m:{mid}"
    # Javob (Reply) uchun belgi: natija xabaridagi `p:d:<id>` ham yig'ilishni topadi.
    assert plaud_mod._MARK.match(f"p:d:{mid}").group(1) == mid


def test_bayonnoma_til_menyusi(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: pytest.fail("menyu modelni chaqirmasligi kerak"))
    bot.handle_update(callback(f"p:d:{mid}", message_id=summary_id))
    menu = _last_markup(tg)["inline_keyboard"]
    assert menu == plaud_mod.minutes_menu(mid, "uz")["inline_keyboard"]
    data = [b["callback_data"] for row in menu for b in row]
    # O'zbek yig'ilish: tavsiya kirill - BIRINCHI; keyin qolgan tillar `LANGS` tartibida; oxirida orqaga.
    assert data == [f"p:d:{mid}:uz-cyrl", f"p:d:{mid}:uz-latn", f"p:d:{mid}:ru", f"p:d:{mid}:en", f"p:b:{mid}"]
    assert [b["text"] for row in menu[:-1] for b in row] == [minutes.LANG_TITLES[l] for l in
                                                             ("uz-cyrl", "uz-latn", "ru", "en")]
    assert set(data[:-1]) == {f"p:d:{mid}:{lang}" for lang in minutes.LANGS}
    # Rus yig'ilish - rus birinchi.
    ru = plaud_mod.minutes_menu(mid, "ru")["inline_keyboard"]
    assert ru[0][0]["callback_data"] == f"p:d:{mid}:ru"
    # Noma'lum til - tugma eskirgan, model chaqirilmaydi.
    bot.handle_update(callback(f"p:d:{mid}:de", message_id=summary_id))
    assert tg.calls[-1][0] == "answer_callback" and tg.calls[-1][1]["text"] == "Tugma eskirgan"


def test_bayonnoma_word_va_pdf_yuboriladi(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    generated = []

    def generate(user, meeting_id, lang, **kwargs):
        generated.append((user.actorId, meeting_id, lang))
        return _minutes_view(warnings=["ungrounded_name:Karimov", "script_mismatch", "unverified_number:12"])

    export_file, exported = _minutes_export()
    monkeypatch.setattr(minutes, "generate", generate)
    monkeypatch.setattr(minutes, "export_file", export_file)
    before = len(tg.calls)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl", message_id=summary_id))

    answer = tg.calls[before][1]
    assert tg.calls[before][0] == "answer_callback" and answer["text"] == "Bayonnoma tayyorlanmoqda…"
    assert _last_markup(tg) == plaud_mod.controls(mid, "uz")                 # menyu o'rniga asosiy tugmalar
    holder = next(kw for kw in tg.sent() if kw["text"].startswith("⏳ Bayonnoma"))
    assert holder["text"] == f"⏳ Bayonnoma ({minutes.LANG_TITLES['uz-cyrl']}) tayyorlanmoqda… 1-3 daqiqa."
    assert generated == [(1, mid, "uz-cyrl")]                                  # odamning O'Z hisobidan
    assert exported == [(mid, "ab" * 16, "docx"), (mid, "ab" * 16, "pdf")]
    docx, pdf = tg.sent("send_document")
    assert docx["filename"].endswith(".docx") and docx["filename"].startswith("Баённома - Haftalik")
    assert pdf["filename"].endswith(".pdf") and pdf["size"] == len(b"pdf")
    assert docx["content_type"] == minutes.FORMATS["docx"][0] and pdf["content_type"] == minutes.FORMATS["pdf"][0]
    assert docx["caption"] == plaud_mod.MINUTES_CAPTION and "«________»" in docx["caption"]
    assert pdf["caption"] is None
    # Yuborilgan fayllarning o'zi arxivda (ega talabi, 2026-11-05): kimga, qaysi yig'ilish va til.
    sent = archive.get().rows(channel="telegram")
    assert [(r["direction"], r["kind"], r["file_name"], r["actor_id"]) for r in sent] == [
        ("out", "document", docx["filename"], 1), ("out", "document", pdf["filename"], 1)]
    assert json.loads(sent[0]["meta"]) == {"meeting": mid, "minutes": "ab" * 16, "lang": "uz-cyrl"}
    assert (archive.get().root / sent[1]["file_path"]).read_bytes() == b"pdf"
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["message_id"] == holder["message_id"]
    text = edited["text"]
    assert text.startswith(f"✅ <b>Bayonnoma tayyor</b> ({minutes.LANG_TITLES['uz-cyrl']}): 2 bo'lim, 5 band.")
    assert "❗ <b>Aniqlashtirish kerak:</b>\n• Muddat &lt;aniq&gt; emas\n• Mas'ul aytilmagan" in text
    assert "Transkriptda bo'lmagan ismlar «________» bilan almashtirildi: Karimov" in text
    assert "kirill/lotin" in text and "unverified_number" not in text
    # Natija xabariga javob (Reply) - shu yig'ilish bo'yicha savol.
    bot.handle_update(reply("Kim mas'ul?", {"message_id": holder["message_id"], "from": {"is_bot": True}}))
    assert tg.sent()[-1]["text"].startswith("⏳ Javob") and bot.backend.questions == []
    # Izohsiz, ogohlantirishsiz - faqat bitta qator.
    assert plaud_mod.minutes_html(_minutes_view(notes=[]), "en") == \
        f"✅ <b>Bayonnoma tayyor</b> ({minutes.LANG_TITLES['en']}): 2 bo'lim, 5 band."


def test_bayonnoma_yozilmadi_va_fayl_yuborilmadi(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: (_ for _ in ()).throw(
        MeetingProblem(503, "llm_not_configured", "Bayonnoma uchun model sozlanmagan")))
    bot.handle_update(callback(f"p:d:{mid}:ru", message_id=summary_id))
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["text"] == "Bayonnoma yozilmadi: Bayonnoma uchun model sozlanmagan"
    assert tg.sent("send_document") == []
    # Hujjat yozildi, lekin Telegram faylni olmadi - odamga aytiladi, qolgan fayl va natija yuboriladi.
    export_file, _ = _minutes_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _minutes_view(notes=[]))
    monkeypatch.setattr(minutes, "export_file", export_file)
    sent = []

    def send_document(chat_id, filename, content, content_type, *, caption=None, reply_markup=None):
        sent.append(filename)
        if filename.endswith(".docx"):
            raise TelegramError("sendDocument: 413", code=413)

    monkeypatch.setattr(tg, "send_document", send_document)
    bot.handle_update(callback(f"p:d:{mid}:en", message_id=summary_id))
    assert len(sent) == 2 and sent[0].endswith(".docx") and sent[1].endswith(".pdf")
    assert any(t.startswith("Faylni yuborib bo'lmadi (docx)") for t in tg.texts())
    assert [kw for n, kw in tg.calls if n == "edit_message_text"][-1]["text"].startswith("✅ <b>Bayonnoma tayyor</b>")
    # Ichki xato - "⏳" o'rnida tushunarli sabab.
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    bot.handle_update(callback(f"p:d:{mid}:en", message_id=summary_id))
    assert [kw for n, kw in tg.calls if n == "edit_message_text"][-1]["text"] == "Bayonnoma yozilmadi: ichki xato."


def test_bayonnoma_begona_odamga_yopiq(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: pytest.fail("begona uchun model chaqirilmasligi kerak"))
    for data in (f"p:d:{mid}", f"p:d:{mid}:uz-cyrl"):
        before = len(tg.calls)
        bot.handle_update(callback(data, message_id=summary_id, tg_id=OTHER_TG))
        assert [n for n, _ in tg.calls[before:]] == ["answer_callback"]
        assert tg.calls[-1][1]["alert"] and tg.calls[-1][1]["text"].startswith("Bajarib bo'lmadi")
    assert tg.sent("send_document") == []


def test_bayonnoma_haqiqiy_quvur_fakellm_bilan(world, monkeypatch):
    """Oxirigacha: soxta model (`meetings_fakes.minutes_reply`) -> validate -> compose -> render.
    Zanjir `ollama` - testda Claude kaliti yo'q (`_claude_key_off`), FakeLLM esa `rt.llm`."""
    bot, tg, rt, plaud = world
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama")
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl", message_id=summary_id))
    docs = tg.sent("send_document")
    assert len(docs) == 2 and docs[0]["filename"].endswith(".docx") and docs[1]["filename"].endswith(".pdf")
    assert all(d["size"] > 0 for d in docs) and docs[0]["filename"].startswith("Баённома")
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["text"].startswith(f"✅ <b>Bayonnoma tayyor</b> ({minutes.LANG_TITLES['uz-cyrl']}):")
    rows = rt.store.minutes_rows(mid)
    assert len(rows) == 1 and rows[0]["status"] == "ready" and rows[0]["language"] == "uz-cyrl"
    # Qayta bosish - model chaqirilmaydi (tayyori bor), fayllar qayta yuboriladi.
    calls = len(rt.llm.calls) if hasattr(rt.llm, "calls") else None
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl", message_id=summary_id))
    assert len(tg.sent("send_document")) == 4 and len(rt.store.minutes_rows(mid)) == 1
    if calls is not None:
        assert len(rt.llm.calls) == calls


def test_jarayon_xabari_foiz_chegara_va_bot_xatosi():
    """`intake.Progress` (Slack va Telegram uchun umumiy): foiz xizmat holatidan (5-80 -> 0-100),
    faqat foiz o'zgarsa tahrir 5 s da bir marta, bosqich o'zgarsa darhol; bot xatosi audio ishini
    to'xtatmaydi."""
    now = [0.0]
    shown, dropped = [], []

    def show(ref, text):
        shown.append((ref, text))
        return ref or "m1"

    progress = intake.Progress("🎙 Ovozli xabaringiz qabul qilindi.", show=show, drop=dropped.append,
                               clock=lambda: now[0])
    progress.show(intake.UPLOAD)
    progress.view({"status": "transcribing", "progress": 42.5, "durationSec": 754.0})
    assert shown[-1] == ("m1", "🎙 Ovozli xabaringiz qabul qilindi.\n\n✅ Audio yuklandi (12 daq 34 s)\n"
                               "⏳ Matnga o'girilmoqda… 50%\n◻️ Qisqa xulosa\n\n"
                               "Natija shu yerga keladi - odatda 1-3 daqiqada.")
    progress.view({"status": "transcribing", "progress": 61.25, "durationSec": 754.0})   # 75%, 5 s o'tmagan
    assert len(shown) == 2
    now[0] = 6.0
    progress.view({"status": "transcribing", "progress": 61.25, "durationSec": 754.0})
    assert len(shown) == 3 and "⏳ Matnga o'girilmoqda… 75%" in shown[-1][1]
    progress.view({"status": "summarizing", "progress": 80.0, "durationSec": 754.0})     # transkript tayyor
    assert len(shown) == 3
    progress.close()
    assert dropped == ["m1"] and progress.ref is None
    progress.show(intake.SUMMARY)                                    # transkript ostida - YANGI xabar
    assert shown[-1][0] is None and "\n⏳ Qisqa xulosa yozilmoqda…\n" in shown[-1][1]

    def flaky(ref, text):
        if ref is not None:
            raise TelegramError("tarmoq")
        return "m2"

    def drop(ref):
        raise TelegramError("tarmoq")

    quiet = intake.Progress("x", show=flaky, drop=drop, clock=lambda: now[0])
    quiet.show(intake.UPLOAD)                                        # yangi xabar
    quiet.show(intake.TRANSCRIBE)                                    # tahrir xatosi - otilmaydi
    quiet.close()                                                    # o'chirish xatosi - otilmaydi
    assert quiet.ref is None

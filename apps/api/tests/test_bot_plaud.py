"""Telegram "🎙 Plaud" (`app/bot/plaud.py`): tugma, ovozli xabar/audio fayl -> transkript va
"Qisqa xulosa", tugmalar (vazifalar, shablon, eksport, boshqa til), yig'ilish chati: «💬 Savol berish»
(ForceReply so'rovi) yoki javob (Reply) bilan savol - matn yoki ovoz (`runner._meeting_voice`),
«🔄 Yangi suhbat», javobning har bo'lagida va ovozli savolning "🎙 matn"ida yig'ilish belgisi. Bayonnoma chatda
(2026-11-12): «✍️ Ko'rsatma berish» (yozishdan oldin), hujjat ostidagi «✏️ O'zgartirish», faylga javob - yangi versiya.

Telegram ham, GAPI ham, STT ham, model ham soxta (`test_telegram_bot.FakeTelegram`, `FakeBackend`,
`meetings_fakes`): hech bir test tarmoqqa chiqmaydi. Fon ishchisi yo'q - kutish o'rniga navbat qo'lda
yuritiladi.
"""

from __future__ import annotations

import json

from types import SimpleNamespace

import pytest

from app.bot import plaud as plaud_mod
from app.bot import render
from app.bot.briefs import REPLY_KEYBOARD, REPLY_KEYBOARD_ADMIN
from app.bot.plaud import BTN_PLAUD, Plaud
from app.bot.runner import COMMANDS, VeneraBot
from app.core.config import settings
from app.core.security import hash_password
from app.services import archive
from app.services.meetings import export, intake, minutes, service
from app.services.stt import SttError, Transcript
from app.services.telegram_links import LinkStore
from app.services.users import StoredUser, UserStore
from meetings_fakes import adts_bytes, enable, ogg_opus_bytes, run_all
from test_telegram_bot import TG_ID, FakeBackend, FakeTelegram, callback, text_update
from app.services.integrations.telegram import TelegramError
from app.services.meetings.errors import MeetingProblem

OTHER_TG = 5550002


class PlaudTelegram(FakeTelegram):
    """`FakeTelegram` + tahrirdagi tugmalar ham yoziladi (chat javobi "⏳" xabari o'rnida, tugmalari bilan) va
    yuborilgan faylning xabar id si (bayonnoma fayliga javob - `replied_document`)."""

    def edit_message_text(self, chat_id, message_id, text, *, html=True, reply_markup=None):
        self._rec("edit_message_text", chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)

    def send_document(self, chat_id, filename, content, content_type, *, caption=None, reply_markup=None,
                      timeout=None):
        sent = super().send_document(chat_id, filename, content, content_type, caption=caption,
                                     reply_markup=reply_markup, timeout=timeout)
        self.calls[-1][1]["message_id"] = sent["message_id"]
        return sent


@pytest.fixture
def world(tmp_path, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    users = UserStore({
        "a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali Valiyev", password_hash=hash_password("x")),
        "b@b.uz": StoredUser(actor_id=2, email="b@b.uz", full_name="Vali Aliyev", password_hash=hash_password("x")),
    })
    tg = PlaudTelegram()
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


def last_edit(tg):
    return [kw for n, kw in tg.calls if n == "edit_message_text"][-1]


def replied(sent):
    """Odam javob (Reply) qilgan bot xabari - Telegram `reply_to_message` da beradigani: teglarsiz matn va
    faqat inline tugmalar (ForceReply qaytmaydi). `sent` - yuborilgan yoki tahrirlangan xabar yozuvi."""
    msg = {"message_id": sent["message_id"], "from": {"is_bot": True}, "text": render.plain(sent["text"])}
    if "inline_keyboard" in (sent.get("reply_markup") or {}):
        msg["reply_markup"] = sent["reply_markup"]
    return msg


def replied_document(sent):
    """Odam javob (Reply) qilgan bot FAYLI - Telegram `reply_to_message` da beradigani: matn yo'q, fayl (nomi, turi),
    izoh (teglarsiz) va inline tugmalar. `sent` - `send_document` yozuvi (`PlaudTelegram` - xabar id si bilan)."""
    msg = {"message_id": sent["message_id"], "from": {"is_bot": True},
           "document": {"file_id": f"FILE-{sent['message_id']}", "file_unique_id": f"UF{sent['message_id']}",
                        "file_name": sent["filename"], "mime_type": sent["content_type"]}}
    if sent.get("caption"):
        msg["caption"] = render.plain(sent["caption"])
    if "inline_keyboard" in (sent.get("reply_markup") or {}):
        msg["reply_markup"] = sent["reply_markup"]
    return msg


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
    assert plaud_mod.KEYBOARD["keyboard"] == [row, [{"text": plaud_mod.BTN_VOICE}]]   # ostida - «🗣 Ovoz namunasi»
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
    # «🗂 Boshqa shablon» yo'q (ega qarori 2026-11-12).
    assert [b["callback_data"] for row in rows for b in row] == [f"p:q:{mid}", f"p:t:{mid}", f"p:e:{mid}",
                                                               f"p:l:{mid}", f"p:d:{mid}"]
    # Yozuv ODAMNING hisobida (actor 1), kanal `bot`, OGG sifatida.
    row = rt.store.meeting_any(mid)
    assert row["actor_id"] == 1 and row["channel"] == "bot" and row["content_type"] == "audio/ogg"
    assert row["title"].startswith("Telegram: ovozli xabar")
    # Plaud filtri (2026-11-11): manba bazada aniq - ilovaning "Telegram bot" filtri shuni oladi.
    assert row["origin"] == "telegram"
    assert rt.store.list_meetings(1, limit=10, offset=0, origin="telegram")[1] == 1
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


def test_vazifalar_eksport_va_eski_shablon_tugmasi(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update(BTN_PLAUD))
    bot.handle_update(voice())
    mid, summary_id = meeting_of(tg), card(tg)["message_id"]
    bot.handle_update(callback(f"p:t:{mid}", message_id=summary_id))
    assert tg.texts()[-1].startswith("✅ <b>Vazifalar</b>\n\n•")
    # Eski xabardagi «🗂 Boshqa shablon» (va uning menyusidagi tanlov) - o'chirilgan (ega qarori 2026-11-12):
    # izoh (alert), tugmalar yangi ko'rinishga almashadi, YANGI XULOSA YOZILMAYDI.
    summaries = len(rt.store.summaries(mid))
    for data in (f"p:s:{mid}", f"p:s:{mid}:minutes"):
        before = len(tg.calls)
        bot.handle_update(callback(data, message_id=summary_id))
        calls = tg.calls[before:]
        assert [n for n, _ in calls] == ["answer_callback", "edit_reply_markup"]
        assert calls[0][1]["text"] == plaud_mod.TEMPLATE_OFF and calls[0][1]["alert"]
        assert calls[1][1]["reply_markup"] == plaud_mod.controls(mid, "uz")
    assert len(rt.store.summaries(mid)) == summaries
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
    # Yig'ilish chati (2026-11-11): so'rov - yozuv nomi HTML'dan tozalangan, bir qatorda, 80 belgigacha.
    prompt = plaud_mod.ask_prompt("Reja <2026>\n& byudjet")
    assert prompt == ("💬 <b>Reja &lt;2026&gt; &amp; byudjet</b> bo'yicha savolingizni yozing.\n"
                      "Barno faqat shu yozuv matni va xulosasiga tayanadi va suhbatni eslab qoladi - "
                      "keyingi savolni javobga «Reply» qilib yozing.")
    assert plaud_mod.ask_prompt(None).startswith("💬 <b>Yozuv</b> bo'yicha")
    assert f"<b>{'x' * 79}…</b>" in plaud_mod.ask_prompt("x" * 200)
    # Javobdagi so'rov (teglarsiz) - faqat BOTNIKI va faqat shu matn bilan.
    assert plaud_mod.is_prompt({"from": {"is_bot": True}, "text": render.plain(prompt)})
    assert not plaud_mod.is_prompt({"from": {"is_bot": False}, "text": render.plain(prompt)})
    assert not plaud_mod.is_prompt({"from": {"is_bot": True}, "text": plaud_mod._HINT})
    assert not plaud_mod.is_prompt({"text": render.plain(prompt)})
    # Yangi tugmalar (`q`, `n`) ham javob (Reply) uchun yig'ilish belgisi.
    for op in ("q", "n"):
        assert plaud_mod._MARK.match(f"p:{op}:{'ab' * 16}").group(1) == "ab" * 16


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


def test_bayonnoma_tugmasi_tortinchi_qatorda(world):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    rows = card(tg)["reply_markup"]["inline_keyboard"]
    # Birinchi qator - «💬 Savol berish» (yig'ilish chati, 2026-11-11), bayonnoma - to'rtinchi.
    assert rows[0] == [{"text": "💬 Savol berish", "callback_data": f"p:q:{mid}"}]
    assert rows[3] == [{"text": "📄 Bayonnoma", "callback_data": f"p:d:{mid}"}]
    # "Qayta urinish" qatori bo'lsa ham - u OXIRGI.
    retry_rows = plaud_mod.controls(mid, "uz", retry=f"p:r:m:{mid}")["inline_keyboard"]
    assert retry_rows[3][0]["callback_data"] == f"p:d:{mid}" and retry_rows[-1][0]["callback_data"] == f"p:r:m:{mid}"
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
    # O'zbek yig'ilish: tavsiya kirill - BIRINCHI; keyin qolgan tillar `LANGS` tartibida; so'ng «✍️ Ko'rsatma
    # berish» (yozishdan oldin ko'rsatma, 2026-11-12); oxirida orqaga.
    assert data == [f"p:d:{mid}:uz-cyrl", f"p:d:{mid}:uz-latn", f"p:d:{mid}:ru", f"p:d:{mid}:en", f"p:g:{mid}",
                    f"p:b:{mid}"]
    assert [b["text"] for row in menu[:-2] for b in row] == [minutes.LANG_TITLES[l] for l in
                                                             ("uz-cyrl", "uz-latn", "ru", "en")]
    assert menu[-2] == [{"text": "✍️ Ko'rsatma berish", "callback_data": f"p:g:{mid}"}]
    assert set(data[:-2]) == {f"p:d:{mid}:{lang}" for lang in minutes.LANGS}
    # Rus yig'ilish - rus birinchi.
    ru = plaud_mod.minutes_menu(mid, "ru")["inline_keyboard"]
    assert ru[0][0]["callback_data"] == f"p:d:{mid}:ru"
    # Noma'lum til - tugma eskirgan, model chaqirilmaydi.
    bot.handle_update(callback(f"p:d:{mid}:de", message_id=summary_id))
    assert tg.calls[-1][0] == "answer_callback" and tg.calls[-1][1]["text"] == "Tugma eskirgan"
    # Til tanlandi - format menyusi (ega qarori 2026-11-13), model chaqirilmaydi; savol - qisqa bildirishnoma.
    bot.handle_update(callback(f"p:d:{mid}:ru", message_id=summary_id))
    formats = _last_markup(tg)
    assert formats == plaud_mod.minutes_format_menu(mid, "ru")
    assert [(b["text"], b["callback_data"]) for row in formats["inline_keyboard"] for b in row] == [
        ("📄 Word", f"p:d:{mid}:ru:docx"), ("📕 PDF", f"p:d:{mid}:ru:pdf"), ("⬅ Orqaga", f"p:d:{mid}")]
    toast = [kw for n, kw in tg.calls if n == "answer_callback"][-1]
    assert toast["text"] == plaud_mod.MINUTES_FORMAT_PROMPT.format(title=minutes.LANG_TITLES["ru"])
    assert max(len(f"p:d:{mid}:{lang}:docx".encode()) for lang in minutes.LANGS) <= render.CALLBACK_MAX
    # Noma'lum format - tugma eskirgan.
    bot.handle_update(callback(f"p:d:{mid}:ru:txt", message_id=summary_id))
    assert tg.calls[-1][1]["text"] == "Tugma eskirgan"


def test_bayonnoma_tanlangan_formatda_bitta_fayl(world, monkeypatch):
    """Til, so'ng format (ega qarori 2026-11-13): FAQAT tanlangan fayl chiziladi va yuboriladi - Word (izohi bilan)
    yoki PDF (o'z izohi bilan); «✏️ O'zgartirish» tugmasida format ham (tahrir fayli o'sha formatda)."""
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
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))

    answer = tg.calls[before][1]
    assert tg.calls[before][0] == "answer_callback" and answer["text"] == "Bayonnoma tayyorlanmoqda…"
    assert _last_markup(tg) == plaud_mod.controls(mid, "uz")                 # menyu o'rniga asosiy tugmalar
    holder = next(kw for kw in tg.sent() if kw["text"].startswith("⏳ Bayonnoma"))
    assert holder["text"] == f"⏳ Bayonnoma ({minutes.LANG_TITLES['uz-cyrl']}) tayyorlanmoqda… 1-3 daqiqa."
    assert generated == [(1, mid, "uz-cyrl")]                                  # odamning O'Z hisobidan
    assert exported == [(mid, "ab" * 16, "docx")]                              # FAQAT tanlangan format
    [docx] = tg.sent("send_document")
    assert docx["filename"].endswith(".docx") and docx["filename"].startswith("Баённома - Haftalik")
    assert docx["content_type"] == minutes.FORMATS["docx"][0]
    assert docx["caption"] == plaud_mod.MINUTES_CAPTION and "«________»" in docx["caption"]
    assert "«✏️ O'zgartirish»ni bosing yoki shu faylga javob (Reply)" in docx["caption"]
    # Fayl ostida «✏️ O'zgartirish» (shu til va format) va «💬 Savol berish»; xotirada - bayonnoma xabari, tili bilan.
    done = plaud_mod.minutes_done_menu(mid, "uz-cyrl", "docx")
    assert docx["reply_markup"] == done and done["inline_keyboard"][0][0]["callback_data"] == f"p:w:{mid}:uz-cyrl:docx"
    assert plaud._intents[(TG_ID, docx["message_id"])] == ("doc", "uz-cyrl")
    assert plaud._formats[(TG_ID, mid, "uz-cyrl")] == "docx"
    # Yuborilgan faylning o'zi arxivda (ega talabi, 2026-11-05): kimga, qaysi yig'ilish va til.
    sent = archive.get().rows(channel="telegram")
    assert [(r["direction"], r["kind"], r["file_name"], r["actor_id"]) for r in sent] == [
        ("out", "document", docx["filename"], 1)]
    assert json.loads(sent[0]["meta"]) == {"meeting": mid, "minutes": "ab" * 16, "lang": "uz-cyrl"}
    assert (archive.get().root / sent[0]["file_path"]).read_bytes() == b"docx"
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["message_id"] == holder["message_id"]
    assert edited["reply_markup"] == done and plaud._intents[(TG_ID, holder["message_id"])] == ("doc", "uz-cyrl")
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
    # PDF tanlansa - faqat PDF, o'z izohi va formatli «✏️ O'zgartirish» bilan.
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:pdf", message_id=summary_id))
    assert exported[1:] == [(mid, "ab" * 16, "pdf")]
    pdf = tg.sent("send_document")[-1]
    assert len(tg.sent("send_document")) == 2 and pdf["filename"].endswith(".pdf") and pdf["size"] == len(b"pdf")
    assert pdf["content_type"] == minutes.FORMATS["pdf"][0] and pdf["caption"] == plaud_mod.MINUTES_PDF_CAPTION
    assert "Word formatini tanlang" in pdf["caption"]
    assert pdf["reply_markup"] == plaud_mod.minutes_done_menu(mid, "uz-cyrl", "pdf")
    assert plaud._formats[(TG_ID, mid, "uz-cyrl")] == "pdf"


def test_bayonnoma_yozilmadi_va_fayl_yuborilmadi(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: (_ for _ in ()).throw(
        MeetingProblem(503, "llm_not_configured", "Bayonnoma uchun model sozlanmagan")))
    bot.handle_update(callback(f"p:d:{mid}:ru:docx", message_id=summary_id))
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["text"] == "Bayonnoma yozilmadi: Bayonnoma uchun model sozlanmagan"
    assert tg.sent("send_document") == []
    # Xato xabarida «💬 Savol berish» - yig'ilish belgisi: qayta ishga tushgandan keyin ham javob shu yozuv chatiga.
    assert edited["reply_markup"] == plaud_mod.ask_menu(mid)
    assert plaud_mod._MARK.match(edited["reply_markup"]["inline_keyboard"][0][0]["callback_data"]).group(1) == mid
    # Hujjat yozildi, lekin Telegram faylni olmadi - odamga aytiladi, natija baribir yuboriladi.
    export_file, _ = _minutes_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _minutes_view(notes=[]))
    monkeypatch.setattr(minutes, "export_file", export_file)
    sent = []

    def send_document(chat_id, filename, content, content_type, *, caption=None, reply_markup=None):
        sent.append(filename)
        if filename.endswith(".docx"):
            raise TelegramError("sendDocument: 413", code=413)

    monkeypatch.setattr(tg, "send_document", send_document)
    bot.handle_update(callback(f"p:d:{mid}:en:docx", message_id=summary_id))
    assert len(sent) == 1 and sent[0].endswith(".docx")
    assert any(t == "Faylni yuborib bo'lmadi (Word) - til va formatni qaytadan tanlang." for t in tg.texts())
    assert [kw for n, kw in tg.calls if n == "edit_message_text"][-1]["text"].startswith("✅ <b>Bayonnoma tayyor</b>")
    # Ichki xato - "⏳" o'rnida tushunarli sabab.
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    bot.handle_update(callback(f"p:d:{mid}:en:pdf", message_id=summary_id))
    crashed = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert crashed["text"] == "Bayonnoma yozilmadi: ichki xato." and crashed["reply_markup"] == plaud_mod.ask_menu(mid)


def test_bayonnoma_begona_odamga_yopiq(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: pytest.fail("begona uchun model chaqirilmasligi kerak"))
    for data in (f"p:d:{mid}", f"p:d:{mid}:uz-cyrl", f"p:d:{mid}:uz-cyrl:docx"):
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
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))
    docs = tg.sent("send_document")
    assert len(docs) == 1 and docs[0]["filename"].endswith(".docx")
    assert docs[0]["size"] > 0 and docs[0]["filename"].startswith("Баённома")
    edited = [kw for n, kw in tg.calls if n == "edit_message_text"][-1]
    assert edited["text"].startswith(f"✅ <b>Bayonnoma tayyor</b> ({minutes.LANG_TITLES['uz-cyrl']}):")
    rows = rt.store.minutes_rows(mid)
    assert len(rows) == 1 and rows[0]["status"] == "ready" and rows[0]["language"] == "uz-cyrl"
    # Qayta tanlash (endi PDF) - model chaqirilmaydi (tayyori bor), faqat PDF chiziladi va yuboriladi.
    calls = len(rt.llm.calls) if hasattr(rt.llm, "calls") else None
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:pdf", message_id=summary_id))
    docs = tg.sent("send_document")
    assert len(docs) == 2 and docs[1]["filename"].endswith(".pdf") and len(rt.store.minutes_rows(mid)) == 1
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


# --- 💬 Yig'ilish chati (ega talabi, 2026-11-11): bitta audio - bitta suhbat -----------------------------


def _ask_card(bot, tg, question, *, message_id=30):
    """"Qisqa xulosa" xabariga javob (Reply) qilib savol; -> "⏳" o'rnidagi javob (tahrir)."""
    bot.handle_update(reply(question, replied(card(tg)), message_id=message_id))
    return last_edit(tg)


def test_savol_berish_tugmasi_forcereply_sorov_va_chat_javobi(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    before = len(tg.calls)
    bot.handle_update(callback(f"p:q:{mid}", message_id=summary_id))
    assert [n for n, _ in tg.calls[before:]] == ["answer_callback", "send_message"]
    assert tg.calls[before][1] == {"id": "cb1", "text": "", "alert": False}
    prompt = tg.sent()[-1]
    assert prompt["text"] == plaud_mod.ask_prompt(rt.store.meeting_any(mid)["title"])
    assert prompt["reply_markup"] == {"force_reply": True, "input_field_placeholder": "Savolingiz…"}
    assert plaud._messages[(TG_ID, prompt["message_id"])] == mid               # so'rov shu yig'ilishniki
    # So'rovga javob - shu yig'ilish chatiga savol: "⏳" o'rnida javob, ostida chat tugmalari.
    bot.handle_update(reply("Kim hisobot yuboradi?", replied(prompt)))
    holder = tg.sent()[-1]
    assert holder["text"] == "⏳ Javob tayyorlanmoqda…" and holder["reply_to"] == 30
    answer = last_edit(tg)
    assert answer["message_id"] == holder["message_id"] and "📌 <b>Manbalar:</b>" in answer["text"]
    assert answer["reply_markup"] == {"inline_keyboard": [[
        {"text": "💬 Yana savol", "callback_data": f"p:q:{mid}"},
        {"text": "🔄 Yangi suhbat", "callback_data": f"p:n:{mid}"}]]}
    assert bot.backend.questions == []                                         # HR yordamchisiga ketmadi
    # Navbat - chatda (mobil ilova ham shuni ko'radi): kanal `telegram`, javob bergan model va til.
    [turn] = rt.store.chat_turns(mid)
    assert turn["question"] == "Kim hisobot yuboradi?" and turn["channel"] == "telegram"
    assert turn["model"] == rt.llm.model and turn["language"] == "uz"
    # Begona odam tugmani bossa - 404: so'rov yuborilmaydi.
    before = len(tg.calls)
    bot.handle_update(callback(f"p:q:{mid}", message_id=summary_id, tg_id=OTHER_TG))
    assert [n for n, _ in tg.calls[before:]] == ["answer_callback"] and tg.calls[-1][1]["alert"]


def test_chat_xotirasi_va_qayta_ishga_tushgandan_keyin(world):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    first = _ask_card(bot, tg, "Kim hisobot yuboradi?")
    # Keyingi savol JAVOBGA javob (Reply): oldingi savol-javob modelga suhbat xotirasi bo'lib boradi.
    bot.handle_update(reply("U qachon yuboradi?", replied(first), message_id=31))
    asked = [c["user"] for c in rt.llm.calls if c["op"] == "meeting_ask"]
    assert len(asked) == 2 and "Kim hisobot yuboradi?" in asked[1]
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Kim hisobot yuboradi?", "U qachon yuboradi?"]
    # Qayta ishga tushgandan keyin: xotira bo'sh, lekin javob tugmalaridagi `p:q:`/`p:n:` - yig'ilish belgisi.
    second = last_edit(tg)
    plaud._messages.clear()
    bot.handle_update(reply("Yana?", replied(second), message_id=32))
    assert tg.sent()[-1]["text"] == "⏳ Javob tayyorlanmoqda…" and bot.backend.questions == []
    assert len(rt.store.chat_turns(mid)) == 3


def test_uzun_javob_har_bolagida_belgi_chat_tugmalari_oxirgisida(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    calls = []

    def chat_send(user, meeting_id, message, language, *, channel="api", **kwargs):
        calls.append((user.actorId, meeting_id, message, language, channel, kwargs))
        text = "\n\n".join(f"{n}-band: " + "batafsil izoh " * 40 for n in range(1, 25))
        return {"id": "q1", "question": message, "answer": text, "citations": [], "followUps": ["a?", "b?", "c?"],
                "createdAt": "2026-11-11T10:00:00Z", "channel": channel, "model": "claude-sonnet-5-5"}

    monkeypatch.setattr(service, "chat_send", chat_send)
    first = _ask_card(bot, tg, "Batafsilroq")
    # Xulosaga javob - aniq niyatsiz (amalni chat modeli tanlaydi) va hujjat tilisiz.
    assert calls == [(1, mid, "Batafsilroq", None, "telegram", {"intent": None, "minutes_lang": None})]
    holder = next(kw for kw in reversed(tg.sent()) if kw["text"] == "⏳ Javob tayyorlanmoqda…")
    # "⏳" o'rnidagi birinchi bo'lak va o'rtadagilari - «💬 Savol berish» (yig'ilish belgisi), oxirgisi - chat tugmalari.
    assert first["message_id"] == holder["message_id"] and first["reply_markup"] == plaud_mod.ask_menu(mid)
    rest = [kw for kw in tg.sent() if kw["message_id"] > holder["message_id"]]
    assert len(rest) >= 2 and all(kw["reply_markup"] == plaud_mod.ask_menu(mid) for kw in rest[:-1])
    [buttons] = rest[-1]["reply_markup"]["inline_keyboard"]
    assert [b["callback_data"] for b in buttons] == [f"p:q:{mid}", f"p:n:{mid}"] and rest[-1]["text"].endswith("• c?")
    # Hamma bo'lak shu yig'ilishniki: savol qaysi bo'lakka javob qilib yozilsa ham.
    assert all(plaud._messages[(TG_ID, kw["message_id"])] == mid for kw in [holder, *rest])


def test_qayta_ishga_tushgandan_keyin_birinchi_bolakka_javob_ham_chatga(world):
    """Haqiqiy `chat_send` (soxta model): ~3900 belgili javob ikki bo'lakka bo'linadi. Xotira tozalangach
    (qayta ishga tushdi) birinchi bo'lakka javob (Reply) - tugmadagi belgi orqali shu yig'ilish chatiga."""
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    ids = [int(s["id"]) for s in rt.store.segments(mid)]
    para = ("[S1] loyiha bo'yicha muhim qaror qabul qildi: hisobot ertaga soat 10 gacha yuboriladi, "
            "budjet 15 foizga oshiriladi va mas'ul sifatida [S2] belgilandi. ")
    answer = "".join(f"{n}. {para}\n" for n in range(1, 60))[:3900]
    rt.llm.script["meeting_ask"] = [json.dumps({"answer": answer, "citations": ids[:6],
                                                "followUps": ["Budjet qancha?", "Kim tayyorlaydi?", "Qachon?"]},
                                               ensure_ascii=False)]
    page1 = _ask_card(bot, tg, "Batafsil ayt")
    rest = [kw for kw in tg.sent() if kw["message_id"] > page1["message_id"]]
    assert len(rest) == 1 and page1["reply_markup"] == plaud_mod.ask_menu(mid)
    assert rest[-1]["reply_markup"] == plaud_mod.chat_menu(mid)
    plaud._messages.clear()
    bot.handle_update(reply("3-band bo'yicha muddat qachon?", replied(page1), message_id=31))
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Batafsil ayt", "3-band bo'yicha muddat qachon?"]
    assert bot.backend.questions == []                                         # HR yordamchisiga ketmadi


def test_chat_xatosi_sababi_va_savol_tugmasi_bilan(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    real, fails = service.chat_send, []

    def chat_send(*args, **kwargs):
        if fails:
            raise fails.pop()
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "chat_send", chat_send)
    fails.append(MeetingProblem(503, "llm_unavailable", "Model hozir javob bera olmayapti - keyinroq urinib ko'ring"))
    failed = _ask_card(bot, tg, "Kim?")
    assert failed["text"] == "Javob berib bo'lmadi: Model hozir javob bera olmayapti - keyinroq urinib ko'ring"
    # Qayta so'rash tugmasi - u yig'ilish belgisi ham: qayta ishga tushgandan keyin xatoga javob ham chatga.
    assert failed["reply_markup"] == plaud_mod.ask_menu(mid)
    plaud._messages.clear()
    bot.handle_update(reply("Kim? (qayta)", replied(failed), message_id=31))
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Kim? (qayta)"] and bot.backend.questions == []
    # Ichki xato ham - tugma bilan.
    fails.append(RuntimeError("boom"))
    broken = _ask_card(bot, tg, "Yana?", message_id=32)
    assert broken["text"] == "Javob berib bo'lmadi: ichki xato." and broken["reply_markup"] == plaud_mod.ask_menu(mid)
    # Yozuv yo'q (o'chirilgan yoki begona, 404) - qayta so'rashning ma'nosi yo'q: tugmasiz.
    fails.append(MeetingProblem(404, "not_found", "Yig'ilish topilmadi"))
    gone = _ask_card(bot, tg, "Va?", message_id=33)
    assert gone["text"] == "Javob berib bo'lmadi: Yig'ilish topilmadi" and gone["reply_markup"] is None


def test_yangi_suhbat_tugmasi_yumshoq_va_toza_boshlanadi(world):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    answer = _ask_card(bot, tg, "Kim hisobot yuboradi?")
    before = len(tg.calls)
    bot.handle_update(callback(f"p:n:{mid}", message_id=answer["message_id"]))
    assert [n for n, _ in tg.calls[before:]] == ["answer_callback", "send_message"]
    done = tg.sent()[-1]
    # Bayonnoma ko'rsatmalari ham suhbat bilan arxivga ketadi, tayyor hujjatlar qoladi (2026-11-12).
    assert done["text"] == ("🔄 Yangi suhbat boshlandi - oldingi savol-javoblar va bayonnoma ko'rsatmalari endi "
                            "hisobga olinmaydi (tayyor bayonnomalar saqlanib qoladi).")
    assert done["reply_markup"] == {"inline_keyboard": [[{"text": "💬 Savol berish", "callback_data": f"p:q:{mid}"}]]}
    assert plaud._messages[(TG_ID, done["message_id"])] == mid
    # Yumshoq: navbat chatdan ham, eski ro'yxatdan ham ketdi, qator bazada qoldi.
    assert rt.store.chat_turns(mid) == [] and rt.store.questions(mid) == []
    assert rt.store.scalar("SELECT COUNT(*) FROM questions WHERE meeting_id=?", (mid,)) == 1
    # Keyingi savol - toza suhbat: oldingi savol modelga bormaydi.
    bot.handle_update(reply("Qaror nima?", replied(done), message_id=31))
    assert "Kim hisobot yuboradi?" not in [c["user"] for c in rt.llm.calls if c["op"] == "meeting_ask"][-1]
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Qaror nima?"]
    # Begona odam - 404: hech narsa arxivga ketmaydi, faqat ogohlantirish.
    before = len(tg.calls)
    bot.handle_update(callback(f"p:n:{mid}", message_id=answer["message_id"], tg_id=OTHER_TG))
    assert [n for n, _ in tg.calls[before:]] == ["answer_callback"] and tg.calls[-1][1]["alert"]
    assert len(rt.store.chat_turns(mid)) == 1


def test_eskirgan_sorov_yutiladi_hr_yordamchisiga_ketmaydi(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(callback(f"p:q:{mid}", message_id=summary_id))
    prompt = tg.sent()[-1]
    plaud._messages.clear()                                                    # qayta ishga tushdi
    llm_calls = len(rt.llm.calls)
    bot.handle_update(reply("Kim hisobot yuboradi?", replied(prompt)))
    stale = tg.sent()[-1]
    assert stale["text"] == "Bu so'rov eskirgan - yozuv ostidagi «💬 Savol berish» tugmasini qayta bosing."
    assert stale["reply_to"] == 30
    assert bot.backend.questions == [] and len(rt.llm.calls) == llm_calls and rt.store.chat_turns(mid) == []
    # "💬" bilan boshlanadigan boshqa bot xabari yoki odamning o'z xabari - so'rov emas: HR yordamchisiga.
    bot.handle_update(reply("salom", {"message_id": 999, "from": {"is_bot": True}, "text": "💬 Boshqa xabar"},
                            message_id=31))
    assert bot.backend.questions[-1][0] == "salom"
    mine = {**replied(prompt), "message_id": 998, "from": {"is_bot": False}}
    bot.handle_update(reply("yana", mine, message_id=32))
    assert bot.backend.questions[-1][0] == "yana"


# --- 🎙 Ovozli savol: yozuv xabariga yoki so'rovga ovozli javob (`runner._meeting_voice`) ---------------------


def _voice_reply(bot, tg, to, text="Kim hisobot yuboradi?", *, file_id="q1", duration=6, message_id=40):
    """Bot xabariga OVOZLI javob (Reply); STT soxta (`FakeBackend.transcribe`) - ovoz matni `text`."""
    tg.files[f"voice/{file_id}.oga"] = b"OggS-savol"
    bot.backend.transcript = Transcript(text=text, backend="gapi")
    bot.handle_update(voice(file_id, duration=duration, message_id=message_id, reply_to=to))


def _prompt(bot, tg, mid, summary_id):
    """«💬 Savol berish» -> ForceReply so'rovi."""
    bot.handle_update(callback(f"p:q:{mid}", message_id=summary_id))
    return tg.sent()[-1]


def _counts(rt):
    """Yozuvlar soni va GAPI'ga yuborilgan audiolar - ovozli savol yangi yozuv bo'lmasligini tekshirish uchun."""
    return rt.store.scalar("SELECT COUNT(*) FROM meetings"), len(rt.gapi.submits)


def test_sorovga_ovozli_javob_yigilish_chatiga_savol(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)                      # qurollanish shu yozuvga sarflandi
    prompt = _prompt(bot, tg, mid, summary_id)
    counts, before = _counts(rt), len(tg.calls)
    _voice_reply(bot, tg, replied(prompt))
    # Matn HR savolidagi AYNI STT yo'li bilan: ovoz o'girildi, matni ovozli xabarga javob qilib ko'rsatildi.
    assert bot.backend.audio == [(b"OggS-savol", "audio/ogg")]
    echo, holder = [kw for n, kw in tg.calls[before:] if n == "send_message"]
    assert echo["text"] == "🎙 <i>Kim hisobot yuboradi?</i>" and echo["reply_to"] == 40
    assert holder["text"] == "⏳ Javob tayyorlanmoqda…" and holder["reply_to"] == 40
    answer = last_edit(tg)
    assert answer["message_id"] == holder["message_id"] and answer["reply_markup"] == plaud_mod.chat_menu(mid)
    # Savol shu yig'ilish chatida; HR yordamchisi ham, yangi yozuv ham yo'q.
    [turn] = rt.store.chat_turns(mid)
    assert turn["question"] == "Kim hisobot yuboradi?" and turn["channel"] == "telegram"
    assert bot.backend.questions == [] and _counts(rt) == counts
    # Ovozning o'zi arxivda - HR savolidagi kabi.
    [row] = [r for r in archive.get().rows(channel="telegram") if r["kind"] == "voice"]
    assert (row["direction"], row["message_id"], row["actor_id"]) == ("in", "40", 1)


def test_qurollangan_chatda_ham_sorovga_ovozli_javob_yozuv_bolmaydi(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(text_update(BTN_PLAUD))                  # yana qurollandi: 15 daqiqa ovoz - yozuv
    prompt = _prompt(bot, tg, mid, summary_id)
    meetings, submits = _counts(rt)
    _voice_reply(bot, tg, replied(prompt), "Qaror nima?")
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Qaror nima?"] and bot.backend.questions == []
    assert _counts(rt) == (meetings, submits)
    # Qurollanish SARFLANMADI: keyingi oddiy (javob emas) ovozli xabar - yangi yozuv.
    tg.files["voice/v2.oga"] = ogg_opus_bytes(64.0)
    bot.handle_update(voice("v2", duration=8, message_id=41))
    assert _counts(rt) == (meetings + 1, submits + 1) and bot.backend.questions == []


def test_javobga_ovozli_javob_suhbatni_davom_ettiradi(world):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    first = _ask_card(bot, tg, "Kim hisobot yuboradi?")
    _voice_reply(bot, tg, replied(first), "U qachon yuboradi?")
    asked = [c["user"] for c in rt.llm.calls if c["op"] == "meeting_ask"]
    assert len(asked) == 2 and "Kim hisobot yuboradi?" in asked[1]           # suhbat xotirasi bilan
    # Qayta ishga tushgandan keyin ham: javob tugmalaridagi belgi orqali.
    plaud._messages.clear()
    _voice_reply(bot, tg, replied(last_edit(tg)), "Muddat qachon?", file_id="q2", message_id=41)
    assert [t["question"] for t in rt.store.chat_turns(mid)] == [
        "Kim hisobot yuboradi?", "U qachon yuboradi?", "Muddat qachon?"]
    assert bot.backend.questions == []


def test_ovozli_savol_stt_xatosi_hr_yordamchisiga_ketmaydi(world, monkeypatch):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    prompt = _prompt(bot, tg, mid, summary_id)
    counts = _counts(rt)
    tg.files["voice/q1.oga"] = b"OggS-savol"
    bot.backend.transcript = SttError("band", status=503)
    bot.handle_update(voice("q1", duration=6, message_id=40, reply_to=replied(prompt)))
    assert tg.texts()[-1] == "Ovoz xizmati band, biroz kutib qayta urinib ko'ring"
    # Ovozdan matn chiqmadi.
    bot.backend.transcript = Transcript(text="  ")
    bot.handle_update(voice("q1", duration=6, message_id=41, reply_to=replied(prompt)))
    assert tg.texts()[-1] == "🎙 Ovozdan matn ajratib bo'lmadi - aniqroq gapirib qayta yuboring."
    # Telegram faylni bermadi.
    real = tg.download
    monkeypatch.setattr(tg, "download", lambda *a, **k: (_ for _ in ()).throw(TelegramError("yo'q")))
    bot.handle_update(voice("q1", duration=6, message_id=42, reply_to=replied(prompt)))
    assert tg.texts()[-1] == "Ovozli xabarni olib bo'lmadi - qaytadan yuboring."
    # Hech biri HR yordamchisiga, yig'ilish chatiga yoki yangi yozuvga ketmadi.
    assert bot.backend.questions == [] and rt.store.chat_turns(mid) == [] and _counts(rt) == counts
    assert not any(t.startswith("⏳ Javob") for t in tg.texts())
    # Qayta yuborilgan ovoz o'tadi - va yana shu yig'ilish chatiga.
    monkeypatch.setattr(tg, "download", real)
    _voice_reply(bot, tg, replied(prompt), message_id=43)
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Kim hisobot yuboradi?"]
    assert bot.backend.questions == []


def test_ovoz_ogirilguncha_yozuv_ochirilsa_savol_yutiladi(world):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    plaud._messages.clear()                                    # qayta ishga tushdi: yig'ilish faqat tugmadan
    hear = bot.backend.transcribe

    def transcribe(audio, content_type):
        service.delete(SimpleNamespace(actorId=1), mid)        # odam shu paytda yozuvni ilovada o'chirdi
        return hear(audio, content_type)

    bot.backend.transcribe = transcribe
    meetings, _ = _counts(rt)
    _voice_reply(bot, tg, replied(card(tg)))
    assert tg.texts()[-1] == "Javob berib bo'lmadi: yozuv topilmadi."
    assert bot.backend.questions == [] and _counts(rt)[0] == meetings - 1
    assert not any(t.startswith("⏳ Javob") for t in tg.texts())


def test_uzun_ovozli_savol_yutiladi_yozuv_ham_hr_ham_emas(world):
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    counts = _counts(rt)
    tg.files["voice/long.oga"] = ogg_opus_bytes(64.0)
    # Qurollanmagan uzun ovoz odatda yozuv bo'ladi - lekin bu xulosaga javob, ya'ni savol.
    bot.handle_update(voice("long", duration=settings.telegram_voice_max_sec + 1, message_id=40,
                            reply_to=replied(card(tg))))
    most = settings.telegram_voice_max_sec // 60
    assert tg.texts()[-1] == (f"Ovozli savol juda uzun - qisqaroq ({most} daqiqagacha) yuboring yoki "
                              "savolni yozib yuboring.")
    assert bot.backend.audio == [] and bot.backend.questions == [] and rt.store.chat_turns(mid) == []
    assert _counts(rt) == counts


def test_eskirgan_sorovga_ovozli_javob_ham_yutiladi_va_boshqa_ovoz_avvalgidek(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    prompt = _prompt(bot, tg, mid, summary_id)
    plaud._messages.clear()                                    # qayta ishga tushdi: so'rov yig'ilishi noma'lum
    llm_calls = len(rt.llm.calls)
    _voice_reply(bot, tg, replied(prompt))
    stale = tg.sent()[-1]
    assert stale["text"] == plaud_mod.STALE_PROMPT and stale["reply_to"] == 40
    assert bot.backend.questions == [] and rt.store.chat_turns(mid) == [] and len(rt.llm.calls) == llm_calls
    # Yig'ilish belgisisiz bot xabariga (HR javobi) ovozli javob - avvalgidek HR savoli.
    _voice_reply(bot, tg, {"message_id": 999, "from": {"is_bot": True}, "text": "Javob muhim."},
                 "ta'til necha kun?", file_id="q2", message_id=41)
    assert bot.backend.questions[-1][0] == "ta'til necha kun?"
    # Odamning o'z xabariga ovozli javob ham - HR savoli (faqat bot xabarlari yozuvniki bo'la oladi).
    _voice_reply(bot, tg, voice()["message"], "Bugun nima bor?", file_id="q3", message_id=42)
    assert bot.backend.questions[-1][0] == "Bugun nima bor?" and rt.store.chat_turns(mid) == []


def _echo(tg, text):
    """Ovozli savolning "🎙 matn" xabari - Telegram javobda (`reply_to_message`) beradigan holatida: keyin
    qo'shilgan tugmasi (`edit_reply_markup`) bilan."""
    sent = next(kw for kw in reversed(tg.sent()) if kw["text"] == f"🎙 <i>{text}</i>")
    marks = [kw["reply_markup"] for n, kw in tg.calls
             if n == "edit_reply_markup" and kw["message_id"] == sent["message_id"]]
    return {**sent, "reply_markup": marks[-1] if marks else sent["reply_markup"]}


def test_ovozli_savol_matniga_javob_ham_yigilish_chatiga_hr_ga_emas(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    _voice_reply(bot, tg, replied(_prompt(bot, tg, mid, summary_id)))
    # "🎙 matn" shu yig'ilishniki: «💬 Savol berish» tugmasi (qayta ishga tushgandan keyin ham belgi) va xotira.
    echo = _echo(tg, "Kim hisobot yuboradi?")
    assert echo["reply_markup"] == plaud_mod.ask_menu(mid) and plaud._messages[(TG_ID, echo["message_id"])] == mid
    # Odam o'z savolining matniga javob (Reply) qilib aniqlashtiradi - shu suhbatga, xotira bilan.
    bot.handle_update(reply("Yo'q, muddatini so'rayapman", replied(echo), message_id=41))
    holder = tg.sent()[-1]
    assert holder["text"] == "⏳ Javob tayyorlanmoqda…" and holder["reply_to"] == 41
    assert last_edit(tg)["message_id"] == holder["message_id"]
    assert last_edit(tg)["reply_markup"] == plaud_mod.chat_menu(mid)
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Kim hisobot yuboradi?", "Yo'q, muddatini so'rayapman"]
    asked = [c["user"] for c in rt.llm.calls if c["op"] == "meeting_ask"]
    assert len(asked) == 2 and "Kim hisobot yuboradi?" in asked[1]           # suhbat xotirasi bilan
    assert bot.backend.questions == []                                         # HR yordamchisiga hech narsa
    # Qayta ishga tushgandan keyin ham: xotira bo'sh, "🎙 matn"dagi tugma - yig'ilish belgisi.
    plaud._messages.clear()
    bot.handle_update(reply("Yana?", replied(echo), message_id=42))
    assert len(rt.store.chat_turns(mid)) == 3 and bot.backend.questions == []


def test_qurollangan_chatda_ovozli_savol_matniga_ovozli_javob_yozuv_bolmaydi(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(text_update(BTN_PLAUD))                  # yana qurollandi: 15 daqiqa ovoz - yozuv
    _voice_reply(bot, tg, replied(_prompt(bot, tg, mid, summary_id)))
    meetings, submits = _counts(rt)
    _voice_reply(bot, tg, replied(_echo(tg, "Kim hisobot yuboradi?")), "Muddat qachon?", file_id="q2",
                 message_id=41)
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Kim hisobot yuboradi?", "Muddat qachon?"]
    assert bot.backend.questions == [] and _counts(rt) == (meetings, submits)
    # Qayta ishga tushgandan keyin ham - "🎙 matn"dagi tugma orqali (bu ovozning "🎙 matn"i ham bog'landi).
    plaud._messages.clear()
    _voice_reply(bot, tg, replied(_echo(tg, "Muddat qachon?")), "Kim tayyorlaydi?", file_id="q3", message_id=42)
    assert len(rt.store.chat_turns(mid)) == 3 and bot.backend.questions == [] and _counts(rt) == (meetings, submits)
    # Qurollanish SARFLANMADI: keyingi oddiy (javob emas) ovozli xabar - yangi yozuv.
    tg.files["voice/v2.oga"] = ogg_opus_bytes(64.0)
    bot.handle_update(voice("v2", duration=8, message_id=43))
    assert _counts(rt) == (meetings + 1, submits + 1) and bot.backend.questions == []


def test_hr_ovozi_va_eskirgan_sorov_matni_yigilishga_boglanmaydi(world):
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    # Oddiy (javob emas, qurollanmagan) ovoz - avvalgidek HR savoli: "🎙 matn" tugmasiz, xotirada yo'q, unga
    # javob ham HR yordamchisiga.
    _voice_reply(bot, tg, None, "ta'til necha kun?", file_id="h1", message_id=40)
    hr = _echo(tg, "ta'til necha kun?")
    assert hr["reply_markup"] is None and (TG_ID, hr["message_id"]) not in plaud._messages
    bot.handle_update(reply("yana bir savol", replied(hr), message_id=41))
    assert [q for q, *_ in bot.backend.questions] == ["ta'til necha kun?", "yana bir savol"]
    # Eskirgan so'rovga ovozli javob: yig'ilish noma'lum - "🎙 matn" ham bog'lanmaydi.
    prompt = _prompt(bot, tg, mid, summary_id)
    plaud._messages.clear()
    _voice_reply(bot, tg, replied(prompt), "Qaror nima?", file_id="q2", message_id=42)
    assert tg.sent()[-1]["text"] == plaud_mod.STALE_PROMPT
    stale = _echo(tg, "Qaror nima?")
    assert stale["reply_markup"] is None and (TG_ID, stale["message_id"]) not in plaud._messages
    assert rt.store.chat_turns(mid) == [] and tg.sent("edit_reply_markup") == []


def test_tahrir_otmasa_ham_har_bolakda_belgi_va_kutish_xabari_yigilishniki(world, monkeypatch):
    """"⏳" tahrirlanmasa birinchi bo'lak yangi xabar bo'lib ketadi - u ham belgili, oxirgisida chat tugmalari.
    O'zgarmay qolgan "⏳" ham shu yig'ilishniki: javob kelguncha unga yozilgan savol ham shu suhbatga."""
    bot, tg, rt, plaud = world
    mid, _ = _delivered(bot, tg)
    real = service.chat_send

    def chat_send(user, meeting_id, message, language, *, channel="api", **kwargs):
        text = "\n\n".join(f"{n}-band: " + "batafsil izoh " * 40 for n in range(1, 25))
        return {"id": "q1", "question": message, "answer": text, "citations": [], "followUps": ["a?", "b?", "c?"],
                "createdAt": "2026-11-11T10:00:00Z", "channel": channel, "model": "claude-sonnet-5-5"}

    def broken(*args, **kwargs):
        raise TelegramError("Bad Request: message to edit not found")

    monkeypatch.setattr(service, "chat_send", chat_send)
    monkeypatch.setattr(tg, "edit_message_text", broken)
    bot.handle_update(reply("Batafsil", replied(card(tg)), message_id=30))
    holder = next(kw for kw in reversed(tg.sent()) if kw["text"] == "⏳ Javob tayyorlanmoqda…")
    pages = [kw for kw in tg.sent() if kw["message_id"] > holder["message_id"]]
    assert len(pages) >= 2 and all(kw["reply_markup"] == plaud_mod.ask_menu(mid) for kw in pages[:-1])
    assert pages[-1]["reply_markup"] == plaud_mod.chat_menu(mid)
    assert all(plaud._messages[(TG_ID, kw["message_id"])] == mid for kw in [holder, *pages])
    # "⏳" ga javob - shu suhbatga (haqiqiy `chat_send`), HR yordamchisiga emas.
    monkeypatch.setattr(service, "chat_send", real)
    bot.handle_update(reply("Qisqaroq ayt", replied(holder), message_id=31))
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["Qisqaroq ayt"] and bot.backend.questions == []


def test_yordam_matnida_yigilish_chati_va_ovozli_savol(world):
    bot, tg, rt, plaud = world
    bot.handle_update(text_update("/help"))
    text = tg.sent()[-1]["text"]
    [line] = [line for line in text.splitlines() if "<b>Plaud</b>" in line]
    assert "«💬 Savol berish»" in line and "javob (Reply)" in line and "ovozli xabar ham" in line
    assert ("eslab qoladi. Bayonnoma uchun ko'rsatma va tayyor bayonnomadagi o'zgartirishlar ham shunday "
            "yoziladi.") in line
    # HTML yaroqli: teglar juft, teglardan tashqarida `<`, `>`, `&` yo'q.
    assert render._balanced(text) and not any(c in render._TAG.sub("", text) for c in "<>&")


# --- 📄 Bayonnoma chatda (ega so'rovi, 2026-11-12): ✍️ ko'rsatma, ✏️ o'zgartirish, faylga javob ------------------


def _queued_minutes(monkeypatch, rt, plaud):
    """Bayonnoma zanjiri - `FakeLLM`, fon ishlari NAVBATDA (`minutes.runner`): ishlab chiqarishdagidek chat navbati
    qaytganda hujjat hali yozilmoqda. Plaud kutishi (`sleep`: `minutes.wait`, `intake`) navbatni ham, yig'ilish
    ishchisini ham yuritadi."""
    jobs = []
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama")
    monkeypatch.setattr(minutes, "runner", jobs.append)

    def sleep(_sec):
        run_all(rt)
        while jobs:
            jobs.pop(0)()

    monkeypatch.setattr(plaud, "_sleep", sleep)
    return jobs


def _claude_chat(monkeypatch, rt):
    """Chat zanjiri - soxta Claude (prod'dagidek `MEETINGS_ASK_CHAIN=claude`): bayonnoma amalini u tanlaydi
    (`meetings_fakes.chat_auto`: savoldagi `ACTION=` va `LANG=`)."""
    from app.services.meetings import llm
    from meetings_fakes import FakeAnthropic

    monkeypatch.setattr(settings, "meetings_ask_chain", "claude", raising=False)
    fake = FakeAnthropic()
    rt.ask_claude = llm.ClaudeChat(lambda: "sk-ant-test-TG", "claude-sonnet-5-5", timeout=10, client_factory=fake,
                                   fallbacks=True)
    return fake


def _recording(monkeypatch):
    """Haqiqiy `service.chat_send`, bot bergan kanal va bayonnoma kalitlari (`intent`, `minutes_lang`) yozib
    boriladi."""
    real, seen = service.chat_send, []

    def chat_send(*args, **kwargs):
        seen.append({key: kwargs.get(key) for key in ("channel", "intent", "minutes_lang")})
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "chat_send", chat_send)
    return seen


def _minutes_calls(rt):
    """Bayonnoma model chaqiruvlari (`FakeLLM`): yangi hujjat va tahrir."""
    return [c for c in rt.llm.calls if c["op"].startswith("meeting_minutes")]


def _stub_minutes(monkeypatch):
    """Soxta `generate` va `export_file`: til tugmasi darhol tayyor hujjat (`_minutes_view`) va fayllarni beradi."""
    export_file, _ = _minutes_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _minutes_view())
    monkeypatch.setattr(minutes, "export_file", export_file)


def test_korsatma_tugmasi_prompt_va_javob(world, monkeypatch):
    """«✍️ Ko'rsatma berish» (til menyusida): ForceReply so'rovi; javob - matn yoki ovoz - `intent="note"` bilan, chat
    modelisiz; javob ostida ko'rsatmalar soni va `note_menu`. Til bosilganda hujjat shu ko'rsatmalar bilan yoziladi."""
    bot, tg, rt, plaud = world
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama")
    mid, summary_id = _delivered(bot, tg)
    seen = _recording(monkeypatch)
    bot.handle_update(callback(f"p:d:{mid}", message_id=summary_id))
    before = len(tg.calls)
    bot.handle_update(callback(f"p:g:{mid}", message_id=summary_id))
    assert [n for n, _ in tg.calls[before:]] == ["answer_callback", "send_message"]
    prompt = tg.sent()[-1]
    title = rt.store.meeting_any(mid)["title"]
    assert prompt["text"] == plaud_mod.guide_prompt(title)
    assert prompt["text"].startswith(f"✍️ <b>{title}</b> bayonnomasi uchun ko'rsatma yozing.\nNimaga e'tibor berish")
    assert prompt["reply_markup"] == {"force_reply": True,
                                      "input_field_placeholder": "Rais, qatnashchilar, nimaga e'tibor…"}
    assert plaud._messages[(TG_ID, prompt["message_id"])] == mid
    assert plaud._intents[(TG_ID, prompt["message_id"])] == ("note", None)
    assert _last_markup(tg) == plaud_mod.minutes_menu(mid, "uz")              # til menyusi o'z joyida qoldi
    # So'rovga javob - ko'rsatma: modelsiz, HR yordamchisiga ham emas.
    asked = len(rt.llm.calls)
    bot.handle_update(reply("Rais - Alisher Karimov, qatnashchilar: bo'lim boshliqlari", replied(prompt)))
    holder = tg.sent()[-1]
    assert holder["text"] == "⏳ Javob tayyorlanmoqda…" and holder["reply_to"] == 30
    answer = last_edit(tg)
    assert answer["message_id"] == holder["message_id"]
    assert answer["text"] == ("Ko'rsatmangiz eslab qolindi - bayonnoma tayyorlanganda hisobga olinadi.\n\n"
                              "📝 Ko'rsatma eslab qolindi (jami 1 ta) - bayonnoma tayyorlashda hisobga olinadi.")
    assert answer["reply_markup"] == plaud_mod.note_menu(mid)
    assert seen == [{"channel": "telegram", "intent": "note", "minutes_lang": None}]
    assert len(rt.llm.calls) == asked and bot.backend.questions == []
    [turn] = rt.store.chat_turns(mid)
    assert turn["kind"] == "note" and turn["channel"] == "telegram"
    # Ovozli javob ham - ikkinchi ko'rsatma (so'rov o'sha).
    _voice_reply(bot, tg, replied(prompt), "Moliyaviy atamalarni o'zgartirmang")
    assert last_edit(tg)["text"].endswith(
        "📝 Ko'rsatma eslab qolindi (jami 2 ta) - bayonnoma tayyorlashda hisobga olinadi.")
    assert seen[-1] == {"channel": "telegram", "intent": "note", "minutes_lang": None}
    assert [n["text"] for n in rt.store.notes(mid)] == ["Rais - Alisher Karimov, qatnashchilar: bo'lim boshliqlari",
                                                        "Moliyaviy atamalarni o'zgartirmang"]
    assert len(rt.llm.calls) == asked and bot.backend.questions == []
    # «📄 Bayonnoma tayyorlash» - shu xabarda til menyusi; tanlangan tilda hujjat ikkala ko'rsatma bilan yoziladi.
    bot.handle_update(callback(f"p:d:{mid}", message_id=answer["message_id"]))
    assert _last_markup(tg) == plaud_mod.minutes_menu(mid, "uz")
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl", message_id=answer["message_id"]))
    assert _last_markup(tg) == plaud_mod.minutes_format_menu(mid, "uz-cyrl") and _minutes_calls(rt) == []
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=answer["message_id"]))
    [call] = _minutes_calls(rt)
    assert call["op"] == "meeting_minutes" and "OWNER INSTRUCTIONS" in call["user"]
    assert "Rais - Alisher Karimov" in call["user"] and "Moliyaviy atamalarni o'zgartirmang" in call["user"]
    result = last_edit(tg)
    assert result["text"].startswith(f"✅ <b>Bayonnoma tayyor</b> ({minutes.LANG_TITLES['uz-cyrl']}): ")
    assert "Ko'rsatmalaringiz hisobga olindi (2 ta)." in result["text"].split("\n")[0]
    # Yana bir ko'rsatma, so'ng o'sha til - qaytadan yozilmaydi: joriy hujjatning ko'rsatmalar tahriri.
    bot.handle_update(callback(f"p:g:{mid}", message_id=summary_id))
    bot.handle_update(reply("Nazoratni moliya bo'limiga yuklang", replied(tg.sent()[-1]), message_id=31))
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))
    assert [c["op"] for c in _minutes_calls(rt)] == ["meeting_minutes", "meeting_minutes_revise"]
    assert last_edit(tg)["text"].startswith(f"✅ <b>Bayonnoma yangilandi</b> ({minutes.LANG_TITLES['uz-cyrl']}, "
                                            "2-versiya): ko'rsatmalaringiz qo'llandi - ")


def test_ozgartirish_tugmasi_prompt_va_tahrir(world, monkeypatch):
    """«✏️ O'zgartirish» (fayl va natija ostida, `p:w:<id>:<til>`): ForceReply so'rovi; javob - matn yoki ovoz -
    `intent="revise"` va shu til; javobdan keyin "⏳ … tahrirlanmoqda", yangi versiya fayli - tanlangan formatda (o'sha
    tugmalar bilan) va "⏳" o'rnida natija: versiya, so'rov va o'zgarishlar."""
    bot, tg, rt, plaud = world
    _queued_minutes(monkeypatch, rt, plaud)
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))   # 1-versiya (shu ipda)
    done = plaud_mod.minutes_done_menu(mid, "uz-cyrl", "docx")
    [docx] = tg.sent("send_document")
    assert docx["reply_markup"] == done and last_edit(tg)["reply_markup"] == done
    seen = _recording(monkeypatch)
    lang = minutes.LANG_TITLES["uz-cyrl"]
    # Word fayli ostidagi ✏️ - so'rov (faqat xotirada: niyat va til).
    before = len(tg.calls)
    bot.handle_update(callback(f"p:w:{mid}:uz-cyrl", message_id=docx["message_id"]))
    assert [n for n, _ in tg.calls[before:]] == ["answer_callback", "send_message"]
    prompt = tg.sent()[-1]
    assert prompt["text"] == plaud_mod.edit_prompt(rt.store.meeting_any(mid)["title"], "uz-cyrl")
    assert f"bayonnomasida ({lang}) nimani o'zgartirish kerak?\nYozing yoki ovozli xabar yuboring" in prompt["text"]
    assert prompt["reply_markup"] == {"force_reply": True,
                                      "input_field_placeholder": "Masalan: 3-bandda muddat 1-dekabr"}
    assert plaud._intents[(TG_ID, prompt["message_id"])] == ("revise", "uz-cyrl")
    # Matnli javob - tahrir: javob, "⏳ … tahrirlanmoqda", yangi fayllar, natija.
    docs = len(tg.sent("send_document"))
    bot.handle_update(reply("TITLE=Moliya qo'mitasi yig'ilishi", replied(prompt)))
    assert seen == [{"channel": "telegram", "intent": "revise", "minutes_lang": "uz-cyrl"}]
    holder, working = tg.sent()[-2:]
    assert holder["text"] == "⏳ Javob tayyorlanmoqda…" and holder["reply_to"] == 30
    assert working["text"] == f"⏳ Bayonnoma ({lang}) tahrirlanmoqda… 1-3 daqiqa."
    answer = next(kw for kw in tg.sent("edit_message_text") if kw["message_id"] == holder["message_id"])
    assert answer["text"] == "So'rovingiz bo'yicha bayonnomaning yangi versiyasini tayyorlayapman - odatda 1-3 daqiqa."
    assert answer["reply_markup"] == plaud_mod.chat_menu(mid)
    [new_docx] = tg.sent("send_document")[docs:]                                 # tanlangan format - Word
    assert new_docx["reply_markup"] == done
    assert "2-таҳрир" in new_docx["filename"] and new_docx["filename"].endswith(".docx")
    assert new_docx["caption"] == plaud_mod.MINUTES_CAPTION
    result = last_edit(tg)
    assert result["message_id"] == working["message_id"] and result["reply_markup"] == done
    assert result["text"].startswith(f"✅ <b>Bayonnoma tahrirlandi</b> ({lang}, 2-versiya): 2 bo'lim, ")
    assert ("\n\nSo'rov: «TITLE=Moliya qo'mitasi yig'ilishi»\n\n<b>O'zgarishlar:</b> sarlavha o'zgardi."
            in result["text"])
    assert all(plaud._intents[(TG_ID, kw["message_id"])] == ("doc", "uz-cyrl") for kw in (new_docx, result))
    assert [c["op"] for c in _minutes_calls(rt)] == ["meeting_minutes", "meeting_minutes_revise"]
    assert bot.backend.questions == []
    # Ovozli javob (natija ostidagi ✏️ dan yangi so'rovga) ham - tahrir, shu tilda.
    bot.handle_update(callback(f"p:w:{mid}:uz-cyrl", message_id=result["message_id"]))
    _voice_reply(bot, tg, replied(tg.sent()[-1]), "DROP=1")
    assert seen[-1] == {"channel": "telegram", "intent": "revise", "minutes_lang": "uz-cyrl"}
    final = last_edit(tg)
    assert final["text"].startswith(f"✅ <b>Bayonnoma tahrirlandi</b> ({lang}, 3-versiya): ")
    assert "So'rov: «DROP=1»" in final["text"]
    assert "<b>O'zgarishlar:</b> avvalgi 1-band olib tashlandi." in final["text"]
    rows = rt.store.minutes_rows(mid)
    assert [(r["revision"], r["status"]) for r in rows] == [(0, "ready"), (1, "ready"), (2, "ready")]
    assert bot.backend.questions == []


def test_bayonnoma_tahriri_oxirigacha_qayta_bosish_bepul(world, monkeypatch):
    """Oxirigacha (`FakeLLM`): til -> 1-versiya; ✏️ "TITLE=…" -> 2-versiyaning fayllari; o'sha tilni qayta bosish -
    model chaqirilmaydi, 2-versiya qayta yuboriladi (tahrir yo'qolmaydi)."""
    bot, tg, rt, plaud = world
    _queued_minutes(monkeypatch, rt, plaud)
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))
    first = [d["filename"] for d in tg.sent("send_document")]
    assert len(first) == 1 and not any("таҳрир" in name for name in first)
    bot.handle_update(callback(f"p:w:{mid}:uz-cyrl:docx", message_id=tg.sent("send_document")[0]["message_id"]))
    bot.handle_update(reply("TITLE=Yangi sarlavha", replied(tg.sent()[-1])))
    second = [d["filename"] for d in tg.sent("send_document")[1:]]
    assert len(second) == 1 and all("2-таҳрир" in name for name in second)
    calls = len(rt.llm.calls)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))
    assert len(rt.llm.calls) == calls and len(rt.store.minutes_rows(mid)) == 2
    assert [d["filename"] for d in tg.sent("send_document")[2:]] == second
    assert last_edit(tg)["text"].startswith(f"✅ <b>Bayonnoma tahrirlandi</b> ({minutes.LANG_TITLES['uz-cyrl']}, "
                                            "2-versiya): ")


def test_hujjatga_javob_avto(world, monkeypatch):
    """Bayonnoma fayliga (Word / PDF) yoki natijasiga javob (Reply) - matn ham, ovoz ham: aniq niyatsiz (amalni chat
    modeli tanlaydi), lekin hujjat tili ma'lum (`minutes_lang`); HR yordamchisiga ketmaydi."""
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    _stub_minutes(monkeypatch)
    bot.handle_update(callback(f"p:d:{mid}:uz-latn:docx", message_id=summary_id))
    bot.handle_update(callback(f"p:d:{mid}:uz-latn:pdf", message_id=summary_id))
    docx, pdf = tg.sent("send_document")
    result = last_edit(tg)
    seen = _recording(monkeypatch)
    bot.handle_update(reply("3-bandda muddat qachon?", replied_document(docx)))
    assert tg.sent()[-1]["text"] == "⏳ Javob tayyorlanmoqda…" and "📌 <b>Manbalar:</b>" in last_edit(tg)["text"]
    bot.handle_update(reply("Kim mas'ul?", replied_document(pdf), message_id=31))
    bot.handle_update(reply("Yana?", replied(result), message_id=32))
    _voice_reply(bot, tg, replied_document(docx), "Qaror nima?")
    assert seen == [{"channel": "telegram", "intent": None, "minutes_lang": "uz-latn"}] * 4
    assert [t["question"] for t in rt.store.chat_turns(mid)] == ["3-bandda muddat qachon?", "Kim mas'ul?", "Yana?",
                                                                 "Qaror nima?"]
    assert bot.backend.questions == []


def test_avto_niyat_claude_tayyorlash_va_tahrir(world, monkeypatch):
    """Haqiqiy chat (soxta Claude - amalni u tanlaydi): xulosaga javob "tayyorla" - hujjat yoziladi ("⏳ …
    tayyorlanmoqda", fayllar, natija); Word fayliga javob "o'zgartir" (tili aytilmagan - fayl tilidan) - yangi
    versiya."""
    bot, tg, rt, plaud = world
    _queued_minutes(monkeypatch, rt, plaud)
    fake = _claude_chat(monkeypatch, rt)
    mid, _ = _delivered(bot, tg)
    lang = minutes.LANG_TITLES["uz-cyrl"]
    bot.handle_update(reply("ACTION=create", replied(card(tg))))
    assert fake.ops() == ["meeting_chat"]
    working = tg.sent()[-1]
    assert working["text"] == f"⏳ Bayonnoma ({lang}) tayyorlanmoqda… 1-3 daqiqa."
    [docx] = tg.sent("send_document")                     # chatdan boshlangan hujjat - Word (format tanlanmagan)
    assert docx["reply_markup"] == plaud_mod.minutes_done_menu(mid, "uz-cyrl", "docx")
    created = last_edit(tg)
    assert created["message_id"] == working["message_id"]
    assert created["text"].startswith(f"✅ <b>Bayonnoma tayyor</b> ({lang}): ")
    bot.handle_update(reply("ACTION=revise TITLE=Kengash yig'ilishi", replied_document(docx), message_id=31))
    assert fake.ops() == ["meeting_chat", "meeting_chat"]
    assert tg.sent()[-1]["text"] == f"⏳ Bayonnoma ({lang}) tahrirlanmoqda… 1-3 daqiqa."
    revised = last_edit(tg)
    assert revised["text"].startswith(f"✅ <b>Bayonnoma tahrirlandi</b> ({lang}, 2-versiya): ")
    assert "<b>O'zgarishlar:</b> sarlavha o'zgardi." in revised["text"]
    assert len(tg.sent("send_document")) == 2
    assert [t["kind"] for t in rt.store.chat_turns(mid)] == ["create", "revise"]
    assert bot.backend.questions == []


def test_pdf_tahriri_ham_pdf_qayta_ishga_tushgandan_keyin_ham(world, monkeypatch):
    """PDF tanlangan hujjatning tahriri ham PDF (ega qarori 2026-11-13: odam tanlagan format). Qayta ishga tushgandan
    keyin (xotira bo'sh) format fayl tugmasidagi `p:w:<id>:<til>:pdf` dan tiklanadi - ✏️ so'rovi orqali ham, faylga
    to'g'ridan-to'g'ri javob (amalni chat modeli tanlaydi) orqali ham."""
    bot, tg, rt, plaud = world
    _queued_minutes(monkeypatch, rt, plaud)
    _claude_chat(monkeypatch, rt)
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:pdf", message_id=summary_id))
    [pdf] = tg.sent("send_document")
    assert pdf["filename"].endswith(".pdf") and pdf["caption"] == plaud_mod.MINUTES_PDF_CAPTION
    plaud._formats.clear()                                                    # qayta ishga tushdi
    bot.handle_update(callback(f"p:w:{mid}:uz-cyrl:pdf", message_id=pdf["message_id"]))
    bot.handle_update(reply("TITLE=Yangi sarlavha", replied(tg.sent()[-1])))
    [second] = tg.sent("send_document")[1:]
    assert "2-таҳрир" in second["filename"] and second["filename"].endswith(".pdf")
    assert second["reply_markup"] == plaud_mod.minutes_done_menu(mid, "uz-cyrl", "pdf")
    plaud._messages.clear()
    plaud._intents.clear()
    plaud._formats.clear()
    bot.handle_update(reply("ACTION=revise TITLE=Uchinchi", replied_document(second), message_id=31))
    [third] = tg.sent("send_document")[2:]
    assert "3-таҳрир" in third["filename"] and third["filename"].endswith(".pdf")
    assert [r["revision"] for r in rt.store.minutes_rows(mid)] == [0, 1, 2] and bot.backend.questions == []


def test_tahrir_ozgarmasa_yoki_ish_boshlanmasa(world, monkeypatch):
    """O'zgarishsiz so'rov - yangi versiya yo'q: "Bayonnoma tahrirlanmadi: …" va «✏️ O'zgartirish» (qayta so'rash).
    Ish boshlanmasa (tahrir chegarasi) - javobda sababi; bayonnoma "⏳" i ham, fayl ham yo'q."""
    bot, tg, rt, plaud = world
    _queued_minutes(monkeypatch, rt, plaud)
    monkeypatch.setattr(settings, "meetings_minutes_edits_per_hour", 1)
    mid, summary_id = _delivered(bot, tg)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))
    docs = len(tg.sent("send_document"))
    bot.handle_update(callback(f"p:w:{mid}:uz-cyrl", message_id=summary_id))
    bot.handle_update(reply("NOOP", replied(tg.sent()[-1])))
    failed = last_edit(tg)
    assert failed["text"] == ("Bayonnoma tahrirlanmadi: Bayonnomada o'zgarish bo'lmadi - nimani o'zgartirish "
                              "kerakligini aniqroq yozing (masalan: «3-bandda muddat - 1-dekabr»)")
    assert failed["reply_markup"] == plaud_mod.minutes_done_menu(mid, "uz-cyrl", "docx")
    assert len(tg.sent("send_document")) == docs
    bot.handle_update(callback(f"p:w:{mid}:uz-cyrl", message_id=failed["message_id"]))
    sent = len(tg.sent())
    bot.handle_update(reply("TITLE=Yangi", replied(tg.sent()[-1]), message_id=31))
    answer = last_edit(tg)
    assert answer["text"] == ("Bayonnoma ishini boshlab bo'lmadi.\n\n"
                              "⚠ So'rovlar ko'p - birozdan keyin qayta urinib ko'ring")
    assert answer["reply_markup"] == plaud_mod.chat_menu(mid)
    assert len(tg.sent()) == sent + 1 and len(tg.sent("send_document")) == docs      # faqat "⏳ Javob"
    assert [r["status"] for r in rt.store.minutes_rows(mid)] == ["ready", "failed"]


def test_bayonnoma_hali_tayyorlanmoqda(world, monkeypatch):
    """Kutish chegarasidan keyin ham yozilmoqda: til tugmasi ham, chat navbati boshlagan ish ham - "hali
    tayyorlanmoqda" (natija keyin til tugmasidan bepul olinadi); tayyor bo'lmagan hujjat eksport qilinmaydi."""
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _minutes_view(status="running"))
    monkeypatch.setattr(minutes, "export_file",
                        lambda *a, **k: pytest.fail("tayyor bo'lmagan hujjat eksport qilinmaydi"))
    bot.handle_update(callback(f"p:d:{mid}:ru:pdf", message_id=summary_id))
    assert last_edit(tg)["text"] == plaud_mod.MINUTES_STILL_RUNNING and tg.sent("send_document") == []
    turn = {"id": "q1", "question": "Tayyorla", "answer": "Tushunarli.", "citations": [], "followUps": [],
            "createdAt": "2026-11-12T10:00:00Z", "channel": "telegram", "model": "claude-sonnet-5-5", "kind": "create",
            "minutes": {"action": "create", "language": "ru", "id": "cd" * 16, "status": "running", "version": 1,
                        "notes": None, "error": None}}
    waited = []
    monkeypatch.setattr(service, "chat_send", lambda *a, **k: turn)
    monkeypatch.setattr(minutes, "status", lambda *a, **k: _minutes_view(id="cd" * 16, status="running"))
    monkeypatch.setattr(minutes, "wait", lambda *a, **k: waited.append(k) or _minutes_view(status="running"))
    bot.handle_update(reply("Bayonnomani rus tilida tayyorla", replied(card(tg))))
    working = tg.sent()[-1]
    assert working["text"] == f"⏳ Bayonnoma ({minutes.LANG_TITLES['ru']}) tayyorlanmoqda… 1-3 daqiqa."
    assert waited == [{"sleep": plaud._sleep}]
    assert last_edit(tg)["message_id"] == working["message_id"]
    assert last_edit(tg)["text"] == plaud_mod.MINUTES_STILL_RUNNING and tg.sent("send_document") == []


def test_qayta_ishga_tushgandan_keyin_bayonnoma_sorovlari_va_fayli(world, monkeypatch):
    """Qayta ishga tushgandan keyin (xotira bo'sh): eski ✍️ / ✏️ so'roviga javob - matn ham, ovoz ham - izoh bilan
    yutiladi (`STALE_GUIDE` / `STALE_EDIT`; HR ga ham, chatga ham emas); faylga javob esa tugmasidagi `p:w` dan
    yig'ilishni ham, tilni ham topadi."""
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    _stub_minutes(monkeypatch)
    bot.handle_update(callback(f"p:d:{mid}:uz-cyrl:docx", message_id=summary_id))
    docx = tg.sent("send_document")[0]
    bot.handle_update(callback(f"p:g:{mid}", message_id=summary_id))
    guide = tg.sent()[-1]
    bot.handle_update(callback(f"p:w:{mid}:uz-cyrl", message_id=docx["message_id"]))
    edit = tg.sent()[-1]
    plaud._messages.clear()
    plaud._intents.clear()
    plaud._formats.clear()
    llm_calls = len(rt.llm.calls)
    bot.handle_update(reply("Rais - Karimov", replied(guide)))
    assert tg.sent()[-1]["text"] == plaud_mod.STALE_GUIDE and tg.sent()[-1]["reply_to"] == 30
    assert plaud_mod.STALE_GUIDE == ("Bu so'rov eskirgan - «📄 Bayonnoma» menyusidagi «✍️ Ko'rsatma berish»ni "
                                     "qayta bosing.")
    bot.handle_update(reply("3-bandni o'chiring", replied(edit), message_id=31))
    assert tg.sent()[-1]["text"] == plaud_mod.STALE_EDIT and tg.sent()[-1]["reply_to"] == 31
    assert plaud_mod.STALE_EDIT == "Bu so'rov eskirgan - bayonnoma ostidagi «✏️ O'zgartirish» tugmasini qayta bosing."
    _voice_reply(bot, tg, replied(edit), "3-bandni o'chiring")
    assert tg.sent()[-1]["text"] == plaud_mod.STALE_EDIT
    assert bot.backend.questions == [] and rt.store.chat_turns(mid) == [] and len(rt.llm.calls) == llm_calls
    seen = _recording(monkeypatch)
    bot.handle_update(reply("Kim mas'ul?", replied_document(docx), message_id=32))
    assert tg.sent()[-1]["text"] == "⏳ Javob tayyorlanmoqda…"
    assert seen == [{"channel": "telegram", "intent": None, "minutes_lang": "uz-cyrl"}] and bot.backend.questions == []
    # Fayl tugmasidagi format (`p:w:<id>:<til>:docx`) ham tiklandi - tahrir fayli o'sha formatda.
    assert plaud._formats[(TG_ID, mid, "uz-cyrl")] == "docx"


def test_begona_p_g_p_w(world):
    """Begona odam ✍️ / ✏️ ni bossa - faqat ogohlantirish (so'rov yuborilmaydi); noma'lum til yoki ortiqcha qism -
    "Tugma eskirgan"."""
    bot, tg, rt, plaud = world
    mid, summary_id = _delivered(bot, tg)
    for data in (f"p:g:{mid}", f"p:w:{mid}:uz-cyrl"):
        before = len(tg.calls)
        bot.handle_update(callback(data, message_id=summary_id, tg_id=OTHER_TG))
        assert [n for n, _ in tg.calls[before:]] == ["answer_callback"]
        assert tg.calls[-1][1]["alert"] and tg.calls[-1][1]["text"].startswith("Bajarib bo'lmadi")
    for data in (f"p:w:{mid}:de", f"p:w:{mid}", f"p:w:{mid}:ru:x", f"p:g:{mid}:x"):
        before = len(tg.calls)
        bot.handle_update(callback(data, message_id=summary_id))
        assert [n for n, _ in tg.calls[before:]] == ["answer_callback"]
        assert tg.calls[-1][1]["text"] == "Tugma eskirgan"
    assert not plaud._intents


def test_bayonnoma_chati_sof_funksiyalar():
    mid = "ab" * 16
    # So'rovlar: matni, turi (Telegram javobdagi xabarni teglarsiz beradi); odamniki yoki boshqa bot xabari - emas.
    guide = plaud_mod.guide_prompt("Reja <2026>")
    assert guide == ("✍️ <b>Reja &lt;2026&gt;</b> bayonnomasi uchun ko'rsatma yozing.\n"
                     "Nimaga e'tibor berish, rais va qatnashchilar, tuzilma, atamalar - matn yoki ovozli xabar bilan "
                     "javob (Reply) qilib yozing. Keyin «📄 Bayonnoma» tugmasidan hujjat tili va formatini tanlang.")
    edit = plaud_mod.edit_prompt(None, "ru")
    assert edit == (f"✏️ <b>Yozuv</b> bayonnomasida ({minutes.LANG_TITLES['ru']}) nimani o'zgartirish kerak?\n"
                    "Yozing yoki ovozli xabar yuboring, masalan: «3-bandda muddat 1-dekabr bo'lsin», «raisni Alisher "
                    "Karimov deb yozing». Barno faqat so'ralgan joyni o'zgartiradi va yangi faylni shu formatda "
                    "yuboradi.")

    def from_bot(text):
        return {"from": {"is_bot": True}, "text": render.plain(text)}

    kinds = [plaud_mod.prompt_kind(from_bot(t)) for t in (plaud_mod.ask_prompt("R"), guide, edit)]
    assert kinds == ["ask", "note", "revise"]
    assert plaud_mod.prompt_kind(from_bot(guide.replace("️", ""))) == "note"     # emoji tanlagichisiz ham
    assert plaud_mod.prompt_kind({"from": {"is_bot": False}, "text": render.plain(edit)}) is None
    for text in (plaud_mod.NOTE_SAVED.format(n=1), "✏️ Boshqa xabar", plaud_mod._HINT, plaud_mod.MINUTES_CAPTION):
        assert plaud_mod.prompt_kind(from_bot(text)) is None and not plaud_mod.is_prompt(from_bot(text))
    assert plaud_mod.is_prompt(from_bot(guide)) and plaud_mod.is_prompt(from_bot(edit))
    # Tugmalar: 64 bayt chegarasida; `p:g` / `p:w` ham yig'ilish belgisi, `p:w` - tili bilan.
    assert plaud_mod.minutes_done_menu(mid, "uz-cyrl") == {"inline_keyboard": [
        [{"text": "✏️ O'zgartirish", "callback_data": f"p:w:{mid}:uz-cyrl"}],
        [{"text": "💬 Savol berish", "callback_data": f"p:q:{mid}"}]]}
    assert plaud_mod.note_menu(mid) == {"inline_keyboard": [
        [{"text": "📄 Bayonnoma tayyorlash", "callback_data": f"p:d:{mid}"}],
        [{"text": "💬 Yana savol", "callback_data": f"p:q:{mid}"},
         {"text": "🔄 Yangi suhbat", "callback_data": f"p:n:{mid}"}]]}
    assert max(len(f"p:w:{mid}:{lang}".encode()) for lang in minutes.LANGS) <= render.CALLBACK_MAX
    for data in (f"p:g:{mid}", f"p:w:{mid}:uz-latn"):
        assert plaud_mod._MARK.match(data).group(1) == mid
    assert plaud_mod._marks({"reply_markup": plaud_mod.minutes_done_menu(mid, "en")}) == (mid, "en", None)
    assert plaud_mod._marks({"reply_markup": plaud_mod.minutes_done_menu(mid, "en", "pdf")}) == (mid, "en", "pdf")
    assert plaud_mod.minutes_done_menu(mid, "en", "txt") == plaud_mod.minutes_done_menu(mid, "en")
    assert max(len(f"p:w:{mid}:{lang}:docx".encode()) for lang in minutes.LANGS) <= render.CALLBACK_MAX
    assert plaud_mod._marks({"reply_markup": plaud_mod.chat_menu(mid)}) == (mid, None, None)
    other = "cd" * 16
    foreign = {"inline_keyboard": [[{"callback_data": f"p:q:{mid}"}], [{"callback_data": f"p:w:{other}:en"}]]}
    assert plaud_mod._marks({"reply_markup": foreign}) == (mid, None, None)
    unknown = {"inline_keyboard": [[{"callback_data": f"p:w:{mid}:de"}]]}
    assert plaud_mod._marks({"reply_markup": unknown}) == (mid, None, None)
    assert plaud_mod._marks({"text": "x"}) is None
    # Natija: so'rov bo'yicha tahrir, ko'rsatmalar tahriri (o'zgarishsiz ham), asl hujjat (ko'rsatmalar soni bilan).
    empty = {"changed": [], "added": [], "removed": []}
    changes = {"items": {"changed": [3], "added": [8], "removed": []}, "agenda": empty, "header": ["chair"],
               "other": []}
    revised = plaud_mod.minutes_html(_minutes_view(notes=[], kind="revise", version=2, notesApplied=1,
                                                   request="3-bandda <muddat>\n1-dekabr", changes=changes), "uz-cyrl")
    assert revised == (f"✅ <b>Bayonnoma tahrirlandi</b> ({minutes.LANG_TITLES['uz-cyrl']}, 2-versiya): 2 bo'lim, "
                       "5 band.\n\nSo'rov: «3-bandda &lt;muddat&gt; 1-dekabr»"
                       "\n\n<b>O'zgarishlar:</b> 3-band o'zgardi; 8-band qo'shildi; rais yangilandi.")
    noted = plaud_mod.minutes_html(_minutes_view(notes=[], kind="revise", version=3, request=None,
                                                 changes=minutes.diff.changes({}, {})), "en")
    assert noted == (f"✅ <b>Bayonnoma yangilandi</b> ({minutes.LANG_TITLES['en']}, 3-versiya): ko'rsatmalaringiz "
                     "qo'llandi - 2 bo'lim, 5 band.\n\n"
                     "Ko'rsatmalar bayonnomada allaqachon aks etgan - matn o'zgarmadi.")
    fresh = plaud_mod.minutes_html(_minutes_view(
        notes=[], notesApplied=2, warnings=["header_dropped:attendees", "header_dropped:chair", "header_capped",
                                            "superseded_revisions:2", "guidance_truncated:3"]), "ru")
    assert fresh == (f"✅ <b>Bayonnoma tayyor</b> ({minutes.LANG_TITLES['ru']}): 2 bo'lim, 5 band. Ko'rsatmalaringiz "
                     "hisobga olindi (2 ta).\n\n"
                     "Ko'rsatmada aniq aytilmagan sarlavha qiymatlari bo'sh qoldirildi: qatnashchilar, rais.\n\n"
                     "⚠ Matn tahrirlangani uchun bayonnoma yangidan yozildi - avvalgi 2 ta o'zgartirish kiritilmagan, "
                     "kerak bo'lsa qayta yozing.\n\n"
                     "⚠ Ko'rsatmalar juda ko'p - eng eskilaridan 3 tasi hisobga olinmadi.")
    # Chat javobi ostidagi bayonnoma qatori.
    assert plaud_mod.minutes_note(None) == "" and plaud_mod.minutes_note({"action": "create", "id": "x"}) == ""
    assert plaud_mod.minutes_note({"action": "note", "notes": 3}) == (
        "\n\n📝 Ko'rsatma eslab qolindi (jami 3 ta) - bayonnoma tayyorlashda hisobga olinadi.")
    assert plaud_mod.minutes_note({"action": "revise", "id": None,
                                   "error": {"code": "minutes_busy", "message": "Band <1>"}}) == "\n\n⚠ Band &lt;1&gt;"
    # Matnlar: yordam, Plaud tavsifi va yangi suhbat - bayonnoma haqida ham.
    assert plaud_mod._HINT.endswith(" Bayonnoma uchun ko'rsatmani ham shunday yozsa bo'ladi.")
    assert plaud_mod.PROMPT.endswith("\n\nBayonnoma uchun ko'rsatma bermoqchi yoki tayyor bayonnomani o'zgartirmoqchi "
                                     "bo'lsangiz - «📄 Bayonnoma» menyusidagi «✍️ Ko'rsatma berish»ni bosing yoki "
                                     "bayonnomaga javob (Reply) qilib yozing: Barno tushunib, yangi versiyasini "
                                     "yuboradi.")
    assert render._balanced(plaud_mod.PROMPT)


# --- video (2026-11-17, ega qarori): audiosi olinadi, video saqlanmaydi ---------------------


def video_update(kind="video", *, file_id="vd1", mime="video/mp4", name=None, size=5000, message_id=22, tg_id=TG_ID):
    payload = {"file_id": file_id, "file_unique_id": f"U{file_id}", "duration": 64, "file_size": size}
    if mime:
        payload["mime_type"] = mime
    if name:
        payload["file_name"] = name
    return {"update_id": 7, "message": {"message_id": message_id, "date": 1762250000,
                                        "from": {"id": tg_id, "is_bot": False},
                                        "chat": {"id": tg_id, "type": "private"}, kind: payload}}


@pytest.mark.parametrize("kind,mime,name,title", [
    ("video", "video/mp4", "yigilish.mp4", "Telegram: yigilish.mp4"),
    ("video_note", None, None, "Telegram: video"),                                  # dumaloq video
    ("document", "video/quicktime", "yigilish.mov", "Telegram: yigilish.mov"),      # fayl sifatidagi video
])
def test_video_plaud_yozuvi_audiosi_olinadi(world, kind, mime, name, title):
    from test_meetings_video import video_mp4

    bot, tg, rt, plaud = world
    tg.files["voice/vd1.oga"] = video_mp4(64)
    bot.handle_update(video_update(kind, mime=mime, name=name))
    assert len(rt.gapi.submits) == 1
    rows, total = rt.store.list_meetings(1, limit=10, offset=0)
    assert total == 1 and rows[0]["title"] == title
    assert rows[0]["content_type"] == "audio/aac" and rows[0]["audio_path"].endswith(".aac")
    status = next(kw for kw in tg.sent() if kw["text"].startswith("🎬 "))
    assert "videodan faqat audio olinadi, video saqlanmaydi" in status["text"] and status["reply_to"] == 22
    assert any(t.startswith("🎙 <b>Transkript</b>") for t in tg.texts())
    # Odamning video xabari chatda qoladi (o'chirilmaydi), arxivga ham yozilmaydi.
    assert not [kw for n, kw in tg.calls if n == "delete_message" and kw["message_id"] == 22]
    assert not [r for r in archive.get().rows(channel="telegram") if r["kind"] in ("video", "video_note", "document")]


def test_video_mp4_bolmasa_yoki_ovozsiz_yoki_katta(world):
    from test_meetings_video import WEBM, video_mp4

    bot, tg, rt, plaud = world
    tg.files["voice/w1.oga"] = WEBM
    bot.handle_update(video_update("document", file_id="w1", mime="video/webm", name="a.webm"))
    assert tg.texts()[-1] == "Matnga o'girib bo'lmadi: Bu formatdan audio ajratib bo'lmadi, MP4 yuboring."
    assert tg.sent()[-1]["reply_markup"] is None
    tg.files["voice/s1.oga"] = video_mp4(sound=False)
    bot.handle_update(video_update(file_id="s1", message_id=23))
    assert tg.texts()[-1] == "Matnga o'girib bo'lmadi: Videoda ovoz yo'q." and tg.sent()[-1]["reply_markup"] is None
    bot.handle_update(video_update(file_id="big", size=plaud_mod.MAX_FILE + 1, message_id=24))
    assert "20 MB" in tg.texts()[-1] and "Slack" in tg.texts()[-1]
    assert rt.gapi.submits == []


def test_ulanmagan_odamning_videosi_avvalgidek_ochiriladi(world):
    from test_telegram_bot import VIDEO_NOTE

    bot, tg, rt, plaud = world
    bot.handle_update(video_update(tg_id=5550099, message_id=25))
    assert ("delete_message", {"chat_id": 5550099, "message_id": 25}) in tg.calls
    assert tg.texts() == [VIDEO_NOTE] and rt.gapi.submits == []

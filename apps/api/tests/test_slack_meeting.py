"""Slack ilovasi (`app/slack/meeting.py`): transkriptdan keyingi imkoniyatlar - thread'dagi
savol, vazifalar, boshqa shablon bilan xulosa, eksport, boshqa tilda qayta o'girish.

Hammasi soxta (`slack_fakes.py`, `meetings_fakes.py`): tarmoq ham, pul ham yo'q.
"""

from __future__ import annotations

import pytest

from app.services.meetings import templates
from app.slack import meeting, render
from slack_fakes import AUDIO, BOT_USER, FakeSlack, as_parent, card, drive, elements, setup, shown


@pytest.fixture
def delivered(users_file, monkeypatch, _isolated_meetings):
    """Audio o'girilgan: (Slack, yig'ilish id, "Qisqa xulosa" xabari)."""
    setup(monkeypatch, users_file)
    client = FakeSlack(files={"F1": AUDIO})
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))
    summary = card(client)
    return client, render.marked(summary), summary


def _click(client, element, value, rt, *, selected=False):
    action = {"action_id": element, **({"selected_option": {"value": value}} if selected else {"value": value})}
    meeting.on_action(client, {"actions": [action], "channel": {"id": "D1"}, "message": {}}, sleep=drive(rt))


def _ask(client, thread, text="Kim hisobot yuboradi?"):
    event = {"channel_type": "im", "channel": "D1", "user": "U1", "text": text, "ts": "200.1", "thread_ts": thread}
    assert meeting.wants(event)
    meeting.on_message(client, event, bot_user=BOT_USER)


def test_xulosa_xabari_ostidagi_savolga_javob(delivered):
    client, mid, summary = delivered
    client.parents[summary["ts"]] = as_parent(summary)
    before = len(client.posted)
    _ask(client, summary["ts"])

    placeholder = client.posted[before]
    assert placeholder["thread_ts"] == summary["ts"] and placeholder["text"].startswith("⏳")
    [update] = client.updated
    assert update["ts"] == placeholder["ts"]
    assert "*Manbalar:*" in update["text"] and "• Kim?" in update["text"]


def test_audio_xabari_ostidagi_savolga_javob(delivered):
    client, _, _ = delivered
    client.parents["50.1"] = {"user": "U1", "ts": "50.1", "files": [AUDIO]}
    _ask(client, "50.1")

    assert "*Manbalar:*" in client.updated[0]["text"]


def test_begona_threadda_va_begona_bot_xabarida_jim(delivered):
    client, _, summary = delivered
    client.parents["60.1"] = {"user": "U1", "ts": "60.1", "text": "boshqa gap"}
    client.parents["70.1"] = {**summary, "bot_id": "B9", "user": "UOTHER"}
    before = len(client.posted)
    _ask(client, "60.1")
    _ask(client, "70.1")

    assert len(client.posted) == before and client.updated == []
    assert not meeting.wants({"channel_type": "im", "channel": "D1", "text": "salom", "ts": "1.1"})


def test_vazifalar_tugmasi(delivered, _isolated_meetings):
    client, mid, _ = delivered
    _click(client, "barno_tasks", mid, _isolated_meetings)

    assert client.posted[-1]["text"].startswith("*Vazifalar*\n")


def test_boshqa_shablon_bilan_xulosa(delivered, _isolated_meetings):
    client, mid, summary = delivered
    title = {t["id"]: t["title"] for t in templates.catalog("uz")}["minutes"]
    options = [e for e in elements(summary) if e["action_id"] == "barno_template"][0]["options"]
    assert f"{mid}|minutes" in [o["value"] for o in options]
    assert f"{mid}|auto" not in [o["value"] for o in options]
    _click(client, "barno_template", f"{mid}|minutes", _isolated_meetings, selected=True)

    assert client.posted[-1]["text"].startswith("⏳")
    assert client.updated[-1]["text"].startswith(f"*Xulosa: {title}*")


def test_eksport_transkript_va_hisobot(delivered, _isolated_meetings):
    client, mid, _ = delivered
    _click(client, "barno_export", f"{mid}|transcript_txt", _isolated_meetings, selected=True)
    _click(client, "barno_export", f"{mid}|report_docx", _isolated_meetings, selected=True)

    txt, docx = client.uploaded
    assert txt["filename"].endswith(".txt") and "Assalomu alaykum".encode() in txt["file"]
    assert docx["filename"].endswith(".docx") and docx["file"][:2] == b"PK"
    assert all(u["channel"] == "D1" and "thread_ts" not in u for u in client.uploaded)


def test_eksport_ruxsat_yoq(delivered, _isolated_meetings):
    from slack_sdk.errors import SlackApiError

    client, mid, _ = delivered
    client.upload_error = SlackApiError("missing_scope", {"ok": False, "error": "missing_scope"})
    _click(client, "barno_export", f"{mid}|transcript_srt", _isolated_meetings, selected=True)

    assert "files:write" in client.posted[-1]["text"]


def test_boshqa_tilda_qayta_ogirish(delivered, _isolated_meetings):
    client, mid, _ = delivered
    before = len(client.posted)
    _click(client, "barno_relang_ru", f"{mid}|ru", _isolated_meetings)

    assert client.posted[before]["text"].startswith("⏳ Audio rus tilida")
    assert client.updated[-1]["text"] == "✅ Audio rus tilida qayta o'girildi."
    # Rus tili - Router orqali (yig'ilish quvurining o'z qoidasi), yangi transkript chatga.
    assert [c["language"] for c in _isolated_meetings.router.calls] == ["ru"]
    assert "Добрый день" in shown(client.posted[before + 1])
    ids = [e["action_id"] for e in elements(card(client))]
    assert ids[-2:] == ["barno_relang_uz", "barno_relang_en"]


# --- 📄 Bayonnoma --------------------------------------------------------------------------------


def _fake_view(**extra):
    view = {"id": "ab" * 16, "meetingId": "m", "language": "uz-cyrl", "status": "ready", "stale": False,
            "agendaCount": 2, "sectionCount": 2, "itemCount": 5,
            "notes": ["Muddat <aniq> emas", "Mas'ul aytilmagan"], "warnings": [], "error": None}
    view.update(extra)
    return view


def _fake_export(fail_fmt: str | None = None):
    from app.services.meetings import export

    calls = []

    def export_file(user, meeting_id, minutes_id, fmt):
        calls.append((meeting_id, minutes_id, fmt))
        if fmt == fail_fmt:
            raise meeting.MeetingProblem(409, "not_ready", "Bayonnoma hali tayyor emas")
        media, ext = minutes.FORMATS[fmt]
        return fmt.encode(), media, export.content_disposition(*export.file_names("Баённома - Haftalik", 1762150000, ext))

    return export_file, calls


from app.services.meetings import minutes  # noqa: E402 - bayonnoma testlari uchun


def test_bayonnoma_tugmasi_kartada(delivered):
    _, mid, summary = delivered
    ids = [e["action_id"] for e in elements(summary)]
    assert ids[:2] == ["barno_tasks", "barno_minutes"]
    assert [e for e in elements(summary) if e["action_id"] == "barno_minutes"][0]["value"] == mid


def test_bayonnoma_til_menyusi(delivered, _isolated_meetings):
    client, mid, _ = delivered
    _click(client, "barno_minutes", mid, _isolated_meetings)

    menu = client.posted[-1]
    assert menu["text"] == render.MINUTES_PROMPT and menu["channel"] == "D1"
    buttons = elements(menu)
    # Har tugmaning o'z id si - Slack bitta blokda takror `action_id` ni rad etadi.
    assert [b["action_id"] for b in buttons] == [f"barno_minutes_lang_{lang}" for lang in
                                                 ["uz-cyrl", "uz-latn", "ru", "en"]]
    assert sorted(b["value"] for b in buttons) == sorted(f"{mid}|{lang}" for lang in minutes.LANGS)
    # O'zbek yig'ilish -> tavsiya kirill: birinchi va `primary`; qolganlarida uslub yo'q.
    assert buttons[0]["value"] == f"{mid}|uz-cyrl" and buttons[0]["style"] == "primary"
    assert buttons[0]["text"]["text"] == minutes.LANG_TITLES["uz-cyrl"]
    assert all("style" not in b for b in buttons[1:])
    actions = [b for b in menu["blocks"] if b["type"] == "actions"][0]
    assert actions["block_id"] == render.mark(mid, "minutes") and render.marked(menu) == mid


def test_bayonnoma_tanlangan_tilda_word_va_pdf(delivered, _isolated_meetings, monkeypatch):
    client, mid, _ = delivered
    generated = []

    def generate(user, meeting_id, lang, **kwargs):
        generated.append((meeting_id, lang))
        return _fake_view(warnings=["ungrounded_name:Karimov", "script_mismatch"])

    export_file, exported = _fake_export()
    monkeypatch.setattr(minutes, "generate", generate)
    monkeypatch.setattr(minutes, "export_file", export_file)
    before = len(client.posted)
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)

    holder = client.posted[before]
    assert holder["text"] == f"⏳ Bayonnoma ({minutes.LANG_TITLES['uz-cyrl']}) tayyorlanmoqda… 1-3 daqiqa."
    assert generated == [(mid, "uz-cyrl")]
    assert exported == [(mid, "ab" * 16, "docx"), (mid, "ab" * 16, "pdf")]
    docx, pdf = client.uploaded
    assert docx["file"] == b"docx" and docx["filename"].endswith(".docx")
    assert pdf["file"] == b"pdf" and pdf["filename"].endswith(".pdf")
    # Nom `Content-Disposition` dagi haqiqiy (`filename*=`) nom - kirill sarlavha bilan.
    assert docx["filename"].startswith("Баённома - Haftalik") and docx["title"] == docx["filename"]
    assert all(u["channel"] == "D1" and "thread_ts" not in u for u in client.uploaded)
    [update] = client.updated
    assert update["ts"] == holder["ts"]
    text = update["text"]
    assert text.startswith(f"✅ *Bayonnoma tayyor* ({minutes.LANG_TITLES['uz-cyrl']}): 2 bo'lim, 5 band.")
    assert "«________»" in text
    assert "*Aniqlashtirish kerak:*\n• Muddat &lt;aniq&gt; emas\n• Mas'ul aytilmagan" in text
    assert "Transkriptda bo'lmagan ismlar «________» bilan almashtirildi: Karimov" in text
    assert "kirill/lotin" in text
    assert len(client.posted) == before + 1


def test_bayonnoma_thread_ichida(delivered, _isolated_meetings, monkeypatch):
    client, mid, summary = delivered
    export_file, _ = _fake_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _fake_view(notes=[]))
    monkeypatch.setattr(minutes, "export_file", export_file)
    body = {"actions": [{"action_id": "barno_minutes_lang", "value": f"{mid}|en"}],
            "channel": {"id": "D1"}, "message": {"thread_ts": summary["ts"]}}
    meeting.on_action(client, body, sleep=drive(_isolated_meetings))

    assert client.posted[-1]["thread_ts"] == summary["ts"]
    assert all(u["thread_ts"] == summary["ts"] for u in client.uploaded)
    assert "Aniqlashtirish" not in client.updated[-1]["text"]
    assert client.updated[-1]["text"].startswith("✅ *Bayonnoma tayyor* (English)")


def test_bayonnoma_notogri_til_jim(delivered, _isolated_meetings, monkeypatch):
    client, mid, _ = delivered
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: pytest.fail("model chaqirilmasligi kerak"))
    before = len(client.posted)
    _click(client, "barno_minutes_lang", f"{mid}|de", _isolated_meetings)

    assert len(client.posted) == before and client.updated == [] and client.uploaded == []


def test_bayonnoma_yozilmadi(delivered, _isolated_meetings, monkeypatch):
    client, mid, _ = delivered

    def generate(user, meeting_id, lang, **kwargs):
        raise meeting.MeetingProblem(503, "llm_not_configured",
                                     "Bayonnoma uchun model sozlanmagan (CLAUDE_API_KEY <...>)")

    monkeypatch.setattr(minutes, "generate", generate)
    _click(client, "barno_minutes_lang", f"{mid}|ru", _isolated_meetings)

    assert client.posted[-1]["text"].startswith("⏳ Bayonnoma (Русский)")
    [update] = client.updated
    assert update["text"] == "Bayonnoma yozilmadi: Bayonnoma uchun model sozlanmagan (CLAUDE_API_KEY &lt;...&gt;)"
    assert client.uploaded == []


def test_bayonnoma_fayl_ruxsati_yoq(delivered, _isolated_meetings, monkeypatch):
    from slack_sdk.errors import SlackApiError

    client, mid, _ = delivered
    export_file, exported = _fake_export()
    monkeypatch.setattr(minutes, "generate", lambda *a, **k: _fake_view())
    monkeypatch.setattr(minutes, "export_file", export_file)
    client.upload_error = SlackApiError("missing_scope", {"ok": False, "error": "missing_scope"})
    _click(client, "barno_minutes_lang", f"{mid}|uz-latn", _isolated_meetings)

    # Yo'riqnoma "⏳" o'rniga (odam kutib qolmasin); ikkinchi fayl urinilmaydi.
    [update] = client.updated
    assert "files:write" in update["text"] and update["ts"] == client.posted[-1]["ts"]
    assert [fmt for *_, fmt in exported] == ["docx"] and client.uploaded == []


def test_bayonnoma_sozlanmagan_model_haqiqiy_quvurda(delivered, _isolated_meetings):
    """Soxtasiz: testda Claude kaliti bo'sh (`_claude_key_off`) - xizmat 503 beradi, Slack esa
    sababni "⏳" o'rniga yozadi."""
    client, mid, _ = delivered
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)

    assert client.updated[-1]["text"].startswith("Bayonnoma yozilmadi: ")
    assert "CLAUDE_API_KEY" in client.updated[-1]["text"] and client.uploaded == []


# TODO(bayonnoma): 2026-11-04 holatida `minutes/render.py` hali stub (`NotImplementedError`) - shu
# test faqat shu sababdan yiqiladi (Slack qismi `test_bayonnoma_tanlangan_tilda_word_va_pdf` da yashil).
def test_bayonnoma_haqiqiy_quvur_fakellm(delivered, _isolated_meetings, monkeypatch):
    """Oxirigacha: `MEETINGS_MINUTES_CHAIN=ollama` -> `rt.llm` (FakeLLM, `auto_reply` op
    `meeting_minutes`) -> validate -> compose -> render -> Word va PDF fayllar Slack'ga.

    E'TIBOR: `minutes/compose.py` va `minutes/render.py` boshqa agentlar tomonidan parallel
    yozilmoqda - ular hali `NotImplementedError` bersa bu test o'sha sabab bilan yiqiladi
    (Slack qismi emas). Modullar tayyor bo'lgach test o'z-o'zidan yashil bo'lishi kerak."""
    from app.core.config import settings

    client, mid, _ = delivered
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)

    assert [c["op"] for c in _isolated_meetings.llm.calls if c["op"] == "meeting_minutes"] == ["meeting_minutes"]
    docx, pdf = client.uploaded
    assert docx["filename"].endswith(".docx") and docx["file"][:2] == b"PK"
    assert pdf["filename"].endswith(".pdf") and pdf["file"][:5] == b"%PDF-"
    assert client.updated[-1]["text"].startswith("✅ *Bayonnoma tayyor* (Ўзбек (кирилл))")
    # Ikkinchi bosish - tayyor hujjat qaytadi, model qayta chaqirilmaydi.
    _click(client, "barno_minutes_lang", f"{mid}|uz-cyrl", _isolated_meetings)
    assert len([c for c in _isolated_meetings.llm.calls if c["op"] == "meeting_minutes"]) == 1
    assert len(client.uploaded) == 4

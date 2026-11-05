"""Slack'dagi Barno AI: audio -> transkript -> "Qisqa xulosa" va tugmalar; thread'dagi savol.

XABARLAR - chatning o'zida (audio thread ichida yuborilgan bo'lsa - o'sha thread'da):
  1. transkript;
  2. "Qisqa xulosa" - mobil kartadagi bilan AYNI matn (`export_meeting(parts="brief")`,
     mobil `brief.ts` bilan umumiy namunada tekshiriladi) va tugmalar: vazifalar, bayonnoma
     (rasmiy hujjat), boshqa shablon bilan xulosa, eksport (fayl), boshqa tilda qayta o'girish.
  3. "📄 Bayonnoma" - til menyusi (lotin/kirill/rus/ingliz), tanlovdan keyin Word va PDF fayl
     (`services.meetings.minutes`): hujjat 1-3 daqiqada yoziladi, odam "⏳" xabarini ko'radi.
Ikkala xabar bloki `block_id` da yig'ilish id'sini olib yuradi (`render.mark`): xabar ostidagi
thread'dagi savol yig'ilishni shundan topadi - lokal ombor kerak emas. Odamning o'z audio
xabari ostidagi savol - fayl kaliti orqali (`transcribe.meeting_of_file`).

NEGA AVTOMATIK XULOSA. Yig'ilish quvuri uni har yozuv uchun baribir yozadi (`summarizing`):
ko'rsatish qo'shimcha LLM chaqiruvi emas.

CHEGARALAR hisob bo'yicha, ya'ni hamma Slack xodimlariga UMUMIY: savol soatiga
`MEETINGS_ASK_PER_HOUR`, boshqa shablon `MEETINGS_SUMMARY_PER_HOUR`, eksport (qisqa xulosa
ham) `MEETINGS_EXPORT_PER_HOUR`, bayonnoma `MEETINGS_MINUTES_PER_HOUR` (har hujjat pullik
Claude chaqiruvi). Oshsa xizmatning o'z xabari ko'rsatiladi.
"""

from __future__ import annotations

import logging
import re
import time

from typing import Any

from ..schemas import meetings as schemas
from ..schemas.auth import AuthUser
from ..services import archive
from ..services.meetings import minutes, service, templates
from ..services.meetings.errors import MeetingProblem
from ..services.meetings.intake import (  # noqa: F401 - umumiy qadamlar (`intake.py`)
    SUMMARY_WAIT_SEC, Sleep, filename, summary_error, wait_summary, wait_summary_card)
from . import render, transcribe

log = logging.getLogger(__name__)
#: Savol chegarasi (`AskRequest.question`).
QUESTION_CHARS = 500
#: Eksport turlari (`render.EXPORTS`) -> xizmat formati.
_TRANSCRIPTS = {"transcript_txt": "txt", "transcript_srt": "srt"}
_REPORTS = {"report_docx": "docx", "report_pdf": "pdf"}
#: "Qayta urinish" foyda bermaydigan xatolar: so'rovning o'zi noto'g'ri, fayl katta/uzun/yaroqsiz.
_FINAL = {400, 403, 404, 413, 415, 422}
_ID = re.compile(r"[0-9a-f]{32}")


def wants(event: dict[str, Any]) -> bool:
    """Bolt tinglovchisi navbatga qo'yadimi: audio yoki thread'dagi savol."""
    return bool(transcribe.audio_files(event)) or is_question(event)


def on_message(client: Any, event: dict[str, Any], *, sleep: Sleep = time.sleep,
               bot_user: str | None = None) -> None:
    files = transcribe.audio_files(event)
    if files:
        handle(client, event["channel"], event.get("thread_ts"), files, sleep=sleep)
    elif is_question(event):
        question(client, event, bot_user=bot_user)


def is_question(event: dict[str, Any]) -> bool:
    """Shaxsiy chatdagi thread javobi - odam yozgan matn. Thread'siz matn hozircha javobsiz."""
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
        return False
    thread = event.get("thread_ts")
    return bool(thread and thread != event.get("ts") and str(event.get("text") or "").strip())


# --- audio ----------------------------------------------------------------------------------


def handle(client: Any, channel: str, thread: str | None, files: list[dict[str, Any]], *,
           sleep: Sleep = time.sleep) -> None:
    """Navbatdagi vazifa: har audio uchun transkript va xulosa, xato bo'lsa sabab (va foyda
    beradigan bo'lsa "Qayta urinish")."""
    for file in files:
        retry = f"f:{file['id']}"
        try:
            user = transcribe.account()
            meeting_id = transcribe.ingest(client, user, file)
            text = transcribe.wait_transcript(user, meeting_id, sleep=sleep)
        except transcribe.Problem as exc:
            fail(client, channel, thread, str(exc), retry if exc.retry else None)
            continue
        except MeetingProblem as exc:
            fail(client, channel, thread, str(exc.detail), None if exc.status_code in _FINAL else retry)
            continue
        except Exception:  # noqa: BLE001 - odam javobsiz qolmasin
            log.exception("Slack audio (%s): kutilmagan xato", file.get("id"))
            fail(client, channel, thread, "ichki xato.", retry)
            continue
        deliver(client, channel, thread, user, meeting_id, text, sleep=sleep)


def deliver(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, text: str, *,
            sleep: Sleep = time.sleep) -> None:
    """Transkript, keyin (yozilishini kutib) "Qisqa xulosa" va tugmalar."""
    parts = render.split(text or "Audioda nutq topilmadi.")
    for n, part in enumerate(parts, 1):
        note = "🎙 Transkript" + (f" ({n}/{len(parts)})" if len(parts) > 1 else "")
        post(client, channel, thread, render.escape(part), [
            {"type": "section", "text": {"type": "plain_text", "text": part}},
            render.context(note, block_id=render.mark(meeting_id, str(n)))])
    view = wait_summary(user, meeting_id, sleep=sleep)
    post(client, channel, thread, "Qisqa xulosa", summary_card(user, meeting_id, view))


def summary_card(user: AuthUser, meeting_id: str, view: dict[str, Any]) -> list[dict[str, Any]]:
    """"Qisqa xulosa" (yoki nega yo'qligi) va tugmalar."""
    status, retry = view["summaryStatus"], None
    if status == "ready":
        try:
            text = brief(user, meeting_id)
        except MeetingProblem as exc:
            text = f"Xulosani olib bo'lmadi: {render.escape(str(exc.detail))}"
    elif status in ("failed", "skipped"):
        reason = summary_error(user, meeting_id)
        text = "Xulosa yozilmadi" + (f": {render.escape(reason)}" if reason else ".")
        retry = f"m:{meeting_id}" if status == "failed" else None
    else:
        text = "Xulosa hali tayyor emas - birozdan keyin «Boshqa shablon bilan xulosa» dan oling."
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "Qisqa xulosa"}}]
    blocks += render.sections(text)[:render.MESSAGE_BLOCKS - 4]
    if retry:
        blocks.append(render.retry_button(retry))
    return blocks + render.controls(meeting_id, view["language"], templates.catalog("uz"))


def brief(user: AuthUser, meeting_id: str, *, summary_id: str | None = None, parts: str = "brief") -> str:
    from ..services.meetings import intake

    return render.mrkdwn(intake.brief_markdown(user, meeting_id, summary_id=summary_id, parts=parts))


def fail(client: Any, channel: str, thread: str | None, reason: str, retry: str | None = None) -> None:
    text = render.escape(f"Matnga o'girib bo'lmadi: {reason}")
    blocks = render.sections(text) + ([render.retry_button(retry)] if retry else [])
    post(client, channel, thread, text, blocks)


# --- thread'dagi savol -----------------------------------------------------------------------


def question(client: Any, event: dict[str, Any], *, bot_user: str | None = None) -> None:
    """Thread'dagi savol -> yig'ilish bo'yicha javob (manbalar bilan) o'sha thread'ga."""
    channel, thread = event["channel"], event["thread_ts"]
    try:
        user = transcribe.account()
    except transcribe.Problem as exc:
        post(client, channel, thread, render.escape(f"Javob berib bo'lmadi: {exc}"))
        return
    meeting_id = meeting_of_thread(client, channel, thread, user, bot_user=bot_user)
    if meeting_id is None:
        # Yig'ilishga bog'liq bo'lmagan thread - jim.
        return
    text = render.unescape(str(event.get("text") or "")).strip()[:QUESTION_CHARS]
    ts = post(client, channel, thread, "⏳ Javob tayyorlanmoqda…")
    try:
        view = service.detail(user, meeting_id)
        found = service.ask(user, meeting_id, text, None)
        body = render.answer(found, render.speakers(view["speakers"]), view["language"])
    except MeetingProblem as exc:
        body = render.escape(f"Javob berib bo'lmadi: {exc.detail}")
    except Exception:  # noqa: BLE001
        log.exception("Slack savoli (%s): kutilmagan xato", meeting_id)
        body = "Javob berib bo'lmadi: ichki xato."
    replace(client, channel, ts, thread, body)


def meeting_of_thread(client: Any, channel: str, thread: str, user: AuthUser, *,
                      bot_user: str | None = None) -> str | None:
    """Thread boshidagi xabar -> yig'ilish: Barno'ning transkript/xulosa xabari (`render.mark`)
    yoki odamning audio xabari (fayl kaliti)."""
    try:
        found = client.conversations_replies(channel=channel, ts=thread, limit=1, inclusive=True)
    except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
        log.warning("Slack thread'i o'qilmadi (%s): %s", channel, exc)
        return None
    messages = found.get("messages") or []
    parent = messages[0] if messages else None
    if not parent:
        return None
    if parent.get("bot_id"):
        # Belgiga faqat O'ZIMIZ yozgan xabarda ishonamiz.
        return render.marked(parent) if not bot_user or parent.get("user") == bot_user else None
    for file in parent.get("files") or []:
        if transcribe.is_audio(file):
            meeting_id = transcribe.meeting_of_file(user, file["id"])
            if meeting_id:
                return meeting_id
    return None


# --- tugmalar --------------------------------------------------------------------------------


def on_action(client: Any, body: dict[str, Any], *, sleep: Sleep = time.sleep) -> None:
    """Tugma yoki ro'yxat tanlovi. Natija chatning o'ziga (tugmali xabar thread ichida bo'lsa
    - o'sha thread'ga)."""
    action = (body.get("actions") or [{}])[0]
    kind = str(action.get("action_id") or "")
    value = str(action.get("value") or (action.get("selected_option") or {}).get("value") or "")
    channel = (body.get("channel") or {}).get("id") or (body.get("container") or {}).get("channel_id")
    thread = (body.get("message") or {}).get("thread_ts")
    if not channel:
        return
    try:
        user = transcribe.account()
        if kind == "barno_retry":
            retry(client, channel, thread, user, value, sleep=sleep)
            return
        meeting_id, _, arg = value.partition("|")
        if not _ID.fullmatch(meeting_id):
            return
        if kind == "barno_tasks":
            tasks(client, channel, thread, user, meeting_id)
        elif kind == "barno_minutes":
            minutes_menu(client, channel, thread, user, meeting_id)
        elif kind.startswith("barno_minutes_lang"):
            minutes_doc(client, channel, thread, user, meeting_id, arg)
        elif kind == "barno_template":
            template(client, channel, thread, user, meeting_id, arg, sleep=sleep)
        elif kind == "barno_export":
            export_file(client, channel, thread, user, meeting_id, arg)
        elif kind.startswith("barno_relang"):
            relang(client, channel, thread, user, meeting_id, arg, sleep=sleep)
    except transcribe.Problem as exc:
        post(client, channel, thread, render.escape(str(exc)))
    except MeetingProblem as exc:
        post(client, channel, thread, render.escape(f"Bajarib bo'lmadi: {exc.detail}"))
    except Exception:  # noqa: BLE001
        log.exception("Slack tugmasi (%s): kutilmagan xato", kind)
        post(client, channel, thread, "Bajarib bo'lmadi: ichki xato.")


def tasks(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str) -> None:
    view = service.detail(user, meeting_id)
    items = service.action_items(user, meeting_id)["items"]
    body = render.tasks(items, render.speakers(view["speakers"]), view["language"])
    post(client, channel, thread, "*Vazifalar*\n" + (body or "Bu yozuvda vazifalar topilmadi."))


def template(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, template_id: str, *,
             sleep: Sleep = time.sleep) -> None:
    """Tanlangan shablon bilan xulosa: yozilishini kutadi, so'ng "Qisqa xulosa" va shablon
    bo'limlari. Xuddi shu shablon qayta tanlansa - tayyori (`create_summary` takrorlamaydi)."""
    titles = {t["id"]: t["title"] for t in templates.catalog("uz")}
    title = titles.get(template_id)
    if title is None:
        return
    ts = post(client, channel, thread, render.escape(f"⏳ «{title}» shabloni bilan xulosa yozilmoqda…"))
    try:
        card, _ = service.create_summary(user, meeting_id, schemas.SummaryRequest(template=template_id))
        card = wait_summary_card(user, meeting_id, card["id"], sleep=sleep)
        if card["status"] == "ready":
            text = f"*Xulosa: {render.escape(title)}*\n\n" + brief(user, meeting_id, summary_id=card["id"],
                                                                     parts="brief,summary")
        elif card["status"] in ("queued", "running"):
            text = "Xulosa hali yozilmoqda - birozdan keyin shu shablonni qayta tanlang."
        else:
            reason = (card.get("error") or {}).get("message")
            text = "Xulosa yozilmadi" + (f": {render.escape(reason)}" if reason else ".")
    except MeetingProblem as exc:
        text = render.escape(f"Xulosa yozilmadi: {exc.detail}")
    replace(client, channel, ts, thread, text)


def export_file(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str,
                kind: str) -> None:
    """Fayl (`render.EXPORTS`) shu chatga. Slack'ka fayl yuborish `files:write` ruxsatini talab qiladi."""
    if kind in _TRANSCRIPTS:
        text, _, name = service.export_transcript(user, meeting_id, _TRANSCRIPTS[kind],
                                                  with_speakers=True, with_timestamps=True)
        data = text.encode("utf-8")
    elif kind == "summary_md":
        summary_id = service.detail(user, meeting_id).get("primarySummaryId")
        if not summary_id:
            raise transcribe.Problem("Bu yozuvda xulosa yo'q.")
        text, _, name = service.export_summary(user, meeting_id, summary_id, "md")
        data = text.encode("utf-8")
    elif kind in _REPORTS:
        data, _, disposition = service.export_meeting(user, meeting_id, _REPORTS[kind])
        name = filename(disposition) or f"barno.{_REPORTS[kind]}"
    else:
        return
    upload(client, channel, thread, data, name)


def upload(client: Any, channel: str, thread: str | None, data: bytes, name: str) -> None:
    """Fayl shu chatga (thread ichida bo'lsa - thread'ga). `files:write` ruxsati yo'q bo'lsa -
    `transcribe.Problem` odam tushunadigan yo'riqnoma bilan (eksport va bayonnoma uchun umumiy).
    Yuborilgan fayl arxivga ham yoziladi (ega talabi, 2026-11-05)."""
    from slack_sdk.errors import SlackApiError

    where = {"thread_ts": thread} if thread else {}
    try:
        client.files_upload_v2(channel=channel, file=data, filename=name, title=name, **where)
    except SlackApiError as exc:
        if (exc.response or {}).get("error") == "missing_scope":
            raise transcribe.Problem("Faylni yuborib bo'lmadi: ilovaga `files:write` ruxsati kerak "
                                     "(OAuth & Permissions -> Bot Token Scopes, keyin Reinstall).") from None
        raise
    archive.record("slack", "out", "document", chat=channel, data=data, name=name,
                   meta={"thread": thread} if thread else None)


# --- bayonnoma -------------------------------------------------------------------------------


def minutes_menu(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str) -> None:
    """"📄 Bayonnoma" -> hujjat tili menyusi. Tavsiya - yig'ilish tilidan (`minutes.default_lang`:
    o'zbek -> kirill), lekin tanlov odamniki (ega qarori: lotin/kirill/rus/ingliz)."""
    view = service.detail(user, meeting_id)
    post(client, channel, thread, render.MINUTES_PROMPT,
         render.minutes_menu(meeting_id, minutes.default_lang(view.get("language"))))


def minutes_doc(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str,
                lang: str) -> None:
    """Tanlangan tilda bayonnoma: "⏳" xabari, model (1-3 daqiqa, shu ipda), so'ng Word va PDF
    fayllar, "⏳" o'rniga natija (bo'lim/band soni, izohlar, ogohlantirishlar).

    NEGA WORD HAM, PDF HAM. Ega qarori: asosiy natija Word (kotib «________» joylarini
    to'ldiradi), PDF - ko'rish uchun nusxa. Avval Word yuklanadi - ruxsat yo'q bo'lsa odam
    yo'riqnomani birinchi fayldan keyin oladi, hujjatning o'zi omborda qoladi (qayta bosilsa
    model chaqirilmaydi - `minutes.generate` tayyorini qaytaradi)."""
    code = minutes.normalize(lang)
    if code is None:
        return
    title = minutes.LANG_TITLES[code]
    ts = post(client, channel, thread, f"⏳ Bayonnoma ({title}) tayyorlanmoqda… 1-3 daqiqa.")
    try:
        view = minutes.generate(user, meeting_id, code)
    except MeetingProblem as exc:
        replace(client, channel, ts, thread, render.escape(f"Bayonnoma yozilmadi: {exc.detail}"))
        return
    except Exception:  # noqa: BLE001 - "⏳" abadiy qolmasin
        log.exception("Slack bayonnomasi (%s): kutilmagan xato", meeting_id)
        replace(client, channel, ts, thread, "Bayonnoma yozilmadi: ichki xato.")
        return
    # Fayllar ALOHIDA: hujjat yozilgan va saqlangan - PDF chizilmasa (shrift, navbat) yoki fayl
    # yuborilmasa Word va natija baribir yetib boradi, sabab esa natija ostida.
    notes: list[str] = []
    for fmt in ("docx", "pdf"):
        try:
            data, _, disposition = minutes.export_file(user, meeting_id, view["id"], fmt)
            upload(client, channel, thread, data, filename(disposition) or f"bayonnoma.{fmt}")
        except transcribe.Problem as exc:
            # `files:write` yo'q - ikkinchi fayl ham yuborilmaydi; yo'riqnoma natija ostida.
            notes.append(render.escape(str(exc)))
            break
        except MeetingProblem as exc:
            notes.append(render.escape(f"{fmt.upper()} fayli tayyorlanmadi: {exc.detail}"))
        except Exception:  # noqa: BLE001
            log.exception("Slack bayonnomasi (%s): %s fayli", meeting_id, fmt)
            notes.append(f"{fmt.upper()} fayli tayyorlanmadi: ichki xato.")
    text = render.minutes_result(view, code)
    if notes:
        text += "\n" + "\n".join(f"⚠ {note}" for note in notes)
    replace(client, channel, ts, thread, text)


def relang(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, lang: str, *,
           sleep: Sleep = time.sleep) -> None:
    """Boshqa tilda qayta o'girish (GAPI qayta to'lanadi - tugmada tasdiq oynasi bor), so'ng
    yangi transkript va xulosa."""
    name = render.LANG_NAMES.get(lang)
    if name is None:
        return
    ts = post(client, channel, thread, f"⏳ Audio {name} tilida qayta o'girilmoqda…")
    try:
        service.retranscribe(user, meeting_id, schemas.RetranscribeRequest(language=lang, confirmCharge=True))
        text = transcribe.wait_transcript(user, meeting_id, sleep=sleep)
    except transcribe.Problem as exc:
        replace(client, channel, ts, thread, render.escape(f"Qayta o'girib bo'lmadi: {exc}"))
        return
    except MeetingProblem as exc:
        replace(client, channel, ts, thread, render.escape(f"Qayta o'girib bo'lmadi: {exc.detail}"))
        return
    replace(client, channel, ts, thread, f"✅ Audio {name} tilida qayta o'girildi.")
    deliver(client, channel, thread, user, meeting_id, text, sleep=sleep)


def retry(client: Any, channel: str, thread: str | None, user: AuthUser, value: str, *,
          sleep: Sleep = time.sleep) -> None:
    """"Qayta urinish": `f:<fayl>` - audio butun yo'ldan (yig'ilish kaliti fayldan, ya'ni
    tayyor qismi takrorlanmaydi), `m:<yig'ilish>` - xulosa."""
    kind, _, ident = value.partition(":")
    if kind == "f" and ident:
        handle(client, channel, thread, [client.files_info(file=ident)["file"]], sleep=sleep)
    elif kind == "m" and _ID.fullmatch(ident):
        service.retry(user, ident)
        post(client, channel, thread, "Qisqa xulosa", summary_card(user, ident, wait_summary(user, ident, sleep=sleep)))


# --- Slack'ka yozish -------------------------------------------------------------------------


def post(client: Any, channel: str, thread: str | None, text: str,
         blocks: list[dict[str, Any]] | None = None) -> str | None:
    """Xabar(lar): bloklar 45 tadan, bloksiz matn - section'larga bo'linadi. `text` - mrkdwn
    (bildirishnoma uchun ham). Qaytaradi: birinchi xabarning `ts`."""
    where = {"thread_ts": thread} if thread else {}
    first = None
    for page_text, page_blocks in _pages(text, blocks):
        try:
            sent = client.chat_postMessage(channel=channel, text=page_text, blocks=page_blocks or None, **where)
        except Exception:  # noqa: BLE001 - SlackApiError, tarmoq
            log.exception("Slack javobi yuborilmadi (%s)", channel)
            return first
        first = first or sent.get("ts")
    return first


def replace(client: Any, channel: str, ts: str | None, thread: str | None, text: str) -> None:
    """"⏳ ..." xabarini natija bilan almashtiradi; sig'masa qolgani - yangi xabarlarda."""
    pages = _pages(text, None)
    if ts:
        page_text, page_blocks = pages[0]
        try:
            client.chat_update(channel=channel, ts=ts, text=page_text, blocks=page_blocks or None)
            pages = pages[1:]
        except Exception:  # noqa: BLE001
            log.exception("Slack xabari yangilanmadi (%s)", channel)
    for page_text, page_blocks in pages:
        post(client, channel, thread, page_text, page_blocks)


def _pages(text: str, blocks: list[dict[str, Any]] | None) -> list[tuple[str, list[dict[str, Any]]]]:
    blocks = blocks if blocks is not None else render.sections(text)
    pages = [blocks[i:i + render.MESSAGE_BLOCKS] for i in range(0, len(blocks), render.MESSAGE_BLOCKS)] or [[]]
    return [(text[:3000], page) for page in pages]

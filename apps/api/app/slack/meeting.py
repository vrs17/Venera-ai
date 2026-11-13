"""Slack'dagi Barno AI: audio -> transkript -> "Qisqa xulosa" va tugmalar; yozuv chati (chatda va thread'da).

XABARLAR - chatning o'zida (audio thread ichida yuborilgan bo'lsa - o'sha thread'da):
  0. til savoli (ega talabi 2026-11-12): audio kelishi bilan DARHOL (`acknowledge`, navbatdan oldin) -
     "qabul qilindi" va «Audio qaysi tilda?» (o'zbek / rus / ingliz tugmalari). Barno ishni til tanlangandan
     KEYIN boshlaydi (`start`) - til noto'g'ri aniqlanmaydi, kartada "qayta o'girish" tugmalari kerak emas;
  0'. o'sha xabar joyida jarayon xabariga aylanadi (`intake.Progress`, ega talabi 2026-11-05): tanlangan til,
     bosqichlar - audio yuklash, matnga o'girish (foizi bilan), qisqa xulosa; xulosa (yoki xato) chiqqach
     o'chiriladi;
  1. "Qisqa xulosa" - mobil kartadagi bilan AYNI matn (`export_meeting(parts="brief")`,
     mobil `brief.ts` bilan umumiy namunada tekshiriladi) va tugmalar (ega tartibi 2026-11-12): «📥 Yuklab olish»
     (transkript TXT/SRT), «✅ Vazifalar», «📄 Bayonnoma» (rasmiy hujjat), «Eksport»
     (xulosa va hisobot fayli). Eski kartalardagi "qayta o'girish" tugmalari ham ishlaydi (`relang`); «Boshqa
     shablon bilan xulosa» esa o'chirilgan (ega qarori 2026-11-12) - eski kartada bosilsa `render.TEMPLATE_OFF`.
  2. "📄 Bayonnoma" - til menyusi (lotin/kirill/rus/ingliz), so'ng format savoli - «📄 Word» yoki «📕 PDF» (ega qarori
     2026-11-13: ikkala faylni chizib yuborish behuda), so'ng FAQAT tanlangan fayl (`services.meetings.minutes`):
     hujjat 1-3 daqiqada yoziladi, odam format savoli o'rnida "⏳" xabarini ko'radi.
BAYONNOMA CHATDA (ega so'rovi 2026-11-12): bitta yozuv - bitta suhbat, ko'rsatma ham, o'zgartirish ham shu suhbatda.
  * yozishdan OLDIN - til menyusi xabarining thread'idagi har javob ko'rsatma (`minutes` tegi, `intent` note: chat
    modelisiz, bepul); yozuvning boshqa thread'ida yozilganini chat modeli o'zi ajratadi. Til tugmasi
    ko'rsatmalarni qo'llaydi (`minutes.generate`), tayyor hujjatdan keyingi yangi ko'rsatmalar - uning tahriri;
  * yozilgandan KEYIN - natija xabari tahrir eslatmasi va `doc:<til>` belgisi bilan (`render.minutes_hint`): uning
    yoki Word / PDF faylining (`_doc_of_files`) thread'idagi keyingi matn shu yozuvga va shu til hujjatiga
    (`minutes_lang`; chatning o'zi 2026-11-13 dan - HR/CRM yordamchisi). Chat modeli "o'zgartir" deb tushunsa (yozuv
    chatida agent bo'g'ini yo'q - amalni Claude tanlaydi, `service._model_answer`) - server yangi versiyani yozadi,
    Barno uni kutib (`_follow_minutes`) yangi faylni (natija belgisidagi formatda: `doc:<til>:<format>`; eski belgida
    - Word) va nima o'zgarganini yuboradi.
TRANSKRIPT CHATGA YOZILMAYDI (ega talabi 2026-11-11): uzun matn chatni tushunarsiz qilardi. U
«📥 Yuklab olish -> Transkript (TXT)» da - .txt fayl kartaning THREAD'iga keladi (asosiy chat toza
qoladi), Slack'da shu yerdan yuklab olinadi. Istisno - xulosa yozilmagan juda qisqa yozuv: bir-ikki
gapni faylga solish o'rniga kartaning o'zida (`SHORT_TRANSCRIPT_CHARS`).
Karta bloki `block_id` da yig'ilish id'sini olib yuradi (`render.mark`): xabar ostidagi
thread'dagi savol yig'ilishni shundan topadi - lokal ombor kerak emas. Odamning o'z audio
xabari ostidagi savol - fayl kaliti orqali (`transcribe.meeting_of_file`).

YOZUV CHATI (ega talabi 2026-11-11): `service.chat_send`, kanal `slack`. Barno shu yozuvning transkripti,
xulosasi va shu suhbatdagi oldingi savol-javoblar bilan javob beradi ("batafsilroq", "u kim edi?" kabi davom
savollari ishlaydi), boshqa yozuvlar aralashmaydi. Javob ostidagi «🔄 Yangi suhbat» xotirani tozalaydi
(`service.chat_reset`, yumshoq - savol-javoblar bazada qoladi). Savol FAQAT yozuv xabarining (karta, javob,
bayonnoma natijasi yoki fayli, odamning audio xabari) thread'ida - HAR QANDAY, eski yozuv bo'yicha ham (`question`).
Chatning o'zidagi (thread'dan tashqaridagi) matn - HR/CRM yordamchisiga (`assistant.py`; ega qarori 2026-11-13,
"thread qoidasi" - 2026-11-11 dagi "chatdagi savol oxirgi yozuvga" o'rniga); yordamchi javobining thread'i ham
unga (`question` -> `assistant.on_thread`).
SUHBAT YOZUVNIKI VA ODAMNIKI (thread'niki emas). 2026-11-12 dan har kim O'Z hisobida (`transcribe.account`,
«Connect Barno AI account» - `link.py`): yozuv uniki, Slack'dagi savollari ilovadagi suhbati bilan BITTA
(`asker` yo'q - egasining suhbati). Ulanmagan odamga ish bajarilmaydi - ulash xabari (`_gate`). ESKI yozuvlar
(ulashdan oldin kelgan) umumiy hisobda qolgan: ularda, avvalgidek, xotira va «🔄 Yangi suhbat» so'rovchi
bo'yicha (`asker`, `slack:<user id>`) - bitta yozuvni ko'rgan har kim o'z suhbatini ko'radi (`who_asks`). Ulash
o'chirilgan o'rnatmada hamma narsa eskicha umumiy hisobda. Bir odamning shu yozuv haqidagi savollari (chatda
ham, istalgan thread'da ham) - bitta suhbat.

NEGA AVTOMATIK XULOSA. Yig'ilish quvuri uni har yozuv uchun baribir yozadi (`summarizing`):
ko'rsatish qo'shimcha LLM chaqiruvi emas.

CHEGARALAR hisob bo'yicha - shaxsiy hisobda har kimniki o'ziga (eski umumiy hisobda - hammaga umumiy): chat savoli soatiga
`MEETINGS_ASK_PER_HOUR`, eksport (qisqa xulosa
ham) `MEETINGS_EXPORT_PER_HOUR`, bayonnoma `MEETINGS_MINUTES_PER_HOUR` (har hujjat pullik
Claude chaqiruvi). Oshsa xizmatning o'z xabari ko'rsatiladi.
"""

from __future__ import annotations

import logging
import re
import threading
import time

from typing import Any

from ..schemas import meetings as schemas
from ..schemas.auth import AuthUser
from ..services import archive
from ..services.meetings import intake, minutes, service
from ..services.meetings.errors import MeetingProblem
from ..services.meetings.intake import (  # noqa: F401 - umumiy qadamlar (`intake.py`)
    SUMMARY_WAIT_SEC, Sleep, filename, summary_error, wait_summary, wait_summary_card)
from . import assistant, link, render, transcribe

log = logging.getLogger(__name__)
#: Chat xabari chegarasi (`ChatRequest.message`, `prompts.CHAT_QUESTION_CHARS`).
QUESTION_CHARS = 1000
#: Xulosa yozilmagan (juda qisqa) yozuvning matni shundan qisqa bo'lsa - kartaning o'zida ko'rsatiladi.
SHORT_TRANSCRIPT_CHARS = 300
#: Bayonnoma FAYLI (Word / PDF) xabarining thread'i (`_doc_of_files`): uning natija xabari fayldan oldingi shuncha xabar
#: ichida va shuncha soniya oldingacha qidiriladi. Natija ("⏳" xabari) hujjat yozilishidan OLDIN chiqadi, fayllar -
#: tayyor bo'lgach (botlar `minutes.WAIT_SEC` gacha kutadi) - zaxira bilan.
DOC_LOOKBACK = 20
DOC_FILE_WINDOW = 30 * 60
#: Eksport turlari (`render.EXPORTS`) -> xizmat formati.
_TRANSCRIPTS = {"transcript_txt": "txt", "transcript_srt": "srt"}
_REPORTS = {"report_docx": "docx", "report_pdf": "pdf"}
#: "Qayta urinish" foyda bermaydigan xatolar: so'rovning o'zi noto'g'ri, fayl katta/uzun/yaroqsiz.
_FINAL = {400, 403, 404, 413, 415, 422}
_ID = re.compile(r"[0-9a-f]{32}")
#: Slack fayli id'si (til tugmasi qiymati).
_FILE = re.compile(r"F[A-Z0-9]{1,40}")
#: Tili tanlanib, hozir ishlanayotgan fayllar: tugma ikki marta (yoki ikki til) bosilsa audio ikki marta boshlanmasin.
_started: set[str] = set()
_started_lock = threading.Lock()
#: Natijasi kuzatilgan (yoki kuzatilayotgan) chat navbatlari (`chat`): Slack hodisani qayta yuborsa (o'sha
#: `client_msg_id`) server saqlangan navbatni qaytaradi - fayllar ikkinchi marta chizilib yuklanmasin. FIFO, `_FOLLOWED_MAX`.
_followed: dict[str, None] = {}
_followed_lock = threading.Lock()
_FOLLOWED_MAX = 2000


def wants(event: dict[str, Any]) -> bool:
    """Bolt tinglovchisi buni qabul qiladimi: audio (til savoli - `acknowledge`) yoki thread'dagi savol (`on_message`)."""
    return bool(transcribe.audio_files(event)) or is_question(event)


def on_message(client: Any, event: dict[str, Any], *, bot_user: str | None = None,
               sleep: Sleep = time.sleep) -> None:
    """Navbatdagi vazifa: thread'dagi savol. Audio bu yerga kelmaydi - unga til savoli (`acknowledge`), ish esa til
    tanlangach (`start`). `sleep` - bayonnoma ishini kutish (`_follow_minutes`; dispetcherda - restartda uziladigan
    `__init__._sleep`)."""
    if is_question(event):
        question(client, event, bot_user=bot_user, sleep=sleep)


def acknowledge(client: Any, event: dict[str, Any]) -> None:
    """Audio kelishi bilan har fayl uchun "qabul qilindi" va til savoli - DARHOL, Bolt ipida (navbatdan oldin): navbat
    band bo'lsa ham odam audiosi qabul qilinganini ko'radi. Ish til tanlangach boshlanadi (`start`); bir xabardagi
    har faylning o'z savoli."""
    files = transcribe.audio_files(event)
    if files and not _gate(client, link.team_of(event), event.get("user"), event["channel"], event.get("thread_ts")):
        return
    for file in files:
        head = received(file)
        post(client, event["channel"], event.get("thread_ts"), f"{head}\n{render.LANG_QUESTION}",
             render.lang_question(head, file["id"]))


def _gate(client: Any, team: str | None, slack_user: str | None, channel: str,
          thread: str | None = None) -> bool:
    """Shaxsiy hisob majburiy bo'lsa (`link.required()`): ulanmagan odamga faqat ulash xabari («Connect Barno
    AI account») va `False` - ish bajarilmaydi; bloklangan hisobga - sababi. Aks holda `True`."""
    return link.gate(client, team, slack_user, channel, thread=thread)


def who_asks(holder: AuthUser, user: AuthUser, slack_user: Any) -> str | None:
    """Yozuv chatidagi so'rovchi (`service.chat_send` / `chat_reset` ning `asker` i). Odamning O'Z yozuvi
    (shaxsiy hisob) - `None`: Slack'dagi savollar uning ilovadagi suhbati bilan bitta. Umumiy hisobdagi
    yozuv (eski yozuvlar yoki ulash o'chirilgan o'rnatma) - `slack:<user id>`: har kim o'z suhbatida."""
    if link.required() and holder.actorId == user.actorId:
        return None
    return asker(slack_user)


def received(file: dict[str, Any]) -> str:
    """"Qabul qilindi" sarlavhasi: Slack'da yozilgan ovozli xabar yoki yuklangan fayl (nomi bilan)."""
    if file.get("subtype") == "slack_audio":
        return "🎙 Ovozli xabaringiz qabul qilindi."
    name = " ".join(str(file.get("name") or file.get("title") or "audio").split())[:80]
    return f"📎 «{render.escape(name)}» qabul qilindi."


def status(client: Any, channel: str, thread: str | None, file: dict[str, Any], *,
           language: str | None = None, ref: str | None = None) -> intake.Progress:
    """Shu audioning jarayon xabari (sarlavhada tanlangan til). `ref` - mavjud xabar (til savoli): jarayon o'sha
    xabarning o'rnida, joyida yangilanadi."""
    head = received(file)
    if language in render.LANG_NAMES:
        head += f" Til: {render.LANG_NAMES[language]}."

    def show(ts: str | None, text: str) -> str | None:
        if ts is None:
            return post(client, channel, thread, text)
        client.chat_update(channel=channel, ts=ts, text=text, blocks=render.sections(text))
        return ts

    progress = intake.Progress(head, show=show, drop=lambda ts: client.chat_delete(channel=channel, ts=ts),
                               transcript_above=False)
    progress.ref = ref
    return progress


def is_question(event: dict[str, Any]) -> bool:
    """Shaxsiy chatdagi thread javobi - odam yozgan matn. Thread'siz matn - HR/CRM yordamchisiga
    (`assistant.on_text`, dispetcherda `home.is_text`)."""
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
        return False
    thread = event.get("thread_ts")
    return bool(thread and thread != event.get("ts") and str(event.get("text") or "").strip())


# --- audio ----------------------------------------------------------------------------------


def handle(client: Any, channel: str, thread: str | None, files: list[dict[str, Any]], *,
           sleep: Sleep = time.sleep, shown: dict[str, intake.Progress] | None = None,
           language: str = intake.LANGUAGE, team: str | None = None, slack_user: str | None = None) -> None:
    """Navbatdagi vazifa: har audio (`language` tilida) uchun jarayon xabari (til savolining o'rnida yoki yangisi),
    transkript va xulosa, xato bo'lsa sabab (va foyda beradigan bo'lsa "Qayta urinish" - o'sha til bilan)."""
    for file in files:
        progress = (shown or {}).get(file.get("id")) or status(client, channel, thread, file, language=language)
        progress.show(intake.UPLOAD)
        retry = f"f:{file['id']}:{language}"
        try:
            user = transcribe.account(team, slack_user)
            meeting_id = transcribe.ingest(client, user, file, language=language)
            text = transcribe.wait_transcript(user, meeting_id, sleep=sleep, progress=progress.view)
        except transcribe.Problem as exc:
            fail(client, channel, thread, str(exc), retry if exc.retry else None,
                 progress=progress)
            continue
        except MeetingProblem as exc:
            fail(client, channel, thread, str(exc.detail), None if exc.status_code in _FINAL else retry,
                 progress=progress)
            continue
        except Exception:  # noqa: BLE001 - odam javobsiz qolmasin
            log.exception("Slack audio (%s): kutilmagan xato", file.get("id"))
            fail(client, channel, thread, "ichki xato.", retry, progress=progress)
            continue
        deliver(client, channel, thread, user, meeting_id, text, sleep=sleep, progress=progress)


def deliver(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, text: str, *,
            sleep: Sleep = time.sleep, progress: intake.Progress | None = None) -> None:
    """Matnga o'girildi: (yozilishini kutib) "Qisqa xulosa" va tugmalar. Transkript chatga YOZILMAYDI -
    kartadagi «📥 Yuklab olish» da (modul izohi). `progress` (audio yo'li) - jarayon xabari
    joyida xulosa bosqichiga o'tadi va xulosa chiqqach o'chiriladi."""
    if progress is not None:
        progress.show(intake.SUMMARY)
    try:
        view = wait_summary(user, meeting_id, sleep=sleep)
        post(client, channel, thread, "Qisqa xulosa", summary_card(user, meeting_id, view, transcript=text))
    finally:
        # Kutish uzilsa ham (server to'xtayapti) "⏳" xabari osilib qolmasin.
        if progress is not None:
            progress.close()


def summary_card(user: AuthUser, meeting_id: str, view: dict[str, Any], *,
                 transcript: str | None = None) -> list[dict[str, Any]]:
    """"Qisqa xulosa" (yoki nega yo'qligi) va tugmalar. `transcript` (matn, `wait_transcript`) - faqat
    xulosa YO'Q holat uchun: nutq yo'q bo'lsa shuni aytadi, juda qisqa bo'lsa matnni kartada ko'rsatadi."""
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
        if transcript is not None:
            spoken = " ".join(transcript.split())
            if not spoken:
                text += "\nAudioda nutq topilmadi."
            elif len(spoken) <= SHORT_TRANSCRIPT_CHARS:
                text += f"\n\n*Matn:* {render.escape(spoken)}"
    else:
        text = "Xulosa hali tayyor emas - birozdan keyin «Eksport -> Xulosa (MD)» dan oling."
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "Qisqa xulosa"}}]
    blocks += render.sections(text)[:render.MESSAGE_BLOCKS - 4]
    if retry:
        blocks.append(render.retry_button(retry))
    return blocks + render.controls(meeting_id)


def brief(user: AuthUser, meeting_id: str, *, summary_id: str | None = None, parts: str = "brief") -> str:
    return render.mrkdwn(intake.brief_markdown(user, meeting_id, summary_id=summary_id, parts=parts))


def fail(client: Any, channel: str, thread: str | None, reason: str, retry: str | None = None, *,
         progress: intake.Progress | None = None) -> None:
    """Sabab - YANGI xabarda (odamga bildirishnoma boradi), jarayon xabari o'chiriladi."""
    if progress is not None:
        progress.close()
    text = render.escape(f"Matnga o'girib bo'lmadi: {reason}")
    blocks = render.sections(text)
    if retry:
        blocks.append(render.retry_button(retry))
    post(client, channel, thread, text, blocks)


# --- yozuv chati: thread'dagi savol -----------------------------------------------------------------


def asker(slack_user: Any) -> str:
    """Umumiy hisobdagi yozuv chatining so'rovchisi: u yerda hamma odam BITTA hisobda, shuning uchun suhbat
    xotirasi va «🔄 Yangi suhbat» har odamga alohida - `slack:<user id>`. Kalit hech qachon bo'sh emas: bo'sh
    (`None`) - hisob egasining ilovadagi suhbati bo'lardi. Qaysi biri kerakligini `who_asks` hal qiladi."""
    return f"slack:{slack_user or ''}"


def question(client: Any, event: dict[str, Any], *, bot_user: str | None = None, sleep: Sleep = time.sleep) -> None:
    """Thread'dagi savol -> o'sha thread boshidagi xabarning yozuvi (`thread_target`) bo'yicha chat (`chat`): eski
    yozuv haqida ham shunday so'raladi. Thread boshi bayonnoma til menyusi (`minutes` tegi) - xabar hujjat uchun
    KO'RSATMA (`intent` note, chat modelisiz); bayonnoma natijasi (`doc:<til>`) - o'sha til hujjati bo'yicha
    (`minutes_lang`: o'zgartirish so'rovi shu hujjatning tahriri bo'ladi). Thread boshi HR/CRM yordamchisi javobi
    (`assistant.owns`) - o'sha suhbatga (`assistant.on_thread`). Boshqa thread - jim."""
    channel, thread = event["channel"], event["thread_ts"]
    parent = _parent(client, channel, thread)
    chat_id = assistant.owns(parent, bot_user=bot_user)
    if chat_id:
        assistant.on_thread(client, event, chat_id)
        return
    team, person = link.team_of(event), event.get("user")
    try:
        user = transcribe.account(team, person)
    except link.NotLinked as exc:
        link.offer(client, team, person, channel, thread=thread, state=exc.state)
        return
    except transcribe.Problem as exc:
        post(client, channel, thread, render.escape(f"Javob berib bo'lmadi: {exc}"))
        return
    target = thread_target(client, channel, thread, user, bot_user=bot_user, parent=parent)
    if target is None:
        return
    meeting_id, tag = target
    try:
        holder = transcribe.owner(user, meeting_id)
    except MeetingProblem as exc:
        post(client, channel, thread, render.escape(f"Javob berib bo'lmadi: {exc.detail}"))
        return
    chat(client, channel, thread, holder, meeting_id, _text(event), who=who_asks(holder, user, person),
         intent="note" if tag == "minutes" else None, minutes_lang=render.doc_lang(tag),
         minutes_fmt=render.doc_format(tag), client_id=_client_id(event), sleep=sleep)


def _sent_at(message: dict[str, Any]) -> float:
    """Slack xabarining vaqti (`ts` - epoch soniya); noma'lum bo'lsa 0, ya'ni "eski"."""
    try:
        return float(message.get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


def chat(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, text: str, *,
         who: str | None, intent: str | None = None, minutes_lang: str | None = None, minutes_fmt: str | None = None,
         client_id: str | None = None, sleep: Sleep = time.sleep) -> None:
    """Yozuv chatiga savol (`service.chat_send`, kanal `slack`, so'rovchi `who` - `asker`): "⏳" xabari, so'ng uning
    o'rnida javob (manbalar bilan) va «🔄 Yangi suhbat» (`render.chat_actions`). Xatoda (chegara, model, yozuv
    topilmadi) - faqat sabab, tugmasiz.

    BAYONNOMA: `intent` - aniq kirish nuqtasi (menyu thread'i - `note`), `minutes_lang` - odam qaysi til hujjatiga
    javob yozyapti (natija belgisi), `minutes_fmt` - o'sha hujjat qaysi formatda yuborilgan (yangi versiya fayli ham
    shu formatda), `client_id` - Slack xabari kaliti (takror hodisa - bitta navbat, bitta ish).
    Ko'rsatma navbatida javob ostida "eslab qolindi", ish boshlanmagan bo'lsa - sababi (`render.minutes_turn_note`);
    navbat hujjat ishini boshlagan bo'lsa (`create` / `revise`) - u kutiladi va natijasi yuboriladi
    (`_follow_minutes`, `sleep` bilan)."""
    ts = post(client, channel, thread, "⏳ Javob tayyorlanmoqda…")
    blocks, ref = None, None
    try:
        view = service.detail(user, meeting_id)
        found = service.chat_send(user, meeting_id, text, None, channel="slack", asker=who, client_id=client_id,
                                  intent=intent, minutes_lang=minutes_lang)
        ref = found.get("minutes")
        body = render.answer(found, render.speakers(view["speakers"]), view["language"])
        body += render.minutes_turn_note(ref)
        blocks = render.sections(body) + [render.chat_actions(meeting_id)]
    except MeetingProblem as exc:
        body = render.escape(f"Javob berib bo'lmadi: {exc.detail}")
    except Exception:  # noqa: BLE001
        log.exception("Slack savoli (%s): kutilmagan xato", meeting_id)
        body = "Javob berib bo'lmadi: ichki xato."
    replace(client, channel, ts, thread, body, blocks)
    if ref and ref.get("action") in ("create", "revise") and ref.get("id") and _first_follow(found["id"]):
        _follow_minutes(client, channel, thread, user, meeting_id, ref, who=who, fmt=minutes_fmt, sleep=sleep)


def _first_follow(turn_id: str) -> bool:
    """Shu chat navbatining bayonnoma natijasi hali kuzatilmaganmi (va endi bizniki): takror hodisa - `False`."""
    with _followed_lock:
        if turn_id in _followed:
            return False
        _followed[turn_id] = None
        while len(_followed) > _FOLLOWED_MAX:
            _followed.pop(next(iter(_followed)))
        return True


def _text(event: dict[str, Any]) -> str:
    """Odam yozgan savol - Slack belgilarisiz (`&lt;` -> `<`), `QUESTION_CHARS` gacha."""
    return render.unescape(str(event.get("text") or "")).strip()[:QUESTION_CHARS]


def _client_id(event: dict[str, Any]) -> str | None:
    """Odam xabarining klient kaliti (`chat_send` ning `client_id` i): Slack odam yozgan xabarga `client_msg_id` beradi
    va hodisani qayta yuborsa ham o'sha - ikkinchi navbat ham, ikkinchi pullik javob yoki bayonnoma ishi ham yo'q.
    Kalitsiz xabar - `None`: `ts` kalit qilinmaydi (soxta hodisalar bir xil `ts` ni qayta ishlatadi - har xil
    savollar bitta navbatga qo'shilib ketardi)."""
    raw = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("client_msg_id") or ""))[:58]
    return f"slack-{raw}" if raw else None


def _parent(client: Any, channel: str, thread: str) -> dict[str, Any] | None:
    """Thread boshidagi xabar (`conversations.replies`, bitta xabar); o'qib bo'lmasa yoki yo'q bo'lsa - `None`."""
    try:
        found = client.conversations_replies(channel=channel, ts=thread, limit=1, inclusive=True)
    except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
        log.warning("Slack thread'i o'qilmadi (%s): %s", channel, exc)
        return None
    messages = found.get("messages") or []
    return messages[0] if messages else None


_UNREAD = object()


def thread_target(client: Any, channel: str, thread: str, user: AuthUser, *, bot_user: str | None = None,
                  parent: Any = _UNREAD) -> tuple[str, str | None] | None:
    """Thread boshidagi xabar -> (yig'ilish, teg). Barno'ning xabari - belgisi (`render.marked_tag`): xulosa kartasi
    (""), chat javobi (`chat`), bayonnoma til menyusi (`minutes`), bayonnoma natijasi (`doc:<til>`); belgisiz
    bayonnoma FAYLI (Word / PDF) - o'z natija xabarining belgisi (`_doc_of_files`). Odamning audio xabari - fayl
    kaliti, teg `None`. Yozuvga bog'liq bo'lmagan thread - `None`. `parent` - chaqiruvchi o'qigan thread boshi
    (`question`, ikkinchi so'rov bo'lmasin)."""
    if parent is _UNREAD:
        parent = _parent(client, channel, thread)
    if not parent:
        return None
    if parent.get("bot_id") or (bot_user and parent.get("user") == bot_user):
        # Belgiga faqat O'ZIMIZ yozgan xabarda ishonamiz.
        if bot_user and parent.get("user") != bot_user:
            return None
        return render.marked_tag(parent) or _doc_of_files(client, channel, parent, user, bot_user=bot_user)
    legacy = transcribe.legacy_account() if link.required() else None
    holders = [user] + ([legacy] if legacy is not None and legacy.actorId != user.actorId else [])
    for file in parent.get("files") or []:
        if transcribe.is_audio(file):
            for holder in holders:
                meeting_id = transcribe.meeting_of_file(holder, file["id"])
                if meeting_id:
                    return meeting_id, None
    return None


def _doc_of_files(client: Any, channel: str, parent: dict[str, Any], user: AuthUser, *,
                  bot_user: str | None = None) -> tuple[str, str] | None:
    """Barno yuborgan bayonnoma FAYLI (Word / PDF) xabarining thread'i -> (yig'ilish, `doc:<til>`) yoki `None`.

    NEGA. Fayl xabariga belgi (blok) qo'yib bo'lmaydi, odam esa ko'pincha aynan faylga javob yozadi (2026-11-13 jonli:
    Word fayli ostidagi «sana 11 noyabr bo'lishi kerak» jim qolgan edi). Natija xabari (`_deliver_minutes`: "⏳" o'rnida,
    `doc:<til>` belgisi bilan) shu fayllardan OLDIN turadi - shuning uchun chat tarixida fayl xabaridan oldingi
    (`DOC_LOOKBACK` ta, `DOC_FILE_WINDOW` gacha) O'Z natija xabarimiz olinadi: tili fayl nomidagi hujjat so'zi bilan
    bir xil (`render.minutes_file_lang`). Bir nechtasi bo'lsa (ikki yozuv bayonnomasi ketma-ket) - yozuv nomi fayl
    nomida borligi (`_titled`), bo'lmasa - eng yaqini. Format - natija belgisidan; eski (formatsiz) belgida - javob
    yozilgan fayl formati (tahrir fayli ham shu formatda)."""
    langs = {lang for lang in (render.minutes_file_lang(f) for f in parent.get("files") or []) if lang}
    if not langs:
        return None
    try:
        found = client.conversations_history(channel=channel, latest=parent.get("ts"), limit=DOC_LOOKBACK,
                                             inclusive=False)
    except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
        log.warning("Slack chat tarixi o'qilmadi (%s): %s", channel, exc)
        return None
    if not found.get("ok", True):
        log.warning("Slack chat tarixi o'qilmadi (%s): %s", channel, found.get("error"))
        return None
    sent = _sent_at(parent)
    names = [str(f.get(key) or "") for f in parent.get("files") or [] for key in ("name", "title")]
    candidates: list[tuple[str, str]] = []
    for message in found.get("messages") or []:                 # yangisi birinchi
        if sent - _sent_at(message) > DOC_FILE_WINDOW:
            break
        if not message.get("bot_id") or (bot_user and message.get("user") != bot_user):
            continue
        target = render.marked_tag(message)
        if target and render.doc_lang(target[1]) in langs and target not in candidates:
            candidates.append(target)
    if not candidates:
        return None
    found = candidates[0]
    if len(candidates) > 1:
        found = next((c for c in candidates if _titled(user, c[0], names)), found)
    if render.doc_format(found[1]) is None:
        # Eski (formatsiz) natija belgisi: tahrir fayli - odam javob yozgan fayl formatida.
        fmts = {fmt for fmt in (render.minutes_file_format(f) for f in parent.get("files") or []) if fmt}
        if len(fmts) == 1:
            found = (found[0], render.doc_tag(str(render.doc_lang(found[1])), fmts.pop()))
    return found


def _titled(user: AuthUser, meeting_id: str, names: list[str]) -> bool:
    """Yozuv nomi fayl nomida bormi (harf va raqamlar bo'yicha: fayl nomida ":" kabi belgilar olib tashlangan)."""
    try:
        title = service.detail(transcribe.owner(user, meeting_id), meeting_id).get("title")
    except MeetingProblem:
        return False
    key = _letters(title)
    return bool(key) and any(key in _letters(name) for name in names)


def _letters(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def meeting_of_thread(client: Any, channel: str, thread: str, user: AuthUser, *,
                      bot_user: str | None = None) -> str | None:
    """Thread boshidagi xabarning yig'ilishi (`thread_target` ning id qismi)."""
    found = thread_target(client, channel, thread, user, bot_user=bot_user)
    return found[0] if found else None


# --- tugmalar --------------------------------------------------------------------------------


def on_action(client: Any, body: dict[str, Any], *, sleep: Sleep = time.sleep) -> None:
    """Tugma yoki ro'yxat tanlovi. Natija chatning o'ziga (tugmali xabar thread ichida bo'lsa
    - o'sha thread'ga)."""
    action = (body.get("actions") or [{}])[0]
    kind = str(action.get("action_id") or "")
    value = str(action.get("value") or (action.get("selected_option") or {}).get("value") or "")
    channel = (body.get("channel") or {}).get("id") or (body.get("container") or {}).get("channel_id")
    message = body.get("message") or {}
    thread = message.get("thread_ts")
    if not channel:
        return
    clicker, team = (body.get("user") or {}).get("id"), link.team_of(body)
    try:
        person = transcribe.account(team, clicker)
        if kind == "barno_retry":
            retry(client, channel, thread, person, value, sleep=sleep, team=team, slack_user=clicker)
            return
        if kind.startswith("barno_lang_"):
            start(client, channel, thread, value, kind[len("barno_lang_"):], ref=message.get("ts"), sleep=sleep,
                  team=team, slack_user=clicker)
            return
        meeting_id, _, arg = value.partition("|")
        if not _ID.fullmatch(meeting_id):
            return
        # Yozuv egasi: odamning o'zi yoki - eski kartada - umumiy hisob (`transcribe.owner`).
        user = transcribe.owner(person, meeting_id)
        if kind == "barno_transcript" or (arg == "transcript_txt" and kind in ("barno_download", "barno_export")):
            # «📥 Yuklab olish -> Transkript (TXT)»; eski kartalardagi tugma va "Eksport -> Transkript (TXT)" ham.
            transcript_file(client, channel, thread, user, meeting_id, card=message.get("ts"), clicker=clicker)
        elif kind == "barno_tasks":
            tasks(client, channel, thread, user, meeting_id)
        elif kind == "barno_minutes":
            minutes_menu(client, channel, _minutes_spot(message), user, meeting_id)
        elif kind.startswith("barno_minutes_lang"):
            minutes_formats(client, channel, _minutes_spot(message), meeting_id, arg)
        elif kind.startswith("barno_minutes_fmt_"):
            minutes_doc(client, channel, _minutes_spot(message), user, meeting_id, arg,
                        fmt=kind[len("barno_minutes_fmt_"):], who=who_asks(user, person, clicker),
                        holder=message.get("ts"), sleep=sleep)
        elif kind == "barno_template":
            # Eski kartadagi menyu: funksiya o'chirilgan (ega qarori 2026-11-12) - xulosa yozilmaydi.
            post(client, channel, thread, render.TEMPLATE_OFF)
        elif kind in ("barno_download", "barno_export"):
            export_file(client, channel, thread, user, meeting_id, arg)
        elif kind.startswith("barno_relang"):
            relang(client, channel, thread, user, meeting_id, arg, sleep=sleep)
        elif kind == "barno_chat_reset":
            chat_reset(client, channel, thread, user, meeting_id, who=who_asks(user, person, clicker))
    except link.NotLinked as exc:
        link.offer(client, team, clicker, channel, thread=thread, state=exc.state)
    except transcribe.Problem as exc:
        post(client, channel, thread, render.escape(str(exc)))
    except MeetingProblem as exc:
        post(client, channel, thread, render.escape(f"Bajarib bo'lmadi: {exc.detail}"))
    except Exception:  # noqa: BLE001
        log.exception("Slack tugmasi (%s): kutilmagan xato", kind)
        post(client, channel, thread, "Bajarib bo'lmadi: ichki xato.")


def _minutes_spot(message: dict[str, Any]) -> str | None:
    """Bayonnoma tugmalari (menyu, til) natijasi qayerga: tugmali xabar thread ICHIDA - o'sha thread'ga; chatning
    o'zidagi xabar - chatning o'ziga. Thread'i bor xabarga Slack `thread_ts` ni uning o'z `ts` i bilan beradi - shuning
    uchun bu holat ham chatning o'zi: aks holda menyu thread'idagi ko'rsatmalardan keyin natija o'sha thread'ga
    tushardi va undagi "o'zgartir" ham ko'rsatma bo'lib qolardi (menyu thread'i - faqat ko'rsatma)."""
    thread = message.get("thread_ts")
    return None if thread and thread == message.get("ts") else thread


def start(client: Any, channel: str, thread: str | None, file_id: str, lang: str, *, ref: str | None,
          sleep: Sleep = time.sleep, team: str | None = None, slack_user: str | None = None) -> None:
    """Til tanlandi (`render.lang_question` tugmasi): til savoli xabari (`ref`) joyida jarayon xabariga aylanadi va
    audio o'sha tilda o'giriladi (`handle`). Fayl Slack'dan qayta so'raladi (`files.info`) - server restartidan keyin
    bosilgan tugma ham ishlaydi. Tugma ikki marta (yoki ikkinchi til) bosilsa - ish bitta (`_started`)."""
    if lang not in render.LANG_NAMES or not _FILE.fullmatch(file_id):
        return
    with _started_lock:
        if file_id in _started:
            return
        _started.add(file_id)
    try:
        file = client.files_info(file=file_id)["file"]
        progress = status(client, channel, thread, file, language=lang, ref=ref)
        handle(client, channel, thread, [file], sleep=sleep, shown={file_id: progress}, language=lang,
               team=team, slack_user=slack_user)
    finally:
        with _started_lock:
            _started.discard(file_id)


def chat_reset(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, *,
               who: str | None) -> None:
    """«🔄 Yangi suhbat»: shu yozuv bo'yicha BOSGAN odamning (`who` - `asker`) faol savol-javoblari arxivga
    (`service.chat_reset`) - keyingi savoli modelga xotirasiz boradi, boshqalarning suhbatiga tegilmaydi. Tasdiq
    xabari - tugma turgan joyga (bosilgan xabarning `thread_ts` i; chatning o'zidagi javobda - chatga)."""
    service.chat_reset(user, meeting_id, asker=who)
    post(client, channel, thread, render.CHAT_RESET_DONE)


def tasks(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str) -> None:
    view = service.detail(user, meeting_id)
    items = service.action_items(user, meeting_id)["items"]
    body = render.tasks(items, render.speakers(view["speakers"]), view["language"])
    post(client, channel, thread, "*Vazifalar*\n" + (body or "Bu yozuvda vazifalar topilmadi."))


def transcript_file(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, *,
                    card: str | None, clicker: str | None) -> None:
    """«📥 Yuklab olish -> Transkript (TXT)» (va eski kartalardagi tugma): .txt (spikerlar va vaqt belgilari bilan - eksport bilan bir xil)
    kartaning THREAD'iga - Slack .txt matnini ochib ko'rsatadi, asosiy chatga tushsa yana o'sha uzun matn
    bo'lardi. Karta o'zi thread ichida bo'lsa - o'sha thread'ga (Slack'da ichma-ich thread yo'q).
    Bosgan odamga (faqat unga ko'rinadi) fayl qayerdaligi aytiladi."""
    text, _, name = service.export_transcript(user, meeting_id, "txt", with_speakers=True, with_timestamps=True)
    target = thread or card
    upload(client, channel, target, text.encode("utf-8"), name)
    if thread is None and card and clicker:
        try:
            client.chat_postEphemeral(channel=channel, user=clicker, text=render.TRANSCRIPT_SENT)
        except Exception as exc:  # noqa: BLE001 - fayl baribir yetib bordi
            log.warning("Slack ephemeral xabari yuborilmadi (%s): %s", channel, exc)


def export_file(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str,
                kind: str) -> None:
    """Fayl («📥 Yuklab olish» - `render.DOWNLOADS`, «Eksport» - `render.EXPORTS`) shu chatga. Slack'ka fayl yuborish
    `files:write` ruxsatini talab qiladi."""
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
    o'zbek -> kirill), lekin tanlov odamniki (ega qarori: lotin/kirill/rus/ingliz). Menyu xabarining thread'i -
    yozishdan oldingi ko'rsatmalar uchun (`render.MINUTES_PROMPT`, `question`)."""
    view = service.detail(user, meeting_id)
    post(client, channel, thread, render.MINUTES_PROMPT,
         render.minutes_menu(meeting_id, minutes.default_lang(view.get("language"))))


def minutes_formats(client: Any, channel: str, thread: str | None, meeting_id: str, lang: str) -> None:
    """Til tanlandi (til menyusi tugmasi) -> format savoli (`render.minutes_formats`: «📄 Word» / «📕 PDF»). Hujjat
    hali yozilmaydi: format tanlangach (`minutes_doc`) faqat o'sha fayl chiziladi va yuboriladi."""
    code = minutes.normalize(lang)
    if code is None:
        return
    post(client, channel, thread, render.MINUTES_FORMAT_PROMPT.format(title=minutes.LANG_TITLES[code]),
         render.minutes_formats(meeting_id, code))


def minutes_doc(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str,
                lang: str, *, fmt: str = "docx", who: str | None, holder: str | None = None,
                sleep: Sleep = time.sleep) -> None:
    """Tanlangan til va formatda bayonnoma (format tugmasi): "⏳" xabari (`holder` - format savoli xabari, o'sha joyda;
    yo'q bo'lsa - yangi xabar), `minutes.generate` (so'rovchi `who` - bosgan odamning ko'rsatmalari qo'llanadi; yangi
    ko'rsatma yo'q - tayyori qaytadi, bepul; tayyoridan keyingi ko'rsatmalar - uning tahriri; ish shu ipda 1-3 daqiqa
    yoki boshqa yo'lning yozilayotgan ishi kutiladi - `sleep`), so'ng FAQAT `fmt` fayli va "⏳" o'rniga natija
    (`_deliver_minutes`). Kutish tugab ham hujjat hali yozilayotgan bo'lsa - `render.MINUTES_STILL_RUNNING`."""
    code = minutes.normalize(lang)
    if code is None or fmt not in render.MINUTES_FORMATS:
        return
    title = minutes.LANG_TITLES[code]
    working = render.MINUTES_WORKING.format(title=title, verb="tayyorlanmoqda")
    if holder:
        replace(client, channel, holder, thread, working)
        ts: str | None = holder
    else:
        ts = post(client, channel, thread, working)
    try:
        view = minutes.generate(user, meeting_id, code, asker=who, sleep=sleep)
    except MeetingProblem as exc:
        _minutes_notice(client, channel, ts, thread, render.escape(f"Bayonnoma yozilmadi: {exc.detail}"),
                        meeting_id, code, fmt)
        return
    except transcribe.Problem as exc:
        # Kutish paytida server to'xtayapti (`__init__._sleep`) - sabab "⏳" o'rnida.
        replace(client, channel, ts, thread, render.escape(str(exc)))
        return
    except Exception:  # noqa: BLE001 - "⏳" abadiy qolmasin
        log.exception("Slack bayonnomasi (%s): kutilmagan xato", meeting_id)
        _minutes_notice(client, channel, ts, thread, "Bayonnoma yozilmadi: ichki xato.", meeting_id, code, fmt)
        return
    if view["status"] == "running":
        _minutes_notice(client, channel, ts, thread, render.MINUTES_STILL_RUNNING, meeting_id, code, fmt)
        return
    _deliver_minutes(client, channel, thread, user, meeting_id, view, code, ts, fmt)


def _deliver_minutes(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str,
                     view: dict[str, Any], code: str, ts: str | None, fmt: str = "docx") -> None:
    """Tayyor hujjat: odam tanlagan formatdagi BITTA fayl (`fmt`: Word yoki PDF) shu joyga, so'ng "⏳" xabari (`ts`;
    yo'q bo'lsa - yangi xabar) o'rnida natija (`render.minutes_result`) va tahrir eslatmasi (`render.minutes_hint`,
    `doc:<til>:<format>` belgisi: shu xabar yoki fayl thread'idagi keyingi matn shu hujjat bo'yicha, tahrir fayli ham
    shu formatda). Format tugmasi (`minutes_doc`) va chatdan boshlangan ish (`_follow_minutes`) uchun umumiy.

    NEGA BITTA FAYL (ega qarori 2026-11-13). Ilgari Word ham, PDF ham chizilib yuborilardi - odamga odatda bittasi
    kerak, PDF chizish esa og'ir (render navbati). Fayl chizilmasa yoki yuborilmasa natija baribir yetib boradi, sabab
    natija ostida; hujjatning o'zi omborda - format qayta tanlansa model chaqirilmaydi (`minutes.generate` tayyorini
    qaytaradi)."""
    fmt = fmt if fmt in render.MINUTES_FORMATS else "docx"
    notes: list[str] = []
    try:
        data, _, disposition = minutes.export_file(user, meeting_id, view["id"], fmt)
        upload(client, channel, thread, data, filename(disposition) or f"bayonnoma.{fmt}")
    except transcribe.Problem as exc:
        # `files:write` yo'q - yo'riqnoma natija ostida.
        notes.append(render.escape(str(exc)))
    except MeetingProblem as exc:
        notes.append(render.escape(f"{render.FORMAT_NAMES[fmt]} fayli tayyorlanmadi: {exc.detail}"))
    except Exception:  # noqa: BLE001
        log.exception("Slack bayonnomasi (%s): %s fayli", meeting_id, fmt)
        notes.append(f"{render.FORMAT_NAMES[fmt]} fayli tayyorlanmadi: ichki xato.")
    text = render.minutes_result(view, code, fmt)
    if notes:
        text += "\n" + "\n".join(f"⚠ {note}" for note in notes)
    replace(client, channel, ts, thread, text, render.sections(text) + [render.minutes_hint(meeting_id, code, fmt)])


def _follow_minutes(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str,
                    ref: dict[str, Any], *, who: str | None, fmt: str | None = None,
                    sleep: Sleep = time.sleep) -> None:
    """Chat navbati boshlagan bayonnoma ishi (`ChatTurn.minutes`: `create` yoki `revise`, hujjat id'si bilan) - javob
    ostida, o'sha joyda: "⏳ Bayonnoma (til) tahrirlanmoqda / tayyorlanmoqda" (ish tugagan bo'lsa ham - natija shu
    xabar o'rnida, fayllardan yuqorida turadi, til tugmasidagidek), ish kutiladi (`minutes.wait`, `sleep`), so'ng:
    tayyor - odam tanlagan formatdagi fayl (`fmt` - natija belgisidan; noma'lum - Word) va natija
    (`_deliver_minutes`); yiqilgan - sababi (`minutes.failure_detail`; tahrirda "o'zgarish bo'lmadi" ham); kutish tugab
    ham yozilmoqda - `render.MINUTES_STILL_RUNNING`."""
    ts = None
    code = str(ref.get("language") or "")
    fmt = fmt if fmt in render.MINUTES_FORMATS else "docx"
    try:
        found = minutes.status(user, meeting_id, ref["id"], asker=who)
        code = found["language"]
        revising = found.get("kind") == "revise"
        ts = post(client, channel, thread, render.MINUTES_WORKING.format(
            title=minutes.LANG_TITLES.get(code, code), verb="tahrirlanmoqda" if revising else "tayyorlanmoqda"))
        if found["status"] == "running":
            found = minutes.wait(user, meeting_id, ref["id"], asker=who, sleep=sleep)
        if found["status"] == "running":
            _minutes_notice(client, channel, ts, thread, render.MINUTES_STILL_RUNNING, meeting_id, code, fmt)
        elif found["status"] == "failed":
            head = "Bayonnoma tahrirlanmadi" if revising else "Bayonnoma yozilmadi"
            _minutes_notice(client, channel, ts, thread, render.escape(f"{head}: {minutes.failure_detail(found)}"),
                            meeting_id, code, fmt)
        else:
            _deliver_minutes(client, channel, thread, user, meeting_id, found, code, ts, fmt)
    except transcribe.Problem as exc:
        # Kutish paytida server to'xtayapti (`__init__._sleep`).
        replace(client, channel, ts, thread, render.escape(str(exc)))
    except MeetingProblem as exc:
        _minutes_notice(client, channel, ts, thread, render.escape(f"Bayonnoma yuborilmadi: {exc.detail}"),
                        meeting_id, code, fmt)
    except Exception:  # noqa: BLE001 - "⏳" abadiy qolmasin
        log.exception("Slack bayonnomasi (%s): chatdan boshlangan ish kuzatilmadi", meeting_id)
        _minutes_notice(client, channel, ts, thread, "Bayonnoma yuborilmadi: ichki xato.", meeting_id, code, fmt)


def _minutes_notice(client: Any, channel: str, ts: str | None, thread: str | None, text: str, meeting_id: str,
                    code: str, fmt: str | None = None) -> None:
    """Bayonnoma xato / "hali tayyorlanmoqda" xabari "⏳" o'rnida - yig'ilish belgisi (`doc:<til>[:<format>]`) bilan:
    shu xabar thread'idagi javob ("qayta urin", "3-bandni ...") shu yozuv va shu hujjatga boradi, fayli o'sha
    formatda. Belgisiz xabarning thread'i "jim" edi (`thread_target`)."""
    blocks = render.sections(text)
    if blocks and minutes.normalize(code):
        blocks[0] = {**blocks[0], "block_id": render.mark(meeting_id, render.doc_tag(code, fmt))}
    replace(client, channel, ts, thread, text, blocks or None)


def relang(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, lang: str, *,
           sleep: Sleep = time.sleep) -> None:
    """Boshqa tilda qayta o'girish - faqat ESKI kartalardagi tugma (2026-11-12 dan til audio yuklanganda so'raladi;
    GAPI qayta to'lanadi - tugmada tasdiq oynasi bor), so'ng yangi "Qisqa xulosa" kartasi."""
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
          sleep: Sleep = time.sleep, team: str | None = None, slack_user: str | None = None) -> None:
    """"Qayta urinish": `f:<fayl>:<til>` - audio butun yo'ldan, o'sha tilda (yig'ilish kaliti fayldan, ya'ni
    tayyor qismi takrorlanmaydi; tilsiz eski tugma - o'zbek), `m:<yig'ilish>` - xulosa."""
    kind, _, ident = value.partition(":")
    if kind == "f" and ident:
        file_id, _, lang = ident.partition(":")
        handle(client, channel, thread, [client.files_info(file=file_id)["file"]], sleep=sleep,
               language=lang if lang in render.LANG_NAMES else intake.LANGUAGE, team=team, slack_user=slack_user)
    elif kind == "m" and _ID.fullmatch(ident):
        user = transcribe.owner(user, ident)
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


def replace(client: Any, channel: str, ts: str | None, thread: str | None, text: str,
            blocks: list[dict[str, Any]] | None = None) -> None:
    """"⏳ ..." xabarini natija bilan almashtiradi; sig'masa qolgani - yangi xabarlarda. `blocks` (bo'lmasa -
    matn section'lari) `post` dagidek `render.MESSAGE_BLOCKS` tadan bo'linadi: oxiridagi tugma oxirgi xabarda."""
    pages = _pages(text, blocks)
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

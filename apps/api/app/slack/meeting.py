"""Slack'dagi Barno AI: audio -> transkript -> "Qisqa xulosa" va tugmalar; yozuv chati (chatda va thread'da).

XABARLAR - chatning o'zida (audio thread ichida yuborilgan bo'lsa - o'sha thread'da):
  0. jarayon xabari (`intake.Progress`, ega talabi 2026-11-05): audio kelishi bilan DARHOL
     (`acknowledge`, navbatdan oldin) - "qabul qilindi" va bosqichlar: audio yuklash, matnga
     o'girish (foizi bilan), qisqa xulosa. Joyida yangilanadi, xulosa (yoki xato) chiqqach o'chiriladi;
  1. "Qisqa xulosa" - mobil kartadagi bilan AYNI matn (`export_meeting(parts="brief")`,
     mobil `brief.ts` bilan umumiy namunada tekshiriladi) va tugmalar: transkriptni yuklab olish,
     vazifalar, bayonnoma (rasmiy hujjat), boshqa shablon bilan xulosa, eksport (fayl), boshqa
     tilda qayta o'girish.
  2. "📄 Bayonnoma" - til menyusi (lotin/kirill/rus/ingliz), tanlovdan keyin Word va PDF fayl
     (`services.meetings.minutes`): hujjat 1-3 daqiqada yoziladi, odam "⏳" xabarini ko'radi.
TRANSKRIPT CHATGA YOZILMAYDI (ega talabi 2026-11-11): uzun matn chatni tushunarsiz qilardi. U
"📥 Transkriptni yuklab olish" tugmasida - .txt fayl kartaning THREAD'iga keladi (asosiy chat toza
qoladi), Slack'da shu yerdan yuklab olinadi. Istisno - xulosa yozilmagan juda qisqa yozuv: bir-ikki
gapni faylga solish o'rniga kartaning o'zida (`SHORT_TRANSCRIPT_CHARS`).
Karta bloki `block_id` da yig'ilish id'sini olib yuradi (`render.mark`): xabar ostidagi
thread'dagi savol yig'ilishni shundan topadi - lokal ombor kerak emas. Odamning o'z audio
xabari ostidagi savol - fayl kaliti orqali (`transcribe.meeting_of_file`).

YOZUV CHATI (ega talabi 2026-11-11): `service.chat_send`, kanal `slack`. Barno shu yozuvning transkripti,
xulosasi va shu suhbatdagi oldingi savol-javoblar bilan javob beradi ("batafsilroq", "u kim edi?" kabi davom
savollari ishlaydi), boshqa yozuvlar aralashmaydi. Javob ostidagi «🔄 Yangi suhbat» xotirani tozalaydi
(`service.chat_reset`, yumshoq - savol-javoblar bazada qoladi). Savol qayerda yoziladi:
  * chatning o'zida (thread'dan tashqarida; ega tasdig'i 2026-11-11, "variant A") - chatdagi OXIRGI yozuv
    bo'yicha (`on_text`, `latest`): javob ham chatning o'zida, boshida «📼 «nom» bo'yicha:», ostidagi tugma
    yig'ilish belgisini olib yuradi - keyingi savol ham shu yozuvga. Yangi audio yuborilsa savollar unga o'tadi
    (u o'girilguncha - `render.CHAT_PENDING`; o'girib bo'lmasa yoki o'chirilsa - yana oldingi yozuvga, xato
    xabari audioni `render.fail_mark` bilan belgilaydi); chatda yaroqli yozuv bo'lmasa - «🎙 Plaud» yo'riqnomasi
    (`home.on_text`), chat tarixini o'qib bo'lmasa - `render.CHAT_UNREAD`;
  * yozuv xabarining (karta, javob, odamning audio xabari) thread'ida - HAR QANDAY, eski yozuv bo'yicha ham
    (`question`).
SUHBAT YOZUVNIKI VA ODAMNIKI (thread'niki emas): Slack'dagi hamma odam bitta hisobda (`transcribe.account`),
shuning uchun xotira va «🔄 Yangi suhbat» so'rovchi bo'yicha (`asker`, `slack:<user id>`): bitta faylni ikki
kishi o'z chatiga yuborsa (bitta yig'ilish) har biri o'z suhbatini ko'radi, hisob egasining ilovadagi suhbati
ham alohida. Bir odamning shu yozuv haqidagi savollari (chatda ham, istalgan thread'da ham) - bitta suhbat.

NEGA AVTOMATIK XULOSA. Yig'ilish quvuri uni har yozuv uchun baribir yozadi (`summarizing`):
ko'rsatish qo'shimcha LLM chaqiruvi emas.

CHEGARALAR hisob bo'yicha, ya'ni hamma Slack xodimlariga UMUMIY: chat savoli soatiga
`MEETINGS_ASK_PER_HOUR`, boshqa shablon `MEETINGS_SUMMARY_PER_HOUR`, eksport (qisqa xulosa
ham) `MEETINGS_EXPORT_PER_HOUR`, bayonnoma `MEETINGS_MINUTES_PER_HOUR` (har hujjat pullik
Claude chaqiruvi). Oshsa xizmatning o'z xabari ko'rsatiladi.
"""

from __future__ import annotations

import logging
import re
import time

from typing import Any, NamedTuple

from ..schemas import meetings as schemas
from ..schemas.auth import AuthUser
from ..services import archive
from ..services.meetings import intake, minutes, service, templates
from ..services.meetings.errors import MeetingProblem
from ..services.meetings.intake import (  # noqa: F401 - umumiy qadamlar (`intake.py`)
    SUMMARY_WAIT_SEC, Sleep, filename, summary_error, wait_summary, wait_summary_card)
from . import home, render, transcribe

log = logging.getLogger(__name__)
#: Chat xabari chegarasi (`ChatRequest.message`, `prompts.CHAT_QUESTION_CHARS`).
QUESTION_CHARS = 1000
#: Thread'dan tashqaridagi savol: oxirgi yozuv chatning shuncha eng yangi xabari ichidan qidiriladi (`latest`).
HISTORY = 50
#: `latest`: chat tarixini o'qib bo'lmadi (Slack xatosi yoki `ok: false`) - `render.CHAT_UNREAD`, yo'riqnoma emas.
UNREAD = "unread"
#: `latest`: chatdagi oxirgi audio hali matnga o'girilmoqda - `render.CHAT_PENDING`.
PENDING = "pending"
#: Yig'ilishi hali yo'q (yoki yuklanishi yarim qolgan) audio shuncha vaqtgacha "yo'lda" (Slack'dan yuklab olinmoqda);
#: undan eskisi - o'girib bo'lmagan (xato xabari o'chirilgan yoki server restartida yozilmay qolgan): "⏳ ...
#: tayyorlanmoqda" abadiy osilib qolmasin - savol oldingi yozuvga (`latest`).
AUDIO_PENDING_SEC = 15 * 60
#: Xulosa yozilmagan (juda qisqa) yozuvning matni shundan qisqa bo'lsa - kartaning o'zida ko'rsatiladi.
SHORT_TRANSCRIPT_CHARS = 300
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
               bot_user: str | None = None, shown: dict[str, intake.Progress] | None = None) -> None:
    files = transcribe.audio_files(event)
    if files:
        handle(client, event["channel"], event.get("thread_ts"), files, sleep=sleep, shown=shown)
    elif is_question(event):
        question(client, event, bot_user=bot_user)


def acknowledge(client: Any, event: dict[str, Any]) -> dict[str, intake.Progress]:
    """Audio kelishi bilan har fayl uchun jarayon xabari - DARHOL, Bolt ipida (navbatdan oldin):
    navbat band bo'lsa ham odam audiosi qabul qilinganini ko'radi. Bir xabardagi fayllar ketma-ket
    o'giriladi - ikkinchisidan boshlab "navbatda". Qaytaradi: fayl id -> xabar (`handle` uchun)."""
    shown: dict[str, intake.Progress] = {}
    for n, file in enumerate(transcribe.audio_files(event)):
        progress = status(client, event["channel"], event.get("thread_ts"), file)
        progress.show(intake.UPLOAD if n == 0 else intake.QUEUED)
        shown[file["id"]] = progress
    return shown


def status(client: Any, channel: str, thread: str | None, file: dict[str, Any]) -> intake.Progress:
    """Shu audioning jarayon xabari: Slack'da yozilgan ovozli xabar yoki yuklangan fayl (nomi bilan)."""
    if file.get("subtype") == "slack_audio":
        head = "🎙 Ovozli xabaringiz qabul qilindi."
    else:
        name = " ".join(str(file.get("name") or file.get("title") or "audio").split())[:80]
        head = f"📎 «{render.escape(name)}» qabul qilindi."

    def show(ts: str | None, text: str) -> str | None:
        if ts is None:
            return post(client, channel, thread, text)
        client.chat_update(channel=channel, ts=ts, text=text, blocks=render.sections(text))
        return ts

    return intake.Progress(head, show=show, drop=lambda ts: client.chat_delete(channel=channel, ts=ts),
                           transcript_above=False)


def is_question(event: dict[str, Any]) -> bool:
    """Shaxsiy chatdagi thread javobi - odam yozgan matn. Thread'siz matn - `on_text` (dispetcherda `home.is_text`)."""
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
        return False
    thread = event.get("thread_ts")
    return bool(thread and thread != event.get("ts") and str(event.get("text") or "").strip())


# --- audio ----------------------------------------------------------------------------------


def handle(client: Any, channel: str, thread: str | None, files: list[dict[str, Any]], *,
           sleep: Sleep = time.sleep, shown: dict[str, intake.Progress] | None = None) -> None:
    """Navbatdagi vazifa: har audio uchun jarayon xabari (`acknowledge` chiqargani yoki yangisi),
    transkript va xulosa, xato bo'lsa sabab (va foyda beradigan bo'lsa "Qayta urinish")."""
    for file in files:
        progress = (shown or {}).get(file.get("id")) or status(client, channel, thread, file)
        progress.show(intake.UPLOAD)
        retry = f"f:{file['id']}"
        try:
            user = transcribe.account()
            meeting_id = transcribe.ingest(client, user, file)
            text = transcribe.wait_transcript(user, meeting_id, sleep=sleep, progress=progress.view)
        except transcribe.Problem as exc:
            fail(client, channel, thread, str(exc), retry if exc.retry else None, file_id=file["id"],
                 progress=progress)
            continue
        except MeetingProblem as exc:
            fail(client, channel, thread, str(exc.detail), None if exc.status_code in _FINAL else retry,
                 file_id=file["id"], progress=progress)
            continue
        except Exception:  # noqa: BLE001 - odam javobsiz qolmasin
            log.exception("Slack audio (%s): kutilmagan xato", file.get("id"))
            fail(client, channel, thread, "ichki xato.", retry, file_id=file["id"], progress=progress)
            continue
        deliver(client, channel, thread, user, meeting_id, text, sleep=sleep, progress=progress)


def deliver(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, text: str, *,
            sleep: Sleep = time.sleep, progress: intake.Progress | None = None) -> None:
    """Matnga o'girildi: (yozilishini kutib) "Qisqa xulosa" va tugmalar. Transkript chatga YOZILMAYDI -
    kartadagi "📥 Transkriptni yuklab olish" da (modul izohi). `progress` (audio yo'li) - jarayon xabari
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
        text = "Xulosa hali tayyor emas - birozdan keyin «Boshqa shablon bilan xulosa» dan oling."
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "Qisqa xulosa"}}]
    blocks += render.sections(text)[:render.MESSAGE_BLOCKS - 4]
    if retry:
        blocks.append(render.retry_button(retry))
    return blocks + render.controls(meeting_id, view["language"], templates.catalog("uz"))


def brief(user: AuthUser, meeting_id: str, *, summary_id: str | None = None, parts: str = "brief") -> str:
    return render.mrkdwn(intake.brief_markdown(user, meeting_id, summary_id=summary_id, parts=parts))


def fail(client: Any, channel: str, thread: str | None, reason: str, retry: str | None = None, *,
         file_id: str | None = None, progress: intake.Progress | None = None) -> None:
    """Sabab - YANGI xabarda (odamga bildirishnoma boradi), jarayon xabari o'chiriladi. `file_id` - xabar qaysi
    audio haqida (`render.fail_mark`): chatdagi savol (`latest`) o'sha audioni "tayyorlanmoqda" deb kutib qolmaydi."""
    if progress is not None:
        progress.close()
    text = render.escape(f"Matnga o'girib bo'lmadi: {reason}")
    blocks = render.sections(text)
    if file_id and blocks:
        blocks[0]["block_id"] = render.fail_mark(file_id)
    if retry:
        blocks.append(render.retry_button(retry))
    post(client, channel, thread, text, blocks)


# --- yozuv chati: thread'dagi va chatdagi savol ----------------------------------------------------


def asker(slack_user: Any) -> str:
    """Yozuv chatidagi so'rovchi (`service.chat_send` / `chat_reset` ning `asker` i): Slack'dagi hamma odam BITTA
    hisobda, shuning uchun suhbat xotirasi va «🔄 Yangi suhbat» har odamga alohida - `slack:<user id>`. Kalit hech
    qachon bo'sh emas: bo'sh (`None`) - hisob egasining ilovadagi suhbati bo'lardi."""
    return f"slack:{slack_user or ''}"


def question(client: Any, event: dict[str, Any], *, bot_user: str | None = None) -> None:
    """Thread'dagi savol -> o'sha thread boshidagi xabarning yozuvi (`meeting_of_thread`) bo'yicha chat (`chat`):
    eski yozuv haqida ham shunday so'raladi. Yozuvga bog'liq bo'lmagan thread - jim."""
    channel, thread = event["channel"], event["thread_ts"]
    try:
        user = transcribe.account()
    except transcribe.Problem as exc:
        post(client, channel, thread, render.escape(f"Javob berib bo'lmadi: {exc}"))
        return
    meeting_id = meeting_of_thread(client, channel, thread, user, bot_user=bot_user)
    if meeting_id is None:
        return
    chat(client, channel, thread, user, meeting_id, _text(event), who=asker(event.get("user")))


def on_text(client: Any, event: dict[str, Any], *, bot_user: str | None = None) -> None:
    """Thread'dan tashqaridagi matn (dispetcher: `home.is_text`) -> chatdagi OXIRGI yozuv (`latest`) bo'yicha chat,
    javob ham chatning o'zida, boshida qaysi yozuv (`render.chat_title`). Oxirgi audio hali matnga o'girilmoqda -
    `render.CHAT_PENDING`; chatda yaroqli yozuv yo'q - avvalgidek «🎙 Plaud» yo'riqnomasi (`home.on_text`, chatga
    `TEXT_EVERY` da bir marta, hisob ham kerak emas); chat tarixini o'qib bo'lmadi - `render.CHAT_UNREAD`, har
    savolga (yo'riqnoma emas: yozuv bordir, faqat Slack javob bermadi)."""
    channel = event.get("channel")
    if not channel:
        return
    try:
        found = latest(client, channel, event.get("user"), bot_user=bot_user)
    except transcribe.Problem as exc:
        post(client, channel, None, render.escape(f"Javob berib bo'lmadi: {exc}"))
        return
    except MeetingProblem as exc:
        post(client, channel, None, render.escape(f"Javob berib bo'lmadi: {exc.detail}"))
        return
    except Exception:  # noqa: BLE001 - navbatdagi vazifa: xato hech qayerda ko'rinmas, odam javobsiz qolardi
        log.exception("Slack chatdagi savoli (%s): kutilmagan xato", channel)
        post(client, channel, None, "Javob berib bo'lmadi: ichki xato.")
        return
    if found is None:
        home.on_text(client, event)
    elif found == UNREAD:
        post(client, channel, None, render.CHAT_UNREAD)
    elif found == PENDING:
        post(client, channel, None, render.CHAT_PENDING)
    else:
        chat(client, channel, None, found.user, found.meeting_id, _text(event), who=asker(event.get("user")),
             view=found.view, titled=True)


class Recording(NamedTuple):
    """`latest` topgan yozuv (matni tayyor): Slack hisobi, yig'ilish va uning ko'rinishi (`service.detail`)."""

    user: AuthUser
    meeting_id: str
    view: dict[str, Any]


def latest(client: Any, channel: str, person: str | None, *,
           bot_user: str | None = None) -> Recording | str | None:
    """Chatdagi OXIRGI yozuv. Chat tarixining `HISTORY` ta eng yangi xabari yangisidan boshlab ko'riladi, nomzodlar:
      * Barno'ning xulosa kartasi yoki chat javobi (`render.LATEST_TAGS`; belgiga faqat O'ZIMIZ yozganida ishonamiz,
        `meeting_of_thread` dagidek). Bayonnoma menyusi kabi tugma natijasi nomzod emas - eski kartada bosilgan
        tugma savollarni eski yozuvga burib yubormasin;
      * odamning (`person`) o'zi yuborgan audio - yig'ilishi fayl kalitidan; bir xabarda bir nechta bo'lsa
        oxirgisidan boshlab (ular ketma-ket o'giriladi).
    Nomzodning yig'ilishi: matni tayyor - `Recording`; hali o'girilmoqda (qayta o'girish ham) - `PENDING`; o'girib
    bo'lmagan yoki o'chirilgan - o'tkaziladi, oldingi yozuv qidiriladi. Yig'ilishi hali yo'q (yoki yuklanishi yarim
    qolgan) audio - faqat chindan yo'lda bo'lsa `PENDING`: tarixda undan yangiroq o'z xato xabari bo'lsa
    (`render.fail_mark`) yoki `AUDIO_PENDING_SEC` dan eski bo'lsa - o'girib bo'lmagan, o'tkaziladi.
    Yaroqli yozuv yo'q - `None` (yo'riqnoma), tarixni o'qib bo'lmadi - `UNREAD`. Slack hisobi birinchi nomzodda
    olinadi (chatda yozuv bo'lmasa kerak ham emas): `transcribe.Problem` - chaqiruvchiga."""
    messages = _history(client, channel)
    if messages is None:
        return UNREAD
    now, failed, lookup = time.time(), set(), _Lookup()
    for message in messages:
        if message.get("bot_id"):
            if bot_user and message.get("user") != bot_user:
                continue                                    # begona bot - belgisiga ishonilmaydi
            failure = render.fail_marked(message)
            if failure:
                failed.add(failure)
                continue
            meeting_id = render.marked(message, tags=render.LATEST_TAGS)
            found = lookup.verdict(meeting_id, lookup.view(meeting_id)) if meeting_id else None
            if found is not None:
                return found
        elif person and message.get("user") == person:
            fresh = now - _sent_at(message) < AUDIO_PENDING_SEC
            for file in reversed([f for f in message.get("files") or [] if transcribe.is_audio(f) and f.get("id")]):
                file_id = str(file["id"])
                meeting_id = transcribe.meeting_of_file(lookup.user, file_id)
                view = lookup.view(meeting_id)
                if view is None or view["status"] == "uploading":
                    # Yig'ilish hali yo'q (Slack'dan yuklanmoqda) yoki yuklash yarim qolgan. Yo'ldami yoki o'girib
                    # bo'lmaganmi - yig'ilishdan bilinmaydi (limit tugasa u o'chiriladi, format yaroqsiz bo'lsa
                    # yaratilmaydi, server restartida yuklash to'xtaydi): xato belgisi va audio yoshidan.
                    if fresh and file_id not in failed:
                        return PENDING
                    continue
                found = lookup.verdict(meeting_id, view)
                if found is not None:
                    return found
    return None


def _history(client: Any, channel: str) -> list[dict[str, Any]] | None:
    """Chatning `HISTORY` ta eng yangi xabari (yangisi birinchi); o'qib bo'lmasa (Slack xatosi, `ok: false`) -
    `None`."""
    try:
        found = client.conversations_history(channel=channel, limit=HISTORY)
    except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
        log.warning("Slack chat tarixi o'qilmadi (%s): %s", channel, exc)
        return None
    if not found.get("ok", True):
        log.warning("Slack chat tarixi o'qilmadi (%s): %s", channel, found.get("error"))
        return None
    return list(found.get("messages") or [])


def _sent_at(message: dict[str, Any]) -> float:
    """Slack xabarining vaqti (`ts` - epoch soniya); noma'lum bo'lsa 0, ya'ni "eski"."""
    try:
        return float(message.get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


class _Lookup:
    """`latest` nomzodlarining yig'ilishi. Slack hisobi birinchi kerak bo'lganda olinadi: chatda yozuv bo'lmasa
    hisob ham kerak emas (yo'riqnoma hisobsiz chiqadi)."""

    def __init__(self) -> None:
        self._user: AuthUser | None = None

    @property
    def user(self) -> AuthUser:
        if self._user is None:
            self._user = transcribe.account()
        return self._user

    def view(self, meeting_id: str | None) -> dict[str, Any] | None:
        """Yig'ilish ko'rinishi; yo'q yoki o'chirilgan (404) - `None`."""
        if not meeting_id:
            return None
        try:
            return service.detail(self.user, meeting_id)
        except MeetingProblem as exc:
            if exc.status_code == 404:
                return None
            raise

    def verdict(self, meeting_id: str, view: dict[str, Any] | None) -> Recording | str | None:
        """Matni tayyor - `Recording`; hali o'girilmoqda - `PENDING`; o'girib bo'lmagan yoki o'chirilgan - `None`
        (oldingi yozuv qidiriladi)."""
        if view is None or view["status"] == "failed":
            return None
        if view["transcript"]["available"]:
            return Recording(self.user, meeting_id, view)
        return PENDING


def chat(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, text: str, *,
         who: str, view: dict[str, Any] | None = None, titled: bool = False) -> None:
    """Yozuv chatiga savol (`service.chat_send`, kanal `slack`, so'rovchi `who` - `asker`): "⏳" xabari, so'ng uning
    o'rnida javob (manbalar bilan; `titled` - birinchi qatorda qaysi yozuv) va «🔄 Yangi suhbat»
    (`render.chat_actions`). Xatoda (chegara, model, yozuv topilmadi) - faqat sabab, tugmasiz."""
    ts = post(client, channel, thread, "⏳ Javob tayyorlanmoqda…")
    blocks = None
    try:
        view = view or service.detail(user, meeting_id)
        found = service.chat_send(user, meeting_id, text, None, channel="slack", asker=who)
        body = render.answer(found, render.speakers(view["speakers"]), view["language"])
        if titled:
            body = f"{render.chat_title(view['title'])}\n{body}"
        blocks = render.sections(body) + [render.chat_actions(meeting_id)]
    except MeetingProblem as exc:
        body = render.escape(f"Javob berib bo'lmadi: {exc.detail}")
    except Exception:  # noqa: BLE001
        log.exception("Slack savoli (%s): kutilmagan xato", meeting_id)
        body = "Javob berib bo'lmadi: ichki xato."
    replace(client, channel, ts, thread, body, blocks)


def _text(event: dict[str, Any]) -> str:
    """Odam yozgan savol - Slack belgilarisiz (`&lt;` -> `<`), `QUESTION_CHARS` gacha."""
    return render.unescape(str(event.get("text") or "")).strip()[:QUESTION_CHARS]


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
    message = body.get("message") or {}
    thread = message.get("thread_ts")
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
        if kind == "barno_transcript" or (kind == "barno_export" and arg == "transcript_txt"):
            # Eski kartalardagi "Eksport -> Transkript (TXT)" ham shu yo'ldan.
            transcript_file(client, channel, thread, user, meeting_id, card=message.get("ts"),
                            clicker=(body.get("user") or {}).get("id"))
        elif kind == "barno_tasks":
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
        elif kind == "barno_chat_reset":
            chat_reset(client, channel, thread, user, meeting_id, who=asker((body.get("user") or {}).get("id")))
    except transcribe.Problem as exc:
        post(client, channel, thread, render.escape(str(exc)))
    except MeetingProblem as exc:
        post(client, channel, thread, render.escape(f"Bajarib bo'lmadi: {exc.detail}"))
    except Exception:  # noqa: BLE001
        log.exception("Slack tugmasi (%s): kutilmagan xato", kind)
        post(client, channel, thread, "Bajarib bo'lmadi: ichki xato.")


def chat_reset(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, *,
               who: str) -> None:
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


def transcript_file(client: Any, channel: str, thread: str | None, user: AuthUser, meeting_id: str, *,
                    card: str | None, clicker: str | None) -> None:
    """"📥 Transkriptni yuklab olish": .txt (spikerlar va vaqt belgilari bilan - eksport bilan bir xil)
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
    """Boshqa tilda qayta o'girish (GAPI qayta to'lanadi - tugmada tasdiq oynasi bor), so'ng yangi
    "Qisqa xulosa" kartasi (yangi transkript - uning "📥 Transkriptni yuklab olish" tugmasida)."""
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

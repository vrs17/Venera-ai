"""Telegram'dagi "Plaud": audio -> transkript -> "Qisqa xulosa" va tugmalar; javob (Reply) bilan savol.

Slack'dagi Barno AI (`app/slack/meeting.py`) bilan AYNI imkoniyatlar, Telegram ko'rinishida:

  * "🎙 Plaud" tugmasi (pastdagi doimiy klaviatura) yoki `/plaud` - odamga "audio yuboring"
    deyiladi va chat `ARMED_SEC` davomida QUROLLANADI: shu oraliqda kelgan ovozli xabar
    HR savoli emas, yozuv deb olinadi. Audio FAYL (mp3, m4a, aac, wav, ogg) va
    `telegram_voice_max_sec` dan uzun ovozli xabar esa har doim yozuv - ular chat savoli
    bo'la olmaydi (bot ularni oldin rad etardi). Yozuv xabariga (yoki «💬 Savol berish»
    so'roviga) JAVOB bo'lgan ovozli xabar bundan mustasno - u shu yozuv bo'yicha savol
    (`claims_reply`, pastda);
  * jarayon xabari (`intake.Progress`, ega talabi 2026-11-05) - audio kelishi bilan DARHOL
    (navbatdan oldin), odamning audio xabariga javob qilib: "qabul qilindi" va bosqichlar - audio
    yuklash, matnga o'girish (foizi bilan), qisqa xulosa. Joyida yangilanadi, transkript chiqqach
    uning ostiga ko'chadi, xulosa (yoki xato) chiqqach o'chiriladi;
  * transkript (xabarlar 4000 belgidan), keyin "📋 Qisqa xulosa" - mobil kartadagi bilan
    AYNI matn (`intake.brief_markdown`) va tugmalar: vazifalar, eksport (fayl), boshqa tilda
    qayta o'girish (tasdiq bilan - GAPI qayta sarflanadi). «🗂 Boshqa shablon» olib tashlangan (ega
    qarori 2026-11-12: hozirgi bosqichda kerak emas - xulosa avtomatik shablon bilan);
  * "📄 Bayonnoma" (ega qarori, 2026-11-04) - rasmiy hujjat loyihasi: til menyusi (lotin /
    kirill / rus / ingliz, tavsiya - yig'ilish tilidan), so'ng format menyusi - Word (asosiy) yoki PDF
    (2026-11-13), so'ng FAQAT o'sha fayl shu chatga (`services.meetings.minutes`); «________» joylari
    Word'da qo'lda to'ldiriladi;
  * yig'ilish CHATI (ega talabi, 2026-11-11) - har yozuvning O'Z suhbati: «💬 Savol berish»
    tugmasi (ForceReply so'rovi - Telegram javob maydonini o'zi ochadi) yoki xulosa (transkript,
    javob, o'z audio) xabariga JAVOB (Reply): Telegram'da thread yo'q, javob shu vazifani
    bajaradi. Javob `service.chat_send` dan (kanal `telegram`): shu yozuv matni, xulosasi va shu
    suhbatning oldingi savol-javoblari bilan - mobil ilova va Slack'dagi savollar bilan BITTA
    suhbat. Javob ostida «💬 Yana savol» va «🔄 Yangi suhbat» (`service.chat_reset` - yumshoq:
    eski navbatlar modelga ham, ro'yxatga ham bormaydi). Yig'ilish qaysi xabarga javob
    berilganidan topiladi: xotiradagi xarita (shu jarayon yuborganlari), xabar tugmalaridagi
    `p:<op>:<yig'ilish>` (qayta ishga tushgandan keyin ham) yoki odamning audio faylining
    kaliti (`intake.client_id`). Shuning uchun chat javobining HAR bo'lagida (va xato
    xabarida) tugma bor: oxirgisida «💬 Yana savol» va «🔄 Yangi suhbat», qolganlarida
    «💬 Savol berish». ForceReply so'rovida tugma bo'la olmaydi: qayta ishga tushgandan keyin
    unga yozilgan savol izoh bilan YUTILADI (HR yordamchisiga ketmaydi). Savol OVOZLI ham
    bo'ladi: yozuv xabariga yoki so'rovga ovozli javob (`claims_reply`) HR savolidagi AYNI yo'l
    bilan matnga o'giriladi (`runner._meeting_voice`) va shu yerga savol bo'lib keladi; uning
    "🎙 matn" xabari ham shu yig'ilishga bog'lanadi (`_link`: «💬 Savol berish» tugmasi va
    xotira) - unga javob, matn yoki ovoz, ham shu suhbatga savol;
  * BAYONNOMA CHATDA (ega so'rovi, 2026-11-12) - o'sha suhbatning o'zida, boshqa yozuvlarniki bilan
    aralashmaydi. Til menyusidagi «✍️ Ko'rsatma berish» (ForceReply so'rovi) - hujjat yozilishidan OLDIN
    ko'rsatma (nimaga e'tibor berish, rais va qatnashchilar, tuzilma, atamalar): javob - matn yoki ovoz -
    `intent="note"` bilan (chat modelisiz, bepul) eslab qolinadi va hujjat yozilganda hisobga olinadi. Til
    tanlangach - format: «📄 Word» yoki «📕 PDF» (ega qarori 2026-11-13: ikkala faylni chizib yuborish behuda) - FAQAT
    o'sha fayl yuboriladi. Tayyor hujjat (fayl va natija xabari) ostida «✏️ O'zgartirish» (`p:w:<id>:<til>:<format>`):
    javob `intent="revise"` bilan - Barno faqat so'ralgan joyni o'zgartirib, hujjatning YANGI versiyasini o'sha
    formatda yuboradi (`_formats`; qayta ishga tushgandan keyin - tugmadagi formatdan), qolgani saqlanadi. Hujjat
    yoki natija xabariga to'g'ridan-to'g'ri javob (Reply) ham shu suhbatga: niyatni (savol, ko'rsatma, tayyorlash,
    o'zgartirish) chat modeli aniqlaydi, hujjat tili - tugmadan (`minutes_lang`). Ish
    boshlansa - javobdan keyin "⏳", so'ng fayllar va natija (`_follow_minutes`). Tilni qayta bosish - yangi
    ko'rsatma bo'lsa joriy hujjatning tahriri, bo'lmasa tayyori bepul qayta yuboriladi (`minutes.generate`).
    Xotirada xabarning NIYATI ham (`_intents`: so'rov - "note" / "revise", hujjat va natija - "doc" va tili);
    qayta ishga tushgandan keyin hujjat va natija tugmasidagi `p:w` dan topiladi, eski ✍️ / ✏️ so'roviga
    javob esa izoh bilan yutiladi (`STALE_GUIDE` / `STALE_EDIT`).

KIMNING NOMIDAN. Telegram odami Venera hisobiga ulangan (`LinkStore`), yozuv O'SHA hisobga
tushadi: uning yig'ilishlar ro'yxatida (mobil, veb) ko'rinadi, kunlik daqiqalar va soatlik
chegaralar o'ziniki. Botga ulangan har bir xodimga ochiq (ega qarori 2026-11-04; ilovada
ham 2026-11-16 dan).

TELEGRAM CHEGARASI. Bot fayllarni 20 MB gacha yuklab ola oladi (`getFile`): ovozli xabar
soatiga ~14 MB, ya'ni bir soatlik yozuv sig'adi; kattaroq fayl uchun mobil ilova yoki Slack.
Ovozli xabar - OGG/Opus, yig'ilish quvuri uni 2026-11-04 dan qabul qiladi (`audio.ogg_info`).

VIDEO (2026-11-17, ega qarori). Video, dumaloq video va fayl sifatidagi video ham yozuv: yig'ilish
audiosini ajratib oladi, video saqlanmaydi (`service._extract_video`). Faqat MP4/MOV; boshqasi -
"MP4 yuboring". Telegram chegarasi o'sha 20 MB - kattasi uchun Slack yoki mobil ilova.

TUGMALAR (`callback_data`, 64 baytgacha; yig'ilish id'si 32 belgi):
    p:q:<id>            savol berish: ForceReply so'rovi (yig'ilish chati)
    p:n:<id>            yangi suhbat: chat navbatlari arxivga (`service.chat_reset`)
    p:t:<id>            vazifalar
    p:s:<id>[:<shablon>] (o'chirilgan) eski xabardagi «🗂 Boshqa shablon»: izoh va asosiy tugmalar
    p:e:<id>[:<tur>]    eksport: menyu / fayl (txt, srt, md, docx, pdf)
    p:l:<id>[:<til>[:y]] boshqa til: menyu / tasdiq / qayta o'girish
    p:d:<id>[:<til>[:<format>]] bayonnoma: hujjat tili menyusi / format menyusi (Word, PDF) / tanlangan til va
                        formatdagi BITTA fayl (`minutes.LANGS`, `MINUTES_FORMATS`)
    p:g:<id>            bayonnoma uchun ko'rsatma: ForceReply so'rovi (javob - `intent="note"`)
    p:w:<id>:<til>[:<format>] tayyor bayonnomani o'zgartirish: ForceReply so'rovi (javob - `intent="revise"`, shu til;
                        yangi versiya fayli - shu formatda)
    p:b:<id>            asosiy tugmalarga qaytish
    p:r:f:<fayl>        "Qayta urinish" - audio butun yo'ldan (fayl xotirada bo'lsa)
    p:r:m:<id>          "Qayta urinish" - xulosa
Tugma ma'lumotiga ishonilmaydi: yig'ilish har safar `service` orqali EGASI bilan olinadi
(begona id - 404, "Bajarib bo'lmadi").

UZUN ISHLAR (transkript soatgacha, xulosa 10 daqiqagacha, bayonnoma 1-3 daqiqa) botning
navbatida EMAS - o'z iplarida (`workers`): odam shu paytda HR savolini beraverishi mumkin, bot
ishchilari ham band bo'lib qolmaydi.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import threading
import time

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ..core.config import settings
from ..schemas import meetings as schemas
from ..schemas.auth import AuthUser
from ..services import archive
from ..services.analytics import bind
from ..services.integrations.telegram import TelegramApi, TelegramError
from ..services.meetings import audio, export, intake, minutes, service
from ..services.meetings.errors import MeetingProblem
from . import render
from .mobile_app import BTN_APP
from .render import esc
from .voice_sample import BTN_VOICE, VoiceSample

log = logging.getLogger(__name__)

BTN_PLAUD = "🎙 Plaud"
#: Pastdagi klaviatura: Plaud va "📲 Ilovani yuklab olish" (`mobile_app.py`) yonma-yon.
KEYBOARD = {"keyboard": [[{"text": BTN_PLAUD}, {"text": BTN_APP}], [{"text": BTN_VOICE}]], "resize_keyboard": True,
            "is_persistent": True}
#: Tugmadan keyin shuncha vaqt ichida kelgan ovozli xabar - yozuv.
ARMED_SEC = 15 * 60
#: Telegram Bot API `getFile` chegarasi.
MAX_FILE = 20 * 1024 * 1024
#: Savol chegarasi (`ChatRequest.message`, mobil ilovadagi chat bilan bir xil).
QUESTION_CHARS = 1000
LANG_NAMES = {"uz": "o'zbek", "ru": "rus", "en": "ingliz"}
LANG_FLAGS = {"uz": "🇺🇿", "ru": "🇷🇺", "en": "🇬🇧"}
#: Eksport turlari: tugma yorlig'i -> xizmat formati.
EXPORTS = (("txt", "📝 Transkript (TXT)"), ("srt", "🎬 Transkript (SRT)"), ("md", "📋 Xulosa (MD)"),
           ("docx", "📄 Hisobot (Word)"), ("pdf", "📄 Hisobot (PDF)"))
#: Bayonnoma Word faylining izohi: hujjat LOYIHA, bo'sh joylar kotib/hujjat tizimi uchun (ega qarori); o'zgartirish -
#: shu fayl ostidagi tugma yoki faylga javob (Reply).
MINUTES_CAPTION = (f"📄 Bayonnoma - loyiha: Word faylidagi «{minutes.BLANK}» joylarini to'ldiring. O'zgartirish kerak "
                   "bo'lsa - «✏️ O'zgartirish»ni bosing yoki shu faylga javob (Reply) qilib yozing.")
#: Bayonnoma PDF faylining izohi: bo'sh joylarni to'ldirish uchun Word kerak.
MINUTES_PDF_CAPTION = (f"📕 Bayonnoma - loyiha (PDF): «{minutes.BLANK}» joylarini to'ldirish uchun Word formatini "
                       "tanlang. O'zgartirish kerak bo'lsa - «✏️ O'zgartirish»ni bosing yoki shu faylga javob (Reply) "
                       "qilib yozing.")
#: Bayonnoma fayli formatlari (til tanlangandan keyin odam BITTASINI tanlaydi) va format menyusi matni.
MINUTES_FORMATS = ("docx", "pdf")
MINUTES_FORMAT_PROMPT = ("📄 Bayonnoma ({title}) - qaysi formatda kerak? Word - tahrirlash va «________» joylarini "
                         "to'ldirish uchun, PDF - ko'rish va ulashish uchun.")
#: Bayonnoma ishi yozilayotgani ("⏳"): `verb` - "tayyorlanmoqda" (yangi hujjat) yoki "tahrirlanmoqda" (o'zgartirish).
MINUTES_WORKING = "⏳ Bayonnoma ({title}) {verb}… 1-3 daqiqa."
#: Kutish chegarasidan (`minutes.WAIT_SEC`) keyin ham yozilmoqda - natija keyin til tugmasidan bepul olinadi.
MINUTES_STILL_RUNNING = ("⏳ Bayonnoma hali tayyorlanmoqda - tayyor bo'lgach «📄 Bayonnoma» tugmasidan til va formatni "
                         "tanlang, fayl qayta yuboriladi.")
#: Ko'rsatma navbati javobi ostida (`n` - so'rovchining faol ko'rsatmalari).
NOTE_SAVED = "📝 Ko'rsatma eslab qolindi (jami {n} ta) - bayonnoma tayyorlashda hisobga olinadi."
#: "Qayta urinish" foyda bermaydigan xatolar: so'rovning o'zi noto'g'ri, fayl katta/uzun/yaroqsiz.
_FINAL = {400, 403, 404, 413, 415, 422}
_ID = re.compile(r"[0-9a-f]{32}")
_MARK = re.compile(r"^p:[a-z]:(?:[fm]:)?([0-9a-f]{32})")
#: Hujjat va natija xabaridagi «✏️ O'zgartirish» tugmasi: yig'ilish, hujjat tili va (2026-11-13 dan) fayl formati -
#: qayta ishga tushgandan keyin ham.
_EDIT_DATA = re.compile(r"^p:w:([0-9a-f]{32}):([a-z-]{2,7})(?::(docx|pdf))?$")
#: Hujjat sifatida kelgan audio - kengaytmasidan (Telegram mime bermasligi mumkin).
_AUDIO_EXT = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus")
#: Hujjat sifatida kelgan video (2026-11-17). MP4/MOV dan boshqasi ham shu yerda - odamga "MP4 yuboring" deyilsin.
_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".3gp", ".webm", ".mkv", ".avi", ".wmv", ".flv", ".mts", ".ts")
#: Video MP4/MOV emas (yoki ichi o'qilmadi) - `errors.MESSAGES["video_unsupported"]` bilan bir xil.
VIDEO_UNSUPPORTED = "Bu formatdan audio ajratib bo'lmadi, MP4 yuboring."
_TASHKENT = timezone(timedelta(hours=5))
_REMEMBER = 2000

PROMPT = (
    "🎙 <b>Plaud</b> - audio yuboring, matnga o'girib, qisqa xulosa beraman.\n\n"
    "• mikrofon tugmasini bosib <b>ovozli xabar</b> yozing (uzun bo'lsa ham bo'ladi), yoki\n"
    "• <b>audio fayl</b> yuboring: mp3, m4a, aac, wav, ogg - 20 MB gacha (Telegram chegarasi), "
    "3 soatgacha, yoki\n"
    "• <b>video</b> yuboring (mp4, mov) - faqat audiosi olinadi, video saqlanmaydi; 20 MB dan kattasini "
    "Slack yoki mobil ilova orqali.\n\n"
    "Keyingi 15 daqiqada kelgan ovozli xabar Plaud'ga ketadi; audio va video fayllar - har doim. "
    "Xulosa ostida: 💬 <b>Savol berish</b> (shu yozuv bo'yicha chat - Barno suhbatni eslab qoladi), "
    "vazifalar, eksport, boshqa til va 📄 <b>Bayonnoma</b> - rasmiy hujjat (Word/PDF) "
    "tanlangan tilda.\n\n"
    "Bayonnoma uchun ko'rsatma bermoqchi yoki tayyor bayonnomani o'zgartirmoqchi bo'lsangiz - «📄 Bayonnoma» "
    "menyusidagi «✍️ Ko'rsatma berish»ni bosing yoki bayonnomaga javob (Reply) qilib yozing: Barno tushunib, "
    "yangi versiyasini yuboradi."
)
BTN_ASK = "💬 Savol berish"
#: Til menyusida: bayonnoma yozilishidan oldin ko'rsatma (`p:g`).
BTN_GUIDE = "✍️ Ko'rsatma berish"
#: Tayyor hujjat (fayl, natija) ostida: o'zgartirish so'rovi (`p:w`).
BTN_EDIT = "✏️ O'zgartirish"
_HINT = ("💬 Savol bo'lsa - «💬 Savol berish» tugmasini bosing yoki shu xabarga javob (Reply) qilib yozing. "
         "Barno suhbatni eslab qoladi. Bayonnoma uchun ko'rsatmani ham shunday yozsa bo'ladi.")
#: ForceReply so'rovlarining tugmasi o'rnida: Telegram javob maydonini o'zi ochadi (izoh - 64 belgigacha).
ASK_REPLY = {"force_reply": True, "input_field_placeholder": "Savolingiz…"}
GUIDE_REPLY = {"force_reply": True, "input_field_placeholder": "Rais, qatnashchilar, nimaga e'tibor…"}
EDIT_REPLY = {"force_reply": True, "input_field_placeholder": "Masalan: 3-bandda muddat 1-dekabr"}
#: So'rov matnlaridagi belgilar (`ask_prompt`, `guide_prompt`, `edit_prompt`; Telegram javobdagi xabarni teglarsiz
#: beradi) - `prompt_kind`.
_PROMPT_MARK = "savolingizni yozing"
_GUIDE_MARK = "bayonnomasi uchun ko'rsatma yozing"
_EDIT_MARK = "nimani o'zgartirish kerak"
STALE_PROMPT = "Bu so'rov eskirgan - yozuv ostidagi «💬 Savol berish» tugmasini qayta bosing."
STALE_GUIDE = "Bu so'rov eskirgan - «📄 Bayonnoma» menyusidagi «✍️ Ko'rsatma berish»ni qayta bosing."
STALE_EDIT = "Bu so'rov eskirgan - bayonnoma ostidagi «✏️ O'zgartirish» tugmasini qayta bosing."
#: Yig'ilishi xotiradan ketgan (qayta ishga tushgan) so'rovga javob - so'rov turi (`prompt_kind`) bo'yicha izoh.
_STALE = {"ask": STALE_PROMPT, "note": STALE_GUIDE, "revise": STALE_EDIT}
CHAT_RESET = ("🔄 Yangi suhbat boshlandi - oldingi savol-javoblar va bayonnoma ko'rsatmalari endi hisobga olinmaydi "
              "(tayyor bayonnomalar saqlanib qoladi).")
#: Eski xabardagi «🗂 Boshqa shablon» bosilsa (ega qarori 2026-11-12: funksiya o'chirilgan).
TEMPLATE_OFF = "«Boshqa shablon» hozircha o'chirilgan - xulosa avtomatik shablon bilan yoziladi."


class Plaud:
    def __init__(self, api: TelegramApi, *, inline: bool = False, workers: int = 4,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.api = api
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        #: chat -> qurollanish muddati (`clock`).
        self._armed: dict[int, float] = {}
        #: Fayl kaliti -> Telegram media obyekti: "Qayta urinish" uchun (faqat xotirada).
        self._files: OrderedDict[str, dict[str, Any]] = OrderedDict()
        #: (chat, xabar) -> yig'ilish: javob (Reply) qaysi yozuv haqida.
        self._messages: OrderedDict[tuple[int, int], str] = OrderedDict()
        #: (chat, xabar) -> (niyat, hujjat tili): "note" / "revise" - ✍️ / ✏️ so'rovi, "doc" - bayonnoma fayli yoki
        #: natijasi (tili bilan). Faqat niyatli xabarlar; qolgani - oddiy savol (`_target_of_reply`).
        self._intents: OrderedDict[tuple[int, int], tuple[str, str | None]] = OrderedDict()
        #: (chat, yig'ilish, hujjat tili) -> odam tanlagan fayl formati: chatdan boshlangan tahrir fayli ham shu
        #: formatda (`_follow_minutes`). Format tugmasi, yuborilgan fayl va «✏️ O'zgartirish» tugmasidagi format
        #: (`_marks`, `p:w`) yangilaydi; yo'q bo'lsa - Word.
        self._formats: OrderedDict[tuple[int, str, str], str] = OrderedDict()
        self._pool = None if inline else ThreadPoolExecutor(max_workers=max(1, workers),
                                                             thread_name_prefix="tg-plaud")
        #: «🗣 Ovoz namunasi» (`voice_sample.py`) - Plaud bilan birga yoqiladi.
        self.voice = VoiceSample(api, clock=clock)

    # --- kirish ---------------------------------------------------------------------------

    @staticmethod
    def media(msg: dict[str, Any]) -> dict[str, Any] | None:
        """Xabardagi yozuv: ovozli xabar, audio fayl yoki audio hujjat; video, dumaloq video yoki video hujjat
        (2026-11-17 - `video: True`, audiosi olinadi). `kind` qo'shiladi."""
        for kind in ("voice", "audio"):
            found = msg.get(kind)
            if isinstance(found, dict) and found.get("file_id"):
                return {**found, "kind": kind}
        for kind in ("video", "video_note"):
            found = msg.get(kind)
            if isinstance(found, dict) and found.get("file_id"):
                return {**found, "kind": kind, "video": True}
        doc = msg.get("document")
        if isinstance(doc, dict) and doc.get("file_id"):
            name = str(doc.get("file_name") or "").lower()
            if str(doc.get("mime_type") or "").startswith("audio/") or name.endswith(_AUDIO_EXT):
                return {**doc, "kind": "document"}
            if audio.is_video_type(doc.get("mime_type")) or name.endswith(_VIDEO_EXT):
                return {**doc, "kind": "document", "video": True}
        return None

    def wants(self, chat_id: int, media: dict[str, Any]) -> bool:
        """Shu audio yozuvmi: fayl - har doim; ovozli xabar - chat qurollangan yoki chat
        savoli uchun juda uzun bo'lsa. Qurollanish bir ovozli xabarga ishlaydi. Yozuv xabariga
        javob bo'lgan ovozli xabar bu yerga kelmaydi (`claims_reply` - qurollanish sarflanmaydi)."""
        if media["kind"] != "voice":
            return True
        with self._lock:
            armed = self._armed.get(chat_id, 0.0) > self._clock()
            if armed:
                self._armed.pop(chat_id, None)
        return armed or int(media.get("duration") or 0) > settings.telegram_voice_max_sec

    def on_button(self, chat_id: int, user: AuthUser) -> None:
        with self._lock:
            self._armed[chat_id] = self._clock() + ARMED_SEC
            if len(self._armed) > _REMEMBER:
                self._armed.clear()
        # Oxirgi bosilgan tugma ustun: ovoz namunasi kutilayotgan bo'lsa - endi yozuv kutiladi.
        self.voice.disarm(chat_id)
        self._send(chat_id, PROMPT, markup=KEYBOARD)

    def disarm(self, chat_id: int) -> None:
        """«🗣 Ovoz namunasi» bosildi - keyingi ovozli xabar Plaud yozuvi emas."""
        with self._lock:
            self._armed.pop(chat_id, None)

    def show_keyboard(self, chat_id: int) -> None:
        self._send(chat_id, "🎙 <b>Plaud</b> - pastdagi tugma: audio yuboring, matn va qisqa xulosa olasiz.\n"
                            "📲 <b>Ilovani yuklab olish</b> - Barno AI ilovasi (Android).\n"
                            "🗣 <b>Ovoz namunasi</b> - Plaud yig'ilishlarida ism-familiyangiz avtomatik chiqishi uchun.",
                   markup=KEYBOARD)

    def on_audio(self, chat_id: int, user: AuthUser, msg: dict[str, Any], media: dict[str, Any]) -> None:
        # Jarayon xabari shu yerda, navbatdan oldin: ishchilar band bo'lsa ham odam audiosi qabul
        # qilinganini darhol ko'radi.
        progress = self._progress(chat_id, media, reply_to=msg.get("message_id"))
        progress.show(intake.UPLOAD)
        recorded_at = float(msg.get("date") or time.time())
        self._submit(user, lambda: self._handle(chat_id, user, media, recorded_at=recorded_at, progress=progress))

    def on_reply(self, chat_id: int, user: AuthUser, msg: dict[str, Any], text: str, *,
                 echo: int | None = None) -> bool:
        """Javob (Reply) yozuv xabariga bo'lsa - shu yig'ilish chatiga xabar. `False` - oddiy savol.
        ✍️ so'roviga javob - bayonnoma uchun ko'rsatma (`intent="note"`), ✏️ so'roviga - tayyor hujjatdagi
        o'zgartirish (`intent="revise"`, shu til); bayonnoma fayli yoki natijasiga javob - niyatni chat modeli
        aniqlaydi, hujjat tili ma'lum (`minutes_lang`). Yig'ilishi xotiradan ketgan (qayta ishga tushgan) so'rovga
        javob - turi bo'yicha izoh bilan yutiladi (`_STALE`): yozuv haqidagi xabar HR yordamchisiga ketmasin.
        `echo` - ovozli xabarning "🎙 matn"i (`runner._meeting_voice`): xabar qabul qilinsa u ham AYNAN shu topilgan
        yig'ilishga bog'lanadi (`_link`)."""
        reply = msg.get("reply_to_message")
        if not isinstance(reply, dict):
            return False
        target = self._target_of_reply(chat_id, user, reply)
        if target is None:
            stale = _STALE.get(prompt_kind(reply) or "")
            if stale is None:
                return False
            self._send(chat_id, stale, reply_to=msg.get("message_id"))
            return True
        meeting_id, intent, lang = target
        self._link(chat_id, echo, meeting_id)
        holder = self._send(chat_id, "⏳ Javob tayyorlanmoqda…", reply_to=msg.get("message_id"))
        # "⏳" - javobning birinchi bo'lagi bo'ladi: javob kelguncha (yoki tahrir o'tmay "⏳" qolsa) unga
        # yozilgan savol ham shu suhbatga, HR yordamchisiga emas.
        self._remember(chat_id, holder, meeting_id)
        question = text.strip()[:QUESTION_CHARS]
        explicit = intent if intent in ("note", "revise") else None
        self._submit(user, lambda: self._question(chat_id, user, meeting_id, question, holder, intent=explicit,
                                                  minutes_lang=lang))
        return True

    def claims_reply(self, chat_id: int, user: AuthUser, msg: dict[str, Any]) -> bool:
        """Ovozli xabar yig'ilish chatiga xabarmi: u BOT xabariga javob (Reply) va o'sha xabardan yig'ilish
        topiladi (`_target_of_reply`; bayonnoma fayli va natijasi, oldingi ovozli savolning "🎙 matn"i ham - `_link`)
        yoki u bot so'rovi - «💬 Savol berish», «✍️ Ko'rsatma berish», «✏️ O'zgartirish» (eskirgani ham - `on_reply`
        uni izoh bilan yutadi). Shunda ovoz yangi yozuv ham emas (qurollanish sarflanmaydi), HR savoli ham emas: bot
        uni matnga o'girib (`runner._meeting_voice`) `on_reply` ga beradi. Odamning o'z xabariga javob - yo'q."""
        reply = msg.get("reply_to_message")
        if not isinstance(reply, dict) or not (reply.get("from") or {}).get("is_bot"):
            return False
        return is_prompt(reply) or self._meeting_of_reply(chat_id, user, reply) is not None

    def on_callback(self, cq_id: str, chat_id: int, msg: dict[str, Any], user: AuthUser, data: str) -> None:
        parts = data.split(":")
        op = parts[1] if len(parts) > 1 else ""
        message_id = msg.get("message_id")
        try:
            if op == "r" and len(parts) == 4:
                self._retry(cq_id, chat_id, user, parts[2], parts[3], message_id)
                return
            meeting_id = parts[2] if len(parts) > 2 else ""
            if not _ID.fullmatch(meeting_id):
                self._answer(cq_id, "Tugma eskirgan", alert=True)
                return
            # EGALIK shu yerda: begona (yoki o'chirilgan) yig'ilish - 404, ish boshlanmaydi.
            view = service.detail(user, meeting_id)
            language = str(view.get("language") or "uz")
            arg = parts[3] if len(parts) > 3 else ""
            if op == "q":
                self._answer(cq_id)
                self._prompt(chat_id, meeting_id, ask_prompt(view.get("title")), ASK_REPLY)
            elif op == "n":
                service.chat_reset(user, meeting_id)
                self._answer(cq_id)
                # Yangi suhbatning birinchi savoli shu yerdan: tugma ham, javob (Reply) ham shu yig'ilishga.
                self._remember(chat_id, self._send(chat_id, CHAT_RESET, markup=ask_menu(meeting_id)), meeting_id)
            elif op == "t":
                self._answer(cq_id)
                self._submit(user, lambda: self._tasks(chat_id, user, meeting_id))
            elif op == "s":
                # Eski xabardagi «🗂 Boshqa shablon» (yoki uning menyusi): funksiya o'chirilgan - xulosa
                # yozilmaydi, tugmalar yangi ko'rinishga almashadi.
                self._answer(cq_id, TEMPLATE_OFF, alert=True)
                self._menu(chat_id, message_id, controls(meeting_id, language))
            elif op == "e" and not arg:
                self._answer(cq_id)
                self._menu(chat_id, message_id, export_menu(meeting_id))
            elif op == "e":
                self._answer(cq_id, "Fayl tayyorlanmoqda…")
                self._menu(chat_id, message_id, controls(meeting_id, language))
                self._submit(user, lambda: self._export(chat_id, user, meeting_id, arg))
            elif op == "l" and not arg:
                self._answer(cq_id)
                self._menu(chat_id, message_id, lang_menu(meeting_id, language))
            elif op == "l" and arg in LANG_NAMES and len(parts) < 5:
                self._answer(cq_id)
                self._menu(chat_id, message_id, confirm_menu(meeting_id, arg))
            elif op == "l" and arg in LANG_NAMES:
                self._answer(cq_id, "Qayta o'girilmoqda…")
                self._menu(chat_id, message_id, controls(meeting_id, arg))
                self._submit(user, lambda: self._relang(chat_id, user, meeting_id, arg))
            elif op == "d" and not arg:
                self._answer(cq_id)
                self._menu(chat_id, message_id, minutes_menu(meeting_id, language))
            elif op == "d" and arg in minutes.LANGS and len(parts) == 4:
                # Til tanlandi - format menyusi (hujjat hali yozilmaydi); savol - qisqa bildirishnoma.
                self._answer(cq_id, MINUTES_FORMAT_PROMPT.format(title=minutes.LANG_TITLES[arg]))
                self._menu(chat_id, message_id, minutes_format_menu(meeting_id, arg))
            elif op == "d" and arg in minutes.LANGS and len(parts) == 5 and parts[4] in MINUTES_FORMATS:
                fmt = parts[4]
                self._answer(cq_id, "Bayonnoma tayyorlanmoqda…")
                self._menu(chat_id, message_id, controls(meeting_id, language))
                self._submit(user, lambda: self._minutes(chat_id, user, meeting_id, arg, fmt))
            elif op == "b":
                self._answer(cq_id)
                self._menu(chat_id, message_id, controls(meeting_id, language))
            elif op == "g" and len(parts) == 3:
                # Til menyusi o'z joyida qoladi: ko'rsatmadan keyin tilni o'sha yerdan tanlash mumkin.
                self._answer(cq_id)
                self._prompt(chat_id, meeting_id, guide_prompt(view.get("title")), GUIDE_REPLY, intent="note")
            elif op == "w" and arg in minutes.LANGS and (len(parts) == 4 or (len(parts) == 5
                                                                            and parts[4] in MINUTES_FORMATS)):
                if len(parts) == 5:
                    self._set_format(chat_id, meeting_id, arg, parts[4])
                self._answer(cq_id)
                self._prompt(chat_id, meeting_id, edit_prompt(view.get("title"), arg), EDIT_REPLY, intent="revise",
                             lang=arg)
            else:
                self._answer(cq_id, "Tugma eskirgan", alert=True)
        except MeetingProblem as exc:
            self._answer(cq_id, f"Bajarib bo'lmadi: {exc.detail}", alert=True)

    # --- audio -> transkript -> xulosa ----------------------------------------------------

    def _handle(self, chat_id: int, user: AuthUser, media: dict[str, Any], *, recorded_at: float,
                progress: intake.Progress | None = None) -> None:
        unique = str(media.get("file_unique_id") or media.get("file_id") or "")
        with self._lock:
            self._files[unique] = media
            while len(self._files) > _REMEMBER:
                self._files.popitem(last=False)
        if progress is None:
            progress = self._progress(chat_id, media)
            progress.show(intake.UPLOAD)
        try:
            meeting_id = self._ingest(user, media, unique, recorded_at)
            text = intake.wait_transcript(user, meeting_id, sleep=self._sleep, progress=progress.view)
        except intake.Problem as exc:
            self._fail(chat_id, progress, str(exc), f"p:r:f:{unique}" if exc.retry else None)
            return
        except MeetingProblem as exc:
            self._fail(chat_id, progress, str(exc.detail), None if exc.status_code in _FINAL else f"p:r:f:{unique}")
            return
        except Exception:  # noqa: BLE001 - odam javobsiz qolmasin
            log.exception("Telegram Plaud (%s): kutilmagan xato", user.actorId)
            self._fail(chat_id, progress, "ichki xato.", f"p:r:f:{unique}")
            return
        self._deliver(chat_id, user, meeting_id, text, progress=progress)

    def _ingest(self, user: AuthUser, media: dict[str, Any], unique: str, recorded_at: float) -> str:
        """Telegram fayli -> yig'ilish id. Oldin kelgan bo'lsa davom ettiriladi."""
        client = intake.client_id("telegram-file", unique)
        meeting_id = intake.meeting_of(user, client)
        if meeting_id is not None and intake.resume(user, meeting_id):
            return meeting_id
        if int(media.get("file_size") or 0) > MAX_FILE:
            raise intake.Problem("Fayl 20 MB dan katta - Telegram boti bundan kattasini ololmaydi. "
                                 "Mobil ilova yoki Slack orqali yuboring.")
        try:
            info = self.api.get_file(str(media["file_id"]))
            data = self.api.download(str(info.get("file_path") or ""),
                                     limit=min(MAX_FILE, service.max_upload_bytes()))
        except TelegramError as exc:
            log.warning("Telegram Plaud (%s): fayl olinmadi: %s", user.actorId, exc)
            if exc.code == 413:
                raise intake.Problem("Fayl juda katta (20 MB gacha).") from None
            raise intake.Problem("Telegram'dan faylni olib bo'lmadi.", retry=True) from None
        if media.get("video"):
            # Video: faqat MP4/MOV; audiosini ajratish va videoni o'chirish - yig'ilishning o'zida (`service.complete`).
            kind = audio.VIDEO_TYPE if audio.sniff(data[:16], audio.VIDEO_TYPE) else None
            if kind is None:
                log.info("Telegram Plaud (%s): video MP4 emas (%s)", user.actorId, media.get("mime_type"))
                raise intake.Problem(VIDEO_UNSUPPORTED)
        else:
            kind = next((t for t in service.ACCEPTED_TYPES if audio.sniff(data[:16], t)), None)
        if kind is None:
            log.info("Telegram Plaud (%s): mos format yo'q (%s)", user.actorId, media.get("mime_type"))
            raise intake.Problem("Bu audio formati qo'llab-quvvatlanmaydi (mp3, m4a, aac, wav, ogg).")
        log.info("Telegram Plaud (%s): %s, %d bayt", user.actorId, kind, len(data))
        with tempfile.TemporaryDirectory(prefix="tg-audio-") as tmp:
            path = Path(tmp) / "audio"
            path.write_bytes(data)
            return intake.upload(user, client, path, len(data), hashlib.sha256(data).hexdigest(), kind,
                                 title=title_of(media, recorded_at), recorded_at=recorded_at, channel="bot",
                                 origin="telegram")

    def _deliver(self, chat_id: int, user: AuthUser, meeting_id: str, text: str, *,
                 progress: intake.Progress | None = None) -> None:
        """Transkript (xabarlar 4000 belgidan), keyin (yozilishini kutib) "Qisqa xulosa" va tugmalar.
        `progress` (audio yo'li) - jarayon xabari transkript OSTIGA ko'chadi va xulosa chiqqach o'chiriladi."""
        pages = render.pack(["🎙 <b>Transkript</b>\n" + esc(text or "Audioda nutq topilmadi.")])
        for n, page in enumerate(pages, 1):
            head = f"🎙 <b>Transkript ({n}/{len(pages)})</b>\n" if len(pages) > 1 and n > 1 else ""
            self._remember(chat_id, self._send(chat_id, head + page), meeting_id)
        if progress is not None:
            progress.close()
            progress.show(intake.SUMMARY)
        try:
            view = intake.wait_summary(user, meeting_id, sleep=self._sleep)
            self._card(chat_id, user, meeting_id, view)
        finally:
            if progress is not None:
                progress.close()

    def _card(self, chat_id: int, user: AuthUser, meeting_id: str, view: dict[str, Any]) -> None:
        """"📋 Qisqa xulosa" (yoki nega yo'qligi) va tugmalar - oxirgi xabar ostida."""
        status, retry = view["summaryStatus"], None
        if status == "ready":
            try:
                body = html_of(intake.brief_markdown(user, meeting_id))
            except MeetingProblem as exc:
                body = esc(f"Xulosani olib bo'lmadi: {exc.detail}")
        elif status in ("failed", "skipped"):
            reason = intake.summary_error(user, meeting_id)
            body = esc("Xulosa yozilmadi" + (f": {reason}" if reason else "."))
            retry = f"p:r:m:{meeting_id}" if status == "failed" else None
        else:
            body = "Xulosa hali tayyor emas - birozdan keyin «📎 Eksport -> 📋 Xulosa (MD)» dan oling."
        pages = render.pack(["📋 <b>Qisqa xulosa</b>\n\n" + body, _HINT])
        markup = controls(meeting_id, view["language"], retry=retry)
        for n, page in enumerate(pages, 1):
            sent = self._send(chat_id, page, markup=markup if n == len(pages) else None)
            self._remember(chat_id, sent, meeting_id)

    def _fail(self, chat_id: int, progress: intake.Progress, reason: str, retry: str | None) -> None:
        text = esc(f"Matnga o'girib bo'lmadi: {reason}")
        markup = render.keyboard([[{"text": "🔁 Qayta urinish", "callback_data": retry}]]) if retry else None
        progress.close()
        self._send(chat_id, text, markup=markup)

    def _progress(self, chat_id: int, media: dict[str, Any], *, reply_to: Any = None) -> intake.Progress:
        """Shu audioning jarayon xabari: ovozli xabar yoki fayl (nomi bilan). Birinchi xabar odamning
        audio xabariga javob (`reply_to`), transkript ostidagisi - oddiy."""
        if media["kind"] == "voice":
            head = "🎙 Ovozli xabaringiz qabul qilindi."
        elif media.get("video"):
            # Video saqlanmaydi - odam buni darhol bilsin (ega qarori 2026-11-17).
            name = export.one_line(media.get("file_name")) or "video"
            head = f"🎬 «{esc(name[:80])}» qabul qilindi - videodan faqat audio olinadi, video saqlanmaydi."
        else:
            name = export.one_line(media.get("file_name") or media.get("title")) or "audio"
            head = f"📎 «{esc(name[:80])}» qabul qilindi."
        first = [reply_to]

        def show(ref: int | None, text: str) -> int | None:
            if ref is None:
                return self._send(chat_id, text, reply_to=first.pop() if first else None)
            self.api.edit_message_text(chat_id, ref, text)
            return ref

        return intake.Progress(head, show=show, drop=lambda ref: self._delete(chat_id, ref))

    # --- savol (Reply) -----------------------------------------------------------------------

    def _target_of_reply(self, chat_id: int, user: AuthUser,
                         reply: dict[str, Any]) -> tuple[str, str | None, str | None] | None:
        """Javob berilgan xabar -> (yig'ilish, niyat, hujjat tili) yoki `None`. Shu tartibda: xotira (`_remember`);
        tugmalardagi belgi (`_marks`: birinchi `p:` tugmasi, EGALIK tekshiruvi bilan; «✏️ O'zgartirish» tugmasi bor
        bo'lsa - bayonnoma xabari, ("doc", til)); odamning audio fayli. Niyat: "note" / "revise" - ✍️ / ✏️ so'rovi,
        "doc" - bayonnoma fayli yoki natijasi, `None` - oddiy xabar."""
        key = (chat_id, int(reply.get("message_id") or 0))
        with self._lock:
            found = self._messages.get(key)
            intent, lang = self._intents.get(key, (None, None))
        if found:
            return found, intent, lang
        marked = _marks(reply)
        if marked is not None:
            meeting_id = self._owned(user, marked[0])
            if meeting_id and marked[1] and marked[2]:
                self._set_format(chat_id, meeting_id, marked[1], marked[2])
            return (meeting_id, "doc" if marked[1] else None, marked[1]) if meeting_id else None
        media = self.media(reply)
        if media is not None:
            unique = str(media.get("file_unique_id") or media.get("file_id") or "")
            meeting_id = intake.meeting_of(user, intake.client_id("telegram-file", unique))
            return (meeting_id, None, None) if meeting_id else None
        return None

    def _meeting_of_reply(self, chat_id: int, user: AuthUser, reply: dict[str, Any]) -> str | None:
        """Javob berilgan xabar -> yig'ilish (`_target_of_reply`): xotira, tugmalardagi belgi yoki odamning audio
        fayli."""
        target = self._target_of_reply(chat_id, user, reply)
        return target[0] if target else None

    @staticmethod
    def _owned(user: AuthUser, meeting_id: str) -> str | None:
        try:
            service.detail(user, meeting_id)
        except MeetingProblem:
            return None
        return meeting_id

    def _link(self, chat_id: int, message_id: int | None, meeting_id: str) -> None:
        """Ovozli savolning "🎙 matn" xabari (`on_reply(echo=...)`) shu yig'ilishniki: «💬 Savol berish» tugmasi
        (`ask_menu` - qayta ishga tushgandan keyin ham belgi) va xotira. Unga javob (Reply) - matn bo'lsa ham,
        ovoz bo'lsa ham (`claims_reply`) - shu suhbatga savol: HR yordamchisiga ham, yangi yozuvga ham ketmaydi.
        Tugma qo'yilmasa (Telegram xatosi) - xotiradagi bog'lanish baribir ishlaydi."""
        if message_id is None:
            return
        self._menu(chat_id, message_id, ask_menu(meeting_id))
        self._remember(chat_id, message_id, meeting_id)

    def _prompt(self, chat_id: int, meeting_id: str, text: str, markup: dict[str, Any], *,
                intent: str | None = None, lang: str | None = None) -> None:
        """ForceReply so'rovi: «💬 Savol berish» (`ask_prompt`), «✍️ Ko'rsatma berish» (`guide_prompt`, niyat "note")
        yoki «✏️ O'zgartirish» (`edit_prompt`, niyat "revise" va hujjat tili); unga javob - shu yig'ilish chatiga
        (`on_reply`). So'rovda `p:` tugmasi bo'la olmaydi - yig'ilish va niyat faqat xotirada eslab qolinadi."""
        self._remember(chat_id, self._send(chat_id, text, markup=markup), meeting_id, intent=intent, lang=lang)

    def _question(self, chat_id: int, user: AuthUser, meeting_id: str, question: str, holder: int | None, *,
                  intent: str | None = None, minutes_lang: str | None = None) -> None:
        """Yig'ilish chatiga xabar (`service.chat_send`, kanal `telegram`): "⏳" o'rnida javob, OXIRGI
        xabarida «💬 Yana savol» va «🔄 Yangi suhbat», qolgan bo'laklarida «💬 Savol berish». Tugmalar - qayta
        ishga tushgandan keyin ham javob (Reply) uchun yig'ilish belgisi, savol qaysi bo'lakka yozilsa ham.
        Xato bo'lsa - sababi va «💬 Savol berish» (qayta so'rash va o'sha belgi); yozuv yo'q (404) - tugmasiz.

        BAYONNOMA: `intent` - aniq kirish nuqtasi (✍️ - "note", ✏️ - "revise"; chat modelisiz), `minutes_lang` - odam
        qaysi til hujjatiga yozyapti. Ko'rsatma navbati - javob ostida nechta ko'rsatma eslab qolingani va
        «📄 Bayonnoma tayyorlash» (`note_menu`); ish boshlanmagan bo'lsa - sababi (`minutes_note`); ish boshlangan
        bo'lsa (tayyorlash yoki o'zgartirish) - javobdan keyin hujjatning o'zi (`_follow_minutes`)."""
        markup = marker = ask_menu(meeting_id)
        ref = None
        try:
            view = service.detail(user, meeting_id)
            found = service.chat_send(user, meeting_id, question, None, channel="telegram", intent=intent,
                                      minutes_lang=minutes_lang)
            turn = found.get("minutes") if isinstance(found.get("minutes"), dict) else None
            body = answer_html(found, speakers_of(view["speakers"]), view["language"]) + minutes_note(turn)
            markup = note_menu(meeting_id) if turn and turn.get("action") == "note" else chat_menu(meeting_id)
            ref = turn
        except MeetingProblem as exc:
            body = esc(f"Javob berib bo'lmadi: {exc.detail}")
            if exc.status_code == 404:
                # O'chirilgan yoki begona yozuv: qayta so'rashning ma'nosi yo'q.
                markup = marker = None
        except Exception:  # noqa: BLE001
            log.exception("Telegram Plaud savoli (%s): kutilmagan xato", meeting_id)
            body = "Javob berib bo'lmadi: ichki xato."
        for message_id in self._replace(chat_id, holder, body, markup=markup, marker=marker):
            self._remember(chat_id, message_id, meeting_id)
        if ref and ref.get("action") in ("create", "revise") and ref.get("id"):
            self._follow_minutes(chat_id, user, meeting_id, ref)

    # --- tugmalar -------------------------------------------------------------------------------

    def _retry(self, cq_id: str, chat_id: int, user: AuthUser, kind: str, ident: str, message_id: Any) -> None:
        if kind == "f":
            with self._lock:
                media = self._files.get(ident)
            if media is None:
                self._answer(cq_id, "Audioni qaytadan yuboring - fayl xotirada yo'q.", alert=True)
                return
            self._answer(cq_id, "Qayta urinilmoqda…")
            self._clear(chat_id, message_id)
            self._submit(user, lambda: self._handle(chat_id, user, media, recorded_at=time.time()))
        elif kind == "m" and _ID.fullmatch(ident):
            self._answer(cq_id, "Xulosa qayta yozilmoqda…")
            self._clear(chat_id, message_id)

            def again() -> None:
                service.retry(user, ident)
                self._card(chat_id, user, ident, intake.wait_summary(user, ident, sleep=self._sleep))

            self._submit(user, again)
        else:
            self._answer(cq_id, "Tugma eskirgan", alert=True)

    def _tasks(self, chat_id: int, user: AuthUser, meeting_id: str) -> None:
        try:
            view = service.detail(user, meeting_id)
            items = service.action_items(user, meeting_id)["items"]
            body = tasks_html(items, speakers_of(view["speakers"]), view["language"])
        except MeetingProblem as exc:
            body = esc(f"Bajarib bo'lmadi: {exc.detail}")
        for page in render.pack(["✅ <b>Vazifalar</b>\n\n" + (body or "Bu yozuvda vazifalar topilmadi.")]):
            self._remember(chat_id, self._send(chat_id, page), meeting_id)

    def _export(self, chat_id: int, user: AuthUser, meeting_id: str, kind: str) -> None:
        """Fayl (`EXPORTS`) shu chatga - `sendDocument`."""
        try:
            if kind in ("txt", "srt"):
                text, _, name = service.export_transcript(user, meeting_id, kind, with_speakers=True,
                                                          with_timestamps=True)
                data, content_type = text.encode("utf-8"), "text/plain"
            elif kind == "md":
                summary_id = service.detail(user, meeting_id).get("primarySummaryId")
                if not summary_id:
                    raise intake.Problem("Bu yozuvda xulosa yo'q.")
                text, _, name = service.export_summary(user, meeting_id, summary_id, "md")
                data, content_type = text.encode("utf-8"), "text/markdown"
            elif kind in ("docx", "pdf"):
                data, content_type, disposition = service.export_meeting(user, meeting_id, kind)
                name = intake.filename(disposition) or f"barno.{kind}"
            else:
                return
        except (MeetingProblem, intake.Problem) as exc:
            self._send(chat_id, esc(f"Faylni olib bo'lmadi: {getattr(exc, 'detail', exc)}"))
            return
        try:
            self.api.send_document(chat_id, name, data, content_type or "application/octet-stream")
        except TelegramError as exc:
            log.warning("Telegram Plaud: fayl yuborilmadi: %s", exc)
            self._send(chat_id, "Faylni yuborib bo'lmadi - qaytadan urinib ko'ring.")
            return
        archive.record("telegram", "out", "document", chat=chat_id, actor=user.actorId, data=data, name=name,
                       mime=content_type or "", meta={"meeting": meeting_id, "export": kind})

    def _relang(self, chat_id: int, user: AuthUser, meeting_id: str, lang: str) -> None:
        """Boshqa tilda qayta o'girish (GAPI qayta to'lanadi - tugmada tasdiq bor), so'ng
        yangi transkript va xulosa."""
        name = LANG_NAMES[lang]
        holder = self._send(chat_id, f"⏳ Audio {name} tilida qayta o'girilmoqda…")
        try:
            service.retranscribe(user, meeting_id, schemas.RetranscribeRequest(language=lang, confirmCharge=True))
            text = intake.wait_transcript(user, meeting_id, sleep=self._sleep)
        except (MeetingProblem, intake.Problem) as exc:
            self._replace(chat_id, holder, esc(f"Qayta o'girib bo'lmadi: {getattr(exc, 'detail', exc)}"))
            return
        self._replace(chat_id, holder, f"✅ Audio {name} tilida qayta o'girildi.")
        self._deliver(chat_id, user, meeting_id, text)

    def _minutes(self, chat_id: int, user: AuthUser, meeting_id: str, lang: str, fmt: str = "docx") -> None:
        """Tanlangan til va formatda bayonnoma (format tugmasi): "⏳" xabari, `minutes.generate` (shu ipda; hisob
        egasining ko'rsatmalari bilan), so'ng FAQAT `fmt` fayli va natija (`_send_minutes`). Tayyor hujjat bo'lsa va
        yangi ko'rsatma yo'q bo'lsa model qayta chaqirilmaydi - fayl shunchaki qayta yuboriladi; yangi ko'rsatmalar
        bo'lsa - joriy hujjatning tahriri (avvalgi o'zgartirishlar saqlanadi). Boshqa yo'lning ishiga qo'shilib,
        kutish chegarasidan keyin ham yozilayotgan bo'lsa - "hali tayyorlanmoqda"."""
        title = minutes.LANG_TITLES.get(lang, lang)
        self._set_format(chat_id, meeting_id, lang, fmt)
        holder = self._send(chat_id, esc(MINUTES_WORKING.format(title=title, verb="tayyorlanmoqda")))
        # "⏳" - natija xabari bo'ladi: kutish paytida unga yozilgani ham shu hujjat tilida chatga.
        self._remember(chat_id, holder, meeting_id, intent="doc", lang=lang)
        # Xato va "hali tayyorlanmoqda" xabarida ham «💬 Savol berish» (`ask_menu`): yig'ilish belgisi - qayta ishga
        # tushgandan keyin ham ularga javob (Reply) shu yozuv chatiga boradi (HR yordamchisiga emas).
        try:
            view = minutes.generate(user, meeting_id, lang, sleep=self._sleep)
        except (MeetingProblem, intake.Problem) as exc:
            self._replace(chat_id, holder, esc(f"Bayonnoma yozilmadi: {getattr(exc, 'detail', exc)}"),
                          markup=ask_menu(meeting_id))
            return
        except Exception:  # noqa: BLE001 - odam "⏳" bilan qolmasin
            log.exception("Telegram Plaud bayonnomasi (%s): kutilmagan xato", meeting_id)
            self._replace(chat_id, holder, "Bayonnoma yozilmadi: ichki xato.", markup=ask_menu(meeting_id))
            return
        if view.get("status") == "running":
            self._replace(chat_id, holder, esc(MINUTES_STILL_RUNNING), markup=ask_menu(meeting_id))
            return
        self._send_minutes(chat_id, user, meeting_id, view, lang, holder, fmt)

    def _follow_minutes(self, chat_id: int, user: AuthUser, meeting_id: str, ref: dict[str, Any]) -> None:
        """Chat navbati boshlagan bayonnoma ishi (`ref` - navbatning `minutes`i, `id` bor): yozilayotgan bo'lsa - "⏳"
        ("tahrirlanmoqda" / "tayyorlanmoqda") va kutish (`minutes.wait`, shu ipda), so'ng fayllar va natija
        (`_send_minutes`; fayl - odam shu hujjat uchun tanlagan formatda, `_formats`, yo'q bo'lsa Word). Yiqilsa -
        sababi (`minutes.failure_detail`; o'zgartirishda «✏️ O'zgartirish» bilan - qayta so'rash uchun); kutish
        chegarasidan keyin ham yozilayotgan bo'lsa - "hali tayyorlanmoqda"."""
        lang = str(ref.get("language") or "")
        fmt = self._format_of(chat_id, meeting_id, lang)
        revise = ref.get("action") == "revise"
        holder = None
        try:
            found = minutes.status(user, meeting_id, str(ref["id"]))
            if found["status"] == "running":
                verb = "tahrirlanmoqda" if revise else "tayyorlanmoqda"
                holder = self._send(chat_id, esc(MINUTES_WORKING.format(title=minutes.LANG_TITLES.get(lang, lang),
                                                                        verb=verb)))
                self._remember(chat_id, holder, meeting_id, intent="doc", lang=lang)
                found = minutes.wait(user, meeting_id, str(ref["id"]), sleep=self._sleep)
            if found["status"] == "ready":
                done_lang = str(found.get("language") or lang)
                self._send_minutes(chat_id, user, meeting_id, found, done_lang, holder,
                                   self._format_of(chat_id, meeting_id, done_lang) if done_lang != lang else fmt)
                return
            markup = None
            if found["status"] == "running":
                text = esc(MINUTES_STILL_RUNNING)
            else:
                head = "Bayonnoma tahrirlanmadi" if revise else "Bayonnoma yozilmadi"
                text = esc(f"{head}: {minutes.failure_detail(found)}")
                markup = minutes_done_menu(meeting_id, lang, fmt) if revise and lang in minutes.LANGS else None
        except MeetingProblem as exc:
            text, markup = esc(f"Bayonnoma yuborilmadi: {exc.detail}"), None
        except Exception:  # noqa: BLE001 - odam "⏳" bilan qolmasin
            log.exception("Telegram Plaud bayonnomasi (%s): chat navbatidagi ish kuzatilmadi", meeting_id)
            text, markup = "Bayonnoma yuborilmadi: ichki xato.", None
        # Tugmasiz xabar qayta ishga tushgandan keyin hech qaysi yozuvga bog'lanmasdi - «💬 Savol berish» belgi.
        for message_id in self._replace(chat_id, holder, text, markup=markup or ask_menu(meeting_id)):
            self._remember(chat_id, message_id, meeting_id, intent="doc", lang=lang)

    def _send_minutes(self, chat_id: int, user: AuthUser, meeting_id: str, view: dict[str, Any], lang: str,
                      holder: int | None, fmt: str = "docx") -> None:
        """Tayyor bayonnoma shu chatga: odam tanlagan formatdagi BITTA fayl (`fmt`: Word yoki PDF, izohi bilan;
        ega qarori 2026-11-13 - ikkalasini chizish behuda), oxirida "⏳" o'rniga natija (`minutes_html`; `holder` yo'q
        - yangi xabar). Fayl ham, natija ham ostida «✏️ O'zgartirish» (formati bilan) va «💬 Savol berish»
        (`minutes_done_menu`) va xotirada ("doc", til): ularga javob (Reply) - shu hujjat tilida chat, tahrir fayli shu
        formatda, qayta ishga tushgandan keyin ham (`p:w` tugmasidan)."""
        fmt = fmt if fmt in MINUTES_FORMATS else "docx"
        self._set_format(chat_id, meeting_id, lang, fmt)
        done = minutes_done_menu(meeting_id, lang, fmt)
        # Fayl chizilmasa yoki yuborilmasa natija baribir yetib boradi, sabab natija ostida; hujjat omborda - formatni
        # qayta tanlash modelni chaqirmaydi.
        notes: list[str] = []
        label = "Word" if fmt == "docx" else "PDF"
        try:
            data, media, disposition = minutes.export_file(user, meeting_id, view["id"], fmt)
        except (MeetingProblem, intake.Problem) as exc:
            notes.append(esc(f"{label} fayli tayyorlanmadi: {getattr(exc, 'detail', exc)}"))
            data = None
        except Exception:  # noqa: BLE001
            log.exception("Telegram Plaud bayonnomasi (%s): %s fayli", meeting_id, fmt)
            notes.append(f"{label} fayli tayyorlanmadi: ichki xato.")
            data = None
        if data is not None:
            name = intake.filename(disposition) or f"bayonnoma.{fmt}"
            try:
                sent = self.api.send_document(chat_id, name, data, media or "application/octet-stream",
                                              caption=MINUTES_CAPTION if fmt == "docx" else MINUTES_PDF_CAPTION,
                                              reply_markup=done)
            except TelegramError as exc:
                log.warning("Telegram Plaud: bayonnoma %s yuborilmadi: %s", fmt, exc)
                self._send(chat_id, f"Faylni yuborib bo'lmadi ({label}) - til va formatni qaytadan tanlang.")
            else:
                self._remember(chat_id, _message_id(sent), meeting_id, intent="doc", lang=lang)
                archive.record("telegram", "out", "document", chat=chat_id, actor=user.actorId, data=data, name=name,
                               mime=media or "", meta={"meeting": meeting_id, "minutes": view["id"], "lang": lang})
        text = minutes_html(view, lang)
        if notes:
            text += "\n" + "\n".join(f"⚠ {note}" for note in notes)
        for message_id in self._replace(chat_id, holder, text, markup=done, marker=ask_menu(meeting_id)):
            self._remember(chat_id, message_id, meeting_id, intent="doc", lang=lang)

    # --- yordamchilar ------------------------------------------------------------------------

    def _submit(self, user: AuthUser, job: Callable[[], None]) -> None:
        def run() -> None:
            # Hisob: shu odam va `bot` kanali bilan (ip o'zgaradi - kontekst qayta bog'lanadi).
            with bind(user.actorId, "bot"):
                try:
                    job()
                except Exception:  # noqa: BLE001
                    log.exception("Telegram Plaud: ish bajarilmadi")

        if self._pool is None:
            run()
            return
        try:
            self._pool.submit(run)
        except RuntimeError:
            pass  # to'xtatilmoqda

    def stop(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def _remember(self, chat_id: int, message_id: int | None, meeting_id: str, *, intent: str | None = None,
                  lang: str | None = None) -> None:
        """(chat, xabar) -> yig'ilish (`_messages`) va niyat (`_intents`: "note" / "revise" / "doc" va hujjat tili).
        Keyingi eslash avvalgisini almashtiradi: niyatsiz eslangan xabar - oddiy (masalan "⏳" chat javobiga
        aylandi). Ikkala xarita ham FIFO, `_REMEMBER` tagacha."""
        if message_id is None:
            return
        key = (chat_id, message_id)
        with self._lock:
            self._messages[key] = meeting_id
            if intent:
                self._intents[key] = (intent, lang)
            else:
                self._intents.pop(key, None)
            for memory in (self._messages, self._intents):
                while len(memory) > _REMEMBER:
                    memory.popitem(last=False)

    def _set_format(self, chat_id: int, meeting_id: str, lang: str, fmt: str) -> None:
        """Odam shu chatda shu yozuvning shu til hujjati uchun tanlagan fayl formati (`_formats`, FIFO)."""
        if fmt not in MINUTES_FORMATS:
            return
        with self._lock:
            self._formats[(chat_id, meeting_id, lang)] = fmt
            self._formats.move_to_end((chat_id, meeting_id, lang))
            while len(self._formats) > _REMEMBER:
                self._formats.popitem(last=False)

    def _format_of(self, chat_id: int, meeting_id: str, lang: str) -> str:
        """Tahrir fayli formati: odam tanlagani (`_set_format`), yo'q bo'lsa - Word (asosiy hujjat)."""
        with self._lock:
            return self._formats.get((chat_id, meeting_id, lang), "docx")

    def _send(self, chat_id: int, text: str, *, markup: dict[str, Any] | None = None,
              reply_to: Any = None) -> int | None:
        """HTML xabar; Telegram belgilashni rad etsa - teglarsiz qayta (`runner._send` kabi)."""
        reply = reply_to if isinstance(reply_to, int) else None
        try:
            sent = self.api.send_message(chat_id, text, reply_markup=markup, reply_to=reply)
        except TelegramError as exc:
            if not exc.bad_markup:
                log.warning("Telegram Plaud: xabar yuborilmadi: %s", exc)
                return None
            try:
                sent = self.api.send_message(chat_id, render.plain(text), html=False, reply_markup=markup,
                                             reply_to=reply)
            except TelegramError as again:
                log.warning("Telegram Plaud: xabar yuborilmadi: %s", again)
                return None
        return _message_id(sent)

    def _replace(self, chat_id: int, holder: int | None, text: str, *, markup: dict[str, Any] | None = None,
                 marker: dict[str, Any] | None = None) -> list[int]:
        """"⏳ ..." xabarini natija bilan almashtiradi; sig'masa qolgani - yangi xabarlarda. `markup`
        (tugmalar) - OXIRGI xabarda, `marker` - qolganlarida (bir necha bo'lak bo'lsa "⏳" o'rnidagisida ham):
        qayta ishga tushgandan keyin istalgan bo'lakka javob (Reply) yig'ilishni tugmadan topsin.
        Tahrir o'tmasa, birinchi bo'lak yangi xabar bo'lib ketadi. Qaytaradi: natija turgan xabarlar."""
        pages = render.pack([text])
        ids: list[int] = []
        for n, page in enumerate(pages):
            keys = markup if n == len(pages) - 1 else marker
            if n == 0 and holder is not None:
                try:
                    self.api.edit_message_text(chat_id, holder, page, reply_markup=keys)
                    ids.append(holder)
                    continue
                except TelegramError as exc:
                    if not exc.not_modified:
                        log.debug("Telegram Plaud: xabar yangilanmadi: %s", exc)
            sent = self._send(chat_id, page, markup=keys)
            if sent is not None:
                ids.append(sent)
        return ids

    def _delete(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            self.api.delete_message(chat_id, message_id)
        except TelegramError as exc:
            log.debug("Telegram Plaud: xabar o'chirilmadi: %s", exc)

    def _menu(self, chat_id: int, message_id: Any, markup: dict[str, Any] | None) -> None:
        if not isinstance(message_id, int):
            return
        try:
            self.api.edit_reply_markup(chat_id, message_id, markup)
        except TelegramError as exc:
            if not exc.not_modified:
                log.debug("Telegram Plaud: tugmalar almashtirilmadi: %s", exc)

    def _clear(self, chat_id: int, message_id: Any) -> None:
        self._menu(chat_id, message_id, None)

    def _answer(self, cq_id: str, text: str = "", *, alert: bool = False) -> None:
        if not cq_id:
            return
        try:
            self.api.answer_callback(cq_id, text, alert=alert)
        except TelegramError as exc:
            log.debug("Telegram Plaud: tugma javobi: %s", exc)


# --- tugmalar (sof funksiyalar) ------------------------------------------------------------------


def _btn(text: str, data: str) -> dict[str, str]:
    return {"text": text, "callback_data": data}


def _message_id(sent: Any) -> int | None:
    """Telegram javobidagi xabar id si (`sendMessage`, `sendDocument`); yo'q yoki g'alati bo'lsa - `None`."""
    found = sent.get("message_id") if isinstance(sent, dict) else None
    return found if isinstance(found, int) else None


def _marks(message: dict[str, Any]) -> tuple[str, str | None, str | None] | None:
    """Xabar tugmalaridagi yig'ilish belgisi (`_MARK` - birinchi mos tugma) va - shu yig'ilishning «✏️ O'zgartirish»
    tugmasi (`p:w:<id>:<til>[:<format>]`) bo'lsa - bayonnoma tili va fayl formati; belgisiz xabar - `None`."""
    meeting_id, edit = None, None
    for row in (message.get("reply_markup") or {}).get("inline_keyboard") or []:
        for button in row:
            data = str(button.get("callback_data") or "")
            marked = _MARK.match(data)
            if marked and meeting_id is None:
                meeting_id = marked.group(1)
            found = _EDIT_DATA.match(data)
            if found and edit is None and found.group(2) in minutes.LANGS:
                edit = found.groups()
    if meeting_id is None:
        return None
    if edit and edit[0] == meeting_id:
        return meeting_id, edit[1], edit[2]
    return meeting_id, None, None


def controls(meeting_id: str, language: str, *, retry: str | None = None) -> dict[str, Any]:
    rows = [[_btn(BTN_ASK, f"p:q:{meeting_id}")],
            [_btn("✅ Vazifalar", f"p:t:{meeting_id}"), _btn("📎 Eksport", f"p:e:{meeting_id}")],
            [_btn("🌐 Boshqa til", f"p:l:{meeting_id}")],
            [_btn("📄 Bayonnoma", f"p:d:{meeting_id}")]]
    if retry:
        rows.append([_btn("🔁 Xulosani qayta urinish", retry)])
    return {"inline_keyboard": rows}


def chat_menu(meeting_id: str) -> dict[str, Any]:
    """Chat javobi ostida: yana savol (ForceReply so'rovi) va yangi suhbat (`service.chat_reset`)."""
    return {"inline_keyboard": [[_btn("💬 Yana savol", f"p:q:{meeting_id}"),
                                 _btn("🔄 Yangi suhbat", f"p:n:{meeting_id}")]]}


def ask_menu(meeting_id: str) -> dict[str, Any]:
    """«💬 Savol berish» tugmasi: "Yangi suhbat boshlandi" ostida (birinchi savol shu tugmadan), uzun chat
    javobining oxirgisidan boshqa bo'laklarida, xato xabarida va ovozli savolning "🎙 matn"ida - yig'ilish
    belgisi ham (`_MARK`)."""
    return {"inline_keyboard": [[_btn(BTN_ASK, f"p:q:{meeting_id}")]]}


def export_menu(meeting_id: str) -> dict[str, Any]:
    items = [_btn(title, f"p:e:{meeting_id}:{kind}") for kind, title in EXPORTS]
    return {"inline_keyboard": [items[:2], items[2:3], items[3:], [_btn("⬅ Orqaga", f"p:b:{meeting_id}")]]}


def lang_menu(meeting_id: str, language: str) -> dict[str, Any]:
    rows = [[_btn(f"{LANG_FLAGS[lang]} {name.capitalize()} tilida qayta o'girish", f"p:l:{meeting_id}:{lang}")]
            for lang, name in LANG_NAMES.items() if lang != language]
    return {"inline_keyboard": rows + [[_btn("⬅ Orqaga", f"p:b:{meeting_id}")]]}


def confirm_menu(meeting_id: str, lang: str) -> dict[str, Any]:
    """Tasdiq: qayta o'girish GAPI daqiqalarini yana sarflaydi va eski transkript hamda
    xulosani almashtiradi (`service.retranscribe`)."""
    return {"inline_keyboard": [
        [_btn(f"✅ {LANG_NAMES[lang].capitalize()} tilida o'girish (daqiqalar qayta sarflanadi)",
              f"p:l:{meeting_id}:{lang}:y")],
        [_btn("⬅ Bekor qilish", f"p:l:{meeting_id}")]]}


def minutes_menu(meeting_id: str, language: str) -> dict[str, Any]:
    """Bayonnoma tili tugmalari (`minutes.LANGS`), har biri o'z qatorida: tavsiya etilgani
    (yig'ilish tilidan `minutes.default_lang` - bank hujjati odatda kirillda) BIRINCHI, lekin
    tanlov odamniki (ega qarori, 2026-11-04). Tillardan keyin - «✍️ Ko'rsatma berish» (yozishdan oldin
    ko'rsatma, 2026-11-12), oxirida - orqaga."""
    default = minutes.default_lang(language)
    order = [default] + [lang for lang in minutes.LANGS if lang != default]
    rows = [[_btn(minutes.LANG_TITLES[lang], f"p:d:{meeting_id}:{lang}")] for lang in order]
    return {"inline_keyboard": rows + [[_btn(BTN_GUIDE, f"p:g:{meeting_id}")],
                                       [_btn("⬅ Orqaga", f"p:b:{meeting_id}")]]}


def minutes_format_menu(meeting_id: str, lang: str) -> dict[str, Any]:
    """Til tanlangandan keyin format (ega qarori 2026-11-13): «📄 Word» (asosiy - kotib «________» joylarini shu faylda
    to'ldiradi), «📕 PDF» va orqaga - til menyusiga (`p:d:<id>`)."""
    return {"inline_keyboard": [[_btn("📄 Word", f"p:d:{meeting_id}:{lang}:docx")],
                                [_btn("📕 PDF", f"p:d:{meeting_id}:{lang}:pdf")],
                                [_btn("⬅ Orqaga", f"p:d:{meeting_id}")]]}


def minutes_done_menu(meeting_id: str, lang: str, fmt: str | None = None) -> dict[str, Any]:
    """Tayyor bayonnoma (fayl, natija xabari) ostida: shu til hujjatini o'zgartirish (`p:w` - ForceReply so'rovi)
    va yozuv bo'yicha savol. `p:w:<id>:<til>[:<format>]` - qayta ishga tushgandan keyin ham javob (Reply) uchun belgi,
    til va tahrir fayli formati."""
    edit = f"p:w:{meeting_id}:{lang}" + (f":{fmt}" if fmt in MINUTES_FORMATS else "")
    return {"inline_keyboard": [[_btn(BTN_EDIT, edit)],
                                [_btn(BTN_ASK, f"p:q:{meeting_id}")]]}


def note_menu(meeting_id: str) -> dict[str, Any]:
    """Ko'rsatma eslab qolingandan keyin: bayonnomani tayyorlash (til menyusi) va chat tugmalari (`chat_menu`)."""
    return {"inline_keyboard": [[_btn("📄 Bayonnoma tayyorlash", f"p:d:{meeting_id}")],
                                *chat_menu(meeting_id)["inline_keyboard"]]}


# --- matn (sof funksiyalar) ---------------------------------------------------------------------


def title_of(media: dict[str, Any], recorded_at: float) -> str:
    """Yig'ilish sarlavhasi: fayl nomi yoki ovozli xabar vaqti (Toshkent)."""
    if media["kind"] == "voice":
        when = datetime.fromtimestamp(recorded_at, _TASHKENT).strftime("%d.%m.%Y %H:%M")
        return f"Telegram: ovozli xabar {when}"
    name = export.one_line(media.get("title") or media.get("file_name")) or ("video" if media.get("video") else "audio")
    return f"Telegram: {name}"


def html_of(markdown: str) -> str:
    """Xulosa markdown'i -> Telegram HTML (`render.to_blocks`: sarlavha, ro'yxat, jadval)."""
    return "\n\n".join(render.to_blocks(markdown))


def ask_prompt(title: Any) -> str:
    """"💬 Savol berish" so'rovi (HTML): yozuv nomi (bir qator, 80 belgigacha) va chat qoidasi."""
    name = export.one_line(title, 80) or "Yozuv"
    return (f"💬 <b>{esc(name)}</b> bo'yicha {_PROMPT_MARK}.\n"
            "Barno faqat shu yozuv matni va xulosasiga tayanadi va suhbatni eslab qoladi - keyingi savolni "
            "javobga «Reply» qilib yozing.")


def guide_prompt(title: Any) -> str:
    """«✍️ Ko'rsatma berish» so'rovi (HTML): yozuv nomi (bir qator, 80 belgigacha) va nima yozish mumkinligi."""
    name = export.one_line(title, 80) or "Yozuv"
    return (f"✍️ <b>{esc(name)}</b> {_GUIDE_MARK}.\n"
            "Nimaga e'tibor berish, rais va qatnashchilar, tuzilma, atamalar - matn yoki ovozli xabar bilan javob "
            "(Reply) qilib yozing. Keyin «📄 Bayonnoma» tugmasidan hujjat tili va formatini tanlang.")


def edit_prompt(title: Any, lang: str) -> str:
    """«✏️ O'zgartirish» so'rovi (HTML): yozuv nomi, hujjat tili va so'rov namunalari."""
    name = export.one_line(title, 80) or "Yozuv"
    return (f"✏️ <b>{esc(name)}</b> bayonnomasida ({esc(minutes.LANG_TITLES.get(lang, lang))}) {_EDIT_MARK}?\n"
            "Yozing yoki ovozli xabar yuboring, masalan: «3-bandda muddat 1-dekabr bo'lsin», «raisni Alisher Karimov "
            "deb yozing». Barno faqat so'ralgan joyni o'zgartiradi va yangi faylni shu formatda yuboradi.")


#: So'rov turi -> (matn boshidagi emoji, belgi). Emoji o'zgarish tanlagichisiz (U+FE0F) solishtiriladi.
_PROMPTS = (("ask", "💬", _PROMPT_MARK), ("note", "✍", _GUIDE_MARK), ("revise", "✏", _EDIT_MARK))


def prompt_kind(message: dict[str, Any]) -> str | None:
    """Botning ForceReply so'rovi turi: «💬 Savol berish» - "ask", «✍️ Ko'rsatma berish» - "note", «✏️ O'zgartirish»
    - "revise"; boshqa xabar (odamniki ham) - `None`. Telegram javobdagi xabarni teglarsiz beradi."""
    if not (message.get("from") or {}).get("is_bot"):
        return None
    text = str(message.get("text") or "")
    return next((kind for kind, head, mark in _PROMPTS if text.startswith(head) and mark in text), None)


def is_prompt(message: dict[str, Any]) -> bool:
    """Botning ForceReply so'rovimi (`prompt_kind`): savol, ko'rsatma yoki o'zgartirish."""
    return prompt_kind(message) is not None


def speakers_of(view_speakers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`person_id` - ismsiz, lekin ovozi tanilgan spiker «Noma'lum #N» bo'lib chiqsin (`export.speaker_name`)."""
    return {sp["id"]: {"name": sp.get("name"), "merged_into": sp.get("mergedInto"), "person_id": sp.get("personId")}
            for sp in view_speakers}


def clock(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, rest = divmod(total, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def tasks_html(items: list[dict[str, Any]], people: dict[str, dict[str, Any]], lang: str) -> str:
    """Vazifalar: ish, mas'ul, muddat; bajarilgani `✓`, ishonchsizi belgilangan."""
    lines = []
    for item in items:
        task = export.one_line(item.get("task"))
        if not task or item.get("status") == "dismissed":
            continue
        owner = item.get("owner") or {}
        who = export.one_line(owner.get("name")) or (
            export.speaker_name(owner.get("speaker"), people, lang) if owner.get("speaker") else "")
        due = item.get("due") or {}
        when = export.one_line(due.get("raw")) or " ".join(x for x in (due.get("date"), due.get("time")) if x)
        details = [f"Mas'ul: {esc(who)}" if who else "", f"Muddat: {esc(when)}" if when else ""]
        line = ("✓ " if item.get("status") == "done" else "") + esc(task)
        if any(details):
            line += " - " + " · ".join(d for d in details if d)
        if item.get("needsConfirmation"):
            line += " <i>(aniqlashtirish kerak)</i>"
        lines.append(f"• {line}")
    return "\n".join(lines)


def minutes_html(view: dict[str, Any], lang: str) -> str:
    """Tayyor bayonnoma haqida xabar (Slack `render.minutes_result` ning Telegram HTML ko'rinishi; loyiha eslatmasi -
    Word faylining izohida, `MINUTES_CAPTION`): sarlavha (`_minutes_head`), o'zgartirish so'rovi va o'zgarishlar
    (`_changes_line`), modelning izohlari (aniqlashtirish kerak) va sifat ogohlantirishlari - `ungrounded_name:<ism>`
    (transkriptda bo'lmagan ism `BLANK` bo'ldi), `script_mismatch` (yozuv tanlangan tilga mos emas) va
    `_warning_lines` dagilari. Boshqa ogohlantirish kodlari odamga ko'rsatilmaydi. Versiya kalitlari `.get()` bilan:
    eski (soxta) ko'rinishda ular yo'q - matn avvalgidek."""
    request = export.one_line(view.get("request"), 200)
    parts = [_minutes_head(view, lang, request)]
    if request:
        parts.append(f"So'rov: «{esc(request)}»")
    changed = _changes_line(view, request)
    if changed:
        parts.append(changed)
    notes = [esc(export.one_line(n)) for n in view.get("notes") or [] if export.one_line(n)]
    if notes:
        parts.append("❗ <b>Aniqlashtirish kerak:</b>\n" + "\n".join(f"• {n}" for n in notes))
    warnings = [str(w) for w in view.get("warnings") or []]
    names = [esc(w.split(":", 1)[1].strip()) for w in warnings if w.startswith("ungrounded_name:")]
    if any(names):
        parts.append(f"Transkriptda bo'lmagan ismlar «{minutes.BLANK}» bilan almashtirildi: "
                     + ", ".join(dict.fromkeys(n for n in names if n)))
    if "script_mismatch" in warnings:
        parts.append("Hujjat yozuvi (kirill/lotin) tanlangan tilga to'liq mos kelmadi - matnni ko'zdan kechiring.")
    return "\n\n".join(parts + _warning_lines(warnings))


def _minutes_head(view: dict[str, Any], lang: str, request: str) -> str:
    """Natija sarlavhasi: o'zgartirish so'rovi bo'yicha tahrir - "tahrirlandi", ko'rsatmalar qo'llangan tahrir -
    "yangilandi" (ikkalasi versiyasi bilan), asl hujjat - "tayyor" (berilgan ko'rsatmalar soni bilan)."""
    title = esc(minutes.LANG_TITLES.get(lang, lang))
    count = f"{int(view.get('sectionCount') or 0)} bo'lim, {int(view.get('itemCount') or 0)} band."
    version = int(view.get("version") or 1)
    if view.get("kind") == "revise" and request:
        return f"✅ <b>Bayonnoma tahrirlandi</b> ({title}, {version}-versiya): {count}"
    if view.get("kind") == "revise":
        return f"✅ <b>Bayonnoma yangilandi</b> ({title}, {version}-versiya): ko'rsatmalaringiz qo'llandi - {count}"
    applied = int(view.get("notesApplied") or 0)
    return f"✅ <b>Bayonnoma tayyor</b> ({title}): {count}" + (
        f" Ko'rsatmalaringiz hisobga olindi ({applied} ta)." if applied else "")


def _changes_line(view: dict[str, Any], request: str) -> str:
    """Tahrirda ota-versiyaga nisbatan o'zgarishlar (`diff.summary_uz`); ko'rsatmalar tahriri matnni o'zgartirmagan
    bo'lsa - shu haqda izoh; asl hujjatda - bo'sh."""
    changes = view.get("changes")
    if view.get("kind") != "revise" or not isinstance(changes, dict):
        return ""
    summary = minutes.diff.summary_uz(changes)
    if summary:
        return f"<b>O'zgarishlar:</b> {esc(summary)}."
    return "" if request else "Ko'rsatmalar bayonnomada allaqachon aks etgan - matn o'zgarmadi."


def _warning_lines(warnings: list[str]) -> list[str]:
    """Ko'rsatmalar bilan bog'liq ogohlantirishlar: `header_dropped:<kalit>` (ko'rsatmada aniq aytilmagan sarlavha
    qiymati bo'sh qoldi), `superseded_revisions:<n>` (matn tahrirlangani uchun hujjat yangidan yozildi - avvalgi
    o'zgartirishlar kirmadi), `guidance_truncated:<n>` (eng eski ko'rsatmalar sig'madi)."""
    out: list[str] = []
    dropped = [w.split(":", 1)[1].strip() for w in warnings if w.startswith("header_dropped:")]
    if dropped:
        names = dict.fromkeys(minutes.diff.HEADER_NAMES_UZ.get(key, key) for key in dropped)
        out.append(f"Ko'rsatmada aniq aytilmagan sarlavha qiymatlari bo'sh qoldirildi: {esc(', '.join(names))}.")
    superseded = _counted(warnings, "superseded_revisions:")
    if superseded:
        out.append(f"⚠ Matn tahrirlangani uchun bayonnoma yangidan yozildi - avvalgi {superseded} ta o'zgartirish "
                   "kiritilmagan, kerak bo'lsa qayta yozing.")
    truncated = _counted(warnings, "guidance_truncated:")
    if truncated:
        out.append(f"⚠ Ko'rsatmalar juda ko'p - eng eskilaridan {truncated} tasi hisobga olinmadi.")
    return out


def _counted(warnings: list[str], prefix: str) -> int:
    """`<prefix><n>` ogohlantirishidagi son (yo'q yoki son emas - 0)."""
    for warning in warnings:
        if warning.startswith(prefix):
            try:
                return max(0, int(warning[len(prefix):]))
            except ValueError:
                return 0
    return 0


def minutes_note(ref: dict[str, Any] | None) -> str:
    """Chat javobi ostidagi bayonnoma qatori (HTML; navbatning `minutes`i): ko'rsatma navbati - nechta ko'rsatma
    eslab qolingani (`NOTE_SAVED`), ish boshlanmagan bo'lsa (`error` bor, `id` yo'q) - sababi; qolganida - bo'sh."""
    if not ref:
        return ""
    if ref.get("action") == "note":
        return "\n\n" + esc(NOTE_SAVED.format(n=ref.get("notes") or 1))
    error = ref.get("error") if isinstance(ref.get("error"), dict) else None
    if error and not ref.get("id"):
        return "\n\n⚠ " + esc(error.get("message") or "Bayonnoma ishi boshlanmadi.")
    return ""


def answer_html(found: dict[str, Any], people: dict[str, dict[str, Any]], lang: str) -> str:
    """Yig'ilish bo'yicha javob: matn, manbalar (vaqt belgisi bilan) va keyingi savollar."""
    parts = [html_of(export.render_tokens(found.get("answer") or "", people, lang))]
    cites = []
    for cite in (found.get("citations") or [])[:5]:
        who = export.speaker_name(cite.get("speaker"), people, lang) if cite.get("speaker") else ""
        quote = esc(export.one_line(cite.get("text"))[:200])
        cites.append(f"• <code>{clock(cite.get('start'))}</code> {esc(who) + ': ' if who else ''}«{quote}»")
    if cites:
        parts.append("📌 <b>Manbalar:</b>\n" + "\n".join(cites))
    follow = [f"• {esc(export.one_line(q))}" for q in (found.get("followUps") or [])[:3] if q]
    if follow:
        parts.append("❓ <b>Yana so'rash mumkin:</b>\n" + "\n".join(follow))
    return "\n\n".join(p for p in parts if p)

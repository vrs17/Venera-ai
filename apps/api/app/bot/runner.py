"""Telegram bot: xabarlarni olish (long polling) va javob berish.

OQIM (bitta savol):

    xabar/ovoz -> [ovoz bo'lsa: fayl -> STT -> "🎙 matn"] -> "⏳" xabari
      -> yuqoridagi xizmat oqimi (bosqich matni "⏳" da ko'rinadi)
      -> "⏳" o'chiriladi, javob YANGI xabar bo'lib keladi (bildirishnoma
         bilan - javob 15-40 s oladi va odam boshqa ishga o'tgan bo'ladi)
      -> manbalar tugmalari, taklif kartasi, ariza fayli

XABAR QANDAY KELADI. Ikki rejim (`settings.telegram_mode`):

  * `polling` - bot o'zi so'raydi (`getUpdates`, chiquvchi ulanish). JONLI
    TIZIMDA SHU. Boshqa nusxa shu tokenni o'qisa (409) - ulanish DARHOL
    qaytarib olinadi (`poll_error`).
  * `webhook` - Telegram xabarni o'zi `/api/v1/telegram/webhook` ga yuboradi
    va boshqa `getUpdates` o'quvchilarni rad etadi. O'LCHANGAN (2026-09-24):
    Telegram'ning serverimizga ulanishi ko'pincha birinchi urinishda
    "Connection timed out" bo'ladi va xabar 20 s - 2 daqiqa kechikadi
    (ovozli savol: yetkazish ~80 s, GAPI 1.6 s, javob 7 s). Tarmoq yo'li
    Venera'dan tashqarida - shuning uchun jonli tizim `polling` da. Webhook
    kodi qoladi: tarmoq tuzatilsa `.env` dagi bitta qator bilan yoqiladi.

NAVBAT. Bitta odamning xabarlari KETMA-KET ishlanadi (tartib saqlanadi:
`/new` dan keyingi savol haqiqatan yangi suhbatga tushadi), turli odamlar
esa parallel - `telegram_workers` ta ipgacha. Tugma bosishlar navbatsiz:
"Tasdiqlash" savol javobini kutib turmasligi kerak.

XATOLAR odamga veb ilovadagi xabarlar bilan aytiladi (`chat._MESSAGES`,
`stt._MESSAGES`, `actions._MESSAGES`) - ichki manzil yoki sir chiqmaydi.

KIRISH FAQAT MATN VA OVOZ (mikrofon). Video (kamera: dumaloq video, video
fayl) QABUL QILINMAYDI: yuklab olinmaydi, ko'rilmaydi va chatdan darhol
o'chiriladi. Kamera tugmasini Telegram ilovasi boshqaradi - bot uni
yashira olmaydi, shaxsiy chatda media cheklovi ham yo'q (`setChatPermissions`
faqat guruhlar uchun). Bot qila oladigani - qabul qilmaslik va o'chirish.

JURNAL: savol, transkript va javob MATNI yozilmaydi (shaxsiy ma'lumot) -
faqat `actorId`, uzunlik va natija.

ADMIN PANEL IZI esa veb chatdagi bilan bir xil (`services/analytics`):
har savol `turns` ga kanal `bot`, tur `bot` bilan yoziladi - kadrlar,
manbalar, vaqtlar va natija. Bu jurnal emas, ADMIN uchun ruxsatli ombor
(saqlash muddati `analytics_retention_days`).
"""

from __future__ import annotations

import json
import logging
import threading
import time

from collections import OrderedDict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services import admin_users
from ..services.analytics import TurnRecorder, bind, redact, set_proposal_status
from ..services.integrations.assistant import AssistantError
from ..services.integrations.telegram import TelegramApi, TelegramError
from ..services.stt import SttError, Transcript
from ..services.telegram_links import LinkStore, TelegramLink
from ..services.identities import Directory
from ..services.users import UserStore
from . import render
from .render import esc

log = logging.getLogger(__name__)

#: Bitta odamning navbatidagi eng ko'p xabar. Undan ortig'iga "kuting".
_QUEUE_LIMIT = 3
#: Ulanmagan odamga ko'rsatma shundan tez-tez takrorlanmaydi (soniya).
_HINT_EVERY = 60.0
#: "Faqat matn va ovoz" izohi shundan tez takrorlanmaydi: albomdagi o'nta
#: video o'nta izoh bo'lmasin (har biri baribir o'chiriladi).
_NOTE_EVERY = 10.0
#: Webhook holati shu oraliqda tekshiriladi (soniya).
_WEBHOOK_CHECK = 60.0
#: Telegram webhook'ga shuncha KETMA-KET tekshiruv davomida yetib bora
#: olmasa (yangi xato va navbatda xabar bor) - `polling` ga qaytiladi. 5
#: daqiqa: qayta ishga tushish paytidagi bir necha soniyalik uzilish buni
#: qo'zg'atmaydi - Telegram keyingi urinishda baribir yetkazadi.
_WEBHOOK_FAILS = 5
#: Telegram javobni olmay qolsa yangilanishni QAYTA yuboradi - shuncha
#: oxirgi `update_id` eslab qolinadi va takrori tashlanadi.
_SEEN_UPDATES = 2000
#: Bot faqat shu turdagi yangilanishlarni oladi.
ALLOWED_UPDATES = ["message", "callback_query"]
#: Boshqa nusxa bilan to'qnashuvda (409) qayta so'rash oralig'i. Ikkinchi
#: nusxa har to'qnashuvdan keyin ~30 s kutadi, biz esa DARHOL qaytamiz - u
#: ulanishni atigi bir necha yuz millisekund ushlab turadi. Nol emas: u ham
#: darhol qaytsa, ikkalasi tarmoqni bosib qo'ymasin.
_CONFLICT_RETRY = 0.1
#: Bir daqiqada shundan ko'p to'qnashuv - ikkinchi nusxa ham shoshyapti:
#: sekinlashamiz (baribir yutib bo'lmaydi, faqat tarmoq to'ladi).
_CONFLICT_BURST = 30
_CONFLICT_SLOW = 2.0
#: "⏳" xabaridagi bosqich matni shundan tez yangilanmaydi.
_STAGE_EVERY = 1.5
#: "yozmoqda..." holati 5 s yashaydi - shundan oldin yangilanadi.
_TYPING_EVERY = 4.5
_TYPING_LIMIT = 180.0
#: Ariza fayli uchun chegara (`assistant._MAX_FILE_BYTES` bilan bir xil):
#: undan katta fayl u yerda JIMGINA kesiladi, kesilgan hujjat yuborilmaydi.
_MAX_FILE = 25 * 1024 * 1024

#: Bot menyusidagi buyruqlar. `/start` ro'yxatda yo'q - uni Telegram o'zi
#: yuboradi.
COMMANDS = [
    {"command": "new", "description": "Yangi suhbat boshlash"},
    {"command": "app", "description": "Venera ilovasini ochish"},
    {"command": "help", "description": "Yordam"},
    {"command": "logout", "description": "Hisobni botdan uzish"},
]

_INTRO = (
    "Salom! Men <b>Venera</b> - HRM va CRM bo'yicha yordamchiman.\n\n"
    "Shu chatda ishlash uchun Venera hisobingizni ulang: pastdagi tugma bilan "
    "Venera ilovasini oching va kiring. Ulangach shu yerga xabar keladi."
)
_EXPIRED = (
    "Bot {days} kun ishlatilmagani uchun xavfsizlik maqsadida ulanish tugadi. "
    "Venera ilovasini ochib kiring - ulanish yangilanadi va shu yerda davom etasiz."
)
#: Admin panelda bloklangan hisob. Sabab va kim bloklagani AYTILMAYDI -
#: faqat nima qilish kerakligi.
_BLOCKED = "Hisobingiz bloklangan. Administratorga murojaat qiling."
_HELP = (
    "<b>Venera</b> - HRM va CRM bo'yicha yordamchi.\n\n"
    "• Savolni yozing yoki 🎙 ovozli xabar yuboring - javobni matn bilan beraman.\n"
    "• Faqat matn va ovoz: video (kamera) qabul qilinmaydi va chatdan o'chiriladi.\n"
    "• HRM yoki CRM da biror narsani o'zgartirish kerak bo'lsa, avval taklif "
    "ko'rsataman: faqat <b>Tasdiqlash</b> ni bossangiz bajariladi.\n"
    "• Hujjat tayyorlansa, faylning o'zini shu yerga yuboraman.\n"
    "• Suhbatlar veb ilova va mini app tarixida ham ko'rinadi.\n\n"
    "/new - yangi suhbat\n"
    "/app - Venera ilovasini ochish\n"
    "/logout - hisobni botdan uzish"
)


def welcome_text(user: AuthUser, *, again: bool = False) -> str:
    """Ulangandan keyingi birinchi xabar (`again` - `/start` da takror)."""
    head = "Hisobingiz ulangan" if again else "Venera hisobingiz ulandi"
    return (
        f"✅ {head}: <b>{esc(user.fullName or user.email)}</b>\n\n"
        "Endi shu chatda savol yozing yoki 🎙 ovozli xabar yuboring - HRM va CRM "
        "bo'yicha javobni shu yerda beraman.\n\n"
        "/new - yangi suhbat · /help - yordam"
    )


class Backend:
    """Bot ishlatadigan xizmatlar - API endpointlari ishlatadigan AYNI nusxalar.

    NEGA ALOHIDA NUSXA EMAS. CRM agent sessiyasi va foydalanuvchi
    ulanishlari `refresh_token` ni ROTATSIYA qiladi: ikkinchi nusxa
    birinchisining tokenini bekor qilib qo'yardi (`chat._crm` izohi). Yuqori
    xizmat va STT navbatlari (semaforlar) ham umumiy bo'lishi kerak - bot
    veb ilovaning ulushini ikki baravar qilib yubormasin.

    Testlar shu sinfni soxtasi bilan almashtiradi.
    """

    def stream(self, question: str, user: AuthUser, chat_id: str):
        from ..api.v1 import chat as _chat

        # Web va mini app bilan BITTA yo'l: xodimlar ma'lumotnomasi, keyin yordamchi.
        # Dvigatel - SHU ODAMNING `bot` kanalidagisi (`effective_engine`):
        # admin unga alohida versiya bergan bo'lsa o'sha, bo'lmasa bot
        # kanali siyosati, oxiri `.env`. Botda tanlov tugmasi yo'q - odam
        # o'z default'ida. "Pro" botda yo'q.
        return _chat.open_stream(question, user, chat_id, channel="bot")

    def engine(self, user: AuthUser | None = None) -> str:
        """Bot kanalining dvigateli (shu odam uchun) - savol izi uchun
        (`_collect`). Odamsiz - "hamma uchun" qiymat."""
        from ..api.v1 import chat as _chat

        return _chat.effective_engine(user, "bot")

    def action(self, verb: str, token: str, user: AuthUser) -> dict[str, Any]:
        from ..api.v1 import chat as _chat
        from ..services import contacts_chat

        if contacts_chat.owns(token):
            return contacts_chat.act(verb, token, user)
        call = _chat._assistant.confirm_action if verb == "confirm" else _chat._assistant.cancel_action
        return call(token, user_id=_chat.assistant_user_id(user), tokens=_chat._live_tokens(user))

    def artifact(self, token: str, kind: str):
        from ..api.v1 import chat as _chat

        return _chat._assistant.fetch_artifact(token, kind)

    def doc(self, doc_id: str):
        from ..api.v1 import chat as _chat

        return _chat._assistant.fetch_doc(doc_id)

    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        from ..api.v1 import stt as _stt

        # Ovozli xabar ham savol: veb ilovadagi `/stt/transcribe` bilan bir
        # xil tanlov va zahira (GAPI -> Router). Til - o'zbek: Telegram
        # interfeysi tili (`language_code`) ko'pincha ruscha yoki inglizcha,
        # gap esa o'zbekcha.
        return _stt._transcribe_with_fallback(
            _stt._pick("uz", settings.stt_provider), audio, "uz", content_type,
            yol="Telegram", budget=settings.stt_deadline,
        )


def _chat_message(status: int) -> str:
    from ..api.v1 import chat as _chat

    return _chat._MESSAGES.get(status, _chat._MESSAGES[502])


def _open_error_code(exc: AssistantError) -> str:
    """Ochilmagan oqim uchun izdagi xato kodi - veb chatdagi qoida."""
    from ..api.v1 import chat as _chat

    return _chat.open_error_code(exc)


def _stt_message(status: int) -> str:
    from ..api.v1 import stt as _stt

    return _stt._MESSAGES.get(status, _stt._MESSAGES[502])


def _action_message(status: int) -> str:
    from ..api.v1 import actions as _actions

    return _actions._MESSAGES.get(status, _actions._MESSAGES[502])


def _proposal_outcome(verb: str, result: dict[str, Any]) -> str | None:
    """Taklif holati izga - veb ilovadagi AYNI qoida (`actions.proposal_outcome`)."""
    from ..api.v1 import actions as _actions

    return _actions.proposal_outcome(verb, result)


def _assistant_proposal(token: str) -> bool:
    """Taklif holati (`turns.proposal_status`) faqat YORDAMCHI takliflari uchun
    yangilanadi - veb ilovadagi `/actions` bilan bir xil qoida. Xodimlar
    ma'lumotnomasi taklifi (`ct_`) Venera'ning o'zida bajariladi."""
    from ..services import contacts_chat

    return not contacts_chat.owns(token)


@dataclass
class _Answer:
    parts: list[str] = field(default_factory=list)
    docs: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    failure: str | None = None
    #: Savol izi uchun: oqim ochilmagan yoki o'rtada uzilgan bo'lsa - sababi.
    error: BaseException | None = None


class _Typing:
    """"yozmoqda..." - javob kelguncha har 4.5 soniyada."""

    def __init__(self, api: TelegramApi, chat_id: int, every: float | None) -> None:
        self.api = api
        self.chat_id = chat_id
        self.every = every
        self._stop = threading.Event()

    def start(self) -> "_Typing":
        if self.every:
            threading.Thread(target=self._run, name="tg-typing", daemon=True).start()
        return self

    def _run(self) -> None:
        deadline = time.monotonic() + _TYPING_LIMIT
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                self.api.send_chat_action(self.chat_id, "typing")
            except TelegramError:
                pass
            self._stop.wait(self.every)

    def stop(self) -> None:
        self._stop.set()


def is_video(msg: dict[str, Any]) -> bool:
    """Kamera/video xabari: dumaloq video, video, yoki fayl sifatidagi video."""
    if isinstance(msg.get("video_note"), dict) or isinstance(msg.get("video"), dict):
        return True
    document = msg.get("document")
    return isinstance(document, dict) and str(document.get("mime_type") or "").lower().startswith("video/")


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


class VeneraBot:
    """Bitta bot nusxasi. `handle_update` - sinxron (testlar shuni chaqiradi),
    `dispatch` - navbat orqali, `start` - so'rov ipi."""

    def __init__(
        self,
        api: TelegramApi,
        links: LinkStore,
        *,
        users: Callable[[], Directory | UserStore],
        backend: Backend | None = None,
        webapp_url: str = "",
        workers: int = 4,
        inline: bool = False,
        typing_every: float | None = _TYPING_EVERY,
        mode: str = "polling",
        webhook_url: str = "",
        webhook_secret: str = "",
    ) -> None:
        self.api = api
        #: Manzil yoki sir bo'lmasa webhook mumkin emas - `polling`.
        self.mode = "webhook" if mode == "webhook" and webhook_url and webhook_secret else "polling"
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self.links = links
        self.users = users
        self.backend = backend or Backend()
        self.webapp_url = webapp_url
        self.typing_every = typing_every
        self.username = ""
        self._inline = inline
        self._pool = None if inline else ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="tg-bot")
        self._queues: dict[int, deque[Callable[[], None]]] = {}
        self._running: set[int] = set()
        self._qlock = threading.Lock()
        self._hint_at: dict[int, float] = {}
        self._note_at: dict[int, float] = {}
        self._busy: set[str] = set()
        self._busy_lock = threading.Lock()
        #: Ariza kaliti -> sarlavha: "PDF" tugmasi bosilganda faylga nom
        #: berish uchun. Faqat xotirada - qayta ishga tushsa nom umumiy bo'ladi.
        self._titles: OrderedDict[str, str] = OrderedDict()
        self._titles_lock = threading.Lock()
        self._offset: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prepared = False
        self._state: dict[str, Any] = {"error": "", "error_at": None, "ok_at": None, "updates": 0,
                                       "note": ""}
        self._seen: OrderedDict[int, None] = OrderedDict()
        self._seen_lock = threading.Lock()
        self._webhook_set_at = 0.0
        self._webhook_fails = 0
        self._webhook: dict[str, Any] = {}
        #: 409 lar vaqti - boshqa nusxa shu tokenni o'qiyotganining izi.
        self._conflicts: deque[float] = deque(maxlen=2000)
        self._conflict_log_at = 0.0

    # --- so'rov ipi ---------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tg-bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def status(self) -> dict[str, Any]:
        """`/api/health/detail` uchun. Token va odamlar ro'yxati YO'Q."""
        return {
            "running": self.running,
            "username": self.username or None,
            "last_ok_at": _iso(self._state["ok_at"]),
            "error": self._state["error"] or None,
            "error_at": _iso(self._state["error_at"]),
            "updates": self._state["updates"],
            "mode": self.mode,
            "note": self._state["note"] or None,
            "webhook": dict(self._webhook) if self._webhook else None,
            #: Oxirgi 10 daqiqada boshqa nusxa bilan to'qnashuvlar (409).
            "conflicts_10min": sum(1 for t in list(self._conflicts) if time.time() - t <= 600),
        }

    def _run(self) -> None:
        if self.mode == "webhook":
            self._run_webhook()
        if not self._stop.is_set():
            # `polling` rejimi - yoki webhook ishlamay, zaxiraga qaytildi.
            self._run_polling()

    # --- webhook ----------------------------------------------------------------

    def _run_webhook(self) -> None:
        """Webhook'ni o'rnatadi va har daqiqada tekshiradi. Faqat to'xtatilganda
        yoki `polling` ga qaytish kerak bo'lganda chiqadi."""
        while not self._stop.is_set():
            if not self._prepared:
                self._prepare()
            try:
                if not self.check_webhook():
                    return
            except TelegramError as exc:
                self._state["error"] = str(exc)
                self._state["error_at"] = time.time()
                log.warning("Telegram webhook tekshirilmadi: %s", exc)
            except Exception:  # noqa: BLE001 - ip o'lmasligi kerak
                log.exception("Telegram webhook: kutilmagan xato")
            self._stop.wait(_WEBHOOK_CHECK)

    def check_webhook(self, *, now: float | None = None) -> bool:
        """Webhook o'z joyidami va Telegram unga yetib boryaptimi.

        `False` - Telegram uzoq vaqt yetib bora olmadi va webhook O'CHIRILDI:
        chaqiruvchi `polling` ga o'tadi (xabarlar Telegram navbatida kutib
        turgan - yo'qolmaydi).
        """
        now = time.time() if now is None else now
        info = self.api.get_webhook_info()
        url = str(info.get("url") or "")
        pending = int(info.get("pending_update_count") or 0)
        error = str(info.get("last_error_message") or "")
        error_at = float(info.get("last_error_date") or 0)
        if url != self.webhook_url:
            # Birinchi marta - yoki kimdir (boshqa nusxa) manzilni o'zgartirgan.
            self._set_webhook(now, "o'rnatildi" if not self._webhook_set_at
                              else "QAYTA o'rnatildi - manzil o'zgartirilgan edi")
            return True
        failing = bool(pending and error_at and error_at > self._webhook_set_at
                       and now - error_at < 3 * _WEBHOOK_CHECK)
        self._webhook = {"pending": pending, "last_error": error or None,
                         "last_error_at": _iso(error_at) if error_at else None}
        if not failing:
            self._webhook_fails = 0
            self._state["error"] = ""
            self._state["ok_at"] = now
            return True
        self._webhook_fails += 1
        self._state["error"] = f"Telegram webhook'ga yetib bora olmayapti: {error}"
        self._state["error_at"] = now
        if self._webhook_fails == 1 and ("401" in error or "403" in error):
            # Sir mos kelmayapti - boshqa nusxa webhook'ni o'z siri bilan
            # o'rnatgan bo'lishi mumkin. Bir marta qayta o'rnatamiz.
            self._set_webhook(now, "QAYTA o'rnatildi - sir rad etilayotgan edi")
            return True
        if self._webhook_fails >= _WEBHOOK_FAILS:
            log.error("Telegram webhook %d daqiqa ishlamadi (%s) - xabarlar yo'qolmasligi uchun "
                      "polling'ga qaytildi", self._webhook_fails, error)
            self.api.delete_webhook()
            self.mode = "polling"
            self._state["note"] = f"webhook ishlamadi ({error}) - polling'ga qaytildi"
            return False
        log.warning("Telegram webhook'ga yetib bora olmayapti (%d/%d): %s",
                    self._webhook_fails, _WEBHOOK_FAILS, error)
        return True

    def _set_webhook(self, now: float, what: str) -> None:
        self.api.set_webhook(self.webhook_url, secret=self.webhook_secret,
                             allowed_updates=ALLOWED_UPDATES)
        first = not self._webhook_set_at
        self._webhook_set_at = now
        self._webhook_fails = 0
        self._webhook = {"pending": 0, "last_error": None, "last_error_at": None}
        self._state["error"] = ""
        self._state["ok_at"] = now
        (log.info if first else log.warning)("Telegram webhook %s: %s", what, self.webhook_url)

    def accept(self, update: dict[str, Any]) -> None:
        """Webhook orqali kelgan yangilanish. Takrori tashlanadi."""
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            with self._seen_lock:
                if update_id in self._seen:
                    return
                self._seen[update_id] = None
                while len(self._seen) > _SEEN_UPDATES:
                    self._seen.popitem(last=False)
        self._state["updates"] += 1
        self._state["ok_at"] = time.time()
        self.dispatch(update)

    # --- polling ------------------------------------------------------------------

    def _run_polling(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            if not self._prepared:
                self._prepare()
            try:
                self.poll_once()
                backoff = 1.0
            except TelegramError as exc:
                wait, backoff = self.poll_error(exc, backoff)
                self._stop.wait(wait)
            except Exception:  # noqa: BLE001 - ip o'lmasligi kerak
                log.exception("Telegram bot: kutilmagan xato")
                self._stop.wait(5.0)

    def poll_error(self, exc: TelegramError, backoff: float, *,
                   now: float | None = None) -> tuple[float, float]:
        """`getUpdates` xatosidan keyin: (qancha kutish, keyingi backoff).

        409 IKKI XIL, va farqi muhim:

          * "webhook is active" - webhook o'rnatilgan, polling umuman
            ishlamaydi: kutamiz va aytamiz (qo'lda `deleteWebhook`);
          * "terminated by other getUpdates request" - BOSHQA NUSXA shu
            tokenni o'qiyapti (2026-09-24 da dev server). DARHOL qayta
            so'raymiz: Telegram'da faqat oxirgi so'rov tirik qoladi, ya'ni
            shu bilan ulanish bizga qaytadi va u nusxa xabarni ushlashga
            deyarli ulgurmaydi. Butunlay to'xtatish - tokenni yangilash.
        """
        now = time.time() if now is None else now
        text = f"{exc.description} {exc}".lower()
        if exc.code == 409 and "webhook" in text:
            self._state["error"] = str(exc)
            self._state["error_at"] = now
            log.error("Telegram bot: webhook o'rnatilgan - polling ishlamaydi, deleteWebhook kerak (%s)", exc)
            return 30.0, backoff
        if exc.code == 409:
            self._conflicts.append(now)
            if now - self._conflict_log_at >= 600:
                self._conflict_log_at = now
                log.warning("Telegram bot: boshqa nusxa ham shu tokenni o'qiyapti (409) - ulanish darhol "
                            "qaytarib olinadi; butunlay to'xtatish uchun bot tokenini yangilang")
            recent = sum(1 for t in self._conflicts if now - t <= 60)
            return (_CONFLICT_SLOW if recent > _CONFLICT_BURST else _CONFLICT_RETRY), backoff
        self._state["error"] = str(exc)
        self._state["error_at"] = now
        if exc.code in (401, 404):
            log.error("Telegram bot: token rad etildi (%s)", exc)
            return 300.0, backoff
        log.warning("Telegram bot: %s", exc)
        return backoff, min(backoff * 2, 30.0)

    def _prepare(self) -> None:
        """Bot nomi va buyruqlar menyusi - bir marta (yiqilsa keyin yana)."""
        try:
            self.username = str(self.api.get_me().get("username") or "")
            if self.api.get_my_commands() != COMMANDS:
                self.api.set_my_commands(COMMANDS)
                log.info("Telegram bot: buyruqlar menyusi yangilandi")
            self._prepared = True
            log.info("Telegram bot ishga tushdi: @%s", self.username)
        except TelegramError as exc:
            log.warning("Telegram bot tayyorlanmadi: %s", exc)

    def poll_once(self, timeout: int = 25) -> int:
        updates = self.api.get_updates(self._offset, timeout=timeout)
        self._state["ok_at"] = time.time()
        self._state["error"] = ""
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                # Keyingi so'rov shu `offset` bilan ketadi - Telegram buni
                # "qabul qilindi" deb biladi va qayta bermaydi.
                self._offset = max(self._offset or 0, update_id + 1)
            self._state["updates"] += 1
            try:
                self.dispatch(update)
            except Exception:  # noqa: BLE001
                log.exception("Telegram xabari navbatga qo'yilmadi")
        return len(updates)

    # --- navbat ---------------------------------------------------------------

    def dispatch(self, update: dict[str, Any]) -> None:
        if self._inline:
            self.handle_update(update)
            return
        if isinstance(update.get("callback_query"), dict):
            self._submit(lambda: self._on_callback(update["callback_query"]))
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat_id = (message.get("chat") or {}).get("id")
        if not isinstance(chat_id, int):
            return
        if is_video(message):
            # Navbatsiz: video DARHOL o'chirilsin - oldingi savolning javobini
            # (15-40 s) kutib chatda turmasin.
            self._submit(lambda: self._on_message(message))
            return
        if not self._enqueue(chat_id, lambda: self._on_message(message)):
            self._submit(lambda: self._say(
                chat_id, "⏳ Oldingi xabarlaringizga javob tayyorlanmoqda - biroz kuting."))

    def _submit(self, job: Callable[[], None]) -> None:
        if self._pool is None:
            job()
            return
        try:
            self._pool.submit(self._guarded, job)
        except RuntimeError:
            pass  # to'xtatilmoqda

    @staticmethod
    def _guarded(job: Callable[[], None]) -> None:
        try:
            job()
        except Exception:  # noqa: BLE001
            log.exception("Telegram xabari ishlanmadi")

    def _enqueue(self, chat_id: int, job: Callable[[], None]) -> bool:
        with self._qlock:
            queue = self._queues.setdefault(chat_id, deque())
            if len(queue) >= _QUEUE_LIMIT:
                return False
            queue.append(job)
            if chat_id in self._running:
                return True
            self._running.add(chat_id)
        self._submit(lambda: self._drain(chat_id))
        return True

    def _drain(self, chat_id: int) -> None:
        while True:
            with self._qlock:
                queue = self._queues.get(chat_id)
                if not queue:
                    self._queues.pop(chat_id, None)
                    self._running.discard(chat_id)
                    return
                job = queue.popleft()
            self._guarded(job)

    # --- yangilanishlar ---------------------------------------------------------

    def handle_update(self, update: dict[str, Any]) -> None:
        if isinstance(update.get("callback_query"), dict):
            self._on_callback(update["callback_query"])
        elif isinstance(update.get("message"), dict):
            self._on_message(update["message"])

    def _on_message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        # FAQAT shaxsiy chat. Javoblarda shaxsiy HR ma'lumoti bor - guruhga
        # qo'shilgan bot u yerda gapirmasligi kerak. Jim: guruhdagi har
        # xabarga "men bu yerda ishlamayman" deyish shovqin bo'lardi.
        if chat.get("type") != "private" or sender.get("is_bot"):
            return
        chat_id, tg_id = chat.get("id"), sender.get("id")
        if not isinstance(chat_id, int) or not isinstance(tg_id, int):
            return
        if is_video(msg):
            # Ulanganmi-yo'qmi - farqi yo'q: kamera yozuvi hech kimdan olinmaydi.
            self._reject_video(chat_id, msg)
            return
        sent = msg.get("date")
        if isinstance(sent, int) and time.time() - sent >= 5:
            # Yuborilgandan ishlanguncha: yetkazish + navbat. Sekin javobni
            # "GAPI mi, yordamchimi, Telegram mi" deb taxmin qilmaslik uchun.
            log.info("Telegram xabari %d s kechikib ishlandi (%s)", int(time.time() - sent), self.mode)
        text = str(msg.get("text") or "").strip()
        if text.startswith("/") and len(text) > 1 and text[1].isalpha():
            self._command(chat_id, tg_id, text)
            return

        link, state = self.links.lookup(tg_id)
        if link is None:
            self._link_prompt(chat_id, state)
            return
        user = self._user_for(chat_id, link)
        if user is None:
            return
        # Hisob: shu xabar bo'yicha har tashqi chaqiruv (STT, Assistant,
        # Telegram) shu odam va `bot` kanali bilan yoziladi. Bot HTTP dan
        # kelmaydi - kanalni sarlavha emas, kodning o'zi aytadi.
        with bind(user.actorId, "bot"):
            if isinstance(msg.get("voice"), dict):
                self._voice(chat_id, tg_id, user, msg)
            elif text:
                self._ask(chat_id, tg_id, user, text)
            else:
                # Rasm, fayl, stiker, audio fayl... - ishlanmaydi.
                self._note(chat_id, "Faqat matn va 🎙 ovozli xabar qabul qilinadi.")

    def _reject_video(self, chat_id: int, msg: dict[str, Any]) -> None:
        """Video (kamera) - yuklab olinmaydi va chatdan o'chiriladi."""
        message_id = msg.get("message_id")
        deleted = False
        if isinstance(message_id, int):
            try:
                self.api.delete_message(chat_id, message_id)
                deleted = True
            except TelegramError as exc:
                log.info("Telegram: video o'chirilmadi: %s", exc)
        log.info("Telegram: video rad etildi (%s)", "o'chirildi" if deleted else "o'chirilmadi")
        self._note(chat_id, "📵 Video qabul qilinmaydi" + (" - xabar o'chirildi" if deleted else "")
                   + ". Savolni yozing yoki 🎙 ovozli xabar yuboring.")

    def _note(self, chat_id: int, text: str) -> None:
        """Qisqa izoh - `_NOTE_EVERY` dan tez takrorlanmaydi."""
        now = time.monotonic()
        if now - self._note_at.get(chat_id, -_NOTE_EVERY) < _NOTE_EVERY:
            return
        self._note_at[chat_id] = now
        if len(self._note_at) > 2000:
            self._note_at.clear()
        self._say(chat_id, text)

    def _user_for(self, chat_id: int, link: TelegramLink) -> AuthUser | None:
        """Ulanishdagi hisob HALI BORMI - har xabarda tekshiriladi: hisob
        `users.yaml` dan olib tashlansa bot darhol to'xtashi kerak.

        Admin qarorlari veb ilovadagi bilan AYNI funksiyadan
        (`admin_users.access`): rollar samarali, bloklangan odam esa
        xushmuomala rad oladi. Bloklanganda ulanish UZILMAYDI - blok olib
        tashlansa odam mini app'ni qayta ochmasdan davom etsin.
        """
        stored = self.users().by_actor_id(link.actor_id)
        if stored is None:
            self.links.unlink(link.tg_id, actor_id=link.actor_id)
            log.warning("Telegram: ulangan hisob topilmadi (%s) - ulanish uzildi", link.actor_id)
            self._send(chat_id, "Venera hisobingiz topilmadi. Ilovani ochib qaytadan kiring.",
                       markup=render.app_button(self.webapp_url))
            return None
        verdict = admin_users.access(stored.to_public(), login=getattr(stored, "username", None))
        if verdict.blocked:
            log.info("Telegram: hisob bloklangan (%s) - savol qabul qilinmadi", link.actor_id)
            self._note(chat_id, _BLOCKED)
            return None
        return verdict.user

    def _link_prompt(self, chat_id: int, state: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._hint_at.get(chat_id, -_HINT_EVERY) < _HINT_EVERY:
            return
        self._hint_at[chat_id] = now
        if len(self._hint_at) > 2000:
            self._hint_at.clear()
        text = _EXPIRED.format(days=settings.telegram_link_days) if state == "expired" else _INTRO
        self._send(chat_id, text, markup=render.app_button(self.webapp_url))

    # --- buyruqlar --------------------------------------------------------------

    def _command(self, chat_id: int, tg_id: int, text: str) -> None:
        head = text.split(maxsplit=1)[0][1:]
        name, _, mention = head.partition("@")
        if mention and self.username and mention.lower() != self.username.lower():
            return
        name = name.lower()
        link, state = self.links.lookup(tg_id)
        if name == "start":
            if link is None:
                self._link_prompt(chat_id, state, force=True)
                return
            user = self._user_for(chat_id, link)
            if user is not None:
                self._send(chat_id, welcome_text(user, again=True))
        elif name == "help":
            self._send(chat_id, _HELP)
            if link is None:
                self._link_prompt(chat_id, state, force=True)
        elif name in ("new", "yangi"):
            if link is None:
                self._link_prompt(chat_id, state, force=True)
            elif self.links.new_chat(tg_id):
                self._send(chat_id, "🆕 Yangi suhbat boshlandi. Savolingizni yozing yoki "
                                    "ovozli xabar yuboring.")
        elif name == "app":
            self._send(chat_id, "Venera ilovasi - ovozli suhbat va suhbatlar tarixi:",
                       markup=render.app_button(self.webapp_url))
        elif name in ("logout", "chiqish"):
            if self.links.unlink(tg_id):
                log.info("Telegram: ulanish bot orqali uzildi (%s)", link.actor_id if link else "-")
                self._send(chat_id, "Hisobingiz botdan uzildi. Qayta ulash uchun Venera ilovasini "
                                    "oching.", markup=render.app_button(self.webapp_url))
            else:
                self._send(chat_id, "Hisob ulanmagan.")
        else:
            self._send(chat_id, "Bunday buyruq yo'q. Yordam: /help")

    # --- savol -> javob -----------------------------------------------------------

    def _ask(self, chat_id: int, tg_id: int, user: AuthUser, question: str, *,
             stt: dict[str, Any] | None = None) -> None:
        """`stt` - ovozli xabar bo'lsa: transkripsiya qancha vaqt olgani va
        qaysi variant (izga nuqta bo'lib tushadi, savol undan KEYIN boshlanadi)."""
        limit = settings.hrm_assistant_max_question_chars
        if len(question) > limit:
            self._say(chat_id, f"Savol juda uzun ({len(question)} belgi) - {limit} belgigacha yozing.")
            return
        chat = self.links.chat_for(tg_id, idle_sec=settings.telegram_chat_idle_hours * 3600)
        # SAVOL IZI (admin panel) - veb chatdagi bilan bir xil shakl.
        rec = TurnRecorder(user, "bot", "bot", question, chat_id=chat, locale="uz",
                           input_mode="voice" if stt else "text")
        if stt:
            rec.point("stt", **stt)
        try:
            with rec.bind():
                typing = _Typing(self.api, chat_id, self.typing_every).start()
                holder = self._send(chat_id, "⏳ Javob tayyorlanmoqda…")
                try:
                    answer = self._collect(question, user, chat, chat_id, holder, rec)
                finally:
                    typing.stop()
                # Javobni Telegram'ga yetkazish ham izda: uzun javob bir
                # necha xabarga bo'linadi va har biri tarmoq so'rovi.
                with rec.span("telegram.deliver"):
                    self._deliver(chat_id, holder, answer)
        except BaseException as exc:
            rec.finish("error", error=exc)
            raise
        rec.finish(error=answer.error)

    def _collect(self, question: str, user: AuthUser, chat: str, chat_id: int,
                 holder: int | None, rec: TurnRecorder) -> _Answer:
        answer = _Answer()
        log.info("Telegram savol (%s): %d belgi", user.actorId, len(question))
        try:
            with rec.span("assistant.open") as info:
                stream = self.backend.stream(question, user, chat)
                info["requestId"] = stream.request_id
        except AssistantError as exc:
            log.warning("Telegram savol (%s) [%s]: %s", user.actorId,
                        getattr(exc, "reason", None) or "-", exc)
            answer.failure = _chat_message(exc.status)
            # Veb chatdagi AYNI kod: `queue_full` / `upstream_unreachable` /
            # `upstream_busy`, qolgani `open_failed`.
            rec.error_code, answer.error = _open_error_code(exc), exc
            # Ochilmagan savolda ham qaysi dvigatelga borilgani izda tursin -
            # SHU ODAMNIKI (admin unga alohida versiya bergan bo'lishi mumkin).
            engine_of = getattr(self.backend, "engine", None)
            if callable(engine_of):
                rec.update(engine=engine_of(user))
            return answer
        # So'ralgan dvigatel (ma'lumotnoma javobida `None`); `done.engine`
        # kelsa `rec.observe` uni haqiqatda javob bergani bilan almashtiradi.
        rec.update(request_id=stream.request_id, engine=getattr(stream, "engine", None))
        frames = stream.frames
        stage_text, stage_at = "", 0.0
        try:
            for raw in frames:
                try:
                    frame = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(frame, dict):
                    continue
                # Izga - JSON qayta o'qilmaydi, tayyor lug'at beriladi.
                rec.observe(frame)
                kind = frame.get("type")
                if kind == "token":
                    answer.parts.append(str(frame.get("text") or ""))
                elif kind == "stage":
                    text = str(frame.get("text") or "").strip()
                    now = time.monotonic()
                    if holder and text and text != stage_text and now - stage_at >= _STAGE_EVERY:
                        stage_text, stage_at = text, now
                        self._edit(chat_id, holder, f"⏳ {esc(text)}")
                elif kind == "sources":
                    docs = render.doc_sources(frame.get("sources") or frame.get("items"))
                    if docs:
                        answer.docs = docs
                elif kind == "artifact":
                    art = frame.get("artifact") or frame
                    if isinstance(art, dict):
                        answer.artifacts.append(art)
                elif kind == "proposal":
                    proposal = frame.get("proposal") or frame
                    if isinstance(proposal, dict) and proposal.get("token"):
                        answer.proposals.append(proposal)
                elif kind == "error":
                    answer.failure = render.frame_error(frame)
        except AssistantError as exc:
            # Oqim o'rtasida uzildi - kelgan qism baribir ko'rsatiladi.
            log.warning("Telegram javob oqimi (%s): %s", user.actorId, exc)
            answer.failure = _chat_message(exc.status)
            # Veb chatdagi kabi kod (`stream_broken`), ichki sabab esa nuqtada.
            rec.point("assistant.broken", status=exc.status, error=redact(exc))
            rec.error_code, answer.error = "stream_broken", exc
        finally:
            # Oqim OXIRIGACHA o'qilmagan bo'lsa ham yopiladi - yuqoridagi
            # xizmat sloti faqat shunda bo'shaydi. `AnswerStream.close` -
            # boshlanmagan oqimda ham slotni qaytaradi; u bo'lmasa (soxta
            # oqim) - generatorning o'zi.
            close = getattr(stream, "close", None) or getattr(frames, "close", None)
            if callable(close):
                close()
            log.info("Telegram javob (%s): request_id=%s natija=%s", user.actorId,
                     stream.request_id, stream.outcome or "-")
        return answer

    def _deliver(self, chat_id: int, holder: int | None, answer: _Answer) -> None:
        if holder:
            try:
                self.api.delete_message(chat_id, holder)
            except TelegramError:
                self._edit(chat_id, holder, "✓")
        body = "".join(answer.parts).strip()
        blocks = render.to_blocks(body) if body else []
        markup = None
        if blocks and answer.docs:
            blocks.append(render.sources_block(answer.docs))
            markup = render.doc_buttons(answer.docs)
        if not blocks:
            if answer.failure:
                blocks = ["⚠️ " + esc(answer.failure)]
            elif not answer.artifacts and not answer.proposals:
                blocks = ["Javob kelmadi. Savolni boshqacha yozib ko'ring."]
        elif answer.failure:
            # Qisman javobdan keyingi xato - izoh, javobning o'rniga emas.
            blocks.append("⚠️ <i>" + esc(answer.failure) + "</i>")
        chunks = render.pack(blocks)
        for index, chunk in enumerate(chunks):
            self._send(chat_id, chunk, markup=markup if index == len(chunks) - 1 else None)
        for proposal in answer.proposals:
            self._send_proposal(chat_id, proposal)
        for artifact in answer.artifacts:
            self._send_artifact(chat_id, artifact)

    # --- ovozli xabar -------------------------------------------------------------

    def _voice(self, chat_id: int, tg_id: int, user: AuthUser, msg: dict[str, Any]) -> None:
        voice = msg["voice"]
        most = settings.telegram_voice_max_sec
        size_limit = int(settings.stt_max_upload_mb * 1024 * 1024)
        duration = int(voice.get("duration") or 0)
        if duration > most or int(voice.get("file_size") or 0) > size_limit:
            self._say(chat_id, f"Ovozli xabar juda uzun - {most // 60} daqiqagacha yuboring.")
            return
        file_id = voice.get("file_id")
        if not isinstance(file_id, str):
            return
        typing = _Typing(self.api, chat_id, self.typing_every).start()
        try:
            try:
                info = self.api.get_file(file_id)
                audio = self.api.download(str(info.get("file_path") or ""), limit=size_limit)
            except TelegramError as exc:
                log.warning("Telegram ovozi olinmadi (%s): %s", user.actorId, exc)
                self._say(chat_id, "Ovozli xabarni olib bo'lmadi - qaytadan yuboring.")
                return
            boshlandi = time.monotonic()
            try:
                result = self.backend.transcribe(audio, str(voice.get("mime_type") or "audio/ogg"))
            except SttError as exc:
                log.warning("Telegram STT (%s): %s", user.actorId, exc)
                self._say(chat_id, _stt_message(exc.status))
                return
            stt_ms = int((time.monotonic() - boshlandi) * 1000)
        finally:
            typing.stop()
        text = (result.text or "").strip()
        log.info("Telegram ovoz (%s): %d s -> %d belgi (%s)", user.actorId, duration,
                 len(text), result.backend or "-")
        if not text:
            self._send(chat_id, "🎙 Ovozdan matn ajratib bo'lmadi - aniqroq gapirib qayta yuboring.",
                       reply_to=msg.get("message_id"))
            return
        note = "\n<i>(yozuv uzun - boshi olindi)</i>" if result.truncated else ""
        self._send(chat_id, f"🎙 <i>{esc(text)}</i>{note}", reply_to=msg.get("message_id"))
        self._ask(chat_id, tg_id, user, text, stt={
            "durMs": stt_ms, "audioSec": duration, "backend": result.backend or None,
            "truncated": bool(result.truncated),
        })

    # --- tugmalar -------------------------------------------------------------------

    def _on_callback(self, cq: dict[str, Any]) -> None:
        cq_id = str(cq.get("id") or "")
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        tg_id = (cq.get("from") or {}).get("id")
        if chat.get("type") != "private" or not isinstance(tg_id, int) or not isinstance(chat.get("id"), int):
            self._answer_cb(cq_id)
            return
        chat_id = chat["id"]
        link, state = self.links.lookup(tg_id)
        if link is None:
            self._answer_cb(cq_id, "Avval Venera hisobingizni ulang: /start", alert=True)
            return
        user = self._user_for(chat_id, link)
        if user is None:
            self._answer_cb(cq_id)
            return
        kind, _, rest = str(cq.get("data") or "").partition(":")
        # Hisob: tugma bo'yicha chaqiruvlar (tasdiqlash, fayl) shu odam va
        # `bot` kanali bilan yoziladi.
        with bind(user.actorId, "bot"):
            self._button(cq_id, chat_id, msg, user, kind, rest)

    def _button(self, cq_id: str, chat_id: int, msg: dict[str, Any], user: AuthUser,
                kind: str, rest: str) -> None:
        if kind == "a":
            verb, _, token = rest.partition(":")
            self._action(cq_id, chat_id, msg.get("message_id"), user, verb, token)
        elif kind == "f":
            short, _, token = rest.partition(":")
            file_kind = {"d": "docx", "p": "pdf"}.get(short)
            if file_kind is None or not render.SAFE_ARTIFACT.fullmatch(token):
                self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
                return
            self._answer_cb(cq_id, "Fayl tayyorlanmoqda…")
            with self._titles_lock:
                title = self._titles.get(token) or "hujjat"
            self._send_file(chat_id, file_kind, token, title)
        elif kind == "d":
            if not render.SAFE_KEY.fullmatch(rest):
                self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
                return
            self._answer_cb(cq_id, "Hujjat yuklanmoqda…")
            self._send_doc(chat_id, rest)
        else:
            self._answer_cb(cq_id, "Tugma eskirgan", alert=True)

    def _action(self, cq_id: str, chat_id: int, message_id: Any, user: AuthUser,
                verb: str, token: str) -> None:
        if verb not in ("c", "x") or not render.SAFE_KEY.fullmatch(token):
            self._answer_cb(cq_id, "Tugma eskirgan", alert=True)
            return
        with self._busy_lock:
            if token in self._busy:
                # Ikki marta tez bosish - bitta so'rov.
                self._answer_cb(cq_id, "Bajarilmoqda…")
                return
            self._busy.add(token)
        what = "tasdiqlash" if verb == "c" else "rad etish"
        try:
            try:
                result = self.backend.action("confirm" if verb == "c" else "cancel", token, user)
            except AssistantError as exc:
                log.warning("Telegram amal %s (%s, %s): %s", what, user.actorId, token, exc)
                self._answer_cb(cq_id, _action_message(exc.status), alert=True)
                if exc.status == 404:
                    # Veb ilovadagi kabi: xizmat tanimagan taklif - muddati o'tgan.
                    if _assistant_proposal(token):
                        set_proposal_status(token, "expired")
                    if isinstance(message_id, int):
                        self._clear_buttons(chat_id, message_id)
                return
            outcome = _proposal_outcome("confirm" if verb == "c" else "cancel", result)
            if outcome and _assistant_proposal(token):
                set_proposal_status(token, outcome)
            settled, text, toast = render.outcome(result)
            log.info("Telegram amal %s (%s): token=%s holat=%s ok=%s", what, user.actorId, token,
                     result.get("status"), result.get("ok"))
            self._answer_cb(cq_id, toast)
            if settled and isinstance(message_id, int):
                self._clear_buttons(chat_id, message_id)
                self._send(chat_id, text, reply_to=message_id)
        finally:
            with self._busy_lock:
                self._busy.discard(token)

    # --- taklif va fayllar -----------------------------------------------------------

    def _send_proposal(self, chat_id: int, proposal: dict[str, Any]) -> None:
        text = render.proposal_card(proposal)
        markup = render.proposal_buttons(str(proposal.get("token") or ""))
        if markup is None:
            text += "\n\n<i>Bu taklifni Venera ilovasida tasdiqlang.</i>"
        self._send(chat_id, text, markup=markup)

    def _send_artifact(self, chat_id: int, art: dict[str, Any]) -> None:
        title = str(art.get("title") or art.get("filename") or "Hujjat").strip()
        refs: dict[str, str] = {}
        for key in ("docx_url", "pdf_url"):
            value = art.get(key)
            if isinstance(value, str):
                parts = value.split("/")
                # `/api/v1/chat/artifact/{token}/{kind}` - `_rewrite_artifact` shakli.
                if (len(parts) == 7 and parts[1:5] == ["api", "v1", "chat", "artifact"]
                        and parts[6] in ("docx", "pdf") and render.SAFE_ARTIFACT.fullmatch(parts[5])):
                    refs[parts[6]] = parts[5]
        if not refs:
            self._send(chat_id, f"📎 Hujjat tayyorlandi: <b>{esc(title)}</b>. "
                                "Faylni Venera ilovasidan yuklab oling.")
            return
        kind = "docx" if "docx" in refs else "pdf"
        markup = render.file_button("pdf", refs["pdf"]) if kind == "docx" and "pdf" in refs else None
        with self._titles_lock:
            for token in refs.values():
                self._titles[token] = title
                self._titles.move_to_end(token)
            while len(self._titles) > 500:
                self._titles.popitem(last=False)
        self._send_file(chat_id, kind, refs[kind], title,
                        caption=f"📎 <b>{esc(title)}</b>", markup=markup)

    def _send_file(self, chat_id: int, kind: str, token: str, title: str, *,
                   caption: str | None = None, markup: dict[str, Any] | None = None) -> None:
        from ..api.v1.chat import _download_name

        self._upload(chat_id, lambda: self.backend.artifact(token, kind),
                     _download_name(title, kind), caption=caption, markup=markup, what="Hujjat")

    def _send_doc(self, chat_id: int, doc_id: str) -> None:
        self._upload(chat_id, lambda: self.backend.doc(doc_id), None, what="Manba hujjati")

    def _upload(self, chat_id: int, open_it: Callable[[], Any], filename: str | None, *,
                caption: str | None = None, markup: dict[str, Any] | None = None,
                what: str = "Hujjat") -> None:
        try:
            content_type, upstream_name, chunks = open_it()
            data = b"".join(chunks)
        except AssistantError as exc:
            log.warning("Telegram: %s olinmadi: %s", what.lower(), exc)
            self._say(chat_id, f"{what}ni olib bo'lmadi: {_chat_message(exc.status)}")
            return
        if not data or len(data) >= _MAX_FILE:
            self._say(chat_id, f"{what}ni yuborib bo'lmadi - fayl bo'sh yoki juda katta.")
            return
        name = filename or upstream_name or "hujjat.pdf"
        try:
            self.api.send_document(chat_id, name, data, content_type or "application/octet-stream",
                                   caption=caption, reply_markup=markup)
        except TelegramError as exc:
            log.warning("Telegram: fayl yuborilmadi: %s", exc)
            self._say(chat_id, f"{what}ni yuborib bo'lmadi - qaytadan urinib ko'ring.")

    # --- yuborish -------------------------------------------------------------------

    def _send(self, chat_id: int, text: str, *, markup: dict[str, Any] | None = None,
              reply_to: Any = None) -> int | None:
        """HTML xabar. Telegram belgilashni rad etsa - teglarsiz qayta.
        Natija: yuborilgan xabar `message_id` si yoki `None`."""
        reply = reply_to if isinstance(reply_to, int) else None
        try:
            sent = self.api.send_message(chat_id, text, reply_markup=markup, reply_to=reply)
        except TelegramError as exc:
            if not exc.bad_markup:
                log.warning("Telegram xabari yuborilmadi: %s", exc)
                return None
            try:
                sent = self.api.send_message(chat_id, render.plain(text), html=False,
                                             reply_markup=markup, reply_to=reply)
            except TelegramError as again:
                log.warning("Telegram xabari yuborilmadi: %s", again)
                return None
        message_id = sent.get("message_id") if isinstance(sent, dict) else None
        return message_id if isinstance(message_id, int) else None

    def _say(self, chat_id: int, text: str) -> None:
        """Oddiy izoh (HTML'siz matn)."""
        self._send(chat_id, esc(text))

    def _edit(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            self.api.edit_message_text(chat_id, message_id, text)
        except TelegramError as exc:
            if not exc.not_modified:
                log.debug("Telegram tahrirlanmadi: %s", exc)

    def _clear_buttons(self, chat_id: int, message_id: int) -> None:
        try:
            self.api.edit_reply_markup(chat_id, message_id, None)
        except TelegramError as exc:
            if not exc.not_modified:
                log.debug("Telegram tugmalari olinmadi: %s", exc)

    def _answer_cb(self, cq_id: str, text: str = "", *, alert: bool = False) -> None:
        if not cq_id:
            return
        try:
            self.api.answer_callback(cq_id, text, alert=alert)
        except TelegramError as exc:
            log.debug("Telegram tugma javobi: %s", exc)

"""Telegram bot: xabarlarni olish (long polling) va javob berish.

OQIM (bitta savol):

    xabar/ovoz -> [ovoz bo'lsa: fayl -> STT -> "🎙 matn"] -> "⏳" xabari
      -> yuqoridagi xizmat oqimi (bosqich matni "⏳" da ko'rinadi)
      -> "⏳" o'chiriladi, javob YANGI xabar bo'lib keladi (bildirishnoma
         bilan - javob 15-40 s oladi va odam boshqa ishga o'tgan bo'ladi)
      -> manbalar tugmalari, taklif kartasi, ariza fayli

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
    "Xavfsizlik uchun ulanish muddati tugadi ({days} kun). Venera ilovasini ochib "
    "kiring - ulanish yangilanadi va shu yerda davom etasiz."
)
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

        return _chat._assistant.stream(
            question,
            user_id=_chat.assistant_user_id(user),
            chat_id=chat_id,
            tokens=_chat._live_tokens(user),
            max_chars=settings.hrm_assistant_max_question_chars,
        )

    def action(self, verb: str, token: str, user: AuthUser) -> dict[str, Any]:
        from ..api.v1 import chat as _chat

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


def _stt_message(status: int) -> str:
    from ..api.v1 import stt as _stt

    return _stt._MESSAGES.get(status, _stt._MESSAGES[502])


def _action_message(status: int) -> str:
    from ..api.v1 import actions as _actions

    return _actions._MESSAGES.get(status, _actions._MESSAGES[502])


@dataclass
class _Answer:
    parts: list[str] = field(default_factory=list)
    docs: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    failure: str | None = None


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
    ) -> None:
        self.api = api
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
        self._state: dict[str, Any] = {"error": "", "error_at": None, "ok_at": None, "updates": 0}

    # --- so'rov ipi ---------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tg-poll", daemon=True)
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
        }

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            if not self._prepared:
                self._prepare()
            try:
                self.poll_once()
                backoff = 1.0
            except TelegramError as exc:
                self._state["error"] = str(exc)
                self._state["error_at"] = time.time()
                if exc.code == 409:
                    # Boshqa jarayon (yoki webhook) shu botni o'qiyapti.
                    log.error("Telegram bot: %s - boshqa nusxa ishlayaptimi?", exc)
                    wait = 30.0
                elif exc.code in (401, 404):
                    log.error("Telegram bot: token rad etildi (%s)", exc)
                    wait = 300.0
                else:
                    log.warning("Telegram bot: %s", exc)
                    wait = backoff
                    backoff = min(backoff * 2, 30.0)
                self._stop.wait(wait)
            except Exception:  # noqa: BLE001 - ip o'lmasligi kerak
                log.exception("Telegram bot: kutilmagan xato")
                self._stop.wait(5.0)

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
        `users.yaml` dan olib tashlansa bot darhol to'xtashi kerak."""
        stored = self.users().by_actor_id(link.actor_id)
        if stored is None:
            self.links.unlink(link.tg_id, actor_id=link.actor_id)
            log.warning("Telegram: ulangan hisob topilmadi (%s) - ulanish uzildi", link.actor_id)
            self._send(chat_id, "Venera hisobingiz topilmadi. Ilovani ochib qaytadan kiring.",
                       markup=render.app_button(self.webapp_url))
            return None
        return stored.to_public()

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

    def _ask(self, chat_id: int, tg_id: int, user: AuthUser, question: str) -> None:
        limit = settings.hrm_assistant_max_question_chars
        if len(question) > limit:
            self._say(chat_id, f"Savol juda uzun ({len(question)} belgi) - {limit} belgigacha yozing.")
            return
        chat = self.links.chat_for(tg_id, idle_sec=settings.telegram_chat_idle_hours * 3600)
        typing = _Typing(self.api, chat_id, self.typing_every).start()
        holder = self._send(chat_id, "⏳ Javob tayyorlanmoqda…")
        try:
            answer = self._collect(question, user, chat, chat_id, holder)
        finally:
            typing.stop()
        self._deliver(chat_id, holder, answer)

    def _collect(self, question: str, user: AuthUser, chat: str, chat_id: int,
                 holder: int | None) -> _Answer:
        answer = _Answer()
        log.info("Telegram savol (%s): %d belgi", user.actorId, len(question))
        try:
            stream = self.backend.stream(question, user, chat)
        except AssistantError as exc:
            log.warning("Telegram savol (%s): %s", user.actorId, exc)
            answer.failure = _chat_message(exc.status)
            return answer
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
        finally:
            # Oqim OXIRIGACHA o'qilmagan bo'lsa ham yopiladi - yuqoridagi
            # xizmat sloti faqat shunda bo'shaydi.
            close = getattr(frames, "close", None)
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
            try:
                result = self.backend.transcribe(audio, str(voice.get("mime_type") or "audio/ogg"))
            except SttError as exc:
                log.warning("Telegram STT (%s): %s", user.actorId, exc)
                self._say(chat_id, _stt_message(exc.status))
                return
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
        self._ask(chat_id, tg_id, user, text)

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
                if exc.status == 404 and isinstance(message_id, int):
                    self._clear_buttons(chat_id, message_id)
                return
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

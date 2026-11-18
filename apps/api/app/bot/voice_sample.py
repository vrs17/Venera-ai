"""Telegram: OVOZ NAMUNASI - Plaud yig'ilishlarida xodim ism-familiyasi bilan chiqishi uchun (ega qarori 2026-11-18;
mantiq - `services/meetings/voice.py`, Slack va mobil ilova bilan BITTA).

  * «🗣 Ovoz namunasi» tugmasi (doimiy klaviatura) yoki `/ovoz` - tartib, o'qish matni va holat; chat
    `ARMED_SEC` davomida QUROLLANADI: shu oraliqda kelgan ovozli xabar (yoki audio fayl) namuna deb olinadi -
    Plaud yozuvi ham, HR savoli ham emas. Bitta xabarga ishlaydi; rad etilsa chat yana qurollanadi (qayta
    yuborish uchun tugmani qayta bosish shart emas).
  * natija - "⏳ Tekshirilmoqda" xabarining o'rnida (5-60 s): ✅ saqlandi yoki aniq sabab (qisqa, ikki ovoz ...).
  * «🗑 Ovozimni o'chirish» - tasdiq bilan (`v:del` -> `v:del!`).

Plaud bo'limi bilan birga yoqiladi (`Plaud.voice`): yig'ilishlar o'chiq bo'lsa namuna ham kerak emas.
"""

from __future__ import annotations

import logging
import threading
import time

from typing import Any, Callable

from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services.integrations.telegram import TelegramApi, TelegramError
from ..services.meetings import voice
from ..services.meetings.errors import MeetingProblem
from . import render
from .render import esc

log = logging.getLogger(__name__)

BTN_VOICE = "🗣 Ovoz namunasi"
ARMED_SEC = 15 * 60
#: Telegram `getFile` chegarasi 20 MB; namunaniki undan kichik (`VOICE_SAMPLE_MAX_BYTES`).
_REMEMBER = 2000
WAIT_TEXT = "⏳ Namuna tekshirilmoqda… (odatda 10-60 soniya)"
AGAIN = "\n\nQayta yozib, shu chatga yuboring - keyingi 15 daqiqada kelgan ovozli xabar namuna bo'ladi."


def instructions_html(status: dict[str, Any] | None = None) -> str:
    """Tartib, matn va holat - HTML (Telegram)."""
    info = voice.instructions()
    lines = [f"<b>{esc(info['intro'])}</b>", ""]
    if status and status.get("enrolled"):
        lines += [f"✅ Ovozingiz saqlangan ({int(status.get('samples') or 0)} ta namuna). Yangi namuna yuborsangiz "
                  "qo'shiladi va tanish aniqroq bo'ladi.", ""]
    lines.append("<b>Qanday yoziladi:</b>")
    lines += [f"{n}. {esc(step)}" for n, step in enumerate(info["steps"], start=1)]
    lines += ["", "<b>O'qiladigan matn:</b>", f"<blockquote>{esc(info['text'])}</blockquote>", "",
              "🎤 Mikrofon tugmasini bosib turib yozing va yuboring (taxminan 45 soniya)."]
    return "\n".join(lines)


def delete_menu(enrolled: bool) -> dict[str, Any] | None:
    if not enrolled:
        return None
    return {"inline_keyboard": [[{"text": "🗑 Ovozimni o'chirish", "callback_data": "v:del"}]]}


class VoiceSample:
    def __init__(self, api: TelegramApi, *, clock: Callable[[], float] = time.monotonic,
                 submit: Callable[..., dict[str, Any]] | None = None) -> None:
        self.api = api
        self._clock = clock
        self._lock = threading.Lock()
        #: chat -> qurollanish muddati (`clock`).
        self._armed: dict[int, float] = {}
        #: `voice.submit` - testlar almashtiradi.
        self._submit = submit or voice.submit

    # --- kirish ---------------------------------------------------------------------------

    def arm(self, chat_id: int) -> None:
        with self._lock:
            self._armed[chat_id] = self._clock() + ARMED_SEC
            if len(self._armed) > _REMEMBER:
                self._armed.clear()

    def disarm(self, chat_id: int) -> None:
        with self._lock:
            self._armed.pop(chat_id, None)

    def armed(self, chat_id: int) -> bool:
        with self._lock:
            return self._armed.get(chat_id, 0.0) > self._clock()

    def wants(self, chat_id: int, media: dict[str, Any] | None) -> bool:
        """Chat qurollangan va xabarda audio (ovozli xabar, audio fayl yoki audio hujjat) - namuna. Video emas."""
        if media is None or media.get("video") or not self.armed(chat_id):
            return False
        self.disarm(chat_id)
        return True

    def on_button(self, chat_id: int, user: AuthUser) -> None:
        try:
            state = voice.status(user)
        except MeetingProblem as exc:
            self._send(chat_id, esc(exc.message))
            return
        if not state.get("enabled"):
            self._send(chat_id, "🗣 Ovoz namunasi hozir o'chiq.")
            return
        self.arm(chat_id)
        self._send(chat_id, instructions_html(state), markup=delete_menu(bool(state.get("enrolled"))))

    def on_audio(self, chat_id: int, user: AuthUser, msg: dict[str, Any], media: dict[str, Any]) -> None:
        holder = self._send(chat_id, WAIT_TEXT, reply_to=msg.get("message_id"))
        limit = int(settings.voice_sample_max_bytes)
        if int(media.get("file_size") or 0) > limit:
            self._finish(chat_id, holder, "Yozuv juda katta - 1 daqiqagacha yozing." + AGAIN, rearm=True)
            return
        try:
            info = self.api.get_file(str(media.get("file_id") or ""))
            data = self.api.download(str(info.get("file_path") or ""), limit=limit)
        except TelegramError as exc:
            log.warning("Telegram ovoz namunasi olinmadi (%s): %s", user.actorId, exc)
            self._finish(chat_id, holder, "Yozuvni olib bo'lmadi - qaytadan yuboring." + AGAIN, rearm=True)
            return
        content_type = str(media.get("mime_type") or ("audio/ogg" if media.get("kind") == "voice" else ""))

        def done(view: dict[str, Any]) -> None:
            ok = view.get("status") == "ok"
            text = esc(view.get("message") or "") + ("" if ok else AGAIN)
            self._finish(chat_id, holder, text, rearm=not ok,
                         markup=delete_menu(True) if ok else None)

        try:
            self._submit(user, data, content_type, "telegram", on_done=done)
        except MeetingProblem as exc:
            self._finish(chat_id, holder, esc(exc.message) + (AGAIN if exc.status_code != 409 else ""),
                         rearm=exc.status_code != 409)

    def on_callback(self, cq_id: str, chat_id: int, msg: dict[str, Any], user: AuthUser, data: str) -> None:
        message_id = msg.get("message_id")
        if data == "v:del":
            self._answer(cq_id)
            self._send(chat_id, "Ovoz namunangiz o'chirilsinmi? Yig'ilishlarda ismingiz endi avtomatik chiqmaydi.",
                       markup={"inline_keyboard": [[{"text": "🗑 Ha, o'chirish", "callback_data": "v:del!"},
                                                    {"text": "Bekor qilish", "callback_data": "v:no"}]]})
            return
        if data == "v:no":
            self._answer(cq_id, "Bekor qilindi")
            self._edit(chat_id, message_id, "Ovoz namunangiz saqlanib qoldi.")
            return
        if data == "v:del!":
            try:
                result = voice.delete(user)
            except MeetingProblem as exc:
                self._answer(cq_id, exc.message, alert=True)
                return
            self._answer(cq_id, "O'chirildi")
            self._edit(chat_id, message_id, esc(result.get("message") or voice.DELETED_TEXT))
            return
        self._answer(cq_id, "Tugma eskirgan", alert=True)

    # --- yordamchilar -----------------------------------------------------------------------

    def _finish(self, chat_id: int, holder: int | None, text: str, *, rearm: bool = False,
                markup: dict[str, Any] | None = None) -> None:
        if rearm:
            self.arm(chat_id)
        if holder is not None and self._edit(chat_id, holder, text, markup=markup):
            return
        self._send(chat_id, text, markup=markup)

    def _send(self, chat_id: int, text: str, *, markup: dict[str, Any] | None = None,
              reply_to: Any = None) -> int | None:
        reply = reply_to if isinstance(reply_to, int) else None
        try:
            sent = self.api.send_message(chat_id, text, reply_markup=markup, reply_to=reply)
        except TelegramError as exc:
            if not exc.bad_markup:
                log.warning("Telegram ovoz namunasi: xabar yuborilmadi: %s", exc)
                return None
            try:
                sent = self.api.send_message(chat_id, render.plain(text), html=False, reply_markup=markup,
                                             reply_to=reply)
            except TelegramError as again:
                log.warning("Telegram ovoz namunasi: xabar yuborilmadi: %s", again)
                return None
        if isinstance(sent, dict) and isinstance(sent.get("message_id"), int):
            return sent["message_id"]
        return None

    def _edit(self, chat_id: int, message_id: Any, text: str, *, markup: dict[str, Any] | None = None) -> bool:
        if not isinstance(message_id, int):
            return False
        try:
            self.api.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            return True
        except TelegramError as exc:
            if exc.not_modified:
                return True
            log.debug("Telegram ovoz namunasi: xabar yangilanmadi: %s", exc)
            return False

    def _answer(self, cq_id: str, text: str = "", *, alert: bool = False) -> None:
        if not cq_id:
            return
        try:
            self.api.answer_callback(cq_id, text, alert=alert)
        except TelegramError as exc:
            log.debug("Telegram ovoz namunasi: tugma javobi: %s", exc)

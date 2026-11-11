"""Slack ilovasi "Barno AI" - Venera'ning Slack'dagi klienti (`app/bot/` ning o'xshashi).

Odam Barno AI ga shaxsiy xabarda AUDIO yuborsa, u matnga o'giriladi (`transcribe.py`),
keyin chatning O'ZIGA "Qisqa xulosa" va tugmalar yoziladi (transkript fayli, vazifalar, boshqa
shablon, eksport, boshqa tilda qayta o'girish). Savol - yozuv chati (`meeting.py`, suhbat xotirasi
bilan): chatga yozilgan matn - chatdagi OXIRGI yozuv bo'yicha, yozuv xabarining thread'idagi savol -
o'sha (eski ham) yozuv bo'yicha. Audio thread ichida yuborilgan bo'lsa - hammasi o'sha thread'da.
Chatda hali yozuv bo'lmasa, matnga «🎙 Plaud» yo'riqnomasi qaytadi (`home.py`).

NEGA SOCKET MODE. Server ichki tarmoqda - Slack bizga HTTP so'rov yubora olmaydi.
Socket Mode'da ulanishni biz ochamiz (chiquvchi WebSocket, TCP 443): ochiq domen va
kiruvchi port kerak emas.

NEGA API JARAYONI ICHIDA. Audio yig'ilishlar quvuriga (`services/meetings`)
to'g'ridan-to'g'ri beriladi: HTTP, login va token kerak emas, fon ishchisi, navbat va
limitlar esa veb va mobil ilova bilan BITTA.

BITTA ULANISH. Bitta `xapp` token bilan ikki jarayon ulansa, Slack hodisalarni ular
orasida TASODIFIY taqsimlaydi va xabarlarning bir qismi "yo'qoladi". Shuning uchun
Telegram botdagi kabi fayl qulfi bor. Shu tokenni boshqa joyda (lokal kompyuter)
ishga tushirmang.
"""

from __future__ import annotations

import contextlib
import logging
import re
import ssl
import threading

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..core.config import BASE_DIR, settings

log = logging.getLogger(__name__)

#: Bir vaqtdagi vazifalar (audio, savol, tugma). Slack hodisa iplari kutib qolmaydi -
#: ular vazifani shu navbatga qo'yadi, xolos. Vazifa ko'p vaqtini KUTISHDA o'tkazadi
#: (transkript, xulosa, javob), GAPI va modelga yukni yig'ilish ishchisi o'zi cheklaydi -
#: shuning uchun ip ko'p: bitta uzun yozuv boshqalarning savolini to'sib qo'ymasin.
WORKERS = 8
#: Tizim CA'lari (`certifi` emas): ofis tarmog'idagi FortiGate SSL tekshiruvi
#: sertifikatni qayta imzolaydi va unga faqat tizim ishonadi. WebSocket ham shu
#: kontekstni ishlatadi (`SocketModeClient` -> `web_client.ssl`).
SSL = ssl.create_default_context()

_handler = None
_pool: ThreadPoolExecutor | None = None
_lock_file = None
_stop = threading.Event()


def start() -> None:
    """Fonda ulanadi - ikkala token bor va qulf olinsa. API ishga tushishini kutdirmaydi."""
    global _lock_file, _pool
    if _pool is not None:
        return
    if not (settings.slack_bot_token and settings.slack_app_token):
        log.info("Slack ilovasi ishga tushirilmadi: token yo'q")
        return
    _lock_file = _take_lock()
    if _lock_file is None:
        log.warning("Slack ilovasi ishga tushirilmadi: boshqa jarayon ulangan (qulf band)")
        return
    _stop.clear()
    _pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="slack-audio")
    threading.Thread(target=_connect, name="slack-connect", daemon=True).start()


def stop() -> None:
    global _handler, _pool, _lock_file
    _stop.set()
    if _handler is not None:
        with contextlib.suppress(Exception):
            _handler.close()
        _handler = None
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
    if _lock_file is not None:
        with contextlib.suppress(Exception):
            _lock_file.close()
        _lock_file = None


def _connect() -> None:
    """Ulanish. Muvaffaqiyatsiz bo'lsa (tarmoq, token) - kutib qayta urinadi, API buni
    sezmaydi. Ulangandan keyingi uzilishlarni `SocketModeClient` o'zi tiklaydi."""
    global _handler
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
        from slack_sdk import WebClient
    except ImportError:
        log.error("Slack ilovasi: `slack_bolt` o'rnatilmagan (`pip install -e .`)")
        return
    delay = 5.0
    while not _stop.is_set():
        try:
            # `App` tokenni shu yerda `auth.test` bilan tekshiradi.
            app = App(client=WebClient(token=settings.slack_bot_token, ssl=SSL))
            app.event("message")(_on_message)
            app.event("app_home_opened")(_on_home)
            app.action(re.compile(r"^barno_"))(_on_action)
            app.command("/plaud")(_on_command)
            handler = SocketModeHandler(app, settings.slack_app_token)
            handler.connect()
        except Exception as exc:  # noqa: BLE001 - tarmoq, yaroqsiz token, Slack xatosi
            log.warning("Slack ilovasi ulanmadi (%s: %s) - %.0f s dan keyin qayta",
                        type(exc).__name__, str(exc)[:200], delay)
            _stop.wait(delay)
            delay = min(delay * 2, 300.0)
            continue
        if _stop.is_set():
            # Ulanish paytida `stop()` chaqirildi.
            with contextlib.suppress(Exception):
                handler.close()
            return
        _handler = handler
        log.info("Slack ilovasi ulandi")
        return


def _on_message(event: dict[str, Any], client: Any, context: Any) -> None:
    """Bolt tinglovchisi. Navbatga qo'yadi: o'girish va javob daqiqalab davom etadi. Faqat
    audioning jarayon xabari shu yerda, darhol (`meeting.acknowledge`): navbat band bo'lsa ham
    odam audiosi qabul qilinganini ko'radi. Thread'dan tashqaridagi oddiy matn - oxirgi yozuv
    chati, chatda yozuv bo'lmasa «🎙 Plaud» yo'riqnomasi (`meeting.on_text`): chat tarixi ham
    navbatda o'qiladi, Bolt ipi Slack'ka murojaat qilmaydi. Har xabar (matn, audio bo'lmagan fayl)
    qo'shimcha ravishda arxivga (`keep.py`)."""
    from . import home, keep, meeting

    pool = _pool
    if pool is None:
        return
    if keep.wants(event):
        pool.submit(keep.record, event)
    bot_user = context.get("bot_user_id")
    if meeting.wants(event):
        shown = meeting.acknowledge(client, event)
        pool.submit(meeting.on_message, client, event, sleep=_sleep, bot_user=bot_user, shown=shown)
    elif home.is_text(event):
        pool.submit(meeting.on_text, client, event, bot_user=bot_user)


def _on_command(ack: Any, body: dict[str, Any], client: Any) -> None:
    """`/plaud` (manifestda bo'lsa). `ack` darhol - Slack 3 s kutadi."""
    from . import home

    ack()
    pool = _pool
    if pool is not None:
        pool.submit(home.on_command, client, body)


def _on_home(event: dict[str, Any], client: Any) -> None:
    """Barno AI ochildi - "Home" varag'i (`home.py`)."""
    from . import home

    pool = _pool
    if pool is not None:
        pool.submit(home.on_open, client, event)


def _on_action(ack: Any, body: dict[str, Any], client: Any) -> None:
    """Tugma va ro'yxat. Slack javobni 3 s ichida kutadi - `ack` darhol, ish navbatda."""
    from . import home, meeting

    ack()
    pool = _pool
    if pool is None:
        return
    if home.is_plaud(body):
        pool.submit(home.on_plaud, client, body)
    else:
        pool.submit(meeting.on_action, client, body, sleep=_sleep)


def _sleep(sec: float) -> None:
    """Kutish - API to'xtayotgan bo'lsa darhol uziladi: navbat iplari restartni ushlab
    turmasin (systemd 20 s dan keyin jarayonni o'ldiradi). "Qayta urinish" restartdan
    keyin ishlaydi: yig'ilish kaliti fayldan, ya'ni tayyor qismi takrorlanmaydi."""
    from .transcribe import Problem

    if _stop.wait(sec):
        raise Problem("Server qayta ishga tushirilmoqda - birozdan keyin qayta urinib ko'ring.", retry=True)


def _take_lock():
    """`data/slack/socket.lock` - boshqa jarayon ushlab tursa `None` (`bot._take_lock` kabi)."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows: qulfsiz
        return object()
    path = BASE_DIR / "data" / "slack" / "socket.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a")  # noqa: SIM115 - jarayon umri davomida ochiq
    except OSError as exc:
        log.warning("Slack qulfi ochilmadi (%s): %s", path, exc)
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle

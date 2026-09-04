"""Loglash: aylanuvchi fayl + (bo'lsa) konsol.

PyInstaller --noconsole rejimida sys.stdout None bo'ladi. Shuning uchun:
  * konsol handler faqat haqiqiy stdout bo'lganda qo'shiladi;
  * print() ishlatilmaydi, hamma joyda logging;
  * sys.excepthook / threading.excepthook / faulthandler faylga yozadi,
    aks holda xatolar hech qayerda ko'rinmay yo'qoladi.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from typing import TextIO

from . import APP_DISPLAY_NAME, __version__, paths

_FORMAT = "%(asctime)s %(levelname)-7s %(threadName)-12s %(name)-28s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_crash_stream: TextIO | None = None


def _real_stream(stream: TextIO | None) -> bool:
    """--noconsole rejimida stdout None yoki fileno'siz bo'ladi."""
    if stream is None:
        return False
    try:
        stream.fileno()
    except Exception:  # noqa: BLE001 - har qanday xato "haqiqiy emas" degani
        return False
    return True


def setup(level: str = "INFO", max_bytes: int = 5 * 1024 * 1024, backup_count: int = 5,
          console: bool | None = None) -> Path:
    """Loglashni sozlaydi va log fayl yo'lini qaytaradi."""
    paths.ensure_dirs()
    log_path = paths.log_file()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        root.addHandler(file_handler)
    except OSError:
        pass  # log fayli ochilmasa ham ilova ishlashi kerak

    want_console = _real_stream(sys.stderr) if console is None else console
    if want_console and _real_stream(sys.stderr):
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        root.addHandler(stream_handler)

    # Uchinchi tomon kutubxonalarining shovqinli loglari
    for noisy in ("comtypes", "comtypes.client", "comtypes.client._generate",
                  "PIL", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _install_crash_handlers()

    logging.getLogger(__name__).info(
        "%s v%s ishga tushdi (python %s, %s)",
        APP_DISPLAY_NAME, __version__, sys.version.split()[0], sys.platform,
    )
    return log_path


def _install_crash_handlers() -> None:
    """Ushlanmagan xatolarni faylga yozadi (--noconsole da yagona iz)."""
    global _crash_stream

    if _crash_stream is None:
        try:
            _crash_stream = paths.crash_file().open("a", encoding="utf-8", buffering=1)
            faulthandler.enable(file=_crash_stream, all_threads=True)
        except OSError:
            _crash_stream = None

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logging.getLogger("crash").critical(
            "Ushlanmagan xato", exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _hook

    def _thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        logging.getLogger("crash").critical(
            "Thread'da ushlanmagan xato: %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_hook


class TranscriptFilter:
    """log_transcripts=false bo'lsa foydalanuvchi matnini logga tushirmaydi."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def text(self, value: str) -> str:
        if self.enabled:
            return value
        return f"<{len(value)} belgi>"

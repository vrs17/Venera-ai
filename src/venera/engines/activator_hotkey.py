"""Global hotkey orqali uyg'otish (Step 1).

Nima uchun RegisterHotKey, `keyboard` paketi emas:
  * RegisterHotKey admin huquqisiz ishlaydi va --noconsole rejimida ham
    muammosiz - u past darajali klaviatura hook'i emas;
  * hook antivirus va DLP tizimlarida keylogger sifatida belgilanishi mumkin,
    bankda bu jiddiy muammo.

Har bir RegisterHotKey chaqirilgan thread'ning o'z xabar navbati bo'lishi kerak,
shuning uchun alohida thread + GetMessageW sikli ishlatiladi.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Callable

from .base import Activator

log = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

HOTKEY_ID = 0xB2B

#: Sozlamadagi kombinatsiya band bo'lsa navbat bilan sinaladi.
#: Ofis kompyuterlarida Ctrl+Alt+Space ni Punto Switcher, Yandex va
#: klaviatura drayverlari tez-tez egallab oladi.
FALLBACKS: list[tuple[list[str], str]] = [
    (["ctrl", "alt"], "space"),
    (["ctrl", "alt"], "b"),
    (["ctrl", "shift"], "space"),
    (["ctrl", "alt"], "f9"),
    (["ctrl", "alt", "shift"], "b"),
    (["win"], "f9"),
]

_MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN,
}

_KEYS = {
    "space": 0x20, "probel": 0x20,
    "enter": 0x0D, "return": 0x0D,
    "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
}


def parse_hotkey(modifiers: list[str], key: str) -> tuple[int, int, str]:
    """(modifier bitmask, virtual key kod, ko'rinadigan nom) qaytaradi."""
    mask = 0
    labels = []
    for name in modifiers or []:
        value = _MODIFIERS.get(str(name).strip().lower())
        if value is None:
            log.warning("Noma'lum modifikator: %r", name)
            continue
        mask |= value
        labels.append(str(name).strip().capitalize())

    key_name = str(key or "space").strip().lower()
    if key_name in _KEYS:
        vk = _KEYS[key_name]
    elif len(key_name) == 1:
        vk = ord(key_name.upper())
    else:
        log.warning("Noma'lum klavisha: %r - Space ishlatiladi", key)
        key_name, vk = "space", 0x20
    labels.append(key_name.capitalize())

    # MOD_NOREPEAT: klavisha bosib turilsa qayta-qayta ishlamasin
    return mask | MOD_NOREPEAT, vk, "+".join(labels)


class HotkeyActivator(Activator):
    name = "hotkey"

    def __init__(self, modifiers: list[str], key: str, allow_fallback: bool = True) -> None:
        self.requested = (list(modifiers or []), str(key or "space"))
        self.allow_fallback = allow_fallback
        self.mask, self.vk, self.label = parse_hotkey(modifiers, key)
        self.fell_back = False
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._callback: Callable[[], None] | None = None
        self._ready = threading.Event()
        self._ok = False
        self._error = ""

    @property
    def error(self) -> str:
        return self._error

    def describe(self) -> str:
        return f"hotkey {self.label}"

    def start(self, on_activate: Callable[[], None]) -> bool:
        if sys.platform != "win32":
            self._error = "global hotkey faqat Windows'da"
            log.warning("%s", self._error)
            return False
        if self._thread is not None:
            return self._ok

        self._callback = on_activate

        combos = [self.requested]
        if self.allow_fallback:
            combos += [c for c in FALLBACKS if c != self.requested]

        for index, (modifiers, key) in enumerate(combos):
            self.mask, self.vk, self.label = parse_hotkey(modifiers, key)
            self._ready.clear()
            self._ok = False
            self._error = ""
            self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
            self._thread.start()
            self._ready.wait(timeout=5.0)
            if self._ok:
                self.fell_back = index > 0
                if self.fell_back:
                    requested_label = parse_hotkey(*self.requested)[2]
                    log.warning("%s band edi - %s ishlatilmoqda", requested_label, self.label)
                return True
            self.stop()

        # Hech biri ishlamadi: so'ralgan kombinatsiya nomi bilan xabar beramiz
        self.mask, self.vk, self.label = parse_hotkey(*self.requested)
        log.warning("Hech qanday uyg'otish klavishasi ro'yxatdan o'tmadi")
        return False

    def stop(self) -> None:
        if self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception as exc:  # noqa: BLE001
                log.debug("Hotkey thread'iga WM_QUIT yuborilmadi: %s", exc)
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _run(self) -> None:
        from ctypes import wintypes  # faqat Windows'da import bo'ladi

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, HOTKEY_ID, self.mask, self.vk):
            code = kernel32.GetLastError()
            self._error = (
                f"{self.label} band (boshqa dastur egallagan)" if code == 1409
                else f"hotkey ro'yxatdan o'tmadi (kod {code})"
            )
            self._ok = False
            log.warning("%s", self._error)
            self._ready.set()
            return

        self._ok = True
        log.info("Global hotkey yoqildi: %s", self.label)
        self._ready.set()

        try:
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    log.debug("Hotkey bosildi")
                    if self._callback is not None:
                        try:
                            self._callback()
                        except Exception:  # noqa: BLE001 - callback xatosi siklni buzmasin
                            log.exception("Hotkey callback xatosi")
        except Exception:  # noqa: BLE001
            log.exception("Hotkey sikli to'xtadi")
        finally:
            try:
                user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:  # noqa: BLE001
                pass
            log.info("Global hotkey o'chirildi")


class NullActivator(Activator):
    """Windows bo'lmagan muhitda yoki hotkey ishlamaganda."""

    name = "none"

    def start(self, on_activate: Callable[[], None]) -> bool:  # noqa: ARG002
        return False

    def stop(self) -> None:
        return None

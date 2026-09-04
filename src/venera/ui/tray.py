"""Tizim trayidagi ikonka va menyu.

pystray `run()` ASOSIY thread'da chaqirilishi kerak: Windows'da u o'z yashirin
oynasi va xabar siklini yaratadi, macOS'da esa AppKit umuman asosiy thread'ni
talab qiladi. Shu sababli butun ilova shu tuzilishga qurilgan - macOS'ga
ko'chirishda bu qism o'zgarmaydi.
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path
from typing import Callable

from .. import APP_DISPLAY_NAME, __version__, paths
from ..core.states import State, label
from . import icons

log = logging.getLogger(__name__)

try:
    import pystray
    PYSTRAY_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001
    pystray = None
    PYSTRAY_ERROR = str(exc)


def _open_path(target: Path) -> None:
    """Papka yoki faylni tizim ko'ruvchisida ochadi."""
    try:
        if sys.platform == "win32":
            import os

            os.startfile(str(target))  # noqa: S606 - foydalanuvchi so'ragan amal
        else:
            webbrowser.open(target.as_uri())
    except Exception as exc:  # noqa: BLE001
        log.warning("Ochilmadi %s: %s", target, exc)


class Tray:
    """Tray ikonkasi. Ishga tushmasa ham ilova ishlayveradi (faqat oyna bilan)."""

    def __init__(
        self,
        adapter,
        on_activate: Callable[[], None],
        on_toggle_window: Callable[[], None],
        on_cancel: Callable[[], None],
        on_reload: Callable[[], None],
        on_quit: Callable[[], None],
        hotkey_label: str = "",
        autostart_command: str = "",
        on_check_update: Callable[[], None] | None = None,
        on_install_update: Callable[[], None] | None = None,
    ) -> None:
        self.adapter = adapter
        self.on_activate = on_activate
        self.on_toggle_window = on_toggle_window
        self.on_cancel = on_cancel
        self.on_reload = on_reload
        self.on_quit = on_quit
        self.hotkey_label = hotkey_label
        self.autostart_command = autostart_command
        self.on_check_update = on_check_update or (lambda: None)
        self.on_install_update = on_install_update or (lambda: None)

        self._update_version = ""
        self._icon = None
        self._state = State.IDLE
        self._detail = ""
        self._error = False
        self._started = False

    # --- ommaviy interfeys ---------------------------------------------------

    @property
    def available(self) -> bool:
        return pystray is not None

    @property
    def error(self) -> str | None:
        return PYSTRAY_ERROR

    def run(self) -> bool:
        """Bloklaydi. Asosiy thread'dan chaqiring."""
        if pystray is None:
            log.warning("Tray ikonkasi mavjud emas: %s", PYSTRAY_ERROR)
            return False
        try:
            self._icon = pystray.Icon(
                name="venera",
                title=self._tooltip(),
                icon=icons.build(self._state.value),
                menu=self._menu(),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Tray ikonkasi yaratilmadi: %s", exc)
            return False

        self._started = True
        log.info("Tray ikonkasi ishga tushdi")
        try:
            self._icon.run()
        except Exception as exc:  # noqa: BLE001
            log.warning("Tray sikli to'xtadi: %s", exc)
            return False
        finally:
            self._started = False
        return True

    def stop(self) -> None:
        icon = self._icon
        if icon is not None:
            try:
                icon.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("Tray to'xtatilmadi: %s", exc)

    def set_state(self, state: str, detail: str = "") -> None:
        try:
            self._state = State(state)
        except ValueError:
            return
        self._detail = detail
        icon = self._icon
        if icon is None:
            return
        try:
            icon.icon = icons.build(self._state.value, error=self._error)
            icon.title = self._tooltip()
        except Exception as exc:  # noqa: BLE001
            log.debug("Tray ikonkasi yangilanmadi: %s", exc)

    def set_update_available(self, version: str) -> None:
        """Menyuda "yangilash" bandi paydo bo'lsin."""
        self._update_version = version or ""
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.menu = self._menu()
            icon.update_menu()
        except Exception as exc:  # noqa: BLE001
            log.debug("Menyu yangilanmadi: %s", exc)

    def set_error(self, is_error: bool) -> None:
        self._error = is_error
        self.set_state(self._state.value, self._detail)

    def notify(self, title: str, message: str) -> None:
        icon = self._icon
        if icon is None or not self._started:
            log.info("Xabar (tray yo'q): %s - %s", title, message)
            return
        try:
            icon.notify(message, title)
        except Exception as exc:  # noqa: BLE001
            log.debug("Toast ko'rsatilmadi: %s", exc)

    # --- menyu ---------------------------------------------------------------

    def _tooltip(self) -> str:
        parts = [APP_DISPLAY_NAME, label(self._state)]
        if self.hotkey_label:
            parts.append(self.hotkey_label)
        return " - ".join(parts)

    def _autostart_checked(self, _item=None) -> bool:
        try:
            return self.adapter.autostart_status().installed
        except Exception:  # noqa: BLE001
            return False

    def _toggle_autostart(self, _icon=None, _item=None) -> None:
        try:
            if self._autostart_checked():
                status = self.adapter.autostart_remove()
                self.notify(APP_DISPLAY_NAME, "Avtostart o'chirildi")
            else:
                status = self.adapter.autostart_install(self.autostart_command)
                if status.installed:
                    self.notify(APP_DISPLAY_NAME, "Avtostart yoqildi - kompyuter yonganda o'zi ishga tushadi")
                else:
                    self.notify(APP_DISPLAY_NAME, f"Avtostart yoqilmadi: {status.detail[:120]}")
            log.info("Avtostart holati: %s", status)
        except Exception:  # noqa: BLE001
            log.exception("Avtostart o'zgartirilmadi")

    def _menu(self):
        item = pystray.MenuItem
        separator = pystray.Menu.SEPARATOR

        return pystray.Menu(
            item(lambda _i: f"Holat: {label(self._state)}", None, enabled=False),
            separator,
            item("Oynani ko'rsatish / yashirish", lambda: self.on_toggle_window(), default=True),
            item(f"Uyg'otish ({self.hotkey_label})" if self.hotkey_label else "Uyg'otish",
                 lambda: self.on_activate()),
            item("To'xtatish", lambda: self.on_cancel()),
            separator,
            item("Windows bilan ishga tushsin", self._toggle_autostart,
                 checked=self._autostart_checked),
            separator,
            item(lambda _i: (f"Yangi versiya {self._update_version} - yangilash"
                             if self._update_version else "Yangilanishni tekshirish"),
                 lambda: (self.on_install_update() if self._update_version
                          else self.on_check_update())),
            item("Sozlamalar faylini ochish", lambda: _open_path(paths.config_file())),
            item("Dasturlar ro'yxatini ochish", lambda: _open_path(paths.apps_file())),
            item("Loglar papkasini ochish", lambda: _open_path(paths.log_dir())),
            item("Sozlamalarni qayta yuklash", lambda: self.on_reload()),
            separator,
            item(f"Versiya {__version__}", None, enabled=False),
            item("Chiqish", lambda: self.on_quit()),
        )

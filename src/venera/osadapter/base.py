"""OS qatlami interfeysi.

macOS'ga ko'chirishda FAQAT shu interfeysning yangi implementatsiyasi yoziladi
(`macos.py`), qolgan kod umuman o'zgarmaydi.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class AutostartStatus:
    installed: bool
    detail: str = ""


class OSAdapter(ABC):
    """Operatsion tizimga bog'liq barcha amallar."""

    name: str = "base"

    # --- dasturlar va havolalar ---------------------------------------------

    @abstractmethod
    def launch(self, targets: list[str]) -> bool:
        """Ro'yxatdagi maqsadlarni navbat bilan sinaydi, birinchi ishlagani yetarli."""

    @abstractmethod
    def open_url(self, url: str) -> bool:
        ...

    # --- tizim ovozi ---------------------------------------------------------

    @abstractmethod
    def get_volume(self) -> int | None:
        """0..100, aniqlab bo'lmasa None."""

    @abstractmethod
    def set_volume(self, percent: int) -> bool:
        ...

    @abstractmethod
    def set_mute(self, muted: bool) -> bool:
        ...

    # --- ekran ---------------------------------------------------------------

    @abstractmethod
    def lock_workstation(self) -> bool:
        ...

    @abstractmethod
    def screenshot(self, destination: Path) -> Path | None:
        ...

    @abstractmethod
    def is_session_locked(self) -> bool:
        """Ekran qulflangan bo'lsa True - bu holatda mikrofon yopiladi."""

    # --- ilova hayoti --------------------------------------------------------

    @abstractmethod
    def acquire_single_instance(self, key: str) -> bool:
        """Birinchi nusxa bo'lsa True. Ikkinchi nusxa False olib, chiqib ketadi."""

    @abstractmethod
    def autostart_status(self) -> AutostartStatus:
        ...

    @abstractmethod
    def autostart_install(self, command: str) -> AutostartStatus:
        ...

    @abstractmethod
    def autostart_remove(self) -> AutostartStatus:
        ...

    # --- xabarlar ------------------------------------------------------------

    def set_notifier(self, notifier: Callable[[str, str], None] | None) -> None:
        """Tray ikonkasi tayyor bo'lgach, toast chiqaruvchi funksiya beriladi."""
        self._notifier = notifier

    def notify(self, title: str, message: str) -> None:
        notifier = getattr(self, "_notifier", None)
        if notifier is not None:
            try:
                notifier(title, message)
            except Exception:  # noqa: BLE001 - xabar ko'rsatilmasa ham ish davom etadi
                pass

    # --- diagnostika ---------------------------------------------------------

    def describe(self) -> dict[str, str]:
        return {"adapter": self.name}


class NullAdapter(OSAdapter):
    """Windows/macOS bo'lmagan muhit (WSL, CI) uchun - hech narsa qilmaydi.

    Shu tufayli butun ilovani Linux'da import qilib, testlarni ishga tushirish mumkin.
    """

    name = "null"

    def launch(self, targets: list[str]) -> bool:
        return False

    def open_url(self, url: str) -> bool:
        return False

    def get_volume(self) -> int | None:
        return None

    def set_volume(self, percent: int) -> bool:
        return False

    def set_mute(self, muted: bool) -> bool:
        return False

    def lock_workstation(self) -> bool:
        return False

    def screenshot(self, destination: Path) -> Path | None:
        return None

    def is_session_locked(self) -> bool:
        return False

    def acquire_single_instance(self, key: str) -> bool:
        return True

    def autostart_status(self) -> AutostartStatus:
        return AutostartStatus(False, "bu platformada qo'llab-quvvatlanmaydi")

    def autostart_install(self, command: str) -> AutostartStatus:
        return AutostartStatus(False, "bu platformada qo'llab-quvvatlanmaydi")

    def autostart_remove(self) -> AutostartStatus:
        return AutostartStatus(False, "bu platformada qo'llab-quvvatlanmaydi")

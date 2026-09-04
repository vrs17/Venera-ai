"""Yangilanish xizmati: tekshirish, yuklab olish, o'rnatishni boshlash.

Oqim:
    1. `version.json` o'qiladi (HTTP yoki tarmoq papkasi).
    2. Versiya hozirgisidan yangi bo'lsa - foydalanuvchiga bildiriladi.
    3. Foydalanuvchi tasdiqlaydi -> Setup.exe yuklab olinadi va sha256 tekshiriladi.
    4. `Setup.exe /S` ishga tushiriladi. U ishlayotgan ilovani to'xtatadi,
       fayllarni almashtiradi va ilovani qayta ishga tushiradi.

Xavfsizlik: nazorat yig'indisi mos kelmasa fayl ishga tushirilmaydi.
Manifestda sha256 bo'lmasa ogohlantirish loglanadi.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import __version__, paths
from .manifest import Manifest, UpdateInfo, is_newer
from .source import UpdateSourceError, download, join_location, read_bytes, strip_mark_of_the_web

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
PENDING_MARKER = "pending_update.txt"


@dataclass(frozen=True)
class CheckResult:
    """Tekshiruv natijasi. `info` None bo'lsa yangilanish yo'q."""

    info: UpdateInfo | None = None
    error: str = ""
    checked: bool = False

    @property
    def available(self) -> bool:
        return self.info is not None


class UpdateService:
    """Yangilanishlarni fon rejimida kuzatadi va o'rnatadi.

    Barcha uzoq amallar alohida thread'da bajariladi, natija `on_event`
    orqali qaytariladi - shuning uchun UI hech qachon muzlab qolmaydi.
    """

    def __init__(
        self,
        config,
        on_available: Callable[[UpdateInfo], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        current_version: str = __version__,
    ) -> None:
        self.config = config
        self.on_available = on_available or (lambda _i: None)
        self.on_progress = on_progress or (lambda _d, _t: None)
        self.on_error = on_error or (lambda _m: None)
        self.on_status = on_status or (lambda _m: None)
        self.current_version = current_version

        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pending: UpdateInfo | None = None
        self._last_check: float = 0.0
        self._last_error: str = ""
        self._active_source: str = ""

    # --- holat ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config.update, "enabled", False)) and bool(self.manifest_url)

    @property
    def sources(self) -> list[str]:
        """Manbalar tartib bo'yicha: avval asosiysi, keyin zaxiralar.

        Bitta o'rnatuvchi turli tarmoqlarda ishlashi uchun kerak: ofisda
        tarmoq papkasi ochiq, uyda esa faqat tashqi HTTPS ishlaydi.
        Birinchi javob bergan manba ishlatiladi.
        """
        raw = getattr(self.config.update, "url", "")
        items = list(raw) if isinstance(raw, (list, tuple)) else [raw]
        items += list(getattr(self.config.update, "fallback_urls", None) or [])
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            value = str(item or "").strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @property
    def manifest_url(self) -> str:
        sources = self.sources
        return sources[0] if sources else ""

    @property
    def active_source(self) -> str:
        """Oxirgi marta javob bergan manba."""
        return self._active_source

    @property
    def pending(self) -> UpdateInfo | None:
        return self._pending

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def describe(self) -> str:
        if not self.enabled:
            return "o'chirilgan" if not self.sources else "manzil ko'rsatilmagan"
        if self._pending is not None:
            return f"yangi versiya {self._pending.version} tayyor"
        if self._last_error:
            return f"xato: {self._last_error}"
        if self._last_check:
            return "so'nggi versiya o'rnatilgan"
        return "hali tekshirilmadi"

    # --- hayot sikli ---------------------------------------------------------

    def start(self) -> None:
        """Fon kuzatuvini boshlaydi."""
        if not self.enabled:
            log.info("Yangilanish tekshiruvi o'chirilgan")
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="updater", daemon=True)
        self._thread.start()
        log.info("Yangilanish manbasi: %s", self.manifest_url)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def _loop(self) -> None:
        # Ishga tushishdan keyin darhol emas: mikrofon va tray birinchi bo'lsin
        delay = float(getattr(self.config.update, "startup_delay_seconds", 90.0))
        if getattr(self.config.update, "check_on_start", True):
            if self._stop.wait(delay):
                return
            self.check_async(notify_when_current=False)

        interval = max(0.5, float(getattr(self.config.update, "check_interval_hours", 6.0))) * 3600
        while not self._stop.wait(interval):
            self.check_async(notify_when_current=False)

    # --- tekshirish ----------------------------------------------------------

    def check_async(self, notify_when_current: bool = True) -> None:
        """Tekshiruvni fon thread'ida boshlaydi (UI'ni bloklamaydi)."""
        if self._busy.locked():
            log.debug("Yangilanish amali allaqachon ketmoqda")
            return
        threading.Thread(
            target=self.check, kwargs={"notify_when_current": notify_when_current},
            name="update-check", daemon=True,
        ).start()

    def check(self, notify_when_current: bool = True) -> CheckResult:
        """Manifestni o'qiydi va yangilanish bor-yo'qligini aniqlaydi."""
        if not self.enabled:
            return CheckResult(error="yangilanish o'chirilgan")

        with self._busy:
            self.on_status("Yangilanish tekshirilmoqda...")
            timeout = float(getattr(self.config.update, "timeout_seconds", 20.0))
            no_proxy = bool(getattr(self.config.update, "no_proxy", True))

            manifest: Manifest | None = None
            source_used = ""
            errors: list[str] = []

            for candidate in self.sources:
                try:
                    payload = read_bytes(candidate, timeout=timeout, no_proxy=no_proxy)
                    manifest = Manifest.parse(payload)
                    source_used = candidate
                    break
                except (UpdateSourceError, ValueError) as exc:
                    errors.append(f"{candidate}: {exc}")
                    log.info("Manba javob bermadi (%s): %s", candidate, exc)

            if manifest is None:
                message = errors[0].split(": ", 1)[-1] if errors else "manba yo'q"
                self._last_error = message
                self._last_check = time.time()
                log.warning("Hech qaysi manba javob bermadi: %s", " | ".join(errors))
                if notify_when_current:
                    self.on_error(f"Yangilanish tekshirilmadi: {message}")
                return CheckResult(error=message, checked=True)

            self._active_source = source_used
            if source_used != self.sources[0]:
                log.info("Zaxira manba ishlatildi: %s", source_used)
            self._last_error = ""
            self._last_check = time.time()

            if not is_newer(manifest.version, self.current_version):
                log.info("So'nggi versiya o'rnatilgan (%s)", self.current_version)
                self._pending = None
                if notify_when_current:
                    self.on_status(f"So'nggi versiya o'rnatilgan ({self.current_version})")
                return CheckResult(checked=True)

            if not manifest.applies_to(self.current_version):
                message = (f"Yangi versiya {manifest.version} bor, lekin avval "
                           f"{manifest.min_version} ga yangilash kerak")
                self.on_error(message)
                return CheckResult(error=message, checked=True)

            info = UpdateInfo(
                manifest=manifest,
                current_version=self.current_version,
                download_url=join_location(source_used, manifest.setup.file),
            )
            self._pending = info
            log.info("Yangi versiya topildi: %s -> %s", self.current_version, manifest.version)
            self.on_available(info)
            return CheckResult(info=info, checked=True)

    # --- o'rnatish -----------------------------------------------------------

    def install_async(self, info: UpdateInfo | None = None) -> None:
        target = info or self._pending
        if target is None:
            self.on_error("O'rnatiladigan yangilanish yo'q")
            return
        if self._busy.locked():
            self.on_error("Yangilanish amali allaqachon ketmoqda")
            return
        threading.Thread(target=self.install, args=(target,),
                         name="update-install", daemon=True).start()

    def install(self, info: UpdateInfo) -> bool:
        """Yuklab oladi, tekshiradi va o'rnatuvchini ishga tushiradi."""
        with self._busy:
            folder = paths.state_dir() / "updates"
            destination = folder / Path(info.manifest.setup.file).name

            self.on_status(f"Yangilanish yuklanmoqda ({info.size_mb or '?'} MB)...")
            try:
                download(
                    info.download_url,
                    destination,
                    expected_sha256=info.manifest.setup.sha256,
                    expected_size=info.manifest.setup.size,
                    timeout=float(getattr(self.config.update, "download_timeout_seconds", 600.0)),
                    no_proxy=bool(getattr(self.config.update, "no_proxy", True)),
                    progress=self.on_progress,
                    cancelled=self._stop.is_set,
                )
            except UpdateSourceError as exc:
                self._last_error = str(exc)
                log.warning("Yangilanish yuklanmadi: %s", exc)
                self.on_error(f"Yangilanish yuklanmadi: {exc}")
                return False

            strip_mark_of_the_web(destination)
            self._write_pending_marker(info.version)

            self.on_status("O'rnatilmoqda... Ilova bir necha soniyaga yopiladi.")
            log.info("O'rnatuvchi ishga tushirilmoqda: %s", destination)
            try:
                subprocess.Popen(
                    [str(destination), "/S"],
                    cwd=str(destination.parent),
                    creationflags=CREATE_NO_WINDOW,
                    close_fds=True,
                )
            except Exception as exc:  # noqa: BLE001
                self._clear_pending_marker()
                log.exception("O'rnatuvchi ishga tushmadi")
                self.on_error(f"O'rnatuvchi ishga tushmadi: {exc}")
                return False
            return True

    # --- "yangilandi" xabari -------------------------------------------------

    def _marker_path(self) -> Path:
        return paths.state_dir() / PENDING_MARKER

    def _write_pending_marker(self, version: str) -> None:
        try:
            path = self._marker_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(version, encoding="utf-8")
        except OSError as exc:
            log.debug("Belgi yozilmadi: %s", exc)

    def _clear_pending_marker(self) -> None:
        try:
            self._marker_path().unlink(missing_ok=True)
        except OSError:
            pass

    def consume_completed_update(self) -> str:
        """Ishga tushganda chaqiriladi.

        Oldingi seansda yangilanish boshlangan va endi shu versiya ishlayotgan
        bo'lsa - versiya nomini qaytaradi, shunda foydalanuvchiga "yangilandi"
        deb aytish mumkin.
        """
        path = self._marker_path()
        try:
            if not path.exists():
                return ""
            requested = path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        self._clear_pending_marker()
        if requested and not is_newer(requested, self.current_version):
            return self.current_version
        return ""

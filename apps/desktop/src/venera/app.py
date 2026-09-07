"""Ilovaning yig'ilish nuqtasi: hamma komponent shu yerda bog'lanadi.

Thread tuzilishi:
    asosiy      - tray ikonkasi (pystray.run bloklaydi)
    core        - asyncio sikli (orchestrator)
    hotkey      - RegisterHotKey + xabar sikli
    ui-window   - tkinter oynasi
    audio-*     - PortAudio callback va o'qish
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from . import (APP_DISPLAY_NAME, __version__, config as config_module, events as ev,
               i18n, logging_setup, paths)
from .actions import apps as apps_module
from .actions import phrases as phrases_module
from .actions.base import ActionContext
from .audio.capture import AudioCapture
from .audio.listener import AudioListener
from .audio.player import AudioPlayer
from .core.orchestrator import Orchestrator
from .core.states import State, label
from .engines.activator_hotkey import HotkeyActivator, NullActivator
from .engines.llm_rules import RulesLlm
from .engines.stt_mock import MockStt
from .engines.stt_onprem import OnpremStt
from .engines.tts_sapi import NullTts, SapiTts
from .engines.tts_say import SayTts
from .osadapter import get_adapter
from .ui.tray import Tray
from .ui.window import StatusWindow
from .update import UpdateService

log = logging.getLogger(__name__)


def autostart_command() -> str:
    """Avtostart ishga tushiradigan buyruq (Windows: Task Scheduler, macOS: LaunchAgent)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m venera'


def _platform_tts(voice: str | None, rate: int, volume: int):
    """Joriy OS uchun mos TTS. Qo'llab-quvvatlanmagan OS'da ovozsiz ishlaydi.

    Linux (CI, WSL) da NullTts qaytadi: butun ilovani import qilib testlarni
    ishga tushirish mumkin bo'lishi kerak - osadapter.NullAdapter bilan bir xil
    mantiq.
    """
    if sys.platform == "win32":
        return SapiTts(voice, rate, volume)
    if sys.platform == "darwin":
        return SayTts(voice, rate, volume)
    log.warning("Bu platformada ovoz sintezi yo'q (%s) - ovozsiz ishlaydi", sys.platform)
    return NullTts()


class Application:
    def __init__(self, config_path: Path | None = None, console: bool = False,
                 no_tray: bool = False, no_window: bool = False) -> None:
        self.config_path = config_path
        self.console = console
        self.no_tray = no_tray
        self.no_window = no_window

        self.config = None
        self.warnings: list[str] = []
        self.adapter = None
        self.stt = None
        self.llm = None
        self.tts = None
        self.activator = None
        self.capture = None
        self.listener = None
        self.player = None
        self.orchestrator = None
        self.window = None
        self.tray = None
        self.updater = None
        self._quitting = threading.Event()

    # --- qurish --------------------------------------------------------------

    def bootstrap(self) -> None:
        """Config, loglar va OS adapteri - eng birinchi bo'lib."""
        paths.ensure_dirs()
        created = config_module.install_defaults()
        # Eski versiyadan qolgan config'ga yangi bo'limlarni qo'shamiz,
        # aks holda yangilangan ilovaning yangi sozlamalari ko'rinmay qoladi.
        added_sections = config_module.upgrade_file(self.config_path)
        # Xuddi shu sabab dasturlar katalogi uchun ham: apps.load() foydalanuvchi
        # faylini topsa standartni o'qimaydi, ya'ni yangilanishda qo'shilgan
        # ovozli buyruq (masalan "claude ni och") aks holda hech qachon ishlamaydi.
        added_apps = config_module.upgrade_apps_file()
        self.config, self.warnings = config_module.load(self.config_path)

        logging_setup.setup(
            level=self.config.logging.level,
            max_bytes=self.config.logging.max_bytes,
            backup_count=self.config.logging.backup_count,
            console=True if self.console else None,
        )
        for path in created:
            log.info("Default fayl yaratildi: %s", path)
        if added_sections:
            log.info("Config'ga yangi bo'limlar qo'shildi: %s", ", ".join(added_sections))
        if added_apps:
            log.info("Yangi ovozli buyruqlar qo'shildi: %s", ", ".join(added_apps))
        for warning in self.warnings:
            log.warning("Config: %s", warning)

        # Til BITTA joydan olinadi: STT so'rovi, javob iboralari, intent
        # qoidalari va interfeys matni - hammasi shu paketdan.
        pack = i18n.bind(self.config.language)
        if not pack.ok:
            for problem in i18n.problems():
                log.warning("Til paketi: %s", problem)

        self.adapter = get_adapter()
        log.info("OS adapteri: %s", self.adapter.name)

    def build(self) -> None:
        """Eski nom - moslik uchun; ikkala bosqichni ketma-ket bajaradi."""
        self.build_core()
        self.build_ui()

    def build_core(self) -> None:
        """Engine'lar va orchestrator. config.engines qaysi implementatsiya ekanini hal qiladi."""
        cfg = self.config

        # --- STT ---
        # `onprem` = ovoz haqiqatan tanib olinadi. `mock` da esa buyruq oynadan
        # matn bo'lib keladi va server umuman kerak emas - shuning uchun u
        # default bo'lib qoladi. `config.validate()` allaqachon tekshirgan:
        # url bo'sh bo'lsa engines.stt o'zi `mock` ga qaytariladi.
        if cfg.engines.stt == "onprem":
            self.stt = OnpremStt(
                base_url=cfg.stt.url,
                language=i18n.stt_code(),
                timeout=cfg.timeouts.stt,
                attempts=cfg.stt.attempts,
                no_proxy=cfg.stt.no_proxy,
                verify_tls=cfg.stt.verify_tls,
                max_concurrent=cfg.stt.max_concurrent,
                max_per_minute=cfg.stt.max_per_minute,
            )
            log.info("STT: %s (til: %s)", self.stt.base_url, self.stt.language)
        else:
            self.stt = MockStt()

        # --- LLM ---
        if cfg.engines.llm == "onprem":
            log.warning("engines.llm=onprem hali qo'shilmagan (Step 3) - qoidalar ishlatilmoqda")
        self.llm = RulesLlm()

        # --- TTS ---
        # Platformaning o'z sintezatori: Windows -> SAPI, macOS -> say.
        # Ikkalasi ham vaqtinchalik yechim (o'zbek ovozi yo'q), Step 4 da
        # on-prem TTS ikkalasini ham almashtiradi.
        if not cfg.tts.enabled or cfg.engines.tts == "none":
            self.tts = NullTts()
        else:
            if cfg.engines.tts == "onprem":
                log.warning("engines.tts=onprem hali qo'shilmagan (Step 4) - "
                            "platforma sintezatori ishlatilmoqda")
            self.tts = _platform_tts(cfg.tts.voice, cfg.tts.rate, cfg.tts.volume)
        log.info("Engine'lar: stt=%s llm=%s tts=%s", self.stt.name, self.llm.name, self.tts.name)

        # --- audio ---
        self.player = AudioPlayer()
        self.capture = AudioCapture(
            sample_rate=cfg.audio.sample_rate,
            blocksize=cfg.audio.blocksize,
            device_hint=cfg.audio.input_device,
            on_level=self._on_level,
            on_error=self._on_audio_error,
        )

        # Ovoz yo'li faqat haqiqiy STT bilan mantiqli: mock rejimda buyruq
        # oynaga yoziladi va mikrofon navbatini band qilishning hojati yo'q.
        # Tinglovchi `capture._queue` ning YAGONA iste'molchisi bo'lishi shart.
        if cfg.engines.stt == "onprem":
            self.listener = AudioListener(
                capture=self.capture,
                sample_rate=cfg.audio.sample_rate,
                frame_size=cfg.audio.blocksize,
                on_level=self._on_level,
            )

        # --- harakatlar ---
        context = ActionContext(
            adapter=self.adapter,
            config=cfg,
            phrases=phrases_module.Phrases.load(),
            catalog=apps_module.load(),
        )

        # --- aktivator ---
        if cfg.engines.activator == "wakeword":
            log.warning("engines.activator=wakeword hali qo'shilmagan (Step 5) - hotkey ishlatilmoqda")
        self.activator = HotkeyActivator(cfg.hotkey.modifiers, cfg.hotkey.key)

        # --- orchestrator ---
        self.orchestrator = Orchestrator(
            config=cfg, adapter=self.adapter, stt=self.stt, llm=self.llm, tts=self.tts,
            activator=self.activator, capture=self.capture, player=self.player,
            context=context, on_event=self._on_core_event, listener=self.listener,
        )

    def build_ui(self) -> None:
        """Oyna va tray. Aktivator ishga tushgandan KEYIN chaqiriladi, chunki
        haqiqiy uyg'otish klavishasi shundagina ma'lum bo'ladi (zaxiraga o'tgan bo'lishi mumkin)."""
        cfg = self.config
        self.updater = UpdateService(
            config=cfg,
            on_available=self._on_update_available,
            on_progress=self._on_update_progress,
            on_error=self._on_update_error,
            on_status=self._on_update_status,
        )
        self.window = StatusWindow(
            on_submit=self._on_window_submit,
            on_activate=lambda: self.orchestrator.activate("window"),
            on_cancel=lambda: self.orchestrator.cancel("window"),
            hotkey_label=self.activator.label,
            topmost=cfg.ui.window_topmost,
            on_update=lambda: self.updater.install_async(),
        )
        self.tray = Tray(
            adapter=self.adapter,
            on_activate=lambda: self.orchestrator.activate("tray"),
            on_toggle_window=self._toggle_window,
            on_cancel=lambda: self.orchestrator.cancel("tray"),
            on_reload=self._reload_config,
            on_quit=self.quit,
            hotkey_label=self.activator.label,
            autostart_command=autostart_command(),
            on_check_update=lambda: self.updater.check_async(notify_when_current=True),
            on_install_update=lambda: self.updater.install_async(),
        )
        self.adapter.set_notifier(lambda title, message: self.tray.notify(title, message))

    # --- hodisalar -----------------------------------------------------------

    def _on_level(self, level: float) -> None:
        window = self.window
        if window is not None and window.alive:
            window.set_level(level)

    def _on_audio_error(self, message: str) -> None:
        log.warning("Audio: %s", message)
        if self.tray is not None:
            self.tray.notify(APP_DISPLAY_NAME, message)

    def _on_core_event(self, event: object) -> None:
        if isinstance(event, ev.StateChanged):
            if self.tray is not None:
                self.tray.set_state(event.state, event.detail)
            if self.window is not None and self.window.alive:
                self.window.set_state(event.state, event.detail)
                if event.state == State.CAPTURING.value and self.config.ui.show_window_on_activate:
                    self.window.show()
        elif isinstance(event, ev.TurnFinished):
            line = f"{event.spoken}   [{event.intent}, {event.elapsed_ms} ms]"
            if self.window is not None and self.window.alive:
                self.window.log_line(line, "ok" if event.ok else "error")
        elif isinstance(event, ev.Notice):
            if self.tray is not None:
                self.tray.notify(APP_DISPLAY_NAME, event.message)
            if self.window is not None and self.window.alive:
                self.window.log_line(event.message, "error" if event.level == "error" else "info")

    # --- yangilanish hodisalari ---------------------------------------------

    def _on_update_available(self, info) -> None:
        log.info("Yangilanish mavjud: %s", info.describe())
        if self.tray is not None:
            self.tray.set_update_available(info.version)
            self.tray.notify(
                APP_DISPLAY_NAME,
                f"Yangi versiya {info.version} mavjud. Yangilash uchun bosing.",
            )
        if self.window is not None and self.window.alive:
            note = info.manifest.notes
            text = f"Yangi versiya {info.version} mavjud"
            if info.size_mb:
                text += f"  ({info.size_mb} MB)"
            if note:
                text += f"\n{note}"
            # Fon tekshiruvi oynani ko'tarmaydi - foydalanuvchi ishlayotgan
            # dastur ustiga otilib chiqish o'rniga tray bildirishnomasi va tray
            # menyusidagi yozuv orqali bildiriladi. Panel oyna ochilganda
            # joyida turadi.
            self.window.show_update(text, raise_window=self.updater.user_initiated)
            self.window.log_line(info.describe(), "info")

        if getattr(self.config.update, "auto_install", False):
            log.info("auto_install yoqilgan - yangilanish so'ramasdan o'rnatilmoqda")
            self.updater.install_async(info)

    def _on_update_progress(self, done: int, total: int) -> None:
        if self.window is not None and self.window.alive:
            self.window.set_update_progress(done, total)

    def _on_update_error(self, message: str) -> None:
        log.warning("Yangilanish: %s", message)
        if self.window is not None and self.window.alive:
            self.window.log_line(message, "error")
            self.window.hide_update()
        if self.tray is not None:
            self.tray.notify(APP_DISPLAY_NAME, message)

    def _on_update_status(self, message: str) -> None:
        log.info("Yangilanish: %s", message)
        if self.window is not None and self.window.alive:
            self.window.log_line(message, "info")

    def _on_window_submit(self, text: str) -> None:
        self.orchestrator.submit_text(text, source="window")

    def _toggle_window(self) -> None:
        window = self.window
        if window is None:
            return
        if not window.alive:
            window.start(visible=True)
            return
        window.toggle()

    def _reload_config(self) -> None:
        new_config, warnings = config_module.load(self.config_path)
        for warning in warnings:
            log.warning("Config: %s", warning)
        # Qayta ishga tushirishsiz o'zgaradigan qismlar
        self.config.timeouts = new_config.timeouts
        self.config.actions = new_config.actions
        self.config.ui = new_config.ui
        self.orchestrator.ctx.config = self.config
        self.orchestrator.ctx.catalog = apps_module.load()
        self.orchestrator.ctx.phrases = phrases_module.Phrases.load()
        log.info("Sozlamalar qayta yuklandi")
        if self.tray is not None:
            self.tray.notify(APP_DISPLAY_NAME, "Sozlamalar qayta yuklandi")

    # --- hayot sikli ---------------------------------------------------------

    def run(self) -> int:
        self.bootstrap()

        if not self.adapter.acquire_single_instance("Local\\VeneraAIAssistant"):
            log.warning("Ilova allaqachon ishlayapti - chiqilmoqda")
            return 3

        self.build_core()
        self.orchestrator.start()

        if self.capture.start():
            log.info("Mikrofon: %s", self.capture.device.label() if self.capture.device else "?")
        else:
            log.warning("Mikrofonsiz davom etilmoqda - buyruq matn bilan kiritiladi")

        # Tinglovchi capture'dan KEYIN: u navbatning yagona o'quvchisi bo'lishi
        # kerak. Ishga tushmasa ilova yiqilmaydi - matn yo'li ishlayveradi.
        if self.listener is not None and not self.listener.start():
            log.warning("Ovoz yo'li ishga tushmadi (%s) - buyruq matn bilan kiritiladi",
                        self.listener.error or "noma'lum sabab")

        # Aktivator UI'dan OLDIN ishga tushadi: klavisha band bo'lsa zaxiraga
        # o'tadi va tray/oyna darhol to'g'ri nomni ko'rsatadi.
        hotkey_ok = self.activator.start(lambda: self.orchestrator.activate("hotkey"))

        self.build_ui()

        if not self.no_window:
            if self.window.start(visible=not self.config.ui.start_minimized):
                self.window.log_line(f"{APP_DISPLAY_NAME} v{__version__} ishga tushdi", "info")
                self._report_startup(hotkey_ok)
            else:
                log.warning("Holat oynasi ochilmadi: %s", self.window.error)

        if not hotkey_ok:
            message = self.activator.error or "klavisha ro'yxatdan o'tmadi"
            log.warning("Uyg'otish klavishasi yoqilmadi: %s", message)

        # Oldingi seansda yangilanish boshlangan bo'lsa - natijani bildiramiz
        updated_to = self.updater.consume_completed_update()
        if updated_to:
            log.info("Ilova %s versiyasiga yangilandi", updated_to)
            if self.window is not None and self.window.alive:
                self.window.log_line(f"Ilova {updated_to} versiyasiga yangilandi", "ok")
            if self.tray is not None:
                self.tray.notify(APP_DISPLAY_NAME, f"{updated_to} versiyasiga yangilandi")
        elif self.updater.failed_update_version:
            # Foydalanuvchi "Yangilash" ni bosgan, o'rnatuvchi ishga tushgan,
            # lekin fayllar almashmagan. Ilgari bu jimgina o'tib ketardi va
            # 6 soatdan keyin xuddi shu taklif qayta chiqardi.
            failed = self.updater.failed_update_version
            log.warning("Yangilanish %s ga o'tmadi", failed)
            message = (f"{failed} o'rnatilmadi - ilova hali {__version__}. "
                       f"Sabab: {self.updater.setup_log_path()}")
            if self.window is not None and self.window.alive:
                self.window.log_line(message, "error")
            if self.tray is not None:
                self.tray.notify(APP_DISPLAY_NAME, f"{failed} o'rnatilmadi. Loglarni qarang.")

        self.updater.start()

        if self.no_tray or not self.tray.run():
            log.info("Tray ikonkasisiz ishlamoqda - to'xtatish uchun Ctrl+C")
            try:
                self._quitting.wait()
            except KeyboardInterrupt:
                pass

        self.shutdown()
        return 0

    def _report_startup(self, hotkey_ok: bool = True) -> None:
        window = self.window
        if window is None or not window.alive:
            return
        if self.capture.running and self.capture.device is not None:
            window.log_line(f"Mikrofon: {self.capture.device.name}", "info")
        else:
            window.log_line("Mikrofon ochilmadi - buyruqni matn bilan yozing", "error")
        if self.listener is not None and self.listener.running:
            window.log_line(f"Ovoz bilan boshqaruv yoqilgan (til: {i18n.stt_code()})", "ok")
        elif self.listener is not None:
            window.log_line("Ovoz yo'li ishga tushmadi - buyruqni matn bilan yozing", "error")
        if not hotkey_ok:
            window.log_line(
                f"Uyg'otish klavishasi ishlamadi: {self.activator.error}. "
                "Oynadan yoki tray menyusidan foydalaning.", "error",
            )
        elif getattr(self.activator, "fell_back", False):
            window.log_line(
                f"Uyg'otish klavishasi: {self.activator.label} "
                "(sozlamadagi kombinatsiya band edi)", "info",
            )
        elif self.activator.label:
            window.log_line(f"Uyg'otish klavishasi: {self.activator.label}", "info")
        status = self.adapter.autostart_status()
        window.log_line(
            "Avtostart yoqilgan" if status.installed
            else "Avtostart o'chirilgan (tray menyusidan yoqing)", "info",
        )

    def quit(self) -> None:
        if self._quitting.is_set():
            return
        log.info("Chiqish so'raldi")
        self._quitting.set()
        if self.tray is not None:
            self.tray.stop()

    def shutdown(self) -> None:
        log.info("To'xtatilmoqda...")
        for name, action in (
            ("yangilanish", lambda: self.updater and self.updater.stop()),
            ("aktivator", lambda: self.activator and self.activator.stop()),
            ("oyna", lambda: self.window and self.window.stop()),
            ("tinglovchi", lambda: self.listener and self.listener.stop()),
            ("mikrofon", lambda: self.capture and self.capture.stop()),
            ("ijro", lambda: self.player and self.player.stop()),
            ("core", lambda: self.orchestrator and self.orchestrator.stop()),
        ):
            try:
                action()
            except Exception:  # noqa: BLE001
                log.debug("%s to'xtatishda xato", name, exc_info=True)
        log.info("%s to'xtadi", APP_DISPLAY_NAME)


def run_check(config_path: Path | None = None) -> int:
    """--check: hamma narsa joyidami degan savolga javob."""
    import asyncio

    app = Application(config_path=config_path, console=True)
    app.bootstrap()
    app.build()

    lines: list[str] = [f"{APP_DISPLAY_NAME} v{__version__}", ""]

    lines.append("Yo'llar:")
    for key, value in paths.describe().items():
        lines.append(f"  {key:14} {value}")

    lines.append("")
    lines.append("Sozlamalar:")
    source = str(app.config.source_path) if app.config.source_path else "default (fayl topilmadi)"
    lines.append(f"  manba          {source}")
    lines.append(f"  engines        stt={app.config.engines.stt} llm={app.config.engines.llm} "
                 f"tts={app.config.engines.tts} activator={app.config.engines.activator}")
    for warning in app.warnings:
        lines.append(f"  ! {warning}")

    lines.append("")
    lines.append(f"OS adapteri: {app.adapter.name}")
    for key, value in app.adapter.describe().items():
        lines.append(f"  {key:14} {value}")

    lines.append("")
    lines.append(f"Uyg'otish: {app.activator.label}")

    lines.append("")
    lines.append("Til:")
    for key, value in i18n.describe().items():
        lines.append(f"  {key:14} {value}")
    for problem in i18n.problems():
        lines.append(f"  ! {problem}")

    lines.append("")
    source = "mikrofon (ovoz)" if app.listener is not None else "oyna (matn)"
    lines.append(f"Buyruq manbai: {source}")

    lines.append("")
    from .audio import capture as capture_module

    devices = capture_module.list_input_devices()
    lines.append(f"Mikrofonlar ({len(devices)} ta):")
    if not devices:
        lines.append(f"  yo'q - {capture_module.SOUNDDEVICE_ERROR or 'qurilma topilmadi'}")
    for device in devices:
        lines.append(f"  {device.label()}")

    lines.append("")
    lines.append(f"Dasturlar katalogi: {len(app.orchestrator.ctx.catalog.entries)} ta "
                 f"({apps_module.FUZZY_BACKEND})")

    async def engine_health() -> list[str]:
        result = []
        for engine in (app.stt, app.llm, app.tts):
            try:
                status = await engine.health()
            except Exception as exc:  # noqa: BLE001
                status = f"xato: {exc}"
            result.append(f"  {engine.name:8} {status}")
        return result

    lines.append("")
    lines.append("Engine'lar:")
    lines.extend(asyncio.run(engine_health()))

    lines.append("")
    lines.append("Yangilanish:")
    source_url = app.config.update.url or "(ko'rsatilmagan)"
    lines.append(f"  manba          {source_url}")
    lines.append(f"  holat          {app.updater.describe()}")
    if app.config.update.url:
        result = app.updater.check(notify_when_current=False)
        if result.available and result.info is not None:
            lines.append(f"  natija         {result.info.describe()}")
        elif result.error:
            lines.append(f"  natija         xato: {result.error}")
        else:
            lines.append("  natija         so'nggi versiya o'rnatilgan")

    lines.append("")
    lines.append(f"Tray: {'mavjud' if app.tray.available else 'mavjud emas - ' + str(app.tray.error)}")

    report = "\n".join(lines)
    log.debug("Tekshiruv natijasi:\n%s", report)
    if sys.stdout is not None:
        print(report)
    return 0

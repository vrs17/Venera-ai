"""Buyruq satri.

    python -m venera                 # tray rejimida ishga tushirish
    python -m venera --check         # diagnostika
    python -m venera --console       # loglarni konsolga ham chiqarish
    python -m venera --install-autostart
    python -m venera --remove-autostart
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_DISPLAY_NAME, __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="venera",
        description=f"{APP_DISPLAY_NAME} - ovozli desktop yordamchi",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.yaml yo'li (default: %%APPDATA%%\\Venera\\config.yaml)")
    parser.add_argument("--check", action="store_true",
                        help="sozlamalar, mikrofon va engine'larni tekshirib chiqadi")
    parser.add_argument("--console", action="store_true",
                        help="loglarni konsolga ham chiqaradi")
    parser.add_argument("--no-tray", action="store_true",
                        help="tray ikonkasisiz ishga tushirish")
    parser.add_argument("--no-window", action="store_true",
                        help="holat oynasisiz ishga tushirish")
    parser.add_argument("--install-autostart", action="store_true",
                        help="tizimga kirganda avtomatik ishga tushishni yoqadi")
    parser.add_argument("--remove-autostart", action="store_true",
                        help="avtomatik ishga tushishni o'chiradi")
    parser.add_argument("--set-update-url", metavar="MANZIL", default=None,
                        help="yangilanish manzilini o'rnatadi; bir nechtasini "
                             "'|' bilan ajrating (birinchisi asosiy, qolganlari zaxira)")
    parser.add_argument("--update", action="store_true",
                        help="yangilanishni tekshiradi va bo'lsa o'rnatadi")
    parser.add_argument("--check-update", action="store_true",
                        help="faqat tekshiradi, o'rnatmaydi")
    parser.add_argument("--uninstall", action="store_true",
                        help="ilovani kompyuterdan o'chiradi")
    parser.add_argument("--silent", action="store_true",
                        help="--uninstall bilan: tasdiq so'ramaydi")
    parser.add_argument("--keep-settings", action="store_true",
                        help="--uninstall bilan: sozlamalar va loglarni saqlab qoladi")
    return parser


def _set_update_url(url: str, config_path: Path | None) -> int:
    """config.yaml dagi yangilanish manzillarini o'rnatadi.

    Bir nechta manzil '|' bilan beriladi: birinchisi asosiy, qolganlari zaxira.
    Shu tufayli bitta o'rnatuvchi ham ofisdagi (tarmoq papkasi), ham tashqaridagi
    (HTTPS) kompyuterlarda ishlaydi - qaysi manba ochiq bo'lsa, o'sha ishlatiladi.

    Izohlar va boshqa sozlamalar saqlanadi, faqat kerakli qatorlar o'zgaradi.
    """
    import re

    from . import config as config_module, logging_setup, paths

    logging_setup.setup(console=True)
    paths.ensure_dirs()
    config_module.install_defaults()
    config_module.upgrade_file(config_path)
    config_module.upgrade_apps_file()

    target = Path(config_path) if config_path else paths.config_file()
    if not target.exists():
        print(f"config topilmadi: {target}")
        return 1

    parts = [item.strip() for item in str(url).split("|") if item.strip()]
    if not parts:
        print("Manzil bo'sh")
        return 1
    primary, fallbacks = parts[0], parts[1:]

    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    text = target.read_text(encoding="utf-8")

    url_pattern = re.compile(
        r"^(update:\s*(?:\n(?:[ \t]+.*|\s*#.*|)$)*?\n[ \t]+url:[ \t]*).*$", re.MULTILINE)
    text, count = url_pattern.subn(lambda m: f"{m.group(1)}{quote(primary)}", text, count=1)
    if count == 0:
        print("config ichida update.url qatori topilmadi")
        return 1

    fallback_pattern = re.compile(r"^([ \t]+fallback_urls:[ \t]*)(\[\]|)$", re.MULTILINE)
    if fallbacks:
        indent = "  "
        block = "\n".join(f"{indent}  - {quote(item)}" for item in fallbacks)
        text, replaced = fallback_pattern.subn(
            lambda m: f"{m.group(1).rstrip()}\n{block}", text, count=1)
        if replaced == 0:
            print("ogohlantirish: fallback_urls qatori topilmadi, faqat asosiy manzil yozildi")
    else:
        text = fallback_pattern.sub(lambda m: f"{m.group(1)}[]", text, count=1)

    target.write_text(text, encoding="utf-8")
    print(f"Yangilanish manzili o'rnatildi: {primary}")
    for item in fallbacks:
        print(f"  zaxira: {item}")
    print(f"  {target}")
    return 0


def _update(install: bool, config_path: Path | None) -> int:
    """--update / --check-update: buyruq satridan yangilanish.

    IT bo'limi ommaviy yangilash uchun ham shu yo'ldan foydalanadi:
        Venera.exe --update
    """
    from . import config as config_module, logging_setup
    from .update import UpdateService

    logging_setup.setup(console=True)
    cfg, warnings = config_module.load(config_path)
    for warning in warnings:
        print(f"config: {warning}")

    service = UpdateService(config=cfg)
    if not service.enabled:
        print("Yangilanish manzili ko'rsatilmagan (config.yaml -> update.url)")
        return 2

    result = service.check(notify_when_current=False)
    if result.error:
        print(f"Xato: {result.error}")
        return 1
    if not result.available or result.info is None:
        print(f"So'nggi versiya o'rnatilgan ({service.current_version})")
        return 0

    info = result.info
    print(f"Yangi versiya: {info.current_version} -> {info.version}")
    if info.manifest.notes:
        print(f"Izoh: {info.manifest.notes}")
    if not install:
        return 0

    print("Yuklab olinmoqda va o'rnatilmoqda...")
    if service.install(info):
        print("O'rnatuvchi ishga tushdi. Ilova bir necha soniyada yangilanadi.")
        return 0
    print(f"Yangilanmadi: {service.last_error}")
    return 1


def _confirm_uninstall() -> bool:
    """Tasdiq oynasi. Oyna ochilmasa - tasdiqlangan deb hisoblanadi."""
    try:
        import ctypes

        MB_YESNO, MB_ICONQUESTION, IDYES = 0x04, 0x20, 6
        answer = ctypes.windll.user32.MessageBoxW(
            None,
            f"{APP_DISPLAY_NAME} kompyuterdan o'chirilsinmi?",
            APP_DISPLAY_NAME,
            MB_YESNO | MB_ICONQUESTION,
        )
        return answer == IDYES
    except Exception:  # noqa: BLE001
        return True


def _uninstall(silent: bool, keep_settings: bool) -> int:
    from . import logging_setup
    from .osadapter.install import uninstall

    logging_setup.setup(console=True)

    if not silent and not _confirm_uninstall():
        return 1

    # Ishlayotgan nusxani to'xtatamiz, aks holda fayllar band bo'ladi.
    # DIQQAT: o'chirishni ham AYNAN SHU exe bajaradi, shuning uchun o'z
    # jarayonimizni filtrdan chiqarib tashlaymiz - aks holda taskkill
    # o'zimizni o'ldiradi va o'chirish yarim yo'lda to'xtaydi.
    import os
    import subprocess

    try:
        subprocess.run(
            ["taskkill", "/IM", "Venera.exe", "/F",
             "/FI", f"PID ne {os.getpid()}"],
            capture_output=True, timeout=20, creationflags=0x08000000,
        )
    except Exception:  # noqa: BLE001
        pass

    steps = uninstall(keep_settings=keep_settings)
    message = "\n".join(f"- {step}" for step in steps)
    if sys.stdout is not None:
        print(f"{APP_DISPLAY_NAME} o'chirilmoqda:\n{message}")
    if not silent:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"{APP_DISPLAY_NAME} o'chirildi.\n\n{message}",
                APP_DISPLAY_NAME, 0x40,
            )
        except Exception:  # noqa: BLE001
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from .app import Application, autostart_command, run_check

    if args.check:
        return run_check(args.config)

    if args.set_update_url is not None:
        return _set_update_url(args.set_update_url, args.config)

    if args.update or args.check_update:
        return _update(install=args.update, config_path=args.config)

    if args.uninstall:
        return _uninstall(silent=args.silent, keep_settings=args.keep_settings)

    if args.install_autostart or args.remove_autostart:
        from . import logging_setup
        from .osadapter import get_adapter

        logging_setup.setup(console=True)
        adapter = get_adapter()
        status = (adapter.autostart_remove() if args.remove_autostart
                  else adapter.autostart_install(autostart_command()))
        message = (f"Avtostart: {'yoqilgan' if status.installed else 'yoqilmagan'}"
                   f"{' - ' + status.detail if status.detail else ''}")
        if sys.stdout is not None:
            print(message)
        return 0 if (status.installed != args.remove_autostart) else 1

    app = Application(
        config_path=args.config, console=args.console,
        no_tray=args.no_tray, no_window=args.no_window,
    )
    try:
        return app.run()
    except KeyboardInterrupt:
        app.shutdown()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

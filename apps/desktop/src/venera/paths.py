"""Fayl yo'llari: config, loglar, resurslar.

PyInstaller bilan "frozen" holatda ham, oddiy dev rejimida ham ishlaydi.
Har bir OS o'zining kelishuviga amal qiladi:

    Windows   %APPDATA%\\Venera            %LOCALAPPDATA%\\Venera
    macOS     ~/Library/Application Support/Venera,  loglar ~/Library/Logs/Venera
    boshqa    XDG ($XDG_CONFIG_HOME, $XDG_STATE_HOME)

macOS'da XDG ishlatilmaydi: foydalanuvchi loglarni Console.app da
~/Library/Logs ostidan izlaydi va ~/.local/state ni Finder umuman
ko'rsatmaydi (nuqtali papka yashirin).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_FROZEN = getattr(sys, "frozen", False)


def _env_dir(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else fallback


def _macos_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def config_dir() -> Path:
    """Foydalanuvchi sozlamalari (config.yaml, apps.yaml)."""
    if IS_WINDOWS:
        return _env_dir("APPDATA", Path.home() / "AppData" / "Roaming") / APP_NAME
    if IS_MACOS:
        return _macos_support_dir()
    return _env_dir("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME.lower()


def state_dir() -> Path:
    """O'zgaruvchan ma'lumot: kesh, yangilanish fayllari, comtypes gen."""
    if IS_WINDOWS:
        return _env_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / APP_NAME
    if IS_MACOS:
        # macOS'da sozlama va holat bitta papkada turishi normal - Apple
        # "Application Support" ni aynan shu maqsad uchun beradi.
        return _macos_support_dir()
    return _env_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME.lower()


def config_file() -> Path:
    return config_dir() / "config.yaml"


def apps_file() -> Path:
    return config_dir() / "apps.yaml"


def log_dir() -> Path:
    # macOS: Console.app aynan shu yerdan o'qiydi, foydalanuvchi ham loglarni
    # shu yerdan izlaydi.
    if IS_MACOS:
        return Path.home() / "Library" / "Logs" / APP_NAME
    return state_dir() / "logs"


def log_file() -> Path:
    return log_dir() / "assistant.log"


def crash_file() -> Path:
    return log_dir() / "crash.log"


def comtypes_gen_dir() -> Path:
    """comtypes frozen holatda yozish mumkin bo'lgan papkaga generatsiya qilishi kerak."""
    return state_dir() / "comtypes_gen"


def debug_audio_dir() -> Path:
    return state_dir() / "debug_audio"


def resources_dir() -> Path:
    """Paket bilan birga keladigan resurslar (default config, iconlar)."""
    if IS_FROZEN:
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "venera" / "resources"
        if candidate.is_dir():
            return candidate
        return base / "resources"
    return Path(__file__).resolve().parent / "resources"


def resource(*parts: str) -> Path:
    return resources_dir().joinpath(*parts)


def pictures_dir() -> Path:
    """Skrinshotlar uchun standart papka."""
    if IS_WINDOWS:
        userprofile = _env_dir("USERPROFILE", Path.home())
        return userprofile / "Pictures"
    return Path.home() / "Pictures"


def ensure_dirs() -> None:
    """Kerakli papkalarni yaratadi. Ishga tushishda bir marta chaqiriladi."""
    for path in (config_dir(), state_dir(), log_dir()):
        path.mkdir(parents=True, exist_ok=True)


def describe() -> dict[str, str]:
    """--check uchun: barcha yo'llarni ko'rsatadi."""
    return {
        "config_dir": str(config_dir()),
        "config_file": str(config_file()),
        "apps_file": str(apps_file()),
        "log_file": str(log_file()),
        "resources": str(resources_dir()),
        "frozen": str(IS_FROZEN),
        "platform": sys.platform,
    }

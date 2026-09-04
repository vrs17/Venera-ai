"""Fayl yo'llari: config, loglar, resurslar.

PyInstaller bilan "frozen" holatda ham, oddiy dev rejimida ham ishlaydi.
Windows'da %APPDATA% / %LOCALAPPDATA%, boshqa OS'da XDG yo'llari.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME

IS_WINDOWS = sys.platform == "win32"
IS_FROZEN = getattr(sys, "frozen", False)


def _env_dir(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else fallback


def config_dir() -> Path:
    """Foydalanuvchi sozlamalari (config.yaml, apps.yaml)."""
    if IS_WINDOWS:
        return _env_dir("APPDATA", Path.home() / "AppData" / "Roaming") / APP_NAME
    return _env_dir("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME.lower()


def state_dir() -> Path:
    """O'zgaruvchan ma'lumot: loglar, kesh, comtypes gen."""
    if IS_WINDOWS:
        return _env_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / APP_NAME
    return _env_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME.lower()


def config_file() -> Path:
    return config_dir() / "config.yaml"


def apps_file() -> Path:
    return config_dir() / "apps.yaml"


def log_dir() -> Path:
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

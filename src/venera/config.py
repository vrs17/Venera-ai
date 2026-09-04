"""Sozlamalar: dataclass default'lar + YAML ustiga qo'yish.

config.yaml topilmasa default'lar ishlatiladi va namuna fayl yozib qo'yiladi.
Noto'g'ri kalit yoki qiymat butun ilovani yiqitmaydi - ogohlantirish loglanadi.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from . import paths

log = logging.getLogger(__name__)


@dataclass
class EnginesConfig:
    """Qaysi implementatsiya ishlatilishi. Step 2+ shu yerdan almashtiriladi."""

    activator: str = "hotkey"   # hotkey | wakeword (Step 5)
    stt: str = "mock"           # mock | onprem (Step 2)
    llm: str = "rules"          # rules | onprem (Step 3)
    tts: str = "sapi"           # sapi | onprem (Step 4) | none


@dataclass
class HotkeyConfig:
    modifiers: list[str] = field(default_factory=lambda: ["ctrl", "alt"])
    key: str = "space"


@dataclass
class AudioConfig:
    input_device: str | None = None   # None = tizim default; yoki qurilma nomining bir qismi
    sample_rate: int = 16000
    channels: int = 1
    blocksize: int = 512
    save_debug_wav: bool = False


@dataclass
class TtsConfig:
    voice: str | None = None    # SAPI ovoz nomining bir qismi, masalan "Irina"
    rate: int = 0               # -10..10
    volume: int = 100           # 0..100
    enabled: bool = True


@dataclass
class UiConfig:
    show_window_on_activate: bool = True
    start_minimized: bool = True
    window_topmost: bool = False


@dataclass
class ActionsConfig:
    screenshot_dir: str | None = None    # None = Pictures/Venera
    search_url: str = "https://www.google.com/search?q={query}"
    volume_step: int = 10


@dataclass
class TimeoutsConfig:
    capturing: float = 15.0
    thinking: float = 2.0
    acting: float = 5.0
    tts_synth: float = 10.0
    playback: float = 30.0


@dataclass
class UpdateConfig:
    """Yangilanishlarni qayerdan olish.

    `url` - version.json manzili. Uch xil bo'lishi mumkin:
        http://10.10.50.9:8000/updates/version.json   ichki HTTP server
        \\\\fileserver\\venera\\assistant\\version.json  tarmoq papkasi
        C:\\updates\\venera\\version.json                 lokal papka (sinov uchun)
    Bo'sh bo'lsa yangilanish tekshirilmaydi.
    """

    enabled: bool = True
    url: str = ""
    #: Asosiy manzil ishlamasa navbat bilan sinaladigan zaxira manzillar.
    #: Ofisda tarmoq papkasi, uydan/VPN'siz esa tashqi HTTPS - bitta o'rnatuvchi
    #: ikkala holatda ham ishlaydi.
    fallback_urls: list[str] = field(default_factory=list)
    check_on_start: bool = True
    check_interval_hours: float = 6.0
    startup_delay_seconds: float = 90.0
    timeout_seconds: float = 20.0
    download_timeout_seconds: float = 600.0
    no_proxy: bool = True          # ichki serverlar korporativ proksi orqali ketmasin
    auto_install: bool = False     # true bo'lsa so'ramasdan o'rnatadi (IT uchun)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_transcripts: bool = False
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 5


@dataclass
class Config:
    engines: EnginesConfig = field(default_factory=EnginesConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    timeouts: TimeoutsConfig = field(default_factory=TimeoutsConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("source_path", None)
        return data


def _merge_section(target: Any, data: Any, prefix: str, warnings: list[str]) -> None:
    """YAML bo'limini dataclass ustiga qo'yadi. Noma'lum kalitlar ogohlantiriladi."""
    if not isinstance(data, dict):
        warnings.append(f"{prefix}: dict kutilgan edi, {type(data).__name__} keldi - o'tkazib yuborildi")
        return

    known = {f.name: f for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            warnings.append(f"{prefix}.{key}: noma'lum kalit - e'tiborsiz qoldirildi")
            continue
        current = getattr(target, key)
        if is_dataclass(current) and not isinstance(current, type):
            _merge_section(current, value, f"{prefix}.{key}", warnings)
        else:
            setattr(target, key, value)


def load(path: Path | None = None) -> tuple[Config, list[str]]:
    """Config yuklaydi. (config, ogohlantirishlar) qaytaradi - hech qachon exception tashlamaydi."""
    cfg = Config()
    warnings: list[str] = []
    target = Path(path) if path else paths.config_file()

    if not target.exists():
        warnings.append(f"config topilmadi ({target}) - default sozlamalar ishlatilmoqda")
        return cfg, warnings

    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - config xatosi ilovani yiqitmasligi kerak
        warnings.append(f"config o'qilmadi ({target}): {exc} - default sozlamalar ishlatilmoqda")
        return cfg, warnings

    _merge_section(cfg, raw, "config", warnings)
    cfg.source_path = target
    warnings.extend(validate(cfg))
    return cfg, warnings


def validate(cfg: Config) -> list[str]:
    """Qiymatlarni tekshiradi va xavfsiz chegaralarga keltiradi."""
    problems: list[str] = []

    if cfg.audio.sample_rate not in (8000, 16000, 22050, 44100, 48000):
        problems.append(f"audio.sample_rate={cfg.audio.sample_rate} g'alati - 16000 ga qaytarildi")
        cfg.audio.sample_rate = 16000
    if cfg.audio.channels != 1:
        problems.append("audio.channels faqat 1 (mono) bo'lishi mumkin - tuzatildi")
        cfg.audio.channels = 1
    if not 64 <= cfg.audio.blocksize <= 8192:
        problems.append(f"audio.blocksize={cfg.audio.blocksize} chegaradan tashqarida - 512 ga qaytarildi")
        cfg.audio.blocksize = 512

    if not -10 <= cfg.tts.rate <= 10:
        problems.append("tts.rate -10..10 oralig'ida bo'lishi kerak - 0 ga qaytarildi")
        cfg.tts.rate = 0
    if not 0 <= cfg.tts.volume <= 100:
        problems.append("tts.volume 0..100 oralig'ida bo'lishi kerak - 100 ga qaytarildi")
        cfg.tts.volume = 100

    if not 1 <= cfg.actions.volume_step <= 50:
        problems.append("actions.volume_step 1..50 oralig'ida bo'lishi kerak - 10 ga qaytarildi")
        cfg.actions.volume_step = 10
    if "{query}" not in cfg.actions.search_url:
        problems.append("actions.search_url ichida {query} yo'q - default'ga qaytarildi")
        cfg.actions.search_url = ActionsConfig.search_url

    for name in ("capturing", "thinking", "acting", "tts_synth", "playback"):
        value = getattr(cfg.timeouts, name)
        if not isinstance(value, (int, float)) or value <= 0:
            default = getattr(TimeoutsConfig(), name)
            problems.append(f"timeouts.{name}={value} noto'g'ri - {default} ga qaytarildi")
            setattr(cfg.timeouts, name, default)

    if cfg.update.check_interval_hours < 0.5:
        problems.append("update.check_interval_hours kamida 0.5 bo'lishi kerak - 6.0 ga qaytarildi")
        cfg.update.check_interval_hours = 6.0
    if cfg.update.url and not str(cfg.update.url).strip():
        cfg.update.url = ""

    level = str(cfg.logging.level).upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        problems.append(f"logging.level={cfg.logging.level} noma'lum - INFO ga qaytarildi")
        level = "INFO"
    cfg.logging.level = level

    valid = {
        "activator": {"hotkey", "wakeword"},
        "stt": {"mock", "onprem"},
        "llm": {"rules", "onprem"},
        "tts": {"sapi", "onprem", "none"},
    }
    for name, allowed in valid.items():
        value = getattr(cfg.engines, name)
        if value not in allowed:
            default = getattr(EnginesConfig(), name)
            problems.append(f"engines.{name}={value!r} noma'lum ({sorted(allowed)}) - {default!r} ga qaytarildi")
            setattr(cfg.engines, name, default)

    return problems


def _split_top_level_blocks(text: str) -> "dict[str, str]":
    """YAML matnini yuqori darajadagi kalitlar bo'yicha bo'laklarga ajratadi.

    Har bir bo'lakka undan oldingi izohlar ham kiradi, shunda yangi bo'lim
    foydalanuvchi fayliga tushuntirishlari bilan birga ko'chadi.
    """
    blocks: dict[str, str] = {}
    pending: list[str] = []
    current_key: str | None = None
    current: list[str] = []

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        is_top_level = (
            stripped
            and not stripped[0].isspace()
            and not stripped.lstrip().startswith("#")
            and ":" in stripped
        )
        if is_top_level:
            if current_key is not None:
                blocks[current_key] = "".join(current)
            current_key = stripped.split(":", 1)[0].strip()
            current = pending + [line]
            pending = []
        elif current_key is None:
            if stripped.lstrip().startswith("#") or not stripped:
                pending.append(line)
        else:
            # Izohlar bloki keyingi kalitga tegishli bo'lishi mumkin
            if stripped.lstrip().startswith("#") and current and current[-1].strip() == "":
                pending.append(line)
            elif not stripped and pending:
                pending.append(line)
            else:
                current.extend(pending)
                pending = []
                current.append(line)

    if current_key is not None:
        blocks[current_key] = "".join(current)
    return blocks


def upgrade_file(path: Path | None = None) -> list[str]:
    """Foydalanuvchi config'iga yangi versiyada paydo bo'lgan bo'limlarni qo'shadi.

    Mavjud sozlamalarga tegilmaydi - faqat yetishmayotgan yuqori darajadagi
    bo'limlar fayl oxiriga izohlari bilan qo'shiladi. Shu tufayli eski
    kompyuterda yangilangan ilova yangi imkoniyatlarni ham ko'rsatadi
    (masalan `update:` bo'limi).

    Qo'shilgan bo'limlar nomlarini qaytaradi.
    """
    target = Path(path) if path else paths.config_file()
    template = paths.resource("config.default.yaml")
    if not target.exists() or not template.exists():
        return []

    try:
        user_text = target.read_text(encoding="utf-8")
        default_text = template.read_text(encoding="utf-8")
        user_data = yaml.safe_load(user_text) or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("Config yangilanmadi (%s): %s", target, exc)
        return []

    if not isinstance(user_data, dict):
        return []

    blocks = _split_top_level_blocks(default_text)
    missing = [key for key in blocks if key not in user_data]
    if not missing:
        return []

    addition = ["\n"]
    for key in missing:
        addition.append("\n" + blocks[key].strip("\n") + "\n")

    try:
        backup = target.with_suffix(".yaml.bak")
        backup.write_text(user_text, encoding="utf-8")
        target.write_text(user_text.rstrip("\n") + "\n" + "".join(addition), encoding="utf-8")
    except OSError as exc:
        log.warning("Config yozilmadi (%s): %s", target, exc)
        return []

    log.info("Config'ga yangi bo'limlar qo'shildi: %s (zaxira: %s)", ", ".join(missing), backup.name)
    return missing


def install_defaults() -> list[Path]:
    """config.yaml va apps.yaml bo'lmasa, namunalarni foydalanuvchi papkasiga ko'chiradi."""
    written: list[Path] = []
    paths.ensure_dirs()
    pairs = [
        (paths.resource("config.default.yaml"), paths.config_file()),
        (paths.resource("apps.default.yaml"), paths.apps_file()),
    ]
    for src, dst in pairs:
        if dst.exists() or not src.exists():
            continue
        try:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(dst)
        except OSError as exc:
            log.warning("Default fayl yozilmadi %s: %s", dst, exc)
    return written

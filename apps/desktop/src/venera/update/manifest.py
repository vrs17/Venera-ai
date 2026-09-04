"""version.json manifesti va versiyalarni solishtirish.

Manifest namunasi (`tools/make_manifest.py` yozadi):

    {
      "version": "0.2.4",
      "released": "2026-09-10",
      "notes": "macOS qo'shildi",
      "mandatory": false,
      "min_version": "0.1.0",
      "setup": {
        "file": "Venera-AI-Assistant-Setup-0.2.4.exe",
        "sha256": "a1b2...",
        "size": 45012345
      },
      "platforms": {
        "windows": { "file": "...Setup-0.2.4.exe", "sha256": "...", "size": 45012345 },
        "macos":   { "file": "...-0.2.4-universal.dmg", "sha256": "...", "size": 52011000,
                     "arch": "universal", "min_os": "11.0" }
      }
    }

NEGA `setup` HAM, `platforms` HAM BOR — bu ataylab, olib tashlab bo'lmaydi:
tarqatilgan eski mijozlar (0.2.3 va undan oldingilar) faqat `setup` ni biladi
va u yo'q bo'lsa "setup.file yo'q" xatosi bilan yangilana olmay qoladi.
Shuning uchun `setup` DOIM Windows o'rnatuvchisining nusxasi bo'lib qoladi,
yangi mijozlar esa `platforms` dan o'z platformasini oladi.

`file` nisbiy nom bo'lsa, u manifest turgan joyga nisbatan izlanadi.
To'liq URL yoki UNC yo'l ham bo'lishi mumkin.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+.](.*))?\s*$")


def parse_version(value: str) -> tuple[int, int, int]:
    """"1.2.3" -> (1, 2, 3). Tanib bo'lmasa (0, 0, 0)."""
    match = _VERSION_RE.match(str(value or ""))
    if not match:
        log.warning("Versiya tanilmadi: %r", value)
        return (0, 0, 0)
    return tuple(int(match.group(i) or 0) for i in (1, 2, 3))  # type: ignore[return-value]


def compare_versions(left: str, right: str) -> int:
    """left > right bo'lsa 1, teng bo'lsa 0, kichik bo'lsa -1."""
    a, b = parse_version(left), parse_version(right)
    return (a > b) - (a < b)


def is_newer(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0


@dataclass(frozen=True)
class SetupAsset:
    file: str
    sha256: str = ""
    size: int = 0
    #: Faqat macOS uchun ma'noli: "arm64" | "x86_64" | "universal".
    arch: str = ""
    #: Eng past OS versiyasi, masalan macOS uchun "11.0". Bo'sh - cheklov yo'q.
    min_os: str = ""

    @property
    def has_checksum(self) -> bool:
        return len(self.sha256) == 64

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SetupAsset":
        return cls(
            file=str(raw["file"]).strip(),
            sha256=str(raw.get("sha256", "")).strip().lower(),
            size=int(raw.get("size", 0) or 0),
            arch=str(raw.get("arch", "")).strip(),
            min_os=str(raw.get("min_os", "")).strip(),
        )


#: sys.platform -> manifestdagi kalit.
PLATFORM_KEYS = {"win32": "windows", "darwin": "macos", "linux": "linux"}


def current_platform_key() -> str:
    return PLATFORM_KEYS.get(sys.platform, sys.platform)


@dataclass(frozen=True)
class Manifest:
    version: str
    setup: SetupAsset
    released: str = ""
    notes: str = ""
    mandatory: bool = False
    min_version: str = ""
    #: Platforma -> fayl. Yangi format; `setup` esa Windows uchun ayni shu
    #: faylning nusxasi bo'lib qoladi (pastdagi izohga qarang).
    platforms: dict[str, SetupAsset] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def asset_for(self, platform_key: str) -> SetupAsset | None:
        """Berilgan platforma uchun fayl. Topilmasa None.

        Zaxiraga o'tish qoidalari ATAYLAB shunday:

        * `platforms` da bor bo'lsa - o'sha.
        * Windows uchun har doim `setup` ga tushadi: kelishuvga ko'ra `setup`
          aynan Windows o'rnatuvchisi.
        * `platforms` UMUMAN yo'q bo'lsa (eski format) - `setup` hammaga
          tegishli deb hisoblanadi. Bunday manifestda platforma haqida
          ma'lumot yo'q, shuning uchun uni "faqat Windows" deb talqin qilish
          o'zgarishdan oldingi xatti-harakatni buzgan bo'lardi.
        * `platforms` bor, lekin bu OS unda yo'q - None. Nashr qiluvchi
          platformalarni ochiq sanagan va bu OS ro'yxatga kirmagan.
        """
        asset = self.platforms.get(platform_key)
        if asset is not None:
            return asset
        if not self.setup.file:
            return None
        if platform_key == "windows" or not self.platforms:
            return self.setup
        return None

    @property
    def current_asset(self) -> SetupAsset | None:
        """Joriy OS uchun fayl. Bu OS uchun reliz yo'q bo'lsa None."""
        return self.asset_for(current_platform_key())

    @classmethod
    def parse(cls, payload: bytes | str) -> "Manifest":
        """Xom JSON'dan manifest. Xato bo'lsa ValueError."""
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8-sig", errors="replace")

        # SPA saytlar (nginx `try_files ... /index.html`) mavjud bo'lmagan yo'lga
        # ham HTTP 200 + index.html qaytaradi - 404 emas. Buni "JSON buzuq" deb
        # emas, "manba sozlanmagan" deb aytamiz, aks holda xato xabari
        # tushunarsiz bo'ladi va IT muammoni topolmaydi.
        if payload.lstrip()[:1] == "<":
            raise ValueError(
                "manba version.json o'rniga HTML sahifa qaytardi - serverda bu yo'l "
                "sozlanmagan (sayt hamma yo'lni index.html'ga yo'naltiryapti)"
            )

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"version.json o'qilmadi: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("version.json ichida obyekt kutilgan edi")

        version = str(data.get("version", "")).strip()
        if not version:
            raise ValueError("version.json ichida 'version' yo'q")

        # Ko'p platformali blok (yangi format).
        platforms: dict[str, SetupAsset] = {}
        platforms_raw = data.get("platforms")
        if isinstance(platforms_raw, dict):
            for key, value in platforms_raw.items():
                if isinstance(value, dict) and value.get("file"):
                    platforms[str(key).strip().lower()] = SetupAsset.from_dict(value)
                else:
                    log.warning("version.json: 'platforms.%s' e'tiborsiz qoldirildi "
                                "(fayl nomi yo'q)", key)

        setup_raw = data.get("setup") or {}
        has_setup = isinstance(setup_raw, dict) and bool(setup_raw.get("file"))
        # `setup` YOKI hech bo'lmasa bitta platforma bo'lishi shart. Ikkalasi
        # ham yo'q bo'lsa manifest hech kimga foydasiz.
        if not has_setup and not platforms:
            raise ValueError("version.json ichida 'setup.file' ham, 'platforms' ham yo'q")

        return cls(
            version=version,
            setup=SetupAsset.from_dict(setup_raw) if has_setup else SetupAsset(file=""),
            released=str(data.get("released", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
            mandatory=bool(data.get("mandatory", False)),
            min_version=str(data.get("min_version", "")).strip(),
            platforms=platforms,
            raw=data,
        )

    def applies_to(self, current_version: str) -> bool:
        """Bu yangilanish shu versiyaga o'rnatilishi mumkinmi."""
        if self.min_version and compare_versions(current_version, self.min_version) < 0:
            log.warning(
                "Yangilanish %s uchun kamida %s kerak, hozirgi versiya %s - "
                "qo'lda o'rnatish talab qilinadi",
                self.version, self.min_version, current_version,
            )
            return False
        return True


@dataclass(frozen=True)
class UpdateInfo:
    """Topilgan yangilanish haqida UI uchun ma'lumot."""

    manifest: Manifest
    current_version: str
    download_url: str
    #: Joriy platforma fayli. Berilmasa manifestdan aniqlanadi - shu tufayli
    #: eski chaqiruvlar (va testlar) o'zgarishsiz ishlayveradi.
    asset: SetupAsset | None = None

    @property
    def resolved_asset(self) -> SetupAsset:
        return self.asset or self.manifest.current_asset or self.manifest.setup

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def mandatory(self) -> bool:
        return self.manifest.mandatory

    @property
    def size_mb(self) -> float:
        size = self.resolved_asset.size
        return round(size / 1048576.0, 1) if size else 0.0

    def describe(self) -> str:
        parts = [f"Yangi versiya {self.version}"]
        if self.size_mb:
            parts.append(f"{self.size_mb} MB")
        if self.manifest.released:
            parts.append(self.manifest.released)
        return "  |  ".join(parts)

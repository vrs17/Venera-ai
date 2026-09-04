"""version.json manifesti va versiyalarni solishtirish.

Manifest namunasi (nashr qiluvchi tomonidan `packaging/publish.ps1` yozadi):

    {
      "version": "0.2.0",
      "released": "2026-09-10",
      "notes": "On-prem STT ulandi",
      "mandatory": false,
      "min_version": "0.1.0",
      "setup": {
        "file": "Venera-AI-Assistant-Setup-0.2.0.exe",
        "sha256": "a1b2...",
        "size": 45012345
      }
    }

`setup.file` nisbiy nom bo'lsa, u manifest turgan joyga nisbatan izlanadi.
To'liq URL yoki UNC yo'l ham bo'lishi mumkin.
"""

from __future__ import annotations

import json
import logging
import re
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

    @property
    def has_checksum(self) -> bool:
        return len(self.sha256) == 64


@dataclass(frozen=True)
class Manifest:
    version: str
    setup: SetupAsset
    released: str = ""
    notes: str = ""
    mandatory: bool = False
    min_version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

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

        setup_raw = data.get("setup") or {}
        if not isinstance(setup_raw, dict) or not setup_raw.get("file"):
            raise ValueError("version.json ichida 'setup.file' yo'q")

        return cls(
            version=version,
            setup=SetupAsset(
                file=str(setup_raw["file"]).strip(),
                sha256=str(setup_raw.get("sha256", "")).strip().lower(),
                size=int(setup_raw.get("size", 0) or 0),
            ),
            released=str(data.get("released", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
            mandatory=bool(data.get("mandatory", False)),
            min_version=str(data.get("min_version", "")).strip(),
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

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def mandatory(self) -> bool:
        return self.manifest.mandatory

    @property
    def size_mb(self) -> float:
        return round(self.manifest.setup.size / 1048576.0, 1) if self.manifest.setup.size else 0.0

    def describe(self) -> str:
        parts = [f"Yangi versiya {self.version}"]
        if self.size_mb:
            parts.append(f"{self.size_mb} MB")
        if self.manifest.released:
            parts.append(self.manifest.released)
        return "  |  ".join(parts)

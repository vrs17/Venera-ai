"""Dasturlar katalogi: ovozli nom -> ishga tushirish maqsadi.

STT o'zbekcha talaffuzni lotin yozuvida qaytaradi ("krom", "eksel"), shuning uchun
aniq moslik yetarli emas - taxminiy (fuzzy) qidiruv ishlatiladi.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import paths

log = logging.getLogger(__name__)

MATCH_THRESHOLD = 78.0

try:
    from rapidfuzz import fuzz as _fuzz

    def _score(a: str, b: str) -> float:
        return max(_fuzz.WRatio(a, b), _fuzz.token_set_ratio(a, b))

    FUZZY_BACKEND = "rapidfuzz"
except Exception:  # noqa: BLE001 - rapidfuzz bo'lmasa stdlib bilan ishlaymiz
    from difflib import SequenceMatcher

    def _score(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100.0

    FUZZY_BACKEND = "difflib"


@dataclass(frozen=True)
class AppEntry:
    name: str
    aliases: tuple[str, ...]
    targets: tuple[str, ...]

    def best_score(self, query: str) -> float:
        candidates = (self.name.lower(), *self.aliases)
        return max((_score(query, c) for c in candidates), default=0.0)


@dataclass
class AppCatalog:
    entries: list[AppEntry] = field(default_factory=list)
    source: Path | None = None

    @property
    def platform_key(self) -> str:
        return "windows" if sys.platform == "win32" else "macos"

    def find(self, query: str) -> tuple[AppEntry | None, float]:
        """Eng mos dasturni topadi. Chegaradan past bo'lsa (None, ball)."""
        query = (query or "").strip().lower()
        if not query or not self.entries:
            return None, 0.0
        best: AppEntry | None = None
        best_score = 0.0
        for entry in self.entries:
            score = entry.best_score(query)
            if score > best_score:
                best, best_score = entry, score
        if best_score < MATCH_THRESHOLD:
            log.info("Dastur topilmadi: %r (eng yaqin %s, ball %.0f)",
                     query, best.name if best else "-", best_score)
            return None, best_score
        return best, best_score

    def names(self) -> list[str]:
        return [entry.name for entry in self.entries]


def load(path: Path | None = None) -> AppCatalog:
    """apps.yaml ni o'qiydi: avval foydalanuvchi papkasidan, keyin paket ichidan."""
    candidates = [path] if path else [paths.apps_file(), paths.resource("apps.default.yaml")]
    platform_key = "windows" if sys.platform == "win32" else "macos"

    for candidate in candidates:
        if candidate is None or not Path(candidate).exists():
            continue
        try:
            raw = yaml.safe_load(Path(candidate).read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("apps.yaml o'qilmadi (%s): %s", candidate, exc)
            continue

        entries: list[AppEntry] = []
        for item in raw.get("apps", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            aliases = tuple(
                str(a).strip().lower() for a in (item.get("aliases") or []) if str(a).strip()
            )
            targets_raw = item.get(platform_key) or []
            if isinstance(targets_raw, str):
                targets_raw = [targets_raw]
            targets = tuple(str(t).strip() for t in targets_raw if str(t).strip())
            if not targets:
                continue
            entries.append(AppEntry(name=name, aliases=aliases, targets=targets))

        log.info("Dasturlar katalogi yuklandi: %d ta (%s, moslik: %s)",
                 len(entries), candidate, FUZZY_BACKEND)
        return AppCatalog(entries=entries, source=Path(candidate))

    log.warning("apps.yaml topilmadi - dastur ochish ishlamaydi")
    return AppCatalog()

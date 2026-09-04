"""Intent modeli.

Bu fayl Step 3 da ham o'zgarmaydi: LLM ham aynan shu Intent obyektini qaytaradi,
faqat `source` maydoni "llm" bo'ladi. Shu sababli actions qatlami LLM qo'shilganda
umuman tegilmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntentName(str, Enum):
    OPEN_APP = "open_app"
    OPEN_URL = "open_url"
    WEB_SEARCH = "web_search"
    VOLUME_SET = "volume_set"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    UNMUTE = "unmute"
    LOCK_SCREEN = "lock_screen"
    SCREENSHOT = "screenshot"
    TIME = "time"
    DATE = "date"
    CANCEL = "cancel"
    REPEAT = "repeat"
    HELP = "help"
    VERSION = "version"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # log va UI uchun
        return self.value


@dataclass(frozen=True)
class Intent:
    """Buyruqning tuzilgan ko'rinishi."""

    name: IntentName = IntentName.UNKNOWN
    app: str = ""          # open_app: foydalanuvchi aytgan nom ("krom")
    url: str = ""          # open_url
    query: str = ""        # web_search
    level: int = 0         # volume_set: 0..100
    raw_text: str = ""     # normalizatsiyadan keyingi matn
    source: str = "rules"  # rules | llm | fastpath
    confidence: float = 1.0

    @property
    def is_known(self) -> bool:
        return self.name is not IntentName.UNKNOWN

    def describe(self) -> str:
        parts = [str(self.name)]
        for field_name in ("app", "url", "query"):
            value = getattr(self, field_name)
            if value:
                parts.append(f"{field_name}={value!r}")
        if self.name is IntentName.VOLUME_SET:
            parts.append(f"level={self.level}")
        return " ".join(parts)

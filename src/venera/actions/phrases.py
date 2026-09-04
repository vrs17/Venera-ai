"""O'zbekcha javob shablonlari.

Javob matni LLM'dan olinmaydi - shuning uchun grammatika doim to'g'ri va
Step 4 da bu iboralarni oldindan TTS bilan sintez qilib keshlash mumkin.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import yaml

from .. import paths

log = logging.getLogger(__name__)

_FALLBACK = {
    "unknown": "Tushunmadim, qayta ayting",
    "action_failed": "Buyruqni bajarib bo'lmadi",
}


class Phrases:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    @classmethod
    def load(cls, path: Path | None = None) -> "Phrases":
        target = path or paths.resource("phrases.uz.yaml")
        try:
            data = yaml.safe_load(Path(target).read_text(encoding="utf-8")) or {}
            log.info("Javob shablonlari yuklandi: %d ta", len(data))
            return cls(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("phrases.uz.yaml o'qilmadi (%s): %s", target, exc)
            return cls(dict(_FALLBACK))

    def get(self, key: str, **kwargs: object) -> str:
        template = self._data.get(key) or _FALLBACK.get(key) or key
        if not isinstance(template, str):
            return key
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            log.warning("Shablon to'ldirilmadi (%s): %s", key, exc)
            return template

    def weekday(self, moment: datetime) -> str:
        names = self._data.get("weekdays") or []
        index = moment.weekday()
        if isinstance(names, list) and 0 <= index < len(names):
            return str(names[index])
        return moment.strftime("%A")

    def month(self, moment: datetime) -> str:
        names = self._data.get("months") or []
        index = moment.month - 1
        if isinstance(names, list) and 0 <= index < len(names):
            return str(names[index])
        return moment.strftime("%B")

    def format_date(self, moment: datetime) -> str:
        return f"{self.weekday(moment)}, {moment.day}-{self.month(moment)} {moment.year}-yil"

    def format_time(self, moment: datetime) -> str:
        return moment.strftime("%H:%M")

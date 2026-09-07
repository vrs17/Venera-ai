"""Javob shablonlari - FAOL til paketidan.

Javob matni LLM'dan olinmaydi - shuning uchun grammatika doim to'g'ri va
Step 4 da bu iboralarni oldindan TTS bilan sintez qilib keshlash mumkin.

Manba ikkita bo'lishi mumkin:
  * faol til paketi (`resources/i18n/<kod>/phrases.yaml`) - ODATDAGI yo'l.
    `config.language` shu orqali javoblarga ham qo'llanadi, faqat STT ga emas.
  * aniq YAML fayl (`Phrases.load(path)`) - testlar va eski `phrases.uz.yaml`
    uchun. Bu yo'l til paketi yuklanmagan holatda ham ishlaydi.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import yaml

from .. import i18n, paths

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
        # Aniq fayl so'ralmagan bo'lsa - faol til paketidan. Paket bo'sh
        # bo'lsagina eski faylga tushamiz, shunda i18n ishlamay qolsa ham
        # ilova gapirishda davom etadi.
        if path is None and i18n.active().phrases:
            log.info("Javob shablonlari: %s til paketi", i18n.code())
            return _PackPhrases()
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


class _PackPhrases(Phrases):
    """Faol til paketiga ULANGAN iboralar.

    Nusxa OLINMAYDI: `i18n.bind()` chaqirilishi bilan javoblar ham yangi
    tilga o'tadi va bu obyektni qayta yasash shart emas.
    """

    def __init__(self) -> None:
        super().__init__({})

    def get(self, key: str, **kwargs: object) -> str:
        text = i18n.phrase(key, **kwargs)
        if text == key:
            # Kalit na faol, na zaxira tilda topildi - oxirgi chora.
            return _FALLBACK.get(key, key)
        return text

    def weekday(self, moment: datetime) -> str:
        return self._from_list("weekdays", moment.weekday(), moment, "%A")

    def month(self, moment: datetime) -> str:
        return self._from_list("months", moment.month - 1, moment, "%B")

    @staticmethod
    def _from_list(key: str, index: int, moment: datetime, fmt: str) -> str:
        names = i18n.raw("phrases", key) or []
        if isinstance(names, list) and 0 <= index < len(names):
            return str(names[index])
        return moment.strftime(fmt)

"""Son so'zlarini butun songa aylantirish - TILGA BOG'LIQ EMAS.

"qirq besh" -> 45, "o'n besh" -> 15, "sakkiz yuz o'n olti ming" -> 816000.
Ovoz balandligi kabi buyruqlar uchun kerak; arifmetika LLM'ga topshirilmaydi.

TUZILISH: `NumberParser` - abstrakt sinf, `PARSERS` - nom -> sinf registri.
Til paketi `words.yaml` da qaysi parser va qanday so'zlar ishlatilishini
aytadi:

    numbers:
      parser: decimal_words
      units:  {bir: 1, ikki: 2, ...}
      tens:   {"o'n": 10, yigirma: 20, ...}
      scales: {yuz: 100, ming: 1000, ...}

`decimal_words` o'nlik sanoq tizimidagi HAR QANDAY til uchun ishlaydi
(uz, ru, en). Xitoycha uchun (万 = 10^4, 亿 = 10^8) alohida parser yozilib
`PARSERS` ga ro'yxatdan o'tkaziladi - bu modulga tegish shart emas.

MODUL OXIRIDA `words_to_int()` / `contains_number()` - ESKI MOSLIK QATLAMI
o'zbekcha default'lar bilan.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Mapping

from .normalize import APOSTROPHE_CHARS, unify_apostrophes

log = logging.getLogger(__name__)

# NEGA shunday murakkab: oddiy `[^\W\d_]+` apostrofni so'z chegarasi deb
# biladi va "o'n besh" -> 15 o'rniga 5 beradi, "to'qson" esa umuman
# topilmaydi. Apostrof O'ZBEK HARFINING BIR QISMI, shuning uchun u ikki harf
# orasida bo'lsa so'zni uzmasligi kerak.
_WORD_RE = re.compile(
    r"[^\W\d_]+(?:[%s][^\W\d_]+)*" % re.escape(APOSTROPHE_CHARS),
    re.UNICODE,
)
_DIGITS_RE = re.compile(r"\d+")


class NumberParser(ABC):
    """Matndan sonni ajratuvchi. Har til uchun bitta implementatsiya."""

    #: `words.yaml` dagi `numbers.parser` qiymati
    name: str = "base"

    @abstractmethod
    def parse(self, text: str) -> int | None:
        """Sonni qaytaradi yoki topilmasa None. Exception TASHLAMAYDI."""

    def contains(self, text: str) -> bool:
        return self.parse(text) is not None

    @property
    def vocabulary(self) -> frozenset[str]:
        """Parser taniydigan barcha so'zlar (regex makrolari uchun qulay)."""
        return frozenset()

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "NumberParser":
        """`words.yaml` dagi `numbers:` bo'limidan parser quradi."""
        raise NotImplementedError


def _int_map(raw: Any, label: str, problems: list[str]) -> dict[str, int]:
    """`{so'z: son}` mappingni xavfsiz o'qiydi."""
    result: dict[str, int] = {}
    if raw is None:
        return result
    if not isinstance(raw, Mapping):
        problems.append(f"numbers.{label}: mapping kutilgan edi, {type(raw).__name__} keldi")
        return result
    for word, value in raw.items():
        key = unify_apostrophes(str(word)).strip().lower()
        if not key:
            continue
        try:
            result[key] = int(value)
        except (TypeError, ValueError):
            problems.append(f"numbers.{label}.{word}: butun son kutilgan edi ({value!r})")
    return result


class DecimalWordParser(NumberParser):
    """O'nlik sanoq: birliklar + o'nliklar + ko'paytiruvchilar.

    Ikki xil ko'paytiruvchi bor va farqi MUHIM:
      * `flush_from` dan KICHIK (odatda "yuz" = 100) joriy yig'indini
        KO'PAYTIRADI: "ikki yuz ellik" -> (2*100) + 50 = 250
      * `flush_from` dan katta-teng ("ming", "million") joriy yig'indini
        umumiy yig'indiga QO'SHIB, hisobni noldan boshlaydi:
        "sakkiz yuz o'n olti ming" -> (800+16)*1000 = 816000
    """

    name = "decimal_words"

    def __init__(
        self,
        units: Mapping[str, int] | None = None,
        tens: Mapping[str, int] | None = None,
        scales: Mapping[str, int] | None = None,
        flush_from: int = 1000,
    ) -> None:
        self.units = dict(units or {})
        self.tens = dict(tens or {})
        self.scales = dict(scales or {})
        self.flush_from = int(flush_from)
        self._all = frozenset(self.units) | frozenset(self.tens) | frozenset(self.scales)

    @property
    def vocabulary(self) -> frozenset[str]:
        return self._all

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "DecimalWordParser":
        problems: list[str] = []
        parser = cls(
            units=_int_map(data.get("units"), "units", problems),
            tens=_int_map(data.get("tens"), "tens", problems),
            scales=_int_map(data.get("scales"), "scales", problems),
            flush_from=int(data.get("flush_from", 1000) or 1000),
        )
        for problem in problems:
            log.warning("words.yaml: %s", problem)
        return parser

    def parse(self, text: str) -> int | None:
        if not text:
            return None

        # Raqam yozilgan bo'lsa u ustun: "ovozni 30 foiz" -> 30
        digits = _DIGITS_RE.search(text)
        if digits:
            try:
                return int(digits.group())
            except ValueError:
                return None

        if not self._all:
            return None

        prepared = unify_apostrophes(str(text)).lower()
        tokens = [t for t in _WORD_RE.findall(prepared) if t in self._all]
        if not tokens:
            return None

        total = 0
        current = 0
        seen = False

        for token in tokens:
            if token in self.units:
                current += self.units[token]
            elif token in self.tens:
                current += self.tens[token]
            else:
                scale = self.scales[token]
                if scale < self.flush_from:
                    current = (current or 1) * scale
                else:
                    total += (current or 1) * scale
                    current = 0
            seen = True

        if not seen:
            return None
        return total + current


#: Nom -> parser sinfi. Yangi til yangi arifmetika talab qilsa, o'z sinfini
#: shu yerga qo'shadi va `words.yaml` da `numbers.parser` ni o'zgartiradi.
PARSERS: dict[str, type[NumberParser]] = {
    DecimalWordParser.name: DecimalWordParser,
}


def build_parser(data: Mapping[str, Any] | None) -> tuple[NumberParser | None, list[str]]:
    """`words.yaml` dagi `numbers:` bo'limidan parser. Xato bo'lsa (None, muammolar)."""
    problems: list[str] = []
    if not data:
        return None, problems
    if not isinstance(data, Mapping):
        return None, [f"numbers: mapping kutilgan edi, {type(data).__name__} keldi"]

    name = str(data.get("parser") or DecimalWordParser.name).strip().lower()
    cls = PARSERS.get(name)
    if cls is None:
        problems.append(f"numbers.parser={name!r} noma'lum ({sorted(PARSERS)}) "
                        f"- {DecimalWordParser.name} ishlatildi")
        cls = DecimalWordParser
    try:
        return cls.from_data(data), problems
    except Exception as exc:  # noqa: BLE001 - buzuq YAML ilovani yiqitmasin
        problems.append(f"numbers: parser qurilmadi ({exc})")
        return None, problems


# --- moslik qatlami (o'zbekcha default'lar) ---------------------------------
#
# DIQQAT: quyidagi uch jadval `resources/i18n/uz/words.yaml` NUSXASI.
# Asosiy manba - YAML fayl. Bir xilligini `tests/test_i18n.py` tekshiradi.

UNITS = {
    "nol": 0, "nol'": 0, "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "besh": 5,
    "olti": 6, "yetti": 7, "etti": 7, "sakkiz": 8, "to'qqiz": 9,
}

TENS = {
    "o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40, "ellik": 50,
    "oltmish": 60, "yetmish": 70, "etmish": 70, "sakson": 80, "to'qson": 90,
}

SCALES = {
    "yuz": 100,
    "ming": 1000,
    "million": 1_000_000,
    "milliard": 1_000_000_000,
}

ALL_NUMBER_WORDS = set(UNITS) | set(TENS) | set(SCALES)

#: `words_to_int()` shu parser orqali ishlaydi.
UZ_PARSER = DecimalWordParser(units=UNITS, tens=TENS, scales=SCALES)


def words_to_int(text: str) -> int | None:
    """O'ZBEKCHA so'zlar ketma-ketligidan son (moslik qatlami).

    Yangi kod `i18n.words().number(...)` ni ishlatsin - u FAOL tilning
    parseriga murojaat qiladi.
    """
    return UZ_PARSER.parse(text)


def contains_number(text: str) -> bool:
    return UZ_PARSER.contains(text)

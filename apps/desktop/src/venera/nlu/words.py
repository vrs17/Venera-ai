"""`WordBook` - bitta tilning so'z boyligi (`words.yaml`).

Bir joyda to'plangan: to'ldiruvchi so'zlar, kelishik qo'shimchalari, alohida
yuklamalar, uyg'otish so'zi, regex makrolari va son parseri. Grammatika ham,
transformatsiyalar ham FAQAT shu obyekt orqali tilga murojaat qiladi - shuning
uchun `grammar.py` da birorta o'zbekcha so'z yo'q.

`words.yaml` sxemasi:

    version: 1
    fillers:       [iltimos, ...]        # ma'noga ta'sir qilmaydigan so'zlar
    suffixes:      [ni, ning, ga, ...]   # so'z oxiridan kesiladigan qo'shimchalar
    particles:     [ni, ga, da, ...]     # ALOHIDA turgan yuklamalar
    wake_prefixes: [venera, ...]         # matn boshidan olib tashlanadi
    macros:
      num: |-
        (?:\\d+|[a-z'\\s]+?)
    numbers:
      parser: decimal_words
      units:  {...}
      tens:   {...}
      scales: {...}

MAKROLAR haqida: `rules.yaml` dagi `{num}` shu bo'limdan olinadi.
`str.format` ISHLATILMAYDI - regexda `{2,3}` kabi kvantifikatorlar bor va
`format` ularni argument deb o'ylab KeyError beradi. Faqat `{nom}`
ko'rinishidagi to'liq makro nomlari almashtiriladi, noma'lumi esa
o'z holicha qoldiriladi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from . import normalize as norm
from .numbers import NumberParser, build_parser

log = logging.getLogger(__name__)

#: Faqat `{harf_va_pastki_chiziq}` almashtiriladi - `{2,3}` tegilmaydi.
_MACRO_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _str_tuple(raw: Any, label: str, problems: list[str]) -> tuple[str, ...]:
    """Ro'yxatni xavfsiz o'qiydi. TARTIB SAQLANADI."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        problems.append(f"{label}: ro'yxat kutilgan edi, {type(raw).__name__} keldi")
        return ()
    out: list[str] = []
    for item in raw:
        value = norm.unify_apostrophes(str(item)).strip().lower()
        if value and value not in out:
            out.append(value)
    return tuple(out)


@dataclass(frozen=True)
class WordBook:
    """Bitta tilning so'z boyligi. O'ZGARMAS - thread'lar orasida qulfsiz ishlatiladi."""

    code: str = ""
    fillers: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    particles: tuple[str, ...] = ()
    wake_prefixes: tuple[str, ...] = ()
    macros: Mapping[str, str] = field(default_factory=dict)
    numbers: NumberParser | None = None
    problems: tuple[str, ...] = ()

    # --- tozalash -----------------------------------------------------------

    @property
    def filler_re(self) -> "re.Pattern[str] | None":
        # frozen dataclass - keshlash uchun `object.__setattr__` kerak bo'lardi;
        # ro'yxat kichik, qayta qurish arzon emas, shuning uchun bir marta
        # `__post_init__` da tayyorlanadi (pastga qarang).
        return self._filler_re

    def __post_init__(self) -> None:
        object.__setattr__(self, "_filler_re", norm.filler_pattern(self.fillers))

    def normalize(self, text: str, drop_fillers: bool = True) -> str:
        """Matnni shu tilning to'ldiruvchi so'zlarisiz tozalaydi."""
        return norm.clean(text, self._filler_re if drop_fillers else None)

    def strip_wake(self, text: str) -> str:
        """Matn boshidagi uyg'otish so'zini olib tashlaydi ("venera chrome och")."""
        return norm.strip_prefix_word(text, self.wake_prefixes)

    # --- morfologiya --------------------------------------------------------

    def strip_suffix(self, word: str) -> str:
        """Bitta so'zning kelishik qo'shimchasini kesadi."""
        return norm.strip_word_suffix(word, self.suffixes)

    def strip_affixes(self, phrase: str) -> str:
        """Ko'p so'zli nomdan qo'shimcha va alohida yuklamani olib tashlaydi.

        "google chrome ni" -> "google chrome"   (alohida yuklama)
        "chromeni"         -> "chrome"          (qo'shilgan qo'shimcha)

        Oxirgi so'z yolg'iz qolsa kesilmaydi: "ni och" da "ni" dastur nomi
        bo'lishi mumkin, uni yo'q qilib bo'lmaydi.
        """
        words = (phrase or "").strip().split()
        if not words:
            return ""
        particles = set(self.particles)
        while len(words) > 1 and words[-1] in particles:
            words.pop()
        words[-1] = self.strip_suffix(words[-1])
        return " ".join(words)

    # --- sonlar -------------------------------------------------------------

    def number(self, text: str) -> int | None:
        if self.numbers is None:
            return None
        try:
            return self.numbers.parse(text)
        except Exception:  # noqa: BLE001 - parser xatosi buyruqni yiqitmasin
            log.debug("Son ajratilmadi: %r", text, exc_info=True)
            return None

    # --- regex makrolari ----------------------------------------------------

    def expand(self, pattern: str) -> str:
        """`rules.yaml` naqshidagi `{makro}` larni almashtiradi."""
        macros = self.macros
        return _MACRO_RE.sub(lambda m: macros.get(m.group(1), m.group(0)), pattern)

    def unknown_macros(self, pattern: str) -> tuple[str, ...]:
        """Naqshda ishlatilgan, lekin `words.yaml` da yo'q makrolar."""
        return tuple(sorted({
            m.group(1) for m in _MACRO_RE.finditer(pattern) if m.group(1) not in self.macros
        }))


def from_data(code: str, data: Any) -> tuple[WordBook, list[str]]:
    """`words.yaml` dan WordBook. HECH QACHON exception tashlamaydi."""
    problems: list[str] = []
    if not isinstance(data, Mapping):
        if data is not None:
            problems.append(f"{code}/words.yaml: mapping kutilgan edi, "
                            f"{type(data).__name__} keldi")
        data = {}

    macros_raw = data.get("macros") or {}
    macros: dict[str, str] = {}
    if isinstance(macros_raw, Mapping):
        for name, value in macros_raw.items():
            key = str(name).strip()
            if not _MACRO_RE.fullmatch("{%s}" % key):
                problems.append(f"{code}/words.yaml: makro nomi noto'g'ri ({name!r}) "
                                "- faqat kichik harf, raqam va _ ruxsat")
                continue
            macros[key] = str(value)
    else:
        problems.append(f"{code}/words.yaml: macros mapping bo'lishi kerak")

    parser, number_problems = build_parser(data.get("numbers"))
    problems.extend(f"{code}/words.yaml: {p}" for p in number_problems)

    book = WordBook(
        code=code,
        fillers=_str_tuple(data.get("fillers"), f"{code}/words.yaml: fillers", problems),
        suffixes=_str_tuple(data.get("suffixes"), f"{code}/words.yaml: suffixes", problems),
        particles=_str_tuple(data.get("particles"), f"{code}/words.yaml: particles", problems),
        wake_prefixes=_str_tuple(data.get("wake_prefixes"),
                                 f"{code}/words.yaml: wake_prefixes", problems),
        macros=macros,
        numbers=parser,
        problems=tuple(problems),
    )
    return book, problems

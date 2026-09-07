"""Matnni tozalash - TILGA BOG'LIQ BO'LMAGAN primitivlar.

Bu modulda ATAYLAB hech qanday o'zbekcha (yoki ruscha, inglizcha) so'z ro'yxati
YO'Q - ular til paketiga, `resources/i18n/<kod>/words.yaml` ga ko'chdi va
`nlu.words.WordBook` orqali ishlatiladi. Shu tufayli yangi til qo'shish uchun
bu faylga tegish shart emas.

Eng muhim primitiv - apostrof. O'zbek lotin yozuvida o' va g' harflari turli
belgilar bilan yoziladi (U+02BB, U+02BC, U+2018, U+2019, backtick, oddiy ').
STT ham, foydalanuvchi ham har xil yozadi, shuning uchun hammasi bitta oddiy '
ga keltiriladi. Apostrof O'CHIRILMAYDI - u harf tarkibiga kiradi
("o'chir" != "ochir").

MODULNING OXIRIDA `normalize()` va `strip_suffix()` bor - ular ESKI MOSLIK
QATLAMI (o'zbekcha default'lar bilan). Yangi kod ularni EMAS,
`i18n.words().normalize(...)` ni chaqirsin.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Sequence

# --- tilga bog'liq bo'lmagan primitivlar ------------------------------------

#: Apostrofga o'xshash barcha belgilar -> '
APOSTROPHES = {
    "\u02bb": "'",  # MODIFIER LETTER TURNED COMMA (oʻ)
    "\u02bc": "'",  # MODIFIER LETTER APOSTROPHE (oʼ)
    "\u2018": "'",  # LEFT SINGLE QUOTATION MARK
    "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK
    "\u201b": "'",
    "\u00b4": "'",  # ACUTE ACCENT
    "\u0060": "'",  # GRAVE ACCENT / backtick
    "\u02b9": "'",
    "\u2032": "'",  # PRIME
}

#: Eski nom - tashqi kod hali `_APOSTROPHES` ga murojaat qilishi mumkin.
_APOSTROPHES = APOSTROPHES

#: Apostrofdan keyin ham davom etadigan harf ketma-ketligi uchun ulagichlar.
#: `numbers.py` va `words.py` shu ro'yxatdan foydalanadi.
APOSTROPHE_CHARS = "'" + "".join(APOSTROPHES)

_PUNCT_RE = re.compile(r"[^\w'\s:/.@%-]+", re.UNICODE)
# So'z oxiridagi tinish belgilari ("qulfla." -> "qulfla"), lekin domen ichidagi
# nuqta saqlanadi ("google.com" -> "google.com").
_TRAILING_RE = re.compile(r"(?<=\w)[.:,;%-]+(?=\s|$)")
_SPACE_RE = re.compile(r"\s+")


def unify_apostrophes(text: str) -> str:
    """Apostrof variantlarini bitta oddiy ' ga keltiradi."""
    for src, dst in APOSTROPHES.items():
        text = text.replace(src, dst)
    return text


def filler_pattern(fillers: Iterable[str]) -> "re.Pattern[str] | None":
    """To'ldiruvchi so'zlar ro'yxatidan regex. Ro'yxat bo'sh bo'lsa None.

    TARTIB MUHIM: ro'yxat qanday berilgan bo'lsa, alternativalar shu tartibda
    yoziladi. Shuning uchun til paketi muallifi uzunroq variantni oldinroq
    yozishi mumkin.
    """
    words = [w for w in (str(f).strip() for f in fillers) if w]
    if not words:
        return None
    try:
        return re.compile(r"\b(?:%s)\b" % "|".join(words))
    except re.error:
        return None


def clean(text: str, fillers: "re.Pattern[str] | None" = None) -> str:
    """Kichik harf, yagona apostrof, ortiqcha tinish belgilarisiz, bitta bo'shliq.

    `fillers` - `filler_pattern()` qaytargan regex yoki None. Tilga bog'liq
    yagona qism SHU va u tashqaridan beriladi.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = unify_apostrophes(text)
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _TRAILING_RE.sub("", text)
    if fillers is not None:
        text = fillers.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def strip_word_suffix(word: str, suffixes: Sequence[str]) -> str:
    """So'z oxiridan berilgan qo'shimchalardan BIRINCHI mos kelganini olib tashlaydi.

    To'liq morfologiya emas - "chromeni" -> "chrome" kabi keng tarqalgan
    holatlar uchun. Qo'shimcha faqat o'zak kamida 3 harf bo'lib qolsa
    kesiladi, aks holda "ni" so'zining o'zi yo'q bo'lib ketardi.
    """
    for suffix in suffixes:
        suffix = str(suffix)
        if suffix and len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def strip_prefix_word(text: str, prefixes: Sequence[str]) -> str:
    """Matn boshidagi uyg'otish so'zini ("venera, chrome och") olib tashlaydi.

    Faqat BUTUN so'z mos kelsa va ortidan yana matn qolsa kesiladi - aks holda
    "venerani och" buyrug'i buzilardi.
    """
    if not text or not prefixes:
        return text
    parts = text.split()
    if len(parts) < 2:
        return text
    if parts[0] in {str(p).strip().lower() for p in prefixes if str(p).strip()}:
        return " ".join(parts[1:])
    return text


# --- moslik qatlami (o'zbekcha default'lar) ---------------------------------
#
# DIQQAT: quyidagi ikki ro'yxat `resources/i18n/uz/words.yaml` NUSXASI.
# Asosiy manba - YAML fayl; bu yerdagi nusxa faqat `normalize()` va
# `strip_suffix()` ni til paketisiz ham ishlatish mumkin bo'lsin deb turibdi
# (eski kod va testlar shu ikki funksiyani import qiladi).
# Ikkalasining bir xilligini `tests/test_i18n.py` tekshiradi - qo'lda
# solishtirish shart emas, lekin BIRINI o'zgartirsangiz IKKINCHISINI ham
# o'zgartiring.

#: Ma'noga ta'sir qilmaydigan so'zlar (uz)
_FILLERS = (
    "iltimos", "marhamat", "qani", "menga", "mendan",
    "mumkinmi", "mumkin", "bo'ladimi", "tez", "tezda",
)

#: Oddiy o'zbek kelishik qo'shimchalari (uz)
_SUFFIXES = ("ni", "ning", "ga", "da", "dan", "ya", "yi")

_FILLER_RE = filler_pattern(_FILLERS)


def normalize(text: str, drop_fillers: bool = True) -> str:
    """O'ZBEKCHA default'lar bilan tozalash (moslik qatlami).

    Yangi kod `i18n.words().normalize(...)` ni ishlatsin - u FAOL tilning
    to'ldiruvchi so'zlarini biladi.
    """
    return clean(text, _FILLER_RE if drop_fillers else None)


def strip_suffix(word: str) -> str:
    """O'ZBEKCHA kelishik qo'shimchasini olib tashlaydi (moslik qatlami)."""
    return strip_word_suffix(word, _SUFFIXES)

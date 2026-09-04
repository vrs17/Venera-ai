"""Matnni qoidalarga solishtirishdan oldin tozalash.

Eng muhimi apostrof: o'zbek lotin yozuvida o' va g' harflari turli belgilar bilan
yoziladi (U+02BB, U+02BC, U+2018, U+2019, backtick, oddiy '). STT ham, foydalanuvchi
ham har xil yozadi, shuning uchun hammasi bitta oddiy ' ga keltiriladi.
Apostrof O'CHIRILMAYDI - u harf tarkibiga kiradi ("o'chir" != "ochir").
"""

from __future__ import annotations

import re
import unicodedata

# Apostrofga o'xshash barcha belgilar -> '
_APOSTROPHES = {
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

# Ma'noga ta'sir qilmaydigan so'zlar
_FILLERS = (
    "iltimos", "marhamat", "qani", "menga", "mendan",
    "mumkinmi", "mumkin", "bo'ladimi", "tez", "tezda",
)

_FILLER_RE = re.compile(r"\b(?:%s)\b" % "|".join(_FILLERS))
_PUNCT_RE = re.compile(r"[^\w'\s:/.@%-]+", re.UNICODE)
# So'z oxiridagi tinish belgilari ("qulfla." -> "qulfla"), lekin domen ichidagi
# nuqta saqlanadi ("google.com" -> "google.com").
_TRAILING_RE = re.compile(r"(?<=\w)[.:,;%-]+(?=\s|$)")
_SPACE_RE = re.compile(r"\s+")


def unify_apostrophes(text: str) -> str:
    for src, dst in _APOSTROPHES.items():
        text = text.replace(src, dst)
    return text


def normalize(text: str, drop_fillers: bool = True) -> str:
    """Kichik harf, yagona apostrof, ortiqcha tinish belgilarisiz, bitta bo'shliq."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = unify_apostrophes(text)
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _TRAILING_RE.sub("", text)
    if drop_fillers:
        text = _FILLER_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def strip_suffix(word: str) -> str:
    """Oddiy o'zbek kelishik qo'shimchalarini olib tashlaydi (alias moslash uchun).

    To'liq morfologiya emas - "chromeni" -> "chrome" kabi keng tarqalgan holatlar uchun.
    """
    for suffix in ("ni", "ning", "ga", "da", "dan", "ya", "yi"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word

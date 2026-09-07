"""O'zbek lotin <-> kirill transliteratsiyasi.

NIMA UCHUN KERAK: interfeys va STT lotin yozuvida ishlaydi, lekin mavjud
platforma sintezatorlarida (Windows SAPI, macOS `say`) o'zbek ovozi yo'q.
Rus ovozi kirill matnini ancha tushunarli o'qiydi, shuning uchun TTS ga
matnni kirillda berish mumkin. Step 4 da on-prem TTS kelganda bu modul
kerak bo'lmay qolishi mumkin - lekin foydalanuvchi kirillda YOZGAN buyruqni
tushunish uchun teskari yo'nalish baribir asqotadi.

BU TO'LIQ ORFOGRAFIYA EMAS. Taxminiy, lekin barqaror: bir xil kirish har doim
bir xil chiqish beradi va hech qachon exception tashlamaydi. Rasmiy qoidada
"e" so'z boshida "э", ichida "е" bo'ladi - shu bitta kontekst hisobga olingan,
qolganlari (ts/ц, ye/е) oddiy almashtirish.
"""

from __future__ import annotations

import re

#: TARTIB MUHIM: uzun birikmalar oldin turishi shart, aks holda "sh" -> "сҳ"
#: bo'lib ketadi. Apostrof allaqachon `normalize.unify_apostrophes()` da
#: bitta ' ga keltirilgan deb hisoblanadi.
_LATIN_TO_CYRILLIC: tuple[tuple[str, str], ...] = (
    ("o'", "ў"), ("g'", "ғ"),
    ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"),
    ("ye", "е"), ("ts", "ц"), ("ng", "нг"),
    ("a", "а"), ("b", "б"), ("d", "д"), ("e", "е"), ("f", "ф"), ("g", "г"),
    ("h", "ҳ"), ("i", "и"), ("j", "ж"), ("k", "к"), ("l", "л"), ("m", "м"),
    ("n", "н"), ("o", "о"), ("p", "п"), ("q", "қ"), ("r", "р"), ("s", "с"),
    ("t", "т"), ("u", "у"), ("v", "в"), ("x", "х"), ("y", "й"), ("z", "з"),
    ("'", "ъ"),
)

#: Kirilldan lotinga. Bu yerda ham uzunlik bo'yicha tartib muhim emas (kirill
#: harflari bir belgili), lekin ko'p harfli lotin ekvivalentlari bor.
_CYRILLIC_TO_LATIN: tuple[tuple[str, str], ...] = (
    ("ў", "o'"), ("ғ", "g'"), ("ш", "sh"), ("ч", "ch"), ("щ", "sh"),
    ("ё", "yo"), ("ю", "yu"), ("я", "ya"), ("ц", "ts"), ("ж", "j"),
    ("а", "a"), ("б", "b"), ("в", "v"), ("г", "g"), ("д", "d"), ("е", "e"),
    ("з", "z"), ("и", "i"), ("й", "y"), ("к", "k"), ("л", "l"), ("м", "m"),
    ("н", "n"), ("о", "o"), ("п", "p"), ("р", "r"), ("с", "s"), ("т", "t"),
    ("у", "u"), ("ф", "f"), ("х", "x"), ("ҳ", "h"), ("қ", "q"), ("ъ", "'"),
    ("ы", "i"), ("э", "e"), ("ь", ""),
)

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)

#: So'z boshidagi "e" kirillda "э" bo'ladi ("eshik" -> "эшик").
_WORD_START_E = re.compile(r"(?<![a-z'])e", re.IGNORECASE)


def _apply(text: str, table: tuple[tuple[str, str], ...]) -> str:
    for src, dst in table:
        text = text.replace(src, dst)
    return text


def _restore_case(source: str, converted: str) -> str:
    """Bosh harfni saqlaydi. So'z butunlay katta bo'lsa - hammasi katta."""
    if not source or not converted:
        return converted
    if source.isupper() and len(source) > 1:
        return converted.upper()
    if source[0].isupper():
        return converted[:1].upper() + converted[1:]
    return converted


def _by_words(text: str, convert) -> str:
    return "".join(
        convert(part) if part.strip() else part
        for part in re.split(r"(\s+)", text)
    )


def to_cyrillic(text: str) -> str:
    """Lotin o'zbekchani kirillga o'giradi. Boshqa belgilarga tegmaydi."""
    if not text:
        return ""

    def word(source: str) -> str:
        lowered = source.lower()
        lowered = _WORD_START_E.sub("э", lowered) if lowered.startswith("e") else lowered
        return _restore_case(source, _apply(lowered, _LATIN_TO_CYRILLIC))

    return _by_words(str(text), word)


def to_latin(text: str) -> str:
    """Kirill o'zbekchani lotinga o'giradi."""
    if not text:
        return ""

    def word(source: str) -> str:
        return _restore_case(source, _apply(source.lower(), _CYRILLIC_TO_LATIN))

    return _by_words(str(text), word)


def detect(text: str) -> str:
    """Matn qaysi yozuvda: "cyrillic", "latin" yoki "other"."""
    if not text:
        return "other"
    cyrillic = len(_CYRILLIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if cyrillic == 0 and latin == 0:
        return "other"
    return "cyrillic" if cyrillic > latin else "latin"


def to_script(text: str, script: str) -> str:
    """Matnni ko'rsatilgan yozuvga keltiradi (`locale.yaml` dagi `script`)."""
    script = (script or "").strip().lower()
    if script == "cyrillic":
        return text if detect(text) == "cyrillic" else to_cyrillic(text)
    if script == "latin":
        return text if detect(text) == "latin" else to_latin(text)
    return text

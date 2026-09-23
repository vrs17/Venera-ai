"""TTS'ga ketadigan matn: sana, vaqt va qisqartmalar SO'Z bilan.

NEGA. TTS serverining raqam normalizatori sanani, vaqtni va "MChJ" kabi
qisqartmani yomon o'qiydi. Jonli tekshirilgan (2026-09-23): TTS ovozi STT
bilan qayta matnga o'girildi, ya'ni jadvalda aynan ESHITILGANI turibdi.

| Matnda                  | Eshitildi                                  |
|-------------------------|--------------------------------------------|
| `“BRB-TECH” MCHJ`       | "b chepche"                                |
| `2026-10-21`            | "ikki ming yigirma olti o'n yigirma bir"   |
| `25.09.2026-30.09.2026` | "... yil, yil o'ttizinchi ..."             |
| `09:00-18:00`           | "to'qqiz nol o'n sakkiz nol"               |
| `09.09.2025dan`         | HTTP 422 - javob umuman ovozsiz qoldi      |

Shuning uchun bularni normalizatorga QOLDIRMAYMIZ, o'zimiz o'zbekcha so'z
bilan yozamiz. Qolgan raqamlar ("12 marta", "2450000 so'm") normalizatorda
qoladi: ularni u to'g'ri o'qiydi.

FAQAT OVOZ UCHUN. Ekrandagi javob o'zgarmaydi, bu yerda faqat TTS'ga
ketadigan nusxa tayyorlanadi.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

#: Joriy yil shu soat mintaqasi bo'yicha: foydalanuvchilar O'zbekistonda.
_TASHKENT = timezone(timedelta(hours=5))

_UNITS = ("", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz")
_TENS = ("", "o'n", "yigirma", "o'ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to'qson")
#: Rasmiy lotin imlosi: "sentabr", "oktabr" ("sentyabr" emas).
MONTHS = ("yanvar", "fevral", "mart", "aprel", "may", "iyun",
          "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr")

#: Sana va vaqtdan keyin keladigan kelishik qo'shimchalari. TARTIB MUHIM:
#: uzuni oldin, aks holda "dagi" dan "da" olinib, "gi" ortib qolardi.
_SUFFIX = r"(?:dagi|gacha|dan|ning|da|ga|ni|gi)"
#: Qo'shimcha: yopishgan (`dan`), chiziqchali (`-dan`) yoki alohida so'z
#: (`09:00 dan`). Keyin harf kelsa - bu qo'shimcha emas, boshqa so'z.
_TAIL_SUFFIX = (rf"(?:-?(?P<qo>{_SUFFIX})(?![^\W\d_])"
                rf"|[ \t]+(?P<soz>{_SUFFIX})(?![^\W\d_]))?")
_RANGE_SEP = re.compile(r"[ \t]*[-–—][ \t]*")


# --- sonlar ------------------------------------------------------------------


def cardinal(n: int) -> str:
    """0..9999 -> "ikki ming yigirma olti"."""
    if n == 0:
        return "nol"
    words: list[str] = []
    thousands, rest = divmod(n, 1000)
    if thousands:
        words += [_UNITS[thousands], "ming"]
    hundreds, rest = divmod(rest, 100)
    if hundreds:
        words += ["yuz"] if hundreds == 1 else [_UNITS[hundreds], "yuz"]
    tens, units = divmod(rest, 10)
    words += [w for w in (_TENS[tens], _UNITS[units]) if w]
    return " ".join(words)


def ordinal(n: int) -> str:
    """Tartib son: faqat OXIRGI so'z qo'shimcha oladi ("yigirma birinchi")."""
    words = cardinal(n)
    return words + ("nchi" if words[-1] in "aeiou" else "inchi")


def attach(word: str, suffix: str) -> str:
    """Qo'shimchani imlo bo'yicha qo'shadi: k/q dan keyin g -> k/q
    ("qirq" + "ga" = "qirqqa", "ellik" + "gacha" = "ellikkacha")."""
    if suffix.startswith("g") and word[-1:] in ("k", "q"):
        suffix = word[-1] + suffix[1:]
    return word + suffix


# --- qisqartmalar -------------------------------------------------------------

#: Tashkiliy-huquqiy shakllar: (qisqartma naqshi, nomdan keyin, yolg'iz).
#: "“BRB-TECH” MChJ" -> "... jamiyati" (qaratqich); "MChJ ochish" -> "...
#: jamiyat ochish". `(qisqartmasi: MChJ)` ATAYLAB qo'shilmaydi: qavs ichidagi
#: "MChJ" yana "mchj" bo'lib o'qiladi (jonli eshitilgan).
_LEGAL_FORMS = (
    (r"M\.\s?Ch\.\s?J\.|(?i:MChJ)", "mas'uliyati cheklangan jamiyati", "mas'uliyati cheklangan jamiyat"),
    (r"AJ", "aksiyadorlik jamiyati", "aksiyadorlik jamiyati"),
    (r"ATB", "aksiyadorlik tijorat banki", "aksiyadorlik tijorat banki"),
    (r"XK", "xususiy korxonasi", "xususiy korxona"),
    (r"QK", "qo'shma korxonasi", "qo'shma korxona"),
    (r"DUK", "davlat unitar korxonasi", "davlat unitar korxona"),
    (r"Y[Aa]TT", "yakka tartibdagi tadbirkor", "yakka tartibdagi tadbirkor"),
)
_LEGAL_RE = tuple(
    # `@` va `/` - manzil ichida (`info@mchj.uz`) qisqartma emas.
    (re.compile(rf"(?<![\w.@/])(?:{pattern})(?:-?(?P<qo>{_SUFFIX}))?(?![^\W\d_])"), named, bare)
    for pattern, named, bare in _LEGAL_FORMS
)
#: Nom qo'shtirnog'i ovozda hech narsa bermaydi, lekin `«BRB-TECH»` ni
#: "barbi tech" qilib yubordi (jonli). Apostroflar (`o‘`, `ta’til`) - harf,
#: ular QOLADI.
_QUOTES = re.compile(r"[«»“”„\"]")


def _after_name(before: str) -> bool:
    """Qisqartma nomdan keyin keldimi: `“BRB-TECH” MChJ`, `Anor XK`."""
    prev = before.rstrip()
    if not prev:
        return False
    if prev[-1] in "\"'”»’":
        return True
    return any(ch.isupper() for ch in prev.split()[-1])


def _legal_forms(text: str) -> str:
    for pattern, named, bare in _LEGAL_RE:
        def expand(m: re.Match[str], named: str = named, bare: str = bare) -> str:
            words = named if _after_name(m.string[:m.start()]) else bare
            return attach(words, m.group("qo")) if m.group("qo") else words
        text = pattern.sub(expand, text)
    return text


# --- sanalar ------------------------------------------------------------------

_DMY_AT = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
#: `T08:45` bilan davom etsa - vaqt tamg'asi; `T` oldinroq bo'sh joyga
#: aylantiriladi, shunda sana ham, vaqt ham alohida o'qiladi.
_ISO_AT = re.compile(r"(?<![\d.])((?:19|20)\d\d)-(\d\d)-(\d\d)(?!\d)")
_ISO_T = re.compile(r"(?<![\d.])((?:19|20)\d\d-\d\d-\d\d)T(?=\d\d:\d\d)")
#: Sanadan keyingi dum: takroriy "yil" / "y." (sana so'zlarida yil bor) va
#: qo'shimcha: `09.09.2025-yildan` -> "... sentabrdan".
_DATE_TAIL = re.compile(
    rf"(?:[ \t]?-?[ \t]?(?P<yil>yil|y\.)(?={_SUFFIX}?(?![^\W\d_])))?" + _TAIL_SUFFIX
)


def _iso_as_dmy(m: re.Match[str]) -> str:
    year, month, day = m.groups()
    try:
        date(int(year), int(month), int(day))
    except ValueError:          # `2026-13-45` - kod yoki raqam, sana emas
        return m.group(0)
    return f"{day}.{month}.{year}"


def _date_of(m: re.Match[str]) -> date | None:
    day, month, year = (int(g) for g in m.groups())
    if not 1900 <= year <= 2099:
        return None
    try:
        return date(year, month, day)
    except ValueError:          # 31.02.2026 - sana emas, tegilmaydi
        return None


def _day_month(d: date, suffix: str) -> str:
    return f"{ordinal(d.day)} {attach(MONTHS[d.month - 1], suffix)}"


def _date_words(d: date, suffix: str, this_year: int) -> str:
    """JORIY YIL AYTILMAYDI: "yigirma sakkizinchi sentabr" - odam ham shunday
    gapiradi, va "... ikki ming yigirma oltinchi yil" har sanaga besh so'z
    qo'shardi. Boshqa yil - rasmiy tartibda, yil oldin."""
    words = _day_month(d, suffix)
    return words if d.year == this_year else f"{ordinal(d.year)} yil {words}"


def _range_words(a: date, b: date, suffix: str, this_year: int) -> str:
    """`A-B` -> "A dan B gacha". Oy nomi IKKALA tomonda ham aytiladi:
    "yigirma beshinchidan o'ttizinchi sentabrgacha" qisqaroq, lekin STT uni
    ikki marta ikki xil eshitdi ("yigirma beshdan o'ttiz"). Umumiy yil bir
    marta aytiladi."""
    if a.year != b.year:
        return f"{_date_words(a, 'dan', this_year)} {_date_words(b, suffix, this_year)}"
    words = f"{_day_month(a, 'dan')} {_day_month(b, suffix)}"
    return words if a.year == this_year else f"{ordinal(a.year)} yil {words}"


def _sentence_ends(text: str, pos: int) -> bool:
    rest = text[pos:]
    return not rest.strip() or (rest[:1].isspace() and rest.lstrip()[:1].isupper())


def _dates(text: str, this_year: int) -> str:
    text = _ISO_T.sub(r"\1 ", text)
    text = _ISO_AT.sub(_iso_as_dmy, text)
    out: list[str] = []
    pos = 0
    while (m := _DMY_AT.search(text, pos)):
        first = _date_of(m)
        if first is None:
            out.append(text[pos:m.end()])
            pos = m.end()
            continue
        end, second = m.end(), None
        if (sep := _RANGE_SEP.match(text, end)) and (m2 := _DMY_AT.match(text, sep.end())):
            if (second := _date_of(m2)) is not None:
                end = m2.end()
        tail = _DATE_TAIL.match(text, end)
        suffix = tail.group("qo") or tail.group("soz") or ""
        out.append(text[pos:m.start()])
        if second is None:
            out.append(_date_words(first, suffix, this_year))
        else:
            out.append(_range_words(first, second, suffix or "gacha", this_year))
        pos = tail.end()
        if tail.group("yil") == "y." and _sentence_ends(text, pos):
            out.append(".")         # "y." gap oxiri ham edi - pauza qolsin
        if text[pos:pos + 1].isalpha():
            out.append(" ")         # so'zlar keyingi so'zga yopishmasin
    out.append(text[pos:])
    return "".join(out)


# --- vaqt ---------------------------------------------------------------------

_TIME_AT = re.compile(r"(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?![\d:])")
_TIME_TAIL = re.compile(_TAIL_SUFFIX)
_SOAT_BEFORE = re.compile(r"soat[\s:]*$", re.IGNORECASE)


def _clock(hour: int, minute: int) -> str:
    """`09:00` -> "to'qqiz", `08:45` -> "sakkiz qirq besh", `13:05` -> "o'n
    uch nol besh". Soniyalar AYTILMAYDI: kelish vaqtidagi `:12` tinglovchi
    uchun faqat shovqin, ekranda esa to'liq turadi."""
    if minute == 0:
        return cardinal(hour)
    if minute < 10:
        return f"{cardinal(hour)} nol {cardinal(minute)}"
    return f"{cardinal(hour)} {cardinal(minute)}"


def _times(text: str) -> str:
    out: list[str] = []
    pos = 0
    last_end = -1
    while (m := _TIME_AT.search(text, pos)):
        start = (int(m.group(1)), int(m.group(2)))
        end, second = m.end(), None
        if (sep := _RANGE_SEP.match(text, end)) and (m2 := _TIME_AT.match(text, sep.end())):
            second = (int(m2.group(1)), int(m2.group(2)))
            end = m2.end()
        tail = _TIME_TAIL.match(text, end)
        suffix = tail.group("qo") or tail.group("soz") or ""
        before = text[pos:m.start()]
        out.append(before)
        # "soat" bir marta: matnda allaqachon bo'lsa yoki bu oldingi vaqtning
        # davomi bo'lsa (`09:00 dan 18:00 gacha`) - qo'shilmaydi.
        joined = last_end == pos and not before.strip()
        if not joined and not _SOAT_BEFORE.search(text[:m.start()]):
            out.append("soat ")
        if second is None:
            words = _clock(*start)
            out.append(attach(words, suffix) if suffix else words)
        else:
            out.append(f"{attach(_clock(*start), 'dan')} {attach(_clock(*second), suffix or 'gacha')}")
        pos = last_end = tail.end()
        if text[pos:pos + 1].isalpha():
            out.append(" ")
    out.append(text[pos:])
    return "".join(out)


# --- hammasi ------------------------------------------------------------------


def for_speech(text: str, *, today: date | None = None) -> str:
    """Matnni TTS o'qishiga tayyorlaydi. Tartib muhim: qisqartma nomni
    qo'shtirnoq bo'yicha taniydi, shuning uchun qo'shtirnoq undan KEYIN
    olinadi; sana `T08:45` ni vaqtga bo'shatadi, shuning uchun vaqtdan OLDIN."""
    this_year = (today or datetime.now(_TASHKENT).date()).year
    text = _legal_forms(text)
    text = _QUOTES.sub("", text)
    text = _dates(text, this_year)
    return _times(text)

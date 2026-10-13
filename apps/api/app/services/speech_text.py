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

import json
import logging
import re
import threading
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

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


# --- nomlar (talaffuz lug'ati) ---------------------------------------------------

#: Lug'at kaliti - qisqartma kod (`DVSIB`). Katta-kichik harf ANIQ solishtiriladi:
#: `Dvsib` - kod emas, oddiy so'z bo'lishi mumkin.
_NAME_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9&]{1,31}$")
_NAME_MAX = 200


#: Shu uzunlikkacha kod (`BA`, `IB`, `BCC`) FAQAT loyiha haqida gap ketganda
#: ochiladi - ortidan "loyiha..." kelsa. Qisqa harflar boshqa narsa ham bo'ladi:
#: "BA" - biznes-tahlilchi, "IB" - axborot xavfsizligi; ular gap o'rtasida loyiha
#: nomiga aylanib qolmasin. Uzun kod (`DVSIB`) esa yolg'iz turganda ham kod.
_SHORT_CODE = 3
_PROJECT_AFTER = re.compile(r"[\s*_]*loyiha", re.IGNORECASE)


@lru_cache(maxsize=32)
def _codes_at(codes: tuple[str, ...]) -> re.Pattern[str]:
    """Kod FAQAT o'z o'rnida: alohida so'z, ixtiyoriy qo'shimcha bilan
    (`DVSIBning`, `DVSIB-ga`). Vazifa kaliti (`DVSIB-266`), manzil
    (`x.uz/DVSIB`, `dvsib@...`) va boshqa so'z ichidagisi TEGILMAYDI - "Data va
    sun'iy intellekt bo'limi ikki yuz oltmish olti" vazifa kaliti emas.

    BITTA naqsh, BITTA o'tish: nom ichida boshqa kod bo'lsa ("BRB-TECH CRM"),
    qo'yilgan nom qayta almashtirilmaydi. Uzuni oldin - `BCCOC` `BCC` dan."""
    alternatives = "|".join(re.escape(code) for code in codes)
    return re.compile(
        rf"(?<![\w@/.\-])(?P<code>{alternatives})"
        rf"(?:[-'’ʼ]?(?P<qo>{_SUFFIX}))?(?![\w\-]|\.\w)"
    )


def _spoken_names(text: str, names: Mapping[str, str]) -> str:
    codes = tuple(sorted(names, key=lambda code: (-len(code), code)))

    def expand(m: re.Match[str]) -> str:
        code = m.group("code")
        if len(code) <= _SHORT_CODE and not _PROJECT_AFTER.match(m.string, m.end()):
            return m.group(0)
        spoken = names[code]
        return attach(spoken, m.group("qo")) if m.group("qo") else spoken

    text = _codes_at(codes).sub(expand, text)
    # Nom matnda kod bilan YONMA-YON yozilgan bo'lsa (`Sotuv bo'limi (SB)`) u endi
    # ikki marta aytilardi - qavsdagisi tashlanadi.
    for spoken in set(names.values()):
        twice = re.escape(spoken)
        text = re.sub(rf"({twice})[ \t]*\([ \t]*{twice}[ \t]*\)", r"\1", text, flags=re.IGNORECASE)
    return text


class SpokenNames:
    """Talaffuz lug'ati fayli: `{"DVSIB": "Data va sun'iy intellekt bo'limi"}`.

    NEGA FAYL. Loyiha kodi (`DVSIB`) ovozda "de-ve-es-i-be" bo'lib eshitiladi -
    rahbar esa loyiha NOMINI eshitishni xohlaydi. Nomlar Venera'da yo'q (CRM
    loyihalari, `crm_list_projects`), va ular kam o'zgaradi: fayl o'zgarsa
    keyingi sintezda o'zi qayta o'qiladi, API'ni qayta ishga tushirish shart emas.
    Fayl git'da (`config/tts_names.json`) - nomlar MR orqali ko'rib chiqiladi.

    FAQAT OVOZ. Ekrandagi matn o'zgarmaydi. Fayl yo'q yoki buzuq bo'lsa ovoz
    BARIBIR ishlaydi - lug'atsiz (buzuq faylda oxirgi yaroqli nusxa bilan).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._names: dict[str, str] = {}

    def __call__(self) -> dict[str, str]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            log.warning("TTS lug'ati o'qilmadi (%s): %s", self.path, exc)
            return self._names
        stamp = (st.st_mtime_ns, st.st_size)
        with self._lock:
            if stamp != self._stamp:
                # Belgi xato bo'lsa ham yangilanadi: buzuq fayl har sintezda
                # qayta o'qilib, jurnalni to'ldirmasin.
                self._stamp = stamp
                self._names = self._load(self._names)
            return self._names

    def _load(self, previous: dict[str, str]) -> dict[str, str]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("TTS lug'ati buzuq (%s), oldingisi qoldi: %s", self.path, exc)
            return previous
        if not isinstance(raw, dict):
            log.warning("TTS lug'ati obyekt emas (%s), oldingisi qoldi", self.path)
            return previous
        names: dict[str, str] = {}
        for code, spoken in raw.items():
            spoken = " ".join(spoken.split()) if isinstance(spoken, str) else ""
            if not _NAME_KEY.match(str(code)) or not spoken or len(spoken) > _NAME_MAX:
                log.warning("TTS lug'ati: yaroqsiz yozuv tashlandi: %r", code)
                continue
            names[str(code)] = spoken
        log.info("TTS lug'ati: %d ta nom (%s)", len(names), self.path)
        return names


# --- hammasi ------------------------------------------------------------------


def for_speech(text: str, *, today: date | None = None,
               names: Mapping[str, str] | None = None) -> str:
    """Matnni TTS o'qishiga tayyorlaydi. Tartib muhim: qisqartma nomni
    qo'shtirnoq bo'yicha taniydi, shuning uchun qo'shtirnoq undan KEYIN
    olinadi; sana `T08:45` ni vaqtga bo'shatadi, shuning uchun vaqtdan OLDIN.
    Loyiha nomlari (`names`) - hammasidan OLDIN: nomning o'zidagi qo'shtirnoq
    va sana keyingi qadamlarda boshqalari kabi tozalanadi."""
    this_year = (today or datetime.now(_TASHKENT).date()).year
    if names:
        text = _spoken_names(text, names)
    text = _legal_forms(text)
    text = _QUOTES.sub("", text)
    text = _dates(text, this_year)
    return _times(text)

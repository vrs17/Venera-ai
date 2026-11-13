"""Muddatlarni KOD hal qiladi: "ertaga", "jumagacha", "до пятницы", "end of month".

NEGA MODELGA ISHONILMAYDI. Model nisbiy sanani ko'pincha to'g'ri hal qiladi,
lekin xato qilganda bu eng qimmat xato: vazifaning muddati bir kunga siljiydi
va hech kim sezmaydi. Shuning uchun model yozgan `due.raw` iborasi shu
jadval bilan QAYTA hal qilinadi; natija farq qilsa kod g'olib, vazifaga esa
"tekshiring" belgisi qo'yiladi (`summarize.Validator.resolve_date`). Ibora
transkriptdagi keltirilgan qatorda AYNAN bo'lishi ham tekshiriladi - model
to'qigan "ertaga" kod jadvalidan o'tib "aniq" sana bo'lib qolmasin.

Jadval uch tilda: o'zbek, rus (kirill VA lotin - ASR ruschani ko'pincha lotin
harfida yozadi: "zavtra", "do pyatnitsy"), ingliz.

Vaqt mintaqasi - Asia/Tashkent, QAT'IY +5 (yozgi vaqt yo'q; `tzdata` ga
bog'liq bo'lmaslik uchun - `gapi_stt._today` dagi qoida).
"""

from __future__ import annotations

import calendar
import re

from datetime import date, datetime, timedelta, timezone

TASHKENT = timezone(timedelta(hours=5))

#: Apostrof ko'rinishlari bir xil ("oʻtgan" = "o'tgan").
_APOS_FOLD = str.maketrans({c: "'" for c in "ʻʼ’‘`´"})

WEEKDAYS = {
    "uz": ("dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"),
    "ru": ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}

MONTHS = {
    # Rasmiy lotin imlosi: "sentabr", "oktabr" (`speech_text.MONTHS` va veb ilova bilan bir xil;
    # mahsulot egasi tasdiqlagan "Qisqa xulosa" namunasi ham "10-oktabr"). O'qishda (`_MONTH_FORMS`)
    # ikkala yozuv ham taniladi.
    "uz": ("yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr",
           "oktabr", "noyabr", "dekabr"),
    # Rus tilida sana bilan qaratqich kelishigida: "10 октября".
    "ru": ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
           "октября", "ноября", "декабря"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"),
}

# --- ibora jadvali ------------------------------------------------------------------
#
# HAR NAQSH SO'Z CHEGARASI BILAN. Avvalgi jadval so'z BOSHINI qidirardi va
# o'zbek tilida bu xavfli edi: "mayli" -> may oyi, "2 marta" (ikki marta) ->
# 2-mart, "Jumanazarov" -> juma, "среди" -> среда. Endi:
#   * oy nomi FAQAT yonida kun raqami bo'lsa sana ("25-oktyabrgacha", "5 мая",
#     "Oct 25"), va o'sha moslikdagi raqam olinadi ("soat 3 da, 10-noyabr" -> 10);
#   * o'zbekcha so'zga faqat kelishik qo'shimchalari ruxsat (-gacha, -da, -ga...);
#   * inglizcha 3 harfli qisqartmalar (may, mar, jan...) faqat raqam bilan.

#: O'zbekcha kelishik qo'shimchalari ("jumagacha", "oktyabrda", "seshanbaga").
_UZ_SUFFIX = r"(?:gacha|igacha|ga|iga|da|ida|dan|idan|ning|ining|ni|ini|dagi|idagi|si|kuni|ki)?"


def _alt(words: tuple[str, ...]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


#: Hafta kunlari: (raqam, o'zbekcha, ruscha/lotin-ruscha shakllar, inglizcha).
_WEEKDAY_FORMS: tuple[tuple[int, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    (0, ("dushanba",), ("понедельник", "понедельника", "понедельнику", "ponedelnik", "ponedel'nik",
                        "ponedelnika", "ponedelniku"), ("monday",)),
    (1, ("seshanba",), ("вторник", "вторника", "вторнику", "vtornik", "vtornika", "vtorniku"), ("tuesday",)),
    (2, ("chorshanba",), ("среда", "среду", "среды", "среде", "sreda", "sredu", "sredy", "srede"), ("wednesday",)),
    (3, ("payshanba",), ("четверг", "четверга", "четвергу", "chetverg", "chetverga", "chetvergu"),
     ("thursday",)),
    (4, ("juma",), ("пятница", "пятницу", "пятницы", "пятнице", "pyatnitsa", "pyatnitsu", "pyatnitsy",
                    "pyatnitse", "pyatnica", "pyatnicu", "pyatnicy", "pyatnice"), ("friday",)),
    (5, ("shanba",), ("суббота", "субботу", "субботы", "субботе", "subbota", "subbotu", "subboty", "subbote"),
     ("saturday",)),
    (6, ("yakshanba",), ("воскресенье", "воскресенья", "воскресенью", "voskresenye", "voskresenya",
                         "voskresenyu", "voskresen'e"),
     ("sunday",)),
)


def _weekday_re(uz: tuple[str, ...], ru: tuple[str, ...], en: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:(?:{_alt(uz)}){_UZ_SUFFIX}|{_alt(ru)}|(?:{_alt(en)})s?)(?!\w)")


_WEEKDAYS_RE = tuple((number, _weekday_re(uz, ru, en)) for number, uz, ru, en in _WEEKDAY_FORMS)

#: Oylar: (raqam, o'zbekcha ildizlar, ruscha shakllar, inglizcha to'liq, inglizcha qisqartma).
#: Lotin harfidagi ruscha "marta"/"maya" ATAYLAB yo'q: o'zbekcha "2 marta" = ikki marta.
_MONTH_FORMS: tuple[tuple[int, tuple[str, ...], tuple[str, ...], str, str], ...] = (
    (1, ("yanvar",), ("января", "январь", "январе", "yanvarya"), "january", "jan"),
    (2, ("fevral",), ("февраля", "февраль", "феврале", "fevralya"), "february", "feb"),
    (3, ("mart",), ("марта", "март", "марте"), "march", "mar"),
    (4, ("aprel",), ("апреля", "апрель", "апреле", "aprelya"), "april", "apr"),
    (5, ("may",), ("мая", "май", "мае"), "may", ""),
    (6, ("iyun",), ("июня", "июнь", "июне", "iyunya", "iyuna"), "june", "jun"),
    (7, ("iyul",), ("июля", "июль", "июле", "iyulya", "iyula"), "july", "jul"),
    (8, ("avgust",), ("августа", "август", "августе", "avgusta"), "august", "aug"),
    (9, ("sentyabr", "sentabr"), ("сентября", "сентябрь", "сентябре", "sentyabrya", "sentabrya"),
     "september", "sept"),
    (10, ("oktyabr", "oktabr"), ("октября", "октябрь", "октябре", "oktyabrya", "oktabrya"), "october", "oct"),
    (11, ("noyabr",), ("ноября", "ноябрь", "ноябре", "noyabrya"), "november", "nov"),
    (12, ("dekabr",), ("декабря", "декабрь", "декабре", "dekabrya"), "december", "dec"),
)


def _month_name_re() -> str:
    parts = []
    for number, uz, ru, en, abbr in _MONTH_FORMS:
        names = [rf"(?:{_alt(uz)}){_UZ_SUFFIX}", _alt(ru), re.escape(en)]
        if abbr:
            # Qisqartma: "Oct 25", "25 Oct.", "Sep"/"Sept" - lekin "marta", "mayli" EMAS.
            names.append(rf"{re.escape(abbr[:3])}{'t?' if abbr == 'sept' else ''}\.?")
        parts.append(rf"(?P<m{number}>{'|'.join(names)})")
    return "|".join(parts)


_MONTH_NAME = _month_name_re()
#: "25-oktyabrgacha", "5 мая", "25 Oct" - kun OLDIN.
_DAY_MONTH = re.compile(rf"(?<![\w:.,])(?P<day>\d{{1,2}})(?:-?(?:chi|inchi|nchi)|st|nd|rd|th)?(?:\s+of)?\s*[-.]?\s*"
                        rf"(?:{_MONTH_NAME})(?!\w)")
#: "October 25", "Oct. 25" - oy OLDIN (faqat inglizcha shakl uchun mantiqli, lekin hammasi ruxsat).
_MONTH_DAY = re.compile(rf"(?<!\w)(?:{_MONTH_NAME})\s*(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?![\d:.]\d)(?!\w)")

#: Soat konteksti - "10.05" sana emas, vaqt ("soat 10.05 gacha").
_TIME_CONTEXT = re.compile(r"(?<!\w)(?:soat|час\w*|chas\w*|time|at|pm|am|утра|вечера|utra|vechera)(?!\w)|\d:\d")

_TODAY = re.compile(r"(?<!\w)(?:bugun\w*|сегодня|segodnya|today)(?!\w)")
_TOMORROW = re.compile(r"(?<!\w)(?:ertaga\w*|завтра|zavtra|tomorrow)(?!\w)")
_PLUS2 = re.compile(r"(?<!\w)(?:indinga\w*|послезавтра|poslezavtra|day after tomorrow)(?!\w)")

#: "keyingi / kelasi / следующей / next" - keyingi hafta yoki oy.
_NEXT = r"(?:keyingi|kelasi|kelgusi|следующ\w*|sleduyushch\w*|sleduyush\w*|next)"
_WEEK = r"(?:hafta\w*|недел\w*|nedel\w*|week)"
_MONTH = r"(?:oy|oyning|oyi|oyda|месяц\w*|mesyats\w*|mesyac\w*|month)"
_END = r"(?:oxir\w*|ohir\w*|yakun\w*|конц\w*|kont?s\w*|konc\w*|end)"

_END_NEXT_WEEK = re.compile(rf"(?<!\w)(?:{_NEXT}\s+{_WEEK}\s+{_END}|{_END}\s+(?:of\s+)?{_NEXT}\s+{_WEEK})(?!\w)")
_END_WEEK = re.compile(rf"(?<!\w)(?:{_WEEK}\s+{_END}|{_END}\s+(?:of\s+)?(?:the\s+|this\s+|этой\s+|etoy\s+)?{_WEEK})(?!\w)")
_END_NEXT_MONTH = re.compile(rf"(?<!\w)(?:{_NEXT}\s+{_MONTH}\s+{_END}|{_END}\s+(?:of\s+)?{_NEXT}\s+{_MONTH})(?!\w)")
_END_MONTH = re.compile(rf"(?<!\w)(?:{_MONTH}\s+{_END}|{_END}\s+(?:of\s+)?(?:the\s+|this\s+|этого\s+|etogo\s+)?{_MONTH})(?!\w)")
_NEXT_WEEK = re.compile(rf"(?<!\w)(?:{_NEXT}\s+{_WEEK}|на\s+следующей\s+неделе|na\s+sleduyushch\w*\s+nedele)(?!\w)")

#: Son so'zlari - "bir haftadan keyin", "через две недели", "in two days".
_NUMBER_WORDS = {
    "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "tort": 4, "besh": 5, "olti": 6, "yetti": 7, "sakkiz": 8,
    "to'qqiz": 9, "toqqiz": 9, "o'n": 10, "on": 10,
    "один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "десять": 10, "odin": 1, "odnu": 1, "dva": 2, "dve": 2, "tri": 3, "chetyre": 4, "pyat": 5,
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10,
}
_NUM = r"(?P<n>\d{1,2}|" + _alt(tuple(_NUMBER_WORDS)) + r")"
#: O'zbekcha: "2 kunda", "2 kundan keyin", "bir hafta ichida", "bir oyda". "2 kunlik" (davomiylik) EMAS.
_UZ_OFFSET = re.compile(
    rf"(?<!\w){_NUM}\s*(?P<unit>kun|hafta|oy)(?:da|dan\s+keyin|dan\s+so'ng|dan\s+song|\s+ichida)(?!\w)"
    r"|(?<!\w)(?P<unit2>hafta|oy)\s+ichida(?!\w)")
#: Ruscha: "через 2 дня", "через неделю", "в течение недели".
_RU_OFFSET = re.compile(
    rf"(?<!\w)(?:через|cherez|в\s+течение|v\s+techenie)\s+{_NUM}?\s*(?P<unit>день|дня|дней|недел\w*|месяц\w*|"
    rf"den|dnya|dney|nedel\w*|mesyats\w*|mesyac\w*)(?!\w)")
#: Inglizcha: "in 2 days", "within a week".
_EN_OFFSET = re.compile(rf"(?<!\w)(?:in|within)\s+{_NUM}?\s*(?P<unit>days?|weeks?|months?)(?!\w)")

#: O'tgan zamon: muddat bo'la olmaydi ("kecha", "o'tgan juma", "2 kun oldin").
#: "jumadan oldin" (jumagacha) - O'TGAN EMAS, shuning uchun "oldin/avval" faqat son+birlik bilan.
_PAST = re.compile(
    r"(?<!\w)(?:o'tgan\w*|otgan\w*|kecha|kechagi|прошл\w*|proshl\w*|вчера|vchera|назад|nazad|last|ago|yesterday)(?!\w)"
    r"|(?<!\w)(?:\d{1,2}|bir|ikki|uch)\s*(?:kun|hafta|oy|yil)\s+(?:oldin|avval)(?!\w)")
_YESTERDAY = re.compile(r"(?<!\w)(?:kecha|kechagi|вчера|vchera|yesterday)(?!\w)")
_AGO = re.compile(rf"(?<!\w){_NUM}\s*(?P<unit>kun|hafta|oy|дн\w*|дня|недел\w*|days?|weeks?)\s+"
                  r"(?:oldin|avval|назад|nazad|ago)(?!\w)")

_VAGUE = re.compile(
    r"(?<!\w)(?:tez\s+orada|keyinroq|keyingi\s+hafta|kelasi\s+hafta|yaqin\s+kunlarda|imkon\s+qadar|скоро|skoro|"
    r"на\s+следующей\s+неделе|na\s+sleduyushch\w*\s+nedele|na\s+sleduyushey\s+nedele|позже|pozzhe|asap|"
    r"as\s+soon\s+as\s+possible|next\s+week|soon|later)(?!\w)")


def _number(raw: str | None) -> int:
    if not raw:
        return 1
    if raw.isdigit():
        return int(raw)
    return _NUMBER_WORDS.get(raw, 1)


def _weekday_of(text: str) -> int | None:
    """Iboradagi hafta kuni. "dushanbadan jumagacha" - muddat "-gacha" li kun."""
    found: list[tuple[int, int, bool]] = []
    for number, pattern in _WEEKDAYS_RE:
        for hit in pattern.finditer(text):
            found.append((hit.start(), number, hit.group().endswith("gacha")))
    if not found:
        return None
    until = [f for f in found if f[2]]
    return min(until or found)[1]


def _next_weekday(base: date, weekday: int) -> date:
    """Uchrashuv kunidan KEYINGI shu hafta kuni (o'sha kunning o'zi emas)."""
    delta = (weekday - base.weekday()) % 7
    return base + timedelta(days=delta or 7)


def _prev_weekday(base: date, weekday: int) -> date:
    delta = (base.weekday() - weekday) % 7
    return base - timedelta(days=delta or 7)


def _end_of_week(base: date) -> date:
    """Shu haftaning jumasi; uchrashuv jumadan keyin bo'lsa - keyingi juma."""
    if base.weekday() <= 4:
        return base + timedelta(days=4 - base.weekday())
    return base + timedelta(days=(4 - base.weekday()) % 7)


def _next_week_monday(base: date) -> date:
    return base + timedelta(days=7 - base.weekday())


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(base: date, months: int) -> date:
    index = base.month - 1 + months
    year, month = base.year + index // 12, index % 12 + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def _nearest(base: date, month: int, day: int, *, past_ok: bool) -> date | None:
    """Yilsiz sana. Muddat: uchrashuv kunidan boshlab eng yaqin KELGUSI sana.
    Voqea (`dates[]`): eng yaqini, ~6 oygacha o'tmishda ham."""
    candidates = []
    for year in (base.year - 1, base.year, base.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    if past_ok:
        near = [c for c in candidates if -183 <= (c - base).days <= 183]
        return min(near, key=lambda c: abs((c - base).days)) if near else None
    future = [c for c in candidates if c >= base]
    return min(future) if future else None


def _explicit(text: str, base: date, *, past_ok: bool) -> date | None:
    iso = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    full = re.search(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{2}|\d{4})(?![\d.])", text)
    if full:
        year = int(full.group(3))
        year = year + 2000 if year < 100 else year
        try:
            return date(year, int(full.group(2)), int(full.group(1)))
        except ValueError:
            return None
    for pattern in (_DAY_MONTH, _MONTH_DAY):
        for hit in pattern.finditer(text):
            day = int(hit.group("day"))
            month = next(int(k[1:]) for k, v in hit.groupdict().items() if k.startswith("m") and v)
            if 1 <= day <= 31:
                found = _nearest(base, month, day, past_ok=past_ok)
                if found is not None:
                    return found
    if not _TIME_CONTEXT.search(text):
        dotted = re.search(r"(?<![\d.:])(\d{1,2})[./](\d{1,2})(?![\d.:])", text)
        if dotted:
            day, month = int(dotted.group(1)), int(dotted.group(2))
            if 1 <= day <= 31 and 1 <= month <= 12:
                return _nearest(base, month, day, past_ok=past_ok)
    return None


#: `mentioned`: oy nomli sana yonidagi yil - "2026 yil 11 noyabr" (oldin) yoki "11 ноября 2026 г." (keyin).
_YEAR_BEFORE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-]?\s*(?:yil\w*|йил\w*|г\.?|года?)?\s*[,.]?\s*$")
_YEAR_AFTER = re.compile(r"^\s*[,.]?\s*((?:19|20)\d{2})(?!\d)")


def mentioned(raw: str | None, base: date) -> list[date]:
    """Matnda ANIQ aytilgan HAMMA sanalar (`_explicit` naqshlari): ISO ("2026-11-11"), "11.11.2026", "11-noyabr",
    "11 ноября 2026 г.", "2026 yil 11 noyabr", "November 11", "11.11". Yil aytilmagan sana - `base` ga eng yaqin kun
    (~6 oy o'tmish yoki kelajak, `_nearest`). Nisbiy so'zlar ("kecha", "bugun") - yo'q: ular qaysi kunga nisbatan
    ekani noma'lum. Bayonnoma sarlavhasidagi sanani EGA aytganmi - shu bilan tekshiriladi (`minutes.validate`)."""
    text = " ".join(str(raw or "").lower().translate(_APOS_FOLD).split())
    found: list[date] = []

    def add(year: int, month: int, day: int) -> None:
        try:
            value = date(year, month, day)
        except ValueError:
            return
        if value not in found:
            found.append(value)

    for hit in re.finditer(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", text):
        add(int(hit.group(1)), int(hit.group(2)), int(hit.group(3)))
    for hit in re.finditer(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{2}|\d{4})(?![\d.])", text):
        year = int(hit.group(3))
        add(year + 2000 if year < 100 else year, int(hit.group(2)), int(hit.group(1)))
    for pattern in (_DAY_MONTH, _MONTH_DAY):
        for hit in pattern.finditer(text):
            day = int(hit.group("day"))
            month = next(int(k[1:]) for k, v in hit.groupdict().items() if k.startswith("m") and v)
            stated = _YEAR_BEFORE.search(text[:hit.start()][-16:]) or _YEAR_AFTER.search(text[hit.end():])
            if stated:
                add(int(stated.group(1)), month, day)
            elif 1 <= day <= 31:
                near = _nearest(base, month, day, past_ok=True)
                if near is not None:
                    add(near.year, near.month, near.day)
    if not _TIME_CONTEXT.search(text):
        for hit in re.finditer(r"(?<![\d.:])(\d{1,2})[./](\d{1,2})(?![\d.:])", text):
            near = _nearest(base, int(hit.group(2)), int(hit.group(1)), past_ok=True) \
                if 1 <= int(hit.group(2)) <= 12 else None
            if near is not None:
                add(near.year, near.month, near.day)
    return found


def _offset(text: str, base: date) -> date | None:
    for pattern in (_UZ_OFFSET, _RU_OFFSET, _EN_OFFSET):
        hit = pattern.search(text)
        if not hit:
            continue
        groups = hit.groupdict()
        n = _number(groups.get("n"))
        unit = groups.get("unit") or groups.get("unit2") or ""
        if unit.startswith(("kun", "д", "dn", "den", "day")):
            return base + timedelta(days=n)
        if unit.startswith(("hafta", "недел", "nedel", "week")):
            return base + timedelta(days=7 * n)
        return _add_months(base, n)
    return None


def _past(text: str, base: date) -> date | None:
    """Faqat `dates[]` uchun: o'tgan voqea sanasi ("kecha", "o'tgan juma", "2 kun oldin")."""
    if _YESTERDAY.search(text):
        return base - timedelta(days=1)
    hit = _AGO.search(text)
    if hit:
        n = _number(hit.group("n"))
        unit = hit.group("unit")
        days = 7 * n if unit.startswith(("hafta", "недел", "week")) else n
        return base - timedelta(days=days)
    weekday = _weekday_of(text)
    if weekday is not None:
        return _prev_weekday(base, weekday)
    return None


def resolve(raw: str | None, meeting_day: date, *, event: bool = False) -> tuple[date | None, str]:
    """Ibora -> (sana, asos). Asos: `explicit` | `relative_resolved` | `vague` | `past` | `none`.

    `event=False` (muddat, `due.raw`, `nextMeeting.raw`): faqat kelajak; o'tgan
    zamon iborasi (`past`) muddat bo'la olmaydi. `event=True` (`dates[]` -
    tilga olingan voqea): yilsiz sana eng yaqin kunga (~6 oy o'tmishgacha),
    "kecha" / "o'tgan juma" ham hal qilinadi.

    `none` + `None` - ibora tanilmadi (chaqiruvchi model sanasini "tekshiring" bilan qoldiradi)."""
    text = " ".join(str(raw or "").lower().translate(_APOS_FOLD).split())
    if not text:
        return None, "none"
    found = _explicit(text, meeting_day, past_ok=event)
    if found is not None:
        return found, "explicit"
    if _PAST.search(text):
        if event:
            day = _past(text, meeting_day)
            return (day, "relative_resolved") if day else (None, "none")
        return None, "past"
    found = _offset(text, meeting_day)
    if found is not None:
        return found, "relative_resolved"
    if _END_NEXT_MONTH.search(text):
        nxt = _add_months(meeting_day.replace(day=1), 1)
        return _month_end(nxt.year, nxt.month), "relative_resolved"
    if _END_MONTH.search(text):
        return _month_end(meeting_day.year, meeting_day.month), "relative_resolved"
    if _END_NEXT_WEEK.search(text):
        return _next_week_monday(meeting_day) + timedelta(days=4), "relative_resolved"
    if _END_WEEK.search(text):
        return _end_of_week(meeting_day), "relative_resolved"
    weekday = _weekday_of(text)
    if weekday is not None and _NEXT_WEEK.search(text):
        return _next_week_monday(meeting_day) + timedelta(days=weekday), "relative_resolved"
    if _PLUS2.search(text):
        return meeting_day + timedelta(days=2), "relative_resolved"
    if _TOMORROW.search(text):
        return meeting_day + timedelta(days=1), "relative_resolved"
    if _TODAY.search(text):
        return meeting_day, "relative_resolved"
    if weekday is not None:
        return _next_weekday(meeting_day, weekday), "relative_resolved"
    if _VAGUE.search(text):
        return None, "vague"
    return None, "none"


def calendar_line(meeting_day: date) -> str:
    """Promptdagi taqvim - model va kod jadvali BIR XIL sanalarni ko'rsin (o'lchamdagi
    model hafta kuni arifmetikasida tez-tez adashadi, har farq esa "tekshiring")."""
    def d(day: date) -> str:
        return f"{WEEKDAYS['en'][day.weekday()][:3]} {day.isoformat()}"

    upcoming = ", ".join(d(_next_weekday(meeting_day, w)) for w in range(7))
    upcoming = ", ".join(sorted(upcoming.split(", "), key=lambda s: s[4:]))
    monday = _next_week_monday(meeting_day)
    nxt = _add_months(meeting_day.replace(day=1), 1)
    return (f"Calendar: today = {d(meeting_day)}; tomorrow = {d(meeting_day + timedelta(days=1))}; "
            f"next occurrence of each weekday: {upcoming}; next week (keyingi hafta) = {d(monday)} .. "
            f"{d(monday + timedelta(days=6))}; end of this week = {d(_end_of_week(meeting_day))}; "
            f"end of next week = {d(monday + timedelta(days=4))}; "
            f"end of this month = {_month_end(meeting_day.year, meeting_day.month).isoformat()}; "
            f"end of next month = {_month_end(nxt.year, nxt.month).isoformat()}.")


def parse_iso(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def tashkent(epoch: float) -> datetime:
    return datetime.fromtimestamp(float(epoch), TASHKENT)


def format_day_time(epoch: float, lang: str) -> str:
    """`10-oktabr, 16:00` / `10 октября, 16:00` / `October 10, 16:00`."""
    moment = tashkent(epoch)
    clock = moment.strftime("%H:%M")
    if lang == "ru":
        return f"{moment.day} {MONTHS['ru'][moment.month - 1]}, {clock}"
    if lang == "en":
        return f"{MONTHS['en'][moment.month - 1]} {moment.day}, {clock}"
    return f"{moment.day}-{MONTHS['uz'][moment.month - 1]}, {clock}"


def format_date(value: str | None, lang: str) -> str:
    """ISO sana -> til bo'yicha (`25-oktabr` / `25 октября` / `October 25`)."""
    day = parse_iso(value)
    if day is None:
        return value or ""
    if lang == "ru":
        return f"{day.day} {MONTHS['ru'][day.month - 1]}"
    if lang == "en":
        return f"{MONTHS['en'][day.month - 1]} {day.day}"
    return f"{day.day}-{MONTHS['uz'][day.month - 1]}"


def next_reset(now: float, *, minute: int = 5) -> float:
    """Keyingi 00:05 Asia/Tashkent (kunlik kvota yangilangandan keyin)."""
    moment = tashkent(now)
    target = moment.replace(hour=0, minute=minute, second=0, microsecond=0)
    if target <= moment:
        target += timedelta(days=1)
    return target.timestamp()


def day_key(now: float) -> str:
    return tashkent(now).date().isoformat()

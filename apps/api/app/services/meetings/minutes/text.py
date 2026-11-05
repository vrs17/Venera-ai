"""Bayonnoma matn konstantalari: tillar, sarlavhalar, yorliqlar, oylar, sanalar.

HAMMASI KODDA, MODELDA EMAS: hujjat sarlavhalari ("КУН ТАРТИБИ:", "ҚАРОР ҚИЛАДИ:"), rim raqamli
bo'lim qolipi, nazorat bandi qolipi, bo'sh joy belgisi va sana formati har hujjatda bir xil
bo'lsin; model faqat mazmunni yozadi (`minutes/prompt.py`).

TO'RT TIL (ega qarori, 2026-11-04): o'zbek lotin, o'zbek kirill, rus, ingliz. Bank hujjati
odatda kirillda - o'zbek yig'ilishning default'i `uz-cyrl`.

BO'SH JOYLAR (ega qarori): bank nomi, shahar, raislik qiluvchi, qatnashuvchilar guruhlari,
tasdiqlovchi, № va tasdiq sanasi, kelishuvchilar - hozircha `BLANK`; hujjat tizimi (hujjat.brb.uz)
yoki kotib to'ldiradi. Muddati/mas'uli aytilmagan bandlarda ham mas'ul o'rni `BLANK`.
"""

from __future__ import annotations

import re

from typing import Any

from .. import dates

LANGS = ("uz-latn", "uz-cyrl", "ru", "en")
#: Tugma/menyu nomlari (o'z tilida).
LANG_TITLES = {"uz-latn": "O'zbek (lotin)", "uz-cyrl": "Ўзбек (кирилл)", "ru": "Русский", "en": "English"}
#: Promptdagi "Output language" qatori uchun.
OUTPUT_LANGUAGE = {"uz-latn": "Uzbek (Latin script: o', g', sh, ch; never Cyrillic)",
                   "uz-cyrl": "Uzbek (Cyrillic script: ў, қ, ғ, ҳ; the official administrative register of "
                              "Uzbekistan state and bank documents; never Latin letters except codes and abbreviations)",
                   "ru": "Russian (official administrative register)", "en": "English (formal minutes register)"}
#: Hujjat tili -> Word/PDF til kodi (imlo tekshiruvi, PDF `/Lang`).
WORD_LANGS = {"uz-latn": "uz-Latn-UZ", "uz-cyrl": "uz-Cyrl-UZ", "ru": "ru-RU", "en": "en-US"}
#: To'ldiriladigan joy.
BLANK = "________"
#: Transkript/xulosa tili (`schemas.Lang`) -> hujjat tili default'i.
_DEFAULT = {"uz": "uz-cyrl", "ru": "ru", "en": "en"}


def normalize(lang: Any) -> str | None:
    """`uz-cyrl`, `uz_cyrl`, `UZ-CYRL`, `cyrl`, `uz` (= lotin) -> kanonik kod; noma'lum - `None`."""
    value = str(lang or "").strip().lower().replace("_", "-")
    aliases = {"uz": "uz-latn", "latn": "uz-latn", "lat": "uz-latn", "cyrl": "uz-cyrl", "kir": "uz-cyrl",
               "uz-cyr": "uz-cyrl", "uz-lat": "uz-latn"}
    value = aliases.get(value, value)
    return value if value in LANGS else None


def default_lang(meeting_language: Any) -> str:
    return _DEFAULT.get(str(meeting_language or "uz"), "uz-cyrl")


#: Sarlavha va yorliqlar. `doc` - hujjat nomi (ajratilgan harflar bilan markazda), `doc_word` - fayl
#: nomi va xabarlar uchun oddiy so'z, `section` - rim raqamli bo'lim qolipi (`{roman}`, `{title}`),
#: `control` - nazorat bandi qolipi (`{who}`), `preamble` - model yozmagan bo'lsa, `speaker` - izohlarda ismsiz
#: spiker (`{n}` - transkriptdagi raqam, bot xabaridagi "3-ishtirokchi" bilan bir xil), `speaker_any` - raqamsiz
#: qolip "[S#]" o'rniga (model ba'zan uni o'zini yozadi).
LABELS: dict[str, dict[str, str]] = {
    "uz-cyrl": {
        "doc": "Б А Ё Н И", "doc_word": "Баённома", "approve": "ТАСДИҚЛАЙМАН",
        "meeting_line": f"{BLANK} ҳузурида ўтказилган йиғилиш",
        "number": "№ ____", "approve_date": "«__» ____________ 20__ й.",
        "city": f"{BLANK} шаҳри", "chair": "Раислик қилувчи:", "attendees": "Қатнашдилар:",
        "agenda": "КУН ТАРТИБИ:", "speakers": "Сўзга чиққанлар:", "decides": "ҚАРОР ҚИЛАДИ:",
        "preamble": "Юқоридагиларни инобатга олиб, Йиғилиш",
        "section": "{roman}. {title} бўйича:",
        "control": "Ушбу баённома ижросини назорат қилиш {who} зиммасига юклатилсин.",
        "approvers": "Келишувчилар:",
        "draft": "ЛОЙИҲА - «________» жойлари қўлда тўлдирилади; бандлар ёзув асосида тузилган.",
        "notes": "Аниқлаштириш керак:", "speaker": "{n}-иштирокчи", "speaker_any": "иштирокчи",
        "warnings": "Текширув огоҳлантиришлари: {n} (ҳужжат ҳолатида кўринади).",
    },
    "uz-latn": {
        "doc": "B A Y O N I", "doc_word": "Bayonnoma", "approve": "TASDIQLAYMAN",
        "meeting_line": f"{BLANK} huzurida o'tkazilgan yig'ilish",
        "number": "№ ____", "approve_date": "«__» ____________ 20__ y.",
        "city": f"{BLANK} shahri", "chair": "Raislik qiluvchi:", "attendees": "Qatnashdilar:",
        "agenda": "KUN TARTIBI:", "speakers": "So'zga chiqqanlar:", "decides": "QAROR QILADI:",
        "preamble": "Yuqoridagilarni inobatga olib, Yig'ilish",
        "section": "{roman}. {title} bo'yicha:",
        "control": "Ushbu bayonnoma ijrosini nazorat qilish {who} zimmasiga yuklatilsin.",
        "approvers": "Kelishuvchilar:",
        "draft": "LOYIHA - «________» joylari qo'lda to'ldiriladi; bandlar yozuv asosida tuzilgan.",
        "notes": "Aniqlashtirish kerak:", "speaker": "{n}-ishtirokchi", "speaker_any": "ishtirokchi",
        "warnings": "Tekshiruv ogohlantirishlari: {n} (hujjat holatida ko'rinadi).",
    },
    "ru": {
        "doc": "П Р О Т О К О Л", "doc_word": "Протокол", "approve": "УТВЕРЖДАЮ",
        "meeting_line": f"совещания под председательством {BLANK}",
        "number": "№ ____", "approve_date": "«__» ____________ 20__ г.",
        "city": f"г. {BLANK}", "chair": "Председательствовал:", "attendees": "Присутствовали:",
        "agenda": "ПОВЕСТКА ДНЯ:", "speakers": "Выступили:", "decides": "РЕШИЛО:",
        "preamble": "Принимая во внимание вышеизложенное, Совещание",
        "section": "{roman}. По вопросу «{title}»:",
        "control": "Контроль за исполнением настоящего протокола возложить на {who}.",
        "approvers": "Согласовано:",
        "draft": "ПРОЕКТ - места «________» заполняются вручную; пункты составлены по записи.",
        "notes": "Требует уточнения:", "speaker": "Участник {n}", "speaker_any": "участник",
        "warnings": "Предупреждений проверки: {n} (см. состояние документа).",
    },
    "en": {
        "doc": "M I N U T E S", "doc_word": "Minutes", "approve": "APPROVED",
        "meeting_line": f"of the meeting chaired by {BLANK}",
        "number": "No. ____", "approve_date": "____ ____________ 20__",
        "city": f"{BLANK}", "chair": "Chair:", "attendees": "Attendees:",
        "agenda": "AGENDA:", "speakers": "Speakers:", "decides": "RESOLVES:",
        "preamble": "Having considered the above, the Meeting",
        "section": "{roman}. On {title}:",
        "control": "Control over the execution of these minutes is assigned to {who}.",
        "approvers": "Agreed by:",
        "draft": "DRAFT - the «________» fields are to be filled in by hand; items are based on the recording.",
        "notes": "To be clarified:", "speaker": "Speaker {n}", "speaker_any": "speaker",
        "warnings": "Validation warnings: {n} (see the document status).",
    },
}

MONTHS: dict[str, tuple[str, ...]] = {
    "uz-cyrl": ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
                "ноябрь", "декабрь"),
    "uz-latn": ("yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr",
                "noyabr", "dekabr"),
    "ru": ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
           "ноября", "декабря"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
}


def label(key: str, lang: str) -> str:
    table = LABELS.get(lang) or LABELS["uz-cyrl"]
    return table.get(key) or LABELS["uz-cyrl"].get(key, key)


def format_date(epoch: float, lang: str) -> str:
    """Hujjat sanasi: `2026 йил 4 ноябрь` / `2026 yil 4 noyabr` / `4 ноября 2026 года` / `4 November 2026`."""
    moment = dates.tashkent(epoch)
    month = MONTHS.get(lang, MONTHS["uz-cyrl"])[moment.month - 1]
    if lang == "ru":
        return f"{moment.day} {month} {moment.year} года"
    if lang == "en":
        return f"{moment.day} {month} {moment.year}"
    if lang == "uz-latn":
        return f"{moment.year} yil {moment.day} {month}"
    return f"{moment.year} йил {moment.day} {month}"


#: Kun tartibi sarlavhasi oxiridagi/boshidagi ko'makchi so'zlar - bo'lim qolipiga ("... бўйича:",
#: "On ...:") qo'shilganda ikkilanmasin: "Режа ижроси тўғрисида бўйича" emas, "Режа ижроси бўйича".
_TRAILING = {
    "uz-cyrl": re.compile(r"\s+(тўғрисида|тугрисида|ҳақида|хакида|юзасидан|бўйича|буйича)\s*$", re.IGNORECASE),
    "uz-latn": re.compile(r"\s+(to[\'`ʻʼ’‘]?g[\'`ʻʼ’‘]?risida|haqida|yuzasidan|bo[\'`ʻʼ’‘]?yicha)\s*$", re.IGNORECASE),
}
_LEADING = {"en": re.compile(r"^(on|about|regarding)\s+", re.IGNORECASE)}


def section_title(title: str, lang: str) -> str:
    """Bo'lim sarlavhasi uchun kun tartibi matni: oxiridagi tinish belgilari va tildagi ko'makchi
    (тўғрисида / to'g'risida / On) olib tashlanadi - qolip o'zi qo'shadi."""
    value = re.sub(r"[\s.;:,]+$", "", str(title or "").strip())
    tail = _TRAILING.get(lang)
    if tail is not None:
        value = tail.sub("", value)
    head = _LEADING.get(lang)
    if head is not None:
        value = head.sub("", value)
    return value.strip()


def roman(n: int) -> str:
    """1 -> I, 4 -> IV, 12 -> XII (bo'limlar 1-39 oralig'ida)."""
    values = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    n, out = max(1, int(n)), ""
    for value, symbol in values:
        while n >= value:
            out += symbol
            n -= value
    return out


def script_share(text: str) -> tuple[int, int, int]:
    """(kirill harflar, lotin harflar, jami harflar) - yozuv tilini tekshirish uchun."""
    cyr = lat = total = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total += 1
        code = ord(ch)
        if 0x0400 <= code <= 0x04FF:
            cyr += 1
        elif code < 0x0250:
            lat += 1
    return cyr, lat, total

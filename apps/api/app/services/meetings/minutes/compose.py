"""Bayonnoma mazmuni -> formatdan mustaqil hujjat bloklari (raqamlash, sarlavhalar, bo'sh joylar - KOD).

SHARTNOMA:

    @dataclass
    class MinutesDoc:
        lang: str            # hujjat tili (`text.LANGS`)
        title: str           # fayl/xususiyat sarlavhasi (yig'ilish nomi)
        text_lang: str       # `text.WORD_LANGS[lang]`
        blocks: list[dict]   # pastdagi turlar

    def compose(content: dict, *, lang: str, title: str, speakers: dict[str, dict], recorded_at: float,
                now: float, revision: int = 0) -> MinutesDoc
    def numbering(content: dict) -> list[Numbered]          # band raqamlari - `compose` AYNAN shuni chop etadi
    def sections_of(content: dict) -> list[dict]            # bo'limlar (`Numbered.section` - shu ro'yxatda, 1-based)
    def items_of(section: dict) -> list                     # bo'lim bandlari (`Numbered.index` - shu ro'yxatda)
    def outline(content: dict, *, lang: str, speakers: dict[str, dict] | None) -> str   # tahrir uchun NUMBERING
    def file_title(title, *, lang: str, revision: int = 0) -> str                       # fayl nomi sarlavhasi

BLOK TURLARI (`kind`):
    approval  {lines: [str]}                        tasdiq bloki, o'ng tomonda: label approve, BLANK (bank),
                                                    BLANK (lavozim), BLANK (F.Familiya), approve_date, number
    title     {lines: [str]}                        markazda, qalin: BLANK (bank nomi), meeting_line, doc
    two_col   {left: str, right: str}               sana (chapda, `text.format_date`) va shahar (o'ngda, label city)
    label     {label: str, value: str}              "Раислик қилувчи:" + BLANK; "Қатнашдилар:" + BLANK
    heading   {text: str}                           markazda, qalin: "КУН ТАРТИБИ:", "ҚАРОР ҚИЛАДИ:"
    agenda    {number: "1.", text: str}             kun tartibi bandi - markazda, qalin
    italic    {text: str}                           so'zga chiqqanlar qatori (faqat ismlar bo'lsa)
    para      {runs: [(str, {bold, italic})], indent: bool}   bayon paragrafi, justify, 1-qator chekinishi
    section   {text: str}                           "I. ... бўйича:" - to'q ko'k (#1F3864), tagi chizilgan, qalin
    item      {number: "12.", runs: [...], sub: [str], follow: str|null}   band: raqam qalin, muddat qalin,
                                                    mas'ul(lar) qalin, matn; kichik bandlar "- "; "Бунда, ..."
    muted     {text: str}                           kulrang izoh (loyiha eslatmasi, aniqlashtirish ro'yxati)
    spacer    {}

SARLAVHA QISMI (`content["header"]`, faqat ega aytgani - `validate`): tashkilot - tasdiq bloki va sarlavhaning
birinchi qatori, `chairedBy` - meeting_line dagi BLANK o'rniga, shahar - city qatoridagi BLANK o'rniga, rais va
qatnashchilar - yorliq qiymati. Aytilmagani (yoki minutes-2 hujjatida `header` umuman yo'q) - `BLANK`, bloklar
avvalgidek baytma-bayt. `revision` (0 - asl) >= 1 bo'lsa loyiha qatorida "2-таҳрир." kabi versiya belgisi.

QOIDALAR: bandlar BARCHA bo'limlar bo'ylab 1..N uzluksiz (`numbering`); har bo'lim `section` = label section
(`roman`, kun tartibi sarlavhasi); `[S#]` tokenlari (bayon, matn, kichik band, "Бунда", preamble)
`export.render_tokens` dek ismga, ism yo'q spiker - `BLANK`; `kind == "task"` va `responsible` bo'sh -> matn
boshida (muddatdan keyin) `BLANK`; `preamble` bo'lmasa label preamble; so'nggi band - nazorat: label control
(`who` = controller yoki BLANK); oxirida `approvers` + BLANK qatori va `muted` loyiha eslatmasi; `notes` bo'lsa
`muted` "Aniqlashtirish kerak:" ro'yxati (`render_notes`: ism yo'q spiker - "3-иштирокчи", BLANK emas).
Matn `export.clean`/`one_line` orqali (DOCX XML buzilmasin).

NEGA TOKENLAR `export.render_tokens` BILAN EMAS. U ism yo'q spikerni "1-ishtirokchi" / "Участник 1" deb
yozadi - xulosa uchun to'g'ri, lekin rasmiy hujjatda "1-ishtirokchi ҳисобот тайёрласин" bo'lmaydi: mas'ul
o'rni `BLANK` bo'lib, kotib to'ldiradi (ega qarori). Birlashtirilgan spikerlar (`merged_into`) esa xuddi
eksportdagidek `export.resolve_speaker` orqali kuzatiladi.

NEGA ISMLAR QALIN QILINADI (oddiy qidiruv). Namunada mas'ul "(И.Фамилия)" qalin. Model ismni matn ichida
yozadi (qo'shimchasi bilan ham: "Азизга"); `responsible` dagi har ismning matndagi HAR uchrashuvi qalin
run bo'ladi - o'zak qalin, qo'shimcha oddiy. Bu bezak, mazmun emas: topilmasa matn o'zgarmaydi.

NEGA `now` LOYIHA QATORIDA. Tasdiq sanasi bo'sh (hujjat tizimi qo'yadi); hujjat QACHON yozilgani esa
loyihani ajratish uchun kerak - "ЛОЙИҲА ... Barno AI, 2026 йил 4 ноябрь".
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Any, Iterable

from .. import export
from . import text
from .text import BLANK

#: Matn ichidagi spiker tokeni `[S1]`; `responsible`/`controller`/`speakers` da qavssiz "S1" ham bo'ladi.
_TOKEN = re.compile(r"\[(S\d{1,2})\]")
_BARE_TOKEN = re.compile(r"^\[?\s*(S\d{1,2})\s*\]?$")
#: Promptdagi qolipning o'zi ("[S#]") - model ba'zan aniq token o'rniga yozadi: matnda `BLANK`, izohda "иштирокчи".
_PLACEHOLDER = re.compile(r"\[\s*S\s*#\s*\]")
_BLANKISH = re.compile(r"^[_\s]{3,}$")
#: Kun tartibi sarlavhasi va muddat oxiridagi tinish belgilari - qolipga ("... бўйича:") qo'shilganda ikkilanmasin.
_TAIL = re.compile(r"[\s.;:,]+$")
#: Kichik band boshidagi belgi - `compose` o'zi "- " qo'yadi, ikki marta bo'lmasin (xom mazmun uchun).
_BULLET = re.compile(r"^(?:[-–—•*]|\d{1,2}[.)])\s*")
_PARAGRAPHS = re.compile(r"\n\s*\n")
#: Kotibga ma'noli ogohlantirishlar (`validate`): to'qima ism, tasdiqlanmagan raqam, yozuv mosligi.
#: Qolganlari texnik (`agenda_dropped`, `provider_failed:...`) - hujjatga chiqmaydi.
HUMAN_WARNINGS = ("ungrounded_name:", "unverified_number:", "script_mismatch", "header_dropped:")
#: Tahrir promptidagi `NUMBERING` qatorida band matnining eng ko'p uzunligi (belgi).
OUTLINE_TEXT = 160

Run = tuple[str, dict[str, bool]]


@dataclass
class MinutesDoc:
    lang: str
    title: str
    text_lang: str = "uz-Cyrl-UZ"
    blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Numbered:
    """Hujjatdagi bitta raqamlangan band (`numbering`)."""

    number: int        # chop etilgan band raqami (bo'limlar bo'ylab uzluksiz)
    section: int       # 1-based bo'lim (rim raqami `text.roman(section)`); 0 - kod qo'shgan nazorat bandi
    index: int         # sections[section-1].items ichidagi indeks; -1 - nazorat bandi
    control: bool = False


class _Names:
    """Spiker tokenlari -> ism. Ism yo'q (yoki noma'lum) spiker -> `BLANK`; `merged_into` kuzatiladi."""

    def __init__(self, speakers: dict[str, dict[str, Any]] | None) -> None:
        self.speakers = speakers or {}

    def name(self, sid: str | None) -> str | None:
        sid = export.resolve_speaker(sid, self.speakers)
        if not sid:
            return None
        return export.one_line((self.speakers.get(sid) or {}).get("name")) or None

    def render(self, value: Any) -> str:
        """Matn ichidagi `[S#]` tokenlari ismga (yo'q bo'lsa `BLANK`), bir qatorli tozalangan matn."""
        rendered = _TOKEN.sub(lambda m: self.name(m.group(1)) or BLANK, str(value or ""))
        return export.one_line(_PLACEHOLDER.sub(BLANK, rendered))

    def note(self, value: Any, lang: str) -> str:
        """Izohdagi `[S#]` -> ism, yo'q bo'lsa "3-иштирокчи": izoh kotib uchun - `BLANK` kim haqida gap
        ketayotganini yashirardi, raqam esa transkriptdagi spiker raqami bilan bir xil."""
        def swap(found: re.Match[str]) -> str:
            sid = export.resolve_speaker(found.group(1), self.speakers) or found.group(1)
            return self.name(sid) or text.label("speaker", lang).format(n=re.sub(r"\D", "", sid))
        rendered = _TOKEN.sub(swap, str(value or ""))
        return export.one_line(_PLACEHOLDER.sub(text.label("speaker_any", lang), rendered))

    def person(self, value: Any) -> str | None:
        """Bitta shaxs maydoni (`controller`, `responsible[i]`, `speakers[i]`): token - ism yoki `None`
        (ism yo'q spiker); bo'sh joy - `None`; aks holda asosli ism (`validate` tekshirgan)."""
        raw = export.one_line(value)
        if not raw or _BLANKISH.match(raw):
            return None
        found = _BARE_TOKEN.match(raw)
        if found:
            return self.name(found.group(1))
        return self.render(raw)

    def people(self, values: Iterable[Any]) -> list[str]:
        out: list[str] = []
        for value in values:
            who = self.person(value)
            if who and who != BLANK and who not in out:
                out.append(who)
        return out


def _paragraphs(report: Any) -> list[str]:
    """Bayon matni -> paragraflar (bo'sh qator bilan ajratilgan); `validate` dan keyin odatda bitta."""
    return [part for part in (export.one_line(p) for p in _PARAGRAPHS.split(export.clean(report))) if part]


def _mark(body: str, targets: list[str]) -> list[Run]:
    """Matnni run'larga bo'ladi: `targets` (mas'ul ismlar) uchrashgan joylar qalin, qolgani oddiy."""
    unique = [t for t in dict.fromkeys(targets) if t]
    if not body:
        return []
    if not unique:
        return [(body, {})]
    pattern = re.compile("|".join(re.escape(t) for t in sorted(unique, key=len, reverse=True)))
    runs: list[Run] = []
    pos = 0
    for found in pattern.finditer(body):
        if found.start() > pos:
            runs.append((body[pos:found.start()], {}))
        runs.append((found.group(0), {"bold": True}))
        pos = found.end()
    if pos < len(body):
        runs.append((body[pos:], {}))
    return runs


def _subpoint(value: Any) -> str:
    point = _BULLET.sub("", export.one_line(value))
    return f"- {point}" if point else ""


def _item(item: dict[str, Any], number: int, names: _Names) -> dict[str, Any]:
    """Band bloki: raqam (qalin), muddat (qalin), [BLANK (qalin)], matn (mas'ullar qalin)."""
    kind = str(item.get("kind") or "other").strip().lower()
    deadline = _TAIL.sub("", export.one_line(item.get("deadline")))
    body = names.render(item.get("text"))
    raw_responsible = item.get("responsible")
    if isinstance(raw_responsible, str):
        raw_responsible = [raw_responsible]
    responsible: list[str] = []
    for entry in raw_responsible if isinstance(raw_responsible, list) else []:
        who = names.person(entry)
        if who is None and _BARE_TOKEN.match(export.one_line(entry) or ""):
            who = BLANK                                      # ism yo'q spiker - mas'ul o'rni bo'sh
        if who and who not in responsible:
            responsible.append(who)
    runs: list[Run] = [(f"{number}. ", {"bold": True})]
    if deadline:
        runs.append((f"{deadline} ", {"bold": True}))
    if kind == "task" and not responsible and BLANK not in body:
        # Mas'ul aytilmagan vazifa: kotib to'ldiradigan joy - muddatdan keyin, matndan oldin.
        runs.append((f"{BLANK} ", {"bold": True}))
    runs += _mark(body, responsible)
    subpoints = item.get("subpoints") if isinstance(item.get("subpoints"), list) else []
    sub = [s for s in (_subpoint(names.render(x)) for x in subpoints) if s]
    follow = names.render(item.get("followUp")) or None
    return {"kind": "item", "number": f"{number}.", "runs": runs, "sub": sub, "follow": follow}


def _control(number: int, who: str, lang: str) -> dict[str, Any]:
    """Nazorat bandi - label control qolipi; `who` qalin."""
    head, _, tail = text.label("control", lang).partition("{who}")
    runs: list[Run] = [(f"{number}. ", {"bold": True})]
    if head:
        runs.append((head, {}))
    runs.append((who, {"bold": True}))
    if tail:
        runs.append((tail, {}))
    return {"kind": "item", "number": f"{number}.", "runs": runs, "sub": [], "follow": None}


def sections_of(content: dict[str, Any]) -> list[dict[str, Any]]:
    """Hujjatdagi bo'limlar (obyekt bo'lmagani tashlanadi) - rim raqami shu ro'yxatdagi o'rni (1-based)."""
    return [s for s in (content.get("sections") or []) if isinstance(s, dict)]


def items_of(section: dict[str, Any]) -> list[Any]:
    """Bo'lim bandlari (xom ro'yxat: `Numbered.index` shu ro'yxatdagi o'rin)."""
    return section.get("items") if isinstance(section.get("items"), list) else []


def numbering(content: dict[str, Any]) -> list[Numbered]:
    """Bandlarning chop etiladigan raqamlari - `compose` AYNAN shu ro'yxat bilan raqamlaydi: Word dagi raqamlar va
    tahrir promptidagi `NUMBERING` (`outline`) hech qachon ajralmaydi. Matnsiz band raqam olmaydi; mazmunda
    `control` turidagi band bo'lmasa, oxiriga kod qo'shadigan nazorat bandi (`control=True`) kiradi."""
    out: list[Numbered] = []
    has_control = False
    for section_no, section in enumerate(sections_of(content), 1):
        for index, item in enumerate(items_of(section)):
            if not isinstance(item, dict) or not export.one_line(item.get("text")):
                continue
            out.append(Numbered(len(out) + 1, section_no, index))
            if str(item.get("kind") or "").strip().lower() == "control":
                has_control = True
    if not has_control:
        out.append(Numbered(len(out) + 1, 0, -1, control=True))
    return out


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit - 1] + "…"


def outline(content: dict[str, Any], *, lang: str, speakers: dict[str, dict[str, Any]] | None) -> str:
    """Tahrir promptining `NUMBERING` bloki: hujjat egasiga Word da qanday ko'rinsa - kun tartibi raqamlari, rim
    raqamli bo'limlar va uzluksiz band raqamlari (`numbering`) - mazmun kalitlariga bog'lab. Ega "5-band",
    "2-masala", "III bo'lim" desa, model qaysi kalitni o'zgartirishni shundan biladi. Matnlarda `[S#]` o'rniga ism
    (Word dagidek); nazorat bandi - kod `controller` dan yozadigan gap, hujjat tilida."""
    code = text.normalize(lang) or "uz-cyrl"
    names = _Names(speakers)
    agenda = [a for a in (content.get("agenda") or []) if isinstance(a, dict)]
    numbers = numbering(content)
    lines = [f"Agenda {n} = agenda[{n - 1}]: «{_clip(names.render(entry.get('title')) or BLANK, OUTLINE_TEXT)}»"
             for n, entry in enumerate(agenda, 1)]
    for section_no, section in enumerate(sections_of(content), 1):
        own = [n for n in numbers if n.section == section_no]
        if not own:
            span = "no items"
        elif len(own) == 1:
            span = f"item {own[0].number}"
        else:
            span = f"items {own[0].number}-{own[-1].number}"
        lines.append(f"Section {text.roman(section_no)} = sections[{section_no - 1}] "
                     f"(agendaIndex {section.get('agendaIndex')}): {span}")
        items = items_of(section)
        for n in own:
            item = items[n.index]
            kind = str(item.get("kind") or "other").strip().lower()
            lines.append(f"  Item {n.number} = sections[{section_no - 1}].items[{n.index}] ({kind}): "
                         f"«{_clip(names.render(item.get('text')), OUTLINE_TEXT)}»")
    control = next((n for n in numbers if n.control), None)
    if control is not None:
        who = names.person(content.get("controller")) or BLANK
        lines.append(f"Item {control.number} = the control item added by code from \"controller\": "
                     f"«{text.label('control', code).format(who=who)}» - to change it, change \"controller\".")
    return "\n".join(lines)


def file_title(title: Any, *, lang: str, revision: int = 0) -> str:
    """Eksport fayli nomining sarlavhasi: "Баённома - <yig'ilish nomi>"; tahrirda versiya bilan -
    "Баённома - Haftalik (2-таҳрир)" (`text.label("version")`)."""
    code = text.normalize(lang) or "uz-cyrl"
    name = f"{text.label('doc_word', code)} - {export.one_line(title)}".strip(" -")
    if int(revision or 0) > 0:
        name = f"{name} ({text.label('version', code).format(n=int(revision) + 1)})"
    return name


def render_notes(content: dict[str, Any], *, speakers: dict[str, dict[str, Any]] | None, lang: str) -> list[str]:
    """Model izohlari (`notes`) - hujjatdagi "Аниқлаштириш керак" ro'yxati va bot xabari uchun BIR XIL."""
    names = _Names(speakers)
    code = text.normalize(lang) or "uz-cyrl"
    return [n for n in (names.note(x, code) for x in (content.get("notes") or [])) if n]


def _fill(template: str, value: str) -> str:
    """Yorliqdagi birinchi `BLANK` o'rniga ega aytgan qiymat; qiymat bo'lmasa yorliq o'zgarmaydi."""
    return template.replace(BLANK, value, 1) if value else template


def compose(content: dict[str, Any], *, lang: str, title: str, speakers: dict[str, dict[str, Any]],
            recorded_at: float, now: float, revision: int = 0) -> MinutesDoc:
    code = text.normalize(lang) or "uz-cyrl"
    names = _Names(speakers)

    def label(key: str) -> str:
        return text.label(key, code)

    header = content.get("header") if isinstance(content.get("header"), dict) else {}

    def fact(key: str) -> str:
        """Sarlavha qismidagi ega aytgan qiymat (`[S#]` - ism) yoki bo'sh satr."""
        value = header.get(key)
        return names.render(value) if isinstance(value, str) else ""

    people = header.get("attendees") if isinstance(header.get("attendees"), list) else []
    attendees = ", ".join(x for x in (names.render(a) for a in people if isinstance(a, str)) if x)
    organization = fact("organization") or BLANK
    meeting_line = _fill(label("meeting_line"), fact("chairedBy"))
    agenda = [a for a in (content.get("agenda") or []) if isinstance(a, dict)]
    sections = sections_of(content)
    blocks: list[dict[str, Any]] = [
        {"kind": "approval", "lines": [label("approve"), organization, BLANK, BLANK, label("approve_date"),
                                       label("number")]},
        {"kind": "spacer"},
        # O'zbekcha - bosh so'z oxirida ("... ҳузурида ўтказилган йиғилиш / Б А Ё Н И"); rus va ingliz
        # tilida hujjat so'zi OLDIN, qaratqich/"of" qatori keyin ("ПРОТОКОЛ / совещания под ...").
        {"kind": "title", "doc": label("doc"),
         "lines": ([organization, label("doc"), meeting_line] if code in ("ru", "en")
                   else [organization, meeting_line, label("doc")])},
        {"kind": "two_col", "left": text.format_date(recorded_at, code) if recorded_at else BLANK,
         "right": _fill(label("city"), fact("city"))},
        {"kind": "label", "label": label("chair"), "value": fact("chair") or BLANK},
        {"kind": "label", "label": label("attendees"), "value": attendees or BLANK},
    ]

    # Kun tartibi: bandlar ro'yxati, so'zga chiqqanlar (faqat haqiqiy ismlar), har band bayoni.
    if agenda:
        blocks.append({"kind": "heading", "text": label("agenda")})
        for n, entry in enumerate(agenda, 1):
            blocks.append({"kind": "agenda", "number": f"{n}.", "text": export.one_line(entry.get("title")) or BLANK})
        spoke = names.people(who for entry in agenda for who in (entry.get("speakers") or [])
                             if isinstance(entry.get("speakers"), list))
        if spoke:
            blocks.append({"kind": "italic", "text": f"{label('speakers')} {', '.join(spoke)}"})
        for entry in agenda:
            for paragraph in _paragraphs(entry.get("report")):
                blocks.append({"kind": "para", "runs": [(names.render(paragraph), {})], "indent": True})

    blocks.append({"kind": "para", "runs": [(names.render(content.get("preamble")) or label("preamble"), {})],
                   "indent": True})
    blocks.append({"kind": "heading", "text": label("decides")})

    # Qarorlar: rim raqamli bo'limlar, bandlar BARCHA bo'limlar bo'ylab uzluksiz raqamlanadi (`numbering` - tahrir
    # promptidagi raqamlar bilan bir xil).
    numbers = numbering(content)
    placed = {(n.section, n.index): n.number for n in numbers if not n.control}
    for section_no, section in enumerate(sections, 1):
        agenda_index = section.get("agendaIndex")
        agenda_title = ""
        if isinstance(agenda_index, int) and not isinstance(agenda_index, bool) and 1 <= agenda_index <= len(agenda):
            agenda_title = export.one_line(agenda[agenda_index - 1].get("title"))
        # Kun tartibi sarlavhasi "... тўғрисида" bilan tugaydi - bo'lim qolipi "... бўйича:" uni takrorlamasin.
        blocks.append({"kind": "section", "text": label("section").format(
            roman=text.roman(section_no), title=text.section_title(agenda_title, code) or BLANK)})
        for index, item in enumerate(items_of(section)):
            number = placed.get((section_no, index))
            if number is not None:
                blocks.append(_item(item, number, names))
    control = next((n for n in numbers if n.control), None)
    if control is not None:
        blocks.append(_control(control.number, names.person(content.get("controller")) or BLANK, code))

    blocks.append({"kind": "spacer"})
    blocks.append({"kind": "label", "label": label("approvers"), "value": BLANK})

    # Aniqlashtirish ro'yxati: model izohlari + tekshiruv ogohlantirishlari soni (kulrang, loyiha uchun).
    notes = render_notes(content, speakers=speakers, lang=code)
    quality = content.get("quality") if isinstance(content.get("quality"), dict) else {}
    warnings = [str(w) for w in (quality.get("warnings") or []) if str(w).startswith(HUMAN_WARNINGS)]
    if notes or warnings:
        lines = [label("notes")] + [f"- {note}" for note in notes]
        if warnings:
            lines.append(label("warnings").format(n=len(warnings)))
        blocks.append({"kind": "muted", "text": "\n".join(lines)})
    draft = label("draft")
    if int(revision or 0) > 0:
        draft = f"{draft} {label('version').format(n=int(revision) + 1)}."
    if now:
        draft = f"{draft} {export.BRAND}, {text.format_date(now, code)}."
    blocks.append({"kind": "muted", "text": draft})

    doc_title = export.one_line(title) or export.one_line(content.get("title")) or label("doc_word")
    return MinutesDoc(lang=code, title=doc_title, text_lang=text.WORD_LANGS[code], blocks=blocks)

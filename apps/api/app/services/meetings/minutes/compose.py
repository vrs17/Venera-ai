"""Bayonnoma mazmuni -> formatdan mustaqil hujjat bloklari (raqamlash, sarlavhalar, bo'sh joylar - KOD).

SHARTNOMA:

    @dataclass
    class MinutesDoc:
        lang: str            # hujjat tili (`text.LANGS`)
        title: str           # fayl/xususiyat sarlavhasi (yig'ilish nomi)
        text_lang: str       # `text.WORD_LANGS[lang]`
        blocks: list[dict]   # pastdagi turlar

    def compose(content: dict, *, lang: str, title: str, speakers: dict[str, dict], recorded_at: float,
                now: float) -> MinutesDoc

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

QOIDALAR: bandlar BARCHA bo'limlar bo'ylab 1..N uzluksiz; har bo'lim `section` = label section
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
HUMAN_WARNINGS = ("ungrounded_name:", "unverified_number:", "script_mismatch")

Run = tuple[str, dict[str, bool]]


@dataclass
class MinutesDoc:
    lang: str
    title: str
    text_lang: str = "uz-Cyrl-UZ"
    blocks: list[dict[str, Any]] = field(default_factory=list)


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


def render_notes(content: dict[str, Any], *, speakers: dict[str, dict[str, Any]] | None, lang: str) -> list[str]:
    """Model izohlari (`notes`) - hujjatdagi "Аниқлаштириш керак" ro'yxati va bot xabari uchun BIR XIL."""
    names = _Names(speakers)
    code = text.normalize(lang) or "uz-cyrl"
    return [n for n in (names.note(x, code) for x in (content.get("notes") or [])) if n]


def compose(content: dict[str, Any], *, lang: str, title: str, speakers: dict[str, dict[str, Any]],
            recorded_at: float, now: float) -> MinutesDoc:
    code = text.normalize(lang) or "uz-cyrl"
    names = _Names(speakers)

    def label(key: str) -> str:
        return text.label(key, code)

    agenda = [a for a in (content.get("agenda") or []) if isinstance(a, dict)]
    sections = [s for s in (content.get("sections") or []) if isinstance(s, dict)]
    blocks: list[dict[str, Any]] = [
        {"kind": "approval", "lines": [label("approve"), BLANK, BLANK, BLANK, label("approve_date"), label("number")]},
        {"kind": "spacer"},
        # O'zbekcha - bosh so'z oxirida ("... ҳузурида ўтказилган йиғилиш / Б А Ё Н И"); rus va ingliz
        # tilida hujjat so'zi OLDIN, qaratqich/"of" qatori keyin ("ПРОТОКОЛ / совещания под ...").
        {"kind": "title", "doc": label("doc"),
         "lines": ([BLANK, label("doc"), label("meeting_line")] if code in ("ru", "en")
                   else [BLANK, label("meeting_line"), label("doc")])},
        {"kind": "two_col", "left": text.format_date(recorded_at, code) if recorded_at else BLANK,
         "right": label("city")},
        {"kind": "label", "label": label("chair"), "value": BLANK},
        {"kind": "label", "label": label("attendees"), "value": BLANK},
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

    # Qarorlar: rim raqamli bo'limlar, bandlar BARCHA bo'limlar bo'ylab uzluksiz raqamlanadi.
    number = 0
    has_control = False
    for index, section in enumerate(sections, 1):
        agenda_index = section.get("agendaIndex")
        agenda_title = ""
        if isinstance(agenda_index, int) and not isinstance(agenda_index, bool) and 1 <= agenda_index <= len(agenda):
            agenda_title = export.one_line(agenda[agenda_index - 1].get("title"))
        # Kun tartibi sarlavhasi "... тўғрисида" bilan tugaydi - bo'lim qolipi "... бўйича:" uni takrorlamasin.
        blocks.append({"kind": "section", "text": label("section").format(
            roman=text.roman(index), title=text.section_title(agenda_title, code) or BLANK)})
        for item in section.get("items") if isinstance(section.get("items"), list) else []:
            if not isinstance(item, dict) or not export.one_line(item.get("text")):
                continue
            number += 1
            blocks.append(_item(item, number, names))
            if str(item.get("kind") or "").strip().lower() == "control":
                has_control = True
    if not has_control:
        number += 1
        blocks.append(_control(number, names.person(content.get("controller")) or BLANK, code))

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
    if now:
        draft = f"{draft} {export.BRAND}, {text.format_date(now, code)}."
    blocks.append({"kind": "muted", "text": draft})

    doc_title = export.one_line(title) or export.one_line(content.get("title")) or label("doc_word")
    return MinutesDoc(lang=code, title=doc_title, text_lang=text.WORD_LANGS[code], blocks=blocks)

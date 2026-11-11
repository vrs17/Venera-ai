"""Slack ko'rinishi: matn bo'laklari, Block Kit bloklari, Markdown -> mrkdwn.

Faqat ko'rinish - xizmatga murojaat yo'q (ma'lumotni `meeting.py` beradi). Slack
cheklovlari: section matni 3000 belgigacha, xabarda 50 tagacha blok, mrkdwn'da `&`, `<`,
`>` maxsus belgilar (havola, eslatma) - odam yoki model yozgan matn doim `escape` dan o'tadi.
"""

from __future__ import annotations

import re

from typing import Any

from ..services.meetings import export
from ..services.meetings.minutes import text as minutes_text

#: Bitta section matni (Slack: 3000) - zaxira bilan.
SECTION_CHARS = 2900
#: Bitta xabardagi bloklar (Slack: 50) - tugma va kontekst bloklariga joy qolsin.
MESSAGE_BLOCKS = 45
#: Yig'ilish belgisi (`block_id`): thread'dagi savol va tugmalar yig'ilishni shundan topadi.
MARK = "barno:"
#: Qayta o'girish tillari (`schemas.meetings.Lang`).
LANG_NAMES = {"uz": "o'zbek", "ru": "rus", "en": "ingliz"}
#: Eksport menyusi: qiymat -> nom. Transkript TXT - alohida tugmada (`TRANSCRIPT_BUTTON`, 2026-11-11); eski
#: kartalardagi `transcript_txt` tanlovi ham o'sha yo'ldan (`meeting.transcript_file`).
EXPORTS = (("transcript_srt", "Transkript (SRT)"), ("summary_md", "Xulosa (MD)"),
           ("report_docx", "Hisobot (Word)"), ("report_pdf", "Hisobot (PDF)"))
#: Transkript chatga YOZILMAYDI (ega talabi 2026-11-11: uzun matn chatni tushunarsiz qiladi) - kartadagi
#: tugma uni .txt fayl qilib kartaning thread'iga yuboradi, Slack'da shu yerdan yuklab olinadi.
TRANSCRIPT_BUTTON = "📥 Transkriptni yuklab olish"
#: Tugmani bosgan odamga (faqat unga ko'rinadi): fayl qayerda.
TRANSCRIPT_SENT = "📥 Transkript fayli shu xulosa ostidagi thread'ga yuklandi - thread'ni ochib, faylni yuklab oling."

_ID = re.compile(r"[0-9a-f]{32}")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*]\s+")


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unescape(text: str) -> str:
    """Slack'dan kelgan matn (savol) - `&lt;` kabi belgilarsiz."""
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def split(text: str, limit: int = SECTION_CHARS) -> list[str]:
    """Qatorlar chegarasida `limit` belgigacha bo'laklar; juda uzun qator kesiladi."""
    parts: list[str] = []
    current = ""
    for line in text.splitlines():
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if current and len(current) + 1 + len(line) > limit:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts or [text]


def mrkdwn(md: str) -> str:
    """Markdown (eksport, javob) -> Slack mrkdwn: `**x**` -> `*x*`, sarlavha qalin qatorga,
    ro'yxat `•` ga, jadval qatori ` · ` bilan (Slack jadvalni chizmaydi)."""
    lines = []
    for raw in escape(md).splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
                continue
            line = " · ".join(cell for cell in cells if cell)
        heading = _HEADING.match(line)
        if heading:
            line = f"*{heading.group(1).replace('*', '').strip()}*"
        line = _BULLET.sub(lambda m: f"{m.group(1)}• ", line)
        lines.append(_BOLD.sub(r"*\1*", line))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def sections(text: str, *, plain: bool = False) -> list[dict[str, Any]]:
    """Matn -> section bloklari. `plain` - transkript: belgilar talqin qilinmaydi."""
    kind = "plain_text" if plain else "mrkdwn"
    return [{"type": "section", "text": {"type": kind, "text": part}} for part in split(text) if part.strip()]


def context(text: str, *, block_id: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}
    if block_id:
        block["block_id"] = block_id
    return block


def mark(meeting_id: str, tag: str = "") -> str:
    """Yig'ilish belgisi. Bitta xabarda `block_id` takrorlanmasligi kerak - `tag`."""
    return f"{MARK}{meeting_id}:{tag}" if tag else f"{MARK}{meeting_id}"


def marked(message: dict[str, Any] | None) -> str | None:
    """Xabar bloklaridagi yig'ilish id'si (`mark`) yoki `None`."""
    for block in (message or {}).get("blocks") or []:
        block_id = str(block.get("block_id") or "")
        if block_id.startswith(MARK):
            meeting_id = block_id[len(MARK):].split(":", 1)[0]
            if _ID.fullmatch(meeting_id):
                return meeting_id
    return None


def option(text: str, value: str) -> dict[str, Any]:
    return {"text": {"type": "plain_text", "text": text[:75]}, "value": value}


def button(text: str, action_id: str, value: str, *, confirm: dict[str, Any] | None = None) -> dict[str, Any]:
    element: dict[str, Any] = {"type": "button", "action_id": action_id,
                               "text": {"type": "plain_text", "text": text[:75]}, "value": value}
    if confirm:
        element["confirm"] = confirm
    return element


def controls(meeting_id: str, language: str, templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Xulosa ostidagi tugmalar va savol haqida eslatma. Qiymatlarda yig'ilish id'si bor."""
    elements = [
        # Birinchi: transkript endi chatda yo'q - uni olishning yagona yo'li shu tugma.
        button(TRANSCRIPT_BUTTON, "barno_transcript", meeting_id),
        button("Vazifalar", "barno_tasks", meeting_id),
        # Rasmiy hujjat: til menyusi alohida xabarda (`minutes_menu`) - tugma faqat uni chaqiradi.
        button("📄 Bayonnoma", "barno_minutes", meeting_id),
        {"type": "static_select", "action_id": "barno_template",
         "placeholder": {"type": "plain_text", "text": "Boshqa shablon bilan xulosa"},
         "options": [option(t["title"], f"{meeting_id}|{t['id']}") for t in templates if t["id"] != "auto"]},
        {"type": "static_select", "action_id": "barno_export",
         "placeholder": {"type": "plain_text", "text": "Eksport"},
         "options": [option(title, f"{meeting_id}|{kind}") for kind, title in EXPORTS]},
    ]
    for lang, name in LANG_NAMES.items():
        if lang == language:
            continue
        # Tasdiq oynasi: qayta o'girish GAPI daqiqalarini yana sarflaydi va eski
        # transkript hamda xulosani almashtiradi (`service.retranscribe`).
        elements.append(button(f"{name.capitalize()} tilida qayta o'girish", f"barno_relang_{lang}",
                               f"{meeting_id}|{lang}", confirm={
                                   "title": {"type": "plain_text", "text": "Qayta o'girish"},
                                   "text": {"type": "mrkdwn", "text": (
                                       f"Audio {name} tilida qaytadan o'giriladi: GAPI daqiqalari yana "
                                       "sarflanadi, eski transkript va xulosa almashtiriladi.")},
                                   "confirm": {"type": "plain_text", "text": "O'girish"},
                                   "deny": {"type": "plain_text", "text": "Bekor qilish"}}))
    return [{"type": "actions", "block_id": mark(meeting_id), "elements": elements},
            context("Savol bo'lsa, shu xabarga thread'da yozing.")]


def retry_button(value: str) -> dict[str, Any]:
    return {"type": "actions", "elements": [button("Qayta urinish", "barno_retry", value)]}


#: Bayonnoma til menyusi xabarining matni (bildirishnoma uchun ham).
MINUTES_PROMPT = "📄 *Bayonnoma* - hujjat tilini tanlang:"


def minutes_menu(meeting_id: str, default: str) -> list[dict[str, Any]]:
    """Bayonnoma tili tugmalari (`minutes.text.LANGS`): tavsiya etilgani (yig'ilish tilidan
    `default_lang`) BIRINCHI va `primary` - bank hujjati odatda kirillda, lekin tanlov odamniki.
    Qiymat `yig'ilish|til`; `block_id` yig'ilish belgisini olib yuradi (`mark`)."""
    order = [default] + [lang for lang in minutes_text.LANGS if lang != default]
    buttons = []
    for lang in order:
        # Har tugmaning O'Z `action_id` si (`barno_minutes_lang_<til>`): Slack bitta `actions` blokida
        # takror id ni `invalid_blocks` bilan rad etadi (`barno_relang_<til>` kabi).
        element = button(minutes_text.LANG_TITLES[lang], f"barno_minutes_lang_{lang}", f"{meeting_id}|{lang}")
        if lang == default:
            element["style"] = "primary"
        buttons.append(element)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": MINUTES_PROMPT}},
            {"type": "actions", "block_id": mark(meeting_id, "minutes"), "elements": buttons}]


def minutes_result(view: dict[str, Any], lang: str) -> str:
    """Tayyor bayonnoma haqida xabar: bo'lim/band soni, loyiha eslatmasi, modelning izohlari
    (aniqlashtirish kerak) va sifat ogohlantirishlari - `ungrounded_name:<ism>` (transkriptda
    bo'lmagan ism `BLANK` bo'ldi), `script_mismatch` (yozuv tanlangan tilga mos emas)."""
    title = minutes_text.LANG_TITLES.get(lang, lang)
    parts = [f"✅ *Bayonnoma tayyor* ({title}): {int(view.get('sectionCount') or 0)} bo'lim, "
             f"{int(view.get('itemCount') or 0)} band. Loyiha - Word faylidagi «{minutes_text.BLANK}» "
             "joylarini to'ldiring (bank nomi, rais, qatnashuvchilar, №, sana)."]
    notes = [escape(export.one_line(n)) for n in view.get("notes") or [] if export.one_line(n)]
    if notes:
        parts.append("*Aniqlashtirish kerak:*\n" + "\n".join(f"• {n}" for n in notes))
    warnings = [str(w) for w in view.get("warnings") or []]
    names = [escape(w.split(":", 1)[1].strip()) for w in warnings if w.startswith("ungrounded_name:")]
    if names:
        parts.append(f"Transkriptda bo'lmagan ismlar «{minutes_text.BLANK}» bilan almashtirildi: "
                     + ", ".join(dict.fromkeys(n for n in names if n)))
    if "script_mismatch" in warnings:
        parts.append("Hujjat yozuvi (kirill/lotin) tanlangan tilga to'liq mos kelmadi - matnni ko'zdan kechiring.")
    return "\n\n".join(parts)


def speakers(view_speakers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Yig'ilish ko'rinishidagi spikerlar -> `export.speaker_name` kutgan shakl."""
    return {sp["id"]: {"name": sp.get("name"), "merged_into": sp.get("mergedInto")} for sp in view_speakers}


def clock(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, rest = divmod(total, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def tasks(items: list[dict[str, Any]], people: dict[str, dict[str, Any]], lang: str) -> str:
    """Vazifalar ro'yxati: ish, mas'ul, muddat; bajarilgani `✓`, ishonchsizi belgilangan."""
    lines = []
    for item in items:
        task = export.one_line(item.get("task"))
        if not task or item.get("status") == "dismissed":
            continue
        owner = item.get("owner") or {}
        who = export.one_line(owner.get("name")) or (
            export.speaker_name(owner.get("speaker"), people, lang) if owner.get("speaker") else "")
        due = item.get("due") or {}
        when = export.one_line(due.get("raw")) or " ".join(x for x in (due.get("date"), due.get("time")) if x)
        details = [f"Mas'ul: {escape(who)}" if who else "", f"Muddat: {escape(when)}" if when else ""]
        line = ("✓ " if item.get("status") == "done" else "") + escape(task)
        if any(details):
            line += " — " + " · ".join(d for d in details if d)
        if item.get("needsConfirmation"):
            line += " _(aniqlashtirish kerak)_"
        lines.append(f"• {line}")
    return "\n".join(lines)


def answer(found: dict[str, Any], people: dict[str, dict[str, Any]], lang: str) -> str:
    """Yig'ilish bo'yicha javob: matn, manbalar (vaqt belgisi bilan) va keyingi savollar."""
    parts = [mrkdwn(export.render_tokens(found.get("answer") or "", people, lang))]
    cites = []
    for cite in (found.get("citations") or [])[:5]:
        who = export.speaker_name(cite.get("speaker"), people, lang) if cite.get("speaker") else ""
        quote = escape(export.one_line(cite.get("text"))[:200])
        cites.append(f"• `{clock(cite.get('start'))}` {escape(who) + ': ' if who else ''}«{quote}»")
    if cites:
        parts.append("*Manbalar:*\n" + "\n".join(cites))
    follow = [f"• {escape(export.one_line(q))}" for q in (found.get("followUps") or [])[:3] if q]
    if follow:
        parts.append("*Yana so'rash mumkin:*\n" + "\n".join(follow))
    return "\n\n".join(p for p in parts if p)

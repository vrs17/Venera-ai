"""Slack ko'rinishi: matn bo'laklari, Block Kit bloklari, Markdown -> mrkdwn.

Faqat ko'rinish - xizmatga murojaat yo'q (ma'lumotni `meeting.py` beradi). Slack
cheklovlari: section matni 3000 belgigacha, xabarda 50 tagacha blok, mrkdwn'da `&`, `<`,
`>` maxsus belgilar (havola, eslatma) - odam yoki model yozgan matn doim `escape` dan o'tadi.
"""

from __future__ import annotations

import re

from typing import Any

from ..services.meetings import export
from ..services.meetings.minutes import diff as minutes_diff
from ..services.meetings.minutes import text as minutes_text

#: Bitta section matni (Slack: 3000) - zaxira bilan.
SECTION_CHARS = 2900
#: Bitta xabardagi bloklar (Slack: 50) - tugma va kontekst bloklariga joy qolsin.
MESSAGE_BLOCKS = 45
#: Yig'ilish belgisi (`block_id`): thread'dagi savol va tugmalar yig'ilishni shundan topadi.
MARK = "barno:"
#: Bayonnoma natijasi belgisining tegi (`minutes_hint`, `doc_tag`): `doc:<til>[:<format>]` - qaysi til hujjati va
#: odam qaysi formatni tanlagan (2026-11-13 dan; eski xabarlarda formatsiz).
DOC_TAG = "doc:"
#: Bayonnoma fayli formatlari (ega qarori 2026-11-13: til tanlangandan keyin odam BITTASINI tanlaydi - ikkala faylni
#: chizib yuborish behuda) va tugmadagi nomlari.
MINUTES_FORMATS = ("docx", "pdf")
FORMAT_NAMES = {"docx": "Word", "pdf": "PDF"}
#: Audio tillari (`schemas.meetings.Lang`): yuklanganda so'raladi (`lang_question`), eski kartalarda - qayta o'girish.
LANG_NAMES = {"uz": "o'zbek", "ru": "rus", "en": "ingliz"}
LANG_FLAGS = {"uz": "🇺🇿", "ru": "🇷🇺", "en": "🇬🇧"}
#: Audio kelganda (ega talabi 2026-11-12): Barno ishni boshlashdan oldin tilni so'raydi - kartada qayta o'girish
#: tugmalari yo'q, til noto'g'ri aniqlanishi ham yo'q.
LANG_QUESTION = "🌐 Audio qaysi tilda? Tanlang - shundan keyin matnga o'giraman."
#: «📥 Yuklab olish» menyusi - transkript fayllari (TXT - kartaning thread'iga, `meeting.transcript_file`).
DOWNLOADS = (("transcript_txt", "Transkript (TXT)"), ("transcript_srt", "Transkript (SRT)"))
#: «Eksport» menyusi - xulosa va hisobot fayllari. Eski kartalardagi `transcript_srt` / `transcript_txt` tanlovlari
#: ham ishlaydi (`meeting.on_action`).
EXPORTS = (("summary_md", "Xulosa (MD)"), ("report_docx", "Hisobot (Word)"), ("report_pdf", "Hisobot (PDF)"))
#: Tugmani bosgan odamga (faqat unga ko'rinadi): fayl qayerda.
TRANSCRIPT_SENT = "📥 Transkript fayli shu xulosa ostidagi thread'ga yuklandi - thread'ni ochib, faylni yuklab oling."
#: Xulosa kartasi ostidagi eslatma (ega qarori 2026-11-13, "thread qoidasi"): yozuv haqidagi savol - o'z xabarining
#: thread'ida (`meeting.question`), bayonnoma ko'rsatmasi va o'zgartirishi ham; chatning o'ziga yozilgan xabar -
#: HR/CRM yordamchisiga (`assistant.on_text`).
CHAT_HINT = ("💬 Shu yozuv haqidagi savolni shu xabarning thread'iga yozing - Barno yozuv bo'yicha javob beradi va "
             "suhbatni eslab qoladi. 📄 Bayonnoma uchun ko'rsatma va o'zgartirishlar - bayonnoma xabari yoki faylining "
             "thread'ida. Chatning o'ziga yozilgan xabarga Barno AI yordamchisi javob beradi (HR, CRM, hujjatlar).")
#: Javob ostidagi tugma (`chat_actions`): suhbat xotirasini tozalaydi (`meeting.chat_reset`).
CHAT_RESET_BUTTON = "🔄 Yangi suhbat"
#: «🔄 Yangi suhbat» bosilgach - tugma turgan joyga (thread yoki chatning o'zi). Bayonnoma ko'rsatmalari ham
#: arxivga o'tadi, yozilgan hujjatlar qoladi (`service.chat_reset`).
CHAT_RESET_DONE = ("🔄 Yangi suhbat boshlandi - keyingi savollar oldingi savol-javoblarni va bayonnoma "
                   "ko'rsatmalarini hisobga olmaydi (tayyor bayonnomalar saqlanib qoladi).")
#: Eski kartadagi «Boshqa shablon bilan xulosa» menyusi bosilsa (funksiya o'chirilgan, ega qarori 2026-11-12).
TEMPLATE_OFF = "«Boshqa shablon bilan xulosa» hozircha o'chirilgan - xulosa avtomatik shablon bilan yoziladi."

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


def marked_tag(message: dict[str, Any] | None, *,
               tags: tuple[str, ...] | None = None) -> tuple[str, str] | None:
    """Xabar bloklaridagi yig'ilish belgisi (`mark`) -> (yig'ilish id'si, teg) yoki `None`. Teg - "" (xulosa kartasi),
    `chat` (chat javobi), `minutes` (bayonnoma til menyusi), `doc:<til>` (bayonnoma natijasi). `tags` - faqat shu
    teglisi; `None` - har qanday."""
    for block in (message or {}).get("blocks") or []:
        block_id = str(block.get("block_id") or "")
        if block_id.startswith(MARK):
            meeting_id, _, tag = block_id[len(MARK):].partition(":")
            if _ID.fullmatch(meeting_id) and (tags is None or tag in tags):
                return meeting_id, tag
    return None


def marked(message: dict[str, Any] | None, *, tags: tuple[str, ...] | None = None) -> str | None:
    """Xabar bloklaridagi yig'ilish id'si (`marked_tag` ning id qismi) yoki `None`."""
    found = marked_tag(message, tags=tags)
    return found[0] if found else None


def minutes_file_lang(file: dict[str, Any] | None) -> str | None:
    """Slack fayli Barno'ning bayonnoma fayli nomidami - "Bayonnoma - <yozuv nomi> ....docx|pdf"
    (`minutes.compose.file_title`, til bo'yicha hujjat so'zi: Баённома / Bayonnoma / Протокол / Minutes) -> hujjat
    tili; aks holda `None`. Fayl xabariga belgi qo'yib bo'lmaydi - uning thread'i natija xabaridan topiladi
    (`meeting.thread_target`)."""
    for key in ("name", "title"):
        name = str((file or {}).get(key) or "")
        if not name.lower().endswith((".docx", ".pdf")):
            continue
        for lang in minutes_text.LANGS:
            if name.startswith(f"{minutes_text.label('doc_word', lang)} - "):
                return lang
    return None


def doc_tag(lang: str, fmt: str | None = None) -> str:
    """Bayonnoma natijasi belgisining tegi: `doc:<til>` yoki - format tanlangan bo'lsa - `doc:<til>:<format>`."""
    return f"{DOC_TAG}{lang}:{fmt}" if fmt in MINUTES_FORMATS else f"{DOC_TAG}{lang}"


def doc_lang(tag: str | None) -> str | None:
    """Bayonnoma natijasi belgisining (`minutes_hint`, teg `doc:<til>[:<format>]`) hujjat tili; boshqa teg - `None`."""
    if not tag or not tag.startswith(DOC_TAG):
        return None
    return minutes_text.normalize(tag[len(DOC_TAG):].partition(":")[0])


def doc_format(tag: str | None) -> str | None:
    """Bayonnoma natijasi belgisidagi odam tanlagan format (`docx` | `pdf`); eski (formatsiz) yoki boshqa teg -
    `None`."""
    if doc_lang(tag) is None:
        return None
    fmt = str(tag)[len(DOC_TAG):].partition(":")[2]
    return fmt if fmt in MINUTES_FORMATS else None


def minutes_file_format(file: dict[str, Any] | None) -> str | None:
    """Barno'ning bayonnoma fayli (`minutes_file_lang`) formati - kengaytmasidan; boshqa fayl - `None`."""
    if minutes_file_lang(file) is None:
        return None
    for key in ("name", "title"):
        name = str((file or {}).get(key) or "").lower()
        for fmt in MINUTES_FORMATS:
            if name.endswith(f".{fmt}"):
                return fmt
    return None


def lang_question(head: str, file_id: str) -> list[dict[str, Any]]:
    """Audio qabul qilindi -> til savoli: sarlavha va savol hamda til tugmalari. Har tugmaning O'Z `action_id` si
    (`barno_lang_<til>`; Slack bitta blokda takror id ni rad etadi), qiymati - fayl id."""
    buttons = [button(f"{LANG_FLAGS[lang]} {name.capitalize()}", f"barno_lang_{lang}", file_id)
               for lang, name in LANG_NAMES.items()]
    return [{"type": "section", "text": {"type": "mrkdwn", "text": f"{head}\n{LANG_QUESTION}"}},
            {"type": "actions", "block_id": f"barno-langs:{file_id}", "elements": buttons}]


def option(text: str, value: str) -> dict[str, Any]:
    return {"text": {"type": "plain_text", "text": text[:75]}, "value": value}


def button(text: str, action_id: str, value: str, *, confirm: dict[str, Any] | None = None) -> dict[str, Any]:
    element: dict[str, Any] = {"type": "button", "action_id": action_id,
                               "text": {"type": "plain_text", "text": text[:75]}, "value": value}
    if confirm:
        element["confirm"] = confirm
    return element


def controls(meeting_id: str) -> list[dict[str, Any]]:
    """Xulosa ostidagi tugmalar (ega tartibi 2026-11-12): «📥 Yuklab olish» (transkript), «✅ Vazifalar»,
    «📄 Bayonnoma», «Eksport» (xulosa, hisobot) va chat haqida eslatma (`CHAT_HINT`).
    Qayta o'girish tugmalari yo'q - til audio yuklanganda so'raladi (`lang_question`). «Boshqa shablon bilan
    xulosa» ham yo'q (ega qarori 2026-11-12: hozirgi bosqichda kerak emas - xulosa avtomatik shablon bilan).
    Qiymatlarda yig'ilish id'si."""
    elements = [
        # Transkript chatga yozilmaydi - uni olish yo'li shu menyu (TXT kartaning thread'iga).
        select("📥 Yuklab olish", "barno_download", [(title, f"{meeting_id}|{kind}") for kind, title in DOWNLOADS]),
        button("✅ Vazifalar", "barno_tasks", meeting_id),
        # Rasmiy hujjat: til menyusi alohida xabarda (`minutes_menu`) - tugma faqat uni chaqiradi.
        button("📄 Bayonnoma", "barno_minutes", meeting_id),
        select("Eksport", "barno_export", [(title, f"{meeting_id}|{kind}") for kind, title in EXPORTS]),
    ]
    return [{"type": "actions", "block_id": mark(meeting_id), "elements": elements}, context(CHAT_HINT)]


def select(placeholder: str, action_id: str, options: list[tuple[str, str]]) -> dict[str, Any]:
    """Ochiladigan ro'yxat (`static_select`): (nom, qiymat) juftlari."""
    return {"type": "static_select", "action_id": action_id,
            "placeholder": {"type": "plain_text", "text": placeholder[:150]},
            "options": [option(text, value) for text, value in options]}


def chat_actions(meeting_id: str) -> dict[str, Any]:
    """Chat javobi ostidagi «🔄 Yangi suhbat» (`barno_chat_reset`, qiymati - yig'ilish id'si). `block_id` - yig'ilish
    belgisi `chat` tegi bilan (`mark`; xabarda takrorlanmaydi)."""
    return {"type": "actions", "block_id": mark(meeting_id, "chat"),
            "elements": [button(CHAT_RESET_BUTTON, "barno_chat_reset", meeting_id)]}


def retry_button(value: str) -> dict[str, Any]:
    return {"type": "actions", "elements": [button("Qayta urinish", "barno_retry", value)]}


#: Bayonnoma til menyusi xabarining matni (bildirishnoma uchun ham). Menyu thread'idagi har javob - hujjat uchun
#: ko'rsatma (`meeting.question`, `minutes` tegi: chat modelisiz), til tugmasi ularni qo'llaydi.
MINUTES_PROMPT = ("📄 *Bayonnoma* - hujjat tilini tanlang. Avval ko'rsatma bermoqchi bo'lsangiz (rais, qatnashchilar, "
                  "yig'ilish sanasi, nimaga e'tibor berish) - shu xabarga thread'da yozing, so'ng tilni tanlang.")
#: Til tanlangandan keyin format savoli (`minutes_formats`): `title` - hujjat tili.
MINUTES_FORMAT_PROMPT = ("📄 *Bayonnoma* ({title}) - qaysi formatda kerak? *Word* - tahrirlash va «________» joylarini "
                         "to'ldirish uchun, *PDF* - ko'rish va ulashish uchun.")
#: Bayonnoma natijasi ostidagi eslatma (`minutes_hint`): o'zgartirish shu xabar yoki fayl thread'ida
#: (`meeting.thread_target`; chatning o'zi - HR/CRM yordamchisi); yangi versiya fayli - odam tanlagan formatda.
MINUTES_EDIT_HINT = ("✏️ O'zgartirish kerak bo'lsa - shu xabarga yoki faylga thread'da yozing, masalan: «3-bandda "
                     "muddat 1-dekabr bo'lsin», «raisni Alisher Karimov deb yozing», «sana 11-noyabr bo'lsin». Barno "
                     "yangi faylni shu formatda yuboradi.")
#: Ko'rsatma eslab qolindi (`minutes_turn_note`) - chat javobi ostida.
MINUTES_NOTE_SAVED = ("📝 Bayonnoma uchun ko'rsatma eslab qolindi (jami {n} ta). Tayyorlash uchun «📄 Bayonnoma» "
                      "tugmasini bosing va tilni tanlang.")
#: Hujjat yozilayotganda "⏳" xabari: `verb` - `tahrirlanmoqda` (tahrir) yoki `tayyorlanmoqda`.
MINUTES_WORKING = "⏳ Bayonnoma ({title}) {verb}… 1-3 daqiqa."
#: Botlar kutishi (`minutes.wait`) tugadi, hujjat esa hali yozilmoqda: tayyori til tugmasidan bepul qayta yuboriladi.
MINUTES_STILL_RUNNING = ("⏳ Bayonnoma hali tayyorlanmoqda - tayyor bo'lgach «📄 Bayonnoma» tugmasidan til va formatni "
                         "tanlang, fayl qayta yuboriladi.")
#: Chat navbatidan bayonnoma ishi boshlanmadi (`ChatTurn.minutes.error`, hujjat id'siz) - chat javobi ostida.
MINUTES_NOT_STARTED = "⚠ Bayonnoma ishi boshlanmadi: {detail}"
#: Word faylidagi bo'sh joylar (`minutes_result`): sarlavha qiymatini ega aytgan bo'lsa (`header`) - u bo'sh emas.
_BLANK_SLOTS = (("organization", "bank nomi"), ("chair", "rais"), ("attendees", "qatnashuvchilar"))


def minutes_menu(meeting_id: str, default: str) -> list[dict[str, Any]]:
    """Bayonnoma tili tugmalari (`minutes.text.LANGS`): tavsiya etilgani (yig'ilish tilidan
    `default_lang`) BIRINCHI va `primary` - bank hujjati odatda kirillda, lekin tanlov odamniki.
    Qiymat `yig'ilish|til`; `block_id` yig'ilish belgisini olib yuradi (`mark`, `minutes` tegi: menyu thread'idagi
    javob shu yozuv bayonnomasi uchun ko'rsatma)."""
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


def minutes_hint(meeting_id: str, lang: str, fmt: str | None = None) -> dict[str, Any]:
    """Bayonnoma natijasi ostidagi tahrir eslatmasi (`MINUTES_EDIT_HINT`). `block_id` - yig'ilish belgisi
    `doc:<til>[:<format>]` tegi bilan (`doc_tag`): shu xabar thread'idagi javob o'sha til hujjati bo'yicha va tahrir
    fayli o'sha formatda (`meeting.question`)."""
    return context(MINUTES_EDIT_HINT, block_id=mark(meeting_id, doc_tag(lang, fmt)))


def minutes_formats(meeting_id: str, lang: str) -> list[dict[str, Any]]:
    """Til tanlangandan keyin format tanlovi (ega qarori 2026-11-13): «📄 Word» (asosiy - kotib «________» joylarini
    shu faylda to'ldiradi) va «📕 PDF». Qiymat `yig'ilish|til`, `action_id` - `barno_minutes_fmt_<format>`; `block_id`
    - `minutes` tegi (til menyusi kabi: thread'idagi javob - yozishdan oldingi ko'rsatma)."""
    title = minutes_text.LANG_TITLES.get(lang, lang)
    buttons = [button("📄 Word", "barno_minutes_fmt_docx", f"{meeting_id}|{lang}"),
               button("📕 PDF", "barno_minutes_fmt_pdf", f"{meeting_id}|{lang}")]
    buttons[0]["style"] = "primary"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": MINUTES_FORMAT_PROMPT.format(title=title)}},
            {"type": "actions", "block_id": mark(meeting_id, "minutes"), "elements": buttons}]


def minutes_turn_note(ref: dict[str, Any] | None) -> str:
    """Chat javobi ostiga bayonnoma amali haqida qator (`ChatTurn.minutes`): ko'rsatma - eslab qolindi (jami nechta)
    va hujjat qanday tayyorlanadi; ish boshlanmagan (`error`, hujjat id'siz) - sababi. Boshqa hollarda bo'sh:
    boshlangan ishning natijasi alohida xabarda (`meeting._follow_minutes`)."""
    if not ref:
        return ""
    if ref.get("action") == "note":
        return "\n\n" + MINUTES_NOTE_SAVED.format(n=int(ref.get("notes") or 0) or 1)
    error = ref.get("error")
    if error and not ref.get("id"):
        return "\n\n" + MINUTES_NOT_STARTED.format(detail=escape(str(error.get("message") or "")))
    return ""


def minutes_result(view: dict[str, Any], lang: str, fmt: str = "docx") -> str:
    """Tayyor bayonnoma haqida xabar: sarlavha (asl hujjat - "tayyor"; tahrir - "tahrirlandi" yoki ko'rsatmalar
    qo'llangan bo'lsa "yangilandi", versiyasi bilan), bo'lim/band soni, loyiha eslatmasi (Word'dagi bo'sh joylar - ega
    aytgan sarlavha qiymatlari bo'sh emas), o'zgartirish so'rovi va o'zgarishlar (`minutes.diff.summary_uz`),
    modelning izohlari (aniqlashtirish kerak) va sifat ogohlantirishlari - `ungrounded_name:<ism>` (transkriptda
    bo'lmagan ism `BLANK` bo'ldi), `script_mismatch` (yozuv tanlangan tilga mos emas), `header_dropped:<kalit>`,
    `superseded_revisions:<n>`, `guidance_truncated:<n>`. Ko'rinishning yangi kalitlari `.get()` bilan: ularsiz
    (eski ko'rinish) matn avvalgidek, baytma-bayt. `fmt` - yuborilgan fayl: PDF'da bo'sh joylarni to'ldirish uchun
    Word tanlash kerakligi aytiladi."""
    request = export.one_line(view.get("request") or "", 200)
    parts = [_minutes_head(view, lang, requested=bool(request), fmt=fmt)]
    if request:
        parts.append(f"So'rov: «{escape(request)}»")
    if view.get("kind") == "revise":
        changes = view.get("changes")
        if not minutes_diff.empty(changes):
            parts.append(f"*O'zgarishlar:* {escape(minutes_diff.summary_uz(changes))}.")
        elif not request:
            parts.append("Ko'rsatmalar bayonnomada allaqachon aks etgan - matn o'zgarmadi.")
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
    dropped = [escape(minutes_diff.HEADER_NAMES_UZ.get(key, key))
               for key in _warning_values(warnings, "header_dropped:")]
    if dropped:
        parts.append("Ko'rsatmada aniq aytilmagan sarlavha qiymatlari bo'sh qoldirildi: "
                     + ", ".join(dict.fromkeys(dropped)) + ".")
    superseded = _warning_count(warnings, "superseded_revisions:")
    if superseded:
        parts.append(f"⚠ Matn tahrirlangani uchun bayonnoma yangidan yozildi - avvalgi {superseded} ta o'zgartirish "
                     "kiritilmagan, kerak bo'lsa qayta yozing.")
    truncated = _warning_count(warnings, "guidance_truncated:")
    if truncated:
        parts.append(f"⚠ Ko'rsatmalar juda ko'p - eng eskilaridan {truncated} tasi hisobga olinmadi.")
    return "\n\n".join(parts)


def _minutes_head(view: dict[str, Any], lang: str, *, requested: bool, fmt: str = "docx") -> str:
    """`minutes_result` ning birinchi xatboshi: sarlavha (`requested` - tahrir o'zgartirish so'rovi bo'yicha),
    bo'lim/band soni, Word'dagi bo'sh joylar va (asl hujjatda) hisobga olingan ko'rsatmalar soni."""
    title = minutes_text.LANG_TITLES.get(lang, lang)
    counts = f"{int(view.get('sectionCount') or 0)} bo'lim, {int(view.get('itemCount') or 0)} band."
    revised = view.get("kind") == "revise"
    version = int(view.get("version") or 1)
    if revised and requested:
        head = f"✅ *Bayonnoma tahrirlandi* ({title}, {version}-versiya): {counts}"
    elif revised:
        head = f"✅ *Bayonnoma yangilandi* ({title}, {version}-versiya): ko'rsatmalaringiz qo'llandi - {counts}"
    else:
        head = f"✅ *Bayonnoma tayyor* ({title}): {counts}"
    header = view.get("header") or {}
    blanks = [name for key, name in _BLANK_SLOTS if not header.get(key)] + ["№", "sana"]
    if fmt == "pdf":
        head += (f" Loyiha - «{minutes_text.BLANK}» joylari bo'sh ({', '.join(blanks)}); ularni to'ldirish uchun Word "
                 "formatini tanlang.")
    else:
        head += f" Loyiha - Word faylidagi «{minutes_text.BLANK}» joylarini to'ldiring ({', '.join(blanks)})."
    applied = int(view.get("notesApplied") or 0)
    if not revised and applied > 0:
        head += f" Ko'rsatmalaringiz hisobga olindi ({applied} ta)."
    return head


def _warning_values(warnings: list[str], prefix: str) -> list[str]:
    """`<prefix><qiymat>` ko'rinishidagi ogohlantirishlarning qiymatlari (bo'shlari tashlanadi)."""
    return [w[len(prefix):].strip() for w in warnings if w.startswith(prefix) and w[len(prefix):].strip()]


def _warning_count(warnings: list[str], prefix: str) -> int:
    """`<prefix><n>` ogohlantirishidagi son (birinchisi); yo'q yoki son emas - 0."""
    for value in _warning_values(warnings, prefix):
        try:
            return max(0, int(value))
        except ValueError:
            return 0
    return 0


def speakers(view_speakers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Yig'ilish ko'rinishidagi spikerlar -> `export.speaker_name` kutgan shakl."""
    return {sp["id"]: {"name": sp.get("name"), "merged_into": sp.get("mergedInto"), "person_id": sp.get("personId")}
            for sp in view_speakers}


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

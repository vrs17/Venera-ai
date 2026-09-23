"""Javobni Telegram xabariga o'girish - SOF funksiyalar, tarmoqsiz.

Qoidalar mini app'dagi (`apps/tg/app.js`) bilan BIR XIL, faqat natija
oddiy matn emas, Telegram HTML'i (`parse_mode=HTML`):

  * AUDIT IZI olib tashlanadi (`answerBody`): javob oxiridagi "Tekshirilgan
    HRM ma'lumotlari:" va `[T1] hrm_today_late - ... status=200` qatorlari
    tizim uchun yozilgan, savol bergan odam uchun emas. Veb ilova uni
    yig'iladigan bo'limda ko'rsatadi, Telegram'da esa u javobni ko'mib
    yuborardi;
  * `[T1]` markerlari ham ketadi, hujjat iqtiboslari (`[1]`) QOLADI - ular
    pastdagi "Manbalar" ro'yxatiga ishora qiladi;
  * markdown: `**qalin**` -> <b>, sarlavha -> qalin qator, ro'yxat -> "•",
    havola -> faqat matni (manzil ichki bo'lishi mumkin).

Telegram HTML'i QATTIQ: yopilmagan yoki kesishgan teg butun xabarni rad
ettiradi. Shuning uchun har qator alohida o'giriladi va teglari tekshiriladi
(`_balanced`); shubhali qator oddiy matn bo'lib qoladi. Yuboruvchi ham
zaxira qiladi: Telegram baribir rad etsa, xabar teglarsiz qayta ketadi.
"""

from __future__ import annotations

import html
import re

from typing import Any

#: Telegram xabari 4096 belgigacha. HTML teglari bilan hisoblaymiz - ya'ni
#: haqiqiy matn bundan ham qisqa, zaxira bilan.
LIMIT = 4000

#: Jonli so'rov manbalari - hujjat emas, ekranga chiqmaydi (mini app'dagi
#: `LOOKUP_KINDS` bilan bir xil).
LOOKUP_KINDS = ("hrm", "crm")

#: Tugma `callback_data` si 64 BAYTGACHA.
_CALLBACK_MAX = 64
#: Yuqoridagi xizmat kalitlari uchun ruxsat etilgan belgilar
#: (`assistant._SAFE_KEY` bilan bir xil).
SAFE_KEY = re.compile(r"[\w.~:-]{1,128}")
#: Ariza fayli kaliti (`assistant._ARTIFACT_URL` bilan bir xil).
SAFE_ARTIFACT = re.compile(r"[\w.~-]{1,256}")

_TRACE_LINE = re.compile(r"^\s*\[[A-Za-z]{1,4}[_-]?\d{1,6}\]\s")
_TAG = re.compile(r"<(/?)(b|i|s|code|pre)>")


def esc(text: Any) -> str:
    """HTML uchun: faqat `&`, `<`, `>` - Telegram shuni talab qiladi."""
    return html.escape(str(text), quote=False)


def plain(markup: str) -> str:
    """HTML -> oddiy matn (Telegram belgilashni rad etgandagi zaxira)."""
    return html.unescape(_TAG.sub("", markup))


# --- javob matni -------------------------------------------------------------


def answer_body(markdown: str) -> str:
    """Javobning o'zi - audit izidan oldingi hammasi (`answerBody` nusxasi).

    Iz qatorlari `[T1]` kabi marker bilan BOSHLANADI; javob ichidagi iqtibos
    esa gap OXIRIDA turadi. Izni tanishtirgan qator (`:` bilan tugaydi) ham
    tashlanadi. Hammasi iz bo'lib chiqsa - boricha qoladi.
    """
    lines = markdown.splitlines()
    at = next((i for i, line in enumerate(lines) if _TRACE_LINE.match(line)), -1)
    if at < 0:
        return markdown
    while at > 0 and (not lines[at - 1].strip() or lines[at - 1].strip().endswith(":")):
        at -= 1
    body = "\n".join(lines[:at]).strip()
    return body or markdown


def to_blocks(markdown: str) -> list[str]:
    """Markdown -> Telegram HTML bloklari (paragraf yoki kod bloki)."""
    text = answer_body(markdown.replace("\r\n", "\n"))
    blocks: list[str] = []
    para: list[str] = []
    code: list[str] = []
    in_code = False

    def flush() -> None:
        if para:
            blocks.append("\n".join(para))
            para.clear()

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                if code:
                    blocks.append("<pre>" + esc("\n".join(code)) + "</pre>")
                code.clear()
                in_code = False
            else:
                flush()
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            flush()
            continue
        converted = _line(line)
        if converted is not None and converted.strip():
            para.append(converted)
    if in_code and code:
        blocks.append("<pre>" + esc("\n".join(code)) + "</pre>")
    flush()
    return blocks


def _line(line: str) -> str | None:
    """Bitta qator. `None` - qator tashlanadi (jadval ajratgichi, chiziq)."""
    if re.fullmatch(r"\s*\|?[\s:|-]{3,}\|?\s*", line) and "-" in line:
        return None
    if re.fullmatch(r"\s*([-*_])(?:\s*\1){2,}\s*", line):
        return None
    heading = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
    if heading:
        inner = _inline(heading.group(1))
        return f"<b>{inner}</b>" if inner and "<b>" not in inner else inner
    bullet = re.match(r"^(\s*)[-*+•]\s+(.*)$", line)
    if bullet:
        return bullet.group(1) + "• " + _inline(bullet.group(2))
    quote = re.match(r"^\s*>\s?(.*)$", line)
    if quote:
        return _inline(quote.group(1))
    stripped = line.strip()
    if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        return " | ".join(_inline(c) for c in cells if c)
    return _inline(line)


def _inline(text: str) -> str:
    """Qator ichidagi belgilash. Kod bo'lagi (`...`) ichiga tegilmaydi."""
    out: list[str] = []
    for part in re.split(r"(`[^`\n]+`)", text):
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            out.append("<code>" + esc(part[1:-1]) + "</code>")
        else:
            out.append(_emphasis(part))
    return _tidy("".join(out))


def _emphasis(part: str) -> str:
    source = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", part)
    # Iz olib tashlangach `[T1]` hech qayerga ishora qilmaydi. ATAYLAB faqat
    # `T`: `[1]` hujjat iqtibosi, u qoladi.
    source = re.sub(r"\[T\d{1,3}\][ \t]?", "", source)
    marked = esc(source)
    marked = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", marked)
    marked = re.sub(r"(?<![\w])__(?=\S)(.+?)(?<=\S)__(?![\w])", r"<b>\1</b>", marked)
    marked = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", marked)
    marked = re.sub(r"(?<![\w*])\*(?=[^\s*])([^*<>\n]+?)(?<=\S)\*(?![\w*])", r"<i>\1</i>", marked)
    marked = marked.replace("*", "").replace("~~", "")
    if not _balanced(marked):
        # Kesishgan belgilash (`**a ~~b** c~~`) - teglarsiz, lekin o'qiladigan.
        return esc(re.sub(r"\*\*|__|~~|\*", "", source))
    return marked


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
    return text.rstrip()


def _balanced(markup: str) -> bool:
    stack: list[str] = []
    for closing, tag in _TAG.findall(markup):
        if not closing:
            stack.append(tag)
        elif not stack or stack.pop() != tag:
            return False
    return not stack


def pack(blocks: list[str], limit: int = LIMIT) -> list[str]:
    """Bloklarni xabarlarga taqsimlaydi: har biri `limit` dan oshmaydi va
    teg hech qachon ikki xabarga bo'linib qolmaydi."""
    chunks: list[str] = []
    current = ""
    for block in _fit(blocks, limit):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = block
    if current:
        chunks.append(current)
    return chunks


def _fit(blocks: list[str], limit: int):
    for block in blocks:
        if len(block) <= limit:
            yield block
            continue
        if block.startswith("<pre>") and block.endswith("</pre>"):
            inner = html.unescape(block[5:-6])
            for piece in _split_text(inner, limit - 11):
                yield "<pre>" + esc(piece) + "</pre>"
            continue
        # Teglar qator chegarasidan o'tmaydi - qator bo'yicha bo'lish xavfsiz.
        current = ""
        for line in block.split("\n"):
            if len(line) > limit:
                if current:
                    yield current
                    current = ""
                for piece in _split_text(plain(line), limit):
                    yield esc(piece)
                continue
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= limit:
                current = candidate
            else:
                yield current
                current = line
        if current:
            yield current


def _split_text(text: str, limit: int) -> list[str]:
    """Uzun oddiy matn - so'z chegarasida bo'laklar. Escape'dan KEYINGI
    uzunlik ham sig'ishi uchun zaxira bilan."""
    size = max(100, limit // 2)
    pieces: list[str] = []
    rest = text
    while len(rest) > size:
        cut = rest.rfind(" ", 0, size)
        cut = cut if cut > size // 2 else size
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def frame_error(frame: dict[str, Any]) -> str:
    """Oqimdagi `error` kadrining matni - mini app'dagi `frameError` nusxasi.

    Xizmatning O'Z matni yutadi: savol qaysi platformani talab qilganini u
    biladi, biz bilmaymiz.
    """
    own = str(frame.get("text") or "").strip()
    if own:
        return own
    if frame.get("code") in ("auth_missing", "auth_expired"):
        return ("Bu savol uchun jonli ma'lumot kerak, o'sha tizim esa hisobingizga bu yerda "
                "hali ulanmagan. Qoidalar va hujjatlar bo'yicha savollar ishlaydi.")
    return "Javob berilmadi"


# --- manbalar ---------------------------------------------------------------


def doc_sources(items: Any) -> list[dict[str, Any]]:
    """Hujjat manbalari. Jonli so'rovlar (`hrm`, `crm`) chiqmaydi - ular audit
    izining o'zi, u esa yuqorida olib tashlangan."""
    if not isinstance(items, list):
        return []
    return [item for item in items
            if isinstance(item, dict) and str(item.get("kind")) not in LOOKUP_KINDS]


def source_label(source: dict[str, Any], index: int) -> str:
    """"[1] Ichki mehnat tartibi qoidalari, 22-bet" - `sourceLabel` nusxasi."""
    mark = source.get("marker") or f"[{source.get('citation_index') or index + 1}]"
    name = source.get("title") or source.get("doc_id") or "hujjat"
    page = source.get("page")
    return f"{mark} {name}" + (f", {page}-bet" if page else "")


def sources_block(docs: list[dict[str, Any]]) -> str:
    lines = [esc(source_label(doc, i)) for i, doc in enumerate(docs)]
    return "📚 <b>Manbalar</b>\n" + "\n".join(lines)


def doc_buttons(docs: list[dict[str, Any]], *, most: int = 9) -> dict[str, Any] | None:
    """Har hujjat uchun tugma - bosilsa PDF'ning o'zi shu chatga keladi."""
    buttons: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, doc in enumerate(docs):
        doc_id = doc.get("doc_id")
        if not isinstance(doc_id, str) or not SAFE_KEY.fullmatch(doc_id) or doc_id in seen:
            continue
        data = f"d:{doc_id}"
        if len(data.encode()) > _CALLBACK_MAX:
            continue
        seen.add(doc_id)
        mark = doc.get("marker") or f"[{doc.get('citation_index') or index + 1}]"
        buttons.append({"text": f"📄 {mark}", "callback_data": data})
        if len(buttons) >= most:
            break
    if not buttons:
        return None
    return {"inline_keyboard": [buttons[i:i + 3] for i in range(0, len(buttons), 3)]}


def file_button(kind: str, token: str) -> dict[str, Any] | None:
    """Ariza faylining boshqa ko'rinishi uchun tugma ("PDF")."""
    data = f"f:{'p' if kind == 'pdf' else 'd'}:{token}"
    if len(data.encode()) > _CALLBACK_MAX or not SAFE_ARTIFACT.fullmatch(token):
        return None
    return {"inline_keyboard": [[{"text": f"📄 {kind.upper()} ko'rinishida", "callback_data": data}]]}


def app_button(url: str, label: str = "Venera ilovasini ochish") -> dict[str, Any] | None:
    """Mini app'ni ochadigan tugma (faqat shaxsiy chatda ishlaydi)."""
    if not url:
        return None
    return {"inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]}


# --- yozuv amali (taklif kartasi) ----------------------------------------------


def action_text(value: Any) -> str:
    """Qiymatning ko'rinadigan matni. Obyekt bo'lsa - nomi, kaliti yoki
    mazmuni; xom JSON ko'rsatilmaydi."""
    if value is None or value == "":
        return "—"
    if isinstance(value, dict):
        for key in ("title", "name", "key", "summary", "id"):
            item = value.get(key)
            if item not in (None, ""):
                return str(item)
        scalars = [str(v) for v in value.values() if isinstance(v, (str, int, float)) and v != ""]
        return " · ".join(scalars) or "—"
    if isinstance(value, list):
        return ", ".join(action_text(v) for v in value) or "—"
    return str(value)


def proposal_card(proposal: dict[str, Any]) -> str:
    """Taklif kartasi - `ActionCard.vue` / mini app 16-bo'lim mazmuni."""
    platform = str(proposal.get("connector") or "").upper()
    lines = ["✏️ <b>Taklif qilingan o'zgarish</b>" + (f" · {esc(platform)}" if platform else "")]
    if proposal.get("summary"):
        lines.append(esc(proposal["summary"]))
    details: list[str] = []
    if proposal.get("target"):
        details.append(f"<b>Obyekt:</b> {esc(action_text(proposal['target']))}")
    for change in proposal.get("changes") or []:
        if not isinstance(change, dict) or not (change.get("field") or "to" in change):
            continue
        label = esc(change.get("field") or "O'zgarish")
        before = change.get("from")
        shown = f"<s>{esc(action_text(before))}</s> → " if before not in (None, "") else ""
        details.append(f"<b>{label}:</b> {shown}{esc(action_text(change.get('to')))}")
    if details:
        lines.append("\n".join(details))
    warnings = [w for w in proposal.get("warnings") or [] if w]
    if warnings:
        lines.append("\n".join(f"⚠️ {esc(w)}" for w in warnings))
    lines.append("<i>Tasdiqlamaguningizcha hech narsa o'zgarmaydi. "
                 "Taklif 15 daqiqada kuchini yo'qotadi.</i>")
    return "\n\n".join(lines)


def proposal_buttons(token: str) -> dict[str, Any] | None:
    """[Rad etish] [Tasdiqlash]. Kalit tugmaga sig'masa `None`."""
    if not SAFE_KEY.fullmatch(token or "") or len(f"a:c:{token}".encode()) > _CALLBACK_MAX:
        return None
    return {"inline_keyboard": [[
        {"text": "✖️ Rad etish", "callback_data": f"a:x:{token}"},
        {"text": "✅ Tasdiqlash", "callback_data": f"a:c:{token}"},
    ]]}


def outcome(result: dict[str, Any]) -> tuple[bool, str, str]:
    """(yakunlandimi, xabar HTML, qisqa bildirishnoma) - `actionOutcome` nusxasi."""
    status = result.get("status")
    if status == "executed" and result.get("ok") is not False:
        found = result.get("result") if isinstance(result.get("result"), dict) else {}
        key = next((found[k] for k in ("key", "id", "number") if found.get(k) is not None), None)
        text = "✅ <b>Bajarildi</b>" + (f": <code>{esc(key)}</code>" if key is not None else "")
        return True, text, "Bajarildi"
    if status == "cancelled":
        return True, "✖️ Rad etildi - hech narsa o'zgarmadi.", "Rad etildi"
    if status == "expired":
        return True, "⌛ Taklif muddati tugagan. Kerak bo'lsa savolni qaytadan bering.", "Muddati tugagan"
    if status == "pending":
        return False, "", "Taklif hali kutilmoqda"
    reason = str(result.get("error") or "Amalni bajarib bo'lmadi.")
    return True, f"⚠️ <b>Bajarilmadi</b>: {esc(reason)}", "Bajarilmadi"

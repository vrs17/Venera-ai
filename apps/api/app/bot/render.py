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
    havola -> faqat matni (manzil ichki bo'lishi mumkin);
  * qonunchilik manbasi (`kind: "law"`, v2) - "Manbalar" ichida "LEX.UZ ·
    qonunchilik" yorlig'i bilan HAVOLA (`<a href>`): u tekshirilgan `https`
    manzil va LEX.UZ dagi moddaga olib boradi. Hujjat ko'ruvchisiga (`d:`
    tugmasi) HECH QACHON yo'naltirilmaydi - u faqat `doc_id` uchun;
  * "Manbalar" - QISQA izohlar ro'yxati: javobda iqtibos qilinganlari
    (`cited`), `FOOTNOTES_MAX` tagacha, uzun nom qisqartiriladi. Telefonda
    javobning o'zi manbalar ostida ko'milib ketmasin.

TUGMALAR (`callback_data`, 64 BAYTGACHA - Telegram chegarasi):

    d:<doc_id>          "Hujjatni ochish" - imzolangan havola yuboriladi
    f:<d|p>:<kalit>     ariza faylining boshqa ko'rinishi
    a:<c|x>:<kalit>     taklifni tasdiqlash / rad etish
    r:<turnId>          "⚑" - javob haqida xabar berish (sabablar ochiladi)
    r:<turnId>:<sabab>  sabab tanlandi (`REPORT_REASONS`); `-` - bekor,
                        `=` - allaqachon yuborilgan

Tugma ma'lumotiga ISHONILMAYDI: o'zgartirilgan Telegram klienti istalgan
`callback_data` yubora oladi. Shuning uchun bu yerda faqat SHAKL
tekshiriladi (`parse_report`), egalik esa chaqiruvchida (`runner`).

Telegram HTML'i QATTIQ: yopilmagan yoki kesishgan teg butun xabarni rad
ettiradi. Shuning uchun har qator alohida o'giriladi va teglari tekshiriladi
(`_balanced`); shubhali qator oddiy matn bo'lib qoladi. Yuboruvchi ham
zaxira qiladi: Telegram baribir rad etsa, xabar teglarsiz qayta ketadi.
"""

from __future__ import annotations

import html
import re

from typing import Any

from ..services.answer_sources import documents
from ..services.integrations.assistant import safe_source_url

#: Telegram xabari 4096 belgigacha. HTML teglari bilan hisoblaymiz - ya'ni
#: haqiqiy matn bundan ham qisqa, zaxira bilan.
LIMIT = 4000

#: Jonli so'rov manbalari - hujjat emas, ekranga chiqmaydi (mini app'dagi
#: `LOOKUP_KINDS` bilan bir xil).
LOOKUP_KINDS = ("hrm", "crm")

#: Qonunchilik manbasi (v2): LEX.UZ dagi modda. Hujjat EMAS - PDF tugmasi
#: yo'q, `/doc` ga yo'naltirilmaydi; havola Telegram'ning o'zida ochiladi.
LAW_KIND = "law"
#: Yorliq - yuqoridagi xizmat xati (4-bo'lim) bo'yicha, web va mini app'da ham shu.
LAW_LABEL = "LEX.UZ · qonunchilik"

#: Tugma `callback_data` si 64 BAYTGACHA.
CALLBACK_MAX = 64
#: Izohlar ro'yxatida shundan ko'p manba ko'rsatilmaydi - qolgani "yana N ta".
FOOTNOTES_MAX = 6
#: Manba nomi shundan uzun bo'lsa qisqartiriladi (telefon ekranida 2 qator).
_TITLE_MAX = 90
#: Hujjat tugmalari: shundan ko'p bo'lsa qisqa yorliq ("📄 [3]") va 3 tadan qator.
_DOC_ROWS_FULL = 3

#: "Xabar berish" sabablari: tugmadagi QISQA kod -> `schemas/reports.REASONS`
#: dagi kalit -> yorliq. Yorliqlar veb ilovadagi bilan bir xil
#: (`apps/web/src/i18n/report.ts`, uz). Kod bitta harf - tugma ma'lumoti
#: 64 baytga bemalol sig'sin.
REPORT_REASONS: tuple[tuple[str, str, str], ...] = (
    ("w", "wrong", "Notoʻgʻri"),
    ("i", "incomplete", "Toʻliq emas"),
    ("o", "outdated", "Eskirgan"),
    ("u", "unsafe", "Xavfli"),
    ("b", "other", "Boshqa"),
)
REPORT_CODES = {code: reason for code, reason, _ in REPORT_REASONS}
#: "⚑" ochilgandagi "Bekor" va yuborilgandan keyingi belgi.
REPORT_CANCEL = "-"
REPORT_DONE = "="
#: Savol kaliti - `TurnRecorder.turn_id` (uuid4 hex, 32 belgi).
_TURN = re.compile(r"[0-9a-f]{32}")
#: Yuqoridagi xizmat kalitlari uchun ruxsat etilgan belgilar
#: (`assistant._SAFE_KEY` bilan bir xil).
SAFE_KEY = re.compile(r"[\w.~:-]{1,128}")
#: Ariza fayli kaliti (`assistant._ARTIFACT_URL` bilan bir xil).
SAFE_ARTIFACT = re.compile(r"[\w.~-]{1,256}")

_TRACE_LINE = re.compile(r"^\s*\[[A-Za-z]{1,4}[_-]?\d{1,6}\]\s")
_TAG = re.compile(r"<(/?)(b|i|s|code|pre)>")
#: Faqat BIZ yasagan havola (`law_line`): manzil qo'shtirnoqsiz, escape qilingan.
_LINK = re.compile(r'<a href="([^"<>]*)">(.*?)</a>')


def esc(text: Any) -> str:
    """HTML uchun: faqat `&`, `<`, `>` - Telegram shuni talab qiladi."""
    return html.escape(str(text), quote=False)


def plain(markup: str) -> str:
    """HTML -> oddiy matn (Telegram belgilashni rad etgandagi zaxira).

    Havola `matn (manzil)` bo'lib qoladi - teglarsiz xabarda ham odam
    LEX.UZ dagi moddani ocha olsin."""
    text = _LINK.sub(lambda m: f"{m.group(2)} ({m.group(1)})", markup)
    return html.unescape(_TAG.sub("", text))


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
    biladi, biz bilmaymiz. Shuning uchun zaxira matn ikkala tizimning
    yo'lini aytadi: HRM qo'lda ulanadi, CRM esa vebga BRB-Tech ID (SSO) bilan
    kirganda o'zi ulanadi - CRM ni "ulash" tugmasi hech qayerda yo'q.
    """
    own = str(frame.get("text") or "").strip()
    if own:
        return own
    if frame.get("code") in ("auth_missing", "auth_expired"):
        return ("Bu savol uchun jonli ma'lumot kerak, o'sha tizim esa hisobingizga hali "
                "ulanmagan. HRM Barno veb ilovasida «+» menyusidan ulanadi; CRM vebga BRB-Tech ID "
                "bilan kirganda o'zi ulanadi. Qoidalar va hujjatlar bo'yicha savollar ishlaydi.")
    return "Javob berilmadi"


# --- manbalar ---------------------------------------------------------------


def doc_sources(items: Any) -> list[dict[str, Any]]:
    """Hujjat manbalari. Jonli so'rovlar (`hrm`, `crm`) chiqmaydi - ular audit
    izining o'zi, u esa yuqorida olib tashlangan."""
    if not isinstance(items, list):
        return []
    # Veb va ilova bilan BITTA qoida (`answer_sources.is_lookup`): DWH, Biznes 24/7,
    # Superapp so'rovlari ham hujjat emas.
    return documents(items)


def source_label(source: dict[str, Any], index: int) -> str:
    """"[1] Ichki mehnat tartibi qoidalari, 22-bet" - `sourceLabel` nusxasi."""
    mark = source.get("marker") or f"[{source.get('citation_index') or index + 1}]"
    name = source.get("title") or source.get("doc_id") or "hujjat"
    page = source.get("page")
    return f"{mark} {name}" + (f", {page}-bet" if page else "")


def law_line(source: dict[str, Any], index: int) -> str:
    """Qonunchilik manbasi - Telegram HTML qatori:

        [2] LEX.UZ · qonunchilik: <a href="https://www.lex.uz/...">Mehnat kodeksi, 160-modda …</a>

    Havola faqat xavfsiz `https` manzil bo'lsa (`safe_source_url` - oqimda
    tekshirilgan, bu yerda IKKINCHI marta: render boshqa manbadan ham
    chaqirilishi mumkin). Aks holda nomi oddiy matn bo'lib qoladi - manba
    yo'qolmaydi, faqat bosib bo'lmaydi.
    """
    mark = source.get("marker") or f"[{source.get('citation_index') or index + 1}]"
    title = str(source.get("title") or "").strip()
    url = safe_source_url(source.get("url"))
    if url is None:
        return esc(f"{mark} {LAW_LABEL}" + (f": {title}" if title else ""))
    link = f'<a href="{html.escape(url, quote=True)}">{esc(title or LAW_LABEL)}</a>'
    return f"{esc(mark)} {esc(LAW_LABEL)}: {link}" if title else f"{esc(mark)} {link}"


def _number(source: dict[str, Any], index: int) -> int:
    """Manbaning iqtibos raqami: `marker` ("[2]") -> `citation_index` -> tartib."""
    found = re.search(r"\d{1,3}", str(source.get("marker") or ""))
    if found:
        return int(found.group())
    cited_at = source.get("citation_index")
    if isinstance(cited_at, int) and not isinstance(cited_at, bool) and cited_at > 0:
        return cited_at
    return index + 1


def cited(docs: list[dict[str, Any]], body: str) -> list[dict[str, Any]]:
    """Javob matnida iqtibos qilingan manbalar (`[1]`, `[2]`) - qisqa javob
    ostida o'nta "ehtimol kerak" hujjat turmasin.

    Javobda birorta ham iqtibos bo'lmasa yoki iqtiboslar hech bir manbaga mos
    kelmasa - HAMMASI (manba yo'qolgandan ortiqchasi yaxshi). Raqam OLDINDAN
    `marker` ga yoziladi: saralangandan keyin tartib raqami siljiydi va
    "[3]" manbasi "[2]" bo'lib qolardi. Bir xil raqam ikki marta kelsa
    (bir hujjatning ikki bo'lagi) - bittasi.
    """
    numbered: list[tuple[int, dict[str, Any]]] = []
    seen: set[int] = set()
    for index, doc in enumerate(docs):
        number = _number(doc, index)
        if number in seen:
            continue
        seen.add(number)
        numbered.append((number, doc if doc.get("marker") else {**doc, "marker": f"[{number}]"}))
    marks = {int(m) for m in re.findall(r"\[(\d{1,3})\]", answer_body(body or ""))}
    picked = [doc for number, doc in numbered if number in marks]
    return picked or [doc for _, doc in numbered]


def _short(text: str, limit: int = _TITLE_MAX) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def sources_block(docs: list[dict[str, Any]], *, most: int = FOOTNOTES_MAX) -> str:
    """Izohlar: "📚 Manbalar" va har manba bitta qisqa qator. LEX.UZ -
    bosiladigan havola (`law_line`), ichki hujjat - nomi va beti (uni
    "Hujjatni ochish" tugmasi ochadi). `most` dan ortig'i - "yana N ta"."""
    lines = []
    for i, doc in enumerate(docs[:most]):
        item = {**doc, "title": _short(str(doc["title"]))} if doc.get("title") else doc
        lines.append(law_line(item, i) if doc.get("kind") == LAW_KIND else esc(source_label(item, i)))
    if len(docs) > most:
        lines.append(f"<i>… yana {len(docs) - most} ta manba - Barno ilovasida</i>")
    return "📚 <b>Manbalar</b>\n" + "\n".join(lines)


def doc_rows(docs: list[dict[str, Any]], *, most: int = 6) -> list[list[dict[str, str]]]:
    """Ichki hujjatlar uchun "Hujjatni ochish" tugmalari (`d:<doc_id>`).

    Bosilganda bot IMZOLANGAN, qisqa muddatli havola yuboradi (`runner`):
    bank hujjatining o'zi Telegram serverlariga yuklanmaydi. Qonunchilik
    manbasi tugma OLMAYDI: u hujjat emas, havolasi izohning o'zida.

    Bitta hujjat - "📄 Hujjatni ochish"; bir nechta - raqami bilan, har biri
    alohida qatorda; ko'p bo'lsa (`_DOC_ROWS_FULL` dan ortiq) - qisqa
    "📄 [n]" va 3 tadan qator, aks holda klaviatura ekranni egallab olardi.
    """
    picked: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, doc in enumerate(docs):
        if doc.get("kind") == LAW_KIND:
            continue
        doc_id = doc.get("doc_id")
        if not isinstance(doc_id, str) or not SAFE_KEY.fullmatch(doc_id) or doc_id in seen:
            continue
        data = f"d:{doc_id}"
        if len(data.encode()) > CALLBACK_MAX:
            continue
        seen.add(doc_id)
        picked.append((f"[{_number(doc, index)}]", data))
        if len(picked) >= most:
            break
    if not picked:
        return []
    if len(picked) == 1:
        return [[{"text": "📄 Hujjatni ochish", "callback_data": picked[0][1]}]]
    if len(picked) <= _DOC_ROWS_FULL:
        return [[{"text": f"📄 {mark} Hujjatni ochish", "callback_data": data}]
                for mark, data in picked]
    buttons = [{"text": f"📄 {mark}", "callback_data": data} for mark, data in picked]
    return [buttons[i:i + 3] for i in range(0, len(buttons), 3)]


def keyboard(rows: list[list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Qatorlar -> `reply_markup`; qator yo'q - `None` (tugmasiz xabar)."""
    return {"inline_keyboard": rows} if rows else None


def doc_buttons(docs: list[dict[str, Any]], *, most: int = 6) -> dict[str, Any] | None:
    """`doc_rows` - tayyor klaviatura sifatida (yoki `None`)."""
    return keyboard(doc_rows(docs, most=most))


def url_button(label: str, url: str) -> dict[str, Any] | None:
    """Brauzerda ochiladigan havola tugmasi - faqat `https`."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    return {"inline_keyboard": [[{"text": label, "url": url}]]}


# --- "Xabar berish" (⚑) --------------------------------------------------------


def report_row(turn_id: str) -> list[dict[str, str]]:
    """Javob ostidagi "⚑" - bosilsa sabablar ochiladi."""
    return [{"text": "⚑", "callback_data": f"r:{turn_id}"}]


def report_reason_rows(turn_id: str) -> list[list[dict[str, str]]]:
    """Sabablar (veb ilovadagi tartibda) va "Bekor" - 2 tadan qator."""
    buttons = [{"text": label, "callback_data": f"r:{turn_id}:{code}"}
               for code, _, label in REPORT_REASONS]
    buttons.append({"text": "Bekor", "callback_data": f"r:{turn_id}:{REPORT_CANCEL}"})
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def report_done_row(turn_id: str) -> list[dict[str, str]]:
    """Yuborilgandan keyin: qayta bosilsa faqat "allaqachon yuborilgan"."""
    return [{"text": "✓ Yuborildi", "callback_data": f"r:{turn_id}:{REPORT_DONE}"}]


def parse_report(rest: str) -> tuple[str, str] | None:
    """`r:` dan keyingi qism -> (savol kaliti, amal). Amal: `""` - sabablarni
    ochish, `REPORT_CODES` kaliti - yuborish, `-` - bekor, `=` - yuborilgan.

    Faqat SHAKL: kalit aynan 32 hex, amal ro'yxatdan. Savol kimniki ekanini
    chaqiruvchi tekshiradi - tugma ma'lumoti soxta bo'lishi mumkin.
    """
    if not isinstance(rest, str) or len(rest.encode()) > CALLBACK_MAX:
        return None
    turn_id, sep, action = rest.partition(":")
    if not _TURN.fullmatch(turn_id):
        return None
    if not sep:
        return turn_id, ""
    if action in REPORT_CODES or action in (REPORT_CANCEL, REPORT_DONE):
        return turn_id, action
    return None


def swap_report_rows(markup: Any, rows: list[list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Xabar klaviaturasidagi "⚑" qatorlarini (`r:` tugmali) `rows` bilan
    almashtiradi; qolgan qatorlar ("Hujjatni ochish") o'z joyida qoladi.

    `markup` - tugma bosilgan xabarning Telegram'dagi klaviaturasi
    (`callback_query.message.reply_markup`). Shakli buzuq bo'lsa - faqat
    `rows`. Notanish tugmalar tashlanadi: faqat matnli va `callback_data`,
    `url` yoki `web_app` li tugma qayta yuboriladi.
    """
    kept: list[list[dict[str, Any]]] = []
    board = markup.get("inline_keyboard") if isinstance(markup, dict) else None
    for row in board if isinstance(board, list) else []:
        if not isinstance(row, list):
            continue
        clean = [b for b in row if isinstance(b, dict) and isinstance(b.get("text"), str)
                 and any(k in b for k in ("callback_data", "url", "web_app"))]
        if not clean or any(str(b.get("callback_data") or "").startswith("r:") for b in clean):
            continue
        kept.append(clean)
    return keyboard(kept + rows)


def file_button(kind: str, token: str) -> dict[str, Any] | None:
    """Ariza faylining boshqa ko'rinishi uchun tugma ("PDF")."""
    data = f"f:{'p' if kind == 'pdf' else 'd'}:{token}"
    if len(data.encode()) > CALLBACK_MAX or not SAFE_ARTIFACT.fullmatch(token):
        return None
    return {"inline_keyboard": [[{"text": f"📄 {kind.upper()} ko'rinishida", "callback_data": data}]]}


#: Mini app tugmasi - ulanmagan odamga, `/start` va `/logout` dan keyin.
APP_LABEL = "Barnoni ochish"


def app_button(url: str, label: str = APP_LABEL) -> dict[str, Any] | None:
    """Mini app'ni ochadigan tugma (`web_app` - faqat shaxsiy chatda ishlaydi)."""
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
    if not SAFE_KEY.fullmatch(token or "") or len(f"a:c:{token}".encode()) > CALLBACK_MAX:
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

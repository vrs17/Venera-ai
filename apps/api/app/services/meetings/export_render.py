"""Yig'ilish hujjatini DOCX (python-docx) va PDF (reportlab Platypus) ga chizish.

Kirish - `export.Document` (formatdan mustaqil bloklar); mazmunni bu modul YIG'MAYDI,
faqat chizadi. Shuning uchun DOCX, PDF, MD va TXT da bo'limlar bir xil.

NEGA KUTUBXONALAR FUNKSIYA ICHIDA import qilinadi. `python-docx` va `reportlab` -
yangi bog'liqlik (2026-10-10). Server `pip install` qilinmasdan yangilansa, butun API
ko'tarilmay qolmasin: faqat shu format 503 (`docx_unavailable` / `pdf_unavailable`)
qaytaradi, MD/TXT va qolgan hamma narsa ishlayveradi.

PDF SHRIFTI - DejaVu Sans (`MEETINGS_EXPORT_FONT_DIR`). reportlab'ning o'z shriftlari
(Helvetica) kirill va o'zbek `o'`/`g'` (U+02BB) harflarini chizmaydi - "qora qutilar"
chiqadi. Fayl yo'q bo'lsa jim Helvetica'ga tushmaymiz: aniq 503 `pdf_unavailable`.
Tarmoq ham, LibreOffice ham yo'q - hammasi shu jarayonda.
"""

from __future__ import annotations

import io
import logging
import threading

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .export import BRAND, WORD_LANGS, Document, RenderUnavailable, xml_safe

log = logging.getLogger(__name__)

#: Ro'yxatga olingan shrift nomlari (reportlab ichida). Fayl - `DejaVuSans*.ttf`.
FONT = "BarnoSans"
FONT_BOLD = "BarnoSans-Bold"
REGULAR_FILE = "DejaVuSans.ttf"
BOLD_FILE = "DejaVuSans-Bold.ttf"
DEFAULT_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

#: Word hujjati shrifti. NEGA Arial: Word, LibreOffice (Liberation Sans), Google Docs va
#: telefondagi WPS da bor, kirillni chizadi; python-docx shablonining Cambria/Calibri mavzu
#: shriftlari esa boshqa dasturlarda turlicha almashtiriladi va PDF bilan uslub mos kelmaydi.
DOCX_FONT = "Arial"

_font_lock = threading.Lock()
_font_key: tuple[str, str] | None = None
#: reportlab'ning shrift va TTF qism-to'plam holati jarayon uchun umumiy: ikki PDF bir
#: vaqtda yig'ilmasin. NEGA kutish chegarasi bilan: endpoint sync - kutayotgan har so'rov
#: umumiy threadpool ipini band qiladi; navbat cheksiz bo'lsa qolgan API ipsiz qolardi.
#: Odatda bunga yetib kelinmaydi (`service._export_slot` bir vaqtdagi eksportlarni cheklaydi).
_pdf_lock = threading.Lock()
PDF_WAIT_SEC = 30.0

# Ranglar: oq qog'ozda bosilganda ham o'qiladigan neytral palitra.
_INK = "#111827"
_MUTED = "#6B7280"
_ACCENT = "#3730A3"
_RULE = "#D1D5DB"
_HEAD_BG = "#EEF2FF"
_WARN = "#B45309"
_QUOTE = "#374151"


# --- DOCX ---------------------------------------------------------------------------------------


def _docx_style(d: Any, doc: Document) -> None:
    """Shablon uslublarini PDF ga moslash: bitta sans shrift, indigo sarlavhalar, ixcham
    oraliqlar va hujjat tili. python-docx shabloni o'zgarishsiz qolsa matn Cambria'da,
    sarlavhalar Word-2010 ko'k rangida, Title ostida ko'k chiziq va HAR qisqa bo'lim oldidan
    24 pt bo'shliq - 16 bo'limli hisobot cho'zilib ketardi."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    def fonts(rpr: Any) -> None:
        # Mavzu atributlari (`asciiTheme` ...) oddiy nomdan USTUN turadi - ularni o'chirmasak
        # Word baribir Cambria/Calibri ni oladi.
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.insert(0, rfonts)
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            rfonts.attrib.pop(qn(attr), None)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(qn(attr), DOCX_FONT)

    defaults = d.styles.element.find(qn("w:docDefaults"))
    rpr = defaults.find(qn("w:rPrDefault")).find(qn("w:rPr"))
    fonts(rpr)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), WORD_LANGS.get(doc.text_lang or doc.lang, "en-US"))

    ink, accent = RGBColor.from_string(_INK[1:]), RGBColor.from_string(_ACCENT[1:])
    normal = d.styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = ink
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.15
    for name, size, color, before, after in (("Title", 19, ink, 0, 6), ("Heading 1", 13.5, accent, 14, 3),
                                             ("Heading 2", 11, ink, 8, 1)):
        style = d.styles[name]
        fonts(style.element.get_or_add_rPr())
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = color
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
    title_ppr = d.styles["Title"].element.pPr
    border = title_ppr.find(qn("w:pBdr")) if title_ppr is not None else None
    if border is not None:
        title_ppr.remove(border)
    quote = d.styles["Quote"]
    quote.font.color.rgb = RGBColor.from_string(_QUOTE[1:])
    quote.paragraph_format.left_indent = Pt(12)


def docx_bytes(doc: Document) -> bytes:
    try:
        from docx import Document as DocxDocument
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Pt, RGBColor
    except ImportError as exc:                                   # pragma: no cover - o'rnatilmagan server
        raise RenderUnavailable("docx_unavailable", "python-docx o'rnatilmagan") from exc

    d = DocxDocument()
    section = d.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.0)
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.8)
    usable = section.page_width - section.left_margin - section.right_margin

    props = d.core_properties
    # 255 - python-docx chegarasi (oshsa ValueError va sarlavha logga tushardi).
    props.title = xml_safe(doc.title)[:255]
    props.author = BRAND
    props.last_modified_by = BRAND
    props.comments = ""
    props.language = WORD_LANGS.get(doc.text_lang or doc.lang, "en-US")
    props.created = props.modified = datetime.now(timezone.utc).replace(tzinfo=None)
    _docx_style(d, doc)

    muted = RGBColor.from_string(_MUTED[1:])
    warn = RGBColor.from_string(_WARN[1:])

    def add(paragraph: Any, text: str, *, bold: bool = False, italic: bool = False, color: Any = None,
            size: float | None = None, no_proof: bool = False) -> Any:
        """Bitta run. HAR matn `xml_safe` dan o'tadi: yig'uvchi biror joyda tozalashni unutsa
        ham (masalan, boshqaruv belgili spiker nomi) lxml ValueError -> 500 bo'lmasin."""
        run = paragraph.add_run(xml_safe(text))
        if bold:
            run.bold = True
        if italic:
            run.italic = True
        if color is not None:
            run.font.color.rgb = color
        if size:
            run.font.size = Pt(size)
        if no_proof:
            run.font.no_proof = True
        return run

    def lines_into(paragraph: Any, text: str, **kw: Any) -> None:
        """Ko'p qatorli matn - bitta paragraf, qatorlar orasida yumshoq uzilish (kuzatuv xabari)."""
        lines = text.split("\n")
        for i, line in enumerate(lines):
            run = add(paragraph, line, **kw)
            if i < len(lines) - 1:
                run.add_break()

    def heading(text: str, level: int) -> None:
        add(d.add_heading("", level=level), text)

    heading(doc.title, 0)
    for name, value in doc.meta:
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        add(p, f"{name}: ", bold=True)
        add(p, value)
    for note in doc.notes:
        lines_into(d.add_paragraph(), note, italic=True, color=warn)

    bullet_styles = ("List Bullet", "List Bullet 2", "List Bullet 3")
    for block in doc.blocks:
        kind = block["kind"]
        if kind == "h2":
            heading(block["text"], 1)
        elif kind == "h3":
            heading(block["text"], 2)
            if block.get("sub"):
                lines_into(d.add_paragraph(), block["sub"], italic=True, color=muted)
        elif kind == "p":
            lines_into(d.add_paragraph(), block["text"])
        elif kind == "muted":
            lines_into(d.add_paragraph(), block["text"], italic=True, color=muted)
        elif kind == "ul":
            for level, text in block["items"]:
                add(d.add_paragraph(style=bullet_styles[min(level, 2)]), text)
        elif kind == "quote":
            p = d.add_paragraph(style="Quote")
            add(p, f"«{block['text']}»")
            add(p, f" — {block['who']}", bold=True)
        elif kind == "table":
            _docx_table(d, block, usable, add, muted, warn, OxmlElement, qn)
            d.add_paragraph()
        elif kind == "tree":
            root = block["root"]
            add(d.add_paragraph(), root["text"], bold=True)

            def walk(node: dict[str, Any], depth: int) -> None:
                add(d.add_paragraph(style=bullet_styles[min(depth, 2)]), node["text"], bold=depth == 0)
                for child in node["children"]:
                    walk(child, depth + 1)
            for branch in root["children"]:
                walk(branch, 0)
        elif kind == "transcript":
            for stamp, who, text in block["lines"]:
                p = d.add_paragraph()
                p.paragraph_format.space_after = Pt(3)
                add(p, f"[{stamp}] ", color=muted, size=9)
                if who:
                    add(p, f"{who}: ", bold=True)
                # Xom ASR matni (o'zbek-rus aralash) - imlo tekshiruvi faqat qizil chiziq beradi.
                add(p, text, no_proof=True)

    # Pastki yozuv: "Barno AI · Yaratildi: ..." va "sahifa / jami" (Word o'zi hisoblaydi).
    foot = section.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add(foot, f"{doc.footer} · ", size=8, color=muted)

    def field(instr: str) -> None:
        simple = OxmlElement("w:fldSimple")
        simple.set(qn("w:instr"), instr)
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "1"
        run.append(text)
        simple.append(run)
        foot._p.append(simple)

    field("PAGE")
    add(foot, " / ", size=8, color=muted)
    field("NUMPAGES")

    buffer = io.BytesIO()
    d.save(buffer)
    return buffer.getvalue()


def _docx_table(d: Any, block: dict[str, Any], usable: int, add: Any, muted: Any, warn: Any,
                OxmlElement: Any, qn: Any) -> None:
    """Vazifalar jadvali. NEGA ustun kengligi UCH joyda: Word katak kengligini (`tcW`)
    o'qiydi, LibreOffice, Google Docs va telefondagi WPS esa `tblGrid/gridCol` ni - faqat
    katakka yozilsa ular 6 ta TENG ustun chizardi (keng "№", siqilgan "Vazifa")."""
    from docx.shared import Pt

    head, rows, widths = block["head"], block["rows"], block["widths"]
    muted_rows = set(block.get("muted") or [])
    table = d.add_table(rows=1, cols=len(head))
    table.style = "Table Grid"
    table.autofit = False                                       # w:tblLayout fixed
    total = float(sum(widths))
    col_w = [int(usable * w / total) for w in widths]
    for i, width in enumerate(col_w):
        table.columns[i].width = width                          # w:gridCol
    tbl_w = table._tbl.tblPr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        table._tbl.tblPr.append(tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(sum(col_w) // 635))               # EMU -> twip

    def fill(cell: Any, text: str, width: int, **kw: Any) -> None:
        cell.width = width                                      # w:tcW
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_after = Pt(0)
        first, *rest = text.split("\n")
        run = add(paragraph, first, size=9, **kw)
        for extra in rest:
            # Katakdagi qo'shimcha qator - ogohlantirish ("⚠ aniqlashtirish kerak").
            run.add_break()
            run = add(paragraph, extra, size=9, color=warn)

    for i, text in enumerate(head):
        cell = table.rows[0].cells[i]
        fill(cell, text, col_w[i], bold=True)
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), _HEAD_BG[1:])
        cell._tc.get_or_add_tcPr().append(shading)
    # Sarlavha qatori har sahifada takrorlansin (uzun jadval).
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    table.rows[0]._tr.get_or_add_trPr().append(header)
    for index, row in enumerate(rows):
        cells = table.add_row().cells
        for i, text in enumerate(row):
            fill(cells[i], text, col_w[i], color=muted if index in muted_rows else None)


# --- PDF ----------------------------------------------------------------------------------------


def _register_fonts(font_dir: Path) -> None:
    """DejaVu Sans'ni reportlab'ga BIR MARTA ro'yxatga oladi (papka o'zgarsa - qayta).
    Oddiy shrift yo'q - 503; qalini yo'q bo'lsa oddiysi qalin o'rnida ham ishlatiladi.
    `_pdf_lock` ICHIDA chaqiriladi: papka o'zgarib qayta ro'yxatga olinayotganda boshqa ip
    yarim yig'ilgan PDF ga ikki xil TTFont aralashtirmasin."""
    global _font_key
    regular, bold = font_dir / REGULAR_FILE, font_dir / BOLD_FILE
    if not regular.is_file():
        raise RenderUnavailable("pdf_unavailable", f"shrift topilmadi: {regular}")
    if not bold.is_file():
        bold = regular
    key = (str(regular), str(bold))
    with _font_lock:
        if _font_key == key:
            return
        try:
            from reportlab.lib.fonts import addMapping
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            pdfmetrics.registerFont(TTFont(FONT, str(regular)))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))
            # `<b>` teglari qalin shriftga o'tsin (kursiv yo'q - oddiysi).
            addMapping(FONT, 0, 0, FONT)
            addMapping(FONT, 1, 0, FONT_BOLD)
            addMapping(FONT, 0, 1, FONT)
            addMapping(FONT, 1, 1, FONT_BOLD)
        except Exception as exc:                                 # noqa: BLE001 - buzilgan TTF
            raise RenderUnavailable("pdf_unavailable", f"shrift o'qilmadi ({type(exc).__name__})") from exc
        _font_key = key


def _x(text: str) -> str:
    """reportlab `Paragraph` mini-HTML: `&`, `<`, `>` qochiriladi, qator - `<br/>`."""
    return escape(xml_safe(text)).replace("\n", "<br/>")


def pdf_bytes(doc: Document, font_dir: Path | None = None, *, wait: float | None = None) -> bytes:
    try:
        from reportlab.platypus.doctemplate import LayoutError
    except ImportError as exc:                                   # pragma: no cover - o'rnatilmagan server
        raise RenderUnavailable("pdf_unavailable", "reportlab o'rnatilmagan") from exc
    if not _pdf_lock.acquire(timeout=PDF_WAIT_SEC if wait is None else wait):
        raise RenderUnavailable("export_busy", "PDF navbati to'la")
    try:
        _register_fonts(font_dir or DEFAULT_FONT_DIR)
        try:
            return _build_pdf(doc, tables=True)
        except LayoutError:
            # Juda baland jadval qatori sahifaga sig'madi: jadvalsiz (ro'yxat) qayta - fayl
            # baribir berilsin, 500 emas.
            log.info("Yig'ilish PDF: jadval sig'madi - ro'yxat ko'rinishida qayta chizildi")
            return _build_pdf(doc, tables=False)
    finally:
        _pdf_lock.release()


def _build_pdf(doc: Document, *, tables: bool) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import (HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    ink, muted, accent = colors.HexColor(_INK), colors.HexColor(_MUTED), colors.HexColor(_ACCENT)
    margin_x = 18 * mm

    def style(name: str, **kw: Any) -> ParagraphStyle:
        base = {"fontName": FONT, "fontSize": 10, "leading": 14, "textColor": ink, "splitLongWords": 1}
        base.update(kw)
        return ParagraphStyle(name, **base)

    s_title = style("title", fontName=FONT_BOLD, fontSize=19, leading=24, spaceAfter=6)
    s_meta = style("meta", fontSize=9.5, leading=13.5, textColor=muted)
    s_note = style("note", fontSize=9.5, leading=13, textColor=colors.HexColor(_WARN), spaceBefore=4)
    # `keepWithNext`: sarlavha (va xarita ildizi) sahifa oxirida o'z mazmunisiz yolg'iz qolmasin.
    s_h2 = style("h2", fontName=FONT_BOLD, fontSize=13.5, leading=17, textColor=accent, spaceBefore=14,
                 spaceAfter=2, keepWithNext=1)
    s_h3 = style("h3", fontName=FONT_BOLD, fontSize=11, leading=14.5, spaceBefore=8, spaceAfter=1, keepWithNext=1)
    s_sub = style("sub", fontSize=8.5, leading=11, textColor=muted, spaceAfter=3, keepWithNext=1)
    s_body = style("body", spaceAfter=5)
    s_muted = style("muted", fontSize=9, leading=12, textColor=muted, spaceAfter=4)
    s_quote = style("quote", leftIndent=12, textColor=colors.HexColor(_QUOTE), spaceAfter=5)
    s_cell = style("cell", fontSize=8.8, leading=11.5)
    s_cell_done = style("cell_done", fontSize=8.8, leading=11.5, textColor=muted)
    s_head = style("head", fontName=FONT_BOLD, fontSize=8.8, leading=11.5)
    s_line = style("line", fontSize=9.2, leading=12.6, spaceAfter=3)
    s_root = style("root", fontName=FONT_BOLD, fontSize=12, leading=16, textColor=accent, spaceAfter=3,
                   keepWithNext=1)
    bullets = [style(f"b{i}", leftIndent=14 + 14 * i, bulletIndent=3 + 14 * i, spaceAfter=2.5,
                     bulletFontName=FONT, bulletColor=accent if i == 0 else muted) for i in range(4)]
    marks = ("•", "◦", "▪", "–")
    tree_marks = ("●", "○", "▪", "–")

    def rule() -> HRFlowable:
        line = HRFlowable(width="100%", thickness=0.6, color=colors.HexColor(_RULE), spaceBefore=1, spaceAfter=6)
        line.keepWithNext = 1
        return line

    def cell_html(text: str) -> str:
        # Katakdagi qo'shimcha qatorlar - ogohlantirish ("⚠ aniqlashtirish kerak").
        first, *rest = text.split("\n")
        return _x(first) + "".join(f"<br/><font color='{_WARN}'>{_x(line)}</font>" for line in rest)

    story: list[Any] = [Paragraph(_x(doc.title), s_title)]
    for name, value in doc.meta:
        story.append(Paragraph(f"<b>{_x(name)}:</b> {_x(value)}", s_meta))
    for note in doc.notes:
        story.append(Paragraph(_x(note), s_note))
    story.append(Spacer(1, 4))

    for block in doc.blocks:
        kind = block["kind"]
        if kind == "h2":
            story += [Paragraph(_x(block["text"]), s_h2), rule()]
        elif kind == "h3":
            story.append(Paragraph(_x(block["text"]), s_h3))
            if block.get("sub"):
                story.append(Paragraph(_x(block["sub"]), s_sub))
        elif kind == "p":
            story.append(Paragraph(_x(block["text"]), s_body))
        elif kind == "muted":
            story.append(Paragraph(_x(block["text"]), s_muted))
        elif kind == "ul":
            for level, text in block["items"]:
                level = min(level, 3)
                story.append(Paragraph(_x(text), bullets[level], bulletText=marks[level]))
            story.append(Spacer(1, 3))
        elif kind == "quote":
            story.append(Paragraph(f"«{_x(block['text'])}» — <b>{_x(block['who'])}</b>", s_quote))
        elif kind == "table":
            head, rows = block["head"], block["rows"]
            done = set(block.get("muted") or [])
            if tables:
                total = float(sum(block["widths"]))
                # Ramka (Frame) ichki chetlari 6 pt dan: jadval matn chizig'idan chiqib ketmasin.
                width = A4[0] - 2 * margin_x - 12
                data = [[Paragraph(_x(h), s_head) for h in head]]
                data += [[Paragraph(cell_html(c), s_cell_done if i in done else s_cell) for c in row]
                         for i, row in enumerate(rows)]
                table = Table(data, colWidths=[width * w / total for w in block["widths"]], repeatRows=1)
                table.setStyle(TableStyle([
                    # Kataklar Paragraph, lekin jadvalning o'z default shrifti Helvetica - u ham DejaVu.
                    ("FONTNAME", (0, 0), (-1, -1), FONT),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_HEAD_BG)),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(_RULE)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]))
                story += [table, Spacer(1, 6)]
            else:
                for row in rows:
                    extra = " · ".join(f"{head[i]}: {row[i]}".replace("\n", " · ") for i in range(2, len(row))
                                       if row[i])
                    text = f"{_x(row[1])}" + (f"<br/><font color='{_MUTED}'>{_x(extra)}</font>" if extra else "")
                    story.append(Paragraph(text, bullets[0], bulletText=f"{row[0]}."))
        elif kind == "tree":
            root = block["root"]
            # Bo'lim sarlavhasi va ildiz BIRINCHI shox bilan bitta guruhda: Platypus `keepWithNext`
            # zanjiri KeepTogether'dan o'tmaydi - aks holda "Aqliy xarita" va ildiz sahifa oxirida
            # yolg'iz qolib, shoxlar keyingi sahifadan boshlanardi.
            lead: list[Any] = []
            while story and story[-1].getKeepWithNext():
                lead.insert(0, story.pop())
            lead.append(Paragraph(_x(root["text"]), s_root))

            def walk(node: dict[str, Any], depth: int, out: list[Any]) -> None:
                level = min(depth, 3)
                text = f"<b>{_x(node['text'])}</b>" if depth == 0 else _x(node["text"])
                out.append(Paragraph(text, bullets[level], bulletText=tree_marks[level]))
                for child in node["children"]:
                    walk(child, depth + 1, out)
            for branch in root["children"]:
                # Shox (mavzu + uning fikrlari) sahifalar orasida bo'linmasin: "Reliz sanasi"
                # bir sahifada, uning bandlari keyingisida qolsa xarita o'qilmaydi. Sahifadan
                # baland shox baribir bo'linadi (KeepTogether shunda oddiy ro'yxat).
                flow, lead = lead, []
                walk(branch, 0, flow)
                story += [KeepTogether(flow), Spacer(1, 3)]
            story += lead                                       # shoxsiz daraxt (bo'lmaydi, lekin)
        elif kind == "transcript":
            for stamp, who, text in block["lines"]:
                head = f"<font color='{_MUTED}'>[{_x(stamp)}]</font> "
                if who:
                    head += f"<b>{_x(who)}:</b> "
                story.append(Paragraph(head + _x(text), s_line))

    class NumberedCanvas(Canvas):
        """"3 / 12" - jami sahifalar soni faqat oxirida ma'lum. Har sahifa raqami alohida
        PDF shakli (form XObject) sifatida OXIRIDA chiziladi: sahifalarni xotirada ushlab
        turish yoki hujjatni ikki marta yig'ish shart emas (va xatcho'plar to'g'ri sahifaga)."""

        pages = 0

        def save(self) -> None:
            for number in range(1, self.pages + 1):
                self.beginForm(f"barnoPage{number}")
                self.setFont(FONT, 8)
                self.setFillColor(muted)
                self.drawRightString(A4[0] - margin_x, 10 * mm, f"{number} / {self.pages}")
                self.endForm()
            super().save()

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(muted)
        canvas.drawString(margin_x, 10 * mm, doc.footer)
        canvas.pages = max(canvas.pages, document.page)
        canvas.doForm(f"barnoPage{document.page}")
        canvas.restoreState()

    class BarnoDocTemplate(SimpleDocTemplate):
        """Har bo'lim sarlavhasi - PDF xatcho'pi (outline): 3 soatlik yig'ilishning o'nlab
        sahifali transkriptida telefonda "Vazifalar" yoki "Transkript" ga bir bosishda o'tish."""

        def afterFlowable(self, flowable: Any) -> None:
            if isinstance(flowable, Paragraph) and flowable.style.name == "h2":
                key = f"section{id(flowable)}"
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(xml_safe(flowable.getPlainText()), key, level=0)

    buffer = io.BytesIO()
    # `initialFontName`: aks holda kanvas Helvetica'ni ham faylga qo'shib qo'yadi (ishlatilmasa ham).
    pdf = BarnoDocTemplate(buffer, pagesize=A4, leftMargin=margin_x, rightMargin=margin_x, topMargin=16 * mm,
                           bottomMargin=18 * mm, title=doc.title, author=BRAND, creator=BRAND, subject=doc.title,
                           lang=WORD_LANGS.get(doc.text_lang or doc.lang, doc.lang), initialFontName=FONT)
    pdf.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=NumberedCanvas)
    return buffer.getvalue()

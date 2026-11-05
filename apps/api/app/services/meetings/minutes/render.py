"""Bayonnoma `MinutesDoc` -> DOCX (python-docx), PDF (reportlab), Markdown.

SHARTNOMA:

    def render(doc: MinutesDoc, fmt: str, *, font_dir=None) -> bytes      # docx | pdf | md
    def docx_bytes(doc) -> bytes
    def pdf_bytes(doc, font_dir: Path | None = None) -> bytes
    def markdown(doc) -> str

NAMUNA KO'RINISHI (ega qarori: Letter): sahifa US Letter (8.5 x 11 in), chetlar 2.0 sm (chap 2.5 sm,
o'ng 1.5 sm); DOCX shrifti Arial 13 pt (asosiy matn justify, 1-qator chekinishi 1 sm), tasdiq bloki
Times New Roman 12 pt o'ngda; sarlavha bloki markazda qalin ("Б А Ё Н И" 14 pt); bo'lim sarlavhasi
(`section`) qalin, to'q ko'k #1F3864, tagi chizilgan; band raqami, muddati va mas'ullari qalin (runs);
kichik bandlar "- " bilan chap chekinish; sahifa raqami va pastki yozuv YO'Q (namunada yo'q); hujjat
tili `doc.text_lang` (`w:lang`, PDF `/Lang`); `core_properties.author = export.BRAND`.

PDF: reportlab Platypus, shrift `export_render._register_fonts(font_dir)` (DejaVu Sans; Times
yo'q - DejaVu Serif bo'lsa tasdiq blokida, aks holda Sans), Letter, xuddi shu bloklar. Kutubxona
yo'q bo'lsa `export.RenderUnavailable("docx_unavailable" | "pdf_unavailable")`; PDF quloqchin
(`export_render._pdf_lock`) shu yerda ham - reportlab shrift holati jarayon uchun umumiy.

Hamma matn `export.xml_safe` dan o'tadi.

NEGA ALOHIDA CHIZUVCHI (`export_render` emas). Xulosa hujjati - hisobot ko'rinishi (A4, indigo
sarlavhalar, jadval, pastki yozuv, sahifa raqami); bayonnoma - rasmiy blank ko'rinishi (Letter, Arial,
o'ngga tasdiq bloki, ikki ustunli sana/shahar, rim raqamli bo'limlar, PASTKI YOZUVSIZ). Bloklar ham
boshqa (`approval`, `two_col`, `section`, `item` run'lari). Umumiy qismlar - shrift ro'yxati, quloqchin,
`_x` qochirish - `export_render` dan olinadi, nusxa qilinmaydi.

NEGA NORMAL USLUBDA MAVZU SHRIFT ATRIBUTLARI O'CHIRILADI. python-docx shablonida `asciiTheme`/`hAnsiTheme`
oddiy `w:ascii` nomidan USTUN: ularni o'chirmasak Word Arial o'rniga Calibri ko'rsatadi (xuddi
`export_render._docx_style.fonts` dagidek).

NEGA SANA/SHAHAR JADVAL (tab emas). O'ng tab to'xtash joyi Word'da yaxshi, LibreOffice/Google Docs/WPS da
har xil chiziladi; chegarasiz 2x1 jadval hamma joyda bir xil: sana chapda, shahar o'ngda.
"""

from __future__ import annotations

import io
import logging

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import export_render
from ..export import BRAND, RenderUnavailable, xml_safe
from .compose import MinutesDoc

log = logging.getLogger(__name__)

#: Word shriftlari (ega qarori: namunadagidek). PDF da ikkalasi o'rniga DejaVu Sans/Serif.
BODY_FONT = "Arial"
APPROVAL_FONT = "Times New Roman"
BODY_PT = 13
APPROVAL_PT = 12
DOC_PT = 14
MUTED_PT = 10
#: Bo'lim sarlavhasi rangi (namunadagi to'q ko'k) va izoh kulrangi.
NAVY = "1F3864"
GRAY = "6B7280"
#: PDF tasdiq bloki uchun serif shrift (DejaVu Serif, bo'lsa) - reportlab ichidagi nom va fayl.
SERIF = "BarnoSerif"
SERIF_FILE = "DejaVuSerif.ttf"
#: 1-qator chekinishi va kichik band chekinishi (pt): 1 sm ~ 28 pt, 1.5 sm ~ 42 pt.
INDENT_PT = 28
SUB_INDENT_PT = 42

_serif_key: str | None = None
#: `w:tblPr` bolalarining sxema tartibi - `tblW` va `tblBorders` dan KEYIN keladiganlar. NEGA: Word tartib
#: buzilgan jadval xususiyatlarini "o'qib bo'lmaydigan mazmun" deb hisoblashi mumkin; `append` o'rniga
#: `insert_element_before` bilan o'z joyiga qo'yiladi.
_TBLPR_AFTER_W = ("w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar",
                  "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange")
_TBLPR_AFTER_BORDERS = _TBLPR_AFTER_W[4:]


def render(doc: MinutesDoc, fmt: str, *, font_dir: Path | str | None = None) -> bytes:
    """Hujjat -> fayl baytlari. DOCX/PDF kutubxonalari faqat kerak bo'lganda yuklanadi:
    o'rnatilmagan serverda butun ilova emas, faqat shu format 503 bo'ladi."""
    if fmt == "md":
        return markdown(doc).encode("utf-8")
    if fmt == "docx":
        return docx_bytes(doc)
    if fmt == "pdf":
        return pdf_bytes(doc, Path(font_dir) if font_dir else None)
    raise ValueError(fmt)


# --- DOCX ---------------------------------------------------------------------------------------


def _rfonts(rpr: Any, name: str, OxmlElement: Any, qn: Any) -> None:
    """`w:rFonts` to'rt yozuv uchun ham `name`; mavzu atributlari o'chiriladi (ular oddiy nomdan ustun)."""
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), name)


def _size(rpr: Any, points: float, OxmlElement: Any, qn: Any) -> None:
    """`w:sz` va `w:szCs` (yarim punktlarda) - python-docx `font.size` faqat `w:sz` ni yozadi, `szCs`
    (murakkab yozuvlar o'lchami) sxema tartibida `sz` dan keyin turadi."""
    value = str(int(round(points * 2)))
    sz = rpr.get_or_add_sz()
    sz.set(qn("w:val"), value)
    sz_cs = rpr.find(qn("w:szCs"))
    if sz_cs is None:
        sz_cs = OxmlElement("w:szCs")
        sz.addnext(sz_cs)
    sz_cs.set(qn("w:val"), value)


def _docx_style(d: Any, doc: MinutesDoc) -> None:
    """Shablon defaultlari -> Arial 13, oraliq 6 pt, qator oralig'i 1.0, hujjat tili."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    defaults = d.styles.element.find(qn("w:docDefaults"))
    rpr = defaults.find(qn("w:rPrDefault")).find(qn("w:rPr"))
    _rfonts(rpr, BODY_FONT, OxmlElement, qn)
    _size(rpr, BODY_PT, OxmlElement, qn)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), doc.text_lang)
    lang.set(qn("w:eastAsia"), doc.text_lang)

    normal = d.styles["Normal"]
    _rfonts(normal.element.get_or_add_rPr(), BODY_FONT, OxmlElement, qn)
    normal.font.name = BODY_FONT
    normal.font.size = Pt(BODY_PT)
    _size(normal.element.get_or_add_rPr(), BODY_PT, OxmlElement, qn)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.0


def _no_borders(table: Any, OxmlElement: Any, qn: Any) -> None:
    """Jadval chegaralari YO'Q (sana/shahar qatori ko'rinmas ustunlar) - Word ham, LibreOffice ham."""
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.insert_element_before(borders, *_TBLPR_AFTER_BORDERS)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "nil")


def docx_bytes(doc: MinutesDoc) -> bytes:
    try:
        from docx import Document as DocxDocument
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Inches, Pt, RGBColor
    except ImportError as exc:                                   # pragma: no cover - o'rnatilmagan server
        raise RenderUnavailable("docx_unavailable", "python-docx o'rnatilmagan") from exc

    d = DocxDocument()
    section = d.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Cm(2.0)
    section.left_margin, section.right_margin = Cm(2.5), Cm(1.5)
    usable = section.page_width - section.left_margin - section.right_margin

    props = d.core_properties
    # 255 - python-docx chegarasi (oshsa ValueError va sarlavha logga tushardi).
    props.title = xml_safe(doc.title)[:255]
    props.author = BRAND
    props.last_modified_by = BRAND
    props.comments = ""
    props.language = doc.text_lang
    props.created = props.modified = datetime.now(timezone.utc).replace(tzinfo=None)
    _docx_style(d, doc)

    navy, gray = RGBColor.from_string(NAVY), RGBColor.from_string(GRAY)
    LEFT, RIGHT, CENTER, JUSTIFY = (WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.CENTER,
                                    WD_ALIGN_PARAGRAPH.JUSTIFY)

    def add(paragraph: Any, text: str, *, bold: bool = False, italic: bool = False, underline: bool = False,
            color: Any = None, size: float | None = None, font: str | None = None) -> Any:
        """Bitta run. HAR matn `xml_safe` dan o'tadi: yig'uvchi biror joyda tozalashni unutsa ham
        lxml ValueError -> 500 bo'lmasin."""
        run = paragraph.add_run(xml_safe(text))
        if bold:
            run.bold = True
        if italic:
            run.italic = True
        if underline:
            run.underline = True
        if color is not None:
            run.font.color.rgb = color
        if size:
            run.font.size = Pt(size)
            _size(run._element.get_or_add_rPr(), size, OxmlElement, qn)
        if font:
            _rfonts(run._element.get_or_add_rPr(), font, OxmlElement, qn)
        return run

    def runs_into(paragraph: Any, runs: list[Any]) -> None:
        for text, flags in runs:
            flags = flags or {}
            add(paragraph, text, bold=bool(flags.get("bold")), italic=bool(flags.get("italic")))

    def lines_into(paragraph: Any, text: str, **kw: Any) -> None:
        """Ko'p qatorli matn - bitta paragraf, qatorlar orasida yumshoq uzilish (izohlar ro'yxati)."""
        lines = xml_safe(text).split("\n")
        for i, line in enumerate(lines):
            run = add(paragraph, line, **kw)
            if i < len(lines) - 1:
                run.add_break()

    def paragraph(align: Any = None, *, indent: bool = False, left: Any = None, before: float | None = None,
                  after: float | None = None, keep_next: bool = False) -> Any:
        p = d.add_paragraph()
        fmt = p.paragraph_format
        if align is not None:
            p.alignment = align
        if indent:
            fmt.first_line_indent = Cm(1.0)
        if left is not None:
            fmt.left_indent = left
        if before is not None:
            fmt.space_before = Pt(before)
        if after is not None:
            fmt.space_after = Pt(after)
        if keep_next:
            fmt.keep_with_next = True
        return p

    for block in doc.blocks:
        kind = block["kind"]
        if kind == "approval":
            lines = block["lines"]
            for i, line in enumerate(lines):
                last = i == len(lines) - 1
                add(paragraph(RIGHT, after=6 if last else 0), line, size=APPROVAL_PT, font=APPROVAL_FONT)
        elif kind == "spacer":
            d.add_paragraph()
        elif kind == "title":
            lines = block["lines"]
            doc_line = block.get("doc") or lines[-1]
            for i, line in enumerate(lines):
                big = line == doc_line                 # hujjat nomi ("Б А Ё Н И" / "ПРОТОКОЛ"), 14 pt
                add(paragraph(CENTER, after=6 if i == len(lines) - 1 else 0, keep_next=True), line, bold=True,
                    size=DOC_PT if big else None)
        elif kind == "two_col":
            table = d.add_table(rows=1, cols=2)
            table.autofit = False                                 # w:tblLayout fixed
            _no_borders(table, OxmlElement, qn)
            half = int(usable // 2)
            for i, (text, align) in enumerate(((block["left"], LEFT), (block["right"], RIGHT))):
                table.columns[i].width = half                     # w:gridCol (LibreOffice, Google Docs)
                cell = table.rows[0].cells[i]
                cell.width = half                                 # w:tcW (Word)
                p = cell.paragraphs[0]
                p.alignment = align
                p.paragraph_format.space_after = Pt(6)
                add(p, text)
            tbl_pr = table._tbl.tblPr
            tbl_w = tbl_pr.find(qn("w:tblW"))
            if tbl_w is None:
                tbl_w = OxmlElement("w:tblW")
                tbl_pr.insert_element_before(tbl_w, *_TBLPR_AFTER_W)
            tbl_w.set(qn("w:type"), "dxa")
            tbl_w.set(qn("w:w"), str((half * 2) // 635))          # EMU -> twip
        elif kind == "label":
            p = paragraph(JUSTIFY)
            add(p, block["label"], bold=True)
            if block.get("value"):
                add(p, f" {block['value']}")
        elif kind == "heading":
            add(paragraph(CENTER, before=12, after=6, keep_next=True), block["text"], bold=True)
        elif kind == "agenda":
            add(paragraph(CENTER, after=3), f"{block['number']} {block['text']}", bold=True)
        elif kind == "italic":
            add(paragraph(JUSTIFY, before=6), block["text"], italic=True)
        elif kind == "para":
            runs_into(paragraph(JUSTIFY, indent=bool(block.get("indent"))), block["runs"])
        elif kind == "section":
            add(paragraph(JUSTIFY, indent=True, before=6, keep_next=True), block["text"], bold=True, underline=True,
                color=navy)
        elif kind == "item":
            runs_into(paragraph(JUSTIFY, indent=True), block["runs"])
            for sub in block.get("sub") or []:
                add(paragraph(JUSTIFY, left=Cm(1.5), after=3), sub)
            if block.get("follow"):
                add(paragraph(JUSTIFY, indent=True), block["follow"])
        elif kind == "muted":
            lines_into(paragraph(JUSTIFY, before=6), block["text"], italic=True, color=gray, size=MUTED_PT)
        else:                                                      # noma'lum blok - yig'uvchi xatosi, jim o'tilmaydi
            raise ValueError(f"minutes.render: noma'lum blok {kind!r}")

    buffer = io.BytesIO()
    d.save(buffer)
    return buffer.getvalue()


# --- PDF ----------------------------------------------------------------------------------------


def _register_serif(font_dir: Path) -> str:
    """Tasdiq bloki shrifti: DejaVu Serif bo'lsa `SERIF` (bir marta ro'yxatga olinadi), aks holda
    `export_render.FONT`. `_pdf_lock` ICHIDA chaqiriladi (reportlab shrift holati umumiy)."""
    global _serif_key
    path = font_dir / SERIF_FILE
    if not path.is_file():
        return export_render.FONT
    key = str(path)
    if _serif_key == key:
        return SERIF
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont(SERIF, key))
    except Exception as exc:                                     # noqa: BLE001 - buzilgan TTF: Sans bilan davom
        log.info("Bayonnoma PDF: serif shrift o'qilmadi (%s) - DejaVu Sans", type(exc).__name__)
        return export_render.FONT
    _serif_key = key
    return SERIF


def pdf_bytes(doc: MinutesDoc, font_dir: Path | None = None, *, wait: float | None = None) -> bytes:
    try:
        from reportlab.platypus import SimpleDocTemplate  # noqa: F401 - mavjudligi tekshiriladi
    except ImportError as exc:                                   # pragma: no cover - o'rnatilmagan server
        raise RenderUnavailable("pdf_unavailable", "reportlab o'rnatilmagan") from exc
    if not export_render._pdf_lock.acquire(timeout=export_render.PDF_WAIT_SEC if wait is None else wait):
        raise RenderUnavailable("export_busy", "PDF navbati to'la")
    try:
        directory = Path(font_dir) if font_dir else export_render.DEFAULT_FONT_DIR
        export_render._register_fonts(directory)
        return _build_pdf(doc, _register_serif(directory))
    finally:
        export_render._pdf_lock.release()


def _runs_html(runs: list[Any]) -> str:
    """Run'lar -> reportlab mini-HTML (`<b>`, `<i>`); matn `export_render._x` bilan qochiriladi."""
    out: list[str] = []
    for text, flags in runs:
        flags = flags or {}
        html = export_render._x(text)
        if flags.get("bold"):
            html = f"<b>{html}</b>"
        if flags.get("italic"):
            html = f"<i>{html}</i>"
        out.append(html)
    return "".join(out)


def _build_pdf(doc: MinutesDoc, serif: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    FONT, FONT_BOLD, _x = export_render.FONT, export_render.FONT_BOLD, export_render._x
    navy, gray = colors.HexColor(f"#{NAVY}"), colors.HexColor(f"#{GRAY}")
    left_margin, right_margin, top_margin, bottom_margin = 2.5 * cm, 1.5 * cm, 2.0 * cm, 2.0 * cm

    def style(name: str, **kw: Any) -> ParagraphStyle:
        base = {"fontName": FONT, "fontSize": BODY_PT, "leading": 16, "textColor": colors.black,
                "splitLongWords": 1, "spaceAfter": 6}
        base.update(kw)
        return ParagraphStyle(name, **base)

    s_approval = style("approval", fontName=serif, fontSize=APPROVAL_PT, leading=14, alignment=TA_RIGHT, spaceAfter=0)
    s_approval_last = style("approval_last", parent=s_approval, spaceAfter=6)
    s_title = style("title", fontName=FONT_BOLD, alignment=TA_CENTER, spaceAfter=0, keepWithNext=1)
    s_doc = style("doc", fontName=FONT_BOLD, fontSize=DOC_PT, leading=17, alignment=TA_CENTER, keepWithNext=1)
    s_left = style("left", alignment=TA_LEFT)
    s_right = style("right", alignment=TA_RIGHT)
    s_label = style("label", alignment=TA_JUSTIFY)
    s_heading = style("heading", fontName=FONT_BOLD, alignment=TA_CENTER, spaceBefore=12, keepWithNext=1)
    s_agenda = style("agenda", fontName=FONT_BOLD, alignment=TA_CENTER, spaceAfter=3)
    s_italic = style("italic", alignment=TA_JUSTIFY, spaceBefore=6)
    s_body = style("body", alignment=TA_JUSTIFY, firstLineIndent=INDENT_PT)
    s_plain = style("plain", alignment=TA_JUSTIFY)
    s_section = style("section", fontName=FONT_BOLD, textColor=navy, alignment=TA_JUSTIFY, firstLineIndent=INDENT_PT,
                      spaceBefore=6, keepWithNext=1)
    s_sub = style("sub", alignment=TA_JUSTIFY, leftIndent=SUB_INDENT_PT, spaceAfter=3)
    s_muted = style("muted", fontSize=MUTED_PT, leading=12, textColor=gray, alignment=TA_JUSTIFY, spaceBefore=6,
                    spaceAfter=4)
    # Ramka (Frame) ichki chetlari 6 pt dan: jadval matn chizig'idan chiqib ketmasin.
    width = letter[0] - left_margin - right_margin - 12

    story: list[Any] = []
    for block in doc.blocks:
        kind = block["kind"]
        if kind == "approval":
            lines = block["lines"]
            for i, line in enumerate(lines):
                story.append(Paragraph(_x(line), s_approval_last if i == len(lines) - 1 else s_approval))
        elif kind == "spacer":
            story.append(Spacer(1, 12))
        elif kind == "title":
            lines = block["lines"]
            doc_line = block.get("doc") or lines[-1]
            for line in lines:
                story.append(Paragraph(_x(line), s_doc if line == doc_line else s_title))
        elif kind == "two_col":
            table = Table([[Paragraph(_x(block["left"]), s_left), Paragraph(_x(block["right"]), s_right)]],
                          colWidths=[width / 2, width / 2])
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), FONT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(table)
        elif kind == "label":
            value = f" {_x(block['value'])}" if block.get("value") else ""
            story.append(Paragraph(f"<b>{_x(block['label'])}</b>{value}", s_label))
        elif kind == "heading":
            story.append(Paragraph(_x(block["text"]), s_heading))
        elif kind == "agenda":
            story.append(Paragraph(f"{_x(block['number'])} {_x(block['text'])}", s_agenda))
        elif kind == "italic":
            # DejaVu kursivi ro'yxatda yo'q (`fonts-dejavu-core`): `<i>` oddiy shriftga tushadi - mazmun saqlanadi.
            story.append(Paragraph(f"<i>{_x(block['text'])}</i>", s_italic))
        elif kind == "para":
            story.append(Paragraph(_runs_html(block["runs"]), s_body if block.get("indent") else s_plain))
        elif kind == "section":
            story.append(Paragraph(f"<u>{_x(block['text'])}</u>", s_section))
        elif kind == "item":
            story.append(Paragraph(_runs_html(block["runs"]), s_body))
            for sub in block.get("sub") or []:
                story.append(Paragraph(_x(sub), s_sub))
            if block.get("follow"):
                story.append(Paragraph(_x(block["follow"]), s_body))
        elif kind == "muted":
            story.append(Paragraph(_x(block["text"]), s_muted))
        else:
            raise ValueError(f"minutes.render: noma'lum blok {kind!r}")

    buffer = io.BytesIO()
    title = xml_safe(doc.title)
    # `initialFontName`: aks holda kanvas Helvetica'ni ham faylga qo'shib qo'yadi (ishlatilmasa ham).
    # Pastki yozuv va sahifa raqami YO'Q (namunada yo'q) - `onFirstPage`/`onLaterPages` berilmaydi.
    pdf = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=left_margin, rightMargin=right_margin,
                            topMargin=top_margin, bottomMargin=bottom_margin, title=title, author=BRAND,
                            creator=BRAND, subject=title, lang=doc.text_lang, initialFontName=FONT)
    pdf.build(story)
    return buffer.getvalue()


# --- Markdown -----------------------------------------------------------------------------------


def _md_runs(runs: list[Any]) -> str:
    """Run'lar -> Markdown: qalin `**...**`, kursiv `_..._`; bo'shliqlar belgilardan TASHQARIDA
    ("12. " -> "**12.** ", aks holda `** 12. **` qalin bo'lmaydi)."""
    out: list[str] = []
    for text, flags in runs:
        flags = flags or {}
        text = xml_safe(text)
        core = text.strip()
        if not core or not (flags.get("bold") or flags.get("italic")):
            out.append(text)
            continue
        lead = text[:len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        if flags.get("bold"):
            core = f"**{core}**"
        if flags.get("italic"):
            core = f"_{core}_"
        out.append(f"{lead}{core}{trail}")
    return "".join(out)


def markdown(doc: MinutesDoc) -> str:
    """Ko'rish uchun Markdown: sarlavhalar oddiy qatorlar (`#` yo'q - hujjat sarlavhasi emas, blank),
    bandlar `**12.** ...`, bo'sh joylar `________` o'zgarmaydi (qochirilmaydi - Telegram/chatga
    ko'chirilganda teskari chiziqlar ko'rinib qolardi)."""
    out: list[str] = []
    previous = ""
    for block in doc.blocks:
        kind = block["kind"]
        if previous == "agenda" and kind != "agenda":
            out.append("")
        if kind == "approval" or kind == "title":
            out += [f"{xml_safe(line)}  " for line in block["lines"]] + [""]
        elif kind == "spacer":
            out.append("")
        elif kind == "two_col":
            out += [f"{xml_safe(block['left'])}    {xml_safe(block['right'])}", ""]
        elif kind == "label":
            value = f" {xml_safe(block['value'])}" if block.get("value") else ""
            out += [f"**{xml_safe(block['label'])}**{value}", ""]
        elif kind == "heading":
            out += [xml_safe(block["text"]), ""]
        elif kind == "agenda":
            out.append(f"{xml_safe(block['number'])} {xml_safe(block['text'])}")
        elif kind == "italic":
            out += [f"_{xml_safe(block['text'])}_", ""]
        elif kind == "para":
            out += [_md_runs(block["runs"]), ""]
        elif kind == "section":
            out += [f"**{xml_safe(block['text'])}**", ""]
        elif kind == "item":
            out.append(_md_runs(block["runs"]))
            out += [f"  {xml_safe(sub)}" for sub in block.get("sub") or []]
            if block.get("follow"):
                # Alohida paragraf: ro'yxatdan keyin bo'sh qatorsiz "Bunda, ..." oxirgi kichik bandga yopishardi.
                out.append("")
                out.append(xml_safe(block["follow"]))
            out.append("")
        elif kind == "muted":
            for line in xml_safe(block["text"]).split("\n"):
                out.append(f"- _{line[2:]}_" if line.startswith("- ") else f"_{line}_")
            out.append("")
        else:
            raise ValueError(f"minutes.render: noma'lum blok {kind!r}")
        previous = kind
    return "\n".join(out).rstrip() + "\n"

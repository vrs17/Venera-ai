"""Bayonnoma yig'uvchisi (`minutes/compose.py`) va chizuvchisi (`minutes/render.py`).

Tarmoqsiz, modelsiz: mazmun - `meetings_fakes.minutes_reply` (to'rt tilda, promptdagi chiqish tili
qatori bo'yicha) + `minutes._fill` qo'shadigan `quality`/`version`/`language`/`meeting` kalitlari.
Tekshiriladi: bloklar tartibi, bandlarning bo'limlar bo'ylab UZLUKSIZ raqamlanishi va nazorat bandi
oxirida, mas'ulsiz vazifada `BLANK`, rim raqamli bo'lim sarlavhasi, `[S#]` -> ism yoki `BLANK`;
DOCX (Letter, Arial 13, Times tasdiq bloki, to'q ko'k bo'lim, pastki yozuv yo'q), PDF (Letter,
DejaVu, `/Lang`, matn), Markdown (`**1.**`), boshqaruv belgilarining tozalanishi.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
import zlib

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt

from app.services.meetings import export, export_render
from app.services.meetings.minutes import compose, render, text
from app.services.meetings.minutes.text import BLANK
from meetings_fakes import minutes_reply, parse_lines

RECORDED_AT = 1762243200.0  # 2025-11-04 09:00 Toshkent
NOW = RECORDED_AT + 2 * 3600
#: S1 nomli, S2 nomsiz - token almashtirishning ikkala yo'li.
SPEAKERS = {"S1": {"id": "S1", "name": "Aziz Karimov", "talk_sec": 30.0},
            "S2": {"id": "S2", "name": None, "talk_sec": 20.0}}
NAMED = {"S1": {"id": "S1", "name": "Aziz Karimov"}, "S2": {"id": "S2", "name": "Dilnoza Rahimova"}}

#: PDF testlari tizim shriftiga bog'liq (`fonts-dejavu-core`): shriftsiz mashinada o'tkazib yuboriladi.
FONTS = (export_render.DEFAULT_FONT_DIR / export_render.REGULAR_FILE).is_file()
SERIF = (export_render.DEFAULT_FONT_DIR / render.SERIF_FILE).is_file()
needs_fonts = pytest.mark.skipif(not FONTS, reason="DejaVu shrifti yo'q (fonts-dejavu-core)")


# --- ma'lumot ---------------------------------------------------------------------------------------


def user_prompt(lang: str) -> str:
    """Promptning soxta modelga kerak qismi: chiqish tili qatori va `#id [vaqt] S# (Ism): matn` qatorlari.
    Oxirgi qator S2 niki: `minutes_reply` ikkinchi bandning mas'ulini OXIRGI qator spikeridan oladi."""
    return "\n".join([
        f"Output language: {text.OUTPUT_LANGUAGE[lang]}", "",
        "#1 [00:00] S1 (Aziz Karimov): Assalomu alaykum, hisobot bo'yicha boshlaymiz.",
        "#2 [00:06] S1 (Aziz Karimov): Narxni 15 mln so'm qilib belgilaymiz.",
        "#3 [00:14] S2: Men ikki kun ichida hisobotni tayyorlayman.",
    ])


def content(lang: str, *, warnings: list[str] | None = None, **top) -> dict:
    """Saqlanadigan mazmun: model javobi + `_write` qo'shadigan kalitlar."""
    user = user_prompt(lang)
    data = minutes_reply(parse_lines(user), user)
    data["quality"] = {"warnings": list(warnings or []), "strict": True}
    data["version"] = "minutes-1"
    data["language"] = lang
    data["meeting"] = {"recordedAt": "2025-11-04T09:00:00+05:00", "durationSec": 22.0, "speakerCount": 2}
    data.update(top)
    return data


def build(lang: str = "uz-cyrl", speakers: dict | None = SPEAKERS, title: str = "Ҳисобот йиғилиши",
          **top) -> compose.MinutesDoc:
    return compose.compose(content(lang, **top), lang=lang, title=title, speakers=speakers or {},
                           recorded_at=RECORDED_AT, now=NOW)


def kinds(doc: compose.MinutesDoc) -> list[str]:
    return [b["kind"] for b in doc.blocks]


def items(doc: compose.MinutesDoc) -> list[dict]:
    return [b for b in doc.blocks if b["kind"] == "item"]


def joined(block: dict) -> str:
    return "".join(t for t, _ in block["runs"])


def bold_runs(block: dict) -> list[str]:
    return [t for t, flags in block["runs"] if flags.get("bold")]


def docx_paragraphs(data: bytes):
    return Document(io.BytesIO(data)).paragraphs


def twips(length) -> int:
    """DOCX chetlar va chekinishlarni twip da saqlaydi (1/20 pt): `Cm(2.5)` qaytib o'qilganda 205 EMU
    farq qiladi - solishtirish twip da."""
    return round(int(length) / 635)


# --- PDF ni kutubxonasiz o'qish (`test_meetings_export` naqshi) -------------------------------------


def _pdf_objects(data: bytes) -> dict[int, tuple[bytes, bytes]]:
    out = {}
    for m in re.finditer(rb"(\d+) 0 obj\s*<<(.*?)>>\s*(?:stream\r?\n(.*?)endstream|endobj)", data, flags=re.S):
        head, raw = m.group(2), m.group(3) or b""
        if raw and b"/ASCII85Decode" in head:
            raw = raw.strip()
            raw = base64.a85decode(raw[:-2] if raw.endswith(b"~>") else raw)
        if raw and b"/FlateDecode" in head:
            raw = zlib.decompressobj().decompress(raw)
        out[int(m.group(1))] = (head, raw)
    return out


_PDF_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _pdf_string(raw: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(raw):
        ch = raw[i:i + 1]
        if ch != b"\\":
            out += ch
            i += 1
            continue
        nxt = raw[i + 1:i + 2]
        octal = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
        if octal:
            out.append(int(octal.group(), 8) & 0xFF)
            i += 1 + len(octal.group())
        else:
            out += _PDF_ESC.get(nxt, nxt)
            i += 2
    return bytes(out)


def pdf_text(data: bytes) -> str:
    """reportlab TTF qism-to'plamining ToUnicode xaritasi orqali matn (glif kodlari -> Unicode)."""
    objects = _pdf_objects(data)
    maps: dict[bytes, dict[int, str]] = {}
    for head, _ in objects.values():
        name = re.search(rb"/Name /(F\d+\+\d+)", head)
        ref = re.search(rb"/ToUnicode (\d+) 0 R", head)
        if name and ref:
            cmap = objects[int(ref.group(1))][1]
            maps[name.group(1)] = {int(a, 16): chr(int(b, 16)) for a, b in
                                   re.findall(rb"<([0-9A-Fa-f]{2})> <([0-9A-Fa-f]{4})>", cmap)}
    lines = []
    for head, raw in objects.values():
        if b"/Length1" in head or b"BT" not in raw:
            continue
        for block in re.findall(rb"BT(.*?)ET", raw, flags=re.S):
            font, parts = b"", []
            for m in re.finditer(rb"/(F\d+\+\d+) [\d.]+ Tf|\(((?:\\.|[^\\)])*)\) Tj", block, flags=re.S):
                if m.group(1):
                    font = m.group(1)
                else:
                    table = maps.get(font, {})
                    parts.append("".join(table.get(b, "?") for b in _pdf_string(m.group(2))))
            lines.append("".join(parts))
    return "\n".join(lines)


# --- compose ----------------------------------------------------------------------------------------


def test_bloklar_tartibi_va_sarlavha_qismi():
    doc = build()
    assert (doc.lang, doc.text_lang, doc.title) == ("uz-cyrl", "uz-Cyrl-UZ", "Ҳисобот йиғилиши")
    k = kinds(doc)
    assert k[:10] == ["approval", "spacer", "title", "two_col", "label", "label", "heading", "agenda", "agenda",
                      "italic"]
    # Ikki bayon paragrafi (har kun tartibi bandi uchun), preamble, "ҚАРОР ҚИЛАДИ:".
    assert k[10:14] == ["para", "para", "para", "heading"]
    assert k[14:] == ["section", "item", "item", "section", "item", "item", "spacer", "label", "muted"]
    assert doc.blocks[0]["lines"] == ["ТАСДИҚЛАЙМАН", BLANK, BLANK, BLANK, "«__» ____________ 20__ й.", "№ ____"]
    assert doc.blocks[2]["lines"] == [BLANK, f"{BLANK} ҳузурида ўтказилган йиғилиш", "Б А Ё Н И"]
    assert doc.blocks[3] == {"kind": "two_col", "left": "2025 йил 4 ноябрь", "right": f"{BLANK} шаҳри"}
    assert doc.blocks[4] == {"kind": "label", "label": "Раислик қилувчи:", "value": BLANK}
    assert doc.blocks[5] == {"kind": "label", "label": "Қатнашдилар:", "value": BLANK}
    assert doc.blocks[6] == {"kind": "heading", "text": "КУН ТАРТИБИ:"}
    assert doc.blocks[7] == {"kind": "agenda", "number": "1.", "text": "Режа ижроси тўғрисида"}
    assert doc.blocks[8] == {"kind": "agenda", "number": "2.", "text": "Жорий масалалар тўғрисида"}
    assert doc.blocks[9] == {"kind": "italic", "text": "Сўзга чиққанлар: Aziz Karimov"}
    assert doc.blocks[10] == {"kind": "para", "indent": True,
                              "runs": [("Кун тартибидаги биринчи масала юзасидан Aziz Karimov ҳисоботи эшитилди.", {})]}
    assert joined(doc.blocks[12]) == "Юқоридагиларни инобатга олиб, Йиғилиш"
    assert doc.blocks[13] == {"kind": "heading", "text": "ҚАРОР ҚИЛАДИ:"}
    # Kun tartibi "... тўғрисида" - bo'lim qolipi ko'makchini takrorlamaydi (`text.section_title`).
    assert doc.blocks[14] == {"kind": "section", "text": "I. Режа ижроси бўйича:"}
    assert doc.blocks[17] == {"kind": "section", "text": "II. Жорий масалалар бўйича:"}
    assert doc.blocks[-2] == {"kind": "label", "label": "Келишувчилар:", "value": BLANK}
    draft = doc.blocks[-1]["text"]
    assert draft.startswith(text.label("draft", "uz-cyrl")) and draft.endswith(f"{export.BRAND}, 2025 йил 4 ноябрь.")


def test_raqamlash_uzluksiz_nazorat_oxirida():
    doc = build()
    assert [b["number"] for b in items(doc)] == ["1.", "2.", "3.", "4."]
    last = items(doc)[-1]
    assert joined(last) == "4. Ушбу баённома ижросини назорат қилиш Aziz Karimov зиммасига юклатилсин."
    assert bold_runs(last) == ["4. ", "Aziz Karimov"]
    # Nazorat bandidan keyin band yo'q - faqat kelishuvchilar va izohlar.
    tail = kinds(doc)[kinds(doc).index("item", doc.blocks.index(last)) + 1:]
    assert "item" not in tail and "section" not in tail


def test_tokenlar_ism_yoki_blank_va_mas_ul_qalin():
    first, second, third, _ = items(build())
    assert joined(first) == "1. Aziz Karimov ҳисоботи маълумот учун қабул қилинсин."
    assert bold_runs(first) == ["1. "]
    # S2 nomsiz: mas'ul ham, matndagi token ham BLANK (ikki marta qo'shilmaydi); muddat qalin.
    assert joined(second) == f"2. Икки кун муддатда {BLANK} ҳисобот тайёрлаш вазифаси юклатилсин."
    assert bold_runs(second) == ["2. ", "Икки кун муддатда ", BLANK]
    assert second["sub"] == ["- муддатлар аниқлаштирилсин;"]
    assert second["follow"] == "Бунда, билдирилган эътирозлар инобатга олинсин."
    # Mas'ul aytilmagan vazifa: BLANK matn boshida (muddat yo'q - raqamdan keyin).
    assert joined(third) == f"3. {BLANK} ҳисобот тайёрлаш вазифаси юклатилсин."
    assert bold_runs(third) == ["3. ", f"{BLANK} "]
    assert third["sub"] == [] and third["follow"] is None
    # Ikkala spiker nomli: ism matnda, qalin, BLANK yo'q.
    second_named = items(build(speakers=NAMED))[1]
    assert joined(second_named) == "2. Икки кун муддатда Dilnoza Rahimova ҳисобот тайёрлаш вазифаси юклатилсин."
    assert bold_runs(second_named) == ["2. ", "Икки кун муддатда ", "Dilnoza Rahimova"]


def test_ismsiz_spikerlar_blank_sozga_chiqqanlar_yoq():
    doc = build(speakers={})
    assert "italic" not in kinds(doc)
    paras = [b for b in doc.blocks if b["kind"] == "para"]
    assert joined(paras[0]) == f"Кун тартибидаги биринчи масала юзасидан {BLANK} ҳисоботи эшитилди."
    assert joined(items(doc)[-1]) == f"4. Ушбу баённома ижросини назорат қилиш {BLANK} зиммасига юклатилсин."
    # Birlashtirilgan spiker ismi egasidan olinadi; kun tartibida nomsiz "S2" yo'q.
    merged = {"S1": {"id": "S1", "name": "Aziz Karimov"}, "S2": {"id": "S2", "name": None, "merged_into": "S1"}}
    doc = build(speakers=merged)
    assert joined(items(doc)[1]) == "2. Икки кун муддатда Aziz Karimov ҳисобот тайёрлаш вазифаси юклатилсин."
    assert [b for b in doc.blocks if b["kind"] == "italic"][0]["text"] == "Сўзга чиққанлар: Aziz Karimov"


def test_preamble_default_va_mavjud_nazorat_bandi():
    doc = build(preamble=None)
    preamble = [b for b in doc.blocks if b["kind"] == "para"][-1]
    assert joined(preamble) == text.label("preamble", "uz-cyrl")
    data = content("uz-cyrl")
    data["sections"][1]["items"].append({"kind": "control", "deadline": None, "deadlineDate": None, "responsible": [],
                                         "text": "Назорат [S1] зиммасида.", "subpoints": [], "followUp": None,
                                         "sourceSegmentIds": [3], "confidence": 0.8})
    doc = compose.compose(data, lang="uz-cyrl", title="", speakers=SPEAKERS, recorded_at=RECORDED_AT, now=NOW)
    assert [joined(b) for b in items(doc)][-2:] == [f"3. {BLANK} ҳисобот тайёрлаш вазифаси юклатилсин.",
                                                   "4. Назорат Aziz Karimov зиммасида."]
    assert doc.title == "Ҳисобот йиғилиши"                       # yig'ilish nomi bo'lmasa - mazmun sarlavhasi


def test_bolim_sarlavhasi_rim_raqam_va_kun_tartibi():
    data = content("uz-cyrl")
    data["agenda"][0]["title"] = "Режа ижроси тўғрисида."           # oxiridagi nuqta qolipda ikkilanmasin
    data["sections"].append({"agendaIndex": 99,
                             "items": [{"kind": "other", "text": "Бошқа масала.", "responsible": []}]})
    doc = compose.compose(data, lang="uz-cyrl", title="T", speakers=SPEAKERS, recorded_at=RECORDED_AT, now=NOW)
    sections = [b["text"] for b in doc.blocks if b["kind"] == "section"]
    assert sections == ["I. Режа ижроси бўйича:", "II. Жорий масалалар бўйича:",
                        f"III. {BLANK} бўйича:"]
    assert [b["number"] for b in items(doc)] == ["1.", "2.", "3.", "4.", "5."]
    ru = build("ru")
    assert [b["text"] for b in ru.blocks if b["kind"] == "section"][0] == "I. По вопросу «О ходе исполнения плана»:"


def test_izohlar_va_ogohlantirishlar_kulrang():
    doc = build(notes=["Муддат аниқ эмас", "Сумма текширилсин"],
                warnings=["ungrounded_name:Бобур", "unverified_number:15", "agenda_dropped", "provider_failed:x"])
    muted = [b["text"] for b in doc.blocks if b["kind"] == "muted"]
    assert len(muted) == 2
    lines = muted[0].split("\n")
    assert lines[:3] == ["Аниқлаштириш керак:", "- Муддат аниқ эмас", "- Сумма текширилсин"]
    assert len(lines) == 4 and "2" in lines[3]                      # faqat kotibga ma'noli ikkitasi sanaladi
    assert muted[1].startswith("ЛОЙИҲА")
    # Faqat texnik ogohlantirishlar - ro'yxat yo'q, loyiha qatori qoladi.
    assert len([b for b in build(warnings=["agenda_dropped"]).blocks if b["kind"] == "muted"]) == 1


def test_tokenlar_bunda_kichik_band_preamble_va_izohlarda():
    # Birinchi jonli sinov (2026-11-05): "Бунда, [S1] ..." va izohdagi "[S3] ва [S4]" hujjatga xom tushgan edi.
    data = content("uz-cyrl", preamble="[S1] таклифини инобатга олиб, Йиғилиш",
                   notes=["[S1] ва [S2] нинг ваколати аниқлаштирилсин.", "[S2] нинг исми 12:40 да эшитилмади."])
    task = data["sections"][0]["items"][1]
    task["subpoints"] = ["[S1] билан келишилсин", "[S#] га юборилсин"]
    task["followUp"] = "Бунда, [S1] ва [S2] ҳафтасига бир марта қўшилади."
    doc = compose.compose(data, lang="uz-cyrl", title="T", speakers=SPEAKERS, recorded_at=RECORDED_AT, now=NOW)
    second = items(doc)[1]
    # Qolipning o'zi ("[S#]", ikkinchi jonli sinov) - matnda BLANK.
    assert second["sub"] == ["- Aziz Karimov билан келишилсин", f"- {BLANK} га юборилсин"]
    assert second["follow"] == f"Бунда, Aziz Karimov ва {BLANK} ҳафтасига бир марта қўшилади."
    assert joined([b for b in doc.blocks if b["kind"] == "para"][-1]) == "Aziz Karimov таклифини инобатга олиб, Йиғилиш"
    # Izoh kotib uchun: ismsiz spiker BLANK emas - transkriptdagi raqami bilan.
    notes = [b["text"] for b in doc.blocks if b["kind"] == "muted"][0].split("\n")
    assert notes[1:] == ["- Aziz Karimov ва 2-иштирокчи нинг ваколати аниқлаштирилсин.",
                         "- 2-иштирокчи нинг исми 12:40 да эшитилмади."]
    assert "[S" not in render.markdown(doc)
    # Boshqa tillar; birlashtirilgan spiker - egasining ismi; spikerlar yo'q - faqat raqam.
    merged = {"S1": {"id": "S1", "name": "Aziz Karimov"}, "S3": {"id": "S3", "name": None, "merged_into": "S1"}}
    assert compose.render_notes({"notes": ["[S3] gapirdi."]}, speakers=merged, lang="uz-latn") == ["Aziz Karimov gapirdi."]
    assert compose.render_notes({"notes": ["[S2] не назван."]}, speakers=SPEAKERS, lang="ru") == ["Участник 2 не назван."]
    assert compose.render_notes({"notes": ["[S4] unclear.", " "]}, speakers=None, lang="en") == ["Speaker 4 unclear."]
    assert compose.render_notes({"notes": ["Номлар [S#] ларга мос эмас."]}, speakers=SPEAKERS,
                                lang="uz-cyrl") == ["Номлар иштирокчи ларга мос эмас."]


@pytest.mark.parametrize("lang", list(text.LANGS))
def test_har_tilda_yorliqlar(lang):
    doc = build(lang)
    assert doc.text_lang == text.WORD_LANGS[lang]
    assert doc.blocks[0]["lines"][0] == text.label("approve", lang)
    title_lines = doc.blocks[2]["lines"]
    assert doc.blocks[2]["doc"] == text.label("doc", lang) and text.label("doc", lang) in title_lines
    # Rus/ingliz: hujjat so'zi qaratqich/"of" qatoridan OLDIN; o'zbek: oxirida.
    expected = [BLANK, text.label("doc", lang), text.label("meeting_line", lang)] if lang in ("ru", "en") else \
        [BLANK, text.label("meeting_line", lang), text.label("doc", lang)]
    assert title_lines == expected
    headings = [b["text"] for b in doc.blocks if b["kind"] == "heading"]
    assert headings == [text.label("agenda", lang), text.label("decides", lang)]
    assert doc.blocks[3]["left"] == text.format_date(RECORDED_AT, lang)
    first_section = [b for b in doc.blocks if b["kind"] == "section"][0]["text"]
    assert first_section.startswith("I. ") and first_section == text.label("section", lang).format(
        roman="I", title=text.section_title(doc.blocks[7]["text"], lang))
    assert joined(items(doc)[-1]) == "4. " + text.label("control", lang).format(who="Aziz Karimov")


# --- DOCX ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("lang", list(text.LANGS))
def test_docx_letter_arial_yorliqlar(lang):
    doc = build(lang)
    data = render.render(doc, "docx")
    d = Document(io.BytesIO(data))
    section = d.sections[0]
    assert (section.page_width, section.page_height) == (Inches(8.5), Inches(11))
    assert (twips(section.left_margin), twips(section.right_margin)) == (twips(Cm(2.5)), twips(Cm(1.5)))
    assert (twips(section.top_margin), twips(section.bottom_margin)) == (twips(Cm(2.0)), twips(Cm(2.0)))
    normal = d.styles["Normal"]
    assert normal.font.name == "Arial" and normal.font.size == Pt(13)
    rfonts = normal.element.rPr.find(qn("w:rFonts"))
    assert rfonts.get(qn("w:eastAsia")) == "Arial" and rfonts.get(qn("w:cs")) == "Arial"
    defaults = d.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
    default_fonts = defaults.find(qn("w:rFonts"))
    # Mavzu atributlari o'chirilgan - aks holda Word Calibri ko'rsatardi.
    assert default_fonts.get(qn("w:asciiTheme")) is None and default_fonts.get(qn("w:ascii")) == "Arial"
    assert defaults.find(qn("w:lang")).get(qn("w:val")) == text.WORD_LANGS[lang]
    body = "\n".join(p.text for p in d.paragraphs)
    for key in ("approve", "doc", "chair", "attendees", "agenda", "decides", "approvers", "draft"):
        assert text.label(key, lang) in body, key
    assert "1. " in body and "4. " in body and BLANK in body
    assert "[S1]" not in body and "[S2]" not in body
    # Pastki va yuqori yozuv YO'Q (namunada yo'q): footer/header qismi ham, sahifa raqami maydoni ham.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert not [n for n in names if n.startswith("word/footer") or n.startswith("word/header")]
    assert "fldSimple" not in document_xml and "PAGE" not in document_xml
    assert d.core_properties.author == export.BRAND and d.core_properties.last_modified_by == export.BRAND
    assert d.core_properties.title == doc.title and d.core_properties.language == text.WORD_LANGS[lang]
    # Sana chapda, shahar o'ngda - chegarasiz 2x1 jadval.
    rows = [[c.text for c in row.cells] for row in d.tables[0].rows]
    assert rows == [[text.format_date(RECORDED_AT, lang), text.label("city", lang)]]
    borders = d.tables[0]._tbl.tblPr.find(qn("w:tblBorders"))
    assert all(edge.get(qn("w:val")) == "nil" for edge in borders)


def test_docx_uslublar():
    d = Document(io.BytesIO(render.docx_bytes(build())))
    by_text = {p.text: p for p in d.paragraphs}
    approve = by_text["ТАСДИҚЛАЙМАН"]
    assert approve.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert approve.runs[0].font.name == "Times New Roman" and approve.runs[0].font.size == Pt(12)
    assert approve.paragraph_format.space_after == Pt(0)
    doc_line = by_text["Б А Ё Н И"]
    assert doc_line.alignment == WD_ALIGN_PARAGRAPH.CENTER and doc_line.runs[0].bold
    assert doc_line.runs[0].font.size == Pt(14)
    assert by_text["КУН ТАРТИБИ:"].alignment == WD_ALIGN_PARAGRAPH.CENTER and by_text["КУН ТАРТИБИ:"].runs[0].bold
    agenda = by_text["1. Режа ижроси тўғрисида"]
    assert agenda.alignment == WD_ALIGN_PARAGRAPH.CENTER and agenda.runs[0].bold
    assert by_text["Сўзга чиққанлар: Aziz Karimov"].runs[0].italic
    section_p = by_text["I. Режа ижроси бўйича:"]
    run = section_p.runs[0]
    assert run.bold and run.underline and str(run.font.color.rgb) == "1F3864"
    item_p = next(p for p in d.paragraphs if p.text.startswith("2. Икки кун"))   # "2. Жорий ..." - kun tartibi
    assert item_p.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    assert twips(item_p.paragraph_format.first_line_indent) == twips(Cm(1.0))
    assert [r.text for r in item_p.runs if r.bold] == ["2. ", "Икки кун муддатда ", BLANK]
    assert [r.text for r in item_p.runs if not r.bold] == [" ҳисобот тайёрлаш вазифаси юклатилсин."]
    sub_p = by_text["- муддатлар аниқлаштирилсин;"]
    assert twips(sub_p.paragraph_format.left_indent) == twips(Cm(1.5))
    follow = by_text["Бунда, билдирилган эътирозлар инобатга олинсин."]
    assert twips(follow.paragraph_format.first_line_indent) == twips(Cm(1.0))
    chair = by_text[f"Раислик қилувчи: {BLANK}"]
    assert chair.runs[0].bold and chair.runs[0].text == "Раислик қилувчи:" and not chair.runs[1].bold
    draft = next(p for p in d.paragraphs if p.text.startswith("ЛОЙИҲА"))
    assert draft.runs[0].italic and draft.runs[0].font.size == Pt(10) and str(draft.runs[0].font.color.rgb) == "6B7280"


def test_docx_izohlar_ro_yxati_bitta_paragraf():
    data = render.docx_bytes(build(notes=["Муддат аниқ эмас"], warnings=["unverified_number:15"]))
    notes = next(p for p in docx_paragraphs(data) if p.text.startswith("Аниқлаштириш керак:"))
    assert "\n- Муддат аниқ эмас\n" in notes.text and notes.text.rstrip().endswith(").")
    assert all(r.italic for r in notes.runs)


# --- PDF -------------------------------------------------------------------------------------------


@needs_fonts
@pytest.mark.parametrize("lang", ["uz-cyrl", "en"])
def test_pdf_letter_dejavu_matn(lang):
    doc = build(lang)
    data = render.render(doc, "pdf", font_dir=export_render.DEFAULT_FONT_DIR)
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF") and len(data) > 2000
    assert re.search(rb"/MediaBox\s*\[\s*0\s+0\s+612\s+792\s*\]", data)          # US Letter
    assert 1 <= len(re.findall(rb"/Type /Page\b", data)) <= 2
    assert b"DejaVuSans" in data and b"Helvetica" not in data
    assert text.WORD_LANGS[lang].encode() in data                                 # /Lang
    if SERIF:
        assert b"DejaVuSerif" in data                                             # tasdiq bloki serifda
    extracted = pdf_text(data)
    for key in ("doc", "agenda", "decides", "approvers"):
        assert text.label(key, lang) in extracted, key
    assert "1. " in extracted and BLANK in extracted and "Aziz Karimov" in extracted
    assert "[S1]" not in extracted


@needs_fonts
def test_pdf_navbat_toliq_export_busy():
    doc = build()
    assert export_render._pdf_lock.acquire(timeout=5)
    try:
        with pytest.raises(export.RenderUnavailable) as info:
            render.pdf_bytes(doc, export_render.DEFAULT_FONT_DIR, wait=0)
        assert info.value.code == "export_busy"
    finally:
        export_render._pdf_lock.release()
    assert render.pdf_bytes(doc, export_render.DEFAULT_FONT_DIR).startswith(b"%PDF")


def test_pdf_shrift_yoq_503(tmp_path):
    with pytest.raises(export.RenderUnavailable) as info:
        render.render(build(), "pdf", font_dir=tmp_path)
    assert info.value.code == "pdf_unavailable"


# --- Markdown va umumiy ------------------------------------------------------------------------------


def test_markdown():
    doc = build()
    md = render.markdown(doc)
    assert render.render(doc, "md") == md.encode("utf-8")
    assert "Б А Ё Н И  \n" in md and "ТАСДИҚЛАЙМАН  \n" in md
    assert f"2025 йил 4 ноябрь    {BLANK} шаҳри" in md
    assert f"**Раислик қилувчи:** {BLANK}" in md
    assert "\nКУН ТАРТИБИ:\n" in md and "\n1. Режа ижроси тўғрисида\n2. Жорий масалалар тўғрисида\n\n" in md
    assert "_Сўзга чиққанлар: Aziz Karimov_" in md
    assert "**I. Режа ижроси бўйича:**" in md
    assert "**1.** Aziz Karimov ҳисоботи маълумот учун қабул қилинсин." in md
    assert f"**2.** **Икки кун муддатда** **{BLANK}** ҳисобот тайёрлаш вазифаси юклатилсин.\n  - муддатлар" in md
    assert "**4.** Ушбу баённома ижросини назорат қилиш **Aziz Karimov** зиммасига юклатилсин." in md
    assert "_ЛОЙИҲА" in md and "[S1]" not in md and "#" not in md


def test_boshqaruv_belgilari_tozalanadi():
    data = content("uz-cyrl", notes=["Изоҳ\x01 бор"], title="Сарлавха\x02")
    data["agenda"][0]["title"] = "Режа\x01 ижроси"
    data["sections"][0]["items"][0]["text"] = "[S1] ҳисоботи\x0c қабул қилинсин."
    doc = compose.compose(data, lang="uz-cyrl", title="Йиғилиш\x1f", speakers=SPEAKERS, recorded_at=RECORDED_AT,
                          now=NOW)
    assert doc.title == "Йиғилиш"
    assert "\x01" not in doc.blocks[7]["text"] and "\x0c" not in joined(items(doc)[0])
    docx = render.render(doc, "docx")
    text_docx = "\n".join(p.text for p in docx_paragraphs(docx))
    assert "Режа ижроси" in text_docx and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text_docx)
    assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", render.markdown(doc))
    if FONTS:
        assert render.render(doc, "pdf", font_dir=export_render.DEFAULT_FONT_DIR).startswith(b"%PDF")


def test_render_nomalum_format_va_blok():
    doc = build()
    with pytest.raises(ValueError):
        render.render(doc, "txt")
    doc.blocks.append({"kind": "h2", "text": "x"})
    with pytest.raises(ValueError):
        render.docx_bytes(doc)
    with pytest.raises(ValueError):
        render.markdown(doc)


def test_bolim_sarlavhasi_komakchini_takrorlamaydi():
    """Kun tartibi "... тўғрисида" / "On ..." bilan tugasa/boshlansa, bo'lim qolipi ("... бўйича:",
    "On ...:") uni ikki marta yozmaydi; rus qolipi «...» ichida o'zgarishsiz."""
    from app.services.meetings.minutes import text as t

    assert t.section_title("Режа ижроси тўғрисида.", "uz-cyrl") == "Режа ижроси"
    assert t.section_title("Жорий масалалар ҲАҚИДА;", "uz-cyrl") == "Жорий масалалар"
    assert t.section_title("Reja ijrosi to'g'risida", "uz-latn") == "Reja ijrosi"
    assert t.section_title("Reja ijrosi toʻgʻrisida", "uz-latn") == "Reja ijrosi"
    assert t.section_title("On the progress of the plan", "en") == "the progress of the plan"
    assert t.section_title("О ходе исполнения", "ru") == "О ходе исполнения"
    assert t.label("section", "uz-cyrl").format(roman="II", title=t.section_title("Режа тўғрисида", "uz-cyrl")) == \
        "II. Режа бўйича:"
    assert "{n}" in t.label("warnings", "uz-latn") and "{n}" in t.label("warnings", "en")


# --- minutes-3: sarlavha qismi, raqamlash, tahrir belgisi ---------------------------------------------------

#: Ega aytgan sarlavha qiymatlari (`validate` dan o'tgan ko'rinishda): S1 nomli, S2 nomsiz.
HEADER = {"organization": "«Агробанк» АТБ", "chairedBy": "Бошқарув раиси А.Каримов", "city": "Тошкент",
          "chair": "Бошқарув раиси [S1]", "attendees": ["[S1]", "Д.Раҳимова (бош ҳисобчи)", "[S2]"]}


def test_sarlavha_yoq_yoki_bosh_bloklar_ozgarmaydi():
    """minutes-2 hujjati (`header` yo'q) va bo'sh sarlavha - bloklar baytma-bayt bir xil (asl, `revision=0`)."""
    from app.services.meetings.minutes import validate

    plain = build()
    assert build(header={**validate.EMPTY_HEADER, "attendees": []}).blocks == plain.blocks
    assert build(header={"organization": "  ", "chair": None, "attendees": ["", "  "]}).blocks == plain.blocks
    assert build(header="buzilgan").blocks == plain.blocks
    again = compose.compose(content("uz-cyrl"), lang="uz-cyrl", title="Ҳисобот йиғилиши", speakers=SPEAKERS,
                            recorded_at=RECORDED_AT, now=NOW, revision=0)
    assert again.blocks == plain.blocks


def test_sarlavha_toldiriladi():
    doc = build(header=HEADER)
    assert doc.blocks[0]["lines"] == ["ТАСДИҚЛАЙМАН", "«Агробанк» АТБ", BLANK, BLANK, "«__» ____________ 20__ й.",
                                      "№ ____"]
    assert doc.blocks[2]["lines"] == ["«Агробанк» АТБ", "Бошқарув раиси А.Каримов ҳузурида ўтказилган йиғилиш",
                                      "Б А Ё Н И"]
    assert doc.blocks[3] == {"kind": "two_col", "left": "2025 йил 4 ноябрь", "right": "Тошкент шаҳри"}
    assert doc.blocks[4] == {"kind": "label", "label": "Раислик қилувчи:", "value": "Бошқарув раиси Aziz Karimov"}
    assert doc.blocks[5] == {"kind": "label", "label": "Қатнашдилар:",
                             "value": f"Aziz Karimov, Д.Раҳимова (бош ҳисобчи), {BLANK}"}
    body = "\n".join(p.text for p in docx_paragraphs(render.docx_bytes(doc)))
    for value in ("«Агробанк» АТБ", "Бошқарув раиси А.Каримов ҳузурида ўтказилган йиғилиш",
                  "Раислик қилувчи: Бошқарув раиси Aziz Karimov", "Д.Раҳимова (бош ҳисобчи)"):
        assert value in body, value
    tables = Document(io.BytesIO(render.docx_bytes(doc))).tables
    assert [[c.text for c in row.cells] for row in tables[0].rows] == [["2025 йил 4 ноябрь", "Тошкент шаҳри"]]
    md = render.markdown(doc)
    assert "«Агробанк» АТБ  \n" in md and "2025 йил 4 ноябрь    Тошкент шаҳри" in md
    assert "**Раислик қилувчи:** Бошқарув раиси Aziz Karimov" in md and "[S" not in md
    # Rus va ingliz: hujjat so'zi oldin, qaratqich/"of" qatori keyin; shahar qolipi tilniki.
    ru = build("ru", header={"organization": "АКБ «Агробанк»", "chairedBy": "Председателя Правления А.Каримова",
                             "city": "Ташкент", "chair": None, "attendees": []})
    assert ru.blocks[2]["lines"] == ["АКБ «Агробанк»", "П Р О Т О К О Л",
                                     "совещания под председательством Председателя Правления А.Каримова"]
    assert ru.blocks[3]["right"] == "г. Ташкент" and ru.blocks[4]["value"] == BLANK and ru.blocks[5]["value"] == BLANK
    en = build("en", header={"organization": None, "chairedBy": None, "city": "Tashkent", "chair": "A. Karimov",
                             "attendees": ["[S2]"]})
    assert en.blocks[2]["lines"] == [BLANK, "M I N U T E S", f"of the meeting chaired by {BLANK}"]
    assert en.blocks[3]["right"] == "Tashkent" and en.blocks[4]["value"] == "A. Karimov"
    assert en.blocks[5]["value"] == BLANK                                 # nomsiz spiker - bo'sh joy


def test_sarlavha_sanasi_yozuv_sanasi_orniga():
    """Ega aytgan yig'ilish sanasi (`header.date`) - chapdagi sana qatorida yozuv sanasi o'rniga, har tilning o'z
    shaklida; fayl nomidagi sana ham shu (`compose.meeting_day`). Yaroqsiz qiymat - yozuv sanasi."""
    from app.services.meetings import dates as dates_mod

    assert build(header={"date": "2026-11-11"}).blocks[3]["left"] == "2026 йил 11 ноябрь"
    assert build("uz-latn", header={"date": "2026-11-11"}).blocks[3]["left"] == "2026 yil 11 noyabr"
    assert build("ru", header={"date": "2026-11-11"}).blocks[3]["left"] == "11 ноября 2026 года"
    assert build("en", header={"date": "2026-11-11"}).blocks[3]["left"] == "11 November 2026"
    assert build(header={"date": "11 noyabr"}).blocks[3]["left"] == "2025 йил 4 ноябрь"           # yozuv sanasi
    day = compose.meeting_day({"header": {"date": "2026-11-11"}}, RECORDED_AT)
    assert dates_mod.tashkent(day).date().isoformat() == "2026-11-11"
    assert compose.meeting_day({"header": {"date": None}}, RECORDED_AT) == RECORDED_AT
    assert compose.meeting_day({}, 0) == 0
    _, real_name = export.file_names(compose.file_title("Haftalik", lang="uz-latn", revision=1), day, "docx")
    assert real_name == "Bayonnoma - Haftalik (2-tahrir) 2026-11-11.docx"


def test_raqamlash_compose_bilan_bir_xil():
    """`numbering` - Word dagi raqamlar: matnsiz band raqam olmaydi, nazorat bandi (mazmunda `control` bo'lmasa)
    oxirida; har yozuv mazmundagi bandni ko'rsatadi. `outline` - tahrir promptidagi o'sha raqamlar."""
    data = content("uz-cyrl")
    data["sections"][0]["items"].insert(1, {"kind": "task", "text": "   ", "responsible": []})
    data["sections"][1]["items"].append({"kind": "other", "text": "Бошқа масала [S1] билан.", "responsible": []})
    numbers = compose.numbering(data)
    doc = compose.compose(data, lang="uz-cyrl", title="T", speakers=SPEAKERS, recorded_at=RECORDED_AT, now=NOW)
    assert [n.number for n in numbers] == [int(b["number"].rstrip(".")) for b in items(doc)] == [1, 2, 3, 4, 5]
    assert [(n.section, n.index, n.control) for n in numbers] == [(1, 0, False), (1, 2, False), (2, 0, False),
                                                                  (2, 1, False), (0, -1, True)]
    names = compose._Names(SPEAKERS)
    for n, block in zip(numbers[:-1], items(doc)[:-1]):
        assert joined(block).endswith(names.render(data["sections"][n.section - 1]["items"][n.index]["text"]))
    assert joined(items(doc)[-1]).startswith("5. Ушбу баённома ижросини назорат")
    lines = compose.outline(data, lang="uz-cyrl", speakers=SPEAKERS).split("\n")
    assert lines == [
        "Agenda 1 = agenda[0]: «Режа ижроси тўғрисида»",
        "Agenda 2 = agenda[1]: «Жорий масалалар тўғрисида»",
        "Section I = sections[0] (agendaIndex 1): items 1-2",
        "  Item 1 = sections[0].items[0] (acknowledge): «Aziz Karimov ҳисоботи маълумот учун қабул қилинсин.»",
        f"  Item 2 = sections[0].items[2] (task): «{BLANK} ҳисобот тайёрлаш вазифаси юклатилсин.»",
        "Section II = sections[1] (agendaIndex 2): items 3-4",
        "  Item 3 = sections[1].items[0] (task): «ҳисобот тайёрлаш вазифаси юклатилсин.»",
        "  Item 4 = sections[1].items[1] (other): «Бошқа масала Aziz Karimov билан.»",
        "Item 5 = the control item added by code from \"controller\": «Ушбу баённома ижросини назорат қилиш Aziz "
        "Karimov зиммасига юклатилсин.» - to change it, change \"controller\"."]
    # Mazmunda nazorat bandi bor - kod qo'shmaydi; uzun matn qisqartiriladi; bo'sh bo'lim - "no items".
    data["sections"][1]["items"].append({"kind": "control", "text": "Назорат " + "жуда " * 60 + "[S1] зиммасида."})
    data["sections"].append({"agendaIndex": 2, "items": [{"kind": "task", "text": ""}]})
    numbers = compose.numbering(data)
    assert not any(n.control for n in numbers) and numbers[-1] == compose.Numbered(5, 2, 2)
    doc = compose.compose(data, lang="uz-cyrl", title="T", speakers=SPEAKERS, recorded_at=RECORDED_AT, now=NOW)
    assert [b["number"] for b in items(doc)] == ["1.", "2.", "3.", "4.", "5."]
    lines = compose.outline(data, lang="uz-cyrl", speakers=SPEAKERS).split("\n")
    assert lines[-2].startswith("  Item 5 = sections[1].items[2] (control): «Назорат жуда")
    assert len(lines[-2].split("«", 1)[1]) == compose.OUTLINE_TEXT + 1 and lines[-2].endswith("…»")
    assert lines[-1] == "Section III = sections[2] (agendaIndex 2): no items"


def test_tahrir_belgisi():
    """Tahrir (`revision` >= 1): loyiha qatorida versiya belgisi; eksport fayli nomida ham (`file_title`)."""
    def draft(lang: str, revision: int) -> str:
        doc = compose.compose(content(lang), lang=lang, title="T", speakers=SPEAKERS, recorded_at=RECORDED_AT,
                              now=NOW, revision=revision)
        return doc.blocks[-1]["text"]

    assert draft("uz-cyrl", 1) == f"{text.label('draft', 'uz-cyrl')} 2-таҳрир. {export.BRAND}, 2025 йил 4 ноябрь."
    assert draft("uz-latn", 2).endswith(f" 3-tahrir. {export.BRAND}, 2025 yil 4 noyabr.")
    assert draft("ru", 1).endswith(f" редакция 2. {export.BRAND}, 4 ноября 2025 года.")
    assert draft("en", 1).endswith(f" version 2. {export.BRAND}, 4 November 2025.")
    assert draft("uz-cyrl", 0) == f"{text.label('draft', 'uz-cyrl')} {export.BRAND}, 2025 йил 4 ноябрь."
    assert compose.file_title("Haftalik", lang="uz-cyrl", revision=1) == "Баённома - Haftalik (2-таҳрир)"
    assert compose.file_title("Haftalik", lang="uz-cyrl") == "Баённома - Haftalik"
    assert compose.file_title("", lang="en", revision=2) == "Minutes (version 3)"
    assert compose.file_title(" Plan\x01 ", lang="ru", revision=0) == "Протокол - Plan"
    ascii_name, real_name = export.file_names(compose.file_title("Haftalik", lang="uz-cyrl", revision=1),
                                              RECORDED_AT, "docx")
    assert real_name == "Баённома - Haftalik (2-таҳрир) 2025-11-04.docx" and ascii_name.endswith("2025-11-04.docx")

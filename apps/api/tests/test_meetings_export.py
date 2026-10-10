"""To'liq hujjat eksporti `GET /meetings/{id}/export` (DOCX/PDF/MD/TXT) va audioni yuklab olish.

Hamma narsa soxtalar bilan (`meetings_fakes.py`): GAPI, model va audio tarmoqqa chiqmaydi.
Xulosa mazmuni - real ko'rinishdagi `rich_content` (o'zbekcha va ruscha), u ishchining
AYNI `apply_primary` yo'li bilan asosiy xulosaga aylantiriladi (vazifalar jadvali jonli
`action_items` dan chiziladi).
"""

from __future__ import annotations

import base64
import io
import re
import threading
import time
import zipfile
import zlib

from urllib.parse import unquote

import pytest

from app.core.config import settings
from app.services.meetings import export, export_render
from app.services.meetings.store import jdump
from app.services.meetings.worker import apply_primary
from meetings_fakes import create_meeting, enable, recorded, run_all

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: PDF testlari tizim shriftiga (`fonts-dejavu-core`) bog'liq: shriftsiz CI/dev mashinada ular
#: YIQILMASIN, o'tkazib yuborilsin (ishlab chiqarishda shrift bor; yo'q bo'lsa endpoint 503 -
#: bu `test_pdf_shrift_yoq_503` da shriftsiz ham tekshiriladi).
FONTS = (export_render.DEFAULT_FONT_DIR / export_render.REGULAR_FILE).is_file()
needs_fonts = pytest.mark.skipif(not FONTS, reason="DejaVu shrifti yo'q (fonts-dejavu-core)")


# --- ma'lumot ---------------------------------------------------------------------------------------


def _ev(*ids: int, start: float | None = None) -> dict:
    return {"sourceSegmentIds": list(ids), "start": start}


def rich_content(lang: str = "uz") -> dict:
    """Real yig'ilishdagidek to'liq xulosa (`SummaryContent`, spetsifikatsiya 6.2)."""
    ru = lang == "ru"
    return {
        "schemaVersion": "meeting-summary/1", "template": "general", "language": lang,
        "meeting": {"date": "2026-10-09", "weekday": "payshanba", "timezone": "Asia/Tashkent",
                    "durationSec": 3725.0, "speakerCount": 3},
        "title": "Релиз мобильного приложения" if ru else "Mobil ilova relizi bo'yicha haftalik yig'ilish",
        "meetingType": {"value": "general", "confidence": 0.9},
        "overview": ("[S1] и [S2] обсудили релиз версии 1.2. Релиз назначен на 17 октября."
                     if ru else "[S1] va [S2] mobil ilovaning 1.2 versiyasi relizini muhokama qildi. "
                                "Reliz 17-oktyabrga belgilandi, testlar seshanbagacha yakunlanadi."),
        "purpose": "Согласовать дату релиза" if ru else "Reliz sanasi va mas'ullarni kelishib olish",
        "participants": [
            {"speaker": "S1", "suggestedName": None, "nameEvidence": [], "role": None, "talkSec": 30.0,
             "talkShare": 0.45, "contribution": "Релиз и сроки" if ru else "Reliz sanasini taklif qildi"},
            {"speaker": "S2", "suggestedName": None, "nameEvidence": [], "role": None, "talkSec": 25.0,
             "talkShare": 0.4, "contribution": None},
            {"speaker": "S3", "suggestedName": None, "nameEvidence": [], "role": None, "talkSec": 10.0,
             "talkShare": 0.15, "contribution": None},
        ],
        "topics": [
            {"id": "T1", "title": "Дата релиза" if ru else "Reliz sanasi", "summary":
                "Команда выбрала 17 октября." if ru else "Jamoa 17-oktyabrni tanladi, boshqa surilmaydi.",
             "outcome": "decided", "startSegmentId": 1, "endSegmentId": 3, "start": 0.0, "end": 22.0,
             "keyPoints": [{"text": "Релиз 17 октября" if ru else "Reliz 17-oktyabr kuni", **_ev(1, start=0.0)},
                           {"text": "Тесты до вторника" if ru else "Testlar seshanbagacha", **_ev(2, start=6.5)}]},
            {"id": "T2", "title": "Бюджет" if ru else "Byudjet", "summary":
                "Бухгалтерия не ответила." if ru else "Buxgalteriya hali javob bermadi.",
             "outcome": "open", "startSegmentId": 4, "endSegmentId": 7, "start": 22.5, "end": 63.0,
             "keyPoints": []},
        ],
        "keyPoints": [{"id": "K1", "text": "Релиз не переносится" if ru else "Reliz boshqa surilmaydi",
                       **_ev(3, start=14.5)}],
        "decisions": [
            {"id": "D1", "text": "Релиз 17 октября" if ru else "Reliz 17-oktyabr kuni chiqariladi",
             "status": "final", "condition": None, "rationale": None, "proposedBy": ["S1"], "agreedBy": ["S2"],
             "topicId": "T1", "quote": "17", "needsConfirmation": False, "verified": True, **_ev(3, start=14.5)},
            {"id": "D2", "text": "Push-уведомления позже" if ru else "Push-bildirishnomalar keyingi versiyaga",
             "status": "tentative", "condition": None, "rationale": None, "proposedBy": [], "agreedBy": [],
             "topicId": None, "quote": "push", "needsConfirmation": True, "verified": None, **_ev(5, start=30.5)},
        ],
        "actionItems": [
            {"id": "A1", "task": "Подготовить отчёт о тестах" if ru else "Test hisobotini tayyorlash",
             "deliverable": None, "condition": None,
             "owner": {"speaker": "S2", "name": None, "kind": "person", "basis": "self_commitment"},
             "assignedBy": None, "due": {"raw": "seshanba", "date": "2026-10-14", "time": None, "basis": "explicit"},
             "priority": "high", "status": "open", "origin": "explicit", "dependsOn": [], "topicId": "T1",
             "quote": "tayyorlab", "confidence": 0.9, "needsConfirmation": False, "verified": True,
             **_ev(2, start=6.5)},
            {"id": "A2", "task": "Обновить страницу в Play Market" if ru else "Play Market sahifasini yangilash",
             "deliverable": None, "condition": None,
             "owner": {"speaker": "S1", "name": None, "kind": "person", "basis": "assigned_and_accepted"},
             "assignedBy": "S2", "due": {"raw": None, "date": "2026-10-16", "time": "18:00", "basis": "explicit"},
             "priority": "normal", "status": "open", "origin": "explicit", "dependsOn": [], "topicId": "T1",
             "quote": "sahifa", "confidence": 0.8, "needsConfirmation": True, "verified": None,
             **_ev(4, start=22.5)},
            {"id": "A3", "task": "Запросить бюджет у бухгалтерии" if ru else "Buxgalteriyadan byudjetni so'rash",
             "deliverable": None, "condition": None,
             "owner": {"speaker": None, "name": "Javlon", "kind": "person", "basis": "volunteered"},
             "assignedBy": None, "due": {"raw": "keyingi hafta", "date": None, "time": None, "basis": "vague"},
             "priority": None, "status": "open", "origin": "explicit", "dependsOn": [], "topicId": "T2",
             "quote": "byudjet", "confidence": 0.7, "needsConfirmation": False, "verified": True,
             **_ev(7, start=50.5)},
        ],
        "openQuestions": [{"id": "Q1", "text": "Каков рекламный бюджет?" if ru else "Reklama byudjeti qancha bo'ladi?",
                           "raisedBy": "S2", "directedTo": None, "whyOpen": "no_answer", **_ev(7, start=50.5)}],
        "risks": [{"id": "R1", "text": "Проверка Apple может задержаться" if ru else "Apple ko'rigi kechikishi mumkin",
                   "kind": "risk", "raisedBy": "S3", "severity": "medium",
                   "mitigation": "Отправить заявку в понедельник" if ru else "Arizani dushanbagacha yuborish",
                   **_ev(6, start=40.5)}],
        "numbers": [{"id": "N1", "value": "15", "unit": "млн сум" if ru else "mln so'm",
                     "what": "рекламный бюджет" if ru else "reklama uchun taxminiy byudjet", **_ev(3, start=14.5)}],
        "dates": [{"id": "E1", "date": "2026-10-17", "time": None, "raw": "17-oktyabr", "what":
                   "релиз" if ru else "reliz", **_ev(3, start=14.5)}],
        "nextSteps": [{"id": "X1", "text": "Финальная сборка" if ru else "Yakuniy yig'ma (build)",
                       **_ev(4, start=22.5)}],
        "nextMeeting": {"date": "2026-10-17", "time": "10:00", "raw": "juma 10:00",
                        "agenda": ["Итоги релиза" if ru else "Reliz natijalari"], **_ev(5, start=30.5)},
        "highlights": [{"id": "H1", "quote": "Релиз не переносим" if ru else "Relizni boshqa surmaymiz",
                        "speaker": "S1", "segmentId": 3, "start": 14.5, "why": "qaror", "fromMark": None}],
        "userMarks": [],
        "keywords": ["reliz", "test", "byudjet"],
        "sentiment": {"overall": "positive", "note": None, "sourceSegmentIds": [], "start": None},
        "templateSections": [],
        "followUpMessage": None,
        "followUps": [{"id": "F1", "text": "Каков рекламный бюджет?" if ru else "Reklama byudjeti qancha bo'ladi?",
                       "reasons": ["no_answer"], "ref": "Q1", "start": 50.5}],
        "quality": {"warnings": [], "droppedItems": 0, "flaggedItems": 1, "chunks": 1, "coverageOk": True,
                    "speakersAvailable": True, "languageWarning": None},
    }


@pytest.fixture
def ready(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(_isolated_meetings)
    return client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()


def make_rich(rt, meeting: dict, lang: str = "uz", *, title: str | None = None) -> str:
    """Asosiy xulosani `rich_content` ga almashtiradi - ishchining AYNI yo'li bilan
    (`apply_primary`: AI vazifalari jonli jadvalga yoziladi). Xulosa id sini qaytaradi."""
    sid = meeting["primarySummaryId"]
    content = rich_content(lang)
    # Soxta model 64 s lik yozuvni `short_call` deb tasniflaydi - to'liq shablon kerak.
    rt.store.update_summary(sid, content_json=jdump(content), language=lang, template="general")
    rt.store.update_meeting(meeting["id"], title_source="auto")
    apply_primary(rt, rt.store.meeting_any(meeting["id"]), sid, "general", content, time.time())
    if title is not None:
        rt.store.update_meeting(meeting["id"], title=title, title_source="user")
    return sid


def name_speakers(client, auth, mid: str, **names: str) -> None:
    for sid, name in names.items():
        assert client.patch(f"/api/v1/meetings/{mid}/speakers/{sid}", headers=auth,
                            json={"name": name}).status_code == 200


def get_export(client, auth, mid: str, fmt: str, lang: str = "uz", **params):
    query = "&".join([f"format={fmt}"] + [f"{k}={v}" for k, v in params.items()])
    return client.get(f"/api/v1/meetings/{mid}/export?{query}", headers={**auth, "Accept-Language": lang})


def docx_text(data: bytes) -> tuple[list[tuple[str, str]], list[list[list[str]]]]:
    from docx import Document

    d = Document(io.BytesIO(data))
    paragraphs = [(p.style.name, p.text) for p in d.paragraphs]
    tables = [[[c.text for c in row.cells] for row in t.rows] for t in d.tables]
    return paragraphs, tables


def _pdf_objects(data: bytes) -> dict[int, tuple[bytes, bytes]]:
    """PDF obyektlari: raqam -> (lug'at, ochilgan oqim). Faqat reportlab yozadigan oddiy shakl."""
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
    """Kutubxonasiz matn ajratish: reportlab TTF qism-to'plamining ToUnicode xaritasi orqali
    (PDF dagi glif kodlari -> Unicode). Matn ajralsa - u haqiqatan DejaVu bilan chizilgan."""
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


def pdf_facts(data: bytes) -> dict:
    """PDF ni tashqi kutubxonasiz tekshirish: sahifalar soni, shriftlar, ajratilgan matn."""
    assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    text = pdf_text(data)
    return {"pages": len(re.findall(rb"/Type /Page\b", data)), "text": text,
            "dejavu": b"DejaVuSans" in data, "helvetica": b"Helvetica" in data, "tounicode": b"/ToUnicode" in data}


# --- formatlar va tillar ---------------------------------------------------------------------------------

TITLES = {
    "uz": ("Vazifalar", "Qarorlar", "Aqliy xarita", "Transkript", "Mas'ul", "Yaratildi"),
    "ru": ("Задачи", "Решения", "Интеллект-карта", "Расшифровка", "Ответственный", "Создано"),
    "en": ("Action items", "Decisions", "Mind map", "Transcript", "Owner", "Generated"),
}


@pytest.mark.parametrize("lang", ["uz", "ru", "en"])
@pytest.mark.parametrize("fmt", ["md", "txt", "docx", pytest.param("pdf", marks=needs_fonts)])
def test_har_format_har_tilda(client, auth, ready, _isolated_meetings, fmt, lang):
    mid = ready["id"]
    make_rich(_isolated_meetings, ready)
    name_speakers(client, auth, mid, S1="Aziz", S2="Dilnoza")
    response = get_export(client, auth, mid, fmt, lang)
    assert response.status_code == 200, response.text
    media, ext = export.FORMATS[fmt]
    assert response.headers["content-type"].startswith(media.split(";")[0])
    disposition = response.headers["content-disposition"]
    # Tutuq belgisi so'zni bo'lmaydi: "bo'yicha" -> "boyicha" (`bo-yicha` emas).
    assert disposition.startswith('attachment; filename="mobil-ilova-relizi-boyicha-haftalik-yigilish-2026-10-09.')
    assert f".{ext}\"; filename*=UTF-8''" in disposition
    assert unquote(disposition.split("''", 1)[1]) == f"Mobil ilova relizi bo'yicha haftalik yig'ilish 2026-10-09.{ext}"
    assert response.headers["cache-control"] == "private, no-store"
    tasks, decisions, mindmap, transcript, owner, generated = TITLES[lang]
    if fmt in ("md", "txt"):
        text = response.text
        for word in (tasks, decisions, mindmap, transcript, owner, f"Barno AI · {generated}"):
            assert word in text, (word, fmt, lang)
        # Mazmun o'z tilida qoladi (xulosa o'zbekcha), ism tokenlari - ism.
        assert "Aziz va Dilnoza mobil ilovaning 1.2 versiyasi" in text
        assert "Test hisobotini tayyorlash" in text and "[S1]" not in text
    elif fmt == "docx":
        paragraphs, tables = docx_text(response.content)
        headings = [text for style, text in paragraphs if style.startswith("Heading")]
        assert tasks in headings and decisions in headings and mindmap in headings and transcript in headings
        assert tables and tables[0][0][2] == owner
    else:
        facts = pdf_facts(response.content)
        assert facts["pages"] >= 2 and facts["dejavu"] and not facts["helvetica"] and facts["tounicode"]
        for word in (tasks, decisions, mindmap, transcript, owner, f"Barno AI · {generated}"):
            assert word in facts["text"], (word, lang)
        assert "Test hisobotini tayyorlash" in facts["text"] and "Reklama byudjeti qancha bo'ladi?" in facts["text"]


def test_docx_tarkibi_tartib_jadval_crm_xarita(client, auth, ready, _isolated_meetings):
    rt = _isolated_meetings
    mid = ready["id"]
    make_rich(rt, ready)
    name_speakers(client, auth, mid, S1="Aziz", S2="Dilnoza")
    # A1 CRM da yaratilgan (kalit bilan), A2 - taklif kutilmoqda (kalit KO'RSATILMAYDI).
    rows = {r["summary_item_id"]: r for r in rt.store.action_items(mid)}
    rt.store.update_action_item(rows["A1"]["id"], crm_token="tok-1", crm_status="executed",
                                crm_result=jdump({"key": "DVSIB-231"}))
    rt.store.update_action_item(rows["A2"]["id"], crm_token="tok-2", crm_status="pending")
    rt.store.update_action_item(rows["A3"]["id"], status="done")
    response = get_export(client, auth, mid, "docx")
    assert response.status_code == 200
    paragraphs, tables = docx_text(response.content)
    assert paragraphs[0] == ("Title", "Mobil ilova relizi bo'yicha haftalik yig'ilish")
    meta = [text for _, text in paragraphs[1:5]]
    assert meta[0] == "Sana: 2026-yil 9-oktabr, 11:00"
    assert meta[1] == "Davomiyligi: 1 daqiqa 4 soniya"   # 10 daqiqadan qisqa - soniyasi bilan
    assert meta[2] == "Ishtirokchilar: Aziz, Dilnoza, 3-ishtirokchi"
    assert meta[3] == "Xulosa turi: Umumiy yig'ilish"
    headings = [text for style, text in paragraphs if style == "Heading 1"]
    # "Qisqa xulosa" BIRINCHI; keyin shablon tartibi (`CORE_LAYOUT`), bo'sh bo'limlar tushib qoladi.
    # "Qisqacha" va "Asosiy fikrlar" yo'q: "Qisqa xulosa" ularni to'liq takrorlaydi (2 gap, 1 fikr).
    # "Ochiq savollar" yo'q: yagona savol "Hal qilinmagan masalalar" da sababi bilan bor (takrorlanmaydi);
    # iqtiboslar va ishtirokchilar faolligi - eksportning o'z nomlari.
    assert headings == ["Qisqa xulosa", "Vazifalar", "Qarorlar", "Hal qilinmagan masalalar", "Mavzular",
                        "Xavflar", "Raqamlar", "Sanalar va muddatlar",
                        "Keyingi qadamlar", "Keyingi yig'ilish", "Iqtiboslar", "Ishtirokchilar faolligi",
                        "Kalit so'zlar", "Kayfiyat", "Aqliy xarita", "Transkript"]
    table = tables[0]
    assert table[0] == ["№", "Vazifa", "Mas'ul", "Muddat", "Holat", "CRM"]
    body = {row[1]: row for row in table[1:]}
    assert body["Test hisobotini tayyorlash"][2:] == ["Dilnoza", "14-oktabr", "ochiq", "DVSIB-231"]
    # Ogohlantirish vazifa matnida emas - holat ustunida, alohida qatorda.
    assert body["Play Market sahifasini yangilash"][2:] == ["Aziz", "16-oktabr, 18:00",
                                                            "ochiq\n⚠ aniqlashtirish kerak", ""]
    assert body["Buxgalteriyadan byudjetni so'rash"][2:] == ["Javlon", "keyingi hafta", "✓ bajarildi", ""]
    texts = [text for _, text in paragraphs]
    assert "Reliz 17-oktyabr kuni chiqariladi [yakuniy] (00:14)" in texts
    assert "Push-bildirishnomalar keyingi versiyaga [taxminiy · ⚠ aniqlashtirish kerak] (00:30)" in texts
    assert "Apple ko'rigi kechikishi mumkin [o'rta] → Arizani dushanbagacha yuborish (00:40)" in texts
    assert "15 mln so'm — reklama uchun taxminiy byudjet" in texts
    assert "Aziz — nutq ulushi 45%: Reliz sanasini taklif qildi" in texts
    assert "Reklama byudjeti qancha bo'ladi? — javob berilmagan (00:50)" in texts
    # Aqliy xarita: ildiz - sarlavha, shoxlar - mavzular (+ natija), qarorlar, vazifalar, savollar.
    at = texts.index("Aqliy xarita")
    tree = paragraphs[at + 1:texts.index("Transkript")]
    assert tree[0] == ("Normal", "Mobil ilova relizi bo'yicha haftalik yig'ilish")
    assert ("List Bullet", "Reliz sanasi (qaror qabul qilindi)") in tree
    assert ("List Bullet 2", "Reliz 17-oktyabr kuni") in tree
    assert ("List Bullet", "Byudjet (ochiq)") in tree
    assert ("List Bullet 2", "Buxgalteriya hali javob bermadi.") in tree      # nuqtasiz mavzu - xulosasi
    assert [t for s, t in tree if s == "List Bullet"] == ["Reliz sanasi (qaror qabul qilindi)", "Byudjet (ochiq)",
                                                          "Qarorlar", "Vazifalar", "Ochiq savollar"]
    # Xaritada holat yo'qolmaydi: vazifa - mas'ul va muddat, bajarilgani "✓", qaror - holati.
    assert ("List Bullet 2", "Test hisobotini tayyorlash — Dilnoza · 14-oktabr") in tree
    assert ("List Bullet 2", "✓ Buxgalteriyadan byudjetni so'rash — Javlon · keyingi hafta (bajarildi)") in tree
    assert ("List Bullet 2", "Push-bildirishnomalar keyingi versiyaga (taxminiy)") in tree
    assert ("List Bullet 2", "Reliz 17-oktyabr kuni chiqariladi") in tree
    assert ("List Bullet 2", "Reklama byudjeti qancha bo'ladi?") in tree     # xaritada savol qoladi
    # Transkript: vaqt (xulosadagi bilan bir xil format - yig'ilish soatdan qisqa) + ism.
    assert texts[texts.index("Transkript") + 1].startswith("[00:00] Aziz: Assalomu alaykum")


def test_kirill_matn_va_nom(client, auth, ready, _isolated_meetings):
    rt = _isolated_meetings
    mid = ready["id"]
    make_rich(rt, ready, "ru", title="Планёрка: релиз «Барно» и бюджет")
    name_speakers(client, auth, mid, S1="Азиз", S2="Дилноза")
    rt.store.execute("UPDATE segments SET text=? WHERE meeting_id=? AND id=1",
                     ("Здравствуйте, начинаем. Oʻzbekcha gʻ va o' ham bor.", mid))
    md = get_export(client, auth, mid, "md", "ru")
    assert md.status_code == 200
    assert md.text.startswith("# Планёрка: релиз «Барно» и бюджет\n")
    assert "**Дата:** 9 октября 2026, 11:00" in md.text
    assert "Азиз и Дилноза обсудили релиз версии 1.2." in md.text
    assert "| 1 | Подготовить отчёт о тестах | Дилноза | 14 октября | открыта |   |" in md.text
    assert "**[00:00] Азиз:** Здравствуйте, начинаем. Oʻzbekcha gʻ va o' ham bor." in md.text
    # ASCII nom (eski klientlar) - kirill lotinga o'giriladi; haqiqiy nom - `filename*` da.
    disposition = md.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="planyorka-reliz-barno-i-byudzhet-2026-10-09.md"; '
                                  'filename*=UTF-8\'\'')
    assert unquote(disposition.split("''", 1)[1]) == "Планёрка релиз «Барно» и бюджет 2026-10-09.md"
    docx = get_export(client, auth, mid, "docx", "ru")
    paragraphs, tables = docx_text(docx.content)
    assert paragraphs[0][1] == "Планёрка: релиз «Барно» и бюджет"
    assert tables[0][1][1] == "Подготовить отчёт о тестах" and tables[0][0][1] == "Задача"
    if not FONTS:
        return
    pdf = get_export(client, auth, mid, "pdf", "ru")
    facts = pdf_facts(pdf.content)
    assert facts["dejavu"] and facts["tounicode"] and not facts["helvetica"]
    assert "Планёрка: релиз «Барно» и бюджет" in facts["text"]
    assert "Подготовить отчёт о тестах" in facts["text"] and "Интеллект-карта" in facts["text"]
    assert "Здравствуйте, начинаем. Oʻzbekcha gʻ va o' ham bor." in facts["text"]
    assert "?" not in facts["text"].replace("Каков рекламный бюджет?", "")


def test_md_va_txt_shakli(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    make_rich(_isolated_meetings, ready)
    name_speakers(client, auth, mid, S1="Aziz", S2="Dilnoza")
    md = get_export(client, auth, mid, "md").text
    assert md.startswith("# Mobil ilova relizi bo'yicha haftalik yig'ilish\n\n**Sana:** 2026-yil 9-oktabr, 11:00  \n")
    assert "| № | Vazifa | Mas'ul | Muddat | Holat | CRM |\n|---|---|---|---|---|---|\n" in md
    assert "- **Mobil ilova relizi bo'yicha haftalik yig'ilish**\n  - **Reliz sanasi (qaror qabul qilindi)**\n" \
           "    - Reliz 17-oktyabr kuni\n" in md
    assert "### Reliz sanasi\n_00:00–00:22 · qaror qabul qilindi_\n" in md
    assert "> «Relizni boshqa surmaymiz» — Aziz (00:14)" in md
    assert md.rstrip().endswith("_") and "---\n_Barno AI · Yaratildi: " in md
    txt = get_export(client, auth, mid, "txt").text
    assert txt.startswith("Mobil ilova relizi bo'yicha haftalik yig'ilish\n=====")
    assert "**" not in txt and "|---" not in txt
    assert "1. Test hisobotini tayyorlash\n   Mas'ul: Dilnoza · Muddat: 14-oktabr · Holat: ochiq\n" in txt
    assert "\nAqliy xarita\n------------\nMobil ilova relizi bo'yicha haftalik yig'ilish\n  - Reliz sanasi" in txt
    assert "[00:06] 2-ishtirokchi: Men ertaga" not in txt and "[00:06] Dilnoza: Men ertaga" in txt
    # Holat ustunidagi ikkinchi qator (ogohlantirish) MD/TXT da " · " bilan bir qatorda.
    assert "| 2 | Play Market sahifasini yangilash | Aziz | 16-oktabr, 18:00 | ochiq · ⚠ aniqlashtirish kerak |" in md
    assert "Holat: ochiq · ⚠ aniqlashtirish kerak" in txt


def test_transkript_tahrirlangan_eski_xulosa_ogohlantirish(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    make_rich(_isolated_meetings, ready)
    assert "Transkript bu xulosadan keyin" not in get_export(client, auth, mid, "md").text
    edited = client.patch(f"/api/v1/meetings/{mid}/segments/1", headers=auth, json={"text": "Tahrirlangan gap."})
    assert edited.status_code == 200
    md = get_export(client, auth, mid, "md").text
    assert "> Transkript bu xulosadan keyin o'zgartirilgan" in md and "Tahrirlangan gap." in md
    # Faqat transkript - ogohlantirish kerak emas (xulosa yo'q).
    assert "Transkript bu xulosadan" not in get_export(client, auth, mid, "md", parts="transcript").text


# --- qismlar, xulosasiz eksport va xatolar -----------------------------------------------------------------


def test_qismlar_tanlash(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    make_rich(_isolated_meetings, ready)
    only = get_export(client, auth, mid, "md", parts="actions,mindmap").text
    assert "## Vazifalar" in only and "## Aqliy xarita" in only
    assert "## Qisqacha" not in only and "## Transkript" not in only
    summary = get_export(client, auth, mid, "md", parts="summary").text
    assert "## Qisqacha" in summary and "## Vazifalar" not in summary and "## Aqliy xarita" not in summary
    transcript = get_export(client, auth, mid, "txt", parts="transcript").text
    assert "Transkript" in transcript and "Qisqacha" not in transcript and "Xulosa turi" not in transcript
    bad = get_export(client, auth, mid, "md", parts="summary,slides")
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_parts"
    assert get_export(client, auth, mid, "xls").status_code == 422


def test_xulosasiz_409_va_faqat_transkript(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    sid = ready["primarySummaryId"]
    assert client.delete(f"/api/v1/meetings/{mid}/summaries/{sid}", headers=auth).status_code == 200
    # Default - nima tayyor bo'lsa: faqat transkript.
    default = get_export(client, auth, mid, "md")
    assert default.status_code == 200
    assert "## Transkript" in default.text and "## Vazifalar" not in default.text
    for parts, missing in (("summary", ["summary"]), ("actions", ["actions"]), ("mindmap", ["mindmap"]),
                           ("summary,transcript", ["summary"]), ("brief", ["brief"])):
        refused = get_export(client, auth, mid, "pdf", parts=parts)
        assert refused.status_code == 409, parts
        body = refused.json()
        assert body["code"] == "not_ready" and body["missing"] == missing
        assert body["available"] == ["transcript"] and body["message"] == "Xulosa hali tayyor emas"
    assert get_export(client, auth, mid, "docx", parts="transcript").status_code == 200
    if FONTS:
        assert get_export(client, auth, mid, "pdf", parts="transcript").status_code == 200


def test_tanlangan_xulosa_tayyor_emas_va_yoq(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    sid = ready["primarySummaryId"]
    _isolated_meetings.store.update_summary(sid, status="running")
    pending = get_export(client, auth, mid, "md", summaryId=sid)
    assert pending.status_code == 409 and pending.json()["missing"] == ["summary"]
    # summaryId siz - asosiy xulosa tayyor emas, transkript beriladi.
    assert get_export(client, auth, mid, "md").status_code == 200
    unknown = get_export(client, auth, mid, "md", summaryId="f" * 32)
    assert unknown.status_code == 404 and unknown.json()["code"] == "summary_not_found"


def test_yuklanmagan_yigilish_409(client, auth, monkeypatch):
    enable(monkeypatch)
    m = create_meeting(client, auth)
    response = get_export(client, auth, m["id"], "pdf")
    assert response.status_code == 409 and response.json()["code"] == "not_ready"
    assert response.json()["available"] == []


def test_follow_up_xulosa_vazifalari_xulosadan(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    follow = client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth, json={"template": "follow_up"}).json()
    run_all(_isolated_meetings)
    md = get_export(client, auth, mid, "md", summaryId=follow["id"], parts="summary,actions").text
    headings = re.findall(r"^## (.+)$", md, flags=re.M)
    assert headings[:2] == ["Kuzatuv xabari", "Qisqacha"] and "Vazifalar" in headings
    assert "Rahmat!" in md and "Xulosa turi:** Kuzatuv xabari" in md


def test_izolyatsiya_404(client, auth, user_auth, monkeypatch, ready):
    enable(monkeypatch, logins="demo@venera.uz")
    mid = ready["id"]
    for fmt in ("md", "pdf"):
        other = get_export(client, user_auth, mid, fmt)
        assert other.status_code == 404 and other.json()["code"] == "not_found"
    assert get_export(client, user_auth, mid, "md", summaryId=ready["primarySummaryId"]).status_code == 404
    assert get_export(client, auth, "0" * 32, "md").status_code == 404
    assert get_export(client, auth, "../etc", "md").status_code == 404
    assert client.get(f"/api/v1/meetings/{mid}/audio?download=1", headers=user_auth).status_code == 404
    assert get_export(client, auth, mid, "md").status_code == 200


def test_bayroq_ochiq_va_ruxsat(client, auth, user_auth, monkeypatch, ready):
    mid = ready["id"]
    denied = get_export(client, user_auth, mid, "md")
    assert denied.status_code == 403 and denied.json()["code"] == "forbidden"
    monkeypatch.setattr(settings, "meetings_enabled", False)
    off = get_export(client, auth, mid, "pdf")
    assert off.status_code == 404 and off.json()["code"] == "not_found"
    assert client.get(f"/api/v1/meetings/{mid}/export?format=pdf").status_code == 401


def test_chegara_429(client, auth, ready, monkeypatch):
    monkeypatch.setattr(settings, "meetings_export_per_hour", 2)
    mid = ready["id"]
    # 409/400 chegarani yemaydi.
    assert get_export(client, auth, mid, "md", summaryId="f" * 32).status_code == 404
    assert get_export(client, auth, mid, "md", parts="nope").status_code == 400
    assert get_export(client, auth, mid, "md").status_code == 200
    assert get_export(client, auth, mid, "txt").status_code == 200
    limited = get_export(client, auth, mid, "pdf")
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) > 0


def test_pdf_shrift_yoq_503(client, auth, ready, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "meetings_export_font_dir", tmp_path / "no-fonts")
    mid = ready["id"]
    response = get_export(client, auth, mid, "pdf")
    assert response.status_code == 503 and response.json()["code"] == "pdf_unavailable"
    assert get_export(client, auth, mid, "docx").status_code == 200       # boshqa formatlar ishlaydi
    assert get_export(client, auth, mid, "md").status_code == 200


def test_kutubxona_yoq_503(client, auth, ready, monkeypatch):
    def missing(doc):
        raise export.RenderUnavailable("docx_unavailable", "test")

    monkeypatch.setattr(export_render, "docx_bytes", missing)
    response = get_export(client, auth, ready["id"], "docx")
    assert response.status_code == 503 and response.json()["code"] == "docx_unavailable"


# --- uzun transkript va "iflos" matn ----------------------------------------------------------------------------


@needs_fonts
def test_uzun_transkript_pdf_va_docx(client, auth, ready, _isolated_meetings):
    rt = _isolated_meetings
    mid = ready["id"]
    make_rich(rt, ready)
    rows = []
    long_word = "x" * 3000                                  # bo'shliqsiz uzun "so'z" (havola, xesh)
    for i in range(1, 1501):
        text = (f"{i}-gap: Oʻzbekcha gʻalaba va o'quv; по-русски тоже — ёжик & <tag> \"quote\". " * 3).strip()
        if i % 500 == 0:
            text += " " + long_word
        rows.append((mid, i, i * 7.0, i * 7.0 + 6.5, f"S{(i % 3) + 1}", text))
    rt.store.execute("DELETE FROM segments WHERE meeting_id=?", (mid,))
    with rt.store.transaction() as conn:
        conn.executemany('INSERT INTO segments (meeting_id, id, start, "end", speaker, text) VALUES (?,?,?,?,?,?)',
                         rows)
    # Juda uzun vazifa matni - PDF jadval qatori sahifaga sig'ishi kerak (qisqartiriladi).
    item = rt.store.action_items(mid)[0]
    rt.store.update_action_item(item["id"], task="Juda uzun vazifa " * 400)
    pdf = get_export(client, auth, mid, "pdf")
    assert pdf.status_code == 200, pdf.text
    facts = pdf_facts(pdf.content)
    assert facts["pages"] > 30 and "1500-gap: Oʻzbekcha gʻalaba" in facts["text"]
    assert "ёжик & <tag> \"quote\"" in facts["text"]
    docx = get_export(client, auth, mid, "docx")
    paragraphs, _ = docx_text(docx.content)
    assert sum(1 for _, t in paragraphs if t.startswith("[0")) == 1500
    md = get_export(client, auth, mid, "md", parts="transcript").text
    assert "&lt;" not in md and "<tag>" in md


def test_boshqaruv_belgilari_va_surrogat(client, auth, ready, _isolated_meetings):
    rt = _isolated_meetings
    mid = ready["id"]
    rt.store.execute("UPDATE segments SET text=? WHERE meeting_id=? AND id=1",
                     ("Salom\x00\x07\x0b dunyo\x1f tugadi", mid))
    rt.store.update_meeting(mid, title="Sarlavha\x01 / bilan: \"qo'shtirnoq\"")
    for fmt in ("docx", "pdf", "md", "txt"):
        response = get_export(client, auth, mid, fmt, parts="transcript")
        assert response.status_code == 200, (fmt, response.text)
    txt = get_export(client, auth, mid, "txt", parts="transcript")
    assert "Salom dunyo tugadi" in txt.text
    name = unquote(txt.headers["content-disposition"].split("''", 1)[1])
    assert name == "Sarlavha bilan qo'shtirnoq 2026-10-09.txt"


# --- birlik testlari ----------------------------------------------------------------------------------------------


def test_birlik_yordamchilar():
    assert export.parse_parts(None) is None and export.parse_parts(" , ") is None
    assert export.parse_parts("transcript, SUMMARY,summary") == ["summary", "transcript"]
    assert export.parse_parts("transcript,brief") == ["brief", "transcript"] and export.PARTS[0] == "brief"
    with pytest.raises(ValueError):
        export.parse_parts("summary,video")
    assert export.format_duration(3725, "uz") == "1 soat 2 daqiqa"
    assert export.format_duration(3600, "ru") == "1 ч"
    assert export.format_duration(42, "en") == "42 s"
    assert export.format_duration(113, "uz") == "1 daqiqa 53 soniya" and export.format_duration(120, "uz") == "2 daqiqa"
    assert export.format_duration(1513, "uz") == "25 daqiqa"            # uzun yozuvda soniya - shovqin
    moment = 1760000000.0                                    # 2025-10-09 08:53 UTC -> 13:53 Toshkent
    assert export.format_moment(moment, "uz") == "2025-yil 9-oktabr, 13:53"
    assert export.format_moment(moment, "ru") == "9 октября 2025, 13:53"
    assert export.format_moment(moment, "en") == "October 9, 2025, 13:53"
    assert export.file_names("Отчёт", moment, "pdf") == ("otchyot-2025-10-09.pdf", "Отчёт 2025-10-09.pdf")
    assert export.file_names("Yig'ilish: reja", 0, "md") == ("yigilish-reja.md", "Yig'ilish reja.md")
    # Bir xil sarlavha - ASCII tutuq yoki U+02BB bilan - BITTA nom; o'zbek kirilli ham lotinga.
    assert export.slug("Oʻquv markazi boʻyicha") == export.slug("O'quv markazi bo'yicha") == "oquv-markazi-boyicha"
    assert export.slug("Ўқув маркази ҳисоботи") == "oquv-markazi-hisoboti"
    assert export.slug("Релиз мобильного приложения") == "reliz-mobilnogo-prilozheniya"
    assert export.slug("🙂 ✓") == "meeting" and len(export.slug("x" * 300)) == 60
    assert export.content_disposition("a.pdf", "Ўз ҳисобот.pdf") == \
        "attachment; filename=\"a.pdf\"; filename*=UTF-8''%D0%8E%D0%B7%20%D2%B3%D0%B8%D1%81%D0%BE%D0%B1%D0%BE%D1%82.pdf"
    assert export.clean("a\x00b\tc\r\nd \ud83d") == "ab c\nd ?"
    assert export.one_line("  a \n b  ", 0) == "a b" and export.one_line("abcdef", 4) == "abc…"


def test_birlik_aqliy_xarita_shoxlari():
    content = rich_content("uz")
    tree = export.mindmap_tree("Yig'ilish", content, {}, "en",
                               [{"task": "Do it", "owner": "Aziz"}])
    assert tree["text"] == "Yig'ilish"
    assert [b["text"] for b in tree["children"]] == ["Reliz sanasi (decided)", "Byudjet (open)", "Decisions",
                                                     "Action items", "Open questions"]
    assert tree["children"][3]["children"] == [{"text": "Do it — Aziz", "children": []}]
    # Mavzusiz (qisqa qo'ng'iroq) - asosiy fikrlar shoxi; hech narsa yo'q - shoxsiz.
    short = {**content, "topics": [], "decisions": [], "openQuestions": []}
    assert [b["text"] for b in export.mindmap_tree("T", short, {}, "uz", None)["children"]] == ["Asosiy fikrlar"]
    assert export.mindmap_tree("T", {}, {}, "uz", None)["children"] == []


def test_birlik_render_xulosasiz_hujjat(tmp_path):
    doc = export.build_document(title="Faqat matn", recorded_at=0, duration_sec=0, speakers={}, lang="xx",
                                now=1760000000.0, parts=["transcript"],
                                segments=[{"start": 1.0, "speaker": None, "text": "Salom"}])
    assert doc.lang == "uz" and doc.meta == []
    assert [b["kind"] for b in doc.blocks] == ["h2", "muted", "transcript"]
    assert export.render(doc, "txt").decode("utf-8").startswith("Faqat matn\n==========\n")
    if FONTS:
        assert export.render(doc, "pdf", font_dir=export_render.DEFAULT_FONT_DIR).startswith(b"%PDF")
    with pytest.raises(export.RenderUnavailable) as caught:
        export.render(doc, "pdf", font_dir=tmp_path)
    assert caught.value.code == "pdf_unavailable"


# --- audio: ulashish uchun yuklab olish -----------------------------------------------------------------------


def test_audio_yuklab_olish(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    _isolated_meetings.store.update_meeting(mid, title="Haftalik reja", title_source="user")
    play = client.get(f"/api/v1/meetings/{mid}/audio", headers=auth)
    assert play.status_code == 200 and "content-disposition" not in play.headers
    download = client.get(f"/api/v1/meetings/{mid}/audio?download=1", headers=auth)
    assert download.status_code == 200 and download.headers["content-type"] == "audio/mp4"
    assert download.headers["content-disposition"] == \
        "attachment; filename=\"haftalik-reja-2026-10-09.m4a\"; filename*=UTF-8''Haftalik%20reja%202026-10-09.m4a"
    # Shaxsiy yozuv - oraliq kesh saqlamasin (eksport fayli bilan bir xil).
    assert download.headers["cache-control"] == "private, no-store"
    assert download.content == play.content and download.content[4:8] == b"ftyp"
    part = client.get(f"/api/v1/meetings/{mid}/audio?download=1", headers={**auth, "Range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10
    assert client.get(f"/api/v1/meetings/{mid}/audio?download=2", headers=auth).status_code == 422


# --- ko'rib chiqish tuzatishlari (2026-10-10) ------------------------------------------------------------------


def test_bir_odam_bir_vaqtda_bitta_eksport_429(client, auth, ready, monkeypatch):
    """Sync endpoint: parallel so'rovlar threadpool'ni band qilmasin - o'sha odamning ikkinchi
    eksporti kutmaydi, darhol 429 `export_busy`; rad etilgani soatlik chegarani yemaydi."""
    monkeypatch.setattr(settings, "meetings_export_per_hour", 2)
    mid = ready["id"]
    entered, release = threading.Event(), threading.Event()
    real = export.render

    def slow(doc, fmt, **kw):
        entered.set()
        assert release.wait(10)
        return real(doc, fmt, **kw)

    monkeypatch.setattr(export, "render", slow)
    first: dict = {}
    worker = threading.Thread(target=lambda: first.update(response=get_export(client, auth, mid, "md")))
    worker.start()
    try:
        assert entered.wait(10)
        busy = get_export(client, auth, mid, "txt")
        assert busy.status_code == 429 and busy.json()["code"] == "export_busy"
        assert int(busy.headers["Retry-After"]) > 0
    finally:
        release.set()
        worker.join(10)
    assert first["response"].status_code == 200
    monkeypatch.setattr(export, "render", real)
    assert get_export(client, auth, mid, "md").status_code == 200          # 2-chi fayl - chegara ichida
    assert get_export(client, auth, mid, "md").status_code == 429          # 3-chisi - soatlik chegara


def test_eksport_navbati_toldi_503(monkeypatch):
    from app.services.meetings import service
    from app.services.meetings.errors import MeetingProblem

    monkeypatch.setattr(settings, "meetings_export_concurrency", 1)
    monkeypatch.setattr(settings, "meetings_export_wait_sec", 0.05)
    with service._export_slot(101):
        with pytest.raises(MeetingProblem) as other:
            with service._export_slot(102):
                pass
        assert other.value.status_code == 503 and other.value.code == "export_busy"
        assert other.value.headers["Retry-After"] == "10"
        with pytest.raises(MeetingProblem) as same:
            with service._export_slot(101):
                pass
        assert same.value.status_code == 429
    # Slot bo'shadi, navbatdan chiqqan odam ham qolib ketmadi.
    with service._export_slot(102):
        pass
    assert service._export_active == 0 and not service._export_users


@needs_fonts
def test_pdf_navbati_band_503(client, auth, ready, monkeypatch):
    monkeypatch.setattr(export_render, "PDF_WAIT_SEC", 0.05)
    assert export_render._pdf_lock.acquire(timeout=5)
    try:
        busy = get_export(client, auth, ready["id"], "pdf")
    finally:
        export_render._pdf_lock.release()
    assert busy.status_code == 503 and busy.json()["code"] == "export_busy"
    assert busy.headers["Retry-After"] == "10"
    assert get_export(client, auth, ready["id"], "pdf").status_code == 200


def test_boshqaruv_belgili_spiker_nomi_docx(client, auth, ready, _isolated_meetings):
    """Eski yozuvdagi `Aziz\x01` ismi iqtibos va shablon bo'limida (standup) - DOCX 500 bermaydi."""
    rt = _isolated_meetings
    mid = ready["id"]
    sid = make_rich(rt, ready)
    content = rich_content("uz")
    content["templateSections"] = [
        {"key": "done", "items": [{"text": "Testlar yozildi", "speaker": "S1", "sourceSegmentIds": [1], "start": 0.0}]},
        {"key": "blockers", "items": [{"text": "Server yo'q", "speaker": "S2", "sourceSegmentIds": [2], "start": 6.5}]},
    ]
    rt.store.update_summary(sid, content_json=jdump(content), template="standup")
    rt.store.execute("UPDATE speakers SET name=? WHERE meeting_id=? AND id=?", ("Aziz\x01\uffff", mid, "S1"))
    rt.store.execute("UPDATE speakers SET name=? WHERE meeting_id=? AND id=?", ("Dil\x1bnoza", mid, "S2"))
    docx = get_export(client, auth, mid, "docx")
    assert docx.status_code == 200, docx.text
    texts = [text for _, text in docx_text(docx.content)[0]]
    assert "Aziz: Testlar yozildi" in texts and "Dilnoza: Server yo'q" in texts
    assert "«Relizni boshqa surmaymiz» — Aziz (00:14)" in texts
    for fmt in ("md", "txt") + (("pdf",) if FONTS else ()):
        assert get_export(client, auth, mid, fmt).status_code == 200, fmt
    # API orqali endi bunday ism saqlanmaydi.
    renamed = client.patch(f"/api/v1/meetings/{mid}/speakers/S3", headers=auth, json={"name": "Jav\x07lon\x01"})
    assert renamed.status_code == 200
    assert {sp["id"]: sp["name"] for sp in renamed.json()["speakers"]}["S3"] == "Javlon"


def test_docx_ustun_kengligi_uslub_va_til(client, auth, ready, _isolated_meetings):
    make_rich(_isolated_meetings, ready)
    data = get_export(client, auth, ready["id"], "docx").content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = z.read("word/document.xml").decode()
        styles = z.read("word/styles.xml").decode()
        core = z.read("docProps/core.xml").decode()
    # LibreOffice / Google Docs / WPS `gridCol` ni o'qiydi - teng emas, vazifa ustuni eng keng.
    grid = [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"/>', body)]
    assert len(grid) == 6 and len(set(grid)) > 1 and grid[1] == max(grid)
    width = re.search(r'<w:tblW w:type="dxa" w:w="(\d+)"/>', body)
    assert width and abs(int(width.group(1)) - sum(grid)) <= 6
    assert '<w:shd w:val="clear" w:color="auto" w:fill="EEF2FF"/>' in body
    # Bitta sans shrift (mavzu shriftlari o'chirilgan), Title ostida chiziq yo'q, matn tili o'zbekcha.
    defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S).group(0)
    assert 'w:ascii="Arial"' in defaults and "Theme" not in defaults and 'w:val="uz-Latn-UZ"' in defaults
    title = re.search(r'<w:style [^>]*w:styleId="Title".*?</w:style>', styles, re.S).group(0)
    assert "<w:pBdr>" not in title and "majorHAnsi" not in title and 'w:val="111827"' in title
    heading = re.search(r'<w:style [^>]*w:styleId="Heading1".*?</w:style>', styles, re.S).group(0)
    assert 'w:val="3730A3"' in heading and 'w:before="280"' in heading
    assert "<dc:language>uz-Latn-UZ</dc:language>" in core
    assert "<w:noProof/>" in body                                           # transkript - imlo tekshiruvisiz
    footer = [n for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.startswith("word/footer")]
    footer_xml = zipfile.ZipFile(io.BytesIO(data)).read(footer[0]).decode()
    assert 'w:instr="PAGE"' in footer_xml and 'w:instr="NUMPAGES"' in footer_xml
    # Ruscha xulosa (ilova inglizcha) - Word ruscha imlo bilan tekshiradi.
    doc = export.build_document(title="T", recorded_at=0, duration_sec=60, speakers={}, lang="en", now=0,
                                parts=["summary"], template="general", content=rich_content("ru"))
    assert doc.text_lang == "ru"
    with zipfile.ZipFile(io.BytesIO(export.render(doc, "docx"))) as z:
        assert 'w:val="ru-RU"' in z.read("word/styles.xml").decode()
    transcript_only = export.build_document(title="T", recorded_at=0, duration_sec=0, speakers={}, lang="uz",
                                            now=0, parts=["transcript"], segments=[], text_lang="ru")
    assert transcript_only.text_lang == "ru"


@needs_fonts
def test_pdf_xatchop_va_sahifa_raqami(client, auth, ready, _isolated_meetings):
    rt = _isolated_meetings
    make_rich(rt, ready)
    done = {r["summary_item_id"]: r for r in rt.store.action_items(ready["id"])}["A3"]
    rt.store.update_action_item(done["id"], status="done")
    data = get_export(client, auth, ready["id"], "pdf").content
    facts = pdf_facts(data)
    # Har bo'lim - xatcho'p (telefonda uzun transkriptdan "Vazifalar" ga bir bosishda).
    assert b"/Outlines" in data
    for title in (b"Qisqa xulosa", b"Vazifalar", b"Aqliy xarita", b"Transkript"):
        assert b"/Title (" + title + b")" in data, title
    pages = facts["pages"]
    assert f"1 / {pages}" in facts["text"] and f"{pages} / {pages}" in facts["text"]
    assert "Toshkent vaqti" in facts["text"]
    assert "⚠ aniqlashtirish kerak" in facts["text"] and "✓ bajarildi" in facts["text"]


def test_birlik_transkript_birlashtirish():
    speakers = {"S1": {"id": "S1", "name": "Aziz", "merged_into": None},
                "S2": {"id": "S2", "name": None, "merged_into": None}}
    segments = [{"start": 0.0, "end": 2.0, "speaker": "S1", "text": "Salom."},
                {"start": 2.5, "end": 4.0, "speaker": "S1", "text": "Boshlaymiz."},       # 0.5 s - qo'shiladi
                {"start": 9.0, "end": 10.0, "speaker": "S1", "text": "Pauzadan keyin."},  # 5 s - yangi paragraf
                {"start": 10.2, "end": 11.0, "speaker": "S2", "text": "Ha."},
                {"start": 11.1, "end": 12.0, "speaker": "S1", "text": "  "},              # bo'sh - tashlanadi
                {"start": 12.1, "end": 13.0, "speaker": "S1", "text": "Davom."}]
    assert export.transcript_lines(segments, speakers, "uz", export.clock) == [
        ("00:00", "Aziz", "Salom. Boshlaymiz."), ("00:09", "Aziz", "Pauzadan keyin."),
        ("00:10", "2-ishtirokchi", "Ha."), ("00:12", "Aziz", "Davom.")]
    # Paragraf cheksiz cho'zilmaydi (`MERGE_CHARS`).
    monolog = [{"start": i * 1.0, "end": i * 1.0 + 0.9, "speaker": "S1", "text": "a" * 500} for i in range(4)]
    assert [len(t) for _, _, t in export.transcript_lines(monolog, speakers, "uz")] == [1001, 1001]


def test_birlik_vaqt_formati_hujjat_boylab_bir_xil():
    content = rich_content("uz")
    segments = [{"start": 14.5, "end": 16.0, "speaker": None, "text": "Salom"}]

    def text(duration: float) -> str:
        return export.render_text(export.build_document(
            title="T", recorded_at=0, duration_sec=duration, speakers={}, lang="uz", now=0, parts=list(export.PARTS),
            template="general", content=content, segments=segments))

    short, long = text(600), text(3700)
    assert "Reliz 17-oktyabr kuni chiqariladi [yakuniy] (00:14)" in short and "[00:14] Salom" in short
    assert "chiqariladi [yakuniy] (00:00:14)" in long and "[00:00:14] Salom" in long and "(00:14)" not in long


def test_birlik_ochiq_savol_takrorlanmaydi():
    content = rich_content("uz")
    question = "Reklama byudjeti qancha bo'ladi?"

    def build(c: dict) -> tuple[list[str], str]:
        doc = export.build_document(title="T", recorded_at=0, duration_sec=60, speakers={}, lang="uz", now=0,
                                    parts=["summary", "mindmap"], template="general", content=c)
        return [b["text"] for b in doc.blocks if b["kind"] == "h2"], export.render_text(doc)

    headings, text = build(content)
    # "Hal qilinmagan masalalar" (sababi bilan) + aqliy xarita; "Ochiq savollar" bo'limi takrorlamaydi.
    assert "Ochiq savollar" not in headings and text.count(question) == 2
    headings, text = build({**content, "followUps": []})
    assert "Ochiq savollar" in headings
    extra = {**content, "openQuestions": content["openQuestions"] + [{"id": "Q2", "text": "Kim test qiladi?",
                                                                      "start": 5.0}]}
    headings, text = build(extra)
    assert "Ochiq savollar" in headings and "- Kim test qiladi? (00:05)" in text and text.count(question) == 2


def test_birlik_juda_uzun_sarlavha_docx():
    """python-docx `core_properties.title` 255 dan oshsa ValueError (va sarlavha logga) - chegara."""
    from docx import Document

    doc = export.build_document(title="Sarlavha " * 3000, recorded_at=0, duration_sec=0, speakers={}, lang="uz",
                                now=0, parts=["transcript"], segments=[])
    assert len(doc.title) == export.TITLE_CHARS
    assert Document(io.BytesIO(export.render(doc, "docx"))).core_properties.title == doc.title
    long_doc = export.Document(lang="uz", title="x" * 5000)
    assert len(Document(io.BytesIO(export_render.docx_bytes(long_doc))).core_properties.title) == 255


# --- "Qisqa xulosa" (brief, 2026-10-10) ------------------------------------------------------------------------

BRIEF_UZ = """**Mobil ilova relizi bo'yicha haftalik yig'ilish**  
9-oktabr 2026 (juma), 11:00 · 1 daq 4 s · 3 ishtirokchi

**Maqsad:** Reliz sanasi va mas'ullarni kelishib olish.

**Qisqacha:** Aziz va Dilnoza mobil ilovaning 1.2 versiyasi relizini muhokama qildi. Reliz 17-oktyabrga belgilandi, testlar seshanbagacha yakunlanadi.

**Asosiy fikr:**
- Reliz boshqa surilmaydi.

**Qarorlar:**
- Reliz 17-oktyabr kuni chiqariladi.
- Push-bildirishnomalar keyingi versiyaga (taxminiy, aniqlashtirish kerak).

**Vazifalar:**
- Test hisobotini tayyorlash. Mas'ul: Dilnoza. Muddat: 14-oktabr.
- Play Market sahifasini yangilash. Mas'ul: Aziz. Muddat: 16-oktabr, 18:00. (aniqlashtirish kerak)
- ✓ Buxgalteriyadan byudjetni so'rash. Mas'ul: Javlon. Muddat: keyingi hafta.

**Ochiq savol:**
- Reklama byudjeti qancha bo'ladi?
"""


def test_qisqa_xulosa_yolgiz_md_va_txt(client, auth, ready, _isolated_meetings):
    """`parts=brief` - fayl aynan foydalanuvchi sevgan ko'rinish: hujjat sarlavhasi, "Sana:" qatorlari
    va pastki yozuvsiz (ulashish uchun). Vazifalar - JONLI jadvaldan (bajarilgani "✓")."""
    rt = _isolated_meetings
    mid = ready["id"]
    make_rich(rt, ready)
    name_speakers(client, auth, mid, S1="Aziz", S2="Dilnoza")
    done = {r["summary_item_id"]: r for r in rt.store.action_items(mid)}["A3"]
    rt.store.update_action_item(done["id"], status="done")
    md = get_export(client, auth, mid, "md", parts="brief")
    assert md.status_code == 200, md.text
    assert md.text == BRIEF_UZ
    txt = get_export(client, auth, mid, "txt", parts="brief").text
    assert txt == BRIEF_UZ.replace("**", "").replace("  \n", "\n")
    assert unquote(md.headers["content-disposition"].split("''", 1)[1]) == \
        "Mobil ilova relizi bo'yicha haftalik yig'ilish 2026-10-09.md"


def test_qisqa_xulosa_yolgiz_docx_va_pdf(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    make_rich(_isolated_meetings, ready)
    docx = get_export(client, auth, mid, "docx", parts="brief")
    assert docx.status_code == 200, docx.text
    paragraphs, tables = docx_text(docx.content)
    assert tables == [] and not any(text.startswith("Sana:") for _, text in paragraphs)
    assert paragraphs[:4] == [("Title", "Mobil ilova relizi bo'yicha haftalik yig'ilish"),
                              ("Normal", "9-oktabr 2026 (juma), 11:00 · 1 daq 4 s · 3 ishtirokchi"),
                              ("Normal", "Maqsad: Reliz sanasi va mas'ullarni kelishib olish."),
                              ("Normal", "Qisqacha: 1-ishtirokchi va 2-ishtirokchi mobil ilovaning 1.2 versiyasi "
                                         "relizini muhokama qildi. Reliz 17-oktyabrga belgilandi, testlar "
                                         "seshanbagacha yakunlanadi.")]
    at = paragraphs.index(("Normal", "Vazifalar:"))
    # Ismsiz spiker - "2-ishtirokchi" (foydalanuvchi namunasi: "Mas'ul: 2-ishtirokchi").
    assert paragraphs[at + 1] == ("List Bullet", "Test hisobotini tayyorlash. Mas'ul: 2-ishtirokchi. "
                                                 "Muddat: 14-oktabr.")
    assert ("List Bullet", "Reklama byudjeti qancha bo'ladi?") in paragraphs
    if not FONTS:
        return
    pdf = get_export(client, auth, mid, "pdf", parts="brief")
    assert pdf.status_code == 200, pdf.text
    facts = pdf_facts(pdf.content)
    assert facts["pages"] == 1 and facts["dejavu"] and not facts["helvetica"]
    for needle in ("9-oktabr 2026 (juma), 11:00 · 1 daq 4 s · 3 ishtirokchi", "Maqsad:", "Asosiy fikr:",
                   "Mas'ul: 2-ishtirokchi. Muddat: 14-oktabr.", "Ochiq savol:", "1 / 1"):
        assert needle in facts["text"], needle
    assert "Sana:" not in facts["text"] and "Transkript" not in facts["text"]


@pytest.mark.parametrize("fmt", ["md", "txt", "docx", pytest.param("pdf", marks=needs_fonts)])
def test_har_eksport_qisqa_xulosa_bilan_boshlanadi(client, auth, ready, _isolated_meetings, fmt):
    mid = ready["id"]
    make_rich(_isolated_meetings, ready)
    response = get_export(client, auth, mid, fmt)
    assert response.status_code == 200, response.text
    if fmt == "docx":
        paragraphs, _ = docx_text(response.content)
        headings = [text for style, text in paragraphs if style == "Heading 1"]
        assert headings[:2] == ["Qisqa xulosa", "Vazifalar"]
        at = paragraphs.index(("Heading 1", "Qisqa xulosa"))
        # Hujjat boshida sarlavha va sana bor - blok ularni takrorlamaydi.
        assert paragraphs[at + 1] == ("Normal", "Maqsad: Reliz sanasi va mas'ullarni kelishib olish.")
        return
    text = response.text if fmt in ("md", "txt") else pdf_facts(response.content)["text"]
    first = text.index("Qisqa xulosa")
    assert first < text.index("Maqsad:") < text.index("Vazifalar") < text.index("Aqliy xarita")
    assert text.count("9-oktabr 2026 (juma)") == 0 and "Sana:" in text
    if fmt == "md":
        assert "## Qisqa xulosa\n\n**Maqsad:** Reliz sanasi" in text and "## Qisqacha" not in text
        assert "**Vazifalar:**\n- Test hisobotini tayyorlash. Mas'ul: 2-ishtirokchi. Muddat: 14-oktabr.\n" in text


def test_qisqa_xulosa_uzun_xulosani_qisqartiradi_va_bolimni_saqlaydi():
    """Eski xulosa (umumiy xulosa 3-5 gap, 8 ta fikr): blokda 2 gap va 6 fikr, to'liq matn esa
    "Qisqacha"/"Asosiy fikrlar" bo'limlarida qoladi (takrorlanmaydigan qismi yo'qolmasin)."""
    content = rich_content("uz")
    content["overview"] = ("Birinchi gap 15 mln. so'm haqida. [S1] ikkinchi gapni aytdi! Uchinchi gap "
                           "ham bor. To'rtinchisi.")
    content["keyPoints"] = [{"id": f"K{i}", "text": f"Fikr {i}.", "sourceSegmentIds": [1], "start": 0.0}
                            for i in range(1, 9)]
    doc = export.build_document(title="T", recorded_at=0, duration_sec=60, speakers={}, lang="uz", now=0,
                                parts=["brief", "summary"], template="general", content=content)
    text = export.render_text(doc)
    assert "Qisqacha: Birinchi gap 15 mln. so'm haqida. 1-ishtirokchi ikkinchi gapni aytdi!\n" in text
    assert "\nQisqacha\n--------\nBirinchi gap 15 mln. so'm haqida. 1-ishtirokchi ikkinchi gapni aytdi! " \
           "Uchinchi gap ham bor. To'rtinchisi.\n" in text
    brief = text.split("Qisqa xulosa")[1].split("\nQisqacha\n")[0]
    assert "- Fikr 6." in brief and "Fikr 7." not in brief
    assert "\nAsosiy fikrlar\n" in text and "- Fikr 8." in text
    # Faqat `summary` - avvalgidek, blok va qisqartirish yo'q.
    only = export.render_text(export.build_document(
        title="T", recorded_at=0, duration_sec=60, speakers={}, lang="uz", now=0, parts=["summary"],
        template="general", content=rich_content("uz")))
    assert "Qisqa xulosa" not in only and "\nQisqacha\n" in only and "\nAsosiy fikrlar\n" in only


def test_birlik_qisqa_xulosa_tillar_va_shakllar():
    content = rich_content("ru")
    actions = export.actions_from_content(content, {}, "ru")
    block = export.brief_block(content, {}, "ru", actions, title="Релиз", meta="m")
    labels = [item["label"] for item in block["items"]]
    # Bitta asosiy fikr - birlikda ("Vazifa:", "Ochiq savol:" kabi; mobil ilova bilan bir xil).
    assert labels == ["Цель", "Кратко", "Ключевой момент", "Решения", "Задачи", "Открытый вопрос"]
    assert block["items"][3]["list"] == ["Релиз 17 октября.",
                                         "Push-уведомления позже (предварительно, требует уточнения)."]
    tasks = block["items"][4]["list"]
    assert tasks[0] == "Подготовить отчёт о тестах. Ответственный: Участник 2. Срок: 14 октября."
    assert tasks[2] == "Запросить бюджет у бухгалтерии. Ответственный: Javlon. Срок: keyingi hafta."
    en = export.brief_block(rich_content("uz"), {}, "en", [{"task": "Send the script", "owner": "", "due": ""}])
    assert [i["label"] for i in en["items"]] == ["Purpose", "In short", "Key point", "Decisions", "Action item",
                                                 "Open question"]
    assert en["items"][4]["list"] == ["Send the script. No owner set. No due date."]
    assert en["items"][3]["list"][1] == "Push-bildirishnomalar keyingi versiyaga (tentative, needs confirmation)."
    team = export.brief_block({}, {}, "uz", [{"task": "Narxni kelishish;", "owner": "", "due": "", "team": True,
                                              "check": True}])
    assert team["items"][0]["list"] == ["Narxni kelishish. Mas'ul: Jamoa. Muddat belgilanmagan. (aniqlashtirish kerak)"]
    # Bekor qilingan qaror blokka kirmaydi; bo'sh bandlar tushib qoladi.
    bare = export.brief_block({"decisions": [{"text": "Eski", "status": "reversed"}], "keyPoints": []}, {}, "uz", [])
    assert bare["items"] == []
    # Mavzusiz eski xulosa - mavzular ichidagi fikrlar.
    legacy = {**rich_content("uz"), "keyPoints": []}
    points = [i for i in export.brief_block(legacy, {}, "uz", None)["items"] if i["label"].startswith("Asosiy")]
    assert points[0]["list"] == ["Reliz 17-oktyabr kuni.", "Testlar seshanbagacha."]
    titles = {**legacy, "topics": [{"title": "Byudjet", "summary": "", "keyPoints": []}]}
    assert export.brief_block(titles, {}, "uz", None)["items"][2]["list"] == ["Byudjet."]
    assert [export.people_count(n, "ru") for n in (1, 2, 5, 11, 21, 22, 112)] == [
        "1 участник", "2 участника", "5 участников", "11 участников", "21 участник", "22 участника",
        "112 участников"]
    assert export.people_count(1, "en") == "1 participant" and export.people_count(3, "uz") == "3 ishtirokchi"
    assert [export.brief_duration(s, "uz") for s in (113, 120, 42, 3725, 3600, 112.5, 0.3)] == [
        "1 daq 53 s", "2 daq", "42 s", "1 soat 2 daq", "1 soat", "1 daq 53 s", "1 s"]
    assert export.brief_duration(113, "ru") == "1 мин 53 с"
    moment = 1760000000.0                                    # 2025-10-09 13:53 Toshkent (payshanba)
    assert export.brief_moment(moment, "uz") == "9-oktabr 2025 (payshanba), 13:53"
    assert export.brief_moment(moment, "ru") == "9 октября 2025 (четверг), 13:53"
    assert export.brief_moment(moment, "en") == "October 9, 2025 (Thursday), 13:53"
    assert export.brief_meta(0, 0, 0, "uz") == "" and export.brief_meta(0, 65, 2, "en") == "1 min 5 s · 2 participants"
    assert export.first_sentences("Bir. Ikki? Uch.") == "Bir. Ikki?"
    assert export.first_sentences("Narx 15 mln. so'm, versiya 1.2 bo'ladi. Keyin.", 1) == \
        "Narx 15 mln. so'm, versiya 1.2 bo'ladi."


def test_qisqa_xulosa_ochiq_savollarni_takrorlatmaydi():
    """Blokda hamma ochiq savol bor - to'liq hujjatdagi "Ochiq savollar" bo'limi faqat vaqt qo'shardi
    (qisqa qo'ng'iroqda ikki marta so'zma-so'z). Qarorlar bo'limi esa (holat, shart, sabab) qoladi."""
    content = {**rich_content("uz"), "followUps": []}

    def headings(parts: list[str]) -> list[str]:
        doc = export.build_document(title="T", recorded_at=0, duration_sec=60, speakers={}, lang="uz", now=0,
                                    parts=parts, template="general", content=content)
        return [b["text"] for b in doc.blocks if b["kind"] == "h2"]

    assert "Ochiq savollar" in headings(["summary"])
    with_brief = headings(["brief", "summary"])
    assert "Ochiq savollar" not in with_brief and "Qarorlar" in with_brief
    assert export.brief_covers(content, {}, "uz") >= {"openQuestions", "keyPoints"}

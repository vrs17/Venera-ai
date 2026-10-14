"""Javob ostidagi manbalar: odamga faqat hujjatlar (ega qarori, 2026-10-14)."""

from __future__ import annotations

import json

from app.bot import render
from app.services.answer_sources import client_view, documents, is_lookup, only_documents

DOC = {"kind": "doc", "citation_index": 1, "doc_id": "HR_045", "title": "Ichki mehnat tartibi"}
LAW = {"kind": "law", "citation_index": 2, "url": "https://www.lex.uz/docs/6257288#6260108"}
GUIDE = {"kind": "biznes247_kb", "citation_index": 3, "title": "Depozit ochish"}
CRM = {"kind": "crm", "marker": "T1", "tool": "crm_my_issues"}
HRM = {"kind": "hrm", "marker": "T2", "tool": "hrm_my_employee"}
DWH = {"kind": "dwh", "marker": "T1"}
KB_LOOKUP = {"kind": "biznes247_kb"}  # raqamsiz - so'rov
NO_KIND_TOOL = {"tool": "work_activity", "marker": "T3"}


def _line(frame: dict) -> bytes:
    return json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n"


def test_qaysi_manba_hujjat():
    for source in (DOC, LAW, GUIDE):
        assert not is_lookup(source), source
    for source in (CRM, HRM, DWH, KB_LOOKUP, NO_KIND_TOOL, "satr", None):
        assert is_lookup(source), source


def test_aralash_kadrdan_sorovlar_olib_tashlanadi():
    out = only_documents(_line({"type": "sources", "sources": [CRM, DOC, DWH, LAW]}))
    frame = json.loads(out)
    assert frame["sources"] == [DOC, LAW]
    assert out.endswith(b"\n")


def test_faqat_sorovli_kadr_umuman_yuborilmaydi():
    assert only_documents(_line({"type": "sources", "sources": [CRM, HRM]})) == b""
    assert only_documents(_line({"type": "sources", "items": [DWH]})) == b""


def test_boshqa_kadrlar_baytma_bayt_ozgarmaydi():
    chunk = b'{"type":"token","text":"Salom"}\n{"type":"stage","name":"tools"}\n'
    assert only_documents(chunk) is chunk
    # "sources" so'zi matn ichida bo'lsa ham token kadri tegilmaydi.
    token = _line({"type": "token", "text": "manbalar - sources"})
    assert only_documents(token) == token


def test_hujjatli_kadr_ozgarmasa_asl_baytlar_qaytadi():
    line = _line({"type": "sources", "sources": [DOC, LAW]})
    assert only_documents(line) == line


def test_bir_bolakda_bir_necha_kadr():
    chunk = (b'{"type":"token","text":"A"}\n' + _line({"type": "sources", "sources": [CRM]})
             + b'{"type":"done"}\n')
    assert only_documents(chunk) == b'{"type":"token","text":"A"}\n{"type":"done"}\n'


def test_client_view_ichki_oqimni_yopadi():
    closed = []

    def inner():
        try:
            yield _line({"type": "token", "text": "x"})
            yield _line({"type": "sources", "sources": [CRM]})
            yield _line({"type": "done"})
        finally:
            closed.append(True)

    view = client_view(inner())
    assert next(view) == _line({"type": "token", "text": "x"})
    # Klient uzildi - ichki oqim (recorder `cancelled`, slot qaytishi) yopilishi shart.
    view.close()
    assert closed == [True]


def test_client_view_soroq_kadrini_tashlab_ketadi():
    frames = [_line({"type": "sources", "sources": [CRM, DOC]}), _line({"type": "sources", "sources": [DWH]}),
              _line({"type": "done"})]
    out = list(client_view(iter(frames)))
    assert [json.loads(x)["type"] for x in out] == ["sources", "done"]
    assert json.loads(out[0])["sources"] == [DOC]


def test_bot_ham_bir_xil_qoida():
    assert render.doc_sources([DOC, CRM, DWH, LAW, GUIDE, KB_LOOKUP]) == [DOC, LAW, GUIDE]
    assert documents("emas") == []

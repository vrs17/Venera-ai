"""Xulosa ko'rinishi: har fakt bir marta (`compact`, ega qarori 2026-10-15).

Namuna - real 8,5 daqiqalik "aqliy hujum" yig'ilishi (2026-10-14): bitta fakt ("ChatGPT
javoblarini yig'ib Gemini'ni o'qitish") vazifa, asosiy fikr, g'oya, afzallik, tanlangan va
mavzu ichida - 6 marta yozilgan edi.
"""

from __future__ import annotations

import copy

from app.services.meetings.compact import COMPACT_VERSION, compact
from app.services.meetings.store import jdump
from test_meetings_export import make_rich, ready  # noqa: F401 - pytest fiksturasi


def _ev(*ids: int) -> dict:
    return {"sourceSegmentIds": list(ids), "start": float(ids[0]) if ids else None}


def brainstorm() -> dict:
    return {
        "language": "uz", "template": "brainstorm",
        "meeting": {"durationSec": 512.0},
        "overview": "Gemini modelini ChatGPT ma'lumotlari asosida o'qitish va BRVtek uchun modullar muhokama qilindi.",
        "actionItems": [
            {"id": "A1", "task": "ChatGPT javoblarini yig'ib, Gemini modelini o'qitish (fine-tuning)",
             "quote": "BRVtek uchun", **_ev(11)},
            {"id": "A2", "task": "Audio yuklash funksiyasining minutlarini ko'paytirishni tekshirish", **_ev(23)},
        ],
        "decisions": [
            {"id": "D1", "text": "Bank va BRVtek uchun alohida tizimlar yaratish, HRni alohida qilish",
             "status": "final", **_ev(65, 67, 68)},
        ],
        "openQuestions": [
            {"id": "Q1", "text": "HR dokumentlarining 30 tasi nima uchun tizimga kirmagan?", **_ev(51, 61)},
        ],
        "keyPoints": [
            {"id": "K1", "text": "ChatGPT javoblarini yig'ib, Gemini modelini o'qitish orqali sifatni yaxshilash "
                                 "rejalashtirildi.", **_ev(11, 13)},
            {"id": "K2", "text": "Lokal model bilan to'liq Intelligent sistema yaratish qiyinligi tan olindi.",
             **_ev(18)},
            {"id": "K3", "text": "Bank, BRVtek va HR uchun alohida modullar/tizimlar yaratishga qaror qilindi.",
             **_ev(65, 68)},
            # Shu qatorlar, lekin BOSHQA fakt (topilma, savol emas) - qoladi.
            {"id": "K4", "text": "HR dokumentlarining 46 tasidan faqat 16 tasi ishlayotgani aniqlandi.",
             **_ev(51, 61)},
        ],
        "risks": [
            {"id": "R1", "text": "Lokal model bilan to'liq Intelligent sistema yaratishning imkonsizligi", **_ev(18)},
        ],
        "nextSteps": [{"id": "X1", "text": "Ma'lumotlar bazasini kopiya qilish", **_ev(44)}],
        "templateSections": [
            {"key": "ideas", "items": [
                {"text": "Model training: ChatGPT javoblarini yig'ib, Gemini'ni o'qitish", **_ev(11, 13)},
                {"text": "Struktura: Bank, BRVtek va HR uchun alohida modullar yaratish", **_ev(65, 68)}]},
            {"key": "pros", "items": [
                {"text": "ChatGPT javoblarini o'qitish orqali Gemini'ni yanada aqlliroq qilish mumkin", **_ev(13)}]},
            {"key": "cons", "items": [
                {"text": "Lokal model bilan to'liq intelligent sistema yaratish imkonsiz", **_ev(18)},
                {"text": "Ma'lumotlarni yig'ish va o'qitish uchun vaqt ketadi", **_ev(16)}]},
            {"key": "shortlist", "items": [
                {"text": "ChatGPT ma'lumotlarini yig'ish va Gemini'ni fine-tune qilish", **_ev(11, 20)},
                {"text": "Bank, BRVtek va HR uchun alohida tizimlar yaratish", **_ev(65)}]},
        ],
        "topics": [
            {"id": "T1", "title": "LLM modellarini solishtirish", "summary": "Gemini va ChatGPT farqlari.",
             "startSegmentId": 1, "endSegmentId": 40,
             "keyPoints": [{"text": "ChatGPT javoblarini yig'ib, Gemini modelini fine-tune qilish orqali sifatni "
                                    "oshirish rejalashtirildi.", **_ev(11, 13)}]},
        ],
        "highlights": [
            {"id": "H1", "quote": "Un Intelligenc sistema lokalniy model bilan qilinmaydi rostdan.", "speaker": "S1",
             "segmentId": 18, "start": 18.0, "why": "muhim xulosa", "fromMark": None},
            {"id": "H2", "quote": "Lokal model bilan bo'lmaydi", "speaker": "S1", "segmentId": 18, "start": 18.0,
             "why": "belgi", "fromMark": "M1"},
        ],
        "numbers": [{"id": "N1", "value": "46", "unit": "ta", "what": "HR dokumentlar soni", **_ev(51, 61)}],
        "followUps": [
            {"id": "F1", "kind": "openQuestion", "ref": "Q1", "text": "HR dokumentlarining 30 tasi?",
             "reasons": ["no_answer"]},
            {"id": "F2", "kind": "actionItem", "ref": "A1", "text": "ChatGPT javoblarini yig'ib", "reasons": ["no_due"]},
            {"id": "F3", "kind": "risk", "ref": "R1", "text": "Lokal model", "reasons": ["no_mitigation"]},
        ],
        "userMarks": [{"id": "M1", "t": 18.0, "segmentIds": [18], "coveredBy": ["K2", "R1", "H2"]}],
    }


def _texts(items: list[dict]) -> list[str]:
    return [i.get("task") or i.get("text") or i.get("quote") for i in items]


def test_bir_fakt_bir_marta_va_belgilar():
    out = compact(brainstorm())
    a1 = out["actionItems"][0]
    # Vazifa qoladi; g'oya, afzallik, tanlangan - belgi (asosiy fikr va mavzu - belgisiz, har faktga tegishli).
    assert [c["label"] for c in a1["alsoIn"]] == ["G'oya", "Afzallik", "Tanlangan"]
    assert [c["key"] for c in a1["alsoIn"]] == ["ideas", "pros", "shortlist"]
    assert [c["label"] for c in out["decisions"][0]["alsoIn"]] == ["G'oya", "Tanlangan"]
    # Asosiy fikr (kartada) xavfdan muhimroq: xavf va kamchilik unga belgi bo'ladi.
    assert [k["id"] for k in out["keyPoints"]] == ["K2", "K4"]
    assert [c["label"] for c in out["keyPoints"][0]["alsoIn"]] == ["Xavf", "Kamchilik"]
    assert out["risks"] == []
    groups = {g["key"]: _texts(g["items"]) for g in out["templateSections"]}
    # Bo'sh qolgan bo'lim yo'qoladi; o'xshashi yo'q kamchilik qoladi.
    assert groups == {"cons": ["Ma'lumotlarni yig'ish va o'qitish uchun vaqt ketadi"]}
    # Mavzu (bob) qoladi, ichidagi takror fikr - yo'q.
    assert out["topics"][0]["title"] == "LLM modellarini solishtirish" and out["topics"][0]["keyPoints"] == []
    # Odam belgilagan lahza HECH QACHON o'chmaydi; model tanlagan iqtibos - shu qatordagi fikr bilan bitta.
    assert [h["id"] for h in out["highlights"]] == ["H2"]
    # Vazifa, qaror, savol, raqam - o'chmaydi. Sanoq: 11 ta takror band + 2 ta kuzatuv (vazifa va savolniki).
    assert len(out["actionItems"]) == 2 and len(out["openQuestions"]) == 1 and len(out["numbers"]) == 1
    assert out["view"] == {"compact": COMPACT_VERSION, "merged": 13}


def test_bir_qator_boshqa_fakt_va_boshqa_qator_bir_matn():
    out = compact(brainstorm())
    # Q1 va K4 - bir xil qatorlar (51, 61), lekin savol va topilma: ikkalasi qoladi.
    assert "Q1" in [q["id"] for q in out["openQuestions"]] and "K4" in [k["id"] for k in out["keyPoints"]]
    # Matni bir xil, lekin transkriptning boshqa joyi - boshqa fakt.
    content = {"language": "uz", "keyPoints": [{"id": "K1", "text": "Narxni kelishish kerak", **_ev(5)}],
               "risks": [{"id": "R1", "text": "Narxni kelishish kerak", **_ev(90)}]}
    assert len(compact(content)["risks"]) == 1
    # Qatorsiz band - faqat juda o'xshash matn birlashadi.
    loose = {"language": "uz", "keyPoints": [{"id": "K1", "text": "Reliz sanasi 17-oktyabr", "sourceSegmentIds": []}],
             "nextSteps": [{"id": "X1", "text": "Reliz sanasi 17-oktyabr", "sourceSegmentIds": []},
                           {"id": "X2", "text": "Reliz uchun dizayn tayyorlash", "sourceSegmentIds": []}]}
    assert _texts(compact(loose)["nextSteps"]) == ["Reliz uchun dizayn tayyorlash"]


def test_vazifa_va_qaror_ochmaydi():
    content = {"language": "uz",
               "actionItems": [{"id": "A1", "task": "Narxni 15 mln so'mga kelishish", **_ev(7)}],
               "decisions": [{"id": "D1", "text": "Narxni 15 mln so'mga kelishish", "status": "final", **_ev(7)}]}
    out = compact(content)
    # Qaror ham vazifa ham "Qisqa xulosa" kartasida, CRM va holat ularga bog'langan - ikkalasi qoladi.
    assert len(out["actionItems"]) == 1 and len(out["decisions"]) == 1 and out["view"]["merged"] == 0


def test_kuzatuv_va_belgilar_qayta_bog_lanadi():
    out = compact(brainstorm())
    # Vazifa va savol kartada o'z holati bilan - kuzatuv ro'yxatida qayta chiqmaydi. Xavf fikrga
    # qo'shildi - kuzatuv shu fikrga ko'chadi.
    assert [(f["id"], f["ref"]) for f in out["followUps"]] == [("F3", "K2")]
    # Havolasiz kuzatuv o'zgarmaydi ("None" bo'lib qolmaydi).
    loose = compact({"language": "uz", "followUps": [{"id": "F1", "text": "Narx?", "ref": None, "reasons": []}]})
    assert loose["followUps"] == [{"id": "F1", "text": "Narx?", "ref": None, "reasons": []}]
    assert out["userMarks"][0]["coveredBy"] == ["K2", "H2"]


def test_nom_tuzatiladi_iqtibos_emas_va_asl_ozgarmaydi():
    raw = brainstorm()
    before = copy.deepcopy(raw)
    out = compact(raw)
    assert raw == before                                         # bazadagi xulosa o'zgarmaydi
    assert "BRB-Tech uchun modullar" in out["overview"]
    assert out["decisions"][0]["text"].startswith("Bank va BRB-Tech uchun")
    assert out["actionItems"][0]["quote"] == "BRVtek uchun"      # dalil so'zma-so'z qoladi
    assert compact(out) is out                                   # qayta qo'llash - o'zgarishsiz
    assert compact(None) is None and compact({}) == {}


def test_api_xulosa_va_eksport_bir_xil_korinish(client, auth, ready, _isolated_meetings):  # noqa: F811
    rt = _isolated_meetings
    sid = make_rich(rt, ready)
    rt.store.update_summary(sid, content_json=jdump(brainstorm()), template="brainstorm")
    body = client.get(f"/api/v1/meetings/{ready['id']}/summaries/{sid}", headers=auth).json()
    content = body["content"]
    assert content["view"]["compact"] == COMPACT_VERSION
    assert [k["id"] for k in content["keyPoints"]] == ["K2", "K4"]
    assert content["actionItems"][0]["alsoIn"][0]["label"] == "G'oya"
    # Bazada asl xulosa (model yozgani) - o'zgarmagan.
    assert len(__import__("json").loads(rt.store.summary(ready["id"], sid)["content_json"])["keyPoints"]) == 4
    md = client.get(f"/api/v1/meetings/{ready['id']}/summaries/{sid}/export?format=md", headers=auth).text
    # "ChatGPT javoblari" fakti 6 joyda yozilgan edi - faylda bir marta.
    assert md.count("javoblarini") == 1 and "BRB-Tech" in md and "BRVtek" not in md

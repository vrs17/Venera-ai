"""Model javoblarining JSON sxemalari - OpenAI "Structured Outputs" (`strict`) uchun.

NEGA. Promptdagi shakl (`prompts.EXTRACT_SHAPE`, ...) - modelga ko'rsatma, xolos:
gemma va v3 uni buzishi mumkin, shuning uchun JSON qutqariladi va har element
tekshiriladi (`summarize.parse_json`, `Validator`). OpenAI esa `strict` sxema
berilsa javobni AYNAN shu shaklda yozadi - kalitlar tartibi ham sxemadagidek
(ro'yxatlar birinchi, `title` va `overview` oxirida - 15-qoida). Tekshiruvchi
baribir ishlaydi: shakl to'g'ri bo'lishi mazmun to'g'riligini kafolatlamaydi.

SXEMA PROMPT BILAN BIR XIL: maydonlar `prompts._item_shapes` dagi tartib va
nomlarda. Prompt o'zgarsa, shu fayl ham o'zgaradi (`tests/test_meetings_llm.py`
ikkalasini solishtiradi).

`strict` QOIDALARI: har obyektda `additionalProperties: false` va HAMMA maydon
`required`; ixtiyoriy qiymat - `["string", "null"]` yoki `anyOf [..., null]`.
Enum ATAYLAB YO'Q: noma'lum qiymatni tekshiruvchi xavfsiz default'ga o'giradi,
sxema esa qanchalik sodda bo'lsa, xizmat uni rad etish ehtimoli shuncha kam.
"""

from __future__ import annotations

from typing import Any

STR: dict[str, Any] = {"type": "string"}
INT: dict[str, Any] = {"type": "integer"}
NUM: dict[str, Any] = {"type": "number"}
BOOL: dict[str, Any] = {"type": "boolean"}


def obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


def null(schema: dict[str, Any]) -> dict[str, Any]:
    """Qiymat yoki `null`."""
    kind = schema.get("type")
    if isinstance(kind, str) and kind not in ("object", "array"):
        return {**schema, "type": [kind, "null"]}
    return {"anyOf": [schema, {"type": "null"}]}


NSTR = null(STR)
IDS = arr(INT)


def _items(*, refs: bool) -> dict[str, Any]:
    """`prompts._item_shapes` ning sxemasi - o'sha tartibda."""
    ref = {"ref": NSTR} if refs else {}
    action = obj({
        "task": STR, "deliverable": NSTR, "condition": NSTR,
        "owner": obj({"speaker": NSTR, "name": NSTR, "kind": STR, "basis": STR}),
        "assignedBy": NSTR,
        "due": obj({"raw": NSTR, "date": NSTR, "time": NSTR, "basis": STR}),
        "priority": NSTR, "status": STR, "origin": STR, "quote": STR, "confidence": NUM,
        "sourceSegmentIds": IDS, **ref})
    decision = obj({"text": STR, "status": STR, "condition": NSTR, "rationale": NSTR, "proposedBy": arr(STR),
                    "agreedBy": arr(STR), "quote": STR, "sourceSegmentIds": IDS, **ref})
    point = obj({"text": STR, "sourceSegmentIds": IDS})
    return {
        "actionItems": arr(action),
        "decisions": arr(decision),
        "openQuestions": arr(obj({"text": STR, "raisedBy": NSTR, "directedTo": NSTR, "whyOpen": STR,
                                  "sourceSegmentIds": IDS})),
        "dates": arr(obj({"raw": STR, "date": NSTR, "time": NSTR, "what": STR, "sourceSegmentIds": IDS})),
        "numbers": arr(obj({"value": STR, "unit": NSTR, "what": STR, "sourceSegmentIds": IDS})),
        "nextMeeting": null(obj({"raw": NSTR, "date": NSTR, "time": NSTR, "agenda": arr(STR),
                                 "sourceSegmentIds": IDS})),
        "risks": arr(obj({"text": STR, "kind": STR, "raisedBy": NSTR, "severity": NSTR, "mitigation": NSTR,
                          "sourceSegmentIds": IDS})),
        "nextSteps": arr(point),
        "topics": arr(obj({"title": STR, "summary": STR, "outcome": STR, "startId": INT, "endId": INT,
                           "keyPoints": arr(point)})),
        "keyPoints": arr(point),
        "highlights": arr(obj({"quote": STR, "segmentId": INT, "why": STR})),
        "participants": arr(obj({"speaker": STR, "suggestedName": NSTR, "nameEvidence": IDS, "role": NSTR,
                                 "contribution": NSTR})),
        "templateSections": arr(obj({"key": STR, "items": arr(obj({"text": STR, "speaker": NSTR,
                                                                    "sourceSegmentIds": IDS}))})),
    }


_COVERAGE = obj({"firstId": INT, "lastId": INT})
_MEETING_TYPE = obj({"value": STR, "confidence": NUM})
_SENTIMENT = null(obj({"overall": STR, "note": NSTR, "sourceSegmentIds": IDS}))
_FOLLOW_UP = null(obj({"subject": NSTR, "body": STR}))


def extract(*, follow_up: bool = False) -> dict[str, Any]:
    props: dict[str, Any] = {"coverage": _COVERAGE, **_items(refs=False), "meetingType": _MEETING_TYPE,
                             "keywords": arr(STR), "sentiment": _SENTIMENT, "purpose": NSTR, "title": STR,
                             "overview": STR}
    if follow_up:
        props["followUpMessage"] = _FOLLOW_UP
    return obj(props)


def map_part() -> dict[str, Any]:
    return obj({"coverage": _COVERAGE, **_items(refs=True), "chunkSummary": STR})


def writer() -> dict[str, Any]:
    return obj({"duplicateGroups": arr(arr(STR)), "keyPoints": arr(obj({"text": STR, "sourceSegmentIds": IDS})),
                "topics": arr(obj({"ref": STR, "title": STR, "summary": STR})), "meetingType": _MEETING_TYPE,
                "keywords": arr(STR), "sentiment": _SENTIMENT, "purpose": NSTR, "title": STR, "overview": STR,
                "followUpMessage": _FOLLOW_UP})


def verify() -> dict[str, Any]:
    return obj({"results": arr(obj({"id": STR, "supported": BOOL, "ownerCorrect": BOOL, "acceptanceCorrect": BOOL,
                                    "dueCorrect": BOOL, "note": NSTR}))})


def classify() -> dict[str, Any]:
    return obj({"template": STR, "confidence": NUM})


def ask() -> dict[str, Any]:
    return obj({"answer": STR, "citations": IDS, "followUps": arr(STR)})


def minutes() -> dict[str, Any]:
    """Bayonnoma (rasmiy hujjat, `minutes/prompt.py` dagi shakl bilan BIR XIL): kun tartibi bandlari,
    har band bo'yicha bayon, qaror bo'limlari (band = tur, muddat, mas'ullar, matn, kichik bandlar,
    "Bunda" davomi, manba qatorlar), nazoratchi, izohlar, qamrov. Sarlavhalar, raqamlash va bo'sh
    joylar ("________") - KOD (`minutes/compose.py`), model emas."""
    item = obj({"kind": STR, "deadline": NSTR, "deadlineDate": NSTR, "responsible": arr(STR), "text": STR,
                "subpoints": arr(STR), "followUp": NSTR, "sourceSegmentIds": IDS, "confidence": NUM})
    agenda = obj({"title": STR, "speakers": arr(STR), "report": STR, "sourceSegmentIds": IDS})
    section = obj({"agendaIndex": INT, "items": arr(item)})
    return obj({"coverage": _COVERAGE, "title": STR, "agenda": arr(agenda), "preamble": NSTR,
                "sections": arr(section), "controller": NSTR, "notes": arr(STR)})


def for_op(op: str, system: str = "") -> dict[str, Any] | None:
    """Amal (`op`) -> sxema; noma'lum amal - `None` (oddiy JSON rejimi). Yig'ilish chati (`meeting_chat`) -
    savol-javob bilan bir xil shakl."""
    if op == "meeting_extract":
        return extract(follow_up='"followUpMessage"' in system)
    builders = {"meeting_map": map_part, "meeting_write": writer, "meeting_verify": verify,
                "meeting_classify": classify, "meeting_ask": ask, "meeting_chat": ask, "meeting_minutes": minutes}
    build = builders.get(op)
    return build() if build else None

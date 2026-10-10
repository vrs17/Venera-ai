"""Xulosa quvuri: JSON qutqarish, tekshiruv, muddatlar, birlashtirish, map-reduce (spetsifikatsiya 6)."""

from __future__ import annotations

import json

from datetime import date, datetime, timezone

import pytest

from app.services.meetings import dates, templates
from app.services.meetings.summarize import (LlmFailed, LlmRateLimited, LlmUnavailable, Merger, Pipeline,
                                             SummaryInput, Validator, parse_json, salvage)
from meetings_fakes import FakeLLM, auto_reply, parse_lines, rate_limited

#: 2026-10-09 (juma) 11:00 Toshkent.
RECORDED = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc).timestamp()
DAY = date(2026, 10, 9)

LINES = [
    ("S1", "Assalomu alaykum, bugun hisobot bo'yicha yig'ildik, boshlaymiz."),
    ("S2", "Men ertaga hisobotni tayyorlab yuboraman, Aziz aka."),
    ("S1", "Yaxshi, unda narxni 15 mln so'm qilib belgilashga kelishdik."),
    ("S2", "Mayli, juma kuni mijoz bilan gaplashaman va natijani aytaman."),
    ("S1", "Keyingi yig'ilish seshanba kuni soat 10:00 da bo'ladi, hammaga rahmat."),
    ("S3", "Men ham dizaynni chorshanbagacha tekshirib chiqaman, savol bo'lsa yozing."),
    ("S2", "Byudjet masalasi hali ochiq, buxgalteriya javob bermadi, kutamiz."),
]


def make_input(lines=LINES, *, template="general", duration=64.0, marks=None, repeat=1, language="uz",
               speakers_available=True) -> SummaryInput:
    segments, t = [], 0.0
    for r in range(repeat):
        for speaker, text in lines:
            segments.append({"id": len(segments) + 1, "start": t, "end": t + 8.0, "speaker": speaker,
                             "text": text if repeat == 1 else f"{text} ({r})"})
            t += 9.0
    talk: dict[str, float] = {}
    for s in segments:
        talk[s["speaker"]] = talk.get(s["speaker"], 0.0) + 8.0
    return SummaryInput(meeting_id="m1", rev=1, recorded_at=RECORDED, duration_sec=duration if repeat == 1 else t,
                        language=language, template=template, segments=segments,
                        speakers=[{"id": k, "name": "Aziz" if k == "S1" else None, "talk_sec": v}
                                  for k, v in sorted(talk.items())],
                        marks=marks or [], speakers_available=speakers_available)


def validator(**kw) -> Validator:
    inp = make_input()
    return Validator(segments=inp.segments, speakers={"S1", "S2", "S3"}, names=["Aziz"], meeting_day=DAY, **kw)


# --- JSON o'qish -------------------------------------------------------------------------


def test_parse_chegara_va_matn_ichida():
    assert parse_json('```json\n{"a": 1}\n```') == ({"a": 1}, False)
    assert parse_json('Mana javob: {"a": [1, 2]} tamom') == ({"a": [1, 2]}, False)
    assert parse_json("umuman json emas") == (None, False)


def test_kesilgan_json_qutqariladi():
    raw = '{"title": "T", "actionItems": [{"task": "a"}, {"task": "b"}, {"task": "c", "own'
    data, salvaged = parse_json(raw)
    assert salvaged and data["title"] == "T" and [x["task"] for x in data["actionItems"]] == ["a", "b"]
    assert salvage('{"x": 1, "y": {"z":') == {"x": 1}


# --- tekshiruv ------------------------------------------------------------------------------


def test_yaroqsiz_id_tashlanadi_iqtibos_bilan_tiklanadi():
    v = validator()
    good = v.action_item({"task": "Hisobotni yuborish", "quote": "ertaga hisobotni tayyorlab yuboraman",
                          "sourceSegmentIds": [999], "owner": {"speaker": "S2", "kind": "person",
                                                               "basis": "self_commitment"}}, "a")
    assert good["sourceSegmentIds"] == [2] and good["needsConfirmation"] is False
    dropped = v.action_item({"task": "To'qima", "quote": "bunday gap yo'q edi", "sourceSegmentIds": [500]}, "b")
    assert dropped is None and v.dropped == 1


def test_iqtibos_mos_kelmasa_tekshiring_belgisi():
    v = validator()
    item = v.decision({"text": "Narx", "quote": "narx 20 mln bo'ladi deb aytildi", "sourceSegmentIds": [3]}, "d")
    assert item["needsConfirmation"] is True
    assert item["quote"] == "Yaxshi, unda narxni 15 mln so'm qilib belgilashga kelishdik."
    fuzzy = v.decision({"text": "Narx", "quote": "unda narxni 15 mln som qilib belgilashga kelishdik",
                        "sourceSegmentIds": [3]}, "d")
    assert fuzzy["needsConfirmation"] is False                       # tinish/apostrof farqi - o'tadi


def test_egasi_transkriptda_bolmasa_olib_tashlanadi():
    v = validator()
    item = v.action_item({"task": "Shartnoma", "quote": "juma kuni mijoz bilan gaplashaman",
                          "sourceSegmentIds": [4], "owner": {"speaker": "S9", "name": "Bobur", "kind": "person",
                                                             "basis": "assigned_and_accepted"}}, "a")
    assert item["owner"]["speaker"] is None and item["owner"]["name"] is None
    assert item["owner"]["kind"] == "unknown" and item["needsConfirmation"] is True
    named = v.action_item({"task": "Hisobot", "quote": "ertaga hisobotni", "sourceSegmentIds": [2],
                           "owner": {"name": "Aziz aka", "kind": "person", "basis": "assigned_no_reply"}}, "a")
    assert named["owner"]["name"] == "Aziz aka" and named["needsConfirmation"] is True


def test_muddat_kod_jadvali_golib():
    v = validator()
    item = v.action_item({"task": "Hisobot", "quote": "ertaga hisobotni tayyorlab", "sourceSegmentIds": [2],
                          "owner": {"speaker": "S2", "kind": "person", "basis": "self_commitment"},
                          "due": {"raw": "ertaga", "date": "2026-10-12", "time": "15:00"}}, "a")
    assert item["due"]["date"] == "2026-10-10" and item["due"]["basis"] == "relative_resolved"
    assert item["due"]["time"] is None                                # soat aytilmagan
    assert item["needsConfirmation"] is True
    same = v.action_item({"task": "Mijoz", "quote": "juma kuni mijoz bilan", "sourceSegmentIds": [4],
                          "owner": {"speaker": "S2", "kind": "person", "basis": "self_commitment"},
                          "due": {"raw": "juma kuni", "date": "2026-10-16"}}, "a")
    assert same["due"]["date"] == "2026-10-16" and same["needsConfirmation"] is False
    timed = v.date_item({"raw": "seshanba", "date": "2026-10-13", "time": "10:00", "what": "yig'ilish",
                         "sourceSegmentIds": [5]}, "e")
    assert timed["time"] == "10:00" and timed["date"] == "2026-10-13"
    # Qatorda yo'q ibora - sana bo'limiga kirmaydi.
    assert v.date_item({"raw": "o'tgan oy", "date": "2026-09-01", "sourceSegmentIds": [5]}, "e") is None


@pytest.mark.parametrize("raw,expected,basis", [
    ("bugun", "2026-10-09", "relative_resolved"), ("ertaga", "2026-10-10", "relative_resolved"),
    ("zavtra", "2026-10-10", "relative_resolved"), ("завтра", "2026-10-10", "relative_resolved"),
    ("indinga", "2026-10-11", "relative_resolved"), ("poslezavtra", "2026-10-11", "relative_resolved"),
    ("tomorrow", "2026-10-10", "relative_resolved"), ("dushanbagacha", "2026-10-12", "relative_resolved"),
    ("do pyatnitsy", "2026-10-16", "relative_resolved"), ("до пятницы", "2026-10-16", "relative_resolved"),
    ("by Friday", "2026-10-16", "relative_resolved"), ("hafta oxirigacha", "2026-10-09", "relative_resolved"),
    ("do kontsa nedeli", "2026-10-09", "relative_resolved"), ("oy oxirigacha", "2026-10-31", "relative_resolved"),
    ("end of month", "2026-10-31", "relative_resolved"), ("25-oktyabrgacha", "2026-10-25", "explicit"),
    ("5 января", "2027-01-05", "explicit"), ("2026-11-02", "2026-11-02", "explicit"),
    ("tez orada", None, "vague"), ("keyingi hafta", None, "vague"), ("skoro", None, "vague"),
    ("ASAP", None, "vague"), ("qachondir", None, "none"),
])
def test_sana_jadvali(raw, expected, basis):
    day, got_basis = dates.resolve(raw, DAY)
    assert (day.isoformat() if day else None) == expected and got_basis == basis


def test_hafta_oxiri_shanbada_keyingi_juma():
    assert dates.resolve("hafta oxirigacha", date(2026, 10, 10))[0] == date(2026, 10, 16)


def test_noma_lum_spiker_tokeni_oddiy_matn():
    v = validator()
    assert v.text("[S1] va [S7] gaplashdi <b>x</b> [havola](http://a.b)", 200) == "[S1] va S7 gaplashdi x havola"


def test_taklif_qilingan_ism_dalil_bilan():
    v = validator()
    assert v.participant({"speaker": "S1", "suggestedName": "Aziz", "nameEvidence": [2]}, "p")["suggestedName"] \
        == "Aziz"
    assert v.participant({"speaker": "S2", "suggestedName": "Laylo", "nameEvidence": [2]}, "p")["suggestedName"] \
        is None


# --- quvur ----------------------------------------------------------------------------------


def test_bir_otish_chegarali_json(monkeypatch):
    llm = FakeLLM()
    reply = auto_reply("meeting_extract", "", "\n".join(
        f"#{i} [00:00] {s}: {t}" for i, (s, t) in enumerate(LINES, start=1)))
    llm.script["meeting_extract"] = ["```json\n" + reply + "\n```"]
    result = Pipeline(llm, verify=False).run(make_input())
    assert result.status == "ready" and llm.ops() == ["meeting_extract"]
    content = result.content
    assert content["schemaVersion"] == "meeting-summary/1" and content["title"] == "Hisobot yig'ilishi"
    assert content["actionItems"][0]["id"] == "A1" and content["actionItems"][0]["start"] == 0.0
    assert content["decisions"][0]["id"] == "D1" and content["topics"][0]["id"] == "T1"
    assert content["meeting"] == {"date": "2026-10-09", "weekday": "juma", "timezone": "Asia/Tashkent",
                                  "durationSec": 64.0, "speakerCount": 3}
    shares = {p["speaker"]: p["talkShare"] for p in content["participants"]}
    assert abs(sum(shares.values()) - 1.0) < 0.01 and shares["S1"] > shares["S3"]
    assert content["quality"]["chunks"] == 1 and content["quality"]["speakersAvailable"] is True


def test_buzuq_json_bir_marta_tuzatiladi():
    llm = FakeLLM()
    llm.script["meeting_extract"] = ["Kechirasiz, men buni qila olmayman"]
    result = Pipeline(llm, verify=False).run(make_input())
    assert llm.ops() == ["meeting_extract", "meeting_extract"]
    assert "Your previous reply was invalid" in llm.calls[1]["user"] and llm.calls[1]["temperature"] == 0.0
    assert result.status == "ready" and result.content["actionItems"]


def test_ikki_marta_buzuq_bolsa_map_yoliga_otadi():
    llm = FakeLLM()
    llm.script["meeting_extract"] = ["yo'q", "yana yo'q"]
    result = Pipeline(llm, verify=False).run(make_input())
    assert llm.ops()[:2] == ["meeting_extract", "meeting_extract"] and "meeting_map" in llm.ops()
    assert "single_pass_fallback" in result.content["quality"]["warnings"]


def test_kesilgan_javob_map_yoliga():
    llm = FakeLLM()
    llm.script["meeting_extract"] = [('{"title": "x"}', {"doneReason": "length", "tokensIn": None})]
    result = Pipeline(llm, verify=False).run(make_input())
    assert "meeting_map" in llm.ops() and result.status == "ready"


def test_juda_qisqa_xulosa_yoq():
    llm = FakeLLM()
    result = Pipeline(llm).run(make_input(lines=[("S1", "Salom")], duration=5.0))
    assert result.status == "skipped" and result.error_code == "too_short" and llm.calls == []


def test_qisqa_qongiroq_qoidasi_klassifikatorsiz():
    llm = FakeLLM()
    result = Pipeline(llm, verify=False).run(make_input(template="auto", duration=120.0))
    assert result.template == "short_call" and "meeting_classify" not in llm.ops()
    content = result.content
    assert content["topics"] == [] and content["keyPoints"] == [] and content["actionItems"]
    assert content["meetingType"] == {"value": "short_call", "confidence": 1.0}


def test_klassifikator_ishonchsiz_bolsa_general():
    llm = FakeLLM()
    llm.script["meeting_classify"] = [json.dumps({"template": "sales_call", "confidence": 0.4})]
    result = Pipeline(llm, verify=False).run(make_input(template="auto", duration=900.0, repeat=6))
    assert result.template == "general"
    llm2 = FakeLLM()
    llm2.script["meeting_classify"] = [json.dumps({"template": "sales_call", "confidence": 0.8})]
    assert Pipeline(llm2, verify=False).run(make_input(template="auto", duration=900.0, repeat=6)).template \
        == "sales_call"


def test_uzun_matn_map_reduce_va_toliqlik_kafolati():
    llm = FakeLLM()
    inp = make_input(repeat=30)                                  # ~210 qator
    pipeline = Pipeline(llm, single_pass_chars=3000, map_chars=2500, verify=False)
    result = pipeline.run(inp)
    maps = llm.ops().count("meeting_map")
    assert maps >= 4 and llm.ops()[-1] == "meeting_write" and "meeting_extract" not in llm.ops()
    content = result.content
    # Har bo'lakning vazifasi va qarori yakuniy xulosada (yozuvchi o'chira olmaydi).
    assert len(content["actionItems"]) == maps and len(content["decisions"]) == maps
    assert content["title"] == "Uzun yig'ilish" and content["quality"]["chunks"] == maps
    # Keyingi bo'laklar CONTEXT ONLY qatorlari va ochiq vazifalar ro'yxatini oladi.
    second = [c for c in llm.calls if c["op"] == "meeting_map"][1]["user"]
    assert "(CONTEXT ONLY)" in second and "Open action items so far" in second and "A1:" in second
    for call in llm.calls:
        assert len(call["user"]) < 30000


def test_map_kesh_takror_chaqirmaydi():
    cache: dict = {}
    llm = FakeLLM()
    inp = make_input(repeat=20)
    kwargs = dict(single_pass_chars=3000, map_chars=2500, verify=False,
                  cache_get=lambda t, a, b: cache.get((t, a, b)),
                  cache_put=lambda t, a, b, part: cache.__setitem__((t, a, b), part))
    Pipeline(llm, **kwargs).run(inp)
    first_maps = llm.ops().count("meeting_map")
    llm2 = FakeLLM()
    Pipeline(llm2, **kwargs).run(inp)
    assert first_maps > 0 and llm2.ops().count("meeting_map") == 0 and llm2.ops() == ["meeting_write"]


def test_kesilgan_bolak_ikkiga_bolinadi():
    llm = FakeLLM()
    llm.script["meeting_map"] = [('{"chunkSummary": "x", "actionItems": [', {"doneReason": "length"})]
    inp = make_input(repeat=4)
    Pipeline(llm, single_pass_chars=100, map_chars=100000, verify=False).run(inp)
    maps = [c for c in llm.calls if c["op"] == "meeting_map"]
    assert len(maps) == 3                                         # butun -> ikki yarim
    halves = [parse_lines(c["user"]) for c in maps[1:]]
    own = [[x["id"] for x in h if not x["context"]] for h in halves]
    assert own[0][0] == 1 and own[1][-1] == len(inp.segments) and own[0][-1] + 1 == own[1][0]


def test_birlashtirish_ref_va_jaccard():
    merger = Merger()
    base = {"owner": {"speaker": "S2", "name": None, "kind": "person", "basis": "self_commitment"},
            "due": {"raw": None, "date": None, "time": None, "basis": "none"}, "status": "open",
            "needsConfirmation": False, "confidence": 0.9, "quote": "q", "ref": None}
    merger.add({"actionItems": [dict(base, task="Hisobotni tayyorlab yuborish", sourceSegmentIds=[2])],
                "decisions": [{"text": "Narx 15 mln", "status": "final", "needsConfirmation": False,
                               "sourceSegmentIds": [3]}]})
    merger.add({"actionItems": [
        dict(base, task="hisobotni tayyorlab yuborish kerak", sourceSegmentIds=[9],
             due={"raw": "juma", "date": "2026-10-16", "time": None, "basis": "relative_resolved"}),
        dict(base, task="Taqdimotni yangilash", ref="A1", sourceSegmentIds=[12], status="done_in_meeting"),
        dict(base, task="Boshqa ish", owner={"speaker": "S1", "name": None, "kind": "person",
                                              "basis": "self_commitment"}, sourceSegmentIds=[4])],
        "decisions": [{"text": "Narx 15 mln.", "status": "reversed", "needsConfirmation": False,
                       "sourceSegmentIds": [8]}]})
    out = merger.result()
    assert len(out["actionItems"]) == 2
    first = out["actionItems"][0]
    assert first["task"] == "Taqdimotni yangilash" and first["status"] == "done_in_meeting"
    assert first["due"]["date"] == "2026-10-16" and first["sourceSegmentIds"] == [2, 9, 12]
    assert len(out["decisions"]) == 1 and out["decisions"][0]["status"] == "reversed"


def test_belgi_qoplanmasa_highlight_qoshiladi():
    llm = FakeLLM()
    inp = make_input(marks=[{"t": 40.0, "note": "narx"}, {"t": 1.0, "note": None}])
    content = Pipeline(llm, verify=False).run(inp).content
    marks = {m["id"]: m for m in content["userMarks"]}
    assert marks["m1"]["coveredBy"] and marks["m2"]["coveredBy"]
    added = [h for h in content["highlights"] if h["fromMark"] == "m1"]
    assert added and added[0]["why"] == "narx" and added[0]["segmentId"] in marks["m1"]["segmentIds"]
    assert "m1 at 00:40" in llm.calls[0]["user"]                  # belgi promptda


def test_tekshiruvchi_rad_etsa_tasdiqlanmagan():
    llm = FakeLLM()
    llm.script["meeting_verify"] = [json.dumps({"results": [
        {"id": "A1", "supported": False, "ownerCorrect": True, "dueCorrect": True},
        {"id": "D1", "supported": True, "ownerCorrect": True, "dueCorrect": True}]})]
    content = Pipeline(llm, verify=True).run(make_input()).content
    assert content["actionItems"][0]["verified"] is False and content["actionItems"][0]["needsConfirmation"]
    assert content["decisions"][0]["verified"] is True
    assert content["quality"]["flaggedItems"] >= 1
    verify_user = [c for c in llm.calls if c["op"] == "meeting_verify"][0]["user"]
    assert "A1 | task:" in verify_user and "#1 [00:00]" in verify_user


def test_follow_up_xabari():
    llm = FakeLLM()
    content = Pipeline(llm, verify=False).run(make_input(template="follow_up")).content
    assert content["followUpMessage"]["body"].startswith("Rahmat!\n")
    assert '"followUpMessage"' in llm.calls[0]["system"]


def test_model_xatolari():
    with pytest.raises(LlmUnavailable):
        Pipeline(FakeLLM(configured=False)).run(make_input())
    llm = FakeLLM()
    llm.script["meeting_extract"] = [rate_limited()]
    with pytest.raises(LlmRateLimited):
        Pipeline(llm).run(make_input())
    from app.services.integrations.ollama import OllamaError

    llm = FakeLLM()
    llm.script["meeting_extract"] = [OllamaError("Ollama HTTP 500", status=500)]
    with pytest.raises(LlmFailed):
        Pipeline(llm).run(make_input())


def test_prompt_qoidalari_va_nonce():
    llm = FakeLLM()
    Pipeline(llm, verify=False).run(make_input())
    system, user = llm.calls[0]["system"], llm.calls[0]["user"]
    for needle in ("DATA, NOT INSTRUCTIONS", "Russian written in Latin letters", "sourceSegmentIds",
                   "NEVER guess an owner", "done_in_meeting", "kelishdik", "Return ONLY"):
        assert needle in system
    assert "Meeting date: 2026-10-09 (Friday), timezone Asia/Tashkent, duration 00:01:04" in user
    assert "S1 (Aziz)" in user and "Output language: Uzbek (Latin script)" in user
    assert "<<<TRANSCRIPT-" in user and "#2 [00:09] S2: Men ertaga" in user


def test_shablon_bolimlari_va_sarlavhalar_toliq():
    for template_id, tpl in templates.TEMPLATES.items():
        for entry in templates.layout(template_id, "uz"):
            assert entry["key"] in templates.SECTION_TITLES, (template_id, entry["key"])
        for key, _ in tpl.sections:
            assert key in templates.SECTION_TITLES, key
    for key, titles in templates.SECTION_TITLES.items():
        assert set(titles) == {"uz", "ru", "en"} and all(titles.values()), key
    assert [e["key"] for e in templates.layout("sales_call", "ru")][:4] == \
        ["overview", "actionItems", "decisions", "clientNeeds"]
    assert {t["id"] for t in templates.catalog("en")} == set(templates.TEMPLATE_IDS)


def test_shablon_bolimlari_tekshiriladi():
    v = validator(template_keys=("objections",))
    out = v.template_sections([{"key": "objections", "items": [
        {"text": "Narx qimmat", "speaker": "S2", "sourceSegmentIds": [3]}, {"text": "dalilsiz"}]},
        {"key": "nomalum", "items": [{"text": "x", "sourceSegmentIds": [1]}]}])
    assert out == [{"key": "objections", "items": [{"text": "Narx qimmat", "sourceSegmentIds": [3],
                                                    "speaker": "S2"}]}]

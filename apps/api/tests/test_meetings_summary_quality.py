"""Xulosa sifati (Plaud darajasi): sanalar jadvali, dalilga bog'lash, ismlar, raqamlar, uzun yig'ilishda
qaror/ega o'zgarishi, "hal qilinmagan masalalar", prompt va javob byudjeti - soxta model bilan."""

from __future__ import annotations

import json

from datetime import date

import pytest

from app.services.meetings import dates, export, prompts, templates
from app.services.meetings.summarize import (KEY_POINTS_MISSING, REAL_CONTENT_WORDS, Merger, Pipeline, Validator,
                                             jaccard, similar)
from meetings_fakes import FakeLLM, auto_reply
from test_meetings_summary import DAY, LINES, make_input

MONDAY = date(2026, 10, 12)


def v_for(lines, **kw) -> Validator:
    inp = make_input(lines=lines)
    return Validator(segments=inp.segments, speakers={"S1", "S2", "S3"}, names=[], meeting_day=DAY, **kw)


# --- sana jadvali (ikkala ko'rib chiqish misollari) -----------------------------------------


@pytest.mark.parametrize("raw,base,expected,basis", [
    ("keyingi hafta oxirigacha", DAY, "2026-10-16", "relative_resolved"),
    ("kelasi oy oxirigacha", DAY, "2026-11-30", "relative_resolved"),
    ("до конца следующей недели", DAY, "2026-10-16", "relative_resolved"),
    ("soat 10.05 gacha", DAY, None, "none"),
    ("mayli, 2 kunda", DAY, "2026-10-11", "relative_resolved"),
    ("by 5 pm, may be later", DAY, None, "vague"),
    ("mayli ertagacha 10 gacha", DAY, "2026-10-10", "relative_resolved"),
    ("2 marta tekshirib", DAY, None, "none"),
    ("soat 3 da, 10-noyabr", DAY, "2026-11-10", "explicit"),
    ("o'tgan juma", DAY, None, "past"),
    ("kecha", DAY, None, "past"),
    ("2 kun oldin", DAY, None, "past"),
    ("jumadan oldin", DAY, "2026-10-16", "relative_resolved"),
    ("keyingi hafta seshanba", MONDAY, "2026-10-20", "relative_resolved"),
    ("next week Tuesday", MONDAY, "2026-10-20", "relative_resolved"),
    ("keyingi seshanba", MONDAY, "2026-10-13", "relative_resolved"),
    ("среди недели", DAY, None, "none"),
    ("Jumanazarov aytdi", DAY, None, "none"),
    ("bir haftadan keyin", DAY, "2026-10-16", "relative_resolved"),
    ("2 kundan keyin", DAY, "2026-10-11", "relative_resolved"),
    ("hafta ichida", DAY, "2026-10-16", "relative_resolved"),
    ("через неделю", DAY, "2026-10-16", "relative_resolved"),
    ("cherez 3 dnya", DAY, "2026-10-12", "relative_resolved"),
    ("in 2 days", DAY, "2026-10-11", "relative_resolved"),
    ("bir oyda", DAY, "2026-11-09", "relative_resolved"),
    ("shu oyda", DAY, None, "none"),
    ("Oct 25", DAY, "2026-10-25", "explicit"),
    ("25th of October", DAY, "2026-10-25", "explicit"),
    ("15-sentabrgacha", DAY, "2027-09-15", "explicit"),
    ("dushanbadan jumagacha", DAY, "2026-10-16", "relative_resolved"),
])
def test_sana_jadvali_kengaytirilgan(raw, base, expected, basis):
    day, got = dates.resolve(raw, base)
    assert (day.isoformat() if day else None, got) == (expected, basis)


def test_voqea_sanasi_otmishda_ham():
    assert dates.resolve("5-oktyabrda", DAY, event=True)[0] == date(2026, 10, 5)
    assert dates.resolve("5-oktyabrda", DAY)[0] == date(2027, 10, 5)              # muddat - kelajak
    assert dates.resolve("o'tgan juma", DAY, event=True)[0] == date(2026, 10, 2)
    assert dates.resolve("kecha", DAY, event=True)[0] == date(2026, 10, 8)


def test_taqvim_qatori_promptda():
    line = dates.calendar_line(MONDAY)
    assert "today = Mon 2026-10-12" in line and "next week (keyingi hafta) = Mon 2026-10-19" in line
    assert "end of this week = Fri 2026-10-16" in line and "end of this month = 2026-10-31" in line


# --- muddat dalilga bog'langan --------------------------------------------------------------

DUE_LINES = [
    ("S1", "Aziz aka, hisobotni qachon yuborasiz?"),
    ("S2", "Chorshanbagacha yuboraman."),
    ("S1", "Yaxshi, kelishdik."),
    ("S3", "Men ham bir haftadan keyin smetani tekshiraman."),
    ("S1", "Narx 15 mln so'm bo'ladi, shoshilinch emas."),
    ("S2", "Men Azizman, savol bo'lsa yozing."),
]


def _item(**kw) -> dict:
    base = {"task": "Hisobotni yuborish", "quote": "Chorshanbagacha yuboraman", "sourceSegmentIds": [2, 1],
            "owner": {"speaker": "S2", "kind": "person", "basis": "self_commitment"}, "confidence": 0.9}
    base.update(kw)
    return base


def test_toqilgan_muddat_iborasi_qabul_qilinmaydi():
    v = v_for(DUE_LINES)
    fake = v.action_item(_item(due={"raw": "ertaga", "date": "2026-10-10"}), "a")
    assert fake["due"]["date"] is None and fake["due"]["raw"] is None and fake["needsConfirmation"] is True
    real = v.action_item(_item(due={"raw": "Chorshanbagacha", "date": "2026-10-14"}), "a")
    assert real["due"]["date"] == "2026-10-14" and real["needsConfirmation"] is False


def test_noma_lum_ibora_model_sanasi_tekshiring_bilan():
    v = v_for(DUE_LINES + [("S3", "Buni o'n ikkinchi sanagacha qilaman.")])
    item = v.action_item(_item(quote="o'n ikkinchi sanagacha qilaman", sourceSegmentIds=[7],
                               owner={"speaker": "S3", "kind": "person", "basis": "self_commitment"},
                               due={"raw": "o'n ikkinchi sanagacha", "date": "2026-10-12"}), "a")
    assert item["due"]["date"] == "2026-10-12" and item["due"]["basis"] == "relative_resolved"
    assert item["needsConfirmation"] is True


def test_iborasiz_sana_qoyilmaydi():
    v = v_for(DUE_LINES)
    item = v.action_item(_item(due={"raw": None, "date": "2026-10-20"}), "a")
    assert item["due"]["date"] is None and item["needsConfirmation"] is True


def test_nisbiy_ibora_jadval_bilan():
    v = v_for(DUE_LINES)
    item = v.action_item(_item(task="Smetani tekshirish", quote="bir haftadan keyin smetani tekshiraman",
                               sourceSegmentIds=[4], owner={"speaker": "S3", "kind": "person",
                                                            "basis": "self_commitment"},
                               due={"raw": "bir haftadan keyin", "date": "2026-10-20"}), "a")
    assert item["due"]["date"] == "2026-10-16" and item["needsConfirmation"] is True     # model adashdi


def test_next_meeting_toqilgan_ibora_sanasiz():
    v = v_for(DUE_LINES)
    nm = v.next_meeting({"raw": "keyingi seshanba", "date": "2026-10-13", "agenda": ["Narx"],
                         "sourceSegmentIds": [3]})
    assert nm["date"] is None and nm["raw"] is None and nm["agenda"] == ["Narx"]


# --- ism, ustuvorlik, raqam --------------------------------------------------------------------


def test_murojaat_qilgan_odam_ism_egasi_emas():
    v = v_for(LINES)
    # 2-qator: S2 "... Aziz aka" deydi - Azizga MUROJAAT; javob beradigan S1 - Aziz.
    assert v.participant({"speaker": "S2", "suggestedName": "Aziz", "nameEvidence": [2]}, "p")["suggestedName"] \
        is None
    assert v.participant({"speaker": "S1", "suggestedName": "Aziz aka", "nameEvidence": [2]}, "p")["suggestedName"] \
        == "Aziz"
    own = v_for(DUE_LINES)
    intro = own.participant({"speaker": "S2", "suggestedName": "Azizjon", "nameEvidence": [6],
                             "contribution": "[S2] hisobotni yuboradi."}, "p")
    assert intro["suggestedName"] == "Aziz" and intro["contribution"] == "[S2] hisobotni yuboradi."


def test_ustuvorlik_faqat_aytilgan_bolsa():
    v = v_for(DUE_LINES)
    assert v.action_item(_item(priority="high"), "a")["priority"] is None
    urgent = v_for([("S1", "Bu shoshilinch, ertaga hisobotni yuboring."), ("S2", "Xo'p, yuboraman.")])
    item = urgent.action_item(_item(quote="Xo'p, yuboraman", sourceSegmentIds=[2, 1], priority="high"), "a")
    assert item["priority"] == "high"


def test_raqam_qatorda_bolmasa_tashlanadi():
    v = v_for(DUE_LINES)
    assert v.number_item({"value": "99 mln so'm", "what": "narx", "sourceSegmentIds": [5]}, "n") is None
    assert v.number_item({"value": "15 mln so'm", "what": "narx", "sourceSegmentIds": [5]}, "n")["value"] \
        == "15 mln so'm"


def test_ozbekcha_chiqishda_kirill_tuzatishga_yuboriladi():
    llm = FakeLLM()
    reply = json.loads(auto_reply("meeting_extract", "", "\n".join(
        f"#{i} [00:00] {s}: {t}" for i, (s, t) in enumerate(LINES, start=1))))
    reply["overview"] = "Совещание по отчёту прошло хорошо, решили цену и сроки отправки отчёта клиенту."
    reply["topics"][0]["summary"] = "Обсуждение отчёта, цены, бюджета и встреч с клиентом на этой неделе."
    llm.script["meeting_extract"] = [json.dumps(reply, ensure_ascii=False)]
    Pipeline(llm, verify=False).run(make_input())
    assert llm.ops()[:2] == ["meeting_extract", "meeting_extract"]
    assert "Latin script" in llm.calls[1]["user"]


# --- uzun yig'ilish: o'zgargan qaror va ega -------------------------------------------------


def _decision(text, status="final", ref=None, ids=(3,)):
    return {"text": text, "status": status, "condition": None, "rationale": None, "proposedBy": [], "agreedBy": [],
            "quote": "q", "needsConfirmation": False, "verified": None, "sourceSegmentIds": list(ids), "ref": ref}


def _action(task, speaker="S2", name=None, ref=None, ids=(2,)):
    return {"task": task, "owner": {"speaker": speaker, "name": name, "kind": "person", "basis": "self_commitment"},
            "due": {"raw": None, "date": None, "time": None, "basis": "none"}, "status": "open",
            "needsConfirmation": False, "confidence": 0.9, "quote": "q", "sourceSegmentIds": list(ids), "ref": ref}


def test_qaror_bekor_qilinishi_va_ega_almashishi():
    merger = Merger()
    merger.add({"decisions": [_decision("Narxni 15 mln qilamiz")], "actionItems": [_action("Shartnomani tayyorlash")]})
    assert [d["ref"] for d in merger.running_decisions()] == ["D1"]
    merger.add({"decisions": [_decision("Narxni 18 mln qilamiz", ref="D1", ids=(40,))],
                "actionItems": [_action("Shartnomani tayyorlash", speaker=None, name="Bobur", ref="A1", ids=(41,))]})
    out = merger.result()
    assert [(d["text"], d["status"]) for d in out["decisions"]] == [("Narxni 15 mln qilamiz", "reversed"),
                                                                    ("Narxni 18 mln qilamiz", "final")]
    assert out["decisions"][0]["rationale"] == "→ Narxni 18 mln qilamiz"
    assert out["actionItems"][0]["owner"]["name"] == "Bobur"                      # qayta tayinlandi


def test_oxshashlik_raqamni_va_ozakni_hisobga_oladi():
    assert jaccard("hisobotni tayyorlab yuborish", "hisobot tayyorlash yuboraman") >= 0.6
    assert not similar("Narxni 15 mln qilamiz", "Narxni 18 mln qilamiz")
    merger = Merger()
    q = {"text": "Byudjetni kim tasdiqlaydi", "sourceSegmentIds": [6]}
    merger.add({"openQuestions": [dict(q)], "decisions": [_decision("Narx o'zgarmaydi", "tentative")]})
    merger.add({"openQuestions": [dict(q, text="Byudjetni kim tasdiqlashi", sourceSegmentIds=[60])],
                "decisions": [_decision("Narx o'zgarmaydi.", "final", ids=(50,))]})
    out = merger.result()
    assert len(out["openQuestions"]) == 1 and out["openQuestions"][0]["sourceSegmentIds"] == [6, 60]
    assert len(out["decisions"]) == 1 and out["decisions"][0]["status"] == "final"


def test_map_bolagi_tashlansa_toliq_deyilmaydi():
    llm = FakeLLM()
    llm.script["meeting_map"] = ["yo'q"] * 2
    content = Pipeline(llm, single_pass_chars=100, map_chars=100000, verify=False).run(make_input()).content
    # Butun bo'lak ikki marta yaroqsiz -> bir marta ikkiga bo'linib qayta uriniladi.
    assert llm.ops().count("meeting_map") == 4 and content["quality"]["coverageOk"] is True

    llm = FakeLLM()
    llm.script["meeting_map"] = ["yo'q"] * 4                      # bo'lak VA birinchi yarmi yaroqsiz
    content = Pipeline(llm, single_pass_chars=100, map_chars=100000, verify=False).run(make_input()).content
    assert llm.ops().count("meeting_map") == 5
    assert content["quality"]["coverageOk"] is False
    assert any(w.startswith("part_dropped") for w in content["quality"]["warnings"])


# --- yakuniy bo'limlar ------------------------------------------------------------------------


def test_hal_qilinmagan_masalalar_va_qisqa_qongiroq():
    llm = FakeLLM()
    data = json.loads(auto_reply("meeting_extract", "", "\n".join(
        f"#{i} [00:00] {s}: {t}" for i, (s, t) in enumerate(LINES, start=1))))
    data["actionItems"][0]["owner"] = {"speaker": None, "name": None, "kind": "unknown", "basis": "unclear"}
    data["decisions"][0]["status"] = "tentative"
    data["openQuestions"] = [{"text": "Byudjet ochiq", "whyOpen": "no_owner", "sourceSegmentIds": [7]}]
    data["numbers"] = [{"value": "15 mln so'm", "what": "narx", "sourceSegmentIds": [3]}]
    data["nextMeeting"] = {"raw": "seshanba kuni", "date": "2026-10-13", "time": "10:00", "agenda": [],
                           "sourceSegmentIds": [5]}
    llm.script["meeting_extract"] = [json.dumps(data, ensure_ascii=False)]
    content = Pipeline(llm, verify=False).run(make_input(template="short_call")).content
    kinds = {(f["kind"], tuple(f["reasons"])) for f in content["followUps"]}
    assert ("openQuestion", ("no_owner",)) in kinds and ("decision", ("tentative",)) in kinds
    assert ("actionItem", ("no_owner", "no_due")) in kinds
    # Qisqa qo'ng'iroqda raqam, ochiq savol va keyingi uchrashuv QOLADI.
    assert content["numbers"] and content["openQuestions"] and content["nextMeeting"]["date"] == "2026-10-13"
    keys = [e["key"] for e in templates.layout("short_call", "uz")]
    assert {"followUps", "numbers", "openQuestions", "nextMeeting"} <= set(keys)
    assert [e["key"] for e in templates.layout("general", "uz")][:4] == ["overview", "actionItems", "decisions",
                                                                         "followUps"]
    text = export.summary_document(content, templates.layout("short_call", "uz"), {}, "uz", 0, markdown=True)
    assert "## Hal qilinmagan masalalar" in text and "mas'ul belgilanmagan" in text


def test_mavzular_boshligi_ogohlantirish():
    llm = FakeLLM()

    def narrow(op, system, user):
        reply = json.loads(auto_reply(op, system, user))
        if op == "meeting_extract":
            reply["topics"][0]["endId"] = reply["topics"][0]["startId"] + 2
        return json.dumps(reply, ensure_ascii=False)

    llm.reply = narrow
    content = Pipeline(llm, verify=False).run(make_input(repeat=4, duration=900.0)).content
    assert "topics_gap" in content["quality"]["warnings"]


def test_tekshiruvchi_toqilgan_savol_va_xavfni_tashlaydi():
    llm = FakeLLM()
    data = json.loads(auto_reply("meeting_extract", "", "\n".join(
        f"#{i} [00:00] {s}: {t}" for i, (s, t) in enumerate(LINES, start=1))))
    data["openQuestions"] = [{"text": "Hech kim so'ramagan savol", "sourceSegmentIds": [1]}]
    data["risks"] = [{"text": "Byudjet kechikishi", "sourceSegmentIds": [7]}]
    llm.script["meeting_extract"] = [json.dumps(data, ensure_ascii=False)]
    llm.script["meeting_verify"] = [json.dumps({"results": [
        {"id": "Q1", "supported": False}, {"id": "R1", "supported": True},
        {"id": "A1", "supported": True, "ownerCorrect": True, "acceptanceCorrect": False, "dueCorrect": True}]})]
    content = Pipeline(llm, verify=True).run(make_input()).content
    assert content["openQuestions"] == [] and len(content["risks"]) == 1
    assert content["actionItems"][0]["verified"] is False and content["quality"]["droppedItems"] >= 1
    verify = [c for c in llm.calls if c["op"] == "meeting_verify"][0]
    assert "Q1 | open question:" in verify["user"] and "(basis: self_commitment)" in verify["user"]
    assert "acceptanceCorrect" in verify["system"]


def test_yozuvchi_takror_qarorlarni_birlashtiradi():
    merged = {"actionItems": [], "decisions": [
        {"_ref": "D1", "text": "Narx 15 mln", "sourceSegmentIds": [1], "needsConfirmation": False},
        {"_ref": "D2", "text": "Narx 15 mln bo'ladi", "sourceSegmentIds": [9], "needsConfirmation": False},
        {"_ref": "D3", "text": "Narx 18 mln", "sourceSegmentIds": [20], "needsConfirmation": False}]}
    Pipeline._apply_duplicates(merged, [["D1", "D2", "D3"]])
    assert [d["_ref"] for d in merged["decisions"]] == ["D1", "D3"] and merged["decisions"][0]["sourceSegmentIds"] \
        == [1, 9]


# --- prompt va byudjet ------------------------------------------------------------------------


def test_prompt_meeting_2_qoidalari():
    assert prompts.PROMPT_VERSION == "meeting-3"
    system = prompts.extract_system("general")
    for needle in ("6b. COMMITMENT FORMS", "-sin", "-aylik", "6c. NOT ACTION ITEMS", "volunteered", "assignedBy",
                   "PARTICIPANT NAMES", "ANSWERS in the next 1-2 lines", "concluding statement",
                   "Never infer authority", "EXAMPLE (illustration only", "never 'buni'".replace("'", "\""),
                   "Turkish letters", "title\" and \"overview\" LAST"):
        assert needle in system, needle
    # Shakl: vazifalar birinchi, umumiy xulosa oxirida; misol qiymatlar yo'q.
    shape = system.split("Return ONLY this JSON object")[1]
    assert shape.index('"actionItems"') < shape.index('"topics"') < shape.index('"overview": "<written last')
    assert "15 mln" not in system.split("Return ONLY this JSON object")[1]
    assert '"ref"' not in system.split("Return ONLY this JSON object")[1]
    assert '"condition": null, "owner"' in system and '"contribution"' in system


def test_promptda_taqvim_eslatma_va_kutilgan_ishtirokchilar():
    llm = FakeLLM()
    inp = make_input()
    inp.expected_speakers = 6
    Pipeline(llm, verify=False).run(inp)
    user = llm.calls[0]["user"]
    assert "Calendar: today = Fri 2026-10-09" in user and "Expected participants: 6" in user
    assert user.rstrip().endswith("quotes stay as spoken.") and user.index("TASK REMINDER") > user.index(
        "TRANSCRIPT-")
    assert llm.calls[0]["num_predict"] == 8192


def test_uzun_segment_kesilmaydi_davomi_bilan():
    seg = {"id": 12, "start": 190.0, "speaker": "S2", "text": "so'z " * 300 + "oxirida ertaga yuboraman"}
    line = prompts.transcript_line(seg, {})
    parts = line.split("\n")
    assert len(parts) == 2 and parts[1].startswith("#12 [03:10] S2 (cont.): ") and line.endswith("ertaga yuboraman")


def test_kesilish_belgisi_inglizcha_promptni_kesilgan_demaydi():
    llm = FakeLLM()
    estimate = None

    def reply(op, system, user):
        return auto_reply(op, system, user)

    llm.reply = reply
    p = Pipeline(llm, verify=False)
    system, user = "s" * 4400, "u" * 4400
    estimate = (len(system) + len(user)) / 2.2
    assert not p._truncated(system, user, {"tokensIn": int(estimate / 2.1)})       # inglizcha ~4.4 belgi/token
    assert p._truncated(system, user, {"tokensIn": int(estimate * 0.2)})


def test_coverage_boshi_mos_kelmasa_map_yoliga():
    llm = FakeLLM()
    data = json.loads(auto_reply("meeting_extract", "", "\n".join(
        f"#{i} [00:00] {s}: {t}" for i, (s, t) in enumerate(LINES, start=1))))
    data["coverage"] = {"firstId": 4, "lastId": 7}
    llm.script["meeting_extract"] = [json.dumps(data, ensure_ascii=False)]
    result = Pipeline(llm, verify=False).run(make_input())
    assert "single_pass_fallback" in result.content["quality"]["warnings"] and "meeting_map" in llm.ops()


# --- "Qisqa xulosa": asosiy fikrlar har shablonda (2026-10-10) ------------------------------------


def _extract(lines=LINES, **changes) -> str:
    data = json.loads(auto_reply("meeting_extract", "", "\n".join(
        f"#{i} [00:00] {s}: {t}" for i, (s, t) in enumerate(lines, start=1))))
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


def test_prompt_meeting_3_qisqa_xulosa_qoidalari():
    system = prompts.extract_system("general")
    for needle in ("3-6 takeaways", "(required, a short call too)", "16. SHORT SUMMARY", "G'oya:",
                   '"overview": never more than 2 sentences', '"purpose": why the meeting was held',
                   "sharp human note-taker", "no bureaucratic or translated-sounding phrases"):
        assert needle in system, needle
    assert "3-5 sentences (5-8" not in system and "3-7 takeaways" not in system
    # "Qisqa xulosa" qoidalari map bo'lagi promptida YO'Q (v3 da har belgi transkript joyini yeydi).
    assert prompts.BRIEF_RULES not in prompts.map_system() and "1-2 short sentences" in prompts.map_system()
    assert "3-6" in prompts.WRITER_SYSTEM and "never more than 2" in prompts.WRITER_SYSTEM
    assert "\"keyPoints\" are REQUIRED" in prompts.WRITER_SYSTEM
    # Eslatma: bir o'tishda "Qisqa xulosa" kalitlari bilan; map bo'lagida (keyPoints/overview yo'q) - yo'q.
    assert prompts.BRIEF_REMINDER in prompts.reminder("uz", final=True)
    assert prompts.BRIEF_REMINDER not in prompts.reminder("uz")
    short = prompts.template_block("short_call")
    assert "Write the purpose, a 1-2 sentence overview and 3-6 short keyPoints" in short
    assert "keep topics, risks, nextSteps and templateSections empty" in short
    assert [e["key"] for e in templates.layout("short_call", "uz")][:3] == ["overview", "keyPoints", "actionItems"]
    assert templates.get("short_call").version == "short_call-3"


def test_eslatma_faqat_bir_otishda():
    llm = FakeLLM()
    Pipeline(llm, single_pass_chars=3000, map_chars=2500, verify=False).run(make_input(repeat=20))
    maps = [c["user"] for c in llm.calls if c["op"] == "meeting_map"]
    assert maps and all(prompts.BRIEF_REMINDER not in u for u in maps)
    single = FakeLLM()
    Pipeline(single, verify=False).run(make_input())
    assert prompts.BRIEF_REMINDER in single.calls[0]["user"]


def test_bosh_asosiy_fikrlar_bir_marta_tuzatiladi():
    llm = FakeLLM()
    llm.script["meeting_extract"] = [_extract(keyPoints=[])]
    content = Pipeline(llm, verify=False).run(make_input(template="short_call")).content
    assert llm.ops() == ["meeting_extract", "meeting_extract"]
    repair = llm.calls[1]["user"]
    assert f"Your previous reply was invalid: {KEY_POINTS_MISSING}" in repair and llm.calls[1]["temperature"] == 0.0
    assert content["keyPoints"] == [{"id": "K1", "text": "Fikr 1", "sourceSegmentIds": [1], "start": 0.0}]
    assert "key_points_missing" not in content["quality"]["warnings"]


@pytest.mark.parametrize("second", ["empty", "broken", "truncated"])
def test_tuzatish_yomon_bolsa_birinchi_javob_qoladi(second):
    llm = FakeLLM()
    reply = {"empty": _extract(keyPoints=[], actionItems=[]), "broken": "buzuq javob",
             "truncated": (_extract(actionItems=[]), {"doneReason": "length", "tokensIn": None})}[second]
    llm.script["meeting_extract"] = [_extract(keyPoints=[]), reply]
    content = Pipeline(llm, verify=False).run(make_input()).content
    # Ikkinchi tuzatish so'ralmaydi, map yo'liga ham o'tilmaydi; birinchi (yaroqli) javobning
    # vazifalari yo'qolmaydi.
    assert llm.ops() == ["meeting_extract", "meeting_extract"]
    assert content["actionItems"][0]["task"] == "Vazifa 1ni bajarish" and content["keyPoints"] == []
    warnings = content["quality"]["warnings"]
    assert "key_points_missing" in warnings and "single_pass_fallback" not in warnings
    assert "validation_errors" not in warnings


def test_zanjirda_fikrsiz_javob_keyingi_modelga_otkazilmaydi():
    llm = FakeLLM()
    llm.script["meeting_extract"] = [_extract(keyPoints=[]), _extract(keyPoints=[])]
    out = Pipeline(llm, verify=False, strict=True).run(make_input())
    assert out.status == "ready" and out.content["actionItems"] and llm.ops() == ["meeting_extract"] * 2


def test_qisqa_matnda_fikrsiz_javob_tuzatilmaydi():
    lines = [("S1", "Salom, eshityapsizmi? Mikrofon ishlayaptimi, tekshirib ko'ramiz."),
             ("S2", "Ha, eshityapman, hammasi joyida, ovoz yaxshi chiqyapti, davom etamiz."),
             ("S1", "Yaxshi, unda ertaga yana uchrashamiz, xayr."),
             ("S2", "Mayli, ertaga soat o'nda shu xonada uchrashamiz, men ham vaqtida kelaman.")]
    assert 30 <= sum(len(t.split()) for _, t in lines) < REAL_CONTENT_WORDS
    llm = FakeLLM()
    llm.script["meeting_extract"] = [_extract(lines, keyPoints=[])]
    content = Pipeline(llm, verify=False).run(make_input(lines=lines)).content
    assert llm.ops() == ["meeting_extract"] and content["keyPoints"] == []
    assert "key_points_missing" not in content["quality"]["warnings"]


def test_yozuvchi_fikrsiz_bolsa_bir_marta_soraladi():
    llm = FakeLLM()

    def reply(op, system, user):
        data = json.loads(auto_reply(op, system, user))
        if op == "meeting_write" and not any(c["op"] == "meeting_write" for c in llm.calls[:-1]):
            data["keyPoints"] = []
        return json.dumps(data, ensure_ascii=False)

    llm.reply = reply
    content = Pipeline(llm, single_pass_chars=3000, map_chars=2500, verify=False).run(make_input(repeat=20)).content
    writes = [c for c in llm.calls if c["op"] == "meeting_write"]
    assert len(writes) == 2 and KEY_POINTS_MISSING in writes[1]["user"]
    assert [k["text"] for k in content["keyPoints"]] == ["Umumiy fikr"]
    assert "key_points_missing" not in content["quality"]["warnings"]


def test_tuzatishdan_faqat_asosiy_fikrlar_olinadi():
    # Birinchi javob yaroqli, faqat asosiy fikrlari (va maqsadi) yo'q; tuzatish - yangi chiqarish:
    # fikrlari bor, lekin bitta vazifani tashlab ketgan va qarorni boshqacha yozgan. Vazifa va
    # qarorlar BIRINCHI javobdan qolishi shart (6-qoida), tuzatishdan faqat fikrlar va maqsad.
    first = json.loads(_extract(keyPoints=[], purpose=None))
    second_task = dict(first["actionItems"][0], task="Hisobotni tayyorlab yuborish", sourceSegmentIds=[2],
                       owner={"speaker": "S2", "name": None, "kind": "person", "basis": "self_commitment"},
                       quote=" ".join(LINES[1][1].split()[:6]))
    first["actionItems"].append(second_task)
    repair = json.loads(_extract(purpose="Hisobotni muhokama qilish",
                                 keyPoints=[{"text": "Narx 15 mln so'm", "sourceSegmentIds": [3]}]))
    repair["decisions"][0]["text"] = "Boshqacha qaror"
    llm = FakeLLM()
    llm.script["meeting_extract"] = [json.dumps(first, ensure_ascii=False), json.dumps(repair, ensure_ascii=False)]
    content = Pipeline(llm, verify=False).run(make_input()).content
    assert llm.ops() == ["meeting_extract", "meeting_extract"]
    assert [a["task"] for a in content["actionItems"]] == ["Vazifa 1ni bajarish", "Hisobotni tayyorlab yuborish"]
    assert [d["text"] for d in content["decisions"]] == [first["decisions"][0]["text"]]
    assert [k["text"] for k in content["keyPoints"]] == ["Narx 15 mln so'm"]
    assert content["purpose"] == "Hisobotni muhokama qilish" and content["overview"] == first["overview"]
    assert "key_points_missing" not in content["quality"]["warnings"]

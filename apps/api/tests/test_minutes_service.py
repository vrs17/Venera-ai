"""Bayonnoma xizmati (`services/meetings/minutes/__init__.py`): yaratish, takror, chegara, xatolar, eksport;
ega ko'rsatmalari (yozishdan oldin), chatdagi o'zgartirish so'rovi bo'yicha TAHRIR (yangi versiya), navbat, kutish.

Model - `FakeLLM` (`MEETINGS_MINUTES_CHAIN=ollama`, `auto_reply`: op `meeting_minutes` - `minutes_reply`, tahrir
`meeting_minutes_revise` - `revision_reply`: `TITLE=` / `DROP=` / `CHAIR=` / `NOOP`); yig'ilish Slack yo'li bilan
tayyorlanadi (`slack_fakes.setup`, admin hisobi). Fon ishi `minutes.runner` orqali: default - shu ipda, `jobs`
fiksturasi bilan - navbatga (test o'zi `drain` qiladi). Ko'rsatma navbatlari to'g'ridan-to'g'ri omborga yoziladi
(`_note`; chat orqali - `test_meetings_chat`). Tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import time

from urllib.parse import quote

import pytest

from app.core.config import settings
from app.schemas import meetings as schemas
from app.services.meetings import llm, minutes, service, shapes
from app.services.meetings.errors import MeetingProblem
from app.services.meetings.minutes import diff, prompt
from app.services.meetings.store import jdump, jload, new_id
from app.slack import meeting, render, transcribe
from meetings_fakes import FakeAnthropic, run_all
from slack_fakes import AUDIO, FakeSlack, card, drive, setup

NO_CHANGES = {"items": {"changed": [], "added": [], "removed": []},
              "agenda": {"changed": [], "added": [], "removed": []}, "header": [], "other": []}


@pytest.fixture(autouse=True)
def _inline_runner(monkeypatch):
    """Fon ishi (`start`, `revise`) HAR TESTDA shu ipda - haqiqiy ip havzasi testda ishga tushmaydi."""
    monkeypatch.setattr(minutes, "runner", lambda job: job())


@pytest.fixture
def jobs(monkeypatch):
    """Fon ishlari navbati: ish shu ro'yxatga qo'yiladi, test `drain` bilan ishga tushiradi."""
    queue: list = []
    monkeypatch.setattr(minutes, "runner", queue.append)
    return queue


def drain(queue: list) -> None:
    while queue:
        queue.pop(0)()


@pytest.fixture
def ready(users_file, monkeypatch, _isolated_meetings):
    """(hisob, transkripti tayyor yig'ilish id, runtime) - bayonnoma zanjiri FakeLLM."""
    setup(monkeypatch, users_file)
    client = FakeSlack(files={"F1": AUDIO})
    meeting.handle(client, "D1", None, [AUDIO], sleep=drive(_isolated_meetings))
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    return transcribe.account(), render.marked(card(client)), _isolated_meetings


def _minutes_calls(rt) -> int:
    return len([c for c in rt.llm.calls if c["op"] == "meeting_minutes"])


def _ops(rt) -> list[str]:
    """Bayonnoma model chaqiruvlari: `meeting_minutes` (yangi hujjat) va `meeting_minutes_revise` (tahrir)."""
    return [c["op"] for c in rt.llm.calls if c["op"].startswith("meeting_minutes")]


def _note(rt, mid: str, text: str, *, asker: str | None = None, kind: str = "note",
          instruction: str | None = None) -> str:
    """Chat navbati to'g'ridan-to'g'ri omborga: default - bayonnoma ko'rsatmasi (`kind='note'`); `kind='create'` +
    `instruction` - ko'rsatma ham bergan "tayyorla" so'rovi (u ham ko'rsatma); `kind='revise'` - o'zgartirish
    so'rovi."""
    qid = new_id()
    rt.store.add_question({"id": qid, "meeting_id": mid, "question": text, "answer": "Ko'rsatmangiz eslab qolindi.",
                           "citations": "[]", "follow_ups": "[]", "kind": kind, "asker": asker, "channel": "api",
                           "minutes_json": jdump({"action": kind, "language": None, "instruction": instruction}),
                           "created_at": int(time.time())})
    return qid


def _revise(user, mid: str, words: str, *, lang: str = "uz-cyrl", **kwargs) -> dict:
    """O'zgartirish so'rovi -> qatorning (ish shu ipda tugagan) jonli holati."""
    started, _ = minutes.revise(user, mid, lang, {"text": words, "instruction": None}, **kwargs)
    return minutes.status(user, mid, started["id"], asker=kwargs.get("asker"))


def _content(rt, mid: str, minutes_id: str) -> dict:
    return jload(rt.store.minutes_row(mid, minutes_id)["content_json"])


def test_yaratish_takror_va_eksport(ready):
    user, mid, rt = ready
    view = minutes.generate(user, mid, "uz-cyrl")
    assert view["status"] == "ready" and view["provider"] == "ollama" and view["language"] == "uz-cyrl"
    assert (view["agendaCount"], view["sectionCount"], view["itemCount"]) == (2, 2, 3)
    assert view["stale"] is False and view["error"] is None and _minutes_calls(rt) == 1
    # Xuddi shu til - tayyori, model qayta chaqirilmaydi; boshqa yozuv shakli - yo'q.
    assert minutes.generate(user, mid, "UZ_CYRL")["id"] == view["id"] and _minutes_calls(rt) == 1
    assert minutes.latest(user, mid, "uz-cyrl")["id"] == view["id"] and minutes.latest(user, mid, "ru") is None
    assert minutes.generate(user, mid, "uz-cyrl", force=True)["id"] != view["id"] and _minutes_calls(rt) == 2
    assert len(minutes.listing(user, mid)["items"]) == 2
    # Eksport: Word, PDF, Markdown - fayl nomida hujjat so'zi va sana.
    docx, media, disposition = minutes.export_file(user, mid, view["id"], "docx")
    assert docx[:2] == b"PK" and media.startswith("application/vnd.openxmlformats") and "docx" in disposition
    assert "%D0%91%D0%B0%D1%91%D0%BD%D0%BD%D0%BE%D0%BC%D0%B0" in disposition      # "Баённома" (UTF-8 foiz bilan)
    pdf, media, _ = minutes.export_file(user, mid, view["id"], "pdf")
    assert pdf[:5] == b"%PDF-" and media == "application/pdf"
    md, media, _ = minutes.export_file(user, mid, view["id"], "md")
    assert "ҚАРОР ҚИЛАДИ:" in md.decode("utf-8") and media.startswith("text/markdown")
    full = minutes.get(user, mid, view["id"])
    assert full["content"]["language"] == "uz-cyrl" and full["content"]["version"] == minutes.prompt.MINUTES_VERSION
    with pytest.raises(MeetingProblem) as bad:
        minutes.export_file(user, mid, view["id"], "txt")
    assert bad.value.status_code == 400
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "de")
    assert bad.value.code == "invalid_language"


def test_model_sozlanmagan_va_chegara(ready, monkeypatch):
    user, mid, rt = ready
    monkeypatch.setattr(settings, "meetings_minutes_chain", "claude", raising=False)   # rt.claude yo'q
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "ru")
    assert bad.value.status_code == 503 and bad.value.code == "llm_not_configured"
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    monkeypatch.setattr(settings, "meetings_minutes_per_hour", 1, raising=False)
    minutes.generate(user, mid, "ru")
    # Tayyori chegarani yemaydi; yangi til - yeydi.
    minutes.generate(user, mid, "ru")
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "en")
    assert bad.value.status_code == 429


def test_kutilmagan_xato_qator_failed(ready, monkeypatch):
    user, mid, rt = ready
    monkeypatch.setattr(minutes.prompt, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "en")
    assert bad.value.status_code == 500
    [row] = rt.store.minutes_rows(mid)
    assert row["status"] == "failed" and row["error_code"] == "internal" and row["error"] == "RuntimeError"
    assert minutes.listing(user, mid)["items"][0]["error"] == {"code": "internal", "message": "RuntimeError"}


def test_model_yaroqsiz_javob_502(ready):
    user, mid, rt = ready
    rt.llm.script["meeting_minutes"] = ["bu JSON emas"]
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "en")
    assert bad.value.status_code == 502 and bad.value.code == "llm_failed"
    assert rt.store.minutes_rows(mid)[-1]["status"] == "failed"


def test_nutqsiz_yozuv_modelsiz_409(ready):
    # Jonli sinov (2026-11-05): 5 s jimlik - model chaqirilmasin, "qayta urinib ko'ring" emas, sabab aytilsin.
    user, mid, rt = ready
    rt.store.execute("UPDATE segments SET text='  ' WHERE meeting_id=?", (mid,))
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "uz-cyrl")
    assert (bad.value.status_code, bad.value.code) == (409, "transcript_empty")
    assert "nutq topilmadi" in bad.value.detail
    assert _minutes_calls(rt) == 0 and rt.store.minutes_rows(mid) == []


def test_izohlarda_spiker_tokeni_korinmaydi(ready):
    # Birinchi jonli sinov (2026-11-05): izohdagi "[S3] ва [S4]" Slack/Telegram xabariga xom tushgan edi.
    user, mid, rt = ready
    view = minutes.generate(user, mid, "uz-cyrl")
    content = jload(rt.store.minutes_row(mid, view["id"])["content_json"])
    content["notes"] = ["[S1] нинг лавозими аниқлаштирилсин.", "[S9] 03:10 да эшитилмади."]
    rt.store.update_minutes(view["id"], content_json=jdump(content))
    service.rename_speaker(user, mid, "S1", "Aziz Karimov")
    expected = ["Aziz Karimov нинг лавозими аниқлаштирилсин.", "9-иштирокчи 03:10 да эшитилмади."]
    assert minutes.latest(user, mid, "uz-cyrl")["notes"] == expected
    assert minutes.get(user, mid, view["id"])["notes"] == expected
    md = minutes.export_file(user, mid, view["id"], "md")[0].decode("utf-8")
    assert "Aziz Karimov нинг лавозими аниқлаштирилсин." in md and "[S" not in md


# --- ega ko'rsatmalari (yozishdan oldin) -----------------------------------------------------------------


def test_korsatma_promptga_va_qatorga(ready, monkeypatch):
    """Ko'rsatma minutes promptida OWNER INSTRUCTIONS bloki bo'lib (transkriptdan OLDIN) boradi; qator qaysi
    ko'rsatmalar berilganini eslaydi (`guidance_json`), ko'rinishda `notesApplied`. Boshqa so'rovchining (Slack odami)
    ko'rsatmasi bu promptga kirmaydi. Sig'maganlar (eng eskilari) - `guidance_truncated`, lekin "qo'llangan"."""
    user, mid, rt = ready
    nid = _note(rt, mid, "Kredit masalalariga alohida e'tibor bering")
    _note(rt, mid, "Begona ko'rsatma", asker="slack:U9")
    view = minutes.generate(user, mid, "uz-cyrl")
    [call] = [c for c in rt.llm.calls if c["op"] == "meeting_minutes"]
    assert "OWNER INSTRUCTIONS" in call["user"] and "1. Kredit masalalariga alohida e'tibor bering" in call["user"]
    assert call["user"].index("OWNER INSTRUCTIONS") < call["user"].index("<<<TRANSCRIPT-")
    assert "Begona" not in call["user"] and call["options"] == {"effort": settings.meetings_minutes_effort}
    row = rt.store.minutes_row(mid, view["id"])
    assert jload(row["guidance_json"]) == {
        "notes": [{"id": nid, "text": "Kredit masalalariga alohida e'tibor bering"}], "dropped": 0}
    assert (row["asker"], row["revision"], row["parent_id"], row["turn_id"]) == (None, 0, None, None)
    assert (view["kind"], view["version"], view["notesApplied"], view["pendingNotes"]) == ("generate", 1, 1, 0)
    assert minutes.status(user, mid, view["id"], asker="slack:U9")["pendingNotes"] == 1
    assert minutes.listing(user, mid)["notes"] == 1 and minutes.listing(user, mid, asker="slack:U9")["notes"] == 1
    # Promptdagi ko'rsatmalar chegarasi: eng yangisi sig'adi, eskisi tushadi (ogohlantirish bilan).
    monkeypatch.setattr(settings, "meetings_minutes_guidance_chars", 50, raising=False)
    _note(rt, mid, "Rais - Alisher Karimov")
    forced = minutes.generate(user, mid, "uz-cyrl", force=True)
    last = rt.llm.calls[-1]["user"]
    assert "1. Rais - Alisher Karimov" in last and "Kredit masalalariga" not in last
    assert "guidance_truncated:1" in forced["warnings"]
    assert jload(rt.store.minutes_row(mid, forced["id"])["guidance_json"])["dropped"] == 1
    assert (forced["notesApplied"], forced["pendingNotes"]) == (2, 0)


def test_yangi_korsatmasiz_qayta_bosish_bepul(ready):
    user, mid, rt = ready
    _note(rt, mid, "Rais - Alisher Karimov")
    first = minutes.generate(user, mid, "uz-cyrl")
    for _ in range(2):
        assert minutes.generate(user, mid, "uz-cyrl")["id"] == first["id"]
    view, started = minutes.start(user, mid, "uz-cyrl")
    assert started is False and view["id"] == first["id"] and view["status"] == "ready"
    # Boshqa so'rovchining ko'rsatmasi hisob egasining bosishini pullik qilmaydi.
    _note(rt, mid, "Slack odamining ko'rsatmasi", asker="slack:U1")
    assert minutes.generate(user, mid, "uz-cyrl")["id"] == first["id"]
    assert _ops(rt) == ["meeting_minutes"] and len(rt.store.minutes_rows(mid)) == 1


def test_kutilayotgan_korsatma_tahrir_boladi(ready, monkeypatch):
    """Hujjat tayyor bo'lgach berilgan ko'rsatma: til bosilsa hujjat QAYTADAN yozilmaydi - HEAD ning tahriri (yangi
    ko'rsatma [new], avvalgisi [applied], tahrir effort'i); keyingi bosish bepul; `force` - barcha ko'rsatmalar bilan
    yangi asl hujjat."""
    user, mid, rt = ready
    first = _note(rt, mid, "Rais - Alisher Karimov")
    head = minutes.generate(user, mid, "uz-cyrl")
    second = _note(rt, mid, "Kredit masalalariga alohida e'tibor bering")
    assert minutes.latest(user, mid, "uz-cyrl")["pendingNotes"] == 1
    monkeypatch.setattr(settings, "meetings_minutes_revise_effort", "max", raising=False)
    edited = minutes.generate(user, mid, "uz-cyrl")
    assert _ops(rt) == ["meeting_minutes", "meeting_minutes_revise"]
    call = rt.llm.calls[-1]
    assert call["options"] == {"effort": "max"} and call["system"] == prompt.system_revision("uz-cyrl")
    assert "1. [applied] Rais - Alisher Karimov" in call["user"]
    assert "2. [new] Kredit masalalariga alohida e'tibor bering" in call["user"]
    assert prompt.NOTES_ONLY_REQUEST in call["user"]
    row = rt.store.minutes_row(mid, edited["id"])
    assert (row["parent_id"], row["revision"], row["request_json"]) == (head["id"], 1, None)
    assert (edited["kind"], edited["version"], edited["parentId"], edited["request"]) == ("revise", 2, head["id"], None)
    assert (edited["notesApplied"], edited["pendingNotes"]) == (2, 0)
    assert edited["changes"] == {**NO_CHANGES, "other": ["title"]}           # soxta model: sarlavhaga " (tahrir)"
    assert [n["id"] for n in jload(row["guidance_json"])["notes"]] == [first, second]
    assert minutes.generate(user, mid, "uz-cyrl")["id"] == edited["id"] and len(_ops(rt)) == 2
    forced = minutes.generate(user, mid, "uz-cyrl", force=True)
    row = rt.store.minutes_row(mid, forced["id"])
    assert (row["parent_id"], row["revision"], _ops(rt)[-1]) == (None, 0, "meeting_minutes")
    assert [n["id"] for n in jload(row["guidance_json"])["notes"]] == [first, second]
    assert "Rais - Alisher Karimov" in rt.llm.calls[-1]["user"] and "Kredit" in rt.llm.calls[-1]["user"]
    assert not any(w.startswith("superseded_revisions:") for w in forced["warnings"])


def test_sarlavha_korsatmadan(ready):
    """Ko'rsatmadagi rais (`CHAIR=`) - hujjat sarlavha qismida va Word dagi "Раислик қилувчи" qatorida."""
    user, mid, rt = ready
    _note(rt, mid, "CHAIR=Alisher Karimov")
    view = minutes.generate(user, mid, "uz-cyrl")
    assert view["header"] == {"chair": "Alisher Karimov"}
    assert _content(rt, mid, view["id"])["header"]["chair"] == "Alisher Karimov"
    md = minutes.export_file(user, mid, view["id"], "md")[0].decode("utf-8")
    assert "**Раислик қилувчи:** Alisher Karimov" in md
    # Ko'rsatma hamma tilga beriladi.
    other = minutes.generate(user, mid, "ru")
    assert other["header"] == {"chair": "Alisher Karimov"} and other["notesApplied"] == 1


# --- tahrir (chatdagi o'zgartirish so'rovi) ------------------------------------------------------------------


def test_tahrir_boshlanishidan_oxirigacha(ready):
    user, mid, rt = ready
    head = minutes.generate(user, mid, "uz-cyrl")
    started, began = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Yangi sarlavha",
                                                            "instruction": "Sarlavhani «Yangi sarlavha» qiling"})
    assert began is True and started["status"] == "running" and started["kind"] == "revise"
    done = minutes.status(user, mid, started["id"])
    assert (done["status"], done["kind"], done["version"], done["parentId"]) == ("ready", "revise", 2, head["id"])
    assert done["request"] == "TITLE=Yangi sarlavha" and done["changes"] == {**NO_CHANGES, "other": ["title"]}
    row = rt.store.minutes_row(mid, started["id"])
    assert row["transcript_gen"] == rt.store.meeting_any(mid)["transcript_gen"] and row["revision"] == 1
    assert jload(row["request_json"]) == {"text": "TITLE=Yangi sarlavha",
                                          "instruction": "Sarlavhani «Yangi sarlavha» qiling"}
    assert _content(rt, mid, started["id"])["title"] == "Yangi sarlavha"
    call = rt.llm.calls[-1]
    assert call["op"] == "meeting_minutes_revise" and call["options"] == {"effort": settings.meetings_minutes_effort}
    assert call["user"].count("<<<TRANSCRIPT-") == 1 and call["user"].count("<<<MINUTES-") == 1
    assert prompt.NUMBERING_HEAD in call["user"] and "1. TITLE=Yangi sarlavha" in call["user"]
    assert f"{prompt.READING_HEAD}Sarlavhani «Yangi sarlavha» qiling" in call["user"]
    # Til tugmasi endi tahrirni qaytaradi - model chaqirilmaydi.
    assert minutes.generate(user, mid, "uz-cyrl")["id"] == started["id"] and len(_ops(rt)) == 2
    md, _, disposition = minutes.export_file(user, mid, started["id"], "md")
    assert "2-таҳрир." in md.decode("utf-8") and quote("(2-таҳрир)", safe="") in disposition
    # Bo'sh so'rov va noma'lum til - qator ham, model ham yo'q.
    for lang, words, code in (("uz-cyrl", "  ", "invalid_request"), ("de", "TITLE=x", "invalid_language")):
        with pytest.raises(MeetingProblem) as bad:
            minutes.revise(user, mid, lang, {"text": words})
        assert (bad.value.status_code, bad.value.code) == (400, code)
    assert len(rt.store.minutes_rows(mid)) == 2


def test_ozgarishsiz_tahrir_no_change(ready):
    """So'rov hujjatni o'zgartirmadi - yangi versiya yo'q (`no_change`, HEAD o'sha). Yangi ko'rsatmalarni qo'llash
    o'zgarishsiz bo'lsa ham tayyor saqlanadi: ko'rsatma endi "qo'llangan", qayta bosish yana pul sarflamaydi."""
    user, mid, rt = ready
    head = minutes.generate(user, mid, "uz-cyrl")
    failed = _revise(user, mid, "NOOP - hech narsa o'zgarmasin")
    assert failed["status"] == "failed" and failed["kind"] == "revise"
    assert failed["error"] == {"code": "no_change", "message": minutes.FAILURES["no_change"][1]}
    assert minutes.failure_detail(failed) == minutes.FAILURES["no_change"][1]
    assert minutes.latest(user, mid, "uz-cyrl")["id"] == head["id"]
    assert minutes.generate(user, mid, "uz-cyrl")["id"] == head["id"] and len(_ops(rt)) == 2
    _note(rt, mid, "NOOP: bu hujjatda allaqachon bor")
    applied = minutes.generate(user, mid, "uz-cyrl")
    assert (applied["status"], applied["kind"], applied["version"]) == ("ready", "revise", 2)
    assert applied["changes"] == NO_CHANGES and diff.empty(applied["changes"])
    assert (applied["notesApplied"], applied["pendingNotes"]) == (1, 0)
    assert _content(rt, mid, applied["id"])["title"] == _content(rt, mid, head["id"])["title"]
    assert minutes.generate(user, mid, "uz-cyrl")["id"] == applied["id"] and len(_ops(rt)) == 3


def test_navbatdagi_tahrir_oldingisi_ustiga(ready, jobs):
    """Uchta tahrir navbatda: har biri qulf ichida O'SHA PAYTDAGI joriy hujjat ustiga yoziladi. O'zgarishsiz
    (`no_change`) qolgani zanjirga kirmaydi - undan keyingisi oldingi tayyor versiyaga qayta ulanadi."""
    user, mid, rt = ready
    head = minutes.generate(user, mid, "uz-cyrl")
    first, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Birinchi"})
    noop, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "NOOP"})
    chair, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "CHAIR=Alisher Karimov"})
    # Ota-versiya vaqtincha - yozilayotgan eng yangi ish.
    assert [(v["parentId"], v["version"]) for v in (first, noop, chair)] == \
        [(head["id"], 2), (first["id"], 3), (noop["id"], 4)]
    assert len(jobs) == 3 and _ops(rt) == ["meeting_minutes"]
    drain(jobs)
    assert minutes.status(user, mid, noop["id"])["error"]["code"] == "no_change"
    row = rt.store.minutes_row(mid, chair["id"])
    assert (row["status"], row["parent_id"], row["revision"]) == ("ready", first["id"], 2)
    content = _content(rt, mid, chair["id"])
    assert content["title"] == "Birinchi" and content["header"]["chair"] == "Alisher Karimov"
    assert jload(row["changes_json"]) == {**NO_CHANGES, "header": ["chair"]}
    assert minutes.latest(user, mid, "uz-cyrl")["id"] == chair["id"]
    # Oxirgi tahrir promptida oldingi so'rov "allaqachon qo'llangan" bo'lib boradi.
    last = rt.llm.calls[-1]["user"]
    assert prompt.EARLIER_HEAD in last and "1. TITLE=Birinchi" in last and "NOOP" not in last


def test_qayta_ogirilgandan_keyin_tahrir_yoq(ready):
    """Tahrir asosi - joriy transkript AVLODINING hujjati: hujjat yo'q - 409 `minutes_missing`; qator tahriridan keyin
    (avlod o'sha) - tahrir mumkin va joriy versiyada yoziladi; qayta o'girilgandan keyin - 409 `minutes_outdated`."""
    user, mid, rt = ready
    with pytest.raises(MeetingProblem) as bad:
        minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=x"})
    assert (bad.value.status_code, bad.value.code, bad.value.detail) == \
        (409, "minutes_missing", minutes.FAILURES["minutes_missing"][1])
    head = minutes.generate(user, mid, "uz-cyrl")
    segment = rt.store.segments(mid)[0]
    service.edit_segment(user, mid, int(segment["id"]), schemas.SegmentPatchRequest(text="Tuzatilgan matn"))
    rev = int(rt.store.meeting_any(mid)["transcript_rev"])
    edited = _revise(user, mid, "TITLE=Matn tahriridan keyin")
    assert edited["status"] == "ready" and edited["parentId"] == head["id"] and edited["transcriptRev"] == rev
    assert edited["stale"] is False and prompt.STALE_NOTE in rt.llm.calls[-1]["user"]
    service.retranscribe(user, mid, schemas.RetranscribeRequest(language="uz", confirmCharge=True))
    run_all(rt)
    assert service._transcript_ready(rt.store.meeting_any(mid))
    with pytest.raises(MeetingProblem) as bad:
        minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=y"})
    assert (bad.value.status_code, bad.value.code) == (409, "minutes_outdated")
    assert minutes.base_row(rt.store, rt.store.meeting_any(mid), "uz-cyrl") == (None, "minutes_outdated")


def test_tahrir_chegarasi_soraluvchi_boyicha(ready, jobs, monkeypatch):
    """Tahrir chegarasi (`minutes_edit`) - so'rovchiga (Slack'da har odamga alohida) va yangi hujjat chegarasidan
    (`minutes`) mustaqil. Navbatda turganda asos yo'qolsa (yozuv qayta o'girildi) - qator `failed`, joy qaytadi."""
    user, mid, rt = ready
    monkeypatch.setattr(settings, "meetings_minutes_per_hour", 1, raising=False)
    monkeypatch.setattr(settings, "meetings_minutes_edits_per_hour", 1, raising=False)
    minutes.generate(user, mid, "uz-cyrl")                                   # "minutes" chegarasi tugadi
    minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Bir"})
    with pytest.raises(MeetingProblem) as bad:
        minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Ikki"})
    assert (bad.value.status_code, bad.value.code) == (429, "rate_limited")
    minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Slack"}, asker="slack:U1")
    with pytest.raises(MeetingProblem) as bad:
        minutes.generate(user, mid, "ru")                                    # yangi hujjat - o'z chegarasi
    assert bad.value.status_code == 429
    drain(jobs)
    # Asos navbatda yo'qoldi: qator `failed` (sabab - odamga matn), joy qaytdi.
    lost, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Uch"}, asker="slack:U2")
    rt.store.execute("UPDATE meetings SET transcript_gen = transcript_gen + 1 WHERE id=?", (mid,))
    drain(jobs)
    gone = minutes.status(user, mid, lost["id"])
    assert gone["status"] == "failed"
    assert gone["error"] == {"code": "minutes_outdated", "message": minutes.FAILURES["minutes_outdated"][1]}
    rt.store.execute("UPDATE meetings SET transcript_gen = transcript_gen - 1 WHERE id=?", (mid,))
    again, began = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=To'rt"}, asker="slack:U2")
    assert began is True
    drain(jobs)
    assert minutes.status(user, mid, again["id"])["status"] == "ready"


def test_navbat_chegarasi(ready, jobs):
    """Shu til uchun `MAX_LIVE` ta tirik ish: to'rtinchi tahrir (va yangi ko'rsatmalar bilan til bosish) - 409
    `minutes_busy`; boshqa tilga ta'sir qilmaydi."""
    user, mid, rt = ready
    minutes.generate(user, mid, "uz-cyrl")                                   # til tugmasi - ish shu ipda
    for n in range(minutes.MAX_LIVE):
        minutes.revise(user, mid, "uz-cyrl", {"text": f"TITLE=Versiya {n + 2}"})
    with pytest.raises(MeetingProblem) as bad:
        minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Ortiqcha"})
    assert (bad.value.status_code, bad.value.code, bad.value.detail) == \
        (409, "minutes_busy", minutes.FAILURES["minutes_busy"][1])
    _note(rt, mid, "Yangi ko'rsatma")
    with pytest.raises(MeetingProblem) as bad:
        minutes.start(user, mid, "uz-cyrl")
    assert bad.value.code == "minutes_busy"
    view, began = minutes.start(user, mid, "ru")
    assert began is True and view["kind"] == "generate"
    assert len(rt.store.minutes_rows(mid)) == 1 + minutes.MAX_LIVE + 1


def test_turn_id_bir_ish(ready):
    """Bitta chat navbati - bitta ish: o'sha `turn_id` bilan qayta chaqiruv (qayta yuborish) o'sha qatorni qaytaradi,
    model qayta chaqirilmaydi."""
    user, mid, rt = ready
    minutes.generate(user, mid, "uz-cyrl")
    first, began = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Bir"}, turn_id="t-1")
    again, repeat = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Bir"}, turn_id="t-1")
    assert (began, repeat) == (True, False) and again["id"] == first["id"] and again["status"] == "ready"
    assert rt.store.minutes_by_turn("t-1")["id"] == first["id"] and _ops(rt).count("meeting_minutes_revise") == 1
    note = _note(rt, mid, "Bayonnoma tayyorla, kredit masalalariga e'tibor bering", kind="create",
                 instruction="Kredit masalalariga e'tibor bering")
    made, began = minutes.start(user, mid, "uz-cyrl", turn_id=note)
    same, repeat = minutes.start(user, mid, "uz-cyrl", turn_id=note)
    assert (began, repeat) == (True, False) and same["id"] == made["id"] and same["kind"] == "revise"
    assert _ops(rt).count("meeting_minutes_revise") == 2 and rt.store.minutes_by_turn(note)["id"] == made["id"]


def test_matn_tahririda_eski_tahrirlar_ogohlantirish(ready):
    """Qator tahriridan keyin til bosilsa hujjat transkriptdan yangidan yoziladi: oldingi joriy hujjat tahrirlangan
    versiya edi - `superseded_revisions:<n>` (ilovada va botlarda "avvalgi n ta o'zgartirish kiritilmagan").
    `force` (odam ataylab qayta yozdi) - ogohlantirishsiz."""
    user, mid, rt = ready
    minutes.generate(user, mid, "uz-cyrl")
    assert _revise(user, mid, "TITLE=Tahrirlangan")["status"] == "ready"
    segment = rt.store.segments(mid)[1]
    service.edit_segment(user, mid, int(segment["id"]), schemas.SegmentPatchRequest(text="Yangi matn"))
    fresh = minutes.generate(user, mid, "uz-cyrl")
    assert fresh["kind"] == "generate" and "superseded_revisions:1" in fresh["warnings"]
    forced = minutes.generate(user, mid, "uz-cyrl", force=True)
    assert not any(w.startswith("superseded_revisions:") for w in forced["warnings"])


# --- botlar: kutish va xato ------------------------------------------------------------------------------


def test_wait_va_failure(ready, jobs):
    user, mid, rt = ready
    sleeps: list[float] = []
    started, _ = minutes.start(user, mid, "uz-cyrl")
    # Navbat hech qachon yurmasa - `timeout` dan keyin ham `running` (aylanishlar soni bilan chegaralangan).
    still = minutes.wait(user, mid, started["id"], sleep=sleeps.append, every=2.0, timeout=10.0)
    assert still["status"] == "running" and sleeps == [2.0] * 5
    sleeps.clear()
    joined = minutes.generate(user, mid, "uz-cyrl", sleep=sleeps.append)       # boshqa yo'lning ishiga qo'shildi
    assert joined["id"] == started["id"] and joined["status"] == "running"
    assert len(sleeps) == int(minutes.WAIT_SEC / minutes.WAIT_EVERY)
    drain(jobs)
    sleeps.clear()
    done = minutes.wait(user, mid, started["id"], sleep=sleeps.append)
    assert done["status"] == "ready" and sleeps == []
    noop, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "NOOP"})
    drain(jobs)
    failed = minutes.wait(user, mid, noop["id"], sleep=sleeps.append)
    assert failed["status"] == "failed" and sleeps == []

    # `failure`: holat, kod va odamga matn `FAILURES` dan; tahrirda model yiqilsa - o'z matni.
    def problem(code: str, kind: str = "generate") -> MeetingProblem:
        return minutes.failure({"status": "failed", "kind": kind, "error": {"code": code, "message": "texnik"}})

    busy = problem("llm_busy")
    assert (busy.status_code, busy.code, busy.detail, busy.headers) == (
        503, "llm_busy", "Model hozir band - birozdan keyin qayta urinib ko'ring", {"Retry-After": "30"})
    limited = problem("llm_rate_limited")
    assert (limited.status_code, limited.headers) == (429, {"Retry-After": "60"})
    assert (problem("llm_failed").status_code, problem("llm_failed").detail) == \
        (502, "Model bayonnomani yozolmadi - qayta urinib ko'ring")
    assert problem("llm_failed", "revise").detail == minutes.REVISE_FAILED
    assert (problem("no_change", "revise").status_code, problem("internal").status_code) == (409, 500)
    assert problem("interrupted").detail == minutes.INTERRUPTED and problem("interrupted").headers is None
    odd = problem("boshqa_kod")
    assert (odd.status_code, odd.code, odd.detail) == (502, "boshqa_kod", minutes.FAILURES["llm_failed"][1])


def test_yangi_suhbatdan_keyin_ism_saqlanadi(ready):
    """Rais tahrir bilan berildi, so'ng "Yangi suhbat" (so'rov navbati arxivda): keyingi tahrirda rais tushib qolmaydi
    - asosdagi ism va oldingi so'rovlar ega matni sifatida asosli (`header_dropped` yo'q)."""
    user, mid, rt = ready
    minutes.generate(user, mid, "uz-cyrl")
    turn = _note(rt, mid, "CHAIR=Alisher Karimov", kind="revise")
    chaired = _revise(user, mid, "CHAIR=Alisher Karimov", turn_id=turn)
    assert chaired["header"] == {"chair": "Alisher Karimov"}
    assert service.chat_reset(user, mid)["archived"] == 1
    later = _revise(user, mid, "TITLE=Keyingi sarlavha")
    assert later["header"] == {"chair": "Alisher Karimov"} and later["changes"] == {**NO_CHANGES, "other": ["title"]}
    assert not any(w.startswith("header_dropped:") for w in later["warnings"])
    assert "Alisher Karimov" not in "".join(t["question"] for t in rt.store.chat_turns(mid))


def test_nusxa_yoli_provenance(ready, jobs):
    """Navbatdagi asl hujjat ishi: shu versiyada tayyor hujjat paydo bo'lgan va unda shu qatorga berilgan hamma
    ko'rsatma bor - model chaqirilmaydi, mazmun ham, kelib chiqishi ham ko'chadi; `turn_id` ko'chmaydi. Ko'rsatma
    tayyor hujjatda bo'lmasa - nusxa yo'q, model yozadi."""
    user, mid, rt = ready
    queued, _ = minutes.start(user, mid, "uz-cyrl", turn_id="t-own")
    rev = int(rt.store.meeting_any(mid)["transcript_rev"])
    gen = int(rt.store.meeting_any(mid)["transcript_gen"])
    donor = _donor_row(rt, mid, "uz-cyrl", rev, gen, turn_id="t-donor", revision=2, parent_id="p" * 32,
                       request={"text": "TITLE=Donor", "instruction": None}, changes={**NO_CHANGES, "other": ["title"]},
                       guidance={"notes": [{"id": "n-1", "text": "Rais"}], "dropped": 0})
    drain(jobs)
    row = rt.store.minutes_row(mid, queued["id"])
    source = rt.store.minutes_row(mid, donor)
    for key in ("status", "provider", "model", "content_json", "finished_at", "parent_id", "revision", "request_json",
                "changes_json", "guidance_json", "transcript_gen", "prompt_version"):
        assert row[key] == source[key], key
    assert (row["turn_id"], row["error_code"], row["error"]) == ("t-own", None, None) and _ops(rt) == []
    # Ko'rsatma tayyor hujjatda yo'q - ko'chirilmaydi, model shu ko'rsatma bilan yozadi.
    note = _note(rt, mid, "Kredit masalalariga e'tibor bering")
    own, _ = minutes.start(user, mid, "ru")
    _donor_row(rt, mid, "ru", rev, gen)
    drain(jobs)
    row = rt.store.minutes_row(mid, own["id"])
    assert row["status"] == "ready" and _ops(rt) == ["meeting_minutes"]
    assert [n["id"] for n in jload(row["guidance_json"])["notes"]] == [note]


def _donor_row(rt, mid: str, lang: str, rev: int, gen: int, *, turn_id: str | None = None, revision: int = 0,
               parent_id: str | None = None, request: dict | None = None, changes: dict | None = None,
               guidance: dict | None = None) -> str:
    """Boshqa yo'l (bot) yozib qo'ygan tayyor hujjat - to'g'ridan-to'g'ri omborga."""
    row_id = new_id()
    content = {"title": "Donor", "agenda": [], "sections": [], "notes": [], "version": "minutes-2"}
    rt.store.insert_minutes({
        "id": row_id, "meeting_id": mid, "language": lang, "transcript_rev": rev, "transcript_gen": gen,
        "prompt_version": "minutes-2", "status": "ready", "provider": "claude", "model": "claude-test",
        "content_json": jdump(content), "created_at": int(time.time()), "finished_at": int(time.time()) - 5,
        "turn_id": turn_id, "revision": revision, "parent_id": parent_id, "request_json": jdump(request),
        "changes_json": jdump(changes), "guidance_json": jdump(guidance)})
    return row_id


def test_claude_tahrir_sxemasi_va_effort(ready, monkeypatch):
    """Ishlab chiqarish zanjiri (Claude): tahrir `meeting_minutes_revise` amali bilan ketadi - sxema bayonnomaniki,
    `effort` - `MEETINGS_MINUTES_REVISE_EFFORT` (bo'sh bo'lsa - `MEETINGS_MINUTES_EFFORT`), tizim prompti - tahrir."""
    user, mid, rt = ready
    fake = FakeAnthropic()
    rt.claude = llm.ClaudeChat(lambda: "sk-ant-test-MINUTES", "claude-sonnet-5-5", timeout=10, client_factory=fake)
    monkeypatch.setattr(settings, "meetings_minutes_chain", "claude", raising=False)
    head = minutes.generate(user, mid, "uz-cyrl")
    assert head["provider"] == "claude" and fake.ops() == ["meeting_minutes"]
    assert fake.requests[0]["output_config"]["effort"] == settings.meetings_minutes_effort
    edited = _revise(user, mid, "DROP=2")
    assert edited["status"] == "ready" and fake.ops() == ["meeting_minutes", "meeting_minutes_revise"]
    request = fake.requests[-1]
    assert request["output_config"]["format"]["schema"] == shapes.minutes()
    assert request["output_config"]["effort"] == settings.meetings_minutes_effort
    assert request["system"] == prompt.system_revision("uz-cyrl")
    assert edited["changes"]["items"] == {"changed": [], "added": [], "removed": [2]}
    assert edited["itemCount"] == head["itemCount"] - 1
    monkeypatch.setattr(settings, "meetings_minutes_revise_effort", "max", raising=False)
    _revise(user, mid, "TITLE=Yana")
    assert fake.requests[-1]["output_config"]["effort"] == "max"


def test_navbat_tartibsiz_bajarilsa_joriy_hujjat_zanjir_uchi(ready, jobs):
    """Qulf adolatli emas: keyin so'ralgan tahrir (R2) oldin bajarilsa, oldin so'ralgani (R1) uning ustiga yoziladi va
    JORIY hujjat R1 bo'ladi (zanjir uchi, eng keyin tayyor bo'lgan) - R1 ning o'zgarishi tushib qolmaydi: HEAD, BASE,
    joriy til va til tugmasi bir xil hujjatni ko'radi."""
    user, mid, rt = ready
    head = minutes.generate(user, mid, "uz-cyrl")
    first, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Birinchi"})
    second, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "CHAIR=Alisher Karimov"})
    jobs.pop()()                                                   # R2 oldin
    jobs.pop()()                                                   # keyin R1 - R2 ustiga
    r1, r2 = rt.store.minutes_row(mid, first["id"]), rt.store.minutes_row(mid, second["id"])
    assert (r2["status"], r2["parent_id"]) == ("ready", head["id"])
    assert (r1["status"], r1["parent_id"], r1["revision"]) == ("ready", second["id"], 2)
    content = _content(rt, mid, first["id"])
    assert content["title"] == "Birinchi" and content["header"]["chair"] == "Alisher Karimov"
    m = rt.store.meeting_any(mid)
    assert minutes.latest(user, mid, "uz-cyrl")["id"] == first["id"]
    assert minutes.base_row(rt.store, m, "uz-cyrl")[0]["id"] == first["id"]
    calls = len(_ops(rt))
    assert minutes.generate(user, mid, "uz-cyrl")["id"] == first["id"] and len(_ops(rt)) == calls


def test_til_tugmasi_begona_yiqilgan_ishdan_keyin_tayyorini_beradi(ready, jobs):
    """Til tugmasi boshqa yo'lning yozilayotgan tahririga qo'shildi va u yiqildi (o'zgarishsiz so'rov): tugma o'sha
    xatoni emas, TAYYOR hujjatni yuboradi. O'zi boshlagan ish yiqilsa - xato avvalgidek."""
    user, mid, rt = ready
    head = minutes.generate(user, mid, "uz-cyrl")
    noop, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "NOOP"})
    found = minutes.generate(user, mid, "uz-cyrl", sleep=lambda _: drain(jobs))
    assert (found["id"], found["status"]) == (head["id"], "ready")
    assert minutes.status(user, mid, noop["id"])["error"]["code"] == "no_change"


def test_navbatda_matn_tahrirlansa_hozirgi_versiya_bilan_belgilanadi(ready, jobs):
    """Tahrir navbatda turganda transkript qatori tahrirlandi (`transcript_rev` oshdi, avlod o'sha): hujjat hozirgi
    qatorlardan yoziladi va hozirgi versiya bilan belgilanadi - tayyor bo'lishi bilan "eskirgan" emas, til tugmasi uni
    bepul qayta yuboradi (yangi pullik hujjat va tahrirning tushib qolishi yo'q)."""
    user, mid, rt = ready
    minutes.generate(user, mid, "uz-cyrl")
    queued, _ = minutes.revise(user, mid, "uz-cyrl", {"text": "TITLE=Navbatda"})
    rt.store.execute("UPDATE meetings SET transcript_rev=transcript_rev+1 WHERE id=?", (mid,))
    drain(jobs)
    row = rt.store.minutes_row(mid, queued["id"])
    assert row["status"] == "ready" and int(row["transcript_rev"]) == int(rt.store.meeting_any(mid)["transcript_rev"])
    assert minutes.status(user, mid, queued["id"])["stale"] is False
    calls = len(_ops(rt))
    assert minutes.generate(user, mid, "uz-cyrl")["id"] == queued["id"] and len(_ops(rt)) == calls


def test_eski_prompt_versiyasi_joriy_hujjat_emas(ready):
    """`READY_VERSIONS` dan tashqari prompt versiyasidagi tayyor qator HEAD ham, tahrir asosi (BASE) ham, joriy til ham
    emas - "joriy hujjat" ta'riflari bir xil."""
    user, mid, rt = ready
    m = rt.store.meeting_any(mid)
    row_id = _donor_row(rt, mid, "uz-cyrl", int(m["transcript_rev"]), int(m["transcript_gen"]))
    rt.store.update_minutes(row_id, prompt_version="minutes-1")
    assert minutes.base_row(rt.store, m, "uz-cyrl") == (None, "minutes_missing")
    assert minutes.current_lang(rt.store, m) is None and minutes.latest(user, mid, "uz-cyrl") is None

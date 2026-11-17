"""`/api/v1/meetings` shartnomasi: eshik (bayroq/ruxsat), izolyatsiya, javob shakllari,
spikerlar, xulosalar, eksport, audio, vazifalar, savol-javob (spetsifikatsiya 3)."""

from __future__ import annotations

import pytest

from app.core import config as config_module
from app.core.config import settings
from meetings_fakes import create_meeting, enable, put_chunk, recorded, run_all

#: Asl funksiyalar - conftest ularni test davomida sozlama o'quvchisiga almashtiradi.
_REAL_ENABLED = config_module.meetings_enabled_now

MEETING_FIELDS = {"id", "clientId", "title", "titleSource", "status", "progress", "pollAfterSec", "language",
                  "detectedLanguage", "languageWarning", "template", "expectedSpeakers", "source", "recordedAt",
                  "durationSec", "createdAt", "updatedAt", "upload", "transcript", "speakers", "summaryStatus",
                  "primarySummaryId", "openActionItems", "audioAvailable", "error"}
CARD_FIELDS = {"id", "clientId", "title", "status", "progress", "recordedAt", "durationSec", "language",
               "template", "summaryStatus", "openActionItems", "overview", "error", "source", "origin", "listedAt"}
SPEAKER_FIELDS = {"id", "name", "suggestedName", "talkSec", "mergedInto"}
SEGMENT_FIELDS = {"id", "speaker", "start", "end", "text", "edited"}
SUMMARY_CARD_FIELDS = {"id", "template", "language", "status", "primary", "stale", "transcriptRev", "createdAt",
                       "finishedAt", "error"}
SUMMARY_FIELDS = SUMMARY_CARD_FIELDS | {"promptVersion", "model", "generatedBy", "layout", "speakers", "content"}
ACTION_FIELDS = {"id", "meetingId", "summaryItemId", "task", "owner", "due", "priority", "status", "origin",
                 "edited", "needsConfirmation", "sourceSegmentIds", "start", "quote", "createdAt", "updatedAt",
                 "crm"}
ASK_FIELDS = {"id", "question", "answer", "citations", "followUps", "createdAt"}
CONTENT_FIELDS = {"schemaVersion", "template", "language", "meeting", "title", "meetingType", "overview",
                  "purpose", "participants", "topics", "keyPoints", "decisions", "actionItems", "openQuestions",
                  "risks", "numbers", "dates", "nextSteps", "nextMeeting", "highlights", "userMarks", "keywords",
                  "sentiment", "templateSections", "followUpMessage", "followUps", "quality",
                  # Javob paytidagi ko'rinish belgisi (`compact`: har fakt bir marta) - bazada yo'q.
                  "view"}


@pytest.fixture
def ready(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(_isolated_meetings)
    return client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()


# --- eshik ----------------------------------------------------------------------------------


def test_bayroq_ochiq_404(client, auth):
    for method, path in (("get", "/api/v1/meetings/config"), ("get", "/api/v1/meetings"),
                         ("get", "/api/v1/meetings/action-items"), ("get", "/api/v1/meetings/" + "a" * 32),
                         ("post", "/api/v1/auth/devices")):
        response = getattr(client, method)(path, headers=auth)
        assert response.status_code == 404, path
        assert response.json()["code"] == "not_found"
    assert client.get("/api/v1/meetings/config").status_code == 401        # tokensiz - avval kim?


def test_bayroq_yoqiq_har_xodimga_ochiq(client, auth, user_auth, monkeypatch):
    """2026-11-16 (ega qarori): sinov ro'yxati yo'q - oddiy xodim ham ADMIN kabi kiradi,
    bloklangan hisob esa `current_user` da to'xtaydi."""
    enable(monkeypatch)
    assert client.get("/api/v1/meetings/config", headers=user_auth).status_code == 200    # oddiy xodim
    assert client.get("/api/v1/meetings", headers=user_auth).status_code == 200
    assert client.get("/api/v1/meetings/config", headers=auth).status_code == 200         # ADMIN
    assert client.get("/api/v1/meetings/config").status_code == 401
    assert client.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True}).status_code == 200
    assert client.get("/api/v1/meetings/config", headers=user_auth).status_code == 401


def test_bayroq_env_dan_jonli(tmp_path, monkeypatch):
    """Haqiqiy o'quvchi (`_REAL_*` - conftest yamog'idan oldin olingan): `.env` o'zgarsa
    restartsiz ko'rinadi; kalit yo'q bo'lsa sozlama obyekti (default `false`)."""
    env = tmp_path / ".env"
    monkeypatch.setattr(config_module, "_ENV_FILE", env)
    monkeypatch.delitem(config_module._token_cache, "meetings_enabled", raising=False)
    monkeypatch.setattr(settings, "meetings_enabled", False)
    env.write_text("OTHER=1\n")
    assert _REAL_ENABLED() is False
    env.write_text("MEETINGS_ENABLED=true\nMEETINGS_LOGINS=a.b, C.d\n")       # eski kalit - e'tiborsiz
    assert _REAL_ENABLED() is True
    env.write_text("MEETINGS_ENABLED=false\n")
    assert _REAL_ENABLED() is False
    config_module._token_cache.pop("meetings_enabled", None)


def test_config(client, auth, monkeypatch):
    enable(monkeypatch)
    body = client.get("/api/v1/meetings/config", headers={**auth, "Accept-Language": "ru-RU,ru;q=0.9"}).json()
    assert body["maxMinutes"] == 180 and body["maxUploadBytes"] == 157286400 and body["maxChunkBytes"] == 4194304
    assert body["acceptedContentTypes"] == ["audio/aac", "audio/mp4", "audio/mpeg", "audio/wav", "audio/ogg", "video/mp4"]
    assert body["maxVideoUploadBytes"] == 1024 * 1024 * 1024
    assert body["maxDistinctSpeakers"] == 4
    assert body["recording"] == {"format": "aac_adts", "sampleRate": 16000, "bitRate": 48000, "channels": 1,
                                 "audioSource": "voice_recognition"}
    general = next(t for t in body["templates"] if t["id"] == "general")
    assert general == {"id": "general", "title": "Общая встреча", "auto": True, "extraTab": False,
                       "description": general["description"]}
    follow = next(t for t in body["templates"] if t["id"] == "follow_up")
    assert follow["extraTab"] is True and follow["auto"] is False


# --- izolyatsiya ----------------------------------------------------------------------------


def test_boshqa_odam_404(client, auth, user_auth, monkeypatch, ready):
    enable(monkeypatch)
    mid = ready["id"]
    for method, path in (("get", f"/api/v1/meetings/{mid}"), ("get", f"/api/v1/meetings/{mid}/transcript"),
                         ("get", f"/api/v1/meetings/{mid}/summaries"), ("get", f"/api/v1/meetings/{mid}/audio"),
                         ("get", f"/api/v1/meetings/{mid}/action-items"), ("delete", f"/api/v1/meetings/{mid}"),
                         ("get", f"/api/v1/meetings/{mid}/upload"), ("get", f"/api/v1/meetings/{mid}/questions")):
        response = getattr(client, method)(path, headers=user_auth)
        assert response.status_code == 404, path
    assert put_chunk(client, user_auth, mid, 0, b"\xff\xf1abc").status_code == 404
    assert client.get("/api/v1/meetings", headers=user_auth).json()["total"] == 0
    assert client.get("/api/v1/meetings/action-items?status=all", headers=user_auth).json()["items"] == []
    assert client.get(f"/api/v1/meetings/{mid}", headers=auth).status_code == 200


# --- shakllar ------------------------------------------------------------------------------------


def test_javob_shakllari(client, auth, ready):
    mid = ready["id"]
    assert set(ready) == MEETING_FIELDS
    assert set(ready["upload"]) == {"receivedBytes", "totalBytes", "maxChunkBytes", "complete"}
    assert set(ready["transcript"]) == {"available", "engine", "speakersAvailable", "timing", "segmentCount",
                                        "transcriptRev"}
    assert ready["transcript"]["available"] is True and ready["recordedAt"] == "2026-10-09T06:00:00Z"
    assert set(ready["speakers"][0]) == SPEAKER_FIELDS
    listing = client.get("/api/v1/meetings", headers=auth).json()
    assert set(listing) == {"items", "limit", "offset", "total"} and set(listing["items"][0]) == CARD_FIELDS
    transcript = client.get(f"/api/v1/meetings/{mid}/transcript", headers=auth).json()
    assert set(transcript) == {"meetingId", "transcriptRev", "engine", "speakersAvailable", "timing", "language",
                               "detectedLanguage", "speakers", "segments"}
    assert set(transcript["segments"][0]) == SEGMENT_FIELDS
    cards = client.get(f"/api/v1/meetings/{mid}/summaries", headers=auth).json()["items"]
    assert set(cards[0]) == SUMMARY_CARD_FIELDS and cards[0]["primary"] is True
    summary = client.get(f"/api/v1/meetings/{mid}/summaries/{cards[0]['id']}", headers=auth).json()
    assert set(summary) == SUMMARY_FIELDS and set(summary["content"]) == CONTENT_FIELDS
    assert summary["layout"][0] == {"key": "overview", "title": "Qisqacha"}
    assert summary["promptVersion"] == "meeting-4" and summary["model"] == "gemma4:31b"
    items = client.get(f"/api/v1/meetings/{mid}/action-items", headers=auth).json()["items"]
    assert set(items[0]) == ACTION_FIELDS and items[0]["summaryItemId"] == "A1"
    assert set(items[0]["owner"]) == {"speaker", "name", "kind"} and set(items[0]["due"]) == {"date", "time", "raw"}


def test_royxat_qidiruv_va_status(client, auth, ready):
    assert client.get("/api/v1/meetings?q=HISOBOT", headers=auth).json()["total"] == 1
    assert client.get("/api/v1/meetings?q=yoq-narsa", headers=auth).json()["total"] == 0
    assert client.get("/api/v1/meetings?status=failed", headers=auth).json()["total"] == 0
    assert client.get("/api/v1/meetings?status=ready", headers=auth).json()["items"][0]["overview"]


def test_royxat_manba_filtri_va_tartib(client, auth, monkeypatch, _isolated_meetings):
    """Plaud (mobil 1.3.8): `origin` filtri va `sort=listed` - 1-oktabrdagi fayl bugun yuklansa ro'yxat
    tepasida (kelgan vaqti), ilovada yozilgani o'z kunida (`recordedAt`). Default tartib eski ilovalar uchun."""
    enable(monkeypatch)
    rec = create_meeting(client, auth, recordedAt="2026-10-09T06:00:00Z")                 # launcher - yozuv
    up = create_meeting(client, auth, source="share", recordedAt="2026-10-01T06:00:00Z")  # tayyor fayl
    created = client.get(f"/api/v1/meetings/{up['id']}", headers=auth).json()["createdAt"]

    only = client.get("/api/v1/meetings?origin=upload", headers=auth).json()
    assert only["total"] == 1 and [c["id"] for c in only["items"]] == [up["id"]]
    assert only["items"][0]["origin"] == "upload" and only["items"][0]["source"] == "share"
    assert [c["id"] for c in client.get("/api/v1/meetings?origin=recording", headers=auth).json()["items"]] == [rec["id"]]
    assert client.get("/api/v1/meetings?origin=slack", headers=auth).json()["total"] == 0

    old = client.get("/api/v1/meetings", headers=auth).json()["items"]
    assert [c["id"] for c in old] == [rec["id"], up["id"]]
    listed = client.get("/api/v1/meetings?sort=listed", headers=auth).json()["items"]
    assert [c["id"] for c in listed] == [up["id"], rec["id"]]
    assert listed[0]["listedAt"] == created and listed[0]["recordedAt"] == "2026-10-01T06:00:00Z"
    assert listed[1]["listedAt"] == listed[1]["recordedAt"] == "2026-10-09T06:00:00Z"

    for bad in ("origin=whatsapp", "sort=title"):
        assert client.get(f"/api/v1/meetings?{bad}", headers=auth).status_code == 422, bad


def test_sarlavha_va_shablon_ozgartirish(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    patched = client.patch(f"/api/v1/meetings/{mid}", headers=auth,
                           json={"title": "  Mening sarlavham ", "template": "minutes"}).json()
    assert patched["title"] == "Mening sarlavham" and patched["titleSource"] == "user"
    assert patched["template"] == "minutes"
    assert client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth,
                       json={"template": "minutes"}).status_code == 202
    run_all(_isolated_meetings)
    assert client.get(f"/api/v1/meetings/{mid}", headers=auth).json()["title"] == "Mening sarlavham"


# --- spikerlar va segmentlar ------------------------------------------------------------------------


def test_spiker_nomi_birlashtirish_va_segment(client, auth, ready):
    mid = ready["id"]
    renamed = client.patch(f"/api/v1/meetings/{mid}/speakers/S1", headers=auth, json={"name": "  Aziz  "}).json()
    assert renamed["speakers"][0]["name"] == "Aziz"
    rev = ready["transcript"]["transcriptRev"]
    assert client.get(f"/api/v1/meetings/{mid}", headers=auth).json()["transcript"]["transcriptRev"] == rev
    assert client.patch(f"/api/v1/meetings/{mid}/speakers/S9", headers=auth, json={"name": "x"}).status_code == 404

    merged = client.post(f"/api/v1/meetings/{mid}/speakers/merge", headers=auth,
                         json={"from": ["S3"], "into": "S1"}).json()
    assert merged["transcriptRev"] == rev + 1
    by_id = {s["id"]: s for s in merged["speakers"]}
    assert by_id["S3"]["mergedInto"] == "S1" and by_id["S3"]["talkSec"] == 0
    segs = client.get(f"/api/v1/meetings/{mid}/transcript", headers=auth).json()["segments"]
    assert "S3" not in {s["speaker"] for s in segs}
    card = client.get(f"/api/v1/meetings/{mid}/summaries", headers=auth).json()["items"][0]
    assert card["stale"] is True
    summary = client.get(f"/api/v1/meetings/{mid}/summaries/{card['id']}", headers=auth).json()
    assert "S3" not in str(summary["content"]["participants"])               # javob paytida S3 -> S1

    edited = client.patch(f"/api/v1/meetings/{mid}/segments/2", headers=auth,
                          json={"text": "Tuzatilgan matn", "speaker": "S1"}).json()
    assert edited["segment"] == {"id": 2, "speaker": "S1", "start": 6.5, "end": 14.0,
                                 "text": "Tuzatilgan matn", "edited": True}
    assert edited["transcriptRev"] == rev + 2
    bad = client.patch(f"/api/v1/meetings/{mid}/segments/2", headers=auth, json={"speaker": "S3"})
    assert bad.status_code == 404                                             # birlashtirilgan spiker


# --- xulosalar va eksport -----------------------------------------------------------------------------


def test_xulosa_idempotent_va_follow_up(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    same = client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth, json={"template": "auto"})
    assert same.status_code == 200 and same.json()["id"] == ready["primarySummaryId"]
    follow = client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth, json={"template": "follow_up"})
    assert follow.status_code == 202 and follow.json()["primary"] is False
    run_all(_isolated_meetings)
    full = client.get(f"/api/v1/meetings/{mid}/summaries/{follow.json()['id']}", headers=auth).json()
    assert full["status"] == "ready" and full["content"]["followUpMessage"]["body"]
    assert full["layout"][0]["key"] == "followUpMessage"
    assert client.get(f"/api/v1/meetings/{mid}", headers=auth).json()["primarySummaryId"] == ready["primarySummaryId"]
    deleted = client.delete(f"/api/v1/meetings/{mid}/summaries/{ready['primarySummaryId']}", headers=auth)
    assert deleted.json() == {"id": ready["primarySummaryId"], "status": "deleted"}
    after = client.get(f"/api/v1/meetings/{mid}", headers=auth).json()
    assert after["primarySummaryId"] is None and after["summaryStatus"] == "none"


def test_xulosa_chegarasi(client, auth, ready, monkeypatch):
    monkeypatch.setattr(settings, "meetings_summary_per_hour", 1)
    mid = ready["id"]
    assert client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth,
                       json={"template": "minutes"}).status_code == 202
    limited = client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth, json={"template": "brainstorm"})
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"


def test_eksportlar(client, auth, ready):
    mid = ready["id"]
    client.patch(f"/api/v1/meetings/{mid}/speakers/S1", headers=auth, json={"name": "Aziz"})
    sid = ready["primarySummaryId"]
    md = client.get(f"/api/v1/meetings/{mid}/summaries/{sid}/export?format=md", headers=auth)
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert 'attachment; filename="' in md.headers["content-disposition"]
    assert md.text.startswith("# Hisobot yig'ilishi\n9-oktabr, 11:00")
    assert "## Vazifalar" in md.text and "Aziz va 2-ishtirokchi" in md.text
    txt = client.get(f"/api/v1/meetings/{mid}/summaries/{sid}/export?format=txt", headers=auth)
    assert txt.headers["content-type"].startswith("text/plain") and "##" not in txt.text
    plain = client.get(f"/api/v1/meetings/{mid}/transcript/export?format=txt", headers=auth).text
    assert plain.splitlines()[0] == "[00:00:00] Aziz: Assalomu alaykum, bugun hisobot bo'yicha yig'ildik, boshlaymiz."
    bare = client.get(f"/api/v1/meetings/{mid}/transcript/export?format=txt&speakers=0&timestamps=0",
                      headers=auth).text
    assert bare.splitlines()[0].startswith("Assalomu")
    srt = client.get(f"/api/v1/meetings/{mid}/transcript/export?format=srt", headers=auth)
    assert srt.headers["content-type"].startswith("application/x-subrip")
    assert srt.text.startswith("1\n00:00:00,000 --> 00:00:06,000\nAziz: Assalomu")


# --- audio ---------------------------------------------------------------------------------------


def test_audio_m4a_va_range(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    full = client.get(f"/api/v1/meetings/{mid}/audio", headers=auth)
    assert full.status_code == 200 and full.headers["content-type"] == "audio/mp4"
    assert full.content[4:8] == b"ftyp" and "X-Audio-Seekable" not in full.headers
    part = client.get(f"/api/v1/meetings/{mid}/audio", headers={**auth, "Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    row = _isolated_meetings.store.meeting_any(mid)
    _isolated_meetings.store.update_meeting(mid, audio_deleted_at=1)
    gone = client.get(f"/api/v1/meetings/{mid}/audio", headers=auth)
    assert gone.status_code == 410 and gone.json()["code"] == "audio_expired"
    assert row["audio_path"]


def test_audio_remux_bolmasa_asl_fayl(client, auth, ready, monkeypatch):
    from app.services.meetings import audio as audio_mod

    def broken(src, dst):
        raise audio_mod.RemuxError("x")

    monkeypatch.setattr(audio_mod, "adts_to_m4a", broken)
    response = client.get(f"/api/v1/meetings/{ready['id']}/audio", headers=auth)
    assert response.status_code == 200 and response.headers["content-type"] == "audio/aac"
    assert response.headers["X-Audio-Seekable"] == "false"


def test_audio_yuklanmasdan_409(client, auth, monkeypatch):
    enable(monkeypatch)
    m = create_meeting(client, auth)
    response = client.get(f"/api/v1/meetings/{m['id']}/audio", headers=auth)
    assert response.status_code == 409 and response.json()["code"] == "not_ready"
    early = client.get(f"/api/v1/meetings/{m['id']}/transcript", headers=auth)
    assert early.status_code == 409 and early.json()["code"] == "not_ready"


# --- vazifalar va savol-javob ----------------------------------------------------------------------------


def test_vazifalar_va_umumiy_royxat(client, auth, ready):
    mid = ready["id"]
    added = client.post(f"/api/v1/meetings/{mid}/action-items", headers=auth,
                        json={"task": "Qo'ng'iroq qilish", "ownerSpeaker": "S2", "dueDate": "2026-10-12",
                              "dueTime": "09:30", "priority": "high"})
    assert added.status_code == 201
    item = added.json()
    assert item["origin"] == "user" and item["owner"] == {"speaker": "S2", "name": None, "kind": "person"}
    done = client.patch(f"/api/v1/meetings/{mid}/action-items/{item['id']}", headers=auth,
                        json={"status": "done"}).json()
    assert done["status"] == "done" and done["edited"] is False
    bad = client.post(f"/api/v1/meetings/{mid}/action-items", headers=auth, json={"task": "x", "dueDate": "ertaga"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_date"
    mine = client.get("/api/v1/meetings/action-items?status=open", headers=auth).json()["items"]
    assert mine and all(i["status"] == "open" for i in mine)
    assert mine[0]["meetingTitle"] == "Hisobot yig'ilishi" and mine[0]["recordedAt"] == "2026-10-09T06:00:00Z"
    everything = client.get("/api/v1/meetings/action-items?status=all", headers=auth).json()["items"]
    assert len(everything) == len(mine) + 1


def test_savol_javob_manbalar_bilan(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    response = client.post(f"/api/v1/meetings/{mid}/ask", headers=auth, json={"question": "Kim hisobot yuboradi?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ASK_FIELDS and body["followUps"] == ["Kim?", "Qachon?", "Nima?"]
    assert [c["segmentId"] for c in body["citations"]] == [1]          # mavjud bo'lmagan id tashlandi
    assert set(body["citations"][0]) == {"segmentId", "start", "speaker", "text"}
    ask_call = [c for c in _isolated_meetings.llm.calls if c["op"] == "meeting_ask"][0]
    assert "Kim hisobot yuboradi?" in ask_call["user"] and "<<<TRANSCRIPT-" in ask_call["user"]
    history = client.get(f"/api/v1/meetings/{mid}/questions", headers=auth).json()["items"]
    assert history[0]["id"] == body["id"]


def test_savol_xatolari(client, auth, ready, monkeypatch, _isolated_meetings):
    from app.services.integrations.ollama import OllamaError

    mid = ready["id"]
    _isolated_meetings.llm.script["meeting_ask"] = [OllamaError("Ollama HTTP 500", status=500)]
    failed = client.post(f"/api/v1/meetings/{mid}/ask", headers=auth, json={"question": "?"})
    assert failed.status_code == 503 and failed.json()["code"] == "llm_unavailable"
    monkeypatch.setattr(settings, "meetings_ask_per_hour", 1)
    from app.services.meetings import service

    service.reset_limits()
    assert client.post(f"/api/v1/meetings/{mid}/ask", headers=auth, json={"question": "a"}).status_code == 200
    limited = client.post(f"/api/v1/meetings/{mid}/ask", headers=auth, json={"question": "b"})
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"


# --- qayta urinish va qayta o'girish -----------------------------------------------------------------------


def test_qayta_ogirish(client, auth, ready, _isolated_meetings):
    mid = ready["id"]
    manual = client.post(f"/api/v1/meetings/{mid}/action-items", headers=auth, json={"task": "Qo'lda"}).json()
    need = client.post(f"/api/v1/meetings/{mid}/retranscribe", headers=auth, json={"language": "ru"})
    assert need.status_code == 400 and need.json()["code"] == "confirm_required"
    again = client.post(f"/api/v1/meetings/{mid}/retranscribe", headers=auth,
                        json={"language": "ru", "confirmCharge": True})
    assert again.status_code == 202 and again.json()["status"] == "uploaded"
    assert again.json()["transcript"]["available"] is False
    items = client.get(f"/api/v1/meetings/{mid}/action-items", headers=auth).json()["items"]
    assert [i["id"] for i in items] == [manual["id"]] and items[0]["sourceSegmentIds"] == []
    run_all(_isolated_meetings)
    detail = client.get(f"/api/v1/meetings/{mid}", headers=auth).json()
    assert detail["transcript"]["engine"] == "router"
    assert detail["transcript"]["transcriptRev"] == ready["transcript"]["transcriptRev"] + 1
    _isolated_meetings.store.update_meeting(mid, audio_deleted_at=1)
    expired = client.post(f"/api/v1/meetings/{mid}/retranscribe", headers=auth,
                          json={"language": "uz", "confirmCharge": True})
    assert expired.status_code == 410 and expired.json()["code"] == "audio_expired"


def test_qayta_urinish_mumkin_bolmasa_409(client, auth, ready):
    response = client.post(f"/api/v1/meetings/{ready['id']}/retry", headers=auth)
    assert response.status_code == 409 and response.json()["code"] == "not_retryable"


def test_sogliq_blokida_meetings(client, auth, ready):
    body = client.get("/api/health/detail", headers=auth).json()
    meetings = body["meetings"]
    assert meetings["enabled"] is True and meetings["counts"] == {"ready": 1}
    assert meetings["minutesToday"] > 0 and "Hisobot" not in str(meetings)
    assert "meeting_audio_sec" in body["stt"]["gapi_spend"]

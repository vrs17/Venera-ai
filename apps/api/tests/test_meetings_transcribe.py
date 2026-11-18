"""Transkripsiya bosqichi: normallashtirish, GAPI vazifasi, yiqilishdan tiklanish, Router (5.2-5.4)."""

from __future__ import annotations

import time

import pytest

from app.core.config import settings
from app.services.integrations.gapi_stt import MeetingTranscript
from app.services.meetings import dates, transcribe
from app.services.meetings.worker import Worker
from meetings_fakes import enable, gapi_error, recorded, run_all


def test_normallashtirish_tartib_bosh_matn_va_spiker_yorliqlari():
    result = MeetingTranscript(segments=[
        {"speaker": 5, "start": 10.004, "end": 12.0, "text": "ikkinchi"},
        {"speaker": 2, "start": 1.0, "end": 3.456, "text": "  birinchi\x07 gap "},
        {"speaker": 2, "start": 4.0, "end": 3.0, "text": "", "formatted_text": "formatlangan"},
        {"speaker": 7, "start": 5.0, "end": 6.0, "text": "   "},
        {"speaker": None, "start": 13.0, "end": 14.0, "raw_asr_text": "xom"},
    ], language={"code": "uz", "share": {"uz": 0.8, "ru": 0.2}})
    out = transcribe.normalize(result)
    segs = out["segments"]
    assert [s["id"] for s in segs] == [1, 2, 3, 4]
    assert [s["text"] for s in segs] == ["birinchi gap", "formatlangan", "ikkinchi", "xom"]
    assert [s["speaker"] for s in segs] == ["S1", "S1", "S2", None]      # paydo bo'lish tartibi
    assert segs[0]["end"] == 3.46 and segs[1]["end"] == segs[1]["start"] == 4.0
    assert segs[2]["start"] == 10.0
    assert out["speakers"][0] == {"id": "S1", "rawIndex": 2, "talkSec": 2.46}
    assert out["speakers"][1]["rawIndex"] == 5
    assert out["speakersAvailable"] is True and out["languageWarning"] is None


def test_diarizatsiya_xatosi_spikersiz():
    out = transcribe.normalize(MeetingTranscript(segments=[{"speaker": 0, "start": 0, "end": 1, "text": "a"}],
                                                 diarization_error=True))
    assert out["segments"][0]["speaker"] is None and out["speakers"] == []
    assert out["speakersAvailable"] is False


@pytest.mark.parametrize("raw,warning", [
    ("uz", None), ("ru", "mostly_other_language"),
    ({"code": "uz", "share": {"uz": 0.4, "ru": 0.6}}, "mostly_other_language"),
    ({"share": {"uz": 0.9}}, None), (None, None),
])
def test_til_ogohlantirishi(raw, warning):
    assert transcribe.language_warning(transcribe.detected_language(raw)) == warning


def test_router_jumla_vaqtlari():
    segs = transcribe.router_segments([(0.0, 10.0, "Bir. Ikki uch! To'rt?"), (10.0, 5.0, "Besh")])
    assert [s["text"] for s in segs] == ["Bir.", "Ikki uch!", "To'rt?", "Besh"]
    assert segs[0]["start"] == 0.0 and segs[2]["end"] == 10.0 and segs[3]["start"] == 10.0
    assert all(s["speaker"] is None for s in segs)
    assert segs[0]["end"] < segs[1]["end"] < segs[2]["end"]


def test_gapi_toliq_yol_va_sozlamalar(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth, expectedSpeakers=3)
    run_all(rt)
    sub = rt.gapi.submits[0]
    assert sub["settings"]["diarization"] is True and sub["settings"]["max_speakers"] == 3
    # Spikerni ovozidan tanish (ega qarori 2026-11-18) - standart yoqiq; emotion/pii baribir o'chiq.
    assert sub["settings"]["speaker_identification"] is True and sub["settings"]["emotion"] is False
    assert "enroll" not in sub["settings"]
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "ready" and detail["transcript"]["engine"] == "gapi"
    assert detail["transcript"]["timing"] == "exact" and detail["transcript"]["speakersAvailable"] is True
    assert detail["detectedLanguage"] == {"code": "uz", "share": {"uz": 0.9, "ru": 0.1}}
    assert rt.store.used_sec(dates.day_key(time.time()), 1) == 64.0
    assert rt.gapi.noted == 64.0


def test_yiqilishdan_keyin_qayta_yuborilmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.gapi.states = ["processing", "processing", "done"]
    w = Worker(rt)
    now = time.time()
    w.run_once(now)                                     # yuborildi, vazifa raqami diskda
    row = rt.store.meeting_any(meeting["id"])
    assert row["stt_job_id"] == "job-1" and row["status"] == "transcribing"
    # "Qayta ishga tushish": yangi ishchi, eski ijara muddati o'tgan.
    rt.store.execute("UPDATE meetings SET lease_owner='dead', lease_until=? WHERE id=?",
                     (int(now - 1), meeting["id"]))
    run_all(rt, now + 5)
    assert len(rt.gapi.submits) == 1
    assert rt.store.meeting_any(meeting["id"])["status"] == "ready"


def test_post_va_202_orasida_uzilish_royxatdan_tiklanadi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    now = time.time()
    rt.store.update_meeting(meeting["id"], status="transcribing", stt_submitted_at=int(now - 30), attempts=1)
    duration = rt.store.meeting_any(meeting["id"])["duration_sec"]
    rt.gapi.jobs_list = [{"id": "other", "created_at": now - 5000, "estimated_seconds": duration},
                         {"id": "job-77", "created_at": now - 20, "estimated_seconds": duration + 1}]
    Worker(rt).run_once(now)
    row = rt.store.meeting_any(meeting["id"])
    assert row["stt_job_id"] == "job-77" and rt.gapi.submits == []


def test_tiklanmasa_bir_marta_qayta_yuboriladi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    now = time.time()
    rt.store.update_meeting(meeting["id"], status="transcribing", stt_submitted_at=int(now - 30), attempts=1)
    Worker(rt).run_once(now)
    assert len(rt.gapi.submits) == 1
    rt.store.update_meeting(meeting["id"], status="transcribing", stt_job_id=None, stt_submitted_at=int(now),
                            attempts=2, next_attempt_at=None)
    Worker(rt).run_once(now + 1)
    row = rt.store.meeting_any(meeting["id"])
    assert len(rt.gapi.submits) == 1 and row["status"] == "failed" and row["error_code"] == "internal"


@pytest.mark.parametrize("error,where,code,status", [
    (gapi_error(404, "not_found"), "poll", "stt_job_lost", "failed"),
    (gapi_error(401, "unauthorized"), "submit", "stt_auth", "failed"),
    (gapi_error(422, "audio_unreadable"), "submit", "audio_unreadable", "failed"),
    (gapi_error(400, "invalid_audio"), "submit", "stt_rejected", "failed"),
    (gapi_error(429, "insufficient_balance", retryable=True), "submit", "quota_service", "waiting_quota"),
])
def test_gapi_xatolari(client, auth, monkeypatch, _isolated_meetings, error, where, code, status):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    if where == "submit":
        rt.gapi.submit_error = error
    else:
        rt.gapi.poll_error = error
    w = Worker(rt)
    now = time.time()
    w.run_once(now)
    w.run_once(now + 5)
    row = rt.store.meeting_any(meeting["id"])
    assert row["status"] == status and row["error_code"] == code
    if code == "stt_auth":
        assert rt.last_auth_failure is not None


def test_vaqtinchalik_xato_kutib_qayta(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.gapi.submit_error = gapi_error(503, "busy", retryable=True)
    now = time.time()
    Worker(rt).run_once(now)
    row = rt.store.meeting_any(meeting["id"])
    assert row["status"] == "transcribing" and row["retries"] == 1
    assert row["next_attempt_at"] == int(now + 30) and row["stt_submitted_at"] is None
    rt.gapi.submit_error = gapi_error(429, "rate_limited", retryable=True, retry_after=7)
    Worker(rt).run_once(now + 31)
    assert rt.store.meeting_any(meeting["id"])["next_attempt_at"] == int(now + 31 + 7)


def test_job_failed_va_natija_tayyor_emas(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.gapi.states = ["done"]
    rt.gapi.result_errors = [gapi_error(409, "result_not_ready", retryable=True)]
    w = Worker(rt)
    now = time.time()
    w.run_once(now)
    w.run_once(now + 3)
    assert rt.store.meeting_any(meeting["id"])["next_attempt_at"] == int(now + 3 + 2)
    run_all(rt, now + 10)
    assert rt.store.meeting_any(meeting["id"])["status"] == "ready"

    second, _ = recorded(client, auth)
    rt.gapi.states = ["failed"]
    run_all(rt, now + 100)
    assert rt.store.meeting_any(second["id"])["error_code"] == "stt_rejected"


def test_muddat_tugasa_stt_timeout_va_retry(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.gapi.states = ["processing"] * 5
    now = time.time()
    Worker(rt).run_once(now)
    Worker(rt).run_once(now + settings.meetings_stt_deadline + 10)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "failed" and detail["error"]["code"] == "stt_timeout"
    assert detail["error"]["retryable"] is True
    retried = client.post(f"/api/v1/meetings/{meeting['id']}/retry", headers=auth)
    assert retried.status_code == 202 and retried.json()["status"] == "uploaded"
    rt.gapi.states = ["done"]
    run_all(rt)
    assert len(rt.gapi.submits) == 1                         # o'sha vazifa, qayta to'lov yo'q
    assert rt.store.meeting_any(meeting["id"])["status"] == "ready"


def test_xizmat_kvotasi_va_balans_zahirasi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.store.add_usage(dates.day_key(time.time()), 99, settings.meetings_gapi_daily_minutes * 60)
    Worker(rt).run_once(time.time())
    row = rt.store.meeting_any(meeting["id"])
    assert row["status"] == "waiting_quota" and row["error_code"] == "quota_service"
    assert row["next_attempt_at"] == int(dates.next_reset(time.time()))

    other, _ = recorded(client, auth)
    rt.store.execute("DELETE FROM quota_days")
    rt.gapi.usage_payload = {"available_g": 61.0}
    now = time.time()
    Worker(rt).run_once(now)
    row = rt.store.meeting_any(other["id"])
    assert row["status"] == "waiting_quota" and row["next_attempt_at"] == int(now + 1800)
    assert rt.gapi.submits == []


def test_gapi_sozlanmagan(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    rt.gapi.configured = False
    meeting, _ = recorded(client, auth)
    run_all(rt)
    assert rt.store.meeting_any(meeting["id"])["error_code"] == "stt_not_configured"


def test_router_yoli_rus_tili(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    monkeypatch.setattr(transcribe, "ROUTER_PIECE_SEC", 20)
    meeting, _ = recorded(client, auth, seconds=50.0, language="ru")
    assert meeting["status"] == "uploaded"                      # Router bepul - kvota yo'q
    run_all(rt)
    assert len(rt.router.calls) == 3 and rt.router.calls[0]["language"] == "ru"
    assert rt.gapi.submits == []
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["transcript"]["engine"] == "router" and detail["transcript"]["timing"] == "approximate"
    assert detail["transcript"]["speakersAvailable"] is False and detail["languageWarning"] is None
    transcript = client.get(f"/api/v1/meetings/{meeting['id']}/transcript", headers=auth).json()
    assert transcript["segments"][0]["text"] == "Добрый день."
    assert all(s["speaker"] is None for s in transcript["segments"])
    assert transcript["segments"][-1]["end"] <= 50.5


def test_router_m4a_uzun_bolsa_xato(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth, language="en")
    rt.store.update_meeting(meeting["id"], content_type="audio/mp4", duration_sec=600.0)
    run_all(rt)
    assert rt.store.meeting_any(meeting["id"])["error_code"] == "router_too_long"

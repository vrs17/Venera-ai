"""GAPI klientining YIG'ILISH metodlari (asinxron vazifalar, spetsifikatsiya 5.1).

Transport soxta (`urllib.request.urlopen`) - `console.gapi.uz` chaqirilmaydi.
Chat diktovkasining sozlamalari (`_SETTINGS`) va `transcribe()` O'ZGARMAGANI
ham shu yerda qo'riqlanadi.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from app.services.integrations import gapi_stt
from app.services.integrations.gapi_stt import (GapiSttClient, _MEETING_SETTINGS, _SETTINGS, meeting_settings,
                                                parse_meeting_result)
from app.services.stt import SttError

BASE = "https://gapi.test/v1"
KEY = "gapi_abcdef123456_secretvalue"


class _Resp:
    def __init__(self, body: bytes, headers: dict | None = None, status: int = 200) -> None:
        self._body = body
        self.headers = headers or {}
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http(url: str, status: int, body: dict, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, status, "err", headers or {}, io.BytesIO(json.dumps(body).encode()))


class Transport:
    """Javoblar navbati: `(status, body, headers)`; so'rovlar yoziladi."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, request, timeout=None):
        data = request.data
        body = b""
        max_read = 0
        if data is not None and hasattr(data, "read"):
            while True:
                block = data.read(8192)
                if not block:
                    break
                body += block
            max_read = getattr(data, "max_read", 0)
        elif data is not None:
            body = data
        self.requests.append({"url": request.full_url, "method": request.get_method(),
                              "auth": request.get_header("Authorization"), "body": body,
                              "length": request.get_header("Content-length"), "max_read": max_read})
        status, payload, headers = self.replies.pop(0)
        if status >= 400:
            raise _http(request.full_url, status, payload, headers)
        return _Resp(json.dumps(payload).encode(), headers or {}, status)


@pytest.fixture
def client():
    return GapiSttClient(BASE, KEY, timeout=5, max_concurrent=1, attempts=1)


def test_yigilish_sozlamalari_aniq_kalitlar_va_biometrik_ochiq_emas():
    assert set(_MEETING_SETTINGS) == {"diarization", "max_speakers", "speaker_roles", "call_outcome",
                                      "stereo_channels_as_speakers", "speaker_identification", "gender",
                                      "language_detection", "word_timestamps", "emotion", "pii"}
    assert _MEETING_SETTINGS["diarization"] is True
    for key in ("emotion", "pii", "speaker_identification", "gender"):
        assert _MEETING_SETTINGS[key] is False
    assert meeting_settings(None)["max_speakers"] == 0
    assert meeting_settings(3)["max_speakers"] == 3
    assert meeting_settings(9)["max_speakers"] == 4         # GAPI 4 dan ko'p ajratmaydi
    assert meeting_settings(2) is not _MEETING_SETTINGS


def test_chat_sozlamalari_ozgarmagan():
    assert _SETTINGS == {"diarization": False, "emotion": False, "pii": False, "speaker_identification": False,
                         "gender": False}


def test_submit_oqim_bilan_fayl_butun_oqilmaydi(client, tmp_path, monkeypatch):
    audio = tmp_path / "m.aac"
    audio.write_bytes(b"\xff\xf1" + b"\x01" * (300 * 1024))
    transport = Transport([(202, {"id": "job-9", "state": "queued", "estimated_seconds": 61.5,
                                  "result_url": f"{BASE}/jobs/job-9/result"}, {})])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    job = client.submit_job(audio, "audio/aac", meeting_settings(2))
    assert job == {"id": "job-9", "state": "queued", "estimatedSeconds": 61.5,
                   "resultUrl": f"{BASE}/jobs/job-9/result"}
    req = transport.requests[0]
    assert req["url"] == f"{BASE}/jobs" and req["method"] == "POST"
    # Content-Length = bosh + fayl + oxir, va tana haqiqatan shuncha.
    assert int(req["length"]) == len(req["body"])
    assert audio.read_bytes() in req["body"]
    assert b'filename="meeting.aac"' in req["body"]
    settings_part = req["body"].split(b'name="settings"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0]
    assert json.loads(settings_part) == meeting_settings(2)
    # Fayl bo'laklab o'qildi (64 KB), butunligicha emas.
    assert 0 < req["max_read"] <= 64 * 1024 < audio.stat().st_size
    assert client.spend()["sent"] == 1


def test_vazifa_holatlari_va_natija(client, monkeypatch):
    payload = {"audio_seconds": 12.0, "segments": [{"speaker": 0, "start": 0, "end": 2, "text": "Salom"}],
               "language": "uz", "diarization_error": False}
    transport = Transport([(200, {"id": "job-1", "state": "processing", "progress_seconds": 3}, {}),
                           (200, {"id": "job-1", "state": "done"}, {}),
                           (200, payload, {})])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    assert client.get_job("job-1")["state"] == "processing"
    assert client.get_job("job-1")["state"] == "done"
    result = parse_meeting_result(client.get_result("job-1", f"{BASE}/jobs/job-1/result"))
    assert result.audio_seconds == 12.0 and len(result.segments) == 1
    assert transport.requests[2]["url"] == f"{BASE}/jobs/job-1/result"


def test_begona_result_url_ga_kalit_yuborilmaydi(client, monkeypatch):
    transport = Transport([(200, {"segments": []}, {})])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    client.get_result("job-5", "https://evil.example/steal")
    assert transport.requests[0]["url"] == f"{BASE}/jobs/job-5/result"


def test_409_result_not_ready_kodi_bilan(client, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", Transport([(409, {"error": "result_not_ready"}, {})]))
    with pytest.raises(SttError) as caught:
        client.get_result("job-1")
    assert caught.value.gapi_status == 409 and caught.value.gapi_code == "result_not_ready"
    assert caught.value.retryable


def test_429_retry_after_va_balans(client, tmp_path, monkeypatch):
    audio = tmp_path / "m.aac"
    audio.write_bytes(b"\xff\xf1" + b"\0" * 100)
    monkeypatch.setattr(urllib.request, "urlopen",
                        Transport([(429, {"error": "rate_limited"}, {"Retry-After": "17"}),
                                   (429, {"error": "insufficient_balance"}, {})]))
    with pytest.raises(SttError) as first:
        client.submit_job(audio, "audio/aac", meeting_settings())
    assert first.value.retry_after == 17.0 and first.value.gapi_code == "rate_limited"
    with pytest.raises(SttError) as second:
        client.submit_job(audio, "audio/aac", meeting_settings())
    assert second.value.gapi_code == "insufficient_balance"


def test_401_kalit_matnda_yoq(client, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", Transport([(401, {"error": "unauthorized",
                                                                     "hint": f"bad key {KEY}"}, {})]))
    with pytest.raises(SttError) as caught:
        client.get_job("job-1")
    assert caught.value.gapi_status == 401
    assert KEY not in str(caught.value)


def test_failed_va_cancelled_holatlari(client, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", Transport([(200, {"id": "j", "state": "failed"}, {}),
                                                              (200, {"id": "j", "state": "cancelled"}, {})]))
    assert client.get_job("j")["state"] == "failed"
    assert client.get_job("j")["state"] == "cancelled"


def test_list_cancel_usage(client, monkeypatch):
    transport = Transport([(200, {"jobs": [{"id": "a"}, {"id": "b"}]}, {}), (200, {}, {}),
                           (200, {"available_g": 312.5, "topup_target_g": 480}, {})])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    assert [j["id"] for j in client.list_jobs()] == ["a", "b"]
    assert client.cancel_job("a") is True
    assert client.usage()["available_g"] == 312.5
    assert transport.requests[0]["url"] == f"{BASE}/jobs?limit=20"
    assert transport.requests[1]["method"] == "DELETE"


def test_parse_meeting_result_shakllarga_chidamli():
    assert parse_meeting_result("bad").segments == []
    wrapped = parse_meeting_result({"result": {"segments": [{"text": "a"}], "audio_seconds": "3"}})
    assert wrapped.segments == [{"text": "a"}] and wrapped.audio_seconds == 3.0
    assert gapi_stt.MAX_MEETING_SPEAKERS == 4


# --- spikerni ovozidan tanish (2026-11-18): sozlamalar, namuna, loyiha ovozlari ---------------


def test_yigilish_tanish_yoqilsa_faqat_speaker_identification_ozgaradi():
    on = meeting_settings(3, identify=True)
    assert on["speaker_identification"] is True
    assert {k: v for k, v in on.items() if k != "speaker_identification"} == \
        {k: v for k, v in meeting_settings(3).items() if k != "speaker_identification"}
    assert "enroll" not in on                                 # GAPI standarti: yangi ovoz ro'yxatga olinadi
    assert meeting_settings(3)["speaker_identification"] is False
    assert _MEETING_SETTINGS["speaker_identification"] is False


def test_namuna_sozlamalari_kalitlari_yigilishniki_bilan_bir_xil():
    assert set(gapi_stt._SAMPLE_SETTINGS) == set(_MEETING_SETTINGS)
    assert gapi_stt._SAMPLE_SETTINGS["diarization"] is True
    assert gapi_stt._SAMPLE_SETTINGS["speaker_identification"] is True
    assert gapi_stt._SAMPLE_SETTINGS["emotion"] is False and gapi_stt._SAMPLE_SETTINGS["pii"] is False


def test_namuna_sinxron_transcribe_va_vazifa_raqami(client, monkeypatch):
    result = {"segments": [], "speech_seconds": 31.0, "audio_seconds": 40.0,
              "speaker_info": [{"index": 0, "speech_seconds": 31.0, "has_voiceprint": True,
                                "identity": {"status": "new", "voice_id": 100, "speaker_id": "sp-1"}}]}
    transport = Transport([(200, result, {"X-Job-Id": "job-77"})])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    payload, job = client.transcribe_sample(b"OggS" + b"\x00" * 100, "audio/ogg", account=1)
    assert job == "job-77" and payload["speech_seconds"] == 31.0
    req = transport.requests[0]
    assert req["url"] == f"{BASE}/transcribe" and req["method"] == "POST"
    assert b'"speaker_identification": true' in req["body"] and b'"diarization": true' in req["body"]
    assert b'filename="speech.ogg"' in req["body"]


def test_namuna_202_bolsa_kutiladi(client, monkeypatch):
    monkeypatch.setattr(gapi_stt, "_POLL_EVERY", 0.0)
    done = {"segments": [], "speaker_info": []}
    transport = Transport([(202, {"id": "job-5", "state": "queued"}, {}), (200, {"state": "done"}, {}),
                           (200, done, {})])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    payload, job = client.transcribe_sample(b"x" * 10, "audio/aac", account=1)
    assert job == "job-5" and payload == done
    assert transport.requests[2]["url"] == f"{BASE}/jobs/job-5/result"


def test_loyiha_ovozlari_api(client, monkeypatch):
    transport = Transport([
        (200, {"speakers": [{"id": "sp-1", "number": 100, "name": None, "kind": "candidate"}]}, {}),
        (201, {"id": "sp-2", "number": 101, "name": "barno-7"}, {}),
        (200, {"id": "sp-2", "name": "barno-8"}, {}),
        (202, {"ok": True}, {}),
        (200, {}, {}),
        (404, {"error": "speaker_not_found"}, {}),
    ])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    assert client.speakers()[0]["number"] == 100
    assert client.create_speaker("barno-7")["id"] == "sp-2"
    client.rename_speaker("sp-2", "barno-8")
    client.enroll_speaker("sp-2", "job-9", speaker_index=1)
    assert client.delete_speaker("sp-2") is True
    assert client.delete_speaker("sp-2") is True             # allaqachon yo'q - ham muvaffaqiyat
    methods = [(r["method"], r["url"].replace(BASE, "")) for r in transport.requests]
    assert methods == [("GET", "/speakers"), ("POST", "/speakers"), ("PATCH", "/speakers/sp-2"),
                       ("POST", "/speakers/sp-2/enroll"), ("DELETE", "/speakers/sp-2"), ("DELETE", "/speakers/sp-2")]
    assert json.loads(transport.requests[1]["body"]) == {"name": "barno-7"}
    assert json.loads(transport.requests[3]["body"]) == {"job_id": "job-9", "speaker_index": 1}
    assert all(r["auth"] == f"Bearer {KEY}" for r in transport.requests)


def test_natijada_speaker_info_va_voices_saqlanadi():
    result = parse_meeting_result({"segments": [], "speaker_info": [{"index": 0, "identity": {"status": "new"}}, "x"],
                                   "voices": [{"speaker": 0, "voice_id": 100}]})
    assert result.speaker_info == [{"index": 0, "identity": {"status": "new"}}]
    assert result.voices == [{"speaker": 0, "voice_id": 100}]
    assert parse_meeting_result({"segments": []}).speaker_info == []


def test_namuna_alohida_maydonda_va_faqat_solishtirish(client, monkeypatch):
    """`tenant` - alohida ovozlar maydoni ("faqat xodimlar"), `enroll: off` - faqat solishtirish (`voice.py`)."""
    transport = Transport([(200, {"segments": [], "speaker_info": []}, {"X-Job-Id": "j1"}),
                           (200, {"segments": [], "speaker_info": []}, {"X-Job-Id": "j2"})])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    client.transcribe_sample(b"x" * 10, "audio/aac", account=1, tenant="barno-staff", enroll="off")
    client.transcribe_sample(b"x" * 10, "audio/aac", account=1)
    assert b'"tenant": "barno-staff"' in transport.requests[0]["body"]
    assert b'"enroll": "off"' in transport.requests[0]["body"]
    assert b"tenant" not in transport.requests[1]["body"] and b"enroll" not in transport.requests[1]["body"]
    assert "tenant" not in gapi_stt._SAMPLE_SETTINGS                # umumiy sozlama o'zgarmaydi


def test_maydon_ovozlari_va_ovoz_parchasi(client, monkeypatch):
    transport = Transport([
        (200, {"speakers": [{"id": "st-1", "number": 100, "name": "barno-3"}]}, {}),
        (201, {"id": "st-2", "number": 101, "name": "barno-4", "tenant": "barno-staff"}, {}),
        (200, {"riff": "wav"}, {}),
        (404, {"error": "no_sample"}, {}),
    ])
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    assert client.speakers(tenant="barno-staff")[0]["name"] == "barno-3"
    assert client.create_speaker("barno-4", tenant="barno-staff")["id"] == "st-2"
    assert client.speaker_clip("sp 1") == json.dumps({"riff": "wav"}).encode()
    with pytest.raises(SttError) as err:
        client.speaker_clip("sp-2")
    assert err.value.gapi_status == 404 and err.value.gapi_code == "no_sample"
    urls = [(r["method"], r["url"].replace(BASE, "")) for r in transport.requests]
    assert urls == [("GET", "/speakers?tenant=barno-staff"), ("POST", "/speakers"),
                    ("GET", "/speakers/sp%201/sample"), ("GET", "/speakers/sp-2/sample")]
    assert json.loads(transport.requests[1]["body"]) == {"name": "barno-4", "tenant": "barno-staff"}

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
    assert _SETTINGS == {"diarization": False, "emotion": False, "pii": False}


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

"""Ikki GAPI kaliti (`GAPI_API_KEY`, `GAPI_API_KEY2`): birinchisining balansi tugasa ikkinchisi.

Klient - soxta transport bilan (`urllib.request.urlopen`), yig'ilish ishchisi esa
`meetings_fakes` bilan: pullik xizmatga hech narsa ketmaydi.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request

import pytest

from app.core.config import settings
from app.services.integrations import gapi_stt
from app.services.integrations.gapi_stt import GapiSttClient
from app.services.meetings.worker import Worker
from app.services.stt import SttError
from meetings_fakes import enable, recorded, run_all

BASE = "https://gapi.test/v1"
KEY1 = "gapi_birinchi_kalit_1111"
KEY2 = "gapi_ikkinchi_kalit_2222"
AUDIO = b"RIFF" + b"\0" * 400


class _Resp:
    def __init__(self, payload) -> None:
        self._raw = json.dumps(payload).encode()
        self.headers: dict = {}

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _error(path: str, status: int, body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(f"{BASE}{path}", status, "error", {}, io.BytesIO(json.dumps(body).encode()))


class Transport:
    """`urlopen` o'rnida. `empty` dagi kalitlar `429 insufficient_balance` oladi (javobda kalitning
    o'zi ham bor - xato matnida yashirilishini tekshirish uchun), `fail` - hamma kalitga."""

    def __init__(self) -> None:
        self.empty: set[str] = set()
        self.fail: tuple[int, dict] | None = None
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request, timeout=None):
        path = "/" + request.full_url.split("/v1/", 1)[1]
        key = (request.get_header("Authorization") or "").removeprefix("Bearer ")
        self.calls.append((path, key))
        if self.fail:
            raise _error(path, *self.fail)
        if key in self.empty:
            raise _error(path, 429, {"error": "insufficient_balance", "hint": f"balans 0: {key}"})
        if path == "/transcribe":
            return _Resp({"text": "Salom Barno", "audio_seconds": 1.4})
        if path == "/usage":
            return _Resp({"available_g": 480})
        if path == "/jobs":
            return _Resp({"id": "job-9", "state": "queued"})
        if path.startswith("/jobs?"):
            return _Resp({"jobs": []})
        if path.startswith("/jobs/"):
            return _Resp({"id": "job-9", "state": "done"})
        raise AssertionError(f"kutilmagan yo'l: {path}")

    def keys(self) -> list[str]:
        return [key for _, key in self.calls]


@pytest.fixture
def transport(monkeypatch):
    fake = Transport()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _client(**kwargs) -> GapiSttClient:
    return GapiSttClient(BASE, KEY1, api_key2=KEY2, timeout=5, deadline=30, attempts=2, **kwargs)


def test_birinchi_kalit_balansi_tugasa_ikkinchisi(transport):
    transport.empty = {KEY1}
    client = _client()

    assert client.transcribe(AUDIO, language="uz").text == "Salom Barno"
    # Balans tugagan kalitga qayta urinilmaydi (`attempts=2` bo'lsa ham) - darhol ikkinchisi.
    assert transport.keys() == [KEY1, KEY2]
    assert client.usable_accounts() == [2]
    assert client._empty[1] - time.time() <= gapi_stt._EMPTY_RECHECK_SEC

    client.transcribe(AUDIO, language="uz")
    assert transport.keys()[2:] == [KEY2]


def test_tekshirish_vaqti_kelsa_birinchi_kalit_yana_ishlatiladi(transport):
    transport.empty = {KEY1}
    client = _client()
    client.transcribe(AUDIO, language="uz")

    transport.empty = set()             # yarim kecha yoki to'ldirildi
    client._empty[1] = time.time() - 1  # chetlab o'tish muddati tugadi
    client.transcribe(AUDIO, language="uz")
    assert transport.keys()[-1] == KEY1 and client.usable_accounts() == [1, 2]


def test_boshqa_xatoda_ikkinchi_kalitga_otilmaydi(transport):
    transport.fail = (401, {"error": "unauthorized"})
    client = _client()

    with pytest.raises(SttError):
        client.transcribe(AUDIO, language="uz")
    assert transport.keys() == [KEY1] and client.usable_accounts() == [1, 2]


def test_ikkala_kalit_tugasa_zahira_uchun_xato_va_kalitlar_yashirin(transport):
    transport.empty = {KEY1, KEY2}
    client = _client()

    with pytest.raises(SttError) as first:
        client.transcribe(AUDIO, language="uz")
    assert gapi_stt.out_of_balance(first.value) and first.value.status == 429
    assert KEY1 not in str(first.value) and KEY2 not in str(first.value)

    # Ikkalasi ham "tugagan": keyingi so'rov tarmoqqa chiqmaydi (chat - darhol Router'ga).
    with pytest.raises(SttError) as second:
        client.transcribe(AUDIO, language="uz")
    assert gapi_stt.out_of_balance(second.value)
    assert transport.keys() == [KEY1, KEY2]


def test_faqat_ikkinchi_kalit_ham_ishlaydi(transport):
    only_second = GapiSttClient(BASE, "", api_key2=KEY2, timeout=5, deadline=30, attempts=1)
    assert only_second.configured and only_second.accounts == [2]
    only_second.transcribe(AUDIO, language="uz")
    assert transport.keys() == [KEY2]
    assert not GapiSttClient(BASE, "").configured


def test_yigilish_amallari_tanlangan_kalit_bilan(transport, tmp_path):
    audio = tmp_path / "a.aac"
    audio.write_bytes(b"\xff\xf1" + b"\0" * 100)
    client = _client()

    assert client.usage(account=2)["available_g"] == 480
    job = client.submit_job(audio, "audio/aac", {"diarization": True}, account=2)
    client.get_job(job["id"], account=2)
    client.get_result(job["id"], account=2)
    client.list_jobs(account=2)
    assert client.cancel_job(job["id"], account=2)
    assert set(transport.keys()) == {KEY2}


# --- yig'ilish ishchisi ---------------------------------------------------------


@pytest.fixture
def two_keys(client, auth, monkeypatch, _isolated_meetings):
    """Ikki kalitli soxta GAPI va bitta yozilgan yig'ilish (64 s = 2 daqiqa)."""
    rt = _isolated_meetings
    enable(monkeypatch)
    monkeypatch.setattr(settings, "meetings_gapi_reserve_minutes", 60, raising=False)
    monkeypatch.setattr(settings, "meetings_gapi_daily_minutes", 180, raising=False)
    rt.gapi.accounts = [1, 2]
    meeting, _ = recorded(client, auth)
    return rt, meeting


def _ops(rt, op: str) -> list[int]:
    return [account for name, account in rt.gapi.account_calls if name == op]


def test_yigilish_birinchi_kalitda_balans_yetmasa_ikkinchisida(two_keys):
    rt, meeting = two_keys
    rt.gapi.usage_by_account = {1: {"available_g": 30.0}, 2: {"available_g": 480.0}}
    run_all(rt)

    row = rt.store.meeting_any(meeting["id"])
    assert _ops(rt, "submit") == [2] and row["stt_account"] == 2
    assert set(_ops(rt, "job") + _ops(rt, "result")) == {2}
    assert int(row["transcript_rev"] or 0) >= 1


def test_yuborishda_balans_tugasa_navbatsiz_ikkinchi_kalitga(two_keys, client, auth):
    rt, meeting = two_keys
    rt.gapi.no_balance = {1}
    worker, now = Worker(rt), time.time()

    worker.run_once(now)
    row = rt.store.meeting_any(meeting["id"])
    assert row["status"] == "transcribing" and row["error_code"] is None
    assert row["next_attempt_at"] <= now + 2

    worker.run_once(now + 3)
    assert _ops(rt, "submit") == [1, 2]
    assert rt.store.meeting_any(meeting["id"])["stt_account"] == 2

    assert client.delete(f"/api/v1/meetings/{meeting['id']}", headers=auth).status_code == 200
    assert _ops(rt, "cancel") == [2]


def test_ikkala_kalitda_balans_tugasa_navbatda_kutadi(two_keys):
    rt, meeting = two_keys
    rt.gapi.no_balance = {1, 2}
    worker, now = Worker(rt), time.time()
    worker.run_once(now)
    worker.run_once(now + 3)

    row = rt.store.meeting_any(meeting["id"])
    assert _ops(rt, "submit") == [1, 2]
    assert row["status"] == "waiting_quota" and row["error_code"] == "quota_service"


def test_xizmat_ulushi_har_kalit_uchun(two_keys, monkeypatch):
    rt, meeting = two_keys
    monkeypatch.setattr(settings, "meetings_gapi_daily_minutes", 1, raising=False)
    rt.gapi.accounts = [1]
    worker, now = Worker(rt), time.time()

    worker.run_once(now)
    assert rt.store.meeting_any(meeting["id"])["error_code"] == "quota_service"   # 2 > 1

    rt.gapi.accounts = [1, 2]
    rt.store.update_meeting(meeting["id"], next_attempt_at=None)
    worker.run_once(now + 1)
    assert _ops(rt, "submit") == [1]                                               # 2 <= 1 x 2

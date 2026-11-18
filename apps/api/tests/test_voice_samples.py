"""Spikerni ovozidan tanish (ega qarori 2026-11-18, 1-bosqich - GAPI): ovoz namunasi va yig'ilishda tanish.

GAPI soxta (`FakeVoiceGapi`, `FakeGapiMeeting`) - tarmoqqa chiqilmaydi, balansdan pul yechilmaydi.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.integrations.gapi_stt import MeetingTranscript
from app.services.meetings import export, transcribe, voice
from meetings_fakes import enable, gapi_error, recorded, run_all

AUDIO = b"OggS" + b"\x00" * 2000


class FakeVoiceGapi:
    """`GapiSttClient` ning ovoz metodlari. `results[hisob]` - `transcribe_sample` javoblari navbati."""

    def __init__(self, accounts=(1, 2)) -> None:
        self.configured = True
        self.accounts = list(accounts)
        self.results: dict[int, list] = {a: [] for a in self.accounts}
        self.calls: list[tuple] = []
        self.created = 0

    def transcribe_sample(self, audio, content_type, *, account=1):
        self.calls.append(("transcribe", account, content_type))
        item = self.results[account].pop(0)
        if isinstance(item, Exception):
            raise item
        return item, f"job-{account}-{len(self.calls)}"

    def create_speaker(self, name, *, account=1):
        self.created += 1
        self.calls.append(("create", account, name))
        return {"id": f"new-{account}-{self.created}", "number": 200 + self.created, "name": name}

    def rename_speaker(self, speaker_id, name, *, account=1):
        self.calls.append(("rename", account, speaker_id, name))
        return {}

    def delete_speaker(self, speaker_id, *, account=1):
        self.calls.append(("delete", account, speaker_id))
        return True

    def enroll_speaker(self, speaker_id, job_id, *, speaker_index=None, segment_indexes=None, account=1):
        self.calls.append(("enroll", account, speaker_id, job_id, speaker_index))
        return {}

    def ops(self, name):
        return [c for c in self.calls if c[0] == name]


def result(status="new", voice_no=100, speaker_id="sp-a", speech=32.0, others=0.0, has=True, name=None):
    info = [{"index": 0, "speech_seconds": speech, "has_voiceprint": has,
             "identity": {"status": status, "voice_id": voice_no, "speaker_id": speaker_id, "name": name,
                          "score": 0.93}}]
    if others:
        info.append({"index": 1, "speech_seconds": others, "has_voiceprint": True, "identity": {"status": "unknown"}})
    return {"speech_seconds": speech + others, "audio_seconds": 45.0, "segments": [], "speaker_info": info}


class _Inline:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


@pytest.fixture
def fake(monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    gapi = FakeVoiceGapi()
    _isolated_meetings.voice_gapi = gapi
    monkeypatch.setattr(voice, "_pool", _Inline())
    return gapi


def post(client, auth, data=AUDIO, ctype="audio/ogg"):
    return client.post("/api/v1/voice-sample", content=data, headers={**auth, "Content-Type": ctype})


def person_of(rt, actor_id=1):
    return rt.store.row("SELECT * FROM voice_persons WHERE actor_id=?", (actor_id,))


# --- namuna -----------------------------------------------------------------------------


def test_holat_tartib_va_matn_bilan(client, auth, fake):
    body = client.get("/api/v1/voice-sample", headers=auth).json()
    assert body["enabled"] is True and body["enrolled"] is False and body["samples"] == 0
    assert body["instructions"]["text"] == voice.SAMPLE_TEXT
    assert len(body["instructions"]["steps"]) == 6 and body["instructions"]["recommendedSeconds"] == 45


def test_yangi_ovoz_ikkala_hisobga_yoziladi_va_taxallus_qoyiladi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    fake.results = {1: [result("new", 100, "sp-a")], 2: [result("new", 100, "sp-b")]}
    response = post(client, auth)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "ok" and response.json()["message"] == voice.OK_TEXT
    person = person_of(rt)
    assert person["kind"] == "employee" and person["name"] == "Administrator"
    links = rt.store.rows("SELECT * FROM voice_links ORDER BY account")
    assert [(link["account"], link["speaker_key"], link["voice_no"], link["named"]) for link in links] == \
        [(1, "sp-a", 100, 1), (2, "sp-b", 100, 1)]
    assert ("rename", 1, "sp-a", f"barno-{person['id']}") in fake.calls
    assert ("rename", 2, "sp-b", f"barno-{person['id']}") in fake.calls
    status = client.get("/api/v1/voice-sample", headers=auth).json()
    assert status["enrolled"] is True and status["samples"] == 1 and status["personId"] == person["id"]
    saved = Path(rt.store.row("SELECT path FROM voice_samples")["path"])
    assert saved.read_bytes() == AUDIO and saved.parent.name == "1" and oct(saved.stat().st_mode)[-3:] == "600"


@pytest.mark.parametrize("payload,reason", [
    (result(speech=8.0), "too_short"),
    (result(speech=30.0, others=10.0), "many_voices"),
    ({"speech_seconds": 40.0, "segments": [], "speaker_info": []}, "no_voiceprint"),
])
def test_yaroqsiz_namuna_rad_etiladi(client, auth, fake, _isolated_meetings, payload, reason):
    fake.results = {1: [payload], 2: []}
    body = post(client, auth).json()
    assert body["status"] == "rejected" and body["reason"] == reason
    assert body["message"] == voice.REASONS[reason]
    assert _isolated_meetings.store.rows("SELECT * FROM voice_links") == []
    assert fake.ops("transcribe") == [("transcribe", 1, "audio/ogg")]       # ikkinchi hisobga ketmaydi


def test_boshqa_xodimning_ovozi_rad_etiladi(client, auth, fake, _isolated_meetings):
    store = _isolated_meetings.store
    other = voice.employee_id(store, 2, "Demo Foydalanuvchi")
    store.execute("INSERT INTO voice_links (account, speaker_key, voice_no, person_id, named, created_at) "
                  "VALUES (1, 'sp-x', 300, ?, 1, 0)", (other,))
    fake.results = {1: [result("matched", 300, "sp-x")], 2: []}
    body = post(client, auth).json()
    assert body["status"] == "rejected" and body["reason"] == "voice_taken"
    assert store.row("SELECT person_id FROM voice_links WHERE speaker_key='sp-x'")["person_id"] == other


def test_yangi_ovoz_ochilsa_bor_ovozga_qoshiladi(client, auth, fake, _isolated_meetings):
    fake.accounts = [1]
    fake.results = {1: [result("new", 100, "sp-own"), result("new", 101, "sp-new")]}
    assert post(client, auth).json()["status"] == "ok"
    assert post(client, auth).json()["status"] == "ok"
    links = _isolated_meetings.store.rows("SELECT speaker_key FROM voice_links")
    assert [link["speaker_key"] for link in links] == ["sp-own"]
    assert ("enroll", 1, "sp-own", "job-1-4", 0) in fake.calls or any(
        c[0] == "enroll" and c[2] == "sp-own" for c in fake.calls)
    assert ("delete", 1, "sp-new") in fake.calls
    assert client.get("/api/v1/voice-sample", headers=auth).json()["samples"] == 2


def test_gapi_ovoz_ochmasa_ozimiz_yaratamiz(client, auth, fake, _isolated_meetings):
    fake.accounts = [1]
    payload = result(speech=30.0)
    payload["speaker_info"][0]["identity"] = {"status": "no_enrolled_voices"}
    fake.results = {1: [payload]}
    assert post(client, auth).json()["status"] == "ok"
    pid = person_of(_isolated_meetings)["id"]
    assert ("create", 1, f"barno-{pid}") in fake.calls
    assert any(c[0] == "enroll" and c[2] == "new-1-1" for c in fake.calls)
    link = _isolated_meetings.store.row("SELECT * FROM voice_links")
    assert link["speaker_key"] == "new-1-1" and link["named"] == 1 and link["voice_no"] == 201


def test_ikkinchi_hisob_xatosi_namunani_buzmaydi(client, auth, fake, _isolated_meetings):
    fake.results = {1: [result("new", 100, "sp-a")], 2: [gapi_error(429, "insufficient_balance", retryable=True)]}
    body = post(client, auth).json()
    assert body["status"] == "ok"
    assert [r["account"] for r in _isolated_meetings.store.rows("SELECT account FROM voice_links")] == [1]


def test_birinchi_hisobda_oqilmasa_unreadable(client, auth, fake):
    fake.results = {1: [gapi_error(422, "audio_unreadable")], 2: []}
    body = post(client, auth).json()
    assert body["status"] == "failed" and body["reason"] == "unreadable"


def test_katta_notogri_tur_va_band(client, auth, fake, monkeypatch, _isolated_meetings):
    monkeypatch.setattr(settings, "voice_sample_max_bytes", 1000, raising=False)
    assert post(client, auth, b"x" * 1001).status_code == 413
    assert post(client, auth, b"hello world", "text/plain").status_code == 415
    monkeypatch.setattr(settings, "voice_sample_max_bytes", 12 * 1024 * 1024, raising=False)
    store = _isolated_meetings.store
    import time as _t

    store.execute("INSERT INTO voice_samples (id, actor_id, channel, status, created_at) "
                  "VALUES ('busy1', 1, 'api', 'processing', ?)", (int(_t.time()),))
    response = post(client, auth)
    assert response.status_code == 409 and response.json()["code"] == "sample_busy"


def test_osilib_qolgan_namuna_uzilgan_deb_korinadi(client, auth, fake, _isolated_meetings):
    _isolated_meetings.store.execute("INSERT INTO voice_samples (id, actor_id, channel, status, created_at) "
                                     "VALUES ('old1', 1, 'api', 'processing', 100)")
    body = client.get("/api/v1/voice-sample/old1", headers=auth).json()
    assert body["status"] == "failed" and body["reason"] == "interrupted"
    assert client.get("/api/v1/voice-sample/old1", headers={"Authorization": "x"}).status_code == 401


def test_ochirish_gapi_va_fayllar(client, auth, fake, _isolated_meetings):
    store = _isolated_meetings.store
    fake.results = {1: [result("new", 100, "sp-a")], 2: [result("new", 100, "sp-b")]}
    post(client, auth)
    path = Path(store.row("SELECT path FROM voice_samples")["path"])
    body = client.delete("/api/v1/voice-sample", headers=auth).json()
    assert body["deleted"] == 2 and body["samples"] == 1 and body["message"] == voice.DELETED_TEXT
    assert ("delete", 1, "sp-a") in fake.calls and ("delete", 2, "sp-b") in fake.calls
    assert store.rows("SELECT * FROM voice_links") == [] and store.rows("SELECT * FROM voice_samples") == []
    assert not path.exists()
    assert client.get("/api/v1/voice-sample", headers=auth).json()["enrolled"] is False


def test_qamrov_faqat_admin(client, auth, user_auth, fake):
    fake.results = {1: [result("new", 100, "sp-a")], 2: [result("new", 100, "sp-b")]}
    post(client, auth)
    assert client.get("/api/v1/voice-sample/coverage", headers=user_auth).status_code == 403
    body = client.get("/api/v1/voice-sample/coverage", headers=auth).json()
    assert [e["name"] for e in body["enrolled"]] == ["Administrator"] and body["enrolled"][0]["voices"] == 2


def test_ochiq_bolim_404(client, auth, monkeypatch, _isolated_meetings):
    monkeypatch.setattr(settings, "meetings_enabled", False, raising=False)
    assert client.get("/api/v1/voice-sample", headers=auth).status_code == 404


def test_namuna_ochirilgan_bolsa_503(client, auth, fake, monkeypatch):
    monkeypatch.setattr(settings, "voice_samples_enabled", False, raising=False)
    assert post(client, auth).status_code == 503


# --- yig'ilishda tanish ------------------------------------------------------------------


SPEAKER_INFO = [
    {"index": 0, "speech_seconds": 20.0, "identity": {"status": "new", "voice_id": 105, "speaker_id": "sp-g"}},
    {"index": 1, "speech_seconds": 25.0, "identity": {"status": "new", "voice_id": 106, "speaker_id": "sp-h"}},
    {"index": 2, "speech_seconds": 9.0, "identity": {"status": "unknown", "score": 0.4}},
]


def _meeting(client, auth, rt):
    rt.gapi.result["speaker_info"] = [dict(s) for s in SPEAKER_INFO]
    meeting, _ = recorded(client, auth)
    run_all(rt)
    return meeting["id"]


def _speakers(client, auth, meeting_id):
    body = client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=auth).json()
    return {sp["id"]: sp for sp in body["speakers"]}


def test_normallashtirish_identity_ni_spikerga_ulaydi():
    out = transcribe.normalize(MeetingTranscript(
        segments=[{"speaker": 3, "start": 0, "end": 1, "text": "a"}, {"speaker": 1, "start": 2, "end": 3, "text": "b"}],
        speaker_info=[{"index": 1, "identity": {"status": "new", "voice_id": 7}},
                      {"index": 3, "identity": {"status": "matched", "voice_id": 9}}]))
    assert out["speakers"][0]["id"] == "S1" and out["speakers"][0]["identity"]["voice_id"] == 9
    assert out["speakers"][1]["identity"]["voice_id"] == 7
    assert "identity" not in transcribe.normalize(MeetingTranscript(
        segments=[{"speaker": 0, "start": 0, "end": 1, "text": "a"}]))["speakers"][0]


def test_mehmon_doimiy_raqam_oladi_ismi_yoq(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    first = _speakers(client, auth, _meeting(client, auth, rt))
    assert rt.gapi.submits[0]["settings"]["speaker_identification"] is True
    assert first["S1"]["personId"] and first["S1"]["name"] is None and first["S1"]["nameSource"] is None
    assert first["S2"]["personId"] and first["S2"]["personId"] != first["S1"]["personId"]
    assert first["S3"]["personId"] is None                                  # 10 s dan kam - raqamsiz
    # Ikkinchi yig'ilishda o'sha ovoz (GAPI: matched) - o'sha raqam.
    rt.gapi.states = ["processing", "done"]
    info = [dict(s) for s in SPEAKER_INFO]
    info[0] = {"index": 0, "identity": {"status": "matched", "voice_id": 105, "speaker_id": "sp-g", "score": 0.9}}
    rt.gapi.result["speaker_info"] = info
    meeting2, _ = recorded(client, auth)
    run_all(rt)
    second = _speakers(client, auth, meeting2["id"])
    assert second["S1"]["personId"] == first["S1"]["personId"] and second["S1"]["voiceScore"] == 0.9
    txt = client.get(f"/api/v1/meetings/{meeting2['id']}/transcript/export?format=txt", headers=auth).text
    assert f"Noma'lum #{first['S1']['personId']}" in txt and "3-ishtirokchi" in txt


def test_namuna_mehmonni_xodimga_aylantiradi_va_otgan_yigilish_ismlanadi(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    meeting_id = _meeting(client, auth, rt)
    guest = _speakers(client, auth, meeting_id)["S1"]["personId"]
    fake.accounts = [1]
    fake.results = {1: [result("matched", 105, "sp-g")]}
    assert post(client, auth).json()["status"] == "ok"
    pid = person_of(rt)["id"]
    after = _speakers(client, auth, meeting_id)
    assert after["S1"]["name"] == "Administrator" and after["S1"]["nameSource"] == "voice"
    assert after["S1"]["personId"] == pid and after["S2"]["name"] is None
    assert rt.store.row("SELECT * FROM voice_persons WHERE id=?", (guest,)) is None    # mehmon qatori birlashdi
    assert any(c[0] == "enroll" and c[2] == "sp-g" for c in fake.calls)              # namuna izi ham qo'shildi
    # Keyingi yig'ilishda shu ovoz - darhol ism bilan (xulosadan oldin).
    rt.gapi.states = ["processing", "done"]
    info = [dict(s) for s in SPEAKER_INFO]
    info[0] = {"index": 0, "identity": {"status": "matched", "voice_id": 105, "speaker_id": "sp-g"}}
    rt.gapi.result["speaker_info"] = info
    meeting2, _ = recorded(client, auth)
    run_all(rt)
    assert _speakers(client, auth, meeting2["id"])["S1"]["name"] == "Administrator"


def test_qolda_qoyilgan_ism_ovozdan_ustun(client, auth, fake, _isolated_meetings):
    rt = _isolated_meetings
    meeting_id = _meeting(client, auth, rt)
    renamed = client.patch(f"/api/v1/meetings/{meeting_id}/speakers/S1", json={"name": "Aziz aka"}, headers=auth)
    assert renamed.status_code == 200
    fake.accounts = [1]
    fake.results = {1: [result("matched", 105, "sp-g")]}
    post(client, auth)
    sp = _speakers(client, auth, meeting_id)["S1"]
    assert sp["name"] == "Aziz aka" and sp["nameSource"] == "manual"


def test_tanish_ochirilsa_avvalgidek(client, auth, fake, monkeypatch, _isolated_meetings):
    monkeypatch.setattr(settings, "meetings_speaker_id", False, raising=False)
    rt = _isolated_meetings
    speakers = _speakers(client, auth, _meeting(client, auth, rt))
    assert rt.gapi.submits[0]["settings"]["speaker_identification"] is False
    assert all(sp["personId"] is None for sp in speakers.values())


def test_speaker_name_raqamli_yorliq():
    people = {"S1": {"name": None, "person_id": 12}, "S2": {"name": "Ali"}, "S3": {"name": None}}
    assert export.speaker_name("S1", people, "uz") == "Noma'lum #12"
    assert export.speaker_name("S1", people, "ru") == "Неизвестный #12"
    assert export.speaker_name("S2", people, "uz") == "Ali"
    assert export.speaker_name("S3", people, "uz") == "3-ishtirokchi"
    assert voice.unknown_label(12, "en") == "Unknown #12"


def test_taxallusli_ovoz_bogsiz_bolsa_shaxsga_ulanadi(fake, _isolated_meetings):
    store = _isolated_meetings.store
    pid = voice.employee_id(store, 1, "Administrator")
    out = voice.identify(store, 2, [{"id": "S1", "rawIndex": 0, "talkSec": 3.0,
                                     "identity": {"status": "matched", "voice_id": 7, "speaker_id": "sp-z",
                                                  "name": f"barno-{pid}"}}])
    assert out[0]["personId"] == pid and out[0]["name"] == "Administrator" and "identity" not in out[0]
    assert store.row("SELECT person_id FROM voice_links WHERE account=2 AND speaker_key='sp-z'")["person_id"] == pid


def test_asosiy_hisob_balansi_tugasa_zaxira_asosiy_boladi(client, auth, fake, _isolated_meetings):
    fake.results = {1: [gapi_error(429, "insufficient_balance", retryable=True)], 2: [result("new", 100, "sp-b")]}
    body = post(client, auth).json()
    assert body["status"] == "ok"
    assert [(r["account"], r["speaker_key"]) for r in _isolated_meetings.store.rows("SELECT * FROM voice_links")] == \
        [(2, "sp-b")]


def test_ikkala_hisob_ishlamasa_xizmat_javob_bermadi(client, auth, fake):
    fake.results = {1: [gapi_error(503, "busy", retryable=True)], 2: [gapi_error(503, "busy", retryable=True)]}
    body = post(client, auth).json()
    assert body["status"] == "failed" and body["reason"] == "stt_unavailable"

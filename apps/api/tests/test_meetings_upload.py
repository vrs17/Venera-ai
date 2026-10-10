"""Yuklash protokoli: yaratish (idempotent), bo'laklar, davom ettirish, yakunlash (spetsifikatsiya 3.2, 2-5)."""

from __future__ import annotations

import time

from app.core.config import settings
from app.services.meetings import dates
from meetings_fakes import (adts_bytes, client_uuid, complete, create_meeting, enable, put_chunk, recorded,
                            sha, upload_all)


def test_yaratish_idempotent_va_default_sarlavha(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    cid = client_uuid()
    first = create_meeting(client, auth, clientId=cid)
    assert first["status"] == "uploading" and first["titleSource"] == "auto"
    assert first["title"] == "Yig'ilish 9-oktyabr, 11:00"            # Toshkent vaqti
    assert first["upload"] == {"receivedBytes": 0, "totalBytes": None, "maxChunkBytes": 4194304,
                               "complete": False}
    again = client.post("/api/v1/meetings", json={"clientId": cid, "recordedAt": "2026-10-09T06:00:00Z",
                                                   "contentType": "audio/aac"}, headers=auth)
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    ru = create_meeting(client, auth, language="ru")
    assert ru["title"] == "Встреча 9 октября, 11:00"
    row = _isolated_meetings.store.meeting_any(first["id"])
    assert row["channel"] == "mobile"


def test_yaratish_tekshiruvlari(client, auth, monkeypatch):
    enable(monkeypatch)
    base = {"clientId": client_uuid(), "recordedAt": "2026-10-09T06:00:00Z"}
    bad_type = client.post("/api/v1/meetings", json={**base, "contentType": "audio/ogg"}, headers=auth)
    assert bad_type.status_code == 415 and bad_type.json()["code"] == "unsupported_format"
    assert client.post("/api/v1/meetings", json={**base, "template": "follow_up"}, headers=auth).status_code == 422
    assert client.post("/api/v1/meetings", json={**base, "clientId": "x"}, headers=auth).status_code == 422
    assert client.post("/api/v1/meetings", json={**base, "language": "de"}, headers=auth).status_code == 422
    assert client.post("/api/v1/meetings", json={**base, "expectedSpeakers": 21}, headers=auth).status_code == 422


def test_yaratish_soatlik_chegara(client, auth, monkeypatch):
    enable(monkeypatch)
    for _ in range(30):
        create_meeting(client, auth)
    response = client.post("/api/v1/meetings", json={"clientId": client_uuid(),
                                                      "recordedAt": "2026-10-09T06:00:00Z"}, headers=auth)
    assert response.status_code == 429 and response.json()["code"] == "rate_limited"
    assert response.headers.get("Retry-After")


def test_bolaklar_takror_va_offset(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    m = create_meeting(client, auth)
    data = adts_bytes(20.0)
    a, b = data[:5000], data[5000:9000]
    assert put_chunk(client, auth, m["id"], 0, a).json() == {"receivedBytes": 5000}
    # Takroriy urinish (javob yetib bormagan) - 200, joy o'zgarmaydi.
    replay = put_chunk(client, auth, m["id"], 0, a)
    assert replay.status_code == 200 and replay.json() == {"receivedBytes": 5000}
    # Noto'g'ri joy - 409 va qayerdan davom etish.
    wrong = put_chunk(client, auth, m["id"], 7000, b)
    assert wrong.status_code == 409
    assert wrong.json()["code"] == "offset_mismatch" and wrong.json()["receivedBytes"] == 5000
    assert put_chunk(client, auth, m["id"], 5000, b).json() == {"receivedBytes": 9000}
    state = client.get(f"/api/v1/meetings/{m['id']}/upload", headers=auth).json()
    assert state == {"receivedBytes": 9000, "maxChunkBytes": 4194304, "complete": False}
    part = _isolated_meetings.store.upload_path(m["id"])
    assert part.read_bytes() == data[:9000]


def test_bolak_xatolari(client, auth, monkeypatch):
    enable(monkeypatch)
    m = create_meeting(client, auth)
    data = adts_bytes(5.0)
    bad_sha = client.put(f"/api/v1/meetings/{m['id']}/audio?offset=0", content=data,
                         headers={**auth, "X-Chunk-Sha256": "0" * 64})
    assert bad_sha.status_code == 400 and bad_sha.json()["code"] == "sha_mismatch"
    not_aac = put_chunk(client, auth, m["id"], 0, b"RIFF" + b"\0" * 100)
    assert not_aac.status_code == 415 and not_aac.json()["code"] == "unsupported_format"
    monkeypatch.setattr(settings, "meetings_chunk_bytes", 1024)
    big = put_chunk(client, auth, m["id"], 0, data[:2048])
    assert big.status_code == 413 and big.json()["code"] == "chunk_too_large"
    monkeypatch.setattr(settings, "meetings_chunk_bytes", 4 * 1024 * 1024)
    monkeypatch.setattr(settings, "meetings_max_upload_mb", 0)
    total = put_chunk(client, auth, m["id"], 0, data[:500])
    assert total.status_code == 413 and total.json()["code"] == "upload_too_large"


def test_mp4_birinchi_bolak_ftyp(client, auth, monkeypatch):
    enable(monkeypatch)
    m = create_meeting(client, auth, contentType="audio/mp4")
    assert put_chunk(client, auth, m["id"], 0, b"\xff\xf1" + b"\0" * 50).status_code == 415
    assert put_chunk(client, auth, m["id"], 0, b"\0\0\0\x18ftypM4A " + b"\0" * 50).status_code == 200


def test_yakunlash_toliq_emas_va_sha_qayta(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    m = create_meeting(client, auth)
    data = adts_bytes(15.0)
    put_chunk(client, auth, m["id"], 0, data[:4000])
    short = complete(client, auth, m["id"], data)
    assert short.status_code == 409 and short.json()["code"] == "upload_incomplete"
    assert short.json()["receivedBytes"] == 4000
    put_chunk(client, auth, m["id"], 4000, data[4000:])
    wrong = client.post(f"/api/v1/meetings/{m['id']}/complete",
                        json={"totalBytes": len(data), "sha256": "a" * 64}, headers=auth)
    assert wrong.status_code == 409 and wrong.json()["code"] == "sha_mismatch"
    assert wrong.json()["receivedBytes"] == 0
    assert _isolated_meetings.store.upload_path(m["id"]).stat().st_size == 0
    # Noldan qayta - endi o'tadi.
    upload_all(client, auth, m["id"], data)
    done = complete(client, auth, m["id"], data, marks=[{"t": 3.5, "note": "narx"}, {"t": 999, "note": None}])
    assert done.status_code == 202, done.text
    body = done.json()
    assert body["status"] == "uploaded" and body["upload"]["complete"] is True
    assert abs(body["durationSec"] - 15.0) < 0.1                    # server o'lchagan
    assert body["pollAfterSec"] == 3 and body["progress"] == 0.0
    row = _isolated_meetings.store.meeting_any(m["id"])
    assert row["audio_path"].endswith(f"/audio/1/{m['id']}.aac")
    assert not _isolated_meetings.store.upload_path(m["id"]).exists()
    # Takroriy yakunlash shu sha bilan - 200.
    assert complete(client, auth, m["id"], data).status_code == 200
    # Yopilgan yuklashga bo'lak - 409.
    closed = put_chunk(client, auth, m["id"], len(data), data[:100])
    assert closed.status_code == 409 and closed.json()["code"] == "upload_closed"


def test_juda_uzun_413_va_audio_saqlanadi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    monkeypatch.setattr(settings, "meetings_max_minutes", 0)
    m = create_meeting(client, auth)
    data = adts_bytes(40.0)
    upload_all(client, auth, m["id"], data)
    response = complete(client, auth, m["id"], data)
    assert response.status_code == 413 and response.json()["code"] == "too_long"
    detail = client.get(f"/api/v1/meetings/{m['id']}", headers=auth).json()
    assert detail["status"] == "failed" and detail["error"]["code"] == "too_long"
    assert detail["error"]["retryable"] is False and detail["audioAvailable"] is True


def test_qisqa_yozuv_davom_etadi_xulosa_skipped(client, auth, monkeypatch, _isolated_meetings):
    from meetings_fakes import run_all

    enable(monkeypatch)
    meeting, _ = recorded(client, auth, seconds=5.0)
    assert meeting["status"] == "uploaded"
    _isolated_meetings.gapi.result = {"audio_seconds": 5.0, "segments": [
        {"speaker": 0, "start": 0, "end": 4, "text": "Salom hammaga"}]}
    run_all(_isolated_meetings)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "ready" and detail["summaryStatus"] == "skipped"
    cards = client.get(f"/api/v1/meetings/{meeting['id']}/summaries", headers=auth).json()["items"]
    assert cards[0]["error"]["code"] == "too_short"


def test_kunlik_kvota_tugasa_navbatga(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    _isolated_meetings.store.add_usage(dates.day_key(time.time()), 1, 240 * 60)
    meeting, _ = recorded(client, auth, seconds=30.0)
    assert meeting["status"] == "waiting_quota"
    assert meeting["error"]["code"] == "quota_user" and meeting["error"]["retryable"] is True
    assert meeting["error"]["retryAt"] and meeting["pollAfterSec"] == 600
    assert meeting["upload"]["complete"] is True                     # rad etilmadi


def test_sha_ham_baytlar_ham_jurnalga_tushmaydi(client, auth, monkeypatch, caplog):
    enable(monkeypatch)
    m = create_meeting(client, auth)
    data = adts_bytes(3.0)
    with caplog.at_level("DEBUG"):
        put_chunk(client, auth, m["id"], 0, data)
    assert sha(data) not in caplog.text

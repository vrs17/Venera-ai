"""Ko'rib chiqish tuzatishlari: ijara (ikki ip), tiklash, kvota, band slot, 429, audio o'lchash,
qurilma sessiyasi eshigi va jonli tekshiruvning e2e aylanishi - hammasi soxtalar bilan, tarmoqsiz."""

from __future__ import annotations

import importlib.util
import json
import threading
import time

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.integrations.ollama import OllamaError
from app.services.meetings import audio, service, transcribe
from app.services.meetings.transcribe import LeaseLost
from app.services.meetings.worker import LEASE_SEC, Worker
from app.services.stt import SttError
from meetings_fakes import FakeRouter, adts_bytes, client_uuid, enable, rate_limited, recorded, run_all, sha

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _busy() -> SttError:
    err = SttError("ilova GAPI chegarasida (1 parallel)", status=503, retryable=True)
    err.local = True
    return err


# --- tiklash: begona vazifa olinmaydi -----------------------------------------------------


def _crashed_submit(client, auth, rt):
    meeting, _ = recorded(client, auth)
    now = time.time()
    rt.store.update_meeting(meeting["id"], status="transcribing", stt_engine="gapi",
                            stt_submitted_at=int(now - 30), attempts=1)
    return meeting, now, rt.store.meeting_any(meeting["id"])["duration_sec"]


def test_tiklash_estimated_seconds_siz_vazifani_olmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, now, _ = _crashed_submit(client, auth, rt)
    rt.gapi.jobs_list = [{"id": "job-of-user-B", "created_at": now - 20}]          # davomiylik yo'q
    Worker(rt).run_once(now)
    row = rt.store.meeting_any(meeting["id"])
    assert row["stt_job_id"] == "job-1" and len(rt.gapi.submits) == 1             # qayta yuborildi


def test_tiklash_boshqa_yigilishning_vazifasini_olmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    other, _ = recorded(client, auth)
    rt.store.update_meeting(other["id"], status="transcribing", stt_job_id="job-owned", stt_engine="gapi",
                            next_attempt_at=int(time.time() + 9999))
    meeting, now, duration = _crashed_submit(client, auth, rt)
    rt.gapi.jobs_list = [{"id": "job-owned", "created_at": now - 20, "estimated_seconds": duration}]
    Worker(rt).run_once(now)
    assert rt.store.meeting_any(meeting["id"])["stt_job_id"] != "job-owned"


def test_tiklash_ikki_nomzod_bolsa_olmaydi_bitta_bolsa_oladi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, now, duration = _crashed_submit(client, auth, rt)
    rt.gapi.jobs_list = [{"id": "a", "created_at": now - 20, "estimated_seconds": duration},
                         {"id": "b", "created_at": now - 25, "estimated_seconds": duration + 1}]
    Worker(rt).run_once(now)
    assert rt.store.meeting_any(meeting["id"])["stt_job_id"] not in ("a", "b")
    second, now2, duration2 = _crashed_submit(client, auth, rt)
    rt.gapi.jobs_list = [{"id": "solo", "created_at": now2 - 20, "estimated_seconds": duration2}]
    Worker(rt).run_once(now2)
    assert rt.store.meeting_any(second["id"])["stt_job_id"] == "solo"


# --- band slot - urinish emas -------------------------------------------------------------


def test_band_gapi_sloti_urinish_hisoblanmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.gapi.submit_error = _busy()
    now = time.time()
    for k in range(4):
        Worker(rt).run_once(now + 10 * k)
        row = rt.store.meeting_any(meeting["id"])
        assert row["status"] == "transcribing" and row["attempts"] == 0 and row["stt_submitted_at"] is None
        assert row["retries"] == 0 and row["next_attempt_at"] >= int(time.time()) + transcribe.LOCAL_BUSY_WAIT - 1
    rt.gapi.submit_error = None
    run_all(rt, now + 100)
    assert rt.store.meeting_any(meeting["id"])["status"] == "ready" and len(rt.gapi.submits) == 1


def test_band_router_va_model_navbati_urinish_emas(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)

    class BusyRouter(FakeRouter):
        def transcribe(self, data, **kw):
            raise _busy()

    rt.router = BusyRouter()
    meeting, _ = recorded(client, auth, language="ru")
    Worker(rt).run_once(time.time())
    row = rt.store.meeting_any(meeting["id"])
    assert row["status"] == "transcribing" and row["retries"] == 0

    rt.router = FakeRouter(" ".join(["Добрый день, коллеги. Я пришлю отчёт завтра до обеда, договорились."] * 6))
    rt.llm.script["meeting_extract"] = [OllamaError("navbat to'la")]
    run_all(rt, time.time(), rounds=2)
    row = rt.store.meeting_any(meeting["id"])
    summary = rt.store.summary(row["id"], row["primary_summary_id"])
    assert summary["status"] == "queued" and summary["attempts"] == 0
    run_all(rt, time.time() + 60)
    assert rt.store.meeting_any(meeting["id"])["summary_status"] == "ready"


# --- kvota: yo'ldagi vazifalar ham hisoblanadi --------------------------------------------


def test_kvota_yuborilgan_lekin_tugamagan_daqiqalarni_hisoblaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    rt.gapi.states = ["processing"] * 50
    ids = []
    for _ in range(4):
        meeting, _ = recorded(client, auth)
        rt.store.update_meeting(meeting["id"], duration_sec=170 * 60.0)             # 170 daqiqa
        ids.append(meeting["id"])
    now = time.time()
    Worker(rt).run_once(now)
    rows = [rt.store.meeting_any(i) for i in ids]
    assert len(rt.gapi.submits) == 1                         # 680 daq "yo'lda" EMAS - bittasi
    parked = [r for r in rows if r["status"] == "waiting_quota"]
    assert len(parked) == 3 and all(r["next_attempt_at"] <= int(now) + 601 for r in parked)
    assert rt.store.inflight_minutes(1) == 170 and rt.store.inflight_minutes(None) == 170


# --- ijara: ikki ip bitta yig'ilishni ishlamaydi -------------------------------------------


def test_ikki_ip_bitta_yigilishni_olmaydi_va_eskirgan_ip_yozmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    monkeypatch.setattr(transcribe, "ROUTER_PIECE_SEC", 20)
    entered, release = threading.Event(), threading.Event()
    calls = []

    class SlowRouter(FakeRouter):
        def transcribe(self, data, **kw):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                assert release.wait(10)
            return super().transcribe(data, **kw)

    rt.router = SlowRouter()
    meeting, _ = recorded(client, auth, seconds=50.0, language="ru")
    w = Worker(rt)
    first = w.claim("A", time.time())
    worker_a = threading.Thread(target=w.process, args=(first, time.time(), "A"))
    worker_a.start()
    assert entered.wait(10)
    # Ijara muddati "o'tdi" (uzoq bitta bo'lak) - lekin jarayon uni hali ishlayapti.
    rt.store.execute("UPDATE meetings SET lease_until=? WHERE id=?", (int(time.time() - 1), meeting["id"]))
    assert w.claim("B", time.time()) is None                         # ikkinchi ip olmaydi
    assert w.heartbeat_once() == 1                                    # yurak urishi ijarani uzaytiradi
    assert rt.store.meeting_any(meeting["id"])["lease_until"] >= int(time.time()) + LEASE_SEC - 5
    release.set()
    worker_a.join(10)
    row = rt.store.meeting_any(meeting["id"])
    assert row["transcript_rev"] == 1 and row["status"] == "summarizing"
    assert rt.store.scalar("SELECT COUNT(*) FROM summaries WHERE meeting_id=?", (meeting["id"],)) == 1


def test_ijara_boshqaga_otgan_bolsa_transkript_yozilmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth, language="ru")
    original = rt.router.transcribe

    def stolen(data, **kw):
        rt.store.execute("UPDATE meetings SET lease_owner='other' WHERE id=?", (meeting["id"],))
        return original(data, **kw)

    rt.router.transcribe = stolen
    m = rt.store.claim("A", time.time(), LEASE_SEC)
    with pytest.raises(LeaseLost):
        Worker(rt).transcriber.step(m, time.time(), "A")
    row = rt.store.meeting_any(meeting["id"])
    assert row["transcript_rev"] == 0 and row["status"] == "transcribing"
    assert rt.store.scalar("SELECT COUNT(*) FROM summaries", (), 0) == 0


# --- model 429 cheksiz emas, kutish vaqti ilovaga ------------------------------------------


def test_model_429_uchinchisida_xulosa_failed(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.llm.script["meeting_extract"] = [rate_limited() for _ in range(3)]
    now = time.time()
    run_all(rt, now, rounds=3)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "summarizing" and 250 <= detail["pollAfterSec"] <= 300   # 5 s emas
    for k in range(1, 4):
        Worker(rt).run_once(now + 2000 * k)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "ready" and detail["summaryStatus"] == "failed"
    cards = client.get(f"/api/v1/meetings/{meeting['id']}/summaries", headers=auth).json()["items"]
    assert cards[0]["error"]["code"] == "llm_failed"
    assert rt.llm.ops().count("meeting_extract") == 3


def test_xulosa_bosqichidan_tashqari_xato_issiq_aylanish_bermaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    from app.services.meetings import worker as worker_mod

    run_all(rt)
    # `apply_primary` - `_run_one` ning try blokidan TASHQARIDA: xato ishchiga chiqadi.
    monkeypatch.setattr(worker_mod, "apply_primary", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    rt.store.update_meeting(meeting["id"], status="summarizing", next_attempt_at=None)
    rt.store.execute("UPDATE summaries SET status='queued'")
    w = Worker(rt)
    assert w.run_once(time.time()) == 1                     # bir marta, keyin kutadi (issiq aylanish yo'q)
    assert rt.store.meeting_any(meeting["id"])["next_attempt_at"] >= int(time.time()) + 50


# --- yangi asosiy xulosa: odam belgilagan vazifa qoladi ------------------------------------


def test_belgilangan_ai_vazifasi_qayta_ochilmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(rt)
    mid = meeting["id"]
    item = client.get(f"/api/v1/meetings/{mid}/action-items", headers=auth).json()["items"][0]
    client.patch(f"/api/v1/meetings/{mid}/action-items/{item['id']}", headers=auth, json={"status": "done"})
    client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth, json={"template": "general", "force": True})
    run_all(rt)
    items = client.get(f"/api/v1/meetings/{mid}/action-items", headers=auth).json()["items"]
    same = [i for i in items if i["task"] == item["task"]]
    assert len(same) == 1 and same[0]["status"] == "done"


def test_asosiy_bolmay_qolgan_xulosa_vazifalarni_almashtirmaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(rt)
    from app.services.meetings.worker import apply_primary

    before = rt.store.action_items(meeting["id"])
    apply_primary(rt, rt.store.meeting_any(meeting["id"]), "boshqa-xulosa", "general",
                  {"actionItems": [{"id": "A1", "task": "Begona", "owner": {}, "due": {}}]}, time.time())
    assert rt.store.action_items(meeting["id"]) == before


# --- yuklash: parallel so'rovlar, kelajakdagi vaqt, audio o'lchash --------------------------


def test_parallel_complete_va_create(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, data = recorded(client, auth)
    stale = dict(rt.store.meeting_any(meeting["id"]), status="uploading")
    monkeypatch.setattr(service, "_owned", lambda actor, mid: stale)
    from app.schemas.meetings import CompleteRequest
    from app.schemas.auth import AuthUser

    user = AuthUser(actorId=1, email="admin@venera.uz", fullName="A", roles=["ADMIN"])
    body = CompleteRequest(totalBytes=len(data), sha256=sha(data), durationSec=60.0, marks=[])
    view, code = service.complete(user, meeting["id"], body)
    assert code == 200 and view["id"] == meeting["id"]                      # 409 emas

    monkeypatch.undo()
    enable(monkeypatch)
    cid = client_uuid()
    first = client.post("/api/v1/meetings", headers=auth, json={"clientId": cid, "recordedAt": "2026-10-09T06:00:00Z"})
    real = rt.store.by_client
    calls = []

    def racing(actor, client_id):
        calls.append(1)
        return None if len(calls) == 1 else real(actor, client_id)

    monkeypatch.setattr(rt.store, "by_client", racing)
    again = client.post("/api/v1/meetings", headers=auth, json={"clientId": cid, "recordedAt": "2026-10-09T06:00:00Z"})
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]


def test_kelajakdagi_recorded_at_server_vaqtiga_tushiriladi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    response = client.post("/api/v1/meetings", headers=auth, json={"clientId": client_uuid(),
                                                                    "recordedAt": "2099-01-01T00:00:00Z"})
    row = _isolated_meetings.store.meeting_any(response.json()["id"])
    assert row["recorded_at"] <= int(time.time()) + service.FUTURE_SKEW_SEC


def test_adts_ortasidagi_axlatdan_keyingi_audio_ham_olchanadi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    monkeypatch.setattr(settings, "meetings_max_minutes", 1)
    from meetings_fakes import complete, create_meeting, upload_all

    data = adts_bytes(20) + b"\x01\x02\x03" + adts_bytes(100)                  # 20 s + axlat + 100 s
    meeting = create_meeting(client, auth)
    upload_all(client, auth, meeting["id"], data, chunk=len(data))
    response = complete(client, auth, meeting["id"], data)
    assert response.status_code == 413 and response.json()["code"] == "too_long"


def test_adts_resync_va_mp4_haqiqiy_davomiylik(tmp_path):
    path = tmp_path / "a.aac"
    path.write_bytes(adts_bytes(20) + b"\xff\xf1junk" + adts_bytes(40) + audio.adts_frame(80)[:30])
    info = audio.adts_info(path)
    assert abs(info.durationSec - 60.0) < 0.2 and info.skippedBytes == 6
    m4a = tmp_path / "a.m4a"
    audio.adts_to_m4a(path, m4a)
    raw = bytearray(m4a.read_bytes())
    at = raw.find(b"mvhd")
    raw[at + 4 + 4 + 8 + 4:at + 4 + 4 + 8 + 8] = (5000).to_bytes(4, "big")    # sarlavhada 5 s
    m4a.write_bytes(bytes(raw))
    assert audio._mvhd_duration(m4a) == 5.0
    assert abs(audio.mp4_duration(m4a) - info.durationSec) < 0.1                # trek - haqiqiy 60 s


# --- qurilma sessiyasi: bayroq -----------------------------------------------------------


def test_qurilma_sessiyasi_bayroq_bilan(client, auth, users_file, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    login = client.post("/api/v1/auth/login", json={"username": "demo@venera.uz", "password": "demo2026"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    device = client.post("/api/v1/auth/devices", headers=headers,
                         json={"deviceName": "x", "platform": "android", "appVersion": "1"}).json()
    token = device["deviceToken"]
    assert client.post("/api/v1/auth/devices/session", json={"deviceToken": token}).status_code == 200
    monkeypatch.setattr(settings, "meetings_enabled", False)
    off = client.post("/api/v1/auth/devices/session", json={"deviceToken": token})
    assert off.status_code == 401 and off.json()["code"] == "invalid_device_token"
    monkeypatch.setattr(settings, "meetings_enabled", True)
    assert client.post("/api/v1/auth/devices/session", json={"deviceToken": token}).status_code == 200  # tirik


def test_qurilma_ombori_yoq_bolsa_sessiya_fayl_yaratmaydi(client, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    assert client.post("/api/v1/auth/devices/session", json={"deviceToken": "x" * 43}).status_code == 401
    assert client.post("/api/v1/auth/devices/revoke", json={"deviceToken": "x" * 43}).status_code == 200
    assert not settings.devices_db.exists()


# --- jonli tekshiruv: e2e aylanishi cheklangan ----------------------------------------------


def _live_check():
    spec = importlib.util.spec_from_file_location("meetings_live_check", TOOLS / "meetings_live_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _e2e_meeting(rt, tmp_path, live):
    src = tmp_path / "s.aac"
    src.write_bytes(adts_bytes(64))
    target = rt.store.audio_dir(0) / "e2e.aac"
    target.write_bytes(src.read_bytes())
    return live.insert_e2e_meeting(rt.store, audio_path=target, ctype="audio/aac", duration=64.0, language="uz",
                                   template="general", size=src.stat().st_size)


def test_live_check_e2e_tugaydi_va_cheksiz_chaqirmaydi(tmp_path, _isolated_meetings):
    rt = _isolated_meetings
    live = _live_check()
    mid = _e2e_meeting(rt, tmp_path, live)
    m = live.run_e2e(rt, mid, sleep=lambda s: None, say=lambda s: None)
    summary = rt.store.summary(mid, m["primary_summary_id"])
    assert m["status"] == "ready" and summary["status"] == "ready"
    assert rt.llm.ops().count("meeting_extract") == 1

    rt.llm.calls.clear()
    rt.llm.script["meeting_extract"] = [rate_limited() for _ in range(10)]
    mid2 = _e2e_meeting(rt, tmp_path, live)
    with pytest.raises(SystemExit):
        live.run_e2e(rt, mid2, sleep=lambda s: None, say=lambda s: None)          # 429: kutmaydi, to'xtaydi
    assert rt.llm.ops().count("meeting_extract") == 1

    # Ijara boshqaga o'tib qolsa (eski xato) - bir urinishdan keyin to'xtaydi, cheksiz emas.
    rt.llm.script.clear()
    rt.llm.calls.clear()
    mid3 = _e2e_meeting(rt, tmp_path, live)
    original = rt.store.renew
    rt.store.renew = lambda meeting_id, owner, until: False if meeting_id == mid3 else original(meeting_id, owner,
                                                                                                until)
    try:
        with pytest.raises(SystemExit):
            live.run_e2e(rt, mid3, sleep=lambda s: None, say=lambda s: None)
    finally:
        rt.store.renew = original
    assert len(rt.llm.calls) <= 2


def test_live_check_ollama_hisoboti_kalitsiz_ishlamaydi(monkeypatch, capsys):
    live = _live_check()
    with pytest.raises(SystemExit):
        live.main(["ollama"])                                           # --yes-spend siz - pul yo'q
    assert json.dumps(live.E2E_SUMMARY_ROUNDS)

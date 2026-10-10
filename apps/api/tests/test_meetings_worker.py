"""Fon ishchisi: ijara, kvota navbati, o'chirish, kesh, model xatolari, asosiy xulosa almashinuvi."""

from __future__ import annotations

import time

from app.core.config import settings
from app.services.integrations.ollama import OllamaError
from app.services.meetings import dates
from app.services.meetings.worker import LLM_RATE_BACKOFF, Worker
from meetings_fakes import enable, rate_limited, recorded, run_all


def _ready(client, auth, rt, monkeypatch, **create):
    enable(monkeypatch)
    meeting, _ = recorded(client, auth, **create)
    run_all(rt)
    return rt.store.meeting_any(meeting["id"])


def test_toliq_yol_holatlar_va_progress(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    w = Worker(rt)
    now = time.time()
    w.run_once(now)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "transcribing" and detail["pollAfterSec"] == 3
    w.run_once(now + 4)                                  # processing: 32/64 s -> 5 + 37.5
    assert client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()["progress"] == 42.5
    w.run_once(now + 8)                                  # done -> transkript, xulosa navbatda
    row = rt.store.meeting_any(meeting["id"])
    assert row["status"] in ("summarizing", "ready")
    run_all(rt, now + 20)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "ready" and detail["summaryStatus"] == "ready"
    assert detail["pollAfterSec"] is None and detail["progress"] is None
    assert detail["title"] == "Hisobot yig'ilishi"            # avtomatik sarlavha
    assert detail["openActionItems"] >= 1 and detail["transcript"]["segmentCount"] == 7
    assert "meeting_extract" in rt.llm.ops()


def test_kvota_00_05_gacha_kutadi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    now = time.time()
    rt.store.add_usage(dates.day_key(now), 1, settings.meetings_user_daily_minutes * 60)
    meeting, _ = recorded(client, auth)
    assert meeting["status"] == "waiting_quota"
    Worker(rt).run_once(now)
    assert rt.gapi.submits == []                          # muddat kelmagan - olinmaydi
    reset = dates.next_reset(now)
    run_all(rt, reset + 1)                               # yangi kun - kvota bo'sh
    assert len(rt.gapi.submits) == 1
    assert rt.store.meeting_any(meeting["id"])["status"] == "ready"


def test_ochirish_ish_paytida(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.gapi.states = ["processing"] * 10
    w = Worker(rt)
    w.run_once(time.time())
    row = rt.store.meeting_any(meeting["id"])
    assert row["stt_job_id"]
    response = client.delete(f"/api/v1/meetings/{meeting['id']}", headers=auth)
    assert response.json() == {"id": meeting["id"], "status": "deleted"}
    assert rt.gapi.cancelled == [row["stt_job_id"]]
    assert w.run_once(time.time() + 60) == 0
    assert not rt.store.meeting_any(meeting["id"])
    assert not list(rt.store.audio_dir(1).glob(f"{meeting['id']}*"))


def test_xulosa_paytida_ochirilsa_toxtaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    original = rt.llm.reply

    def delete_then_reply(op, system, user):
        rt.store.delete_meeting_rows(meeting["id"])
        return original(op, system, user)

    rt.llm.reply = delete_then_reply
    run_all(rt)
    assert rt.store.meeting_any(meeting["id"]) is None
    # 64 s - "qisqa qo'ng'iroq" qoidasi, tasniflovchisiz; birinchi chaqiruvdan keyin to'xtadi.
    assert rt.llm.ops() == ["meeting_extract"]


def test_model_xatosi_3_urinish_keyin_ready_failed(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.llm.script["meeting_extract"] = [OllamaError("Ollama HTTP 500", status=500) for _ in range(3)]
    now = time.time()
    run_all(rt, now, rounds=3)
    for k in range(1, 4):
        Worker(rt).run_once(now + 200 * k)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "ready" and detail["summaryStatus"] == "failed"
    cards = client.get(f"/api/v1/meetings/{meeting['id']}/summaries", headers=auth).json()["items"]
    assert cards[0]["error"]["code"] == "llm_failed"
    # Transkript baribir o'qiladi; qayta urinish xulosani navbatga qo'yadi.
    assert client.get(f"/api/v1/meetings/{meeting['id']}/transcript", headers=auth).status_code == 200
    retry = client.post(f"/api/v1/meetings/{meeting['id']}/retry", headers=auth)
    assert retry.status_code == 202 and retry.json()["status"] == "summarizing"
    run_all(rt, now + 2000)
    assert rt.store.meeting_any(meeting["id"])["summary_status"] == "ready"


def test_model_429_kutadi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    rt.llm.script["meeting_extract"] = [rate_limited()]
    now = time.time()
    run_all(rt, now, rounds=3)
    row = rt.store.meeting_any(meeting["id"])
    assert row["status"] == "summarizing" and row["summary_status"] == "queued"
    assert row["next_attempt_at"] >= int(now + LLM_RATE_BACKOFF[0]) - 60
    run_all(rt, row["next_attempt_at"] + 1)
    assert rt.store.meeting_any(meeting["id"])["status"] == "ready"


def test_model_sozlanmagan(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    rt.llm.configured = False
    row = _ready(client, auth, rt, monkeypatch)
    assert row["status"] == "ready" and row["summary_status"] == "failed"
    summary = rt.store.summary(row["id"], row["primary_summary_id"])
    assert summary["error_code"] == "llm_not_configured"


def test_ijara_otib_ketgan_xulosa_qayta_ishlanadi_kesh_bilan(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    monkeypatch.setattr(settings, "meetings_single_pass_chars", 200)
    monkeypatch.setattr(settings, "meetings_map_chars", 250)
    row = _ready(client, auth, rt, monkeypatch, template="general")
    maps_first = rt.llm.ops().count("meeting_map")
    assert maps_first >= 2 and rt.store.scalar("SELECT COUNT(*) FROM summary_parts") == maps_first
    # "Yiqilish": xulosa `running` holatda qolgan, ijara muddati o'tgan.
    rt.store.update_summary(row["primary_summary_id"], status="running", content_json=None)
    rt.store.update_meeting(row["id"], status="summarizing", summary_status="running", lease_owner="dead",
                            lease_until=int(time.time() - 1))
    rt.llm.calls.clear()
    run_all(rt)
    assert rt.llm.ops().count("meeting_map") == 0         # bo'laklar keshdan
    assert rt.store.meeting_any(row["id"])["status"] == "ready"


def test_yangi_asosiy_xulosa_tahrirlangan_vazifani_saqlaydi(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    row = _ready(client, auth, rt, monkeypatch)
    mid = row["id"]
    items = client.get(f"/api/v1/meetings/{mid}/action-items", headers=auth).json()["items"]
    ai = items[0]
    edited = client.patch(f"/api/v1/meetings/{mid}/action-items/{ai['id']}", headers=auth,
                          json={"task": "Tahrirlangan vazifa", "dueDate": "2026-10-20"}).json()
    assert edited["edited"] is True and edited["needsConfirmation"] is False
    manual = client.post(f"/api/v1/meetings/{mid}/action-items", headers=auth, json={"task": "Qo'lda"}).json()
    assert manual["origin"] == "user"
    created = client.post(f"/api/v1/meetings/{mid}/summaries", headers=auth,
                          json={"template": "minutes", "force": True})
    assert created.status_code == 202 and created.json()["primary"] is True
    run_all(rt)
    tasks = {i["task"]: i for i in client.get(f"/api/v1/meetings/{mid}/action-items", headers=auth).json()["items"]}
    assert "Tahrirlangan vazifa" in tasks and "Qo'lda" in tasks
    ai_items = [i for i in tasks.values() if i["origin"] == "ai" and not i["edited"]]
    assert len(ai_items) == 1                              # eski tahrirlanmagan AI vazifasi almashdi
    assert rt.store.meeting_any(mid)["template"] == "minutes"


def test_bayroq_ochiq_bolsa_navbat_ishlanmaydi_lekin_tozalash_ishlaydi(_isolated_meetings, monkeypatch):
    rt = _isolated_meetings
    w = Worker(rt)
    assert not w._active()                                  # ombor yo'q, bayroq o'chiq
    assert not (rt.store.root).exists()

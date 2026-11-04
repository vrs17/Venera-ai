"""Yig'ilishlar ombori: migratsiyalar, huquqlar, izolyatsiya, kaskad, tozalash (spetsifikatsiya 4)."""

from __future__ import annotations

import os
import sqlite3
import stat
import time

import pytest

from app.core.config import settings
from app.services import meetings
from app.services.meetings import store as store_mod
from app.services.meetings.store import MeetingStore, new_id
from app.services.meetings.worker import purge

DAY = 86400


def _meeting(st: MeetingStore, actor: int, **fields) -> dict:
    now = int(fields.pop("now", time.time()))
    row = {"id": new_id(), "actor_id": actor, "client_id": new_id(), "title": "t", "language": "uz",
           "template": "auto", "status": "ready", "summary_status": "none", "recorded_at": now,
           "created_at": now, "updated_at": now}
    row.update(fields)
    st.insert_meeting(row)
    return st.meeting_any(row["id"])


def test_migratsiya_noldan_va_qayta(tmp_path):
    st = MeetingStore(tmp_path / "m")
    assert st.version() == store_mod.SCHEMA_VERSION
    tables = {r["name"] for r in st.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meetings", "speakers", "segments", "summaries", "summary_parts", "action_items", "questions",
            "quota_days"} <= tables
    st.close_all()
    again = MeetingStore(tmp_path / "m")             # qayta ochish - qadam takrorlanmaydi
    assert again.version() == store_mod.SCHEMA_VERSION
    assert again.scalar("PRAGMA foreign_keys") == 1
    assert again.scalar("PRAGMA secure_delete") == 1
    again.close_all()


def test_huquqlar_700_600(tmp_path):
    st = MeetingStore(tmp_path / "m")
    st.connect()
    assert stat.S_IMODE(os.stat(tmp_path / "m").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(tmp_path / "m" / "uploads").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(st.db_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(st.audio_dir(7)).st_mode) == 0o700
    st.close_all()


def test_boshqa_odam_yigilishi_korinmaydi_va_kaskad(tmp_path):
    st = MeetingStore(tmp_path / "m")
    mine = _meeting(st, 1)
    st.replace_transcript(mine["id"], [{"id": 1, "start": 0.0, "end": 1.0, "speaker": "S1", "text": "salom"}],
                          [{"id": "S1", "rawIndex": 0, "talkSec": 1.0}], stt_engine="gapi")
    assert st.meeting(1, mine["id"]) is not None
    assert st.meeting(2, mine["id"]) is None
    rows, total = st.list_meetings(2, limit=10, offset=0)
    assert rows == [] and total == 0
    st.delete_meeting_rows(mine["id"])
    assert st.scalar("SELECT COUNT(*) FROM segments") == 0
    assert st.scalar("SELECT COUNT(*) FROM speakers") == 0
    st.close_all()


def test_qidiruv_apostrof_va_registrga_qaramaydi(tmp_path):
    st = MeetingStore(tmp_path / "m")
    _meeting(st, 1, title="Oʻzbek tili yig'ilishi")
    _meeting(st, 1, title="Boshqa", overview="Narx bo'yicha QAROR")
    assert st.list_meetings(1, limit=10, offset=0, q="o'zbek")[1] == 1
    assert st.list_meetings(1, limit=10, offset=0, q="ozbek")[1] == 1
    assert st.list_meetings(1, limit=10, offset=0, q="qaror")[1] == 1
    assert st.list_meetings(1, limit=10, offset=0, q="%")[1] == 0
    st.close_all()


def test_ijara_bitta_ishchiga(tmp_path):
    st = MeetingStore(tmp_path / "m")
    m = _meeting(st, 1, status="uploaded")
    now = time.time()
    first = st.claim("a", now, 300)
    assert first["id"] == m["id"]
    assert st.claim("b", now, 300) is None                 # ijara band
    assert st.claim("b", now + 301, 300)["id"] == m["id"]  # muddati o'tdi - boshqaga
    assert not st.renew(m["id"], "a", now + 600)
    st.close_all()


def test_tozalash(tmp_path, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    st = rt.store
    now = time.time()
    audio_dir = st.audio_dir(1)

    def with_audio(name: str, **fields):
        path = audio_dir / f"{name}.aac"
        path.write_bytes(b"x")
        (audio_dir / f"{name}.m4a").write_bytes(b"y")
        return _meeting(st, 1, audio_path=str(path), **fields), path

    old_audio, old_path = with_audio("old", recorded_at=int(now - 31 * DAY), created_at=int(now - 31 * DAY))
    fresh, fresh_path = with_audio("fresh", recorded_at=int(now - DAY))
    too_long, long_path = with_audio("long", status="failed", error_code="too_long",
                                     completed_at=int(now - 2 * DAY), recorded_at=int(now - 2 * DAY))
    ancient = _meeting(st, 1, recorded_at=int(now - 200 * DAY), created_at=int(now - 200 * DAY))
    # Telefon soati noto'g'ri / oflayn navbat: yozuv "200 kun oldin", serverga BUGUN keldi -
    # audio ham, yig'ilish ham darhol o'chmaydi.
    late, late_path = with_audio("late", recorded_at=int(now - 200 * DAY))
    # Hali ishlanayotgan yozuvning audiosi tegilmaydi (o'girish uchun kerak).
    busy, busy_path = with_audio("busy", status="transcribing", recorded_at=int(now - 40 * DAY),
                                 created_at=int(now - 40 * DAY))
    upload = _meeting(st, 1, status="uploading", updated_at=int(now - 73 * 3600))
    st.prepare()
    st.upload_path(upload["id"]).write_bytes(b"part")
    live_upload = _meeting(st, 1, status="uploading")

    counts = purge(rt, now)
    assert counts["audio"] >= 1 and counts["tooLong"] == 1 and counts["meetings"] == 1 and counts["uploads"] == 1
    assert not old_path.exists() and not (audio_dir / "old.m4a").exists()
    assert st.meeting_any(old_audio["id"])["audio_deleted_at"] is not None
    assert st.meeting_any(old_audio["id"])["title"] == "t"          # matn qoladi
    assert fresh_path.exists()
    assert not long_path.exists()
    assert st.meeting_any(ancient["id"]) is None
    assert st.meeting_any(upload["id"]) is None and not st.upload_path(upload["id"]).exists()
    assert st.meeting_any(live_upload["id"]) is not None
    assert late_path.exists() and st.meeting_any(late["id"]) is not None
    assert busy_path.exists() and st.meeting_any(busy["id"])["audio_deleted_at"] is None

    monkeypatch.setattr(settings, "meetings_retention_days", 0)
    keep = _meeting(st, 1, recorded_at=int(now - 400 * DAY))
    purge(rt, now)
    assert st.meeting_any(keep["id"]) is not None                     # 0 - saqlanadi

    monkeypatch.setattr(settings, "meetings_audio_days", 0)
    keep_audio, keep_path = with_audio("keep", recorded_at=int(now - 400 * DAY), created_at=int(now - 400 * DAY))
    assert purge(rt, now)["audio"] == 0
    assert keep_path.exists() and st.meeting_any(keep_audio["id"])["audio_deleted_at"] is None   # 0 - audio qoladi


def test_ombor_yoq_bolsa_holat_hech_narsa_yaratmaydi(tmp_path, _isolated_meetings):
    assert not _isolated_meetings.store.exists
    state = meetings.status()
    assert state["counts"] == {} and not (tmp_path / "meetings").exists()


def test_kvota_odam_va_xizmat(tmp_path):
    st = MeetingStore(tmp_path / "m")
    st.add_usage("2026-10-09", 5, 120.0)
    st.add_usage("2026-10-09", 6, 60.0)
    assert st.used_sec("2026-10-09", 5) == 120.0
    assert st.used_sec("2026-10-09", 0) == 180.0                       # xizmat jami
    st.close_all()


def test_sqlite_fk_buzilsa_xato(tmp_path):
    st = MeetingStore(tmp_path / "m")
    with pytest.raises(sqlite3.IntegrityError):
        st.execute("INSERT INTO segments (meeting_id, id, start, \"end\", text) VALUES ('nope', 1, 0, 1, 'x')")
    st.close_all()


def test_migratsiya_v1_dan_v2_ga_malumot_bilan(tmp_path):
    """Ishlab turgan v1 ombori (ma'lumoti bilan) v2 ga o'tadi: faqat ustun qo'shiladi, eski
    qatorlar joyida, yangi ustunlar bo'sh - eski xulosa `generatedBy` siz (Ollama deb) o'qiladi."""
    root = tmp_path / "m"
    root.mkdir()
    conn = sqlite3.connect(root / "meetings.db")
    for statement in store_mod.MIGRATIONS[0]:
        conn.execute(statement)
    now = int(time.time())
    conn.execute("INSERT INTO meetings (id, actor_id, client_id, created_at, updated_at, status) "
                 "VALUES ('m1', 7, 'c1', ?, ?, 'ready')", (now, now))
    conn.execute("INSERT INTO summaries (id, meeting_id, template, language, prompt_version, transcript_rev, status, "
                 "model, content_json, created_at) VALUES ('s1', 'm1', 'general', 'uz', 'p1', 1, 'ready', "
                 "'gemma4:31b', '{}', ?)", (now,))
    conn.execute("INSERT INTO action_items (id, meeting_id, task, created_at, updated_at) "
                 "VALUES ('a1', 'm1', 'Hisobot yuborish', ?, ?)", (now, now))
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    st = MeetingStore(root)
    assert st.version() == store_mod.SCHEMA_VERSION == 4
    # v4: eski yozuvning GAPI hisobi bo'sh - ya'ni birinchi kalit (`GAPI_API_KEY`).
    assert st.rows("SELECT stt_account FROM meetings WHERE id='m1'")[0]["stt_account"] is None
    summary = st.summary("m1", "s1")
    assert summary["model"] == "gemma4:31b" and summary["provider"] is None
    item = st.action_item("m1", "a1")
    assert item["task"] == "Hisobot yuborish" and item["crm_token"] is None and item["crm_status"] is None
    indexes = {r["name"] for r in st.rows("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "action_items_crm" in indexes
    # Bajarilgan CRM holati 404/410 dan keyin `expired` ga TUSHMAYDI.
    st.update_action_item("a1", crm_token="tok", crm_status="executed")
    assert st.set_crm_status(7, "tok", "expired") == 0
    assert st.action_item("m1", "a1")["crm_status"] == "executed"
    st.close_all()

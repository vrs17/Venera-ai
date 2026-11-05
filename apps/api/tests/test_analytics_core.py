"""Analitika yadrosi: ombor sxemasi, yozuvchi ip, savol izi, chaqiruvlar hisobi,
kanal.

Hammasi OFLAYN va har test O'Z vaqtinchalik faylida (`reset_for_tests`):
jonli `data/analytics/venera.db` ga hech narsa tegmaydi. Yuqoridagi xizmat
chaqirilmaydi - kadrlar qo'lda yasaladi, aynan `chat.py` uzatadigan
ko'rinishda (bayt, `\\n` bilan).
"""

from __future__ import annotations

import contextvars
import gc
import json
import os
import sqlite3
import threading
import time

from concurrent.futures import ThreadPoolExecutor

import anyio
import pytest
from starlette.concurrency import iterate_in_threadpool
from starlette.requests import Request

from app.core.channels import CHANNELS, channel_of, normalize
from app.schemas.auth import AuthUser
from app.services import analytics
from app.services.analytics import db as db_module
from app.services.analytics import writer as writer_module
from app.services.analytics.db import SCHEMA_VERSION, Database, _migrate
from app.services.analytics.meter import (
    begin, bind, carry, current, http_status_of, metered, record_auth_event, record_call, redact,
)
from app.services.analytics.recorder import (
    ANSWER_CAP, PAYLOAD_CAP, QUESTION_CAP, RAW_CAP, SNIPPET_CAP, TurnRecorder,
    set_proposal_status, valid_turn_id,
)
from app.services.analytics.writer import Writer, _group, purge

USER = AuthUser(actorId=42, email="Y.Mamajonov@Brb.uz", fullName="Yusuf Mamajonov",
                roles=["USER"])

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


@pytest.fixture(autouse=True)
def adb(tmp_path):
    """Har test uchun yangi ombor va yangi yozuvchi."""
    database = analytics.reset_for_tests(tmp_path / "analytics" / "venera.db")
    yield database
    analytics.shutdown()
    database.close_all()


def _line(frame: dict) -> bytes:
    return json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n"


def _turn(adb: Database, turn_id: str) -> dict:
    assert analytics.flush()
    row = adb.row("SELECT * FROM turns WHERE id = ?", (turn_id,))
    assert row is not None
    return row


# ================================================================ ombor sxemasi


SPEC_TABLES = {"turns", "turn_events", "turn_sources", "api_calls", "auth_events", "reports",
               "user_admin", "audit_log",
               # Sxema v3 (2026-10-04): dvigatelni admin panel boshqaradi.
               "engine_policy", "engine_access",
               # Sxema v4 (2026-10-10): miya flag'lari va shadow taqqoslash.
               "brain_routing", "shadow_results", "playground_cases"}
SPEC_INDEXES = {"turns_started", "turns_actor", "turns_channel", "turns_chat",
                "turn_sources_ref", "api_calls_ts", "api_calls_service", "api_calls_turn",
                "auth_events_ts", "reports_status", "turns_engine",
                "shadow_results_ts", "shadow_results_feature", "playground_cases_created"}
TURN_COLUMNS = [
    "id", "started_at", "ended_at", "actor_id", "user_name", "user_login", "channel", "kind",
    "input_mode", "locale", "chat_id", "request_id", "question", "answer", "route", "status",
    "error_code", "error_text", "http_status", "ttft_ms", "total_ms", "frames",
    "sources_count", "tool_calls", "has_artifact", "has_proposal", "proposal_token",
    "proposal_status", "answer_chars",
    # Sxema v2 (2026-10-02): yordamchi dvigateli.
    "engine",
]


def test_sxema_spetsifikatsiya_boyicha(adb):
    assert adb.version() == SCHEMA_VERSION == 5
    tables = {r["name"] for r in adb.rows(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert tables == SPEC_TABLES
    indexes = {r["name"] for r in adb.rows(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")}
    assert indexes == SPEC_INDEXES
    assert [r["name"] for r in adb.rows("PRAGMA table_info(turns)")] == TURN_COLUMNS
    columns = {r["name"]: r for r in adb.rows("PRAGMA table_info(turns)")}
    assert columns["status"]["dflt_value"] == "'running'"
    assert columns["kind"]["dflt_value"] == "'chat'"
    assert columns["channel"]["notnull"] == 1
    assert [r["name"] for r in adb.rows("PRAGMA table_info(turn_sources)")] == [
        "turn_id", "idx", "kind", "ref", "title", "page", "score", "snippet", "status",
        "digest", "citation", "raw"]
    assert [r["name"] for r in adb.rows("PRAGMA table_info(user_admin)")] == [
        "actor_id", "roles", "disabled", "token_version", "note", "updated_at", "updated_by"]
    assert adb.scalar("PRAGMA journal_mode") == "wal"
    assert adb.scalar("PRAGMA foreign_keys") == 1
    assert adb.scalar("PRAGMA busy_timeout") == 5000


def test_migratsiya_takrorlansa_hech_narsa_buzilmaydi(adb):
    adb.execute("INSERT INTO reports (id, created_at, snapshot) VALUES ('r1', 1.0, '{}')")
    # Xuddi shu fayl - yangi obyekt (qayta ishga tushish) va to'g'ridan-to'g'ri
    # qayta chaqiruv: ikkalasi ham jim o'tadi, ma'lumot joyida.
    again = Database(adb.path)
    assert again.version() == SCHEMA_VERSION
    assert _migrate(again.connect()) == SCHEMA_VERSION
    assert again.scalar("SELECT COUNT(*) FROM reports") == 1
    again.close_all()


def test_bir_vaqtda_ochilgan_ikki_jarayon(tmp_path):
    """API va seed vositasi bir faylni bir vaqtda ochsa - qadam bir marta."""
    path = tmp_path / "x" / "venera.db"
    errors: list[BaseException] = []

    def open_it() -> None:
        try:
            database = Database(path)
            assert database.version() == SCHEMA_VERSION
            database.close_all()
        except BaseException as exc:                        # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=open_it) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_v1_ombor_v2_ga_otadi_malumot_joyida(tmp_path):
    """Prod fayli (sxema v1, ma'lumot bilan) yangi kod bilan ochilsa: `engine`
    ustuni va indeksi qo'shiladi, eski qatorlar joyida va `engine` - NULL
    ("default"), yangi savol esa dvigateli bilan yoziladi. (Oxirgi qadamgacha
    o'tadi - v3 ning o'zi `test_engine_control.py` da.)"""
    from app.services.analytics.db import MIGRATIONS

    path = tmp_path / "prod" / "venera.db"
    path.parent.mkdir()
    old = sqlite3.connect(str(path), isolation_level=None)
    for statement in MIGRATIONS[0]:
        old.execute(statement)
    old.execute("PRAGMA user_version = 1")
    old.execute("INSERT INTO turns (id, started_at, channel, question, status, route) "
                "VALUES ('a' || hex(randomblob(15)), 1.0, 'web', 'eski savol', 'ok', 'rules')")
    old.close()

    database = Database(path)
    assert database.version() == SCHEMA_VERSION
    columns = [r["name"] for r in database.rows("PRAGMA table_info(turns)")]
    assert columns == TURN_COLUMNS
    assert "turns_engine" in {r["name"] for r in database.rows(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    [row] = database.rows("SELECT question, route, engine FROM turns")
    assert (row["question"], row["route"], row["engine"]) == ("eski savol", "rules", None)
    # Jadval sxemasi o'qiladigan holda (ALTER matni `CREATE TABLE` ga qo'shiladi).
    database.execute("INSERT INTO turns (id, started_at, channel, question, engine) "
                     "VALUES ('b', 2.0, 'web', 'yangi', 'v2')")
    assert database.scalar("SELECT engine FROM turns WHERE id='b'") == "v2"
    database.close_all()


def test_eski_kod_yangi_omborni_ochsa_ishlaydi(tmp_path):
    """Deploy orqaga qaytarilsa: v1 kod (`MIGRATIONS` bitta qadam) yangi
    (v3) faylni ochadi - ogohlantiradi, lekin ishlaydi; o'z ustunlarini
    nomlab yozadi."""
    from app.services.analytics import db as db_module

    path = tmp_path / "venera.db"
    fresh = Database(path)
    assert fresh.version() == SCHEMA_VERSION
    fresh.close_all()
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    original = db_module.SCHEMA_VERSION
    try:
        db_module.SCHEMA_VERSION = 1
        assert db_module._migrate(conn) == original
    finally:
        db_module.SCHEMA_VERSION = original
    conn.execute("INSERT INTO turns (id, started_at, channel, question, status) "
                 "VALUES ('x', 1.0, 'web', 'savol', 'ok')")
    assert conn.execute("SELECT engine FROM turns").fetchone()[0] is None
    conn.close()


def test_papka_700_fayl_600(tmp_path):
    path = tmp_path / "yangi" / "ichki" / "venera.db"
    database = Database(path)
    database.connect()
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600
    database.close_all()


def test_har_ipda_alohida_ulanish(adb):
    mine = adb.connect()
    theirs: list[sqlite3.Connection] = []
    thread = threading.Thread(target=lambda: theirs.append(adb.connect()))
    thread.start()
    thread.join()
    assert theirs and theirs[0] is not mine
    assert adb.connect() is mine


def test_standart_yol_sozlamadan(monkeypatch, tmp_path):
    """Sozlama maydoni hali yo'q bo'lsa - default yo'l; testda esa
    `reset_for_tests` qo'ygan fayl."""
    assert db_module.default_path().parts[-3:] == ("data", "analytics", "venera.db")
    assert db_module.setting("mavjud_emas", 7) == 7
    assert db_module.get_db().path == tmp_path / "analytics" / "venera.db"


# ================================================================ yozuvchi ip


_INSERT_AUTH = "INSERT INTO auth_events (ts, login, ok) VALUES (?, ?, 1)"


def test_toplab_yozadi_va_flush_kutadi(adb):
    writer = Writer(adb, batch_wait=0.2)
    for i in range(450):
        assert writer.submit(_INSERT_AUTH, (float(i), f"u{i}"))
    assert writer.flush(5.0)
    assert adb.scalar("SELECT COUNT(*) FROM auth_events") == 450
    stats = writer.stats()
    assert stats["written"] == 450 and stats["dropped"] == 0 and stats["errors"] == 0
    assert stats["maxBatch"] <= 200
    assert stats["batches"] >= 3
    writer.stop()


def test_flush_toplam_vaqtini_kutmaydi(adb):
    writer = Writer(adb, batch_wait=5.0)
    writer.submit(_INSERT_AUTH, (1.0, "a"))
    started = time.monotonic()
    assert writer.flush(3.0)
    assert time.monotonic() - started < 1.0
    assert adb.scalar("SELECT COUNT(*) FROM auth_events") == 1
    writer.stop()


def test_ketma_ket_bir_xil_sql_birlashadi():
    ops = [("sql", "A", (1,)), ("sql", "A", (2,)), ("many", "A", [(3,), (4,)]),
           ("sql", "B", (5,)), ("sql", "A", (6,))]
    groups = _group(ops)
    # Tartib saqlanadi: oxirgi `A` alohida guruh, `B` dan keyin.
    assert [(g[1], g[2]) for g in groups] == [
        ("A", [(1,), (2,), (3,), (4,)]), ("B", [(5,)]), ("A", [(6,)])]


def test_buzuq_yozuv_boshqalarini_yoqotmaydi(adb):
    writer = Writer(adb, batch_wait=0.5)
    writer.submit(_INSERT_AUTH, (1.0, "yaxshi-1"))
    # `ok` NOT NULL - rad etiladi.
    writer.submit("INSERT INTO auth_events (ts, login, ok) VALUES (?, ?, NULL)", (2.0, "buzuq"))
    writer.submit_many(_INSERT_AUTH, [(3.0, "yaxshi-2"), (4.0, "yaxshi-3")])
    writer.submit("INSERT INTO yoq_jadval VALUES (1)")
    assert writer.flush()
    assert [r["login"] for r in adb.rows("SELECT login FROM auth_events ORDER BY ts")] == [
        "yaxshi-1", "yaxshi-2", "yaxshi-3"]
    assert writer.stats()["errors"] == 2
    writer.stop()


def test_navbat_tolsa_tashlaydi_va_hisoblaydi(adb):
    writer = Writer(adb, max_queue=5, autostart=False)
    results = [writer.submit(_INSERT_AUTH, (float(i), "x")) for i in range(8)]
    assert results == [True] * 5 + [False] * 3
    assert writer.dropped == 3
    assert writer.flush()                                   # ipni o'zi ishga tushiradi
    assert adb.scalar("SELECT COUNT(*) FROM auth_events") == 5
    assert writer.stop()
    # To'xtagandan keyingi yozuv - tashlanadi, xato bermaydi.
    assert writer.submit(_INSERT_AUTH, (9.0, "kech")) is False
    assert writer.dropped == 4


def test_ip_ishlamagan_bolsa_stop_navbatni_yozadi(adb):
    writer = Writer(adb, autostart=False)
    writer.submit(_INSERT_AUTH, (1.0, "a"))
    writer.submit(_INSERT_AUTH, (2.0, "b"))
    assert writer.stop()
    assert adb.scalar("SELECT COUNT(*) FROM auth_events") == 2


def test_call_yozuvchi_ipda_bajariladi(adb):
    writer = Writer(adb)
    seen: list[str] = []

    def work(conn: sqlite3.Connection) -> None:
        seen.append(threading.current_thread().name)
        conn.execute(_INSERT_AUTH, (1.0, "call"))

    def broken(conn: sqlite3.Connection) -> None:
        conn.execute(_INSERT_AUTH, (2.0, "yarim"))
        raise RuntimeError("buzildi")

    assert writer.call(work) and writer.call(broken)
    assert writer.flush()
    assert seen == ["analytics-writer"]
    # Buzilgan funksiyaning yarim yozuvi ham qaytarildi (SAVEPOINT).
    assert [r["login"] for r in adb.rows("SELECT login FROM auth_events")] == ["call"]
    writer.stop()


def _seed_old_and_new(adb: Database, now: float) -> None:
    old, new = now - 200 * 86400, now - 10 * 86400
    with adb.transaction() as conn:
        for tid, ts in (("old1", old), ("old2", old), ("new1", new)):
            conn.execute("INSERT INTO turns (id, started_at, channel, question) VALUES (?,?,?,?)",
                         (tid, ts, "web", "q"))
            conn.execute("INSERT INTO turn_events (turn_id, seq, t_ms, type, name) "
                         "VALUES (?, 0, 0, 'frame', 'stage')", (tid,))
            conn.execute("INSERT INTO turn_sources (turn_id, idx) VALUES (?, 0)", (tid,))
        for ts in (old, old, new):
            conn.execute("INSERT INTO api_calls (ts, service, op, status, duration_ms) "
                         "VALUES (?, 'tts', 'speak', 'ok', 1)", (ts,))
            conn.execute("INSERT INTO auth_events (ts, ok) VALUES (?, 1)", (ts,))
        conn.execute("INSERT INTO reports (id, created_at, turn_id, snapshot) "
                     "VALUES ('r', ?, 'old1', '{}')", (old,))
        conn.execute("INSERT INTO audit_log (ts, action) VALUES (?, 'user.block')", (old,))


def test_eski_yozuvlar_tozalanadi_shikoyat_va_audit_qoladi(adb):
    now = time.time()
    _seed_old_and_new(adb, now)
    counts = purge(adb, 180, now=now, chunk=1)              # bo'laklab ham to'g'ri
    assert counts == {"turns": 2, "events": 2, "sources": 2, "apiCalls": 2, "authEvents": 2}
    assert [r["id"] for r in adb.rows("SELECT id FROM turns")] == ["new1"]
    assert adb.scalar("SELECT COUNT(*) FROM turn_events") == 1
    assert adb.scalar("SELECT COUNT(*) FROM turn_sources") == 1
    assert adb.scalar("SELECT COUNT(*) FROM api_calls") == 1
    assert adb.scalar("SELECT COUNT(*) FROM auth_events") == 1
    assert adb.scalar("SELECT COUNT(*) FROM reports") == 1
    assert adb.scalar("SELECT COUNT(*) FROM audit_log") == 1
    assert purge(adb, 0, now=now) == dict.fromkeys(counts, 0)   # 0 - o'chiq


def test_yozuvchi_davriy_tozalaydi(adb):
    _seed_old_and_new(adb, time.time())
    writer = Writer(adb, purge_first=0.0, purge_every=3600.0, retention_days=180)
    writer.start()
    deadline = time.monotonic() + 5.0
    while writer.stats()["lastPurgeAt"] is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert writer.stats()["purged"]["turns"] == 2
    assert adb.scalar("SELECT COUNT(*) FROM turns") == 1
    writer.stop()


def test_ombor_ochilmasa_ham_xato_chiqmaydi(tmp_path):
    blocker = tmp_path / "fayl"
    blocker.write_text("papka emas")
    writer = Writer(Database(blocker / "venera.db"))       # ota "papka" - fayl
    assert writer.submit(_INSERT_AUTH, (1.0, "x")) is True
    assert writer.flush()
    assert writer.stats()["errors"] == 1
    writer.stop()


# ================================================================ savol izi


def _realistic_frames(delay: float = 0.03):
    """Jonli oqim tartibi: stage -> sources (2 hujjat + 1 HRM) -> 20 token -> done."""
    yield _line({"type": "stage", "text": "Hujjatlar qidirilmoqda"})
    yield _line({"type": "sources", "items": [
        {"kind": "doc", "doc_id": "HR_045", "title": "Ichki mehnat tartibi qoidalari",
         "page": 22, "citation_index": 1, "score": 0.83,
         "snippet": "Ish vaqti 9:00 dan 18:00 gacha", "docUrl": "/api/v1/chat/doc/HR_045#page=22"},
        {"kind": "doc", "doc_id": "HR_012", "title": "Mehnat ta'tili nizomi", "page": "3",
         "citation_index": 2, "relevance": 0.71, "text": "Yillik ta'til 21 kun"},
        {"kind": "hrm", "tool": "hrm_today_late", "marker": "[T1]", "status": "ok",
         "digest": "3 ta kechikish"},
    ]})
    time.sleep(delay)
    for i in range(20):
        yield _line({"type": "token", "text": f"so'z{i} "})
    yield _line({"type": "done", "route": "hybrid", "request_id": "upstream-rid-1"})


def test_realistik_oqim_toliq_iz(adb):
    rec = TurnRecorder(USER, "web", "chat", "Bugun kim kechikdi?", chat_id="chat-1",
                       locale="uz", input_mode="voice")
    passed = list(rec.wrap(_realistic_frames()))
    assert len(passed) == 23                                # kadrlar o'zgarmasdan o'tdi
    assert passed[0] == _line({"type": "stage", "text": "Hujjatlar qidirilmoqda"})

    turn = _turn(adb, rec.turn_id)
    assert turn["status"] == "ok"
    assert turn["actor_id"] == 42 and turn["user_name"] == "Yusuf Mamajonov"
    assert turn["user_login"] == "y.mamajonov@brb.uz"
    assert (turn["channel"], turn["kind"], turn["input_mode"]) == ("web", "chat", "voice")
    assert (turn["locale"], turn["chat_id"]) == ("uz", "chat-1")
    assert turn["question"] == "Bugun kim kechikdi?"
    assert turn["answer"] == "".join(f"so'z{i} " for i in range(20))
    assert turn["answer_chars"] == len(turn["answer"])
    assert turn["route"] == "hybrid" and turn["request_id"] == "upstream-rid-1"
    assert turn["frames"] == 23
    assert turn["sources_count"] == 2 and turn["tool_calls"] == 1
    assert turn["has_artifact"] == 0 and turn["has_proposal"] == 0
    assert turn["ttft_ms"] >= 25
    assert turn["total_ms"] >= turn["ttft_ms"]
    assert turn["ended_at"] >= turn["started_at"]
    assert turn["error_code"] is None and turn["http_status"] is None

    events = adb.rows("SELECT * FROM turn_events WHERE turn_id = ? ORDER BY seq", (rec.turn_id,))
    assert [(e["type"], e["name"]) for e in events] == [
        ("note", "first_frame"), ("frame", "stage"), ("frame", "sources"),
        ("note", "first_token"), ("frame", "done")]
    by_name = {e["name"]: e for e in events}
    assert json.loads(by_name["stage"]["payload"]) == {"text": "Hujjatlar qidirilmoqda"}
    assert json.loads(by_name["sources"]["payload"]) == {
        "count": 3, "docs": 2, "tools": 1, "refs": ["HR_045", "HR_012", "hrm_today_late"]}
    assert by_name["first_token"]["t_ms"] == turn["ttft_ms"]
    assert json.loads(by_name["done"]["payload"])["route"] == "hybrid"

    sources = adb.rows("SELECT * FROM turn_sources WHERE turn_id = ? ORDER BY idx",
                       (rec.turn_id,))
    assert [(s["idx"], s["kind"], s["ref"]) for s in sources] == [
        (0, "doc", "HR_045"), (1, "doc", "HR_012"), (2, "hrm", "hrm_today_late")]
    first, second, tool = sources
    assert (first["title"], first["page"], first["score"], first["citation"]) == (
        "Ichki mehnat tartibi qoidalari", 22, 0.83, 1)
    assert first["snippet"] == "Ish vaqti 9:00 dan 18:00 gacha"
    assert (second["page"], second["score"], second["snippet"]) == (3, 0.71, "Yillik ta'til 21 kun")
    assert (tool["status"], tool["digest"], tool["citation"]) == ("ok", "3 ta kechikish", 1)
    assert json.loads(first["raw"])["docUrl"].startswith("/api/v1/chat/doc/HR_045")


def test_boshida_running_qator_yoziladi(adb):
    rec = TurnRecorder(USER, "miniapp", "chat", "Savol")
    turn = _turn(adb, rec.turn_id)
    assert turn["status"] == "running" and turn["ended_at"] is None
    assert rec.finish() is True
    assert rec.finish("error") is False                     # ikkinchisi - hech narsa
    assert _turn(adb, rec.turn_id)["status"] == "ok"


def test_xato_kadri(adb):
    rec = TurnRecorder(USER, "web", "chat", "CRM dagi vazifalarim?")
    frames = [
        _line({"type": "stage", "text": "CRM"}),
        _line({"type": "error", "code": "auth_missing", "text": "CRM tizimiga kiring"}),
        _line({"type": "done", "route": None}),
    ]
    assert list(rec.wrap(frames)) == frames
    turn = _turn(adb, rec.turn_id)
    assert turn["status"] == "error"
    assert (turn["error_code"], turn["error_text"]) == ("auth_missing", "CRM tizimiga kiring")
    assert turn["answer"] == "" and turn["ttft_ms"] is None and turn["route"] is None
    names = [r["name"] for r in adb.rows(
        "SELECT name FROM turn_events WHERE turn_id = ? ORDER BY seq", (rec.turn_id,))]
    assert names == ["first_frame", "stage", "error", "done"]


class _UpstreamBroke(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def test_oqim_orasida_istisno(adb):
    def frames():
        yield _line({"type": "token", "text": "Yarim"})
        raise _UpstreamBroke(f"javob to'xtab qoldi, Authorization: Bearer {JWT}", 504)

    rec = TurnRecorder(USER, "web", "chat", "q")
    with pytest.raises(_UpstreamBroke):
        list(rec.wrap(frames()))
    turn = _turn(adb, rec.turn_id)
    assert turn["status"] == "error" and turn["http_status"] == 504
    assert turn["error_code"] == "_UpstreamBroke"
    assert JWT not in turn["error_text"] and "<token>" in turn["error_text"]
    assert turn["answer"] == "Yarim"


def test_klient_uzilsa_cancelled_va_ichki_oqim_yopiladi(adb):
    closed = threading.Event()

    def frames():
        try:
            yield from _realistic_frames(delay=0)
        finally:
            closed.set()

    rec = TurnRecorder(USER, "web", "chat", "q")
    stream = rec.wrap(frames())
    next(stream)
    next(stream)
    stream.close()                                          # GeneratorExit
    assert closed.is_set()
    turn = _turn(adb, rec.turn_id)
    assert turn["status"] == "cancelled" and turn["frames"] == 2


def test_hech_boshlanmagan_oqim_ham_yakunlanadi(adb):
    rec = TurnRecorder(USER, "web", "chat", "q")
    turn_id = rec.turn_id
    stream = rec.wrap(iter([_line({"type": "token", "text": "x"})]))
    del stream, rec
    gc.collect()
    assert _turn(adb, turn_id)["status"] == "cancelled"


def test_chegaralar(adb):
    rec = TurnRecorder(USER, "web", "chat", "s" * 10_000)
    rec.observe({"type": "stage", "text": "x" * 200_000})
    rec.observe({"type": "sources", "sources": [
        {"kind": "doc", "doc_id": "HR_1", "snippet": "y" * 5000, "extra": "z" * 20_000}]})
    for _ in range(70):
        rec.observe({"type": "token", "text": "a" * 1000})
    rec.finish()
    turn = _turn(adb, rec.turn_id)
    assert len(turn["question"]) == QUESTION_CAP
    assert len(turn["answer"]) == ANSWER_CAP and turn["answer_chars"] == 70_000
    payload = adb.scalar("SELECT payload FROM turn_events WHERE turn_id = ? AND name = 'stage'",
                         (rec.turn_id,))
    assert len(payload) <= PAYLOAD_CAP and json.loads(payload)["_truncated"] is True
    source = adb.row("SELECT snippet, raw FROM turn_sources WHERE turn_id = ?", (rec.turn_id,))
    assert len(source["snippet"]) == SNIPPET_CAP
    assert len(source["raw"]) <= RAW_CAP and json.loads(source["raw"])["_truncated"] is True


def test_hodisalar_soni_chegaralangan(adb, monkeypatch):
    from app.services.analytics import recorder as recorder_module

    monkeypatch.setattr(recorder_module, "MAX_EVENTS", 5)
    rec = TurnRecorder(USER, "web", "chat", "q")
    for i in range(10):
        rec.observe({"type": "stage", "text": str(i)})
    rec.finish()
    names = [r["name"] for r in analytics.flush() and adb.rows(
        "SELECT name FROM turn_events WHERE turn_id = ? ORDER BY seq", (rec.turn_id,))]
    assert len(names) == 6 and names[-1] == "events_dropped"


def test_artifact_proposal_hold_va_kop_qatorli_bolak(adb):
    rec = TurnRecorder(USER, "web", "chat", "Ta'til arizasi yoz")
    chunk = (_line({"type": "hold", "text": "Bir soniya", "clip": "tatil-ilk-0", "at": 1,
                    "topic": "tatil", "source": "ollama"})
             + _line({"type": "artifact", "artifact": {
                 "title": "Ariza", "doc_id": "A1",
                 "docx_url": "/api/v1/chat/artifact/SECRET-ONE-TIME/docx", "pdf_url": None}}))
    rec.observe_raw(chunk)
    rec.observe_raw(_line({"type": "proposal", "proposal": {
        "token": "prop-token-1", "summary": "Ta'tilni yozish", "operation": "leave.create",
        "changes": [{"field": "days", "to": 3}]}}))
    rec.observe_raw(b"buzuq json\n")
    rec.observe_raw(_line({"type": "yangi_tur", "foo": 1}))
    rec.finish()
    turn = _turn(adb, rec.turn_id)
    assert turn["has_artifact"] == 1 and turn["has_proposal"] == 1
    assert (turn["proposal_token"], turn["proposal_status"]) == ("prop-token-1", "pending")
    assert turn["frames"] == 4
    events = {r["name"]: r for r in adb.rows(
        "SELECT * FROM turn_events WHERE turn_id = ?", (rec.turn_id,))}
    # `hold` - bizning kadrimiz, `first_frame` artifact'ga tegishli.
    assert json.loads(events["first_frame"]["payload"]) == {"type": "artifact"}
    assert json.loads(events["hold"]["payload"])["clip"] == "tatil-ilk-0"
    assert "SECRET-ONE-TIME" not in events["artifact"]["payload"]
    assert json.loads(events["artifact"]["payload"])["files"] == ["docx"]
    assert "prop-token-1" not in events["proposal"]["payload"]
    assert json.loads(events["proposal"]["payload"])["operation"] == "leave.create"
    assert json.loads(events["yangi_tur"]["payload"]) == {"foo": 1}
    assert json.loads(events["bad_lines"]["payload"]) == {"count": 1}

    assert set_proposal_status("prop-token-1", "executed")
    assert set_proposal_status("prop-token-1", "nimadir") is False
    assert _turn(adb, rec.turn_id)["proposal_status"] == "executed"


def test_ask_quvuri_shaklidagi_manbalar(adb):
    """`/chat/ask` natijasi boshqa nomlar bilan keladi - ular ham tanilaydi."""
    rec = TurnRecorder(USER, "api", "ask", "q")
    rec.observe({"type": "sources", "sources": [{
        "chunkId": "c1", "text": "Parcha", "documentId": "DOC-7",
        "source": {"documentTitle": "Nizom", "page": 4}, "rerankScore": 0.5}]})
    rec.observe({"type": "sources", "items": [{"tool": "crm_my_issues", "status": "ok"}, "g'alati"]})
    rec.update(answer="To'liq javob", route="rag", request_id="rid", nomalum=1)
    rec.finish()
    turn = _turn(adb, rec.turn_id)
    assert (turn["kind"], turn["answer"], turn["route"], turn["request_id"]) == (
        "ask", "To'liq javob", "rag", "rid")
    assert turn["sources_count"] == 2 and turn["tool_calls"] == 1
    rows = adb.rows("SELECT * FROM turn_sources WHERE turn_id = ? ORDER BY idx", (rec.turn_id,))
    assert [(r["idx"], r["kind"], r["ref"], r["title"], r["page"], r["score"]) for r in rows] == [
        (0, "doc", "DOC-7", "Nizom", 4, 0.5),
        (1, "crm", "crm_my_issues", None, None, None),
        (2, None, None, None, None, None)]
    assert json.loads(rows[2]["raw"]) == {"value": "g'alati"}


def test_span_point_va_tashqi_oraliq(adb):
    rec = TurnRecorder(USER, "web", "chat", "q")
    with rec.span("assistant.open", model="x") as info:
        time.sleep(0.02)
        info["requestId"] = "r1"
    with pytest.raises(ValueError):
        with rec.span("hold.classify"):
            raise ValueError("model javob bermadi")
    started = time.monotonic() - 0.5
    rec.record_span("stt", started, started + 0.25, audioSec=3.2)
    rec.point("hold.fire", at=1)
    rec.finish()
    events = {r["name"]: r for r in analytics.flush() and adb.rows(
        "SELECT * FROM turn_events WHERE turn_id = ?", (rec.turn_id,))}
    assert events["assistant.open"]["type"] == "span"
    assert events["assistant.open"]["dur_ms"] >= 15
    assert json.loads(events["assistant.open"]["payload"]) == {"model": "x", "requestId": "r1"}
    assert "model javob bermadi" in json.loads(events["hold.classify"]["payload"])["error"]
    assert events["stt"]["dur_ms"] == 250
    assert events["hold.fire"]["type"] == "note" and events["hold.fire"]["dur_ms"] is None


def test_with_blok_yakunlaydi(adb):
    with TurnRecorder(USER, "web", "ask", "q") as rec:
        assert current().turn_id == rec.turn_id
    assert current().turn_id is None
    assert _turn(adb, rec.turn_id)["status"] == "ok"
    with pytest.raises(RuntimeError):
        with TurnRecorder(USER, "web", "ask", "q") as failed:
            raise RuntimeError("quvur yiqildi")
    assert _turn(adb, failed.turn_id)["error_code"] == "RuntimeError"


def test_ochiq_bolmasa_hech_narsa_yozilmaydi(adb, monkeypatch):
    monkeypatch.setattr(db_module, "analytics_enabled", lambda: False)
    rec = TurnRecorder(USER, "web", "chat", "q")
    assert list(rec.wrap([_line({"type": "token", "text": "x"})])) == [
        _line({"type": "token", "text": "x"})]
    assert record_call("tts", "speak") is False
    with metered("tts", "speak"):
        pass
    assert analytics.flush()
    assert adb.scalar("SELECT COUNT(*) FROM turns") == 0
    assert adb.scalar("SELECT COUNT(*) FROM api_calls") == 0


def test_turn_kaliti_tekshiruvi():
    assert valid_turn_id("0123456789ABCDEF0123456789abcdef ") == "0123456789abcdef0123456789abcdef"
    for bad in (None, "", "xyz", "0" * 31, "0" * 33, "g" * 32, 123):
        assert valid_turn_id(bad) is None
    assert TurnRecorder(USER, "web", "chat", "q", turn_id="bad").turn_id != "bad"


# ================================================================ chaqiruvlar hisobi


def _calls(adb: Database) -> list[dict]:
    assert analytics.flush()
    return adb.rows("SELECT * FROM api_calls ORDER BY id")


def test_metered_muvaffaqiyat(adb):
    with bind(7, "miniapp", "t" * 32):
        with metered("tts", "speak", units={"chars": 120}) as call:
            time.sleep(0.01)
            call.units["audioSec"] = 7.25
            call.units["ignored"] = "matn"
    [row] = _calls(adb)
    assert (row["service"], row["op"], row["status"]) == ("tts", "speak", "ok")
    assert row["duration_ms"] >= 5
    assert (row["actor_id"], row["channel"], row["turn_id"]) == (7, "miniapp", "t" * 32)
    assert json.loads(row["units"]) == {"chars": 120, "audioSec": 7.25}
    assert row["error"] is None and row["http_status"] is None


class _HttpLike(Exception):
    def __init__(self, message: str, **attrs) -> None:
        super().__init__(message)
        for key, value in attrs.items():
            setattr(self, key, value)


def test_metered_xato_statusi_va_sirlar(adb, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "hrm_assistant_client_secret", "juda-maxfiy-sir-123")
    with pytest.raises(_HttpLike):
        with metered("assistant", "stream"):
            raise _HttpLike("X-Client-Secret: juda-maxfiy-sir-123 rad etildi", status=503)
    with pytest.raises(_HttpLike):
        with metered("telegram", "sendMessage"):
            raise _HttpLike("bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ/sendMessage", code=404)
    with pytest.raises(_HttpLike):
        with metered("crm", "refresh"):
            raise _HttpLike('{"refresh_token": "abc.def", "password": "p@ss"}', code="BAD_RESPONSE")
    with metered("stt_router", "transcribe") as call:
        call.fail("navbat to'la", http_status=503)
    rows = _calls(adb)
    assert [(r["status"], r["http_status"]) for r in rows] == [
        ("error", 503), ("error", 404), ("error", None), ("error", 503)]
    assert "juda-maxfiy-sir-123" not in rows[0]["error"] and "***" in rows[0]["error"]
    assert "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ" not in rows[1]["error"]
    assert "abc.def" not in rows[2]["error"] and "p@ss" not in rows[2]["error"]
    assert rows[3]["error"] == "navbat to'la"
    assert all(len(r["error"]) <= 300 for r in rows)


def test_redact_va_http_status():
    assert redact(f"Bearer {JWT}") == "Bearer <token>"
    assert JWT not in redact(f"token {JWT} rad etildi")
    assert redact("gapi_abcdef123 kaliti") == "<key> kaliti"
    assert redact("0123456789abcdef0123456789abcdef.AbCdEfGhIjKlMnOpQrStUvWx") == "<key>"
    assert redact("initData=query_id%3DAAH&hash=abc") == "initData=***&hash=***"
    assert redact("hrm_token o'qib bo'lmadi") == "hrm_token o'qib bo'lmadi"
    assert redact("a\n  b") == "a b"
    long = redact("x" * 1000)
    assert len(long) == 300 and long.endswith("…")
    assert http_status_of(_HttpLike("x", status=True)) is None
    assert http_status_of(_HttpLike("x", code=429)) == 429
    assert http_status_of(None) is None


def test_record_call_va_begin_end(adb):
    assert record_call("hrm", "authenticate", status="error", duration_ms=12.6, http_status=401,
                       actor_id="5", channel="Telegram", error="Parol noto'g'ri")
    call = begin("assistant", "stream", units={"frames": 0})
    call.units["frames"] = 23
    done = threading.Event()
    threading.Thread(target=lambda: (call.end(), done.set())).start()   # boshqa ipdan
    assert done.wait(2)
    assert call.end() is False                              # ikkinchisi - hech narsa
    first, second = _calls(adb)
    assert (first["actor_id"], first["channel"], first["duration_ms"]) == (5, "bot", 13)
    assert first["error"] == "Parol noto'g'ri"
    assert json.loads(second["units"]) == {"frames": 23} and second["status"] == "ok"


def test_kirish_hodisasi(adb):
    assert record_auth_event("  Y.Mamajonov@BRB.uz " + "x" * 200, False, method="sso",
                             channel="web", reason="bad_password")
    assert analytics.flush()
    row = adb.row("SELECT * FROM auth_events")
    assert row["login"].startswith("y.mamajonov@brb.uz") and len(row["login"]) == 128
    assert (row["ok"], row["method"], row["channel"], row["reason"]) == (
        0, "sso", "web", "bad_password")


def test_bind_ichma_ich_va_qaytarish():
    assert current() == (None, None, None)
    with bind(1, "web", "a" * 32):
        with bind(channel="miniapp"):                       # qolganlari o'zgarmaydi
            assert current() == (1, "miniapp", "a" * 32)
        with bind(turn_id=None):                            # `None` - tozalash
            assert current().turn_id is None
        assert current() == (1, "web", "a" * 32)
    assert current() == (None, None, None)


def test_bind_boshqa_kontekstda_reset_xato_bermaydi():
    binding = contextvars.Context().run(bind, 1, "web", None)
    binding.reset()                                         # jim o'tadi
    assert current() == (None, None, None)


def test_atributsiya_ishchi_ipda(adb):
    def work(op: str) -> None:
        with metered("ollama", op):
            pass

    with bind(9, "web", "b" * 32):
        # 1) `carry` bilan o'ralgan oddiy ip;
        thread = threading.Thread(target=carry(work), args=("carry",))
        thread.start()
        thread.join()
        # 2) threadpool - FastAPI qiladigandek, kontekst nusxasi bilan;
        with ThreadPoolExecutor(2) as pool:
            ctx = contextvars.copy_context()
            pool.submit(ctx.run, work, "pool").result()
        # 3) O'RALMAGAN ip - kontekst meros bo'lmaydi (Python 3.10). Shu
        #    sababli `carry` kerak; bu test o'sha xulqni hujjatlaydi.
        bare = threading.Thread(target=work, args=("bare",))
        bare.start()
        bare.join()
        # `begin` atributsiyani BOSHIDA oladi - `end` istalgan ipda.
        call = begin("assistant", "stream")
    closer = threading.Thread(target=call.end)
    closer.start()
    closer.join()
    rows = {r["op"]: r for r in _calls(adb)}
    for op in ("carry", "pool", "stream"):
        assert (rows[op]["actor_id"], rows[op]["channel"], rows[op]["turn_id"]) == (
            9, "web", "b" * 32), op
    assert (rows["bare"]["actor_id"], rows["bare"]["turn_id"]) == (None, None)


def test_generator_boshqa_iplarda_iste_mol_qilinadi(adb):
    """`StreamingResponse` har `next()` ni BOSHQA ipda, BO'SH kontekstda
    bajarsa ham generator ichidagi har chaqiruv shu savolga yoziladi."""
    def frames():
        for i in range(3):
            with metered("assistant", f"step{i}"):
                pass
            yield _line({"type": "token", "text": str(i)})

    rec = TurnRecorder(USER, "desktop", "chat", "q")
    stream = rec.wrap(frames())
    out = []
    with ThreadPoolExecutor(3) as pool:
        while True:
            # Har qadam - yangi bo'sh kontekst, navbatdagi ip.
            item = pool.submit(contextvars.Context().run, next, stream, None).result()
            if item is None:
                break
            out.append(item)
    assert len(out) == 3
    rows = _calls(adb)
    assert [r["op"] for r in rows] == ["step0", "step1", "step2"]
    assert {(r["actor_id"], r["channel"], r["turn_id"]) for r in rows} == {
        (42, "desktop", rec.turn_id)}
    assert current() == (None, None, None)                  # hech narsa sizib chiqmadi
    assert _turn(adb, rec.turn_id)["answer"] == "012"


def test_starlette_threadpool_orqali(adb):
    """Aynan `StreamingResponse` ishlatadigan yo'l: `iterate_in_threadpool`."""
    def frames():
        for i in range(2):
            record_call("assistant", f"s{i}")
            yield _line({"type": "token", "text": "x"})

    rec = TurnRecorder(USER, "web", "chat", "q")

    async def consume() -> list[bytes]:
        return [chunk async for chunk in iterate_in_threadpool(rec.wrap(frames()))]

    assert len(anyio.run(consume)) == 2
    rows = _calls(adb)
    assert [r["turn_id"] for r in rows] == [rec.turn_id, rec.turn_id]
    assert _turn(adb, rec.turn_id)["status"] == "ok"


# ================================================================ kanal


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


@pytest.mark.parametrize(("headers", "expected"), [
    ({"X-Venera-Client": "web"}, "web"),
    ({"X-Venera-Client": " MiniApp "}, "miniapp"),
    ({"x-venera-client": "desktop"}, "desktop"),
    # `bot` sarlavha orqali qabul qilinmaydi - soxta.
    ({"X-Venera-Client": "bot"}, "api"),
    ({"X-Venera-Client": "bot", "Referer": "https://llm.brb-tech.uz/tg/?x=1"}, "miniapp"),
    ({"Referer": "https://llm.brb-tech.uz/tg/"}, "miniapp"),
    ({"Referer": "https://llm.brb-tech.uz/tg"}, "miniapp"),
    ({"X-Venera-Client": "boshqa", "Referer": "https://llm.brb-tech.uz/tg/index.html"}, "miniapp"),
    ({"Referer": "https://llm.brb-tech.uz/tgx/"}, "api"),
    # Yangi Mini App (beta) - o'z yo'li ostida.
    ({"Referer": "https://llm.brb-tech.uz/tg-beta/"}, "miniapp"),
    ({"Referer": "https://llm.brb-tech.uz/tg-beta"}, "miniapp"),
    ({"Referer": "https://llm.brb-tech.uz/tg-beta/?tg_init=x"}, "miniapp"),
    ({"Referer": "https://llm.brb-tech.uz/tg-betax/"}, "api"),
    ({"Referer": "https://llm.brb-tech.uz/tg-app.html"}, "api"),
    ({"Referer": "https://llm.brb-tech.uz/chat"}, "api"),
    ({"Origin": "https://llm.brb-tech.uz"}, "api"),
    ({"X-Venera-Client": "web", "Referer": "https://llm.brb-tech.uz/tg/"}, "web"),
    ({}, "api"),
])
def test_channel_of(headers, expected):
    assert channel_of(_request(headers)) == expected


def test_channel_of_chidamli():
    assert channel_of(None) == "api"
    assert channel_of(object()) == "api"
    assert channel_of(type("R", (), {"headers": {"x-venera-client": "web"}})()) == "web"


def test_normalize():
    assert normalize("WEB") == "web"
    assert normalize("telegram") == "bot"
    assert normalize("tg") == "miniapp"
    assert normalize("nimadir") == "api"
    assert normalize("nimadir", default=None) is None
    assert normalize(None) == "api"
    # `mobile` - yig'ilish yozuvchisi ilovasi (docs/plans/meeting-recorder.md).
    assert set(CHANNELS) == {"web", "miniapp", "bot", "desktop", "mobile", "api"}
    assert normalize("mobile") == "mobile"


def test_umumiy_yozuvchi_testdagi_faylga_yozadi(adb, tmp_path):
    """`reset_for_tests` yozuvchini ham almashtiradi - jonli faylga tegilmaydi."""
    assert writer_module.get_writer().db is adb
    assert adb.path == tmp_path / "analytics" / "venera.db"
    assert db_module.default_path() != adb.path

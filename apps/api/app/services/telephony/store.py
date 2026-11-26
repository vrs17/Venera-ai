"""Qo'ng'iroqlar ombori - SQLite (`data/telephony/calls.db`, 600).

HOLATLAR (`status`):
    placing    so'rov FreePBX'ga ketmoqda;
    queued     FreePBX qabul qildi (202) - mijozga qo'ng'iroq qilinmoqda, natija kutilmoqda;
    rejected   FreePBX qabul qilmadi (409/422/429/502/503...) yoki unga ulanib bo'lmadi - qo'ng'iroq YO'Q;
    failed     mijoz javob bermadi / band / tarmoq (FreePBX `failed` natijasi);
    completed  mijoz javob berdi, suhbat tugadi (FreePBX `answered` natijasi);
    unknown    202 dan keyin belgilangan vaqtda natija kelmadi, yoki so'rov ketdi-yu javob kelmadi.
               YAKUNIY EMAS: kech kelgan natija uni `failed`/`completed` ga almashtiradi.

NATIJA BIR MARTA yoziladi (`result_at IS NULL` sharti bilan, bitta UPDATE - ikki parallel yetkazish ham
bittasi bo'lib qoladi). Kelgan HAR so'rov (takror, notanish call_id, buzilgan) `call_events` ga yoziladi -
FreePBX bilan kelishmovchilik bo'lsa dalil shu yerda.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_SCHEMA = (
    """CREATE TABLE calls (
  call_id TEXT PRIMARY KEY, phone TEXT NOT NULL, actor_id INTEGER, note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', http_status INTEGER,
  created_at INTEGER NOT NULL, placed_at INTEGER, result_at INTEGER,
  answer_time INTEGER, end_time INTEGER, talk_sec INTEGER, gateway_status TEXT, hangup_cause TEXT, uniqueid TEXT,
  result_json TEXT)""",
    "CREATE INDEX calls_created ON calls(created_at)",
    """CREATE TABLE call_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, received_at INTEGER NOT NULL, call_id TEXT, event TEXT,
  verdict TEXT NOT NULL, caller TEXT, payload TEXT NOT NULL)""",
    "CREATE INDEX call_events_call ON call_events(call_id)",
)

#: Natija bilan yangilanadigan ustunlar (service.py shu nomlar bilan beradi).
RESULT_COLUMNS = ("status", "outcome", "answer_time", "end_time", "talk_sec", "gateway_status", "hangup_cause",
                  "uniqueid")


class CallStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        with self._lock:
            if not self._ready:
                parent = self.path.parent
                created = not parent.exists()
                parent.mkdir(parents=True, exist_ok=True)
                if created:
                    with contextlib.suppress(OSError):
                        os.chmod(parent, 0o700)
                if not self.path.exists():
                    os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
                with contextlib.suppress(OSError):
                    os.chmod(self.path, 0o600)
            conn = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            if not self._ready:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                            for statement in _SCHEMA:
                                conn.execute(statement)
                            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                self._ready = True
        self._local.conn = conn
        return conn

    # ------------------------------------------------------------------ yozish

    def create(self, call_id: str, phone: str, actor_id: int | None, note: str, now: int) -> None:
        self._connect().execute(
            "INSERT INTO calls (call_id, phone, actor_id, note, status, created_at) VALUES (?, ?, ?, ?, 'placing', ?)",
            (call_id, phone, actor_id, note, now))

    def mark_placed(self, call_id: str, *, status: str, http_status: int | None, detail: str, now: int) -> None:
        """call-live javobi: `queued` (202), `rejected` yoki `unknown` (so'rov ketdi, javob kelmadi)."""
        self._connect().execute(
            "UPDATE calls SET status = ?, http_status = ?, detail = ?, placed_at = ? "
            "WHERE call_id = ? AND result_at IS NULL",
            (status, http_status, detail, now, call_id))

    def apply_result(self, call_id: str, fields: dict[str, Any], raw: str, now: int) -> str:
        """FreePBX natijasi -> `recorded` | `duplicate` (natija allaqachon bor) | `unknown_call` (bizda yo'q)."""
        columns = [name for name in RESULT_COLUMNS if name in fields]
        assignments = ", ".join(f"{name} = ?" for name in columns)
        values = [fields[name] for name in columns]
        conn = self._connect()
        cursor = conn.execute(
            f"UPDATE calls SET {assignments}, result_at = ?, result_json = ? WHERE call_id = ? AND result_at IS NULL",
            (*values, now, raw, call_id))
        if cursor.rowcount == 1:
            return "recorded"
        exists = conn.execute("SELECT 1 FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        return "duplicate" if exists else "unknown_call"

    def add_event(self, *, call_id: str | None, event: str | None, verdict: str, caller: str, payload: str,
                  now: int) -> None:
        self._connect().execute(
            "INSERT INTO call_events (received_at, call_id, event, verdict, caller, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (now, call_id, event, verdict, caller, payload[:8192]))

    def mark_stale_unknown(self, *, placed_before: int, created_before: int) -> int:
        """Natijasi kelmagan eski qo'ng'iroqlar -> `unknown` (`queued`, yoki osilib qolgan `placing`)."""
        cursor = self._connect().execute(
            "UPDATE calls SET status = 'unknown', detail = 'no_result' "
            "WHERE result_at IS NULL AND ((status = 'queued' AND placed_at < ?) OR (status = 'placing' AND created_at < ?))",
            (placed_before, created_before))
        return cursor.rowcount

    # ------------------------------------------------------------------ o'qish

    def get(self, call_id: str) -> dict[str, Any] | None:
        row = self._connect().execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        return _row(row) if row else None

    def recent(self, limit: int) -> list[dict[str, Any]]:
        rows = self._connect().execute("SELECT * FROM calls ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
        return [_row(row) for row in rows]

    def count_since(self, since: int) -> int:
        return int(self._connect().execute("SELECT COUNT(*) FROM calls WHERE created_at >= ?", (since,)).fetchone()[0])

    def events(self, call_id: str) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT received_at, event, verdict, caller FROM call_events WHERE call_id = ? ORDER BY id", (call_id,))
        return [dict(row) for row in rows]


def _row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw = data.pop("result_json", None)
    try:
        data["result"] = json.loads(raw) if raw else None
    except ValueError:
        data["result"] = None
    return data

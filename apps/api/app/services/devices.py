"""Qurilma tokenlari - mobil ilova uchun uzoq sessiya (spetsifikatsiya 3.2, 29-31).

MUAMMO. Venera JWT 12 soat yashaydi va yangilanmaydi. Yozuvchi ilova esa
"bir marta kiring, keyin o'zi" bo'lishi kerak: yon tugma bilan yozish
boshlanganda parol so'rash - yozuvni yo'qotish degani.

YECHIM `/telegram/session` dan nusxa: kirgan odam qurilmani ro'yxatdan
o'tkazadi va 32 baytlik tasodifiy TOKEN oladi; token keyin yangi JWT ga
almashtiriladi. Admin qarorlari (blok, "hamma joydan chiqarish") har
almashtirishda tekshiriladi - token sessiya versiyasi bilan bog'langan.

OMBORDA FAQAT XESH (`sha256(token)`). Fayl o'g'irlansa ham undan token
tiklab bo'lmaydi. Muddat SIRPANUVCHI: oxirgi ishlatilgandan 30 kun.
Fayl `data/devices.db`, 600.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid

from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA = (
    """CREATE TABLE devices (
  id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, actor_id INTEGER NOT NULL,
  token_version INTEGER NOT NULL DEFAULT 0, device_name TEXT, platform TEXT, app_version TEXT,
  created_at INTEGER NOT NULL, last_used_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  revoked_at INTEGER)""",
    "CREATE INDEX devices_actor ON devices(actor_id)",
)


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def new_token() -> str:
    """32 tasodifiy bayt -> 43 belgili base64url (to'ldiruvchisiz)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


class DeviceStore:
    def __init__(self, path: Path | str, *, days: int | None = None) -> None:
        self.path = Path(path)
        self._days = days
        self._local = threading.local()
        self._lock = threading.Lock()
        self._ready = False

    @property
    def days(self) -> int:
        if self._days is not None:
            return int(self._days)
        from ..core.config import settings

        return int(settings.device_token_days)

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
        conn.execute("PRAGMA secure_delete=ON")
        with self._lock:
            if not self._ready:
                if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
                            for statement in _SCHEMA:
                                conn.execute(statement)
                            conn.execute("PRAGMA user_version = 1")
                        conn.execute("COMMIT")
                    except BaseException:
                        conn.execute("ROLLBACK")
                        raise
                self._ready = True
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.chmod(f"{self.path}{suffix}", 0o600)
        self._local.conn = conn
        return conn

    def register(self, actor_id: int, token_version: int, *, name: str, platform: str, app_version: str,
                 now: float | None = None) -> tuple[str, str, int]:
        """-> (device_id, token, expires_at). Token FAQAT shu yerda ko'rinadi."""
        t = int(now if now is not None else time.time())
        token = new_token()
        device_id = uuid.uuid4().hex
        expires = t + self.days * 86400
        self._connect().execute(
            "INSERT INTO devices (id, token_hash, actor_id, token_version, device_name, platform, app_version, "
            "created_at, last_used_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (device_id, token_hash(token), int(actor_id), int(token_version), name[:80], platform[:16],
             app_version[:40], t, t, expires))
        return device_id, token, expires

    def lookup(self, token: str, now: float | None = None) -> tuple[dict[str, Any] | None, str]:
        """-> (qator, sabab). Sabab: `ok` | `unknown` | `revoked` | `expired`."""
        if not self.path.exists():
            # Ombor yo'q - token ham yo'q. Autentifikatsiyasiz so'rov fayl YARATMASIN.
            return None, "unknown"
        t = int(now if now is not None else time.time())
        found = self._connect().execute("SELECT * FROM devices WHERE token_hash=?",
                                        (token_hash(token),)).fetchone()
        if found is None:
            return None, "unknown"
        row = dict(found)
        if row.get("revoked_at"):
            return None, "revoked"
        if int(row["expires_at"]) <= t:
            return None, "expired"
        return row, "ok"

    def touch(self, device_id: str, now: float | None = None) -> int:
        """Sirpanuvchi muddat: oxirgi ishlatilgandan yana `days` kun."""
        t = int(now if now is not None else time.time())
        expires = t + self.days * 86400
        self._connect().execute("UPDATE devices SET last_used_at=?, expires_at=? WHERE id=? AND revoked_at IS NULL",
                                (t, expires, device_id))
        return expires

    def revoke(self, token: str, now: float | None = None) -> bool:
        if not self.path.exists():
            return False
        t = int(now if now is not None else time.time())
        return self._connect().execute("UPDATE devices SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                                       (t, token_hash(token))).rowcount == 1

    def purge(self, now: float | None = None) -> int:
        """Muddati o'tgan va bekor qilinganlar o'chiriladi. Fayl bo'lmasa - yaratilmaydi."""
        if not self.path.exists():
            return 0
        t = int(now if now is not None else time.time())
        return self._connect().execute("DELETE FROM devices WHERE expires_at <= ? OR revoked_at IS NOT NULL",
                                       (t,)).rowcount

    def rows(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._connect().execute("SELECT * FROM devices").fetchall()]

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            self._local.conn = None
            with contextlib.suppress(sqlite3.Error):
                conn.close()

"""ARXIV - Telegram va Slack orqali kelgan va yuborilgan, boshqa joyda saqlanmaydigan hamma narsa.

Ega talabi (2026-11-05): "telegram yoki slackdan kelgan har qanaqa ma'lumot saqlanishi kerak".
Boshqa joyda allaqachon saqlanadigani bu yerda TAKRORLANMAYDI:
    yig'ilish audiosi, matni, xulosasi, savol-javobi, bayonnomasi - `meetings` (audio ham)
    Telegram chatdagi savol va javob matni                       - `analytics` (`turns`)
    Telegram guruh xabarining matni (niqoblangan)                - `tg_groups`
Bu yerda - qolgani:
    in   Telegram ovozli savolining AUDIOSI (`runner._voice`); shaxsiy chat va ro'yxatdagi
         guruhlardagi rasm, fayl, ovoz, audio, video (`app/bot/media.py`); guruhdagi so'rov matni
         (/summary, @Barno - guruh omboriga yozilmaydi); Slack shaxsiy chatidagi matn va audio
         bo'lmagan fayllar (`app/slack/keep.py`; Slack audiosi - yig'ilish)
    out  odamga yuborilgan fayllar (bayonnoma, xulosa eksporti, assistent hujjati - Word/PDF/MD);
         guruh xulosasi va javobi, rahbariyat brifi (matn, yuborilgan ko'rinishida)

MATN chaqiruvchida niqoblanadi (`tg_groups.mask_text` - telefon, email, karta, tokenlar), guruh
matni kabi (ega qarori: "niqob qolsin"). Fayl o'zgarmaydi.

MUDDAT YO'Q - hech narsa o'chirilmaydi (`purge` yo'q). `max_bytes` dan katta fayl yozilmaydi:
qator `too_large` bilan qoladi (kim, qachon, nomi, hajmi).

JOYI: `settings.archive_dir` (`data/archive/`, gitignore'da): `archive.db` - indeks (600),
`files/YYYY/MM/<id><kengaytma>` - fayllar (600, papkalar 700).

ARXIV XATOSI ODAMGA TA'SIR QILMAYDI: `record` hech qachon xato otmaydi - yozilmasa jurnalda
ogohlantirish (mazmunsiz) va `None`; javob, xulosa va fayl yuborish davom etadi.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import mimetypes
import os
import re
import sqlite3
import stat
import threading
import time
import uuid

from pathlib import Path
from typing import Any

from ..core.config import settings

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    channel TEXT NOT NULL,
    direction TEXT NOT NULL,
    kind TEXT NOT NULL,
    chat_id TEXT,
    user_id TEXT,
    actor_id INTEGER,
    message_id TEXT,
    text TEXT,
    file_path TEXT,
    file_name TEXT,
    mime TEXT,
    size INTEGER,
    sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    meta TEXT
);
CREATE INDEX IF NOT EXISTS items_chat ON items(channel, chat_id, ts);
"""

_COLUMNS = ("id", "ts", "channel", "direction", "kind", "chat_id", "user_id", "actor_id", "message_id", "text",
            "file_path", "file_name", "mime", "size", "sha256", "status", "meta")

#: Kengaytma - fayl nomidan (faqat harf va raqam, 8 belgigacha) yoki turidan; bo'lmasa `.bin`.
_EXT = re.compile(r"\.([A-Za-z0-9]{1,8})$")
_DIR_MODE = stat.S_IRWXU
_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR


def _ext(name: str, mime: str) -> str:
    found = _EXT.search(name or "")
    if found:
        return "." + found.group(1).lower()
    guessed = mimetypes.guess_extension(mime.split(";")[0].strip()) if mime else None
    return guessed or ".bin"


def _ident(value: Any) -> str | None:
    """id lar (Telegram soni, Slack "D123" / "1730.123") matn sifatida; bo'sh - `None`."""
    if value is None or value == "":
        return None
    return str(value)[:64]


class Archive:
    """Ip-xavfsiz: har yozuv o'z ulanishini ochadi (`tg_groups.GroupStore` kabi)."""

    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self.root = Path(root)
        self.max_bytes = max(0, int(max_bytes))
        self._lock = threading.Lock()
        self._ready = False

    @property
    def db_path(self) -> Path:
        return self.root / "archive.db"

    def _dir(self, *parts: str) -> Path:
        """`root/parts...` - har bo'g'ini 700 (faqat arxiv ichida, yuqoridagi papkalarga tegmaydi)."""
        self.root.parent.mkdir(parents=True, exist_ok=True)
        path = self.root
        for part in ("", *parts):
            path = path / part if part else path
            path.mkdir(mode=_DIR_MODE, exist_ok=True)
            os.chmod(path, _DIR_MODE)
        return path

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            with self._lock:
                if not self._ready:
                    self._dir()
                    conn = sqlite3.connect(self.db_path, timeout=10)
                    try:
                        conn.executescript(_SCHEMA)
                        conn.commit()
                    finally:
                        conn.close()
                    os.chmod(self.db_path, _FILE_MODE)
                    self._ready = True
        return sqlite3.connect(self.db_path, timeout=10)

    def record(self, channel: str, direction: str, kind: str, *, chat: Any = None, user: Any = None,
               actor: int | None = None, message: Any = None, text: str | None = None,
               data: bytes | None = None, name: str = "", mime: str = "", size: int | None = None,
               status: str = "ok", meta: dict[str, Any] | None = None, now: float | None = None) -> str | None:
        """Bitta yozuv (va `data` bo'lsa - fayl) -> id; yozilmasa `None`, xato otmaydi."""
        item = uuid.uuid4().hex
        stamp = int(time.time() if now is None else now)
        written: Path | None = None
        try:
            relative = digest = None
            if data is not None:
                size = len(data)
                if size > self.max_bytes:
                    status = "too_large"
                else:
                    folder = self._dir("files", *time.strftime("%Y/%m", time.gmtime(stamp)).split("/"))
                    written = folder / f"{item}{_ext(name, mime)}"
                    temp = written.with_name(written.name + ".tmp")
                    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                    os.replace(temp, written)
                    relative = written.relative_to(self.root).as_posix()
                    digest = hashlib.sha256(data).hexdigest()
            row = (item, stamp, channel, direction, kind, _ident(chat), _ident(user),
                   actor if isinstance(actor, int) and not isinstance(actor, bool) else None, _ident(message),
                   text or None, relative, (name or "")[:255] or None, (mime or "")[:120] or None, size,
                   digest, status, json.dumps(meta, ensure_ascii=False, default=str) if meta else None)
            with contextlib.closing(self._connect()) as conn, conn:
                conn.execute(f"INSERT INTO items ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
                             row)
            return item
        except Exception as exc:  # noqa: BLE001 - arxiv xatosi asosiy ishni to'xtatmasin
            log.warning("Arxiv: %s/%s/%s yozilmadi (%s)", channel, direction, kind, type(exc).__name__)
            if written is not None:
                with contextlib.suppress(OSError):
                    written.unlink()
            return None

    def rows(self, *, channel: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Oxirgi yozuvlar, eskisi birinchi (sinov va tekshiruv uchun)."""
        if not self.db_path.exists():
            return []
        where, params = ("WHERE channel = ?", [channel]) if channel else ("", [])
        with contextlib.closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            found = conn.execute(f"SELECT * FROM items {where} ORDER BY ts DESC, rowid DESC LIMIT ?",
                                 [*params, int(limit)]).fetchall()
        return [dict(r) for r in reversed(found)]


_archive: Archive | None = None
_guard = threading.Lock()


def get() -> Archive:
    """Joriy sozlamalardagi arxiv: `archive_dir` o'zgarsa - yangisi (testlar har birida o'z papkasida)."""
    global _archive
    root = Path(settings.archive_dir)
    limit = max(0, int(settings.archive_max_file_mb)) * 1024 * 1024
    with _guard:
        if _archive is None or _archive.root != root or _archive.max_bytes != limit:
            _archive = Archive(root, max_bytes=limit)
        return _archive


def record(channel: str, direction: str, kind: str, **fields: Any) -> str | None:
    """`Archive.record` joriy arxivga. Xato otmaydi."""
    try:
        target = get()
    except Exception as exc:  # noqa: BLE001
        log.warning("Arxiv ochilmadi (%s)", type(exc).__name__)
        return None
    return target.record(channel, direction, kind, **fields)

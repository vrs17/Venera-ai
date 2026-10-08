"""Telegram guruh xabarlari ombori - guruh xulosasi uchun (`app/bot/groups.py`).

NEGA SAQLANADI. Bot API botga guruh TARIXINI bermaydi: bot faqat kelayotgan
xabarlarni ko'radi (guruhda administrator bo'lsa - hammasini). Ya'ni "oxirgi
3 kun xulosasi" uchun xabarlarni o'zimiz yozib borishimiz kerak. Xulosa
faqat guruh ro'yxatga (`telegram_groups`) qo'shilgandan KEYINGI xabarlarni
qamraydi.

NIMA SAQLANADI - faqat ro'yxatdagi guruhdan, faqat odamlarning xabarlari:
matn yoki izoh (telefon, email, karta, tokenlar NIQOBLANGAN - `mask_text`),
yuborgan odamning ismi va Telegram id si, javob qilingan xabar, mavzu
(forum). Rasm, fayl, ovozning O'ZI saqlanmaydi - faqat turi (`[rasm]`).
Forward qilingan xabar matni asl muallif nomi bilan saqlanadi
(`[forward: Ism, 06.10 17:50] matn`): uni guruh a'zosi guruhga O'ZI ulashgan -
guruhdagilar uni allaqachon ko'radi (2026-10-06 qarori; avval matnsiz edi).

QANCHA - `telegram_group_days` (90) kun, keyin o'chiriladi (`purge`).
`secure_delete`: o'chirilgan matn fayl ichida qolib ketmaydi.

SQLite (`data/telegram/groups.db`, gitignore'da, 600) - kontaktlar ombori
bilan bir xil yondashuv: alohida fayl, tahlil bazasiga tegmaydi.

RAHBARIYAT BRIFI (`app/bot/briefs.py`) shu faylda ikki jadval qo'shadi:
`chats` - guruh nomlari (menyu uchun) va `brief_events` - har guruhning har
kunidan ajratilgan hodisalar (kesh). Hodisalarda xabar mazmuni bor - ular
ham xabarlar bilan birga `days` kundan keyin o'chiriladi (`purge`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sqlite3
import stat
import threading
import time

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Tashkent")
#: Bitta xabar matni shundan uzun bo'lsa qisqartiriladi (Telegram chegarasi 4096).
TEXT_MAX = 4000
#: Ism shundan uzun bo'lsa qisqartiriladi.
NAME_MAX = 64
#: Eskilarni o'chirish shuncha vaqtda bir marta (xabar qo'shilganda).
_PURGE_EVERY = 3600.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    thread_id  INTEGER,
    date       INTEGER NOT NULL,
    from_id    INTEGER,
    from_name  TEXT NOT NULL DEFAULT '',
    username   TEXT,
    text       TEXT NOT NULL,
    reply_to   INTEGER,
    edited_at  INTEGER,
    orig_date  INTEGER,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS messages_chat_date ON messages (chat_id, date);
-- 2: guruh nomlari va rahbariyat brifi uchun ajratilgan hodisalar (`app/bot/briefs.py`).
CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS brief_events (
    chat_id    INTEGER NOT NULL,
    day        TEXT NOT NULL,
    marker     TEXT NOT NULL,
    version    TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    events     TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (chat_id, day)
);
PRAGMA user_version = 3;
"""
#: Forward belgisidagi asl vaqt: `[forward: Ism, 15.07 10:00]` (eski yozuvlar uchun).
_FWD_TIME = re.compile(r"^\[forward: [^\]]*?(\d{2})\.(\d{2}) (\d{2}):(\d{2})\]")
#: Belgidagi vaqt bo'lagi - yozishmani modelga berishda olib tashlanadi.
_FWD_STAMP = re.compile(r"^\[forward: ([^\]]*?),? ?\d{2}\.\d{2} \d{2}:\d{2}\]")
#: Toshkent = UTC+5, yozgi vaqt yo'q: kun chegarasi SQL da shu siljish bilan.
_DAY_SHIFT = 5 * 3600

# --- niqoblash ------------------------------------------------------------------

#: Har biri qator ICHIDA ishlaydi - qator uzilishlari saqlanadi (xulosa uchun
#: kerak). `analytics.redact` bunga to'g'ri kelmaydi: u bo'shliqlarni yig'adi.
_MASKS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Tokenlar va kalitlar (`analytics/meter.py` dagi shakllar).
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+"), "Bearer <token>"),
    (re.compile(r"eyJ[\w-]{8,}(?:\.[\w-]+){0,2}"), "<token>"),
    (re.compile(r"\b\d{5,}:[\w-]{30,}"), "<token>"),
    (re.compile(r"\b[0-9a-f]{32}\.[\w-]{16,}"), "<key>"),
    (re.compile(r"(?i)\b((?:parol|пароль|password|passwd|token|secret|api[_-]?key)\s*[:=]\s*)\S+"),
     r"\1***"),
    # Email.
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}"), "<email>"),
    # Karta raqami: 16 raqam, guruhlab yoki yaxlit.
    (re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"), "<karta>"),
    # Telefon: +998 bilan har qanday shaklda; usiz - faqat ajratilgan shaklda
    # (`90 123 45 67`, `(90) 123-45-67`), aks holda har 9 xonali son
    # (buyurtma raqami) telefon bo'lib qolardi.
    (re.compile(r"(?<![\w+])\+?998[\s-]?\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"), "<telefon>"),
    (re.compile(r"(?<![\w+])\(?\d{2}\)?[\s-]\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"), "<telefon>"),
)


def mask_text(text: str) -> str:
    """Telefon, email, karta va tokenlarni niqoblaydi, qatorlarni saqlaydi."""
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


# --- xabar -> yozuv --------------------------------------------------------------


def sender_name(user: dict[str, Any]) -> str:
    """Telegram ismi (`first_name last_name`), bo'lmasa `@username`."""
    name = " ".join(str(user.get(k) or "").strip() for k in ("first_name", "last_name")).strip()
    if not name and user.get("username"):
        name = "@" + str(user["username"])
    name = " ".join(name.split())
    return name[:NAME_MAX] or "Noma'lum"


def message_text(msg: dict[str, Any]) -> str:
    """Saqlanadigan matn: matn yoki izoh, oldida turi (`[rasm]`, `[fayl: x.pdf]`).

    Bo'sh satr - saqlanmaydi (stiker, xizmat xabari va h.k.). Forward -
    asl muallif va vaqti bilan: model mazmunni o'sha odamga nisbat beradi.
    """
    body = str(msg.get("text") or msg.get("caption") or "").strip()
    kind = ""
    if "photo" in msg:
        kind = "[rasm]"
    elif isinstance(msg.get("document"), dict):
        name = str(msg["document"].get("file_name") or "").strip()[:80]
        kind = f"[fayl: {name}]" if name else "[fayl]"
    elif "voice" in msg:
        kind = "[ovozli xabar]"
    elif "video" in msg or "video_note" in msg:
        kind = "[video]"
    elif "audio" in msg:
        kind = "[audio]"
    elif isinstance(msg.get("poll"), dict):
        kind = "[so'rovnoma]"
        body = str(msg["poll"].get("question") or "").strip()
    origin = msg.get("forward_origin")
    if isinstance(origin, dict):
        kind = " ".join(filter(None, (_forward_label(origin), kind)))
    text = f"{kind} {body}".strip() if kind else body
    return mask_text(text)[:TEXT_MAX]


def _forward_label(origin: dict[str, Any]) -> str:
    """`[forward: Ism, 06.10 17:50]` - asl muallif (odam, yashirin odam,
    guruh yoki kanal) va asl xabar vaqti, ma'lum bo'lsa."""
    kind = origin.get("type")
    if kind == "user" and isinstance(origin.get("sender_user"), dict):
        who = sender_name(origin["sender_user"])
    elif kind == "hidden_user":
        who = " ".join(str(origin.get("sender_user_name") or "").split())
    else:
        chat = origin.get("chat") if kind == "channel" else origin.get("sender_chat")
        who = " ".join(str((chat or {}).get("title") or "").split())
    parts = [who[:60]] if who else []
    if isinstance(origin.get("date"), int):
        parts.append(datetime.fromtimestamp(origin["date"], _TZ).strftime("%d.%m %H:%M"))
    return f"[forward: {', '.join(parts)}]" if parts else "[forward]"


def strip_forward_time(text: str) -> str:
    """`[forward: Ism, 15.07 10:00] matn` -> `[forward: Ism] matn`.

    Forward qilingan xabar guruhga TUSHGAN vaqti bilan o'qiladi (2026-10-08
    qarori): asl vaqt modelga berilmaydi - "ertaga" ham, hodisa kuni ham
    guruhdagi vaqtdan. Saqlangan matn o'zgarmaydi."""
    return _FWD_STAMP.sub(lambda m: f"[forward: {m.group(1)}]" if m.group(1) else "[forward]", text, count=1)


@dataclass(frozen=True)
class Row:
    message_id: int
    thread_id: int | None
    date: int
    from_id: int | None
    from_name: str
    username: str | None
    text: str
    reply_to: int | None
    #: Forward bo'lsa - xabar ASLIDA yozilgan vaqt (`forward_origin.date`).
    #: Saqlanadi, lekin hozir ishlatilmaydi: guruh xulosasi ham, rahbariyat
    #: brifi ham xabarni guruhga TUSHGAN vaqti (`date`) bilan sanaydi.
    orig_date: int | None = None


# --- ombor -------------------------------------------------------------------------


def _origin_epoch(match: re.Match[str], posted: int) -> int | None:
    """`dd.mm HH:MM` (yilsiz) -> vaqt: guruhga tushgan vaqtdan oldingi eng yaqin sana."""
    day, month, hour, minute = (int(g) for g in match.groups())
    year = datetime.fromtimestamp(posted, _TZ).year
    for candidate in (year, year - 1):
        try:
            value = int(datetime(candidate, month, day, hour, minute, tzinfo=_TZ).timestamp())
        except ValueError:
            continue
        if value <= posted + 60:
            return value
    return None


def _backfill_orig(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT chat_id, message_id, date, text FROM messages"
                        " WHERE text LIKE '[forward:%'").fetchall()
    for chat_id, message_id, date, text in rows:
        match = _FWD_TIME.match(text)
        value = _origin_epoch(match, date) if match else None
        if value is not None:
            conn.execute("UPDATE messages SET orig_date = ? WHERE chat_id = ? AND message_id = ?",
                         (value, chat_id, message_id))


class GroupStore:
    """Guruh xabarlari. Ip-xavfsiz: har chaqiruv o'z ulanishini ochadi."""

    def __init__(self, path: Path, *, days: int = 90) -> None:
        self.path = Path(path)
        self.days = days if 1 <= days <= 365 else 90
        self._lock = threading.Lock()
        self._ready = False
        self._purged_at = 0.0

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            with self._lock:
                if not self._ready:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(self.path, timeout=10)
                    try:
                        columns = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
                        if columns and "orig_date" not in columns:
                            # 3: forward'ning asl vaqti. Eski yozuvlar - belgidagi sanadan.
                            conn.execute("ALTER TABLE messages ADD COLUMN orig_date INTEGER")
                            _backfill_orig(conn)
                        conn.executescript(_SCHEMA)
                        conn.commit()
                    finally:
                        conn.close()
                    # Ish yozishmalari: faqat egasi o'qiy oladi.
                    os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
                    self._ready = True
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA secure_delete = ON")
        return conn

    @contextlib.contextmanager
    def _tx(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add(self, msg: dict[str, Any]) -> bool:
        """Xabarni yozadi. Takror kelgani (qayta ishga tushganda) e'tiborsiz.
        Natija: yozildimi."""
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        if not isinstance(chat_id, int) or not isinstance(message_id, int) or message_id <= 0:
            return False
        title = " ".join(str((msg.get("chat") or {}).get("title") or "").split())[:NAME_MAX * 2]
        text = message_text(msg)
        if not text:
            if title:
                with self._tx() as conn:
                    self._title(conn, chat_id, title)
            return False
        sender = msg.get("from") or {}
        reply = msg.get("reply_to_message")
        reply_to = reply.get("message_id") if isinstance(reply, dict) else None
        thread_id = msg.get("message_thread_id") if msg.get("is_topic_message") else None
        if isinstance(reply_to, int) and reply_to == thread_id:
            # Mavzuning o'ziga "javob" - bu oddiy xabar, javob emas.
            reply_to = None
        date = msg.get("date") if isinstance(msg.get("date"), int) else int(time.time())
        origin = msg.get("forward_origin")
        orig_date = origin.get("date") if isinstance(origin, dict) and isinstance(origin.get("date"), int) else None
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO messages (chat_id, message_id, thread_id, date, from_id,"
                " from_name, username, text, reply_to, orig_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, message_id, thread_id if isinstance(thread_id, int) else None, date,
                 sender.get("id") if isinstance(sender.get("id"), int) else None,
                 sender_name(sender), str(sender.get("username") or "")[:NAME_MAX] or None,
                 text, reply_to if isinstance(reply_to, int) else None, orig_date),
            )
            added = cur.rowcount > 0
            if title:
                self._title(conn, chat_id, title)
        self._maybe_purge()
        return added

    @staticmethod
    def _title(conn: sqlite3.Connection, chat_id: int, title: str) -> None:
        """Guruh nomi (brif menyusi uchun) - faqat o'zgarganda yoziladi."""
        conn.execute(
            "INSERT INTO chats (chat_id, title, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at"
            " WHERE chats.title IS NOT excluded.title",
            (chat_id, title, int(time.time())))

    def titles(self, chat_ids: Any) -> dict[int, str]:
        """Guruh nomlari; noma'lumi - yo'q (chaqiruvchi zaxira nom qo'yadi)."""
        ids = [c for c in chat_ids if isinstance(c, int)]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self._tx() as conn:
            rows = conn.execute(f"SELECT chat_id, title FROM chats WHERE chat_id IN ({marks})", ids)
            return {chat_id: title for chat_id, title in rows}

    def day_markers(self, chat_id: int, since: float, until: float) -> dict[str, str]:
        """Toshkent kuni (`YYYY-MM-DD`) -> belgi `soni:max_id:max_tahrir`. Belgi
        o'zgarsa - o'sha kun xabarlari o'zgargan (yangi xabar yoki tahrir)."""
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT date(date + ?, 'unixepoch') AS day, COUNT(*), MAX(message_id),"
                " COALESCE(MAX(edited_at), 0) FROM messages"
                " WHERE chat_id = ? AND date >= ? AND date < ? GROUP BY day",
                (_DAY_SHIFT, chat_id, int(since), int(until))).fetchall()
        return {day: f"{count}:{top}:{edited}" for day, count, top, edited in rows}

    def get_events(self, chat_id: int, days: Any) -> dict[str, dict[str, Any]]:
        """Saqlangan hodisalar: kun -> {marker, version, status, created_at, events}."""
        wanted = [d for d in days if isinstance(d, str)]
        if not wanted:
            return {}
        marks = ",".join("?" * len(wanted))
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT day, marker, version, status, created_at, events FROM brief_events"
                f" WHERE chat_id = ? AND day IN ({marks})", [chat_id, *wanted]).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for day, marker, version, status, created_at, events in rows:
            try:
                parsed = json.loads(events)
            except ValueError:
                parsed = []
            out[day] = {"marker": marker, "version": version, "status": status,
                        "created_at": created_at, "events": parsed if isinstance(parsed, list) else []}
        return out

    def put_events(self, chat_id: int, day: str, *, marker: str, version: str, status: str,
                   events: list[dict[str, Any]], created_at: float | None = None) -> None:
        """`created_at` - chaqiruvchining soati (brif dvigateli o'z soati bilan
        "yangimi" deb solishtiradi)."""
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO brief_events (chat_id, day, marker, version, status,"
                " created_at, events) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, day, marker, version, status, int(time.time() if created_at is None else created_at),
                 json.dumps(events, ensure_ascii=False)))

    def edit(self, msg: dict[str, Any]) -> bool:
        """Tahrirlangan xabar - yangi matn. Saqlanmagan xabar qo'shilmaydi."""
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        if not isinstance(chat_id, int) or not isinstance(message_id, int):
            return False
        text = message_text(msg)
        if not text:
            return False
        edited = msg.get("edit_date") if isinstance(msg.get("edit_date"), int) else int(time.time())
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE messages SET text = ?, edited_at = ? WHERE chat_id = ? AND message_id = ?",
                (text, edited, chat_id, message_id))
            return cur.rowcount > 0

    def window(self, chat_id: int, since: float, until: float, *,
               thread_id: int | None = None, limit: int = 3000) -> list[Row]:
        """`[since, until)` dagi xabarlar, eskidan yangiga. `limit` dan ko'p
        bo'lsa - ENG YANGILARI. `thread_id` - faqat shu mavzu (forum)."""
        sql = ("SELECT message_id, thread_id, date, from_id, from_name, username, text, reply_to, orig_date"
               " FROM messages WHERE chat_id = ? AND date >= ? AND date < ?")
        args: list[Any] = [chat_id, int(since), int(until)]
        if thread_id is not None:
            sql += " AND thread_id = ?"
            args.append(thread_id)
        sql += " ORDER BY date DESC, message_id DESC LIMIT ?"
        args.append(limit)
        with self._tx() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [Row(*row) for row in reversed(rows)]

    def first_date(self, chat_id: int) -> int | None:
        """Shu guruhdan saqlangan eng eski xabar vaqti."""
        with self._tx() as conn:
            (value,) = conn.execute("SELECT MIN(date) FROM messages WHERE chat_id = ?",
                                    (chat_id,)).fetchone()
        return value

    def count_between(self, chat_id: int, since: float, until: float) -> int:
        """Shu guruhning `[since, until)` dagi xabarlari soni (brif statistikasi).
        Forward - guruhga tushgan vaqti bilan, hodisalar kabi."""
        with self._tx() as conn:
            (value,) = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?"
                                    " AND date >= ? AND date < ?",
                                    (chat_id, int(since), int(until))).fetchone()
        return int(value)

    def count(self) -> int:
        with self._tx() as conn:
            (value,) = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return int(value)

    def purge(self, now: float | None = None) -> int:
        """`days` kundan eski xabarlarni o'chiradi. Natija: nechta."""
        cutoff = int((time.time() if now is None else now) - self.days * 86400)
        cutoff_day = time.strftime("%Y-%m-%d", time.gmtime(cutoff + _DAY_SHIFT))
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM messages WHERE date < ?", (cutoff,))
            # Brif hodisalari ham xabarlar bilan birga ketadi (ichida xabar mazmuni bor).
            conn.execute("DELETE FROM brief_events WHERE day < ?", (cutoff_day,))
            return cur.rowcount

    def _maybe_purge(self) -> None:
        now = time.monotonic()
        if self._purged_at and now - self._purged_at < _PURGE_EVERY:
            return
        self._purged_at = now
        try:
            removed = self.purge()
        except sqlite3.Error as exc:
            log.warning("Guruh xabarlari: eskilari o'chirilmadi: %s", exc)
            return
        if removed:
            log.info("Guruh xabarlari: %d ta eski xabar o'chirildi", removed)

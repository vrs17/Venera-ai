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

QANCHA - `telegram_group_days` (90) kun, keyin o'chiriladi (`purge`). 0 - muddat bo'yicha
o'chirilmaydi (2026-11-05 ega qarori: hech narsa o'chmasin); xulosa va savol davri baribir
`WINDOW_DAYS` dan oshmaydi. Rasm, fayl, ovozning o'zi - arxivda (`app/bot/media.py`).
`secure_delete`: o'chirilgan matn fayl ichida qolib ketmaydi.

SQLite (`data/telegram/groups.db`, gitignore'da, 600) - kontaktlar ombori
bilan bir xil yondashuv: alohida fayl, tahlil bazasiga tegmaydi.

RAHBARIYAT BRIFI (`app/bot/briefs.py`) shu faylda ikki jadval qo'shadi:
`chats` - guruh nomlari (menyu uchun) va `brief_events` - har guruhning har
kunidan ajratilgan hodisalar (kesh). Hodisalarda xabar mazmuni bor - ular
ham xabarlar bilan birga `days` kundan keyin o'chiriladi (`purge`).

GURUHLAR RO'YXATI (`groups` jadvali, `GroupRegistry`) - qaysi guruhni Venera
o'qiydi va guruh turi (support / loyiha). Rahbar uni botning o'zida
boshqaradi (`app/bot/group_admin.py`); `.env` dagi `TELEGRAM_GROUPS` ham
ishlayveradi - qoida `_effective` da.

GURUHDAGI CRM HOLATI (`crm_chats`, `crm_messages`, `GroupCrmState`, 2026-10-10) -
`app/bot/group_actions.py` uchun. NEGA DISKDA: avval faqat xotirada edi - API qayta
ishga tushsa kutayotgan tasdiq tugmalari "eskirgan" bo'lib qolardi, agentdagi
suhbatlar (ichida guruhdagi BOSHQA odamlarning xabarlari bor) esa hech qayerda
yozilmagani uchun o'chirilmasdi. Endi har agent suhbati (`chat_id`) guruhga bog'lab
yoziladi va agentda o'chiriladi: muddati (`IDLE`) tugaganda, guruh ro'yxatdan
olib tashlanganda va saqlash muddati (`days`) o'tganda. Xabar MATNI bu jadvallarda
YO'Q - faqat id, vaqt va so'ragan odam ismi.
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
import uuid

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..core.config import telegram_groups_now

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
-- 4: guruhlar ro'yxati - rahbariyat botda boshqaradi (`GroupRegistry`).
CREATE TABLE IF NOT EXISTS groups (
    chat_id     INTEGER PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'pending',
    kind        TEXT,
    chat_type   TEXT,
    bot_status  TEXT,
    can_pin     INTEGER,
    added_tg    INTEGER,
    owner_tg    INTEGER,
    decided_by  INTEGER,
    decided_at  INTEGER,
    notice_id   INTEGER,
    asked_at    INTEGER,
    migrated_to INTEGER,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS groups_state ON groups (state);
-- 5: guruhdagi CRM (`GroupCrmState`): agentdagi suhbatlar va Venera'ning CRM xabarlari egasi.
-- Matn yo'q - faqat id va vaqt: suhbatning o'zi agentda turadi va shu yerdan o'chiriladi.
CREATE TABLE IF NOT EXISTS crm_chats (
    conversation TEXT PRIMARY KEY,
    chat_id      INTEGER NOT NULL,
    actor_id     INTEGER NOT NULL,
    user_id      TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    last_at      INTEGER NOT NULL,
    closed_at    INTEGER,
    deleted_at   INTEGER,
    attempts     INTEGER NOT NULL DEFAULT 0,
    -- Agentda o'chirilmagan suhbat qachon qayta urinadi (bo'sh - darhol). NEGA: bitta
    -- "zaharli" suhbat (doim 4xx) navbat boshida turib qolib, qolganlarini to'smasin.
    next_at      INTEGER
);
CREATE INDEX IF NOT EXISTS crm_chats_owner ON crm_chats (chat_id, actor_id, last_at);
CREATE INDEX IF NOT EXISTS crm_chats_pending ON crm_chats (deleted_at, last_at);
CREATE TABLE IF NOT EXISTS crm_messages (
    chat_id      INTEGER NOT NULL,
    message_id   INTEGER NOT NULL,
    conversation TEXT NOT NULL,
    actor_id     INTEGER NOT NULL,
    tg_id        INTEGER NOT NULL,
    name         TEXT NOT NULL,
    token        TEXT,
    created_at   INTEGER NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS crm_messages_token ON crm_messages (token);
PRAGMA user_version = 5;
"""
#: Forward belgisidagi asl vaqt: `[forward: Ism, 15.07 10:00]` (eski yozuvlar uchun).
_FWD_TIME = re.compile(r"^\[forward: [^\]]*?(\d{2})\.(\d{2}) (\d{2}):(\d{2})\]")
#: Belgidagi vaqt bo'lagi - yozishmani modelga berishda olib tashlanadi.
_FWD_STAMP = re.compile(r"^\[forward: ([^\]]*?),? ?\d{2}\.\d{2} \d{2}:\d{2}\]")
#: Toshkent = UTC+5, yozgi vaqt yo'q: kun chegarasi SQL da shu siljish bilan.
_DAY_SHIFT = 5 * 3600

# --- niqoblash ------------------------------------------------------------------

def _intl_phone(match: re.Match[str]) -> str:
    """`+7 916 123-45-67`, `+44 20 7946 0958` - faqat 8 va undan ko'p raqam bo'lsa
    telefon (`+15 %` kabi qisqa son o'z holicha qoladi)."""
    found = match.group(0)
    return "<telefon>" if sum(ch.isdigit() for ch in found) >= 8 else found


#: Faqat SIRLAR: tokenlar, kalitlar, `parol: ...`. Guruhda CRM so'ragan odamning O'Z
#: so'rovi shu bilan o'tadi (`group_actions._question`): telefon va email esa CRM
#: vazifasi uchun kerak bo'lishi mumkin ("mijozga qo'ng'iroq qil: +998...") - ularni
#: niqoblash egasining mahsulot qarori.
_SECRET_MASKS: tuple[tuple[re.Pattern[str], Any], ...] = (
    # Tokenlar va kalitlar (`analytics/meter.py` dagi shakllar).
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+"), "Bearer <token>"),
    (re.compile(r"eyJ[\w-]{8,}(?:\.[\w-]+){0,2}"), "<token>"),
    (re.compile(r"\b\d{5,}:[\w-]{30,}"), "<token>"),
    (re.compile(r"\b[0-9a-f]{32}\.[\w-]{16,}"), "<key>"),
    (re.compile(r"(?i)\b((?:parol|пароль|password|passwd|token|secret|api[_-]?key)\s*[:=]\s*)\S+"),
     r"\1***"),
)

#: Har biri qator ICHIDA ishlaydi - qator uzilishlari saqlanadi (xulosa uchun
#: kerak). `analytics.redact` bunga to'g'ri kelmaydi: u bo'shliqlarni yig'adi.
#: Faqat QO'SHILADI (2026-10-10, sharh): xalqaro raqam, nuqtali telefon, JSHSHIR
#: (PINFL) va pasport - avval ular niqobsiz o'tardi.
_MASKS: tuple[tuple[re.Pattern[str], Any], ...] = _SECRET_MASKS + (
    # Email.
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}"), "<email>"),
    # Karta raqami: 16 raqam, guruhlab yoki yaxlit.
    (re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"), "<karta>"),
    # JSHSHIR (PINFL): 14 raqam, birinchisi 3-6 (jins va asr). Kartadan KEYIN - 16 lik
    # karta ichidan 14 talik bo'lak olinmasin.
    (re.compile(r"(?<!\w)[3-6]\d{13}(?!\w)"), "<jshshir>"),
    # Pasport / ID karta: `AA1234567`, `AD 1234567`.
    (re.compile(r"(?<!\w)[A-Z]{2} ?\d{7}(?!\w)"), "<pasport>"),
    # Telefon: +998 bilan har qanday shaklda (bo'shliq, chiziq yoki nuqta bilan); usiz -
    # faqat ajratilgan shaklda (`90 123 45 67`, `(90) 123-45-67`, `90.123.45.67`), aks
    # holda har 9 xonali son (buyurtma raqami) telefon bo'lib qolardi.
    (re.compile(r"(?<![\w+])\+?998[\s.-]?\(?\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)"), "<telefon>"),
    # Boshqa davlat raqami: `+` va mamlakat kodi bilan (`+7 916 123-45-67`) - usiz shakldan OLDIN,
    # aks holda `+49 30 1234567` ning dumi mahalliy raqam bo'lib, `+49` ochiq qolardi.
    (re.compile(r"(?<![\w+])\+\d{1,3}(?:[\s.-]?\(?\d{2,4}\)?){2,6}(?!\d)"), _intl_phone),
    (re.compile(r"(?<![\w+])\(?\d{2}\)?[\s-]\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"), "<telefon>"),
    (re.compile(r"(?<![\w+.])\(?\d{2}\)?\.\d{3}\.\d{2}\.\d{2}(?!\.?\d)"), "<telefon>"),
)


def _mask_kind(replacement: Any) -> str:
    """Qoida nomi - admin sinovi uchun (`<email>`, `<telefon>`, `parol`...)."""
    if callable(replacement):
        return "<telefon>"
    return "parol" if "***" in str(replacement) else str(replacement)


def _apply_masks(text: str, masks: tuple[tuple[re.Pattern[str], Any], ...],
                 fired: dict[str, int] | None) -> str:
    """Qoidalar ketma-ket (tartib muhim - `_MASKS` izohi). `fired` berilsa - qaysi qoida
    necha marta ishlagani yoziladi (admin "Tizim xaritasi" sinovi: AYNI qoidalar, nusxa emas).

    Faqat matnni HAQIQATAN o'zgartirgan moslik sanaladi: `_intl_phone` qisqa sonni
    (`+12 34 56`) o'z holicha qaytaradi - u "niqoblandi" deb ko'rsatilmasin."""
    for pattern, replacement in masks:
        if fired is None:
            text = pattern.sub(replacement, text)
            continue
        kind = _mask_kind(replacement)

        def counted(match: re.Match[str], replacement: Any = replacement, kind: str = kind) -> str:
            out = replacement(match) if callable(replacement) else match.expand(replacement)
            if out != match.group(0):
                fired[kind] = fired.get(kind, 0) + 1
            return out

        text = pattern.sub(counted, text)
    return text


def mask_text(text: str, fired: dict[str, int] | None = None) -> str:
    """Telefon, email, karta, JSHSHIR, pasport va tokenlarni niqoblaydi, qatorlarni saqlaydi."""
    return _apply_masks(text, _MASKS, fired)


def mask_secrets(text: str, fired: dict[str, int] | None = None) -> str:
    """Faqat tokenlar, kalitlar va parollar (`_SECRET_MASKS`) - telefon va email qoladi."""
    return _apply_masks(text, _SECRET_MASKS, fired)


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
        # 0 - muddatsiz (o'chirilmaydi); 1-365 - kun; boshqasi - default.
        self.days = days if 0 <= days <= 365 else 90
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
                        crm = {r[1] for r in conn.execute("PRAGMA table_info(crm_chats)")}
                        if crm and "next_at" not in crm:
                            # 5 ning dastlabki shakli (sinov omborlari): qayta urinish vaqti ustuni.
                            conn.execute("ALTER TABLE crm_chats ADD COLUMN next_at INTEGER")
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

    def set_title(self, chat_id: int, title: str) -> None:
        """Guruh nomi - xabarsiz manbadan (bot qo'shilganda, `getChat`)."""
        title = " ".join(str(title or "").split())[:NAME_MAX * 2]
        if title:
            with self._tx() as conn:
                self._title(conn, chat_id, title)

    def chat_stats(self, chat_id: int) -> tuple[int, int | None]:
        """Shu guruhdan saqlangan xabarlar soni va eng eskisi vaqti (guruh kartasi uchun)."""
        with self._tx() as conn:
            count, first = conn.execute("SELECT COUNT(*), MIN(date) FROM messages WHERE chat_id = ?",
                                        (chat_id,)).fetchone()
        return int(count), first

    @staticmethod
    def _delete_chat(conn: sqlite3.Connection, chat_id: int) -> int:
        """Guruhning BARCHA saqlangan ma'lumoti: xabarlar, brif keshi, nomi.

        Guruhdagi CRM: tugma egalari o'chadi (tugma - "eskirgan"), agentdagi
        suhbatlar "yopiladi" - ularni agentda `GroupActions.sweep` o'chiradi
        (tarmoq chaqiruvi tranzaksiya ichida bo'lmasin)."""
        removed = conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,)).rowcount
        conn.execute("DELETE FROM brief_events WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
        _close_crm(conn, chat_id)
        return removed

    @staticmethod
    def _move_chat(conn: sqlite3.Connection, old: int, new: int) -> int:
        """Guruh supergroup'ga aylandi - tarix yangi id ga o'tadi.

        Xabar raqami MANFIY bo'ladi (`raqam - eng_katta - 1`): oddiy guruh
        raqamlari botning umumiy hisoblagichidan, supergroup'niki esa 1 dan
        boshlanadi - to'qnashsa yangi xabar jimgina tashlanardi (`INSERT OR
        IGNORE`). Siljitish tartibni saqlaydi (bir soniyadagi xabarlar ham).
        Javob qilingan xabar ham shunday. Brif keshi tashlanadi - kunlar
        qayta ajratiladi."""
        (top,) = conn.execute("SELECT MAX(message_id) FROM messages WHERE chat_id = ?", (old,)).fetchone()
        shift = (top or 0) + 1
        moved = conn.execute(
            "INSERT OR IGNORE INTO messages (chat_id, message_id, thread_id, date, from_id, from_name,"
            " username, text, reply_to, edited_at, orig_date)"
            " SELECT ?, CASE WHEN message_id > 0 THEN message_id - ? ELSE message_id END, thread_id, date,"
            " from_id, from_name, username, text,"
            " CASE WHEN reply_to > 0 THEN reply_to - ? ELSE reply_to END, edited_at, orig_date"
            " FROM messages WHERE chat_id = ?", (new, shift, shift, old)).rowcount
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (old,))
        conn.execute("DELETE FROM brief_events WHERE chat_id IN (?, ?)", (old, new))
        conn.execute("INSERT OR IGNORE INTO chats (chat_id, title, updated_at)"
                     " SELECT ?, title, updated_at FROM chats WHERE chat_id = ?", (new, old))
        conn.execute("DELETE FROM chats WHERE chat_id = ?", (old,))
        # Eski id dagi CRM suhbatlari davom etmaydi (eski guruh endi o'qilmaydi) - agentda
        # o'chiriladi; yangi id da so'rov yangi suhbat ochadi.
        _close_crm(conn, old)
        return moved

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

    @property
    def window_days(self) -> int:
        """Xulosa va savol davrining chegarasi: saqlash muddati, muddatsiz bo'lsa - `WINDOW_DAYS`."""
        return self.days or WINDOW_DAYS

    def purge(self, now: float | None = None) -> int:
        """`days` kundan eski xabarlarni o'chiradi (`days == 0` - muddat bo'yicha hech narsa
        o'chmaydi; o'chirilgan guruhniki va texnik izlar - baribir). Natija: nechta."""
        now = time.time() if now is None else now
        aged = self.days > 0
        cutoff = int(now - self.days * 86400)
        cutoff_day = time.strftime("%Y-%m-%d", time.gmtime(cutoff + _DAY_SHIFT))
        with self._tx() as conn:
            deleted = 0
            if aged:
                deleted = conn.execute("DELETE FROM messages WHERE date < ?", (cutoff,)).rowcount
                # Brif hodisalari ham xabarlar bilan birga ketadi (ichida xabar mazmuni bor).
                conn.execute("DELETE FROM brief_events WHERE day < ?", (cutoff_day,))
            # O'chirilgan va boshqa id ga o'tgan guruhlar: o'chirish bilan bir
            # paytda kelib qolgan xabar (ip poygasi) ham qolib ketmasin.
            gone = "SELECT chat_id FROM groups WHERE state IN ('removed', 'migrated')"
            conn.execute(f"DELETE FROM messages WHERE chat_id IN ({gone})")
            conn.execute(f"DELETE FROM brief_events WHERE chat_id IN ({gone})")
            # Guruhdagi CRM ham shu saqlash muddatiga bo'ysunadi: agentdagi suhbat ichida
            # guruh xabarlari bor - muddatdan eskisi (yoki o'chirilgan guruhniki) agentda
            # o'chiriladi (`GroupActions.sweep`); o'chirilganining izi ham muddatdan keyin
            # ketadi. Tugma egalari - `CRM_MESSAGE_TTL` dan keyin.
            stamp = int(now)
            if aged:
                conn.execute("UPDATE crm_chats SET closed_at = ? WHERE closed_at IS NULL AND deleted_at IS NULL"
                             " AND created_at < ?", (stamp, cutoff))
            conn.execute(f"UPDATE crm_chats SET closed_at = ? WHERE closed_at IS NULL AND chat_id IN ({gone})",
                         (stamp,))
            if aged:
                conn.execute("DELETE FROM crm_chats WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))
            conn.execute("DELETE FROM crm_messages WHERE created_at < ?", (int(now - CRM_MESSAGE_TTL),))
            conn.execute(f"DELETE FROM crm_messages WHERE chat_id IN ({gone})")
            # Hech kim qaror qilmagan "kutilayotgan" guruh - ro'yxatdan tushadi.
            conn.execute("DELETE FROM groups WHERE state = 'pending' AND decided_by IS NULL AND kind IS NULL"
                         " AND updated_at < ?", (int(now - PENDING_DAYS * 86400),))
            return deleted

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


# --- guruhlar ro'yxati ------------------------------------------------------------------

#: Guruh turi - rahbariyat brifi ko'rinishi (`app/bot/briefs.py`).
KINDS = ("support", "project")
#: Bot guruhda emas: chiqarib yuborilgan yoki o'zi chiqqan.
GONE = frozenset({"left", "kicked"})
#: Hech kim qaror qilmagan "kutilayotgan" guruhlar chegarasi - begona odam botni
#: yuzlab guruhga qo'shib rahbar ro'yxatini to'ldira olmasin.
PENDING_MAX = 100
#: Shuncha kun qaror qilinmagan "kutilayotgan" guruh ro'yxatdan tushadi (`purge`).
PENDING_DAYS = 30
#: Muddatsiz saqlashda (`days == 0`) xulosa va savol davrining eng uzuni - model bir so'rovda
#: cheksiz yozishmani o'qimasin.
WINDOW_DAYS = 365

_FIELDS = ("chat_id", "state", "kind", "chat_type", "bot_status", "can_pin", "added_tg", "owner_tg",
           "decided_by", "decided_at", "notice_id", "asked_at", "migrated_to", "created_at", "updated_at")
_SELECT = f"SELECT {', '.join(_FIELDS)} FROM groups"


@dataclass(frozen=True)
class GroupInfo:
    """Bitta guruh: ro'yxatdagi qatori (bo'lmasa - faqat `.env` dan) va
    Venera uni hozir o'qiydimi (`effective`)."""

    chat_id: int
    title: str
    #: pending | active | paused | removed | migrated
    state: str
    kind: str | None
    chat_type: str | None
    #: Telegram'dagi holati: creator | administrator | member | restricted | left | kicked | None
    bot_status: str | None
    can_pin: bool | None
    from_env: bool
    effective: bool
    added_tg: int | None = None
    owner_tg: int | None = None
    decided_by: int | None = None
    notice_id: int | None = None
    asked_at: int | None = None
    migrated_to: int | None = None

    @property
    def present(self) -> bool:
        """Bot guruhdami (noma'lum - bor deb olinadi)."""
        return self.bot_status not in GONE

    @property
    def adopted(self) -> bool:
        """Rahbar qaror qilgan - endi `.env` emas, bot boshqaradi."""
        return self.decided_by is not None


def _effective(row: Mapping[str, Any] | None, in_env: bool) -> bool:
    """Venera shu guruhni o'qiydimi - BITTA qoida:

    * bot guruhda bo'lishi kerak (`left`/`kicked` - yo'q);
    * rahbar yoqgan (`active`) - ha; to'xtatgan, o'chirgan - yo'q;
    * qaror yo'q (qator yo'q yoki `pending` va `decided_by` bo'sh) - `.env`
      dagi `TELEGRAM_GROUPS` hal qiladi. Ya'ni qatorlar bo'lmasa ro'yxat
      aynan `.env` - mavjud guruhlar hech narsa qilmasdan ishlayveradi.
    """
    if row is None:
        return in_env
    if row["bot_status"] in GONE:
        return False
    if row["state"] == "active":
        return True
    return row["state"] == "pending" and row["decided_by"] is None and in_env


class GroupRegistry:
    """Venera o'qiydigan guruhlar va ularning turi.

    Ikki manba: `.env` (`TELEGRAM_GROUPS`, jonli) va rahbar botda qilgan
    qarorlar (`groups` jadvali). Rahbar guruh haqida BIRINCHI qaror qilganda
    (turi, to'xtatish, o'chirish) guruh "bot boshqaruvi"ga o'tadi - keyin
    `.env` unga ta'sir qilmaydi.

    `allowed_ids()` HAR guruh xabarida chaqiriladi: qatorlar xotirada (`ttl`),
    har yozuvdan keyin darhol yangilanadi; ombor o'qilmasa - oxirgi nusxa yoki
    faqat `.env`. Hech qachon xato tashlamaydi.
    """

    def __init__(self, store: GroupStore, *, env: Callable[[], frozenset[int]] = telegram_groups_now,
                 ttl: float = 30.0, pending_max: int = PENDING_MAX, ask_every: float = 600.0,
                 seen_every: float = 600.0, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self._env = env
        self.ttl = ttl
        self.pending_max = pending_max
        self.ask_every = ask_every
        self.seen_every = seen_every
        self._clock = clock
        self._lock = threading.Lock()
        self._gen = 0
        self._cache: dict[int, dict[str, Any]] | None = None
        self._cache_at = 0.0
        self._cache_gen = -1
        self._error_at = 0.0
        self._seen: dict[int, float] = {}
        #: Guruh ro'yxatdan olib tashlangandan KEYIN chaqiriladi (`remove`, chat_id bilan).
        #: NEGA: guruhdagi CRM suhbatlari agentda turadi - ularni o'chiruvchi
        #: (`GroupActions.kick`) navbatdagi aylanishni kutmasdan darhol ishga tushsin.
        self.removed_hooks: list[Callable[[int], None]] = []

    # --- o'qish -------------------------------------------------------------------

    def env_ids(self) -> frozenset[int]:
        try:
            return frozenset(self._env())
        except Exception:  # noqa: BLE001 - `.env` o'qilmasa - bo'sh
            log.exception("Guruhlar: TELEGRAM_GROUPS o'qilmadi")
            return frozenset()

    def _rows(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            if (self._cache is not None and self._cache_gen == self._gen
                    and time.monotonic() - self._cache_at < self.ttl):
                return self._cache
            gen = self._gen
        try:
            with self.store._tx() as conn:
                rows = {row[0]: dict(zip(_FIELDS, row)) for row in conn.execute(_SELECT)}
        except sqlite3.Error as exc:
            if time.monotonic() - self._error_at > 300:
                self._error_at = time.monotonic()
                log.error("Guruhlar ro'yxati o'qilmadi - oxirgi nusxa / faqat .env: %s", exc)
            return self._cache or {}
        with self._lock:
            if gen == self._gen:
                self._cache, self._cache_at, self._cache_gen = rows, time.monotonic(), gen
        return rows

    def invalidate(self) -> None:
        with self._lock:
            self._gen += 1
            self._cache = None

    def allowed_ids(self) -> frozenset[int]:
        """Venera HOZIR o'qiydigan guruhlar (`_effective`)."""
        env = self.env_ids()
        rows = self._rows()
        out = {chat_id for chat_id in env if chat_id not in rows}
        out.update(chat_id for chat_id, row in rows.items() if _effective(row, chat_id in env))
        return frozenset(out)

    def kind_of(self, chat_id: int) -> str | None:
        """Guruh turi (`KINDS`) yoki `None` - tanlanmagan (brif uni loyiha deb oladi)."""
        row = self._rows().get(chat_id)
        kind = row.get("kind") if row else None
        return kind if kind in KINDS else None

    def state_of(self, chat_id: int) -> tuple[str | None, bool]:
        """(holat, rahbardan "turini tanlang" deb so'ralganmi) - xotiradagi
        nusxadan: yoqilmagan guruhdagi har xabarda chaqiriladi."""
        row = self._rows().get(chat_id)
        return (row["state"], row["asked_at"] is not None) if row else (None, False)

    def get(self, chat_id: int, *, follow: bool = True) -> GroupInfo | None:
        """Bitta guruh - ombordan YANGI o'qib (tugma bosilganda). `follow` - guruh
        boshqa id ga o'tgan bo'lsa (supergroup) yangisi qaytadi."""
        with self.store._tx() as conn:
            found = conn.execute(f"{_SELECT} WHERE chat_id = ?", (chat_id,)).fetchone()
        row = dict(zip(_FIELDS, found)) if found else None
        if row and follow and row["state"] == "migrated" and isinstance(row["migrated_to"], int):
            return self.get(row["migrated_to"], follow=False)
        env = self.env_ids()
        if row is None and chat_id not in env:
            return None
        return self._info(chat_id, row, env, self.store.titles([chat_id]).get(chat_id, ""))

    def listing(self) -> list[GroupInfo]:
        """Rahbar ko'radigan guruhlar: `.env` + ro'yxat, o'chirilgan va
        ko'chganlarsiz."""
        env = self.env_ids()
        with self.store._tx() as conn:
            rows = {row[0]: dict(zip(_FIELDS, row)) for row in conn.execute(_SELECT)}
        ids = [c for c in set(rows) | set(env)
               if not (rows.get(c) and rows[c]["state"] in ("removed", "migrated"))]
        titles = self.store.titles(ids)
        return [self._info(c, rows.get(c), env, titles.get(c, "")) for c in ids]

    @staticmethod
    def _info(chat_id: int, row: dict[str, Any] | None, env: frozenset[int], title: str) -> GroupInfo:
        row = row or {}
        can_pin = row.get("can_pin")
        return GroupInfo(
            chat_id=chat_id, title=title, state=row.get("state") or "pending",
            kind=row.get("kind") if row.get("kind") in KINDS else None, chat_type=row.get("chat_type"),
            bot_status=row.get("bot_status"), can_pin=None if can_pin is None else bool(can_pin),
            from_env=chat_id in env, effective=_effective(row or None, chat_id in env),
            added_tg=row.get("added_tg"), owner_tg=row.get("owner_tg"), decided_by=row.get("decided_by"),
            notice_id=row.get("notice_id"), asked_at=row.get("asked_at"), migrated_to=row.get("migrated_to"))

    # --- Telegram hodisalari (qaror emas: `decided_by` ga tegmaydi) ----------------------

    def seen(self, chat: Mapping[str, Any]) -> None:
        """Yoqilmagan guruhdan xabar keldi: bot u yerda bor. Ro'yxatga
        "kutilayotgan" bo'lib tushadi - FAQAT id, nomi, turi; xabar mazmuni
        SAQLANMAYDI. Har guruhga `seen_every` da bir marta."""
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return
        now = time.monotonic()
        with self._lock:
            if now - self._seen.get(chat_id, -self.seen_every) < self.seen_every:
                return
            self._seen[chat_id] = now
            if len(self._seen) > 5000:
                self._seen.clear()
        stamp = int(self._clock())
        try:
            with self.store._tx() as conn:
                row = conn.execute("SELECT state, bot_status FROM groups WHERE chat_id = ?",
                                   (chat_id,)).fetchone()
                if row is None:
                    (pending,) = conn.execute("SELECT COUNT(*) FROM groups WHERE state = 'pending'"
                                              " AND decided_by IS NULL").fetchone()
                    if pending >= self.pending_max:
                        return
                    conn.execute("INSERT INTO groups (chat_id, state, chat_type, created_at, updated_at)"
                                 " VALUES (?, 'pending', ?, ?, ?)", (chat_id, chat.get("type"), stamp, stamp))
                elif row[1] in GONE and row[0] not in ("removed", "migrated"):
                    # Xabar keldi - demak bot guruhda (chiqarilgani haqidagi xabar eskirgan).
                    conn.execute("UPDATE groups SET bot_status = NULL, updated_at = ? WHERE chat_id = ?",
                                 (stamp, chat_id))
                title = " ".join(str(chat.get("title") or "").split())[:NAME_MAX * 2]
                if title:
                    GroupStore._title(conn, chat_id, title)
        except sqlite3.Error as exc:
            log.warning("Guruhlar: yoqilmagan guruh yozilmadi: %s", exc)
            return
        self.invalidate()

    def joined(self, chat: Mapping[str, Any], *, adder_tg: int | None, bot_status: str | None,
               can_pin: bool | None) -> tuple[GroupInfo | None, bool]:
        """Bot guruhga qo'shildi (yoki qaytdi). Natija: guruh va "birinchi
        signalmi" - `my_chat_member`, `new_chat_members` xabari bir qo'shilish
        uchun ikki marta keladi: rahbarga savol BIR marta (`asked_at`)."""
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return None, False
        stamp = int(self._clock())
        pin = None if can_pin is None else int(bool(can_pin))
        with self.store._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM groups WHERE chat_id = ?", (chat_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO groups (chat_id, state, chat_type, bot_status, can_pin, added_tg, created_at,"
                    " updated_at) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?)",
                    (chat_id, chat.get("type"), bot_status, pin, adder_tg, stamp, stamp))
            elif row[0] == "migrated":
                return None, False
            else:
                # O'chirilgan guruhga qayta qo'shildi - yana "kutilayotgan";
                # `decided_by` qoladi: `.env` uni o'zicha yoqib yubormaydi.
                conn.execute(
                    "UPDATE groups SET state = CASE WHEN state = 'removed' THEN 'pending' ELSE state END,"
                    " chat_type = COALESCE(?, chat_type), bot_status = COALESCE(?, bot_status),"
                    " can_pin = COALESCE(?, can_pin), added_tg = COALESCE(?, added_tg), updated_at = ?"
                    " WHERE chat_id = ?", (chat.get("type"), bot_status, pin, adder_tg, stamp, chat_id))
            first = conn.execute(
                "UPDATE groups SET asked_at = ? WHERE chat_id = ? AND (asked_at IS NULL OR asked_at < ?)",
                (stamp, chat_id, stamp - int(self.ask_every))).rowcount == 1
            title = " ".join(str(chat.get("title") or "").split())[:NAME_MAX * 2]
            if title:
                GroupStore._title(conn, chat_id, title)
        self.invalidate()
        return self.get(chat_id, follow=False), first

    def member_status(self, chat_id: int, bot_status: str | None,
                      can_pin: bool | None) -> tuple[GroupInfo | None, GroupInfo | None]:
        """Botning guruhdagi holati o'zgardi (chiqarildi, admin qilindi, huquqi
        olindi). Natija: (oldin, keyin)."""
        before = self.get(chat_id, follow=False)
        stamp = int(self._clock())
        pin = None if can_pin is None else int(bool(can_pin))
        with self.store._tx() as conn:
            cur = conn.execute(
                "UPDATE groups SET bot_status = ?, can_pin = ?, updated_at = ?,"
                " asked_at = CASE WHEN ? IN ('left', 'kicked') THEN NULL ELSE asked_at END"
                " WHERE chat_id = ? AND state NOT IN ('removed', 'migrated')",
                (bot_status, pin, stamp, bot_status, chat_id))
            if cur.rowcount == 0 and before is not None and before.state == "pending" and before.from_env:
                # `.env` dagi guruh, hali qatori yo'q - holat yozib qo'yiladi.
                conn.execute("INSERT OR IGNORE INTO groups (chat_id, state, bot_status, can_pin, created_at,"
                             " updated_at) VALUES (?, 'pending', ?, ?, ?, ?)",
                             (chat_id, bot_status, pin, stamp, stamp))
        self.invalidate()
        return before, self.get(chat_id, follow=False)

    def migrate(self, old: int, new: int, *, title: str = "") -> bool:
        """Oddiy guruh supergroup'ga aylandi (`migrate_to_chat_id`). Qaror va
        turi yangi id ga o'tadi, tarix ham (`GroupStore._move_chat`); eski id -
        `migrated` (yangisiga ishora). Takror chaqirilsa - hech narsa. Natija:
        ko'chirildimi."""
        if old == new:
            return False
        env = self.env_ids()
        stamp = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            found = conn.execute(f"{_SELECT} WHERE chat_id = ?", (old,)).fetchone()
            row = dict(zip(_FIELDS, found)) if found else None
            if row is not None and row["state"] in ("migrated", "removed"):
                return False
            if row is None and old not in env:
                return False                         # Venera bilmagan guruh
            decided = conn.execute("SELECT decided_by FROM groups WHERE chat_id = ?", (new,)).fetchone()
            if decided is None or decided[0] is None:
                # `.env` orqali yoqilgan guruh yangi id da ANIQ yoqiladi - `.env` ni
                # qo'lda tuzatish endi kerak emas.
                state = "active" if _effective(row, old in env) else (row["state"] if row else "pending")
                conn.execute(
                    "INSERT INTO groups (chat_id, state, kind, chat_type, added_tg, owner_tg, decided_by, decided_at,"
                    " asked_at, created_at, updated_at) VALUES (?, ?, ?, 'supergroup', ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(chat_id) DO UPDATE SET state = excluded.state,"
                    " kind = COALESCE(excluded.kind, groups.kind), chat_type = 'supergroup',"
                    " added_tg = COALESCE(excluded.added_tg, groups.added_tg),"
                    " owner_tg = COALESCE(excluded.owner_tg, groups.owner_tg),"
                    " decided_by = excluded.decided_by, decided_at = excluded.decided_at,"
                    " asked_at = COALESCE(excluded.asked_at, groups.asked_at), updated_at = excluded.updated_at",
                    (new, state, (row or {}).get("kind"), (row or {}).get("added_tg"), (row or {}).get("owner_tg"),
                     (row or {}).get("decided_by"), (row or {}).get("decided_at"), (row or {}).get("asked_at"),
                     stamp, stamp))
            conn.execute(
                "INSERT INTO groups (chat_id, state, migrated_to, created_at, updated_at)"
                " VALUES (?, 'migrated', ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET state = 'migrated',"
                " migrated_to = excluded.migrated_to, updated_at = excluded.updated_at", (old, new, stamp, stamp))
            moved = GroupStore._move_chat(conn, old, new)
            title = " ".join(str(title or "").split())[:NAME_MAX * 2]
            if title:
                GroupStore._title(conn, new, title)
        self.invalidate()
        log.info("Guruhlar: guruh supergroup'ga aylandi - qaror va %d ta xabar yangi id ga o'tdi", moved)
        return True

    def set_notice(self, chat_id: int, message_id: int | None) -> None:
        """Guruhdagi e'lon (qadalgan xabar) - `.env` guruhida qator bo'lmasa ham yoziladi
        (`pending` + `decided_by` bo'sh: `.env` qoidasi o'zgarmaydi)."""
        stamp = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("INSERT INTO groups (chat_id, state, notice_id, created_at, updated_at)"
                         " VALUES (?, 'pending', ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET"
                         " notice_id = excluded.notice_id, updated_at = excluded.updated_at",
                         (chat_id, message_id, stamp, stamp))
        self.invalidate()

    # --- rahbar qarorlari (solishtirib-yozish: ikki bosish - bitta natija) ----------------

    def activate(self, chat_id: int, kind: str, *, actor_id: int, owner_tg: int | None) -> str:
        """Guruhni yoqish. Natija: `activated` | `already` | `paused` | `gone` | `unknown`."""
        if kind not in KINDS:
            return "unknown"
        env = self.env_ids()
        stamp = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state, bot_status FROM groups WHERE chat_id = ?", (chat_id,)).fetchone()
            if row is None:
                if chat_id not in env:
                    return "unknown"
                conn.execute("INSERT INTO groups (chat_id, state, kind, owner_tg, decided_by, decided_at, created_at,"
                             " updated_at) VALUES (?, 'active', ?, ?, ?, ?, ?, ?)",
                             (chat_id, kind, owner_tg, actor_id, stamp, stamp, stamp))
                result = "activated"
            elif row[0] in ("removed", "migrated"):
                return "unknown"
            elif row[1] in GONE:
                return "gone"
            elif row[0] == "active":
                return "already"
            elif row[0] == "paused":
                return "paused"
            else:
                conn.execute("UPDATE groups SET state = 'active', kind = ?, owner_tg = COALESCE(?, owner_tg),"
                             " decided_by = ?, decided_at = ?, updated_at = ? WHERE chat_id = ?",
                             (kind, owner_tg, actor_id, stamp, stamp, chat_id))
                result = "activated"
        self.invalidate()
        return result

    def set_kind(self, chat_id: int, kind: str, *, actor_id: int, owner_tg: int | None = None) -> bool:
        """Guruh turini almashtiradi. `.env` guruhi shu bilan bot boshqaruviga o'tadi."""
        if kind not in KINDS:
            return False
        env = self.env_ids()
        stamp = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state, decided_by FROM groups WHERE chat_id = ?", (chat_id,)).fetchone()
            if row is None:
                if chat_id not in env:
                    return False
                conn.execute("INSERT INTO groups (chat_id, state, kind, owner_tg, decided_by, decided_at, created_at,"
                             " updated_at) VALUES (?, 'active', ?, ?, ?, ?, ?, ?)",
                             (chat_id, kind, owner_tg, actor_id, stamp, stamp, stamp))
            elif row[0] in ("removed", "migrated"):
                return False
            else:
                state = "active" if row[0] == "pending" and row[1] is None and chat_id in env else row[0]
                conn.execute("UPDATE groups SET kind = ?, state = ?, owner_tg = COALESCE(owner_tg, ?), decided_by = ?,"
                             " decided_at = ?, updated_at = ? WHERE chat_id = ?",
                             (kind, state, owner_tg, actor_id, stamp, stamp, chat_id))
        self.invalidate()
        return True

    def pause(self, chat_id: int, *, actor_id: int) -> bool:
        """Vaqtincha to'xtatish: o'qilmaydi, brifga kirmaydi; saqlangani qoladi."""
        env = self.env_ids()
        stamp = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state, decided_by FROM groups WHERE chat_id = ?", (chat_id,)).fetchone()
            if row is None:
                if chat_id not in env:
                    return False
                conn.execute("INSERT INTO groups (chat_id, state, decided_by, decided_at, created_at, updated_at)"
                             " VALUES (?, 'paused', ?, ?, ?, ?)", (chat_id, actor_id, stamp, stamp, stamp))
            elif row[0] == "active" or (row[0] == "pending" and row[1] is None and chat_id in env):
                conn.execute("UPDATE groups SET state = 'paused', decided_by = ?, decided_at = ?, updated_at = ?"
                             " WHERE chat_id = ?", (actor_id, stamp, stamp, chat_id))
            else:
                return False
        self.invalidate()
        return True

    def resume(self, chat_id: int, *, actor_id: int) -> bool:
        stamp = int(self._clock())
        with self.store._tx() as conn:
            changed = conn.execute(
                "UPDATE groups SET state = 'active', decided_by = ?, decided_at = ?, updated_at = ?"
                " WHERE chat_id = ? AND state = 'paused'", (actor_id, stamp, stamp, chat_id)).rowcount
        self.invalidate()
        return changed == 1

    def remove(self, chat_id: int, *, actor_id: int) -> int | None:
        """Venera'dan butunlay olib tashlash: o'qilmaydi va saqlangan HAMMA
        narsasi (xabarlar, brif keshi, nomi) o'chiriladi - bitta
        tranzaksiyada. Qator "o'chirilgan" bo'lib qoladi: `.env` dagi guruh
        o'zicha qaytib yoqilmasin. Natija: o'chirilgan xabarlar soni; `None` -
        allaqachon o'chirilgan yoki noma'lum."""
        env = self.env_ids()
        stamp = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM groups WHERE chat_id = ?", (chat_id,)).fetchone()
            if row is None:
                if chat_id not in env:
                    return None
                conn.execute("INSERT INTO groups (chat_id, state, decided_by, decided_at, created_at, updated_at)"
                             " VALUES (?, 'removed', ?, ?, ?, ?)", (chat_id, actor_id, stamp, stamp, stamp))
            elif row[0] in ("removed", "migrated"):
                return None
            else:
                conn.execute("UPDATE groups SET state = 'removed', decided_by = ?, decided_at = ?, asked_at = NULL,"
                             " notice_id = NULL, updated_at = ? WHERE chat_id = ?", (actor_id, stamp, stamp, chat_id))
            removed = GroupStore._delete_chat(conn, chat_id)
        self.invalidate()
        for hook in list(self.removed_hooks):
            try:
                hook(chat_id)
            except Exception:  # noqa: BLE001 - o'chirish baribir bajarildi; tozalovchi keyin ham ishlaydi
                log.exception("Guruhlar: o'chirishdan keyingi ilova yiqildi")
        return removed


# --- guruhdagi CRM holati -----------------------------------------------------------------

#: Guruhdagi CRM suhbatlari agentda shu prefiks bilan ochiladi. NEGA: odamning shaxsiy
#: suhbatlar tarixi (`/api/v1/chats`) ularni bazaga qaramasdan taniydi va yashiradi -
#: ombor o'qilmasa ham guruh yozishmasi shaxsiy tarixga chiqib qolmaydi.
AGENT_CHAT_PREFIX = "tgcrm-"
#: Venera'ning guruhdagi CRM xabari egasi va tasdiq tugmasi shuncha saqlanadi. Agentdagi
#: taklif 15 daqiqada eskiradi - bu chegara faqat "eskirgan" javobini agentning o'zidan
#: olish uchun (tugmalar tozalanadi); undan keyin - bizning "Tugma eskirgan".
CRM_MESSAGE_TTL = 7 * 86400
#: Agentda shuncha marta o'chirilmagan suhbat "tiqilgan" (`counts()["stuck"]`, health
#: ogohlantirishi): urinish davom etadi, lekin odam ko'rishi kerak.
CRM_DELETE_STUCK = 5
#: Qayta urinishlar orasidagi eng uzun tanaffus (s): 10 daq, 20, 40, ... - eng ko'pi 1 kun.
CRM_RETRY_MAX = 86400


def new_agent_chat_id() -> str:
    """Guruh CRM suhbati uchun yangi agent `chat_id` si (`AGENT_CHAT_PREFIX` bilan)."""
    return f"{AGENT_CHAT_PREFIX}{uuid.uuid4()}"


def is_group_agent_chat(chat_id: Any) -> bool:
    """Agentdagi shu suhbat guruhdagi CRM suhbatimi (shaxsiy tarixda ko'rinmaydi)."""
    return isinstance(chat_id, str) and chat_id.startswith(AGENT_CHAT_PREFIX)


def _close_crm(conn: sqlite3.Connection, chat_id: int) -> None:
    """Guruhning CRM suhbatlari endi davom etmaydi (agentda o'chiriladi), tugmalari - yo'q."""
    conn.execute("UPDATE crm_chats SET closed_at = ? WHERE chat_id = ? AND closed_at IS NULL",
                 (int(time.time()), chat_id))
    conn.execute("DELETE FROM crm_messages WHERE chat_id = ?", (chat_id,))


@dataclass(frozen=True)
class CrmOwner:
    """Venera'ning guruhdagi CRM xabari kimniki (davomi va tasdiqlash uchun)."""

    actor_id: int
    tg_id: int
    name: str
    conversation: str


class GroupCrmState:
    """Guruhdagi CRM holati `groups.db` da: agent suhbatlari, xabar egalari, tugmalar.

    NEGA DISKDA (avval faqat xotirada edi): qayta ishga tushganda kutayotgan tasdiq
    va davomi yo'qolmasin; agentdagi suhbatlar (ichida guruhdagi boshqa odamlarning
    xabarlari) ro'yxatda bo'lsin - ularni keyin agentda o'chirish uchun. Noma'lum
    yoki muddati o'tgan tugma - `None` (chaqiruvchi "Tugma eskirgan" deydi).

    `sqlite3.Error` chaqiruvchiga chiqadi - u xotiradagi zaxiraga tushadi.
    """

    def __init__(self, store: GroupStore, *, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self._clock = clock

    def conversation(self, chat_id: int, actor_id: int, user_id: str, *, idle: float) -> str:
        """Odamning shu guruhdagi CRM suhbati: `idle` dan beri so'ramagan bo'lsa - yangisi.
        Eskisi "yopiladi" - u endi HECH QACHON davom ettirilmaydi (agentda yangi xabar
        o'chirilgan suhbatni tiklab yuborardi), keyin agentda o'chiriladi (`due`)."""
        now = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT conversation, last_at FROM crm_chats WHERE chat_id = ? AND actor_id = ?"
                " AND closed_at IS NULL AND deleted_at IS NULL ORDER BY last_at DESC LIMIT 1",
                (chat_id, actor_id)).fetchone()
            if row is not None and now - row[1] <= idle:
                conn.execute("UPDATE crm_chats SET last_at = ? WHERE conversation = ?", (now, row[0]))
                return row[0]
            conn.execute("UPDATE crm_chats SET closed_at = ? WHERE chat_id = ? AND actor_id = ?"
                         " AND closed_at IS NULL", (now, chat_id, actor_id))
            conversation = new_agent_chat_id()
            conn.execute("INSERT INTO crm_chats (conversation, chat_id, actor_id, user_id, created_at, last_at)"
                         " VALUES (?, ?, ?, ?, ?, ?)", (conversation, chat_id, actor_id, user_id, now, now))
            return conversation

    def remember(self, chat_id: int, message_id: int, owner: CrmOwner, *, token: str | None = None) -> None:
        """Venera'ning guruhdagi CRM xabari (javob yoki taklif kartasi) va tugma tokeni."""
        with self.store._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO crm_messages (chat_id, message_id, conversation, actor_id, tg_id, name,"
                " token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, message_id, owner.conversation, owner.actor_id, owner.tg_id, owner.name[:NAME_MAX * 2],
                 token or None, int(self._clock())))

    def owner_of(self, chat_id: int, message_id: int) -> CrmOwner | None:
        """Shu xabar Venera'ning CRM xabarimi va kimniki (muddati o'tmagan bo'lsa)."""
        since = int(self._clock() - CRM_MESSAGE_TTL)
        with self.store._tx() as conn:
            row = conn.execute("SELECT actor_id, tg_id, name, conversation FROM crm_messages"
                               " WHERE chat_id = ? AND message_id = ? AND created_at >= ?",
                               (chat_id, message_id, since)).fetchone()
        return CrmOwner(*row) if row else None

    def token_owner(self, token: str, chat_id: int) -> CrmOwner | None:
        """Taklif tugmasi egasi - FAQAT shu guruhdagi taklif bo'lsa."""
        if not token:
            return None
        since = int(self._clock() - CRM_MESSAGE_TTL)
        with self.store._tx() as conn:
            row = conn.execute("SELECT actor_id, tg_id, name, conversation FROM crm_messages"
                               " WHERE token = ? AND chat_id = ? AND created_at >= ?"
                               " ORDER BY created_at DESC LIMIT 1", (token, chat_id, since)).fetchone()
        return CrmOwner(*row) if row else None

    def due(self, *, idle: float, margin: float, limit: int = 50) -> list[tuple[str, str]]:
        """Agentda o'chirilishi kerak suhbatlar: (chat_id, user_id). Yopilgan (guruh
        o'chirildi, saqlash muddati o'tdi, yangisi ochildi) yoki `idle` dan beri
        jim. `margin` - oxirgi savoldan keyin shuncha kutiladi: shu payt oqimda turgan
        javob tugasin (aks holda o'chirilgan suhbatga yozib, uni tiklab yuborardi).

        Tartib - avval KAM urinilganlar (`attempts`), keyin eskisi; qayta urinish vaqti
        (`next_at`) kelmaganlari olinmaydi. NEGA: doim yiqiladigan bitta suhbat har
        aylanishda boshda turib, qolganlarini abadiy to'sib qo'ymasin (sharh, 2026-10-10)."""
        now = int(self._clock())
        with self.store._tx() as conn:
            rows = conn.execute(
                "SELECT conversation, user_id FROM crm_chats WHERE deleted_at IS NULL AND last_at < ?"
                " AND (closed_at IS NOT NULL OR last_at < ?) AND (next_at IS NULL OR next_at <= ?)"
                " ORDER BY attempts, last_at LIMIT ?",
                (now - int(margin), now - int(idle), now, int(limit))).fetchall()
        return [(conversation, user_id) for conversation, user_id in rows]

    def deleted(self, conversation: str) -> None:
        """Agentda o'chirildi. Iz (`deleted_at`) saqlash muddatigacha qoladi (`purge`)."""
        now = int(self._clock())
        with self.store._tx() as conn:
            conn.execute("UPDATE crm_chats SET deleted_at = ?, closed_at = COALESCE(closed_at, ?)"
                         " WHERE conversation = ?", (now, now, conversation))

    def failed(self, conversation: str, *, retry_in: float | None = None) -> None:
        """Agentda o'chirilmadi. `retry_in` yo'q - keyingi aylanishda yana (agentning
        o'zi ishlamayapti: aybi suhbatda emas); bor - shu suhbat uchun tanaffus, har
        urinishda ikki baravar (`CRM_RETRY_MAX` gacha): faqat shu suhbat yiqilyapti."""
        now = int(self._clock())
        with self.store._tx() as conn:
            if retry_in is None:
                conn.execute("UPDATE crm_chats SET attempts = attempts + 1 WHERE conversation = ?",
                             (conversation,))
                return
            row = conn.execute("SELECT attempts FROM crm_chats WHERE conversation = ?", (conversation,)).fetchone()
            tried = int(row[0]) if row else 0
            wait = min(float(retry_in) * (2 ** min(tried, 20)), float(CRM_RETRY_MAX))
            conn.execute("UPDATE crm_chats SET attempts = attempts + 1, next_at = ? WHERE conversation = ?",
                         (now + int(max(1.0, wait)), conversation))

    def counts(self) -> dict[str, int]:
        """Holat sonlari (`/api/health/detail`, testlar): ochiq, o'chirilishi kutilayotgan,
        o'chirilgan va tiqilgan (`CRM_DELETE_STUCK` martadan ko'p o'chirilmagan)."""
        with self.store._tx() as conn:
            open_, pending, deleted, stuck = conn.execute(
                "SELECT COALESCE(SUM(closed_at IS NULL AND deleted_at IS NULL), 0),"
                " COALESCE(SUM(closed_at IS NOT NULL AND deleted_at IS NULL), 0),"
                " COALESCE(SUM(deleted_at IS NOT NULL), 0),"
                " COALESCE(SUM(deleted_at IS NULL AND attempts >= ?), 0) FROM crm_chats",
                (CRM_DELETE_STUCK,)).fetchone()
        return {"open": int(open_), "closing": int(pending), "deleted": int(deleted), "stuck": int(stuck)}


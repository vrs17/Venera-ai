"""Yig'ilishlar ombori - bitta SQLite fayl + audio fayllar (spetsifikatsiya 4).

    data/meetings/meetings.db                     WAL, foreign_keys, secure_delete
    data/meetings/uploads/<meetingId>.part        yuklanayotgan fayl
    data/meetings/audio/<actorId>/<meetingId>.aac yig'ilgan asl yozuv (STT ga shu ketadi)
    data/meetings/audio/<actorId>/<meetingId>.m4a tinglash uchun nusxa (remux)
    data/meetings/worker.lock                     bitta ishchi qulfi

NEGA ANALITIKA OMBORIDAN ALOHIDA. Bu yerda odamlarning yig'ilish matni turadi
(1:1, suhbatlar, mijoz qo'ng'iroqlari) - boshqa saqlash muddati, boshqa
o'chirish qoidasi (`secure_delete`), va admin panel unga umuman qaramaydi.

IZOLYATSIYA BITTA QOIDA BILAN. `actor_id` faqat `meetings` jadvalida turadi;
har bola jadval so'rovi `meetings m ON m.id=? AND m.actor_id=?` orqali
o'tadi va har ommaviy metod `actor_id` oladi. Boshqa odamning yig'ilishi
"yo'q" bilan bir xil ko'rinadi (404) - borligi ham bilinmasin.

SXEMA `PRAGMA user_version` bilan, `analytics/db.py` dagi kabi: `MIGRATIONS`
FAQAT OXIRIGA qo'shiladi, mavjud qadam o'zgartirilmaydi.

HUQUQLAR: papkalar 700, fayllar 600 - SQLite ochishidan OLDIN yaratiladi
(aks holda `umask` bo'yicha bir lahza hamma o'qiy oladigan bo'lib turardi).
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
import unicodedata
import uuid

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

log = logging.getLogger(__name__)

_V1: tuple[str, ...] = (
    """CREATE TABLE meetings (
  id TEXT PRIMARY KEY, actor_id INTEGER NOT NULL, client_id TEXT NOT NULL,
  title TEXT, title_source TEXT NOT NULL DEFAULT 'auto', language TEXT NOT NULL DEFAULT 'uz',
  detected_lang TEXT, template TEXT NOT NULL DEFAULT 'auto', expected_speakers INTEGER,
  source TEXT, channel TEXT, app_version TEXT, device TEXT,
  recorded_at INTEGER, ended_at INTEGER, duration_sec REAL, content_type TEXT,
  received_bytes INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER, audio_sha256 TEXT,
  audio_path TEXT, audio_deleted_at INTEGER, marks TEXT,
  status TEXT NOT NULL DEFAULT 'uploading', progress REAL, error_code TEXT, error_stage TEXT,
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER, lease_owner TEXT, lease_until INTEGER,
  stt_engine TEXT, stt_job_id TEXT, stt_result_url TEXT, stt_submitted_at INTEGER, stt_audio_sec REAL,
  transcript_rev INTEGER NOT NULL DEFAULT 0, primary_summary_id TEXT,
  summary_status TEXT NOT NULL DEFAULT 'none',
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  -- extras (build notes): list overview, poll timing, transcript flags, backoff
  overview TEXT, completed_at INTEGER, speakers_available INTEGER NOT NULL DEFAULT 0,
  timing TEXT, retries INTEGER NOT NULL DEFAULT 0, stt_deadline_at INTEGER,
  UNIQUE(actor_id, client_id))""",
    "CREATE INDEX meetings_actor ON meetings(actor_id, recorded_at DESC)",
    "CREATE INDEX meetings_queue ON meetings(status, next_attempt_at)",
    """CREATE TABLE speakers (
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  id TEXT NOT NULL, raw_index INTEGER, name TEXT, suggested_name TEXT,
  talk_sec REAL NOT NULL DEFAULT 0, merged_into TEXT,
  PRIMARY KEY (meeting_id, id))""",
    """CREATE TABLE segments (
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  id INTEGER NOT NULL, start REAL NOT NULL, "end" REAL NOT NULL, speaker TEXT,
  text TEXT NOT NULL, orig_text TEXT, edited INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (meeting_id, id))""",
    """CREATE TABLE summaries (
  id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  template TEXT NOT NULL, language TEXT NOT NULL, prompt_version TEXT NOT NULL,
  transcript_rev INTEGER NOT NULL, status TEXT NOT NULL, model TEXT, content_json TEXT,
  error_code TEXT, error TEXT, created_at INTEGER NOT NULL, finished_at INTEGER,
  requested_template TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER)""",
    "CREATE INDEX summaries_meeting ON summaries(meeting_id, created_at)",
    """CREATE TABLE summary_parts (
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  transcript_rev INTEGER NOT NULL, prompt_version TEXT NOT NULL, template TEXT NOT NULL,
  language TEXT NOT NULL, part INTEGER NOT NULL, first_id INTEGER NOT NULL, last_id INTEGER NOT NULL,
  content_json TEXT NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY (meeting_id, transcript_rev, prompt_version, template, language, part))""",
    """CREATE TABLE action_items (
  id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  summary_item_id TEXT, task TEXT NOT NULL, owner_speaker TEXT, owner_name TEXT,
  owner_kind TEXT NOT NULL DEFAULT 'unknown', due_date TEXT, due_time TEXT, due_raw TEXT,
  priority TEXT, status TEXT NOT NULL DEFAULT 'open', origin TEXT NOT NULL DEFAULT 'ai',
  edited INTEGER NOT NULL DEFAULT 0, needs_confirmation INTEGER NOT NULL DEFAULT 0,
  source_ids TEXT, quote TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""",
    "CREATE INDEX action_items_meeting ON action_items(meeting_id, status)",
    """CREATE TABLE questions (
  id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  question TEXT NOT NULL, answer TEXT NOT NULL, citations TEXT, follow_ups TEXT,
  created_at INTEGER NOT NULL)""",
    "CREATE INDEX questions_meeting ON questions(meeting_id, created_at)",
    """CREATE TABLE quota_days (
  day TEXT NOT NULL, actor_id INTEGER NOT NULL, audio_sec REAL NOT NULL DEFAULT 0,
  jobs INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, actor_id))""",
)

#: v2 (2026-10-09): xulosani QAYSI provayder yozgani (`v3` | `openai` | `ollama`; model -
#: `model` ustunida) va vazifaning CRM taklifi: kalit (`/api/v1/actions/{token}/confirm`
#: shu bilan), holati, kartaga kerak taklif obyekti, muddati, CRM natijasi va so'rov izi
#: (`crm_sig`: vazifa o'zgarmagan bo'lsa ikkinchi bosish agentga qayta bormaydi).
_V2: tuple[str, ...] = (
    "ALTER TABLE summaries ADD COLUMN provider TEXT",
    "ALTER TABLE action_items ADD COLUMN crm_token TEXT",
    "ALTER TABLE action_items ADD COLUMN crm_status TEXT",
    "ALTER TABLE action_items ADD COLUMN crm_proposal TEXT",
    "ALTER TABLE action_items ADD COLUMN crm_expires_at TEXT",
    "ALTER TABLE action_items ADD COLUMN crm_result TEXT",
    "ALTER TABLE action_items ADD COLUMN crm_sig TEXT",
    "ALTER TABLE action_items ADD COLUMN crm_updated_at INTEGER",
    "CREATE INDEX action_items_crm ON action_items(crm_token)",
)

#: v3 (2026-10-11): qo'ng'iroq yozuvi roziligi SERVERDA (avval faqat telefonda edi): odam
#: "suhbatdoshni ogohlantiring" eslatmasini qachon qabul qilgani va matn versiyasi.
_V3: tuple[str, ...] = (
    "ALTER TABLE meetings ADD COLUMN consent_at INTEGER",
    "ALTER TABLE meetings ADD COLUMN consent_version TEXT",
)

#: v4 (2026-11-03): vazifa QAYSI GAPI kaliti bilan yuborilgani (1 - `GAPI_API_KEY`, 2 -
#: `GAPI_API_KEY2`): vazifa o'sha hisobniki, holati va natijasi ham o'sha kalit bilan
#: so'raladi. `NULL` - eski yozuvlar, ya'ni 1.
_V4: tuple[str, ...] = (
    "ALTER TABLE meetings ADD COLUMN stt_account INTEGER",
)

#: v5 (2026-11-04): BAYONNOMA - rasmiy hujjat (`services/meetings/minutes/`): yig'ilish uchun
#: tanlangan tilda (`uz-latn` | `uz-cyrl` | `ru` | `en`) model yozgan hujjat mazmuni (JSON), kim
#: yozgani va holati. Xulosalardan ALOHIDA jadval: mobil ilova `summaries` ro'yxatini tab sifatida
#: ko'rsatadi va bu shaklni chiza olmaydi; dedupe kaliti - til + transkript versiyasi + prompt versiyasi.
_V5: tuple[str, ...] = (
    """CREATE TABLE minutes (
  id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  language TEXT NOT NULL, transcript_rev INTEGER NOT NULL, prompt_version TEXT NOT NULL,
  status TEXT NOT NULL, provider TEXT, model TEXT, content_json TEXT, error_code TEXT, error TEXT,
  created_at INTEGER NOT NULL, finished_at INTEGER)""",
    "CREATE INDEX minutes_meeting ON minutes(meeting_id, created_at)",
)

#: v6 (2026-11-11): Plaud filtri - yozuv QAYERDAN kelgani (`ORIGIN_SQL`). Ustunga faqat server o'zi
#: yaratgan yozuv (Slack, Telegram bot - `intake.upload`) yoziladi: qolganini `channel`/`source` aytadi.
#: Slack'ni ulardan ajratib bo'lmaydi (`channel=api`) - eski Slack yozuvlari nomidan ("Slack: ...")
#: belgilanadi, shunda odam keyin nomini o'zgartirsa ham Slack filtrida qoladi.
_V6: tuple[str, ...] = (
    "ALTER TABLE meetings ADD COLUMN origin TEXT",
    "UPDATE meetings SET origin = 'slack' WHERE origin IS NULL AND channel = 'api' AND title LIKE 'Slack:%'",
)

#: v7 (2026-11-11): yig'ilish CHATI - bitta audio, bitta suhbat (`services/meetings/chat.py`). Savol-javob
#: qatori endi suhbat navbati: qaysi kanaldan kelgani (`mobile|web|miniapp|desktop|api|slack|telegram`;
#: `NULL` - eski qator), kim javob bergani (model nomi), javob tili va "Yangi suhbat" belgisi
#: (`archived_at`): belgilangan navbat modelga xotira sifatida ham, ro'yxatga ham bormaydi, lekin
#: bazada qoladi - yumshoq tozalash, qattiq o'chirish yo'q. `asker` - UMUMIY hisobda kim so'ragani
#: (Slack'dagi hamma odam bitta `SLACK_ACTOR_ID` hisobidan: `slack:<user id>`): har odamning suhbati va
#: "Yangi suhbat"i o'ziniki. `NULL` - hisob egasining o'z kanallari (ilova, web, Telegram). `client_id` -
#: xabarning klient kaliti (idempotentlik, `ChatRequest.clientId`): ilova noaniq xatodan keyin o'sha kalit
#: bilan qayta yuboradi va server ikkinchi navbat yozmaydi; `NULL` - kalitsiz (botlar, eski qator).
_V7: tuple[str, ...] = (
    "ALTER TABLE questions ADD COLUMN channel TEXT",
    "ALTER TABLE questions ADD COLUMN model TEXT",
    "ALTER TABLE questions ADD COLUMN language TEXT",
    "ALTER TABLE questions ADD COLUMN archived_at INTEGER",
    "ALTER TABLE questions ADD COLUMN asker TEXT",
    "ALTER TABLE questions ADD COLUMN client_id TEXT",
    "CREATE INDEX questions_client ON questions(meeting_id, client_id)",
    # Transkript AVLODI: faqat transkript butunlay almashganda (`replace_transcript` - o'girish/qayta o'girish)
    # oshadi; qator tahriri va spikerlarni birlashtirish (`transcript_rev`) uni o'zgartirmaydi. Chat navbati
    # kutish paytida matn almashganini shu bilan biladi (`add_turn`).
    "ALTER TABLE meetings ADD COLUMN transcript_gen INTEGER NOT NULL DEFAULT 0",
)

#: `MIGRATIONS[i]` fayl `user_version = i` dan `i + 1` ga o'tkazadi. FAQAT OXIRIGA.
MIGRATIONS: tuple[tuple[str, ...], ...] = (_V1, _V2, _V3, _V4, _V5, _V6, _V7)
SCHEMA_VERSION = len(MIGRATIONS)

#: Yozuv manbasi (Plaud filtri; mobil `MeetingOrigin`). `recording` - telefonda yozilgan, `upload` - telefondan
#: yuborilgan tayyor fayl ("Audio yuklash", "Ulashish -> Barno AI", qo'ng'iroq yozuvi), `miniapp`/`web`/`desktop` -
#: o'sha klient, `api` - qolgani (skript, REST import).
ORIGINS: tuple[str, ...] = ("recording", "upload", "slack", "telegram", "miniapp", "web", "desktop", "api")

#: Manba - BITTA joyda, SQL ifoda: filtr ham, karta ham shundan (Python'da ikkinchi nusxa yo'q). `origin`
#: ustuni bo'sh bo'lsa (v6 dan oldingi yoki boshqa ombordan ko'chirilgan qator) `channel`/`source` dan.
ORIGIN_SQL = """CASE
  WHEN origin IS NOT NULL THEN origin
  WHEN channel = 'bot' THEN 'telegram'
  WHEN channel = 'api' AND title LIKE 'Slack:%' THEN 'slack'
  WHEN channel = 'mobile' AND source IN ('share', 'call') THEN 'upload'
  WHEN channel = 'mobile' THEN 'recording'
  WHEN channel IN ('miniapp', 'web', 'desktop') THEN channel
  ELSE 'api' END"""

#: Ro'yxatdagi o'rni (`sort=listed`): tayyor fayl (`share`, `call` - telefondan, Slack'dan, Telegram'dan)
#: Barno'ga KELGAN vaqti bilan, ilovada yozilgani - YOZILGAN vaqti bilan. NEGA: 8-noyabrdagi yozuv bugun
#: yuklansa - u bugungi ish, 8-noyabr ostiga tushib, ko'rinmay qolmasin (ega talabi 2026-11-11).
LISTED_SQL = "CASE WHEN source IN ('share', 'call') THEN created_at ELSE COALESCE(recorded_at, created_at) END"

#: Apostrofning hamma ko'rinishi - qidiruvda olib tashlanadi ("o'zbek" = "oʻzbek" = "ozbek").
_APOSTROPHES = "'ʻʼ’‘`´"


def fold(text: Any) -> str:
    """Qidiruv uchun: NFKC, kichik harf, apostroflarsiz."""
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    for ch in _APOSTROPHES:
        value = value.replace(ch, "")
    return value


def new_id() -> str:
    return uuid.uuid4().hex


def jdump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def jload(raw: Any, default: Any = None) -> Any:
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def transcript_ready(m: Mapping[str, Any]) -> bool:
    """Transkript tayyor: o'girilgan (`transcript_rev > 0`, `stt_engine`) va yig'ilish xulosa bosqichida yoki
    tayyor. Qayta o'girish paytida (`uploaded`, `transcribing`, `stt_engine` bo'sh) - yo'q."""
    return bool(int(m.get("transcript_rev") or 0) > 0 and m.get("stt_engine")
                and m.get("status") in ("summarizing", "ready"))


def _migrate(conn: sqlite3.Connection) -> int:
    """`analytics/db._migrate` nusxasi: har qadam o'z `BEGIN IMMEDIATE` tranzaksiyasida."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        log.warning("Yig'ilishlar ombori yangiroq sxemada: %d > %d", version, SCHEMA_VERSION)
        return version
    while version < SCHEMA_VERSION:
        conn.execute("BEGIN IMMEDIATE")
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version >= SCHEMA_VERSION:
                conn.execute("COMMIT")
                break
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            version += 1
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        log.info("Yig'ilishlar ombori sxemasi: v%d", version)
    return version


def _private_dir(path: Path) -> None:
    """Papka 700 - faqat o'zimiz yaratgan yoki egasi biz bo'lsa toraytiriladi."""
    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        info = path.stat()
        if created or info.st_uid == os.getuid():
            os.chmod(path, 0o700)


def private_file(path: Path) -> None:
    """Fayl 600 bilan, MAZMUNDAN OLDIN yaratiladi."""
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


class MeetingStore:
    """Ombor. Har ip o'z ulanishini oladi (`analytics/db.Database` kabi)."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.db_path = self.root / "meetings.db"
        self._local = threading.local()
        self._lock = threading.Lock()
        self._prepared = False
        self._migrated = False
        self._all: set[sqlite3.Connection] = set()

    # --- joylar --------------------------------------------------------------

    @property
    def exists(self) -> bool:
        """Ombor diskda bormi - bo'lim o'chiq va ma'lumot yo'q bo'lsa ishchi
        hech narsa YARATMASLIGI uchun."""
        return self.db_path.exists()

    def upload_path(self, meeting_id: str) -> Path:
        return self.root / "uploads" / f"{meeting_id}.part"

    def audio_dir(self, actor_id: int) -> Path:
        path = self.root / "audio" / str(int(actor_id))
        _private_dir(self.root / "audio")
        _private_dir(path)
        return path

    def lock_path(self) -> Path:
        return self.root / "worker.lock"

    def prepare(self) -> None:
        if self._prepared:
            return
        with self._lock:
            if self._prepared:
                return
            _private_dir(self.root)
            _private_dir(self.root / "uploads")
            _private_dir(self.root / "audio")
            private_file(self.db_path)
            self._prepared = True

    # --- ulanish -------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self.prepare()
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None,
                               check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA foreign_keys=ON")
            # O'chirilgan matn diskda "qoldiq" bo'lib qolmasin: yig'ilish
            # o'chirildi degani - uning so'zlari fayldan ham ketdi degani.
            conn.execute("PRAGMA secure_delete=ON")
            conn.create_function("vfold", 1, fold, deterministic=True)
            with self._lock:
                if not self._migrated:
                    _migrate(conn)
                    self._migrated = True
        except BaseException:
            conn.close()
            raise
        self._local.conn = conn
        with self._lock:
            self._all.add(conn)
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.chmod(f"{self.db_path}{suffix}", 0o600)
        return conn

    def close_all(self) -> None:
        with self._lock:
            conns, self._all = list(self._all), set()
        for conn in conns:
            with contextlib.suppress(sqlite3.Error):
                conn.close()
        self._local = threading.local()

    def version(self) -> int:
        return int(self.connect().execute("PRAGMA user_version").fetchone()[0])

    # --- umumiy so'rovlar ------------------------------------------------------

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        return self.connect().execute(sql, params)

    def rows(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.connect().execute(sql, params).fetchall()]

    def row(self, sql: str, params: Any = ()) -> dict[str, Any] | None:
        found = self.connect().execute(sql, params).fetchone()
        return dict(found) if found is not None else None

    def scalar(self, sql: str, params: Any = (), default: Any = None) -> Any:
        found = self.connect().execute(sql, params).fetchone()
        return default if found is None or found[0] is None else found[0]

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        try:
            conn.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            raise

    # --- yig'ilishlar --------------------------------------------------------

    def meeting(self, actor_id: int, meeting_id: str) -> dict[str, Any] | None:
        """Faqat EGASIGA. Boshqasi uchun `None` (= 404)."""
        return self.row("SELECT * FROM meetings WHERE id=? AND actor_id=?",
                        (str(meeting_id), int(actor_id)))

    def meeting_any(self, meeting_id: str) -> dict[str, Any] | None:
        """ISHCHI uchun (egasiz) - HTTP yo'lida ishlatilmaydi."""
        return self.row("SELECT * FROM meetings WHERE id=?", (str(meeting_id),))

    def by_client(self, actor_id: int, client_id: str) -> dict[str, Any] | None:
        return self.row("SELECT * FROM meetings WHERE actor_id=? AND client_id=?",
                        (int(actor_id), str(client_id)))

    def insert_meeting(self, fields: dict[str, Any]) -> None:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self.execute(f"INSERT INTO meetings ({cols}) VALUES ({marks})", tuple(fields.values()))

    def update_meeting(self, meeting_id: str, *, actor_id: int | None = None,
                       now: float | None = None, **fields: Any) -> int:
        """Maydonlarni yangilaydi (`updated_at` o'zi). `actor_id` berilsa - faqat egasiniki."""
        fields["updated_at"] = int(now if now is not None else time.time())
        sets = ", ".join(f"{name}=?" for name in fields)
        params: list[Any] = list(fields.values()) + [str(meeting_id)]
        sql = f"UPDATE meetings SET {sets} WHERE id=?"
        if actor_id is not None:
            sql += " AND actor_id=?"
            params.append(int(actor_id))
        return self.execute(sql, params).rowcount

    def delete_meeting_rows(self, meeting_id: str) -> None:
        self.execute("DELETE FROM meetings WHERE id=?", (str(meeting_id),))

    def list_meetings(self, actor_id: int, *, limit: int, offset: int, q: str = "", status: str = "",
                      origin: str = "", sort: str = "recorded") -> tuple[list[dict[str, Any]], int]:
        """Qatorlarda qo'shimcha `effective_origin` (`ORIGIN_SQL`) va `listed_at` (`LISTED_SQL`) bor.
        `sort`: `recorded` - yozilgan vaqti (eski ilovalar shunga guruhlaydi), `listed` - ro'yxatdagi o'rni."""
        where = ["actor_id=?"]
        params: list[Any] = [int(actor_id)]
        if status:
            where.append("status=?")
            params.append(status)
        if origin:
            where.append(f"({ORIGIN_SQL}) = ?")
            params.append(origin)
        needle = fold(q).strip()
        if needle:
            pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(vfold(title) LIKE ? ESCAPE '\\' OR vfold(overview) LIKE ? ESCAPE '\\')")
            params += [pattern, pattern]
        clause = " AND ".join(where)
        total = int(self.scalar(f"SELECT COUNT(*) FROM meetings WHERE {clause}", params, 0))
        order = "listed_at DESC, created_at DESC" if sort == "listed" else "recorded_at DESC, created_at DESC"
        rows = self.rows(f"SELECT *, ({ORIGIN_SQL}) AS effective_origin, ({LISTED_SQL}) AS listed_at "
                         f"FROM meetings WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                         params + [int(limit), int(offset)])
        return rows, total

    # --- transkripsiya --------------------------------------------------------

    def speakers(self, meeting_id: str) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM speakers WHERE meeting_id=? ORDER BY id", (meeting_id,))

    def segments(self, meeting_id: str) -> list[dict[str, Any]]:
        return self.rows('SELECT id, start, "end", speaker, text, orig_text, edited '
                         "FROM segments WHERE meeting_id=? ORDER BY id", (meeting_id,))

    def segment_count(self, meeting_id: str) -> int:
        return int(self.scalar("SELECT COUNT(*) FROM segments WHERE meeting_id=?", (meeting_id,), 0))

    def replace_transcript(self, meeting_id: str, segments: list[dict[str, Any]],
                           speakers: list[dict[str, Any]], *, guard_owner: str | None = None,
                           guard_status: tuple[str, ...] | None = None, summary: dict[str, Any] | None = None,
                           **meeting_fields: Any) -> int | None:
        """Transkriptni BITTA tranzaksiyada almashtiradi va `transcript_rev` ni oshiradi.

        Yarim yozilgan transkript bo'lmasin: xizmat o'rtada to'xtasa ham
        eski holat yoki to'liq yangisi qoladi.

        `guard_owner` / `guard_status` - ESKIRGAN ip yozmasin: ijara boshqaga o'tgan
        yoki holat o'zgargan bo'lsa hech narsa yozilmaydi va `None` qaytadi.
        `summary` - asosiy xulosa qatori O'SHA tranzaksiyada qo'shiladi (transkript
        bor-u xulosa navbatda yo'q, yoki ikki marta navbatga qo'yilgan holat bo'lmasin)."""
        now = int(time.time())
        with self.transaction() as conn:
            if guard_owner is not None or guard_status is not None:
                row = conn.execute("SELECT lease_owner, status FROM meetings WHERE id=?", (meeting_id,)).fetchone()
                if row is None or (guard_owner is not None and row["lease_owner"] != guard_owner) \
                        or (guard_status is not None and row["status"] not in guard_status):
                    return None
            conn.execute("DELETE FROM segments WHERE meeting_id=?", (meeting_id,))
            conn.execute("DELETE FROM speakers WHERE meeting_id=?", (meeting_id,))
            conn.executemany(
                'INSERT INTO segments (meeting_id, id, start, "end", speaker, text, orig_text, edited) '
                "VALUES (?,?,?,?,?,?,?,0)",
                [(meeting_id, s["id"], s["start"], s["end"], s["speaker"], s["text"], s["text"])
                 for s in segments])
            conn.executemany(
                "INSERT INTO speakers (meeting_id, id, raw_index, name, suggested_name, talk_sec, merged_into) "
                "VALUES (?,?,?,NULL,NULL,?,NULL)",
                [(meeting_id, sp["id"], sp.get("rawIndex"), sp.get("talkSec", 0.0)) for sp in speakers])
            meeting_fields["updated_at"] = now
            sets = ", ".join(f"{name}=?" for name in meeting_fields)
            conn.execute(f"UPDATE meetings SET transcript_rev=transcript_rev+1, transcript_gen=transcript_gen+1, "
                         f"{sets} WHERE id=?", list(meeting_fields.values()) + [meeting_id])
            rev = conn.execute("SELECT transcript_rev FROM meetings WHERE id=?",
                               (meeting_id,)).fetchone()[0]
            if summary is not None:
                fields = dict(summary, transcript_rev=int(rev))
                cols = ", ".join(fields)
                conn.execute(f"INSERT INTO summaries ({cols}) VALUES ({', '.join('?' for _ in fields)})",
                             tuple(fields.values()))
        return int(rev)

    def bump_rev(self, meeting_id: str) -> int:
        self.execute("UPDATE meetings SET transcript_rev=transcript_rev+1, updated_at=? WHERE id=?",
                     (int(time.time()), meeting_id))
        return int(self.scalar("SELECT transcript_rev FROM meetings WHERE id=?", (meeting_id,), 0))

    # --- xulosalar ------------------------------------------------------------

    def summaries(self, meeting_id: str) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM summaries WHERE meeting_id=? ORDER BY created_at, rowid",
                         (meeting_id,))

    def summary(self, meeting_id: str, summary_id: str) -> dict[str, Any] | None:
        return self.row("SELECT * FROM summaries WHERE id=? AND meeting_id=?", (summary_id, meeting_id))

    def insert_summary(self, fields: dict[str, Any]) -> None:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self.execute(f"INSERT INTO summaries ({cols}) VALUES ({marks})", tuple(fields.values()))

    def update_summary(self, summary_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{name}=?" for name in fields)
        self.execute(f"UPDATE summaries SET {sets} WHERE id=?", list(fields.values()) + [summary_id])

    def part(self, meeting_id: str, key: tuple, first_id: int, last_id: int) -> Any:
        """Map bosqichi keshi: shu bo'lak avval tekshirib saqlanganmi."""
        rev, version, template, language = key
        raw = self.scalar(
            "SELECT content_json FROM summary_parts WHERE meeting_id=? AND transcript_rev=? AND "
            "prompt_version=? AND template=? AND language=? AND first_id=? AND last_id=?",
            (meeting_id, rev, version, template, language, first_id, last_id))
        return jload(raw)

    def put_part(self, meeting_id: str, key: tuple, first_id: int, last_id: int, content: Any) -> None:
        rev, version, template, language = key
        with self.transaction() as conn:
            nxt = conn.execute(
                "SELECT COALESCE(MAX(part), 0) + 1 FROM summary_parts WHERE meeting_id=? AND "
                "transcript_rev=? AND prompt_version=? AND template=? AND language=?",
                (meeting_id, rev, version, template, language)).fetchone()[0]
            conn.execute(
                "INSERT INTO summary_parts (meeting_id, transcript_rev, prompt_version, template, language, "
                "part, first_id, last_id, content_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (meeting_id, rev, version, template, language, int(nxt), first_id, last_id,
                 jdump(content), int(time.time())))

    # --- bayonnoma (rasmiy hujjat) ------------------------------------------------------

    def minutes_rows(self, meeting_id: str) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM minutes WHERE meeting_id=? ORDER BY created_at, rowid", (meeting_id,))

    def minutes_row(self, meeting_id: str, minutes_id: str) -> dict[str, Any] | None:
        return self.row("SELECT * FROM minutes WHERE id=? AND meeting_id=?", (minutes_id, meeting_id))

    def insert_minutes(self, fields: dict[str, Any]) -> None:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self.execute(f"INSERT INTO minutes ({cols}) VALUES ({marks})", tuple(fields.values()))

    def update_minutes(self, minutes_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{name}=?" for name in fields)
        self.execute(f"UPDATE minutes SET {sets} WHERE id=?", list(fields.values()) + [minutes_id])

    # --- vazifalar ----------------------------------------------------------------

    def action_items(self, meeting_id: str) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM action_items WHERE meeting_id=?", (meeting_id,))

    def action_item(self, meeting_id: str, item_id: str) -> dict[str, Any] | None:
        return self.row("SELECT * FROM action_items WHERE id=? AND meeting_id=?", (item_id, meeting_id))

    def insert_action_item(self, fields: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        (conn or self.connect()).execute(f"INSERT INTO action_items ({cols}) VALUES ({marks})",
                                         tuple(fields.values()))

    def update_action_item(self, item_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{name}=?" for name in fields)
        self.execute(f"UPDATE action_items SET {sets} WHERE id=?", list(fields.values()) + [item_id])

    def set_crm_status(self, actor_id: int, token: str, status: str, result: Any = None,
                       now: float | None = None) -> int:
        """Taklif tasdiqlandi / rad etildi / muddati o'tdi (`/api/v1/actions/...`) - shu
        kalitli vazifaning CRM holati. Faqat EGASINING yig'ilishidagi vazifa.

        `executed` HECH QACHON almashtirilmaydi: bajarilgan taklifni qayta tasdiqlash xizmatdan
        404/410 oladi va `expired` bo'lib yozilardi - shunda vazifa yana "yuborilmagan" ko'rinib,
        CRM da ikkinchi marta yaratilishi mumkin edi."""
        return self.execute(
            "UPDATE action_items SET crm_status=?, crm_result=COALESCE(?, crm_result), crm_updated_at=? "
            "WHERE crm_token=? AND COALESCE(crm_status, '') != 'executed' "
            "AND meeting_id IN (SELECT id FROM meetings WHERE actor_id=?)",
            (status, jdump(result) if result is not None else None, int(now if now is not None else time.time()),
             str(token), int(actor_id))).rowcount

    def open_items(self, meeting_id: str) -> int:
        return int(self.scalar("SELECT COUNT(*) FROM action_items WHERE meeting_id=? AND status='open'",
                               (meeting_id,), 0))

    def my_action_items(self, actor_id: int, status: str, limit: int) -> list[dict[str, Any]]:
        where = "m.actor_id=?"
        params: list[Any] = [int(actor_id)]
        if status in ("open", "done"):
            where += " AND a.status=?"
            params.append(status)
        return self.rows(
            "SELECT a.*, m.title AS meeting_title, m.recorded_at AS meeting_recorded_at "
            f"FROM action_items a JOIN meetings m ON m.id=a.meeting_id WHERE {where} "
            "ORDER BY CASE a.status WHEN 'open' THEN 0 WHEN 'done' THEN 1 ELSE 2 END, "
            "COALESCE(a.due_date, '9999-12-31'), m.recorded_at DESC, a.created_at, a.id LIMIT ?",
            params + [int(limit)])

    # --- savollar (yig'ilish chati) -----------------------------------------------

    def questions(self, meeting_id: str) -> list[dict[str, Any]]:
        """Faol (arxivlanmagan) savol-javoblar, YANGISI birinchi - eski `/questions` ro'yxati. Faqat hisob
        EGASINIKI (`asker IS NULL`): umumiy hisobdagi boshqa odamlarning (Slack) savollari ko'rinmaydi."""
        return self.rows("SELECT * FROM questions WHERE meeting_id=? AND archived_at IS NULL AND asker IS NULL "
                         "ORDER BY created_at DESC, rowid DESC", (meeting_id,))

    def chat_turns(self, meeting_id: str, limit: int = 0, *, asker: str | None = None) -> list[dict[str, Any]]:
        """Faol suhbat navbatlari, ESKISI birinchi - faqat shu so'rovchiniki (`asker`; `None` - hisob egasi).
        `limit` - faqat oxirgi shuncha navbat (0 - hammasi): modelga xotira uchun butun tarix o'qilmaydi."""
        where = "meeting_id=? AND archived_at IS NULL AND asker IS ?"
        if limit > 0:
            newest = self.rows(f"SELECT * FROM questions WHERE {where} ORDER BY created_at DESC, rowid DESC LIMIT ?",
                               (meeting_id, asker, int(limit)))
            return newest[::-1]
        return self.rows(f"SELECT * FROM questions WHERE {where} ORDER BY created_at, rowid", (meeting_id, asker))

    def archive_questions(self, meeting_id: str, at: float, *, asker: str | None = None) -> int:
        """Yangi suhbat: shu so'rovchining (`None` - hisob egasi) faol navbatlari arxivga (`archived_at`) -
        qatorlar o'chirilmaydi, boshqa so'rovchilarnikiga tegilmaydi. -> nechtasi."""
        return self.execute("UPDATE questions SET archived_at=? WHERE meeting_id=? AND archived_at IS NULL "
                            "AND asker IS ?", (int(at), meeting_id, asker)).rowcount

    def add_question(self, fields: dict[str, Any]) -> None:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self.execute(f"INSERT INTO questions ({cols}) VALUES ({marks})", tuple(fields.values()))

    #: Shu so'rovchining shu klient kalitli FAOL navbati - (yig'ilish, kalit, so'rovchi); `turn_by_client` va
    #: `add_turn` dagi takror tekshiruvi AYNAN bitta shart bilan.
    _BY_CLIENT = ("SELECT * FROM questions WHERE meeting_id=? AND client_id=? AND asker IS ? "
                  "AND archived_at IS NULL ORDER BY created_at, rowid LIMIT 1")

    def turn_by_client(self, meeting_id: str, client_id: str, *, asker: str | None = None) -> dict[str, Any] | None:
        """Shu so'rovchining (`None` - hisob egasi) shu klient kalitli FAOL navbati (`None` - yo'q): ilova xabarni
        qayta yuborgan - javob allaqachon saqlangan. Arxivdagisi hisobga olinmaydi."""
        return self.row(self._BY_CLIENT, (meeting_id, client_id, asker))

    def add_turn(self, fields: dict[str, Any], *, used: Iterable[str] = (), gen: int | None = None) -> dict[str, Any]:
        """Chat navbatini saqlaydi -> bazadagi qator (`archived_at` bilan). Javob kutilayotganda nima o'zgargani
        o'sha BITTA tranzaksiyada (`BEGIN IMMEDIATE`) tekshiriladi:

          * TAKROR (`fields["client_id"]`): shu so'rovchining shu kalitli FAOL navbati allaqachon bor (ilova qayta
            yubordi va birinchi urinish boshqa yo'ldan saqlab ulgurdi) - yangisi yozilmaydi, O'SHA qator qaytadi;
          * XOTIRA (`used` - javob qurilgan navbatlar id lari): "Yangi suhbat" (yoki qayta o'girish) ulardan birini
            arxivga o'tkazgan bo'lsa - yangi navbat ham O'SHA vaqt bilan arxivda tug'iladi: eski suhbat ustiga
            qurilgan javob yangi suhbatga xotira bo'lib o'tmasin;
          * MATN (`gen` - savol boshida o'qilgan `transcript_gen`): transkript butunlay almashgan (qayta o'girish
            tugagan) yoki endi tayyor emas (`transcript_ready`: qayta o'girilmoqda) - navbat HOZIRGI vaqt bilan
            arxivda tug'iladi. Xotirasiz birinchi savolni faqat shu ushlaydi: eski matn bo'yicha javob (manba id lari
            yangi matnda boshqa qatorni ko'rsatadi) faol qolmasin. Qator tahriri va spikerlarni birlashtirish
            (`transcript_rev`) bunga KIRMAYDI: qator id lari o'zgarmaydi, manbalar to'g'ri - navbat faol qoladi.

        NEGA VAQT BILAN EMAS ("tozalash so'rov boshlangandan keyinmi"): vaqt soniyagacha - tozalashdan keyin
        o'sha soniyada berilgan yangi savol ham "eski" bo'lib qolardi."""
        ids = [str(x) for x in used]
        with self.transaction() as conn:
            if fields.get("client_id"):
                same = conn.execute(self._BY_CLIENT, (fields["meeting_id"], fields["client_id"],
                                                      fields.get("asker"))).fetchone()
                if same is not None:
                    return dict(same)
            gone = None
            if ids:
                marks = ", ".join("?" for _ in ids)
                gone = conn.execute(f"SELECT MAX(archived_at) FROM questions WHERE id IN ({marks}) "
                                    "AND archived_at IS NOT NULL", ids).fetchone()[0]
            if gone is None and gen is not None:
                m = conn.execute("SELECT transcript_gen, transcript_rev, status, stt_engine FROM meetings WHERE id=?",
                                 (fields["meeting_id"],)).fetchone()
                # Yig'ilish o'chirilgan bo'lsa (`None`) - INSERT tashqi kalitdan yiqiladi (chaqiruvchida 404).
                if m is not None and (int(m["transcript_gen"] or 0) != int(gen) or not transcript_ready(dict(m))):
                    gone = int(time.time())
            row = dict(fields, archived_at=gone)
            conn.execute(f"INSERT INTO questions ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                         tuple(row.values()))
            return dict(conn.execute("SELECT * FROM questions WHERE id=?", (row["id"],)).fetchone())

    # --- kvota --------------------------------------------------------------------

    def add_usage(self, day: str, actor_id: int, audio_sec: float) -> None:
        """Odamning VA xizmatning (actor 0) kunlik daqiqasi. Diskda: GAPI
        klientining hisoblagichi restartda nolga tushadi, kvota esa yo'q."""
        with self.transaction() as conn:
            for actor in (int(actor_id), 0):
                conn.execute(
                    "INSERT INTO quota_days (day, actor_id, audio_sec, jobs) VALUES (?,?,?,1) "
                    "ON CONFLICT(day, actor_id) DO UPDATE SET audio_sec=audio_sec+excluded.audio_sec, "
                    "jobs=jobs+1", (day, actor, float(audio_sec)))

    def used_sec(self, day: str, actor_id: int) -> float:
        return float(self.scalar("SELECT audio_sec FROM quota_days WHERE day=? AND actor_id=?",
                                 (day, int(actor_id)), 0.0))

    def inflight_minutes(self, actor_id: int | None, *, exclude: str | None = None) -> int:
        """GAPI ga YUBORILGAN, natijasi hali kelmagan yozuvlar (daqiqa, har biri yuqoriga
        yaxlitlangan). `quota_days` faqat TUGAGAN vazifalarni biladi - bir vaqtda
        kelgan 4 ta yozuv shusiz hammasi kvotadan o'tib ketardi. `None` - butun xizmat."""
        sql = ("SELECT duration_sec FROM meetings WHERE status='transcribing' AND stt_engine='gapi' "
               "AND (stt_job_id IS NOT NULL OR stt_submitted_at IS NOT NULL) AND id<>?")
        params: list[Any] = [str(exclude or "")]
        if actor_id is not None:
            sql += " AND actor_id=?"
            params.append(int(actor_id))
        return sum(math.ceil(float(r["duration_sec"] or 0) / 60.0) for r in self.rows(sql, params))

    def job_ids_in_use(self, *, exclude: str) -> set[str]:
        """Boshqa yig'ilishlarga BOG'LANGAN GAPI vazifalari - tiklashda ularni olib bo'lmaydi."""
        return {str(r["stt_job_id"]) for r in self.rows(
            "SELECT stt_job_id FROM meetings WHERE stt_job_id IS NOT NULL AND id<>?", (str(exclude),))}

    # --- ishchi: navbat va ijara -------------------------------------------------

    def claim(self, owner: str, now: float, lease_sec: int, *, enabled: bool = True,
              exclude: Any = ()) -> dict[str, Any] | None:
        """Navbatdagi BITTA yig'ilishni ijaraga oladi (atomik).

        Ijara (`lease_until`) - jarayon yiqilsa ish yo'qolmasin: muddati
        o'tgan ijara boshqa ishchiga (yoki qayta ishga tushgan xizmatga) o'tadi.
        Navbat: ishlov kutayotgan holatlar, yoki tayyor yig'ilishning navbatdagi
        qo'shimcha xulosasi. `exclude` - SHU jarayonda hozir ishlanayotganlar:
        ijara muddati o'tsa ham ikkinchi ip ularni olmaydi."""
        if not enabled:
            return None
        t = int(now)
        skip = [str(x) for x in exclude]
        not_in = f"AND m.id NOT IN ({', '.join('?' for _ in skip)}) " if skip else ""
        with self.transaction() as conn:
            found = conn.execute(
                "SELECT id FROM meetings m WHERE "
                "(m.status IN ('uploaded','transcribing','summarizing','waiting_quota') "
                " OR (m.status='ready' AND EXISTS (SELECT 1 FROM summaries s WHERE s.meeting_id=m.id "
                "     AND s.status IN ('queued','running') AND COALESCE(s.next_attempt_at,0)<=?))) "
                "AND COALESCE(m.next_attempt_at, 0) <= ? AND COALESCE(m.lease_until, 0) < ? " + not_in +
                "ORDER BY COALESCE(m.next_attempt_at, 0), m.updated_at LIMIT 1", [t, t, t, *skip]).fetchone()
            if found is None:
                return None
            conn.execute("UPDATE meetings SET lease_owner=?, lease_until=? WHERE id=?",
                         (owner, t + int(lease_sec), found[0]))
            row = conn.execute("SELECT * FROM meetings WHERE id=?", (found[0],)).fetchone()
        return dict(row)

    def renew(self, meeting_id: str, owner: str, until: float) -> bool:
        """Ijarani uzaytiradi; `False` - ijara boshqaga o'tgan yoki yig'ilish o'chirilgan."""
        return self.execute("UPDATE meetings SET lease_until=? WHERE id=? AND lease_owner=?",
                            (int(until), meeting_id, owner)).rowcount == 1

    def release(self, meeting_id: str, owner: str) -> None:
        self.execute("UPDATE meetings SET lease_owner=NULL, lease_until=NULL WHERE id=? AND lease_owner=?",
                     (meeting_id, owner))

    def counts(self) -> dict[str, int]:
        return {r["status"]: int(r["n"]) for r in
                self.rows("SELECT status, COUNT(*) AS n FROM meetings GROUP BY status")}


def remove_file(path: Path | str | None) -> None:
    if not path:
        return
    with contextlib.suppress(FileNotFoundError, OSError):
        os.remove(path)

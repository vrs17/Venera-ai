"""Xodimlar ma'lumotnomasi: F.I.SH, Telegram, telefon, email.

NEGA VENERA'NING O'ZIDA. Ro'yxat kompaniyaning ichki kontaktlari - HRM da
Telegram va telefon yo'q, yuqoridagi yordamchi xizmat esa bu ro'yxatni
bilmaydi. Savol ("Azizov Boburning telefoni?") shu yerda, ro'yxatning o'zidan
javob oladi: tez, aniq va shaxsiy ma'lumot tashqi LLM ga CHIQMAYDI.

SAQLASH - SQLite (`data/contacts/contacts.db`, gitignore'da, 600). Nega JSON
emas: bir necha administrator bir vaqtda o'zgartirishi mumkin, va har
o'zgarish JURNALGA yoziladi (kim, qachon, nimani nimadan nimaga) - bu
tranzaksiya bilan ishonchli. O'chirish YUMSHOQ: xodim ro'yxatdan chiqadi,
yozuvi va tarixi qoladi.

BO'SH MAYDON NORMAL. Ro'yxatda hammaning ma'lumoti to'liq emas: `-` va yolg'iz
`+998` "kiritilmagan" deb saqlanadi va keyin to'ldiriladi.

QIDIRISH ISM BO'YICHA, imlo farqlariga chidamli: o'/o‘/oʻ, g'/g‘, x/h, kirill
yozuvi, qo'shimchalar ("Boburning", "Azizovga"), qisqa ism ("Bobur" ->
"Boburbek") va bitta harf xatosi ("Isroiliv" -> "Isroilov").
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sqlite3
import stat
import threading
import time

from dataclasses import dataclass
from pathlib import Path

from ..core.config import settings

log = logging.getLogger(__name__)

#: Tahrirlanadigan maydonlar va ularning ko'rinadigan nomi.
FIELDS = ("full_name", "phone", "telegram", "email")
LABELS = {"full_name": "F.I.SH", "phone": "Telefon", "telegram": "Telegram", "email": "Email"}

#: Bo'sh qiymat belgilari (ro'yxatdagi `-`).
_EMPTY = {"", "-", "—", "–", "@"}


class ContactError(ValueError):
    """Qiymat qabul qilinmadi - matni foydalanuvchiga ko'rsatiladi."""


@dataclass(frozen=True)
class Employee:
    id: int
    full_name: str
    phone: str | None
    telegram: str | None
    email: str | None
    updated_at: float = 0.0

    def get(self, field: str) -> str | None:
        return getattr(self, field)

    @property
    def short(self) -> str:
        """"Azizov Boburbek" - familiya va ism."""
        return " ".join(self.full_name.split()[:2])


# --- qiymatlarni tozalash ------------------------------------------------------


def clean_name(value: object) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:")
    if len(name.split()) < 2 or not re.search(r"[^\W\d_]{2}", name):
        raise ContactError("F.I.SH kamida familiya va ismdan iborat bo'lishi kerak")
    if len(name) > 120:
        raise ContactError("F.I.SH juda uzun")
    return name


def clean_phone(value: object) -> str | None:
    raw = str(value or "").strip()
    if raw in _EMPTY:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits in ("", "998"):
        return None
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) != 12 or not digits.startswith("998"):
        raise ContactError("Telefon raqami noto'g'ri - +998 XX XXX XX XX shaklida yozing")
    return "+" + digits


def clean_telegram(value: object) -> str | None:
    raw = str(value or "").strip()
    if raw in _EMPTY:
        return None
    raw = re.sub(r"^(?:https?://)?(?:t\.me|telegram\.me)/", "", raw, flags=re.IGNORECASE).lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", raw):
        raise ContactError("Telegram username noto'g'ri - @username shaklida yozing")
    return "@" + raw


def clean_email(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in _EMPTY:
        return None
    if not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", raw):
        raise ContactError("Email noto'g'ri")
    return raw


CLEANERS = {"full_name": clean_name, "phone": clean_phone,
            "telegram": clean_telegram, "email": clean_email}


# --- ism bo'yicha solishtirish ---------------------------------------------------

_APOS = re.compile(r"[‘’ʻʼ`´ʹ′']")
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}
#: Otasining ismidagi qo'shimcha so'zlar - solishtirishda kerak emas.
_PATRONYMIC_WORDS = {"o'g'li", "og'li", "o'gli", "ogli", "qizi"}
#: So'z oxiridagi qo'shimchalar: "Boburning", "Azizovga", "Malikani".
_SUFFIXES = ("larning", "lardan", "ning", "niki", "dagi", "dan", "ga", "ka", "qa",
             "da", "ni", "lar", "im", "i")


def fold(text: str) -> str:
    """Solishtirish shakli: kichik harf, apostroflar bitta, kirill -> lotin."""
    text = _APOS.sub("'", str(text).lower())
    return "".join(_CYR.get(ch, ch) for ch in text)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", fold(text))


def skeleton(token: str) -> str:
    """Imlo farqi yo'q shakl: apostrofsiz, x=h, takror harf bitta."""
    token = token.replace("'", "").replace("x", "h")
    return re.sub(r"(.)\1+", r"\1", token)


def stems(word: str) -> set[str]:
    """So'z va qo'shimchasiz shakllari."""
    out = {word}
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            out.add(word[: -len(suffix)])
    return out


def _distance(a: str, b: str, limit: int) -> int:
    """Levenshtein masofasi (`limit` dan oshsa - `limit + 1`)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def similar(query: str, name: str) -> float:
    """Savoldagi so'z ismning bir bo'lagiga qanchalik mos (0..1)."""
    if len(query) < 3:
        return 0.0
    if query == name:
        return 1.0
    q, n = skeleton(query), skeleton(name)
    if q == n:
        return 0.95
    if len(q) >= 4 and n.startswith(q):
        return 0.85                                   # "bobur" -> "boburbek"
    if len(q) >= 5 and len(n) >= 5:
        d = _distance(q, n, 2)
        if d == 1:
            return 0.8                                # "isroiliv" -> "isroilov"
        if d == 2 and min(len(q), len(n)) >= 8:
            return 0.7                                # "yuldashev" -> "yo'ldashov"
    return 0.0


def name_parts(full_name: str) -> list[str]:
    return [w for w in words(full_name) if w not in _PATRONYMIC_WORDS]


def match_score(employee: Employee, query_words: list[str]) -> float:
    """Familiya + ism (+ otasining ismi, kam og'irlik bilan)."""
    parts = name_parts(employee.full_name)
    if not parts:
        return 0.0
    candidates = [s for w in query_words for s in stems(w)]

    def best(part: str) -> float:
        return max((similar(c, part) for c in candidates), default=0.0)

    score = best(parts[0])
    if len(parts) > 1:
        score += best(parts[1])
    if len(parts) > 2:
        score += 0.3 * best(parts[2])
    return score


#: Shundan past - moslik emas. Bitta aniq bo'lak (familiya YOKI ism) 0.8+.
MIN_SCORE = 0.8
#: Eng yaxshisidan shuncha pastgacha - "teng" nomzodlar.
TIE_MARGIN = 0.25


# --- ombor ---------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,
    phone       TEXT,
    telegram    TEXT,
    email       TEXT,
    created_at  REAL NOT NULL,
    created_by  TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    updated_by  TEXT NOT NULL,
    deleted_at  REAL,
    deleted_by  TEXT
);
CREATE TABLE IF NOT EXISTS employee_changes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id  INTEGER NOT NULL,
    at           REAL NOT NULL,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    field        TEXT,
    old          TEXT,
    new          TEXT
);
"""


class ContactStore:
    """Xodimlar va o'zgarishlar jurnali. Har chaqiruv o'z ulanishi bilan -
    iplar orasida xavfsiz; yozuvlar tranzaksiyada."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            with self._lock:
                if not self._ready:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(self.path, timeout=10)
                    try:
                        conn.executescript(_SCHEMA)
                        conn.commit()
                    finally:
                        conn.close()
                    # Shaxsiy ma'lumot: faqat egasi o'qiy oladi.
                    os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
                    self._ready = True
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextlib.contextmanager
    def _tx(self):
        """Bitta tranzaksiya: xato bo'lsa hammasi bekor, oxirida ulanish YOPILADI."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # --- o'qish ---

    def all(self) -> list[Employee]:
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM employees WHERE deleted_at IS NULL ORDER BY full_name").fetchall()
        return [_employee(r) for r in rows]

    def get(self, employee_id: int) -> Employee | None:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM employees WHERE id = ? AND deleted_at IS NULL",
                               (employee_id,)).fetchone()
        return _employee(row) if row else None

    def count(self) -> int:
        with self._tx() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM employees WHERE deleted_at IS NULL").fetchone()[0])

    def find(self, text: str) -> list[tuple[Employee, float]]:
        """Matndagi ism bo'yicha nomzodlar - eng mosi birinchi, "teng"lari bilan."""
        query = words(text)
        scored = [(e, match_score(e, query)) for e in self.all()]
        scored = [(e, s) for e, s in scored if s >= MIN_SCORE]
        if not scored:
            return []
        top = max(s for _, s in scored)
        return sorted(((e, s) for e, s in scored if s >= top - TIE_MARGIN), key=lambda x: -x[1])

    def history(self, employee_id: int, limit: int = 20) -> list[dict]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT at, actor, action, field, old, new FROM employee_changes "
                "WHERE employee_id = ? ORDER BY id DESC LIMIT ?", (employee_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # --- yozish ---

    def add(self, values: dict[str, str | None], *, actor: str) -> Employee:
        clean = {f: CLEANERS[f](values.get(f)) for f in FIELDS}
        now = time.time()
        with self._tx() as conn:
            _check_unique(conn, clean, exclude=None)
            cur = conn.execute(
                "INSERT INTO employees (full_name, phone, telegram, email, created_at, created_by, "
                "updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (clean["full_name"], clean["phone"], clean["telegram"], clean["email"], now, actor, now, actor))
            employee_id = int(cur.lastrowid)
            for field in FIELDS:
                if clean[field]:
                    _journal(conn, employee_id, now, actor, "create", field, None, clean[field])
        log.info("Xodim qo'shildi: #%s (%s)", employee_id, actor)
        return self.get(employee_id)  # type: ignore[return-value]

    def update(self, employee_id: int, changes: dict[str, str | None], *, actor: str,
               expect: dict[str, str | None] | None = None) -> Employee:
        """`expect` - taklif paytidagi qiymatlar: shu orada boshqa odam
        o'zgartirgan bo'lsa, ustidan yozilmaydi."""
        clean = {f: CLEANERS[f](v) for f, v in changes.items() if f in FIELDS}
        if not clean:
            raise ContactError("O'zgartiriladigan maydon yo'q")
        now = time.time()
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM employees WHERE id = ? AND deleted_at IS NULL",
                               (employee_id,)).fetchone()
            if row is None:
                raise ContactError("Xodim topilmadi (o'chirilgan bo'lishi mumkin)")
            for field, old in (expect or {}).items():
                if row[field] != old:
                    raise ContactError("Ma'lumot shu orada o'zgargan - qaytadan so'rang")
            _check_unique(conn, clean, exclude=employee_id)
            for field, new in clean.items():
                if row[field] != new:
                    _journal(conn, employee_id, now, actor, "update", field, row[field], new)
            assignments = ", ".join(f"{f} = ?" for f in clean)
            conn.execute(f"UPDATE employees SET {assignments}, updated_at = ?, updated_by = ? WHERE id = ?",
                         (*clean.values(), now, actor, employee_id))
        log.info("Xodim o'zgartirildi: #%s %s (%s)", employee_id, ",".join(clean), actor)
        return self.get(employee_id)  # type: ignore[return-value]

    def delete(self, employee_id: int, *, actor: str) -> Employee:
        now = time.time()
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM employees WHERE id = ? AND deleted_at IS NULL",
                               (employee_id,)).fetchone()
            if row is None:
                raise ContactError("Xodim topilmadi (allaqachon o'chirilgan bo'lishi mumkin)")
            conn.execute("UPDATE employees SET deleted_at = ?, deleted_by = ? WHERE id = ?",
                         (now, actor, employee_id))
            _journal(conn, employee_id, now, actor, "delete", None, None, None)
        log.info("Xodim o'chirildi: #%s (%s)", employee_id, actor)
        return _employee(row)

    def restore(self, employee_id: int, *, actor: str) -> Employee:
        now = time.time()
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM employees WHERE id = ? AND deleted_at IS NOT NULL",
                               (employee_id,)).fetchone()
            if row is None:
                raise ContactError("O'chirilgan xodim topilmadi")
            conn.execute("UPDATE employees SET deleted_at = NULL, deleted_by = NULL, updated_at = ?, "
                         "updated_by = ? WHERE id = ?", (now, actor, employee_id))
            _journal(conn, employee_id, now, actor, "restore", None, None, None)
        return self.get(employee_id)  # type: ignore[return-value]


def _employee(row: sqlite3.Row) -> Employee:
    return Employee(id=int(row["id"]), full_name=row["full_name"], phone=row["phone"],
                    telegram=row["telegram"], email=row["email"], updated_at=float(row["updated_at"]))


def _journal(conn, employee_id, at, actor, action, field, old, new) -> None:
    conn.execute("INSERT INTO employee_changes (employee_id, at, actor, action, field, old, new) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)", (employee_id, at, actor, action, field, old, new))


def _check_unique(conn: sqlite3.Connection, clean: dict[str, str | None], *, exclude: int | None) -> None:
    """Bir telefon, Telegram yoki email ikki xodimda bo'lmasin."""
    for field in ("phone", "telegram", "email"):
        value = clean.get(field)
        if not value:
            continue
        row = conn.execute(
            f"SELECT full_name FROM employees WHERE lower({field}) = lower(?) AND deleted_at IS NULL "
            "AND id IS NOT ?", (value, exclude)).fetchone()
        if row is not None:
            raise ContactError(f"Bu {LABELS[field].lower()} boshqa xodimda bor: {row['full_name']}")


#: Jonli ombor - testlar vaqtinchalik fayl bilan almashtiradi (`conftest.py`).
store = ContactStore(settings.contacts_db)

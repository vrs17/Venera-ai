"""Barno konnektori ombori - `data/connector/connector.db` (`docs/barno-connector.md`).

    clients    Claude / ChatGPT mijozlari: CIMD (URL kimlik) yoki DCR (biz bergan id)
    requests   `/oauth/authorize` dan kelgan, odam hali javob bermagan so'rovlar (10 daqiqa)
    codes      bir martalik avtorizatsiya kodlari (HASH, 5 daqiqa, PKCE bilan)
    grants     odamning ruxsati: qaysi ilovaga, qaysi qamrov (`plaud.read`), qachon
    tokens     access / refresh tokenlar - faqat HASH (SHA-256), ruxsatga bog'langan
    calls      murojaat jurnali: kim, qaysi ilova, qaysi vosita, holat, vaqt, hajm - MATN YO'Q

NEGA SHAFFOF EMAS (JWT EMAS). Token - tasodifiy satr, serverda faqat xeshi. Ruxsat bekor
qilinsa yoki admin o'chirsa, keyingi chaqiruvdayoq ishlamaydi - JWT bo'lsa muddati
tugaguncha yurardi. Ombor o'g'irlansa ham tokenlarning o'zi yo'q.

NEGA `subject` (actor_id emas). Har chaqiruvda odam sayt tokenidagi kabi qayta topiladi
(`deps.user_for_subject`): bloklangan hisob va "hamma joydan chiqarish" (`token_version`)
konnektorni ham o'sha zahoti to'xtatadi.

Fayl SHAXSIY ma'lumot bilan: papka 700, fayl 600, `data/` gitignore'da.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    client_id     TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,              -- cimd | dcr
    name          TEXT NOT NULL,
    redirect_uris TEXT NOT NULL,              -- JSON ro'yxat
    metadata      TEXT NOT NULL DEFAULT '{}', -- mijoz hujjati (CIMD) yoki DCR tanasi
    created_at    REAL NOT NULL,
    fetched_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    id             TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT '',
    code_challenge TEXT NOT NULL,
    scopes         TEXT NOT NULL,             -- bo'shliq bilan
    resource       TEXT NOT NULL,
    created_at     REAL NOT NULL,
    expires_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS codes (
    code_hash      TEXT PRIMARY KEY,
    grant_id       TEXT NOT NULL,
    client_id      TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    resource       TEXT NOT NULL,
    expires_at     REAL NOT NULL,
    used_at        REAL
);
CREATE TABLE IF NOT EXISTS grants (
    id            TEXT PRIMARY KEY,
    subject       TEXT NOT NULL,
    actor_id      INTEGER NOT NULL,
    token_version INTEGER,
    client_id     TEXT NOT NULL,
    client_name   TEXT NOT NULL,
    scopes        TEXT NOT NULL,
    resource      TEXT NOT NULL,
    created_at    REAL NOT NULL,
    last_used_at  REAL,
    revoked_at    REAL
);
CREATE INDEX IF NOT EXISTS grants_actor ON grants (actor_id, revoked_at);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash TEXT PRIMARY KEY,
    grant_id   TEXT NOT NULL,
    kind       TEXT NOT NULL,                 -- access | refresh
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at    REAL                           -- refresh: aylantirilgan payt
);
CREATE INDEX IF NOT EXISTS tokens_grant ON tokens (grant_id);
CREATE TABLE IF NOT EXISTS calls (
    ts         REAL NOT NULL,
    grant_id   TEXT NOT NULL,
    actor_id   INTEGER NOT NULL,
    client_id  TEXT NOT NULL,
    tool       TEXT NOT NULL,
    status     TEXT NOT NULL,                 -- ok | error | denied
    ms         INTEGER NOT NULL,
    out_bytes  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_actor ON calls (actor_id, ts);
CREATE INDEX IF NOT EXISTS calls_grant ON calls (grant_id, ts);
"""

#: Kutilayotgan so'rov va kod umri (soniya).
REQUEST_TTL = 600
CODE_TTL = 300
#: Bitta odamning jonli ruxsatlari chegarasi. Bitta ilova (CIMD - masalan hamma Claude Code
#: nusxalari bitta `client_id`) bir necha qurilma yoki hisobdan ulanishi normal, shuning uchun
#: yangi rozilik eskisini UZMAYDI; chegaradan oshsa - eng uzoq ishlatilmagani uziladi.
MAX_GRANTS_PER_ACTOR = 20
#: Murojaat jurnali qancha saqlanadi va qanchada bir tozalanadi (soniya).
CALLS_KEEP = 90 * 24 * 3600
CALLS_PRUNE_EVERY = 3600


def digest(raw: str) -> str:
    """Token / kod -> saqlanadigan xesh. Tasodifiy 256 bit - tuz kerak emas."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Client:
    client_id: str
    kind: str
    name: str
    redirect_uris: tuple[str, ...]
    fetched_at: float


@dataclass(frozen=True)
class Pending:
    id: str
    client_id: str
    redirect_uri: str
    state: str
    code_challenge: str
    scopes: frozenset[str]
    resource: str
    expires_at: float


@dataclass(frozen=True)
class GrantRow:
    id: str
    subject: str
    actor_id: int
    token_version: int | None
    client_id: str
    client_name: str
    scopes: frozenset[str]
    resource: str
    created_at: float
    last_used_at: float | None
    revoked_at: float | None


@dataclass(frozen=True)
class Issued:
    access_token: str
    refresh_token: str
    expires_in: int
    scopes: frozenset[str]


def _scopes(text: str) -> frozenset[str]:
    return frozenset(part for part in (text or "").split() if part)


def _grant(row: sqlite3.Row) -> GrantRow:
    return GrantRow(id=row["id"], subject=row["subject"], actor_id=int(row["actor_id"]),
                    token_version=row["token_version"], client_id=row["client_id"],
                    client_name=row["client_name"], scopes=_scopes(row["scopes"]),
                    resource=row["resource"], created_at=row["created_at"],
                    last_used_at=row["last_used_at"], revoked_at=row["revoked_at"])


class ConnectorStore:
    """Bitta SQLite fayl, bitta qulf. Yuk kichik (har MCP chaqiruvi - bitta o'qish va bitta
    jurnal yozuvi), shuning uchun ulanish har amalda ochiladi - iplar orasida bo'linmaydi."""

    def __init__(self, path: Path, *, clock=time.time) -> None:
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()
        self._ready = False
        self._calls_pruned_at = 0.0

    # --- ulanish -----------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        if not self._ready:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA secure_delete=ON")
            conn.executescript(SCHEMA)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            self._ready = True
        return conn

    def _run(self, fn):
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    return fn(conn)
            finally:
                conn.close()

    # --- mijozlar ----------------------------------------------------------------------------

    def put_client(self, client_id: str, kind: str, name: str, redirect_uris: list[str],
                   metadata: dict[str, Any]) -> Client:
        now = self._clock()

        def run(conn: sqlite3.Connection) -> Client:
            conn.execute(
                "INSERT INTO clients (client_id, kind, name, redirect_uris, metadata, created_at, "
                "fetched_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(client_id) DO UPDATE SET "
                "name=excluded.name, redirect_uris=excluded.redirect_uris, "
                "metadata=excluded.metadata, fetched_at=excluded.fetched_at",
                (client_id, kind, name[:120], json.dumps(redirect_uris),
                 json.dumps(metadata, ensure_ascii=False)[:20000], now, now))
            return Client(client_id, kind, name[:120], tuple(redirect_uris), now)

        return self._run(run)

    def client(self, client_id: str) -> Client | None:
        def run(conn: sqlite3.Connection) -> Client | None:
            row = conn.execute("SELECT * FROM clients WHERE client_id=?", (client_id,)).fetchone()
            if row is None:
                return None
            return Client(row["client_id"], row["kind"], row["name"],
                          tuple(json.loads(row["redirect_uris"])), row["fetched_at"])

        return self._run(run)

    def prune_dcr(self, *, idle_seconds: int, unused_seconds: int = 3600) -> int:
        """DCR mijozlarini tozalaydi (Claude har yangi ulanishda yangisini ro'yxatdan o'tkazadi):

          * hech qachon ruxsatga yetmagan va `unused_seconds` dan eski (kutilayotgan so'rov
            yoki kod yo'q) - ro'yxatdan o'tib tashlab ketilgan yoki SUN'IY to'ldirilgan;
          * `idle_seconds` dan eski va jonli ruxsati yo'q.

        Qaytaradi: nechta o'chdi."""
        now = self._clock()
        busy = ("client_id NOT IN (SELECT client_id FROM requests WHERE expires_at >= :now) "
                "AND client_id NOT IN (SELECT client_id FROM codes WHERE expires_at >= :now)")

        def run(conn: sqlite3.Connection) -> int:
            unused = conn.execute(
                f"DELETE FROM clients WHERE kind='dcr' AND created_at < :cut AND {busy} "
                "AND client_id NOT IN (SELECT client_id FROM grants)",
                {"cut": now - unused_seconds, "now": now}).rowcount
            idle = conn.execute(
                f"DELETE FROM clients WHERE kind='dcr' AND created_at < :cut AND {busy} "
                "AND client_id NOT IN (SELECT client_id FROM grants WHERE revoked_at IS NULL)",
                {"cut": now - idle_seconds, "now": now}).rowcount
            return unused + idle

        return self._run(run)

    def evict_unused_dcr(self, count: int) -> int:
        """Chegara to'lganda: eng eski, hech qachon ruxsatga yetmagan va hozir oqimda bo'lmagan
        `count` ta DCR mijozini o'chiradi - begona to'ldirish haqiqiy ulanishni 503 bilan
        to'smasin. Qaytaradi: nechta o'chdi."""
        now = self._clock()
        return self._run(lambda conn: conn.execute(
            "DELETE FROM clients WHERE client_id IN (SELECT client_id FROM clients WHERE kind='dcr' "
            "AND client_id NOT IN (SELECT client_id FROM grants) "
            "AND client_id NOT IN (SELECT client_id FROM requests WHERE expires_at >= :now) "
            "AND client_id NOT IN (SELECT client_id FROM codes WHERE expires_at >= :now) "
            "ORDER BY created_at ASC LIMIT :n)", {"now": now, "n": int(count)}).rowcount)

    def count_clients(self, kind: str) -> int:
        return self._run(lambda conn: conn.execute(
            "SELECT COUNT(*) FROM clients WHERE kind=?", (kind,)).fetchone()[0])

    # --- kutilayotgan so'rovlar ----------------------------------------------------------------

    def put_request(self, client_id: str, redirect_uri: str, state: str, code_challenge: str,
                    scopes: frozenset[str], resource: str) -> Pending:
        now = self._clock()
        pending = Pending(new_secret(), client_id, redirect_uri, state, code_challenge,
                          scopes, resource, now + REQUEST_TTL)

        def run(conn: sqlite3.Connection) -> Pending:
            conn.execute("DELETE FROM requests WHERE expires_at < ?", (now,))
            conn.execute(
                "INSERT INTO requests (id, client_id, redirect_uri, state, code_challenge, scopes, "
                "resource, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (pending.id, client_id, redirect_uri, state, code_challenge,
                 " ".join(sorted(scopes)), resource, now, pending.expires_at))
            return pending

        return self._run(run)

    def request(self, request_id: str) -> Pending | None:
        now = self._clock()

        def run(conn: sqlite3.Connection) -> Pending | None:
            row = conn.execute("SELECT * FROM requests WHERE id=? AND expires_at >= ?",
                               (request_id, now)).fetchone()
            if row is None:
                return None
            return Pending(row["id"], row["client_id"], row["redirect_uri"], row["state"],
                           row["code_challenge"], _scopes(row["scopes"]), row["resource"],
                           row["expires_at"])

        return self._run(run)

    def drop_request(self, request_id: str) -> bool:
        """So'rovni O'CHIRADI (bir martalik). `True` - u bor edi."""
        return self._run(lambda conn: conn.execute(
            "DELETE FROM requests WHERE id=?", (request_id,)).rowcount > 0)

    # --- ruxsat va kod -------------------------------------------------------------------------

    def approve(self, pending: Pending, *, subject: str, actor_id: int, token_version: int | None,
                client_name: str, scopes: frozenset[str]) -> str:
        """Odam "Ruxsat berish" dedi: so'rov yonadi, ruxsat yoziladi, bir martalik kod qaytadi.

        Oldingi ruxsatlar UZILMAYDI: CIMD da `client_id` - mahsulotning bitta URL i (hamma
        Claude Code nusxalari, hamma ChatGPT hisoblari), ya'ni "bitta ilova - bitta ruxsat"
        ikkinchi qurilmani birinchisini uzishga majbur qilardi. Eskisini odam "Ulangan
        ilovalar" dan uzadi; `MAX_GRANTS_PER_ACTOR` dan oshsa - eng uzoq ishlatilmagani."""
        now = self._clock()
        code = new_secret()
        grant_id = new_secret()

        def run(conn: sqlite3.Connection) -> str:
            if conn.execute("DELETE FROM requests WHERE id=? AND expires_at >= ?",
                            (pending.id, now)).rowcount == 0:
                raise LookupError("request")
            live = [r["id"] for r in conn.execute(
                "SELECT id FROM grants WHERE actor_id=? AND revoked_at IS NULL "
                "ORDER BY COALESCE(last_used_at, created_at) ASC", (actor_id,))]
            for gid in live[:max(0, len(live) - MAX_GRANTS_PER_ACTOR + 1)]:
                conn.execute("UPDATE grants SET revoked_at=? WHERE id=?", (now, gid))
                conn.execute("DELETE FROM tokens WHERE grant_id=?", (gid,))
            conn.execute(
                "INSERT INTO grants (id, subject, actor_id, token_version, client_id, client_name, "
                "scopes, resource, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (grant_id, subject, actor_id, token_version, pending.client_id, client_name[:120],
                 " ".join(sorted(scopes)), pending.resource, now))
            conn.execute(
                "INSERT INTO codes (code_hash, grant_id, client_id, redirect_uri, code_challenge, "
                "resource, expires_at) VALUES (?,?,?,?,?,?,?)",
                (digest(code), grant_id, pending.client_id, pending.redirect_uri,
                 pending.code_challenge, pending.resource, now + CODE_TTL))
            return code

        return self._run(run)

    def redeem(self, code: str, *, client_id: str, redirect_uri: str, resource: str | None,
               verify) -> tuple[GrantRow, str]:
        """Kod -> (ruxsat, code_challenge). `verify(challenge)` - PKCE tekshiruvi (chaqiruvchida).

        Kod BIR MARTA: ikkinchi urinish (`used_at` bor) - kod o'g'irlangan bo'lishi mumkin,
        shuning uchun shu kod bilan berilgan ruxsat ham BEKOR qilinadi (OAuth 2.1, 4.1.3)."""
        now = self._clock()

        def run(conn: sqlite3.Connection) -> tuple[GrantRow, str] | None:
            row = conn.execute("SELECT * FROM codes WHERE code_hash=?", (digest(code),)).fetchone()
            if row is None or row["expires_at"] < now:
                raise LookupError("invalid_grant")
            if row["used_at"] is not None:
                # Bekor qilish SAQLANSIN: bu yerda `raise` tranzaksiyani orqaga qaytarardi.
                conn.execute("UPDATE grants SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                             (now, row["grant_id"]))
                conn.execute("DELETE FROM tokens WHERE grant_id=?", (row["grant_id"],))
                return None
            if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
                raise LookupError("invalid_grant")
            if resource is not None and resource != row["resource"]:
                raise LookupError("invalid_target")
            if not verify(row["code_challenge"]):
                raise LookupError("invalid_grant")
            conn.execute("UPDATE codes SET used_at=? WHERE code_hash=?", (now, row["code_hash"]))
            grant = conn.execute("SELECT * FROM grants WHERE id=? AND revoked_at IS NULL",
                                 (row["grant_id"],)).fetchone()
            if grant is None:
                raise LookupError("invalid_grant")
            return _grant(grant), row["code_challenge"]

        found = self._run(run)
        if found is None:
            raise LookupError("invalid_grant")
        return found

    # --- tokenlar ------------------------------------------------------------------------------

    def issue(self, grant_id: str, *, access_ttl: int, refresh_ttl: int) -> Issued:
        now = self._clock()
        access, refresh = new_secret(), new_secret()

        def run(conn: sqlite3.Connection) -> Issued:
            grant = conn.execute("SELECT * FROM grants WHERE id=? AND revoked_at IS NULL",
                                 (grant_id,)).fetchone()
            if grant is None:
                raise LookupError("invalid_grant")
            conn.execute("DELETE FROM tokens WHERE grant_id=? AND expires_at < ?", (grant_id, now))
            conn.executemany(
                "INSERT INTO tokens (token_hash, grant_id, kind, created_at, expires_at) "
                "VALUES (?,?,?,?,?)",
                [(digest(access), grant_id, "access", now, now + access_ttl),
                 (digest(refresh), grant_id, "refresh", now, now + refresh_ttl)])
            return Issued(access, refresh, int(access_ttl), _scopes(grant["scopes"]))

        return self._run(run)

    def rotate(self, refresh_token: str, *, client_id: str, resource: str | None,
               access_ttl: int, refresh_ttl: int) -> Issued:
        """Refresh token -> yangi juft; eskisi yonadi. Yongan refresh qayta kelsa - token
        o'g'irlangan bo'lishi mumkin: butun ruxsat bekor (OAuth 2.1, 4.3.1)."""
        now = self._clock()

        def run(conn: sqlite3.Connection) -> str | None:
            row = conn.execute("SELECT * FROM tokens WHERE token_hash=? AND kind='refresh'",
                               (digest(refresh_token),)).fetchone()
            if row is None or row["expires_at"] < now:
                raise LookupError("invalid_grant")
            if row["used_at"] is not None:
                conn.execute("UPDATE grants SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                             (now, row["grant_id"]))
                conn.execute("DELETE FROM tokens WHERE grant_id=?", (row["grant_id"],))
                return None
            grant = conn.execute("SELECT * FROM grants WHERE id=? AND revoked_at IS NULL",
                                 (row["grant_id"],)).fetchone()
            if grant is None or grant["client_id"] != client_id:
                raise LookupError("invalid_grant")
            if resource is not None and resource != grant["resource"]:
                raise LookupError("invalid_target")
            conn.execute("UPDATE tokens SET used_at=? WHERE token_hash=?", (now, row["token_hash"]))
            return row["grant_id"]

        grant_id = self._run(run)
        if grant_id is None:
            raise LookupError("invalid_grant")
        return self.issue(grant_id, access_ttl=access_ttl, refresh_ttl=refresh_ttl)

    def access(self, access_token: str) -> GrantRow | None:
        """Access token -> jonli ruxsat yoki `None` (yo'q, muddati o'tgan, bekor qilingan)."""
        now = self._clock()

        def run(conn: sqlite3.Connection) -> GrantRow | None:
            row = conn.execute(
                "SELECT g.* FROM tokens t JOIN grants g ON g.id = t.grant_id "
                "WHERE t.token_hash=? AND t.kind='access' AND t.expires_at >= ? "
                "AND g.revoked_at IS NULL", (digest(access_token), now)).fetchone()
            return _grant(row) if row is not None else None

        return self._run(run)

    def revoke_token(self, token: str) -> None:
        """RFC 7009: token (access yoki refresh) -> butun ruxsat bekor. Noma'lum token - jim."""
        now = self._clock()

        def run(conn: sqlite3.Connection) -> None:
            row = conn.execute("SELECT grant_id FROM tokens WHERE token_hash=?",
                               (digest(token),)).fetchone()
            if row is not None:
                conn.execute("UPDATE grants SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                             (now, row["grant_id"]))
                conn.execute("DELETE FROM tokens WHERE grant_id=?", (row["grant_id"],))

        self._run(run)

    # --- odamning ruxsatlari (Sozlamalar -> "Ulangan ilovalar") --------------------------------

    def grants_of(self, actor_id: int) -> list[GrantRow]:
        return self._run(lambda conn: [_grant(r) for r in conn.execute(
            "SELECT * FROM grants WHERE actor_id=? AND revoked_at IS NULL ORDER BY created_at DESC",
            (actor_id,))])

    def revoke_grant(self, actor_id: int, grant_id: str) -> bool:
        """Faqat O'Z ruxsati (`actor_id` bilan) - boshqa odamning id sini bilib qolgan ham
        uza olmaydi. `True` - bekor qilindi."""
        now = self._clock()

        def run(conn: sqlite3.Connection) -> bool:
            done = conn.execute("UPDATE grants SET revoked_at=? WHERE id=? AND actor_id=? "
                                "AND revoked_at IS NULL", (now, grant_id, actor_id)).rowcount > 0
            if done:
                conn.execute("DELETE FROM tokens WHERE grant_id=?", (grant_id,))
            return done

        return self._run(run)

    # --- jurnal --------------------------------------------------------------------------------

    def record_call(self, grant: GrantRow, tool: str, status: str, ms: int, out_bytes: int) -> None:
        now = self._clock()
        prune = now - self._calls_pruned_at >= CALLS_PRUNE_EVERY
        if prune:
            self._calls_pruned_at = now

        def run(conn: sqlite3.Connection) -> None:
            if prune:
                # Jurnal cheksiz o'smasin (har chaqiruv - bitta qator): 90 kundan eskisi o'chadi.
                conn.execute("DELETE FROM calls WHERE ts < ?", (now - CALLS_KEEP,))
            conn.execute("INSERT INTO calls (ts, grant_id, actor_id, client_id, tool, status, ms, "
                         "out_bytes) VALUES (?,?,?,?,?,?,?,?)",
                         (now, grant.id, grant.actor_id, grant.client_id, tool[:64], status[:16],
                          int(ms), int(out_bytes)))
            conn.execute("UPDATE grants SET last_used_at=? WHERE id=?", (now, grant.id))

        self._run(run)

    def calls_since(self, grant_id: str, since: float) -> int:
        """Shu ruxsat bilan `since` dan beri BAJARILGAN chaqiruvlar soni - tezlik chegarasi uchun.
        Rad etilganlari (`denied`) sanalmaydi: aks holda to'xtamay so'rayotgan mijoz chegaradan
        hech qachon chiqmasdi (har rad yangi "chaqiruv" bo'lib qo'shilardi)."""
        return self._run(lambda conn: conn.execute(
            "SELECT COUNT(*) FROM calls WHERE grant_id=? AND ts >= ? AND status != 'denied'",
            (grant_id, since)).fetchone()[0])

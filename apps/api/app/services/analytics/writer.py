"""Yozuvchi ip: analitika yozuvlarining HAMMASI shu yerdan diskka tushadi.

NEGA ALOHIDA IP. Chat oqimi kadrma-kadr ketadi va har bir kechikish
foydalanuvchiga ko'rinadi. SQLite yozuvi esa diskni kutadi (`fsync`) va
bir vaqtda faqat BITTA yozuvchiga ruxsat beradi - so'rov iplari o'zi
yozganda ular bir-birini navbatda kutib, javobni sekinlatardi. Shuning uchun
so'rov yo'li faqat navbatga qo'yadi (mikrosoniyalar), yozishni esa bitta ip
to'plab bajaradi.

TO'PLAM: 200 ta amal yoki 250 ms - qaysi biri oldin kelsa. Bitta
tranzaksiya = bitta `fsync`, ya'ni yuk ostida yuzlab qator bir yozuv narxiga
tushadi. Ketma-ket kelgan bir xil SQL `executemany` bilan bajariladi.

CHEGARA: navbat 10 000 ta. To'lsa yangi yozuv TASHLANADI va hisoblanadi
(`dropped`, `/admin/system` da ko'rinadi). Kutish o'rniga tashlash -
ataylab: disk qotib qolsa ham chat ishlashda davom etishi kerak, analitika
esa ikkinchi darajali.

XATO HECH QACHON CHAQIRUVCHIGA QAYTMAYDI. Bitta buzuq yozuv butun to'plamni
ham yo'qotmaydi: to'plam xato bersa, u yozuvlar bittadan qayta yoziladi va
faqat buzug'i tashlanadi.

ESKI YOZUVLAR har 6 soatda tozalanadi (`purge`): `turns` (hodisalari va
manbalari bilan), `api_calls`, `auth_events`. Shikoyatlar va audit
SAQLANADI - ular hujjat, statistika emas.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import queue
import sqlite3
import threading
import time

from typing import Any, Callable, Sequence

from . import db as _db
from .db import Database, Params, iter_chunks, log_limited

log = logging.getLogger(__name__)

#: Navbat turlari.
_SQL = "sql"            # (tur, sql, params)
_MANY = "many"          # (tur, sql, [params, ...])
_CALL = "call"          # (tur, fn, None) - fn(conn), yozuvchi ipda
_FLUSH = "flush"        # (tur, Event, None)
_STOP = "stop"          # (tur, Event, None)

#: Tozalash bitta tranzaksiyada shuncha qatordan oshmaydi: 180 kunlik eski
#: yozuvlarni BIR YO'LA o'chirish yozuv qulfini soniyalab ushlab, shu paytda
#: kelgan chat yozuvlarini kutdirardi.
_PURGE_CHUNK = 500


class Writer:
    """Bitta fon ipi, chegaralangan navbat, to'plab yozish.

    `db` berilmasa umumiy ombor (`db.get_db()`) - birinchi yozuvda olinadi.
    `autostart=False` - ip birinchi `submit` da emas, faqat `start()` da
    ishga tushadi (testlarda navbat to'lishini ko'rish uchun).
    """

    def __init__(
        self,
        db: Database | None = None,
        *,
        max_queue: int = 10_000,
        batch_max: int = 200,
        batch_wait: float = 0.25,
        purge_every: float = 6 * 3600.0,
        purge_first: float = 60.0,
        retention_days: int | None = None,
        autostart: bool = True,
    ) -> None:
        self._db = db
        self.max_queue = max(1, int(max_queue))
        self.batch_max = max(1, int(batch_max))
        self.batch_wait = max(0.0, float(batch_wait))
        self.purge_every = float(purge_every)
        #: Birinchi tozalash ishga tushgandan KEYIN, darhol emas: ilova
        #: ochilayotgan paytda diskni band qilmaslik uchun.
        self.purge_first = float(purge_first)
        self._retention = retention_days
        self.autostart = autostart
        self._queue: queue.Queue = queue.Queue(maxsize=self.max_queue)
        self._thread: threading.Thread | None = None
        # Ishga tushirish qulfi BLOKLAMASDAN olinadi (`start`). `Thread.start()`
        # xotira ajratadi va o'sha lahzada - yangi ipning boshlanishida ham - GC
        # ishlab ketishi mumkin; GC esa `weakref.finalize` (TTS oqimi hisobi,
        # `services/tts.py`) orqali `record_call` -> `submit` -> `start()` ni
        # chaqiradi. Kutadigan qulf bilan bu o'z-o'zini (yoki ishga tushayotgan ip
        # bilan bir-birini) abadiy kutishga olib kelardi - testlarda ushlangan:
        # `test_tts.py` osilib qoldi. Qulf band bo'lsa ip allaqachon ishga
        # tushirilmoqda: yozuv navbatda turadi va o'sha ip uni o'qiydi.
        self._start_lock = threading.Lock()
        self._stopped = False
        # Hisoblagichlar - `/admin/system` uchun. Bitta ip yozadi, qolganlar
        # faqat o'qiydi; `dropped` esa ko'p ipdan - shuning uchun qulf bilan.
        self._count_lock = threading.Lock()
        self._dropped = 0
        self._written = 0
        self._errors = 0
        self._batches = 0
        self._max_batch = 0
        self._purged: dict[str, int] = {}
        self._last_purge_at: float | None = None

    # --- ombor ---

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = _db.get_db()
        return self._db

    # --- navbatga qo'yish (so'rov iplari) ---

    def submit(self, sql: str, params: Params = ()) -> bool:
        """Bitta yozuv. `False` - navbat to'la yoki yozuvchi to'xtagan
        (yozuv tashlandi va hisoblandi). HECH QACHON xato bermaydi."""
        return self._put((_SQL, sql, params))

    def submit_many(self, sql: str, rows: Sequence[Params]) -> bool:
        """Bitta SQL, ko'p qator - `executemany` bilan, BITTA navbat
        elementi sifatida (turn hodisalari kabi)."""
        rows = list(rows)
        if not rows:
            return True
        return self._put((_MANY, sql, rows))

    def call(self, fn: Callable[[sqlite3.Connection], Any]) -> bool:
        """Ixtiyoriy yozuv funksiyasi - yozuvchi ipda, to'plam tranzaksiyasi
        ichida (o'z SAVEPOINT'ida). Xato bersa faqat shu funksiya bekor
        bo'ladi. Ichida `Database.transaction()` CHAQIRILMAYDI - tranzaksiya
        allaqachon ochiq."""
        return self._put((_CALL, fn, None))

    def _put(self, item: tuple) -> bool:
        try:
            if self._stopped:
                self._count_drop()
                return False
            self._ensure_started()
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            self._count_drop()
            log_limited("analytics.queue_full",
                        "Analitika navbati to'la (%d) - yozuvlar tashlanmoqda", self.max_queue)
            return False
        except Exception:                                   # noqa: BLE001
            self._count_drop()
            log_limited("analytics.submit", "Analitika yozuvi navbatga qo'yilmadi", exc_info=True)
            return False

    def _count_drop(self) -> None:
        with self._count_lock:
            self._dropped += 1

    # --- boshqaruv ---

    def start(self) -> None:
        """Ipni ishga tushiradi (allaqachon ishlayotgan bo'lsa - hech narsa)."""
        if not self._start_lock.acquire(blocking=False):
            return
        try:
            if self._stopped:
                return
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="analytics-writer",
                                            daemon=True)
            self._thread.start()
        finally:
            self._start_lock.release()

    def _ensure_started(self) -> None:
        # Arzon tekshiruv birinchi: har yozuvda qulf olinmasin.
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        if self.autostart:
            # O'lgan ip ham QAYTA ishga tushadi - kutilmagan xato analitikani
            # jimgina butunlay o'chirib qo'ymasligi uchun.
            self.start()

    def flush(self, timeout: float = 5.0) -> bool:
        """Shu paytgacha navbatga qo'yilgan HAMMA yozuv diskka tushguncha
        kutadi. `False` - `timeout` ichida ulgurmadi (yoki ip ishlamayapti).

        Testlar, to'xtash, va "hozirgina yozilgan narsani o'qish" kerak
        bo'lgan joylar uchun (masalan shikoyat oxirgi savolni o'qiydi).
        """
        try:
            if threading.current_thread() is self._thread:
                # Yozuvchi ipning o'zidan chaqirilsa o'zini kutib qolardi.
                return True
            thread = self._thread
            if thread is None or not thread.is_alive():
                if self._queue.empty():
                    return True
                if self._stopped:
                    return False
                self.start()
            done = threading.Event()
            self._queue.put((_FLUSH, done, None), timeout=timeout)
            return done.wait(timeout)
        except Exception:                                   # noqa: BLE001
            log_limited("analytics.flush", "Analitika flush bajarilmadi", exc_info=True)
            return False

    def stop(self, timeout: float = 5.0) -> bool:
        """Navbatdagini yozib, ipni to'xtatadi. Shundan keyingi yozuvlar
        tashlanadi. Takroriy chaqiruv zararsiz."""
        try:
            with self._start_lock:
                if self._stopped:
                    return True
                self._stopped = True
                thread = self._thread
            if thread is None or not thread.is_alive():
                if not self._queue.empty():
                    # Ip hech ishga tushmagan - navbatdagini shu yerning o'zida
                    # yozamiz, yo'qolmasin.
                    self._drain_inline()
                return True
            done = threading.Event()
            self._queue.put((_STOP, done, None), timeout=timeout)
            ok = done.wait(timeout)
            thread.join(timeout)
            return ok
        except Exception:                                   # noqa: BLE001
            log_limited("analytics.stop", "Analitika yozuvchisi to'xtatilmadi", exc_info=True)
            return False

    def _drain_inline(self) -> None:
        """Navbatda qolganini SHU ipda yozadi (to'xtash paytida)."""
        ops: list[tuple] = []
        waiters: list[threading.Event] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item[0] in (_SQL, _MANY, _CALL):
                ops.append(item)
            else:
                waiters.append(item[1])
        for start in range(0, len(ops), self.batch_max):
            self._commit(ops[start:start + self.batch_max])
        # Kutayotganlar yozuvdan KEYIN qo'yib yuboriladi.
        for event in waiters:
            event.set()
        with contextlib.suppress(Exception):
            self.db.close()

    def stats(self) -> dict[str, Any]:
        """Holat: navbatda, tashlangan, yozilgan, xatolar, to'plamlar."""
        with self._count_lock:
            dropped = self._dropped
        thread = self._thread
        return {
            "queued": self._queue.qsize(),
            "dropped": dropped,
            "written": self._written,
            "errors": self._errors,
            "batches": self._batches,
            "maxBatch": self._max_batch,
            "running": bool(thread is not None and thread.is_alive()),
            "lastPurgeAt": self._last_purge_at,
            "purged": dict(self._purged),
        }

    @property
    def dropped(self) -> int:
        with self._count_lock:
            return self._dropped

    # --- yozuvchi ip ---

    def _run(self) -> None:
        next_purge = time.monotonic() + self.purge_first
        while True:
            try:
                if self.purge_every > 0:
                    wait = max(0.05, min(60.0, next_purge - time.monotonic()))
                else:
                    wait = 60.0
                try:
                    first = self._queue.get(timeout=wait)
                except queue.Empty:
                    first = None
                if first is not None:
                    if self._batch(first):
                        return
                if self.purge_every > 0 and time.monotonic() >= next_purge:
                    next_purge = time.monotonic() + self.purge_every
                    self._purge()
            except Exception:                               # noqa: BLE001
                # Ip O'LMASLIGI kerak - aks holda keyingi yozuvlar navbatda
                # to'planib, oxiri hammasi tashlanardi.
                log_limited("analytics.loop", "Analitika yozuvchisida kutilmagan xato",
                            exc_info=True)
                time.sleep(0.5)

    def _batch(self, item: tuple) -> bool:
        """Bitta to'plamni yig'ib yozadi. `True` - to'xtash buyrug'i keldi."""
        ops: list[tuple] = []
        waiters: list[threading.Event] = []
        stop: threading.Event | None = None
        deadline = time.monotonic() + self.batch_wait
        while True:
            kind = item[0]
            if kind == _FLUSH:
                # Flush'dan OLDINGI hamma narsa `ops` da - darhol yozamiz.
                waiters.append(item[1])
                break
            if kind == _STOP:
                stop = item[1]
                break
            ops.append(item)
            if len(ops) >= self.batch_max:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                break
        self._commit(ops)
        for event in waiters:
            event.set()
        if stop is not None:
            # To'xtashdan oldin navbatda qolganini ham yozamiz.
            self._drain_inline()
            stop.set()
            return True
        return False

    def _commit(self, ops: list[tuple]) -> None:
        if not ops:
            return
        try:
            conn = self.db.connect()
        except Exception:                                   # noqa: BLE001
            self._errors += len(ops)
            log_limited("analytics.connect", "Analitika ombori ochilmadi (%s)", self.db.path,
                        exc_info=True)
            return
        groups = _group(ops)
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            # `busy_timeout` (5 s) ichida qulf olinmadi - to'plam tashlanadi,
            # navbat esa to'xtamaydi.
            self._errors += len(ops)
            log_limited("analytics.begin", "Analitika ombori band - to'plam tashlandi",
                        exc_info=True)
            return
        written = 0
        try:
            for group in groups:
                written += self._apply(conn, group)
            conn.execute("COMMIT")
        except Exception:                                   # noqa: BLE001
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            self._errors += len(ops)
            log_limited("analytics.commit", "Analitika to'plami yozilmadi", exc_info=True)
            return
        self._written += written
        self._batches += 1
        self._max_batch = max(self._max_batch, len(ops))

    def _apply(self, conn: sqlite3.Connection, group: tuple[str, Any, list]) -> int:
        """Bitta guruh o'z SAVEPOINT'ida. Xato bo'lsa guruh bittalab qayta
        yoziladi va faqat buzuq yozuv tashlanadi."""
        kind, target, rows = group
        if kind == _CALL:
            written = 0
            for fn in rows:
                if self._savepoint(conn, lambda: fn(conn)):
                    written += 1
            return written
        if self._savepoint(conn, lambda: conn.executemany(target, rows), quiet=True):
            return len(rows)
        written = 0
        for params in rows:
            if self._savepoint(conn, lambda: conn.execute(target, params)):
                written += 1
        return written

    def _savepoint(self, conn: sqlite3.Connection, action: Callable[[], Any], *,
                   quiet: bool = False) -> bool:
        conn.execute("SAVEPOINT w")
        try:
            action()
        except Exception:                                   # noqa: BLE001
            conn.execute("ROLLBACK TO w")
            conn.execute("RELEASE w")
            if not quiet:
                self._errors += 1
                log_limited("analytics.row", "Analitika yozuvi rad etildi", exc_info=True)
            return False
        conn.execute("RELEASE w")
        return True

    def _purge(self) -> None:
        # Shadow qatorlari O'Z muddati bilan (30 kun) - umumiy muddat (180 kun yoki
        # o'chiq) ularga taalluqli emas: ular faqat ko'chish davri uchun kerak.
        self._purge_shadow()
        days = self._retention if self._retention is not None else _db.retention_days()
        if days <= 0:
            return
        try:
            counts = purge(self.db, days)
        except Exception:                                   # noqa: BLE001
            log_limited("analytics.purge", "Analitika tozalashi bajarilmadi", exc_info=True)
            return
        self._last_purge_at = time.time()
        for name, value in counts.items():
            self._purged[name] = self._purged.get(name, 0) + value
        if any(counts.values()):
            log.info("Analitika tozalandi (%d kundan eski): %s", days, counts)

    def _purge_shadow(self) -> None:
        try:
            days = int(_db.setting("shadow_results_days", 30))
        except (TypeError, ValueError):
            days = 30
        if days <= 0:
            return
        try:
            removed = purge_shadow(self.db, days)
        except Exception:                                   # noqa: BLE001
            log_limited("analytics.purge_shadow", "Shadow qatorlari tozalanmadi", exc_info=True)
            return
        if removed:
            self._purged["shadowResults"] = self._purged.get("shadowResults", 0) + removed
            log.info("Shadow qatorlari tozalandi (%d kundan eski): %d", days, removed)


def purge_shadow(db: Database, days: int, *, now: float | None = None,
                 chunk: int = _PURGE_CHUNK) -> int:
    """`shadow_results` dan `days` kundan eskilarini o'chiradi (bo'laklab). Jadval
    hali yo'q bo'lsa (eski sxema) - 0: tozalash umumiy tozalashni to'xtatmasin."""
    if days <= 0:
        return 0
    cutoff = (now if now is not None else time.time()) - days * 86400.0
    conn = db.connect()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_results'"
                    ).fetchone() is None:
        return 0
    total = 0
    while True:
        with db.transaction():
            removed = conn.execute(
                "DELETE FROM shadow_results WHERE id IN "
                "(SELECT id FROM shadow_results WHERE ts < ? LIMIT ?)", (cutoff, chunk)).rowcount
        total += removed
        if removed < chunk:
            return total


def _group(ops: list[tuple]) -> list[tuple[str, Any, list]]:
    """KETMA-KET kelgan bir xil SQL'larni bitta `executemany` ga birlashtiradi.

    Faqat ketma-ketlari - butun to'plam bo'yicha emas: `INSERT turn` dan
    keyin kelgan `UPDATE turn` tartibi saqlanishi shart.
    """
    groups: list[tuple[str, Any, list]] = []
    for kind, target, payload in ops:
        if kind == _CALL:
            if groups and groups[-1][0] == _CALL:
                groups[-1][2].append(target)
            else:
                groups.append((_CALL, None, [target]))
            continue
        rows = payload if kind == _MANY else [payload]
        if groups and groups[-1][0] == _SQL and groups[-1][1] == target:
            groups[-1][2].extend(rows)
        else:
            groups.append((_SQL, target, list(rows)))
    return groups


# --- tozalash ---------------------------------------------------------------------


def purge(db: Database, days: int, *, now: float | None = None,
          chunk: int = _PURGE_CHUNK) -> dict[str, int]:
    """`days` kundan eski yozuvlarni o'chiradi; nechtasi o'chgani qaytadi.

    To'g'ridan-to'g'ri ham chaqirish mumkin (testlar, `tools/`). Bo'laklab
    ishlaydi: har bo'lak - alohida qisqa tranzaksiya, ya'ni oradagi chat
    yozuvlari uzoq kutmaydi.

    `reports` va `audit_log` TEGILMAYDI: shikoyat unga bog'langan savol
    o'chgandan keyin ham o'z nusxasini (`snapshot`) saqlaydi.
    """
    counts = {"turns": 0, "events": 0, "sources": 0, "apiCalls": 0, "authEvents": 0}
    if days <= 0:
        return counts
    cutoff = (now if now is not None else time.time()) - days * 86400.0
    conn = db.connect()
    while True:
        with db.transaction():
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM turns WHERE started_at < ? LIMIT ?", (cutoff, chunk))]
            if not ids:
                break
            for part in iter_chunks(ids, 400):
                marks = ",".join("?" * len(part))
                counts["events"] += conn.execute(
                    f"DELETE FROM turn_events WHERE turn_id IN ({marks})", part).rowcount
                counts["sources"] += conn.execute(
                    f"DELETE FROM turn_sources WHERE turn_id IN ({marks})", part).rowcount
                counts["turns"] += conn.execute(
                    f"DELETE FROM turns WHERE id IN ({marks})", part).rowcount
    for table, key in (("api_calls", "apiCalls"), ("auth_events", "authEvents")):
        while True:
            with db.transaction():
                removed = conn.execute(
                    f"DELETE FROM {table} WHERE id IN "
                    f"(SELECT id FROM {table} WHERE ts < ? LIMIT ?)", (cutoff, chunk)).rowcount
            counts[key] += removed
            if removed < chunk:
                break
    return counts


# --- umumiy nusxa ---------------------------------------------------------------

_writer: Writer | None = None
_writer_lock = threading.Lock()


def get_writer() -> Writer:
    """Ilova bo'yicha BITTA yozuvchi (ip birinchi yozuvda ishga tushadi)."""
    global _writer
    found = _writer
    if found is not None:
        return found
    with _writer_lock:
        if _writer is None:
            _writer = Writer()
        return _writer


def shutdown(timeout: float = 5.0) -> None:
    """Navbatni yozib, yozuvchini to'xtatadi - ilova to'xtaganda (lifespan
    `shutdown` yoki `atexit`). Takroriy chaqiruv zararsiz."""
    global _writer
    with _writer_lock:
        found, _writer = _writer, None
    if found is not None:
        found.stop(timeout)


def reset_for_tests(db: Database | None = None, **kwargs: Any) -> Writer:
    """Eski yozuvchini to'xtatib, `db` ga yozadigan yangisini o'rnatadi."""
    global _writer
    with _writer_lock:
        old, _writer = _writer, Writer(db, **kwargs)
        new = _writer
    if old is not None:
        old.stop(2.0)
    return new


# Jarayon tugaganda navbatda qolgan yozuvlar yo'qolmasin. `atexit` fon
# iplari o'ldirilishidan OLDIN ishlaydi.
atexit.register(shutdown)

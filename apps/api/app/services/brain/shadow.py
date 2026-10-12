"""Shadow: foydalanuvchi LOKAL natijani oladi, agent esa fonda xuddi shu ishni qiladi.

NIMA UCHUN. Agentga ko'chirishdan oldin sifat, tezlik va xatolarni haqiqiy yukda
o'lchash kerak (`migration-plan.md` 8-bo'lim) - lekin foydalanuvchini xavf ostiga
qo'ymasdan. Natijalar `shadow_results` jadvaliga yoziladi.

QOIDALAR (har biri sabab bilan):

  * FOYDALANUVCHI HECH QACHON KUTMAYDI. Vazifa navbatga `put_nowait` bilan
    qo'yiladi; navbat to'la bo'lsa vazifa TASHLANADI va hisoblanadi (`dropped`).
  * O'Z NAVBATI. Ishchi iplar soni `AGENT_SHADOW_MAX_CONCURRENT` (1), agent mijozi
    ham alohida (`routing.client("shadow")`): chatning 4 ta o'rni
    (`hrm_assistant_max_concurrent`) ishlatilmaydi - aks holda jonli odamlar
    `queue_full` olardi.
  * NAMUNA. Har chaqiruv `sample_rate` ehtimoli bilan (`AGENT_SHADOW_SAMPLE_RATE`,
    yoki admin flag qatoridagi qiymat) - sig'imni agent jamoasi tasdiqlaydi.
  * XOM MATN SAQLANMAYDI. Jadvalda faqat vaqt, belgi soni, arzon o'xshashlik
    (so'zlar to'plamining Jaccard'i) va sonli ko'rsatkichlar. Prompt va javoblar
    faqat xotirada, vazifa tugaguncha turadi.
"""

from __future__ import annotations

import json
import math
import logging
import queue
import random
import re
import threading
import time

from collections.abc import Callable, Mapping
from typing import Any

from ...core.config import settings
from ..analytics import db as _db
from ..analytics.db import log_limited
from ..analytics.meter import bind, carry, current, redact
from ..analytics.writer import get_writer

log = logging.getLogger(__name__)

_INSERT = (
    "INSERT INTO shadow_results (ts, feature, op, status, trace_id, request_id, local_ms, agent_ms, "
    "input_chars, local_chars, agent_chars, similarity, metrics, error, actor_id, channel) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)

_WORD = re.compile(r"[^\W_]+(?:['ʻ’][^\W_]+)*", re.UNICODE)
_FENCE = re.compile(r"^```(?:json|JSON)?\s*|\s*```$")


# --- taqqoslash (arzon, deterministik) ----------------------------------------------------------


def words(text: Any) -> set[str]:
    """Kichik harfli so'zlar to'plami (1 harflilar tashlanadi: "a", "i" shovqin)."""
    return {w.lower() for w in _WORD.findall(str(text or "")) if len(w) > 1}


def similarity(a: Any, b: Any) -> float:
    """So'zlar to'plamining Jaccard'i, 0..1. Ikkalasi bo'sh - 1.0 (bir xil)."""
    left, right = words(a), words(b)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(len(left & right) / len(left | right), 4)


def overlap(a: Any, b: Any) -> float | None:
    """Ikki id to'plamining Jaccard'i (iqtiboslar, topilgan vazifalar). Ikkalasi bo'sh - `None`."""
    left = {str(x) for x in (a or [])}
    right = {str(x) for x in (b or [])}
    if not left and not right:
        return None
    return round(len(left & right) / len(left | right), 4)


def parse_json(text: Any) -> Any:
    """Model matnidan JSON (```json ... ``` o'ramini olib). Bo'lmasa `None`."""
    raw = _FENCE.sub("", str(text or "").strip())
    if not raw or raw[0] not in "[{":
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def items_count(value: Any) -> int | None:
    """JSON dagi bandlar soni: ro'yxat - uzunligi; lug'at - ichidagi ro'yxatlar yig'indisi."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(len(v) for v in value.values() if isinstance(v, list))
    return None


def text_metrics(local: Any, agent: Any) -> dict[str, Any]:
    """Matnli natija uchun sonlar: qatorlar, JSON bo'ldimi, bandlar soni."""
    out: dict[str, Any] = {}
    for side, text in (("local", local), ("agent", agent)):
        value = str(text or "")
        out[f"{side}_lines"] = len([line for line in value.splitlines() if line.strip()])
        parsed = parse_json(value)
        out[f"{side}_json"] = 1 if parsed is not None else 0
        count = items_count(parsed)
        if count is not None:
            out[f"{side}_items"] = count
    return out


def _numbers(metrics: Mapping[str, Any] | None) -> str | None:
    """Faqat sonlar (bool -> 0/1) - jadvalga matn tushmasin."""
    if not metrics:
        return None
    clean: dict[str, float | int] = {}
    for key, value in metrics.items():
        if isinstance(value, bool):
            clean[str(key)[:40]] = int(value)
        elif isinstance(value, (int, float)):
            clean[str(key)[:40]] = round(value, 4) if isinstance(value, float) else value
    return json.dumps(clean, separators=(",", ":"), sort_keys=True) if clean else None


def _ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(round(value)))


def record(feature: str, op: str, *, status: str = "ok", trace_id: str | None = None,
           request_id: str | None = None, local_ms: float | None = None, agent_ms: float | None = None,
           input_chars: int | None = None, local_chars: int | None = None, agent_chars: int | None = None,
           similarity: float | None = None, metrics: Mapping[str, Any] | None = None,
           error: Any = None) -> bool:
    """Bitta taqqoslash qatori (yozuvchi navbati orqali). HECH QACHON xato bermaydi."""
    try:
        if not _db.analytics_enabled():
            return False
        who = current()
        if isinstance(error, BaseException):
            # Faqat tur, kod va HTTP status - xato MATNI yo'q: agentning 4xx izohi yoki
            # parser xatosi kirishimizni (guruh, yig'ilish matnini) qaytarishi mumkin, jadval
            # esa "faqat sonlar" deb hujjatlangan (sharh, 2026-10-10).
            code, http = getattr(error, "code", None), getattr(error, "status", None)
            error = ":".join(str(x) for x in (type(error).__name__, code, http) if x not in (None, ""))
        elif error is not None:
            # Matnli qiymat - javobdagi xato KODI (`error.code`); kod bo'lmasa tashlanadi.
            text = str(error)[:48]
            error = text if text and all(ch.isalnum() or ch in "_.:-" for ch in text) else "error"
        params = (
            time.time(), str(feature)[:40], str(op)[:64], status if status in ("ok", "error", "timeout")
            else "error", (str(trace_id)[:64] if trace_id else None), (str(request_id)[:64] if request_id else None),
            _ms(local_ms), _ms(agent_ms), _ms(input_chars), _ms(local_chars), _ms(agent_chars),
            (round(float(similarity), 4) if isinstance(similarity, (int, float))
             and not isinstance(similarity, bool) else None),
            _numbers(metrics), (redact(error) or None) if error is not None else None,
            who.actor_id, who.channel,
        )
        return get_writer().submit(_INSERT, params)
    except Exception:                                       # noqa: BLE001
        log_limited("brain.shadow.record", "Shadow qatori yozilmadi", exc_info=True)
        return False


# --- navbat -------------------------------------------------------------------------------------


class ShadowQueue:
    """Chegaralangan navbat + `workers` ta fon ipi. `submit` hech qachon bloklamaydi."""

    def __init__(self, *, workers: int = 1, maxsize: int = 8,
                 rand: Callable[[], float] = random.random) -> None:
        self.workers = max(1, int(workers))
        self.maxsize = max(1, int(maxsize))
        self._rand = rand
        self._queue: queue.Queue = queue.Queue(maxsize=self.maxsize)
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._stopped = False
        self._counts = {"submitted": 0, "sampledOut": 0, "dropped": 0, "done": 0, "failed": 0}

    def _count(self, key: str) -> None:
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1

    def _start(self) -> None:
        with self._lock:
            if self._stopped or len(self._threads) >= self.workers:
                return
            while len(self._threads) < self.workers:
                thread = threading.Thread(target=self._run, name=f"brain-shadow-{len(self._threads)}",
                                          daemon=True)
                self._threads.append(thread)
                thread.start()

    def submit(self, feature: str, job: Callable[[], None], *, sample_rate: float) -> bool:
        """Namunaga tushsa va navbatda joy bo'lsa - `True`. Vazifa joriy hisob
        kontekstini (kim, kanal) oladi; savol kaliti (`turn`) olinmaydi - shadow
        chaqiruvi odamning savol iziga aralashmasin."""
        try:
            rate = float(sample_rate)
        except (TypeError, ValueError):
            rate = 0.0
        if rate <= 0.0 or (rate < 1.0 and self._rand() >= rate):
            self._count("sampledOut")
            return False
        if self._stopped:
            self._count("dropped")
            return False

        def run() -> None:
            with bind(turn_id=None):
                job()

        try:
            self._queue.put_nowait((feature, carry(run)))
        except queue.Full:
            self._count("dropped")
            log_limited(f"brain.shadow.full.{feature}", "Shadow navbati to'la - %s tashlandi", feature)
            return False
        self._count("submitted")
        self._start()
        return True

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                feature, job = item
                try:
                    job()
                    self._count("done")
                except Exception:                           # noqa: BLE001
                    self._count("failed")
                    log_limited(f"brain.shadow.job.{feature}", "Shadow vazifasi yiqildi (%s)", feature,
                                exc_info=True)
            finally:
                self._queue.task_done()

    def drain(self, timeout: float = 5.0) -> bool:
        """Navbat bo'shaguncha kutadi (testlar). `True` - bo'shadi."""
        ends = time.monotonic() + timeout
        while time.monotonic() < ends:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            threads = list(self._threads)
        for _ in threads:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def stats(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = dict(self._counts)
        out.update(queued=self._queue.qsize(), maxsize=self.maxsize, workers=self.workers)
        return out


_queue_lock = threading.Lock()
_shared: ShadowQueue | None = None


def get_queue() -> ShadowQueue:
    global _shared
    found = _shared
    if found is not None:
        return found
    with _queue_lock:
        if _shared is None:
            _shared = ShadowQueue(workers=settings.agent_shadow_max_concurrent,
                                  maxsize=settings.agent_shadow_queue)
        return _shared


def reset_for_tests(**kwargs: Any) -> ShadowQueue:
    global _shared
    with _queue_lock:
        old, _shared = _shared, ShadowQueue(**kwargs)
    if old is not None:
        old.stop()
    return _shared


def submit(feature: str, job: Callable[[], None], *, sample_rate: float) -> bool:
    return get_queue().submit(feature, job, sample_rate=sample_rate)


# --- admin uchun jamlanma ------------------------------------------------------------------------


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def summary(days: int = 7, *, db: Any = None, now: float | None = None) -> dict[str, Any]:
    """`GET /api/v1/admin/engines/brain/shadow` - har funksiya bo'yicha taqqoslash natijasi:
    nechta, xato/timeout ulushi, bizning va agentning kechikishi (p50/p95), o'rtacha o'xshashlik.
    Egasi "agentga o'tkazamizmi" qarorini SHU raqamlarga qarab beradi (reja 7.2). Faqat sonlar."""
    days = max(1, min(int(days), 90))
    since = (time.time() if now is None else now) - days * 86400
    database = db or _db.get_db()
    rows = database.rows(
        "SELECT feature, status, local_ms, agent_ms, similarity, ts FROM shadow_results WHERE ts >= ? "
        "ORDER BY ts", (since,))
    out: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["feature"]), []).append(row)
    for feature, items in grouped.items():
        ok = [r for r in items if r["status"] == "ok"]
        sims = [float(r["similarity"]) for r in ok if r["similarity"] is not None]
        local = [int(r["local_ms"]) for r in items if r["local_ms"] is not None]
        agent = [int(r["agent_ms"]) for r in ok if r["agent_ms"] is not None]
        out[feature] = {
            "count": len(items),
            "ok": len(ok),
            "errors": sum(1 for r in items if r["status"] == "error"),
            "timeouts": sum(1 for r in items if r["status"] == "timeout"),
            "similarityAvg": round(sum(sims) / len(sims), 3) if sims else None,
            "localP50": _pct(local, 0.5), "localP95": _pct(local, 0.95),
            "agentP50": _pct(agent, 0.5), "agentP95": _pct(agent, 0.95),
            "lastAt": int(items[-1]["ts"]),
        }
    return {"days": days, "features": out}

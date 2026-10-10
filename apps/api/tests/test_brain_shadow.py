"""Shadow: arzon taqqoslash, chegaralangan navbat (foydalanuvchi kutmaydi), namuna,
`shadow_results` (xom matnsiz) va uning tozalanishi."""

from __future__ import annotations

import json
import threading
import time

from app.services import analytics
from app.services.analytics.meter import bind
from app.services.analytics.writer import Writer, purge_shadow
from app.services.brain import shadow
from app.services.brain.shadow import ShadowQueue


def test_oxshashlik_va_korsatkichlar():
    assert shadow.similarity("Login xatosi tuzatildi", "login XATOSI tuzatildi!") == 1.0
    assert shadow.similarity("", "") == 1.0 and shadow.similarity("bor", "") == 0.0
    assert 0.0 < shadow.similarity("Aziz hisobotni yuboradi", "Aziz hisobotni ertaga yuboradi") < 1.0
    assert shadow.similarity("o'zbek tili", "o'zbek tili") == 1.0       # apostrof so'z ichida
    assert shadow.overlap(["1", "2"], [2, 3]) == round(1 / 3, 4) and shadow.overlap([], []) is None
    metrics = shadow.text_metrics('```json\n{"events": [{"a": 1}, {"a": 2}], "x": []}\n```', "- bir\n- ikki\n")
    assert metrics == {"local_lines": 3, "local_json": 1, "local_items": 2, "agent_lines": 2, "agent_json": 0}


def test_namuna_va_navbat_toliqligi_bloklamaydi():
    release = threading.Event()
    queue = ShadowQueue(workers=1, maxsize=2, rand=lambda: 0.5)
    assert queue.submit("group_ask", lambda: None, sample_rate=0.4) is False    # namunaga tushmadi
    assert queue.submit("group_ask", lambda: None, sample_rate=0.0) is False
    started = threading.Event()

    def slow():
        started.set()
        release.wait(5)

    assert queue.submit("group_ask", slow, sample_rate=1.0)
    assert started.wait(5)                                          # ishchi band
    assert queue.submit("group_ask", lambda: None, sample_rate=0.6)  # 0.5 < 0.6 - namunada
    assert queue.submit("group_ask", lambda: None, sample_rate=1.0)
    began = time.monotonic()
    assert queue.submit("group_ask", lambda: None, sample_rate=1.0) is False   # to'la - tashlanadi
    assert time.monotonic() - began < 0.1                           # kutmadi
    stats = queue.stats()
    assert (stats["dropped"], stats["sampledOut"], stats["submitted"], stats["workers"]) == (1, 2, 3, 1)
    release.set()
    assert queue.drain(5)
    assert queue.stats()["done"] == 3
    queue.stop()


def test_ishchi_bittadan_kop_parallel_ishlamaydi():
    queue = ShadowQueue(workers=1, maxsize=8)
    active, peak, lock = [0], [0], threading.Lock()

    def job():
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.01)
        with lock:
            active[0] -= 1

    for _ in range(5):
        assert queue.submit("meeting_summary", job, sample_rate=1.0)
    assert queue.drain(5)
    assert peak[0] == 1
    queue.stop()


def test_yiqilgan_vazifa_ishchini_toxtatmaydi():
    queue = ShadowQueue(workers=1, maxsize=4)

    def boom():
        raise RuntimeError("agent yiqildi")

    queue.submit("x", boom, sample_rate=1.0)
    queue.submit("x", lambda: None, sample_rate=1.0)
    assert queue.drain(5)
    assert (queue.stats()["failed"], queue.stats()["done"]) == (1, 1)
    queue.stop()


def test_qator_xom_matnsiz_va_atributsiya(_isolated_analytics):
    with bind(42, "bot", "turn-1"):
        captured: list[tuple] = []

        def job():
            from app.services.analytics.meter import current

            captured.append(tuple(current()))
            shadow.record("group_ask", "group_ask", trace_id="trace-9", request_id="req-1", local_ms=1200.4,
                          agent_ms=3400, input_chars=5000, local_chars=300, agent_chars=280, similarity=0.61234,
                          metrics={"local_items": 3, "truncated": True, "matn": "MAXFIY"},
                          error=RuntimeError("token=eyJhbGciOiJIUzI1NiJ9.abcdefgh"))

        assert shadow.submit("group_ask", job, sample_rate=1.0)
    assert shadow.get_queue().drain(5)
    # Shadow chaqiruvi odamning savol iziga aralashmaydi (`turn` yo'q), kim/kanal saqlanadi.
    assert captured == [(42, "bot", None)]
    assert analytics.flush()
    [row] = _isolated_analytics.rows("SELECT * FROM shadow_results")
    assert (row["feature"], row["op"], row["status"], row["trace_id"]) == ("group_ask", "group_ask", "ok",
                                                                          "trace-9")
    assert (row["local_ms"], row["agent_ms"], row["input_chars"], row["similarity"]) == (1200, 3400, 5000, 0.6123)
    assert json.loads(row["metrics"]) == {"local_items": 3, "truncated": 1}      # matn tashlandi
    assert "eyJ" not in row["error"] and (row["actor_id"], row["channel"]) == (42, "bot")


def test_shadow_qatorlari_30_kundan_keyin_tozalanadi(_isolated_analytics):
    db = _isolated_analytics
    now = time.time()
    for ts in (now - 40 * 86400, now - 31 * 86400, now - 1 * 86400):
        db.execute("INSERT INTO shadow_results (ts, feature, op, status) VALUES (?, 'group_ask', 'group_ask', 'ok')",
                   (ts,))
    assert purge_shadow(db, 30, now=now, chunk=1) == 2
    assert db.scalar("SELECT COUNT(*) FROM shadow_results") == 1
    assert purge_shadow(db, 0) == 0


def test_yozuvchi_tozalashi_shadowni_ham_tozalaydi(_isolated_analytics, monkeypatch):
    from app.core.config import settings

    db = _isolated_analytics
    db.execute("INSERT INTO shadow_results (ts, feature, op, status) VALUES (?, 'x', 'x', 'ok')",
               (time.time() - 60 * 86400,))
    monkeypatch.setattr(settings, "shadow_results_days", 30, raising=False)
    writer = Writer(db, autostart=False, retention_days=0)          # umumiy tozalash o'chiq
    writer._purge()
    assert db.scalar("SELECT COUNT(*) FROM shadow_results") == 0
    assert writer.stats()["purged"]["shadowResults"] == 1

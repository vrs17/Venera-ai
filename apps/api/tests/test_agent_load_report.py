"""`scripts/agent_load_report.py`: ombor FAQAT o'qiladi, op va kun bo'yicha sonlar to'g'ri."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3

from datetime import datetime
from pathlib import Path

import pytest

from app.services.analytics.db import Database

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "agent_load_report.py"
NOW = datetime.fromisoformat("2026-10-10T12:00:00+05:00").timestamp()


def _module():
    spec = importlib.util.spec_from_file_location("agent_load_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def report_db(tmp_path):
    path = tmp_path / "venera.db"
    db = Database(path)
    rows = []
    for i, ms in enumerate((100, 200, 300, 400, 1000)):              # bugun, group_summary
        rows.append((NOW - 3600 - i, "ollama", "group_summary", "ok" if i < 4 else "error", ms,
                     json.dumps({"chars": 1000 * (i + 1)})))
    rows.append((NOW - 86400 - 60, "ollama", "group_summary", "ok", 50, json.dumps({"chars": 10})))   # kecha
    rows.append((NOW - 3600, "assistant", "stream", "ok", 7000, json.dumps({"bytes": 2048})))
    rows.append((NOW - 3600, "tts", "speak", "ok", 900, None))                                     # xizmat emas
    rows.append((NOW - 40 * 86400, "ollama", "group_summary", "ok", 10, None))                    # oynadan tashqari
    with db.transaction() as conn:
        conn.executemany("INSERT INTO api_calls (ts, service, op, status, duration_ms, units) VALUES (?,?,?,?,?,?)",
                         rows)
        conn.execute("INSERT INTO turns (id, started_at, channel, question) VALUES ('t', ?, 'web', 'MAXFIY SAVOL')",
                     (NOW - 10,))
        for sim, ms in ((0.5, 3000), (0.7, 5000)):
            conn.execute("INSERT INTO shadow_results (ts, feature, op, status, local_ms, agent_ms, similarity) "
                         "VALUES (?, 'group_ask', 'group_ask', 'ok', 1000, ?, ?)", (NOW - 100, ms, sim))
    db.close_all()
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_hisobot_op_va_kun_boyicha(report_db):
    module = _module()
    report = module.build(report_db, days=14, now=NOW)
    totals = {(t["service"], t["op"]): t for t in report["totals"]}
    assert set(totals) == {("ollama", "group_summary"), ("assistant", "stream")}
    gs = totals[("ollama", "group_summary")]
    assert (gs["calls"], gs["peak_day_calls"], gs["error_rate"]) == (6, 5, round(1 / 6, 4))
    assert gs["calls_per_day"] == round(6 / 14, 2)
    daily = [d for d in report["daily"] if d["op"] == "group_summary"]
    assert [d["day"] for d in daily] == ["2026-10-09", "2026-10-10"]
    today = daily[1]
    assert (today["calls"], today["errors"], today["input_chars_total"], today["input_chars_max"]) == (
        5, 1, 15000, 5000)
    assert (today["p50_ms"], today["p95_ms"]) == (300.0, 1000.0)
    assert totals[("assistant", "stream")]["input_chars_avg"] == 2048       # `bytes` zahira
    [shadow] = report["shadow"]
    assert (shadow["runs"], shadow["similarity_avg"], shadow["agent_p95_ms"]) == (2, 0.6, 5000.0)


def test_ombor_faqat_oqiladi_va_matn_chiqmaydi(report_db, capsys):
    module = _module()
    before = _digest(report_db)
    assert module.main([str(report_db), "--days", "14", "--json"]) == 0
    out = capsys.readouterr().out
    assert "MAXFIY" not in out and json.loads(out)["days"] == 14
    assert module.main([str(report_db)]) == 0
    text = capsys.readouterr().out
    assert "group_summary" in text and "SHADOW" in text
    assert _digest(report_db) == before                                      # fayl o'zgarmadi
    conn = module.connect_ro(report_db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM api_calls")
    conn.close()


def test_fayl_yoq_yoki_eski_ombor(tmp_path, capsys):
    module = _module()
    assert module.main([str(tmp_path / "yoq.db")]) == 1
    assert not (tmp_path / "yoq.db").exists()                                # yangisi yaratilmadi
    old = tmp_path / "old.db"
    sqlite3.connect(str(old)).close()
    report = module.build(old, days=7, now=NOW)
    assert report["totals"] == [] and report["shadow"] == []


def test_percentile():
    module = _module()
    assert module.percentile([], 95) is None
    assert module.percentile([5.0], 50) == 5.0
    assert module.percentile([float(x) for x in range(1, 101)], 95) == 95.0

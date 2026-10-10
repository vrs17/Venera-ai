#!/usr/bin/env python3
"""Agent jamoasi uchun yuk hisoboti: har op bo'yicha kunlik chaqiruvlar, kirish hajmi, kechikish.

NEGA KERAK. Agentga ko'chirishdan oldin agent jamoasi sig'imni (navbat, kvota, SLA)
bizning HAQIQIY yukimizga qarab tasdiqlashi kerak (`migration-plan.md` W0.10,
`agent-contract.md` 14.5). Raqamlar analytics omborining `api_calls` jadvalida bor:
har tashqi chaqiruv - xizmat, op, vaqt, natija va hajm (`units.chars`). Bu skript
ularni op va kun bo'yicha yig'adi.

FAQAT O'QIYDI. Ombor `mode=ro` URI bilan ochiladi va `PRAGMA query_only` yoqiladi:
jonli faylga hech narsa yozilmaydi (migratsiya ham, WAL nazorat nuqtasi ham).
Ichida savol matnlari bor (SHAXSIY MA'LUMOT) - skript ularni O'QIMAYDI: faqat
`api_calls` va `shadow_results` dagi sonlar. Chiqishda matn yo'q.

Ishlatish (apps/api ichidan; venv shart emas - faqat standart kutubxona):

    python3 scripts/agent_load_report.py data/analytics/venera.db             # oxirgi 14 kun
    python3 scripts/agent_load_report.py data/analytics/venera.db --days 30
    python3 scripts/agent_load_report.py data/analytics/venera.db --json      # agent jamoasiga
    python3 scripts/agent_load_report.py data/analytics/venera.db --services ollama

Kun - Toshkent vaqti bo'yicha (UTC+5). `input_chars` - so'rovdagi belgi soni
(`units.chars`; yo'q bo'lsa - `units.bytes`). `p50/p95_ms` - butun chaqiruv vaqti.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

#: Toshkent: yozgi vaqt yo'q, doim UTC+5.
TZ = timezone(timedelta(hours=5))
#: Default: LLM va agent xizmatlari (chat oqimi ham - agentning bugungi yuki).
DEFAULT_SERVICES = ("ollama", "openai", "assistant", "brain")


def connect_ro(path: Path) -> sqlite3.Connection:
    """Ombor FAQAT O'QISH uchun. Fayl yo'q bo'lsa - xato (yangisi yaratilmaydi)."""
    if not path.is_file():
        raise FileNotFoundError(f"ombor topilmadi: {path}")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def percentile(values: list[float], q: float) -> float | None:
    """Eng yaqin daraja usuli (nearest-rank). Bo'sh - `None`."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _chars(units: Any) -> int | None:
    if not units:
        return None
    try:
        data = json.loads(units)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("chars", "bytes"):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d")


def load_calls(conn: sqlite3.Connection, *, days: int, now: float,
               services: Iterable[str] = DEFAULT_SERVICES) -> list[dict[str, Any]]:
    """`api_calls` dan oxirgi `days` kun (faqat kerakli ustunlar - matn yo'q)."""
    wanted = [s for s in services if s]
    if not wanted or not _has_table(conn, "api_calls"):
        return []
    since = now - days * 86400.0
    marks = ",".join("?" * len(wanted))
    cursor = conn.execute(
        f"SELECT ts, service, op, status, duration_ms, units FROM api_calls "
        f"WHERE ts >= ? AND service IN ({marks}) ORDER BY ts", (since, *wanted))
    return [dict(row) for row in cursor]


def summarize_calls(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(xizmat, op, kun) bo'yicha: soni, xatolar, kirish hajmi, p50/p95."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["service"], row["op"], _day(float(row["ts"])))].append(row)
    out: list[dict[str, Any]] = []
    for (service, op, day), items in sorted(groups.items()):
        durations = [float(r["duration_ms"] or 0) for r in items]
        sizes = [c for c in (_chars(r["units"]) for r in items) if c is not None]
        out.append({
            "service": service, "op": op, "day": day,
            "calls": len(items),
            "errors": sum(1 for r in items if r["status"] != "ok"),
            "input_chars_total": sum(sizes),
            "input_chars_avg": round(sum(sizes) / len(sizes)) if sizes else None,
            "input_chars_p95": percentile([float(s) for s in sizes], 95),
            "input_chars_max": max(sizes) if sizes else None,
            "p50_ms": percentile(durations, 50),
            "p95_ms": percentile(durations, 95),
        })
    return out


def totals(daily: list[dict[str, Any]], rows: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """Butun oyna bo'yicha (xizmat, op): jami, kunlik o'rtacha va eng ko'p kun."""
    by_op: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_op[(row["service"], row["op"])].append(row)
    peak: dict[tuple[str, str], int] = defaultdict(int)
    for item in daily:
        key = (item["service"], item["op"])
        peak[key] = max(peak[key], item["calls"])
    out = []
    for (service, op), items in sorted(by_op.items()):
        durations = [float(r["duration_ms"] or 0) for r in items]
        sizes = [c for c in (_chars(r["units"]) for r in items) if c is not None]
        out.append({
            "service": service, "op": op, "calls": len(items),
            "calls_per_day": round(len(items) / max(1, days), 2),
            "peak_day_calls": peak[(service, op)],
            "error_rate": round(sum(1 for r in items if r["status"] != "ok") / len(items), 4),
            "input_chars_avg": round(sum(sizes) / len(sizes)) if sizes else None,
            "input_chars_p95": percentile([float(s) for s in sizes], 95),
            "p50_ms": percentile(durations, 50),
            "p95_ms": percentile(durations, 95),
        })
    return out


def shadow_summary(conn: sqlite3.Connection, *, days: int, now: float) -> list[dict[str, Any]]:
    """`shadow_results` (sxema v4) bo'yicha funksiya va op: soni, xatolar, o'xshashlik,
    agent kechikishi. Jadval yo'q (eski ombor) - bo'sh ro'yxat."""
    if not _has_table(conn, "shadow_results"):
        return []
    since = now - days * 86400.0
    groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in conn.execute("SELECT feature, op, status, local_ms, agent_ms, similarity FROM shadow_results "
                            "WHERE ts >= ?", (since,)):
        groups[(row["feature"], row["op"])].append(row)
    out = []
    for (feature, op), items in sorted(groups.items()):
        sims = [float(r["similarity"]) for r in items if r["similarity"] is not None]
        agent_ms = [float(r["agent_ms"]) for r in items if r["agent_ms"] is not None and r["status"] == "ok"]
        local_ms = [float(r["local_ms"]) for r in items if r["local_ms"] is not None]
        out.append({
            "feature": feature, "op": op, "runs": len(items),
            "errors": sum(1 for r in items if r["status"] != "ok"),
            "similarity_avg": round(sum(sims) / len(sims), 4) if sims else None,
            "local_p50_ms": percentile(local_ms, 50), "local_p95_ms": percentile(local_ms, 95),
            "agent_p50_ms": percentile(agent_ms, 50), "agent_p95_ms": percentile(agent_ms, 95),
        })
    return out


def build(path: Path, *, days: int = 14, now: float | None = None,
          services: Iterable[str] = DEFAULT_SERVICES) -> dict[str, Any]:
    now = time.time() if now is None else now
    conn = connect_ro(path)
    try:
        rows = load_calls(conn, days=days, now=now, services=services)
        daily = summarize_calls(rows)
        return {
            "generated_at": datetime.fromtimestamp(now, TZ).isoformat(timespec="seconds"),
            "days": days,
            "services": list(services),
            "totals": totals(daily, rows, days),
            "daily": daily,
            "shadow": shadow_summary(conn, days=days, now=now),
        }
    finally:
        conn.close()


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.0f}" if value >= 100 or value == int(value) else f"{value:.2f}"
    return str(value)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    cells = [[_fmt(v) for v in row] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(c.ljust(widths[i]) for i, c in enumerate(row)) for row in cells]
    return "\n".join(lines)


def render_text(report: dict[str, Any]) -> str:
    parts = [f"Agent yuk hisoboti - oxirgi {report['days']} kun ({report['generated_at']}), "
             f"xizmatlar: {', '.join(report['services'])}", ""]
    if not report["totals"]:
        parts.append("Bu oynada chaqiruv yo'q.")
    else:
        parts.append("JAMI (op bo'yicha)")
        parts.append(_table(
            ["service", "op", "calls", "per_day", "peak_day", "err_rate", "chars_avg", "chars_p95", "p50_ms",
             "p95_ms"],
            [[t["service"], t["op"], t["calls"], t["calls_per_day"], t["peak_day_calls"], t["error_rate"],
              t["input_chars_avg"], t["input_chars_p95"], t["p50_ms"], t["p95_ms"]] for t in report["totals"]]))
        parts += ["", "KUNLIK"]
        parts.append(_table(
            ["day", "service", "op", "calls", "errors", "chars_total", "chars_avg", "chars_max", "p50_ms",
             "p95_ms"],
            [[d["day"], d["service"], d["op"], d["calls"], d["errors"], d["input_chars_total"],
              d["input_chars_avg"], d["input_chars_max"], d["p50_ms"], d["p95_ms"]] for d in report["daily"]]))
    if report["shadow"]:
        parts += ["", "SHADOW (lokal va agent taqqoslash)"]
        parts.append(_table(
            ["feature", "op", "runs", "errors", "similarity", "local_p50", "local_p95", "agent_p50", "agent_p95"],
            [[s["feature"], s["op"], s["runs"], s["errors"], s["similarity_avg"], s["local_p50_ms"],
              s["local_p95_ms"], s["agent_p50_ms"], s["agent_p95_ms"]] for s in report["shadow"]]))
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("db", type=Path, help="analytics ombori (venera.db) - faqat o'qiladi")
    parser.add_argument("--days", type=int, default=14, help="oxirgi N kun (default 14)")
    parser.add_argument("--services", default=",".join(DEFAULT_SERVICES),
                        help="vergul bilan: ollama,openai,assistant,brain")
    parser.add_argument("--json", action="store_true", help="JSON chiqish (agent jamoasiga)")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days kamida 1")
    services = [s.strip() for s in args.services.split(",") if s.strip()]
    try:
        report = build(args.db, days=args.days, services=services)
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"Xato: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

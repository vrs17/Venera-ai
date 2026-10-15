"""Admin "Agent playground": agentning debug endpointlari va saqlangan regressiya sinovlari.

NEGA (ega, 2026-10-15). "Agent aqlsiz" degan shikoyatda sabab model emas, bosqichlar orasida
bo'lishi mumkin: 24 799 mijoz soni "so'm" deb yorliqlanib yozuvchiga ketgan (kod), yozuvchi
o'zining oldingi javobini ko'rmagan (dizayn). Buni topish uchun serverda jurnal titkilash
kerak edi. Playground shu ishni admin sahifasiga olib chiqadi:

    1. haqiqiy savolni tanlash -> har bosqichning AYNAN modelga ketgan kirishi va chiqishi;
    2. bitta bosqichni tahrirlab qayta ishga tushirish, modelni almashtirish, ikki modelni
       yonma-yon solishtirish;
    3. holatni regressiya sinoviga saqlash (keyingi tuzatishdan keyin qayta tekshiriladi).

BOSQICH ICHI AGENTNIKI. Prompt, xabarlar, vositalar - agent jamoasining kodi; ularni
yig'ish va ishga tushirish `/api/v4/debug/*` da (agent tomoni, faqat bizning mijozimiz,
debug ruxsati bilan). Bu yerda - ularni chaqirish, xatoni odam tiliga o'girish, audit.

XAVFSIZLIK. Bosqich vosita chaqiruvlarini QAYTARADI, bajarmaydi - playground CRM/HRM ga
hech narsa yozmaydi. Agent mijozi `probe_client` (o'z uzgichi): sinov xatolari ishlab
turgan chat, guruh va yig'ilishni lokal yo'lga o'tkazib yubormaydi. Bosqich kirishi
(xodim va bank ma'lumoti) BIZDA saqlanmaydi - faqat sinov savollari va kutilgan xulq.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ..schemas.playground import CaseIn, PromptQuery, StageRun
from .analytics.db import get_db
from .brain import routing
from .integrations.agent_v4 import AgentError

log = logging.getLogger(__name__)

#: Agent shartnomasidagi yo'l (prefiks `/api/v4` - mijozniki).
DEBUG = "/debug"
#: Bitta bosqich: model javobi uzun bo'lishi mumkin (agent ichida tool-loop yo'q - bitta chaqiruv).
RUN_TIMEOUT = 120.0
SMALL_TIMEOUT = 15.0
#: Tahrirlangan kirish hajmi - agentning o'z chegarasi bor, bu yerda keraksiz yukni to'xtatamiz.
MAX_INPUT_BYTES = 400_000


@dataclass
class Unavailable(Exception):
    """Playground hozir ishlay olmaydi - sababi odam tilida va HTTP holati bilan."""

    status: int
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - jurnal uchun
        return f"{self.code}: {self.message}"


def _from_agent(exc: AgentError) -> Unavailable:
    code = exc.code or "agent_error"
    if exc.status == 404 and code in ("http_404", "not_found_route"):
        return Unavailable(501, "debug_missing",
                           "Agent tomonida playground hali yoqilmagan (/api/v4/debug). Agent jamoasi "
                           "DEBUG_PLAYGROUND_ENABLED ni yoqishi kerak.")
    if exc.status in (401, 403):
        return Unavailable(403, "debug_forbidden", "Agent debug ruxsatini bermadi (mijozda debug huquqi yo'q).")
    if code in ("circuit_open", "busy") or exc.status in (429, 503):
        return Unavailable(503, code, "Agent band yoki vaqtincha javob bermayapti - birozdan keyin urinib ko'ring.")
    if code == "network":
        return Unavailable(502, code, "Agentga ulanib bo'lmadi (tarmoq).")
    if code == "not_configured":
        return Unavailable(503, code, "Agent manzili yoki kaliti sozlanmagan.")
    if exc.status and 400 <= exc.status < 500:
        detail = f": {exc.detail}" if getattr(exc, "detail", "") else ""
        return Unavailable(400, code, f"Agent kirishni qabul qilmadi ({code}){detail}")
    return Unavailable(502, code, f"Agent xatosi ({code}).")


def _call(method: str, path: str, *, op: str, body: dict[str, Any] | None = None,
          timeout: float = SMALL_TIMEOUT) -> dict[str, Any]:
    client = routing.probe_client()
    if not client.configured:
        raise Unavailable(503, "not_configured", "Agent manzili yoki kaliti sozlanmagan.")
    try:
        payload, _ = client.request(method, f"{DEBUG}{path}", body=body, op=op, timeout=timeout)
    except AgentError as exc:
        raise _from_agent(exc) from None
    return payload


# --- agent ---------------------------------------------------------------------------------


def status() -> dict[str, Any]:
    """Playground ishlaydimi va qaysi modellar tanlanadi. Hech qachon xato bermaydi -
    sahifa sababini ko'rsatadi."""
    try:
        payload = _call("GET", "/models", op="debug.models")
    except Unavailable as exc:
        return {"available": False, "code": exc.code, "message": exc.message, "models": []}
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    return {"available": True, "code": None, "message": None, "models": models,
            "default_model": payload.get("default")}


def turn(turn_id: str) -> dict[str, Any] | None:
    """Bizdagi savol (analitika) + agentdagi bosqichlar yozuvi. `None` - savol topilmadi."""
    row = get_db().row(
        "SELECT id, started_at, user_login, channel, chat_id, request_id, question, answer, route, engine, "
        "status, ttft_ms, total_ms FROM turns WHERE id=?", (turn_id,))
    if row is None:
        return None
    capture: dict[str, Any] | None = None
    problem: dict[str, Any] | None = None
    if not row.get("request_id"):
        problem = {"code": "no_request_id", "message": "Bu savolda agent so'rov raqami yo'q (eski yoki lokal javob)."}
    else:
        try:
            capture = _call("GET", f"/turns/{row['request_id']}", op="debug.turn")
        except Unavailable as exc:
            if exc.status == 400 and exc.code in ("not_found", "turn_not_found", "expired"):
                problem = {"code": "not_captured",
                           "message": "Agent bu savolning bosqichlarini saqlamagan (eski yoki muddati o'tgan)."}
            else:
                problem = {"code": exc.code, "message": exc.message}
    return {"turn": row, "capture": capture, "problem": problem}


def prompt(query: PromptQuery) -> dict[str, Any]:
    """Yangi savol uchun bosqich kirishini yig'ish - model chaqirilmaydi."""
    return _call("POST", "/prompt", op="debug.prompt", body=query.model_dump(), timeout=30.0)


def _one(body: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        out = _call("POST", "/run", op="debug.run", body=body, timeout=RUN_TIMEOUT)
    except Unavailable as exc:
        return {"model": body.get("model"), "ok": False, "code": exc.code, "message": exc.message,
                "ms": round((time.monotonic() - started) * 1000)}
    return {"model": out.get("model") or body.get("model"), "ok": True, "output": out.get("output"),
            "ms": out.get("ms"), "tokens_in": out.get("tokens_in"), "tokens_out": out.get("tokens_out"),
            "tool_calls": out.get("tool_calls")}


def check_size(req: StageRun) -> None:
    size = len(json.dumps(req.input, ensure_ascii=False).encode("utf-8"))
    if size > MAX_INPUT_BYTES:
        raise Unavailable(413, "too_large", f"Kirish juda katta ({size // 1000} KB, chegara {MAX_INPUT_BYTES // 1000} KB).")


def run(req: StageRun) -> dict[str, Any]:
    """Bitta bosqich (va ixtiyoriy ikkinchi model) - AYNI kirish bilan. Ikki model
    parallel: solishtirishda kutish ikki baravar uzaymasin."""
    check_size(req)
    base = {"stage": req.stage, "input": req.input,
            "params": req.params.model_dump(exclude_none=True)}
    bodies = [{**base, "model": req.model}]
    if req.compare_model:
        bodies.append({**base, "model": req.compare_model})
    if len(bodies) == 1:
        return {"runs": [_one(bodies[0])]}
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="playground") as pool:
        return {"runs": list(pool.map(_one, bodies))}


# --- regressiya sinovlari ---------------------------------------------------------------------


def _case_view(row: dict[str, Any]) -> dict[str, Any]:
    return {**{k: row[k] for k in ("id", "created_at", "created_by", "title", "area", "needs", "turn_id",
                                   "stage", "note")},
            "dialog": json.loads(row["dialog"]), "expect": json.loads(row["expect"])}


def create_case(conn: Any, case: CaseIn, by: str) -> dict[str, Any]:
    row = {"id": uuid.uuid4().hex, "created_at": time.time(), "created_by": by, "title": case.title,
           "area": case.area, "needs": case.needs,
           "dialog": json.dumps(case.dialog, ensure_ascii=False),
           "expect": json.dumps(case.expect, ensure_ascii=False),
           "turn_id": case.turn_id, "stage": case.stage, "note": case.note}
    conn.execute(
        "INSERT INTO playground_cases (id, created_at, created_by, title, area, needs, dialog, expect, turn_id, "
        "stage, note) VALUES (:id, :created_at, :created_by, :title, :area, :needs, :dialog, :expect, :turn_id, "
        ":stage, :note)", row)
    return _case_view(row)


def list_cases(limit: int = 200) -> list[dict[str, Any]]:
    rows = get_db().rows("SELECT * FROM playground_cases WHERE archived=0 ORDER BY created_at DESC LIMIT ?",
                         (int(limit),))
    return [_case_view(r) for r in rows]


def archive_case(conn: Any, case_id: str) -> bool:
    cur = conn.execute("UPDATE playground_cases SET archived=1 WHERE id=? AND archived=0", (case_id,))
    return cur.rowcount > 0


def export_suite() -> dict[str, Any]:
    """Sinovlar `~/.local/share/barno-eval/run_inproc.py` to'plami shaklida
    (`{dialogs: [{id, area, needs, turns, expect}]}`): admin saqlagan holat keyingi
    tekshiruvda o'z-o'zidan qatnashadi."""
    cases = list(reversed(list_cases(limit=1000)))
    return {"created": time.strftime("%Y-%m-%d", time.gmtime()), "source": "admin playground",
            "dialogs": [{"id": f"P{i}", "area": c["area"], "needs": c["needs"], "turns": c["dialog"],
                         "expect": c["expect"], "title": c["title"], "case_id": c["id"]}
                        for i, c in enumerate(cases, start=1)]}

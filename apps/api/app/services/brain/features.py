"""Funksiya darajasidagi choklar: zanjir bo'g'ini yoki butun vazifa agentga.

  * `brief_crm_ask(local)`        - brif CRM tekshiruvi: lokal = bugungi `agent_ask` +
                                    gemma normalizer; agent = bitta chat vazifasi
                                    (`purpose=brief_crm`, `store:false`, faqat `crm.read`,
                                    `response_format`, shartnoma 6.6.3, W1 shakli).
  * `meeting_summary_providers`   - yig'ilish xulosasi zanjiri: agent holatida boshiga
                                    `agent` bo'g'ini qo'yiladi. BUTUN xulosa bitta modelda
                                    yoziladi, agent yiqilsa - bugungi zanjir boshidan.
  * `meeting_ask_providers`       - savol-javob zanjiri, xuddi shunday.
  * `hold_mode` / `hold_shadow`   - ovozli kutish tasnifi (`HOLD_CLASSIFIER`, `route` kadri).
  * `admin_view`                  - admin sahifasi uchun hamma narsa bitta joyda.

Lokal yo'l - HAR DOIM bugungi kod, o'zgarmasdan. Agent xatosi - lokal zahira
(`chat.note_fallback`). Shadow - foydalanuvchi kutmaydi (`shadow.py`).
"""

from __future__ import annotations

import copy
import json
import logging
import time

from collections.abc import Callable, Mapping
from typing import Any

from ...core import config as _config
from ...core.config import settings
from .. import engine_control as _control
from ..integrations.agent_v4 import AgentError, AgentV4Client
from . import routing, shadow
from .chat import AgentComplete, note_fallback

log = logging.getLogger(__name__)


# --- brif CRM holati -------------------------------------------------------------------------

#: `brief_crm` natijasi (shartnoma 9.3.7) - OpenAI "strict" qoidalari: hamma maydon
#: majburiy, bo'sh qiymat - `null`.
CRM_STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tasks"],
    "properties": {"tasks": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["n", "found", "key", "title", "status", "assignee", "due", "updated"],
        "properties": {
            "n": {"type": "integer"},
            "found": {"type": "boolean"},
            "key": {"type": ["string", "null"]},
            "title": {"type": ["string", "null"]},
            "status": {"type": ["string", "null"]},
            "assignee": {"type": ["string", "null"]},
            "due": {"type": ["string", "null"]},
            "updated": {"type": ["string", "null"]},
        }}}},
}

AskFn = Callable[[str, Any, float], dict[str, Any]]


def brief_crm_request(question: str, actor_id: Any, crm_token: str, *, shadow_mode: bool = False) -> dict[str, Any]:
    """Shartnoma 6.6.3 (W1 shakli): bugungi savol matni + `response_format`. Faqat
    CRM tokeni (HRM yo'q), `store:false` - rahbar tarixi va xotirasi to'lmaydi,
    `venera-brief:` aylanma kimligi kerak emas."""
    body: dict[str, Any] = {
        "purpose": "brief_crm",
        "question": question,
        "user_id": f"venera:{actor_id}",
        "tokens": {"crm": crm_token},
        "store": False,
        "audience": "private",
        "tools": ["crm.read"],
        "memory_scopes": [],
        "response_format": {"type": "json_schema", "name": "crm_status", "schema": CRM_STATUS_SCHEMA,
                            "strict": True},
        "client": {"channel": "bot"},
    }
    if shadow_mode:
        body["shadow"] = True
    return body


def agent_brief_crm(client: AgentV4Client, question: str, user: Any, timeout: float, *,
                    shadow_mode: bool = False, tokens: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Agent vazifasi -> `agent_ask` bilan BIR XIL shakl: `{answer, sources, error}`.
    `answer` - natija JSON matni: `CrmChecker` uni bugungidek o'qiydi va tekshiradi
    (`_crm_read`, `_valid`), normalizer kerak bo'lmaydi."""
    if tokens is None:
        from ...api.v1 import chat as _chat

        tokens = _chat._live_tokens(user)
    crm = (tokens or {}).get("crm")
    if not crm:
        return {"answer": "", "sources": [], "error": {"code": "auth_missing"}}
    body = brief_crm_request(question, user.actorId, crm, shadow_mode=shadow_mode)
    payload, _ = client.chat(body, op="shadow.brief_crm" if shadow_mode else "brief_crm", timeout=timeout,
                             units={"chars": len(question)})
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    code = meta.get("error_code")
    result = payload.get("result")
    if isinstance(result, (dict, list)):
        answer = json.dumps(result, ensure_ascii=False)
    else:
        answer = str(payload.get("answer") or "")
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    reply: dict[str, Any] = {"answer": answer, "sources": sources,
                             "error": {"code": str(code)[:48]} if code else None}
    reply["traceId"] = str(meta.get("trace_id") or "")[:64] or None
    return reply


def _found(reply: Mapping[str, Any]) -> list[str]:
    """Javobdagi `found: true` vazifalar raqamlari (taqqoslash uchun)."""
    parsed = shadow.parse_json(reply.get("answer"))
    rows = parsed.get("tasks") if isinstance(parsed, dict) else None
    out: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("found") is True:
            out.append(str(row.get("n")))
    return out


def _crm_read(reply: Mapping[str, Any]) -> bool:
    return any(isinstance(s, dict) and s.get("kind") == "crm" for s in reply.get("sources") or [])


def brief_crm_ask(local: AskFn) -> AskFn:
    """`CrmChecker(ask=...)` uchun o'ram. Lokal - `local` ning o'zi (bugungi `agent_ask`)."""

    def ask(question: str, user: Any, timeout: float) -> dict[str, Any]:
        route = routing.route("brief_crm")
        if route.agent:
            try:
                return agent_brief_crm(routing.client("interactive"), question, user, timeout)
            except Exception as exc:                        # noqa: BLE001 - zahira har qanday xatoda
                note_fallback("brief_crm", "brief_crm", exc)
        started = time.monotonic()
        reply = local(question, user, timeout)
        if route.shadow and isinstance(reply, dict) and not reply.get("error"):
            _brief_crm_shadow(question, user, timeout, reply, (time.monotonic() - started) * 1000.0,
                              route.sample_rate)
        return reply

    return ask


def _brief_crm_shadow(question: str, user: Any, timeout: float, local: dict[str, Any], local_ms: float,
                      sample_rate: float) -> None:
    # Token HOZIR olinadi (so'rov ipida): fondagi ish odamning sessiyasini yangilamasin.
    from ...api.v1 import chat as _chat

    tokens = {k: v for k, v in _chat._live_tokens(user).items() if k == "crm"}
    local_found = _found(local)

    def job() -> None:
        started = time.monotonic()
        base = dict(local_ms=local_ms, input_chars=len(question), local_chars=len(str(local.get("answer") or "")))
        try:
            reply = agent_brief_crm(routing.client("shadow"), question, user, timeout, shadow_mode=True,
                                    tokens=tokens)
        except AgentError as exc:
            shadow.record("brief_crm", "brief_crm", status="error", agent_ms=(time.monotonic() - started) * 1000,
                          error=exc, **base)
            return
        agent_found = _found(reply)
        shadow.record("brief_crm", "brief_crm", status="error" if reply.get("error") else "ok",
                      trace_id=reply.get("traceId"), agent_ms=(time.monotonic() - started) * 1000,
                      agent_chars=len(reply.get("answer") or ""), similarity=shadow.overlap(local_found, agent_found),
                      metrics={"local_found": len(local_found), "agent_found": len(agent_found),
                               "local_crm_read": _crm_read(local), "agent_crm_read": _crm_read(reply)},
                      error=(reply.get("error") or {}).get("code"), **base)

    shadow.submit("brief_crm", job, sample_rate=sample_rate)


# --- yig'ilish xulosasi va savol-javob: zanjir bo'g'ini ---------------------------------------------


def _agent_link(name: str, client_name: str, language: str = "uz") -> Any:
    from ..meetings.llm import Provider

    return Provider("agent", AgentComplete(lambda: routing.client(client_name), language=language, name=name))


#: Agentga hech qaysi holatda (`shadow`, `agent`) bormaydigan yozuv turlari. Telefon
#: qo'ng'irog'i: ikkinchi tomonning ovozi va mijoz raqami - avval serverda rozilik yozuvi
#: va huquqiy qaror (`boundary.md` 5.3, 8.1 #5, reja D8), keyin alohida `call_summary`
#: flag'i. Bu yerda flag yo'q - ataylab: admin bitta kalit bilan qo'ng'iroqlarni
#: yuborib qo'ya olmasin.
AGENT_EXCLUDED_SOURCES = frozenset({"call"})


def meeting_agent_ok(meeting: Mapping[str, Any] | None) -> bool:
    """Shu yozuv uchun YANGI agent yo'li (zanjir bo'g'ini, shadow) mumkinmi."""
    source = str((meeting or {}).get("source") or "").strip().lower()
    return source not in AGENT_EXCLUDED_SOURCES


def meeting_summary_providers(providers: list[Any], *, language: str = "uz") -> list[Any]:
    """Agent holatida - zanjir boshiga `agent` (bitta xulosa - bitta model; yiqilsa
    `run_chain` bugungi zanjirni boshidan yuradi). Aks holda ro'yxat o'zgarmaydi."""
    if not routing.route("meeting_summary").agent:
        return providers
    return [_agent_link("meeting_summary", "meetings", language), *providers]


def meeting_ask_providers(providers: list[Any], *, language: str = "uz") -> list[Any]:
    """Savol-javob zanjiri: agent holatida boshiga `agent`; `local` - bugungi zanjir
    (`MEETINGS_ASK_CHAIN`) o'zgarmaydi."""
    if not routing.route("meeting_ask").agent:
        return providers
    return [_agent_link("meeting_ask", "interactive", language), *providers]


def _digest(content: Mapping[str, Any] | None) -> str:
    """Xulosaning taqqoslanadigan matni: sarlavha, umumiy matn, vazifa va qarorlar."""
    if not isinstance(content, Mapping):
        return ""
    parts = [str(content.get(key) or "") for key in ("title", "overview", "summary", "tldr")]
    for key, field in (("actionItems", "task"), ("decisions", "text"), ("keyPoints", "text")):
        for item in content.get(key) or []:
            if isinstance(item, Mapping):
                parts.append(str(item.get(field) or ""))
    return "\n".join(p for p in parts if p)


def _counts(content: Mapping[str, Any] | None, side: str) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(content, Mapping):
        return out
    for key, name in (("actionItems", "actions"), ("decisions", "decisions"), ("keyPoints", "points"),
                      ("openQuestions", "questions"), ("topics", "topics")):
        value = content.get(key)
        if isinstance(value, list):
            out[f"{side}_{name}"] = len(value)
    return out


def meeting_summary_shadow(inp: Any, local_content: Mapping[str, Any] | None, local_ms: float) -> bool:
    """Lokal xulosa tayyor bo'lgach (agent holatida emas): namuna bo'yicha fonda
    agent butun quvurni bizning tekshirgichlar bilan yuradi. `True` - navbatga qo'yildi."""
    route = routing.route("meeting_summary")
    if not route.shadow:
        return False
    snapshot = copy.deepcopy(inp)
    local = copy.deepcopy(dict(local_content or {}))
    chars = sum(len(str(s.get("text") or "")) for s in getattr(snapshot, "segments", []) or [])

    def job() -> None:
        from ..meetings.summarize import Pipeline

        started = time.monotonic()
        base = dict(local_ms=local_ms, input_chars=chars, local_chars=len(_digest(local)))
        pipeline = Pipeline(AgentComplete(lambda: routing.client("shadow"), shadow=True,
                                          language=getattr(snapshot, "language", "uz") or "uz"),
                            single_pass_chars=settings.meetings_single_pass_chars,
                            map_chars=settings.meetings_map_chars, verify=settings.meetings_verify,
                            extract_predict=settings.meetings_extract_num_predict,
                            map_predict=settings.meetings_map_num_predict)
        try:
            out = pipeline.run(snapshot)
        except Exception as exc:                            # noqa: BLE001 - shadow hech narsani buzmaydi
            shadow.record("meeting_summary", "meeting_summary", status="error",
                          agent_ms=(time.monotonic() - started) * 1000, error=exc,
                          metrics={"calls": pipeline.steps}, **base)
            return
        content = out.content if isinstance(out.content, Mapping) else None
        shadow.record("meeting_summary", "meeting_summary", status="ok" if content else "error",
                      agent_ms=(time.monotonic() - started) * 1000, agent_chars=len(_digest(content)),
                      similarity=shadow.similarity(_digest(local), _digest(content)),
                      metrics={**_counts(local, "local"), **_counts(content, "agent"), "calls": pipeline.steps,
                               "chunks": pipeline.chunks, "warnings": len(pipeline.warnings),
                               "same_template": out.template == local.get("template")},
                      error=None if content else (out.error_code or out.status), **base)

    return shadow.submit("meeting_summary", job, sample_rate=route.sample_rate)


def meeting_ask_shadow(kwargs: Mapping[str, Any], local: Mapping[str, Any], local_ms: float) -> bool:
    """Savol-javob: lokal javob berilgach, agent xuddi shu savolga (bizning prompt va
    `Validator` bilan) fonda javob yozadi. Taqqoslash: matn va iqtiboslar."""
    route = routing.route("meeting_ask")
    if not route.shadow:
        return False
    args = copy.deepcopy(dict(kwargs))
    local_answer = str(local.get("answer") or "")
    local_cites = list(local.get("citations") or [])

    def job() -> None:
        from ..meetings.ask import answer

        started = time.monotonic()
        base = dict(local_ms=local_ms, input_chars=len(str(args.get("question") or "")),
                    local_chars=len(local_answer))
        try:
            result = answer(AgentComplete(lambda: routing.client("shadow"), shadow=True,
                                          language=str(args.get("language") or "uz")), budget=0, **args)
        except Exception as exc:                            # noqa: BLE001
            shadow.record("meeting_ask", "meeting_ask", status="error",
                          agent_ms=(time.monotonic() - started) * 1000, error=exc, **base)
            return
        text = str(result.get("answer") or "")
        cites = list(result.get("citations") or [])
        shadow.record("meeting_ask", "meeting_ask", status="ok", agent_ms=(time.monotonic() - started) * 1000,
                      agent_chars=len(text), similarity=shadow.similarity(local_answer, text),
                      metrics={"local_citations": len(local_cites), "agent_citations": len(cites),
                               "citation_overlap": shadow.overlap(local_cites, cites) or 0.0}, **base)

    return shadow.submit("meeting_ask", job, sample_rate=route.sample_rate)


# --- ovozli kutish tasnifi -------------------------------------------------------------------


def hold_mode() -> tuple[str, bool]:
    """(lokal tasnif usuli, `route` kadrini kuzatish kerakmi).

    * `agent`   - LLM chaqirilmaydi; yorliq chat oqimidagi `route` kadridan, kelmasa
                  kalit so'z jadvalidan (`hold_first_ms` da, bugungi zahira yo'li);
    * `llm`     - bugungidek gemma (`HOLD_CLASSIFIER=llm`, default);
    * `keyword` - faqat jadval: ovozli savol `ollama.com` ga CHIQMAYDI.
    Ikkinchi qiymat `True` - shadow: `route` kadri kelganda lokal yorliq bilan taqqoslanadi."""
    route = routing.route("hold_classify")
    if route.agent:
        return "agent", True
    return _config.hold_classifier_now(), route.shadow


def hold_shadow(local: tuple[str, str] | None, agent: tuple[str, str] | None, *, local_source: str,
                route_ms: float | None, confidence: Any = None) -> bool:
    """`route` kadri va lokal yorliq taqqoslanadi (qo'shimcha chaqiruv yo'q - kadr bepul)."""
    if local is None or agent is None:
        return False
    return shadow.record("hold_classify", "classify", status="ok", agent_ms=route_ms,
                         similarity=1.0 if local[0] == agent[0] else 0.0,
                         metrics={"tone_equal": local[1] == agent[1], "local_llm": local_source == "ollama",
                                  **({"confidence": float(confidence)} if isinstance(confidence, (int, float))
                                     and not isinstance(confidence, bool) else {})})


# --- admin ------------------------------------------------------------------------------------


def admin_view(*, refresh: bool = False) -> dict[str, Any]:
    """`GET /api/v1/admin/engines/brain` - flag'lar (sozlangan va hozir ishlayotgan,
    nega), agent holati va imkoniyatlari, shadow navbati, hold tasnifchisi. Sir yo'q."""
    caps = routing.capabilities()
    usable, reason = routing.agent_usable()
    if refresh and usable:
        caps.refresh()
    features = []
    for row in _control.brain_view():
        route = routing.route(row["feature"])
        features.append({**row, "effective": route.effective, "reason": route.reason})
    return {
        "states": list(_control.BRAIN_STATES),
        "features": features,
        "agent": {"enabled": _config.agent_v4_enabled_now(), "configured": routing.client().configured,
                  "usable": usable, "reason": reason, "capabilities": caps.state(),
                  "circuit": routing.client().breaker.state()},
        "shadow": shadow.get_queue().stats(),
        "holdClassifier": _config.hold_classifier_now(),
    }

"""Soxta agent (v4 shartnomasi) - tarmoqsiz `transport`. Hech bir test haqiqiy
xizmatga chiqmaydi: `AgentV4Client(transport=FakeAgent(...))`."""

from __future__ import annotations

import json
import threading

from typing import Any, Callable

from app.core.config import settings
from app.services.brain import routing
from app.services.integrations.agent_v4 import AgentV4Client

SECRET = "sekret-agent-0123456789"

#: Hammasi bor: v4 to'liq yetkazilgan agent.
FULL_CAPS: dict[str, Any] = {
    "contract": "4.0",
    "in_network_models_only": True,
    "features": {
        "purpose": True, "store": True, "chat_visibility": True, "context": True, "audience": True,
        "tools_allowlist": True, "response_format": True, "chat_template": False, "shadow": True,
        "complete": True, "instructions_mode": True, "jobs": True, "job_kinds": ["meeting_summary"],
        "frames": ["route", "stage", "sources", "token", "done", "error"],
    },
    "engines": ["v2", "v3", "v4"],
}


def caps_without(*names: str) -> dict[str, Any]:
    out = json.loads(json.dumps(FULL_CAPS))
    for name in names:
        key, _, value = name.partition(":")
        if value:
            out["features"][key] = [v for v in out["features"].get(key, []) if v != value]
        else:
            out["features"][key] = False
    return out


def _complete_ok(body: dict[str, Any]) -> dict[str, Any]:
    return {"output": "Agent javobi: login xatosi tuzatildi.", "cited_ids": [],
            "validation": {"schema_valid": True, "repaired": False, "dropped_citations": 0,
                           "dropped_items": 0, "warnings": []},
            "meta": {"trace_id": "trace-1", "request_id": "r", "purpose": body.get("purpose"),
                     "engine": "v4", "model": "in-network", "priority": body.get("priority"),
                     "queue_ms": 1, "ms": 5, "tokens_in": 100, "tokens_out": 20, "truncated": False,
                     "attempts": 1, "store_applied": False}}


def _chat_ok(body: dict[str, Any]) -> dict[str, Any]:
    return {"answer": "", "sources": [{"kind": "crm", "tool": "crm.search_issues", "status": "ok"}],
            "result": {"tasks": [{"n": 1, "found": True, "key": "DVSIB-131", "title": "Kredit hisobi",
                                  "status": "In progress", "assignee": "Yusufxon", "due": None,
                                  "updated": "2026-10-09"}]},
            "proposals": [], "meta": {"trace_id": "trace-chat", "purpose": body.get("purpose"),
                                      "store_applied": False}}


class FakeAgent:
    """`transport` o'rnida. `handlers[path]` - `body -> payload` yoki `(status, payload)`;
    istisno ko'tarsa - tarmoq xatosi kabi."""

    def __init__(self, *, caps: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "/capabilities": lambda body: caps or FULL_CAPS,
            "/limits": lambda body: {"complete": {"max_input_chars": 200000}},
            "/complete": _complete_ok,
            "/chat": _chat_ok,
        }

    def __call__(self, method, url, headers, body, timeout):
        path = url.split("/api/v4", 1)[1] if "/api/v4" in url else url
        payload = json.loads(body.decode("utf-8")) if body else None
        with self.lock:
            self.calls.append({"method": method, "url": url, "path": path, "headers": dict(headers),
                               "body": payload, "timeout": timeout})
        handler = self.handlers.get(path)
        if handler is None:
            return 404, {}, json.dumps({"error": {"code": "not_found", "message": "yo'q"}}).encode()
        result = handler(payload or {})
        status = 200
        if isinstance(result, tuple):
            status, result = result
        return status, {"Content-Type": "application/json"}, json.dumps(result, ensure_ascii=False).encode()

    def paths(self) -> list[str]:
        with self.lock:
            return [c["path"] for c in self.calls]

    def bodies(self, path: str) -> list[dict[str, Any]]:
        with self.lock:
            return [c["body"] for c in self.calls if c["path"] == path]

    def client(self, **kwargs: Any) -> AgentV4Client:
        kwargs.setdefault("max_concurrent", 2)
        return AgentV4Client("http://agent.test", "barno-test", SECRET, transport=self, **kwargs)


def enable_agent(monkeypatch, fake: FakeAgent, *, caps: dict[str, Any] | None = None,
                 **engines: str) -> FakeAgent:
    """Bosh kalit yoqiq, mijozlar soxta agentga, imkoniyatlar keshi to'la.
    `engines` - `group_ask="agent"` kabi flag'lar (`.env` qatlami)."""
    monkeypatch.setattr(settings, "agent_v4_enabled", True, raising=False)
    for feature, state in engines.items():
        monkeypatch.setattr(settings, f"{feature}_engine", state, raising=False)
    # Haqiqiy `routing._build` dagi kabi: shadow va yig'ilish - fon ishchisi kanali.
    routing.reset_for_tests(interactive=fake.client(channel="bot"),
                            batch=fake.client(max_concurrent=1, channel="worker"),
                            meetings=fake.client(max_concurrent=1, channel="worker"),
                            shadow=fake.client(max_concurrent=1, slot_wait=5.0, channel="worker"),
                            caps=caps if caps is not None else FULL_CAPS)
    return fake

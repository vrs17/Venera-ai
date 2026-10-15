"""Admin "Agent playground" (`admin_playground.py`, `services/playground.py`).

Asosiy kafolatlar:
  * hamma yo'l FAQAT ADMIN (oddiy xodimga 403, tokensiz 401) - unda xom promptlar;
  * agentga faqat `/api/v4/debug/*` ketadi, o'z uzgichi bilan (`probe_client`);
  * model chaqiruvi tasdiqsiz bo'lmaydi (428), ikki model AYNI kirish bilan;
  * agent debug yoqilmagan, ruxsat bermagan yoki savolni saqlamagan bo'lsa - tushunarli sabab;
  * sinov saqlash: savollar va kutilgan xulq, bosqich kirishi emas; eksport `run_inproc` shaklida;
  * har ko'rish va ishga tushirish auditda, kiritilgan matn auditda yo'q.
Tashqi xizmat chaqirilmaydi.
"""

from __future__ import annotations

import json

import pytest

from agent_fakes import FakeAgent
from app.api.v1 import admin_probe
from app.services.analytics import get_db
from app.services.brain import routing

API = "/api/v1/admin/playground"

CAPTURE = {
    "request_id": "rid-1", "engine": "v4", "route": "biznes247_kpi",
    "stages": [
        {"id": "s1", "name": "router", "model": "gemma4:31b-cloud", "ms": 900, "tokens_in": 1200, "tokens_out": 80,
         "input": {"system": "You route questions.", "messages": [{"role": "user", "content": "savol"}]},
         "output": {"json": {"route": "biznes247_kpi"}}},
        {"id": "s2", "name": "bank_writer", "model": "gemma4:31b-cloud", "ms": 2100, "tokens_in": 900,
         "tokens_out": 60, "input": {"system": "Write the answer.", "messages": [], "extra": {"facts": "jami: 24 799 so'm"}},
         "output": {"text": "24 799 so'm deb ko'rsatilgan"}},
    ],
}


@pytest.fixture
def agent(monkeypatch):
    fake = FakeAgent()
    fake.handlers.update({
        "/debug/models": lambda body: {"models": ["gemma4:31b-cloud", "gpt-6-luna"], "default": "gemma4:31b-cloud"},
        "/debug/turns/rid-1": lambda body: CAPTURE,
        "/debug/turns/rid-old": lambda body: (404, {"error": {"code": "turn_not_found", "message": "yo'q"}}),
        "/debug/prompt": lambda body: {"stage": body["stage"], "input": {"system": "S", "messages": []}},
        "/debug/run": lambda body: {"model": body.get("model") or "gemma4:31b-cloud", "output": {"text": "javob"},
                                    "ms": 1500, "tokens_in": 900, "tokens_out": 40,
                                    "tool_calls": [{"name": "crm_my_issues", "arguments": {}}]},
    })
    monkeypatch.setattr(routing, "probe_client", lambda: fake.client(channel="bot"))
    admin_probe._paid_runs.clear()
    return fake


def _turn(turn_id: str = "t1", request_id: str | None = "rid-1") -> None:
    with get_db().transaction() as conn:
        conn.execute("INSERT INTO turns (id, started_at, channel, question, answer, request_id, route, engine) "
                     "VALUES (?, 1792055700, 'web', 'Biznes 24/7 holati', '24 799 so''m', ?, 'biznes247_kpi', 'v4')",
                     (turn_id, request_id))


def _audit() -> list[dict]:
    rows = get_db().rows("SELECT action, target_id, detail FROM audit_log WHERE action LIKE 'playground.%' ORDER BY id")
    for row in rows:
        row["detail"] = json.loads(row["detail"]) if row["detail"] else None
    return rows


_ROUTES = [
    ("get", "/status", None),
    ("get", "/turns/t1", None),
    ("post", "/prompt", {"stage": "router", "question": "savol"}),
    ("post", "/run", {"stage": "router", "input": {}, "confirm_cost": True}),
    ("get", "/cases", None),
    ("post", "/cases", {"title": "t", "dialog": ["a"], "expect": ["b"]}),
    ("delete", "/cases/x1", None),
    ("get", "/cases/export", None),
]


@pytest.mark.parametrize("method,path,body", _ROUTES)
def test_faqat_admin(client, user_auth, agent, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(f"{API}{path}", headers=user_auth, **kwargs).status_code == 403
    assert getattr(client, method)(f"{API}{path}", **kwargs).status_code == 401
    assert agent.paths() == []                       # huquqsiz so'rov agentga chiqmaydi


def test_status_modellar_va_debug_yoqilmagan(client, auth, agent):
    body = client.get(f"{API}/status", headers=auth).json()
    assert body["available"] is True and body["models"] == ["gemma4:31b-cloud", "gpt-6-luna"]
    # Agentda yo'l yo'q (FastAPI 404 `detail` bilan) - debug yoqilmagan deb aytiladi.
    agent.handlers["/debug/models"] = lambda body: (404, {"detail": "Not Found"})
    body = client.get(f"{API}/status", headers=auth).json()
    assert body["available"] is False and body["code"] == "debug_missing"
    assert "DEBUG_PLAYGROUND_ENABLED" in body["message"]


def test_savol_va_bosqichlar(client, auth, agent):
    _turn()
    body = client.get(f"{API}/turns/t1", headers=auth).json()
    assert body["turn"]["request_id"] == "rid-1" and body["turn"]["question"] == "Biznes 24/7 holati"
    assert [s["name"] for s in body["capture"]["stages"]] == ["router", "bank_writer"]
    assert body["problem"] is None
    assert agent.paths() == ["/debug/turns/rid-1"]
    # Kim xom promptni ko'rgani auditda; savol matni yo'q.
    audit = _audit()
    assert audit[-1]["action"] == "playground.view" and audit[-1]["target_id"] == "t1"
    assert "Biznes" not in json.dumps(audit, ensure_ascii=False)


def test_saqlanmagan_va_raqamsiz_savol(client, auth, agent):
    _turn("t2", "rid-old")
    _turn("t3", None)
    old = client.get(f"{API}/turns/t2", headers=auth).json()
    assert old["capture"] is None and old["problem"]["code"] == "not_captured"
    bare = client.get(f"{API}/turns/t3", headers=auth).json()
    assert bare["capture"] is None and bare["problem"]["code"] == "no_request_id"
    assert client.get(f"{API}/turns/yoq", headers=auth).status_code == 404


def test_ishga_tushirish_tasdiq_va_ikki_model(client, auth, agent):
    run = {"stage": "bank_writer", "input": CAPTURE["stages"][1]["input"], "model": "gemma4:31b-cloud"}
    first = client.post(f"{API}/run", headers=auth, json=run)
    assert first.status_code == 428 and agent.bodies("/debug/run") == []    # tasdiqsiz - model chaqirilmaydi
    body = client.post(f"{API}/run", headers=auth,
                       json={**run, "compare_model": "gpt-6-luna", "confirm_cost": True,
                             "params": {"temperature": 0.2}}).json()
    assert [r["model"] for r in body["runs"]] == ["gemma4:31b-cloud", "gpt-6-luna"]
    assert all(r["ok"] and r["output"] == {"text": "javob"} for r in body["runs"])
    # Vosita chaqiruvi QAYTARILADI (bajarilmaydi) - sahifa ko'rsatadi.
    assert body["runs"][0]["tool_calls"][0]["name"] == "crm_my_issues"
    sent = agent.bodies("/debug/run")
    assert len(sent) == 2 and all(s["input"] == run["input"] and s["params"] == {"temperature": 0.2} for s in sent)
    assert {s["model"] for s in sent} == {"gemma4:31b-cloud", "gpt-6-luna"}
    assert "OpenAI pullik" in body["cost_note"]
    audit = _audit()[-1]
    assert audit["action"] == "playground.run" and audit["detail"]["models"] == ["gemma4:31b-cloud", "gpt-6-luna"]
    assert "24 799" not in json.dumps(audit, ensure_ascii=False)


def test_ishga_tushirish_chegaralari(client, auth, agent, monkeypatch):
    big = {"stage": "router", "input": {"system": "x" * 450_000}, "confirm_cost": True}
    assert client.post(f"{API}/run", headers=auth, json=big).status_code == 413
    bad = {"stage": "Router Stage!", "input": {}, "confirm_cost": True}
    assert client.post(f"{API}/run", headers=auth, json=bad).status_code == 422
    monkeypatch.setattr(admin_probe, "PAID_PER_HOUR", 1)
    ok = {"stage": "router", "input": {"system": "s"}, "confirm_cost": True}
    assert client.post(f"{API}/run", headers=auth, json=ok).status_code == 200
    assert client.post(f"{API}/run", headers=auth, json=ok).status_code == 429


def test_agent_ruxsat_bermadi_va_xato(client, auth, agent):
    agent.handlers["/debug/run"] = lambda body: (403, {"error": {"code": "forbidden", "message": "no scope"}})
    body = client.post(f"{API}/run", headers=auth,
                       json={"stage": "router", "input": {"system": "s"}, "confirm_cost": True}).json()
    run = body["runs"][0]
    assert run["ok"] is False and run["code"] == "debug_forbidden"


def test_prompt_yigish(client, auth, agent):
    body = client.post(f"{API}/prompt", headers=auth,
                       json={"stage": "agent", "question": "CRMda vazifalarim", "platforms": ["crm", "hrm"]}).json()
    assert body["stage"] == "agent"
    assert agent.bodies("/debug/prompt")[0] == {"stage": "agent", "question": "CRMda vazifalarim",
                                                "lang": "uz_latn", "platforms": ["crm", "hrm"]}


def test_sinovlar_saqlash_eksport_arxiv(client, auth, agent):
    case = {"title": "24 799 so'm emas", "dialog": ["Biznes 24/7ni xolati haqida hisobot ber", "  "],
            "expect": ["mijozlar soni so'm deb aytilmaydi"], "turn_id": "t1", "stage": "bank_writer",
            "area": "bank_context"}
    created = client.post(f"{API}/cases", headers=auth, json=case)
    assert created.status_code == 201
    saved = created.json()
    assert saved["dialog"] == ["Biznes 24/7ni xolati haqida hisobot ber"]      # bo'sh qator tashlandi
    assert client.post(f"{API}/cases", headers=auth, json={**case, "dialog": [" "]}).status_code == 422
    items = client.get(f"{API}/cases", headers=auth).json()["items"]
    assert [c["id"] for c in items] == [saved["id"]]
    suite = client.get(f"{API}/cases/export", headers=auth).json()
    assert suite["dialogs"] == [{"id": "P1", "area": "bank_context", "needs": "none",
                                 "turns": ["Biznes 24/7ni xolati haqida hisobot ber"],
                                 "expect": ["mijozlar soni so'm deb aytilmaydi"], "title": "24 799 so'm emas",
                                 "case_id": saved["id"]}]
    assert client.delete(f"{API}/cases/{saved['id']}", headers=auth).json()["archived"] is True
    assert client.get(f"{API}/cases", headers=auth).json()["items"] == []
    assert client.delete(f"{API}/cases/{saved['id']}", headers=auth).status_code == 404
    actions = [a["action"] for a in _audit()]
    assert actions[-2:] == ["playground.case_create", "playground.case_delete"]
    assert agent.paths() == []                       # sinov saqlash agentga chiqmaydi

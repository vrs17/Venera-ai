"""Yig'ilish vazifasi CRM ga - agent v4 shakli (migratsiya W1, 2026-10-11).

`meeting_crm` flag'i `agent` bo'lsa: `purpose: meeting_crm`, faqat `crm.read`/`crm.propose`,
faqat o'z CRM tokeni, `store: false`, `memory_scopes: []`. Agent xatosida va qo'ng'iroq
yozuvida - bugungi v3 yo'li. Tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

from tests.agent_fakes import FakeAgent, enable_agent
from tests.test_agent_w1 import CLOUD_CAPS
from tests.test_meetings_llm import TOKEN, _proposal, crm_ready  # noqa: F401 - pytest fixture
from meetings_fakes import v3_frames


def _agent(monkeypatch) -> FakeAgent:
    fake = FakeAgent()
    fake.handlers["/chat"] = lambda body: {"answer": "Taklif tayyor.", "sources": [], "proposals": [_proposal()["proposal"]],
                                           "meta": {"trace_id": "t-m", "purpose": body.get("purpose"),
                                                    "engine": "v4", "store_applied": False}}
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS, meeting_crm="agent")
    return fake


def test_v4_taklif(client, auth, monkeypatch, crm_ready):  # noqa: F811
    row, item, live = crm_ready
    fake = _agent(monkeypatch)
    body = client.post(f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm", headers=auth).json()
    assert body["status"] == "proposed" and body["proposal"]["token"] == TOKEN
    assert live.calls == []                                       # v3 ga borilmadi
    [sent] = fake.bodies("/chat")
    assert sent["purpose"] == "meeting_crm" and sent["tokens"] == {"crm": "crm-jwt"}
    assert (sent["store"], sent["audience"], sent["memory_scopes"]) == (False, "private", [])
    assert sent["tools"] == ["crm.read", "crm.propose"] and sent["user_id"] == f"venera:{row['actor_id']}"
    assert "FAQAT BITTA taklif" in sent["question"]


def test_v4_xatosida_bugungi_yol(client, auth, monkeypatch, crm_ready):  # noqa: F811
    row, item, live = crm_ready
    fake = _agent(monkeypatch)
    fake.handlers["/chat"] = lambda body: (503, {"error": {"code": "model_unavailable", "message": "m"}})
    live.script["meeting_crm"] = [v3_frames("Taklif tayyor.", extra=[_proposal()])]
    body = client.post(f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm", headers=auth).json()
    assert body["status"] == "proposed" and len(live.calls) == 1


def test_qongiroq_yozuvi_agentga_bormaydi(client, auth, monkeypatch, crm_ready, _isolated_meetings):  # noqa: F811
    row, item, live = crm_ready
    fake = _agent(monkeypatch)
    _isolated_meetings.store.update_meeting(row["id"], source="call")
    live.script["meeting_crm"] = [v3_frames("Taklif tayyor.", extra=[_proposal()])]
    body = client.post(f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm", headers=auth).json()
    assert body["status"] == "proposed" and fake.bodies("/chat") == [] and len(live.calls) == 1

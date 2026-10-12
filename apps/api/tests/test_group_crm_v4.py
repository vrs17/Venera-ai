"""Guruh CRM - agent v4 shakli (migratsiya W1, 2026-10-11).

Shakl agent jamoasi tasdiqlagan ko'rinishda: savol - so'rovchining O'Z matni (sarlavhasiz),
bitta kontekst bloki (`tg:<chat>`, niqoblangan, `policy.external_llm`), `surface` suhbat,
`audience: group`, faqat `crm.read`/`crm.propose`, faqat o'z CRM tokeni, `retention_days: 7`,
`reply_to_ref` - javob qilingan xabar bandlar ichida bo'lsa. Agent xatosida - bugungi yo'l.
Tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import pytest

from app.bot import group_actions as ga
from app.services.brain import routing
from app.services.brain import shadow as brain_shadow
from tests.agent_fakes import FakeAgent, enable_agent
from tests.test_agent_w1 import CLOUD_CAPS
from tests.test_bot_group_actions import ISLOM, YUSUF, gmsg, group_sent, make_world, mockup, send
from tests.test_bot_groups import BOT
from tests.test_telegram_bot import PROPOSAL


@pytest.fixture
def w(tmp_path, _isolated_analytics):
    world = make_world(tmp_path)
    world.backend.own_crm_token = lambda user: f"crm-{user.actorId}" if user.actorId in world.backend.crm_actors else None
    return world


def _agent(monkeypatch, state: str = "agent") -> FakeAgent:
    fake = FakeAgent()
    fake.handlers["/chat"] = lambda body: {
        "answer": "DVSIB loyihasida vazifa taklif qilindi [#2].", "sources": [], "cited_ids": ["2"],
        "proposals": [] if body.get("shadow") else [PROPOSAL],
        "meta": {"trace_id": "t-g", "purpose": body.get("purpose"), "engine": "v4", "store_applied": body.get("store")}}
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS, group_crm=state)
    return fake


def test_agent_yoli_tasdiqlangan_shakl(w, monkeypatch):
    fake = _agent(monkeypatch)
    request = mockup(w)
    assert w.backend.group_questions == []                       # bugungi v3 yo'li ishlamadi
    [body] = fake.bodies("/chat")
    assert body["purpose"] == "group_crm"
    assert body["question"].startswith("Aha hop") and "[Telegram ish guruhi" not in body["question"]
    assert (body["chat_visibility"], body["audience"], body["store"], body["retention_days"]) == (
        "surface", "group", True, 7)
    assert body["tools"] == ["crm.read", "crm.propose"] and body["tokens"] == {"crm": "crm-1"}
    assert body["chat_id"].startswith("tgcrm-") and body["user_id"] == "venera:1"
    [block] = body["context"]
    assert block["surface_id"] == f"tg:{request['chat']['id']}" and block["kind"] == "tg_group"
    assert block["policy"] == {"external_llm": True, "personal_memory": False, "learn": False, "retention_days": 7}
    ids = [it["id"] for it in block["items"]]
    assert len(ids) == len(set(ids)) and all(isinstance(i, str) for i in ids)
    texts = " ".join(it["text"] for it in block["items"])
    assert "Deepseek 4.1 modelini testlash kere" in texts
    replied = request["reply_to_message"]["message_id"]
    assert body["reply_to_ref"] == f"tg:{request['chat']['id']}#{replied}"
    [note] = block["notes"]
    assert "@islom_kaizen = Islom Amanullayev" in note["text"] and "So'ragan: Islom Amanullayev" in note["text"]
    # X-Barno-Contract - har so'rovda (agent `purpose` ni shunda talab qiladi).
    [call] = [c for c in fake.calls if c["path"] == "/chat"]
    assert call["headers"]["X-Barno-Contract"] == "4.0"
    sent = group_sent(w)
    assert any("taklif qilindi" in m["text"] for m in sent)
    card = [m for m in sent if "Taklif qilingan o'zgarish" in m["text"]][0]
    assert card["reply_to"] == request["message_id"]


def test_agent_xatosida_bugungi_yol(w, monkeypatch):
    fake = _agent(monkeypatch)
    fake.handlers["/chat"] = lambda body: (503, {"error": {"code": "model_unavailable", "message": "m",
                                                           "retryable": True}})
    mockup(w)
    assert len(w.backend.group_questions) == 1                   # zahira: v3 oqimi
    assert any("taklif qilindi" in m["text"] for m in group_sent(w))


def test_token_yoq_bolsa_bugungi_yol(w, monkeypatch):
    fake = _agent(monkeypatch)
    w.backend.own_crm_token = lambda user: None
    mockup(w)
    assert fake.bodies("/chat") == [] and len(w.backend.group_questions) == 1


def test_default_local_bugungi_yol(w):
    routing.reset_for_tests()
    mockup(w)
    assert len(w.backend.group_questions) == 1


def test_shadow_foydalanuvchi_bugungisini_oladi(w, monkeypatch):
    fake = _agent(monkeypatch, state="shadow")
    queue = brain_shadow.reset_for_tests()
    monkeypatch.setattr(ga, "_brain_route", lambda feature: routing.Route(
        feature=feature, configured="shadow", effective="shadow", source="env", sample_rate=1.0))
    mockup(w)
    assert len(w.backend.group_questions) == 1                   # foydalanuvchi - bugungi javob
    assert queue.drain(5)
    [body] = fake.bodies("/chat")
    assert body["shadow"] is True and body["store"] is False     # taklif ham, yozuv ham yo'q


def test_javob_qilingan_xabar_oynadan_tashqarida(w, monkeypatch):
    fake = _agent(monkeypatch)
    old = {"message_id": 777, "date": 1, "chat": {"id": -1, "type": "supergroup"},
           "from": {"id": YUSUF[0], "first_name": YUSUF[1]}, "text": "Telefon +998 90 123 45 67 ga qo'ng'iroq"}
    send(w, gmsg(f"@{BOT} crmga kiritib qo'y", user=ISLOM, reply=old))
    [body] = fake.bodies("/chat")
    [block] = body["context"]
    item = [it for it in block["items"] if it["id"] == "777"][0]
    assert "+998 90 123 45 67" not in item["text"]                # niqoblangan
    assert body["reply_to_ref"].endswith("#777")

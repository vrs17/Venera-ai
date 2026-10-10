"""Choklar (seams): har chaqiruv joyi flag orqali "lokal yoki agent" deb so'raydi.

Asosiy kafolat: `local` (default) - AYNAN bugungi chaqiruv, agentga hech narsa
ketmaydi. `agent` - shartnoma shaklidagi so'rov, xatoda lokal zahira. `shadow` -
foydalanuvchi lokal natijani oladi, agent fonda, `shadow_results` da matn yo'q.
Agent soxta (`tests/agent_fakes.py`) - tarmoqqa chiqilmaydi.
"""

from __future__ import annotations

import json
import time

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.auth import AuthUser
from app.services import analytics
from app.services.analytics.meter import bind
from app.services.brain import BrainChat, brief_crm_ask, routing, shadow
from app.services.brain.features import CRM_STATUS_SCHEMA
from app.services.integrations.ollama import OllamaChat, OllamaError
from meetings_fakes import auto_reply, enable, recorded, run_all
from tests.agent_fakes import FakeAgent, enable_agent
from app.bot.groups import _FAILED
from app.bot.render import esc
from tests.test_bot_groups import GROUP, FakeWriter, gmsg, make_world, replies, send
from tests.test_hold import FakeClassifier, _kadrlar, chat  # noqa: F401 - fikstura

USER = AuthUser(actorId=7, email="rahbar@venera.uz", fullName="Rahbar")


class FakeLocal:
    """`OllamaChat` o'rnida: argumentlarni AYNAN yozib oladi."""

    def __init__(self, text: str = "Lokal javob: login xatosi tuzatildi.") -> None:
        self.text = text
        self.calls: list[tuple[tuple, dict]] = []
        self.configured = True
        self.model = "gemma4:31b"

    def complete(self, system, user, **kwargs):
        self.calls.append(((system, user), kwargs))
        if isinstance(self.text, Exception):
            raise self.text
        return self.text

    def complete_meta(self, system, user, **kwargs):
        self.calls.append(((system, user), kwargs))
        return self.text, {"doneReason": "stop"}


def _shadow_rows(db) -> list[dict]:
    assert shadow.get_queue().drain(5)
    assert analytics.flush()
    return db.rows("SELECT * FROM shadow_results ORDER BY id")


# ================================================================ BrainChat (guruh, brif)


def test_local_aynan_bugungi_chaqiruv(_isolated_analytics):
    local, fake = FakeLocal(), FakeAgent()
    writer = BrainChat(local)
    out = writer.complete("TIZIM", "MATN", num_predict=2000, op="group_summary")
    assert out == local.text
    assert local.calls == [(("TIZIM", "MATN"), {"num_predict": 2000, "op": "group_summary"})]
    assert writer.complete_meta("S", "U", op="brief_extract", format="json") == (local.text, {"doneReason": "stop"})
    assert writer.model == "gemma4:31b" and writer.configured                # atributlar lokalniki
    assert fake.calls == []
    assert analytics.flush() and _isolated_analytics.scalar("SELECT COUNT(*) FROM shadow_results") == 0


def test_agent_shartnoma_shaklida_va_zahira(_isolated_analytics, monkeypatch):
    fake = enable_agent(monkeypatch, FakeAgent(), group_ask="agent")
    local = FakeLocal()
    writer = BrainChat(local)
    with bind(12, "bot"):
        out = writer.complete("TIZIM PROMPTI", "GURUH MATNI", num_predict=1000, temperature=0.2, op="group_ask")
    assert out == "Agent javobi: login xatosi tuzatildi." and local.calls == []
    [call] = fake.calls
    body = call["body"]
    assert call["path"] == "/complete"
    assert body == {"purpose": "group_ask", "instructions": "TIZIM PROMPTI",
                    "input": {"text": "GURUH MATNI", "vars": {"op": "group_ask"}}, "output_format": "text",
                    "language": "uz", "priority": "interactive", "max_output_tokens": 1000, "temperature": 0.2,
                    "deadline_ms": 60000, "user_id": "venera:12", "audience": "group"}
    # Agent yiqilsa - bugungi chaqiruv, zahira hisoblanadi.
    fake.handlers["/complete"] = lambda body: (503, {"error": {"code": "model_unavailable", "message": "band"}})
    with bind(12, "bot"):
        assert writer.complete("S", "U", op="group_ask") == local.text
    assert analytics.flush()
    ops = [r["op"] for r in _isolated_analytics.rows("SELECT op FROM api_calls WHERE service='brain'")]
    assert ops == ["fallback.group_ask"]


def test_brif_tayyorlash_batch_navbatida(monkeypatch):
    fake = enable_agent(monkeypatch, FakeAgent(), brief_extract="agent")
    BrainChat(FakeLocal()).complete("S", "U", num_predict=3000, op="brief_extract_support", format="json")
    BrainChat(FakeLocal()).complete("S", "U", num_predict=400, op="brief_headline")
    first, second = fake.bodies("/complete")
    assert (first["purpose"], first["priority"]) == ("brief_extract", "batch") and "audience" not in first
    assert (second["purpose"], second["priority"]) == ("brief_headline", "interactive")


def test_yonaltirilmagan_op_doim_lokal(monkeypatch):
    """`brief_crm` normalizeri o'ramdan o'tadi, lekin `brief_crm` flag'i uni agentga
    yubormaydi: agent shakli - butun CRM tekshiruvi (`brief_crm_ask`)."""
    fake = enable_agent(monkeypatch, FakeAgent(), brief_crm="agent", group_summary="agent")
    local = FakeLocal()
    assert BrainChat(local).complete("N", "J", op="brief_crm", format="json") == local.text
    assert BrainChat(local).complete("N", "J", op="group") == local.text
    assert fake.calls == []


def test_shadow_foydalanuvchi_lokalni_oladi_matn_saqlanmaydi(_isolated_analytics, monkeypatch):
    fake = enable_agent(monkeypatch, FakeAgent(), group_summary="shadow")
    monkeypatch.setattr(settings, "agent_shadow_sample_rate", 1.0)
    local = FakeLocal("Lokal xulosa: login xatosi tuzatildi, demo juma kuni.")
    with bind(5, "bot", "turn-x"):
        out = BrainChat(local).complete("MAXFIY TIZIM", "MAXFIY GURUH MATNI", op="group_summary")
    assert out == local.text
    [row] = _shadow_rows(_isolated_analytics)
    assert (row["feature"], row["op"], row["status"], row["trace_id"]) == (
        "group_summary", "group_summary", "ok", "trace-1")
    assert row["input_chars"] == len("MAXFIY TIZIM") + len("MAXFIY GURUH MATNI")
    assert 0.0 < row["similarity"] < 1.0 and row["agent_ms"] is not None
    assert "MAXFIY" not in json.dumps(row) and "login" not in json.dumps(row)
    [call] = fake.calls
    assert call["body"]["shadow"] is True and call["headers"]["X-Barno-Channel"] == "worker"
    # Shadow chaqiruvi `api_calls` da alohida op bilan - yuk hisobida aralashmaydi.
    assert [r["op"] for r in _isolated_analytics.rows("SELECT op FROM api_calls WHERE service='assistant'")] == [
        "shadow.group_summary"]


def test_shadow_namunadan_tashqarida_agentga_bormaydi(_isolated_analytics, monkeypatch):
    fake = enable_agent(monkeypatch, FakeAgent(), group_ask="shadow")
    monkeypatch.setattr(settings, "agent_shadow_sample_rate", 0.0)
    BrainChat(FakeLocal()).complete("S", "U", op="group_ask")
    assert shadow.get_queue().drain(5) and fake.calls == []


def test_bot_yozuvchisi_braincchat_ichida_ollama():
    import app.bot as bot_module

    writer = bot_module._writer()
    assert isinstance(writer, BrainChat) and isinstance(writer.local, OllamaChat)


# ================================================================ guruh /summary oxirigacha


def test_guruh_xulosasi_local_va_agent(tmp_path, monkeypatch):
    world = make_world(tmp_path)
    world.groups.writer = BrainChat(world.writer)
    send(world, gmsg("Login sahifasi 500 xato beryapti", ago=3600))
    send(world, gmsg("/summary"))
    [local_reply] = replies(world)
    assert "<b>Muhokama</b>" in local_reply["text"] and len(world.writer.calls) == 1

    fake = FakeAgent()
    fake.handlers["/complete"] = lambda body: {"output": "**Agent bo'limi**\n- Login xatosi", "meta": {}}
    enable_agent(monkeypatch, fake, group_summary="agent")
    send(world, gmsg("/summary"))
    agent_reply = replies(world)[-1]
    assert "<b>Agent bo'limi</b>" in agent_reply["text"]
    assert len(world.writer.calls) == 1                                     # lokal chaqirilmadi
    assert fake.bodies("/complete")[0]["audience"] == "group"


def test_guruh_agent_ham_lokal_ham_yiqilsa_bugungi_xato_xabari(tmp_path, monkeypatch):
    world = make_world(tmp_path)
    world.groups.writer = BrainChat(FakeWriter(OllamaError("Ollama HTTP 500", status=500)))
    fake = FakeAgent()
    fake.handlers["/complete"] = lambda body: (500, {"error": {"code": "internal", "message": "x"}})
    enable_agent(monkeypatch, fake, group_ask="agent")
    send(world, gmsg("Demo tayyor"))
    send(world, gmsg("/askbarno nima bo'ldi?"))
    [reply] = [r for r in replies(world) if r["chat_id"] == GROUP]
    assert reply["text"] == esc(_FAILED)                                     # bugungi xabar
    assert len(world.groups.writer.local.calls) == 1                         # zahira urinildi


# ================================================================ brif CRM


def _items() -> list[dict]:
    return [{"type": "task", "status": "open", "title": "Kredit qoldig'i hisobi", "detail": None,
             "owner": "Yusufxon", "group": -100, "at": time.time(), "severity": "high"}]


def test_brif_crm_local_bugungi_ask(monkeypatch):
    from app.bot.crm_status import CrmChecker

    seen = []

    def local_ask(question, user, timeout):
        seen.append(question)
        return {"answer": json.dumps({"tasks": [{"n": 1, "found": True, "key": "DVSIB-1", "title": "Hisob",
                                                 "status": "Done"}]}),
                "sources": [{"kind": "crm", "tool": "crm.search_issues"}], "error": None}

    fake = FakeAgent()
    checker = CrmChecker(brief_crm_ask(local_ask))
    items = _items()
    report = checker.check(USER, items)
    assert report.found == 1 and items[0]["crm"]["key"] == "DVSIB-1"
    assert len(seen) == 1 and fake.calls == []


def test_brif_crm_agent_faqat_crm_tokeni_va_normalizersiz(monkeypatch):
    import app.api.v1.chat as chat_module
    from app.bot.crm_status import CrmChecker

    monkeypatch.setattr(chat_module, "_live_tokens", lambda user: {"hrm": "HRM-JWT", "crm": "CRM-JWT"})
    fake = enable_agent(monkeypatch, FakeAgent(), brief_crm="agent")
    writer = FakeLocal()

    def local_ask(question, user, timeout):
        raise AssertionError("lokal chaqirilmasligi kerak")

    items = _items()
    report = CrmChecker(brief_crm_ask(local_ask), writer=writer).check(USER, items)
    assert report.found == 1 and items[0]["crm"]["key"] == "DVSIB-131"
    assert items[0]["crm"]["status"] == "in_progress" and writer.calls == []    # gemma normalizer yo'q
    [body] = fake.bodies("/chat")
    assert body["tokens"] == {"crm": "CRM-JWT"}                                  # HRM yuborilmaydi
    assert (body["purpose"], body["store"], body["tools"], body["user_id"]) == (
        "brief_crm", False, ["crm.read"], "venera:7")
    assert body["response_format"]["schema"] == CRM_STATUS_SCHEMA and body["question"].startswith(
        "Rahbariyat brifi uchun CRM tekshiruvi")


def test_brif_crm_agent_tokensiz_auth_missing(monkeypatch):
    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "_live_tokens", lambda user: {"hrm": "HRM-JWT"})
    fake = enable_agent(monkeypatch, FakeAgent(), brief_crm="agent")
    reply = brief_crm_ask(lambda *a: {"answer": "lokal"})("savol", USER, 30.0)
    assert reply["error"] == {"code": "auth_missing"} and fake.calls == []


def test_brif_crm_shadow(_isolated_analytics, monkeypatch):
    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "_live_tokens", lambda user: {"crm": "CRM-JWT"})
    fake = enable_agent(monkeypatch, FakeAgent(), brief_crm="shadow")
    monkeypatch.setattr(settings, "agent_shadow_sample_rate", 1.0)
    local = {"answer": json.dumps({"tasks": [{"n": 1, "found": True}]}), "sources": [{"kind": "crm"}],
             "error": None}
    assert brief_crm_ask(lambda *a: local)("savol", USER, 30.0) is local
    [row] = _shadow_rows(_isolated_analytics)
    assert (row["feature"], row["status"], row["similarity"]) == ("brief_crm", "ok", 1.0)
    assert json.loads(row["metrics"]) == {"agent_crm_read": 1, "agent_found": 1, "local_crm_read": 1,
                                          "local_found": 1}
    assert fake.bodies("/chat")[0]["shadow"] is True


# ================================================================ yig'ilish xulosasi


def _agent_meetings(fake: FakeAgent) -> FakeAgent:
    def complete(body):
        op = body["input"]["vars"]["op"]
        return {"output": auto_reply(op, body["instructions"], body["input"]["text"]),
                "meta": {"trace_id": f"t-{op}", "tokens_in": 10, "tokens_out": 10}}

    fake.handlers["/complete"] = complete
    return fake


def test_xulosa_local_zanjir_ozgarmaydi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(_isolated_meetings)
    [summary] = _isolated_meetings.store.rows("SELECT provider, status FROM summaries")
    assert summary == {"provider": "ollama", "status": "ready"}
    assert "meeting_extract" in _isolated_meetings.llm.ops()


def test_xulosa_agent_bogini_butun_xulosa_agentda(client, auth, monkeypatch, _isolated_meetings):
    fake = enable_agent(monkeypatch, _agent_meetings(FakeAgent()), meeting_summary="agent")
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(_isolated_meetings)
    [summary] = _isolated_meetings.store.rows("SELECT provider, model, status FROM summaries")
    assert summary == {"provider": "agent", "model": "agent", "status": "ready"}
    assert _isolated_meetings.llm.ops() == []                                # lokal model chaqirilmadi
    steps = [b["input"]["vars"]["op"] for b in fake.bodies("/complete")]
    assert "meeting_extract" in steps and {b["purpose"] for b in fake.bodies("/complete")} <= {
        "meeting_classify", "meeting_summary"}
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["summaryStatus"] == "ready" and detail["title"] == "Hisobot yig'ilishi"


def test_xulosa_agent_yiqilsa_bugungi_zanjir_boshidan(client, auth, monkeypatch, _isolated_meetings):
    fake = FakeAgent()
    fake.handlers["/complete"] = lambda body: (503, {"error": {"code": "model_unavailable", "message": "band"}})
    enable_agent(monkeypatch, fake, meeting_summary="agent")
    enable(monkeypatch)
    recorded(client, auth)
    run_all(_isolated_meetings)
    [summary] = _isolated_meetings.store.rows("SELECT provider, status, content_json FROM summaries")
    assert (summary["provider"], summary["status"]) == ("ollama", "ready")
    assert "provider_failed:agent" in json.loads(summary["content_json"])["quality"]["warnings"]


def test_xulosa_shadow_fonda_va_taqqoslanadi(client, auth, monkeypatch, _isolated_meetings, _isolated_analytics):
    fake = enable_agent(monkeypatch, _agent_meetings(FakeAgent()), meeting_summary="shadow")
    monkeypatch.setattr(settings, "agent_shadow_sample_rate", 1.0)
    enable(monkeypatch)
    recorded(client, auth)
    run_all(_isolated_meetings)
    [summary] = _isolated_meetings.store.rows("SELECT provider, status FROM summaries")
    assert summary == {"provider": "ollama", "status": "ready"}             # foydalanuvchi - lokal
    [row] = _shadow_rows(_isolated_analytics)
    assert (row["feature"], row["status"]) == ("meeting_summary", "ok")
    assert row["similarity"] == 1.0                                          # bir xil soxta model
    metrics = json.loads(row["metrics"])
    assert metrics["local_actions"] == metrics["agent_actions"] and metrics["calls"] >= 2
    assert all(b["shadow"] is True for b in fake.bodies("/complete"))
    assert "hisobot" not in json.dumps(row).lower()


# ================================================================ yig'ilish savol-javobi


def _ready(client, auth, monkeypatch, rt):
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(rt)
    return meeting["id"]


def test_savol_agent_bogini(client, auth, monkeypatch, _isolated_meetings):
    mid = _ready(client, auth, monkeypatch, _isolated_meetings)
    fake = enable_agent(monkeypatch, _agent_meetings(FakeAgent()), meeting_ask="agent")
    before = len(_isolated_meetings.llm.calls)
    response = client.post(f"/api/v1/meetings/{mid}/ask", headers=auth, json={"question": "Kim hisobot yuboradi?"})
    assert response.status_code == 200, response.text
    assert [c["segmentId"] for c in response.json()["citations"]] == [1]     # bizning Validator ishladi
    assert len(_isolated_meetings.llm.calls) == before
    [body] = fake.bodies("/complete")
    assert (body["purpose"], body["input"]["vars"]["op"]) == ("meeting_ask", "meeting_ask")
    assert "Kim hisobot yuboradi?" in body["input"]["text"]


def test_savol_shadow(client, auth, monkeypatch, _isolated_meetings, _isolated_analytics):
    mid = _ready(client, auth, monkeypatch, _isolated_meetings)
    enable_agent(monkeypatch, _agent_meetings(FakeAgent()), meeting_ask="shadow")
    monkeypatch.setattr(settings, "agent_shadow_sample_rate", 1.0)
    response = client.post(f"/api/v1/meetings/{mid}/ask", headers=auth, json={"question": "Kim hisobot yuboradi?"})
    assert response.status_code == 200
    [row] = _shadow_rows(_isolated_analytics)
    assert (row["feature"], row["status"], row["similarity"]) == ("meeting_ask", "ok", 1.0)
    assert json.loads(row["metrics"])["citation_overlap"] == 1.0


# ================================================================ ovozli kutish tasnifi


def _sekin():
    time.sleep(0.5)
    yield b'{"type":"token","text":"Javob"}\n'
    yield b'{"type":"done","route":"hrm"}\n'


def test_hold_keyword_modeli_chaqirmaydi(chat, monkeypatch):
    monkeypatch.setattr(settings, "hold_classifier", "keyword")
    monkeypatch.setattr(settings, "hold_first_ms", 150)
    fake = FakeClassifier()
    monkeypatch.setattr(chat, "_hold_classifier", fake)
    points = []
    recorder = SimpleNamespace(point=lambda name, **kw: points.append((name, kw)), record_span=lambda *a, **k: None)
    plan = chat._HoldPlan("TEZDA AYT! kim kech qoldi", "uz", recorder)
    kadrlar = _kadrlar(plan, chat, _sekin)
    holds = [(t, k) for t, k in kadrlar if k["type"] == "hold"]
    assert fake.calls == 0 and ("hold.classify", {"skipped": "keyword"}) in points
    t, hold = holds[0]
    assert hold["source"] == "jadval" and hold["topic"] == "kechikish" and t >= 0.14   # `hold_first_ms` da


def test_hold_default_keyword_llm_qaytarish_kaliti(chat, monkeypatch):
    """Default `keyword` (reja W0.5, D2): ovozli savol `ollama.com` ga chiqmaydi.
    `HOLD_CLASSIFIER=llm` - qaytarish: bugungi gemma yo'li o'zgarmagan."""
    assert settings.hold_classifier == "keyword"
    monkeypatch.setattr(settings, "hold_first_ms", 150)
    fake = FakeClassifier(kechikish=0.05)
    monkeypatch.setattr(chat, "_hold_classifier", fake)
    plan = chat._HoldPlan("TEZDA AYT! kim kech qoldi", "uz")
    holds = [k for _, k in _kadrlar(plan, chat, _sekin) if k["type"] == "hold"]
    assert fake.calls == 0 and holds[0]["source"] == "jadval"
    monkeypatch.setattr(settings, "hold_classifier", "llm")
    plan = chat._HoldPlan("TEZDA AYT! kim kech qoldi", "uz")
    holds = [k for _, k in _kadrlar(plan, chat, _sekin) if k["type"] == "hold"]
    assert fake.calls == 1 and holds[0]["source"] == "ollama"


def test_hold_agent_route_kadridan(chat, monkeypatch):
    enable_agent(monkeypatch, FakeAgent(), hold_classify="agent")
    fake = FakeClassifier()
    monkeypatch.setattr(chat, "_hold_classifier", fake)

    def oqim():
        yield b'{"type":"route","route":"hrm","topic":"tatil","tone":"oddiy","confidence":0.9,"final":true}\n'
        time.sleep(0.5)
        yield b'{"type":"token","text":"Javob"}\n'
        yield b'{"type":"done","route":"hrm"}\n'

    plan = chat._HoldPlan("TEZDA AYT! kim kech qoldi", "uz")
    kadrlar = _kadrlar(plan, chat, oqim)
    holds = [(t, k) for t, k in kadrlar if k["type"] == "hold"]
    assert fake.calls == 0                                                   # gemma chaqirilmadi
    t, hold = holds[0]
    assert (hold["topic"], hold["source"]) == ("tatil", "agent") and t < 0.4
    assert [k["type"] for _, k in kadrlar][0] == "route"                     # kadr klientga ham o'tadi


def test_hold_shadow_route_bilan_taqqoslanadi(chat, monkeypatch, _isolated_analytics):
    enable_agent(monkeypatch, FakeAgent(), hold_classify="shadow")
    monkeypatch.setattr(settings, "hold_classifier", "llm")                # gemma yorlig'i bilan taqqoslash
    monkeypatch.setattr(chat, "_hold_classifier", FakeClassifier(natija=("kechikish", "shoshilinch")))

    def oqim():
        time.sleep(0.1)
        yield b'{"type":"route","route":"hrm","topic":"kechikish","tone":"oddiy","confidence":0.8,"final":true}\n'
        time.sleep(0.3)
        yield b'{"type":"token","text":"Javob"}\n'
        yield b'{"type":"done","route":"hrm"}\n'

    plan = chat._HoldPlan("kim kech qoldi", "uz")
    holds = [k for _, k in _kadrlar(plan, chat, oqim) if k["type"] == "hold"]
    assert holds[0]["source"] == "ollama"                                   # foydalanuvchiga - lokal
    assert analytics.flush()
    [row] = _isolated_analytics.rows("SELECT * FROM shadow_results")
    assert (row["feature"], row["op"], row["similarity"]) == ("hold_classify", "classify", 1.0)
    assert json.loads(row["metrics"]) == {"confidence": 0.8, "local_llm": 1, "tone_equal": 0}


@pytest.mark.parametrize("raw", [b'{"type":"done","route":"hrm"}\n', b'{"type":"route","topic":"yoq"}\n', b"buzuq"])
def test_hold_route_emas_kadrlar_etiborsiz(chat, monkeypatch, raw):
    enable_agent(monkeypatch, FakeAgent(), hold_classify="agent")
    plan = chat._HoldPlan("savol", "uz")
    plan.start()
    plan.saw(raw)
    assert plan.label is None and plan.mode == "agent"


# ================================================================ sharhdan keyin (2026-10-10)


def test_qongiroq_xulosasi_agentga_hech_qachon_bormaydi(client, auth, monkeypatch, _isolated_meetings,
                                                         _isolated_analytics):
    """Telefon qo'ng'irog'i (`source == "call"`): `meeting_summary` `agent` yoki `shadow`
    bo'lsa ham transkript agentga KETMAYDI (rozilik va huquqiy qaror - D8)."""
    for state in ("agent", "shadow"):
        fake = enable_agent(monkeypatch, _agent_meetings(FakeAgent()), meeting_summary=state)
        monkeypatch.setattr(settings, "agent_shadow_sample_rate", 1.0)
        enable(monkeypatch)
        recorded(client, auth, source="call")
        run_all(_isolated_meetings)
        assert shadow.get_queue().drain(5)
        assert fake.bodies("/complete") == [], state
    providers = {r["provider"] for r in _isolated_meetings.store.rows("SELECT provider FROM summaries")}
    assert providers == {"ollama"}
    assert analytics.flush() and _isolated_analytics.scalar("SELECT COUNT(*) FROM shadow_results") == 0


def test_qongiroq_savoli_agent_bogini_va_shadowsiz(client, auth, monkeypatch, _isolated_meetings,
                                                   _isolated_analytics):
    enable(monkeypatch)
    meeting, _ = recorded(client, auth, source="call")
    run_all(_isolated_meetings)
    for state in ("agent", "shadow"):
        fake = enable_agent(monkeypatch, _agent_meetings(FakeAgent()), meeting_ask=state)
        monkeypatch.setattr(settings, "agent_shadow_sample_rate", 1.0)
        response = client.post(f"/api/v1/meetings/{meeting['id']}/ask", headers=auth,
                               json={"question": "Kim hisobot yuboradi?"})
        assert response.status_code == 200, response.text
        assert shadow.get_queue().drain(5)
        assert fake.bodies("/complete") == [], state
    assert analytics.flush() and _isolated_analytics.scalar("SELECT COUNT(*) FROM shadow_results") == 0


def test_yigilish_xulosasi_job_kinds_siz_lokal(client, auth, monkeypatch, _isolated_meetings):
    """`complete` bor, lekin agent `job_kinds` da `meeting_summary` ni e'lon qilmagan (W5
    sig'imi) - xulosa lokal, transkript agentga bormaydi."""
    from tests.agent_fakes import caps_without

    fake = enable_agent(monkeypatch, _agent_meetings(FakeAgent()), caps=caps_without("job_kinds:meeting_summary"),
                        meeting_summary="agent")
    assert routing.route("meeting_summary").reason == "capability_missing:job_kinds:meeting_summary"
    enable(monkeypatch)
    recorded(client, auth)
    run_all(_isolated_meetings)
    [summary] = _isolated_meetings.store.rows("SELECT provider FROM summaries")
    assert summary == {"provider": "ollama"} and fake.calls == []


def test_json_kutilganda_yaroqsiz_agent_javobi_lokalga(_isolated_analytics, monkeypatch):
    fake = enable_agent(monkeypatch, FakeAgent(), brief_extract="agent")
    fake.handlers["/complete"] = lambda body: {"output": "Kechirasiz, bugun hodisa topa olmadim.", "meta": {}}
    local = FakeLocal('{"events": []}')
    assert BrainChat(local).complete("S", "U", op="brief_extract", format="json") == '{"events": []}'
    assert len(local.calls) == 1 and len(fake.bodies("/complete")) == 1
    # O'ralgan yoki oldida gapi bor JSON - yaroqli (bugungi parser'lar ham o'qiydi).
    fake.handlers["/complete"] = lambda body: {"output": "Natija:\n```json\n{\"events\": [1]}\n```", "meta": {}}
    assert "events" in BrainChat(FakeLocal("x")).complete("S", "U", op="brief_extract", format="json")
    # Matnli op (format yo'q) - tekshirilmaydi.
    fake.handlers["/complete"] = lambda body: {"output": "Oddiy matn", "meta": {}}
    monkeypatch.setattr(settings, "group_ask_engine", "agent")
    assert BrainChat(FakeLocal("x")).complete("S", "U", op="group_ask") == "Oddiy matn"
    assert analytics.flush()
    ops = [r["op"] for r in _isolated_analytics.rows("SELECT op FROM api_calls WHERE service='brain'")]
    assert ops == ["fallback.brief_extract"]


def test_brif_tayyorlash_alohida_batch_mijozida(monkeypatch):
    """`brief_extract*` - `batch` mijozi: interaktiv o'rinlar (guruh `/summary`) band bo'lmaydi."""
    interactive, batch = FakeAgent(), FakeAgent()
    monkeypatch.setattr(settings, "agent_v4_enabled", True, raising=False)
    monkeypatch.setattr(settings, "brief_extract_engine", "agent", raising=False)
    from tests.agent_fakes import FULL_CAPS

    routing.reset_for_tests(interactive=interactive.client(), batch=batch.client(max_concurrent=1),
                            caps=FULL_CAPS)
    BrainChat(FakeLocal()).complete("S", "U", op="brief_extract", format="json")
    BrainChat(FakeLocal()).complete("S", "U", op="brief_headline")
    assert [b["input"]["vars"]["op"] for b in batch.bodies("/complete")] == ["brief_extract"]
    assert [b["input"]["vars"]["op"] for b in interactive.bodies("/complete")] == ["brief_headline"]


def test_uzgich_ochiq_bolsa_hammasi_darhol_lokal(monkeypatch):
    fake = enable_agent(monkeypatch, FakeAgent(), group_ask="agent")
    fake.handlers["/complete"] = lambda body: (503, {"error": {"code": "model_unavailable"}})
    for _ in range(3):
        assert BrainChat(FakeLocal()).complete("S", "U", op="group_ask") == FakeLocal().text
    assert routing.route("group_ask").reason == "circuit_open"
    calls = len(fake.calls)
    assert BrainChat(FakeLocal()).complete("S", "U", op="group_ask") == FakeLocal().text
    assert len(fake.calls) == calls                                         # agentga borilmadi


def test_shadow_xato_matni_saqlanmaydi(_isolated_analytics, monkeypatch):
    fake = enable_agent(monkeypatch, FakeAgent(), group_summary="shadow")
    monkeypatch.setattr(settings, "agent_shadow_sample_rate", 1.0)
    fake.handlers["/complete"] = lambda body: (422, {"error": {"code": "invalid_input",
                                                               "message": "Aziz: maosh 5 mln - yaroqsiz"}})
    with bind(5, "bot"):
        BrainChat(FakeLocal()).complete("S", "U", op="group_summary")
    [row] = _shadow_rows(_isolated_analytics)
    assert row["status"] == "error" and row["error"] == "AgentError:invalid_input:422"
    assert "maosh" not in json.dumps(row)

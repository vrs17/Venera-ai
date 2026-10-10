"""Yig'ilish model zanjiri: v3 -> OpenAI -> Ollama (xulosa, savol-javob) va vazifani CRM ga (v3 taklifi).

Hech bir test tarmoqqa chiqmaydi: v3 - `FakeAssistant` (kadrlar), OpenAI - mahalliy HTTP
server (`FakeOpenAI`), Ollama - `FakeLLM`.
"""

from __future__ import annotations

import json
import re
import threading
import time

import pytest

from app.api.v1 import chat as chat_api
from app.core.config import settings
from app.services import analytics
from app.services.integrations.assistant import AssistantError
from app.services.integrations.ollama import OllamaError
from app.services.meetings import crm, llm, prompts, shapes
from app.services.meetings.summarize import (BudgetExceeded, LlmBusy, LlmFailed, LlmRateLimited, LlmUnavailable,
                                             Pipeline, PromptTooLong, parse_json)
from meetings_fakes import (FakeAssistant, FakeLLM, FakeOpenAI, auto_reply, completion, enable, recorded, run_all,
                            v3_auto, v3_frames)
from test_meetings_summary import make_input

TOKEN = "prop-7Qx2"


@pytest.fixture
def chain(monkeypatch):
    def set_chain(value: str, ask: str = "") -> None:
        monkeypatch.setattr(settings, "meetings_llm_chain", value, raising=False)
        monkeypatch.setattr(settings, "meetings_ask_chain", ask, raising=False)
    return set_chain


@pytest.fixture
def v3(_isolated_meetings):
    fake = FakeAssistant()
    _isolated_meetings.assistant = fake
    return fake


@pytest.fixture
def openai_server():
    server = FakeOpenAI()
    yield server
    server.close()


@pytest.fixture
def openai_client(_isolated_meetings, openai_server, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    client = llm.OpenAIChat(openai_server.base_url, lambda: "sk-test-SECRET", "gpt-test", timeout=10)
    _isolated_meetings.openai = client
    _isolated_meetings.ask_openai = client
    return client


def _summary(client, auth, meeting_id: str) -> dict:
    meeting = client.get(f"/api/v1/meetings/{meeting_id}", headers=auth).json()
    return client.get(f"/api/v1/meetings/{meeting_id}/summaries/{meeting['primarySummaryId']}", headers=auth).json()


def _ready(client, auth, monkeypatch, rt, **create) -> dict:
    enable(monkeypatch)
    meeting, _ = recorded(client, auth, **create)
    run_all(rt)
    return rt.store.meeting_any(meeting["id"])


# --- zanjir sozlamasi ---------------------------------------------------------------------


def test_zanjir_nomlari():
    assert llm.parse_chain("v3, OpenAI;ollama") == ["v3", "openai", "ollama"]
    assert llm.parse_chain("v3,v3,gpt5") == ["v3"]                    # takror va noma'lum tashlanadi
    assert llm.parse_chain("") == ["ollama"] and llm.parse_chain("nima") == ["ollama"]


def test_default_zanjir_ollama_ozgarmagan(client, auth, monkeypatch, _isolated_meetings, v3):
    """Sozlanmaguncha: v3 bor bo'lsa ham CHAQIRILMAYDI, xulosa - Ollama, avvalgidek."""
    rt = _isolated_meetings
    row = _ready(client, auth, monkeypatch, rt)
    assert row["summary_status"] == "ready" and v3.calls == []
    assert rt.llm.ops() == ["meeting_extract", "meeting_verify"]
    summary = _summary(client, auth, row["id"])
    assert summary["generatedBy"] == {"provider": "ollama", "model": "gemma4:31b"} and summary["model"] == "gemma4:31b"
    assert not any(w.startswith("provider_failed") for w in summary["content"]["quality"]["warnings"])


def test_run_chain_oxirgisi_yumshoq_va_xato_turlari():
    seen: list[tuple[str, bool]] = []

    class P:
        def __init__(self, name, configured=True):
            self.name, self.configured, self.client = name, configured, None

    def attempt(errors):
        def run(provider, strict):
            seen.append((provider.name, strict))
            exc = errors.get(provider.name)
            if exc:
                raise exc
            return provider.name
        return run

    result, used, failed = llm.run_chain([P("v3"), P("openai", False), P("ollama")],
                                         attempt({"v3": LlmFailed("x")}))
    assert (result, used.name, failed) == ("ollama", "ollama", ["v3"])
    assert seen == [("v3", True), ("ollama", False)]                  # sozlanmagani o'tkazildi
    with pytest.raises(LlmBusy):                                      # xulosada "band" - zanjir to'xtaydi
        llm.run_chain([P("v3"), P("ollama")], attempt({"v3": LlmBusy("navbat to'la")}))
    result, _, failed = llm.run_chain([P("v3"), P("ollama")], attempt({"v3": LlmBusy("x")}),
                                      busy_falls_through=True)
    assert result == "ollama" and failed == ["v3"]
    with pytest.raises(LlmRateLimited):                               # oxirgisining xatosi - ishchiga
        llm.run_chain([P("v3"), P("ollama")], attempt({"v3": LlmFailed("x"), "ollama": LlmRateLimited("429")}))
    seen.clear()
    with pytest.raises(LlmUnavailable):                               # hech biri sozlanmagan - oxirgisi
        llm.run_chain([P("v3", False), P("ollama", False)], attempt({"ollama": LlmUnavailable("yo'q")}))
    assert seen == [("ollama", False)]


# --- v3 xulosa ------------------------------------------------------------------------------------


def test_xulosa_v3_birinchi_fenced_json_tokensiz(client, auth, monkeypatch, chain, _isolated_meetings, v3):
    rt = _isolated_meetings
    chain("v3,openai,ollama")
    # stage / sources / kutilmagan proposal kadrlari ham keladi - e'tiborsiz, faqat matn olinadi.
    v3.reply = lambda op, q: [*v3_auto(op, q)[:2], _proposal(), *v3_auto(op, q)[2:]]
    row = _ready(client, auth, monkeypatch, rt)
    assert row["summary_status"] == "ready"
    assert v3.ops() == ["meeting_extract", "meeting_verify"] and rt.llm.calls == []
    for call in v3.calls:
        # Xulosada v3 HECH NARSAGA kira olmaydi: token yo'q, alohida kimlik, suhbat xotirasi yo'q.
        assert call["tokens"] == {} and call["chat_id"] is None and call["engine"] == "v3"
        assert call["user_id"] == f"venera-meet:{row['actor_id']}" and call["max_chars"] == 20000
        assert call["question"].startswith(llm.SUMMARY_HEAD) and "<<<TRANSCRIPT-" in call["question"]
        assert len(call["question"]) <= 20000
    assert v3.closed == 2                                              # oqim har doim yopiladi (slot qaytadi)
    summary = _summary(client, auth, row["id"])
    assert summary["generatedBy"] == {"provider": "v3", "model": "v3"}
    assert summary["content"]["title"] == "Hisobot yig'ilishi" and summary["content"]["actionItems"]
    stored = rt.store.summary(row["id"], row["primary_summary_id"])
    assert (stored["provider"], stored["model"]) == ("v3", "v3")
    items = client.get(f"/api/v1/meetings/{row['id']}/action-items", headers=auth).json()["items"]
    assert items and items[0]["crm"] is None


@pytest.mark.parametrize("verify", [
    v3_frames("", extra=[{"type": "error", "code": "internal", "text": "xato"}]),
    v3_frames("Tekshirib chiqdim, hammasi to'g'ri."),                 # JSON yo'q
])
def test_v3_tekshiruv_yiqilsa_xulosa_saqlanadi(client, auth, monkeypatch, chain, _isolated_meetings, v3, verify):
    """Tekshiruvchi faqat belgi qo'yadi: uning xatosi tayyor v3 xulosasini tashlatmaydi."""
    rt = _isolated_meetings
    chain("v3,openai,ollama")
    v3.script["meeting_verify"] = [verify]
    row = _ready(client, auth, monkeypatch, rt)
    assert v3.ops() == ["meeting_extract", "meeting_verify"] and rt.llm.calls == []
    summary = _summary(client, auth, row["id"])
    assert summary["generatedBy"]["provider"] == "v3"
    warnings = summary["content"]["quality"]["warnings"]
    assert "verify_failed" in warnings and not any(w.startswith("provider_failed") for w in warnings)


def test_v3_bir_otish_yaroqsiz_butun_xulosa_ollamada_boshidan(client, auth, monkeypatch, chain, _isolated_meetings,
                                                             v3):
    rt = _isolated_meetings
    chain("v3,openai,ollama")
    v3.script["meeting_extract"] = [v3_frames("Kechirasiz."), v3_frames("Yana kechirasiz.")]
    row = _ready(client, auth, monkeypatch, rt)
    assert v3.ops() == ["meeting_extract", "meeting_extract"]          # chaqiruv + bitta tuzatish
    # BITTA xulosa - BITTA model: Ollama v3 ning qismini olmaydi, o'zi boshidan yozadi.
    assert rt.llm.ops() == ["meeting_extract", "meeting_verify"]
    summary = _summary(client, auth, row["id"])
    assert summary["generatedBy"]["provider"] == "ollama"
    assert "provider_failed:v3" in summary["content"]["quality"]["warnings"]


@pytest.mark.parametrize("frames", [
    v3_frames("", extra=[{"type": "error", "code": "auth_missing", "text": "HRM ga kiring"}]),
    v3_frames("Kechirasiz, bu savolga javob bera olmayman."),           # JSON yo'q - tuzatishdan keyin ham
    v3_frames('```json\n{"result": {"title": "Yig\'ilish", "summary": "..."}}\n```'),   # boshqa shakl
])
def test_v3_yaroqsiz_javob_keyingi_model(client, auth, monkeypatch, chain, _isolated_meetings, v3, frames):
    rt = _isolated_meetings
    chain("v3,ollama")
    v3.reply = lambda op, question: frames
    row = _ready(client, auth, monkeypatch, rt)
    assert row["summary_status"] == "ready"
    assert _summary(client, auth, row["id"])["generatedBy"]["provider"] == "ollama"
    assert rt.llm.ops()[0] == "meeting_extract"


def test_v3_map_yolida_yozuvchi_yiqilsa_kesh_ollamaga_otmaydi(client, auth, monkeypatch, chain, _isolated_meetings,
                                                             v3):
    rt = _isolated_meetings
    chain("v3,ollama")
    monkeypatch.setattr(settings, "meetings_single_pass_chars", 200)
    monkeypatch.setattr(settings, "meetings_map_chars", 250)
    # Vaqtinchalik uzilish 3 marta ketma-ket (asl + 2 qayta urinish) - keyin zanjir.
    v3.script["meeting_write"] = [AssistantError("javob oqimi uzildi", status=503, retryable=True)] * 3
    row = _ready(client, auth, monkeypatch, rt, template="general")
    assert v3.ops().count("meeting_write") == 3
    v3_maps = v3.ops().count("meeting_map")
    assert v3_maps >= 2 and rt.llm.ops().count("meeting_map") == v3_maps     # hammasi qaytadan, keshsiz
    templates_cached = {r["template"] for r in rt.store.rows("SELECT template FROM summary_parts")}
    assert templates_cached == {"v3:general", "general"}
    assert _summary(client, auth, row["id"])["generatedBy"]["provider"] == "ollama"


def test_v3_navbat_band_kutadi_pastki_modelga_tushmaydi(client, auth, monkeypatch, chain, _isolated_meetings, v3):
    rt = _isolated_meetings
    chain("v3,ollama")
    v3.reply = lambda op, q: AssistantError("navbat to'la", status=503, retryable=True, reason="queue_full")
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(rt, time.time(), rounds=3)
    row = rt.store.meeting_any(meeting["id"])
    summary = rt.store.summary(row["id"], row["primary_summary_id"])
    assert summary["status"] == "queued" and int(summary["attempts"]) == 0 and summary["next_attempt_at"]
    assert rt.llm.calls == [] and v3.calls


def test_pipeline_prompt_chegarasiga_sigdiradi():
    """v3 chegarasi: bir o'tish sig'masa - map; bo'laklar, yozuvchi va tekshiruv promptlari
    chegaradan oshmaydi; natija baribir to'liq."""
    fake = FakeLLM()
    limit = 21000
    inp = make_input(repeat=12)                                        # 84 qator, ~6 ming belgi
    out = Pipeline(fake, single_pass_chars=30000, map_chars=20000, max_prompt_chars=limit, strict=True).run(inp)
    assert out.status == "ready" and out.content["actionItems"]
    assert fake.ops()[0] == "meeting_map" and fake.ops().count("meeting_map") >= 2
    assert "meeting_write" in fake.ops() and "meeting_verify" in fake.ops()
    assert all(len(c["system"]) + len(c["user"]) <= limit for c in fake.calls)
    # Chegarasiz (Ollama) - o'sha matn bitta chaqiruvda, avvalgidek.
    plain = FakeLLM()
    Pipeline(plain, single_pass_chars=30000, map_chars=20000).run(inp)
    assert plain.ops()[0] == "meeting_extract"


def test_pipeline_juda_kichik_chegara_provayder_yaramaydi():
    with pytest.raises(PromptTooLong):
        Pipeline(FakeLLM(), max_prompt_chars=15000, strict=True).run(make_input(repeat=12))


def test_v3chat_sarlavha_va_chegara(v3):
    chat = llm.V3Chat(v3, user_id="venera-meet:1", tokens={}, max_chars=500)
    with pytest.raises(PromptTooLong):
        chat.complete_meta("s" * 300, "u" * 300, op="meeting_extract")
    assert v3.calls == []                                             # chegaradan oshgan savol yuborilmaydi
    v3.reply = lambda op, q: v3_frames('{"template": "general", "confidence": 0.9}')
    text, meta = llm.V3Chat(v3, user_id="u", max_chars=20000).complete_meta("SYS", "USER", op="meeting_classify")
    assert json.loads(text)["template"] == "general" and meta["engine"] == "v3" and meta["doneReason"] is None
    assert v3.calls[-1]["question"] == f"{llm.SUMMARY_HEAD}\n\nINSTRUCTIONS:\nSYS\n\nINPUT:\nUSER"
    # Quvur byudjeti AYNAN: shu uzunlikdagi prompt sig'adi, bitta belgi ortig'i - yo'q.
    exact = llm.V3Chat(v3, user_id="u", max_chars=20000)
    room = exact.max_prompt_chars
    assert len(exact.question("s" * (room - 10), "u" * 10)) == 20000
    for exc, kind in ((AssistantError("x", status=501), LlmUnavailable),
                      (AssistantError("x", status=503, reason="queue_full"), LlmBusy),
                      (AssistantError("x", status=429), LlmRateLimited),
                      # Xizmatning o'z 429 i `_mapped_errors` da 502 ga aylanadi - xabardan taniladi.
                      (AssistantError("Assistant 429: slow down", status=502, reason="upstream_http"),
                       LlmRateLimited),
                      (AssistantError("x", status=504, reason="upstream_timeout"), LlmFailed)):
        v3.script["meeting_x"] = [exc]
        with pytest.raises(kind):
            llm.V3Chat(v3, user_id="u", max_chars=20000).complete_meta("s", "u", op="meeting_x")


# --- OpenAI ---------------------------------------------------------------------------------------


def test_openai_strict_json_schema_va_hisob(client, auth, monkeypatch, chain, _isolated_meetings, openai_server,
                                            openai_client, _isolated_analytics, caplog):
    rt = _isolated_meetings
    chain("v3,openai,ollama")                                          # v3 klienti yo'q - o'tkaziladi
    row = _ready(client, auth, monkeypatch, rt)
    assert row["summary_status"] == "ready" and rt.llm.calls == []
    assert openai_server.ops() == ["meeting_extract", "meeting_verify"]
    first = openai_server.requests[0]
    assert first["path"] == "/v1/chat/completions" and first["auth"] == "Bearer sk-test-SECRET"
    body = first["body"]
    assert body["model"] == "gpt-test" and "temperature" not in body and "max_completion_tokens" not in body
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema == shapes.extract() and schema["additionalProperties"] is False
    assert list(schema["properties"])[:2] == ["coverage", "actionItems"] and schema["required"][-1] == "overview"
    assert openai_server.requests[1]["body"]["response_format"]["json_schema"]["schema"] == shapes.verify()
    summary = _summary(client, auth, row["id"])
    assert summary["generatedBy"] == {"provider": "openai", "model": "gpt-test"}
    assert analytics.flush()
    calls = _isolated_analytics.rows("SELECT service, op, status, units, actor_id, channel FROM api_calls "
                                     "WHERE service='openai'")
    assert [c["op"] for c in calls] == ["meeting_extract", "meeting_verify"]
    assert calls[0]["status"] == "ok" and json.loads(calls[0]["units"])["tokens_out"] == 340
    assert calls[0]["actor_id"] == row["actor_id"] and calls[0]["channel"] == "mobile"
    assert "sk-test-SECRET" not in caplog.text


@pytest.mark.parametrize("status", [429, 500])
def test_openai_xatosi_keyingi_modelga(client, auth, monkeypatch, chain, _isolated_meetings, openai_server,
                                       openai_client, status, caplog):
    rt = _isolated_meetings
    chain("openai,ollama")
    openai_server.responses = [(status, {"error": {"message": "sk-test-SECRET rejected"}})]
    row = _ready(client, auth, monkeypatch, rt)
    summary = _summary(client, auth, row["id"])
    assert summary["generatedBy"]["provider"] == "ollama"
    assert "provider_failed:openai" in summary["content"]["quality"]["warnings"]
    assert rt.llm.ops() == ["meeting_extract", "meeting_verify"]
    assert "sk-test-SECRET" not in caplog.text


def test_openai_sxema_rad_etilsa_json_rejimi(openai_server, openai_client):
    openai_server.responses = [(400, {"error": {"message": "Invalid schema for response_format"}}),
                               (200, completion('{"template": "standup", "confidence": 0.8}'))]
    text, meta = openai_client.complete_meta("Return JSON", "matn", op="meeting_classify", format="json")
    assert json.loads(text)["template"] == "standup" and meta["tokensOut"] == 340 and meta["tokensIn"] is None
    kinds = [r["body"]["response_format"]["type"] for r in openai_server.requests]
    assert kinds == ["json_schema", "json_object"]


def test_openai_kesilgan_javob_va_rad(openai_server, openai_client):
    openai_server.responses = [(200, completion('{"a": 1', finish="length"))]
    _, meta = openai_client.complete_meta("s", "u", op="meeting_map")
    assert meta["doneReason"] == "length"
    refusal = completion("")
    refusal["choices"][0]["message"]["refusal"] = "I can't help"
    openai_server.responses = [(200, refusal)]
    with pytest.raises(LlmFailed):
        openai_client.complete_meta("s", "u", op="meeting_map")
    openai_server.responses = [(401, {"error": {}})]
    with pytest.raises(LlmUnavailable):
        openai_client.complete_meta("s", "u", op="meeting_map")


def test_openai_kalit_yoki_model_bolmasa_ochiq(openai_server):
    assert not llm.OpenAIChat(openai_server.base_url, lambda: "", "gpt-test").configured
    assert not llm.OpenAIChat(openai_server.base_url, lambda: "k", "").configured     # default model YO'Q
    assert settings.meetings_openai_model == "" and settings.meetings_llm_chain == "ollama"
    with pytest.raises(LlmUnavailable):
        llm.OpenAIChat(openai_server.base_url, lambda: "", "gpt-test").complete_meta("s", "u")
    assert openai_server.requests == []


def test_sxema_prompt_shakli_bilan_bir_xil():
    """`shapes.py` - `prompts` dagi JSON shakllarining aynan nusxasi (nomlar va tartib)."""
    def top(shape: str) -> list[str]:
        return re.findall(r'^  "(\w+)":', shape, flags=re.MULTILINE)

    def every(node) -> set[str]:
        out: set[str] = set()
        if isinstance(node, dict):
            for key, value in (node.get("properties") or {}).items():
                out.add(key)
                out |= every(value)
            for key in ("items", "anyOf"):
                child = node.get(key)
                for part in child if isinstance(child, list) else [child]:
                    out |= every(part)
        return out

    assert top(prompts.EXTRACT_SHAPE) == list(shapes.extract()["properties"])
    assert top(prompts.MAP_SHAPE) == list(shapes.map_part()["properties"])
    assert top(prompts.WRITER_SHAPE) == list(shapes.writer()["properties"])
    assert set(re.findall(r'"(\w+)":', prompts.EXTRACT_SHAPE)) == every(shapes.extract())
    assert set(re.findall(r'"(\w+)":', prompts.MAP_SHAPE)) == every(shapes.map_part())
    assert "followUpMessage" in shapes.for_op("meeting_extract", prompts.extract_system("follow_up"))["properties"]
    assert "followUpMessage" not in shapes.for_op("meeting_extract", prompts.extract_system("general"))["properties"]
    assert shapes.for_op("meeting_ask") == shapes.ask() and shapes.for_op("group") is None

    def strict_ok(node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False and node["required"] == list(node["properties"])
            for value in node.values():
                strict_ok(value)
        elif isinstance(node, list):
            for value in node:
                strict_ok(value)

    for build in (shapes.extract, shapes.map_part, shapes.writer, shapes.verify, shapes.classify, shapes.ask):
        strict_ok(build())


# --- savol-javob (Ask) -----------------------------------------------------------------------------


def test_savol_v3_orqali_odam_tokenlari_bilan(client, auth, monkeypatch, chain, _isolated_meetings):
    rt = _isolated_meetings
    row = _ready(client, auth, monkeypatch, rt)                       # xulosa - Ollama (default)
    chain("v3,ollama")
    live = FakeAssistant()
    rt.live_assistant = live
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {"crm": "crm-jwt", "hrm": "hrm-jwt"})
    rt.llm.calls.clear()
    live.reply = lambda op, q: v3_frames('```json\n{"answer": "[S2] hisobotni **ertaga** yuboradi.", '
                                         '"citations": [2, 999], "followUps": ["Kim?", "Qachon?", "Nima?"]}\n```')
    response = client.post(f"/api/v1/meetings/{row['id']}/ask", headers=auth, json={"question": "Kim yuboradi?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"id", "question", "answer", "citations", "followUps", "createdAt"}
    assert body["answer"] == "[S2] hisobotni **ertaga** yuboradi." and [c["segmentId"] for c in body["citations"]] == [2]
    call = live.calls[0]
    # 2026-10-10 (F0): faqat CRM tokeni - yig'ilish savoliga HRM kerak emas.
    assert call["user_id"] == f"venera:{row['actor_id']}" and call["tokens"] == {"crm": "crm-jwt"}
    assert call["engine"] == "v3" and call["chat_id"] is None and call["op"] == "meeting_ask"
    assert call["question"].startswith(llm.ASK_HEAD) and "Kim yuboradi?" in call["question"]
    assert "HRM" not in llm.ASK_HEAD
    assert rt.llm.calls == []


def test_savol_platformalari_sozlamadan_qaytariladi(client, auth, monkeypatch, chain, _isolated_meetings):
    """`MEETINGS_ASK_PLATFORMS=crm,hrm` - deploysiz qaytarish: HRM tokeni yana ketadi."""
    from app.core.config import settings

    rt = _isolated_meetings
    row = _ready(client, auth, monkeypatch, rt)
    chain("v3,ollama")
    live = FakeAssistant()
    rt.live_assistant = live
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {"crm": "crm-jwt", "hrm": "hrm-jwt", "dwh": "d"})
    monkeypatch.setattr(settings, "meetings_ask_platforms", " CRM , hrm ", raising=False)
    live.reply = lambda op, q: v3_frames('{"answer": "[S2] ertaga.", "citations": [2], "followUps": []}')
    response = client.post(f"/api/v1/meetings/{row['id']}/ask", headers=auth, json={"question": "Kim?"})
    assert response.status_code == 200, response.text
    assert live.calls[0]["tokens"] == {"crm": "crm-jwt", "hrm": "hrm-jwt"}


def test_savol_v3_yiqilsa_ollama_v3_matni_ham_javob(client, auth, monkeypatch, chain, _isolated_meetings):
    rt = _isolated_meetings
    row = _ready(client, auth, monkeypatch, rt)
    chain("ollama", ask="v3,ollama")
    live = FakeAssistant()
    rt.live_assistant = live
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {})
    live.script["meeting_ask"] = [v3_frames("", extra=[{"type": "error", "code": "auth_missing"}])]
    first = client.post(f"/api/v1/meetings/{row['id']}/ask", headers=auth, json={"question": "Kim?"}).json()
    assert first["answer"] == "[S1] hisobotni ertaga yuboradi." and "meeting_ask" in rt.llm.ops()
    # v3 JSON o'rniga oddiy matn yozsa - o'sha matn javob (manbasiz), Ollama chaqirilmaydi.
    rt.llm.calls.clear()
    live.script["meeting_ask"] = [v3_frames("Hisobotni **Aziz** yuboradi.")]
    second = client.post(f"/api/v1/meetings/{row['id']}/ask", headers=auth, json={"question": "Kim?"}).json()
    assert second["answer"] == "Hisobotni **Aziz** yuboradi." and second["citations"] == [] and rt.llm.calls == []
    # Hammasi yiqilsa - avvalgidek 503.
    live.script["meeting_ask"] = [AssistantError("x", status=502)]
    rt.llm.script["meeting_ask"] = [LlmFailed("x")]
    failed = client.post(f"/api/v1/meetings/{row['id']}/ask", headers=auth, json={"question": "Kim?"})
    assert failed.status_code == 503 and failed.json()["code"] == "llm_unavailable"


# --- vazifa -> CRM ------------------------------------------------------------------------------


def _proposal(token: str = TOKEN, minutes: int = 15) -> dict:
    expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + minutes * 60))
    return {"type": "proposal", "proposal": {
        "token": token, "connector": "crm", "operation": "create_issue", "summary": "CRM da vazifa yaratish",
        "target": {"project": "DVSIB"}, "changes": [{"field": "title", "to": "Vazifa 1ni bajarish"}],
        "warnings": ["Mas'ul aniqlanmadi"], "expires_at": expires, "internal_note": "o'tmasin"}}


def _own_crm(monkeypatch, tokens: dict | None) -> None:
    """Odamning O'Z ulanishlari (`connectors.hub`): `None` - CRM ulanmagan."""
    monkeypatch.setattr(chat_api, "has_own_crm", lambda user: tokens is not None and "crm" in tokens)
    monkeypatch.setattr(chat_api._connectors.hub, "tokens", lambda actor: dict(tokens or {}))


@pytest.fixture
def crm_ready(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    row = _ready(client, auth, monkeypatch, rt)
    live = FakeAssistant()
    rt.live_assistant = live
    # O'z ulanishi: CRM va HRM - CRM so'roviga FAQAT CRM tokeni ketadi.
    _own_crm(monkeypatch, {"crm": "crm-jwt", "hrm": "hrm-jwt"})
    # Umumiy (CrmAuth / .env) tokenlar - CRM so'roviga ISHLATILMAYDI.
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {"crm": "shared-crm", "hrm": "shared-hrm"})
    items = client.get(f"/api/v1/meetings/{row['id']}/action-items", headers=auth).json()["items"]
    return row, items[0], live


def test_crm_taklif_tasdiqlash_bilan(client, auth, monkeypatch, crm_ready, _isolated_meetings):
    row, item, live = crm_ready
    live.script["meeting_crm"] = [v3_frames("Taklif tayyor.", extra=[_proposal()])]
    url = f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm"
    response = client.post(url, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "proposed" and body["reason"] is None
    assert set(body["proposal"]) == set(crm.PROPOSAL_KEYS) and body["proposal"]["token"] == TOKEN
    assert body["item"]["crm"]["token"] == TOKEN and body["item"]["crm"]["status"] == "pending"
    call = live.calls[0]
    # O'z CRM tokeni, HRM yo'q, umumiy hisob yo'q.
    assert call["user_id"] == f"venera:{row['actor_id']}" and call["tokens"] == {"crm": "crm-jwt"}
    assert call["engine"] == "v3" and call["op"] == "meeting_crm" and call["chat_id"] is None
    question = call["question"]
    assert "FAQAT BITTA taklif" in question and "HRM ga murojaat qilmang" in question
    assert f"Vazifa nomi (aynan shunday - tarjima qilmang, qisqartirmang): {item['task']}" in question
    assert "Mas'ul" in question and "So'ragan (topshiriq beruvchi):" in question
    assert "Muddat: aytilmagan - muddat qo'ymang" in question and "Hisobot yig'ilishi" in question
    assert "(Toshkent)" in question and "faqat BITTA loyiha aniq mos kelsa" in question
    # Ikkinchi bosish - agentga qayta borilmaydi, o'sha taklif.
    again = client.post(url, headers=auth, json={}).json()
    assert again["status"] == "proposed" and again["proposal"]["token"] == TOKEN and len(live.calls) == 1
    listed = client.get(f"/api/v1/meetings/{row['id']}/action-items", headers=auth).json()["items"]
    assert next(i for i in listed if i["id"] == item["id"])["crm"]["proposal"]["operation"] == "create_issue"

    class Upstream:
        def confirm_action(self, token, *, user_id, tokens=None):
            assert (token, user_id) == (TOKEN, f"venera:{row['actor_id']}")
            return {"token": token, "status": "executed", "ok": True, "summary": "Yaratildi",
                    "result": {"key": "DVSIB-231"}}

    monkeypatch.setattr(chat_api, "_assistant", Upstream())
    confirmed = client.post(f"/api/v1/actions/{TOKEN}/confirm", headers=auth)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "executed"
    listed = client.get(f"/api/v1/meetings/{row['id']}/action-items", headers=auth).json()["items"]
    crm_state = next(i for i in listed if i["id"] == item["id"])["crm"]
    assert crm_state["status"] == "executed" and crm_state["result"] == {"key": "DVSIB-231"}
    mine = client.get("/api/v1/meetings/action-items?status=all", headers=auth).json()["items"]
    assert next(i for i in mine if i["id"] == item["id"])["crm"]["status"] == "executed"
    # Yaratilgandan keyin yana bosish (force bilan ham) - agentga BORILMAYDI, natija saqlanadi:
    # aks holda ikkinchi tasdiq CRM da ikkinchi vazifa yaratardi.
    for payload in ({}, {"force": True}):
        again = client.post(url, headers=auth, json=payload).json()
        assert again["status"] == "failed" and again["reason"] == "already_created" and again["proposal"] is None
        assert again["item"]["crm"]["status"] == "executed" and again["item"]["crm"]["result"] == {"key": "DVSIB-231"}
    assert len(live.calls) == 1

    class Expired:
        def confirm_action(self, token, *, user_id, tokens=None):
            raise AssistantError("Assistant 410: expired", status=410)

    # Bajarilgan taklifni qayta tasdiqlash 410 oladi - vazifa `expired` ga TUSHMAYDI.
    monkeypatch.setattr(chat_api, "_assistant", Expired())
    assert client.post(f"/api/v1/actions/{TOKEN}/confirm", headers=auth).status_code == 410
    listed = client.get(f"/api/v1/meetings/{row['id']}/action-items", headers=auth).json()["items"]
    assert next(i for i in listed if i["id"] == item["id"])["crm"]["status"] == "executed"


def test_crm_javob_matn_va_loyiha_ishorasi(client, auth, crm_ready):
    row, item, live = crm_ready
    live.script["meeting_crm"] = [v3_frames("Qaysi loyihaga qo'shay: DVSIB yoki HRM?")]
    body = client.post(f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm", headers=auth,
                       json={"project": "Venera"}).json()
    assert body["status"] == "answered" and body["text"].startswith("Qaysi loyihaga") and body["proposal"] is None
    assert body["item"]["crm"] is None and "Loyiha: Venera" in live.calls[0]["question"]


def test_crm_ulanmagan_va_xatolar(client, auth, monkeypatch, crm_ready):
    row, item, live = crm_ready
    url = f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm"
    # O'z CRM ulanishi yo'q - umumiy CrmAuth hisobi bo'lsa ham agentga borilmaydi.
    _own_crm(monkeypatch, {"hrm": "hrm-jwt"})
    body = client.post(url, headers=auth).json()
    assert body == {**body, "status": "failed", "reason": "crm_not_connected"} and live.calls == []
    # `MEETINGS_CRM_OWN_TOKENS=false` - umumiy CRM hisobi, HRM baribir yuborilmaydi.
    monkeypatch.setattr(settings, "meetings_crm_own_tokens", False)
    live.script["meeting_crm"] = [v3_frames("Qaysi loyiha?")]
    assert client.post(url, headers=auth).json()["status"] == "answered"
    assert live.calls[-1]["tokens"] == {"crm": "shared-crm"}
    monkeypatch.setattr(settings, "meetings_crm_own_tokens", True)
    live.calls.clear()
    _own_crm(monkeypatch, {"crm": "crm-jwt"})
    live.script["meeting_crm"] = [v3_frames("", extra=[{"type": "error", "code": "auth_expired"}]),
                                  AssistantError("navbat to'la", status=503, reason="queue_full"),
                                  v3_frames("", extra=[{"type": "error", "code": "internal"}]),
                                  v3_frames("")]
    reasons = [client.post(url, headers=auth).json()["reason"] for _ in range(4)]
    assert reasons == ["crm_not_connected", "assistant_busy", "assistant_error", "empty"]
    live.configured = False
    assert client.post(url, headers=auth).json()["reason"] == "assistant_not_configured"


def test_crm_izolyatsiya_bayroq_va_chegara(client, auth, user_auth, monkeypatch, crm_ready):
    row, item, live = crm_ready
    url = f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm"
    enable(monkeypatch, logins="demo@venera.uz")
    other = client.post(url, headers=user_auth)
    assert other.status_code == 404 and other.json()["code"] == "not_found"
    missing = client.post(f"/api/v1/meetings/{row['id']}/action-items/{'0' * 32}/crm", headers=auth)
    assert missing.status_code == 404 and missing.json()["code"] == "item_not_found"
    monkeypatch.setattr(settings, "meetings_crm_per_hour", 1)
    live.reply = lambda op, q: v3_frames("Aniqlik kerak.")
    assert client.post(url, headers=auth).status_code == 200
    limited = client.post(url, headers=auth)
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    monkeypatch.setattr(settings, "meetings_enabled", False)
    assert client.post(url, headers=auth).status_code == 404
    assert len(live.calls) == 1


def test_crm_taklif_muddati_otsa_expired_va_force(client, auth, crm_ready, _isolated_meetings):
    row, item, live = crm_ready
    live.script["meeting_crm"] = [v3_frames("", extra=[_proposal("old-1", minutes=-1)]),
                                  v3_frames("", extra=[_proposal("new-2")])]
    url = f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm"
    late = client.post(url, headers=auth).json()                      # kelgandayoq muddati o'tgan
    assert (late["status"], late["reason"], late["proposal"]) == ("failed", "expired", None)
    assert late["item"]["crm"] is None
    fresh = client.post(url, headers=auth).json()
    assert fresh["proposal"]["token"] == "new-2" and len(live.calls) == 2
    live.script["meeting_crm"] = [v3_frames("", extra=[_proposal("new-3")])]
    forced = client.post(url, headers=auth, json={"force": True}).json()
    assert forced["proposal"]["token"] == "new-3" and len(live.calls) == 3
    # Almashtirilgan (hali kutilayotgan) taklif yuqorida ham bekor qilindi - eski karta tasdiqlanmasin.
    assert live.cancelled == [{"token": "new-2", "user_id": f"venera:{row['actor_id']}",
                               "tokens": {"crm": "crm-jwt"}}]


def test_tasdiqlash_yigilish_omborini_yaratmaydi(client, auth, monkeypatch, _isolated_meetings):
    """Chat tasdiqlashi o'zgarmagan: yig'ilish bo'limi yoqilmagan bo'lsa ombor yaratilmaydi."""
    class Upstream:
        def confirm_action(self, token, *, user_id, tokens=None):
            return {"token": token, "status": "executed", "ok": True}

    monkeypatch.setattr(chat_api, "_assistant", Upstream())
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {})
    response = client.post(f"/api/v1/actions/{TOKEN}/confirm", headers=auth)
    assert response.status_code == 200 and response.json()["status"] == "executed"
    assert not _isolated_meetings.store.exists


def test_assistant_hisob_nomi_default_stream(monkeypatch):
    """`AssistantClient.stream(op=...)` qo'shimcha: chat chaqiruvi avvalgidek `assistant / stream`."""
    from app.services.integrations import assistant as assistant_mod

    seen: list[tuple[str, str]] = []
    real_begin = assistant_mod.begin

    def spy(service, op, **kw):
        seen.append((service, op))
        return real_begin(service, op, **kw)

    class Response:
        headers = {"X-Request-Id": "r"}
        status = 200

        def __init__(self):
            self.lines = [b'{"type": "token", "text": "ok"}\n', b'{"type": "done"}\n', b""]

        def readline(self, limit=-1):
            return self.lines.pop(0)

        def close(self):
            return None

    monkeypatch.setattr(assistant_mod, "begin", spy)
    client = assistant_mod.AssistantClient("http://a.test", "id", "secret")
    monkeypatch.setattr(client, "_open", lambda *a, **kw: Response())
    for op in (None, "meeting_extract"):
        stream = client.stream("savol", user_id="u", engine="v3", **({"op": op} if op else {}))
        assert list(stream.frames)
    assert seen == [("assistant", "stream"), ("assistant", "meeting_extract")]


def test_sogliq_zanjir_sirsiz(client, auth, monkeypatch, chain, _isolated_meetings, openai_client):
    enable(monkeypatch)
    chain("v3,openai,ollama")
    body = client.get("/api/health/detail", headers=auth).json()["meetings"]
    assert body["llmChain"] == [{"provider": "v3", "configured": False, "model": None},
                                {"provider": "openai", "configured": True, "model": "gpt-test"},
                                {"provider": "ollama", "configured": True, "model": "gemma4:31b"}]
    assert "sk-test" not in json.dumps(body)


def test_v3_auto_soxtasi_ishlaydi():
    """Soxtaning o'zi: markdown ichidagi JSON `parse_json` bilan o'qiladi."""
    from app.services.meetings.summarize import parse_json

    text = "".join(f["text"] for f in v3_auto("meeting_classify", "") if f["type"] == "token")
    assert parse_json(text)[0] == {"template": "general", "confidence": 0.9}


def test_yangi_asosiy_xulosa_crm_vazifasini_saqlaydi(client, auth, crm_ready, _isolated_meetings):
    row, item, live = crm_ready
    live.script["meeting_crm"] = [v3_frames("", extra=[_proposal()])]
    assert client.post(f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm",
                       headers=auth).json()["status"] == "proposed"
    created = client.post(f"/api/v1/meetings/{row['id']}/summaries", headers=auth,
                          json={"template": "minutes", "force": True})
    assert created.status_code == 202
    run_all(_isolated_meetings)
    items = client.get(f"/api/v1/meetings/{row['id']}/action-items", headers=auth).json()["items"]
    kept = [i for i in items if i["id"] == item["id"]]
    assert kept and kept[0]["crm"]["token"] == TOKEN
    # O'sha vazifa yangi xulosadan qayta "ochiq" bo'lib qo'shilmaydi.
    assert [i["task"] for i in items].count(item["task"]) == 1


def test_crm_vazifa_tahrirlansa_eski_taklif_qaytmaydi(client, auth, crm_ready):
    row, item, live = crm_ready
    live.script["meeting_crm"] = [v3_frames("", extra=[_proposal("first")]), v3_frames("", extra=[_proposal("second")])]
    url = f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm"
    assert client.post(url, headers=auth).json()["proposal"]["token"] == "first"
    assert client.post(url, headers=auth).json()["proposal"]["token"] == "first" and len(live.calls) == 1
    client.patch(f"/api/v1/meetings/{row['id']}/action-items/{item['id']}", headers=auth,
                 json={"task": "Mijozga yangilangan taklifni yuborish"})
    again = client.post(url, headers=auth).json()
    assert again["proposal"]["token"] == "second" and "Mijozga yangilangan taklifni yuborish" in live.calls[-1]["question"]


# --- sharh tuzatishlari (2026-10-09) ---------------------------------------------------------------


def _v3_room(limit: int = 20000) -> int:
    return llm.V3Chat(None, user_id="u", max_chars=limit).max_prompt_chars


def test_v3_bolak_hajmi_va_belgilar():
    """20000 belgilik v3 savoli: map bo'lagiga ~2.9K belgi transkript (`general`). Belgilar faqat
    O'Z bo'lagidan joy oladi: ko'p belgili yig'ilishda ham joy kichraymaydi va v3 yaraydi."""
    room = _v3_room()
    plain = make_input(repeat=14)
    size = Pipeline(FakeLLM(), max_prompt_chars=room, strict=True)._map_size(plain, "general", [])
    assert 2500 <= size <= 3500
    marks = [{"t": 9.0 * 7 * i, "note": "Muhim lahza, albatta qarang " * 8} for i in range(1, 7)]
    marked = make_input(repeat=14, marks=marks)
    fake = FakeLLM()
    pipeline = Pipeline(fake, max_prompt_chars=room, strict=True)
    assert pipeline._map_size(marked, "general", pipeline._marks(marked)) == size
    out = pipeline.run(marked)
    assert out.status == "ready" and fake.ops().count("meeting_map") >= 3
    assert all(len(c["system"]) + len(c["user"]) <= room for c in fake.calls)


def test_v3_byudjet_oshsa_oldindan_keyingi_model():
    room = _v3_room()
    fake = FakeLLM()
    with pytest.raises(BudgetExceeded):
        Pipeline(fake, max_prompt_chars=room, strict=True, call_budget=4).run(make_input(repeat=34))
    assert fake.calls == []                                           # birorta map chaqiruvi QILINMADI
    # Oxirgi provayder (yumshoq) - byudjet yo'q, avvalgidek.
    assert Pipeline(FakeLLM(), max_prompt_chars=room, call_budget=4).run(make_input(repeat=34)).status == "ready"
    ticks = iter([0.0] + [1000.0] * 100)                             # vaqt byudjeti - soxta soat
    slow = FakeLLM()
    with pytest.raises(BudgetExceeded):
        Pipeline(slow, max_prompt_chars=room, strict=True, time_budget=600,
                 clock=lambda: next(ticks)).run(make_input(repeat=34))
    assert slow.calls == []


def test_v3_json_yozmasa_bolak_bolinmaydi():
    fake = FakeLLM()
    fake.script["meeting_map"] = ["Kechirasiz, JSON yozolmayman."] * 10
    with pytest.raises(LlmFailed):
        Pipeline(fake, max_prompt_chars=_v3_room(), strict=True).run(make_input(repeat=14))
    assert fake.ops() == ["meeting_map", "meeting_map"]               # chaqiruv + tuzatish, bo'linmadi


def test_v3_shakl_orami_va_tashlangan_bosh_royxat():
    """Agent butun JSON ni o'rab yuboradi va bo'sh ro'yxatlarni tashlab ketadi - qabul qilinadi."""
    fake = FakeLLM()

    def reply(op, system, user):
        data = json.loads(auto_reply(op, system, user))
        if op == "meeting_extract":
            data.pop("decisions")
            data.pop("openQuestions")
            return json.dumps({"summary": data}, ensure_ascii=False)
        return json.dumps(data, ensure_ascii=False)

    fake.reply = reply
    out = Pipeline(fake, strict=True).run(make_input())
    assert out.status == "ready" and fake.ops() == ["meeting_extract", "meeting_verify"]
    assert out.content["actionItems"] and out.content["title"] == "Hisobot yig'ilishi"


def test_v3_til_tekshiruvi_faqat_zanjirda():
    english = ("The team discussed the report and agreed that the budget will be approved with the client "
               "for the next quarter.")

    def reply(op, system, user):
        data = json.loads(auto_reply(op, system, user))
        if op == "meeting_extract":
            data["overview"] = english
            data["title"] = "The weekly report meeting of the team"
        return json.dumps(data, ensure_ascii=False)

    strict = FakeLLM()
    strict.reply = reply
    with pytest.raises(LlmFailed):
        Pipeline(strict, strict=True).run(make_input())
    assert strict.ops() == ["meeting_extract", "meeting_extract"]
    assert "not English" in strict.calls[1]["user"]                   # tuzatish so'rovi sababni aytadi
    lenient = FakeLLM()                                               # oxirgi model - avvalgidek
    lenient.reply = reply
    out = Pipeline(lenient).run(make_input())
    assert out.status == "ready" and lenient.ops() == ["meeting_extract", "meeting_verify"]


def test_v3_manba_raqamlari_olib_tashlanadi():
    class V3Like(FakeLLM):
        name = "v3"

    def reply(op, system, user):
        data = json.loads(auto_reply(op, system, user))
        if op == "meeting_extract":
            data["overview"] = "[S1] hisobotni muhokama qildi [1]. Qaror qabul qilindi [2][3]. Keyingi qadam bor."
        return json.dumps(data, ensure_ascii=False)

    fake = V3Like()
    fake.reply = reply
    overview = Pipeline(fake, strict=True).run(make_input()).content["overview"]
    assert "[1]" not in overview and "[2]" not in overview and "[3]" not in overview
    assert "muhokama qildi." in overview and "qilindi." in overview
    plain = FakeLLM()                                                 # boshqa model - o'zgarmagan
    plain.reply = reply
    assert "[1]" in Pipeline(plain).run(make_input()).content["overview"]


def test_v3_tasniflovchi_bitta_tuzatish():
    fake = FakeLLM()
    fake.script["meeting_classify"] = ["Bu umumiy yig'ilish.", '{"template": "general", "confidence": 0.9}']
    out = Pipeline(fake, strict=True).run(make_input(template="auto", repeat=12))
    assert out.status == "ready" and fake.ops()[:3] == ["meeting_classify", "meeting_classify", "meeting_extract"]
    bad = FakeLLM()
    bad.script["meeting_classify"] = ["Bilmadim.", "Yana bilmadim."]
    with pytest.raises(LlmFailed):
        Pipeline(bad, strict=True).run(make_input(template="auto", repeat=12))
    assert bad.ops() == ["meeting_classify", "meeting_classify"]


def test_v3_slot_kutadi_va_band(v3):
    slept: list[float] = []
    busy = AssistantError("navbat to'la", status=503, retryable=True, reason="queue_full")
    v3.script["meeting_classify"] = [busy, busy]
    chat = llm.V3Chat(v3, user_id="u", max_chars=20000, slot_wait=30, sleep=slept.append)
    text, _ = chat.complete_meta("s", "u", op="meeting_classify")
    assert parse_json(text)[0]["template"] == "general" and slept == [2.0, 2.0] and len(v3.calls) == 3
    # Savol-javob (`slot_wait=0`) - kutmaydi, darhol "band" (keyingi model).
    v3.script["meeting_classify"] = [busy]
    with pytest.raises(LlmBusy):
        llm.V3Chat(v3, user_id="u", max_chars=20000, sleep=slept.append).complete_meta("s", "u",
                                                                                       op="meeting_classify")
    # Kutish tugasa - "band" (ishchi xulosani 30 s dan keyin qayta oladi).
    v3.script["meeting_classify"] = [busy] * 10
    with pytest.raises(LlmBusy):
        llm.V3Chat(v3, user_id="u", max_chars=20000, slot_wait=5, sleep=lambda s: None).complete_meta(
            "s", "u", op="meeting_classify")


def test_v3_vaqtinchalik_xatoda_qayta_urinish(v3):
    slept: list[float] = []
    v3.script["meeting_classify"] = [AssistantError("Assistant 503: band", status=503, reason="upstream_busy"),
                                     AssistantError("javob oqimi uzildi (done kadri kelmadi)", status=503,
                                                    retryable=True)]
    chat = llm.V3Chat(v3, user_id="u", max_chars=20000, retries=2, sleep=slept.append)
    text, _ = chat.complete_meta("s", "u", op="meeting_classify")
    assert parse_json(text)[0]["template"] == "general" and slept == [5.0, 15.0] and len(v3.calls) == 3
    for exc, kind in ((AssistantError("Assistant 422: x", status=422, reason="upstream_http"), LlmFailed),
                      (AssistantError("Assistant 429: x", status=502, reason="upstream_http"), LlmRateLimited),
                      (AssistantError("oqim muddati", status=504, reason="stream_deadline"), LlmFailed)):
        v3.calls.clear()
        slept.clear()
        v3.script["meeting_classify"] = [exc]
        with pytest.raises(kind):
            chat.complete_meta("s", "u", op="meeting_classify")
        assert len(v3.calls) == 1 and slept == []                    # qayta urinilmadi


def test_v3_auth_kadri_lekin_json_bor(v3):
    v3.script["meeting_classify"] = [v3_frames('{"template": "general", "confidence": 0.9}',
                                               extra=[{"type": "error", "code": "auth_missing"}])]
    text, _ = llm.V3Chat(v3, user_id="u", max_chars=20000).complete_meta("s", "u", op="meeting_classify")
    assert json.loads(text)["template"] == "general"
    v3.script["meeting_classify"] = [v3_frames("CRM ga kiring.", extra=[{"type": "error", "code": "auth_missing"}])]
    with pytest.raises(LlmFailed):
        llm.V3Chat(v3, user_id="u", max_chars=20000).complete_meta("s", "u", op="meeting_classify")


def test_v3_darvoza_band_xulosa_navbatda_kutadi(client, auth, monkeypatch, chain, _isolated_meetings, v3):
    """Ikki ishchi ipi: v3 da boshqa xulosa yozilyapti - bu xulosa butunlay navbatda kutadi
    (urinish emas), pastki modelga tushmaydi; bo'shagach v3 da yoziladi."""
    rt = _isolated_meetings
    chain("v3,ollama")
    assert rt.v3_gate.acquire(blocking=False)
    try:
        enable(monkeypatch)
        meeting, _ = recorded(client, auth)
        run_all(rt, time.time(), rounds=3)
        row = rt.store.meeting_any(meeting["id"])
        summary = rt.store.summary(row["id"], row["primary_summary_id"])
        assert summary["status"] == "queued" and int(summary["attempts"]) == 0
        assert v3.calls == [] and rt.llm.calls == []
    finally:
        rt.v3_gate.release()
    run_all(rt, time.time() + 120)
    assert _summary(client, auth, meeting["id"])["generatedBy"]["provider"] == "v3"


def test_yiqilgan_v3_qayta_navbatda_takrorlanmaydi(client, auth, monkeypatch, chain, _isolated_meetings, v3):
    """v3 yiqildi, oxirgi model (Ollama) band - xulosa navbatga; keyingi urinishda v3 BOSHIDAN
    takrorlanmaydi (aks holda har 30 s da yiqilgan v3 urinishi cheksiz qaytardi)."""
    rt = _isolated_meetings
    chain("v3,ollama")
    v3.reply = lambda op, q: v3_frames("Kechirasiz.")                 # JSON yo'q - v3 yiqiladi
    rt.llm.script["meeting_extract"] = [OllamaError("navbat to'la")]
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(rt, time.time())
    run_all(rt, time.time() + 120)
    assert v3.ops() == ["meeting_extract", "meeting_extract"]         # faqat bir marta (+ tuzatish)
    assert rt.llm.ops().count("meeting_extract") == 2                 # band + muvaffaqiyat
    summary = _summary(client, auth, meeting["id"])
    assert summary["generatedBy"]["provider"] == "ollama"
    assert summary["content"]["quality"]["warnings"].count("provider_failed:v3") == 1
    assert _isolated_meetings.chain_failures == {}


def test_savol_json_javobsiz_keyingi_model_va_503(client, auth, monkeypatch, chain, _isolated_meetings):
    rt = _isolated_meetings
    row = _ready(client, auth, monkeypatch, rt)
    chain("v3,ollama")
    live = FakeAssistant()
    rt.live_assistant = live
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {})
    rt.llm.calls.clear()
    live.script["meeting_ask"] = [v3_frames('```json\n{"result": {"text": "boshqa shakl"}}\n```')]
    url = f"/api/v1/meetings/{row['id']}/ask"
    body = client.post(url, headers=auth, json={"question": "Kim?"}).json()
    assert body["answer"] == "[S1] hisobotni ertaga yuboradi." and rt.llm.ops() == ["meeting_ask"]
    # `{"result": {"answer": ...}}` o'rami - o'qiladi.
    live.script["meeting_ask"] = [v3_frames('{"result": {"answer": "Aziz yuboradi [1]."}}')]
    assert client.post(url, headers=auth, json={"question": "Kim?"}).json()["answer"] == "Aziz yuboradi."
    # Oxirgi model ham javobsiz JSON bersa - 503, bo'sh javob SAQLANMAYDI.
    live.script["meeting_ask"] = [v3_frames('{"citations": []}')]
    rt.llm.script["meeting_ask"] = ['{"citations": [1]}']
    failed = client.post(url, headers=auth, json={"question": "Kim?"})
    assert failed.status_code == 503 and failed.json()["code"] == "llm_unavailable"
    stored = client.get(f"/api/v1/meetings/{row['id']}/questions", headers=auth).json()["items"]
    assert len(stored) == 2 and all(q["answer"] for q in stored)


def test_savol_umumiy_muddat_jim_v3(client, auth, monkeypatch, chain, _isolated_meetings):
    """v3 jim (kadr yo'q) - umumiy muddatning 2/3 qismidan keyin keyingi model javob beradi."""
    rt = _isolated_meetings
    row = _ready(client, auth, monkeypatch, rt)
    chain("v3,ollama")
    live = FakeAssistant()
    live.delay = 3.0
    rt.live_assistant = live
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {})
    monkeypatch.setattr(settings, "meetings_ask_deadline", 3.3)
    rt.llm.calls.clear()
    started = time.monotonic()
    body = client.post(f"/api/v1/meetings/{row['id']}/ask", headers=auth, json={"question": "Kim?"}).json()
    assert body["answer"] == "[S1] hisobotni ertaga yuboradi." and rt.llm.ops() == ["meeting_ask"]
    assert time.monotonic() - started < 3.0 and len(live.calls) == 1


def test_crm_boshqa_platforma_taklifi_va_tanlov(client, auth, crm_ready):
    row, item, live = crm_ready
    url = f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm"
    hrm = _proposal("hrm-1")
    hrm["proposal"].update(connector="hrm", operation="create_leave_request")
    live.script["meeting_crm"] = [v3_frames("", extra=[hrm])]
    body = client.post(url, headers=auth).json()
    assert (body["status"], body["reason"], body["proposal"]) == ("failed", "unexpected_proposal", None)
    assert body["item"]["crm"] is None
    update = _proposal("upd-1")
    update["proposal"]["operation"] = "update_issue"
    live.script["meeting_crm"] = [v3_frames("", extra=[_proposal("create-1"), update, hrm])]
    body = client.post(url, headers=auth).json()
    assert body["status"] == "proposed" and body["proposal"]["token"] == "create-1"


def test_crm_outcome_muddat_chala_matn():
    reply = llm.V3Reply(text="Loyihani qidiryapman...", timed_out=True)
    assert crm.outcome(reply) == {"status": "failed", "proposal": None, "text": None, "reason": "timeout"}


def test_crm_qattiq_muddat_jim_v3(client, auth, monkeypatch, crm_ready):
    row, item, live = crm_ready
    live.delay = 1.0
    monkeypatch.setattr(settings, "meetings_crm_timeout", 0.3)
    started = time.monotonic()
    body = client.post(f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm", headers=auth).json()
    assert (body["status"], body["reason"]) == ("failed", "timeout") and body["item"]["crm"] is None
    assert time.monotonic() - started < 0.9


def test_crm_ikki_tez_bosish_bitta_taklif(client, auth, crm_ready):
    row, item, live = crm_ready
    live.delay = 0.3
    live.script["meeting_crm"] = [v3_frames("", extra=[_proposal("one")]), v3_frames("", extra=[_proposal("two")])]
    url = f"/api/v1/meetings/{row['id']}/action-items/{item['id']}/crm"
    results: list[dict] = []
    threads = [threading.Thread(target=lambda: results.append(client.post(url, headers=auth).json()))
               for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert [r["proposal"]["token"] for r in results] == ["one", "one"] and len(live.calls) == 1


def test_openai_uzilgan_javob_keyingi_model_va_hisob(openai_server, openai_client, _isolated_analytics):
    openai_server.responses = [(200, FakeOpenAI.TRUNCATED)]
    with pytest.raises(LlmFailed):
        openai_client.complete_meta("s", "u", op="meeting_map")
    assert analytics.flush()
    rows = _isolated_analytics.rows("SELECT status FROM api_calls WHERE service='openai'")
    assert [r["status"] for r in rows] == ["error"]


def test_openai_400_faqat_aniq_sababda_tuzatiladi(openai_server, openai_client):
    openai_server.responses = [(400, {"error": {"message": "maximum context length is 128000 tokens",
                                                "param": "messages", "code": "context_length_exceeded"}})]
    with pytest.raises(LlmFailed):
        openai_client.complete_meta("s", "u", op="meeting_classify", format="json")
    assert len(openai_server.requests) == 1                           # bekor qayta so'rov yo'q
    client = llm.OpenAIChat(openai_server.base_url, lambda: "k", "gpt-test", timeout=10, reasoning_effort="high",
                            temperature=0.1)
    openai_server.requests.clear()
    openai_server.responses = [(400, {"error": {"message": "Unsupported parameter: 'reasoning_effort'",
                                                "param": "reasoning_effort"}}),
                               (200, completion('{"template": "general", "confidence": 0.9}'))]
    text, _ = client.complete_meta("s", "u", op="meeting_classify", format="json")
    first, second = (r["body"] for r in openai_server.requests)
    assert json.loads(text)["template"] == "general"
    assert first["reasoning_effort"] == "high" and "reasoning_effort" not in second and second["temperature"] == 0.1
    assert second["response_format"]["type"] == "json_schema"


def test_openai_5xx_bir_marta_qayta(openai_server, openai_client):
    slept: list[float] = []
    client = llm.OpenAIChat(openai_server.base_url, lambda: "k", "gpt-test", timeout=10, retries=1,
                            sleep=slept.append)
    ok = completion('{"template": "general", "confidence": 0.9}')
    openai_server.responses = [(503, {"error": {"message": "overloaded"}}), (200, ok)]
    text, _ = client.complete_meta("s", "u", op="meeting_classify", format="json")
    assert json.loads(text)["template"] == "general" and slept == [3.0] and len(openai_server.requests) == 2
    openai_server.responses = [(503, {"error": {}}), (502, {"error": {}})]
    with pytest.raises(LlmFailed):
        client.complete_meta("s", "u", op="meeting_classify", format="json")
    openai_server.responses = [(400, {"error": {"message": "bad"}})]   # 4xx - qayta urinilmaydi
    slept.clear()
    with pytest.raises(LlmFailed):
        client.complete_meta("s", "u", op="meeting_classify", format="json")
    assert slept == []

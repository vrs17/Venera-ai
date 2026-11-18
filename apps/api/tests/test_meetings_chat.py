"""Yig'ilish CHATI (bitta audio - bitta suhbat): `GET/POST/DELETE /api/v1/meetings/{id}/chat`, suhbat xotirasi,
Claude'ning ko'p navbatli so'rovi (prompt keshi, rad-zahirasi), boshqa modellarga matn bloki, umumiy hisobda
so'rovchi bo'yicha alohida suhbat (Slack, `asker`), qayta o'girish va javob kutilayotgandagi "Yangi suhbat" yoki
qayta o'girish, klient kaliti (`clientId` - idempotentlik), ombor (v7, v8).

BAYONNOMA CHATDA (2026-11-12): chat modeli amal tanlaydi (`none` / `note` / `create` / `revise`, soxta javob -
`chat_reply`), aniq kirish nuqtasi (`intent`) modelsiz, hujjat va holat bloklari (kesh qoidasi), navbatdagi hujjatning
jonli holati, ish boshlanmasa ham 200, ko'rsatmalar qayta o'girishdan keyin qoladi, ikki yozuv aralashmaydi. Hujjat -
`FakeLLM` (`MEETINGS_MINUTES_CHAIN=ollama`), fon ishi shu ipda (`minutes.runner`).

Hech bir test tarmoqqa chiqmaydi: Claude - `FakeAnthropic` (`ClaudeChat(client_factory=...)`), Ollama - `FakeLLM`,
agent - `FakeAgent`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

import anthropic
import pytest

from app.core.config import settings
from app.schemas import meetings as schemas
from app.schemas.auth import AuthUser
from app.services import analytics
from app.services import meetings as meetings_pkg
from app.services.meetings import ask, chat, llm, minutes, prompts, service, shapes
from app.services.meetings import store as store_mod
from app.services.meetings.minutes import state as minutes_state
from app.services.meetings.store import MeetingStore, jload
from app.services.meetings.summarize import LlmUnavailable
from meetings_fakes import (CHAT_ACTION_ANSWER, FakeAnthropic, auto_reply, chat_reply, claude_error, claude_message,
                            create_meeting, enable, recorded, run_all)
from tests.agent_fakes import FakeAgent, enable_agent

CLAUDE_KEY = "sk-ant-test-CHAT-SECRET"
TURN_FIELDS = {"id", "question", "answer", "citations", "followUps", "createdAt", "channel", "model", "clientId",
               "kind", "minutes"}
#: Amalsiz navbat qayta yuborilganda (`chat.replay`) - `shapes.chat` dagi `minutes` qiymati.
NO_ACTION = {"action": "none", "language": None, "instruction": None}
ASK_FIELDS = {"id", "question", "answer", "citations", "followUps", "createdAt"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: Ilova beradigan klient kaliti shaklida (tasodifiy, URL-xavfsiz).
KEY = "m1-7Hq2_Zx9-retry"


@pytest.fixture
def claude(_isolated_meetings, monkeypatch):
    """Prod'dagidek: savol/chat zanjiri faqat Claude (`MEETINGS_ASK_CHAIN=claude`), klient rad-zahirasi bilan."""
    monkeypatch.setattr(settings, "meetings_ask_chain", "claude", raising=False)
    fake = FakeAnthropic()
    _isolated_meetings.ask_claude = llm.ClaudeChat(lambda: CLAUDE_KEY, "claude-sonnet-5-5", timeout=10,
                                                   client_factory=fake, fallbacks=True)
    return fake


@pytest.fixture
def ready(client, auth, monkeypatch, _isolated_meetings) -> str:
    """Transkripti va asosiy xulosasi tayyor yig'ilish id si (xulosa - FakeLLM, default zanjir)."""
    enable(monkeypatch)
    meeting, _ = recorded(client, auth)
    run_all(_isolated_meetings)
    return meeting["id"]


@pytest.fixture
def docs(ready, monkeypatch) -> str:
    """`ready` + bayonnoma: zanjir `FakeLLM` (`MEETINGS_MINUTES_CHAIN=ollama`), fon ishi shu ipda (deterministik)."""
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    monkeypatch.setattr(minutes, "runner", lambda job: job())
    return ready


def _minutes_calls(rt) -> list[dict]:
    """Bayonnoma model chaqiruvlari (`FakeLLM`): yangi hujjat va tahrir."""
    return [c for c in rt.llm.calls if c["op"].startswith("meeting_minutes")]


def _url(mid: str) -> str:
    return f"/api/v1/meetings/{mid}/chat"


def _say(client, auth, mid: str, message: str, **body) -> dict:
    response = client.post(_url(mid), headers=auth, json={"message": message, **body})
    assert response.status_code == 200, response.text
    return response.json()


def _owner(rt, mid: str) -> AuthUser:
    return AuthUser(actorId=rt.store.meeting_any(mid)["actor_id"], email="admin@venera.uz", fullName="Admin",
                    roles=["ADMIN"])


@pytest.fixture
def waiting(caplog):
    """Takroriy xabar birinchisini kuta boshlaganini boshqa ipga bildiradi (`chat_send` jurnali - matnsiz):
    parallel testlar uyqu bilan emas, aniq nuqtada uchrashadi."""
    caplog.set_level(logging.INFO, logger=service.log.name)
    seen = threading.Event()

    class _Seen(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if "birinchisi kutiladi" in record.getMessage():
                seen.set()

    handler = _Seen(logging.INFO)
    service.log.addHandler(handler)
    yield seen
    service.log.removeHandler(handler)


def _in_background(fn) -> tuple[threading.Thread, dict]:
    """`fn()` boshqa ipda (ikkinchi so'rov) -> (ip, natija qutisi: `value` yoki `error`)."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:                               # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def _fallback_served(text: str):
    """Rad-zahirasi ishlagan javob (beta xabar): `fallback` bloki + zahira modelining matni."""
    from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaUsage
    from anthropic.types.beta.beta_fallback_block import BetaFallbackBlock

    switch = BetaFallbackBlock.model_validate({"type": "fallback", "from": {"model": "claude-sonnet-5-5"},
                                               "to": {"model": "claude-sonnet-5"},
                                               "trigger": {"type": "refusal", "category": "cyber"}})
    return BetaMessage(id="msg_fb", type="message", role="assistant", model="claude-sonnet-5",
                       content=[switch, BetaTextBlock(type="text", text=text)], stop_reason="end_turn",
                       stop_sequence=None, usage=BetaUsage(input_tokens=10, output_tokens=5))


# --- Claude: ko'p navbatli so'rov ------------------------------------------------------------------


def test_ikkinchi_xabar_birinchi_navbatni_xotira_sifatida_oladi(client, auth, ready, claude):
    first = _say(client, auth, ready, "Hisobotni kim yuboradi?")
    second = _say(client, auth, ready, "Batafsilroq?")
    one, two = claude.chats()
    assert [m["role"] for m in one["messages"]] == ["user"]
    assert [m["role"] for m in two["messages"]] == ["user", "assistant", "user"]
    # Tarix faqat oxiriga qo'shiladi: birinchi savol AYNAN o'sha shaklda qayta yuboriladi.
    assert two["messages"][0] == one["messages"][0] == {"role": "user",
                                                        "content": prompts.chat_question("Hisobotni kim yuboradi?",
                                                                                         "uz")}
    # Javob - modelning o'z JSON shakli (`shapes.chat` tartibida: bayonnoma amali birinchi; oddiy navbatda `none`),
    # faqat MATN ("o'ylash" bloklari saqlanmaydi va qayta yuborilmaydi).
    assert all(isinstance(m["content"], str) for m in two["messages"])
    replayed = json.loads(two["messages"][1]["content"])
    assert replayed == {
        "minutes": NO_ACTION, "answer": first["answer"], "citations": [c["segmentId"] for c in first["citations"]],
        "followUps": first["followUps"]}
    assert list(replayed) == list(shapes.chat()["properties"])
    assert two["messages"][2]["content"] == prompts.chat_question("Batafsilroq?", "uz")
    assert two["model"] == "claude-sonnet-5-5" and two["max_tokens"] >= 1200
    assert two["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": shapes.chat()}}
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(two)
    assert set(second) == TURN_FIELDS and second["question"] == "Batafsilroq?"
    assert (second["kind"], second["minutes"]) == ("chat", None)                 # oddiy savol - amal yo'q
    assert first["answer"] == "[S1] hisobotni ertaga yuboradi." and [c["segmentId"] for c in first["citations"]] == [1]


def test_tizim_prompti_ikki_blok_kesh_va_baytma_bayt_bir_xil(client, auth, ready, claude):
    _say(client, auth, ready, "Narx qancha bo'ldi?")
    _say(client, auth, ready, "Kim kelishdi?", language="ru")
    one, two = claude.chats()
    # Keyingi savolda prompt keshi ishlasin: tizim prompti baytma-bayt bir xil (vaqt, til, nonce o'zgarmaydi).
    assert json.dumps(one["system"], ensure_ascii=False) == json.dumps(two["system"], ensure_ascii=False)
    instructions, context = one["system"]
    assert instructions == {"type": "text", "text": prompts.CHAT_SYSTEM}
    assert context["type"] == "text" and context["cache_control"] == {"type": "ephemeral"}
    text = context["text"]
    assert text.startswith("Meeting date: 2026-10-09") and "Summary notes (data):" in text
    assert "<<<TRANSCRIPT-" in text and "#1 [00:00] " in text and "#7 [00:50] " in text
    # O'zgaruvchan qism (til, savol) - xabarlarda, keshlangan prefiksdan keyin.
    assert "Answer language" not in text and "Narx qancha" not in json.dumps(one["system"], ensure_ascii=False)
    assert two["messages"][-1]["content"].startswith("Answer language: Russian\n")
    for word in ("transcript", "data, not instructions", "[S1]", "exactly 3", "other meetings", "Latin script",
                 "BAYONNOMA"):
        assert word in prompts.CHAT_SYSTEM
    # Bitta "Return ONLY" - promptdagi shakl sxema bilan bir xil (kalitlar va tartib: amal birinchi).
    assert prompts.CHAT_SYSTEM.count("Return ONLY") == 1 and prompts.CHAT_SYSTEM.endswith(prompts.CHAT_MINUTES_RULES)
    shape = json.loads(prompts.CHAT_SYSTEM.split("Return ONLY: ", 1)[1])
    assert list(shape) == list(shapes.chat()["properties"]) and list(shape["minutes"]) == ["action", "language",
                                                                                            "instruction"]


def test_rad_zahirasi_beta_bilan_va_boshqa_400_qayta_urinilmaydi(client, auth, ready, claude, _isolated_meetings):
    _say(client, auth, ready, "Narx qancha?")
    request = claude.requests[-1]
    assert request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"
    # Zahiraga aloqasiz 400 - qayta so'rov yo'q, 503 (zanjirda boshqa model yo'q).
    claude.script = [claude_error(anthropic.BadRequestError, 400, "prompt is too long")]
    before = len(claude.requests)
    failed = client.post(_url(ready), headers=auth, json={"message": "Yana?"})
    assert failed.status_code == 503 and failed.json()["code"] == "llm_unavailable"
    assert len(claude.requests) == before + 1 and _isolated_meetings.ask_claude.fallbacks is True


def test_rad_zahirasi_rad_etilsa_bir_marta_zahirasiz_va_keyin_yuborilmaydi(client, auth, ready, claude,
                                                                          _isolated_meetings, caplog):
    caplog.set_level(logging.WARNING)
    claude.script = [claude_error(anthropic.BadRequestError, 400,
                                  f"anthropic-beta: unexpected value {FALLBACK_BETA} (key {CLAUDE_KEY})")]
    body = _say(client, auth, ready, "Kim kelishdi?")
    rejected, retried = claude.requests
    assert rejected["betas"] == [FALLBACK_BETA] and not {"betas", "fallbacks"} & set(retried)
    assert {k: v for k, v in rejected.items() if k not in ("betas", "fallbacks")} == retried
    assert body["answer"] == "[S1] hisobotni ertaga yuboradi."
    assert _isolated_meetings.ask_claude.fallbacks is False
    _say(client, auth, ready, "Yana?")
    assert len(claude.requests) == 3 and "betas" not in claude.requests[-1]
    assert sum("rad-zahirasi rad etildi" in r.getMessage() for r in caplog.records) == 1
    assert CLAUDE_KEY not in caplog.text


def test_zahira_modeli_javob_bersa_shu_model_saqlanadi(client, auth, ready, claude, _isolated_meetings):
    reply = json.dumps({"answer": "[S2] hisobotni yuboradi.", "citations": [2],
                        "followUps": ["Qachon?", "Kim?", "Nima?"]})
    claude.script = [lambda request: _fallback_served(reply)]
    body = _say(client, auth, ready, "Hisobotni kim yuboradi?")
    assert body["answer"] == "[S2] hisobotni yuboradi." and [c["segmentId"] for c in body["citations"]] == [2]
    assert body["model"] == "claude-sonnet-5"                        # `fallback` bloki o'qilmadi, model - zahiraniki
    assert _isolated_meetings.store.chat_turns(ready)[0]["model"] == "claude-sonnet-5"


def test_hisobda_kesh_tokenlari_jurnalda_matn_yoq(client, auth, ready, claude, _isolated_analytics, caplog):
    caplog.set_level(logging.INFO)
    reply = json.dumps({"answer": "Narx 15 mln so'm bo'ldi.", "citations": [3], "followUps": ["a", "b", "c"]},
                       ensure_ascii=False)
    claude.script = [claude_message(reply, cache_read=900, cache_write=0)]
    _say(client, auth, ready, "Narxni kim aytdi?")
    assert analytics.flush()
    [row] = _isolated_analytics.rows("SELECT op, status, units FROM api_calls WHERE service='claude'")
    units = json.loads(row["units"])
    assert (row["op"], row["status"]) == ("meeting_chat", "ok")
    assert (units["tokens_in"], units["tokens_out"], units["cache_read"], units["cache_write"]) == (1200, 340, 900, 0)
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Claude (meeting_chat)")]
    assert "claude-sonnet-5-5" in line and "900" in line and "1200" in line
    for secret in ("Narxni kim aytdi", "15 mln", CLAUDE_KEY):
        assert secret not in caplog.text


def test_converse_sxema_400_formatsiz_zahira_saqlanadi():
    fake = FakeAnthropic()
    client = llm.ClaudeChat(lambda: CLAUDE_KEY, "claude-sonnet-5-5", timeout=10, effort="low", client_factory=fake,
                            fallbacks=True)
    system = chat.system_blocks("meta", "", ["#1 [00:00] S1: salom"])
    messages = [{"role": "user", "content": prompts.chat_question("Kim?", "uz")}]
    fake.script = [claude_error(anthropic.BadRequestError, 400, "output_config.format.schema: unsupported"),
                   '{"answer": "ok", "citations": [1], "followUps": []}']
    text, meta = client.converse(system, messages)
    assert json.loads(text)["answer"] == "ok" and meta["model"] == "claude-sonnet-5-5"
    first, second = fake.requests
    assert first["system"] == system and first["messages"] == messages and first["max_tokens"] == 16000
    assert first["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": shapes.chat()}}
    assert second["output_config"] == {"effort": "low"} and second["betas"] == [FALLBACK_BETA]
    assert "meeting_chat" in client._formatless and client.fallbacks is True
    # Sozlanmagan klient - so'rov ham, SDK klienti ham yo'q.
    off = llm.ClaudeChat(lambda: "", "claude-sonnet-5-5", client_factory=fake)
    with pytest.raises(LlmUnavailable):
        off.converse(system, messages)
    assert len(fake.requests) == 2


def test_haqiqiy_sdk_sorov_shakli_tarmoqsiz(caplog):
    """Soxta SDK kalit nomlarini tekshirmaydi: HAQIQIY `anthropic` klienti (`httpx2.MockTransport` - tarmoq yo'q)
    `converse` so'rovini qabul qiladi - beta sarlavha, `fallbacks`, kesh bloki; zahira rad etilsa - oddiy yo'l."""
    import httpx2

    seen: list[dict] = []
    events = [
        {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant",
                                              "model": "claude-sonnet-5-5", "content": [], "stop_reason": None,
                                              "stop_sequence": None,
                                              "usage": {"input_tokens": 10, "output_tokens": 1,
                                                        "cache_read_input_tokens": 7,
                                                        "cache_creation_input_tokens": 3}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": '{"answer": "ok", "citations": [1], "followUps": []}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
         "usage": {"output_tokens": 12}},
        {"type": "message_stop"},
    ]

    def handler(request):
        seen.append({"beta": request.headers.get("anthropic-beta"), "body": json.loads(request.content)})
        if len(seen) == 1:
            return httpx2.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": f"Unexpected value(s) `{FALLBACK_BETA}` for the "
                                                           "`anthropic-beta` header."}})
        stream = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        return httpx2.Response(200, content=stream.encode(), headers={"content-type": "text/event-stream"})

    def factory(**kwargs):
        return anthropic.Anthropic(http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), **kwargs)

    client = llm.ClaudeChat(lambda: CLAUDE_KEY, "claude-sonnet-5-5", timeout=10, retries=0, client_factory=factory,
                            fallbacks=True)
    history = [{"question": "Kim?", "answer": "[S1].", "citations": [1], "followUps": ["Qachon?"], "language": "uz"}]
    messages = chat.replay(history, "uz") + [{"role": "user", "content": prompts.chat_question("Batafsil?", "uz")}]
    text, meta = client.converse(chat.system_blocks("meta", "", ["#1 [00:00] S1: salom"]), messages)
    assert json.loads(text)["answer"] == "ok" and meta == {"doneReason": "end_turn", "tokensIn": None, "tokensOut": 12,
                                                           "model": "claude-sonnet-5-5"}
    first, second = seen
    assert first["beta"] == FALLBACK_BETA and first["body"]["fallbacks"] == "default"
    assert second["beta"] is None and "fallbacks" not in second["body"] and client.fallbacks is False
    body = second["body"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert body["system"][1]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in body["system"][0]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(body)
    assert CLAUDE_KEY not in caplog.text


def test_chat_klienti_sozlamalardan(monkeypatch):
    """`rt.ask_claude` zavodi: chat modeli va `effort`i (bo'sh - xulosaniki), slotlar va rad-zahirasi."""
    own = meetings_pkg._claude(3, 120.0, 0, model="claude-opus-5-5", effort="high", fallbacks=True)
    assert (own.model, own.effort, own.fallbacks, own.retries, own.timeout) == ("claude-opus-5-5", "high", True, 0,
                                                                               120.0)
    assert all(own._slots.acquire(blocking=False) for _ in range(3)) and not own._slots.acquire(blocking=False)
    default = meetings_pkg._claude(1, 600.0, 2)
    assert (default.model, default.effort, default.fallbacks) == (settings.meetings_claude_model,
                                                                  settings.meetings_claude_effort, False)
    # Koddagi default'lar (`.env` dagi qiymat emas).
    defaults = {name: field.default for name, field in type(settings).model_fields.items()}
    assert {name: defaults[name] for name in ("meetings_chat_model", "meetings_chat_effort",
                                              "meetings_chat_history_turns", "meetings_chat_history_chars",
                                              "meetings_chat_context_chars", "meetings_chat_concurrency",
                                              "meetings_chat_fallbacks", "meetings_ask_per_hour")} == {
        "meetings_chat_model": "", "meetings_chat_effort": "", "meetings_chat_history_turns": 10,
        "meetings_chat_history_chars": 40000, "meetings_chat_context_chars": 400000, "meetings_chat_concurrency": 4,
        "meetings_chat_fallbacks": True, "meetings_ask_per_hour": 60}


# --- suhbat: tarix, izolyatsiya, "Yangi suhbat" ---------------------------------------------------------


def test_tarix_eskisi_birinchi_va_model_nomi(client, auth, ready, claude, monkeypatch, _isolated_meetings):
    first = _say(client, auth, ready, "Birinchi savol?")
    second = _say(client, auth, ready, "Ikkinchi savol?")
    body = client.get(_url(ready), headers=auth).json()
    assert set(body) == {"items", "model"} and body["model"] == "claude-sonnet-5-5"
    assert [t["id"] for t in body["items"]] == [first["id"], second["id"]]
    assert all(set(t) == TURN_FIELDS for t in body["items"])
    assert set(body["items"][0]["citations"][0]) == {"segmentId", "start", "speaker", "text"}
    # Yorliq - zanjirdagi birinchi SOZLANGAN model; hech biri sozlanmagan - "".
    monkeypatch.setattr(settings, "meetings_ask_chain", "claude,ollama", raising=False)
    _isolated_meetings.ask_claude = None
    assert client.get(_url(ready), headers=auth).json()["model"] == "gemma4:31b"
    monkeypatch.setattr(settings, "meetings_ask_chain", "openai", raising=False)
    assert client.get(_url(ready), headers=auth).json()["model"] == ""


def test_har_yigilish_alohida_suhbat(client, auth, ready, claude, _isolated_meetings):
    other, _ = recorded(client, auth)
    run_all(_isolated_meetings)
    _say(client, auth, ready, "Narx qancha bo'ldi?")
    _say(client, auth, other["id"], "Keyingi yig'ilish qachon?")
    to_other = claude.chats()[-1]
    assert len(to_other["messages"]) == 1 and "Narx qancha" not in json.dumps(to_other, ensure_ascii=False)
    assert [t["question"] for t in client.get(_url(other["id"]), headers=auth).json()["items"]] == \
        ["Keyingi yig'ilish qachon?"]
    assert [t["question"] for t in client.get(_url(ready), headers=auth).json()["items"]] == ["Narx qancha bo'ldi?"]
    # "Yangi suhbat" faqat o'z yig'ilishida.
    assert client.delete(_url(other["id"]), headers=auth).json() == {"archived": 1}
    assert len(client.get(_url(ready), headers=auth).json()["items"]) == 1


def test_yangi_suhbat_yumshoq_arxiv_va_xotirasiz_boshlanadi(client, auth, ready, claude, _isolated_meetings):
    _say(client, auth, ready, "Hisobotni kim yuboradi?")
    _say(client, auth, ready, "Qachon?")
    assert client.delete(_url(ready), headers=auth).json() == {"archived": 2}
    assert client.get(_url(ready), headers=auth).json()["items"] == []
    fresh = _say(client, auth, ready, "Yangi savol?")
    assert len(claude.chats()[-1]["messages"]) == 1                 # eski navbatlar modelga bormaydi
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [fresh["id"]]
    # Qatorlar bazada qoladi (qattiq o'chirish yo'q); takroriy "Yangi suhbat" faqat faollarni oladi.
    rows = _isolated_meetings.store.rows("SELECT archived_at FROM questions WHERE meeting_id=?", (ready,))
    assert len(rows) == 3 and sum(r["archived_at"] is not None for r in rows) == 2
    assert client.delete(_url(ready), headers=auth).json() == {"archived": 1}
    assert client.delete(_url(ready), headers=auth).json() == {"archived": 0}


def test_eski_ask_xotira_bilan_questions_arxivni_korsatmaydi(client, auth, ready, claude, _isolated_meetings):
    base = f"/api/v1/meetings/{ready}"
    first = client.post(f"{base}/ask", headers={**auth, "X-Venera-Client": "mobile"},
                        json={"question": "Hisobotni kim yuboradi?"})
    assert first.status_code == 200 and set(first.json()) == ASK_FIELDS          # eski shakl o'zgarmagan
    second = client.post(f"{base}/ask", headers=auth, json={"question": "Qachon?"}).json()
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user", "assistant", "user"]
    listed = client.get(f"{base}/questions", headers=auth).json()["items"]
    assert [q["id"] for q in listed] == [second["id"], first.json()["id"]]           # yangisi birinchi
    assert all(set(q) == ASK_FIELDS for q in listed)
    stored = {r["id"]: r["channel"] for r in _isolated_meetings.store.rows("SELECT id, channel FROM questions")}
    assert stored == {first.json()["id"]: "mobile", second["id"]: "api"}
    # Bitta suhbat: `/ask` savollari chat tarixida ham.
    assert [t["question"] for t in client.get(_url(ready), headers=auth).json()["items"]] == \
        ["Hisobotni kim yuboradi?", "Qachon?"]
    client.delete(_url(ready), headers=auth)
    assert client.get(f"{base}/questions", headers=auth).json()["items"] == []


def test_kanal_model_til_saqlanadi_va_server_kanallari_egasi_suhbatida(client, auth, ready, claude,
                                                                       _isolated_meetings):
    rt = _isolated_meetings
    mobile = _say(client, auth, ready, "Narx qancha?", channel="mobile", language="ru")
    plain = _say(client, auth, ready, "Kim kelishdi?")
    assert (mobile["channel"], mobile["model"], plain["channel"]) == ("mobile", "claude-sonnet-5-5", "api")
    rows = {r["id"]: r for r in rt.store.rows("SELECT id, channel, model, language, archived_at, asker "
                                              "FROM questions")}
    assert rows[mobile["id"]] == {"id": mobile["id"], "channel": "mobile", "model": "claude-sonnet-5-5",
                                  "language": "ru", "archived_at": None, "asker": None}
    assert (rows[plain["id"]]["channel"], rows[plain["id"]]["language"]) == ("api", "uz")
    # Server ichidan (`service.chat_send`): `asker` siz - hisob egasining O'SHA suhbati (Telegram shunday);
    # noma'lum kanal - `api`.
    user = _owner(rt, ready)
    slack = service.chat_send(user, ready, "Muddat qachon?", None, channel="slack")
    assert slack["channel"] == "slack" and set(slack) == TURN_FIELDS
    replayed = claude.chats()[-1]["messages"]
    assert len(replayed) == 5 and replayed[0]["content"].startswith("Answer language: Russian\n")  # o'z tilida
    assert service.chat_send(user, ready, "Yana?", "en", channel="telegram")["channel"] == "telegram"
    assert service.chat_send(user, ready, "Yana?", None, channel="fax")["channel"] == "api"
    # Eski chaqiruv: `service.ask(user, id, matn, None)` - egasining chat navbati.
    legacy = service.ask(user, ready, "Eski yo'l?", None)
    assert legacy["channel"] == "api" and set(legacy) == TURN_FIELDS
    assert len(client.get(_url(ready), headers=auth).json()["items"]) == 6


def test_xotira_sozlamasi_oxirgi_navbatlar(client, auth, ready, claude, monkeypatch):
    monkeypatch.setattr(settings, "meetings_chat_history_turns", 1)
    for question in ("Birinchi?", "Ikkinchi?", "Uchinchi?"):
        _say(client, auth, ready, question)
    last = claude.chats()[-1]["messages"]
    assert len(last) == 3 and last[0]["content"].endswith("Question: Ikkinchi?")
    monkeypatch.setattr(settings, "meetings_chat_history_turns", 0)                 # xotira o'chiq
    _say(client, auth, ready, "To'rtinchi?")
    assert len(claude.chats()[-1]["messages"]) == 1


def test_uzun_transkript_savol_va_oldingi_savol_bilan_tanlanadi(client, auth, ready, claude, monkeypatch):
    monkeypatch.setattr(settings, "meetings_chat_context_chars", 250)
    _say(client, auth, ready, "Byudjet masalasi nima bo'ldi?")
    _say(client, auth, ready, "U nima uchun?")                       # o'zida mos so'z yo'q - oldingi savoldan
    for request in claude.chats():
        context = request["system"][1]
        assert "#7 [00:50] " in context["text"] and "#1 [00:00] " not in context["text"]
        # Tanlov har savolda boshqa - kesh yozuvi (oddiy kirishdan qimmat) behuda: kontekst keshlanmaydi.
        assert "cache_control" not in context and "cache_control" not in request["system"][0]
    monkeypatch.setattr(settings, "meetings_chat_context_chars", 400000)            # sig'adi - hammasi
    _say(client, auth, ready, "Yana?")
    context = claude.chats()[-1]["system"][1]
    assert "#1 [00:00] " in context["text"] and context["cache_control"] == {"type": "ephemeral"}
    assert chat.system_blocks("meta", "", ["#1 [00:00] S1: salom"], cache=False)[1] == {
        "type": "text", "text": prompts.chat_context("meta", "", ["#1 [00:00] S1: salom"])}


def _agent_meetings(fake):
    """Soxta agent `complete` i yig'ilish amallariga `auto_reply` bilan javob beradi (`test_brain_seams` dagidek)."""
    def complete(body):
        op = body["input"]["vars"]["op"]
        return {"output": auto_reply(op, body["instructions"], body["input"]["text"]),
                "meta": {"trace_id": f"t-{op}", "tokens_in": 10, "tokens_out": 10}}

    fake.handlers["/complete"] = complete
    return fake


def test_chat_agent_yoqiq_bolsa_ham_claude_va_bayonnoma_amali(client, auth, docs, claude, monkeypatch,
                                                               _isolated_meetings):
    """`MEETING_ASK_ENGINE=agent` (prod, ega qarori 2026-10-12) bo'lsa ham yozuv CHATI - Claude (`chat.converse`):
    agent eski savol-javob promptini oladi, unda bayonnoma amali yo'q. 2026-11-13 jonli topilma: Slack'dagi "sana 11
    noyabr bo'lsin" oddiy savol bo'lib qoldi, hujjat tahrirlanmadi. `GET /chat` yorlig'i ham shu zanjirdan; agentga
    hech narsa bormaydi. Eski `/ask` - avvalgidek agentda (`test_brain_seams.test_savol_agent_bogini`)."""
    rt = _isolated_meetings
    fake = enable_agent(monkeypatch, _agent_meetings(FakeAgent()), meeting_ask="agent")
    claude.script = [chat_reply()]
    plain = _say(client, auth, docs, "Kim hisobot yuboradi?")
    assert (plain["model"], plain["kind"]) == ("claude-sonnet-5-5", "chat")
    claude.script = [chat_reply("create")]
    made = _say(client, auth, docs, "Bayonnoma tayyorlab ber")
    assert (made["kind"], made["minutes"]["version"]) == ("create", 1)
    claude.script = [chat_reply("revise", instruction="Sarlavhani «Yangi sarlavha» qilish")]
    edited = _say(client, auth, docs, "TITLE=Yangi sarlavha")
    assert (edited["model"], edited["kind"], edited["minutes"]["version"]) == ("claude-sonnet-5-5", "revise", 2)
    assert jload(rt.store.minutes_by_turn(edited["id"])["content_json"])["title"] == "Yangi sarlavha"
    # Bayonnoma bloklari Claude'ga borgan (tahrir navbatida hujjat ko'rinadi), agentga - hech narsa.
    assert "BAYONNOMA" in json.dumps(claude.chats()[-1]["system"], ensure_ascii=False)
    assert len(claude.chats()) == 3 and fake.bodies("/complete") == []
    assert client.get(_url(docs), headers=auth).json()["model"] == "claude-sonnet-5-5"
    rt.store.update_meeting(docs, source="call")                       # telefon qo'ng'irog'i ham - Claude
    assert client.get(_url(docs), headers=auth).json()["model"] == "claude-sonnet-5-5"


def test_chatda_sana_tahriri_word_va_fayl_nomida(client, auth, docs, claude, _isolated_meetings):
    """Jonli topilma (2026-11-13): audio yig'ilishdan keyin yuklangan - Word'dagi sana yuklangan kun edi, «sana 11
    noyabr bo'lishi kerak» esa hech narsa o'zgartirmasdi (sana maydoni yo'q edi). Endi tahrir: yangi versiyada
    sarlavha sanasi (`header.date`) ega aytgan kun, Word'dagi sana qatori va fayl nomi shu, o'zgarishlar - "sana"."""
    from app.services.meetings.minutes import diff

    rt = _isolated_meetings
    user = _owner(rt, docs)
    claude.script = [chat_reply("create")]
    _say(client, auth, docs, "Bayonnoma tayyorlab ber")
    claude.script = [chat_reply("revise", instruction="Bayonnoma sanasini 2026-yil 11-noyabr qilish")]
    edited = _say(client, auth, docs, "bayonoma sanasi 2026 yil 11 noyabr bo'lishi kerak DATE=2026-11-11")
    assert (edited["kind"], edited["minutes"]["version"], edited["minutes"]["status"]) == ("revise", 2, "ready")
    row = rt.store.minutes_by_turn(edited["id"])
    assert jload(row["content_json"])["header"]["date"] == "2026-11-11"
    changes = jload(row["changes_json"])
    assert changes["header"] == ["date"] and "sana yangilandi" in diff.summary_uz(changes)
    data, _, disposition = minutes.export_file(user, docs, row["id"], "docx")
    assert "2026-11-11.docx" in disposition
    import io
    import zipfile

    assert "2026 йил 11 ноябрь" in zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    assert minutes.status(user, docs, row["id"])["header"]["date"] == "2026-11-11"


# --- umumiy hisob (Slack): har so'rovchining suhbati o'ziniki ---------------------------------------------


def test_ikki_sorovchi_bir_yigilishda_alohida_xotira_va_yangi_suhbat(client, auth, ready, claude, _isolated_meetings):
    """Slack'dagi hamma odam bitta hisobdan (`SLACK_ACTOR_ID`): ikki odam bitta yozuvga yetsa ham (qayta ulashilgan
    fayl) bir-birining savolini xotirada olmaydi va "Yangi suhbat"i faqat o'zinikini tozalaydi."""
    rt = _isolated_meetings
    user = _owner(rt, ready)
    service.chat_send(user, ready, "A-SAVOL: kim qaysi vazifani oldi?", None, channel="slack", asker="slack:U1")
    service.chat_send(user, ready, "B-SAVOL: budjet qancha?", None, channel="slack", asker="slack:U2")
    service.chat_send(user, ready, "Batafsilroq", None, channel="slack", asker=" slack:U1 ")   # chetidagi bo'shliq
    _, to_b, follow = claude.chats()
    assert len(to_b["messages"]) == 1 and "A-SAVOL" not in json.dumps(to_b, ensure_ascii=False)
    assert [m["role"] for m in follow["messages"]] == ["user", "assistant", "user"]
    assert "A-SAVOL" in follow["messages"][0]["content"] and "B-SAVOL" not in json.dumps(follow, ensure_ascii=False)
    stored = rt.store.rows("SELECT asker, channel FROM questions ORDER BY created_at, rowid")
    assert [(r["asker"], r["channel"]) for r in stored] == [("slack:U1", "slack"), ("slack:U2", "slack"),
                                                            ("slack:U1", "slack")]
    # "Yangi suhbat" - faqat bosgan odamniki; boshqasining suhbati joyida.
    assert service.chat_reset(user, ready, asker="slack:U2") == {"archived": 1}
    assert rt.store.chat_turns(ready, asker="slack:U2") == []
    assert [t["question"] for t in rt.store.chat_turns(ready, asker="slack:U1")] == [
        "A-SAVOL: kim qaysi vazifani oldi?", "Batafsilroq"]
    service.chat_send(user, ready, "Yana?", None, channel="slack", asker="slack:U1")
    assert len(claude.chats()[-1]["messages"]) == 5                             # U1 ning ikki navbati xotirada
    service.chat_send(user, ready, "Qaytadan?", None, channel="slack", asker="slack:U2")
    assert len(claude.chats()[-1]["messages"]) == 1
    assert service.chat_reset(user, ready, asker="slack:U1") == {"archived": 3}
    assert [t["question"] for t in rt.store.chat_turns(ready, asker="slack:U2")] == ["Qaytadan?"]


def test_sorovchi_kaliti_ochiq_matn_qirqiladi_bosh_kalit_egasi(client, auth, ready, claude, _isolated_meetings):
    rt = _isolated_meetings
    user = _owner(rt, ready)
    assert chat.asker_of("  slack:U1\n") == "slack:U1" and chat.asker_of("x" * 150) == "x" * chat.ASKER_CHARS
    assert chat.asker_of(None) is None and chat.asker_of("") is None and chat.asker_of("   ") is None
    long = service.chat_send(user, ready, "Uzun kalit?", None, channel="slack", asker="y" * 150)
    blank = service.chat_send(user, ready, "Bo'sh kalit?", None, channel="slack", asker="   ")
    stored = {r["id"]: r["asker"] for r in rt.store.rows("SELECT id, asker FROM questions")}
    assert stored == {long["id"]: "y" * 100, blank["id"]: None}
    assert len(claude.chats()[-1]["messages"]) == 1                             # bo'sh kalit - egasining suhbati
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [blank["id"]]


def test_ega_va_sorovchi_bir_birining_xotirasi_va_royxatiga_kirmaydi(client, auth, ready, claude,
                                                                      _isolated_meetings):
    """Hisob egasi (ilova, `POST /chat`) va Slack odami bitta yozuv bo'yicha so'rasa: egasining savoli Slack odamining
    promptiga bormaydi va aksincha; `GET /chat` va eski `/questions` - faqat egasiniki. HTTP API `asker` olmaydi."""
    rt = _isolated_meetings
    user = _owner(rt, ready)
    own = _say(client, auth, ready, "EGA-MAXFIY: bonus kimga?", asker="slack:U1")       # tanadagi `asker` e'tiborsiz
    assert rt.store.row("SELECT asker FROM questions WHERE id=?", (own["id"],))["asker"] is None
    slack = service.chat_send(user, ready, "Kim kelishdi?", None, channel="slack", asker="slack:U1")
    to_slack = claude.chats()[-1]
    assert len(to_slack["messages"]) == 1 and "EGA-MAXFIY" not in json.dumps(to_slack, ensure_ascii=False)
    follow = _say(client, auth, ready, "Batafsilroq?")
    back = claude.chats()[-1]
    assert [m["role"] for m in back["messages"]] == ["user", "assistant", "user"]
    assert "EGA-MAXFIY" in back["messages"][0]["content"] and "Kim kelishdi" not in json.dumps(back,
                                                                                               ensure_ascii=False)
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [own["id"], follow["id"]]
    listed = client.get(f"/api/v1/meetings/{ready}/questions", headers=auth).json()["items"]
    assert [q["id"] for q in listed] == [follow["id"], own["id"]]
    # Egasining "Yangi suhbat"i (`DELETE /chat`) Slack odamiga tegmaydi.
    assert client.delete(_url(ready), headers=auth).json() == {"archived": 2}
    assert [t["id"] for t in rt.store.chat_turns(ready, asker="slack:U1")] == [slack["id"]]


# --- qayta o'girish va javob kutilayotgandagi "Yangi suhbat" ------------------------------------------------


def test_qayta_ogirish_hamma_sorovchining_suhbatini_arxivlaydi(client, auth, ready, claude, _isolated_meetings):
    """Qayta o'girishdan keyin eski javoblarning manba id lari yangi matnda boshqa qatorni ko'rsatadi: hamma
    so'rovchining faol navbatlari arxivga (yumshoq), keyingi savol xotirasiz."""
    rt = _isolated_meetings
    user = _owner(rt, ready)
    _say(client, auth, ready, "Hisobotni kim yuboradi?")
    service.chat_send(user, ready, "Budjet qancha?", None, channel="slack", asker="slack:U1")
    response = client.post(f"/api/v1/meetings/{ready}/retranscribe", headers=auth,
                           json={"language": "ru", "confirmCharge": True})
    assert response.status_code == 202, response.text
    assert client.get(_url(ready), headers=auth).json()["items"] == []          # o'girish paytida ham
    run_all(rt)
    assert rt.store.meeting_any(ready)["stt_engine"] == "router"
    assert client.get(_url(ready), headers=auth).json()["items"] == []
    assert client.get(f"/api/v1/meetings/{ready}/questions", headers=auth).json()["items"] == []
    assert rt.store.chat_turns(ready, asker="slack:U1") == []
    _say(client, auth, ready, "U qachon yuboradi?")
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user"]
    service.chat_send(user, ready, "Yana?", None, channel="slack", asker="slack:U1")
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user"]
    rows = rt.store.rows("SELECT archived_at FROM questions WHERE meeting_id=?", (ready,))
    assert len(rows) == 4 and sum(r["archived_at"] is not None for r in rows) == 2


def test_javob_kutilayotganda_yangi_suhbat_navbat_arxivda_tugaydi(client, auth, ready, claude, _isolated_meetings):
    """Claude javob yozayotganda «🔄 Yangi suhbat» bosildi: javob baribir qaytadi, lekin u eski suhbat ustiga
    qurilgan - navbat o'sha tozalash vaqti bilan arxivda tug'iladi va yangi suhbatga xotira bo'lib o'tmaydi."""
    rt = _isolated_meetings
    user = _owner(rt, ready)
    _say(client, auth, ready, "Birinchi savol?")

    def during(request):
        assert [m["role"] for m in request["messages"]] == ["user", "assistant", "user"]
        assert service.chat_reset(user, ready) == {"archived": 1}
        return json.dumps({"answer": "Yuqoridagiga qo'shimcha: [S1] hisobot.", "citations": [1],
                           "followUps": ["a", "b", "c"]})

    claude.script = [during]
    late = _say(client, auth, ready, "Batafsilroq?")
    assert late["answer"] == "Yuqoridagiga qo'shimcha: [S1] hisobot."
    assert client.get(_url(ready), headers=auth).json()["items"] == []
    first, second = rt.store.rows("SELECT archived_at FROM questions WHERE meeting_id=? ORDER BY created_at, rowid",
                                  (ready,))
    assert first["archived_at"] is not None and second["archived_at"] == first["archived_at"]
    _say(client, auth, ready, "Yangi mavzu?")
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user"]
    # Nazorat (vaqt qoidasi emas): tozalashdan darhol keyin (odatda o'sha soniyada) berilgan savol - faol.
    assert service.chat_reset(user, ready) == {"archived": 1}
    again = service.chat_send(user, ready, "Darhol keyingi savol?", None)
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [again["id"]]


def test_boshqa_sorovchi_tozalasa_kutilayotgan_javob_faol_qoladi(client, auth, ready, claude, _isolated_meetings):
    rt = _isolated_meetings
    user = _owner(rt, ready)
    service.chat_send(user, ready, "U1 savoli?", None, channel="slack", asker="slack:U1")
    service.chat_send(user, ready, "U2 savoli?", None, channel="slack", asker="slack:U2")

    def during(request):
        assert service.chat_reset(user, ready, asker="slack:U2") == {"archived": 1}     # boshqa odam
        return json.dumps({"answer": "[S1] davomi.", "citations": [1], "followUps": ["a", "b", "c"]})

    claude.script = [during]
    service.chat_send(user, ready, "Batafsilroq?", None, channel="slack", asker="slack:U1")
    assert [t["question"] for t in rt.store.chat_turns(ready, asker="slack:U1")] == ["U1 savoli?", "Batafsilroq?"]
    assert rt.store.chat_turns(ready, asker="slack:U2") == []


def test_javob_kutilayotganda_yozuv_ochirilsa_404(client, auth, ready, claude, _isolated_meetings):
    rt = _isolated_meetings
    user = _owner(rt, ready)

    def during(request):
        service.delete(user, ready)                      # boshqa qurilmadan / saqlash muddati
        return json.dumps({"answer": "[S1] javob.", "citations": [1], "followUps": ["a", "b", "c"]})

    claude.script = [during]
    response = client.post(_url(ready), headers=auth, json={"message": "Kim?"})
    assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert rt.store.scalar("SELECT COUNT(*) FROM questions") == 0


def _old_text_reply(request) -> str:
    return json.dumps({"answer": "ESKI-MATN: [S1] hisobotni ertaga yuboradi.", "citations": [1],
                       "followUps": ["Qachon?", "Kimga?", "Nima uchun?"]})


def test_birinchi_savol_kutilayotganda_qayta_ogirish_navbat_arxivda(client, auth, ready, claude, _isolated_meetings):
    """Suhbatning BIRINCHI savoli (xotira yo'q - "Yangi suhbat" qoidasi ushlamaydi) Claude'da turganda yozuv qayta
    o'girishga yuborildi: javob qaytadi (odam so'ragan edi), lekin u ESKI matn bo'yicha - navbat arxivda tug'iladi;
    yangi matn tayyor bo'lgach ham chat bo'sh, keyingi savol xotirasiz."""
    rt = _isolated_meetings
    user = _owner(rt, ready)

    def during(request):
        assert [m["role"] for m in request["messages"]] == ["user"]                  # xotira yo'q
        service.retranscribe(user, ready, schemas.RetranscribeRequest(language="ru", confirmCharge=True))
        return _old_text_reply(request)

    claude.script = [during]
    late = _say(client, auth, ready, "Hisobotni kim yuboradi?")
    assert late["answer"].startswith("ESKI-MATN") and late["citations"][0]["segmentId"] == 1
    assert rt.store.row("SELECT archived_at FROM questions WHERE id=?", (late["id"],))["archived_at"] is not None
    run_all(rt)                                                                       # yangi matn tayyor
    assert service._transcript_ready(rt.store.meeting_any(ready))
    assert client.get(_url(ready), headers=auth).json()["items"] == []
    assert client.get(f"/api/v1/meetings/{ready}/questions", headers=auth).json()["items"] == []
    _say(client, auth, ready, "Batafsilroq?")
    nxt = claude.chats()[-1]
    assert [m["role"] for m in nxt["messages"]] == ["user"] and "ESKI-MATN" not in json.dumps(nxt, ensure_ascii=False)


def test_qayta_ogirish_javob_kutilayotganda_tugasa_ham_navbat_arxivda(client, auth, ready, claude,
                                                                      _isolated_meetings):
    """Qayta o'girish javob kutilayotganda boshlanib TUGAB ham ulgurdi (holat yana tayyor): buni faqat transkript
    avlodi (`transcript_gen`) ko'radi - navbat baribir arxivda. Nazorat: matn o'zgarmasa keyingi savol faol."""
    rt = _isolated_meetings
    user = _owner(rt, ready)
    gen = int(rt.store.meeting_any(ready)["transcript_gen"])

    def during(request):
        service.retranscribe(user, ready, schemas.RetranscribeRequest(language="ru", confirmCharge=True))
        run_all(rt)
        m = rt.store.meeting_any(ready)
        assert service._transcript_ready(m) and int(m["transcript_gen"]) > gen        # yana tayyor, avlod boshqa
        return _old_text_reply(request)

    claude.script = [during]
    late = _say(client, auth, ready, "Hisobotni kim yuboradi?")
    assert rt.store.row("SELECT archived_at FROM questions WHERE id=?", (late["id"],))["archived_at"] is not None
    assert client.get(_url(ready), headers=auth).json()["items"] == []
    fresh = _say(client, auth, ready, "Yangi matn bo'yicha kim?")
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [fresh["id"]]


def test_javob_kutilayotganda_qator_tahriri_va_birlashtirish_navbatga_tegmaydi(client, auth, ready, claude,
                                                                               _isolated_meetings):
    """Javob kutilayotganda egasi Matn tabida qatorni tuzatdi va ikki spikerni birlashtirdi: `transcript_rev` oshadi,
    lekin transkript almashmagan (`transcript_gen` o'sha, qator id lari o'sha, manbalar to'g'ri) - navbat FAOL
    qoladi, ro'yxatda turadi va keyingi savolga xotira bo'lib boradi."""
    rt = _isolated_meetings
    user = _owner(rt, ready)
    first = _say(client, auth, ready, "Hisobotni kim yuboradi?")
    before = rt.store.meeting_any(ready)

    def during(request):
        service.edit_segment(user, ready, 2, schemas.SegmentPatchRequest(text="Tuzatilgan matn"))
        service.merge_speakers(user, ready, ["S3"], "S1")
        m = rt.store.meeting_any(ready)
        assert int(m["transcript_rev"]) == int(before["transcript_rev"]) + 2
        assert int(m["transcript_gen"]) == int(before["transcript_gen"]) and service._transcript_ready(m)
        return json.dumps({"answer": "[S1] ertaga yuboradi.", "citations": [1], "followUps": ["a", "b", "c"]})

    claude.script = [during]
    late = _say(client, auth, ready, "Qachon?")
    assert rt.store.row("SELECT archived_at FROM questions WHERE id=?", (late["id"],))["archived_at"] is None
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [first["id"], late["id"]]
    _say(client, auth, ready, "Batafsilroq?")
    assert [m["role"] for m in claude.chats()[-1]["messages"]] == ["user", "assistant", "user", "assistant", "user"]


# --- idempotentlik: klient kaliti (`clientId`) ------------------------------------------------------------


def test_bir_xil_kalit_bitta_navbat_modelga_bir_marta_chegara_olinmaydi(client, auth, ready, claude, monkeypatch,
                                                                        _isolated_meetings):
    """Ilova noaniq xatodan (proksi 504, uzilgan ulanish) keyin o'sha `clientId` bilan qayta yubordi: javob allaqachon
    saqlangan - O'SHA navbat qaytadi; Claude'ga ikkinchi so'rov yo'q, soatlik chegaradan token olinmaydi."""
    monkeypatch.setattr(settings, "meetings_ask_per_hour", 1)
    service.reset_limits()
    first = _say(client, auth, ready, "Hisobotni kim yuboradi?", clientId=KEY, channel="mobile")
    again = _say(client, auth, ready, "Hisobotni kim yuboradi?", clientId=KEY, channel="mobile")
    assert again == first and set(first) == TURN_FIELDS and first["clientId"] == KEY
    assert len(claude.chats()) == 1
    # Chegara (1/soat) birinchi xabarga ketdi: takror token olmadi, yangi kalitli xabar esa - 429.
    limited = client.post(_url(ready), headers=auth, json={"message": "Yana?", "clientId": "m2-other-key"})
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    items = client.get(_url(ready), headers=auth).json()["items"]
    assert [(t["id"], t["clientId"]) for t in items] == [(first["id"], KEY)]
    assert _isolated_meetings.store.scalar("SELECT COUNT(*) FROM questions") == 1


def test_parallel_takror_birinchisini_kutadi_va_otsha_navbatni_oladi(client, auth, ready, claude, waiting,
                                                                     _isolated_meetings):
    """Birinchi so'rov hali Claude javobini kutyapti (soxta model ichida), ilova o'sha kalit bilan qayta yubordi:
    ikkinchisi modelga bormaydi - birinchisini kutib turadi va O'SHA navbatni oladi."""
    second: dict = {}

    def during(request):
        second["thread"], second["box"] = _in_background(
            lambda: client.post(_url(ready), headers=auth, json={"message": "Kim yuboradi?", "clientId": KEY}))
        assert waiting.wait(10)                                    # ikkinchisi kutyapti - endi javob beriladi
        assert "box" in second and not second["box"]               # ... va hali qaytmagan
        return json.dumps({"answer": "[S1] hisobotni ertaga yuboradi.", "citations": [1],
                           "followUps": ["Qachon?", "Kimga?", "Nima uchun?"]})

    claude.script = [during]
    first = _say(client, auth, ready, "Kim yuboradi?", clientId=KEY)
    second["thread"].join(10)
    response = second["box"]["value"]
    assert response.status_code == 200 and response.json() == first
    assert len(claude.chats()) == 1
    assert _isolated_meetings.store.scalar("SELECT COUNT(*) FROM questions") == 1
    assert chat._flights == {}                                     # kalit bo'shadi


def test_kalitni_egallagach_saqlangan_navbat_qayta_tekshiriladi(client, auth, ready, claude, monkeypatch):
    """Tekshiruv ("navbat yo'q") bilan kalitni egallash orasida oldingi urinish saqlab, kalitni bo'shatdi: egasi
    bo'lgan so'rov modelga bormasdan O'SHA navbatni oladi."""
    first = _say(client, auth, ready, "Kim yuboradi?", clientId=KEY)
    real, calls = store_mod.MeetingStore.turn_by_client, []

    def late(self, *args, **kwargs):
        calls.append(args)
        return None if len(calls) == 1 else real(self, *args, **kwargs)        # birinchi qarash - hali yo'q edi

    monkeypatch.setattr(store_mod.MeetingStore, "turn_by_client", late)
    assert _say(client, auth, ready, "Kim yuboradi?", clientId=KEY) == first
    assert len(calls) == 2 and len(claude.chats()) == 1 and chat._flights == {}


def test_birinchi_urinish_503_bolsa_otsha_kalit_bilan_yangi_urinish(client, auth, ready, claude, _isolated_meetings):
    claude.script = [claude_error(anthropic.APITimeoutError)]
    failed = client.post(_url(ready), headers=auth, json={"message": "Kim yuboradi?", "clientId": KEY})
    assert failed.status_code == 503 and failed.json()["code"] == "llm_unavailable"
    retried = _say(client, auth, ready, "Kim yuboradi?", clientId=KEY)
    assert retried["clientId"] == KEY and len(claude.chats()) == 2
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [retried["id"]]
    assert chat._flights == {}


def test_kutayotgan_takror_birinchisi_yiqilsa_ozi_urinadi(client, auth, ready, claude, waiting, _isolated_meetings):
    """Birinchi urinish (ikkinchisi uni kutib turganda) 503 bilan yiqildi: hech narsa saqlanmagan - kutgan so'rov
    o'zi oddiy urinish qiladi va javob oladi (bitta navbat)."""
    second: dict = {}

    def failing(request):
        second["thread"], second["box"] = _in_background(
            lambda: client.post(_url(ready), headers=auth, json={"message": "Kim yuboradi?", "clientId": KEY}))
        assert waiting.wait(10)
        return claude_error(anthropic.APITimeoutError)

    claude.script = [failing]
    failed = client.post(_url(ready), headers=auth, json={"message": "Kim yuboradi?", "clientId": KEY})
    assert failed.status_code == 503
    second["thread"].join(10)
    response = second["box"]["value"]
    assert response.status_code == 200 and response.json()["clientId"] == KEY
    assert len(claude.chats()) == 2
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [response.json()["id"]]


def test_turli_kalit_va_kalitsiz_alohida_navbat(client, auth, ready, claude):
    one = _say(client, auth, ready, "Kim yuboradi?", clientId="k-aaaa-0001")
    two = _say(client, auth, ready, "Kim yuboradi?", clientId="k-aaaa-0002")
    plain = _say(client, auth, ready, "Kim yuboradi?")                       # kalitsiz - har so'rov yangi
    again = _say(client, auth, ready, "Kim yuboradi?", clientId=None)
    assert len({one["id"], two["id"], plain["id"], again["id"]}) == 4 and len(claude.chats()) == 4
    assert [t["clientId"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [
        "k-aaaa-0001", "k-aaaa-0002", None, None]


def test_kalit_yigilish_va_sorovchi_doirasida(client, auth, ready, claude, _isolated_meetings):
    """Kalit (yig'ilish, so'rovchi, kalit) bo'yicha: boshqa yig'ilishda yoki boshqa so'rovchida o'sha kalit - boshqa
    navbat; har doirada takror - o'sha navbat. Egasining server kanallari (`asker` siz) HTTP bilan bir doira."""
    rt = _isolated_meetings
    other, _ = recorded(client, auth)
    run_all(rt)
    user = _owner(rt, ready)
    own = _say(client, auth, ready, "Kim?", clientId=KEY)
    elsewhere = _say(client, auth, other["id"], "Kim?", clientId=KEY)
    u1 = service.chat_send(user, ready, "Kim?", None, channel="slack", asker="slack:U1", client_id=KEY)
    u2 = service.chat_send(user, ready, "Kim?", None, channel="slack", asker="slack:U2", client_id=KEY)
    assert len({own["id"], elsewhere["id"], u1["id"], u2["id"]}) == 4 and len(claude.chats()) == 4
    assert service.chat_send(user, ready, "Kim?", None, channel="slack", asker="slack:U1", client_id=KEY) == u1
    assert _say(client, auth, other["id"], "Kim?", clientId=KEY)["id"] == elsewhere["id"]
    assert service.chat_send(user, ready, "Kim?", None, channel="telegram", client_id=KEY)["id"] == own["id"]
    assert len(claude.chats()) == 4
    stored = rt.store.rows("SELECT asker, client_id FROM questions WHERE meeting_id=? ORDER BY created_at, rowid",
                           (ready,))
    assert [(r["asker"], r["client_id"]) for r in stored] == [(None, KEY), ("slack:U1", KEY), ("slack:U2", KEY)]


@pytest.mark.parametrize("key", ["short12", "x" * 65, "kalit bor", "kalit/123", "kalit.123", "абвгдежзик",
                                 "abcdefgh\n", "", 12345678])
def test_yaroqsiz_klient_kaliti_422(client, auth, ready, claude, key):
    response = client.post(_url(ready), headers=auth, json={"message": "salom", "clientId": key})
    assert response.status_code == 422, key
    assert claude.requests == []


def test_klient_kaliti_chegaralari_qabul(client, auth, ready, claude):
    for key in ("a" * 8, ("Az09_-" * 11)[:64]):
        assert _say(client, auth, ready, "Kim?", clientId=key)["clientId"] == key
    assert _say(client, auth, ready, "Kim?", clientId=None)["clientId"] is None


def test_arxivdagi_navbat_kalitni_band_qilmaydi(client, auth, ready, claude, _isolated_meetings):
    """"Yangi suhbat" dan keyin o'sha kalit - yangi navbat (arxivdagisi qaytmaydi va xotiraga ham kirmaydi)."""
    first = _say(client, auth, ready, "Kim yuboradi?", clientId=KEY)
    assert client.delete(_url(ready), headers=auth).json() == {"archived": 1}
    again = _say(client, auth, ready, "Kim yuboradi?", clientId=KEY)
    assert again["id"] != first["id"] and again["clientId"] == KEY and len(claude.chats()) == 2
    assert len(claude.chats()[-1]["messages"]) == 1
    assert [t["id"] for t in client.get(_url(ready), headers=auth).json()["items"]] == [again["id"]]


# --- xatolar --------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {}, {"message": ""}, {"message": "   "}, {"message": "x" * 1001}, {"message": "salom", "channel": "slack"},
    {"message": "salom", "language": "de"}, {"message": "salom", "intent": "create"},
    {"message": "salom", "intent": "rewrite"}, {"message": "salom", "minutesLanguage": "uz"},
    {"message": "salom", "minutesLanguage": "de"},
])
def test_xabar_tekshiruvi_422(client, auth, ready, claude, body):
    response = client.post(_url(ready), headers=auth, json=body)
    assert response.status_code == 422, body
    assert claude.requests == []


def test_uzun_xabar_chegarada_qabul(client, auth, ready, claude):
    body = _say(client, auth, ready, "x" * 1000)
    assert body["question"] == "x" * 1000 and claude.chats()[0]["messages"][-1]["content"].endswith("x" * 1000)


def test_boshqa_odam_404_va_transkriptsiz_409(client, auth, user_auth, monkeypatch, ready, claude):
    enable(monkeypatch)
    for method, kwargs in (("get", {}), ("post", {"json": {"message": "salom"}}), ("delete", {})):
        response = getattr(client, method)(_url(ready), headers=user_auth, **kwargs)
        assert response.status_code == 404 and response.json()["code"] == "not_found", method
    assert client.get(_url("nope"), headers=auth).status_code == 404
    pending = create_meeting(client, auth)                                       # yuklanmagan - transkript yo'q
    response = client.post(_url(pending["id"]), headers=auth, json={"message": "salom"})
    assert response.status_code == 409 and response.json()["code"] == "not_ready"
    # Tarix va "Yangi suhbat" transkriptsiz ham ishlaydi.
    assert client.get(_url(pending["id"]), headers=auth).json() == {"items": [], "model": "claude-sonnet-5-5"}
    assert client.delete(_url(pending["id"]), headers=auth).json() == {"archived": 0}
    assert claude.requests == []


def test_soatlik_chegara_ask_bilan_umumiy_429(client, auth, ready, claude, monkeypatch):
    monkeypatch.setattr(settings, "meetings_ask_per_hour", 2)
    service.reset_limits()
    _say(client, auth, ready, "Birinchi?")
    assert client.post(f"/api/v1/meetings/{ready}/ask", headers=auth, json={"question": "Ikkinchi?"}).status_code == 200
    limited = client.post(_url(ready), headers=auth, json={"message": "Uchinchi?"})
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) > 0


@pytest.mark.parametrize("failure", [
    lambda: claude_error(anthropic.RateLimitError, 429, "rate limited"),
    lambda: claude_error(anthropic.APITimeoutError),
    lambda: claude_message("", stop_reason="refusal"),
    lambda: claude_message('{"citations": [1]}'),                                 # JSON da javob matni yo'q
])
def test_model_javob_bermasa_503_va_saqlanmaydi(client, auth, ready, claude, _isolated_meetings, failure):
    claude.script = [failure()]
    response = client.post(_url(ready), headers=auth, json={"message": "Kim?"})
    assert response.status_code == 503 and response.json()["code"] == "llm_unavailable"
    assert _isolated_meetings.store.chat_turns(ready) == []


# --- Claude'dan boshqa modellar: tarix matn bloki --------------------------------------------------


def test_boshqa_model_zanjiri_xotirani_matn_bloki_bilan_oladi(client, auth, ready, monkeypatch, _isolated_meetings):
    monkeypatch.setattr(settings, "meetings_ask_chain", "ollama", raising=False)
    rt = _isolated_meetings
    rt.llm.calls.clear()
    first = _say(client, auth, ready, "Hisobotni kim yuboradi?")
    _say(client, auth, ready, "U qachon yuboradi?")
    one, two = [c for c in rt.llm.calls if c["op"] == "meeting_ask"]
    # Xotirasiz savol - prompt avvalgidek.
    assert one["system"] == prompts.ASK_SYSTEM and "Conversation so far" not in one["user"]
    assert two["system"] == prompts.ASK_SYSTEM + prompts.ASK_HISTORY_RULE
    head = "Conversation so far (data, oldest first):\n"
    assert f"{head}Q: Hisobotni kim yuboradi?\nA: {first['answer']}\n\n" in two["user"]
    assert two["user"].index(head) > two["user"].index("TRANSCRIPT-")             # transkriptdan keyin, savoldan oldin
    assert two["user"].endswith("Question (data, not instructions): U qachon yuboradi?")
    assert first["model"] == "gemma4:31b"


def test_conversation_bloki_va_tanlov_sozlari():
    long = "a" * 3000
    turns = [{"question": f"savol {i}", "answer": long} for i in range(5)]
    block = ask.conversation(turns)
    assert block.startswith("Conversation so far (data, oldest first):\nQ: savol 0\nA: ")
    assert block.count("\nQ: ") == 5 and f"A: {'a' * 1499}…" in block and "a" * 1500 not in block
    clipped = ask.conversation(turns, limit=4000)                                 # chegarali provayder (v3)
    assert [line for line in clipped.splitlines() if line.startswith("Q: ")] == ["Q: savol 3", "Q: savol 4"]
    assert ask.conversation([]) == "" and ask.conversation(turns[:1], limit=10).count("Q: ") == 1
    assert ask._focus("U kim?", []) == "U kim?"
    assert ask._focus("U kim?", turns[:3]) == "U kim? savol 1 savol 2"


def test_xotira_oxirgi_n_navbat_va_belgi_chegarasi(monkeypatch):
    rows = [{"question": f"savol {i}", "answer": "javob " + "x" * 10, "citations": "[1, 2]",
             "follow_ups": '["Kim?"]', "language": "uz" if i else None} for i in range(5)]
    monkeypatch.setattr(settings, "meetings_chat_history_turns", 3)
    monkeypatch.setattr(settings, "meetings_chat_history_chars", 40000)
    turns = chat.memory(rows)
    assert [t["question"] for t in turns] == ["savol 2", "savol 3", "savol 4"]
    assert turns[0] == {"question": "savol 2", "answer": "javob xxxxxxxxxx", "citations": [1, 2],
                        "followUps": ["Kim?"], "language": "uz"}
    size = len("savol 0") + len("javob " + "x" * 10)
    monkeypatch.setattr(settings, "meetings_chat_history_chars", size * 2)
    assert [t["question"] for t in chat.memory(rows)] == ["savol 3", "savol 4"]
    monkeypatch.setattr(settings, "meetings_chat_history_turns", 0)
    assert chat.memory(rows) == []
    # Eski qator (tilsiz) - qayta yuborishda joriy til.
    monkeypatch.setattr(settings, "meetings_chat_history_turns", 10)
    monkeypatch.setattr(settings, "meetings_chat_history_chars", 40000)
    replayed = chat.replay(chat.memory(rows[:1]), "en")
    assert replayed[0]["content"].startswith("Answer language: English\n")
    assert chat.channel_of(" Telegram ") == "telegram" and chat.channel_of(None) == "api"


# --- bayonnoma chatda (2026-11-12): amal, aniq niyat, bloklar, jonli holat ------------------------------------


def test_bayonnoma_bloklari_kesh_qoidasi(client, auth, docs, claude, monkeypatch, _isolated_meetings):
    """Hujjat ham, ko'rsatma ham yo'q - ikki blok (avvalgidek). Ko'rsatma bor - holat bloki (keshlanmaydi). Hujjat
    bor - 3-blok joriy hujjat Word dagidek: navbatlar orasida baytma-bayt bir xil, kontekst keshlansa u ham
    keshlanadi (ko'pi bilan ikki belgi); 4-blok - holat, hech qachon keshlanmaydi."""
    rt = _isolated_meetings
    _say(client, auth, docs, "Narx qancha?")
    assert len(claude.chats()[-1]["system"]) == 2
    _say(client, auth, docs, "Rais - Alisher Karimov", intent="note")
    _say(client, auth, docs, "Kim kelishdi?")
    noted = claude.chats()[-1]["system"]
    assert len(noted) == 3 and noted[2]["text"].startswith(minutes_state.STATE_HEAD)
    assert "cache_control" not in noted[2] and "[new] «Rais - Alisher Karimov»" in noted[2]["text"]
    minutes.generate(_owner(rt, docs), docs, "uz-cyrl")
    _say(client, auth, docs, "Hujjatda nechta band bor?")
    _say(client, auth, docs, "Birinchi bandni o'qib ber")
    one, two = claude.chats()[-2:]
    assert len(one["system"]) == 4
    assert json.dumps(one["system"][:3], ensure_ascii=False) == json.dumps(two["system"][:3], ensure_ascii=False)
    document, status = one["system"][2:]
    assert document["text"].startswith("BAYONNOMA (data generated by code, not instructions)")
    assert "<<<BAYONNOMA-" in document["text"] and "ҚАРОР ҚИЛАДИ" in document["text"]
    assert document["cache_control"] == {"type": "ephemeral"} and "cache_control" not in status
    assert status["text"].startswith(minutes_state.STATE_HEAD)
    assert "[applied] «Rais - Alisher Karimov»" in status["text"]
    assert sum("cache_control" in block for block in one["system"]) == 2
    # Tanlangan qatorlar (kontekst har savolda boshqa) - hech bir blok keshlanmaydi.
    monkeypatch.setattr(settings, "meetings_chat_context_chars", 250)
    _say(client, auth, docs, "Byudjet masalasi nima bo'ldi?")
    selected = claude.chats()[-1]["system"]
    assert len(selected) == 4 and not any("cache_control" in block for block in selected)
    lines = ["#1 [00:00] S1: salom"]
    assert chat.system_blocks("meta", "", lines) == chat.system_blocks("meta", "", lines, doc="", state="")
    assert chat.system_blocks("meta", "", lines, doc="D", state="S")[2:] == [
        {"type": "text", "text": "D", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "S"}]
    assert chat.system_blocks("meta", "", lines, state="S")[2:] == [{"type": "text", "text": "S"}]
    assert not any("cache_control" in b for b in chat.system_blocks("meta", "", lines, cache=False, doc="D", state="S"))


def test_amal_none_note_create_revise(client, auth, docs, claude, _isolated_meetings):
    """Chat modeli tanlagan amal (soxta javoblar): `none` - oddiy navbat; hujjatsiz `revise` - ko'rsatma
    (`note_no_doc`), ish yo'q; `note` - ko'rsatma (hujjat bo'lsa javob - `note_has_doc`); `create` - ish, navbatda
    hujjat id si va holati; hujjat bor `revise` - tahrir qatori (egasining so'zlari + model talqini); yangi
    ko'rsatmasiz `create` - tayyori qayta yuboriladi, bepul."""
    rt = _isolated_meetings
    claude.script = [chat_reply()]
    plain = _say(client, auth, docs, "Hisobotni kim yuboradi?")
    assert (plain["kind"], plain["minutes"]) == ("chat", None)
    assert rt.store.turn(docs, plain["id"])["kind"] is None                      # oddiy navbat - `kind` NULL
    claude.script = [chat_reply("revise", instruction="Raisni Karimov deb yozish")]
    early = _say(client, auth, docs, "Raisni Karimov deb yozing")
    assert (early["kind"], early["answer"]) == ("note", chat.CANNED["note_no_doc"]["uz"])
    assert early["minutes"] == {"action": "note", "language": "uz-cyrl", "id": None, "status": None, "version": None,
                                "notes": 1, "error": None}
    claude.script = [chat_reply("note", instruction="Kredit masalalariga e'tibor berish")]
    noted = _say(client, auth, docs, "Kredit masalalariga alohida e'tibor bering")
    assert (noted["kind"], noted["answer"], noted["minutes"]["notes"]) == ("note", CHAT_ACTION_ANSWER, 2)
    assert rt.store.minutes_rows(docs) == [] and _minutes_calls(rt) == []
    claude.script = [chat_reply("create")]
    made = _say(client, auth, docs, "Bayonnoma tayyorlab ber")
    assert (made["kind"], made["answer"]) == ("create", CHAT_ACTION_ANSWER)
    [row] = rt.store.minutes_rows(docs)
    assert made["minutes"] == {"action": "create", "language": "uz-cyrl", "id": row["id"], "status": "ready",
                               "version": 1, "notes": None, "error": None}
    assert row["turn_id"] == made["id"] and rt.store.turn(docs, made["id"])["minutes_id"] == row["id"]
    [call] = _minutes_calls(rt)
    assert call["op"] == "meeting_minutes" and "OWNER INSTRUCTIONS" in call["user"]
    assert "1. Raisni Karimov deb yozing" in call["user"] and "2. Kredit masalalariga alohida" in call["user"]
    claude.script = [chat_reply("note", instruction="Kotib - Bobur")]
    later = _say(client, auth, docs, "Kotib - Bobur")
    assert (later["kind"], later["answer"]) == ("note", chat.CANNED["note_has_doc"]["uz"])
    claude.script = [chat_reply("revise", instruction="Sarlavhani «Yangi sarlavha» qilish")]
    edited = _say(client, auth, docs, "TITLE=Yangi sarlavha")
    assert (edited["kind"], edited["answer"]) == ("revise", CHAT_ACTION_ANSWER)
    revision = rt.store.minutes_by_turn(edited["id"])
    assert (revision["parent_id"], revision["revision"], revision["status"]) == (row["id"], 1, "ready")
    assert jload(revision["request_json"]) == {"text": "TITLE=Yangi sarlavha",
                                               "instruction": "Sarlavhani «Yangi sarlavha» qilish"}
    assert edited["minutes"] == {"action": "revise", "language": "uz-cyrl", "id": revision["id"], "status": "ready",
                                 "version": 2, "notes": None, "error": None}
    call = _minutes_calls(rt)[-1]
    assert call["op"] == "meeting_minutes_revise" and "Assistant's reading" in call["user"]
    assert "[new] Kotib - Bobur" in call["user"] and jload(revision["content_json"])["title"] == "Yangi sarlavha"
    # Yangi ko'rsatma yo'q - "tayyorla" tayyorini qayta yuboradi: yangi qator ham, model chaqiruvi ham yo'q.
    claude.script = [chat_reply("create")]
    again = _say(client, auth, docs, "Bayonnomani yana yubor")
    assert again["minutes"]["id"] == revision["id"] and again["minutes"]["version"] == 2
    assert len(rt.store.minutes_rows(docs)) == 2 and len(_minutes_calls(rt)) == 2
    # Butun suhbat bitta: keyingi savolda amalli navbatlar ham xotirada (o'z amali bilan).
    _say(client, auth, docs, "Nimalarni o'zgartirdik?")
    replayed = [json.loads(m["content"]) for m in claude.chats()[-1]["messages"] if m["role"] == "assistant"]
    assert [r["minutes"]["action"] for r in replayed] == ["none", "note", "note", "create", "note", "revise", "create"]


def test_aniq_niyat_modelsiz(client, auth, docs, claude, monkeypatch, _isolated_meetings):
    """Aniq kirish nuqtasi (`intent`): chat modeli ham, "ask" soatlik chegarasi ham yo'q. Ko'rsatma - darhol
    (tayyor javob, so'rov tilida); o'zgartirish - tahrir ishi (tahrir chegarasi bilan). Slack odamining ko'rsatmasi
    faqat o'ziniki."""
    rt = _isolated_meetings
    monkeypatch.setattr(settings, "meetings_ask_per_hour", 1)
    service.reset_limits()
    note = _say(client, auth, docs, "Rais - Alisher Karimov", intent="note", channel="mobile")
    assert (note["kind"], note["answer"], note["model"], note["citations"], note["followUps"]) == (
        "note", chat.CANNED["note"]["uz"], None, [], [])
    assert note["minutes"] == {"action": "note", "language": None, "id": None, "status": None, "version": None,
                               "notes": 1, "error": None}
    ru = _say(client, auth, docs, "Kredit masalalariga e'tibor bering", intent="note", language="ru")
    assert (ru["answer"], ru["minutes"]["notes"]) == (chat.CANNED["note"]["ru"], 2)
    head = minutes.generate(_owner(rt, docs), docs, "uz-cyrl")
    assert head["notesApplied"] == 2
    later = _say(client, auth, docs, "Kotib - Bobur", intent="note")
    assert later["answer"] == chat.CANNED["note_has_doc"]["uz"]
    edit = _say(client, auth, docs, "TITLE=Yangi sarlavha", intent="revise", minutesLanguage="uz-cyrl")
    assert (edit["kind"], edit["answer"]) == ("revise", chat.CANNED["revise"]["uz"])
    row = rt.store.minutes_row(docs, edit["minutes"]["id"])
    assert edit["minutes"] == {"action": "revise", "language": "uz-cyrl", "id": row["id"], "status": "ready",
                               "version": 2, "notes": None, "error": None}
    assert (row["parent_id"], row["turn_id"], jload(row["request_json"])) == (
        head["id"], edit["id"], {"text": "TITLE=Yangi sarlavha", "instruction": None})
    assert claude.chats() == []                                                  # chat modeli chaqirilmadi
    # "ask" chegarasi (1/soat) olinmagan: model javob beradigan birinchi xabar o'tadi, ikkinchisi - 429.
    _say(client, auth, docs, "Narx qancha?")
    assert client.post(_url(docs), headers=auth, json={"message": "Yana?"}).status_code == 429
    # Slack odami (umumiy hisob): ko'rsatma faqat o'ziniki - egasining ko'rsatmalari va ro'yxatiga kirmaydi.
    user = _owner(rt, docs)
    slack = service.chat_send(user, docs, "Qatnashchilar: boshqaruv a'zolari", None, channel="slack",
                              asker="slack:U1", intent=" NOTE ")
    assert (slack["kind"], slack["minutes"]["notes"]) == ("note", 1)
    assert len(rt.store.notes(docs)) == 3 and len(rt.store.notes(docs, asker="slack:U1")) == 1
    assert slack["id"] not in [t["id"] for t in client.get(_url(docs), headers=auth).json()["items"]]
    # Noma'lum niyat va til - e'tiborsiz (server ichidan): oddiy navbat, chegara esa allaqachon tugagan.
    with pytest.raises(service.MeetingProblem) as limited:
        service.chat_send(user, docs, "Yana?", None, intent="rewrite", minutes_lang="de")
    assert limited.value.status_code == 429


def test_arxivda_tugilgan_navbat_ish_boshlamaydi(client, auth, docs, claude, _isolated_meetings):
    """"Tayyorla" javobi yozilayotganda «Yangi suhbat» bosildi: navbat arxivda tug'iladi va pullik ish
    BOSHLANMAYDI (qator ham, model chaqiruvi ham yo'q)."""
    rt = _isolated_meetings
    user = _owner(rt, docs)
    _say(client, auth, docs, "Birinchi savol?")

    def during(request):
        assert service.chat_reset(user, docs) == {"archived": 1}
        return chat_reply("create")

    claude.script = [during]
    late = _say(client, auth, docs, "Bayonnoma tayyorla")
    assert late["kind"] == "create" and late["minutes"]["id"] is None and late["minutes"]["error"] is None
    assert rt.store.turn(docs, late["id"])["archived_at"] is not None
    assert rt.store.minutes_rows(docs) == [] and _minutes_calls(rt) == []


def test_clientId_takror_bitta_ish(client, auth, docs, claude, _isolated_meetings):
    """Ilova o'sha `clientId` bilan qayta yubordi: o'sha navbat (jonli holat bilan), chat modeliga ham, bayonnoma
    modeliga ham ikkinchi so'rov yo'q - bitta navbat, bitta ish (aniq tahrirda ham)."""
    rt = _isolated_meetings
    claude.script = [chat_reply("create")]
    first = _say(client, auth, docs, "Bayonnoma tayyorla", clientId=KEY)
    again = _say(client, auth, docs, "Bayonnoma tayyorla", clientId=KEY)
    assert again == first and first["minutes"]["status"] == "ready"
    assert len(claude.chats()) == 1 and len(rt.store.minutes_rows(docs)) == 1 and len(_minutes_calls(rt)) == 1
    edit = _say(client, auth, docs, "TITLE=Bir marta", intent="revise", clientId="k-edit-0001")
    assert _say(client, auth, docs, "TITLE=Bir marta", intent="revise", clientId="k-edit-0001") == edit
    assert len(rt.store.minutes_rows(docs)) == 2 and len(_minutes_calls(rt)) == 2 and chat._flights == {}


def test_ish_boshlanmasa_200_va_xato(client, auth, docs, claude, monkeypatch, _isolated_meetings):
    """Ish boshlanmadi (tahrir chegarasi tugagan, bayonnoma modeli sozlanmagan): chat baribir 200, navbat saqlanadi -
    sabab `minutes.error` da (`id` yo'q), javob - `not_started`."""
    rt = _isolated_meetings
    monkeypatch.setattr(settings, "meetings_minutes_edits_per_hour", 1, raising=False)
    service.reset_limits()
    minutes.generate(_owner(rt, docs), docs, "uz-cyrl")
    first = _say(client, auth, docs, "TITLE=Birinchi", intent="revise")
    assert first["minutes"]["status"] == "ready" and first["minutes"]["error"] is None
    second = _say(client, auth, docs, "TITLE=Ikkinchi", intent="revise", language="en")
    assert second["answer"] == chat.CANNED["not_started"]["en"]
    assert second["minutes"] == {"action": "revise", "language": "uz-cyrl", "id": None, "status": None,
                                 "version": None, "notes": None,
                                 "error": {"code": "rate_limited",
                                           "message": "So'rovlar ko'p - birozdan keyin qayta urinib ko'ring"}}
    assert jload(rt.store.turn(docs, second["id"])["minutes_json"])["error"]["code"] == "rate_limited"
    assert len(rt.store.minutes_rows(docs)) == 2                                 # yangi qator yo'q
    # Model tanlagan "tayyorla", lekin bayonnoma modeli sozlanmagan (Claude kaliti yo'q) - 503 emas, 200 + sabab.
    monkeypatch.setattr(settings, "meetings_minutes_chain", "claude", raising=False)
    claude.script = [chat_reply("create", language="ru")]
    made = _say(client, auth, docs, "Ruscha bayonnoma tayyorla")
    assert (made["kind"], made["answer"]) == ("create", chat.CANNED["not_started"]["uz"])
    assert made["minutes"]["language"] == "ru" and made["minutes"]["error"]["code"] == "llm_not_configured"
    listed = client.get(_url(docs), headers=auth).json()["items"]
    assert [t["minutes"]["error"]["code"] for t in listed[-2:]] == ["rate_limited", "llm_not_configured"]


def test_eski_ask_amalsiz(client, auth, docs, claude, _isolated_meetings):
    """Eski `/ask` (va `service.ask`) - faqat savol-javob: model amal tanlasa ham ish yo'q, navbat oddiy, bayonnoma
    bloklari yuborilmaydi."""
    rt = _isolated_meetings
    minutes.generate(_owner(rt, docs), docs, "uz-cyrl")
    _say(client, auth, docs, "Rais - Alisher Karimov", intent="note")
    claude.script = [chat_reply("revise", instruction="Sarlavhani o'zgartirish")]
    response = client.post(f"/api/v1/meetings/{docs}/ask", headers=auth, json={"question": "Sarlavhani o'zgartir"})
    assert response.status_code == 200 and set(response.json()) == ASK_FIELDS
    row = rt.store.turn(docs, response.json()["id"])
    assert (row["kind"], row["minutes_json"], row["minutes_id"]) == (None, None, None)
    assert len(claude.chats()[-1]["system"]) == 2
    # Model bayonnoma ishini va'da qilmasin - amallar o'chiq (oddiy chatda bu qo'shimcha yo'q).
    assert claude.chats()[-1]["system"][0]["text"] == f"{prompts.CHAT_SYSTEM}\n\n{prompts.CHAT_MINUTES_OFF}"
    claude.script = [chat_reply()]
    _say(client, auth, docs, "Hisobotni kim yuboradi?")
    assert claude.chats()[-1]["system"][0]["text"] == prompts.CHAT_SYSTEM
    claude.script = [chat_reply("create")]
    legacy = service.ask(_owner(rt, docs), docs, "Bayonnoma tayyorla", None)
    assert (legacy["kind"], legacy["minutes"]) == ("chat", None)
    assert len(rt.store.minutes_rows(docs)) == 1 and len(_minutes_calls(rt)) == 1


def test_get_chat_jonli_holat(client, auth, docs, claude, monkeypatch, _isolated_meetings):
    """`GET /chat` navbatdagi hujjatning JONLI holatini beradi: yozilmoqda -> tayyor; tahrirda model yiqildi -
    `REVISE_FAILED`; yozayotgan ip o'lgan (eskirgan `running`) - `interrupted`."""
    rt = _isolated_meetings
    minutes.generate(_owner(rt, docs), docs, "uz-cyrl")
    queue: list = []
    monkeypatch.setattr(minutes, "runner", queue.append)
    turn = _say(client, auth, docs, "TITLE=Jonli", intent="revise")
    assert (turn["minutes"]["status"], turn["minutes"]["version"]) == ("running", 2)
    [listed] = client.get(_url(docs), headers=auth).json()["items"]
    assert listed["minutes"] == turn["minutes"] and set(listed) == TURN_FIELDS
    while queue:
        queue.pop(0)()
    [listed] = client.get(_url(docs), headers=auth).json()["items"]
    assert (listed["minutes"]["status"], listed["minutes"]["version"], listed["minutes"]["error"]) == ("ready", 2, None)
    rt.llm.script["meeting_minutes_revise"] = ["javob JSON emas"]
    _say(client, auth, docs, "TITLE=Yomon", intent="revise")
    while queue:
        queue.pop(0)()
    failed = client.get(_url(docs), headers=auth).json()["items"][-1]
    assert failed["minutes"]["status"] == "failed"
    assert failed["minutes"]["error"] == {"code": "llm_failed", "message": minutes.REVISE_FAILED}
    stuck = _say(client, auth, docs, "TITLE=Osilgan", intent="revise")           # navbatda qoldi
    rt.store.update_minutes(stuck["minutes"]["id"], created_at=int(time.time() - minutes.stale_after() - 60))
    stale = client.get(_url(docs), headers=auth).json()["items"][-1]
    assert stale["minutes"]["status"] == "failed"
    assert stale["minutes"]["error"] == {"code": "interrupted", "message": minutes.INTERRUPTED}


def test_qayta_ogirish_korsatmani_saqlaydi_reset_tozalaydi(client, auth, docs, claude, _isolated_meetings):
    """Qayta o'girish savol-javoblarni arxivlaydi, ko'rsatmalar (`kind='note'`) QOLADI: eski matn hujjati
    tahrirlanmaydi (sabab navbatda, 200), yangi hujjat ko'rsatma bilan yoziladi. «Yangi suhbat» ko'rsatmalarni ham
    arxivlaydi, hujjatlar qoladi."""
    rt = _isolated_meetings
    note = _say(client, auth, docs, "Rais - Alisher Karimov", intent="note")
    _say(client, auth, docs, "Hisobotni kim yuboradi?")
    # Ko'rsatma bergan "tayyorla" (talqinli `create`) ham ko'rsatma - qoladi; talqinsizi - arxivga.
    claude.script = [chat_reply("create", instruction="Kotib - Bobur Aliyev")]
    guided = _say(client, auth, docs, "Bayonnomani tayyorla, kotib - Bobur Aliyev")
    claude.script = [chat_reply("create")]
    _say(client, auth, docs, "Bayonnomani yana yubor")
    head = minutes.generate(_owner(rt, docs), docs, "uz-cyrl")
    response = client.post(f"/api/v1/meetings/{docs}/retranscribe", headers=auth,
                           json={"language": "ru", "confirmCharge": True})
    assert response.status_code == 202, response.text
    run_all(rt)
    kept, kept_create = client.get(_url(docs), headers=auth).json()["items"]
    assert (kept["id"], kept["kind"], kept["minutes"]["notes"]) == (note["id"], "note", 2)
    assert (kept_create["id"], kept_create["kind"]) == (guided["id"], "create")
    assert [n["text"] for n in rt.store.notes(docs)] == ["Rais - Alisher Karimov",
                                                          "Bayonnomani tayyorla, kotib - Bobur Aliyev"]
    stale = _say(client, auth, docs, "TITLE=Eski", intent="revise", minutesLanguage="uz-cyrl")
    assert stale["minutes"]["error"]["code"] == "minutes_outdated" and stale["minutes"]["id"] is None
    assert stale["answer"] == chat.CANNED["not_started"]["ru"]                   # yozuv endi ruscha - javob tili ham
    claude.script = [chat_reply("create")]
    made = _say(client, auth, docs, "Bayonnomani qaytadan tayyorla")
    assert made["minutes"]["status"] == "ready" and made["minutes"]["id"] != head["id"]
    assert "Rais - Alisher Karimov" in _minutes_calls(rt)[-1]["user"]
    assert "kotib - Bobur Aliyev" in _minutes_calls(rt)[-1]["user"]
    assert client.delete(_url(docs), headers=auth).json() == {"archived": 4}
    assert rt.store.notes(docs) == [] and len(rt.store.minutes_rows(docs)) >= 2            # hujjatlar qoladi


def test_ikki_yozuv_aralashmaydi(client, auth, docs, claude, _isolated_meetings):
    """Bitta audio - bitta suhbat: A yozuvidagi ko'rsatma B ning bayonnoma promptiga ham, B chatining bloklariga ham
    kirmaydi (va aksincha); hujjat bloki faqat o'z yozuviniki."""
    rt = _isolated_meetings
    other, _ = recorded(client, auth)
    run_all(rt)
    b = other["id"]
    _say(client, auth, docs, "A-KO'RSATMA: rais Karimov", intent="note")
    claude.script = [chat_reply("create")]
    made = _say(client, auth, b, "Bayonnoma tayyorla")
    assert made["minutes"]["status"] == "ready"
    prompt_b = _minutes_calls(rt)[-1]["user"]
    assert "A-KO'RSATMA" not in prompt_b and "OWNER INSTRUCTIONS" not in prompt_b
    _say(client, auth, b, "B-KO'RSATMA: kredit bo'limi", intent="note")
    _say(client, auth, b, "Hujjatda nima bor?")
    to_b = claude.chats()[-1]
    assert len(to_b["system"]) == 4 and "B-KO'RSATMA" in to_b["system"][3]["text"]
    assert "A-KO'RSATMA" not in json.dumps(to_b, ensure_ascii=False)
    _say(client, auth, docs, "Ko'rsatmalarim qaysi?")
    to_a = claude.chats()[-1]
    assert len(to_a["system"]) == 3 and "A-KO'RSATMA" in to_a["system"][2]["text"]     # A da hujjat yo'q
    assert "B-KO'RSATMA" not in json.dumps(to_a, ensure_ascii=False)
    assert [n["text"] for n in rt.store.notes(docs)] == ["A-KO'RSATMA: rais Karimov"]
    assert [n["text"] for n in rt.store.notes(b)] == ["B-KO'RSATMA: kredit bo'limi"]
    assert rt.store.minutes_rows(docs) == []


def test_memory_eski_qator_ozgarmaydi(monkeypatch):
    """Eski (v8 dan oldingi) va oddiy navbat xotirada avvalgi shaklda; amalli navbatda yana `kind` va `minutes`.
    Qayta yuborishda (`replay`) amal faqat amal, til va talqin (xatosiz); amalsiz - `none`."""
    monkeypatch.setattr(settings, "meetings_chat_history_turns", 10)
    monkeypatch.setattr(settings, "meetings_chat_history_chars", 40000)
    legacy = {"question": "Kim?", "answer": "[S1].", "citations": "[1]", "follow_ups": '["Qachon?"]', "language": "uz"}
    plain = {**legacy, "kind": None, "minutes_json": None}
    noted = {**legacy, "question": "Rais - Karimov", "answer": "Eslab qolindi.", "citations": "[]",
             "follow_ups": "[]", "kind": "note",
             "minutes_json": json.dumps({"action": "note", "language": "uz-cyrl", "instruction": "Rais Karimov",
                                         "error": {"code": "rate_limited", "message": "x"}})}
    old, same, note = chat.memory([legacy, plain, noted])
    assert old == {"question": "Kim?", "answer": "[S1].", "citations": [1], "followUps": ["Qachon?"], "language": "uz"}
    assert same == old
    assert (note["kind"], note["minutes"]["instruction"]) == ("note", "Rais Karimov")
    replayed = chat.replay([old, note], "uz")
    assert json.loads(replayed[1]["content"])["minutes"] == NO_ACTION
    assert json.loads(replayed[3]["content"]) == {
        "minutes": {"action": "note", "language": "uz-cyrl", "instruction": "Rais Karimov"},
        "answer": "Eslab qolindi.", "citations": [], "followUps": []}


def test_minutes_action_tahlili():
    """Model javobidagi amal: `{"result": ...}` o'rami, noma'lum / `none` / kalitsiz / JSON emas - `None`, til
    `minutes.text.normalize` (yolg'iz "uz" - yozuvi noma'lum, `None`), talqin bir qatorga va chegaraga."""
    def parsed(minutes_value, *, wrap=False):
        body = {"minutes": minutes_value, "answer": "ok", "citations": [], "followUps": []}
        return chat.minutes_action(json.dumps({"result": body} if wrap else body, ensure_ascii=False))

    assert parsed({"action": "Revise", "language": "UZ_CYRL", "instruction": "  3-band:\n muddat\t1-dekabr "}) == {
        "action": "revise", "language": "uz-cyrl", "instruction": "3-band: muddat 1-dekabr"}
    assert parsed({"action": "note", "language": None, "instruction": None}, wrap=True) == {
        "action": "note", "language": None, "instruction": None}
    for odd in ({"action": "none"}, {"action": "delete"}, {"action": None}, {}, "create", None):
        assert parsed(odd) is None, odd
    assert chat.minutes_action("Bu JSON emas") is None
    assert chat.minutes_action('{"answer": "ok", "citations": [], "followUps": []}') is None
    langs = {"cyrl": "uz-cyrl", "uz-latn": "uz-latn", "RU": "ru", "en": "en", "uz": None, "de": None, "": None}
    for raw, code in langs.items():
        assert parsed({"action": "create", "language": raw, "instruction": None})["language"] == code, raw
    long = parsed({"action": "revise", "language": None, "instruction": "x" * 1500})["instruction"]
    assert len(long) == chat.INSTRUCTION_CHARS and long.endswith("…")
    assert parsed({"action": "revise", "language": None, "instruction": {"bad": 1}})["instruction"] is None
    assert parsed({"action": "create", "language": None, "instruction": "   "})["instruction"] is None


def test_boshqa_provayder_aniq_tahrir(client, auth, docs, monkeypatch, _isolated_meetings):
    """Claude'dan boshqa chat zanjiri (Ollama): aniq `intent="revise"` baribir tahrirlaydi (chat modelisiz); model
    javob bergan navbat esa amalsiz - Ollama amal qaytarmaydi."""
    monkeypatch.setattr(settings, "meetings_ask_chain", "ollama", raising=False)
    rt = _isolated_meetings
    minutes.generate(_owner(rt, docs), docs, "uz-cyrl")
    rt.llm.calls.clear()
    edited = _say(client, auth, docs, "TITLE=Ollama tahriri", intent="revise")
    assert (edited["minutes"]["status"], edited["minutes"]["version"]) == ("ready", 2)
    assert rt.llm.ops() == ["meeting_minutes_revise"]
    assert jload(rt.store.minutes_row(docs, edited["minutes"]["id"])["content_json"])["title"] == "Ollama tahriri"
    plain = _say(client, auth, docs, "ACTION=revise sarlavhani o'zgartir")
    assert (plain["kind"], plain["minutes"]) == ("chat", None) and rt.llm.ops()[-1] == "meeting_ask"
    assert len(rt.store.minutes_rows(docs)) == 2


# --- ombor: v7 ------------------------------------------------------------------------------------


def test_migratsiya_v6_dan_v7_ga_savollar_bilan(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    conn = sqlite3.connect(root / "meetings.db")
    for step in store_mod.MIGRATIONS[:6]:
        for statement in step:
            conn.execute(statement)
    now = int(time.time())
    conn.execute("INSERT INTO meetings (id, actor_id, client_id, created_at, updated_at, status) "
                 "VALUES ('m1', 7, 'c1', ?, ?, 'ready')", (now, now))
    conn.execute("INSERT INTO questions (id, meeting_id, question, answer, citations, follow_ups, created_at) "
                 "VALUES ('q1', 'm1', 'Kim?', '[S1] yuboradi.', '[1]', '[]', ?)", (now - 5,))
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()

    st = MeetingStore(root)
    assert st.version() == store_mod.SCHEMA_VERSION == 9
    columns = {r["name"] for r in st.rows("PRAGMA table_info(questions)")}
    assert {"channel", "model", "language", "archived_at", "asker", "client_id"} <= columns
    [index] = [r for r in st.rows("PRAGMA index_list(questions)") if r["name"] == "questions_client"]
    assert [r["name"] for r in st.rows("PRAGMA index_info(questions_client)")] == ["meeting_id", "client_id"]
    assert not index["unique"]                                       # arxivdagi navbatda o'sha kalit qolishi mumkin
    assert st.meeting_any("m1")["transcript_gen"] == 0               # yangi ustun, eski yozuvda 0
    [old] = st.chat_turns("m1")                                      # eski qator - hisob egasiniki
    assert (old["id"], old["channel"], old["model"], old["language"], old["archived_at"], old["asker"],
            old["client_id"]) == ("q1", None, None, None, None, None, None)
    for qid in ("q2", "q3"):                                         # bir soniyada - qo'shilish tartibi
        st.add_question({"id": qid, "meeting_id": "m1", "question": "?", "answer": "!", "channel": "mobile",
                         "model": "claude-sonnet-5-5", "language": "uz", "created_at": now})
    assert [q["id"] for q in st.chat_turns("m1")] == ["q1", "q2", "q3"]
    assert [q["id"] for q in st.chat_turns("m1", limit=2)] == ["q2", "q3"]
    assert [q["id"] for q in st.questions("m1")] == ["q3", "q2", "q1"]
    assert st.archive_questions("m1", now) == 3 and st.chat_turns("m1") == [] and st.questions("m1") == []
    assert st.scalar("SELECT COUNT(*) FROM questions WHERE archived_at = ?", (now,)) == 3   # yumshoq: qatorlar qoladi
    assert st.archive_questions("m1", now + 1) == 0
    st.close_all()


def test_bot_tayyor_javoblari_ozbekcha(client, auth, docs, claude, _isolated_meetings):
    """Botlar (Slack, Telegram) interfeysi o'zbekcha: tayyor javoblar yig'ilish tili rus bo'lsa ham o'zbekcha (bot o'z
    qatorini o'zbekcha qo'shadi - bitta xabarda ikki til aralashmasin); ilova (REST) - so'rov tilida."""
    rt = _isolated_meetings
    rt.store.execute("UPDATE meetings SET language='ru' WHERE id=?", (docs,))
    user = _owner(rt, docs)
    for channel, asker in (("telegram", None), ("slack", "slack:U1")):
        turn = service.chat_send(user, docs, "Rais - Karimov", None, channel=channel, asker=asker, intent="note")
        assert turn["answer"] == chat.CANNED["note"]["uz"]
    app = _say(client, auth, docs, "Rais - Karimov", intent="note", language="ru")
    assert app["answer"] == chat.CANNED["note"]["ru"]


def test_model_ozbek_yozuvini_adashtirsa_mavjud_hujjat_tahrirlanadi(client, auth, docs, claude, _isolated_meetings):
    """Model lotin harfli xabarga "uz-latn" desa, hujjat esa kirillda: mavjud (kirill) hujjat tahrirlanadi - so'rov
    "bu tilda hujjat yo'q" deb ko'rsatmaga aylanmaydi. Aniq aytilgan boshqa til (rus) - o'zgarmaydi."""
    rt = _isolated_meetings
    claude.script = [chat_reply("create")]
    made = _say(client, auth, docs, "Bayonnoma tayyorlab ber")
    assert (made["minutes"]["language"], made["minutes"]["status"]) == ("uz-cyrl", "ready")
    claude.script = [chat_reply("revise", language="uz-latn", instruction="Sarlavhani o'zgartirish")]
    edited = _say(client, auth, docs, "TITLE=Yangi sarlavha")
    assert (edited["kind"], edited["minutes"]["language"], edited["minutes"]["version"]) == ("revise", "uz-cyrl", 2)
    claude.script = [chat_reply("revise", language="ru", instruction="Ruscha hujjatda sarlavhani o'zgartirish")]
    russian = _say(client, auth, docs, "Ruscha bayonnomada sarlavhani o'zgartiring")
    assert (russian["kind"], russian["answer"]) == ("note", chat.CANNED["note_no_doc"]["uz"])
    assert len(_minutes_calls(rt)) == 2

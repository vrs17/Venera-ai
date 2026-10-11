"""Migratsiya W1 (2026-10-11): agent jamoasining HAQIQIY v4 javobiga moslash.

Tekshiriladi:
  * egasining qarori - Ollama Cloud (`external_models_allowed: true`) + bizning jonli kalit
    (`AGENT_V4_ALLOW_EXTERNAL_MODELS`) himoyadan o'tkazadi; kalit o'chsa - yana `local`;
  * guruh CRM suhbatini HAQIQIY o'chirish (`DELETE /api/v4/chats/{id}?mode=purge`):
    imkoniyat bo'lmasa - eski yumshoq yo'l; 404 - o'chgan; agent ishlamasa - tozalovchi
    keyinroq qayta uradi (yumshoq o'chirishga tushmaydi).
Tarmoqqa chiqilmaydi (`FakeAgent`).
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from app.core.config import settings
from app.services.brain import routing
from app.services.integrations.assistant import AssistantError
from tests.agent_fakes import FULL_CAPS, FakeAgent, enable_agent

#: Agent jamoasining 2026-10-11 dagi haqiqiy javobi shakli: ichki tarmoq modeli yo'q,
#: egasi Ollama Cloud'ga ruxsat bergan.
CLOUD_CAPS = {**FULL_CAPS, "in_network_models_only": False, "external_models_allowed": True,
              "models": {"in_network": None, "external": ["gemma4:31b-cloud (Ollama Cloud)"]},
              "features": {**FULL_CAPS["features"], "chat_purge": True}}


def _purge_path(chat_id: str, user_id: str) -> str:
    return (f"/chats/{quote(chat_id, safe='')}?user_id={quote(user_id, safe='')}"
            "&mode=purge&forget_learned=true")


# ================================================================ tashqi model qoidasi


def test_ollama_cloud_egasi_ruxsati_bilan_otadi(_isolated_analytics, monkeypatch):
    fake = FakeAgent()
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS, group_summary="shadow")
    route = routing.route("group_summary")
    assert (route.effective, route.reason) == ("shadow", None)
    assert routing.capabilities().get().view()["externalAllowed"] is True


def test_kalit_ochsa_yana_local(_isolated_analytics, monkeypatch):
    fake = FakeAgent()
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS, group_summary="agent")
    # Kalit `.env` da bo'lmasa sozlama qiymati olinadi (`_env_flag`, jonli o'qish).
    monkeypatch.setattr(settings, "agent_v4_allow_external_models", False)
    assert routing.route("group_summary").reason == "not_in_network"


def test_tashqi_ruxsat_yoq_bolsa_local(_isolated_analytics, monkeypatch):
    fake = FakeAgent()
    caps = {**CLOUD_CAPS, "external_models_allowed": False}
    enable_agent(monkeypatch, fake, caps=caps, group_summary="agent")
    assert routing.route("group_summary").reason == "not_in_network"


# ================================================================ haqiqiy o'chirish


def test_purge_imkoniyat_yoq_bolsa_none(_isolated_analytics, monkeypatch):
    fake = FakeAgent()
    caps = {**CLOUD_CAPS, "features": {**CLOUD_CAPS["features"], "chat_purge": False}}
    enable_agent(monkeypatch, fake, caps=caps)
    assert routing.purge_chat("tgcrm-abc", "venera:3") is None
    assert not [p for p in fake.paths() if p.startswith("/chats/")]


def test_purge_agent_ochiq_bolsa_none(_isolated_analytics, monkeypatch):
    routing.reset_for_tests()
    assert routing.purge_chat("tgcrm-abc", "venera:3") is None


def test_purge_kvitansiya_bilan(_isolated_analytics, monkeypatch):
    fake = FakeAgent()
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS)
    path = _purge_path("tgcrm-abc", "venera:3")
    receipt = {"alg": "hmac-sha256", "sig": "ab" * 32}
    fake.handlers[path] = lambda body: {"chat_id": "tgcrm-abc", "turns_purged": 2, "learned_forgotten": 0,
                                        "receipt": receipt}
    out = routing.purge_chat("tgcrm-abc", "venera:3")
    assert out["receipt"] == receipt
    [call] = [c for c in fake.calls if c["path"] == path]
    assert call["method"] == "DELETE" and call["body"] is None


def test_purge_404_ochgan_hisoblanadi(_isolated_analytics, monkeypatch):
    fake = FakeAgent()
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS)
    # Ishlovchi yo'q - soxta agent 404 qaytaradi.
    assert routing.purge_chat("tgcrm-yoq", "venera:3") == {}


@pytest.mark.parametrize(("status", "down"), [(503, True), (429, True), (403, False)])
def test_purge_xatosi_tozalovchiga_qayta_urinish(_isolated_analytics, monkeypatch, status, down):
    fake = FakeAgent()
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS)
    path = _purge_path("tgcrm-abc", "venera:3")
    fake.handlers[path] = lambda body: (status, {"error": {"code": "x", "message": "m", "retryable": down}})
    with pytest.raises(AssistantError) as info:
        routing.purge_chat("tgcrm-abc", "venera:3")
    assert info.value.retryable is down
    assert (info.value.status == 503) is down


def test_runner_forget_chat_avval_purge_keyin_yumshoq(_isolated_analytics, monkeypatch):
    from app.api.v1 import chat as _chat
    from app.bot.runner import Backend

    soft: list[tuple[str, str]] = []
    monkeypatch.setattr(_chat._assistant, "delete_chat", lambda chat_id, *, user_id: soft.append((chat_id, user_id)))
    backend = Backend.__new__(Backend)
    # v4 o'chirish bor - yumshoq yo'lga TUSHILMAYDI.
    fake = FakeAgent()
    enable_agent(monkeypatch, fake, caps=CLOUD_CAPS)
    fake.handlers[_purge_path("tgcrm-a", "venera:3")] = lambda body: {"receipt": {"sig": "x"}}
    backend.forget_chat("tgcrm-a", "venera:3")
    assert soft == []
    # v4 o'chirish yo'q (agent o'chiq) - avvalgidek yumshoq.
    routing.reset_for_tests()
    backend.forget_chat("tgcrm-b", "venera:3")
    assert soft == [("tgcrm-b", "venera:3")]

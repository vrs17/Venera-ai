"""Ovoz uchun matn agentdan (`POST /speech`, flag `tts_speech`).

Muammo: OmniVoice normalizatori vergulni minglik ajratuvchi deb o'qiydi - "40,98 trln"
"to'rt ming to'qson sakkiz" bo'lib, "-0,2%" minussiz chiqardi. Agent raqamlarni o'zbekcha
so'z bilan yozadi; javob kelmasa yoki kechiksa - bugungi yo'l, ovoz baribir chiqadi.
"""

from __future__ import annotations

import pytest

from app.services.brain import routing
from app.services.integrations.agent_v4 import AgentError
from app.services.tts import TtsClient, TtsError, prepare_speech

BANK = "Aktivlar: 40,98 trln so'm; kamaygan (-0,2%)."
SPOKEN = "Aktivlar: qirq trillion to'qqiz yuz sakson milliard so'm; kamaygan (minus nol butun o'ndan ikki foiz)."


def test_agent_matni_ishlatiladi_va_izda_korinadi():
    seen: list[str] = []

    def speakable(text):
        seen.append(text)
        return SPOKEN, {"route": "agent", "reason": None}

    trace: list[dict] = []
    out = prepare_speech(BANK, max_chars=3000, speakable=speakable, trace=trace)
    assert out.text == SPOKEN
    # Agentga bizning tayyorlangan matn ketadi (lug'at va sana bosqichidan KEYIN).
    assert seen == [BANK]
    stage = next(s for s in trace if s["stage"] == "agent_speech")
    assert stage["used"] is True and stage["route"] == "agent"
    # Normalizator xavfi agent matnida tekshiriladi va oxirgi bosqich bo'lib qoladi.
    assert trace[-1]["stage"] == "risky_for_normalizer"


@pytest.mark.parametrize("behaviour", ["none", "raise"])
def test_agent_javob_bermasa_bugungi_yol(behaviour):
    def speakable(text):
        if behaviour == "raise":
            raise RuntimeError("kutilmagan")
        return None, {"route": "local", "reason": None}

    trace: list[dict] = []
    out = prepare_speech(BANK, max_chars=3000, speakable=speakable, trace=trace)
    assert out.text == prepare_speech(BANK, max_chars=3000).text
    stage = next(s for s in trace if s["stage"] == "agent_speech")
    assert stage["used"] is False


def test_bosh_matn_agentga_bormaydi():
    called = []
    with pytest.raises(TtsError):
        prepare_speech("   ", max_chars=3000, speakable=lambda t: called.append(t) or (None, {}))
    assert called == []


def test_klient_prepare_hookni_uzatadi():
    client = TtsClient("http://tts.test", "id", "secret",
                       speakable=lambda text: ("bir ikki uch", {"route": "agent", "reason": None}))
    assert client.prepare("1 2 3", max_chars=3000).text == "bir ikki uch"


class _FakeAgent:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def speech(self, text, *, lang="uz_latn", timeout=None):
        self.calls.append((text, lang))
        if self.error:
            raise self.error
        return self.result


def _route(effective):
    return routing.Route(feature="tts_speech", configured=effective, effective=effective, source="admin",
                         sample_rate=0.0, reason=None if effective == "agent" else "capability_missing:speech")


def test_routing_local_agentni_chaqirmaydi(monkeypatch):
    fake = _FakeAgent({"text": SPOKEN})
    monkeypatch.setattr(routing, "route", lambda name: _route("local"))
    monkeypatch.setattr(routing, "client", lambda name="interactive": fake)
    text, info = routing.speakable(BANK)
    assert text is None and info["route"] == "local" and fake.calls == []


def test_routing_agent_matn_qaytaradi(monkeypatch):
    fake = _FakeAgent({"text": SPOKEN + "  ", "lang": "uz_latn"})
    names = []
    monkeypatch.setattr(routing, "route", lambda name: _route("agent"))
    monkeypatch.setattr(routing, "client", lambda name="interactive": names.append(name) or fake)
    text, info = routing.speakable(BANK)
    assert text == SPOKEN and info["route"] == "agent"
    # O'z mijozi (qisqa kutish, alohida uzgich) - umumiy `interactive` emas.
    assert names == ["speech"] and fake.calls == [(BANK, "uz_latn")]


@pytest.mark.parametrize("fake, code", [
    (_FakeAgent(error=AgentError("timeout", code="network", retryable=True)), "network"),
    (_FakeAgent({"text": ""}), "bad_response"),
    (_FakeAgent({"text": "x" * 50_000}), "bad_response"),
    (_FakeAgent({"nima": 1}), "bad_response"),
])
def test_routing_agent_xatosida_bugungi_yol(monkeypatch, fake, code):
    monkeypatch.setattr(routing, "route", lambda name: _route("agent"))
    monkeypatch.setattr(routing, "client", lambda name="interactive": fake)
    text, info = routing.speakable(BANK)
    assert text is None and info["error"] == code


def test_speech_mijozi_ozining_uzgichi_bilan():
    built = routing._build("speech")
    assert built.breaker is not routing._shared_breaker()
    assert built.name == "speech"


def test_needs_speech_imkoniyati():
    assert routing.NEEDS["tts_speech"]["agent"] == ("speech",)


def test_modelsiz_funksiya_tashqi_model_qoidasiga_bogliq_emas(monkeypatch, _isolated_analytics):
    """`/speech` modelga yubormaydi: tashqi modellar o'chiq va agent "ichki tarmoq" demasa
    ham `tts_speech` agentga boradi; model ishlatadigan funksiya esa `local` qoladi."""
    from tests.agent_fakes import FULL_CAPS, FakeAgent, enable_agent

    caps = {**FULL_CAPS, "in_network_models_only": False}
    enable_agent(monkeypatch, FakeAgent(), caps=caps, tts_speech="agent", group_summary="agent")
    monkeypatch.setattr(routing._config, "agent_v4_external_models_now", lambda: False)
    assert routing.route("tts_speech").effective == "agent"
    blocked = routing.route("group_summary")
    assert (blocked.effective, blocked.reason) == ("local", "not_in_network")

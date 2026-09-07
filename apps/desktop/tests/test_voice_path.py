"""Ovoz yo'li: mikrofon -> tinglovchi -> STT -> intent -> harakat.

Bu fayl AYNAN ulanishni tekshiradi. `listener` berilmasa orchestrator eski
matn yo'lida qolishi shart - `test_orchestrator.py` shunga tayanadi va u
fayl bu yerda TEGILMAYDI.
"""

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from venera import config as config_module
from venera import events as ev
from venera.actions import apps as apps_module
from venera.actions import phrases as phrases_module
from venera.actions.base import ActionContext
from venera.core.orchestrator import Orchestrator
from venera.core.states import State
from venera.engines.llm_rules import RulesLlm
from venera.engines.stt_mock import MockStt
from venera.engines.tts_sapi import NullTts
from tests.test_actions import FakeAdapter
from tests.test_orchestrator import Collector, FakePlayer

WAV = b"RIFF____WAVEfmt short-but-not-empty"


class FakeCapture:
    """`start()` muvaffaqiyatli - qulf testida tiklanishni ko'rish uchun."""

    def __init__(self):
        self.running = False
        self.device = None
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1
        self.running = True
        return True

    def stop(self):
        self.stops += 1
        self.running = False

    def drain(self): pass
    def reopen(self, rescan=True): return False
    def is_alive(self, tolerance=2.0): return True
    def seconds_since_audio(self): return 0.0
    def record(self, seconds, drain_first=True): return np.zeros(0, dtype=np.int16)


class FakeListener:
    """`AudioListener` ning shartnomasi: running/start/stop/pause/resume +
    bloklovchi `capture_utterance(timeout, cancel)`."""

    error = ""

    def __init__(self, wav=WAV, block=False):
        self.running = True
        self.wav = wav
        self.block = block            # True = cancel/timeout kutadi
        self.calls = []
        self.pauses = 0
        self.resumes = 0
        self.starts = 0
        self.stops = 0
        self.cancelled = threading.Event()
        self.entered = threading.Event()

    def start(self):
        self.starts += 1
        self.running = True
        return True

    def stop(self):
        self.stops += 1
        self.running = False

    def pause(self):
        self.pauses += 1

    def resume(self):
        self.resumes += 1

    def capture_utterance(self, timeout, cancel):
        self.calls.append(timeout)
        self.entered.set()
        if not self.block:
            return self.wav
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                self.cancelled.set()
                return b""
            time.sleep(0.01)
        return b""


class FakeStt:
    """`submit_text` ATAYLAB yo'q: `_transcribe()` uni ko'rmasa matnni
    o'zgarishsiz o'tkazadi - ovoz rejimida aynan shu kerak."""

    name = "fake"

    def __init__(self, text="chromeni och", error=None):
        self.text = text
        self.error = error
        self.seen = []

    async def transcribe(self, wav_bytes):
        self.seen.append(wav_bytes)
        if self.error is not None:
            raise self.error
        return self.text

    async def close(self):
        return None


def build(listener=None, stt=None, capture=None, capturing=1.0):
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    cfg.timeouts.capturing = capturing
    cfg.timeouts.stt = 2.0
    adapter = FakeAdapter()
    player = FakePlayer()
    collector = Collector()
    ctx = ActionContext(adapter=adapter, config=cfg,
                        phrases=phrases_module.Phrases.load(), catalog=apps_module.load())
    orch = Orchestrator(
        config=cfg, adapter=adapter, stt=stt or MockStt(), llm=RulesLlm(), tts=NullTts(),
        activator=None, capture=capture or FakeCapture(), player=player,
        context=ctx, on_event=collector, listener=listener,
    )
    return orch, adapter, player, collector


@pytest.fixture
def voice():
    listener = FakeListener()
    stt = FakeStt()
    orch, adapter, player, collector = build(listener=listener, stt=stt)
    orch.start()
    yield orch, listener, stt, adapter, collector
    orch.stop()


# --- rejim tanlash ----------------------------------------------------------

def test_listener_yoq_bolsa_matn_yoli():
    orch, *_ = build()
    assert orch.voice_mode is False


def test_listener_ishlamasa_matn_yoli():
    listener = FakeListener()
    listener.running = False
    orch, *_ = build(listener=listener)
    assert orch.voice_mode is False


def test_listener_ishlasa_ovoz_rejimi():
    orch, *_ = build(listener=FakeListener())
    assert orch.voice_mode is True


# --- to'liq oqim ------------------------------------------------------------

def test_ovozli_buyruq_bajariladi(voice):
    orch, listener, stt, adapter, collector = voice
    orch.activate("hotkey")
    assert collector.wait_turn(), "ovozli buyruq tugamadi"
    turn = collector.turns()[-1]
    assert turn.intent == "open_app" and turn.ok
    assert adapter.launched, "harakat bajarilmadi"
    assert orch.state is State.IDLE


def test_stt_aynan_listener_bergan_wav_ni_oladi(voice):
    orch, listener, stt, _adapter, collector = voice
    orch.activate("hotkey")
    assert collector.wait_turn()
    assert stt.seen == [WAV], f"STT ga boshqa narsa ketdi: {stt.seen!r}"
    assert listener.calls, "capture_utterance chaqirilmadi"


def test_transcribing_holati_otiladi(voice):
    orch, _listener, _stt, _adapter, collector = voice
    orch.activate("hotkey")
    assert collector.wait_turn()
    states = collector.states()
    assert "capturing" in states and "transcribing" in states
    assert states.index("capturing") < states.index("transcribing")


def test_nutq_eshitilmasa_turn_bolmaydi():
    listener = FakeListener(wav=b"")
    stt = FakeStt()
    orch, _adapter, _player, collector = build(listener=listener, stt=stt)
    orch.start()
    try:
        orch.activate("hotkey")
        time.sleep(0.5)
        assert collector.turns() == []
        assert stt.seen == [], "bo'sh segment STT ga yuborilmasligi kerak"
        assert orch.state is State.IDLE
    finally:
        orch.stop()


# --- xatolar ----------------------------------------------------------------

def _notices(collector):
    with collector._lock:
        return [e for e in collector.events if isinstance(e, ev.Notice)]


def test_stt_xatosi_bildiriladi_va_ilova_yiqilmaydi():
    stt = FakeStt(error=RuntimeError("server band"))
    orch, _adapter, _player, collector = build(listener=FakeListener(), stt=stt)
    orch.start()
    try:
        orch.activate("hotkey")
        time.sleep(0.6)
        notices = _notices(collector)
        assert notices, "STT xatosi bildirilmadi"
        assert notices[-1].level == "error"
        assert "stt_error" != notices[-1].message, "xom kalit ko'rsatildi - ibora yo'q"
        assert orch.state is State.IDLE
    finally:
        orch.stop()


def test_stt_xato_iborasi_tarjimada_bor():
    """`stt_error` kaliti yo'q bo'lsa foydalanuvchi kalitning O'ZINI eshitardi."""
    phrases = phrases_module.Phrases.load()
    assert phrases.get("stt_error") != "stt_error"


# --- bekor qilish -----------------------------------------------------------

def test_bekor_qilish_yozuv_threadini_toxtatadi():
    """`run_in_executor` future'ini bekor qilish thread'ni to'xtatmaydi -
    faqat cancel Event to'xtatadi. Aks holda mikrofon segment oxirigacha band."""
    listener = FakeListener(block=True)
    orch, _adapter, _player, _collector = build(listener=listener, capturing=5.0)
    orch.start()
    try:
        orch.activate("hotkey")
        assert listener.entered.wait(2.0), "yozuv boshlanmadi"
        orch.cancel("test")
        assert listener.cancelled.wait(2.0), "cancel Event qo'yilmadi - thread osilib qoldi"
    finally:
        orch.stop()


# --- barge-in himoyasi ------------------------------------------------------

def test_ijro_paytida_tinglovchi_karlanadi(voice):
    """AEC yo'q: Venera o'z javobini keyingi buyruq deb yozib olmasligi kerak."""
    orch, listener, _stt, _adapter, collector = voice
    orch.activate("hotkey")
    assert collector.wait_turn()
    assert listener.pauses > 0, "ijro oldidan pause() chaqirilmadi"
    assert listener.pauses == listener.resumes, "pause/resume juftlashmadi"


# --- ekran qulfi (0.2.9 dagi #1 nuqson) -------------------------------------

def test_qulflanganda_tinglovchi_ham_toxtaydi():
    capture = FakeCapture()
    listener = FakeListener()
    orch, _adapter, _player, _collector = build(listener=listener, capture=capture)
    orch.start()
    try:
        orch.post(ev.SessionLocked())
        time.sleep(0.4)
        assert orch.state is State.PAUSED
        assert listener.stops == 1, "tinglovchi to'xtatilmadi"
        assert capture.stops == 1
    finally:
        orch.stop()


def test_qulf_ochilganda_mikrofon_tiklanadi():
    """Ilgari `_on_unlock` faqat holatni almashtirardi: mikrofon ilova qayta
    ishga tushmaguncha o'lik qolardi."""
    capture = FakeCapture()
    listener = FakeListener()
    orch, _adapter, _player, _collector = build(listener=listener, capture=capture)
    orch.start()
    try:
        orch.post(ev.SessionLocked())
        time.sleep(0.4)
        orch.post(ev.SessionUnlocked())
        time.sleep(0.4)
        assert orch.state is State.IDLE
        assert capture.starts >= 1, "mikrofon qayta ochilmadi"
        assert listener.starts >= 1, "tinglovchi qayta ishga tushmadi"
        assert listener.running is True
    finally:
        orch.stop()


def test_qulfdan_keyin_ovozli_buyruq_yana_ishlaydi():
    capture = FakeCapture()
    listener = FakeListener()
    stt = FakeStt()
    orch, adapter, _player, collector = build(listener=listener, capture=capture, stt=stt)
    orch.start()
    try:
        orch.post(ev.SessionLocked())
        time.sleep(0.3)
        orch.post(ev.SessionUnlocked())
        time.sleep(0.3)
        orch.activate("hotkey")
        assert collector.wait_turn(), "qulfdan keyin ovozli buyruq ishlamadi"
        assert adapter.launched
    finally:
        orch.stop()

"""Holat mashinasining to'liq oqimi: matn -> intent -> harakat -> javob."""

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


class FakeCapture:
    running = False
    device = None

    def start(self): return False
    def stop(self): pass
    def drain(self): pass
    def reopen(self, rescan=True): return False
    def is_alive(self, tolerance=2.0): return False
    def seconds_since_audio(self): return 0.0
    def record(self, seconds, drain_first=True): return np.zeros(0, dtype=np.int16)


class FakePlayer:
    def __init__(self):
        self.played = []
        self.stopped = 0

    def play(self, pcm, sample_rate, timeout=30.0):
        self.played.append((len(pcm), sample_rate))
        return True

    def stop(self):
        self.stopped += 1


class FakeActivator:
    name = "fake"
    label = "Ctrl+Alt+Space"
    error = ""

    def start(self, on_activate): return True
    def stop(self): pass


class Collector:
    """Orchestrator chiqargan hodisalarni yig'adi."""

    def __init__(self):
        self.events = []
        self._lock = threading.Lock()
        self._turn = threading.Event()

    def __call__(self, event):
        with self._lock:
            self.events.append(event)
        if isinstance(event, ev.TurnFinished):
            self._turn.set()

    def wait_turn(self, timeout=5.0):
        ok = self._turn.wait(timeout)
        self._turn.clear()
        return ok

    def states(self):
        with self._lock:
            return [e.state for e in self.events if isinstance(e, ev.StateChanged)]

    def turns(self):
        with self._lock:
            return [e for e in self.events if isinstance(e, ev.TurnFinished)]


@pytest.fixture
def rig():
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    cfg.timeouts.capturing = 1.0
    adapter = FakeAdapter()
    player = FakePlayer()
    collector = Collector()
    ctx = ActionContext(adapter=adapter, config=cfg,
                        phrases=phrases_module.Phrases.load(), catalog=apps_module.load())
    orch = Orchestrator(
        config=cfg, adapter=adapter, stt=MockStt(), llm=RulesLlm(), tts=NullTts(),
        activator=FakeActivator(), capture=FakeCapture(), player=player,
        context=ctx, on_event=collector,
    )
    orch.start()
    yield orch, adapter, player, collector
    orch.stop()


def test_boshlangich_holat(rig):
    orch, *_ = rig
    assert orch.state is State.IDLE


def test_matn_yuborilsa_harakat_bajariladi(rig):
    orch, adapter, _player, collector = rig
    orch.submit_text("chromeni och")
    assert collector.wait_turn(), "buyruq tugamadi"
    turn = collector.turns()[-1]
    assert turn.intent == "open_app" and turn.ok
    assert adapter.launched
    assert orch.state is State.IDLE


def test_holatlar_ketma_ketligi(rig):
    orch, _adapter, _player, collector = rig
    orch.submit_text("soat necha")
    assert collector.wait_turn()
    states = collector.states()
    for expected in ("transcribing", "thinking", "acting", "speaking"):
        assert expected in states, f"{expected} holati o'tilmadi: {states}"
    assert states[-1] == "idle"


def test_ovoz_buyrugi(rig):
    orch, adapter, _player, collector = rig
    orch.submit_text("ovozni qirq besh foiz")
    assert collector.wait_turn()
    assert adapter.volume == 45


def test_qulflash_javobdan_keyin_bajariladi(rig):
    """Ekran qulflansa ovoz uziladi, shuning uchun javob oldin aytilishi kerak."""
    orch, adapter, _player, collector = rig
    orch.submit_text("ekranni qulfla")
    assert collector.wait_turn()
    states = collector.states()
    assert states.index("speaking") < states.index("acting")
    assert adapter.locked


def test_nomalum_buyruq(rig):
    orch, _adapter, _player, collector = rig
    orch.submit_text("bugun ob-havo qanday bo'ladi")
    assert collector.wait_turn()
    turn = collector.turns()[-1]
    assert turn.intent == "unknown" and not turn.ok


def test_bosh_matn_hech_narsa_qilmaydi(rig):
    orch, _adapter, _player, collector = rig
    orch.submit_text("   ")
    time.sleep(0.4)
    assert collector.turns() == []
    assert orch.state is State.IDLE


def test_aktivatsiya_keyin_matn(rig):
    orch, adapter, _player, collector = rig
    orch.activate("test")
    time.sleep(0.2)
    assert orch.state is State.CAPTURING
    orch.submit_text("chromeni och")
    assert collector.wait_turn()
    assert adapter.launched


def test_aktivatsiya_vaqt_tugashi(rig):
    """Buyruq kiritilmasa CAPTURING dan IDLE ga qaytadi."""
    orch, *_ = rig
    orch.activate("test")
    time.sleep(0.2)
    assert orch.state is State.CAPTURING
    time.sleep(1.4)
    assert orch.state is State.IDLE


def test_bekor_qilish(rig):
    orch, _adapter, player, _collector = rig
    orch.activate("test")
    time.sleep(0.2)
    orch.cancel("test")
    time.sleep(0.3)
    assert orch.state is State.IDLE
    assert player.stopped >= 1


def test_toxta_buyrugi(rig):
    orch, _adapter, _player, collector = rig
    orch.submit_text("to'xta")
    assert collector.wait_turn()
    assert collector.turns()[-1].intent == "cancel"


def test_ketma_ket_buyruqlar(rig):
    orch, adapter, _player, collector = rig
    for text in ["soat necha", "ovozni 20 ga qo'y", "bugun qaysi kun"]:
        orch.submit_text(text)
        assert collector.wait_turn(), f"{text!r} tugamadi"
    assert adapter.volume == 20
    assert len(collector.turns()) == 3
    assert orch.state is State.IDLE


def test_ekran_qulflanganda_pauza(rig):
    orch, adapter, _player, _collector = rig
    orch.post(ev.SessionLocked())
    time.sleep(0.3)
    assert orch.state is State.PAUSED
    orch.activate("test")          # qulflangan holatda e'tiborsiz qoldirilishi kerak
    time.sleep(0.2)
    assert orch.state is State.PAUSED
    orch.post(ev.SessionUnlocked())
    time.sleep(0.3)
    assert orch.state is State.IDLE

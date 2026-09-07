"""Adversarial ko'rik topgan nuqsonlar - qaytib kelmasligi uchun.

Har bir test 12 agentlik tekshiruv TASDIQLAGAN aniq nuqsonni qamraydi.
Ularning uchtasi bitta sababdan edi: barge-in ijroni to'xtatmasdi, lekin
`_play` ning `finally` bloki mikrofonni darhol ochardi.
"""

import time
from pathlib import Path

import pytest

from venera import config as config_module
from venera import events as ev
from venera import i18n
from venera.actions import apps as apps_module
from venera.actions import phrases as phrases_module
from venera.actions.base import ActionContext
from venera.core.orchestrator import Orchestrator, SttUnavailable
from venera.core.states import State
from venera.engines.base import AudioClip
from venera.engines.llm_rules import RulesLlm
from venera.engines.stt_mock import MockStt
from tests.test_actions import FakeAdapter
from tests.test_orchestrator import Collector, FakePlayer
from tests.test_voice_path import FakeCapture, FakeListener, FakeStt


class RecordingTts:
    """Aytilgan matnni yozib boradi - `NullTts` uni yutib yuborardi."""

    name = "recording"

    def __init__(self):
        self.spoken = []

    async def synthesize(self, text):
        self.spoken.append(text)
        return AudioClip.silence()

    async def close(self):
        return None


class SlowPlayer(FakePlayer):
    """`play()` bloklaydi - barge-in paytida ijro haqiqatan ketayotgan bo'ladi."""

    def __init__(self, seconds=1.5):
        super().__init__()
        self.seconds = seconds

    def play(self, pcm, sample_rate, timeout=30.0):
        deadline = time.monotonic() + self.seconds
        while time.monotonic() < deadline:
            if self.stopped:
                return False
            time.sleep(0.01)
        self.played.append((len(pcm), sample_rate))
        return True


def build(listener=None, stt=None, capture=None, tts=None, player=None,
          capturing=1.0, language="uz"):
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    cfg.timeouts.capturing = capturing
    cfg.timeouts.stt = 2.0
    cfg.language = language
    adapter = FakeAdapter()
    collector = Collector()
    ctx = ActionContext(adapter=adapter, config=cfg,
                        phrases=phrases_module.Phrases.load(), catalog=apps_module.load())
    orch = Orchestrator(
        config=cfg, adapter=adapter, stt=stt or MockStt(), llm=RulesLlm(),
        tts=tts or RecordingTts(), activator=None, capture=capture or FakeCapture(),
        player=player or FakePlayer(), context=ctx, on_event=collector,
        listener=listener,
    )
    return orch, adapter, collector


def _notices(collector):
    with collector._lock:
        return [e for e in collector.events if isinstance(e, ev.Notice)]


def _details(collector):
    with collector._lock:
        return [e.detail for e in collector.events if isinstance(e, ev.StateChanged)]


# --- 1. Barge-in ijroni to'xtatadi -----------------------------------------

def test_barge_in_ijroni_toxtatadi():
    """`_play` ning finally bloki `listener.resume()` ni DARHOL chaqiradi.
    Ijro to'xtatilmasa, mikrofon Veneraning o'z ovoziga ochilardi va VAD
    shovqin polini foydalanuvchining nutqiga sozlab, keyingi butun gapni
    yo'qotardi."""
    player = SlowPlayer(1.5)
    orch, _adapter, collector = build(player=player)
    orch.start()
    try:
        orch.submit_text("soat necha")
        time.sleep(0.4)
        oldingi = player.stopped
        orch.activate("hotkey")          # barge-in
        time.sleep(0.4)
        assert player.stopped > oldingi, "barge-in ijroni to'xtatmadi"
    finally:
        orch.stop()


def test_matn_yuborish_ham_ijroni_toxtatadi():
    player = SlowPlayer(1.5)
    orch, _adapter, _collector = build(player=player)
    orch.start()
    try:
        orch.submit_text("soat necha")
        time.sleep(0.4)
        oldingi = player.stopped
        orch.submit_text("chromeni och")
        time.sleep(0.4)
        assert player.stopped > oldingi, "yangi matn eski ijroni to'xtatmadi"
    finally:
        orch.stop()


# --- 2. STT xatosi AYTILADI ------------------------------------------------

def test_stt_xatosi_ovoz_bilan_aytiladi():
    """Ilgari server xatosi "vaqt tugadi" + `tick` signaliga aylanardi:
    foydalanuvchi "eshitmadim" deb tushunib qayta gapirardi."""
    tts = RecordingTts()
    stt = FakeStt(error=RuntimeError("ulanmadi (VPN uzilgan)"))
    orch, _adapter, collector = build(listener=FakeListener(), stt=stt, tts=tts)
    orch.start()
    try:
        orch.activate("hotkey")
        time.sleep(0.8)
        ibora = phrases_module.Phrases.load().get("stt_error")
        assert ibora in tts.spoken, f"xato aytilmadi, aytilganlar: {tts.spoken}"
        assert "stt xatosi" in _details(collector), \
            f"holat sababi noto'g'ri: {_details(collector)}"
        assert _notices(collector), "bildirishnoma yuborilmadi"
    finally:
        orch.stop()


def test_nutq_eshitilmasa_xato_deb_aytilmaydi():
    """Teskarisi ham to'g'ri bo'lishi kerak: haqiqatan jimlik bo'lsa
    "server ishlamadi" deb aytish ham yolg'on bo'lardi."""
    tts = RecordingTts()
    orch, _adapter, collector = build(listener=FakeListener(wav=b""), tts=tts)
    orch.start()
    try:
        orch.activate("hotkey")
        time.sleep(0.6)
        ibora = phrases_module.Phrases.load().get("stt_error")
        assert ibora not in tts.spoken
        assert "stt xatosi" not in _details(collector)
    finally:
        orch.stop()


# --- 3. STT byudjeti qayta urinishlarni qamraydi ---------------------------

def test_stt_byudjeti_barcha_urinishlarga_yetadi():
    """Tashqi chegara bitta urinish chegarasiga teng bo'lsa, zanjir ikkinchi
    urinish boshlanishidan oldin uzilardi - `stt.attempts` aynan o'zi kerak
    bo'lgan holatda (server osilib qolganda) ishlamasdi."""
    orch, _adapter, _collector = build()
    orch.config.timeouts.stt = 30.0
    orch.config.stt.attempts = 3
    byudjet = orch._stt_budget()
    assert byudjet >= 30.0 * 3, f"byudjet urinishlarga yetmaydi: {byudjet}"


def test_stt_byudjeti_bitta_urinishda_ham_mantiqiy():
    orch, _adapter, _collector = build()
    orch.config.timeouts.stt = 10.0
    orch.config.stt.attempts = 1
    assert orch._stt_budget() >= 10.0


def test_stt_unavailable_alohida_tur():
    """`None` bilan "hech narsa eshitilmadi" dan ajralib turishi SHART."""
    assert issubclass(SttUnavailable, Exception)


# --- 4. Qulfdan keyin tiklash ----------------------------------------------

def test_ovoz_rejimida_mikrofon_ochilmasa_paused_qoladi():
    """"Tayyor" yozuvi yolg'on bo'lardi: ilova haqiqatan eshitmaydi."""
    capture = FakeCapture()
    capture.start = lambda: False          # qurilma band / uyqudan keyin yo'q
    orch, _adapter, _collector = build(listener=FakeListener(), capture=capture)
    orch.start()
    try:
        orch.post(ev.SessionLocked())
        time.sleep(0.4)
        orch.post(ev.SessionUnlocked())
        time.sleep(0.5)
        assert orch.state is State.PAUSED
        assert orch._needs_audio_restore is True, "qayta urinish rejalashtirilmadi"
    finally:
        orch.stop()


def test_matn_rejimida_mikrofonsiz_ham_idle_ga_qaytadi():
    """Matn rejimida mikrofon IXTIYORIY - uni kutib ilovani bloklash
    foydalanuvchini matn yozishdan ham mahrum qilardi."""
    capture = FakeCapture()
    capture.start = lambda: False
    orch, _adapter, _collector = build(capture=capture)      # listener YO'Q
    orch.start()
    try:
        orch.post(ev.SessionLocked())
        time.sleep(0.4)
        orch.post(ev.SessionUnlocked())
        time.sleep(0.5)
        assert orch.state is State.IDLE
    finally:
        orch.stop()


def test_matn_rejimida_ortiqcha_ogohlantirish_yoq():
    capture = FakeCapture()
    capture.start = lambda: False
    orch, _adapter, collector = build(capture=capture)
    orch.start()
    try:
        orch.post(ev.SessionLocked())
        time.sleep(0.3)
        orch.post(ev.SessionUnlocked())
        time.sleep(0.4)
        assert not _notices(collector), "matn rejimida mikrofon ogohlantirishi shovqin"
    finally:
        orch.stop()


def test_watchdog_tiklashni_qayta_uradi():
    """Ilgari bitta muvaffaqiyatsiz urinishdan keyin ikkinchi shans yo'q edi:
    `_paused_by_lock` tiklashdan OLDIN tushirilardi."""
    capture = FakeCapture()
    listener = FakeListener()
    urinishlar = {"n": 0}

    def flaky_start():
        urinishlar["n"] += 1
        if urinishlar["n"] <= 1:
            return False
        capture.running = True
        return True

    capture.start = flaky_start
    orch, _adapter, _collector = build(listener=listener, capture=capture)
    orch.start()
    try:
        orch.post(ev.SessionLocked())
        time.sleep(0.4)
        orch.post(ev.SessionUnlocked())
        time.sleep(0.5)
        assert orch.state is State.PAUSED, "birinchi urinish muvaffaqiyatsiz bo'lishi kerak"

        chegara = time.monotonic() + 10.0
        while time.monotonic() < chegara:
            if orch.state is State.IDLE:
                break
            time.sleep(0.2)
        assert orch.state is State.IDLE, "watchdog tiklashni qayta urinmadi"
        assert urinishlar["n"] >= 2
        assert orch._needs_audio_restore is False
    finally:
        orch.stop()

"""`Application.build_core()` haqiqatan qaysi engine'ni quradi.

Bu testlar 0.2.9 gacha bo'lgan asosiy muammoni ushlaydi: `stt_onprem.py`,
`i18n/` va `listener.py` yozilgan va testdan o'tgan edi, lekin `app.py`
ularni IMPORT ham qilmasdi - config'da `onprem` yozilsa ham mock ishlardi.
"""

from pathlib import Path

import pytest

from venera import config as config_module
from venera import i18n
from venera.app import Application
from venera.audio.listener import AudioListener
from venera.engines.stt_mock import MockStt
from venera.engines.stt_onprem import OnpremStt
from tests.test_actions import FakeAdapter


def make_app(**engines):
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    for key, value in engines.items():
        setattr(cfg.engines, key, value)
    app = Application()
    app.config = cfg
    app.adapter = FakeAdapter()
    return app, cfg


# --- STT tanlash ------------------------------------------------------------

def test_mock_default_boligicha_qoladi():
    app, _cfg = make_app(stt="mock")
    app.build_core()
    assert isinstance(app.stt, MockStt)
    assert app.listener is None, "mock rejimda mikrofon band qilinmasligi kerak"


def test_onprem_haqiqiy_klientni_quradi():
    app, cfg = make_app(stt="onprem")
    cfg.stt.url = "http://10.10.50.4:8006"
    app.build_core()
    assert isinstance(app.stt, OnpremStt), "engines.stt=onprem hali mock berardi"
    assert app.stt.base_url == "http://10.10.50.4:8006"
    assert app.stt.transcribe_url.endswith("/transcribe")


def test_onprem_config_sozlamalarini_uzatadi():
    app, cfg = make_app(stt="onprem")
    cfg.stt.url = "http://server:8006"
    cfg.stt.attempts = 5
    cfg.stt.max_concurrent = 3
    cfg.timeouts.stt = 12.0
    app.build_core()
    assert app.stt.attempts == 5
    assert app.stt.timeout == 12.0


def test_onprem_tilni_i18n_dan_oladi():
    app, cfg = make_app(stt="onprem")
    cfg.stt.url = "http://server:8006"
    app.build_core()
    assert app.stt.language == i18n.stt_code()


# --- tinglovchi -------------------------------------------------------------

def test_onprem_tinglovchini_quradi():
    app, cfg = make_app(stt="onprem")
    cfg.stt.url = "http://server:8006"
    app.build_core()
    assert isinstance(app.listener, AudioListener)
    assert app.listener.capture is app.capture, "tinglovchi boshqa oqimga ulangan"


def test_tinglovchi_orchestratorga_uzatiladi():
    app, cfg = make_app(stt="onprem")
    cfg.stt.url = "http://server:8006"
    app.build_core()
    assert app.orchestrator.listener is app.listener, "orchestrator tinglovchini olmadi"


def test_mock_rejimda_orchestrator_matn_yolida():
    app, _cfg = make_app(stt="mock")
    app.build_core()
    assert app.orchestrator.listener is None
    assert app.orchestrator.voice_mode is False


def test_tinglovchi_audio_sozlamalarini_oladi():
    app, cfg = make_app(stt="onprem")
    cfg.stt.url = "http://server:8006"
    cfg.audio.sample_rate = 16000
    cfg.audio.blocksize = 512
    app.build_core()
    assert app.listener.sample_rate == 16000
    assert app.listener.frame_size == 512


# --- config himoyasi --------------------------------------------------------

def test_url_bosh_bolsa_mock_ga_qaytadi():
    """`config.validate()` buni allaqachon ushlaydi - ulanish uni buzmasin."""
    cfg, problems = config_module.load(Path("__yoq__.yaml"))
    cfg.engines.stt = "onprem"
    cfg.stt.url = ""
    problems = config_module.validate(cfg)
    assert cfg.engines.stt == "mock", f"bo'sh url bilan onprem qoldi: {problems}"


# --- i18n ulanishi ----------------------------------------------------------

def test_i18n_faol_paket_beradi():
    pack = i18n.bind("uz")
    assert pack.code == "uz"
    assert pack.ui, "ui.yaml yuklanmadi"


def test_stt_code_serverga_yaroqli():
    from venera.engines.stt_onprem import LANGUAGES
    i18n.bind("uz")
    assert i18n.stt_code() in LANGUAGES, "STT serveri bu kodni 400 bilan rad etadi"

"""To'liq ovoz zanjiri: tinglovchi -> OnpremStt -> HTTP -> intent -> harakat.

Soxta STT emas: haqiqiy `OnpremStt` haqiqiy HTTP server bilan gaplashadi,
ya'ni multipart kodlash, qayta urinish va xato xaritasi ham shu yo'ldan
o'tadi. Faqat MIKROFONNING o'zi soxta - qolgani ishlab turgan zanjir.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pytest

from venera import config as config_module
from venera import events as ev
from venera.actions import apps as apps_module
from venera.actions import phrases as phrases_module
from venera.actions.base import ActionContext
from venera.audio.wav import encode_wav
from venera.core.orchestrator import Orchestrator
from venera.core.states import State
from venera.engines.llm_rules import RulesLlm
from venera.engines.stt_onprem import OnpremStt
from venera.engines.tts_sapi import NullTts
from tests.test_actions import FakeAdapter
from tests.test_orchestrator import Collector, FakePlayer
from tests.test_voice_path import FakeCapture, FakeListener

#: Haqiqiy WAV - server uni multipart ichida shundayligicha ko'rishi kerak.
SPEECH = encode_wav(np.zeros(16000, dtype=np.int16), 16000)


class _Handler(BaseHTTPRequestHandler):
    codes: list = [200]
    text: str = "chromeni och"
    calls: list = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self._json(200, {"status": "ok"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        _Handler.calls.append(raw)
        index = min(len(_Handler.calls) - 1, len(_Handler.codes) - 1)
        code = _Handler.codes[index]
        if code != 200:
            self._json(code, {"detail": f"sinov xatosi {code}"})
            return
        self._json(200, {
            "text": _Handler.text,
            "language": "uz",
            "backend": "uzbek_stt",
            "duration_sec": 1.0,
            "elapsed_sec": 0.2,
            "low_confidence": None,
            "language_mismatch": None,
        })

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    _Handler.codes = [200]
    _Handler.text = "chromeni och"
    _Handler.calls = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", _Handler
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def chain(server):
    """Orchestrator + haqiqiy OnpremStt + soxta mikrofon."""
    base, handler = server
    cfg, _ = config_module.load(Path("__yoq__.yaml"))
    cfg.timeouts.capturing = 2.0
    cfg.timeouts.stt = 10.0        # qayta urinishlar ham sig'sin
    adapter = FakeAdapter()
    collector = Collector()
    listener = FakeListener(wav=SPEECH)
    stt = OnpremStt(base_url=base, language="uz", timeout=5.0)
    ctx = ActionContext(adapter=adapter, config=cfg,
                        phrases=phrases_module.Phrases.load(), catalog=apps_module.load())
    orch = Orchestrator(
        config=cfg, adapter=adapter, stt=stt, llm=RulesLlm(), tts=NullTts(),
        activator=None, capture=FakeCapture(), player=FakePlayer(),
        context=ctx, on_event=collector, listener=listener,
    )
    orch.start()
    yield orch, handler, adapter, collector, listener
    orch.stop()


def test_ovozdan_harakatgacha(chain):
    """Ctrl+Alt+Space -> gapirdi -> "chromeni och" -> Chrome ochildi."""
    orch, handler, adapter, collector, _listener = chain
    orch.activate("hotkey")
    assert collector.wait_turn(timeout=15.0), "zanjir tugamadi"
    turn = collector.turns()[-1]
    assert turn.intent == "open_app" and turn.ok, f"intent: {turn.intent}"
    assert adapter.launched, "dastur ochilmadi"
    assert orch.state is State.IDLE
    assert len(handler.calls) == 1, "serverga aynan bitta so'rov ketishi kerak"


def test_wav_serverga_butun_yetadi(chain):
    orch, handler, _adapter, collector, _listener = chain
    orch.activate("hotkey")
    assert collector.wait_turn(timeout=15.0)
    body = handler.calls[0]
    assert SPEECH in body, "WAV multipart ichida buzilgan"
    assert b'name="language"' in body and b"uz" in body, "til maydoni yuborilmadi"


def test_server_band_bolsa_qayta_urinadi(chain):
    """503 = navbat to'lgan, nosozlik emas: klient qayta urinadi va buyruq bajariladi."""
    orch, handler, adapter, collector, _listener = chain
    handler.codes = [503, 200]
    orch.activate("hotkey")
    assert collector.wait_turn(timeout=20.0), "503 dan keyin tiklanmadi"
    assert adapter.launched
    assert len(handler.calls) == 2, "qayta urinish bo'lmadi"


def test_server_yiqilsa_ilova_yiqilmaydi(chain):
    """400 - bizning xatomiz, qayta urinish yordam bermaydi. Foydalanuvchi
    xabar oladi, ilova esa IDLE ga qaytadi."""
    orch, handler, _adapter, collector, _listener = chain
    handler.codes = [400]
    orch.activate("hotkey")
    time.sleep(3.0)
    with collector._lock:
        notices = [e for e in collector.events if isinstance(e, ev.Notice)]
    assert notices, "STT xatosi foydalanuvchiga bildirilmadi"
    assert notices[-1].level == "error"
    assert orch.state is State.IDLE
    assert collector.turns() == [], "xato bo'lsa turn yakunlanmasligi kerak"


def test_bosh_javob_buyruq_bermaydi(chain):
    """Server jimlikni bo'sh matn deb qaytarsa - hech narsa bajarilmaydi."""
    orch, handler, adapter, collector, _listener = chain
    handler.text = ""
    orch.activate("hotkey")
    time.sleep(2.5)
    assert collector.turns() == []
    assert not adapter.launched
    assert orch.state is State.IDLE

"""On-prem STT klienti.

Bu testlar SOXTA obyekt emas, HAQIQIY HTTP server bilan ishlaydi: multipart
kodlash, 503 qayta urinish va xato xaritasi aynan urllib yo'lidan o'tadi.
Mock bilan bularning hech biri sinalmasdi.
"""

import asyncio
import email.parser
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from venera.engines.stt_onprem import (
    LANGUAGES, OnpremStt, SttError, Transcript, encode_multipart,
)

WAV = b"RIFF____WAVEfmt " + b"\x00" * 40


class _Handler(BaseHTTPRequestHandler):
    """Sinov serveri. Xulqni sinf atributlari boshqaradi."""

    #: Ketma-ket javob kodlari. Oxirgisi tugagach takrorlanadi.
    codes: list = [200]
    calls: list = []

    def log_message(self, *_args):  # noqa: D102 - sinovda shovqin kerak emas
        pass

    def do_GET(self):  # noqa: N802
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        _Handler.calls.append({
            "content_type": self.headers.get("Content-Type", ""),
            "body": raw,
        })
        index = min(len(_Handler.calls) - 1, len(_Handler.codes) - 1)
        code = _Handler.codes[index]

        if code == 200:
            payload = {
                "text": "  chromeni och  ",
                "language": "uz",
                "backend": "uzbek_stt",
                "duration_sec": 1.4,
                "elapsed_sec": 0.31,
                # uzbek_stt backend sifat maydonlarini null qaytaradi
                "low_confidence": None,
                "language_mismatch": None,
                "detected_language": None,
                "truncated": False,
            }
        else:
            payload = {"detail": f"sinov xatosi {code}"}

        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    _Handler.codes = [200]
    _Handler.calls = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler
    httpd.shutdown()
    httpd.server_close()


def run(coro):
    return asyncio.run(coro)


# --- multipart kodlash -------------------------------------------------------

def test_multipart_ikkala_maydonni_ham_yozadi():
    body, content_type = encode_multipart(b"\x01\x02\x03", "ru")
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="command.wav"' in body
    assert b'name="language"' in body
    assert b"\r\nru\r\n" in body
    assert b"\x01\x02\x03" in body


def test_multipart_email_parseri_bilan_oqiladi():
    """Server FastAPI bilan o'qiydi - shuning uchun standart parser tushunishi shart."""
    body, content_type = encode_multipart(WAV, "uz")
    message = email.parser.BytesParser().parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    parts = {}
    for part in message.get_payload():
        name = part.get_param("name", header="content-disposition")
        parts[name] = part.get_payload(decode=True)
    assert parts["language"] == b"uz"
    assert parts["file"] == WAV


def test_multipart_chegarasi_har_safar_boshqacha():
    """Chegara audio ichida tasodifan uchramasligi uchun tasodifiy bo'lishi kerak."""
    _, first = encode_multipart(WAV, "uz")
    _, second = encode_multipart(WAV, "uz")
    assert first != second


# --- javobni o'qish ----------------------------------------------------------

def test_null_sifat_maydonlari_false_boladi():
    """uz backend null qaytaradi - `if r.low_confidence` yiqilmasligi kerak."""
    result = Transcript.from_json({
        "text": "salom", "low_confidence": None,
        "language_mismatch": None, "detected_language": None,
    })
    assert result.low_confidence is False
    assert result.language_mismatch is False
    assert result.detected_language == ""


def test_matn_boshi_oxiridagi_boshliq_olib_tashlanadi():
    assert Transcript.from_json({"text": "  och  "}).text == "och"


def test_buzilgan_javob_yiqitmaydi():
    result = Transcript.from_json({"duration_sec": "juda-uzun", "text": None})
    assert result.text == ""
    assert result.duration_sec == 0.0


# --- so'rov ------------------------------------------------------------------

def test_transcribe_matnni_qaytaradi(server):
    base, _ = server
    stt = OnpremStt(base, language="uz")
    assert run(stt.transcribe(WAV)) == "chromeni och"


def test_tanlangan_til_yuboriladi(server):
    base, handler = server
    stt = OnpremStt(base, language="ru")
    run(stt.transcribe(WAV))
    assert b"\r\nru\r\n" in handler.calls[0]["body"]


def test_bosh_audio_serverga_bormaydi(server):
    base, handler = server
    stt = OnpremStt(base)
    assert run(stt.transcribe(b"")) == ""
    assert handler.calls == []


def test_notogri_til_uz_ga_qaytadi():
    assert OnpremStt("http://x", language="de").language == "uz"
    for language in LANGUAGES:
        assert OnpremStt("http://x", language=language).language == language


def test_set_language_keyingi_sorovga_tasir_qiladi(server):
    base, handler = server
    stt = OnpremStt(base, language="uz")
    stt.set_language("zh")
    run(stt.transcribe(WAV))
    assert b"\r\nzh\r\n" in handler.calls[0]["body"]


# --- 503 va qayta urinish ----------------------------------------------------

def test_503_qayta_urinadi_va_muvaffaqiyat_bilan_tugaydi(server):
    """503 = navbat to'lgan, XATO EMAS."""
    base, handler = server
    handler.codes = [503, 503, 200]
    stt = OnpremStt(base, attempts=3)
    assert run(stt.transcribe(WAV)) == "chromeni och"
    assert len(handler.calls) == 3


def test_503_urinishlar_tugagach_xato_beradi(server):
    base, handler = server
    handler.codes = [503]
    stt = OnpremStt(base, attempts=2)
    with pytest.raises(SttError) as caught:
        run(stt.transcribe(WAV))
    assert caught.value.status == 503
    assert caught.value.retryable
    assert len(handler.calls) == 2


def test_400_qayta_urinilmaydi(server):
    """Bizning xatomiz - qayta urinish yordam bermaydi, serverni bo'shga yuklaydi."""
    base, handler = server
    handler.codes = [400]
    stt = OnpremStt(base, attempts=3)
    with pytest.raises(SttError) as caught:
        run(stt.transcribe(WAV))
    assert caught.value.status == 400
    assert not caught.value.retryable
    assert len(handler.calls) == 1


def test_502_va_504_qayta_urinadi(server):
    base, handler = server
    handler.codes = [502, 504, 200]
    stt = OnpremStt(base, attempts=3)
    assert run(stt.transcribe(WAV)) == "chromeni och"


def test_server_xabari_xatoga_kiradi(server):
    base, handler = server
    handler.codes = [413]
    stt = OnpremStt(base, attempts=1)
    with pytest.raises(SttError, match="sinov xatosi 413"):
        run(stt.transcribe(WAV))


# --- himoya choralari --------------------------------------------------------

def test_daqiqalik_chegara_serverni_himoya_qiladi(server):
    """Mikrofoni shovqinda qolgan bitta PC parkni yiqitmasligi kerak."""
    base, handler = server
    stt = OnpremStt(base, max_per_minute=2)
    run(stt.transcribe(WAV))
    run(stt.transcribe(WAV))
    with pytest.raises(SttError, match="klient chegarasi"):
        run(stt.transcribe(WAV))
    assert len(handler.calls) == 2


def test_chegara_nol_bolsa_ochiq():
    stt = OnpremStt("http://x", max_per_minute=0)
    assert all(stt._limiter.allow() for _ in range(100))


def test_manzil_sozlanmagan_bolsa_aniq_xato():
    with pytest.raises(SttError, match="sozlanmagan"):
        run(OnpremStt("").transcribe(WAV))


# --- health ------------------------------------------------------------------

def test_health_serverdan_holatni_oladi(server):
    base, _ = server
    status = run(OnpremStt(base).health())
    assert status.ok
    assert "ok" in status.detail


def test_health_manzilsiz_yiqilmaydi():
    status = run(OnpremStt("").health())
    assert not status.ok
    assert "sozlanmagan" in status.detail


def test_health_olik_serverda_tez_qaytadi():
    """`--check` osilib qolmasligi kerak - health o'z timeout'iga ega."""
    status = run(OnpremStt("http://127.0.0.1:9").health())
    assert not status.ok


def test_nom_sakkiz_belgidan_qisqa():
    """`--check` hisoboti `{:8}` formatida chop etadi."""
    assert len(OnpremStt("http://x").name) <= 8

"""Servislar uchun STT: `POST /api/v1/stt/service/transcribe` (birinchisi - HRM boti).

Odam tokeni emas, servis kaliti (`X-Service-Key`) bilan ishlaydi; serverda
kalitning faqat SHA-256 izi turadi (`STT_SERVICE_KEYS=nom:sha256hex`).
"""

from __future__ import annotations

import hashlib
import io

import pytest

from app.core.config import settings
from app.services.analytics import current_actor, current_channel
from app.services.stt import SttError, Transcript

URL = "/api/v1/stt/service/transcribe"
KEY = "hrm-sinov-kaliti-123"


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@pytest.fixture
def service(monkeypatch):
    """Bitta `hrm` kaliti, toza daqiqalik hisob va so'rovlarni yozib boruvchi soxta STT."""
    import app.api.v1.stt as module

    monkeypatch.setattr(settings, "stt_service_keys", f"hrm:{_digest(KEY)}")
    monkeypatch.setattr(settings, "stt_service_per_min", 20)
    monkeypatch.setattr(module, "_service_rate", module._ServiceRate())
    calls: list[dict] = []

    def transcribe(audio, *, language, filename="a.ogg", content_type="audio/ogg", budget=None):
        calls.append({"bytes": len(audio), "language": language, "content_type": content_type,
                      "actor": current_actor.get(), "channel": current_channel.get()})
        return Transcript(text="tirbandlik sabab kechikdim", language=language, duration_sec=4.2)

    monkeypatch.setattr(module._router_client, "transcribe", transcribe)
    return calls


def _voice(size: int = 2048) -> dict:
    return {"file": ("voice.ogg", io.BytesIO(b"OggS" + b"\0" * size), "audio/ogg")}


def test_kalitsiz_401_va_stt_ga_bormaydi(client, service):
    response = client.post(URL, files=_voice())
    assert response.status_code == 401
    assert not service


def test_notogri_kalit_401(client, service):
    response = client.post(URL, files=_voice(), headers={"X-Service-Key": "boshqa"})
    assert response.status_code == 401
    assert not service


def test_kalit_sozlanmagan_bolsa_hamma_kalit_401(client, service, monkeypatch):
    monkeypatch.setattr(settings, "stt_service_keys", "")
    response = client.post(URL, files=_voice(), headers={"X-Service-Key": KEY})
    assert response.status_code == 401


def test_togri_kalit_matn_qaytaradi_til_standart_uz(client, service):
    response = client.post(URL, files=_voice(), headers={"X-Service-Key": KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "tirbandlik sabab kechikdim"
    assert body["durationSec"] == 4.2
    assert service[0]["language"] == "uz"
    assert service[0]["content_type"] == "audio/ogg"


def test_hisob_odamsiz_api_kanalida(client, service):
    """Sarf hisobida servis Barno foydalanuvchilariga aralashmasligi kerak."""
    client.post(URL, files=_voice(), headers={"X-Service-Key": KEY})
    assert service[0]["actor"] is None
    assert service[0]["channel"] == "api"


def test_odam_tokeni_servis_yolida_ishlamaydi(client, auth, service):
    response = client.post(URL, files=_voice(), headers=auth)
    assert response.status_code == 401
    assert not service


def test_servis_kaliti_odam_yolida_ishlamaydi(client, service):
    response = client.post("/api/v1/stt/transcribe", files=_voice(), data={"language": "uz"},
                           headers={"X-Service-Key": KEY})
    assert response.status_code == 401
    assert not service


def test_daqiqalik_chegara_429(client, service, monkeypatch):
    monkeypatch.setattr(settings, "stt_service_per_min", 2)
    headers = {"X-Service-Key": KEY}
    assert client.post(URL, files=_voice(), headers=headers).status_code == 200
    assert client.post(URL, files=_voice(), headers=headers).status_code == 200
    response = client.post(URL, files=_voice(), headers=headers)
    assert response.status_code == 429
    assert len(service) == 2


def test_katta_fayl_400(client, service, monkeypatch):
    monkeypatch.setattr(settings, "stt_max_upload_mb", 0.001)
    response = client.post(URL, files=_voice(4096), headers={"X-Service-Key": KEY})
    assert response.status_code == 400
    assert not service


def test_stt_xatosi_ichki_matnsiz(client, service, monkeypatch):
    import app.api.v1.stt as module

    def busy(*a, **k):
        raise SttError("http://10.10.50.4:8006 navbat to'la", status=503)

    monkeypatch.setattr(module._router_client, "transcribe", busy)
    response = client.post(URL, files=_voice(), headers={"X-Service-Key": KEY})
    assert response.status_code == 503
    assert "10.10.50.4" not in response.text


def test_notogri_yozilgan_juftlik_tashlanadi(monkeypatch):
    import app.api.v1.stt as module

    monkeypatch.setattr(settings, "stt_service_keys",
                        f" hrm:{_digest(KEY).upper()} , buzuq, :{_digest('x')}, qisqa:abc")
    assert module._service_keys() == [("hrm", _digest(KEY))]

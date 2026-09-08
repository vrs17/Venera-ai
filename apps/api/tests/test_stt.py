"""Ovoz -> matn endpointi.

STT serverining O'ZI bu testlarda chaqirilmaydi: u ichki tarmoqda, VPN
ortida va CI da yo'q. Shuning uchun klient soxtalashtiriladi va bu yerda
BIZNING qatlam tekshiriladi - autentifikatsiya, til tekshiruvi, hajm
chegarasi va xatolarni foydalanuvchiga ko'rsatish.
"""

from __future__ import annotations

import io

import pytest

from app.services.stt import LOCALE_TO_STT, SttError, Transcript


@pytest.fixture
def fake_stt(monkeypatch):
    """Klientni almashtiradi va nima yuborilganini yozib boradi."""
    calls: list[dict] = []

    def transcribe(audio, *, language, filename="a.webm", content_type="audio/webm"):
        calls.append({"bytes": len(audio), "language": language, "filename": filename})
        return Transcript(text="salom dunyo", language=language, duration_sec=1.5)

    import app.api.v1.stt as module
    monkeypatch.setattr(module._client, "transcribe", transcribe)
    return calls


def _audio(size: int = 4096) -> dict:
    return {"file": ("speech.webm", io.BytesIO(b"\x1a\x45\xdf\xa3" + b"\0" * size), "audio/webm")}


def test_tokensiz_rad_etiladi(client, fake_stt):
    """Ovoz yuborish PULLIK amal: STT serverida navbat cheklangan."""
    response = client.post("/api/v1/stt/transcribe", files=_audio(), data={"language": "uz"})
    assert response.status_code == 401
    assert not fake_stt, "autentifikatsiyasiz STT serveriga so'rov ketdi"


def test_token_bilan_matn_qaytadi(client, auth, fake_stt):
    body = client.post("/api/v1/stt/transcribe", files=_audio(), data={"language": "uz"},
                       headers=auth).json()
    assert body["text"] == "salom dunyo"
    assert set(body) == {"text", "language", "durationSec", "lowConfidence"}, \
        "types.ts dagi Transcript bilan mos emas"


def test_uz_cyrl_uz_ga_ogiriladi(client, auth, fake_stt):
    """`uz-Cyrl` alohida STT tili EMAS - yozuv boshqa, til bir xil.

    O'girmasak router 400 qaytarardi va kirill tilini tanlagan foydalanuvchi
    uchun ovoz UMUMAN ishlamasdi.
    """
    client.post("/api/v1/stt/transcribe", files=_audio(), data={"language": "uz-Cyrl"}, headers=auth)
    assert fake_stt[0]["language"] == "uz"


@pytest.mark.parametrize("locale,expected", sorted(LOCALE_TO_STT.items()))
def test_hamma_frontend_tillari_qabul_qilinadi(client, auth, fake_stt, locale, expected):
    response = client.post("/api/v1/stt/transcribe", files=_audio(),
                           data={"language": locale}, headers=auth)
    assert response.status_code == 200, f"{locale} rad etildi"
    assert fake_stt[-1]["language"] == expected


def test_notanish_til_400(client, auth, fake_stt):
    response = client.post("/api/v1/stt/transcribe", files=_audio(),
                           data={"language": "fr"}, headers=auth)
    assert response.status_code == 400
    assert not fake_stt, "noto'g'ri til STT serveriga yuborildi"


def test_bosh_audio_400(client, auth, fake_stt):
    response = client.post(
        "/api/v1/stt/transcribe",
        files={"file": ("s.webm", io.BytesIO(b""), "audio/webm")},
        data={"language": "uz"}, headers=auth,
    )
    assert response.status_code == 400
    assert not fake_stt


def test_juda_katta_fayl_rad_etiladi(client, auth, fake_stt):
    """Chegara BIZDA ham bo'lishi kerak.

    Router 25 MB da to'xtatadi, lekin unga qadar fayl butun ichki tarmoqni
    bosib o'tardi va faqat oxirida rad etilardi.
    """
    from app.core.config import settings
    too_big = int(settings.stt_max_upload_mb * 1024 * 1024) + 1
    response = client.post(
        "/api/v1/stt/transcribe",
        files={"file": ("s.webm", io.BytesIO(b"\0" * too_big), "audio/webm")},
        data={"language": "uz"}, headers=auth,
    )
    assert response.status_code == 400
    assert not fake_stt, "chegaradan katta fayl STT serveriga yuborildi"


def test_navbat_tola_bolsa_503(client, auth, monkeypatch):
    """503 = "keyinroq urin", xato emas - foydalanuvchiga shunday aytiladi."""
    import app.api.v1.stt as module

    def busy(*a, **k):
        raise SttError("navbat to'la", status=503, retryable=True)

    monkeypatch.setattr(module._client, "transcribe", busy)
    response = client.post("/api/v1/stt/transcribe", files=_audio(),
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 503
    assert "band" in response.json()["message"].lower()


def test_xato_ichki_manzilni_oshkor_qilmaydi(client, auth, monkeypatch):
    """Xato matni FOYDALANUVCHIGA ko'rinadi - ichki host chiqmasin."""
    import app.api.v1.stt as module

    def leak(*a, **k):
        raise SttError("http://10.10.50.4:8006/transcribe ishlamadi", status=500)

    monkeypatch.setattr(module._client, "transcribe", leak)
    body = client.post("/api/v1/stt/transcribe", files=_audio(),
                       data={"language": "uz"}, headers=auth).json()
    assert "10.10.50" not in body["message"]
    assert "8006" not in body["message"]

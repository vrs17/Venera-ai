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
    from tests.test_contract import TRANSCRIPT_FIELDS
    assert set(body) == TRANSCRIPT_FIELDS, "types.ts dagi Transcript bilan mos emas"


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


# ─── Router hujjati bo'yicha xulq ────────────────────────────────────────────

import json as _json
import threading
import urllib.error

from app.services.stt import SttClient


class _FakeRouter:
    """`SttClient._once` ni Router o'rniga javob beradigan qilib almashtiradi.

    Router'ning O'ZI chaqirilmaydi (ichki tarmoq), lekin uning javob SHAKLI
    hujjatdan aynan olingan - shu tufayli null maydonlar va mismatch
    xulqi haqiqiy shaklda tekshiriladi.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.languages: list[str] = []

    def __call__(self, body: bytes, content_type: str):
        # multipart ichidan `language` ni ajratamiz
        lang = body.split(b'name="language"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode()
        self.languages.append(lang)
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def _uz(text="salom"):
    """uz backend: sifat maydonlari NULL (hujjatdagi namuna)."""
    return {"text": text, "language": "uz", "backend": "uzbek_stt", "model": "uzbek_stt_v1",
            "duration_sec": 5.83, "truncated": False, "avg_logprob": None, "segments": None,
            "low_confidence": None, "language_mismatch": None, "detected_language": None,
            "elapsed_sec": 0.25}


def _ml(text, lang="ru", **q):
    base = {"text": text, "language": lang, "backend": "multilang", "model": "large-v3-turbo-ct2",
            "duration_sec": 5.83, "truncated": False, "avg_logprob": -0.12, "segments": 1,
            "low_confidence": False, "language_mismatch": False, "detected_language": None,
            "elapsed_sec": 0.25}
    base.update(q)
    return base


def _client(monkeypatch, responses, **kw):
    c = SttClient("http://router.test", attempts=1, **kw)
    fake = _FakeRouter(responses)
    monkeypatch.setattr(c, "_once", lambda body, ct: SttClient._parse(fake(body, ct)))
    return c, fake


def test_uz_backend_null_maydonlari_false_boladi(monkeypatch):
    """Hujjat: uz backend `low_confidence: null` beradi - klient uni false deb olsin."""
    c, _ = _client(monkeypatch, [_uz()])
    r = c.transcribe(b"x" * 100, language="uz")
    assert r.low_confidence is False and r.language_mismatch is False
    assert r.detected_language is None and r.truncated is False
    assert r.backend == "uzbek_stt"


def test_parallellik_chegarasi_503_beradi(monkeypatch):
    """Hujjat: butun park <=10 parallel. Chegaradan oshgan so'rov Router'ga
    BORMASDAN 503 (qayta uriniladigan) olishi kerak."""
    gate = threading.Event()
    c = SttClient("http://router.test", attempts=1, max_concurrent=1)
    monkeypatch.setattr(c, "_once", lambda b, ct: (gate.wait(5), SttClient._parse(_uz()))[1])

    first_done = threading.Event()
    def first():
        c.transcribe(b"x" * 100, language="uz"); first_done.set()
    t = threading.Thread(target=first); t.start()
    import time; time.sleep(0.1)          # birinchisi slotni egallasin

    with pytest.raises(SttError) as e:
        c.transcribe(b"x" * 100, language="uz")   # 2 s kutadi, keyin taslim
    assert e.value.status == 503 and e.value.retryable
    gate.set(); t.join(5); assert first_done.is_set()


def test_slot_xatoda_ham_boshatiladi(monkeypatch):
    """Istisno chiqsa semafora qaytarilmasa - 4 xatodan keyin ilova abadiy 503."""
    c = SttClient("http://router.test", attempts=1, max_concurrent=1)
    monkeypatch.setattr(c, "_once", lambda b, ct: (_ for _ in ()).throw(SttError("yiqildi", status=502)))
    for _ in range(3):
        with pytest.raises(SttError):
            c.transcribe(b"x" * 100, language="uz")
    # slot bo'sh bo'lsa acquire darhol o'tadi
    assert c._slots.acquire(timeout=0.1); c._slots.release()


def test_endpoint_yangi_maydonlarni_uzatadi(client, auth, monkeypatch):
    import app.api.v1.stt as module
    monkeypatch.setattr(module._client, "transcribe", lambda *a, **k: Transcript(
        text="salom", language="uz", backend="uzbek_stt", low_confidence=True, truncated=True))
    body = client.post("/api/v1/stt/transcribe", files=_audio(), data={"language": "uz"},
                       headers=auth).json()
    assert body["lowConfidence"] is True and body["truncated"] is True
    assert body["backend"] == "uzbek_stt"


# ─── Mahsulot qarori: ovoz FAQAT UI tilida, til aniqlash YO'Q ────────────────

def test_mismatch_bolsa_ham_qayta_yuborilmaydi(monkeypatch):
    """Router "audio boshqa tilda" desa ham BITTA so'rov, so'ralgan tilda.

    Router hujjati `detected_language` bilan qayta yuborishni tavsiya qiladi -
    bu tizimda ATAYLAB qilinmaydi: foydalanuvchi tanlagan til qat'iy. Bu test
    kimdir "yaxshilab" qo'yishidan qo'riqlaydi.
    """
    c, fake = _client(monkeypatch, [
        _ml("1命女孩的饿吐", "ru", low_confidence=True, language_mismatch=True, detected_language="zh"),
        _ml("BU KELMASLIGI KERAK", "zh"),
    ])
    r = c.transcribe(b"x" * 100, language="ru")
    assert fake.languages == ["ru"], "ikkinchi so'rov ketdi - til almashtirildi"
    assert r.text == "1命女孩的饿吐" and r.language == "ru"


def test_javobda_aniqlangan_til_yoq(client, auth, monkeypatch):
    """`detectedLanguage` klientga chiqmaydi - u tizim tilini o'zgartirishga
    undaydigan ma'lumot, mahsulotda esa bunday xulq yo'q."""
    import app.api.v1.stt as module
    monkeypatch.setattr(module._client, "transcribe", lambda *a, **k: Transcript(
        text="x", language="ru", language_mismatch=True, detected_language="zh"))
    body = client.post("/api/v1/stt/transcribe", files=_audio(), data={"language": "ru"},
                       headers=auth).json()
    assert "detectedLanguage" not in body and "languageMismatch" not in body


def test_zh_qabul_qilinmaydi(client, auth, fake_stt):
    """Router xitoy tilini biladi, tizim esa yo'q - 400, Router'ga bormaydi."""
    response = client.post("/api/v1/stt/transcribe", files=_audio(),
                           data={"language": "zh"}, headers=auth)
    assert response.status_code == 400
    assert not fake_stt

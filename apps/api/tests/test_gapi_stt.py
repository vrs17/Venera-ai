"""GAPI STT (2-variant) va variantlar orasidagi tanlov.

`console.gapi.uz` ning O'ZI chaqirilmaydi: u tashqi pullik xizmat va CI da
yo'q. Almashtirish nuqtasi `urllib.request.urlopen` - ya'ni faqat TRANSPORT
soxta, ustidagi hamma mantiq (sozlamalar, 202 yo'li, xatolarni guruhlash,
kalitni yashirish, tanlov) haqiqiy kod bo'lib qoladi.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request

import pytest

from app.services.integrations.gapi_stt import GapiSttClient, _safe
from app.services.stt import SttError

BASE = "https://gapi.test/v1"
KEY = "gapi_abcdef123456_secretvalue"
AUDIO = b"RIFF" + b"\0" * 400


class FakeGapi:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail: tuple[int, dict, dict] | None = None   # (status, body, headers)
        #: `/transcribe` natija o'rniga 202 + job_id qaytaradi.
        self.defer = False
        #: `/jobs/{id}` shu holatlarni ketma-ket beradi.
        self.states = ["done"]

    def __call__(self, request, timeout=None):
        path = "/" + request.full_url.split("/v1/", 1)[1]
        self.calls.append({
            "path": path,
            "method": request.get_method(),
            "auth": request.get_header("Authorization"),
            "body": request.data,
        })
        if self.fail:
            status, body, headers = self.fail
            raise _http_error(path, status, body, headers)

        if path == "/transcribe":
            if self.defer:
                return _Resp(json.dumps({"id": "job-7", "state": "processing"}).encode(),
                             {"X-Job-Id": "job-7"})
            return _Resp(json.dumps({"text": "Salom Venera", "audio_seconds": 1.4}).encode(),
                         {"X-Job-Id": "job-1"})
        if path.endswith("/result"):
            return _Resp(json.dumps({"text": "kechikkanlar ro'yxati",
                                     "audio_seconds": 9.0}).encode(), {})
        if path.startswith("/jobs/"):
            state = self.states.pop(0) if self.states else "done"
            return _Resp(json.dumps({"id": "job-7", "state": state}).encode(), {})
        raise AssertionError(f"kutilmagan yo'l: {path}")

    def settings_sent(self) -> dict:
        """`/transcribe` tanasidagi `settings` JSON'i."""
        body = self.calls[0]["body"]
        marker = b'name="settings"\r\n\r\n'
        start = body.index(marker) + len(marker)
        end = body.index(b"\r\n--", start)
        return json.loads(body[start:end])


class _Resp:
    def __init__(self, raw: bytes, headers: dict) -> None:
        self._raw = raw
        self.headers = headers

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _http_error(path, code, payload, headers=None):
    return urllib.error.HTTPError(
        f"{BASE}{path}", code, "error", headers or {},
        io.BytesIO(json.dumps(payload).encode()),
    )


@pytest.fixture
def gapi(monkeypatch):
    fake = FakeGapi()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    # `deadline` ATAYLAB katta: klient endi keyingi urinishning `timeout`
    # ini ham byudjetga qo'shadi (`services/stt.py` kabi), ya'ni 5/5 da
    # qayta urinish umuman sig'masdi va bu testlar qayta urinishni emas,
    # arifmetikani sinagan bo'lardi.
    return GapiSttClient(BASE, KEY, timeout=5, deadline=30, attempts=2), fake


# --- oddiy yo'l -------------------------------------------------------------


def test_transcribe_matnni_qaytaradi(gapi):
    client, fake = gapi
    result = client.transcribe(AUDIO, language="uz")
    assert result.text == "Salom Venera"
    assert result.backend == "gapi"
    assert result.language == "uz"
    assert result.duration_sec == 1.4
    assert fake.calls[0]["path"] == "/transcribe"
    assert fake.calls[0]["auth"] == f"Bearer {KEY}"


def test_narx_tuzogi_emotion_va_pii_ochirilgan(gapi):
    """ENG MUHIM TEST. Yangi loyihada `emotion` va `pii` YOQIQ turadi va
    har yozuv ×2.2 tarifga tushadi - ikki barobardan qimmat. Biz ularni
    har so'rovda ataylab `false` qilib yuboramiz.

    Bu test o'chsa, hisob jimgina ikki barobar oshadi va buni hech kim
    kod tomonidan sezmaydi.
    """
    client, fake = gapi
    client.transcribe(AUDIO, language="uz")
    sent = fake.settings_sent()
    assert sent["emotion"] is False, "emotion yoqiq ketdi - ×2.2 tarif"
    assert sent["pii"] is False, "pii yoqiq ketdi - ×2.2 tarif"
    assert sent["diarization"] is False


def test_notogri_sozlama_kaliti_yuborilmaydi(gapi):
    """Noma'lum kalit butun yuklashni rad etadi (`400 unknown_setting`),
    shuning uchun yuboriladigan kalitlar ro'yxati QAT'IY."""
    client, fake = gapi
    client.transcribe(AUDIO, language="uz")
    # `speaker_identification`/`gender` - ANIQ o'chiq (2026-11-18): yuborilmasa loyiha sozlamasidan olinadi va
    # diktovka xodimlarning nomsiz nusxa ovozlarini ochishi mumkin (`voice.py`, NUSXA OVOZ). Ikkalasi ham GAPI
    # biladigan kalit (yig'ilish va namuna sozlamalarida bor; jonli tekshirilgan).
    assert set(fake.settings_sent()) == {"diarization", "emotion", "pii", "speaker_identification", "gender"}
    assert fake.settings_sent()["speaker_identification"] is False and fake.settings_sent()["gender"] is False


def test_til_maydoni_yuborilmaydi(gapi):
    """GAPI da `language` maydoni YO'Q - u o'zbek uchun bitta model.
    Noma'lum narsa yuborish yuklashni rad etishi mumkin."""
    client, fake = gapi
    client.transcribe(AUDIO, language="uz")
    assert b'name="language"' not in fake.calls[0]["body"]


# --- 202 yo'li -------------------------------------------------------------


def test_202_da_vazifa_kutiladi(gapi, monkeypatch):
    """`/transcribe` 3 daqiqada ulgurmasa natija o'rniga 202 + job_id
    qaytaradi. Bu holatni ishlov bermaslik "javobda segments topilmadi"
    degan tushunarsiz xatoga olib kelardi."""
    import app.services.integrations.gapi_stt as mod

    monkeypatch.setattr(mod, "_POLL_EVERY", 0.0)
    client, fake = gapi
    fake.defer = True
    fake.states = ["processing", "done"]
    result = client.transcribe(AUDIO, language="uz")
    assert result.text == "kechikkanlar ro'yxati"
    assert [c["path"] for c in fake.calls] == [
        "/transcribe", "/jobs/job-7", "/jobs/job-7", "/jobs/job-7/result",
    ]


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_vazifa_yiqilsa_xato(gapi, monkeypatch, state):
    import app.services.integrations.gapi_stt as mod

    monkeypatch.setattr(mod, "_POLL_EVERY", 0.0)
    client, fake = gapi
    fake.defer = True
    fake.states = [state]
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert state in str(caught.value)


# --- xatolar --------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 503, 507, 409])
def test_kutib_qayta_urinish_mumkin(gapi, status):
    client, fake = gapi
    fake.fail = (status, {"error": "rate_limited", "hint": "sekin"}, {})
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert caught.value.retryable is True
    # Ikki urinish: `attempts=2`.
    assert len(fake.calls) == 2


@pytest.mark.parametrize("status", [400, 413, 422, 404, 410])
def test_qayta_urinilmaydigan_xatolar(gapi, status):
    """So'rovni tuzatish kerak yoki umuman qaytmaydi - takrorlash zarar."""
    client, fake = gapi
    fake.fail = (status, {"error": "unknown_setting", "hint": "kalit xato"}, {})
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert caught.value.retryable is False
    assert len(fake.calls) == 1, "qayta urinmasligi kerak edi"


def test_401_brauzerga_502_bolib_chiqadi(gapi):
    """401 - BIZNING kalitimiz noto'g'ri, ya'ni SOZLAMA xatosi. Brauzerga
    401 qaytarish "sessiyangiz tugadi" degan ma'no berardi, holbuki
    foydalanuvchi sessiyasi mutlaqo joyida."""
    client, fake = gapi
    fake.fail = (401, {"error": "unauthorized", "hint": "token xato"}, {})
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert caught.value.status == 502


def test_429_retry_after_hisobga_olinadi(gapi):
    client, fake = gapi
    fake.fail = (429, {"error": "rate_limited", "hint": "kutib turing"},
                 {"Retry-After": "2"})
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert getattr(caught.value, "retry_after", None) == 2.0


def test_sozlanmagan_bolsa_501(monkeypatch):
    client = GapiSttClient(BASE, "")
    assert client.configured is False
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert caught.value.status == 501


def test_ozbekdan_boshqa_til_rad_etiladi(gapi):
    """GAPI da `ru`/`en` uchun model YO'Q. Jim ishlab noto'g'ri tilda
    matn qaytargandan ko'ra aniq xato afzal."""
    client, fake = gapi
    for language in ("ru", "en"):
        with pytest.raises(SttError) as caught:
            client.transcribe(AUDIO, language=language)
        assert caught.value.status == 400
    assert not fake.calls, "so'rov yuborilmasligi kerak edi"


# --- kalit oshkor bo'lmasligi ---------------------------------------------


def test_kalit_xato_matniga_tushmaydi(gapi):
    client, fake = gapi
    fake.fail = (400, {"error": "bad", "hint": f"token {KEY} bilan"}, {})
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert KEY not in str(caught.value)
    assert "<key>" in str(caught.value)


def test_har_transkripsiya_jurnalga_tushadi(gapi, caplog):
    """Jurnalda QAYSI variant ishlaganini ko'rsatuvchi satr bo'lishi kerak.

    Bu shunchaki qulaylik emas: 1 va 2-variant orasidagi qaror jurnaldagi
    o'lchovlarga tayanadi, GAPI esa audio DAQIQASI uchun pul oladi - shu
    satrlardagi sekundlar hisobning o'zi. Satr yo'qolsa sarf ham, tanlov
    ham ko'rinmay qoladi.

    Format Router bilan bir xil (`services/stt.py`), ya'ni bitta `grep STT`
    ikkalasini ham topadi.
    """
    client, fake = gapi
    with caplog.at_level(logging.INFO):
        client.transcribe(AUDIO, language="uz")
    line = next((r.getMessage() for r in caplog.records
                 if r.getMessage().startswith("STT ")), "")
    assert line, "transkripsiya jurnalga tushmadi"
    assert "gapi/gapi:job-1" in line, line
    assert "1.4s audio" in line, "hisob uchun audio uzunligi yo'q"


def test_jurnalda_matnning_ozi_yozilmaydi(gapi, caplog):
    """Matn - xodim aytgan gap, ya'ni shaxsiy ma'lumot. Jurnalga faqat
    uzunligi tushadi."""
    client, fake = gapi
    with caplog.at_level(logging.DEBUG):
        client.transcribe(AUDIO, language="uz")
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Salom Venera" not in logged
    assert "12 belgi" in logged


def test_kalit_jurnalga_tushmaydi(gapi, caplog):
    client, fake = gapi
    with caplog.at_level(logging.DEBUG):
        client.transcribe(AUDIO, language="uz")
    assert KEY not in "\n".join(r.getMessage() for r in caplog.records)


def test_kalit_prefiksi_boshqa_bolsa_ham_yashiriladi(monkeypatch):
    """Redaksiya TAXMINGA tayanmasligi kerak.

    Eski `_safe` faqat `gapi_` prefiksini qidirardi. Bugungi kalit shunday
    boshlanadi, lekin xizmat formatni o'zgartirsa himoya JIMGINA ishlamay
    qolardi - va buni faqat sir oqib ketganda bilardik.
    """
    boshqacha = "sk-live-9f2b7c4e11aa"
    client = GapiSttClient(BASE, boshqacha, timeout=5, deadline=5, attempts=1)
    fake = FakeGapi()
    fake.fail = (400, {"error": "bad", "hint": f"token {boshqacha} xato"}, {})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(SttError) as caught:
        client.transcribe(AUDIO, language="uz")
    assert boshqacha not in str(caught.value)
    assert "<key>" in str(caught.value)


def test_kunlik_sarf_hisoblanadi(gapi):
    """Kvota tugashini XATO ko'rinishida bilish eng kech payt."""
    client, fake = gapi
    assert client.spend()["calls"] == 0
    client.transcribe(AUDIO, language="uz")
    client.transcribe(AUDIO, language="uz")
    spend = client.spend()
    assert spend["calls"] == 2
    # Soxta javobda `audio_seconds` = 1.4.
    assert spend["audio_sec"] == pytest.approx(2.8, abs=0.01)


def test_safe_kalitni_yashiradi():
    assert _safe(f"oldin {KEY} keyin") == "oldin <key> keyin"
    assert _safe("kalit yo'q") == "kalit yo'q"
    assert _safe("") == ""


# --- variantlar orasidagi tanlov -----------------------------------------


@pytest.fixture
def picker(monkeypatch):
    import app.api.v1.stt as module

    monkeypatch.setattr(module._gapi_client, "_api_key", KEY)
    monkeypatch.setattr(module._gapi_client, "base_url", BASE)
    return module


def test_gapi_faqat_ozbek_uchun_tanlanadi(picker):
    """2-variantga o'tish rus va ingliz interfeysini BUZMASLIGI kerak."""
    assert picker._pick("uz", "gapi") is picker._gapi_client
    assert picker._pick("ru", "gapi") is picker._router_client
    assert picker._pick("en", "gapi") is picker._router_client


def test_uygotish_alohida_klient_oladi(picker):
    """Uyg'otish ham GAPI ga boradi, LEKIN o'zining slotli klienti bilan -
    aks holda fon ishi savolning slotini olib qo'yardi (o'lchangan: 4
    parallel so'rovdan biri 503)."""
    assert picker._pick("uz", "gapi", wake=True) is picker._gapi_wake_client
    assert picker._pick("uz", "gapi") is picker._gapi_client
    # Rus/ingliz uyg'otishi baribir Router'da: GAPI da model yo'q.
    assert picker._pick("ru", "gapi", wake=True) is picker._router_client


def test_router_tanlovi_ozgarmaydi(picker):
    for language in ("uz", "ru", "en"):
        assert picker._pick(language, "router") is picker._router_client


def test_kalit_bosh_bolsa_routerga_tushadi(picker, monkeypatch):
    """Sozlanmagani uchun ovozni butunlay ishdan chiqarish noto'g'ri."""
    monkeypatch.setattr(picker._gapi_client, "_api_key", "")
    assert picker._pick("uz", "gapi") is picker._router_client


def test_notanish_provider_routerga_tushadi(picker):
    """`.env` ga xato yozilsa (`STT_PROVIDER=gpai`) tizim ishlashda
    davom etishi kerak - isbotlangan yo'l bilan."""
    assert picker._pick("uz", "gpai") is picker._router_client
    assert picker._pick("uz", "") is picker._router_client

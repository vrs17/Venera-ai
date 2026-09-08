"""Matn -> ovoz endpointi va TTS klienti.

TTS serverining O'ZI chaqirilmaydi: u ichki tarmoqda, VPN ortida va CI da
yo'q. Transport darajasi (`_open`) soxtalashtiriladi, ustidagi hamma
mantiq - token keshi, `download_url` tuzog'i, normalizator naqshlari,
navbat chegarasi va xatolarni foydalanuvchiga ko'rsatish - haqiqiy kod.
"""

from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from app.services.tts import (
    LOCALE_TO_TTS,
    TtsClient,
    TtsError,
    clip,
    risky_for_normalizer,
)

WAV = b"RIFF$\x00\x00\x00WAVEfmt "


class FakeServer:
    """Hujjatdagi javob shakllarini beradi va so'rovlarni yozib boradi.

    ALMASHTIRISH NUQTASI `build_opener` - ya'ni klientning `_open` metodi,
    HTTPError'ni TtsError'ga o'girish va sirni yashirish bilan birga, HAQIQIY
    kod bo'lib qoladi. `_open` ning o'zi almashtirilsa aynan shu mantiq
    testdan chetda qolardi.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None, dict]] = []
        #: Shu tokenlar endi yaroqsiz (401) - "muddati tugadi" ni modellaydi.
        self.dead_tokens: set[str] = set()
        self.generate_status: int | None = None
        self.audio_path = "/srv/shared/audio/7__deadbeef.wav"
        self.issued = 0

    def open(self, request, timeout=None):
        path = request.full_url.split("://", 1)[1].split("/", 1)[1]
        path = "/" + path
        payload = json.loads(request.data) if request.data else None
        token = (request.get_header("Authorization") or "").removeprefix("Bearer ")
        self.calls.append((path, payload, {"token": token}))

        if path == "/api/v1/auth/token":
            self.issued += 1
            return _ok(json.dumps({"access_token": f"tok{self.issued}",
                                   "token_type": "bearer", "expires_in": 86400}).encode())

        if token in self.dead_tokens:
            raise _http_error(path, 401, "Token muddati tugagan")

        if path == "/api/v1/tts/generate":
            if self.generate_status:
                raise _http_error(path, self.generate_status,
                                  "TTS xatosi: list index out of range")
            return _ok(json.dumps({
                "user_id": payload["user_id"], "phone": payload["phone"], "status": "success",
                "audio_path": self.audio_path,
                "download_url": "http://10.10.50.4:8200/api/v1/tts/audio/7",
                "duration_sec": 4.84, "normalized_text": payload["text"],
            }).encode())

        if path.startswith("/api/v1/tts/file/"):
            return _ok(WAV)
        raise AssertionError(f"kutilmagan yo'l: {path}")


class _ok:
    """Minimal `urlopen` javobi - kontekst menejer va `read()`."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._data


def _http_error(path: str, code: int, detail: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        f"http://tts{path}", code, detail, {},
        io.BytesIO(json.dumps({"detail": detail}).encode()),
    )


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    return fake


@pytest.fixture
def tts(server):
    return TtsClient("http://tts", "frontend", "s3cret")


# --- klient -----------------------------------------------------------------


def test_token_bir_marta_olinadi(tts, server):
    """Token 24 soat yashaydi - har sintezda qayta so'rash ortiqcha yuk."""
    for _ in range(3):
        tts.synthesize("salom", user_id="7")
    tokens = [c for c in server.calls if c[0] == "/api/v1/auth/token"]
    assert len(tokens) == 1, f"token {len(tokens)} marta so'raldi"


def test_401_da_token_yangilanadi(tts, server):
    """Token so'rovlar ORASIDA eskiradi (24 soat yashaydi) yoki server qayta
    ishga tushadi. Foydalanuvchi buni ko'rmasligi kerak - bir marta jimgina
    yangilanadi va so'rov takrorlanadi."""
    tts.synthesize("birinchi", user_id="7")
    server.dead_tokens.add("tok1")          # keshdagi token endi yaroqsiz
    server.calls.clear()

    speech = tts.synthesize("ikkinchi", user_id="7")

    assert speech.audio == WAV, "401 dan keyin tiklanmadi"
    assert server.issued == 2, "token yangilanmadi"


def test_401_bir_martadan_kop_urinilmaydi(tts, server):
    """Sir noto'g'ri bo'lsa har so'rov 401 beradi. Cheksiz aylanish serverga
    tinimsiz token so'rovi yog'dirardi."""
    tts.synthesize("birinchi", user_id="7")
    server.dead_tokens.update({"tok1", "tok2", "tok3"})
    with pytest.raises(TtsError) as caught:
        tts.synthesize("ikkinchi", user_id="7")
    assert caught.value.status == 401
    assert server.issued <= 2, f"token {server.issued} marta so'raldi"


def test_sir_hech_qachon_qaytmaydi(tts, server):
    """Xato matnida sir bo'lsa u log'ga va foydalanuvchiga tushardi."""
    server.generate_status = 500
    with pytest.raises(TtsError) as caught:
        tts.synthesize("salom", user_id="7")
    assert "s3cret" not in str(caught.value)


def test_audio_download_url_dan_OLINMAYDI(tts, server):
    """Hujjatdagi tuzoq: `download_url` `user_id` bo'yicha ENG SO'NGGI faylni
    beradi. Ikki foydalanuvchi bir vaqtda so'rasa, biri boshqasining
    audiosini eshitardi. Aynan fayl nomi bo'yicha olamiz."""
    tts.synthesize("salom", user_id="7")
    fetched = [c[0] for c in server.calls if c[0].startswith("/api/v1/tts/")]
    assert "/api/v1/tts/file/7__deadbeef.wav" in fetched
    assert not any("/audio/" in path for path in fetched), "download_url ishlatilgan"


def test_buzuq_fayl_nomi_rad_etiladi(tts, server):
    """Server nomi URL'ga qo'yilishidan oldin tekshiriladi."""
    server.audio_path = "/srv/audio/../../../etc/passwd"
    with pytest.raises(TtsError) as caught:
        tts.synthesize("salom", user_id="7")
    assert caught.value.status == 502
    assert not any("passwd" in c[0] for c in server.calls), "traversal so'rov ketdi"


@pytest.mark.parametrize("text", [
    "Kartangiz 8600123456789012 raqamiga tolov qiling",   # 16 xona -> 500
    "Versiya v1.2.3 chiqdi",                              # nuqtali guruh -> 422
    "Summa 1.000.000 som",
])
def test_xavfli_raqamda_normalizatsiya_ochiriladi(tts, server, text):
    """Bu naqshlarda serverning normalizatori YIQILADI (jonli tekshirilgan).
    Oldindan tanib, normalizatsiyasiz yuboramiz - xato javobdan afzal."""
    tts.synthesize(text, user_id="7")
    generate = next(c for c in server.calls if c[0] == "/api/v1/tts/generate")
    assert generate[1]["normalize_numbers"] is False


def test_oddiy_raqamda_normalizatsiya_qoladi(tts, server):
    """2450000 -> "ikki million ..." - bu ISHLAYDI va o'chirilmasligi kerak."""
    tts.synthesize("Qarzdorlik 2450000 som", user_id="7")
    generate = next(c for c in server.calls if c[0] == "/api/v1/tts/generate")
    assert generate[1]["normalize_numbers"] is True


def test_email_serverga_ketmaydi(tts, server):
    """`user_id` fayl nomiga kiradi va server fayllarni HECH QACHON
    o'chirmaydi - u yerga shaxsiy ma'lumot yozilmaydi."""
    tts.synthesize("salom", user_id="7")
    generate = next(c for c in server.calls if c[0] == "/api/v1/tts/generate")
    assert generate[1]["user_id"] == "7"
    assert "@" not in json.dumps(generate[1])


def test_navbat_toladi_503(server, monkeypatch):
    """Server BITTA GPU'da ketma-ket ishlaydi va 429 qaytarmaydi. Chegarani
    o'zimiz qo'ymasak, navbat cheksiz o'sardi va hamma timeout'ga uchrardi."""
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    started = threading.Event()
    release = threading.Event()
    real_open = server.open

    def slow(request, timeout=None):
        if request.full_url.endswith("/generate"):
            started.set()
            release.wait(3.0)
        return real_open(request, timeout)

    server.open = slow                           # type: ignore[method-assign]
    thread = threading.Thread(target=lambda: client.synthesize("uzoq", user_id="7"))
    thread.start()
    try:
        assert started.wait(3.0), "birinchi so'rov boshlanmadi"
        with pytest.raises(TtsError) as caught:
            client.synthesize("ikkinchi", user_id="8")
        assert caught.value.status == 503
    finally:
        release.set()
        thread.join(5.0)


def test_sirsiz_501(server):
    """Sir berilmagan bo'lsa ovoz o'chiq - lekin ilova ishlayveradi.

    503 EMAS: 503 "band, keyinroq" degani va klient qayta urinaverardi.
    Sozlanmagan xizmat esa kutish bilan tuzalmaydi."""
    client = TtsClient("http://tts", "frontend", "")
    assert not client.configured
    with pytest.raises(TtsError) as caught:
        client.synthesize("salom", user_id="7")
    assert caught.value.status == 501
    assert not server.calls, "sirsiz holda serverga so'rov ketdi"


def test_deadline_ikkinchi_sorovni_cheklaydi(server):
    """`/speak` IKKITA ketma-ket so'rov qiladi. Bitta so'rov timeout'i
    yetmaydi: 60 + 60 = 120 s, nginx esa aynan 120 s da uzadi va javob
    brauzerga yetib bormaydi. Ikkinchi so'rov qolgan byudjetni oladi."""
    client = TtsClient("http://tts", "frontend", "s3cret", timeout=60.0, deadline=5.0)
    seen: list[float | None] = []
    real = server.open

    def record(request, timeout=None):
        seen.append(timeout)
        return real(request, timeout)

    server.open = record                         # type: ignore[method-assign]
    client.synthesize("salom", user_id="7")
    # Oxirgi so'rov - faylni olish. U `timeout` (60) ni EMAS, `deadline` (5)
    # dan qolganini olishi kerak.
    assert seen[-1] is not None and seen[-1] <= 5.0, f"fayl so'rovi {seen[-1]} s oldi"


def test_deadline_tugasa_504(server, monkeypatch):
    """Byudjet tugagach kutishning ma'nosi yo'q - javobni hech kim ko'rmaydi."""
    import app.services.tts as module
    client = TtsClient("http://tts", "frontend", "s3cret", deadline=5.0)
    # 1-chaqiruv: `started`. 2-chaqiruv: `_left()` - byudjet allaqachon tugagan.
    clock = iter([0.0, 99.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock, 99.0))
    with pytest.raises(TtsError) as caught:
        client.synthesize("salom", user_id="7")
    assert caught.value.status == 504


def test_uzun_matn_qisqartiriladi():
    """Xato emas, qisqartirish: matn foydalanuvchi endigina aytgan gapi, va
    uzun matn bitta GPU navbatini ushlab turadi."""
    text = "bir ikki uch tort besh " * 40
    cut, truncated = clip(text, 60)
    assert truncated and len(cut) <= 60
    assert not cut.endswith(" "), "so'z o'rtasidan kesildi"


def test_qisqa_matn_tegilmaydi():
    assert clip("  salom dunyo  ", 600) == ("salom dunyo", False)


@pytest.mark.parametrize("text", [
    "8600123456789012",                       # karta, uzluksiz -> 500
    "Kartangiz 8600 1234 5678 9012 raqami",   # AJRATGICH BILAN: server bo'sh
    "8600-1234-5678-9012",                    # joyli guruhlarni bitta songa
    "1.000.000 som",                          # qo'shib yuboradi -> baribir 500
    "server 10.10.50.4 da",
    "versiya v1.2.3",
])
def test_risky_topadi(text):
    assert risky_for_normalizer(text), f"tuzoq o'tkazib yuborildi: {text}"


@pytest.mark.parametrize("text", [
    "2450000 som",                            # hujjatda ISHLAYDIGAN holatlar -
    "2 450 000 som",                          # bularda normalizatsiya
    "chegirma 15%",                           # o'chirilsa, raqamlar yomon
    "12.5 foiz",                              # o'qiladi
    "1-mart",
    "5-uy",
    "25.06.2026 yilda",                       # SANA - nuqtali guruh, lekin ishlaydi
    "24/7 ishlaymiz",
    "Soat 09:00 dan 17:00 gacha",
    "Shartnoma 25.06.2026, summa 2450000 som, chegirma 15%",
])
def test_risky_ishlaydiganlarga_tegmaydi(text):
    """Har bir noto'g'ri "ha" BUTUN gapdagi raqamlarni normalizatsiyasiz
    qoldiradi - ya'ni bitta sana tufayli "2450000" ham buzilib o'qilardi."""
    assert not risky_for_normalizer(text), f"ishlaydigan holat tuzoq deb belgilandi: {text}"


def test_dict_bolmagan_javob_502(tts, server, monkeypatch):
    """200 bilan `null` yoki ro'yxat kelsa, `.get()` AttributeError berardi -
    u TtsError EMAS va butun so'rovni 500 ga aylantirardi."""
    real = server.open

    def bad(request, timeout=None):
        if request.full_url.endswith("/generate"):
            return _ok(b"null")
        return real(request, timeout)

    server.open = bad                            # type: ignore[method-assign]
    with pytest.raises(TtsError) as caught:
        tts.synthesize("salom", user_id="7")
    assert caught.value.status == 502


def test_qisqa_ttl_da_kesh_olmaydi(server, monkeypatch):
    """`max(60, ttl) - 60` NOL berardi: qisqa muddatli token bilan har
    so'rov yangi token so'rardi."""
    real = server.open

    def short_ttl(request, timeout=None):
        if request.full_url.endswith("/auth/token"):
            server.issued += 1
            return _ok(json.dumps({"access_token": f"tok{server.issued}",
                                   "expires_in": 30}).encode())
        return real(request, timeout)

    server.open = short_ttl                      # type: ignore[method-assign]
    client = TtsClient("http://tts", "frontend", "s3cret")
    client.synthesize("bir", user_id="7")
    client.synthesize("ikki", user_id="7")
    assert server.issued == 1, f"token {server.issued} marta so'raldi"


def test_sir_xato_matnidan_ochiriladi(tts, server):
    """Server 422 da so'rov tanasini o'zicha qaytarishi mumkin (FastAPI
    validatsiya xatosi `input` ni aynan ko'chiradi) - u yerda esa
    `client_secret` turadi."""
    real = server.open

    def echoes_body(request, timeout=None):
        if request.full_url.endswith("/auth/token"):
            raise _http_error("/api/v1/auth/token", 422,
                              'Field required: {"client_secret": "s3cret"}')
        return real(request, timeout)

    server.open = echoes_body                    # type: ignore[method-assign]
    with pytest.raises(TtsError) as caught:
        tts.synthesize("salom", user_id="7")
    assert "s3cret" not in str(caught.value)
    assert "***" in str(caught.value)


# --- endpoint ---------------------------------------------------------------


def _speak(client, auth, **body):
    return client.post("/api/v1/tts/speak", json={"text": "salom", **body}, headers=auth)


def test_tokensiz_rad_etiladi(client, server):
    response = client.post("/api/v1/tts/speak", json={"text": "salom", "language": "uz"})
    assert response.status_code == 401
    assert not server.calls, "autentifikatsiyasiz TTS serveriga so'rov ketdi"


def test_wav_qaytadi(client, auth, monkeypatch, server):
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client", TtsClient("http://tts", "frontend", "s3cret"))
    response = _speak(client, auth, language="uz")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == WAV
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("language", ["ru", "en", "uz-Cyrl", "zh"])
def test_faqat_uz(client, auth, monkeypatch, server, language):
    """Birinchi bosqich ataylab faqat o'zbek lotin: model shu til uchun,
    kirill uchun translit yo'q, ru/en uchun ovoz umuman yo'q."""
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client", TtsClient("http://tts", "frontend", "s3cret"))
    response = _speak(client, auth, language=language)
    assert response.status_code == 400
    assert not server.calls, "qo'llab-quvvatlanmaydigan til serverga yuborildi"


def test_xato_ichki_hostni_ochmaydi(client, auth, monkeypatch, server):
    """Xabarda `10.10.50.4` yoki sir ko'rinsa, u brauzerga chiqib ketardi."""
    server.generate_status = 500
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client", TtsClient("http://10.10.50.4:8200", "frontend", "s3cret"))
    response = _speak(client, auth, language="uz")
    assert response.status_code == 502
    text = response.text
    assert "10.10.50.4" not in text and "s3cret" not in text
    assert "list index out of range" not in text


def test_yuqoridagi_401_brauzerga_502(client, auth, monkeypatch, server):
    """Yuqoridagi 401 = BIZNING `client_secret` noto'g'ri, ya'ni sozlama
    xatosi. Brauzerga 401 qaytarish "sessiyangiz tugadi" degan ma'no berardi,
    holbuki foydalanuvchi token'i joyida."""
    import app.api.v1.tts as module
    bad = TtsClient("http://tts", "frontend", "notogri")
    monkeypatch.setattr(module, "_client", bad)
    real = server.open
    server.open = lambda request, timeout=None: (   # type: ignore[method-assign]
        _raise(_http_error("/api/v1/auth/token", 401, "client_secret noto'g'ri"))
        if request.full_url.endswith("/auth/token") else real(request, timeout)
    )
    response = _speak(client, auth, language="uz")
    assert response.status_code == 502, "sozlama xatosi foydalanuvchi 401 iga aylandi"


def _raise(exc):
    raise exc


@pytest.mark.parametrize("voice", ["bosqa_ovoz", "uz_female_calm\nSOXTA LOG QATORI"])
def test_notogri_ovoz_422(client, auth, monkeypatch, server, voice):
    """`voice` erkin satr bo'lganda noma'lum qiymat xato matniga, u esa
    log'ga aynan ko'chirilardi - foydalanuvchi log'ga o'z qatorini
    yozdira olardi."""
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client", TtsClient("http://tts", "frontend", "s3cret"))
    response = _speak(client, auth, language="uz", voice=voice)
    assert response.status_code == 422
    assert not server.calls


def test_uz_yagona_til():
    """Bu bosqichda ro'yxat aynan bitta til bo'lishi kerak."""
    assert set(LOCALE_TO_TTS) == {"uz"}

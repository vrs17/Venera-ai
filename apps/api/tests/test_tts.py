"""Matn -> ovoz endpointi va TTS klienti.

TTS serverining O'ZI chaqirilmaydi: u ichki tarmoqda, VPN ortida va CI da
yo'q. Transport darajasi (`_open`) soxtalashtiriladi, ustidagi hamma
mantiq - token keshi, `download_url` tuzog'i, normalizator naqshlari,
navbat chegarasi va xatolarni foydalanuvchiga ko'rsatish - haqiqiy kod.
"""

from __future__ import annotations

import io
import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from app.services.tts import (
    LOCALE_TO_TTS,
    STREAM_FORMAT,
    TtsClient,
    TtsError,
    clip,
    risky_for_normalizer,
)

#: Bir bo'lak xom PCM (16-bit LE mono). Haqiqiy audio emas - biz
#: baytlarning O'ZGARMASDAN o'tishini tekshiramiz.
PCM = bytes(range(256)) * 4


class FakeServer:
    """`/tts/stream` kontraktini taqlid qiladi.

    ALMASHTIRISH NUQTASI `build_opener` - ya'ni klientning transport qatlami,
    HTTPError'ni TtsError'ga o'girish va sirni yashirish bilan birga, HAQIQIY
    kod bo'lib qoladi. Transportning o'zi almashtirilsa aynan shu mantiq
    testdan chetda qolardi.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None, dict]] = []
        #: Shu tokenlar endi yaroqsiz (401) - "muddati tugadi" ni modellaydi.
        self.dead_tokens: set[str] = set()
        self.stream_status: int | None = None
        self.issued = 0
        self.sample_rate = 8000
        self.chunks = [PCM, PCM, PCM]
        #: Nechanchi bo'lakdan keyin ulanish uziladi (oqim o'rtasidagi nosozlik).
        self.cut_after: int | None = None

    def open(self, request, timeout=None):
        path = "/" + request.full_url.split("://", 1)[1].split("/", 1)[1]
        payload = json.loads(request.data) if request.data else None
        token = (request.get_header("Authorization") or "").removeprefix("Bearer ")
        self.calls.append((path, payload, {"token": token}))

        if path == "/api/v1/auth/token":
            self.issued += 1
            return _ok(json.dumps({"access_token": f"tok{self.issued}",
                                   "token_type": "bearer", "expires_in": 86400}).encode())

        if token in self.dead_tokens:
            raise _http_error(path, 401, "Token muddati tugagan")

        if path == "/api/v1/tts/stream":
            if self.stream_status:
                raise _http_error(path, self.stream_status,
                                  "Matnni normalizatsiya qilib bo'lmadi: list index out of range")
            return _stream(self.chunks, {
                "x-stream-id": "abc123",
                "x-chunk-count": str(len(self.chunks)),
                "x-sample-rate": str(self.sample_rate),
                "content-type": f"audio/L16; rate={self.sample_rate}; channels=1",
            }, cut_after=self.cut_after)

        raise AssertionError(f"kutilmagan yo'l: {path}")


class _ok:
    """Minimal `urlopen` javobi - kontekst menejer va `read()`."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data, self._data = self._data, b""
            return data
        data, self._data = self._data[:size], self._data[size:]
        return data

    def close(self) -> None:
        self._data = b""


class _stream:
    """Bo'lak-bo'lak beradigan javob. `read()` bo'lak chegarasida to'xtaydi -
    haqiqiy chunked oqimdagi kabi."""

    def __init__(self, chunks, headers, cut_after=None) -> None:
        self._chunks = list(chunks)
        self.headers = headers
        self._cut_after = cut_after
        self._served = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if self._cut_after is not None and self._served >= self._cut_after:
            raise http.client.IncompleteRead(b"", 1)
        if not self._chunks:
            return b""
        self._served += 1
        return self._chunks.pop(0)

    def close(self) -> None:
        self.closed = True


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


def drain(client, text="salom", **kwargs) -> bytes:
    """Oqimni to'liq o'qib, PCM baytlarini qaytaradi."""
    return b"".join(client.stream(text, **kwargs).chunks)


# --- klient -----------------------------------------------------------------


def test_token_bir_marta_olinadi(tts, server):
    """Token 24 soat yashaydi - har sintezda qayta so'rash ortiqcha yuk."""
    for _ in range(3):
        drain(tts)
    tokens = [c for c in server.calls if c[0] == "/api/v1/auth/token"]
    assert len(tokens) == 1, f"token {len(tokens)} marta so'raldi"


def test_401_da_token_yangilanadi(tts, server):
    """Token so'rovlar ORASIDA eskiradi (24 soat yashaydi) yoki server qayta
    ishga tushadi. Foydalanuvchi buni ko'rmasligi kerak - bir marta jimgina
    yangilanadi va so'rov takrorlanadi."""
    drain(tts, "birinchi")
    server.dead_tokens.add("tok1")          # keshdagi token endi yaroqsiz
    server.calls.clear()

    pcm = drain(tts, "ikkinchi")

    assert pcm, "401 dan keyin tiklanmadi"
    assert server.issued == 2, "token yangilanmadi"


def test_401_bir_martadan_kop_urinilmaydi(tts, server):
    """Sir noto'g'ri bo'lsa har so'rov 401 beradi. Cheksiz aylanish serverga
    tinimsiz token so'rovi yog'dirardi."""
    drain(tts, "birinchi")
    server.dead_tokens.update({"tok1", "tok2", "tok3"})
    with pytest.raises(TtsError) as caught:
        drain(tts, "ikkinchi")
    assert caught.value.status == 401
    assert server.issued <= 2, f"token {server.issued} marta so'raldi"


def test_sir_hech_qachon_qaytmaydi(tts, server):
    """Xato matnida sir bo'lsa u log'ga va foydalanuvchiga tushardi."""
    server.stream_status = 500
    with pytest.raises(TtsError) as caught:
        drain(tts)
    assert "s3cret" not in str(caught.value)


@pytest.mark.parametrize("text", [
    "Kartangiz 8600123456789012 raqamiga tolov qiling",   # 16 xona -> 500
    "Versiya v1.2.3 chiqdi",                              # nuqtali guruh -> 422
    "Summa 1.000.000 som",
])
def test_xavfli_raqamda_normalizatsiya_ochiriladi(tts, server, text):
    """Bu naqshlarda serverning normalizatori YIQILADI (jonli tekshirilgan).
    Oldindan tanib, normalizatsiyasiz yuboramiz - xato javobdan afzal."""
    drain(tts, text)
    call = next(c for c in server.calls if c[0] == "/api/v1/tts/stream")
    assert call[1]["normalize_numbers"] is False


def test_oddiy_raqamda_normalizatsiya_qoladi(tts, server):
    """2450000 -> "ikki million ..." - bu ISHLAYDI va o'chirilmasligi kerak."""
    drain(tts, "Qarzdorlik 2450000 som")
    call = next(c for c in server.calls if c[0] == "/api/v1/tts/stream")
    assert call[1]["normalize_numbers"] is True


def test_shaxsiy_malumot_serverga_ketmaydi(tts, server):
    """`/generate` `user_id` ni TALAB qilardi va uni fayl nomiga yozardi, fayl
    esa hech qachon o'chirilmasdi. `/stream` da bunday maydon umuman yo'q -
    ya'ni bizning foydalanuvchimiz haqida u yerda hech narsa qolmaydi."""
    drain(tts)
    call = next(c for c in server.calls if c[0] == "/api/v1/tts/stream")
    assert set(call[1]) == {"text", "voice_profile", "speed",
                            "normalize_numbers", "format", "chunk_sec"}
    assert "@" not in json.dumps(call[1])


def test_sirsiz_501(server):
    """Sir berilmagan bo'lsa ovoz o'chiq - lekin ilova ishlayveradi.

    503 EMAS: 503 "band, keyinroq" degani va klient qayta urinaverardi.
    Sozlanmagan xizmat esa kutish bilan tuzalmaydi."""
    client = TtsClient("http://tts", "frontend", "")
    assert not client.configured
    with pytest.raises(TtsError) as caught:
        drain(client)
    assert caught.value.status == 501
    assert not server.calls, "sirsiz holda serverga so'rov ketdi"


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
    drain(client, "bir")
    drain(client, "ikki")
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
        drain(tts)
    assert "s3cret" not in str(caught.value)
    assert "***" in str(caught.value)



def test_generate_ISHLATILMAYDI(tts, server):
    """`/generate` butun xabar tayyor bo'lgunicha jim turadi (19 s xabar
    uchun 11 s) va faylni serverda qoldiradi. `/stream` da birinchi bayt
    ~1.1 s da keladi va fayl umuman yaratilmaydi."""
    drain(tts)
    paths = [c[0] for c in server.calls]
    assert "/api/v1/tts/stream" in paths
    assert not any("generate" in p or "/audio/" in p or "/file/" in p for p in paths), paths


def test_l16_soraladi(tts, server):
    """`wav` EMAS: oqim boshida umumiy uzunlik noma'lum, shuning uchun server
    sarlavhaga 0xFFFFFFFF yozadi va pleyerlar davomiylikni 74 soat deb
    ko'rsatadi."""
    drain(tts)
    call = next(c for c in server.calls if c[0] == "/api/v1/tts/stream")
    assert call[1]["format"] == STREAM_FORMAT == "l16"
    assert 0.5 <= call[1]["chunk_sec"] <= 10, "server bu diapazondan tashqarisiga 422 beradi"


def test_baytlar_ozgarmasdan_otadi(tts, server):
    server.chunks = [b"\x01\x02", b"\x03\x04", b"\x05\x06"]
    assert drain(tts) == b"\x01\x02\x03\x04\x05\x06"


def test_bolaklar_alohida_keladi(tts, server):
    """Oqimning butun ma'nosi shu: bo'laklar YIG'ILMAYDI, kelgani zahoti
    uzatiladi. Bitta baytga birlashtirilsa TTFB afzalligi yo'qolardi."""
    server.chunks = [PCM, PCM, PCM]
    parts = list(tts.stream("salom").chunks)
    assert len(parts) == 3, f"{len(parts)} ta bo'lak - oqim yig'ilib qolgan"


def test_sarlavhalar_oqiladi(tts, server):
    server.sample_rate = 16000
    speech = tts.stream("salom")
    assert speech.sample_rate == 16000, "chastota qattiq yozilgan"
    assert speech.chunk_count == 3
    assert speech.stream_id == "abc123"
    list(speech.chunks)


def test_sarlavha_yoq_bolsa_default(tts, server, monkeypatch):
    """Sarlavha yetishmasa 8000 ga tushamiz - lekin yiqilmaymiz."""
    real = server.open

    def no_headers(request, timeout=None):
        response = real(request, timeout)
        if hasattr(response, "headers") and "x-sample-rate" in response.headers:
            response.headers = {}
        return response

    server.open = no_headers                     # type: ignore[method-assign]
    speech = tts.stream("salom")
    assert speech.sample_rate == 8000
    list(speech.chunks)


def test_oqim_ortasida_uzilsa_502(tts, server):
    """Server 200 yuborib bo'lgach statusni o'zgartira olmaydi, shuning uchun
    ulanishni ATAYLAB uzadi. Bu jimgina o'tib ketmasligi kerak."""
    server.cut_after = 2
    stream = tts.stream("salom")
    got = []
    with pytest.raises(TtsError) as caught:
        for part in stream.chunks:
            got.append(part)
    assert caught.value.status == 502
    assert len(got) == 2, "uzilishdan oldingi bo'laklar berilmadi"
    assert "abc123" in str(caught.value), "stream_id log uchun xabarda yo'q"


def test_slot_oqim_tugagach_bosaydi(server):
    """Slot oqim DAVOMIDA band turadi. Erta bo'shatilsa, ikkinchi so'rov
    GPU'ni bir vaqtda bo'lishib, ikkalasining ham TTFB'sini buzardi."""
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    stream = client.stream("birinchi")
    with pytest.raises(TtsError) as caught:
        client.stream("ikkinchi")
    assert caught.value.status == 503, "oqim ochiq turganda slot bo'sh ko'rindi"
    list(stream.chunks)                          # oqimni tugatamiz
    list(client.stream("uchinchi").chunks)        # endi o'tishi kerak


def test_slot_xatoda_ham_bosaydi(server):
    """Oqim ochilishida xato bo'lsa slot qaytarilmasa, ilova bir necha
    xatodan keyin butunlay to'xtab qolardi."""
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    server.stream_status = 500
    for _ in range(3):
        with pytest.raises(TtsError):
            client.stream("salom")
    server.stream_status = None
    assert b"".join(client.stream("salom").chunks), "slot sizib ketdi"


def test_uzilgan_oqim_ham_slotni_bosaydi(server):
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    server.cut_after = 1
    with pytest.raises(TtsError):
        list(client.stream("salom").chunks)
    server.cut_after = None
    assert b"".join(client.stream("salom").chunks), "uzilishdan keyin slot sizdi"


def test_tashlab_ketilgan_oqim_slotni_qaytaradi(server):
    """Oqim ochilib, generator HECH QACHON boshlanmasa ham slot qaytadi.

    BU AYNAN JONLI TIZIMDA BO'LGAN NOSOZLIK. Brauzer sarlavhalar
    kelgandan keyin, lekin javob tanasi boshlanishidan oldin uzilsa,
    Starlette generatorni umuman harakatga keltirmaydi. Generatorning
    `try/finally` si esa faqat u birinchi marta ishga tushganda
    qurollanadi - ya'ni eski kodda `finally` o'tmasdi va slot MANGU band
    qolardi. Jurnalda o'lchandi: 68 oqim ochilgan, 66 javob qaytgan,
    ikki slot oqib ketgan va `max_concurrent=2` bo'lgani uchun ovoz
    xizmati butunlay o'lgan.

    Chegaradan IKKI BAROBAR ko'p tashlab ketamiz: eski kod ikkinchisida
    o'lardi.
    """
    import gc

    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=2, queue_wait=0.05)
    for _ in range(4):                  # chegaradan IKKI BAROBAR ko'p
        speech = client.stream("salom")
        del speech                      # generator BOSHLANMADI
        gc.collect()

    # ATAYLAB `busy()` ISHLATILMAYDI. Tekshiruv shu satr bo'lishi kerak:
    # eski kodda to'rtta tashlab ketilgandan keyin ikki slot band qolib,
    # bu chaqiruv `TtsError(503)` bilan yiqilardi. `busy()` bilan yozilsa
    # test eski kodda "bunday atribut yo'q" deb yiqilardi - ya'ni oqishning
    # O'ZINI isbotlamasdan.
    assert b"".join(client.stream("salom").chunks), "slot sizib ketdi"


def test_close_slotni_qaytaradi(server):
    """`close()` - birinchi to'r: endpoint uni `finally` da chaqiradi."""
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    speech = client.stream("salom")
    assert client.busy() == 1
    speech.close()                      # tana o'qilmadi
    assert client.busy() == 0, "close() slotni qaytarmadi"
    assert b"".join(client.stream("salom").chunks), "close() dan keyin slot sizdi"


def test_takroriy_qaytarish_xavfsiz(server):
    """Uchta to'r ham bitta slotni qaytarishga urinadi.

    Qaytarish idempotent bo'lmasa `BoundedSemaphore` ortiqcha
    `release()` da `ValueError` tashlar edi - yoki undan battari,
    chegara o'sib ketib, GPU navbatiga bir vaqtda bir nechta so'rov
    tushardi.
    """
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    speech = client.stream("salom")
    speech.close()
    speech.close()
    list(speech.chunks)                 # generatorni ham tugatib ko'ramiz
    assert speech.slot is not None
    assert speech.slot.release() is False, "ikkinchi qaytarish True dedi"
    assert client.busy() == 0, f"chegara buzildi: band={client.busy()}"
    # Chegara O'SMAGANINI tekshiramiz: bitta oqim ochilgach ikkinchisi 503.
    held = client.stream("birinchi")
    with pytest.raises(TtsError) as caught:
        client.stream("ikkinchi")
    assert caught.value.status == 503, "ortiqcha release chegarani oshirib yubordi"
    held.close()


def test_soat_qotib_qolgan_slotni_qaytaradi(server, monkeypatch):
    """Uchinchi to'r: yuqoridagi ikkisi ham ishlamasa, soat qaytaradi.

    Bu NOSOZLIK yo'li, oddiy yo'l emas - shu sababli jonli kodda chegara
    180 s va WARNING bilan yoziladi. Testda uni qisqartiramiz.
    """
    import app.services.tts as mod

    monkeypatch.setattr(mod, "_SLOT_CEILING", 0.15)
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    speech = client.stream("salom")
    assert client.busy() == 1
    # Ikkinchi to'rni ATAYLAB o'chiramiz: havola saqlanadi, ya'ni obyekt
    # yig'ilmaydi va `close()` ham chaqirilmaydi. Faqat soat qoladi.
    deadline = time.monotonic() + 3.0
    while client.busy() == 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.busy() == 0, "soat qotib qolgan slotni qaytarmadi"
    assert speech is not None            # havola hali ham tirik


def test_synthesize_wav_haqiqiy_sarlavha_yozadi():
    """Serverning `format=wav` i oqim boshida uzunlikni bilmaydi va
    0xFFFFFFFF yozadi. Oflayn fayl uchun bu yaramaydi - saytdagi audio
    74 soat deb ko'rinardi."""
    import wave, io as _io
    fake = FakeServer()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    import urllib.request as _u
    original = _u.build_opener
    _u.build_opener = lambda *a, **kw: Opener()
    try:
        data = TtsClient("http://tts", "frontend", "s3cret").synthesize_wav("salom")
    finally:
        _u.build_opener = original

    with wave.open(_io.BytesIO(data)) as w:
        assert w.getframerate() == 8000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == len(PCM) * 3 // 2


# --- endpoint ---------------------------------------------------------------


def _speak(client, auth, **body):
    return client.post("/api/v1/tts/speak", json={"text": "salom", **body}, headers=auth)


def test_tokensiz_rad_etiladi(client, server):
    response = client.post("/api/v1/tts/speak", json={"text": "salom", "language": "uz"})
    assert response.status_code == 401
    assert not server.calls, "autentifikatsiyasiz TTS serveriga so'rov ketdi"


def test_pcm_oqimi_qaytadi(client, auth, monkeypatch, server):
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client", TtsClient("http://tts", "frontend", "s3cret"))
    response = _speak(client, auth, language="uz")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/L16")
    assert "rate=8000" in response.headers["content-type"]
    assert response.content == PCM * 3
    assert response.headers["cache-control"] == "no-store"
    # nginx uchun: bu yo'lda buferlash o'chiq bo'lishi kerak, aks holda u
    # butun oqimni yig'ib beradi va streaming ma'nosini yo'qotadi.
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["x-venera-sample-rate"] == "8000"


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
    server.stream_status = 500
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

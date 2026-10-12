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
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import wave

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
        #: Haqiqiy normalizator xatosi (jonli, 2026-09-23): qo'shimchasi
        #: YOPISHGAN sana (`09.09.2025dan`) -> 422.
        self.glued_date_bug = False
        #: Biz bilmagan naqsh: normalizatsiya yoqilgan HAR QANDAY matn -> 422.
        self.normalizer_crash = False

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
            if payload["normalize_numbers"] and (
                self.normalizer_crash
                or (self.glued_date_bug
                    and re.search(r"\d{1,2}\.\d{1,2}\.\d{4}[^\W\d_]", payload["text"]))
            ):
                raise _http_error(path, 422, "invalid literal for int() with base 10: '09.2025'")
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


@pytest.mark.parametrize("text", [
    "Siz 01.09.2026, 03.09.2026 va 05.09.2026 kunlari kechikdingiz",
    "Ta'til 25.09.2026 - 30.09.2026",
    "Ta'til 25.09.2026-30.09.2026",
])
def test_sanalar_royxati_karta_emas(text):
    """JONLI (2026-09-23): ikki sana yonma-yon kelsa "16 xonali raqam" deb
    topilardi va BUTUN javob normalizatsiyasiz ketardi - sanalar "mundoq
    suzish ikki ming yigirma besh" bo'lib eshitildi. Normalizator esa ularni
    to'g'ri o'qiydi."""
    assert not risky_for_normalizer(text), f"sanalar karta deb topildi: {text}"


def test_yopishgan_sana_ovozsiz_qolmaydi(tts, server):
    """JONLI XATO (2026-09-23): "...09.09.2025dan tuzilgan..." javobi 422
    bilan rad etildi va odam javobni ESHITMADI. Endi sana serverga raqam
    bo'lib umuman bormaydi - so'z bilan yoziladi (`speech_text.py`)."""
    server.glued_date_bug = True
    assert drain(tts, "Shartnoma 09.09.2025dan tuzilgan.") == PCM * 3
    calls = [c[1] for c in server.calls if c[0] == "/api/v1/tts/stream"]
    assert len(calls) == 1, "zahiraga tushdi - sana so'zga aylanmadi"
    assert calls[0]["normalize_numbers"] is True
    assert "to'qqizinchi sentabrdan tuzilgan" in calls[0]["text"]
    assert "09.09.2025" not in calls[0]["text"]


def test_sozlar_qisqartirishdan_keyin_qoshiladi(tts, server):
    """Klient javobni 3000 belgiga O'ZI sig'diradi. So'zlar matnni uzaytiradi
    - agar ular qisqartirishdan OLDIN qo'shilsa, sig'dirilgan javobning
    oxiri shu uzayish hisobiga kesilib qolardi."""
    text = ("Muddat 25.09.2026. " * 150).strip()        # 2849 belgi, chegaradan past
    assert len(text) < 3000
    drain(tts, text, max_chars=3000)
    sent = next(c[1]["text"] for c in server.calls if c[0] == "/api/v1/tts/stream")
    assert sent.count("sentabr") == 150, "javob oxiri kesildi"


def test_nomalum_naqshda_normalizatsiyasiz_qayta_yuboriladi(tts, server):
    """Biz bilmagan yangi naqsh: raqamlar yomonroq o'qilgani jim qolishdan
    afzal."""
    server.normalizer_crash = True
    assert drain(tts, "Qarzdorlik 2450000 som") == PCM * 3
    flags = [c[1]["normalize_numbers"] for c in server.calls if c[0] == "/api/v1/tts/stream"]
    assert flags == [True, False]


def test_500_da_qayta_yuborilmaydi(tts, server):
    """500 - GPU/model xatosi: qayta urinish uni tuzatmaydi, faqat GPU
    navbatiga ikkinchi og'ir so'rov qo'shadi."""
    server.stream_status = 500
    with pytest.raises(TtsError):
        drain(tts)
    assert sum(c[0] == "/api/v1/tts/stream" for c in server.calls) == 1


def test_zahira_ham_yiqilsa_bir_marta(tts, server):
    """Zahira BITTA: ikkinchi 422 foydalanuvchiga o'z xabari bilan boradi."""
    server.stream_status = 422
    with pytest.raises(TtsError) as caught:
        drain(tts)
    assert caught.value.status == 422
    assert sum(c[0] == "/api/v1/tts/stream" for c in server.calls) == 2


def test_normalizatsiyasiz_matn_qayta_yuborilmaydi(tts, server):
    """Normalizatsiya allaqachon o'chiq bo'lsa, zahira ma'nosiz."""
    server.stream_status = 422
    with pytest.raises(TtsError):
        drain(tts, "Kartangiz 8600123456789012 raqami")
    assert sum(c[0] == "/api/v1/tts/stream" for c in server.calls) == 1


def test_zahira_slotni_sizdirmaydi(server):
    """Qayta urinish slot ichida: ikkalasi yiqilsa ham slot qaytishi kerak."""
    client = TtsClient("http://tts", "frontend", "s3cret", max_concurrent=1, queue_wait=0.05)
    server.stream_status = 422
    for _ in range(3):
        with pytest.raises(TtsError):
            client.stream("salom")
    server.stream_status = None
    assert b"".join(client.stream("salom").chunks), "slot sizib ketdi"


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


def test_endpoint_yopishgan_sanali_javob_ovozli(client, auth, monkeypatch, server):
    """Foydalanuvchi ko'rgan holat: "Javob keldi, lekin ovoz tayyorlanmadi"."""
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client", TtsClient("http://tts", "frontend", "s3cret"))
    server.glued_date_bug = True
    response = _speak(client, auth, language="uz",
                      text="Ariza tayyorlandi: 09.09.2025dan tuzilgan mehnat shartnomasini "
                           "bekor qilishni so'rayman. Sana: 25.09.2026")
    assert response.status_code == 200
    assert response.content == PCM * 3


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


# --- /tts/clip: mobil ilova uchun to'liq WAV --------------------------------
#
# expo-audio xom PCM oqimini o'ynata olmaydi - faqat tayyor faylni. Klient
# javobni gap chegarasida bo'laklaydi va har bo'lakni shu yo'ldan to'liq WAV
# qilib oladi.


@pytest.fixture
def clip_tts(monkeypatch, server):
    """Endpoint ishlatadigan klient - soxta transport ustida. `queue_wait`
    qisqa: "band" holati testni bir soniya to'xtatmasin."""
    import app.api.v1.tts as module

    client = TtsClient("http://tts", "frontend", "s3cret", queue_wait=0.05)
    monkeypatch.setattr(module, "_client", client)
    return client


def _clip(client, auth, **body):
    return client.post("/api/v1/tts/clip", json={"text": "Salom, men Barno.", **body},
                       headers=auth)


def _stream_calls(server) -> list[dict]:
    return [c[1] for c in server.calls if c[0] == "/api/v1/tts/stream"]


def test_clip_haqiqiy_wav_qaytaradi(client, auth, server, clip_tts):
    """Sarlavhadagi hajm HAQIQIY bo'lishi shart: serverning `format=wav` i
    `0xFFFFFFFF` yozadi va pleyer davomiylikni 74 soat deb ko'radi."""
    response = _clip(client, auth)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-venera-truncated"] == "0"
    assert response.headers["x-venera-sample-rate"] == "8000"
    with wave.open(io.BytesIO(response.content)) as w:
        assert w.getframerate() == 8000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        frames = w.getnframes()
        assert frames == len(PCM) * 3 // 2
        assert w.readframes(frames) == PCM * 3, "audio o'zgarib ketdi"
    assert response.headers["x-venera-duration-ms"] == str(round(frames * 1000 / 8000))
    # RIFF hajmlari baytlarning o'zi bilan mos (`wave` ham shuni tekshiradi,
    # lekin mobil `parseWav` bo'laklarni o'zi yuradi).
    data = response.content
    assert int.from_bytes(data[4:8], "little") == len(data) - 8
    assert int.from_bytes(data[40:44], "little") == len(PCM) * 3
    assert clip_tts.busy() == 0, "slot qaytmadi"


def test_clip_tokensiz_401(client, server, clip_tts):
    response = client.post("/api/v1/tts/clip", json={"text": "salom"})
    assert response.status_code == 401
    assert not server.calls, "autentifikatsiyasiz TTS serveriga so'rov ketdi"


def test_clip_600_belgigacha_otadi(client, auth, server, clip_tts):
    """600 - chegara o'zi: klient <=350 yuboradi, zaxira bilan."""
    response = _clip(client, auth, text="a" * 600)
    assert response.status_code == 200, response.text


def test_clip_601_belgi_422(client, auth, server, clip_tts):
    """Bitta so'rov uzun bo'lsa umumiy ikki slotdan birini o'nlab soniya
    ushlaydi. Qisqartirish emas, rad etish: klient bo'laklashi kerak."""
    response = _clip(client, auth, text="a" * 601)
    assert response.status_code == 422
    assert response.json()["message"]
    assert not server.calls


@pytest.mark.parametrize("voice", ["bosqa_ovoz", "uz_female_calm\nSOXTA LOG QATORI"])
def test_clip_notogri_ovoz_422(client, auth, server, clip_tts, voice):
    response = _clip(client, auth, voice=voice)
    assert response.status_code == 422
    assert not server.calls


@pytest.mark.parametrize("speed", [2.0, 0.5, 0.69, 1.31])
def test_clip_tezlik_chegarada_422(client, auth, server, clip_tts, speed):
    response = _clip(client, auth, speed=speed)
    assert response.status_code == 422
    assert not server.calls


def test_clip_tezlik_nan_422(client, auth, server, clip_tts):
    """`NaN` har qanday taqqoslashda "yolg'on" - chegarani jimgina
    aylanib o'tmasligi kerak (Python `json` uni qabul qiladi)."""
    response = client.post("/api/v1/tts/clip", content='{"text": "salom", "speed": NaN}',
                           headers={**auth, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert not server.calls


@pytest.mark.parametrize("language", ["ru", "en", "uz-Cyrl"])
def test_clip_faqat_uz(client, auth, server, clip_tts, language):
    response = _clip(client, auth, language=language)
    assert response.status_code == 400
    assert not server.calls, "qo'llab-quvvatlanmaydigan til serverga yuborildi"


def test_clip_bosh_matn_400(client, auth, server, clip_tts):
    response = _clip(client, auth, text="   ")
    assert response.status_code == 400
    assert not server.calls


def test_clip_sirsiz_501(client, auth, server, monkeypatch):
    """501 - "hali yoqilmagan": klient buni ilova davomida eslab qoladi va
    qayta urinmaydi. 503 bo'lsa cheksiz urinardi."""
    import app.api.v1.tts as module

    monkeypatch.setattr(module, "_client", TtsClient("http://tts", "frontend", ""))
    response = _clip(client, auth)
    assert response.status_code == 501
    assert response.json()["message"] == "Ovoz javobi hali yoqilmagan"
    assert not server.calls


def test_clip_band_503_retry_after(client, auth, server, clip_tts):
    """Ikki slot ham band (boshqa foydalanuvchilarning oqimi) - darhol 503
    va `Retry-After`: navbat cheksiz o'smasin."""
    held = [clip_tts.stream("birinchi"), clip_tts.stream("ikkinchi")]
    try:
        server.calls.clear()
        response = _clip(client, auth)
        assert response.status_code == 503
        assert response.headers["retry-after"] == "1"
        assert response.json()["message"].startswith("Ovoz xizmati band")
        assert not _stream_calls(server), "band paytida TTS ga so'rov ketdi"
    finally:
        for speech in held:
            speech.close()
    assert clip_tts.busy() == 0


def test_clip_bir_odam_umumiy_slotlarni_egallay_olmaydi_503(client, auth, server, clip_tts,
                                                           monkeypatch):
    """Uzilgan so'rov serverda oxirigacha sintez qilinadi (sync route). Bitta odam
    ketma-ket bo'lib gapirsa ikkala umumiy TTS slotini egallab, BOSHQALARNI 503 ga
    tushirardi - shuning uchun odamga o'z chegarasi (503 + Retry-After, klient qayta urinadi)."""
    import app.api.v1.tts as module

    monkeypatch.setattr(module, "_CLIP_PER_USER", 0)
    server.calls.clear()
    response = _clip(client, auth)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["message"].startswith("Ovoz xizmati band")
    assert not _stream_calls(server), "chegaradan oshgan so'rov TTS ga ketdi"


def test_clip_odam_sloti_muvaffaqiyat_va_xatoda_qaytadi(client, auth, server, clip_tts, monkeypatch):
    import app.api.v1.tts as module

    seen: list[int] = []
    real = clip_tts.synthesize_clip

    def spy(*args, **kwargs):
        seen.append(sum(module._clip_inflight.values()))
        return real(*args, **kwargs)

    monkeypatch.setattr(clip_tts, "synthesize_clip", spy)
    assert _clip(client, auth).status_code == 200
    server.cut_after = 1
    assert _clip(client, auth).status_code == 502
    server.cut_after = None
    assert seen == [1, 1], "sintez paytida odam sloti hisoblanmadi"
    assert module._clip_inflight == {}, "odam sloti qaytmadi"


def test_clip_slotlar_javob_sarlavhasidan_oldin_qaytadi(client, auth, server, clip_tts,
                                                       monkeypatch):
    """Mobil klient keyingi bo'lakni shu javobning SARLAVHASI kelishi bilan so'raydi
    (77-440 KB tanani kutmaydi). Bu faqat sarlavha ketishidan OLDIN ikkala o'rin -
    TTS semaforasi va odam sloti - bo'shagan bo'lsa to'g'ri: aks holda keyingi so'rov
    o'z odamining chegarasiga urilib 503 olardi va bir odam ikki sintezni ushlardi.
    `Response` yaratilishi - sarlavha ketishidan oldingi oxirgi nuqta."""
    import app.api.v1.tts as module

    seen: list[tuple[dict, int]] = []
    real = module.Response

    class Spy(real):
        def __init__(self, *args, **kwargs):
            seen.append((dict(module._clip_inflight), clip_tts.busy()))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "Response", Spy)
    monkeypatch.setattr(module, "_CLIP_PER_USER", 1)
    assert _clip(client, auth).status_code == 200
    assert seen == [({}, 0)], "sarlavha ketayotganda o'rin hali band"
    # Ketma-ket ikkinchi so'rov (klient sarlavhada yuboradi) - 503 emas.
    assert _clip(client, auth).status_code == 200


def test_clip_oqim_ortasida_uzilsa_502_va_slot_qaytadi(client, auth, server, clip_tts):
    """HAMMASI YOKI HECH NARSA: yarim WAV klientda gapning yarmini o'ynatardi.
    200 hali yuborilmagan - shuning uchun bu yerda HAQIQIY xato statusi."""
    server.cut_after = 1
    response = _clip(client, auth)
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["message"] == "Ovoz xizmati javob bermadi"
    assert clip_tts.busy() == 0, "uzilgan oqim slotni qaytarmadi"
    server.cut_after = None
    assert _clip(client, auth).status_code == 200


def test_clip_timeout_504(client, auth, server, clip_tts, monkeypatch):
    """Oqim o'rtasida jim qolish (timeout) - 504, yarim audio emas."""
    real = server.open

    def stalls(request, timeout=None):
        response = real(request, timeout)
        if request.full_url.endswith("/tts/stream"):
            served = {"n": 0}
            original = response.read

            def read(size=-1):
                served["n"] += 1
                if served["n"] > 1:
                    raise TimeoutError("timed out")
                return original(size)

            response.read = read
        return response

    server.open = stalls                         # type: ignore[method-assign]
    response = _clip(client, auth)
    assert response.status_code == 504
    assert clip_tts.busy() == 0


def test_clip_bosh_audio_502(client, auth, server, clip_tts):
    """Uzunligi nol fayl ba'zi pleyerlarda "tugadi" hodisasini bermaydi va
    klient navbati qotadi - bo'sh audio aniq xato bo'lishi kerak."""
    server.chunks = []
    response = _clip(client, auth)
    assert response.status_code == 502
    assert clip_tts.busy() == 0


def test_clip_ovoz_va_tezlik_yuqoriga_ketadi(client, auth, server, clip_tts):
    response = _clip(client, auth, voice="uz_male_news", speed=1.1)
    assert response.status_code == 200
    call = _stream_calls(server)[-1]
    assert call["voice_profile"] == "uz_male_news"
    assert call["speed"] == 1.1
    # Oqim tafsilotlari `/speak` bilan bir xil: xom PCM so'raladi (biz o'zimiz
    # WAV ga o'raymiz) va bo'lak davomiyligi server diapazonida.
    assert call["format"] == "l16"
    assert 0.5 <= call["chunk_sec"] <= 10


def test_clip_bosh_ovoz_va_tezlik_sozlamadan(client, auth, server, clip_tts, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "tts_voice", "uz_male_news")
    monkeypatch.setattr(settings, "tts_speed", 0.9)
    assert _clip(client, auth).status_code == 200
    call = _stream_calls(server)[-1]
    assert (call["voice_profile"], call["speed"]) == ("uz_male_news", 0.9)


def test_clip_sanalar_sozga_aylanadi(client, auth, server, clip_tts):
    """`/speak` dagi `for_speech` va normalizator to'rlari shu yo'lda HAM
    ishlaydi - alohida yo'l yozilmagan."""
    server.glued_date_bug = True
    response = _clip(client, auth, text="Shartnoma 09.09.2025dan tuzilgan.")
    assert response.status_code == 200
    calls = _stream_calls(server)
    assert len(calls) == 1
    assert "09.09.2025" not in calls[0]["text"]


def test_clip_loyiha_kodi_nom_bilan(client, auth, server, monkeypatch):
    """Talaffuz lug'ati klient orqali ishlaydi: TTS serveriga kod emas, nom ketadi."""
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client", TtsClient(
        "http://tts", "frontend", "s3cret", queue_wait=0.05,
        spoken_names=lambda: {"DVSIB": "Raqamli bank"}))
    response = _clip(client, auth, text="DVSIB loyihasida DVSIB-266 yopildi.")
    assert response.status_code == 200
    assert _stream_calls(server)[-1]["text"] == "Raqamli bank loyihasida DVSIB-266 yopildi."


def test_clip_xato_ichki_hostni_ochmaydi(client, auth, server, monkeypatch):
    server.stream_status = 500
    import app.api.v1.tts as module
    monkeypatch.setattr(module, "_client",
                        TtsClient("http://10.10.50.4:8200", "frontend", "s3cret", queue_wait=0.05))
    response = _clip(client, auth)
    assert response.status_code == 502
    text = response.text
    assert "10.10.50.4" not in text and "s3cret" not in text
    assert "list index out of range" not in text


def test_clip_yuqoridagi_401_502(client, auth, server, clip_tts):
    """Yuqoridagi 401 - BIZNING sir noto'g'ri. Foydalanuvchiga 401 qaytarsa
    ilova "sessiya tugadi" deb uni tizimdan chiqarib yuborardi."""
    server.dead_tokens.update({"tok1", "tok2", "tok3"})
    response = _clip(client, auth)
    assert response.status_code == 502


def test_clip_matni_logga_tushmaydi(client, auth, server, clip_tts, caplog):
    """Matn - foydalanuvchining HRM javobi. Muvaffaqiyatli so'rovda ham,
    yuqoridagi server matnni xato ichida qaytarganda ham log'ga tushmasin."""
    marker = "Maxfiy maosh 7777777 som"
    real = server.open

    def echoes_text(request, timeout=None):
        if request.full_url.endswith("/tts/stream") and server.stream_status:
            payload = json.loads(request.data)
            server.calls.append(("/api/v1/tts/stream", payload, {}))
            raise _http_error("/api/v1/tts/stream", 500, f"xato: {payload['text']}")
        return real(request, timeout)

    server.open = echoes_text                    # type: ignore[method-assign]
    caplog.set_level(logging.DEBUG)
    assert _clip(client, auth, text=marker).status_code == 200
    server.stream_status = 500
    assert _clip(client, auth, text=marker).status_code == 502
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "7777777" not in logged and "maosh" not in logged


def test_clip_hisobi_clip_yorligi_va_savol_kaliti_bilan(client, auth, server, clip_tts,
                                                        _isolated_analytics):
    """Admin tahlilida javob bo'laklari (`clip`) oqimdan (`speak`) ajralib
    ko'rinsin, ovoz esa o'sha savolga bog'lansin."""
    from app.services import analytics

    turn_id = "cd" * 16
    response = client.post("/api/v1/tts/clip",
                           headers={**auth, "X-Venera-Turn": turn_id, "X-Venera-Client": "mobile"},
                           json={"text": "salom", "language": "uz"})
    assert response.status_code == 200
    # Yaroqsiz kalit - e'tiborsiz, xato emas.
    response = client.post("/api/v1/tts/clip", headers={**auth, "X-Venera-Turn": "../x"},
                           json={"text": "salom", "language": "uz"})
    assert response.status_code == 200

    assert analytics.flush(5.0)
    calls = _isolated_analytics.rows(
        "SELECT * FROM api_calls WHERE service='tts' AND op != 'token' ORDER BY id")
    assert [c["op"] for c in calls] == ["clip", "clip"]
    first, second = calls
    assert (first["turn_id"], first["channel"], first["status"]) == (turn_id, "mobile", "ok")
    assert json.loads(first["units"])["audioSec"] == round(len(PCM) * 3 / 16000, 2)
    assert second["turn_id"] is None


# --- synthesize_clip -----------------------------------------------------------


def test_synthesize_clip_davomiylik_va_qisqartirish(tts, server):
    server.chunks = [b"\0\0" * 8000]             # 1 s, 8 kHz
    audio = tts.synthesize_clip("salom " * 200, max_chars=60)
    assert audio.sample_rate == 8000
    assert audio.duration_ms == 1000
    assert audio.truncated is True
    assert len(_stream_calls(server)[-1]["text"]) <= 60 + 40   # `for_speech` uzaytirishi mumkin


def test_synthesize_clip_toq_baytni_tashlaydi(tts, server):
    """16-bit da toq bayt - yarim namuna; u `data` bo'lagini toq qilib RIFF
    ni buzardi (toq bo'lak to'ldirilishi shart)."""
    server.chunks = [b"\x01\x02\x03"]
    audio = tts.synthesize_clip("salom")
    with wave.open(io.BytesIO(audio.wav)) as w:
        assert w.getnframes() == 1
        assert w.readframes(1) == b"\x01\x02"
    assert len(audio.wav) % 2 == 0


def test_synthesize_wav_yorligi_ozgarmagan(server, _isolated_analytics):
    """Ishga tushishdagi qizdirish avvalgidek `speak` bo'lib ko'rinadi."""
    from app.services import analytics

    TtsClient("http://tts", "frontend", "s3cret").synthesize_wav("salom")
    assert analytics.flush(5.0)
    ops = [r["op"] for r in _isolated_analytics.rows(
        "SELECT op FROM api_calls WHERE service='tts' ORDER BY id")]
    assert ops == ["token", "speak"]

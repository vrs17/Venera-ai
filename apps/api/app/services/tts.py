"""TTS klienti - matnni o'zbekcha ovozga o'giradi.

Server `10.10.50.4:8200` da turadi. STT Router'dan uchta jihati bilan farq
qiladi va shu farqlar bu modulning butun shaklini belgilaydi:

  1. AUTENTIFIKATSIYA BOR. `client_id`/`client_secret` -> 24 soatlik token.
     Token keshlanadi, aks holda har sintezdan oldin ortiqcha so'rov ketardi.
  2. GPU `Lock` OSTIDA, KETMA-KET. Bitta uvicorn ishchisi, bitta GPU: so'rovlar
     navbatda kutadi va server 429 QAYTARMAYDI - shunchaki javob kechikadi.
     Ya'ni ortiqcha yukni O'ZIMIZ to'xtatishimiz kerak (semafora), aks holda
     navbat cheksiz o'sadi va hamma timeout'ga uchraydi.
  3. AUDIO OQIM BILAN KELADI. `/tts/stream` matnni tinish belgilari bo'yicha
     bo'laklaydi va HAR BO'LAKNI tayyor bo'lishi bilan yuboradi. 19 s xabar
     uchun birinchi bayt 11.1 s o'rniga 1.1 s da keladi - odam butun sintezni
     kutib o'tirmaydi.

`/tts/generate` ATAYLAB ISHLATILMAYDI. U butun xabar tayyor bo'lgunча jim
turadi, ustiga faylni serverda qoldiradi (`{user_id}__{uuid}.wav`, hech qachon
o'chirilmaydi) va uni ikkinchi so'rov bilan olib kelish kerak. `/stream` da
fayl umuman yaratilmaydi va `user_id` ham so'ralmaydi - ya'ni bizning
foydalanuvchimiz haqida u yerda hech narsa qolmaydi.

`urllib` STT klientidagi kabi - ishlab chiqarish uchun yangi paket qo'shilmaydi.
Modul BLOKLAYDI; endpoint ataylab oddiy `def` bo'lib, FastAPI uni threadpool'da
ishlatadi.
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import wave
import weakref

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from socket import timeout as socket_timeout
from typing import Any

from .analytics.meter import begin, metered
from .speech_text import for_speech

log = logging.getLogger(__name__)

#: Server bilgan ovozlar (`/health` -> `voice_profiles`).
VOICES = ("uz_female_calm", "uz_male_news")

#: Frontend tillari -> TTS. HOZIRCHA FAQAT O'ZBEK LOTIN. Model o'zbek uchun
#: o'rgatilgan; `uz-Cyrl` bu yerda ATAYLAB yo'q - kirill matn lotin o'quvchiga
#: berilsa harf-baharf noto'g'ri o'qiladi, translit esa alohida ish va u hali
#: qilinmagan. `ru`/`en` uchun bu serverda umuman ovoz yo'q.
LOCALE_TO_TTS = {"uz": "uz"}

#: Normalizator YIQILADIGAN naqshlar (jonli tekshirilgan, hujjatdagi jadval).
#: Bunday matnda normalizatsiyani O'ZIMIZ o'chiramiz: xato javobdan ko'ra
#: raqamni model o'zicha o'qigani afzal.
#:
#: 1) 16+ xonali raqam (karta, hisob raqami) -> HTTP 500. Ajratgichlar bilan
#:    yozilgani ham SHU YERGA kiradi: hujjat bo'yicha server bo'sh joy bilan
#:    ajratilgan guruhlarni bitta songa qo'shib yuboradi ("1234 567" ->
#:    1234567), ya'ni "8600 1234 5678 9012" ham o'sha 16 xonaga aylanadi.
_DIGIT_RUN = re.compile(r"\d[\d\s\u00a0.,-]{10,}\d")
#: 2) Nuqta bilan uch va undan ko'p guruh: `1.000.000`, `10.10.50.4`, `v1.2.3`
#:    -> HTTP 422. SANA BUNDAN MUSTASNO: `25.06.2026` hujjatda ISHLAYDIGAN
#:    holat, va uni ham tuzoq deb hisoblasak bitta sana butun gapdagi
#:    raqamlarni (`2450000 som`, `15%`) normalizatsiyasiz qoldirardi.
_DOTTED_GROUPS = re.compile(r"\d+(?:\.\d+){2,}")
_LOOKS_LIKE_DATE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")

#: `dd.mm.yyyy` - `risky_for_normalizer()` sanalarni raqam qatoridan chiqaradi.
#: Sanalarning O'ZI normalizatorga bormaydi: `speech_text.for_speech()` ularni
#: oldinroq so'z bilan yozadi. Bu yerga faqat yaroqsizi (`31.02.2026`) yetadi.
_DMY_ANY = re.compile(r"(?<![\d.])\d{1,2}\.\d{1,2}\.\d{4}(?!\d)")

#: Bo'lakning maqsadli davomiyligi (soniya). Hujjat jonli qo'ng'iroq uchun
#: 1.0-2.0 ni tavsiya qiladi: kattaroq qiymatda birinchi bo'lak uzayadi va
#: TTFB afzalligi yo'qoladi (3.0 da ~5x sekinroq), kichigida esa bo'laklar
#: mayda bo'lib, GPU navbatiga ortiqcha ish tushadi.
DEFAULT_CHUNK_SEC = 1.5

#: `l16` - sarlavhasiz xom PCM, 16-bit little-endian mono.
#:
#: NEGA `wav` EMAS: oqim boshida umumiy uzunlik hali noma'lum, shuning uchun
#: server WAV sarlavhasidagi ikkala hajm maydoniga `0xFFFFFFFF` yozadi.
#: Audio to'g'ri, lekin pleyerlar davomiylikni 74 SOAT deb ko'rsatadi.
#: Brauzer PCM ni `<audio>` bilan ocholmaydi, lekin biz uni baribir
#: Web Audio bilan bo'lak-bo'lak ijro qilamiz - ya'ni sarlavha kerak emas.
STREAM_FORMAT = "l16"

#: Soketdan bir marta o'qiladigan hajm. 3200 bayt = 8 kHz da 200 ms.
#: KICHIK bo'lishi SHART: katta bufer baytlar tayyor bo'lsa ham to'lguncha
#: kutib turadi va butun TTFB afzalligini yeb qo'yadi.
_READ_SIZE = 3200


class TtsError(Exception):
    """`status` - klientga qaytariladigan HTTP kodi."""

    def __init__(self, message: str, *, status: int = 502, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


#: Bitta oqim egallashi mumkin bo'lgan ENG UZUN vaqt (soniya). Shundan
#: keyin joy MAJBURAN qaytariladi.
#:
#: O'lchovga asoslangan: 3000 belgi (`tts_max_chars`) ~198 s ovoz bo'lib,
#: oqim ~41 s davom etadi; 5000 belgi ~71 s. GPU navbatida uch barobar
#: sekinlashsa ham 180 s ichida tugaydi. Ya'ni bu chegara HAQIQIY oqimni
#: kesmaydi - u faqat qotib qolgan joyni qaytaradi.
_SLOT_CEILING = 180.0


class _Slot:
    """Band qilingan bitta joy. Qaytarilishi KAFOLATLANGAN.

    NEGA BU KLASS KERAK. Ilgari joy `pump()` generatorining `finally`
    blokida qaytarilardi, va bu JONLI TIZIMDA OQIB KETDI: generatorning
    `try/finally` si faqat u BIRINCHI MARTA harakatga kelganda qurollanadi.
    Brauzer sarlavhalar kelgandan keyin, lekin javob boshlanishidan oldin
    uzilsa, Starlette tanani hech qachon boshlamaydi - generator boshlanmay
    turib tashlanadi, `finally` ishlamaydi, joy esa MANGU band qoladi.
    Jurnalda o'lchandi: 68 oqim ochilgan, 66 tasi javob bergan, ya'ni ikki
    joy oqib ketgan - va `max_concurrent=2` bo'lgani uchun TTS butunlay
    o'lgan.

    Endi uchta mustaqil to'r bor, har biri boshqasidan qat'i nazar ishlaydi:
      1) `SpeechStream.close()` - oddiy yo'l va oqim o'rtasida uzilish;
      2) `weakref.finalize` - obyekt yig'ilganda (aynan yuqoridagi holat);
      3) soat (`threading.Timer`) - oxirgi chora, WARNING bilan.
    """

    def __init__(self, semaphore: threading.BoundedSemaphore, stream_id: str = "?") -> None:
        self._semaphore = semaphore
        self._lock = threading.Lock()
        self._released = False
        self.stream_id = stream_id
        self._timer = threading.Timer(_SLOT_CEILING, self._expire)
        # `daemon`: bu soat jarayonning o'chishini USHLAB TURMASLIGI kerak.
        self._timer.daemon = True
        self._timer.start()

    def _expire(self) -> None:
        if self.release():
            # Bu NOSOZLIK belgisi, oddiy holat emas: yuqoridagi ikki to'r
            # ishlamagan. Jurnalda ko'rinib turishi shart.
            log.warning(
                "TTS: joy %.0f s dan keyin majburan qaytarildi (oqim %s) - "
                "bu oqish belgisi, yuqoridagi to'rlar ishlamagan",
                _SLOT_CEILING, self.stream_id,
            )

    def release(self) -> bool:
        """Joyni qaytaradi. Takroriy chaqiruv XAVFSIZ (`False` qaytaradi).

        Idempotentlik SHART: uchta to'r ham bir xil joyni qaytarishga
        harakat qiladi, va `BoundedSemaphore` ortiqcha `release()` da
        `ValueError` tashlab, chegarani buzib yuborardi.
        """
        with self._lock:
            if self._released:
                return False
            self._released = True
        self._timer.cancel()
        self._semaphore.release()
        return True


@dataclass
class SpeechStream:
    """Boshlanib bo'lgan oqim.

    Sarlavhalar allaqachon kelgan - server ularni BIRINCHI bo'lak tayyor
    bo'lgach yuboradi, ya'ni bu obyekt qo'lga tekkanda validatsiya xatolari
    (401/403/422/500) allaqachon o'tib bo'lgan. Qolgani faqat baytlar.
    """

    #: Chiqish chastotasi. QATTIQ YOZILMAYDI - server `x-sample-rate` da
    #: aytadi va u deploy'ga qarab o'zgarishi mumkin.
    sample_rate: int
    #: Bo'laklar SONI (bayt hajmi emas).
    chunk_count: int
    #: Server log'i bilan bog'lash uchun (`x-stream-id`).
    stream_id: str
    #: Xom PCM baytlari. Bir marta o'qiladi.
    chunks: Iterator[bytes] = field(repr=False, default_factory=lambda: iter(()))
    #: Matn chegaradan uzun bo'lib qisqartirilgan.
    truncated: bool = False
    #: Egallangan joy. Chaqiruvchi `close()` ni `finally` da ishlatadi.
    slot: _Slot | None = field(repr=False, default=None)

    def close(self) -> None:
        """Oqimni yopadi va JOYNI QAYTARADI. Takroriy chaqiruv xavfsiz.

        Generatorni yopish yetarli EMAS: `close()` boshlanmagan generatorning
        tanasini ishlatmaydi, ya'ni `finally` bloki o'tmaydi. Shu sababli joy
        bu yerda TO'G'RIDAN-TO'G'RI ham qaytariladi.
        """
        with contextlib.suppress(Exception):
            close = getattr(self.chunks, "close", None)
            if close is not None:
                close()
        if self.slot is not None:
            self.slot.release()


@dataclass(frozen=True)
class ClipAudio:
    """To'liq yig'ilgan bitta bo'lak: haqiqiy sarlavhali WAV.

    `/tts/clip` va kutish ovozlari shuni oladi. Oqimdan farqi - hajm va
    davomiylik OLDINDAN ma'lum, ya'ni pleyer faylni diskdan darhol
    o'ynatadi va davomiylikni to'g'ri ko'rsatadi.
    """

    wav: bytes = field(repr=False)
    sample_rate: int
    duration_ms: int
    truncated: bool


def risky_for_normalizer(text: str) -> bool:
    """Normalizator shu matnda yiqiladimi?

    ATAYLAB TOR: har bir noto'g'ri "ha" butun gapdagi raqamlarni
    normalizatsiyasiz qoldiradi, ya'ni ishlaydigan holatlarni ham buzadi.

    Sanalar raqam qatoridan CHIQARILADI: `01.09.2026, 03.09.2026` ikkita
    sana, 16 xonali karta emas. Jonli (2026-09-23): shunday ro'yxat tufayli
    butun javob normalizatsiyasiz ketdi va sanalar "mundoq suzish ikki ming
    yigirma besh" bo'lib eshitildi - holbuki normalizator ularni to'g'ri
    o'qiydi.
    """
    for run in _DIGIT_RUN.finditer(_DMY_ANY.sub(" ", text)):
        if len(re.sub(r"\D", "", run.group())) >= 16:
            return True
    return any(
        not _LOOKS_LIKE_DATE.match(match.group())
        for match in _DOTTED_GROUPS.finditer(text)
    )


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Matnni chegaraga sig'diradi, so'z chegarasida.

    NEGA XATO EMAS: matn foydalanuvchi endigina AYTGAN gapi. "Juda uzun"
    deyish o'rniga boricha o'qib berish tushunarliroq - ayniqsa GPU ketma-ket
    ishlaganda, uzun matn butun navbatni ushlab turadi.
    """
    text = text.strip()
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-"), True


@dataclass(frozen=True)
class SpeechText:
    """TTS serveriga AYNAN ketadigan matn va unga bog'liq qarorlar."""

    text: str
    #: Matn chegaradan uzun edi va kesildi (`clip`).
    truncated: bool
    #: Serverning raqam normalizatori yoqiladimi (`risky_for_normalizer` qarori).
    normalize_numbers: bool


def prepare_speech(text: str, *, max_chars: int, names: Mapping[str, str] | None = None,
                   normalize_numbers: bool = True,
                   trace: list[dict[str, Any]] | None = None) -> SpeechText:
    """Serverdagi BUTUN matn tayyorlash zanjiri - `stream()` (ya'ni `/tts/speak`
    va `/tts/clip`) shu funksiyani chaqiradi.

    NEGA ALOHIDA FUNKSIYA. Admin "Tizim xaritasi" sinovi (`admin_probe.py`) har
    bosqichdan keyingi matnni ko'rsatadi. Sinov bosqichlarni o'zicha qayta
    yozsa, vaqt o'tib haqiqiy yo'ldan ajralib ketardi va noto'g'ri narsani
    "to'g'ri" deb ko'rsatardi. Shuning uchun ikkalasi ham shu bitta funksiyadan
    o'tadi; `trace` berilmasa xulq avvalgidek.

    Tartib (o'zgarmagan): kesish -> bo'sh tekshiruvi -> `for_speech` (lug'at,
    qisqartma, qo'shtirnoq, sana, vaqt) -> normalizator xavfi."""
    clean, truncated = clip(text, max_chars)
    if trace is not None:
        trace.append({"stage": "clip", "text": clean, "limit": max_chars, "truncated": truncated})
    if not clean:
        raise TtsError("matn bo'sh", status=400)
    # Sana, vaqt va "MChJ" - so'z bilan (`speech_text.py`). Qisqartirishdan
    # KEYIN: so'zlar matnni uzaytiradi, va oldin qilinsa, klient allaqachon
    # 3000 belgiga sig'dirgan javobning oxiri shu uzayish hisobiga kesilardi.
    clean = for_speech(clean, names=names, trace=trace)

    # Normalizator ba'zi raqamlarda yiqiladi - bunday matnni OLDINDAN
    # tanib, normalizatsiyasiz yuboramiz. `/stream` da bu 422 beradi
    # (`/generate` da 500 edi), lekin ikkalasi ham foydalanuvchi uchun
    # "ovoz yo'q" degani.
    risky = bool(normalize_numbers) and risky_for_normalizer(clean)
    if risky:
        log.info("TTS: xavfli raqam naqshi - normalize_numbers o'chirildi")
        normalize_numbers = False
    if trace is not None:
        trace.append({"stage": "risky_for_normalizer", "text": clean, "risky": risky,
                      "normalize_numbers": bool(normalize_numbers)})
    return SpeechText(text=clean, truncated=truncated, normalize_numbers=bool(normalize_numbers))


class TtsClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        timeout: float = 60.0,
        max_concurrent: int = 2,
        queue_wait: float = 1.0,
        spoken_names: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        #: Talaffuz lug'ati (`speech_text.SpokenNames`): `DVSIB` -> loyiha nomi.
        self.spoken_names = spoken_names
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.max_concurrent = max(1, max_concurrent)
        self.queue_wait = queue_wait
        self._slots = threading.BoundedSemaphore(self.max_concurrent)
        self._token_lock = threading.Lock()
        self._token: str | None = None
        self._token_expires = 0.0

    # --- token ---------------------------------------------------------

    @property
    def configured(self) -> bool:
        """Sir berilganmi. Berilmagan bo'lsa endpoint 503 qaytaradi - ovoz
        sintezi ixtiyoriy imkoniyat, usiz ham butun ilova ishlaydi."""
        return bool(self.client_id and self.client_secret)

    def _fetch_token(self) -> str:
        body = json.dumps(
            {"client_id": self.client_id, "client_secret": self.client_secret}
        ).encode("utf-8")
        # Hisobda alohida amal: sir noto'g'ri bo'lsa (401) aynan shu qatorda
        # ko'rinadi, ovoz so'rovlarining xatosi ichida yo'qolib ketmaydi.
        with metered("tts", "token"):
            payload = self._json_request("/api/v1/auth/token", body=body, authorized=False)
        token = str(payload.get("access_token") or "")
        if not token:
            raise TtsError("TTS tokeni bo'sh keldi", status=502)
        # 60 s zaxira: uzoq sintez o'rtasida token eskirib qolmasin. Zaxira
        # TTL dan katta bo'lsa kesh muddati NOLGA emas, 30 s ga tushadi -
        # `max(60, ttl) - 60` nol berardi va har so'rov token so'rardi.
        ttl = float(payload.get("expires_in") or 3600)
        self._token = token
        self._token_expires = time.time() + max(30.0, ttl - 60.0)
        log.info("TTS: yangi token olindi (%.0f s)", ttl)
        return token

    def _valid_token(self) -> str:
        # Qulf butun blokni qamraydi: usiz bir vaqtda kelgan ikki so'rov
        # ikkita token so'rardi va ikkinchisi birinchisini almashtirib
        # yuborardi - zararsiz, lekin serverga ortiqcha yuk.
        with self._token_lock:
            if self._token and time.time() < self._token_expires:
                return self._token
            return self._fetch_token()

    def _drop_token(self) -> None:
        with self._token_lock:
            self._token = None
            self._token_expires = 0.0

    # --- sintez ---------------------------------------------------------

    def prepare(self, text: str, *, max_chars: int, normalize_numbers: bool = True,
                trace: list[dict[str, Any]] | None = None) -> SpeechText:
        """Sintezga ketadigan matn - tarmoqsiz, slotsiz (`prepare_speech` + shu
        klientning talaffuz lug'ati). `stream()` ham, admin sinovi ham shuni chaqiradi."""
        names = self.spoken_names() if self.spoken_names else None
        return prepare_speech(text, max_chars=max_chars, names=names,
                              normalize_numbers=normalize_numbers, trace=trace)

    def stream(
        self,
        text: str,
        *,
        voice: str = "uz_female_calm",
        speed: float | None = None,
        normalize_numbers: bool = True,
        chunk_sec: float = DEFAULT_CHUNK_SEC,
        max_chars: int = 600,
        op: str = "speak",
    ) -> SpeechStream:
        """Matn -> boshlanib bo'lgan PCM oqimi.

        Chaqiruvchi `chunks` ni OXIRIGACHA o'qishi yoki `close()` qilishi
        SHART: slot va yuqoridagi ulanish shu generator tugaguncha band
        turadi. FastAPI `StreamingResponse` ikkalasini ham o'zi bajaradi.

        `op` - faqat hisob yorlig'i (`api_calls.op`): admin tahlilida javob
        bo'laklari (`clip`) oqimdan (`speak`) ajralib ko'rinsin. Sintezga
        ta'siri yo'q.
        """
        if not self.configured:
            # 503 EMAS: 503 "band, keyinroq urinib ko'ring" degani va klientni
            # cheksiz qayta urinishga chorlaydi. Sozlanmagan xizmat esa
            # kutish bilan tuzalmaydi - 501 "hali yoqilmagan".
            raise TtsError("TTS sozlanmagan (client_secret yo'q)", status=501)
        if voice not in VOICES:
            raise TtsError(f"noma'lum ovoz: {voice}", status=400)
        # Matn tayyorlash - BITTA funksiyada (`prepare_speech`): admin sinovi ham
        # aynan shu yo'ldan o'tadi.
        prepared = self.prepare(text, max_chars=max_chars, normalize_numbers=normalize_numbers)
        clean, truncated, normalize_numbers = prepared.text, prepared.truncated, prepared.normalize_numbers

        if not self._slots.acquire(timeout=self.queue_wait):
            # Server BITTA GPU'da ketma-ket ishlaydi va 429 QAYTARMAYDI:
            # navbatni o'zimiz cheklamasak, u cheksiz o'sadi. Hujjat: har
            # qo'shimcha parallel so'rov TTFB'ga ~1.1 s qo'shadi.
            raise TtsError(
                f"ilova TTS chegarasida ({self.max_concurrent} parallel)",
                status=503, retryable=True,
            )

        slot = _Slot(self._slots)
        # Hisob: ochilishdan oqim oxirigacha. Birliklar - belgi (so'ralgan
        # matn), bayt va audio soniyasi (oqim tugaganda ma'lum bo'ladi).
        call = begin("tts", op, units={"chars": len(clean)})
        try:
            try:
                response = self._open_stream(clean, voice, speed, normalize_numbers, chunk_sec)
            except TtsError as exc:
                # ZAHIRA - biz hali bilmagan naqsh uchun. Normalizatsiyasiz
                # raqamlar yomon o'qiladi, lekin javob ESHITILADI: 422 esa
                # butun javobni ovozsiz qoldirardi. Faqat 422: 500 - GPU
                # xatosi, qayta urinish uni tuzatmaydi, navbatni esa
                # ikki barobar yuklaydi. WARNING - yangi naqsh
                # `speech_text.for_speech` ga qo'shilishi kerak degan signal.
                if exc.status != 422 or not normalize_numbers:
                    raise
                log.warning("TTS matnni normalizatsiya bilan qabul qilmadi (%s) - "
                            "normalizatsiyasiz qayta yuborildi", exc)
                normalize_numbers = False
                response = self._open_stream(clean, voice, speed, False, chunk_sec)
        except BaseException as exc:
            slot.release()
            call.end("error", http_status=_upstream_status(exc), error=exc)
            raise
        call.http_status = 200

        def headers_of(name: str, default: str = "") -> str:
            # Sim ustida sarlavhalar KICHIK harfda keladi; `http.client`
            # ularni registrsiz qidiradi, lekin default'ni o'zimiz beramiz.
            return response.headers.get(name) or default

        sample_rate = _int_or(headers_of("x-sample-rate"), 8000)
        chunk_count = _int_or(headers_of("x-chunk-count"), 0)
        stream_id = headers_of("x-stream-id", "?")
        log.info("TTS oqim %s: %d bo'lak, %d Hz, ovoz=%s, normalize=%s",
                 stream_id, chunk_count, sample_rate, voice, normalize_numbers)

        slot.stream_id = stream_id

        def pump() -> Iterator[bytes]:
            sent = 0
            failure: BaseException | None = None
            try:
                while True:
                    # Kichik bo'lak: bufer katta bo'lsa TTFB afzalligi
                    # yeyiladi - baytlar tayyor bo'lsa ham kutib turadi.
                    part = response.read(_READ_SIZE)
                    if not part:
                        return
                    sent += len(part)
                    yield part
            except (TimeoutError, socket_timeout) as exc:
                failure = TtsError("TTS oqimi to'xtab qoldi (timeout)", status=504)
                raise failure from exc
            except (http.client.HTTPException, OSError) as exc:
                # Oqim O'RTASIDA nosozlik: server ulanishni ATAYLAB uzadi,
                # chunki 200 yuborilgandan keyin statusni o'zgartirib
                # bo'lmaydi. Sabab server log'ida, `x-stream-id` bo'yicha.
                failure = TtsError(f"TTS oqimi uzildi ({stream_id}): {exc}", status=502)
                raise failure from exc
            except BaseException as exc:
                failure = exc
                raise
            finally:
                with contextlib.suppress(Exception):
                    response.close()
                slot.release()
                # L16 mono: 2 bayt = 1 namuna. Klient uzilsa (`GeneratorExit`)
                # bu xato emas - xizmat o'z ishini qilgan.
                units = {"bytes": sent, "audioSec": round(sent / (2.0 * max(1, sample_rate)), 2)}
                if failure is None or isinstance(failure, GeneratorExit):
                    call.end("ok", units=units, error=failure)
                else:
                    call.end("error", units=units, error=failure)

        speech = SpeechStream(
            sample_rate=sample_rate,
            chunk_count=chunk_count,
            stream_id=stream_id,
            chunks=pump(),
            truncated=truncated,
            slot=slot,
        )
        # IKKINCHI TO'R. Obyekt yig'ilganda joy qaytadi - aynan o'sha
        # holat uchun: javob boshlanmay so'rov tashlab ketilgan, ya'ni
        # `close()` ni chaqiradigan hech kim yo'q. `slot.release` obyektga
        # havola SAQLAMAYDI, shuning uchun bu yig'ilishga to'sqinlik qilmaydi.
        weakref.finalize(speech, slot.release)
        # Xuddi shu sabab bilan hisob ham: boshlanmagan oqimning `finally` si
        # ishlamaydi, chaqiruv esa hisobdan tushib qolmasin.
        weakref.finalize(speech, call.end)
        return speech

    def busy(self) -> int:
        """Ayni vaqtda band joylar soni - `/api/health` uchun.

        `_value` xususiy, lekin muqobili yo'q: `BoundedSemaphore` sanoqni
        ochiq bermaydi. Xatoga uchrasa `-1` qaytadi, chunki sog'lik
        tekshiruvi buning ustida yiqilmasligi kerak.
        """
        try:
            return self.max_concurrent - self._slots._value  # type: ignore[attr-defined]
        except Exception:
            return -1

    def synthesize_clip(
        self,
        text: str,
        *,
        voice: str = "uz_female_calm",
        speed: float | None = None,
        normalize_numbers: bool = True,
        chunk_sec: float = DEFAULT_CHUNK_SEC,
        max_chars: int = 600,
        op: str = "clip",
    ) -> ClipAudio:
        """Oqimni to'liq yig'ib, HAQIQIY sarlavhali WAV qaytaradi.

        `stream()` ning ustida turadi, ya'ni token keshi, normalizator
        to'rlari, `for_speech`, semafora sloti va slot qaytarish to'rlari -
        hammasi AYNAN o'sha kod. Alohida yo'l yozilsa ular vaqt o'tib
        ajralib ketardi.

        HAMMASI YOKI HECH NARSA: oqim o'rtasida uzilsa `TtsError` ko'tariladi
        va yarim audio HECH QACHON qaytmaydi - klient gapning yarmini
        o'ynatib qo'ymasin.
        """
        speech = self.stream(
            text, voice=voice, speed=speed, normalize_numbers=normalize_numbers,
            chunk_sec=chunk_sec, max_chars=max_chars, op=op,
        )
        try:
            pcm = b"".join(speech.chunks)
        finally:
            # Generator to'liq o'qilsa joy o'zi qaytadi, lekin o'rtada xato
            # bo'lsa ham qaytishi SHART.
            speech.close()
        if speech.sample_rate <= 0:
            # `wave` 0 chastotada `wave.Error` tashlardi (500); sarlavha
            # yaroqsiz - bu yuqoridagi xizmat xatosi.
            raise TtsError(f"TTS chastotasi yaroqsiz: {speech.sample_rate}", status=502)
        # 16-bit: toq bayt - yarim namuna. U eshitilmaydi, lekin `data`
        # bo'lagini toq qilib RIFF ni buzadi (toq bo'lak to'ldirilishi kerak).
        pcm = pcm[: len(pcm) - len(pcm) % 2]
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(speech.sample_rate)
            out.writeframes(pcm)
        frames = len(pcm) // 2
        return ClipAudio(
            wav=buffer.getvalue(),
            sample_rate=speech.sample_rate,
            duration_ms=round(frames * 1000 / speech.sample_rate),
            truncated=speech.truncated,
        )

    def synthesize_wav(self, text: str, **kwargs) -> bytes:
        """Faqat WAV baytlari (`synthesize_clip(...).wav`).

        Oflayn ishlar uchun (kutish ovozlarini tayyorlash): bu yerda kutish
        muhim emas, to'g'ri uzunlikli sarlavha esa muhim. Serverning
        `format=wav` i buni BERMAYDI - u oqim boshida uzunlikni bilmagani
        uchun `0xFFFFFFFF` yozadi.

        Hisob yorlig'i ATAYLAB `speak` qoladi (o'zgarishsiz): ishga tushishdagi
        qizdirish admin tahlilida avvalgidek ko'rinsin.
        """
        kwargs.setdefault("op", "speak")
        return self.synthesize_clip(text, **kwargs).wav

    # --- transport ------------------------------------------------------

    def _json_request(self, path: str, *, body: bytes | None = None, authorized: bool = True) -> dict:
        raw = self._send(path, body=body, authorized=authorized, accept="application/json")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TtsError(f"TTS javobi o'qilmadi: {exc}", status=502) from exc
        # Tur tekshiruvi MAJBURIY: 200 bilan `null`, `[]` yoki satr kelsa
        # keyingi `.get()` AttributeError berardi, u esa TtsError EMAS va
        # butun so'rovni 500 ga aylantirardi.
        if not isinstance(payload, dict):
            raise TtsError(f"TTS javobi kutilmagan turda: {type(payload).__name__}", status=502)
        return payload

    def _send(self, path: str, *, body: bytes | None, authorized: bool, accept: str,
              timeout: float | None = None) -> bytes:
        """Bitta so'rov. 401 da token bir marta yangilanib qayta yuboriladi.

        NEGA QAYTA URINISH SHU YERDA: token 24 soat yashaydi, ya'ni u
        odatda so'rovlar ORASIDA eskiradi. Server qayta ishga tushsa ham
        (imzo kaliti yangilansa) eski token yaroqsiz bo'ladi. Ikkala holatda
        ham foydalanuvchi buni ko'rmasligi kerak.
        """
        for attempt in (0, 1):
            headers = {"Accept": accept}
            if body is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(body))
            if authorized:
                headers["Authorization"] = f"Bearer {self._valid_token()}"
            try:
                return self._open(path, body, headers, timeout or self.timeout)
            except TtsError as exc:
                if exc.status == 401 and authorized and attempt == 0:
                    log.info("TTS: token rad etildi, yangilanmoqda")
                    self._drop_token()
                    continue
                raise
        raise TtsError("TTS javob bermadi", status=502)

    def _open(self, path: str, body: bytes | None, headers: dict[str, str],
              timeout: float | None = None) -> bytes:
        with _mapped_errors(self.client_secret):
            with self._opener().open(
                self._request(path, body, headers), timeout=timeout or self.timeout
            ) as response:
                return response.read()

    def _open_stream(self, text: str, voice: str, speed: float | None,
                     normalize_numbers: bool, chunk_sec: float):
        """`/tts/stream` ni ochadi va javob obyektini QAYTARADI - o'qilmagan.

        Sarlavhalar birinchi bo'lak tayyor bo'lgach keladi (~1.1 s), ya'ni
        shu yerga qaytgan bo'lsak validatsiya allaqachon o'tgan: 401, 403,
        422 va birinchi bo'lakdagi 500 shu chaqiruvda `HTTPError` bo'lib
        ko'tariladi. Undan keyingi nosozlik esa endi HTTP xatosi emas -
        ulanish uziladi, va uni `pump()` tutadi.
        """
        body = json.dumps({
            "text": text,
            "voice_profile": voice,
            "speed": speed,
            "normalize_numbers": normalize_numbers,
            "format": STREAM_FORMAT,
            "chunk_sec": chunk_sec,
        }).encode("utf-8")

        # 401 da token bir marta yangilanadi - `_send` dagi kabi, lekin bu
        # yerda javob O'QILMAYDI, shuning uchun alohida sikl.
        for attempt in (0, 1):
            headers = {
                "Accept": "*/*",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Authorization": f"Bearer {self._valid_token()}",
            }
            try:
                with _mapped_errors(self.client_secret):
                    return self._opener().open(
                        self._request("/api/v1/tts/stream", body, headers),
                        timeout=self.timeout,
                    )
            except TtsError as exc:
                if exc.status == 401 and attempt == 0:
                    log.info("TTS: token rad etildi, yangilanmoqda")
                    self._drop_token()
                    continue
                raise
        raise TtsError("TTS javob bermadi", status=502)

    def _request(self, path: str, body: bytes | None, headers: dict[str, str]):
        return urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method="POST" if body is not None else "GET",
            headers=headers,
        )

    @staticmethod
    def _opener():
        # Ichki manzil korporativ proksi orqali KETMASLIGI kerak.
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))


@contextlib.contextmanager
def _mapped_errors(secret: str):
    """`urllib` xatolarini `TtsError` ga o'giradi.

    Alohida funksiya, chunki oddiy so'rov ham, oqim ochilishi ham AYNAN bir
    xil xaritaga muhtoj - ikki nusxada saqlash esa ularni vaqt o'tib
    ajralib ketishiga olib borardi.
    """
    try:
        yield
    except urllib.error.HTTPError as exc:
        status = exc.code
        # Sir REDAKSIYA qilinadi: server 422 da so'rov tanasini o'zicha
        # qaytarishi mumkin (FastAPI validatsiya xatosi `input` ni aynan
        # ko'chiradi), va u token so'rovi tanasi - ya'ni `client_secret`.
        detail = _redact(_detail(exc), secret)
        # 401 chaqiruvchida tutiladi (token yangilash). 422 - matn
        # normalizatordan o'tmadi, 500 - GPU/model xatosi: ikkalasi ham
        # qayta urinishdan tuzalmaydi.
        mapped = status if status in (400, 401, 403, 422, 503) else 502
        raise TtsError(f"TTS {status}: {detail}", status=mapped) from exc
    except urllib.error.URLError as exc:
        raise TtsError(f"TTS serveriga ulanib bo'lmadi: {exc.reason}",
                       status=503, retryable=True) from exc
    except (TimeoutError, socket_timeout) as exc:
        raise TtsError("TTS javob bermadi (timeout)", status=504) from exc
    except (http.client.HTTPException, OSError) as exc:
        raise TtsError(f"TTS ulanishi uzildi: {exc}", status=503, retryable=True) from exc


def _upstream_status(exc: BaseException) -> int | None:
    """Xizmatning HAQIQIY HTTP statusi (`HTTPError.code`). `TtsError.status`
    esa foydalanuvchiga ko'rsatiladigani - 500 u yerda 502. HTTP javobi
    bo'lmagan bo'lsa (`None`) hisob `TtsError.status` ni oladi."""
    cause = exc.__cause__
    return cause.code if isinstance(cause, urllib.error.HTTPError) else None


def _int_or(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _redact(text: str, secret: str) -> str:
    """Sirni xato matnidan olib tashlaydi. Ikki belgidan uzun sir uchun -
    qisqa qiymat tasodifiy mos kelib, matnni buzib yuborishi mumkin."""
    return text.replace(secret, "***") if secret and len(secret) > 2 else text


def _detail(exc: urllib.error.HTTPError) -> str:
    """`{"detail": "..."}` dan matn. Sir HECH QACHON bu yerga tushmaydi -
    faqat server javobi o'qiladi."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return str(exc.reason or "")
    try:
        text = str(json.loads(raw).get("detail") or raw)
    except Exception:  # noqa: BLE001
        text = raw
    return text[:300]

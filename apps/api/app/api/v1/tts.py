"""Matnni ovozga o'girish - OQIM bilan.

Brauzer matnni shu yerga yuboradi, biz TTS serverining `/tts/stream` iga
borib, kelgan baytlarni o'sha zahoti brauzerga uzatamiz.

NEGA OQIM. To'liq sintez 19 s xabar uchun 11 s oladi; oqimda birinchi bayt
~1.1 s da keladi. Odam savolini berib bo'lgach 11 soniya jim ekranga qarab
o'tirmasligi kerak.

NEGA TO'G'RIDAN-TO'G'RI EMAS - STT bilan bir xil sabab (`v1/stt.py`), ustiga
yana bittasi: TTS serverining `client_secret` i BRAUZERGA HECH QACHON
berilmasligi kerak. Agar frontend o'zi token olsa, sir JS bundle'ida yoki
tarmoq panelida ochiq turardi.

Javob - `audio/L16` xom PCM (sarlavhasiz, 16-bit little-endian mono).
Brauzer buni `<audio>` bilan ocholmaydi va ATAYLAB shunday: `format=wav` da
server oqim boshida umumiy uzunlikni bilmagani uchun sarlavhaga `0xFFFFFFFF`
yozadi va pleyerlar davomiylikni 74 soat deb ko'rsatadi. Frontend PCM ni
Web Audio bilan bo'lak-bo'lak ijro qiladi (`api/tts.api.ts`).

MOBIL ILOVA uchun alohida yo'l bor - `/tts/clip`: bitta qisqa bo'lak, to'liq
WAV (sababi o'sha funksiya izohida).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path as FsPath
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response, StreamingResponse

from ...core.config import settings
from ...core.errors import bad_request, error_status
from ...schemas.auth import AuthUser
from ...schemas.tts import CLIP_MAX_CHARS, ClipRequest, SpeakRequest
from ...services.analytics import bind, valid_turn_id
from ...services.hold import HoldVoices, all_clips
from ...services.speech_text import SpokenNames
from ...services.tts import LOCALE_TO_TTS, TtsClient, TtsError
from ..deps import current_user

#: `chat.TURN_HEADER` bilan bir xil. Import emas: `chat` ni modul boshida
#: import qilish aylanma bog'liqlik yasaydi (`_hold_voices` izohi).
_TURN_HEADER = "X-Venera-Turn"

log = logging.getLogger(__name__)
router = APIRouter(prefix="/tts", tags=["tts"])

_client = TtsClient(
    settings.tts_base_url,
    settings.tts_client_id,
    settings.tts_client_secret,
    timeout=settings.tts_timeout,
    max_concurrent=settings.tts_max_concurrent,
    spoken_names=SpokenNames(settings.tts_spoken_names_path),
)

#: Foydalanuvchiga ko'rinadigan xabarlar - status bo'yicha, ichki matnsiz.
#: Ichki host va sir xabarga HECH QACHON tushmaydi.
#:
#: Yuqoridagi 401/403 bu yerda ATAYLAB yo'q. Ular "bizning `client_secret`
#: noto'g'ri yoki scope yetmaydi" degani - ya'ni SOZLAMA xatosi. Brauzerga
#: 401 qaytarish "sessiyangiz tugadi" degan ma'no berardi, holbuki
#: foydalanuvchi token'i mutlaqo joyida. Ular 502 ga tushadi.
_MESSAGES = {
    501: "Ovoz javobi hali yoqilmagan",
    503: "Ovoz xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Ovoz tayyorlash juda uzoq cho'zildi",
    400: "Matn ovozga o'girilmadi",
    422: "Bu matnni ovozga o'girib bo'lmadi",
    502: "Ovoz xizmati javob bermadi",
}


@router.post(
    "/speak",
    response_class=StreamingResponse,
    responses={200: {"content": {"audio/L16": {}},
                     "description": "Xom PCM oqimi, 16-bit LE mono"}},
)
def speak(body: SpeakRequest, request: Request,
          user: AuthUser = Depends(current_user)) -> StreamingResponse:
    """Matn -> PCM oqimi.

    `async def` EMAS, ataylab: klient bloklaydigan `urllib` ishlatadi. Oddiy
    `def` bilan FastAPI uni threadpool'da ishlatadi va event loop bo'sh
    qoladi - aks holda bitta uzun oqim butun serverni to'xtatib qo'yardi.

    `X-Venera-Turn` (ixtiyoriy) - klient o'qib berayotgan javobning savol
    kaliti: hisobda ovoz o'sha savolga bog'lanadi. Faqat yaroqli kalit
    (32 hex) olinadi, boshqasi e'tiborsiz - bu faqat statistika.
    """
    if LOCALE_TO_TTS.get(body.language) is None:
        # Birinchi bosqich ataylab faqat o'zbek (lotin): model shu til uchun,
        # `uz-Cyrl` uchun translit hali yo'q, `ru`/`en` uchun ovoz umuman yo'q.
        raise bad_request(f"ovoz bu tilda hali yo'q: {body.language}")

    text = body.text.strip()
    if not text:
        raise bad_request("matn bo'sh")

    turn = valid_turn_id(request.headers.get(_TURN_HEADER))
    binding = bind(turn_id=turn) if turn else None
    try:
        # Oqim SHU YERDA ochiladi, generator ichida emas: validatsiya
        # xatolari (422, 500, 503) shunda oddiy HTTP javobi bo'lib chiqadi.
        # Generator ichida ochilsa, biz allaqachon 200 yuborib bo'lgan
        # bo'lardik va xato faqat uzilgan ulanish bo'lib ko'rinardi.
        speech = _client.stream(
            text,
            voice=body.voice or settings.tts_voice,
            speed=settings.tts_speed,
            chunk_sec=settings.tts_chunk_sec,
            max_chars=settings.tts_max_chars,
        )
    except TtsError as exc:
        log.warning("TTS (%s): %s", user.email, exc)
        status = exc.status if exc.status in _MESSAGES else 502
        raise error_status(status, _MESSAGES[status]) from exc
    finally:
        # Hisob chaqiruvi kalitni OCHILISHDA oldi (`begin`) - endi kerak emas.
        if binding is not None:
            binding.reset()

    def body_iter():
        try:
            yield from speech.chunks
        except TtsError as exc:
            # Oqim o'rtasida uzildi. Statusni endi o'zgartirib bo'lmaydi
            # (200 ketib bo'lgan), shuning uchun biz ham ulanishni tugatamiz
            # - brauzer buni tugallanmagan oqim deb ko'radi, xuddi
            # yuqoridagi server bizga ko'rsatgani kabi. Sabab log'da.
            log.warning("TTS oqimi (%s): %s", user.email, exc)
        finally:
            # MAJBURIY: brauzer ijro o'rtasida uzilsa (odam sferani bosdi,
            # panelni yopdi) Starlette generatorni tashlab ketadi. Bu
            # `finally` TTS navbatidagi joyni darhol qaytaradi - aks holda
            # u faqat soat bo'yicha, 180 s dan keyin qaytardi.
            speech.close()

    return StreamingResponse(
        body_iter(),
        media_type=f"audio/L16; rate={speech.sample_rate}; channels=1",
        headers={
            # Audio foydalanuvchiga xos - proksi yoki brauzer keshiga tushmasin.
            "Cache-Control": "no-store",
            "X-Venera-Sample-Rate": str(speech.sample_rate),
            "X-Venera-Chunks": str(speech.chunk_count),
            "X-Venera-Truncated": "1" if speech.truncated else "0",
            # nginx uchun: bu yo'lda buferlash O'CHIQ bo'lishi kerak, aks
            # holda u butun oqimni yig'ib, keyin bir yo'la beradi va TTFB
            # afzalligi yo'qoladi. Sarlavha konfiguratsiyaga qo'shimcha
            # himoya - `location` sozlamasi asosiy.
            "X-Accel-Buffering": "no",
        },
    )


#: Bitta foydalanuvchining bir vaqtdagi `/clip` sintezlari. NEGA CHEKLOV: route oddiy
#: `def` (threadpool) - klient so'rovni uzsa (bo'lib gapirish, suhbatni yopish) server buni
#: sezmaydi va bo'lakni oxirigacha sintez qiladi. TTS ning 2 sloti HAMMAGA umumiy: bitta
#: odam (ikki qurilma yoki ketma-ket bo'lib gapirish) ikkalasini egallab, boshqalarni 503 ga
#: tushirmasin. Klient bitta so'rov yuboradi; 2 - uzilgan so'rov tugaguncha yangisiga joy.
_CLIP_PER_USER = 2
_clip_inflight: dict[tuple[str, int], int] = {}
_clip_guard = threading.Lock()


@contextmanager
def _clip_slot(user: AuthUser) -> Iterator[None]:
    key = (user.actorType, user.actorId)
    with _clip_guard:
        busy = _clip_inflight.get(key, 0)
        if busy >= _CLIP_PER_USER:
            error = error_status(503, _MESSAGES[503])
            error.headers = {"Retry-After": "1"}
            raise error
        _clip_inflight[key] = busy + 1
    try:
        yield
    finally:
        with _clip_guard:
            left = _clip_inflight.get(key, 1) - 1
            if left > 0:
                _clip_inflight[key] = left
            else:
                _clip_inflight.pop(key, None)


@router.post(
    "/clip",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}},
                     "description": "To'liq WAV (PCM 16-bit LE mono), haqiqiy sarlavha bilan"},
               501: {"description": "Ovoz sintezi sozlanmagan"},
               503: {"description": "TTS band (`Retry-After`)"}},
)
def clip_wav(body: ClipRequest, request: Request,
             user: AuthUser = Depends(current_user)) -> Response:
    """Bitta bo'lak matn -> TO'LIQ WAV (mobil ilova).

    NEGA OQIM EMAS. Mobil pleyer (expo-audio) faqat TAYYOR faylni o'ynata
    oladi - xom PCM oqimini ocholmaydi. Qisqa to'liq fayl esa diskdan darhol
    o'ynaydi. Oqimning TTFB afzalligini klient boshqa yo'l bilan qaytaradi:
    javobni GAP chegarasida bo'laklaydi (birinchisi <=60 belgi, ~1.2-2.2 s
    sintez), keyingi bo'lak oldingisi o'ynayotganda tayyorlanadi. Klient
    keyingi bo'lakni shu javobning SARLAVHASI kelishi bilan so'raydi: sarlavha
    sintez tugab, TTS o'rni va `_clip_slot` bo'shagandan keyin ketadi - ya'ni
    bu bir foydalanuvchida bir vaqtda ikkita sintez qilmaydi. SHU SABABLI
    `/clip` HECH QACHON `StreamingResponse` ga o'tkazilmasin: sarlavha sintezdan
    OLDIN ketsa har foydalanuvchi ikkala umumiy TTS o'rnini egallab, boshqalarni
    503 ga tushiradi (`test_clip_slotlar_javob_sarlavhasidan_oldin_qaytadi`).

    NEGA <=600 BELGI. Bu BITTA bo'lak (klient <=350 yuboradi). TTS ning ikki
    sloti BARCHA foydalanuvchilarga umumiy: qisqa so'rov slotni ~2 s ushlaydi,
    3000 belgilik oqim esa ~40 s - ya'ni uzun so'rov boshqalarni 503 ga
    tushirardi.

    HAMMASI YOKI HECH NARSA: oqim o'rtasida uzilsa yarim WAV emas, JSON xato
    qaytadi (statusi bilan) - klient gapning yarmini o'ynatib qo'ymasin.

    Matn log'ga HECH QACHON yozilmaydi: u foydalanuvchining HRM javobi.

    `async def` EMAS - `/speak` dagi sabab: bloklaydigan `urllib`, threadpool.
    """
    if LOCALE_TO_TTS.get(body.language) is None:
        # `/speak` dagi kabi: hozircha faqat o'zbek lotin.
        raise bad_request(f"ovoz bu tilda hali yo'q: {body.language}")

    text = body.text.strip()
    if not text:
        raise bad_request("matn bo'sh")

    turn = valid_turn_id(request.headers.get(_TURN_HEADER))
    binding = bind(turn_id=turn) if turn else None
    try:
        with _clip_slot(user):
            audio = _client.synthesize_clip(
                text,
                voice=body.voice or settings.tts_voice,
                speed=body.speed if body.speed is not None else settings.tts_speed,
                chunk_sec=settings.tts_chunk_sec,
                max_chars=CLIP_MAX_CHARS,
            )
    except TtsError as exc:
        # Faqat status: `str(exc)` ichida yuqoridagi serverning `detail` i
        # bo'lishi mumkin, u esa (422 da) matn bo'lagini aynan ko'chiradi.
        log.warning("TTS bo'lak (%s): status=%s", user.email, exc.status)
        raise _tts_http_error(exc) from exc
    finally:
        if binding is not None:
            binding.reset()

    if audio.duration_ms <= 0:
        # Server 200 bilan BO'SH audio berdi. Uzunligi nol fayl ba'zi
        # pleyerlarda "tugadi" hodisasini bermaydi va klient navbati qotadi -
        # yaxshisi aniq xato.
        log.warning("TTS bo'lak (%s): bo'sh audio keldi", user.email)
        raise error_status(502, _MESSAGES[502])

    return Response(
        content=audio.wav,
        media_type="audio/wav",
        headers={
            # Audio foydalanuvchiga xos (HRM javobi) - keshga tushmasin.
            "Cache-Control": "no-store",
            "X-Venera-Sample-Rate": str(audio.sample_rate),
            "X-Venera-Duration-Ms": str(audio.duration_ms),
            "X-Venera-Truncated": "1" if audio.truncated else "0",
        },
    )


def _tts_http_error(exc: TtsError):
    """`TtsError` -> foydalanuvchiga ko'rinadigan HTTP xatosi (ichki matnsiz).

    503 ga `Retry-After` qo'shiladi (`chat.py` dagi kabi): klient 503 da
    qisqa pauza bilan qayta urinadi, sarlavha esa buni mashina o'qiydigan
    qilib aytadi.
    """
    status = exc.status if exc.status in _MESSAGES else 502
    error = error_status(status, _MESSAGES[status])
    if status == 503:
        error.headers = {"Retry-After": "1"}
    return error


@router.get(
    "/hold/{clip}.wav",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}},
               404: {"description": "Bu ovoz hali sintez qilinmagan"}},
)
def hold_clip(clip: str = Path(pattern=r"^[a-z0-9-]{1,80}$"),
              voice: Literal["uz_female_calm", "uz_male_news"] | None = Query(
                  default=None,
                  description="Bo'sh yoki `TTS_VOICE` - tayyor kesh; boshqasi birinchi "
                              "so'rovda sintez qilinib keshlanadi"),
              user: AuthUser = Depends(current_user)) -> Response:
    """Tayyor kutish gapining ovozi.

    NEGA ALOHIDA YO'L, kadr ichida emas. Kutish gapining butun ma'nosi
    KECHIKISHNING NOLLIGIDA: agar klient matnni olib, uni TTS ga yuborsa,
    o'lchangan 1.1 sekund yana qo'shilardi - ya'ni "tayyor ovoz" ning
    afzalligi yo'qolardi. Ovozni kadr ichida base64 bilan yuborish esa
    oqimni bloklaydi (~34 KB) va javob kadrlarini kechiktiradi.

    Shu yo'l esa keshlanadi: brauzer ovozni bir marta oladi va keyingi
    barcha kutishlarda uni DISKDAN o'ynatadi - ya'ni tarmoq ham
    ishlatilmaydi. `immutable` xavfsiz, chunki kalit oxirida gap MATNINING
    xeshi bor (`services/hold.py: clip_key`): matn o'zgarsa kalit ham
    o'zgaradi va brauzer eski ovozni o'ynatib qolmaydi.

    Kalit naqshi faqat kichik harf, raqam va chiziqcha: nuqta ham, `/` ham
    yo'q - ya'ni kalit orqali fayl tizimida boshqa joyga chiqib bo'lmaydi.

    `?voice=` - mobil ilovada odam tanlagan ovoz. Asosiy ovoz (yoki bo'sh)
    AYNAN avvalgi yo'l. Boshqa ovoz ishga tushishda QIZDIRILMAYDI, birinchi
    so'rovda yasaladi (`_hold_in_voice`). URL da `?voice` bor, ya'ni
    `immutable` kesh ovozlarni aralashtirmaydi.
    """
    if voice is None or voice == settings.tts_voice:
        data = _hold_voices().get(clip)
    else:
        data = _hold_in_voice(clip, voice)
    if not data:
        # Sintez hali tugamagan (xizmat yangi ishga tushgan) yoki TTS
        # o'chiq. Bu XATO EMAS: klient matnni o'zi ovozga aylantiradi.
        raise error_status(404, "Bu ovoz hali tayyor emas")
    return Response(
        content=data,
        media_type="audio/wav",
        headers={
            # Matn kodda yozilgan va o'zgarmaydi, ya'ni ovoz ham o'zgarmaydi.
            # Uzoq kesh - bu yo'l kutishning eng tez qismi bo'lishi kerak.
            "Cache-Control": "private, max-age=86400, immutable",
        },
    )


def _hold_voices():
    """Kutish ovozlari keshi.

    Import FUNKSIYA ICHIDA: `api/v1/chat.py` ni modul boshida import
    qilish aylanma bog'liqlik yasaydi. Kesh obyekti CHAT modulida turadi,
    chunki uni to'ldiradigan reja ham o'sha yerda.
    """
    from .chat import _hold_voices as voices

    return voices


#: Asosiy ovozdan boshqa ovozlarning kutish keshi: papka -> kesh. Kalit
#: PAPKA (ovoz nomi emas): `settings.hold_voice_dir` testda almashtirilsa,
#: eski papkadagi kesh yangisiga aralashib ketmaydi.
_voice_caches: dict[FsPath, HoldVoices] = {}
#: Bitta (papka, kalit) uchun bitta sintez. Bir vaqtda kelgan ikki so'rov
#: ikkita bir xil sintez qilib, umumiy ikki TTS slotini bekor band qilardi.
_synth_locks: dict[tuple[FsPath, str], threading.Lock] = {}
_registry_lock = threading.Lock()
#: Sintez qulfini shuncha kutamiz, keyin 404. Klient kutish ovozini ~4 s
#: kutadi; undan uzoq ushlab turilgan ip faqat threadpool'ni band qiladi.
_HOLD_SYNTH_WAIT = 5.0


def _voice_cache(voice: str) -> HoldVoices:
    directory = settings.hold_voice_dir / voice
    with _registry_lock:
        cache = _voice_caches.get(directory)
        if cache is None:
            cache = _voice_caches[directory] = HoldVoices(directory)
        return cache


def _synth_lock(directory: FsPath, clip: str) -> threading.Lock:
    with _registry_lock:
        return _synth_locks.setdefault((directory, clip), threading.Lock())


def _hold_in_voice(clip: str, voice: str) -> bytes | None:
    """Kutish ovozi TANLANGAN ovozda: keshdan yoki birinchi so'rovda sintez.

    NEGA QIZDIRISH EMAS. Ikkinchi ovozni ishga tushishda yasash har qayta
    ishga tushishdan keyin ~50 s davomida ikki umumiy TTS slotidan birini
    egallardi - hamma foydalanuvchining javob ovozi sekinlashardi. Talab
    bo'yicha esa faqat har gapning BIRINCHI so'rovi ~1.5 s kutadi; klient
    ovozni faqat savol hali "o'ylanayotgan" bo'lsa o'ynatadi.

    `None` -> 404: noma'lum kalit, TTS sozlanmagan, band yoki yiqildi.
    Kutish ovozi - xushmuomalalik, klient uni jimgina o'tkazib yuboradi.
    """
    text = dict(all_clips()).get(clip)
    if text is None:
        # Noma'lum kalit hech qachon sintezga bormaydi (aks holda URL orqali
        # ixtiyoriy matnni TTS ga yuborib bo'lardi) va diskdagi ESKI fayl
        # ham berilmaydi - u eskirgan gapning ovozi.
        return None
    cache = _voice_cache(voice)
    data = cache.get(clip)
    if data:
        return data
    if not _client.configured:
        return None
    lock = _synth_lock(cache.cache_dir, clip)
    if not lock.acquire(timeout=_HOLD_SYNTH_WAIT):
        return None
    try:
        # Qulfni kutayotganda boshqa so'rov yasab qo'ygan bo'lishi mumkin.
        data = cache.get(clip)
        if data:
            return data
        try:
            wav = _client.synthesize_wav(text, voice=voice, op="hold")
        except TtsError as exc:
            log.info("Kutish ovozi %s ovozida yasalmadi (%s): status=%s",
                     voice, clip, exc.status)
            return None
        # Birinchi yozuvdan oldin ESKI gaplarning ovozi tozalanadi (`warm`
        # dagi kabi; har nusxada bir marta).
        cache.prune({key for key, _ in all_clips()})
        # Diskka yozilmasa ham shu so'rovga beramiz - ovoz tayyor.
        cache.put(clip, wav)
        return wav
    finally:
        lock.release()

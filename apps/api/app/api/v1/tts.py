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
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response, StreamingResponse

from ...core.config import settings
from ...core.errors import bad_request, error_status
from ...schemas.auth import AuthUser
from ...schemas.tts import SpeakRequest
from ...services.analytics import bind, valid_turn_id
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


@router.get(
    "/hold/{clip}.wav",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}},
               404: {"description": "Bu ovoz hali sintez qilinmagan"}},
)
def hold_clip(clip: str = Path(pattern=r"^[a-z0-9-]{1,80}$"),
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
    """
    data = _hold_voices().get(clip)
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

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

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...core.config import settings
from ...core.errors import bad_request, error_status
from ...schemas.auth import AuthUser
from ...schemas.tts import SpeakRequest
from ...services.tts import LOCALE_TO_TTS, TtsClient, TtsError
from ..deps import current_user

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
def speak(body: SpeakRequest, user: AuthUser = Depends(current_user)) -> StreamingResponse:
    """Matn -> PCM oqimi.

    `async def` EMAS, ataylab: klient bloklaydigan `urllib` ishlatadi. Oddiy
    `def` bilan FastAPI uni threadpool'da ishlatadi va event loop bo'sh
    qoladi - aks holda bitta uzun oqim butun serverni to'xtatib qo'yardi.
    """
    if LOCALE_TO_TTS.get(body.language) is None:
        # Birinchi bosqich ataylab faqat o'zbek (lotin): model shu til uchun,
        # `uz-Cyrl` uchun translit hali yo'q, `ru`/`en` uchun ovoz umuman yo'q.
        raise bad_request(f"ovoz bu tilda hali yo'q: {body.language}")

    text = body.text.strip()
    if not text:
        raise bad_request("matn bo'sh")

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

    def body_iter():
        try:
            yield from speech.chunks
        except TtsError as exc:
            # Oqim o'rtasida uzildi. Statusni endi o'zgartirib bo'lmaydi
            # (200 ketib bo'lgan), shuning uchun biz ham ulanishni tugatamiz
            # - brauzer buni tugallanmagan oqim deb ko'radi, xuddi
            # yuqoridagi server bizga ko'rsatgani kabi. Sabab log'da.
            log.warning("TTS oqimi (%s): %s", user.email, exc)

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

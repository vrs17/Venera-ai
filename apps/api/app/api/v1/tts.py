"""Matnni ovozga o'girish.

Brauzer matnni shu yerga yuboradi, biz TTS serveriga borib WAV olib qaytaramiz.

NEGA TO'G'RIDAN-TO'G'RI EMAS - STT bilan bir xil sabab (`v1/stt.py`), ustiga
yana bittasi: TTS serverining `client_secret` i BRAUZERGA HECH QACHON
berilmasligi kerak. Agar frontend o'zi token olsa, sir JS bundle'ida yoki
tarmoq panelida ochiq turardi va uni ko'rgan har kim butun TTS parkidan
foydalana olardi.

Javob - `audio/wav` baytlari (8000 Hz, mono). JSON emas.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response

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
    deadline=settings.tts_deadline,
)

#: Foydalanuvchiga ko'rinadigan xabarlar - status bo'yicha, ichki matnsiz.
#: Ichki host va sir xabarga HECH QACHON tushmaydi.
#: Yuqoridagi 401/403 bu yerda ATAYLAB yo'q. Ular "bizning `client_secret`
#: noto'g'ri yoki scope yetmaydi" degani - ya'ni SOZLAMA xatosi. Brauzerga
#: 401 qaytarish "sessiyangiz tugadi" degan ma'no berardi, holbuki
#: foydalanuvchi token'i mutlaqo joyida. Ular 502 ga tushadi va sabab
#: faqat log'da qoladi (operator uchun).
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
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}, "description": "WAV, 8000 Hz, mono"}},
)
def speak(body: SpeakRequest, user: AuthUser = Depends(current_user)) -> Response:
    """Matn -> WAV.

    `async def` EMAS, ataylab: klient bloklaydigan `urllib` ishlatadi va
    sintez soniyalab davom etadi. Oddiy `def` bilan FastAPI uni threadpool'da
    ishlatadi, event loop esa bo'sh qoladi.
    """
    if LOCALE_TO_TTS.get(body.language) is None:
        # Birinchi bosqich ataylab faqat o'zbek (lotin): model shu til uchun,
        # `uz-Cyrl` uchun translit hali yo'q, `ru`/`en` uchun ovoz umuman yo'q.
        raise bad_request(f"ovoz bu tilda hali yo'q: {body.language}")

    text = body.text.strip()
    if not text:
        raise bad_request("matn bo'sh")

    try:
        speech = _client.synthesize(
            text,
            # Fayl nomiga tushadi va server fayllarni o'chirmaydi - shuning
            # uchun email emas, ichki raqamli id.
            user_id=str(user.actorId),
            voice=body.voice or settings.tts_voice,
            speed=settings.tts_speed,
            max_chars=settings.tts_max_chars,
        )
    except TtsError as exc:
        log.warning("TTS (%s): %s", user.email, exc)
        status = exc.status if exc.status in _MESSAGES else 502
        raise error_status(status, _MESSAGES[status]) from exc

    return Response(
        content=speech.audio,
        media_type=speech.content_type,
        headers={
            # Audio foydalanuvchiga xos - proksi yoki brauzer keshiga tushmasin.
            "Cache-Control": "no-store",
            "X-Venera-Duration": f"{speech.duration_sec:.2f}",
            "X-Venera-Truncated": "1" if speech.truncated else "0",
        },
    )

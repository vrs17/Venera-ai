"""Ovozni matnga o'girish.

Brauzer mikrofondan yozib, shu yerga yuboradi; biz STT Router'ga uzatamiz.

NEGA TO'G'RIDAN-TO'G'RI EMAS: brauzer `10.10.50.4:8006` ga o'zi bora olmaydi.
Sayt HTTPS'da bo'lsa aralash-kontent bloklanadi, HTTP'da bo'lsa CORS to'sadi,
va ikkala holatda ham ichki manzil brauzerga ochilgan bo'lardi. Proksi bilan
STT serveri tashqariga umuman ko'rinmaydi va so'rov autentifikatsiyadan
o'tadi.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ...core.config import settings
from ...core.errors import bad_request, error_status
from ...schemas.auth import AuthUser
from ...schemas.stt import TranscriptResponse
from ...services.stt import LOCALE_TO_STT, SttClient, SttError
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/stt", tags=["stt"])

_client = SttClient(
    settings.stt_base_url,
    timeout=settings.stt_timeout,
    attempts=settings.stt_attempts,
    max_concurrent=settings.stt_max_concurrent,
    deadline=settings.stt_deadline,
)

#: Foydalanuvchiga ko'rinadigan xabarlar - status bo'yicha, ichki matnsiz.
#: 503 = band (qayta urinsa bo'ladi), 504 = juda uzoq, 413 = katta,
#: 415 = format, 400/422 = audio qabul qilinmadi, 502 = xizmat javob bermadi.
_MESSAGES = {
    503: "Ovoz xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Ovozni qayta ishlash juda uzoq cho'zildi - qisqaroq gapirib ko'ring",
    413: "Audio juda katta",
    415: "Bu audio formati qabul qilinmaydi",
    400: "Audio qabul qilinmadi",
    422: "Audio qabul qilinmadi",
    502: "Ovoz xizmati javob bermadi",
}


@router.post("/transcribe", response_model=TranscriptResponse)
def transcribe(
    file: UploadFile = File(description="Audio (webm/ogg/wav)"),
    language: str = Form(description="uz | uz-Cyrl | ru | en - UI tili"),
    user: AuthUser = Depends(current_user),
) -> TranscriptResponse:
    """Audio -> matn.

    `async def` EMAS, ataylab: STT klienti bloklaydigan `urllib` ishlatadi.
    Oddiy `def` bilan FastAPI uni threadpool'da ishlatadi va event loop
    to'silmaydi - aks holda bitta uzun transkripsiya butun serverni
    to'xtatib qo'yardi.
    """
    stt_language = LOCALE_TO_STT.get(language)
    if stt_language is None:
        raise bad_request(f"til qo'llab-quvvatlanmaydi: {language}")

    audio = file.file.read()
    limit = int(settings.stt_max_upload_mb * 1024 * 1024)
    if len(audio) > limit:
        raise bad_request(f"audio juda katta ({len(audio) // 1024} KB, chegara {settings.stt_max_upload_mb} MB)")
    if not audio:
        raise bad_request("audio bo'sh")

    try:
        result = _client.transcribe(
            audio,
            language=stt_language,
            content_type=file.content_type or "application/octet-stream",
        )
    except SttError as exc:
        log.warning("STT (%s, %s): %s", user.email, stt_language, exc)
        status = exc.status if exc.status in _MESSAGES else 502
        raise error_status(status, _MESSAGES[status]) from exc

    return TranscriptResponse(
        text=result.text,
        language=result.language or stt_language,
        durationSec=result.duration_sec,
        lowConfidence=result.low_confidence,
        truncated=result.truncated,
        backend=result.backend,
    )

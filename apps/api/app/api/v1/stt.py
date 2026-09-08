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
)


@router.post("/transcribe", response_model=TranscriptResponse)
def transcribe(
    file: UploadFile = File(description="Audio (webm/ogg/wav)"),
    language: str = Form(description="uz | uz-Cyrl | ru | en | zh"),
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
            filename=file.filename or "audio.webm",
            content_type=file.content_type or "application/octet-stream",
        )
    except SttError as exc:
        log.warning("STT (%s, %s): %s", user.email, stt_language, exc)
        # Xato matni FOYDALANUVCHIGA ko'rinadi, shuning uchun ichki manzil
        # yoki stek uzatilmaydi - faqat nima bo'lgani.
        message = (
            "Ovoz xizmati band, biroz kutib qayta urinib ko'ring"
            if exc.retryable or exc.status == 503
            else "Ovozni matnga o'girib bo'lmadi"
        )
        raise error_status(exc.status if exc.status in (400, 413) else 503, message) from exc

    return TranscriptResponse(
        text=result.text,
        language=result.language or stt_language,
        durationSec=result.duration_sec,
        lowConfidence=result.low_confidence,
    )

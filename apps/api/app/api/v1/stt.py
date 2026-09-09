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
from ...schemas.stt import TranscriptResponse, WakeResponse
from ...services.stt import LOCALE_TO_STT, SttClient, SttError
from ...services.wake import FLAT_LIMIT, WakeLog, is_wake_phrase, measure
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
_wake_log = WakeLog(settings.wake_log_dir, max_files=settings.wake_log_max_files)

#: Uyg'otish parchasi qisqa (0.35-2.6 s). Undan kattasi tinglagichdan
#: kelmaydi, ya'ni bu chegara xato yoki suiiste'mol belgisi.
_WAKE_MAX_BYTES = 1024 * 1024

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


@router.post("/wake", response_model=WakeResponse)
def wake(
    file: UploadFile = File(description="Qisqa audio parcha (WAV 16 kHz mono)"),
    language: str = Form(description="uz | uz-Cyrl - UI tili"),
    user: AuthUser = Depends(current_user),
) -> WakeResponse:
    """Uyg'otish so'zi tekshiruvi.

    `/transcribe` DAN ALOHIDA, garchi ikkalasi ham STT ga borsa ham:

      * QAROR shu yerda qabul qilinadi. Brauzerda qolsa, server nima uchun
        uyg'onmaganini bilmasdi va moslashtirgichni sozlash uchun frontend
        obrazini har safar qayta yig'ish kerak bo'lardi.
      * Urinish YOZIB BORILADI - audio, transkript va sabab bir joyda.
        Aynan shu ma'lumot "juda aniq aytmasa uyg'onmaydi" degan muammoni
        taxmin bilan emas, dalil bilan tuzatish imkonini beradi.
      * Xato JIM. Hech kim hech narsa so'ramagan: navbat to'la bo'lsa yoki
        audio yaroqsiz bo'lsa, javob shunchaki "uyg'onmadi" bo'ladi. Har
        necha soniyada ekranda xato chiqishi sukunatdan yomonroq.
    """
    stt_language = LOCALE_TO_STT.get(language)
    if stt_language is None:
        raise bad_request(f"til qo'llab-quvvatlanmaydi: {language}")

    audio = file.file.read()
    if not audio or len(audio) > _WAKE_MAX_BYTES:
        raise bad_request("audio yaroqsiz")

    try:
        result = _client.transcribe(
            audio,
            language=stt_language,
            content_type=file.content_type or "audio/wav",
        )
    except SttError as exc:
        # Uyg'otish tekshiruvi FON ishi: 503 (navbat to'la) bu yerda odatiy
        # hol va uni xato sifatida ko'rsatish noto'g'ri bo'lardi.
        log.info("Uyg'otish tekshiruvi o'tmadi (%s): %s", user.email, exc)
        # `checked=False`: bu "uyg'otish so'zi emas" degani EMAS, "tekshirib
        # bo'lmadi" degani. Klient buni ko'rib urinishlar oralig'ini
        # uzaytiradi - o'chgan backend'ni har ikki soniyada urib turishning
        # ma'nosi yo'q.
        return WakeResponse(text="", matched=False, reason="stt xatosi", checked=False)

    matched, reason = is_wake_phrase(result.text)
    if settings.wake_log_enabled:
        entry = _wake_log.record(
            audio,
            actor_id=user.actorId,
            language=stt_language,
            text=result.text,
            matched=matched,
            reason=reason,
            duration_sec=result.duration_sec,
            backend=result.backend,
        )
        flat = entry.flat
    else:
        flat = measure(audio)[3]
    # Buzilgan yozuvda "uyg'onmadi" ning aybi so'zda emas. Brauzer buni
    # foydalanuvchiga aytadi - darvozani (OS/drayver) faqat u o'chira oladi,
    # bizning hech qanday sozlamamiz unga yetmaydi.
    distorted = flat > FLAT_LIMIT
    log.info("Uyg'otish: %r -> %s (%s)%s", result.text, "HA" if matched else "yo'q", reason,
             f" BUZILGAN tekis={flat:.0%}" if distorted else "")
    return WakeResponse(text=result.text, matched=matched, reason=reason, distorted=distorted)

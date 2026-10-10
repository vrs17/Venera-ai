"""Yig'ilish xatolari: mashina o'qiydigan kod + o'zbekcha xabar.

NEGA KOD. Mobil ilova xatoni MATNDAN emas, koddan taniydi: `offset_mismatch`
da yuklashni `receivedBytes` dan davom ettiradi, `sha_mismatch` da noldan
boshlaydi, `quota_user` da "ertaga" deydi. Matn odam uchun, kod - dastur
uchun; matnni tahrirlash ilovani buzmasligi kerak.

NEGA `HTTPException` DAN. Xizmat qatlami (`service.py`) endpoint qaytaradigan
holatni o'zi biladi (409 + `receivedBytes`, 413 + `code`). Har endpointda
`try/except` bilan o'girish 30 ta joyda bir xil kod bo'lardi; bu sinf esa
`core/errors.py` dagi umumiy handler orqali o'zi to'g'ri shaklga tushadi
(`extra` maydonlari konvertga qo'shiladi).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

#: Kod -> odamga ko'rinadigan xabar (o'zbekcha). `MeetingError.message`.
MESSAGES: dict[str, str] = {
    "upload_incomplete": "Yozuv to'liq yuklanmagan - ilova qolgan qismini yuboradi.",
    "sha_mismatch": "Yuklangan fayl buzilgan - ilova uni qaytadan yuboradi.",
    "unsupported_format": "Bu audio formati qo'llab-quvvatlanmaydi.",
    "too_long": "Yozuv juda uzun - yangi yozuv boshlang.",
    "too_large": "Fayl juda katta.",
    "audio_unreadable": "Audioni o'qib bo'lmadi.",
    "stt_rejected": "Matnga o'girish xizmati yozuvni qabul qilmadi.",
    "stt_not_configured": "Matnga o'girish xizmati sozlanmagan.",
    "stt_auth": "Matnga o'girish xizmatiga ulanishda xato - administratorga xabar bering.",
    "stt_job_lost": "Matnga o'girish vazifasi yo'qoldi - qayta urinib ko'ring.",
    "stt_timeout": "Matnga o'girish juda uzoq cho'zildi - qayta urinib ko'ring.",
    "router_too_long": "Bu tilda 10 daqiqadan uzun m4a yozuvni o'girib bo'lmaydi.",
    "quota_user": "Bugungi limitingiz tugadi - yozuv navbatda, ertaga o'giriladi.",
    "quota_service": "Xizmat limiti tugadi - yozuv navbatda, keyinroq o'giriladi.",
    "llm_not_configured": "Xulosa yozuvchi model sozlanmagan.",
    "llm_failed": "Xulosani yozib bo'lmadi - qayta urinib ko'ring.",
    "too_short": "Yozuv juda qisqa - xulosa yozilmadi.",
    "internal": "Ichki xato - qayta urinib ko'ring.",
}

#: Foydalanuvchi `POST /retry` bilan qayta urina oladigan kodlar.
RETRYABLE = frozenset({"stt_timeout", "stt_job_lost", "quota_user", "quota_service",
                       "llm_failed", "internal"})


def message_for(code: str | None) -> str:
    return MESSAGES.get(code or "", MESSAGES["internal"])


class MeetingProblem(HTTPException):
    """Endpoint javobiga aylanadigan xato: HTTP kodi, `code` va qo'shimcha maydonlar."""

    def __init__(self, status: int, code: str, message: str | None = None, *,
                 headers: dict[str, str] | None = None, **extra: Any) -> None:
        super().__init__(status_code=status, detail=message or message_for(code), headers=headers)
        self.code = code
        self.extra = {"code": code, **extra}


def not_found() -> MeetingProblem:
    """Begona yig'ilish ham, yo'q yig'ilish ham - BIR XIL 404: boshqa odamning
    yig'ilishi borligini ham bilib bo'lmasin."""
    return MeetingProblem(404, "not_found", "Yig'ilish topilmadi")

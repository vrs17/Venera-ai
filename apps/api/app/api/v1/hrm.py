"""HRM integratsiyasi - servis kaliti bilan (odam tokeni emas).

`POST /hrm/late-decision`: xodimning kechikish sababiga avtomatik qaror. HRM fon ishi xodim javob
yozgan yangi kechikishlarni yuboradi; APPROVE / REJECT ni HRM o'zi qo'llaydi, MANUAL - HR manager'ga
qoladi (`services/hrm_late.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core.config import settings
from ...core.errors import error_status
from ...schemas.hrm import LateDecisionRequest, LateDecisionResponse
from ...services import hrm_late
from .service_auth import PerMinuteRate, parse_service_keys, service_caller_for

router = APIRouter(prefix="/hrm", tags=["hrm"])


def _keys() -> list[tuple[str, str]]:
    """`HRM_LATE_SERVICE_KEYS`; bo'sh bo'lsa `STT_SERVICE_KEYS` (HRM ning bitta kaliti ikkala endpoint uchun)."""
    return parse_service_keys(settings.hrm_late_service_keys or settings.stt_service_keys)


hrm_caller = service_caller_for(_keys)
_rate = PerMinuteRate(lambda: settings.hrm_late_per_min)


@router.post("/late-decision", response_model=LateDecisionResponse)
def late_decision(body: LateDecisionRequest, caller: str = Depends(hrm_caller)) -> LateDecisionResponse:
    """Kechikish sababi -> APPROVE / REJECT / MANUAL. Xodim ismi yuborilmaydi va Barno'da hech narsa
    saqlanmaydi. 429 - daqiqalik chegara; 503 - model hozir javob bermadi (HRM keyinroq qayta so'raydi)."""
    if not _rate.allow(caller):
        raise error_status(429, "So'rovlar juda ko'p - birozdan keyin qayta urinib ko'ring")
    try:
        return hrm_late.decide(body)
    except hrm_late.LateDecisionUnavailable:
        raise error_status(503, "AI xizmati hozir javob bermadi - keyinroq qayta urinib ko'ring") from None

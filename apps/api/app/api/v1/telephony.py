"""Telefoniya - Barno chiquvchi qo'ng'iroqlari FreePBX orqali (`services/telephony/`).

`POST /telephony/call-result`  FreePBX qo'ng'iroq natijasini yuboradi (`X-Service-Key`). Kalit to'g'ri bo'lsa
                               doim 2xx (takroriy natija - 409): FreePBX boshqa 4xx da 24 soat qayta yuboradi.
`POST /telephony/calls`        ADMIN: mijozga (hozircha sinov) qo'ng'iroq boshlash.
`GET  /telephony/status`       ADMIN: qo'ng'iroq boshlash mumkinmi (yoqilgan, sozlangan, kunlik chegara).
`GET  /telephony/calls`        ADMIN: oxirgi qo'ng'iroqlar.
`GET  /telephony/calls/{id}`   ADMIN: bitta qo'ng'iroq - FreePBX natijasi, kelgan so'rovlar, bridge/Speko qaydi.

XATOLAR (qo'ng'iroq boshlashda): 422 - raqam noto'g'ri; 429 - kunlik yoki daqiqalik chegara; 503 - telefoniya
o'chiq yoki sozlanmagan. FreePBX qabul qilmasa - 200, lekin holat `rejected` va sababi `detail` da.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ...core.config import settings
from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.telephony import CallView, PlaceCallRequest, TelephonyStatus
from ...services.telephony import service
from ..deps import require_roles
from .service_auth import PerMinuteRate, parse_service_keys, service_caller_for

router = APIRouter(prefix="/telephony", tags=["telephony"])

admin_only = require_roles("ADMIN")
result_caller = service_caller_for(lambda: parse_service_keys(settings.telephony_result_service_keys))
_per_admin = PerMinuteRate(lambda: max(1, int(settings.telephony_calls_per_min)))
MAX_RESULT_BYTES = 16 * 1024


@router.post("/call-result")
async def call_result(request: Request, caller: str = Depends(result_caller)) -> JSONResponse:
    raw_bytes = (await request.body())[:MAX_RESULT_BYTES]
    raw = raw_bytes.decode("utf-8", "replace")
    try:
        payload = json.loads(raw) if raw.strip() else None
    except ValueError:
        payload = None
    code, body = await run_in_threadpool(service.record_result, payload, caller=caller, raw=raw)
    return JSONResponse(body, status_code=code)


@router.post("/calls", response_model=CallView)
def place_call(body: PlaceCallRequest, user: AuthUser = Depends(admin_only)) -> CallView:
    if not _per_admin.allow(str(user.actorId)):
        raise error_status(429, "Juda tez - birozdan keyin qayta urinib ko'ring")
    try:
        call = service.place_call(body.phone, actor_id=user.actorId, note=body.note)
    except service.InvalidPhone as exc:
        raise error_status(422, str(exc)) from None
    except service.TelephonyLimit as exc:
        raise error_status(429, str(exc)) from None
    except service.TelephonyUnavailable as exc:
        raise error_status(503, str(exc)) from None
    return CallView.of(call)


@router.get("/status", response_model=TelephonyStatus, dependencies=[Depends(admin_only)])
def telephony_status() -> TelephonyStatus:
    return TelephonyStatus(**service.status())


@router.get("/calls", response_model=list[CallView], dependencies=[Depends(admin_only)])
def list_calls(limit: int = 50) -> list[CallView]:
    return [CallView.of(call) for call in service.list_calls(limit)]


@router.get("/calls/{call_id}", response_model=CallView, dependencies=[Depends(admin_only)])
def get_call(call_id: str) -> CallView:
    call = service.get_call(call_id)
    if call is None:
        raise error_status(404, "Qo'ng'iroq topilmadi")
    return CallView.of(call)

"""Telefoniya - Barno chiquvchi qo'ng'iroqlari FreePBX orqali (`services/telephony/`).

`POST /telephony/call-result`  FreePBX qo'ng'iroq natijasini yuboradi (`X-Service-Key`). Kalit to'g'ri bo'lsa
                               doim 2xx (takroriy natija - 409): FreePBX boshqa 4xx da 24 soat qayta yuboradi.
`GET  /telephony/status`       kirgan har kim: panel shu odamga ochiqmi (`allowed`), yoqilgan/sozlanganmi, chegara.
`POST /telephony/calls`        RUXSATLI: mijozga (hozircha sinov) qo'ng'iroq boshlash.
`GET  /telephony/calls`        RUXSATLI: oxirgi qo'ng'iroqlar.
`GET  /telephony/calls/{id}`   RUXSATLI: bitta qo'ng'iroq - FreePBX natijasi, kelgan so'rovlar, bridge/Speko qaydi.

RUXSATLI = ADMIN roli yoki `TELEPHONY_LOGINS` dagi login (ADMIN huquqi bermaydi - faqat telefon qo'ng'iroqlari).

XATOLAR (qo'ng'iroq boshlashda): 422 - raqam noto'g'ri; 429 - kunlik yoki daqiqalik chegara; 503 - telefoniya
o'chiq yoki sozlanmagan. FreePBX qabul qilmasa - 200, lekin holat `rejected` va sababi `detail` da.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ...core.config import settings
from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.telephony import CallView, PlaceCallRequest, TelephonyStatus
from ...services.telephony import service
from ...services import admin_users
from ...services.identities import IdentityStore
from ..deps import current_user, get_identity_store
from .service_auth import PerMinuteRate, parse_service_keys, service_caller_for

router = APIRouter(prefix="/telephony", tags=["telephony"])


def _logins() -> frozenset[str]:
    raw = str(settings.telephony_logins or "")
    return frozenset(part.strip().lower() for part in re.split(r"[,\s;]+", raw) if part.strip())


def allowed(user: AuthUser, identities: IdentityStore) -> bool:
    """ADMIN roli yoki `TELEPHONY_LOGINS`. SSO hisobi - logini bilan, `users.yaml` hisobi - emaili bilan."""
    if admin_users.ADMIN in user.roles:
        return True
    identity = identities.by_actor_id(user.actorId)
    value = getattr(identity, "username", None) or user.email
    return bool(value) and str(value).strip().lower() in _logins()


def phone_user(user: AuthUser = Depends(current_user),
               identities: IdentityStore = Depends(get_identity_store)) -> AuthUser:
    if not allowed(user, identities):
        raise error_status(403, "Bu bo'lim uchun ruxsat yo'q")
    return user

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
def place_call(body: PlaceCallRequest, user: AuthUser = Depends(phone_user)) -> CallView:
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


@router.get("/status", response_model=TelephonyStatus)
def telephony_status(user: AuthUser = Depends(current_user),
                     identities: IdentityStore = Depends(get_identity_store)) -> TelephonyStatus:
    """Kirgan har kimga: ruxsati yo'q odamga faqat `allowed=false` (boshqa ma'lumot berilmaydi)."""
    if not allowed(user, identities):
        return TelephonyStatus(allowed=False, enabled=False, configured=False, dailyCap=0, used24h=0)
    return TelephonyStatus(allowed=True, **service.status())


@router.get("/calls", response_model=list[CallView], dependencies=[Depends(phone_user)])
def list_calls(limit: int = 50) -> list[CallView]:
    return [CallView.of(call) for call in service.list_calls(limit)]


@router.get("/calls/{call_id}", response_model=CallView, dependencies=[Depends(phone_user)])
def get_call(call_id: str) -> CallView:
    call = service.get_call(call_id)
    if call is None:
        raise error_status(404, "Qo'ng'iroq topilmadi")
    return CallView.of(call)

"""Qurilma sessiyalari - mobil ilova "bir marta kiring, keyin o'zi" (spetsifikatsiya 3.2, 29-31).

    POST /auth/devices          sessiya bilan: shu qurilmani ro'yxatga olish -> qurilma tokeni
    POST /auth/devices/session  qurilma tokeni -> yangi Venera JWT (`/auth/login` javobi bilan bir xil)
    POST /auth/devices/revoke   tokenni bekor qilish (chiqishda)

DIZAYN `/telegram/session` NUSXASI. Token faqat parol bilan kirgan sessiyadan
olinadi; almashtirishda admin qarorlari QAYTA tekshiriladi: blok - 403,
"hamma joydan chiqarish" (sessiya versiyasi oshgan) - 401 va token o'ladi.
Zahira hisoblarda (`users.yaml`) `/auth/login` ning ikki qoidasi ham
(`local_login_enabled`, `password_change_required`) - aks holda qurilma tokeni
ularni aylanib o'tish yo'li bo'lardi.

Ro'yxatga olish sinov davrida bo'lim eshigi (`meetings_access`) ortida:
bayroq o'chiq bo'lsa yangi token chiqmaydi. ALMASHTIRISH ham: qurilma tokeni
TO'LIQ Venera JWT beradi, shuning uchun bayroq o'chirilsa yoki odam
`MEETINGS_LOGINS` dan chiqarilsa telefon sessiyani yangilay olmaydi (401;
ro'yxatdan chiqarilganning tokeni bekor qilinadi).
"""

from __future__ import annotations

import logging

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core import config as _config
from ...core.channels import CLIENT_CHANNELS, channel_of
from ...core.config import settings
from ...core.errors import unauthorized
from ...core.security import create_token
from ...schemas.auth import AuthUser, LoginResponse
from ...schemas.devices import DeviceRegistered, DeviceRegisterRequest, DeviceRevoked, DeviceTokenRequest
from ...services import admin_users
from ...services.analytics import record_auth_event
from ...services.devices import token_hash
from ...services.identities import Directory, Identity, IdentityStore
from ...services.meetings import runtime
from ...services.meetings.errors import MeetingProblem
from ...services.reports import RateLimiter
from ...services.users import UserStore
from ..deps import get_identity_store, get_user_store
from .auth import _admit
from .meetings import meetings_access, meetings_allowed

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/devices", tags=["auth"])

#: Bitta token xeshidan daqiqasiga 6 urinish (Telegram sessiyasi bilan bir xil).
_token_limiter = RateLimiter(limit=6, window=60)
#: Bitta IP dan daqiqasiga - token tanlab ko'rishni sekinlatadi.
_ip_limiter = RateLimiter(limit=30, window=60)

#: Tashqariga BITTA xabar: noma'lum, eskirgan, bekor qilingan - farqi faqat jurnalda.
_MSG = "Qurilma sessiyasi yaroqsiz - login va parol bilan kiring"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat().replace("+00:00", "Z")


def _devices():
    return runtime().devices


def _channel(request: Request) -> str:
    declared = channel_of(request)
    return declared if declared in CLIENT_CHANNELS else "mobile"


@router.post("", response_model=DeviceRegistered, status_code=status.HTTP_201_CREATED)
def register(body: DeviceRegisterRequest, user: AuthUser = Depends(meetings_access)) -> DeviceRegistered:
    """Shu sessiya egasi uchun qurilma tokeni. Omborga FAQAT xesh yoziladi."""
    verdict = admin_users.access(user)
    device_id, token, expires = _devices().register(
        user.actorId, verdict.token_version, name=body.deviceName.strip(), platform=body.platform,
        app_version=body.appVersion.strip())
    log.info("Qurilma ro'yxatga olindi: actor %s (%s)", user.actorId, body.platform)
    return DeviceRegistered(deviceId=device_id, deviceToken=token, expiresAt=_iso(expires))


def _refuse(reason: str, channel: str, *, actor_id: int | None = None, login: str | None = None) -> HTTPException:
    record_auth_event(login, False, method="device", channel=channel, reason=reason, actor_id=actor_id)
    log.info("Qurilma sessiyasi rad etildi (%s): %s", actor_id or "-", reason)
    error = unauthorized(_MSG)
    # Mashina o'qiydigan kod (konvertga `core/errors.py` qo'shadi): ilova shu kod bilan
    # login ekraniga o'tadi, yozuvlar navbati esa saqlanadi.
    error.extra = {"code": "invalid_device_token"}
    return error


def _limited(limiter: RateLimiter, key: object) -> None:
    wait = limiter.take(key)
    if wait is not None:
        raise MeetingProblem(429, "rate_limited", "Juda ko'p urinish - birozdan keyin qayta urinib ko'ring",
                             headers={"Retry-After": str(wait)})


@router.post("/session", response_model=LoginResponse)
def session(body: DeviceTokenRequest, request: Request,
            store: UserStore = Depends(get_user_store),
            identities: IdentityStore = Depends(get_identity_store)) -> LoginResponse:
    """Qurilma tokeni -> yangi JWT. Kirish qoidalari `/auth/login` niki."""
    channel = _channel(request)
    _limited(_ip_limiter, request.client.host if request.client else "?")
    _limited(_token_limiter, token_hash(body.deviceToken))
    if not _config.meetings_enabled_now():
        # Sinov bo'limi o'chiq - qurilma tokenlari ham ishlamaydi (token o'lmaydi:
        # bo'lim qayta yoqilsa ilova yana kira oladi).
        raise _refuse("meetings_disabled", channel)
    devices = _devices()
    row, state = devices.lookup(body.deviceToken)
    if row is None:
        raise _refuse(f"device_{state}", channel)
    actor_id = int(row["actor_id"])
    stored = Directory(identities, store).by_actor_id(actor_id)
    if stored is None:
        raise _refuse("device_unknown_actor", channel, actor_id=actor_id)
    if isinstance(stored, Identity):
        login, sso_login, subject = stored.username, stored.username, stored.subject
    else:
        login, sso_login, subject = stored.email, None, stored.email
        if not settings.local_login_enabled:
            raise _refuse("local_login_disabled", channel, actor_id=actor_id, login=login)
        if stored.password_change_required:
            raise _refuse("password_change_required", channel, actor_id=actor_id, login=login)
    verdict = _admit(stored.to_public(), sso_login, attempt=login, method="device", channel=channel)
    if verdict.loaded and int(row["token_version"]) != int(verdict.token_version):
        # "Hamma joydan chiqarish" - qurilma tokeni ham o'ladi.
        devices.revoke(body.deviceToken)
        raise _refuse("device_signed_out", channel, actor_id=actor_id, login=login)
    if not meetings_allowed(verdict.user, login):
        # Sinov guruhidan chiqarilgan - token o'ladi.
        devices.revoke(body.deviceToken)
        raise _refuse("meetings_not_allowed", channel, actor_id=actor_id, login=login)
    devices.touch(row["id"])
    token, expires = create_token(subject, version=verdict.token_version)
    record_auth_event(login, True, method="device", channel=channel, actor_id=actor_id)
    log.info("Kirish (qurilma): actor_id %s", actor_id)
    return LoginResponse(token=token, tokenType="Bearer", expiresAt=expires.isoformat(),
                         passwordChangeRequired=False, user=verdict.user)


@router.post("/revoke", response_model=DeviceRevoked)
def revoke(body: DeviceTokenRequest, request: Request) -> DeviceRevoked:
    """Idempotent: noma'lum yoki allaqachon bekor qilingan token ham 200."""
    _limited(_ip_limiter, request.client.host if request.client else "?")
    if _devices().revoke(body.deviceToken):
        log.info("Qurilma tokeni bekor qilindi")
    return DeviceRevoked()

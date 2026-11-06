"""Autentifikatsiya endpointlari.

KIRISH IKKI YO'L BILAN:

  1. SSO - Keycloak, BRAUZER orqali (`services/oidc.py`):
       GET  /auth/sso/config    - frontend: SSO yoqilganmi, parol shakli bormi
       GET  /auth/sso/start     - odamni Keycloak kirish sahifasiga yuboradi
       GET  /auth/sso/callback  - Keycloak'dan qaytish: tokenlar tekshiriladi,
                                  shaxs `identities.json` ga yoziladi (`actor_id`
                                  BIR MARTA tanlanadi, `services/identities.py`),
                                  Barno sessiyasi (JWT) yasaladi va frontend'ga
                                  BIR MARTALIK kod bilan qaytariladi
       POST /auth/sso/exchange  - o'sha kod -> `LoginResponse` (token)
     Parol Barno'ga HECH QACHON kelmaydi. Rollar - Keycloak'dagi bizning
     client'ning rollari (`admin` -> ADMIN).

  2. Zahira - `config/users.yaml` (`POST /auth/login`, `local_login_enabled`):
     administrator Keycloak'siz ham kira olsin (Keycloak yiqilganda,
     birinchi sozlashda). Prod'da o'chirish mumkin - shunda bu endpoint 403
     va kirish sahifasida faqat SSO tugmasi qoladi.

OLDINGI YO'L - login+parolni Keycloak'ga ilovaning o'zi yuborishi (parol
granti) va o'sha parol bilan HRM ga kirish - OLIB TASHLANDI (2026-11): SSO
ning ma'nosi ilova parolni ko'rmasligi. HRM/CRM ulanishlari endi kirishda
o'zi ochilmaydi - "+" menyusida (`api/v1/connectors.py`); HRM Keycloak
tokenini qabul qilgan kuni u ham SSO sessiyasidan ochiladi.

Frontend (`apps/web/src/api/auth.api.ts`). `signup` va `change-password`
ATAYLAB 501: hisob va parol Keycloak'da.
"""

from __future__ import annotations

import logging
import secrets
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from ...core.channels import channel_of
from ...core.config import settings
from ...core.errors import error_status, unauthorized
from ...core.security import create_token
from ...schemas.auth import (
    AuthUser,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SsoConfig,
    SsoExchangeRequest,
)
from ...services import admin_users
from ...services.analytics import record_auth_event
from ...services.identities import IdentityStore
from ...services.oidc import HANDOFF, ID_TOKENS, KeycloakOidc, OidcError
from ...services.users import UserStore
from . import connectors as _connectors
from ..deps import current_user, get_identity_store, get_user_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

#: Xabar ATAYLAB UMUMIY: qaysi biri xato ekanini aytsak, qaysi loginlar
#: borligini aniqlash mumkin bo'lardi.
_MSG_BAD_LOGIN = "Login yoki parol noto'g'ri"
#: Admin panelda bloklangan hisob (`services/admin_users.py`). Parol to'g'ri
#: bo'lgandagina aytiladi.
_MSG_BLOCKED = "Hisob bloklangan. Administratorga murojaat qiling."
_MSG_LOCAL_OFF = "Parol bilan kirish o'chirilgan - SSO orqali kiring"
_MSG_HANDOFF = "Kirish kodi eskirgan yoki ishlatilgan - qaytadan kiring"

START_PATH = "/api/v1/auth/sso/start"
CALLBACK_PATH = "/api/v1/auth/sso/callback"
_CHANNELS = frozenset({"web", "miniapp", "desktop", "mobile"})
#: Frontend ko'rsatadigan sabab kodlari (`shell.auth.sso.*`); qolgani `failed`.
_PUBLIC_REASONS = frozenset({"denied", "blocked", "expired", "network", "config"})
#: `OidcError.code` -> frontend sababi. Keycloak `invalid_grant` = kod eskirgan
#: yoki ikki marta ishlatilgan (odam "orqaga" bosdi); `invalid_client` = bizning
#: sir noto'g'ri - administrator tuzatadi.
_REASON_MAP = {"invalid_grant": "expired", "invalid_client": "config", "unauthorized_client": "config"}


def _oidc() -> KeycloakOidc:
    """Chaqiruv paytida sozlamadan: testlar `settings.sso_*` ni almashtiradi."""
    return KeycloakOidc(settings.sso_issuer, settings.sso_client_id, settings.sso_client_secret,
                        timeout=settings.sso_timeout)


def _app_url(request: Request) -> str:
    """Ilovaning tashqi manzili (`sso_app_url` izohi, `core/config.py`)."""
    base = (settings.sso_app_url or "").strip().rstrip("/")
    if base:
        return base
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _safe_return(raw: str | None) -> str:
    """Kirishdan keyin qaytiladigan manzil: FAQAT ilova ichidagi yo'l (`/...`)
    yoki sozlangan mobil manzil. `//host` ochiq yo'naltirish bo'lardi."""
    value = (raw or "").strip()
    if value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    mobile = (settings.sso_mobile_redirect or "").strip()
    if mobile and value == mobile:
        return value
    return "/"


def _is_mobile(return_to: str) -> bool:
    mobile = (settings.sso_mobile_redirect or "").strip()
    return bool(mobile) and return_to == mobile


def _channel(request: Request, raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in _CHANNELS:
        return value
    found = channel_of(request)
    return found if found in _CHANNELS else "web"


def _with_query(url: str, params: dict[str, str]) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urllib.parse.urlencode(params)}"


def _done_url(app: str, return_to: str, handoff: str) -> str:
    """Kirish tugadi: frontend `?sso=<kod>` ni ko'rib `exchange` ni chaqiradi."""
    if _is_mobile(return_to):
        return _with_query(return_to, {"sso": handoff})
    params = {"sso": handoff}
    if return_to != "/":
        params["redirect"] = return_to
    return _with_query(f"{app}/login", params)


def _fail_url(app: str, return_to: str, reason: str) -> str:
    reason = _REASON_MAP.get(reason, reason)
    code = reason if reason in _PUBLIC_REASONS else "failed"
    target = return_to if _is_mobile(return_to) else f"{app}/login"
    return _with_query(target, {"sso_error": code})


def _admit(user: AuthUser, login: str | None, *, attempt: str, method: str,
           channel: str) -> admin_users.Access:
    """Shaxs TASDIQLANGANDAN keyin: admin bloklaganmi? -> `Access` yoki 403.

    Tekshiruv shaxs tasdiqlangandan KEYIN, ataylab: aks holda "bloklangan"
    javobi parolni bilmagan odamga ham hisob borligini aytib qo'yardi.
    `devices.py` va `telegram.py` ham shu qoidani ishlatadi.
    """
    verdict = admin_users.access(user, login=login)
    if not verdict.blocked:
        return verdict
    record_auth_event(attempt, False, method=method, channel=channel, reason="blocked",
                      actor_id=user.actorId)
    log.info("Kirish rad etildi - hisob bloklangan: actor_id %s", user.actorId)
    raise error_status(status.HTTP_403_FORBIDDEN, _MSG_BLOCKED)


# --- SSO ---------------------------------------------------------------------


@router.get("/sso/config", response_model=SsoConfig)
def sso_config() -> SsoConfig:
    """Kirish sahifasi uchun: qaysi yo'llar ochiq. Ochiq endpoint, sir yo'q."""
    return SsoConfig(
        enabled=_oidc().configured,
        localLoginEnabled=bool(settings.local_login_enabled),
        startPath=START_PATH,
    )


@router.get("/sso/start", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
def sso_start(
    request: Request,
    return_to: str | None = Query(default=None, alias="return"),
    channel: str | None = None,
) -> RedirectResponse:
    """Brauzerni Keycloak kirish sahifasiga yuboradi.

    `return` - kirishdan keyin qaytiladigan ilova yo'li (`/admin/users`),
    `channel` - web/miniapp/desktop/mobile (hisob uchun). Ikkalasi
    `state` ostida serverda turadi, Keycloak'ga ketmaydi.
    """
    oidc = _oidc()
    if not oidc.configured:
        raise error_status(status.HTTP_501_NOT_IMPLEMENTED, "SSO sozlanmagan")
    url = oidc.begin(f"{_app_url(request)}{CALLBACK_PATH}",
                     return_to=_safe_return(return_to), channel=_channel(request, channel))
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/sso/callback", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def sso_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    store: UserStore = Depends(get_user_store),
    identities: IdentityStore = Depends(get_identity_store),
) -> RedirectResponse:
    """Keycloak'dan qaytish. Har qanday natija - frontend'ga yo'naltirish:
    muvaffaqiyat `?sso=<bir martalik kod>`, xato `?sso_error=<sabab>`.
    JSON emas: bu manzilni brauzerning o'zi ochadi, JS yo'q.

    `async def` EMAS: Keycloak'ka `urllib` bilan boriladi (bloklaydi).
    """
    oidc = _oidc()
    app = _app_url(request)
    return_to, channel = "/", _channel(request, None)
    try:
        pending = oidc.take_pending(state)
        return_to, channel = pending.return_to, pending.channel
        if error:
            # Odam Keycloak sahifasida "bekor" dedi yoki Keycloak so'rovni rad etdi.
            raise OidcError(error_description or error, status=400,
                            code="denied" if error == "access_denied" else error)
        if not code:
            raise OidcError("Keycloak kod qaytarmadi", status=400, code="no_code")
        tokens = oidc.exchange(code, pending, f"{app}{CALLBACK_PATH}")
        profile = oidc.profile(tokens, nonce=pending.nonce)
    except OidcError as exc:
        log.warning("SSO kirish bajarilmadi (%s): %s", exc.code, exc)
        record_auth_event("sso", False, method="sso", channel=channel, reason=f"sso:{exc.code}")
        return RedirectResponse(_fail_url(app, return_to, exc.code), status_code=status.HTTP_303_SEE_OTHER)

    login = profile.username
    try:
        known = identities.by_subject(profile.subject)
        if known is not None:
            # Ma'lum odam - blokni `identities.json` ga TEGMASDAN tekshiramiz:
            # bloklangan urinish "oxirgi kirish" bo'lib ko'rinmasin.
            _admit(known.to_public(), known.username, attempt=login, method="sso", channel=channel)
        identity = identities.upsert(profile, legacy=store)
        # Birinchi kirishda `actor_id` eski (`users.yaml`) hisobdan kelishi
        # mumkin - u bloklangan bo'lsa ham shu yerda to'xtaydi.
        verdict = _admit(identity.to_public(), identity.username, attempt=login, method="sso",
                         channel=channel)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        return RedirectResponse(_fail_url(app, return_to, "blocked"), status_code=status.HTTP_303_SEE_OTHER)

    token, expires = create_token(identity.subject, version=verdict.token_version)
    if tokens.id_token:
        ID_TOKENS[identity.actor_id] = tokens.id_token
    record_auth_event(login, True, method="sso", channel=channel, actor_id=identity.actor_id)
    log.info("Kirish (SSO): %s (actor_id %s, %s)", identity.username, identity.actor_id, channel)
    response = LoginResponse(
        token=token,
        tokenType="Bearer",
        expiresAt=expires.isoformat(),
        passwordChangeRequired=False,
        user=verdict.user,
    )
    handoff = secrets.token_urlsafe(32)
    HANDOFF.put(handoff, response.model_dump())
    return RedirectResponse(_done_url(app, return_to, handoff), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sso/exchange", response_model=LoginResponse)
def sso_exchange(body: SsoExchangeRequest) -> LoginResponse:
    """Bir martalik kod -> token. Ikkinchi marta 400: kod ishlatilgan."""
    code = (body.code or "").strip()
    payload = HANDOFF.pop(code) if code else None
    if payload is None:
        raise error_status(status.HTTP_400_BAD_REQUEST, _MSG_HANDOFF)
    return LoginResponse(**payload)


# --- zahira (parol) -----------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    request: Request,
    store: UserStore = Depends(get_user_store),
) -> LoginResponse:
    """Zahira hisob (`config/users.yaml`): login + parol -> token.

    Har urinish `auth_events` ga yoziladi: natija, yo'l (`local`), sabab
    kodi - PAROL HECH QACHON.
    """
    channel = channel_of(request)
    if not settings.local_login_enabled:
        record_auth_event(data.username, False, method="local", channel=channel,
                          reason="local_login_disabled")
        raise error_status(status.HTTP_403_FORBIDDEN, _MSG_LOCAL_OFF)
    # `authenticate` topilmagan hisob uchun ham xeshni tekshiradi - javob
    # vaqti bo'yicha hisob borligini aniqlab bo'lmaydi.
    user = store.authenticate(data.username, data.password)
    if user is None:
        log.info("Muvaffaqiyatsiz kirish: %s", data.username)
        record_auth_event(data.username, False, method="local", channel=channel,
                          reason="bad_credentials")
        raise unauthorized(_MSG_BAD_LOGIN)
    verdict = _admit(user.to_public(), None, attempt=data.username, method="local", channel=channel)
    token, expires = create_token(user.email, version=verdict.token_version)
    record_auth_event(data.username, True, method="local", channel=channel, actor_id=user.actor_id)
    log.info("Kirish (zahira): %s", user.email)
    return LoginResponse(
        token=token,
        tokenType="Bearer",
        expiresAt=expires.isoformat(),
        passwordChangeRequired=user.password_change_required,
        user=verdict.user,
    )


# --- sessiya -----------------------------------------------------------------


@router.get("/me", response_model=AuthUser)
def me(user: AuthUser = Depends(current_user)) -> AuthUser:
    """Token'ni tekshiradi va foydalanuvchini qaytaradi.

    Frontend uni ilova ochilganda chaqiradi: token localStorage da saqlangan
    bo'lsa ham u eskirgan bo'lishi mumkin.
    """
    return user


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    user: AuthUser = Depends(current_user),
    identities: IdentityStore = Depends(get_identity_store),
) -> LogoutResponse:
    """Sessiyani yopish.

    JWT HOLATSIZ - server tomonda bekor qilinadigan sessiya YO'Q: tokenni
    FRONTEND o'chiradi, u muddati tugaguncha (`token_ttl_hours`) texnik
    jihatdan yaroqli qoladi. Odamning HAMMA sessiyasini admin tugata oladi:
    `POST /admin/users/{id}/signout` versiyani oshiradi (`api/deps.py`).

    SSO bilan kirgan odamga `ssoLogoutUrl` qaytadi: frontend o'sha yerga
    o'tadi va KEYCLOAK sessiyasi ham yopiladi. Aks holda "Kirish" tugmasi
    odamni so'ramasdan qaytadan kiritardi (SSO sessiyasi tirik) - umumiy
    kompyuterda bu xavfli.

    Ulanishlar (HRM/CRM) QOLADI - ular sessiya emas, odamning saqlangan
    ulanishi; uzish "+" menyusida. Xotiradagi HRM paroli esa o'chiriladi.
    """
    _connectors.hub.forget_password(str(user.actorId))
    sso_url: str | None = None
    oidc = _oidc()
    if oidc.configured and identities.by_actor_id(user.actorId) is not None:
        hint = ID_TOKENS.pop(user.actorId, None)
        sso_url = oidc.logout_url(f"{_app_url(request)}/welcome", id_token_hint=hint)
    log.info("Chiqish: %s", user.email)
    return LogoutResponse(status="OK", message="Sessiya yopildi", ssoLogoutUrl=sso_url)


@router.post("/signup", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def signup() -> None:
    """Ro'yxatdan o'tish YO'Q - hisob Keycloak'da, zahira `config/users.yaml` da."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Ro'yxatdan o'tish yo'q: SSO (Keycloak) hisobingiz bilan kiring.",
    )


@router.post("/change-password", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def change_password() -> None:
    """Parol Keycloak'da o'zgartiriladi - bu yerda emas."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Parol SSO (Keycloak) tizimida o'zgartiriladi - u yerda almashtiring.",
    )

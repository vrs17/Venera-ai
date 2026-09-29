"""Autentifikatsiya endpointlari.

KIRISH IKKI YO'L BILAN (`login`):

  1. SSO - Keycloak (`services/sso.py`). CRM ulanishi (`crm-client`)
     sozlangan bo'lsa login + parol O'SHA yerga ketadi. Keycloak "ha"
     desa: shaxs `identities.json` ga yoziladi (`actor_id` BIR MARTA
     tanlanadi, `services/identities.py`), Keycloak sessiyasi CRM
     ulanishiga aylanadi va o'sha parol bilan HRM ga ham kiriladi -
     "+" menyusida ikkalasi ham ULANGAN turadi, odam faqat kalitni
     buradi. HRM yiqilsa kirish baribir bo'ladi, HRM qatori "ulanmagan"
     qoladi va odam uni menyudan o'zi ulaydi.

  2. Zahira - `config/users.yaml` (`local_login_enabled`). Keycloak
     sozlanmagan, o'chgan yoki parolni rad etgan bo'lsa sinab ko'riladi:
     administrator Keycloak'siz ham kira olsin.

Frontend (`apps/web/src/api/auth.api.ts`) beshta endpoint chaqiradi. Uchtasi
bajarilgan; qolgan ikkitasi (`signup`, `change-password`) ATAYLAB 501
qaytaradi - "bor, lekin hali qilinmagan" degani "yo'q" dan aniqroq va
frontend ularni chaqirsa tushunarli xabar ko'radi. SSO bilan ular umuman
kerak emas: hisob va parol Keycloak'da.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.config import settings
from ...core.errors import error_status, unauthorized
from ...core.security import create_token
from ...schemas.auth import AuthUser, LoginRequest, LoginResponse, LogoutResponse
from ...services.identities import Identity, IdentityStore
from ...services.integrations.connectors import ConnectorError
from ...services.sso import KeycloakSso, SsoError, SsoLogin
from ...services.users import UserStore
from . import connectors as _connectors
from ..deps import current_user, get_identity_store, get_user_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

#: Xabar ATAYLAB UMUMIY (Keycloak ham, zahira ham): qaysi biri xato
#: ekanini aytsak, qaysi loginlar borligini aniqlash mumkin bo'lardi.
_MSG_BAD_LOGIN = "Login yoki parol noto'g'ri"


def _sso() -> KeycloakSso:
    """Keycloak - ulanishlar markazidagi AYNI sozlama (`connectors.hub.crm`).

    Chaqiruv paytida o'qiladi: testlar `hub` ni almashtiradi va SSO shu
    bilan birga sozlanmagan/soxta bo'ladi - jonli Keycloak'ka chiqmaydi.
    """
    return KeycloakSso(_connectors.hub.crm)


def _auto_connect(identity: Identity, username: str, password: str, login: SsoLogin) -> None:
    """Kirgan odam uchun "+" menyusidagi ikkala qatorni ochadi.

    CRM - Keycloak javobidan (qo'shimcha so'rovsiz). HRM - o'sha login va
    parol bilan (`HrmAuth.login`); parol shu yerdan nariga o'tmaydi. HRM
    xatosi kirishni TO'XTATMAYDI: odam kirsin, HRM ni keyin menyudan ulaydi.
    """
    hub = _connectors.hub
    uid = str(identity.actor_id)
    hub.adopt_crm(uid, login.profile.username, login.access_token, login.refresh_token,
                  login.ttl, keep_enabled=True, revoke_old=True)
    if not hub.hrm.configured:
        return
    # Parolni XOTIRADA tutamiz - HRM tokeni 10 soatda o'ladi va uni
    # yangilashning boshqa yo'li yo'q (`connectors.py` moduli izohi).
    # Keycloak uni hozirgina tasdiqladi, ya'ni saqlashga arziydi.
    hub.remember_password(uid, password)
    try:
        hub.connect(uid, "hrm", username, password, keep_enabled=True)
    except ConnectorError as exc:
        log.warning("HRM avto-ulanish (%s): %s", identity.username, exc)


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    store: UserStore = Depends(get_user_store),
    identities: IdentityStore = Depends(get_identity_store),
) -> LoginResponse:
    """Login + parol -> token. Avval Keycloak, keyin zahira (`users.yaml`).

    `async def` EMAS: Keycloak va HRM ga `urllib` bilan boriladi
    (bloklaydi), FastAPI oddiy `def` ni threadpool'da bajaradi.
    """
    sso = _sso()
    sso_error: SsoError | None = None
    if sso.configured:
        try:
            result = sso.login(data.username, data.password)
        except SsoError as exc:
            sso_error = exc
        else:
            identity = identities.upsert(result.profile, legacy=store)
            _auto_connect(identity, data.username, data.password, result)
            token, expires = create_token(identity.subject)
            log.info("Kirish (SSO): %s (actor_id %s)", identity.username, identity.actor_id)
            return LoginResponse(
                token=token,
                tokenType="Bearer",
                expiresAt=expires.isoformat(),
                passwordChangeRequired=False,
                user=identity.to_public(),
            )

    # Zahira. `authenticate` topilmagan hisob uchun ham xeshni tekshiradi -
    # javob vaqti bo'yicha hisob borligini aniqlab bo'lmaydi.
    user = store.authenticate(data.username, data.password) if settings.local_login_enabled else None
    if user is not None:
        token, expires = create_token(user.email)
        log.info("Kirish (zahira): %s", user.email)
        return LoginResponse(
            token=token,
            tokenType="Bearer",
            expiresAt=expires.isoformat(),
            passwordChangeRequired=user.password_change_required,
            user=user.to_public(),
        )

    if sso_error is not None and not sso_error.bad_credentials:
        # Keycloak javob bermadi yoki hisobni (parolni emas) rad etdi -
        # sababi odamga AYTILADI, u parolini emas, boshqa narsani tekshiradi.
        log.warning("SSO kirish (%s): %s", data.username, sso_error)
        raise error_status(sso_error.status, str(sso_error))
    log.info("Muvaffaqiyatsiz kirish: %s", data.username)
    raise unauthorized(_MSG_BAD_LOGIN)


@router.get("/me", response_model=AuthUser)
def me(user: AuthUser = Depends(current_user)) -> AuthUser:
    """Token'ni tekshiradi va foydalanuvchini qaytaradi.

    Frontend uni ilova ochilganda chaqiradi: token localStorage da saqlangan
    bo'lsa ham u eskirgan bo'lishi mumkin.
    """
    return user


@router.post("/logout", response_model=LogoutResponse)
def logout(user: AuthUser = Depends(current_user)) -> LogoutResponse:
    """Sessiyani yopish.

    JWT HOLATSIZ - server tomonda bekor qilinadigan sessiya YO'Q. Ya'ni bu
    endpoint amalda faqat tasdiq qaytaradi, tokenni esa FRONTEND o'chiradi.
    Token muddati tugaguncha (`token_ttl_hours`) texnik jihatdan yaroqli
    qoladi. Ulanishlar (HRM/CRM) ham QOLADI - ular sessiya emas, odamning
    saqlangan ulanishi; uzish "+" menyusida.

    XOTIRADAGI PAROL esa O'CHIRILADI: u faqat HRM tokenini yangilash
    uchun turardi, va "chiqdim" degan odam ortidan hech narsa qolmasligi
    kerak. Keyingi kirishda u qaytadan olinadi (`_auto_connect`).

    Haqiqiy bekor qilish kerak bo'lsa: Redis'da qora ro'yxat va
    `core/security.verify_token` da tekshiruv. Demo uchun ortiqcha.
    """
    _connectors.hub.forget_password(str(user.actorId))
    log.info("Chiqish: %s", user.email)
    return LogoutResponse(status="OK", message="Sessiya yopildi")


@router.post("/signup", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def signup() -> None:
    """Ro'yxatdan o'tish YO'Q - hisob Keycloak'da (HRM/CRM logini), zahira `config/users.yaml` da."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Ro'yxatdan o'tish yo'q: HRM/CRM logini va paroli bilan kiring.",
    )


@router.post("/change-password", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def change_password() -> None:
    """Parol Keycloak'da o'zgartiriladi (HRM/CRM paroli) - bu yerda emas."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Parol HRM/CRM tizimida o'zgartiriladi - u yerda almashtiring.",
    )

"""Autentifikatsiya endpointlari.

Frontend (`apps/web/src/api/auth.api.ts`) beshta endpoint chaqiradi. Demo
uchun uchtasi bajarilgan; qolgan ikkitasi (`signup`, `change-password`)
ATAYLAB 501 qaytaradi - "bor, lekin hali qilinmagan" degani "yo'q" dan
aniqroq va frontend ularni chaqirsa tushunarli xabar ko'radi.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.errors import unauthorized
from ...schemas.auth import AuthUser, LoginRequest, LoginResponse, LogoutResponse
from ...core.security import create_token
from ...services.users import UserStore
from ..deps import current_user, get_user_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    store: UserStore = Depends(get_user_store),
) -> LoginResponse:
    """Email + parol -> token.

    XATO XABARI ATAYLAB UMUMIY: "Email yoki parol noto'g'ri". Qaysi biri
    xato ekanini aytsak, qaysi emaillar ro'yxatda borligini aniqlash
    mumkin bo'lardi.
    """
    user = store.authenticate(data.email, data.password)
    if user is None:
        log.info("Muvaffaqiyatsiz kirish: %s", data.email)
        raise unauthorized("Email yoki parol noto'g'ri")

    token, expires = create_token(user.email)
    log.info("Kirish: %s", user.email)
    return LoginResponse(
        token=token,
        tokenType="Bearer",
        expiresAt=expires.isoformat(),
        passwordChangeRequired=user.password_change_required,
        user=user.to_public(),
    )


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
    qoladi.

    Haqiqiy bekor qilish kerak bo'lsa: Redis'da qora ro'yxat va
    `core/security.verify_token` da tekshiruv. Demo uchun ortiqcha.
    """
    log.info("Chiqish: %s", user.email)
    return LogoutResponse(status="OK", message="Sessiya yopildi")


@router.post("/signup", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def signup() -> None:
    """Demo uchun ro'yxatdan o'tish YO'Q - foydalanuvchilar `config/users.yaml` da."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Ro'yxatdan o'tish hozircha yopiq. Hisob uchun administratorga murojaat qiling.",
    )


@router.post("/change-password", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def change_password() -> None:
    """Parol o'zgartirish hali yo'q - xeshni administrator yasaydi."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Parolni o'zgartirish hozircha administrator orqali amalga oshiriladi.",
    )

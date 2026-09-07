"""FastAPI bog'liqliklari (dependencies).

Router'lar bu yerdagi funksiyalarni `Depends(...)` orqali oladi. Shu tufayli
autentifikatsiya mantig'i BITTA joyda turadi va har endpoint uni takrorlamaydi.

Test qilish ham shu tufayli oson: `app.dependency_overrides[current_user] = ...`
deb yozib, tokensiz test yozish mumkin.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Request

from ..core.config import settings
from ..core.errors import unauthorized
from ..core.security import verify_token
from ..schemas.auth import AuthUser
from ..services.users import UserStore


@lru_cache(maxsize=1)
def get_user_store() -> UserStore:
    """Foydalanuvchilar ombori - fayl bir marta o'qiladi.

    Fayl o'zgarsa serverni qayta ishga tushirish kerak. Demo uchun bu maqbul;
    DB ga o'tilganda `lru_cache` olib tashlanadi.
    """
    return UserStore.from_file(settings.users_file)


def bearer_token(request: Request) -> str:
    """`Authorization: Bearer <token>` sarlavhasidan tokenni ajratadi."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized("Token yuborilmadi")
    return token.strip()


def current_user(
    token: str = Depends(bearer_token),
    store: UserStore = Depends(get_user_store),
) -> AuthUser:
    """Token'dan foydalanuvchini tiklaydi.

    MUHIM: shaxs FAQAT shu yerdan keladi. Endpoint'lar so'rov tanasidagi
    email/id ga HECH QACHON ishonmaydi - aks holda klient o'zini boshqa
    xodim deb tanishtira olardi.
    """
    email = verify_token(token)
    if not email:
        raise unauthorized("Token yaroqsiz yoki muddati tugagan")

    user = store.by_email(email)
    if user is None:
        # Token haqiqiy, lekin foydalanuvchi o'chirilgan - 401 beramiz,
        # 403 emas: sessiya endi yaroqsiz va qayta kirish kerak.
        raise unauthorized("Foydalanuvchi topilmadi")
    return user.to_public()

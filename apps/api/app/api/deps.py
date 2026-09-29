"""FastAPI bog'liqliklari (dependencies).

Router'lar bu yerdagi funksiyalarni `Depends(...)` orqali oladi. Shu tufayli
autentifikatsiya mantig'i BITTA joyda turadi va har endpoint uni takrorlamaydi.

Test qilish ham shu tufayli oson: `app.dependency_overrides[current_user] = ...`
deb yozib, tokensiz test yozish mumkin.
"""

from __future__ import annotations

import base64
import binascii

from functools import lru_cache

from fastapi import Depends, Request, status
from fastapi import HTTPException

from ..core.config import settings
from ..core.errors import unauthorized
from ..core.security import verify_token
from ..schemas.auth import AuthUser
from ..services.identities import Directory, IdentityStore
from ..services.users import UserStore


@lru_cache(maxsize=1)
def get_user_store() -> UserStore:
    """Foydalanuvchilar ombori - fayl bir marta o'qiladi.

    Fayl o'zgarsa serverni qayta ishga tushirish kerak. Demo uchun bu maqbul;
    DB ga o'tilganda `lru_cache` olib tashlanadi.
    """
    return UserStore.from_file(settings.users_file)


@lru_cache(maxsize=1)
def get_identity_store() -> IdentityStore:
    """SSO bilan kirganlar (`services/identities.py`). Fayl o'zgarsa
    ombor o'zi qayta o'qiydi - qayta ishga tushirish shart emas."""
    return IdentityStore(settings.identities_file)


def get_directory() -> Directory:
    """Telegram bot uchun: `actor_id` -> hisob, ikkala manbadan."""
    return Directory(get_identity_store(), get_user_store())


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
    identities: IdentityStore = Depends(get_identity_store),
) -> AuthUser:
    """Token'dan foydalanuvchini tiklaydi.

    MUHIM: shaxs FAQAT shu yerdan keladi. Endpoint'lar so'rov tanasidagi
    email/id ga HECH QACHON ishonmaydi - aks holda klient o'zini boshqa
    xodim deb tanishtira olardi.

    Tokenning `sub` i ikki xil: SSO bilan kirganda Keycloak `sub` (UUID,
    `identities.json` da), zahira hisobda email (`users.yaml` da). UUID
    ichida `@` bo'lmaydi, shuning uchun ikkisi aralashmaydi.
    """
    subject = verify_token(token)
    if not subject:
        raise unauthorized("Token yaroqsiz yoki muddati tugagan")

    identity = identities.by_subject(subject)
    if identity is not None:
        return identity.to_public()
    user = store.by_email(subject)
    if user is None:
        # Token haqiqiy, lekin foydalanuvchi o'chirilgan - 401 beramiz,
        # 403 emas: sessiya endi yaroqsiz va qayta kirish kerak.
        raise unauthorized("Foydalanuvchi topilmadi")
    return user.to_public()


def _basic_challenge(message: str) -> HTTPException:
    """401 + `WWW-Authenticate: Basic` - brauzer parol oynasini ko'rsatadi.

    `Bearer` EMAS: hujjat sahifasi brauzerda ochiladi va u yerda token
    yuboradigan JS yo'q. Basic bilan brauzerning o'zi so'raydi.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": 'Basic realm="Venera API - hujjat"'},
    )


def docs_viewer(
    request: Request,
    store: UserStore = Depends(get_user_store),
) -> str:
    """Hujjat sahifasi uchun HTTP Basic tekshiruvi.

    NEGA KERAK: sayt tashqi proksi orqali internetdan ochiq. Himoyasiz
    `/api/docs` va `/api/openapi.json` har kimga butun endpoint ro'yxatini,
    so'rov/javob modellarini va rol nomlarini beradi - ya'ni hujumchiga
    nimani sinashni aytib beradi.

    Alohida parol EMAS, mavjud hisoblar ishlatiladi: ikkinchi sir ikkinchi
    unutiladigan joy bo'lardi.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "basic" or not raw.strip():
        raise _basic_challenge("Hujjat uchun kirish talab qilinadi")

    try:
        decoded = base64.b64decode(raw.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise _basic_challenge("Sarlavha buzilgan")

    email, sep, password = decoded.partition(":")
    if not sep:
        raise _basic_challenge("Sarlavha buzilgan")

    # `authenticate` mavjud bo'lmagan email uchun ham parolni tekshiradi -
    # javob vaqti bo'yicha email borligini aniqlab bo'lmaydi.
    user = store.authenticate(email, password)
    if user is None:
        raise _basic_challenge("Email yoki parol noto'g'ri")
    return user.email

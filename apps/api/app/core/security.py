"""Parol va token.

PAROL: `hashlib.pbkdf2_hmac` - stdlib, qo'shimcha bog'liqliksiz. bcrypt/argon2
kuchliroq, lekin ular C kengaytma talab qiladi va demo uchun PBKDF2 (600k
iteratsiya) yetarli. Almashtirish oson: faqat shu fayldagi ikki funksiya.

PAROL HECH QACHON OCHIQ SAQLANMAYDI - `config/users.yaml` da faqat xesh
turadi. Xeshni yasash uchun: `python -m app.tools.hash_password`.

TOKEN: JWT (PyJWT). Nima uchun sessiya emas: backend HOLATSIZ (stateless)
bo'lsa gorizontal kengayadi - ikkinchi nusxa qo'shsangiz hech narsa
sozlamaysiz. Tokenni muddatidan oldin bekor qilish uchun qora ro'yxat
(Redis) o'rniga tokenda `ver` turadi - odamning sessiya versiyasi. Admin
versiyani oshirsa eski tokenlar rad etiladi (`TokenClaims`, `api/deps.py`).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

#: OWASP 2023 tavsiyasi (PBKDF2-HMAC-SHA256 uchun).
_ITERATIONS = 600_000
_ALGORITHM = "HS256"


def hash_password(password: str, salt: str | None = None) -> str:
    """`pbkdf2$<iteratsiya>$<salt>$<xesh>` ko'rinishidagi satr.

    Format o'z ichiga iteratsiya sonini oladi - shunda kelajakda uni
    oshirsak ESKI xeshlar ham tekshirilaveradi.
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Parolni xesh bilan solishtiradi. Noto'g'ri formatda False qaytaradi."""
    try:
        scheme, iterations, salt, expected = stored.split("$", 3)
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    # compare_digest - vaqt bo'yicha hujumdan (timing attack) himoya.
    return hmac.compare_digest(digest.hex(), expected)


@dataclass(frozen=True)
class TokenClaims:
    """Tekshirilgan tokendan kerakli ikki narsa.

    `version` - token berilgan paytdagi `user_admin.token_version`. Admin
    "hamma sessiyalardan chiqarish" ni bossa versiya oshadi va shu
    paytgacha berilgan HAMMA token yaroqsiz bo'ladi (`api/deps.py`).
    """

    subject: str
    version: int = 0
    #: Brauzer SSO kirishidan ochilgan sessiya (`create_token(sso=True)`).
    sso: bool = False


def create_token(subject: str, *, version: int = 0, sso: bool = False) -> tuple[str, datetime]:
    """(token, tugash vaqti). `subject` - SSO `sub` yoki zahira hisob emaili.

    `version` - `ver` claim'i. Eski tokenlarda u YO'Q va 0 deb o'qiladi:
    shu tufayli bu o'zgarishdan oldin berilgan sessiyalar uzilmaydi.
    """
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.token_ttl_hours)
    payload = {
        "sub": subject,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
        "ver": int(version),
    }
    if sso:
        # Sessiya BRAUZER SSO kirishidan ochilgan: chiqishda Keycloak sessiyasi ham
        # yopiladi (`api/v1/auth.py` logout). Telegram, qurilma va zahira (parol)
        # sessiyalarida bu belgi yo'q.
        payload["sso"] = True
    token = jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)
    return token, expires


def verify_claims(token: str) -> TokenClaims | None:
    """Token haqiqiy bo'lsa `TokenClaims`, aks holda None.

    ISTISNO TASHLAMAYDI: chaqiruvchi (api/deps.py) 401 ni o'zi hosil qiladi
    va shu bilan xato matni bitta joyda boshqariladi.

    `ver` butun son bo'lmasa token RAD ETILADI: bu maydonni faqat biz
    yozamiz, boshqacha qiymat - buzilgan yoki soxta token.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    if not subject:
        return None
    version = payload.get("ver", 0)
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return TokenClaims(subject=str(subject), version=version, sso=payload.get("sso") is True)


def verify_token(token: str) -> str | None:
    """Token haqiqiy bo'lsa `sub` qaytaradi, aks holda None (`verify_claims`
    ning qisqa shakli - versiya kerak bo'lmagan joylar uchun)."""
    claims = verify_claims(token)
    return claims.subject if claims else None

"""Parol va token.

PAROL: `hashlib.pbkdf2_hmac` - stdlib, qo'shimcha bog'liqliksiz. bcrypt/argon2
kuchliroq, lekin ular C kengaytma talab qiladi va demo uchun PBKDF2 (600k
iteratsiya) yetarli. Almashtirish oson: faqat shu fayldagi ikki funksiya.

PAROL HECH QACHON OCHIQ SAQLANMAYDI - `config/users.yaml` da faqat xesh
turadi. Xeshni yasash uchun: `python -m app.tools.hash_password`.

TOKEN: JWT (PyJWT). Nima uchun sessiya emas: backend HOLATSIZ (stateless)
bo'lsa gorizontal kengayadi - ikkinchi nusxa qo'shsangiz hech narsa
sozlamaysiz. Narxi: chiqarilgan tokenni muddatidan oldin bekor qilib
bo'lmaydi. Demo uchun bu maqbul; keyinchalik kerak bo'lsa qora ro'yxat
(Redis) qo'shiladi va faqat `verify_token` o'zgaradi.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
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


def create_token(subject: str) -> tuple[str, datetime]:
    """(token, tugash vaqti). `subject` - foydalanuvchi emaili."""
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.token_ttl_hours)
    payload = {
        "sub": subject,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)
    return token, expires


def verify_token(token: str) -> str | None:
    """Token haqiqiy bo'lsa `sub` (email) qaytaradi, aks holda None.

    ISTISNO TASHLAMAYDI: chaqiruvchi (api/deps.py) 401 ni o'zi hosil qiladi
    va shu bilan xato matni bitta joyda boshqariladi.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None

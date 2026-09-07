"""Autentifikatsiya sxemalari.

MUHIM: bu modeller `apps/web/src/types.ts` dagi interfeyslarning AYNAN
nusxasi. Maydon nomi yoki turi farq qilsa frontend jimgina buziladi -
TypeScript kompilyatori serverdan kelgan JSON ni tekshira olmaydi.

Shuning uchun qoida: bu yerni o'zgartirsangiz `types.ts` ni ham o'zgartiring
va aksincha. Ikkalasining mosligini `tests/test_contract.py` tekshiradi.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class AuthUser(BaseModel):
    """types.ts: AuthUser

    Shaxsni server token'dan aniqlaydi - frontend bu maydonlarni HECH QACHON
    yubormaydi, faqat oladi.
    """

    actorId: int
    actorType: str = "EMPLOYEE"          # EMPLOYEE | CUSTOMER
    email: str
    fullName: str
    position: str | None = None
    department: str | None = None
    roles: list[str] = Field(default_factory=list)
    passwordChangeRequired: bool = False


class LoginRequest(BaseModel):
    """types.ts: LoginRequest"""

    email: str
    password: str


class LoginResponse(BaseModel):
    """types.ts: LoginResponse"""

    token: str
    tokenType: str = "Bearer"
    #: ISO-8601 UTC. Frontend uni faqat ko'rsatish uchun ishlatadi, tokenning
    #: haqiqiyligini SERVER tekshiradi.
    expiresAt: str
    passwordChangeRequired: bool = False
    user: AuthUser


class LogoutResponse(BaseModel):
    """types.ts: LogoutResponse"""

    status: str = "OK"
    message: str = ""


class ApiErrorResponse(BaseModel):
    """types.ts: ApiErrorResponse - HAR QANDAY xatoda qaytadigan yagona shakl.

    Frontend `api/http.ts:apiFetch` aynan `message` maydonini o'qiydi
    (`body?.message || "Request failed (status)"`). Boshqa shaklda qaytarsak
    foydalanuvchi doim umumiy "Request failed" ni ko'radi.

    DIQQAT: FastAPI default holda `{"detail": "..."}` qaytaradi - bu MOS
    KELMAYDI. `core/errors.py` shuning uchun handler'larni almashtiradi.
    """

    timestamp: str
    status: int
    error: str
    message: str
    path: str

"""Ulanishlar sxemalari - `apps/web/src/types.ts` dagi `ConnectorStatus` va
`ConnectRequest` ning aynan nusxasi. `tests/test_connectors.py` mosligini
tekshiradi.

TOKEN BU YERDA YO'Q va bo'lmaydi: klient faqat holatni ko'radi.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectorStatus(BaseModel):
    """types.ts: ConnectorStatus"""

    #: Odamga faqat `hrm` qaytadi (`USER_PLATFORMS`); `crm` - admin panel qatorida.
    id: str                      # hrm | crm
    label: str                   # HRM | CRM
    #: Serverda sozlanganmi (`.env`). Sozlanmagan bo'lsa "+" bosilmaydi.
    configured: bool
    #: disconnected | connected | expired
    state: str
    #: Ulangan hisobning logini - qatorda ko'rsatish uchun.
    login: str | None = None
    #: Kalit yo'q: yozuv bor bo'lsa har doim `true` (ulangan = ishlatiladi).
    #: Maydon eski klientlar (mobil ilova) uchun qoldi.
    enabled: bool = False
    #: HRM tokenining muddati (ISO-8601 UTC). CRM da va SSO ulanishida yo'q -
    #: token o'zi yangilanadi.
    expiresAt: str | None = None
    #: `sso` - ulanish BRB-Tech ID kirishidan (odam uni qo'lda yangilamaydi;
    #: qayta kirish uni yangilaydi), `null` - login + parol bilan qo'lda ulangan.
    via: str | None = None


class ConnectorsResponse(BaseModel):
    """types.ts: ConnectorsResponse"""

    connectors: list[ConnectorStatus]


class ConnectRequest(BaseModel):
    """types.ts: ConnectRequest - platformaning O'Z logini va paroli."""

    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class ConnectorUpdate(BaseModel):
    """`PATCH /connectors/{platform}` tanasi - eski klientlar uchun. `enabled`
    qabul qilinadi, lekin hech narsani hal qilmaydi (kalit yo'q)."""

    enabled: bool

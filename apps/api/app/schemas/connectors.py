"""Ulanishlar sxemalari - `apps/web/src/types.ts` dagi `ConnectorStatus` va
`ConnectRequest` ning aynan nusxasi. `tests/test_connectors.py` mosligini
tekshiradi.

TOKEN BU YERDA YO'Q va bo'lmaydi: klient faqat holatni ko'radi.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectorStatus(BaseModel):
    """types.ts: ConnectorStatus"""

    id: str                      # hrm | crm
    label: str                   # HRM | CRM
    #: Serverda sozlanganmi (`.env`). Sozlanmagan bo'lsa "+" bosilmaydi.
    configured: bool
    #: disconnected | connected | expired
    state: str
    #: Ulangan hisobning logini - qatorda ko'rsatish uchun.
    login: str | None = None
    #: Ulangan tizim chatda ishlatiladi (kalit).
    enabled: bool = False
    #: HRM tokenining muddati (ISO-8601 UTC). CRM da yo'q - u o'zi yangilanadi.
    expiresAt: str | None = None


class ConnectorsResponse(BaseModel):
    """types.ts: ConnectorsResponse"""

    connectors: list[ConnectorStatus]


class ConnectRequest(BaseModel):
    """types.ts: ConnectRequest - platformaning O'Z logini va paroli."""

    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class ConnectorUpdate(BaseModel):
    """types.ts: ConnectorUpdate"""

    enabled: bool

"""Jonli ovozli suhbat (`/api/v1/live`, `api/v1/live.py`) - so'rov va javob shakllari."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


class LiveSessionRequest(BaseModel):
    #: Suhbatdosh. Hozircha faqat Barno (Speko'dagi «O'zbek operator» agenti): boshqa ovoz yo'q.
    persona: Literal["barno"] = "barno"


class LiveSessionResponse(BaseModel):
    """Brauzerdagi ovozli klient (`@spekoai/client`) uchun bir martalik ulanish ma'lumoti. Platforma kaliti
    bu yerda YO'Q - faqat shu suhbatning qisqa muddatli tokeni."""

    sessionId: str = Field(description="Speko sessiya raqami (loglar va fikr-mulohaza uchun)")
    transport: str = Field(description="Media transporti: `livekit` (yoki `daily`)")
    transportToken: str
    transportUrl: str
    expiresAt: str | None = None


#: Baho sababi - sahifadagi tayyor tugma kaliti (`natural`, `slow`, ...): erkin matn emas.
Reason = Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,24}$")]


class LiveFeedbackRequest(BaseModel):
    """Suhbatdan keyingi baho (rahmat sahifasi)."""

    sessionId: str = Field(default="", max_length=80)
    persona: Literal["barno"] = "barno"
    rating: int = Field(ge=1, le=5)
    reasons: list[Reason] = Field(default_factory=list, max_length=8)
    comment: str = Field(default="", max_length=500)
    durationSec: int = Field(default=0, ge=0, le=24 * 3600)


class LiveFeedbackResponse(BaseModel):
    saved: bool = True

"""HRM integratsiyasi: kechikish sababiga avtomatik qaror (`POST /api/v1/hrm/late-decision`).

Maydon nomlari camelCase - HRM (Java/Jackson) va STT javobi (`lowConfidence`) bilan bir xil.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LateReasonMessage(BaseModel):
    text: str = Field(default="", max_length=4000,
                      description="Xodim yozgan matn (ovozli xabar - STT matni, `🎤` bilan)")
    minutesAfterNotice: int | None = Field(default=None, description="Xabarnomadan necha daqiqa keyin yozilgan")
    beforeNotice: bool = Field(default=False, description="Xabarnomadan OLDIN yozilgan (oldindan ogohlantirish)")
    attachments: int = Field(default=0, ge=0, le=50, description="Biriktirilgan fayllar soni (rasm, hujjat)")


class LateDecisionRequest(BaseModel):
    lateId: int | None = Field(default=None, description="HRM `employee_late.id` - faqat jurnal uchun")
    workDate: str | None = Field(default=None, max_length=10, description="Ish kuni, YYYY-MM-DD")
    arrivalTime: str | None = Field(default=None, max_length=8, description="Kelgan vaqt, HH:MM")
    lateMinutes: int | None = Field(default=None, ge=0, le=1440, description="Necha daqiqa kechikkan")
    messages: list[LateReasonMessage] = Field(default_factory=list, max_length=40,
                                              description="Xodimning shu kungi xabarlari, vaqt tartibida")


class LateDecisionResponse(BaseModel):
    decision: Literal["APPROVE", "REJECT", "MANUAL"] = Field(
        description="APPROVE / REJECT - HRM avtomatik qo'llaydi; MANUAL - HR manager hal qiladi")
    category: str = Field(description="Sabab toifasi (`services/hrm_late.CATEGORIES`)")
    confidence: float = Field(default=0.0, description="Model ishonchi, 0..1")
    note: str = Field(default="", description="HR uchun qisqa izoh (o'zbekcha): toifa va xodim nima degani")
    model: str | None = Field(default=None, description="Baholagan model")

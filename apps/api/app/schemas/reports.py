"""Shikoyat ("Xabar berish") - foydalanuvchi tomoni: `apps/web/src/types.ts`
dagi `ReportCreate`, `ReportMessage`, `ReportCreated` ning aynan nusxasi;
`tests/test_contract.py` mosligini tekshiradi.

Admin tomonidagi `ReportSummary` / `ReportDetail` - `schemas/admin.py` da.

CHEGARALAR shu yerda, chunki bu tana to'g'ridan-to'g'ri omborga tushadi:
izoh 2000 belgi, xabarlar 200 ta, har biri 20 000 belgi. Uzun matn KESILADI
(odam javobning uzunligini tanlamaydi - shikoyat shu sababli yo'qolmasin),
ro'yxat chegarasidan oshsa esa 422: klient oxirgi 200 tasini yuborishi kerak.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

#: Sabab kodlari - frontend chiplari shu tartibda.
REASONS: tuple[str, ...] = ("wrong", "incomplete", "outdated", "unsafe", "other")

COMMENT_LIMIT = 2000
MESSAGES_LIMIT = 200
CONTENT_LIMIT = 20_000
SOURCES_LIMIT = 50


class ReportMessage(BaseModel):
    """types.ts: ReportMessage - suhbatdagi bitta xabar.

    Klient yuboradigan zahira nusxa ham, saqlangan `snapshot.messages` ham
    shu shaklda. `turnId` - `X-Venera-Turn` (javob izi), `sources` -
    javob manbalari (klientdagi shaklda; server faqat tanish maydonlarni
    saqlaydi). Telemetriyadan olingan javobda qo'shimcha `status` bo'ladi.
    """

    role: Literal["user", "assistant"]
    content: str = ""
    createdAt: str | None = Field(default=None, max_length=64)
    turnId: str | None = Field(default=None, max_length=64)
    sources: list[Any] | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _cap_content(cls, value: Any) -> Any:
        if isinstance(value, str) and len(value) > CONTENT_LIMIT:
            return value[:CONTENT_LIMIT]
        return value

    @field_validator("sources", mode="before")
    @classmethod
    def _cap_sources(cls, value: Any) -> Any:
        if isinstance(value, list) and len(value) > SOURCES_LIMIT:
            return value[:SOURCES_LIMIT]
        return value


class ReportCreate(BaseModel):
    """types.ts: ReportCreate - `POST /reports` tanasi.

    Kamida bittasi kerak: `chatId`, `turnId` yoki `messages`. Hammasi
    ixtiyoriy bo'lsa ham, "nima haqida" noma'lum shikoyat foydasiz.
    """

    chatId: str | None = Field(default=None, max_length=128)
    turnId: str | None = Field(default=None, max_length=64)
    reason: Literal["wrong", "incomplete", "outdated", "unsafe", "other"] | None = None
    comment: str | None = None
    messages: list[ReportMessage] | None = Field(default=None, max_length=MESSAGES_LIMIT)

    @field_validator("comment", mode="before")
    @classmethod
    def _trim_comment(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()[:COMMENT_LIMIT]
            return value or None
        return value

    @field_validator("chatId", "turnId", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _something_to_report(self) -> "ReportCreate":
        if not (self.chatId or self.turnId or self.messages):
            raise ValueError("chatId, turnId yoki messages kerak")
        return self


class ReportCreated(BaseModel):
    """types.ts: ReportCreated - 201 javobi."""

    id: str
    #: Har doim `new` - admin keyin o'zgartiradi.
    status: str
    createdAt: str

""""Pro" rejimi sxemalari - `apps/web/src/types.ts` dagi `ProQuota` va
`ProInfo` ning aynan nusxasi; `tests/test_contract.py` mosligini tekshiradi.

Maydon nomlari yuqoridagi xizmatnikidek (snake_case): javob
o'zgartirilmasdan o'tkaziladi, `ActionResult` va suhbat tarixi kabi.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProWindows(BaseModel):
    """Uchta suriladigan oyna: oxirgi 24 soat / 7 kun / 30 kun."""

    day: int = 0
    week: int = 0
    month: int = 0


class ProQuota(BaseModel):
    """types.ts: ProQuota - `GET /api/v1/pro/quota` javobi."""

    #: Shu oynada yana nechta "Pro" savol qolgan.
    remaining: ProWindows = Field(default_factory=ProWindows)
    #: Oynaning chegarasi. QOTIRILMAYDI - rolga qarab o'zgaradi.
    limits: ProWindows = Field(default_factory=ProWindows)
    #: Shu oynada sarflangani.
    used: ProWindows = Field(default_factory=ProWindows)

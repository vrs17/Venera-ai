""""Pro" rejimi sxemalari - `apps/web/src/types.ts` dagi `ProQuota` va
`ProInfo` ning aynan nusxasi; `tests/test_contract.py` mosligini tekshiradi.

Maydon nomlari yuqoridagi xizmatnikidek (snake_case): javob
o'zgartirilmasdan o'tkaziladi, `ActionResult` va suhbat tarixi kabi.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Yuqoridagi xizmatdan O'ZGARISHSIZ olinadigan maydonlar. `engine` va
#: `available` - Venera'niki, ular xizmat javobidan OLINMAYDI.
UPSTREAM_QUOTA_FIELDS = ("remaining", "limits", "used")


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
    #: So'rovchi uchun SHU KANALDA (`X-Venera-Client`) ishlaydigan dvigatel -
    #: admin qarori va `?engine=` tanlovi qo'llangandan keyin
    #: (`services/engine_control.py`): `v1` | `v2` | `""` (versiyasiz). "Pro" faqat `v2` da.
    engine: Literal["v1", "v2", "v3", "v4", ""] = ""
    #: "Pro" shu kanalda ishlatsa bo'ladimi: dvigatel `v2` VA byudjet
    #: yuqoridagi xizmatdan o'qildi. `false` bo'lsa klient "Pro" tugmasini
    #: ko'rsatmaydi (oynalar shunda nollar - ular haqiqiy byudjet emas).
    available: bool = False

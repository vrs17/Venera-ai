"""Yozuv amallari sxemalari - `apps/web/src/types.ts` dagi `ActionResult`
ning aynan nusxasi. Maydon nomlari yuqoridagi xizmatnikidek (snake_case):
javob o'zgartirilmasdan o'tkaziladi, ariza fayli maydonlari kabi.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ActionResult(BaseModel):
    """types.ts: ActionResult - tasdiqlash / bekor qilish / holat natijasi."""

    token: str
    #: executed | failed | cancelled | pending | expired
    status: str
    summary: str = ""
    operation: str | None = None
    connector: str | None = None
    #: Platforma o'zgarishni qabul qildi.
    ok: bool | None = None
    #: Nega bajarilmadi (bajarilmagan bo'lsa).
    error: str | None = None
    #: Audit kaliti.
    request_id: str | None = None
    #: Platforma qaytargan narsa, masalan {"key": "DVSIB-231"}.
    result: dict[str, Any] | None = None

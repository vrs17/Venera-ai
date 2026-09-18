"""Suhbatlar tarixi sxemalari - `apps/web/src/types.ts` dagi `ChatSummary`,
`ChatMessage`, `ChatDetail`, `ChatList`, `ChatDeleted` ning aynan nusxasi;
`tests/test_contract.py` mosligini tekshiradi.

Maydon nomlari yuqoridagi xizmatnikidek (snake_case): `ActionResult` kabi
javob o'zgartirilmasdan o'tkaziladi, bizning o'z maydonimiz yo'q. Vaqtlar
ISO-8601 UTC (`Z` bilan) - brauzer o'z vaqt zonasiga o'giradi.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class ChatSummary(BaseModel):
    """types.ts: ChatSummary - yon paneldagi bitta qator."""

    chat_id: str
    #: Yon paneldagi nom: modelning qisqa nomi, u nom bermaguncha birinchi
    #: xabarning boshi, yoki odam kiritgan matn.
    title: str
    #: auto (mashina bergan) | user (odam o'zgartirgan - model endi tegmaydi)
    title_source: str = "auto"
    #: Birinchi xabar. Eski (bu imkoniyatdan oldingi) suhbatlarda bo'lmasligi mumkin.
    created_at: str | None = None
    #: Oxirgi faollik - ro'yxat shu bo'yicha tartiblangan.
    updated_at: str | None = None
    #: Saqlangan xabarlar soni, ikkala tomon (odam + yordamchi).
    messages: int | None = None


class ChatMessage(BaseModel):
    """types.ts: ChatMessage"""

    #: user | assistant
    role: str
    #: Ko'rsatilgan matn. Yordamchi matni tekshiruv izohi ("Tekshirilgan ...")
    #: siz saqlanadi; `[1]`, `[T1]` iqtibos belgilari qoladi.
    content: str
    created_at: str | None = None


class ChatDetail(BaseModel):
    """types.ts: ChatDetail - ochilgan suhbat, xabarlari bilan."""

    chat_id: str
    title: str
    title_source: str = "auto"
    created_at: str | None = None
    updated_at: str | None = None
    #: Eskisi birinchi; oxirgi `limit` tasi.
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatList(BaseModel):
    """types.ts: ChatList"""

    #: Oxirgi faollik bo'yicha, yangisi birinchi; o'chirilganlar yo'q.
    items: list[ChatSummary] = Field(default_factory=list)
    limit: int
    offset: int


class ChatRename(BaseModel):
    """types.ts: `renameChat(id, title)` tanasi - {"title": "..."}.

    Chegara xizmatniki bilan bir xil (1-80 belgi, bo'shliqlar bittaga
    tushiriladi). Bu yerda ham tekshiriladi: bo'sh nom uchun ichki tarmoqqa
    borib 422 olib kelish ma'nosiz.
    """

    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def _collapse_whitespace(cls, value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            raise ValueError("suhbat nomi bo'sh")
        return value


class ChatDeleted(BaseModel):
    """types.ts: ChatDeleted - `DELETE /chats/{chat_id}` javobi."""

    chat_id: str
    #: "deleted". Yumshoq: ro'yxatdan chiqadi, lekin tiklash mumkin.
    status: str

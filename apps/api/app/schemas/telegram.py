"""Telegram bot: hisobni ulash sxemalari (mini app chaqiradi)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TelegramLinkRequest(BaseModel):
    """`Telegram.WebApp.initData` - Telegram imzolagan satr, o'zgartirilmasdan.

    KIMLIK BU YERDA EMAS: Venera hisobi `Authorization` sessiyasidan, Telegram
    hisobi esa shu satrning IMZOSIDAN olinadi. Klient `user_id` yubormaydi.
    """

    initData: str = Field(min_length=1, max_length=8192)


class TelegramLinkResult(BaseModel):
    linked: bool = True
    #: `new` | `refreshed` | `switched` (boshqa Venera hisobidan o'tkazildi).
    status: str
    #: Bot nomi (`@` siz) - ma'lum bo'lsa.
    bot: str | None = None
    #: Ulanish shuncha kun yashaydi (mini app ochilganda yangilanadi).
    days: int


class TelegramUnlinkResult(BaseModel):
    unlinked: bool

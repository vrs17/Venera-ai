"""Slack hisobini ulash sxemalari (`api/v1/slack.py`; veb tasdiq sahifasi chaqiradi)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SlackLinkRequest(BaseModel):
    """Chipta - Slack'dagi tugma havolasidagi `t`. KIMLIK BU YERDA EMAS: Barno hisobi `Authorization`
    sessiyasidan, Slack hisobi chiptaning serverdagi yozuvidan olinadi. Klient Slack id yubormaydi."""

    ticket: str = Field(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class SlackLinkInfo(BaseModel):
    #: Slack'dagi ism (ruxsat bo'lmasa `null`) - odam BEGONA havolani ochganini payqashi uchun.
    slackName: str | None = None
    #: Ulanadigan Barno hisobi - shu sessiya egasi.
    accountName: str
    accountLogin: str
    #: Chipta yana necha soniya yashaydi.
    expiresIn: int


class SlackLinkResult(BaseModel):
    linked: bool = True
    #: `new` | `refreshed` | `switched` (boshqa Barno hisobidan o'tkazildi).
    status: str
    slackName: str | None = None
    #: Ulanish oxirgi faollikdan shuncha kun yashaydi.
    days: int


class SlackUnlinkResult(BaseModel):
    unlinked: int

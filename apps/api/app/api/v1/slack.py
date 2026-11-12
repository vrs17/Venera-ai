"""Slack hisobini Barno hisobiga ulash - veb tomoni (`app/slack/link.py` ning ikkinchi yarmi).

Slack'dagi «Connect Barno AI account» tugmasi brauzerda `/link/slack?t=<chipta>` ni ochadi. Sahifa
(`apps/web/src/views/SlackLinkView.vue`) shu yo'llarni chaqiradi:

  GET  /slack/link/{ticket}  - KIM ulanayotgani (Slack'dagi ism, Barno hisobi). Chipta YONMAYDI.
  POST /slack/link           - odam "Ulash" ni bosdi: chipta yonadi, ulanish yoziladi, Slack'ga xabar.
  POST /slack/unlink         - shu hisobning hamma Slack ulanishlarini uzish.

Hammasi `current_user` ortida: Barno hisobi `Authorization` sessiyasidan (SSO yoki zahira - ega qarori:
kirish sahifasida ikkalasi ham bor), Slack hisobi esa CHIPTADAN - u Slack yetkazgan id'lar bilan Slack
ilovasining ichida yasalgan. Klient hech qanday Slack id yubormaydi.

Kirishning o'zi hech narsani ulamaydi: ulanish faqat `POST /slack/link` da, ya'ni odam tasdiq
sahifasidagi tugmani bosganda (`link.py` izohi - havolani birovga yuborish hujumi).
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Path, Request, status

from ...core.channels import channel_of
from ...core.config import settings
from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.slack import SlackLinkInfo, SlackLinkRequest, SlackLinkResult, SlackUnlinkResult
from ...services.analytics import record_auth_event
from ...slack import link as slack_link
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/slack", tags=["slack"])

#: Bitta umumiy xabar: chipta yo'q, eskirgan yoki ishlatilgan - farqi aytilmaydi.
_MSG_TICKET = "Ulash havolasi eskirgan yoki ishlatilgan - Slack'da Barno AI ga qayta yozing"
_MSG_OFF = "Slack hisobini ulash sozlanmagan"
_TICKET = Path(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


def _ready() -> None:
    if not slack_link.required():
        raise error_status(status.HTTP_501_NOT_IMPLEMENTED, _MSG_OFF)


@router.get("/link/{ticket}", response_model=SlackLinkInfo)
def link_info(ticket: str = _TICKET, user: AuthUser = Depends(current_user)) -> SlackLinkInfo:
    """Tasdiq sahifasi uchun: kim kimga ulanyapti. Chiptani yoqmaydi - sahifa qayta yuklansa ham ishlaydi."""
    _ready()
    found = slack_link.describe(ticket)
    if found is None:
        raise error_status(status.HTTP_404_NOT_FOUND, _MSG_TICKET)
    left = max(0, int(slack_link.TICKET_TTL - (time.time() - found.created)))
    return SlackLinkInfo(slackName=found.name or None, accountName=user.fullName, accountLogin=user.email,
                         expiresIn=left)


@router.post("/link", response_model=SlackLinkResult)
def link_account(body: SlackLinkRequest, request: Request,
                 user: AuthUser = Depends(current_user)) -> SlackLinkResult:
    """Ulash. Chipta bir martalik: ikkinchi so'rov 404."""
    _ready()
    done = slack_link.confirm(body.ticket, user)
    if done is None:
        raise error_status(status.HTTP_404_NOT_FOUND, _MSG_TICKET)
    ticket, result = done
    record_auth_event(user.email, True, method="slack", channel=channel_of(request), actor_id=user.actorId)
    slack_link.notify_linked(ticket, user)
    return SlackLinkResult(status=result, slackName=ticket.name or None,
                           days=int(getattr(settings, "slack_link_days", 30) or 30))


@router.post("/unlink", response_model=SlackUnlinkResult)
def unlink(user: AuthUser = Depends(current_user)) -> SlackUnlinkResult:
    """Shu Barno hisobiga ulangan HAMMA Slack hisoblarini uzadi (odamning o'z qarori)."""
    removed = slack_link.store().unlink_actor(user.actorId)
    if removed:
        log.info("Slack ulanishlari uzildi (actor %s): %d", user.actorId, removed)
    return SlackUnlinkResult(unlinked=removed)

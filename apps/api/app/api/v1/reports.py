"""Shikoyat ("Xabar berish") - chatdagi bayroqcha tugmasi.

    POST /reports    butun suhbat + ixtiyoriy sabab va izoh -> 201 {id, status, createdAt}

Odam suhbatni yoki bitta javobni belgilaydi; ikkala holda ham BUTUN suhbat
saqlanadi (`services/reports.py`: surat qayerdan olinadi va nega). Admin
uni `/admin/reports` da ko'radi.

KIMLIK SERVERDAN (`current_user`) - tanadagi hech narsa "kim" ni
belgilamaydi. Klient yuborgan `turnId` ham faqat O'SHA ODAMNIKI bo'lsa
ilinadi.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core.channels import channel_of
from ...schemas.auth import AuthUser
from ...schemas.reports import ReportCreate, ReportCreated
from ...services import reports as _reports
from ...services.analytics import bind
from ...services.tg_groups import is_group_agent_chat
from . import chat as _chat
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportCreated, status_code=status.HTTP_201_CREATED)
def create_report(
    body: ReportCreate,
    request: Request,
    user: AuthUser = Depends(current_user),
) -> ReportCreated:
    """Shikoyat yuborish. Soatiga 20 tagacha (429 + `Retry-After`).

    `async def` EMAS: surat uchun yuqoridagi xizmatga `urllib` bilan borilishi
    mumkin (bloklaydi) va ombor yozuvi ham sinxron.
    """
    channel = channel_of(request)

    def upstream(chat_id: str):
        # Odamning O'Z kaliti bilan - boshqa odamning suhbati 404 beradi.
        if is_group_agent_chat(chat_id):
            # Savol kaliti (`turnId`) orqali kelgan guruh CRM suhbati ham agentdan olinmaydi.
            raise LookupError("guruh CRM suhbati")
        return _chat._assistant.get_chat(chat_id, user_id=_chat.assistant_user_id(user),
                                         limit=_reports.SNAPSHOT_TURNS * 2)

    try:
        # Yuqoridagi xizmat chaqiruvi hisobda shu odam va kanalga yozilsin.
        with bind(user.actorId, channel):
            result = _reports.create(
                user,
                channel=channel,
                # Guruhdagi CRM suhbati (`tgcrm-`) shikoyat suratiga OLINMAYDI: ichida guruhdagi
                # boshqa odamlarning xabarlari bor, surat esa admin panelda ko'rinadi.
                chat_id=None if is_group_agent_chat(body.chatId) else body.chatId,
                turn_id=body.turnId,
                reason=body.reason,
                comment=body.comment,
                messages=[m.model_dump() for m in body.messages or []],
                upstream=upstream,
            )
    except _reports.ReportError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status, detail=str(exc), headers=headers) from exc
    return ReportCreated(**result)

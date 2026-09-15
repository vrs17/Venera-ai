"""Ulanishlar: foydalanuvchining O'Z HRM / CRM hisobi.

    GET    /connectors                     holat (ikkala platforma)
    POST   /connectors/{platform}/connect  login + parol -> ulanish
    PATCH  /connectors/{platform}          chatda ishlatish kaliti
    DELETE /connectors/{platform}          uzish (CRM da refresh_token bekor qilinadi)

Mantiq `services/integrations/connectors.py` da, bu yerda faqat HTTP.
TOKENLAR JAVOBGA TUSHMAYDI - klient faqat holatni ko'radi. Chat esa
`hub.tokens()` orqali o'sha odamning yaroqli tokenlarini oladi.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path

from ...core.config import settings
from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.connectors import (
    ConnectorStatus,
    ConnectorUpdate,
    ConnectorsResponse,
    ConnectRequest,
)
from ...services.integrations.connectors import (
    ConnectorError,
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
)
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/connectors", tags=["connectors"])

#: BITTA nusxa: CRM refresh_token ROTATSIYA qiladi va access_token keshi
#: xotirada - ikki nusxa bir-birining tokenini bekor qilardi. Chat shu
#: obyektdan tokenlarni oladi (`api/v1/chat.py`), health esa holatini.
hub = ConnectorHub(
    ConnectorStore(settings.connectors_file),
    HrmAuth(settings.hrm_base_url, timeout=settings.hrm_timeout),
    CrmUserAuth(
        settings.crm_idp_token_url,
        settings.crm_client_id,
        settings.crm_client_secret,
        settings.crm_base_url,
        timeout=settings.crm_timeout,
    ),
    hrm_margin=settings.hrm_token_margin,
    crm_margin=settings.crm_token_margin,
)

_PLATFORM = Path(max_length=16, description="hrm | crm")


def _uid(user: AuthUser) -> str:
    """Ombor kaliti. `actorId` - email o'zgarsa ham turadi."""
    return str(user.actorId)


def _fail(exc: ConnectorError, user: AuthUser, platform: str, what: str):
    # Xabar `connectors.py` da yasalgan va tokensiz - jurnalga tushishi mumkin.
    log.info("Ulanish %s (%s, %s): %s", what, user.email, platform, exc)
    return error_status(exc.status, str(exc))


@router.get("", response_model=ConnectorsResponse)
def list_connectors(user: AuthUser = Depends(current_user)) -> ConnectorsResponse:
    """Ikkala platformaning holati - "+" menyusi shuni ko'rsatadi."""
    return ConnectorsResponse(connectors=hub.status(_uid(user)))


@router.post("/{platform}/connect", response_model=ConnectorStatus)
def connect(
    body: ConnectRequest,
    platform: str = _PLATFORM,
    user: AuthUser = Depends(current_user),
) -> ConnectorStatus:
    """Platformaning O'Z logini va paroli bilan kirish.

    `async def` EMAS: platformaga `urllib` bilan boriladi (bloklaydi), FastAPI
    oddiy `def` ni threadpool'da bajaradi.
    """
    try:
        return ConnectorStatus(**hub.connect(_uid(user), platform, body.username, body.password))
    except ConnectorError as exc:
        raise _fail(exc, user, platform, "rad etildi") from exc


@router.patch("/{platform}", response_model=ConnectorStatus)
def update(
    body: ConnectorUpdate,
    platform: str = _PLATFORM,
    user: AuthUser = Depends(current_user),
) -> ConnectorStatus:
    """Kalit: ulangan tizimni chatda ishlatish / vaqtincha ishlatmaslik."""
    try:
        return ConnectorStatus(**hub.set_enabled(_uid(user), platform, body.enabled))
    except ConnectorError as exc:
        raise _fail(exc, user, platform, "kaliti") from exc


@router.delete("/{platform}", response_model=ConnectorStatus)
def disconnect(
    platform: str = _PLATFORM,
    user: AuthUser = Depends(current_user),
) -> ConnectorStatus:
    """Uzish: saqlangan token o'chiriladi, CRM da refresh_token bekor qilinadi."""
    try:
        return ConnectorStatus(**hub.disconnect(_uid(user), platform))
    except ConnectorError as exc:
        raise _fail(exc, user, platform, "uzish") from exc

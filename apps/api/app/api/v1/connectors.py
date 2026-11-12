"""Ulanishlar: odam O'ZI boshqaradigan hisob - faqat HRM (`USER_PLATFORMS`).

    GET    /connectors                     holat (faqat HRM qatori) - Mini App, mobil ilova
    POST   /connectors/{platform}/connect  410: qo'lda ulash yo'q (2026-11-12) - HRM ham
                                           BRB-Tech ID kirishida o'zi ulanadi (`api/v1/auth.py`)
    PATCH  /connectors/{platform}          eski klientlar uchun: hech narsani o'zgartirmaydi
    DELETE /connectors/{platform}          uzish (qayta ulash - BRB-Tech ID bilan qayta kirish)

CRM BU YERDA YO'Q (2026-11-12, ega qarori): u SSO kirishida o'zi ulanadi
(`api/v1/auth.py`) va har doim ishlatiladi - odam uni ko'rmaydi va boshqarmaydi.
`crm` uchala yo'lda ham notanish platforma bilan bir xil 404 oladi; CRM ni
ko'rish va uzish faqat admin panelda (`api/v1/admin_users.py`).

KALIT YO'Q: ulangan tizim har doim ishlatiladi. `PATCH` mobil ilova va eski
Mini App uchun qabul qilinadi, lekin `enabled` hech narsani hal qilmaydi.

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
)
from ...services.integrations.connectors import (
    MSG_SSO_ONLY,
    USER_PLATFORMS,
    ConnectorError,
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
)
from ...services.integrations.crm_sso import CrmSso, HrmSso, SsoSession
from ...services.oidc import from_settings as oidc_from_settings
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/connectors", tags=["connectors"])

#: BITTA nusxa: CRM refresh_token ROTATSIYA qiladi va access_token keshi
#: xotirada - ikki nusxa bir-birining tokenini bekor qilardi. Chat shu
#: obyektdan tokenlarni oladi (`api/v1/chat.py`), health esa holatini.
hub = ConnectorHub(
    ConnectorStore(settings.connectors_file),
    HrmAuth(settings.hrm_base_url, timeout=settings.hrm_timeout),
    # Faqat ESKI (qo'lda ulangan) CRM yozuvlarini yangilash va bekor qilish uchun.
    CrmUserAuth(
        settings.crm_idp_token_url,
        settings.crm_client_id,
        settings.crm_client_secret,
        settings.crm_base_url,
        timeout=settings.crm_timeout,
    ),
    hrm_margin=settings.hrm_token_margin,
    crm_margin=settings.crm_token_margin,
    # CRM va HRM ulanishi SSO sessiyasidan (`crm_sso.py`): sozlama chaqiruv
    # paytida o'qiladi, shuning uchun funksiyalar beriladi.
    sso=CrmSso(oidc_from_settings, lambda: settings.crm_base_url,
               timeout=min(settings.crm_timeout, 5.0)),
    session=SsoSession(oidc_from_settings),
    hrm_check=HrmSso(lambda: settings.hrm_base_url, timeout=min(settings.hrm_timeout, 5.0)),
)

_PLATFORM = Path(max_length=16, description="hrm")


def _uid(user: AuthUser) -> str:
    """Ombor kaliti. `actorId` - email o'zgarsa ham turadi."""
    return str(user.actorId)


def _fail(exc: ConnectorError, user: AuthUser, platform: str, what: str):
    # Xabar `connectors.py` da yasalgan va tokensiz - jurnalga tushishi mumkin.
    log.info("Ulanish %s (%s, %s): %s", what, user.email, platform, exc)
    return error_status(exc.status, str(exc))


@router.get("", response_model=ConnectorsResponse)
def list_connectors(user: AuthUser = Depends(current_user)) -> ConnectorsResponse:
    """Odam boshqaradigan platformalar holati (faqat HRM) - "+" menyusi shuni ko'rsatadi."""
    return ConnectorsResponse(connectors=hub.status(_uid(user), USER_PLATFORMS))


@router.post("/{platform}/connect", response_model=ConnectorStatus)
def connect(platform: str = _PLATFORM, user: AuthUser = Depends(current_user)) -> ConnectorStatus:
    """ESKI KLIENTLAR UCHUN: login + parol bilan HRM ga ulash 2026-11-12 da olib
    tashlandi (ega so'rovi) - HRM BRB-Tech ID kirishida o'zi ulanadi. Tana
    o'qilmaydi (parol serverga kelsa ham hech qayerga ketmaydi): `hrm` - 410 va
    nima qilish kerakligi, boshqa nom - 404 (`crm` ham)."""
    try:
        if platform not in USER_PLATFORMS:
            raise ConnectorError("Bunday platforma yo'q", status=404, code="UNKNOWN_PLATFORM")
        raise ConnectorError(MSG_SSO_ONLY, status=410, code="SSO_ONLY")
    except ConnectorError as exc:
        raise _fail(exc, user, platform, "qo'lda ulash so'raldi") from exc


@router.patch("/{platform}", response_model=ConnectorStatus)
def update(
    body: ConnectorUpdate,
    platform: str = _PLATFORM,
    user: AuthUser = Depends(current_user),
) -> ConnectorStatus:
    """ESKI KLIENTLAR UCHUN (mobil ilova, eski Mini App) - kalit endi yo'q.

    So'rov qabul qilinadi, lekin `enabled` hech narsani o'zgartirmaydi: ulangan
    HRM har doim ishlatiladi va javob haqiqiy holatni aytadi (`enabled: true`).
    Ulanmagan bo'lsa avvalgidek 409, `crm` - 404.
    """
    try:
        return ConnectorStatus(**hub.connected(_uid(user), platform))
    except ConnectorError as exc:
        raise _fail(exc, user, platform, "kaliti") from exc


@router.delete("/{platform}", response_model=ConnectorStatus)
def disconnect(
    platform: str = _PLATFORM,
    user: AuthUser = Depends(current_user),
) -> ConnectorStatus:
    """Uzish: HRM ulanishi o'chiriladi (SSO sessiyasini boshqa tizim ishlatmasa -
    u ham, Keycloak'da). `crm` - 404: odam CRM ni uzmaydi (uni admin panel uzadi)."""
    try:
        return ConnectorStatus(**hub.disconnect(_uid(user), platform, among=USER_PLATFORMS))
    except ConnectorError as exc:
        raise _fail(exc, user, platform, "uzish") from exc

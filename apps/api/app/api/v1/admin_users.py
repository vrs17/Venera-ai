"""Admin panel: foydalanuvchilar. FAQAT ADMIN (`require_roles("ADMIN")`).

    GET    /admin/users                              ro'yxat (q, role, status, channel, from, to)
    GET    /admin/users/{actorId}                    varaq: statistika, ulanishlar, Telegram, audit
    PATCH  /admin/users/{actorId}                    rollar / bloklash / izoh
    POST   /admin/users/{actorId}/signout            hamma sessiyalardan chiqarish
    DELETE /admin/users/{actorId}/connectors/{p}     HRM/CRM ulanishini uzish
    DELETE /admin/users/{actorId}/telegram           Telegram ulanishlarini uzish

Mantiq `services/admin_users.py` da (himoyalar, audit), bu yerda faqat HTTP.
Ulanishlar markazi va Telegram ombori - endpointlar va bot ishlatadigan AYNI
nusxalar (`connectors.hub`, `bot.links`): alohida nusxa CRM refresh_token
rotatsiyasini buzardi.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from ... import bot
from ...core.errors import error_status
from ...schemas.admin_users import (
    AdminConnector,
    AdminUser,
    AdminUserDetail,
    AdminUserList,
    AdminUserUpdate,
    SignoutResult,
    TelegramUnlinked,
)
from ...schemas.auth import AuthUser
from ...services import admin_users as _admin
from ...services.identities import IdentityStore
from ...services.users import UserStore
from . import connectors as _connectors
from ..deps import get_identity_store, get_user_store, require_roles

admin_only = require_roles("ADMIN")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_only)])

_ACTOR = Path(ge=0, le=2**53, description="Barno `actorId`")
_CHANNEL = "^(web|miniapp|bot|desktop|api)$"


def _fail(exc: _admin.AdminError):
    return error_status(exc.status, str(exc))


@router.get("/users", response_model=AdminUserList)
def list_users(
    q: str | None = Query(None, max_length=200, description="Ism, login, email, bo'lim"),
    role: str | None = Query(None, max_length=64),
    status: str | None = Query(None, pattern="^(active|blocked)$"),
    channel: str | None = Query(None, pattern=_CHANNEL),
    start: str | None = Query(None, alias="from", max_length=40),
    end: str | None = Query(None, alias="to", max_length=40),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> AdminUserList:
    """Katalog: SSO ∪ users.yaml ∪ savollar tarixidagi odamlar. Statistika
    (`turns`, `channels`, `reports`) - tanlangan oraliq bo'yicha."""
    try:
        since, until = _admin.parse_range(start, end)
        items = _admin.list_users(identities, users, q=q, role=role, status=status,
                                  channel=channel, since=since, until=until)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    return AdminUserList(items=items)


@router.get("/users/{actor_id}", response_model=AdminUserDetail)
def user_detail(
    actor_id: int = _ACTOR,
    start: str | None = Query(None, alias="from", max_length=40),
    end: str | None = Query(None, alias="to", max_length=40),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> AdminUserDetail:
    try:
        since, until = _admin.parse_range(start, end)
        item = _admin.user_detail(actor_id, identities, users, hub=_connectors.hub,
                                  links=bot.links, since=since, until=until)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    return AdminUserDetail(**item)


@router.patch("/users/{actor_id}", response_model=AdminUser)
def update_user(
    body: AdminUserUpdate,
    actor_id: int = _ACTOR,
    admin: AuthUser = Depends(admin_only),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> AdminUser:
    """Rollar (`null` - manbaga qaytarish), bloklash, izoh. Yuborilmagan
    maydon o'zgarmaydi. Himoyalar: o'zini pasaytirish/bloklash, oxirgi admin,
    `admin_logins` - 409."""
    sent = body.model_fields_set
    changes: dict = {}
    if "roles" in sent:
        changes["roles"] = body.roles
    if "disabled" in sent and body.disabled is not None:
        changes["disabled"] = body.disabled
    if "note" in sent:
        changes["note"] = body.note
    try:
        item = _admin.update_user(admin, actor_id, identities, users, hub=_connectors.hub,
                                  **changes)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    return AdminUser(**item)


@router.post("/users/{actor_id}/signout", response_model=SignoutResult)
def signout(
    actor_id: int = _ACTOR,
    admin: AuthUser = Depends(admin_only),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> SignoutResult:
    """Hamma sessiyalar tugaydi: veb/mini app tokenlari 401, Telegram bot va
    Slack ulanishlari uziladi. Odam qaytadan kira oladi (bloklash emas)."""
    from ...slack import link as slack_link

    try:
        version = _admin.signout(admin, actor_id, identities, users, links=bot.links,
                                 hub=_connectors.hub, slack=slack_link.store())
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    return SignoutResult(tokenVersion=version)


@router.delete("/users/{actor_id}/connectors/{platform}", response_model=AdminConnector)
def disconnect_connector(
    actor_id: int = _ACTOR,
    platform: str = Path(max_length=16, description="hrm | crm"),
    admin: AuthUser = Depends(admin_only),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> AdminConnector:
    """Odamning HRM/CRM ulanishini uzish - "+" menyusidagi AYNI amal (CRM da
    refresh_token bekor qilinadi)."""
    try:
        item = _admin.disconnect_connector(admin, actor_id, platform, identities, users,
                                           hub=_connectors.hub)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    return AdminConnector(**item)


@router.delete("/users/{actor_id}/telegram", response_model=TelegramUnlinked)
def unlink_telegram(
    actor_id: int = _ACTOR,
    admin: AuthUser = Depends(admin_only),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> TelegramUnlinked:
    """Hamma Telegram ulanishlari uziladi - bot odamni tanimay qo'yadi."""
    try:
        removed = _admin.unlink_telegram(admin, actor_id, identities, users, links=bot.links)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    return TelegramUnlinked(unlinked=removed)

"""Admin panel: yordamchi dvigatellari (versiyalari). FAQAT ADMIN.

    GET    /admin/engines                     katalog, siyosat, .env, hozirgi holat,
                                              7 kunlik statistika, kimga nima berilgan
    PUT    /admin/engines/policy              "hamma uchun" versiya (umumiy va kanal bo'yicha)
    PUT    /admin/engines/access/{actorId}    odamga versiyalar (sinovchilar)
    DELETE /admin/engines/access/{actorId}    odamni umumiy siyosatga qaytarish

NEGA ADMIN PANELDA. Ilgari versiya faqat `.env` da edi: uni almashtirish
serverga kirish va restart talab qilardi (restart esa oqib turgan
javoblarni kesadi), kim, qachon almashtirgani esa hech qayerda qolmasdi.
Endi qaror ombordan o'qiladi, darhol kuchga kiradi va auditga yoziladi.

Mantiq `services/engine_control.py` da (tanlov tartibi, kesh, audit), bu
yerda faqat HTTP. Huquq router darajasida (`admin.py` dagi sabab bilan).
`async def` EMAS: SQLite bloklaydi.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Path

from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.engines import (
    AdminEngines,
    EngineAccessRemoved,
    EngineAccessRow,
    EngineAccessUpdate,
    EnginePolicyUpdate,
)
from ...services import admin_users as _admin
from ...services import engine_control as _control
from ...services.identities import IdentityStore
from ...services.users import UserStore
from ..deps import get_identity_store, get_user_store, require_roles

admin_only = require_roles("ADMIN")

router = APIRouter(prefix="/admin/engines", tags=["admin"], dependencies=[Depends(admin_only)])

_ACTOR = Path(ge=0, le=2**53, description="Barno `actorId`")


def _fail(exc: _admin.AdminError):
    return error_status(exc.status, str(exc))


def _unavailable(exc: BaseException):
    # 503, 500 emas: ombor band yoki disk to'la - vaqtinchalik holat
    # (`admin._checked` bilan bir xil xabar).
    return error_status(503, "Analitika ombori hozir javob bermadi, qayta urinib ko'ring")


@router.get("", response_model=AdminEngines)
def get_engines(
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> AdminEngines:
    """Dvigatellar sahifasi: nima tanlash mumkin, hozir nima ishlaydi va
    nega (siyosat yoki `.env`), versiyalar qanday ishlayapti (7 kun) va
    kimga alohida versiya berilgan."""
    try:
        return AdminEngines(**_control.admin_view(identities, users))
    except (sqlite3.Error, OSError) as exc:
        raise _unavailable(exc) from exc


@router.put("/policy", response_model=AdminEngines)
def put_policy(
    body: EnginePolicyUpdate,
    admin: AuthUser = Depends(admin_only),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> AdminEngines:
    """"Hamma uchun" versiya. QO'SHILADIGAN o'zgarish: yuborilmagan maydon
    va kanal o'zgarmaydi, `null` - kalitni olib tashlaydi (keyingi bo'g'in,
    oxiri `.env`). Noma'lum dvigatel yoki kanal - 422. Javob - yangi holat."""
    sent = body.model_fields_set
    changes: dict = {}
    if "default" in sent:
        changes["default"] = body.default
    try:
        view = _control.put_policy(admin, identities, users, channels=body.channels, **changes)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    except (sqlite3.Error, OSError) as exc:
        raise _unavailable(exc) from exc
    return AdminEngines(**view)


@router.put("/access/{actor_id}", response_model=EngineAccessRow)
def put_access(
    body: EngineAccessUpdate,
    actor_id: int = _ACTOR,
    admin: AuthUser = Depends(admin_only),
    identities: IdentityStore = Depends(get_identity_store),
    users: UserStore = Depends(get_user_store),
) -> EngineAccessRow:
    """Odamga versiyalar: u shulardan tanlay oladi (`/chat/engines`),
    `defaultEngine` (yoki yagona versiya) esa tanlamasa ishlaydi. Odam
    `/admin/users` katalogida bo'lmasa - 404. `note` yuborilmasa eskisi qoladi."""
    changes: dict = {}
    if "note" in body.model_fields_set:
        changes["note"] = body.note
    try:
        row = _control.set_access(admin, actor_id, identities, users, engines=body.engines,
                                  default_engine=body.defaultEngine, **changes)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    except (sqlite3.Error, OSError) as exc:
        raise _unavailable(exc) from exc
    return EngineAccessRow(**row)


@router.delete("/access/{actor_id}", response_model=EngineAccessRemoved)
def delete_access(
    actor_id: int = _ACTOR,
    admin: AuthUser = Depends(admin_only),
) -> EngineAccessRemoved:
    """Odam umumiy siyosatga qaytadi. Qator yo'q bo'lsa `removed: false`
    (xato emas - ikki marta bosish zararsiz)."""
    try:
        removed = _control.remove_access(admin, actor_id)
    except _admin.AdminError as exc:
        raise _fail(exc) from exc
    return EngineAccessRemoved(removed=removed)

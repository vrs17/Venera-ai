"""Barno konnektorining umumiy qismi: bosh kalit, ochiq manzil, qamrovlar, token -> odam.

OAuth eshigi (`connector/oauth.py`), MCP (`connector/mcp.py`) va sayt rozilik API si
(`api/v1/connector.py`) shu fayldan oladi - qoida bir joyda (`docs/barno-connector.md`).
"""

from __future__ import annotations

from ..core import config as _config
from ..core.config import settings
from ..schemas.auth import AuthUser
from .store import ConnectorStore, GrantRow

#: QAMROVLAR - modul bo'yicha. 1-bosqich: faqat Plaud, faqat o'qish (egasining qarori,
#: 2026-11-25). Kalit - rozilik sahifasidagi tarjima kaliti ham (`connector.scopes.<kalit>`).
SCOPES: dict[str, str] = {
    "plaud.read": "Read your Plaud meetings: list, summaries, transcripts, action items",
}

#: Mijoz `scope` bermasa - shu (Claude va ChatGPT ko'pincha metadata dagi ro'yxatni so'raydi).
DEFAULT_SCOPES: frozenset[str] = frozenset({"plaud.read"})

_store: ConnectorStore | None = None


def store() -> ConnectorStore:
    """Jarayon bo'yicha bitta ombor. Testlar `reset_for_tests` bilan vaqtinchalik faylga."""
    global _store
    if _store is None:
        _store = ConnectorStore(settings.connector_dir / "connector.db")
    return _store


def reset_for_tests(path, *, clock=None) -> ConnectorStore:
    global _store
    _store = ConnectorStore(path, **({"clock": clock} if clock else {}))
    return _store


def enabled() -> bool:
    """Bosh kalit (`MCP_CONNECTOR_ENABLED`) - `.env` dan jonli."""
    return _config.mcp_connector_enabled_now()


def public_base() -> str:
    """`https://llm.brb-tech.uz` - oxirida `/` siz. Bo'sh bo'lsa konnektor ishlamaydi:
    `resource` va metadata so'rov Host'iga bog'lanib qolmasin (proksi uni o'zgartirishi mumkin)."""
    base = (settings.mcp_public_url or settings.sso_app_url or "").strip().rstrip("/")
    return base


def mcp_resource() -> str:
    """MCP serverining kanonik manzili - tokenning `resource` i (RFC 8707) shu bilan solishtiriladi."""
    return f"{public_base()}/mcp"


def resolve_access_token(raw: str) -> GrantRow | None:
    """`Authorization: Bearer <raw>` -> jonli ruxsat yoki `None`.

    `None` - token yo'q / muddati o'tgan / bekor qilingan YOKI boshqa manzil uchun berilgan
    (`resource` mos emas): hammasi bir xil 401 (MCP avtorizatsiyasi, audience tekshiruvi)."""
    raw = (raw or "").strip()
    if not raw or len(raw) > 512:
        return None
    grant = store().access(raw)
    if grant is None or grant.resource != mcp_resource():
        return None
    return grant


def user_for_grant(grant: GrantRow) -> AuthUser | None:
    """Ruxsat -> odam, sayt tokenidagi qoida bilan (`deps.user_for_subject`). `None` -
    hisob o'chirilgan, bloklangan yoki "hamma joydan chiqarish" bosilgan: ruxsat ham BEKOR
    qilinadi - keyingi safar tekshirib o'tirmaslik va "Ulangan ilovalar" da qolmasligi uchun."""
    from fastapi import HTTPException

    from ..api.deps import get_identity_store, get_user_store, user_for_subject

    from ..main import app

    # Saytdagi `Depends` bilan AYNI ombor (testlar va kelajakdagi almashtirish shu orqali).
    users = app.dependency_overrides.get(get_user_store, get_user_store)()
    identities = app.dependency_overrides.get(get_identity_store, get_identity_store)()
    try:
        user = user_for_subject(grant.subject, grant.token_version, users, identities)
    except HTTPException:
        store().revoke_grant(grant.actor_id, grant.id)
        return None
    if user.actorId != grant.actor_id:
        # Kimlik boshqa odamga bog'lanib qolgan (qo'lda tahrir, birlashtirish) - xavfsiz tomon.
        store().revoke_grant(grant.actor_id, grant.id)
        return None
    return user


def record_call(grant: GrantRow, tool: str, status: str, ms: int, out_bytes: int) -> None:
    """Murojaat jurnali - MATN YOZILMAYDI, faqat kim/qaysi ilova/vosita/holat/vaqt/hajm."""
    store().record_call(grant, tool, status, ms, out_bytes)

"""Barno konnektori - sayt tomoni: rozilik sahifasi (`/connect`) va "Ulangan ilovalar".

    GET    /api/v1/connector/requests/{id}           kutilayotgan so'rov: qaysi ilova, qaysi qamrov
    POST   /api/v1/connector/requests/{id}/approve   ruxsat -> mijozga qaytish manzili (kod bilan)
    POST   /api/v1/connector/requests/{id}/deny      rad -> mijozga `access_denied`
    GET    /api/v1/connector/apps                    odamning jonli ruxsatlari va bosh kalit holati
    DELETE /api/v1/connector/apps/{grant_id}         ruxsatni uzish (faqat O'ZINIKI)

NEGA SAYT ORQALI. Odam allaqachon saytga kirgan (BRB-Tech ID yoki zahira kirish) - shu
kirish ishlatiladi, konnektor uchun alohida parol yoki cookie yo'q. Rozilik POST i odamning
Barno tokeni bilan (`Authorization`), cookie bilan emas - begona sahifa uni odam nomidan
yubora olmaydi (CSRF yo'q). Kod qaytadigan manzil so'rovda allaqachon tekshirilgan
(`connector/oauth.py: redirect_matches`) - bu yerda faqat o'sha manzil ishlatiladi.

Bosh kalit o'chiq bo'lsa hammasi 404 `connector_disabled` - sahifa "o'chirilgan" deydi.
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...connector import core
from ...connector import oauth as connector_oauth
from ...core.security import verify_claims
from ...schemas.auth import AuthUser
from ..deps import bearer_token, current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/connector", tags=["connector"])


class ScopeView(BaseModel):
    id: str


class RequestView(BaseModel):
    id: str
    #: Manzildan chiqarilgan nom (`Claude` / `ChatGPT` / `Claude Code`) - mijoz aytgani emas.
    client: str
    #: Kod qaytadigan host - sahifada ko'rinadi (`claude.ai`).
    host: str
    scopes: list[ScopeView]
    expiresAt: str


class ApproveRequest(BaseModel):
    #: Odam belgilagan qamrovlar - so'ralganlarning ICHIDAN. Bo'sh - rad bilan bir xil emas,
    #: 400 (hech bo'lmasa bitta modul kerak).
    scopes: list[str] = Field(default_factory=list, max_length=20)


class RedirectView(BaseModel):
    redirect: str


class AppView(BaseModel):
    id: str
    client: str
    scopes: list[str]
    createdAt: str
    lastUsedAt: str | None = None


class AppsView(BaseModel):
    #: Bosh kalit holati - sahifa o'chiq paytda "manzilni qo'shing" demasin.
    enabled: bool
    apps: list[AppView]


class Revoked(BaseModel):
    revoked: bool


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _gate() -> None:
    if not core.enabled() or not core.public_base():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="connector_disabled")


def _pending(request_id: str):
    pending = core.store().request(request_id) if request_id and len(request_id) <= 128 else None
    if pending is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="request_not_found")
    return pending


@router.get("/requests/{request_id}", response_model=RequestView)
def get_request(request_id: str, user: AuthUser = Depends(current_user)) -> RequestView:
    _gate()
    pending = _pending(request_id)
    return RequestView(
        id=pending.id,
        client=connector_oauth.client_label(pending.redirect_uri),
        host=urllib.parse.urlsplit(pending.redirect_uri).hostname or "",
        scopes=[ScopeView(id=s) for s in sorted(pending.scopes)],
        expiresAt=_iso(pending.expires_at) or "",
    )


@router.post("/requests/{request_id}/approve", response_model=RedirectView)
def approve(request_id: str, body: ApproveRequest, user: AuthUser = Depends(current_user),
            token: str = Depends(bearer_token)) -> RedirectView:
    _gate()
    pending = _pending(request_id)
    chosen = frozenset(body.scopes) & pending.scopes
    if not chosen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no_scope")
    claims = verify_claims(token)
    if claims is None:  # `current_user` o'tkazgan - bu faqat poyga holati
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token yaroqsiz")
    label = connector_oauth.client_label(pending.redirect_uri)
    try:
        code = core.store().approve(pending, subject=claims.subject, actor_id=user.actorId,
                                    token_version=claims.version, client_name=label, scopes=chosen)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="request_not_found") from None
    log.info("Konnektor: rozilik - actor %s, %s, %s", user.actorId, label, " ".join(sorted(chosen)))
    return RedirectView(redirect=connector_oauth.approved_redirect(pending.redirect_uri, code,
                                                                   pending.state))


@router.post("/requests/{request_id}/deny", response_model=RedirectView)
def deny(request_id: str, user: AuthUser = Depends(current_user)) -> RedirectView:
    _gate()
    pending = _pending(request_id)
    core.store().drop_request(pending.id)
    return RedirectView(redirect=connector_oauth.denied_redirect(pending.redirect_uri, pending.state))


@router.get("/apps", response_model=AppsView)
def list_apps(user: AuthUser = Depends(current_user)) -> AppsView:
    """"Ulangan ilovalar" - bosh kalit o'chiq bo'lsa ham ko'rinadi: odam eski ruxsatini
    baribir uza olsin (`enabled` - sahifa nima deyishini biladi)."""
    return AppsView(
        enabled=core.enabled() and bool(core.public_base()),
        apps=[AppView(id=g.id, client=g.client_name, scopes=sorted(g.scopes),
                      createdAt=_iso(g.created_at) or "", lastUsedAt=_iso(g.last_used_at))
              for g in core.store().grants_of(user.actorId)])


@router.delete("/apps/{grant_id}", response_model=Revoked)
def revoke_app(grant_id: str, user: AuthUser = Depends(current_user)) -> Revoked:
    done = core.store().revoke_grant(user.actorId, grant_id[:128])
    if not done:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="app_not_found")
    log.info("Konnektor: uzildi - actor %s", user.actorId)
    return Revoked(revoked=True)

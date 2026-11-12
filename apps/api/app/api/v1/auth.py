"""Autentifikatsiya endpointlari.

KIRISH IKKI YO'L BILAN:

  1. SSO - Keycloak, BRAUZER orqali (`services/oidc.py`):
       GET  /auth/sso/config    - frontend: SSO yoqilganmi, parol shakli bormi
       GET  /auth/sso/start     - odamni Keycloak kirish sahifasiga yuboradi
       GET  /auth/sso/callback  - Keycloak'dan qaytish: tokenlar tekshiriladi,
                                  shaxs `identities.json` ga yoziladi (`actor_id`
                                  BIR MARTA tanlanadi, `services/identities.py`),
                                  Barno sessiyasi (JWT) yasaladi va frontend'ga
                                  BIR MARTALIK kod bilan qaytariladi
       POST /auth/sso/exchange  - o'sha kod -> `LoginResponse` (token)
     Parol Barno'ga HECH QACHON kelmaydi. Rollar - Keycloak'dagi bizning
     client'ning rollari (`admin` -> ADMIN).

  2. Zahira - `config/users.yaml` (`POST /auth/login`, `local_login_enabled`):
     administrator Keycloak'siz ham kira olsin (Keycloak yiqilganda,
     birinchi sozlashda). Prod'da o'chirish mumkin - shunda bu endpoint 403
     va kirish sahifasida faqat SSO tugmasi qoladi.

OLDINGI YO'L - login+parolni Keycloak'ga ilovaning o'zi yuborishi (parol
granti) va o'sha parol bilan HRM ga kirish - OLIB TASHLANDI (2026-11): SSO
ning ma'nosi ilova parolni ko'rmasligi. CRM va HRM ulanishi SSO sessiyasining
o'zidan ochiladi (`_connect_sso`) - har tizim tokenni qabul qilsagina. HRM rad
etsa odam uni "+" menyusida qo'lda ulaydi (`api/v1/connectors.py`, zahira).

Frontend (`apps/web/src/api/auth.api.ts`). `signup` va `change-password`
ATAYLAB 501: hisob va parol Keycloak'da.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import logging
import re
import secrets
import urllib.parse

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from ...core.channels import channel_of
from ...core.config import settings
from ...core.errors import error_status, unauthorized
from ...core.security import create_token, verify_claims
from ...schemas.auth import (
    AuthUser,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SsoConfig,
    SsoExchangeRequest,
)
from ...services import admin_users
from ...services.analytics import record_auth_event
from ...services.identities import IdentityStore
from ...services.oidc import HANDOFF, HANDOFF_TTL, ID_TOKENS, PENDING_TTL, KeycloakOidc, OidcError, Tokens, s256
from ...services.oidc import from_settings as oidc_from_settings
from ...services.users import UserStore
from . import connectors as _connectors
from ..deps import current_user, get_identity_store, get_user_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

#: Xabar ATAYLAB UMUMIY: qaysi biri xato ekanini aytsak, qaysi loginlar
#: borligini aniqlash mumkin bo'lardi.
_MSG_BAD_LOGIN = "Login yoki parol noto'g'ri"
#: Admin panelda bloklangan hisob (`services/admin_users.py`). Parol to'g'ri
#: bo'lgandagina aytiladi.
_MSG_BLOCKED = "Hisob bloklangan. Administratorga murojaat qiling."
_MSG_LOCAL_OFF = "Parol bilan kirish o'chirilgan - SSO orqali kiring"
_MSG_HANDOFF = "Kirish kodi eskirgan yoki ishlatilgan - qaytadan kiring"
#: Mobil ilovaning PKCE challenge'i (S256): base64url, 43 belgi.
_APP_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")

START_PATH = "/api/v1/auth/sso/start"
CALLBACK_PATH = "/api/v1/auth/sso/callback"
_CHANNELS = frozenset({"web", "miniapp", "desktop", "mobile"})
#: Frontend ko'rsatadigan sabab kodlari (`shell.auth.sso.*`); qolgani `failed`.
_PUBLIC_REASONS = frozenset({"denied", "blocked", "expired", "network", "config"})
#: `OidcError.code` -> frontend sababi. Keycloak `invalid_grant` = kod eskirgan
#: yoki ikki marta ishlatilgan (odam "orqaga" bosdi); `invalid_client` = bizning
#: sir noto'g'ri - administrator tuzatadi.
_REASON_MAP = {
    "invalid_grant": "expired", "invalid_client": "config", "unauthorized_client": "config",
    # Kirish boshqa brauzerda boshlangan (`_BIND_COOKIE`) - odam qaytadan boshlaydi.
    "binding": "expired",
    # Keycloak `offline_access` ni bermadi: client'ning "Optional client scopes"
    # ro'yxatida yo'q yoki odamda `offline_access` realm roli yo'q - bu SOZLAMA
    # (`SSO_CRM_CONNECT`, docs/auth-sso.md), odam hech narsa qila olmaydi.
    "invalid_scope": "config", "not_allowed": "config",
}

#: Kirishni BOSHLAGAN brauzerga bog'laydigan cookie. `state` va bir martalik
#: kod faqat URL'da yuradi - ularni boshqa odamga yuborib bo'ladi: hujumchi o'z
#: kirishini oxirgi qadamda to'xtatib, havolani hamkasbiga bersa, hamkasbi
#: HUJUMCHINING hisobiga kirib qolardi (login CSRF) va o'z savollari, audio
#: yozuvlari, "+" menyusida kiritgan HRM/CRM paroli o'sha hisobga tushardi.
#: Cookie `start` da qo'yiladi, uning SHA-256 i `Pending` va `HANDOFF` da
#: turadi; `callback` va `exchange` cookie mos kelmasa rad etadi. HttpOnly
#: (JS o'qimaydi), SameSite=Lax (Keycloak'dan qaytishda - yuqori darajali GET -
#: yuboriladi).
#:
#: HTTPS da nomi `__Host-` bilan: bunday cookie'ni brauzer faqat AYNAN shu
#: host qo'ygan bo'lsa qabul qiladi (Secure, Path=/, Domain'siz) - qo'shni
#: `*.brb-tech.uz` saytidan (yoki undagi XSS dan) hujumchi o'z qiymatini
#: "tashlab" qo'ya olmaydi. `http` (dev) da prefiks ishlamaydi - oddiy nom va
#: tor yo'l.
_BIND_COOKIE = "barno_sso"
_BIND_PATH = "/api/v1/auth/sso"
_BIND_COOKIE_HOST = "__Host-barno_sso"
#: Cookie `start` dan `exchange` gacha yashashi kerak: kutish (`PENDING_TTL`) va
#: undan keyin bir martalik kod muddati (`HANDOFF_TTL`).
_BIND_MAX_AGE = int(PENDING_TTL + HANDOFF_TTL)
#: Boshqa hostda boshlangan kirishni asosiy manzilga bir marta ko'chirish belgisi.
_CANONICAL_MARK = "_c"


def _bind_cookie(app: str) -> tuple[str, str, bool]:
    """(nom, yo'l, secure) - ilovaning TASHQI manzilidan: prod'da TLS chekkada
    tugaydi, API o'zi `http` ni ko'radi."""
    if app.startswith("https://"):
        return _BIND_COOKIE_HOST, "/", True
    return _BIND_COOKIE, _BIND_PATH, False


def _sso_session(request: Request) -> bool:
    """So'rov tokeni brauzer SSO kirishidan olinganmi. Tokenni `current_user`
    allaqachon tekshirgan - bu yerda faqat belgisi o'qiladi."""
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    claims = verify_claims(token.strip()) if scheme.lower() == "bearer" else None
    return bool(claims and claims.sso)


def _binding(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest() if value else ""


def _bound(request: Request, expected: str) -> bool:
    """So'rov kirishni boshlagan brauzerdanmi. `expected` bo'sh - bog'lanmagan
    kirish (mobil qaytish, testlar) - tekshirilmaydi."""
    if not expected:
        return True
    name = _bind_cookie(_app_url(request))[0]
    return hmac.compare_digest(expected, _binding(request.cookies.get(name)))


def _other_host(request: Request, app: str) -> bool:
    """So'rov ilovaning asosiy manzilidan BOSHQA hostga kelganmi (masalan sayt
    domen o'rniga server IP si bilan ochilgan). Faqat host nomi solishtiriladi:
    API portni va sxemani ko'rmaydi (nginx `$host` ni portsiz uzatadi)."""
    wanted = (urllib.parse.urlsplit(app).hostname or "").lower()
    raw = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    got = (urllib.parse.urlsplit(f"//{raw.split(',')[0].strip()}").hostname or "").lower()
    return bool(wanted and got and wanted != got)


def _oidc() -> KeycloakOidc:
    """Chaqiruv paytida sozlamadan: testlar `settings.sso_*` ni almashtiradi."""
    return oidc_from_settings()


def _connect_sso(oidc: KeycloakOidc, actor_id: int, username: str, tokens: Tokens) -> None:
    """Kirgan odamning SSO sessiyasini uning CRM va HRM ulanishiga aylantiradi
    (`sso_crm_connect`, `sso_hrm_connect`, `services/integrations/crm_sso.py`).

    HECH QACHON kirishni to'xtatmaydi: har qanday xato jurnalga yoziladi,
    odam baribir kiradi.

    Qoida: sessiya faqat tizim uni QABUL QILGANDA o'sha tizimning ulanishiga
    aylanadi (eski ulanish almashtiriladi). Tizim rad etsa yoki javob bermasa
    odamning mavjud ulanishiga TEGILMAYDI - ishlab turgan (masalan qo'lda
    ulangan HRM) ulanishni tekshirilmagan sessiya bilan almashtirmaymiz.
    Keyingi kirishda yana sinaladi. Ikkala tekshiruv PARALLEL: har biri 5 s
    gacha kutadi, kirish 10 s kutib qolmasin.

    CRM HAR DOIM YOQIQ (2026-11-12, ega qarori): kalit yo'q, odam CRM ni
    ko'rmaydi ham. Yangi yozuv `enabled: true` bilan saqlanadi.
    """
    hub = _connectors.hub
    checks: dict[str, Any] = {}
    if settings.sso_crm_connect and hub.sso is not None and hub.sso.configured:
        checks["crm"] = lambda: (hub.sso.accepts(tokens.access_token), "")
    hrm = hub.hrm_check
    if settings.sso_hrm_connect and hrm is not None and hrm.configured:
        checks["hrm"] = lambda: hrm.check(tokens.access_token)
    if not checks:
        return
    try:
        if not tokens.refresh_token:
            log.info("SSO: Keycloak refresh_token bermadi - CRM/HRM ulanishi ochilmadi (%s)", username)
            return
        with ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="sso-check") as pool:
            futures = {name: pool.submit(run) for name, run in checks.items()}
            results = {name: future.result() for name, future in futures.items()}
        accepted = tuple(name for name in ("crm", "hrm") if results.get(name, (None, ""))[0] is True)
        for name, (verdict, reason) in results.items():
            if verdict is True:
                continue
            # Sabab odatda tokenning KIMGA berilganida (`aud`, `azp`). Nomlar sir emas.
            seen = oidc.describe(tokens.access_token)
            log.warning(
                "SSO: %s sessiyani %s (%s)%s - %s ulanishi ochilmadi. Token: azp=%s aud=%s clientlar=%s",
                name.upper(), "RAD ETDI" if verdict is False else "tekshira olmadi", username,
                f" [{reason}]" if reason else "", name.upper(),
                seen.get("azp") or "?", seen.get("aud") or [], seen.get("clients") or [],
            )
        if accepted:
            hub.adopt_sso(str(actor_id), username, tokens.access_token, tokens.refresh_token,
                          tokens.expires_in, accepted, revoke_old=True)
    except Exception:  # noqa: BLE001 - CRM/HRM kirishga to'siq bo'lmasin
        log.exception("SSO: CRM/HRM ulanishini ochishda xato (%s) - kirish davom etadi", username)


def _app_url(request: Request) -> str:
    """Ilovaning tashqi manzili (`sso_app_url` izohi, `core/config.py`)."""
    base = (settings.sso_app_url or "").strip().rstrip("/")
    if base:
        return base
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _safe_return(raw: str | None) -> str:
    """Kirishdan keyin qaytiladigan manzil: FAQAT ilova ichidagi yo'l (`/...`)
    yoki sozlangan mobil manzil. `//host` ochiq yo'naltirish bo'lardi."""
    value = (raw or "").strip()
    if value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    mobile = (settings.sso_mobile_redirect or "").strip()
    if mobile and value == mobile:
        return value
    return "/"


def _is_mobile(return_to: str) -> bool:
    mobile = (settings.sso_mobile_redirect or "").strip()
    return bool(mobile) and return_to == mobile


def _channel(request: Request, raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in _CHANNELS:
        return value
    found = channel_of(request)
    return found if found in _CHANNELS else "web"


def _with_query(url: str, params: dict[str, str]) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urllib.parse.urlencode(params)}"


def _done_url(app: str, return_to: str, handoff: str) -> str:
    """Kirish tugadi: frontend `?sso=<kod>` ni ko'rib `exchange` ni chaqiradi."""
    if _is_mobile(return_to):
        return _with_query(return_to, {"sso": handoff})
    params = {"sso": handoff}
    if return_to != "/":
        params["redirect"] = return_to
    return _with_query(f"{app}/login", params)


def _fail_url(app: str, return_to: str, reason: str) -> str:
    reason = _REASON_MAP.get(reason, reason)
    code = reason if reason in _PUBLIC_REASONS else "failed"
    target = return_to if _is_mobile(return_to) else f"{app}/login"
    return _with_query(target, {"sso_error": code})


def _finish(return_to: str, url: str) -> Response:
    """Callback natijasi: veb - 303 yo'naltirish; MOBIL ilova - kichik sahifa.

    Android Chrome ilovani (`venera-rec://`) foydalanuvchi bosmagan avtomatik yo'naltirishdan
    ochishni rad etishi mumkin - masalan Keycloak sessiyasi tirik va kirish birorta bosishsiz
    o'tganda: odam bo'sh sahifada qolardi. Sahifa ilovani darhol ochishga urinadi va
    «Barno AI ilovasini ochish» tugmasini qoldiradi (bosish - foydalanuvchi harakati).
    Koddan qo'rqish shart emas: u bir martalik va faqat PKCE verifier bilan almashadi."""
    if not _is_mobile(return_to):
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    nonce = secrets.token_urlsafe(16)
    href = html.escape(url, quote=True)
    page = f"""<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Barno AI</title></head>
<body style="margin:0;font-family:system-ui,sans-serif;background:#fff;color:#1d1d1f">
<main style="max-width:420px;margin:0 auto;padding:48px 24px;text-align:center">
<p style="font-size:17px;line-height:1.5;margin:0 0 24px">Barno AI ilovasiga qayting.<br>
<span style="color:#6e6e73;font-size:14px">Return to the Barno AI app.</span></p>
<a id="go" href="{href}" style="display:inline-block;padding:14px 24px;border-radius:14px;background:#EE5A24;color:#fff;text-decoration:none;font-weight:600;font-size:16px">Barno AI ilovasini ochish</a>
</main><script nonce="{nonce}">location.replace(document.getElementById("go").href);</script>
</body></html>"""
    return HTMLResponse(page, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'",
    })


def _admit(user: AuthUser, login: str | None, *, attempt: str, method: str,
           channel: str) -> admin_users.Access:
    """Shaxs TASDIQLANGANDAN keyin: admin bloklaganmi? -> `Access` yoki 403.

    Tekshiruv shaxs tasdiqlangandan KEYIN, ataylab: aks holda "bloklangan"
    javobi parolni bilmagan odamga ham hisob borligini aytib qo'yardi.
    `devices.py` va `telegram.py` ham shu qoidani ishlatadi.
    """
    verdict = admin_users.access(user, login=login)
    if not verdict.blocked:
        return verdict
    record_auth_event(attempt, False, method=method, channel=channel, reason="blocked",
                      actor_id=user.actorId)
    log.info("Kirish rad etildi - hisob bloklangan: actor_id %s", user.actorId)
    raise error_status(status.HTTP_403_FORBIDDEN, _MSG_BLOCKED)


# --- SSO ---------------------------------------------------------------------


@router.get("/sso/config", response_model=SsoConfig)
def sso_config() -> SsoConfig:
    """Kirish sahifasi uchun: qaysi yo'llar ochiq. Ochiq endpoint, sir yo'q."""
    return SsoConfig(
        enabled=_oidc().configured,
        localLoginEnabled=bool(settings.local_login_enabled),
        startPath=START_PATH,
    )


@router.get("/sso/start", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
def sso_start(
    request: Request,
    return_to: str | None = Query(default=None, alias="return"),
    channel: str | None = None,
    app_challenge: str | None = Query(default=None, max_length=64),
) -> RedirectResponse:
    """Brauzerni Keycloak kirish sahifasiga yuboradi.

    `return` - kirishdan keyin qaytiladigan ilova yo'li (`/admin/users`),
    `channel` - web/miniapp/desktop/mobile (hisob uchun). Ikkalasi
    `state` ostida serverda turadi, Keycloak'ga ketmaydi.

    Mobil ilova (`return` = `SSO_MOBILE_REDIRECT`) `app_challenge` ni ham beradi -
    O'Z PKCE challenge'i (S256). Kod ilovaga `venera-rec://` orqali qaytadi; shu sxemani
    boshqa ilova ham ro'yxatdan o'tkazishi mumkin, shuning uchun kodni faqat verifier'ni
    bilgan ilova almashtiradi (RFC 8252). Usiz mobil kirish boshlanmaydi (400).
    """
    oidc = _oidc()
    if not oidc.configured:
        raise error_status(status.HTTP_501_NOT_IMPLEMENTED, "SSO sozlanmagan")
    app = _app_url(request)
    # Sayt asosiy manzildan boshqa host bilan ochilgan bo'lsa (IP, eski nom),
    # Keycloak baribir ASOSIY manzilga qaytaradi - bu hostda qo'yilgan cookie u
    # yerga yetmaydi va kirish "eskirgan" bo'lib tugardi. Shuning uchun kirish
    # asosiy manzilda qaytadan boshlanadi. Belgi (`_c`) - proksi Host'ni
    # o'zgartirib yuborsa cheksiz aylanmaslik uchun: ikkinchi marta ko'chirilmaydi.
    if settings.sso_app_url and _CANONICAL_MARK not in request.query_params \
            and _other_host(request, app):
        query = urllib.parse.urlencode([*request.query_params.multi_items(), (_CANONICAL_MARK, "1")])
        return RedirectResponse(f"{app}{START_PATH}?{query}", status_code=status.HTTP_302_FOUND)
    return_path = _safe_return(return_to)
    challenge = ""
    if _is_mobile(return_path):
        challenge = (app_challenge or "").strip()
        if not _APP_CHALLENGE.fullmatch(challenge):
            raise error_status(status.HTTP_400_BAD_REQUEST, "Ilova kirishi uchun app_challenge (PKCE S256) kerak")
    secret = secrets.token_urlsafe(32)
    url = oidc.begin(f"{app}{CALLBACK_PATH}", return_to=return_path,
                     channel=_channel(request, channel), binding=_binding(secret), app_challenge=challenge)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    name, path, secure = _bind_cookie(app)
    response.set_cookie(name, secret, max_age=_BIND_MAX_AGE, path=path,
                        httponly=True, samesite="lax", secure=secure)
    return response


@router.get("/sso/callback", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER,
            response_model=None)
def sso_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    store: UserStore = Depends(get_user_store),
    identities: IdentityStore = Depends(get_identity_store),
) -> Response:
    """Keycloak'dan qaytish. Har qanday natija - frontend'ga yo'naltirish:
    muvaffaqiyat `?sso=<bir martalik kod>`, xato `?sso_error=<sabab>`.
    JSON emas: bu manzilni brauzerning o'zi ochadi, JS yo'q.

    `async def` EMAS: Keycloak'ka `urllib` bilan boriladi (bloklaydi).
    """
    oidc = _oidc()
    app = _app_url(request)
    return_to, channel = "/", _channel(request, None)
    try:
        pending = oidc.take_pending(state)
        return_to, channel = pending.return_to, pending.channel
        if not _bound(request, pending.binding):
            raise OidcError("Kirish boshqa brauzerda boshlangan - qaytadan kiring",
                            status=400, code="binding")
        if error:
            # Odam Keycloak sahifasida "bekor" dedi yoki Keycloak so'rovni rad etdi.
            raise OidcError(error_description or error, status=400,
                            code="denied" if error == "access_denied" else error)
        if not code:
            raise OidcError("Keycloak kod qaytarmadi", status=400, code="no_code")
        tokens = oidc.exchange(code, pending, f"{app}{CALLBACK_PATH}")
        profile = oidc.profile(tokens, nonce=pending.nonce)
    except OidcError as exc:
        log.warning("SSO kirish bajarilmadi (%s): %s", exc.code, exc)
        record_auth_event("sso", False, method="sso", channel=channel, reason=f"sso:{exc.code}")
        return _finish(return_to, _fail_url(app, return_to, exc.code))

    login = profile.username
    try:
        known = identities.by_subject(profile.subject)
        if known is not None:
            # Ma'lum odam - blokni `identities.json` ga TEGMASDAN tekshiramiz:
            # bloklangan urinish "oxirgi kirish" bo'lib ko'rinmasin.
            _admit(known.to_public(), known.username, attempt=login, method="sso", channel=channel)
        identity = identities.upsert(profile, legacy=store)
        # Birinchi kirishda `actor_id` eski (`users.yaml`) hisobdan kelishi
        # mumkin - u bloklangan bo'lsa ham shu yerda to'xtaydi.
        verdict = _admit(identity.to_public(), identity.username, attempt=login, method="sso",
                         channel=channel)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        return _finish(return_to, _fail_url(app, return_to, "blocked"))

    token, expires = create_token(identity.subject, version=verdict.token_version, sso=True)
    if tokens.id_token:
        ID_TOKENS[identity.actor_id] = tokens.id_token
    record_auth_event(login, True, method="sso", channel=channel, actor_id=identity.actor_id)
    log.info("Kirish (SSO): %s (actor_id %s, %s)", identity.username, identity.actor_id, channel)
    _connect_sso(oidc, identity.actor_id, identity.username, tokens)
    response = LoginResponse(
        token=token,
        tokenType="Bearer",
        expiresAt=expires.isoformat(),
        passwordChangeRequired=False,
        user=verdict.user,
    )
    handoff = secrets.token_urlsafe(32)
    # Mobil qaytishda kodni ILOVA almashtiradi - unda brauzer cookie'si yo'q,
    # shuning uchun u yerda cookie bilan bog'lanmaydi. Lekin bunday kodni BRAUZER
    # almashtira olmasligi shart (`sso_exchange`) - aks holda hujumchi mobil
    # qaytish bilan olgan kodini `/login?sso=` havolasida birovga berardi.
    mobile = _is_mobile(return_to)
    HANDOFF.put(handoff, {"binding": "" if mobile else pending.binding, "mobile": mobile,
                          "app_challenge": pending.app_challenge if mobile else "",
                          "response": response.model_dump()})
    return _finish(return_to, _done_url(app, return_to, handoff))


@router.post("/sso/exchange", response_model=LoginResponse)
def sso_exchange(body: SsoExchangeRequest, request: Request, response: Response) -> LoginResponse:
    """Bir martalik kod -> token. Ikkinchi marta 400: kod ishlatilgan. Kod
    kirishni boshlagan brauzerdagina ishlaydi (`_BIND_COOKIE`); boshqa brauzer
    urinsa ham kod YONADI - o'g'irlangan havola ikkinchi marta sinalmasin."""
    code = (body.code or "").strip()
    payload = HANDOFF.pop(code) if code else None
    if payload is None or not _bound(request, payload["binding"]):
        raise error_status(status.HTTP_400_BAD_REQUEST, _MSG_HANDOFF)
    # Mobil qaytish kodi faqat ILOVA uchun. Brauzer so'rovini brauzerning o'zi
    # belgilaydi (`Sec-Fetch-Site`, `Origin` - sahifa kodi ularni o'zgartira
    # olmaydi); ilovaning HTTP klienti ularni yubormaydi.
    if payload.get("mobile") and (request.headers.get("sec-fetch-site") or request.headers.get("origin")):
        raise error_status(status.HTTP_400_BAD_REQUEST, _MSG_HANDOFF)
    # Mobil kod - faqat kirishni BOSHLAGAN ilova uchun: o'sha `app_challenge` ning verifier'i
    # bilan. `venera-rec://` ni ushlab olgan boshqa ilovada verifier yo'q - kod esa yuqorida
    # allaqachon yondi.
    if payload.get("mobile"):
        challenge = str(payload.get("app_challenge") or "")
        if not challenge or not body.verifier or not hmac.compare_digest(s256(body.verifier), challenge):
            raise error_status(status.HTTP_400_BAD_REQUEST, _MSG_HANDOFF)
    name, path, secure = _bind_cookie(_app_url(request))
    response.delete_cookie(name, path=path, secure=secure, httponly=True, samesite="lax")
    return LoginResponse(**payload["response"])


# --- zahira (parol) -----------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    request: Request,
    store: UserStore = Depends(get_user_store),
) -> LoginResponse:
    """Zahira hisob (`config/users.yaml`): login + parol -> token.

    Har urinish `auth_events` ga yoziladi: natija, yo'l (`local`), sabab
    kodi - PAROL HECH QACHON.
    """
    channel = channel_of(request)
    if not settings.local_login_enabled:
        record_auth_event(data.username, False, method="local", channel=channel,
                          reason="local_login_disabled")
        raise error_status(status.HTTP_403_FORBIDDEN, _MSG_LOCAL_OFF)
    # `authenticate` topilmagan hisob uchun ham xeshni tekshiradi - javob
    # vaqti bo'yicha hisob borligini aniqlab bo'lmaydi.
    user = store.authenticate(data.username, data.password)
    if user is None:
        log.info("Muvaffaqiyatsiz kirish: %s", data.username)
        record_auth_event(data.username, False, method="local", channel=channel,
                          reason="bad_credentials")
        raise unauthorized(_MSG_BAD_LOGIN)
    verdict = _admit(user.to_public(), None, attempt=data.username, method="local", channel=channel)
    token, expires = create_token(user.email, version=verdict.token_version)
    record_auth_event(data.username, True, method="local", channel=channel, actor_id=user.actor_id)
    log.info("Kirish (zahira): %s", user.email)
    return LoginResponse(
        token=token,
        tokenType="Bearer",
        expiresAt=expires.isoformat(),
        passwordChangeRequired=user.password_change_required,
        user=verdict.user,
    )


# --- sessiya -----------------------------------------------------------------


@router.get("/me", response_model=AuthUser)
def me(user: AuthUser = Depends(current_user)) -> AuthUser:
    """Token'ni tekshiradi va foydalanuvchini qaytaradi.

    Frontend uni ilova ochilganda chaqiradi: token localStorage da saqlangan
    bo'lsa ham u eskirgan bo'lishi mumkin.
    """
    return user


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    user: AuthUser = Depends(current_user),
    identities: IdentityStore = Depends(get_identity_store),
) -> LogoutResponse:
    """Sessiyani yopish.

    JWT HOLATSIZ - server tomonda bekor qilinadigan sessiya YO'Q: tokenni
    FRONTEND o'chiradi, u muddati tugaguncha (`token_ttl_hours`) texnik
    jihatdan yaroqli qoladi. Odamning HAMMA sessiyasini admin tugata oladi:
    `POST /admin/users/{id}/signout` versiyani oshiradi (`api/deps.py`).

    SSO bilan kirgan odamga `ssoLogoutUrl` qaytadi: frontend o'sha yerga
    o'tadi va KEYCLOAK sessiyasi ham yopiladi. Aks holda "Kirish" tugmasi
    odamni so'ramasdan qaytadan kiritardi (SSO sessiyasi tirik) - umumiy
    kompyuterda bu xavfli.

    Ulanishlar (HRM/CRM) QOLADI - ular sessiya emas, odamning saqlangan
    ulanishi (BRB-Tech ID sessiyasi): uni admin panel uzadi.
    """
    sso_url: str | None = None
    oidc = _oidc()
    # Keycloak manzili faqat BRAUZER SSO kirishidan ochilgan sessiyaga beriladi
    # (tokendagi `sso` belgisi). Telegram (`/telegram/session`), qurilma va zahira
    # sessiyalarida Keycloak brauzer sessiyasi yo'q: Mini App "Chiqish" bosilganda
    # Telegram WebView Keycloak sahifasiga, keyin veb ilovaga ketib qolardi.
    # Belgi klient sarlavhasidan EMAS, sessiyaning o'zidan - Mini App to'plami oddiy
    # brauzerda ochilgan bo'lsa ham SSO sessiyasi to'g'ri yopiladi.
    if _sso_session(request) and oidc.configured and identities.by_actor_id(user.actorId) is not None:
        hint = ID_TOKENS.pop(user.actorId, None)
        sso_url = oidc.logout_url(f"{_app_url(request)}/welcome", id_token_hint=hint)
    log.info("Chiqish: %s", user.email)
    return LogoutResponse(status="OK", message="Sessiya yopildi", ssoLogoutUrl=sso_url)


@router.post("/signup", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def signup() -> None:
    """Ro'yxatdan o'tish YO'Q - hisob Keycloak'da, zahira `config/users.yaml` da."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Ro'yxatdan o'tish yo'q: SSO (Keycloak) hisobingiz bilan kiring.",
    )


@router.post("/change-password", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def change_password() -> None:
    """Parol Keycloak'da o'zgartiriladi - bu yerda emas."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Parol SSO (Keycloak) tizimida o'zgartiriladi - u yerda almashtiring.",
    )

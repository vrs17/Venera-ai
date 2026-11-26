"""Barno konnektorining OAuth eshigi (`docs/barno-connector.md`, "Kirish va ruxsat").

    GET  /.well-known/oauth-protected-resource[/mcp]   RFC 9728 - MCP qaysi serverga ishonadi
    GET  /.well-known/oauth-authorization-server       RFC 8414 - eshik metadata si
    POST /oauth/register                               RFC 7591 (DCR) - faqat ma'lum qaytish manzillari
    GET  /oauth/authorize                              so'rov -> sayt rozilik sahifasi `/connect`
    POST /oauth/token                                  kod + PKCE -> tokenlar; refresh aylanadi
    POST /oauth/revoke                                 RFC 7009

NEGA O'Z ESHIGIMIZ (Keycloak emas). Keycloak'ning MCP talablari (CIMD, RFC 8707) hali
"experimental" va bizga baribir o'z rozilik ekranimiz kerak (modul bo'yicha ruxsat). Odam
baribir BRB-Tech ID bilan kiradi - sayt kirishi (`/connect` sahifasi) orqali; Keycloak'da
hech narsa o'zgarmaydi.

MIJOZLAR FAQAT CLAUDE VA CHATGPT. Qaytish manzili ruxsat ro'yxatidan (`redirect_allowed`):
kod faqat claude.ai / chatgpt.com ga yoki odamning O'Z kompyuteriga (Claude Code, loopback)
qaytadi. Ro'yxatdan tashqari manzil bilan na DCR, na CIMD o'tadi - begona sayt odamning
roziligini o'ziga yo'naltira olmaydi. Rozilik sahifasida ham mijoz o'zi aytgan nom emas,
manzildan chiqarilgan nom ko'rinadi (`client_label`): DCR mijozi o'zini "Claude" deb atasa
ham, kod baribir faqat ro'yxatdagi hostga ketadi.

KOD VA TOKENLAR - `connector/store.py`: bir martalik kod (PKCE S256 majburiy), shaffof
tokenlar (HASH), refresh har ishlatilganda aylanadi, qayta ishlatilgan kod/refresh butun
ruxsatni bekor qiladi.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..core import config as _config
from ..core.config import settings
from . import core
from .store import Client, new_secret

log = logging.getLogger(__name__)

router = APIRouter(tags=["connector"], include_in_schema=False)

#: CIMD hujjati yuklanadigan hostlar (Claude: "published identity", Claude Code, ChatGPT).
CIMD_HOSTS = frozenset({"claude.ai", "claude.com", "chatgpt.com"})

#: Aniq qaytish manzillari (web, desktop, telefon ilovalari - hammasi shu bitta manzil orqali).
EXACT_REDIRECTS = frozenset({
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "https://chatgpt.com/connector_platform_oauth_redirect",
})
#: ChatGPT ning eski shakli: `https://chatgpt.com/connector/oauth/{callback_id}`.
_CHATGPT_CALLBACK = re.compile(r"https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,128}")
#: Claude Code: odamning o'z kompyuteri (RFC 8252 loopback) - port har safar boshqa.
_LOOPBACK = re.compile(r"http://(localhost|127\.0\.0\.1)(:(\d{1,5}))?/callback")

#: DCR: jami mijozlar chegarasi va ishlatilmagan mijoz umri (Claude har yangi ulanishda
#: yangisini ro'yxatdan o'tkazadi - ular yig'ilib qolmasin).
DCR_MAX_CLIENTS = 5000
DCR_IDLE_SECONDS = 7 * 24 * 3600
#: CIMD hujjati keshi va yuklash chegaralari.
CIMD_TTL = 24 * 3600
CIMD_MAX_BYTES = 64 * 1024
CIMD_TIMEOUT = 5.0

_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")


# --- yordamchilar ------------------------------------------------------------------------------


def _off() -> JSONResponse | None:
    """Bosh kalit o'chiq yoki manzil yo'q - yo'q yo'l bilan bir xil 404."""
    if not core.enabled() or not core.public_base():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return None


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def redirect_allowed(uri: str) -> bool:
    """Qaytish manzili ruxsat ro'yxatidami (modul izohi)."""
    if not isinstance(uri, str) or len(uri) > 512:
        return False
    if uri in EXACT_REDIRECTS or _CHATGPT_CALLBACK.fullmatch(uri):
        return True
    found = _LOOPBACK.fullmatch(uri)
    return bool(found) and (found.group(3) is None or 0 < int(found.group(3)) < 65536)


def redirect_matches(registered: tuple[str, ...], requested: str) -> bool:
    """So'rovdagi manzil ro'yxatdagilardan biriga AYNAN teng. Loopback'da port farq qilishi
    mumkin (RFC 8252, 7.3): `http://localhost/callback` ro'yxatda bo'lsa `:53122` ham mos."""
    if not redirect_allowed(requested):
        return False
    if requested in registered:
        return True
    found = _LOOPBACK.fullmatch(requested)
    if not found:
        return False
    base = f"http://{found.group(1)}/callback"
    return any(_LOOPBACK.fullmatch(item) and _strip_port(item) == base for item in registered)


def _strip_port(uri: str) -> str:
    found = _LOOPBACK.fullmatch(uri)
    return f"http://{found.group(1)}/callback" if found else uri


def client_label(redirect_uri: str) -> str:
    """Rozilik sahifasida ko'rinadigan nom - mijoz aytgani emas, QAYTISH MANZILIDAN."""
    host = (urllib.parse.urlsplit(redirect_uri).hostname or "").lower()
    if host in ("claude.ai", "claude.com"):
        return "Claude"
    if host == "chatgpt.com":
        return "ChatGPT"
    if host in ("localhost", "127.0.0.1"):
        return "Claude Code"
    return host or "?"


def pkce_ok(verifier: str, challenge: str) -> bool:
    if not _VERIFIER.fullmatch(verifier or ""):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return expected == challenge


def _canonical_resource(value: str | None) -> str | None:
    """`resource` (RFC 8707) - bo'sh bo'lsa `None` (eski mijoz: biznikini olamiz), oxiridagi
    `/` e'tiborsiz. Boshqa manzil - xato."""
    if value is None or not value.strip():
        return None
    return value.strip().rstrip("/")


def _scopes_from(raw: str | None) -> frozenset[str]:
    """So'ralgan qamrov - bizda bori; noma'lum so'zlar (`openid`, `offline_access`) tashlanadi.
    Hech biri qolmasa - default (`plaud.read`)."""
    wanted = frozenset((raw or "").split()) & frozenset(core.SCOPES)
    return wanted or core.DEFAULT_SCOPES


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    """Qaytish manzili ishonchsiz bo'lsa - YO'NALTIRILMAYDI, faqat sahifa (RFC 6749, 4.1.2.1)."""
    body = ("<!doctype html><meta charset=utf-8><title>Barno</title>"
            "<body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
            f"<h1>Barno</h1><p>{html.escape(message)}</p></body>")
    return HTMLResponse(body, status_code=status)


def _redirect_error(redirect_uri: str, state: str, error: str, description: str = "") -> RedirectResponse:
    params = {"error": error, "iss": core.public_base()}
    if description:
        params["error_description"] = description
    if state:
        params["state"] = state
    return RedirectResponse(_with_query(redirect_uri, params), status_code=302)


def _with_query(uri: str, params: dict[str, str]) -> str:
    sep = "&" if urllib.parse.urlsplit(uri).query else "?"
    return f"{uri}{sep}{urllib.parse.urlencode(params)}"


def approved_redirect(redirect_uri: str, code: str, state: str) -> str:
    """Rozilikdan keyingi qaytish: `code`, `state`, `iss` (RFC 9207)."""
    params = {"code": code, "iss": core.public_base()}
    if state:
        params["state"] = state
    return _with_query(redirect_uri, params)


def denied_redirect(redirect_uri: str, state: str) -> str:
    params = {"error": "access_denied", "iss": core.public_base()}
    if state:
        params["state"] = state
    return _with_query(redirect_uri, params)


# --- CIMD --------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib imzosi
        return None


def _fetch_json(url: str) -> dict:
    """CIMD hujjatini yuklaydi: yo'naltirishsiz, 5 s, 64 KB. Testlar shu funksiyani almashtiradi."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "barno-connector/1"})
    with opener.open(request, timeout=CIMD_TIMEOUT) as response:
        if getattr(response, "status", 200) != 200:
            raise ValueError(f"status {response.status}")
        data = response.read(CIMD_MAX_BYTES + 1)
    if len(data) > CIMD_MAX_BYTES:
        raise ValueError("too large")
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    return doc


def _is_cimd(client_id: str) -> bool:
    parts = urllib.parse.urlsplit(client_id)
    return parts.scheme == "https" and bool(parts.path) and parts.path != "/"


def resolve_client(client_id: str) -> Client | None:
    """`client_id` -> mijoz yoki `None` (noma'lum / ruxsatsiz). CIMD - URL, kesh bilan."""
    client_id = (client_id or "").strip()
    if not client_id or len(client_id) > 512:
        return None
    store = core.store()
    if not _is_cimd(client_id):
        found = store.client(client_id)
        return found if found is not None and found.kind == "dcr" else None
    parts = urllib.parse.urlsplit(client_id)
    try:
        port = parts.port               # buzuq port (`:abc`, `:99999`) - ValueError
    except ValueError:
        return None
    if (parts.hostname or "").lower() not in CIMD_HOSTS or parts.query or parts.fragment \
            or parts.username or port not in (None, 443):
        return None
    cached = store.client(client_id)
    if cached is not None and cached.kind == "cimd" and time.time() - cached.fetched_at < CIMD_TTL:
        return cached
    try:
        doc = _fetch_json(client_id)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        log.warning("Konnektor: CIMD yuklanmadi (%s): %s", parts.hostname, exc)
        return cached if cached is not None and cached.kind == "cimd" else None
    uris = doc.get("redirect_uris")
    if doc.get("client_id") != client_id or not isinstance(uris, list) or not uris:
        log.warning("Konnektor: CIMD hujjati yaroqsiz (%s)", parts.hostname)
        return None
    allowed = [u for u in uris if isinstance(u, str) and redirect_allowed(u)]
    if not allowed:
        return None
    name = doc.get("client_name") if isinstance(doc.get("client_name"), str) else parts.hostname
    keep = {k: doc[k] for k in ("client_name", "client_uri", "logo_uri", "grant_types",
                                "token_endpoint_auth_method") if k in doc}
    return store.put_client(client_id, "cimd", name, allowed, keep)


# --- metadata ----------------------------------------------------------------------------------


def protected_resource() -> dict:
    base = core.public_base()
    return {
        "resource": core.mcp_resource(),
        "authorization_servers": [base],
        "scopes_supported": sorted(core.SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "Barno AI",
        "resource_documentation": f"{base}/connector",
    }


def authorization_server() -> dict:
    base = core.public_base()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": sorted(core.SCOPES),
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{base}/connector",
    }


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def get_protected_resource() -> Response:
    return _off() or JSONResponse(protected_resource())


@router.get("/.well-known/oauth-authorization-server")
def get_authorization_server() -> Response:
    return _off() or JSONResponse(authorization_server())


@router.get("/.well-known/openai-apps-challenge")
def get_openai_apps_challenge() -> Response:
    """OpenAI ilovalar katalogi domen tasdig'i: `.env` dagi kod oddiy matn sifatida. Kod yo'q - 404."""
    code = _config.openai_apps_challenge_now()[:1024]
    if not code:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return _off() or _no_store(Response(code, media_type="text/plain"))


# --- DCR ---------------------------------------------------------------------------------------


def _dcr_error(error: str, description: str) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=400)


@router.post("/oauth/register")
async def register(request: Request) -> Response:
    """RFC 7591. Faqat ommaviy mijoz (`none`) va faqat ruxsat ro'yxatidagi qaytish manzillari."""
    if (off := _off()) is not None:
        return off
    try:
        body = await request.json()
    except ValueError:
        return _dcr_error("invalid_client_metadata", "Body must be JSON")
    if not isinstance(body, dict):
        return _dcr_error("invalid_client_metadata", "Body must be a JSON object")
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > 10 \
            or not all(isinstance(u, str) and redirect_allowed(u) for u in uris):
        return _dcr_error("invalid_redirect_uri",
                          "Only Claude and ChatGPT callback addresses are accepted")
    grants = body.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
        return _dcr_error("invalid_client_metadata", "Only authorization_code and refresh_token")
    store = core.store()
    store.prune_dcr(idle_seconds=DCR_IDLE_SECONDS)
    if store.count_clients("dcr") >= DCR_MAX_CLIENTS:
        # Ruxsatga yetmagan eng eskilarini bo'shatamiz (begona to'ldirish 503 bilan to'smasin).
        store.evict_unused_dcr(max(1, DCR_MAX_CLIENTS // 100))
        if store.count_clients("dcr") >= DCR_MAX_CLIENTS:
            log.warning("Konnektor: DCR chegarasi to'ldi (%d)", DCR_MAX_CLIENTS)
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
    raw_name = body.get("client_name")
    name = raw_name.strip()[:120] if isinstance(raw_name, str) and raw_name.strip() \
        else client_label(uris[0])
    client_id = "dcr_" + new_secret()
    client = store.put_client(client_id, "dcr", name, list(uris), {"client_name": name})
    response = JSONResponse({
        "client_id": client.client_id,
        "client_id_issued_at": int(client.fetched_at),
        "client_name": client.name,
        "redirect_uris": list(client.redirect_uris),
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }, status_code=201)
    return _no_store(response)


# --- authorize ---------------------------------------------------------------------------------


@router.get("/oauth/authorize")
def authorize(request: Request) -> Response:
    """So'rovni tekshiradi va sayt rozilik sahifasiga (`/connect?request=`) yuboradi.

    Mijoz yoki qaytish manzili ishonchsiz - sahifa (yo'naltirish YO'Q). Qolgan xatolar -
    mijozga `error` bilan qaytariladi (RFC 6749, 4.1.2.1)."""
    if (off := _off()) is not None:
        return off
    q = request.query_params
    client_id, redirect_uri, state = q.get("client_id", ""), q.get("redirect_uri", ""), q.get("state", "")
    client = resolve_client(client_id)
    if client is None:
        return _error_page("This app is not allowed to connect to Barno.")
    if not redirect_uri and len(client.redirect_uris) == 1 and not _LOOPBACK.fullmatch(client.redirect_uris[0]):
        redirect_uri = client.redirect_uris[0]
    if not redirect_matches(client.redirect_uris, redirect_uri):
        return _error_page("The return address of this app is not allowed.")
    state = state[:1024]
    if q.get("response_type") != "code":
        return _redirect_error(redirect_uri, state, "unsupported_response_type")
    challenge = q.get("code_challenge", "")
    if q.get("code_challenge_method") != "S256" or not _CHALLENGE.fullmatch(challenge):
        return _redirect_error(redirect_uri, state, "invalid_request", "PKCE S256 is required")
    resource = _canonical_resource(q.get("resource"))
    if resource is not None and resource != core.mcp_resource():
        return _redirect_error(redirect_uri, state, "invalid_target")
    pending = core.store().put_request(client.client_id, redirect_uri, state, challenge,
                                       _scopes_from(q.get("scope")), core.mcp_resource())
    query = urllib.parse.urlencode({"request": pending.id})
    return RedirectResponse(f"{core.public_base()}/connect?{query}", status_code=302)


# --- token -------------------------------------------------------------------------------------


def _token_error(error: str, description: str = "", status: int = 400) -> Response:
    body = {"error": error}
    if description:
        body["error_description"] = description
    return _no_store(JSONResponse(body, status_code=status))


def _token_body(issued) -> Response:
    return _no_store(JSONResponse({
        "access_token": issued.access_token,
        "token_type": "Bearer",
        "expires_in": issued.expires_in,
        "refresh_token": issued.refresh_token,
        "scope": " ".join(sorted(issued.scopes)),
    }))


@router.post("/oauth/token")
async def token(request: Request) -> Response:
    if (off := _off()) is not None:
        return off
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 - buzuq tana: oddiy OAuth xatosi
        return _token_error("invalid_request")
    grant_type = str(form.get("grant_type") or "")
    client_id = str(form.get("client_id") or "")
    if not client_id:
        return _token_error("invalid_client", "client_id is required", status=401)
    resource = _canonical_resource(form.get("resource") if isinstance(form.get("resource"), str) else None)
    if resource is not None and resource != core.mcp_resource():
        return _token_error("invalid_target")
    store = core.store()
    ttl = {"access_ttl": settings.mcp_access_ttl, "refresh_ttl": settings.mcp_refresh_ttl}
    if grant_type == "authorization_code":
        verifier = str(form.get("code_verifier") or "")
        try:
            grant, _ = store.redeem(str(form.get("code") or ""), client_id=client_id,
                                    redirect_uri=str(form.get("redirect_uri") or ""),
                                    resource=resource,
                                    verify=lambda challenge: pkce_ok(verifier, challenge))
            issued = store.issue(grant.id, **ttl)
        except LookupError as exc:
            return _token_error(str(exc.args[0]) if exc.args else "invalid_grant")
        log.info("Konnektor: ruxsat berildi - actor %s, %s", grant.actor_id, grant.client_name)
        return _token_body(issued)
    if grant_type == "refresh_token":
        raw = str(form.get("refresh_token") or "")
        try:
            issued = store.rotate(raw, client_id=client_id, resource=resource, **ttl)
        except LookupError as exc:
            return _token_error(str(exc.args[0]) if exc.args else "invalid_grant")
        # Odam hali ruxsatlimi (blok, "hamma joydan chiqarish") - yangi token bilan tekshiramiz.
        grant = store.access(issued.access_token)
        if grant is None or core.user_for_grant(grant) is None:
            return _token_error("invalid_grant")
        return _token_body(issued)
    return _token_error("unsupported_grant_type")


@router.post("/oauth/revoke")
async def revoke(request: Request) -> Response:
    """RFC 7009: noma'lum token ham 200 - token borligini tekshirish vositasi bo'lmasin."""
    if (off := _off()) is not None:
        return off
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return _token_error("invalid_request")
    raw = str(form.get("token") or "")
    if raw and len(raw) <= 512:
        core.store().revoke_token(raw)
    return _no_store(Response(status_code=200))

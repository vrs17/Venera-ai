"""Barno konnektorining MCP serveri - `POST /mcp` (Streamable HTTP, holatsiz, JSON javob).

Reja: `docs/barno-connector.md`. Tashqi `mcp` SDK yo'q - kerakli qism kichik va to'liq testlanadi:

    POST   /mcp    bitta JSON-RPC 2.0 xabari -> JSON javob (SSE yo'q, `Mcp-Session-Id` yo'q)
    GET    /mcp    405 (`Allow: POST`) - serverdan oqim yo'q
    DELETE /mcp    405 - sessiya yo'q

TARTIB (har so'rovda): bosh kalit (o'chiq - 404, yo'q yo'l bilan bir xil) -> `Origin` (DNS-rebinding,
MCP spetsifikatsiyasi) -> `MCP-Protocol-Version` -> token (JSON-RPC dan OLDIN: tokensiz so'rov
tanasi o'qilmaydi ham) -> xabar. 401 dagi `WWW-Authenticate` mijozni OAuth metadata siga yuboradi
(`connector/oauth.py`).

IKKI DAVR (har so'rov o'zi tanlaydi - server holatsiz):
- 2025 (`initialize` bilan): 2025-11-25 / 2025-06-18 / 2025-03-26 - avvalgidek.
- 2026-07-28 (holatsiz yadro): `initialize` yo'q; har so'rov `_meta` da versiya va mijoz imkoniyatlarini,
  sarlavhalarda `MCP-Protocol-Version`, `Mcp-Method` (va `tools/call` uchun `Mcp-Name`) olib keladi -
  tana bilan mos kelmasa 400 / -32020. `server/discover`; natijalarda `resultType` va kesh ko'rsatmalari
  (`ttlMs`, `cacheScope`); noma'lum metod 404 / -32601.
Noma'lum versiya (sarlavhada yoki `_meta` da) - 400 / -32022, `data.supported` bilan: yangi mijoz
"eski server" deb 2025 ga tushib qolmasdan 2026-07-28 bilan qayta so'raydi.

`tools/call`: qamrov (`plaud.read`), tezlik chegarasi (ruxsatga daqiqasiga 60), jurnal
(`core.record_call` - kim / ilova / vosita / holat / vaqt / hajm; MATN YO'Q). Vositalar va
ularning xatolari - `plaud_tools.py`.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..schemas.auth import AuthUser
from ..services.analytics import bind as _meter_bind
from . import core
from .plaud_tools import TOOLS, Result, Tool, ToolError
from .store import GrantRow

log = logging.getLogger(__name__)

router = APIRouter(tags=["connector"], include_in_schema=False)

#: 2026-07-28 - holatsiz yadro (har so'rov o'z versiyasi bilan keladi).
MODERN_VERSION = "2026-07-28"
#: `initialize` bilan ishlaydigan versiyalar - birinchisi eng yangisi (`initialize` da mijozniki
#: noma'lum bo'lsa shu).
LEGACY_VERSIONS: tuple[str, ...] = ("2025-11-25", "2025-06-18", "2025-03-26")
#: Hammasi - `MCP-Protocol-Version` sarlavhasi, `server/discover` va -32022 dagi ro'yxat.
PROTOCOL_VERSIONS: tuple[str, ...] = (MODERN_VERSION, *LEGACY_VERSIONS)
#: 2026-07-28 so'rov `_meta` kalitlari.
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
#: Kesh ko'rsatmalari (2026-07-28 `caching`): `server/discover` hamma uchun bir xil - `public`;
#: vositalar ro'yxati ruxsat qamroviga qarab - `private`.
DISCOVER_TTL_MS = 3_600_000
TOOLS_TTL_MS = 300_000
#: `Origin` sarlavhasi kelsa - faqat shular (va o'zimiz, `core.public_base`).
ALLOWED_ORIGINS = frozenset({"https://claude.ai", "https://claude.com", "https://chatgpt.com"})
#: Ruxsat bo'yicha tezlik chegarasi (`calls` jurnalidan sanaladi - jarayonlar orasida ham bir xil).
RATE_LIMIT = 60
RATE_WINDOW = 60.0
#: Javob matnining umumiy qopqog'i (belgi) - vositalar o'zi kichikroq beradi, bu oxirgi to'r.
MAX_TEXT = 100_000
#: So'rov tanasi - bitta JSON-RPC xabari, katta bo'lishi uchun sabab yo'q.
MAX_BODY = 256 * 1024

SERVER_INFO = {"name": "barno", "title": "Barno AI", "version": "1.0.0"}
INSTRUCTIONS = (
    "Barno AI provides read-only access to the signed-in person's own meeting recordings from Barno "
    "(Plaud and the Barno recorder): meeting list, summaries, transcripts, action items and minutes. "
    "Meeting ids are 32-character hex strings returned by search_meetings and search. Long transcripts "
    "are paginated with next_cursor."
)

# JSON-RPC xato kodlari.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
HEADER_MISMATCH = -32020          # 2026-07-28: sarlavha yo'q yoki tana bilan mos emas
UNSUPPORTED_VERSION = -32022      # 2026-07-28: `data.supported` / `data.requested` bilan

#: 2026-07-28 sarlavha qiymati ASCII bo'lmasa: `=?base64?...?=`.
_BASE64_HEADER = re.compile(r"=\?base64\?([A-Za-z0-9+/]*={0,2})\?=")


class RpcError(Exception):
    """JSON-RPC xatosi (`error` bilan): noma'lum metod / vosita, ruxsatsiz qamrov. HTTP 200;
    2026-07-28 da noma'lum metod - 404."""

    def __init__(self, code: int, message: str, status: int = 200) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# --- transport -------------------------------------------------------------------------------------


def _gate(request: Request) -> Response | None:
    """Bosh kalit va `Origin`. `None` - davom etish mumkin."""
    base = core.public_base()
    if not core.enabled() or not base:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    origin = request.headers.get("origin")
    if origin is not None and origin.strip().rstrip("/").lower() not in ALLOWED_ORIGINS | {base.lower()}:
        return JSONResponse({"error": "forbidden_origin"}, status_code=403)
    return None


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def challenge(rejected: bool) -> str:
    """`WWW-Authenticate` (RFC 6750 + RFC 9728): metadata manzili va kerakli qamrov. `invalid_token` -
    token kelgan, lekin yaroqsiz (muddati o'tgan, bekor qilingan, boshqa manzil uchun, hisob bloklangan)."""
    parts = ['error="invalid_token"'] if rejected else []
    parts.append(f'resource_metadata="{core.public_base()}/.well-known/oauth-protected-resource/mcp"')
    parts.append(f'scope="{" ".join(sorted(core.SCOPES))}"')
    return "Bearer " + ", ".join(parts)


def _unauthorized(rejected: bool) -> Response:
    body = {"error": "invalid_token", "error_description": "The access token is not valid"} if rejected \
        else {"error": "unauthorized", "error_description": "Authorization required"}
    return JSONResponse(body, status_code=401, headers={"WWW-Authenticate": challenge(rejected)})


def _authenticate(raw: str) -> tuple[GrantRow, AuthUser] | None:
    """Token -> (ruxsat, odam). Odam har safar qayta tekshiriladi (blok, "hamma joydan chiqarish")."""
    grant = core.resolve_access_token(raw) if raw else None
    if grant is None:
        return None
    user = core.user_for_grant(grant)
    return (grant, user) if user is not None else None


async def _read(request: Request) -> bytes | None:
    """Tana `MAX_BODY` gacha; oshsa `None` (butunlay xotiraga o'qilmaydi)."""
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _json(data: Any, status: int = 200) -> Response:
    # `ensure_ascii=True`: mijoz yuborgan yolg'iz surrogat (`"\ud800"`) UTF-8 ga o'tmay 500 bermasin.
    return Response(json.dumps(data).encode("ascii"), status_code=status, media_type="application/json")


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _valid_id(msg_id: Any) -> bool:
    return msg_id is None or (isinstance(msg_id, (str, int)) and not isinstance(msg_id, bool))


def _envelope(body: bytes) -> dict[str, Any] | Response:
    """Tana -> so'rov yoki bildirishnoma xabari (`id` yo'q bo'lishi mumkin - `mcp_post` hal qiladi),
    yoki tayyor javob: xato (400 / -326xx) yoki 202 (mijozning javobi - unga JSON-RPC javobi
    berilmaydi)."""
    try:
        msg = json.loads(body)
    except (ValueError, RecursionError):          # buzuq JSON yoki juda chuqur ichma-ichlik
        return _json(_error(None, PARSE_ERROR, "Parse error"), 400)
    if isinstance(msg, list):
        return _json(_error(None, INVALID_REQUEST, "Batch requests are not supported"), 400)
    if not isinstance(msg, dict):
        return _json(_error(None, INVALID_REQUEST, "Invalid request"), 400)
    if "method" not in msg:
        # Mijozning javobi (biz so'rov yubormaymiz) - qabul qilinadi, javobsiz.
        if "id" in msg and ("result" in msg or "error" in msg):
            return Response(status_code=202)
        return _json(_error(None, INVALID_REQUEST, "Invalid request"), 400)
    msg_id = msg.get("id")
    if not _valid_id(msg_id):
        return _json(_error(None, INVALID_REQUEST, "Invalid id"), 400)
    if msg.get("jsonrpc") != "2.0" or not isinstance(msg["method"], str):
        return _json(_error(msg_id, INVALID_REQUEST, "Invalid request"), 400)
    return msg


def _meta(msg: dict[str, Any]) -> dict[str, Any] | None:
    params = msg.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    return meta if isinstance(meta, dict) else None


def _is_modern(header_version: str | None, msg: dict[str, Any]) -> bool:
    """2026-07-28 so'rovimi: sarlavha yoki `_meta` dagi versiya kaliti. `initialize` - har doim
    2025 davri ("initialize eski semantikani tanlaydi", 2026-07-28 versioning)."""
    if msg["method"] == "initialize":
        return False
    if header_version == MODERN_VERSION:
        return True
    meta = _meta(msg)
    return meta is not None and META_VERSION in meta


def _unsupported(msg_id: Any, requested: Any) -> Response:
    error = _error(msg_id, UNSUPPORTED_VERSION, "Unsupported protocol version")
    error["error"]["data"] = {"supported": list(PROTOCOL_VERSIONS), "requested": str(requested)[:64]}
    return _json(error, 400)


def _header(request: Request, name: str) -> str | None:
    """2026-07-28 standart sarlavhasi (`=?base64?...?=` ochiladi). Ochilmasa - `None` (mos emas)."""
    raw = request.headers.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    found = _BASE64_HEADER.fullmatch(raw)
    if found is None:
        return raw
    try:
        return base64.b64decode(found.group(1), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):            # `binascii.Error` - `ValueError`
        return None


def _modern_problem(request: Request, header_version: str | None, msg: dict[str, Any]) -> Response | None:
    """2026-07-28 so'rov qoidalari (basic `_meta`, streamable-http sarlavhalari). `None` - joyida."""
    msg_id = msg.get("id")
    meta = _meta(msg) or {}
    version = meta.get(META_VERSION)
    if version is None:
        return _json(_error(msg_id, INVALID_PARAMS, f"Missing required _meta field: {META_VERSION}"), 400)
    if version != MODERN_VERSION:
        return _unsupported(msg_id, version)
    if header_version != version:
        return _json(_error(msg_id, HEADER_MISMATCH,
                            "Header mismatch: MCP-Protocol-Version header does not match the request body"), 400)
    if not isinstance(meta.get(META_CAPABILITIES), dict):
        return _json(_error(msg_id, INVALID_PARAMS, f"Missing required _meta field: {META_CAPABILITIES}"), 400)
    if _header(request, "mcp-method") != msg["method"]:
        return _json(_error(msg_id, HEADER_MISMATCH,
                            "Header mismatch: Mcp-Method header is missing or does not match the request body"), 400)
    if msg["method"] == "tools/call":
        params = msg.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        if not isinstance(name, str) or _header(request, "mcp-name") != name:
            return _json(_error(msg_id, HEADER_MISMATCH,
                                "Header mismatch: Mcp-Name header is missing or does not match the request body"),
                         400)
    return None


@router.api_route("/mcp", methods=["GET", "DELETE"])
async def mcp_other(request: Request) -> Response:
    """Serverdan oqim (GET) va sessiya (DELETE) yo'q - holatsiz server."""
    return _gate(request) or Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    """Bitta JSON-RPC xabari - tekshiruvlar tartibi modul izohida."""
    if (blocked := _gate(request)) is not None:
        return blocked
    version = request.headers.get("mcp-protocol-version")
    version = version.strip() if version is not None else None
    if version is not None and version not in PROTOCOL_VERSIONS:
        return _unsupported(None, version)
    raw = _bearer(request)
    auth = await run_in_threadpool(_authenticate, raw)
    if auth is None:
        return _unauthorized(rejected=bool(raw))
    grant, user = auth
    # Hisob konteksti SO'ROV vazifasida (async) - threadpool'dagi vositalar uni nusxada oladi
    # (`deps.current_user` bilan bir xil, `analytics/meter.py` 2-tuzoq).
    _meter_bind(user.actorId, "api")

    body = await _read(request)
    if body is None:
        return _json(_error(None, INVALID_REQUEST, "Request body too large"), 413)
    msg = _envelope(body)
    if isinstance(msg, Response):
        return msg
    modern = _is_modern(version, msg)
    if modern and (problem := _modern_problem(request, version, msg)) is not None:
        return problem
    if "id" not in msg:
        return Response(status_code=202)                # bildirishnoma (`notifications/initialized` ...)
    msg_id, method, params = msg["id"], msg["method"], msg.get("params")
    if msg_id is None:
        return _json(_error(None, INVALID_REQUEST, "Request id must not be null"), 400)
    if params is not None and not isinstance(params, dict):
        return _json(_error(msg_id, INVALID_PARAMS, "params must be an object"))
    try:
        result = await _dispatch(method, params or {}, grant, user, modern)
    except RpcError as exc:
        return _json(_error(msg_id, exc.code, exc.message), exc.status)
    return _json({"jsonrpc": "2.0", "id": msg_id, "result": result})


# --- metodlar --------------------------------------------------------------------------------------


async def _dispatch(method: str, params: dict[str, Any], grant: GrantRow, user: AuthUser,
                    modern: bool = False) -> dict[str, Any]:
    if modern:
        if method == "server/discover":
            return discover()
        if method == "tools/list":
            return {"resultType": "complete", "tools": [t.listing() for t in granted_tools(grant)],
                    "ttlMs": TOOLS_TTL_MS, "cacheScope": "private"}
        if method == "tools/call":
            return {"resultType": "complete", **await run_in_threadpool(call_tool, grant, user, params)}
        # `ping`, `initialize` ... 2026-07-28 da yo'q; noma'lum metod - 404 (streamable-http).
        raise RpcError(METHOD_NOT_FOUND, "Method not found", status=404)
    if method == "initialize":
        return initialize(params)
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [t.listing() for t in granted_tools(grant)]}
    if method == "tools/call":
        return await run_in_threadpool(call_tool, grant, user, params)
    raise RpcError(METHOD_NOT_FOUND, "Method not found")


def initialize(params: dict[str, Any]) -> dict[str, Any]:
    """2025 davri. 2026-07-28 so'ralsa ham 2025-11-25 (u versiyada `initialize` yo'q)."""
    wanted = params.get("protocolVersion")
    return {"protocolVersion": wanted if wanted in LEGACY_VERSIONS else LEGACY_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}


def discover() -> dict[str, Any]:
    """2026-07-28 `server/discover`: versiyalar, imkoniyatlar, server nomi (`_meta`), ko'rsatma, kesh."""
    return {"resultType": "complete", "supportedVersions": list(PROTOCOL_VERSIONS),
            "capabilities": {"tools": {}}, "_meta": {META_SERVER_INFO: SERVER_INFO},
            "instructions": INSTRUCTIONS, "ttlMs": DISCOVER_TTL_MS, "cacheScope": "public"}


def granted_tools(grant: GrantRow) -> list[Tool]:
    """Faqat odam ruxsat bergan modullarning vositalari."""
    return [t for t in TOOLS.values() if t.scope in grant.scopes]


def _ok(out: Result) -> dict[str, Any]:
    text = out.text if out.text is not None else json.dumps(out.structured, ensure_ascii=False)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n\n[...truncated]"
    return {"content": [{"type": "text", "text": text}], "structuredContent": out.structured, "isError": False}


def _fail(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _size(result: dict[str, Any]) -> int:
    return len(json.dumps(result).encode("ascii"))


def call_tool(grant: GrantRow, user: AuthUser, params: dict[str, Any]) -> dict[str, Any]:
    """Bitta vosita chaqiruvi; har natija (muvaffaqiyat, xato, rad) jurnalga yoziladi."""
    name, args = params.get("name"), params.get("arguments")
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None:
        # Mijoz yuborgan ixtiyoriy nom jurnalga yozilmaydi - faqat "unknown".
        core.record_call(grant, "unknown", "error", 0, 0)
        raise RpcError(INVALID_PARAMS, f"Unknown tool: {str(name)[:64]}")
    if tool.scope not in grant.scopes:
        core.record_call(grant, tool.name, "denied", 0, 0)
        raise RpcError(INVALID_PARAMS, f"Tool not permitted for this connection: {tool.name}")
    if args is not None and not isinstance(args, dict):
        core.record_call(grant, tool.name, "error", 0, 0)
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    started = time.monotonic()
    if core.store().calls_since(grant.id, time.time() - RATE_WINDOW) >= RATE_LIMIT:
        result, status = _fail(f"Rate limit reached ({RATE_LIMIT} calls per minute); retry in a minute"), "denied"
    else:
        try:
            result, status = _ok(tool.handler(user, args or {})), "ok"
        except ToolError as exc:
            result, status = _fail(exc.message), exc.status
        except Exception:                                           # noqa: BLE001 - 500 emas, natija
            log.warning("Konnektor: %s vositasi yiqildi (actor %s)", tool.name, grant.actor_id, exc_info=True)
            result, status = _fail("Internal error in Barno; try again later"), "error"
    ms = int((time.monotonic() - started) * 1000)
    core.record_call(grant, tool.name, status, ms, _size(result))
    return result

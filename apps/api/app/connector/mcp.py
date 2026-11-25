"""Barno konnektorining MCP serveri - `POST /mcp` (Streamable HTTP, holatsiz, JSON javob).

Reja: `docs/barno-connector.md`. Tashqi `mcp` SDK yo'q - kerakli qism kichik va to'liq testlanadi:

    POST   /mcp    bitta JSON-RPC 2.0 xabari -> JSON javob (SSE yo'q, `Mcp-Session-Id` yo'q)
    GET    /mcp    405 (`Allow: POST`) - serverdan oqim yo'q
    DELETE /mcp    405 - sessiya yo'q

TARTIB (har so'rovda): bosh kalit (o'chiq - 404, yo'q yo'l bilan bir xil) -> `Origin` (DNS-rebinding,
MCP spetsifikatsiyasi) -> `MCP-Protocol-Version` -> token (JSON-RPC dan OLDIN: tokensiz so'rov
tanasi o'qilmaydi ham) -> xabar. 401 dagi `WWW-Authenticate` mijozni OAuth metadata siga yuboradi
(`connector/oauth.py`).

`tools/call`: qamrov (`plaud.read`), tezlik chegarasi (ruxsatga daqiqasiga 60), jurnal
(`core.record_call` - kim / ilova / vosita / holat / vaqt / hajm; MATN YO'Q). Vositalar va
ularning xatolari - `plaud_tools.py`.
"""

from __future__ import annotations

import json
import logging
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

#: Qo'llanadigan protokol versiyalari - birinchisi eng yangisi (mijozniki noma'lum bo'lsa shu).
PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-11-25", "2025-06-18", "2025-03-26")
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


class RpcError(Exception):
    """JSON-RPC xatosi (HTTP 200, `error` bilan): noma'lum metod / vosita, ruxsatsiz qamrov."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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


def _envelope(body: bytes) -> dict[str, Any] | Response:
    """Tana -> javob kutadigan so'rov xabari, yoki tayyor javob: xato (400 / -326xx) yoki 202
    (bildirishnoma, mijozning javobi - ularga JSON-RPC javobi berilmaydi)."""
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
    if msg_id is not None and (isinstance(msg_id, bool) or not isinstance(msg_id, (str, int))):
        return _json(_error(None, INVALID_REQUEST, "Invalid id"), 400)
    if msg.get("jsonrpc") != "2.0" or not isinstance(msg["method"], str):
        return _json(_error(msg_id, INVALID_REQUEST, "Invalid request"), 400)
    if "id" not in msg:
        return Response(status_code=202)                # bildirishnoma (`notifications/initialized` ...)
    if msg_id is None:
        return _json(_error(None, INVALID_REQUEST, "Request id must not be null"), 400)
    if msg.get("params") is not None and not isinstance(msg["params"], dict):
        return _json(_error(msg_id, INVALID_PARAMS, "params must be an object"))
    return msg


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
    if version is not None and version.strip() not in PROTOCOL_VERSIONS:
        return _json(_error(None, INVALID_REQUEST, "Unsupported MCP-Protocol-Version"), 400)
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
    msg_id, method, params = msg["id"], msg["method"], msg.get("params") or {}
    try:
        result = await _dispatch(method, params, grant, user)
    except RpcError as exc:
        return _json(_error(msg_id, exc.code, exc.message))
    return _json({"jsonrpc": "2.0", "id": msg_id, "result": result})


# --- metodlar --------------------------------------------------------------------------------------


async def _dispatch(method: str, params: dict[str, Any], grant: GrantRow, user: AuthUser) -> dict[str, Any]:
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
    wanted = params.get("protocolVersion")
    return {"protocolVersion": wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}


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

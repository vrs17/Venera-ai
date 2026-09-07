"""Yagona xato shakli.

MUAMMO: FastAPI har qanday xatoda `{"detail": "..."}` qaytaradi. Frontend esa
(`apps/web/src/api/http.ts`) aynan shunday o'qiydi:

    throw new ApiError(body?.message || `Request failed (${response.status})`, body)

Ya'ni u `message` maydonini kutadi. `detail` bilan qaytarsak foydalanuvchi
HAR DOIM umumiy "Request failed (400)" ni ko'radi va serverning aniq xabari
(masalan "Email yoki parol noto'g'ri") YO'QOLADI.

Shuning uchun bu yerda FastAPI ning uchala handler'i ham almashtiriladi.
Bu jimgina yo'qoladigan turdagi nuqson - shuning uchun `tests/test_errors.py`
uni qo'riqlaydi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

#: HTTP kodi -> qisqa nom (frontend `error` maydonini log/debug uchun ishlatadi).
_NAMES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def error_response(request: Request, code: int, message: str) -> JSONResponse:
    """`schemas.auth.ApiErrorResponse` shakliga mos javob."""
    return JSONResponse(
        status_code=code,
        content={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": code,
            "error": _NAMES.get(code, "Error"),
            "message": message,
            "path": request.url.path,
        },
    )


def install(app: FastAPI) -> None:
    """Handler'larni ilovaga ulaydi. `main.py` dan bir marta chaqiriladi."""

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # HTTPException(detail=...) dagi matn `message` ga o'tadi.
        return error_response(request, exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic xatolari ro'yxat bo'lib keladi. Foydalanuvchiga birinchisini
        # o'qiladigan qilib ko'rsatamiz, qolganini logga yozamiz.
        problems = exc.errors()
        first = problems[0] if problems else {}
        field = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = first.get("msg", "So'rov noto'g'ri")
        log.debug("Validatsiya xatosi %s: %s", request.url.path, problems)
        return error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{field}: {message}" if field else message,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Ichki xato tafsiloti FOYDALANUVCHIGA CHIQMAYDI (stack trace ichida
        # yo'l, kutubxona versiyasi va ba'zan sir bo'ladi) - faqat logga.
        log.exception("Ushlanmagan xato: %s %s", request.method, request.url.path)
        return error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Ichki xato yuz berdi",
        )


def unauthorized(message: str = "Avtorizatsiya talab qilinadi") -> HTTPException:
    """401 - token yo'q, eskirgan yoki buzilgan."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )

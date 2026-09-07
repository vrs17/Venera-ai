"""Venera API - ilova nuqtasi.

Ishga tushirish (ishlab chiqish):
    cd apps/api && uvicorn app.main:app --reload --port 8000

Hujjat: http://localhost:8000/api/docs  (avtomatik, qo'lda yozilmaydi)

TUZILMA:
    app/core/       sozlama, xavfsizlik, xato shakli
    app/api/v1/     HTTP qatlami - router'lar, mantiq YO'Q
    app/schemas/    so'rov/javob modellari (frontend types.ts nusxasi)
    app/services/   MANTIQ shu yerda: foydalanuvchilar, quvur, integratsiyalar

Qoida: router'da mantiq yozilmaydi, `services/` da HTTP haqida bilinmaydi.
Shu tufayli mantiqni test qilish uchun HTTP kerak emas va integratsiya
qo'shganda router'ga tegilmaydi.
"""

from __future__ import annotations

import logging

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api.deps import get_user_store
from .api.v1 import router as v1_router
from .core import errors
from .core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# Hujjat manzillari ATAYLAB `/api/` ostida.
#
# Sabab: nginx (apps/web/deploy/nginx.container.conf) FAQAT `location /api/`
# ni backend'ga uzatadi, qolgan hamma narsa SPA ga ketadi. Default `/docs`
# bilan qoldirsak Swagger tashqaridan OCHILMAYDI va nginx'ga alohida
# location qo'shishga to'g'ri kelardi. Shu bitta qaror bilan deploy
# sozlamasiga umuman tegilmaydi.
#
# Swagger UI ning O'ZI ham muammo: FastAPI uni default holda
# `cdn.jsdelivr.net` dan yuklaydi. Ichki tarmoqda internet yo'q va sahifa
# BO'SH ochiladi. Shuning uchun `docs_url=None` va quyida o'z route'imiz -
# u fayllarni LOKAL beradi, ular bo'lmasa CDN ga qaytadi (ishlab chiqish
# mashinasida internet bor).
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Venera AI - web ilova uchun backend.",
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

#: Swagger UI fayllari shu papkada bo'lsa lokal beriladi (Dockerfile ularni
#: build paytida yuklab oladi). Bo'lmasa - CDN.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_SWAGGER_LOCAL = (_STATIC_DIR / "swagger-ui-bundle.js").exists()

if _SWAGGER_LOCAL:
    app.mount("/api/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/api/docs", include_in_schema=False)
def swagger_ui() -> HTMLResponse:
    """Swagger UI. Fayllar lokal bo'lsa internetsiz ham ochiladi."""
    base = "/api/static" if _SWAGGER_LOCAL else "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5"
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title=f"{settings.app_name} - hujjat",
        swagger_js_url=f"{base}/swagger-ui-bundle.js",
        swagger_css_url=f"{base}/swagger-ui.css",
        # Default favicon ham tashqi manzildan keladi - uni umuman so'ramaymiz.
        swagger_favicon_url="data:,",
    )

# FastAPI ning default `{"detail": ...}` shakli frontend kutgan shaklga MOS
# KELMAYDI - shuning uchun handler'lar almashtiriladi. Tafsilot: core/errors.py
errors.install(app)

# CORS odatda KERAK EMAS: nginx frontend va `/api` ni BIR XIL originda
# ko'rsatadi. Faqat frontend boshqa domenda ishlasa `cors_origins` to'ldiriladi.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(v1_router)


@app.get("/api/health", tags=["service"])
@app.get("/health", tags=["service"], include_in_schema=False)
def health() -> dict:
    """Holat. Konteyner orkestratori va IT xodimi uchun.

    `warnings` - ishga tushdi, lekin e'tibor talab qiladigan holatlar.
    Bular server KO'TARILISHINI to'smaydi: buzuq config tufayli xizmat
    umuman ishlamagandan ko'ra, ishlab turib muammoni AYTGANI yaxshiroq.
    """
    store = get_user_store()
    warnings: list[str] = []
    if settings.secret_is_default:
        warnings.append("secret_key default qiymatda - PRODUCTION uchun o'zgartiring")
    if len(store) == 0:
        warnings.append(f"foydalanuvchilar yuklanmadi ({settings.users_file})")

    return {
        "status": "degraded" if warnings else "ok",
        "version": settings.version,
        "users": len(store),
        "warnings": warnings,
    }

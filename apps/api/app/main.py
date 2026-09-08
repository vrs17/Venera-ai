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
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api.deps import get_user_store
from .api.v1 import router as v1_router
from .core import errors
from .core.config import settings
from .services.users import example_password_hashes

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
# Swagger UI ning O'ZI ham muammo, va ikki qatlamda:
#
#   1. FastAPI uni default holda `cdn.jsdelivr.net` dan yuklaydi. Ichki
#      tarmoqda internet yo'q. Shuning uchun fayllar `app/static/` da turadi.
#   2. Frontend nginx butun saytga qattiq CSP qo'yadi - `script-src 'self'`.
#      FastAPI ning `get_swagger_ui_html()` funksiyasi INLINE `<script>` yozadi,
#      CSP esa uni bloklaydi: bundle yuklanadi, ishga tushirilmaydi, sahifa
#      BO'SH ochiladi. curl 200 qaytaradi va muammo ko'rinmaydi.
#
# Shuning uchun sahifa quyida QO'LDA yig'iladi: inline skript YO'Q, ishga
# tushirish kodi `static/swagger-init.js` da. CSP ni bo'shashtirish kerak emas.
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Venera AI - web ilova uchun backend.",
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

#: Swagger UI fayllari shu papkada turadi. Yuklab olish:
#: docs/deploy-api.md, "Swagger fayllari" bo'limi.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_SWAGGER_FILES = ("swagger-ui-bundle.js", "swagger-ui.css", "swagger-init.js")
_SWAGGER_MISSING = [f for f in _SWAGGER_FILES if not (_STATIC_DIR / f).exists()]

# Papka bo'lmasa `StaticFiles` ISHGA TUSHISHDA yiqiladi va butun API
# ko'tarilmaydi - hujjat sahifasi tufayli xizmatni yo'qotish mantiqsiz.
_STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/static", StaticFiles(directory=_STATIC_DIR), name="static")

#: Sahifada INLINE SKRIPT YO'Q - CSP `script-src 'self'` uni bloklardi.
_DOCS_PAGE = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/api/static/swagger-ui.css">
<link rel="icon" href="data:,">
</head>
<body>
<div id="swagger-ui"></div>
<script src="/api/static/swagger-ui-bundle.js"></script>
<script src="/api/static/swagger-init.js"></script>
</body>
</html>"""


@app.get("/api/docs", include_in_schema=False)
def swagger_ui() -> HTMLResponse:
    """Swagger UI. Internetsiz ishlaydi va qattiq CSP ostida ham ochiladi."""
    if _SWAGGER_MISSING:
        # ATAYLAB xato sahifasi, BO'SH sahifa emas. CDN ga qaytish MA'NOSIZ:
        # CSP `script-src 'self'` tashqi manbani baribir bloklaydi, natijada
        # foydalanuvchi sababsiz oq ekran ko'rardi.
        log.error("Swagger fayllari yetishmayapti: %s", ", ".join(_SWAGGER_MISSING))
        return HTMLResponse(
            "<h1>Swagger fayllari yo'q</h1>"
            f"<p>Yetishmayapti: <code>{', '.join(_SWAGGER_MISSING)}</code></p>"
            "<p>Yechim: <code>docs/deploy-api.md</code>, "
            "&laquo;Swagger fayllari&raquo; bo'limi.</p>"
            "<p>OpenAPI JSON ishlayapti: <a href=\"/api/openapi.json\">/api/openapi.json</a></p>",
            status_code=503,
        )
    return HTMLResponse(_DOCS_PAGE.format(title=f"{settings.app_name} - hujjat"))

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
    """Holat. Monitoring va IT xodimi uchun.

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

    # `users.example.yaml` git'da, undagi parollar esa README da OCHIQ yozilgan.
    # Uni nusxalab qoldirish eng oson va eng xavfli xato: tizim ishlaydi,
    # hech nima buzilmaydi, va parol allaqachon e'lon qilingan bo'ladi.
    # Buni AYTMASA hech kim sezmaydi - shu tekshiruv yo'qligi tufayli bir
    # marta jonli tizimda aynan shunday bo'lgan.
    demo = store.emails_using(
        example_password_hashes(settings.users_file.parent / "users.example.yaml")
    )
    if demo:
        warnings.append(
            "NAMUNA PAROLLARI ISHLATILMOQDA (" + ", ".join(demo) + ") - "
            "ular git'da ochiq yozilgan, DARHOL almashtiring: "
            "venv/bin/python -m app.tools.hash_password"
        )

    return {
        "status": "degraded" if warnings else "ok",
        "version": settings.version,
        "users": len(store),
        "warnings": warnings,
    }

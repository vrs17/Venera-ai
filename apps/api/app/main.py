"""Venera API - ilova nuqtasi.

Ishga tushirish (ishlab chiqish):
    cd apps/api && uvicorn app.main:app --reload --port 8000

Hujjat: http://localhost:8000/docs  (avtomatik, qo'lda yozilmaydi)

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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.deps import get_user_store
from .api.v1 import router as v1_router
from .core import errors
from .core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Venera AI - web ilova uchun backend.",
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


@app.get("/health", tags=["service"])
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

"""v1 API - barcha router'lar shu yerda yig'iladi.

Yangi bo'lim qo'shish: fayl yarating, `router` e'lon qiling va quyida bitta
qator qo'shing. `main.py` ga tegilmaydi.

Nima uchun `/v1` prefiksi: buzuvchi o'zgarish kerak bo'lganda `/v2` yonida
paydo bo'ladi va eski klientlar (masalan o'rnatilgan desktop ilova) ishlashda
davom etadi.
"""

from fastapi import APIRouter

from . import auth, chat, stt

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(chat.router)
router.include_router(stt.router)

__all__ = ["router"]

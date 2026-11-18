"""v1 API - barcha router'lar shu yerda yig'iladi.

Yangi bo'lim qo'shish: fayl yarating, `router` e'lon qiling va quyida bitta
qator qo'shing. `main.py` ga tegilmaydi.

Nima uchun `/v1` prefiksi: buzuvchi o'zgarish kerak bo'lganda `/v2` yonida
paydo bo'ladi va eski klientlar (masalan o'rnatilgan desktop ilova) ishlashda
davom etadi.
"""

from fastapi import APIRouter

from . import actions, auth, chat, chats, connectors, hrm, pro, stt, telegram, tts
from . import admin_users, reports
from . import admin, admin_engines, admin_osmap, admin_playground, admin_probe
from . import devices, meetings, voice
from . import assistant_extras
from . import slack

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(chat.router)
router.include_router(chats.router)
router.include_router(connectors.router)
router.include_router(actions.router)
router.include_router(pro.router)
router.include_router(stt.router)
# HRM (servis kaliti bilan): kechikish sababiga avtomatik qaror (`hrm.py`).
router.include_router(hrm.router)
router.include_router(tts.router)
router.include_router(telegram.router)
router.include_router(reports.router)
router.include_router(admin_users.router)
router.include_router(admin.router)
router.include_router(admin_engines.router)
# "Tizim xaritasi": xarita ma'lumoti (ichki promptlar - faqat ADMIN, statik fayl
# EMAS) va qadamlarni jonli serverda AYNI kod bilan sinash (`admin_probe.py`).
router.include_router(admin_osmap.router)
router.include_router(admin_probe.router)
# "Agent playground": agent bosqichlarining aniq kirishi, tahrirlab qayta ishga tushirish,
# modellarni solishtirish va regressiya sinovlari (`admin_playground.py`).
router.include_router(admin_playground.router)
# Barno xotirasi va platforma kalitlari - yuqoridagi xizmat ustidan proksi
# (`assistant_extras.py`). `/connectors` dan ALOHIDA: u yerda odamning
# HRM/CRM login tokenlari.
router.include_router(assistant_extras.router)
# Yig'ilish yozuvchisi (mobil ilova). Yo'llar DOIM ulangan, lekin eshik
# (`meetings_access`) `MEETINGS_ENABLED` o'chiq bo'lsa 404 qaytaradi - bayroq
# `.env` dan jonli o'qiladi, ya'ni yoqish uchun restart kerak emas.
router.include_router(meetings.router)
# Ovoz namunasi (spikerni ovozidan tanish, `services/meetings/voice.py`).
router.include_router(voice.router)
router.include_router(devices.router)
# Slack hisobini Barno hisobiga ulash - tasdiq sahifasining yo'llari (`slack.py`; Slack ilovasining
# o'zi HTTP emas, Socket Mode - `app/slack/`).
router.include_router(slack.router)

__all__ = ["router"]

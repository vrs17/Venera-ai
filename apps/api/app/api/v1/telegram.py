"""Telegram bot uchun hisobni ulash - mini app chaqiradi.

    POST /telegram/link     shu Telegram hisobi -> sessiyadagi Venera hisobi
    POST /telegram/unlink   uzish (mini app'dan chiqishda)
    POST /telegram/webhook  Telegram'ning o'zi xabar yuboradi (webhook rejimi)

ISBOT IKKITA, va ikkalasi ham kerak:

  * `Authorization` sessiyasi - "bu kim" (Venera hisobi);
  * `initData` IMZOSI - "bu Telegram hisobi aynan shu odamning qo'lida".
    Imzoni bot tokeni bilan faqat Telegram qo'ya oladi.

Faqat sessiya yetmaydi: unda klient istalgan Telegram `id` sini yuborib,
BOSHQA odamning bot chatini o'z hisobiga ulab olardi - ya'ni o'sha odamning
savollari va HR javoblari unikiga ketardi. Faqat imzo ham yetmaydi: u
Venera hisobi haqida hech narsa aytmaydi.

Bot chatida parol so'ralmaydi: u Telegram serverida suhbat tarixida qolardi.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Request

from ... import bot
from ...core.config import settings
from ...core.errors import bad_request, error_status
from ...schemas.auth import AuthUser
from ...schemas.telegram import TelegramLinkRequest, TelegramLinkResult, TelegramUnlinkResult
from ...services.integrations.telegram import InitDataError, verify_init_data
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])

#: Uzish uchun `initData` yoshi CHEKLANMAYDI (100 yil): imzo Telegram
#: hisobini baribir isbotlaydi, uzish esa faqat SHU sessiya egasining
#: ulanishiga tegadi - ya'ni eski satr bilan hech kimga zarar qilib bo'lmaydi.
_ANY_AGE = 100 * 365 * 86400


def _telegram_user(init_data: str, *, max_age: int, actor_id: int) -> int:
    if not settings.telegram_bot_token:
        raise error_status(501, "Telegram bot sozlanmagan")
    try:
        tg_user = verify_init_data(init_data, settings.telegram_bot_token, max_age=max_age)
    except InitDataError as exc:
        # Sabab faqat jurnalda: tashqariga "qaysi tekshiruv yiqildi" aytilmaydi.
        log.info("Telegram initData rad etildi (%s): %s", actor_id, exc)
        if exc.stale:
            raise bad_request("Telegram ma'lumoti eskirgan - ilovani yopib qayta oching") from exc
        raise bad_request("Telegram ma'lumoti tasdiqlanmadi") from exc
    return int(tg_user["id"])


@router.post("/link", response_model=TelegramLinkResult)
def link(body: TelegramLinkRequest, user: AuthUser = Depends(current_user)) -> TelegramLinkResult:
    """Bot chatini shu Venera hisobiga ulaydi (yoki muddatini yangilaydi).

    Mini app buni HAR ochilganda chaqiradi - ulanish muddati shu bilan
    yangilanadi (botdagi har savol ham yangilaydi). Yangi ulanishda bot
    "hisobingiz ulandi" deb yozadi.
    """
    tg_id = _telegram_user(body.initData, max_age=settings.telegram_init_max_age,
                           actor_id=user.actorId)
    result = bot.links.link(tg_id, user.actorId)
    if result != "refreshed":
        log.info("Telegram hisobi ulandi (%s): %s", user.actorId, result)
        bot.welcome(tg_id, user)
    return TelegramLinkResult(status=result, bot=bot.username() or None,
                              days=settings.telegram_link_days)


@router.post("/unlink", response_model=TelegramUnlinkResult)
def unlink(body: TelegramLinkRequest, user: AuthUser = Depends(current_user)) -> TelegramUnlinkResult:
    """Uzadi - faqat shu sessiya egasiga ulangan bo'lsa."""
    tg_id = _telegram_user(body.initData, max_age=_ANY_AGE, actor_id=user.actorId)
    removed = bot.links.unlink(tg_id, actor_id=user.actorId)
    if removed:
        log.info("Telegram hisobi uzildi (%s)", user.actorId)
    return TelegramUnlinkResult(unlinked=removed)


#: Telegram yangilanishi odatda bir necha KB. Undan kattasi - xato yoki suiiste'mol.
_WEBHOOK_MAX_BYTES = 1024 * 1024


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request) -> dict:
    """Telegram yuborgan yangilanish (webhook rejimi) - SESSIYASIZ.

    Kimligi `X-Telegram-Bot-Api-Secret-Token` sarlavhasi bilan tekshiriladi:
    sirni faqat Telegram biladi (`setWebhook` da berilgan). Sirsiz so'rov
    rad etiladi - aks holda har kim soxta "xabar" yuborib, bot nomidan
    boshqa odamning chatiga javob chiqarib olishi mumkin edi.

    Javob DARHOL qaytadi: xabar navbatga qo'yiladi, ishlanishi (15-40 s)
    Telegram'ni kutdirmaydi.
    """
    expected = bot.webhook_secret()
    given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise error_status(401, "Ruxsat yo'q")
    try:
        size = int(request.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    if size > _WEBHOOK_MAX_BYTES:
        raise error_status(413, "Yangilanish juda katta")
    try:
        update = await request.json()
    except ValueError as exc:
        raise bad_request("Yangilanish o'qilmadi") from exc
    if not isinstance(update, dict):
        raise bad_request("Yangilanish o'qilmadi")
    if not bot.feed(update):
        # Bot ishlamayapti (endigina ishga tushyapti) - Telegram keyin qayta yuboradi.
        raise error_status(503, "Bot hozir ishlamayapti")
    return {"ok": True}

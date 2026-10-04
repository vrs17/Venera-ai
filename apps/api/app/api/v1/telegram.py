"""Telegram bot uchun hisobni ulash - mini app chaqiradi.

    POST /telegram/link     shu Telegram hisobi -> sessiyadagi Venera hisobi
    POST /telegram/unlink   uzish (mini app'dan chiqishda)
    POST /telegram/session  ulangan Telegram hisobi -> yangi Venera sessiyasi
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

`/session` - TESKARI yo'nalish: ulanish allaqachon bor (u yuqoridagi ikki
isbot bilan yaratilgan), endi imzoning o'zi yetadi. Mini App tokenni
yo'qotganda (iOS WebView xotirasini tozalaydi, boshqa telefon) odamdan
parolni qayta so'ramaslik uchun.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ... import bot
from ...core.channels import CLIENT_CHANNELS, channel_of
from ...core.config import settings
from ...core.errors import bad_request, error_status, unauthorized
from ...core.security import create_token
from ...schemas.auth import AuthUser, LoginResponse
from ...schemas.telegram import (
    TelegramLinkRequest,
    TelegramLinkResult,
    TelegramSessionRequest,
    TelegramUnlinkResult,
)
from ...services.analytics import record_auth_event
from ...services.identities import Directory, Identity, IdentityStore
from ...services.integrations.telegram import InitDataError, verify_init_data
from ...services.reports import RateLimiter
from ...services.users import UserStore
from ..deps import current_user, get_identity_store, get_user_store
from .auth import _admit

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


# --- Telegram orqali kirish ---------------------------------------------------------

#: Sessiya uchun `initData` yoshi - ulashdagidan (`telegram_init_max_age`, 1 kun)
#: ancha QISQA. Mini App bu so'rovni ochilgan zahoti yuboradi, ya'ni yangi satr
#: soniyalar ichida keladi. Uzun muddat esa jurnalda yoki ekran rasmida qolgan
#: satrni bir kun davomida "parolsiz kirish kaliti" qilib qo'yardi.
_SESSION_MAX_AGE = 600

#: Bitta Telegram hisobidan daqiqasiga shuncha urinish. Mini App uni ochilganda
#: va sessiya 401 olganda bir martadan chaqiradi - chegaraga faqat buzilgan
#: klient yoki qo'lda takrorlash yetadi. Kalit - IMZODAN olingan `id`, ya'ni
#: boshqa odamning chegarasini "yeb qo'yib" bo'lmaydi.
_session_limiter = RateLimiter(limit=6, window=60)

#: Xabar ATAYLAB BITTA: imzo soxta, eskirgan, ulanmagan, muddati o'tgan - farqi
#: faqat jurnalda va `auth_events` da. Mini App baribir hammasida kirish
#: ekraniga o'tadi, tashqariga esa "bu Telegram hisobi ulangan" degan ma'lumot
#: chiqmaydi.
_MSG_NO_SESSION = "Telegram orqali kirib bo'lmadi - login va parol bilan kiring"


def _session_channel(request: Request) -> str:
    """Kanal: klient aytgani, aytmasa - `miniapp`.

    Imzolangan `initData` faqat Telegram Mini App ichida bo'ladi. Sarlavhasiz
    so'rov (eski build, `/tg-beta/` dagi `Referer` - `channels.py` uni tanimaydi)
    ham shu yerdan keladi - statistikada `api` bo'lib ketmasin.
    """
    declared = channel_of(request)
    return declared if declared in CLIENT_CHANNELS else "miniapp"


def _refuse(login: str | None, reason: str, channel: str, *, actor_id: int | None = None,
            ) -> HTTPException:
    """Rad etish: `auth_events` ga sabab bilan yoziladi, tashqariga - umumiy 401."""
    record_auth_event(login, False, method="telegram", channel=channel, reason=reason,
                      actor_id=actor_id)
    log.info("Telegram orqali kirish rad etildi (%s): %s", actor_id or "-", reason)
    return unauthorized(_MSG_NO_SESSION)


@router.post("/session", response_model=LoginResponse)
def session(
    body: TelegramSessionRequest,
    request: Request,
    store: UserStore = Depends(get_user_store),
    identities: IdentityStore = Depends(get_identity_store),
) -> LoginResponse:
    """Ulangan Telegram hisobi -> yangi Venera sessiyasi (parolsiz).

    ISBOT: Telegram imzosi (faqat Telegram yasaydi) + MAVJUD ulanish. Ulanishni
    faqat parol bilan kirgan sessiya va o'sha imzo birga yaratadi (`/link`),
    ya'ni bu yo'l parol bilan bir marta kirilgan joyni qayta ochadi, xolos.
    Chiqishda Mini App avval `/unlink` ni chaqiradi - shundan keyin bu yerda 401.

    Kirish qoidalari `/auth/login` niki: admin bloki (403), sessiya versiyasi
    ("hamma joydan chiqarish" dan keyingi token yangi versiya bilan), har
    urinish `auth_events` ga (`method="telegram"`). HRM/CRM ulanishlari bu yerda
    YANGILANMAYDI - parol yo'q; Keycloak tokeni o'lgan bo'lsa `GET /connectors`
    `expired` ko'rsatadi va odam parol bilan qayta kiradi.

    `async def` EMAS: fayllar va analitika ombori bloklaydi - threadpool'da.
    """
    channel = _session_channel(request)
    if not settings.telegram_bot_token:
        raise error_status(status.HTTP_501_NOT_IMPLEMENTED, "Telegram bot sozlanmagan")
    try:
        tg_user = verify_init_data(body.initData, settings.telegram_bot_token,
                                   max_age=_SESSION_MAX_AGE)
    except InitDataError as exc:
        raise _refuse(None, "tg_stale" if exc.stale else "tg_invalid", channel) from exc
    tg_id = int(tg_user["id"])

    wait = _session_limiter.take(tg_id)
    if wait is not None:
        # `auth_events` ga YOZILMAYDI: chegaraning maqsadi aynan shu jadvalni
        # takroriy urinishlar bilan to'ldirmaslik.
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Juda ko'p urinish - birozdan keyin qayta oching",
                            headers={"Retry-After": str(wait)})

    # `tg:<id>` - login o'rnida: kim urinayotgani admin jurnalida ko'rinsin
    # (Telegram `id` ulanishlar faylida ham turadi - yangi shaxsiy ma'lumot emas).
    tg_login = f"tg:{tg_id}"
    found, state = bot.links.lookup(tg_id)
    if found is None:
        raise _refuse(tg_login, "tg_link_expired" if state == "expired" else "tg_not_linked",
                      channel)
    actor_id = found.actor_id

    # `Depends` orqali kelgan omborlar (`deps.get_directory` emas): testlar va
    # `dependency_overrides` aynan shularni almashtiradi.
    stored = Directory(identities, store).by_actor_id(actor_id)
    if stored is None:
        # Hisob o'chirilgan. Ulanishni bot o'zi keyingi xabarda uzadi.
        raise _refuse(tg_login, "tg_unknown_actor", channel, actor_id=actor_id)
    if isinstance(stored, Identity):
        # Token `sub` i va admin qarorlari uchun login - `/auth/login` (SSO) dagidek.
        login, sso_login, subject = stored.username, stored.username, stored.subject
    else:
        # Zahira hisob (`users.yaml`). `/auth/login` u bilan kirishni o'chirgan
        # bo'lsa yoki parolni almashtirish talab qilinsa - parolsiz yo'l ham yopiq,
        # aks holda Telegram shu ikki qoidani aylanib o'tish yo'li bo'lardi.
        login, sso_login, subject = stored.email, None, stored.email
        if not settings.local_login_enabled:
            raise _refuse(login, "local_login_disabled", channel, actor_id=actor_id)
        if stored.password_change_required:
            raise _refuse(login, "password_change_required", channel, actor_id=actor_id)

    # Blok - 403 (sababi aytiladi: imzo + ulanish = to'g'ri parol bilan teng).
    verdict = _admit(stored.to_public(), sso_login, attempt=login, method="telegram",
                     channel=channel)
    if not bot.links.touch(tg_id, actor_id):
        # Tekshiruvdan keyin uzildi (odam chiqdi yoki admin "hamma joydan
        # chiqarish" ni bosdi) - tiriltirmaymiz.
        raise _refuse(tg_login, "tg_not_linked", channel, actor_id=actor_id)
    token, expires = create_token(subject, version=verdict.token_version)
    record_auth_event(login, True, method="telegram", channel=channel, actor_id=actor_id)
    log.info("Kirish (Telegram): actor_id %s", actor_id)
    return LoginResponse(
        token=token,
        tokenType="Bearer",
        expiresAt=expires.isoformat(),
        passwordChangeRequired=False,
        user=verdict.user,
    )


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

"""Telegram bot uchun hisobni ulash - mini app chaqiradi.

    POST /telegram/link     shu Telegram hisobi -> sessiyadagi Venera hisobi
    POST /telegram/unlink   uzish (mini app'dan chiqishda)
    POST /telegram/session  ulangan Telegram hisobi -> yangi Venera sessiyasi
    POST /telegram/webhook  Telegram'ning o'zi xabar yuboradi (webhook rejimi)

    BRB-Tech ID orqali birinchi kirish (2026-11-12) - brauzerda tasdiq, pastdagi bo'lim:
    POST /telegram/link-ticket          Mini App: imzo -> chipta va brauzer havolasi
    GET  /telegram/link-ticket/{t}      tasdiq sahifasi: kim kimga ulanyapti (sessiya bilan)
    POST /telegram/link-ticket/confirm  tasdiq sahifasi: "Ulash" (sessiya bilan)
    POST /telegram/link-ticket/claim    Mini App: chipta + imzo -> `pending` yoki sessiya

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
import time

from dataclasses import dataclass, replace

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

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
    TelegramTicket,
    TelegramTicketClaim,
    TelegramTicketClaimResult,
    TelegramTicketConfirm,
    TelegramTicketInfo,
    TelegramUnlinkResult,
)
from ...services.analytics import record_auth_event
from ...services.identities import Directory, Identity, IdentityStore
from ...services.integrations.telegram import InitDataError, verify_init_data
from ...services.link_tickets import TicketStore
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
_MSG_NO_SESSION = "Telegram orqali kirib bo'lmadi - BRB-Tech ID bilan kiring"


def _session_channel(request: Request) -> str:
    """Kanal: klient aytgani, aytmasa - `miniapp`.

    Imzolangan `initData` faqat Telegram Mini App ichida bo'ladi. Sarlavhasiz
    va `Referer` siz so'rov (eski build, `Referer` ni kesadigan WebView) ham
    shu yerdan keladi - statistikada `api` bo'lib ketmasin.
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
    kirgan sessiya va o'sha imzo birga yaratadi (`/link`, yoki brauzerdagi tasdiq -
    `/link-ticket/confirm`), ya'ni bu yo'l bir marta kirilgan joyni qayta ochadi, xolos.
    Chiqishda Mini App avval `/unlink` ni chaqiradi - shundan keyin bu yerda 401.

    Kirish qoidalari `/auth/login` niki: admin bloki (403), sessiya versiyasi
    ("hamma joydan chiqarish" dan keyingi token yangi versiya bilan), har
    urinish `auth_events` ga (`method="telegram"`). HRM/CRM ulanishlari bu yerda
    YANGILANMAYDI - parol ham, Keycloak sessiyasi ham yo'q: HRM muddati tugasa
    `GET /connectors` `expired` ko'rsatadi va odam uni vebda qayta ulaydi; CRM
    (odamga ko'rinmaydi) vebga BRB-Tech ID bilan keyingi kirishda yangilanadi.

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
    return _open_session(tg_id, store, identities, channel)


def _open_session(tg_id: int, store: UserStore, identities: IdentityStore, channel: str) -> LoginResponse:
    """Ulanish -> Venera sessiyasi, `/auth/login` qoidalari bilan. Imzo va chegaralar
    chaqiruvchida (`/session` - 600 s va daqiqasiga 6; `/link-ticket/claim` - chipta)."""
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


# --- BRB-Tech ID orqali ulash: brauzerda tasdiq (2026-11-12, ega so'rovi) -------------------
#
# Mini App ICHIDA Keycloak sahifasini ochib bo'lmaydi: Telegram Web va Desktop Mini App'ni
# iframe'da ochadi (Keycloak ramkaga ruxsat bermaydi, kirishni brauzerga bog'laydigan SameSite
# cookie iframe'da yo'qoladi), Android esa boshqa manzilni tashqi brauzerga chiqarib yuborishi
# mumkin. Shuning uchun - Slack'dagi kabi (`app/slack/link.py`):
#
#   1. Mini App chipta oladi (`/link-ticket`): KIM ekanini Telegram IMZOSI aytadi.
#   2. Havolani BRAUZERDA ochadi (`Telegram.WebApp.openLink`): `<SSO_APP_URL>/link/telegram?t=`.
#      Odam Barno'ga kiradi (BRB-Tech ID yoki login + parol) va tasdiq sahifasida "Ulash" ni
#      bosadi (`/link-ticket/confirm`) - ulanish SHU YERDA yoziladi, bot "ulandi" deydi.
#   3. Mini App chiptani so'rab turadi (`/link-ticket/claim`, O'Z imzosi bilan): tasdiqlangach
#      sessiya oladi - odam Telegram'ga qaytganda Barno ochiq turadi.
#
# NEGA TASDIQ: havolani boshqa odamga yuborib bo'ladi. Hamkasb uni ochib tasdiqsiz ulansa,
# YUBORUVCHINING Telegram'i HAMKASBNING hisobiga ulanardi va uning HR javoblari begona botga
# ketardi. Sahifa Telegram ismi va @username'ni ko'rsatadi va ogohlantiradi; kirishning o'zi
# hech narsani ulamaydi.

#: Chipta muddati: brauzer, BRB-Tech ID, ikki bosqichli tasdiq - yarim soat yetarli.
LINK_TICKET_TTL = 1800.0
#: Bitta Telegram hisobidan 10 daqiqada shuncha chipta (tugmani qayta-qayta bosish).
_ticket_limiter = RateLimiter(limit=10, window=600)
#: Mini App natijani har ~2.5 s da so'raydi; chegara faqat buzilgan klientga yetadi.
_claim_limiter = RateLimiter(limit=60, window=60)
#: Bitta umumiy xabar: chipta yo'q, eskirgan, ishlatilgan yoki boshqa Telegram hisobiniki.
_MSG_TICKET = "Ulash havolasi eskirgan yoki ishlatilgan - Telegram'da Barno'ni qayta oching"
_TICKET = Path(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class TgTicket:
    tg_id: int
    #: Telegram'dagi ism va @username - tasdiq sahifasida "kim ulanyapti" uchun (imzodan).
    name: str
    username: str
    created: float
    #: Tasdiqlagan Barno hisobi; `None` - hali tasdiqlanmagan.
    actor_id: int | None = None


TICKETS: TicketStore[TgTicket] = TicketStore(LINK_TICKET_TTL)


def _app_url() -> str:
    return (settings.sso_app_url or "").strip().rstrip("/")


def _signed_user(init_data: str) -> dict:
    """Imzo -> Telegram `user`. Yosh - ulashdagidek (`telegram_init_max_age`): Mini App
    ochilganiga ancha bo'lgan bo'lishi mumkin, chipta esa o'zi qisqa yashaydi."""
    try:
        return verify_init_data(init_data, settings.telegram_bot_token,
                                max_age=settings.telegram_init_max_age)
    except InitDataError as exc:
        log.info("Telegram ulash chiptasi: imzo rad etildi: %s", exc)
        if exc.stale:
            raise bad_request("Telegram ma'lumoti eskirgan - ilovani yopib qayta oching") from exc
        raise bad_request("Telegram ma'lumoti tasdiqlanmadi") from exc


def _too_many(wait: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                         detail="Juda ko'p urinish - birozdan keyin qayta urinib ko'ring",
                         headers={"Retry-After": str(wait)})


@router.post("/link-ticket", response_model=TelegramTicket)
def link_ticket(body: TelegramLinkRequest) -> TelegramTicket:
    """Mini App: "BRB-Tech ID bilan kirish". Imzo -> bir martalik chipta va brauzer havolasi."""
    if not settings.telegram_bot_token:
        raise error_status(status.HTTP_501_NOT_IMPLEMENTED, "Telegram bot sozlanmagan")
    app = _app_url()
    if not app:
        raise error_status(status.HTTP_501_NOT_IMPLEMENTED, "Barno manzili sozlanmagan (SSO_APP_URL)")
    tg_user = _signed_user(body.initData)
    tg_id = int(tg_user["id"])
    wait = _ticket_limiter.take(tg_id)
    if wait is not None:
        raise _too_many(wait)
    name = " ".join(str(tg_user.get(k) or "").strip() for k in ("first_name", "last_name")).strip()
    value = TICKETS.new(TgTicket(tg_id=tg_id, name=name[:120],
                                 username=str(tg_user.get("username") or "").strip()[:64],
                                 created=time.time()))
    log.info("Telegram ulash chiptasi yaratildi (tg %s)", tg_id)
    return TelegramTicket(ticket=value, url=f"{app}/link/telegram?t={value}", expiresIn=int(LINK_TICKET_TTL))


def _open_ticket(value: str) -> TgTicket:
    found = TICKETS.peek(value)
    if found is None or found.actor_id is not None:
        raise error_status(status.HTTP_404_NOT_FOUND, _MSG_TICKET)
    return found


@router.get("/link-ticket/{ticket}", response_model=TelegramTicketInfo)
def link_ticket_info(ticket: str = _TICKET, user: AuthUser = Depends(current_user)) -> TelegramTicketInfo:
    """Tasdiq sahifasi: kim kimga ulanyapti. Chiptani YOQMAYDI - sahifa qayta yuklansa ham ishlaydi."""
    found = _open_ticket(ticket)
    left = max(0, int(LINK_TICKET_TTL - (time.time() - found.created)))
    return TelegramTicketInfo(telegramName=found.name or None, telegramUsername=found.username or None,
                              accountName=user.fullName, accountLogin=user.email, expiresIn=left)


@router.post("/link-ticket/confirm", response_model=TelegramLinkResult)
def link_ticket_confirm(body: TelegramTicketConfirm, request: Request,
                        user: AuthUser = Depends(current_user)) -> TelegramLinkResult:
    """"Ulash": Telegram hisobi (chiptadagi, imzodan) shu sessiya egasiga ulanadi. Chipta
    "tasdiqlangan" bo'lib qoladi - uni endi faqat O'SHA Telegram hisobi yig'ib oladi (`claim`)."""
    found = _open_ticket(body.ticket)
    if not TICKETS.swap(body.ticket, found, replace(found, actor_id=user.actorId)):
        raise error_status(status.HTTP_404_NOT_FOUND, _MSG_TICKET)
    result = bot.links.link(found.tg_id, user.actorId)
    log.info("Telegram hisobi brauzerda ulandi (%s, tg %s): %s", user.actorId, found.tg_id, result)
    if result != "refreshed":
        bot.welcome(found.tg_id, user)
    record_auth_event(user.email, True, method="tg_link", channel=channel_of(request), actor_id=user.actorId)
    return TelegramLinkResult(status=result, bot=bot.username() or None, days=settings.telegram_link_days)


@router.post("/link-ticket/claim", response_model=TelegramTicketClaimResult)
def link_ticket_claim(
    body: TelegramTicketClaim,
    request: Request,
    store: UserStore = Depends(get_user_store),
    identities: IdentityStore = Depends(get_identity_store),
) -> TelegramTicketClaimResult:
    """Mini App: tasdiqlandimi. Chipta va imzo BITTA Telegram hisobiniki bo'lishi shart (boshqa
    odamning chiptasi - eskirgan bilan bir xil 404). Tasdiqlangach chipta yonadi va sessiya
    beriladi - qoidalar `/session` niki (blok, sessiya versiyasi, `auth_events`)."""
    channel = _session_channel(request)
    if not settings.telegram_bot_token:
        raise error_status(status.HTTP_501_NOT_IMPLEMENTED, "Telegram bot sozlanmagan")
    tg_id = int(_signed_user(body.initData)["id"])
    wait = _claim_limiter.take(tg_id)
    if wait is not None:
        raise _too_many(wait)
    found = TICKETS.peek(body.ticket)
    if found is None or found.tg_id != tg_id:
        raise error_status(status.HTTP_404_NOT_FOUND, _MSG_TICKET)
    if found.actor_id is None:
        return TelegramTicketClaimResult(status="pending")
    if TICKETS.pop(body.ticket) != found:
        raise error_status(status.HTTP_404_NOT_FOUND, _MSG_TICKET)
    return TelegramTicketClaimResult(status="ready", session=_open_session(tg_id, store, identities, channel))


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

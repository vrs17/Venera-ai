"""Barno xotirasi va platforma kalitlari - yuqoridagi xizmat ustidan proksi.

    GET    /assistant/memory                       odamning uzoq muddatli xotirasi
    DELETE /assistant/memory/{item_id}             bitta bandni unutish
    DELETE /assistant/memory?confirm=forget-all    HAMMASINI unutish
    GET    /assistant/platforms                    faqat HRM qatori (eski klientlar uchun)
    PUT    /assistant/platforms/{platform_id}      {"enabled": true|false} - faqat `hrm`

MA'LUMOT BU YERDA SAQLANMAYDI. Xotira ham, kalitlar ham yuqoridagi xizmatda
(HR Assistant 3.3, `/api/memory`, `/api/connectors`) `(ilova, user_id)`
bo'yicha turadi. Bu fayl faqat proksi: brauzer -> Barno -> xizmat.

KIMLIK FAQAT SERVERDAN: `chat.assistant_user_id(user)` = `venera:{actorId}`,
chat, suhbatlar tarixi va amallar bilan AYNAN bir xil kalit. So'rovdagi
`user_id` (so'rov satrida yoki tanada) e'tiborga OLINMAYDI - aks holda
boshqa odamning xotirasini o'qish yoki o'chirish bitta parametr bo'lardi.

"CONNECTORS" EMAS, "PLATFORMS": bizning `/api/v1/connectors` - odamning
HRM LOGIN tokeni ("+" menyusi). Xizmatning `/api/connectors` i esa
"Barno shu manbadan foydalansinmi" kalitlari. Bir xil nom ikki xil narsani
anglatmasin deb bizda ular `platforms`.

PLATFORMALARDAN FAQAT HRM QOLDI (2026-11-12, ega qarori). Xizmat ro'yxatida
yana CRM va vaqtinchalik namoyish manbalari (DWH, Biznes 24/7, Superapp,
qo'llanmalar, Biznes Help) bo'lishi mumkin - ular odamga ko'rsatilmaydi va
ularning kaliti almashtirilmaydi: ro'yxat `USER_PLATFORMS` gacha qisqartiriladi,
boshqa `id` ga `PUT` esa xizmatga BORMASDAN 404 `platform_not_found` oladi. Bu
ikki yo'lni eski klientlar (mobil ilova) hali chaqiradi - shuning uchun qoldi.

XOTIRA MATNI JURNALGA YOZILMAYDI: faqat kalitlar va soni. Xato matnida ham
xizmat javobining tanasi yo'q (`AssistantClient._json(quiet=True)`).

"HAMMASINI UNUTISH" QAYTARIB BO'LMAYDI, shuning uchun aniq tasdiq so'raladi
(`?confirm=forget-all`): umumiy `DELETE` yordamchisi yoki tasodifiy so'rov
xotirani o'chirib yubormasin. Tasdiqsiz so'rov xizmatga BORMAYDI.
"""

from __future__ import annotations

import logging

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from ...core.config import settings
from ...schemas.assistant_extras import (
    MemoryDeleted, MemoryItem, MemoryList, Platform, PlatformList, PlatformToggle,
)
from ...schemas.auth import AuthUser
from ...services.integrations.assistant import AssistantError
from ...services.integrations.connectors import USER_PLATFORMS
from ...services.reports import RateLimiter
from . import chat as _chat
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/assistant", tags=["assistant"])

#: "Hammasini unutish" tasdig'i. `true` emas, aniq ibora: umumiy yordamchi
#: `?confirm=true` ni boshqa joydan ko'chirib qo'ysa ham xotira o'chmasin.
FORGET_ALL = "forget-all"

#: Chegaralar (odam bo'yicha, sirpanuvchi oyna). Sozlamalar ekrani soniyada
#: bir-ikki so'rov beradi; bundan ko'pi - tsikl yoki skript, va u yuqoridagi
#: xizmatni (bitta LLM turgan server) band qilmasligi kerak. "Hammasini
#: unutish" alohida va qattiq: qaytarib bo'lmaydigan amal tez takrorlanmaydi.
READ_LIMIT = (60, 60.0)        # GET xotira / platformalar: 60 ta / daqiqa
WRITE_LIMIT = (30, 60.0)       # bitta bandni o'chirish, kalitni almashtirish: 30 / daqiqa
FORGET_ALL_LIMIT = (5, 3600.0)  # hammasini unutish: 5 / soat

_read = RateLimiter(*READ_LIMIT)
_write = RateLimiter(*WRITE_LIMIT)
_forget_all = RateLimiter(*FORGET_ALL_LIMIT)

_ITEM_ID = Path(max_length=128, description="Xotira bandi kaliti (`GET /assistant/memory` dagi `id`)")
_PLATFORM_ID = Path(max_length=40, description="Platforma kaliti: faqat `hrm`")

#: Foydalanuvchiga ko'rinadigan xabarlar - `code` bo'yicha. UI matnni o'zi
#: tarjima qiladi (`code` ga qarab), bu - zahira. Ichki manzil va sir bu
#: yerga HECH QACHON tushmaydi.
_MESSAGES = {
    "invalid_id": "Kalit yaroqsiz",
    "confirm_required": f"Hammasini unutish uchun tasdiq kerak (confirm={FORGET_ALL})",
    "memory_not_found": "Bu xotira bandi topilmadi - u allaqachon o'chirilgan bo'lishi mumkin",
    "platform_not_found": "Bunday platforma yo'q",
    "rate_limited": "So'rovlar ko'p - birozdan keyin qayta urinib ko'ring",
    "not_configured": "Barno xizmati hali sozlanmagan",
    "upstream_unavailable": "Barno xizmati hozir band yoki ulanib bo'lmadi, birozdan keyin qayta urinib ko'ring",
    "upstream_timeout": "Barno xizmati javob bermadi (vaqt tugadi)",
    "upstream_error": "Barno xizmati javob bermadi",
}


class AssistantProblem(HTTPException):
    """Xato javobi + mashina o'qiydigan `code` (`core/errors.error_response`
    `extra` ni yagona shaklga qo'shadi): UI xabarni matndan emas, koddan
    tanlaydi va 4 tilda ko'rsatadi."""

    def __init__(self, status: int, code: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(status_code=status, detail=_MESSAGES[code], headers=headers)
        self.code = code
        self.extra = {"code": code}


def _limit(limiter: RateLimiter, user: AuthUser) -> None:
    """Chegara: oshsa 429 `rate_limited` + `Retry-After` - xizmatga bormasdan."""
    wait = limiter.take(int(user.actorId))
    if wait is not None:
        raise AssistantProblem(429, "rate_limited", headers={"Retry-After": str(wait)})


#: Xizmat tomonidagi nosozlik: so'rov bajarilmagan (yoki natijasi noma'lum, lekin
#: amal idempotent). Bunday urinish odamning chegarasidan QAYTARILADI.
_UPSTREAM_FAULTS = frozenset({502, 503, 504})


def _run_limited(limiter: RateLimiter, user: AuthUser, run: Callable[[], Any]) -> Any:
    """`_limit` + chaqiruv; xizmat nosozligida (502/503/504) band qilingan joy
    qaytariladi. NEGA: "Hammasini unutish" soatiga 5 ta - agent qayta ishga
    tushayotganda 5 ta 504 odamni bir soatga maxfiylik amalidan mahrum qilardi.
    Amallar idempotent (o'chirilgan narsani yana o'chirish, kalitni yana bir xil
    qo'yish), shuning uchun 504 dan keyingi qayta urinish xavfsiz. Bizning rad
    (400/404/422) esa chegarani yeydi - aks holda tsikl uni cheksiz urardi."""
    _limit(limiter, user)
    try:
        return run()
    except AssistantProblem as exc:
        if exc.status_code in _UPSTREAM_FAULTS:
            limiter.give_back(int(user.actorId))
        raise


def _problem(exc: AssistantError, *, not_found: str | None) -> AssistantProblem:
    """`AssistantError` -> bizning xato. Yuqoridagi xizmatning har xatosi
    502/503/504 ga tushadi; 404 faqat bitta narsani o'chirish/almashtirishda
    ma'noli (`not_found` kodi bilan) - ro'yxat yo'lidagi 404 esa "xizmatda bu
    yo'l hali yo'q" degani, ya'ni xizmat xatosi (502).

    `reason` yo'q 400 - BIZNING tekshiruv (kalit yaroqsiz), xizmatga borilmagan.
    """
    reason = getattr(exc, "reason", None)
    if exc.status == 400 and reason is None:
        return AssistantProblem(400, "invalid_id")
    if exc.status == 501:
        return AssistantProblem(503, "not_configured")
    if exc.status == 404 and not_found:
        return AssistantProblem(404, not_found)
    if exc.status == 503:
        return AssistantProblem(503, "upstream_unavailable")
    if exc.status == 504:
        return AssistantProblem(504, "upstream_timeout")
    return AssistantProblem(502, "upstream_error")


def _run(call: Callable[[float], dict[str, Any]], user: AuthUser, what: str, *,
         not_found: str | None = None) -> dict[str, Any]:
    """Xizmatga boradi (sozlamalar chegarasi bilan); xatoni jurnalga yozib,
    yagona shaklga o'giradi. Jurnalda faqat status va ichki sabab - xotira
    yo'llarida xato matni xizmat tanasisiz (`quiet`)."""
    try:
        return call(float(settings.hrm_assistant_settings_timeout))
    except AssistantError as exc:
        problem = _problem(exc, not_found=not_found)
        log.warning("Barno %s (actor %s) [%s] -> %s %s: %s", what, user.actorId,
                    getattr(exc, "reason", None) or "-", problem.status_code, problem.code, exc)
        raise problem from exc


def _user_id(user: AuthUser) -> str:
    # `chat.py`, `chats.py`, `actions.py` dagi bilan AYNAN bir xil kalit:
    # xotira chatda shu id bilan yoziladi, shu id bilan o'qiladi.
    return _chat.assistant_user_id(user)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _time(value: Any) -> str | None:
    # Xizmat "vaqt yo'q" ni `""` bilan ham beradi (CRM tartibi) - UI uchun bitta `null`.
    return value if isinstance(value, str) and value.strip() else None


def normalize_memory(result: dict[str, Any]) -> MemoryList:
    """Xizmat javobi -> `MemoryList`. Kalitsiz yoki matnsiz band TASHLANADI
    (ko'rsatib bo'lmaydi, o'chirib ham bo'lmaydi); qolganining yetishmagan
    maydonlari bo'sh. `count` - haqiqatda qaytarilgan bandlar soni."""
    items: list[MemoryItem] = []
    raw = result.get("items")
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        item_id, text = entry.get("id"), entry.get("text")
        # Bo'sh yoki faqat bo'shliqdan iborat matn ham tashlanadi - web (`toMemoryItem`)
        # ham shunday qiladi: aks holda `count` (3) va ekrandagi ro'yxat (1) farq qilib,
        # ko'rinmaydigan bandni o'chirishning ham yo'li bo'lmasdi.
        if not isinstance(item_id, str) or not item_id or not isinstance(text, str) \
                or not text.strip():
            continue
        items.append(MemoryItem(
            id=item_id, text=text, kind=_text(entry.get("kind")), source=_text(entry.get("source")),
            created_at=_time(entry.get("created_at")), updated_at=_time(entry.get("updated_at")),
        ))
    return MemoryList(items=items, count=len(items))


def normalize_deleted(result: dict[str, Any]) -> MemoryDeleted:
    raw = result.get("deleted")
    deleted = [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
    status = result.get("status")
    if not isinstance(status, str) or not status:
        status = "deleted" if deleted else "empty"
    return MemoryDeleted(deleted=deleted, status=status)


def normalize_platform(entry: Any) -> Platform | None:
    """Bitta platforma. `enabled` xizmat bermasa - `available AND user_enabled`
    (xizmat hujjatidagi ta'rif)."""
    if not isinstance(entry, dict):
        return None
    platform_id = entry.get("id")
    if not isinstance(platform_id, str) or not platform_id:
        return None

    def flag(key: str, default: bool) -> bool:
        value = entry.get(key)
        return value if isinstance(value, bool) else default

    available = flag("available", True)
    user_enabled = flag("user_enabled", True)
    return Platform(
        id=platform_id,
        name=_text(entry.get("name")) or platform_id,
        description=_text(entry.get("description")),
        kind=_text(entry.get("kind")),
        needs_login=flag("needs_login", False),
        available=available,
        user_enabled=user_enabled,
        enabled=flag("enabled", available and user_enabled),
    )


def normalize_platforms(result: dict[str, Any]) -> PlatformList:
    """Xizmatning `connectors` ro'yxati -> bizning `platforms`: FAQAT odam
    boshqaradigan platformalar (`USER_PLATFORMS` - HRM). CRM va namoyish
    manbalari xizmat ro'yxatida bo'lsa ham tashlanadi (modul izohi)."""
    raw = result.get("connectors")
    items = raw if isinstance(raw, list) else []
    return PlatformList(platforms=[p for p in map(normalize_platform, items)
                                   if p is not None and p.id in USER_PLATFORMS])


# --- xotira -----------------------------------------------------------------------


@router.get("/memory", response_model=MemoryList)
def list_memory(response: Response, user: AuthUser = Depends(current_user)) -> MemoryList:
    """Barno shu odam haqida eslab qolgan hamma narsa - "Xotira" ekrani uchun.

    `async def` EMAS: klient bloklaydigan `urllib` ishlatadi, FastAPI oddiy
    `def` ni threadpool'da bajaradi (`chats.py` dagi kabi)."""
    _limit(_read, user)
    result = _run(
        lambda timeout: _chat._assistant.list_memory(user_id=_user_id(user), timeout=timeout),
        user, "xotira ro'yxati",
    )
    # Shaxsiy ma'lumot: brauzer yoki oraliq proksi keshlamasin.
    response.headers["Cache-Control"] = "private, no-store"
    return normalize_memory(result)


@router.delete("/memory/{item_id}", response_model=MemoryDeleted)
def forget_item(item_id: str = _ITEM_ID, user: AuthUser = Depends(current_user)) -> MemoryDeleted:
    """Bitta bandni butunlay unutish. Yo'q yoki boshqa odamniki - bir xil 404
    (`memory_not_found`): boshqa odamning kaliti borligini ham bilib bo'lmasin."""
    result = _run_limited(_write, user, lambda: _run(
        lambda timeout: _chat._assistant.delete_memory_item(
            item_id, user_id=_user_id(user), timeout=timeout),
        user, "xotira bandini o'chirish", not_found="memory_not_found",
    ))
    deleted = normalize_deleted(result)
    log.info("Xotira bandi o'chirildi (actor %s): %s -> %s", user.actorId, item_id, deleted.status)
    return deleted


@router.delete("/memory", response_model=MemoryDeleted)
def forget_all(
    confirm: str | None = Query(
        None, max_length=32,
        description=f"Aniq `{FORGET_ALL}` bo'lishi shart - aks holda 400 `confirm_required`"),
    user: AuthUser = Depends(current_user),
) -> MemoryDeleted:
    """HAMMASINI unutish (CRM dan o'rganilgan tartib ham). Suhbatlarga tegmaydi.

    Tasdiq chegaradan OLDIN tekshiriladi: tasdiqsiz xato so'rov soatlik 5 ta
    urinishni yeb qo'ymasin."""
    if confirm != FORGET_ALL:
        raise AssistantProblem(400, "confirm_required")
    result = _run_limited(_forget_all, user, lambda: _run(
        lambda timeout: _chat._assistant.clear_memory(user_id=_user_id(user), timeout=timeout),
        user, "xotirani tozalash",
    ))
    deleted = normalize_deleted(result)
    log.info("Xotira tozalandi (actor %s): %d ta band, %s", user.actorId, len(deleted.deleted),
             deleted.status)
    return deleted


# --- platformalar -----------------------------------------------------------------


@router.get("/platforms", response_model=PlatformList)
def list_platforms(user: AuthUser = Depends(current_user)) -> PlatformList:
    """Odam boshqaradigan platformalar - faqat HRM qatori (`normalize_platforms`)."""
    _limit(_read, user)
    result = _run(
        lambda timeout: _chat._assistant.list_platforms(user_id=_user_id(user), timeout=timeout),
        user, "platformalar ro'yxati",
    )
    return normalize_platforms(result)


@router.put("/platforms/{platform_id}", response_model=Platform)
def set_platform(body: PlatformToggle, platform_id: str = _PLATFORM_ID,
                 user: AuthUser = Depends(current_user)) -> Platform:
    """Eski klientlar uchun qoldirilgan (mobil ilova): kalitlar olib tashlangan -
    ULANGAN DEGANI ISHLATILADI. So'rov qabul qilinadi, lekin xizmatga har doim
    `enabled: true` yuboriladi: eski klient HRM ni o'chirib qo'ya olmaydi (uni qayta
    yoqadigan joy endi yo'q), ilgari o'chirilgan bo'lsa esa shu so'rov uni qayta
    yoqadi. Javob - platformaning YANGI holati: server o'chirgan platforma
    (`available: false`) baribir `enabled: false` qoladi.

    Boshqa har qanday `id` (CRM, namoyish manbalari, notanish yoki yaroqsiz
    nom) - 404 `platform_not_found`, xizmatga BORMASDAN va chegarani yemasdan:
    eski klient CRM ni yoki olib tashlangan manbani o'chirib qo'ya olmasin."""
    if platform_id not in USER_PLATFORMS:
        raise AssistantProblem(404, "platform_not_found")
    result = _run_limited(_write, user, lambda: _run(
        lambda timeout: _chat._assistant.set_platform(
            platform_id, user_id=_user_id(user), enabled=True, timeout=timeout),
        user, "platforma kaliti", not_found="platform_not_found",
    ))
    platform = normalize_platform(result)
    if platform is None:
        # Xizmat 200 berdi-yu, platformani qaytarmadi - natija noma'lum.
        log.warning("Barno platforma kaliti (actor %s): javobda platforma yo'q", user.actorId)
        raise AssistantProblem(502, "upstream_error")
    log.info("Platforma kaliti (actor %s): %s user_enabled=%s enabled=%s", user.actorId,
             platform.id, platform.user_enabled, platform.enabled)
    return platform


def reset_limits() -> None:
    """Testlar uchun: chegaralarni tozalaydi."""
    for limiter in (_read, _write, _forget_all):
        limiter.reset()

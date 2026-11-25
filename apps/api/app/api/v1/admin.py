"""Admin panel API - FAQAT ADMIN roli.

    GET   /admin/overview         KPI, faollik, kanallar, yo'nalishlar, dvigatellar, javob vaqti, ...
    GET   /admin/turns            savollar: filtrlar (`engine=v1|v2|v3|v4|v5|default` ham), kursor bilan
    GET   /admin/turns/{id}       bitta savolning to'liq izi
    GET   /admin/chats            suhbatlar (`chat_id` bo'yicha guruhlangan)
    GET   /admin/reports          xabarlar (shikoyatlar) qutisi
    GET   /admin/reports/{id}     bitta xabar, suhbat nusxasi bilan
    PATCH /admin/reports/{id}     holat / admin izohi - auditga yoziladi
    GET   /admin/usage            tashqi xizmatlar: so'rovlar, xatolar, p50/p95, birliklar
    GET   /admin/system           tashxis, sozlamalar, ombor hajmi, audit jurnali
    GET   /admin/search?q=        foydalanuvchi, savol, xabar - buyruqlar oynasi (⌘K)
    GET   /admin/me               kim kirgan + ko'rilmagan xabarlar soni (menyu nishoni)

HUQUQ ROUTERNING O'ZIDA, har endpointda emas. Bu sahifalar odamlarning
savollari va javoblarini TO'LIQ ko'rsatadi - tekshiruvni bitta yangi
endpointda unutish butun suhbatlar tarixini har bir xodimga ochib
qo'yardi. Router darajasidagi bog'liqlik esa bu yerga qo'shilgan har
endpointni o'zi himoyalaydi.

MANTIQ BU YERDA YO'Q: SQL va hisob-kitob `services/analytics/queries.py`
da, foydalanuvchilar katalogi va audit - `services/admin_users.py` da.
Bu fayl faqat parametrlarni o'qiydi va xatolarni HTTP kodiga o'giradi.

`async def` EMAS: SQLite bloklaydi, FastAPI oddiy `def` ni threadpool'da
bajaradi va voqealar sikli bo'sh qoladi.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3

from typing import Any, Iterator

from fastapi import APIRouter, Depends, Path, Query

from ...core.channels import normalize as normalize_channel
from ...core.config import settings
from ...core.errors import error_status
from ...schemas.admin import (
    AdminMe, AdminOverview, AdminSearch, AdminSystem, AdminUsage, ChatPage, ReportDetail,
    ReportPage, ReportUpdate, TurnDetail, TurnPage,
)
from ...schemas.auth import AuthUser
from ...services import admin_users, analytics
from ...services.analytics import queries
from ...services.analytics.queries import KEEP, QueryError, TurnFilter
from ..deps import get_identity_store, get_user_store, require_roles

log = logging.getLogger(__name__)

#: BITTA nusxa: router darajasida ham, adminning o'zi kerak bo'lgan
#: endpointda ham shu obyekt - FastAPI bir so'rovda uni bir marta bajaradi.
admin_only = require_roles("ADMIN")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_only)])

_STATUS_PATTERN = "^(" + "|".join(queries.TURN_STATUSES) + ")$"
_ENGINE_PATTERN = "^(" + "|".join(queries.TURN_ENGINES) + ")$"
_REPORT_PATTERN = "^(" + "|".join(queries.REPORT_STATUSES) + ")$"

# Bir necha endpointda takrorlanadigan parametrlar (`chats.py` dagi `_CHAT_ID` kabi).
_FROM = Query(None, alias="from", max_length=64,
              description="Oraliq boshi: ISO-8601, `YYYY-MM-DD` yoki epoch")
_TO = Query(None, alias="to", max_length=64,
            description="Oraliq oxiri (o'zi kirmaydi); faqat sana bo'lsa - shu kun ham kiradi")
_CHANNEL = Query(None, max_length=32,
                 description="web | miniapp | bot | desktop | api; bo'sh yoki `all` - hammasi")
_CURSOR = Query(None, max_length=512, description="Oldingi javobdagi `nextCursor`")
_LIMIT = Query(50, ge=1, le=100, description="Sahifa hajmi")
_SEARCH = Query(None, max_length=200,
                description="Savol, javob, ism yoki login bo'yicha; kalit (id) - aynan")


@contextlib.contextmanager
def _checked() -> Iterator[None]:
    """Noto'g'ri parametr -> 422, ombor o'qilmasa -> 503.

    503, 500 emas: ombor band yoki disk to'la - bu vaqtinchalik holat, va
    admin "qayta urinib ko'ring" degan xabarni ko'rishi kerak.
    """
    try:
        yield
    except QueryError as exc:
        raise error_status(422, str(exc)) from exc
    except sqlite3.Error as exc:
        log.error("Admin panel: analitika ombori xatosi: %s", exc)
        raise error_status(503, "Analitika ombori hozir javob bermadi, qayta urinib ko'ring") \
            from exc


def _channel(value: str | None) -> str | None:
    """`?channel=` -> kanal nomi; bo'sh yoki `all` - filtrsiz."""
    text = (value or "").strip()
    if not text or text.lower() == "all":
        return None
    found = normalize_channel(text, default=None)
    if found is None:
        raise QueryError("channel: noma'lum kanal")
    return found


def _period(start: str | None, end: str | None, *,
            default: bool) -> tuple[float | None, float | None]:
    """`?from=&to=` -> epoch. `default=True` - berilmagani oxirgi 7 kun bilan
    to'ldiriladi (grafiklar uchun oraliq shart); aks holda chegarasiz."""
    begin = queries.parse_time(start, name="from")
    stop = queries.parse_time(end, name="to", end=True)
    if default:
        return queries.resolve_range(begin, stop)
    if begin is not None and stop is not None and begin >= stop:
        raise QueryError("from: 'to' dan oldin bo'lishi kerak")
    return begin, stop


def _text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def turn_filter(
    start: str | None = _FROM,
    end: str | None = _TO,
    channel: str | None = _CHANNEL,
    q: str | None = _SEARCH,
    actor_id: int | None = Query(None, alias="actorId", description="Faqat shu odam"),
    route: str | None = Query(None, max_length=64,
                              description="rules | hrm | crm | live | both | clarify | contacts | none"),
    status: str | None = Query(None, pattern=_STATUS_PATTERN),
    reported: bool | None = Query(None, description="true - faqat xabar berilganlar"),
    min_ms: int | None = Query(None, alias="minMs", ge=0, description="To'liq vaqt kamida (ms)"),
    chat_id: str | None = Query(None, alias="chatId", max_length=128),
    engine: str | None = Query(
        None, pattern=_ENGINE_PATTERN,
        description="Yordamchi dvigateli: v1 | v2 | default (yozilmagan - versiyasiz yo'l)"),
) -> TurnFilter:
    """Savollar va suhbatlar uchun umumiy filtr (`?from&to&channel&q&...`)."""
    with _checked():
        begin, stop = _period(start, end, default=False)
        return TurnFilter(
            start=begin, end=stop, channel=_channel(channel), q=_text(q), actor_id=actor_id,
            route=_text(route), status=status, reported=reported, min_ms=min_ms,
            chat_id=_text(chat_id), engine=engine,
        )


# --- umumiy ko'rinish -----------------------------------------------------------------


@router.get("/overview", response_model=AdminOverview)
def get_overview(start: str | None = _FROM, end: str | None = _TO,
                 channel: str | None = _CHANNEL) -> dict[str, Any]:
    """Bosh sahifa. Oraliq berilmasa - oxirgi 7 kun; KPI lar xuddi shu
    uzunlikdagi oldingi davr bilan taqqoslanadi. Grafik guruhi 2 kungacha
    soat, undan uzun - kun (UTC; mahalliy vaqtga brauzer o'giradi)."""
    with _checked():
        begin, stop = _period(start, end, default=True)
        return queries.overview(analytics.get_db(), start=begin, end=stop,
                                channel=_channel(channel))


# --- savollar ----------------------------------------------------------------------------


@router.get("/turns", response_model=TurnPage)
def list_turns(flt: TurnFilter = Depends(turn_filter), cursor: str | None = _CURSOR,
               limit: int = _LIMIT) -> dict[str, Any]:
    """Savollar - yangisi birinchi. Keyingi sahifa: `?cursor=<nextCursor>`
    (filtrlar o'sha-o'sha qoladi)."""
    with _checked():
        return queries.list_turns(analytics.get_db(), flt, cursor=cursor, limit=limit)


@router.get("/turns/{turn_id}", response_model=TurnDetail)
def get_turn(turn_id: str = Path(max_length=64)) -> dict[str, Any]:
    """Bitta savolning izi: vaqt chizig'i, manbalar, tashqi chaqiruvlar,
    suhbatning boshqa savollari va unga berilgan xabarlar."""
    with _checked():
        found = queries.turn_detail(analytics.get_db(), turn_id)
    if found is None:
        raise error_status(404, "Savol topilmadi")
    return found


@router.get("/chats", response_model=ChatPage)
def list_chats(flt: TurnFilter = Depends(turn_filter), cursor: str | None = _CURSOR,
               limit: int = _LIMIT) -> dict[str, Any]:
    """Suhbatlar - oxirgi faollik bo'yicha. Filtrlar savollarga qo'llanadi,
    `reported` esa suhbatga (unga yoki biror savoliga xabar berilgan)."""
    with _checked():
        return queries.list_chats(analytics.get_db(), flt, cursor=cursor, limit=limit)


# --- xabarlar (shikoyatlar) ------------------------------------------------------------------


@router.get("/reports", response_model=ReportPage)
def list_reports(
    status: str | None = Query(None, pattern=_REPORT_PATTERN),
    start: str | None = _FROM,
    end: str | None = _TO,
    channel: str | None = _CHANNEL,
    q: str | None = _SEARCH,
    actor_id: int | None = Query(None, alias="actorId"),
    cursor: str | None = _CURSOR,
    limit: int = _LIMIT,
) -> dict[str, Any]:
    """Xabarlar qutisi - yangisi birinchi. `counts` - holat yorliqlari uchun,
    `status` filtrisiz (qolgan filtrlar bilan)."""
    with _checked():
        begin, stop = _period(start, end, default=False)
        return queries.list_reports(
            analytics.get_db(), status=status, start=begin, end=stop, channel=_channel(channel),
            q=_text(q), actor_id=actor_id, cursor=cursor, limit=limit)


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: str = Path(max_length=64)) -> dict[str, Any]:
    """Bitta xabar: izoh, sabab, suhbat nusxasi (xabar berilgan paytdagi
    holati - keyin o'chgan savollar ham shu yerda qoladi), admin izohi."""
    with _checked():
        found = queries.report_detail(analytics.get_db(), report_id)
    if found is None:
        raise error_status(404, "Xabar topilmadi")
    return found


@router.patch("/reports/{report_id}", response_model=ReportDetail)
def update_report(body: ReportUpdate, report_id: str = Path(max_length=64),
                  admin: AuthUser = Depends(admin_only)) -> dict[str, Any]:
    """Holat (`new → reviewing → resolved | dismissed`) va/yoki admin izohi.
    Har haqiqiy o'zgarish auditga yoziladi; o'zgarmagan qiymat - yozilmaydi.
    `adminNote: null` yoki `""` - izohni o'chirish."""
    given = body.model_fields_set
    status = body.status if "status" in given and body.status is not None else KEEP
    note = body.adminNote if "adminNote" in given else KEEP
    with _checked():
        found = queries.update_report(analytics.get_db(), report_id, admin=admin,
                                      status=status, admin_note=note)
    if found is None:
        raise error_status(404, "Xabar topilmadi")
    log.info("Xabar %s yangilandi (%s): %s", report_id, admin.email, sorted(given))
    return found


# --- foydalanish va tizim --------------------------------------------------------------------


@router.get("/usage", response_model=AdminUsage)
def get_usage(start: str | None = _FROM, end: str | None = _TO,
              channel: str | None = _CHANNEL) -> dict[str, Any]:
    """Tashqi xizmatlar: so'rovlar, xato ulushi, p50/p95, birliklar (audio
    soniya, belgi, bayt, kadr), vaqt va kanal bo'yicha, eng sekin amallar."""
    with _checked():
        begin, stop = _period(start, end, default=True)
        return queries.usage(analytics.get_db(), start=begin, end=stop,
                             channel=_channel(channel))


def _health() -> dict[str, Any]:
    """`/api/health/detail` dagi AYNI tashxis.

    Import funksiya ichida: `main` routerlarni import qiladi, ya'ni modul
    boshida import qilinsa aylanma bo'lardi. Tashxis yiqilsa ham tizim
    sahifasi ochilsin - ombor hajmi va audit undan mustaqil.
    """
    try:
        from ... import main

        return main._diagnostics()
    except Exception:                                       # noqa: BLE001
        log.exception("Admin panel: tashxis olinmadi")
        return {"status": "unknown", "warnings": ["Tashxis olinmadi - server jurnaliga qarang"]}


def _sso_configured() -> bool:
    try:
        from ... import main

        return bool(main.connector_hub().crm.configured)
    except Exception:                                       # noqa: BLE001
        return False


def _bot_mode(telegram: dict[str, Any]) -> str:
    """Botning HAQIQIY rejimi - `bot.status()["mode"]` dan.

    Prod'da ikki rejim bor (`bot/runner.py`): `polling` va `webhook`, va
    webhook ishlamasa bot o'zi `polling` ga qaytadi - ya'ni sozlamaga emas,
    botning o'ziga qarash kerak. Bot hali ishga tushmagan bo'lsa (holatda
    `mode` yo'q) - `polling`, u zaxira rejim.
    """
    mode = telegram.get("mode")
    return mode if mode in ("polling", "webhook") else "polling"


def _config(health: dict[str, Any]) -> dict[str, Any]:
    """Sozlamalar - QIYMATLARSIZ, faqat yoqilgan/o'chiq (kalit va manzillar
    admin panelga ham chiqmaydi)."""
    login = health.get("login") if isinstance(health.get("login"), dict) else {}
    telegram = health.get("telegram") if isinstance(health.get("telegram"), dict) else {}
    sso = login.get("sso")
    bot_enabled = bool(settings.telegram_bot_enabled)
    bot_configured = bool(telegram.get("configured", bool(settings.telegram_bot_token)))
    return {
        "ssoEnabled": sso if isinstance(sso, bool) else _sso_configured(),
        "localLoginEnabled": bool(settings.local_login_enabled),
        "telegramMode": _bot_mode(telegram) if bot_enabled and bot_configured else "off",
        "telegramBotEnabled": bot_enabled,
        "retentionDays": analytics.retention_days(),
        "analyticsEnabled": analytics.analytics_enabled(),
    }


@router.get("/system", response_model=AdminSystem)
def get_system() -> dict[str, Any]:
    """Tizim: har bir tashqi xizmat holati, sozlamalar, analitika ombori
    (hajm, qatorlar, tashlangan yozuvlar) va admin amallari jurnali."""
    health = _health()
    db = analytics.get_db()
    with _checked():
        return {
            "health": health,
            "config": _config(health),
            "storage": queries.storage(db, dropped=analytics.get_writer().dropped),
            "audit": admin_users.audit_entries(limit=50, db=db),
        }


# --- qidiruv va nishon ------------------------------------------------------------------------


@router.get("/search", response_model=AdminSearch)
def search(
    q: str = Query(..., min_length=1, max_length=200),
    identities: Any = Depends(get_identity_store),
    users: Any = Depends(get_user_store),
) -> dict[str, Any]:
    """Buyruqlar oynasi (⌘K): har turdan 5 tagacha - odamlar (katalogdan),
    savollar va xabarlar. Kalit (savol, so'rov, suhbat, xabar id) - aynan."""
    text = q.strip()
    if not text:
        return {"users": [], "turns": [], "reports": []}
    db = analytics.get_db()
    with _checked():
        found = queries.search(db, text, limit=5)
    return {"users": admin_users.list_users(identities, users, q=text, limit=5, db=db), **found}


@router.get("/me", response_model=AdminMe)
def get_me(admin: AuthUser = Depends(admin_only)) -> dict[str, Any]:
    """Kim kirgan (samarali rollar bilan) va ko'rilmagan xabarlar soni -
    menyu nishoni uchun tez-tez so'raladi, shuning uchun arzon."""
    with _checked():
        count = queries.count_reports(analytics.get_db(), status="new")
    return {"user": admin, "newReports": count}

"""Yordamchi dvigatelini (versiyasini) ADMIN PANEL boshqaradi.

    effective_engine(user, channel, requested=None)  -> "v1" | "v2" | "v3" | "v4" | ""

BITTA FUNKSIYA, hamma yo'l shundan: web oqimi (`/chat/stream`), `/chat/ask`,
Mini App (u ham `/chat/stream`, kanal `miniapp`), Telegram bot va "Pro"
byudjeti (`/pro/quota`). Ikki joyda alohida yozilgan qoida ertami-kechmi
farqlanib qoladi - va farq "web'da v2, botda esa v1" yoki "Pro tugmasi
ko'rinadi, savol esa v1 ga ketadi" bo'lib chiqadi.

TARTIB (birinchi topilgani ishlaydi):

  1. klient so'ragani (`requested`) - FAQAT odamga alohida berilgan
     versiyalar (`engine_access.engines`) ichida bo'lsa;
  2. odamning o'z default'i (`engine_access.default_engine`), yoki unga
     bitta versiya berilgan bo'lsa - o'sha;
  3. admin siyosati, shu kanal uchun (`engine_policy` `channel:<kanal>`);
  4. admin siyosati, umumiy (`engine_policy` `default`);
  5. `.env` (`HRM_ASSISTANT_ENGINE_BY_CHANNEL`, keyin `HRM_ASSISTANT_ENGINE`)
     - admin hali hech narsa saqlamaguncha boshlang'ich qiymat;
  6. kod default'i `v2` (`core/engines.DEFAULT_ENGINE`, 5-bo'g'in ichida).

QO'SHIMCHA QOIDA: odamga versiyalar berilgan bo'lsa, natija HAR DOIM o'sha
ro'yxatdan. Siyosat (yoki `.env` dagi versiyasiz yo'l) ro'yxatda bo'lmagan
dvigatelni bersa - ro'yxatning birinchisi. Aks holda klientga "tanlash
mumkin: v1, v2", "hozirgisi: legacy" degan, o'zi bilan zid javob ketardi.

KLIENT TANLOVI HUQUQ EMAS. `requested` - faqat istak: ruxsat etilmagan
qiymat JIMGINA e'tiborsiz qoladi (xato emas). Aks holda eski klient yoki
qo'lda yasalgan so'rov chatni sindirardi; sinov versiyasini esa faqat admin
bergan odam ochadi. So'ralgani baribir ishlaydiganining o'zi bo'lsa (klient
`current` ni qaytarib yuborsa) - bu rad etish EMAS (`ignored` yo'q): aks
holda izda har savolda yolg'on `engine.ignored` nuqtasi paydo bo'lardi.

KANAL - HUQUQ EMAS. Kanal `X-Venera-Client` dan (`core/channels.py`), uni
har kim yoza oladi: odam boshqa kanalning "hamma uchun" versiyasiga sarlavha
bilan o'ta oladi (`bot` dan tashqari - u sarlavhada qabul qilinmaydi). Kanal
siyosati - versiyani kanal-kanal YOYISH vositasi, cheklov emas. Sinov
versiyasini faqat bir guruhga ochish kerak bo'lsa - `engine_access`
(odamga beriladi, token bo'yicha), kanal siyosati emas.

KESH 5 SONIYA (`CACHE_TTL`). Qoida har savolda o'qiladi - bot va web
oqimlari omborga har gal bormasin. Admin yozuvi shu jarayonda keshni DARHOL
tozalaydi (`invalidate`); boshqa jarayon (masalan ikkinchi worker) eng ko'pi
5 soniyada ko'radi. Kesh ombor obyektiga bog'langan: testlar har safar yangi
ombor oladi va bir-birining qarorini ko'rmaydi.

HECH QACHON XATO BERMAYDI. Ombor o'qilmasa (disk, buzilgan fayl, eski sxema)
- `.env` bo'yicha ishlaydi va jurnalga daqiqasiga bir marta yoziladi.
Dvigatelni tanlay olmaganimiz uchun chatni to'xtatish noto'g'ri versiyadan
yomonroq (`core/engines.py` dagi qoida bilan bir xil).

AUDIT. Har admin o'zgarishi `audit_log` ga O'SHA tranzaksiyada:
`engine.policy`, `engine.access.set`, `engine.access.remove`. Odamga oid
yozuvlar `target_type = user` bilan - foydalanuvchi varag'idagi auditda
ham ko'rinadi.

MIYA FLAG'LARI (2026-10-10, LLM ishlarining agentga ko'chishi). Shu yerda,
dvigatel siyosati YONIDA: funksiya bo'yicha `local | shadow | agent`
(`brain_choice`, `put_brain`, audit `feature.state`). Tartib: admin
(`brain_routing` jadvali) -> `.env` (`<FEATURE>_ENGINE`, jonli) -> `local`.
Bu - SOZLANGAN holat; agent haqiqatan tayyormi (bosh kalit, `capabilities`)
degan tekshiruv `services/brain/routing.py` da - flag'ni oldindan yoqib
qo'yish xavfsiz bo'lsin. Kesh va `invalidate` dvigatel qarorlari bilan bitta.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..core import config as _config
from ..core import engines as _engines
from ..core.channels import CHANNELS
from ..core.channels import normalize as normalize_channel
from ..schemas.auth import AuthUser
from . import admin_users as _admin
from .admin_users import AdminError
from .analytics import queries as _queries
from .analytics.db import Database, get_db, log_limited
from .analytics.queries import iso

log = logging.getLogger(__name__)

#: `engine_policy` kalitlari.
DEFAULT_KEY = "default"
CHANNEL_PREFIX = "channel:"

#: Admin panelda "hozir nima ishlaydi" ko'rsatiladigan kanallar. `desktop` va
#: `api` siyosatda bor (kalit saqlasa bo'ladi), lekin bugun ulardan savol
#: deyarli kelmaydi - kartochkada joy olmasin.
SHOWN_CHANNELS: tuple[str, ...] = ("web", "miniapp", "bot", "slack")

#: Qoida keshining umri (soniya).
CACHE_TTL = 5.0

#: Statistika oynasi - oxirgi 7 kun.
STATS_DAYS = 7

#: Monoton soat - testlar keshning eskirishini kutmasdan sinash uchun almashtiradi.
_clock = time.monotonic

_UNSET: Any = object()


# --- ombordagi qarorlar ---------------------------------------------------------------


@dataclass(frozen=True)
class Grant:
    """`engine_access` qatori: odamga berilgan versiyalar (katalog tartibida)."""

    actor_id: int
    engines: tuple[str, ...]
    default_engine: str | None = None
    note: str | None = None
    updated_at: float | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class BrainRow:
    """`brain_routing` qatori: admin bergan holat va shadow namunasi."""

    feature: str
    state: str
    sample_rate: float | None = None
    note: str | None = None
    updated_at: float | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class Rules:
    """Ombordagi hamma qarorlar: siyosat (`kalit -> dvigatel`) va odamlar."""

    policy: Mapping[str, str]
    access: Mapping[int, Grant]
    updated_at: float | None = None
    updated_by: str | None = None
    #: `False` - ombor o'qilmadi, bu bo'sh o'rinbosar (`.env` ishlaydi).
    loaded: bool = True
    #: Miya flag'lari (`feature -> BrainRow`) - admin aytmagan funksiya yo'q.
    brain: Mapping[str, BrainRow] = field(default_factory=dict)


#: Ombor o'qilmaganda - hech qanday admin qarori yo'q, ya'ni `.env`.
EMPTY = Rules(policy={}, access={}, loaded=False)


def _known_key(key: str) -> bool:
    if key == DEFAULT_KEY:
        return True
    return key.startswith(CHANNEL_PREFIX) and key[len(CHANNEL_PREFIX):] in CHANNELS


def _ordered(engines: Iterable[str]) -> tuple[str, ...]:
    """Katalog kalitlari - KATALOG tartibida, takrorsiz. Tartib bir xil
    bo'lishi kerak: "birinchisi" (`resolve`) qaysi ekanini admin
    yuborgan ro'yxatning tartibi emas, katalog belgilaydi."""
    wanted = set(engines)
    return tuple(engine for engine in _engines.CATALOG_IDS if engine in wanted)


def _ts(value: object) -> float | None:
    """Vaqt ustuni -> son. Qo'lda buzilgan qiymat (matn) - `None`. Aks holda
    `load` dagi solishtirish `TypeError` berib, BUTUN qarorlarni (hamma
    odamlarning ruxsati bilan) tashlab `.env` ga tushirardi - bitta buzuq
    qator uchun hamma sinovchi o'z versiyasini yo'qotardi."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: object) -> str | None:
    """Matn ustuni (`note`, `updated_by`) - satr yoki `None`: javob sxemasi
    (`EngineAccessRow`) son qabul qilmaydi, admin sahifasi 500 bermasin."""
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _grant_of(row: Mapping[str, Any]) -> Grant | None:
    """Qator -> `Grant`. Qo'lda buzilgan qator (JSON emas, katalogda yo'q
    versiyalar) - `None`: odam umumiy siyosatda qoladi, taxmin qilib unga
    sinov versiyasi berilmaydi."""
    actor_id = int(row["actor_id"])
    try:
        raw = json.loads(row["engines"])
    except (TypeError, ValueError):
        raw = None
    if not isinstance(raw, list):
        log_limited("engine_control.access", "engine_access buzilgan (actor %s) - e'tiborsiz",
                    actor_id)
        return None
    engines = _ordered(e for e in (_engines.catalog_id(item) for item in raw) if e)
    if not engines:
        log_limited("engine_control.access_empty",
                    "engine_access bo'sh yoki katalogda yo'q (actor %s)", actor_id)
        return None
    default = _engines.catalog_id(row.get("default_engine"))
    return Grant(
        actor_id=actor_id,
        engines=engines,
        default_engine=default if default in engines else None,
        note=_text(row.get("note")),
        updated_at=_ts(row.get("updated_at")),
        updated_by=_text(row.get("updated_by")),
    )


def load(db: Database) -> Rules:
    """Ombordan YANGI o'qish (keshsiz). Ombor xatosi chaqiruvchiga chiqadi -
    admin sahifasi uni 503 qiladi, so'rov yo'li esa `rules()` orqali o'qiydi."""
    policy: dict[str, str] = {}
    updated_at: float | None = None
    updated_by: str | None = None
    for row in db.rows("SELECT key, value, updated_at, updated_by FROM engine_policy"):
        key, engine = str(row["key"]), _engines.catalog_id(row["value"])
        if not _known_key(key) or engine is None:
            log_limited("engine_control.policy", "engine_policy: %r=%r tanilmadi - e'tiborsiz",
                        key, row["value"])
            continue
        policy[key] = engine
        at = _ts(row["updated_at"])
        if at is not None and (updated_at is None or at > updated_at):
            updated_at, updated_by = at, _text(row["updated_by"])
    access: dict[int, Grant] = {}
    for row in db.rows("SELECT * FROM engine_access"):
        grant = _grant_of(row)
        if grant is not None:
            access[grant.actor_id] = grant
    return Rules(policy=policy, access=access, updated_at=updated_at, updated_by=updated_by,
                 brain=_brain_rows(db))


# --- kesh ----------------------------------------------------------------------------

_cache_lock = threading.Lock()
#: (ombor, o'qilgan payt, qarorlar).
_cached: tuple[Database, float, Rules] | None = None
#: Har `invalidate` da oshadi. O'qish boshlanganda olingan raqam yozish
#: paytida o'zgargan bo'lsa natija keshga QO'YILMAYDI: aks holda admin
#: yozuvidan OLDIN boshlangan sekin o'qish eski qarorni yana 5 soniyaga
#: tiklab qo'yardi.
_generation = 0


def invalidate() -> None:
    """Keshni tozalaydi - admin yozuvidan keyin, shu jarayonda darhol ko'rinsin."""
    global _cached, _generation
    with _cache_lock:
        _generation += 1
        _cached = None


def rules() -> Rules:
    """Keshlangan qarorlar (<= `CACHE_TTL`). HECH QACHON xato bermaydi:
    ombor o'qilmasa `EMPTY` (ya'ni `.env`), u ham keshlanadi - nosoz ombor
    har savolda qayta urinib, so'rovlarni sekinlatmasin."""
    global _cached
    try:
        db = get_db()
    except Exception:                                       # noqa: BLE001
        log_limited("engine_control.db", "Analitika ombori ochilmadi - dvigatel .env dan",
                    exc_info=True)
        return EMPTY
    now = _clock()
    with _cache_lock:
        found, generation = _cached, _generation
    if found is not None and found[0] is db and 0.0 <= now - found[1] < CACHE_TTL:
        return found[2]
    try:
        fresh = load(db)
    except Exception:                                       # noqa: BLE001
        log_limited("engine_control.read", "Dvigatel qarorlari o'qilmadi - .env ishlatildi",
                    exc_info=True)
        fresh = EMPTY
    with _cache_lock:
        if _generation == generation:
            _cached = (db, now, fresh)
    return fresh


# --- tanlov ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    """Tanlov natijasi.

    `source` - qaysi bo'g'in hal qildi: requested | user | channel | default
    | env. `available` - odam tanlay oladigan dvigatellar (versiya berilmagan
    bo'lsa faqat `engine`). `ignored` - klient so'radi, lekin boshqasi ishladi
    (ruxsat yo'q yoki notanish qiymat)."""

    engine: str
    source: str
    available: tuple[str, ...]
    selectable: bool = False
    ignored: bool = False


def _actor_id(user: AuthUser | int | None) -> int | None:
    if user is None:
        return None
    if isinstance(user, int):
        return user
    found = getattr(user, "actorId", None)
    return int(found) if isinstance(found, int) else None


def _public(channel: str | None, data: Rules) -> tuple[str, str]:
    """3-6 bo'g'inlar: versiya berilmagan odam uchun ("hamma uchun")."""
    if channel is not None:
        found = data.policy.get(CHANNEL_PREFIX + channel)
        if found:
            return found, "channel"
    found = data.policy.get(DEFAULT_KEY)
    if found:
        return found, "default"
    return _engines.engine_for(channel), "env"


def resolve(user: AuthUser | int | None, channel: str | None, requested: object = None, *,
            data: Rules | None = None) -> Choice:
    """To'liq tanlov (modul izohidagi tartib). `data` berilmasa - kesh.

    `channel` - `core/channels.py` nomi; tanilmasa kanal bo'g'ini
    o'tkazib yuboriladi. `user` - `AuthUser`, `actorId` yoki `None`
    ("hamma uchun" - admin sahifasidagi `effective`)."""
    data = rules() if data is None else data
    actor = _actor_id(user)
    grant = data.access.get(actor) if actor is not None else None
    name = normalize_channel(channel, default=None)
    wanted = _engines.catalog_id(requested)

    if grant is not None:
        allowed, many = grant.engines, len(grant.engines) > 1
        if wanted is not None and wanted in allowed:
            return Choice(wanted, "requested", allowed, many)
        own = grant.default_engine or (allowed[0] if len(allowed) == 1 else None)
        if own is not None:
            return Choice(own, "user", allowed, many, ignored=_ignored(requested, own))
        engine, source = _public(name, data)
        if engine not in allowed:
            engine, source = allowed[0], "user"
        return Choice(engine, source, allowed, many, ignored=_ignored(requested, engine))

    engine, source = _public(name, data)
    return Choice(engine, source, (engine,), False, ignored=_ignored(requested, engine))


def _ignored(requested: object, engine: str) -> bool:
    """Klient so'radi, lekin BOSHQA dvigatel ishladi. So'ragani ishlaganining
    o'zi bo'lsa - rad etish emas (modul izohi): yangi klient har savolda
    `current` ni yuborishi mumkin va izda yolg'on nuqta bo'lmasin."""
    if requested is None or requested == "":
        return False
    return _engines.catalog_id(requested) != engine


def _env_choice(channel: str | None, requested: object) -> Choice:
    """Eng oxirgi zahira: faqat `.env` (u ham yiqilsa - kod default'i)."""
    try:
        engine = _engines.engine_for(channel)
    except Exception:                                       # noqa: BLE001
        engine = _engines.DEFAULT_ENGINE
    return Choice(engine, "env", (engine,), False, ignored=_ignored(requested, engine))


def choose(user: AuthUser | int | None, channel: str | None,
           requested: object = None) -> Choice:
    """`resolve` - lekin HECH QACHON xato bermaydi (so'rov yo'llari uchun)."""
    try:
        return resolve(user, channel, requested)
    except Exception:                                       # noqa: BLE001
        log_limited("engine_control.resolve", "Dvigatel tanlanmadi - .env ishlatildi",
                    exc_info=True)
        return _env_choice(channel, requested)


def effective_engine(user: AuthUser | int | None, channel: str | None,
                     requested: object = None) -> str:
    """Shu odam, shu kanal (va klient so'ragan bo'lsa - shu tanlov) uchun
    dvigatel. Web, `/chat/ask`, Mini App, bot va `/pro/quota` - hammasi shu."""
    return choose(user, channel, requested).engine


def health_state() -> dict[str, Any]:
    """`/api/health/detail` uchun: kim hal qilyapti (`admin` | `env`), ombor
    o'qildimi, nechta odamga alohida versiya berilgan va "hamma uchun" har
    kanalning dvigateli. Sir yo'q - faqat versiya nomlari va son."""
    try:
        data = rules()
        return {
            "source": "admin" if data.policy else "env",
            "loaded": data.loaded,
            "grants": len(data.access),
            "byChannel": {name: resolve(None, name, data=data).engine for name in CHANNELS},
        }
    except Exception:                                       # noqa: BLE001
        log_limited("engine_control.health", "Dvigatel holati olinmadi", exc_info=True)
        return {"source": "env", "loaded": False, "grants": 0, "byChannel": {}}


def client_view(user: AuthUser, channel: str | None) -> dict[str, Any]:
    """`GET /api/v1/chat/engines` - `EngineChoice` shakli."""
    found = choose(user, channel)
    return {
        "current": found.engine,
        "selectable": found.selectable,
        "available": list(found.available),
        "catalog": _engines.catalog(),
    }


# --- admin: ko'rinish ----------------------------------------------------------------------


def _policy_shape(policy: Mapping[str, str]) -> dict[str, Any]:
    """`{default, channels}` - audit va javob uchun bir xil shakl."""
    return {
        "default": policy.get(DEFAULT_KEY),
        "channels": {name: policy[CHANNEL_PREFIX + name] for name in CHANNELS
                     if CHANNEL_PREFIX + name in policy},
    }


def policy_view(data: Rules) -> dict[str, Any]:
    """types.ts: EnginePolicy."""
    return {
        **_policy_shape(data.policy),
        "source": "admin" if data.policy else "env",
        "updatedAt": iso(data.updated_at),
        "updatedBy": data.updated_by,
    }


def env_defaults() -> dict[str, Any]:
    """types.ts: EnvDefaults - `.env` dagi boshlang'ich qiymatlar. Faqat
    kanalga ALOHIDA aytilganlari (`policy.channels` bilan bir xil ma'no)."""
    overrides, _ = _engines.channel_overrides()
    return {
        "default": _engines.default_engine(),
        "channels": {name: overrides[name] for name in CHANNELS if name in overrides},
    }


def effective_for(user: AuthUser | int | None, data: Rules) -> dict[str, str]:
    """types.ts: EffectiveEngines - ko'rsatiladigan kanallar bo'yicha."""
    return {name: resolve(user, name, data=data).engine for name in SHOWN_CHANNELS}


def _person_name(person: Any, actor_id: int) -> str:
    # `admin_users.admin_user` dagi AYNI qoida - ikki sahifada bitta odam
    # ikki xil nom bilan ko'rinmasin.
    if person is None:
        return f"#{actor_id}"
    return person.name or person.login or person.email or f"#{actor_id}"


def access_row(grant: Grant, person: Any) -> dict[str, Any]:
    """types.ts: EngineAccessRow."""
    return {
        "actorId": grant.actor_id,
        "name": _person_name(person, grant.actor_id),
        "login": getattr(person, "login", None) if person is not None else None,
        "engines": list(grant.engines),
        "defaultEngine": grant.default_engine,
        "note": grant.note,
        "updatedAt": iso(grant.updated_at),
        "updatedBy": grant.updated_by,
    }


def admin_view(identities: Any, users: Any, *, db: Database | None = None,
               now: float | None = None) -> dict[str, Any]:
    """`GET /api/v1/admin/engines` - `AdminEngines` shakli.

    KESHSIZ: admin aynan omborda turganini ko'rishi kerak. Ombor xatosi
    (`sqlite3.Error`) chaqiruvchiga chiqadi - router 503 qiladi."""
    db = db or get_db()
    now = time.time() if now is None else now
    data = load(db)
    found = _admin.people(identities, users, db=db) if data.access else {}
    rows = [access_row(grant, found.get(aid)) for aid, grant in data.access.items()]
    rows.sort(key=lambda r: (r["name"].casefold(), r["actorId"]))
    return {
        "catalog": _engines.catalog(),
        "policy": policy_view(data),
        "envDefaults": env_defaults(),
        "effective": effective_for(None, data),
        "stats": _queries.engine_stats(db, start=now - STATS_DAYS * 86400.0, end=now),
        "access": rows,
    }


def user_engine(actor_id: int, *, db: Database | None = None) -> dict[str, Any]:
    """`AdminUserDetail.engine` - shu odamga hozir nima ishlaydi va unga
    alohida nima berilgan. Ombor o'qilmasa - `.env` bo'yicha (varaq baribir
    ochilsin, `admin_users._safe_rows` kabi)."""
    try:
        data = load(db or get_db())
    except (sqlite3.Error, OSError):
        log_limited("engine_control.user", "Dvigatel qarorlari o'qilmadi (foydalanuvchi varag'i)",
                    exc_info=True)
        data = EMPTY
    grant = data.access.get(int(actor_id))
    return {
        "effective": effective_for(int(actor_id), data),
        "access": ({"engines": list(grant.engines), "defaultEngine": grant.default_engine}
                   if grant is not None else None),
    }


# --- admin: o'zgartirish ------------------------------------------------------------------


def _engine_or_422(value: object, where: str) -> str:
    found = _engines.catalog_id(value)
    if found is None:
        raise AdminError(f"{where}: noma'lum dvigatel ({str(value)[:32]!r}) - "
                         f"{' | '.join(_engines.CATALOG_IDS)}", status=422, code="UNKNOWN_ENGINE")
    return found


def _channel_or_422(value: object) -> str:
    name = value.strip().lower() if isinstance(value, str) else ""
    if name not in CHANNELS:
        raise AdminError(f"channels: noma'lum kanal ({str(value)[:32]!r}) - "
                         f"{' | '.join(CHANNELS)}", status=422, code="UNKNOWN_CHANNEL")
    return name


def put_policy(admin: AuthUser, identities: Any, users: Any, *, default: Any = _UNSET,
               channels: Mapping[str, Any] | None = None, db: Database | None = None,
               now: float | None = None) -> dict[str, Any]:
    """`PUT /api/v1/admin/engines/policy` - QO'SHILADIGAN o'zgarish.

    `default` berilmasa - o'zgarmaydi, `None` - o'chiriladi. `channels` dagi
    har kalit xuddi shunday; yo'q kanal o'zgarmaydi. Avval HAMMASI
    tekshiriladi (422), keyin bitta tranzaksiyada yoziladi - yarim
    saqlangan siyosat qolmaydi. Haqiqiy o'zgarish bo'lsagina auditga
    yoziladi. Javob - `admin_view` (yangi holat)."""
    changes: dict[str, str | None] = {}
    if default is not _UNSET:
        changes[DEFAULT_KEY] = None if default is None else _engine_or_422(default, "default")
    for raw, value in (channels or {}).items():
        name = _channel_or_422(raw)
        changes[CHANNEL_PREFIX + name] = (None if value is None
                                          else _engine_or_422(value, f"channels.{name}"))
    db = db or get_db()
    now = time.time() if now is None else now
    by = _admin._by(admin)
    try:
        with db.transaction() as conn:
            before = {str(r["key"]): str(r["value"]) for r in conn.execute(
                "SELECT key, value FROM engine_policy").fetchall()}
            after = dict(before)
            for key, value in changes.items():
                if value is None:
                    after.pop(key, None)
                else:
                    after[key] = value
            if after != before:
                for key, value in changes.items():
                    if value is None:
                        conn.execute("DELETE FROM engine_policy WHERE key = ?", (key,))
                    elif before.get(key) != value:
                        conn.execute(
                            "INSERT INTO engine_policy (key, value, updated_at, updated_by) "
                            "VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                            "value=excluded.value, updated_at=excluded.updated_at, "
                            "updated_by=excluded.updated_by",
                            (key, value, now, by))
                # `policy.updatedAt/updatedBy` - SIYOSATNING oxirgi o'zgarishi
                # (`load` qatorlarning eng yangisini oladi). Faqat kalit
                # o'chirilganda yangi qator yo'q: qolganlarini belgilamasak,
                # sahifa eski vaqtni va boshqa adminni "oxirgi o'zgartirgan"
                # deb ko'rsatardi. Har kalitning o'z tarixi - auditda.
                conn.execute("UPDATE engine_policy SET updated_at = ?, updated_by = ?",
                             (now, by))
                _admin.write_audit(conn, admin, "engine.policy", "engine", "policy", {
                    "from": _policy_shape(before), "to": _policy_shape(after)}, ts=now)
    except AdminError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise _admin._write_failed(exc) from exc
    invalidate()
    log.info("Admin (%s): dvigatel siyosati %s", admin.actorId, sorted(changes))
    return admin_view(identities, users, db=db, now=now)


def _read_grant(conn: sqlite3.Connection, actor_id: int) -> Grant | None:
    row = conn.execute("SELECT * FROM engine_access WHERE actor_id = ?", (actor_id,)).fetchone()
    return _grant_of(dict(row)) if row is not None else None


def _grant_shape(grant: Grant | None) -> dict[str, Any] | None:
    if grant is None:
        return None
    return {"engines": list(grant.engines), "defaultEngine": grant.default_engine}


def set_access(admin: AuthUser, actor_id: int, identities: Any, users: Any, *,
               engines: Iterable[Any], default_engine: Any = None, note: Any = _UNSET,
               db: Database | None = None, now: float | None = None) -> dict[str, Any]:
    """`PUT /api/v1/admin/engines/access/{actorId}` - odamga versiyalar.

    Odam KATALOGDA bo'lishi shart (`/admin/users` dagi ro'yxat) - aks holda
    404: xato yozilgan raqam hech kimga tegishli bo'lmagan "osilgan" qator
    bo'lib qolmasin. `note` berilmasa eskisi qoladi."""
    picked: list[str] = []
    for raw in engines:
        found = _engine_or_422(raw, "engines")
        if found not in picked:
            picked.append(found)
    ordered = _ordered(picked)
    if not ordered:
        raise AdminError("engines: kamida bitta versiya kerak", status=422, code="NO_ENGINES")
    default = None
    if default_engine is not None:
        default = _engine_or_422(default_engine, "defaultEngine")
        if default not in ordered:
            raise AdminError("defaultEngine: berilgan versiyalardan biri bo'lishi kerak",
                             status=422, code="DEFAULT_NOT_ALLOWED")
    actor_id = int(actor_id)
    db = db or get_db()
    now = time.time() if now is None else now
    person = _admin.people(identities, users, db=db).get(actor_id)
    if person is None:
        raise AdminError("Foydalanuvchi topilmadi", status=404, code="NOT_FOUND")
    by = _admin._by(admin)
    try:
        with db.transaction() as conn:
            old = _read_grant(conn, actor_id)
            if note is _UNSET:
                new_note = old.note if old is not None else None
            else:
                new_note = (str(note).strip()[:_admin.NOTE_LIMIT] or None) if note is not None \
                    else None
            new = Grant(actor_id=actor_id, engines=ordered, default_engine=default,
                        note=new_note, updated_at=now, updated_by=by)
            same = old is not None and (old.engines, old.default_engine, old.note) == (
                new.engines, new.default_engine, new.note)
            if same:
                new = old
            else:
                conn.execute(
                    "INSERT INTO engine_access (actor_id, engines, default_engine, note, "
                    "updated_at, updated_by) VALUES (?,?,?,?,?,?) ON CONFLICT(actor_id) DO "
                    "UPDATE SET engines=excluded.engines, default_engine=excluded.default_engine, "
                    "note=excluded.note, updated_at=excluded.updated_at, "
                    "updated_by=excluded.updated_by",
                    (actor_id, json.dumps(list(ordered)), default, new_note, now, by))
                detail: dict[str, Any] = {"from": _grant_shape(old), "to": _grant_shape(new)}
                if (old.note if old is not None else None) != new_note:
                    # Izohning o'zi emas - boshi (`user.note` kabi): to'liq
                    # matn jadvalda, jurnal esa "kim, qachon" uchun.
                    detail["note"] = (new_note or "")[:120]
                _admin.write_audit(conn, admin, "engine.access.set", "user", actor_id, detail,
                                   ts=now)
    except AdminError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise _admin._write_failed(exc) from exc
    invalidate()
    log.info("Admin (%s): %s ga dvigatellar %s (default %s)", admin.actorId, actor_id,
             list(ordered), default)
    return access_row(new, person)


def remove_access(admin: AuthUser, actor_id: int, *, db: Database | None = None,
                  now: float | None = None) -> bool:
    """`DELETE /api/v1/admin/engines/access/{actorId}` - odam umumiy
    siyosatga qaytadi. Katalogda bo'lishi SHART EMAS: ishdan ketgan odamning
    qatorini ham tozalash mumkin bo'lsin. Qator yo'q bo'lsa - `False`, audit
    yozilmaydi."""
    actor_id = int(actor_id)
    db = db or get_db()
    now = time.time() if now is None else now
    removed = False
    try:
        with db.transaction() as conn:
            row = conn.execute("SELECT * FROM engine_access WHERE actor_id = ?",
                               (actor_id,)).fetchone()
            if row is not None:
                old = _grant_of(dict(row))
                conn.execute("DELETE FROM engine_access WHERE actor_id = ?", (actor_id,))
                _admin.write_audit(conn, admin, "engine.access.remove", "user", actor_id,
                                   {"from": _grant_shape(old)}, ts=now)
                removed = True
    except (sqlite3.Error, OSError) as exc:
        raise _admin._write_failed(exc) from exc
    invalidate()
    if removed:
        log.info("Admin (%s): %s ning dvigatel ruxsati olib tashlandi", admin.actorId, actor_id)
    return removed


# --- miya: LLM ishini kim bajaradi (agentga ko'chish flag'lari) ------------------------------
#
# NEGA SHU YERDA. Flag - control plane: dvigatel siyosati kabi admin
# paneldan, restartsiz, audit bilan almashadi va 5 soniyalik kesh bilan
# o'qiladi. Yangi umumiy flag tizimi qurilmadi (`migration-plan.md` 1.2).

#: Holatlar: `local` - bugungi kod; `shadow` - foydalanuvchi lokal natijani
#: oladi, agent fonda taqqoslash uchun ishlaydi; `agent` - agent asosiy,
#: xatoda lokal zahira.
BRAIN_STATES: tuple[str, ...] = ("local", "shadow", "agent")


@dataclass(frozen=True)
class BrainFeature:
    """Ko'chadigan funksiya: flag nomi, unga tegishli analytics op'lari, izoh."""

    name: str
    ops: tuple[str, ...]
    label: str


#: Ko'chadigan funksiyalar (`agent-contract.md` 2.1 dagi 14 op shularga
#: bo'lingan). Tartib - admin sahifasidagi tartib.
BRAIN_FEATURES: dict[str, BrainFeature] = {f.name: f for f in (
    BrainFeature("group_summary", ("group_summary",), "Guruhda /summary"),
    BrainFeature("group_ask", ("group_ask",), "Guruhda /askbarno va murojaat"),
    BrainFeature("brief_extract", ("brief_extract", "brief_extract_support", "brief_headline",
                                   "brief_project"), "Rahbar brifi: hodisalar, sarlavha, loyiha matni"),
    BrainFeature("brief_crm", ("brief_crm",), "Brifdagi CRM holati"),
    BrainFeature("meeting_summary", ("meeting_classify", "meeting_extract", "meeting_map",
                                     "meeting_write", "meeting_verify"), "Yig'ilish xulosasi"),
    BrainFeature("meeting_ask", ("meeting_ask",), "Yig'ilish bo'yicha savol-javob"),
    BrainFeature("hold_classify", ("classify",), "Ovozli kutish tasnifi"),
    # Bizning LLM op'imiz yo'q (bugun ham agentga boradi) - faqat so'rov SHAKLI ko'chadi (W1).
    BrainFeature("group_crm", (), "Guruhdagi CRM so'rovi (agent v4 shakli)"),
    BrainFeature("meeting_crm", (), "Yig'ilish vazifasi CRM ga (agent v4 shakli)"),
    # Modelsiz: agentning `/speech` qoidalari raqamlarni so'z bilan yozadi (o'qib berish).
    BrainFeature("tts_speech", (), "Ovoz uchun matn (raqamlar so'z bilan)"),
)}

#: Op -> funksiya (bitta op faqat bitta funksiyada).
BRAIN_OP_FEATURE: dict[str, str] = {op: f.name for f in BRAIN_FEATURES.values() for op in f.ops}


@dataclass(frozen=True)
class BrainChoice:
    """Sozlangan holat. `source`: admin | env | default. `sample_rate` - shadow
    namunasi (0..1). Agent tayyorligi bu yerda TEKSHIRILMAYDI (`brain.routing`)."""

    feature: str
    state: str
    source: str
    sample_rate: float


def _rate(value: object) -> float | None:
    """Namuna qiymati: 0..1 dagi son, aks holda `None`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rate = float(value)
    return rate if 0.0 <= rate <= 1.0 else None


def default_sample_rate() -> float:
    """`.env` dagi namuna (`AGENT_SHADOW_SAMPLE_RATE`), 0..1 ga qisilgan."""
    try:
        return min(1.0, max(0.0, float(_config.settings.agent_shadow_sample_rate)))
    except (TypeError, ValueError):
        return 0.0


def _brain_rows(db: Database) -> dict[str, BrainRow]:
    """`brain_routing` qatorlari. Jadval yo'q (eski sxema) yoki buzuq qator -
    o'tkazib yuboriladi: dvigatel qarorlari bunga bog'liq bo'lib qolmasin."""
    try:
        raw = db.rows("SELECT * FROM brain_routing")
    except sqlite3.Error:
        log_limited("engine_control.brain", "brain_routing o'qilmadi - miya flag'lari .env dan",
                    exc_info=True)
        return {}
    out = _brain_rows_of(raw)
    if len(out) != len(raw):
        log_limited("engine_control.brain_row", "brain_routing: %d qator tanilmadi - e'tiborsiz",
                    len(raw) - len(out))
    return out


def brain_choice(feature: str, *, data: Rules | None = None) -> BrainChoice:
    """Funksiyaning SOZLANGAN holati. HECH QACHON xato bermaydi - noma'lum
    funksiya yoki o'qish xatosi `local` (bugungi xulq)."""
    try:
        if feature not in BRAIN_FEATURES:
            return BrainChoice(feature, "local", "default", 0.0)
        data = rules() if data is None else data
        rate = default_sample_rate()
        row = data.brain.get(feature)
        if row is not None:
            return BrainChoice(feature, row.state, "admin",
                               row.sample_rate if row.sample_rate is not None else rate)
        env = _config.brain_engine_now(feature)
        if env in BRAIN_STATES:
            return BrainChoice(feature, env, "env", rate)
        if env:
            log_limited(f"engine_control.brain_env.{feature}",
                        "%s_ENGINE=%r tanilmadi - local", feature.upper(), env[:16])
        return BrainChoice(feature, "local", "default", rate)
    except Exception:                                       # noqa: BLE001
        log_limited("engine_control.brain_choice", "Miya flag'i o'qilmadi - local", exc_info=True)
        return BrainChoice(feature, "local", "default", 0.0)


def _brain_shape(row: BrainRow | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"state": row.state, "sampleRate": row.sample_rate}


def brain_view(*, db: Database | None = None, data: Rules | None = None) -> list[dict[str, Any]]:
    """Admin: har funksiya - sozlangan holat, manbasi, `.env` qiymati, kim
    o'zgartirgan. KESHSIZ (`data` berilmasa omborni o'qiydi)."""
    if data is None:
        data = load(db or get_db())
    out: list[dict[str, Any]] = []
    for name, spec in BRAIN_FEATURES.items():
        choice = brain_choice(name, data=data)
        row = data.brain.get(name)
        out.append({
            "feature": name,
            "label": spec.label,
            "ops": list(spec.ops),
            "state": choice.state,
            "source": choice.source,
            "sampleRate": choice.sample_rate,
            "envState": _config.brain_engine_now(name) or "local",
            "note": row.note if row is not None else None,
            "updatedAt": iso(row.updated_at) if row is not None else None,
            "updatedBy": row.updated_by if row is not None else None,
        })
    return out


def put_brain(admin: AuthUser, feature: str, *, state: Any = _UNSET, sample_rate: Any = _UNSET,
              note: Any = _UNSET, db: Database | None = None, now: float | None = None) -> list[dict[str, Any]]:
    """`PUT /api/v1/admin/engines/brain/{feature}` - QO'SHILADIGAN o'zgarish.

    `state`: `local | shadow | agent`, `None` - admin qarori olib tashlanadi
    (`.env` ga qaytadi). `sample_rate`: 0..1, `None` - `.env` dagisi. Admin
    qarori yo'q funksiyada faqat namuna berilsa - 422 (holat ham kerak).
    Avval tekshiriladi, keyin bitta tranzaksiyada yoziladi; haqiqiy o'zgarish
    bo'lsagina `feature.state` auditi. Javob - `brain_view`."""
    name = str(feature or "").strip().lower()
    if name not in BRAIN_FEATURES:
        raise AdminError(f"noma'lum funksiya ({str(feature)[:40]!r}) - {' | '.join(BRAIN_FEATURES)}",
                         status=422, code="UNKNOWN_FEATURE")
    if state is not _UNSET and state is not None and state not in BRAIN_STATES:
        raise AdminError(f"state: noma'lum holat ({str(state)[:16]!r}) - {' | '.join(BRAIN_STATES)}",
                         status=422, code="UNKNOWN_STATE")
    if sample_rate is not _UNSET and sample_rate is not None and _rate(sample_rate) is None:
        raise AdminError("sampleRate: 0 dan 1 gacha son bo'lishi kerak", status=422,
                         code="BAD_SAMPLE_RATE")
    db = db or get_db()
    now = time.time() if now is None else now
    by = _admin._by(admin)
    after: BrainRow | None = None
    try:
        with db.transaction() as conn:
            found = conn.execute("SELECT * FROM brain_routing WHERE feature = ?", (name,)).fetchone()
            before = _brain_rows_of([dict(found)]).get(name) if found is not None else None
            if state is None:
                after = None
            else:
                new_state = state if state is not _UNSET else (before.state if before else None)
                if new_state is None:
                    raise AdminError("state: bu funksiyada admin qarori yo'q - holatni ham bering",
                                     status=422, code="STATE_REQUIRED")
                new_rate = (before.sample_rate if before else None) if sample_rate is _UNSET \
                    else _rate(sample_rate)
                if note is _UNSET:
                    new_note = before.note if before else None
                else:
                    new_note = (str(note).strip()[:_admin.NOTE_LIMIT] or None) if note is not None \
                        else None
                after = BrainRow(feature=name, state=new_state, sample_rate=new_rate, note=new_note,
                                 updated_at=now, updated_by=by)
            same = (before is None and after is None) or (
                before is not None and after is not None
                and (before.state, before.sample_rate, before.note)
                == (after.state, after.sample_rate, after.note))
            if not same:
                if after is None:
                    conn.execute("DELETE FROM brain_routing WHERE feature = ?", (name,))
                else:
                    conn.execute(
                        "INSERT INTO brain_routing (feature, state, sample_rate, note, updated_at, "
                        "updated_by) VALUES (?,?,?,?,?,?) ON CONFLICT(feature) DO UPDATE SET "
                        "state=excluded.state, sample_rate=excluded.sample_rate, note=excluded.note, "
                        "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                        (name, after.state, after.sample_rate, after.note, now, by))
                _admin.write_audit(conn, admin, "feature.state", "feature", name, {
                    "from": _brain_shape(before), "to": _brain_shape(after)}, ts=now)
    except AdminError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise _admin._write_failed(exc) from exc
    invalidate()
    log.info("Admin (%s): miya flag'i %s -> %s", admin.actorId, name,
             after.state if after is not None else ".env")
    return brain_view(db=db)


def _brain_rows_of(raw: list[dict[str, Any]]) -> dict[str, BrainRow]:
    """Tranzaksiya ichida o'qilgan qatorlar -> `BrainRow` (`_brain_rows` qoidasi)."""
    out: dict[str, BrainRow] = {}
    for row in raw:
        feature, state = str(row.get("feature") or ""), str(row.get("state") or "")
        if feature in BRAIN_FEATURES and state in BRAIN_STATES:
            out[feature] = BrainRow(feature=feature, state=state, sample_rate=_rate(row.get("sample_rate")),
                                    note=_text(row.get("note")), updated_at=_ts(row.get("updated_at")),
                                    updated_by=_text(row.get("updated_by")))
    return out

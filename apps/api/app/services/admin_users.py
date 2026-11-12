"""Foydalanuvchilarni boshqarish: rollar, bloklash, sessiyalarni tugatish, audit.

NEGA ALOHIDA JADVAL. Shaxs ikki manbadan keladi va ikkalasi ham BIZNIKI
EMAS: SSO hisoblari (`identities.json`, har kirishda Keycloak'dan qayta
yoziladi) va zahira hisoblar (`config/users.yaml`, IT xodimi qo'lda
tahrirlaydi). Admin paneldagi o'zgarish ularning ustiga yozilsa, keyingi
kirish yoki fayl tahriri uni jimgina o'chirib yuborardi. Shuning uchun
admin qarori analitika omboridagi `user_admin` jadvalida, `actor_id`
bo'yicha, manbadan ALOHIDA turadi va manbaning USTIDAN qo'yiladi:

  * rollar - `user_admin.roles` NULL bo'lmasa o'sha, aks holda manbaniki
    (SSO manbasidan rollar bizning Keycloak client'imizniki, ishoniladi -
    `_source_roles` izohi);
  * bloklash - `disabled=1`: kirish 403, mavjud token 401, bot rad etadi;
  * sessiya versiyasi - `token_version`. Tokenda `ver` turadi
    (`core/security.py`); versiya oshsa shu paytgacha berilgan HAMMA
    token o'ladi. Qora ro'yxatsiz "hamma joydan chiqarish".

HAMMASI BITTA JOYDA (`access` / `effective`): `api/deps.current_user`,
kirish (`api/v1/auth.py`) va Telegram bot shu funksiyalarni chaqiradi.
Ikki joyda alohida yozilgan tekshiruv ertami-kechmi farqlanib qoladi - va
farq aynan "bloklangan odam bot orqali ishlayveradi" ko'rinishida chiqadi.

ZAXIRA KALIT (`settings.admin_logins`). `.env` dagi ro'yxatdagi login yoki
email HAR DOIM ADMIN va uni panel orqali bloklab yoki ADMIN dan mahrum
qilib bo'lmaydi (`rolesLocked`). Sabab: panel yagona admin'ni tasodifan
o'chirib qo'yishi mumkin - serverga kirish huquqi bor odam esa `.env`
orqali har doim qaytib kira olishi kerak.

AUDIT. Har o'zgarish `audit_log` ga, O'SHA tranzaksiyada yoziladi: yozuv
bor - o'zgarish bor, va aksincha. Parol, token hech qachon yozilmaydi.

YOZISH `writer.py` navbati orqali EMAS, to'g'ridan-to'g'ri
(`Database.transaction`): admin natijani darhol ko'rishi kerak va "oxirgi
admin" tekshiruvi o'qish bilan yozish orasida o'zgarmasligi kerak
(`BEGIN IMMEDIATE`). Bunday yozuvlar kam - chat yozuvlarini kutdirmaydi.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import statistics
import time

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..core.channels import CHANNELS
from ..core.config import settings
from ..schemas.auth import AuthUser
from .analytics.db import Database, get_db, log_limited
from .analytics.queries import DEFAULT_DAYS, QueryError, iso, parse_time, resolve_range
from .analytics.queries import turn_summaries as _turn_summaries

log = logging.getLogger(__name__)

#: Ilova biladigan rollar. Manbalarda boshqa rollar ham bo'lishi mumkin
#: (Keycloak: `employee`, `crm-user`) - ular ham qabul qilinadi, lekin faqat
#: biror manbada allaqachon mavjud bo'lsa (`_allowed_roles`).
KNOWN_ROLES: tuple[str, ...] = ("ADMIN", "RAG_ADMIN", "USER")
ADMIN = "ADMIN"
#: Venera'da imtiyoz beradigan rollar: ADMIN - admin panel va hammaning suhbat
#: yozuvlari, RAG_ADMIN - modelning xom chiqishi (diagnostika). SSO
#: manbasidan ular DEFAULT RAD ETILADI (`_source_roles`).
PRIVILEGED_ROLES: frozenset[str] = frozenset({"ADMIN", "RAG_ADMIN"})

#: Admin paneldagi "Izoh" chegarasi.
NOTE_LIMIT = 500
#: Bitta sahifadagi hisob-kitob uchun ko'rib chiqiladigan savollar chegarasi
#: (median uchun) - juda faol odamda ham so'rov yengil qolsin.
_TTFT_ROWS = 50_000


class AdminError(Exception):
    """Admin amali rad etildi. `status` HTTP kodi bo'ladi, matn adminga
    ko'rinadi (router uni `error_status` ga o'giradi)."""

    def __init__(self, message: str, *, status: int = 400, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


# --- vaqt ------------------------------------------------------------------------
#
# Vaqt formati va oraliq qoidalari admin panelning QOLGAN qismi bilan bir
# xil bo'lishi kerak (`analytics/queries.py`): bitta sahifada ikki xil sana
# shakli yoki "to" ning ikki xil ma'nosi bo'lsa, raqamlar mos kelmay qoladi.


def parse_range(start: str | None, end: str | None, *, default_days: int = DEFAULT_DAYS,
                now: float | None = None) -> tuple[float, float]:
    """`?from=&to=` -> `[boshi, oxiri)` epoch (`queries.parse_time` qoidalari).

    Tushunarsiz qiymat yoki teskari oraliq - `AdminError` 422: jimgina
    "hammasi" deb olinsa admin noto'g'ri raqamga qarab qaror qilardi.
    """
    try:
        return resolve_range(parse_time(start, name="from"), parse_time(end, name="to", end=True),
                             default_days=default_days, now=now)
    except QueryError as exc:
        raise AdminError(str(exc), status=422, code="BAD_RANGE") from exc


# --- zaxira kalit: admin_logins --------------------------------------------------

_bootstrap_cache: tuple[str, frozenset[str]] = ("", frozenset())


def bootstrap_logins() -> frozenset[str]:
    """`settings.admin_logins` - vergul (yoki bo'shliq) bilan ajratilgan login /
    emaillar, kichik harfda. Sozlama maydoni hali bo'lmasa - bo'sh.

    Har chaqiruvda sozlamadan o'qiladi (testlar va `.env` qayta o'qilishi
    uchun), bo'lish esa satr o'zgarganda qayta qilinadi.
    """
    global _bootstrap_cache
    raw = getattr(settings, "admin_logins", "") or ""
    if isinstance(raw, (list, tuple, set, frozenset)):
        raw = ",".join(str(item) for item in raw)
    raw = str(raw)
    cached_raw, cached = _bootstrap_cache
    if raw == cached_raw:
        return cached
    parsed = frozenset(part.strip().lower() for part in re.split(r"[,\s;]+", raw) if part.strip())
    _bootstrap_cache = (raw, parsed)
    return parsed


def is_bootstrap(email: str | None, login: str | None = None) -> bool:
    """Shu odam `admin_logins` da bormi.

    `login` BERILSA (SSO hisobi, `None` emas) - FAQAT login solishtiriladi,
    email EMAS. Sabab: SSO emailini Keycloak beradi va odam uni hisob
    sahifasida O'ZI o'zgartira olishi mumkin; ro'yxatdagi email hali hech
    kimga tegishli bo'lmasa (masalan faqat `users.yaml` dagi zahira admin),
    har qanday xodim o'z emailini shunga o'zgartirib ADMIN bo'lib olardi.
    SSO login (`preferred_username`) esa odam tomonidan o'zgarmaydi.
    `login=None` - zahira hisob (`users.yaml`): u yerda email loginning
    o'zi va uni faqat IT xodimi yozadi - email solishtiriladi.

    Emailning `@` gacha qismi ham ATAYLAB solishtirilmaydi (xuddi shu sabab).
    """
    wanted = bootstrap_logins()
    if not wanted:
        return False
    value = email if login is None else login
    return bool(value) and str(value).strip().lower() in wanted


def _source_roles(source: Iterable[str], *, sso: bool) -> list[str]:
    """Manba rollari.

    SSO rollari endi FAQAT bizning Keycloak client'imizning rollari
    (`services/oidc.py`, `resource_access["barno-ai"].roles`): ularni
    Keycloak administratori aynan Barno uchun beradi - ishoniladi, ADMIN
    ham. Realm rollari (boshqa tizimlar uchun berilganlar) u yerda umuman
    o'qilmaydi, shuning uchun eski `SSO_TRUSTED_ROLES` suzgichi kerak emas.
    `sso` argumenti chaqiruvchilar manbani aniq aytishi uchun qoldi.
    """
    del sso
    return list(source)


# --- holat (user_admin) -----------------------------------------------------------


@dataclass(frozen=True)
class AdminState:
    """`user_admin` qatori. Qator yo'q - hamma narsa manbadagidek."""

    actor_id: int
    #: `None` - manba rollari; ro'yxat (bo'sh ham) - admin qo'ygan rollar.
    roles: tuple[str, ...] | None = None
    disabled: bool = False
    token_version: int = 0
    note: str | None = None
    updated_at: float | None = None
    updated_by: str | None = None
    #: `False` - ombor o'qilmadi va bu SUKUT holati (`state` izohi): versiya
    #: haqiqiy emas, ya'ni u bilan tokenni rad etib bo'lmaydi.
    loaded: bool = True


def _roles_json(raw: Any, actor_id: Any) -> tuple[str, ...] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = None
    if not isinstance(value, list):
        # Qo'lda buzilgan qator: manba rollariga qaytamiz - taxmin qilib
        # kimgadir ADMIN berib yuborishdan ko'ra xavfsiz.
        log.error("user_admin.roles buzilgan (actor %s) - manba rollari ishlatildi", actor_id)
        return None
    return tuple(str(r) for r in value if isinstance(r, str) and r.strip())


def _state_of(row: Mapping[str, Any] | None, actor_id: int) -> AdminState:
    if not row:
        return AdminState(actor_id=actor_id)
    return AdminState(
        actor_id=actor_id,
        roles=_roles_json(row.get("roles"), actor_id),
        disabled=bool(row.get("disabled")),
        token_version=int(row.get("token_version") or 0),
        note=row.get("note"),
        updated_at=row.get("updated_at"),
        updated_by=row.get("updated_by"),
    )


def state(actor_id: int, *, db: Database | None = None) -> AdminState:
    """Bitta odamning admin holati.

    OMBOR O'QILMASA - sukut holati (bloklanmagan, versiya 0, manba rollari)
    va jurnalga yoziladi. Ataylab "ochiq" tomonga: disk yoki fayl nosozligi
    HAMMANI, shu jumladan uni tuzatishi kerak bo'lgan adminni ham, tizimdan
    chiqarib yuborardi. Shaxsning o'zi (parol, SSO) baribir manbada
    tekshiriladi - bu yerda faqat qo'shimcha cheklovlar turadi.
    """
    try:
        row = (db or get_db()).row("SELECT * FROM user_admin WHERE actor_id = ?", (int(actor_id),))
    except (sqlite3.Error, OSError):
        log_limited("admin_users.state", "user_admin o'qilmadi - sukut holati ishlatildi",
                    exc_info=True)
        return AdminState(actor_id=int(actor_id), loaded=False)
    return _state_of(row, int(actor_id))


def _states(db: Database) -> dict[int, AdminState]:
    rows = _safe_rows(db, "SELECT * FROM user_admin")
    return {int(r["actor_id"]): _state_of(r, int(r["actor_id"])) for r in rows}


# --- samarali rollar -------------------------------------------------------------


def _dedupe(roles: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for role in roles:
        if role not in seen:
            seen.add(role)
            out.append(role)
    return out


def _effective_roles(source: Iterable[str], st: AdminState, bootstrap: bool, *,
                     sso: bool) -> list[str]:
    """Samarali rollar - ular HISOBLANADIGAN YAGONA joy (sessiya, kirish,
    bot va panel shu yerdan o'tadi).

    `sso` - majburiy nomli argument, ataylab default'siz: yangi chaqiruvchi
    manbani "unutib", Keycloak rollariga jimgina ishonib qo'ymasin.
    Admin qo'ygan rollar (`st.roles`) suzilmaydi - bu admin qarori.
    """
    roles = _dedupe(st.roles if st.roles is not None else _source_roles(source, sso=sso))
    if bootstrap and ADMIN not in roles:
        roles.append(ADMIN)
    return roles


def effective(user: AuthUser, *, login: str | None = None,
              admin_state: AdminState | None = None) -> AuthUser:
    """Manbadagi `AuthUser` -> admin qarorlari qo'yilgan `AuthUser`.

    Rollar: `user_admin.roles` (bo'lsa), aks holda manbaniki; `admin_logins`
    dagi odamga ADMIN har doim qo'shiladi. `login` - SSO logini (zahira
    hisobda yo'q, u yerda email login vazifasini bajaradi). Shu sababli
    `login is not None` - SSO manbasi (`is_bootstrap` bilan bir xil qoida).
    """
    st = admin_state if admin_state is not None else state(user.actorId)
    roles = _effective_roles(user.roles, st, is_bootstrap(user.email, login),
                             sso=login is not None)
    if roles == list(user.roles):
        return user
    return user.model_copy(update={"roles": roles})


@dataclass(frozen=True)
class Access:
    """Sessiya uchun hukm: samarali foydalanuvchi, bloklanganmi, versiya."""

    user: AuthUser
    blocked: bool
    token_version: int
    bootstrap: bool
    #: Holat ombordan haqiqatan o'qildimi. `False` bo'lsa versiya tekshirilmaydi:
    #: aks holda ombor nosozligi "hamma joydan chiqarilgan" har bir odamni
    #: (tokenida `ver` > 0) tizimdan haydab yuborardi.
    loaded: bool = True


def access(user: AuthUser, *, login: str | None = None) -> Access:
    """`current_user`, kirish va bot uchun BITTA tekshiruv.

    `admin_logins` dagi odam bloklangan hisoblanmaydi: u panel orqali
    bloklanmaydi, lekin ro'yxatga qo'shilishidan OLDIN bloklangan bo'lsa ham
    `.env` orqali qaytib kira olishi kerak (modul izohi, "zaxira kalit").
    """
    st = state(user.actorId)
    boot = is_bootstrap(user.email, login)
    return Access(
        user=effective(user, login=login, admin_state=st),
        blocked=st.disabled and not boot,
        token_version=st.token_version,
        bootstrap=boot,
        loaded=st.loaded,
    )


# --- katalog: kim bor ---------------------------------------------------------------


@dataclass
class Person:
    """Admin paneldagi bitta odam - uch manbadan yig'ilgan."""

    actor_id: int
    name: str = ""
    #: SSO login (`y.mamajonov`); zahira hisobda - email; faqat tarixda - tarixdagi login.
    login: str | None = None
    email: str | None = None
    department: str | None = None
    position: str | None = None
    sso: bool = False
    local: bool = False
    #: SSO login - `admin_logins` bilan solishtirish uchun (faqat SSO dan).
    sso_login: str | None = None
    source_roles: list[str] = field(default_factory=list)
    last_login_at: float | None = None
    last_seen_at: float | None = None

    @property
    def source(self) -> str:
        """sso | local | both | telemetry (faqat tarixda qolgan: hisob
        manbadan olib tashlangan, lekin savollari bor)."""
        if self.sso and self.local:
            return "both"
        if self.sso:
            return "sso"
        if self.local:
            return "local"
        return "telemetry"

    @property
    def bootstrap(self) -> bool:
        # SSO hisobi - faqat login (`is_bootstrap` izohi); sessiya ham
        # (`api/deps.py`) aynan shunday tekshiradi, panel undan farq qilmasin.
        return is_bootstrap(self.email, (self.sso_login or "") if self.sso else None)

    def auth_user(self) -> AuthUser:
        return AuthUser(
            actorId=self.actor_id,
            email=self.email or self.login or str(self.actor_id),
            fullName=self.name or self.login or self.email or str(self.actor_id),
            position=self.position,
            department=self.department,
            roles=list(self.source_roles),
        )


def _safe_rows(db: Database, sql: str, params: Any = ()) -> list[dict[str, Any]]:
    """O'qish; ombor nosoz bo'lsa bo'sh ro'yxat (panel fayl manbalari bilan
    baribir ochilsin) va jurnalda bitta qator."""
    try:
        return db.rows(sql, params)
    except (sqlite3.Error, OSError):
        log_limited("admin_users.read", "Analitika ombori o'qilmadi (admin panel)", exc_info=True)
        return []


def people(identities: Any, users: Any, *, db: Database | None = None) -> dict[int, Person]:
    """Katalog: `identities.json` ∪ `users.yaml` ∪ tarixdagi (turns) odamlar,
    `actor_id` bo'yicha birlashtirilgan.

    Ikkala manbada bo'lsa (eski hisob SSO bilan kirgan) ism, email va
    ROLLAR SSO dan: kirishning asosiy yo'li shu, zahira hisob rollari faqat
    zahira bilan kirganda amal qiladi. "Oxirgi admin" hisobi shu qoidaga
    tayanadi - ya'ni ehtiyotkor tomonga adashadi (adminni sanamay qolishi
    mumkin, ortiqcha sanamaydi).
    """
    db = db or get_db()
    found: dict[int, Person] = {}

    # 1) Tarix - eng past ustunlik: faqat ism/login surati.
    seen = _safe_rows(db, (
        "SELECT t.actor_id, t.user_name, t.user_login, t.started_at AS last_seen "
        "FROM (SELECT actor_id, MAX(started_at) AS m FROM turns "
        "      WHERE actor_id IS NOT NULL GROUP BY actor_id) g "
        "JOIN turns t ON t.actor_id = g.actor_id AND t.started_at = g.m"))
    for row in seen:
        aid = int(row["actor_id"])
        person = found.get(aid) or Person(actor_id=aid)
        person.last_seen_at = row["last_seen"]
        person.name = person.name or (row["user_name"] or "")
        login = row["user_login"] or None
        person.login = person.login or login
        if login and "@" in login:
            person.email = person.email or login
        found[aid] = person

    # 2) Zahira hisoblar (`users.yaml`).
    for aid in sorted(_ids(users)):
        stored = users.by_actor_id(aid)
        if stored is None:
            continue
        person = found.get(aid) or Person(actor_id=aid)
        person.local = True
        person.name = stored.full_name or person.name
        person.email = stored.email
        person.login = stored.email
        person.department = stored.department or person.department
        person.position = stored.position or person.position
        person.source_roles = list(stored.roles)
        found[aid] = person

    # 3) SSO - eng yuqori ustunlik.
    for aid in sorted(_ids(identities)):
        ident = identities.by_actor_id(aid)
        if ident is None:
            continue
        person = found.get(aid) or Person(actor_id=aid)
        person.sso = True
        person.sso_login = ident.username or None
        person.name = ident.full_name or ident.username or person.name
        person.email = ident.email or person.email
        person.login = ident.username or person.login
        person.department = ident.department or person.department
        person.position = ident.position or person.position
        person.source_roles = list(ident.roles)
        person.last_login_at = ident.last_login_at or None
        found[aid] = person

    # Oxirgi muvaffaqiyatli kirish - zahira hisob uchun yagona manba, SSO
    # uchun esa `identities.json` bilan solishtiriladi (kattasi olinadi).
    for row in _safe_rows(db, ("SELECT actor_id, MAX(ts) AS at FROM auth_events "
                               "WHERE ok = 1 AND actor_id IS NOT NULL GROUP BY actor_id")):
        person = found.get(int(row["actor_id"]))
        if person is not None and row["at"]:
            person.last_login_at = max(person.last_login_at or 0.0, float(row["at"]))
    return found


def _ids(store: Any) -> set[int]:
    try:
        return {int(a) for a in store.actor_ids()}
    except Exception:                                       # noqa: BLE001
        log_limited("admin_users.ids", "Hisoblar manbasi o'qilmadi", exc_info=True)
        return set()


# --- AdminUser --------------------------------------------------------------------


@dataclass
class _Stats:
    turns: int = 0
    channels: list[str] = field(default_factory=list)
    reports: int = 0


def _range_stats(db: Database, since: float, until: float,
                 actor_id: int | None = None) -> dict[int, _Stats]:
    where = "started_at >= ? AND started_at < ? AND actor_id IS NOT NULL"
    params: list[Any] = [since, until]
    if actor_id is not None:
        where += " AND actor_id = ?"
        params.append(actor_id)
    stats: dict[int, _Stats] = {}
    for row in _safe_rows(db, (f"SELECT actor_id, channel, COUNT(*) AS n FROM turns WHERE {where} "
                               "GROUP BY actor_id, channel"), params):
        item = stats.setdefault(int(row["actor_id"]), _Stats())
        item.turns += int(row["n"])
        if row["channel"] not in item.channels:
            item.channels.append(row["channel"])
    rwhere = "created_at >= ? AND created_at < ? AND actor_id IS NOT NULL"
    rparams: list[Any] = [since, until]
    if actor_id is not None:
        rwhere += " AND actor_id = ?"
        rparams.append(actor_id)
    for row in _safe_rows(db, f"SELECT actor_id, COUNT(*) AS n FROM reports WHERE {rwhere} "
                              "GROUP BY actor_id", rparams):
        stats.setdefault(int(row["actor_id"]), _Stats()).reports = int(row["n"])
    order = {name: i for i, name in enumerate(CHANNELS)}
    for item in stats.values():
        item.channels.sort(key=lambda c: order.get(c, len(order)))
    return stats


def admin_user(person: Person, st: AdminState, stats: _Stats | None = None) -> dict[str, Any]:
    """`schemas.admin_users.AdminUser` shaklidagi lug'at."""
    stats = stats or _Stats()
    boot = person.bootstrap
    return {
        "actorId": person.actor_id,
        "name": person.name or person.login or person.email or f"#{person.actor_id}",
        "login": person.login,
        "email": person.email,
        "department": person.department,
        "position": person.position,
        "source": person.source,
        "roles": _effective_roles(person.source_roles, st, boot, sso=person.sso),
        "rolesSource": "admin" if st.roles is not None else "source",
        "rolesLocked": boot,
        "disabled": st.disabled and not boot,
        "lastSeenAt": iso(person.last_seen_at),
        "lastLoginAt": iso(person.last_login_at),
        "turns": stats.turns,
        "channels": list(stats.channels),
        "reports": stats.reports,
    }


def _matches(item: Mapping[str, Any], q: str) -> bool:
    needle = q.strip().casefold()
    if not needle:
        return True
    if needle.isdigit() and int(needle) == item["actorId"]:
        return True
    hay = " ".join(str(item.get(k) or "") for k in ("name", "login", "email", "department",
                                                     "position"))
    return needle in hay.casefold()


def list_users(identities: Any, users: Any, *, q: str | None = None, role: str | None = None,
               status: str | None = None, channel: str | None = None,
               since: float | None = None, until: float | None = None,
               limit: int | None = None, db: Database | None = None) -> list[dict[str, Any]]:
    """`GET /admin/users` - filtrlar bilan. Tartib: oxirgi faollik (yangisi
    birinchi), keyin ism. `limit` - qidiruv (`/admin/search`) uchun."""
    db = db or get_db()
    if since is None or until is None:
        since, until = parse_range(None, None)
    found = people(identities, users, db=db)
    states = _states(db)
    stats = _range_stats(db, since, until)
    wanted_role = (role or "").strip().casefold()
    items: list[dict[str, Any]] = []
    for aid, person in found.items():
        item = admin_user(person, states.get(aid) or AdminState(actor_id=aid), stats.get(aid))
        if q and not _matches(item, q):
            continue
        if wanted_role and wanted_role not in {r.casefold() for r in item["roles"]}:
            continue
        if status == "active" and item["disabled"]:
            continue
        if status in ("blocked", "disabled") and not item["disabled"]:
            continue
        if channel and channel not in item["channels"]:
            continue
        items.append(item)
    items.sort(key=lambda i: (-(found[i["actorId"]].last_seen_at or 0.0), i["name"].casefold(),
                              i["actorId"]))
    return items[:limit] if limit else items


# --- audit ------------------------------------------------------------------------

_INSERT_AUDIT = (
    "INSERT INTO audit_log (ts, admin_actor_id, admin_name, action, target_type, target_id, detail) "
    "VALUES (?,?,?,?,?,?,?)"
)


def write_audit(conn: sqlite3.Connection, admin: AuthUser | None, action: str,
                target_type: str | None, target_id: Any, detail: Mapping[str, Any] | None = None,
                *, ts: float | None = None) -> None:
    """Audit yozuvi - chaqiruvchining TRANZAKSIYASI ichida (`db.transaction()`).

    Alohida tranzaksiyada yozilsa, o'zgarish bo'lib audit yo'qolishi (yoki
    aksincha) mumkin edi. `detail` - JSON; unga parol/token QO'YILMAYDI.
    """
    conn.execute(_INSERT_AUDIT, (
        ts if ts is not None else time.time(),
        admin.actorId if admin is not None else None,
        (admin.fullName or admin.email) if admin is not None else None,
        action,
        target_type,
        None if target_id is None else str(target_id),
        json.dumps(dict(detail), ensure_ascii=False, separators=(",", ":")) if detail else None,
    ))


def audit_entries(*, target_type: str | None = None, target_id: Any = None, limit: int = 20,
                  db: Database | None = None) -> list[dict[str, Any]]:
    """Oxirgi audit yozuvlari (`AuditEntry` shakli), yangisi birinchi."""
    db = db or get_db()
    where, params = [], []
    if target_type is not None:
        where.append("target_type = ?")
        params.append(target_type)
    if target_id is not None:
        where.append("target_id = ?")
        params.append(str(target_id))
    sql = "SELECT * FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    out = []
    for row in _safe_rows(db, sql, params):
        try:
            detail = json.loads(row["detail"]) if row.get("detail") else None
        except ValueError:
            detail = {"raw": row["detail"]}
        out.append({
            "id": row["id"],
            "createdAt": iso(row["ts"]),
            "adminActorId": row.get("admin_actor_id"),
            "adminName": row.get("admin_name"),
            "action": row["action"],
            "targetType": row.get("target_type"),
            "targetId": row.get("target_id"),
            "detail": detail if isinstance(detail, dict) else ({"value": detail} if detail else None),
        })
    return out


# --- bitta odam ---------------------------------------------------------------------


def _person_or_404(actor_id: int, identities: Any, users: Any,
                   db: Database) -> tuple[Person, dict[int, Person]]:
    found = people(identities, users, db=db)
    person = found.get(int(actor_id))
    if person is None:
        raise AdminError("Foydalanuvchi topilmadi", status=404, code="NOT_FOUND")
    return person, found


def _median(values: list[float]) -> int | None:
    return int(round(statistics.median(values))) if values else None


def connector_rows(hub: Any, actor_id: int) -> list[dict[str, Any]]:
    """Odamning HRM/CRM ulanishlari - TOKENSIZ (`ConnectorHub.status`)."""
    try:
        rows = hub.status(str(actor_id))
    except Exception:                                       # noqa: BLE001
        log_limited("admin_users.connectors", "Ulanishlar holati o'qilmadi", exc_info=True)
        return []
    return [connector_row(row) for row in rows]


def connector_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """`ConnectorHub` holati -> `AdminConnector` shakli."""
    state_name = str(row.get("state") or "disconnected")
    return {
        "platform": row.get("id"),
        "connected": state_name == "connected",
        "enabled": bool(row.get("enabled")),
        "login": row.get("login"),
        "expiresAt": row.get("expiresAt"),
        "state": state_name,
    }


def telegram_row(links: Any, actor_id: int) -> dict[str, Any]:
    """Telegram ulanishlari soni va oxirgi tasdiq (mini app ochilgan payt)."""
    try:
        found = links.by_actor(actor_id)
    except Exception:                                       # noqa: BLE001
        log_limited("admin_users.telegram", "Telegram ulanishlari o'qilmadi", exc_info=True)
        found = []
    last = max((link.seen_at for link in found), default=None)
    return {"links": len(found), "lastSeenAt": iso(last) if last else None}


def user_detail(actor_id: int, identities: Any, users: Any, *, hub: Any, links: Any,
                since: float, until: float, db: Database | None = None) -> dict[str, Any]:
    """`GET /admin/users/{actorId}` - `AdminUserDetail` shaklidagi lug'at."""
    db = db or get_db()
    person, _ = _person_or_404(actor_id, identities, users, db)
    st = state(actor_id, db=db)
    stats = _range_stats(db, since, until, actor_id).get(actor_id)
    item = admin_user(person, st, stats)

    counts = (_safe_rows(db, (
        "SELECT COUNT(*) AS turns, "
        "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors, "
        "SUM(CASE WHEN input_mode = 'voice' THEN 1 ELSE 0 END) AS voice "
        "FROM turns WHERE actor_id = ? AND started_at >= ? AND started_at < ?"),
        (actor_id, since, until)) or [{}])[0]
    ttft = [float(r["ttft_ms"]) for r in _safe_rows(db, (
        "SELECT ttft_ms FROM turns WHERE actor_id = ? AND started_at >= ? AND started_at < ? "
        "AND ttft_ms IS NOT NULL LIMIT ?"), (actor_id, since, until, _TTFT_ROWS))]
    recent = _safe_rows(db, "SELECT * FROM turns WHERE actor_id = ? ORDER BY started_at DESC, id DESC "
                            "LIMIT 10", (actor_id,))
    item.update({
        "stats": {
            "turns": int(counts.get("turns") or 0),
            "errors": int(counts.get("errors") or 0),
            "medianTtftMs": _median(ttft),
            "reports": stats.reports if stats else 0,
            "voiceTurns": int(counts.get("voice") or 0),
        },
        "connectors": connector_rows(hub, actor_id),
        "telegram": telegram_row(links, actor_id),
        # `TurnSummary` - savollar ro'yxatidagi AYNI shakl va `reported` ma'nosi.
        "recentTurns": _turn_summaries(db, recent),
        "audit": audit_entries(target_type="user", target_id=actor_id, limit=20, db=db),
        "note": st.note,
        # Import shu yerda: `engine_control` bu modulni (audit, katalog)
        # import qiladi - modul boshida bo'lsa aylanma bo'lardi.
        "engine": _engine_of(actor_id, db),
    })
    return item


def _engine_of(actor_id: int, db: Database) -> dict[str, Any]:
    """`AdminUserDetail.engine` - `services/engine_control.user_engine`."""
    from . import engine_control

    return engine_control.user_engine(actor_id, db=db)


# --- o'zgartirish -----------------------------------------------------------------


def _allowed_roles(found: Mapping[int, Person]) -> dict[str, str]:
    """Qabul qilinadigan rollar: ma'lum uchtasi + manbalarda BOR rollar.

    Kalit - kichik harfda, qiymat - asl yozilishi: `admin` so'ralsa `ADMIN`
    saqlanadi. Yangi ixtiyoriy rol nomi to'qib bo'lmaydi - xato yozilgan rol
    jimgina "hech narsa bermaydigan" rolga aylanardi.
    """
    allowed = {role.lower(): role for role in KNOWN_ROLES}
    for person in found.values():
        for role in person.source_roles:
            allowed.setdefault(role.lower(), role)
    return allowed


def normalize_roles(requested: Iterable[str], found: Mapping[int, Person]) -> list[str]:
    allowed = _allowed_roles(found)
    out: list[str] = []
    for raw in requested:
        key = str(raw).strip().lower()
        if not key:
            continue
        role = allowed.get(key)
        if role is None:
            raise AdminError(f"Noma'lum rol: {str(raw).strip()[:64]}", status=422,
                             code="UNKNOWN_ROLE")
        if role not in out:
            out.append(role)
    return out


def _is_active_admin(person: Person, st: AdminState) -> bool:
    boot = person.bootstrap
    roles = _effective_roles(person.source_roles, st, boot, sso=person.sso)
    return ADMIN in roles and not (st.disabled and not boot)


def _upsert_state(conn: sqlite3.Connection, st: AdminState, *, by: str | None, now: float) -> None:
    conn.execute(
        "INSERT INTO user_admin (actor_id, roles, disabled, token_version, note, updated_at, updated_by) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(actor_id) DO UPDATE SET roles=excluded.roles, "
        "disabled=excluded.disabled, token_version=excluded.token_version, note=excluded.note, "
        "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (st.actor_id, None if st.roles is None else json.dumps(list(st.roles), ensure_ascii=False),
         1 if st.disabled else 0, st.token_version, st.note, now, by),
    )


def _read_state(conn: sqlite3.Connection, actor_id: int) -> AdminState:
    row = conn.execute("SELECT * FROM user_admin WHERE actor_id = ?", (actor_id,)).fetchone()
    return _state_of(dict(row) if row is not None else None, actor_id)


def _by(admin: AuthUser) -> str:
    return (admin.email or admin.fullName or str(admin.actorId))[:128]


def _write_failed(exc: BaseException) -> AdminError:
    log.error("Admin amali saqlanmadi: %s", exc)
    return AdminError("O'zgarish saqlanmadi - server xatosi, qayta urinib ko'ring", status=503,
                      code="STORE_FAILED")


_UNSET: Any = object()


def update_user(admin: AuthUser, actor_id: int, identities: Any, users: Any, *,
                roles: Any = _UNSET, disabled: Any = _UNSET, note: Any = _UNSET,
                hub: Any = None, db: Database | None = None,
                now: float | None = None) -> dict[str, Any]:
    """`PATCH /admin/users/{actorId}`. Berilmagan maydon o'zgarmaydi;
    `roles=None` - manba rollariga qaytarish.

    Himoyalar (409):
      * admin O'ZIDAN ADMIN ni ololmaydi va O'ZINI bloklay olmaydi - aks
        holda bitta noto'g'ri bosish uni paneldan chiqarib yuborardi;
      * `admin_logins` dagi odamni bloklab bo'lmaydi (u zaxira kalit);
      * oxirgi faol ADMIN ni pasaytirib yoki bloklab bo'lmaydi.
    Bloklashda sessiya versiyasi ham oshadi: blok olib tashlanganda eski
    tokenlar qayta tirilmasin.
    """
    db = db or get_db()
    now = time.time() if now is None else now
    actor_id = int(actor_id)
    try:
        with db.transaction() as conn:
            # Katalog va holatlar TRANZAKSIYA ICHIDA o'qiladi: "oxirgi admin"
            # hisobi ikki admin bir vaqtda bir-birini pasaytirganda ham to'g'ri.
            person, found = _person_or_404(actor_id, identities, users, db)
            old = _read_state(conn, actor_id)
            new_roles = old.roles
            if roles is not _UNSET:
                new_roles = None if roles is None else tuple(normalize_roles(roles, found))
            new_disabled = old.disabled if disabled is _UNSET else bool(disabled)
            new_note = old.note
            if note is not _UNSET:
                new_note = (str(note).strip()[:NOTE_LIMIT] or None) if note is not None else None
            blocking = new_disabled and not old.disabled
            new = AdminState(
                actor_id=actor_id, roles=new_roles, disabled=new_disabled,
                token_version=old.token_version + (1 if blocking else 0),
                note=new_note, updated_at=now, updated_by=_by(admin),
            )
            boot = person.bootstrap
            is_self = int(admin.actorId) == actor_id
            new_roles_eff = _effective_roles(person.source_roles, new, boot, sso=person.sso)
            if is_self and ADMIN not in new_roles_eff:
                raise AdminError("O'zingizdan ADMIN rolini olib bo'lmaydi", status=409,
                                 code="SELF_DEMOTE")
            if is_self and new.disabled:
                raise AdminError("O'zingizni bloklab bo'lmaydi", status=409, code="SELF_BLOCK")
            if boot and new.disabled and not old.disabled:
                raise AdminError("Bu hisob admin_logins ro'yxatida - uni bloklab bo'lmaydi",
                                 status=409, code="BOOTSTRAP_LOCKED")
            if _is_active_admin(person, old) and not _is_active_admin(person, new):
                states = {aid: _read_state(conn, aid) for aid in found}
                others = sum(1 for aid, p in found.items()
                             if aid != actor_id and _is_active_admin(p, states[aid]))
                if others == 0:
                    raise AdminError("Oxirgi administratorni pasaytirib yoki bloklab bo'lmaydi",
                                     status=409, code="LAST_ADMIN")

            changed = (new.roles != old.roles or new.disabled != old.disabled
                       or new.note != old.note)
            if changed:
                _upsert_state(conn, new, by=_by(admin), now=now)
            if new.roles != old.roles:
                write_audit(conn, admin, "user.roles", "user", actor_id, {
                    "from": _effective_roles(person.source_roles, old, boot, sso=person.sso),
                    "to": new_roles_eff,
                    "override": None if new.roles is None else list(new.roles),
                }, ts=now)
            if new.disabled != old.disabled:
                write_audit(conn, admin, "user.block" if new.disabled else "user.unblock",
                            "user", actor_id,
                            {"tokenVersion": new.token_version} if new.disabled else None, ts=now)
            if new.note != old.note:
                # Izohning o'zi emas - uzunligi va boshi (`report.note` kabi):
                # to'liq matn `user_admin` da, jurnal esa "kim, qachon" uchun.
                write_audit(conn, admin, "user.note", "user", actor_id,
                            {"chars": len(new.note or ""), "preview": (new.note or "")[:120]},
                            ts=now)
    except AdminError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise _write_failed(exc) from exc

    if blocking and hub is not None:
        # Xotiradagi HRM paroli faqat o'zini yangilash uchun turardi -
        # bloklangan odam uchun u endi kerak emas (`/auth/logout` kabi).
        try:
            hub.forget_password(str(actor_id))
        except Exception:                                   # noqa: BLE001
            log_limited("admin_users.forget", "HRM paroli xotiradan o'chirilmadi", exc_info=True)
    log.info("Admin (%s): foydalanuvchi %s o'zgartirildi", admin.actorId, actor_id)
    since, until = parse_range(None, None, now=now)
    return admin_user(person, new, _range_stats(db, since, until, actor_id).get(actor_id))


def signout(admin: AuthUser, actor_id: int, identities: Any, users: Any, *, links: Any = None,
            hub: Any = None, db: Database | None = None, now: float | None = None,
            slack: Any = None) -> int:
    """`POST /admin/users/{actorId}/signout` - hamma sessiyalar tugaydi.

    Versiya oshadi (veb va mini app tokenlari 401 oladi), Telegram bot
    va Slack (`slack` - `slack_links.LinkStore`) ulanishlari uziladi (u
    yerdagi sessiya JWT emas - u faqat ulanish bilan yashaydi) va
    xotiradagi HRM paroli o'chiriladi. HRM/CRM ulanishlari
    QOLADI: ular sessiya emas, odamning saqlangan ulanishi (`/auth/logout`
    izohi); ularni uzish - alohida tugma.
    """
    db = db or get_db()
    now = time.time() if now is None else now
    actor_id = int(actor_id)
    telegram = len(links.by_actor(actor_id)) if links is not None else 0
    slack_links = len(slack.by_actor(actor_id)) if slack is not None else 0
    try:
        with db.transaction() as conn:
            _person_or_404(actor_id, identities, users, db)
            old = _read_state(conn, actor_id)
            new = AdminState(actor_id=actor_id, roles=old.roles, disabled=old.disabled,
                             token_version=old.token_version + 1, note=old.note)
            _upsert_state(conn, new, by=_by(admin), now=now)
            detail = {"tokenVersion": new.token_version, "telegramLinks": telegram}
            if slack_links:
                detail["slackLinks"] = slack_links
            write_audit(conn, admin, "user.signout", "user", actor_id, detail, ts=now)
    except AdminError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise _write_failed(exc) from exc
    if links is not None:
        links.unlink_actor(actor_id)
    if slack is not None:
        try:
            slack.unlink_actor(actor_id)
        except OSError:
            log_limited("admin_users.slack", "Slack ulanishi uzilmadi", exc_info=True)
    if hub is not None:
        try:
            hub.forget_password(str(actor_id))
        except Exception:                                   # noqa: BLE001
            log_limited("admin_users.forget", "HRM paroli xotiradan o'chirilmadi", exc_info=True)
    log.info("Admin (%s): foydalanuvchi %s hamma sessiyalardan chiqarildi", admin.actorId, actor_id)
    return new.token_version


def disconnect_connector(admin: AuthUser, actor_id: int, platform: str, identities: Any,
                         users: Any, *, hub: Any, db: Database | None = None) -> dict[str, Any]:
    """`DELETE /admin/users/{actorId}/connectors/{platform}` - odamning
    o'zi "+" menyusida bosadigan AYNI uzish (`ConnectorHub.disconnect`: CRM
    da refresh_token bekor qilinadi, HRM paroli xotiradan o'chadi)."""
    from .integrations.connectors import ConnectorError

    db = db or get_db()
    actor_id = int(actor_id)
    _person_or_404(actor_id, identities, users, db)
    before = {row["platform"]: row for row in connector_rows(hub, actor_id)}
    try:
        result = hub.disconnect(str(actor_id), platform)
    except ConnectorError as exc:
        raise AdminError(str(exc), status=exc.status, code=exc.code or "CONNECTOR") from exc
    try:
        with db.transaction() as conn:
            write_audit(conn, admin, "user.connector.disconnect", "user", actor_id, {
                "platform": platform,
                "state": (before.get(platform) or {}).get("state"),
            })
    except (sqlite3.Error, OSError) as exc:
        # Uzish BAJARILDI - faqat audit yozilmadi. Adminga xato deyish uni
        # qayta bosishga undardi; jurnalda qoladi.
        log.error("Audit yozilmadi (ulanish uzildi, actor %s): %s", actor_id, exc)
    log.info("Admin (%s): %s ulanishi uzildi (%s)", admin.actorId, platform, actor_id)
    return connector_row(result)


def unlink_telegram(admin: AuthUser, actor_id: int, identities: Any, users: Any, *,
                    links: Any, db: Database | None = None) -> int:
    """`DELETE /admin/users/{actorId}/telegram` - hamma Telegram ulanishlari."""
    db = db or get_db()
    actor_id = int(actor_id)
    _person_or_404(actor_id, identities, users, db)
    removed = links.unlink_actor(actor_id)
    try:
        with db.transaction() as conn:
            write_audit(conn, admin, "user.telegram.unlink", "user", actor_id, {"links": removed})
    except (sqlite3.Error, OSError) as exc:
        log.error("Audit yozilmadi (Telegram uzildi, actor %s): %s", actor_id, exc)
    log.info("Admin (%s): Telegram ulanishlari uzildi (%s): %d", admin.actorId, actor_id, removed)
    return removed

"""Foydalanuvchining O'Z HRM / CRM hisobi: ulanish, saqlash, yangilash.

`crm_auth.py` dagi agent sessiyasidan FARQI: u yerda BITTA umumiy hisob
(agentniki), bu yerda esa HAR BIR foydalanuvchining O'Z ulanishi turadi va
yuqoridagi xizmatga uning O'Z tokeni beriladi. Shunda "men bugun
kechikdimmi?" degan savol haqiqatan o'sha odam haqida bo'ladi - umumiy token
bilan esa javob token EGASI haqida bo'lardi (`core/config.py`, `hrm_token`).

KIM NIMANI BOSHQARADI (2026-11-12, ega qarori):

  * HRM ham SSO kirishida O'ZI ulanadi (`crm_sso.HrmSso`, `api/v1/auth._connect_sso`;
    jonli tekshirilgan 2026-11-12). Login + parol bilan qo'lda ulash OLIB TASHLANDI
    (2026-11-12, ega so'rovi): `POST /connectors/hrm/connect` - 410. Odam HRM
    holatini ko'radi va uzishi mumkin (`USER_PLATFORMS`, `/api/v1/connectors`);
    qayta ulash - BRB-Tech ID bilan qayta kirish. Avval qo'lda ulanganlarning
    yozuvi tokeni (10 soat) tugaguncha ishlaydi, keyin "expired".
  * CRM odamga KO'RINMAYDI va uni odam boshqarmaydi: ulanish SSO kirishida
    o'zi ochiladi (`api/v1/auth.py`, `crm_sso.py`). Uni ombor va admin panel
    biladi (`PLATFORMS`); odamning endpointlarida `crm` - 404.
  * KALIT YO'Q: ulangan tizim har doim ishlatiladi. Yozuvdagi `enabled`
    maydoni eski formatdan qolgan va hech narsani hal qilmaydi (`tokens`).

IKKI PLATFORMA:

  HRM   SSO sessiyasidan (`via: "sso"`) - umumiy access token (pastda). ESKI
        qo'lda ulangan yozuv (`token`, `expires_at`; HRM `/api/authenticate`
        bergan 10 soatlik token) muddati `hrm_margin` dan KO'P qolgandagina
        beriladi va yangilanmaydi - tugagach "expired".

  CRM   refresh_token (doimiy) -> access_token, 300 SEKUND. Har savol
        oldidan tekshiriladi: muddati `crm_margin` dan kam qolgan bo'lsa
        yangilanadi. ROTATSIYA: javobda yangi refresh_token kelsa o'sha
        saqlanadi. Refresh 400/401 bersa token o'lgan - holat "expired",
        odam vebga BRB-Tech ID bilan qayta kiradi. refresh_token ning
        manbasi ikki xil:

        SSO sessiyasidan (`via: "sso"`, 2026-11-12) - HOZIRGI YAGONA YO'L.
        Brauzer orqali SSO da parol bizga kelmaydi: CRM ulanishi Keycloak
        SESSIYASINING o'zi (`barno-ai` client'iga berilgan refresh_token,
        `offline_access`). access_token ni KEYCLOAK yangilaydi va bekor
        qilish ham o'sha yerda (`crm_sso.py`).

        ESKI yozuvlar (`via` yo'q). 2026-11-12 gacha odam CRM ga login +
        parol bilan qo'lda ulanardi (Keycloak parol granti, `crm-client`).
        Yangi bunday ulanish OCHILMAYDI, saqlanganlari esa ishlayveradi:
        ularni CRM o'zi yangilaydi (`POST /api/auth/refresh`) va bekor
        qiladi (`CrmUserAuth`) - odamning keyingi SSO kirishigacha.

SSO SESSIYASI - BITTA YOZUV (`SESSION`, omborda `sso` kaliti). CRM va HRM ikkalasi
SSO dan ulanganda (`via: "sso"`) ularning yozuvida TOKEN YO'Q: ikkalasi `sso`
yozuvidagi BITTA Keycloak sessiyasidan BIR XIL access tokenni oladi va u BITTA
joyda yangilanadi (`_sso_access`). Sessiya o'lsa ikkala holat "expired". Oxirgi
SSO ulanish uzilganda sessiya Keycloak'da bekor qilinadi. 2026-11-12 gacha
yozilgan (sessiya CRM yozuvining ichida) fayl o'qilganda o'zi yangi shaklga
o'tadi (`_migrate`).

SAQLASH. `refresh_token` PAROLDAN FARQI YO'Q - uni qo'lga kiritgan odam o'sha
foydalanuvchi nomidan cheksiz token yasay oladi. Shuning uchun:

  * `data/connectors/` da, 600 huquq bilan, atomik yoziladi (`data/`
    gitignore'da);
  * PAROL HECH QAYERDA YO'Q: na diskda, na xotirada (2026-11-12 gacha HRM
    paroli xotirada turardi - qo'lda ulangan HRM ni 10 soatdan keyin qayta
    kiritish uchun; qo'lda ulash olib tashlanganda u ham ketdi);
  * tokenlar jurnalga, xato matniga va API javobiga TUSHMAYDI - klient
    faqat holatni ko'radi: ulanmagan / ulangan / muddati tugagan.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import stat
import tempfile
import threading
import time

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .crm_auth import CrmAuthError, _safe, post_json

log = logging.getLogger(__name__)

#: Ombor va admin panel biladigan platformalar.
PLATFORMS: tuple[str, ...] = ("hrm", "crm")
#: Odam O'ZI boshqaradigan platformalar (`/api/v1/connectors`): ulaydi, holatini
#: ko'radi, uzadi. CRM bu yerda YO'Q - u SSO kirishida o'zi ulanadi va odamga
#: ko'rinmaydi (modul izohi).
USER_PLATFORMS: tuple[str, ...] = ("hrm",)
LABELS = {"hrm": "HRM", "crm": "CRM"}
#: Ombordagi umumiy SSO sessiyasi yozuvining kaliti (platforma EMAS: holatda,
#: admin panelda va `PLATFORMS` da yo'q).
SESSION = "sso"


def _via_sso(entry: Any) -> bool:
    """Ulanish umumiy SSO sessiyasidanmi (yozuvida token yo'q)."""
    return isinstance(entry, dict) and entry.get("via") == "sso"


def _migrate(data: dict[str, Any]) -> None:
    """2026-11-12 gacha: SSO sessiyasi CRM yozuvining ICHIDA edi (`via: "sso"` va
    `refresh_token`). Endi u alohida `sso` yozuvida - CRM va HRM uni bo'lishadi.
    Joyida, xotirada; keyingi yozuv diskka yangi shaklda yozadi."""
    for user in data.values():
        if not isinstance(user, dict) or SESSION in user:
            continue
        crm = user.get("crm")
        if _via_sso(crm) and "refresh_token" in crm:
            user[SESSION] = {"login": crm.get("login"), "refresh_token": crm.get("refresh_token") or "",
                             "expired": bool(crm.get("expired")), "connected_at": crm.get("connected_at")}
            user["crm"] = {k: v for k, v in crm.items() if k not in ("refresh_token", "expired")}

#: CRM `expires_in` yo'q yoki aqldan tashqari bo'lsa - hujjatdagi 300 s.
_CRM_DEFAULT_TTL = 300.0
#: Qo'lda ulash so'ralganda (eski klient) - u endi yo'q.
MSG_SSO_ONLY = ("HRM endi BRB-Tech ID bilan kirganda o'zi ulanadi - Barno'dan chiqib, "
                "BRB-Tech ID bilan qayta kiring")


class ConnectorError(Exception):
    """`status` HTTP kodi bo'lib qaytadi, matn foydalanuvchiga ko'rinadi.

    Matnda token, ichki manzil yoki sir BO'LMASLIGI kerak - hamma xabar
    shu faylda yasaladi va `_safe` dan o'tadi.
    """

    def __init__(self, message: str, *, status: int = 400, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _normalize(base_url: str) -> str:
    """Sxema qo'shiladi, yozilmagan bo'lsa - `crm_auth.py` dagi kabi."""
    base = (base_url or "").strip().rstrip("/")
    if base and "://" not in base:
        base = f"https://{base}"
    return base


def _ttl(value: Any, default: float) -> float:
    """`expires_in` ga ishonamiz, lekin ko'r-ko'rona emas."""
    try:
        ttl = float(value or 0)
    except (TypeError, ValueError):
        ttl = 0.0
    return ttl if 30.0 <= ttl <= 24 * 3600.0 else default


# --- HRM ------------------------------------------------------------------


class HrmAuth:
    """HRM manzili - faqat "sozlanganmi" uchun (holat va admin panel). Ulanish SSO
    kirishida (`crm_sso.HrmSso`); login + parol bilan kirish 2026-11-12 da olib
    tashlandi."""

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self.base_url = _normalize(base_url)
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url)


# --- CRM ------------------------------------------------------------------


class CrmUserAuth:
    """CRM, ESKI (qo'lda ulangan) yozuvlar: CRM refresh -> access_token, uzishda logout.

    YANGI ULANISH BU YERDAN OCHILMAYDI (2026-11-12): parol bilan kirish
    (Keycloak parol granti) olib tashlandi - CRM SSO kirishida ulanadi
    (`crm_sso.py`). `token_url`, `client_id` va `client_secret` endi hech
    qayerga yuborilmaydi; ular faqat `configured` shartida qoldi - eski
    yozuvlar avvalgidek AYNAN shu to'rt sozlama to'liq bo'lgandagina
    yangilanadi (sozlamalarni olib tashlash - deploy bilan birga, alohida).
    """

    def __init__(self, token_url: str, client_id: str, client_secret: str,
                 base_url: str, *, timeout: float = 10.0) -> None:
        self.token_url = (token_url or "").strip()
        self.client_id = client_id or ""
        self._client_secret = client_secret or ""
        self.base_url = _normalize(base_url)
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token_url and self.client_id and self._client_secret and self.base_url)

    def refresh(self, refresh_token: str) -> tuple[str, str, float]:
        """-> (access_token, yangi refresh_token yoki "", muddati).

        `CrmAuthError` 400/401 = token o'lgan (bekor qilingan yoki 30 kun
        ishlatilmagan) - chaqiruvchi holatni "expired" qiladi. Qolgani
        vaqtinchalik: tarmoq, 429, 5xx.
        """
        try:
            data = post_json(f"{self.base_url}/api/auth/refresh",
                             {"refresh_token": refresh_token}, self.timeout)
        except CrmAuthError as exc:
            raise ConnectorError(_safe(str(exc)), status=exc.status or 502,
                                 code=exc.code) from None
        access = str(data.get("access_token") or "")
        if not access:
            raise ConnectorError("CRM javobida access_token yo'q", status=502, code="BAD_RESPONSE")
        return access, str(data.get("refresh_token") or ""), _ttl(data.get("expires_in"), _CRM_DEFAULT_TTL)

    def logout(self, refresh_token: str) -> None:
        """`refresh_token` ni CRM da BEKOR qiladi - uzish tugmasi. Eng yaxshi
        harakat: xato bo'lsa jurnalga yoziladi, uzish baribir bajariladi."""
        try:
            post_json(f"{self.base_url}/api/auth/logout", {"refresh_token": refresh_token}, self.timeout)
        except CrmAuthError as exc:
            log.warning("CRM logout: %s", _safe(str(exc)))


# --- saqlash --------------------------------------------------------------


class ConnectorStore:
    """`{user_id: {platform: {...}}}` - bitta JSON fayl, 600, atomik.

    Xotirada keshlanadi va fayl o'zgargani `stat` bilan aniqlanadi
    (`mtime_ns` + hajm) - ikki jarayon bir faylni bo'lishsa ham bir-birining
    yozuvini ko'radi.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._mark: tuple[int, int] | None = None

    def get(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Odamning barcha ulanishlari - NUSXA, o'zgartirish `set` orqali."""
        with self._lock:
            self._reload()
            return copy.deepcopy(self._data.get(user_id) or {})

    def set(self, user_id: str, platform: str, entry: dict[str, Any] | None) -> None:
        """`entry=None` - o'chirish."""
        with self._lock:
            self._reload()
            user = self._data.setdefault(user_id, {})
            if entry is None:
                user.pop(platform, None)
                if not user:
                    self._data.pop(user_id, None)
            else:
                user[platform] = copy.deepcopy(entry)
            self._write()

    def update(self, user_id: str, changes: dict[str, dict[str, Any] | None]) -> None:
        """Bir nechta yozuv BITTA yozishda (`None` - o'chirish): sessiya va uning
        ulanishlari bir-biridan ajralib qolmasin."""
        with self._lock:
            self._reload()
            user = self._data.setdefault(user_id, {})
            for key, entry in changes.items():
                if entry is None:
                    user.pop(key, None)
                else:
                    user[key] = copy.deepcopy(entry)
            if not user:
                self._data.pop(user_id, None)
            self._write()

    def replace_if(self, user_id: str, platform: str, expected: str, /, **fields: Any) -> bool:
        """Mavjud yozuvning ayrim maydonlarini yangilaydi, lekin FAQAT yozuv hali
        o'sha sessiya bo'lsa (saqlangan `refresh_token` == `expected`): tekshiruv va
        yozish bitta qulf ostida. `get` + `set` emas - ular orasida boshqa ip yozgan
        narsa yo'qolardi. Shu orada ulanish uzilgan yoki odam qayta kirgan bo'lsa
        hech narsa yozilmaydi va `False` qaytadi. `expected` faqat pozitsion -
        `fields` ichida ham `refresh_token` (yangi qiymat) kelishi mumkin."""
        with self._lock:
            self._reload()
            entry = (self._data.get(user_id) or {}).get(platform)
            if entry is None or entry.get("refresh_token") != expected:
                return False
            if any(entry.get(key) != value for key, value in fields.items()):
                entry.update(copy.deepcopy(fields))
                self._write()
            return True

    def user_count(self) -> int:
        with self._lock:
            self._reload()
            return len(self._data)

    def _reload(self) -> None:
        try:
            info = self.path.stat()
        except OSError:
            self._data, self._mark = {}, None
            return
        mark = (info.st_mtime_ns, info.st_size)
        if mark == self._mark:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Buzilgan fayl xotiradagini O'CHIRMAYDI: keyingi yozuv uni
            # to'g'ri shaklda qayta yozadi.
            log.warning("Ulanishlar fayli o'qilmadi (%s): %s", self.path, exc)
            return
        self._data = raw if isinstance(raw, dict) else {}
        _migrate(self._data)
        self._mark = mark

    def _write(self) -> None:
        """ATOMIK va 600 - `crm_auth.py` dagi `_save` bilan bir xil sabablarga
        ko'ra: yarim yozilgan fayl "hamma uzildi" degani bo'lardi, huquq esa
        almashtirishdan OLDIN qo'yiladi."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent,
                prefix=".connectors.", suffix=".tmp", delete=False,
            )
            try:
                with handle:
                    json.dump(self._data, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
                os.replace(handle.name, self.path)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
            info = self.path.stat()
            self._mark = (info.st_mtime_ns, info.st_size)
        except OSError as exc:
            log.error("Ulanishlar saqlanmadi (%s): %s", self.path, exc)
            raise ConnectorError("Ulanish saqlanmadi - server xatosi", status=500,
                                 code="STORE_FAILED") from exc


# --- markaz ---------------------------------------------------------------


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


class ConnectorHub:
    """Holat, ulanish, uzish - va chat uchun yaroqli tokenlar."""

    def __init__(self, store: ConnectorStore, hrm: HrmAuth, crm: CrmUserAuth, *,
                 hrm_margin: float = 300.0, crm_margin: float = 180.0,
                 sso: Any | None = None, session: Any | None = None,
                 hrm_check: Any | None = None) -> None:
        self.store = store
        self.hrm = hrm
        #: ESKI (qo'lda ulangan) CRM yozuvlarini yangilash va bekor qilish uchun.
        self.crm = crm
        #: CRM ni SSO sessiyasidan ulash (`crm_sso.CrmSso`): `configured`,
        #: `accepts` (kirishda tekshiruv). Yo'q bo'lsa CRM ulanishi ochilmaydi.
        self.sso = sso
        #: Umumiy SSO sessiyasini yangilash/bekor qilish (`crm_sso.SsoSession`):
        #: `configured`, `refresh`, `revoke`. Berilmasa - `sso` (u ham sessiya).
        self.session = session if session is not None else sso
        #: HRM ni SSO sessiyasidan ulash (`crm_sso.HrmSso`): `configured`, `check`.
        #: Yo'q bo'lsa HRM faqat qo'lda ulanadi.
        self.hrm_check = hrm_check
        self.hrm_margin = hrm_margin
        self.crm_margin = crm_margin
        self._lock = threading.Lock()
        #: user_id -> (access_token, muddati `time.monotonic()` bo'yicha).
        #: Faqat xotirada: 300 sekundlik tokenni diskka yozish ma'nosiz.
        self._crm_cache: dict[str, tuple[str, float]] = {}
        #: Xuddi shunday - umumiy SSO sessiyasining access tokeni (CRM va HRM).
        self._sso_cache: dict[str, tuple[str, float]] = {}
        #: Har odam uchun alohida qulf: bir vaqtda kelgan ikki savol BITTA
        #: yangilashni bo'lishadi, aks holda rotatsiya bir-birini bekor qilardi.
        self._user_locks: dict[str, threading.Lock] = {}

    # --- tashqi yuz -------------------------------------------------------

    def status(self, user_id: str, platforms: tuple[str, ...] = PLATFORMS) -> list[dict[str, Any]]:
        """Holat. Sukut bo'yicha HAMMA platforma (admin panel); odamning o'ziga
        faqat `USER_PLATFORMS` ko'rsatiladi (`api/v1/connectors.py`)."""
        data = self.store.get(user_id)
        return [self._entry_status(p, data.get(p), user_id=user_id, session=data.get(SESSION))
                for p in platforms]

    def adopt_crm(self, user_id: str, username: str, access: str, refresh: str, ttl: float,
                  *, revoke_old: bool = False, via: str = "") -> dict[str, Any]:
        """Tayyor Keycloak sessiyasini CRM ulanishi sifatida saqlaydi.

        SSO kirishida (`api/v1/auth.py`) Keycloak javobi ikki ish qiladi:
        shaxsni beradi VA shu yerda CRM ulanishiga aylanadi - odam CRM ga
        alohida kirmaydi. `revoke_old`: oldingi `refresh_token` bekor
        qilinadi - har kirish yangi doimiy kredensial yasaydi, eskilari
        to'planib qolmasin. `via="sso"`: sessiya BIZNING client'ga berilgan -
        uni CRM emas, Keycloak yangilaydi va bekor qiladi (modul izohi).
        """
        if via == "sso":
            return self.adopt_sso(user_id, username, access, refresh, ttl, ("crm",),
                                  revoke_old=revoke_old)["crm"]
        old = self.store.get(user_id).get("crm")
        # `enabled` har doim `True` yoziladi: kalit yo'q, va eski yozuvdagi
        # `enabled: false` (odam bir paytlar CRM ni o'chirib qo'ygan) qayta
        # kirishdan keyin qolmaydi.
        entry = {"login": username, "refresh_token": refresh, "expired": False,
                 "enabled": True, "connected_at": time.time()}
        with self._lock:
            self._crm_cache[user_id] = (access, time.monotonic() + ttl)
        self.store.set(user_id, "crm", entry)
        stale = (old or {}).get("refresh_token")
        if revoke_old and stale and stale != refresh:
            self._revoke_crm(old, stale)
        log.info("Ulanish: %s -> crm", user_id)
        return self._entry_status("crm", entry, user_id=user_id)

    def adopt_sso(self, user_id: str, username: str, access: str, refresh: str, ttl: float,
                  platforms: tuple[str, ...], *, revoke_old: bool = False) -> dict[str, dict[str, Any]]:
        """SSO kirishida: Keycloak sessiyasi umumiy `sso` yozuviga, `platforms`
        (kirishda tekshirilib, tokenni QABUL QILGANLAR) - shu sessiyaning
        ulanishlariga aylanadi. Ro'yxatda yo'q platformaning yozuviga TEGILMAYDI
        (masalan HRM rad etsa qo'lda ulangan HRM joyida qoladi).

        Almashtirilgan qo'lda ulanishlar: CRM ning o'z refresh_token i CRM da
        bekor qilinadi (`revoke_old`); qo'lda ulangan HRM tokeni shunchaki
        almashtiriladi (HRM da bekor qilish yo'li yo'q).
        Eski SSO sessiyasi esa BEKOR QILINMAYDI: brauzerda Keycloak sessiyasi
        tirik bo'lsa qayta kirish O'SHA sessiyada bo'ladi va `offline_access`
        tokenlari uning ichida BITTA offline sessiyani bo'lishadi - eskisini
        bekor qilish hozirgina olingan yangi tokenni ham o'ldirardi.
        Ishlatilmagan offline sessiyani Keycloak o'zi tozalaydi (Offline Session
        Idle); oxirgi SSO ulanishini uzish (`disconnect`) esa bekor qiladi.
        """
        old = self.store.get(user_id)
        now = time.time()
        session = {"login": username, "refresh_token": refresh, "expired": False, "connected_at": now}
        # `enabled` - eski format maydoni (modul izohi): har doim `True`.
        entries = {p: {"login": username, "via": "sso", "enabled": True, "connected_at": now}
                   for p in platforms if p in PLATFORMS}
        with self._lock:
            self._sso_cache[user_id] = (access, time.monotonic() + ttl)
            if "crm" in entries:
                self._crm_cache.pop(user_id, None)
        self.store.update(user_id, {SESSION: session, **entries})
        stale_crm = old.get("crm")
        if revoke_old and "crm" in entries and stale_crm and not _via_sso(stale_crm) \
                and stale_crm.get("refresh_token"):
            self._revoke_crm(stale_crm, stale_crm["refresh_token"])
        log.info("Ulanish: %s -> %s (sso)", user_id, ", ".join(entries) or "-")
        return {p: self._entry_status(p, entry, user_id=user_id, session=session)
                for p, entry in entries.items()}

    def _crm_source(self, entry: dict[str, Any] | None) -> Any | None:
        """Shu yozuvning tokenini KIM yangilaydi va bekor qiladi: SSO sessiyasi
        (`via: "sso"` yoki `sso` yozuvi) - Keycloak (`self.session`), eski qo'lda
        ulangan CRM - CRM (`self.crm`). Sozlanmagan bo'lsa `None`."""
        source = self.session if _via_sso(entry) else self.crm
        return source if source is not None and source.configured else None

    def _session_source(self) -> Any | None:
        source = self.session
        return source if source is not None and source.configured else None

    def _revoke_crm(self, entry: dict[str, Any] | None, refresh_token: str) -> None:
        """`refresh_token` ni egasida bekor qiladi. Eng yaxshi harakat - ikkala
        manba ham xatoni o'zi jurnalga yozadi."""
        source = self._crm_source(entry)
        if source is None:
            return
        if source is self.crm:
            self.crm.logout(refresh_token)
        else:
            source.revoke(refresh_token)

    def disconnect(self, user_id: str, platform: str,
                   *, among: tuple[str, ...] = PLATFORMS) -> dict[str, Any]:
        """Uzish. Sukut bo'yicha har qanday platforma (admin panel CRM ni ham
        uzadi); odamning o'zi faqat `USER_PLATFORMS` ni uzadi - endpoint shuni
        `among` ga beradi."""
        self._check(platform, among)
        data = self.store.get(user_id)
        entry = data.get(platform)
        changes: dict[str, dict[str, Any] | None] = {platform: None}
        # Oxirgi SSO ulanishi uzilsa sessiya ham ketadi; boshqa tizim hali
        # ishlatayotgan bo'lsa (masalan CRM uzildi, HRM qoldi) sessiya qoladi.
        session = data.get(SESSION)
        others = [p for p in PLATFORMS if p != platform and _via_sso(data.get(p))]
        drop_session = _via_sso(entry) and session is not None and not others
        if drop_session:
            changes[SESSION] = None
        # AVVAL ombordan o'chiriladi: bundan keyin hech bir yangilash uni qayta
        # yoza olmaydi (`replace_if`), va bekor qilish (tarmoq) yiqilsa ham uzish
        # bajarilgan bo'ladi.
        self.store.update(user_id, changes)
        if platform == "crm":
            with self._lock:
                self._crm_cache.pop(user_id, None)
        # Saqlangan refresh_token egasida ham bekor qilinadi (qo'lda ulangan CRM -
        # CRM da, SSO sessiyasi - Keycloak'da): o'g'irlangan deb gumon qilsa, uzish
        # uni darhol yaroqsiz qilsin. Eng yaxshi harakat.
        stale = session if drop_session else (entry if platform == "crm" and not _via_sso(entry) else None)
        if drop_session:
            with self._lock:
                self._sso_cache.pop(user_id, None)
        if stale and stale.get("refresh_token"):
            try:
                if drop_session:
                    source = self._session_source()
                    if source is not None:
                        source.revoke(stale["refresh_token"])
                else:
                    self._revoke_crm(stale, stale["refresh_token"])
            except Exception:  # noqa: BLE001 - uzish baribir bajarildi
                log.exception("Token bekor qilinmadi (%s, %s) - ulanish uzilgan", user_id, platform)
        log.info("Uzish: %s -> %s", user_id, platform)
        return self._entry_status(platform, None, user_id=user_id)

    def connected(self, user_id: str, platform: str) -> dict[str, Any]:
        """Odam boshqaradigan platformaning holati; ulanmagan bo'lsa 409.

        ESKI KLIENTLAR UCHUN (`PATCH /connectors/hrm`: mobil ilova, eski Mini
        App). Kalit yo'q - ulangan tizim har doim ishlatiladi: so'rov hech
        narsani o'zgartirmaydi, javob esa haqiqiy holat (`enabled: true`).
        """
        self._check(platform, USER_PLATFORMS)
        data = self.store.get(user_id)
        entry = data.get(platform)
        if not entry:
            raise ConnectorError(f"{LABELS[platform]} ulanmagan", status=409, code="NOT_CONNECTED")
        return self._entry_status(platform, entry, user_id=user_id, session=data.get(SESSION))

    def tokens(self, user_id: str) -> dict[str, str]:
        """Chat uchun: FAQAT ulangan va yaroqli tokenlar.

        KALIT YO'Q (2026-11-12): ulangan tizim har doim ishlatiladi. Yozuvdagi
        eski `enabled: false` e'tiborga OLINMAYDI - aks holda kalitsiz ilovada
        odam uni hech qachon qayta yoqa olmasdi.

        Yo'q platforma xaritada BO'LMAYDI - chaqiruvchi o'z zahirasini
        (umumiy `.env` tokeni, agent sessiyasi) ishlatishi mumkin.
        """
        out: dict[str, str] = {}
        data = self.store.get(user_id)
        # Umumiy SSO sessiyasining tokeni - kerak bo'lsa BIR marta (CRM va HRM bitta token).
        shared: list[str] = []

        def sso_access() -> str:
            if not shared:
                shared.append(self._sso_access(user_id, data.get(SESSION)))
            return shared[0]

        hrm = data.get("hrm")
        if _via_sso(hrm):
            access = sso_access()
            if access:
                out["hrm"] = access
        elif hrm:
            # ESKI qo'lda ulangan yozuv: token javob oxirigacha yaroqli bo'lsagina.
            # Yangilanmaydi - tugagach odam BRB-Tech ID bilan qayta kiradi.
            token = str(hrm.get("token") or "")
            if token and self._hrm_left(hrm) > self.hrm_margin:
                out["hrm"] = token

        crm = data.get("crm")
        if _via_sso(crm):
            access = sso_access()
            if access:
                out["crm"] = access
        elif crm and crm.get("refresh_token"):
            access = self._crm_access(user_id, crm)
            if access:
                out["crm"] = access
        return out

    # --- ichki ------------------------------------------------------------

    @staticmethod
    def _check(platform: str, among: tuple[str, ...] = PLATFORMS) -> None:
        """`among` da yo'q platforma - 404. Odamning amallarida `among` =
        `USER_PLATFORMS`: CRM notanish nom bilan BIR XIL javob oladi."""
        if platform not in among:
            raise ConnectorError("Bunday platforma yo'q", status=404, code="UNKNOWN_PLATFORM")

    def configured(self, platform: str) -> bool:
        """Shu platformaga ulanish OCHILA oladimi: HRM - login manzili bor,
        CRM - SSO manbasi sozlangan (CRM faqat SSO kirishida ulanadi)."""
        if platform == "hrm":
            return self.hrm.configured
        return self.sso is not None and bool(self.sso.configured)

    @staticmethod
    def _hrm_left(entry: dict[str, Any]) -> float:
        try:
            return float(entry.get("expires_at") or 0) - time.time()
        except (TypeError, ValueError):
            return 0.0

    def _entry_status(self, platform: str, entry: dict[str, Any] | None,
                      *, user_id: str = "", session: dict[str, Any] | None = None) -> dict[str, Any]:
        """API javobi. TOKEN YO'Q - faqat holat. `via`: `sso` - ulanish SSO
        kirishidan (odam uni qo'lda yangilamaydi), `null` - qo'lda ulangan."""
        status: dict[str, Any] = {
            "id": platform,
            "label": LABELS[platform],
            "configured": self.configured(platform),
            "state": "disconnected",
            "login": None,
            "enabled": False,
            "expiresAt": None,
            "via": None,
        }
        if not entry:
            return status
        status["login"] = entry.get("login") or None
        # Kalit yo'q: ulangan = ishlatiladi. Maydon eski klientlar uchun qoldi
        # (mobil ilova undan "Chatda ishlatish" ni chizadi); yozuvdagi eski
        # `enabled: false` ko'rsatilmaydi - u hech narsani o'chirmaydi.
        status["enabled"] = True
        if _via_sso(entry):
            # Muddat yo'q: token har savol oldidan sessiyadan yangilanadi. Sessiya
            # o'lgan (bekor qilingan yoki muddati o'tgan) - odam qayta kiradi.
            alive = bool(session) and bool(session.get("refresh_token")) and not session.get("expired")
            status["state"] = "connected" if alive else "expired"
            status["via"] = "sso"
            return status
        if platform == "hrm":
            # ESKI qo'lda ulangan yozuv: o'zi yangilanmaydi.
            left = self._hrm_left(entry)
            status["expiresAt"] = _iso(time.time() + left) if entry.get("expires_at") else None
            status["state"] = "connected" if left > self.hrm_margin else "expired"
        else:
            dead = bool(entry.get("expired")) or not entry.get("refresh_token")
            status["state"] = "expired" if dead else "connected"
        return status

    def _user_lock(self, user_id: str) -> threading.Lock:
        with self._lock:
            lock = self._user_locks.get(user_id)
            if lock is None:
                lock = self._user_locks[user_id] = threading.Lock()
            return lock

    def _crm_access(self, user_id: str, entry: dict[str, Any]) -> str:
        """Yaroqli access_token ESKI (qo'lda ulangan) CRM yozuvidan."""
        return self._refresh_access(user_id, "crm", entry, self._crm_source(entry), self._crm_cache)

    def _sso_access(self, user_id: str, session: dict[str, Any] | None) -> str:
        """Yaroqli access_token umumiy SSO sessiyasidan (CRM va HRM uchun bitta)."""
        if not session or not session.get("refresh_token"):
            return ""
        return self._refresh_access(user_id, SESSION, session, self._session_source(), self._sso_cache)

    def _refresh_access(self, user_id: str, key: str, entry: dict[str, Any], source: Any | None,
                        cache: dict[str, tuple[str, float]]) -> str:
        """Yaroqli access_token: keshdan, bo'lmasa refresh. `key` - ombordagi
        yozuv (`crm` - qo'lda ulangan CRM, `sso` - umumiy sessiya), `source` - uni
        kim yangilaydi (CRM yoki Keycloak, `refresh` shakli bir xil)."""
        with self._user_lock(user_id):
            cached = cache.get(user_id)
            now = time.monotonic()
            if cached and now < cached[1] - self.crm_margin:
                return cached[0]
            if source is None:
                return cached[0] if cached and now < cached[1] else ""
            try:
                access, refresh, ttl = source.refresh(entry["refresh_token"])
            except ConnectorError as exc:
                if exc.status in (400, 401, 403):
                    # Token o'lgan: bekor qilingan yoki 30 kun ishlatilmagan.
                    # Holat "expired" - odam qayta kiradi. Login SAQLANADI,
                    # oyna uni to'ldirib beradi.
                    log.info("%s refresh rad etildi (%s): %s - qayta kirish kerak", key, user_id, exc)
                    # Faqat O'SHA sessiya "o'lgan" deb belgilanadi: shu orada odam
                    # qayta kirgan bo'lsa yangi ulanishga tegilmaydi.
                    if self.store.replace_if(user_id, key, entry["refresh_token"],
                                             refresh_token="", expired=True):
                        cache.pop(user_id, None)
                    return ""
                # Vaqtinchalik (tarmoq, 429, 5xx): eski token hali yaroqli
                # bo'lsa - o'sha, bo'lmasa bu savol shu tizimsiz ketadi.
                log.warning("%s refresh (%s): %s", key, user_id, exc)
                return cached[0] if cached and now < cached[1] else ""
            # Yangilash davomida (tarmoq - soniyalar) ulanish O'ZGARGAN bo'lishi
            # mumkin: odam qayta kirdi yoki ulanish uzildi - ular bu qulfni
            # olmaydi. Natija ESKI nusxa ustiga yozilsa uzilgan ulanish tirilardi,
            # yangi sessiya esa o'lgan tokenga almashardi. Shuning uchun natija
            # faqat omborda hali O'SHA `refresh_token` turgan bo'lsa yoziladi -
            # tekshiruv va yozish bitta qulf ostida (`replace_if`). ROTATSIYA: yangi
            # refresh_token kelsa o'sha saqlanadi - eskisi egasida bekor bo'lgan
            # bo'lishi mumkin; boshqa maydonlar tegilmaydi.
            sent = entry["refresh_token"]
            if not self.store.replace_if(user_id, key, sent,
                                         refresh_token=refresh or sent, expired=False):
                fresh = cache.get(user_id)
                still = self.store.get(user_id).get(key)
                return fresh[0] if still and fresh and time.monotonic() < fresh[1] else ""
            cache[user_id] = (access, time.monotonic() + ttl)
            return access

"""Foydalanuvchining O'Z HRM / CRM hisobi: ulanish, saqlash, yangilash.

`crm_auth.py` dagi agent sessiyasidan FARQI: u yerda BITTA umumiy hisob
(agentniki), bu yerda esa HAR BIR foydalanuvchining O'Z ulanishi turadi va
yuqoridagi xizmatga uning O'Z tokeni beriladi. Shunda "men bugun
kechikdimmi?" degan savol haqiqatan o'sha odam haqida bo'ladi - umumiy token
bilan esa javob token EGASI haqida bo'lardi (`core/config.py`, `hrm_token`).

KIM NIMANI BOSHQARADI (2026-11-12, ega qarori):

  * HRM SSO kirishida O'ZI ulanadi, agar HRM sessiya tokenini qabul qilsa
    (`crm_sso.HrmSso`, `api/v1/auth._connect_sso`). Qabul qilmasa yoki odam
    SSO siz kirgan bo'lsa - odam uni O'ZI ulaydi ("+" menyusi, login + parol,
    vaqtinchalik zahira): ulash, holat, muddati tugasa qayta ulash, uzish
    (`USER_PLATFORMS`, `/api/v1/connectors`).
  * CRM odamga KO'RINMAYDI va uni odam boshqarmaydi: ulanish SSO kirishida
    o'zi ochiladi (`api/v1/auth.py`, `crm_sso.py`). Uni ombor va admin panel
    biladi (`PLATFORMS`); odamning endpointlarida `crm` - 404.
  * KALIT YO'Q: ulangan tizim har doim ishlatiladi. Yozuvdagi `enabled`
    maydoni eski formatdan qolgan va hech narsani hal qilmaydi (`tokens`).

IKKI PLATFORMA, IKKI XIL SHAKL:

  HRM   POST /api/authenticate {username, password} -> JWT, 10 SOAT.
        Refresh yo'q: muddati tugasa odam qayta kiradi. "Meni eslab qol"
        maydoni ham yo'q - 2026-09-29 da jonli HRM'da uchala yozilishi
        sinaldi (`rememberMe`, `remember-me`, `remember_me`), HRM ularni
        e'tiborsiz qoldirib, baribir 10.0 soatlik token berdi. Token yuqoridagi
        xizmatga muddati `hrm_margin` dan KO'P qolgandagina beriladi -
        savol-javob bir necha daqiqa cho'zilishi mumkin va token javob
        OXIRIGACHA yaroqli turishi kerak. Kam qolsa holat "expired".

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
foydalanuvchi nomidan cheksiz token yasay oladi. HRM tokeni ham 10 soatlik
to'liq sessiya. Shuning uchun:

  * `data/connectors/` da, 600 huquq bilan, atomik yoziladi (`data/`
    gitignore'da);
  * PAROL DISKKA HECH QACHON YOZILMAYDI. Lekin u XOTIRADA saqlanadi
    (`ConnectorHub._passwords`), chunki HRM tokenini 10 soatdan keyin
    yangilashning BOSHQA YO'LI YO'Q: HRM da na refresh, na uzoq
    yashaydigan token bor (2026-09-29 da jonli HRM da o'lchangan).
    Shartlari:
      - parol faqat kirishda yoki "+" menyusidan ulanishda olinadi va
        FAQAT HRM ga qayta kirish uchun ishlatiladi;
      - jarayon qayta ishga tushsa yo'qoladi - diskda, jurnalda va
        zaxira nusxada izi qolmaydi;
      - chiqishda va HRM uzilganda darhol o'chiriladi;
      - HRM "login yoki parol noto'g'ri" desa ham o'chiriladi (parol
        o'zgargan) va odam qaytadan kiradi;
  * tokenlar jurnalga, xato matniga va API javobiga TUSHMAYDI - klient
    faqat holatni ko'radi: ulanmagan / ulangan / muddati tugagan.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
import re
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from ..analytics.meter import begin
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

#: HRM tokeni `exp` siz kelsa (kutilmaydi) - hujjatdagi 10 soat.
_HRM_DEFAULT_TTL = 10 * 3600.0
#: CRM `expires_in` yo'q yoki aqldan tashqari bo'lsa - hujjatdagi 300 s.
_CRM_DEFAULT_TTL = 300.0

#: Foydalanuvchiga ko'rinadigan xabar. ATAYLAB UMUMIY: qaysi biri xato
#: ekanini aytsak, qaysi loginlar borligini aniqlash mumkin bo'lardi.
MSG_BAD_CREDENTIALS = "Login yoki parol noto'g'ri"

#: JWT: uch bo'lak, `eyJ` bilan boshlanadi. "Bearer " prefiksi tashlanadi.
_JWT_RE = re.compile(r"^(?:Bearer\s+)?(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*)$")
#: HRM javobida token turishi mumkin bo'lgan nomlar - tartib ustunlik.
_TOKEN_KEYS = ("id_token", "idToken", "token", "access_token", "accessToken",
               "jwt", "authToken", "auth_token")


class ConnectorError(Exception):
    """`status` HTTP kodi bo'lib qaytadi, matn foydalanuvchiga ko'rinadi.

    Matnda token, ichki manzil yoki sir BO'LMASLIGI kerak - hamma xabar
    shu faylda yasaladi va `_safe` dan o'tadi.
    """

    def __init__(self, message: str, *, status: int = 400, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class _HttpFailure(Exception):
    """Ichki: HTTP xato + tahlil qilingan tanasi. Har platforma o'zi o'giradi."""

    def __init__(self, status: int, payload: Any) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.payload = payload if isinstance(payload, dict) else {}


def _normalize(base_url: str) -> str:
    """Sxema qo'shiladi, yozilmagan bo'lsa - `crm_auth.py` dagi kabi."""
    base = (base_url or "").strip().rstrip("/")
    if base and "://" not in base:
        base = f"https://{base}"
    return base


def jwt_exp(token: str) -> float | None:
    """JWT `exp` (epoch soniya). IMZO TEKSHIRILMAYDI - faqat muddat o'qiladi,
    tokenga ishonch esa uni bergan tizimniki."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    return float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None


def _ttl(value: Any, default: float) -> float:
    """`expires_in` ga ishonamiz, lekin ko'r-ko'rona emas."""
    try:
        ttl = float(value or 0)
    except (TypeError, ValueError):
        ttl = 0.0
    return ttl if 30.0 <= ttl <= 24 * 3600.0 else default


class _Reply(NamedTuple):
    payload: Any
    headers: dict[str, str]


def _send(request: urllib.request.Request, timeout: float, *, what: str,
          service: str = "", op: str = "request") -> _Reply:
    """So'rovni yuboradi. 2xx -> tahlil qilingan tana + sarlavhalar; HTTP
    xato -> `_HttpFailure`; tarmoq -> `ConnectorError` (502).

    Hisob (`api_calls`): `service`/`op` - masalan `hrm`/`authenticate`.
    Parol so'rov tanasida - u hisobga HECH QACHON tushmaydi: xato matni
    faqat javobdagi kod va tavsifdan yasaladi.
    """
    call = begin(service or what.lower(), op)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            headers = {str(k): str(v) for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            payload = None
        call.end("error", http_status=exc.code, error=_failure_text(exc.code, payload))
        raise _HttpFailure(exc.code, payload) from None
    except (urllib.error.URLError, OSError) as exc:
        log.warning("%s ga ulanib bo'lmadi: %s", what, _safe(str(exc)))
        call.end("error", error=_safe(f"ulanib bo'lmadi: {exc}"))
        raise ConnectorError(f"{what} tizimiga ulanib bo'lmadi", status=502, code="UNREACHABLE") from exc
    except BaseException as exc:
        call.end("error", error=exc)
        raise
    call.end("ok", http_status=200)
    if not raw:
        return _Reply({}, headers)
    text = raw.decode("utf-8", "replace")
    try:
        return _Reply(json.loads(text), headers)
    except ValueError:
        # JSON emas - yalang'och token bo'lishi mumkin (`_pick_token` tekshiradi).
        return _Reply(text.strip(), headers)


def _failure_text(status: int, payload: Any) -> str:
    """Hisob uchun qisqa sabab: HTTP kodi + javobdagi kod/tavsif
    (`invalid_grant: Account is not fully set up`). JWT lar `_safe` bilan
    olib tashlanadi; qolgan sirlarni `analytics.redact` tozalaydi."""
    parts = [f"HTTP {status}"]
    if isinstance(payload, dict):
        for key in ("error", "error_description", "detail", "title", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip()[:120])
    return _safe(": ".join(parts))


def _as_jwt(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    match = _JWT_RE.match(value.strip())
    return match.group(1) if match else ""


def _pick_token(payload: Any, depth: int = 0) -> str:
    """HRM javobidan tokenni topadi.

    Shakl hujjatlashtirilmagan, shuning uchun QIDIRUV: avval tanish nomlar
    (`id_token`, `accessToken`, ...), keyin ichma-ich obyektlar (`data`,
    `result`, ...), oxirida JWT ga o'xshagan HAR QANDAY satr. Tanish nomda
    JWT bo'lmagan qiymat ham olinadi (opaque token) - muddati u holda
    hujjatdagi 10 soat deb hisoblanadi.
    """
    if depth > 4:
        return ""
    if isinstance(payload, str):
        return _as_jwt(payload)
    if isinstance(payload, list):
        for item in payload:
            found = _pick_token(item, depth + 1)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in _TOKEN_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _as_jwt(value) or value.strip()
    for value in payload.values():
        if isinstance(value, (dict, list)):
            found = _pick_token(value, depth + 1)
            if found:
                return found
    for value in payload.values():
        found = _as_jwt(value)
        if found:
            return found
    return ""


def _shape(payload: Any, depth: int = 0) -> str:
    """Javobning SHAKLI - faqat kalit nomlari, qiymatsiz. Token topilmaganda
    jurnalga yoziladi: keyingi tuzatish taxmin emas, dalil bilan bo'lsin."""
    if isinstance(payload, dict):
        if depth > 3:
            return "{...}"
        parts = []
        for key, value in payload.items():
            parts.append(f"{key}: {_shape(value, depth + 1)}" if isinstance(value, (dict, list)) else str(key))
        return "{" + ", ".join(parts) + "}"
    if isinstance(payload, list):
        return f"[{len(payload)}]"
    return type(payload).__name__


# --- HRM ------------------------------------------------------------------


class HrmAuth:
    """HRM: `POST /api/authenticate` -> JWT (10 soat). Refresh yo'q."""

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self.base_url = _normalize(base_url)
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def login(self, username: str, password: str) -> tuple[str, float]:
        """-> (token, muddati epoch soniyada)."""
        request = urllib.request.Request(
            f"{self.base_url}/api/authenticate",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            reply = _send(request, self.timeout, what="HRM", service="hrm", op="authenticate")
        except _HttpFailure as exc:
            raise self._error(exc) from None
        # Token tanada, bo'lmasa `Authorization` sarlavhasida (ba'zi API'lar
        # shunday beradi).
        token = _pick_token(reply.payload)
        if not token:
            for name, value in reply.headers.items():
                if name.lower() == "authorization":
                    token = _as_jwt(value)
                    break
        if not token:
            log.warning("HRM javobida token topilmadi: tana %s, sarlavhalar %s",
                        _shape(reply.payload), sorted(reply.headers))
            raise ConnectorError("HRM javobida token yo'q", status=502, code="BAD_RESPONSE")
        exp = jwt_exp(token)
        # BERILGAN MUDDAT jurnalga yoziladi (token EMAS, faqat soat).
        # `rememberMe` tajribasi aynan shu qator bilan o'lchanadi: HRM uni
        # tushunsa muddat 10 soatdan sezilarli uzun bo'ladi.
        # BERILGAN MUDDAT jurnalga yoziladi (token EMAS, faqat soat).
        # HRM muddatni o'zgartirsa buni shu qator bilan darhol bilamiz -
        # aks holda "nega yana uzildi" degan savolga faqat taxmin bilan
        # javob berilardi.
        log.info("HRM tokeni: %.1f soat",
                 ((exp or 0) - time.time()) / 3600 if exp else _HRM_DEFAULT_TTL / 3600)
        # `exp` o'tib ketgan bo'lsa ham O'SHA olinadi: holat darhol "expired"
        # bo'ladi va bu halol - 10 soat deb yolg'on va'da berishdan yaxshi.
        return token, exp if exp is not None else time.time() + _HRM_DEFAULT_TTL

    @staticmethod
    def _error(exc: _HttpFailure) -> ConnectorError:
        detail = _safe(" ".join(str(exc.payload.get(k) or "")
                                for k in ("detail", "title", "message")))
        # HRM NOTO'G'RI LOGIN/PAROLGA 401 EMAS, 500 QAYTARADI - tanasida
        # `"detail": "401 Unauthorized: [no body]"` (o'lchangan, 2026-09-15:
        # mavjud bo'lmagan hisob ham, bo'sh parol ham shu javobni oladi).
        # Uni "HRM javob bermadi" deb ko'rsatish odamni noto'g'ri yo'lga
        # yuborardi - u parolini emas, tarmoqni tekshirardi.
        wrapped_401 = exc.status == 500 and ("401" in detail or "unauthorized" in detail.lower())
        if exc.status in (400, 401, 403) or wrapped_401:
            return ConnectorError(MSG_BAD_CREDENTIALS, status=400, code="BAD_CREDENTIALS")
        if exc.status == 429:
            return ConnectorError("HRM band, biroz kutib qayta urinib ko'ring",
                                  status=503, code="RATE_LIMIT")
        log.warning("HRM %s: %s", exc.status, detail[:200] or "(tanasiz)")
        return ConnectorError(f"HRM javob bermadi ({exc.status})", status=502,
                              code=f"HTTP_{exc.status}")


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
        #: user_id -> parol. FAQAT XOTIRADA (modul izohidagi shartlarga
        #: qara) va faqat HRM ga qayta kirish uchun.
        self._passwords: dict[str, str] = {}

    # --- parol (xotirada) -------------------------------------------------

    def remember_password(self, user_id: str, password: str) -> None:
        """HRM tokenini o'zi yangilash uchun parolni xotirada tutadi.

        Chaqiriladi: Venera'ga kirishda (SSO parolni tasdiqlagan) va "+"
        menyusidan HRM ga qo'lda ulanganda.
        """
        if not password:
            return
        with self._lock:
            self._passwords[str(user_id)] = password

    def forget_password(self, user_id: str) -> None:
        """Chiqish, HRM uzilishi yoki noto'g'ri parol - darhol o'chadi."""
        with self._lock:
            self._passwords.pop(str(user_id), None)

    def _password(self, user_id: str) -> str:
        with self._lock:
            return self._passwords.get(str(user_id), "")

    def has_password(self, user_id: str) -> bool:
        """Holat uchun: HRM ulanishi o'zini yangilay oladimi."""
        return bool(self._password(user_id))

    # --- tashqi yuz -------------------------------------------------------

    def status(self, user_id: str, platforms: tuple[str, ...] = PLATFORMS) -> list[dict[str, Any]]:
        """Holat. Sukut bo'yicha HAMMA platforma (admin panel); odamning o'ziga
        faqat `USER_PLATFORMS` ko'rsatiladi (`api/v1/connectors.py`)."""
        data = self.store.get(user_id)
        return [self._entry_status(p, data.get(p), user_id=user_id, session=data.get(SESSION))
                for p in platforms]

    def connect(self, user_id: str, platform: str, username: str, password: str) -> dict[str, Any]:
        """Login + parol -> ulanish. Parol shu yerdan nariga o'tmaydi.

        Faqat odam o'zi boshqaradigan platforma (`USER_PLATFORMS` - HRM). CRM ga
        parol bilan kirilmaydi: u SSO kirishida ulanadi (`adopt_crm`).
        """
        self._check(platform, USER_PLATFORMS)
        if not self.hrm.configured:
            raise ConnectorError("HRM ulanishi serverda sozlanmagan", status=503,
                                 code="NOT_CONFIGURED")
        username = username.strip()
        token, expires_at = self.hrm.login(username, password)
        return self.adopt_hrm(user_id, username, token, expires_at)

    def adopt_hrm(self, user_id: str, username: str, token: str,
                  expires_at: float) -> dict[str, Any]:
        """Tayyor HRM sessiyasini saqlaydi (`connect`)."""
        # `enabled` - eski format maydoni (modul izohi): har doim `True` yoziladi.
        entry = {"login": username, "token": token, "expires_at": expires_at,
                 "enabled": True, "connected_at": time.time()}
        self.store.set(user_id, "hrm", entry)
        log.info("Ulanish: %s -> hrm", user_id)
        return self._entry_status("hrm", entry, user_id=user_id)

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
        bekor qilinadi (`revoke_old`), HRM paroli xotiradan o'chadi - endi SSO.
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
        if "hrm" in entries:
            self.forget_password(user_id)
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
        if platform == "hrm":
            # Parol faqat HRM ni yangilash uchun turardi - endi keraksiz.
            self.forget_password(user_id)
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
            token = str(hrm.get("token") or "")
            if token and self._hrm_left(hrm) > self.hrm_margin:
                out["hrm"] = token
            else:
                # Muddati yaqin yoki tugagan. Parol xotirada bo'lsa QAYTA
                # KIRAMIZ - aks holda odam har 10 soatda "+" menyusidan
                # qo'lda ulanishi kerak edi.
                renewed = self._renew_hrm(user_id, hrm)
                if renewed:
                    out["hrm"] = renewed
                elif token:
                    log.info("HRM tokeni muddati yaqin (%s), parol xotirada yo'q - "
                             "yuborilmaydi, qayta kirish kerak", user_id)

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

    def _renew_hrm(self, user_id: str, entry: dict[str, Any]) -> str:
        """HRM ga xotiradagi parol bilan QAYTA KIRADI. -> token yoki "".

        HRM da refresh yo'q, ya'ni "yangilash" = qayta kirish. Qulf shuning
        uchun: bir vaqtda kelgan ikki savol ikkita login qilib, biri
        ikkinchisining tokenini behuda almashtirib yubormasin.
        """
        password = self._password(user_id)
        login_name = str(entry.get("login") or "")
        if not password or not login_name or not self.hrm.configured:
            return ""
        with self._user_lock(user_id):
            # Qulfni kutayotganda boshqa ip allaqachon yangilagan bo'lishi
            # mumkin - o'shanda ikkinchi login QILINMAYDI.
            current = self.store.get(user_id).get("hrm") or entry
            token = str(current.get("token") or "")
            if token and self._hrm_left(current) > self.hrm_margin:
                return token
            try:
                token, expires_at = self.hrm.login(login_name, password)
            except ConnectorError as exc:
                if exc.code == "BAD_CREDENTIALS":
                    # Parol o'zgargan. Saqlanganini TASHLAYMIZ: aks holda
                    # har savolda noto'g'ri parol bilan urinib, hisobni
                    # bloklatib qo'yish mumkin edi.
                    self.forget_password(user_id)
                    log.info("HRM o'zini yangilay olmadi (%s): parol o'zgargan", user_id)
                else:
                    log.warning("HRM o'zini yangilay olmadi (%s): %s", user_id, exc)
                return ""
            entry = {**current, "token": token, "expires_at": expires_at}
            self.store.set(user_id, "hrm", entry)
            log.info("HRM tokeni o'zi yangilandi (%s): %.1f soat",
                     user_id, (expires_at - time.time()) / 3600)
            return token

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
            left = self._hrm_left(entry)
            status["expiresAt"] = _iso(time.time() + left) if entry.get("expires_at") else None
            # Parol xotirada bo'lsa ULANGAN deb ko'rsatiladi: token
            # muddati o'tgan bo'lsa ham, keyingi savol oldidan o'zi
            # yangilanadi (`_renew_hrm`). Aks holda odam menyuda
            # "muddati tugagan" ni ko'rib, keraksiz joydan qayta ulardi -
            # ya'ni avtomatik yangilashning butun foydasi yo'qolardi.
            renews = bool(user_id) and self.has_password(user_id)
            status["state"] = "connected" if left > self.hrm_margin or renews else "expired"
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

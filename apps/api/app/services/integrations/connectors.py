"""Foydalanuvchining O'Z HRM / CRM hisobi: ulanish, saqlash, yangilash.

`crm_auth.py` dagi agent sessiyasidan FARQI: u yerda BITTA umumiy hisob
(agentniki), bu yerda esa HAR BIR foydalanuvchi "+" menyusidan o'z logini va
paroli bilan kiradi, va yuqoridagi xizmatga uning O'Z tokeni beriladi. Shunda
"men bugun kechikdimmi?" degan savol haqiqatan o'sha odam haqida bo'ladi -
umumiy token bilan esa javob token EGASI haqida bo'lardi (`core/config.py`,
`hrm_token`).

IKKI PLATFORMA, IKKI XIL SHAKL:

  HRM   POST /api/authenticate {username, password} -> JWT, 10 SOAT.
        Refresh yo'q: muddati tugasa odam qayta kiradi. Token yuqoridagi
        xizmatga muddati `hrm_margin` dan KO'P qolgandagina beriladi -
        savol-javob bir necha daqiqa cho'zilishi mumkin va token javob
        OXIRIGACHA yaroqli turishi kerak. Kam qolsa holat "expired".

  CRM   Keycloak parol granti (`offline_access`) -> refresh_token (doimiy),
        keyin CRM `POST /api/auth/refresh` -> access_token, 300 SEKUND.
        Har savol oldidan tekshiriladi: muddati `crm_margin` dan kam
        qolgan bo'lsa yangilanadi. ROTATSIYA: javobda yangi refresh_token
        kelsa o'sha saqlanadi. Refresh 400/401 bersa token o'lgan - holat
        "expired", odam qayta kiradi.

SAQLASH. `refresh_token` PAROLDAN FARQI YO'Q - uni qo'lga kiritgan odam o'sha
foydalanuvchi nomidan cheksiz token yasay oladi. HRM tokeni ham 10 soatlik
to'liq sessiya. Shuning uchun:

  * `data/connectors/` da, 600 huquq bilan, atomik yoziladi (`data/`
    gitignore'da);
  * PAROL HECH QACHON SAQLANMAYDI - u faqat login so'roviga ketadi va
    javob kelishi bilan unutiladi;
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
import urllib.parse
import urllib.request

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from .crm_auth import CrmAuthError, _safe, post_json

log = logging.getLogger(__name__)

PLATFORMS: tuple[str, ...] = ("hrm", "crm")
LABELS = {"hrm": "HRM", "crm": "CRM"}

#: HRM tokeni `exp` siz kelsa (kutilmaydi) - hujjatdagi 10 soat.
_HRM_DEFAULT_TTL = 10 * 3600.0
#: CRM `expires_in` yo'q yoki aqldan tashqari bo'lsa - hujjatdagi 300 s.
_CRM_DEFAULT_TTL = 300.0
_CRM_SCOPE = "openid profile email offline_access"

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


def _send(request: urllib.request.Request, timeout: float, *, what: str) -> _Reply:
    """So'rovni yuboradi. 2xx -> tahlil qilingan tana + sarlavhalar; HTTP
    xato -> `_HttpFailure`; tarmoq -> `ConnectorError` (502)."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            headers = {str(k): str(v) for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            payload = None
        raise _HttpFailure(exc.code, payload) from None
    except (urllib.error.URLError, OSError) as exc:
        log.warning("%s ga ulanib bo'lmadi: %s", what, _safe(str(exc)))
        raise ConnectorError(f"{what} tizimiga ulanib bo'lmadi", status=502, code="UNREACHABLE") from exc
    if not raw:
        return _Reply({}, headers)
    text = raw.decode("utf-8", "replace")
    try:
        return _Reply(json.loads(text), headers)
    except ValueError:
        # JSON emas - yalang'och token bo'lishi mumkin (`_pick_token` tekshiradi).
        return _Reply(text.strip(), headers)


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
            reply = _send(request, self.timeout, what="HRM")
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
    """CRM: Keycloak parol granti -> refresh_token; CRM refresh -> access_token."""

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

    def login(self, username: str, password: str) -> tuple[str, str, float]:
        """-> (access_token, refresh_token, access muddati soniyada)."""
        form = urllib.parse.urlencode({
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            "username": username,
            "password": password,
            "scope": _CRM_SCOPE,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.token_url,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            method="POST",
        )
        try:
            payload = _send(request, self.timeout, what="CRM").payload
        except _HttpFailure as exc:
            raise self._error(exc) from None
        if not isinstance(payload, dict):
            raise ConnectorError("CRM javobi obyekt emas", status=502, code="BAD_RESPONSE")
        access = str(payload.get("access_token") or "")
        refresh = str(payload.get("refresh_token") or "")
        if not access or not refresh:
            raise ConnectorError("CRM javobida token yo'q", status=502, code="BAD_RESPONSE")
        return access, refresh, _ttl(payload.get("expires_in"), _CRM_DEFAULT_TTL)

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

    @staticmethod
    def _error(exc: _HttpFailure) -> ConnectorError:
        code = str(exc.payload.get("error") or "")
        desc = _safe(str(exc.payload.get("error_description") or ""))
        if exc.status in (400, 401) and code == "invalid_grant":
            # "Invalid user credentials" - parol. Boshqa sabab (masalan
            # "Account is not fully set up") odamga AYTILADI: bu uning
            # parolida emas, hisobida, va CRM administratori tuzatadi.
            if not desc or "credential" in desc.lower():
                return ConnectorError(MSG_BAD_CREDENTIALS, status=400, code=code)
            return ConnectorError(f"CRM hisobga kirishni rad etdi: {desc}", status=400, code=code)
        if code in ("invalid_client", "unauthorized_client"):
            # Bizning `client_secret` noto'g'ri - odam hech narsa qila olmaydi.
            log.error("CRM client rad etildi (%s) - CRM_CLIENT_ID/SECRET ni tekshiring", code)
            return ConnectorError("CRM ulanishi serverda noto'g'ri sozlangan", status=503, code=code)
        if exc.status == 429:
            return ConnectorError("CRM band, biroz kutib qayta urinib ko'ring",
                                  status=503, code="RATE_LIMIT")
        return ConnectorError(f"CRM kirish xizmati javob bermadi ({exc.status})",
                              status=502, code=code or f"HTTP_{exc.status}")


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
    """Holat, ulanish, uzish, kalit - va chat uchun yaroqli tokenlar."""

    def __init__(self, store: ConnectorStore, hrm: HrmAuth, crm: CrmUserAuth, *,
                 hrm_margin: float = 300.0, crm_margin: float = 180.0) -> None:
        self.store = store
        self.hrm = hrm
        self.crm = crm
        self.hrm_margin = hrm_margin
        self.crm_margin = crm_margin
        self._lock = threading.Lock()
        #: user_id -> (access_token, muddati `time.monotonic()` bo'yicha).
        #: Faqat xotirada: 300 sekundlik tokenni diskka yozish ma'nosiz.
        self._crm_cache: dict[str, tuple[str, float]] = {}
        #: Har odam uchun alohida qulf: bir vaqtda kelgan ikki savol BITTA
        #: yangilashni bo'lishadi, aks holda rotatsiya bir-birini bekor qilardi.
        self._user_locks: dict[str, threading.Lock] = {}

    # --- tashqi yuz -------------------------------------------------------

    def status(self, user_id: str) -> list[dict[str, Any]]:
        data = self.store.get(user_id)
        return [self._entry_status(p, data.get(p)) for p in PLATFORMS]

    def connect(self, user_id: str, platform: str, username: str, password: str) -> dict[str, Any]:
        """Login + parol -> ulanish. Parol shu yerdan nariga o'tmaydi."""
        self._check(platform)
        username = username.strip()
        if platform == "hrm":
            token, expires_at = self.hrm.login(username, password)
            entry = {"login": username, "token": token, "expires_at": expires_at,
                     "enabled": True, "connected_at": time.time()}
        else:
            access, refresh, ttl = self.crm.login(username, password)
            entry = {"login": username, "refresh_token": refresh, "expired": False,
                     "enabled": True, "connected_at": time.time()}
            with self._lock:
                self._crm_cache[user_id] = (access, time.monotonic() + ttl)
        self.store.set(user_id, platform, entry)
        log.info("Ulanish: %s -> %s", user_id, platform)
        return self._entry_status(platform, entry)

    def disconnect(self, user_id: str, platform: str) -> dict[str, Any]:
        self._check(platform, need_configured=False)
        entry = self.store.get(user_id).get(platform)
        if platform == "crm":
            with self._lock:
                self._crm_cache.pop(user_id, None)
            # Saqlangan refresh_token CRM da ham bekor qilinadi: o'g'irlangan
            # deb gumon qilsa, uzish uni darhol yaroqsiz qilsin.
            if entry and entry.get("refresh_token") and self.crm.configured:
                self.crm.logout(entry["refresh_token"])
        self.store.set(user_id, platform, None)
        log.info("Uzish: %s -> %s", user_id, platform)
        return self._entry_status(platform, None)

    def set_enabled(self, user_id: str, platform: str, enabled: bool) -> dict[str, Any]:
        self._check(platform, need_configured=False)
        entry = self.store.get(user_id).get(platform)
        if not entry:
            raise ConnectorError(f"{LABELS[platform]} ulanmagan", status=409, code="NOT_CONNECTED")
        entry["enabled"] = bool(enabled)
        self.store.set(user_id, platform, entry)
        return self._entry_status(platform, entry)

    def tokens(self, user_id: str) -> dict[str, str]:
        """Chat uchun: FAQAT ulangan, yoqilgan va yaroqli tokenlar.

        Yo'q platforma xaritada BO'LMAYDI - chaqiruvchi o'z zahirasini
        (umumiy `.env` tokeni, agent sessiyasi) ishlatishi mumkin.
        """
        out: dict[str, str] = {}
        data = self.store.get(user_id)

        hrm = data.get("hrm")
        if hrm and hrm.get("enabled", True):
            token = str(hrm.get("token") or "")
            if token and self._hrm_left(hrm) > self.hrm_margin:
                out["hrm"] = token
            elif token:
                log.info("HRM tokeni muddati yaqin (%s) - yuborilmaydi, qayta kirish kerak", user_id)

        crm = data.get("crm")
        if crm and crm.get("enabled", True) and crm.get("refresh_token"):
            access = self._crm_access(user_id, crm)
            if access:
                out["crm"] = access
        return out

    # --- ichki ------------------------------------------------------------

    def _check(self, platform: str, *, need_configured: bool = True) -> None:
        if platform not in PLATFORMS:
            raise ConnectorError("Bunday platforma yo'q", status=404, code="UNKNOWN_PLATFORM")
        auth = self.hrm if platform == "hrm" else self.crm
        if need_configured and not auth.configured:
            raise ConnectorError(f"{LABELS[platform]} ulanishi serverda sozlanmagan",
                                 status=503, code="NOT_CONFIGURED")

    @staticmethod
    def _hrm_left(entry: dict[str, Any]) -> float:
        try:
            return float(entry.get("expires_at") or 0) - time.time()
        except (TypeError, ValueError):
            return 0.0

    def _entry_status(self, platform: str, entry: dict[str, Any] | None) -> dict[str, Any]:
        """API javobi. TOKEN YO'Q - faqat holat."""
        auth = self.hrm if platform == "hrm" else self.crm
        status: dict[str, Any] = {
            "id": platform,
            "label": LABELS[platform],
            "configured": auth.configured,
            "state": "disconnected",
            "login": None,
            "enabled": False,
            "expiresAt": None,
        }
        if not entry:
            return status
        status["login"] = entry.get("login") or None
        status["enabled"] = bool(entry.get("enabled", True))
        if platform == "hrm":
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
        """Yaroqli CRM access_token: keshdan, bo'lmasa refresh."""
        with self._user_lock(user_id):
            cached = self._crm_cache.get(user_id)
            now = time.monotonic()
            if cached and now < cached[1] - self.crm_margin:
                return cached[0]
            if not self.crm.configured:
                return cached[0] if cached and now < cached[1] else ""
            try:
                access, refresh, ttl = self.crm.refresh(entry["refresh_token"])
            except ConnectorError as exc:
                if exc.status in (400, 401, 403):
                    # Token o'lgan: bekor qilingan yoki 30 kun ishlatilmagan.
                    # Holat "expired" - odam qayta kiradi. Login SAQLANADI,
                    # oyna uni to'ldirib beradi.
                    log.info("CRM refresh rad etildi (%s): %s - qayta kirish kerak", user_id, exc)
                    entry = {**entry, "refresh_token": "", "expired": True}
                    self.store.set(user_id, "crm", entry)
                    self._crm_cache.pop(user_id, None)
                    return ""
                # Vaqtinchalik (tarmoq, 429, 5xx): eski token hali yaroqli
                # bo'lsa - o'sha, bo'lmasa bu savol CRM siz ketadi.
                log.warning("CRM refresh (%s): %s", user_id, exc)
                return cached[0] if cached and now < cached[1] else ""
            self._crm_cache[user_id] = (access, time.monotonic() + ttl)
            # ROTATSIYA: yangi refresh_token kelsa o'sha saqlanadi - eskisi
            # CRM tomonida bekor bo'lgan bo'lishi mumkin.
            if refresh and refresh != entry.get("refresh_token"):
                self.store.set(user_id, "crm", {**entry, "refresh_token": refresh, "expired": False})
            return access

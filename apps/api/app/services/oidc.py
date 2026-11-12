"""Keycloak orqali kirish: OpenID Connect, brauzer oqimi (Authorization Code + PKCE).

OLDINGI YO'L (`services/sso.py`, o'chirildi) login va parolni Keycloak'ga
ilovaning O'ZI yuborardi (parol granti) va o'sha parol bilan HRM ga ham
kirardi. SSO ning maqsadi aynan shu: ilova parolni KO'RMASIN. Endi:

  1. `GET /auth/sso/start` - brauzer Keycloak'ning kirish sahifasiga ketadi.
     `state` (qaytganda tanib olish), `nonce` (ID token aynan shu kirish
     uchun berilganini isbotlash) va PKCE `code_verifier` (kodni o'g'irlagan
     odam uni tokenga almashtira olmasin) shu modulda, 10 daqiqa turadi.
  2. Odam Keycloak'da kiradi - parol faqat brauzer va Keycloak orasida.
  3. Keycloak brauzerni `GET /auth/sso/callback?code&state` ga qaytaradi.
  4. Server `code` ni client siri + `code_verifier` bilan tokenlarga
     almashtiradi va ID tokenning IMZOSINI Keycloak'ning ochiq kaliti (JWKS)
     bilan tekshiradi: `iss` bizning realm, `aud` bizning client, `exp`,
     `nonce`. Eski modul imzoni ataylab tekshirmasdi (token to'g'ridan-to'g'ri
     TLS orqali kelardi); bu yerda u brauzer orqali keladi - tekshirilADI.
  5. Shaxs - ID tokendan (`sub`, `preferred_username`, `email`, `name`).
     Rollar - access tokendagi `resource_access["<bizning client>"].roles`:
     FAQAT bizning client'ning rollari. Realm rollari e'tiborga olinmaydi -
     ularni boshqa tizimlar uchun kim ham berishi mumkin (`services/admin_users`
     modulining eski izohi). Keycloak'dagi `admin` -> Barno `ADMIN`.

Manzillar discovery'siz: Keycloak'da ular realm manzilidan qat'iy kelib
chiqadi (`<issuer>/protocol/openid-connect/...`); discovery esa har ishga
tushishda tarmoqqa bog'liqlik qo'shardi.

HOLAT XOTIRADA (`PENDING`, `HANDOFF`, `ID_TOKENS`): API bitta jarayonda
ishlaydi (`uvicorn` ishchisiz). Qayta ishga tushirish kirish o'rtasida
kelsa odam "Kirish" ni yana bosadi, xolos. Diskka yozilmaydi - bu
qiymatlar bir martalik va sirli (`code_verifier`).
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import os
import secrets
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import jwt

from .identities import SsoProfile

log = logging.getLogger(__name__)

#: Kirish boshlanganidan qaytishgacha ruxsat etilgan vaqt. Keycloak sahifasida
#: parolni eslash, ikki bosqichli tasdiq - 10 daqiqa yetarli.
PENDING_TTL = 600.0
#: Callback -> frontend qo'lga olishi uchun bir martalik kod muddati.
HANDOFF_TTL = 90.0
#: Xotira chegarasi: bot-trafik `start` ni urib turganda ham o'smasin.
_MAX_ENTRIES = 5000
#: Soat farqi uchun yon berish (sekund) - Keycloak va bizning server.
_LEEWAY = 30
_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256", "ES384", "ES512"]
_SCOPE = "openid profile email"
#: CRM ulanishi SSO sessiyasidan ochilganda (`sso_crm_connect`) `offline_access`
#: ham so'raladi: usiz `refresh_token` Keycloak'ning SSO sessiyasi bilan birga
#: o'ladi (odatda 30 daqiqa harakatsizlik) va CRM ulanishi kuniga bir necha
#: marta "muddati tugagan" bo'lib qolardi. Oldingi yo'l (`crm-client`, parol
#: granti) ham aynan shu scope'ni so'rardi (`connectors._CRM_SCOPE`).
_SCOPE_OFFLINE = f"{_SCOPE} offline_access"
#: JWKS noma'lum `kid` uchun qayta so'raladi, lekin bundan tez-tez emas.
_JWKS_MIN_REFRESH = 60.0

#: Keycloak client roli -> Barno roli. Ro'yxatda yo'q rol ham o'tadi (katta
#: harfda, `-` -> `_`): masalan `rag-admin` -> `RAG_ADMIN`. Ro'yxat faqat
#: hujjat va aniqlik uchun.
ROLE_MAP = {
    "admin": "ADMIN",
    "employee": "EMPLOYEE",
    "executive": "EXECUTIVE",
    "rag-admin": "RAG_ADMIN",
    "rag_admin": "RAG_ADMIN",
}


class OidcError(Exception):
    """Kirish bajarilmadi. `message` odamga ko'rsatiladi (token/sir yo'q),
    `code` jurnal va `auth_events` uchun qisqa sabab."""

    def __init__(self, message: str, *, status: int = 502, code: str = "failed") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Tokens:
    """Token endpoint javobi."""

    id_token: str
    access_token: str
    refresh_token: str = ""
    expires_in: float = 300.0


@dataclass
class Pending:
    """Boshlangan, hali qaytmagan kirish."""

    state: str
    verifier: str
    nonce: str
    return_to: str
    channel: str
    created: float = field(default_factory=time.time)
    #: Kirishni BOSHLAGAN brauzerga bog'lash: `start` qo'ygan cookie'ning
    #: SHA-256 i (`api/v1/auth.py`). Bo'sh - bog'lanmagan (testlar, eski yo'l).
    binding: str = ""


class _Expiring:
    """`{kalit: (vaqt, qiymat)}` - TTL bilan, bir martalik `pop`."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, Any]] = {}

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._prune()
            self._items[key] = (time.time(), value)

    def pop(self, key: str) -> Any | None:
        with self._lock:
            self._prune()
            found = self._items.pop(key, None)
            return found[1] if found else None

    def __len__(self) -> int:
        with self._lock:
            self._prune()
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def _prune(self) -> None:
        now = time.time()
        if len(self._items) > _MAX_ENTRIES:
            # Eng eskilaridan qisqartiriladi - yangi kirishlar ishlayversin.
            for key, _ in sorted(self._items.items(), key=lambda kv: kv[1][0])[: len(self._items) // 2]:
                self._items.pop(key, None)
        for key in [k for k, (ts, _) in self._items.items() if now - ts > self.ttl]:
            self._items.pop(key, None)


#: Boshlangan kirishlar: `state` -> `Pending`.
PENDING = _Expiring(PENDING_TTL)
#: Callback'dan frontend'ga bir martalik kod: kod -> tayyor `LoginResponse` (dict).
#: Token URL'da YURMAYDI (jurnal, tarix, Referer) - faqat shu kod yuradi.
HANDOFF = _Expiring(HANDOFF_TTL)
class IdTokens:
    """Chiqish uchun oxirgi ID token (`id_token_hint`): actor_id -> token - DISKDA.

    2026-11-12 gacha faqat xotirada edi va API har qayta ishga tushganda yo'qolardi:
    shundan keyin chiqishda Keycloak (`brb-realm`, `post_logout_redirect_uri` bilan
    `id_token_hint` siz) "We are sorry... Missing parameters: id_token_hint" sahifasini
    ko'rsatardi (jonli sayt, ega xabari). Endi `data/sso/id_tokens.json` da (600, atomik).
    ID token API'ga kirish kaliti EMAS - Keycloak uni faqat "kim chiqyapti" belgisi
    sifatida o'qiydi (imzosi tekshiriladi, muddati emas). `TTL` dan eskisi tashlanadi.
    """

    TTL = 30 * 86400.0

    def __init__(self, path: Callable[[], Path]) -> None:
        self._path = path
        self._lock = threading.Lock()

    def __setitem__(self, actor_id: int, token: str) -> None:
        with self._lock:
            data = self._read()
            data[str(int(actor_id))] = {"token": token, "at": time.time()}
            self._write(data)

    def get(self, actor_id: int, default: str | None = None) -> str | None:
        with self._lock:
            entry = self._read().get(str(int(actor_id)))
        return entry["token"] if entry else default

    def pop(self, actor_id: int, default: str | None = None) -> str | None:
        with self._lock:
            data = self._read()
            entry = data.pop(str(int(actor_id)), None)
            if entry is not None:
                self._write(data)
        return entry["token"] if entry else default

    def clear(self) -> None:
        with self._lock:
            self._write({})

    def __len__(self) -> int:
        with self._lock:
            return len(self._read())

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(Path(self._path()).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        now = time.time()
        return {k: v for k, v in (raw.items() if isinstance(raw, dict) else [])
                if isinstance(v, dict) and isinstance(v.get("token"), str)
                and now - float(v.get("at") or 0) <= self.TTL}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        path = Path(self._path())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                                 prefix=".id-tokens.", suffix=".tmp", delete=False)
            try:
                with handle:
                    json.dump(data, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
                os.replace(handle.name, path)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            # Chiqish manzili baribir quriladi (hint'siz - `logout_url`), kirish to'xtamaydi.
            log.warning("ID tokenlar fayli yozilmadi (%s): %s", path, exc)


def _id_tokens_path() -> Path:
    from ..core.config import settings

    return Path(settings.sso_id_tokens_file)


ID_TOKENS = IdTokens(_id_tokens_path)


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge S256). RFC 7636: verifier 43-128 belgi."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --- tarmoq -----------------------------------------------------------------


def _request(request: urllib.request.Request, timeout: float, *, what: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001 - javob tanasi bo'lmasligi mumkin
            pass
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            payload = {}
        code = str(payload.get("error") or "") if isinstance(payload, dict) else ""
        desc = str(payload.get("error_description") or "") if isinstance(payload, dict) else ""
        log.warning("Keycloak %s: HTTP %s %s %s", what, exc.code, code, desc[:120])
        raise _http_failure(exc.code, code, desc) from None
    except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as exc:
        # `HTTPException` (buzilgan holat qatori, uzilgan javob) `OSError` emas va
        # urllib uni o'ramaydi - ushlanmasa "eng yaxshi harakat" chaqiruvlaridan
        # (masalan `revoke`) tashqariga chiqib, uzishni yarim yo'lda to'xtatardi.
        log.warning("Keycloak %s: aloqa yo'q: %s", what, exc)
        raise OidcError("SSO (Keycloak) bilan aloqa yo'q", status=502, code="network") from None
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise OidcError("Keycloak javobi o'qilmadi", status=502, code="bad_response") from None
    if not isinstance(payload, dict):
        raise OidcError("Keycloak javobi obyekt emas", status=502, code="bad_response")
    return payload


def _http_failure(status: int, code: str, desc: str) -> OidcError:
    if code == "invalid_grant":
        # Kod ikki marta ishlatildi, muddati o'tdi yoki `redirect_uri` boshqa.
        return OidcError("Kirish kodi eskirgan yoki ishlatilgan - qaytadan kiring",
                         status=400, code="invalid_grant")
    if code in ("invalid_client", "unauthorized_client"):
        log.error("Keycloak client rad etildi (%s) - SSO_CLIENT_ID/SECRET ni tekshiring", code)
        return OidcError("SSO serverda noto'g'ri sozlangan (client)", status=503, code=code)
    if status == 429:
        return OidcError("SSO band, biroz kutib qayta urinib ko'ring", status=503, code="rate_limit")
    return OidcError(f"SSO javob bermadi ({status})", status=502, code=code or f"http_{status}")


def _post_form(url: str, form: dict[str, str], timeout: float, *, what: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    return _request(request, timeout, what=what)


def _get_json(url: str, timeout: float, *, what: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    return _request(request, timeout, what=what)


# --- JWKS -------------------------------------------------------------------


class Jwks:
    """Realm'ning ochiq kalitlari, `kid` bo'yicha. Noma'lum `kid` kelsa (kalit
    almashtirilgan) bir marta qayta so'raladi, lekin daqiqada bir martadan ko'p emas."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched: dict[str, float] = {}
        #: Oxirgi qayta so'rovga sabab bo'lgan noma'lum `kid` - AYNI `kid`
        #: qayta-qayta kelsa (soxta token) JWKS daqiqada bir martadan ko'p
        #: so'ralmaydi; BOSHQA yangi `kid` (haqiqiy almashtirish) darhol.
        self._unknown: dict[str, tuple[str, float]] = {}

    def key(self, url: str, kid: str, timeout: float) -> Any:
        with self._lock:
            keys = self._keys.get(url)
            if keys is None:
                keys = self._fetch(url, timeout)
            elif kid not in keys:
                last_kid, last_at = self._unknown.get(url, ("", 0.0))
                if kid != last_kid or time.time() - last_at > _JWKS_MIN_REFRESH:
                    keys = self._fetch(url, timeout)
                    # Cheklov faqat MUVAFFAQIYATLI so'rovdan keyin yoziladi: so'rov
                    # yiqilsa (timeout, 5xx) keyingi kirish darhol qayta so'raydi -
                    # aks holda kalit almashgandan keyin bir daqiqa hamma kira olmasdi.
                    self._unknown[url] = (kid, time.time())
            found = keys.get(kid)
        if found is None:
            raise OidcError("Keycloak tokeni noma'lum kalit bilan imzolangan", status=502, code="unknown_kid")
        return found

    def _fetch(self, url: str, timeout: float) -> dict[str, Any]:
        payload = _get_json(url, timeout, what="jwks")
        keys: dict[str, Any] = {}
        for raw in payload.get("keys") or []:
            if not isinstance(raw, dict) or not raw.get("kid"):
                continue
            if raw.get("use") not in (None, "sig"):
                continue
            try:
                keys[str(raw["kid"])] = jwt.PyJWK(raw).key
            except jwt.PyJWKError as exc:
                log.warning("JWKS kaliti o'qilmadi (%s): %s", raw.get("kid"), exc)
        self._keys[url] = keys
        self._fetched[url] = time.time()
        return keys

    def forget(self) -> None:
        with self._lock:
            self._keys.clear()
            self._fetched.clear()
            self._unknown.clear()


JWKS = Jwks()


# --- client -----------------------------------------------------------------


class KeycloakOidc:
    """Bitta realm + bizning client. Sozlama `core/config.py` (`sso_*`)."""

    def __init__(self, issuer: str, client_id: str, client_secret: str, *,
                 timeout: float = 10.0, offline: bool = False) -> None:
        self.issuer = (issuer or "").strip().rstrip("/")
        self.client_id = (client_id or "").strip()
        self._client_secret = client_secret or ""
        self.timeout = timeout
        #: `offline_access` so'raladimi (`_SCOPE_OFFLINE` izohi).
        self.scope = _SCOPE_OFFLINE if offline else _SCOPE

    @property
    def configured(self) -> bool:
        return bool(self.issuer and self.client_id and self._client_secret)

    # Keycloak manzillari realm'dan kelib chiqadi.
    @property
    def authorize_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/token"

    @property
    def jwks_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/certs"

    @property
    def end_session_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/logout"

    @property
    def revocation_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/revoke"

    # --- 1. boshlash --------------------------------------------------------

    def begin(self, redirect_uri: str, *, return_to: str, channel: str, binding: str = "") -> str:
        """Kirishni boshlaydi: `Pending` ni saqlaydi, Keycloak manzilini qaytaradi."""
        verifier, challenge = pkce_pair()
        pending = Pending(
            state=secrets.token_urlsafe(32),
            verifier=verifier,
            nonce=secrets.token_urlsafe(24),
            return_to=return_to,
            channel=channel,
            binding=binding,
        )
        PENDING.put(pending.state, pending)
        query = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.scope,
            "state": pending.state,
            "nonce": pending.nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"{self.authorize_endpoint}?{query}"

    # --- 2. qaytish ---------------------------------------------------------

    @staticmethod
    def take_pending(state: str) -> Pending:
        pending = PENDING.pop(state) if state else None
        if pending is None:
            raise OidcError("Kirish sessiyasi topilmadi yoki eskirgan - qaytadan kiring",
                            status=400, code="expired")
        return pending

    def exchange(self, code: str, pending: Pending, redirect_uri: str) -> Tokens:
        """`code` -> tokenlar (client siri + PKCE verifier bilan)."""
        payload = _post_form(self.token_endpoint, {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            "code_verifier": pending.verifier,
        }, self.timeout, what="token")
        return self._tokens(payload)

    def refresh(self, refresh_token: str) -> Tokens:
        """Keycloak sessiyasini yangilash - CRM ulanishi shu bilan yashaydi
        (`services/integrations/crm_sso.py`)."""
        payload = _post_form(self.token_endpoint, {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self._client_secret,
        }, self.timeout, what="refresh")
        return self._tokens(payload)

    def revoke(self, refresh_token: str) -> None:
        """Saqlangan tokenni Keycloak'da BEKOR qiladi - FAQAT bizning client'ning
        ruxsatini (RFC 7009, `/revoke`; `offline_access` tokeni ham shu yo'l bilan).

        ATAYLAB `/logout` EMAS: u sessiyani yopadi - `refresh_token` bilan
        chaqirilsa odamning BUTUN Keycloak sessiyasi tugaydi va u shu brauzerda
        ochiq turgan CRM va boshqa SSO tizimlaridan ham chiqib ketadi. "CRM ni
        uzish" tugmasi esa faqat Barno'ning saqlangan ruxsatini o'chirishi kerak.

        Eng yaxshi harakat: xato jurnalga yoziladi, chaqiruvchi ishini davom
        ettiradi - "uzish" Keycloak javob bermagani uchun to'xtab qolmasin."""
        if not refresh_token:
            return
        try:
            _post_form(self.revocation_endpoint, {
                "client_id": self.client_id,
                "client_secret": self._client_secret,
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            }, self.timeout, what="revoke")
        except OidcError as exc:
            log.warning("Keycloak tokeni bekor qilinmadi (%s): %s", exc.code, exc)

    def describe(self, access_token: str) -> dict[str, Any]:
        """Access token KIMGA mo'ljallangani - jurnal uchun, sirsiz: `azp`, `aud`
        va `resource_access` dagi client NOMLARI (rollar emas). CRM tokenni rad
        etsa sabab shu yerdan ko'rinadi (masalan `aud` da `crm-client` yo'q).
        O'qib bo'lmasa bo'sh lug'at - bu faqat diagnostika."""
        if not access_token or access_token.count(".") != 2:
            return {}
        try:
            claims = self._decode(access_token, audience=None)
        except OidcError:
            return {}
        aud = claims.get("aud")
        if isinstance(aud, (list, tuple)):
            audiences = [str(item) for item in aud]
        else:
            audiences = [str(aud)] if aud else []
        clients = claims.get("resource_access")
        return {
            "azp": str(claims.get("azp") or ""),
            "aud": audiences,
            "clients": sorted(str(name) for name in clients) if isinstance(clients, dict) else [],
        }

    @staticmethod
    def _tokens(payload: dict[str, Any]) -> Tokens:
        access = str(payload.get("access_token") or "")
        if not access:
            raise OidcError("Keycloak javobida access_token yo'q", status=502, code="bad_response")
        try:
            expires = float(payload.get("expires_in") or 300)
        except (TypeError, ValueError):
            expires = 300.0
        return Tokens(
            id_token=str(payload.get("id_token") or ""),
            access_token=access,
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_in=expires,
        )

    # --- 3. tekshirish ------------------------------------------------------

    def profile(self, tokens: Tokens, *, nonce: str) -> SsoProfile:
        """ID tokenni TEKSHIRIB shaxsni, access tokendan rollarni oladi."""
        if not tokens.id_token:
            raise OidcError("Keycloak javobida id_token yo'q (scope `openid` kerak)",
                            status=502, code="bad_response")
        claims = self._decode(tokens.id_token, audience=self.client_id)
        if str(claims.get("nonce") or "") != nonce:
            raise OidcError("Keycloak tokeni boshqa kirishga tegishli (nonce)", status=400, code="nonce")
        azp = claims.get("azp")
        if azp and str(azp) != self.client_id:
            raise OidcError("Keycloak tokeni boshqa client uchun berilgan", status=400, code="azp")
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise OidcError("Keycloak tokenida shaxs (sub) yo'q", status=502, code="bad_token")
        username = str(claims.get("preferred_username") or "").strip()
        return SsoProfile(
            subject=subject,
            username=username or subject,
            email=str(claims.get("email") or "").strip().lower(),
            full_name=_full_name(claims),
            roles=tuple(self.roles(tokens.access_token)),
        )

    def roles(self, access_token: str) -> list[str]:
        """Bizning client'ning rollari - access tokendan, imzosi tekshirilib.

        Access token JWT bo'lmasa (realm "opaque" token bersa) rollar bo'sh:
        kirish ishlaydi, imtiyoz yo'q - va bu jurnalda ko'rinadi.
        """
        if not access_token or access_token.count(".") != 2:
            log.warning("Keycloak access_token JWT emas - rollar o'qilmadi")
            return []
        # `aud` tekshirilmaydi: Keycloak access tokenida u `account` yoki
        # boshqa client bo'lishi mumkin; imzo, `iss` va `exp` tekshiriladi.
        claims = self._decode(access_token, audience=None)
        clients = claims.get("resource_access") or {}
        raw = (clients.get(self.client_id) or {}).get("roles") or [] if isinstance(clients, dict) else []
        roles: list[str] = []
        for item in raw:
            name = str(item).strip()
            if not name:
                continue
            mapped = ROLE_MAP.get(name.lower()) or name.upper().replace("-", "_")
            if mapped not in roles:
                roles.append(mapped)
        return roles

    def _decode(self, token: str, *, audience: str | None) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise OidcError(f"Keycloak tokeni o'qilmadi: {exc}", status=502, code="bad_token") from None
        kid = str(header.get("kid") or "")
        key = JWKS.key(self.jwks_endpoint, kid, self.timeout)
        options = {"require": ["exp", "iat", "iss", "sub"], "verify_aud": audience is not None}
        try:
            return jwt.decode(
                token, key, algorithms=_ALGORITHMS, audience=audience, issuer=self.issuer,
                leeway=_LEEWAY, options=options,
            )
        except jwt.ExpiredSignatureError:
            raise OidcError("Keycloak tokeni muddati o'tgan - qaytadan kiring", status=400, code="expired_token") from None
        except jwt.InvalidIssuerError:
            log.error("Keycloak `iss` mos emas: kutilgan %s", self.issuer)
            raise OidcError("Keycloak tokeni boshqa realm'dan", status=400, code="issuer") from None
        except jwt.InvalidAudienceError:
            raise OidcError("Keycloak tokeni boshqa client uchun berilgan", status=400, code="audience") from None
        except jwt.PyJWTError as exc:
            log.warning("Keycloak token imzosi/tuzilishi rad etildi: %s", exc)
            raise OidcError("Keycloak tokeni haqiqiy emas", status=400, code="bad_signature") from None

    # --- 4. chiqish ---------------------------------------------------------

    def logout_url(self, post_logout_redirect_uri: str, *, id_token_hint: str | None = None) -> str:
        """Keycloak chiqish manzili. `id_token_hint` bo'lsa - chiqqach Barno'ga qaytadi.
        Bo'lmasa - QAYTISH MANZILISIZ: `brb-realm` Keycloak'i `post_logout_redirect_uri`
        ni `id_token_hint` siz rad etadi ("Missing parameters: id_token_hint", `client_id`
        yetmaydi - 2026-11-12, jonli). Unda Keycloak "chiqasizmi?" deb so'raydi va o'z
        "chiqdingiz" sahifasini ko'rsatadi - xato sahifasi emas, sessiya baribir yopiladi."""
        if not id_token_hint:
            return self.end_session_endpoint
        params = {"client_id": self.client_id, "post_logout_redirect_uri": post_logout_redirect_uri,
                  "id_token_hint": id_token_hint}
        return f"{self.end_session_endpoint}?{urllib.parse.urlencode(params)}"


def from_settings() -> KeycloakOidc:
    """Bizning client - CHAQIRUV PAYTIDAGI sozlamadan (testlar `settings.sso_*`
    ni almashtiradi). Kirish (`api/v1/auth.py`) va CRM ulanishi
    (`integrations/crm_sso.py`) BITTA joydan yasaydi - scope ikkisida bir xil
    bo'lsin."""
    from ..core.config import settings

    return KeycloakOidc(settings.sso_issuer, settings.sso_client_id, settings.sso_client_secret,
                        timeout=settings.sso_timeout,
                        offline=bool(settings.sso_crm_connect or settings.sso_hrm_connect))


def _full_name(claims: dict[str, Any]) -> str:
    name = str(claims.get("name") or "").strip()
    if name:
        return name
    parts = [str(claims.get(k) or "").strip() for k in ("given_name", "family_name")]
    return " ".join(p for p in parts if p)

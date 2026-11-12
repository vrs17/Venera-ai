"""CRM va HRM ulanishi SSO sessiyasidan (2026-11-12, ega so'rovi).

BITTA SESSIYA, IKKI TIZIM. Kirishda Keycloak bergan sessiya (`barno-ai` client'iga
berilgan access + refresh token) odamning ombordagi `sso` yozuvida turadi
(`ConnectorHub.adopt_sso`). CRM ham, HRM ham o'sha realm'ning tokenini qabul
qiladi, ya'ni ikkalasiga BIR XIL access token beriladi va uni BITTA joyda
yangilanadi (`SsoSession`): ikki nusxa refresh tokenni alohida aylantirsa,
Keycloak'ning "Revoke Refresh Token" sozlamasida biri ikkinchisini o'ldirardi.
Har tizim kirishda o'zi tekshiriladi va faqat qabul qilgani ulanadi:
CRM - `CrmSso.accepts` (`GET /api/auth/me`), HRM - `HrmSso.check`
(`GET /api/account`).

HRM (2026-11-12): HRM jamoasi kod bo'yicha ko'rsatdi - HRM Keycloak `brb-realm`
tokenini Bearer sifatida tekshiradi (`iss`, `aud` = `account` yoki
`api://default`, imzo; shaxs - `preferred_username`), `/api/authenticate` ham
Keycloak tokenini (`smart-office-client`) qaytaradi. "HRM o'z JWT'sini beradi"
degan eski yozuv (2026-09-29) noto'g'ri edi. Rad etilsa jurnalda HRM aytgan sabab
(`WWW-Authenticate` dagi `error_description`, masalan "Invalid audience") va
tokenning `aud`/`azp` i yoziladi - token o'zi emas.

Oldingi kirish (`services/sso.py`, o'chirilgan) parolni ko'rardi va Keycloak
javobini (`crm-client`, parol granti) CRM ulanishiga aylantirardi - odam "+"
menyusiga kirmasdi. Brauzer orqali SSO da parol bizga kelmaydi, lekin Keycloak
SESSIYASI keladi: `barno-ai` client'iga berilgan access va refresh token. CRM
ham o'sha Keycloak'ning (o'sha realm'ning) tokenlarini qabul qiladi - demak
sessiyaning o'zi CRM ulanishi bo'la oladi.

Oldingi yo'ldan IKKI farq:

  * Access tokenni CRM EMAS, KEYCLOAK yangilaydi. `POST <CRM>/api/auth/refresh`
    faqat `crm-client` ga berilgan refresh tokenni yangilay oladi (Keycloak
    "token boshqa client'niki" deb rad etadi) - bizniki esa `barno-ai` ga
    berilgan. Shuning uchun `ConnectorHub` bu ulanishni `via="sso"` deb
    belgilaydi va yangilashni shu modulga beradi (`refresh`).
  * CRM bizning client'ga berilgan tokenni qabul qilishi KAFOLATLANMAGAN: u
    `aud` yoki `azp` ni tekshirsa rad etadi. Shuning uchun ulanish kirish
    paytida TEKSHIRILADI (`accepts`: `GET <CRM>/api/auth/me`). CRM "yo'q"
    desa ulanish OCHILMAYDI va odamning eski (qo'lda ulangan) CRM ulanishiga
    tegilmaydi - ishlamaydigan sessiyani "ulangan" deb saqlashdan ko'ra halol.
    Rad etilsa yechim Keycloak tomonda: `barno-ai` client'iga `crm-client`
    uchun "Audience" mapper (`docs/auth-sso.md`).

BU - CRM GA ULANISHNING YAGONA YO'LI (2026-11-12, ega qarori): odam CRM ni
ko'rmaydi, qo'lda ulamaydi va o'chirib qo'ymaydi; ulanish har doim ishlatiladi.
Uzish faqat admin panelda (`ConnectorHub.disconnect`).

Token shu yerda ham jurnalga, xato matniga va API javobiga TUSHMAYDI.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request

from typing import Callable

from ..analytics.meter import begin
from ..oidc import KeycloakOidc, OidcError
from .connectors import ConnectorError, _normalize
from .crm_auth import _safe

log = logging.getLogger(__name__)

#: "Men kimman" - CRM ning eng arzon himoyalangan manzili (`openapi-crm.json`).
#: 2026-11-12 da jonli CRM da tekshirilgan: tokensiz va yaroqsiz token bilan 401.
ME_PATH = "/api/auth/me"
#: HRM: joriy xodim (`AccountResource`). Tokensiz va yaroqsiz token bilan 401
#: (2026-11-12, jonli HRM). Login HRM xodimlari jadvalida bo'lmasa HRM xato
#: qaytaradi - u holda ulanish ochilmaydi (HRM bu odamni tanimaydi).
ACCOUNT_PATH = "/api/account"
_ERROR_DESCRIPTION = re.compile(r'error_description="([^"]*)"')


class SsoSession:
    """Odamning Keycloak sessiyasini yangilash va bekor qilish - CRM va HRM uchun
    BITTA (modul izohi). Sozlama CHAQIRUV PAYTIDA o'qiladi (`oidc` - funksiya):
    testlar `settings.*` ni almashtiradi, `.env` esa faqat ishga tushishda
    o'qilsa ham obyekt modul yuklanganda yasaladi."""

    def __init__(self, oidc: Callable[[], KeycloakOidc]) -> None:
        self._oidc = oidc

    @property
    def configured(self) -> bool:
        return self._oidc().configured

    def refresh(self, refresh_token: str) -> tuple[str, str, float]:
        """-> (access_token, yangi refresh_token yoki "", muddati) - shakli
        `CrmUserAuth.refresh` bilan bir xil, `ConnectorHub._refresh_access` ikkalasini
        bir xil ishlatadi. 400 = sessiya o'lgan (bekor qilingan, muddati o'tgan
        yoki odam Keycloak'da o'chirilgan) - holat "expired"; qolgani vaqtinchalik."""
        try:
            tokens = self._oidc().refresh(refresh_token)
        except OidcError as exc:
            if exc.code == "invalid_grant":
                raise ConnectorError("SSO sessiyasi tugagan - qaytadan kiring",
                                     status=400, code="invalid_grant") from None
            raise ConnectorError(str(exc), status=exc.status if exc.status >= 500 else 502,
                                 code=exc.code) from None
        return tokens.access_token, tokens.refresh_token, tokens.expires_in

    def revoke(self, refresh_token: str) -> None:
        """Saqlangan sessiyani Keycloak'da bekor qiladi - uzishda (admin panel).
        Eng yaxshi harakat."""
        self._oidc().revoke(refresh_token)


class CrmSso(SsoSession):
    """SSO sessiyasi <-> CRM: sessiya (`SsoSession`) + CRM tekshiruvi."""

    def __init__(self, oidc: Callable[[], KeycloakOidc], base_url: Callable[[], str],
                 *, timeout: float = 5.0) -> None:
        super().__init__(oidc)
        self._base_url = base_url
        #: Kirishni kechiktirmasin: CRM sekin bo'lsa tekshiruv "noma'lum" bo'ladi.
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(_normalize(self._base_url())) and self._oidc().configured

    def accepts(self, access_token: str) -> bool | None:
        """CRM shu tokenni qabul qiladimi: `True` - ha, `False` - rad etdi
        (401/403), `None` - aniqlab bo'lmadi (tarmoq, 5xx, kutilmagan javob)."""
        base = _normalize(self._base_url())
        if not base or not access_token:
            return None
        request = urllib.request.Request(
            f"{base}{ME_PATH}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        call = begin("crm", "me")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            call.end("error", http_status=exc.code, error=f"HTTP {exc.code}")
            if exc.code in (401, 403):
                return False
            log.warning("CRM tekshiruvi (%s): kutilmagan javob %s", ME_PATH, exc.code)
            return None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            call.end("error", error=exc)
            log.warning("CRM tekshiruvi (%s): aloqa yo'q: %s", ME_PATH, exc)
            return None
        call.end("ok", http_status=200)
        return True


class HrmSso:
    """SSO sessiyasi <-> HRM: kirishda HRM shu tokenni qabul qiladimi. Yangilash
    va bekor qilish - umumiy sessiyada (`SsoSession`)."""

    def __init__(self, base_url: Callable[[], str], *, timeout: float = 5.0) -> None:
        self._base_url = base_url
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(_normalize(self._base_url()))

    def check(self, access_token: str) -> tuple[bool | None, str]:
        """-> (hukm, sabab). Hukm: `True` - qabul qildi (200), `False` - rad
        etdi (401/403), `None` - aniqlab bo'lmadi (tarmoq, 5xx, xodim topilmadi).
        Sabab - jurnal uchun (HTTP kodi va HRM'ning `error_description` i), token yo'q."""
        base = _normalize(self._base_url())
        if not base or not access_token:
            return None, "sozlanmagan"
        request = urllib.request.Request(
            f"{base}{ACCOUNT_PATH}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        call = begin("hrm", "account")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            reason = f"HTTP {exc.code}"
            found = _ERROR_DESCRIPTION.search(exc.headers.get("WWW-Authenticate", "") if exc.headers else "")
            if found:
                reason = f"{reason}: {_safe(found.group(1))[:160]}"
            call.end("error", http_status=exc.code, error=reason)
            return (False if exc.code in (401, 403) else None), reason
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            call.end("error", error=exc)
            return None, _safe(f"aloqa yo'q: {exc}")[:160]
        call.end("ok", http_status=200)
        return True, "HTTP 200"

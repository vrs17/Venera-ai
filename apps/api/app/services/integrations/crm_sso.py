"""CRM ulanishi SSO sessiyasidan (2026-11-12, ega so'rovi).

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
    tegilmaydi - menyuda "ulangan" deb yolg'on ko'rsatishdan ko'ra halol.
    Rad etilsa yechim Keycloak tomonda: `barno-ai` client'iga `crm-client`
    uchun "Audience" mapper (`docs/auth-sso.md`).

Token shu yerda ham jurnalga, xato matniga va API javobiga TUSHMAYDI.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from typing import Callable

from ..analytics.meter import begin
from ..oidc import KeycloakOidc, OidcError
from .connectors import ConnectorError, _normalize

log = logging.getLogger(__name__)

#: "Men kimman" - CRM ning eng arzon himoyalangan manzili (`openapi-crm.json`).
#: 2026-11-12 da jonli CRM da tekshirilgan: tokensiz va yaroqsiz token bilan 401.
ME_PATH = "/api/auth/me"


class CrmSso:
    """SSO sessiyasi <-> CRM. Sozlama CHAQIRUV PAYTIDA o'qiladi (ikkala
    argument ham funksiya): testlar `settings.*` ni almashtiradi, `.env` esa
    faqat ishga tushishda o'qilsa ham obyekt modul yuklanganda yasaladi."""

    def __init__(self, oidc: Callable[[], KeycloakOidc], base_url: Callable[[], str],
                 *, timeout: float = 5.0) -> None:
        self._oidc = oidc
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

    def refresh(self, refresh_token: str) -> tuple[str, str, float]:
        """-> (access_token, yangi refresh_token yoki "", muddati) - shakli
        `CrmUserAuth.refresh` bilan bir xil, `ConnectorHub._crm_access` ikkalasini
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
        """Saqlangan sessiyani Keycloak'da bekor qiladi - "uzish" tugmasi va
        yangi kirish eskisini almashtirganda. Eng yaxshi harakat."""
        self._oidc().revoke(refresh_token)

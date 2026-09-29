"""Keycloak orqali kirish (SSO): login + parol -> shaxs + CRM sessiyasi.

NEGA PAROL GRANTI, REDIRECT EMAS. Talab: kirgandan keyin "+" menyusida HRM
ham, CRM ham odamning o'z hisobi bilan ULANGAN turishi kerak, odam faqat
kalitni buradi. HRM Keycloak tokenini QABUL QILMAYDI - u JHipster
shaklidagi o'z JWT'sini faqat login+parolga beradi (`connectors.py`).
Ya'ni HRM ni ochish uchun parolni BIR MARTA ko'rishimiz shart, redirect
oqimida esa parol brauzer bilan Keycloak orasida qoladi. HRM va Keycloak
paroli bir xil (tasdiqlangan, 2026-09-29), shuning uchun bitta login
ikkalasini ham ochadi.

Keycloak so'rovi `CrmUserAuth.login` ning O'ZI (`crm-client`,
`offline_access`): CRM ulanishi allaqachon shu yo'l bilan ochilardi, endi
o'sha javob KIRISHNING o'zi ham bo'ladi - `access_token` shaxsni beradi,
`refresh_token` esa CRM ulanishiga ketadi (`api/v1/auth.py`).

TOKEN IMZOSI TEKSHIRILMAYDI, va bu ataylab: token Keycloak'dan TLS orqali,
bizning client siri bilan, TO'G'RIDAN-TO'G'RI olindi - uni yo'lda kimdir
almashtira olmaydi. Tekshiriladigani: `iss` bizning realm'mi (boshqa
manzilga sozlab qo'yilsa bilinsin) va `exp` o'tmaganmi.
"""

from __future__ import annotations

import logging
import time

from dataclasses import dataclass

import jwt

from .identities import SsoProfile
from .integrations.connectors import MSG_BAD_CREDENTIALS, ConnectorError, CrmUserAuth

log = logging.getLogger(__name__)

#: Keycloak har odamga beradigan texnik rollar - foydalanuvchiga ko'rinmaydi.
_NOISE_ROLES = {"offline_access", "uma_authorization"}
_NOISE_PREFIX = "default-roles-"

#: Keycloak `invalid_grant: "Account is not fully set up"` - PAROL TO'G'RI,
#: lekin hisobda TUGALLANMAGAN AMAL bor (parolni yangilash, emailni
#: tasdiqlash, profilni to'ldirish, OTP). Brauzer orqali kirganda Keycloak
#: o'sha qadamni ko'rsatardi; parol granti (API) buni qila olmaydi va rad
#: etadi. Odam BIR MARTA brauzer orqali CRM saytiga kirsa amal bajariladi
#: va shu kirish ishlaydi (Keycloak'ning o'z hisob sahifasi bu realm'da
#: o'chiq - "Client not found", 2026-09-29). Yoki Keycloak administratori
#: amalni olib tashlaydi. Xom matn odamga hech narsa demaydi - shuning
#: uchun aytiladi. Agent hisobida ham aynan shu bo'lgan (`crm_auth.py`).
_NOT_SET_UP = "not fully set up"
MSG_ACCOUNT_SETUP = (
    "Parol to'g'ri, lekin Keycloak hisobingizda tugallanmagan amal bor "
    "(parolni yangilash, emailni tasdiqlash yoki profilni to'ldirish). "
    "Bir marta CRM saytiga brauzer orqali kiring, so'ralgan qadamni "
    "bajaring va shu yerda qaytadan urinib ko'ring."
)


class SsoError(Exception):
    """Kirish rad etildi yoki Keycloak javob bermadi. Matn foydalanuvchiga
    ko'rinadi, ichida token yo'q (`CrmUserAuth._error` shunday yasaydi)."""

    def __init__(self, message: str, *, status: int = 502, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def bad_credentials(self) -> bool:
        """Parol xato - zahira (`users.yaml`) sinab ko'riladi, keyin 401."""
        return str(self) == MSG_BAD_CREDENTIALS


@dataclass(frozen=True)
class SsoLogin:
    """Muvaffaqiyatli kirish: shaxs + CRM ulanishi uchun tokenlar."""

    profile: SsoProfile
    access_token: str
    refresh_token: str
    ttl: float


class KeycloakSso:
    """`CrmUserAuth` ustidagi yupqa qatlam: parol granti + claim'larni o'qish."""

    def __init__(self, idp: CrmUserAuth) -> None:
        self.idp = idp

    @property
    def configured(self) -> bool:
        # CRM ulanishi sozlangan bo'lsa SSO ham sozlangan - bitta manba
        # (`CRM_IDP_TOKEN_URL`, `CRM_CLIENT_ID/SECRET`, `CRM_BASE_URL`).
        return self.idp.configured

    @property
    def issuer(self) -> str:
        """`.../realms/<realm>` - token manzilidan olinadi."""
        url = self.idp.token_url
        marker = "/protocol/openid-connect/"
        return url.split(marker, 1)[0] if marker in url else ""

    def login(self, username: str, password: str) -> SsoLogin:
        try:
            access, refresh, ttl = self.idp.login(username, password)
        except ConnectorError as exc:
            message = str(exc)
            if exc.code == "invalid_grant" and _NOT_SET_UP in message.lower():
                message = MSG_ACCOUNT_SETUP
            raise SsoError(message, status=exc.status, code=exc.code) from None
        claims = self._claims(access)
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise SsoError("Keycloak javobida shaxs (sub) yo'q", status=502, code="BAD_TOKEN")
        profile = SsoProfile(
            subject=subject,
            username=str(claims.get("preferred_username") or username).strip(),
            email=str(claims.get("email") or "").strip().lower(),
            full_name=_full_name(claims),
            roles=tuple(self._roles(claims)),
        )
        return SsoLogin(profile=profile, access_token=access, refresh_token=refresh, ttl=ttl)

    # --- ichki ------------------------------------------------------------

    def _claims(self, token: str) -> dict:
        try:
            claims = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        except jwt.PyJWTError as exc:
            log.warning("Keycloak access_token o'qilmadi: %s", exc)
            raise SsoError("Keycloak tokeni o'qilmadi", status=502, code="BAD_TOKEN") from None
        exp = claims.get("exp")
        if isinstance(exp, (int, float)) and exp < time.time():
            raise SsoError("Keycloak muddati o'tgan token berdi", status=502, code="BAD_TOKEN")
        issuer = self.issuer
        if issuer and str(claims.get("iss") or "").rstrip("/") != issuer.rstrip("/"):
            log.error("Keycloak `iss` mos emas: kutilgan %s", issuer)
            raise SsoError("Keycloak tokeni boshqa realm'dan", status=502, code="BAD_ISSUER")
        return claims

    def _roles(self, claims: dict) -> list[str]:
        """Realm rollari + bizning client rollari, texnik rollarsiz."""
        roles: list[str] = []
        realm = claims.get("realm_access") or {}
        roles.extend(realm.get("roles") or [])
        clients = claims.get("resource_access") or {}
        roles.extend((clients.get(self.idp.client_id) or {}).get("roles") or [])
        seen: list[str] = []
        for role in roles:
            role = str(role).strip()
            if not role or role in _NOISE_ROLES or role.startswith(_NOISE_PREFIX) or role in seen:
                continue
            seen.append(role)
        return seen


def _full_name(claims: dict) -> str:
    name = str(claims.get("name") or "").strip()
    if name:
        return name
    parts = [str(claims.get(k) or "").strip() for k in ("given_name", "family_name")]
    return " ".join(p for p in parts if p)

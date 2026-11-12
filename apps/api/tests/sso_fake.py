"""Soxta Keycloak (OpenID Connect) - SSO testlari uchun umumiy qism.

Keycloak'ning o'zi chaqirilmaydi: almashtirish nuqtasi `urllib.request.urlopen`
(`test_connectors.FakeNet` kabi, uning ustiga quriladi - HRM/CRM soxtalari
ham ishlayveradi). Soxta Keycloak:

  * `authorize(url)` - brauzer Keycloak sahifasida "kirdi": `start` bergan
    manzildan `state`, `code_challenge`, `nonce`, `redirect_uri` o'qiladi,
    `code` yasaladi;
  * token endpoint - `authorization_code` grantini TEKSHIRADI (client siri,
    PKCE S256, `redirect_uri`) va HAQIQIY RS256 imzoli ID/access token
    qaytaradi (test RSA kaliti bilan);
  * certs endpoint - o'sha kalitning JWK'si.

`sso_login(client, net)` butun oqimni (start -> callback -> exchange) bosib
`LoginResponse` ni qaytaradi - boshqa test fayllari shuni chaqiradi.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request

import jwt
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.v1 import connectors as connectors_api
from app.core.config import settings
from app.services import oidc as oidc_module
from app.services.integrations.connectors import (
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
)
from tests.test_connectors import CRM, HRM, IDP, FakeNet, _Response, _http_error

ISSUER = "https://idp.test/auth/realms/brb-realm"
CLIENT_ID = "barno-ai"
SECRET = "client-siri"
APP_URL = "http://testserver"
CALLBACK = f"{APP_URL}/api/v1/auth/sso/callback"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
CERTS_URL = f"{ISSUER}/protocol/openid-connect/certs"
AUTH_URL = f"{ISSUER}/protocol/openid-connect/auth"
LOGOUT_URL = f"{ISSUER}/protocol/openid-connect/logout"
SUB = "6f1a2b3c-0000-4000-8000-000000000001"
USERNAME = "y.mamajonov"
#: Eski testlar `LOGIN["username"]` ni ishlatadi (`admin_logins` va h.k.).
LOGIN = {"username": USERNAME}
KID = "test-kalit-1"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
)
_JWK = jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True)
#: Ikkinchi kalit - "Keycloak kalitni almashtirdi" holati uchun.
_KEY2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM2 = _KEY2.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
)
_JWK2 = jwt.algorithms.RSAAlgorithm.to_jwk(_KEY2.public_key(), as_dict=True)
KID2 = "test-kalit-2"


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class FakeKeycloak(FakeNet):
    """`urllib.request.urlopen` o'rnida. Sozlanadigan maydonlar - test
    "Keycloak shunday javob bersa nima bo'ladi" deb o'zgartiradi."""

    def __init__(self) -> None:
        super().__init__()
        self.sub = SUB
        self.username = USERNAME
        self.email = "y.mamajonov@brb-tech.uz"
        self.name = "Test Xodim"
        self.iss = ISSUER
        #: `resource_access["barno-ai"].roles` - Barno ko'radigani.
        self.client_roles: list[str] = ["employee"]
        #: Realm rollari - Barno E'TIBOR BERMAYDI (`ADMIN` ataylab bor).
        self.realm_roles: list[str] = ["offline_access", "uma_authorization",
                                       "default-roles-brb-realm", "ADMIN"]
        #: Boshqa client'ning rollari - ham e'tiborsiz.
        self.other_client_roles: list[str] = ["admin"]
        self.kid = KID
        self.aud = CLIENT_ID
        self.azp: str | None = CLIENT_ID
        self.nonce_override: str | None = None
        self.id_token_missing = False
        self.access_opaque = False
        self.exp_offset = 300
        #: Token endpoint har doim shu xato.
        self.token_error: tuple[int, dict] | None = None
        self.certs_calls = 0
        #: JWKS da qaysi kalitlar e'lon qilinadi.
        self.published: list[str] = [KID]
        self._codes: dict[str, dict[str, str]] = {}
        self.last_authorize: dict[str, str] = {}
        self.token_calls: list[dict[str, str]] = []
        #: CRM `GET /api/auth/me` (SSO sessiyasidan CRM ulanishi, `crm_sso.py`):
        #: True - 200, False - 401, None - 503 (aniqlab bo'lmaydi).
        self.crm_accepts: bool | None = True
        #: `me` ga kelgan `Authorization` sarlavhalari.
        self.me_calls: list[str] = []
        #: Keycloak logout endpoint'ida bekor qilingan refresh tokenlar.
        self.revoked: list[str] = []
        #: `refresh_token` granti shu xato bilan yiqiladi (masalan sessiya o'lgan).
        self.refresh_error: tuple[int, dict] | None = None

    # --- "brauzer" Keycloak sahifasida -------------------------------------

    def authorize(self, location: str) -> tuple[str, str]:
        """`start` bergan Keycloak manzili -> (code, state). Keycloak kabi
        so'rovni tekshiradi."""
        parsed = urllib.parse.urlparse(location)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTH_URL, location
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        assert query["response_type"] == "code"
        assert query["client_id"] == CLIENT_ID
        assert "openid" in query["scope"].split()
        assert query["code_challenge_method"] == "S256"
        for key in ("state", "nonce", "code_challenge", "redirect_uri"):
            assert query.get(key), f"{key} yo'q: {location}"
        self.last_authorize = query
        code = secrets.token_urlsafe(16)
        self._codes[code] = query
        return code, query["state"]

    # --- tarmoq ------------------------------------------------------------

    def __call__(self, request, timeout=None):
        url = request.full_url
        if url == CERTS_URL:
            self.certs_calls += 1
            self.calls.append((url, {}))
            keys = []
            if KID in self.published:
                keys.append({**_JWK, "kid": KID, "use": "sig", "alg": "RS256"})
            if KID2 in self.published:
                keys.append({**_JWK2, "kid": KID2, "use": "sig", "alg": "RS256"})
            return _Response(json.dumps({"keys": keys}).encode())
        if url == f"{CRM}/api/auth/me":
            self.calls.append((url, {}))
            self.me_calls.append(request.get_header("Authorization") or "")
            if self.crm_accepts is None:
                raise _http_error(url, 503, {"error": "unavailable"})
            if not self.crm_accepts:
                raise _http_error(url, 401, {"error": "unauthorized"})
            return _Response(json.dumps({"data": {"username": self.username}}).encode())
        if url == LOGOUT_URL:
            raw = (request.data or b"").decode()
            body = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
            self.calls.append((url, body))
            if body.get("client_id") != CLIENT_ID or body.get("client_secret") != SECRET:
                raise _http_error(url, 401, {"error": "invalid_client"})
            self.revoked.append(body.get("refresh_token", ""))
            return _Response(b"")
        if url == TOKEN_URL:
            raw = (request.data or b"").decode()
            body = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
            if body.get("grant_type") in ("authorization_code", "refresh_token") \
                    and body.get("client_id") == CLIENT_ID:
                self.calls.append((url, body))
                self.token_calls.append(body)
                return self._token(body)
        return super().__call__(request, timeout)

    def _token(self, body: dict[str, str]) -> _Response:
        if self.token_error:
            raise _http_error(TOKEN_URL, *self.token_error)
        if body.get("client_secret") != SECRET:
            raise _http_error(TOKEN_URL, 401, {"error": "invalid_client",
                                               "error_description": "Invalid client or Invalid client credentials"})
        if body["grant_type"] == "refresh_token":
            if self.refresh_error:
                raise _http_error(TOKEN_URL, *self.refresh_error)
            return _Response(json.dumps(self._tokens(nonce="")).encode())
        issued = self._codes.pop(body.get("code", ""), None)
        if issued is None:
            raise _http_error(TOKEN_URL, 400, {"error": "invalid_grant", "error_description": "Code not valid"})
        if s256(body.get("code_verifier", "")) != issued["code_challenge"]:
            raise _http_error(TOKEN_URL, 400, {"error": "invalid_grant", "error_description": "PKCE verification failed"})
        if body.get("redirect_uri") != issued["redirect_uri"]:
            raise _http_error(TOKEN_URL, 400, {"error": "invalid_grant", "error_description": "Incorrect redirect_uri"})
        return _Response(json.dumps(self._tokens(nonce=issued["nonce"])).encode())

    def _tokens(self, *, nonce: str) -> dict:
        now = int(time.time())
        pem = _PEM2 if self.kid == KID2 else _PEM
        # `jti` - haqiqiy Keycloak kabi har token noyob (bir sekund ichida ikki
        # marta berilsa ham): "yangilandi" ni testlar token farqidan ko'radi.
        base = {"iss": self.iss, "sub": self.sub, "iat": now, "exp": now + self.exp_offset,
                "jti": secrets.token_hex(8),
                "preferred_username": self.username, "email": self.email, "name": self.name}
        if self.azp:
            base["azp"] = self.azp
        id_claims = {**base, "aud": self.aud, "typ": "ID",
                     "nonce": self.nonce_override if self.nonce_override is not None else nonce}
        access_claims = {**base, "aud": "account", "typ": "Bearer",
                         "realm_access": {"roles": list(self.realm_roles)},
                         "resource_access": {
                             CLIENT_ID: {"roles": list(self.client_roles)},
                             "crm-client": {"roles": list(self.other_client_roles)},
                         }}
        headers = {"kid": self.kid}
        payload = {
            "access_token": "opaque-token" if self.access_opaque
            else jwt.encode(access_claims, pem, algorithm="RS256", headers=headers),
            "refresh_token": f"refresh-{secrets.token_hex(4)}",
            "expires_in": 300,
            "token_type": "Bearer",
        }
        if not self.id_token_missing:
            payload["id_token"] = jwt.encode(id_claims, pem, algorithm="RS256", headers=headers)
        return payload


# --- fiksturalar ---------------------------------------------------------------


#: Joriy soxta Keycloak - `net` fiksturasi qo'yadi; `sso_login(client)` ni
#: `net` ni qo'lida tutmaydigan yordamchilar (`_sso_login(client)`) ham chaqira olsin.
_CURRENT: FakeKeycloak | None = None


@pytest.fixture
def net(monkeypatch):
    """Soxta Keycloak o'rnatilgan va SSO sozlangan."""
    global _CURRENT
    fake = FakeKeycloak()
    _CURRENT = fake
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(settings, "sso_issuer", ISSUER)
    monkeypatch.setattr(settings, "sso_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "sso_client_secret", SECRET)
    monkeypatch.setattr(settings, "sso_app_url", APP_URL)
    monkeypatch.setattr(settings, "sso_mobile_redirect", "")
    _reset()
    yield fake
    _reset()


def _reset() -> None:
    oidc_module.JWKS.forget()
    oidc_module.PENDING.clear()
    oidc_module.HANDOFF.clear()
    oidc_module.ID_TOKENS.clear()


@pytest.fixture
def hub(tmp_path, net, monkeypatch):
    """Sozlangan ulanishlar markazi (HRM + CRM) - "+" menyusi testlari uchun."""
    built = ConnectorHub(
        ConnectorStore(tmp_path / "connectors" / "tokens.json"),
        HrmAuth(HRM),
        CrmUserAuth(IDP, "crm-client", "sir", CRM),
    )
    monkeypatch.setattr(connectors_api, "hub", built)
    return built


# --- yordamchilar --------------------------------------------------------------


def start(client, fake: FakeKeycloak, **params) -> tuple[str, str]:
    """`GET /auth/sso/start` -> Keycloak'da "kirdi" -> (code, state)."""
    response = client.get("/api/v1/auth/sso/start", params=params, follow_redirects=False)
    assert response.status_code == 302, response.text
    return fake.authorize(response.headers["location"])


def callback(client, code: str, state: str, **extra) -> tuple[str, dict[str, str]]:
    """`GET /auth/sso/callback` -> (yo'naltirilgan manzil, uning query'si)."""
    response = client.get("/api/v1/auth/sso/callback",
                          params={"code": code, "state": state, **extra}, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(location).query).items()}
    return location, query


def sso_login(client, fake: FakeKeycloak | None = None, roles: list[str] | None = None,
              **params) -> dict:
    """Butun oqim: start -> callback -> exchange. `LoginResponse` (dict).
    `roles` - Keycloak'dagi bizning client'ning rollari (`employee`, `admin`...)."""
    fake = fake or _CURRENT
    assert fake is not None, "`net` fiksturasi kerak"
    if roles is not None:
        fake.client_roles = list(roles)
    code, state = start(client, fake, **params)
    location, query = callback(client, code, state)
    assert "sso" in query, location
    response = client.post("/api/v1/auth/sso/exchange", json={"code": query["sso"]})
    assert response.status_code == 200, response.text
    return response.json()


def sso_session(client, fake: FakeKeycloak | None = None,
                roles: list[str] | None = None) -> tuple[int, dict]:
    """(actor_id, Authorization sarlavhasi) - integratsiya testlari uchun."""
    body = sso_login(client, fake, roles)
    return body["user"]["actorId"], {"Authorization": f"Bearer {body['token']}"}

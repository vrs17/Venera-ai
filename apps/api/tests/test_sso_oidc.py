"""SSO kirish: Keycloak, brauzer oqimi (Authorization Code + PKCE).

`api/v1/auth.py` (`/auth/sso/*`), `services/oidc.py`, `services/identities.py`.
Keycloak'ning o'zi chaqirilmadi - `tests/sso_fake.py` dagi soxta Keycloak
HAQIQIY RS256 imzoli tokenlar beradi, shuning uchun imzo, `iss`, `aud`,
`nonce`, `exp` tekshiruvlari ham haqiqiy kod bilan sinaladi.
"""

from __future__ import annotations

import stat
import urllib.parse

import pytest

from app.core.config import settings
from app.services import analytics
from app.services import oidc as oidc_module
from app.services.analytics import get_db
from app.services.identities import Directory, IdentityStore, SsoProfile
from app.services.users import UserStore
from tests.conftest import ADMIN
from tests.sso_fake import (  # noqa: F401 - fiksturalar
    APP_URL,
    AUTH_URL,
    CALLBACK,
    CERTS_URL,
    CLIENT_ID,
    ISSUER,
    KID,
    KID2,
    LOGOUT_URL,
    SUB,
    TOKEN_URL,
    USERNAME,
    callback,
    hub,
    net,
    sso_login,
    start,
    mobile_callback,
)


def _bearer(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['token']}"}


def _auth_events() -> list[tuple]:
    analytics.flush()
    return [(r["ok"], r["method"], r["reason"], r["channel"])
            for r in get_db().rows("SELECT * FROM auth_events ORDER BY id")]


def _query(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(location).query).items()}


# --- sozlama -------------------------------------------------------------------


def test_config_sso_sozlanmagan(client):
    body = client.get("/api/v1/auth/sso/config").json()
    assert body == {"enabled": False, "localLoginEnabled": True, "startPath": "/api/v1/auth/sso/start"}
    # SSO yo'q - `start` 501, parol bilan kirish ishlaydi.
    assert client.get("/api/v1/auth/sso/start", follow_redirects=False).status_code == 501
    assert client.post("/api/v1/auth/login", json=ADMIN).status_code == 200


def test_config_sso_sozlangan_parol_ochiq(client, net):
    body = client.get("/api/v1/auth/sso/config").json()
    assert body["enabled"] is True and body["localLoginEnabled"] is True


def test_parol_ochiq_bolmasa_login_403(client, net, monkeypatch):
    monkeypatch.setattr(settings, "local_login_enabled", False)
    assert client.get("/api/v1/auth/sso/config").json()["localLoginEnabled"] is False
    response = client.post("/api/v1/auth/login", json=ADMIN)
    assert response.status_code == 403
    assert "SSO" in response.json()["message"]
    assert _auth_events()[-1][:3] == (0, "local", "local_login_disabled")


# --- start ---------------------------------------------------------------------


def test_start_keycloak_manziliga_yuboradi(client, net):
    response = client.get("/api/v1/auth/sso/start", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(AUTH_URL + "?")
    query = _query(location)
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == CALLBACK
    # `offline_access` - CRM ulanishi SSO sessiyasidan ochilgani uchun (default
    # `sso_crm_connect=True`); o'chirilgan holati `test_sso_crm.py` da.
    assert query["scope"] == "openid profile email offline_access"
    assert query["code_challenge_method"] == "S256"
    assert len(query["state"]) >= 32 and len(query["nonce"]) >= 24
    # Parol, login, sir - manzilda hech narsa yo'q.
    assert "secret" not in location.lower()
    assert len(oidc_module.PENDING) == 1


def test_start_manzil_sorovdan_olinadi_app_url_bosh_bolsa(client, net, monkeypatch):
    monkeypatch.setattr(settings, "sso_app_url", "")
    response = client.get("/api/v1/auth/sso/start", follow_redirects=False,
                          headers={"X-Forwarded-Proto": "https", "Host": "llm.brb-tech.uz"})
    assert _query(response.headers["location"])["redirect_uri"] == "https://llm.brb-tech.uz/api/v1/auth/sso/callback"


# --- to'liq kirish -------------------------------------------------------------


def test_kirish_toliq_oqim(client, net, users_file):
    body = sso_login(client, net, roles=["employee", "admin"])
    user = body["user"]
    assert user["email"] == "y.mamajonov@brb-tech.uz"
    assert user["fullName"] == "Test Xodim"
    assert user["actorType"] == "EMPLOYEE"
    # Bizning client rollari Barno rollariga aylanadi; realm `ADMIN` va boshqa
    # client'ning `admin` i (soxta Keycloak ikkalasini ham beradi) o'qilmaydi.
    assert user["roles"] == ["EMPLOYEE", "ADMIN"]
    # users.yaml da 1 va 2 band - yangi odam 3.
    assert user["actorId"] == 3
    assert body["passwordChangeRequired"] is False
    assert body["tokenType"] == "Bearer"

    # Token endpoint: kod + client siri + PKCE verifier + aynan o'sha redirect_uri.
    call = net.token_calls[0]
    assert call["grant_type"] == "authorization_code"
    assert call["redirect_uri"] == CALLBACK and "code_verifier" in call and "client_secret" in call
    assert net.urls()[:2] == [TOKEN_URL, CERTS_URL]

    # Sessiya ishlaydi, rollar ham sessiyada.
    me = client.get("/api/v1/auth/me", headers=_bearer(body))
    assert me.status_code == 200 and me.json()["roles"] == ["EMPLOYEE", "ADMIN"]
    assert client.get("/api/v1/admin/users", headers=_bearer(body)).status_code == 200
    assert _auth_events() == [(1, "sso", None, "web")]

    # Bir martalik kod ikkinchi marta ishlamaydi.
    code = oidc_module.HANDOFF
    assert len(code) == 0


def test_realm_rollari_va_boshqa_client_rollari_oqilmaydi(client, net):
    net.realm_roles = ["ADMIN", "RAG_ADMIN", "offline_access"]
    net.other_client_roles = ["admin", "rag-admin"]
    body = sso_login(client, net, roles=["employee"])
    assert body["user"]["roles"] == ["EMPLOYEE"]
    assert client.get("/api/v1/admin/users", headers=_bearer(body)).status_code == 403


def test_client_roli_bosh_bolsa_kirish_ishlaydi_imtiyozsiz(client, net):
    body = sso_login(client, net, roles=[])
    assert body["user"]["roles"] == []
    assert client.get("/api/v1/auth/me", headers=_bearer(body)).status_code == 200


def test_handoff_kodi_bir_martalik(client, net):
    code, state = start(client, net)
    _, query = callback(client, code, state)
    first = client.post("/api/v1/auth/sso/exchange", json={"code": query["sso"]})
    assert first.status_code == 200
    again = client.post("/api/v1/auth/sso/exchange", json={"code": query["sso"]})
    assert again.status_code == 400
    assert client.post("/api/v1/auth/sso/exchange", json={"code": ""}).status_code == 400
    assert client.post("/api/v1/auth/sso/exchange", json={"code": "yoq"}).status_code == 400


def test_return_ilova_ichidagi_yol_bilan_qaytadi(client, net):
    code, state = start(client, net, **{"return": "/admin/users?q=a", "channel": "desktop"})
    location, query = callback(client, code, state)
    assert location.startswith(f"{APP_URL}/login?")
    assert query["redirect"] == "/admin/users?q=a"
    assert _auth_events() == [(1, "sso", None, "desktop")]


@pytest.mark.parametrize("bad", ["//evil.test/x", "https://evil.test/", "/\\evil", "javascript:alert(1)"])
def test_return_ochiq_yonaltirish_rad_etiladi(client, net, bad):
    code, state = start(client, net, **{"return": bad})
    location, query = callback(client, code, state)
    assert location.startswith(f"{APP_URL}/login?") and "redirect" not in query


def test_mobil_qaytish_manzili_faqat_sozlangani(client, net, monkeypatch):
    from app.services.oidc import pkce_pair

    monkeypatch.setattr(settings, "sso_mobile_redirect", "barnoai://sso")
    verifier, challenge = pkce_pair()
    code, state = start(client, net, **{"return": "barnoai://sso", "channel": "mobile", "app_challenge": challenge})
    location, query = mobile_callback(client, code, state)
    assert location.startswith("barnoai://sso?sso=")
    assert client.post("/api/v1/auth/sso/exchange",
                       json={"code": query["sso"], "verifier": verifier}).status_code == 200
    # Boshqa sxema - rad (ilova ichiga qaytadi).
    code, state = start(client, net, **{"return": "evil://sso"})
    location, _ = callback(client, code, state)
    assert location.startswith(f"{APP_URL}/login?")


# --- actor_id ------------------------------------------------------------------


def test_eski_hisob_email_boyicha_actor_id_saqlanadi(client, net):
    """`users.yaml` dagi admin Keycloak bilan kirsa - eski actor_id (1), tarixi joyida."""
    net.email = ADMIN["email"]
    body = sso_login(client, net)
    assert body["user"]["actorId"] == 1


def test_actor_id_bir_marta_tanlanadi(client, net):
    first = sso_login(client, net)
    net.email, net.name = "yangi@brb-tech.uz", "Yangi Ism"
    second = sso_login(client, net)
    assert second["user"]["actorId"] == first["user"]["actorId"] == 3
    # Keycloak'dagi o'zgarish ko'chadi, raqam qotgan.
    assert second["user"]["fullName"] == "Yangi Ism"


def test_identities_fayli_600_va_sirsiz(client, net):
    body = sso_login(client, net)
    path = settings.identities_file
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text()
    assert SUB in text and body["token"] not in text
    for call in net.token_calls:
        assert call["client_secret"] not in text and call["code_verifier"] not in text


# --- rad etish holatlari ---------------------------------------------------------


def _fail(client, net, *, code: str | None = None, **extra) -> str:
    """start -> callback -> `sso_error` sababi. `code=""` - Keycloak kod bermadi."""
    issued, state = start(client, net)
    location, query = callback(client, issued if code is None else code, state, **extra)
    assert location.startswith(f"{APP_URL}/login?"), location
    assert "sso" not in query
    return query["sso_error"]


def test_notogri_state_expired(client, net):
    code, _ = start(client, net)
    location, query = callback(client, code, "soxta-state")
    assert query["sso_error"] == "expired"
    assert _auth_events() == [(0, "sso", "sso:expired", "web")]


def test_state_ikkinchi_marta_ishlamaydi(client, net):
    code, state = start(client, net)
    callback(client, code, state)
    _, query = callback(client, code, state)
    assert query["sso_error"] == "expired"


def test_pending_muddati_otsa_expired(client, net, monkeypatch):
    monkeypatch.setattr(oidc_module.PENDING, "ttl", -1)
    code, state = start(client, net)
    _, query = callback(client, code, state)
    assert query["sso_error"] == "expired"


def test_odam_keycloakda_bekor_qilsa_denied(client, net):
    assert _fail(client, net, code="", error="access_denied", error_description="User cancelled") == "denied"
    assert net.token_calls == []
    assert _auth_events() == [(0, "sso", "sso:denied", "web")]


def test_kod_eskirgan_bolsa_expired(client, net):
    net.token_error = (400, {"error": "invalid_grant", "error_description": "Code not valid"})
    assert _fail(client, net) == "expired"


def test_client_siri_notogri_config(client, net, monkeypatch):
    monkeypatch.setattr(settings, "sso_client_secret", "boshqa")
    assert _fail(client, net) == "config"
    assert _auth_events()[-1][2] == "sso:invalid_client"


def test_keycloak_javob_bermasa_network(client, net, monkeypatch):
    import urllib.error
    import urllib.request

    def down(request, timeout=None):
        raise urllib.error.URLError("yiqildi")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    code, state = start(client, net)
    _, query = callback(client, code, state)
    assert query["sso_error"] == "network"


def test_nonce_mos_bolmasa_failed(client, net):
    net.nonce_override = "boshqa-nonce"
    assert _fail(client, net) == "failed"
    assert _auth_events()[-1][2] == "sso:nonce"


def test_boshqa_client_uchun_token_failed(client, net):
    net.aud = "crm-client"
    net.azp = "crm-client"
    assert _fail(client, net) == "failed"
    assert _auth_events()[-1][2] == "sso:audience"


def test_boshqa_realm_tokeni_failed(client, net):
    net.iss = "https://idp.test/auth/realms/boshqa"
    assert _fail(client, net) == "failed"
    assert _auth_events()[-1][2] == "sso:issuer"


def test_muddati_otgan_token_failed(client, net):
    net.exp_offset = -120
    assert _fail(client, net) == "failed"
    assert _auth_events()[-1][2] == "sso:expired_token"


def test_id_token_bolmasa_failed(client, net):
    net.id_token_missing = True
    assert _fail(client, net) == "failed"


def test_nomalum_kalit_failed(client, net):
    net.published = []
    assert _fail(client, net) == "failed"
    assert _auth_events()[-1][2] == "sso:unknown_kid"


def test_kalit_almashsa_jwks_qayta_oqiladi(client, net):
    sso_login(client, net)
    assert net.certs_calls == 1
    # Keycloak kalitni almashtirdi: yangi `kid` - JWKS bir marta qayta so'raladi.
    net.published = [KID, KID2]
    net.kid = KID2
    body = sso_login(client, net)
    assert body["user"]["actorId"] == 3
    assert net.certs_calls == 2
    # Tanish kalit uchun qayta so'ralmaydi.
    sso_login(client, net)
    assert net.certs_calls == 2


def test_access_token_jwt_bolmasa_rollar_bosh(client, net):
    net.access_opaque = True
    body = sso_login(client, net, roles=["admin"])
    assert body["user"]["roles"] == []


def test_imzosi_buzilgan_token_failed(client, net, monkeypatch):
    """Tokenning imzosi boshqa kalitniki (soxta Keycloak KID2 bilan imzolaydi,
    JWKS esa KID2 ostida KID ning kalitini e'lon qilgandek)."""
    original = net.__class__.__call__

    def swap(self, request, timeout=None):
        reply = original(self, request, timeout)
        if request.full_url == CERTS_URL:
            import json
            payload = json.loads(reply.read())
            for key in payload["keys"]:
                key["kid"] = KID2
            return type(reply)(json.dumps(payload).encode())
        return reply

    monkeypatch.setattr(net.__class__, "__call__", swap)
    net.kid = KID2
    assert _fail(client, net) == "failed"
    assert _auth_events()[-1][2] == "sso:bad_signature"


# --- chiqish -------------------------------------------------------------------


def test_sso_chiqishda_keycloak_manzili(client, net):
    body = sso_login(client, net)
    response = client.post("/api/v1/auth/logout", headers=_bearer(body))
    assert response.status_code == 200
    url = response.json()["ssoLogoutUrl"]
    assert url.startswith(LOGOUT_URL + "?")
    query = _query(url)
    assert query["client_id"] == CLIENT_ID
    assert query["post_logout_redirect_uri"] == f"{APP_URL}/welcome"
    assert query["id_token_hint"].count(".") == 2
    # Ikkinchi chiqish (token hali yaroqli) - ID token qolmagan: QAYTISH MANZILISIZ
    # (`brb-realm` `post_logout_redirect_uri` ni hint'siz "Missing parameters" bilan rad etadi).
    again = client.post("/api/v1/auth/logout", headers=_bearer(body)).json()["ssoLogoutUrl"]
    assert again == LOGOUT_URL


def test_chiqish_tokeni_api_qayta_ishga_tushganda_yoqolmaydi(client, net, tmp_path):
    """Jonli xato (2026-11-12): ID token faqat xotirada edi - restartdan keyin chiqish Keycloak'ning
    "Missing parameters: id_token_hint" sahifasiga olib borardi. Endi diskda (600)."""
    import stat

    from app.core.config import settings
    from app.services import oidc as oidc_module

    body = sso_login(client, net)
    path = settings.sso_id_tokens_file
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    restarted = oidc_module.IdTokens(lambda: path)          # yangi jarayon - xotira bo'sh
    assert restarted.get(body["user"]["actorId"]).count(".") == 2
    url = client.post("/api/v1/auth/logout", headers=_bearer(body)).json()["ssoLogoutUrl"]
    assert "id_token_hint=" in url and "post_logout_redirect_uri=" in url
    assert restarted.get(body["user"]["actorId"]) is None, "chiqishda o'chiriladi"


def test_zahira_hisob_chiqishida_sso_manzili_yoq(client, net):
    body = client.post("/api/v1/auth/login", json=ADMIN).json()
    assert client.post("/api/v1/auth/logout", headers=_bearer(body)).json()["ssoLogoutUrl"] is None


# --- ombor va bot ------------------------------------------------------------------


def test_directory_bot_uchun_ikkala_manba(tmp_path, users_file):
    users = UserStore.from_file(users_file)
    identities = IdentityStore(tmp_path / "identities.json")
    who = identities.upsert(SsoProfile(subject=SUB, username="y.m", email="y.m@brb.uz"), legacy=users)
    directory = Directory(identities, users)
    assert who.actor_id == 3
    assert directory.by_actor_id(3).to_public().email == "y.m@brb.uz"
    assert directory.by_actor_id(1).to_public().email == ADMIN["email"]
    assert directory.by_actor_id(99) is None


def test_ombor_fayl_ozgarsa_qayta_oqiydi(tmp_path):
    path = tmp_path / "identities.json"
    first = IdentityStore(path)
    second = IdentityStore(path)
    first.upsert(SsoProfile(subject=SUB, username="a"))
    assert second.by_subject(SUB) is not None
    assert len(second) == 1


def test_buzuq_fayl_yiqitmaydi(tmp_path):
    path = tmp_path / "identities.json"
    path.write_text("{buzuq")
    store = IdentityStore(path)
    assert store.by_subject(SUB) is None
    assert store.upsert(SsoProfile(subject=SUB, username="a")).actor_id == 1


# --- oidc moduli -----------------------------------------------------------------


def test_pkce_juftligi_rfc_7636():
    verifier, challenge = oidc_module.pkce_pair()
    assert 43 <= len(verifier) <= 128
    from tests.sso_fake import s256
    assert challenge == s256(verifier)


def test_rol_xaritasi():
    client = oidc_module.KeycloakOidc(ISSUER, CLIENT_ID, "x")
    assert oidc_module.ROLE_MAP["admin"] == "ADMIN"
    assert client.roles("") == []
    assert client.roles("opaque") == []


def test_expiring_ombor_chegarasi(monkeypatch):
    store = oidc_module._Expiring(60)
    monkeypatch.setattr(oidc_module, "_MAX_ENTRIES", 10)
    for i in range(12):
        store.put(f"k{i}", i)
    assert len(store) <= 11
    assert store.pop("k11") == 11
    assert store.pop("k11") is None

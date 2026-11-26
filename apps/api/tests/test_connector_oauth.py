"""Barno konnektorining OAuth eshigi (`app/connector/oauth.py`) va rozilik API si
(`app/api/v1/connector.py`) - `docs/barno-connector.md`.

Tekshiriladi: bosh kalit, metadata (RFC 9728 / 8414), DCR faqat Claude / ChatGPT manzillari
bilan, CIMD faqat ruxsatli hostdan, authorize xatolari (ishonchsiz manzilga yo'naltirish
YO'Q), to'liq oqim (rozilik -> kod -> token -> MCP ruxsati), PKCE, kod va refresh qayta
ishlatilsa ruxsat bekor, rad etish, "Ulangan ilovalar" va bekor qilish.
"""

from __future__ import annotations

import base64
import hashlib
import urllib.parse

import pytest

from app.connector import core
from app.connector import oauth as connector_oauth
from app.core.config import settings

BASE = "https://barno.test"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 43 + "-erifier_0123456789"
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "mcp_connector_enabled", True, raising=False)


def register(client, uris=(CLAUDE,), **extra):
    return client.post("/oauth/register", json={"redirect_uris": list(uris), "client_name": "Claude", **extra})


def authorize(client, client_id, **over):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE,
              "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "st-1",
              "scope": "plaud.read", "resource": f"{BASE}/mcp"}
    params.update(over)
    params = {k: v for k, v in params.items() if v is not None}
    return client.get("/oauth/authorize", params=params, follow_redirects=False)


def query_of(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def consent(client, headers, client_id, scopes=("plaud.read",)) -> dict[str, str]:
    """authorize -> rozilik -> qaytish manzilining so'rov qismi (`code`, `state`, `iss`)."""
    response = authorize(client, client_id)
    assert response.status_code == 302
    request_id = query_of(response.headers["location"])["request"]
    approved = client.post(f"/api/v1/connector/requests/{request_id}/approve", headers=headers,
                           json={"scopes": list(scopes)})
    assert approved.status_code == 200, approved.text
    target = approved.json()["redirect"]
    assert target.startswith(CLAUDE + "?")
    return query_of(target)


def exchange(client, client_id, code, **over):
    form = {"grant_type": "authorization_code", "code": code, "client_id": client_id,
            "redirect_uri": CLAUDE, "code_verifier": VERIFIER, "resource": f"{BASE}/mcp"}
    form.update(over)
    return client.post("/oauth/token", data={k: v for k, v in form.items() if v is not None})


# ================================================================ bosh kalit va metadata


def test_kalit_ochiq_bolsa_hamma_yol_404(client):
    for method, path in [("get", "/.well-known/oauth-protected-resource"),
                         ("get", "/.well-known/oauth-authorization-server"),
                         ("get", "/oauth/authorize"), ("post", "/oauth/token"),
                         ("post", "/oauth/revoke")]:
        assert getattr(client, method)(path).status_code == 404, path
    assert register(client).status_code == 404


def test_metadata(client, on):
    resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == f"{BASE}/mcp"
    assert resource["authorization_servers"] == [BASE]
    assert client.get("/.well-known/oauth-protected-resource").json() == resource
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"] == BASE
    assert meta["authorization_endpoint"] == f"{BASE}/oauth/authorize"
    assert meta["token_endpoint"] == f"{BASE}/oauth/token"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["token_endpoint_auth_methods_supported"] == ["none"]
    assert meta["client_id_metadata_document_supported"] is True
    assert meta["authorization_response_iss_parameter_supported"] is True
    assert meta["scopes_supported"] == ["plaud.read"]


def test_openai_domen_tasdigi(client, monkeypatch):
    url = "/.well-known/openai-apps-challenge"
    monkeypatch.setattr(settings, "openai_apps_challenge", " abc-123 \n", raising=False)
    assert client.get(url).status_code == 404                           # bosh kalit o'chiq
    monkeypatch.setattr(settings, "mcp_connector_enabled", True, raising=False)
    response = client.get(url)
    assert response.status_code == 200 and response.text == "abc-123"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    monkeypatch.setattr(settings, "openai_apps_challenge", "", raising=False)
    assert client.get(url).status_code == 404                           # kod qo'yilmagan


# ================================================================ DCR va CIMD


@pytest.mark.parametrize("uri", [CLAUDE, "https://chatgpt.com/connector_platform_oauth_redirect",
                                 "https://chatgpt.com/connector/oauth/abc_123",
                                 "http://localhost:53122/callback", "http://127.0.0.1/callback"])
def test_dcr_claude_va_chatgpt_manzillari(client, on, uri):
    response = register(client, uris=(uri,))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["client_id"].startswith("dcr_")
    assert body["token_endpoint_auth_method"] == "none"
    assert body["redirect_uris"] == [uri]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("uri", ["https://evil.example/cb", "https://claude.ai.evil.example/api/mcp/auth_callback",
                                 "http://claude.ai/api/mcp/auth_callback", "https://claude.ai/other",
                                 "http://localhost:8080/steal", "http://192.168.1.5/callback"])
def test_dcr_begona_manzil_rad(client, on, uri):
    response = register(client, uris=(CLAUDE, uri))
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_dcr_faqat_kod_va_refresh(client, on):
    response = register(client, grant_types=["client_credentials"])
    assert response.status_code == 400


def test_cimd_ruxsatli_hostdan(client, on, monkeypatch):
    url = "https://claude.ai/oauth/claude-code-client-metadata"
    fetched = []

    def fake(target):
        fetched.append(target)
        return {"client_id": url, "client_name": "Claude Code",
                "redirect_uris": ["http://localhost/callback", "https://evil.example/cb"]}

    monkeypatch.setattr(connector_oauth, "_fetch_json", fake)
    response = authorize(client, url, redirect_uri="http://localhost:61001/callback")
    assert response.status_code == 302
    assert response.headers["location"].startswith(f"{BASE}/connect?request=")
    # Begona manzil hujjatda bo'lsa ham ro'yxatga kirmaydi.
    assert authorize(client, url, redirect_uri="https://evil.example/cb").status_code == 400
    assert fetched == [url]                                        # kesh: ikkinchi marta yuklanmadi


@pytest.mark.parametrize("url", ["https://evil.example/client.json", "http://claude.ai/x.json",
                                 "https://claude.ai/x.json?a=1", "https://claude.ai:8443/x.json"])
def test_cimd_ruxsatsiz_manzil(client, on, monkeypatch, url):
    monkeypatch.setattr(connector_oauth, "_fetch_json", lambda target: pytest.fail("yuklanmasligi kerak"))
    response = authorize(client, url)
    assert response.status_code == 400 and "location" not in response.headers


def test_cimd_hujjati_boshqa_id_bilan(client, on, monkeypatch):
    url = "https://chatgpt.com/oauth/client.json"
    monkeypatch.setattr(connector_oauth, "_fetch_json",
                        lambda target: {"client_id": "https://chatgpt.com/other.json",
                                        "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"]})
    assert authorize(client, url).status_code == 400


# ================================================================ authorize xatolari


def test_authorize_nomalum_mijoz_yonaltirilmaydi(client, on):
    response = authorize(client, "dcr_nope")
    assert response.status_code == 400 and "location" not in response.headers


def test_authorize_boshqa_manzil_yonaltirilmaydi(client, on):
    client_id = register(client).json()["client_id"]
    response = authorize(client, client_id, redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect")
    assert response.status_code == 400 and "location" not in response.headers


@pytest.mark.parametrize(("over", "error"), [
    ({"code_challenge_method": "plain"}, "invalid_request"),
    ({"code_challenge": None}, "invalid_request"),
    ({"response_type": "token"}, "unsupported_response_type"),
    ({"resource": "https://other.example/mcp"}, "invalid_target"),
])
def test_authorize_xatosi_mijozga_qaytadi(client, on, over, error):
    client_id = register(client).json()["client_id"]
    response = authorize(client, client_id, **over)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(CLAUDE + "?")
    assert query_of(location) | {} == {**query_of(location), "error": error, "state": "st-1", "iss": BASE}


def test_resource_yoq_va_ortiqcha_scope(client, on, auth):
    client_id = register(client).json()["client_id"]
    response = authorize(client, client_id, resource=None, scope="openid offline_access")
    request_id = query_of(response.headers["location"])["request"]
    view = client.get(f"/api/v1/connector/requests/{request_id}", headers=auth).json()
    assert view["client"] == "Claude" and view["host"] == "claude.ai"
    assert view["scopes"] == [{"id": "plaud.read"}]


# ================================================================ to'liq oqim


def test_toliq_oqim_rozilikdan_mcp_ruxsatigacha(client, on, user_auth):
    client_id = register(client).json()["client_id"]
    back = consent(client, user_auth, client_id)
    assert back["state"] == "st-1" and back["iss"] == BASE
    response = exchange(client, client_id, back["code"])
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert tokens["token_type"] == "Bearer" and tokens["scope"] == "plaud.read"
    assert tokens["expires_in"] == settings.mcp_access_ttl
    assert response.headers["cache-control"] == "no-store"
    grant = core.resolve_access_token(tokens["access_token"])
    assert grant is not None and grant.actor_id == 2 and grant.client_name == "Claude"
    assert core.user_for_grant(grant).actorId == 2
    # Refresh token MCP da ishlamaydi; sayt tokeni ham.
    assert core.resolve_access_token(tokens["refresh_token"]) is None
    assert core.resolve_access_token(user_auth["Authorization"].split()[1]) is None


def test_pkce_va_mijoz_tekshiruvi(client, on, user_auth):
    client_id = register(client).json()["client_id"]
    code = consent(client, user_auth, client_id)["code"]
    assert exchange(client, client_id, code, code_verifier="x" * 43).json()["error"] == "invalid_grant"
    # Muvaffaqiyatsiz urinish kodni ishlatmaydi, lekin boshqa mijoz yoki manzil bilan ham o'tmaydi.
    other = register(client).json()["client_id"]
    assert exchange(client, other, code).json()["error"] == "invalid_grant"
    assert exchange(client, client_id, code, redirect_uri="http://localhost/callback").json()["error"] == "invalid_grant"
    assert exchange(client, client_id, code, resource="https://other.example/mcp").json()["error"] == "invalid_target"
    assert exchange(client, client_id, code).status_code == 200


def test_kod_qayta_ishlatilsa_ruxsat_bekor(client, on, user_auth):
    client_id = register(client).json()["client_id"]
    code = consent(client, user_auth, client_id)["code"]
    first = exchange(client, client_id, code).json()
    assert core.resolve_access_token(first["access_token"]) is not None
    assert exchange(client, client_id, code).json()["error"] == "invalid_grant"
    assert core.resolve_access_token(first["access_token"]) is None


def test_refresh_aylanadi_va_eskisi_qaytsa_bekor(client, on, user_auth):
    client_id = register(client).json()["client_id"]
    first = exchange(client, client_id, consent(client, user_auth, client_id)["code"]).json()
    form = {"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": client_id}
    second = client.post("/oauth/token", data=form).json()
    assert second["access_token"] != first["access_token"]
    assert core.resolve_access_token(second["access_token"]) is not None
    # Eski refresh qayta keldi - o'g'irlangan bo'lishi mumkin: butun ruxsat bekor.
    assert client.post("/oauth/token", data=form).json()["error"] == "invalid_grant"
    assert core.resolve_access_token(second["access_token"]) is None


def test_refresh_bloklangan_odamga_berilmaydi(client, on, user_auth, monkeypatch):
    client_id = register(client).json()["client_id"]
    first = exchange(client, client_id, consent(client, user_auth, client_id)["code"]).json()
    monkeypatch.setattr(core, "user_for_grant", lambda grant: None)
    response = client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                                 "refresh_token": first["refresh_token"]})
    assert response.json()["error"] == "invalid_grant"


def test_nomalum_grant_turi(client, on):
    response = client.post("/oauth/token", data={"grant_type": "client_credentials", "client_id": "x"})
    assert response.json()["error"] == "unsupported_grant_type"
    assert client.post("/oauth/token", data={"grant_type": "refresh_token"}).status_code == 401


# ================================================================ rad, ilovalar, bekor qilish


def test_rad_etish(client, on, user_auth):
    client_id = register(client).json()["client_id"]
    request_id = query_of(authorize(client, client_id).headers["location"])["request"]
    denied = client.post(f"/api/v1/connector/requests/{request_id}/deny", headers=user_auth).json()
    assert query_of(denied["redirect"]) == {"error": "access_denied", "state": "st-1", "iss": BASE}
    # So'rov yondi - qayta tasdiqlab bo'lmaydi.
    again = client.post(f"/api/v1/connector/requests/{request_id}/approve", headers=user_auth,
                        json={"scopes": ["plaud.read"]})
    assert again.status_code == 404


def test_qamrovsiz_rozilik_400(client, on, user_auth):
    client_id = register(client).json()["client_id"]
    request_id = query_of(authorize(client, client_id).headers["location"])["request"]
    response = client.post(f"/api/v1/connector/requests/{request_id}/approve", headers=user_auth,
                           json={"scopes": ["crm.write"]})
    assert response.status_code == 400


def test_rozilik_kirishsiz_401(client, on):
    client_id = register(client).json()["client_id"]
    request_id = query_of(authorize(client, client_id).headers["location"])["request"]
    assert client.get(f"/api/v1/connector/requests/{request_id}").status_code == 401


def test_ulangan_ilovalar_va_uzish(client, on, user_auth, auth):
    client_id = register(client).json()["client_id"]
    tokens = exchange(client, client_id, consent(client, user_auth, client_id)["code"]).json()
    listing = client.get("/api/v1/connector/apps", headers=user_auth).json()
    assert listing["enabled"] is True
    apps = listing["apps"]
    assert [(a["client"], a["scopes"]) for a in apps] == [("Claude", ["plaud.read"])]
    assert client.get("/api/v1/connector/apps", headers=auth).json()["apps"] == []
    # Boshqa odam uza olmaydi.
    assert client.delete(f"/api/v1/connector/apps/{apps[0]['id']}", headers=auth).status_code == 404
    assert core.resolve_access_token(tokens["access_token"]) is not None
    assert client.delete(f"/api/v1/connector/apps/{apps[0]['id']}", headers=user_auth).json() == {"revoked": True}
    assert core.resolve_access_token(tokens["access_token"]) is None
    assert client.get("/api/v1/connector/apps", headers=user_auth).json()["apps"] == []


def test_ikkinchi_qurilma_birinchisini_uzmaydi(client, on, user_auth):
    """CIMD da `client_id` - mahsulotning bitta URL i (hamma Claude Code nusxalari): ikkinchi
    qurilmadagi rozilik birinchisini uzmasligi kerak."""
    client_id = register(client).json()["client_id"]
    first = exchange(client, client_id, consent(client, user_auth, client_id)["code"]).json()
    second = exchange(client, client_id, consent(client, user_auth, client_id)["code"]).json()
    assert core.resolve_access_token(first["access_token"]) is not None
    assert core.resolve_access_token(second["access_token"]) is not None
    assert len(client.get("/api/v1/connector/apps", headers=user_auth).json()["apps"]) == 2


def test_ruxsatlar_chegarasi_eng_eskisini_uzadi(client, on, user_auth, monkeypatch):
    from app.connector import store as store_module

    monkeypatch.setattr(store_module, "MAX_GRANTS_PER_ACTOR", 2)
    client_id = register(client).json()["client_id"]
    tokens = [exchange(client, client_id, consent(client, user_auth, client_id)["code"]).json()
              for _ in range(3)]
    assert core.resolve_access_token(tokens[0]["access_token"]) is None
    assert all(core.resolve_access_token(t["access_token"]) for t in tokens[1:])


def test_revoke_endpoint(client, on, user_auth):
    client_id = register(client).json()["client_id"]
    tokens = exchange(client, client_id, consent(client, user_auth, client_id)["code"]).json()
    assert client.post("/oauth/revoke", data={"token": tokens["refresh_token"]}).status_code == 200
    assert core.resolve_access_token(tokens["access_token"]) is None
    assert client.post("/oauth/revoke", data={"token": "nomalum"}).status_code == 200


def test_kalit_ochiq_bolsa_ilovalar_korinadi_rozilik_yoq(client, on, user_auth, monkeypatch):
    client_id = register(client).json()["client_id"]
    exchange(client, client_id, consent(client, user_auth, client_id)["code"])
    request_id = query_of(authorize(client, client_id).headers["location"])["request"]
    monkeypatch.setattr(settings, "mcp_connector_enabled", False)
    assert client.get(f"/api/v1/connector/requests/{request_id}", headers=user_auth).status_code == 404
    listing = client.get("/api/v1/connector/apps", headers=user_auth).json()
    assert listing["enabled"] is False and len(listing["apps"]) == 1


def test_eski_dcr_mijozlari_tozalanadi(on):
    store = core.store()
    store.put_client("dcr_old", "dcr", "Claude", [CLAUDE], {})
    assert store.prune_dcr(idle_seconds=-1) == 1
    assert store.client("dcr_old") is None


def test_ishlatilmagan_dcr_bir_soatda_tozalanadi_oqimdagisi_qoladi(on):
    clock = {"now": 1_000_000.0}
    store = core.reset_for_tests(settings.connector_dir / "clock.db", clock=lambda: clock["now"])
    store.put_client("dcr_unused", "dcr", "Claude", [CLAUDE], {})
    store.put_client("dcr_busy", "dcr", "Claude", [CLAUDE], {})
    clock["now"] += 3500
    store.put_request("dcr_busy", CLAUDE, "", CHALLENGE, frozenset({"plaud.read"}), f"{BASE}/mcp")
    clock["now"] += 200                                   # ikkalasi ham 1 soatdan eski
    assert store.prune_dcr(idle_seconds=7 * 86400) == 1
    assert store.client("dcr_unused") is None and store.client("dcr_busy") is not None


def test_dcr_chegarasi_toliqda_ishlatilmaganlar_boshatiladi(client, on, monkeypatch):
    monkeypatch.setattr(connector_oauth, "DCR_MAX_CLIENTS", 3)
    for _ in range(3):
        assert register(client).status_code == 201
    # To'ldirilgan, lekin hech biri ruxsatga yetmagan - haqiqiy ro'yxatdan o'tish 503 olmaydi.
    assert register(client).status_code == 201
    assert core.store().count_clients("dcr") == 3


def test_buzuq_portli_cimd_500_emas(client, on, monkeypatch):
    monkeypatch.setattr(connector_oauth, "_fetch_json", lambda target: pytest.fail("yuklanmasligi kerak"))
    for url in ("https://claude.ai:99999/x.json", "https://claude.ai:abc/x.json"):
        response = authorize(client, url)
        assert response.status_code == 400 and "location" not in response.headers

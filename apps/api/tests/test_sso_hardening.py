"""SSO: jonli chiqishdan oldingi ko'rib chiqish (2026-11-12) topgan kamchiliklar.

Har test bitta va'dani tutadi:
  * kirish uni BOSHLAGAN brauzerga bog'langan - `state` yoki bir martalik kod
    boshqa brauzerda ishlamaydi (login CSRF);
  * Mini App va mobil ilova chiqishda Keycloak sahifasiga yuborilmaydi;
  * ESKI kirish yozgan rollarga ishonilmaydi (realm / crm-client rollari);
  * `offline_access` berilmasa odam "sozlama" sababini ko'radi;
  * JWKS so'rovi yiqilsa keyingi kirish darhol qayta so'raydi;
  * CRM tokenini yangilash shu orada o'zgargan ulanishni buzmaydi.
"""

from __future__ import annotations

import http.client
import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_identity_store
from app.api.v1 import connectors as connectors_api
from app.core.config import settings
from app.main import app
from app.services import oidc as oidc_module
from app.core.security import create_token
from app.services.identities import CLIENT_ROLES, IdentityStore, SsoProfile
from app.services.integrations.connectors import (
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
)
from app.services.integrations.crm_sso import CrmSso
from app.services.oidc import OidcError
from app.services.oidc import from_settings as oidc_from_settings
from tests.sso_fake import (  # noqa: F401 - fiksturalar
    CERTS_URL,
    KID,
    KID2,
    LOGOUT_URL,
    SUB,
    USERNAME,
    callback,
    net,
    sso_login,
    start,
    mobile_callback,
)
from tests.test_connectors import CRM, HRM, IDP

COOKIE = "barno_sso"


def _bearer(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['token']}"}


def _other_browser() -> TestClient:
    """Ikkinchi brauzer: o'sha ilova, lekin O'Z cookie idishi bilan (bo'sh)."""
    return TestClient(app)


# --- kirish boshlagan brauzerga bog'langan ------------------------------------------


def test_start_brauzerga_cookie_qoyadi(client, net):
    response = client.get("/api/v1/auth/sso/start", follow_redirects=False)
    assert response.status_code == 302
    header = response.headers["set-cookie"]
    assert header.startswith(f"{COOKIE}=")
    lowered = header.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered
    # Muddat: kutish (600 s) + bir martalik kod (90 s) - `exchange` gacha yashasin.
    assert "path=/api/v1/auth/sso" in lowered and "max-age=690" in lowered
    # Dev (`http://`) da Secure yo'q - aks holda brauzer cookie'ni qaytarmasdi.
    assert "secure" not in lowered
    # Cookie qiymati Keycloak'ga KETMAYDI va serverda faqat xeshi turadi.
    value = header.split(";", 1)[0].split("=", 1)[1]
    assert value not in response.headers["location"]
    state = net.authorize(response.headers["location"])[1]
    assert oidc_module.PENDING._items[state][1].binding not in ("", value)


def test_prodda_cookie_host_prefiksi_bilan(client, net, monkeypatch):
    """HTTPS da cookie `__Host-` nomi bilan: Secure, Path=/, Domain'siz - qo'shni
    subdomen uni "tashlab" qo'ya olmaydi."""
    monkeypatch.setattr(settings, "sso_app_url", "https://llm.test")
    response = client.get("/api/v1/auth/sso/start", headers={"host": "llm.test"}, follow_redirects=False)
    assert response.status_code == 302
    header = response.headers["set-cookie"]
    lowered = header.lower()
    assert header.startswith("__Host-barno_sso=")
    assert "secure" in lowered and "path=/;" in lowered + ";" and "domain=" not in lowered
    assert "httponly" in lowered and "samesite=lax" in lowered


def test_prodda_butun_oqim_host_cookie_bilan(client, net, monkeypatch):
    """Prod shakli (https tashqi manzil, API o'zi http ko'radi): cookie nomi boshqa,
    lekin oqim o'sha - o'z brauzerida ishlaydi, cookie'siz rad etiladi."""
    monkeypatch.setattr(settings, "sso_app_url", "https://llm.test")
    host = {"host": "llm.test"}

    def begin() -> tuple[str, str, str]:
        response = client.get("/api/v1/auth/sso/start", headers=host, follow_redirects=False)
        value = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
        code, state = net.authorize(response.headers["location"])
        return code, state, value

    # Cookie'siz (boshqa brauzer): rad.
    code, state, _ = begin()
    client.cookies.clear()
    response = client.get("/api/v1/auth/sso/callback", params={"code": code, "state": state},
                          headers=host, follow_redirects=False)
    assert response.headers["location"] == "https://llm.test/login?sso_error=expired"

    # O'z brauzeri: `Secure` cookie'ni test klienti http orqali o'zi yubormaydi - qo'lda.
    code, state, value = begin()
    client.cookies.clear()
    jar = {**host, "cookie": f"__Host-barno_sso={value}"}
    response = client.get("/api/v1/auth/sso/callback", params={"code": code, "state": state},
                          headers=jar, follow_redirects=False)
    location = response.headers["location"]
    assert location.startswith("https://llm.test/login?sso="), location
    handoff = location.split("sso=", 1)[1]
    assert client.post("/api/v1/auth/sso/exchange", json={"code": handoff}, headers=jar).status_code == 200


# --- sayt asosiy manzildan boshqa host bilan ochilgan ---------------------------------


def test_boshqa_hostda_boshlangan_kirish_asosiy_manzilga_kochadi(client, net, monkeypatch):
    """Sayt IP bilan ochilgan: Keycloak baribir domenga qaytaradi, shu hostdagi cookie
    u yerga yetmaydi - kirish domenda qaytadan boshlanadi (holat yaratilmaydi)."""
    monkeypatch.setattr(settings, "sso_app_url", "https://llm.test")
    response = client.get("/api/v1/auth/sso/start", params={"return": "/admin/users", "channel": "web"},
                          headers={"host": "10.10.50.4:5173"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == \
        "https://llm.test/api/v1/auth/sso/start?return=%2Fadmin%2Fusers&channel=web&_c=1"
    assert "set-cookie" not in response.headers
    assert len(oidc_module.PENDING) == 0


def test_kochirish_ikkinchi_marta_takrorlanmaydi(client, net, monkeypatch):
    """Proksi Host'ni o'zgartirib yuborsa ham cheksiz aylanish yo'q: belgi bilan kelgan
    so'rov ko'chirilmaydi, kirish boshlanadi."""
    monkeypatch.setattr(settings, "sso_app_url", "https://llm.test")
    response = client.get("/api/v1/auth/sso/start", params={"_c": "1"},
                          headers={"host": "ichki-nom:8010"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.test/")


def test_app_url_bosh_bolsa_kochirilmaydi(client, net, monkeypatch):
    """Dev: `SSO_APP_URL` bo'sh - manzil so'rovning o'zidan olinadi, ko'chirish yo'q."""
    monkeypatch.setattr(settings, "sso_app_url", "")
    response = client.get("/api/v1/auth/sso/start", headers={"host": "10.10.50.4:5174"},
                          follow_redirects=False)
    assert response.headers["location"].startswith("https://idp.test/")
    assert "barno_sso=" in response.headers["set-cookie"]


def test_callback_boshqa_brauzerda_rad_etiladi(client, net):
    code, state = start(client, net)                      # A brauzeri boshladi
    stranger = _other_browser()                           # havola B ga yuborildi
    response = stranger.get("/api/v1/auth/sso/callback",
                            params={"code": code, "state": state}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login?sso_error=expired")
    # Keycloak'ga kod almashtirishga ham borilmagan - B hech kim bo'lib kirmadi.
    assert not [b for b in net.token_calls if b.get("grant_type") == "authorization_code"]
    # `state` bir martalik: A ham endi qaytadan boshlaydi.
    _, query = callback(client, code, state)
    assert query == {"sso_error": "expired"}


def test_bir_martalik_kod_boshqa_brauzerda_ishlamaydi_va_yonadi(client, net):
    code, state = start(client, net)
    _, query = callback(client, code, state)              # A oxirgi qadamgacha bordi
    handoff = query["sso"]

    stranger = _other_browser()                           # ... va havolani B ga berdi
    refused = stranger.post("/api/v1/auth/sso/exchange", json={"code": handoff})
    assert refused.status_code == 400
    assert "token" not in refused.text
    # Kod yondi: A ning o'zi ham endi ishlata olmaydi (o'g'irlangan havola ikki marta sinalmaydi).
    assert client.post("/api/v1/auth/sso/exchange", json={"code": handoff}).status_code == 400


def test_oz_brauzerida_kirish_ishlaydi_va_cookie_ochadi(client, net):
    code, state = start(client, net)
    assert client.cookies.get(COOKIE)
    _, query = callback(client, code, state)
    response = client.post("/api/v1/auth/sso/exchange", json={"code": query["sso"]})
    assert response.status_code == 200 and response.json()["token"]
    assert f"{COOKIE}=" in response.headers["set-cookie"] and "max-age=0" in response.headers["set-cookie"].lower()
    assert not client.cookies.get(COOKIE)


def test_ikkinchi_boshlash_birinchisini_bekor_qiladi(client, net):
    """Ikki varaqda "Kirish" bosilsa oxirgisi ishlaydi; birinchisi qaytadan boshlanadi."""
    first = start(client, net)
    second = start(client, net)
    _, query = callback(client, *first)
    assert query == {"sso_error": "expired"}
    _, query = callback(client, *second)
    assert "sso" in query


# --- mobil qaytish kodini brauzer almashtira olmaydi ------------------------------------


def test_mobil_kodni_brauzer_almashtira_olmaydi(client, net, monkeypatch):
    """Mobil qaytish kodi cookie bilan bog'lanmagan (uni ilova almashtiradi). Hujumchi
    uni `/login?sso=` havolasida birovga bersa - brauzer so'rovi rad etiladi."""
    monkeypatch.setattr(settings, "sso_mobile_redirect", "venera-rec://sso")
    from app.services.oidc import pkce_pair

    verifier, challenge = pkce_pair()

    def mobile_code() -> str:
        code, state = start(client, net, **{"return": "venera-rec://sso", "channel": "mobile",
                                             "app_challenge": challenge})
        location, query = mobile_callback(client, code, state)
        assert location.startswith("venera-rec://sso?sso=")
        return query["sso"]

    victim = _other_browser()
    refused = victim.post("/api/v1/auth/sso/exchange", json={"code": mobile_code(), "verifier": verifier},
                          headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"})
    assert refused.status_code == 400
    # Ilovaning o'zi (brauzer sarlavhalarisiz, cookie'siz, O'Z verifier'i bilan) - ishlaydi.
    app_client = _other_browser()
    assert app_client.post("/api/v1/auth/sso/exchange",
                           json={"code": mobile_code(), "verifier": verifier}).status_code == 200


def test_mobil_kodni_boshqa_ilova_verifiersiz_almashtira_olmaydi(client, net, monkeypatch):
    """`venera-rec://` sxemasini boshqa ilova ham ro'yxatdan o'tkazishi mumkin (RFC 8252):
    u kodni ushlab olsa ham verifier'siz yoki boshqa verifier bilan almashtira olmaydi,
    urinish esa kodni yoqadi. Challenge'siz mobil kirish umuman boshlanmaydi."""
    from app.services.oidc import pkce_pair

    monkeypatch.setattr(settings, "sso_mobile_redirect", "venera-rec://sso")
    verifier, challenge = pkce_pair()
    other_verifier, _ = pkce_pair()

    def mobile_code() -> str:
        code, state = start(client, net, **{"return": "venera-rec://sso", "channel": "mobile",
                                             "app_challenge": challenge})
        return mobile_callback(client, code, state)[1]["sso"]

    thief = _other_browser()
    stolen = mobile_code()
    assert thief.post("/api/v1/auth/sso/exchange", json={"code": stolen}).status_code == 400
    assert thief.post("/api/v1/auth/sso/exchange",
                      json={"code": stolen, "verifier": verifier}).status_code == 400, "kod yondi"
    assert thief.post("/api/v1/auth/sso/exchange",
                      json={"code": mobile_code(), "verifier": other_verifier}).status_code == 400
    refused = client.get("/api/v1/auth/sso/start", params={"return": "venera-rec://sso", "channel": "mobile"},
                         follow_redirects=False)
    assert refused.status_code == 400


# --- chiqish: Mini App va mobil ilova Keycloak'ga yuborilmaydi ------------------------


def test_sso_bolmagan_sessiya_chiqishida_keycloak_manzili_yoq(client, net):
    """Telegram (`/telegram/session`), qurilma va zahira sessiyalarida `sso` belgisi yo'q -
    odamning SSO yozuvi bo'lsa ham Keycloak'ga yuborilmaydi (Mini App WebView chiqib ketmasin)."""
    body = sso_login(client, net)                       # shaxs yozuvi yaratildi
    subject = get_identity_store().by_actor_id(body["user"]["actorId"]).subject
    plain, _ = create_token(subject)                    # o'sha odam, lekin SSO sessiyasi emas
    response = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {plain}",
                                                           "X-Venera-Client": "miniapp"})
    assert response.status_code == 200
    assert response.json()["ssoLogoutUrl"] is None


@pytest.mark.parametrize("channel", ["web", "miniapp"])
def test_sso_sessiyasi_chiqishida_keycloak_manzili_bor(client, net, channel):
    """Belgi klient sarlavhasidan emas, sessiyadan: Mini App to'plami oddiy brauzerda
    SSO sessiyasi bilan ochilgan bo'lsa ham Keycloak sessiyasi yopiladi."""
    body = sso_login(client, net)
    response = client.post("/api/v1/auth/logout",
                           headers={**_bearer(body), "X-Venera-Client": channel})
    assert response.json()["ssoLogoutUrl"].startswith(LOGOUT_URL + "?")


# --- eski kirish yozgan rollarga ishonilmaydi -----------------------------------------


def _strip_stamp(path, roles: list[str]) -> None:
    """Yozuvni ESKI kirish yozgandek qiladi: `client_roles` yo'q, `roles` da realm/CRM rollari."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for record in data.values():
        record.pop(CLIENT_ROLES, None)
        record["roles"] = list(roles)
    path.write_text(json.dumps(data), encoding="utf-8")


def _old_code_rewrites(path, roles: list[str]) -> None:
    """Rollback: ESKI kod yozuvni qayta yozdi - `roles` ni almashtirdi, `client_roles` ni
    bilmaydi va unga tegmadi."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for record in data.values():
        record["roles"] = list(roles)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_eski_yozuv_rollari_oqilmaydi(tmp_path):
    path = tmp_path / "identities.json"
    store = IdentityStore(path)
    profile = SsoProfile(subject=SUB, username=USERNAME, email="y@brb-tech.uz",
                         full_name="Test Xodim", roles=("EMPLOYEE",))
    assert store.upsert(profile).roles == ["EMPLOYEE"]
    assert json.loads(path.read_text())[SUB][CLIENT_ROLES] == ["EMPLOYEE"]

    _strip_stamp(path, ["ADMIN", "RAG_ADMIN", "EMPLOYEE", "crm-manager"])
    old = IdentityStore(path).by_subject(SUB)
    assert old is not None and old.roles == [] and old.actor_id == 1     # shaxs joyida, rollar yo'q

    # Odam yangi oqim bilan kirdi - rollar yana ishonchli manbadan.
    assert IdentityStore(path).upsert(profile).roles == ["EMPLOYEE"]

    # Rollback: eski kod `roles` ga realm rollarini yozib ketdi. Qayta chiqarilganda
    # ular ishonchli bo'lib QOLMAYDI - faqat oxirgi yangi kirishdagi client rollari.
    _old_code_rewrites(path, ["ADMIN", "RAG_ADMIN"])
    assert IdentityStore(path).by_subject(SUB).roles == ["EMPLOYEE"]


def test_eski_yozuvdagi_admin_roli_sessiyaga_otmaydi(client, net):
    body = sso_login(client, net, roles=["employee"])
    me = client.get("/api/v1/auth/me", headers=_bearer(body)).json()
    assert me["roles"] == ["EMPLOYEE"]

    _strip_stamp(settings.identities_file, ["ADMIN", "RAG_ADMIN"])
    get_identity_store.cache_clear()
    me = client.get("/api/v1/auth/me", headers=_bearer(body)).json()
    assert "ADMIN" not in me["roles"] and "RAG_ADMIN" not in me["roles"]
    assert client.get("/api/v1/admin/me", headers=_bearer(body)).status_code == 403


# --- offline_access berilmasa - "sozlama" ----------------------------------------------


def test_invalid_scope_sozlama_xatosi(client, net):
    _, state = start(client, net)
    _, query = callback(client, "", state, error="invalid_scope",
                        error_description="Invalid scopes: openid profile email offline_access")
    assert query == {"sso_error": "config"}


def test_offline_token_berilmasa_sozlama_xatosi(client, net):
    net.token_error = (400, {"error": "not_allowed",
                             "error_description": "Offline tokens not allowed for the user or client"})
    code, state = start(client, net)
    _, query = callback(client, code, state)
    assert query == {"sso_error": "config"}


# --- JWKS: yiqilgan so'rov keyingisini to'smaydi ----------------------------------------


def test_jwks_yiqilgan_sorov_cheklov_yozmaydi(net, monkeypatch):
    jwks = oidc_module.Jwks()
    jwks.key(CERTS_URL, KID, 5)                            # kesh to'ldi (faqat KID)
    net.published = [KID, KID2]                            # Keycloak kalitni almashtirdi

    real = oidc_module._get_json
    calls = {"n": 0}

    def flaky(url, timeout, *, what):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OidcError("SSO (Keycloak) bilan aloqa yo'q", status=502, code="network")
        return real(url, timeout, what=what)

    monkeypatch.setattr(oidc_module, "_get_json", flaky)
    with pytest.raises(OidcError):
        jwks.key(CERTS_URL, KID2, 5)                       # birinchi qayta so'rov yiqildi
    assert jwks.key(CERTS_URL, KID2, 5) is not None        # ikkinchisi DARHOL qayta so'raydi
    assert calls["n"] == 2


# --- CRM: yangilash shu orada o'zgargan ulanishni buzmaydi ---------------------------------


@pytest.fixture
def hub(tmp_path, net, monkeypatch):
    monkeypatch.setattr(settings, "sso_crm_connect", True)
    built = ConnectorHub(
        ConnectorStore(tmp_path / "connectors" / "tokens.json"),
        HrmAuth(HRM),
        CrmUserAuth(IDP, "crm-client", "sir", CRM),
        sso=CrmSso(oidc_from_settings, lambda: CRM),
    )
    monkeypatch.setattr(connectors_api, "hub", built)
    return built


def _during_refresh(hub: ConnectorHub, monkeypatch, action) -> None:
    """Keycloak yangilashi "tarmoqda" turganda `action` ni bajaradi."""
    real = hub.sso.refresh

    def slow(refresh_token: str):
        result = real(refresh_token)
        action()
        return result

    monkeypatch.setattr(hub.sso, "refresh", slow)


def test_yangilash_paytida_uzilgan_ulanish_tirilmaydi(client, hub, net, monkeypatch):
    uid = str(sso_login(client, net)["user"]["actorId"])
    hub._sso_cache.pop(uid)
    _during_refresh(hub, monkeypatch, lambda: hub.disconnect(uid, "crm"))

    assert hub.tokens(uid) == {}
    assert "crm" not in hub.store.get(uid) and "sso" not in hub.store.get(uid)
    assert next(s for s in hub.status(uid) if s["id"] == "crm")["state"] == "disconnected"


def test_yangilash_paytidagi_qayta_kirish_ustun(client, hub, net, monkeypatch):
    uid = str(sso_login(client, net)["user"]["actorId"])
    hub._sso_cache.pop(uid)
    _during_refresh(hub, monkeypatch, lambda: hub.adopt_crm(
        uid, USERNAME, "yangi-access", "yangi-refresh", 300.0, via="sso"))

    assert hub.tokens(uid) == {"crm": "yangi-access"}
    assert hub.store.get(uid)["sso"]["refresh_token"] == "yangi-refresh"


def test_olgan_sessiya_xabari_yangi_ulanishni_buzmaydi(client, hub, net, monkeypatch):
    uid = str(sso_login(client, net)["user"]["actorId"])
    hub._sso_cache.pop(uid)
    real = hub.sso.refresh

    def dead_but_replaced(refresh_token: str):
        hub.adopt_crm(uid, USERNAME, "yangi-access", "yangi-refresh", 300.0, via="sso")
        net.refresh_error = (400, {"error": "invalid_grant", "error_description": "Session not active"})
        return real(refresh_token)

    monkeypatch.setattr(hub.sso, "refresh", dead_but_replaced)
    hub.tokens(uid)
    entry = hub.store.get(uid)["sso"]
    assert entry["refresh_token"] == "yangi-refresh" and entry["expired"] is False


def test_bekor_qilish_yiqilsa_ham_uzish_bajariladi(client, hub, net, monkeypatch):
    """Keycloak yoki oldidagi proksi buzuq javob bersa (`HTTPException`) ham "uzish" yarim
    yo'lda qolmaydi: ulanish o'chirilgan, API 200. CRM ni faqat admin panel uzadi."""
    body = sso_login(client, net, roles=["admin"])
    uid = str(body["user"]["actorId"])
    original = net.__class__.__call__

    def broken(self, request, timeout=None):
        if request.full_url.endswith("/revoke"):
            raise http.client.BadStatusLine("")
        return original(self, request, timeout)

    monkeypatch.setattr(net.__class__, "__call__", broken)
    response = client.delete(f"/api/v1/admin/users/{uid}/connectors/crm", headers=_bearer(body))
    assert response.status_code == 200 and response.json()["state"] == "disconnected"
    assert "crm" not in hub.store.get(uid) and hub.tokens(uid) == {}


def test_yangilash_faqat_osha_sessiyaga_yoziladi(client, hub, net):
    """Rotatsiya yozuvning boshqa maydonlariga tegmaydi, `replace_if` esa boshqa sessiya
    (boshqa refresh token) yoki yo'q yozuv ustiga hech narsa yozmaydi."""
    uid = str(sso_login(client, net)["user"]["actorId"])
    before = hub.store.get(uid)["sso"]["refresh_token"]
    hub._sso_cache.pop(uid)
    hub.tokens(uid)
    after = hub.store.get(uid)["sso"]
    crm = hub.store.get(uid)["crm"]
    assert after["refresh_token"] != before and crm["enabled"] is True and crm["via"] == "sso"
    assert hub.store.replace_if("yoq-odam", "sso", before, expired=True) is False
    assert hub.store.replace_if(uid, "sso", "boshqa-token", expired=True) is False
    assert hub.store.get(uid)["sso"]["expired"] is False


def test_mobil_qaytish_sahifasi_ilovani_ochadi_va_xatoni_ham_aytadi(client, net, monkeypatch):
    """Mobil qaytish 303 emas, kichik sahifa: Android Chrome ilovani bosishsiz yo'naltirishdan
    ochmasligi mumkin. Sahifa ilovani darhol ochishga urinadi va tugma qoldiradi; keshlanmaydi,
    Referer yubormaydi. Odam Keycloak'da "bekor" desa ham sahifa ilovaga sababni olib boradi."""
    import urllib.parse

    from app.services.oidc import pkce_pair

    monkeypatch.setattr(settings, "sso_mobile_redirect", "venera-rec://sso")
    _, challenge = pkce_pair()
    response = client.get("/api/v1/auth/sso/start", params={"return": "venera-rec://sso", "channel": "mobile",
                                                            "app_challenge": challenge}, follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(response.headers["location"]).query)["state"][0]
    page = client.get("/api/v1/auth/sso/callback", params={"state": state, "error": "access_denied"},
                      follow_redirects=False)
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "script-src 'nonce-" in page.headers["content-security-policy"]
    assert 'href="venera-rec://sso?sso_error=denied"' in page.text
    assert "Barno AI ilovasini ochish" in page.text

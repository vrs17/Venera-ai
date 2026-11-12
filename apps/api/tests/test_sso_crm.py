"""CRM ulanishi SSO sessiyasidan (`services/integrations/crm_sso.py`, 2026-11-12).

Kirgan odamning Keycloak sessiyasi (bizning client'ga berilgan tokenlar) CRM
ulanishiga aylanadi - "+" menyusiga kirmasdan. Keycloak ham, CRM ham soxta
(`tests/sso_fake.py`): Keycloak HAQIQIY imzoli token beradi, CRM esa
`GET /api/auth/me` da tokenni "qabul qiladi" yoki rad etadi.

Tekshiriladigan va'dalar:
  * CRM qabul qilsa - ulanadi; rad etsa yoki javob bermasa - mavjud ulanishga
    TEGILMAYDI va kirish baribir ishlaydi;
  * access tokenni CRM emas, KEYCLOAK yangilaydi; sessiya o'lsa holat "expired";
  * uzish sessiyani Keycloak'da bekor qiladi; SSO -> SSO almashtirishda eskisi
    bekor QILINMAYDI (bitta offline sessiyani bo'lishishi mumkin);
  * token API javobiga tushmaydi.
"""

from __future__ import annotations

import urllib.error

import pytest

from app.api.v1 import connectors as connectors_api
from app.core.config import settings
from app.services.integrations.connectors import (
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
)
from app.services.integrations.crm_sso import CrmSso
from app.services.oidc import from_settings as oidc_from_settings
from tests.sso_fake import (  # noqa: F401 - fiksturalar
    CLIENT_ID,
    LOGOUT_URL,
    TOKEN_URL,
    USERNAME,
    net,
    sso_login,
)
from tests.test_connectors import CRM, HRM, IDP, PASSWORD, STATUS_FIELDS

ME_URL = f"{CRM}/api/auth/me"
CRM_REFRESH_URL = f"{CRM}/api/auth/refresh"
CRM_LOGOUT_URL = f"{CRM}/api/auth/logout"


@pytest.fixture
def hub(tmp_path, net, monkeypatch):
    """Ulanishlar markazi SSO manbasi bilan - prod'dagi modul `hub` i kabi."""
    monkeypatch.setattr(settings, "sso_crm_connect", True)
    built = ConnectorHub(
        ConnectorStore(tmp_path / "connectors" / "tokens.json"),
        HrmAuth(HRM),
        CrmUserAuth(IDP, "crm-client", "sir", CRM),
        sso=CrmSso(oidc_from_settings, lambda: CRM),
    )
    monkeypatch.setattr(connectors_api, "hub", built)
    return built


def _uid(body: dict) -> str:
    return str(body["user"]["actorId"])


def _crm(hub: ConnectorHub, uid: str) -> dict:
    return next(item for item in hub.status(uid) if item["id"] == "crm")


def _auth(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['token']}"}


def _refresh_calls(net) -> list[dict]:
    return [body for body in net.token_calls if body.get("grant_type") == "refresh_token"]


# --- kirishda ulanish ------------------------------------------------------------


def test_kirishda_crm_ulanadi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)

    status = _crm(hub, uid)
    assert status["state"] == "connected"
    assert status["login"] == USERNAME
    assert status["enabled"] is True
    # CRM dan AYNAN shu odamning Keycloak access tokeni bilan so'ralgan.
    assert len(net.me_calls) == 1 and net.me_calls[0].startswith("Bearer ey")
    token = net.me_calls[0].removeprefix("Bearer ")
    # Chat shu tokenni oladi - kesh, Keycloak'ka qayta borilmaydi.
    assert hub.tokens(uid) == {"crm": token}
    assert _refresh_calls(net) == []
    # Saqlangan yozuv SSO sessiyasi deb belgilangan.
    entry = hub.store.get(uid)["crm"]
    assert entry["via"] == "sso" and entry["refresh_token"].startswith("refresh-")


def test_offline_access_soraladi(client, hub, net):
    sso_login(client, net)
    assert net.last_authorize["scope"].split() == ["openid", "profile", "email", "offline_access"]


def test_ochirilgan_bolsa_crm_ga_borilmaydi(client, hub, net, monkeypatch):
    monkeypatch.setattr(settings, "sso_crm_connect", False)
    body = sso_login(client, net)
    assert net.last_authorize["scope"] == "openid profile email"
    assert net.me_calls == []
    assert _crm(hub, _uid(body))["state"] == "disconnected"


def test_crm_sozlanmagan_bolsa_ulanmaydi(client, net, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sso_crm_connect", True)
    built = ConnectorHub(ConnectorStore(tmp_path / "c" / "tokens.json"), HrmAuth(""),
                         CrmUserAuth("", "", "", ""), sso=CrmSso(oidc_from_settings, lambda: ""))
    monkeypatch.setattr(connectors_api, "hub", built)
    body = sso_login(client, net)
    assert net.me_calls == []
    assert _crm(built, _uid(body))["state"] == "disconnected"


def test_refresh_token_bolmasa_ulanmaydi(client, hub, net, monkeypatch):
    original = net._tokens

    def without_refresh(*, nonce: str) -> dict:
        payload = original(nonce=nonce)
        payload.pop("refresh_token")
        return payload

    monkeypatch.setattr(net, "_tokens", without_refresh)
    body = sso_login(client, net)
    assert net.me_calls == []
    assert _crm(hub, _uid(body))["state"] == "disconnected"


# --- CRM rad etsa yoki javob bermasa ------------------------------------------------


def test_crm_rad_etsa_ulanmaydi_kirish_ishlaydi(client, hub, net, caplog):
    net.crm_accepts = False
    with caplog.at_level("WARNING"):
        body = sso_login(client, net)
    assert body["token"] and body["user"]["actorId"]
    assert _crm(hub, _uid(body))["state"] == "disconnected"
    assert hub.tokens(_uid(body)) == {}
    # Jurnalda sabab uchun yetarli ma'lumot bor, token esa yo'q.
    text = caplog.text
    assert "RAD ETDI" in text and f"azp={CLIENT_ID}" in text and "crm-client" in text
    assert net.me_calls[0].removeprefix("Bearer ") not in text


def test_crm_rad_etsa_qolda_ulangan_crm_qoladi(client, hub, net):
    body = sso_login(client, net)          # 1-kirish: SSO sessiyasi ulandi
    uid = _uid(body)
    hub.connect(uid, "crm", USERNAME, PASSWORD)   # odam "+" menyusidan qo'lda uladi
    manual = dict(hub.store.get(uid)["crm"])
    assert "via" not in manual

    net.crm_accepts = False
    sso_login(client, net)                 # 2-kirish: CRM endi rad etadi
    assert hub.store.get(uid)["crm"] == manual
    assert _crm(hub, uid)["state"] == "connected"
    assert CRM_LOGOUT_URL not in net.urls()[-3:]


def test_crm_javob_bermasa_mavjud_ulanishga_tegilmaydi(client, hub, net):
    net.crm_accepts = None                 # 503 - aniqlab bo'lmaydi
    body = sso_login(client, net)
    uid = _uid(body)
    assert _crm(hub, uid)["state"] == "disconnected"

    hub.connect(uid, "crm", USERNAME, PASSWORD)
    manual = dict(hub.store.get(uid)["crm"])
    sso_login(client, net)
    assert hub.store.get(uid)["crm"] == manual


def test_crm_ga_ulanib_bolmasa_kirish_ishlaydi(client, hub, net, monkeypatch):
    original = net.__class__.__call__

    def flaky(self, request, timeout=None):
        if request.full_url == ME_URL:
            raise urllib.error.URLError("connection refused")
        return original(self, request, timeout)

    monkeypatch.setattr(net.__class__, "__call__", flaky)
    body = sso_login(client, net)
    assert body["token"]
    assert _crm(hub, _uid(body))["state"] == "disconnected"


def test_ulanishdagi_kutilmagan_xato_kirishni_toxtatmaydi(client, hub, net, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk to'la")

    monkeypatch.setattr(hub, "adopt_crm", boom)
    body = sso_login(client, net)
    assert body["token"] and body["user"]["actorId"]


# --- yangilash: Keycloak, CRM emas ------------------------------------------------------


def test_access_token_keycloakda_yangilanadi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    first = hub.tokens(uid)["crm"]
    stored = hub.store.get(uid)["crm"]["refresh_token"]

    hub._crm_cache.pop(uid)                # kesh eskirdi deb faraz qilamiz
    second = hub.tokens(uid)["crm"]

    calls = _refresh_calls(net)
    assert len(calls) == 1
    assert calls[0]["refresh_token"] == stored and calls[0]["client_id"] == CLIENT_ID
    # CRM ning o'z refresh manziliga BORILMAGAN: u bizning client tokenini yangilay olmaydi.
    assert CRM_REFRESH_URL not in net.urls()
    assert second.startswith("ey") and second != first
    # Rotatsiya: Keycloak yangi refresh_token berdi - o'sha saqlandi, belgi joyida.
    entry = hub.store.get(uid)["crm"]
    assert entry["refresh_token"] != stored and entry["via"] == "sso" and entry["expired"] is False


def test_sessiya_olgan_bolsa_holat_expired(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub._crm_cache.pop(uid)
    net.refresh_error = (400, {"error": "invalid_grant", "error_description": "Session not active"})

    assert hub.tokens(uid) == {}
    status = _crm(hub, uid)
    assert status["state"] == "expired" and status["login"] == USERNAME
    assert hub.store.get(uid)["crm"]["refresh_token"] == ""


def test_keycloak_vaqtincha_yiqilsa_ulanish_qoladi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub._crm_cache.pop(uid)
    net.refresh_error = (503, {"error": "temporarily_unavailable"})

    assert hub.tokens(uid) == {}             # bu savol CRM siz ketadi
    assert _crm(hub, uid)["state"] == "connected"
    net.refresh_error = None
    assert hub.tokens(uid)["crm"].startswith("ey")


# --- uzish va almashtirish --------------------------------------------------------------


def test_uzish_sessiyani_keycloakda_bekor_qiladi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    stored = hub.store.get(uid)["crm"]["refresh_token"]

    response = client.delete("/api/v1/connectors/crm", headers=_auth(body))
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "disconnected"
    assert net.revoked == [stored]
    logout_body = next(b for url, b in net.calls if url == LOGOUT_URL)
    assert logout_body["client_id"] == CLIENT_ID and logout_body["client_secret"]
    assert CRM_LOGOUT_URL not in net.urls()
    assert hub.tokens(uid) == {}


def test_qayta_kirish_eski_sso_sessiyasini_bekor_qilmaydi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    old = hub.store.get(uid)["crm"]["refresh_token"]

    sso_login(client, net)
    new = hub.store.get(uid)["crm"]["refresh_token"]
    assert new != old
    # Ikkalasi bitta offline sessiyani bo'lishishi mumkin - eskisini bekor qilish
    # yangisini ham o'ldirardi.
    assert net.revoked == []
    assert _crm(hub, uid)["state"] == "connected"


def test_sso_sessiyasi_qolda_ulangan_crm_ni_almashtiradi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub.connect(uid, "crm", USERNAME, PASSWORD)          # qo'lda (crm-client sessiyasi)
    manual_refresh = hub.store.get(uid)["crm"]["refresh_token"]

    sso_login(client, net)                               # CRM qabul qiladi -> SSO sessiyasi
    entry = hub.store.get(uid)["crm"]
    assert entry["via"] == "sso" and entry["refresh_token"] != manual_refresh
    # Eski qo'lda ulangan kredensial CRM da bekor qilindi (to'planib qolmasin).
    assert (CRM_LOGOUT_URL, {"refresh_token": manual_refresh}) in net.calls


def test_qolda_ulash_sso_belgisini_olib_tashlaydi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub.connect(uid, "crm", USERNAME, PASSWORD)
    assert "via" not in hub.store.get(uid)["crm"]
    hub._crm_cache.pop(uid)
    hub.tokens(uid)
    # Endi yangilash yana CRM orqali.
    assert CRM_REFRESH_URL in net.urls()
    assert _refresh_calls(net) == []


def test_kalit_ochirilgan_bolsa_qayta_kirish_yoqmaydi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub.set_enabled(uid, "crm", False)
    sso_login(client, net)
    assert _crm(hub, uid)["enabled"] is False
    assert hub.tokens(uid) == {}


# --- API javobi ----------------------------------------------------------------------------


def test_api_javobida_token_yoq(client, hub, net):
    body = sso_login(client, net)
    response = client.get("/api/v1/connectors", headers=_auth(body))
    assert response.status_code == 200, response.text
    items = response.json()["connectors"]
    crm = next(item for item in items if item["id"] == "crm")
    assert set(crm) == STATUS_FIELDS
    assert crm["state"] == "connected" and crm["login"] == USERNAME
    raw = response.text
    assert hub.store.get(_uid(body))["crm"]["refresh_token"] not in raw
    assert net.me_calls[0].removeprefix("Bearer ") not in raw


def test_sso_manbasi_yoq_markazda_sso_yozuvi_token_bermaydi(tmp_path, net):
    """SSO o'chirilgan o'rnatmada eski `via: sso` yozuvi qolsa - token yo'q, xato ham yo'q."""
    plain = ConnectorHub(ConnectorStore(tmp_path / "p" / "tokens.json"), HrmAuth(HRM),
                         CrmUserAuth(IDP, "crm-client", "sir", CRM))
    plain.store.set("7", "crm", {"login": USERNAME, "refresh_token": "refresh-x", "via": "sso",
                                 "expired": False, "enabled": True})
    assert plain.tokens("7") == {}
    assert CRM_REFRESH_URL not in net.urls() and TOKEN_URL not in net.urls()
    plain.disconnect("7", "crm")            # bekor qilishga manba yo'q - jim o'tadi
    assert net.revoked == [] and CRM_LOGOUT_URL not in net.urls()

"""CRM ulanishi SSO sessiyasidan (`services/integrations/crm_sso.py`, 2026-11-12).

Kirgan odamning Keycloak sessiyasi (bizning client'ga berilgan tokenlar) CRM
ulanishiga aylanadi - bu CRM ga ulanishning yagona yo'li. Keycloak ham, CRM ham
soxta (`tests/sso_fake.py`): Keycloak HAQIQIY imzoli token beradi, CRM esa
`GET /api/auth/me` da tokenni "qabul qiladi" yoki rad etadi.

Tekshiriladigan va'dalar:
  * CRM qabul qilsa - ulanadi; rad etsa yoki javob bermasa - mavjud (eski, qo'lda
    ulangan) ulanishga TEGILMAYDI va kirish baribir ishlaydi;
  * access tokenni CRM emas, KEYCLOAK yangilaydi; sessiya o'lsa holat "expired";
  * CRM HAR DOIM YOQIQ: kalit yo'q, eski `enabled: false` tokenni to'xtatmaydi va
    qayta kirishdan keyin yozuvda ham qolmaydi;
  * odam CRM ni KO'RMAYDI va boshqarmaydi: `GET /connectors` da CRM qatori yo'q,
    `crm` uchun ulash / kalit / uzish - 404. Uzish - admin panelda, va u
    sessiyani Keycloak'da bekor qiladi; SSO -> SSO almashtirishda eskisi bekor
    QILINMAYDI (bitta offline sessiyani bo'lishishi mumkin);
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
    REVOKE_URL,
    TOKEN_URL,
    USERNAME,
    net,
    sso_login,
)
from tests.test_connectors import CRM, HRM, IDP, STATUS_FIELDS, legacy_crm

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
    """CRM qatori - admin panel ko'radigan holat (odamning ro'yxatida u yo'q)."""
    return next(item for item in hub.status(uid) if item["id"] == "crm")


def _new_person(client, net) -> str:
    """Shaxs yaratiladi (birinchi kirish), lekin CRM ulanmaydi - CRM sessiyani rad etdi."""
    net.crm_accepts = False
    uid = _uid(sso_login(client, net))
    net.crm_accepts = True
    return uid


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
    # Saqlangan yozuv SSO sessiyasi deb belgilangan; sessiyaning o'zi umumiy `sso` yozuvida.
    entry = hub.store.get(uid)["crm"]
    assert entry["via"] == "sso" and "refresh_token" not in entry
    assert hub.store.get(uid)["sso"]["refresh_token"].startswith("refresh-")


def test_offline_access_soraladi(client, hub, net):
    sso_login(client, net)
    assert net.last_authorize["scope"].split() == ["openid", "profile", "email", "offline_access"]


def test_ochirilgan_bolsa_crm_ga_borilmaydi(client, hub, net, monkeypatch):
    monkeypatch.setattr(settings, "sso_crm_connect", False)
    monkeypatch.setattr(settings, "sso_hrm_connect", False)        # ikkalasi o'chiq - offline ham kerak emas
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


def test_crm_rad_etsa_eski_ulanish_qoladi(client, hub, net):
    uid = _new_person(client, net)
    legacy_crm(hub, uid, USERNAME)         # odamning eski, qo'lda ulangan CRM i
    manual = dict(hub.store.get(uid)["crm"])
    assert "via" not in manual

    net.crm_accepts = False
    sso_login(client, net)                 # kirish: CRM sessiyani rad etadi
    assert hub.store.get(uid)["crm"] == manual
    assert _crm(hub, uid)["state"] == "connected"
    assert CRM_LOGOUT_URL not in net.urls()


def test_crm_javob_bermasa_mavjud_ulanishga_tegilmaydi(client, hub, net):
    net.crm_accepts = None                 # 503 - aniqlab bo'lmaydi
    body = sso_login(client, net)
    uid = _uid(body)
    assert _crm(hub, uid)["state"] == "disconnected"

    legacy_crm(hub, uid, USERNAME)
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

    monkeypatch.setattr(hub, "adopt_sso", boom)
    body = sso_login(client, net)
    assert body["token"] and body["user"]["actorId"]


# --- yangilash: Keycloak, CRM emas ------------------------------------------------------


def test_access_token_keycloakda_yangilanadi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    first = hub.tokens(uid)["crm"]
    stored = hub.store.get(uid)["sso"]["refresh_token"]

    hub._sso_cache.pop(uid)                # kesh eskirdi deb faraz qilamiz
    second = hub.tokens(uid)["crm"]

    calls = _refresh_calls(net)
    assert len(calls) == 1
    assert calls[0]["refresh_token"] == stored and calls[0]["client_id"] == CLIENT_ID
    # CRM ning o'z refresh manziliga BORILMAGAN: u bizning client tokenini yangilay olmaydi.
    assert CRM_REFRESH_URL not in net.urls()
    assert second.startswith("ey") and second != first
    # Rotatsiya: Keycloak yangi refresh_token berdi - o'sha saqlandi, belgi joyida.
    session = hub.store.get(uid)["sso"]
    assert session["refresh_token"] != stored and session["expired"] is False
    assert hub.store.get(uid)["crm"]["via"] == "sso"


def test_sessiya_olgan_bolsa_holat_expired(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub._sso_cache.pop(uid)
    net.refresh_error = (400, {"error": "invalid_grant", "error_description": "Session not active"})

    assert hub.tokens(uid) == {}
    status = _crm(hub, uid)
    assert status["state"] == "expired" and status["login"] == USERNAME
    assert hub.store.get(uid)["sso"]["refresh_token"] == ""


def test_keycloak_vaqtincha_yiqilsa_ulanish_qoladi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub._sso_cache.pop(uid)
    net.refresh_error = (503, {"error": "temporarily_unavailable"})

    assert hub.tokens(uid) == {}             # bu savol CRM siz ketadi
    assert _crm(hub, uid)["state"] == "connected"
    net.refresh_error = None
    assert hub.tokens(uid)["crm"].startswith("ey")


# --- uzish va almashtirish --------------------------------------------------------------


def test_uzish_sessiyani_keycloakda_bekor_qiladi(client, hub, net):
    """Uzish faqat admin panelda (`DELETE /admin/users/{id}/connectors/crm`)."""
    body = sso_login(client, net, roles=["admin"])
    uid = _uid(body)
    stored = hub.store.get(uid)["sso"]["refresh_token"]

    response = client.delete(f"/api/v1/admin/users/{uid}/connectors/crm", headers=_auth(body))
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "disconnected"
    assert net.revoked == [stored]
    revoke_body = next(b for url, b in net.calls if url == REVOKE_URL)
    assert revoke_body["client_id"] == CLIENT_ID and revoke_body["client_secret"]
    # Butun Keycloak sessiyasi YOPILMAGAN: odam shu brauzerdagi CRM dan chiqib ketmaydi.
    assert LOGOUT_URL not in net.urls()
    assert CRM_LOGOUT_URL not in net.urls()
    assert hub.tokens(uid) == {}
    assert "sso" not in hub.store.get(uid)             # oxirgi SSO ulanishi edi - sessiya ham ketdi


def test_qayta_kirish_eski_sso_sessiyasini_bekor_qilmaydi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    old = hub.store.get(uid)["sso"]["refresh_token"]

    sso_login(client, net)
    new = hub.store.get(uid)["sso"]["refresh_token"]
    assert new != old
    # Ikkalasi bitta offline sessiyani bo'lishishi mumkin - eskisini bekor qilish
    # yangisini ham o'ldirardi.
    assert net.revoked == []
    assert _crm(hub, uid)["state"] == "connected"


def test_sso_sessiyasi_eski_qolda_ulangan_crm_ni_almashtiradi(client, hub, net):
    uid = _new_person(client, net)
    legacy_crm(hub, uid, USERNAME)                       # eski (crm-client sessiyasi) ...
    hub.store.set(uid, "crm", {**hub.store.get(uid)["crm"], "enabled": False})   # ... va o'chirilgan
    manual_refresh = hub.store.get(uid)["crm"]["refresh_token"]

    sso_login(client, net)                               # CRM qabul qiladi -> SSO sessiyasi
    entry = hub.store.get(uid)["crm"]
    assert entry["via"] == "sso" and hub.store.get(uid)["sso"]["refresh_token"] != manual_refresh
    assert entry["enabled"] is True, "eski kalit yangi ulanishga o'tmaydi"
    # Eski qo'lda ulangan kredensial CRM da bekor qilindi (to'planib qolmasin).
    assert (CRM_LOGOUT_URL, {"refresh_token": manual_refresh}) in net.calls


def test_eski_yozuvni_crm_yangilaydi_keycloak_emas(client, hub, net):
    """SSO manbasi bor markazda ham `via` siz (eski) yozuv CRM ning o'zida yangilanadi."""
    uid = _new_person(client, net)
    legacy_crm(hub, uid, USERNAME)
    hub._crm_cache.pop(uid)
    assert hub.tokens(uid)["crm"].startswith("access-")
    assert CRM_REFRESH_URL in net.urls()
    assert _refresh_calls(net) == []


def test_ochirilgan_crm_baribir_ishlaydi_va_qayta_kirishda_yoqiladi(client, hub, net):
    """CRM har doim yoqiq. Eski kod yozgan `enabled: false` (odam bir paytlar kalitni
    o'chirgan) tokenni to'xtatmaydi; qayta kirishdan keyin yozuvda ham qolmaydi."""
    body = sso_login(client, net)
    uid = _uid(body)
    hub.store.set(uid, "crm", {**hub.store.get(uid)["crm"], "enabled": False})

    assert hub.tokens(uid)["crm"].startswith("ey"), "qayta kirmasdan ham ishlaydi"
    assert _crm(hub, uid)["enabled"] is True

    sso_login(client, net)
    entry = hub.store.get(uid)["crm"]
    assert entry["enabled"] is True and entry["via"] == "sso"
    assert _crm(hub, uid)["enabled"] is True
    assert hub.tokens(uid)["crm"].startswith("ey")


# --- API javobi ----------------------------------------------------------------------------


def test_api_royxatida_crm_yoq_va_token_yoq(client, hub, net):
    """CRM ulangan, lekin odamga ko'rsatilmaydi: ro'yxatda faqat HRM qatori."""
    body = sso_login(client, net)
    assert _crm(hub, _uid(body))["state"] == "connected"
    response = client.get("/api/v1/connectors", headers=_auth(body))
    assert response.status_code == 200, response.text
    items = response.json()["connectors"]
    assert [item["id"] for item in items] == ["hrm"]
    assert set(items[0]) == STATUS_FIELDS
    raw = response.text
    assert "crm" not in raw.lower() and USERNAME not in raw
    assert hub.store.get(_uid(body))["sso"]["refresh_token"] not in raw
    assert net.me_calls[0].removeprefix("Bearer ") not in raw


def test_api_odam_crm_ni_boshqara_olmaydi(client, hub, net):
    """`crm` uchun ulash / kalit / uzish - 404: sessiya joyida, Keycloak'da hech narsa
    bekor qilinmagan, token berilaveradi."""
    body = sso_login(client, net)
    uid = _uid(body)
    before = hub.store.get(uid)["crm"]
    calls_before = len(net.calls)

    responses = [
        client.post("/api/v1/connectors/crm/connect", headers=_auth(body),
                    json={"username": USERNAME, "password": "parol"}),
        client.patch("/api/v1/connectors/crm", headers=_auth(body), json={"enabled": False}),
        client.delete("/api/v1/connectors/crm", headers=_auth(body)),
    ]
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert hub.store.get(uid)["crm"] == before
    assert net.revoked == [] and len(net.calls) == calls_before
    assert _crm(hub, uid)["enabled"] is True
    assert hub.tokens(uid)["crm"].startswith("ey")


def test_health_crm_ulanishi_sso_yolidan(client, auth, hub, net, monkeypatch):
    """`/api/health/detail` -> `connectors.crm`: SSO kirishida CRM ulanishi ochila
    oladimi (SSO + `CRM_BASE_URL` + `SSO_CRM_CONNECT`), eski `crm-client` sozlamasi emas."""
    body = client.get("/api/health/detail", headers=auth).json()
    assert body["connectors"]["crm"] is True
    assert not [w for w in body["warnings"] if "CRM ulanishi" in w]

    monkeypatch.setattr(settings, "sso_crm_connect", False)
    body = client.get("/api/health/detail", headers=auth).json()
    assert body["connectors"]["crm"] is False
    assert [w for w in body["warnings"] if "CRM ulanishi" in w and "SSO_CRM_CONNECT" in w]


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

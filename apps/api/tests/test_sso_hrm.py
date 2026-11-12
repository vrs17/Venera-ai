"""HRM ulanishi SSO sessiyasidan (`services/integrations/crm_sso.py`, 2026-11-12, ega so'rovi).

HRM jamoasi kod bo'yicha ko'rsatdi: HRM Keycloak `brb-realm` tokenini Bearer sifatida
tekshiradi. Shuning uchun kirgan odamning sessiyasi HRM ga ham beriladi - CRM bilan
BITTA sessiya, BITTA token, bitta yangilash (`sso` yozuvi). Keycloak, CRM va HRM soxta
(`tests/sso_fake.py`): HRM `GET /api/account` da tokenni qabul qiladi yoki sabab bilan
rad etadi.

Va'dalar:
  * HRM qabul qilsa - kirishda o'zi ulanadi, eski qo'lda ulangan HRM almashtiriladi;
    rad etsa yoki javob bermasa - mavjud HRM ga TEGILMAYDI,
    jurnalda sabab (HRM'ning `error_description` i, tokenning `aud`/`azp` i), token yo'q;
  * CRM rad etsa ham HRM ulanadi (va aksincha) - har tizim o'zi hal qiladi;
  * ikkala tizim BIR XIL tokenni oladi, yangilash bitta; sessiya o'lsa ikkalasi "expired";
  * bitta tizim uzilsa sessiya qoladi, oxirgisi uzilsa Keycloak'da bekor qilinadi;
  * 2026-11-12 gacha yozilgan fayl (sessiya CRM yozuvi ichida) o'zi yangi shaklga o'tadi.
"""

from __future__ import annotations

import json

import pytest

from app import main as main_module
from app.api.v1 import connectors as connectors_api
from app.core.config import settings
from app.services.integrations.connectors import ConnectorHub, ConnectorStore, CrmUserAuth, HrmAuth
from app.services.integrations.crm_sso import CrmSso, HrmSso, SsoSession
from app.services.oidc import from_settings as oidc_from_settings
from tests.sso_fake import REVOKE_URL, USERNAME, net, sso_login  # noqa: F401 - fikstura
from tests.test_connectors import CRM, HRM, IDP, STATUS_FIELDS, legacy_hrm


@pytest.fixture
def hub(tmp_path, net, monkeypatch):
    """Prod'dagi modul `hub` i kabi: CRM tekshiruvi, umumiy sessiya, HRM tekshiruvi."""
    monkeypatch.setattr(settings, "sso_crm_connect", True)
    monkeypatch.setattr(settings, "sso_hrm_connect", True)
    built = ConnectorHub(
        ConnectorStore(tmp_path / "connectors" / "tokens.json"),
        HrmAuth(HRM),
        CrmUserAuth(IDP, "crm-client", "sir", CRM),
        sso=CrmSso(oidc_from_settings, lambda: CRM),
        session=SsoSession(oidc_from_settings),
        hrm_check=HrmSso(lambda: HRM),
    )
    monkeypatch.setattr(connectors_api, "hub", built)
    return built


def _uid(body: dict) -> str:
    return str(body["user"]["actorId"])


def _auth(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['token']}"}


def _state(hub: ConnectorHub, uid: str, platform: str) -> dict:
    return next(item for item in hub.status(uid) if item["id"] == platform)


def _refresh_calls(net) -> list[dict]:
    return [body for body in net.token_calls if body.get("grant_type") == "refresh_token"]


def _new_person(client, net) -> str:
    """Shaxs yaratiladi, lekin hech narsa ulanmaydi (ikkala tizim ham rad etdi)."""
    net.crm_accepts, net.hrm_accepts = False, False
    uid = _uid(sso_login(client, net))
    net.crm_accepts, net.hrm_accepts = True, True
    return uid


# --- kirishda ulanish ------------------------------------------------------------


def test_kirishda_hrm_va_crm_bitta_sessiyadan_ulanadi(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)

    hrm = _state(hub, uid, "hrm")
    assert (hrm["state"], hrm["login"], hrm["via"], hrm["expiresAt"]) == ("connected", USERNAME, "sso", None)
    assert _state(hub, uid, "crm")["state"] == "connected"
    # HRM dan AYNAN shu odamning access tokeni bilan so'ralgan; CRM bilan bir xil token.
    token = net.account_calls[0].removeprefix("Bearer ")
    assert token.startswith("ey") and net.me_calls[0] == net.account_calls[0]
    assert hub.tokens(uid) == {"hrm": token, "crm": token}
    assert _refresh_calls(net) == []                         # kesh: Keycloak'ka qayta borilmaydi

    stored = hub.store.get(uid)
    assert "token" not in stored["hrm"] and "refresh_token" not in stored["hrm"]
    assert stored["sso"]["refresh_token"].startswith("refresh-")

    response = client.get("/api/v1/connectors", headers=_auth(body))
    assert response.status_code == 200, response.text
    [item] = response.json()["connectors"]
    assert set(item) == STATUS_FIELDS and (item["state"], item["via"]) == ("connected", "sso")
    assert token not in response.text and stored["sso"]["refresh_token"] not in response.text


def test_qolda_ulangan_eski_hrm_almashtiriladi(client, hub, net):
    uid = _new_person(client, net)
    legacy_hrm(hub, uid, USERNAME)
    assert _state(hub, uid, "hrm")["via"] is None

    sso_login(client, net)
    entry = hub.store.get(uid)["hrm"]
    assert entry["via"] == "sso" and "token" not in entry


def test_hrm_rad_etsa_qolda_ulangan_hrm_qoladi_sabab_jurnalda(client, hub, net, caplog):
    uid = _new_person(client, net)
    legacy_hrm(hub, uid, USERNAME)
    manual = dict(hub.store.get(uid)["hrm"])

    net.hrm_accepts = False
    with caplog.at_level("WARNING"):
        sso_login(client, net)
    assert hub.store.get(uid)["hrm"] == manual                # tegilmadi
    assert _state(hub, uid, "crm")["state"] == "connected"    # CRM o'zi hal qildi
    text = caplog.text
    assert "HRM sessiyani RAD ETDI" in text and "Invalid audience" in text and "aud=" in text
    assert net.account_calls[-1].removeprefix("Bearer ") not in text


def test_hrm_javob_bermasa_ulanmaydi(client, hub, net, caplog):
    net.hrm_accepts = None                                   # 500 - masalan xodim topilmadi
    with caplog.at_level("WARNING"):
        body = sso_login(client, net)
    uid = _uid(body)
    assert _state(hub, uid, "hrm")["state"] == "disconnected"
    assert _state(hub, uid, "crm")["state"] == "connected"
    assert "HRM sessiyani tekshira olmadi" in caplog.text and "HTTP 500" in caplog.text


def test_crm_rad_etsa_ham_hrm_ulanadi(client, hub, net):
    net.crm_accepts = False
    body = sso_login(client, net)
    uid = _uid(body)
    assert _state(hub, uid, "crm")["state"] == "disconnected"
    assert _state(hub, uid, "hrm")["state"] == "connected"
    assert list(hub.tokens(uid)) == ["hrm"]


def test_hrm_ochirilgan_bolsa_tekshirilmaydi(client, hub, net, monkeypatch):
    monkeypatch.setattr(settings, "sso_hrm_connect", False)
    body = sso_login(client, net)
    assert net.account_calls == []
    assert _state(hub, _uid(body), "hrm")["state"] == "disconnected"
    assert "offline_access" in net.last_authorize["scope"].split()     # CRM uchun hali kerak


def test_faqat_hrm_yoqiq_bolsa_ham_offline_soraladi(client, hub, net, monkeypatch):
    monkeypatch.setattr(settings, "sso_crm_connect", False)
    body = sso_login(client, net)
    assert "offline_access" in net.last_authorize["scope"].split()
    assert net.me_calls == [] and _state(hub, _uid(body), "hrm")["state"] == "connected"


def test_salomatlik_hrm_sso_tayyor(hub, monkeypatch):
    assert main_module._hrm_sso_ready(hub) is True
    monkeypatch.setattr(settings, "sso_hrm_connect", False)
    assert main_module._hrm_sso_ready(hub) is False


# --- bitta sessiya: yangilash, o'lim, uzish ----------------------------------------------


def test_bitta_yangilash_ikki_tizimga(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    first = hub.tokens(uid)["hrm"]
    stored = hub.store.get(uid)["sso"]["refresh_token"]

    hub._sso_cache.pop(uid)
    tokens = hub.tokens(uid)
    [call] = _refresh_calls(net)                             # ikki tizim - BITTA yangilash
    assert call["refresh_token"] == stored
    assert tokens["hrm"] == tokens["crm"] != first
    assert hub.store.get(uid)["sso"]["refresh_token"] != stored    # rotatsiya saqlandi


def test_sessiya_olsa_ikkalasi_expired(client, hub, net):
    body = sso_login(client, net)
    uid = _uid(body)
    hub._sso_cache.pop(uid)
    net.refresh_error = (400, {"error": "invalid_grant", "error_description": "Session not active"})

    assert hub.tokens(uid) == {}
    assert _state(hub, uid, "hrm")["state"] == "expired" and _state(hub, uid, "crm")["state"] == "expired"
    items = client.get("/api/v1/connectors", headers=_auth(body)).json()["connectors"]
    assert items[0]["state"] == "expired" and items[0]["login"] == USERNAME


def test_crm_uzilsa_hrm_qoladi_oxirgisi_uzilsa_sessiya_bekor(client, hub, net):
    body = sso_login(client, net, roles=["admin"])
    uid = _uid(body)
    stored = hub.store.get(uid)["sso"]["refresh_token"]

    response = client.delete(f"/api/v1/admin/users/{uid}/connectors/crm", headers=_auth(body))
    assert response.status_code == 200, response.text
    assert net.revoked == [] and list(hub.tokens(uid)) == ["hrm"]   # sessiya HRM uchun qoldi

    gone = client.delete("/api/v1/connectors/hrm", headers=_auth(body))
    assert gone.status_code == 200 and gone.json()["state"] == "disconnected"
    assert net.revoked == [stored] and "sso" not in hub.store.get(uid)
    assert hub.tokens(uid) == {}
    assert REVOKE_URL in [url for url, _ in net.calls]


# --- eski fayl --------------------------------------------------------------------------


def test_eski_fayl_yangi_shaklga_otadi(tmp_path, net):
    """2026-11-12 gacha: sessiya CRM yozuvining ichida edi. O'qilganda `sso` ga ko'chadi,
    keyingi yozuv diskka yangi shaklda yozadi; CRM ishlayveradi."""
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"7": {
        "crm": {"login": "u", "refresh_token": "r-1", "expired": False, "enabled": True,
                "connected_at": 1.0, "via": "sso"},
        "hrm": {"login": "u", "token": "t", "expires_at": 9e9, "enabled": True, "connected_at": 1.0},
    }}))
    store = ConnectorStore(path)
    data = store.get("7")
    assert data["sso"] == {"login": "u", "refresh_token": "r-1", "expired": False, "connected_at": 1.0}
    assert data["crm"] == {"login": "u", "enabled": True, "connected_at": 1.0, "via": "sso"}
    assert data["hrm"]["token"] == "t"                       # qo'lda ulangan HRM - joyida

    hub = ConnectorHub(store, HrmAuth(HRM), CrmUserAuth(IDP, "crm-client", "sir", CRM),
                       sso=CrmSso(oidc_from_settings, lambda: CRM))
    assert next(s for s in hub.status("7") if s["id"] == "crm")["state"] == "connected"
    store.set("8", "hrm", {"login": "x", "token": "t2", "expires_at": 9e9})
    assert json.loads(path.read_text())["7"]["sso"]["refresh_token"] == "r-1"

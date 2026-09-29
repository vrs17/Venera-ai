"""SSO kirish: Keycloak + HRM/CRM avto-ulanish.

`api/v1/auth.py`, `services/sso.py`, `services/identities.py`. Keycloak, HRM
va CRM ning o'zi chaqirilmaydi - `test_connectors.py` dagi soxta tarmoq
(`urllib.request.urlopen`) ustiga Keycloak'ning haqiqiy shaklidagi
`access_token` (JWT, claim'lar bilan) qo'shiladi.
"""

from __future__ import annotations

import base64
import json
import stat
import time
import urllib.request

import pytest

from app.api.v1 import connectors as connectors_api
from app.core.config import settings
from app.services.identities import Directory, IdentityStore, SsoProfile
from app.services.integrations.connectors import (
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
)
from app.services.users import UserStore
from tests.conftest import ADMIN
from tests.test_connectors import CRM, HRM, IDP, PASSWORD, FakeNet, _Response

ISSUER = "https://idp.test/auth/realms/brb-realm"
SUB = "6f1a2b3c-0000-4000-8000-000000000001"
LOGIN = {"username": "y.mamajonov", "password": PASSWORD}


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def kc_jwt(claims: dict) -> str:
    return f"{_b64({'alg': 'RS256', 'kid': 'k1'})}.{_b64(claims)}.sig"


class FakeSso(FakeNet):
    """Keycloak javobidagi `access_token` - claim'li JWT (jonli shaklda)."""

    def __init__(self) -> None:
        super().__init__()
        self.sub = SUB
        self.email = "y.mamajonov@brb-tech.uz"
        self.name = "Test Xodim"
        self.iss = ISSUER
        self.roles = ["employee", "offline_access", "uma_authorization", "default-roles-brb-realm"]

    def __call__(self, request, timeout=None):
        reply = super().__call__(request, timeout)
        if request.full_url != IDP:
            return reply
        payload = json.loads(reply.read())
        now = int(time.time())
        # `preferred_username` - so'rovdagi login (Keycloak shunday qaytaradi).
        username = self.calls[-1][1].get("username", "")
        payload["access_token"] = kc_jwt({
            "iss": self.iss, "sub": self.sub, "aud": "account", "azp": "crm-client",
            "typ": "Bearer", "iat": now, "exp": now + 300,
            "preferred_username": username, "email": self.email, "name": self.name,
            "realm_access": {"roles": list(self.roles)},
            "resource_access": {"crm-client": {"roles": ["crm-user"]}},
        })
        return _Response(json.dumps(payload).encode())


@pytest.fixture
def net(monkeypatch):
    fake = FakeSso()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def hub(tmp_path, net, monkeypatch):
    """Sozlangan ulanishlar markazi - `auth._sso()` ham shundan Keycloak'ni oladi."""
    built = ConnectorHub(
        ConnectorStore(tmp_path / "connectors" / "tokens.json"),
        HrmAuth(HRM),
        CrmUserAuth(IDP, "crm-client", "sir", CRM),
    )
    monkeypatch.setattr(connectors_api, "hub", built)
    return built


def _rows(client, token: str) -> dict:
    body = client.get("/api/v1/connectors", headers={"Authorization": f"Bearer {token}"}).json()
    return {row["id"]: row for row in body["connectors"]}


# --- kirish ------------------------------------------------------------------


def test_sso_kirish_ikkala_ulanishni_ochadi(client, hub, net):
    response = client.post("/api/v1/auth/login", json=LOGIN)
    assert response.status_code == 200, response.text
    body = response.json()
    user = body["user"]
    assert user["email"] == "y.mamajonov@brb-tech.uz"
    assert user["fullName"] == "Test Xodim"
    assert user["actorType"] == "EMPLOYEE"
    # Texnik rollar (offline_access, default-roles-*) ko'rinmaydi; client roli ko'rinadi.
    assert user["roles"] == ["employee", "crm-user"]
    # users.yaml da 1 va 2 band - yangi odam 3.
    assert user["actorId"] == 3
    assert body["passwordChangeRequired"] is False

    # Avval Keycloak, keyin o'sha parol bilan HRM. Parol faqat shu ikki so'rovda.
    assert net.urls() == [IDP, f"{HRM}/api/authenticate"]
    assert net.calls[1][1] == {"username": "y.mamajonov", "password": PASSWORD}

    rows = _rows(client, body["token"])
    assert (rows["hrm"]["state"], rows["hrm"]["login"], rows["hrm"]["enabled"]) == ("connected", "y.mamajonov", True)
    assert (rows["crm"]["state"], rows["crm"]["login"], rows["crm"]["enabled"]) == ("connected", "y.mamajonov", True)
    # Chat ikkala tokenni oladi - CRM uchun qo'shimcha so'rovsiz (kesh).
    assert set(hub.tokens("3")) == {"hrm", "crm"}
    assert net.urls().count(f"{CRM}/api/auth/refresh") == 0
    # HRM paroli xotirada (10 soatdan keyin qayta kirish uchun), diskda emas.
    assert hub.has_password("3")
    assert PASSWORD not in hub.store.path.read_text()


def test_me_sso_tokeni_bilan(client, hub, net):
    body = client.post("/api/v1/auth/login", json=LOGIN).json()
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["actorId"] == body["user"]["actorId"]
    assert me.json()["email"] == "y.mamajonov@brb-tech.uz"


def test_eski_nom_email_ham_qabul_qilinadi(client, hub, net):
    """Eski build `{email, password}` yuboradi - kirish ishlayveradi."""
    response = client.post("/api/v1/auth/login", json={"email": "y.mamajonov", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["user"]["actorId"] == 3


def test_bosh_login_422(client, hub, net):
    assert client.post("/api/v1/auth/login", json={"username": "  ", "password": "x"}).status_code == 422


# --- actor_id ----------------------------------------------------------------


def test_eski_hisob_email_boyicha_actor_id_saqlanadi(client, hub, net):
    """users.yaml dagi admin Keycloak bilan kirsa - o'sha actor_id (1):
    suhbat tarixi, ulanishlar, Telegram ulanishi joyida qoladi."""
    net.email = ADMIN["email"]
    body = client.post("/api/v1/auth/login", json=LOGIN).json()
    assert body["user"]["actorId"] == 1
    assert set(hub.tokens("1")) == {"hrm", "crm"}


def test_eski_hisob_login_boyicha_ham_topiladi(client, hub, net):
    """Keycloak email bermasa: email'ning `@` gacha qismi login bilan bir xil hisob."""
    net.email = ""
    body = client.post("/api/v1/auth/login", json={"username": "demo", "password": PASSWORD}).json()
    assert body["user"]["actorId"] == 2
    # email majburiy maydon - Keycloak bermasa login turadi.
    assert body["user"]["email"] == "demo"


def test_actor_id_bir_marta_tanlanadi(client, hub, net):
    first = client.post("/api/v1/auth/login", json=LOGIN).json()["user"]["actorId"]
    second = client.post("/api/v1/auth/login", json=LOGIN).json()["user"]["actorId"]
    assert first == second == 3
    net.sub = "6f1a2b3c-0000-4000-8000-000000000002"
    net.email = "boshqa@brb-tech.uz"
    assert client.post("/api/v1/auth/login", json=LOGIN).json()["user"]["actorId"] == 4


def test_identities_fayli_600_va_sirsiz(client, hub, net):
    client.post("/api/v1/auth/login", json=LOGIN)
    path = settings.identities_file
    raw = path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert PASSWORD not in raw
    assert "refresh-" not in raw and "eyJ" not in raw, "TOKEN identities.json ga tushdi"
    assert SUB in raw


# --- ulanishlar ----------------------------------------------------------------


def test_hrm_yiqilsa_kirish_baribir_boladi(client, hub, net):
    net.hrm_shape = "none"  # HRM tokensiz javob beradi -> 502
    body = client.post("/api/v1/auth/login", json=LOGIN)
    assert body.status_code == 200
    rows = _rows(client, body.json()["token"])
    assert rows["hrm"]["state"] == "disconnected"
    assert rows["crm"]["state"] == "connected"


def test_kalit_holati_qayta_kirishda_saqlanadi(client, hub, net):
    token = client.post("/api/v1/auth/login", json=LOGIN).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.patch("/api/v1/connectors/hrm", json={"enabled": False}, headers=auth).status_code == 200
    token = client.post("/api/v1/auth/login", json=LOGIN).json()["token"]
    rows = _rows(client, token)
    assert rows["hrm"]["enabled"] is False and rows["hrm"]["state"] == "connected"
    assert rows["crm"]["enabled"] is True


def test_qayta_kirishda_eski_crm_refresh_bekor_qilinadi(client, hub, net):
    client.post("/api/v1/auth/login", json=LOGIN)
    client.post("/api/v1/auth/login", json=LOGIN)
    logouts = [body for url, body in net.calls if url == f"{CRM}/api/auth/logout"]
    assert logouts == [{"refresh_token": "refresh-1"}]
    assert hub.store.get("3")["crm"]["refresh_token"] == "refresh-2"


def test_menyudan_qolda_ulash_kalitni_yoqadi(hub, net):
    """`connect` (dialog) `keep_enabled` siz - o'chiq kalit qayta yonadi."""
    hub.connect("7", "hrm", "y.mamajonov", PASSWORD)
    hub.set_enabled("7", "hrm", False)
    assert hub.connect("7", "hrm", "y.mamajonov", PASSWORD)["enabled"] is True


# --- zahira va xatolar -----------------------------------------------------------


def test_notogri_parol_401_umumiy_xabar(client, hub, net):
    wrong = client.post("/api/v1/auth/login", json={**LOGIN, "password": "xato"})
    unknown = client.post("/api/v1/auth/login", json={"username": "yoq", "password": "xato"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"] == "Login yoki parol noto'g'ri"
    # Keycloak "yo'q" degach zahira ham sinaldi, lekin ulanish ochilmadi.
    assert net.urls() == [IDP, IDP]


def test_keycloak_rad_etsa_zahira_hisob_kiradi(client, hub, net):
    """Admin paroli Keycloak'da yo'q - users.yaml orqali kiradi, ulanishlar ochilmaydi."""
    response = client.post("/api/v1/auth/login", json=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json()["user"]["actorId"] == 1
    assert net.urls() == [IDP]
    rows = _rows(client, response.json()["token"])
    assert rows["hrm"]["state"] == rows["crm"]["state"] == "disconnected"


def test_zahira_ochiq_bolsa_401(client, hub, net, monkeypatch):
    monkeypatch.setattr(settings, "local_login_enabled", False)
    assert client.post("/api/v1/auth/login", json=ADMIN).status_code == 401


def test_keycloak_ochgan_bolsa_zahira_kiradi(client, hub, net):
    net.idp_error = (503, {"error": "server_error"})
    assert client.post("/api/v1/auth/login", json=ADMIN).status_code == 200


def test_keycloak_ochgan_zahira_yoq_sabab_aytiladi(client, hub, net):
    net.idp_error = (503, {"error": "server_error"})
    response = client.post("/api/v1/auth/login", json=LOGIN)
    assert response.status_code == 502
    assert "javob bermadi" in response.json()["message"]


def test_hisob_sozlanmagan_bolsa_nima_qilishni_aytadi(client, hub, net):
    """Keycloak "Account is not fully set up" - parol TO'G'RI, hisobda tugallanmagan
    amal bor (2026-09-29 da jonli: B.Boqiyev). Xom matn o'rniga nima qilish aytiladi,
    zahira hisob esa SINALMAYDI (bu parol xatosi emas)."""
    net.idp_error = (400, {"error": "invalid_grant", "error_description": "Account is not fully set up"})
    response = client.post("/api/v1/auth/login", json=LOGIN)
    assert response.status_code == 400
    message = response.json()["message"]
    assert "tugallanmagan amal" in message and "brauzer" in message
    assert "not fully set up" not in message


def test_boshqa_realm_tokeni_rad_etiladi(client, hub, net):
    net.iss = "https://boshqa.test/auth/realms/x"
    response = client.post("/api/v1/auth/login", json=LOGIN)
    assert response.status_code == 502
    assert "realm" in response.json()["message"]


def test_sso_sozlanmagan_bolsa_faqat_zahira(client, net):
    """conftest: hub sozlanmagan -> Keycloak umuman chaqirilmaydi."""
    assert client.post("/api/v1/auth/login", json=ADMIN).status_code == 200
    assert net.urls() == []


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

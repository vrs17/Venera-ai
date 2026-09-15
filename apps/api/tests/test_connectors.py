"""Ulanishlar: foydalanuvchining o'z HRM / CRM hisobi.

HRM, Keycloak va CRM ning O'ZI chaqirilmaydi - almashtirish nuqtasi
`urllib.request.urlopen` (`test_crm_auth.py` dagi kabi). Ustidagi mantiq
(saqlash, muddat oynasi, refresh, rotatsiya, "expired" holati, token
javobga tushmasligi) haqiqiy kod bo'lib qoladi.
"""

from __future__ import annotations

import base64
import io
import json
import stat
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.api.v1 import chat as chat_api
from app.api.v1 import connectors as connectors_api
from app.schemas.auth import AuthUser
from app.services.integrations.crm_auth import CrmAuth
from app.services.integrations.connectors import (
    ConnectorError,
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
    jwt_exp,
)

HRM = "https://hrm.test"
IDP = "https://idp.test/auth/realms/brb-realm/protocol/openid-connect/token"
CRM = "https://crm.test"
PASSWORD = "to'g'ri-parol"

# types.ts: ConnectorStatus
STATUS_FIELDS = {"id", "label", "configured", "state", "login", "enabled", "expiresAt"}


def make_jwt(exp: float) -> str:
    def part(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'HS512'})}.{part({'sub': 'y.m', 'exp': int(exp)})}.sig"


class _Response:
    def __init__(self, raw: bytes, headers: dict | None = None) -> None:
        self._raw = raw
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _http_error(url: str, code: int, payload: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(json.dumps(payload).encode()))


class FakeNet:
    """HRM `/api/authenticate`, Keycloak token, CRM refresh/logout."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.hrm_exp = time.time() + 10 * 3600
        #: HRM javobining shakli - hujjatlashtirilmagan, bir nechtasi sinaladi.
        self.hrm_shape = "id_token"
        self.serial = 0
        #: refresh 400 beradi - token bekor qilingan.
        self.refresh_dead = False
        #: refresh har doim shu xato bilan yiqiladi (vaqtinchalik).
        self.refresh_fail: tuple[int, dict] | None = None
        #: Keycloak har doim shu xato.
        self.idp_error: tuple[int, dict] | None = None

    def __call__(self, request, timeout=None):
        url = request.full_url
        raw = request.data or b""
        if "x-www-form-urlencoded" in request.get_header("Content-type", ""):
            body = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
        else:
            body = json.loads(raw) if raw else {}
        self.calls.append((url, body))

        if url == f"{HRM}/api/authenticate":
            if body.get("password") != PASSWORD:
                # JONLI HRM shunday qaytaradi: 500, ichida 401 (2026-09-15).
                raise _http_error(url, 500, {
                    "type": "https://www.brbtech.uz/problem/problem-with-message",
                    "title": "Internal Server Error", "status": 500,
                    "detail": "401 Unauthorized: [no body]", "message": "error.http.500"})
            jwt = make_jwt(self.hrm_exp)
            if self.hrm_shape == "camel_nested":
                return _Response(json.dumps({"success": True, "data": {
                    "user": {"login": "y.m"}, "accessToken": jwt}}).encode())
            if self.hrm_shape == "header":
                return _Response(b'{"status":"ok"}', {"Authorization": f"Bearer {jwt}"})
            if self.hrm_shape == "unknown_key":
                return _Response(json.dumps({"payload": {"sessionJwt": jwt}}).encode())
            if self.hrm_shape == "none":
                return _Response(json.dumps({"status": "ok", "user": {"login": "y.m"}}).encode())
            return _Response(json.dumps({"id_token": jwt}).encode())
        if url == IDP:
            if self.idp_error:
                raise _http_error(url, *self.idp_error)
            if body.get("password") != PASSWORD:
                raise _http_error(url, 401, {"error": "invalid_grant",
                                             "error_description": "Invalid user credentials"})
            self.serial += 1
            return _Response(json.dumps({
                "access_token": f"access-{self.serial}", "expires_in": 300,
                "refresh_expires_in": 0, "refresh_token": f"refresh-{self.serial}",
                "token_type": "Bearer", "scope": "openid profile email offline_access",
            }).encode())
        if url == f"{CRM}/api/auth/refresh":
            if self.refresh_fail:
                raise _http_error(url, *self.refresh_fail)
            if self.refresh_dead:
                raise _http_error(url, 400, {"error": {"code": "AUTH_FAILED", "message": "rejected"}})
            self.serial += 1
            return _Response(json.dumps({"data": {
                "access_token": f"access-{self.serial}",
                "refresh_token": f"refresh-{self.serial}", "expires_in": 300,
            }}).encode())
        if url == f"{CRM}/api/auth/logout":
            return _Response(b"")
        raise AssertionError(f"kutilmagan so'rov: {url}")

    def urls(self) -> list[str]:
        return [url for url, _ in self.calls]


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def hub(tmp_path, net, monkeypatch):
    built = ConnectorHub(
        ConnectorStore(tmp_path / "connectors" / "tokens.json"),
        HrmAuth(HRM),
        CrmUserAuth(IDP, "crm-client", "sir", CRM),
        hrm_margin=300.0,
        crm_margin=180.0,
    )
    # API va chat AYNI nusxani ishlatadi - `chat.py` `_connectors.hub` ni
    # chaqiruv paytida o'qiydi, shuning uchun bu almashtirish ikkisiga ham
    # ta'sir qiladi.
    monkeypatch.setattr(connectors_api, "hub", built)
    return built


def _later(monkeypatch, seconds: float) -> None:
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + seconds)


# --- HRM ---------------------------------------------------------------------


def test_hrm_ulanish_token_beradi(hub, net):
    status = hub.connect("1", "hrm", "y.m", PASSWORD)
    assert status["state"] == "connected"
    assert status["login"] == "y.m"
    assert status["enabled"] is True
    assert set(status) == STATUS_FIELDS, "holatda token yoki ortiqcha maydon bor"
    assert net.urls() == [f"{HRM}/api/authenticate"]
    assert net.calls[0][1] == {"username": "y.m", "password": PASSWORD}
    tokens = hub.tokens("1")
    assert set(tokens) == {"hrm"}
    assert jwt_exp(tokens["hrm"]) == pytest.approx(net.hrm_exp, abs=1)


def test_parol_saqlanmaydi_va_fayl_600(hub, net):
    hub.connect("1", "hrm", "y.m", PASSWORD)
    raw = hub.store.path.read_text()
    assert PASSWORD not in raw, "PAROL DISKKA TUSHDI"
    mode = stat.S_IMODE(hub.store.path.stat().st_mode)
    assert mode == 0o600, f"tokenlar fayli huquqi {oct(mode)}"


@pytest.mark.parametrize("shape", ["camel_nested", "header", "unknown_key"])
def test_hrm_javob_shakli_har_xil(hub, net, shape):
    """HRM javobining shakli hujjatlashtirilmagan: camelCase, ichma-ich,
    sarlavhada - hammasidan token topiladi."""
    net.hrm_shape = shape
    assert hub.connect("1", "hrm", "y.m", PASSWORD)["state"] == "connected"
    assert jwt_exp(hub.tokens("1")["hrm"]) == pytest.approx(net.hrm_exp, abs=1)


def test_hrm_tokensiz_javob_502(hub, net):
    net.hrm_shape = "none"
    with pytest.raises(ConnectorError) as exc:
        hub.connect("1", "hrm", "y.m", PASSWORD)
    assert exc.value.status == 502


def test_hrm_muddati_yaqin_bolsa_yuborilmaydi(hub, net):
    """Savol-javob bir necha daqiqa cho'zilishi mumkin: 300 s dan kam
    qolgan token javob o'rtasida o'lardi."""
    net.hrm_exp = time.time() + 200
    status = hub.connect("1", "hrm", "y.m", PASSWORD)
    assert status["state"] == "expired"
    assert hub.tokens("1") == {}


def test_hrm_notogri_parol(hub, net):
    """HRM 500 ichida 401 beradi - bu PAROL xatosi, "javob bermadi" emas."""
    with pytest.raises(ConnectorError) as exc:
        hub.connect("1", "hrm", "y.m", "xato")
    assert exc.value.status == 400
    assert "parol" in str(exc.value).lower()
    assert hub.status("1")[0]["state"] == "disconnected"


def test_hrm_haqiqiy_500_javob_bermadi(hub, net, monkeypatch):
    """401 siz 500 - HRM ning o'z xatosi, parol emas."""
    real = net.__call__

    def broken(request, timeout=None):
        if request.full_url == f"{HRM}/api/authenticate":
            raise _http_error(request.full_url, 500, {"title": "Internal Server Error",
                                                      "detail": "NullPointerException"})
        return real(request, timeout)

    monkeypatch.setattr(urllib.request, "urlopen", broken)
    with pytest.raises(ConnectorError) as exc:
        hub.connect("1", "hrm", "y.m", PASSWORD)
    assert exc.value.status == 502


def test_qayta_ishga_tushganda_saqlangan_qoladi(tmp_path, net):
    path = tmp_path / "tokens.json"
    first = ConnectorHub(ConnectorStore(path), HrmAuth(HRM), CrmUserAuth(IDP, "c", "s", CRM))
    first.connect("1", "hrm", "y.m", PASSWORD)
    second = ConnectorHub(ConnectorStore(path), HrmAuth(HRM), CrmUserAuth(IDP, "c", "s", CRM))
    assert "hrm" in second.tokens("1")
    assert second.status("1")[0]["login"] == "y.m"


def test_jwt_exp():
    assert jwt_exp(make_jwt(1_800_000_000)) == 1_800_000_000.0
    assert jwt_exp("bu-jwt-emas") is None
    assert jwt_exp("a.b.c") is None


# --- CRM ---------------------------------------------------------------------


def test_crm_ulanish_keycloak_orqali(hub, net):
    status = hub.connect("1", "crm", "y.m", PASSWORD)
    assert status["state"] == "connected"
    url, form = net.calls[0]
    assert url == IDP
    assert form["grant_type"] == "password"
    assert form["client_id"] == "crm-client"
    assert form["client_secret"] == "sir"
    assert "offline_access" in form["scope"]
    # Login paytidagi access_token keshlanadi - darhol refresh qilinmaydi.
    assert hub.tokens("1") == {"crm": "access-1"}
    assert net.urls() == [IDP]


def test_crm_savol_oldidan_yangilanadi_va_rotatsiya(hub, net, monkeypatch):
    """Muddati 180 s dan kam qolganda refresh; yangi refresh_token saqlanadi."""
    hub.connect("1", "crm", "y.m", PASSWORD)
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {"crm": "access-2"}
    assert net.urls() == [IDP, f"{CRM}/api/auth/refresh"]
    assert net.calls[1][1] == {"refresh_token": "refresh-1"}
    assert json.loads(hub.store.path.read_text())["1"]["crm"]["refresh_token"] == "refresh-2"


def test_crm_kesh_qayta_ishlatiladi(hub, net):
    hub.connect("1", "crm", "y.m", PASSWORD)
    hub.tokens("1")
    hub.tokens("1")
    assert len(net.calls) == 1, "har savolda refresh - 30/daqiqa chegarasini o'zimiz yeymiz"


def test_crm_refresh_olgan_bolsa_expired(hub, net, monkeypatch):
    hub.connect("1", "crm", "y.m", PASSWORD)
    net.refresh_dead = True
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {}
    status = hub.status("1")[1]
    assert status["state"] == "expired"
    assert status["login"] == "y.m", "login qoladi - oyna uni to'ldirib beradi"
    # Keyingi savol yana urinmaydi: refresh_token o'chirilgan.
    assert hub.tokens("1") == {}
    assert net.urls().count(f"{CRM}/api/auth/refresh") == 1


def test_crm_vaqtinchalik_xatoda_eski_token(hub, net, monkeypatch):
    hub.connect("1", "crm", "y.m", PASSWORD)
    net.refresh_fail = (503, {"error": "DOWN"})
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {"crm": "access-1"}, "hali 150 s yaroqli"
    assert hub.status("1")[1]["state"] == "connected"


def test_crm_hisob_sozlanmagan_xabari(hub, net):
    net.idp_error = (400, {"error": "invalid_grant", "error_description": "Account is not fully set up"})
    with pytest.raises(ConnectorError) as exc:
        hub.connect("1", "crm", "y.m", PASSWORD)
    assert exc.value.status == 400
    assert "Account is not fully set up" in str(exc.value)


def test_crm_notogri_parol(hub, net):
    with pytest.raises(ConnectorError) as exc:
        hub.connect("1", "crm", "y.m", "xato")
    assert exc.value.status == 400
    assert "parol" in str(exc.value).lower()


def test_uzish_crm_da_bekor_qiladi(hub, net):
    hub.connect("1", "crm", "y.m", PASSWORD)
    status = hub.disconnect("1", "crm")
    assert status["state"] == "disconnected"
    assert (f"{CRM}/api/auth/logout", {"refresh_token": "refresh-1"}) in net.calls
    assert hub.tokens("1") == {}


# --- umumiy ------------------------------------------------------------------


def test_kalit_ochiq_bolsa_token_yuborilmaydi(hub, net):
    hub.connect("1", "hrm", "y.m", PASSWORD)
    assert hub.set_enabled("1", "hrm", False)["enabled"] is False
    assert hub.tokens("1") == {}
    hub.set_enabled("1", "hrm", True)
    assert "hrm" in hub.tokens("1")


def test_ulanmaganga_kalit_409(hub):
    with pytest.raises(ConnectorError) as exc:
        hub.set_enabled("1", "hrm", True)
    assert exc.value.status == 409


def test_sozlanmagan_platforma(tmp_path):
    empty = ConnectorHub(ConnectorStore(tmp_path / "t.json"), HrmAuth(""), CrmUserAuth("", "", "", ""))
    assert [s["configured"] for s in empty.status("1")] == [False, False]
    with pytest.raises(ConnectorError) as exc:
        empty.connect("1", "hrm", "y.m", PASSWORD)
    assert exc.value.status == 503


def test_foydalanuvchilar_aralashmaydi(hub, net):
    hub.connect("1", "hrm", "y.m", PASSWORD)
    assert hub.tokens("2") == {}
    assert hub.status("2")[0]["state"] == "disconnected"


# --- API ---------------------------------------------------------------------


def test_api_tokensiz_401(client):
    assert client.get("/api/v1/connectors").status_code == 401


def test_api_holat_types_ts_ga_mos(client, auth, hub):
    body = client.get("/api/v1/connectors", headers=auth).json()
    assert [c["id"] for c in body["connectors"]] == ["hrm", "crm"]
    for entry in body["connectors"]:
        assert set(entry) == STATUS_FIELDS


def test_api_ulanish_kalit_uzish(client, auth, hub, net):
    response = client.post("/api/v1/connectors/hrm/connect", headers=auth,
                           json={"username": "y.m", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "connected"
    assert "eyJ" not in response.text, "TOKEN BRAUZERGA KETDI"

    response = client.patch("/api/v1/connectors/hrm", headers=auth, json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = client.delete("/api/v1/connectors/hrm", headers=auth)
    assert response.status_code == 200
    assert response.json()["state"] == "disconnected"


def test_api_notogri_parol_400(client, auth, hub, net):
    response = client.post("/api/v1/connectors/hrm/connect", headers=auth,
                           json={"username": "y.m", "password": "xato"})
    assert response.status_code == 400
    assert response.json()["message"]


def test_api_bosh_maydon_422(client, auth, hub):
    response = client.post("/api/v1/connectors/hrm/connect", headers=auth,
                           json={"username": "", "password": ""})
    assert response.status_code == 422


def test_api_notogri_platforma_404(client, auth, hub):
    response = client.post("/api/v1/connectors/sap/connect", headers=auth,
                           json={"username": "a", "password": "b"})
    assert response.status_code == 404


def test_chat_odamning_tokeni_umumiydan_ustun(client, auth, hub, net, monkeypatch, tmp_path):
    """O'z hisobi bilan kirgan odam uchun `.env` dagi umumiy token EMAS,
    uning o'z tokeni ketadi; ulanmagan odam uchun umumiy token qoladi."""
    monkeypatch.setattr(chat_api, "platform_tokens", lambda: {"hrm": "umumiy"})
    # Agent sessiyasi (`.env` dagi CRM_USERNAME/PASSWORD) bu testga aloqasiz
    # va sozlangan bo'lsa soxta tarmoqqa noma'lum so'rov yuborardi.
    monkeypatch.setattr(chat_api, "_crm", CrmAuth("", "", "", tmp_path / "agent"))
    me = AuthUser(actorId=1, email="admin@venera.uz", fullName="Admin")
    other = AuthUser(actorId=2, email="demo@venera.uz", fullName="Demo")
    assert chat_api._live_tokens(me) == {"hrm": "umumiy"}
    client.post("/api/v1/connectors/hrm/connect", headers=auth,
                json={"username": "y.m", "password": PASSWORD})
    assert chat_api._live_tokens(me)["hrm"].startswith("eyJ")
    assert chat_api._live_tokens(other) == {"hrm": "umumiy"}


def test_health_ulanishlar_holati(client, auth, hub):
    body = client.get("/api/health/detail", headers=auth).json()
    assert body["connectors"] == {"hrm": True, "crm": True, "users": 0}

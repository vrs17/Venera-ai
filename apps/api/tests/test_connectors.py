"""Ulanishlar: foydalanuvchining o'z HRM / CRM hisobi.

HRM va CRM ning O'ZI chaqirilmaydi - almashtirish nuqtasi
`urllib.request.urlopen` (`test_crm_auth.py` dagi kabi). Ustidagi mantiq
(saqlash, muddat oynasi, refresh, rotatsiya, "expired" holati, token
javobga tushmasligi) haqiqiy kod bo'lib qoladi.

KELISHUV (2026-11-12, ega qarori):
  * HRM va CRM ga login + parol bilan ulanib bo'lmaydi - ikkalasi SSO
    kirishida o'zi ulanadi (`test_sso_crm.py`, `test_sso_hrm.py`).
    `POST /connectors/hrm/connect` - 410, `crm` - 404; bu yerda faqat ESKI,
    qo'lda ulangan yozuvlar sinaladi - ular tokeni tugaguncha ishlaydi;
  * `GET /connectors` faqat HRM qatorini beradi (Mini App, mobil ilova);
  * kalit yo'q: yozuvdagi `enabled: false` hech narsani o'chirmaydi;
  * parol hech qayerda yo'q - na diskda, na xotirada.
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
    USER_PLATFORMS,
    ConnectorError,
    ConnectorHub,
    ConnectorStore,
    CrmUserAuth,
    HrmAuth,
)

HRM = "https://hrm.test"
IDP = "https://idp.test/auth/realms/brb-realm/protocol/openid-connect/token"
CRM = "https://crm.test"
PASSWORD = "to'g'ri-parol"

# types.ts: ConnectorStatus
STATUS_FIELDS = {"id", "label", "configured", "state", "login", "enabled", "expiresAt", "via"}


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
    """CRM refresh/logout (eski, qo'lda ulangan yozuvlar uchun). HRM ga login va
    Keycloak parol granti YO'Q: ularga so'rov ketsa - "kutilmagan so'rov"."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.serial = 0
        #: refresh 400 beradi - token bekor qilingan.
        self.refresh_dead = False
        #: refresh har doim shu xato bilan yiqiladi (vaqtinchalik).
        self.refresh_fail: tuple[int, dict] | None = None

    def __call__(self, request, timeout=None):
        url = request.full_url
        raw = request.data or b""
        if "x-www-form-urlencoded" in request.get_header("Content-type", ""):
            body = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
        else:
            body = json.loads(raw) if raw else {}
        self.calls.append((url, body))

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


def legacy_crm(hub: ConnectorHub, uid: str = "1", login: str = "y.m") -> None:
    """ESKI, qo'lda ulangan CRM yozuvi (`via` yo'q) - 2026-11-12 gacha odam CRM ga
    parol bilan ulanganda shunday saqlanardi. Yangisi ochilmaydi, borlari ishlaydi:
    token `access-0` (300 s), yangilash CRM ning o'zida (`refresh-0` bilan)."""
    hub.adopt_crm(uid, login, "access-0", "refresh-0", 300.0)


def legacy_hrm(hub: ConnectorHub, uid: str = "1", login: str = "y.m", *, left: float = 10 * 3600) -> str:
    """ESKI, qo'lda ulangan HRM yozuvi - 2026-11-12 gacha odam HRM ga login + parol
    bilan ulanganda shunday saqlanardi (HRM bergan 10 soatlik token). Yangisi
    ochilmaydi, borlari tokeni tugaguncha ishlaydi. Qaytaradi: token."""
    exp = time.time() + left
    token = make_jwt(exp)
    hub.store.set(uid, "hrm", {"login": login, "token": token, "expires_at": exp,
                               "enabled": True, "connected_at": time.time()})
    return token


# --- HRM: qo'lda ulash yo'q, eski yozuvlar tokeni tugaguncha ishlaydi ---------------


def test_eski_qolda_ulangan_hrm_token_beradi(hub, net):
    token = legacy_hrm(hub)
    status = hub.status("1")[0]
    assert (status["state"], status["login"], status["enabled"], status["via"]) == ("connected", "y.m", True, None)
    assert set(status) == STATUS_FIELDS, "holatda token yoki ortiqcha maydon bor"
    assert hub.tokens("1") == {"hrm": token}
    assert net.calls == [], "HRM ga hech qanday so'rov ketmaydi"


def test_eski_hrm_muddati_yaqin_bolsa_yuborilmaydi_va_yangilanmaydi(hub, net):
    """Savol-javob bir necha daqiqa cho'zilishi mumkin: 300 s dan kam qolgan token
    javob o'rtasida o'lardi. Qayta kirish (parol bilan) yo'q - odam BRB-Tech ID bilan
    qayta kiradi."""
    legacy_hrm(hub, left=200)
    assert hub.status("1")[0]["state"] == "expired"
    assert hub.tokens("1") == {}
    assert net.calls == []


def test_qolda_ulash_va_parol_xotirasi_yoq(hub):
    for gone in ("connect", "adopt_hrm", "remember_password", "forget_password", "has_password", "_renew_hrm"):
        assert not hasattr(hub, gone), gone
    assert not hasattr(hub.hrm, "login")


def test_tokenlar_fayli_600_va_parolsiz(hub, net):
    legacy_hrm(hub)
    legacy_crm(hub)
    raw = hub.store.path.read_text()
    assert "password" not in raw.lower()
    mode = stat.S_IMODE(hub.store.path.stat().st_mode)
    assert mode == 0o600, f"tokenlar fayli huquqi {oct(mode)}"


def test_qayta_ishga_tushganda_saqlangan_qoladi(tmp_path, net):
    path = tmp_path / "tokens.json"
    first = ConnectorHub(ConnectorStore(path), HrmAuth(HRM), CrmUserAuth(IDP, "c", "s", CRM))
    legacy_hrm(first)
    second = ConnectorHub(ConnectorStore(path), HrmAuth(HRM), CrmUserAuth(IDP, "c", "s", CRM))
    assert "hrm" in second.tokens("1")
    assert second.status("1")[0]["login"] == "y.m"


# --- CRM: parol bilan ulanish yo'q, eski yozuvlar ishlaydi ---------------------


def test_eski_crm_yozuvi_token_beradi(hub, net):
    legacy_crm(hub)
    entry = hub.store.get("1")["crm"]
    assert "via" not in entry and entry["enabled"] is True
    # Saqlangan paytdagi access_token keshlanadi - darhol refresh qilinmaydi.
    assert hub.tokens("1") == {"crm": "access-0"}
    assert net.calls == []


def test_crm_savol_oldidan_yangilanadi_va_rotatsiya(hub, net, monkeypatch):
    """Muddati 180 s dan kam qolganda refresh; yangi refresh_token saqlanadi."""
    legacy_crm(hub)
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {"crm": "access-1"}
    assert net.urls() == [f"{CRM}/api/auth/refresh"]
    assert net.calls[0][1] == {"refresh_token": "refresh-0"}
    assert json.loads(hub.store.path.read_text())["1"]["crm"]["refresh_token"] == "refresh-1"


def test_crm_kesh_qayta_ishlatiladi(hub, net):
    legacy_crm(hub)
    hub.tokens("1")
    hub.tokens("1")
    assert net.calls == [], "har savolda refresh - 30/daqiqa chegarasini o'zimiz yeymiz"


def test_crm_refresh_olgan_bolsa_expired(hub, net, monkeypatch):
    legacy_crm(hub)
    net.refresh_dead = True
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {}
    status = hub.status("1")[1]
    assert status["state"] == "expired"
    assert status["login"] == "y.m", "login qoladi - admin panel kimligini ko'rsatadi"
    # Keyingi savol yana urinmaydi: refresh_token o'chirilgan.
    assert hub.tokens("1") == {}
    assert net.urls().count(f"{CRM}/api/auth/refresh") == 1


def test_crm_vaqtinchalik_xatoda_eski_token(hub, net, monkeypatch):
    legacy_crm(hub)
    net.refresh_fail = (503, {"error": "DOWN"})
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {"crm": "access-0"}, "hali 150 s yaroqli"
    assert hub.status("1")[1]["state"] == "connected"


def test_uzish_crm_da_bekor_qiladi(hub, net):
    """Admin panel uzishi (`hub.disconnect`, sukut - hamma platforma)."""
    legacy_crm(hub)
    status = hub.disconnect("1", "crm")
    assert status["state"] == "disconnected"
    assert (f"{CRM}/api/auth/logout", {"refresh_token": "refresh-0"}) in net.calls
    assert hub.tokens("1") == {}


# --- umumiy ------------------------------------------------------------------


def _switch_off(hub: ConnectorHub, uid: str, platform: str) -> None:
    """Yozuvni eski kod "o'chirib qo'ygan" holatga keltiradi (`enabled: false`)."""
    hub.store.set(uid, platform, {**hub.store.get(uid)[platform], "enabled": False})


def test_ochirilgan_hrm_baribir_token_beradi(hub, net):
    """Kalit yo'q: yozuvda eski `enabled: false` qolgan bo'lsa ham ulangan, yaroqli
    HRM tokeni ishlatiladi - aks holda kalitsiz ilovada uni qayta yoqib bo'lmasdi."""
    token = legacy_hrm(hub)
    _switch_off(hub, "1", "hrm")
    assert hub.tokens("1")["hrm"] == token
    status = hub.status("1")[0]
    assert status["state"] == "connected" and status["enabled"] is True


def test_ochirilgan_crm_baribir_token_beradi(hub, net, monkeypatch):
    """CRM har doim yoqiq: saqlangan `enabled: false` tokenni to'xtatmaydi (kesh ham,
    yangilash ham), holatda "o'chiq" ko'rinmaydi va guruh / yig'ilish CRM i sharti
    (`has_own_crm`) ham bajariladi."""
    me = AuthUser(actorId=1, email="admin@venera.uz", fullName="Admin")
    assert chat_api.has_own_crm(me) is False
    legacy_crm(hub)
    _switch_off(hub, "1", "crm")
    assert hub.tokens("1") == {"crm": "access-0"}
    assert chat_api.has_own_crm(me) is True
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {"crm": "access-1"}
    # Rotatsiya eski maydonga tegmaydi - va u baribir hech narsani o'chirmaydi.
    assert hub.store.get("1")["crm"]["enabled"] is False
    assert hub.status("1")[1]["enabled"] is True
    assert chat_api.has_own_crm(me) is True


def test_muddati_otgan_crm_oz_ulanishi_emas(hub, net, monkeypatch):
    """`has_own_crm` faqat tirik sessiyani hisoblaydi: refresh rad etilgach - yo'q."""
    me = AuthUser(actorId=1, email="admin@venera.uz", fullName="Admin")
    legacy_crm(hub)
    net.refresh_dead = True
    _later(monkeypatch, 150.0)
    assert hub.tokens("1") == {}
    assert chat_api.has_own_crm(me) is False


def test_ulanmaganga_kalit_409(hub):
    with pytest.raises(ConnectorError) as exc:
        hub.connected("1", "hrm")
    assert exc.value.status == 409


def test_holat_odamga_faqat_hrm_adminga_ikkalasi(hub, net):
    legacy_crm(hub)
    assert USER_PLATFORMS == ("hrm",)
    assert [s["id"] for s in hub.status("1", USER_PLATFORMS)] == ["hrm"]
    assert [(s["id"], s["state"]) for s in hub.status("1")] == [
        ("hrm", "disconnected"), ("crm", "connected")]


def test_sozlanmagan_platforma(tmp_path):
    empty = ConnectorHub(ConnectorStore(tmp_path / "t.json"), HrmAuth(""), CrmUserAuth("", "", "", ""))
    assert [s["configured"] for s in empty.status("1")] == [False, False]


def test_foydalanuvchilar_aralashmaydi(hub, net):
    legacy_hrm(hub)
    assert hub.tokens("2") == {}
    assert hub.status("2")[0]["state"] == "disconnected"


# --- API ---------------------------------------------------------------------


def test_api_tokensiz_401(client):
    assert client.get("/api/v1/connectors").status_code == 401


def test_api_holat_types_ts_ga_mos(client, auth, hub):
    body = client.get("/api/v1/connectors", headers=auth).json()
    assert [c["id"] for c in body["connectors"]] == ["hrm"]
    for entry in body["connectors"]:
        assert set(entry) == STATUS_FIELDS


def test_api_royxatda_faqat_hrm_crm_ulangan_bolsa_ham(client, auth, hub, net):
    """CRM odamga ko'rinmaydi: ulangan bo'lsa ham ro'yxatda faqat HRM qatori."""
    legacy_crm(hub)                                   # "1" - `auth` dagi admin
    response = client.get("/api/v1/connectors", headers=auth)
    assert response.status_code == 200, response.text
    assert [c["id"] for c in response.json()["connectors"]] == ["hrm"]
    assert "crm" not in response.text.lower() and "refresh-0" not in response.text


def test_api_crm_ulash_kalit_uzish_404(client, auth, hub, net):
    """CRM ni odam boshqarmaydi: uchala yo'l ham notanish platforma bilan BIR XIL
    404 beradi, ulanishga tegmaydi va tarmoqqa bormaydi."""
    legacy_crm(hub)
    before = hub.store.get("1")["crm"]
    unknown = client.delete("/api/v1/connectors/sap", headers=auth)
    assert unknown.status_code == 404
    responses = [
        client.post("/api/v1/connectors/crm/connect", headers=auth,
                    json={"username": "y.m", "password": PASSWORD}),
        client.patch("/api/v1/connectors/crm", headers=auth, json={"enabled": False}),
        client.delete("/api/v1/connectors/crm", headers=auth),
    ]
    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json()["message"] == unknown.json()["message"]
    assert hub.store.get("1")["crm"] == before
    assert net.calls == []
    assert hub.tokens("1") == {"crm": "access-0"}, "CRM ishlab turibdi"


def test_api_holat_kalit_uzish(client, auth, hub, net):
    legacy_hrm(hub)                                   # "1" - `auth` dagi admin
    response = client.get("/api/v1/connectors", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["connectors"][0]["state"] == "connected"
    assert "eyJ" not in response.text, "TOKEN BRAUZERGA KETDI"

    # Eski klientlar kalitni hali yuboradi: so'rov qabul qilinadi, lekin hech narsani
    # o'chirmaydi - javob haqiqiy holat, token esa ishlatilaveradi.
    response = client.patch("/api/v1/connectors/hrm", headers=auth, json={"enabled": False})
    assert response.status_code == 200
    assert set(response.json()) == STATUS_FIELDS
    assert response.json()["enabled"] is True and response.json()["state"] == "connected"
    assert "hrm" in hub.tokens("1")

    response = client.delete("/api/v1/connectors/hrm", headers=auth)
    assert response.status_code == 200
    assert response.json()["state"] == "disconnected"
    assert hub.tokens("1") == {}


def test_api_kalit_tanasi_hali_tekshiriladi(client, auth, hub, net):
    """`PATCH` shakli o'zgarmagan: tanasiz so'rov 422, ulanmagan HRM - 409."""
    assert client.patch("/api/v1/connectors/hrm", headers=auth, json={}).status_code == 422
    assert client.patch("/api/v1/connectors/hrm", headers=auth,
                        json={"enabled": True}).status_code == 409


def test_api_qolda_ulash_410(client, auth, hub, net):
    """Eski klient (keshdagi veb, eski Mini App) parol yuborsa ham: 410, nima qilish
    kerakligi aytiladi, HRM ga ham, omborga ham hech narsa ketmaydi."""
    for body in ({"username": "y.m", "password": PASSWORD}, None):
        response = client.post("/api/v1/connectors/hrm/connect", headers=auth, json=body)
        assert response.status_code == 410, response.text
        assert "BRB-Tech ID" in response.json()["message"]
        assert PASSWORD not in response.text
    assert net.calls == [] and hub.store.get("1") == {}


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
    legacy_hrm(hub)
    assert chat_api._live_tokens(me)["hrm"].startswith("eyJ")
    assert chat_api._live_tokens(other) == {"hrm": "umumiy"}


def test_health_ulanishlar_holati(client, auth, hub):
    """`crm` - SSO kirishida CRM ulanishi ochila oladimi. Bu markazda SSO manbasi
    yo'q (eski `crm-client` sozlamalari to'liq bo'lsa ham) - demak yo'q, va sababi
    ogohlantirishda aytiladi. SSO bilan holat - `test_sso_crm.py`."""
    body = client.get("/api/health/detail", headers=auth).json()
    assert body["connectors"] == {"hrm": True, "hrmSso": False, "crm": False, "users": 0}
    note = next(w for w in body["warnings"] if "CRM ulanishi" in w)
    assert "SSO_CRM_CONNECT" in note and "CRM_BASE_URL" in note

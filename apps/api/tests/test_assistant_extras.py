"""Barno xotirasi va platforma kalitlari: `/api/v1/assistant/...` proksi.

Yuqoridagi xizmat chaqirilmaydi - `build_opener` soxta (`test_chats.py` dagi
kabi), lekin soxta xizmat HOLATLI: xotira va kalitlar `user_id` bo'yicha
saqlanadi. Shu tufayli asosiy kafolatni haqiqiy ko'rinishda tekshirsa
bo'ladi - odam faqat O'Z xotirasini ko'radi va o'chiradi, chunki `user_id`
FAQAT sessiyadan olinadi (so'rovdagi `user_id` e'tiborsiz yoki 422).

Qolgani: "hammasini unutish" tasdiqsiz xizmatga bormaydi; xizmat xatolari
502/503/504 + `code` ga tushadi (401 - ham 502: sessiya joyida); sozlamalar
chegarasi (`HRM_ASSISTANT_SETTINGS_TIMEOUT`) klientga yetadi; chegaradan
oshgan so'rov 429 + `Retry-After` va xizmatga bormaydi; xotira matni
jurnalga ham, hisobga (`api_calls`) ham tushmaydi.
"""

from __future__ import annotations

import io
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.api.v1 import assistant_extras as extras
from app.api.v1 import chat as chat_api
from app.core.config import settings
from app.services import analytics
from app.services.integrations.assistant import AssistantClient, AssistantError
from app.services.reports import RateLimiter

BASE = "http://assistant.test"
SECRET = "juda-maxfiy-sir-123"
#: Jurnalga tushmasligi kerak bo'lgan xotira matni - izlash oson bo'lsin deb noyob.
PRIVATE = "Qizimning ismi Malika-7f3a, u har seshanba suzishga boradi"

ADMIN_ID = "venera:1"   # conftest: admin@venera.uz, actor 1
DEMO_ID = "venera:2"    # conftest: demo@venera.uz, actor 2

# Kontrakt (UI lane va mobil shu shakllarga yoziladi).
MEMORY_LIST_FIELDS = {"items", "count"}
MEMORY_ITEM_FIELDS = {"id", "text", "kind", "source", "created_at", "updated_at"}
MEMORY_DELETED_FIELDS = {"deleted", "status"}
PLATFORM_LIST_FIELDS = {"platforms"}
PLATFORM_FIELDS = {"id", "name", "description", "kind", "needs_login", "available",
                   "user_enabled", "enabled"}
ERROR_FIELDS = {"timestamp", "status", "error", "message", "path", "code"}

PLATFORM_IDS = ["hrm", "crm", "dwh", "biznes247", "superapp", "biznes247_kb", "biznes247_help"]


def _platform(pid: str, *, available: bool = True, user_enabled: bool = True) -> dict:
    return {
        "id": pid,
        "name": {"biznes247": "Biznes 24/7", "biznes247_kb": "Biznes 24/7 qo'llanmalari",
                 "biznes247_help": "Biznes Help"}.get(pid, pid.upper()),
        "description": f"{pid} izohi",
        "kind": "live" if pid in ("hrm", "crm") else ("data" if pid == "dwh" else "knowledge"),
        "needs_login": pid in ("hrm", "crm"),
        "available": available,
        "user_enabled": user_enabled,
        "enabled": available and user_enabled,
    }


class _JsonResponse:
    def __init__(self, payload, raw: bytes | None = None) -> None:
        self._raw = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode()
        self.headers = {"X-Request-Id": "served-1"}
        self.status = 200

    def read(self, size: int = -1) -> bytes:
        raw, self._raw = self._raw, b""
        return raw

    def close(self) -> None:
        return None


class FakeAgent:
    """Xizmatning `/api/memory` va `/api/connectors` yo'llari - `user_id` bo'yicha holatli."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.memory: dict[str, list[dict]] = {
            ADMIN_ID: [
                {"id": "m1", "text": PRIVATE, "kind": "fact", "source": "user",
                 "created_at": "2026-10-09T08:00:00Z", "updated_at": "2026-10-09T08:00:00Z"},
                {"id": "h3f2a", "text": "Har dushanba sprint rejasini tuzadi", "kind": "routine",
                 "source": "learned", "created_at": "", "updated_at": None},
            ],
            DEMO_ID: [
                {"id": "m2", "text": "Javoblarni qisqa yozing", "kind": "preference",
                 "source": "learned", "created_at": "2026-10-08T10:00:00Z"},
            ],
        }
        self.switches: dict[tuple[str, str], bool] = {}
        self.unavailable = {"superapp"}
        #: Xato in'ektsiyasi: HTTP status (int) yoki ko'tariladigan istisno.
        self.fail: int | BaseException | None = None
        self.fail_body = {"detail": "xato"}
        #: To'g'ridan-to'g'ri qaytariladigan xom javob (buzuq JSON va h.k.).
        self.raw: bytes | None = None
        #: Har yo'lga majburan qaytariladigan obyekt (shakl sinovi).
        self.payload: dict | list | None = None

    def open(self, request, timeout=None):
        parts = urllib.parse.urlsplit(request.full_url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        method = request.get_method()
        body = json.loads(request.data) if request.data else None
        self.calls.append({
            "path": parts.path, "query": query, "method": method, "body": body,
            "timeout": timeout,
            "client_id": request.get_header("X-client-id"),
            "client_secret": request.get_header("X-client-secret"),
        })
        if isinstance(self.fail, BaseException):
            raise self.fail
        if isinstance(self.fail, int):
            raise urllib.error.HTTPError(request.full_url, self.fail, "xato", {},
                                         io.BytesIO(json.dumps(self.fail_body).encode()))
        if self.raw is not None:
            return _JsonResponse(None, raw=self.raw)
        if self.payload is not None:
            return _JsonResponse(self.payload)
        user = query.get("user_id", "")
        if not user:
            return self._error(request, 422, "user_id required")
        path = parts.path
        if path == "/api/memory" and method == "GET":
            items = self.memory.get(user, [])
            return _JsonResponse({"items": items, "count": len(items)})
        if path == "/api/memory" and method == "DELETE":
            items = self.memory.pop(user, [])
            return _JsonResponse({"deleted": [i["id"] for i in items],
                                  "status": "deleted" if items else "empty"})
        if path.startswith("/api/memory/") and method == "DELETE":
            item_id = urllib.parse.unquote(path.rsplit("/", 1)[1])
            items = self.memory.get(user, [])
            if not any(i["id"] == item_id for i in items):
                return self._error(request, 404, f"no memory item {item_id}")
            self.memory[user] = [i for i in items if i["id"] != item_id]
            return _JsonResponse({"deleted": [item_id], "status": "deleted"})
        if path == "/api/connectors" and method == "GET":
            return _JsonResponse({"connectors": [self._item(user, pid) for pid in PLATFORM_IDS]})
        if path.startswith("/api/connectors/") and method == "PUT":
            pid = path.rsplit("/", 1)[1]
            if pid not in PLATFORM_IDS:
                return self._error(request, 404, "Unknown connector")
            self.switches[(user, pid)] = bool(body["enabled"])
            return _JsonResponse(self._item(user, pid))
        return self._error(request, 404, "Not Found")

    def _item(self, user: str, pid: str) -> dict:
        return _platform(pid, available=pid not in self.unavailable,
                         user_enabled=self.switches.get((user, pid), True))

    @staticmethod
    def _error(request, status: int, detail: str):
        raise urllib.error.HTTPError(request.full_url, status, "xato", {},
                                     io.BytesIO(json.dumps({"detail": detail}).encode()))


@pytest.fixture(autouse=True)
def _fresh_limits():
    extras.reset_limits()
    yield
    extras.reset_limits()


@pytest.fixture
def agent(monkeypatch) -> FakeAgent:
    fake = FakeAgent()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    return fake


@pytest.fixture
def assistant(agent) -> AssistantClient:
    return AssistantClient(BASE, "barno", SECRET, timeout=120, max_concurrent=2)


@pytest.fixture
def api(monkeypatch, assistant, client):
    """Endpointlar soxta xizmat ustida."""
    monkeypatch.setattr(chat_api, "_assistant", assistant)
    return client


def _rows(sql: str) -> list[dict]:
    assert analytics.flush(5.0), "yozuvchi ulgurmadi"
    return analytics.get_db().rows(sql)


# --- klient ---------------------------------------------------------------------------


def test_klient_xotira_yollari(assistant, agent):
    assert assistant.list_memory(user_id=ADMIN_ID, timeout=7)["count"] == 2
    assert assistant.delete_memory_item("m1", user_id=ADMIN_ID)["deleted"] == ["m1"]
    assert assistant.clear_memory(user_id=ADMIN_ID)["status"] == "deleted"
    get, delete, clear = agent.calls
    assert (get["method"], get["path"], get["query"]) == ("GET", "/api/memory", {"user_id": ADMIN_ID})
    assert get["timeout"] == 7, "sozlamalar chegarasi chaqiruvga yetadi"
    assert get["body"] is None
    assert get["client_id"] == "barno" and get["client_secret"] == SECRET
    assert (delete["method"], delete["path"]) == ("DELETE", "/api/memory/m1")
    assert delete["timeout"] == 120, "berilmasa - klientniki"
    assert (clear["method"], clear["path"], clear["query"]) == (
        "DELETE", "/api/memory", {"user_id": ADMIN_ID})


def test_klient_platforma_yollari(assistant, agent):
    listed = assistant.list_platforms(user_id=DEMO_ID)
    assert [p["id"] for p in listed["connectors"]] == PLATFORM_IDS
    item = assistant.set_platform("dwh", user_id=DEMO_ID, enabled=False)
    assert item["user_enabled"] is False and item["enabled"] is False
    get, put = agent.calls
    assert (get["method"], get["path"], get["query"]) == ("GET", "/api/connectors", {"user_id": DEMO_ID})
    assert (put["method"], put["path"], put["query"], put["body"]) == (
        "PUT", "/api/connectors/dwh", {"user_id": DEMO_ID}, {"enabled": False})


@pytest.mark.parametrize("bad", ["", "a/b", "../x", "x y", "x" * 129, ".", "..", "...",
                                 "-m1", "_m1", "ид1", "m1\u0663", "m~1"])
def test_klient_yaroqsiz_xotira_kaliti_xizmatga_bormaydi(assistant, agent, bad):
    with pytest.raises(AssistantError) as exc:
        assistant.delete_memory_item(bad, user_id=ADMIN_ID)
    assert exc.value.status == 400 and exc.value.reason is None
    assert agent.calls == []


@pytest.mark.parametrize("good", ["m12", "h3f2a9c", "M-1", "a.b", "x" * 128])
def test_klient_xotira_kaliti_yaroqli(assistant, agent, good):
    """Xizmat kalitlari (`m12`, hex) va ehtiyot uchun `-`, `.` ichida - o'tadi."""
    with pytest.raises(AssistantError) as exc:
        assistant.delete_memory_item(good, user_id=ADMIN_ID)
    assert exc.value.status == 404, "xizmatga bordi (soxtada bunday band yo'q)"
    assert agent.calls[0]["path"] == f"/api/memory/{good}"


@pytest.mark.parametrize("bad", [".", "..", "..."])
def test_klient_nuqtali_kalit_hech_qayerda_otmaydi(assistant, agent, bad):
    """`_SAFE_KEY` (suhbat, hujjat, fayl kalitlari): faqat nuqtadan iborat kalit
    yo'lga tushmaydi - izohdagi va'da endi haqiqat."""
    for call in (lambda: assistant.fetch_doc(bad), lambda: assistant.get_action(bad),
                 lambda: AssistantClient._chat_path(bad)):
        with pytest.raises(AssistantError) as exc:
            call()
        assert exc.value.status == 400
    assert agent.calls == []


@pytest.mark.parametrize("bad", ["", "HRM", "a/b", "..", "a.b", "x" * 41])
def test_klient_yaroqsiz_platforma_kaliti_xizmatga_bormaydi(assistant, agent, bad):
    with pytest.raises(AssistantError) as exc:
        assistant.set_platform(bad, user_id=ADMIN_ID, enabled=True)
    assert exc.value.status == 400
    assert agent.calls == []


@pytest.mark.parametrize("call", [
    lambda a: a.list_memory(user_id=""),
    lambda a: a.clear_memory(user_id="  "),
    lambda a: a.delete_memory_item("m1", user_id=""),
    lambda a: a.list_platforms(user_id=""),
    lambda a: a.set_platform("hrm", user_id="", enabled=False),
])
def test_klient_egasiz_sorov_xizmatga_bormaydi(assistant, agent, call):
    """Bo'sh `user_id` bilan "hammasini unut" - xizmatning tekshiruviga
    qoldirilmaydi."""
    with pytest.raises(AssistantError) as exc:
        call(assistant)
    assert exc.value.status == 400
    assert agent.calls == []


def test_klient_xotira_xatosida_tana_yoq(assistant, agent):
    """Xotira yo'llarida xizmat xato tanasi xato matniga tushmaydi (u jurnal
    va `api_calls.error` ga boradi)."""
    agent.fail = 500
    agent.fail_body = {"detail": f"bad item: {PRIVATE}"}
    with pytest.raises(AssistantError) as exc:
        assistant.list_memory(user_id=ADMIN_ID)
    assert PRIVATE not in str(exc.value)
    assert exc.value.status == 502


def test_klient_platforma_xatosida_sir_yashiriladi(assistant, agent):
    agent.fail = 500
    agent.fail_body = {"detail": f"secret was {SECRET}"}
    with pytest.raises(AssistantError) as exc:
        assistant.list_platforms(user_id=ADMIN_ID)
    assert SECRET not in str(exc.value)


# --- API: kimlik va ajratish -----------------------------------------------------------


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/assistant/memory"),
    ("DELETE", "/api/v1/assistant/memory/m1"),
    ("DELETE", "/api/v1/assistant/memory?confirm=forget-all"),
    ("GET", "/api/v1/assistant/platforms"),
    ("PUT", "/api/v1/assistant/platforms/hrm"),
])
def test_api_tokensiz_401(api, agent, method, path):
    response = api.request(method, path, json={"enabled": False} if method == "PUT" else None)
    assert response.status_code == 401
    assert agent.calls == []


def test_api_xotira_royxati_kimlik_serverdan(api, auth, user_auth, agent):
    admin = api.get("/api/v1/assistant/memory", headers=auth)
    assert admin.status_code == 200, admin.text
    body = admin.json()
    assert set(body) == MEMORY_LIST_FIELDS
    assert body["count"] == 2 and [i["id"] for i in body["items"]] == ["m1", "h3f2a"]
    assert all(set(i) == MEMORY_ITEM_FIELDS for i in body["items"])
    assert body["items"][0]["created_at"] == "2026-10-09T08:00:00Z"
    # CRM tartibida vaqt yo'q: xizmatning `""` i UI uchun `null`.
    assert body["items"][1]["created_at"] is None and body["items"][1]["updated_at"] is None
    assert admin.headers["Cache-Control"] == "private, no-store"

    demo = api.get("/api/v1/assistant/memory", headers=user_auth).json()
    assert [i["id"] for i in demo["items"]] == ["m2"]
    assert [c["query"]["user_id"] for c in agent.calls] == [ADMIN_ID, DEMO_ID]


def test_api_sorovdagi_user_id_etiborsiz(api, auth, agent):
    """Admin `?user_id=venera:2` yuborsa ham - O'Z xotirasini oladi."""
    body = api.get(f"/api/v1/assistant/memory?user_id={DEMO_ID}", headers=auth).json()
    assert [i["id"] for i in body["items"]] == ["m1", "h3f2a"]
    api.get(f"/api/v1/assistant/platforms?user_id={DEMO_ID}", headers=auth)
    api.delete(f"/api/v1/assistant/memory/m1?user_id={DEMO_ID}", headers=auth)
    assert {c["query"]["user_id"] for c in agent.calls} == {ADMIN_ID}
    assert [i["id"] for i in agent.memory[DEMO_ID]] == ["m2"], "boshqa odamning xotirasi joyida"


def test_api_bitta_bandni_unutish(api, auth, agent):
    response = api.delete("/api/v1/assistant/memory/m1", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": ["m1"], "status": "deleted"}
    assert [i["id"] for i in agent.memory[ADMIN_ID]] == ["h3f2a"]
    assert agent.calls[0]["method"] == "DELETE"


def test_api_boshqa_odamning_bandi_404(api, auth, agent):
    """Demo'ning `m2` kaliti adminga 404 - yo'q band bilan bir xil javob."""
    response = api.delete("/api/v1/assistant/memory/m2", headers=auth)
    assert response.status_code == 404
    body = response.json()
    assert set(body) == ERROR_FIELDS and body["code"] == "memory_not_found"
    assert [i["id"] for i in agent.memory[DEMO_ID]] == ["m2"]
    missing = api.delete("/api/v1/assistant/memory/m999", headers=auth).json()
    assert (missing["code"], missing["message"]) == (body["code"], body["message"])


def test_api_yaroqsiz_band_kaliti_400(api, auth, agent):
    response = api.delete("/api/v1/assistant/memory/a%20b", headers=auth)
    assert response.status_code == 400 and response.json()["code"] == "invalid_id"
    # Kodlangan nuqtalar: biror hop `/api/memory/.` ni `/api/memory/` ga
    # normallashtirsa, tasdiqsiz "hammasini unutish" bo'lib qolardi.
    for dots in ("%2E", "%2E%2E", "%2e%2e%2e"):
        response = api.delete(f"/api/v1/assistant/memory/{dots}", headers=auth)
        assert response.status_code == 400, dots
        assert response.json()["code"] == "invalid_id"
    assert len(agent.memory[ADMIN_ID]) == 2
    assert api.delete("/api/v1/assistant/memory/" + "x" * 129, headers=auth).status_code == 422
    assert agent.calls == []


# --- API: hammasini unutish ------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "?confirm=", "?confirm=true", "?confirm=1",
                                   "?confirm=FORGET-ALL", "?confirm=forget-all%20"])
def test_api_hammasini_unutish_tasdiqsiz_400(api, auth, agent, query):
    response = api.delete(f"/api/v1/assistant/memory{query}", headers=auth)
    assert response.status_code == 400
    body = response.json()
    assert set(body) == ERROR_FIELDS and body["code"] == "confirm_required"
    assert agent.calls == [], "tasdiqsiz so'rov xizmatga BORMAYDI"
    assert len(agent.memory[ADMIN_ID]) == 2


def test_api_hammasini_unutish_faqat_ozini(api, auth, user_auth, agent):
    response = api.delete("/api/v1/assistant/memory?confirm=forget-all", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": ["m1", "h3f2a"], "status": "deleted"}
    assert ADMIN_ID not in agent.memory
    assert [i["id"] for i in agent.memory[DEMO_ID]] == ["m2"], "boshqa odamniki joyida"
    call = agent.calls[0]
    assert (call["method"], call["path"], call["query"]) == (
        "DELETE", "/api/memory", {"user_id": ADMIN_ID})
    # Takror - bo'sh, xato emas.
    again = api.delete("/api/v1/assistant/memory?confirm=forget-all", headers=auth).json()
    assert again == {"deleted": [], "status": "empty"}
    assert api.get("/api/v1/assistant/memory", headers=auth).json() == {"items": [], "count": 0}


def test_api_hammasini_unutish_tanadagi_tasdiq_yetmaydi(api, auth, agent):
    """Tasdiq faqat so'rov satrida: tanadagi `confirm` hisobga olinmaydi."""
    response = api.request("DELETE", "/api/v1/assistant/memory", headers=auth,
                           json={"confirm": "forget-all"})
    assert response.status_code == 400 and response.json()["code"] == "confirm_required"
    assert agent.calls == []


# --- API: platformalar -----------------------------------------------------------------


def test_api_platformalar_royxati(api, auth, agent):
    response = api.get("/api/v1/assistant/platforms", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PLATFORM_LIST_FIELDS
    assert [p["id"] for p in body["platforms"]] == PLATFORM_IDS, "tartib xizmatniki"
    assert all(set(p) == PLATFORM_FIELDS for p in body["platforms"])
    superapp = next(p for p in body["platforms"] if p["id"] == "superapp")
    assert (superapp["available"], superapp["user_enabled"], superapp["enabled"]) == (False, True, False)
    hrm = body["platforms"][0]
    assert hrm["needs_login"] is True and hrm["kind"] == "live"
    assert agent.calls[0]["query"] == {"user_id": ADMIN_ID}


def test_api_platforma_kaliti_faqat_ozida(api, auth, user_auth, agent):
    response = api.put("/api/v1/assistant/platforms/biznes247", headers=auth, json={"enabled": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PLATFORM_FIELDS
    assert (body["id"], body["user_enabled"], body["enabled"]) == ("biznes247", False, False)
    call = agent.calls[0]
    assert (call["method"], call["path"], call["query"], call["body"]) == (
        "PUT", "/api/connectors/biznes247", {"user_id": ADMIN_ID}, {"enabled": False})
    demo = api.get("/api/v1/assistant/platforms", headers=user_auth).json()
    assert next(p for p in demo["platforms"] if p["id"] == "biznes247")["enabled"] is True


def test_api_server_ochirgan_platforma_yoqilmaydi(api, auth, agent):
    body = api.put("/api/v1/assistant/platforms/superapp", headers=auth, json={"enabled": True}).json()
    assert (body["available"], body["user_enabled"], body["enabled"]) == (False, True, False)


@pytest.mark.parametrize("payload", [
    {"enabled": False, "user_id": DEMO_ID},
    {"enabled": "false"},
    {"enabled": 0},
    {"enabled": None},
    {},
])
def test_api_platforma_tanasi_qattiq(api, auth, agent, payload):
    """Faqat `{"enabled": bool}`: `user_id` tanada ham o'tmaydi, `"false"` satri
    "yoqish" bo'lib ketmaydi."""
    response = api.put("/api/v1/assistant/platforms/hrm", headers=auth, json=payload)
    assert response.status_code == 422, payload
    assert agent.calls == []


def test_api_nomalum_platforma_404(api, auth, agent):
    response = api.put("/api/v1/assistant/platforms/telegram", headers=auth, json={"enabled": False})
    assert response.status_code == 404
    assert response.json()["code"] == "platform_not_found"


def test_api_yaroqsiz_platforma_kaliti_400(api, auth, agent):
    response = api.put("/api/v1/assistant/platforms/a.b", headers=auth, json={"enabled": False})
    assert response.status_code == 400 and response.json()["code"] == "invalid_id"
    assert agent.calls == []


# --- API: xizmat javobining shakli -------------------------------------------------------


def test_api_buzuq_bandlar_tashlanadi(api, auth, agent):
    agent.payload = {"count": 99, "items": [
        {"id": "m1", "text": "yaxshi"},
        {"id": "", "text": "kalitsiz"},
        {"text": "kalitsiz 2"},
        {"id": "m3"},
        "satr",
        {"id": "m4", "text": "turi yo'q", "kind": 5, "source": None, "created_at": "  "},
    ]}
    body = api.get("/api/v1/assistant/memory", headers=auth).json()
    assert [i["id"] for i in body["items"]] == ["m1", "m4"]
    assert body["count"] == 2, "soni - haqiqatda qaytarilgani"
    assert body["items"][1] == {"id": "m4", "text": "turi yo'q", "kind": "", "source": "",
                                "created_at": None, "updated_at": None}


def test_api_bosh_matnli_band_tashlanadi(api, auth, agent):
    """Matni bo'sh yoki faqat bo'shliq - web ham tashlaydi: `count` ekrandagi bilan teng."""
    agent.payload = {"count": 3, "items": [
        {"id": "m1", "text": "  "},
        {"id": "m2", "text": "\n\t"},
        {"id": "m3", "text": "Qisqa javob"},
    ]}
    body = api.get("/api/v1/assistant/memory", headers=auth).json()
    assert [i["id"] for i in body["items"]] == ["m3"] and body["count"] == 1


def test_api_platforma_maydonlari_toldiriladi(api, auth, agent):
    agent.payload = {"connectors": [{"id": "dwh", "available": True, "user_enabled": False},
                                    {"name": "kalitsiz"}, 7]}
    body = api.get("/api/v1/assistant/platforms", headers=auth).json()
    assert body["platforms"] == [{
        "id": "dwh", "name": "dwh", "description": "", "kind": "", "needs_login": False,
        "available": True, "user_enabled": False, "enabled": False,
    }]


def test_api_kalit_javobida_platforma_yoq_502(api, auth, agent):
    agent.payload = {"ok": True}
    response = api.put("/api/v1/assistant/platforms/hrm", headers=auth, json={"enabled": True})
    assert response.status_code == 502 and response.json()["code"] == "upstream_error"


# --- API: xatolar ------------------------------------------------------------------------


@pytest.mark.parametrize("failure,status,code", [
    (500, 502, "upstream_error"),
    (401, 502, "upstream_error"),          # bizning ilova siri - sozlama xatosi, sessiya EMAS
    (403, 502, "upstream_error"),
    (422, 502, "upstream_error"),
    (404, 502, "upstream_error"),          # ro'yxat yo'li yo'q = xizmat eski
    (503, 503, "upstream_unavailable"),
    (urllib.error.URLError("connection refused"), 503, "upstream_unavailable"),
    (ConnectionResetError("reset"), 503, "upstream_unavailable"),
    (socket.timeout("timed out"), 504, "upstream_timeout"),
    (TimeoutError("timed out"), 504, "upstream_timeout"),
])
@pytest.mark.parametrize("path", ["/api/v1/assistant/memory", "/api/v1/assistant/platforms"])
def test_api_xizmat_xatolari(api, auth, agent, failure, status, code, path):
    agent.fail = failure
    response = api.get(path, headers=auth)
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == ERROR_FIELDS and body["code"] == code
    assert "assistant.test" not in response.text and SECRET not in response.text


def test_api_buzuq_json_502(api, auth, agent):
    agent.raw = b"<html>nginx</html>"
    response = api.get("/api/v1/assistant/memory", headers=auth)
    assert response.status_code == 502 and response.json()["code"] == "upstream_error"


def test_api_sozlanmagan_503(api, auth, agent, monkeypatch):
    monkeypatch.setattr(chat_api, "_assistant", AssistantClient(BASE, "", "", timeout=5))
    response = api.get("/api/v1/assistant/platforms", headers=auth)
    assert response.status_code == 503 and response.json()["code"] == "not_configured"
    assert agent.calls == []


def test_api_sozlamalar_chegarasi_klientga_yetadi(api, auth, agent, monkeypatch):
    """Oqimning 120 s i emas - `HRM_ASSISTANT_SETTINGS_TIMEOUT`."""
    monkeypatch.setattr(settings, "hrm_assistant_settings_timeout", 3.5)
    api.get("/api/v1/assistant/memory", headers=auth)
    api.delete("/api/v1/assistant/memory/m1", headers=auth)
    api.delete("/api/v1/assistant/memory?confirm=forget-all", headers=auth)
    api.get("/api/v1/assistant/platforms", headers=auth)
    api.put("/api/v1/assistant/platforms/hrm", headers=auth, json={"enabled": False})
    assert [c["timeout"] for c in agent.calls] == [3.5] * 5


def test_sozlamalar_chegarasi_default():
    assert type(settings).model_fields["hrm_assistant_settings_timeout"].default == 15.0


# --- API: chegaralar ---------------------------------------------------------------------


def test_api_oqish_chegarasi_429(api, auth, user_auth, agent, monkeypatch):
    monkeypatch.setattr(extras, "_read", RateLimiter(2, 60.0))
    assert api.get("/api/v1/assistant/memory", headers=auth).status_code == 200
    assert api.get("/api/v1/assistant/platforms", headers=auth).status_code == 200
    response = api.get("/api/v1/assistant/memory", headers=auth)
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1
    assert len(agent.calls) == 2, "chegaradan oshgan so'rov xizmatga bormaydi"
    # Chegara odam bo'yicha: boshqasi ishlayveradi.
    assert api.get("/api/v1/assistant/memory", headers=user_auth).status_code == 200


def test_api_yozish_chegarasi_429(api, auth, agent, monkeypatch):
    monkeypatch.setattr(extras, "_write", RateLimiter(1, 60.0))
    assert api.put("/api/v1/assistant/platforms/hrm", headers=auth,
                   json={"enabled": False}).status_code == 200
    response = api.delete("/api/v1/assistant/memory/m1", headers=auth)
    assert response.status_code == 429 and response.json()["code"] == "rate_limited"
    assert len(agent.calls) == 1


def test_api_hammasini_unutish_soatiga_5(api, auth, agent):
    assert extras.FORGET_ALL_LIMIT == (5, 3600.0)
    for _ in range(3):   # tasdiqsiz urinishlar chegarani yemaydi
        assert api.delete("/api/v1/assistant/memory", headers=auth).status_code == 400
    for _ in range(5):
        assert api.delete("/api/v1/assistant/memory?confirm=forget-all",
                          headers=auth).status_code == 200
    response = api.delete("/api/v1/assistant/memory?confirm=forget-all", headers=auth)
    assert response.status_code == 429 and "Retry-After" in response.headers
    assert len(agent.calls) == 5


@pytest.mark.parametrize("failure", [502, 503, socket.timeout("timed out")])
def test_api_hammasini_unutish_xizmat_xatosi_chegarani_yemaydi(api, auth, agent, failure):
    """Agent qayta ishga tushayotganda 5 ta 502/503/504 odamni bir soat
    "Hammasini unutish" dan mahrum qilmasin: xizmat nosozligi joyni qaytaradi."""
    agent.fail = failure
    for _ in range(7):
        response = api.delete("/api/v1/assistant/memory?confirm=forget-all", headers=auth)
        assert response.status_code in (502, 503, 504), response.text
    agent.fail = None
    response = api.delete("/api/v1/assistant/memory?confirm=forget-all", headers=auth)
    assert response.status_code == 200, "chegara yeyilmagan"


def test_api_yozish_chegarasi_bizning_raddan_qaytmaydi(api, auth, agent, monkeypatch):
    """Xizmatning 404 i (yo'q band) - xizmat nosozligi EMAS: joy qaytarilmaydi,
    aks holda tsikl chegarani cheksiz urardi."""
    monkeypatch.setattr(extras, "_write", RateLimiter(2, 60.0))
    assert api.delete("/api/v1/assistant/memory/m404", headers=auth).status_code == 404
    agent.fail = 503
    assert api.delete("/api/v1/assistant/memory/m1", headers=auth).status_code == 503
    agent.fail = None
    assert api.delete("/api/v1/assistant/memory/m1", headers=auth).status_code == 200
    assert api.delete("/api/v1/assistant/memory/h3f2a", headers=auth).status_code == 429


# --- jurnal va hisob ---------------------------------------------------------------------


def test_xotira_matni_jurnalga_tushmaydi(api, auth, agent, caplog):
    caplog.set_level(logging.DEBUG)
    assert api.get("/api/v1/assistant/memory", headers=auth).status_code == 200
    assert api.delete("/api/v1/assistant/memory/m1", headers=auth).status_code == 200
    agent.fail = 500
    agent.fail_body = {"detail": PRIVATE}
    assert api.get("/api/v1/assistant/memory", headers=auth).status_code == 502
    assert PRIVATE not in caplog.text
    assert "Malika" not in caplog.text
    assert "m1" in caplog.text, "kalit esa yoziladi - kim nimani o'chirgani izlanadi"


def test_hisobga_yoziladi_matnsiz(api, auth, agent):
    """Har chaqiruv `api_calls` da (xizmat `assistant`, amal nomi bilan),
    xato matnida xotira yo'q."""
    api.get("/api/v1/assistant/memory", headers={**auth, "X-Venera-Client": "web"})
    api.delete("/api/v1/assistant/memory/m1", headers=auth)
    api.delete("/api/v1/assistant/memory?confirm=forget-all", headers=auth)
    api.get("/api/v1/assistant/platforms", headers=auth)
    api.put("/api/v1/assistant/platforms/dwh", headers=auth, json={"enabled": False})
    agent.fail = 500
    agent.fail_body = {"detail": PRIVATE}
    api.get("/api/v1/assistant/memory", headers=auth)
    calls = _rows("SELECT op, status, http_status, actor_id, channel, error FROM api_calls "
                  "WHERE service = 'assistant' ORDER BY id")
    assert [(c["op"], c["status"]) for c in calls] == [
        ("memory.list", "ok"), ("memory.delete", "ok"), ("memory.clear", "ok"),
        ("platforms.list", "ok"), ("platforms.set", "ok"), ("memory.list", "error"),
    ]
    assert calls[0]["channel"] == "web" and all(c["actor_id"] == 1 for c in calls)
    assert calls[-1]["http_status"] == 500
    assert all(PRIVATE not in (c["error"] or "") for c in calls)


def test_platforma_xatosida_ham_tana_yozilmaydi(api, auth, agent, caplog):
    """`/assistant/*` ning hammasiga bitta qoida: xizmat xato tanasi jurnalga ham,
    hisobga ham tushmaydi (platforma yo'llari ham `quiet`)."""
    caplog.set_level(logging.DEBUG)
    agent.fail = 500
    agent.fail_body = {"detail": PRIVATE}
    assert api.get("/api/v1/assistant/platforms", headers=auth).status_code == 502
    assert api.put("/api/v1/assistant/platforms/dwh", headers=auth,
                   json={"enabled": False}).status_code == 502
    assert "Malika" not in caplog.text
    calls = _rows("SELECT error FROM api_calls WHERE service = 'assistant' ORDER BY id")
    assert calls and all("Malika" not in (c["error"] or "") for c in calls)


def test_json_yollari_yonaltirishga_ergashmaydi(monkeypatch):
    """30x - xato (502), sir esa yangi manzilga KO'CHMAYDI. Haqiqiy `urllib`
    va mahalliy server: yo'naltirish ishlovchisi soxta emas."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.path)
            if self.path.startswith("/api/memory"):
                self.send_response(302)
                self.send_header("Location", "/leak")
                self.end_headers()
                return
            # Yo'naltirilgan so'rov bu yerga kelsa - sir ko'chgan bo'lardi.
            seen.append(self.headers.get("X-Client-Secret") or "")
            body = b'{"items": [], "count": 0}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # jim
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = AssistantClient(f"http://127.0.0.1:{server.server_address[1]}", "barno",
                                 SECRET, timeout=5)
        with pytest.raises(AssistantError) as exc:
            client.list_memory(user_id=ADMIN_ID, timeout=5)
        assert exc.value.status == 502
        assert SECRET not in str(exc.value)
        assert seen == [f"/api/memory?user_id={urllib.parse.quote(ADMIN_ID)}"], seen
    finally:
        server.shutdown()
        server.server_close()

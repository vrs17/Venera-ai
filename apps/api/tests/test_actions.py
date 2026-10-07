"""Yozuv amallari: taklif kadri, tasdiqlash va rad etish.

Yuqoridagi xizmat chaqirilmaydi - `build_opener` soxta (`test_assistant.py`
dagi kabi). Tekshiriladigan mantiq: kimlik va token SERVERDAN qo'yiladi,
ichki havolalar brauzerga tushmaydi, xatolar tushunarli xabarga o'giriladi.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from app.api.v1 import chat as chat_api
from app.services.integrations import assistant as mod
from app.services.integrations.assistant import AssistantClient, AssistantError

BASE = "http://assistant.test"
TOKEN = "bCqctM12doIGngZiBVLO4t1ZydzGNGVL"

# types.ts: ActionResult
RESULT_FIELDS = {"token", "status", "summary", "operation", "connector", "ok", "error",
                 "request_id", "result"}


class _JsonResponse:
    def __init__(self, payload: dict, headers: dict | None = None) -> None:
        self._raw = json.dumps(payload).encode()
        self.headers = headers or {"X-Request-Id": "served-9"}

    def read(self, size: int = -1) -> bytes:
        raw, self._raw = self._raw, b""
        return raw

    def close(self) -> None:
        return None


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.status: int | None = None
        self.state = "pending"

    def open(self, request, timeout=None):
        path = "/" + request.full_url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append({
            "path": path,
            "method": request.get_method(),
            "body": json.loads(request.data) if request.data else None,
            "client_id": request.get_header("X-client-id"),
            "client_secret": request.get_header("X-client-secret"),
        })
        if self.status:
            raise urllib.error.HTTPError(f"{BASE}{path}", self.status, "xato", {},
                                         io.BytesIO(json.dumps({"detail": "yo'q"}).encode()))
        if path.endswith("/confirm"):
            self.state = "executed"
            return _JsonResponse({"token": TOKEN, "status": "executed", "summary": "Vaqt yozildi",
                                  "operation": "worklog", "connector": "crm", "ok": True,
                                  "result": {"key": "DVSIB-231"}})
        if path.endswith("/cancel"):
            self.state = "cancelled"
            return _JsonResponse({"token": TOKEN, "status": "cancelled", "summary": "Vaqt yozish"})
        return _JsonResponse({"token": TOKEN, "status": self.state, "summary": "Vaqt yozish"})


@pytest.fixture
def server(monkeypatch):
    fake = FakeActions()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    return fake


@pytest.fixture
def assistant(server) -> AssistantClient:
    return AssistantClient(BASE, "venera", "sir", timeout=5, max_concurrent=2)


@pytest.fixture
def api(monkeypatch, assistant, client):
    """Endpoint soxta xizmat ustida; odamning tokenlari ham soxta."""
    monkeypatch.setattr(chat_api, "_assistant", assistant)
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {"crm": "crm-jwt", "hrm": ""})
    return client


# --- klient ------------------------------------------------------------------


def test_tasdiqlash_kimlik_va_token_bilan(assistant, server):
    result = assistant.confirm_action(TOKEN, user_id="venera:1", tokens={"crm": "c", "hrm": ""})
    assert result["status"] == "executed"
    assert result["result"] == {"key": "DVSIB-231"}
    assert result["request_id"] == "served-9", "audit kaliti xizmatniki"
    call = server.calls[0]
    assert call["path"] == f"/api/actions/{TOKEN}/confirm"
    assert call["method"] == "POST"
    assert call["client_id"] == "venera" and call["client_secret"] == "sir"
    # Bo'sh token YUBORILMAYDI - "sessiya bor, lekin yaroqsiz" deb tushunilmasin.
    assert call["body"] == {"user_id": "venera:1", "tokens": {"crm": "c"}}


def test_rad_etish(assistant, server):
    assert assistant.cancel_action(TOKEN, user_id="venera:1")["status"] == "cancelled"
    assert server.calls[0]["path"].endswith("/cancel")
    assert server.calls[0]["body"] == {"user_id": "venera:1"}


def test_holat_get(assistant, server):
    assert assistant.get_action(TOKEN)["status"] == "pending"
    assert server.calls[0]["method"] == "GET"
    assert server.calls[0]["body"] is None


@pytest.mark.parametrize("bad", ["", "a/b", "../x", "x" * 129])
def test_yaroqsiz_kalit_xizmatga_bormaydi(assistant, server, bad):
    with pytest.raises(AssistantError) as exc:
        assistant.confirm_action(bad, user_id="venera:1")
    assert exc.value.status == 400
    assert server.calls == []


def test_sozlanmagan_501(server):
    empty = AssistantClient(BASE, "", "", timeout=5)
    with pytest.raises(AssistantError) as exc:
        empty.confirm_action(TOKEN, user_id="venera:1")
    assert exc.value.status == 501


# --- taklif kadri ------------------------------------------------------------


def test_taklif_kadridan_ichki_havolalar_olib_tashlanadi():
    line = json.dumps({"type": "proposal", "token": TOKEN, "summary": "Vaqt yozish",
                       "confirm_url": "http://10.10.50.4:8080/api/actions/x/confirm",
                       "cancel_url": "http://10.10.50.4:8080/api/actions/x/cancel"}).encode()
    frame = mod._clean_frame(line, BASE)
    assert frame == {"type": "proposal", "token": TOKEN, "summary": "Vaqt yozish"}


def test_taklif_kadri_ichma_ich_bolsa_ham():
    line = json.dumps({"type": "proposal", "proposal": {
        "token": TOKEN, "confirm_url": "http://10.10.50.4:8080/x", "changes": []}}).encode()
    frame = mod._clean_frame(line, BASE)
    assert frame == {"type": "proposal", "proposal": {"token": TOKEN, "changes": []}}


# --- API ---------------------------------------------------------------------


def test_api_tokensiz_401(client):
    assert client.post(f"/api/v1/actions/{TOKEN}/confirm").status_code == 401


def test_api_tasdiqlash_kimlik_serverdan(api, auth, server):
    response = api.post(f"/api/v1/actions/{TOKEN}/confirm", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == RESULT_FIELDS
    assert body["status"] == "executed" and body["ok"] is True
    # Brauzer hech narsa yubormadi; kimlik va token serverdan.
    assert server.calls[0]["body"] == {"user_id": "venera:1", "tokens": {"crm": "crm-jwt"}}


def test_api_rad_etish_va_holat(api, auth, server):
    assert api.post(f"/api/v1/actions/{TOKEN}/cancel", headers=auth).json()["status"] == "cancelled"
    assert api.get(f"/api/v1/actions/{TOKEN}", headers=auth).json()["status"] == "cancelled"


def test_api_topilmagan_taklif_404(api, auth, server):
    server.status = 404
    response = api.post(f"/api/v1/actions/{TOKEN}/confirm", headers=auth)
    assert response.status_code == 404
    assert "muddati" in response.json()["message"]


def test_api_muddati_otgan_taklif_410(api, auth, server):
    # Xizmat 2026-10 dan muddati o'tgan taklifga aniq 410 beradi - bu "xizmat
    # javob bermadi" (502) EMAS, odamga nima qilish kerakligi aytiladi.
    server.status = 410
    response = api.post(f"/api/v1/actions/{TOKEN}/confirm", headers=auth)
    assert response.status_code == 410
    assert "muddati tugagan" in response.json()["message"]


def test_api_xizmat_xatosi_502(api, auth, server):
    server.status = 500
    response = api.post(f"/api/v1/actions/{TOKEN}/confirm", headers=auth)
    assert response.status_code == 502
    assert "10.10.50" not in response.text

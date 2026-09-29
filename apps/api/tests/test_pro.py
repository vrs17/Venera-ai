""""Pro" rejimi: `mode` ning o'tishi, `pro` blokining qaytishi va byudjet.

Yuqoridagi xizmat chaqirilmaydi - `build_opener` soxta (`test_actions.py`
dagi kabi). Tekshiriladigan mantiq: `pro` FAQAT so'ralganda yuboriladi,
kimlik serverdan qo'yiladi, javobdagi `pro` bloki o'zgarishsiz o'tadi va
chegaralar qotirilmaydi.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.api.v1 import chat as chat_api
from app.services.integrations.assistant import AssistantClient, AssistantError

BASE = "http://assistant.test"

QUOTA = {
    "remaining": {"day": 99, "week": 199, "month": 499},
    "limits": {"day": 100, "week": 200, "month": 500},
    "used": {"day": 1, "week": 1, "month": 1},
}
PRO_BLOCK = {"requested": True, "used": True, "calls": 1,
             "remaining": {"day": 99, "week": 199, "month": 499},
             "limits": {"day": 100, "week": 200, "month": 500}}

# types.ts: ProQuota / ProWindows
QUOTA_FIELDS = {"remaining", "limits", "used"}
WINDOW_FIELDS = {"day", "week", "month"}


def frame(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False).encode("utf-8") + b"\n"


class _Ndjson:
    def __init__(self, lines) -> None:
        self._lines = list(lines)
        self.headers = {"X-Request-Id": "served-pro"}

    def readline(self, limit: int = -1) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def read(self, size: int = -1) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def close(self) -> None:
        return None


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.status: int | None = None
        #: Xizmat "Pro" berdimi - `done` kadridagi blok shunga qarab.
        self.pro = PRO_BLOCK

    def open(self, request, timeout=None):
        parts = urllib.parse.urlsplit(request.full_url)
        body = json.loads(request.data) if request.data else None
        self.calls.append({"path": parts.path,
                           "query": dict(urllib.parse.parse_qsl(parts.query)),
                           "method": request.get_method(), "body": body})
        if self.status:
            raise urllib.error.HTTPError(request.full_url, self.status, "xato", {},
                                         io.BytesIO(b'{"detail":"yo\'q"}'))
        if parts.path == "/api/pro/quota":
            raw = json.dumps(QUOTA).encode()
            return _Ndjson([raw])
        done = {"type": "done", "route": "rules", "request_id": "r-1"}
        if body and body.get("mode") == "pro":
            done["pro"] = self.pro
        return _Ndjson([frame(type="token", text="Javob"), frame(**done)])


@pytest.fixture
def server(monkeypatch):
    fake = FakeService()

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
    monkeypatch.setattr(chat_api, "_assistant", assistant)
    monkeypatch.setattr(chat_api, "_live_tokens", lambda user: {})
    return client


def _frames(stream) -> list[dict]:
    return [json.loads(line) for line in stream.frames]


# --- mode ---------------------------------------------------------------


def test_standard_yuborilmaydi(assistant, server):
    """`standard` xizmatning o'z default'i - ortiqcha maydon qo'shilmaydi."""
    _frames(assistant.stream("savol", user_id="venera:1"))
    assert "mode" not in server.calls[0]["body"]


def test_pro_yuboriladi(assistant, server):
    _frames(assistant.stream("savol", user_id="venera:1", mode="pro"))
    assert server.calls[0]["body"]["mode"] == "pro"


def test_pro_bloki_done_kadrida_ozgarishsiz_keladi(assistant, server):
    frames = _frames(assistant.stream("savol", user_id="venera:1", mode="pro"))
    done = frames[-1]
    assert done["type"] == "done"
    assert done["pro"] == PRO_BLOCK, "blok o'zgarishsiz o'tishi kerak"


def test_standard_javobida_pro_bloki_yoq(assistant, server):
    assert "pro" not in _frames(assistant.stream("savol", user_id="venera:1"))[-1]


def test_berilmagan_pro_sababi_bilan_keladi(assistant, server):
    """Byudjet tugagan: javob BOR, blokda esa sabab."""
    server.pro = {"requested": True, "used": False, "calls": 0, "reason": "limit",
                  "remaining": {"day": 0, "week": 10, "month": 90},
                  "limits": {"day": 100, "week": 200, "month": 500}}
    done = _frames(assistant.stream("savol", user_id="venera:1", mode="pro"))[-1]
    assert done["pro"]["used"] is False and done["pro"]["reason"] == "limit"


# --- API: mode klientdan, kimlik serverdan ------------------------------


def test_api_pro_sorovdan_otadi(api, auth, server):
    response = api.post("/api/v1/chat/stream",
                        json={"question": "savol", "mode": "pro"}, headers=auth)
    assert response.status_code == 200, response.text
    body = server.calls[0]["body"]
    assert body["mode"] == "pro"
    assert body["user_id"] == "venera:1", "kimlik SERVERDAN"


def test_api_default_standard(api, auth, server):
    api.post("/api/v1/chat/stream", json={"question": "savol"}, headers=auth)
    assert "mode" not in server.calls[0]["body"]


def test_api_notanish_rejim_422(api, auth, server):
    """Notanish qiymat xizmatga BORMAYDI."""
    response = api.post("/api/v1/chat/stream",
                        json={"question": "savol", "mode": "turbo"}, headers=auth)
    assert response.status_code == 422
    assert server.calls == []


# --- byudjet ------------------------------------------------------------


def test_byudjet_kimlik_bilan_soraladi(assistant, server):
    result = assistant.pro_quota(user_id="venera:1")
    assert result["remaining"] == QUOTA["remaining"]
    call = server.calls[0]
    assert call["path"] == "/api/pro/quota"
    assert call["query"] == {"user_id": "venera:1"}
    assert call["method"] == "GET"


def test_api_byudjet_types_ts_ga_mos(api, auth, server):
    body = api.get("/api/v1/pro/quota", headers=auth).json()
    assert set(body) == QUOTA_FIELDS
    for window in QUOTA_FIELDS:
        assert set(body[window]) == WINDOW_FIELDS
    assert body["limits"]["day"] == 100, "chegara xizmatdan keladi, qotirilmagan"
    assert server.calls[0]["query"] == {"user_id": "venera:1"}


def test_api_byudjet_tokensiz_401(client):
    assert client.get("/api/v1/pro/quota").status_code == 401


def test_api_byudjet_xizmat_xatosi_502(api, auth, server):
    server.status = 500
    response = api.get("/api/v1/pro/quota", headers=auth)
    assert response.status_code == 502
    assert "assistant.test" not in response.text

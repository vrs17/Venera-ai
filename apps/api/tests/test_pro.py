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
QUOTA_FIELDS = {"remaining", "limits", "used", "engine", "available"}
QUOTA_WINDOWS = ("remaining", "limits", "used")
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
    _frames(assistant.stream("savol", user_id="venera:1", mode="pro", engine="v2"))
    assert server.calls[0]["body"]["mode"] == "pro"
    assert server.calls[0]["path"] == "/api/v2/chat/stream"


@pytest.mark.parametrize("engine,path", [("v1", "/api/v1/chat/stream"),
                                         ("", "/api/chat/stream")])
def test_pro_v2_dan_boshqa_dvigatelga_yuborilmaydi(assistant, server, engine, path):
    """Ikkinchi to'r: `chat.py` dan o'tib kelgan bo'lsa ham, pulli rejim
    "Pro" yo'q dvigatelga hech qachon ketmaydi."""
    _frames(assistant.stream("savol", user_id="venera:1", mode="pro", engine=engine))
    assert server.calls[0]["path"] == path
    assert "mode" not in server.calls[0]["body"]


def test_pro_bloki_done_kadrida_ozgarishsiz_keladi(assistant, server):
    frames = _frames(assistant.stream("savol", user_id="venera:1", mode="pro", engine="v2"))
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
    done = _frames(assistant.stream("savol", user_id="venera:1", mode="pro", engine="v2"))[-1]
    assert done["pro"]["used"] is False and done["pro"]["reason"] == "limit"


def test_soralmagan_pro_bloki_otmaydi(assistant, server, monkeypatch):
    """Xizmat "Pro" so'ralmagan javobga ham blok qo'shsa - brauzerga O'TMAYDI:
    aks holda klient "Pro ishlatildi" belgisini ko'rsatardi."""
    real = server.open

    def always_pro(request, timeout=None):
        response = real(request, timeout)
        response._lines = [line.replace(b'"route": "rules"', b'"route": "rules", "pro": {"used": true}')
                           if b'"done"' in line else line for line in response._lines]
        return response

    monkeypatch.setattr(server, "open", always_pro)
    done = _frames(assistant.stream("savol", user_id="venera:1", mode="pro", engine="v1"))[-1]
    assert done["type"] == "done" and "pro" not in done


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
    for window in QUOTA_WINDOWS:
        assert set(body[window]) == WINDOW_FIELDS
    assert body["limits"]["day"] == 100, "chegara xizmatdan keladi, qotirilmagan"
    assert (body["engine"], body["available"]) == ("v2", True)
    assert server.calls[0]["query"] == {"user_id": "venera:1"}


def test_api_byudjet_tokensiz_401(client):
    assert client.get("/api/v1/pro/quota").status_code == 401


def test_api_byudjet_xizmat_xatosi_502(api, auth, server):
    server.status = 500
    response = api.get("/api/v1/pro/quota", headers=auth)
    assert response.status_code == 502
    assert "assistant.test" not in response.text


# --- "Pro" faqat v2 dvigatelida (kanal bo'yicha) ---------------------------


def _engines(monkeypatch, default: str = "v2", by_channel: str = "") -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "hrm_assistant_engine", default)
    monkeypatch.setattr(settings, "hrm_assistant_engine_by_channel", by_channel)


def test_api_byudjet_v1_kanalda_mavjud_emas_va_xizmatga_bormaydi(api, auth, server, monkeypatch):
    """Mini app `v1` da: byudjet so'ralmaydi (xizmatga BORILMAYDI), javob 200 va
    `available: false` - klient "Pro" tugmasini ko'rsatmaydi."""
    _engines(monkeypatch, by_channel="miniapp=v1")
    body = api.get("/api/v1/pro/quota", headers={**auth, "X-Venera-Client": "miniapp"}).json()
    assert set(body) == QUOTA_FIELDS
    assert (body["engine"], body["available"]) == ("v1", False)
    assert body["remaining"] == {"day": 0, "week": 0, "month": 0}
    assert server.calls == [], "v1 kanal uchun xizmatga borilmaydi"
    # Web shu paytda ham v2 da - byudjet xizmatdan.
    web = api.get("/api/v1/pro/quota", headers={**auth, "X-Venera-Client": "web"}).json()
    assert (web["engine"], web["available"]) == ("v2", True)
    assert len(server.calls) == 1


def test_api_byudjet_versiyasiz_dvigatelda_ham_mavjud_emas(api, auth, server, monkeypatch):
    _engines(monkeypatch, default="")
    body = api.get("/api/v1/pro/quota", headers=auth).json()
    assert (body["engine"], body["available"]) == ("", False)
    assert server.calls == []


def test_api_v1_kanalda_pro_tashlanadi_va_izda_sababi_bilan(api, auth, server, monkeypatch):
    """`mode=pro` v1 kanalda: yuqoriga YUBORILMAYDI, `done` da `pro` bloki yo'q,
    savol izida esa "so'ralgan, berilmagan, sabab `engine`"."""
    from app.services import analytics

    _engines(monkeypatch, by_channel="miniapp=v1")
    response = api.post("/api/v1/chat/stream", json={"question": "savol", "mode": "pro"},
                        headers={**auth, "X-Venera-Client": "miniapp"})
    assert response.status_code == 200, response.text
    call = server.calls[0]
    assert call["path"] == "/api/v1/chat/stream"
    assert "mode" not in call["body"]
    done = [json.loads(line) for line in response.text.splitlines() if line.strip()][-1]
    assert done["type"] == "done" and "pro" not in done

    assert analytics.flush(5.0)
    db = analytics.get_db()
    turn_id = response.headers["x-venera-turn"]
    events = db.rows("SELECT type, name, payload FROM turn_events WHERE turn_id=? ORDER BY seq",
                     (turn_id,))
    [requested] = [e for e in events if e["name"] == "pro.requested"]
    [pro] = [e for e in events if e["name"] == "pro"]
    assert pro["type"] == "note"
    assert json.loads(pro["payload"]) == {"requested": True, "used": False, "calls": 0,
                                          "reason": "engine"}
    assert db.row("SELECT engine FROM turns WHERE id=?", (turn_id,))["engine"] == "v1"
    assert requested


def test_api_v2_kanalda_pro_yuboriladi_va_engine_yoziladi(api, auth, server, monkeypatch):
    from app.services import analytics

    _engines(monkeypatch, by_channel="miniapp=v1")
    response = api.post("/api/v1/chat/stream", json={"question": "savol", "mode": "pro"},
                        headers={**auth, "X-Venera-Client": "web"})
    assert response.status_code == 200
    assert server.calls[0]["path"] == "/api/v2/chat/stream"
    assert server.calls[0]["body"]["mode"] == "pro"
    done = [json.loads(line) for line in response.text.splitlines() if line.strip()][-1]
    assert done["pro"] == PRO_BLOCK
    assert analytics.flush(5.0)
    turn = analytics.get_db().row("SELECT engine FROM turns WHERE id=?",
                                  (response.headers["x-venera-turn"],))
    # `done` da `engine` yo'q - so'ralgani yoziladi.
    assert turn["engine"] == "v2"

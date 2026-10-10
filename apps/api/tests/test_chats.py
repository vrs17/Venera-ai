"""Suhbatlar tarixi: ro'yxat, ochish, nomini o'zgartirish, o'chirish, tiklash.

Yuqoridagi xizmat chaqirilmaydi - `build_opener` soxta (`test_actions.py`
dagi kabi). Tekshiriladigan mantiq: kimlik SERVERDAN qo'yiladi va so'rov
tanasida emas, so'rov satrida ketadi; kalit tekshirilib yo'lga mos
qilinadi; PATCH/DELETE/tanasiz POST to'g'ri metod bilan boradi; xatolar
tushunarli xabarga o'giriladi va ichki manzil brauzerga tushmaydi.
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
CHAT = "c-9a1f"

SUMMARY = {
    "chat_id": CHAT,
    "title": "Aktiv CRM vazifalari",
    "title_source": "auto",
    "created_at": "2026-09-17T11:30:14Z",
    "updated_at": "2026-09-17T11:32:25Z",
    "messages": 2,
}
DETAIL = {
    **{k: v for k, v in SUMMARY.items() if k != "messages"},
    "messages": [
        {"role": "user", "content": "CRMda qanday aktiv vazifalarim bor?",
         "created_at": "2026-09-17T11:30:14Z"},
        {"role": "assistant", "content": "Sizda jami 11 ta aktiv vazifa mavjud [T1].",
         "created_at": "2026-09-17T11:30:17Z"},
    ],
}

# types.ts: ChatSummary / ChatDetail / ChatMessage / ChatList / ChatDeleted
SUMMARY_FIELDS = {"chat_id", "title", "title_source", "created_at", "updated_at", "messages"}
MESSAGE_FIELDS = {"role", "content", "created_at"}
LIST_FIELDS = {"items", "limit", "offset"}
DELETED_FIELDS = {"chat_id", "status"}


class _JsonResponse:
    def __init__(self, payload: dict, headers: dict | None = None) -> None:
        self._raw = json.dumps(payload, ensure_ascii=False).encode()
        self.headers = headers or {"X-Request-Id": "served-3"}

    def read(self, size: int = -1) -> bytes:
        raw, self._raw = self._raw, b""
        return raw

    def close(self) -> None:
        return None


class FakeChats:
    """Xizmatning suhbat yo'llari - so'rovlarni yozib, javob shaklini qaytaradi."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.status: int | None = None
        self.deleted = False
        #: Ro'yxatdagi qo'shimcha suhbatlar (masalan guruhdagi CRM suhbati).
        self.extra: list[dict] = []

    def open(self, request, timeout=None):
        parts = urllib.parse.urlsplit(request.full_url)
        method = request.get_method()
        body = json.loads(request.data) if request.data else None
        self.calls.append({
            "path": parts.path,
            "query": dict(urllib.parse.parse_qsl(parts.query)),
            "method": method,
            "body": body,
            "client_id": request.get_header("X-client-id"),
            "client_secret": request.get_header("X-client-secret"),
            "accept": request.get_header("Accept"),
        })
        if self.status:
            raise urllib.error.HTTPError(
                request.full_url, self.status, "xato", {},
                io.BytesIO(json.dumps({"detail": {"code": "not_found",
                                                  "message": "No such chat for this user."}}).encode()))
        if parts.path == "/api/chats":
            query = dict(urllib.parse.parse_qsl(parts.query))
            return _JsonResponse({"items": [SUMMARY, *self.extra], "limit": int(query.get("limit", 50)),
                                  "offset": int(query.get("offset", 0))})
        if parts.path.endswith("/restore"):
            self.deleted = False
            return _JsonResponse(SUMMARY)
        if method == "PATCH":
            return _JsonResponse({**SUMMARY, "title": body["title"], "title_source": "user"})
        if method == "DELETE":
            self.deleted = True
            return _JsonResponse({"chat_id": CHAT, "status": "deleted"})
        return _JsonResponse(DETAIL)


@pytest.fixture
def server(monkeypatch):
    fake = FakeChats()

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
    """Endpoint soxta xizmat ustida."""
    monkeypatch.setattr(chat_api, "_assistant", assistant)
    return client


# --- klient ------------------------------------------------------------------


def test_royxat_kimlik_va_sahifa_sorov_satrida(assistant, server):
    result = assistant.list_chats(user_id="venera:1", limit=20, offset=40)
    assert result["items"][0]["chat_id"] == CHAT
    assert result["request_id"] == "served-3", "audit kaliti xizmatniki"
    call = server.calls[0]
    assert call["method"] == "GET" and call["path"] == "/api/chats"
    assert call["query"] == {"user_id": "venera:1", "limit": "20", "offset": "40"}
    assert call["body"] is None, "GET da tana bo'lmaydi"
    assert call["client_id"] == "venera" and call["client_secret"] == "sir"
    assert call["accept"] == "application/json"


def test_ochish(assistant, server):
    result = assistant.get_chat(CHAT, user_id="venera:1", limit=5)
    assert [m["role"] for m in result["messages"]] == ["user", "assistant"]
    call = server.calls[0]
    assert call["method"] == "GET" and call["path"] == f"/api/chats/{CHAT}"
    assert call["query"] == {"user_id": "venera:1", "limit": "5"}


def test_nomini_ozgartirish_patch_bilan(assistant, server):
    result = assistant.rename_chat(CHAT, user_id="venera:1", title="Ta'til savollari")
    assert result["title"] == "Ta'til savollari" and result["title_source"] == "user"
    call = server.calls[0]
    assert call["method"] == "PATCH"
    assert call["query"] == {"user_id": "venera:1"}
    assert call["body"] == {"title": "Ta'til savollari"}


def test_ochirish_va_tiklash(assistant, server):
    assert assistant.delete_chat(CHAT, user_id="venera:1")["status"] == "deleted"
    assert server.deleted
    assert assistant.restore_chat(CHAT, user_id="venera:1")["chat_id"] == CHAT
    assert not server.deleted
    delete, restore = server.calls
    assert delete["method"] == "DELETE" and delete["path"] == f"/api/chats/{CHAT}"
    assert delete["body"] is None
    assert restore["method"] == "POST" and restore["path"] == f"/api/chats/{CHAT}/restore"
    assert restore["body"] is None, "tiklashda tana yo'q - hujjat shunday"
    assert restore["query"] == {"user_id": "venera:1"}


def test_kalit_yolga_mos_qilinadi(assistant, server):
    """`:` ruxsat etilgan belgi, lekin yo'lda ochiq turmaydi."""
    assistant.get_chat("app:42", user_id="venera:1")
    assert server.calls[0]["path"] == "/api/chats/app%3A42"


@pytest.mark.parametrize("bad", ["", "a/b", "../x", "x y", "x" * 129])
def test_yaroqsiz_kalit_xizmatga_bormaydi(assistant, server, bad):
    with pytest.raises(AssistantError) as exc:
        assistant.get_chat(bad, user_id="venera:1")
    assert exc.value.status == 400
    assert server.calls == []


def test_sozlanmagan_501(server):
    empty = AssistantClient(BASE, "", "", timeout=5)
    with pytest.raises(AssistantError) as exc:
        empty.list_chats(user_id="venera:1")
    assert exc.value.status == 501
    assert server.calls == []


def test_xizmat_404_boshqa_odamniki_yoki_ochirilgan(assistant, server):
    server.status = 404
    with pytest.raises(AssistantError) as exc:
        assistant.get_chat(CHAT, user_id="venera:2")
    assert exc.value.status == 404


# --- API ---------------------------------------------------------------------


def test_api_tokensiz_401(client):
    assert client.get("/api/v1/chats").status_code == 401
    assert client.get(f"/api/v1/chats/{CHAT}").status_code == 401
    assert client.delete(f"/api/v1/chats/{CHAT}").status_code == 401


def test_api_royxat_kimlik_serverdan(api, auth, server):
    response = api.get("/api/v1/chats", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == LIST_FIELDS
    assert set(body["items"][0]) == SUMMARY_FIELDS
    # Brauzer hech narsa yubormadi - kimlik tokendagi admin (actor 1).
    assert server.calls[0]["query"] == {"user_id": "venera:1", "limit": "50", "offset": "0"}


def test_api_royxat_sahifa_chegarasi(api, auth, server):
    assert api.get("/api/v1/chats?limit=200&offset=10", headers=auth).status_code == 200
    assert server.calls[0]["query"]["limit"] == "200"
    for bad in ("limit=0", "limit=201", "offset=-1", "limit=abc"):
        assert api.get(f"/api/v1/chats?{bad}", headers=auth).status_code == 422, bad
    assert len(server.calls) == 1, "yaroqsiz sahifa so'rovi xizmatga bormaydi"


def test_api_ochish_types_ts_ga_mos(api, auth, server):
    body = api.get(f"/api/v1/chats/{CHAT}?limit=2", headers=auth).json()
    assert set(body) == SUMMARY_FIELDS, "ChatDetail maydonlari"
    assert isinstance(body["messages"], list)
    assert set(body["messages"][0]) == MESSAGE_FIELDS
    assert body["messages"][0]["role"] == "user"
    assert server.calls[0]["query"] == {"user_id": "venera:1", "limit": "2"}


def test_api_ochish_chegarasi(api, auth, server):
    assert api.get(f"/api/v1/chats/{CHAT}?limit=1001", headers=auth).status_code == 422
    assert server.calls == []


def test_api_nomini_ozgartirish(api, auth, server):
    response = api.patch(f"/api/v1/chats/{CHAT}", json={"title": "  Ta'til   savollari "}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == SUMMARY_FIELDS
    assert body["title_source"] == "user"
    # Bo'shliqlar bittaga tushirilib, chekkalari kesilib ketadi.
    assert server.calls[0]["body"] == {"title": "Ta'til savollari"}


@pytest.mark.parametrize("title", ["", "   ", "x" * 81])
def test_api_bosh_yoki_uzun_nom_422(api, auth, server, title):
    response = api.patch(f"/api/v1/chats/{CHAT}", json={"title": title}, headers=auth)
    assert response.status_code == 422
    assert response.json()["message"]
    assert server.calls == [], "yaroqsiz nom xizmatga bormaydi"


def test_api_ochirish_va_tiklash(api, auth, server):
    body = api.delete(f"/api/v1/chats/{CHAT}", headers=auth).json()
    assert set(body) == DELETED_FIELDS and body["status"] == "deleted"
    body = api.post(f"/api/v1/chats/{CHAT}/restore", headers=auth).json()
    assert set(body) == SUMMARY_FIELDS
    assert [c["method"] for c in server.calls] == ["DELETE", "POST"]
    assert all(c["query"] == {"user_id": "venera:1"} for c in server.calls)


def test_api_topilmagan_suhbat_404(api, auth, server):
    server.status = 404
    response = api.get(f"/api/v1/chats/{CHAT}", headers=auth)
    assert response.status_code == 404
    assert response.json()["message"] == "Suhbat topilmadi"


def test_api_xizmat_xatosi_502_va_sir_chiqmaydi(api, auth, server):
    server.status = 500
    response = api.get("/api/v1/chats", headers=auth)
    assert response.status_code == 502
    assert "assistant.test" not in response.text
    assert "sir" not in response.json()["message"]


def test_api_yaroqsiz_kalit_400(api, auth, server):
    response = api.get("/api/v1/chats/a%20b", headers=auth)
    assert response.status_code == 400
    assert server.calls == []


# --- guruhdagi CRM suhbatlari shaxsiy tarixda yo'q (2026-10-10, F0) -----------------------


GROUP_CHAT = "tgcrm-3f0c2b9e-8f6e-4d7a-9b1c-2a4e5d6f7a8b"


def test_api_guruh_crm_suhbati_royxatda_korinmaydi(api, auth, server):
    server.extra = [{**SUMMARY, "chat_id": GROUP_CHAT, "title": "AI team: crmga kiritib qo'y"},
                    {**SUMMARY, "chat_id": "c-2", "title": "Ta'til"}]
    body = api.get("/api/v1/chats", headers=auth).json()
    assert [item["chat_id"] for item in body["items"]] == [CHAT, "c-2"]
    # Sahifa so'rovi o'zgarmagan - xizmatga avvalgidek boradi.
    assert server.calls[0]["query"] == {"user_id": "venera:1", "limit": "50", "offset": "0"}


def test_api_guruh_crm_suhbati_ochilmaydi_va_tiklanmaydi(api, auth, server):
    for response in (api.get(f"/api/v1/chats/{GROUP_CHAT}", headers=auth),
                     api.patch(f"/api/v1/chats/{GROUP_CHAT}", json={"title": "Meniki"}, headers=auth),
                     api.post(f"/api/v1/chats/{GROUP_CHAT}/restore", headers=auth)):
        assert response.status_code == 404
        assert response.json()["message"] == "Suhbat topilmadi"
    assert server.calls == [], "guruh suhbati uchun xizmatga borilmaydi"
    # O'chirish - zararsiz (agentda yumshoq yashirish), avvalgidek o'tadi.
    assert api.delete(f"/api/v1/chats/{GROUP_CHAT}", headers=auth).status_code == 200
    assert [c["method"] for c in server.calls] == ["DELETE"]


def test_api_guruh_crm_suhbatida_savol_berilmaydi(api, auth, server):
    """`POST /chat/stream` guruhdagi CRM suhbatini shaxsiy chatda davom ettirmaydi."""
    response = api.post("/api/v1/chat/stream", json={"question": "davom et", "chatId": GROUP_CHAT}, headers=auth)
    assert response.status_code == 404
    assert server.calls == []


def test_bot_shikoyat_surati_guruh_crm_suhbatini_olmaydi(monkeypatch):
    from types import SimpleNamespace

    from app.bot.runner import Backend

    seen = []
    monkeypatch.setattr(chat_api._assistant, "get_chat", lambda *a, **k: seen.append(a))
    with pytest.raises(AssistantError):
        Backend().history(GROUP_CHAT, SimpleNamespace(actorId=1))
    assert seen == []

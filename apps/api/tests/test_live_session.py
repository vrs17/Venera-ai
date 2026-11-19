"""Jonli ovozli suhbat: `POST /api/v1/live/session` - Speko agentida («O'zbek operator» = Barno) sessiya ochish.

Speko soxta (`urllib.request.urlopen`) - `api.speko.dev` chaqirilmaydi, hisobdan daqiqa yechilmaydi.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from app.api.v1 import live
from app.core.config import settings
from app.services.integrations.speko import SpekoClient, SpekoError

KEY = "sk_live_test_abcdef0123456789"
URL = "/api/v1/live/session"
OK = {"mode": "cascade", "runtime": "livekit", "transport": "livekit", "sessionId": "sess-1234567890",
      "transportToken": "tok.en.x", "transportUrl": "wss://speko-test.livekit.cloud",
      "conversationToken": "tok.en.x", "livekitUrl": "wss://speko-test.livekit.cloud",
      "expiresAt": "2026-11-19T06:18:22.423Z"}


class _Resp:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Speko:
    """Javoblar navbati: `(status, body)` yoki istisno; so'rovlar yoziladi."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, request, timeout=None):
        self.requests.append({"url": request.full_url, "method": request.get_method(), "timeout": timeout,
                              "auth": request.get_header("Authorization"), "body": json.loads(request.data)})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, io.BytesIO(raw))
        return _Resp(raw, status)


@pytest.fixture
def speko(monkeypatch):
    monkeypatch.setattr(settings, "speko_agent_key", KEY, raising=False)
    monkeypatch.setattr(settings, "speko_api_url", "https://speko.test", raising=False)
    monkeypatch.setattr(settings, "speko_agent_id", "agent_test", raising=False)
    monkeypatch.setattr(settings, "live_sessions_per_min", 3, raising=False)
    monkeypatch.setattr(settings, "live_sessions_per_hour", 30, raising=False)
    live.reset_limits()
    fake = Speko([(201, OK)])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    yield fake
    live.reset_limits()


def test_sessiya_ochiladi_va_brauzerga_faqat_transport_beriladi(client, auth, speko):
    response = client.post(URL, json={"persona": "barno"}, headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"sessionId": "sess-1234567890", "transport": "livekit", "transportToken": "tok.en.x",
                               "transportUrl": "wss://speko-test.livekit.cloud",
                               "expiresAt": "2026-11-19T06:18:22.423Z"}
    assert response.headers["cache-control"] == "no-store"
    assert KEY not in response.text                                     # platforma kaliti brauzerga chiqmaydi
    sent = speko.requests[0]
    assert sent["url"] == "https://speko.test/v1/sessions" and sent["method"] == "POST"
    assert sent["auth"] == f"Bearer {KEY}"
    assert sent["body"] == {"mode": "cascade", "agentId": "agent_test"}  # odam haqida hech narsa ketmaydi


def test_tana_bolmasa_ham_barno(client, auth, speko):
    assert client.post(URL, json={}, headers=auth).status_code == 200
    assert speko.requests[0]["body"]["agentId"] == "agent_test"


def test_kirmagan_odamga_sessiya_ochilmaydi(client, speko):
    assert client.post(URL, json={"persona": "barno"}).status_code == 401
    assert speko.requests == []                                          # Speko'ga so'rov ketmadi - daqiqa yo'q


def test_notanish_suhbatdosh_rad_etiladi(client, auth, speko):
    assert client.post(URL, json={"persona": "sardor"}, headers=auth).status_code in (400, 422)
    assert speko.requests == []


def test_kalit_bolmasa_503(client, auth, speko, monkeypatch):
    monkeypatch.setattr(settings, "speko_agent_key", "", raising=False)
    response = client.post(URL, json={}, headers=auth)
    assert response.status_code == 503 and response.json()["message"] == live.UNAVAILABLE
    assert speko.requests == []


@pytest.mark.parametrize("upstream,ours", [(401, 502), (404, 502), (429, 503), (402, 503), (500, 503)])
def test_speko_xatosi_sirsiz_qaytadi(client, auth, speko, upstream, ours):
    speko.replies = [(upstream, {"error": f"bad key {KEY}", "message": f"denied for {KEY}"})]
    response = client.post(URL, json={}, headers=auth)
    assert response.status_code == ours
    assert response.json()["message"] == live.UNAVAILABLE and KEY not in response.text


def test_tarmoq_xatosi_503_va_chegaradan_joy_yemaydi(client, auth, speko):
    speko.replies = [urllib.error.URLError("timed out")] * 5 + [(201, OK)]
    for _ in range(5):                                                   # chegara 3, lekin xato hisobga kirmaydi
        assert client.post(URL, json={}, headers=auth).status_code == 503
    assert client.post(URL, json={}, headers=auth).status_code == 200


def test_daqiqalik_chegara_odam_boshiga(client, auth, user_auth, speko):
    speko.replies = [(201, OK)] * 5
    for _ in range(3):
        assert client.post(URL, json={}, headers=auth).status_code == 200
    blocked = client.post(URL, json={}, headers=auth)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1
    assert len(speko.requests) == 3                                      # to'rtinchisi Speko'ga yetmadi
    assert client.post(URL, json={}, headers=user_auth).status_code == 200   # boshqa odamning o'z chegarasi


def test_soatlik_chegara(client, auth, speko, monkeypatch):
    monkeypatch.setattr(settings, "live_sessions_per_min", 10, raising=False)
    monkeypatch.setattr(settings, "live_sessions_per_hour", 2, raising=False)
    speko.replies = [(201, OK)] * 3
    assert client.post(URL, json={}, headers=auth).status_code == 200
    assert client.post(URL, json={}, headers=auth).status_code == 200
    assert client.post(URL, json={}, headers=auth).status_code == 429


# --- baho -----------------------------------------------------------------------------------


def test_baho_faylga_yoziladi(client, auth, speko, tmp_path, monkeypatch):
    path = tmp_path / "live" / "feedback.jsonl"
    monkeypatch.setattr(settings, "live_feedback_file", path, raising=False)
    body = {"sessionId": "sess-1", "persona": "barno", "rating": 2, "reasons": ["slow", "misheard", "slow"],
            "comment": "  Javob   kech keldi\n", "durationSec": 75}
    response = client.post("/api/v1/live/feedback", json=body, headers=auth)
    assert response.status_code == 200 and response.json() == {"saved": True}
    assert client.post("/api/v1/live/feedback", json={"rating": 5}, headers=auth).status_code == 200
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert {k: rows[0][k] for k in ("sessionId", "persona", "rating", "reasons", "comment", "durationSec")} == {
        "sessionId": "sess-1", "persona": "barno", "rating": 2, "reasons": ["slow", "misheard"],
        "comment": "Javob kech keldi", "durationSec": 75}
    assert rows[0]["actorId"] == 1 and rows[0]["ts"] > 0 and rows[1]["rating"] == 5
    assert oct(path.stat().st_mode)[-3:] == "600" and oct(path.parent.stat().st_mode)[-3:] == "700"


@pytest.mark.parametrize("body", [{}, {"rating": 0}, {"rating": 6}, {"rating": 3, "reasons": ["DROP TABLE"]},
                                  {"rating": 3, "comment": "x" * 501}, {"rating": 3, "persona": "sardor"}])
def test_notogri_baho_rad_etiladi(client, auth, speko, tmp_path, monkeypatch, body):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(settings, "live_feedback_file", path, raising=False)
    assert client.post("/api/v1/live/feedback", json=body, headers=auth).status_code in (400, 422)
    assert not path.exists()


def test_baho_faqat_kirgan_odamdan(client, speko, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "live_feedback_file", tmp_path / "feedback.jsonl", raising=False)
    assert client.post("/api/v1/live/feedback", json={"rating": 5}).status_code == 401


# --- klient ---------------------------------------------------------------------------------


def test_klient_200_va_eski_nomlarni_ham_qabul_qiladi(monkeypatch):
    legacy = {"sessionId": "s1", "conversationToken": "t", "livekitUrl": "wss://x.livekit.cloud"}
    monkeypatch.setattr(urllib.request, "urlopen", Speko([(200, legacy)]))
    session = SpekoClient("https://speko.test/", KEY).create_session("agent_x")
    assert (session.transport_token, session.transport_url, session.transport) == ("t", "wss://x.livekit.cloud", "livekit")
    assert session.expires_at is None


@pytest.mark.parametrize("body", [{"sessionId": "s1"}, [1, 2], b"<html>bad gateway</html>"])
def test_klient_notogri_javob(monkeypatch, body):
    monkeypatch.setattr(urllib.request, "urlopen", Speko([(200, body)]))
    with pytest.raises(SpekoError) as err:
        SpekoClient("https://speko.test", KEY).create_session("agent_x")
    assert err.value.status == 502


def test_klient_xato_matnida_kalit_yoq(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", Speko([(401, {"message": f"invalid key {KEY}"})]))
    with pytest.raises(SpekoError) as err:
        SpekoClient("https://speko.test", KEY).create_session("agent_x")
    assert KEY not in str(err.value) and "***" in str(err.value) and err.value.upstream == 401
    assert SpekoClient("https://speko.test", "").configured is False
    with pytest.raises(SpekoError) as off:
        SpekoClient("https://speko.test", "").create_session("agent_x")
    assert off.value.status == 503

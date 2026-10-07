"""Savol izi va tashqi chaqiruvlar hisobi - JONLI kod yo'llari ustida.

Admin panel "nima bo'ldi" degan savolga shu yozuvlardan javob beradi:
qaysi kanal, kim, qaysi hujjatlar, qaysi HRM/CRM chaqiruvi, birinchi so'z
qachon, qaysi tashqi xizmat qancha vaqt oldi. Bu testlar yozuvlar HAQIQIY
endpoint va klientlar orqali tushishini tekshiradi.

Hech bir tashqi xizmat chaqirilmaydi: Assistant, TTS, STT, Telegram,
Ollama, CRM, HRM, Keycloak - hammasi soxta transport ustida
(`build_opener` / `urlopen`), ustidagi mantiq haqiqiy kod. Ombor har testda
vaqtinchalik (`conftest._isolated_analytics`).
"""

from __future__ import annotations

import gc
import http.client
import io
import json
import re
import time
import urllib.error
import urllib.request

import pytest

from app.core.config import settings
from app.schemas.auth import AuthUser
from app.schemas.chat import StreamRequest
from app.services import analytics
from app.services.integrations.assistant import AnswerStream, AssistantClient

BASE = "http://assistant.test"
SECRET = "capture-client-secret"
HRM_TOKEN = "hrm-jwt-secret-value"
TURN = re.compile(r"[0-9a-f]{32}")
#: Yordamchining oqim yo'li - versiyasiz yoki dvigatel bilan.
STREAM_PATH = re.compile(r"/api/(v[12]/)?chat/stream")


def frame(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False).encode("utf-8") + b"\n"


FRAMES = [
    frame(type="stage", stage="retrieval", text="Hujjatlar qidirilmoqda"),
    frame(type="sources", items=[
        {"kind": "doc", "doc_id": "HR_045", "title": "Ichki mehnat tartibi", "page": 22,
         "citation_index": 1, "score": 0.83, "snippet": "Yillik ta'til 21 kalendar kun"},
        {"kind": "hrm", "marker": "[T1]", "tool": "hrm_today_late", "status": "ok",
         "digest": "count=9"},
    ]),
    frame(type="token", text="Yillik ta'til "),
    frame(type="token", text="21 kalendar kun."),
    frame(type="done", route="both", request_id="rid-777"),
]


# --- soxta Assistant --------------------------------------------------------------


class _Response:
    """`http.client` javobi o'rnida: qator-qator (oqim) yoki bir yo'la (JSON)."""

    def __init__(self, parts, headers=None, cut_after=None) -> None:
        self._parts = list(parts)
        self.headers = headers or {}
        self.status = 200
        self._cut_after = cut_after
        self._served = 0
        self.closed = False

    def readline(self, limit: int = -1) -> bytes:
        if self._cut_after is not None and self._served >= self._cut_after:
            raise http.client.IncompleteRead(b"", 1)
        if not self._parts:
            return b""
        self._served += 1
        return self._parts.pop(0)

    def read(self, size: int = -1) -> bytes:
        return self._parts.pop(0) if self._parts else b""

    def close(self) -> None:
        self.closed = True


def _http_error(url: str, code: int, body: bytes = b'{"detail":"xato"}') -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "xato", {}, io.BytesIO(body))


class Upstream:
    """Assistant xizmati: oqim, JSON yo'llar va xatolar."""

    def __init__(self) -> None:
        self.frames = list(FRAMES)
        self.cut_after: int | None = None
        self.status: int | None = None
        self.json: dict[str, dict] = {}
        self.errors: dict[str, int] = {}
        #: Qaysi oqim yo'llari ochildi - dvigatel tanlovini tekshirish uchun.
        self.paths: list[str] = []

    def open(self, request, timeout=None):
        path = request.full_url.split(BASE, 1)[1].split("?", 1)[0]
        if self.status:
            raise _http_error(request.full_url, self.status)
        if path in self.errors:
            raise _http_error(request.full_url, self.errors[path])
        # Oqim yo'li dvigatelga bog'liq (`core/engines.py`): versiyasiz yoki v1/v2.
        if STREAM_PATH.fullmatch(path):
            self.paths.append(path)
            return _Response(self.frames, {"X-Request-Id": "served-1"}, cut_after=self.cut_after)
        if path in self.json:
            return _Response([json.dumps(self.json[path]).encode()])
        raise AssertionError(f"kutilmagan yo'l: {path}")


@pytest.fixture
def db(_isolated_analytics):
    return _isolated_analytics


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    """Chat moduli soxta Assistant ustida. CRM agent sessiyasi SOZLANMAGAN
    (jonli CRM ga login bo'lmasin), platforma tokeni - sir qiymatli satr:
    u izga tushmasligini tekshirish uchun."""
    import app.api.v1.chat as chat_module
    from app.services.integrations.crm_auth import CrmAuth

    fake = Upstream()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    monkeypatch.setattr(chat_module, "_assistant",
                        AssistantClient(BASE, "venera", SECRET, timeout=5, max_concurrent=2))
    monkeypatch.setattr(chat_module, "_crm", CrmAuth("", "", "", tmp_path / "crm"))
    monkeypatch.setattr(chat_module, "platform_tokens", lambda: {"hrm": HRM_TOKEN})
    return fake


def rows(db, sql: str, params: tuple = ()) -> list[dict]:
    """Yozuvchi navbatini diskka tushirib, keyin o'qiydi."""
    assert analytics.flush(5.0), "yozuvchi ulgurmadi"
    return db.rows(sql, params)


def ask_stream(client, auth, *, channel: str | None = "web", **body):
    headers = dict(auth)
    if channel:
        headers["X-Venera-Client"] = channel
    return client.post("/api/v1/chat/stream", headers=headers,
                       json={"question": "Ta'til necha kun?", **body})


def events_of(db, turn_id: str) -> list[dict]:
    return rows(db, "SELECT seq, t_ms, dur_ms, type, name, payload FROM turn_events "
                    "WHERE turn_id=? ORDER BY seq", (turn_id,))


def payload(event: dict) -> dict:
    return json.loads(event["payload"]) if event["payload"] else {}


def all_text(db) -> str:
    """Butun ombor matni - sirlar hech qayerda yo'qligini tekshirish uchun."""
    analytics.flush(5.0)
    return json.dumps([db.rows(f"SELECT * FROM {table}") for table in
                       ("turns", "turn_events", "turn_sources", "api_calls")],
                      ensure_ascii=False, default=str)


# ============================================================ /chat/stream


def test_savol_izi_toliq_yoziladi(client, auth, upstream, db):
    response = ask_stream(client, auth, chatId="c-1", locale="uz")
    assert response.status_code == 200
    turn_id = response.headers["x-venera-turn"]
    assert TURN.fullmatch(turn_id)
    # Kadrlar O'ZGARMASDAN ketadi - iz faqat kuzatadi.
    kinds = [json.loads(line)["type"] for line in response.text.splitlines() if line.strip()]
    assert kinds == ["stage", "sources", "token", "token", "done"]

    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
    assert (turn["channel"], turn["kind"], turn["status"]) == ("web", "chat", "ok")
    assert (turn["actor_id"], turn["user_login"]) == (1, "admin@venera.uz")
    assert (turn["question"], turn["chat_id"], turn["locale"]) == ("Ta'til necha kun?", "c-1", "uz")
    assert turn["answer"] == "Yillik ta'til 21 kalendar kun."
    assert (turn["route"], turn["request_id"]) == ("both", "served-1")
    assert turn["input_mode"] == "text"
    assert turn["ttft_ms"] is not None and turn["total_ms"] >= turn["ttft_ms"]
    assert (turn["frames"], turn["sources_count"], turn["tool_calls"]) == (5, 1, 1)

    events = events_of(db, turn_id)
    names = [(e["type"], e["name"]) for e in events]
    for expected in [("span", "tokens"), ("span", "assistant.open"), ("note", "first_frame"),
                     ("note", "first_token"), ("frame", "stage"), ("frame", "sources"),
                     ("frame", "done")]:
        assert expected in names, (expected, names)
    by_name = {e["name"]: e for e in events}
    # Tokenlarning faqat NOMLARI - qiymati hech qachon.
    assert payload(by_name["tokens"]) == {"platforms": ["hrm"]}
    assert payload(by_name["assistant.open"])["requestId"] == "served-1"
    assert by_name["assistant.open"]["dur_ms"] is not None

    sources = rows(db, "SELECT * FROM turn_sources WHERE turn_id=? ORDER BY idx", (turn_id,))
    assert [(s["kind"], s["ref"]) for s in sources] == [("doc", "HR_045"), ("hrm", "hrm_today_late")]
    doc, tool = sources
    assert (doc["title"], doc["page"], doc["citation"]) == ("Ichki mehnat tartibi", 22, 1)
    assert doc["score"] == pytest.approx(0.83)
    assert (tool["citation"], tool["digest"], tool["status"]) == (1, "count=9", "ok")

    text = all_text(db)
    assert HRM_TOKEN not in text and SECRET not in text


def test_assistant_chaqiruvi_egasi_kanali_va_savoli_bilan(client, auth, upstream, db):
    response = ask_stream(client, auth, channel="miniapp")
    turn_id = response.headers["x-venera-turn"]
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    assert (call["op"], call["status"], call["http_status"]) == ("stream", "ok", 200)
    # Atributsiya: kim (`current_user`), qaysi kanal (sarlavha), qaysi savol
    # (recorder) - oqim boshqa ipda o'qilgan bo'lsa ham.
    assert (call["actor_id"], call["channel"], call["turn_id"]) == (1, "miniapp", turn_id)
    units = json.loads(call["units"])
    assert units["frames"] == 5 and units["bytes"] > 0
    assert call["duration_ms"] >= 0 and call["error"] is None


@pytest.mark.parametrize("headers,expected", [
    ({"X-Venera-Client": "desktop"}, "desktop"),
    ({"Referer": "https://llm.test/tg/?tgWebAppStartParam=x"}, "miniapp"),
    # `bot` sarlavha orqali qabul qilinmaydi - bot HTTP'dan kelmaydi.
    ({"X-Venera-Client": "bot"}, "api"),
    ({}, "api"),
])
def test_kanal_sarlavhadan(client, auth, upstream, db, headers, expected):
    response = client.post("/api/v1/chat/stream", headers={**auth, **headers},
                           json={"question": "salom"})
    [turn] = rows(db, "SELECT channel FROM turns WHERE id=?", (response.headers["x-venera-turn"],))
    assert turn["channel"] == expected


def test_oqim_ortasida_uzilsa_xato_bilan_yakunlanadi(client, auth, upstream, db):
    upstream.cut_after = 2
    response = ask_stream(client, auth)
    assert response.status_code == 200
    kinds = [json.loads(line)["type"] for line in response.text.splitlines() if line.strip()]
    assert kinds[-2:] == ["error", "done"]
    turn_id = response.headers["x-venera-turn"]
    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
    assert (turn["status"], turn["error_code"]) == ("error", "stream_broken")
    broken = [e for e in events_of(db, turn_id) if e["name"] == "assistant.broken"]
    assert broken and "uzildi" in payload(broken[0])["error"]
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    # Sarlavhalar kelgan (200), keyin uzilgan - hisobda aynan shunday.
    assert (call["status"], call["http_status"]) == ("error", 200)
    assert "uzildi" in call["error"]


@pytest.mark.parametrize("upstream_status,user_status,code", [
    # Xizmatning O'ZI 503 bergani - alohida kod (bizning navbat to'lganidan farqli).
    (503, 503, "upstream_busy"), (401, 502, "open_failed"), (422, 422, "open_failed")])
def test_ochilmagan_oqim_statusi_bilan_yoziladi(client, auth, upstream, db,
                                                upstream_status, user_status, code):
    upstream.status = upstream_status
    response = ask_stream(client, auth)
    assert response.status_code == user_status
    [turn] = rows(db, "SELECT * FROM turns")
    assert (turn["status"], turn["http_status"], turn["error_code"]) == (
        "error", user_status, code)
    assert turn["channel"] == "web" and turn["actor_id"] == 1
    # Xato javobida ham savol kaliti - shikoyatga qo'shish uchun.
    assert response.headers["x-venera-turn"] == turn["id"]
    opened = [e for e in events_of(db, turn["id"]) if e["name"] == "assistant.open"]
    assert opened and "error" in payload(opened[0])
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    # Hisobda xizmatning HAQIQIY statusi: 401 - "ilova siri noto'g'ri".
    assert (call["status"], call["http_status"]) == ("error", upstream_status)
    assert call["turn_id"] == turn["id"]
    assert SECRET not in all_text(db)


def test_sozlanmagan_xizmat_savoli_ham_yoziladi(client, auth, upstream, db, monkeypatch):
    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module._assistant, "client_id", "")
    response = ask_stream(client, auth)
    assert response.status_code == 501
    [turn] = rows(db, "SELECT * FROM turns")
    assert (turn["status"], turn["http_status"]) == ("error", 501)
    # Xizmatga umuman borilmagan - hisobda chaqiruv yo'q.
    assert rows(db, "SELECT * FROM api_calls WHERE service='assistant'") == []


# --- klient uzilishi -------------------------------------------------------------


@pytest.fixture
def captured(monkeypatch):
    """Endpointni HTTP'siz chaqirish: javob obyekti o'rniga uning tanasi
    (generator) va sarlavhalari olinadi - uzilishni aynan boshqarish uchun."""
    import app.api.v1.chat as chat_module

    got: dict = {}

    class Capture:
        def __init__(self, content, media_type=None, headers=None) -> None:
            got["content"], got["headers"] = content, headers

    monkeypatch.setattr(chat_module, "StreamingResponse", Capture)
    return got


class _Request:
    headers = {"X-Venera-Client": "web"}


USER = AuthUser(actorId=7, email="Uzilgan@Venera.uz", fullName="Uzilgan Xodim")


def test_klient_uzilsa_cancelled_va_slot_qaytadi(upstream, db, captured):
    import app.api.v1.chat as chat_module

    chat_module.stream(StreamRequest(question="salom"), _Request(), user=USER)
    body, turn_id = captured["content"], captured["headers"]["X-Venera-Turn"]
    assert json.loads(next(body))["type"] == "stage"
    body.close()                                     # brauzer uzildi

    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
    assert (turn["status"], turn["actor_id"], turn["user_login"]) == ("cancelled", 7,
                                                                      "uzilgan@venera.uz")
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    # Klient ketgani xizmatning xatosi EMAS.
    assert (call["status"], call["error"], call["turn_id"]) == ("ok", "cancelled", turn_id)
    assert chat_module._assistant.busy() == 0


def test_boshlanmagan_oqim_ham_yakunlanadi(upstream, db, captured):
    """Brauzer sarlavhadan keyin, tanadan OLDIN uzilsa generator hech
    boshlanmaydi va `finally` ishlamaydi. Iz ham, slot ham osilib qolmasin."""
    import app.api.v1.chat as chat_module

    chat_module.stream(StreamRequest(question="salom"), _Request(), user=USER)
    turn_id = captured["headers"]["X-Venera-Turn"]
    captured.clear()
    gc.collect()

    [turn] = rows(db, "SELECT status FROM turns WHERE id=?", (turn_id,))
    assert turn["status"] == "cancelled"
    [call] = rows(db, "SELECT status, error FROM api_calls WHERE service='assistant'")
    assert (call["status"], call["error"]) == ("ok", "cancelled")
    assert chat_module._assistant.busy() == 0


# --- kutish ovozi --------------------------------------------------------------


def test_ovozli_savolda_tasnif_va_kutish_kadri_izda(client, auth, monkeypatch, tmp_path, db):
    import app.api.v1.chat as chat_module
    from app.services.hold import HoldVoices, all_clips
    from app.services.integrations.crm_auth import CrmAuth

    # `.env` ga bog'liq bo'lmasin: kutish ovozi shu test uchun YOQIQ.
    monkeypatch.setattr(settings, "hold_enabled", True)
    monkeypatch.setattr(settings, "hold_first_ms", 1200)
    monkeypatch.setattr(settings, "hold_repeat_ms", 9000)
    monkeypatch.setattr(settings, "hold_max", 4)
    voices = HoldVoices(tmp_path / "hold")
    voices.cache_dir.mkdir(parents=True, exist_ok=True)
    for kalit, _ in all_clips():
        (voices.cache_dir / f"{kalit}.wav").write_bytes(b"RIFF" + b"\0" * 40)
    monkeypatch.setattr(chat_module, "_hold_voices", voices)

    class Classifier:
        configured = True
        model = "gemma-test"

        def classify(self, question):
            return ("kechikish", "shoshilinch")

    class Assistant:
        def stream(self, *a, **kw):
            def frames():
                time.sleep(0.4)                  # javob kechikadi - kutish ovozi kerak
                yield b'{"type":"token","text":"Javob"}\n'
                yield b'{"type":"done","route":"hrm"}\n'

            return AnswerStream(request_id="req-h", frames=frames(), outcome={})

    monkeypatch.setattr(chat_module, "_hold_classifier", Classifier())
    monkeypatch.setattr(chat_module, "_assistant", Assistant())
    monkeypatch.setattr(chat_module, "_crm", CrmAuth("", "", "", tmp_path / "crm"))
    monkeypatch.setattr(chat_module, "platform_tokens", dict)

    response = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                           json={"question": "kim kechikdi?", "voice": True, "locale": "uz"})
    kinds = [json.loads(line)["type"] for line in response.text.splitlines() if line.strip()]
    assert "hold" in kinds, kinds
    turn_id = response.headers["x-venera-turn"]
    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
    assert (turn["input_mode"], turn["status"], turn["route"]) == ("voice", "ok", "hrm")

    events = events_of(db, turn_id)
    [classify] = [e for e in events if e["name"] == "hold.classify"]
    assert classify["type"] == "span" and classify["dur_ms"] is not None
    assert payload(classify) == {"model": "gemma-test", "ok": True, "topic": "kechikish",
                                 "tone": "shoshilinch"}
    holds = [e for e in events if e["type"] == "frame" and e["name"] == "hold"]
    assert holds and payload(holds[0])["source"] == "ollama"
    assert payload(holds[0])["topic"] == "kechikish" and payload(holds[0])["at"] == 1
    # `first_frame` - yuqoridagi xizmatning birinchi kadri, kutish kadri emas.
    first = next(e for e in events if e["name"] == "first_frame")
    assert payload(first)["type"] == "token"


# --- /chat/ask ------------------------------------------------------------------


def test_ask_yoli_ham_izga_tushadi(client, auth, db):
    response = client.post("/api/v1/chat/ask", headers={**auth, "X-Venera-Client": "web"},
                           json={"question": "Ta'til qancha qoldi?"})
    assert response.status_code == 200
    turn_id = response.headers["x-venera-turn"]
    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
    assert (turn["kind"], turn["channel"], turn["status"]) == ("ask", "web", "ok")
    assert turn["answer"] == response.json()["answer"]
    by_name = {e["name"]: e for e in events_of(db, turn_id)}
    assert payload(by_name["pipeline"])["finalStatus"] == "RAG_DOMAIN_NOT_READY"
    assert payload(by_name["pipeline.result"])["guard"] == "ALLOW"


# --- taklif holati ---------------------------------------------------------------


@pytest.mark.parametrize("verb,reply,expected", [
    ("confirm", {"status": "executed", "ok": True, "result": {"key": "DVSIB-1"}}, "executed"),
    ("confirm", {"status": "error", "ok": False}, "failed"),
    ("cancel", {"status": "cancelled"}, "cancelled"),
    ("confirm", 404, "expired"),
    ("confirm", 410, "expired"),
])
def test_taklif_tasdiqlansa_izdagi_holati_yangilanadi(client, auth, upstream, db,
                                                      verb, reply, expected):
    token = "prop-" + "a" * 27
    upstream.frames = [
        frame(type="token", text="Tasdiqlaysizmi?"),
        frame(type="proposal", proposal={"token": token, "connector": "crm",
                                         "summary": "DVSIB da yangi task"}),
        frame(type="done", route="crm"),
    ]
    turn_id = ask_stream(client, auth).headers["x-venera-turn"]
    [turn] = rows(db, "SELECT * FROM turns WHERE id=?", (turn_id,))
    assert (turn["has_proposal"], turn["proposal_token"], turn["proposal_status"]) == (
        1, token, "pending")
    # Kalit vaqt chizig'iga tushmaydi - faqat `turns.proposal_token` da.
    assert token not in json.dumps(events_of(db, turn_id))

    path = f"/api/actions/{token}/{verb}"
    if isinstance(reply, int):
        upstream.errors[path] = reply
    else:
        upstream.json[path] = {"token": token, **reply}
    response = client.post(f"/api/v1/actions/{token}/{verb}", headers=auth)
    assert response.status_code == (reply if isinstance(reply, int) else 200)

    [turn] = rows(db, "SELECT proposal_status FROM turns WHERE id=?", (turn_id,))
    assert turn["proposal_status"] == expected
    [call] = rows(db, "SELECT * FROM api_calls WHERE op=?", (f"action.{verb}",))
    assert (call["service"], call["actor_id"], call["channel"]) == ("assistant", 1, "api")
    assert call["status"] == ("error" if isinstance(reply, int) else "ok")


def test_suhbatlar_royxati_ham_hisoblanadi(client, auth, upstream, db):
    upstream.json["/api/chats"] = {"items": [], "limit": 50, "offset": 0}
    response = client.get("/api/v1/chats", headers={**auth, "X-Venera-Client": "web"})
    assert response.status_code == 200
    [call] = rows(db, "SELECT * FROM api_calls WHERE service='assistant'")
    assert (call["op"], call["status"], call["actor_id"], call["channel"]) == (
        "chats.list", "ok", 1, "web")
    assert call["turn_id"] is None and json.loads(call["units"])["bytes"] > 0


# ======================================================================= STT / TTS


def test_stt_savol_va_uygotish_alohida_hisoblanadi(client, auth, monkeypatch, db):
    import app.api.v1.stt as stt_module
    from app.services.stt import SttError, Transcript

    monkeypatch.setattr(settings, "wake_log_enabled", False)
    monkeypatch.setattr(stt_module._router_client, "transcribe",
                        lambda audio, **kw: Transcript(text="salom venera", duration_sec=2.5,
                                                       backend="uz"))
    audio = b"RIFF" + b"\0" * 100
    headers = {**auth, "X-Venera-Client": "miniapp"}
    form = {"language": "uz"}
    files = {"file": ("a.wav", audio, "audio/wav")}
    assert client.post("/api/v1/stt/transcribe", headers=headers, files=files,
                       data=form).status_code == 200
    assert client.post("/api/v1/stt/wake", headers=headers, files=files,
                       data=form).status_code == 200

    def busy(audio, **kw):
        raise SttError("navbat to'la", status=503, retryable=True)

    monkeypatch.setattr(stt_module._router_client, "transcribe", busy)
    assert client.post("/api/v1/stt/transcribe", headers=headers, files=files,
                       data=form).status_code == 503

    calls = rows(db, "SELECT * FROM api_calls WHERE service LIKE 'stt%' ORDER BY id")
    assert [(c["service"], c["op"], c["status"]) for c in calls] == [
        ("stt_router", "transcribe", "ok"), ("stt_router", "wake", "ok"),
        ("stt_router", "transcribe", "error")]
    assert all((c["actor_id"], c["channel"]) == (1, "miniapp") for c in calls)
    assert json.loads(calls[0]["units"]) == {"bytes": len(audio), "audioSec": 2.5}
    assert calls[2]["http_status"] == 503


def test_tts_hisobi_savol_kaliti_bilan(client, auth, monkeypatch, db):
    from test_tts import PCM, FakeServer as TtsServer

    import app.api.v1.tts as tts_module
    from app.services.tts import TtsClient

    fake = TtsServer()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    monkeypatch.setattr(tts_module, "_client", TtsClient("http://tts", "frontend", "tts-s3cret"))
    turn_id = "ab" * 16
    response = client.post("/api/v1/tts/speak",
                           headers={**auth, "X-Venera-Turn": turn_id, "X-Venera-Client": "web"},
                           json={"text": "salom", "language": "uz"})
    assert response.status_code == 200 and response.content == PCM * 3
    # Yaroqsiz kalit - e'tiborsiz, xato emas.
    response = client.post("/api/v1/tts/speak", headers={**auth, "X-Venera-Turn": "../x"},
                           json={"text": "salom", "language": "uz"})
    assert response.status_code == 200

    calls = rows(db, "SELECT * FROM api_calls WHERE service='tts' ORDER BY id")
    assert [c["op"] for c in calls] == ["token", "speak", "speak"]
    token_call, first, second = calls
    assert token_call["status"] == "ok"
    assert (first["turn_id"], first["actor_id"], first["channel"]) == (turn_id, 1, "web")
    assert json.loads(first["units"]) == {"chars": 5, "bytes": len(PCM) * 3,
                                          "audioSec": round(len(PCM) * 3 / 16000, 2)}
    assert (first["status"], first["http_status"]) == ("ok", 200)
    assert second["turn_id"] is None
    assert "tts-s3cret" not in all_text(db)


# ========================================================== boshqa tashqi xizmatlar


class _Http:
    """`urlopen` javobi: kontekst menejer, `read`, `headers`."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.headers: dict[str, str] = {}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1) -> bytes:
        data, self._data = self._data, b""
        return data


def test_ollama_tasnifi_hisoblanadi(monkeypatch, db):
    from test_hold import KEY, FakeOllama

    from app.services.integrations.ollama import HoldClassifier

    fake = FakeOllama()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    classifier = HoldClassifier("https://ollama.test", KEY, "gemma4:31b", timeout=2.0)
    with analytics.bind(5, "web", "cd" * 16):
        assert classifier.classify("kim kechikdi?") == ("kechikish", "oddiy")
    fake.status = 401
    assert classifier.classify("savol") is None

    calls = rows(db, "SELECT * FROM api_calls WHERE service='ollama' ORDER BY id")
    assert [(c["op"], c["status"], c["http_status"]) for c in calls] == [
        ("classify", "ok", 200), ("classify", "error", 401)]
    assert (calls[0]["actor_id"], calls[0]["channel"], calls[0]["turn_id"]) == (5, "web", "cd" * 16)
    assert KEY not in all_text(db)


def test_crm_hrm_keycloak_kirishlari_hisoblanadi(monkeypatch, db):
    from app.services.integrations import connectors as conn
    from app.services.integrations.crm_auth import CrmAuthError, post_json

    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjE5OTk5OTk5OTl9.c2ln"

    def fake(request, timeout=None):
        url = request.full_url
        if url.endswith("/api/auth/refresh"):
            return _Http(json.dumps({"data": {"access_token": jwt, "expires_in": 300}}).encode())
        if url.endswith("/api/auth/logout"):
            raise _http_error(url, 400, b'{"error":{"code":"AUTH_FAILED","message":"bekor"}}')
        if url.endswith("/api/authenticate"):
            return _Http(json.dumps({"id_token": jwt}).encode())
        if url.endswith("/openid-connect/token"):
            # Ba'zi xizmatlar so'rovni xato matnida qaytaradi - parol hisobga
            # tushmasligi kerak.
            raise _http_error(url, 401, b'{"error":"invalid_grant","error_description":'
                                        b'"Invalid user credentials password=Parol-123"}')
        raise AssertionError(url)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with analytics.bind(3, "web"):
        post_json("https://crm.test/api/auth/refresh", {"refresh_token": "r-token"}, 5)
        with pytest.raises(CrmAuthError):
            post_json("https://crm.test/api/auth/logout", {"refresh_token": "r-token"}, 5)
        conn.HrmAuth("https://hrm.test").login("ali", "Parol-123")
        with pytest.raises(conn.ConnectorError):
            conn.CrmUserAuth("https://kc.test/realms/r/protocol/openid-connect/token",
                             "crm-client", "kc-client-secret", "https://crm.test"
                             ).login("ali", "Parol-123")

    calls = rows(db, "SELECT * FROM api_calls ORDER BY id")
    assert [(c["service"], c["op"], c["status"], c["http_status"]) for c in calls] == [
        ("crm", "refresh", "ok", 200), ("crm", "logout", "error", 400),
        ("hrm", "authenticate", "ok", 200), ("keycloak", "token", "error", 401)]
    assert all((c["actor_id"], c["channel"]) == (3, "web") for c in calls)
    assert "AUTH_FAILED" in calls[1]["error"] and "invalid_grant" in calls[3]["error"]
    text = all_text(db)
    for secret in ("Parol-123", "kc-client-secret", "r-token", jwt):
        assert secret not in text, secret


def test_telegram_api_hisobi(monkeypatch, db):
    from app.services.integrations.telegram import TelegramApi, TelegramError

    token = "123456:TEST-token-for-capture-only_abcdefghij"

    def fake(request, timeout=None):
        method = request.full_url.rsplit("/", 1)[1]
        if method == "sendMessage":
            return _Http(b'{"ok":true,"result":{"message_id":5}}')
        if method == "getUpdates":
            return _Http(b'{"ok":true,"result":[]}')
        if method == "getMe":
            raise _http_error(request.full_url, 409, b'{"ok":false,"error_code":409,'
                                                     b'"description":"Conflict: terminated"}')
        raise AssertionError(method)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    api = TelegramApi(token)
    api.send_message(1, "salom")
    api.get_updates(None, timeout=0)             # muvaffaqiyatli uzun so'rov - shovqin
    with pytest.raises(TelegramError):
        api.get_me()

    calls = rows(db, "SELECT * FROM api_calls WHERE service='telegram' ORDER BY id")
    assert [(c["op"], c["status"], c["http_status"], c["channel"]) for c in calls] == [
        ("sendMessage", "ok", 200, "bot"), ("getMe", "error", 409, "bot")]
    assert token not in all_text(db)


# ======================================================================== bot


@pytest.fixture
def bot_world(tmp_path):
    from test_telegram_bot import FakeBackend, FakeTelegram

    from app.bot.runner import VeneraBot
    from app.core.security import hash_password
    from app.services.telegram_links import LinkStore
    from app.services.users import StoredUser, UserStore

    users = UserStore({"a@b.uz": StoredUser(actor_id=1, email="a@b.uz", full_name="Ali Valiyev",
                                            password_hash=hash_password("x"))})
    tg, links, backend = FakeTelegram(), LinkStore(tmp_path / "links.json"), FakeBackend()
    bot = VeneraBot(tg, links, users=lambda: users, backend=backend,
                    webapp_url="https://llm.test/tg/", inline=True, typing_every=None)
    return bot, tg, links, backend


def test_bot_savoli_izga_bot_kanali_bilan_yoziladi(bot_world, db):
    from test_telegram_bot import TG_ID, _frames, callback, text_update

    bot, tg, links, backend = bot_world
    links.link(TG_ID, 1)
    token = "b" * 32
    backend.frames = _frames(
        {"type": "stage", "text": "Hujjatlar qidirilmoqda"},
        {"type": "sources", "items": [
            {"kind": "doc", "doc_id": "HR_045", "title": "Ichki mehnat tartibi", "page": 22},
            {"kind": "hrm", "tool": "hrm_today_late", "digest": "count=9"}]},
        {"type": "token", "text": "21 kun asosiy ta'til [1]."},
        {"type": "proposal", "proposal": {"token": token, "connector": "crm", "summary": "Task"}},
        {"type": "done", "route": "rules"})
    bot.handle_update(text_update("ta'til necha kun?"))

    [turn] = rows(db, "SELECT * FROM turns")
    assert (turn["channel"], turn["kind"], turn["status"]) == ("bot", "bot", "ok")
    assert (turn["actor_id"], turn["user_name"], turn["user_login"]) == (1, "Ali Valiyev", "a@b.uz")
    assert (turn["question"], turn["answer"]) == ("ta'til necha kun?", "21 kun asosiy ta'til [1].")
    assert (turn["route"], turn["request_id"], turn["input_mode"]) == ("rules", "req-1", "text")
    assert turn["chat_id"] == links.lookup(TG_ID)[0].chat_id
    assert (turn["sources_count"], turn["tool_calls"], turn["has_proposal"]) == (1, 1, 1)
    names = {(e["type"], e["name"]) for e in events_of(db, turn["id"])}
    assert {("span", "assistant.open"), ("span", "telegram.deliver"),
            ("note", "first_token"), ("frame", "sources")} <= names

    bot.handle_update(callback("a:c:" + token))
    [turn] = rows(db, "SELECT proposal_status FROM turns")
    assert turn["proposal_status"] == "executed"


def test_bot_ovozli_va_xato_savollari(bot_world, db):
    from test_telegram_bot import TG_ID, text_update, voice_update

    from app.services.integrations.assistant import AssistantError

    bot, tg, links, backend = bot_world
    links.link(TG_ID, 1)
    tg.files["voice/v1.oga"] = b"OggS-fake"
    bot.handle_update(voice_update())
    backend.open_error = AssistantError("navbat to'la", status=503)
    bot.handle_update(text_update("yana savol"))

    voice, failed = rows(db, "SELECT * FROM turns ORDER BY started_at")
    assert (voice["input_mode"], voice["question"], voice["status"]) == (
        "voice", "bugun kech qoldimmi", "ok")
    [stt] = [e for e in events_of(db, voice["id"]) if e["name"] == "stt"]
    assert payload(stt)["backend"] == "gapi" and payload(stt)["audioSec"] == 4
    assert (failed["status"], failed["http_status"], failed["error_code"]) == (
        "error", 503, "open_failed")
    assert failed["channel"] == "bot"

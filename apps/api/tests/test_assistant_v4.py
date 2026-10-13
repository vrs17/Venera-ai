"""Chat dvigateli v4 - agentning shartnoma 4.0 yo'li (`/api/v4/chat/stream`).

Agent tomonida v1-v3 MUZLATILGAN (har yangilik faqat v4 da), shuning uchun v4 bizda
katalogga qo'shiladi va admin uni avval bitta odamga (`engine_access`), keyin hammaga
(`engine_policy`) beradi. Tekshiriladi (`services/integrations/assistant.py`):

  * SO'ROV: yo'l, `X-Barno-Contract: 4.0`, majburiy `purpose: "chat"`, `store: true`,
    `chat_visibility: "personal"`; qolgani v3 niki (kimlik, tokenlar, `chat_id`, "Pro");
    `style: "voice"` faqat GAPIRILGAN savolda va faqat v4 da;
  * KADRLAR: `ping` / `result` klientga O'TMAYDI, `done` dan `meta` / `cited_ids`
    olinadi, ovozli gaplar orasiga bo'shliq qo'yiladi;
  * JIMLIK: `ping` `timeout` ni uzaytirmaydi (v3 dagi kabi 504);
  * XATO: v4 xato tanasi (`{"error": {"code", "message"}}`) jurnalda kodi bilan;
  * ADMIN: bitta odamga berilgan v4 - faqat uning savoli v4 ga; iz, "Pro" byudjeti va
    ovozda "ha" bilan bajarilgan amal (`action`) holati.

Tarmoqqa chiqilmaydi: agent soxta (`build_opener`), ombor vaqtinchalik.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.core import engines
from app.services import analytics
from app.services import engine_control as control
from app.services.integrations.assistant import AssistantClient, AssistantError, stream_path

BASE = "http://assistant.test"
DEMO_ID = 2          # conftest: demo@venera.uz, faqat USER
QUOTA = {"remaining": {"day": 9, "week": 19, "month": 49},
         "limits": {"day": 10, "week": 20, "month": 50},
         "used": {"day": 1, "week": 1, "month": 1}}
V4_DONE = {"type": "done", "route": "crm", "request_id": "r-4", "engine": "v4",
           "trace_id": "tr-4", "task": {"intent": "crm.list", "state": "done"},
           "cited_ids": [], "meta": {"engine": "v4", "model": "gemma4:31b-cloud", "ms": 812,
                                     "tokens_in": 0, "tokens_out": 0, "store_applied": True}}


def frame(**kw) -> bytes:
    return json.dumps(kw, ensure_ascii=False).encode("utf-8") + b"\n"


class _Ndjson:
    def __init__(self, lines, on_read=None) -> None:
        self._lines = list(lines)
        self.headers = {"X-Request-Id": "served-v4"}
        self.status = 200
        self._on_read = on_read

    def readline(self, limit: int = -1) -> bytes:
        if self._on_read is not None:
            self._on_read()
        return self._lines.pop(0) if self._lines else b""

    def read(self, size: int = -1) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def close(self) -> None:
        return None


class Agent:
    """Soxta agent: yo'l, sarlavhalar, tana; v4 kadrlari `lines` dan."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        #: v4 javobi (kadrlar) - test o'zi almashtiradi.
        self.lines: list[bytes] = [
            frame(type="stage", key="thinking", text="O'ylab ko'ryapman."),
            frame(type="ping"),
            frame(type="sources", items=[{"kind": "hrm", "marker": "T1", "tool": "crm_my_issues"}]),
            frame(type="token", text="Sizda 3 ta vazifa bor.", paced=True),
            frame(type="result", output={"x": 1}, cited_ids=[]),
            frame(**V4_DONE),
        ]
        self.error: BaseException | None = None
        self.on_read = None

    def open(self, request, timeout=None):
        parts = urllib.parse.urlsplit(request.full_url)
        body = json.loads(request.data) if request.data else None
        headers = {name.lower(): value for name, value in request.header_items()}
        self.calls.append({"path": parts.path, "body": body, "headers": headers})
        if self.error is not None:
            raise self.error
        if parts.path == "/api/pro/quota":
            return _Ndjson([json.dumps(QUOTA).encode()])
        if parts.path == "/api/v4/chat/stream":
            return _Ndjson(list(self.lines), on_read=self.on_read)
        version = parts.path.split("/")[2]
        return _Ndjson([frame(type="token", text="Javob"),
                        frame(type="done", route="rules", request_id="r-1", engine=version)])

    def streams(self) -> list[dict]:
        return [c for c in self.calls if c["path"].endswith("/chat/stream")]


@pytest.fixture
def agent(monkeypatch):
    fake = Agent()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    return fake


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_client(**kw) -> AssistantClient:
    kw.setdefault("timeout", 5)
    kw.setdefault("max_concurrent", 2)
    return AssistantClient(BASE, "venera", "sir", **kw)


def frames_of(stream) -> list[dict]:
    return [json.loads(line) for line in stream.frames]


@pytest.fixture(autouse=True)
def _fresh_cache():
    control.invalidate()
    yield
    control.invalidate()


@pytest.fixture
def wired(monkeypatch, agent, tmp_path):
    """`chat` moduli soxta agent ustida; CRM sessiyasi va umumiy tokenlar yo'q."""
    import app.api.v1.chat as chat_module
    from app.services.integrations.crm_auth import CrmAuth

    monkeypatch.setattr(chat_module, "_assistant", make_client())
    monkeypatch.setattr(chat_module, "_crm", CrmAuth("", "", "", tmp_path / "crm"))
    monkeypatch.setattr(chat_module, "platform_tokens", dict)
    return chat_module


@pytest.fixture
def db(_isolated_analytics):
    return _isolated_analytics


def grant(db, actor_id: int, granted: list[str], default: str | None = None) -> None:
    db.execute("INSERT OR REPLACE INTO engine_access (actor_id, engines, default_engine, "
               "updated_at, updated_by) VALUES (?,?,?,?,?)",
               (actor_id, json.dumps(granted), default, time.time(), "test"))
    control.invalidate()


def lines(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def rows(db, sql: str, params=()) -> list[dict]:
    assert analytics.flush(5.0)
    return db.rows(sql, params)


# ================================================================ katalog va yo'l


def test_v4_katalogda_pro_va_qonun_bilan():
    assert {"id": "v4", "pro": True, "law": True} in engines.catalog()
    assert engines.catalog_id(" V4 ") == "v4" and engines.normalize("v4") == "v4"
    assert engines.pro_available("v4")
    assert stream_path("v4") == "/api/v4/chat/stream"
    # Kod default'i O'ZGARMAYDI: v4 ni faqat admin beradi.
    assert engines.DEFAULT_ENGINE == "v2"


# ================================================================ so'rov


def test_v4_sorovi_shartnoma_sarlavhasi_va_maqsad_bilan(agent):
    stream = make_client().stream("Vazifalarim qanday?", user_id="venera:7", chat_id="c-1",
                                  tokens={"crm": "crm-jwt", "hrm": ""}, mode="pro", engine="v4")
    frames_of(stream)
    [call] = agent.calls
    assert call["path"] == "/api/v4/chat/stream"
    assert call["headers"]["x-barno-contract"] == "4.0"
    # Ilova kaliti v3 dagi kabi (agentda `require_client` bitta).
    assert call["headers"]["x-client-id"] == "venera"
    assert call["headers"]["x-client-secret"] == "sir"
    assert call["headers"]["x-request-id"]
    assert call["body"] == {
        "question": "Vazifalarim qanday?", "user_id": "venera:7", "chat_id": "c-1",
        "tokens": {"crm": "crm-jwt"}, "mode": "pro",
        "purpose": "chat", "store": True, "chat_visibility": "personal",
    }


def test_ovozli_uslub_faqat_v4_da(agent):
    client = make_client()
    frames_of(client.stream("savol", user_id="venera:7", engine="v4", style="voice"))
    frames_of(client.stream("savol", user_id="venera:7", engine="v4"))
    frames_of(client.stream("savol", user_id="venera:7", engine="v3", style="voice"))
    voice, text, v3 = agent.calls
    assert voice["body"]["style"] == "voice"
    assert "style" not in text["body"]
    # v3 - bugungi so'rov, bir harf ham o'zgarmagan.
    assert v3["path"] == "/api/v3/chat/stream"
    assert v3["body"] == {"question": "savol", "user_id": "venera:7"}
    assert "x-barno-contract" not in v3["headers"]


# ================================================================ kadrlar


def test_v4_kadrlari_klientga_v3_shaklida(agent):
    stream = make_client().stream("savol", user_id="venera:7", engine="v4")
    got = frames_of(stream)
    # `ping` va `result` - xizmat kadrlari, klientga o'tmaydi.
    assert [f["type"] for f in got] == ["stage", "sources", "token", "done"]
    assert got[2]["text"] == "Sizda 3 ta vazifa bor."
    done = got[-1]
    assert "meta" not in done and "cited_ids" not in done
    assert done["engine"] == "v4" and done["trace_id"] == "tr-4"
    assert done["task"] == {"intent": "crm.list", "state": "done"}
    assert stream.outcome == {"route": "crm", "engine": "v4", "frames": 4}


def test_ovozli_gaplar_bosliq_bilan_qoshiladi(agent):
    agent.lines = [
        frame(type="stage", key="hrm_tool", text="CRM tizimini tekshiryapman.", speak=True),
        frame(type="token", text="DVSIB loyihasida 13 ta vazifa bor.", sentence=1),
        frame(type="token", text="Qolganini aytaymi?", sentence=2),
        frame(type="token", text=" Allaqachon bo'shliqli.", sentence=3),
        frame(type="done", route="crm", request_id="r", engine="v4",
              voice={"sentences": 3, "words": 11}),
    ]
    got = frames_of(make_client().stream("savol", user_id="venera:7", engine="v4", style="voice"))
    texts = [f["text"] for f in got if f["type"] == "token"]
    # Klientlar bo'laklarni to'g'ridan-to'g'ri qo'shadi - ekranda gaplar ajralib tursin.
    assert "".join(texts) == ("DVSIB loyihasida 13 ta vazifa bor. Qolganini aytaymi? "
                              "Allaqachon bo'shliqli.")


def test_matnli_bolaklarga_bosliq_qoshilmaydi(agent):
    agent.lines = [frame(type="token", text="Sizda ", paced=True),
                   frame(type="token", text="3 ta", paced=True),
                   frame(type="done", route="crm", request_id="r", engine="v4")]
    got = frames_of(make_client().stream("savol", user_id="venera:7", engine="v4"))
    assert "".join(f["text"] for f in got if f["type"] == "token") == "Sizda 3 ta"


def test_v3_kadrlariga_tegilmaydi(agent, monkeypatch):
    """v3 yo'lida `ping` ham, `meta` ham bo'lsa - avvalgidek O'ZGARISHSIZ o'tadi."""
    original = agent.open

    def v3_open(request, timeout=None):
        response = original(request, timeout)
        if "/api/v3/" in request.full_url:
            response._lines = [frame(type="ping"), frame(type="done", route="r", request_id="x",
                                                         meta={"trace_id": "t"})]
        return response

    monkeypatch.setattr(agent, "open", v3_open)
    got = frames_of(make_client().stream("savol", user_id="venera:7", engine="v3"))
    assert got == [{"type": "ping"}, {"type": "done", "route": "r", "request_id": "x",
                                      "meta": {"trace_id": "t"}}]


# ================================================================ jimlik va xatolar


def test_ping_jimlikni_uzaytirmaydi(agent):
    """Agent tirik (`ping`), lekin javob yo'q: `timeout` dan keyin 504 - v3 dagi kabi."""
    clock = Clock()
    agent.lines = [frame(type="stage", text="..."), frame(type="ping"), frame(type="ping"),
                   frame(type="token", text="kech")]
    # Har o'qishda soat shuncha soniya oldinga: 1-ping jimlikning 3-soniyasida (o'tadi),
    # 2-ping 6-soniyasida - `timeout` (5 s) dan oshdi.
    reads = iter([0, 3, 3])

    def tick() -> None:
        clock.now += next(reads, 0)

    agent.on_read = tick
    stream = make_client(timeout=5, clock=clock).stream("savol", user_id="venera:7", engine="v4")
    with pytest.raises(AssistantError) as caught:
        frames_of(stream)
    assert caught.value.status == 504 and caught.value.reason == "upstream_timeout"


def test_ping_timeout_ichida_bolsa_oqim_davom_etadi(agent):
    clock = Clock()
    agent.lines = [frame(type="stage", text="..."), frame(type="ping"),
                   frame(type="token", text="Javob"),
                   frame(type="done", route="rules", request_id="r", engine="v4")]
    agent.on_read = lambda: setattr(clock, "now", clock.now + 2)
    got = frames_of(make_client(timeout=5, clock=clock).stream("savol", user_id="venera:7",
                                                               engine="v4"))
    assert [f["type"] for f in got] == ["stage", "token", "done"]


def test_v4_xato_tanasi_kodi_bilan(agent):
    body = {"error": {"code": "invalid_request", "message": "purpose is required on contract v4 "
                      "requests.", "retryable": False, "details": {"field": "purpose"}}}
    agent.error = urllib.error.HTTPError(f"{BASE}/api/v4/chat/stream", 400, "Bad Request", {},
                                         io.BytesIO(json.dumps(body).encode()))
    with pytest.raises(AssistantError) as caught:
        make_client().stream("savol", user_id="venera:7", engine="v4")
    assert caught.value.status == 400 and caught.value.reason == "upstream_http"
    assert "invalid_request: purpose is required" in str(caught.value)


def test_v4_navbati_tola_v3_dagi_kabi_503(agent):
    body = {"error": {"code": "queue_full", "message": "Busy.", "retryable": True}}
    agent.error = urllib.error.HTTPError(f"{BASE}/api/v4/chat/stream", 503, "busy", {},
                                         io.BytesIO(json.dumps(body).encode()))
    with pytest.raises(AssistantError) as caught:
        make_client().stream("savol", user_id="venera:7", engine="v4")
    assert caught.value.status == 503 and caught.value.reason == "upstream_busy"


# ================================================================ admin: bitta odamga


def test_v4_bitta_odamga_berilsa_faqat_uning_savoli_v4_ga(wired, client, auth, user_auth,
                                                          agent, db):
    grant(db, DEMO_ID, ["v3", "v4"], "v4")
    mine = client.post("/api/v1/chat/stream", headers={**user_auth, "X-Venera-Client": "web"},
                       json={"question": "Vazifalarim qanday?", "chatId": "c-9"})
    other = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                        json={"question": "savol"})
    assert mine.status_code == other.status_code == 200
    assert [c["path"] for c in agent.streams()] == ["/api/v4/chat/stream", "/api/v2/chat/stream"]
    sent = agent.streams()[0]
    assert sent["headers"]["x-barno-contract"] == "4.0"
    assert sent["body"]["purpose"] == "chat" and sent["body"]["chat_id"] == "c-9"
    assert sent["body"]["user_id"] == f"venera:{DEMO_ID}"
    got = lines(mine)
    assert [f["type"] for f in got] == ["stage", "sources", "token", "done"]
    assert got[-1]["engine"] == "v4" and "meta" not in got[-1]
    recorded = rows(db, "SELECT id, engine FROM turns ORDER BY started_at")
    assert [r["engine"] for r in recorded] == ["v4", "v2"]
    [done] = rows(db, "SELECT payload FROM turn_events WHERE turn_id=? AND name='done'",
                  (mine.headers["x-venera-turn"],))
    assert json.loads(done["payload"])["trace_id"] == "tr-4"
    # Xizmat kadrlari izga ham tushmaydi.
    names = {r["name"] for r in rows(db, "SELECT name FROM turn_events WHERE turn_id=?",
                                     (mine.headers["x-venera-turn"],))}
    assert not names & {"ping", "result"}


def test_v4_hammaga_siyosat_bilan(wired, client, auth, agent, db):
    db.execute("INSERT OR REPLACE INTO engine_policy (key, value, updated_at, updated_by) "
               "VALUES ('default', 'v4', ?, 'test')", (time.time(),))
    control.invalidate()
    response = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                           json={"question": "savol"})
    assert response.status_code == 200
    assert agent.streams()[0]["path"] == "/api/v4/chat/stream"


@pytest.mark.parametrize(("channel", "extra", "style"), [
    ("web", {"voice": True}, "voice"),                      # web ovoz paneli
    ("mobile", {"voice": True, "input": "voice"}, "voice"),  # Android ovoz rejimi
    ("web", {"voice": True, "input": "text"}, None),         # yozilgan savol
    ("miniapp", {"voice": True}, None),                      # o'qib berish yoqiq, lekin yozilgan
    ("web", {}, None),
])
def test_gapirilgan_savolda_ovozli_uslub(wired, client, auth, agent, db, channel, extra, style):
    grant(db, 1, ["v4"], "v4")                              # conftest: admin@venera.uz
    response = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": channel},
                           json={"question": "Vazifalarim?", "locale": "ru", **extra})
    assert response.status_code == 200
    [sent] = agent.streams()
    assert sent["path"] == "/api/v4/chat/stream"
    assert sent["body"].get("style") == style


def test_ovozda_ha_bilan_bajarilgan_amal_izda(wired, client, auth, agent, db):
    """Ovozli uslubda "ha" - tasdiq: agent taklifni o'zi bajaradi va `action` kadrini
    yuboradi. Taklif holati izda tugma bosilgandagi kabi yangilanadi, kalit esa vaqt
    chizig'iga tushmaydi."""
    grant(db, 1, ["v4"], "v4")
    agent.lines = [frame(type="token", text="Vazifani ochaymi?", sentence=1),
                   frame(type="proposal", proposal={"token": "tok-77", "summary": "Ovoz sinovi",
                                                    "operation": "create_issue"}),
                   frame(type="done", route="crm", request_id="r", engine="v4")]
    first = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                        json={"question": "Ovoz sinovi vazifasini och", "voice": True,
                              "locale": "ru"})
    agent.lines = [frame(type="token", text="Tayyor, vazifa CRMda ochildi.", sentence=1),
                   frame(type="action", action={"token": "tok-77", "status": "executed",
                                                "summary": "Ovoz sinovi",
                                                "result": {"key": "DVSIB-12"}}),
                   frame(type="done", route="crm", request_id="r2", engine="v4")]
    second = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                         json={"question": "ha", "voice": True, "locale": "ru"})
    assert first.status_code == second.status_code == 200
    assert [c["body"].get("style") for c in agent.streams()] == ["voice", "voice"]
    [turn] = rows(db, "SELECT proposal_status FROM turns WHERE id=?",
                  (first.headers["x-venera-turn"],))
    assert turn["proposal_status"] == "executed"
    [action] = rows(db, "SELECT payload FROM turn_events WHERE turn_id=? AND name='action'",
                    (second.headers["x-venera-turn"],))
    payload = json.loads(action["payload"])
    assert payload == {"status": "executed", "summary": "Ovoz sinovi",
                       "result": {"key": "DVSIB-12"}}
    assert "tok-77" not in action["payload"]


def test_pro_byudjeti_v4_da_bor(wired, client, user_auth, agent, db):
    grant(db, DEMO_ID, ["v4"], "v4")
    body = client.get("/api/v1/pro/quota", headers={**user_auth, "X-Venera-Client": "web"}).json()
    assert body["engine"] == "v4" and body["available"] is True

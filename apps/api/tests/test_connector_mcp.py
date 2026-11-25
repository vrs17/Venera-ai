"""Barno konnektorining MCP serveri - `POST /mcp` (`connector/mcp.py`) va Plaud vositalari (`plaud_tools.py`).

Ruxsat (grant) haqiqiy ombor orqali yasaladi (`core.store()`: mijoz -> so'rov -> rozilik -> token), yig'ilishlar -
`meetings_fakes` bilan (GAPI va model soxta, tarmoq yo'q). Bosh kalit har testda o'chiq (`conftest`), kerakli test
`on` fiksturasi bilan yoqadi.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3

import pytest

from app.connector import core, mcp, plaud_tools
from app.core.config import settings
from app.services.analytics import meter
from app.services.meetings import minutes
from conftest import ADMIN, USER
from meetings_fakes import DEFAULT_RESULT, enable, gapi_segments, recorded, run_all

CLIENT = "https://claude.ai/oauth/test-client"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
METADATA = "https://barno.test/.well-known/oauth-protected-resource/mcp"
PLAUD = frozenset({"plaud.read"})
TOOL_NAMES = {"search_meetings", "get_meeting", "get_summary", "get_transcript", "list_action_items",
              "get_minutes", "search", "fetch"}


@pytest.fixture
def on(client, monkeypatch):
    """Konnektor va yig'ilishlar yoqiq (bosh kalit va foydalanuvchilar ombori - `conftest`)."""
    monkeypatch.setattr(settings, "mcp_connector_enabled", True)
    enable(monkeypatch)
    return client


def make_grant(actor_id: int = 1, subject: str = ADMIN["email"], *, scopes=PLAUD, resource: str | None = None,
               client_id: str = CLIENT, token_version: int = 0):
    """Haqiqiy ruxsat: mijoz -> so'rov -> rozilik -> access token. -> (token, ruxsat)."""
    st = core.store()
    st.put_client(client_id, "cimd", "Claude", [CALLBACK], {})
    pending = st.put_request(client_id, CALLBACK, "state", "c" * 43, scopes, resource or core.mcp_resource())
    st.approve(pending, subject=subject, actor_id=actor_id, token_version=token_version, client_name="Claude",
               scopes=scopes)
    row = next(g for g in st.grants_of(actor_id) if g.client_id == client_id)
    return st.issue(row.id, access_ttl=3600, refresh_ttl=86400).access_token, row


def post(client, token: str | None, body, **headers):
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = body if isinstance(body, (str, bytes)) else json.dumps(body)
    return client.post("/mcp", content=data, headers={"Content-Type": "application/json", **headers})


def rpc(client, token, method: str, params=None, *, msg_id=1, **headers):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return post(client, token, body, **headers)


def call(client, token, tool: str, **args) -> dict:
    response = rpc(client, token, "tools/call", {"name": tool, "arguments": args})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def ok(result: dict) -> dict:
    assert result["isError"] is False, result
    assert result["content"][0]["type"] == "text"
    return result["structuredContent"]


def calls(where: str = "1=1") -> list[dict]:
    conn = sqlite3.connect(core.store().path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM calls WHERE {where} ORDER BY ts, rowid")]
    finally:
        conn.close()


@pytest.fixture
def meeting(on, auth, _isolated_meetings) -> str:
    """Adminning tayyor yig'ilishi (transkript, xulosa, vazifalar)."""
    m, _ = recorded(on, auth)
    run_all(_isolated_meetings)
    return m["id"]


# --- eshik: bosh kalit, Origin, versiya, usul ----------------------------------------------------


def test_bosh_kalit_ochiq_404(client, monkeypatch):
    for method in ("post", "get", "delete"):
        assert getattr(client, method)("/mcp").status_code == 404
    monkeypatch.setattr(settings, "mcp_connector_enabled", True)
    monkeypatch.setattr(settings, "mcp_public_url", "")
    monkeypatch.setattr(settings, "sso_app_url", "")
    assert client.post("/mcp").status_code == 404                       # manzil yo'q - ham 404


def test_get_va_delete_405(on):
    for method in ("get", "delete"):
        response = getattr(on, method)("/mcp")
        assert response.status_code == 405 and response.headers["allow"] == "POST"


def test_origin_va_versiya(on):
    token, _ = make_grant()
    assert rpc(on, token, "ping", Origin="https://evil.example").status_code == 403
    assert rpc(on, token, "ping", Origin="null").status_code == 403
    for origin in ("https://claude.ai", "https://chatgpt.com", "https://claude.com", "https://barno.test"):
        assert rpc(on, token, "ping", Origin=origin).status_code == 200, origin
    response = rpc(on, token, "ping", **{"MCP-Protocol-Version": "2024-11-05"})
    assert response.status_code == 400
    assert rpc(on, token, "ping", **{"MCP-Protocol-Version": "2025-06-18"}).status_code == 200
    assert rpc(on, None, "ping", Origin="https://evil.example").status_code == 403   # Origin tokendan oldin


# --- token ----------------------------------------------------------------------------------------


def test_tokensiz_401_aniq_sarlavha(on):
    response = rpc(on, None, "initialize", {"protocolVersion": "2025-11-25"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == \
        f'Bearer resource_metadata="{METADATA}", scope="plaud.read"'


def test_yaroqsiz_token_401(on):
    expected = f'Bearer error="invalid_token", resource_metadata="{METADATA}", scope="plaud.read"'
    assert rpc(on, "not-a-real-token", "ping").headers["www-authenticate"] == expected
    # Boshqa manzil (`resource`) uchun berilgan token - bizda ishlamaydi.
    other, _ = make_grant(resource="https://other.test/mcp", client_id="https://claude.ai/oauth/other")
    response = rpc(on, other, "ping")
    assert response.status_code == 401 and response.headers["www-authenticate"] == expected
    # Bekor qilingan ruxsat.
    token, grant = make_grant()
    assert rpc(on, token, "ping").status_code == 200
    assert core.store().revoke_grant(1, grant.id)
    assert rpc(on, token, "ping").status_code == 401
    # "Hamma joydan chiqarish" dan oldingi versiya.
    stale, _ = make_grant(token_version=7, client_id="https://chatgpt.com/oauth/client.json")
    assert rpc(on, stale, "ping").status_code == 401


def test_bloklangan_hisob_401_va_ruxsat_bekor(on, auth):
    token, _ = make_grant(2, USER["email"])
    assert rpc(on, token, "ping").status_code == 200
    assert on.patch("/api/v1/admin/users/2", headers=auth, json={"disabled": True}).status_code == 200
    response = rpc(on, token, "ping")
    assert response.status_code == 401 and 'error="invalid_token"' in response.headers["www-authenticate"]
    assert core.store().grants_of(2) == []                               # "Ulangan ilovalar" dan ham ketdi


# --- protokol -------------------------------------------------------------------------------------


def test_initialize_ping_va_bildirishnoma(on):
    token, _ = make_grant()
    result = rpc(on, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "claude-ai", "version": "1"}}).json()
    assert result["id"] == 1 and result["jsonrpc"] == "2.0"
    init = result["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["capabilities"] == {"tools": {"listChanged": False}}
    assert init["serverInfo"] == {"name": "barno", "title": "Barno AI", "version": "1.0.0"}
    assert "read-only" in init["instructions"] and "ignore" not in init["instructions"].lower()
    unknown = rpc(on, token, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
    assert unknown["protocolVersion"] == "2025-11-25"
    assert rpc(on, token, "ping", msg_id="abc").json() == {"jsonrpc": "2.0", "id": "abc", "result": {}}
    note = post(on, token, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202 and note.content == b""
    reply = post(on, token, {"jsonrpc": "2.0", "id": 9, "result": {}})            # mijozning javobi
    assert reply.status_code == 202 and reply.content == b""
    assert "mcp-session-id" not in {k.lower() for k in note.headers}


def test_protokol_xatolari(on):
    token, _ = make_grant()
    batch = post(on, token, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert batch.status_code == 400 and batch.json()["error"]["code"] == -32600
    broken = post(on, token, "{not json")
    assert broken.status_code == 400 and broken.json()["error"]["code"] == -32700
    # Juda chuqur ichma-ichlik (RecursionError) va yolg'iz surrogat - 500 emas.
    deep = post(on, token, "[" * 100_000)
    assert deep.status_code == 400 and deep.json()["error"]["code"] == -32700
    lone = post(on, token, '{"jsonrpc": "2.0", "id": "\\ud800", "method": "ping"}')
    assert lone.status_code == 200 and lone.json()["result"] == {}
    weird = post(on, token, '{"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "\\ud800"}}')
    assert weird.status_code == 200 and weird.json()["error"]["code"] == -32602
    unknown = rpc(on, token, "resources/list")
    assert unknown.status_code == 200 and unknown.json()["error"]["code"] == -32601
    assert post(on, token, {"jsonrpc": "1.0", "id": 1, "method": "ping"}).json()["error"]["code"] == -32600
    assert post(on, token, {"jsonrpc": "2.0", "id": None, "method": "ping"}).status_code == 400
    assert rpc(on, token, "tools/call", ["x"]).json()["error"]["code"] == -32602
    assert post(on, token, "x" * (mcp.MAX_BODY + 1)).status_code == 413


# --- vositalar ro'yxati va qamrov -----------------------------------------------------------------


def test_tools_list_izohlar(on):
    token, _ = make_grant()
    tools = rpc(on, token, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == TOOL_NAMES
    for t in tools:
        assert len(t["name"]) <= 64 and t["title"] and t["description"]
        assert t["inputSchema"]["type"] == "object" and "outputSchema" not in t
        assert t["annotations"] == {"title": t["title"], "readOnlyHint": True, "destructiveHint": False,
                                    "idempotentHint": True, "openWorldHint": False}
    by_name = {t["name"]: t for t in tools}
    assert by_name["get_transcript"]["inputSchema"]["required"] == ["meeting_id"]
    assert by_name["search"]["inputSchema"]["required"] == ["query"]


def test_faqat_ruxsat_berilgan_qamrov(on):
    token, _ = make_grant(scopes=frozenset())
    assert rpc(on, token, "tools/list").json()["result"]["tools"] == []
    denied = rpc(on, token, "tools/call", {"name": "search_meetings", "arguments": {}}).json()
    assert denied["error"]["code"] == -32602
    full, _ = make_grant(client_id="https://chatgpt.com/oauth/client.json")
    unknown = rpc(on, full, "tools/call", {"name": "delete_everything", "arguments": {}}).json()
    assert unknown["error"]["code"] == -32602
    assert [(r["tool"], r["status"]) for r in calls()] == [("search_meetings", "denied"), ("unknown", "error")]


# --- Plaud vositalari -----------------------------------------------------------------------------


def test_search_meetings_faqat_ozinikini(on, auth, user_auth, meeting, _isolated_meetings):
    mine, _ = recorded(on, user_auth, title="Demo rejasi")
    run_all(_isolated_meetings)
    demo, _ = make_grant(2, USER["email"])
    admin, _ = make_grant()
    seen = ok(call(on, demo, "search_meetings"))
    assert [m["id"] for m in seen["meetings"]] == [mine["id"]] and seen["total"] == 1
    card = seen["meetings"][0]
    assert {"id", "title", "recorded_at", "duration_sec", "status", "summary_status", "open_action_items",
            "url"} <= set(card)
    assert card["url"] == f"https://barno.test/meeting/{mine['id']}"
    assert [m["id"] for m in ok(call(on, admin, "search_meetings"))["meetings"]] == [meeting]
    # Begona yig'ilish - "topilmadi" (bor-yo'qligi ham bilinmaydi), 500 emas.
    for tool in ("get_meeting", "get_summary", "get_transcript", "get_minutes"):
        result = call(on, demo, tool, meeting_id=meeting)
        assert result["isError"] is True and "not_found" in result["content"][0]["text"], tool
    assert call(on, demo, "fetch", id=meeting)["isError"] is True
    assert call(on, demo, "list_action_items", meeting_id=meeting)["isError"] is True
    items = ok(call(on, demo, "list_action_items", status="all"))["action_items"]
    assert items and {a["meeting_id"] for a in items} == {mine["id"]}
    assert meeting not in json.dumps(ok(call(on, demo, "search", query="")))


def test_search_meetings_sahifa_va_argumentlar(on, meeting):
    token, _ = make_grant()
    page = ok(call(on, token, "search_meetings", query="hisobot", limit="1"))
    assert page["limit"] == 1 and page["next_offset"] is None and len(page["meetings"]) == 1
    assert ok(call(on, token, "search_meetings", query="topilmaydigan-soz"))["meetings"] == []
    bad = call(on, token, "search_meetings", limit=500)
    assert bad["isError"] is True and "limit" in bad["content"][0]["text"]
    assert call(on, token, "search_meetings", origin="mars")["isError"] is True


def test_get_meeting_va_xulosa(on, meeting):
    token, _ = make_grant()
    card = ok(call(on, token, "get_meeting", meeting_id=meeting))
    assert card["id"] == meeting and card["transcript"]["available"] is True
    assert card["speakers"] and all(s["name"] for s in card["speakers"])
    assert card["summaries"] and card["summary_status"] == "ready"
    result = call(on, token, "get_summary", meeting_id=meeting)
    summary = ok(result)
    assert summary["summary_id"] == card["primary_summary_id"] and summary["truncated"] is False
    markdown = result["content"][0]["text"]
    assert markdown.startswith("#") and "Hisobot" in markdown
    # Ismsiz spiker - xulosa eksportidagi nom bilan bir xil (bir odam - bir nom).
    assert "1-ishtirokchi" in {s["name"] for s in card["speakers"]} and "1-ishtirokchi" in markdown
    same = ok(call(on, token, "get_summary", meeting_id=meeting, summary_id=summary["summary_id"]))
    assert same["summary_id"] == summary["summary_id"]
    missing = call(on, token, "get_summary", meeting_id=meeting, summary_id="f" * 32)
    assert missing["isError"] is True
    assert call(on, token, "get_meeting")["isError"] is True                     # meeting_id shart


def test_transkript_bolaklab(on, auth, _isolated_meetings):
    lines = [(i % 3, float(i), float(i) + 0.9, f"{i}-gap: hisobot bo'yicha muhokama davom etmoqda, navbat bilan.")
             for i in range(60)]
    _isolated_meetings.gapi.result = {**DEFAULT_RESULT, "segments": gapi_segments(lines)}
    m, _ = recorded(on, auth)
    run_all(_isolated_meetings)
    token, _ = make_grant()
    got, cursor, pages = [], None, 0
    while True:
        args = {"meeting_id": m["id"], "max_chars": 1000, **({"cursor": cursor} if cursor else {})}
        result = call(on, token, "get_transcript", **args)
        page = ok(result)
        text = result["content"][0]["text"]
        body = text.split("\n\n[Transcript continues")[0].splitlines()
        assert len(body) == page["returned_lines"] and len("\n".join(body)) <= 1000
        got += body
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert f'next_cursor: "{cursor}"' in text
    assert pages > 3 and len(got) == page["segment_count"] == 60
    assert got[0].startswith("[00:00:00] ") and ": 0-gap" in got[0] and got[-1].endswith("navbat bilan.")
    assert len(set(got)) == 60
    assert call(on, token, "get_transcript", meeting_id=m["id"], cursor="abc")["isError"] is True


def test_uzun_segment_bolaklanadi_matn_yoqolmaydi(on, auth, _isolated_meetings):
    """Byudjetdan uzun BITTA segment: kursor segment ichiga ko'rsatadi va butun matn qaytadi."""
    long_text = " ".join(f"so'z{i}" for i in range(1500))          # ~10 000 belgi
    lines = [(0, 0.0, 30.0, long_text), (1, 30.0, 31.0, "Oxirgi gap.")]
    _isolated_meetings.gapi.result = {**DEFAULT_RESULT, "segments": gapi_segments(lines)}
    m, _ = recorded(on, auth)
    run_all(_isolated_meetings)
    token, _ = make_grant()
    pages, cursor = [], None
    while True:
        args = {"meeting_id": m["id"], "max_chars": 1000, **({"cursor": cursor} if cursor else {})}
        page = call(on, token, "get_transcript", **args)
        body = page["content"][0]["text"].split("\n\n[Transcript continues")[0]
        assert len(body) <= 1000
        pages.append(body)
        cursor = page["structuredContent"]["next_cursor"]
        if cursor is None:
            break
    joined = "".join(line.split(": ", 1)[1].lstrip("…") if ": " in line else line
                     for page in pages for line in page.splitlines() if "Oxirgi" not in line)
    assert long_text.replace(" ", "") == joined.replace(" ", "")
    assert pages[-1].splitlines()[-1].endswith("Oxirgi gap.")
    assert len(pages) >= 10


def test_vazifalar(on, meeting, user_auth):
    token, _ = make_grant()
    per = ok(call(on, token, "list_action_items", meeting_id=meeting))
    assert per["status"] == "open" and per["count"] >= 1
    item = per["action_items"][0]
    assert {"id", "meeting_id", "task", "owner", "due_date", "priority", "status"} <= set(item)
    assert item["meeting_id"] == meeting and item["status"] == "open" and item["owner"]
    across = ok(call(on, token, "list_action_items"))
    assert [a["id"] for a in across["action_items"]] == [a["id"] for a in per["action_items"]]
    assert across["action_items"][0]["meeting_title"]
    assert ok(call(on, token, "list_action_items", status="done"))["action_items"] == []
    assert call(on, token, "list_action_items", status="later")["isError"] is True
    demo, _ = make_grant(2, USER["email"])
    assert ok(call(on, demo, "list_action_items", status="all"))["action_items"] == []


def test_bayonnoma(on, auth, meeting, monkeypatch):
    token, _ = make_grant()
    none = call(on, token, "get_minutes", meeting_id=meeting)
    assert none["isError"] is True and "minutes" in none["content"][0]["text"]
    queue: list = []
    monkeypatch.setattr(minutes, "runner", queue.append)
    monkeypatch.setattr(settings, "meetings_minutes_chain", "ollama", raising=False)
    started = on.post(f"/api/v1/meetings/{meeting}/minutes", json={"language": "uz-latn"}, headers=auth)
    assert started.status_code == 202, started.text
    while queue:
        queue.pop(0)()
    result = call(on, token, "get_minutes", meeting_id=meeting)
    doc = ok(result)
    assert doc["minutes_id"] == started.json()["id"] and doc["language"] == "uz-latn"
    assert doc["languages_available"] == ["uz-latn"] and result["content"][0]["text"].strip()
    assert call(on, token, "get_minutes", meeting_id=meeting, language="ru")["isError"] is True


def test_search_va_fetch_shakli(on, meeting):
    token, _ = make_grant()
    result = call(on, token, "search", query="hisobot")
    found = json.loads(result["content"][0]["text"])
    assert found == result["structuredContent"]
    assert found == {"results": [{"id": meeting, "title": found["results"][0]["title"],
                                  "url": f"https://barno.test/meeting/{meeting}"}]}
    # To'liq ibora topilmasa - so'zlar bo'yicha.
    words = json.loads(call(on, token, "search", query="hisobot budjeti haqida")["content"][0]["text"])
    assert [r["id"] for r in words["results"]] == [meeting]
    assert json.loads(call(on, token, "search", query="zzzz yyyy")["content"][0]["text"]) == {"results": []}
    doc_result = call(on, token, "fetch", id=meeting)
    doc = json.loads(doc_result["content"][0]["text"])
    assert set(doc) == {"id", "title", "text", "url", "metadata"} and doc == doc_result["structuredContent"]
    assert doc["id"] == meeting and doc["url"] == f"https://barno.test/meeting/{meeting}"
    assert "## Summary" in doc["text"] and "## Transcript" in doc["text"] and "Assalomu alaykum" in doc["text"]
    assert doc["metadata"]["summary_id"] and doc["metadata"]["transcript_truncated"] is False


def test_tayyor_bolmagan_yigilish(on, auth):
    m, _ = recorded(on, auth)                                       # ishchi yurmagan - transkript yo'q
    token, _ = make_grant()
    pending = call(on, token, "get_transcript", meeting_id=m["id"])
    assert pending["isError"] is True and "not_ready" in pending["content"][0]["text"]
    assert call(on, token, "get_summary", meeting_id=m["id"])["isError"] is True
    doc = json.loads(call(on, token, "fetch", id=m["id"])["content"][0]["text"])
    assert doc["id"] == m["id"] and "## Transcript" not in doc["text"] and doc["metadata"]["summary_id"] is None


# --- holatlar: bo'lim o'chiq, chegara, kutilmagan xato, hisob konteksti ---------------------------------


def test_yigilishlar_bolimi_ochiq_iserror(on, monkeypatch):
    token, _ = make_grant()
    monkeypatch.setattr(settings, "meetings_enabled", False)
    result = call(on, token, "search_meetings")
    assert result["isError"] is True and "turned off" in result["content"][0]["text"]
    assert calls()[-1]["status"] == "denied"


def test_tezlik_chegarasi(on):
    token, grant = make_grant()
    for _ in range(mcp.RATE_LIMIT - 1):
        core.record_call(grant, "search_meetings", "ok", 1, 10)
    assert call(on, token, "search_meetings")["isError"] is False            # 60-chi - hali mumkin
    limited = call(on, token, "search_meetings")
    assert limited["isError"] is True and "Rate limit" in limited["content"][0]["text"]
    assert calls()[-1]["status"] == "denied"
    # Rad etilgan chaqiruvlar chegaraga qo'shilmaydi - to'xtamay so'ragan mijoz ham daqiqadan keyin chiqadi.
    call(on, token, "search_meetings")
    assert core.store().calls_since(grant.id, 0) == mcp.RATE_LIMIT
    other, _ = make_grant(client_id="https://chatgpt.com/oauth/client.json")  # boshqa ruxsat - alohida
    assert call(on, other, "search_meetings")["isError"] is False


def test_kutilmagan_xato_500_emas_va_hisob_konteksti(on, monkeypatch):
    token, _ = make_grant(2, USER["email"])
    seen = {}

    def spy(user, args):
        seen["actor"], seen["channel"] = meter.current_actor.get(), meter.current_channel.get()
        raise RuntimeError("boom")

    tool = plaud_tools.TOOLS["search_meetings"]
    monkeypatch.setitem(plaud_tools.TOOLS, "search_meetings", dataclasses.replace(tool, handler=spy))
    result = call(on, token, "search_meetings")
    assert result["isError"] is True and "boom" not in result["content"][0]["text"]
    assert seen == {"actor": 2, "channel": "api"}
    assert calls()[-1]["status"] == "error"


def test_jurnal_matnsiz(on, meeting):
    token, grant = make_grant()
    call(on, token, "get_transcript", meeting_id=meeting)
    call(on, token, "get_summary", meeting_id=meeting)
    call(on, token, "get_meeting", meeting_id="0" * 32)
    rows = calls()
    assert [(r["tool"], r["status"]) for r in rows] == [("get_transcript", "ok"), ("get_summary", "ok"),
                                                        ("get_meeting", "error")]
    assert set(rows[0]) == {"ts", "grant_id", "actor_id", "client_id", "tool", "status", "ms", "out_bytes"}
    assert all(r["grant_id"] == grant.id and r["actor_id"] == 1 and r["client_id"] == CLIENT for r in rows)
    assert rows[0]["out_bytes"] > 200 and rows[2]["out_bytes"] > 0
    dump = json.dumps(rows, ensure_ascii=False)
    for phrase in ("Assalomu", "hisobot", "Hisobot", meeting):
        assert phrase not in dump
    assert core.store().grants_of(1)[0].last_used_at is not None
    assert rpc(on, token, "ping").status_code == 200 and len(calls()) == 3     # ping jurnalga tushmaydi


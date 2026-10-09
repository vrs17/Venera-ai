"""Admin panel API: huquq, javob shakllari, filtrlar, sahifalash, audit.

Ombor HAR TESTDA vaqtinchalik (`conftest._isolated_analytics`). Ma'lumot
qo'lda, aniq vaqtlar bilan yoziladi (`_seed`) - shunda har raqamni
oldindan hisoblab, aynan tekshirish mumkin. Bitta test esa yozuvni haqiqiy
yo'ldan (`TurnRecorder` -> yozuvchi ip) o'tkazib, panel uni ko'rishini
tekshiradi. Tashqi xizmat chaqirilmaydi.
"""

from __future__ import annotations

import json
import sys

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.services import analytics
from app.services.analytics import queries
from app.services.analytics.recorder import TurnRecorder

API = "/api/v1/admin"

#: 2026-09-20 00:00 UTC - hamma vaqtlar shundan hisoblanadi.
T0 = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()
H = 3600.0


def at(hours: float) -> str:
    """T0 + soat -> ISO (so'rov parametri uchun)."""
    return queries.iso(T0 + hours * H)


# --- types.ts bilan shartnoma: maydonlar TO'PLAMI aynan ---------------------------

TURN_SUMMARY = {
    "id", "startedAt", "actorId", "userName", "userLogin", "channel", "kind", "inputMode",
    "chatId", "question", "route", "status", "errorCode", "ttftMs", "totalMs", "sourcesCount",
    "toolCalls", "hasProposal", "proposalStatus", "hasArtifact", "reported", "engine",
}
TURN_DETAIL = TURN_SUMMARY | {
    "answer", "requestId", "locale", "endedAt", "httpStatus", "errorText", "events", "sources",
    "apiCalls", "chatTurns", "reports",
}
TURN_EVENT = {"seq", "tMs", "durMs", "type", "name", "payload"}
TURN_SOURCE = {"idx", "kind", "ref", "title", "page", "score", "snippet", "status", "digest",
               "citation"}
API_CALL = {"id", "ts", "service", "op", "status", "httpStatus", "durationMs", "actorId",
            "channel", "turnId", "units", "error"}
CHAT_TURN = {"id", "startedAt", "question", "status"}
REPORT_SUMMARY = {"id", "createdAt", "actorId", "userName", "channel", "chatId", "turnId",
                  "reason", "commentPreview", "status", "messages"}
REPORT_DETAIL = REPORT_SUMMARY | {"comment", "snapshot", "adminNote", "updatedAt", "updatedBy"}
ADMIN_CHAT = {"chatId", "actorId", "userName", "channel", "firstAt", "lastAt", "turns", "errors",
              "reported", "title"}
OVERVIEW = {"range", "kpis", "activity", "channels", "routes", "engines", "latency", "topDocs",
            "tools", "recentReports", "slowTurns"}
ENGINE_STAT = {"engine", "turns", "errors", "medianTtftMs"}
OVERVIEW_RANGE = {"from", "to", "prevFrom", "prevTo", "bucket"}
KPIS = {"turns", "activeUsers", "medianTtftMs", "errorRate", "newReports"}
KPI = {"value", "prev", "spark"}
USAGE = {"services", "series", "byChannel", "ops"}
USAGE_SERVICE = {"service", "requests", "errors", "errorRate", "p50Ms", "p95Ms", "units", "spark"}
USAGE_OP = {"service", "op", "requests", "errors", "p95Ms"}
SYSTEM = {"health", "config", "storage", "audit"}
SYSTEM_CONFIG = {"ssoEnabled", "localLoginEnabled", "telegramMode", "telegramBotEnabled",
                 "retentionDays", "analyticsEnabled"}
STORAGE = {"dbBytes", "turns", "events", "apiCalls", "reports", "dropped"}
AUDIT_ENTRY = {"id", "createdAt", "adminActorId", "adminName", "action", "targetType",
               "targetId", "detail"}


# --- ma'lumot ---------------------------------------------------------------------------

_TURN_COLUMNS = (
    "id", "started_at", "ended_at", "actor_id", "user_name", "user_login", "channel", "kind",
    "input_mode", "locale", "chat_id", "request_id", "question", "answer", "route", "status",
    "error_code", "error_text", "http_status", "ttft_ms", "total_ms", "frames",
    "sources_count", "tool_calls", "has_artifact", "has_proposal", "proposal_token",
    "proposal_status", "answer_chars", "engine",
)


def tid(letter: str) -> str:
    """Savol kaliti: 32 hex (haqiqiydek)."""
    return (letter.encode().hex() * 32)[:32]


A, B, C, D, E, F, G, HH = (tid(x) for x in "ABCDEFGH")

#: Dvigatel (sxema v2): A, B - v2; C, D - v1 (mini app eski dvigatelda); qolgani
#: NULL - versiyasiz yo'l yoki eski yozuv ("default").
ENGINE_OF = {A: "v2", B: "v2", C: "v1", D: "v1"}

#: (kalit, soat, actor, ism, login, kanal, kind, input, chat, savol, javob, route, holat,
#:  xato kodi, ttft, total, request_id)
TURNS = [
    (A, 1, 11, "Aziza Karimova", "a.karimova", "web", "chat", "text", "c1",
     "Mehnat ta'tili necha kun?", "Yillik asosiy ta'til 21 kalendar kun [1].", "rules", "ok",
     None, 1200, 5200, "req-a"),
    (B, 2, 11, "Aziza Karimova", "a.karimova", "web", "chat", "text", "c1",
     "Qo'shimcha ta'til kimga beriladi?", "Nogironligi bor xodimlarga [1] [2].", "rules", "ok",
     None, 1500, 6100, "req-b"),
    (C, 3, 12, "Bobur Aliyev", "b.aliyev", "miniapp", "chat", "text", "c2",
     "Bugun kechikdimmi?", "Yo'q, 08:52 da kelgansiz [T1].", "hrm", "ok",
     None, 800, 2100, "req-c"),
    (D, 4, 12, "Bobur Aliyev", "b.aliyev", "miniapp", "chat", "text", "c2",
     "CRM dagi vazifalarim", None, "crm", "error",
     "auth_missing", None, 900, "req-d"),
    (E, 5, 13, "Dilnoza Rahimova", "d.rahimova", "bot", "bot", "voice", "c3",
     "Xizmat safari kunlik puli qancha?", "Kunlik xarajat eng kam ish haqining 10% [1].",
     "rules", "ok", None, 2500, 9800, "req-e"),
    (F, 6, 13, "Dilnoza Rahimova", "d.rahimova", "bot", "bot", "text", "c3",
     "Ta'til uchun ariza yozib bering", "Ariza tayyor.", "rules", "ok",
     None, 3000, 15000, "req-f"),
    (G, 30, 11, "Aziza Karimova", "a.karimova", "web", "chat", "text", "c4",
     "Отпуск по уходу за ребёнком", None, None, "cancelled",
     None, None, 400, None),
    (HH, 50, 14, None, None, "api", "ask", "text", None,
     "Salom", None, "clarify", "running",
     None, None, None, None),
]

REPORTS = [
    # (id, soat, actor, ism, kanal, chat, turn, sabab, izoh, holat, nusxa xabarlari)
    ("rep-1", 7, 11, "Aziza Karimova", "web", "c1", B, "wrong",
     "Javob eskirgan nizomga tayangan\nikkinchi qator", "new",
     [{"role": "user", "content": "Mehnat ta'tili necha kun?", "turnId": A},
      {"role": "assistant", "content": "21 kun", "turnId": A},
      {"role": "user", "content": "Qo'shimcha ta'til kimga beriladi?", "turnId": B},
      {"role": "assistant", "content": "Nogironligi bor xodimlarga", "turnId": B}]),
    ("rep-2", 8, 13, "Dilnoza Rahimova", "bot", "c3", None, "incomplete", None, "reviewing",
     [{"role": "user", "content": "Xizmat safari kunlik puli qancha?", "turnId": E},
      {"role": "assistant", "content": "Kunlik xarajat ...", "turnId": E}]),
    ("rep-3", 40, 12, "Bobur Aliyev", "miniapp", "c2", D, "other", "", "resolved", []),
    ("rep-4", 60, 12, "Bobur Aliyev", "miniapp", None, None, None, "Umuman javob yo'q",
     "dismissed", [{"role": "user", "content": "Salom"}]),
]


def _seed(db) -> None:
    with db.transaction() as conn:
        for (key, hours, actor, name, login, channel, kind, mode, chat, question, answer,
             route, status, code, ttft, total, request) in TURNS:
            start = T0 + hours * H
            values = {
                "id": key, "started_at": start,
                "ended_at": start + total / 1000 if total else None,
                "actor_id": actor, "user_name": name, "user_login": login, "channel": channel,
                "kind": kind, "input_mode": mode, "locale": "uz", "chat_id": chat,
                "request_id": request, "question": question, "answer": answer, "route": route,
                "status": status, "error_code": code,
                "error_text": "Bu savol uchun CRM hisobi kerak" if code else None,
                "http_status": 200 if status == "ok" else None,
                "ttft_ms": ttft, "total_ms": total, "frames": 12,
                "sources_count": {A: 2, B: 2, E: 1}.get(key, 0),
                "tool_calls": 1 if key in (C, D) else 0,
                "has_artifact": 1 if key == F else 0,
                "has_proposal": 1 if key == F else 0,
                "proposal_token": "tok-f" if key == F else None,
                "proposal_status": "executed" if key == F else None,
                "answer_chars": len(answer or ""),
                "engine": ENGINE_OF.get(key),
            }
            conn.execute(
                f"INSERT INTO turns ({', '.join(_TURN_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(_TURN_COLUMNS))})",
                tuple(values[c] for c in _TURN_COLUMNS))
        conn.executemany(
            "INSERT INTO turn_sources (turn_id, idx, kind, ref, title, page, score, snippet, "
            "status, digest, citation, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
                (A, 0, "doc", "tatil-nizom", "Mehnat ta'tillari nizomi", 3, 0.91,
                 "Yillik asosiy ta'til 21 kalendar kundan kam bo'lmaydi.", None, None, 1, "{}"),
                (A, 1, "doc", "tatil-nizom", "Mehnat ta'tillari nizomi", 4, 0.84,
                 "Ta'til ish yili uchun beriladi.", None, None, 1, "{}"),
                (B, 0, "doc", "tatil-nizom", "Mehnat ta'tillari nizomi", 7, 0.88,
                 "Qo'shimcha ta'til ...", None, None, 1, "{}"),
                (B, 1, "doc", "ichki-tartib", "Ichki mehnat tartibi qoidalari", 12, 0.71,
                 "Ish vaqti 09:00 dan ...", None, None, 2, "{}"),
                (C, 0, "hrm", "hrm_today_late", None, None, None, None, "200",
                 "kechikish yo'q, kelish 08:52", 1, "{}"),
                (D, 0, "crm", "crm_my_issues", None, None, None, None, "error",
                 "auth_missing", 1, "{}"),
                (E, 0, "doc", "safar-yoriqnoma", "Xizmat safarlari yo'riqnomasi", 2, 0.93,
                 "Kunlik xarajatlar ...", None, None, 1, "{}"),
            ])
        conn.executemany(
            "INSERT INTO turn_events (turn_id, seq, t_ms, dur_ms, type, name, payload) "
            "VALUES (?,?,?,?,?,?,?)", [
                (A, 0, 3, 210, "span", "assistant.open", json.dumps({"requestId": "req-a"})),
                (A, 1, 215, None, "note", "first_frame", json.dumps({"type": "stage"})),
                (A, 2, 216, None, "frame", "stage", json.dumps({"text": "Hujjatlar qidirilmoqda"})),
                (A, 3, 900, None, "frame", "sources",
                 json.dumps({"count": 2, "docs": 2, "tools": 0, "refs": ["tatil-nizom"]})),
                (A, 4, 1200, None, "note", "first_token", None),
                (A, 5, 5100, None, "frame", "done", json.dumps({"route": "rules"})),
            ])
        calls = [
            # (soat, service, op, status, http, ms, actor, kanal, turn, units)
            (1, "assistant", "stream", "ok", 200, 5200, 11, "web", A, {"frames": 40}),
            (2, "assistant", "stream", "ok", 200, 6100, 11, "web", B, {"frames": 52}),
            (3, "assistant", "stream", "ok", 200, 2100, 12, "miniapp", C, {"frames": 20}),
            (4, "assistant", "stream", "error", 401, 900, 12, "miniapp", D, {"frames": 2}),
            (5, "assistant", "stream", "ok", 200, 9800, 13, "bot", E, {"frames": 80}),
            (6, "assistant", "stream", "ok", 200, 15000, 13, "bot", F, {"frames": 95}),
            (1, "tts", "speak", "ok", 200, 1400, 11, "web", None, {"chars": 300}),
            (3, "tts", "speak", "error", 503, 50, 12, "miniapp", None, {"chars": 50}),
            (5, "stt_router", "transcribe", "ok", 200, 1200, 13, "bot", None, {"audioSec": 4.5}),
            (0.5, "keycloak", "authenticate", "ok", 200, 300, None, None, None, None),
            (5, "telegram", "sendMessage", "ok", 200, 150, 13, "bot", None, None),
        ]
        conn.executemany(
            "INSERT INTO api_calls (ts, service, op, status, http_status, duration_ms, actor_id, "
            "channel, turn_id, units, error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(T0 + h * H, s, o, st, http, ms, actor, ch, turn,
              json.dumps(units) if units else None,
              "HTTP 401: auth_missing" if st == "error" else None)
             for h, s, o, st, http, ms, actor, ch, turn, units in calls])
        for (rid, hours, actor, name, channel, chat, turn, reason, comment, status,
             messages) in REPORTS:
            conn.execute(
                "INSERT INTO reports (id, created_at, actor_id, user_name, user_login, channel, "
                "chat_id, turn_id, reason, comment, snapshot, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, T0 + hours * H, actor, name, None, channel, chat, turn, reason, comment,
                 json.dumps({"source": "telemetry", "messages": messages}), status))


@pytest.fixture
def adb(_isolated_analytics):
    """Vaqtinchalik ombor, yuqoridagi ma'lumot bilan."""
    _seed(_isolated_analytics)
    return _isolated_analytics


def ids(items) -> list[str]:
    return [item["id"] for item in items]


# ================================================================ huquq


ENDPOINTS = [
    "/overview", "/turns", f"/turns/{A}", "/chats", "/reports", "/reports/rep-1", "/usage",
    "/system", "/search?q=ta", "/me",
]


# Har tekshiruv alohida test EMAS, bitta tsiklda: har test klient va ikki
# parol xeshini qaytadan yasaydi (~1 s), huquq esa baribir bir xil yo'l.


def test_oddiy_xodim_admin_bolimini_ocha_olmaydi(client, user_auth, adb):
    for path in ENDPOINTS:
        response = client.get(API + path, headers=user_auth)
        assert response.status_code == 403, path
        assert response.json()["message"] == "Bu bo'lim uchun ruxsat yo'q"


def test_tokensiz_401(client, adb):
    for path in ENDPOINTS:
        assert client.get(API + path).status_code == 401, path


def test_oddiy_xodim_xabarni_ozgartira_olmaydi(client, user_auth, adb):
    response = client.patch(f"{API}/reports/rep-1", json={"status": "resolved"},
                            headers=user_auth)
    assert response.status_code == 403
    # Hech narsa o'zgarmagan, audit ham yo'q.
    assert adb.scalar("SELECT status FROM reports WHERE id = 'rep-1'") == "new"
    assert adb.scalar("SELECT COUNT(*) FROM audit_log") == 0


def test_admin_hammasini_ochadi(client, auth, adb, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_diagnostics", lambda: {"status": "ok"})
    for path in ENDPOINTS:
        assert client.get(API + path, headers=auth).status_code == 200, path


def test_bosh_ombor_bilan_ham_ishlaydi(client, auth, _isolated_analytics, monkeypatch):
    """Yangi o'rnatilgan tizim: hali birorta savol yo'q - sahifalar yiqilmasin."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "_diagnostics", lambda: {"status": "ok"})
    overview = client.get(f"{API}/overview", headers=auth).json()
    assert overview["kpis"]["turns"]["value"] == 0
    assert overview["kpis"]["medianTtftMs"]["value"] is None
    assert overview["kpis"]["errorRate"]["value"] is None
    # Oxirgi 7 kun, kunlik: boshi va oxiri chala kun bo'lsa - 8 nuqta.
    assert overview["range"]["bucket"] == "day" and len(overview["activity"]) in (7, 8)
    assert len(overview["kpis"]["turns"]["spark"]) == 14
    assert client.get(f"{API}/turns", headers=auth).json() == {"items": [], "nextCursor": None}
    assert client.get(f"{API}/chats", headers=auth).json() == {"items": [], "nextCursor": None}
    usage = client.get(f"{API}/usage", headers=auth).json()
    assert [s["service"] for s in usage["services"]] == list(queries.KNOWN_SERVICES)
    assert all(s["requests"] == 0 and s["p95Ms"] is None for s in usage["services"])
    assert client.get(f"{API}/system", headers=auth).status_code == 200


# ================================================================ umumiy ko'rinish


def test_overview_shakli_va_raqamlari(client, auth, adb):
    body = client.get(f"{API}/overview", headers=auth,
                      params={"from": at(0), "to": at(48)}).json()
    assert set(body) == OVERVIEW
    assert set(body["range"]) == OVERVIEW_RANGE
    assert set(body["kpis"]) == KPIS
    assert all(set(kpi) == KPI for kpi in body["kpis"].values())
    assert body["range"] == {"from": at(0), "to": at(48), "prevFrom": at(-48),
                             "prevTo": at(0), "bucket": "hour"}

    kpis = body["kpis"]
    # A..G oraliqda, H (50-soat) - tashqarida.
    assert kpis["turns"]["value"] == 7 and kpis["turns"]["prev"] == 0
    assert kpis["activeUsers"]["value"] == 3
    # TTFT: 800, 1200, 1500, 2500, 3000 -> mediana 1500.
    assert kpis["medianTtftMs"]["value"] == 1500 and kpis["medianTtftMs"]["prev"] is None
    # Bitta xato (D) yettita tugagan savoldan.
    assert kpis["errorRate"]["value"] == round(1 / 7, 4)
    assert kpis["newReports"] == {"value": 3, "prev": 0, "spark": kpis["newReports"]["spark"]}
    assert sum(kpis["newReports"]["spark"]) == 3
    assert len(kpis["turns"]["spark"]) == 14 and sum(kpis["turns"]["spark"]) == 7

    # 48 soat - 48 ta soatlik nuqta, bo'shlari ham.
    assert len(body["activity"]) == 48
    assert set(body["activity"][0]) == {"t", "web", "miniapp", "bot", "desktop", "api"}
    assert body["activity"][1]["web"] == 1                      # A, 01:00
    assert sum(p[c] for p in body["activity"] for c in ("web", "miniapp", "bot", "api")) == 7
    assert body["latency"][1] == {"t": at(1), "p50": 1200, "p95": 1200}
    assert body["latency"][0]["p50"] is None

    assert body["channels"] == [
        {"channel": "web", "turns": 3, "users": 1, "errors": 0},
        {"channel": "bot", "turns": 2, "users": 1, "errors": 0},
        {"channel": "miniapp", "turns": 2, "users": 1, "errors": 1},
    ]
    assert body["routes"] == [
        {"route": "rules", "turns": 4, "errors": 0},
        {"route": "crm", "turns": 1, "errors": 1},
        {"route": "hrm", "turns": 1, "errors": 0},
        {"route": None, "turns": 1, "errors": 0},
    ]
    # Dvigatel bo'yicha (v1 va v2 ni solishtirish): NULL - "default" (E, F, G).
    # TTFT mediana: default (2500, 3000) -> 2750; v1 (800) - D da TTFT yo'q.
    assert body["engines"] == [
        {"engine": "default", "turns": 3, "errors": 0, "medianTtftMs": 2750},
        {"engine": "v1", "turns": 2, "errors": 1, "medianTtftMs": 800},
        {"engine": "v2", "turns": 2, "errors": 0, "medianTtftMs": 1350},
    ]
    assert all(set(e) == ENGINE_STAT for e in body["engines"])
    # Bitta javobdagi ikki parcha - bitta iqtibos.
    assert body["topDocs"] == [
        {"ref": "tatil-nizom", "title": "Mehnat ta'tillari nizomi", "citations": 2},
        {"ref": "ichki-tartib", "title": "Ichki mehnat tartibi qoidalari", "citations": 1},
        {"ref": "safar-yoriqnoma", "title": "Xizmat safarlari yo'riqnomasi", "citations": 1},
    ]
    assert body["tools"] == [
        {"ref": "crm_my_issues", "calls": 1, "errors": 1},
        {"ref": "hrm_today_late", "calls": 1, "errors": 0},
    ]
    assert ids(body["recentReports"]) == ["rep-3", "rep-2", "rep-1"]
    assert all(set(r) == REPORT_SUMMARY for r in body["recentReports"])
    assert ids(body["slowTurns"]) == [F, E, B, A, C]
    assert all(set(t) == TURN_SUMMARY for t in body["slowTurns"])


def test_overview_kunlik_guruh_va_kanal_filtri(client, auth, adb):
    body = client.get(f"{API}/overview", headers=auth,
                      params={"from": "2026-09-20", "to": "2026-09-22", "channel": "bot"}).json()
    # Faqat sana: `to` kuni ham kiradi - 3 kun, kunlik guruh.
    assert body["range"]["bucket"] == "day"
    assert body["range"]["to"] == at(72)
    assert [p["t"] for p in body["activity"]] == [at(0), at(24), at(48)]
    assert body["kpis"]["turns"]["value"] == 2
    assert body["activity"][0]["bot"] == 2 and body["activity"][0]["web"] == 0
    assert [c["channel"] for c in body["channels"]] == ["bot"]
    assert ids(body["recentReports"]) == ["rep-2"]


def test_overview_oldingi_davr_bilan_taqqoslaydi(client, auth, adb):
    # 24..48 soat: G; oldingi davr 0..24: A..F.
    body = client.get(f"{API}/overview", headers=auth,
                      params={"from": at(24), "to": at(48)}).json()
    assert body["kpis"]["turns"] == {**body["kpis"]["turns"], "value": 1, "prev": 6}
    assert body["kpis"]["activeUsers"]["prev"] == 3
    assert body["kpis"]["errorRate"]["prev"] == round(1 / 6, 4)
    assert body["kpis"]["medianTtftMs"]["value"] is None


def test_overview_notogri_parametr_422(client, auth, adb):
    for params, fragment in [
        ({"from": "kecha"}, "from"),
        ({"to": "2026-13-45"}, "to"),
        ({"from": at(10), "to": at(5)}, "from"),
        ({"channel": "faks"}, "channel"),
        ({"from": "2020-01-01", "to": "2026-01-01"}, "oraliq"),
    ]:
        response = client.get(f"{API}/overview", headers=auth, params=params)
        assert response.status_code == 422, params
        assert fragment in response.json()["message"], params


# ================================================================ savollar


def turns(client, auth, **params) -> list[str]:
    response = client.get(f"{API}/turns", headers=auth, params=params)
    assert response.status_code == 200, response.text
    return ids(response.json()["items"])


def test_savollar_royxati_shakli_va_tartibi(client, auth, adb):
    body = client.get(f"{API}/turns", headers=auth).json()
    assert set(body) == {"items", "nextCursor"}
    assert body["nextCursor"] is None
    assert ids(body["items"]) == [HH, G, F, E, D, C, B, A]
    assert all(set(t) == TURN_SUMMARY for t in body["items"])
    first = {t["id"]: t for t in body["items"]}
    assert first[F]["hasProposal"] is True and first[F]["proposalStatus"] == "executed"
    assert first[F]["hasArtifact"] is True
    assert first[E]["inputMode"] == "voice" and first[E]["kind"] == "bot"
    assert first[D]["errorCode"] == "auth_missing" and first[D]["toolCalls"] == 1
    assert first[A]["sourcesCount"] == 2 and first[A]["startedAt"] == at(1)
    assert first[A]["userLogin"] == "a.karimova"
    assert (first[A]["engine"], first[C]["engine"], first[E]["engine"]) == ("v2", "v1", None)


def test_savollar_filtrlari(client, auth, adb):
    assert turns(client, auth, channel="web") == [G, B, A]
    assert turns(client, auth, channel="telegram") == [F, E]          # taxallus -> bot
    assert turns(client, auth, status="error") == [D]
    assert turns(client, auth, route="rules") == [F, E, B, A]
    assert turns(client, auth, route="none") == [G]
    assert turns(client, auth, actorId=12) == [D, C]
    assert turns(client, auth, minMs=6000) == [F, E, B]
    assert turns(client, auth, chatId="c2") == [D, C]
    # `to` o'zi kirmaydi: E aynan 5-soatda.
    assert turns(client, auth, **{"from": at(2), "to": at(5)}) == [D, C, B]
    assert turns(client, auth, **{"from": "2026-09-21"}) == [HH, G]
    assert turns(client, auth, **{"to": "2026-09-20"}) == [F, E, D, C, B, A]
    # Dvigatel: v1 / v2, `default` - yozilmagan (versiyasiz yo'l, eski qator).
    assert turns(client, auth, engine="v2") == [B, A]
    assert turns(client, auth, engine="v1") == [D, C]
    assert turns(client, auth, engine="default") == [HH, G, F, E]
    assert turns(client, auth, engine="v1", status="error") == [D]


def test_xabar_berilganlar_filtri(client, auth, adb):
    """B - xabar aynan unga; E, F - butun suhbatga (turnId siz); D - aynan.
    A - o'sha suhbatda, lekin xabar B ga yozilgan."""
    assert turns(client, auth, reported="true") == [F, E, D, B]
    assert turns(client, auth, reported="false") == [HH, G, C, A]
    items = client.get(f"{API}/turns", headers=auth).json()["items"]
    assert {t["id"] for t in items if t["reported"]} == {F, E, D, B}


def test_savollar_qidiruvi(client, auth, adb):
    # Savol va javob matni.
    assert turns(client, auth, q="ta'til") == [F, B, A]
    # Tutuq belgisining boshqa yozilishi ham topadi.
    assert turns(client, auth, q="taʼtil") == [F, B, A]
    assert turns(client, auth, q="ta‘til") == [F, B, A]
    # Kirill: SQLite LIKE registrga faqat lotinda qaramaydi.
    assert turns(client, auth, q="отпуск") == [G]
    # Ism, login, kalitlar (aynan).
    assert turns(client, auth, q="karimova") == [G, B, A]
    assert turns(client, auth, q="req-c") == [C]
    assert turns(client, auth, q=A) == [A]
    # `%` va `_` - oddiy belgi, shablon emas.
    assert turns(client, auth, q="10%") == [E]
    assert turns(client, auth, q="_") == []


def test_savollar_sahifalash(client, auth, adb):
    seen: list[str] = []
    pages = 0
    cursor = None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = client.get(f"{API}/turns", headers=auth, params=params).json()
        seen += ids(body["items"])
        pages += 1
        cursor = body["nextCursor"]
        if not cursor:
            break
    assert pages == 3
    assert seen == [HH, G, F, E, D, C, B, A]


def test_bir_xil_vaqtdagi_savollar_chegarada_yoqolmaydi(client, auth, _isolated_analytics):
    with _isolated_analytics.transaction() as conn:
        for index in range(7):
            conn.execute("INSERT INTO turns (id, started_at, channel, question, status) "
                         "VALUES (?,?,?,?,?)", (f"{index:032x}", T0, "web", "bir xil", "ok"))
    seen: list[str] = []
    cursor = None
    while True:
        body = client.get(f"{API}/turns", headers=auth,
                          params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += ids(body["items"])
        cursor = body["nextCursor"]
        if not cursor:
            break
    assert seen == [f"{index:032x}" for index in reversed(range(7))]


def test_savollar_notogri_parametr_422(client, auth, adb):
    for params in [
        {"cursor": "buzuq!"}, {"cursor": "WzEsMl0"}, {"status": "yaxshi"}, {"limit": 101},
        {"limit": 0}, {"minMs": -1}, {"channel": "pochta"}, {"from": "ertaga"},
        {"engine": "v9"}, {"engine": "V2;--"},
    ]:
        assert client.get(f"{API}/turns", headers=auth, params=params).status_code == 422, params
        assert client.get(f"{API}/chats", headers=auth, params=params).status_code == 422, params


def test_savol_izi(client, auth, adb):
    body = client.get(f"{API}/turns/{A}", headers=auth).json()
    assert set(body) == TURN_DETAIL
    assert body["question"] == "Mehnat ta'tili necha kun?"
    assert body["answer"].startswith("Yillik asosiy ta'til")
    assert body["requestId"] == "req-a" and body["locale"] == "uz"
    assert body["endedAt"] == queries.iso(T0 + H + 5.2)
    assert body["reported"] is False
    assert [e["name"] for e in body["events"]] == [
        "assistant.open", "first_frame", "stage", "sources", "first_token", "done"]
    assert all(set(e) == TURN_EVENT for e in body["events"])
    assert body["events"][0] == {"seq": 0, "tMs": 3, "durMs": 210, "type": "span",
                                 "name": "assistant.open", "payload": {"requestId": "req-a"}}
    assert body["events"][4]["payload"] is None
    assert [s["idx"] for s in body["sources"]] == [0, 1]
    assert all(set(s) == TURN_SOURCE for s in body["sources"])
    assert body["sources"][0]["score"] == 0.91 and body["sources"][0]["page"] == 3
    assert len(body["apiCalls"]) == 1 and set(body["apiCalls"][0]) == API_CALL
    assert body["apiCalls"][0]["units"] == {"frames": 40}
    assert ids(body["chatTurns"]) == [A, B]
    assert all(set(c) == CHAT_TURN for c in body["chatTurns"])
    # Suhbatga berilgan xabar ham ko'rinadi (B ga yozilgan bo'lsa ham).
    assert ids(body["reports"]) == ["rep-1"]


def test_savol_izi_xabar_va_suhbatsiz(client, auth, adb):
    body = client.get(f"{API}/turns/{B}", headers=auth).json()
    assert body["reported"] is True
    lone = client.get(f"{API}/turns/{HH}", headers=auth).json()
    assert ids(lone["chatTurns"]) == [HH] and lone["reports"] == []
    assert lone["events"] == [] and lone["sources"] == [] and lone["apiCalls"] == []
    assert client.get(f"{API}/turns/{'0' * 32}", headers=auth).status_code == 404


# ================================================================ suhbatlar


def test_suhbatlar(client, auth, adb):
    body = client.get(f"{API}/chats", headers=auth).json()
    assert set(body) == {"items", "nextCursor"}
    items = body["items"]
    # H ning suhbati yo'q - bu ro'yxatda emas.
    assert [c["chatId"] for c in items] == ["c4", "c3", "c2", "c1"]
    assert all(set(c) == ADMIN_CHAT for c in items)
    c1 = items[3]
    assert c1 == {"chatId": "c1", "actorId": 11, "userName": "Aziza Karimova", "channel": "web",
                  "firstAt": at(1), "lastAt": at(2), "turns": 2, "errors": 0, "reported": True,
                  "title": "Mehnat ta'tili necha kun?"}
    assert items[2]["errors"] == 1 and items[2]["reported"] is True
    assert items[0]["reported"] is False


def test_suhbatlar_filtr_va_sahifalash(client, auth, adb):
    def chats(**params):
        return [c["chatId"] for c in client.get(f"{API}/chats", headers=auth,
                                                  params=params).json()["items"]]

    assert chats(reported="false") == ["c4"]
    assert chats(reported="true") == ["c3", "c2", "c1"]
    assert chats(channel="bot") == ["c3"]
    assert chats(q="kechikdim") == ["c2"]
    # Dvigatel filtri savollarga: c2 - mini app (v1), c1 - web (v2).
    assert chats(engine="v1") == ["c2"]
    assert chats(engine="v2") == ["c1"]
    assert chats(engine="default") == ["c4", "c3"]
    first = client.get(f"{API}/chats", headers=auth, params={"limit": 2}).json()
    assert [c["chatId"] for c in first["items"]] == ["c4", "c3"]
    second = client.get(f"{API}/chats", headers=auth,
                        params={"limit": 2, "cursor": first["nextCursor"]}).json()
    assert [c["chatId"] for c in second["items"]] == ["c2", "c1"]
    assert second["nextCursor"] is None


# ================================================================ xabarlar


def test_xabarlar_qutisi(client, auth, adb):
    body = client.get(f"{API}/reports", headers=auth).json()
    assert set(body) == {"items", "counts", "nextCursor"}
    assert ids(body["items"]) == ["rep-4", "rep-3", "rep-2", "rep-1"]
    assert all(set(r) == REPORT_SUMMARY for r in body["items"])
    assert body["counts"] == {"new": 1, "reviewing": 1, "resolved": 1, "dismissed": 1}
    by_id = {r["id"]: r for r in body["items"]}
    # Izohning birinchi qatori.
    assert by_id["rep-1"]["commentPreview"] == "Javob eskirgan nizomga tayangan"
    assert by_id["rep-1"]["messages"] == 4 and by_id["rep-1"]["turnId"] == B
    # Izoh yo'q, suhbatga yozilgan - nusxadagi savol.
    assert by_id["rep-2"]["commentPreview"] == "Xizmat safari kunlik puli qancha?"
    # Izoh bo'sh - bog'langan savol.
    assert by_id["rep-3"]["commentPreview"] == "CRM dagi vazifalarim"
    assert by_id["rep-3"]["messages"] == 0


def test_xabarlar_filtrlari_va_sahifalash(client, auth, adb):
    def reports(**params):
        return client.get(f"{API}/reports", headers=auth, params=params).json()

    only_new = reports(status="new")
    assert ids(only_new["items"]) == ["rep-1"]
    # Yorliqlar soni holat filtriga qaramaydi.
    assert only_new["counts"] == {"new": 1, "reviewing": 1, "resolved": 1, "dismissed": 1}
    day = reports(**{"from": "2026-09-20", "to": "2026-09-20"})
    assert ids(day["items"]) == ["rep-2", "rep-1"]
    assert day["counts"] == {"new": 1, "reviewing": 1, "resolved": 0, "dismissed": 0}
    assert ids(reports(channel="miniapp")["items"]) == ["rep-4", "rep-3"]
    assert ids(reports(q="eskirgan")["items"]) == ["rep-1"]
    assert ids(reports(q="rep-3")["items"]) == ["rep-3"]
    assert ids(reports(actorId=13)["items"]) == ["rep-2"]
    first = reports(limit=3)
    assert ids(first["items"]) == ["rep-4", "rep-3", "rep-2"]
    rest = reports(limit=3, cursor=first["nextCursor"])
    assert ids(rest["items"]) == ["rep-1"] and rest["nextCursor"] is None
    assert client.get(f"{API}/reports", headers=auth,
                      params={"status": "ochiq"}).status_code == 422


def test_xabar_tafsiloti(client, auth, adb):
    body = client.get(f"{API}/reports/rep-1", headers=auth).json()
    assert set(body) == REPORT_DETAIL
    assert body["comment"] == "Javob eskirgan nizomga tayangan\nikkinchi qator"
    assert body["snapshot"]["source"] == "telemetry"
    assert [m["turnId"] for m in body["snapshot"]["messages"]] == [A, A, B, B]
    assert body["adminNote"] is None and body["updatedAt"] is None
    assert client.get(f"{API}/reports/yoq", headers=auth).status_code == 404


def test_buzuq_nusxa_sahifani_yiqitmaydi(client, auth, _isolated_analytics):
    with _isolated_analytics.transaction() as conn:
        conn.execute("INSERT INTO reports (id, created_at, snapshot, status, comment) "
                     "VALUES ('bad', ?, '{buzuq', 'new', NULL)", (T0,))
    listed = client.get(f"{API}/reports", headers=auth).json()["items"]
    assert listed[0]["messages"] == 0 and listed[0]["commentPreview"] is None
    body = client.get(f"{API}/reports/bad", headers=auth).json()
    assert body["snapshot"] == {"source": "unknown", "messages": []}


def audit(adb) -> list[dict]:
    return adb.rows("SELECT * FROM audit_log ORDER BY id")


def test_xabar_holati_ozgaradi_va_auditga_yoziladi(client, auth, adb):
    assert client.get(f"{API}/me", headers=auth).json()["newReports"] == 1
    response = client.patch(f"{API}/reports/rep-1", json={"status": "reviewing"}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == REPORT_DETAIL
    assert body["status"] == "reviewing"
    assert body["updatedBy"] == "admin@venera.uz" and body["updatedAt"]
    entries = audit(adb)
    assert len(entries) == 1
    assert entries[0]["action"] == "report.status" and entries[0]["target_type"] == "report"
    assert entries[0]["target_id"] == "rep-1" and entries[0]["admin_actor_id"] == 1
    assert json.loads(entries[0]["detail"]) == {"from": "new", "to": "reviewing"}
    assert client.get(f"{API}/me", headers=auth).json()["newReports"] == 0

    # Xuddi shu holat - o'zgarish yo'q, audit ham yo'q.
    client.patch(f"{API}/reports/rep-1", json={"status": "reviewing"}, headers=auth)
    assert len(audit(adb)) == 1

    # Izoh: qo'yish va o'chirish - ikkalasi ham auditda.
    noted = client.patch(f"{API}/reports/rep-1", json={"adminNote": "  2025 nizomi bilan  "},
                         headers=auth).json()
    assert noted["adminNote"] == "2025 nizomi bilan" and noted["status"] == "reviewing"
    cleared = client.patch(f"{API}/reports/rep-1", json={"adminNote": None}, headers=auth).json()
    assert cleared["adminNote"] is None
    assert [e["action"] for e in audit(adb)] == ["report.status", "report.note", "report.note"]
    assert json.loads(audit(adb)[1]["detail"])["chars"] == len("2025 nizomi bilan")

    # Tizim sahifasidagi jurnal shu yozuvlarni ko'rsatadi.
    import app.main as main_module

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main_module, "_diagnostics", lambda: {"status": "ok"})
        system = client.get(f"{API}/system", headers=auth).json()
    assert [e["action"] for e in system["audit"]] == ["report.note", "report.note",
                                                     "report.status"]
    assert all(set(e) == AUDIT_ENTRY for e in system["audit"])
    assert system["audit"][-1]["adminName"] == "Administrator"


def test_xabar_ozgartirish_tekshiruvi(client, auth, adb):
    for payload in ({"status": "yopildi"}, {"statuss": "resolved"}, {"adminNote": "x" * 2001}):
        response = client.patch(f"{API}/reports/rep-1", json=payload, headers=auth)
        assert response.status_code == 422, payload
    response = client.patch(f"{API}/reports/yoq", json={"status": "resolved"}, headers=auth)
    assert response.status_code == 404
    assert audit(adb) == []
    assert adb.scalar("SELECT status FROM reports WHERE id = 'rep-1'") == "new"


# ================================================================ foydalanish


def test_foydalanish(client, auth, adb):
    body = client.get(f"{API}/usage", headers=auth,
                      params={"from": at(0), "to": at(48)}).json()
    assert set(body) == USAGE
    names = [s["service"] for s in body["services"]]
    assert names == list(queries.KNOWN_SERVICES)
    assert all(set(s) == USAGE_SERVICE for s in body["services"])
    services = {s["service"]: s for s in body["services"]}
    assistant = services["assistant"]
    assert assistant["requests"] == 6 and assistant["errors"] == 1
    assert assistant["errorRate"] == round(1 / 6, 4)
    # 900, 2100, 5200, 6100, 9800, 15000 -> p50 5650, p95 13700 (chiziqli).
    assert assistant["p50Ms"] == 5650 and assistant["p95Ms"] == 13700
    assert assistant["units"] == {"frames": 289}
    assert len(assistant["spark"]) == 14 and sum(assistant["spark"]) == 6
    assert services["tts"]["units"] == {"chars": 350} and services["tts"]["errors"] == 1
    assert services["stt_router"]["units"] == {"audioSec": 4.5}
    assert services["hrm"] == {**services["hrm"], "requests": 0, "p50Ms": None, "units": {}}

    assert body["series"]["bucket"] == "hour" and len(body["series"]["points"]) == 48
    assert set(body["series"]["points"][0]) == {"t", *names}
    assert sum(p["assistant"] for p in body["series"]["points"]) == 6
    lanes = {row["channel"]: row for row in body["byChannel"]}
    assert [row["channel"] for row in body["byChannel"]] == ["web", "miniapp", "bot", "system"]
    assert lanes["system"]["keycloak"] == 1 and lanes["bot"]["assistant"] == 2
    assert all(set(o) == USAGE_OP for o in body["ops"])
    assert (body["ops"][0]["service"], body["ops"][0]["op"]) == ("assistant", "stream")


def test_foydalanish_kanal_filtri(client, auth, adb):
    body = client.get(f"{API}/usage", headers=auth,
                      params={"from": at(0), "to": at(48), "channel": "web"}).json()
    services = {s["service"]: s for s in body["services"]}
    assert services["assistant"]["requests"] == 2 and services["tts"]["requests"] == 1
    assert services["keycloak"]["requests"] == 0
    assert [row["channel"] for row in body["byChannel"]] == ["web"]


# ================================================================ tizim, qidiruv, nishon


def test_tizim(client, auth, adb, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_diagnostics", lambda: {
        "status": "degraded", "warnings": ["TTS navbati to'la"],
        "login": {"sso": True, "local": True, "identities": 3},
        "telegram": {"configured": True, "enabled": False, "running": False},
    })
    monkeypatch.setattr(settings, "analytics_retention_days", 90)
    monkeypatch.setattr(settings, "local_login_enabled", False)
    body = client.get(f"{API}/system", headers=auth).json()
    assert set(body) == SYSTEM
    assert body["health"]["status"] == "degraded"
    assert set(body["config"]) == SYSTEM_CONFIG
    assert body["config"] == {"ssoEnabled": True, "localLoginEnabled": False,
                              "telegramMode": "off", "telegramBotEnabled": False,
                              "retentionDays": 90, "analyticsEnabled": True}
    assert set(body["storage"]) == STORAGE
    storage = body["storage"]
    assert (storage["turns"], storage["events"], storage["apiCalls"], storage["reports"]) == \
        (8, 6, 11, 4)
    assert storage["dbBytes"] > 0 and storage["dropped"] == 0

    monkeypatch.setattr(settings, "telegram_bot_enabled", True)
    assert client.get(f"{API}/system", headers=auth).json()["config"]["telegramMode"] == "polling"


def test_tizim_tashxis_yiqilsa_ham_ochiladi(client, auth, adb, monkeypatch):
    import app.main as main_module

    def broken():
        raise RuntimeError("upstream yo'q")

    monkeypatch.setattr(main_module, "_diagnostics", broken)
    body = client.get(f"{API}/system", headers=auth).json()
    assert body["health"]["status"] == "unknown"
    assert body["storage"]["turns"] == 8


def test_qidiruv(client, auth, adb):
    body = client.get(f"{API}/search", headers=auth, params={"q": "Karimova"}).json()
    assert set(body) == {"users", "turns", "reports"}
    assert ids(body["turns"]) == [G, B, A]
    assert ids(body["reports"]) == ["rep-1"]
    assert [u["actorId"] for u in body["users"]] == [11]
    assert body["users"][0]["name"] == "Aziza Karimova"
    # Har turdan ko'pi bilan 5 ta.
    many = client.get(f"{API}/search", headers=auth, params={"q": "a"}).json()
    assert len(many["turns"]) == 5 and len(many["reports"]) <= 5 and len(many["users"]) <= 5
    assert client.get(f"{API}/search", headers=auth).status_code == 422
    blank = client.get(f"{API}/search", headers=auth, params={"q": "   "}).json()
    assert blank == {"users": [], "turns": [], "reports": []}


def test_me(client, auth, adb):
    body = client.get(f"{API}/me", headers=auth).json()
    assert set(body) == {"user", "newReports"}
    assert body["user"]["email"] == "admin@venera.uz" and "ADMIN" in body["user"]["roles"]
    assert body["newReports"] == 1


# ================================================================ haqiqiy yozuv yo'li


def _line(frame: dict) -> bytes:
    return json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n"


def test_yozib_olingan_savol_panelda_korinadi(client, auth, _isolated_analytics):
    """`TurnRecorder` -> yozuvchi ip -> ombor -> admin API: butun yo'l."""
    recorder = TurnRecorder({"actorId": 2, "fullName": "Demo Foydalanuvchi",
                             "email": "Demo@Venera.uz"}, "miniapp", "chat",
                            "Kasallik varaqasi qanday to'lanadi?", chat_id="chat-rec",
                            locale="uz")
    frames = [
        {"type": "stage", "text": "Hujjatlar qidirilmoqda"},
        {"type": "sources", "items": [
            {"kind": "doc", "doc_id": "kasallik-tartib", "title": "Kasallik varaqasi tartibi",
             "page": 2, "score": 0.87, "snippet": "Nafaqa o'rtacha ish haqidan ...",
             "citation_index": 1},
            {"tool": "hrm_sick_leave", "status": "200", "digest": "ochiq varaqa yo'q",
             "marker": "[T1]"},
        ]},
        {"type": "token", "text": "Nafaqa "},
        {"type": "token", "text": "8 yillik stajda 80% [1]."},
        {"type": "done", "route": "rules", "request_id": "req-rec"},
    ]
    assert list(recorder.wrap(iter([_line(f) for f in frames])))
    assert analytics.flush()

    items = client.get(f"{API}/turns", headers=auth, params={"channel": "miniapp"}).json()["items"]
    assert ids(items) == [recorder.turn_id]
    summary = items[0]
    assert summary["userLogin"] == "demo@venera.uz" and summary["route"] == "rules"
    assert summary["sourcesCount"] == 1 and summary["toolCalls"] == 1
    assert summary["status"] == "ok" and summary["ttftMs"] is not None

    detail = client.get(f"{API}/turns/{recorder.turn_id}", headers=auth).json()
    assert detail["answer"] == "Nafaqa 8 yillik stajda 80% [1]."
    assert detail["requestId"] == "req-rec"
    assert [s["ref"] for s in detail["sources"]] == ["kasallik-tartib", "hrm_sick_leave"]
    assert detail["sources"][1]["kind"] == "hrm" and detail["sources"][1]["citation"] == 1
    assert "first_token" in [e["name"] for e in detail["events"]]

    overview = client.get(f"{API}/overview", headers=auth).json()
    assert overview["kpis"]["turns"]["value"] == 1
    assert overview["topDocs"][0]["ref"] == "kasallik-tartib"
    assert overview["tools"] == [{"ref": "hrm_sick_leave", "calls": 1, "errors": 0}]


# ================================================================ yordamchilar


@pytest.mark.parametrize("value,end,expected", [
    ("2026-09-20T00:00:00Z", False, T0),
    ("2026-09-20T00:00:00.000Z", False, T0),
    ("2026-09-20T05:00:00+05:00", False, T0),
    # URL'da kodlanmagan `+` bo'shliqqa aylanadi.
    ("2026-09-20T05:00:00 05:00", False, T0),
    ("2026-09-20T00:00:00", False, T0),
    ("2026-09-20", False, T0),
    ("2026-09-20", True, T0 + 86400),
    (str(int(T0)), False, T0),
    (str(int(T0 * 1000)), False, T0),
    ("", False, None),
    (None, False, None),
])
def test_vaqt_oqiladi(value, end, expected):
    assert queries.parse_time(value, end=end) == expected


def test_foiz_chiziqli():
    assert queries.percentile([], 0.5) is None
    assert queries.percentile([7], 0.95) == 7
    assert queries.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert queries.percentile(list(range(101)), 0.95) == 95


def test_kursor_qaytadi():
    cursor = queries.encode_cursor(T0 + 0.123456789, "abc")
    assert queries.decode_cursor(cursor) == (T0 + 0.123456789, "abc")
    with pytest.raises(queries.QueryError):
        queries.decode_cursor("WyJ4IiwxXQ")          # ["x", 1]


# ================================================================ sinov ma'lumoti vositasi


def _seed_tool():
    import importlib.util

    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "tools" / "seed_analytics.py"
    spec = importlib.util.spec_from_file_location("seed_analytics", path)
    module = importlib.util.module_from_spec(spec)
    # `dataclass` sinf modulini `sys.modules` dan qidiradi.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_seed_vositasi_toldiradi_va_takrorlanadi(tmp_path, capsys):
    from app.services.analytics.db import Database

    seed = _seed_tool()
    path = tmp_path / "dev" / "venera.db"
    args = ["--db", str(path), "--days", "3", "--users", "8", "--scale", "0.4",
            "--end", "2026-09-20T00:00:00Z"]
    assert seed.main(args) == 0
    db = Database(path)
    try:
        def snapshot():
            return {table: db.scalar(f"SELECT COUNT(*) FROM {table}")
                    for table in seed.TABLES}

        first = snapshot()
        assert first["turns"] > 50 and first["reports"] == 25
        assert all(first[t] > 0 for t in seed.TABLES)
        channels = {r["channel"] for r in db.rows("SELECT DISTINCT channel FROM turns")}
        assert channels <= {"web", "miniapp", "bot"} and "web" in channels
        statuses = {r["status"] for r in db.rows("SELECT DISTINCT status FROM reports")}
        assert statuses == set(queries.REPORT_STATUSES)
        assert db.scalar("SELECT MAX(started_at) FROM turns") < T0
        # Admin sahifalari shu ma'lumotni o'qiy oladi.
        overview = queries.overview(db, start=T0 - 3 * 86400, end=T0)
        assert overview["kpis"]["turns"]["value"] == first["turns"]
        assert overview["topDocs"] and overview["tools"]
        # Dvigatel ustuni ham to'ladi (sxema v2) - "Dvigatellar" kartochkasi bo'sh qolmasin.
        engines_seen = {e["engine"] for e in overview["engines"]}
        assert "v2" in engines_seen and engines_seen <= {"v1", "v2"}

        # Ikkinchi marta - rad etadi (ma'lumot bor); `--reset` - xuddi shunday qaytadan.
        assert seed.main(args) == 1
        assert seed.main([*args, "--reset"]) == 0
        assert snapshot() == first
    finally:
        db.close_all()
    assert (path.stat().st_mode & 0o777) == 0o600


def test_seed_vositasi_prod_omborga_yozmaydi(tmp_path):
    seed = _seed_tool()
    with pytest.raises(SystemExit) as refused:
        seed.main(["--db", "/home/ymamajonov/Venera/apps/api/data/analytics/venera.db"])
    assert "RAD ETILDI" in str(refused.value)
    # Symlink orqali aylanib o'tish ham ishlamaydi.
    link = tmp_path / "yorliq"
    link.symlink_to(seed.PROD_ROOT)
    with pytest.raises(SystemExit):
        seed.main(["--db", str(link / "venera.db")])

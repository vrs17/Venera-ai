"""Chat dvigateli v5 - agentning yangi dvigateli (`/api/v5/chat/stream`, 2026-11-25).

Agent jamoasi aytgani: v5 shartnoma 4.0 ni AYNAN v4 dagi kabi gapiradi - so'rov tanasi
(`purpose` majburiy, `X-Barno-Contract: 4.0`), kadrlar, tasdiq va bekor qilish yo'llari,
suhbatlar ro'yxati, xotira va tarix bir xil; `done` da `engine: "v5"`. Farqlari:
"Pro" qabul qilinadi va E'TIBORSIZ qoldiriladi (bizda `pro: False`), ariza fayli hali
yo'q (`artifact` kadri kelmaydi), ovozda gap javob to'liq tayyor bo'lganda keladi.

Bizda v5 - katalogdagi yangi qator va `CONTRACT_ENGINES` dagi ikkinchi nom; admin uni
avval bitta odamga (`engine_access`) beradi. Tekshiriladi:

  * KATALOG: v5 bor, "Pro" yo'q, qonun manbasi bor; kod default'i o'zgarmagan;
  * SO'ROV: v5 tanasi va sarlavhasi v4 niki bilan BIR XIL (faqat yo'l boshqa);
    "Pro" v5 ga yuborilmaydi;
  * KADRLAR: v4 dagi kabi tozalanadi (`ping`, `result`, `meta`, `cited_ids`);
  * ADMIN: faqat v5 berilgan odamning savoli v5 ga; boshqasi so'rasa ham - yo'q;
    "Pro" byudjeti v5 da `available: false`; ovozli uslub; iz filtri `engine=v5`.

Tarmoqqa chiqilmaydi: agent soxta (`test_assistant_v4` dagi), ombor vaqtinchalik.
"""

from __future__ import annotations

import pytest

from app.core import engines
from app.services.integrations.assistant import CONTRACT_ENGINES, stream_path
from tests.test_assistant_v4 import (  # noqa: F401 - fiksturalar
    DEMO_ID,
    V4_DONE,
    _fresh_cache,
    agent,
    db,
    frame,
    frames_of,
    grant,
    lines,
    make_client,
    rows,
    wired,
)


@pytest.fixture
def v5_agent(agent, monkeypatch):
    """Soxta agent `/api/v5/chat/stream` da ham v4 kadrlarini beradi, `done` - `engine: v5`."""
    original = agent.open

    def open_(request, timeout=None):
        response = original(request, timeout)
        if "/api/v5/chat/stream" in request.full_url:
            done = {**V4_DONE, "engine": "v5", "request_id": "r-5",
                    "meta": {**V4_DONE["meta"], "engine": "v5"}}
            response._lines = [*agent.lines[:-1], frame(**done)]
        return response

    monkeypatch.setattr(agent, "open", open_)
    return agent


# ================================================================ katalog va yo'l


def test_v5_katalogda_prosiz_qonun_bilan():
    assert {"id": "v5", "pro": False, "law": True} in engines.catalog()
    assert engines.catalog_id(" V5 ") == "v5" and engines.normalize("v5") == "v5"
    assert not engines.pro_available("v5")
    assert stream_path("v5") == "/api/v5/chat/stream"
    assert "v5" in CONTRACT_ENGINES
    # Kod default'i O'ZGARMAYDI: v5 ni faqat admin beradi.
    assert engines.DEFAULT_ENGINE == "v2"


# ================================================================ so'rov


def test_v5_sorovi_v4_niki_bilan_bir_xil(agent):
    client = make_client()
    for engine in ("v4", "v5"):
        frames_of(client.stream("Vazifalarim qanday?", user_id="venera:7", chat_id="c-1",
                                tokens={"crm": "crm-jwt"}, engine=engine, style="voice"))
    v4, v5 = agent.calls
    assert v5["path"] == "/api/v5/chat/stream"
    assert v5["body"] == v4["body"] == {
        "question": "Vazifalarim qanday?", "user_id": "venera:7", "chat_id": "c-1",
        "tokens": {"crm": "crm-jwt"},
        "purpose": "chat", "store": True, "chat_visibility": "personal", "style": "voice",
    }
    assert v5["headers"]["x-barno-contract"] == "4.0"
    assert v5["headers"]["x-client-id"] == "venera"


def test_v5_ga_pro_yuborilmaydi(agent):
    """Agent v5 da "Pro" ni e'tiborsiz qoldiradi - yuborsak, izda "Pro ishlatildi" degan
    yolg'on belgi va byudjet hisobi chalkashardi. v4 da avvalgidek ketadi."""
    client = make_client()
    frames_of(client.stream("savol", user_id="venera:7", engine="v5", mode="pro"))
    frames_of(client.stream("savol", user_id="venera:7", engine="v4", mode="pro"))
    v5, v4 = agent.calls
    assert "mode" not in v5["body"]
    assert v4["body"]["mode"] == "pro"


def test_v5_guruh_sorovi_v4_dagi_cheklov_bilan(agent):
    frames_of(make_client().stream("vazifa och", user_id="venera:7", chat_id="tgcrm-1",
                                   tokens={"crm": "own-crm"}, engine="v5", audience="group",
                                   style="voice"))
    [call] = agent.calls
    assert call["body"]["purpose"] == "group_crm" and call["body"]["audience"] == "group"
    assert call["body"]["tools"] == ["crm.read", "crm.propose"]
    assert call["body"]["memory_scopes"] == [] and "style" not in call["body"]


# ================================================================ kadrlar


def test_v5_kadrlari_v4_dagi_kabi_tozalanadi(v5_agent):
    stream = make_client().stream("savol", user_id="venera:7", engine="v5")
    got = frames_of(stream)
    assert [f["type"] for f in got] == ["stage", "sources", "token", "done"]
    done = got[-1]
    assert "meta" not in done and "cited_ids" not in done
    assert done["engine"] == "v5"
    assert stream.outcome == {"route": "crm", "engine": "v5", "frames": 4}


# ================================================================ admin: bitta odamga


def test_v5_bitta_odamga_berilsa_faqat_uning_savoli_v5_ga(wired, client, auth, user_auth,
                                                          v5_agent, db):
    grant(db, DEMO_ID, ["v4", "v5"], "v5")
    mine = client.post("/api/v1/chat/stream", headers={**user_auth, "X-Venera-Client": "web"},
                       json={"question": "Vazifalarim qanday?", "chatId": "c-9"})
    # Admin v5 ni SO'RAYDI, lekin unga berilmagan - jimgina umumiy versiya.
    other = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                        json={"question": "savol", "engine": "v5"})
    assert mine.status_code == other.status_code == 200
    assert [c["path"] for c in v5_agent.streams()] == ["/api/v5/chat/stream",
                                                       "/api/v2/chat/stream"]
    sent = v5_agent.streams()[0]
    assert sent["headers"]["x-barno-contract"] == "4.0"
    assert sent["body"]["purpose"] == "chat" and sent["body"]["chat_id"] == "c-9"
    assert sent["body"]["user_id"] == f"venera:{DEMO_ID}"
    assert lines(mine)[-1]["engine"] == "v5"
    recorded = rows(db, "SELECT engine FROM turns ORDER BY started_at")
    assert [r["engine"] for r in recorded] == ["v5", "v2"]


def test_v5_odam_v4_ni_tanlay_oladi(wired, client, user_auth, agent, db):
    """Ikkala versiya berilgan odam chatda o'zi tanlaydi: suhbat v5 da boshlanib v4 da
    davom etadi (agentda tarix dvigatelsiz)."""
    grant(db, DEMO_ID, ["v4", "v5"], "v5")
    for engine in ("v5", "v4"):
        response = client.post("/api/v1/chat/stream",
                               headers={**user_auth, "X-Venera-Client": "web"},
                               json={"question": "savol", "chatId": "c-5", "engine": engine})
        assert response.status_code == 200
    assert [c["path"] for c in agent.streams()] == ["/api/v5/chat/stream", "/api/v4/chat/stream"]
    assert {c["body"]["chat_id"] for c in agent.streams()} == {"c-5"}


def test_v5_da_pro_soralsa_standart_rejim(wired, client, user_auth, agent, db):
    grant(db, DEMO_ID, ["v5"], "v5")
    quota = client.get("/api/v1/pro/quota", headers={**user_auth, "X-Venera-Client": "web"})
    assert quota.json()["engine"] == "v5" and quota.json()["available"] is False
    response = client.post("/api/v1/chat/stream", headers={**user_auth, "X-Venera-Client": "web"},
                           json={"question": "savol", "mode": "pro"})
    assert response.status_code == 200
    [sent] = agent.streams()
    assert sent["path"] == "/api/v5/chat/stream" and "mode" not in sent["body"]


def test_v5_da_gapirilgan_savol_ovozli_uslubda(wired, client, auth, agent, db):
    grant(db, 1, ["v5"], "v5")                              # conftest: admin@venera.uz
    response = client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                           json={"question": "Vazifalarim?", "voice": True, "locale": "ru"})
    assert response.status_code == 200
    [sent] = agent.streams()
    assert sent["path"] == "/api/v5/chat/stream" and sent["body"]["style"] == "voice"


def test_admin_izida_v5_filtri(wired, client, auth, agent, db):
    grant(db, 1, ["v5"], "v5")
    assert client.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "web"},
                       json={"question": "savol"}).status_code == 200
    assert rows(db, "SELECT engine FROM turns") == [{"engine": "v5"}]
    response = client.get("/api/v1/admin/turns", params={"engine": "v5"}, headers=auth)
    assert response.status_code == 200
    assert [t["engine"] for t in response.json()["items"]] == ["v5"]

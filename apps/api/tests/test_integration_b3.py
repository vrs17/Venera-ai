"""Birlashtirish (B3, end-to-end tekshiruv): jonli stekda topilgan uchrashuv joylari.

`test_integration_merge_b.py` dan keyin, dev stek (API + soxta yuqori xizmat +
brauzer) ustida ko'rilgan narsalar:

  * savol QANDAY kiritilgani (`input`): Mini App'da javobni o'qish default
    yoqiq, ya'ni `voice: true` yozilgan savol bilan ham keladi - izda hamma
    Mini App savoli "ovozli" edi. Endi `input` ustun, eski build uchun
    (maydonsiz) avvalgi xulq;
  * Mini App uchala savol yo'lida `input` ni aniq aytadi (mikrofon, past
    ishonchli transkriptni tasdiqlash, yozib yuborish);
  * `contacts` oralig'i izda `answered` bilan - admin panel uni "ma'lumotnomadan
    javob berildi / ma'lumotnoma savoli emas" deb ko'rsatadi;
  * soxta yuqori xizmat (`tools/dev_mock_upstream.py`) "Pro" ni jonli xizmat
    shaklida beradi: `GET /api/pro/quota` va `done.pro` (ishlatildi / kerak
    bo'lmadi / limit).
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import re
import sys
import threading

from pathlib import Path

import pytest

from app.api.v1 import chat as chat_api
from app.services import analytics
from tests.test_contacts import people  # noqa: F401 - fikstura
from tests.test_integration_merge import PERSON_Q, PHONE, _no_assistant
from tests.test_pro import api, assistant, server  # noqa: F401 - fikstura

ROOT = Path(__file__).resolve().parents[3]
ASSIST_Q = "Yillik ta'til necha kun?"


@pytest.fixture
def db(_isolated_analytics):
    return _isolated_analytics


def rows(db, sql: str, params=()) -> list[dict]:
    analytics.flush()
    return db.rows(sql, params)


# --- `input`: savol qanday kiritilgani ------------------------------------------------


@pytest.mark.parametrize(("extra", "mode"), [
    # Mini App: o'qish rejimi yoqiq, savol YOZILGAN - "ovozli" emas.
    ({"voice": True, "input": "text"}, "text"),
    ({"voice": True, "input": "voice"}, "voice"),
    ({"voice": False, "input": "voice"}, "voice"),
    # Eski build / web: maydon yo'q - `voice` dan (avvalgi xulq).
    ({"voice": True}, "voice"),
    ({}, "text"),
])
def test_savol_izi_input_maydonidan(api, auth, server, db, extra, mode):
    r = api.post("/api/v1/chat/stream", headers={**auth, "X-Venera-Client": "miniapp"},
                 json={"question": ASSIST_Q, **extra})
    assert r.status_code == 200, r.text
    [turn] = rows(db, "SELECT input_mode, channel FROM turns")
    assert (turn["input_mode"], turn["channel"]) == (mode, "miniapp")
    # `input` faqat iz uchun - yuqoridagi xizmatga ketmaydi.
    assert "input" not in server.calls[-1]["body"]


def test_notanish_input_422(api, auth, server):
    r = api.post("/api/v1/chat/stream", headers=auth,
                 json={"question": ASSIST_Q, "input": "telepathy"})
    assert r.status_code == 422
    assert server.calls == []


def test_mini_app_har_savol_yolida_inputni_aytadi():
    """`apps/tg/app.js`: body'da `input`, va `ask` ning UCHALA chaqiruvi
    (mikrofon, tasdiq, yozib yuborish) `spoken` ni aniq beradi - `undefined`
    jimgina "text" bo'lib ketmasin."""
    src = (ROOT / "apps" / "tg" / "app.js").read_text(encoding="utf-8")
    assert "input: spoken ? 'voice' : 'text'" in src
    assert "async function streamAsk(question, onFrame, signal, spoken)" in src
    assert "streamAsk(question, onFrame, aborter ? aborter.signal : undefined, spoken)" in src
    calls = re.findall(r"(?<![\w.])ask\(([^)]*)\);", src)
    assert len(calls) == 3, calls
    assert sorted(c.split(",")[-1].strip() for c in calls) == ["false", "true", "true"], calls


# --- `contacts` oralig'i: admin izi uchun `answered` ----------------------------------


def test_contacts_oraligi_javob_berilganini_aytadi(client, auth, people, db, monkeypatch):
    monkeypatch.setattr(chat_api._assistant, "stream", _no_assistant)
    r = client.post("/api/v1/chat/stream", headers=auth, json={"question": PERSON_Q})
    assert r.status_code == 200 and PHONE in r.text
    [event] = rows(db, "SELECT payload FROM turn_events WHERE turn_id=? AND name='contacts'",
                   (r.headers["X-Venera-Turn"],))
    assert json.loads(event["payload"])["answered"] is True


def test_contacts_oraligi_yordamchi_savolida_false(api, auth, server, db):
    r = api.post("/api/v1/chat/stream", headers=auth, json={"question": ASSIST_Q})
    assert r.status_code == 200 and len(server.calls) == 1
    [event] = rows(db, "SELECT payload FROM turn_events WHERE turn_id=? AND name='contacts'",
                   (r.headers["X-Venera-Turn"],))
    assert json.loads(event["payload"])["answered"] is False


# --- soxta yuqori xizmat: "Pro" ----------------------------------------------------------


@pytest.fixture
def mock_upstream():
    """`tools/dev_mock_upstream.py` - vaqtinchalik portda, kechikishsiz."""
    path = ROOT / "apps" / "api" / "tools" / "dev_mock_upstream.py"
    spec = importlib.util.spec_from_file_location("dev_mock_upstream_b3", path)
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` modulni `sys.modules` dan qidiradi.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.OPTS.speed, module.OPTS.pro_day = 0.0, 2
    srv = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        sys.modules.pop(spec.name, None)


def _call(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"X-Client-Id": "t", "X-Client-Secret": "t", "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    return resp.status, data


def _done(port: int, question: str, **extra) -> dict:
    status, text = _call(port, "POST", "/api/chat/stream",
                         {"question": question, "user_id": "venera:7", **extra})
    assert status == 200, text
    frames = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert frames[-1]["type"] == "done"
    return frames[-1]


def test_soxta_xizmat_pro_shakli_jonli_xizmatdek(mock_upstream):
    from app.schemas.pro import ProQuota

    status, text = _call(mock_upstream, "GET", "/api/pro/quota?user_id=venera:7")
    assert status == 200
    quota = ProQuota(**json.loads(text))
    assert (quota.limits.day, quota.remaining.day, quota.used.day) == (2, 2, 0)

    # Standart savolda blok YO'Q; "pro" hujjat savoli byudjetdan yeydi.
    assert "pro" not in _done(mock_upstream, ASSIST_Q)
    pro = _done(mock_upstream, ASSIST_Q, mode="pro")["pro"]
    assert (pro["requested"], pro["used"], pro["calls"], pro["remaining"]["day"]) == (True, True, 1, 1)
    # Kichik gap - kerak bo'lmadi, byudjet yeyilmaydi.
    pro = _done(mock_upstream, "Salom", mode="pro")["pro"]
    assert (pro["used"], pro.get("reason"), pro["remaining"]["day"]) == (False, None, 1)
    # Tugadi: javob BOR, blokda sabab.
    _done(mock_upstream, ASSIST_Q, mode="pro")
    final = _done(mock_upstream, ASSIST_Q, mode="pro")
    assert final["pro"]["used"] is False and final["pro"]["reason"] == "limit"
    status, text = _call(mock_upstream, "GET", "/api/pro/quota?user_id=venera:7")
    assert json.loads(text)["remaining"]["day"] == 0
    # Boshqa odamning byudjeti alohida.
    status, text = _call(mock_upstream, "GET", "/api/pro/quota?user_id=venera:8")
    assert json.loads(text)["remaining"]["day"] == 2

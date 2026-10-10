"""v4 agent mijozi: sarlavhalar, xatolar, o'z navbati, sirlar, hisob - soxta transport bilan."""

from __future__ import annotations

import json
import threading
import urllib.error

import pytest

from app.services import analytics
from app.services.integrations.agent_v4 import AgentError, AgentV4Client, urllib_transport
from app.services.integrations.ollama import OllamaError
from tests.agent_fakes import SECRET, FakeAgent


def test_sarlavhalar_va_yol():
    fake = FakeAgent()
    client = fake.client()
    payload, request_id = client.complete({"purpose": "group_ask", "instructions": "s", "input": {"text": "u"}},
                                          op="group_ask")
    assert payload["output"].startswith("Agent javobi")
    [call] = fake.calls
    assert call["method"] == "POST" and call["url"] == "http://agent.test/api/v4/complete"
    headers = call["headers"]
    assert headers["X-Client-Id"] == "barno-test" and headers["X-Client-Secret"] == SECRET
    assert headers["X-Request-Id"] == request_id and len(request_id) == 32
    assert headers["X-Barno-Contract"] == "4.0" and headers["Content-Type"] == "application/json"
    # Yaratuvchi POST - `Idempotency-Key` (3.6); W3C `traceparent`.
    assert len(headers["Idempotency-Key"]) == 32
    version, trace, span, flags = headers["traceparent"].split("-")
    assert (version, flags, len(trace), len(span)) == ("00", "01", 32, 16)


def test_get_sorovlarda_idempotency_yoq_va_prefiks_sozlanadi():
    fake = FakeAgent()
    client = AgentV4Client("http://agent.test/", "id", SECRET, prefix="api/v3/", transport=fake)
    fake.handlers["/capabilities"] = lambda body: {"features": {}}
    # Prefiks `/api/v3` - soxta transport yo'lni `/api/v4` bo'yicha ajratadi, shuning uchun to'liq URL.
    with pytest.raises(AgentError):
        client.capabilities()
    assert fake.calls[0]["url"] == "http://agent.test/api/v3/capabilities"
    assert "Idempotency-Key" not in fake.calls[0]["headers"]


def test_sozlanmagan_mijoz_tarmoqqa_chiqmaydi():
    fake = FakeAgent()
    client = AgentV4Client("http://agent.test", "", "", transport=fake)
    assert not client.configured
    with pytest.raises(AgentError) as info:
        client.limits()
    assert info.value.code == "not_configured" and fake.calls == []


def test_agent_xatosi_kod_bilan_va_ollama_xatosi_sifatida_ushlanadi():
    fake = FakeAgent()
    fake.handlers["/complete"] = lambda body: (400, {"error": {
        "code": "unsupported_field", "message": f"store maydoni; secret={SECRET}", "retryable": False}})
    with pytest.raises(OllamaError) as info:                     # bugungi `except OllamaError` lar ushlaydi
        fake.client().complete({"purpose": "x"}, op="group_ask")
    exc = info.value
    assert isinstance(exc, AgentError) and exc.status == 400 and exc.code == "unsupported_field"
    assert SECRET not in str(exc)


def test_429_status_saqlanadi():
    fake = FakeAgent()
    fake.handlers["/complete"] = lambda body: (429, {"error": {"code": "quota_exceeded", "message": "kvota",
                                                               "retryable": True}})
    with pytest.raises(AgentError) as info:
        fake.client().complete({}, op="brief_extract")
    assert info.value.status == 429 and info.value.retryable


def test_tarmoq_xatosi_sirsiz():
    def broken(method, url, headers, body, timeout):
        raise urllib.error.URLError(f"connection refused {SECRET}")

    client = AgentV4Client("http://agent.test", "id", SECRET, transport=broken)
    with pytest.raises(AgentError) as info:
        client.chat({"purpose": "brief_crm"}, op="brief_crm")
    assert info.value.code == "network" and SECRET not in str(info.value)


def test_json_bolmagan_javob():
    client = AgentV4Client("http://agent.test", "id", SECRET,
                           transport=lambda *a: (200, {}, b"<html>proxy</html>"))
    with pytest.raises(AgentError) as info:
        client.limits()
    assert info.value.code == "bad_response"


def test_oz_navbati_tola_bolsa_kutmaydi():
    """Interaktiv mijoz o'z o'rinlari to'la bo'lsa DARHOL `busy` - chatning o'rinlari
    va foydalanuvchi kutmaydi; zahira yo'li ishlaydi."""
    entered, release = threading.Event(), threading.Event()

    def slow(method, url, headers, body, timeout):
        entered.set()
        release.wait(5)
        return 200, {}, b"{}"

    client = AgentV4Client("http://agent.test", "id", SECRET, transport=slow, max_concurrent=1)
    worker = threading.Thread(target=lambda: client.limits())
    worker.start()
    assert entered.wait(5)
    with pytest.raises(AgentError) as info:
        client.limits()
    assert info.value.code == "busy" and info.value.status == 503
    release.set()
    worker.join(5)
    assert client.limits() == {}                                  # o'rin qaytdi


def test_hisob_matnsiz(_isolated_analytics):
    fake = FakeAgent()
    fake.client().complete({"purpose": "group_ask", "instructions": "MAXFIY PROMPT",
                            "input": {"text": "MAXFIY MATN"}}, op="group_ask", units={"chars": 23})
    assert analytics.flush()
    [row] = _isolated_analytics.rows("SELECT service, op, status, units, error FROM api_calls")
    assert (row["service"], row["op"], row["status"]) == ("assistant", "group_ask", "ok")
    units = json.loads(row["units"])
    assert units["chars"] == 23 and units["tokens_in"] == 100 and units["tokens_out"] == 20
    assert "MAXFIY" not in json.dumps(row)


def test_job_kutish_muddat_otsa_bekor_qiladi():
    fake = FakeAgent()
    fake.handlers["/jobs/j_1"] = lambda body: {"job_id": "j_1", "status": "running"}
    fake.handlers["/jobs/j_1/cancel"] = lambda body: {"job_id": "j_1", "status": "cancelled"}
    ticks = iter([0.0, 0.0, 10.0, 10.0])
    with pytest.raises(AgentError) as info:
        fake.client().wait_job("j_1", deadline=5.0, sleep=lambda s: None, clock=lambda: next(ticks))
    assert info.value.code == "deadline_exceeded"
    assert fake.paths()[-1] == "/jobs/j_1/cancel"


def test_job_natijasi_va_xavfli_id():
    fake = FakeAgent()
    fake.handlers["/jobs/j_2"] = lambda body: {"job_id": "j_2", "status": "succeeded"}
    fake.handlers["/jobs/j_2/result"] = lambda body: {"days": []}
    assert fake.client().wait_job("j_2", deadline=5, sleep=lambda s: None) == {"days": []}
    with pytest.raises(AgentError):
        fake.client().job("../../admin")


def test_yonaltirishga_ergashilmaydi(monkeypatch):
    """3xx kuzatilmaydi: `X-Client-Secret` boshqa manzilga ketmasin."""
    import app.services.integrations.agent_v4 as module

    seen: list[str] = []

    class Opener:
        def open(self, request, timeout):
            seen.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 302, "Found", {"Location": "http://evil.test"}, None)

    monkeypatch.setattr(module, "_opener", Opener())
    status, _, body = urllib_transport("GET", "http://agent.test/api/v4/limits", {"X-Client-Secret": SECRET},
                                       None, 1.0)
    assert status == 302 and seen == ["http://agent.test/api/v4/limits"]
    assert isinstance(module._opener, Opener)
    # Haqiqiy opener'da yo'naltiruvchi qayta so'rov yaratmaydi.
    assert module._NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://evil.test") is None


# --- sharhdan keyin (2026-10-10): uzgich, manzil, xato matni --------------------------------


def test_xato_matnida_agent_izohi_yoq(_isolated_analytics):
    """Agentning 4xx izohi kirishimizni qaytarishi mumkin - matnda, `api_calls` da faqat kod."""
    fake = FakeAgent()
    fake.handlers["/complete"] = lambda body: (422, {"error": {
        "code": "invalid_input", "message": "Mijoz Aziz +998901234567 haqidagi matn yaroqsiz"}})
    with pytest.raises(AgentError) as info:
        fake.client().complete({"purpose": "group_ask"}, op="group_ask")
    exc = info.value
    assert str(exc) == "agent HTTP 422: invalid_input" and "Aziz" in exc.detail
    assert analytics.flush()
    [row] = _isolated_analytics.rows("SELECT error FROM api_calls")
    assert row["error"] == "invalid_input"


def test_kod_orniga_matn_kelsa_ham_jurnalga_tushmaydi():
    fake = FakeAgent()
    fake.handlers["/complete"] = lambda body: (400, {"error": {"code": "Aziz aytdi: maosh 5 mln"}})
    with pytest.raises(AgentError) as info:
        fake.client().complete({}, op="group_ask")
    assert info.value.code == "http_400" and "maosh" not in str(info.value)


def test_uzgich_ketma_ket_xatolardan_keyin_ochiladi_va_tiklanadi():
    from app.services.integrations.agent_v4 import Breaker

    now = [100.0]
    fake = FakeAgent()
    fake.handlers["/limits"] = lambda body: (503, {"error": {"code": "queue_full"}})
    client = fake.client(breaker=Breaker(failures=3, cooldown=30, clock=lambda: now[0]))
    for _ in range(3):
        with pytest.raises(AgentError):
            client.limits()
    assert len(fake.calls) == 3 and client.breaker.state()["open"]
    with pytest.raises(AgentError) as info:
        client.limits()
    assert info.value.code == "circuit_open" and len(fake.calls) == 3          # tarmoqqa chiqilmadi
    now[0] += 31
    fake.handlers["/limits"] = lambda body: {"complete": {}}
    assert client.limits() == {"complete": {}}                                 # sinov o'tdi - yopiladi
    assert not client.breaker.state()["open"] and client.breaker.state()["failures"] == 0


def test_uzgich_4xx_dan_ochilmaydi():
    fake = FakeAgent()
    fake.handlers["/limits"] = lambda body: (422, {"error": {"code": "bad"}})
    client = fake.client()
    for _ in range(5):
        with pytest.raises(AgentError):
            client.limits()
    assert not client.breaker.state()["open"] and len(fake.calls) == 5


def test_uzgich_tarmoq_xatosidan_ochiladi():
    from app.services.integrations.agent_v4 import Breaker

    def broken(method, url, headers, body, timeout):
        raise TimeoutError("timed out")

    client = AgentV4Client("http://agent.test", "id", SECRET, transport=broken,
                           breaker=Breaker(failures=2, cooldown=60))
    for _ in range(2):
        with pytest.raises(AgentError):
            client.limits()
    with pytest.raises(AgentError) as info:
        client.limits()
    assert info.value.code == "circuit_open"


@pytest.mark.parametrize("url, ok", [
    ("https://agent.example.com", True), ("http://10.10.50.4:8080", True), ("http://127.0.0.1:9000", True),
    ("http://localhost:8001", True), ("http://hr-assistant:8080", True), ("http://agent.brb.internal", True),
    ("http://agent.test", True), ("http://agent.example.com", False), ("http://8.8.8.8", False),
    ("ftp://10.0.0.1", False), ("", False), ("not a url", False),
])
def test_kalit_faqat_xavfsiz_manzilga(url, ok):
    from app.services.integrations.agent_v4 import safe_base_url

    assert safe_base_url(url) is ok
    client = AgentV4Client(url, "id", SECRET, transport=FakeAgent())
    assert client.configured is ok

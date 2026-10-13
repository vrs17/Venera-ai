"""Agent ("HR Assistant API") ning v4 shartnomasi mijozi - `agent-contract.md`.

NEGA ALOHIDA MIJOZ. `assistant.py` - bugungi chat oqimi (`/api/v1|v2|v3/chat/stream`)
va uning 4 ta o'rni (`hrm_assistant_max_concurrent`). Bu mijoz esa LLM ishlarini
agentga ko'chirish uchun YANGI endpointlarni chaqiradi: `capabilities`, `limits`,
`complete`, `chat` (yangi maydonlar bilan), `jobs`. O'z navbati bilan (`max_concurrent`):
fondagi brif yoki shadow taqqoslash jonli chatning o'rnini HECH QACHON olmaydi.

O'CHIQ BO'LIB KELADI. Uni `services/brain/routing.py` faqat `AGENT_V4_ENABLED=true`,
kredensial bor va `capabilities` kerakli imkoniyatni `true` degandagina ishlatadi.
Testlarda tarmoq yo'q: `transport` soxtasi beriladi.

SARLAVHALAR (shartnoma 3.2): `X-Client-Id/Secret` (chat bilan bir xil kalit),
`X-Request-Id` (bizning uuid4 hex), `traceparent` (W3C), `X-Barno-Contract`,
`X-Barno-Channel` va yaratuvchi POST larda `Idempotency-Key`.

QAYTA YO'NALTIRISH (3xx) KUZATILMAYDI: urllib o'zi kuzatsa `X-Client-Secret` ni
yangi manzilga ko'chirib yuborardi (`assistant.py` dagi qoida bilan bir xil).

XATO - `AgentError` (`OllamaError` ning vorisi): bugungi lokal yo'l kutayotgan
`except OllamaError` lar agent xatosini ham ushlaydi va zahiraga o'tadi. Xato
MATNIDA agentdan kelgan gap YO'Q - faqat HTTP kodi va `code` (2026-10-10, sharh):
agentning 4xx javobi kirishimizni (guruh yoki yig'ilish matnini) qaytarishi mumkin,
xato matni esa jurnal, `api_calls.error` va `shadow_results.error` ga tushadi.
Agentning o'z izohi faqat `AgentError.detail` da (sirsiz, qisqartirilgan).

UZGICH (circuit breaker). Agent ketma-ket `breaker_failures` marta ishlamasa
(tarmoq, vaqt tugashi, 5xx, 429) - `breaker_cooldown` soniya (har safar ikki
baravar, 5 daqiqagacha) unga BORILMAYDI: `AgentError(code="circuit_open")` darhol.
NEGA: agent o'chganda har guruh `/summary` yoki brif chaqiruvi 60 s timeout kutib,
keyingina lokal zahiraga o'tardi. Muddat tugagach keyingi chaqiruv sinov bo'ladi:
o'tsa - uzgich yopiladi, yiqilsa - yana ochiladi.

MANZIL. `X-Client-Secret` faqat `https` ga yoki ichki tarmoqqa (`localhost`,
xususiy IP, nuqtasiz yoki `.local`/`.internal` nomli host) yuboriladi
(`safe_base_url`). Aks holda mijoz "sozlanmagan" - kalit tashqariga ketmaydi.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from collections.abc import Callable, Mapping
from typing import Any

from ..analytics.meter import begin, redact
from .ollama import OllamaError

log = logging.getLogger(__name__)

#: `transport(method, url, headers, body, timeout) -> (status, headers, body)`.
Transport = Callable[[str, str, Mapping[str, str], "bytes | None", float],
                     "tuple[int, Mapping[str, str], bytes]"]

#: Javobning eng katta hajmi: undan katta javob - xato (xotira himoyasi).
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class AgentError(OllamaError):
    """Agent chaqiruvi bajarilmadi. `code` - shartnoma 15-bo'limidagi kod
    (`unsupported_field`, `queue_full`, ...) yoki bizniki (`not_configured`,
    `busy`, `network`, `bad_response`). `status` - HTTP kodi (bo'lsa)."""

    def __init__(self, message: str = "", status: int | None = None, *, code: str = "",
                 retryable: bool = False, detail: str = "") -> None:
        super().__init__(message, status=status)
        self.code = code
        self.retryable = retryable
        #: Agentning o'z izohi (sirsiz, <= 300 belgi) - jurnalga va omborga YOZILMAYDI.
        self.detail = detail


#: Ichki tarmoq nomlari: `X-Client-Secret` ni `http` orqali ham shularga yuborish mumkin.
#: `.test` va `.localhost` - RFC 6761: ochiq internetda hech qachon topilmaydi (sinovlar).
_INTERNAL_SUFFIXES = (".local", ".internal", ".lan", ".svc", ".cluster.local", ".intranet", ".test",
                      ".localhost")


def safe_base_url(url: str) -> bool:
    """Kalit (`X-Client-Secret`) shu manzilga yuborilishi mumkinmi: `https` - har qanday
    host; `http` - faqat ichki: `localhost`, xususiy/loopback/link-local IP, nuqtasiz
    (konteyner) nom yoki `_INTERNAL_SUFFIXES`. Prod: `http://10.10.50.4:8080` - ichki."""
    try:
        parts = urllib.parse.urlsplit(str(url or "").strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if not host or parts.scheme not in ("http", "https"):
        return False
    if parts.scheme == "https":
        return True
    if host == "localhost" or "." not in host or host.endswith(_INTERNAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


class Breaker:
    """Uzgich (modul izohi). Ip-xavfsiz; `clock` - testlar uchun."""

    def __init__(self, *, failures: int = 3, cooldown: float = 30.0, max_cooldown: float = 300.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.threshold = max(1, int(failures))
        self.base = max(1.0, float(cooldown))
        self.max_cooldown = max(self.base, float(max_cooldown))
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._cooldown = self.base
        self._open_until = 0.0
        self.opened = 0

    @property
    def open(self) -> bool:
        with self._lock:
            return self._clock() < self._open_until

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._cooldown = self.base
            self._open_until = 0.0

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures < self.threshold:
                return
            self._open_until = self._clock() + self._cooldown
            self._cooldown = min(self._cooldown * 2, self.max_cooldown)
            self.opened += 1
            seconds = int(self._open_until - self._clock())
        log.warning("Agent: ketma-ket xatolar - %d s davomida chaqirilmaydi (lokal yo'l)", seconds)

    def state(self) -> dict[str, Any]:
        with self._lock:
            left = max(0.0, self._open_until - self._clock())
            return {"open": left > 0, "failures": self._failures, "retryIn": round(left, 1),
                    "opened": self.opened}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None


_opener = urllib.request.build_opener(_NoRedirect())


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                     timeout: float) -> tuple[int, Mapping[str, str], bytes]:
    """Haqiqiy tarmoq (stdlib). HTTP xato ham javob sifatida qaytadi."""
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with _opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            data = exc.read(MAX_RESPONSE_BYTES + 1) or b""
        except Exception:                                   # noqa: BLE001
            data = b""
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, data


def traceparent() -> str:
    """W3C `traceparent`: `00-<32 hex>-<16 hex>-01`."""
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


class AgentV4Client:
    """v4 endpointlari. Har chaqiruv `api_calls` ga `assistant / <op>` bo'lib yoziladi
    (matn emas - faqat hajm va tokenlar)."""

    def __init__(self, base_url: str, client_id: str, client_secret: str, *, prefix: str = "/api/v4",
                 contract: str = "4.0", timeout: float = 60.0, max_concurrent: int = 2,
                 slot_wait: float = 0.0, channel: str = "api", transport: Transport | None = None,
                 name: str = "agent", breaker: Breaker | None = None) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.prefix = "/" + (prefix or "/api/v4").strip("/")
        self.client_id = client_id or ""
        self._secret = client_secret or ""
        self.contract = contract or "4.0"
        self.timeout = float(timeout)
        self.max_concurrent = max(1, int(max_concurrent))
        self.slot_wait = max(0.0, float(slot_wait))
        self.channel = channel
        self.name = name
        self._transport = transport or urllib_transport
        self._slots = threading.BoundedSemaphore(self.max_concurrent)
        self.breaker = breaker or Breaker()
        #: Kalit tashqi `http` manzilga yuborilmaydi (`safe_base_url`).
        self.url_ok = safe_base_url(self.base_url) if self.base_url else False

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.client_id and self._secret and self.url_ok)

    # --- umumiy ----------------------------------------------------------------------------

    def _headers(self, request_id: str, idempotency_key: str | None) -> dict[str, str]:
        headers = {
            "X-Client-Id": self.client_id,
            "X-Client-Secret": self._secret,
            "X-Request-Id": request_id,
            "traceparent": traceparent(),
            "X-Barno-Contract": self.contract,
            "X-Barno-Channel": self.channel,
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:128]
        return headers

    def _safe(self, text: Any) -> str:
        value = str(text or "")
        if self._secret and len(self._secret) >= 4:
            value = value.replace(self._secret, "***")
        return redact(value)

    def request(self, method: str, path: str, *, body: Mapping[str, Any] | None = None, op: str,
                idempotent: bool = False, timeout: float | None = None,
                units: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        """Bitta chaqiruv -> (JSON javob, bizning `X-Request-Id`). Xato - `AgentError`."""
        if not self.configured:
            raise AgentError("agent sozlanmagan", code="not_configured")
        if self.breaker.open:
            # Ketma-ket xatolar: tarmoqqa chiqmaymiz, chaqiruvchi darhol lokal zahiraga.
            raise AgentError("agent vaqtincha chaqirilmaydi (uzgich)", status=503, code="circuit_open",
                             retryable=True)
        got = (self._slots.acquire(timeout=self.slot_wait) if self.slot_wait
               else self._slots.acquire(blocking=False))
        if not got:
            # O'Z navbatimiz to'la: kutmaymiz - chaqiruvchi zahiraga o'tadi.
            raise AgentError("agent navbati band", status=503, code="busy", retryable=True)
        request_id = uuid.uuid4().hex
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = self._headers(request_id, uuid.uuid4().hex if idempotent else None)
        if data is not None:
            headers["Content-Type"] = "application/json"
        call = begin("assistant", op, units={"bytes": len(data or b""), **dict(units or {})})
        try:
            status, _, raw = self._transport(method, f"{self.base_url}{self.prefix}{path}", headers, data,
                                             timeout if timeout is not None else self.timeout)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            message = f"{type(exc).__name__}: {self._safe(exc)}"
            call.end("error", error=message)
            self.breaker.failure()
            raise AgentError(message, code="network", retryable=True) from exc
        except BaseException as exc:
            call.end("error", error=f"{type(exc).__name__}")
            raise
        finally:
            self._slots.release()
        if len(raw) > MAX_RESPONSE_BYTES:
            call.end("error", http_status=status, error="javob juda katta")
            raise AgentError("agent javobi juda katta", status=status, code="bad_response")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            payload = None
        if status >= 500 or status == 429:
            self.breaker.failure()
        else:
            # Agent javob berdi (4xx ham) - u tirik; uzgich hisobi nolga.
            self.breaker.success()
        if status >= 400:
            error = (payload or {}).get("error") if isinstance(payload, dict) else None
            error = error if isinstance(error, dict) else {}
            code = _code(error.get("code"), f"http_{status}")
            detail = self._safe(error.get("message") or "")[:300]
            # Matn - faqat kod: agent izohi kirishimizni qaytarishi mumkin (modul izohi).
            call.end("error", http_status=status, error=code)
            raise AgentError(f"agent HTTP {status}: {code}", status=status, code=code,
                             retryable=bool(error.get("retryable")), detail=detail)
        if not isinstance(payload, dict):
            call.end("error", http_status=status, error="JSON emas")
            raise AgentError("agent javobi JSON emas", status=status, code="bad_response")
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        extra = {name: meta[key] for name, key in (("tokens_in", "tokens_in"), ("tokens_out", "tokens_out"))
                 if isinstance(meta.get(key), int)}
        call.end("ok", http_status=status, units=extra)
        return payload, request_id

    # --- endpointlar (shartnoma 3.7, 6, 7, 8) ---------------------------------------------

    def capabilities(self, *, timeout: float = 10.0) -> dict[str, Any]:
        return self.request("GET", "/capabilities", op="capabilities", timeout=timeout)[0]

    def limits(self, *, timeout: float = 10.0) -> dict[str, Any]:
        return self.request("GET", "/limits", op="limits", timeout=timeout)[0]

    def complete(self, body: Mapping[str, Any], *, op: str, timeout: float | None = None,
                 units: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        """`POST /complete` - vositasiz bitta vazifa (7-bo'lim)."""
        return self.request("POST", "/complete", body=body, op=op, idempotent=True, timeout=timeout,
                            units=units)

    def speech(self, text: str, *, lang: str = "uz_latn", timeout: float | None = None) -> dict[str, Any]:
        """`POST /speech` - matnni quloq uchun yozadi (raqam, foiz, sana so'z bilan). Model
        chaqirilmaydi; javob `{"text", "lang"}`."""
        return self.request("POST", "/speech", body={"text": text, "lang": lang}, op="speech",
                            timeout=timeout)[0]

    def chat(self, body: Mapping[str, Any], *, op: str, timeout: float | None = None,
             units: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        """`POST /chat` - oqimsiz javob (6.2), yangi maydonlar bilan (6.1)."""
        return self.request("POST", "/chat", body=body, op=op, timeout=timeout, units=units)

    def submit_job(self, body: Mapping[str, Any], *, op: str, timeout: float | None = None) -> dict[str, Any]:
        """`POST /jobs` - 202 `{job_id, status, ...}` (8.1)."""
        return self.request("POST", "/jobs", body=body, op=op, idempotent=True, timeout=timeout)[0]

    def job(self, job_id: str, *, op: str = "job.status") -> dict[str, Any]:
        return self.request("GET", f"/jobs/{_job_id(job_id)}", op=op)[0]

    def job_result(self, job_id: str, *, op: str = "job.result") -> dict[str, Any]:
        return self.request("GET", f"/jobs/{_job_id(job_id)}/result", op=op)[0]

    def cancel_job(self, job_id: str, *, op: str = "job.cancel") -> dict[str, Any]:
        return self.request("POST", f"/jobs/{_job_id(job_id)}/cancel", op=op)[0]

    def wait_job(self, job_id: str, *, deadline: float, poll: float = 2.0,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
        """Natijani so'rab kutadi (SSE siz, oddiy so'rash). Muddat o'tsa - bekor
        qilinadi va `AgentError(code="deadline_exceeded")`."""
        ends = clock() + max(0.0, deadline)
        while True:
            state = self.job(job_id)
            status = str(state.get("status") or "")
            if status == "succeeded":
                return self.job_result(job_id)
            if status in ("failed", "cancelled", "expired"):
                error = state.get("error") if isinstance(state.get("error"), dict) else {}
                code = _code(error.get("code"), status)
                raise AgentError(f"job {status}: {code}", code=code,
                                 detail=self._safe(error.get("message") or "")[:300])
            if clock() >= ends:
                try:
                    self.cancel_job(job_id)
                except AgentError:
                    pass
                raise AgentError("job muddati o'tdi", code="deadline_exceeded", retryable=True)
            sleep(poll)


def _code(value: Any, fallback: str) -> str:
    """Agentning xato kodi - faqat `[a-z0-9_.-]`, <= 48 belgi (kod o'rnida matn kelsa ham
    jurnalga erkin matn tushmasin)."""
    text = str(value or "").strip()[:48]
    if text and all(ch.isalnum() or ch in "_.-" for ch in text):
        return text
    return fallback


def _job_id(value: str) -> str:
    """Yo'lga qo'yiladigan id: faqat xavfsiz belgilar (yo'lni buzib bo'lmasin)."""
    text = str(value or "")
    if not text or len(text) > 128 or not all(ch.isalnum() or ch in "-_" for ch in text):
        raise AgentError("noto'g'ri job id", code="bad_request")
    return text

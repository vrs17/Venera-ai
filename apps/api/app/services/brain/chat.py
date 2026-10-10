"""Matn yozadigan model chaqiruvlari uchun choc (seam): `OllamaChat` bilan BIR XIL shakl.

    writer = BrainChat(OllamaChat(...))        # bot: guruh xulosasi, savol, brif
    writer.complete(system, user, op="group_summary")

`op` bo'yicha funksiya topiladi (`engine_control.BRAIN_OP_FEATURE`) va uning flag'i
so'raladi (`routing.route`):

  * `local`  - AYNAN bugungi chaqiruv (`local.complete(...)` o'sha argumentlar bilan);
  * `shadow` - bugungi chaqiruv + namuna bo'yicha fonda agent (`shadow.py`), natija
    faqat taqqoslanadi;
  * `agent`  - agentning `POST /complete` i; xato bo'lsa - bugungi chaqiruv (zahira,
    `brain / fallback.<op>` bo'lib hisoblanadi). JSON kutilgan op'da (`format`) agent
    javobi JSON bo'lmasa ham - zahira (`invalid_output`): yaroqsiz natija foydalanuvchiga
    bormaydi, brif kuni "tahlil qilinmadi" bo'lib qolmaydi (sharh, 2026-10-10).
    Fon op'lari (`BATCH_OPS`) - alohida `batch` mijozi orqali: interaktivning o'rnini olmaydi.

`AgentComplete` - `complete_meta` shaklidagi agent mijozi, shartnomaning
"instructions mode" i (7.1, 7.3): bizning tizim prompti `instructions`, foydalanuvchi
matni `input.text`, javob - matn (`output_format: "text"`). Ya'ni agent AYNAN bugungi
vazifani o'z modelida bajaradi, natijani esa bugungi parser va tekshirgichlarimiz
(`polish_summary`, `parse_events`, `validate_events`, yig'ilish `Validator` i) o'qiydi.
Shablon reestri (W2) kelgach `template` ga o'tiladi - chaqiruv joylari o'zgarmaydi.

Yig'ilish xulosasi va savol-javobi bu o'ramdan EMAS, zanjir bo'g'ini sifatida o'tadi
(`features.py`): "bitta xulosa - bitta model" qoidasi buzilmasin.
"""

from __future__ import annotations

import json
import logging
import time

from collections.abc import Callable, Mapping
from typing import Any

from ..analytics.meter import current, record_call
from ..engine_control import BRAIN_OP_FEATURE
from ..integrations.agent_v4 import AgentError, AgentV4Client
from . import routing, shadow

log = logging.getLogger(__name__)

#: Bizning op -> shartnomadagi `purpose` (4.1). Yig'ilish qadamlari bitta `meeting_summary`.
PURPOSE: dict[str, str] = {
    "group_summary": "group_summary", "group_ask": "group_ask",
    "brief_extract": "brief_extract", "brief_extract_support": "brief_extract",
    "brief_headline": "brief_headline", "brief_project": "brief_project", "brief_crm": "brief_crm",
    "meeting_classify": "meeting_classify", "meeting_extract": "meeting_summary",
    "meeting_map": "meeting_summary", "meeting_write": "meeting_summary",
    "meeting_verify": "meeting_summary", "meeting_ask": "meeting_ask", "classify": "hold_route",
}

#: Fon ishlari (brif tayyorlash har 30 daqiqada) - `batch` navbati (shartnoma 14.3).
BATCH_OPS = frozenset({"brief_extract", "brief_extract_support"})
#: Guruh auditoriyasi: agent HR ma'lumotini va shaxsiy mavzularni chiqarmaydi (4.2).
GROUP_OPS = frozenset({"group_summary", "group_ask"})

#: Botdagi o'ram shu op'larni yo'naltiradi. `brief_crm` bu yerda EMAS: uning
#: agent shakli - butun CRM tekshiruvi bitta chat vazifasi (`features.brief_crm_ask`),
#: gemma normalizer esa lokal yo'lning bir qismi bo'lib qoladi.
BOT_OPS: dict[str, str] = {op: BRAIN_OP_FEATURE[op] for op in (
    "group_summary", "group_ask", "brief_extract", "brief_extract_support", "brief_headline",
    "brief_project")}


def actor_user_id() -> str | None:
    """`venera:{actorId}` - joriy hisob kontekstidan (bot, ishchi `bind` qilgan)."""
    actor = current().actor_id
    return f"venera:{actor}" if actor is not None else None


def note_fallback(feature: str, op: str, exc: BaseException) -> None:
    """Agent yo'li yiqildi - zahiraga o'tildi. Ulush kuzatiladi (maqsad < 2%)."""
    log.info("Miya: %s agentda bajarilmadi (%s) - lokal zahira", op,
             getattr(exc, "code", "") or type(exc).__name__)
    record_call("brain", f"fallback.{op}", status="error", error=exc)


class AgentComplete:
    """Agentning `complete` i - `OllamaChat.complete_meta` shaklida (instructions mode)."""

    def __init__(self, client: AgentV4Client | Callable[[], AgentV4Client], *, shadow: bool = False,
                 language: str = "uz", name: str = "agent", max_prompt_chars: int = 0) -> None:
        self._client = client
        self.shadow = bool(shadow)
        self.language = language if language in ("uz", "ru", "en") else "uz"
        self.name = name
        self.model = "agent"
        #: Zanjir bo'g'ini (`meetings.llm.Provider`) uchun: 0 - chegara yo'q (agent
        #: `413 payload_too_large` bersa - zanjirda keyingisi).
        self.max_prompt_chars = int(max_prompt_chars or 0)

    @property
    def client(self) -> AgentV4Client:
        # Fabrika (lambda) - mijoz har safar `routing` dan olinadi: testlar uni almashtira oladi.
        return self._client() if callable(self._client) else self._client

    @property
    def configured(self) -> bool:
        return self.client.configured and routing.agent_usable()[0]

    @property
    def timeout(self) -> float:
        return self.client.timeout

    def request(self, system: str, user: str, *, num_predict: int, temperature: float, op: str) -> dict[str, Any]:
        """Shartnoma 7.1 `CompleteReq` (instructions mode)."""
        body: dict[str, Any] = {
            "purpose": PURPOSE.get(op, op),
            "instructions": system,
            # `vars.op` - bizning qadam nomi (masalan `meeting_map`): agent tomonida qadam
            # bo'yicha o'lchash uchun; ko'rsatma emas (TaskInput.vars, 4.5).
            "input": {"text": user, "vars": {"op": op}},
            "output_format": "text",
            "language": self.language,
            "priority": "batch" if op in BATCH_OPS else "interactive",
            "max_output_tokens": int(num_predict),
            "temperature": float(temperature),
            "deadline_ms": int(self.client.timeout * 1000),
        }
        user_id = actor_user_id()
        if user_id:
            body["user_id"] = user_id
        if op in GROUP_OPS:
            body["audience"] = "group"
        if self.shadow:
            body["shadow"] = True
        return body

    def complete(self, system: str, user: str, *, num_predict: int = 1200, temperature: float = 0.2,
                 op: str = "group", format: str | None = None) -> str:
        return self.complete_meta(system, user, num_predict=num_predict, temperature=temperature, op=op,
                                  format=format)[0]

    def complete_meta(self, system: str, user: str, *, num_predict: int = 1200, temperature: float = 0.2,
                      op: str = "group", format: str | None = None, options: Mapping[str, Any] | None = None,
                      think: bool | None = None) -> tuple[str, dict[str, Any]]:
        """(matn, meta) - `OllamaChat.complete_meta` bilan bir xil. `format`, `options`,
        `think` - Ollama'ga xos, agentga yuborilmaydi (javob baribir parser'dan o'tadi)."""
        body = self.request(system, user, num_predict=num_predict, temperature=temperature, op=op)
        label = f"shadow.{op}" if self.shadow else op
        payload, request_id = self.client.complete(body, op=label,
                                                   units={"chars": len(system) + len(user)})
        output = payload.get("output")
        if isinstance(output, str):
            text = output
        elif output is None:
            text = ""
        else:
            text = json.dumps(output, ensure_ascii=False)
        text = text.strip()
        if not text:
            raise AgentError("agent bo'sh javob berdi", code="empty")
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        info = {
            # Kesilish - agentning o'z belgisi (`meta.truncated`). `tokensIn` ATAYLAB `None`:
            # yig'ilish quvuri uni Ollama'ning jim prompt qisqartirishini aniqlashga ishlatadi
            # (`summarize._truncated`), agent tokenizatori esa boshqa - noto'g'ri signal bo'lardi.
            "doneReason": "length" if meta.get("truncated") is True else "stop",
            "tokensIn": None,
            "agentTokensIn": meta.get("tokens_in") if isinstance(meta.get("tokens_in"), int) else None,
            "tokensOut": meta.get("tokens_out") if isinstance(meta.get("tokens_out"), int) else None,
            "thinkingChars": 0,
            "traceId": str(meta.get("trace_id") or "")[:64] or None,
            "requestId": request_id,
        }
        return text, info


def _wants_json(kwargs: Mapping[str, Any]) -> bool:
    """Chaqiruvchi JSON kutyaptimi (`format="json"` yoki sxema - `OllamaChat` dagi kabi)."""
    value = kwargs.get("format")
    return value == "json" or isinstance(value, Mapping)


def looks_json(text: str) -> bool:
    """Matnda o'qiladigan JSON obyekt yoki ro'yxat bormi (```json``` o'rami va oldidagi
    gap mumkin - bugungi parser'lar ham shunday o'qiydi)."""
    raw = str(text or "")
    if shadow.parse_json(raw) is not None:
        return True
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char in "[{":
            try:
                decoder.raw_decode(raw, index)
                return True
            except ValueError:
                continue
    return False


def _text_of(result: Any) -> str:
    """`complete` -> matn, `complete_meta` -> (matn, meta)."""
    if isinstance(result, tuple) and result:
        return str(result[0] or "")
    return str(result or "")


class BrainChat:
    """`OllamaChat` o'rnida turadi; har op o'z flag'i bo'yicha (modul izohi)."""

    def __init__(self, local: Any, *, ops: Mapping[str, str] | None = None,
                 agent: AgentComplete | None = None, shadow_agent: AgentComplete | None = None) -> None:
        self._local = local
        self._ops = dict(BOT_OPS if ops is None else ops)
        self._agent = agent or AgentComplete(lambda: routing.client("interactive"))
        #: Fon op'lari (`BATCH_OPS`, brif prewarm) - o'z mijozi va o'rni.
        self._batch_agent = agent or AgentComplete(lambda: routing.client("batch"))
        self._shadow_agent = shadow_agent or AgentComplete(lambda: routing.client("shadow"), shadow=True)

    def __getattr__(self, name: str) -> Any:
        # `model`, `base_url`, `timeout` va boshqalar - lokal mijozniki (bugungidek).
        return getattr(self._local, name)

    @property
    def local(self) -> Any:
        return self._local

    @property
    def configured(self) -> bool:
        if getattr(self._local, "configured", False):
            return True
        return any(routing.route(feature).agent for feature in set(self._ops.values()))

    def complete(self, system: str, user: str, **kwargs: Any) -> str:
        return self._run("complete", system, user, kwargs)

    def complete_meta(self, system: str, user: str, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        return self._run("complete_meta", system, user, kwargs)

    def _run(self, kind: str, system: str, user: str, kwargs: dict[str, Any]) -> Any:
        op = str(kwargs.get("op") or "group")
        feature = self._ops.get(op)
        local = getattr(self._local, kind)
        if feature is None:
            return local(system, user, **kwargs)
        route = routing.route(feature)
        num_predict = int(kwargs.get("num_predict", 1200))
        temperature = float(kwargs.get("temperature", 0.2))
        if route.agent:
            agent = self._batch_agent if op in BATCH_OPS else self._agent
            try:
                text, info = agent.complete_meta(system, user, num_predict=num_predict,
                                                 temperature=temperature, op=op)
                if _wants_json(kwargs) and not looks_json(text):
                    raise AgentError("agent javobi JSON emas", code="invalid_output")
                return (text, info) if kind == "complete_meta" else text
            except Exception as exc:                        # noqa: BLE001 - zahira har qanday xatoda
                note_fallback(feature, op, exc)
        started = time.monotonic()
        result = local(system, user, **kwargs)
        if route.shadow:
            local_ms = (time.monotonic() - started) * 1000.0
            self._shadow(feature, op, system, user, _text_of(result), local_ms, num_predict, temperature,
                         route.sample_rate)
        return result

    def _shadow(self, feature: str, op: str, system: str, user: str, local_text: str, local_ms: float,
                num_predict: int, temperature: float, sample_rate: float) -> None:
        agent = self._shadow_agent

        def job() -> None:
            started = time.monotonic()
            base = dict(local_ms=local_ms, input_chars=len(system) + len(user), local_chars=len(local_text))
            try:
                text, info = agent.complete_meta(system, user, num_predict=num_predict,
                                                 temperature=temperature, op=op)
            except AgentError as exc:
                shadow.record(feature, op, status="timeout" if exc.code in ("network", "deadline_exceeded")
                              else "error", agent_ms=(time.monotonic() - started) * 1000.0, error=exc,
                              **base)
                return
            shadow.record(feature, op, status="ok", trace_id=info.get("traceId"),
                          request_id=info.get("requestId"), agent_ms=(time.monotonic() - started) * 1000.0,
                          agent_chars=len(text), similarity=shadow.similarity(local_text, text),
                          metrics={**shadow.text_metrics(local_text, text),
                                   "truncated": info.get("doneReason") == "length"}, **base)

        shadow.submit(feature, job, sample_rate=sample_rate)

"""Har funksiya uchun: lokal, shadow yoki agent - va NEGA.

    route("group_summary") -> Route(effective="local" | "shadow" | "agent", reason=...)

IKKI QAVAT. Sozlangan holat (`engine_control.brain_choice`: admin -> `.env` ->
`local`) va xavfsizlik to'ri (CAPABILITY GUARD, `migration-plan.md` 1.2): flag
`shadow`/`agent` bo'lsa ham, quyidagilardan biri bo'lsa ish `local` da qoladi:

  * `AGENT_V4_ENABLED` o'chiq (bosh kalit, `.env` dan jonli) - `agent_disabled`;
  * kredensial yoki manzil yo'q - `agent_not_configured`; manzil tashqi `http` -
    `agent_url_not_internal` (kalit u yerga yuborilmaydi);
  * agent ketma-ket ishlamadi, uzgich ochiq - `circuit_open` (30 s dan, ikki baravar);
  * `GET /capabilities` hali o'qilmagan yoki o'qilmadi - `capabilities_unknown`;
  * agent tarmoq ichidagi modellarda ishlashini tasdiqlamagan
    (`in_network_models_only`) - `not_in_network`: guruh va yig'ilish matni
    tarmoqdan chiqmasligi kerak (shartnoma 3.7, 16.6);
  * funksiyaga kerakli imkoniyat `false` - `capability_missing:<nom>`.

Shuning uchun flag'ni agent jamoasi yetkazmasdan OLDIN yoqib qo'yish xavfsiz:
imkoniyat paydo bo'lgan zahoti (kesh yangilanganda) ish o'zi o'tadi.

SO'ROV YO'LI KUTMAYDI. `local` holat - faqat flag o'qish (5 s kesh). Imkoniyatlar
keshi bo'sh yoki eskirgan bo'lsa yangilash FONDA boshlanadi, javob esa darhol
(bo'sh kesh - `local`). Agentning sekin `/capabilities` i guruhdagi `/summary` ni
kuttirmasligi kerak.
"""

from __future__ import annotations

import logging
import threading
import time

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ...core import config as _config
from ...core.config import settings
from .. import engine_control as _control
from ..analytics.db import log_limited
from ..analytics.meter import carry
from ..integrations.agent_v4 import AgentError, AgentV4Client, Breaker

log = logging.getLogger(__name__)

#: Funksiya -> holat -> kerakli imkoniyatlar (`capabilities.features`).
#: `nom:qiymat` - ro'yxat ichida bo'lishi kerak (`frames:route`).
#:
#: W0-W2 ORALIG'I: matnli funksiyalar `complete` ning "instructions mode" ida
#: (7.1): bizning promptimiz va matnimiz o'zgarmasdan agent modeliga boradi,
#: natijani bizning parser va tekshirgichlarimiz o'qiydi. Shablon reestri
#: (`templates`) kelgach bu ro'yxat o'zgaradi.
NEEDS: dict[str, dict[str, tuple[str, ...]]] = {
    "group_summary": {"agent": ("complete", "instructions_mode"),
                      "shadow": ("complete", "instructions_mode", "shadow")},
    "group_ask": {"agent": ("complete", "instructions_mode"),
                  "shadow": ("complete", "instructions_mode", "shadow")},
    "brief_extract": {"agent": ("complete", "instructions_mode"),
                      "shadow": ("complete", "instructions_mode", "shadow")},
    "brief_crm": {"agent": ("purpose", "store", "tools_allowlist", "response_format"),
                  "shadow": ("purpose", "store", "tools_allowlist", "response_format", "shadow")},
    # Yig'ilish xulosasi rejada OXIRGI (W5): agent jamoasi `job_kinds` da `meeting_summary`
    # ni e'lon qilmaguncha (sig'im: bitta yig'ilish 5-27 chaqiruv, map-reduce, sana
    # grammatikasi) transkriptlar agentga bormaydi - `complete` paydo bo'lishi (W2) yetmaydi.
    # W5 kodi shu bo'g'inni job chaqiruviga almashtiradi; ungacha bo'g'in - instructions mode.
    "meeting_summary": {"agent": ("complete", "instructions_mode", "job_kinds:meeting_summary"),
                        "shadow": ("complete", "instructions_mode", "shadow", "job_kinds:meeting_summary")},
    "meeting_ask": {"agent": ("complete", "instructions_mode"),
                    "shadow": ("complete", "instructions_mode", "shadow")},
    # `route` kadri chat oqimining o'zida keladi - qo'shimcha chaqiruv yo'q.
    "hold_classify": {"agent": ("frames:route",), "shadow": ("frames:route",)},
    # W1: guruh CRM - v4 chat maydonlari (6.1). `chat_purge` - agentdagi suhbat haqiqiy o'chishi.
    "group_crm": {"agent": ("purpose", "store", "chat_visibility", "context", "audience", "tools_allowlist",
                            "chat_purge"),
                  "shadow": ("purpose", "store", "chat_visibility", "context", "audience", "tools_allowlist",
                             "shadow")},
    # W1: yig'ilish vazifasi CRM ga. Shadow yo'q - taklif yaratish fonda takrorlanmaydi
    # (`shadow` holati amalda `local` kabi ishlaydi, chaqiruv joyida).
    "meeting_crm": {"agent": ("purpose", "store", "tools_allowlist"),
                    "shadow": ("purpose", "store", "tools_allowlist", "shadow")},
    # Ovoz uchun matn: `features.speech`. Shadow yo'q (natija deterministik, taqqoslash
    # foyda bermaydi) - `shadow` chaqiruv joyida `local` kabi ishlaydi.
    "tts_speech": {"agent": ("speech",), "shadow": ("speech",)},
}

#: Modelsiz funksiyalar: agent matnni hech qanday modelga yubormaydi (sof kod, o'sha
#: serverda). Ularga "ichki tarmoq modeli / tashqi modelga ruxsat" qoidasi tegishli EMAS -
#: aks holda tashqi modellar o'chirilganda `/speech` ham behuda yopilib qolardi.
MODEL_FREE: frozenset[str] = frozenset({"tts_speech"})


@dataclass(frozen=True)
class Route:
    """`configured` - flag nima deydi; `effective` - hozir nima ishlaydi;
    `reason` - nega pastroq (bo'lsa)."""

    feature: str
    configured: str
    effective: str
    source: str
    sample_rate: float
    reason: str | None = None

    @property
    def agent(self) -> bool:
        return self.effective == "agent"

    @property
    def shadow(self) -> bool:
        return self.effective == "shadow"

    @property
    def local(self) -> bool:
        return self.effective == "local"


# --- imkoniyatlar ------------------------------------------------------------------------------


class Capabilities:
    """`GET /capabilities` javobi (3.7). Noma'lum imkoniyat - `false`."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        features = payload.get("features") if isinstance(payload, Mapping) else None
        self.features: Mapping[str, Any] = features if isinstance(features, Mapping) else {}
        self.contract = str(payload.get("contract") or "") if isinstance(payload, Mapping) else ""
        self.in_network = isinstance(payload, Mapping) and payload.get("in_network_models_only") is True
        #: Agent tashqi modelga (Ollama Cloud) ruxsat berilganini aytadi (egasining qarori,
        #: 2026-10-11). Bizning kalit bilan birga himoyadan o'tkazadi (`models_ok`).
        self.external_allowed = isinstance(payload, Mapping) and payload.get("external_models_allowed") is True

    def models_ok(self) -> bool:
        """Model qoidasi: ichki tarmoq modeli YOKI egasi ruxsat bergan tashqi model
        (`AGENT_V4_ALLOW_EXTERNAL_MODELS`, jonli). Ikkalasi ham yo'q - `local`."""
        return self.in_network or (self.external_allowed and _config.agent_v4_external_models_now())

    def has(self, name: str) -> bool:
        key, _, value = name.partition(":")
        found = self.features.get(key)
        if value:
            return isinstance(found, (list, tuple)) and value in found
        return found is True

    def view(self) -> dict[str, Any]:
        """Admin uchun: faqat `true` bo'lganlari va ro'yxatlar (sir yo'q)."""
        return {
            "contract": self.contract,
            "inNetwork": self.in_network,
            "externalAllowed": self.external_allowed,
            "features": sorted(k for k, v in self.features.items() if v is True),
            "frames": [str(f) for f in self.features.get("frames") or [] if isinstance(f, str)][:40],
            "jobKinds": [str(f) for f in self.features.get("job_kinds") or [] if isinstance(f, str)][:40],
        }


class CapabilityCache:
    """Imkoniyatlar keshi: eskirsa fonda yangilanadi, o'qish hech qachon kutmaydi.

    Oxirgi YAXSHI qiymat xato bo'lganda ham saqlanadi (agent qisqa uzilsa flag
    sakramasin); xato esa `error_ttl` dan keyin qayta uriniladi."""

    def __init__(self, fetch: Callable[[], Mapping[str, Any]], *, ttl: float = 300.0,
                 error_ttl: float = 60.0, clock: Callable[[], float] = time.monotonic,
                 background: bool = True) -> None:
        self._fetch = fetch
        self.ttl = float(ttl)
        self.error_ttl = float(error_ttl)
        self._clock = clock
        self.background = background
        self._lock = threading.Lock()
        self._value: Capabilities | None = None
        self._checked_at: float | None = None
        self._ok_at: float | None = None
        self._error: str | None = None
        self._fetching = False

    def get(self) -> Capabilities | None:
        now = self._clock()
        with self._lock:
            value, checked, error = self._value, self._checked_at, self._error
            wait = self.error_ttl if error else self.ttl
            stale = checked is None or now - checked >= wait
            start = stale and not self._fetching
            if start:
                self._fetching = True
        if start:
            if self.background:
                threading.Thread(target=carry(self._refresh), name="agent-capabilities",
                                 daemon=True).start()
            else:
                self._refresh()
                with self._lock:
                    value = self._value
        return value

    def refresh(self) -> Capabilities | None:
        """Darhol (sinxron) yangilash - admin sahifasi va testlar uchun."""
        with self._lock:
            if self._fetching:
                return self._value
            self._fetching = True
        self._refresh()
        with self._lock:
            return self._value

    def _refresh(self) -> None:
        try:
            payload = self._fetch()
            fresh = Capabilities(payload if isinstance(payload, Mapping) else {})
            error = None
        except AgentError as exc:
            fresh, error = None, exc.code or "error"
        except Exception as exc:                            # noqa: BLE001
            fresh, error = None, type(exc).__name__
        now = self._clock()
        with self._lock:
            self._checked_at = now
            self._error = error
            if fresh is not None:
                self._value, self._ok_at = fresh, now
            self._fetching = False
        if error:
            log_limited("brain.capabilities", "Agent imkoniyatlari o'qilmadi (%s)", error)

    def prime(self, payload: Mapping[str, Any] | None) -> None:
        """Qiymatni qo'lda qo'yish (testlar). `None` - kesh tozalanadi."""
        with self._lock:
            self._value = Capabilities(payload) if payload is not None else None
            self._checked_at = self._ok_at = self._clock() if payload is not None else None
            self._error = None
            self._fetching = False

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {"value": self._value.view() if self._value is not None else None,
                    "error": self._error, "checkedAgo": _ago(self._checked_at, self._clock()),
                    "okAgo": _ago(self._ok_at, self._clock())}


def _ago(at: float | None, now: float) -> float | None:
    return None if at is None else round(max(0.0, now - at), 1)


# --- mijozlar (har biri O'Z navbati bilan) ----------------------------------------------------------

_clients_lock = threading.Lock()
_clients: dict[str, AgentV4Client] = {}
_caps: CapabilityCache | None = None
#: BITTA uzgich hamma mijozlar uchun: agent - bitta servis; u o'chsa guruh, brif,
#: yig'ilish va shadow birga darhol lokal yo'lga o'tadi (`agent_v4.Breaker`).
_breaker: Breaker | None = None


def _shared_breaker() -> Breaker:
    global _breaker
    if _breaker is None:
        _breaker = Breaker(failures=settings.agent_v4_breaker_failures,
                           cooldown=settings.agent_v4_breaker_cooldown)
    return _breaker


def _build(name: str, *, breaker: Breaker | None = None) -> AgentV4Client:
    base = settings.agent_v4_base_url or settings.hrm_assistant_base_url
    common = dict(prefix=settings.agent_v4_prefix, contract=settings.agent_v4_contract,
                  client_id=settings.hrm_assistant_client_id,
                  client_secret=settings.hrm_assistant_client_secret, breaker=breaker or _shared_breaker())
    if name == "shadow":
        # Shadow: BITTA o'rin (default), ishchi ip slotni kutadi - foydalanuvchi emas.
        return AgentV4Client(base, timeout=settings.agent_shadow_timeout,
                             max_concurrent=settings.agent_shadow_max_concurrent,
                             slot_wait=settings.agent_shadow_timeout, channel="worker", name="shadow",
                             **common)
    if name == "batch":
        # Fon ishlari (brif prewarm, har 30 daqiqada <= 40 chaqiruv) - O'Z o'rni: interaktiv
        # `/summary` va `/askbarno` ning 2 ta o'rnini egallamasin. Band bo'lsa kutmaydi -
        # zahira (lokal) ishlaydi; prewarm ketma-ket bo'lgani uchun o'zi bilan to'qnashmaydi.
        return AgentV4Client(base, timeout=settings.agent_shadow_timeout,
                             max_concurrent=settings.agent_v4_batch_max_concurrent, channel="worker",
                             name="batch", **common)
    if name == "speech":
        # O'qib berish birinchi ovozgacha shuni kutadi: qisqa kutish va O'Z uzgichi - sekin
        # `/speech` guruh, brif va yig'ilishlarni lokal yo'lga o'tkazib yubormasin.
        return AgentV4Client(base, timeout=settings.tts_agent_speech_timeout, max_concurrent=4,
                             channel="web", name="speech", **{**common, "breaker": breaker or Breaker()})
    if name == "meetings":
        # Yig'ilish xulosasi o'z o'rnida: uzun xulosa guruh va brif chaqiruvlarini kuttirmasin.
        return AgentV4Client(base, timeout=settings.meetings_llm_timeout,
                             max_concurrent=settings.meetings_v3_max_concurrent,
                             slot_wait=settings.meetings_v3_slot_wait, channel="worker", name="meetings",
                             **common)
    return AgentV4Client(base, timeout=settings.agent_v4_timeout,
                         max_concurrent=settings.agent_v4_max_concurrent, channel="bot", name="interactive",
                         **common)


def client(name: str = "interactive") -> AgentV4Client:
    """`interactive` (guruh, brif sarlavhasi, savol-javob), `batch` (brif hodisalari),
    `meetings` (xulosa), `shadow` (fon taqqoslash)."""
    found = _clients.get(name)
    if found is not None:
        return found
    with _clients_lock:
        if name not in _clients:
            _clients[name] = _build(name)
        return _clients[name]


def speakable(text: str) -> tuple[str | None, dict[str, Any]]:
    """Ovoz uchun matn agentdan (`POST /speech`): raqam, foiz, mln/mlrd/trln, sana va vaqt
    o'zbekcha so'z bilan. `(matn, izoh)`; matn `None` - bugungi yo'l qoladi (flag `local`,
    agent tayyor emas, xato yoki kechikish). HECH QACHON xato bermaydi: ovoz bunga
    bog'liq bo'lib qolmasin."""
    found = route("tts_speech")
    info: dict[str, Any] = {"route": found.effective, "reason": found.reason}
    if not found.agent:
        return None, info
    try:
        payload = client("speech").speech(text, lang="uz_latn")
    except AgentError as exc:
        log_limited("brain.speech", "Agent /speech ishlamadi (%s) - bugungi yo'l", exc.code)
        info["error"] = exc.code
        return None, info
    got = payload.get("text")
    # Bo'sh yoki g'ayritabiiy uzun javob - ishonmaymiz (so'z bilan yozish matnni
    # uzaytiradi, lekin o'n baravardan ko'p emas).
    if not isinstance(got, str) or not got.strip() or len(got) > 10 * len(text) + 2000:
        info["error"] = "bad_response"
        return None, info
    return got.strip(), info


def probe_client() -> AgentV4Client:
    """Admin "Tizim xaritasi" sinovi uchun mijoz: sozlamasi `interactive` bilan AYNAN bir
    xil (manzil, kalit, shartnoma), lekin uzgichi O'ZINIKI va keshlanmaydi.

    NEGA ALOHIDA UZGICH. Uzgich hamma mijozga umumiy: agent o'chiq paytda admin "Sinab
    ko'rish" ni uch marta bossa, guruh, brif va yig'ilish 30 s davomida lokal yo'lga
    o'tib qolardi - sinov ishlab turgan tizimning xulqini o'zgartirmasligi kerak."""
    return _build("interactive", breaker=Breaker())


def capabilities() -> CapabilityCache:
    global _caps
    found = _caps
    if found is not None:
        return found
    with _clients_lock:
        if _caps is None:
            _caps = CapabilityCache(lambda: client().capabilities(), ttl=settings.agent_capabilities_ttl)
        return _caps


def reset_for_tests(*, interactive: AgentV4Client | None = None, meetings: AgentV4Client | None = None,
                    shadow: AgentV4Client | None = None, batch: AgentV4Client | None = None,
                    caps: Mapping[str, Any] | None = None) -> None:
    """Mijozlar, uzgich va imkoniyatlar keshini almashtiradi. `caps` berilsa - kesh
    to'ldiriladi va fonda yangilanmaydi (`ttl` cheksiz)."""
    global _caps, _breaker
    with _clients_lock:
        _clients.clear()
        _breaker = None
        for name, value in (("interactive", interactive), ("meetings", meetings), ("shadow", shadow),
                            ("batch", batch)):
            if value is not None:
                _clients[name] = value
        _caps = CapabilityCache(lambda: client().capabilities(), ttl=float("inf") if caps else 300.0,
                                background=False)
    if caps is not None:
        _caps.prime(caps)


# --- tanlov ------------------------------------------------------------------------------------------


def agent_usable() -> tuple[bool, str | None]:
    """Bosh kalit va kredensial. (ha/yo'q, sabab)."""
    if not _config.agent_v4_enabled_now():
        return False, "agent_disabled"
    found = client()
    if not found.configured:
        # Manzil tashqi `http` - kalit u yerga yuborilmaydi (`agent_v4.safe_base_url`).
        insecure = bool(found.base_url) and not getattr(found, "url_ok", True)
        return False, "agent_url_not_internal" if insecure else "agent_not_configured"
    if found.breaker.open:
        # Ketma-ket xatolar (`agent_v4.Breaker`): agentga borilmaydi, shadow ham navbatga tushmaydi.
        return False, "circuit_open"
    return True, None


def route(feature: str) -> Route:
    """Shu funksiya hozir qayerda ishlaydi. HECH QACHON xato bermaydi - shubhada `local`."""
    try:
        choice = _control.brain_choice(feature)
        base = dict(feature=feature, configured=choice.state, source=choice.source,
                    sample_rate=choice.sample_rate)
        if choice.state == "local":
            return Route(effective="local", **base)
        usable, reason = agent_usable()
        if not usable:
            return Route(effective="local", reason=reason, **base)
        caps = capabilities().get()
        if caps is None:
            return Route(effective="local", reason="capabilities_unknown", **base)
        if feature not in MODEL_FREE and not caps.models_ok():
            return Route(effective="local", reason="not_in_network", **base)
        missing = [name for name in NEEDS.get(feature, {}).get(choice.state, ("?",)) if not caps.has(name)]
        if missing:
            return Route(effective="local", reason="capability_missing:" + ",".join(missing), **base)
        return Route(effective=choice.state, **base)
    except Exception:                                       # noqa: BLE001
        log_limited("brain.route", "Miya yo'nalishi aniqlanmadi - local", exc_info=True)
        return Route(feature=feature, configured="local", effective="local", source="default",
                     sample_rate=0.0, reason="error")


# --- suhbatni haqiqiy o'chirish (shartnoma 10.6) -------------------------------------------


def purge_chat(chat_id: str, user_id: str) -> dict[str, Any] | None:
    """Agentdagi suhbatni HAQIQIY o'chirish: `DELETE /api/v4/chats/{id}?mode=purge
    &forget_learned=true` - xabarlar, qatorlar, iz va undan o'rganilganlar o'chadi, agent
    imzolangan kvitansiya qaytaradi. Guruh CRM suhbatlari uchun (ichida boshqa a'zolarning
    xabarlari bor): F0 da faqat yumshoq o'chirish bor edi.

    Natija:
      * `None` - v4 o'chirish hozir yo'q (agent o'chiq, `chat_purge` e'lon qilinmagan):
        chaqiruvchi eski (yumshoq) yo'lga o'tadi;
      * lug'at - o'chirildi (404 ham: agentda bunday suhbat yo'q);
      * `AssistantError` - imkoniyat BOR, lekin bajarilmadi: tozalovchi keyinroq qayta
        uradi (yumshoq o'chirishga TUSHMAYMIZ - aks holda "o'chirildi" deb belgilanib,
        haqiqiy o'chirish hech qachon bo'lmasdi)."""
    from urllib.parse import quote

    from ..integrations.assistant import AssistantError

    usable, _ = agent_usable()
    if not usable:
        return None
    caps = capabilities().get()
    if caps is None or not caps.has("chat_purge"):
        return None
    path = (f"/chats/{quote(str(chat_id), safe='')}?user_id={quote(str(user_id), safe='')}"
            "&mode=purge&forget_learned=true")
    try:
        payload, _ = client().request("DELETE", path, op="chat.purge", timeout=30.0)
    except AgentError as exc:
        if exc.status == 404:
            return {}
        # Tozalovchining `_agent_down` tili: agentning o'zi ishlamasa aylanish to'xtaydi.
        down = exc.code in ("network", "circuit_open", "busy") or (exc.status or 0) >= 500 \
            or exc.status in (401, 429)
        raise AssistantError(f"agent v4 purge: {exc.code}", status=503 if down else (exc.status or 502),
                             retryable=down, reason="upstream_busy" if down else "upstream_http") from None
    receipt = payload.get("receipt") if isinstance(payload, dict) else None
    log.info("Agent: suhbat haqiqiy o'chirildi (kvitansiya %s)", "bor" if receipt else "yo'q")
    return payload if isinstance(payload, dict) else {}

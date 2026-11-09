"""Venera Yozuv - yig'ilish yozuvchisi (spetsifikatsiya: `docs/plans/meeting-recorder.md`).

    store.py       SQLite ombor, migratsiyalar, fayllar (700/600)
    audio.py       ADTS/MP4 o'lchash, bo'lish, m4a remux - sof Python
    transcribe.py  GAPI (spikerlar bilan) va Router (ru/en) bosqichi
    prompts.py     promptlar, `PROMPT_VERSION`
    templates.py   shablonlar va bo'lim sarlavhalari
    summarize.py   xulosa quvuri: bir o'tish / map-reduce, tekshiruv, yakun
    dates.py       muddatlarni kod hal qiladi
    ask.py         yig'ilish bo'yicha savol-javob (manbali)
    export.py      Markdown/TXT/SRT
    worker.py      fon ishchisi: ijara, qayta urinish, kvota, tozalash
    service.py     endpointlar mantig'i (router'da mantiq yo'q)
    errors.py      xato kodlari va o'zbekcha xabarlar

Bu modul - YAGONA "ish vaqti" (`Runtime`): ombor, GAPI klienti, Router
klienti, model klientlari (Ollama, OpenAI, Claude) va yordamchining v3 klienti. Testlar
uni `reset_for_tests` bilan soxtalariga almashtiradi - hech bir test tarmoqqa chiqmaydi.

    llm.py         model zanjiri: v3 -> OpenAI -> Claude -> Ollama (xulosa va savol-javob);
                   bayonnoma zanjiri (`MEETINGS_MINUTES_CHAIN`, default Claude)
    shapes.py      JSON sxemalari: OpenAI `strict`, Claude `output_config.format`
    crm.py         vazifani CRM ga: v3 taklifi (`proposal`), tasdiqlash - `/actions`
"""

from __future__ import annotations

import logging
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ...core.config import claude_key_now, claude_workspace_now, ollama_key_now, openai_key_now, settings
from ..integrations.assistant import AssistantClient
from ..integrations.gapi_stt import GapiSttClient
from ..integrations.ollama import OllamaChat
from ..stt import SttClient
from .prompts import PROMPT_VERSION
from .store import MeetingStore, new_id

log = logging.getLogger(__name__)


@dataclass
class Runtime:
    store: MeetingStore
    gapi: Any
    router: Any
    llm: Any
    ask_llm: Any
    devices: Any = None
    #: v3 ("Venera Core") - yig'ilish ishchisining O'Z klienti (alohida navbat): fondagi
    #: xulosa chatdagi odamlarning slotlarini olmasin. `None` - v3 yo'q.
    assistant: Any = None
    #: OpenAI: xulosa (1 slot) va savol-javob (2 slot, qisqa kutish) - Ollama kabi alohida.
    openai: Any = None
    ask_openai: Any = None
    #: Claude (Anthropic): xulosa va bayonnoma (1 slot) va savol-javob (2 slot) - alohida klientlar.
    claude: Any = None
    ask_claude: Any = None
    #: Savol-javob va CRM uchun v3 klienti. `None` - chatning o'zi (`chat._assistant`):
    #: odam kutib turgan so'rov chat bilan bir navbatda, taklif ham o'sha klientda tasdiqlanadi.
    live_assistant: Any = None
    clock: Callable[[], float] = time.time
    last_auth_failure: float | None = None
    worker: Any = None
    #: Model zanjiri kutishlari (v3 slot, qayta urinish) - testlar uni bo'sh funksiyaga almashtiradi.
    sleep: Callable[[float], None] = time.sleep
    #: v3 da BIR VAQTDA yoziladigan xulosalar (`MEETINGS_V3_MAX_CONCURRENT`): ikki ishchi ipi
    #: bitta v3 slotini chaqiruvma-chaqiruv talashib, yarim xulosani "band" bilan tashlamasin -
    #: ikkinchi xulosa butunlay navbatda kutadi (30 s dan keyin qayta).
    v3_gate: Any = None
    #: Xulosa (id, transkript versiyasi) -> (vaqt, shu xulosada yiqilgan provayderlar): qayta
    #: navbatga tushgan xulosa yiqilgan modelni boshidan takrorlamaydi (`llm.run_chain(skip=...)`).
    chain_failures: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.v3_gate is None:
            self.v3_gate = threading.BoundedSemaphore(max(1, int(settings.meetings_v3_max_concurrent or 1)))

    def note_auth_failure(self, now: float) -> None:
        """GAPI 401/403 - kalit noto'g'ri; `/api/health/detail` da ogohlantirish."""
        self.last_auth_failure = now

    def schedule_primary(self, m: dict[str, Any], now: float) -> str:
        """Transkript tayyor - asosiy xulosa navbatga, yig'ilish `summarizing`."""
        sid = new_id()
        self.store.insert_summary({
            "id": sid, "meeting_id": m["id"], "template": m.get("template") or "auto",
            "requested_template": m.get("template") or "auto", "language": m.get("language") or "uz",
            "prompt_version": PROMPT_VERSION, "transcript_rev": int(m.get("transcript_rev") or 0),
            "status": "queued", "created_at": int(now)})
        self.store.update_meeting(m["id"], now=now, status="summarizing", primary_summary_id=sid,
                                  summary_status="queued", progress=80.0, next_attempt_at=None)
        m.update(status="summarizing", primary_summary_id=sid, summary_status="queued")
        return sid


def _gapi_meeting_client() -> GapiSttClient:
    """UCHINCHI GAPI klienti - faqat yig'ilishlar uchun: bitta slot (chatning
    ikki slotini hech qachon olmaydi), 120 s har HTTP amal, ichki qayta
    urinishsiz (ishchi o'zi kutadi va holatni diskda saqlaydi)."""
    return GapiSttClient(settings.gapi_base_url, settings.gapi_api_key, timeout=settings.meetings_stt_timeout,
                         max_concurrent=1, deadline=settings.meetings_stt_deadline, attempts=1,
                         api_key2=settings.gapi_api_key2)


def _router_client() -> SttClient:
    """Ru/en uchun alohida Router klienti - bitta slot, chat diktovkasidan ajratilgan."""
    return SttClient(settings.stt_base_url, timeout=120.0, attempts=2, max_concurrent=1, deadline=300.0)


def _llm(max_concurrent: int, timeout: float) -> OllamaChat:
    """Yig'ilish xulosasi O'Z model klientida: guruh xulosalari va brif uni kutmasin."""
    return OllamaChat(settings.ollama_base_url, ollama_key_now,
                      settings.meetings_llm_model or settings.ollama_model,
                      timeout=timeout, max_concurrent=max_concurrent)


def _assistant() -> AssistantClient:
    """Yig'ilish xulosasi uchun v3 klienti: chatniki bilan bir xil manzil va kalit, lekin
    o'z navbati (`MEETINGS_V3_MAX_CONCURRENT`) va uzunroq kutish - agent 20 ming
    belgilik savolni o'qib, javob yozishni boshlaguncha chat savolidan ko'proq o'ylaydi."""
    return AssistantClient(settings.hrm_assistant_base_url, settings.hrm_assistant_client_id,
                           settings.hrm_assistant_client_secret, timeout=settings.meetings_v3_timeout,
                           max_concurrent=settings.meetings_v3_max_concurrent,
                           max_stream_seconds=settings.meetings_v3_max_stream_seconds)


def _openai(max_concurrent: int, timeout: float, retries: int = 0) -> Any:
    from .llm import OpenAIChat

    return OpenAIChat(settings.openai_base_url, openai_key_now, settings.meetings_openai_model,
                      timeout=timeout, max_concurrent=max_concurrent,
                      max_output_tokens=settings.meetings_openai_max_output_tokens,
                      reasoning_effort=settings.meetings_openai_reasoning_effort,
                      temperature=_temperature(settings.meetings_openai_temperature), retries=retries)


def _temperature(raw: Any) -> float | None:
    """`MEETINGS_OPENAI_TEMPERATURE`: bo'sh yoki noto'g'ri - yuborilmaydi."""
    try:
        return float(str(raw).strip()) if str(raw or "").strip() else None
    except ValueError:
        return None


def _claude(max_concurrent: int, timeout: float, retries: int = 0) -> Any:
    """Claude (Anthropic SDK). EGA QARORI (2026-11-04): xulosa va bayonnoma gemma4:31b o'rniga
    Claude Sonnet 5.5. Kalit `claude_key_now` bilan JONLI (`.env` dagi `CLAUDE_API_KEY` - kalit
    qo'yilgach restartsiz ishlaydi), model, manzil, javob chegarasi va `effort` - sozlamadan.
    Xulosa klienti (1 slot, uzun kutish, SDK qayta urinishlari) va savol-javob klienti (2 slot,
    qisqa kutish, qayta urinishsiz - odam kutib turibdi) alohida, OpenAI/Ollama kabi."""
    from .llm import ClaudeChat

    return ClaudeChat(claude_key_now, settings.meetings_claude_model, base_url=settings.claude_base_url,
                      timeout=timeout, max_concurrent=max_concurrent,
                      max_output_tokens=settings.meetings_claude_max_output_tokens,
                      effort=settings.meetings_claude_effort, retries=retries,
                      workspace_id=claude_workspace_now)


def _devices():
    from ..devices import DeviceStore

    return DeviceStore(settings.devices_db)


_runtime: Runtime | None = None
_runtime_lock = threading.Lock()


def runtime() -> Runtime:
    """Ilova bo'yicha bitta `Runtime` - birinchi chaqiruvda (import paytida EMAS:
    testlar yo'llarni almashtirishga ulgursin)."""
    global _runtime
    found = _runtime
    if found is not None:
        return found
    with _runtime_lock:
        if _runtime is None:
            _runtime = Runtime(
                store=MeetingStore(settings.meetings_dir),
                gapi=_gapi_meeting_client(),
                router=_router_client(),
                llm=_llm(1, settings.meetings_llm_timeout),
                # Savol-javob odam kutib turgan paytda - xulosa navbatida turmasin.
                ask_llm=_llm(2, 120.0),
                devices=_devices(),
                assistant=_assistant(),
                # Xulosa: 5xx/tarmoqda bir marta qayta; savol: odam kutib turibdi - qayta urinish yo'q.
                openai=_openai(1, settings.meetings_openai_timeout, settings.meetings_openai_retries),
                ask_openai=_openai(2, 120.0),
                # Claude (ega qarori 2026-11-04): xulosa va bayonnoma - uzun kutish, SDK qayta
                # urinishlari; savol - 2 slot, qisqa, qayta urinishsiz (odam kutib turibdi).
                claude=_claude(1, settings.meetings_claude_timeout, settings.meetings_claude_retries),
                ask_claude=_claude(2, 120.0, 0),
            )
        return _runtime


def reset_for_tests(root: Path | str, *, gapi: Any = None, router: Any = None, llm: Any = None,
                    ask_llm: Any = None, devices: Any = None, assistant: Any = None, openai: Any = None,
                    ask_openai: Any = None, live_assistant: Any = None, claude: Any = None,
                    ask_claude: Any = None) -> Runtime:
    """Ish vaqtini vaqtinchalik papka va soxta klientlarga almashtiradi. `ask_*` berilmasa -
    o'sha xulosa klienti (test bitta soxtani kuzatadi). Claude default `None` (sozlanmagan):
    testlar `FakeAnthropic` li `ClaudeChat` ni o'zi qo'yadi (`rt.claude`, `rt.ask_claude`)."""
    global _runtime
    with _runtime_lock:
        old = _runtime
        _runtime = Runtime(store=MeetingStore(root), gapi=gapi, router=router, llm=llm,
                           ask_llm=ask_llm if ask_llm is not None else llm, devices=devices,
                           assistant=assistant, openai=openai,
                           ask_openai=ask_openai if ask_openai is not None else openai,
                           claude=claude, ask_claude=ask_claude if ask_claude is not None else claude,
                           live_assistant=live_assistant,
                           # Testlar haqiqatan uxlamaydi (v3 slotini kutish, qayta urinish).
                           sleep=lambda seconds: None)
    if old is not None:
        if old.worker is not None:
            old.worker.stop(1.0)
        old.store.close_all()
    return _runtime


def start() -> None:
    """Ilova ishga tushganda (`main.py`). `MEETINGS_WORKER=false` - ip yo'q."""
    # Bayonnoma: oldingi jarayondan qolgan `running` qatorlar darhol `interrupted` (`minutes.recover`) -
    # ishchi o'chiq bo'lsa ham (bayonnomani ishchi emas, REST havzasi va botlar yozadi).
    from .minutes import recover as recover_minutes

    try:
        recover_minutes(runtime().store)
    except Exception:                                            # noqa: BLE001
        log.exception("Bayonnoma: qolib ketgan running qatorlarni tozalab bo'lmadi")
    if not settings.meetings_worker:
        return
    from .worker import Worker

    rt = runtime()
    if rt.worker is None:
        rt.worker = Worker(rt, threads=settings.meetings_worker_threads)
    rt.worker.start()


def stop() -> None:
    rt = _runtime
    if rt is not None and rt.worker is not None:
        rt.worker.stop()
    # Bayonnoma fon havzasi (REST `minutes.start`): navbatdagi ishlar to'xtash paytida boshlanib, pullik
    # chaqiruvni jarayon bilan birga yo'qotmasin.
    from .minutes import stop as stop_minutes

    stop_minutes()


def status() -> dict[str, Any]:
    """`/api/health/detail` uchun: sonlar va daqiqalar - MAZMUN YO'Q.

    Ombor diskda bo'lmasa - yaratilmaydi (bo'lim o'chiq, ma'lumot yo'q)."""
    from ...core import config
    from . import dates

    rt = runtime()
    enabled = config.meetings_enabled_now()
    out: dict[str, Any] = {"enabled": enabled, "worker": rt.worker.status() if rt.worker else {"alive": False},
                           "gapiConfigured": bool(getattr(rt.gapi, "configured", False)),
                           "llmConfigured": bool(getattr(rt.llm, "configured", False))}
    from .llm import chain_state

    # Zanjir: provayder nomi, sozlanganmi, modeli - kalit va manzil YO'Q.
    out["llmChain"] = chain_state(rt)
    spend = getattr(rt.gapi, "spend", None)
    if callable(spend):
        out["gapiSpend"] = spend()
    if not rt.store.exists:
        out.update({"counts": {}, "minutesToday": 0.0, "oldestQueuedSec": None})
        return out
    now = time.time()
    out["counts"] = rt.store.counts()
    out["minutesToday"] = round(rt.store.used_sec(dates.day_key(now), 0) / 60.0, 1)
    oldest = rt.store.scalar("SELECT MIN(COALESCE(completed_at, updated_at)) FROM meetings "
                             "WHERE status IN ('uploaded','transcribing','summarizing','waiting_quota')")
    out["oldestQueuedSec"] = int(now - oldest) if oldest else None
    out["lastAuthFailureAt"] = rt.last_auth_failure
    return out

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
klienti va ikkita model klienti. Testlar uni `reset_for_tests` bilan
soxtalariga almashtiradi - hech bir test tarmoqqa chiqmaydi.
"""

from __future__ import annotations

import logging
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ...core.config import ollama_key_now, settings
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
    clock: Callable[[], float] = time.time
    last_auth_failure: float | None = None
    worker: Any = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

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
                         max_concurrent=1, deadline=settings.meetings_stt_deadline, attempts=1)


def _router_client() -> SttClient:
    """Ru/en uchun alohida Router klienti - bitta slot, chat diktovkasidan ajratilgan."""
    return SttClient(settings.stt_base_url, timeout=120.0, attempts=2, max_concurrent=1, deadline=300.0)


def _llm(max_concurrent: int, timeout: float) -> OllamaChat:
    """Yig'ilish xulosasi O'Z model klientida: guruh xulosalari va brif uni kutmasin."""
    return OllamaChat(settings.ollama_base_url, ollama_key_now,
                      settings.meetings_llm_model or settings.ollama_model,
                      timeout=timeout, max_concurrent=max_concurrent)


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
            )
        return _runtime


def reset_for_tests(root: Path | str, *, gapi: Any = None, router: Any = None, llm: Any = None,
                    ask_llm: Any = None, devices: Any = None) -> Runtime:
    """Ish vaqtini vaqtinchalik papka va soxta klientlarga almashtiradi."""
    global _runtime
    with _runtime_lock:
        old = _runtime
        _runtime = Runtime(store=MeetingStore(root), gapi=gapi, router=router, llm=llm,
                           ask_llm=ask_llm if ask_llm is not None else llm, devices=devices)
    if old is not None:
        if old.worker is not None:
            old.worker.stop(1.0)
        old.store.close_all()
    return _runtime


def start() -> None:
    """Ilova ishga tushganda (`main.py`). `MEETINGS_WORKER=false` - ip yo'q."""
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

"""Fon ishchisi: transkripsiya, xulosa, tozalash (spetsifikatsiya 3.3, 4.3).

NEGA JARAYON ICHIDA (Celery, Redis emas). Yuk kichik - kuniga o'nlab
yig'ilish - va har qo'shimcha xizmat deploy, monitoring va xotira (server
3 GB) talab qiladi. Navbatning o'zi SQLite jadvalida turadi.

CHEGARALANGAN PARALLELLIK. `meetings_worker_threads` (2) ta ip: biri GAPI
natijasini kutayotganda ikkinchisi xulosa yozadi. Har ip navbatdan bitta
yig'ilishni IJARAGA oladi (`lease_until`) va BITTA qadam bajaradi.

IJARA HAR IPNIKI. Har ipning o'z `owner` i bor (`<pid>-<uuid>-<ip>`), jarayon
esa hozir ishlanayotgan yig'ilishlar to'plamini (`_inflight`) saqlaydi -
`claim` ularni olmaydi. Alohida "yurak urishi" ipi har 60 s da shu
yig'ilishlarning ijarasini uzaytiradi: uzoq BITTA amal (150 MB yuklash,
20 bo'lakli Router, model navbatini kutish) 300 s dan oshsa ham ikkinchi ip
o'sha yig'ilishni qayta olmaydi. Yakuniy yozuvlar (transkript, xulosa) faqat
ijara hali SHU ipda bo'lsa bajariladi.

YIQILISHGA CHIDAMLI. Holat to'liq omborda: vazifa raqami, yuborilgan payt,
map bo'laklari keshi. Xizmat o'rtada to'xtasa ijara muddati o'tadi va
qadam boshqa ip (yoki qayta ishga tushgan xizmat) tomonidan davom ettiriladi.
GAPI ga yuborilgan audio QAYTA yuborilmaydi (`transcribe.py`), tayyor map
bo'laklari uchun model QAYTA chaqirilmaydi (`summary_parts`).

BITTA NUSXA. Bir nechta uvicorn ishchisi bo'lsa ham navbatni faqat bittasi
ishlaydi - `worker.lock` ga `fcntl` qulfi.

BO'LIM O'CHIQ BO'LSA navbat ishlanmaydi, lekin ombor diskda bo'lsa TOZALASH
davom etadi: saqlash muddati - va'da, bayroq esa uni bekor qilmasligi kerak.
Ombor yo'q bo'lsa ishchi hech narsa yaratmaydi.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
import uuid

from typing import Any

from ...core.config import settings
from .. import brain as _brain
from ..analytics import bind
from . import llm as llm_mod
from . import store as store_mod
from .prompts import PROMPT_VERSION
from .store import jdump, jload, new_id
from .summarize import (LlmBusy, LlmFailed, LlmRateLimited, LlmUnavailable, Pipeline, SummaryInput, similar)
from .transcribe import LeaseLost, Transcriber, language_warning

log = logging.getLogger(__name__)

#: Ijara: shuncha soniyada yangilanmasa ish boshqa ipga o'tadi.
LEASE_SEC = 300
#: Model 429 bersa: 5, keyin 15 daqiqa; UCHINCHI 429 - xulosa `llm_failed` (qayta
#: urinish mumkin). Aks holda Ollama kvotasi tugaganda yig'ilish soatlab
#: `summarizing` da qolib, telefonlar har 5 s da so'rab turardi.
LLM_RATE_BACKOFF = (300, 900, 1800)
LLM_RATE_LIMIT_ATTEMPTS = 3
#: Boshqa model xatolari: jami shuncha urinish.
LLM_ATTEMPTS = 3
#: O'z model navbatimiz band (`LlmBusy`) - urinish emas, shuncha soniyadan keyin.
LLM_BUSY_WAIT = 30
#: Ishchi qadamida kutilmagan xato - shuncha soniya kutib (issiq aylanish bo'lmasin).
ERROR_WAIT = 60
#: Yurak urishi: ishlanayotgan yig'ilishlar ijarasi shuncha soniyada uzaytiriladi.
HEARTBEAT_EVERY = 60
#: Tozalash har soatda.
PURGE_EVERY = 3600
#: Hali ishlanayotgan holatlar - audio va yig'ilish tozalashdan o'tkazib yuboriladi.
IN_PROGRESS = ("uploading", "uploaded", "transcribing", "waiting_quota", "summarizing")


class Cancelled(Exception):
    """Yig'ilish ish paytida o'chirildi - joriy qadamdan keyin to'xtaladi."""


# --- xulosa bosqichi ---------------------------------------------------------------


def summary_input(rt: Any, m: dict[str, Any], s: dict[str, Any]) -> SummaryInput:
    segments = rt.store.segments(m["id"])
    speakers = [sp for sp in rt.store.speakers(m["id"]) if not sp.get("merged_into")]
    detected = jload(m.get("detected_lang"))
    return SummaryInput(
        meeting_id=m["id"], rev=int(m["transcript_rev"] or 0), recorded_at=float(m.get("recorded_at") or 0),
        duration_sec=float(m.get("duration_sec") or 0), language=s["language"],
        template=s.get("requested_template") or s["template"],
        segments=[{"id": int(x["id"]), "start": float(x["start"]), "end": float(x["end"]),
                   "speaker": x["speaker"], "text": x["text"]} for x in segments],
        speakers=[{"id": sp["id"], "name": sp.get("name"), "talk_sec": sp.get("talk_sec") or 0.0}
                  for sp in speakers],
        marks=jload(m.get("marks"), []) or [],
        speakers_available=bool(m.get("speakers_available")),
        language_warning=language_warning(detected) if m.get("stt_engine") == "gapi" else None,
        expected_speakers=m.get("expected_speakers"),
        source=m.get("source") or "app",
    )


def _item_key(owner_speaker: Any, owner_name: Any, task: Any) -> tuple[str, str]:
    return (str(owner_speaker or owner_name or "").lower(), str(task or ""))


def apply_primary(rt: Any, m: dict[str, Any], summary_id: str, template: str, content: dict[str, Any],
                  now: float) -> None:
    """Yangi ASOSIY xulosa: AI vazifalari almashtiriladi (odam tahrirlagani, qo'shgani
    va BELGILAGANI - bajarildi / kerak emas - QOLADI), taklif qilingan ismlar,
    avtomatik sarlavha. Xulosa shu orada asosiy bo'lmay qolgan bo'lsa (almashtirildi
    yoki o'chirildi) - hech narsa yozilmaydi."""
    t = int(now)
    with rt.store.transaction() as conn:
        row = conn.execute("SELECT primary_summary_id FROM meetings WHERE id=?", (m["id"],)).fetchone()
        if row is None or row["primary_summary_id"] != summary_id:
            return
        # CRM ga yuborilgan vazifa ham qoladi (`crm_token`): taklif/CRM dagi vazifa bilan bog'i uzilmasin
        # va o'sha vazifa yangi xulosadan qayta "ochiq" bo'lib, ikkinchi marta CRM ga ketmasin.
        conn.execute("DELETE FROM action_items WHERE meeting_id=? AND origin='ai' AND edited=0 AND status='open' "
                     "AND crm_token IS NULL", (m["id"],))
        # Odam belgilagan AI vazifalari qoladi; yangi xulosada xuddi shu vazifa
        # bo'lsa, u QAYTA "ochiq" bo'lib qo'shilmaydi.
        kept = [_item_key(r["owner_speaker"], r["owner_name"], r["task"]) for r in conn.execute(
            "SELECT owner_speaker, owner_name, task FROM action_items WHERE meeting_id=? AND origin='ai'",
            (m["id"],)).fetchall()]
        for item in content.get("actionItems") or []:
            owner, due = item.get("owner") or {}, item.get("due") or {}
            key = _item_key(owner.get("speaker"), owner.get("name"), item["task"])
            if any(k[0] == key[0] and similar(k[1], key[1]) for k in kept):
                continue
            rt.store.insert_action_item({
                "id": new_id(), "meeting_id": m["id"], "summary_item_id": item["id"], "task": item["task"],
                "owner_speaker": owner.get("speaker"), "owner_name": owner.get("name"),
                "owner_kind": owner.get("kind") or "unknown", "due_date": due.get("date"),
                "due_time": due.get("time"), "due_raw": due.get("raw"), "priority": item.get("priority"),
                "status": "done" if item.get("status") == "done_in_meeting" else "open", "origin": "ai",
                "edited": 0, "needs_confirmation": 1 if item.get("needsConfirmation") else 0,
                "source_ids": jdump(item.get("sourceSegmentIds") or []), "quote": item.get("quote"),
                "created_at": t, "updated_at": t}, conn=conn)
        for p in content.get("participants") or []:
            if p.get("suggestedName"):
                conn.execute("UPDATE speakers SET suggested_name=? WHERE meeting_id=? AND id=?",
                             (p["suggestedName"], m["id"], p["speaker"]))
        fields: dict[str, Any] = {"summary_status": "ready", "template": template,
                                  "overview": content.get("overview") or None, "updated_at": t}
        if m.get("title_source") != "user" and content.get("title"):
            fields["title"] = content["title"][:120]
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE meetings SET {sets} WHERE id=? AND primary_summary_id=?",
                     list(fields.values()) + [m["id"], summary_id])


def run_summaries(rt: Any, m: dict[str, Any], now: float, owner: str) -> None:
    """Navbatdagi xulosalar. `owner` - ijara egasi: har model chaqiruvidan keyin ijara
    yangilanadi, yangilab bo'lmasa (o'chirildi yoki boshqa ipga o'tdi) to'xtaydi."""
    store = rt.store
    queue = store.rows("SELECT * FROM summaries WHERE meeting_id=? AND status IN ('queued','running') "
                       "ORDER BY created_at, rowid", (m["id"],))
    for s in queue:
        if s.get("next_attempt_at") and int(s["next_attempt_at"]) > now:
            continue
        _run_one(rt, m, s, now, owner)
        m = store.meeting_any(m["id"])
        if m is None:
            return
    _settle(rt, m, now)


def _settle(rt: Any, m: dict[str, Any], now: float) -> None:
    """`summarizing` -> `ready`, asosiy xulosa tugagach (muvaffaqiyatli bo'lmasa ham:
    transkript o'qiladi, xulosaning holati alohida - `summaryStatus`)."""
    if m.get("status") != "summarizing":
        return
    primary = rt.store.summary(m["id"], m["primary_summary_id"]) if m.get("primary_summary_id") else None
    if primary is not None and primary["status"] in ("queued", "running"):
        if primary.get("next_attempt_at"):
            rt.store.update_meeting(m["id"], now=now, next_attempt_at=int(primary["next_attempt_at"]))
        return
    rt.store.update_meeting(m["id"], now=now, status="ready", progress=None, next_attempt_at=None,
                            error_code=None, error_stage=None,
                            summary_status=primary["status"] if primary else m.get("summary_status") or "none")


def _run_one(rt: Any, m: dict[str, Any], s: dict[str, Any], now: float, owner: str) -> None:
    store = rt.store
    primary = s["id"] == m.get("primary_summary_id")
    store.update_summary(s["id"], status="running")
    if primary:
        store.update_meeting(m["id"], now=now, summary_status="running")

    shown = [0.0]

    def progress(done: int, total: int) -> None:
        if not store.renew(m["id"], owner, time.time() + LEASE_SEC):
            raise Cancelled()
        if primary and m.get("status") == "summarizing":
            # Faqat OSHADI: zanjirda keyingi model xulosani boshidan yozganda (yoki bo'lak
            # bo'linib qadamlar ko'payganda) ilovadagi progress orqaga sakramasin.
            shown[0] = max(shown[0], round(min(99.0, 80.0 + 19.0 * done / max(1, total)), 1))
            store.update_meeting(m["id"], progress=shown[0])

    attempts = int(s.get("attempts") or 0)
    memo_key = (s["id"], int(m["transcript_rev"] or 0))
    # Shu xulosada avval yiqilgan modellar (qayta navbatdan keyin) - boshidan takrorlanmaydi.
    skip = _failures(rt, memo_key)
    failed: list[str] = []
    started = time.monotonic()
    try:
        inp = summary_input(rt, m, s)
        with bind(m["actor_id"], m.get("channel") or "mobile"):
            # Zanjir (`llm.py`): BUTUN xulosa bitta model bilan; yiqilsa - keyingisi bilan boshidan.
            # `meeting_summary` flag'i `agent` bo'lsa boshida agent bo'g'ini (`services/brain`);
            # default `local` - zanjir o'zgarmaydi.
            # Telefon qo'ng'irog'i (`source == "call"`) agentga HECH QAYSI holatda bormaydi:
            # ikkinchi tomonning ovozi va mijoz raqami - server rozilik yozuvi va huquqiy
            # qarordan keyin, alohida `call_summary` flag'i bilan (`boundary.md` 5.3, D8).
            providers = llm_mod.summary_providers(rt, m["actor_id"])
            if _brain.meeting_agent_ok(m):
                providers = _brain.meeting_summary_providers(providers, language=inp.language)
            result, used, _ = llm_mod.run_chain(
                providers,
                lambda provider, strict: _attempt(rt, m, s, provider, strict, progress, inp),
                skip=skip, failed=failed)
    except Cancelled:
        log.info("Yig'ilish %s o'chirildi - xulosa to'xtatildi", m["id"])
        return
    except LlmUnavailable:
        _forget(rt, memo_key)
        _summary_failed(rt, m, s, now, "llm_not_configured", primary)
        return
    except LlmBusy:
        _remember(rt, memo_key, failed)
        # O'z navbatimiz band (boshqa ip modelni kutyapti) - urinish hisoblanmaydi.
        retry_at = int(time.time() + LLM_BUSY_WAIT)
        store.update_summary(s["id"], status="queued", next_attempt_at=retry_at)
        store.update_meeting(m["id"], now=now, next_attempt_at=retry_at,
                             summary_status="queued" if primary else m.get("summary_status"))
        return
    except LlmRateLimited:
        _remember(rt, memo_key, failed)
        retries = int(m.get("retries") or 0) + 1
        if retries >= LLM_RATE_LIMIT_ATTEMPTS:
            log.info("Yig'ilish %s: model %d marta 429 - xulosa to'xtatildi", m["id"], retries)
            _summary_failed(rt, m, s, now, "llm_failed", primary, attempts=attempts)
            store.update_meeting(m["id"], now=now, retries=0)
            return
        wait = LLM_RATE_BACKOFF[min(retries - 1, len(LLM_RATE_BACKOFF) - 1)]
        # Kutish HOZIRDAN: uzun quvurdan keyin `now + wait` o'tmishda bo'lib qolishi mumkin.
        retry_at = int(time.time() + wait)
        store.update_summary(s["id"], status="queued", next_attempt_at=retry_at)
        store.update_meeting(m["id"], now=now, retries=retries, next_attempt_at=retry_at,
                             summary_status="queued" if primary else m.get("summary_status"))
        log.info("Yig'ilish %s: model 429 - %d s dan keyin", m["id"], wait)
        return
    except Exception as exc:                                     # noqa: BLE001
        attempts += 1
        if not isinstance(exc, LlmFailed):
            log.exception("Yig'ilish %s: xulosada kutilmagan xato", m["id"])
        else:
            log.info("Yig'ilish %s: xulosa urinishi %d yiqildi: %s", m["id"], attempts, exc)
        if attempts >= LLM_ATTEMPTS:
            _forget(rt, memo_key)
            _summary_failed(rt, m, s, now, "llm_failed" if isinstance(exc, LlmFailed) else "internal", primary,
                            attempts=attempts)
        else:
            _remember(rt, memo_key, failed)
            retry_at = int(time.time() + 60 * attempts)
            store.update_summary(s["id"], status="queued", attempts=attempts, next_attempt_at=retry_at)
            store.update_meeting(m["id"], now=now, next_attempt_at=retry_at,
                                 summary_status="queued" if primary else m.get("summary_status"))
        return
    _forget(rt, memo_key)
    if not store.renew(m["id"], owner, time.time() + LEASE_SEC):
        # Natija tayyor, lekin ijara endi bizniki emas (yoki yig'ilish o'chirildi) - yozilmaydi.
        log.info("Yig'ilish %s: xulosa natijasi yozilmadi - ijara yo'qolgan", m["id"])
        return
    finished = int(time.time())
    if result.status == "skipped":
        store.update_summary(s["id"], status="skipped", error_code=result.error_code, template=result.template,
                             finished_at=finished, next_attempt_at=None)
        if primary:
            store.update_meeting(m["id"], now=now, summary_status="skipped", retries=0)
        return
    failed = [name for name in dict.fromkeys(list(skip) + failed) if name != used.name]
    if failed and isinstance((result.content or {}).get("quality"), dict):
        # Qaysi model yiqilib, xulosa keyingisiga o'tgani ko'rinsin (faqat nomlar).
        quality = result.content["quality"]
        quality["warnings"] = [f"provider_failed:{name}" for name in failed] + list(quality.get("warnings") or [])
    store.update_summary(s["id"], status="ready", template=result.template, model=used.model[:120],
                         provider=used.name, content_json=jdump(result.content), finished_at=finished,
                         error_code=None, error=None, next_attempt_at=None)
    if primary:
        apply_primary(rt, m, s["id"], result.template, result.content, now)
        store.update_meeting(m["id"], now=now, retries=0)
    if used.name != "agent" and _brain.meeting_agent_ok(m):
        # Shadow (flag `shadow` bo'lsa, namuna bo'yicha): agent xuddi shu xulosani FONDA
        # yozadi va taqqoslanadi - foydalanuvchi faqat yuqoridagi natijani ko'radi.
        with bind(m["actor_id"], m.get("channel") or "mobile"):
            _brain.meeting_summary_shadow(inp, result.content, (time.monotonic() - started) * 1000.0)


#: Xulosada yiqilgan provayderlar xotirasi shuncha yashaydi (s): keyinroq (masalan v3
#: tuzalgach) qo'lda qayta so'ralgan xulosa yana eng yaxshi modeldan boshlaydi.
FAILURE_MEMORY_SEC = 3600


def _failures(rt: Any, key: tuple[str, int]) -> list[str]:
    with rt._lock:
        entry = rt.chain_failures.get(key)
        if entry is None:
            return []
        if time.time() - entry[0] > FAILURE_MEMORY_SEC:
            rt.chain_failures.pop(key, None)
            return []
        return list(entry[1])


def _remember(rt: Any, key: tuple[str, int], failed: list[str]) -> None:
    if not failed:
        return
    with rt._lock:
        known = list(rt.chain_failures.get(key, (0.0, []))[1])
        rt.chain_failures[key] = (time.time(), list(dict.fromkeys(known + failed)))
        # Eskilari tozalanadi - xotira o'smaydi.
        for old in [k for k, v in rt.chain_failures.items() if time.time() - v[0] > FAILURE_MEMORY_SEC]:
            rt.chain_failures.pop(old, None)


def _forget(rt: Any, key: tuple[str, int]) -> None:
    with rt._lock:
        rt.chain_failures.pop(key, None)


def _attempt(rt: Any, m: dict[str, Any], s: dict[str, Any], provider: Any, strict: bool, progress: Any,
             inp: Any) -> Any:
    """Bitta provayder bilan butun xulosa. v3 - darvoza orqali: bo'sh joy bo'lmasa `LlmBusy`
    (xulosa 30 s dan keyin qayta, pastki modelga tushmaydi)."""
    if provider.name != "v3":
        return _pipeline(rt, m, s, provider, strict, progress).run(inp)
    gate = getattr(rt, "v3_gate", None)
    if gate is not None and not gate.acquire(blocking=False):
        raise LlmBusy("v3 boshqa xulosa bilan band")
    try:
        return _pipeline(rt, m, s, provider, strict, progress).run(inp)
    finally:
        if gate is not None:
            gate.release()


def _pipeline(rt: Any, m: dict[str, Any], s: dict[str, Any], provider: Any, strict: bool,
              progress: Any) -> Pipeline:
    """Shu provayder uchun quvur. Ollama - AYNAN avvalgi sozlamalar bilan; OpenAI - katta
    bir o'tish; v3 - prompt chegarasi bo'yicha (`max_prompt_chars`) bo'laklanadi.

    Map keshi PROVAYDER bo'yicha ajratilgan: v3 yiqilib, xulosa OpenAI bilan boshidan
    yozilganda v3 ning tayyor bo'laklari olinmasin (bitta xulosa - bitta model). Ollama
    kaliti avvalgidek (shablon nomi) - mavjud kesh o'z joyida."""
    store = rt.store
    name = provider.name
    space = "" if name == "ollama" else (f"openai/{provider.model}:" if name == "openai" else f"{name}:")
    key = lambda template: (int(m["transcript_rev"] or 0), PROMPT_VERSION, space + template,  # noqa: E731
                            s["language"])
    if name == "openai":
        single, size = settings.meetings_openai_single_pass_chars, settings.meetings_openai_map_chars
    else:
        single, size = settings.meetings_single_pass_chars, settings.meetings_map_chars
    ollama = name == "ollama"
    v3 = name == "v3"
    return Pipeline(
        provider.client, single_pass_chars=single, map_chars=size,
        verify=settings.meetings_verify, num_ctx=settings.meetings_llm_num_ctx if ollama else 0,
        extract_predict=settings.meetings_extract_num_predict, map_predict=settings.meetings_map_num_predict,
        think=_think() if ollama else None,
        cache_get=lambda tpl, a, b: store.part(m["id"], key(tpl), a, b),
        cache_put=lambda tpl, a, b, part: store.put_part(m["id"], key(tpl), a, b, part),
        progress=progress, strict=strict, max_prompt_chars=provider.max_prompt_chars,
        # Byudjet faqat v3 da va faqat zanjirda (`strict`, keyingi model bor): sekin v3 xulosani
        # o'nlab daqiqa ushlab turmasin, uzun yig'ilish darhol OpenAI ning katta bir o'tishiga.
        call_budget=settings.meetings_v3_summary_max_calls if v3 else 0,
        time_budget=settings.meetings_v3_summary_budget_sec if v3 else 0.0)


def _think() -> bool | None:
    """`MEETINGS_LLM_THINK`: bo'sh - yuborilmaydi; `false`/`true` - Ollama `think`."""
    raw = str(settings.meetings_llm_think or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return None


def _summary_failed(rt: Any, m: dict[str, Any], s: dict[str, Any], now: float, code: str, primary: bool,
                    attempts: int | None = None) -> None:
    fields: dict[str, Any] = {"status": "failed", "error_code": code, "finished_at": int(now),
                              "next_attempt_at": None}
    if attempts is not None:
        fields["attempts"] = attempts
    rt.store.update_summary(s["id"], **fields)
    if primary:
        rt.store.update_meeting(m["id"], now=now, summary_status="failed", retries=0, next_attempt_at=None)


# --- o'chirish va tozalash ------------------------------------------------------------


def audio_files(rt: Any, m: dict[str, Any]) -> list[str]:
    out = []
    if m.get("audio_path"):
        out.append(m["audio_path"])
        if str(m["audio_path"]).endswith(".aac"):
            out.append(str(m["audio_path"])[:-4] + ".m4a")
    return out


def delete_meeting(rt: Any, m: dict[str, Any]) -> None:
    """Qatorlar (kaskad), audio, yuklash bo'lagi va tinglash nusxasi - hammasi."""
    rt.store.delete_meeting_rows(m["id"])
    for path in audio_files(rt, m) + [str(rt.store.upload_path(m["id"]))]:
        store_mod.remove_file(path)


def drop_audio(rt: Any, m: dict[str, Any], now: float) -> None:
    for path in audio_files(rt, m):
        store_mod.remove_file(path)
    rt.store.update_meeting(m["id"], now=now, audio_deleted_at=int(now))


def purge(rt: Any, now: float) -> dict[str, int]:
    """Saqlash muddatlari (4.3). Faqat id va son jurnalga yoziladi."""
    store = rt.store
    counts = {"audio": 0, "meetings": 0, "uploads": 0, "tooLong": 0, "devices": 0}
    busy = ", ".join(f"'{x}'" for x in IN_PROGRESS)
    # Muddat yozilgan paytdan, lekin serverga kelgandan ko'pi bilan 7 kun oldindan
    # hisoblanadi: telefon soati noto'g'ri yoki yozuv oflayn navbatda uzoq turgan
    # bo'lsa ham audio yuklangan zahoti o'chib ketmasin. Ishlanayotgani tegilmaydi.
    audio_cutoff = now - settings.meetings_audio_days * 86400
    for m in store.rows("SELECT * FROM meetings WHERE audio_path IS NOT NULL AND audio_deleted_at IS NULL "
                        f"AND status NOT IN ({busy}) AND MAX(COALESCE(recorded_at, created_at), "
                        "created_at - 7 * 86400) < ?", (int(audio_cutoff),)):
        drop_audio(rt, m, now)
        counts["audio"] += 1
    for m in store.rows("SELECT * FROM meetings WHERE status='failed' AND error_code='too_long' "
                        "AND audio_path IS NOT NULL AND audio_deleted_at IS NULL AND COALESCE(completed_at, "
                        "updated_at) < ?", (int(now - 86400),)):
        drop_audio(rt, m, now)
        counts["tooLong"] += 1
    if settings.meetings_retention_days > 0:
        cutoff = now - settings.meetings_retention_days * 86400
        for m in store.rows(f"SELECT * FROM meetings WHERE status NOT IN ({busy}) AND "
                            "MAX(COALESCE(recorded_at, created_at), created_at - 30 * 86400) < ?", (int(cutoff),)):
            delete_meeting(rt, m)
            counts["meetings"] += 1
    ttl = now - settings.meetings_upload_ttl_hours * 3600
    for m in store.rows("SELECT * FROM meetings WHERE status='uploading' AND updated_at < ?", (int(ttl),)):
        delete_meeting(rt, m)
        counts["uploads"] += 1
    if getattr(rt, "devices", None) is not None:
        with contextlib.suppress(Exception):
            counts["devices"] = rt.devices.purge(now)
    if any(counts.values()):
        log.info("Yig'ilishlar tozalandi: %s", counts)
    return counts


# --- ishchi ---------------------------------------------------------------------------


class Worker:
    def __init__(self, rt: Any, *, threads: int = 2, tick: float = 2.0) -> None:
        self.rt = rt
        self.threads = max(1, int(threads))
        self.tick = tick
        self.owner_base = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        #: Sinxron `run_once` (testlar, jonli tekshiruv) egasi; fon iplari - `<base>-<ip>`.
        self.owner = f"{self.owner_base}-sync"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock_fd: int | None = None
        self._lock_guard = threading.Lock()
        #: Shu jarayonda HOZIR ishlanayotgan yig'ilishlar: id -> ijara egasi.
        self._inflight: dict[str, str] = {}
        self._inflight_lock = threading.Lock()
        self._last_purge = 0.0
        self.last_tick: float | None = None
        self.last_error: str | None = None
        self.transcriber = Transcriber(rt)

    # --- ijara ---

    def claim(self, owner: str, now: float) -> dict[str, Any] | None:
        """Navbatdan bittasi - shu jarayonda ishlanayotganlardan TASHQARI (atomik)."""
        with self._inflight_lock:
            m = self.rt.store.claim(owner, now, LEASE_SEC, exclude=tuple(self._inflight))
            if m is not None:
                self._inflight[m["id"]] = owner
        return m

    def heartbeat_once(self, now: float | None = None) -> int:
        """Ishlanayotgan yig'ilishlar ijarasini uzaytiradi. Uzaytirilganlar soni."""
        moment = time.time() if now is None else now
        with self._inflight_lock:
            items = list(self._inflight.items())
        renewed = 0
        for meeting_id, owner in items:
            with contextlib.suppress(Exception):
                renewed += 1 if self.rt.store.renew(meeting_id, owner, moment + LEASE_SEC) else 0
        return renewed

    # --- bitta qadam (testlar shuni to'g'ridan-to'g'ri chaqiradi) ---

    def process(self, m: dict[str, Any], now: float, owner: str | None = None) -> None:
        owner = owner or self.owner
        with self._inflight_lock:
            self._inflight[m["id"]] = owner
        try:
            status = m.get("status")
            if status in ("uploaded", "waiting_quota", "transcribing"):
                self.transcriber.step(m, now, owner)
            elif status in ("summarizing", "ready"):
                run_summaries(self.rt, m, now, owner)
        except LeaseLost:
            log.info("Yig'ilish %s: ijara yo'qolgan - qadam yozilmadi", m.get("id"))
        except Exception as exc:                                 # noqa: BLE001
            self.last_error = f"{type(exc).__name__}"
            log.exception("Yig'ilish %s: ishchi qadamida xato", m.get("id"))
            current = self.rt.store.meeting_any(m["id"])
            if current is not None and current.get("status") in ("uploaded", "transcribing", "waiting_quota"):
                self.transcriber.backoff(current, now)
            elif current is not None and current.get("status") in ("summarizing", "ready"):
                # Xulosa bosqichidan tashqaridagi xato (masalan ma'lumotni o'qishda) -
                # darhol qayta olinib, jurnalni to'ldirmasin.
                with contextlib.suppress(Exception):
                    self.rt.store.update_meeting(m["id"], now=now, next_attempt_at=int(time.time() + ERROR_WAIT))
        finally:
            with contextlib.suppress(Exception):
                self.rt.store.release(m["id"], owner)
            with self._inflight_lock:
                if self._inflight.get(m["id"]) == owner:
                    del self._inflight[m["id"]]

    def run_once(self, now: float | None = None, *, limit: int = 50) -> int:
        """Hozir navbatda turgan hamma qadamlarni bajaradi (sinxron). Qadamlar soni."""
        done = 0
        while done < limit:
            moment = now if now is not None else time.time()
            m = self.claim(self.owner, moment)
            if m is None:
                break
            self.process(m, moment, self.owner)
            done += 1
        return done

    # --- fon ---

    def _active(self) -> bool:
        from ...core import config

        return config.meetings_enabled_now() or self.rt.store.exists

    def _hold_lock(self) -> bool:
        """`worker.lock` - bitta jarayon. Ombor papkasi bo'lmasa yaratilmaydi."""
        with self._lock_guard:
            if self._lock_fd is not None:
                return True
            try:
                import fcntl

                self.rt.store.prepare()
                fd = os.open(self.rt.store.lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    os.close(fd)
                    return False
                self._lock_fd = fd
                return True
            except Exception:                                     # noqa: BLE001
                log.exception("Yig'ilish ishchisi qulfi olinmadi")
                return False

    def _loop(self, index: int) -> None:
        from ...core import config

        owner = f"{self.owner_base}-{index}"
        while not self._stop.is_set():
            try:
                if not self._active() or not self._hold_lock():
                    self._stop.wait(10.0)
                    continue
                self.last_tick = time.time()
                if index == 0 and time.time() - self._last_purge >= PURGE_EVERY:
                    self._last_purge = time.time()
                    purge(self.rt, time.time())
                if config.meetings_enabled_now():
                    m = self.claim(owner, time.time())
                    if m is not None:
                        self.process(m, time.time(), owner)
                        continue
                self._stop.wait(self.tick)
            except Exception as exc:                              # noqa: BLE001
                self.last_error = f"{type(exc).__name__}"
                log.exception("Yig'ilish ishchisi: kutilmagan xato")
                self._stop.wait(5.0)

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_EVERY):
            try:
                self.heartbeat_once()
            except Exception:                                     # noqa: BLE001
                log.exception("Yig'ilish ishchisi: ijarani uzaytirib bo'lmadi")

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for index in range(self.threads):
            thread = threading.Thread(target=self._loop, args=(index,), name=f"meetings-worker-{index}",
                                      daemon=True)
            thread.start()
            self._threads.append(thread)
        beat = threading.Thread(target=self._heartbeat, name="meetings-lease", daemon=True)
        beat.start()
        self._threads.append(beat)
        log.info("Yig'ilish ishchisi ishga tushdi (%d ip)", self.threads)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout)
        self._threads = []
        with self._lock_guard:
            if self._lock_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self._lock_fd)
                self._lock_fd = None

    def status(self) -> dict[str, Any]:
        return {"alive": any(t.is_alive() for t in self._threads), "threads": self.threads,
                "lockHeld": self._lock_fd is not None, "lastTickAt": self.last_tick, "lastError": self.last_error}

"""Yig'ilishlar bo'limi - endpointlar MANTIG'I (router'da mantiq yo'q, `main.py` qoidasi).

Har funksiya `actor_id` oladi va boshqa odamning yig'ilishini "yo'q" deb
ko'radi (404). Javoblar spetsifikatsiyaning 3.1 bo'limidagi shaklda
(camelCase) - mobil `src/api/types.ts` AYNAN shu shaklni kutadi.

JURNALGA MATN YOZILMAYDI: transkript, xulosa, savol, yuklangan baytlar va
ularning xeshi - hech qachon. Faqat id, hajm, davomiylik va xato kodi.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...core.config import settings
from ...schemas.auth import AuthUser
from ..integrations.gapi_stt import MAX_MEETING_SPEAKERS
from ..reports import RateLimiter
from ..stt import SttError
from . import ask as ask_mod
from . import audio, compact, crm, dates, export, prompts, runtime, templates
from . import chat as chat_mod
from . import llm as llm_mod
from .errors import RETRYABLE, MeetingProblem, message_for, not_found
from .store import jdump, jload, new_id, private_file, transcript_ready
from .summarize import LlmBusy, LlmFailed, LlmRateLimited, LlmUnavailable
from .transcribe import language_warning
from .worker import delete_meeting

log = logging.getLogger(__name__)

LANGS = ("uz", "ru", "en")
#: mp3 va wav - 2026-10-22 (ega: kompyuterdagi tayyor yozuvlar). Taxalluslar (`audio/mp3`, `audio/x-wav`,
#: `audio/x-m4a`) `audio.canonical_type` bilan shularga keltiriladi.
#: `audio/ogg` (2026-11-04) - Telegram ovozli xabari (Opus); GAPI uni to'g'ridan-to'g'ri oladi.
ACCEPTED_TYPES = ("audio/aac", "audio/mp4", "audio/mpeg", "audio/wav", "audio/ogg")
MIN_SECONDS = 10
MAX_MARKS = 200
#: `recordedAt` kelajakda bo'lolmaydi (telefon soati / qasddan): saqlash muddatini
#: aylanib o'tmasin. Shundan ko'p oldinda bo'lsa - server vaqti olinadi.
FUTURE_SKEW_SEC = 300


# --- umumiy yordamchilar ----------------------------------------------------------------


def iso(epoch: Any) -> str | None:
    if epoch in (None, ""):
        return None
    return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise MeetingProblem(400, "invalid_time", "Vaqt ISO-8601 shaklida bo'lishi kerak") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def max_upload_bytes() -> int:
    return int(settings.meetings_max_upload_mb) * 1024 * 1024


def _owned(actor_id: int, meeting_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", str(meeting_id or "")):
        raise not_found()
    m = runtime().store.meeting(actor_id, meeting_id)
    if m is None:
        raise not_found()
    return m


_limiters: dict[tuple[str, int], RateLimiter] = {}
_limiters_lock = threading.Lock()


def _rate(name: str, actor_id: int, limit: int, window: float = 3600.0) -> None:
    """Soatlik chegara: oshsa 429 `rate_limited` + `Retry-After`."""
    with _limiters_lock:
        limiter = _limiters.setdefault((name, int(limit)), RateLimiter(limit=max(1, int(limit)), window=window))
    wait = limiter.take(int(actor_id))
    if wait is not None:
        raise MeetingProblem(429, "rate_limited", "So'rovlar ko'p - birozdan keyin qayta urinib ko'ring",
                             headers={"Retry-After": str(wait)})


def reset_limits() -> None:
    with _limiters_lock:
        _limiters.clear()


_upload_locks: dict[str, threading.Lock] = {}
_upload_guard = threading.Lock()


def _upload_lock(meeting_id: str) -> threading.Lock:
    with _upload_guard:
        if len(_upload_locks) > 1000:
            for key in [k for k, v in _upload_locks.items() if not v.locked()]:
                del _upload_locks[key]
        return _upload_locks.setdefault(meeting_id, threading.Lock())


def default_title(recorded_at: float, lang: str) -> str:
    word = {"uz": "Yig'ilish", "ru": "Встреча", "en": "Meeting"}.get(lang, "Yig'ilish")
    return f"{word} {dates.format_day_time(recorded_at, lang)}"


def accept_language(header: str | None) -> str:
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in LANGS:
            return tag
    return "uz"


# --- ko'rinishlar (3.1) --------------------------------------------------------------------


def speaker_view(sp: dict[str, Any]) -> dict[str, Any]:
    return {"id": sp["id"], "name": sp.get("name"), "suggestedName": sp.get("suggested_name"),
            "talkSec": round(float(sp.get("talk_sec") or 0), 2), "mergedInto": sp.get("merged_into")}


def segment_view(seg: dict[str, Any]) -> dict[str, Any]:
    return {"id": int(seg["id"]), "speaker": seg.get("speaker"), "start": round(float(seg["start"]), 2),
            "end": round(float(seg["end"]), 2), "text": seg["text"], "edited": bool(seg.get("edited"))}


def error_view(m: dict[str, Any], now: float) -> dict[str, Any] | None:
    code = m.get("error_code")
    if not code:
        return None
    retry_at = None
    if m.get("next_attempt_at") and (m.get("status") == "waiting_quota" or code in RETRYABLE):
        if float(m["next_attempt_at"]) > now:
            retry_at = iso(m["next_attempt_at"])
    return {"code": code, "message": message_for(code), "stage": m.get("error_stage") or "transcribe",
            "retryable": code in RETRYABLE, "retryAt": retry_at}


def _progress(m: dict[str, Any]) -> float | None:
    if m.get("status") not in ("uploaded", "transcribing", "summarizing"):
        return None
    return round(float(m.get("progress") or 0.0), 1)


def _poll_after(m: dict[str, Any], now: float) -> int | None:
    """Ilova qachon yana so'rasin. Kutish (`next_attempt_at`, masalan model 429 dan
    keyin 5-15 daqiqa) bo'lsa - shungacha (10 daqiqadan ko'p emas): har 5 s da bekor so'rov yo'q."""
    status = m.get("status")
    if status in ("uploaded", "transcribing"):
        since = float(m.get("completed_at") or m.get("updated_at") or now)
        base = 3 if now - since < 60 else 10
    elif status == "summarizing":
        base = 5
    elif status == "waiting_quota":
        return 600
    else:
        return None
    pending = float(m.get("next_attempt_at") or 0) - now
    return int(min(600, max(base, pending))) if pending > base else base


def meeting_view(m: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    store = runtime().store
    detected = jload(m.get("detected_lang"))
    speakers = [speaker_view(sp) for sp in store.speakers(m["id"])]
    count = store.segment_count(m["id"])
    engine = m.get("stt_engine") if int(m.get("transcript_rev") or 0) > 0 else None
    # Qayta o'girish paytida eski transkript o'chirilgan - "bor" deyilmaydi.
    available = bool(engine) and m.get("status") in ("summarizing", "ready")
    return {
        "id": m["id"], "clientId": m["client_id"], "title": m.get("title") or "",
        "titleSource": m.get("title_source") or "auto", "status": m["status"], "progress": _progress(m),
        "pollAfterSec": _poll_after(m, now), "language": m.get("language") or "uz",
        "detectedLanguage": detected,
        "languageWarning": language_warning(detected) if m.get("stt_engine") == "gapi" else None,
        "template": m.get("template") or "auto", "expectedSpeakers": m.get("expected_speakers"),
        "source": m.get("source") or "app", "recordedAt": iso(m.get("recorded_at")),
        "durationSec": round(float(m["duration_sec"]), 2) if m.get("duration_sec") is not None else None,
        "createdAt": iso(m.get("created_at")), "updatedAt": iso(m.get("updated_at")),
        "upload": {"receivedBytes": int(m.get("received_bytes") or 0), "totalBytes": m.get("total_bytes"),
                   "maxChunkBytes": int(settings.meetings_chunk_bytes), "complete": bool(m.get("completed_at"))},
        "transcript": {"available": available, "engine": engine,
                       "speakersAvailable": bool(m.get("speakers_available")) if engine else False,
                       "timing": m.get("timing") if engine else None, "segmentCount": count,
                       "transcriptRev": int(m.get("transcript_rev") or 0)},
        "speakers": speakers,
        "summaryStatus": m.get("summary_status") or "none",
        "primarySummaryId": m.get("primary_summary_id"),
        "openActionItems": store.open_items(m["id"]),
        "audioAvailable": bool(m.get("audio_path") and not m.get("audio_deleted_at")),
        "error": error_view(m, now),
    }


def card_view(m: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    overview = m.get("overview")
    if overview and len(overview) > 200:
        overview = overview[:199] + "…"
    return {
        "id": m["id"], "clientId": m["client_id"], "title": m.get("title") or "", "status": m["status"],
        "progress": _progress(m), "recordedAt": iso(m.get("recorded_at")),
        "durationSec": round(float(m["duration_sec"]), 2) if m.get("duration_sec") is not None else None,
        "language": m.get("language") or "uz", "template": m.get("template") or "auto",
        "summaryStatus": m.get("summary_status") or "none",
        "openActionItems": runtime().store.open_items(m["id"]), "overview": overview,
        "error": error_view(m, now), "source": m.get("source") or "app",
        # 2026-11-11, Plaud filtri va saralash: qatorni `store.list_meetings` beradi (`ORIGIN_SQL`, `LISTED_SQL`).
        "origin": m.get("effective_origin") or m.get("origin") or "api",
        "listedAt": iso(m.get("listed_at") or m.get("recorded_at")),
    }


# --- 1. config ------------------------------------------------------------------------------


def config(user: AuthUser, lang: str) -> dict[str, Any]:
    store = runtime().store
    used = store.used_sec(dates.day_key(time.time()), user.actorId) / 60.0 if store.exists else 0.0
    return {
        "enabled": True, "maxMinutes": int(settings.meetings_max_minutes),
        "maxUploadBytes": max_upload_bytes(), "maxChunkBytes": int(settings.meetings_chunk_bytes),
        "acceptedContentTypes": list(ACCEPTED_TYPES), "languages": list(LANGS), "defaultLanguage": "uz",
        "maxDistinctSpeakers": MAX_MEETING_SPEAKERS,
        "userDailyMinutes": int(settings.meetings_user_daily_minutes), "userTodayMinutes": round(used, 1),
        "recording": {"format": "aac_adts", "sampleRate": 16000, "bitRate": 48000, "channels": 1,
                      "audioSource": settings.meetings_audio_source or "voice_recognition"},
        "templates": templates.catalog(lang),
    }


# --- 2-5. yaratish va yuklash ------------------------------------------------------------------


def create(user: AuthUser, body: Any, channel: str, now: float | None = None, *,
           origin: str | None = None) -> tuple[dict[str, Any], bool]:
    """`origin` - faqat server o'zi yaratgan yozuv (Slack, Telegram bot): qolganiniki `store.ORIGIN_SQL` da."""
    now = time.time() if now is None else now
    store = runtime().store
    client_id = str(body.clientId).lower()
    existing = store.by_client(user.actorId, client_id)
    if existing is not None:
        return meeting_view(existing, now), False
    content_type = audio.canonical_type(body.contentType)
    if content_type not in ACCEPTED_TYPES:
        raise MeetingProblem(415, "unsupported_format")
    _rate("create", user.actorId, 30)
    recorded = min(parse_time(body.recordedAt) or int(now), int(now) + FUTURE_SKEW_SEC)
    meeting_id = new_id()
    title = (body.title or "").strip()
    fields = {
        "id": meeting_id, "actor_id": int(user.actorId), "client_id": client_id,
        "title": title or default_title(recorded, body.language),
        "title_source": "user" if title else "auto", "language": body.language, "template": body.template,
        "expected_speakers": body.expectedSpeakers, "source": body.source, "channel": channel,
        "app_version": (body.appVersion or "")[:40] or None, "device": (body.device or "")[:80] or None,
        "recorded_at": recorded, "content_type": content_type, "status": "uploading",
        "summary_status": "none", "created_at": int(now), "updated_at": int(now)}
    if origin:
        fields["origin"] = origin
    consent_at = parse_time(getattr(body, "consentAt", None)) if body.source == "call" else None
    if consent_at:
        # Kelajakdagi vaqt (telefon soati) - hozirgiga tushiriladi; versiya - qisqa belgi.
        fields["consent_at"] = min(consent_at, int(now))
        fields["consent_version"] = (getattr(body, "consentVersion", None) or "")[:32] or None
    try:
        store.insert_meeting(fields)
    except sqlite3.IntegrityError:
        # Bir xil `clientId` bilan parallel so'rov (ilova qayta urindi) - o'sha yig'ilish.
        existing = store.by_client(user.actorId, client_id)
        if existing is None:
            raise
        return meeting_view(existing, now), False
    log.info("Yig'ilish yaratildi: %s (actor %s, %s)", meeting_id, user.actorId, body.language)
    return meeting_view(store.meeting(user.actorId, meeting_id), now), True


def upload_state(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    m = _owned(user.actorId, meeting_id)
    return {"receivedBytes": int(m.get("received_bytes") or 0), "maxChunkBytes": int(settings.meetings_chunk_bytes),
            "complete": bool(m.get("completed_at"))}


def _hash_range(path: Path, offset: int, length: int) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        fh.seek(offset)
        remaining = length
        while remaining > 0:
            block = fh.read(min(remaining, 1024 * 1024))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def append_chunk(user: AuthUser, meeting_id: str, offset: int, data: bytes, chunk_sha: str | None,
                 now: float | None = None) -> dict[str, Any]:
    """Bitta bo'lak. Diskka `fsync` bilan - telefon "yuborildi" deb o'chirgan bayt yo'qolmasin."""
    now = time.time() if now is None else now
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    if not data:
        raise MeetingProblem(400, "empty_chunk", "Bo'lak bo'sh")
    if len(data) > int(settings.meetings_chunk_bytes):
        raise MeetingProblem(413, "chunk_too_large", "Bo'lak juda katta")
    digest = hashlib.sha256(data).hexdigest()
    if chunk_sha and chunk_sha.strip().lower() != digest:
        raise MeetingProblem(400, "sha_mismatch", "Bo'lak buzilgan - qayta yuboring")
    with _upload_lock(m["id"]):
        m = store.meeting(user.actorId, meeting_id) or m
        received = int(m.get("received_bytes") or 0)
        if m["status"] != "uploading":
            raise MeetingProblem(409, "upload_closed", "Yuklash yopilgan", receivedBytes=received)
        path = store.upload_path(m["id"])
        if offset == received:
            if offset + len(data) > max_upload_bytes():
                raise MeetingProblem(413, "upload_too_large", message_for("too_large"))
            if offset == 0 and not audio.sniff(data, m.get("content_type") or ""):
                raise MeetingProblem(415, "unsupported_format")
            store.prepare()
            private_file(path)
            with open(path, "r+b") as fh:
                # Avvalgi yarim yozuv (yiqilish) - qabul qilinmagan baytlar kesiladi.
                fh.truncate(received)
                fh.seek(received)
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            received += len(data)
            store.update_meeting(m["id"], now=now, received_bytes=received)
            return {"receivedBytes": received}
        if 0 <= offset and offset + len(data) <= received and path.exists() \
                and _hash_range(path, offset, len(data)) == digest:
            # Takroriy urinish (javob telefonga yetmagan) - allaqachon saqlangan.
            return {"receivedBytes": received}
        raise MeetingProblem(409, "offset_mismatch", "Yuklash joyi mos emas", receivedBytes=received)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _marks(raw: list[Any], duration: float) -> list[dict[str, Any]]:
    out = []
    for mark in raw[:MAX_MARKS]:
        t = max(0.0, min(float(mark.t), duration or float(mark.t)))
        note = (mark.note or "").strip()[:200] or None
        out.append({"t": round(t, 2), "note": note})
    return sorted(out, key=lambda x: x["t"])


def complete(user: AuthUser, meeting_id: str, body: Any, now: float | None = None) -> tuple[dict[str, Any], int]:
    now = time.time() if now is None else now
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    sha = body.sha256.lower()
    if m["status"] != "uploading":
        if m.get("completed_at") and m.get("audio_sha256") == sha:
            return meeting_view(m, now), 200
        raise MeetingProblem(409, "upload_closed", "Yuklash yopilgan",
                             receivedBytes=int(m.get("received_bytes") or 0))
    with _upload_lock(m["id"]):
        m = store.meeting(user.actorId, meeting_id) or m
        received = int(m.get("received_bytes") or 0)
        if m["status"] != "uploading":
            # Parallel `/complete` (ilova javobni kutmay qayta yubordi) qulf ostida yakunlab bo'ldi.
            if m.get("completed_at") and m.get("audio_sha256") == sha:
                return meeting_view(m, now), 200
            raise MeetingProblem(409, "upload_closed", "Yuklash yopilgan", receivedBytes=received)
        if int(body.totalBytes) != received:
            raise MeetingProblem(409, "upload_incomplete", receivedBytes=received)
        path = store.upload_path(m["id"])
        if received == 0 or not path.exists():
            raise MeetingProblem(409, "upload_incomplete", receivedBytes=0)
        if _file_sha(path) != sha:
            with open(path, "r+b") as fh:
                fh.truncate(0)
            store.update_meeting(m["id"], now=now, received_bytes=0)
            raise MeetingProblem(409, "sha_mismatch", receivedBytes=0)
        content_type = m.get("content_type") or "audio/aac"
        duration = audio.measure(path, content_type)
        if not duration:
            store.update_meeting(m["id"], now=now, status="failed", error_code="unsupported_format",
                                 error_stage="upload")
            with contextlib.suppress(OSError):
                path.unlink()
            raise MeetingProblem(415, "unsupported_format")
        suffix = audio.EXTENSIONS.get(content_type, ".aac")
        target = store.audio_dir(user.actorId) / f"{m['id']}{suffix}"
        os.replace(path, target)
        with contextlib.suppress(OSError):
            os.chmod(target, 0o600)
        fields: dict[str, Any] = {
            "audio_path": str(target), "audio_sha256": sha, "total_bytes": received,
            "duration_sec": round(float(duration), 2), "ended_at": parse_time(body.endedAt),
            "marks": jdump(_marks(body.marks or [], float(duration))), "completed_at": int(now),
            "progress": 0.0, "error_code": None, "error_stage": None, "next_attempt_at": None}
        if duration > settings.meetings_max_minutes * 60 + 30:
            fields.update(status="failed", error_code="too_long", error_stage="upload")
            store.update_meeting(m["id"], now=now, **fields)
            log.info("Yig'ilish %s: juda uzun (%.0f s)", m["id"], duration)
            raise MeetingProblem(413, "too_long")
        status = "uploaded"
        if (m.get("language") or "uz") == "uz":
            minutes = math.ceil(duration / 60.0)
            used = store.used_sec(dates.day_key(now), user.actorId) / 60.0
            if used + minutes > settings.meetings_user_daily_minutes:
                # Faqat TUGAGAN daqiqalar: yo'ldagilarni ishchi kvota qulfi ostida hisoblaydi.
                # Yozuv RAD ETILMAYDI - ertaga o'giriladi.
                status = "waiting_quota"
                fields.update(error_code="quota_user", error_stage="quota",
                              next_attempt_at=int(dates.next_reset(now)), progress=None)
        fields["status"] = status
        store.update_meeting(m["id"], now=now, **fields)
        log.info("Yig'ilish %s yuklandi: %d bayt, %.1f s, %s", m["id"], received, duration, status)
    return meeting_view(store.meeting(user.actorId, meeting_id), now), 202


# --- 6-11. ro'yxat, ko'rish, o'zgartirish ---------------------------------------------------------


def list_meetings(user: AuthUser, *, limit: int, offset: int, q: str, status: str, origin: str = "",
                  sort: str = "recorded") -> dict[str, Any]:
    store = runtime().store
    if not store.exists:
        return {"items": [], "limit": limit, "offset": offset, "total": 0}
    rows, total = store.list_meetings(user.actorId, limit=limit, offset=offset, q=q, status=status,
                                      origin=origin, sort=sort)
    now = time.time()
    return {"items": [card_view(m, now) for m in rows], "limit": limit, "offset": offset, "total": total}


def detail(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    return meeting_view(_owned(user.actorId, meeting_id))


def patch(user: AuthUser, meeting_id: str, body: Any) -> dict[str, Any]:
    m = _owned(user.actorId, meeting_id)
    fields: dict[str, Any] = {}
    given = body.model_fields_set
    if "title" in given and body.title is not None:
        fields.update(title=body.title.strip()[:120], title_source="user")
    if "template" in given and body.template is not None:
        fields["template"] = body.template
    if "expectedSpeakers" in given:
        fields["expected_speakers"] = body.expectedSpeakers
    if fields:
        runtime().store.update_meeting(m["id"], actor_id=user.actorId, **fields)
    return detail(user, meeting_id)


def delete(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    rt = runtime()
    m = _owned(user.actorId, meeting_id)
    if m.get("stt_job_id") and m.get("status") == "transcribing" and getattr(rt.gapi, "configured", False):
        # Eng yaxshi urinish: GAPI vazifani faqat yashiradi (30 kun saqlaydi).
        with contextlib.suppress(SttError, Exception):
            rt.gapi.cancel_job(m["stt_job_id"], account=int(m.get("stt_account") or 1))
    delete_meeting(rt, m)
    log.info("Yig'ilish o'chirildi: %s", m["id"])
    return {"id": m["id"], "status": "deleted"}


def retry(user: AuthUser, meeting_id: str, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    status, code = m["status"], m.get("error_code")
    if status in ("uploaded", "transcribing", "summarizing"):
        return meeting_view(m, now)
    if status == "waiting_quota":
        store.update_meeting(m["id"], now=now, next_attempt_at=None)
        return meeting_view(store.meeting(user.actorId, meeting_id), now)
    if status == "failed" and code in RETRYABLE:
        fields: dict[str, Any] = {"status": "uploaded", "error_code": None, "error_stage": None,
                                  "next_attempt_at": None, "retries": 0, "progress": 0.0}
        if code == "stt_job_lost":
            # Vazifa yo'q - QAYTA yuboriladi (va qayta to'lanadi).
            fields.update(stt_job_id=None, stt_result_url=None, stt_submitted_at=None, attempts=0)
        elif code == "stt_timeout":
            fields["stt_deadline_at"] = int(now + settings.meetings_stt_deadline)
        elif code == "internal" and not m.get("stt_job_id"):
            fields.update(stt_submitted_at=None, attempts=0)
        if int(m.get("transcript_rev") or 0) > 0 and store.segment_count(m["id"]) and m.get("stt_engine"):
            # Transkript bor - faqat xulosa qayta.
            fields["status"] = "ready"
        store.update_meeting(m["id"], now=now, **fields)
        m = store.meeting(user.actorId, meeting_id)
        if m["status"] == "ready":
            _requeue_primary(m, now)
        return meeting_view(store.meeting(user.actorId, meeting_id), now)
    if status == "ready" and m.get("summary_status") == "failed":
        primary = store.summary(m["id"], m["primary_summary_id"]) if m.get("primary_summary_id") else None
        if primary and primary.get("error_code") in RETRYABLE:
            _requeue_primary(m, now)
            return meeting_view(store.meeting(user.actorId, meeting_id), now)
    raise MeetingProblem(409, "not_retryable", "Bu holatda qayta urinib bo'lmaydi")


def _requeue_primary(m: dict[str, Any], now: float) -> None:
    store = runtime().store
    sid = m.get("primary_summary_id")
    if sid and store.summary(m["id"], sid):
        store.update_summary(sid, status="queued", attempts=0, next_attempt_at=None, error_code=None, error=None)
        store.update_meeting(m["id"], now=now, status="summarizing", summary_status="queued", progress=80.0,
                             next_attempt_at=None)
    else:
        m = store.meeting_any(m["id"])
        runtime().schedule_primary(m, now)


def retranscribe(user: AuthUser, meeting_id: str, body: Any, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    if not body.confirmCharge:
        raise MeetingProblem(400, "confirm_required", "Qayta o'girish qayta to'lanadi - tasdiqlang")
    if m["status"] not in ("ready", "failed"):
        raise MeetingProblem(409, "not_ready", "Yig'ilish hali ishlanmoqda")
    if not m.get("audio_path") or m.get("audio_deleted_at") or not Path(m["audio_path"]).exists():
        raise MeetingProblem(410, "audio_expired", "Audio saqlash muddati tugagan")
    if float(m.get("duration_sec") or 0) > settings.meetings_max_minutes * 60 + 30:
        raise MeetingProblem(413, "too_long")
    with store.transaction() as conn:
        conn.execute("DELETE FROM summaries WHERE meeting_id=?", (m["id"],))
        conn.execute("DELETE FROM summary_parts WHERE meeting_id=?", (m["id"],))
        # Odam tahrirlagan, qo'shgan, belgilagan (bajarildi / kerak emas) yoki CRM ga yuborgan vazifalar qoladi.
        conn.execute("DELETE FROM action_items WHERE meeting_id=? AND origin='ai' AND edited=0 AND status='open' "
                     "AND crm_token IS NULL", (m["id"],))
        conn.execute("UPDATE action_items SET source_ids='[]' WHERE meeting_id=?", (m["id"],))
        # Chat: eski matn bo'yicha javoblar (manba id lari yangi matnda boshqa qatorni ko'rsatadi) xotiraga ham,
        # ro'yxatga ham bormasin - HAMMA so'rovchining faol navbatlari arxivga (yumshoq, qatorlar qoladi).
        conn.execute("UPDATE questions SET archived_at=? WHERE meeting_id=? AND archived_at IS NULL",
                     (int(now), m["id"]))
        conn.execute("DELETE FROM segments WHERE meeting_id=?", (m["id"],))
        conn.execute("DELETE FROM speakers WHERE meeting_id=?", (m["id"],))
        conn.execute(
            "UPDATE meetings SET status='uploaded', language=?, expected_speakers=?, stt_engine=NULL, "
            "stt_job_id=NULL, stt_result_url=NULL, stt_submitted_at=NULL, stt_deadline_at=NULL, attempts=0, "
            "retries=0, error_code=NULL, error_stage=NULL, next_attempt_at=NULL, progress=0, "
            "primary_summary_id=NULL, summary_status='none', detected_lang=NULL, speakers_available=0, "
            "timing=NULL, overview=NULL, completed_at=?, updated_at=? WHERE id=?",
            (body.language, body.expectedSpeakers if "expectedSpeakers" in body.model_fields_set
             else m.get("expected_speakers"), int(now), int(now), m["id"]))
    log.info("Yig'ilish %s qayta o'girishga (%s)", m["id"], body.language)
    return meeting_view(store.meeting(user.actorId, meeting_id), now)


# --- 12-15. transkript va spikerlar ------------------------------------------------------------------


def _transcript_ready(m: dict[str, Any]) -> bool:
    """Qoida bitta joyda - `store.transcript_ready` (chat navbatini saqlash tranzaksiyasi ham shundan)."""
    return transcript_ready(m)


def _require_transcript(m: dict[str, Any]) -> None:
    if not _transcript_ready(m):
        raise MeetingProblem(409, "not_ready", "Transkript hali tayyor emas")


def transcript(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    _require_transcript(m)
    return {
        "meetingId": m["id"], "transcriptRev": int(m["transcript_rev"]), "engine": m.get("stt_engine"),
        "speakersAvailable": bool(m.get("speakers_available")), "timing": m.get("timing"),
        "language": m.get("language"), "detectedLanguage": jload(m.get("detected_lang")),
        "speakers": [speaker_view(sp) for sp in store.speakers(m["id"])],
        "segments": [segment_view(s) for s in store.segments(m["id"])],
    }


def rename_speaker(user: AuthUser, meeting_id: str, speaker_id: str, name: str | None) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    # Boshqaruv belgilari (`\x01`, U+FFFF ...) ismda kerak emas va DOCX eksportini buzardi.
    clean = " ".join(export.clean(name).split()) or None
    if clean is not None and len(clean) > 60:
        raise MeetingProblem(400, "invalid_name", "Ism 60 belgidan oshmasin")
    if store.execute("UPDATE speakers SET name=? WHERE meeting_id=? AND id=?",
                     (clean, m["id"], speaker_id)).rowcount != 1:
        raise MeetingProblem(404, "speaker_not_found", "Spiker topilmadi")
    return {"speakers": [speaker_view(sp) for sp in store.speakers(m["id"])]}


def merge_speakers(user: AuthUser, meeting_id: str, sources: list[str], into: str) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    known = {sp["id"]: sp for sp in store.speakers(m["id"])}
    if into not in known or known[into].get("merged_into"):
        raise MeetingProblem(404, "speaker_not_found", "Spiker topilmadi")
    sources = [s for s in dict.fromkeys(sources) if s != into]
    if not sources or any(s not in known for s in sources):
        raise MeetingProblem(404, "speaker_not_found", "Spiker topilmadi")
    with store.transaction() as conn:
        for src in sources:
            conn.execute("UPDATE segments SET speaker=? WHERE meeting_id=? AND speaker=?", (into, m["id"], src))
            conn.execute("UPDATE speakers SET merged_into=?, talk_sec=0 WHERE meeting_id=? AND id=?",
                         (into, m["id"], src))
            # Avval shu spikerga birlashtirilganlar ham yangi egaga o'tadi.
            conn.execute("UPDATE speakers SET merged_into=? WHERE meeting_id=? AND merged_into=?",
                         (into, m["id"], src))
            conn.execute("UPDATE action_items SET owner_speaker=? WHERE meeting_id=? AND owner_speaker=?",
                         (into, m["id"], src))
        _recount_talk(conn, m["id"])
        conn.execute("UPDATE meetings SET transcript_rev=transcript_rev+1, updated_at=? WHERE id=?",
                     (int(time.time()), m["id"]))
    m = store.meeting(user.actorId, meeting_id)
    return {"speakers": [speaker_view(sp) for sp in store.speakers(m["id"])],
            "transcriptRev": int(m["transcript_rev"])}


def _recount_talk(conn: Any, meeting_id: str) -> None:
    conn.execute(
        "UPDATE speakers SET talk_sec=COALESCE((SELECT SUM(\"end\"-start) FROM segments s WHERE "
        "s.meeting_id=speakers.meeting_id AND s.speaker=speakers.id), 0) WHERE meeting_id=?", (meeting_id,))


def edit_segment(user: AuthUser, meeting_id: str, segment_id: int, body: Any) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    seg = store.row('SELECT * FROM segments WHERE meeting_id=? AND id=?', (m["id"], int(segment_id)))
    if seg is None:
        raise MeetingProblem(404, "segment_not_found", "Segment topilmadi")
    given = body.model_fields_set
    fields: dict[str, Any] = {}
    if "text" in given and body.text is not None:
        text = " ".join(body.text.split())
        if not text:
            raise MeetingProblem(400, "invalid_text", "Matn bo'sh bo'lmasin")
        fields["text"] = text
    if "speaker" in given:
        if body.speaker is not None:
            known = {sp["id"]: sp for sp in store.speakers(m["id"])}
            if body.speaker not in known or known[body.speaker].get("merged_into"):
                raise MeetingProblem(404, "speaker_not_found", "Spiker topilmadi")
        fields["speaker"] = body.speaker
    if fields:
        with store.transaction() as conn:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE segments SET {sets}, edited=1 WHERE meeting_id=? AND id=?",
                         list(fields.values()) + [m["id"], int(segment_id)])
            if "speaker" in fields:
                _recount_talk(conn, m["id"])
            conn.execute("UPDATE meetings SET transcript_rev=transcript_rev+1, updated_at=? WHERE id=?",
                         (int(time.time()), m["id"]))
    seg = store.row('SELECT * FROM segments WHERE meeting_id=? AND id=?', (m["id"], int(segment_id)))
    m = store.meeting(user.actorId, meeting_id)
    return {"segment": segment_view(seg), "transcriptRev": int(m["transcript_rev"])}


# --- 16-21. xulosalar va eksport ------------------------------------------------------------------------


def summary_card(s: dict[str, Any], m: dict[str, Any]) -> dict[str, Any]:
    error = {"code": s["error_code"], "message": message_for(s["error_code"])} if s.get("error_code") else None
    return {"id": s["id"], "template": s["template"], "language": s["language"], "status": s["status"],
            "primary": s["id"] == m.get("primary_summary_id"),
            "stale": int(s.get("transcript_rev") or 0) < int(m.get("transcript_rev") or 0),
            "transcriptRev": int(s.get("transcript_rev") or 0), "createdAt": iso(s.get("created_at")),
            "finishedAt": iso(s.get("finished_at")), "error": error}


_TOKEN = re.compile(r"\[(S\d{1,2})\]")


def _map_merged(value: Any, merged: dict[str, str]) -> Any:
    """Birlashtirilgan spikerlar xulosada javob paytida almashtiriladi (S3 -> S1)."""
    if not merged:
        return value
    if isinstance(value, str):
        if value in merged:
            return merged[value]
        return _TOKEN.sub(lambda m: f"[{merged.get(m.group(1), m.group(1))}]", value)
    if isinstance(value, list):
        out = [_map_merged(v, merged) for v in value]
        if out and all(isinstance(v, str) for v in out):
            out = list(dict.fromkeys(out))
        return out
    if isinstance(value, dict):
        return {k: _map_merged(v, merged) for k, v in value.items()}
    return value


def _merged_map(speakers: list[dict[str, Any]]) -> dict[str, str]:
    by_id = {sp["id"]: sp for sp in speakers}
    out = {}
    for sp in speakers:
        target, seen = sp.get("merged_into"), 0
        while target and by_id.get(target, {}).get("merged_into") and seen < 8:
            target, seen = by_id[target]["merged_into"], seen + 1
        if target:
            out[sp["id"]] = target
    return out


def summaries(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    m = _owned(user.actorId, meeting_id)
    return {"items": [summary_card(s, m) for s in runtime().store.summaries(m["id"])]}


def create_summary(user: AuthUser, meeting_id: str, body: Any, now: float | None = None) -> tuple[dict[str, Any], int]:
    now = time.time() if now is None else now
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    _require_transcript(m)
    if m["status"] not in ("ready", "summarizing"):
        raise MeetingProblem(409, "not_ready", "Transkript hali tayyor emas")
    language = body.language or m.get("language") or "uz"
    rev = int(m["transcript_rev"])
    if not body.force:
        for s in store.summaries(m["id"]):
            if s["status"] in ("ready", "queued", "running") and s["language"] == language \
                    and int(s["transcript_rev"]) == rev and s["prompt_version"] == prompts.PROMPT_VERSION \
                    and body.template in (s["template"], s.get("requested_template")):
                return summary_card(s, m), 200
    _rate("summary", user.actorId, settings.meetings_summary_per_hour)
    make_primary = body.makePrimary if body.makePrimary is not None else body.template != "follow_up"
    if body.template == "follow_up":
        make_primary = False
    sid = new_id()
    store.insert_summary({"id": sid, "meeting_id": m["id"], "template": body.template,
                          "requested_template": body.template, "language": language,
                          "prompt_version": prompts.PROMPT_VERSION, "transcript_rev": rev, "status": "queued",
                          "created_at": int(now)})
    if make_primary:
        store.update_meeting(m["id"], now=now, primary_summary_id=sid, summary_status="queued",
                             next_attempt_at=None)
    else:
        # Ishchi tayyor yig'ilishni darhol olsin (eski kutish muddati to'smasin).
        store.update_meeting(m["id"], now=now, next_attempt_at=None)
    m = store.meeting(user.actorId, meeting_id)
    return summary_card(store.summary(m["id"], sid), m), 202


def _summary_or_404(m: dict[str, Any], summary_id: str) -> dict[str, Any]:
    s = runtime().store.summary(m["id"], summary_id)
    if s is None:
        raise MeetingProblem(404, "summary_not_found", "Xulosa topilmadi")
    return s


def get_summary(user: AuthUser, meeting_id: str, summary_id: str) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    s = _summary_or_404(m, summary_id)
    speakers = store.speakers(m["id"])
    content = jload(s.get("content_json")) if s["status"] == "ready" else None
    # Ko'rinish: har fakt bir marta (`compact`) - bazadagi xulosa o'zgarmaydi, eski yozuvlar ham.
    content = compact.compact(_map_merged(content, _merged_map(speakers))) if content else content
    return {**summary_card(s, m), "promptVersion": s["prompt_version"], "model": s.get("model") or "",
            "generatedBy": generated_by(s),
            "layout": templates.layout(s["template"], s["language"]),
            "speakers": [speaker_view(sp) for sp in speakers], "content": content}


def generated_by(s: dict[str, Any]) -> dict[str, Any] | None:
    """Xulosani qaysi model yozgan: `{provider: v3|openai|ollama, model}`. Faqat tayyor
    xulosada. `provider` ustuni yo'q eski qator - zanjirdan oldin faqat Ollama bor edi."""
    if s.get("status") != "ready" or not (s.get("provider") or s.get("model")):
        return None
    return {"provider": s.get("provider") or "ollama", "model": s.get("model") or None}


def delete_summary(user: AuthUser, meeting_id: str, summary_id: str) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    s = _summary_or_404(m, summary_id)
    store.execute("DELETE FROM summaries WHERE id=?", (s["id"],))
    if m.get("primary_summary_id") == s["id"]:
        store.update_meeting(m["id"], primary_summary_id=None, summary_status="none")
    return {"id": s["id"], "status": "deleted"}


def export_summary(user: AuthUser, meeting_id: str, summary_id: str, fmt: str) -> tuple[str, str, str]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    s = _summary_or_404(m, summary_id)
    if s["status"] != "ready":
        raise MeetingProblem(409, "not_ready", "Xulosa hali tayyor emas")
    speakers = {sp["id"]: sp for sp in store.speakers(m["id"])}
    content = compact.compact(_map_merged(jload(s["content_json"], {}), _merged_map(list(speakers.values()))))
    text = export.summary_document(content, templates.layout(s["template"], s["language"]), speakers,
                                   s["language"], float(m.get("recorded_at") or 0), markdown=fmt == "md")
    name = export.slug(content.get("title") or m.get("title") or "meeting")
    if fmt == "md":
        return text, "text/markdown; charset=utf-8", f"{name}.md"
    return text, "text/plain; charset=utf-8", f"{name}.txt"


def export_transcript(user: AuthUser, meeting_id: str, fmt: str, *, with_speakers: bool,
                      with_timestamps: bool) -> tuple[str, str, str]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    _require_transcript(m)
    speakers = {sp["id"]: sp for sp in store.speakers(m["id"])}
    segments = store.segments(m["id"])
    lang = m.get("language") or "uz"
    name = export.slug(m.get("title") or "meeting")
    if fmt == "srt":
        return (export.transcript_srt(segments, speakers, lang, with_speakers=with_speakers),
                "application/x-subrip; charset=utf-8", f"{name}.srt")
    return (export.transcript_txt(segments, speakers, lang, with_speakers=with_speakers,
                                  with_timestamps=with_timestamps), "text/plain; charset=utf-8", f"{name}.txt")


#: 503 xabarlari: DOCX/PDF kutubxonasi yoki PDF shrifti serverda yo'q, yoki navbat to'la.
_RENDER_MESSAGES = {
    "pdf_unavailable": "PDF hozircha tayyorlab bo'lmaydi - DOCX yoki matn ko'rinishida yuklab oling",
    "docx_unavailable": "Word fayli hozircha tayyorlab bo'lmaydi - PDF yoki matn ko'rinishida yuklab oling",
    "export_busy": "Hozir boshqa fayllar tayyorlanmoqda - birozdan keyin qayta urinib ko'ring",
}

_export_cond = threading.Condition()
#: Eksport kutayotgan YOKI chizilayotgan odamlar (`actorId`) va hozir chizilayotganlar soni.
_export_users: set[int] = set()
_export_active = 0


@contextlib.contextmanager
def _export_slot(actor_id: int):
    """Bir vaqtdagi eksportlar chegarasi.

    NEGA: endpoint sync - kutayotgan har so'rov umumiy threadpool'dan (anyio, ~40 ip) bitta
    ipni band qiladi, API ning deyarli hamma handleri ham sync. Soatlik chegara (30) bir
    vaqtdagi so'rovlarni to'xtatmaydi: bitta odam 30 ta PDF ni BIRDAN yuborsa, ular navbatda
    o'tirib qolgan API ni ipsiz qoldirardi. Shuning uchun:

    * bitta odam - bir vaqtda BITTA eksport: ikkinchisi kutmaydi, darhol 429 `export_busy`
      (+ `Retry-After`) - ilova "tayyorlanmoqda" deydi;
    * butun jarayon - bir vaqtda `MEETINGS_EXPORT_CONCURRENCY` ta; navbat qisqa
      (`MEETINGS_EXPORT_WAIT_SEC`), oshsa 503 `export_busy`.

    Rad etilgan so'rov soatlik chegarani yemaydi (u slot olingandan keyin hisoblanadi)."""
    global _export_active
    actor = int(actor_id)
    limit = max(1, int(settings.meetings_export_concurrency))
    with _export_cond:
        if actor in _export_users:
            raise MeetingProblem(429, "export_busy", "Oldingi fayl hali tayyorlanmoqda",
                                 headers={"Retry-After": "5"})
        _export_users.add(actor)
        if not _export_cond.wait_for(lambda: _export_active < limit,
                                     timeout=max(0.0, float(settings.meetings_export_wait_sec))):
            _export_users.discard(actor)
            raise MeetingProblem(503, "export_busy", _RENDER_MESSAGES["export_busy"], headers={"Retry-After": "10"})
        _export_active += 1
    try:
        yield
    finally:
        with _export_cond:
            _export_active -= 1
            _export_users.discard(actor)
            _export_cond.notify_all()


def export_meeting(user: AuthUser, meeting_id: str, fmt: str, *, summary_id: str | None = None,
                   parts: str | None = None, lang: str = "uz", now: float | None = None) -> tuple[bytes, str, str]:
    """To'liq hujjat (DOCX/PDF/MD/TXT) -> (baytlar, Content-Type, Content-Disposition).

    Xulosa - `summaryId` yoki asosiy xulosa. `parts` bo'sh - nima TAYYOR bo'lsa hammasi:
    xulosa hali yozilmagan bo'lsa ham transkriptning o'zi beriladi. Aniq so'ralgan qism
    tayyor bo'lmasa - 409 `not_ready` (+ `missing`, `available`: ilova "faqat transkript"
    deb qayta so'ray oladi). Chegara (`MEETINGS_EXPORT_PER_HOUR`) faqat haqiqiy faylga
    sarflanadi - 404/409 hisobga kirmaydi."""
    now = time.time() if now is None else now
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    if fmt not in export.FORMATS:
        # Router `pattern` bu yerga yetkazmaydi (422); funksiya to'g'ridan-to'g'ri chaqirilsa
        # KeyError -> 500 bo'lmasin.
        raise MeetingProblem(400, "invalid_format", "Format: docx, pdf, md yoki txt")
    try:
        wanted = export.parse_parts(parts)
    except ValueError as exc:
        raise MeetingProblem(400, "invalid_parts", f"Noma'lum qism: {exc}") from None
    if summary_id:
        s = _summary_or_404(m, summary_id)
    else:
        s = store.summary(m["id"], m["primary_summary_id"]) if m.get("primary_summary_id") else None
    summary_ready = bool(s and s["status"] == "ready" and s.get("content_json"))
    transcript_ready = _transcript_ready(m)
    available = [p for p in export.PARTS if (transcript_ready if p == "transcript" else summary_ready)]
    if wanted is None:
        if summary_id and not summary_ready:
            # Aniq tanlangan xulosa tayyor emas - jim "faqat transkript" berish chalg'itardi.
            raise MeetingProblem(409, "not_ready", "Xulosa hali tayyor emas", missing=["summary"],
                                 available=available)
        wanted = available
        if not wanted:
            raise MeetingProblem(409, "not_ready", "Yig'ilish hali tayyor emas", missing=list(export.PARTS),
                                 available=[])
    missing = [p for p in wanted if p not in available]
    if missing:
        message = ("Xulosa hali tayyor emas" if any(p in export.SUMMARY_PARTS for p in missing)
                   else "Transkript hali tayyor emas")
        raise MeetingProblem(409, "not_ready", message, missing=missing, available=available)
    with _export_slot(user.actorId):
        _rate("export", user.actorId, settings.meetings_export_per_hour)
        data, title, recorded_at = _export_render(m, s, wanted, summary_ready, fmt, lang, now)
    media, ext = export.FORMATS[fmt]
    ascii_name, real_name = export.file_names(title, recorded_at, ext)
    log.info("Yig'ilish %s: eksport %s, %d bayt, qismlar=%s", m["id"], fmt, len(data), ",".join(wanted))
    return data, media, export.content_disposition(ascii_name, real_name)


def _export_render(m: dict[str, Any], s: dict[str, Any] | None, wanted: list[str], summary_ready: bool, fmt: str,
                   lang: str, now: float) -> tuple[bytes, str, float]:
    """Hujjatni yig'ib chizadi -> (baytlar, sarlavha, yozilgan vaqt). 503 - `MeetingProblem`."""
    store = runtime().store
    speakers = {sp["id"]: sp for sp in store.speakers(m["id"])}
    content: dict[str, Any] | None = None
    actions: list[dict[str, Any]] | None = None
    brief_actions: list[dict[str, Any]] | None = None
    if s and summary_ready and any(p in export.SUMMARY_PARTS for p in wanted):
        # Fayl ham ilovadagi ko'rinishni oladi: har fakt bir marta.
        content = compact.compact(_map_merged(jload(s["content_json"], {}) or {},
                                              _merged_map(list(speakers.values()))))
        if "actions" in wanted or "mindmap" in wanted or "brief" in wanted:
            # "Qisqa xulosa" - XULOSA tilida (yorliqlar ham, "2-ishtirokchi" ham), jadval - ilova tilida.
            brief_lang = content.get("language") or lang
            if s["id"] == m.get("primary_summary_id"):
                # Asosiy xulosa - JONLI vazifalar: odam tahrirlagani/qo'shgani, holati va CRM kaliti.
                rows = sorted(store.action_items(m["id"]), key=_action_order)
                rows = [{**a, "crm_result": jload(a.get("crm_result"))} for a in rows]
                actions = export.actions_from_rows(rows, speakers, lang)
                if "brief" in wanted:
                    brief_actions = export.actions_from_rows(rows, speakers, brief_lang)
            else:
                actions = export.actions_from_content(content, speakers, lang)
                if "brief" in wanted:
                    brief_actions = export.actions_from_content(content, speakers, brief_lang)
    segments = store.segments(m["id"]) if "transcript" in wanted else None
    recorded_at = float(m.get("recorded_at") or m.get("created_at") or 0)
    title = m.get("title") or (content or {}).get("title") or default_title(recorded_at, lang)
    duration = float(m.get("duration_sec") or ((content or {}).get("meeting") or {}).get("durationSec") or 0)
    stale = bool(s and summary_ready and int(s.get("transcript_rev") or 0) < int(m.get("transcript_rev") or 0))
    doc = export.build_document(title=title, recorded_at=recorded_at, duration_sec=duration, speakers=speakers,
                                lang=lang, now=now, parts=wanted, template=s["template"] if s else None,
                                content=content, actions=actions, segments=segments, stale=stale,
                                text_lang=(s or {}).get("language") or m.get("language"),
                                brief_actions=brief_actions, user_title=m.get("title_source") == "user")
    try:
        data = export.render(doc, fmt, font_dir=settings.meetings_export_font_dir)
    except export.RenderUnavailable as exc:
        log.warning("Yig'ilish %s: %s eksporti bo'lmadi (%s)", m["id"], fmt, exc.code)
        headers = {"Retry-After": "10"} if exc.code == "export_busy" else None
        raise MeetingProblem(503, exc.code, _RENDER_MESSAGES.get(exc.code), headers=headers) from None
    return data, title, recorded_at


# --- 22-25. vazifalar --------------------------------------------------------------------------------


def action_view(a: dict[str, Any], starts: dict[int, float]) -> dict[str, Any]:
    ids = [int(x) for x in jload(a.get("source_ids"), []) or []]
    return {"id": a["id"], "meetingId": a["meeting_id"], "summaryItemId": a.get("summary_item_id"),
            "task": a["task"],
            "owner": {"speaker": a.get("owner_speaker"), "name": a.get("owner_name"),
                      "kind": a.get("owner_kind") or "unknown"},
            "due": {"date": a.get("due_date"), "time": a.get("due_time"), "raw": a.get("due_raw")},
            "priority": a.get("priority"), "status": a["status"], "origin": a["origin"],
            "edited": bool(a.get("edited")), "needsConfirmation": bool(a.get("needs_confirmation")),
            "sourceSegmentIds": ids, "start": starts.get(ids[0]) if ids else None, "quote": a.get("quote"),
            "createdAt": iso(a.get("created_at")), "updatedAt": iso(a.get("updated_at")),
            "crm": crm_view(a)}


def crm_view(a: dict[str, Any], now: float | None = None) -> dict[str, Any] | None:
    """Vazifaning CRM taklifi: kalit (tasdiqlash `/api/v1/actions/{token}/confirm`), holat
    (`pending` muddati o'tgan bo'lsa - `expired`), kartadagi taklif, natija. Taklif bo'lmasa `null`."""
    if not a.get("crm_token"):
        return None
    status = a.get("crm_status") or "pending"
    expires = a.get("crm_expires_at")
    if status == "pending" and crm.expired(expires, time.time() if now is None else now):
        status = "expired"
    return {"token": a["crm_token"], "status": status, "proposal": jload(a.get("crm_proposal")),
            "expiresAt": expires, "result": jload(a.get("crm_result")), "updatedAt": iso(a.get("crm_updated_at"))}


def _starts(meeting_id: str) -> dict[int, float]:
    return {int(r["id"]): round(float(r["start"]), 2) for r in
            runtime().store.rows("SELECT id, start FROM segments WHERE meeting_id=?", (meeting_id,))}


_STATUS_ORDER = {"open": 0, "done": 1, "dismissed": 2}


def _action_order(a: dict[str, Any]) -> tuple:
    """Vazifalar tartibi (ro'yxat va eksport jadvali bir xil): holat, muddat, xulosadagi raqam."""
    return (_STATUS_ORDER.get(a["status"], 3), a.get("due_date") or "9999-12-31",
            a.get("summary_item_id") is None, _item_number(a), a["created_at"], a["id"])


def action_items(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    m = _owned(user.actorId, meeting_id)
    starts = _starts(m["id"])
    items = sorted(runtime().store.action_items(m["id"]), key=_action_order)
    return {"items": [action_view(a, starts) for a in items]}


def _item_number(a: dict[str, Any]) -> int:
    found = re.search(r"\d+", a.get("summary_item_id") or "")
    return int(found.group()) if found else 0


def _check_item_fields(m: dict[str, Any], body: Any, given: set[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if "task" in given:
        task = " ".join((body.task or "").split())
        if not task:
            raise MeetingProblem(400, "invalid_task", "Vazifa matni bo'sh bo'lmasin")
        fields["task"] = task[:300]
    if "ownerSpeaker" in given:
        if body.ownerSpeaker is not None:
            known = {sp["id"] for sp in runtime().store.speakers(m["id"])}
            if body.ownerSpeaker not in known:
                raise MeetingProblem(404, "speaker_not_found", "Spiker topilmadi")
        fields["owner_speaker"] = body.ownerSpeaker
    if "ownerName" in given:
        fields["owner_name"] = (" ".join((body.ownerName or "").split()) or None)
    if "dueDate" in given:
        if body.dueDate is not None and dates.parse_iso(body.dueDate) is None:
            raise MeetingProblem(400, "invalid_date", "Sana YYYY-MM-DD shaklida bo'lsin")
        fields["due_date"] = dates.parse_iso(body.dueDate).isoformat() if body.dueDate else None
    if "dueTime" in given:
        if body.dueTime is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", body.dueTime):
            raise MeetingProblem(400, "invalid_time", "Vaqt HH:MM shaklida bo'lsin")
        fields["due_time"] = body.dueTime
    if "priority" in given:
        fields["priority"] = body.priority
    if "owner_speaker" in fields or "owner_name" in fields:
        fields["owner_kind"] = "person" if (fields.get("owner_speaker") or fields.get("owner_name")) else "unknown"
    return fields


def add_action_item(user: AuthUser, meeting_id: str, body: Any) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    fields = _check_item_fields(m, body, set(body.model_fields_set) | {"task"})
    t = int(time.time())
    item_id = new_id()
    store.insert_action_item({"id": item_id, "meeting_id": m["id"], "status": "open", "origin": "user",
                              "edited": 0, "needs_confirmation": 0, "source_ids": "[]", "created_at": t,
                              "updated_at": t, "owner_kind": "unknown", **fields})
    return action_view(store.action_item(m["id"], item_id), {})


def patch_action_item(user: AuthUser, meeting_id: str, item_id: str, body: Any) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    item = store.action_item(m["id"], item_id)
    if item is None:
        raise MeetingProblem(404, "item_not_found", "Vazifa topilmadi")
    given = set(body.model_fields_set)
    fields = _check_item_fields(m, body, given - {"status"})
    if fields:
        fields["edited"] = 1
        if {"owner_speaker", "owner_name", "due_date", "due_time"} & set(fields):
            fields["needs_confirmation"] = 0
    if "status" in given and body.status is not None:
        fields["status"] = body.status
    if fields:
        fields["updated_at"] = int(time.time())
        store.update_action_item(item["id"], **fields)
    return action_view(store.action_item(m["id"], item_id), _starts(m["id"]))


#: Vazifa bo'yicha CRM so'rovi qulfi: ikki tez bosish ikkita taklif (ikkala kartani ham
#: tasdiqlash mumkin bo'lib qoladi) bermasin - ikkinchisi birinchisini kutadi va o'sha taklifni oladi.
_crm_locks: dict[str, threading.Lock] = {}
_crm_locks_guard = threading.Lock()


def _crm_lock(item_id: str) -> threading.Lock:
    with _crm_locks_guard:
        if len(_crm_locks) > 1000:
            for key in [k for k, lock in _crm_locks.items() if not lock.locked()]:
                _crm_locks.pop(key, None)
        return _crm_locks.setdefault(item_id, threading.Lock())


def action_item_to_crm(user: AuthUser, meeting_id: str, item_id: str, body: Any = None) -> dict[str, Any]:
    """Vazifa -> v3 -> CRM TAKLIFI (`crm.py`). Tasdiqlash - chatdagi `/api/v1/actions/{token}/confirm`.

    Muddati o'tmagan taklif bo'lsa va vazifa o'shandan beri o'zgarmagan bo'lsa (ikki marta
    bosildi) - agentga qayta borilmaydi, o'sha taklif qaytadi; `force` - yangisi. CRM da
    allaqachon yaratilgan (`executed`) vazifa HECH QACHON qayta yuborilmaydi (`force` bilan
    ham): aks holda saqlangan CRM kaliti o'chib, ikkinchi tasdiq ikkinchi vazifa yaratardi.
    -> `{status, proposal, text, reason, item}`."""
    rt = runtime()
    store = rt.store
    m = _owned(user.actorId, meeting_id)
    if store.action_item(m["id"], item_id) is None:
        raise MeetingProblem(404, "item_not_found", "Vazifa topilmadi")
    lock = _crm_lock(item_id)
    if not lock.acquire(timeout=float(settings.meetings_crm_timeout) + 15.0):
        return {"status": "failed", "proposal": None, "text": None, "reason": crm.BUSY,
                "item": action_view(store.action_item(m["id"], item_id), _starts(m["id"]))}
    try:
        return _item_to_crm(rt, user, m, item_id, body)
    finally:
        lock.release()


def _item_to_crm(rt: Any, user: AuthUser, m: dict[str, Any], item_id: str, body: Any) -> dict[str, Any]:
    store = rt.store
    # Qulf ichida QAYTA o'qiladi: kutib turgan bosish birinchisi saqlagan taklifni ko'rsin.
    item = store.action_item(m["id"], item_id)
    if item is None:
        raise MeetingProblem(404, "item_not_found", "Vazifa topilmadi")
    current = crm_view(item)

    def done(result: dict[str, Any], row: dict[str, Any] | None = None) -> dict[str, Any]:
        log.info("Yig'ilish %s: vazifa %s CRM ga - %s%s", m["id"], item["id"], result["status"],
                 f" ({result['reason']})" if result.get("reason") else "")
        return {**result, "item": action_view(row or item, _starts(m["id"]))}

    if current and current["status"] == "executed":
        # Bitta vazifa - bitta CRM vazifasi: agentga borilmaydi, chegara ham sarflanmaydi.
        return done({"status": "failed", "proposal": None, "text": None, "reason": crm.ALREADY})
    speakers = {sp["id"]: sp for sp in store.speakers(m["id"])}
    primary = store.summary(m["id"], m["primary_summary_id"]) if m.get("primary_summary_id") else None
    content = jload(primary.get("content_json"), {}) if primary and primary["status"] == "ready" else {}
    question = crm.question(item, m, speakers, project=getattr(body, "project", None),
                            keywords=(content or {}).get("keywords") or [], requester=user.fullName)
    # So'rov izi: vazifa (matn, mas'ul, muddat) yoki loyiha ishorasi o'zgarsa - eski taklif mos emas.
    sig = hashlib.sha256(question.encode("utf-8")).hexdigest()[:32]
    if not getattr(body, "force", False) and current and current["status"] == "pending" and current["proposal"] \
            and item.get("crm_sig") == sig:
        return {"status": "proposed", "proposal": current["proposal"], "text": None, "reason": None,
                "item": action_view(item, _starts(m["id"]))}
    _rate("crm", user.actorId, settings.meetings_crm_per_hour)

    client = live_assistant(rt)
    if client is None or not getattr(client, "configured", False):
        return done({"status": "failed", "proposal": None, "text": None, "reason": crm.NOT_CONFIGURED})
    user_id, tokens = crm_identity(user)
    if not tokens.get("crm"):
        # CRM ulanmagan - agentga bormasdan (u baribir `auth_missing` derdi).
        return done({"status": "failed", "proposal": None, "text": None, "reason": crm.NOT_CONNECTED})
    from ..analytics import bind
    from ..integrations.assistant import AssistantError

    try:
        with bind(user.actorId):
            # W1 (2026-10-11): `meeting_crm` flag'i `agent` bo'lsa - v4 shakli; xato bo'lsa yoki
            # qo'ng'iroq yozuvi bo'lsa (rozilik hali serverda yo'q) - bugungi v3 yo'li.
            reply = _meeting_crm_v4(m, question, user_id, tokens)
            if reply is None:
                # Qattiq muddat (`within`): v3 jim tursa ham odam `MEETINGS_CRM_TIMEOUT` dan ortiq kutmaydi;
                # kech kelgan taklif tashlanadi (saqlanmaydi, 15 daqiqada o'zi eskiradi).
                reply = llm_mod.within(
                    lambda: llm_mod.collect(client, question, user_id=user_id, tokens=tokens,
                                            max_chars=settings.meetings_v3_max_chars, op="meeting_crm",
                                            deadline=settings.meetings_crm_timeout),
                    float(settings.meetings_crm_timeout), what="CRM")
    except llm_mod.DeadlineExceeded:
        return done({"status": "failed", "proposal": None, "text": None, "reason": crm.TIMEOUT})
    except AssistantError as exc:
        return done({"status": "failed", "proposal": None, "text": None, "reason": crm.open_failure(exc)})
    result = crm.outcome(reply)
    if result["status"] != "proposed":
        return done(result)
    proposal = result["proposal"]
    token = str(proposal["token"])[:256]
    store.update_action_item(item["id"], crm_token=token, crm_status="pending",
                             crm_proposal=jdump(proposal), crm_expires_at=proposal.get("expires_at"),
                             crm_result=None, crm_sig=sig, crm_updated_at=int(time.time()))
    if current and current["status"] == "pending" and current["token"] != token:
        # Eski (hali tasdiqlanmagan) taklif yuqorida ham bekor qilinadi: ekranda qolgan eski
        # karta tasdiqlanib, ikkinchi vazifa yaratilmasin. Eng yaxshi urinish - xato jurnalga.
        _cancel_upstream(client, current["token"], user_id, tokens)
    return done(result, store.action_item(m["id"], item["id"]))


def _cancel_upstream(client: Any, token: str, user_id: str, tokens: dict[str, str]) -> None:
    cancel = getattr(client, "cancel_action", None)
    if not callable(cancel):
        return
    try:
        cancel(token, user_id=user_id, tokens=tokens)
    except Exception as exc:                                         # noqa: BLE001
        log.info("Yig'ilish vazifasi: eski CRM taklifi bekor qilinmadi (%s)", type(exc).__name__)


def note_crm_outcome(actor_id: int, token: str, status: str, result: Any = None) -> None:
    """`/api/v1/actions/{token}/confirm|cancel` natijasi -> vazifaning CRM holati.

    Chat tasdiqlashi O'ZGARMAYDI: ombor yo'q bo'lsa (bo'lim hech qachon yoqilmagan) hech
    narsa qilinmaydi va yaratilmaydi, xato esa faqat jurnalga - tasdiq javobiga ta'sir qilmaydi."""
    try:
        store = runtime().store
        if not store.exists or not token or not status:
            return
        changed = store.set_crm_status(actor_id, token, status,
                                       result if isinstance(result, dict) and result else None)
        if changed:
            log.info("Yig'ilish vazifasi: CRM taklifi %s", status)
    except Exception:                                              # noqa: BLE001
        log.warning("Yig'ilish vazifasining CRM holati yozilmadi", exc_info=True)


def my_action_items(user: AuthUser, status: str, limit: int) -> dict[str, Any]:
    store = runtime().store
    if not store.exists:
        return {"items": []}
    rows = store.my_action_items(user.actorId, status, limit)
    starts: dict[str, dict[int, float]] = {}
    out = []
    for a in rows:
        if a["meeting_id"] not in starts:
            starts[a["meeting_id"]] = _starts(a["meeting_id"])
        view = action_view(a, starts[a["meeting_id"]])
        view.update(meetingTitle=a.get("meeting_title") or "", recordedAt=iso(a.get("meeting_recorded_at")))
        out.append(view)
    return {"items": out}


# --- 26-27. savol-javob va yig'ilish chati (`chat.py`) ---------------------------------------------------------


def _question_view(q: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    citations = []
    for sid in jload(q.get("citations"), []) or []:
        seg = by_id.get(int(sid))
        if seg:
            citations.append({"segmentId": int(sid), "start": round(float(seg["start"]), 2),
                              "speaker": seg.get("speaker"), "text": seg["text"]})
    # `clientId` - xabarning klient kaliti (`chat_send`): ilova kutilayotgan xabarini tarixdagi navbat bilan shu
    # kalit orqali tanib oladi. Eski `/ask` va `/questions` javob modeli (`AskAnswer`) uni ko'rsatmaydi.
    return {"id": q["id"], "question": q["question"], "answer": q["answer"], "citations": citations,
            "followUps": jload(q.get("follow_ups"), []) or [], "createdAt": iso(q.get("created_at")),
            "clientId": q.get("client_id")}


def _turn_view(q: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Chat navbati: savol-javob ko'rinishi (klient kaliti bilan) + qaysi kanaldan kelgani va qaysi model javob
    bergani (eski qatorda `None`). Eski `/ask` va `/questions` javob modeli (`AskAnswer`) ortiqcha maydonlarni
    ko'rsatmaydi."""
    return {**_question_view(q, by_id), "channel": q.get("channel"), "model": q.get("model")}


def chat_history(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    """Yig'ilish chati: hisob EGASINING faol navbatlari (ESKISI birinchi; boshqa so'rovchilarniki - Slack -
    ko'rinmaydi) va hozir javob beradigan model nomi (`""` - sozlanmagan). Transkript shart emas (tayyor
    bo'lmasa ro'yxat shunchaki bo'sh)."""
    rt = runtime()
    m = _owned(user.actorId, meeting_id)
    by_id = {int(s["id"]): s for s in rt.store.segments(m["id"])}
    return {"items": [_turn_view(q, by_id) for q in rt.store.chat_turns(m["id"])], "model": _chat_model(rt, m)}


def _chat_model(rt: Any, m: dict[str, Any]) -> str:
    """Shu yozuvga javob beradigan zanjirdagi birinchi SOZLANGAN modelning nomi (ilovadagi yorliq) - `chat_send`
    dagi AYNAN o'sha zanjir: agent bo'g'ini yoqiq bo'lsa (`brain.meeting_ask_providers`, telefon qo'ng'irog'idan
    boshqasida) - `agent`. Tokensiz va tarmoqsiz: tarix so'rovi CRM sessiyasini yangilamaydi, agent holati
    keshdan o'qiladi."""
    from .. import brain as _brain

    live = live_assistant(rt) if "v3" in llm_mod.ask_chain_names() else None
    providers = llm_mod.ask_providers(rt, user_id="", tokens={}, live_assistant=live)
    if _brain.meeting_agent_ok(m):
        providers = _brain.meeting_ask_providers(providers, language=m.get("language") or "uz")
    return next((p.model for p in providers if p.configured), "")


def chat_send(user: AuthUser, meeting_id: str, message: str, language: str | None, *,
              channel: str = "api", asker: str | None = None, client_id: str | None = None) -> dict[str, Any]:
    """Yig'ilish chatiga xabar -> javob navbati (`_turn_view`). Javob shu yig'ilishning transkripti, asosiy
    xulosasi va suhbat xotirasi (`chat.memory`) bilan - hisob egasining mobil ilova, web va Telegram'dagi
    savollari bitta suhbat. `asker` - UMUMIY hisobda kim so'rayapti (Slack: `slack:<user id>`; ochiq matn,
    `chat.asker_of`): xotira faqat o'sha odamning navbatlaridan, navbat ham unga yoziladi; `None` - hisob egasi.
    Saqlanadi: kanal (`chat.CHANNELS`, noma'lumi - `api`), so'rovchi, klient kaliti, javob bergan model va javob
    tili. Javob kutilayotganda suhbat tozalansa (xotira qatorlari arxivga o'tsa) yoki matn almashsa (qayta
    o'girish) - navbat arxivda tug'iladi (`store.add_turn`).

    `client_id` - IDEMPOTENTLIK (ilova «Qayta yuborish»da o'sha kalitni yuboradi; botlar bermaydi), soatlik
    chegara va modeldan OLDIN: (yig'ilish, so'rovchi, kalit) bo'yicha FAOL navbat bor - o'sha qaytadi; shu kalitli
    xabar shu jarayonda hali javob kutyapti - birinchisi kutiladi (`MEETINGS_ASK_DEADLINE` + `chat.WAIT_EXTRA_SEC`
    gacha) va yana qaraladi; hech narsa saqlanmagan bo'lsa (birinchisi yiqildi) - oddiy urinish. Xatolar `/ask`
    dagidek: 404, 409 `not_ready`, 429 `rate_limited` (savol bilan UMUMIY soatlik chegara), 503 `llm_unavailable`."""
    rt = runtime()
    asker = chat_mod.asker_of(asker)
    client_id = chat_mod.client_id_of(client_id)
    until = time.monotonic() + float(settings.meetings_ask_deadline) + chat_mod.WAIT_EXTRA_SEC
    while True:
        # Har aylanishda qaytadan: kutish paytida yozuv o'chirilgan yoki qayta o'girilgan bo'lishi mumkin.
        m = _owned(user.actorId, meeting_id)
        _require_transcript(m)
        if client_id is None:
            return _chat_answer(rt, user, m, message, language, channel=channel, asker=asker, client_id=None)
        done = _client_turn(rt, m, client_id, asker)
        if done is not None:
            return done
        key = (m["id"], asker, client_id)
        event, owner = chat_mod.claim(key)
        if owner:
            try:
                # Oldingi urinish tekshiruv bilan egallash orasida saqlab, kalitni bo'shatgan bo'lishi mumkin.
                return _client_turn(rt, m, client_id, asker) or _chat_answer(
                    rt, user, m, message, language, channel=channel, asker=asker, client_id=client_id)
            finally:
                chat_mod.release(key, event)
        left = until - time.monotonic()
        if left <= 0:
            # Birinchi urinish o'z muddatidan ham oshdi: oddiy urinish (saqlashda baribir takror yozilmaydi).
            return _chat_answer(rt, user, m, message, language, channel=channel, asker=asker, client_id=client_id)
        log.info("Yig'ilish %s: shu klient kalitli xabar hali javob kutmoqda - birinchisi kutiladi", m["id"])
        event.wait(left)


def _client_turn(rt: Any, m: dict[str, Any], client_id: str, asker: str | None) -> dict[str, Any] | None:
    """Shu so'rovchining shu klient kalitli FAOL navbati (`_turn_view`) yoki `None`: xabar qayta yuborilgan, javob
    allaqachon saqlangan - modelga ham, soatlik chegaraga ham bormaymiz."""
    stored = rt.store.turn_by_client(m["id"], client_id, asker=asker)
    if stored is None:
        return None
    log.info("Yig'ilish %s: takroriy chat xabari (o'sha klient kaliti) - saqlangan navbat qaytdi", m["id"])
    return _turn_view(stored, {int(s["id"]): s for s in rt.store.segments(m["id"])})


def _chat_answer(rt: Any, user: AuthUser, m: dict[str, Any], message: str, language: str | None, *,
                 channel: str, asker: str | None, client_id: str | None) -> dict[str, Any]:
    """`chat_send` ning bitta urinishi: soatlik chegara, kontekst va xotira, model zanjiri, saqlash."""
    store = rt.store
    _rate("ask", user.actorId, settings.meetings_ask_per_hour)
    segments = [{"id": int(s["id"]), "start": float(s["start"]), "end": float(s["end"]), "speaker": s["speaker"],
                 "text": s["text"]} for s in store.segments(m["id"])]
    speakers = [sp for sp in store.speakers(m["id"]) if not sp.get("merged_into")]
    primary = store.summary(m["id"], m["primary_summary_id"]) if m.get("primary_summary_id") else None
    summary = jload(primary.get("content_json")) if primary and primary["status"] == "ready" else None
    day = dates.tashkent(float(m.get("recorded_at") or 0))
    meta = prompts.meta_line(day.date(), dates.WEEKDAYS["en"][day.weekday()], float(m.get("duration_sec") or 0),
                             [{"id": sp["id"], "name": sp.get("name")} for sp in speakers],
                             bool(m.get("speakers_available")), call=m.get("source") == "call")
    language = language or m.get("language") or "uz"
    channel = chat_mod.channel_of(channel)
    keep = int(settings.meetings_chat_history_turns or 0)
    loaded = store.chat_turns(m["id"], limit=keep, asker=asker) if keep > 0 else []
    history = chat_mod.memory(loaded)
    from .. import brain as _brain
    from ..analytics import bind

    try:
        with bind(user.actorId):
            providers = _ask_providers(rt, user)
            # Umumiy muddat: hamma model birga `MEETINGS_ASK_DEADLINE` ga sig'adi (odam kutib turibdi).
            # Telefon qo'ng'irog'i - yangi agent yo'li (bo'g'in va shadow) yo'q (`brain.meeting_agent_ok`).
            result, used = ask_mod.answer_chain(
                providers, deadline=settings.meetings_ask_deadline, agent_ok=_brain.meeting_agent_ok(m),
                question=message, language=language, meta=meta, segments=segments,
                speakers=[{"id": sp["id"], "name": sp.get("name")} for sp in speakers], summary=summary,
                history=history)
    except (LlmUnavailable, LlmFailed, LlmRateLimited, LlmBusy):
        raise MeetingProblem(503, "llm_unavailable", "Model hozir javob bera olmayapti - keyinroq urinib ko'ring")
    qid = new_id()
    try:
        # Javob qurilgan xotira qatorlari va savol boshidagi matn versiyasi bilan BITTA tranzaksiyada: kutish paytida
        # suhbat tozalangan yoki matn almashgan bo'lsa navbat arxivda tug'iladi (javob baribir qaytadi - odam so'ragan
        # edi); shu kalitli navbatni boshqa urinish saqlab ulgurgan bo'lsa - o'sha qaytadi.
        q = store.add_turn(
            {"id": qid, "meeting_id": m["id"], "question": message.strip()[:prompts.CHAT_QUESTION_CHARS],
             "answer": result["answer"], "citations": jdump(result["citations"]),
             "follow_ups": jdump(result["followUps"]), "channel": channel, "asker": asker, "client_id": client_id,
             "model": str(result.get("model") or used.model)[:80], "language": language,
             "created_at": int(time.time())},
            used=[r["id"] for r in loaded], gen=int(m.get("transcript_gen") or 0))
    except sqlite3.IntegrityError as exc:
        if "FOREIGN KEY" not in str(exc):
            raise
        # Javob kutilayotganda yozuv o'chirildi (boshqa qurilma, saqlash muddati) - 500 emas, oddiy 404.
        raise not_found() from None
    if q["id"] != qid:
        log.info("Yig'ilish %s: chatga %s javob berdi, lekin shu klient kalitli navbat allaqachon saqlangan - o'sha "
                 "qaytdi", m["id"], used.name)
    else:
        log.info("Yig'ilish %s: chatga %s javob berdi (%s, xotirada %d navbat%s)", m["id"], used.name, channel,
                 len(history), ", kutish paytida suhbat tozalangan yoki matn almashgan - navbat arxivda"
                 if q["archived_at"] is not None else "")
    return _turn_view(q, {s["id"]: s for s in segments})


def chat_reset(user: AuthUser, meeting_id: str, now: float | None = None, *,
               asker: str | None = None) -> dict[str, Any]:
    """Yangi suhbat: shu so'rovchining (`asker`, `chat_send` dagidek; `None` - hisob egasi) faol navbatlari
    arxivga - modelga ham, ro'yxatlarga ham bormaydi, qatorlar bazada qoladi (yumshoq); boshqa so'rovchilarning
    suhbatiga tegilmaydi. Faqat egalik tekshiriladi, transkript shart emas. -> `{"archived": n}`."""
    m = _owned(user.actorId, meeting_id)
    archived = runtime().store.archive_questions(m["id"], time.time() if now is None else now,
                                                 asker=chat_mod.asker_of(asker))
    log.info("Yig'ilish %s: yangi suhbat (%d navbat arxivga)", m["id"], archived)
    return {"archived": archived}


def ask(user: AuthUser, meeting_id: str, question: str, language: str | None, *,
        channel: str = "api") -> dict[str, Any]:
    """Eski savol-javob (`/ask`: eski ilovalar va web) - endi hisob egasining chat navbati (`chat_send`): o'sha
    ko'rinish, suhbat xotirasi bilan."""
    return chat_send(user, meeting_id, question, language, channel=channel)


def _ask_providers(rt: Any, user: AuthUser) -> list[Any]:
    """Savol zanjiri. v3 bo'lsa - odamning O'Z kimligi va tokenlari bilan (chatdagi qoida);
    tokenlar faqat v3 zanjirda bo'lganda olinadi (CRM sessiyasini yangilash tarmoqqa chiqadi)."""
    if "v3" not in llm_mod.ask_chain_names():
        return llm_mod.ask_providers(rt, user_id="", tokens={}, live_assistant=None)
    user_id, tokens = assistant_identity(user)
    return llm_mod.ask_providers(rt, user_id=user_id, tokens=tokens, live_assistant=live_assistant(rt))


def live_assistant(rt: Any) -> Any:
    """Savol-javob va CRM uchun v3 klienti: sinovda soxta, aks holda chatniki."""
    if rt.live_assistant is not None:
        return rt.live_assistant
    from ...api.v1 import chat as _chat

    return _chat._assistant


def assistant_identity(user: AuthUser) -> tuple[str, dict[str, str]]:
    """Savol-javob (Ask) uchun (`user_id`, platforma tokenlari) - chat bilan AYNAN bir xil
    (`chat.assistant_user_id`, `chat._live_tokens`), lekin FAQAT `meetings_ask_platforms`
    dagilari (default `crm`): yig'ilish savoliga HRM tokeni kerak emas (2026-10-10, F0)."""
    from ...api.v1 import chat as _chat

    from ...core.config import platforms_now

    allowed = platforms_now("meetings_ask_platforms")
    tokens = {k: v for k, v in dict(_chat._live_tokens(user)).items() if k in allowed}
    return _chat.assistant_user_id(user), tokens


#: Agent v4 chat savol chegarasi (`/api/v4/limits` -> `chat.max_question_chars`).
_V4_QUESTION_MAX = 8000


def meeting_crm_v4_body(question: str, user_id: str, crm_token: str) -> dict[str, Any]:
    """`POST /api/v4/chat` tanasi (`purpose: meeting_crm`). Alohida funksiya - admin
    "Tizim xaritasi" sinovi tanani AYNAN shu yerdan oladi (token o'rniga belgi bilan)."""
    return {
        "purpose": "meeting_crm",
        "question": question[:_V4_QUESTION_MAX],
        "user_id": user_id,
        "tokens": {"crm": crm_token},
        "store": False,
        "audience": "private",
        "tools": ["crm.read", "crm.propose"],
        "memory_scopes": [],
        "client": {"channel": "mobile"},
    }


def _meeting_crm_v4(m: dict[str, Any], question: str, user_id: str,
                    tokens: dict[str, str]) -> "llm_mod.V3Reply | None":
    """Agent v4 orqali CRM taklifi (`purpose: meeting_crm`) yoki `None` - bugungi yo'l.

    Faqat `crm.read` va `crm.propose`, faqat o'z CRM tokeni, `store: false` (tarix va vazifa
    holati yozilmaydi), `memory_scopes: []` (shaxsiy xotira ishlatilmaydi). Qo'ng'iroq yozuvi
    (`source == "call"`) agentga BORMAYDI - serverdagi rozilik belgisi (`call_consent`) va egasining
    alohida qarori (reja W5) kelguncha."""
    from ..brain import routing as _routing
    from ..integrations.agent_v4 import AgentError

    if str(m.get("source") or "") == "call" or not tokens.get("crm"):
        return None
    if not _routing.route("meeting_crm").agent:
        return None
    body = meeting_crm_v4_body(question, user_id, tokens["crm"])
    try:
        payload, _ = _routing.client().chat(body, op="meeting_crm", timeout=float(settings.meetings_crm_timeout),
                                            units={"chars": len(body["question"])})
    except AgentError as exc:
        log.warning("Yig'ilish %s: agent v4 CRM javob bermadi (%s) - bugungi yo'l", m.get("id"), exc.code)
        return None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    code = meta.get("error_code")
    proposals = [p for p in payload.get("proposals") or [] if isinstance(p, dict) and p.get("token")]
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    return llm_mod.V3Reply(text=str(payload.get("answer") or ""), proposals=proposals, sources=len(sources),
                           engine="v4", error={"code": str(code)} if code else None)


def call_consent(m: dict[str, Any]) -> dict[str, Any] | None:
    """Qo'ng'iroq yozuvining serverdagi rozilik belgisi (`None` - yo'q yoki qo'ng'iroq emas).
    Agentga (AI) ko'chirish yo'llari qo'ng'iroqni FAQAT shu belgi va egasining alohida qarori
    bilan yuboradi (migratsiya rejasi W5); bugun hamma agent yo'li qo'ng'iroqni o'tkazib yuboradi."""
    if str(m.get("source") or "") != "call" or not m.get("consent_at"):
        return None
    return {"at": int(m["consent_at"]), "version": m.get("consent_version")}


def crm_identity(user: AuthUser) -> tuple[str, dict[str, str]]:
    """CRM so'rovi uchun (`user_id`, FAQAT `crm` tokeni) - guruhdagi CRM qoidasi (`bot/runner.py`).

    NEGA `_live_tokens` EMAS: u odamning o'z ulanishi bo'lmasa umumiy `CrmAuth` hisobini va
    `.env` dagi HRM tokenini ham qo'shadi - vazifa so'ragan odam nomidan emas, umumiy hisobdan
    yaratilardi, "CRM ulanmagan" tekshiruvi hech qachon ishlamasdi, va yig'ilishdagi gap
    (iqtibos) agentga HRM ni ochardi. `MEETINGS_CRM_OWN_TOKENS=false` - o'z ulanishi bo'lmasa
    umumiy CRM hisobi (HRM baribir yo'q). Tasdiqlash (`/actions`, `_live_tokens`) ham odamning
    o'z CRM tokenini birinchi oladi - ikkalasi bir xil hisob."""
    from ...api.v1 import chat as _chat

    if settings.meetings_crm_own_tokens:
        tokens = _chat._connectors.hub.tokens(str(user.actorId)) if _chat.has_own_crm(user) else {}
    else:
        tokens = _chat._live_tokens(user)
    return _chat.assistant_user_id(user), {k: v for k, v in dict(tokens).items() if k == "crm"}


def questions(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    """Eski `/questions`: hisob egasining faol savol-javoblari, YANGISI birinchi ("Yangi suhbat" dan oldingilari va
    umumiy hisobdagi boshqa so'rovchilarniki - Slack - ko'rinmaydi)."""
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    by_id = {int(s["id"]): s for s in store.segments(m["id"])}
    return {"items": [_question_view(q, by_id) for q in store.questions(m["id"])]}


# --- 28. audio --------------------------------------------------------------------------------------------

_remux_lock = threading.Lock()


def audio_file(user: AuthUser, meeting_id: str, *, download: bool = False) -> tuple[Path, str, dict[str, str]]:
    """Tinglash uchun audio. `download` - ulashish uchun: o'sha fayl, lekin `attachment` va
    odamga tushunarli nom (`haftalik-reja-2026-10-10.m4a`) bilan - alohida endpoint shart emas."""
    m = _owned(user.actorId, meeting_id)
    path, media, headers = _audio_path(m)
    if download:
        recorded_at = float(m.get("recorded_at") or m.get("created_at") or 0)
        ascii_name, real_name = export.file_names(m.get("title") or default_title(recorded_at, "uz"), recorded_at,
                                                  audio.EXTENSIONS.get(media, ".aac").lstrip("."))
        # Shaxsiy yozuv: oraliq kesh (proksi) saqlab qolmasin - eksport fayli bilan bir xil.
        headers = {**headers, "Content-Disposition": export.content_disposition(ascii_name, real_name),
                   "Cache-Control": "private, no-store"}
    return path, media, headers


def _audio_path(m: dict[str, Any]) -> tuple[Path, str, dict[str, str]]:
    if not m.get("completed_at"):
        raise MeetingProblem(409, "not_ready", "Audio hali yuklanmagan")
    path = Path(m["audio_path"]) if m.get("audio_path") else None
    if m.get("audio_deleted_at") or path is None or not path.exists():
        raise MeetingProblem(410, "audio_expired", "Audio saqlash muddati tugagan")
    if (m.get("content_type") or "") in ("audio/mp4", "audio/mpeg", "audio/wav", "audio/ogg"):
        # m4a, mp3, wav, ogg - pleyer o'zi tinglaydi va istalgan joyga sakraydi; faqat ADTS m4a ga o'giriladi.
        return path, m["content_type"], {}
    cache = path.with_suffix(".m4a")
    if not cache.exists():
        with _remux_lock:
            if not cache.exists():
                try:
                    audio.adts_to_m4a(path, cache)
                except Exception as exc:                          # noqa: BLE001
                    log.info("Yig'ilish %s: remux bo'lmadi (%s) - asl fayl beriladi", m["id"],
                             type(exc).__name__)
                    return path, "audio/aac", {"X-Audio-Seekable": "false"}
    return cache, "audio/mp4", {}


def new_client_id() -> str:
    return str(uuid.uuid4())

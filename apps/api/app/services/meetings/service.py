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
from . import audio, dates, export, prompts, runtime, templates
from .errors import RETRYABLE, MeetingProblem, message_for, not_found
from .store import jdump, jload, new_id, private_file
from .summarize import LlmFailed, LlmRateLimited, LlmUnavailable
from .transcribe import language_warning
from .worker import delete_meeting

log = logging.getLogger(__name__)

LANGS = ("uz", "ru", "en")
ACCEPTED_TYPES = ("audio/aac", "audio/mp4")
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
        "error": error_view(m, now),
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


def create(user: AuthUser, body: Any, channel: str, now: float | None = None) -> tuple[dict[str, Any], bool]:
    now = time.time() if now is None else now
    store = runtime().store
    client_id = str(body.clientId).lower()
    existing = store.by_client(user.actorId, client_id)
    if existing is not None:
        return meeting_view(existing, now), False
    if body.contentType not in ACCEPTED_TYPES:
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
        "recorded_at": recorded, "content_type": body.contentType, "status": "uploading",
        "summary_status": "none", "created_at": int(now), "updated_at": int(now)}
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
        suffix = ".m4a" if content_type == "audio/mp4" else ".aac"
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


def list_meetings(user: AuthUser, *, limit: int, offset: int, q: str, status: str) -> dict[str, Any]:
    store = runtime().store
    if not store.exists:
        return {"items": [], "limit": limit, "offset": offset, "total": 0}
    rows, total = store.list_meetings(user.actorId, limit=limit, offset=offset, q=q, status=status)
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
            rt.gapi.cancel_job(m["stt_job_id"])
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
        # Odam tahrirlagan, qo'shgan yoki belgilagan (bajarildi / kerak emas) vazifalar qoladi.
        conn.execute("DELETE FROM action_items WHERE meeting_id=? AND origin='ai' AND edited=0 AND status='open'",
                     (m["id"],))
        conn.execute("UPDATE action_items SET source_ids='[]' WHERE meeting_id=?", (m["id"],))
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


def _require_transcript(m: dict[str, Any]) -> None:
    if not (int(m.get("transcript_rev") or 0) > 0 and m.get("stt_engine")
            and m.get("status") in ("summarizing", "ready")):
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
    clean = " ".join((name or "").split()) or None
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
    content = _map_merged(content, _merged_map(speakers)) if content else content
    return {**summary_card(s, m), "promptVersion": s["prompt_version"], "model": s.get("model") or "",
            "layout": templates.layout(s["template"], s["language"]),
            "speakers": [speaker_view(sp) for sp in speakers], "content": content}


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
    content = _map_merged(jload(s["content_json"], {}), _merged_map(list(speakers.values())))
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
            "createdAt": iso(a.get("created_at")), "updatedAt": iso(a.get("updated_at"))}


def _starts(meeting_id: str) -> dict[int, float]:
    return {int(r["id"]): round(float(r["start"]), 2) for r in
            runtime().store.rows("SELECT id, start FROM segments WHERE meeting_id=?", (meeting_id,))}


_STATUS_ORDER = {"open": 0, "done": 1, "dismissed": 2}


def action_items(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    m = _owned(user.actorId, meeting_id)
    starts = _starts(m["id"])
    items = sorted(runtime().store.action_items(m["id"]),
                   key=lambda a: (_STATUS_ORDER.get(a["status"], 3), a.get("due_date") or "9999-12-31",
                                  a.get("summary_item_id") is None, _item_number(a), a["created_at"], a["id"]))
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


# --- 26-27. savol-javob ------------------------------------------------------------------------------------


def _question_view(q: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    citations = []
    for sid in jload(q.get("citations"), []) or []:
        seg = by_id.get(int(sid))
        if seg:
            citations.append({"segmentId": int(sid), "start": round(float(seg["start"]), 2),
                              "speaker": seg.get("speaker"), "text": seg["text"]})
    return {"id": q["id"], "question": q["question"], "answer": q["answer"], "citations": citations,
            "followUps": jload(q.get("follow_ups"), []) or [], "createdAt": iso(q.get("created_at"))}


def ask(user: AuthUser, meeting_id: str, question: str, language: str | None) -> dict[str, Any]:
    rt = runtime()
    store = rt.store
    m = _owned(user.actorId, meeting_id)
    _require_transcript(m)
    _rate("ask", user.actorId, settings.meetings_ask_per_hour)
    segments = [{"id": int(s["id"]), "start": float(s["start"]), "end": float(s["end"]), "speaker": s["speaker"],
                 "text": s["text"]} for s in store.segments(m["id"])]
    speakers = [sp for sp in store.speakers(m["id"]) if not sp.get("merged_into")]
    primary = store.summary(m["id"], m["primary_summary_id"]) if m.get("primary_summary_id") else None
    summary = jload(primary.get("content_json")) if primary and primary["status"] == "ready" else None
    day = dates.tashkent(float(m.get("recorded_at") or 0))
    meta = prompts.meta_line(day.date(), dates.WEEKDAYS["en"][day.weekday()], float(m.get("duration_sec") or 0),
                             [{"id": sp["id"], "name": sp.get("name")} for sp in speakers],
                             bool(m.get("speakers_available")))
    from ..analytics import bind

    try:
        with bind(user.actorId):
            result = ask_mod.answer(rt.ask_llm, question=question, language=language or m.get("language") or "uz",
                                    meta=meta, segments=segments,
                                    speakers=[{"id": sp["id"], "name": sp.get("name")} for sp in speakers],
                                    summary=summary)
    except (LlmUnavailable, LlmFailed, LlmRateLimited):
        raise MeetingProblem(503, "llm_unavailable", "Model hozir javob bera olmayapti - keyinroq urinib ko'ring")
    qid = new_id()
    store.add_question({"id": qid, "meeting_id": m["id"], "question": question.strip()[:500],
                        "answer": result["answer"], "citations": jdump(result["citations"]),
                        "follow_ups": jdump(result["followUps"]), "created_at": int(time.time())})
    q = store.row("SELECT * FROM questions WHERE id=?", (qid,))
    return _question_view(q, {s["id"]: s for s in segments})


def questions(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    store = runtime().store
    m = _owned(user.actorId, meeting_id)
    by_id = {int(s["id"]): s for s in store.segments(m["id"])}
    return {"items": [_question_view(q, by_id) for q in store.questions(m["id"])]}


# --- 28. audio --------------------------------------------------------------------------------------------

_remux_lock = threading.Lock()


def audio_file(user: AuthUser, meeting_id: str) -> tuple[Path, str, dict[str, str]]:
    m = _owned(user.actorId, meeting_id)
    if not m.get("completed_at"):
        raise MeetingProblem(409, "not_ready", "Audio hali yuklanmagan")
    path = Path(m["audio_path"]) if m.get("audio_path") else None
    if m.get("audio_deleted_at") or path is None or not path.exists():
        raise MeetingProblem(410, "audio_expired", "Audio saqlash muddati tugagan")
    if (m.get("content_type") or "") == "audio/mp4":
        return path, "audio/mp4", {}
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

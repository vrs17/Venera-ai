"""Transkripsiya bosqichi (spetsifikatsiya 5.2 - 5.4).

O'ZBEK TILI - GAPI, spikerlar bilan. Asinxron vazifa: audio yuboriladi,
`202` + vazifa raqami, keyin holat so'raladi. Har QADAM - qisqa: bitta
yuborish yoki bitta so'rov; ishchi ipni bir soat band qilib turmaydi, holat
esa diskda (`stt_job_id`, `stt_submitted_at`) - xizmat qayta ishga tushsa
o'sha vazifa davom etadi va PUL QAYTA YECHILMAYDI.

    1. kvota      odamning va xizmatning kunlik daqiqasi, GAPI balansida zahira
    2. yuborish   `stt_submitted_at` POST DAN OLDIN, vazifa raqami 202 dan DARHOL KEYIN
    3. tiklash    POST va 202 orasida uzilgan bo'lsa - oxirgi vazifalardan topib olinadi
    4. so'rash    3 s (birinchi daqiqa), keyin 10 s; muddat `MEETINGS_STT_DEADLINE`
    5. natija     normallashtiriladi va BITTA tranzaksiyada saqlanadi

RUS / INGLIZ - ichki STT Router (spikersiz, vaqtlar taxminiy). GAPI faqat
o'zbekcha biladi; Router esa 600 s dan keyin kesadi - ADTS kadr chegarasida
540 s lik bo'laklarga bo'linadi. Uzun m4a (telefon qo'ng'irog'i yozuvi) avval
ADTS ga o'tkaziladi (`audio.mp4_to_adts`), keyin xuddi shunday bo'linadi.

O'ZBEKCHA HECH QACHON Router'ga TUSHMAYDI: u 300 s da kesadi va spiker
ajratmaydi - yig'ilish uchun bunday natija yolg'on xotirjamlik bo'lardi.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import tempfile
import threading
import time

from datetime import datetime
from pathlib import Path
from typing import Any

from ...core.config import settings
from ..analytics import bind, record_call
from ..integrations.gapi_stt import MeetingTranscript, meeting_settings, out_of_balance, parse_meeting_result
from ..stt import SttError
from . import audio, dates
from .errors import RETRYABLE
from .prompts import PROMPT_VERSION
from .store import jdump, new_id

log = logging.getLogger(__name__)

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
#: Vaqtinchalik xatolar uchun kutish (Retry-After bo'lmasa): 30 s, 2 daq, 10 daq.
BACKOFF = (30, 120, 600)
#: Shuncha vaqtinchalik xatodan keyin - `failed` (`internal`, qayta urinish mumkin).
MAX_RETRIES = 12
#: Router uchun bo'lak (s) va m4a chegarasi.
ROUTER_PIECE_SEC = 540
ROUTER_M4A_MAX_SEC = 590
#: mp3/wav bo'lagi baytda ham cheklanadi: Router 25 MB dan kattasini olmaydi (sifatli WAV 540 s da ~95 MB).
ROUTER_PIECE_BYTES = 20 * 1024 * 1024
#: O'Z slotimiz band (boshqa ip yuklayapti) - bu urinish EMAS, shuncha soniyadan keyin yana.
LOCAL_BUSY_WAIT = 5
#: Tiklash: vazifa yuborilgan paytdan shuncha oldin/keyin yaratilgan bo'lishi mumkin
#: (soat farqi / 150 MB yuklash vaqti).
ADOPT_BEFORE_SEC = 120
ADOPT_AFTER_SEC = 600

#: Kvota tekshiruvi + "yuborildi" belgisi BITTA qulf ostida: ikki ip bir vaqtda
#: tekshirib, ikkalasi ham "joy bor" deb yubormasin.
_SUBMIT_LOCK = threading.Lock()


class LeaseLost(Exception):
    """Ijara boshqa ipga o'tgan yoki yig'ilish o'chirilgan - eskirgan ip yozmaydi."""


def _local(exc: BaseException) -> bool:
    """Xato BIZNING tomonda (o'z slotimiz band) - GAPI/Router ga so'rov ketmagan."""
    return bool(getattr(exc, "local", False))


# --- normallashtirish (5.3) ---------------------------------------------------------


def _text_of(seg: dict[str, Any]) -> str:
    for key in ("text", "formatted_text", "raw_asr_text"):
        value = seg.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(_CONTROL.sub(" ", value).split())
    return ""


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def detected_language(raw: Any) -> dict[str, Any] | None:
    """`language` - obyekt (`{code, share}`), oddiy satr yoki yo'q."""
    if isinstance(raw, str) and raw.strip():
        return {"code": raw.strip().lower()[:8], "share": {}}
    if isinstance(raw, dict):
        code = raw.get("code") or raw.get("language") or raw.get("detected")
        share_raw = raw.get("share") or raw.get("shares") or raw.get("distribution") or {}
        share: dict[str, float] = {}
        if isinstance(share_raw, dict):
            for key, value in share_raw.items():
                number = _num(value)
                if number is not None:
                    share[str(key).lower()[:8]] = round(number, 3)
        if code or share:
            if not code and share:
                code = max(share, key=share.get)
            return {"code": str(code).lower()[:8] if code else None, "share": share}
    return None


def language_warning(detected: dict[str, Any] | None) -> str | None:
    """Yozuv asosan boshqa tilda bo'lsa - ilova rus/ingliz tilida qayta o'girishni taklif qiladi."""
    if not detected:
        return None
    code = detected.get("code")
    share = detected.get("share") or {}
    if (code and code != "uz") or ("uz" in share and share["uz"] < 0.5):
        return "mostly_other_language"
    return None


def normalize(result: MeetingTranscript) -> dict[str, Any]:
    """GAPI natijasi -> segmentlar (id 1..N), spikerlar (S1.. paydo bo'lish tartibida)."""
    raw = []
    for index, seg in enumerate(result.segments):
        text = _text_of(seg)
        if not text:
            continue
        start = _num(seg.get("start", seg.get("start_time")))
        end = _num(seg.get("end", seg.get("end_time")))
        start = round(max(0.0, start or 0.0), 2)
        end = round(max(end if end is not None else start, start), 2)
        raw.append((start, index, end, seg.get("speaker"), text))
    raw.sort(key=lambda r: (r[0], r[1]))
    labels: dict[str, str] = {}
    raw_index: dict[str, int | None] = {}
    segments, talk = [], {}
    for number, (start, _, end, speaker, text) in enumerate(raw, start=1):
        label = None
        if not result.diarization_error and speaker is not None and str(speaker).strip() != "":
            key = str(speaker)
            if key not in labels:
                labels[key] = f"S{len(labels) + 1}"
                found = re.search(r"\d+", key)
                raw_index[labels[key]] = int(found.group()) if found else None
            label = labels[key]
            talk[label] = talk.get(label, 0.0) + (end - start)
        segments.append({"id": number, "start": start, "end": end, "speaker": label, "text": text})
    speakers = [{"id": label, "rawIndex": raw_index.get(label), "talkSec": round(talk.get(label, 0.0), 2)}
                for label in labels.values()]
    detected = detected_language(result.language)
    return {
        "segments": segments, "speakers": speakers, "detected": detected,
        "languageWarning": language_warning(detected),
        "speakersAvailable": bool(not result.diarization_error and speakers),
    }


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.?!…])\s+", " ".join(str(text or "").split()))
    return [p for p in (x.strip() for x in parts) if p]


def router_segments(pieces: list[tuple[float, float, str]]) -> list[dict[str, Any]]:
    """(bo'lak boshi, davomiyligi, matn) -> taxminiy vaqtli segmentlar (5.4).

    Router vaqt bermaydi: jumla vaqti bo'lak ichida BELGI o'rniga mutanosib
    taqsimlanadi. Shuning uchun `timing='approximate'` va ilova bannerda aytadi."""
    out: list[dict[str, Any]] = []
    for start, duration, text in pieces:
        parts = sentences(text)
        total = sum(len(p) for p in parts) or 1
        offset = 0
        for part in parts:
            s = start + duration * offset / total
            offset += len(part)
            e = start + duration * offset / total
            out.append({"id": len(out) + 1, "start": round(s, 2), "end": round(e, 2), "speaker": None,
                        "text": part})
    return out


# --- ishchi bosqichi --------------------------------------------------------------------


def _created_epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) / (1000.0 if value > 1e11 else 1.0)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


class Transcriber:
    """Bitta yig'ilish uchun BITTA qadam. Holat faqat omborda."""

    def __init__(self, runtime: Any) -> None:
        self.rt = runtime

    # --- yordamchilar ---

    @property
    def store(self):
        return self.rt.store

    def _update(self, m: dict[str, Any], now: float, **fields: Any) -> None:
        self.store.update_meeting(m["id"], now=now, **fields)
        m.update(fields)

    def fail(self, m: dict[str, Any], now: float, code: str, *, stage: str = "transcribe") -> None:
        log.info("Yig'ilish %s: %s (%s)", m["id"], code, stage)
        self._update(m, now, status="failed", error_code=code, error_stage=stage, progress=None,
                     next_attempt_at=None)

    def park_quota(self, m: dict[str, Any], now: float, code: str, retry_at: float) -> None:
        self._update(m, now, status="waiting_quota", error_code=code, error_stage="quota", progress=None,
                     next_attempt_at=int(retry_at))

    def backoff(self, m: dict[str, Any], now: float, exc: SttError | None = None) -> None:
        retries = int(m.get("retries") or 0)
        if retries >= MAX_RETRIES:
            self.fail(m, now, "internal")
            return
        wait = getattr(exc, "retry_after", None) or BACKOFF[min(retries, len(BACKOFF) - 1)]
        self._update(m, now, retries=retries + 1, next_attempt_at=int(now + float(wait)))

    def _meter(self, m: dict[str, Any], status: str, *, http: int | None = None, error: Any = None,
               units: dict[str, Any] | None = None, op: str = "meeting", service: str = "stt_gapi",
               started: float | None = None, now: float | None = None) -> None:
        duration = max(0.0, ((now or time.time()) - started) * 1000) if started else 0
        record_call(service, op, status=status, http_status=http, units=units, error=error,
                    duration_ms=duration, actor_id=m["actor_id"], channel=m.get("channel") or "mobile")

    # --- kirish nuqtasi ---

    def step(self, m: dict[str, Any], now: float, owner: str | None = None) -> None:
        """`owner` - ishchi ipining ijarasi: uzun ish (Router bo'laklari) davomida
        yangilanadi, yakuniy yozuv faqat ijara SHU ipda bo'lsa bajariladi."""
        if not m.get("audio_path") or not Path(m["audio_path"]).exists():
            self.fail(m, now, "audio_unreadable")
            return
        duration = float(m.get("duration_sec") or 0)
        if duration > settings.meetings_max_minutes * 60 + 30:
            self.fail(m, now, "too_long", stage="upload")
            return
        with bind(m["actor_id"], m.get("channel") or "mobile"):
            if m.get("language") in ("ru", "en"):
                self._router(m, now, owner)
            else:
                self._gapi(m, now, owner)

    def _renew(self, m: dict[str, Any], owner: str | None) -> None:
        if owner is None:
            return
        from .worker import LEASE_SEC

        if not self.store.renew(m["id"], owner, time.time() + LEASE_SEC):
            raise LeaseLost()

    # --- GAPI (o'zbekcha) ---

    def _quota(self, m: dict[str, Any], now: float) -> int | None:
        """Qaysi GAPI hisobi bilan yuborish mumkin (1 - `GAPI_API_KEY`, 2 - `GAPI_API_KEY2`);
        `None` - yig'ilish navbatga qo'yildi.

        Sarf = tugagan vazifalar (`quota_days`) + YUBORILGAN-u natijasi kelmaganlar. Xizmat
        ulushi har kalit uchun, hisob esa tartib bilan: birinchisida balans yetmasa - ikkinchisi."""
        minutes = math.ceil(float(m.get("duration_sec") or 0) / 60.0)
        day = dates.day_key(now)
        service_cap = settings.meetings_gapi_daily_minutes * max(1, len(self.rt.gapi.accounts))
        for code, actor, cap in (("quota_user", m["actor_id"], settings.meetings_user_daily_minutes),
                                 ("quota_service", None, service_cap)):
            done = self.store.used_sec(day, 0 if actor is None else actor) / 60.0
            if done + minutes > cap:
                self.park_quota(m, now, code, dates.next_reset(now))
                return None
            if done + self.store.inflight_minutes(actor, exclude=m["id"]) + minutes > cap:
                # Faqat YO'LDAGI vazifalar tufayli to'lgan - ular tugagach joy qolishi
                # mumkin (haqiqiy audio qisqaroq): ertagacha emas, 10 daqiqa kutamiz.
                self.park_quota(m, now, code, now + 600)
                return None
        for account in self.rt.gapi.usable_accounts():
            try:
                usage = self.rt.gapi.usage(account=account)
            except SttError as exc:
                # Balansni bilib bo'lmadi - TO'XTATMAYMIZ: kunlik ulush yuqorida
                # tekshirildi, balans so'rovi esa faqat qo'shimcha to'r.
                log.info("GAPI balansi o'qilmadi: %s", exc)
                return account
            available = _num(usage.get("available_g"))
            if available is None or available - minutes >= settings.meetings_gapi_reserve_minutes:
                return account
        self.park_quota(m, now, "quota_service", now + 30 * 60)
        return None

    def _gapi(self, m: dict[str, Any], now: float, owner: str | None = None) -> None:
        if not self.rt.gapi.configured:
            self.fail(m, now, "stt_not_configured")
            return
        if m.get("stt_job_id"):
            self._poll(m, now, owner)
            return
        if m.get("stt_submitted_at") and m.get("status") == "transcribing":
            # POST yuborilgan, 202 kelmagan (yiqilish yoki uzilish): vazifa
            # GAPI da bor bo'lishi mumkin - qayta yuborish ikki marta pul.
            if self._adopt(m, now):
                return
            if int(m.get("attempts") or 0) >= 2:
                self.fail(m, now, "internal")
                return
        with _SUBMIT_LOCK:
            account = self._quota(m, now)
            if account is None:
                return
            # POST DAN OLDIN (va kvota qulfi ostida): yiqilsak, keyingi qadam
            # "yuborilganmi?" deb so'raydi; parallel ip esa buni "yo'lda" deb hisoblaydi.
            self._update(m, now, status="transcribing", stt_engine="gapi", stt_submitted_at=int(now),
                         stt_account=account, attempts=int(m.get("attempts") or 0) + 1, progress=5.0,
                         error_code=None, error_stage=None)
        self._submit(m, now)

    def _adopt(self, m: dict[str, Any], now: float) -> bool:
        """POST va 202 orasida uzilgan yuborishni GAPI ro'yxatidan topish.

        KALIT UMUMIY - ro'yxatda HAMMA odamlarning vazifalari bor. Shuning uchun
        faqat aniq bitta nomzod olinadi: yaratilgan vaqti yuborish oynasida,
        `estimated_seconds` BOR va davomiylikka ±2 s mos, va boshqa yig'ilishga
        bog'lanmagan. Shubha bo'lsa - qayta yuboriladi (eng ko'pi 2 urinish):
        ikki marta to'lash begona odamning transkriptini berishdan yaxshiroq."""
        try:
            jobs = self.rt.gapi.list_jobs(limit=20, account=int(m.get("stt_account") or 1))
        except SttError as exc:
            log.info("GAPI vazifalari ro'yxati o'qilmadi: %s", exc)
            self.backoff(m, now, exc)
            return True
        submitted = float(m["stt_submitted_at"])
        duration = float(m.get("duration_sec") or 0)
        taken = self.store.job_ids_in_use(exclude=m["id"])
        candidates = []
        for job in jobs:
            job_id = str(job.get("id") or "")
            created = _created_epoch(job.get("created_at"))
            estimated = _num(job.get("estimated_seconds"))
            if not job_id or job_id in taken or created is None or estimated is None:
                continue
            if not (submitted - ADOPT_BEFORE_SEC <= created <= submitted + ADOPT_AFTER_SEC):
                continue
            if abs(estimated - duration) > 2:
                continue
            candidates.append(job)
        if len(candidates) != 1:
            if candidates:
                log.info("Yig'ilish %s: tiklash uchun %d nomzod - qayta yuboriladi", m["id"], len(candidates))
            return False
        job = candidates[0]
        log.info("Yig'ilish %s: uzilgan yuborish tiklandi (vazifa topildi)", m["id"])
        self._update(m, now, stt_job_id=str(job["id"]), stt_result_url=job.get("result_url"),
                     stt_deadline_at=int(now + settings.meetings_stt_deadline), next_attempt_at=int(now + 3))
        return True

    def _submit(self, m: dict[str, Any], now: float) -> None:
        path = Path(m["audio_path"])
        account = int(m.get("stt_account") or 1)
        try:
            job = self.rt.gapi.submit_job(path, m.get("content_type") or "audio/aac",
                                          meeting_settings(m.get("expected_speakers")), account=account)
        except SttError as exc:
            if _local(exc):
                # O'z slotimiz band - so'rov KETMAGAN: belgi va urinish qaytariladi.
                self._update(m, now, stt_submitted_at=None, attempts=max(0, int(m.get("attempts") or 1) - 1),
                             next_attempt_at=int(time.time() + LOCAL_BUSY_WAIT))
                return
            self._meter(m, "error", http=getattr(exc, "gapi_status", None), error=exc,
                        units={"bytes": path.stat().st_size}, op="meeting.submit")
            if getattr(exc, "gapi_status", None) is not None:
                # Javob keldi - vazifa YARATILMAGAN, qayta yuborish xavfsiz.
                self._update(m, now, stt_submitted_at=None)
            if out_of_balance(exc):
                self.rt.gapi.mark_out_of_balance(account)
                if self.rt.gapi.usable_accounts():
                    # Boshqa kalitda balans bor - navbatda kutmasdan o'shanga (`_quota` tanlaydi).
                    # Vazifa yaratilmagan: urinish sanalmaydi.
                    self._update(m, now, attempts=max(0, int(m.get("attempts") or 1) - 1),
                                 next_attempt_at=int(now + 2))
                    return
            self._error(m, now, exc, polling=False)
            return
        # 202 DAN DARHOL KEYIN: vazifa raqami diskda - endi hech qachon qayta yuborilmaydi.
        self._update(m, now, stt_job_id=job["id"], stt_result_url=job.get("resultUrl"),
                     stt_deadline_at=int(now + settings.meetings_stt_deadline), retries=0,
                     next_attempt_at=int(now + 3))

    def _poll(self, m: dict[str, Any], now: float, owner: str | None = None) -> None:
        deadline = m.get("stt_deadline_at") or ((m.get("stt_submitted_at") or now) + settings.meetings_stt_deadline)
        if now > float(deadline):
            self.fail(m, now, "stt_timeout")
            return
        account = int(m.get("stt_account") or 1)
        try:
            job = self.rt.gapi.get_job(m["stt_job_id"], account=account)
        except SttError as exc:
            self._error(m, now, exc, polling=True)
            return
        state = str(job.get("state") or "")
        if state in ("failed", "cancelled", "canceled", "error"):
            self._meter(m, "error", error=f"job {state}", started=m.get("stt_submitted_at"), now=now)
            self.fail(m, now, "stt_rejected")
            return
        if state != "done":
            done = _num(job.get("progress_seconds")) or 0.0
            total = _num(job.get("audio_seconds")) or float(m.get("duration_sec") or 0) or 1.0
            progress = 5.0 + 75.0 * max(0.0, min(1.0, done / total))
            started = float(m.get("stt_submitted_at") or now)
            wait = 3 if now - started < 60 else 10
            self._update(m, now, status="transcribing", progress=round(progress, 1),
                         next_attempt_at=int(now + wait))
            return
        try:
            payload = self.rt.gapi.get_result(m["stt_job_id"], m.get("stt_result_url"), account=account)
        except SttError as exc:
            if getattr(exc, "gapi_status", None) == 409 or getattr(exc, "gapi_code", "") == "result_not_ready":
                self._update(m, now, next_attempt_at=int(now + 2))
                return
            self._error(m, now, exc, polling=True)
            return
        result = parse_meeting_result(payload)
        audio_sec = result.audio_seconds or float(m.get("duration_sec") or 0)
        normalized = normalize(result)
        self.store.add_usage(dates.day_key(now), m["actor_id"], audio_sec)
        self.rt.gapi.note_meeting_audio(audio_sec)
        self._meter(m, "ok", http=200, started=m.get("stt_submitted_at"), now=now,
                    units={"bytes": int(m.get("total_bytes") or 0), "audioSec": round(audio_sec, 1)})
        log.info("Yig'ilish %s: GAPI natijasi - %d segment, %d spiker, %.1f s audio",
                 m["id"], len(normalized["segments"]), len(normalized["speakers"]), audio_sec)
        self.finish(m, now, normalized, engine="gapi", timing="exact", audio_sec=audio_sec, owner=owner)

    def _error(self, m: dict[str, Any], now: float, exc: SttError, *, polling: bool) -> None:
        status = getattr(exc, "gapi_status", None)
        code = getattr(exc, "gapi_code", "") or ""
        if _local(exc):
            self._update(m, now, next_attempt_at=int(time.time() + LOCAL_BUSY_WAIT))
        elif exc.status == 501:
            self.fail(m, now, "stt_not_configured")
        elif polling and status in (404, 410):
            self.fail(m, now, "stt_job_lost")
        elif status in (401, 403):
            self.rt.note_auth_failure(now)
            self.fail(m, now, "stt_auth")
        elif status == 429 and code == "insufficient_balance":
            self.park_quota(m, now, "quota_service", now + 30 * 60)
        elif status == 422:
            self.fail(m, now, "audio_unreadable")
        elif status in (400, 413):
            self.fail(m, now, "stt_rejected")
        else:
            # 429 (chegara), 409, 5xx, tarmoq - kutib qayta urinish.
            self.backoff(m, now, exc)

    # --- Router (ru/en) ---

    def _router(self, m: dict[str, Any], now: float, owner: str | None = None) -> None:
        content_type = m.get("content_type") or "audio/aac"
        path = Path(m["audio_path"])
        duration = float(m.get("duration_sec") or 0)
        tmp = Path(tempfile.mkdtemp(prefix="vmeet-", dir=str(path.parent)))
        try:
            source, piece_type = path, content_type
            if content_type == "audio/mp4" and duration > ROUTER_M4A_MAX_SEC:
                # Uzun m4a (telefon qo'ng'irog'i yozuvi, "Ulashish") Router'ga bir so'rovda sig'maydi:
                # AAC kadrlari ADTS ga o'tkazilib, oddiy yozuvdek bo'laklanadi. AAC bo'lmasa - avvalgidek xato.
                source, piece_type = tmp / "whole.aac", "audio/aac"
                try:
                    audio.mp4_to_adts(path, source)
                except (audio.RemuxError, OSError) as exc:
                    log.info("Yig'ilish %s: m4a ni bo'lib bo'lmadi (%s)", m["id"], exc)
                    self.fail(m, now, "router_too_long")
                    return
            self._update(m, now, status="transcribing", stt_engine="router", progress=5.0, error_code=None,
                         error_stage=None)
            if piece_type == "audio/mp4":
                pieces = [(path, 0.0, duration)]
            elif piece_type in ("audio/mpeg", "audio/wav", "audio/ogg"):
                # mp3 - kadr, wav - blok, ogg - sahifa chegarasida; bo'lak Router chegarasidan (bayt) ham oshmaydi.
                splitter = audio.split_ogg if piece_type == "audio/ogg" else (
                    lambda *a, **kw: audio.split_plain(a[0], piece_type, *a[1:], **kw))
                pieces, offset = [], 0.0
                for piece, length in splitter(source, ROUTER_PIECE_SEC, tmp, max_bytes=ROUTER_PIECE_BYTES):
                    pieces.append((piece, offset, length))
                    offset += length
            else:
                pieces, offset = [], 0.0
                for piece in audio.split_adts(source, ROUTER_PIECE_SEC, tmp):
                    info = audio.adts_info(piece)
                    length = info.durationSec if info else 0.0
                    pieces.append((piece, offset, length))
                    offset += length
            texts: list[tuple[float, float, str]] = []
            for index, (piece, start, length) in enumerate(pieces, start=1):
                data = piece.read_bytes()
                started = time.time()
                try:
                    result = self.rt.router.transcribe(data, language=m["language"], content_type=piece_type)
                except SttError as exc:
                    if _local(exc):
                        # Chat diktovkasi bilan umumiy emas, lekin boshqa ip Router'da - kutamiz, urinish emas.
                        self._update(m, now, next_attempt_at=int(time.time() + LOCAL_BUSY_WAIT))
                        return
                    self._meter(m, "error", http=exc.status, error=exc, service="stt_router",
                                units={"bytes": len(data)}, started=started)
                    if exc.retryable or exc.status in (502, 503, 504):
                        # Kutish HOZIRDAN: 20 bo'lakli yozuvda qadam boshidagi `now` ancha eskirgan.
                        self.backoff(m, time.time(), exc)
                    else:
                        self.fail(m, now, "stt_rejected")
                    return
                self._meter(m, "ok", http=200, service="stt_router", started=started,
                            units={"bytes": len(data), "audioSec": round(length, 1)})
                texts.append((start, length, result.text))
                self._update(m, now, progress=round(5.0 + 75.0 * index / len(pieces), 1))
                # Har bo'lakdan keyin ijara yangilanadi: 3 soatlik yozuv = 20 bo'lak.
                self._renew(m, owner)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        normalized = {"segments": router_segments(texts), "speakers": [], "detected": None,
                      "languageWarning": None, "speakersAvailable": False}
        self.finish(m, now, normalized, engine="router", timing="approximate", audio_sec=duration, owner=owner)

    # --- yakun: transkript saqlanadi, asosiy xulosa navbatga ---

    def finish(self, m: dict[str, Any], now: float, normalized: dict[str, Any], *, engine: str, timing: str,
               audio_sec: float, owner: str | None = None) -> None:
        """Transkript + asosiy xulosa navbati BITTA tranzaksiyada, faqat yig'ilish hali
        `transcribing` va (ishchida) ijara SHU ipda bo'lsa. Eskirgan ip yozmaydi:
        aks holda transkript ikki marta almashib, ikkinchi "asosiy" xulosa ham
        navbatga tushardi (ikki barobar model xarajati)."""
        sid = new_id()
        template = m.get("template") or "auto"
        summary = {"id": sid, "meeting_id": m["id"], "template": template, "requested_template": template,
                   "language": m.get("language") or "uz", "prompt_version": PROMPT_VERSION, "status": "queued",
                   "created_at": int(now)}
        rev = self.store.replace_transcript(
            m["id"], normalized["segments"], normalized["speakers"], guard_owner=owner,
            guard_status=("uploaded", "transcribing", "waiting_quota"),
            summary=summary,
            stt_engine=engine, timing=timing, speakers_available=1 if normalized["speakersAvailable"] else 0,
            detected_lang=jdump(normalized["detected"]), stt_audio_sec=round(audio_sec, 2),
            progress=80.0, error_code=None, error_stage=None, retries=0, next_attempt_at=None,
            status="summarizing", primary_summary_id=sid, summary_status="queued")
        if rev is None:
            log.info("Yig'ilish %s: transkript yozilmadi - ijara yoki holat o'zgargan", m["id"])
            raise LeaseLost()
        m.update(transcript_rev=rev, status="summarizing", primary_summary_id=sid, summary_status="queued")


def retryable(code: str | None) -> bool:
    return bool(code) and code in RETRYABLE


def describe(payload: Any) -> str:
    """Jonli tekshiruv uchun: natijaning kalitlari (matnsiz)."""
    if not isinstance(payload, dict):
        return type(payload).__name__
    return json.dumps(sorted(payload.keys()))

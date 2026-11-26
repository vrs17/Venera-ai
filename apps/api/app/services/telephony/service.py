"""Telefoniya xizmati: qo'ng'iroq boshlash, FreePBX natijasini qabul qilish, holatlar.

NATIJA ENDPOINT'I QOIDALARI (FreePBX admini bilan kelishilgan):
  * kalit to'g'ri bo'lsa DOIM 2xx: notanish yoki kech kelgan call_id ham, buzilgan so'rov ham qabul qilinadi
    va `call_events` ga yoziladi. Boshqa 4xx da FreePBX natijani 24 soat har daqiqada qayta yuboradi;
  * takroriy natija - 409 (FreePBX buni «yetkazildi» deb tushunadi va qayta yubormaydi);
  * `unknown` yakuniy emas - kech kelgan natija holatni yangilaydi;
  * qayta urinish - har doim YANGI call_id (eskisi FreePBX'da 409 oladi).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ...core.config import settings
from . import freepbx
from .store import CallStore

log = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^[1-9][0-9]{8}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: FreePBX `failed` natijasidagi Asterisk sababi (`${REASON}`) -> natija.
FAILED_REASONS = {"0": "failed", "1": "rejected", "3": "no_answer", "5": "busy", "8": "congestion"}


class TelephonyUnavailable(Exception):
    """Qo'ng'iroq boshlash o'chiq yoki sozlanmagan (503)."""


class TelephonyLimit(Exception):
    """Chegara (429)."""


class InvalidPhone(ValueError):
    pass


_store: CallStore | None = None
_store_lock = threading.Lock()


def store() -> CallStore:
    """Modul darajasidagi ombor (yo'l sozlamadan; testlar `reset_store()` bilan almashtiradi)."""
    global _store
    with _store_lock:
        if _store is None or _store.path != Path(settings.telephony_calls_db):
            _store = CallStore(settings.telephony_calls_db)
        return _store


def reset_store() -> None:
    global _store
    with _store_lock:
        _store = None


def mask_phone(phone: str) -> str:
    """Jurnal uchun: `901234567` -> `90*****67`."""
    return phone[:2] + "*" * max(0, len(phone) - 4) + phone[-2:] if len(phone) > 4 else "***"


def normalize_phone(raw: str) -> str:
    """`+998 90 123-45-67` / `998901234567` / `901234567` -> `901234567`; noto'g'ri bo'lsa `InvalidPhone`."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("998"):
        digits = digits[3:]
    if not PHONE_RE.match(digits):
        raise InvalidPhone("Raqam 9 xonali bo'lishi kerak (masalan 901234567 yoki +998 90 123 45 67)")
    return digits


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------- holat

def configured() -> bool:
    return bool(settings.telephony_call_live_url and settings.telephony_call_live_token
                and freepbx.normalize_fingerprint(settings.telephony_call_live_cert_sha256))


def status() -> dict[str, Any]:
    """Panel uchun: qo'ng'iroq boshlash mumkinmi va oxirgi 24 soatda nechtasi ishlatilgan."""
    return {"enabled": bool(settings.telephony_enabled), "configured": configured(),
            "dailyCap": max(0, int(settings.telephony_daily_cap)), "used24h": store().count_since(_now() - 24 * 3600)}


# ---------------------------------------------------------------------------- qo'ng'iroq boshlash

def place_call(phone_raw: str, *, actor_id: int | None, note: str = "") -> dict[str, Any]:
    """Mijozga qo'ng'iroq boshlaydi. Qaytadi: qo'ng'iroq yozuvi (holati `queued`, `rejected` yoki `unknown`)."""
    phone = normalize_phone(phone_raw)
    if not settings.telephony_enabled:
        raise TelephonyUnavailable("Telefoniya o'chirilgan")
    if not configured():
        raise TelephonyUnavailable("Telefoniya sozlanmagan")
    calls = store()
    now = _now()
    if calls.count_since(now - 24 * 3600) >= max(0, int(settings.telephony_daily_cap)):
        raise TelephonyLimit("Kunlik qo'ng'iroqlar chegarasi tugadi")
    call_id = str(uuid.uuid4())
    calls.create(call_id, phone, actor_id, note.strip()[:200], now)
    answer = freepbx.place(settings.telephony_call_live_url, settings.telephony_call_live_token,
                           settings.telephony_call_live_cert_sha256, call_id=call_id, phone=phone,
                           timeout=float(settings.telephony_call_live_timeout))
    if answer.status == 202:
        status = "queued"
    elif answer.status == 0 and answer.sent:
        status = "unknown"              # so'rov ketdi, javob kelmadi - qo'ng'iroq bo'lgan bo'lishi mumkin
    else:
        status = "rejected"
    calls.mark_placed(call_id, status=status, http_status=answer.status or None, detail=answer.detail, now=_now())
    log.info("Telefoniya: %s -> %s (%s, HTTP %s %s, admin %s)", call_id[:8], status, mask_phone(phone),
             answer.status, answer.detail, actor_id)
    if answer.detail == "cert_mismatch":
        log.warning("Telefoniya: FreePBX sertifikati kutilgan barmoq iziga mos EMAS - token yuborilmadi")
    if status == "unknown" and int(settings.telephony_unknown_retry_sec) > 0:
        timer = threading.Timer(int(settings.telephony_unknown_retry_sec), _retry_safely, args=(call_id,))
        timer.daemon = True
        timer.start()
    return calls.get(call_id)


def _retry_safely(call_id: str) -> None:
    try:
        retry_unknown(call_id)
    except Exception:  # noqa: BLE001 - fon ishi: xato jurnalga, API'ga ta'sir qilmaydi
        log.exception("Telefoniya: %s - qayta yuborishda xato", call_id[:8])


def retry_unknown(call_id: str) -> str | None:
    """Javobsiz qolgan so'rovni XUDDI SHU call_id bilan bir marta qayta yuboradi. Qaytadi: yangi holat yoki None.

    409 - birinchi so'rov yetib borgan, qo'ng'iroq ketgan; 202 - birinchisi yetmagan, qo'ng'iroq endi ketdi. Ikkalasida
    ham natija keyin `call-result` ga keladi. Boshqa javob - holat `unknown` qoladi (sababi `retry_failed:...`).
    """
    calls = store()
    if not calls.claim_retry(call_id):
        return None                     # natija kelgan yoki allaqachon qayta yuborilgan
    call = calls.get(call_id)
    answer = freepbx.place(settings.telephony_call_live_url, settings.telephony_call_live_token,
                           settings.telephony_call_live_cert_sha256, call_id=call_id, phone=call["phone"],
                           timeout=float(settings.telephony_call_live_timeout))
    if answer.status in (202, 409):
        status, detail = "queued", "retry_accepted" if answer.status == 202 else "retry_duplicate"
    else:
        status, detail = "unknown", f"retry_failed:{answer.status or answer.detail}"[:80]
    calls.mark_placed(call_id, status=status, http_status=answer.status or None, detail=detail, now=_now())
    log.info("Telefoniya: %s - qayta yuborildi -> %s (HTTP %s)", call_id[:8], detail, answer.status)
    return status


# ---------------------------------------------------------------------------- FreePBX natijasi

def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _epoch(value: Any) -> int | None:
    """FreePBX vaqti -> epoch soniya. Kontraktda ISO 8601 UTC (`2025-11-25T10:00:00Z`); son ham qabul qilinadi."""
    number = _int(value)
    if number is not None:
        return number
    try:
        return int(dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def _text(value: Any, limit: int = 64) -> str | None:
    return None if value in (None, "") else str(value)[:limit]


def result_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """FreePBX natijasi -> ombor ustunlari (holat va natija shu yerda aniqlanadi)."""
    if payload.get("event") == "failed":
        reason = str(payload.get("reason", "")).strip()
        return {"status": "failed", "outcome": FAILED_REASONS.get(reason, "failed"),
                "uniqueid": _text(payload.get("uniqueid"))}
    gateway = _text(payload.get("gateway_status"))
    # gateway_status - FreePBX'dagi `Dial(SIP/barno-gw/...)` natijasi: ANSWER - mijoz Barno bilan gaplashdi;
    # boshqasi - mijoz javob berdi, lekin shlyuz/bridge ulanmadi (u uzr yozuvini eshitdi); yo'q - noma'lum.
    outcome = ("talked" if gateway.upper() == "ANSWER" else "gateway_failed") if gateway else ""
    return {"status": "completed", "outcome": outcome,
            "answer_time": _epoch(payload.get("answer_time")), "end_time": _epoch(payload.get("end_time")),
            "talk_sec": _int(payload.get("talk_sec")), "gateway_status": gateway,
            "hangup_cause": _text(payload.get("hangup_cause")), "uniqueid": _text(payload.get("uniqueid"))}


def record_result(payload: Any, *, caller: str, raw: str) -> tuple[int, dict[str, Any]]:
    """FreePBX natijasi -> (HTTP kodi, javob). Kalit tekshirilgan bo'ladi (endpoint'da)."""
    calls = store()
    now = _now()
    call_id = event = None
    if isinstance(payload, dict):
        call_id = str(payload.get("call_id") or "").strip().lower() or None
        event = payload.get("event")
    if not call_id or event not in ("failed", "answered"):
        calls.add_event(call_id=call_id, event=str(event)[:16] if event else None, verdict="invalid_payload",
                        caller=caller, payload=raw, now=now)
        log.warning("Telefoniya: FreePBX'dan tushunarsiz natija keldi (%s) - saqlandi", caller)
        return 200, {"ok": True, "status": "invalid_payload"}
    if not UUID_RE.match(call_id):
        verdict = "unknown_call"
    else:
        previous = calls.get(call_id)
        verdict = calls.apply_result(call_id, result_fields(payload), json.dumps(payload, ensure_ascii=False)[:8192],
                                     now)
        if verdict == "recorded" and previous and previous["status"] == "unknown":
            log.info("Telefoniya: %s - kech kelgan natija qabul qilindi", call_id[:8])
    calls.add_event(call_id=call_id, event=event, verdict=verdict, caller=caller, payload=raw, now=now)
    if verdict == "duplicate":
        return 409, {"ok": True, "status": "duplicate"}
    if verdict == "unknown_call":
        log.warning("Telefoniya: notanish call_id uchun natija (%s) - saqlandi", call_id[:8])
    else:
        log.info("Telefoniya: %s - natija %s", call_id[:8], event)
    return 200, {"ok": True, "status": verdict}


# ---------------------------------------------------------------------------- ko'rish

def _sweep() -> None:
    minutes = max(1, int(settings.telephony_unknown_after_min))
    cutoff = _now() - minutes * 60
    store().mark_stale_unknown(placed_before=cutoff, created_before=cutoff)


def bridge_record(call_id: str) -> dict[str, Any] | None:
    """Bridge qaydidan qisqa ma'lumot: Speko sessiyasi, davomiylik, narx, tugash sababi (matnsiz)."""
    root = (settings.telephony_bridge_dir or "").strip()
    if not root or not UUID_RE.match(call_id):
        return None
    for path in sorted(Path(root).glob(f"calls/*/{call_id}.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        report = data.get("agentReport") or {}
        return {"endReason": data.get("endReason"), "seconds": data.get("seconds"),
                "sessionId": report.get("sessionId"), "agentSeconds": report.get("durationSeconds"),
                "costUsd": report.get("totalCostUsd"), "agentEndReason": report.get("endReason")}
    return None


def list_calls(limit: int = 50) -> list[dict[str, Any]]:
    _sweep()
    return store().recent(max(1, min(int(limit), 200)))


def get_call(call_id: str) -> dict[str, Any] | None:
    _sweep()
    call = store().get(call_id.lower())
    if call is None:
        return None
    call["events"] = store().events(call["call_id"])
    call["bridge"] = bridge_record(call["call_id"])
    return call

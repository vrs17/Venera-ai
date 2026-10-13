"""Admin panel: "Tizim xaritasi" sinovlari - qadamni JONLI serverda, AYNI kod bilan. FAQAT ADMIN.

    POST /admin/probe/stt              audio -> matn: `/stt/transcribe` dagi AYNI `_pick`,
                                       GAPI/Router klientlari va zahira (`_transcribe_with_fallback`)
    POST /admin/probe/tts-text         matn -> TTS ga AYNAN ketadigan matn, har bosqichdan keyin
                                       (`TtsClient.prepare` -> `prepare_speech`, `/tts/speak` ham shu)
    POST /admin/probe/wake             eshitilgan matn -> uyg'otish qarori (`wake.is_wake_phrase`)
    POST /admin/probe/hold             savol -> kutish ovozi tanlovi (`hold.keyword_topic`, `pick`),
                                       `use_llm` bo'lsa gemma tasnifi ham
    POST /admin/probe/mask             matn -> modelga ketadigan niqoblangan matn (`mask_text`)
    GET  /admin/probe/agent            agent v4 `/capabilities` va `/limits` - faqat o'qish
    GET  /admin/probe/health           `/api/health/detail` dagi AYNI tashxis, qismlar vaqti bilan
    POST /admin/probe/brain/{feature}  miya funksiyasi: modelga ketadigan prompt va agent tanasi
                                       (DRY, model chaqirilmaydi); `execute: true` - model bilan

NEGA. Egasi butun tizimni n8n kabi xaritada ko'radi va istalgan qadamni bosib, uni
shu yerning o'zida sinab ko'rmoqchi: "bu qadam hozir nima qiladi va qancha vaqt
oladi". Shuning uchun QOIDALAR qat'iy:

  * Sinov ishlab chiqarish kodini CHAQIRADI, nusxalamaydi. Kerak bo'lgan joyda
    ishlab chiqarish funksiyasiga ixtiyoriy `trace` qo'shildi (xulq o'zgarmagan) -
    nusxa vaqt o'tib asl yo'ldan ajralib, noto'g'ri narsani "to'g'ri" deb ko'rsatardi.
  * CRM/HRM ga HECH QACHON yozmaydi, Telegram'ga yubormaydi, suhbat saqlamaydi.
    Guruh va brif sinovi vaqtinchalik ombor (o'chiriladi) va "soxta Telegram"
    (hech narsa yubormaydi) ustida ishlaydi; CRM taklifi yaratadigan yoki
    yuqoridagi xizmatda suhbat saqlaydigan funksiyalar `execute` da 409 qaytaradi.
  * Har sinov jurnalga va admin auditiga (`probe.run`) yoziladi - kim va qaysi sinov.
    Kiritilgan matn YOZILMAYDI (u xodim savoli yoki guruh yozishmasi bo'lishi mumkin).
  * Javob shakli bitta: `{ok, trace: [{step, ms, detail}], result, cost_note}`.

Huquq router darajasida (`admin.py` dagi sabab bilan). `async def` EMAS: STT, TTS,
SQLite va model chaqiruvlari bloklaydi - FastAPI ularni threadpool'da ishlatadi.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import tempfile
import threading
import time

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path as FsPath
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile

from ...core import config as _config
from ...core.config import settings
from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.probe import BrainProbe, HoldProbe, MaskProbe, ProbeResult, TtsTextProbe, WakeProbe
from ...schemas.tts import CLIP_MAX_CHARS
from ...services import admin_users as _admin
from ...services import brain as _brain
from ...services import engine_control as _control
from ...services import hold as _hold
from ...services import tg_groups as _groups
from ...services import wake as _wake
from ...services.analytics.db import get_db
from ...services.brain import routing as _routing
from ...services.integrations.agent_v4 import AgentError
from ...services.stt import LOCALE_TO_STT, SttError, safe_filename
from ...services.tts import LOCALE_TO_TTS, TtsError
from ..deps import require_roles
from . import chat as _chat
from . import stt as _stt
from . import tts as _tts

log = logging.getLogger(__name__)

admin_only = require_roles("ADMIN")

router = APIRouter(prefix="/admin/probe", tags=["admin"], dependencies=[Depends(admin_only)])


# --- umumiy -----------------------------------------------------------------------------------


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000.0, 1)


class _Trace:
    """Qadamlar ro'yxati: har qadam - nomi, vaqti (ms) va tafsiloti."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.started = time.monotonic()

    @contextmanager
    def step(self, name: str, **detail: Any) -> Iterator[dict[str, Any]]:
        """Blok vaqtini o'lchaydi; blok ichida `detail` ga qo'shiladi. Xato bo'lsa ham
        qadam yoziladi - qaysi qadamda to'xtagani ko'rinsin."""
        box: dict[str, Any] = dict(detail)
        started = time.monotonic()
        try:
            yield box
        finally:
            self.steps.append({"step": name, "ms": _ms(started), "detail": box})

    def add(self, name: str, ms: float = 0.0, **detail: Any) -> None:
        self.steps.append({"step": name, "ms": round(float(ms), 1), "detail": detail})


def _finish(admin: AuthUser, probe: str, tr: _Trace, *, ok: bool, result: Any,
            cost_note: str | None = None) -> ProbeResult:
    total = _ms(tr.started)
    # Kim va qaysi sinov - matnsiz: kiritilgan matn xodim savoli yoki guruh
    # yozishmasi bo'lishi mumkin, jurnal esa `journalctl` orqali kengroq ko'rinadi.
    log.info("Admin sinovi (%s): %s - %s, %.0f ms", _admin._by(admin), probe, "ok" if ok else "xato", total)
    _audit(admin, probe, ok, total)
    return ProbeResult(ok=ok, trace=tr.steps, result=result, cost_note=cost_note)


def _audit(admin: AuthUser, probe: str, ok: bool, ms: float) -> None:
    """Admin auditi (`engine_control` ishlatadigan AYNI jurnal). Yozilmasa sinov
    baribir javob beradi: audit - hujjat, sinovning sharti emas."""
    try:
        with get_db().transaction() as conn:
            _admin.write_audit(conn, admin, "probe.run", "probe", probe, {"ok": ok, "ms": round(ms)})
    except (sqlite3.Error, OSError) as exc:
        log.warning("Admin sinovi auditga yozilmadi (%s): %s", probe, type(exc).__name__)


#: Pullik sinovlar (GAPI daqiqasi, gemma, model `execute`) - admin boshiga soatiga.
#: Sahifadagi tasdiq yetmaydi: API ni to'g'ridan-to'g'ri chaqirgan admin (skript, curl)
#: uni chetlab o'tardi, va GAPI ning kunlik hisobi foydalanuvchilar bilan BITTA.
PAID_PER_HOUR = 30
_paid_runs: dict[str, deque[float]] = {}
_paid_lock = threading.Lock()


def _paid_gate(admin: AuthUser, probe: str, confirmed: bool, note: str) -> None:
    """Pullik sinov: aniq tasdiq (`confirm_cost`) va soatlik chek. Tasdiqsiz - 428
    (narx yozuvi bilan), chekdan oshsa - 429. Bepul sinovlarga tegmaydi."""
    if not confirmed:
        raise error_status(428, f"Pullik sinov ({probe}): {note} Davom etish uchun confirm_cost=true yuboring.")
    who = _admin._by(admin)
    now = time.monotonic()
    with _paid_lock:
        runs = _paid_runs.setdefault(who, deque())
        while runs and now - runs[0] > 3600:
            runs.popleft()
        if len(runs) >= PAID_PER_HOUR:
            raise error_status(429, f"Pullik sinovlar chegarasi: soatiga {PAID_PER_HOUR} ta. Birozdan keyin urinib ko'ring.")
        runs.append(now)


class _Stamped(list):
    """Ishlab chiqarish funksiyasi `trace.append(...)` qilganda vaqt tamg'asini qo'shadi -
    bosqichlar vaqtini o'lchash uchun ishlab chiqarish kodiga soat qo'shish shart emas."""

    def append(self, item: Any) -> None:  # noqa: D401
        super().append({**item, "_t": time.perf_counter()})


# --- STT ----------------------------------------------------------------------------------------


def _pick_reason(wanted: str, language: str) -> str:
    """`_pick` qarorining sababi - uning UCHTA shartiga mos (`stt._pick` izohi)."""
    if wanted != "gapi":
        return "tanlov: Router (1-variant)"
    if language != "uz":
        return "GAPI da faqat o'zbekcha model bor - Router"
    if not _stt._gapi_client.configured:
        return "GAPI kaliti yo'q - Router"
    return "GAPI (2-variant)"


def _stt_cost(steps: list[dict[str, Any]]) -> str:
    if any(s.get("step") == "stt_gapi" for s in steps):
        return ("GAPI (2-variant) PULLIK: shu audio kunlik 480 audio-daqiqalik hisobdan ketdi "
                "(javobsiz urinish ham hisoblanadi).")
    return "Router (1-variant) - ichki va bepul, hisob ketmadi."


@router.post("/stt", response_model=ProbeResult)
def probe_stt(
    file: UploadFile = File(description="Audio - ovoz paneli yuboradigan 16 kHz WAV yoki boshqa format"),
    language: Literal["uz", "ru", "en"] = Form("uz"),
    provider: Literal["auto", "gapi", "router"] = Form("auto", description="`auto` - `STT_PROVIDER`"),
    confirm_cost: bool = Form(False, description="GAPI (pullik) tanlansa - aniq tasdiq"),
    admin: AuthUser = Depends(admin_only),
) -> ProbeResult:
    """Audio -> matn, `/stt/transcribe` bilan AYNI yo'l: hajm tekshiruvi (`upload_bytes`),
    variant tanlovi (`_pick`), GAPI yoki Router, zahira (`_transcribe_with_fallback`).
    Hisobda alohida amal (`op=probe`) - foydalanuvchilar statistikasiga aralashmaydi."""
    tr = _Trace()
    with tr.step("upload") as d:
        audio = _stt.upload_bytes(file)
        ctype = file.content_type or "application/octet-stream"
        d.update(bytes=len(audio), contentType=ctype, forwardedAs=safe_filename(ctype))
    stt_language = LOCALE_TO_STT[language]
    wanted = settings.stt_provider if provider == "auto" else provider
    with tr.step("pick") as d:
        client = _stt._pick(stt_language, wanted)
        chosen = "router" if client is _stt._router_client else "gapi"
        d.update(requested=provider, setting=settings.stt_provider, chosen=chosen,
                 why=_pick_reason(wanted, stt_language))
    if chosen == "gapi":
        _paid_gate(admin, "stt", confirm_cost, "GAPI audio-daqiqasi kunlik hisobdan ketadi.")
    inner: list[dict[str, Any]] = []
    forwarded = {"filename": safe_filename(ctype), "contentType": ctype, "bytes": len(audio)}
    try:
        result = _stt._transcribe_with_fallback(client, audio, stt_language, ctype, yol="Admin sinovi",
                                                budget=settings.stt_deadline, op="probe", trace=inner)
    except SttError as exc:
        tr.steps.extend(inner)
        status, message = _stt.public_error(exc)
        return _finish(admin, "stt", tr, ok=False, cost_note=_stt_cost(inner), result={
            "error": message, "status": status, "provider": chosen,
            "fallbackUsed": any(s["step"] == "fallback" for s in inner), "forwarded": forwarded})
    tr.steps.extend(inner)
    return _finish(admin, "stt", tr, ok=True, cost_note=_stt_cost(inner), result={
        "provider": chosen,
        "fallbackUsed": any(s["step"] == "fallback" for s in inner),
        "backend": result.backend,
        "model": result.model,
        "forwarded": forwarded,
        "language": result.language or stt_language,
        "text": result.text,
        "durationSec": result.duration_sec,
        "lowConfidence": result.low_confidence,
        "truncated": result.truncated,
    })


# --- TTS matni ----------------------------------------------------------------------------------


@router.post("/tts-text", response_model=ProbeResult)
def probe_tts_text(body: TtsTextProbe, admin: AuthUser = Depends(admin_only)) -> ProbeResult:
    """Serverdagi matn tayyorlash - `/tts/speak` (yoki `/tts/clip`) bilan AYNI tartibda:
    til tekshiruvi, `strip`, kesish (`clip`), talaffuz lug'ati, qisqartmalar, qo'shtirnoq,
    sanalar, vaqt, normalizator xavfi. Ovoz SINTEZ QILINMAYDI (bu `tts-speak` - brauzerda)."""
    tr = _Trace()
    limit = settings.tts_max_chars if body.mode == "speak" else CLIP_MAX_CHARS
    endpoint = f"/api/v1/tts/{body.mode}"
    with tr.step("route") as d:
        language_ok = LOCALE_TO_TTS.get(body.language) is not None
        text = body.text.strip()
        d.update(endpoint=endpoint, language=body.language, languageOk=language_ok, chars=len(text), limit=limit)
    base = {"endpoint": endpoint, "limit": limit}
    if not language_ok:
        return _finish(admin, "tts-text", tr, ok=False,
                       result={**base, "error": f"ovoz bu tilda hali yo'q: {body.language}", "status": 400})
    if body.mode == "clip" and len(body.text) > CLIP_MAX_CHARS:
        # `ClipRequest.text` ning `max_length` i - route matnni umuman qabul qilmaydi.
        return _finish(admin, "tts-text", tr, ok=False, result={
            **base, "status": 422, "error": f"/tts/clip {CLIP_MAX_CHARS} belgidan uzun matnni qabul qilmaydi"})
    if not text:
        return _finish(admin, "tts-text", tr, ok=False, result={**base, "error": "matn bo'sh", "status": 400})
    stages = _Stamped()
    started = time.perf_counter()
    client = _tts._client
    try:
        prepared = client.prepare(text, max_chars=limit, trace=stages)
    except TtsError as exc:
        return _finish(admin, "tts-text", tr, ok=False,
                       result={**base, "error": str(exc)[:200], "status": exc.status})
    out: list[dict[str, Any]] = [{"stage": "input", "text": text, "changed": False}]
    previous_at, previous = started, text
    for entry in stages:
        stamp = entry.pop("_t")
        changed = entry["text"] != previous
        extra = {k: v for k, v in entry.items() if k not in ("stage", "text")}
        tr.add(entry["stage"], (stamp - previous_at) * 1000.0, changed=changed, chars=len(entry["text"]), **extra)
        out.append({**entry, "changed": changed})
        previous_at, previous = stamp, entry["text"]
    names = client.spoken_names() if client.spoken_names else {}
    return _finish(admin, "tts-text", tr, ok=True, result={
        **base,
        "stages": out,
        "final": prepared.text,
        "truncated": prepared.truncated,
        "normalizeNumbers": prepared.normalize_numbers,
        "voice": settings.tts_voice,
        "spokenNames": len(names),
        "configured": client.configured,
    })


# --- uyg'otish so'zi ----------------------------------------------------------------------------


@router.post("/wake", response_model=ProbeResult)
def probe_wake(body: WakeProbe, admin: AuthUser = Depends(admin_only)) -> ProbeResult:
    """Eshitilgan matn -> qaror (`is_wake_phrase`) va uning ichki qadamlari: tozalash,
    so'z chegarasi, kirill -> lotin, har so'zning nomgacha masofasi. Oraliq qiymatlar
    AYNI funksiyaning o'zidan (`trace`) - sinov ularni qayta hisoblamaydi."""
    tr = _Trace()
    seen: dict[str, Any] = {}
    started = time.monotonic()
    matched, reason = _wake.is_wake_phrase(body.text, trace=seen)
    ms = _ms(started)
    heard = str(seen.get("heard") or "")
    words = list(seen.get("words") or [])
    # Uzun yoki bo'sh gapda funksiya lotinga o'tmasdan to'xtaydi - jadval uchun baribir ko'rsatiladi.
    latin = list(seen["latin"]) if "latin" in seen else heard.translate(_wake._TO_LATIN).split()
    tr.add("normalize_heard", heard=heard, words=len(words))
    tr.add("word_limit", words=len(words), max=_wake.MAX_WORDS, nameOnlyWords=_wake.NAME_ONLY_WORDS,
           ok=0 < len(words) <= _wake.MAX_WORDS)
    tr.add("to_latin", latin=" ".join(latin), changed=latin != words, reached="latin" in seen)
    tr.add("match", ms, matched=matched, reason=reason, barno=seen.get("barno"), greetingIn=seen.get("pool"))
    # Salom - funksiya qidirgan so'zlar ichida (`pool`: nom lotincha topilsa - lotin, aks holda asl).
    pool = words if seen.get("pool") == "heard" else latin
    detail = []
    for word, lat, greet in zip(words, latin, pool):
        detail.append({
            "word": word,
            "latin": lat,
            "distanceBarno": _wake.distance(lat, _wake.NAME, 3),
            "distanceVenera": _wake.distance(word, _wake.LEGACY_NAME, 3),
            "isBarno": _wake._is_barno(lat),
            "isVenera": _wake._is_legacy(word),
            "greeting": any(_wake.distance(greet, g, 2) <= 2 for g in _wake.GREETINGS),
        })
    return _finish(admin, "wake", tr, ok=True, result={
        "heard": heard, "latin": " ".join(latin), "words": detail, "matched": matched, "reason": reason,
        "maxWords": _wake.MAX_WORDS, "nameOnlyWords": _wake.NAME_ONLY_WORDS,
    })


# --- kutish ovozi -------------------------------------------------------------------------------


def _hold_clips(mavzu: str, ohang: str) -> list[dict[str, Any]]:
    """Shu savol uchun aytiladigan ovozlar ketma-ketligi (`_HoldPlan.fire` tartibi).

    `ilk` uchun navbat (`_navbat`) KO'RILADI, SURILMAYDI: `pick` ga indeks beriladi -
    sinov foydalanuvchilarning keyingi kutish gapini o'zgartirmasin."""
    m, o, _ = _hold._variantlar(mavzu, ohang, "ilk")
    with _hold._navbat_lock:
        orin = _hold._navbat.get((m, o), 0)
    plan = [("ilk", _hold.pick(mavzu, ohang, "ilk", orin))]
    plan += [("davom", _hold.pick(mavzu, ohang, "davom", n)) for n in range(max(0, settings.hold_max - 1))]
    voices = _chat._hold_voices
    out = []
    for at, (stage, (text, key)) in enumerate(plan, 1):
        out.append({"at": at, "stage": stage, "text": text, "clip": key, "ready": voices.ready(key),
                    "url": f"/api/v1/tts/hold/{key}.wav",
                    "afterMs": settings.hold_first_ms if at == 1 else (at - 1) * settings.hold_repeat_ms})
    return out


@router.post("/hold", response_model=ProbeResult)
def probe_hold(body: HoldProbe, admin: AuthUser = Depends(admin_only)) -> ProbeResult:
    """Savol -> kutish ovozi: kalit so'z jadvali (`keyword_topic`), jonli usul
    (`hold_mode`), so'ralsa gemma tasnifi (AYNI `_hold_classifier`), tanlangan gaplar va
    ularning tayyor ovozi (`/api/v1/tts/hold/<kalit>.wav`)."""
    tr = _Trace()
    with tr.step("keyword_topic") as d:
        topic = _hold.keyword_topic(body.question)
        d.update(topic=topic)
    with tr.step("mode") as d:
        mode, watch_route = _brain.hold_mode()
        d.update(mode=mode, watchRoute=watch_route, holdEnabled=settings.hold_enabled,
                 classifierSetting=_config.hold_classifier_now(),
                 note=None if mode == "llm" else "ishlab chiqarishda model CHAQIRILMAYDI")
    label, source = (topic, "oddiy"), "jadval"
    cost = None
    if body.use_llm:
        _paid_gate(admin, "hold", body.confirm_cost, "gemma tasnifi pullik, savol tashqi modelga chiqadi.")
        clf = _chat._hold_classifier
        with tr.step("classify") as d:
            d.update(model=clf.model, configured=clf.configured)
            got = clf.classify(body.question) if clf.configured else None
            d.update(label=list(got) if got else None,
                     fallback=None if got else "jadval (model javob bermadi yoki sozlanmagan)")
        if got:
            label, source = got, "ollama"
        if clf.configured:
            cost = f"{clf.model} (Ollama Cloud) - bitta pullik chaqiruv; savol ollama.com ga chiqdi."
    mavzu, ohang = label
    with tr.step("pick") as d:
        clips = _hold_clips(mavzu, ohang)
        d.update(topic=mavzu, tone=ohang, source=source, clips=len(clips),
                 ready=sum(1 for c in clips if c["ready"]))
    return _finish(admin, "hold", tr, ok=True, cost_note=cost, result={
        "keywordTopic": topic, "mode": mode, "label": {"topic": mavzu, "tone": ohang}, "source": source,
        "clips": clips, "firstMs": settings.hold_first_ms, "repeatMs": settings.hold_repeat_ms,
    })


# --- niqoblash ----------------------------------------------------------------------------------


@router.post("/mask", response_model=ProbeResult)
def probe_mask(body: MaskProbe, admin: AuthUser = Depends(admin_only)) -> ProbeResult:
    """Modelga va agentga ketadigan matnning niqobi - AYNI `mask_text` (guruh xabarlari:
    saqlashda, xulosa, brif, guruh CRM konteksti) va `mask_secrets` (guruhda CRM so'ragan
    odamning o'z so'rovi: telefon va email qoladi)."""
    tr = _Trace()
    fired: dict[str, int] = {}
    with tr.step("mask_text") as d:
        masked = _groups.mask_text(body.text, fired)
        d.update(fired=dict(fired), changed=masked != body.text)
    secret_fired: dict[str, int] = {}
    with tr.step("mask_secrets") as d:
        secrets_only = _groups.mask_secrets(body.text, secret_fired)
        d.update(fired=dict(secret_fired), changed=secrets_only != body.text)
    return _finish(admin, "mask", tr, ok=True, result={
        "masked": masked, "fired": fired,
        "secretsOnly": {"masked": secrets_only, "fired": secret_fired},
    })


# --- agent v4 -----------------------------------------------------------------------------------


@router.get("/agent", response_model=ProbeResult)
def probe_agent(admin: AuthUser = Depends(admin_only)) -> ProbeResult:
    """Agent v4: `GET /capabilities` va `GET /limits` - faqat o'qish, suhbat yo'q.
    O'z uzgichi bilan (`routing.probe_client`): sinov xatosi ishlab turgan funksiyalarni
    lokal yo'lga o'tkazib yubormasin. Bosh kalit (`AGENT_V4_ENABLED`) o'chiq bo'lsa
    ham so'raladi - u funksiyalar uchun, o'qish uchun emas; holati javobda."""
    tr = _Trace()
    with tr.step("switch") as d:
        usable, reason = _routing.agent_usable()
        d.update(enabled=_config.agent_v4_enabled_now(), usable=usable, reason=reason,
                 circuit=_routing.client().breaker.state())
    client = _routing.probe_client()
    base = {"enabled": _config.agent_v4_enabled_now(), "usable": usable, "reason": reason,
            "contract": client.contract}
    if not client.configured:
        insecure = bool(client.base_url) and not client.url_ok
        return _finish(admin, "agent", tr, ok=False, result={
            **base, "error": "agent manzili tashqi http - kalit yuborilmaydi" if insecure
            else "agent sozlanmagan (manzil yoki kalit yo'q)"})
    out: dict[str, Any] = {}
    ok = True
    for name, call in (("capabilities", client.capabilities), ("limits", client.limits)):
        with tr.step(name) as d:
            try:
                out[name] = call(timeout=10.0)
                d.update(ok=True)
            except AgentError as exc:
                ok = False
                out[name] = None
                d.update(ok=False, code=exc.code, status=exc.status)
    return _finish(admin, "agent", tr, ok=ok, result={**base, **out})


# --- sog'lik ------------------------------------------------------------------------------------


def _health_checks(main: Any) -> list[tuple[str, Callable[[], Any], Callable[[Any], str]]]:
    """(nom, `main` dagi AYNI funksiya, holatni o'qish). `/api/health/detail` shu
    funksiyalarni `_diagnostics` ichida chaqiradi - bu yerda har biri alohida o'lchanadi."""

    def upstream_status(v: Any) -> str:
        stt = str((v.get("stt") or {}).get("status") or "?")
        tts = str((v.get("tts") or {}).get("status") or "?")
        return "ok" if stt == "ok" and tts == "ok" else f"stt:{stt} tts:{tts}"

    def assistant_status(v: Any) -> str:
        slots = v.get("slots") or {}
        full = slots.get("busy", 0) >= slots.get("limit", 1)
        return "degraded" if (v.get("engine") or {}).get("problems") or full else "ok"

    def telegram_status(v: Any) -> str:
        if not (v.get("configured") and v.get("enabled")):
            return "off"
        return "error" if v.get("error") else ("ok" if v.get("running") else "degraded")

    def agent_status(v: Any) -> str:
        usable, reason = v
        return "ok" if usable else ("off" if reason == "agent_disabled" else str(reason))

    return [
        ("upstream", main._upstream.snapshot, upstream_status),
        ("assistant", main.assistant_state, assistant_status),
        ("stt", main.stt_variants,
         lambda v: "degraded" if (v.get("fallback") or {}).get("last_5min") else "ok"),
        ("hold", main.hold_state,
         lambda v: "off" if not v.get("enabled") else ("ok" if v.get("model_configured") else "keyword")),
        ("crm_session", lambda: main.crm_auth().warning(), lambda v: "degraded" if v else "ok"),
        ("telegram", main.telegram_state, telegram_status),
        ("meetings", main.meetings_state, lambda v: "ok" if v.get("enabled") else "off"),
        ("agent", _routing.agent_usable, agent_status),
    ]


@router.get("/health", response_model=ProbeResult)
def probe_health(admin: AuthUser = Depends(admin_only)) -> ProbeResult:
    """`/api/health/detail` - AYNI `_diagnostics()`, oldidan har qism alohida vaqt
    bilan (qaysi qism sekin). STT/TTS holati `UpstreamHealth` da 30 s keshlanadi."""
    from ... import main as _main      # aylanma import: `main` -> `api.v1` -> shu modul

    tr = _Trace()
    services: list[dict[str, Any]] = []
    for name, call, status_of in _health_checks(_main):
        started = time.monotonic()
        try:
            status = status_of(call())
            error = None
        except Exception as exc:                            # noqa: BLE001 - sinov hisobot beradi
            status, error = "error", type(exc).__name__
        ms = _ms(started)
        tr.add(name, ms, status=status, **({"error": error} if error else {}))
        services.append({"name": name, "status": status, "ms": ms})
    with tr.step("diagnostics") as d:
        diagnostics = _main._diagnostics()
        d.update(status=diagnostics.get("status"), warnings=len(diagnostics.get("warnings") or []))
    return _finish(admin, "health", tr, ok=diagnostics.get("status") == "ok", result={
        "status": diagnostics.get("status"), "services": services,
        "warnings": diagnostics.get("warnings") or [], "diagnostics": diagnostics,
    })


# --- miya funksiyalari (DRY) --------------------------------------------------------------------

#: Haqiqiy token hech qachon javobga tushmaydi - agent tanasida shu belgi turadi.
_TOKEN = "<crm-token>"
#: Vaqtinchalik guruh (sinov ombori ichida - jonli guruhlar bilan aralashmaydi).
_CHAT = -1_000_000_000_001
_TITLE = "Sinov guruhi"


class _DryRunStop(BaseException):
    """Prompt ushlandi - model CHAQIRILMAYDI. `BaseException`: ishlab chiqarish kodidagi
    `except Exception` / `except OllamaError` uni "model xatosi" deb yutib, xato yo'liga
    (masalan brifning `_fail` -> omborga yozuv) o'tib ketmasin."""


class _Recording:
    """Model o'rnida turadi: har chaqiruvni (system, user, parametrlar) yozadi.

    `inner=None` - DRY: yozadi va `_DryRunStop` ko'taradi. `inner` berilsa - AYNI
    chaqiruvni haqiqiy modelga uzatadi (`execute`) va javobni ham yozadi."""

    configured = True
    name = "probe"
    max_prompt_chars = 0

    def __init__(self, inner: Any = None) -> None:
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return getattr(self.inner, "model", "dry-run") if self.inner is not None else "dry-run"

    def complete(self, system: str, user: str, **kwargs: Any) -> str:
        return self._run("complete", system, user, kwargs)

    def complete_meta(self, system: str, user: str, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        return self._run("complete_meta", system, user, kwargs)

    def _run(self, kind: str, system: str, user: str, kwargs: dict[str, Any]) -> Any:
        fmt = kwargs.get("format")
        call = {"op": kwargs.get("op"), "system": system, "user": user,
                "num_predict": kwargs.get("num_predict"), "temperature": kwargs.get("temperature"),
                "format": fmt if isinstance(fmt, str) or fmt is None else "json-schema"}
        self.calls.append(call)
        if self.inner is None:
            raise _DryRunStop()
        started = time.monotonic()
        try:
            out = getattr(self.inner, kind)(system, user, **kwargs)
        finally:
            call["ms"] = _ms(started)
        text = out[0] if isinstance(out, tuple) else out
        call["output"] = str(text or "")[:20000]
        return out


class _NullTelegram:
    """Telegram o'rnida: HECH NARSA yubormaydi, "yuborilgan bo'lardi" xabarlarni yozadi.
    Faqat `_answer` ishlatadigan ikki usul bor - boshqasi chaqirilsa `AttributeError`
    (jim yuborib qo'yishdan ko'ra aniq xato yaxshi)."""

    configured = False

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_chat_action(self, *args: Any, **kwargs: Any) -> None:
        return None

    def send_message(self, chat_id: Any, text: str, **kwargs: Any) -> dict[str, Any]:
        self.sent.append(text)
        return {"message_id": len(self.sent)}


@contextmanager
def _sandbox() -> Iterator[Any]:
    """Vaqtinchalik guruh ombori - jonli `groups.db` ga TEGILMAYDI. Papka sinov
    tugashi bilan o'chiriladi (namuna matni diskda qolmasin)."""
    from ...services.tg_groups import GroupStore

    with tempfile.TemporaryDirectory(prefix="barno-probe-") as folder:
        yield GroupStore(FsPath(folder) / "groups.db", days=settings.telegram_group_days)


_SPEAKER_LINE = re.compile(r"^\s*([^:\n]{1,40}?)\s*:\s*(.+)$")


def _lines(raw: str, default: str = "Guruh a'zosi") -> list[tuple[str, str]]:
    """`Ism: matn` qatorlari -> (muallif, matn). Ikki nuqtasiz qator - `default` niki."""
    out: list[tuple[str, str]] = []
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        found = _SPEAKER_LINE.match(line)
        out.append((found.group(1).strip(), found.group(2).strip()) if found else (default, line))
    return out[:400]


def _seed(store: Any, lines: list[tuple[str, str]], now: float) -> None:
    """Namuna xabarlarni BUGUNGI kun ichiga (Toshkent) tartib bilan joylaydi - guruh
    xulosasi (24 soat) ham, brif kuni ham ularni ko'rsin. `store.add` - AYNI saqlash yo'li
    (`message_text` -> `mask_text`), ya'ni modelga niqoblangan matn boradi."""
    from ...bot.briefs import _day_start

    start = max(_day_start(now) + 60, now - len(lines) * 60)
    step = max(1.0, (now - 5 - start) / max(1, len(lines)))
    people: dict[str, int] = {}
    for n, (author, text) in enumerate(lines, 1):
        uid = people.setdefault(author, 9_000_000 + len(people))
        store.add({"chat": {"id": _CHAT, "type": "supergroup", "title": _TITLE}, "message_id": n,
                   "date": int(start + (n - 1) * step), "from": {"id": uid, "first_name": author},
                   "text": text})


def _agent_complete_body(call: dict[str, Any], client_name: str) -> dict[str, Any]:
    """Agent holatida `POST /complete` ga ketadigan tana - AYNI `AgentComplete.request`."""
    from ...services.brain.chat import AgentComplete

    agent = AgentComplete(lambda: _routing.client(client_name))
    temperature = call.get("temperature")
    return agent.request(call["system"], call["user"], num_predict=int(call.get("num_predict") or 1200),
                         temperature=float(0.2 if temperature is None else temperature),
                         op=str(call.get("op") or ""))


def _live_writer(feature: str) -> Any:
    """`execute` uchun bot yozuvchisi (`bot._writer`, AYNI `BrainChat`). Agent holatida -
    o'rami bilan (agent, xatoda lokal). Aks holda - lokal model TO'G'RIDAN-TO'G'RI: `shadow`
    taqqoslashi navbatga qo'yilmasin (u shadow natijalari jadvaliga yozadi)."""
    from ... import bot as _bot

    brain = _bot._writer()
    return brain if _routing.route(feature).agent else brain.local


def _bot_model() -> str:
    return settings.telegram_group_model or settings.ollama_model


def _group_answer(feature: str, body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Guruh `/summary` yoki `/askbarno` - AYNI `GroupAssistant._answer` vaqtinchalik ombor va
    soxta Telegram ustida: davr, yozishma qatorlari, prompt, model, javobni bo'laklash."""
    from ...bot.groups import GroupAssistant, Request

    lines = _lines(body.input)
    if not lines:
        raise error_status(422, "input: guruh xabarlari kerak (har qatorda `Ism: matn`)")
    kind = "summary" if feature == "group_summary" else "ask"
    writer = _Recording(_live_writer(feature) if body.execute else None)
    api = _NullTelegram()
    now = time.time()
    with _sandbox() as store:
        _seed(store, lines, now)
        assistant = GroupAssistant(api, store, writer, allowed=lambda: frozenset({_CHAT}), inline=True)
        msg = {"chat": {"id": _CHAT, "type": "supergroup", "title": _TITLE}, "message_id": len(lines) + 1,
               "date": int(now), "from": {"id": admin.actorId, "first_name": "Admin"},
               "text": f"/{'summary' if kind == 'summary' else 'askbarno'} {body.question}".strip()}
        try:
            assistant._answer(msg, Request(kind, body.question.strip()), "barno_bot")
        except _DryRunStop:
            pass
        finally:
            assistant.stop()
    out = {"calls": writer.calls, "model": _bot_model(), "messages": len(lines)}
    if body.execute:
        # `_send` ga borgan HTML bo'laklar - guruhga AYNAN shular yuborilgan bo'lardi.
        out["telegramWouldSend"] = api.sent
    return out, (f"{_bot_model()} - pullik model chaqiruvi" if body.execute else None)


def _brief_extract(body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Brif: bir kunlik hodisalarni ajratish - AYNI `BriefEngine.extract_day` (prompt,
    qism-qism bo'lish, oldingi ochiq ishlar, tekshirish) vaqtinchalik omborda."""
    from ...bot.briefs import CHUNK_CHARS, BriefEngine, TZ

    lines = _lines(body.input)
    if not lines:
        raise error_status(422, "input: guruh xabarlari kerak (har qatorda `Ism: matn`)")
    writer = _Recording(_live_writer("brief_extract") if body.execute else None)
    now = time.time()
    day = datetime.fromtimestamp(now, TZ).strftime("%Y-%m-%d")
    events = None
    with _sandbox() as store:
        _seed(store, lines, now)
        engine = BriefEngine(store, writer, groups=lambda: frozenset({_CHAT}), kind_of=lambda _c: body.kind,
                             clock=lambda: now, chunk_chars=CHUNK_CHARS)
        marker = store.day_markers(_CHAT, now - 86400 * 2, now + 60).get(day, "")
        try:
            events = engine.extract_day(_CHAT, _TITLE, day, marker, kind=body.kind)
        except _DryRunStop:
            pass
    out: dict[str, Any] = {"calls": writer.calls, "model": _bot_model(), "kind": body.kind, "day": day}
    if body.execute:
        out["events"] = events
    return out, (f"{_bot_model()} - pullik model chaqiruvi" if body.execute else None)


def _brief_crm(body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Brif CRM tekshiruvi: savol matni (AYNI `CrmChecker._question`) va agent holatidagi
    tana (`brief_crm_request`). Model ham, CRM ham chaqirilmaydi."""
    from ...bot.crm_status import BATCH, NORMALIZE_PROMPT, CrmChecker
    from ...services.brain.features import brief_crm_request

    items = []
    for n, (owner, title) in enumerate(_lines(body.input, default=""), 1):
        items.append({"type": "task", "title": title, "status": "open", "severity": "medium",
                      "at": time.time() - n, "group": _CHAT, "owner": owner or None})
    if not items:
        raise error_status(422, "input: vazifalar kerak (har qatorda bitta; `Mas'ul: vazifa` ham bo'ladi)")
    checker = CrmChecker(lambda q, u, t: {}, writer=None)
    titles = {_CHAT: _TITLE}
    chunk = checker._fit(items[:BATCH], titles)
    question = checker._question(chunk, titles)
    return {
        "question": question,
        "items": len(chunk),
        "agentRequest": brief_crm_request(question, admin.actorId, _TOKEN),
        "localPath": "v3 yordamchi (`agent_ask`, faqat CRM tokeni) -> javob gemma bilan JSON ga (NORMALIZE_PROMPT)",
        "normalizePrompt": NORMALIZE_PROMPT,
    }, None


def _summary_input(raw: str) -> Any:
    """`S1: matn` (yoki `Ism: matn`) qatorlari -> yig'ilish segmentlari (`SummaryInput`)."""
    from ...services.meetings.summarize import SummaryInput

    segments: list[dict[str, Any]] = []
    speakers: dict[str, dict[str, Any]] = {}
    clock = 0.0
    for n, (who, text) in enumerate(_lines(raw, default="S1"), 1):
        sid = who.upper() if re.fullmatch(r"[sS]\d{1,2}", who) else None
        if sid is None:
            sid = next((k for k, v in speakers.items() if v["name"] == who), f"S{len(speakers) + 1}")
        spoken = max(2.0, len(text.split()) * 0.45)
        segments.append({"id": n, "start": round(clock, 2), "end": round(clock + spoken, 2), "speaker": sid,
                         "text": text})
        row = speakers.setdefault(sid, {"id": sid, "name": None if sid == who.upper() else who, "talk_sec": 0.0})
        row["talk_sec"] += spoken
        clock += spoken + 0.3
    return SummaryInput(meeting_id="probe", rev=1, recorded_at=time.time(), duration_sec=round(clock, 1),
                        language="uz", template="auto", segments=segments, speakers=list(speakers.values()),
                        marks=[], speakers_available=True)


def _meeting_summary(body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Yig'ilish xulosasi - AYNI `Pipeline` (shablon tanlovi, bir o'tish yoki map), birinchi
    model chaqiruvigacha. Keyingi qadamlar model javobiga bog'liq - DRY da ular yo'q."""
    from types import SimpleNamespace

    from ...services.meetings.worker import _pipeline

    inp = _summary_input(body.input)
    if not inp.segments:
        raise error_status(422, "input: yig'ilish matni kerak (har qatorda `S1: matn`)")
    writer = _Recording()
    # AYNI quvur yasovchi (`worker._pipeline`, `ollama` bo'g'ini) - sozlamalar bu yerda
    # qayta yozilmaydi. Map keshi - bo'sh va yozilmaydigan (jonli yig'ilish keshiga tegmaydi).
    null_cache = SimpleNamespace(part=lambda *a, **k: None, put_part=lambda *a, **k: None)
    provider = SimpleNamespace(name="ollama", client=writer, model=writer.model, max_prompt_chars=0)
    pipeline = _pipeline(SimpleNamespace(store=null_cache), {"id": "probe", "transcript_rev": 1},
                         {"language": inp.language}, provider, False, None)
    skipped = None
    try:
        out = pipeline.run(inp)
        skipped = out.error_code or out.status
    except _DryRunStop:
        pass
    return {"calls": writer.calls, "skipped": skipped, "chain": settings.meetings_llm_chain,
            "segments": len(inp.segments), "durationSec": inp.duration_sec}, None


def _meeting_ask(body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Yig'ilish savol-javobi - AYNI `ask.answer` (qatorlarni tanlash, qaydlar, prompt)."""
    from ...services.meetings import ask as ask_mod
    from ...services.meetings import dates, prompts

    inp = _summary_input(body.input)
    if not inp.segments or not body.question.strip():
        raise error_status(422, "input (yig'ilish matni) va question (savol) kerak")
    day = dates.tashkent(inp.recorded_at)
    speakers = [{"id": s["id"], "name": s.get("name")} for s in inp.speakers]
    meta = prompts.meta_line(day.date(), dates.WEEKDAYS["en"][day.weekday()], inp.duration_sec, speakers, True)
    writer = _Recording()
    try:
        ask_mod.answer(writer, question=body.question, language="uz", meta=meta, segments=inp.segments,
                       speakers=speakers, summary=None)
    except _DryRunStop:
        pass
    return {"calls": writer.calls, "chain": settings.meetings_ask_chain or settings.meetings_llm_chain}, None


def _hold_classify(body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Ovozli kutish tasnifi - Ollama'ga AYNAN ketadigan tana (`HoldClassifier.request_body`).
    Agent holatida qo'shimcha chaqiruv yo'q: yorliq chat oqimidagi `route` kadridan keladi."""
    question = (body.question or body.input).strip()
    if not question:
        raise error_status(422, "question: savol kerak")
    clf = _chat._hold_classifier
    out: dict[str, Any] = {"request": clf.request_body(question), "model": clf.model,
                           "configured": clf.configured, "mode": _brain.hold_mode()[0],
                           "keywordTopic": _hold.keyword_topic(question)}
    cost = None
    if body.execute:
        started = time.monotonic()
        label = clf.classify(question) if clf.configured else None
        out["label"] = list(label) if label else None
        out["ms"] = _ms(started)
        cost = f"{clf.model} (Ollama Cloud) - bitta pullik chaqiruv" if clf.configured else None
    return out, cost


class _ProbeCrmBackend:
    """Guruh CRM uchun bot "orqasi" o'rnida: token o'rniga `_TOKEN` belgisi, kimlik - AYNI
    `assistant_user_id` (jonli `runner` dagi kabi). Agentga hech narsa yubormaydi."""

    @staticmethod
    def own_crm_token(user: AuthUser) -> str:
        return _TOKEN

    @staticmethod
    def agent_user_id(user: AuthUser) -> str:
        return _chat.assistant_user_id(user)


def _group_crm(body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Guruhdagi CRM so'rovi - agent v4 tanasi, AYNI `GroupActions._v4_body` vaqtinchalik ombor
    ustida: oxirgi yozishma oynasi (`_recent`), niqob (`mask_text`, so'rov - `mask_secrets`),
    ismlar eslatmasi va kontekst bloki. Agent chaqirilmaydi."""
    from ...bot.group_actions import GroupActions

    lines = _lines(body.input)
    if not lines:
        raise error_status(422, "input: guruh xabarlari kerak (har qatorda `Ism: matn`)")
    now = time.time()
    with _sandbox() as store:
        _seed(store, lines, now)
        actions = GroupActions(_NullTelegram(), store, _ProbeCrmBackend(), resolve=lambda _tg_id: None,
                               clock=lambda: now)
        msg = {"chat": {"id": _CHAT, "type": "supergroup", "title": _TITLE}, "message_id": len(lines) + 1,
               "date": int(now), "from": {"id": 8_999_999, "first_name": "Admin"}, "text": body.question}
        request = actions._v4_body(msg, body.question, admin, "tgcrm-probe")
    return {"agentRequest": request,
            "note": "chat_id sinov belgisi; jonli yo'lda guruhga bog'langan `tgcrm-` suhbat"}, None


def _meeting_crm(body: BrainProbe, admin: AuthUser) -> tuple[dict[str, Any], str | None]:
    """Yig'ilish vazifasi CRM ga: savol (AYNI `meetings.crm.question`) va agent v4 tanasi
    (`service.meeting_crm_v4_body`). Birinchi qator - vazifa, ikkinchisi - iqtibos."""
    from ...services.meetings import crm as meeting_crm
    from ...services.meetings.service import meeting_crm_v4_body

    rows = [line.strip() for line in body.input.splitlines() if line.strip()]
    if not rows:
        raise error_status(422, "input: vazifa matni kerak (1-qator), iqtibos (2-qator, ixtiyoriy)")
    item = {"task": rows[0], "quote": rows[1] if len(rows) > 1 else None}
    meeting = {"title": "Sinov yig'ilishi", "recorded_at": time.time()}
    question = meeting_crm.question(item, meeting, {}, requester=admin.fullName)
    return {"question": question,
            "agentRequest": meeting_crm_v4_body(question, _chat.assistant_user_id(admin), _TOKEN)}, None


#: Funksiya -> (DRY/execute ishlovchisi, `execute` mumkinmi, mumkin bo'lmasa sababi).
_BRAIN: dict[str, tuple[Callable[[BrainProbe, AuthUser], tuple[dict[str, Any], str | None]], str | None]] = {
    "group_summary": (lambda b, a: _group_answer("group_summary", b, a), None),
    "group_ask": (lambda b, a: _group_answer("group_ask", b, a), None),
    "brief_extract": (_brief_extract, None),
    "brief_crm": (_brief_crm,
                  "Brif CRM tekshiruvi odamning CRM tokeni bilan yuqoridagi yordamchiga boradi va u yerda "
                  "suhbat (`venera-brief:`) saqlanadi - sinovda bajarilmaydi, faqat savol va tana."),
    "meeting_summary": (_meeting_summary,
                        "Yig'ilish xulosasi 5-27 model chaqiruvidan iborat zanjir (ollama/openai/v3/agent) va "
                        "yig'ilish keshiga bog'liq - sinov faqat birinchi qadam promptini ko'rsatadi."),
    "meeting_ask": (_meeting_ask,
                    "Savol-javob zanjiri (v3 da odamning tokenlari bilan) yuqorida suhbat qoldirishi mumkin - "
                    "sinov faqat promptni ko'rsatadi."),
    "hold_classify": (_hold_classify, None),
    "group_crm": (_group_crm,
                  "Guruh CRM so'rovi agentda suhbat saqlaydi (`store: true`) va CRM taklifi (`crm.propose`) "
                  "yaratadi - sinovda bajarilmaydi, faqat tana."),
    "meeting_crm": (_meeting_crm,
                    "Yig'ilish vazifasi CRM taklifini yaratadi (`crm.propose`) - sinovda bajarilmaydi, "
                    "faqat savol va tana."),
}

#: Agent holatida `complete` ga boradigan funksiyalar - qaysi mijoz (`routing.client`).
_COMPLETE_CLIENT = {"group_summary": "interactive", "group_ask": "interactive", "brief_extract": "batch",
                    "meeting_summary": "meetings", "meeting_ask": "interactive"}


@router.post("/brain/{feature}", response_model=ProbeResult)
def probe_brain(
    body: BrainProbe,
    feature: str = Path(min_length=1, max_length=40, description="group_summary, brief_extract, ..."),
    admin: AuthUser = Depends(admin_only),
) -> ProbeResult:
    """Miya funksiyasi namunada: modelga AYNAN ketadigan prompt (lokal) va agent holatidagi
    so'rov tanasi (v4) - model CHAQIRILMAYDI. `execute: true` - model ham chaqiriladi
    (pullik), lekin yon ta'sirsiz: Telegram'ga yuborilmaydi, CRM ga yozilmaydi, jonli
    omborga tegilmaydi. Yon ta'sirsiz qilib bo'lmaydigan funksiyada `execute` - 409."""
    name = feature.strip().lower()
    if name not in _control.BRAIN_FEATURES or name not in _BRAIN:
        raise error_status(422, f"noma'lum funksiya ({feature[:40]!r}) - {' | '.join(_BRAIN)}")
    handler, refuse = _BRAIN[name]
    if body.execute and refuse:
        raise error_status(409, refuse)
    if body.execute:
        _paid_gate(admin, f"brain:{name}", body.confirm_cost, "model haqiqatan chaqiriladi (pullik).")
    tr = _Trace()
    with tr.step("route") as d:
        route = _routing.route(name)
        d.update(configured=route.configured, effective=route.effective, reason=route.reason, source=route.source)
    with tr.step("execute" if body.execute else "render") as d:
        out, cost = handler(body, admin)
        d.update(calls=len(out.get("calls") or []))
    client_name = _COMPLETE_CLIENT.get(name)
    calls = out.get("calls") or []
    if client_name and calls:
        with tr.step("agent_request"):
            # Birinchi chaqiruvning agent holatidagi tanasi - `BrainChat`/zanjir bo'g'ini
            # agentga AYNAN shuni yuborardi.
            out["agentRequest"] = _agent_complete_body(calls[0], client_name)
    ok = True
    if body.execute:
        # Ishlab chiqarish kodi model xatosini o'zi yutadi (guruhga "bajarib bo'lmadi" yozadi,
        # brif kunini "failed" qiladi, tasnif jadvalga tushadi) - sinov buni "ok" demasin.
        if name == "hold_classify":
            ok = out.get("label") is not None
        else:
            ok = bool(calls) and all("output" in c for c in calls)
            if name == "brief_extract":
                ok = ok and out.get("events") is not None
    result = {"feature": name, "mode": "execute" if body.execute else "dry",
              "route": {"configured": route.configured, "effective": route.effective, "reason": route.reason},
              **out}
    return _finish(admin, f"brain:{name}", tr, ok=ok, result=result, cost_note=cost)

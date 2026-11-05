"""BAYONNOMA - yig'ilish yozuvidan rasmiy hujjat (ega topshirig'i, 2026-11-04).

Namuna: bank Boshqaruv raisi huzuridagi yig'ilish "БАЁНИ" - tasdiq bloki, sarlavha, sana/shahar,
raislik qiluvchi, qatnashganlar, KUN TARTIBI, har band bo'yicha bayon, "ҚАРОР ҚИЛАДИ:", rim
raqamli bo'limlar ichida UZLUKSIZ raqamlangan bandlar (muddat + mas'ul + vazifa + buyruq fe'li),
nazorat bandi. Audiodan faqat TANASI chiqadi: kun tartibi, bayon, bandlar. Tasdiq bloki, №,
QR, bank nomi, shahar, rais va qatnashuvchilar lavozimlari, kelishuvchilar - BO'SH JOY
(`text.BLANK`), hujjat tizimi yoki kotib to'ldiradi (ega qarori: hozircha bo'sh).

QUVUR (bitta model chaqiruvi, sinxron - bot ipida 1-3 daqiqa):
    prompt.build   transkript (+ jonli vazifalar) -> Claude ga ko'rsatma; chiqish tili tanlanadi
    llm.run_chain  `MEETINGS_MINUTES_CHAIN` (default faqat `claude`); javob - qat'iy JSON (`shapes.minutes`)
    validate       shakl, chegaralar, ASOSLASH: manba qatorlar mavjud, ismlar transkriptda bor
                   (yo'q ism -> `BLANK`), yozuv (kirill/lotin) mos; ogohlantirishlar `quality`
    store          `minutes` jadvali (v5): til + transkript versiyasi + prompt versiyasi bo'yicha
                   TAKRORLANMAYDI (`force` bo'lmasa tayyori qaytadi)
    compose/render Letter formatli DOCX (Arial 13) va PDF (DejaVu Sans) - asosiy natija Word, PDF nusxa.

HUJJAT TILI foydalanuvchi tanlovi: `uz-latn` | `uz-cyrl` | `ru` | `en` (`text.LANGS`); o'zbek
yig'ilish uchun default - kirill (bank hujjati). Transkript tilidan farq qilishi mumkin - model
o'giradi, iqtibos va kodlar o'zgarmaydi.

KIMNING NOMIDAN: xulosa kabi - yig'ilish egasi (`service._owned`); Slack'da umumiy hisob,
Telegram'da odamning o'z hisobi. Soatlik chegara `MEETINGS_MINUTES_PER_HOUR` (har hujjat pullik).
"""

from __future__ import annotations

import logging
import threading
import time

from typing import Any

from ....core.config import settings
from ....schemas.auth import AuthUser
from .. import export, llm, service
from ..errors import MeetingProblem
from ..store import jdump, jload, new_id
from ...integrations.ollama import OllamaError
from ..summarize import LlmBusy, LlmFailed, LlmRateLimited, LlmUnavailable, parse_json
from . import compose, prompt, render, text, validate
from .text import BLANK, LANG_TITLES, LANGS, default_lang, normalize  # noqa: F401 - umumiy nomlar

log = logging.getLogger(__name__)

#: Hujjat formatlari -> (Content-Type, kengaytma). Asosiy natija - Word; PDF - nusxa; MD - ko'rish uchun.
FORMATS = {"docx": export.FORMATS["docx"], "pdf": export.FORMATS["pdf"], "md": export.FORMATS["md"]}

_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(meeting_id: str, lang: str) -> threading.Lock:
    """Bitta yig'ilish + til uchun bir vaqtda BITTA model chaqiruvi: ikki odam (yoki ikki bosish)
    bir xil hujjatni ikki marta to'latmasin - ikkinchisi birinchisining natijasini oladi."""
    with _locks_guard:
        if len(_locks) > 500:
            for key in [k for k, lock in _locks.items() if not lock.locked()]:
                _locks.pop(key, None)
        return _locks.setdefault((meeting_id, lang), threading.Lock())


def _speakers(meeting_id: str) -> dict[str, dict[str, Any]]:
    return {sp["id"]: sp for sp in service.runtime().store.speakers(meeting_id)}


def view(row: dict[str, Any], m: dict[str, Any]) -> dict[str, Any]:
    """Qator -> ko'rinish (mazmunsiz): holat, kim yozgani, bandlar soni, izohlar, eskirganmi.
    Izohlar hujjatdagidek (`compose.render_notes`): Slack/Telegram xabarida `[S#]` ko'rinmasin."""
    content = jload(row.get("content_json")) or {} if row.get("status") == "ready" else {}
    sections = content.get("sections") or []
    quality = content.get("quality") or {}
    notes = compose.render_notes(content, speakers=_speakers(m["id"]) if content.get("notes") else None,
                                 lang=row["language"])
    error = None
    if row.get("status") == "failed":
        error = {"code": row.get("error_code") or "llm_failed", "message": row.get("error") or ""}
    return {"id": row["id"], "meetingId": row["meeting_id"], "language": row["language"], "status": row["status"],
            "createdAt": service.iso(row.get("created_at")), "finishedAt": service.iso(row.get("finished_at")),
            "provider": row.get("provider"), "model": row.get("model"),
            "transcriptRev": int(row.get("transcript_rev") or 0),
            "stale": int(row.get("transcript_rev") or 0) < int(m.get("transcript_rev") or 0),
            "agendaCount": len(content.get("agenda") or []), "sectionCount": len(sections),
            "itemCount": sum(len(s.get("items") or []) for s in sections),
            "notes": notes, "warnings": list(quality.get("warnings") or []),
            "error": error}


def _ready_row(store: Any, meeting_id: str, lang: str, rev: int) -> dict[str, Any] | None:
    for row in reversed(store.minutes_rows(meeting_id)):
        if row["status"] == "ready" and row["language"] == lang and int(row["transcript_rev"]) == rev \
                and row["prompt_version"] == prompt.MINUTES_VERSION and row.get("content_json"):
            return row
    return None


def listing(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    m = service._owned(user.actorId, meeting_id)
    return {"items": [view(r, m) for r in service.runtime().store.minutes_rows(m["id"])]}


def latest(user: AuthUser, meeting_id: str, lang: str) -> dict[str, Any] | None:
    """Shu tilda, joriy transkript bo'yicha TAYYOR hujjat (yoki `None`)."""
    code = normalize(lang)
    if code is None:
        raise MeetingProblem(400, "invalid_language", "Hujjat tili: uz-latn, uz-cyrl, ru yoki en")
    m = service._owned(user.actorId, meeting_id)
    row = _ready_row(service.runtime().store, m["id"], code, int(m.get("transcript_rev") or 0))
    return view(row, m) if row else None


def generate(user: AuthUser, meeting_id: str, lang: str, *, force: bool = False,
             now: float | None = None) -> dict[str, Any]:
    """Hujjatni yozadi (yoki tayyorini qaytaradi) -> `view`. Xatolar `MeetingProblem`:
    400 til, 409 transkript yo'q yoki unda nutq yo'q, 429 chegara / model 429, 503 model
    sozlanmagan yoki band, 502 model yozolmadi (sabab `detail` da)."""
    now = time.time() if now is None else now
    code = normalize(lang)
    if code is None:
        raise MeetingProblem(400, "invalid_language", "Hujjat tili: uz-latn, uz-cyrl, ru yoki en")
    rt = service.runtime()
    store = rt.store
    m = service._owned(user.actorId, meeting_id)
    service._require_transcript(m)
    if store.row("SELECT 1 FROM segments WHERE meeting_id=? AND trim(text) <> '' LIMIT 1", (m["id"],)) is None:
        # Yozuvda nutq yo'q (masalan 5 s jimlik): model chaqirilmaydi - u bo'sh hujjat qaytarib, odam
        # "qayta urinib ko'ring" degan noto'g'ri xabarni olardi (2026-11-05 jonli sinovi).
        raise MeetingProblem(409, "transcript_empty",
                             "Yozuvda nutq topilmadi - bayonnoma uchun gapirilgan yig'ilish yozuvi kerak")
    rev = int(m.get("transcript_rev") or 0)
    if not force:
        found = _ready_row(store, m["id"], code, rev)
        if found is not None:
            return view(found, m)
    providers = [p for p in llm.minutes_providers(rt, m["actor_id"]) if p.configured]
    if not providers:
        raise MeetingProblem(503, "llm_not_configured",
                             "Bayonnoma uchun model sozlanmagan (CLAUDE_API_KEY / MEETINGS_MINUTES_CHAIN)")
    with _lock(m["id"], code):
        if not force:
            # Qulf ichida qayta: parallel bosish birinchisining natijasini oladi - model ham, soatlik
            # chegara ham ikkinchi marta sarflanmaydi.
            found = _ready_row(store, m["id"], code, rev)
            if found is not None:
                return view(found, m)
        service._rate("minutes", user.actorId, settings.meetings_minutes_per_hour)
        row = _write(rt, m, code, rev, providers, now)
    return view(row, store.meeting_any(m["id"]) or m)


def _write(rt: Any, m: dict[str, Any], lang: str, rev: int, providers: list[Any], now: float) -> dict[str, Any]:
    store = rt.store
    minutes_id = new_id()
    # Qator OLDIN yoziladi (`running`): prompt yig'ish yoki model xatosi ham qatorda qoladi (`failed`).
    store.insert_minutes({"id": minutes_id, "meeting_id": m["id"], "language": lang, "transcript_rev": rev,
                          "prompt_version": prompt.MINUTES_VERSION, "status": "running", "created_at": int(now)})

    def attempt(provider: Any, strict: bool) -> dict[str, Any]:
        content = _ask(provider, system, user_text)
        try:
            cleaned, warnings = validate.validate(content, lang=lang, segments=segments, speakers=speakers)
        except validate.Invalid as exc:
            # Shakl yaroqsiz - shu model yiqildi: zanjirda keyingisi bo'lsa u yozadi (`run_chain`).
            raise LlmFailed(f"bayonnoma: {exc}") from exc
        cleaned["quality"] = {"warnings": warnings, "strict": strict}
        return cleaned

    try:
        segments = store.segments(m["id"])
        speakers = [sp for sp in store.speakers(m["id"]) if not sp.get("merged_into")]
        items = store.action_items(m["id"])
        system, user_text = prompt.build(m, segments=segments, speakers=speakers, action_items=items, lang=lang)
        content, used, failed = llm.run_chain(providers, attempt, what="bayonnoma")
    except LlmUnavailable as exc:
        _failed(store, minutes_id, "llm_not_configured", str(exc))
        raise MeetingProblem(503, "llm_not_configured", "Bayonnoma modeli sozlanmagan") from None
    except LlmBusy:
        _failed(store, minutes_id, "llm_busy", "navbat to'la")
        raise MeetingProblem(503, "llm_busy", "Model hozir band - birozdan keyin qayta urinib ko'ring",
                             headers={"Retry-After": "30"}) from None
    except LlmRateLimited:
        _failed(store, minutes_id, "llm_rate_limited", "429")
        raise MeetingProblem(429, "llm_rate_limited", "Model chegarasi - birozdan keyin qayta urinib ko'ring",
                             headers={"Retry-After": "60"}) from None
    except LlmFailed as exc:
        _failed(store, minutes_id, "llm_failed", str(exc)[:300])
        log.info("Yig'ilish %s: bayonnoma yozilmadi (%s: %s)", m["id"], type(exc).__name__, str(exc)[:160])
        raise MeetingProblem(502, "llm_failed", "Model bayonnomani yozolmadi - qayta urinib ko'ring") from None
    except Exception as exc:                                     # noqa: BLE001
        # Kutilmagan xato (ombor, prompt yig'ish) - qator `running` da abadiy qolmasin.
        _failed(store, minutes_id, "internal", type(exc).__name__)
        log.exception("Yig'ilish %s: bayonnomada kutilmagan xato", m["id"])
        raise MeetingProblem(500, "internal", "Bayonnoma yozilmadi: ichki xato") from None
    content["version"] = prompt.MINUTES_VERSION
    content["language"] = lang
    content["meeting"] = {"recordedAt": service.iso(m.get("recorded_at")),
                          "durationSec": float(m.get("duration_sec") or 0), "speakerCount": len(speakers)}
    if failed:
        content["quality"]["warnings"] = [f"provider_failed:{name}" for name in failed] + \
            list(content["quality"].get("warnings") or [])
    store.update_minutes(minutes_id, status="ready", provider=used.name, model=str(used.model)[:120],
                         content_json=jdump(content), finished_at=int(time.time()), error_code=None, error=None)
    log.info("Yig'ilish %s: bayonnoma tayyor (%s, %s, %d band)", m["id"], lang, used.name,
             sum(len(s.get("items") or []) for s in content.get("sections") or []))
    return store.minutes_row(m["id"], minutes_id)


def _ask(provider: Any, system: str, user_text: str) -> dict[str, Any]:
    """Bitta provayder bilan hujjat JSON i. Kesilgan yoki yaroqsiz javob - `LlmFailed` (zanjir
    keyingisiga, bo'lsa). `options.effort` - Claude `output_config.effort`; Ollama uni e'tiborsiz
    qoldiradi (`num_ctx` kabi noma'lum sozlama)."""
    try:
        raw, meta = provider.client.complete_meta(
            system, user_text, num_predict=settings.meetings_minutes_max_output_tokens, temperature=0.2,
            op="meeting_minutes", format="json", options={"effort": settings.meetings_minutes_effort})
    except OllamaError as exc:
        # Ollama klienti o'z xatosini otadi (`summarize.call_llm` dagi xaritalash): 429 - kutish,
        # sozlanmagan - yo'q, navbat to'la - band, qolgani - yiqildi (zanjir keyingisiga).
        status = getattr(exc, "status", None)
        if status == 429:
            raise LlmRateLimited(str(exc)) from exc
        if str(exc) == "Ollama sozlanmagan":
            raise LlmUnavailable(str(exc)) from exc
        if str(exc) == "navbat to'la":
            raise LlmBusy(str(exc)) from exc
        raise LlmFailed(f"bayonnoma: {exc}") from exc
    if (meta or {}).get("doneReason") == "length":
        raise LlmFailed("bayonnoma: javob kesildi (max tokens)")
    data, _ = parse_json(raw)
    if not isinstance(data, dict):
        raise LlmFailed("bayonnoma: javob JSON emas")
    return data


def _failed(store: Any, minutes_id: str, code: str, reason: str) -> None:
    store.update_minutes(minutes_id, status="failed", error_code=code, error=reason[:300],
                         finished_at=int(time.time()))


def get(user: AuthUser, meeting_id: str, minutes_id: str) -> dict[str, Any]:
    """Ko'rinish + mazmun (tayyor bo'lsa)."""
    m = service._owned(user.actorId, meeting_id)
    row = _row_or_404(m, minutes_id)
    out = view(row, m)
    out["content"] = jload(row.get("content_json")) if row["status"] == "ready" else None
    return out


def _row_or_404(m: dict[str, Any], minutes_id: str) -> dict[str, Any]:
    row = service.runtime().store.minutes_row(m["id"], str(minutes_id or ""))
    if row is None:
        raise MeetingProblem(404, "minutes_not_found", "Bayonnoma topilmadi")
    return row


def export_file(user: AuthUser, meeting_id: str, minutes_id: str, fmt: str, *,
                now: float | None = None) -> tuple[bytes, str, str]:
    """Tayyor hujjat -> (baytlar, Content-Type, Content-Disposition). `fmt`: docx | pdf | md."""
    now = time.time() if now is None else now
    if fmt not in FORMATS:
        raise MeetingProblem(400, "invalid_format", "Format: docx, pdf yoki md")
    m = service._owned(user.actorId, meeting_id)
    row = _row_or_404(m, minutes_id)
    if row["status"] != "ready" or not row.get("content_json"):
        raise MeetingProblem(409, "not_ready", "Bayonnoma hali tayyor emas")
    content = jload(row["content_json"], {}) or {}
    lang = row["language"]
    recorded_at = float(m.get("recorded_at") or m.get("created_at") or 0)
    doc = compose.compose(content, lang=lang, title=m.get("title") or content.get("title") or "",
                          speakers=_speakers(m["id"]), recorded_at=recorded_at, now=now)
    with service._export_slot(user.actorId):
        try:
            data = render.render(doc, fmt, font_dir=settings.meetings_export_font_dir)
        except export.RenderUnavailable as exc:
            log.warning("Yig'ilish %s: bayonnoma %s chizilmadi (%s)", m["id"], fmt, exc.code)
            headers = {"Retry-After": "10"} if exc.code == "export_busy" else None
            raise MeetingProblem(503, exc.code, service._RENDER_MESSAGES.get(exc.code), headers=headers) from None
    media, ext = FORMATS[fmt]
    title = f"{text.label('doc_word', lang)} - {export.one_line(m.get('title') or content.get('title') or '')}".strip(" -")
    ascii_name, real_name = export.file_names(title, recorded_at, ext)
    log.info("Yig'ilish %s: bayonnoma eksporti %s, %d bayt", m["id"], fmt, len(data))
    return data, media, export.content_disposition(ascii_name, real_name)

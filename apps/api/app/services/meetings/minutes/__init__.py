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

IKKI YO'L, BITTA QUVUR (2026-11-06):
    generate   SINXRON - Slack va Telegram (bot ipi 1-3 daqiqa kutadi, natijani o'zi yuboradi)
    start      ASINXRON - REST / mobil ilova: tez tekshiruvlar so'rov ipida, `running` qator yoziladi,
               model fon ipida (`runner` yoki `WORKERS` li havza) `_lock` ostida; ilova qatorni `get`
               bilan so'rab turadi. HTTP so'rovi 1-3 daqiqa osilib turmasin (proksi va telefon tarmog'i
               uzib qo'yardi, ilova esa "qayta bosish" bilan ikkinchi pullik chaqiruv qilardi).
Ikkalasi bir xil tekshiruv (`_code`, `_source`, `_providers`), dedupe (`_ready_row`) va yozuvdan
(`_insert` + `_fill`) foydalanadi. `running` qator `stale_after()` dan eski bo'lsa - uni yozayotgan ip
jarayon bilan o'lgan (restart, yiqilish): `failed` / `interrupted` (`_settle`), dedupe uni hisoblamaydi.
"""

from __future__ import annotations

import logging
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ....core.config import settings
from ....schemas.auth import AuthUser
from .. import export, llm, service
from ..errors import MeetingProblem
from ..store import jdump, jload, new_id
from ...analytics.meter import carry
from ...integrations.ollama import OllamaError
from ..summarize import LlmBusy, LlmFailed, LlmRateLimited, LlmUnavailable, parse_json
from . import compose, prompt, render, text, validate
from .text import BLANK, LANG_TITLES, LANGS, default_lang, normalize  # noqa: F401 - umumiy nomlar

log = logging.getLogger(__name__)

#: Hujjat formatlari -> (Content-Type, kengaytma). Asosiy natija - Word; PDF - nusxa; MD - ko'rish uchun.
FORMATS = {"docx": export.FORMATS["docx"], "pdf": export.FORMATS["pdf"], "md": export.FORMATS["md"]}

#: Fon ishi iplari (`start`). Claude klientida bitta slot (`meetings._claude(1, ...)`, xulosa bilan umumiy):
#: ko'p ip faqat semaforda o'tirib, `meetings_claude_timeout` dan keyin `llm_busy` bilan yiqilardi. Ikkinchi
#: ip - boshqa yig'ilishning hujjati birinchisi tugashi bilan navbatsiz boshlansin.
WORKERS = 2
#: Eskirgan `running` qator chegarasi ustiga zaxira (soniya): prompt yig'ish, tekshiruv, ombor, havza navbati.
STALE_MARGIN_SEC = 300
#: Uzilgan qatorning sababi (`error.message`) - odam uchun: tugma bosilsa yangisi yoziladi.
INTERRUPTED = "Bayonnoma yozilishi uzilib qoldi - qayta urinib ko'ring"
#: Fon ishini kim bajaradi. `None` - umumiy ip havzasi (`WORKERS`). Testlar o'rniga `lambda job: job()`
#: (shu ipda - deterministik) yoki `jobs.append` (keyin qo'lda ishga tushiradi) qo'yadi.
runner: Callable[[Callable[[], None]], Any] | None = None

_pool: ThreadPoolExecutor | None = None
_pool_guard = threading.Lock()
#: `start` dagi "tayyormi / yozilmoqdami -> chegara -> qator" ketma-ketligi uchun QISQA qulf (ombor so'rovlari):
#: bir vaqtda kelgan ikki bosish ikkita qator va ikkita model chaqiruvi bo'lib ketmasin. Modelni `_lock` kutadi.
_start_guard = threading.Lock()

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


def stale_after() -> float:
    """`running` qator shuncha soniyadan eski bo'lsa - TIRIK EMAS: uni yozayotgan ip jarayon bilan birga
    o'lgan (restart, yiqilish). Aks holda qator abadiy "yozilmoqda" bo'lib, yangi bosishni ham o'ziga
    qo'shib yutib turardi. Chegara - eng yomon model vaqti (`ClaudeChat.complete_meta`): slotni kutish
    (`meetings_claude_timeout` gacha) + har urinish (`meetings_claude_retries` + 1) shu chegaragacha, ustiga
    `STALE_MARGIN_SEC`. Default: 600 x (1 + 3) + 300 = 2700 s (45 daqiqa)."""
    timeout = max(0.0, float(settings.meetings_claude_timeout))
    attempts = max(0, int(settings.meetings_claude_retries)) + 1
    return timeout * (1 + attempts) + STALE_MARGIN_SEC


def _fail_running(store: Any, minutes_id: str, code: str, reason: str, now: float | None = None) -> None:
    """Qator HALI `running` bo'lsa - `failed`. Shart ombor so'rovining o'zida: shu orada tugagan ishning
    natijasi (`ready` yoki aniq sabab) ustidan yozilmaydi."""
    store.execute("UPDATE minutes SET status='failed', error_code=?, error=?, finished_at=? "
                  "WHERE id=? AND status='running'",
                  (code, str(reason)[:300], int(time.time() if now is None else now), minutes_id))


def _settle(store: Any, row: dict[str, Any], now: float) -> dict[str, Any]:
    """Eskirgan `running` qator -> `failed` / `interrupted` (omborga ham yoziladi - holat hamma joyda bir
    xil). Boshqa qator o'zgarmaydi."""
    if row.get("status") != "running" or now - float(row.get("created_at") or 0) <= stale_after():
        return row
    _fail_running(store, row["id"], "interrupted", INTERRUPTED, now)
    log.info("Yig'ilish %s: bayonnoma %s uzilgan (running %d s) - interrupted", row["meeting_id"], row["id"],
             int(now - float(row.get("created_at") or 0)))
    return store.minutes_row(row["meeting_id"], row["id"]) or {
        **row, "status": "failed", "error_code": "interrupted", "error": INTERRUPTED, "finished_at": int(now)}


def recover(store: Any, now: float | None = None) -> int:
    """Jarayon ishga tushganda (`meetings.start`): ombordagi BARCHA `running` qatorlar oldingi jarayondan
    qolgan - ularni yozayotgan iplar (REST havzasi, Slack/Telegram `generate`) jarayon bilan birga o'lgan
    (API bitta uvicorn jarayoni, bu paytda yangi ish hali boshlanmagan). `stale_after` ni (45 daqiqa)
    kutmasdan darhol `failed` / `interrupted`: aks holda har deploy (restart) dan keyin ilova shu qatorni
    "yozilmoqda" deb ko'rsatib turar, qayta bosish ham (`force` bilan ham) o'lik qatorga qo'shilardi.
    Qaytaradi - belgilangan qatorlar soni."""
    if not store.exists:
        # Ombor hali yo'q (yangi o'rnatish, bo'lim o'chiq): unda qator ham yo'q - ishga tushish uni
        # YARATMASIN (`MeetingStore.exists` qoidasi, ishchi ham shunday).
        return 0
    now = time.time() if now is None else now
    rows = store.rows("SELECT id FROM minutes WHERE status='running'")
    for row in rows:
        _fail_running(store, row["id"], "interrupted", INTERRUPTED, now)
    if rows:
        log.info("Bayonnoma: oldingi jarayondan qolgan %d ta yozuv uzilgan deb belgilandi (interrupted)",
                 len(rows))
    return len(rows)


def _running_row(store: Any, meeting_id: str, lang: str, rev: int, now: float) -> dict[str, Any] | None:
    """Xuddi shu hujjat (til + transkript versiyasi + prompt versiyasi) hozir yozilmoqdami - tirik `running`
    qator (REST fon ishi yoki Slack/Telegram `generate`). Eskirgani shu yerda `interrupted` bo'ladi."""
    for row in reversed(store.minutes_rows(meeting_id)):
        if row["status"] == "running" and row["language"] == lang and int(row["transcript_rev"]) == rev \
                and row["prompt_version"] == prompt.MINUTES_VERSION \
                and _settle(store, row, now)["status"] == "running":
            return row
    return None


def _code(lang: Any) -> str:
    code = normalize(lang)
    if code is None:
        raise MeetingProblem(400, "invalid_language", "Hujjat tili: uz-latn, uz-cyrl, ru yoki en")
    return code


def _source(user: AuthUser, meeting_id: str) -> dict[str, Any]:
    """Hujjat manbasi: egasining yig'ilishi (404), transkripti tayyor (409 `not_ready`) va unda nutq bor."""
    m = service._owned(user.actorId, meeting_id)
    service._require_transcript(m)
    if service.runtime().store.row("SELECT 1 FROM segments WHERE meeting_id=? AND trim(text) <> '' LIMIT 1",
                                   (m["id"],)) is None:
        # Yozuvda nutq yo'q (masalan 5 s jimlik): model chaqirilmaydi - u bo'sh hujjat qaytarib, odam
        # "qayta urinib ko'ring" degan noto'g'ri xabarni olardi (2026-11-05 jonli sinovi).
        raise MeetingProblem(409, "transcript_empty",
                             "Yozuvda nutq topilmadi - bayonnoma uchun gapirilgan yig'ilish yozuvi kerak")
    return m


def _providers(rt: Any, m: dict[str, Any]) -> list[Any]:
    providers = [p for p in llm.minutes_providers(rt, m["actor_id"]) if p.configured]
    if not providers:
        raise MeetingProblem(503, "llm_not_configured",
                             "Bayonnoma uchun model sozlanmagan (CLAUDE_API_KEY / MEETINGS_MINUTES_CHAIN)")
    return providers


def listing(user: AuthUser, meeting_id: str, *, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    m = service._owned(user.actorId, meeting_id)
    store = service.runtime().store
    return {"items": [view(_settle(store, r, now), m) for r in store.minutes_rows(m["id"])]}


def latest(user: AuthUser, meeting_id: str, lang: str) -> dict[str, Any] | None:
    """Shu tilda, joriy transkript bo'yicha TAYYOR hujjat (yoki `None`)."""
    code = _code(lang)
    m = service._owned(user.actorId, meeting_id)
    row = _ready_row(service.runtime().store, m["id"], code, int(m.get("transcript_rev") or 0))
    return view(row, m) if row else None


def generate(user: AuthUser, meeting_id: str, lang: str, *, force: bool = False,
             now: float | None = None) -> dict[str, Any]:
    """Hujjatni yozadi (yoki tayyorini qaytaradi) -> `view`. Xatolar `MeetingProblem`:
    400 til, 409 transkript yo'q yoki unda nutq yo'q, 429 chegara / model 429, 503 model
    sozlanmagan yoki band, 502 model yozolmadi (sabab `detail` da)."""
    now = time.time() if now is None else now
    code = _code(lang)
    rt = service.runtime()
    store = rt.store
    m = _source(user, meeting_id)
    rev = int(m.get("transcript_rev") or 0)
    if not force:
        found = _ready_row(store, m["id"], code, rev)
        if found is not None:
            return view(found, m)
    providers = _providers(rt, m)
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


def start(user: AuthUser, meeting_id: str, lang: str | None = None, *, force: bool = False,
          now: float | None = None) -> tuple[dict[str, Any], bool]:
    """REST (mobil ilova): hujjatni FONDA boshlaydi -> (`view`, boshlandimi).

    `True` (202): tez tekshiruvlar (`generate` dagi tartibda: 400 til, 404, 409 transkript yo'q / nutqsiz,
    503 model sozlanmagan, 429 chegara) shu ipda o'tdi, `running` qator yozildi va model fon ipida
    (`_background`). `False` (200): tayyori bor (`force` bo'lmasa) YOKI xuddi shu hujjat hozir yozilmoqda -
    ikkinchi bosish birinchisiga qo'shiladi, `force` bilan ham (yozilayotgan hujjat baribir yangi): model
    ham, soatlik chegara ham ikkinchi marta sarflanmaydi. `lang` `None` - yig'ilish tilidan (`default_lang`)."""
    now = time.time() if now is None else now
    code = _code(lang) if lang is not None else None
    rt = service.runtime()
    store = rt.store
    m = _source(user, meeting_id)
    code = code or default_lang(m.get("language"))
    rev = int(m.get("transcript_rev") or 0)
    with _start_guard:
        if not force:
            found = _ready_row(store, m["id"], code, rev)
            if found is not None:
                return view(found, m), False
        running = _running_row(store, m["id"], code, rev, now)
        if running is not None:
            return view(running, m), False
        providers = _providers(rt, m)
        service._rate("minutes", user.actorId, settings.meetings_minutes_per_hour)
        minutes_id = _insert(store, m, code, rev, now)
    # Javob - qator yozilgan paytdagi holat (`running`): fon ishi shu ipda bajarilsa ham (testlar) shartnoma
    # bir xil, natijani ilova `get` bilan oladi.
    out = view(store.minutes_row(m["id"], minutes_id), m)

    def job() -> None:
        _background(rt, m, code, rev, providers, minutes_id, force)

    try:
        # `carry`: hisob konteksti (kim, qaysi kanal) fon ipiga ham o'tadi - Claude chaqiruvi odamniki bo'lib yoziladi.
        _submit(carry(job))
    except Exception:
        _fail_running(store, minutes_id, "internal", "fon ishi boshlanmadi")
        raise
    return out, True


def _background(rt: Any, m: dict[str, Any], lang: str, rev: int, providers: list[Any], minutes_id: str,
                force: bool) -> None:
    """Fon ipi (`start`): `generate` dagidek `_lock` ostida model. Natija ham, sabab ham - qatorda; hech
    qanday xato qatorni `running` da qoldirmaydi (qolsa - `stale_after` dan keyin `interrupted`)."""
    store = rt.store
    try:
        with _lock(m["id"], lang):
            if store.minutes_row(m["id"], minutes_id) is None:
                # Navbatda turgan paytda yig'ilish (qatorlari kaskad bilan) o'chirildi - pullik chaqiruv yo'q.
                log.info("Yig'ilish %s: bayonnoma %s - yig'ilish o'chirilgan, model chaqirilmadi", m["id"],
                         minutes_id)
                return
            if not force:
                # Qulf ichida qayta (`generate` dagidek): navbatda turgan paytda boshqa yo'l (Slack/Telegram)
                # xuddi shu hujjatni yozib bo'lgan bo'lsa - model ikkinchi marta chaqirilmaydi, tayyor mazmun
                # shu qatorga ko'chiriladi (ilova aynan shu id ni so'rab turibdi).
                found = _ready_row(store, m["id"], lang, rev)
                if found is not None:
                    store.update_minutes(minutes_id, status="ready", provider=found.get("provider"),
                                         model=found.get("model"), content_json=found["content_json"],
                                         finished_at=int(time.time()), error_code=None, error=None)
                    return
            _fill(rt, m, lang, rev, providers, minutes_id)
    except MeetingProblem as exc:
        # Model / tekshiruv xatosi: `_fill` sababni qatorga yozgan (pastdagi - ehtiyot to'ri); odam ilovada ko'radi.
        log.info("Yig'ilish %s: bayonnoma (fon) yozilmadi: %s", m["id"], exc.code)
        code, reason = exc.code, str(exc.detail)
    except Exception as exc:                                     # noqa: BLE001
        log.exception("Yig'ilish %s: bayonnoma fon ishida kutilmagan xato", m["id"])
        code, reason = "internal", type(exc).__name__
    else:
        return
    try:
        _fail_running(store, minutes_id, code, reason)
    except Exception:                                            # noqa: BLE001
        # Havza `Future` idagi xatoni hech kim o'qimaydi - shu yerda jurnalga; qator eskirgach `interrupted`.
        log.exception("Yig'ilish %s: bayonnoma qatori yangilanmadi", m["id"])


def _submit(job: Callable[[], None]) -> None:
    """Fon ishini beradi: `runner` (testlar) yoki umumiy ip havzasi (birinchi ishda yaratiladi)."""
    global _pool
    custom = runner
    if custom is not None:
        custom(job)
        return
    with _pool_guard:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="minutes")
        pool = _pool
    pool.submit(job)


def stop() -> None:
    """Ilova to'xtaganda (`meetings.stop`): navbatdagi ishlar bekor qilinadi (qatorlari eskirgach
    `interrupted`), boshlangani jarayon bilan tugaydi - Slack/Telegram havzalari kabi."""
    global _pool
    with _pool_guard:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def _write(rt: Any, m: dict[str, Any], lang: str, rev: int, providers: list[Any], now: float) -> dict[str, Any]:
    """Sinxron yo'l (`generate`, chaqiruvchi `_lock` ichida): qator + model."""
    return _fill(rt, m, lang, rev, providers, _insert(rt.store, m, lang, rev, now))


def _insert(store: Any, m: dict[str, Any], lang: str, rev: int, now: float) -> str:
    minutes_id = new_id()
    # Qator OLDIN yoziladi (`running`): prompt yig'ish yoki model xatosi ham qatorda qoladi (`failed`);
    # REST yo'lida ilova aynan shu id ni so'rab turadi.
    store.insert_minutes({"id": minutes_id, "meeting_id": m["id"], "language": lang, "transcript_rev": rev,
                          "prompt_version": prompt.MINUTES_VERSION, "status": "running", "created_at": int(now)})
    return minutes_id


def _fill(rt: Any, m: dict[str, Any], lang: str, rev: int, providers: list[Any], minutes_id: str) -> dict[str, Any]:
    """`running` qatorga model natijasi (`ready`) yoki sabab (`failed` + `MeetingProblem`)."""
    store = rt.store

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


def get(user: AuthUser, meeting_id: str, minutes_id: str, *, now: float | None = None) -> dict[str, Any]:
    """Ko'rinish + mazmun (tayyor bo'lsa). REST ilovasi `start` dan keyin shuni so'rab turadi."""
    now = time.time() if now is None else now
    m = service._owned(user.actorId, meeting_id)
    row = _settle(service.runtime().store, _row_or_404(m, minutes_id), now)
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

"""BAYONNOMA - yig'ilish yozuvidan rasmiy hujjat (ega topshirig'i, 2026-11-04).

Namuna: bank Boshqaruv raisi huzuridagi yig'ilish "БАЁНИ" - tasdiq bloki, sarlavha, sana/shahar,
raislik qiluvchi, qatnashganlar, KUN TARTIBI, har band bo'yicha bayon, "ҚАРОР ҚИЛАДИ:", rim
raqamli bo'limlar ichida UZLUKSIZ raqamlangan bandlar (muddat + mas'ul + vazifa + buyruq fe'li),
nazorat bandi. Audiodan faqat TANASI chiqadi: kun tartibi, bayon, bandlar. Tasdiq bloki, №,
QR, bank nomi, shahar, rais va qatnashuvchilar lavozimlari, kelishuvchilar - BO'SH JOY
(`text.BLANK`), hujjat tizimi yoki kotib to'ldiradi (ega qarori: hozircha bo'sh). Ega o'zi aytgan
sarlavha qiymatlari (rais, qatnashchilar, tashkilot, shahar) - 2026-11-12 dan hujjatga yoziladi.

QUVUR (bitta model chaqiruvi; bot ipida 1-3 daqiqa yoki fon ipida):
    prompt.build   transkript (+ jonli vazifalar, ega ko'rsatmalari) -> Claude ga ko'rsatma; chiqish tili tanlanadi
    llm.run_chain  `MEETINGS_MINUTES_CHAIN` (default faqat `claude`); javob - qat'iy JSON (`shapes.minutes`)
    validate       shakl, chegaralar, ASOSLASH: manba qatorlar mavjud, ismlar transkriptda yoki egadan
                   (yo'q ism -> `BLANK`), yozuv (kirill/lotin) mos; ogohlantirishlar `quality`
    store          `minutes` jadvali (v5, v8): til + transkript versiyasi + prompt versiyasi bo'yicha
                   TAKRORLANMAYDI (`force` bo'lmasa tayyori qaytadi); tahrir - yangi qator (versiya zanjiri)
    compose/render Letter formatli DOCX (Arial 13) va PDF (DejaVu Sans) - asosiy natija Word, PDF nusxa.

HUJJAT TILI foydalanuvchi tanlovi: `uz-latn` | `uz-cyrl` | `ru` | `en` (`text.LANGS`); o'zbek
yig'ilish uchun default - kirill (bank hujjati). Transkript tilidan farq qilishi mumkin - model
o'giradi, iqtibos va kodlar o'zgarmaydi.

KIMNING NOMIDAN: xulosa kabi - yig'ilish egasi (`service._owned`); Slack'da umumiy hisob,
Telegram'da odamning o'z hisobi. Soatlik chegaralar: yangi hujjat - `MEETINGS_MINUTES_PER_HOUR` (hisobga),
tahrir - `MEETINGS_MINUTES_EDITS_PER_HOUR` (so'rovchiga: Slack'da har odamga alohida). Har chaqiruv pullik.

UCH KIRISH, BITTA ISH (2026-11-06; tahrir - 2026-11-12):
    start      ASINXRON - REST / mobil ilova va chatdagi "tayyorla" so'rovi: tez tekshiruvlar so'rov ipida, qaror
               (`start` jadvali: tayyori / yozilayotgani / yangi hujjat / yangi ko'rsatmalar bo'yicha tahrir),
               `running` qator yoziladi; model fon ipida (`runner` yoki `WORKERS` li havza) - `_run`
    revise     ASINXRON - chatdagi o'zgartirish so'rovi: joriy hujjatning YANGI VERSIYASI (`parent_id`, `revision`),
               faqat so'ralgan joy o'zgaradi (`prompt.build_revision`); o'zgarmasa - yangi versiya yo'q (`no_change`)
    generate   SINXRON - Slack va Telegram til tugmasi: `start(inline=True)` (ish shu ipda); boshqa yo'lning
               yozilayotgan ishiga qo'shilsa - natijani `wait` bilan kutadi
Hammasi bir xil tekshiruv (`_code`, `_source`, `_providers`), qator tanlash (`rows`: HEAD / BASE) va ishdan (`_run` ->
`_fill`) foydalanadi. Ish `_lock` (yig'ilish + til) ostida: navbatdagi tahrir oldingisi tugagach, O'SHA PAYTDAGI
joriy hujjat (BASE) ustiga yoziladi (`_run` ota-versiyani qulf ichida qayta tanlaydi). `running` qator `stale_after()`
dan eski bo'lsa - uni yozayotgan ip jarayon bilan o'lgan (restart, yiqilish): `failed` / `interrupted` (`_settle`).

KO'RSATMALAR (`store.notes`): yozishdan oldin aytilganlar (rais, qatnashchilar, nimaga e'tibor berish). Qator
yozilganda so'rovchining faol ko'rsatmalari qatorga "suratga" olinadi (`guidance_json`) - qaysilari hujjatda bor,
qaysilari hali kutilmoqda (`rows.pending`) shundan ma'lum. Kutilayotgan ko'rsatma bilan til bosilsa - hujjat qaytadan
yozilmaydi, joriy hujjatning tahriri bo'ladi: avvalgi o'zgartirishlar saqlanadi.

`rows` (HEAD / BASE / joriy til / ko'rsatmalar qamrovi - `service` ni import qilmaydi), `diff` (versiyalar orasidagi
o'zgarishlar), `state` (chat modeli ko'radigan hujjat va holat bloklari) - shu paket ichidagi umumiy modullar.
"""

from __future__ import annotations

import logging
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Mapping, Sequence

from ....core.config import settings
from ....schemas.auth import AuthUser
from .. import export, llm, prompts, service
from ..errors import MeetingProblem
from ..store import jdump, jload, new_id
from ...analytics.meter import carry
from ...integrations.ollama import OllamaError
from ..summarize import LlmBusy, LlmFailed, LlmRateLimited, LlmUnavailable, parse_json
from . import compose, diff, prompt, render, rows, validate
from . import state, text  # noqa: F401 - umumiy modullar (`minutes.state`, `minutes.text`)
from .rows import STALE_MARGIN_SEC, base_row, current_lang, stale_after  # noqa: F401 - umumiy nomlar
from .text import BLANK, LANG_TITLES, LANGS, default_lang, normalize  # noqa: F401 - umumiy nomlar

log = logging.getLogger(__name__)

#: Hujjat formatlari -> (Content-Type, kengaytma). Asosiy natija - Word; PDF - nusxa; MD - ko'rish uchun.
FORMATS = {"docx": export.FORMATS["docx"], "pdf": export.FORMATS["pdf"], "md": export.FORMATS["md"]}

#: Fon ishi iplari (`start`). Claude klientida bitta slot (`meetings._claude(1, ...)`, xulosa bilan umumiy):
#: ko'p ip faqat semaforda o'tirib, `meetings_claude_timeout` dan keyin `llm_busy` bilan yiqilardi. Ikkinchi
#: ip - boshqa yig'ilishning hujjati birinchisi tugashi bilan navbatsiz boshlansin.
WORKERS = 2
#: Uzilgan qatorning sababi (`error.message`) - odam uchun: tugma bosilsa yangisi yoziladi.
INTERRUPTED = "Bayonnoma yozilishi uzilib qoldi - qayta urinib ko'ring"
#: Bitta yig'ilish + til uchun bir vaqtda TIRIK `running` qatorlar chegarasi: navbatdagi tahrirlar shu chegaragacha
#: kutadi, ortig'i - 409 `minutes_busy` (`_check_queue`).
MAX_LIVE = 3
#: Botlar `wait` ining eng uzun kutishi (soniya; Claude slotini xulosa bilan bo'lishadi) va so'rash oralig'i.
WAIT_SEC = 900.0
WAIT_EVERY = 2.0
#: Qator xato kodi -> (HTTP holati, odamga matn). `_fill` ham, `failure` ham shu matnlarni ishlatadi; birinchi
#: beshtasi - avvalgi `_fill` matnlari, baytma-bayt (Slack/Telegram xabarlari va testlar).
FAILURES: dict[str, tuple[int, str]] = {
    "llm_not_configured": (503, "Bayonnoma modeli sozlanmagan"),
    "llm_busy": (503, "Model hozir band - birozdan keyin qayta urinib ko'ring"),
    "llm_rate_limited": (429, "Model chegarasi - birozdan keyin qayta urinib ko'ring"),
    "llm_failed": (502, "Model bayonnomani yozolmadi - qayta urinib ko'ring"),
    "internal": (500, "Bayonnoma yozilmadi: ichki xato"),
    "interrupted": (503, INTERRUPTED),
    "no_change": (409, "Bayonnomada o'zgarish bo'lmadi - nimani o'zgartirish kerakligini aniqroq yozing "
                       "(masalan: «3-bandda muddat - 1-dekabr»)"),
    "minutes_outdated": (409, "Yozuv qayta o'girilgan - bayonnomani qaytadan tayyorlang"),
    "minutes_missing": (409, "Bu tilda tahrirlash uchun tayyor bayonnoma yo'q - avval bayonnomani tayyorlang"),
    "minutes_busy": (409, "Bayonnomaning oldingi o'zgarishlari hali tayyorlanmoqda - tugashini kuting"),
}
#: Tahrirda model yiqilsa (`llm_failed`, `kind` revise) - odamga matn.
REVISE_FAILED = "Model bayonnomani tahrirlay olmadi - qayta urinib ko'ring"
#: `Retry-After` (soniya): model band yoki o'z chegarasida.
_RETRY_AFTER = {"llm_busy": "30", "llm_rate_limited": "60"}
#: O'zgartirish so'rovi matnining (egasining so'zlari) va chat modeli talqinining eng katta uzunligi (belgi).
REQUEST_CHARS = 1000
#: Tahrir promptidagi oxirgi suhbat navbatlari (havolalarni tushunish uchun).
RECENT_TURNS = 6
#: Tahrir promptidagi oldingi o'zgartirish so'rovlari: eng yangilari, soni va jami uzunligi chegarasida.
EARLIER_REQUESTS = 20
EARLIER_CHARS = 4000

#: Fon ishini kim bajaradi. `None` - umumiy ip havzasi (`WORKERS`). Testlar o'rniga `lambda job: job()`
#: (shu ipda - deterministik) yoki `jobs.append` (keyin qo'lda ishga tushiradi) qo'yadi.
runner: Callable[[Callable[[], None]], Any] | None = None

_pool: ThreadPoolExecutor | None = None
_pool_guard = threading.Lock()
#: `start` / `revise` dagi "tayyormi / yozilmoqdami -> chegara -> qator" ketma-ketligi uchun QISQA qulf (ombor
#: so'rovlari): bir vaqtda kelgan ikki bosish ikkita qator va ikkita model chaqiruvi bo'lib ketmasin. Modelni `_lock`
#: kutadi.
_start_guard = threading.Lock()

_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(meeting_id: str, lang: str) -> threading.Lock:
    """Bitta yig'ilish + til uchun bir vaqtda BITTA model chaqiruvi: ikki odam (yoki ikki bosish)
    bir xil hujjatni ikki marta to'latmasin, navbatdagi tahrir esa oldingisining natijasi ustiga yozilsin."""
    with _locks_guard:
        if len(_locks) > 500:
            for key in [k for k, lock in _locks.items() if not lock.locked()]:
                _locks.pop(key, None)
        return _locks.setdefault((meeting_id, lang), threading.Lock())


def _speakers(meeting_id: str) -> dict[str, dict[str, Any]]:
    return {sp["id"]: sp for sp in service.runtime().store.speakers(meeting_id)}


# --- ko'rinish -----------------------------------------------------------------------------------


def view(row: dict[str, Any], m: dict[str, Any], *, asker: str | None = None,
         active: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Qator -> ko'rinish (mazmunsiz): holat, kim yozgani, bandlar soni, izohlar, eskirganmi; versiya zanjiri
    (`kind`, `version` = `revision` + 1, `parentId`), o'zgartirish so'rovi (`request` - egasining so'zlari) va
    ota-versiyaga nisbatan o'zgarishlar (`changes`), egadan kelgan sarlavha qiymatlari (`header` - faqat
    to'ldirilganlari), ko'rsatmalar: hujjatga berilganlari soni (`notesApplied`) va - faqat TAYYOR hujjatda -
    `asker` ning unda hali yo'q faol ko'rsatmalari (`pendingNotes`; `active` - oldindan o'qilgan `store.notes`).
    Izohlar hujjatdagidek (`compose.render_notes`): Slack/Telegram xabarida `[S#]` ko'rinmasin."""
    ready = row.get("status") == "ready"
    content = (jload(row.get("content_json")) or {}) if ready else {}
    sections = content.get("sections") or []
    quality = content.get("quality") or {}
    notes = compose.render_notes(content, speakers=_speakers(m["id"]) if content.get("notes") else None,
                                 lang=row["language"])
    error = None
    if row.get("status") == "failed":
        error = {"code": row.get("error_code") or "llm_failed", "message": row.get("error") or ""}
    pending = 0
    if ready:
        if active is None:
            active = service.runtime().store.notes(m["id"], asker=asker)
        pending = len(rows.pending(row, active))
    request = jload(row.get("request_json"))
    return {"id": row["id"], "meetingId": row["meeting_id"], "language": row["language"], "status": row["status"],
            "createdAt": service.iso(row.get("created_at")), "finishedAt": service.iso(row.get("finished_at")),
            "provider": row.get("provider"), "model": row.get("model"),
            "transcriptRev": int(row.get("transcript_rev") or 0),
            "stale": int(row.get("transcript_rev") or 0) < int(m.get("transcript_rev") or 0),
            "agendaCount": len(content.get("agenda") or []), "sectionCount": len(sections),
            "itemCount": sum(len(s.get("items") or []) for s in sections),
            "notes": notes, "warnings": list(quality.get("warnings") or []),
            "error": error,
            "kind": _kind(row), "version": int(row.get("revision") or 0) + 1, "parentId": row.get("parent_id") or None,
            "request": (str(request.get("text") or "") or None) if isinstance(request, dict) else None,
            "notesApplied": len(rows.snapshot(row)), "pendingNotes": pending,
            "header": _header_view(content.get("header")), "changes": jload(row.get("changes_json")) or None}


def _kind(row: Mapping[str, Any]) -> str:
    """"revise" - tahrir (ota-versiyasi bor), "generate" - transkriptdan yozilgan asl hujjat."""
    return "revise" if row.get("parent_id") else "generate"


def _header_view(raw: Any) -> dict[str, Any] | None:
    """Egadan kelgan sarlavha qiymatlari - faqat to'ldirilganlari (`HEADER_KEYS` tartibida); hech biri yo'q - `None`."""
    if not isinstance(raw, dict):
        return None
    out = {key: raw[key] for key in validate.HEADER_KEYS if raw.get(key)}
    return out or None


# --- qatorlarni tanlash ----------------------------------------------------------------------------


def _ready_row(store: Any, meeting_id: str, lang: str, rev: int) -> dict[str, Any] | None:
    """HEAD (`rows.ready_row`): shu tilda joriy transkript versiyasi bo'yicha tayyor hujjat (`READY_VERSIONS`)."""
    return rows.ready_row(store, meeting_id, lang, rev)


def _live_rows(store: Any, meeting_id: str, lang: str, now: float, *, rev: int | None = None,
               kind: str | None = None) -> list[dict[str, Any]]:
    """Shu tilning TIRIK `running` qatorlari, YANGISI birinchi; eskirganlari shu yerda `interrupted` (`_settle`).
    `rev` - faqat shu transkript versiyasidagilari; `kind` - "generate" (asl hujjat, `parent_id` yo'q) yoki
    "revise"."""
    out: list[dict[str, Any]] = []
    for row in reversed(store.minutes_rows(meeting_id)):
        if row["status"] != "running" or row["language"] != lang:
            continue
        if rev is not None and int(row["transcript_rev"]) != int(rev):
            continue
        if kind is not None and _kind(row) != kind:
            continue
        if _settle(store, row, now)["status"] == "running":
            out.append(row)
    return out


def _tip(store: Any, meeting_id: str, lang: str, rev: int, now: float) -> dict[str, Any] | None:
    """Til tugmasi nimani oladi (shu transkript versiyasi, `READY_VERSIONS`): TIRIK `running` qator bo'lsa - eng
    yangisi (navbatdagi tahrir: u tugagach joriy hujjat o'shaniki - asos qulf ichida tanlanadi); aks holda eng keyin
    tayyor bo'lgan hujjat (HEAD, `rows.newest_ready`). Yiqilgan qator hisobga olinmaydi."""
    found = [row for row in store.minutes_rows(meeting_id)
             if row["language"] == lang and int(row["transcript_rev"]) == int(rev)
             and row["prompt_version"] in prompt.READY_VERSIONS]
    for row in reversed(found):
        if row["status"] == "running" and _settle(store, row, now)["status"] == "running":
            return row
    return rows.newest_ready(found)


def _snapshot(row: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Qator yozilganda berilgan ko'rsatmalar (`guidance_json.notes`): [{"id", "text"}]."""
    return rows.snapshot(row)


def _check_queue(store: Any, meeting_id: str, lang: str, now: float, *,
                 live: Sequence[Mapping[str, Any]] | None = None) -> None:
    """Shu til uchun `MAX_LIVE` ta ish allaqachon tirik - 409 `minutes_busy` (navbat cheksiz o'smasin)."""
    live = _live_rows(store, meeting_id, lang, now) if live is None else live
    if len(live) >= MAX_LIVE:
        raise _problem("minutes_busy")


def _by_turn(store: Any, m: Mapping[str, Any], turn_id: str | None) -> dict[str, Any] | None:
    """Shu chat navbati allaqachon boshlagan qator (bitta navbat - bitta ish) - faqat SHU yig'ilishniki."""
    if not turn_id:
        return None
    row = store.minutes_by_turn(turn_id)
    return row if row is not None and row["meeting_id"] == m["id"] else None


def _fail_running(store: Any, minutes_id: str, code: str, reason: str, now: float | None = None) -> None:
    """Qator HALI `running` bo'lsa - `failed`. Shart ombor so'rovining o'zida: shu orada tugagan ishning
    natijasi (`ready` yoki aniq sabab) ustidan yozilmaydi."""
    store.execute("UPDATE minutes SET status='failed', error_code=?, error=?, finished_at=? "
                  "WHERE id=? AND status='running'",
                  (code, str(reason)[:300], int(time.time() if now is None else now), minutes_id))


def _settle(store: Any, row: dict[str, Any], now: float) -> dict[str, Any]:
    """Eskirgan `running` qator -> `failed` / `interrupted` (omborga ham yoziladi - holat hamma joyda bir
    xil). Boshqa qator o'zgarmaydi."""
    if row.get("status") != "running" or rows.is_live(row, now):
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
    found = store.rows("SELECT id FROM minutes WHERE status='running'")
    for row in found:
        _fail_running(store, row["id"], "interrupted", INTERRUPTED, now)
    if found:
        log.info("Bayonnoma: oldingi jarayondan qolgan %d ta yozuv uzilgan deb belgilandi (interrupted)",
                 len(found))
    return len(found)


# --- tekshiruvlar va xatolar ---------------------------------------------------------------------------


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


def _problem(code: str, detail: str | None = None) -> MeetingProblem:
    """Xato kodi -> `MeetingProblem`: holat va matn `FAILURES` dan (noma'lum kod - `llm_failed` niki), model band yoki
    chegarada bo'lsa `Retry-After`."""
    status, message = FAILURES.get(code, FAILURES["llm_failed"])
    retry = _RETRY_AFTER.get(code)
    return MeetingProblem(status, code, detail or message, headers={"Retry-After": retry} if retry else None)


def _refund(m: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    """Ish bajarilmay qoldi (asosi yo'qoldi, fon ishi boshlanmadi) - olingan soatlik joy qaytadi: tahrir -
    so'rovchining `minutes_edit` chegarasiga, asl hujjat - hisobning `minutes` chegarasiga."""
    if row.get("parent_id"):
        service._refund("minutes_edit", int(m["actor_id"]), settings.meetings_minutes_edits_per_hour,
                        scope=row.get("asker"))
    else:
        service._refund("minutes", int(m["actor_id"]), settings.meetings_minutes_per_hour)


# --- o'qish ---------------------------------------------------------------------------------------------


def listing(user: AuthUser, meeting_id: str, *, asker: str | None = None,
            now: float | None = None) -> dict[str, Any]:
    """Hamma qatorlar (eskisi birinchi) va `asker` ning faol ko'rsatmalari soni (`notes`)."""
    now = time.time() if now is None else now
    m = service._owned(user.actorId, meeting_id)
    store = service.runtime().store
    active = store.notes(m["id"], asker=asker)
    return {"items": [view(_settle(store, r, now), m, asker=asker, active=active) for r in store.minutes_rows(m["id"])],
            "notes": len(active)}


def latest(user: AuthUser, meeting_id: str, lang: str, *, asker: str | None = None) -> dict[str, Any] | None:
    """Shu tilda, joriy transkript bo'yicha TAYYOR hujjat - HEAD (yoki `None`)."""
    code = _code(lang)
    m = service._owned(user.actorId, meeting_id)
    row = _ready_row(service.runtime().store, m["id"], code, int(m.get("transcript_rev") or 0))
    return view(row, m, asker=asker) if row else None


def status(user: AuthUser, meeting_id: str, minutes_id: str, *, asker: str | None = None,
           now: float | None = None) -> dict[str, Any]:
    """Bitta qatorning jonli holati (mazmunsiz): eskirgan `running` shu yerda `interrupted`."""
    m, row = _current(user, meeting_id, minutes_id, now)
    return view(row, m, asker=asker)


def get(user: AuthUser, meeting_id: str, minutes_id: str, *, asker: str | None = None,
        now: float | None = None) -> dict[str, Any]:
    """Ko'rinish + mazmun (tayyor bo'lsa). REST ilovasi `start` dan keyin shuni so'rab turadi."""
    m, row = _current(user, meeting_id, minutes_id, now)
    out = view(row, m, asker=asker)
    out["content"] = jload(row.get("content_json")) if row["status"] == "ready" else None
    return out


def _current(user: AuthUser, meeting_id: str, minutes_id: str, now: float | None) -> tuple[dict[str, Any], dict]:
    now = time.time() if now is None else now
    m = service._owned(user.actorId, meeting_id)
    return m, _settle(service.runtime().store, _row_or_404(m, minutes_id), now)


def _row_or_404(m: dict[str, Any], minutes_id: str) -> dict[str, Any]:
    row = service.runtime().store.minutes_row(m["id"], str(minutes_id or ""))
    if row is None:
        raise MeetingProblem(404, "minutes_not_found", "Bayonnoma topilmadi")
    return row


def wait(user: AuthUser, meeting_id: str, minutes_id: str, *, asker: str | None = None,
         sleep: Callable[[float], Any] = time.sleep, every: float = WAIT_EVERY,
         timeout: float = WAIT_SEC) -> dict[str, Any]:
    """Botlar (Slack, Telegram): qator `running` dan chiqquncha kutadi -> oxirgi ko'rinish. `timeout` dan keyin ham
    yozilayotgan bo'lsa - `running` qaytadi (chaqiruvchi "hali tayyorlanmoqda" deydi). Aylanishlar SONI bilan
    chegaralangan (soat bilan emas): testdagi `sleep` vaqtni surmaydi."""
    found = status(user, meeting_id, minutes_id, asker=asker)
    for _ in range(max(1, int(timeout / every))):
        if found["status"] != "running":
            return found
        sleep(every)
        found = status(user, meeting_id, minutes_id, asker=asker)
    return found


def failure_detail(found: Mapping[str, Any]) -> str:
    """Yiqilgan qator ko'rinishi -> odamga sabab: tahrirda model yiqilsa `REVISE_FAILED`, aks holda `FAILURES` matni
    (noma'lum kod - `llm_failed` niki)."""
    code = (found.get("error") or {}).get("code") or "llm_failed"
    if code == "llm_failed" and found.get("kind") == "revise":
        return REVISE_FAILED
    return FAILURES.get(code, FAILURES["llm_failed"])[1]


def failure(found: Mapping[str, Any]) -> MeetingProblem:
    """Yiqilgan qator ko'rinishi -> `MeetingProblem` (holat `FAILURES` dan, matn `failure_detail`, model band - 30 s,
    model chegarasi - 60 s `Retry-After`): sinxron `generate` xatoni avvalgidek otadi."""
    code = (found.get("error") or {}).get("code") or "llm_failed"
    return _problem(code, failure_detail(found))


# --- boshlash ---------------------------------------------------------------------------------------------


def generate(user: AuthUser, meeting_id: str, lang: str, *, force: bool = False, asker: str | None = None,
             now: float | None = None, sleep: Callable[[float], Any] = time.sleep) -> dict[str, Any]:
    """Slack va Telegram til tugmasi (SINXRON): `start` qarori, ish shu ipda -> `view`. Boshqa yo'lning yozilayotgan
    ishiga qo'shilsa - natijasi kutiladi (`wait`, `WAIT_SEC` gacha; undan keyin ham `running` bo'lishi mumkin -
    chaqiruvchi "hali tayyorlanmoqda" deydi). Xatolar `MeetingProblem`: 400 til, 409 transkript yo'q yoki unda nutq
    yo'q / navbat to'la, 429 chegara / model 429, 503 model sozlanmagan yoki band, 502 model yozolmadi, 500 ichki
    xato (sabab `detail` da)."""
    found, started = start(user, meeting_id, lang, force=force, asker=asker, now=now, inline=True)
    if found["status"] == "running":
        found = wait(user, meeting_id, found["id"], asker=asker, sleep=sleep)
    if found["status"] == "failed":
        if not started and not force:
            # BOSHQA yo'lning ishiga qo'shilgan edik (masalan chatdagi tahrir) va u yiqildi ("o'zgarish bo'lmadi",
            # model xatosi): tayyor hujjat bor bo'lsa - o'sha yuboriladi, begona so'rovning xatosi ko'rsatilmaydi.
            head = latest(user, meeting_id, lang, asker=asker)
            if head is not None:
                return head
        raise failure(found)
    return found


def start(user: AuthUser, meeting_id: str, lang: str | None = None, *, force: bool = False,
          asker: str | None = None, turn_id: str | None = None, now: float | None = None,
          inline: bool = False) -> tuple[dict[str, Any], bool]:
    """Hujjatni boshlaydi (REST, chatdagi "tayyorla", botlar - `generate`) -> (`view`, boshlandimi).

    Tez tekshiruvlar shu ipda: 400 til, 404, 409 transkript yo'q / nutqsiz. Qaror (`_start_guard` ostida, shu
    tartibda):
        1. `turn_id` ning qatori bor (navbat qayta yuborildi)      -> o'sha, False
        2. `force` va shu versiyada asl hujjat yozilmoqda          -> unga qo'shiladi, False
        3. `force`                                                -> yangi asl hujjat, barcha ko'rsatmalar bilan
        4. tayyori ham, yozilayotgani ham yo'q (`_tip`)           -> yangi asl hujjat ("minutes" chegarasi)
        5. bor va `asker` ning hamma faol ko'rsatmalari unda      -> o'sha (tayyori qayta yuboriladi, yozilayotganiga
                                                                     qo'shiladi), False, BEPUL
        6. bor, lekin yangi ko'rsatmalar bor                      -> joriy hujjatning TAHRIRI (`parent` - o'sha;
                                                                     `minutes_edit` chegarasi, so'rovchiga)
    Yangi qatordan oldin: 409 `minutes_busy` (shu tilda `MAX_LIVE` ta ish tirik), 503 model sozlanmagan, 429 chegara -
    qator ham, chegara ham yo'q. `True` (202): `running` qator yozildi, ish fon ipida (`_run`); `inline` - ish SHU ipda, javob - ishdan
    keyingi holat (`generate`). `lang` `None` - yig'ilish tilidan (`default_lang`)."""
    now = time.time() if now is None else now
    code = _code(lang) if lang is not None else None
    rt = service.runtime()
    store = rt.store
    m = _source(user, meeting_id)
    code = code or default_lang(m.get("language"))
    rev = int(m.get("transcript_rev") or 0)
    with _start_guard:
        same = _by_turn(store, m, turn_id)
        if same is not None:
            return view(_settle(store, same, now), m, asker=asker), False
        live = _live_rows(store, m["id"], code, now, rev=rev, kind="generate") if force else []
        if live:
            # Yozilayotgan asl hujjat baribir yangi: ikkinchi bosish modelni ham, chegarani ham qayta sarflamaydi.
            return view(live[0], m, asker=asker), False
        tip = None if force else _tip(store, m["id"], code, rev, now)
        active = store.notes(m["id"], asker=asker)
        if tip is not None and not rows.pending(tip, active):
            return view(tip, m, asker=asker, active=active), False
        _check_queue(store, m["id"], code, now)
        providers = _providers(rt, m)
        if tip is not None:
            # Yangi ko'rsatmalar - hujjat qaytadan yozilmaydi: joriy hujjatning tahriri, avvalgi o'zgartirishlar qoladi.
            service._rate("minutes_edit", user.actorId, settings.meetings_minutes_edits_per_hour, scope=asker)
        else:
            service._rate("minutes", user.actorId, settings.meetings_minutes_per_hour)
        minutes_id = _insert(store, m, code, rev, now, asker=asker, turn_id=turn_id, notes=active, parent=tip)
    return _launch(rt, m, code, rev, providers, minutes_id, force=force, asker=asker, inline=inline)


def revise(user: AuthUser, meeting_id: str, lang: str, request: Mapping[str, Any], *, asker: str | None = None,
           turn_id: str | None = None, now: float | None = None) -> tuple[dict[str, Any], bool]:
    """Chatdagi o'zgartirish so'rovi (ASINXRON) -> (`view`, boshlandimi). `request` - {"text": egasining so'zlari,
    "instruction": chat modelining talqini yoki `None`}.

    Joriy hujjat (BASE - shu transkript avlodining eng yangi tayyor hujjati; qator tahriridan keyin ham) yoki shu
    tilda yozilayotgan ish bo'lmasa - 409 (`minutes_outdated`: yozuv qayta o'girilgan, `minutes_missing`: bu tilda
    hujjat yo'q). Navbat to'la - 409 `minutes_busy`; 503 model sozlanmagan; 429 tahrir chegarasi (so'rovchiga). Ota-
    versiya VAQTINCHA (yozilayotgan eng yangi ish yoki BASE): ish qulf ichida uni o'sha paytdagi BASE ga almashtiradi
    (`_run`) - navbatdagi tahrir oldingisining natijasi ustiga yoziladi."""
    now = time.time() if now is None else now
    code = _code(lang)
    rt = service.runtime()
    store = rt.store
    m = _source(user, meeting_id)
    words = str((request or {}).get("text") or "").strip()
    if not words:
        raise MeetingProblem(400, "invalid_request", "O'zgartirish so'rovi bo'sh")
    reading = str((request or {}).get("instruction") or "").strip()[:REQUEST_CHARS] or None
    rev = int(m.get("transcript_rev") or 0)
    with _start_guard:
        same = _by_turn(store, m, turn_id)
        if same is not None:
            return view(_settle(store, same, now), m, asker=asker), False
        base, reason = base_row(store, m, code)
        live = _live_rows(store, m["id"], code, now)
        if base is None and not live:
            raise _problem(reason or "minutes_missing")
        _check_queue(store, m["id"], code, now, live=live)
        providers = _providers(rt, m)
        service._rate("minutes_edit", user.actorId, settings.meetings_minutes_edits_per_hour, scope=asker)
        minutes_id = _insert(store, m, code, rev, now, asker=asker, turn_id=turn_id,
                             notes=store.notes(m["id"], asker=asker), parent=live[0] if live else base,
                             request={"text": words[:REQUEST_CHARS], "instruction": reading})
    return _launch(rt, m, code, rev, providers, minutes_id, asker=asker)


def _insert(store: Any, m: dict[str, Any], lang: str, rev: int, now: float, *, asker: str | None = None,
            turn_id: str | None = None, notes: Iterable[Mapping[str, Any]] = (),
            parent: Mapping[str, Any] | None = None, request: Mapping[str, Any] | None = None) -> str:
    """`running` qator OLDIN yoziladi: prompt yig'ish yoki model xatosi ham qatorda qoladi (`failed`); REST yo'lida
    ilova aynan shu id ni so'rab turadi. `transcript_gen` - qaysi transkript avlodi bo'yicha (tahrir asosi - faqat
    joriy avlod hujjati); `notes` - so'rovchining faol ko'rsatmalari (surat: qaysilari shu hujjatga berildi);
    `parent` - tahrirning ota-versiyasi (`revision` = ota + 1); `request` - o'zgartirish so'rovi."""
    minutes_id = new_id()
    store.insert_minutes({
        "id": minutes_id, "meeting_id": m["id"], "language": lang, "transcript_rev": rev,
        "transcript_gen": int(m.get("transcript_gen") or 0), "prompt_version": prompt.MINUTES_VERSION,
        "status": "running", "created_at": int(now), "asker": asker, "turn_id": turn_id,
        "parent_id": parent["id"] if parent else None,
        "revision": int(parent.get("revision") or 0) + 1 if parent else 0,
        "guidance_json": jdump({"notes": [{"id": str(n["id"]), "text": str(n.get("text") or "")} for n in notes]}),
        "request_json": jdump(dict(request)) if request is not None else None})
    return minutes_id


def _launch(rt: Any, m: dict[str, Any], lang: str, rev: int, providers: list[Any], minutes_id: str, *,
            force: bool = False, asker: str | None = None, inline: bool = False) -> tuple[dict[str, Any], bool]:
    """Yozilgan `running` qatorning ishi: `inline` - shu ipda (javob - ishdan keyingi holat), aks holda fon ipida
    (javob - qator yozilgan paytdagi holat; natijani ilova `get`, botlar `wait` bilan oladi)."""
    store = rt.store

    def job() -> None:
        _run(rt, m, lang, rev, providers, minutes_id, force=force)

    if inline:
        job()
        row = store.minutes_row(m["id"], minutes_id)
        if row is None:
            # Ish paytida yig'ilish (qatorlari kaskad bilan) o'chirildi.
            raise MeetingProblem(404, "minutes_not_found", "Bayonnoma topilmadi")
        return view(row, store.meeting_any(m["id"]) or m, asker=asker), True
    row = store.minutes_row(m["id"], minutes_id)
    out = view(row, m, asker=asker)
    try:
        # `carry`: hisob konteksti (kim, qaysi kanal) fon ipiga ham o'tadi - Claude chaqiruvi odamniki bo'lib yoziladi.
        _submit(carry(job))
    except Exception:
        _fail_running(store, minutes_id, "internal", "fon ishi boshlanmadi")
        _refund(m, row)
        raise
    return out, True


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


# --- ish ------------------------------------------------------------------------------------------------


def _run(rt: Any, m: dict[str, Any], lang: str, rev: int, providers: list[Any], minutes_id: str, *,
         force: bool = False) -> None:
    """Bitta qatorning ishi (fon ipida yoki `inline` - shu ipda) `_lock` ostida. Natija ham, sabab ham - qatorda; hech
    qanday xato qatorni `running` da qoldirmaydi (qolsa - `stale_after` dan keyin `interrupted`).

    Asl hujjat: navbatda turgan paytda boshqa yo'l xuddi shu hujjatni yozib bo'lgan bo'lsa - model chaqirilmaydi
    (`_copy_ready`). Tahrir: ota-versiya QULF ICHIDA qayta tanlanadi (BASE) - oldingi tahrir tugagan bo'lsa uning
    ustiga; asos yo'qolgan bo'lsa (yozuv qayta o'girildi) - qator `failed`, olingan chegara qaytadi."""
    store = rt.store
    try:
        with _lock(m["id"], lang):
            row = store.minutes_row(m["id"], minutes_id)
            if row is None or row["status"] != "running":
                # Navbatda turgan paytda yig'ilish o'chirildi yoki qator yopildi (uzildi) - pullik chaqiruv yo'q.
                log.info("Yig'ilish %s: bayonnoma %s - qator yo'q yoki yopilgan, model chaqirilmadi", m["id"],
                         minutes_id)
                return
            fresh = store.meeting_any(m["id"]) or m
            rev = _restamp(store, row, fresh)
            row = store.minutes_row(m["id"], minutes_id) or row
            if not row.get("parent_id"):
                if not force and _copy_ready(store, m["id"], lang, rev, row):
                    return
                _fill(rt, fresh, lang, rev, providers, row, force=force)
                return
            base, reason = base_row(store, fresh, lang)
            if base is None:
                reason = reason or "minutes_missing"
                _refund(m, row)
                _fail_running(store, minutes_id, reason, FAILURES[reason][1])
                log.info("Yig'ilish %s: bayonnoma tahriri %s - asos yo'q (%s)", m["id"], minutes_id, reason)
                return
            if base["id"] != row["parent_id"]:
                store.update_minutes(minutes_id, parent_id=base["id"], revision=int(base.get("revision") or 0) + 1)
                row = store.minutes_row(m["id"], minutes_id) or row
            _fill(rt, fresh, lang, rev, providers, row, base=base)
    except MeetingProblem as exc:
        # Model / tekshiruv xatosi: `_fill` sababni qatorga yozgan (pastdagi - ehtiyot to'ri); odam ilovada ko'radi.
        log.info("Yig'ilish %s: bayonnoma %s yozilmadi: %s", m["id"], minutes_id, exc.code)
        code, reason = exc.code, str(exc.detail)
    except Exception as exc:                                     # noqa: BLE001
        log.exception("Yig'ilish %s: bayonnoma ishida kutilmagan xato", m["id"])
        code, reason = "internal", type(exc).__name__
    else:
        return
    try:
        _fail_running(store, minutes_id, code, reason)
    except Exception:                                            # noqa: BLE001
        # Havza `Future` idagi xatoni hech kim o'qimaydi - shu yerda jurnalga; qator eskirgach `interrupted`.
        log.exception("Yig'ilish %s: bayonnoma qatori yangilanmadi", m["id"])


def _restamp(store: Any, row: Mapping[str, Any], fresh: Mapping[str, Any]) -> int:
    """Navbatda turgan paytda transkript qatori tahrirlangan (`transcript_rev` oshgan) - hujjat HOZIRGI qatorlardan
    yoziladi, shuning uchun qator ham hozirgi versiya bilan belgilanadi (aks holda tayyor bo'lishi bilan "eskirgan"
    ko'rinib, til tugmasi uni topmay qayta pullik yozardi va tahrir tushib qolardi). Asl hujjat qayta o'girilgan
    matndan yozilsa - avlodi ham yangilanadi; tahrir esa avlod almashganda baribir to'xtaydi (asos yo'q). -> versiya."""
    rev = int(fresh.get("transcript_rev") or 0)
    gen = int(fresh.get("transcript_gen") or 0)
    fields: dict[str, Any] = {}
    if int(row.get("transcript_rev") or 0) != rev:
        fields["transcript_rev"] = rev
    if not row.get("parent_id") and row.get("transcript_gen") != gen:
        fields["transcript_gen"] = gen
    if fields:
        store.update_minutes(row["id"], **fields)
        log.info("Yig'ilish %s: bayonnoma %s navbatda turganda matn o'zgargan - hozirgi versiya bilan belgilandi (%s)",
                 row["meeting_id"], row["id"], ", ".join(f"{k}={v}" for k, v in fields.items()))
    return rev


def _copy_ready(store: Any, meeting_id: str, lang: str, rev: int, row: Mapping[str, Any]) -> bool:
    """Navbatda turgan asl hujjat ishi: shu versiyada tayyor hujjat (HEAD) paydo bo'lgan va unda shu qatorga berilgan
    HAMMA ko'rsatmalar bor - model chaqirilmaydi, tayyor mazmun va uning kelib chiqishi (ota-versiya, so'rov,
    o'zgarishlar, ko'rsatmalar, avlod) shu qatorga ko'chiriladi (ilova aynan shu id ni so'rab turibdi). `turn_id`
    KO'CHIRILMAYDI: u qaysi chat navbati shu qatorni boshlaganini bildiradi."""
    found = _ready_row(store, meeting_id, lang, rev)
    if found is None or found["id"] == row["id"] or not rows.applied_ids(row) <= rows.applied_ids(found):
        return False
    store.update_minutes(row["id"], status="ready", provider=found.get("provider"), model=found.get("model"),
                         content_json=found["content_json"], finished_at=found.get("finished_at") or int(time.time()),
                         error_code=None, error=None, parent_id=found.get("parent_id"),
                         revision=int(found.get("revision") or 0), request_json=found.get("request_json"),
                         changes_json=found.get("changes_json"), guidance_json=found.get("guidance_json"),
                         transcript_gen=found.get("transcript_gen"), prompt_version=found.get("prompt_version"))
    log.info("Yig'ilish %s: bayonnoma %s - tayyor hujjat %s ko'chirildi, model chaqirilmadi", meeting_id, row["id"],
             found["id"])
    return True


def _fit(notes: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], int]:
    """Promptga sig'adigan ko'rsatmalar -> (eskisi birinchi tartibda, tushib qolganlar soni): eng YANGILARI, tozalangan
    (`prompts.clean_block`) uzunliklari yig'indisi `MEETINGS_MINUTES_GUIDANCE_CHARS` gacha; eng eskilari tushadi."""
    budget = max(0, int(settings.meetings_minutes_guidance_chars or 0))
    kept: list[Mapping[str, Any]] = []
    used = 0
    for note in reversed(notes):
        size = len(prompts.clean_block(str(note.get("text") or ""), prompt.OWNER_TEXT_CHARS))
        if used + size > budget:
            break
        kept.append(note)
        used += size
    kept.reverse()
    return kept, len(notes) - len(kept)


def _union(*groups: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ko'rsatmalar suratlarining birlashmasi - id bo'yicha takrorsiz, birinchi uchragan tartibida."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for note in group:
            key = str(note.get("id"))
            if key not in seen:
                seen.add(key)
                out.append({"id": key, "text": str(note.get("text") or "")})
    return out


def _superseded(store: Any, m: Mapping[str, Any], lang: str, rev: int) -> list[str]:
    """Matn (qator) tahriridan keyin hujjat yangidan yozilmoqda, oldingi joriy hujjat esa tahrirlangan versiya edi -
    o'sha o'zgartirishlar yangi hujjatga kirmaydi: `superseded_revisions:<nechta tahrir>` ogohlantirishi."""
    prior, _ = base_row(store, m, lang)
    if prior is not None and int(prior.get("transcript_rev") or 0) < int(rev) and int(prior.get("revision") or 0) > 0:
        return [f"superseded_revisions:{int(prior['revision'])}"]
    return []


def _recent(store: Any, meeting_id: str, row: Mapping[str, Any]) -> list[dict[str, str]]:
    """So'rovchining oxirgi `RECENT_TURNS` ta faol suhbat navbati (eskisi birinchi) - shu so'rovning o'z navbatisiz
    (u CHANGE REQUEST blokida)."""
    turns = store.chat_turns(meeting_id, limit=RECENT_TURNS + 1, asker=row.get("asker"))
    picked = [t for t in turns if t["id"] != row.get("turn_id")][-RECENT_TURNS:]
    return [{"question": str(t.get("question") or ""), "answer": str(t.get("answer") or "")} for t in picked]


def _chain_requests(store: Any, meeting_id: str, base: Mapping[str, Any]) -> list[str]:
    """Asosgacha qo'llangan o'zgartirish so'rovlari: asosdan ota-versiyalar bo'ylab yuqoriga (asl hujjatgacha), ESKISI
    birinchi; eng yangi `EARLIER_REQUESTS` tasi, jami `EARLIER_CHARS` belgigacha."""
    by_id = {r["id"]: r for r in store.minutes_rows(meeting_id)}
    newest_first: list[str] = []
    seen: set[str] = set()
    row: Mapping[str, Any] | None = base
    while row is not None and row["id"] not in seen:
        seen.add(row["id"])
        request = jload(row.get("request_json"))
        words = str(request.get("text") or "").strip() if isinstance(request, dict) else ""
        if words:
            newest_first.append(words)
        row = by_id.get(row.get("parent_id") or "")
    kept: list[str] = []
    total = 0
    for words in newest_first:
        if len(kept) >= EARLIER_REQUESTS or total + len(words) > EARLIER_CHARS:
            break
        kept.append(words)
        total += len(words)
    return kept[::-1]


def _revision_prompt(store: Any, m: dict[str, Any], lang: str, rev: int, row: Mapping[str, Any],
                     base: Mapping[str, Any], current: dict[str, Any], kept: Sequence[Mapping[str, Any]],
                     notes: Sequence[Mapping[str, Any]], request: Mapping[str, Any],
                     segments: list[dict[str, Any]], speakers: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    """Tahrir prompti -> (system, user, ega matnlari). Ega matnlari (`validate(owner=...)`: ulardagi ism va raqamlar
    asosli, sarlavha qismi faqat shulardan): ko'rsatmalar, oxirgi suhbatdagi SAVOLLAR (javoblar - model matni,
    kirmaydi), so'rov, asosdagi ism va lavozimlar (`owner_terms`), asosga berilgan ko'rsatmalar va oldingi so'rovlar -
    "Yangi suhbat" dan keyin ham ega aytgan ism keyingi tahrirda tushib qolmaydi."""
    applied = rows.applied_ids(base)
    flagged = [{"text": str(n.get("text") or ""), "new": str(n.get("id")) not in applied} for n in kept]
    recent = _recent(store, m["id"], row)
    earlier = _chain_requests(store, m["id"], base)
    owner = [str(n.get("text") or "") for n in notes] + [t["question"] for t in recent] \
        + [str(request.get("text") or "")] + validate.owner_terms(current) \
        + [str(n.get("text") or "") for n in rows.snapshot(base)] + earlier
    system, user_text = prompt.build_revision(
        m, segments=segments, speakers=speakers, lang=lang, current=current,
        outline=compose.outline(current, lang=lang, speakers=_speakers(m["id"])), notes=flagged, earlier=earlier,
        recent=recent, request=request or None, stale=int(base.get("transcript_rev") or 0) < int(rev))
    return system, user_text, [said for said in owner if said.strip()]


def _fill(rt: Any, m: dict[str, Any], lang: str, rev: int, providers: list[Any], row: Mapping[str, Any], *,
          base: Mapping[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
    """`running` qatorga model natijasi (`ready`) yoki sabab (`failed` + `MeetingProblem`).

    `base` yo'q - transkriptdan yangi hujjat (ko'rsatmalar OWNER INSTRUCTIONS bloki bilan); bor - o'sha hujjatning
    tahriri (`prompt.build_revision`): so'rov hujjatni o'zgartirmasa - `no_change` (yangi versiya yo'q); yangi
    ko'rsatmalarni qo'llash o'zgarishsiz bo'lsa ham tayyor (ko'rsatmalar "qo'llangan" bo'ladi - qayta bosish yana
    pul sarflamasin)."""
    store = rt.store
    minutes_id = row["id"]
    revising = base is not None
    notes = _snapshot(row)
    request = jload(row.get("request_json"))
    request = request if isinstance(request, dict) else {}
    current: dict[str, Any] = {}
    extra: list[str] = []

    def attempt(provider: Any, strict: bool) -> dict[str, Any]:
        content = _ask(provider, system, user_text, op=op, effort=effort)
        try:
            cleaned, warnings = validate.validate(content, lang=lang, segments=segments, speakers=speakers,
                                                  owner=owner)
        except validate.Invalid as exc:
            # Shakl yaroqsiz - shu model yiqildi: zanjirda keyingisi bo'lsa u yozadi (`run_chain`).
            raise LlmFailed(f"bayonnoma: {exc}") from exc
        cleaned["quality"] = {"warnings": warnings, "strict": strict}
        return cleaned

    try:
        segments = store.segments(m["id"])
        speakers = [sp for sp in store.speakers(m["id"]) if not sp.get("merged_into")]
        kept, dropped = _fit(notes)
        if dropped:
            extra.append(f"guidance_truncated:{dropped}")
        if revising:
            current = jload(base.get("content_json"), {}) or {}
            system, user_text, owner = _revision_prompt(store, m, lang, rev, row, base, current, kept, notes, request,
                                                        segments, speakers)
            op = "meeting_minutes_revise"
            effort = settings.meetings_minutes_revise_effort or settings.meetings_minutes_effort
        else:
            system, user_text = prompt.build(m, segments=segments, speakers=speakers,
                                             action_items=store.action_items(m["id"]), lang=lang,
                                             guidance=[str(n.get("text") or "") for n in kept])
            owner = [str(n.get("text") or "") for n in notes]
            op, effort = "meeting_minutes", settings.meetings_minutes_effort
            if not force:
                extra += _superseded(store, m, lang, rev)
        content, used, failed = llm.run_chain(providers, attempt, what="bayonnoma")
    except LlmUnavailable as exc:
        _failed(store, minutes_id, "llm_not_configured", str(exc))
        raise _problem("llm_not_configured") from None
    except LlmBusy:
        _failed(store, minutes_id, "llm_busy", "navbat to'la")
        raise _problem("llm_busy") from None
    except LlmRateLimited:
        _failed(store, minutes_id, "llm_rate_limited", "429")
        raise _problem("llm_rate_limited") from None
    except LlmFailed as exc:
        _failed(store, minutes_id, "llm_failed", str(exc)[:300])
        log.info("Yig'ilish %s: bayonnoma yozilmadi (%s: %s)", m["id"], type(exc).__name__, str(exc)[:160])
        raise _problem("llm_failed", REVISE_FAILED if revising else None) from None
    except Exception as exc:                                     # noqa: BLE001
        # Kutilmagan xato (ombor, prompt yig'ish) - qator `running` da abadiy qolmasin.
        _failed(store, minutes_id, "internal", type(exc).__name__)
        log.exception("Yig'ilish %s: bayonnomada kutilmagan xato", m["id"])
        raise _problem("internal") from None
    changes = diff.changes(current, content) if revising else None
    if revising and diff.empty(changes) and str(request.get("text") or "").strip():
        # So'rov hujjatga ta'sir qilmadi (tushunarsiz yoki allaqachon shunday) - yangi versiya ham, yangi fayl ham yo'q.
        _failed(store, minutes_id, "no_change", FAILURES["no_change"][1])
        log.info("Yig'ilish %s: bayonnoma tahriri %s - o'zgarish yo'q (no_change)", m["id"], minutes_id)
        raise _problem("no_change")
    content["version"] = prompt.MINUTES_VERSION
    content["language"] = lang
    content["meeting"] = {"recordedAt": service.iso(m.get("recorded_at")),
                          "durationSec": float(m.get("duration_sec") or 0), "speakerCount": len(speakers)}
    content["quality"]["warnings"] = [f"provider_failed:{name}" for name in failed] + \
        list(content["quality"].get("warnings") or []) + extra
    applied = _union(_snapshot(base), notes) if revising else _union(notes)
    store.update_minutes(minutes_id, status="ready", provider=used.name, model=str(used.model)[:120],
                         content_json=jdump(content), finished_at=int(time.time()), error_code=None, error=None,
                         changes_json=jdump(changes) if revising else None,
                         guidance_json=jdump({"notes": applied, "dropped": dropped}))
    log.info("Yig'ilish %s: bayonnoma %s (%s, %s, %d band)", m["id"], "tahrirlandi" if revising else "tayyor", lang,
             used.name, sum(len(s.get("items") or []) for s in content.get("sections") or []))
    return store.minutes_row(m["id"], minutes_id)


def _ask(provider: Any, system: str, user_text: str, *, op: str = "meeting_minutes",
         effort: str | None = None) -> dict[str, Any]:
    """Bitta provayder bilan hujjat JSON i. Kesilgan yoki yaroqsiz javob - `LlmFailed` (zanjir
    keyingisiga, bo'lsa). `op` - "meeting_minutes" yoki tahrir "meeting_minutes_revise" (sxema bir xil);
    `options.effort` - Claude `output_config.effort`; Ollama uni e'tiborsiz qoldiradi (`num_ctx` kabi noma'lum
    sozlama)."""
    try:
        raw, meta = provider.client.complete_meta(
            system, user_text, num_predict=settings.meetings_minutes_max_output_tokens, temperature=0.2,
            op=op, format="json", options={"effort": effort or settings.meetings_minutes_effort})
    except OllamaError as exc:
        # Ollama klienti o'z xatosini otadi (`summarize.call_llm` dagi xaritalash): 429 - kutish,
        # sozlanmagan - yo'q, navbat to'la - band, qolgani - yiqildi (zanjir keyingisiga).
        status_code = getattr(exc, "status", None)
        if status_code == 429:
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


# --- eksport ----------------------------------------------------------------------------------------------


def export_file(user: AuthUser, meeting_id: str, minutes_id: str, fmt: str, *,
                now: float | None = None) -> tuple[bytes, str, str]:
    """Tayyor hujjat -> (baytlar, Content-Type, Content-Disposition). `fmt`: docx | pdf | md. Tahrirlangan versiyada
    (`revision` >= 1) loyiha qatorida ham, fayl nomida ham versiya belgisi ("2-таҳрир")."""
    now = time.time() if now is None else now
    if fmt not in FORMATS:
        raise MeetingProblem(400, "invalid_format", "Format: docx, pdf yoki md")
    m = service._owned(user.actorId, meeting_id)
    row = _row_or_404(m, minutes_id)
    if row["status"] != "ready" or not row.get("content_json"):
        raise MeetingProblem(409, "not_ready", "Bayonnoma hali tayyor emas")
    content = jload(row["content_json"], {}) or {}
    lang = row["language"]
    revision = int(row.get("revision") or 0)
    recorded_at = float(m.get("recorded_at") or m.get("created_at") or 0)
    doc = compose.compose(content, lang=lang, title=m.get("title") or content.get("title") or "",
                          speakers=_speakers(m["id"]), recorded_at=recorded_at, now=now, revision=revision)
    with service._export_slot(user.actorId):
        try:
            data = render.render(doc, fmt, font_dir=settings.meetings_export_font_dir)
        except export.RenderUnavailable as exc:
            log.warning("Yig'ilish %s: bayonnoma %s chizilmadi (%s)", m["id"], fmt, exc.code)
            headers = {"Retry-After": "10"} if exc.code == "export_busy" else None
            raise MeetingProblem(503, exc.code, service._RENDER_MESSAGES.get(exc.code), headers=headers) from None
    media, ext = FORMATS[fmt]
    title = compose.file_title(m.get("title") or content.get("title") or "", lang=lang, revision=revision)
    ascii_name, real_name = export.file_names(title, recorded_at, ext)
    log.info("Yig'ilish %s: bayonnoma eksporti %s, %d bayt", m["id"], fmt, len(data))
    return data, media, export.content_disposition(ascii_name, real_name)

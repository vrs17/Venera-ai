"""Bitta savol-javobning to'liq izi: savol -> Venera bosqichlari -> yuqoridagi
xizmat kadrlari -> javob, vaqtlari bilan.

NEGA KERAK. "Nega bunday javob keldi" degan savolga javob berish uchun
qaysi hujjatlar topilgani (`sources`), qaysi HRM/CRM chaqiruvi bo'lgani,
birinchi so'z qachon kelgani va yo'nalish (`route`) qanday tanlangani
ko'rinishi kerak. Oqim tugagach bularning hech biri qolmaydi - shuning
uchun oqim O'TAYOTGANDA yig'iladi.

OQIMNI SEKINLATMASLIK. Kadr brauzerga BUFERSIZ ketadi; bu yerda faqat
kuzatiladi. `token` kadri eng ko'p (yuzlab) - uning yo'li eng arzon: bitta
lug'at qidiruvi va ro'yxatga qo'shish. Hodisalar va manbalar XOTIRADA
yig'iladi va `finish` da BITTA to'plam bilan yozuvchiga beriladi.

QULAB TUSHISHGA CHIDAMLI. `turns` qatori savol BOSHIDA (`running` holatida)
yoziladi: jarayon o'rtada o'lsa ham "shu savol boshlangan, tugamagan" degan
iz qoladi. `finish` esa UPSERT bilan yozadi - boshlang'ich yozuv navbat
to'lgani uchun tashlangan bo'lsa ham qator yo'qolmaydi.

HECH QACHON XATO BERMAYDI: yozib olishdagi har qanday nosozlik jurnalga
tushadi (daqiqasiga bir marta), javob esa odatdagidek ketaveradi.

Hajm chegaralari: savol 4 KB, javob 64 KB, hodisa 64 KB, parcha 2 KB, asl
manba 8 KB (belgilarda). Tokenlar, parollar, `initData`, ilova siri bu
yerga tushmaydi: kadrlarda ular yo'q, xato matnlari esa `redact` dan o'tadi.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import time
import uuid

from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping

from ...core.channels import normalize as _normalize_channel
from . import db as _db
from .db import log_limited
from .meter import Binding, bind, http_status_of, redact
from .writer import Writer, get_writer

if TYPE_CHECKING:                                           # pragma: no cover
    from ...schemas.auth import AuthUser

# --- chegaralar -------------------------------------------------------------------

QUESTION_CAP = 4 * 1024
ANSWER_CAP = 64 * 1024
PAYLOAD_CAP = 64 * 1024
SNIPPET_CAP = 2 * 1024
RAW_CAP = 8 * 1024
ERROR_TEXT_CAP = 1000
#: Bitta savol uchun hodisalar soni. `token` hodisa emas, ya'ni oddiy javobda
#: o'ntacha bo'ladi; minglab bo'lsa - nosozlik, va xotirani yeb qo'ymasin.
MAX_EVENTS = 1000
MAX_SOURCES = 200

KINDS = ("chat", "ask", "bot")
STATUSES = ("running", "ok", "error", "cancelled")
PROPOSAL_STATUSES = ("pending", "executed", "cancelled", "failed", "expired")
#: Platforma chaqiruvlari - hujjat emas (`bot/render.py` va
#: `AnswerSources.vue` dagi `LOOKUP_KINDS` bilan bir xil).
TOOL_KINDS = frozenset({"hrm", "crm"})

_TURN_ID = re.compile(r"[0-9a-f]{32}")
_DIGITS = re.compile(r"\d+")

#: Taklif holati shu muddat ichidagi savollardan izlanadi: `proposal_token`
#: indekssiz, `started_at` esa indeksli - butun jadvalni o'qimaslik uchun.
#: Takliflar daqiqalarda eskiradi, bir hafta - katta zahira.
_PROPOSAL_WINDOW = 7 * 86400.0

_TURN_COLUMNS = (
    "id", "started_at", "ended_at", "actor_id", "user_name", "user_login", "channel",
    "kind", "input_mode", "locale", "chat_id", "request_id", "question", "answer", "route",
    "status", "error_code", "error_text", "http_status", "ttft_ms", "total_ms", "frames",
    "sources_count", "tool_calls", "has_artifact", "has_proposal", "proposal_token",
    "proposal_status", "answer_chars",
)
#: `finish` da o'zgarmaydigan ustunlar (qolganlari `excluded` dan olinadi).
_FIXED = {"id", "started_at", "actor_id", "user_name", "user_login", "channel", "kind",
          "question", "proposal_status"}

_INSERT_START = (
    "INSERT OR IGNORE INTO turns (id, started_at, actor_id, user_name, user_login, channel, "
    "kind, input_mode, locale, chat_id, request_id, question, status) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'running')"
)
_UPSERT_FINISH = (
    f"INSERT INTO turns ({', '.join(_TURN_COLUMNS)}) "
    f"VALUES ({','.join('?' * len(_TURN_COLUMNS))}) "
    "ON CONFLICT(id) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _TURN_COLUMNS if c not in _FIXED)
    # Taklif holati `finish` dan OLDIN tasdiqlangan bo'lsa (`set_proposal_status`)
    # - o'sha holat qoladi, "pending" ustiga yozilmaydi.
    + ", proposal_status=COALESCE(turns.proposal_status, excluded.proposal_status)"
)
_INSERT_EVENT = (
    "INSERT OR IGNORE INTO turn_events (turn_id, seq, t_ms, dur_ms, type, name, payload) "
    "VALUES (?,?,?,?,?,?,?)"
)
_INSERT_SOURCE = (
    "INSERT OR IGNORE INTO turn_sources (turn_id, idx, kind, ref, title, page, score, snippet, "
    "status, digest, citation, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
)
_UPDATE_PROPOSAL = (
    "UPDATE turns SET proposal_status=? WHERE proposal_token=? AND started_at >= ?"
)


# --- yordamchilar -----------------------------------------------------------------


def new_turn_id() -> str:
    """Yangi savol kaliti: uuid4, 32 ta hex belgi."""
    return uuid.uuid4().hex


def valid_turn_id(value: Any) -> str | None:
    """Klientdan kelgan kalit (`X-Venera-Turn`) yaroqlimi: aynan 32 hex.
    Yaroqsiz bo'lsa `None` - boshqa hech narsa omborga tushmaydi."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if _TURN_ID.fullmatch(value) else None


def _cap(text: Any, limit: int) -> str:
    value = text if isinstance(text, str) else ("" if text is None else str(text))
    return value if len(value) <= limit else value[:limit]


def _str(value: Any, limit: int = 512) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple)):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value:        # NaN emas
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number else None
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            number = float(value.strip())
            return number if number == number else None
    return None


def _first(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _citation(value: Any) -> int | None:
    """`citation_index: 2` -> 2; `marker: "[T1]"` -> 1."""
    number = _int(value)
    if number is not None:
        return number
    if isinstance(value, str):
        found = _DIGITS.search(value)
        if found:
            return int(found.group())
    return None


def _capped_json(obj: Any, cap: int) -> str:
    """JSON matn, `cap` belgidan oshmaydi. Oshsa - avval uzun satrlar
    qisqartiriladi, bo'lmasa faqat boshlanishi saqlanadi (`_truncated`)."""
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        text = json.dumps({"_unserializable": type(obj).__name__})
    if len(text) <= cap:
        return text
    if isinstance(obj, Mapping):
        slim = {str(k): (v[:1000] + "…" if isinstance(v, str) and len(v) > 1000 else v)
                for k, v in obj.items()}
        slim["_truncated"] = True
        with contextlib.suppress(TypeError, ValueError):
            again = json.dumps(slim, ensure_ascii=False, default=str, separators=(",", ":"))
            if len(again) <= cap:
                return again
    preview = text[:cap // 2]
    while True:
        out = json.dumps({"_truncated": True, "chars": len(text), "preview": preview},
                         ensure_ascii=False)
        if len(out) <= cap or not preview:
            return out
        preview = preview[:len(preview) // 2]


def _error_text(error: Any) -> str | None:
    if error is None:
        return None
    if isinstance(error, GeneratorExit):
        return "cancelled"
    if isinstance(error, BaseException):
        text = str(error)
        error = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return redact(error, ERROR_TEXT_CAP) or None


def _source_items(frame: Mapping[str, Any]) -> list[Any]:
    """`sources` kadridagi ro'yxat: jonli xizmat `items` ostida, hujjat
    `sources` ostida yuboradi - ikkalasi ham o'qiladi (`types.ts` izohi)."""
    for key in ("items", "sources"):
        value = frame.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            inner = value.get("items") or value.get("sources")
            return inner if isinstance(inner, list) else [value]
    return []


def _source_row(turn_id: str, idx: int, item: Any) -> tuple[tuple, bool]:
    """Bitta manba -> `turn_sources` qatori va "bu platforma chaqiruvimi".

    Notanish shakllarga chidamli: maydon nomlari yuqoridagi xizmatniki
    (`doc_id`, `citation_index`, `tool`, `digest`), `/chat/ask` quvuriniki
    (`documentId`, `source.documentTitle`, `rerankScore`) ham tanilaydi.
    """
    if not isinstance(item, Mapping):
        item = {"value": item}
    nested = item.get("source") if isinstance(item.get("source"), Mapping) else {}
    tool = _str(item.get("tool"), 128)
    doc_id = _str(_first(item, "doc_id", "documentId", "document_id")
                  or nested.get("documentId"), 128)
    kind = _str(item.get("kind"), 32)
    if kind is None:
        if tool:
            prefix = tool.split("_", 1)[0].lower()
            kind = prefix if prefix in TOOL_KINDS else "tool"
        elif doc_id:
            kind = "doc"
    ref = doc_id or tool or _str(_first(item, "ref", "id", "chunkId", "name", "url"), 256)
    title = _str(_first(item, "title", "documentTitle", "doc_title")
                 or nested.get("documentTitle"), 512)
    page = _int(_first(item, "page") if item.get("page") is not None else nested.get("page"))
    score = _float(_first(item, "score", "relevance", "rerankScore", "rerank_score",
                          "vectorScore", "vector_score"))
    snippet = _str(_first(item, "snippet", "text", "excerpt", "content", "chunk"),
                   SNIPPET_CAP)
    status = _str(item.get("status"), 32)
    digest = _str(item.get("digest"), 1000)
    citation = _citation(_first(item, "citation_index", "citation", "marker"))
    raw = _capped_json(dict(item), RAW_CAP)
    is_tool = bool(tool) or (kind or "") in TOOL_KINDS
    return (turn_id, idx, kind, ref, title, page, score, snippet, status, digest,
            citation, raw), is_tool


def _attr(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _close(iterator: Any) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


# --- yozib oluvchi ------------------------------------------------------------------


class TurnRecorder:
    """Bitta savol-javob. Savol boshida yaratiladi:

        rec = TurnRecorder(user, channel_of(request), "chat", body.question,
                           chat_id=body.chatId, locale=body.locale,
                           input_mode="voice" if body.voice else "text")

    Oqim uchun eng sodda yo'l - `rec.wrap(frames)`: har kadrni kuzatadi,
    meter atributsiyasini har qadamda qo'yadi va oxirida `finish` ni o'zi
    chaqiradi (klient uzilsa - `cancelled`). Qo'lda: `observe_raw(raw)` /
    `observe(frame)` va oxirida `finish(...)`.

    `with TurnRecorder(...) as rec:` ham ishlaydi - blok davomida
    atributsiya qo'yilgan, oxirida `finish` (xato bo'lsa `error`).
    """

    def __init__(
        self,
        actor: "AuthUser | Mapping[str, Any] | None" = None,
        channel: str | None = "api",
        kind: str = "chat",
        question: str = "",
        chat_id: str | None = None,
        locale: str | None = None,
        input_mode: str | bool = "text",
        *,
        request_id: str | None = None,
        user_login: str | None = None,
        turn_id: str | None = None,
        writer: Writer | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._finished = False
        self._lock = threading.Lock()
        self.turn_id: str = valid_turn_id(turn_id) or new_turn_id()
        self.enabled = _db.analytics_enabled() if enabled is None else bool(enabled)
        self.started_at = time.time()
        self._t0 = time.monotonic()
        self._writer = writer

        self.actor_id: int | None = _int(_attr(actor, "actorId"))
        self.user_name = _str(_attr(actor, "fullName"), 256)
        login = user_login or _attr(actor, "email")
        self.user_login = (_str(login, 128) or "").lower() or None
        self.channel: str = _normalize_channel(channel) or "api"
        self.kind = kind if kind in KINDS else (_str(kind, 16) or "chat")
        self.input_mode = "voice" if input_mode is True or input_mode == "voice" else "text"
        self.locale = _str(locale, 16)
        self.chat_id = _str(chat_id, 64)
        self.request_id = _str(request_id, 128)
        self.question = _cap(question, QUESTION_CAP)

        self.status = "running"
        self.route: str | None = None
        self.error_code: str | None = None
        self.error_text: str | None = None
        self.http_status: int | None = None
        self.ttft_ms: int | None = None
        self.total_ms: int | None = None
        self.ended_at: float | None = None
        self.frames = 0
        self.sources_count = 0
        self.tool_calls = 0
        self.has_artifact = False
        self.has_proposal = False
        self.proposal_token: str | None = None
        self.answer_chars = 0

        self._parts: list[str] = []
        self._stored = 0
        self._answer_override: str | None = None
        self._first_frame = False
        self._events: list[tuple] = []
        self._events_dropped = 0
        self._seq = 0
        self._sources: list[tuple] = []
        self._bad_lines = 0

        if self.enabled:
            try:
                self._submit(_INSERT_START, (
                    self.turn_id, self.started_at, self.actor_id, self.user_name,
                    self.user_login, self.channel, self.kind, self.input_mode, self.locale,
                    self.chat_id, self.request_id, self.question,
                ))
            except Exception:                               # noqa: BLE001
                log_limited("recorder.start", "Savol yozuvi boshlanmadi", exc_info=True)

    # --- umumiy ---

    def _submit(self, sql: str, params: Any) -> bool:
        return (self._writer or get_writer()).submit(sql, params)

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def answer(self) -> str:
        """Yig'ilgan javob matni (64 KB gacha)."""
        if self._answer_override is not None:
            return self._answer_override
        return "".join(self._parts)

    def bind(self) -> Binding:
        """Meter atributsiyasi: shu savolning actor, kanal va kaliti.

            with rec.bind():
                answer = _assistant.stream(...)   # api_calls.turn_id = rec.turn_id
        """
        return bind(self.actor_id, self.channel, self.turn_id)

    def update(self, **fields: Any) -> None:
        """Keyin ma'lum bo'lgan maydonlar: `request_id`, `chat_id`, `locale`,
        `route`, `answer` (oqimsiz yo'l, masalan `/chat/ask`), `input_mode`."""
        try:
            for name, value in fields.items():
                if name == "request_id":
                    self.request_id = _str(value, 128)
                elif name == "chat_id":
                    self.chat_id = _str(value, 64)
                elif name == "locale":
                    self.locale = _str(value, 16)
                elif name == "route":
                    self.route = _str(value, 64)
                elif name == "input_mode":
                    self.input_mode = "voice" if value is True or value == "voice" else "text"
                elif name == "answer":
                    text = "" if value is None else str(value)
                    self._answer_override = _cap(text, ANSWER_CAP)
                    self.answer_chars = len(text)
                else:
                    log_limited(f"recorder.update.{name}", "TurnRecorder.update: noma'lum maydon %s",
                                name)
        except Exception:                                   # noqa: BLE001
            log_limited("recorder.update", "Savol maydoni yangilanmadi", exc_info=True)

    # --- vaqt chizig'i ---

    def _event(self, etype: str, name: str, payload: Any, *, t_ms: int | None = None,
               dur_ms: int | None = None) -> None:
        if self._finished or not self.enabled:
            return
        data = _capped_json(payload, PAYLOAD_CAP) if payload else None
        with self._lock:
            if self._finished:
                return
            if len(self._events) >= MAX_EVENTS:
                self._events_dropped += 1
                return
            seq = self._seq
            self._seq += 1
            self._events.append((self.turn_id, seq, self._now_ms() if t_ms is None else t_ms,
                                 dur_ms, etype, str(name)[:64], data))

    def point(self, name: str, **payload: Any) -> None:
        """Venera tomonidagi lahza (`note`): masalan `hold.fire`."""
        try:
            self._event("note", name, payload)
        except Exception:                                   # noqa: BLE001
            log_limited("recorder.point", "Savol hodisasi yozilmadi", exc_info=True)

    def record_span(self, name: str, started: float, ended: float | None = None,
                    **payload: Any) -> None:
        """Boshqa joyda o'lchangan oraliq (`span`). `started` / `ended` -
        `time.monotonic()` qiymatlari; masalan alohida ipdagi tasnif:

            t = time.monotonic(); label = classify(q)
            rec.record_span("hold.classify", t, model=..., topic=...)
        """
        try:
            end = time.monotonic() if ended is None else ended
            t_ms = max(0, int((started - self._t0) * 1000))
            dur_ms = max(0, int((end - started) * 1000))
            self._event("span", name, payload, t_ms=t_ms, dur_ms=dur_ms)
        except Exception:                                   # noqa: BLE001
            log_limited("recorder.span", "Savol oralig'i yozilmadi", exc_info=True)

    @contextlib.contextmanager
    def span(self, name: str, **payload: Any) -> Iterator[dict[str, Any]]:
        """Oraliqni o'lchaydi. Qaytgan lug'atga natijani qo'shish mumkin:

            with rec.span("assistant.open") as info:
                answer = _assistant.stream(...)
                info["requestId"] = answer.request_id

        Xato bo'lsa `error` maydoni qo'shiladi va xato O'ZGARMASDAN qaytadi.
        """
        started = time.monotonic()
        extra: dict[str, Any] = dict(payload)
        try:
            yield extra
        except BaseException as exc:
            with contextlib.suppress(Exception):
                extra["error"] = _error_text(exc)
            raise
        finally:
            self.record_span(name, started, time.monotonic(), **extra)

    # --- kadrlar ---

    def observe_raw(self, raw: bytes | str) -> None:
        """Oqimdagi NDJSON qatori (odatda bitta kadr, `\\n` bilan)."""
        if not self.enabled or self._finished:
            return
        try:
            newline = b"\n" if isinstance(raw, (bytes, bytearray)) else "\n"
            lines = raw.splitlines() if raw.count(newline) > 1 else (raw,)
            for line in lines:
                if not line or line.isspace():
                    continue
                try:
                    frame = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    self._bad_lines += 1
                    continue
                if isinstance(frame, dict):
                    self.observe(frame)
        except Exception:                                   # noqa: BLE001
            log_limited("recorder.raw", "Kadr o'qilmadi", exc_info=True)

    def observe(self, frame: Mapping[str, Any]) -> None:
        """Bitta kadr (lug'at). `token` - faqat javobga qo'shiladi; qolganlari
        vaqt chizig'iga (`frame`) tushadi."""
        if not self.enabled or self._finished:
            return
        try:
            self.frames += 1
            kind = frame.get("type")
            if not self._first_frame and kind != "hold":
                # `hold` - bizning kutish kadrimiz, yuqoridagi xizmatniki emas.
                self._first_frame = True
                self._event("note", "first_frame", {"type": _str(kind, 32)})
            if kind == "token":
                if self.ttft_ms is None:
                    self.ttft_ms = self._now_ms()
                    self._event("note", "first_token", None, t_ms=self.ttft_ms)
                text = frame.get("text")
                if isinstance(text, str) and text:
                    self.answer_chars += len(text)
                    room = ANSWER_CAP - self._stored
                    if room > 0:
                        piece = text if len(text) <= room else text[:room]
                        self._parts.append(piece)
                        self._stored += len(piece)
                return
            handler = _HANDLERS.get(kind) if isinstance(kind, str) else None
            if handler is not None:
                handler(self, frame)
            else:
                self._event("frame", _str(kind, 64) or "unknown", _without_type(frame))
        except Exception:                                   # noqa: BLE001
            log_limited("recorder.observe", "Kadr kuzatilmadi", exc_info=True)

    def _on_stage(self, frame: Mapping[str, Any]) -> None:
        self._event("frame", "stage", _without_type(frame))

    def _on_sources(self, frame: Mapping[str, Any]) -> None:
        items = _source_items(frame)
        docs = tools = 0
        refs: list[str] = []
        for item in items:
            # Tartib raqami BUTUN savol bo'yicha: `sources` kadri ikki marta
            # kelsa ham `idx` takrorlanmaydi.
            idx = self.sources_count + self.tool_calls
            row, is_tool = _source_row(self.turn_id, idx, item)
            if is_tool:
                tools += 1
                self.tool_calls += 1
            else:
                docs += 1
                self.sources_count += 1
            if len(self._sources) < MAX_SOURCES:
                self._sources.append(row)
            if row[3] and len(refs) < 20:
                refs.append(row[3])
        self._event("frame", "sources", {"count": len(items), "docs": docs, "tools": tools,
                                         "refs": refs})

    def _on_artifact(self, frame: Mapping[str, Any]) -> None:
        self.has_artifact = True
        art = frame.get("artifact") if isinstance(frame.get("artifact"), Mapping) else frame
        # Havolalarning O'ZI yozilmaydi: ular bir martalik yuklab olish
        # kaliti. Qaysi fayllar berilgani yetarli.
        files = [key.removesuffix("_url") for key in ("docx_url", "pdf_url", "preview_url")
                 if art.get(key)]
        payload = {key: art.get(key) for key in ("title", "doc_id", "expires_at")
                   if art.get(key) is not None}
        payload["files"] = files
        self._event("frame", "artifact", payload)

    def _on_proposal(self, frame: Mapping[str, Any]) -> None:
        self.has_proposal = True
        prop = frame.get("proposal") if isinstance(frame.get("proposal"), Mapping) else frame
        token = _str(prop.get("token"), 256)
        if token:
            self.proposal_token = token
        # Kalit vaqt chizig'iga TUSHMAYDI - u faqat `turns.proposal_token` da,
        # holatni yangilash uchun.
        payload = {key: prop.get(key) for key in (
            "summary", "operation", "connector", "target", "changes", "warnings", "expires_at",
        ) if prop.get(key) is not None}
        self._event("frame", "proposal", payload)

    def _on_done(self, frame: Mapping[str, Any]) -> None:
        route = frame.get("route")
        self.route = _str(route, 64)
        served = _str(frame.get("request_id"), 128)
        if served and not self.request_id:
            self.request_id = served
        self._event("frame", "done", {"route": self.route, "request_id": served})

    def _on_error(self, frame: Mapping[str, Any]) -> None:
        self.error_code = _str(frame.get("code"), 64) or self.error_code or "error"
        text = frame.get("text") or frame.get("message")
        if text:
            self.error_text = redact(text, ERROR_TEXT_CAP)
        self._event("frame", "error", {"code": self.error_code, "text": self.error_text})

    def _on_hold(self, frame: Mapping[str, Any]) -> None:
        self._event("frame", "hold", {key: frame.get(key) for key in (
            "at", "clip", "topic", "source", "text") if frame.get(key) is not None})

    # --- oqim qobig'i ---

    def wrap(self, frames: Iterable[bytes]) -> Iterator[bytes]:
        """Kadrlarni O'ZGARTIRMASDAN va BUFERSIZ uzatadi, yo'l-yo'lakay kuzatadi.

        Meter atributsiyasi HAR `next()` atrofida qo'yiladi va olinadi:
        `StreamingResponse` har qadamni boshqa ishchi ipda, kontekstning
        yangi nusxasida bajaradi (`meter.py` izohi, 3-tuzoq).

        Yakun: oqim tugasa - `finish()` (xato kadri bo'lgan bo'lsa `error`);
        klient uzilsa (`GeneratorExit`) - `cancelled`, ichki oqim ham
        yopiladi (yuqoridagi xizmat sloti bo'shasin); xato - `error`.
        """
        iterator: Any = None
        try:
            iterator = iter(frames)
            while True:
                with self.bind():
                    try:
                        raw = next(iterator)
                    except StopIteration:
                        break
                self.observe_raw(raw)
                yield raw
        except GeneratorExit:
            self.finish("cancelled")
            with self.bind():
                _close(iterator)
            raise
        except BaseException as exc:
            self.finish("error", error=exc)
            raise
        self.finish()

    # --- yakun ---

    def finish(self, status: str | None = None, http_status: int | None = None,
               error: Any = None) -> bool:
        """Savolni yakunlaydi va yozuvchiga beradi. Faqat BIRINCHI chaqiruv
        ishlaydi (`True`), keyingilari hech narsa qilmaydi (`False`).

        `status` berilmasa: xato kadri kelgan yoki `error` berilgan bo'lsa
        `error`, aks holda `ok`. `error` - istisno yoki matn; `http_status`
        berilmasa istisnodan (`.status` / `.code`) olinadi.
        """
        with self._lock:
            if self._finished:
                return False
            self._finished = True
        try:
            if not self.enabled:
                return False
            self.ended_at = time.time()
            self.total_ms = self._now_ms()
            if error is not None:
                if not self.error_text:
                    self.error_text = _error_text(error)
                if not self.error_code:
                    # Mashina o'qiydigan kod: xatoning o'z `code` i (satr
                    # bo'lsa), bo'lmasa sinf nomi (`AssistantError`).
                    code = getattr(error, "code", None)
                    if isinstance(code, str) and code:
                        self.error_code = code[:64]
                    elif isinstance(error, BaseException):
                        self.error_code = type(error).__name__[:64]
                    else:
                        self.error_code = "error"
                if http_status is None and isinstance(error, BaseException):
                    http_status = http_status_of(error)
            if status is None:
                status = "error" if (self.error_code or error is not None) else "ok"
            elif status not in STATUSES or status == "running":
                status = "error"
            self.status = status
            if isinstance(http_status, int) and not isinstance(http_status, bool):
                self.http_status = http_status
            events = list(self._events)
            if self._events_dropped:
                events.append((self.turn_id, self._seq, self.total_ms, None, "note",
                               "events_dropped", json.dumps({"count": self._events_dropped})))
            if self._bad_lines:
                events.append((self.turn_id, self._seq + 1, self.total_ms, None, "note",
                               "bad_lines", json.dumps({"count": self._bad_lines})))
            self._submit(_UPSERT_FINISH, self._row())
            writer = self._writer or get_writer()
            writer.submit_many(_INSERT_EVENT, events)
            writer.submit_many(_INSERT_SOURCE, self._sources)
            return True
        except Exception:                                   # noqa: BLE001
            log_limited("recorder.finish", "Savol yakuni yozilmadi", exc_info=True)
            return False

    def _row(self) -> tuple:
        values = {
            "id": self.turn_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "actor_id": self.actor_id,
            "user_name": self.user_name,
            "user_login": self.user_login,
            "channel": self.channel,
            "kind": self.kind,
            "input_mode": self.input_mode,
            "locale": self.locale,
            "chat_id": self.chat_id,
            "request_id": self.request_id,
            "question": self.question,
            "answer": self.answer,
            "route": self.route,
            "status": self.status,
            "error_code": self.error_code,
            "error_text": self.error_text,
            "http_status": self.http_status,
            "ttft_ms": self.ttft_ms,
            "total_ms": self.total_ms,
            "frames": self.frames,
            "sources_count": self.sources_count,
            "tool_calls": self.tool_calls,
            "has_artifact": int(self.has_artifact),
            "has_proposal": int(self.has_proposal),
            "proposal_token": self.proposal_token,
            "proposal_status": "pending" if self.has_proposal else None,
            "answer_chars": self.answer_chars,
        }
        return tuple(values[c] for c in _TURN_COLUMNS)

    # --- `with` ---

    def __enter__(self) -> "TurnRecorder":
        self._binding = self.bind()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        binding = getattr(self, "_binding", None)
        if binding is not None:
            binding.reset()
        if exc is None:
            self.finish()
        elif isinstance(exc, GeneratorExit):
            self.finish("cancelled")
        else:
            self.finish("error", error=exc)

    def __del__(self) -> None:
        # Oqim BIRINCHI kadrdan oldin tashlab ketilsa generator hech ishga
        # tushmaydi va `wrap` yakunni yoza olmaydi. Qator "running" bo'lib
        # abadiy qolmasin.
        try:
            if not self._finished and self.enabled:
                self.finish("cancelled")
        except Exception:                                   # noqa: BLE001
            pass


def _without_type(frame: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in frame.items() if k != "type"}


_HANDLERS = {
    "stage": TurnRecorder._on_stage,
    "sources": TurnRecorder._on_sources,
    "artifact": TurnRecorder._on_artifact,
    "proposal": TurnRecorder._on_proposal,
    "done": TurnRecorder._on_done,
    "error": TurnRecorder._on_error,
    "hold": TurnRecorder._on_hold,
}


def set_proposal_status(token: str, status: str, *, writer: Writer | None = None) -> bool:
    """Taklif tasdiqlandi / bekor qilindi: `turns.proposal_status` ni kalit
    bo'yicha yangilaydi (`/actions/{token}/confirm|cancel`). Noma'lum holat
    yozilmaydi."""
    try:
        if not _db.analytics_enabled() or not token or status not in PROPOSAL_STATUSES:
            return False
        return (writer or get_writer()).submit(
            _UPDATE_PROPOSAL, (status, str(token)[:256], time.time() - _PROPOSAL_WINDOW))
    except Exception:                                       # noqa: BLE001
        log_limited("recorder.proposal", "Taklif holati yozilmadi", exc_info=True)
        return False

"""Tashqi chaqiruvlar hisobi: qaysi xizmat, qaysi amal, qancha vaqt, natija.

NEGA `contextvars`. Chaqiruv chuqurda bo'ladi (`AssistantClient._open`,
TTS klienti, Ollama tasnifchisi) va u yerda "kim so'radi, qaysi kanaldan,
qaysi savol uchun" degan ma'lumot yo'q. Uni har funksiyaga parametr qilib
o'tkazish o'nlab imzoni o'zgartirardi. Kontekst o'zgaruvchisi esa so'rov
boshida BIR MARTA qo'yiladi (`bind`) va chuqurdagi `metered(...)` uni o'zi
o'qiydi.

IPLAR BILAN EHTIYOT BO'LISH KERAK - bu yerda uchta tuzoq bor:

  1. `threading.Thread` kontekstni MEROS OLMAYDI (Python 3.10): yangi ip
     bo'sh kontekst bilan boshlanadi. Ip ichidagi chaqiruv ham hisobga
     tushishi uchun maqsad funksiya `carry(fn)` bilan o'raladi.
  2. FastAPI SINXRON bog'liqlikni (`def` dependency) threadpool'da,
     kontekstning NUSXASIDA bajaradi - u yerda qo'yilgan qiymat endpointga
     YETIB BORMAYDI. `bind` endpointning o'zida (yoki `async`
     bog'liqlikda) chaqiriladi.
  3. `StreamingResponse` sinxron generatorning HAR BIR `next()` ini boshqa
     ishchi ipda, so'rov kontekstining yangi nusxasida bajaradi. Generator
     ichida bir marta qo'yilgan qiymat keyingi qadamda YO'Q, va eski
     tokenni boshqa kontekstda `reset` qilish xato beradi. Shuning uchun
     oqim uchun `TurnRecorder.wrap` qiymatlarni HAR QADAMDA qo'yib-oladi.

Uzoq oqimlar (`stream`) uchun `begin(...)` - atributsiya BOSHIDA olinadi va
chaqiruv boshqa ipda yoki generator oxirida `Call.end()` bilan yopiladi.

HECH NARSA CHAQIRUVCHIGA XATO BERMAYDI: hisob ikkinchi darajali, u
chaqiruvning o'zini buzmasligi kerak. `metered` ichidagi xato esa
O'ZGARMASDAN qaytadi - hisob faqat uni yozib qo'yadi.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import json
import re
import time

from contextvars import ContextVar
from typing import Any, Callable, Iterator, Mapping, NamedTuple, TypeVar

from ...core.channels import normalize as _normalize_channel
from ...core.config import settings
from . import db as _db
from .db import log_limited
from .writer import Writer, get_writer

#: Kim so'radi (`actorId`).
current_actor: ContextVar[int | None] = ContextVar("venera_actor", default=None)
#: Qaysi interfeysdan: web | miniapp | bot | desktop | api.
current_channel: ContextVar[str | None] = ContextVar("venera_channel", default=None)
#: Qaysi savol uchun (`turns.id`).
current_turn: ContextVar[str | None] = ContextVar("venera_turn", default=None)

#: "Bu maydonni o'zgartirma" belgisi - `None` esa "tozala" degani.
KEEP: Any = object()

_ERROR_LIMIT = 300
_NAME_LIMIT = 64

_INSERT_CALL = (
    "INSERT INTO api_calls (ts, service, op, status, http_status, duration_ms, "
    "actor_id, channel, turn_id, units, error) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
)
_INSERT_AUTH = (
    "INSERT INTO auth_events (ts, actor_id, login, ok, method, channel, reason) "
    "VALUES (?,?,?,?,?,?,?)"
)

F = TypeVar("F", bound=Callable[..., Any])


# --- atributsiya ---------------------------------------------------------------


class Attribution(NamedTuple):
    actor_id: int | None
    channel: str | None
    turn_id: str | None


def current() -> Attribution:
    """Joriy kontekstdagi (actor, kanal, savol)."""
    return Attribution(current_actor.get(), current_channel.get(), current_turn.get())


def _actor(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Binding:
    """`bind(...)` natijasi. Qiymatlar YARATILGANDA qo'yiladi, `reset()` yoki
    `with` blokining oxirida qaytariladi.

    Yaratilganda qo'yilishi ataylab: `yield` li bog'liqlikda yoki
    `try/finally` da `with` siz ham ishlatish mumkin.
    """

    __slots__ = ("_tokens",)

    def __init__(self, actor_id: Any = KEEP, channel: Any = KEEP, turn_id: Any = KEEP) -> None:
        self._tokens: list[tuple[ContextVar, contextvars.Token]] = []
        try:
            if actor_id is not KEEP:
                self._tokens.append((current_actor, current_actor.set(_actor(actor_id))))
            if channel is not KEEP:
                value = _normalize_channel(channel, default=None) if channel is not None else None
                self._tokens.append((current_channel, current_channel.set(value)))
            if turn_id is not KEEP:
                self._tokens.append((current_turn, current_turn.set(
                    str(turn_id) if turn_id is not None else None)))
        except Exception:                                   # noqa: BLE001
            log_limited("meter.bind", "Hisob konteksti qo'yilmadi", exc_info=True)

    def reset(self) -> None:
        """Oldingi qiymatlarni qaytaradi. Takroriy chaqiruv zararsiz.

        Token BOSHQA kontekstda yaratilgan bo'lsa (`ValueError`) - jim
        o'tkazib yuboriladi: u kontekst baribir tashlab yuborilgan nusxa.
        """
        tokens, self._tokens = self._tokens, []
        for var, token in reversed(tokens):
            with contextlib.suppress(ValueError, RuntimeError):
                var.reset(token)

    def __enter__(self) -> "Binding":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.reset()


def bind(actor_id: Any = KEEP, channel: Any = KEEP, turn_id: Any = KEEP) -> Binding:
    """Atributsiyani qo'yadi; berilmagan maydon o'zgarmaydi, `None` tozalaydi.

        with bind(user.actorId, "web", rec.turn_id):
            ...                     # ichidagi har `metered(...)` shu uchlikni oladi
    """
    return Binding(actor_id, channel, turn_id)


def carry(fn: F) -> F:
    """`fn` ni JORIY kontekst bilan o'raydi - boshqa ipda ishga tushirish uchun.

        threading.Thread(target=carry(pump), daemon=True).start()

    Har chaqiruv kontekstning O'Z nusxasida ishlaydi: bitta `Context`
    obyektiga ikki ip bir vaqtda kira olmaydi (`RuntimeError`), o'ralgan
    funksiya esa bir necha marta chaqirilishi mumkin.
    """
    captured = contextvars.copy_context()

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        return captured.copy().run(fn, *args, **kwargs)

    return run  # type: ignore[return-value]


# --- sirlarni olib tashlash ----------------------------------------------------

#: Sozlamadagi sirlar - AYNAN qiymati bilan olib tashlanadi. Bu asosiy to'r:
#: qiymatni bilib turib o'chirish taxminga bog'liq emas.
_SECRET_SETTINGS = (
    "hrm_assistant_client_secret", "tts_client_secret", "gapi_api_key", "gapi_api_key2",
    "ollama_api_key", "venera_api_url", "telegram_bot_token", "crm_client_secret",
    "crm_password", "secret_key", "hrm_token", "crm_token",
)

#: Ikkinchi to'r - SHAKL bo'yicha. Har biri loyihadagi mavjud yordamchining
#: naqshi: JWT (`crm_auth._safe`), Ollama kaliti (`ollama._safe`), GAPI
#: (`gapi_stt._safe`), Telegram bot tokeni (`telegram._redact`).
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+"), "Bearer <token>"),
    (re.compile(r"eyJ[\w-]{8,}(?:\.[\w-]+){0,2}"), "<token>"),
    (re.compile(r"\bbot\d{5,}:[\w-]{20,}"), "bot<token>"),
    (re.compile(r"\b\d{5,}:[\w-]{30,}"), "<token>"),
    (re.compile(r"\b[0-9a-f]{32}\.[\w-]{16,}"), "<key>"),
    (re.compile(r"\bgapi_[\w-]+"), "<key>"),
    (re.compile(
        r"(?i)([\"']?\b(?:password|passwd|secret|client_secret|x-client-secret|api[_-]?key|"
        r"access_token|refresh_token|id_token|token|authorization|init_?data|hash)\b[\"']?"
        r"\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s&,;}]+)"),
     r"\1***"),
)


def redact(text: Any, limit: int = _ERROR_LIMIT) -> str:
    """Xato matnidan sirlarni olib tashlaydi va `limit` belgigacha qisqartiradi.

    Platforma tokenlari, parol, `Authorization`, `initData`, `X-Client-Secret`
    hech qachon omborga tushmasligi kerak: admin panelni ko'rgan odam ular
    orqali boshqa odam nomidan kira olardi.
    """
    try:
        value = str(text if text is not None else "")
        if not value:
            return ""
        for name in _SECRET_SETTINGS:
            secret = getattr(settings, name, "")
            if isinstance(secret, str) and len(secret) >= 8 and secret in value:
                value = value.replace(secret, "***")
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        value = " ".join(value.split())
        if limit and len(value) > limit:
            value = value[:max(1, limit - 1)] + "…"
        return value
    except Exception:                                       # noqa: BLE001
        return "<redaction failed>"


def http_status_of(exc: BaseException | None) -> int | None:
    """Xatodan HTTP status: `.status`, bo'lmasa `.code`, bo'lmasa
    `.http_status` - faqat butun son bo'lsa (`code="BAD_RESPONSE"` emas)."""
    if exc is None:
        return None
    for attr in ("status", "code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


def _units_json(units: Mapping[str, Any] | None) -> str | None:
    """Faqat sonlar; bo'sh bo'lsa `None`. Kalitlar: audioSec, chars, bytes, frames."""
    if not units:
        return None
    clean: dict[str, float | int] = {}
    for key, value in units.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        clean[str(key)[:32]] = round(value, 3) if isinstance(value, float) else value
    return json.dumps(clean, separators=(",", ":")) if clean else None


def _name(value: Any) -> str:
    return (str(value or "").strip() or "?")[:_NAME_LIMIT]


def _error_text(error: Any) -> str | None:
    if error is None:
        return None
    if isinstance(error, GeneratorExit):
        return "cancelled"
    if isinstance(error, BaseException):
        text = str(error)
        return redact(f"{type(error).__name__}: {text}" if text else type(error).__name__)
    return redact(error) or None


# --- chaqiruvni yozish ---------------------------------------------------------


def record_call(
    service: str,
    op: str,
    *,
    status: str = "ok",
    duration_ms: float | int = 0,
    http_status: int | None = None,
    units: Mapping[str, Any] | None = None,
    error: Any = None,
    actor_id: Any = KEEP,
    channel: Any = KEEP,
    turn_id: Any = KEEP,
    ts: float | None = None,
    writer: Writer | None = None,
) -> bool:
    """Bitta chaqiruvni to'g'ridan-to'g'ri yozadi. Berilmagan atributsiya
    joriy kontekstdan olinadi. `False` - yozilmadi (o'chiq yoki navbat to'la).
    """
    try:
        if not _db.analytics_enabled():
            return False
        now = current()
        actor = now.actor_id if actor_id is KEEP else _actor(actor_id)
        chan = now.channel if channel is KEEP else (
            _normalize_channel(channel, default=None) if channel is not None else None)
        turn = now.turn_id if turn_id is KEEP else (str(turn_id) if turn_id else None)
        state = "ok" if status == "ok" else "error"
        http = http_status if isinstance(http_status, int) and not isinstance(http_status, bool) \
            else None
        params = (
            ts if ts is not None else time.time(),
            _name(service), _name(op), state, http,
            max(0, int(round(duration_ms or 0))),
            actor, chan, turn, _units_json(units), _error_text(error),
        )
        return (writer or get_writer()).submit(_INSERT_CALL, params)
    except Exception:                                       # noqa: BLE001
        log_limited("meter.record", "Chaqiruv hisobi yozilmadi", exc_info=True)
        return False


class Call:
    """Boshlangan chaqiruv. Atributsiya va vaqt `begin` paytida olinadi,
    `end` esa istalgan ipdan va istalgan paytda (bir marta) chaqiriladi.

    `units` - lug'at, chaqiruv davomida to'ldirish mumkin
    (`call.units["bytes"] += len(chunk)`).
    """

    __slots__ = ("service", "op", "units", "http_status", "error", "_failed", "_t0", "_ts",
                 "_who", "_done", "_writer", "_enabled")

    def __init__(self, service: str, op: str, *, units: Mapping[str, Any] | None = None,
                 actor_id: Any = KEEP, channel: Any = KEEP, turn_id: Any = KEEP,
                 writer: Writer | None = None) -> None:
        self.service = service
        self.op = op
        self.units: dict[str, Any] = dict(units or {})
        self.http_status: int | None = None
        self.error: Any = None
        self._failed = False
        self._t0 = time.monotonic()
        self._ts = time.time()
        now = current()
        self._who = (
            now.actor_id if actor_id is KEEP else actor_id,
            now.channel if channel is KEEP else channel,
            now.turn_id if turn_id is KEEP else turn_id,
        )
        self._done = False
        self._writer = writer
        self._enabled = _db.analytics_enabled()

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def fail(self, error: Any = None, *, http_status: int | None = None) -> None:
        """Xatosiz yakunlangan, lekin natijasi xato bo'lgan chaqiruv (masalan
        HTTP 503 javobi istisnosiz qaytgan)."""
        self._failed = True
        if error is not None:
            self.error = error
        if http_status is not None:
            self.http_status = http_status

    def end(self, status: str | None = None, *, http_status: int | None = None,
            error: Any = None, units: Mapping[str, Any] | None = None) -> bool:
        """Yozadi. Ikkinchi chaqiruv hech narsa qilmaydi (`False`)."""
        if self._done:
            return False
        self._done = True
        try:
            if not self._enabled:
                return False
            if units:
                self.units.update(units)
            if error is not None:
                self.error = error
            if http_status is None:
                http_status = self.http_status
            if http_status is None and isinstance(self.error, BaseException):
                http_status = http_status_of(self.error)
            if status is None:
                status = "error" if (self._failed or self.error is not None) else "ok"
            actor, chan, turn = self._who
            return record_call(
                self.service, self.op, status=status, duration_ms=self.elapsed_ms,
                http_status=http_status, units=self.units, error=self.error,
                actor_id=actor, channel=chan, turn_id=turn, ts=self._ts, writer=self._writer,
            )
        except Exception:                                   # noqa: BLE001
            log_limited("meter.end", "Chaqiruv hisobi yakunlanmadi", exc_info=True)
            return False


def begin(service: str, op: str, *, units: Mapping[str, Any] | None = None,
          actor_id: Any = KEEP, channel: Any = KEEP, turn_id: Any = KEEP,
          writer: Writer | None = None) -> Call:
    """Chaqiruvni boshlaydi (oqimlar uchun): `call = begin("assistant", "stream")`,
    oqim tugaganda `call.end(units={"frames": n})`."""
    try:
        return Call(service, op, units=units, actor_id=actor_id, channel=channel,
                    turn_id=turn_id, writer=writer)
    except Exception:                                       # noqa: BLE001
        log_limited("meter.begin", "Chaqiruv hisobi boshlanmadi", exc_info=True)
        # Yozmaydigan, lekin chaqiruvchi uchun to'liq ishlaydigan obyekt:
        # `call.units[...] = ...` va `call.end()` xato bermasligi kerak.
        call = Call(service, op, writer=writer, actor_id=None, channel=None, turn_id=None)
        call._done = True
        return call


@contextlib.contextmanager
def metered(service: str, op: str, *, units: Mapping[str, Any] | None = None,
            actor_id: Any = KEEP, channel: Any = KEEP, turn_id: Any = KEEP,
            writer: Writer | None = None) -> Iterator[Call]:
    """Sinxron chaqiruvni o'lchaydi:

        with metered("tts", "speak", units={"chars": len(text)}) as call:
            audio = client.speak(text)
            call.units["audioSec"] = seconds

    Istisno bo'lsa: `status=error`, `http_status` istisnodan (`.status` /
    `.code`), `error` - sirsiz, 300 belgigacha. Istisno O'ZGARMASDAN qaytadi.
    """
    call = begin(service, op, units=units, actor_id=actor_id, channel=channel,
                 turn_id=turn_id, writer=writer)
    try:
        yield call
    except BaseException as exc:
        call.end("error", error=exc)
        raise
    else:
        call.end()


def record_auth_event(login: Any, ok: bool, *, method: str | None = None,
                      channel: str | None = None, reason: str | None = None,
                      actor_id: Any = None, ts: float | None = None,
                      writer: Writer | None = None) -> bool:
    """Kirish urinishi (`auth_events`). PAROL HECH QACHON berilmaydi; login
    kichik harfda va 128 belgigacha, sabab - qisqa kod (`bad_password`,
    `blocked`, ...)."""
    try:
        if not _db.analytics_enabled():
            return False
        params = (
            ts if ts is not None else time.time(),
            _actor(actor_id),
            (str(login or "").strip().lower()[:128] or None),
            1 if ok else 0,
            (str(method)[:16] if method else None),
            (_normalize_channel(channel, default=None) if channel else None),
            (redact(reason, 120) if reason else None),
        )
        return (writer or get_writer()).submit(_INSERT_AUTH, params)
    except Exception:                                       # noqa: BLE001
        log_limited("meter.auth", "Kirish hodisasi yozilmadi", exc_info=True)
        return False

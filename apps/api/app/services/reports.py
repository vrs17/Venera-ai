"""Shikoyatlar ("Xabar berish") - foydalanuvchi tomoni: yaratish.

NIMA SAQLANADI. Butun suhbatning SURATI (`snapshot`) - shikoyat qilingan
paytdagi holati. Havola emas, nusxa: suhbat keyin o'chirilishi, davom
ettirilishi yoki muddati o'tib telemetriyadan tozalanishi mumkin, admin
esa odam aynan NIMANI ko'rib shikoyat qilganini ko'rishi kerak. Shikoyatlar
tozalashda (`writer.purge`) O'CHIRILMAYDI - ular statistika emas, hujjat.

SURAT QAYERDAN - ustunlik tartibida:

  1. TELEMETRIYA (`turns`): o'sha `chatId` dagi, O'SHA ODAMNING savollari.
     Eng boy manba - har javobning izi (`turnId`), manbalari va holati bor,
     va egalik tekshirilgan (`actor_id`). Boshqa odamning savoli suratga
     TUSHMAYDI, hatto u o'sha `chatId` ni yuborgan bo'lsa ham.
  2. YUQORIDAGI XIZMAT (`get_chat`): suhbat tarixi odamning O'Z kaliti
     (`venera:{actorId}`) bilan so'raladi - boshqa odamning suhbati 404.
     Telemetriya o'chiq yoki savollar tozalangan bo'lsa ishlaydi. Xatosi
     shikoyatni TO'XTATMAYDI.
  3. KLIENT nusxasi (`messages`): tekshirib bo'lmaydi - shuning uchun
     `source: client` deb belgilanadi, admin buni biladi.

CHEGARA: bitta odam soatiga 20 ta. Xotirada (bitta jarayon) - bu
suiiste'moldan himoya, hisob emas; qayta ishga tushish uni tozalasa zarar
yo'q.

JURNALGA izoh va xabar MATNI yozilmaydi (shaxsiy ma'lumot) - faqat
`actorId`, manba va xabarlar soni.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid

from collections import deque
from typing import Any, Callable, Iterable, Mapping

from ..schemas.auth import AuthUser
from . import analytics
from .analytics.db import Database, get_db, iter_chunks, log_limited
from .analytics.queries import iso
from .analytics.recorder import valid_turn_id

log = logging.getLogger(__name__)

RATE_LIMIT = 20
RATE_WINDOW = 3600.0
#: Suratdagi eng ko'p savol (har biri - ikki xabar). Juda uzun suhbatda
#: oxirgilari olinadi: shikoyat odatda oxirgi javob haqida.
SNAPSHOT_TURNS = 100
#: Bitta xabar matni suratda shundan uzun bo'lmaydi (klient chegarasi bilan bir xil).
CONTENT_CAP = 20_000
#: Butun surat (JSON) chegarasi - oshsa eng eski savollar tashlanadi.
SNAPSHOT_BYTES = 2 * 1024 * 1024
#: Telemetriya `chat_id` ni shu uzunlikda saqlaydi (`recorder._str(chat_id, 64)`).
_CHAT_KEY = 64
#: Yangi yozilgan savol omborga tushishini shuncha kutamiz (so'rov yo'lida).
_FLUSH_WAIT = 2.0

#: Klient manbasidan saqlanadigan maydonlar. Qolgani (havolalar, ichki
#: kalitlar) tashlanadi: tana tekshirilmagan va omborga to'g'ridan-to'g'ri
#: tushadi.
_SOURCE_KEYS = ("kind", "doc_id", "documentId", "title", "documentTitle", "page", "tool",
                "status", "digest", "citation_index", "marker", "score", "snippet")
_SNIPPET_CAP = 2048
_FIELD_CAP = 512


class ReportError(Exception):
    """Shikoyat qabul qilinmadi. `status` HTTP kodi bo'ladi."""

    def __init__(self, message: str, *, status: int = 400, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


# --- chegara ---------------------------------------------------------------------


class RateLimiter:
    """Sirpanuvchi oyna: `window` soniyada `limit` tadan ko'p emas, kalit bo'yicha."""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW) -> None:
        self.limit = int(limit)
        self.window = float(window)
        self._hits: dict[Any, deque[float]] = {}
        self._lock = threading.Lock()

    def take(self, key: Any, *, now: float | None = None) -> int | None:
        """Joy bo'lsa - band qiladi va `None`; bo'lmasa - bo'shashiga necha
        soniya qolgani (`Retry-After`)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            if len(self._hits) > 10_000:
                # Xotira o'smasin: bo'sh navbatlar tashlanadi.
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return None

    def give_back(self, key: Any) -> None:
        """Band qilingan joyni qaytaradi - shikoyat saqlanmay qolsa."""
        with self._lock:
            hits = self._hits.get(key)
            if hits:
                hits.pop()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


# --- surat --------------------------------------------------------------------------


def _cap(text: Any, limit: int) -> str:
    value = text if isinstance(text, str) else ("" if text is None else str(text))
    return value if len(value) <= limit else value[:limit]


def _message(role: str, content: Any, created_at: Any = None, turn_id: Any = None,
             sources: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    out = {
        "role": role,
        "content": _cap(content, CONTENT_CAP),
        "createdAt": created_at if isinstance(created_at, str) and created_at else None,
        "turnId": turn_id or None,
        "sources": sources or None,
    }
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _clean_source(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    out: dict[str, Any] = {}
    for key in _SOURCE_KEYS:
        value = item.get(key)
        if value is None or isinstance(value, (dict, list, tuple)):
            continue
        if isinstance(value, str):
            value = _cap(value, _SNIPPET_CAP if key == "snippet" else _FIELD_CAP)
        elif not isinstance(value, (int, float, bool)):
            continue
        out[key] = value
    return out or None


def _client_messages(messages: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for raw in messages:
        role = raw.get("role")
        if role not in ("user", "assistant"):
            continue
        sources = [s for s in (_clean_source(i) for i in (raw.get("sources") or [])) if s]
        out.append(_message(role, raw.get("content"), raw.get("createdAt"),
                            valid_turn_id(raw.get("turnId")), sources))
    return out


def _telemetry_messages(db: Database, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`turns` qatorlari -> savol + javob xabarlari, manbalari bilan."""
    ids = [r["id"] for r in rows]
    sources: dict[str, list[dict[str, Any]]] = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for s in db.rows(
            f"SELECT turn_id, kind, ref, title, page, citation, status FROM turn_sources "
            f"WHERE turn_id IN ({marks}) ORDER BY turn_id, idx", ids,
        ):
            item = {k: s[k] for k in ("kind", "ref", "title", "page", "citation", "status")
                    if s[k] is not None}
            sources.setdefault(s["turn_id"], []).append(item)
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(_message("user", r["question"], iso(r["started_at"]), r["id"]))
        out.append(_message("assistant", r.get("answer") or "",
                            iso(r.get("ended_at") or r["started_at"]), r["id"],
                            sources.get(r["id"]), status=r.get("status")))
    return out


def _upstream_messages(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, Mapping):
        return [], None
    out = []
    for raw in payload.get("messages") or []:
        if isinstance(raw, Mapping) and raw.get("role") in ("user", "assistant"):
            out.append(_message(raw["role"], raw.get("content"), raw.get("created_at")))
    title = payload.get("title")
    return out, (title if isinstance(title, str) and title else None)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fit(snapshot: dict[str, Any]) -> str:
    """JSON; `SNAPSHOT_BYTES` dan oshsa eng eski xabarlar (juft-juft) tashlanadi.

    NEGA BIR O'TISHDA. Har tashlashdan keyin BUTUN suratni qayta yozish
    O(n²) edi: 200 ta uzun xabar (klient chegarasi) - ~1.2 s sof CPU, va
    `json.dumps` shu vaqt GIL ni ushlab turadi, ya'ni boshqa odamlarning
    oqimlari ham to'xtab qolardi. Endi har xabar hajmi bir marta o'lchanadi,
    nechtasini tashlash hisoblanadi va surat bir marta yoziladi. Oxirgi
    tsikl - faqat hisob adashgan kamdan-kam holat uchun to'r.
    """
    text = _dumps(snapshot)
    messages = snapshot["messages"]
    size = len(text.encode("utf-8"))
    if size <= SNAPSHOT_BYTES or len(messages) <= 2:
        return text
    # Massivdan xabar olinsa, uning JSON'i va bitta vergul ketadi.
    sizes = [len(_dumps(m).encode("utf-8")) + 1 for m in messages]
    # `"truncated":true` belgisi qo'shiladi - joyi oldindan ajratiladi.
    size += len(',"truncated":true')
    drop = 0
    while size > SNAPSHOT_BYTES and len(messages) - drop > 2:
        size -= sizes[drop] + sizes[drop + 1]
        drop += 2
    del messages[:drop]
    snapshot["truncated"] = True
    text = _dumps(snapshot)
    while len(text.encode("utf-8")) > SNAPSHOT_BYTES and len(messages) > 2:
        del messages[:2]
        text = _dumps(snapshot)
    return text


def build_snapshot(actor_id: int, *, chat_id: str | None, turn_id: str | None,
                   messages: list[Mapping[str, Any]] | None = None,
                   upstream: Callable[[str], Any] | None = None,
                   db: Database | None = None) -> tuple[dict[str, Any], str | None, str | None]:
    """(surat, suhbat kaliti, savol kaliti). Savol kaliti faqat O'SHA ODAMGA
    tegishli bo'lsa qoladi - aks holda `None` (boshqa odamning izi
    shikoyatga ilinmaydi)."""
    db = db or get_db()
    owned_turn: dict[str, Any] | None = None
    chat_rows: list[dict[str, Any]] = []
    if chat_id or turn_id:
        # Hozirgina tugagan savol hali navbatda bo'lishi mumkin.
        analytics.flush(_FLUSH_WAIT)
        try:
            if turn_id:
                row = db.row("SELECT * FROM turns WHERE id = ?", (turn_id,))
                if row is not None and row.get("actor_id") == actor_id:
                    owned_turn = row
                    chat_id = chat_id or row.get("chat_id")
                elif row is not None:
                    log.warning("Shikoyat: boshqa odamning savoli (%s) - ilinmadi", actor_id)
            if chat_id:
                chat_rows = db.rows(
                    "SELECT * FROM turns WHERE chat_id = ? AND actor_id = ? "
                    "ORDER BY started_at DESC, id DESC LIMIT ?",
                    (chat_id[:_CHAT_KEY], actor_id, SNAPSHOT_TURNS))
                chat_rows.reverse()
                if not chat_rows and _foreign_chat(db, chat_id, actor_id):
                    # Bu suhbatda shu odamning savoli YO'Q, boshqa odamniki bor -
                    # kalit begona (taxmin qilingan yoki nusxalangan). Saqlansa,
                    # admin panelda begona suhbat "xabar berilgan" deb belgilanar
                    # va uning har savoli izida shu shikoyat chiqardi. Kalit
                    # tashlanadi; odamning O'Z savoli berilgan bo'lsa - o'sha
                    # savolning suhbati olinadi (server bilgan haqiqat).
                    log.warning("Shikoyat: begona suhbat kaliti (%s) - ilinmadi", actor_id)
                    chat_id = (owned_turn or {}).get("chat_id")
                    if owned_turn is not None:
                        chat_rows = [owned_turn]
            elif owned_turn is not None:
                chat_rows = [owned_turn]
            if chat_rows:
                snap = {"source": "telemetry", "messages": _telemetry_messages(db, chat_rows)}
                return snap, chat_id, (owned_turn or {}).get("id")
        except (sqlite3.Error, OSError):
            log_limited("reports.telemetry", "Shikoyat: telemetriya o'qilmadi", exc_info=True)

    if chat_id and upstream is not None:
        try:
            found, title = _upstream_messages(upstream(chat_id))
        except Exception as exc:                            # noqa: BLE001
            # Xizmat yiqilgan, suhbat o'chirilgan yoki boshqa odamniki (404) -
            # shikoyat baribir qabul qilinadi, klient nusxasi bilan.
            log.info("Shikoyat: suhbat tarixi olinmadi (%s): %s", actor_id, type(exc).__name__)
        else:
            if found:
                snap = {"source": "upstream", "messages": found,
                        **({"title": title} if title else {})}
                return snap, chat_id, (owned_turn or {}).get("id")

    found = _owned_only(db, actor_id, _client_messages(messages or []))
    return {"source": "client", "messages": found}, chat_id, (owned_turn or {}).get("id")


def _foreign_chat(db: Database, chat_id: str, actor_id: int) -> bool:
    """Telemetriyada bu suhbat BOSHQA odamniki ekani ko'rinib turibdimi.

    Faqat ijobiy dalil: savollari yo'q suhbat (telemetriyadan oldingi, yoki
    tozalangan) begona HISOBLANMAYDI - aks holda odamning eski suhbati
    haqidagi shikoyat kalitini yo'qotardi. `turns_chat` indeksi bilan arzon.
    """
    return db.scalar(
        "SELECT 1 FROM turns WHERE chat_id = ? AND actor_id IS NOT NULL AND actor_id != ? "
        "LIMIT 1", (chat_id[:_CHAT_KEY], actor_id)) is not None


def _owned_only(db: Database, actor_id: int, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Klient xabarlaridagi `turnId` - faqat O'SHA ODAMNIKI bo'lsa qoladi.

    Aks holda klient suratga boshqa odamning savol kalitini yozib, admin
    paneldagi "iz" havolasini unga yo'naltira olardi. Tekshirib bo'lmagani
    (telemetriya o'chiq, savol tozalangan) ham olib tashlanadi - tasdiqlanmagan
    bog'lanishdan bog'lanmagani yaxshi.
    """
    claimed = sorted({m["turnId"] for m in found if m.get("turnId")})
    owned: set[str] = set()
    if claimed:
        analytics.flush(_FLUSH_WAIT)
        try:
            for part in iter_chunks(claimed, 400):
                marks = ",".join("?" * len(part))
                owned.update(r["id"] for r in db.rows(
                    f"SELECT id FROM turns WHERE actor_id = ? AND id IN ({marks})",
                    (actor_id, *part)))
        except (sqlite3.Error, OSError):
            log_limited("reports.owned", "Shikoyat: savol egaligi tekshirilmadi", exc_info=True)
    for message in found:
        if message.get("turnId") and message["turnId"] not in owned:
            message["turnId"] = None
    return found


# --- yaratish ----------------------------------------------------------------------


def create(user: AuthUser, *, channel: str, chat_id: str | None = None,
           turn_id: str | None = None, reason: str | None = None, comment: str | None = None,
           messages: list[Mapping[str, Any]] | None = None,
           upstream: Callable[[str], Any] | None = None, db: Database | None = None,
           now: float | None = None) -> dict[str, Any]:
    """Shikoyatni saqlaydi -> `{id, status, createdAt}`.

    Ombor yozuvi SINXRON (`transaction`), navbat orqali emas: odam
    "Yuborildi" ni ko'rsa, shikoyat haqiqatan diskda bo'lishi kerak. Yozuv
    yiqilsa - 503, chegara joyi qaytariladi.
    """
    turn_key = None
    if turn_id:
        turn_key = valid_turn_id(turn_id)
        if turn_key is None:
            raise ReportError("turnId noto'g'ri", status=422)
    chat_key = chat_id.strip() if isinstance(chat_id, str) and chat_id.strip() else None

    wait = limiter.take(user.actorId)
    if wait is not None:
        raise ReportError("Juda ko'p xabar yuborildi - birozdan keyin qayta urinib ko'ring",
                          status=429, retry_after=wait)
    db = db or get_db()
    now = time.time() if now is None else now
    try:
        snap, chat_key, turn_key = build_snapshot(
            user.actorId, chat_id=chat_key, turn_id=turn_key, messages=messages,
            upstream=upstream, db=db)
        report_id = uuid.uuid4().hex
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO reports (id, created_at, actor_id, user_name, user_login, channel, "
                "chat_id, turn_id, reason, comment, snapshot, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'new')",
                (report_id, now, user.actorId, user.fullName, (user.email or "").lower() or None,
                 channel, chat_key, turn_key, reason, comment, _fit(snap)),
            )
    except (sqlite3.Error, OSError) as exc:
        limiter.give_back(user.actorId)
        log.error("Shikoyat saqlanmadi (%s): %s", user.actorId, exc)
        raise ReportError("Xabar saqlanmadi - birozdan keyin qayta urinib ko'ring",
                          status=503) from exc
    except BaseException:
        limiter.give_back(user.actorId)
        raise
    log.info("Shikoyat (%s): %s, manba=%s, xabarlar=%d, sabab=%s", user.actorId, report_id,
             snap["source"], len(snap["messages"]), reason or "-")
    return {"id": report_id, "status": "new", "createdAt": iso(now)}

"""Admin panel so'rovlari: analitika omboridan o'qish va admin yozuvlari.

NEGA ALOHIDA MODUL. Router (`api/v1/admin.py`) faqat HTTP: parametr, huquq,
javob modeli. SQL va hisob-kitob shu yerda - HTTP'siz test qilinadi va
boshqa bo'limlar ham qayta ishlatadi (`list_turns`, `turn_summaries` -
foydalanuvchi kartasidagi so'nggi savollar). Foydalanuvchilar katalogi va
admin audit jurnali esa `services/admin_users.py` da - bu yerda ular
qayta yozilmaydi.

VAQT. Omborda UTC epoch soniyalari, javobda ISO-8601 UTC (`Z` bilan). Soat
va kun guruhlari esa ORALIQ BOSHIDAN kesiladi (`grid_origin`): brauzer
`from` ni o'z mahalliy yarim tunidan yuboradi va kunlar shu mintaqada
chiqadi - server mintaqani bilmasa ham. Guruh yorlig'i (`t`) - UTC lahza,
uni mahalliy vaqtga o'girish brauzerning ishi.

FOIZLAR (p50/p95) PYTHON'DA. SQLite 3.37 da `percentile` yo'q, oyna
funksiyalari bilan esa o'qib bo'lmaydigan SQL chiqadi. Hajm kichik: bitta
oraliqdan ko'pi bilan `ROW_CAP` qator o'qiladi - bu yuzlab millisekund,
admin panel uchun maqbul.

SAHIFALASH KALIT BO'YICHA (keyset), `OFFSET` emas. `OFFSET 5000` SQLite'ni
5000 qatorni o'qib tashlashga majbur qiladi, va sahifalar orasida yangi
savol kelsa ro'yxat siljib, qator takrorlanadi yoki tushib qoladi. Kursor
esa "shu qatordan keyingilar" deydi - yangi yozuvlar unga ta'sir qilmaydi.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import math
import re
import sqlite3
import time

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from ...core.channels import CHANNELS
from .db import Database, iter_chunks

if TYPE_CHECKING:                                           # pragma: no cover
    from ...schemas.auth import AuthUser

log = logging.getLogger(__name__)

# --- chegaralar -------------------------------------------------------------------

#: Bitta oraliqdan hisob uchun o'qiladigan qatorlar chegarasi. Undan ko'pi -
#: eng yangilari olinadi va jurnalga yoziladi.
ROW_CAP = 200_000
#: KPI kartochkasidagi kichik chiziq nuqtalari (dizayn: 14 ta).
SPARK_POINTS = 14
#: Ro'yxatdagi savol matni - bitta qatorga sig'adigan qismi.
QUESTION_PREVIEW = 240
#: Xabar izohining ko'rinishi va suhbat nomi.
PREVIEW = 160
TITLE_PREVIEW = 80
TOP_DOCS = 8
TOP_TOOLS = 8
#: Oraliq berilmasa - oxirgi 7 kun.
DEFAULT_DAYS = 7
#: Oraliq shundan uzun bo'lsa guruh - kun, aks holda soat.
HOURLY_MAX = 2 * 86400.0
#: Undan uzun oraliq so'ralmaydi: 180 kunlik saqlash muddatida ikki yil
#: yetarlidan ortiq, cheksiz oraliq esa minglab bo'sh nuqta yasardi.
MAX_RANGE = 731 * 86400.0
NOTE_CAP = 2000

TURN_STATUSES = ("running", "ok", "error", "cancelled")
#: Dvigatel filtri (`?engine=`): `default` - ustun NULL (versiyasiz yo'l yoki
#: yordamchiga bormagan javob), umumiy ko'rinishdagi `engines` bilan bir xil nom.
TURN_ENGINES = ("v1", "v2", "v3", "default")
#: NULL dvigatelning ko'rinadigan nomi (`engines[].engine`).
DEFAULT_ENGINE = "default"
REPORT_STATUSES = ("new", "reviewing", "resolved", "dismissed")
REPORT_REASONS = ("wrong", "incomplete", "outdated", "unsafe", "other")
#: Foydalanish sahifasidagi xizmatlar TARTIBI. Chaqiruvi bo'lmasa ham
#: chiqadi (nol bilan) - kartochkalar joyidan sakramasin.
KNOWN_SERVICES = ("assistant", "stt_router", "stt_gapi", "tts", "ollama", "hrm", "crm",
                  "keycloak", "telegram")
#: Kanalsiz chaqiruv (ishga tushishdagi qizdirish, agent sessiyasini
#: yangilash) - hech bir foydalanuvchi so'rovi emas.
SYSTEM_CHANNEL = "system"
#: Manba "platforma chaqiruvi" (hujjat emas) - `recorder.py` dagi bilan bir xil.
TOOL_KINDS = ("hrm", "crm", "tool")

#: "Qiymat berilmadi" belgisi - `None` esa "tozala" degani.
KEEP: Any = object()


class QueryError(ValueError):
    """Parametr noto'g'ri - router uni 422 ga o'giradi. Matn foydalanuvchiga
    ko'rinadi, shuning uchun qisqa va aniq."""


# --- vaqt ------------------------------------------------------------------------


def iso(ts: Any) -> str | None:
    """Epoch -> `2026-09-29T10:15:30.123Z`. Buzuq qiymat - `None`."""
    if ts is None:
        return None
    try:
        moment = datetime.fromtimestamp(float(ts), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


_EPOCH = re.compile(r"\d{9,}(\.\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: `?from=...T00:00+05:00` - URL'da kodlanmagan `+` bo'shliqqa aylanadi.
_LOST_PLUS = re.compile(r"T(.+) (\d{2}:?\d{2})$")


def parse_time(value: Any, *, name: str = "sana", end: bool = False) -> float | None:
    """So'rovdagi vaqt -> epoch soniya. Qabul qilinadi:

      * ISO-8601: `2026-09-29T10:00:00.000Z`, `...+05:00`, zonasiz (UTC deb);
      * faqat sana: `2026-09-29` - UTC yarim tun; `end=True` bo'lsa KEYINGI
        kunning boshi, ya'ni `to=2026-09-29` shu kunni ham o'z ichiga oladi;
      * epoch soniya yoki millisekund (9+ raqam).

    Tanilmasa `QueryError`.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _EPOCH.fullmatch(text):
        number = float(text)
        return number / 1000.0 if number > 1e11 else number
    raw = text
    if raw[-1] in "Zz":
        raw = raw[:-1] + "+00:00"
    raw = _LOST_PLUS.sub(r"T\1+\2", raw)
    try:
        if _DATE.fullmatch(raw):
            day = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return day.timestamp() + (86400.0 if end else 0.0)
        moment = datetime.fromisoformat(raw)
    except ValueError:
        raise QueryError(f"{name}: sana noto'g'ri") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def resolve_range(start: float | None, end: float | None, *, default_days: int = DEFAULT_DAYS,
                  now: float | None = None) -> tuple[float, float]:
    """`[start, end)` oralig'i; berilmagan chegara - hozir / `default_days` oldin."""
    stop = end if end is not None else (time.time() if now is None else now)
    begin = start if start is not None else stop - default_days * 86400.0
    if begin >= stop:
        raise QueryError("from: 'to' dan oldin bo'lishi kerak")
    if stop - begin > MAX_RANGE:
        raise QueryError("oraliq 2 yildan oshmasin")
    return begin, stop


def bucket_for(start: float, end: float) -> str:
    """Grafik guruhi: 2 kungacha - soat, undan uzun - kun."""
    return "hour" if end - start <= HOURLY_MAX else "day"


def _step(bucket: str) -> float:
    return 3600.0 if bucket == "hour" else 86400.0


#: Soat mintaqalari siljishi 15 daqiqaga karrali (+05:00, +05:30, +05:45).
_ZONE_GRAIN = 900.0


def grid_origin(start: float, bucket: str) -> float:
    """Guruhlar to'rining siljishi (0 - UTC chegaralari).

    NEGA. Admin panel oraliqni MAHALLIY yarim tundan yuboradi (Toshkentda
    `...T19:00:00Z`). Kunlar UTC yarim tunidan kesilsa, har "kun" mahalliy
    05:00 dan 05:00 gacha bo'lib, 30 kunlik oraliq 31 ta chala ustun bo'lardi
    - buni brauzer qayta tuzata olmaydi (sonlar allaqachon qo'shilgan). Shuning
    uchun `start` 15 daqiqaga karrali bo'lsa (ya'ni kimningdir mahalliy soat
    boshi), to'r AYNAN o'sha nuqtadan boshlanadi. Aks holda (`from` berilmagan,
    "hozirdan 7 kun oldin") - odatdagi UTC chegaralari: soat/kun boshi.
    Yozgi vaqt o'tishida kun 23/25 soat bo'lishi hisobga olinmaydi (O'zbekistonda
    yo'q).
    """
    if start % _ZONE_GRAIN == 0:
        return start % _step(bucket)
    return 0.0


def floor_bucket(ts: float, bucket: str, origin: float = 0.0) -> float:
    """Guruh boshi: `origin` siljishli soat yoki kun boshi (0 - UTC)."""
    step = _step(bucket)
    return math.floor((ts - origin) / step) * step + origin


def bucket_starts(start: float, end: float, bucket: str) -> list[float]:
    """Oraliqni qoplaydigan guruhlar boshlari - BO'SHLARI ham: grafikda
    jimlik ham ko'rinishi kerak, chiziq esa uni sakrab o'tmasligi kerak.
    To'r `grid_origin` dan boshlanadi (mahalliy kunlar)."""
    step = _step(bucket)
    out: list[float] = []
    moment = floor_bucket(start, bucket, grid_origin(start, bucket))
    while moment < end:
        out.append(moment)
        moment += step
    return out


def _segment(ts: float, start: float, end: float, points: int = SPARK_POINTS) -> int:
    """Kichik chiziq uchun: oraliq `points` ta TENG bo'lakka bo'linadi."""
    width = (end - start) / points
    index = int((ts - start) / width) if width > 0 else 0
    return min(max(index, 0), points - 1)


# --- foizlar -------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float | None:
    """`values` TARTIBLANGAN bo'lishi shart. Chiziqli interpolyatsiya
    (numpy'ning default usuli): kichik to'plamda ham silliq natija beradi."""
    count = len(values)
    if not count:
        return None
    if count == 1:
        return float(values[0])
    position = (count - 1) * q
    low = int(math.floor(position))
    high = min(low + 1, count - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def _ms(value: float | None) -> int | None:
    return None if value is None else int(round(value))


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


# --- kursor -----------------------------------------------------------------------


def encode_cursor(ts: float, key: str) -> str:
    """Oxirgi qatorning (vaqt, kalit) jufti -> URL uchun xavfsiz satr.

    `json` float'ni `repr` bilan yozadi, ya'ni vaqt AYNAN qaytadi - aks
    holda bir xil soniyadagi qatorlar chegarada yo'qolishi mumkin edi.
    """
    raw = json.dumps([ts, key], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> tuple[float, str] | None:
    """`encode_cursor` ning teskarisi; buzuq bo'lsa `QueryError`."""
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        ts, key = data
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not isinstance(key, str):
            raise ValueError("shakl")
        return float(ts), key
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise QueryError("cursor: noto'g'ri qiymat") from None


def _after(ts_col: str, key_col: str, cursor: tuple[float, str] | None,
           conds: list[str], params: list[Any]) -> None:
    """Kamayish tartibida "kursordan keyingilar" sharti."""
    if cursor is None:
        return
    ts, key = cursor
    conds.append(f"({ts_col} < ? OR ({ts_col} = ? AND {key_col} < ?))")
    params.extend((ts, ts, key))


# --- qidiruv matni ------------------------------------------------------------------

#: O'zbekcha tutuq belgisi to'rt xil yoziladi: `ta'til`, `taʼtil`, `taʻtil`,
#: `ta’til`. Qidiruv qaysi biri bilan yozilsa ham topsin.
_APOSTROPHES = ("'", "ʻ", "ʼ", "’", "‘")


def _like_patterns(q: str) -> list[str]:
    """`LIKE` naqshlari. SQLite `LIKE` faqat LOTIN (ASCII) harflarida registrga
    qaramaydi, kirill va boshqa harflar uchun esa kichik/katta/bosh harfli
    variantlar qo'shiladi."""
    text = q.strip()
    forms = [text]
    if any(mark in text for mark in _APOSTROPHES):
        for mark in _APOSTROPHES:
            form = text
            for other in _APOSTROPHES:
                form = form.replace(other, mark)
            if form not in forms:
                forms.append(form)
    if not text.isascii():
        for form in list(forms):
            for variant in (form.lower(), form.upper(), form.capitalize()):
                if variant not in forms:
                    forms.append(variant)
    escaped = [f.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for f in forms]
    return [f"%{f}%" for f in escaped]


def _match(columns: Sequence[str], q: str) -> tuple[str, list[Any]]:
    """`(col1 LIKE ? OR col2 LIKE ? ...)` va parametrlari."""
    patterns = _like_patterns(q)
    terms: list[str] = []
    params: list[Any] = []
    for column in columns:
        for pattern in patterns:
            terms.append(f"{column} LIKE ? ESCAPE '\\'")
            params.append(pattern)
    return "(" + " OR ".join(terms) + ")", params


def _where(conds: Sequence[str]) -> str:
    return ("WHERE " + " AND ".join(conds)) if conds else ""


def _marks(items: Sequence[Any]) -> str:
    return ",".join("?" * len(items))


def _preview(text: Any, limit: int) -> str | None:
    if not isinstance(text, str):
        return None
    value = " ".join(text.split())
    return value[:limit] if value else None


def _first_line(text: Any, limit: int = PREVIEW) -> str | None:
    if not isinstance(text, str):
        return None
    for line in text.splitlines():
        line = line.strip()
        if line:
            return " ".join(line.split())[:limit]
    return None


def _json(text: Any) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


# --- savollar: filtr --------------------------------------------------------------

#: Savol "xabar berilgan": shikoyat AYNAN unga (`turn_id`) yoki butun
#: suhbatiga (`turn_id` siz, `chat_id` bilan) yozilgan. `x IN (...)` NULL
#: bilan NULL qaytaradi va `NOT` ni buzadi - shuning uchun `IS NOT NULL`
#: shartlari bor.
_TURN_REPORTED = (
    "({a}.id IN (SELECT turn_id FROM reports WHERE turn_id IS NOT NULL) OR "
    "({a}.chat_id IS NOT NULL AND {a}.chat_id IN "
    "(SELECT chat_id FROM reports WHERE turn_id IS NULL AND chat_id IS NOT NULL)))"
)
#: Suhbat "xabar berilgan": shikoyat suhbatga yoki uning biror savoliga.
_CHAT_REPORTED = (
    "({a}.chat_id IN (SELECT chat_id FROM reports WHERE chat_id IS NOT NULL) OR "
    "{a}.chat_id IN (SELECT tt.chat_id FROM reports rr JOIN turns tt ON tt.id = rr.turn_id "
    "WHERE tt.chat_id IS NOT NULL))"
)


@dataclass(frozen=True)
class TurnFilter:
    """Savollar ro'yxati, suhbatlar va qidiruvning umumiy filtri.

    `route="none"` - yo'nalishsiz savollar (xato yoki bekor qilingan).
    `reported`: `True` - faqat xabar berilganlar, `False` - faqat berilmaganlar.
    `engine`: `v1` | `v2` | `default` (dvigatel yozilmagan - versiyasiz yo'l).
    """

    start: float | None = None
    end: float | None = None
    channel: str | None = None
    q: str | None = None
    actor_id: int | None = None
    route: str | None = None
    status: str | None = None
    reported: bool | None = None
    min_ms: int | None = None
    chat_id: str | None = None
    engine: str | None = None

    def where(self, alias: str = "t", *, chats: bool = False) -> tuple[list[str], list[Any]]:
        a = alias
        conds: list[str] = []
        params: list[Any] = []
        if self.engine:
            if self.engine == DEFAULT_ENGINE:
                conds.append(f"{a}.engine IS NULL")
            else:
                conds.append(f"{a}.engine = ?")
                params.append(self.engine)
        if self.start is not None:
            conds.append(f"{a}.started_at >= ?")
            params.append(self.start)
        if self.end is not None:
            conds.append(f"{a}.started_at < ?")
            params.append(self.end)
        if self.channel:
            conds.append(f"{a}.channel = ?")
            params.append(self.channel)
        if self.actor_id is not None:
            conds.append(f"{a}.actor_id = ?")
            params.append(self.actor_id)
        if self.route:
            if self.route == "none":
                conds.append(f"{a}.route IS NULL")
            else:
                conds.append(f"{a}.route = ?")
                params.append(self.route)
        if self.status:
            conds.append(f"{a}.status = ?")
            params.append(self.status)
        if self.min_ms:
            conds.append(f"{a}.total_ms >= ?")
            params.append(int(self.min_ms))
        if self.chat_id:
            conds.append(f"{a}.chat_id = ?")
            params.append(self.chat_id)
        if self.q and self.q.strip():
            q = self.q.strip()
            # Kalit (savol, so'rov yoki suhbat) AYNAN qidiriladi - jurnaldan
            # nusxalangan `request_id` bilan to'g'ri savolga borish uchun.
            like, like_params = _match(
                [f"{a}.question", f"{a}.answer", f"{a}.user_name", f"{a}.user_login"], q)
            conds.append(f"({a}.id = ? OR {a}.request_id = ? OR {a}.chat_id = ? OR {like})")
            params.extend((q, q, q, *like_params))
        if self.reported is not None:
            cond = (_CHAT_REPORTED if chats else _TURN_REPORTED).format(a=a)
            conds.append(cond if self.reported else f"NOT {cond}")
        return conds, params


_SUMMARY_COLUMNS = (
    "t.id, t.started_at, t.actor_id, t.user_name, t.user_login, t.channel, t.kind, "
    "t.input_mode, t.chat_id, substr(t.question, 1, {n}) AS question, t.route, t.status, "
    "t.error_code, t.ttft_ms, t.total_ms, t.sources_count, t.tool_calls, t.has_proposal, "
    "t.proposal_status, t.has_artifact, t.engine"
).format(n=QUESTION_PREVIEW)


def _turn_summary(row: Mapping[str, Any], reported: bool) -> dict[str, Any]:
    """types.ts: TurnSummary."""
    return {
        "id": row["id"],
        "startedAt": iso(row["started_at"]),
        "actorId": row["actor_id"],
        "userName": row["user_name"],
        "userLogin": row["user_login"],
        "channel": row["channel"],
        "kind": row["kind"],
        "inputMode": row["input_mode"],
        "chatId": row["chat_id"],
        "question": (row["question"] or "")[:QUESTION_PREVIEW],
        "route": row["route"],
        "status": row["status"],
        "errorCode": row["error_code"],
        "ttftMs": row["ttft_ms"],
        "totalMs": row["total_ms"],
        "sourcesCount": int(row["sources_count"] or 0),
        "toolCalls": int(row["tool_calls"] or 0),
        "hasProposal": bool(row["has_proposal"]),
        "proposalStatus": row["proposal_status"],
        "hasArtifact": bool(row["has_artifact"]),
        "reported": reported,
        # `v1` | `v2`; `null` - versiyasiz yo'l yoki yordamchiga bormagan javob.
        # `.keys()` orqali: ustunsiz qator (boshqa so'rovdan yig'ilgan) ham o'qilsin.
        "engine": row["engine"] if "engine" in row.keys() else None,
    }


def reported_turns(db: Database, rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """Berilgan savollardan qaysilari xabar berilgan (`_TURN_REPORTED` bilan
    bir xil ma'no). Sahifadagi ≤100 qator uchun - butun jadval emas."""
    ids = [r["id"] for r in rows]
    chats = sorted({r["chat_id"] for r in rows if r["chat_id"]})
    found: set[str] = set()
    direct: set[str] = set()
    whole: set[str] = set()
    for part in iter_chunks(ids, 400):
        direct.update(r["turn_id"] for r in db.rows(
            f"SELECT turn_id FROM reports WHERE turn_id IN ({_marks(part)})", part))
    for part in iter_chunks(chats, 400):
        whole.update(r["chat_id"] for r in db.rows(
            f"SELECT chat_id FROM reports WHERE turn_id IS NULL AND chat_id IN ({_marks(part)})",
            part))
    for r in rows:
        if r["id"] in direct or (r["chat_id"] and r["chat_id"] in whole):
            found.add(r["id"])
    return found


def turn_summaries(db: Database, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`_SUMMARY_COLUMNS` qatorlari -> TurnSummary lug'atlari."""
    flags = reported_turns(db, rows) if rows else set()
    return [_turn_summary(r, r["id"] in flags) for r in rows]


def list_turns(db: Database, flt: TurnFilter, *, cursor: str | None = None,
               limit: int = 50) -> dict[str, Any]:
    """Savollar - yangisi birinchi: `{items: TurnSummary[], nextCursor}`."""
    conds, params = flt.where("t")
    _after("t.started_at", "t.id", decode_cursor(cursor), conds, params)
    rows = db.rows(
        f"SELECT {_SUMMARY_COLUMNS} FROM turns t {_where(conds)} "
        "ORDER BY t.started_at DESC, t.id DESC LIMIT ?", (*params, limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": turn_summaries(db, rows),
        "nextCursor": encode_cursor(rows[-1]["started_at"], rows[-1]["id"]) if more else None,
    }


def turn_detail(db: Database, turn_id: str) -> dict[str, Any] | None:
    """types.ts: TurnDetail - bitta savolning to'liq izi. Yo'q bo'lsa `None`."""
    row = db.row("SELECT * FROM turns WHERE id = ?", (turn_id,))
    if row is None:
        return None
    summary = _turn_summary(row, turn_id in reported_turns(db, [row]))
    events = [
        {"seq": e["seq"], "tMs": e["t_ms"], "durMs": e["dur_ms"], "type": e["type"],
         "name": e["name"], "payload": _json(e["payload"])}
        for e in db.rows("SELECT seq, t_ms, dur_ms, type, name, payload FROM turn_events "
                         "WHERE turn_id = ? ORDER BY seq", (turn_id,))
    ]
    sources = [
        {"idx": s["idx"], "kind": s["kind"], "ref": s["ref"], "title": s["title"],
         "page": s["page"], "score": s["score"], "snippet": s["snippet"], "status": s["status"],
         "digest": s["digest"], "citation": s["citation"]}
        for s in db.rows("SELECT idx, kind, ref, title, page, score, snippet, status, digest, "
                         "citation FROM turn_sources WHERE turn_id = ? ORDER BY idx", (turn_id,))
    ]
    calls = [_api_call(c) for c in db.rows(
        "SELECT * FROM api_calls WHERE turn_id = ? ORDER BY ts, id", (turn_id,))]
    if row["chat_id"]:
        chat_rows = db.rows(
            f"SELECT id, started_at, substr(question, 1, {QUESTION_PREVIEW}) AS question, status "
            "FROM turns WHERE chat_id = ? ORDER BY started_at, id LIMIT 500", (row["chat_id"],))
    else:
        chat_rows = [row]
    chat_turns = [{"id": c["id"], "startedAt": iso(c["started_at"]),
                   "question": (c["question"] or "")[:QUESTION_PREVIEW], "status": c["status"]}
                  for c in chat_rows]
    reports = _report_rows(db, ["(r.turn_id = ? OR (r.chat_id IS NOT NULL AND r.chat_id = ?))"],
                           [turn_id, row["chat_id"]], limit=50)
    return {
        **summary,
        "question": row["question"] or "",
        "answer": row["answer"],
        "requestId": row["request_id"],
        "locale": row["locale"],
        "endedAt": iso(row["ended_at"]),
        "httpStatus": row["http_status"],
        "errorText": row["error_text"],
        "events": events,
        "sources": sources,
        "apiCalls": calls,
        "chatTurns": chat_turns,
        "reports": reports,
    }


def _api_call(row: Mapping[str, Any]) -> dict[str, Any]:
    """types.ts: ApiCall."""
    units = _json(row["units"])
    return {
        "id": row["id"],
        "ts": iso(row["ts"]),
        "service": row["service"],
        "op": row["op"],
        "status": row["status"],
        "httpStatus": row["http_status"],
        "durationMs": int(row["duration_ms"] or 0),
        "actorId": row["actor_id"],
        "channel": row["channel"],
        "turnId": row["turn_id"],
        "units": _numbers(units),
        "error": row["error"],
    }


def _numbers(value: Any) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    return {str(k): v for k, v in value.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


# --- suhbatlar ------------------------------------------------------------------------


def list_chats(db: Database, flt: TurnFilter, *, cursor: str | None = None,
               limit: int = 50) -> dict[str, Any]:
    """Savollar `chat_id` bo'yicha guruhlangan - oxirgi faollik bo'yicha.

    Filtr SAVOLLARGA qo'llanadi (`turns`, `errors` - mos kelganlari soni),
    `reported` esa SUHBATGA: suhbatga yoki uning biror savoliga xabar
    berilgan bo'lsa. Nom (`title`) - suhbatning birinchi savoli, egasi va
    kanali - oxirgisidan (oraliqdan tashqaridagi savollar ham hisobga
    olinadi: nom oraliqqa qarab o'zgarib turmasin).
    """
    conds, params = flt.where("t", chats=True)
    conds.append("t.chat_id IS NOT NULL")
    having: list[str] = []
    having_params: list[Any] = []
    _after("MAX(t.started_at)", "t.chat_id", decode_cursor(cursor), having, having_params)
    rows = db.rows(
        "SELECT t.chat_id AS chat_id, MIN(t.started_at) AS first_at, "
        "MAX(t.started_at) AS last_at, COUNT(*) AS turns, "
        "SUM(CASE WHEN t.status = 'error' THEN 1 ELSE 0 END) AS errors "
        f"FROM turns t {_where(conds)} GROUP BY t.chat_id "
        + (f"HAVING {' AND '.join(having)} " if having else "")
        + "ORDER BY last_at DESC, chat_id DESC LIMIT ?",
        (*params, *having_params, limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    chat_ids = [r["chat_id"] for r in rows]
    first: dict[str, Mapping[str, Any]] = {}
    last: dict[str, Mapping[str, Any]] = {}
    reported: set[str] = set()
    for part in iter_chunks(chat_ids, 400):
        marks = _marks(part)
        for t in db.rows(
                "SELECT chat_id, actor_id, user_name, channel, "
                f"substr(question, 1, {TITLE_PREVIEW}) AS title FROM turns "
                f"WHERE chat_id IN ({marks}) ORDER BY started_at, id", part):
            first.setdefault(t["chat_id"], t)
            last[t["chat_id"]] = t
        reported.update(r["chat_id"] for r in db.rows(
            f"SELECT chat_id FROM reports WHERE chat_id IN ({marks}) "
            "UNION SELECT tt.chat_id FROM reports rr JOIN turns tt ON tt.id = rr.turn_id "
            f"WHERE tt.chat_id IN ({marks})", (*part, *part)))
    items = []
    for r in rows:
        head = first.get(r["chat_id"], {})
        tail = last.get(r["chat_id"], {})
        items.append({
            "chatId": r["chat_id"],
            "actorId": tail.get("actor_id"),
            "userName": tail.get("user_name"),
            "channel": tail.get("channel"),
            "firstAt": iso(r["first_at"]),
            "lastAt": iso(r["last_at"]),
            "turns": int(r["turns"] or 0),
            "errors": int(r["errors"] or 0),
            "reported": r["chat_id"] in reported,
            "title": _preview(head.get("title"), TITLE_PREVIEW) or "",
        })
    return {
        "items": items,
        "nextCursor": encode_cursor(rows[-1]["last_at"], rows[-1]["chat_id"]) if more else None,
    }


# --- xabarlar (shikoyatlar) -----------------------------------------------------------

_REPORT_COLUMNS = (
    "r.id, r.created_at, r.actor_id, r.user_name, r.user_login, r.channel, r.chat_id, "
    "r.turn_id, r.reason, r.comment, r.status, "
    # `json_valid` birinchi: buzuq nusxada `json_array_length` xato beradi va
    # butun ro'yxatni yiqitardi.
    "CASE WHEN json_valid(r.snapshot) THEN json_array_length(r.snapshot, '$.messages') "
    "END AS n_messages, "
    f"substr(tq.question, 1, {PREVIEW}) AS turn_question"
)


def _report_summary(row: Mapping[str, Any], question: str | None = None) -> dict[str, Any]:
    """types.ts: ReportSummary. `commentPreview` - izohning birinchi qatori,
    izoh bo'lmasa - xabar berilgan savol (ro'yxatda bo'sh qator qolmasin)."""
    return {
        "id": row["id"],
        "createdAt": iso(row["created_at"]),
        "actorId": row["actor_id"],
        "userName": row["user_name"],
        "channel": row["channel"],
        "chatId": row["chat_id"],
        "turnId": row["turn_id"],
        "reason": row["reason"],
        "commentPreview": _first_line(row["comment"]) or _preview(
            question or row["turn_question"], PREVIEW),
        "status": row["status"],
        "messages": int(row["n_messages"] or 0),
    }


def _snapshot_question(snapshot: Any, turn_id: str | None) -> str | None:
    """Nusxadagi savol: xabar berilgan savolniki, bo'lmasa oxirgi savol."""
    messages = snapshot.get("messages") if isinstance(snapshot, Mapping) else None
    if not isinstance(messages, list):
        return None
    asked = [m for m in messages if isinstance(m, Mapping) and m.get("role") == "user"
             and isinstance(m.get("content"), str)]
    for m in asked:
        if turn_id and m.get("turnId") == turn_id:
            return m["content"]
    return asked[-1]["content"] if asked else None


def _report_rows(db: Database, conds: list[str], params: list[Any], *,
                 limit: int) -> list[dict[str, Any]]:
    rows = db.rows(
        f"SELECT {_REPORT_COLUMNS} FROM reports r LEFT JOIN turns tq ON tq.id = r.turn_id "
        f"{_where(conds)} ORDER BY r.created_at DESC, r.id DESC LIMIT ?", (*params, limit))
    return _report_summaries(db, rows)


def _report_summaries(db: Database, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    # Izohi ham, bog'langan savoli ham yo'q (savol eskirib o'chgan) qatorlar
    # uchun savol nusxadan olinadi. Nusxa katta bo'lishi mumkin - faqat
    # shu qatorlarniki o'qiladi.
    need = [r["id"] for r in rows if not _first_line(r["comment"]) and not r["turn_question"]]
    questions: dict[str, str | None] = {}
    for part in iter_chunks(need, 200):
        for s in db.rows(f"SELECT id, turn_id, snapshot FROM reports WHERE id IN ({_marks(part)})",
                         part):
            questions[s["id"]] = _snapshot_question(_json(s["snapshot"]), s["turn_id"])
    return [_report_summary(r, questions.get(r["id"])) for r in rows]


def _report_where(*, status: str | None = None, start: float | None = None,
                  end: float | None = None, channel: str | None = None, q: str | None = None,
                  actor_id: int | None = None) -> tuple[list[str], list[Any]]:
    conds: list[str] = []
    params: list[Any] = []
    if status:
        conds.append("r.status = ?")
        params.append(status)
    if start is not None:
        conds.append("r.created_at >= ?")
        params.append(start)
    if end is not None:
        conds.append("r.created_at < ?")
        params.append(end)
    if channel:
        conds.append("r.channel = ?")
        params.append(channel)
    if actor_id is not None:
        conds.append("r.actor_id = ?")
        params.append(actor_id)
    if q and q.strip():
        text = q.strip()
        like, like_params = _match(
            ["r.comment", "r.user_name", "r.user_login", "r.admin_note"], text)
        conds.append(f"(r.id = ? OR r.chat_id = ? OR r.turn_id = ? OR {like})")
        params.extend((text, text, text, *like_params))
    return conds, params


def list_reports(db: Database, *, status: str | None = None, start: float | None = None,
                 end: float | None = None, channel: str | None = None, q: str | None = None,
                 actor_id: int | None = None, cursor: str | None = None,
                 limit: int = 50) -> dict[str, Any]:
    """Xabarlar qutisi: `{items, counts, nextCursor}`, yangisi birinchi.

    `counts` holat bo'yicha - `status` filtrisiz (qolgan filtrlar bilan):
    qutidagi yorliqlar tanlangan yorliqqa qaramay hammasining sonini
    ko'rsatadi.
    """
    base, base_params = _report_where(start=start, end=end, channel=channel, q=q,
                                      actor_id=actor_id)
    counts = {name: 0 for name in REPORT_STATUSES}
    for r in db.rows(f"SELECT r.status AS status, COUNT(*) AS n FROM reports r {_where(base)} "
                     "GROUP BY r.status", base_params):
        if r["status"] in counts:
            counts[r["status"]] = int(r["n"])
    conds, params = list(base), list(base_params)
    if status:
        conds.append("r.status = ?")
        params.append(status)
    _after("r.created_at", "r.id", decode_cursor(cursor), conds, params)
    rows = db.rows(
        f"SELECT {_REPORT_COLUMNS} FROM reports r LEFT JOIN turns tq ON tq.id = r.turn_id "
        f"{_where(conds)} ORDER BY r.created_at DESC, r.id DESC LIMIT ?", (*params, limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": _report_summaries(db, rows),
        "counts": counts,
        "nextCursor": encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None,
    }


def count_reports(db: Database, *, status: str | None = None, channel: str | None = None) -> int:
    """Xabarlar soni (masalan `new` - admin menyusidagi nishon)."""
    conds, params = _report_where(status=status, channel=channel)
    return int(db.scalar(f"SELECT COUNT(*) FROM reports r {_where(conds)}", params, default=0))


def report_detail(db: Database, report_id: str) -> dict[str, Any] | None:
    """types.ts: ReportDetail - izoh, suhbat nusxasi, admin izohi bilan."""
    row = db.row(
        f"SELECT {_REPORT_COLUMNS}, r.snapshot, r.admin_note, r.updated_at, r.updated_by "
        "FROM reports r LEFT JOIN turns tq ON tq.id = r.turn_id WHERE r.id = ?", (report_id,))
    if row is None:
        return None
    snapshot = _json(row["snapshot"])
    if not isinstance(snapshot, dict):
        # Buzuq nusxa sahifani yiqitmasin - admin hech bo'lmasa izohni ko'rsin.
        snapshot = {"source": "unknown", "messages": []}
    return {
        **_report_summary(row, _snapshot_question(snapshot, row["turn_id"])),
        "comment": row["comment"],
        "snapshot": snapshot,
        "adminNote": row["admin_note"],
        "updatedAt": iso(row["updated_at"]),
        "updatedBy": row["updated_by"],
    }


def update_report(db: Database, report_id: str, *, admin: "AuthUser", status: Any = KEEP,
                  admin_note: Any = KEEP) -> dict[str, Any] | None:
    """Holat va/yoki admin izohini o'zgartiradi; har o'zgarish auditga.

    BITTA TRANZAKSIYADA: o'qish, yangilash va audit yozuvi - ikki admin bir
    vaqtda bosganda ham audit haqiqiy "qaysi holatdan qaysiga" ni yozadi.
    Hech narsa o'zgarmasa (xuddi shu holat) audit ham yozilmaydi - jurnal
    ikki marta bosilgan tugma bilan to'lmasin.

    Audit yozuvchisi `admin_users.write_audit` - jurnal BITTA, shakli ham
    bitta (`AuditEntry`). Import funksiya ichida: `admin_users` keyinchalik
    shu modulni import qilsa ham aylanma import bo'lmasin.
    """
    from ..admin_users import write_audit

    if status is not KEEP and status not in REPORT_STATUSES:
        raise QueryError("status: noma'lum holat")
    with db.transaction() as conn:
        row = conn.execute("SELECT status, admin_note FROM reports WHERE id = ?",
                           (report_id,)).fetchone()
        if row is None:
            return None
        sets: list[str] = []
        values: list[Any] = []
        if status is not KEEP and status != row["status"]:
            sets.append("status = ?")
            values.append(status)
            write_audit(conn, admin, "report.status", "report", report_id,
                        {"from": row["status"], "to": status})
        if admin_note is not KEEP:
            note = (str(admin_note).strip()[:NOTE_CAP] or None) if admin_note is not None else None
            if note != row["admin_note"]:
                sets.append("admin_note = ?")
                values.append(note)
                # Izohning o'zi emas, uzunligi va boshi: to'liq matn
                # xabarning o'zida turadi, jurnal esa "kim, qachon" uchun.
                write_audit(conn, admin, "report.note", "report", report_id,
                            {"chars": len(note or ""), "preview": _preview(note, 120)})
        if sets:
            by = (admin.email or admin.fullName or str(admin.actorId))[:128]
            conn.execute(
                f"UPDATE reports SET {', '.join(sets)}, updated_at = ?, updated_by = ? "
                "WHERE id = ?", (*values, time.time(), by, report_id))
    return report_detail(db, report_id)


# --- umumiy ko'rinish -------------------------------------------------------------------


def _range_rows(db: Database, sql: str, params: Sequence[Any], what: str) -> list[sqlite3.Row]:
    rows = db.execute(f"{sql} LIMIT ?", (*params, ROW_CAP)).fetchall()
    if len(rows) >= ROW_CAP:
        log.warning("Admin %s: oraliqda %d dan ko'p qator - faqat eng yangilari hisoblandi",
                    what, ROW_CAP)
    return rows


def _turn_rows(db: Database, start: float, end: float, channel: str | None) -> list[sqlite3.Row]:
    """(started_at, channel, actor_id, status, ttft_ms, route, engine) - oraliqdagi savollar."""
    conds = ["started_at >= ?", "started_at < ?"]
    params: list[Any] = [start, end]
    if channel:
        conds.append("channel = ?")
        params.append(channel)
    return _range_rows(
        db, f"SELECT started_at, channel, actor_id, status, ttft_ms, route, engine FROM turns "
            f"{_where(conds)} ORDER BY started_at DESC", params, "overview")


def _kpi_values(rows: Iterable[Sequence[Any]]) -> tuple[int, int, int | None, float | None]:
    """(savollar, faol odamlar, TTFT mediana, xato ulushi).

    Xato ulushining maxraji - TUGAGAN savollar: `running` (hozir oqayotgan)
    savol hali na xato, na muvaffaqiyat.
    """
    turns = finished = errors = 0
    actors: set[int] = set()
    ttfts: list[int] = []
    for _, _, actor, status, ttft, _, _ in rows:
        turns += 1
        if actor is not None:
            actors.add(actor)
        if status != "running":
            finished += 1
        if status == "error":
            errors += 1
        if ttft is not None:
            ttfts.append(ttft)
    ttfts.sort()
    return turns, len(actors), _ms(percentile(ttfts, 0.5)), _rate(errors, finished)


def overview(db: Database, *, start: float, end: float,
             channel: str | None = None) -> dict[str, Any]:
    """types.ts: AdminOverview. Oldingi davr - xuddi shu uzunlikdagi, darhol
    oldingi oraliq (KPI farqi uchun).

    `medianTtftMs` va `latency` - BIRINCHI SO'Z vaqti (TTFT): foydalanuvchi
    "javob keldi" deb sezadigan payt shu; to'liq vaqt savol izida bor.
    `newReports` - shu oraliqda KELGAN xabarlar (holatidan qat'i nazar);
    ko'rilmaganlar soni esa `/admin/me` va `/admin/reports` (`counts.new`) da.
    """
    span = end - start
    prev_start, prev_end = start - span, start
    bucket = bucket_for(start, end)
    starts = bucket_starts(start, end, bucket)
    step = _step(bucket)
    origin = grid_origin(start, bucket)
    first_bucket = starts[0] if starts else floor_bucket(start, bucket, origin)

    rows = _turn_rows(db, start, end, channel)
    prev_rows = _turn_rows(db, prev_start, prev_end, channel)

    turns, users, median_ttft, error_rate = _kpi_values(rows)
    p_turns, p_users, p_median, p_error = _kpi_values(prev_rows)

    # Kichik chiziqlar: oraliq 14 ta teng bo'lakka.
    seg_rows: list[list[Sequence[Any]]] = [[] for _ in range(SPARK_POINTS)]
    # Grafiklar: soat/kun guruhlari.
    activity = [{"t": iso(t), **{c: 0 for c in CHANNELS}} for t in starts]
    bucket_ttft: list[list[int]] = [[] for _ in starts]
    per_channel: dict[str, dict[str, Any]] = {}
    per_route: dict[str | None, list[int]] = {}
    per_engine: dict[str, dict[str, Any]] = {}
    for row in rows:
        ts, chan, actor, status, ttft, route, engine = row
        # Dvigatel bo'yicha: savollar, xatolar, birinchi so'zgacha. NULL -
        # "default" (versiyasiz yo'l yoki yordamchiga bormagan javob).
        lane = per_engine.setdefault(engine or DEFAULT_ENGINE,
                                     {"turns": 0, "errors": 0, "ttft": []})
        lane["turns"] += 1
        if status == "error":
            lane["errors"] += 1
        if ttft is not None:
            lane["ttft"].append(ttft)
        seg_rows[_segment(ts, start, end)].append(row)
        index = int((floor_bucket(ts, bucket, origin) - first_bucket) // step)
        chan = chan if chan in CHANNELS else "api"
        if 0 <= index < len(activity):
            activity[index][chan] += 1
            if ttft is not None:
                bucket_ttft[index].append(ttft)
        stat = per_channel.setdefault(chan, {"turns": 0, "users": set(), "errors": 0})
        stat["turns"] += 1
        if actor is not None:
            stat["users"].add(actor)
        if status == "error":
            stat["errors"] += 1
        counts = per_route.setdefault(route, [0, 0])
        counts[0] += 1
        if status == "error":
            counts[1] += 1

    sparks = [_kpi_values(seg) for seg in seg_rows]
    latency = []
    for t, values in zip(starts, bucket_ttft):
        values.sort()
        latency.append({"t": iso(t), "p50": _ms(percentile(values, 0.5)),
                        "p95": _ms(percentile(values, 0.95))})

    report_conds, report_params = _report_where(start=start, end=end, channel=channel)
    created = [r[0] for r in db.execute(
        f"SELECT r.created_at FROM reports r {_where(report_conds)}", report_params)]
    prev_conds, prev_params = _report_where(start=prev_start, end=prev_end, channel=channel)
    prev_created = int(db.scalar(f"SELECT COUNT(*) FROM reports r {_where(prev_conds)}",
                                 prev_params, default=0))
    report_spark = [0] * SPARK_POINTS
    for ts in created:
        report_spark[_segment(ts, start, end)] += 1

    top_docs, tools = _source_stats(db, start, end, channel)
    slow_conds = ["t.started_at >= ?", "t.started_at < ?", "t.total_ms IS NOT NULL"]
    slow_params: list[Any] = [start, end]
    if channel:
        slow_conds.append("t.channel = ?")
        slow_params.append(channel)
    slow = db.rows(f"SELECT {_SUMMARY_COLUMNS} FROM turns t {_where(slow_conds)} "
                   "ORDER BY t.total_ms DESC, t.id LIMIT 5", slow_params)

    return {
        "range": {"from": iso(start), "to": iso(end), "prevFrom": iso(prev_start),
                  "prevTo": iso(prev_end), "bucket": bucket},
        "kpis": {
            "turns": {"value": turns, "prev": p_turns, "spark": [s[0] for s in sparks]},
            "activeUsers": {"value": users, "prev": p_users, "spark": [s[1] for s in sparks]},
            "medianTtftMs": {"value": median_ttft, "prev": p_median,
                             "spark": [s[2] for s in sparks]},
            "errorRate": {"value": error_rate, "prev": p_error, "spark": [s[3] for s in sparks]},
            "newReports": {"value": len(created), "prev": prev_created, "spark": report_spark},
        },
        "activity": activity,
        "channels": [
            {"channel": name, "turns": s["turns"], "users": len(s["users"]), "errors": s["errors"]}
            for name, s in sorted(per_channel.items(), key=lambda kv: (-kv[1]["turns"], kv[0]))
        ],
        "routes": [
            {"route": route, "turns": n, "errors": e}
            for route, (n, e) in sorted(per_route.items(),
                                        key=lambda kv: (-kv[1][0], kv[0] or "~"))
        ],
        # v1 va v2 ni yonma-yon solishtirish (xat, 2-bo'lim: "compare").
        "engines": [
            {"engine": name, "turns": s["turns"], "errors": s["errors"],
             "medianTtftMs": _ms(percentile(sorted(s["ttft"]), 0.5))}
            for name, s in sorted(per_engine.items(), key=lambda kv: (-kv[1]["turns"], kv[0]))
        ],
        "latency": latency,
        "topDocs": top_docs,
        "tools": tools,
        "recentReports": _report_rows(db, report_conds, report_params, limit=5),
        "slowTurns": turn_summaries(db, slow),
    }


def engine_stats(db: Database, *, start: float, end: float) -> list[dict[str, Any]]:
    """types.ts: EngineUsage - dvigatellar sahifasi uchun (`/admin/engines`).

    Umumiy ko'rinishdagi `engines` bilan AYNI hisob (NULL - `default`,
    xato - `status = 'error'`, TTFT mediana), ustiga `users` - nechta odam
    shu dvigatelda so'radi. Versiyani "hammaga ochish" qarori aynan shu
    savolga tayanadi: sinovchilar yetarlimi va xatolari ko'p emasmi.
    """
    rows = _range_rows(
        db, "SELECT engine, status, ttft_ms, actor_id FROM turns "
            "WHERE started_at >= ? AND started_at < ? ORDER BY started_at DESC",
        (start, end), "engines")
    lanes: dict[str, dict[str, Any]] = {}
    for engine, status, ttft, actor in rows:
        lane = lanes.setdefault(engine or DEFAULT_ENGINE,
                                {"turns": 0, "errors": 0, "ttft": [], "users": set()})
        lane["turns"] += 1
        if status == "error":
            lane["errors"] += 1
        if ttft is not None:
            lane["ttft"].append(ttft)
        if actor is not None:
            lane["users"].add(actor)
    return [
        {"engine": name, "turns": s["turns"], "errors": s["errors"],
         "medianTtftMs": _ms(percentile(sorted(s["ttft"]), 0.5)), "users": len(s["users"])}
        for name, s in sorted(lanes.items(), key=lambda kv: (-kv[1]["turns"], kv[0]))
    ]


#: Platforma chaqiruvi xatomi: holat bor va u "yaxshi" emas (`ok`, `200`, ...).
_TOOL_ERROR = (
    "CASE WHEN s.status IS NULL OR lower(s.status) IN ('ok', 'success', 'done') "
    "OR s.status GLOB '2[0-9][0-9]' THEN 0 ELSE 1 END"
)


def _source_stats(db: Database, start: float, end: float,
                  channel: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Ko'p iqtibos qilingan hujjatlar va platforma chaqiruvlari.

    Hujjatning "iqtibosi" - uni manba sifatida olgan SAVOLLAR soni: bitta
    javobda bir hujjatdan uch parcha kelsa ham bu bitta iqtibos.
    """
    conds = ["t.started_at >= ?", "t.started_at < ?", "s.ref IS NOT NULL"]
    params: list[Any] = [start, end]
    if channel:
        conds.append("t.channel = ?")
        params.append(channel)
    kinds = _marks(TOOL_KINDS)
    docs = db.rows(
        "SELECT s.ref AS ref, MAX(s.title) AS title, COUNT(DISTINCT s.turn_id) AS citations "
        "FROM turns t JOIN turn_sources s ON s.turn_id = t.id "
        f"{_where(conds)} AND COALESCE(s.kind, 'doc') NOT IN ({kinds}) "
        "GROUP BY s.ref ORDER BY citations DESC, s.ref LIMIT ?",
        (*params, *TOOL_KINDS, TOP_DOCS))
    tools = db.rows(
        f"SELECT s.ref AS ref, COUNT(*) AS calls, SUM({_TOOL_ERROR}) AS errors "
        "FROM turns t JOIN turn_sources s ON s.turn_id = t.id "
        f"{_where(conds)} AND s.kind IN ({kinds}) "
        "GROUP BY s.ref ORDER BY calls DESC, s.ref LIMIT ?",
        (*params, *TOOL_KINDS, TOP_TOOLS))
    return (
        [{"ref": d["ref"], "title": d["title"], "citations": int(d["citations"])} for d in docs],
        [{"ref": t["ref"], "calls": int(t["calls"]), "errors": int(t["errors"] or 0)}
         for t in tools],
    )


# --- foydalanish (tashqi xizmatlar) --------------------------------------------------------


def usage(db: Database, *, start: float, end: float, channel: str | None = None) -> dict[str, Any]:
    """types.ts: AdminUsage - har tashqi xizmat: so'rovlar, xatolar, p50/p95,
    birliklar (audio soniya, belgi, bayt, kadr), vaqt bo'yicha va kanal
    bo'yicha taqsimot, eng sekin amallar."""
    bucket = bucket_for(start, end)
    starts = bucket_starts(start, end, bucket)
    step = _step(bucket)
    origin = grid_origin(start, bucket)
    first_bucket = starts[0] if starts else floor_bucket(start, bucket, origin)
    conds = ["ts >= ?", "ts < ?"]
    params: list[Any] = [start, end]
    if channel:
        conds.append("channel = ?")
        params.append(channel)
    rows = _range_rows(
        db, f"SELECT ts, service, op, status, duration_ms, channel, units FROM api_calls "
            f"{_where(conds)} ORDER BY ts DESC", params, "usage")

    services: dict[str, dict[str, Any]] = {
        name: _service_acc() for name in KNOWN_SERVICES}
    ops: dict[tuple[str, str], dict[str, Any]] = {}
    series: list[dict[str, int]] = [{} for _ in starts]
    by_channel: dict[str, dict[str, int]] = {}
    for ts, service, op, status, duration, chan, units in rows:
        acc = services.setdefault(service, _service_acc())
        failed = status != "ok"
        acc["requests"] += 1
        acc["errors"] += failed
        acc["durations"].append(duration or 0)
        acc["spark"][_segment(ts, start, end)] += 1
        if units:
            for key, value in _numbers(_json(units)).items():
                acc["units"][key] = acc["units"].get(key, 0) + value
        op_acc = ops.setdefault((service, op), {"requests": 0, "errors": 0, "durations": []})
        op_acc["requests"] += 1
        op_acc["errors"] += failed
        op_acc["durations"].append(duration or 0)
        index = int((floor_bucket(ts, bucket, origin) - first_bucket) // step)
        if 0 <= index < len(series):
            series[index][service] = series[index].get(service, 0) + 1
        lane = by_channel.setdefault(chan if chan else SYSTEM_CHANNEL, {})
        lane[service] = lane.get(service, 0) + 1

    names = list(KNOWN_SERVICES) + sorted(set(services) - set(KNOWN_SERVICES))
    out_services = []
    for name in names:
        acc = services[name]
        durations = sorted(acc["durations"])
        out_services.append({
            "service": name,
            "requests": acc["requests"],
            "errors": acc["errors"],
            "errorRate": _rate(acc["errors"], acc["requests"]),
            "p50Ms": _ms(percentile(durations, 0.5)),
            "p95Ms": _ms(percentile(durations, 0.95)),
            "units": {k: (round(v, 3) if isinstance(v, float) else v)
                      for k, v in sorted(acc["units"].items())},
            "spark": acc["spark"],
        })
    channel_order = list(CHANNELS) + [SYSTEM_CHANNEL]
    lanes = sorted(by_channel, key=lambda c: (channel_order.index(c)
                                              if c in channel_order else len(channel_order), c))
    out_ops = []
    for (service, op), acc in ops.items():
        durations = sorted(acc["durations"])
        out_ops.append({"service": service, "op": op, "requests": acc["requests"],
                        "errors": acc["errors"], "p95Ms": _ms(percentile(durations, 0.95))})
    out_ops.sort(key=lambda o: (-(o["p95Ms"] or 0), -o["errors"], o["service"], o["op"]))
    return {
        "services": out_services,
        "series": {
            "bucket": bucket,
            "points": [{"t": iso(t), **{name: point.get(name, 0) for name in names}}
                       for t, point in zip(starts, series)],
        },
        "byChannel": [{"channel": lane, **{name: by_channel[lane].get(name, 0) for name in names}}
                      for lane in lanes],
        "ops": out_ops,
    }


def _service_acc() -> dict[str, Any]:
    return {"requests": 0, "errors": 0, "durations": [], "units": {},
            "spark": [0] * SPARK_POINTS}


# --- tizim ---------------------------------------------------------------------------------


def storage(db: Database, *, dropped: int = 0) -> dict[str, Any]:
    """types.ts: StorageStats - fayl hajmi va jadvallardagi qatorlar."""
    def count(table: str) -> int:
        return int(db.scalar(f"SELECT COUNT(*) FROM {table}", default=0))

    return {
        "dbBytes": db.size_bytes(),
        "turns": count("turns"),
        "events": count("turn_events"),
        "apiCalls": count("api_calls"),
        "reports": count("reports"),
        "dropped": int(dropped),
    }


# --- qidiruv -------------------------------------------------------------------------------


def search(db: Database, q: str, *, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Buyruqlar oynasi (⌘K) uchun: savollar va xabarlar. Foydalanuvchilar
    ro'yxati katalogdan keladi (router), bu yerda faqat analitika."""
    return {
        "turns": list_turns(db, TurnFilter(q=q), limit=limit)["items"],
        "reports": list_reports(db, q=q, limit=limit)["items"],
    }

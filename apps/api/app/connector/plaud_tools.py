"""Plaud (yig'ilishlar) vositalari - Barno konnektorining 1-bosqichi, FAQAT O'QISH.

Har vosita `services/meetings` ni odamning O'Z `AuthUser` i bilan chaqiradi: boshqa xodimning
yozuvi `service._owned` da "yo'q" (404) bo'lib qoladi - bu yerda alohida egalik tekshiruvi
yo'q va bo'lmasligi kerak (qoida bitta joyda).

NEGA IXCHAM. Javob odamning Claude / ChatGPT kontekstiga ketadi: id, nom, sana, davomiylik,
holat, spiker ismlari - yetarli. Uzun matn (transkript) bo'laklab (`next_cursor`), xulosa va
bayonnoma - tayyor markdown eksportidan (`export_summary`, `minutes.export_file`), qayta
yozilmaydi.

NEGA `MeetingProblem` -> `ToolError`. "Topilmadi", "hali tayyor emas" - kutilgan holat: model
sababni `isError: true` natijada ko'rib, o'zi tuzatadi. 500 bo'lsa mijoz konnektorni "buzuq"
deb belgilaydi.

`Tool`, `Result`, `ToolError` - umumiy turlar; ikkinchi modul (CRM) kelganda `connector/tools.py`
ga ko'chadi (hozir bitta modul - alohida fayl ortiqcha).
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Any, Callable, get_args

from ..core import config as _config
from ..schemas.auth import AuthUser
from ..schemas.meetings import MeetingOrigin
from ..services.meetings import export, minutes, service
from ..services.meetings.errors import MeetingProblem
from ..services.meetings.prompts import hms
from . import core

SCOPE = "plaud.read"

#: Chegaralar (belgi). Umumiy qopqoq (`mcp.MAX_TEXT`, ~100k) - oxirgi to'r; vositalar o'zi kichikroq beradi.
SUMMARY_CHARS = 80_000
MINUTES_CHARS = 80_000
FETCH_CHARS = 60_000
TRANSCRIPT_DEFAULT = 20_000
TRANSCRIPT_MAX = 50_000
SEARCH_LIMIT = 20
#: `search` so'zlarga bo'lib qidirganda ko'pi bilan shuncha so'z (har biri - bitta ombor so'rovi).
SEARCH_WORDS = 6

ORIGINS: tuple[str, ...] = get_args(MeetingOrigin)
MINUTES_LANGS = ("uz-latn", "uz-cyrl", "ru", "en")
_TOKEN = re.compile(r"\[(S\d{1,2})\]")
_DIGITS = re.compile(r"\d{1,12}")
#: Transkript kursori: segment id, ixtiyoriy - shu segment matnidagi belgi (`"123"`, `"123:4000"`).
_CURSOR = re.compile(r"(\d{1,12})(?::(\d{1,9}))?")


# --- umumiy turlar ------------------------------------------------------------------------------


class ToolError(Exception):
    """Kutilgan xato -> `isError: true` natija. `status` - jurnal uchun: `error` yoki `denied`."""

    def __init__(self, message: str, status: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Result:
    """`structured` - `structuredContent`; `text` - model o'qiydigan matn (`None` - `structured` JSON)."""

    structured: dict[str, Any]
    text: str | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    handler: Callable[[AuthUser, dict[str, Any]], Result]
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    scope: str = SCOPE

    def listing(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "object", "properties": self.properties,
                                  "additionalProperties": False}
        if self.required:
            schema["required"] = list(self.required)
        return {"name": self.name, "title": self.title, "description": self.description,
                "inputSchema": schema,
                "annotations": {"title": self.title, "readOnlyHint": True, "destructiveHint": False,
                                "idempotentHint": True, "openWorldHint": False}}


# --- argumentlar --------------------------------------------------------------------------------


def _text(args: dict[str, Any], key: str, *, required: bool = False, limit: int = 200) -> str:
    value = args.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    value = value.strip()
    if required and not value:
        raise ToolError(f"{key} is required")
    if len(value) > limit:
        raise ToolError(f"{key} is longer than {limit} characters")
    return value


def _int(args: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = args.get(key)
    if value is None:
        return default
    # Ba'zi mijozlar sonni satr qilib yuboradi ("20") - qabul qilamiz; `True` esa son emas.
    if isinstance(value, str) and _DIGITS.fullmatch(value.strip()):
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    if not low <= value <= high:
        raise ToolError(f"{key} must be between {low} and {high}")
    return value


def _choice(args: dict[str, Any], key: str, choices: tuple[str, ...], default: str) -> str:
    value = _text(args, key, limit=32) or default
    if value and value not in choices:
        raise ToolError(f"{key} must be one of: {', '.join(choices)}")
    return value


# --- ko'rinishlar -------------------------------------------------------------------------------


def meeting_url(meeting_id: str) -> str:
    """Yig'ilish havolasi (ChatGPT iqtibos uchun kutadi). Mobil ilova yo'li (`/meeting/<id>`) bilan
    bir xil; veb ilovada yig'ilish sahifasi hali yo'q - u yerda bosh sahifaga ochiladi."""
    return f"{core.public_base()}/meeting/{meeting_id}"


def _speaker_rows(meeting_id: str) -> dict[str, dict[str, Any]]:
    """Xom spiker qatorlari (`merged_into`, `person_id` bilan) - `export.speaker_name` shuni kutadi."""
    return {sp["id"]: sp for sp in service.runtime().store.speakers(meeting_id)}


def _meeting_lang(user: AuthUser, meeting_id: str) -> str:
    """Spiker yorlig'i tili (`_label`) - vazifalar ro'yxatida yig'ilish kartasi yo'q."""
    m = service.runtime().store.meeting(user.actorId, meeting_id)
    return (m or {}).get("language") or "uz"


def _from_views(views: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`speaker_view` (camelCase) -> `export.speaker_name` kutadigan shakl."""
    return {sp["id"]: {"name": sp.get("name"), "merged_into": sp.get("mergedInto"),
                       "person_id": sp.get("personId")} for sp in views}


def _label(speaker: str | None, rows: dict[str, dict[str, Any]], lang: str | None) -> str | None:
    """Spiker ismi; ismsizga yig'ilish tilida "2-ishtirokchi" / "Noma'lum #3" - xulosa eksportidagi bilan
    AYNAN bir xil (`export.speaker_name`), model bir odamni ikki nom bilan ko'rmasin."""
    return export.speaker_name(speaker, rows, lang or "uz") if speaker else None


def _people(rows: dict[str, dict[str, Any]], lang: str | None,
            talk: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Birlashtirilmagan spikerlar: id va ism."""
    out = []
    for sid, sp in rows.items():
        if sp.get("merged_into"):
            continue
        item: dict[str, Any] = {"id": sid, "name": _label(sid, rows, lang)}
        if talk is not None:
            item["talk_sec"] = talk.get(sid)
        out.append(item)
    return out


def _render(text: Any, rows: dict[str, dict[str, Any]], lang: str | None) -> str | None:
    """Xulosa matnidagi `[S1]` belgilari -> ism (modelga `S1` hech narsa demaydi)."""
    if not text:
        return None
    return _TOKEN.sub(lambda m: _label(m.group(1), rows, lang) or "?", str(text))


def _card(c: dict[str, Any]) -> dict[str, Any]:
    overview = _render(c.get("overview"), _speaker_rows(c["id"]), c.get("language"))
    return {"id": c["id"], "title": c.get("title") or "", "recorded_at": c.get("recordedAt"),
            "duration_sec": c.get("durationSec"), "status": c["status"],
            "summary_status": c.get("summaryStatus"), "open_action_items": c.get("openActionItems"),
            "origin": c.get("origin"), "overview": overview, "url": meeting_url(c["id"])}


def _title(title: str, recorded_at: str | None) -> str:
    return title or f"Meeting {(recorded_at or '')[:10]}".strip()


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n\n[...truncated]", True


# --- vositalar ----------------------------------------------------------------------------------


def search_meetings(user: AuthUser, args: dict[str, Any]) -> Result:
    query = _text(args, "query")
    limit = _int(args, "limit", 20, 1, 50)
    offset = _int(args, "offset", 0, 0, 100_000)
    origin = _choice(args, "origin", ORIGINS, "")
    data = service.list_meetings(user, limit=limit, offset=offset, q=query, status="", origin=origin)
    items = [_card(c) for c in data["items"]]
    end = offset + len(items)
    return Result({"meetings": items, "total": data["total"], "offset": offset, "limit": limit,
                   "next_offset": end if end < data["total"] else None})


def _summaries(user: AuthUser, meeting_id: str) -> list[dict[str, Any]]:
    return service.summaries(user, meeting_id)["items"]


def _summary_brief(s: dict[str, Any]) -> dict[str, Any]:
    return {"id": s["id"], "template": s["template"], "language": s["language"], "status": s["status"],
            "primary": s["primary"], "created_at": s["createdAt"]}


def get_meeting(user: AuthUser, args: dict[str, Any]) -> Result:
    mid = _text(args, "meeting_id", required=True, limit=64)
    m = service.detail(user, mid)
    rows = _from_views(m["speakers"])
    talk = {sp["id"]: sp.get("talkSec") for sp in m["speakers"]}
    error = m.get("error")
    return Result({
        "id": m["id"], "title": m["title"], "status": m["status"], "recorded_at": m["recordedAt"],
        "duration_sec": m["durationSec"], "language": m["language"],
        "speakers": _people(rows, m["language"], talk),
        "transcript": {"available": m["transcript"]["available"],
                       "segment_count": m["transcript"]["segmentCount"]},
        "summary_status": m["summaryStatus"], "primary_summary_id": m["primarySummaryId"],
        "summaries": [_summary_brief(s) for s in _summaries(user, mid)],
        "open_action_items": m["openActionItems"],
        "error": error["message"] if error else None, "url": meeting_url(m["id"]),
    })


def _pick_summary(cards: list[dict[str, Any]], summary_id: str) -> dict[str, Any]:
    """Tanlangani yoki asosiy (tayyor bo'lsa), aks holda eng yangi tayyor xulosa."""
    if summary_id:
        found = next((s for s in cards if s["id"] == summary_id), None)
        if found is None:
            raise ToolError("Summary not found for this meeting")
        if found["status"] != "ready":
            raise ToolError(f"This summary is not ready (status: {found['status']})")
        return found
    ready = [s for s in cards if s["status"] == "ready"]
    if not ready:
        raise ToolError("This meeting has no ready summary yet")
    return next((s for s in ready if s["primary"]), ready[-1])


def _summary_markdown(user: AuthUser, mid: str,
                      summary_id: str = "") -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    cards = _summaries(user, mid)
    chosen = _pick_summary(cards, summary_id)
    text, _, _ = service.export_summary(user, mid, chosen["id"], "md")
    return chosen, text, cards


def get_summary(user: AuthUser, args: dict[str, Any]) -> Result:
    mid = _text(args, "meeting_id", required=True, limit=64)
    chosen, markdown, cards = _summary_markdown(user, mid, _text(args, "summary_id", limit=64))
    body, cut = _clip(markdown, SUMMARY_CHARS)
    return Result({"meeting_id": mid, "summary_id": chosen["id"], "template": chosen["template"],
                   "language": chosen["language"], "created_at": chosen["createdAt"],
                   "stale": chosen["stale"], "truncated": cut,
                   "other_summaries": [_summary_brief(s) for s in cards if s["id"] != chosen["id"]]},
                  body)


def _lines(segments: list[dict[str, Any]], rows: dict[str, dict[str, Any]], lang: str | None, start: int,
           budget: int, offset: int = 0) -> tuple[list[str], str | None]:
    """`start` segmentdan (uning matnidagi `offset` belgidan) boshlab `budget` belgigacha qatorlar.

    Kursor: `"<segment>"` yoki `"<segment>:<belgi>"`. Byudjetga sig'maydigan UZUN segment bo'lib
    beriladi va kursor uning ICHIGA ko'rsatadi - matn hech qachon jim tushib qolmaydi: matn
    qolgan bo'lsa kursor bor, yo'q bo'lsa `None` (`fetch` ham shunga tayanadi)."""
    out: list[str] = []
    used = 0
    for seg in segments:
        if seg["id"] < start:
            continue
        skip = offset if seg["id"] == start else 0
        text = (seg.get("text") or "")[skip:]
        who = _label(seg.get("speaker"), rows, lang)
        prefix = f"[{hms(seg['start'])}] {who}: " if who else f"[{hms(seg['start'])}] "
        if skip:
            prefix += "…"                       # oldingi sahifadagi gapning davomi
        sep = 1 if out else 0
        room = budget - used - sep
        if len(prefix) + len(text) <= room:
            out.append(prefix + text)
            used += sep + len(prefix) + len(text)
            continue
        take = room - len(prefix)
        if out and take < 200:
            # Qolgan joy juda kam - segment keyingi sahifadan (shu joyidan) boshlanadi.
            return out, f"{seg['id']}:{skip}" if skip else str(seg["id"])
        take = max(take, 1)
        out.append(prefix + text[:take])
        return out, f"{seg['id']}:{skip + take}"
    return out, None


def get_transcript(user: AuthUser, args: dict[str, Any]) -> Result:
    mid = _text(args, "meeting_id", required=True, limit=64)
    cursor = _text(args, "cursor", limit=24)
    found = _CURSOR.fullmatch(cursor) if cursor else None
    if cursor and found is None:
        raise ToolError("cursor is not valid; use next_cursor from the previous page")
    budget = _int(args, "max_chars", TRANSCRIPT_DEFAULT, 1000, TRANSCRIPT_MAX)
    data = service.transcript(user, mid)
    rows = _from_views(data["speakers"])
    start, offset = (int(found.group(1)), int(found.group(2) or 0)) if found else (0, 0)
    lines, nxt = _lines(data["segments"], rows, data["language"], start, budget, offset)
    text = "\n".join(lines)
    if nxt:
        text += f'\n\n[Transcript continues; next_cursor: "{nxt}"]'
    return Result({"meeting_id": mid, "transcript_rev": data["transcriptRev"], "language": data["language"],
                   "speakers": _people(rows, data["language"]), "segment_count": len(data["segments"]),
                   "returned_lines": len(lines), "next_cursor": nxt}, text)


def _item(a: dict[str, Any], rows: dict[str, dict[str, Any]], lang: str) -> dict[str, Any]:
    owner = a["owner"]
    out = {"id": a["id"], "meeting_id": a["meetingId"], "task": a["task"],
           "owner": owner.get("name") or _label(owner.get("speaker"), rows, lang),
           "due_date": a["due"].get("date"), "due_time": a["due"].get("time"), "due_text": a["due"].get("raw"),
           "priority": a.get("priority"), "status": a["status"],
           "needs_confirmation": a.get("needsConfirmation")}
    if "meetingTitle" in a:
        out.update(meeting_title=a["meetingTitle"], meeting_recorded_at=a.get("recordedAt"))
    return out


def list_action_items(user: AuthUser, args: dict[str, Any]) -> Result:
    mid = _text(args, "meeting_id", limit=64)
    status = _choice(args, "status", ("open", "done", "all"), "open")
    limit = _int(args, "limit", 100, 1, 200)
    if mid:
        items = service.action_items(user, mid)["items"]
        items = [a for a in items if status == "all" or a["status"] == status][:limit]
    else:
        items = service.my_action_items(user, status, limit)["items"]
    known: dict[str, tuple[dict[str, dict[str, Any]], str]] = {}
    out = []
    for a in items:
        if a["meetingId"] not in known:
            known[a["meetingId"]] = (_speaker_rows(a["meetingId"]), _meeting_lang(user, a["meetingId"]))
        out.append(_item(a, *known[a["meetingId"]]))
    return Result({"meeting_id": mid or None, "status": status, "count": len(out), "action_items": out})


def _pick_minutes(views: list[dict[str, Any]], lang: str) -> tuple[dict[str, Any], list[str]]:
    """Joriy hujjat (`rows.newest_ready` qoidasi ko'rinishlarda): tayyor, iloji bo'lsa eskirmagan, zanjir
    uchi (boshqa tayyor versiyaning ota-versiyasi emas), eng keyin tayyor bo'lgani."""
    ready = [v for v in views if v["status"] == "ready"]
    langs = sorted({v["language"] for v in ready})
    ready = [v for v in ready if not lang or v["language"] == lang]
    if not ready:
        raise ToolError("This meeting has no minutes document" + (f" in {lang}" if lang else ""))
    fresh = [v for v in ready if not v["stale"]] or ready
    parents = {v["parentId"] for v in fresh if v.get("parentId")}
    tips = [v for v in fresh if v["id"] not in parents] or fresh
    best = max(enumerate(tips), key=lambda iv: (iv[1].get("finishedAt") or iv[1].get("createdAt") or "", iv[0]))
    return best[1], langs


def get_minutes(user: AuthUser, args: dict[str, Any]) -> Result:
    mid = _text(args, "meeting_id", required=True, limit=64)
    lang = _choice(args, "language", MINUTES_LANGS, "")
    chosen, langs = _pick_minutes(minutes.listing(user, mid)["items"], lang)
    data, _, _ = minutes.export_file(user, mid, chosen["id"], "md")
    body, cut = _clip(data.decode("utf-8", "replace"), MINUTES_CHARS)
    return Result({"meeting_id": mid, "minutes_id": chosen["id"], "language": chosen["language"],
                   "version": chosen["version"], "finished_at": chosen["finishedAt"], "stale": chosen["stale"],
                   "item_count": chosen["itemCount"], "languages_available": langs, "truncated": cut}, body)


def search(user: AuthUser, args: dict[str, Any]) -> Result:
    """ChatGPT (connectors, deep research) kutadigan shakl. Ombor qidiruvi - nom va sharhdagi QISM satr:
    to'liq ibora topilmasa, so'zlarga bo'lib qidiriladi va ko'p so'z mos kelgani oldinga chiqadi."""
    query = _text(args, "query", limit=200)

    def find(q: str) -> list[dict[str, Any]]:
        return service.list_meetings(user, limit=SEARCH_LIMIT, offset=0, q=q, status="")["items"]

    # Ball: to'liq ibora - 100, har mos so'z - 1; teng bo'lsa yangisi oldinda.
    hits: dict[str, list[Any]] = {c["id"]: [100, c] for c in find(query)}
    words = sorted({w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3}, key=len, reverse=True)
    if len(hits) < SEARCH_LIMIT and len(words) > 1:
        for word in words[:SEARCH_WORDS]:
            for c in find(word):
                hits.setdefault(c["id"], [0, c])[0] += 1
    ordered = sorted(hits.values(), key=lambda e: (e[0], e[1].get("recordedAt") or ""), reverse=True)
    results = [{"id": c["id"], "title": _title(c.get("title") or "", c.get("recordedAt")),
                "url": meeting_url(c["id"])} for _, c in ordered[:SEARCH_LIMIT]]
    return Result({"results": results})


def fetch(user: AuthUser, args: dict[str, Any]) -> Result:
    """Bitta yig'ilish - hujjat sifatida: sarlavha, xulosa (bo'lsa) va transkript (`FETCH_CHARS` gacha)."""
    mid = _text(args, "id", required=True, limit=64)
    m = service.detail(user, mid)
    title = _title(m["title"], m["recordedAt"])
    parts = [f"# {title}", f"Recorded: {m['recordedAt'] or '-'}; duration: {hms(m['durationSec'] or 0)}; "
                            f"status: {m['status']}"]
    summary_id = None
    try:
        chosen, markdown, _ = _summary_markdown(user, mid)
        summary_id = chosen["id"]
        parts.append("## Summary\n\n" + markdown.strip())
    except (ToolError, MeetingProblem):
        pass                                    # xulosa yo'q - transkript yetadi
    cut = False
    try:
        data = service.transcript(user, mid)
    except MeetingProblem:
        data = None                             # transkript hali tayyor emas - bori qaytadi
    if data is not None:
        budget = max(1000, FETCH_CHARS - sum(len(p) for p in parts))
        lines, nxt = _lines(data["segments"], _from_views(data["speakers"]), data["language"], 0, budget)
        parts.append("## Transcript\n\n" + "\n".join(lines))
        cut = nxt is not None
    text, clipped = _clip("\n\n".join(parts), FETCH_CHARS)
    rows = _from_views(m["speakers"])
    return Result({"id": m["id"], "title": title, "text": text, "url": meeting_url(m["id"]),
                   "metadata": {"recorded_at": m["recordedAt"], "duration_sec": m["durationSec"],
                                "status": m["status"], "language": m["language"],
                                "speakers": [p["name"] for p in _people(rows, m["language"])],
                                "open_action_items": m["openActionItems"], "summary_id": summary_id,
                                "transcript_truncated": cut or clipped}})


# --- ro'yxat ------------------------------------------------------------------------------------


def _guard(fn: Callable[[AuthUser, dict[str, Any]], Result]) -> Callable[[AuthUser, dict[str, Any]], Result]:
    """Bo'lim eshigi (REST dagi `meetings_access` bilan bir xil, JONLI) va xatolarni natijaga o'girish."""

    def run(user: AuthUser, args: dict[str, Any]) -> Result:
        if not _config.meetings_enabled_now():
            raise ToolError("Meetings are turned off in Barno right now", status="denied")
        try:
            return fn(user, args)
        except MeetingProblem as exc:
            raise ToolError(f"{exc.detail} ({exc.code})") from None

    return run


_MEETING_ID = {"type": "string", "description": "Meeting id (32 hex characters) from search_meetings or search.",
               "maxLength": 64}

TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("search_meetings", "Search meetings",
         "Lists the signed-in person's own meetings, newest first. An optional query matches words in the "
         "meeting title or overview. Each result has id, title, recording date, duration, processing status, "
         "summary status and the number of open action items.",
         _guard(search_meetings),
         {"query": {"type": "string", "maxLength": 200,
                    "description": "Text to look for in titles and overviews. Empty lists all meetings."},
          "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
          "offset": {"type": "integer", "minimum": 0, "default": 0},
          "origin": {"type": "string", "enum": list(ORIGINS),
                     "description": "Where the recording came from (recording = Barno recorder app)."}}),
    Tool("get_meeting", "Get meeting",
         "Details of one meeting: title, date, duration, status, speakers with talk time, transcript "
         "availability, summaries and the number of open action items.",
         _guard(get_meeting), {"meeting_id": _MEETING_ID}, ("meeting_id",)),
    Tool("get_summary", "Get meeting summary",
         "The meeting summary as Markdown: overview, topics, decisions and action items. By default the "
         "primary ready summary; summary_id selects another one listed by get_meeting.",
         _guard(get_summary),
         {"meeting_id": _MEETING_ID,
          "summary_id": {"type": "string", "maxLength": 64, "description": "Optional summary id."}},
         ("meeting_id",)),
    Tool("get_transcript", "Get meeting transcript",
         "The meeting transcript as lines of '[hh:mm:ss] Speaker: text'. Long transcripts come in pages; "
         "next_cursor is set when more lines follow.",
         _guard(get_transcript),
         {"meeting_id": _MEETING_ID,
          "cursor": {"type": "string", "maxLength": 24, "description": "next_cursor from the previous page."},
          "max_chars": {"type": "integer", "minimum": 1000, "maximum": TRANSCRIPT_MAX,
                        "default": TRANSCRIPT_DEFAULT}},
         ("meeting_id",)),
    Tool("list_action_items", "List action items",
         "Action items with task, owner, due date, priority and status - for one meeting, or across all of "
         "the signed-in person's meetings when meeting_id is omitted.",
         _guard(list_action_items),
         {"meeting_id": {**_MEETING_ID, "description": "Optional meeting id; omit for all meetings."},
          "status": {"type": "string", "enum": ["open", "done", "all"], "default": "open"},
          "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100}}),
    Tool("get_minutes", "Get meeting minutes",
         "The latest formal minutes document of a meeting as Markdown (agenda, discussion, numbered "
         "decisions), if one was prepared in Barno.",
         _guard(get_minutes),
         {"meeting_id": _MEETING_ID,
          "language": {"type": "string", "enum": list(MINUTES_LANGS),
                       "description": "Optional document language; by default the newest document."}},
         ("meeting_id",)),
    Tool("search", "Search",
         "Searches the signed-in person's meetings by title and overview. Returns JSON "
         "{\"results\": [{\"id\", \"title\", \"url\"}]}; ids work with fetch.",
         _guard(search),
         {"query": {"type": "string", "maxLength": 200, "description": "Search text."}}, ("query",)),
    Tool("fetch", "Fetch meeting",
         "One meeting as a document: JSON {\"id\", \"title\", \"text\", \"url\", \"metadata\"}, where text "
         "holds the summary and the transcript.",
         _guard(fetch),
         {"id": {"type": "string", "maxLength": 64, "description": "Meeting id from search."}}, ("id",)),
)}

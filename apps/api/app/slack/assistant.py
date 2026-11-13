"""Slack'dagi Barno AI yordamchisi - veb chatdagi AYNI assistent (ega so'rovi 2026-11-13): HR hujjatlari va qoidalari,
HRM (ta'til, xodimlar ...) va CRM (mijozlar, vazifalar) ma'lumotlari, CRM dagi o'zgarish takliflari.

QAYERDA (ega qarori 2026-11-13, "thread qoidasi"): shaxsiy chatda thread'dan TASHQARIDA yozilgan HAR xabar shu yerga
(`__init__._on_message` -> `on_text`), yordamchi javobining thread'idagi xabar ham (`meeting.question` -> `on_thread`).
Yozuv (Plaud) va bayonnoma savollari - o'sha yozuv yoki fayl xabarining thread'ida (`meeting.question`); audio - yozuv
(`meeting.acknowledge`). Kanal va guruhlarda yordamchi yo'q: javobda shaxsiy HR ma'lumoti bo'ladi (Telegram'dagi qoida).

OQIM (Telegram botdagi kabi, `bot/runner.py`): "⏳ Javob tayyorlanmoqda…" -> `chat.open_stream` (kanal `slack`, odamning
O'Z hisobi; dvigatel - admin siyosati) -> bosqich matni "⏳" da -> javob shu xabar o'rnida: matn (`render.mrkdwn` va
havolalar), «📚 Manbalar», ichki hujjat tugmalari (bosilganda 10 daqiqalik imzolangan havola - bank hujjatining o'zi
Slack'ka yuklanmaydi), «🔄 Yangi suhbat»; so'ng takliflar («✅ Tasdiqlash» / «✖️ Rad etish» - tasdiqlanmaguncha hech
narsa o'zgarmaydi) va tayyorlangan hujjatlar (Word; PDF - tugmadan).

KIM. Faqat BRB-Tech ID bilan ulangan odam (`link.person`): savol va HR/CRM ma'lumoti uning O'Z hisobi va tokenlari bilan
(`chat._live_tokens` - SSO ulanishlari; bu modul ularni faqat O'QIYDI). Ulanmagan - ulash xabari (`link.offer`). Ulash
o'chiq o'rnatmada (umumiy hisob) yordamchi ishlamaydi: bitta hisob ostida hamma odamning HR ma'lumoti aralashardi.

SUHBAT. Odamning joriy suhbati (`ChatStore`: `<team>:<user>` -> UUID, `data/slack/assistant_chats.json`):
`SLACK_CHAT_IDLE_HOURS` jimlikdan keyin yoki «🔄 Yangi suhbat» bilan yangisi. Javob belgisi (`block_id`
`barno-hr:<suhbat>`) - uning thread'idagi savol O'SHA suhbatni davom ettiradi (eski javob ostida ham). Bir odamning
savollari ketma-ket (qulf) - agentdagi bitta suhbatga ikki savol aralashmasin.

ADMIN PANEL: savol izi veb va botdagi bilan bir xil (`TurnRecorder`, kanal `slack`, tur `bot`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..bot import render as bot_render
from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services import archive
from ..services.analytics import TurnRecorder, redact, set_proposal_status
from ..services.integrations.assistant import AssistantError
from ..services.meetings.intake import Problem
from . import link, render

log = logging.getLogger(__name__)

#: Javob belgisi (`block_id`): `barno-hr:<suhbat kaliti>`. `render.MARK` ("barno:") bilan boshlanmaydi - yig'ilish
#: belgisi deb o'qilmaydi (`render.marked_tag`).
MARK = "barno-hr:"
#: Tugmalar (`__init__._on_action` -> `on_action`).
ACTION_PREFIX = "barno_hr_"
NEW_ACTION = "barno_hr_new"
DOC_ACTION = "barno_hr_doc"
OK_ACTION = "barno_hr_ok"
NO_ACTION = "barno_hr_no"
FILE_ACTION = "barno_hr_file"
#: Imzolangan hujjat havolasi tugmasi (`url`) - bosilganda Slack brauzerni o'zi ochadi.
OPEN_ACTION = "barno_hr_open"
#: Bosqich matni "⏳" da shundan tez yangilanmaydi (Slack `chat.update` chegarasi).
STAGE_EVERY = 2.0
#: Javob ostidagi ichki hujjat tugmalari - ko'pi bilan.
DOC_BUTTONS = 5
#: Slack'ka yuklanadigan tayyorlangan hujjat chegarasi (bayt).
MAX_FILE = 40 * 1024 * 1024

WORKING = "⏳ Javob tayyorlanmoqda…"
NEW_BUTTON = "🔄 Yangi suhbat"
NEW_DONE = "🔄 Yangi suhbat boshlandi - keyingi savolingiz yangi suhbatda bo'ladi."
SHARED = ("HR va CRM yordamchisi faqat shaxsiy Barno AI hisobi bilan ishlaydi - javobda shaxsiy ma'lumot bo'ladi. "
          "Yozuvlar (Plaud) avvalgidek ishlaydi.")
TOO_LONG = "Savol juda uzun ({n} belgi) - {limit} belgigacha yozing."
EMPTY = "Javob kelmadi. Savolni boshqacha yozib ko'ring."
STALE = "Tugma eskirgan - savolni qaytadan bering."
#: Bir odamning bir vaqtdagi savollari (bittasi ishlanadi, qolgani navbatda) - ortig'iga "kuting": navbat iplari
#: (audio bilan umumiy, `__init__.WORKERS`) bitta odamga band bo'lib qolmasin (Telegram botdagi `_QUEUE_LIMIT` kabi).
QUEUE_LIMIT = 2
BUSY = "⏳ Oldingi savolingizga javob tayyorlanmoqda - u kelgach yozing."

_CHAT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: Markdown havolasi `[matn](https://...)` (`render.mrkdwn` dan keyin - `&` allaqachon `&amp;`).
_MD_LINK = re.compile(r"\[([^\]\n|]{1,300})\]\((https?://[^\s)|<>]{1,1000})\)")


# --- suhbat kaliti ---------------------------------------------------------------------------------------------


class ChatStore:
    """Odamning joriy yordamchi suhbati: `<team>:<user>` -> `{chat, at}`. Fayl (600, atomik yozuv) - restartda suhbat
    uzilmaydi; o'qib bo'lmasa bo'sh (yangi suhbat). Ko'pi bilan `MAX` odam - eng eskisi tashlanadi."""

    MAX = 5000

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] | None = None

    def current(self, key: str, *, idle_sec: float, now: float | None = None) -> str:
        """Joriy suhbat kaliti; jimlik `idle_sec` dan oshgan (yoki yo'q) bo'lsa - yangisi. Faollik vaqti yangilanadi."""
        now = time.time() if now is None else now
        with self._lock:
            data = self._load()
            entry = data.get(key) or {}
            chat = entry.get("chat")
            if not (isinstance(chat, str) and _CHAT.fullmatch(chat)) or now - float(entry.get("at") or 0) > idle_sec:
                chat = str(uuid.uuid4())
            data[key] = {"chat": chat, "at": now}
            self._save()
            return chat

    def renew(self, key: str, *, now: float | None = None) -> str:
        """«🔄 Yangi suhbat»: keyingi savol yangi suhbatda."""
        with self._lock:
            chat = str(uuid.uuid4())
            self._load()[key] = {"chat": chat, "at": time.time() if now is None else now}
            self._save()
            return chat

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._data is None:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            self._data = {str(k): v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}
        return self._data

    def _save(self) -> None:
        data = self._load()
        if len(data) > self.MAX:
            for key in sorted(data, key=lambda k: float(data[k].get("at") or 0))[:len(data) - self.MAX]:
                data.pop(key, None)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("Slack yordamchi suhbatlari yozilmadi (%s)", self.path, exc_info=True)


_store: ChatStore | None = None
_store_lock = threading.Lock()


def store() -> ChatStore:
    """Suhbatlar ombori - sozlama o'zgarsa (testlar) yangisi."""
    global _store
    path = Path(settings.slack_assistant_chats_file)
    with _store_lock:
        if _store is None or _store.path != path:
            _store = ChatStore(path)
        return _store


# --- kirish nuqtalari ------------------------------------------------------------------------------------------


def on_text(client: Any, event: dict[str, Any]) -> None:
    """Shaxsiy chatda thread'dan tashqaridagi matn (dispetcher: `home.is_text`) -> yordamchi; javob ham chatning o'zida,
    odamning joriy suhbatida."""
    channel = event.get("channel")
    if not channel:
        return
    _serve(client, event, channel, None, chat=None)


def owns(parent: dict[str, Any] | None, *, bot_user: str | None = None) -> str | None:
    """Thread boshidagi xabar yordamchi javobimi (O'ZIMIZ yozgan, `MARK` belgili) -> uning suhbat kaliti, aks holda
    `None` (`meeting.question` yozuvga bog'liq bo'lmagan thread'ni shu yerga beradi)."""
    if not parent or not parent.get("bot_id") or (bot_user and parent.get("user") != bot_user):
        return None
    for block in parent.get("blocks") or []:
        block_id = str(block.get("block_id") or "")
        if block_id.startswith(MARK) and _CHAT.fullmatch(block_id[len(MARK):]):
            return block_id[len(MARK):]
    return None


def on_thread(client: Any, event: dict[str, Any], chat: str) -> None:
    """Yordamchi javobining thread'idagi savol - O'SHA suhbatda (`owns`), javob ham shu thread'da."""
    _serve(client, event, event["channel"], event.get("thread_ts"), chat=chat)


def handles(body: dict[str, Any]) -> bool:
    """Shu modulning tugmasimi (`__init__._on_action` dispetcheri)."""
    action = (body.get("actions") or [{}])[0]
    return str(action.get("action_id") or "").startswith(ACTION_PREFIX)


# --- savol -----------------------------------------------------------------------------------------------------


@dataclass
class Answer:
    """Oqimdan yig'ilgan javob (Telegram botdagi `_Answer` kabi)."""

    parts: list[str] = field(default_factory=list)
    docs: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    failure: str | None = None
    #: Savol izi uchun: oqim ochilmagan yoki o'rtada uzilgan bo'lsa - sababi.
    error: BaseException | None = None


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
#: Odam -> hozir kutayotgan (ishlanayotgan va navbatdagi) savollari soni (`QUEUE_LIMIT`).
_pending: dict[str, int] = {}


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        if len(_locks) > 5000:
            _locks.clear()
        return _locks.setdefault(key, threading.Lock())


def _serve(client: Any, event: dict[str, Any], channel: str, thread: str | None, *, chat: str | None) -> None:
    """Bitta savol: hisob, suhbat kaliti, chegara, so'ng `ask`. Xato odamga tushunarli matn bilan."""
    team, person = link.team_of(event), event.get("user")
    question = render.unescape(str(event.get("text") or "")).strip()
    if not question:
        return
    user = _account(client, team, person, channel, thread)
    if user is None:
        return
    limit = int(settings.hrm_assistant_max_question_chars or 0)
    if limit and len(question) > limit:
        _post(client, channel, thread, TOO_LONG.format(n=len(question), limit=limit))
        return
    key = f"{team or ''}:{person or ''}"
    with _locks_guard:
        waiting = _pending.get(key, 0)
        if waiting < QUEUE_LIMIT:
            _pending[key] = waiting + 1
    if waiting >= QUEUE_LIMIT:
        _post(client, channel, thread, BUSY)
        return
    try:
        with _lock_for(key):
            if chat is None:
                chat = store().current(key, idle_sec=float(settings.slack_chat_idle_hours or 6.0) * 3600)
            ask(client, channel, thread, user, question, chat)
    except Exception:  # noqa: BLE001 - navbatdagi vazifa: xato hech qayerda ko'rinmas, odam javobsiz qolardi
        log.exception("Slack yordamchi savoli (%s): kutilmagan xato", user.actorId)
        _post(client, channel, thread, "Javob berib bo'lmadi: ichki xato.")
    finally:
        with _locks_guard:
            left = _pending.get(key, 1) - 1
            if left > 0:
                _pending[key] = left
            else:
                _pending.pop(key, None)


def _account(client: Any, team: str | None, slack_user: str | None, channel: str, thread: str | None, *,
             force: bool = False) -> AuthUser | None:
    """Kimning nomidan: ulangan odamning O'Z hisobi (`link.person` - har so'rovda qayta tekshiriladi). Ulash o'chiq
    o'rnatma - `SHARED`; ulanmagan yoki bloklangan - `link.gate` xabari (faqat unga ko'rinadi; `force` - tugmani o'zi
    bosgan, takror cheklovi yo'q). Bo'lmasa `None`."""
    if not link.required():
        _post(client, channel, thread, SHARED)
        return None
    if not link.gate(client, team, slack_user, channel, thread=thread, force=force):
        return None
    try:
        return link.person(team, slack_user)
    except Problem as exc:                     # `gate` va shu orasida uzildi
        _post(client, channel, thread, render.escape(str(exc)))
        return None


def ask(client: Any, channel: str, thread: str | None, user: AuthUser, question: str, chat: str) -> None:
    """Savol -> "⏳" -> oqim -> javob (o'sha xabar o'rnida) -> takliflar va hujjatlar. Savol izi admin panelda."""
    rec = TurnRecorder(user, "slack", "bot", question, chat_id=chat, locale="uz", input_mode="text")
    answer = Answer()
    try:
        with rec.bind():
            holder = _post(client, channel, thread, WORKING)
            answer = _collect(client, channel, holder, question, user, chat, rec)
            with rec.span("slack.deliver"):
                _deliver(client, channel, thread, holder, answer, user, chat)
    except BaseException as exc:
        rec.finish("error", error=exc)
        raise
    rec.finish(error=answer.error)


def _collect(client: Any, channel: str, holder: str | None, question: str, user: AuthUser, chat: str,
             rec: TurnRecorder) -> Answer:
    """Oqimni o'qiydi (Telegram botdagi `_collect` bilan bir xil kadrlar): matn, bosqich ("⏳" da), manbalar, hujjatlar,
    takliflar, xato. Oqim har holda yopiladi - yuqoridagi xizmat sloti shunda bo'shaydi."""
    from ..api.v1 import chat as _chat

    answer = Answer()
    log.info("Slack yordamchi savoli (%s): %d belgi", user.actorId, len(question))
    try:
        with rec.span("assistant.open") as info:
            stream = _chat.open_stream(question, user, chat, channel="slack", mode="standard", engine=None)
            info["requestId"] = stream.request_id
    except AssistantError as exc:
        log.warning("Slack yordamchi savoli (%s) [%s]: %s", user.actorId, getattr(exc, "reason", None) or "-", exc)
        answer.failure = _chat._MESSAGES.get(exc.status, _chat._MESSAGES[502])
        rec.error_code, answer.error = _chat.open_error_code(exc), exc
        rec.update(engine=_chat.effective_engine(user, "slack"))
        return answer
    rec.update(request_id=stream.request_id, engine=getattr(stream, "engine", None))
    stage_text, stage_at = "", 0.0
    try:
        for raw in stream.frames:
            try:
                frame = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(frame, dict):
                continue
            rec.observe(frame)
            kind = frame.get("type")
            if kind == "token":
                answer.parts.append(str(frame.get("text") or ""))
            elif kind == "stage":
                text = str(frame.get("text") or "").strip()
                now = time.monotonic()
                if holder and text and text != stage_text and now - stage_at >= STAGE_EVERY:
                    stage_text, stage_at = text, now
                    _update(client, channel, holder, f"⏳ {render.escape(text)}")
            elif kind == "sources":
                docs = bot_render.doc_sources(frame.get("sources") or frame.get("items"))
                if docs:
                    answer.docs = docs
            elif kind == "artifact":
                art = frame.get("artifact") or frame
                if isinstance(art, dict):
                    answer.artifacts.append(art)
            elif kind == "proposal":
                proposal = frame.get("proposal") or frame
                if isinstance(proposal, dict) and proposal.get("token"):
                    answer.proposals.append(proposal)
            elif kind == "error":
                answer.failure = bot_render.frame_error(frame)
    except AssistantError as exc:
        # Oqim o'rtasida uzildi - kelgan qism baribir ko'rsatiladi.
        log.warning("Slack yordamchi javob oqimi (%s): %s", user.actorId, exc)
        answer.failure = _chat._MESSAGES.get(exc.status, _chat._MESSAGES[502])
        rec.point("assistant.broken", status=exc.status, error=redact(exc))
        rec.error_code, answer.error = "stream_broken", exc
    finally:
        close = getattr(stream, "close", None) or getattr(stream.frames, "close", None)
        if callable(close):
            close()
        log.info("Slack yordamchi javobi (%s): request_id=%s natija=%s", user.actorId, stream.request_id,
                 stream.outcome or "-")
    return answer


def _deliver(client: Any, channel: str, thread: str | None, holder: str | None, answer: Answer, user: AuthUser,
             chat: str) -> None:
    """Javob "⏳" o'rnida: matn, «📚 Manbalar», qisman javobdan keyingi xato izohi va oxirida tugmalar (ichki hujjatlar,
    «🔄 Yangi suhbat») - `MARK` belgisi bilan (thread'idagi savol shu suhbatga). So'ng takliflar va hujjatlar."""
    body = "".join(answer.parts).strip()
    text = answer_text(body) if body else ""
    shown: list[dict[str, Any]] = []
    if text and answer.docs:
        shown = bot_render.cited(answer.docs, body)
        text += "\n\n" + sources_text(shown)
    if not text:
        if answer.failure:
            text = "⚠️ " + render.escape(answer.failure)
        elif not answer.artifacts and not answer.proposals:
            text = EMPTY
    elif answer.failure:
        text += "\n\n⚠️ _" + render.escape(answer.failure) + "_"
    if text:
        blocks = render.sections(text) + [answer_actions(chat, shown)]
        _replace(client, channel, holder, thread, text, blocks)
    elif holder:
        # Faqat taklif yoki hujjat - "⏳" kerak emas.
        try:
            client.chat_delete(channel=channel, ts=holder)
        except Exception:  # noqa: BLE001
            _update(client, channel, holder, "✓")
    for proposal in answer.proposals:
        text, blocks = proposal_message(proposal)
        _post(client, channel, thread, text, blocks)
    for artifact in answer.artifacts:
        send_artifact(client, channel, thread, user, artifact)


# --- ko'rinish -------------------------------------------------------------------------------------------------


def answer_text(body: str) -> str:
    """Yordamchi markdown javobi -> Slack mrkdwn (`render.mrkdwn`) va bosiladigan havolalar (`<url|matn>`)."""
    return _MD_LINK.sub(lambda m: f"<{m.group(2)}|{m.group(1).strip()}>", render.mrkdwn(body))


def sources_text(docs: list[dict[str, Any]], *, most: int = bot_render.FOOTNOTES_MAX) -> str:
    """«📚 Manbalar»: har manba bitta qator. LEX.UZ - bosiladigan havola (faqat xavfsiz `https`,
    `bot_render.safe_source_url`), ichki hujjat - nomi va beti (uni javob ostidagi tugma ochadi)."""
    lines = []
    for index, doc in enumerate(docs[:most]):
        if doc.get("kind") == bot_render.LAW_KIND:
            mark = doc.get("marker") or f"[{doc.get('citation_index') or index + 1}]"
            title = " ".join(str(doc.get("title") or "").split())[:120]
            url = bot_render.safe_source_url(doc.get("url"))
            name = render.escape(title or bot_render.LAW_LABEL).replace("|", "/")
            shown = f"<{render.escape(url)}|{name}>" if url else name
            lines.append(f"{render.escape(str(mark))} {render.escape(bot_render.LAW_LABEL)}: {shown}"
                         if title else f"{render.escape(str(mark))} {shown}")
        else:
            lines.append(render.escape(bot_render.source_label(doc, index)))
    if len(docs) > most:
        lines.append(f"_… yana {len(docs) - most} ta manba - Barno ilovasida_")
    return "📚 *Manbalar*\n" + "\n".join(lines)


def answer_actions(chat: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Javob ostidagi tugmalar: ichki hujjatlar («📄 [n] nomi» - bosilganda imzolangan havola) va «🔄 Yangi suhbat».
    `block_id` - javob belgisi (`MARK`): thread'idagi savol shu suhbatga."""
    elements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, doc in enumerate(docs):
        doc_id = doc.get("doc_id")
        if doc.get("kind") == bot_render.LAW_KIND or not isinstance(doc_id, str) or doc_id in seen:
            continue
        if not bot_render.SAFE_KEY.fullmatch(doc_id) or len(elements) >= DOC_BUTTONS:
            continue
        seen.add(doc_id)
        title = " ".join(str(doc.get("title") or "Hujjat").split())
        mark = doc.get("marker") or f"[{index + 1}]"
        elements.append(render.button(f"📄 {mark} {title}"[:75], DOC_ACTION, f"{doc_id}|{title[:200]}"))
    # Bitta `actions` blokida 25 tagacha element - sig'adi (`DOC_BUTTONS` + 1).
    elements.append(render.button(NEW_BUTTON, NEW_ACTION, chat))
    return {"type": "actions", "block_id": f"{MARK}{chat}", "elements": elements}


def proposal_message(proposal: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Taklif kartasi (`bot_render.proposal_card` mazmuni, Slack mrkdwn) va «✖️ Rad etish» / «✅ Tasdiqlash»; kalit
    tugmaga sig'masa - "Barno ilovasida tasdiqlang"."""
    platform = str(proposal.get("connector") or "").upper()
    lines = ["✏️ *Taklif qilingan o'zgarish*" + (f" · {render.escape(platform)}" if platform else "")]
    if proposal.get("summary"):
        lines.append(render.escape(str(proposal["summary"])))
    details: list[str] = []
    if proposal.get("target"):
        details.append(f"*Obyekt:* {render.escape(bot_render.action_text(proposal['target']))}")
    for change in proposal.get("changes") or []:
        if not isinstance(change, dict) or not (change.get("field") or "to" in change):
            continue
        label = render.escape(str(change.get("field") or "O'zgarish"))
        before = change.get("from")
        was = f"~{render.escape(bot_render.action_text(before))}~ → " if before not in (None, "") else ""
        details.append(f"*{label}:* {was}{render.escape(bot_render.action_text(change.get('to')))}")
    if details:
        lines.append("\n".join(details))
    warnings = [str(w) for w in proposal.get("warnings") or [] if w]
    if warnings:
        lines.append("\n".join(f"⚠️ {render.escape(w)}" for w in warnings))
    token = str(proposal.get("token") or "")
    if bot_render.SAFE_KEY.fullmatch(token):
        lines.append("_Tasdiqlamaguningizcha hech narsa o'zgarmaydi. Taklif 15 daqiqada kuchini yo'qotadi._")
        text = "\n\n".join(lines)
        no = render.button("✖️ Rad etish", NO_ACTION, token)
        ok = {**render.button("✅ Tasdiqlash", OK_ACTION, token), "style": "primary"}
        return text, render.sections(text) + [{"type": "actions", "elements": [no, ok]}]
    lines.append("_Bu taklifni Barno ilovasida tasdiqlang._")
    text = "\n\n".join(lines)
    return text, render.sections(text)


def outcome_text(result: dict[str, Any]) -> tuple[bool, str]:
    """(yakunlandimi, xabar) - `bot_render.outcome` qoidasi, Slack mrkdwn."""
    status = result.get("status")
    if status == "executed" and result.get("ok") is not False:
        found = result.get("result") if isinstance(result.get("result"), dict) else {}
        key = next((found[k] for k in ("key", "id", "number") if found.get(k) is not None), None)
        return True, "✅ *Bajarildi*" + (f": `{render.escape(str(key))}`" if key is not None else "")
    if status == "cancelled":
        return True, "✖️ Rad etildi - hech narsa o'zgarmadi."
    if status == "expired":
        return True, "⌛ Taklif muddati tugagan. Kerak bo'lsa savolni qaytadan bering."
    if status == "pending":
        return False, "Taklif hali kutilmoqda."
    reason = str(result.get("error") or "Amalni bajarib bo'lmadi.")
    return True, f"⚠️ *Bajarilmadi*: {render.escape(reason)}"


# --- tugmalar --------------------------------------------------------------------------------------------------


_busy: set[str] = set()
_busy_lock = threading.Lock()


def on_action(client: Any, body: dict[str, Any]) -> None:
    """«🔄 Yangi suhbat», hujjat havolasi, taklifni tasdiqlash / rad etish, hujjatning boshqa formati. Bosgan odam -
    ulangan hisobi bilan (begona yoki ulanmagan - ulash xabari)."""
    action = (body.get("actions") or [{}])[0]
    kind = str(action.get("action_id") or "")
    value = str(action.get("value") or "")
    channel = (body.get("channel") or {}).get("id") or (body.get("container") or {}).get("channel_id")
    message = body.get("message") or {}
    thread = message.get("thread_ts")
    team, person = link.team_of(body), (body.get("user") or {}).get("id")
    if not channel or kind == OPEN_ACTION:
        # Havola-tugma: brauzerni Slack o'zi ochgan - ish yo'q.
        return
    user = _account(client, team, person, channel, thread, force=True)
    if user is None:
        return
    try:
        if kind == NEW_ACTION:
            store().renew(f"{team or ''}:{person or ''}")
            _post(client, channel, thread, NEW_DONE)
        elif kind == DOC_ACTION:
            open_doc(client, channel, thread or message.get("ts"), user, value)
        elif kind in (OK_ACTION, NO_ACTION):
            decide(client, channel, message, user, "confirm" if kind == OK_ACTION else "cancel", value)
        elif kind == FILE_ACTION:
            fmt, _, rest = value.partition("|")
            token, _, title = rest.partition("|")
            if fmt in ("docx", "pdf") and bot_render.SAFE_ARTIFACT.fullmatch(token):
                send_file(client, channel, thread, fmt, token, title or "Hujjat")
            else:
                _post(client, channel, thread, STALE)
    except Exception:  # noqa: BLE001 - navbatdagi vazifa: odam javobsiz qolmasin
        log.exception("Slack yordamchi tugmasi (%s): kutilmagan xato", kind)
        _post(client, channel, thread, "Bajarib bo'lmadi: ichki xato.")


def open_doc(client: Any, channel: str, thread: str | None, user: AuthUser, value: str) -> None:
    """Ichki hujjat: imzolangan, qisqa muddatli havola (`chat.doc_link`, kanal `slack`) - yangi xabar, havola-tugma
    bilan. NEGA HAVOLA, fayl emas: bank hujjati Slack serverlarida qolmasin; tugma har bosilganda yangi havola
    beradi."""
    from ..api.v1 import chat as _chat

    doc_id, _, title = value.partition("|")
    origin = _origin(settings.telegram_webapp_url)
    if not bot_render.SAFE_KEY.fullmatch(doc_id) or not origin:
        _post(client, channel, thread, "Hujjatni hozir ochib bo'lmadi - Barno ilovasida oching.")
        return
    try:
        found = _chat.doc_link(doc_id, user.actorId, title or doc_id, channel="slack")
    except ValueError:
        _post(client, channel, thread, STALE)
        return
    path = str(getattr(found, "url", "") or "")
    if not path.startswith("/"):
        _post(client, channel, thread, "Hujjatni hozir ochib bo'lmadi - Barno ilovasida oching.")
        return
    minutes = max(1, int(getattr(found, "expiresIn", 600) or 600) // 60)
    text = (f"📄 *{render.escape(title or 'Hujjat')}*\n_Havola {minutes} daqiqa ishlaydi - keyin tugmani javob "
            "ostidan qayta bosing._")
    button = {"type": "button", "action_id": OPEN_ACTION, "text": {"type": "plain_text", "text": "📄 Ochish"},
              "url": origin + path}
    _post(client, channel, thread, text, render.sections(text) + [{"type": "actions", "elements": [button]}])


def decide(client: Any, channel: str, message: dict[str, Any], user: AuthUser, verb: str, token: str) -> None:
    """Taklifni tasdiqlash yoki rad etish (`/actions` dagi AYNI chaqiruv: odamning O'Z kimligi va tokenlari). Natija -
    karta tugmalarsiz va ostida natija; muddati o'tgan - tugmalar olinadi. Ikki marta bosish - bitta so'rov
    (ikkinchisi jim)."""
    from ..api.v1 import actions as _actions
    from ..api.v1 import chat as _chat

    thread = message.get("thread_ts")
    if not bot_render.SAFE_KEY.fullmatch(token):
        _post(client, channel, thread, STALE)
        return
    with _busy_lock:
        if token in _busy:
            return
        _busy.add(token)
    try:
        call = _chat._assistant.confirm_action if verb == "confirm" else _chat._assistant.cancel_action
        try:
            result = call(token, user_id=_chat.assistant_user_id(user), tokens=_chat._live_tokens(user))
        except AssistantError as exc:
            log.warning("Slack taklif %s (%s): %s", verb, user.actorId, exc)
            text = render.escape(_actions._MESSAGES.get(exc.status, _actions._MESSAGES[502]))
            if exc.status in _actions.EXPIRED_STATUSES:
                set_proposal_status(token, "expired")
                _settle(client, channel, message, "⌛ Taklif muddati tugagan. Kerak bo'lsa savolni qaytadan bering.")
            else:
                _post(client, channel, thread, f"⚠️ {text}")
            return
        status = _actions.proposal_outcome(verb, result)
        if status:
            set_proposal_status(token, status)
        settled, text = outcome_text(result)
        log.info("Slack taklif %s (%s): holat=%s ok=%s", verb, user.actorId, result.get("status"), result.get("ok"))
        if settled:
            _settle(client, channel, message, text)
        else:
            _post(client, channel, thread, text)
    finally:
        with _busy_lock:
            _busy.discard(token)


def _settle(client: Any, channel: str, message: dict[str, Any], outcome: str) -> None:
    """Taklif kartasi yakunlandi: tugmalar olinadi, ostida natija (karta matni o'zgarmaydi)."""
    ts = message.get("ts")
    blocks = [b for b in message.get("blocks") or [] if b.get("type") != "actions"]
    text = str(message.get("text") or "Taklif")
    _replace(client, channel, ts, message.get("thread_ts"), text, blocks + [render.context(outcome)])


def send_artifact(client: Any, channel: str, thread: str | None, user: AuthUser, art: dict[str, Any]) -> None:
    """Tayyorlangan hujjat (ariza): Word fayli (yo'q bo'lsa - PDF) shu joyga; ikkalasi ham bo'lsa - PDF tugmasi
    (kerak bo'lsa olinadi, ikkinchi fayl behuda yuklanmaydi). Kalitlar - `/api/v1/chat/artifact/{token}/{tur}`."""
    title = " ".join(str(art.get("title") or art.get("filename") or "Hujjat").split())[:200]
    refs: dict[str, str] = {}
    for key in ("docx_url", "pdf_url"):
        parts = str(art.get(key) or "").split("/")
        if (len(parts) == 7 and parts[1:5] == ["api", "v1", "chat", "artifact"] and parts[6] in ("docx", "pdf")
                and bot_render.SAFE_ARTIFACT.fullmatch(parts[5])):
            refs[parts[6]] = parts[5]
    if not refs:
        _post(client, channel, thread, f"📎 Hujjat tayyorlandi: *{render.escape(title)}*. Faylni Barno ilovasidan "
                                       "yuklab oling.")
        return
    kind = "docx" if "docx" in refs else "pdf"
    if send_file(client, channel, thread, kind, refs[kind], title) and kind == "docx" and "pdf" in refs:
        value = f"pdf|{refs['pdf']}|{title}"[:2000]
        text = f"📎 *{render.escape(title)}* - PDF ham kerak bo'lsa:"
        _post(client, channel, thread, text,
              render.sections(text) + [{"type": "actions", "elements": [render.button("📕 PDF", FILE_ACTION, value)]}])


def send_file(client: Any, channel: str, thread: str | None, kind: str, token: str, title: str) -> bool:
    """Hujjat fayli yuqoridagi xizmatdan (`fetch_artifact`) - shu joyga; arxivga ham. Yuborilsa `True`."""
    from ..api.v1 import chat as _chat

    try:
        content_type, upstream_name, chunks = _chat._assistant.fetch_artifact(token, kind)
        data = b"".join(chunks)
    except AssistantError as exc:
        log.warning("Slack: hujjat olinmadi: %s", exc)
        _post(client, channel, thread, "Hujjatni olib bo'lmadi: "
              + render.escape(_chat._MESSAGES.get(exc.status, _chat._MESSAGES[502])))
        return False
    if not data or len(data) >= MAX_FILE:
        _post(client, channel, thread, "Hujjatni yuborib bo'lmadi - fayl bo'sh yoki juda katta.")
        return False
    name = _chat._download_name(title, kind) or upstream_name or f"hujjat.{kind}"
    try:
        where = {"thread_ts": thread} if thread else {}
        client.files_upload_v2(channel=channel, file=data, filename=name, title=name, **where)
    except Exception as exc:  # noqa: BLE001 - SlackApiError (`files:write` yo'q), tarmoq
        log.warning("Slack: hujjat yuborilmadi: %s", exc)
        _post(client, channel, thread, "Hujjatni yuborib bo'lmadi - qaytadan urinib ko'ring.")
        return False
    archive.record("slack", "out", "document", chat=channel, data=data, name=name, mime=content_type or "",
                   meta={"thread": thread} if thread else None)
    return True


# --- Slack'ka yozish -------------------------------------------------------------------------------------------


def _origin(url: str) -> str:
    """Ommaviy manzilning boshi (`https://host`) - imzolangan havola shu domendan ochiladi; `https` bo'lmasa - bo'sh."""
    found = re.match(r"^(https://[^/\s]+)", str(url or "").strip())
    return found.group(1) if found else ""


def _post(client: Any, channel: str, thread: str | None, text: str,
          blocks: list[dict[str, Any]] | None = None) -> str | None:
    from .meeting import post

    return post(client, channel, thread, text, blocks)


def _update(client: Any, channel: str, ts: str, text: str) -> None:
    try:
        client.chat_update(channel=channel, ts=ts, text=text[:3000], blocks=render.sections(text) or None)
    except Exception:  # noqa: BLE001 - bosqich matni muhim emas
        log.debug("Slack: bosqich matni yangilanmadi", exc_info=True)


def _replace(client: Any, channel: str, ts: str | None, thread: str | None, text: str,
             blocks: list[dict[str, Any]] | None = None) -> None:
    from .meeting import replace

    replace(client, channel, ts, thread, text, blocks)

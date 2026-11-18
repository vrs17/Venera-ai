"""Slack: OVOZ NAMUNASI - Plaud yig'ilishlarida xodim ism-familiyasi bilan chiqishi uchun (ega qarori 2026-11-18;
mantiq - `services/meetings/voice.py`, Telegram va mobil ilova bilan BITTA).

  * «🗣 Ovoz namunasi» tugmasi ("Home" varag'ida va Plaud yo'riqnomasida) yoki shaxsiy chatga «ovoz namunasi» deb
    yozish - tartib, o'qish matni va holat shaxsiy chatga keladi; odam `ARMED_SEC` davomida QUROLLANADI: shu
    oraliqda shaxsiy chatga yuborgan audio (Slack'ning mikrofon tugmasi bilan yozilgan klip yoki fayl) namuna deb
    olinadi - Plaud yozuvi emas. Bitta audioga ishlaydi; rad etilsa yana qurollanadi.
  * natija - audio xabarining thread'ida "⏳" o'rnida: ✅ saqlandi yoki aniq sabab.
  * «🗑 Ovozimni o'chirish» - Slack'ning o'z tasdiq oynasi bilan.

KIMNING NOMIDAN - FAQAT odamning O'Z Barno hisobi (`link.person`): umumiy `SLACK_ACTOR_ID` hisobiga ovoz
yozilmaydi (ovoz - bitta odamniki). Ulanmagan odamga ulash xabari.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time

from pathlib import Path
from typing import Any

from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services.meetings import voice
from ..services.meetings.errors import MeetingProblem
from . import link, render

log = logging.getLogger(__name__)

START_ACTION = "barno_voice"
DELETE_ACTION = "barno_voice_del"
ARMED_SEC = 15 * 60
BUTTON = "🗣 Ovoz namunasi"
WAIT_TEXT = "⏳ Namuna tekshirilmoqda… (odatda 10-60 soniya)"
AGAIN = "\n\nQayta yozib, shu chatga yuboring - keyingi 15 daqiqada kelgan audio namuna bo'ladi."
#: Shaxsiy chatga shu so'zlardan biri yozilsa - yo'riqnoma (HR yordamchisiga ketmaydi).
KEYWORDS = {"ovoz namunasi", "ovoz", "/ovoz", "voice sample", "образец голоса", BUTTON.lower()}
HOME_TEXT = ("🗣 *Ovoz namunasi* — Plaud yig'ilishlarida ism-familiyangiz avtomatik chiqishi uchun ~45 soniyalik "
             "namuna yozing. Bir marta yozasiz: Slack, Telegram va mobil ilovadagi yig'ilishlarning hammasida ishlaydi.")

_lock = threading.Lock()
_armed: dict[str, float] = {}


def _key(team: str | None, user: str | None) -> str:
    return f"{team or ''}:{user or ''}"


def arm(team: str | None, user: str | None) -> None:
    with _lock:
        _armed[_key(team, user)] = time.monotonic() + ARMED_SEC
        if len(_armed) > 5000:
            _armed.clear()


def disarm(team: str | None, user: str | None) -> None:
    with _lock:
        _armed.pop(_key(team, user), None)


def armed(team: str | None, user: str | None) -> bool:
    with _lock:
        return _armed.get(_key(team, user), 0.0) > time.monotonic()


# --- bloklar ---------------------------------------------------------------------------------


def start_button() -> dict[str, Any]:
    return render.button(BUTTON, START_ACTION, "start")


def delete_button() -> dict[str, Any]:
    return render.button("🗑 Ovozimni o'chirish", DELETE_ACTION, "delete", confirm={
        "title": {"type": "plain_text", "text": "Ovoz namunasi"},
        "text": {"type": "mrkdwn", "text": "Ovoz namunangiz o'chirilsinmi? Yig'ilishlarda ismingiz endi avtomatik "
                                           "chiqmaydi."},
        "confirm": {"type": "plain_text", "text": "Ha, o'chirish"},
        "deny": {"type": "plain_text", "text": "Bekor qilish"}})


def home_blocks() -> list[dict[str, Any]]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": HOME_TEXT}},
            {"type": "actions", "block_id": "barno:voice", "elements": [start_button()]}]


def instructions_text(status: dict[str, Any] | None = None) -> str:
    info = voice.instructions()
    lines = [f"*{info['intro']}*", ""]
    if status and status.get("enrolled"):
        lines += [f"✅ Ovozingiz saqlangan ({int(status.get('samples') or 0)} ta namuna). Yangi namuna yuborsangiz "
                  "qo'shiladi va tanish aniqroq bo'ladi.", ""]
    lines.append("*Qanday yoziladi:*")
    lines += [f"{n}. {step}" for n, step in enumerate(info["steps"], start=1)]
    lines += ["", "*O'qiladigan matn:*", f"> {info['text']}", "",
              "🎤 Xabar maydonidagi mikrofon tugmasini bosib yozing va shu chatga yuboring (taxminan 45 soniya)."]
    return "\n".join(lines)


def instructions_blocks(status: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    blocks = render.sections(instructions_text(status))
    if status and status.get("enrolled"):
        blocks.append({"type": "actions", "block_id": "barno:voice-del", "elements": [delete_button()]})
    return blocks


# --- hodisalar ---------------------------------------------------------------------------------


def handles(body: dict[str, Any]) -> bool:
    action = (body.get("actions") or [{}])[0]
    return str(action.get("action_id") or "") in (START_ACTION, DELETE_ACTION)


def is_text(event: dict[str, Any]) -> bool:
    """Shaxsiy chatdagi (thread'dan tashqari) «ovoz namunasi» so'rovi."""
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype") or event.get("thread_ts"):
        return False
    return " ".join(str(event.get("text") or "").lower().split()) in KEYWORDS


def wants(event: dict[str, Any]) -> bool:
    """Qurollangan odamning shaxsiy chatdagi audiosi - namuna (Plaud yozuvi emas). Qurollanish sarflanadi."""
    from .transcribe import audio_files

    if event.get("channel_type") != "im" or event.get("bot_id"):
        return False
    files = [f for f in audio_files(event) if not f.get("subtype") == "slack_video"]
    team, user = link.team_of(event), event.get("user")
    if not files or not armed(team, user):
        return False
    disarm(team, user)
    return True


def _person(client: Any, team: str | None, user: str | None, channel: str | None,
            thread: str | None = None) -> AuthUser | None:
    try:
        return link.person(team, user)
    except link.NotLinked as exc:
        link.offer(client, team, user, channel, thread=thread, state=exc.state, force=True)
    except Exception as exc:  # noqa: BLE001 - bloklangan hisob (`Problem`) va boshqalar
        if user:
            try:
                client.chat_postMessage(channel=user, text=render.escape(str(exc)))
            except Exception:  # noqa: BLE001
                pass
    return None


def show(client: Any, team: str | None, user: str | None, channel: str | None = None) -> None:
    """Tartib, matn va holat - odamning shaxsiy chatiga; odam qurollanadi."""
    person = _person(client, team, user, channel)
    if person is None:
        return
    try:
        state = voice.status(person)
    except MeetingProblem as exc:
        client.chat_postMessage(channel=user, text=exc.message)
        return
    if not state.get("enabled"):
        client.chat_postMessage(channel=user, text="🗣 Ovoz namunasi hozir o'chiq.")
        return
    arm(team, user)
    text = instructions_text(state)
    try:
        client.chat_postMessage(channel=user, text=text[:3000], blocks=instructions_blocks(state))
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack ovoz namunasi yo'riqnomasi yuborilmadi: %s", exc)


def on_text(client: Any, event: dict[str, Any]) -> None:
    show(client, link.team_of(event), event.get("user"), event.get("channel"))


def on_action(client: Any, body: dict[str, Any]) -> None:
    action = str(((body.get("actions") or [{}])[0]).get("action_id") or "")
    user = (body.get("user") or {}).get("id")
    channel = (body.get("channel") or {}).get("id")
    team = link.team_of(body)
    if action == START_ACTION:
        show(client, team, user, channel)
        return
    person = _person(client, team, user, channel)
    if person is None:
        return
    try:
        result = voice.delete(person)
        text = result.get("message") or voice.DELETED_TEXT
    except MeetingProblem as exc:
        text = exc.message
    try:
        client.chat_postMessage(channel=user, text=text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack ovoz namunasi: javob yuborilmadi: %s", exc)


def on_audio(client: Any, event: dict[str, Any]) -> None:
    """Namuna: fayl yuklab olinadi, tekshiruv fonda (`voice.submit`), natija thread'dagi "⏳" o'rnida."""
    from . import meeting
    from .transcribe import Problem, audio_files, fetch

    team, user, channel = link.team_of(event), event.get("user"), event.get("channel")
    thread = event.get("thread_ts") or event.get("ts")
    person = _person(client, team, user, channel, thread)
    if person is None or not channel:
        return
    holder = meeting.post(client, channel, thread, WAIT_TEXT)
    file = next(f for f in audio_files(event))
    try:
        if file.get("file_access") == "check_file_info":
            file = client.files_info(file=file["id"])["file"]
        with tempfile.TemporaryDirectory(prefix="slack-voice-") as tmp:
            path, size, _sha, kind = fetch(file, Path(tmp))
            if size > int(settings.voice_sample_max_bytes):
                raise Problem("Yozuv juda katta - 1 daqiqagacha yozing.")
            data = path.read_bytes()
    except Problem as exc:
        arm(team, user)
        meeting.replace(client, channel, holder, thread, render.escape(str(exc)) + AGAIN)
        return
    except Exception:  # noqa: BLE001 - SlackApiError, tarmoq
        log.exception("Slack ovoz namunasi olinmadi")
        arm(team, user)
        meeting.replace(client, channel, holder, thread, "Yozuvni olib bo'lmadi - qaytadan yuboring." + AGAIN)
        return

    def done(view: dict[str, Any]) -> None:
        ok = view.get("status") == "ok"
        if not ok:
            arm(team, user)
        meeting.replace(client, channel, holder, thread, (view.get("message") or "") + ("" if ok else AGAIN))

    try:
        voice.submit(person, data, kind, "slack", on_done=done)
    except MeetingProblem as exc:
        if exc.status_code != 409:
            arm(team, user)
        meeting.replace(client, channel, holder, thread, exc.message + (AGAIN if exc.status_code != 409 else ""))

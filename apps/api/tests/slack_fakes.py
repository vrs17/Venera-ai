"""Slack testlari uchun soxtalar: `WebClient`, Slack hisobi va audio fayli. Tarmoqqa chiqmaydi."""

from __future__ import annotations

import time

from typing import Any

from app.api import deps
from app.core.config import settings
from app.services.identities import Directory
from app.services.users import UserStore
from app.slack import render, transcribe
from meetings_fakes import adts_bytes, enable, run_all, sha

AUDIO = {"id": "F1", "name": "ovoz.aac", "mimetype": "audio/aac", "created": 1762150000,
         "url_private_download": "https://files.slack.com/files-pri/T1-F1/download/ovoz.aac"}
#: Barno'ning bot foydalanuvchisi - thread boshidagi xabar "o'zimizniki"mi.
BOT_USER = "UBOT"


class FakeSlack:
    """`WebClient` ning ishlatiladigan metodlari: yuborilgan, yangilangan, o'chirilgan va yuklangan narsalar yoziladi.

    Chat tarixi (`conversations_history`) - Slack'dagidek chatning o'zidan (`timeline`): Barno'ning thread'dan
    tashqaridagi xabarlari (oxirgi tahriri bilan, o'chirilgani yo'q) va odam yozganlari (`say`). `history` da
    qo'lda berilgan kanal - aynan o'sha ro'yxat. `history_error` - tarix o'qilmaydi: istisno ko'tariladi, lug'at esa
    Slack javobi sifatida qaytadi (`{"ok": False, ...}`)."""

    def __init__(self, files: dict[str, dict] | None = None, parents: dict[str, dict] | None = None,
                 upload_error: Exception | None = None) -> None:
        self.posted: list[dict] = []
        self.updated: list[dict] = []
        self.deleted: list[dict] = []
        self.uploaded: list[dict] = []
        self.published: list[dict] = []
        self.ephemeral: list[dict] = []
        self.history: dict[str, list[dict]] = {}
        #: (kanal, ts) -> xabar, yozilish tartibida (thread'dan tashqaridagilar).
        self.timeline: dict[tuple[str, str], dict] = {}
        self.history_reads: list[dict] = []
        self.history_error: Exception | dict | None = None
        self.said = 0
        self.files = files or {}
        self.parents = parents or {}
        self.upload_error = upload_error

    def chat_postMessage(self, **kwargs):
        kwargs["ts"] = f"100.{len(self.posted) + 1}"
        self.posted.append(kwargs)
        if not kwargs.get("thread_ts"):
            self.timeline[(kwargs["channel"], kwargs["ts"])] = as_parent(kwargs)
        return {"ok": True, "ts": kwargs["ts"]}

    def chat_update(self, **kwargs):
        self.updated.append(kwargs)
        message = self.timeline.get((kwargs.get("channel"), kwargs.get("ts")))
        if message is not None:
            message.update(text=kwargs.get("text"), blocks=kwargs.get("blocks"))
        return {"ok": True}

    def chat_delete(self, **kwargs):
        self.deleted.append(kwargs)
        self.timeline.pop((kwargs.get("channel"), kwargs.get("ts")), None)
        return {"ok": True}

    def say(self, channel: str = "D1", text: str = "", *, user: str = "U1", files: list[dict] | None = None,
            thread: str | None = None, ago: float = 0.0) -> dict:
        """Odam chatga yozdi: thread'dan tashqarida bo'lsa - chat tarixiga. `ts` - Slack'dagidek epoch soniya
        (`ago` soniya oldin; `meeting.AUDIO_PENDING_SEC`). Qaytaradi: Bolt `message` hodisasi."""
        self.said += 1
        event = {"type": "message", "channel_type": "im", "channel": channel, "user": user, "text": text,
                 "ts": f"{int(time.time() - ago)}.{self.said:06d}"}
        if files:
            event["files"] = list(files)
        if thread:
            event["thread_ts"] = thread
        else:
            self.timeline[(channel, event["ts"])] = event
        return event

    def visible(self) -> list[dict]:
        """Chatda QOLGAN xabarlar: jarayon xabari (`intake.Progress`) natija chiqqach o'chiriladi."""
        gone = {d["ts"] for d in self.deleted}
        return [m for m in self.posted if m["ts"] not in gone]

    def files_info(self, file):
        return {"file": self.files[file]}

    def files_upload_v2(self, **kwargs):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploaded.append(kwargs)
        return {"ok": True}

    def views_publish(self, **kwargs):
        self.published.append(kwargs)
        return {"ok": True}

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)
        return {"ok": True}

    def conversations_history(self, channel, limit=100, **kwargs):
        """YANGISI birinchi, `limit` tagacha (Slack kabi)."""
        self.history_reads.append({"channel": channel, "limit": limit, **kwargs})
        if isinstance(self.history_error, Exception):
            raise self.history_error
        if self.history_error is not None:
            return self.history_error
        if channel in self.history:
            return {"ok": True, "messages": list(self.history[channel])[:limit]}
        return {"ok": True,
                "messages": [m for (ch, _), m in reversed(self.timeline.items()) if ch == channel][:limit]}

    def conversations_replies(self, channel, ts, **kwargs):
        return {"messages": [self.parents[ts]] if ts in self.parents else []}


def setup(monkeypatch, users_file, *, seconds: float = 64.0) -> list[str]:
    """Slack hisobi - ADMIN (actor 1), yuklab olinadigan fayl - sintetik ADTS.
    Qaytaradi: yuklab olingan manzillar ro'yxati."""
    store = UserStore.from_file(users_file)
    monkeypatch.setattr(deps, "get_directory", lambda: Directory(deps.get_identity_store(), store))
    monkeypatch.setattr(settings, "slack_actor_id", "1", raising=False)
    enable(monkeypatch)
    calls: list[str] = []

    def download(url, dest, limit):
        calls.append(url)
        data = adts_bytes(seconds)
        dest.write_bytes(data)
        return len(data), sha(data), data[:16]

    monkeypatch.setattr(transcribe, "download", download)
    return calls


def question_of(client: "FakeSlack", file_id: str) -> dict[str, Any]:
    """Shu audioga Barno'ning til savoli («Audio qaysi tilda?», `render.lang_question`)."""
    return next(m for m in reversed(client.posted) if render.lang_marked(m) == file_id)


def choose_language(client: "FakeSlack", question: dict[str, Any], lang: str, rt, *, user: str = "U1") -> None:
    """Odam til savolidagi tugmani bosdi (`meeting.on_action` -> `meeting.start`); navbat qo'lda (`drive`)."""
    from app.slack import meeting

    [button] = [e for e in elements(question) if e["action_id"] == f"barno_lang_{lang}"]
    message = {"ts": question["ts"], **({"thread_ts": question["thread_ts"]} if question.get("thread_ts") else {})}
    meeting.on_action(client, {"actions": [button], "channel": {"id": question["channel"]}, "user": {"id": user},
                               "message": message}, sleep=drive(rt))


def send_audio(client: "FakeSlack", event: dict[str, Any], rt, lang: str = "uz", *, user: str = "U1") -> None:
    """Odam audio yubordi (Bolt yo'li): til savoli (`meeting.acknowledge`), so'ng har fayl uchun tilni tanlaydi.
    Fayl `files.info` uchun soxta klientga ham qo'shiladi."""
    from app.slack import meeting

    meeting.acknowledge(client, event)
    for file in transcribe.audio_files(event):
        client.files.setdefault(file["id"], file)
        choose_language(client, question_of(client, file["id"]), lang, rt, user=user)


def drive(rt):
    """`sleep` o'rniga: yig'ilish navbatini oxirigacha yuritadi (fon ishchisi yo'q)."""
    return lambda _sec: run_all(rt)


def shown(message: dict[str, Any]) -> str:
    """Xabarda ko'rinadigan matn: section va kontekst bloklari (bo'lmasa `text`)."""
    parts = []
    for block in message.get("blocks") or []:
        if block.get("type") in ("section", "header"):
            parts.append(block["text"]["text"])
        elif block.get("type") == "context":
            parts.extend(e.get("text", "") for e in block["elements"])
    return "\n".join(parts) if parts else message.get("text", "")


def card(client: FakeSlack) -> dict[str, Any]:
    """Oxirgi "Qisqa xulosa" xabari - tugmalar bloki yig'ilish belgisini olib yuradi."""
    return next(m for m in reversed(client.posted)
                if any(b.get("type") == "actions" and str(b.get("block_id", "")).startswith(render.MARK)
                       for b in m.get("blocks") or []))


def elements(message: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for b in message.get("blocks") or [] if b.get("type") == "actions" for e in b["elements"]]


def as_parent(message: dict[str, Any]) -> dict[str, Any]:
    """Yuborilgan xabar - `conversations.replies` qaytaradigan shaklda (bot yozgan)."""
    return {**message, "bot_id": "B1", "user": BOT_USER}

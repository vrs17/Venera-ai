"""Slack testlari uchun soxtalar: `WebClient`, Slack hisobi va audio fayli. Tarmoqqa chiqmaydi."""

from __future__ import annotations

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
    """`WebClient` ning ishlatiladigan metodlari: yuborilgan, yangilangan va yuklangan narsalar yoziladi."""

    def __init__(self, files: dict[str, dict] | None = None, parents: dict[str, dict] | None = None,
                 upload_error: Exception | None = None) -> None:
        self.posted: list[dict] = []
        self.updated: list[dict] = []
        self.uploaded: list[dict] = []
        self.published: list[dict] = []
        self.files = files or {}
        self.parents = parents or {}
        self.upload_error = upload_error

    def chat_postMessage(self, **kwargs):
        kwargs["ts"] = f"100.{len(self.posted) + 1}"
        self.posted.append(kwargs)
        return {"ok": True, "ts": kwargs["ts"]}

    def chat_update(self, **kwargs):
        self.updated.append(kwargs)
        return {"ok": True}

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

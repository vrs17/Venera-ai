"""Slack shaxsiy chati -> arxiv (`services/archive.py`): odam yozgan matn va audio bo'lmagan fayllar.

Ega talabi (2026-11-05): Slack'dan kelgan hech narsa yo'qolmasin. Audio fayl va Slack ovozli xabari
yig'ilish bo'ladi (`meeting.py`, audiosi o'sha yerda saqlanadi) - bu yerda yozilmaydi. Matn
NIQOBLANADI (`tg_groups.mask_text` - telefon, email, karta, tokenlar), Telegram guruh matni kabi.
Thread'dagi savol ham yoziladi (yig'ilish savollari jadvalida ham bor; bu yerda - kim, qachon,
qaysi thread'da yozgani bilan). Faqat yangi xabar: tahrir va o'chirish hodisalari yozilmaydi.
"""

from __future__ import annotations

import logging
import tempfile

from pathlib import Path
from typing import Any

from ..services import archive
from ..services.tg_groups import mask_text
from . import transcribe

log = logging.getLogger(__name__)


def wants(event: dict[str, Any]) -> bool:
    """Odamning shaxsiy chatdagi yangi xabari (matn yoki fayl bilan)."""
    return (event.get("channel_type") == "im" and not event.get("bot_id") and bool(event.get("user"))
            and event.get("subtype") in (None, "file_share"))


def record(event: dict[str, Any]) -> None:
    """Xabar matni va audio bo'lmagan fayllari - arxivga. Xato otmaydi."""
    try:
        common = {"chat": event.get("channel"), "user": event.get("user"), "message": event.get("ts")}
        thread = event.get("thread_ts")
        meta = {"thread": thread} if thread and thread != event.get("ts") else None
        text = str(event.get("text") or "").strip()
        if text:
            archive.record("slack", "in", "text", text=mask_text(text), meta=meta, **common)
        for file in event.get("files") or []:
            if isinstance(file, dict) and not transcribe.is_audio(file):
                _file(file, meta, common)
    except Exception:  # noqa: BLE001 - arxiv asosiy ishni to'xtatmasin
        log.exception("Slack arxivi: xabar yozilmadi")


def _file(file: dict[str, Any], meta: dict[str, Any] | None, common: dict[str, Any]) -> None:
    fields = {**common, "name": str(file.get("name") or file.get("title") or file.get("id") or "fayl"),
              "mime": str(file.get("mimetype") or ""), "meta": {**(meta or {}), "file": file.get("id")}}
    size = int(file.get("size") or 0)
    limit = archive.get().max_bytes
    url = file.get("url_private_download") or file.get("url_private")
    if size > limit:
        archive.record("slack", "in", "file", status="too_large", size=size, **fields)
        return
    if not url:
        archive.record("slack", "in", "file", status="failed", size=size or None, **fields)
        return
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file"
            transcribe.download(url, path, limit)
            data = path.read_bytes()
    except Exception as exc:  # noqa: BLE001 - `transcribe.Problem` va tarmoq xatolari
        log.warning("Slack arxivi: fayl yuklab olinmadi (%s)", type(exc).__name__)
        archive.record("slack", "in", "file", status="failed", size=size or None, **fields)
        return
    archive.record("slack", "in", "file", data=data, **fields)

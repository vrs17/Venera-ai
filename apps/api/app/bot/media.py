"""Telegram xabaridagi fayl -> arxiv (`services/archive.py`): shaxsiy chat va ro'yxatdagi guruhlar.

NIMA: rasm (eng katta o'lchami), fayl (hujjat), ovozli xabar, audio, video, dumaloq video, GIF -
Telegram xabari bitta fayl olib keladi. Izoh (caption) NIQOBLANIB yoziladi (`tg_groups.mask_text`).
Ovozli SAVOL audiosini `runner._voice` o'zi yozadi: u faylni baribir yuklab oladi, ikkinchi marta
so'ralmaydi.

NIMA EMAS: shaxsiy chatdagi video - arxivga yozilmaydi: ulangan odamniki Plaud yozuvi bo'ladi (2026-11-17:
audiosi ajratib olinadi, video saqlanmaydi), qolgani o'chiriladi (`runner.is_video`); Plaud yozuvi -
yig'ilish bo'ladi (audiosi o'sha yerda saqlanadi); stiker - umumiy to'plamdan, odamning ma'lumoti emas.

Telegram botga 20 MB dan katta faylni bermaydi (`getFile`): bunday fayl qatori `too_large` bilan
yoziladi (kim, qachon, nomi, hajmi). Yuklab bo'lmasa - `failed`. Xato hech qachon otilmaydi.
"""

from __future__ import annotations

import logging

from typing import Any

from ..services import archive
from ..services.tg_groups import mask_text

log = logging.getLogger(__name__)

#: Bot API `getFile` chegarasi.
BOT_DOWNLOAD_LIMIT = 20 * 1024 * 1024
#: Rasmdan boshqa fayl maydonlari (rasm - o'lchamlar ro'yxati, alohida).
_KINDS = ("voice", "audio", "document", "video", "video_note", "animation")


def file_of(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Xabardagi fayl: {kind, file_id, name, mime, size, duration} yoki `None`."""
    number = msg.get("message_id")
    photos = msg.get("photo")
    if isinstance(photos, list) and photos and isinstance(photos[-1], dict):
        best = photos[-1]                                    # Telegram o'lchamlarni o'sib boruvchi beradi
        if isinstance(best.get("file_id"), str):
            return {"kind": "photo", "file_id": best["file_id"], "name": f"photo-{number}.jpg",
                    "mime": "image/jpeg", "size": int(best.get("file_size") or 0), "duration": None}
    for kind in _KINDS:
        item = msg.get(kind)
        if isinstance(item, dict) and isinstance(item.get("file_id"), str):
            return {"kind": kind, "file_id": item["file_id"],
                    "name": str(item.get("file_name") or "").strip() or f"{kind}-{number}",
                    "mime": str(item.get("mime_type") or ""), "size": int(item.get("file_size") or 0),
                    "duration": item.get("duration")}
    return None


def keep(api: Any, msg: dict[str, Any], *, channel: str, actor: int | None = None) -> str | None:
    """Xabardagi faylni yuklab arxivga yozadi -> arxiv id (fayl yo'q bo'lsa `None`). Xato otmaydi."""
    found = file_of(msg)
    if found is None:
        return None
    caption = str(msg.get("caption") or "").strip()
    meta = {key: value for key, value in (("duration", found["duration"]), ("date", msg.get("date")))
            if value is not None}
    common: dict[str, Any] = {
        "chat": (msg.get("chat") or {}).get("id"), "user": (msg.get("from") or {}).get("id"), "actor": actor,
        "message": msg.get("message_id"), "text": mask_text(caption) if caption else None,
        "name": found["name"], "mime": found["mime"], "meta": meta or None,
    }
    limit = min(archive.get().max_bytes, BOT_DOWNLOAD_LIMIT)
    if found["size"] > limit:
        return archive.record(channel, "in", found["kind"], status="too_large", size=found["size"], **common)
    try:
        info = api.get_file(found["file_id"])
        data = api.download(str(info.get("file_path") or ""), limit=limit)
    except Exception as exc:  # noqa: BLE001 - arxiv asosiy ishni to'xtatmasin
        log.warning("Telegram arxiv: %s yuklab olinmadi (%s)", found["kind"], type(exc).__name__)
        return archive.record(channel, "in", found["kind"], status="failed", size=found["size"] or None, **common)
    return archive.record(channel, "in", found["kind"], data=data, **common)

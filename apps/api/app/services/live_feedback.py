"""Jonli suhbatdan keyingi baho (`/barno` rahmat sahifasi) - `data/live/feedback.jsonl` ga, qatorma-qator.

Nega fayl: baholar kam (suhbat boshiga bitta), o'qish - `jq` yoki admin skripti bilan; alohida jadval va migratsiya
bunga ortiqcha. Fayl va papka faqat xizmat egasiga ochiq (600 / 700): izohda odam yozgan erkin matn bor.
Suhbatning O'ZI (ovoz, transkript) bizda saqlanmaydi - u Speko panelida, `sessionId` shu bilan bog'laydi.
"""

from __future__ import annotations

import json
import os
import threading
import time

from pathlib import Path
from typing import Any

from ..core.config import settings
from ..schemas.auth import AuthUser
from ..schemas.live import LiveFeedbackRequest

_lock = threading.Lock()


def save(user: AuthUser, feedback: LiveFeedbackRequest, *, now: float | None = None) -> dict[str, Any]:
    """Bahoni yozadi va yozilgan qatorni qaytaradi."""
    record = {
        "ts": int(now if now is not None else time.time()),
        "actorId": user.actorId,
        "sessionId": feedback.sessionId,
        "persona": feedback.persona,
        "rating": feedback.rating,
        "reasons": list(dict.fromkeys(feedback.reasons)),
        "comment": " ".join(feedback.comment.split()),
        "durationSec": feedback.durationSec,
    }
    path = Path(settings.live_feedback_file)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record

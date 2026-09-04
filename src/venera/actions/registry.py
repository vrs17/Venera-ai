"""Intent -> bajaruvchi yo'naltirish."""

from __future__ import annotations

import logging

from ..nlu.intents import Intent, IntentName
from .base import ActionContext, ActionResult
from .handlers import HANDLERS

log = logging.getLogger(__name__)

# Javob AYTILGANDAN KEYIN bajariladigan intentlar: aks holda foydalanuvchi
# javobni eshitmay qoladi (ekran qulflansa ovoz ham uziladi).
DEFERRED = {IntentName.LOCK_SCREEN}


def execute(intent: Intent, ctx: ActionContext) -> ActionResult:
    """Intentni bajaradi. Hech qachon exception tashlamaydi."""
    handler = HANDLERS.get(intent.name, HANDLERS[IntentName.UNKNOWN])
    try:
        result = handler(intent, ctx)
    except Exception as exc:  # noqa: BLE001 - bitta buyruq ilovani yiqitmasin
        log.exception("Harakat bajarilmadi: %s", intent.describe())
        return ActionResult.failure(ctx.phrases.get("action_failed"), detail=str(exc))

    if result.ok and intent.name not in (IntentName.REPEAT,):
        ctx.last_reply = result.spoken
    log.info("%s -> %s (%s)", intent.describe(), result.spoken, "ok" if result.ok else "xato")
    return result


def is_deferred(intent: Intent) -> bool:
    """True bo'lsa: avval javob aytiladi, keyin harakat bajariladi."""
    return intent.name in DEFERRED

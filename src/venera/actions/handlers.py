"""Har bir intent uchun bajaruvchi.

Bu funksiyalar bloklaydi (ShellExecute, COM, fayl yozish), shuning uchun
orchestrator ularni `run_in_executor` orqali chaqiradi.
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import quote_plus

from ..nlu.intents import Intent, IntentName
from .base import ActionContext, ActionResult

log = logging.getLogger(__name__)


def open_app(intent: Intent, ctx: ActionContext) -> ActionResult:
    entry, score = ctx.catalog.find(intent.app)
    if entry is None:
        return ActionResult.failure(
            ctx.phrases.get("open_app_fail", app=intent.app or "Dastur"),
            detail=f"eng yaqin ball {score:.0f}",
        )
    if ctx.adapter.launch(list(entry.targets)):
        return ActionResult(ctx.phrases.get("open_app_ok", app=entry.name))
    return ActionResult.failure(
        ctx.phrases.get("open_app_fail", app=entry.name),
        detail=f"maqsadlar ishlamadi: {entry.targets}",
    )


def open_url(intent: Intent, ctx: ActionContext) -> ActionResult:
    if ctx.adapter.open_url(intent.url):
        return ActionResult(ctx.phrases.get("open_url_ok"))
    return ActionResult.failure(ctx.phrases.get("action_failed"), detail=intent.url)


def web_search(intent: Intent, ctx: ActionContext) -> ActionResult:
    query = intent.query.strip()
    if not query:
        return ActionResult.failure(ctx.phrases.get("unknown"))
    url = ctx.config.actions.search_url.format(query=quote_plus(query))
    if ctx.adapter.open_url(url):
        return ActionResult(ctx.phrases.get("web_search_ok", query=query))
    return ActionResult.failure(ctx.phrases.get("action_failed"), detail=url)


def volume_set(intent: Intent, ctx: ActionContext) -> ActionResult:
    if ctx.adapter.set_volume(intent.level):
        return ActionResult(ctx.phrases.get("volume_set_ok", level=intent.level))
    return ActionResult.failure(ctx.phrases.get("volume_fail"))


def _volume_step(ctx: ActionContext, direction: int) -> ActionResult:
    current = ctx.adapter.get_volume()
    if current is None:
        return ActionResult.failure(ctx.phrases.get("volume_fail"))
    step = ctx.config.actions.volume_step * direction
    target = max(0, min(100, current + step))
    if not ctx.adapter.set_volume(target):
        return ActionResult.failure(ctx.phrases.get("volume_fail"))
    key = "volume_up_ok" if direction > 0 else "volume_down_ok"
    return ActionResult(ctx.phrases.get(key, level=target))


def volume_up(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    return _volume_step(ctx, +1)


def volume_down(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    return _volume_step(ctx, -1)


def mute(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    if ctx.adapter.set_mute(True):
        return ActionResult(ctx.phrases.get("mute_ok"))
    return ActionResult.failure(ctx.phrases.get("volume_fail"))


def unmute(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    if ctx.adapter.set_mute(False):
        return ActionResult(ctx.phrases.get("unmute_ok"))
    return ActionResult.failure(ctx.phrases.get("volume_fail"))


def lock_screen(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    # Javob ekran qulflanishidan OLDIN aytilishi kerak, shuning uchun natija
    # qaytariladi va qulflash orchestrator tomonidan javobdan keyin bajariladi.
    if ctx.adapter.lock_workstation():
        return ActionResult(ctx.phrases.get("lock_ok"))
    return ActionResult.failure(ctx.phrases.get("action_failed"))


def screenshot(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = ctx.screenshot_dir() / f"venera-{stamp}.png"
    saved = ctx.adapter.screenshot(destination)
    if saved is not None:
        return ActionResult(ctx.phrases.get("screenshot_ok"), detail=str(saved))
    return ActionResult.failure(ctx.phrases.get("screenshot_fail"))


def tell_time(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    now = datetime.now()
    return ActionResult(ctx.phrases.get("time_ok", time=ctx.phrases.format_time(now)))


def tell_date(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    now = datetime.now()
    return ActionResult(ctx.phrases.get("date_ok", date=ctx.phrases.format_date(now)))


def cancel(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    return ActionResult(ctx.phrases.get("cancel_ok"))


def repeat(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    if ctx.last_reply:
        return ActionResult(ctx.last_reply)
    return ActionResult(ctx.phrases.get("repeat_none"))


def help_(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    return ActionResult(ctx.phrases.get("help_ok"))


def tell_version(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    from .. import __version__

    return ActionResult(ctx.phrases.get("version_ok", version=__version__))


def unknown(intent: Intent, ctx: ActionContext) -> ActionResult:  # noqa: ARG001
    return ActionResult.failure(ctx.phrases.get("unknown"))


HANDLERS = {
    IntentName.OPEN_APP: open_app,
    IntentName.OPEN_URL: open_url,
    IntentName.WEB_SEARCH: web_search,
    IntentName.VOLUME_SET: volume_set,
    IntentName.VOLUME_UP: volume_up,
    IntentName.VOLUME_DOWN: volume_down,
    IntentName.MUTE: mute,
    IntentName.UNMUTE: unmute,
    IntentName.LOCK_SCREEN: lock_screen,
    IntentName.SCREENSHOT: screenshot,
    IntentName.TIME: tell_time,
    IntentName.DATE: tell_date,
    IntentName.CANCEL: cancel,
    IntentName.REPEAT: repeat,
    IntentName.HELP: help_,
    IntentName.VERSION: tell_version,
    IntentName.UNKNOWN: unknown,
}

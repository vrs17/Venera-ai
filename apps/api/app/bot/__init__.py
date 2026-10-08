"""Telegram bot - Venera'ning uchinchi klienti (veb ilova, mini app, bot).

Odam botga oddiy xabar yoki ovozli xabar yozadi va javobni MATN bilan oladi
(ovoz sintezi yo'q). Imkoniyatlari veb chat bilan bir xil: HRM/CRM savollari,
yozuv amalini tasdiqlash, ariza fayli, manba hujjati, suhbatlar tarixi.

NEGA API JARAYONI ICHIDA, alohida xizmat emas. Bot `api/v1/chat.py` dagi
AYNI klientlarni ishlatadi: CRM sessiyasi va foydalanuvchi ulanishlari
`refresh_token` ni rotatsiya qiladi (ikki nusxa bir-birini bekor qilardi),
yuqoridagi xizmat va STT navbatlari esa umumiy bo'lishi kerak.

XABAR QANDAY KELADI - `runner.py` boshidagi izohga qara. Jonli tizimda
WEBHOOK (`TELEGRAM_MODE=webhook`): bitta tokenni boshqa muhitdagi nusxa ham
`getUpdates` bilan o'qiganda xabarlar bo'linib ketgan edi, webhook esa
buning oldini oladi. `/api/v1/telegram/webhook` nginx `/api/` orqali o'tadi
- nginx'ga tegilmagan. Bitta xost ichida ikkinchi nusxa botni ishga
tushirmasligi uchun fayl qulfi ham bor.

Kimning nomidan javob berish - `services/telegram_links.py` (ulanish faqat
mini app orqali, `api/v1/telegram.py`).
"""

from __future__ import annotations

import logging
import threading

from typing import Any

from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services.integrations.telegram import TelegramApi, TelegramError, webhook_secret as _secret
from ..services.telegram_links import LinkStore

log = logging.getLogger(__name__)

#: Bot API klienti va ulanishlar ombori - endpoint va bot BITTA nusxani
#: ishlatadi. Testlar ularni almashtiradi (`conftest.py`).
api = TelegramApi(settings.telegram_bot_token)
links = LinkStore(settings.telegram_links_file, ttl_days=settings.telegram_link_days)

_bot = None
_lock_file = None
_state = {"note": ""}


def start() -> None:
    """So'rov ipini ishga tushiradi - token bor, yoqilgan va qulf olinsa."""
    global _bot, _lock_file
    if _bot is not None:
        return
    if not (settings.telegram_bot_enabled and api.configured):
        _state["note"] = "o'chiq" if api.configured else "token yo'q"
        log.info("Telegram bot ishga tushirilmadi: %s", _state["note"])
        return
    _lock_file = _take_lock()
    if _lock_file is None:
        _state["note"] = "boshqa jarayon botni o'qiyapti (qulf band)"
        log.warning("Telegram bot ishga tushirilmadi: %s", _state["note"])
        return

    from ..api.deps import get_directory
    from .runner import VeneraBot

    # `get_directory`: SSO bilan kirganlar (`identities.json`) + `users.yaml`.
    # `sync_commands=True` - buyruqlar menyusi FAQAT shu yerda (jonli ishga
    # tushish) yoziladi va faqat Telegram'dagisi farq qilsa (`sync_menu`).
    store = _group_store()
    # Qaysi guruh o'qiladi - `.env` + rahbar botda qilgan qarorlar (`GroupRegistry`).
    # Guruh yordamchisi, brif va guruhlar menyusi BITTA ro'yxatdan foydalanadi.
    registry = _registry(store)
    briefs = _briefs(store, registry)
    _bot = VeneraBot(api, links, users=get_directory, webapp_url=settings.telegram_webapp_url,
                     workers=settings.telegram_workers, mode=settings.telegram_mode,
                     webhook_url=settings.telegram_webhook_url, webhook_secret=webhook_secret(),
                     beta_url=settings.telegram_webapp_beta_url, sync_commands=True,
                     groups=_groups(store, registry), briefs=briefs, admin=_admin(store, registry))
    _bot.start()
    # Fonda: guruhlarning kunlik hodisalarini oldindan ajratish - uzun davrli
    # brif soniyalarda ochilsin.
    briefs.start()
    _state["note"] = ""


def _group_store():
    """Guruh xabarlari ombori - guruh yordamchisi va brif uchun BITTA."""
    from ..services.tg_groups import GroupStore

    return GroupStore(settings.telegram_groups_db, days=settings.telegram_group_days)


def _registry(store):
    from ..services.tg_groups import GroupRegistry

    return GroupRegistry(store)


def _admin(store, registry):
    """Guruhlarni botda boshqarish (`group_admin.py`) - rahbar o'zi qo'shadi."""
    from .group_admin import GroupAdmin

    return GroupAdmin(api, registry, store, days=settings.telegram_group_days)


def _writer():
    from ..core.config import ollama_key_now
    from ..services.integrations.ollama import OllamaChat

    return OllamaChat(settings.ollama_base_url, ollama_key_now,
                      settings.telegram_group_model or settings.ollama_model)


def _groups(store, registry):
    """Ro'yxatdagi guruhlar yordamchisi (`groups.py`). Ro'yxat bo'sh bo'lsa
    ham yaratiladi - guruh keyin (botda yoki `.env` da), qayta ishga
    tushirmasdan qo'shiladi."""
    from .groups import GroupAssistant

    return GroupAssistant(api, store, _writer(), allowed=registry.allowed_ids)


def _briefs(store, registry):
    """Rahbariyat brifi (`briefs.py`). O'z `OllamaChat` i - o'z navbati bilan:
    fondagi tahlil guruhdagi `/summary` ni kuttirmasin. Vazifalarning CRM
    holati - Venera AI agentidan (`crm_status.py`), agent sozlangan bo'lsa."""
    from .briefs import BriefEngine, BriefService
    from .crm_status import CrmChecker, agent_ask

    writer = _writer()
    crm = CrmChecker(agent_ask, writer=writer) if settings.hrm_assistant_base_url else None
    # Guruh turi (🛠 support / 📁 loyiha) - brif kartasi va CRM shunga qarab.
    engine = BriefEngine(store, writer, groups=registry.allowed_ids, kind_of=registry.kind_of)
    return BriefService(api, engine, crm=crm, groups=registry.allowed_ids, manage=True)


def stop() -> None:
    global _bot
    if _bot is not None:
        _bot.stop()
        _bot = None


def webhook_secret() -> str:
    """Webhook sarlavhasi uchun sir (`SECRET_KEY` + bot tokenidan)."""
    return _secret(settings.telegram_bot_token, settings.secret_key)


def feed(update: dict[str, Any]) -> bool:
    """Webhook'dan kelgan yangilanishni botga beradi. `False` - bot webhook
    rejimida ishlamayapti (endpoint 503 qaytaradi, Telegram keyin qayta
    yuboradi)."""
    current = _bot
    if current is None or current.mode != "webhook":
        return False
    current.accept(update)
    return True


def username() -> str:
    return _bot.username if _bot is not None else ""


def status() -> dict[str, Any]:
    """`/api/health/detail` uchun: holat va SONLAR. Token, Telegram id va
    ismlar YO'Q."""
    out: dict[str, Any] = {
        "configured": api.configured,
        "enabled": settings.telegram_bot_enabled,
        "linked": links.count(),
    }
    if _bot is not None:
        out.update(_bot.status())
    else:
        out["running"] = False
        out["note"] = _state["note"] or None
    return out


def welcome(tg_id: int, user: AuthUser) -> None:
    """Yangi ulanish haqida botdan xabar - FONDA: HTTP javobi kutmasin.

    Odam botni hech ochmagan bo'lsa Telegram 403 beradi - bu normal, mini
    app baribir botdan ochilgan bo'ladi.
    """
    if not api.configured:
        return
    from .runner import welcome_text

    def run() -> None:
        try:
            api.send_message(tg_id, welcome_text(user))
        except TelegramError as exc:
            log.info("Telegram: ulanish xabari yuborilmadi (%s): %s", user.actorId, exc)

    threading.Thread(target=run, name="tg-welcome", daemon=True).start()


def _take_lock():
    """`data/telegram/poll.lock` - boshqa jarayon ushlab tursa `None`."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows: qulfsiz
        return object()
    path = settings.telegram_links_file.parent / "poll.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a")  # noqa: SIM115 - jarayon umri davomida ochiq
    except OSError as exc:
        log.warning("Telegram bot qulfi ochilmadi (%s): %s", path, exc)
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle

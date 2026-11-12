"""Slack hisobini Barno hisobiga ulash - «Connect Barno AI account» (2026-11-12, ega qarori).

OQIM (Slack'dagi Claude agentidagi kabi):
  1. Ulanmagan odam Barno AI ga yozadi (matn, audio, tugma) -> Barno ishni bajarmaydi, faqat o'ziga
     ko'rinadigan xabar yuboradi: "Barno AI hisobingizni ulang" va «Connect Barno AI account» tugmasi.
  2. Tugma - havola: `<SSO_APP_URL>/link/slack?t=<chipta>`. Brauzerda Barno ochiladi; odam kirmagan bo'lsa
     kirish sahifasi (BRB-Tech ID yoki login + parol), kirgach shu sahifaga qaytadi.
  3. Sahifa KIM ulanayotganini ko'rsatadi va TASDIQ so'raydi; tasdiqlangach `POST /api/v1/slack/link`
     chiptani yoqadi va ulanishni yozadi (`services/slack_links.py`). Barno Slack'da "ulandi" deb yozadi.
  4. Odam xabarini qayta yuboradi - endi u o'z hisobida ishlaydi.

CHIPTA - tasodifiy, bir martalik, `TICKET_TTL` yashaydi, faqat xotirada (Slack ilovasi API jarayonining
ichida ishlaydi - `app/slack/__init__.py`; jarayon qayta ishga tushsa odam tugmani yana oladi). Chipta ichida
Slack id'lari turadi va ular FAQAT Slack yetkazgan hodisadan olingan: URL'da id yo'q, uni hech kim
o'zgartira olmaydi.

NEGA TASDIQ SAHIFASI. Havolani boshqa odamga yuborib bo'ladi: hamkasb uni ochsa va brauzerida Barno
sessiyasi bo'lsa, tasdiqsiz ulash YUBORUVCHINING Slack'ini HAMKASBNING hisobiga bog'lab qo'yardi - uning
yozuvlari va (keyinroq) CRM javoblari begona qo'lga o'tardi. Shuning uchun kirishning o'zi hech narsani
ulamaydi: sahifa "Slack'dagi <ism> sizning hisobingizga ulanadi" deb aniq yozadi va tugma bosilishini kutadi.
Kirishni brauzerga bog'laydigan cookie (`api/v1/auth.py`) bu yerda yordam bermaydi - u Slack'ni brauzerga
bog'lamaydi.

MAJBURIYMI. `SLACK_LINK_REQUIRED` (default yoqiq) VA `SSO_APP_URL` to'ldirilgan bo'lsa - ha (havola uchun
manzil kerak; Slack kodida uni olish uchun HTTP so'rov yo'q). Aks holda Slack eskicha, umumiy hisobda
(`SLACK_ACTOR_ID`) ishlaydi.
"""

from __future__ import annotations

import logging
import threading
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..schemas.auth import AuthUser
from ..services import admin_users
from ..services.meetings.intake import Problem
from ..services.link_tickets import TicketStore
from ..services.slack_links import LinkStore
from . import render

log = logging.getLogger(__name__)

#: Chipta muddati: kirish sahifasi, parol, ikki bosqichli tasdiq - yarim soat yetarli.
TICKET_TTL = 1800.0
#: Tugmalar. Hammasi `barno_` bilan boshlanadi - Bolt faqat shu naqshni tinglaydi (`__init__.py`).
LINK_ACTION = "barno_link"          # havola-tugma (brauzerni Slack o'zi ochadi; bizga faqat `ack` kerak)
CONNECT_ACTION = "barno_connect"    # "Home" varag'idagi tugma -> chatga ulash xabari
UNLINK_ACTION = "barno_unlink"      # "Home" varag'idagi «Uzish»
BUTTON = "Connect Barno AI account"
#: Ulash xabari bitta odamga bundan tez takrorlanmaydi (bir xabarda bir nechta audio, ketma-ket yozish).
OFFER_EVERY = 20.0

OFFER_HEAD = "*Barno AI hisobingizni ulang*"
OFFER_TEXT = ("So'rovlaringiz bilan ishlashim uchun kerak. Bir marta ulang, keyin xabaringizni qayta yuboring.")
OFFER_EXPIRED = "Ulanish muddati tugagan - hisobingizni qaytadan ulang, keyin xabaringizni qayta yuboring."
OFFER_NOTE = "Buni faqat siz ko'rasiz. Istalgan payt Barno AI'ning «Home» varag'idan uzishingiz mumkin."
BLOCKED = "Barno hisobingiz bloklangan. Administratorga murojaat qiling."


class NotLinked(Problem):
    """Slack odami Barno hisobiga ulanmagan (`state`: `none` | `expired`). Chaqiruvchi ishni bajarmaydi va
    ulash xabarini yuboradi (`offer`)."""

    def __init__(self, state: str = "none") -> None:
        super().__init__("Barno AI hisobingiz ulanmagan.")
        self.state = state


@dataclass(frozen=True)
class Ticket:
    team_id: str
    user_id: str
    #: Ulangach "ulandi" xabari shu chatga yoziladi (bo'sh bo'lsa - odamning o'ziga).
    channel: str
    #: Slack'dagi ism - tasdiq sahifasi uchun (bo'lmasa bo'sh; `users:read` ruxsati kerak).
    name: str
    created: float


TICKETS: TicketStore[Ticket] = TicketStore(TICKET_TTL)
_offered: dict[str, float] = {}
_offered_lock = threading.Lock()
_store: LinkStore | None = None
_store_key: tuple[str, float] | None = None
_store_lock = threading.Lock()


# --- sozlama ---------------------------------------------------------------------------------


def app_url() -> str:
    """Barno'ning tashqi manzili - ulash havolasi shundan yasaladi."""
    return (settings.sso_app_url or "").strip().rstrip("/")


def required() -> bool:
    """Slack'da shaxsiy hisob majburiymi (modul izohi)."""
    return bool(settings.slack_link_required) and bool(app_url())


def store() -> LinkStore:
    """Ulanishlar ombori - sozlama o'zgarsa (testlar) yangisi."""
    global _store, _store_key
    path = Path(settings.slack_links_file)
    days = float(settings.slack_link_days or 30)
    with _store_lock:
        if _store is None or _store_key != (str(path), days):
            _store, _store_key = LinkStore(path, ttl_days=days), (str(path), days)
        return _store


# --- kim ---------------------------------------------------------------------------------------


def person(team_id: str | None, user_id: str | None) -> AuthUser:
    """Slack odamining Barno hisobi - HAR so'rovda qayta tekshiriladi (bot kabi): hisob o'chirilsa yoki
    bloklansa darhol to'xtaydi. Ulanmagan - `NotLinked`."""
    from ..api.deps import get_directory

    links = store()
    link, state = links.lookup(team_id, user_id)
    if link is None:
        raise NotLinked(state)
    stored = get_directory().by_actor_id(link.actor_id)
    if stored is None:
        # Hisob o'chirilgan - ulanish ham kerak emas.
        links.unlink(team_id, user_id, actor_id=link.actor_id)
        raise NotLinked("none")
    verdict = admin_users.access(stored.to_public(), login=getattr(stored, "username", None))
    if verdict.blocked:
        raise Problem(BLOCKED)
    if not links.touch(team_id, user_id, link.actor_id):
        raise NotLinked("none")
    return verdict.user


def linked_name(team_id: str | None, user_id: str | None) -> str | None:
    """Ulangan hisob egasining ismi ("Home" varag'i uchun); ulanmagan - `None`."""
    from ..api.deps import get_directory

    link, _ = store().lookup(team_id, user_id)
    if link is None:
        return None
    stored = get_directory().by_actor_id(link.actor_id)
    if stored is None:
        return None
    public = stored.to_public()
    return public.fullName or public.email


# --- ulash xabari ---------------------------------------------------------------------------------


def new_ticket(team_id: str | None, user_id: str, channel: str | None, *, name: str = "") -> str:
    return TICKETS.new(Ticket(team_id=(team_id or "").strip(), user_id=user_id, channel=channel or "",
                              name=name.strip()[:120], created=time.time()))


def link_url(ticket: str) -> str:
    return f"{app_url()}/link/slack?t={ticket}"


def offer_blocks(url: str, *, state: str = "none") -> list[dict[str, Any]]:
    """Ulash xabari: sarlavha, sabab, havola-tugma va eslatma."""
    text = OFFER_EXPIRED if state == "expired" else OFFER_TEXT
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{OFFER_HEAD}\n{text}"}},
        {"type": "actions", "block_id": "barno:link", "elements": [
            {"type": "button", "action_id": LINK_ACTION, "style": "primary", "url": url,
             "text": {"type": "plain_text", "text": BUTTON}}]},
        render.context(OFFER_NOTE),
    ]


def offer(client: Any, team_id: str | None, user_id: str | None, channel: str | None, *,
          thread: str | None = None, state: str = "none", force: bool = False) -> bool:
    """Odamga ulash xabarini yuboradi: chatda - faqat o'ziga ko'rinadigan (ephemeral), kanal noma'lum
    bo'lsa ("Home" varag'idan) - shaxsiy xabar. `OFFER_EVERY` dan tez takrorlanmaydi (`force` - odam
    tugmani o'zi bosgan). Yuborilsa `True`."""
    if not user_id:
        return False
    key = f"{team_id or ''}:{user_id}"
    now = time.monotonic()
    with _offered_lock:
        if not force and now - _offered.get(key, -OFFER_EVERY) < OFFER_EVERY:
            return False
        _offered[key] = now
        if len(_offered) > 5000:
            _offered.clear()
    url = link_url(new_ticket(team_id, user_id, channel, name=display_name(client, user_id)))
    return _tell(client, user_id, channel, thread, f"{BUTTON}: {url}", offer_blocks(url, state=state))


def _tell(client: Any, user_id: str, channel: str | None, thread: str | None, text: str,
          blocks: list[dict[str, Any]] | None = None) -> bool:
    """Faqat shu odamga: chatda - ephemeral; chat noma'lum yoki u yerga yozib bo'lmasa (`/plaud` Barno
    a'zo bo'lmagan kanalda) - shaxsiy xabar. Havola ichida bir martalik chipta bor - hech qachon hammaga
    ko'rinadigan xabar emas."""
    if channel:
        where = {"thread_ts": thread} if thread else {}
        try:
            client.chat_postEphemeral(channel=channel, user=user_id, text=text, blocks=blocks, **where)
            return True
        except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
            log.info("Slack ephemeral xabar ketmadi (%s), shaxsiy xabarga o'tildi: %s", channel, exc)
    try:
        client.chat_postMessage(channel=user_id, text=text, blocks=blocks)
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack ulash xabari yuborilmadi (%s): %s", user_id, exc)
        return False
    return True


def gate(client: Any, team_id: str | None, user_id: str | None, channel: str | None, *,
         thread: str | None = None, force: bool = False) -> bool:
    """Ish boshlashdan oldingi tekshiruv. Shaxsiy hisob majburiy emas yoki odam ulangan - `True`.
    Ulanmagan - ulash xabari va `False`; hisobi bloklangan - sababi va `False`. `force` - odam tugmani
    yoki buyruqni o'zi bosgan (takror cheklovi yo'q)."""
    if not required():
        return True
    try:
        person(team_id, user_id)
    except NotLinked as exc:
        offer(client, team_id, user_id, channel, thread=thread, state=exc.state, force=force)
        return False
    except Problem as exc:
        if user_id:
            _tell(client, user_id, channel, thread, render.escape(str(exc)))
        return False
    return True


def display_name(client: Any, user_id: str) -> str:
    """Slack'dagi ism - tasdiq sahifasida "kim ulanyapti" uchun. `users:read` ruxsati bo'lmasa yoki xato
    bo'lsa - bo'sh (sahifa ismsiz ham ogohlantiradi)."""
    try:
        found = client.users_info(user=user_id)
    except Exception:  # noqa: BLE001 - ruxsat yo'q, tarmoq, soxta klientda metod yo'q
        return ""
    user = (found or {}).get("user") or {}
    profile = user.get("profile") or {}
    return str(profile.get("display_name") or profile.get("real_name") or user.get("real_name") or "").strip()


# --- tugmalar -----------------------------------------------------------------------------------


def _action(body: dict[str, Any]) -> str:
    return str(((body.get("actions") or [{}])[0]).get("action_id") or "")


def handles(body: dict[str, Any]) -> bool:
    """Shu modulning tugmasimi (`__init__._on_action` dispetcheri)."""
    return _action(body) in (LINK_ACTION, CONNECT_ACTION, UNLINK_ACTION)


def on_action(client: Any, body: dict[str, Any]) -> None:
    """`barno_link` - havola-tugma: brauzerni Slack ochgan, hech narsa qilinmaydi. `barno_connect` -
    "Home" varag'idan ulash xabarini so'rash. `barno_unlink` - uzish."""
    kind = _action(body)
    user_id = (body.get("user") or {}).get("id")
    team_id = team_of(body)
    if not user_id or kind == LINK_ACTION:
        return
    if kind == CONNECT_ACTION:
        offer(client, team_id, user_id, (body.get("channel") or {}).get("id"), force=True)
    elif kind == UNLINK_ACTION:
        removed = store().unlink(team_id, user_id)
        log.info("Slack ulanishi uzildi (%s:%s): %s", team_id, user_id, removed)
        publish_home(client, team_id, user_id)
        try:
            client.chat_postMessage(channel=user_id, text="Barno AI hisobingiz uzildi. Qayta ulash uchun "
                                                          "shu chatga yozing.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Slack uzish xabari yuborilmadi (%s): %s", user_id, exc)


def team_of(payload: dict[str, Any]) -> str:
    """Ish maydoni id'si - hodisa (`team`) yoki tugma (`team.id`, `user.team_id`) yukidan."""
    team = payload.get("team")
    if isinstance(team, dict):
        team = team.get("id")
    # Hodisada `user` - satr (id), tugma yukida - lug'at (`team_id` bilan).
    user = payload.get("user")
    of_user = user.get("team_id") if isinstance(user, dict) else None
    return str(team or payload.get("team_id") or of_user or payload.get("user_team") or "")


# --- "Home" varag'i --------------------------------------------------------------------------------


def home_blocks(team_id: str | None, user_id: str | None) -> list[dict[str, Any]]:
    """Hisob holati - "Home" varag'i uchun: ulangan bo'lsa ism va «Uzish», aks holda ulash tugmasi."""
    if not required() or not user_id:
        return []
    name = linked_name(team_id, user_id)
    if name:
        return [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"✅ Barno AI hisobi ulangan: *{render.escape(name)}*"}},
            {"type": "actions", "block_id": "barno:unlink", "elements": [render.button(
                "Uzish", UNLINK_ACTION, "unlink",
                confirm={"title": {"type": "plain_text", "text": "Hisobni uzish"},
                         "text": {"type": "plain_text", "text": "Barno AI Slack'da hisobingizdan foydalanmaydi. "
                                                                 "Keyin qayta ulash mumkin."},
                         "confirm": {"type": "plain_text", "text": "Uzish"},
                         "deny": {"type": "plain_text", "text": "Bekor qilish"}})]},
        ]
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{OFFER_HEAD}\n{OFFER_TEXT}"}},
        {"type": "actions", "block_id": "barno:connect", "elements": [
            {**render.button(BUTTON, CONNECT_ACTION, "connect"), "style": "primary"}]},
    ]


def publish_home(client: Any, team_id: str | None, user_id: str) -> None:
    """"Home" varag'ini qayta yozadi (ulangach yoki uzilgach holat darhol ko'rinsin). Xato odamga ko'rinmaydi."""
    from . import home

    try:
        client.views_publish(user_id=user_id, view=home.view(team_id, user_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack Home yangilanmadi (%s): %s", user_id, exc)


# --- API tomoni (`api/v1/slack.py`) -----------------------------------------------------------------


def describe(value: str) -> Ticket | None:
    """Chipta ma'lumoti - YOQMASDAN (tasdiq sahifasi)."""
    return TICKETS.peek(value) if value else None


def confirm(value: str, user: AuthUser) -> tuple[Ticket, str] | None:
    """Tasdiqlandi: chipta yoqiladi va Slack hisobi `user` ga ulanadi. Chipta yo'q/eskirgan - `None`.
    Qaytaradi: (chipta, `new` | `refreshed` | `switched`)."""
    ticket = TICKETS.pop(value) if value else None
    if ticket is None:
        return None
    result = store().link(ticket.team_id, ticket.user_id, user.actorId)
    log.info("Slack ulandi: %s:%s -> actor_id %s (%s)", ticket.team_id, ticket.user_id, user.actorId, result)
    return ticket, result


def web_client() -> Any | None:
    """Slack `WebClient` - API so'rovi ichidan Slack'ka yozish uchun (Bolt hodisasi yo'q joyda). Token
    yoki kutubxona bo'lmasa `None`."""
    if not settings.slack_bot_token:
        return None
    try:
        from slack_sdk import WebClient
    except ImportError:
        return None
    from . import SSL

    return WebClient(token=settings.slack_bot_token, ssl=SSL)


def notify_linked(ticket: Ticket, user: AuthUser, *, client: Any | None = None) -> None:
    """Slack'da "ulandi" xabari va yangilangan "Home" varag'i. Eng yaxshi harakat: ulanish allaqachon
    yozilgan, xabar ketmasa ham ishlaydi."""
    client = client or web_client()
    if client is None:
        return
    name = render.escape(user.fullName or user.email)
    text = (f"✅ Barno AI hisobingiz ulandi: *{name}*. Endi audio yuboring yoki savolingizni yozing.\n"
            "Bu siz bo'lmasangiz - Barno AI'ning «Home» varag'ida «Uzish» ni bosing.")
    try:
        client.chat_postMessage(channel=ticket.channel or ticket.user_id, text=text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack 'ulandi' xabari yuborilmadi (%s): %s", ticket.user_id, exc)
    publish_home(client, ticket.team_id, ticket.user_id)

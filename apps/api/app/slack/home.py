"""Slack'da «🎙 Plaud» - chatning ichida (Telegram'dagi tugmaga o'xshab) va "Home" varag'ida.

Slack'da Telegram'dagi kabi doimiy pastki klaviatura yo'q, shuning uchun tugma CHATDA uch
yo'l bilan qo'l ostida turadi:
  * xush kelibsiz xabari - odam Barno chatini ("Messages" varag'i) birinchi marta ochganda
    (chat bo'sh), yo'riqnoma va tugma chatning o'zida;
  * oddiy matnga javob - thread'dan tashqaridagi matnli xabarga (hozircha HR chat yo'q)
    yo'riqnoma va tugma qaytariladi, chatga `TEXT_EVERY` da bir marta;
  * `/plaud` buyrug'i (Bolt `command`, Socket Mode'da ishlaydi) - manifestda slash command
    bo'lsa; bo'lmasa shunchaki chaqirilmaydi.
"Home" varag'i ham bor (`app_home_opened` -> `views.publish`, ruxsat kerak emas).
Tugma bosilganda: chatda - faqat bosgan odamga ko'rinadigan (ephemeral) eslatma, Home'dan -
odamning chatiga xabar (`chat.postMessage` ga foydalanuvchi id'si, `chat:write` bilan DM
ochiladi).

HOZIRCHA audio REJIMSIZ ishlanadi: Slack'dagi Barno faqat audio va thread savoli bilan
ishlaydi, ya'ni Telegram'dagi kabi "bu yozuv" deb belgilash shart emas. Tugma - nom
("Plaud") va yo'riqnoma uchun; Slack'ka HR chat qo'shilganda (ega rejasi, 2026-11-04) aynan
shu tugma Telegram'dagi kabi rejimni yoqadi (`app/bot/plaud.py`).
"""

from __future__ import annotations

import logging
import threading
import time

from typing import Any

from . import render

log = logging.getLogger(__name__)

PLAUD_ACTION = "barno_plaud"
#: Oddiy matnga yo'riqnoma bitta chatga shundan tez takrorlanmaydi (soniya).
TEXT_EVERY = 600.0
_hint_at: dict[str, float] = {}
_hint_lock = threading.Lock()

TAGLINE = "BRB-TECHning foydali, aniq va xavfsiz AI yordamchisi"
FEATURES = (
    "*🎙 Audio → matn* — ovozli xabar yozing yoki audio fayl yuklang (mp3, m4a, aac, wav, ogg; "
    "3 soat yoki 150 MB gacha). Matn shu chatda chiqadi, bir necha kishi gapirgan bo'lsa — kim gapirgani bilan.\n"
    "*📋 Qisqa xulosa* — matndan keyin o'zi keladi: maqsad, asosiy fikrlar, qarorlar, vazifalar, ochiq savollar.\n"
    "*💬 Savol-javob* — xulosa ostidagi thread'da savol yozing: Barno yozuv bo'yicha javob beradi va gap "
    "audioning qaysi daqiqasida aytilganini ko'rsatadi.\n"
    "*✅ Vazifalar* — bitta tugma: kim, nima, qachongacha.\n"
    "*🗂 Boshqa shablon* — bayonnoma, standup, 1:1, savdo qo'ng'irog'i, intervyu, ma'ruza va boshqalar.\n"
    "*📎 Eksport* — transkript (TXT/SRT), xulosa (MD) yoki to'liq hisobot (Word/PDF) fayli.\n"
    "*📄 Bayonnoma* — rasmiy bayonnoma loyihasi (Word + PDF): kun tartibi, bayon, raqamlangan qaror bandlari; "
    "til tanlanadi (o'zbek lotin/kirill, rus, ingliz), «________» joylari qo'lda to'ldiriladi.\n"
    "*🌐 Boshqa til* — audio rus yoki ingliz tilida bo'lsa, bitta tugma bilan qayta o'giring."
)
NOTES = (
    "Barno hozircha faqat shaxsiy chatda va audio bilan ishlaydi; thread'dan tashqaridagi oddiy matnga "
    "javob bermaydi. Kunlik transkripsiya limiti hamma uchun umumiy — tugasa, audioni ertaga yuboring."
)
PROMPT = (
    "🎙 *Plaud* — audio yuboring, matnga o'girib, qisqa xulosa beraman.\n"
    "• mikrofon tugmasi bilan ovozli xabar yozing, yoki\n"
    "• audio fayl yuklang: mp3, m4a, aac, wav, ogg — 3 soat yoki 150 MB gacha.\n"
    "Xulosa ostida: vazifalar, boshqa shablon, eksport, boshqa til va 📄 Bayonnoma (rasmiy hujjat, Word/PDF). "
    "Savol bo'lsa — xulosa xabarining thread'ida yozing."
)


def view() -> dict[str, Any]:
    """"Home" varag'i (Block Kit `home` view)."""
    return {"type": "home", "blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": "Barno AI"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": TAGLINE}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*🎙 Plaud* — audio yuboring: Barno matnga "
                                                                 "o'giradi, xulosa qiladi va savollaringizga "
                                                                 "javob beradi."}},
        {"type": "actions", "block_id": "barno:home",
         "elements": [render.button("🎙 Plaud", PLAUD_ACTION, "plaud")]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Nimalar qila oladi:*\n" + FEATURES}},
        render.context(NOTES),
    ]}


def prompt_blocks() -> list[dict[str, Any]]:
    """Yo'riqnoma va «🎙 Plaud» tugmasi - chatdagi xabar uchun."""
    return render.sections(PROMPT) + [
        {"type": "actions", "block_id": "barno:plaud", "elements": [render.button("🎙 Plaud", PLAUD_ACTION, "plaud")]}]


def is_plaud(body: dict[str, Any]) -> bool:
    """Tugma bosilishi «🎙 Plaud» mi (Home varag'idan yoki xabardan)."""
    action = (body.get("actions") or [{}])[0]
    return str(action.get("action_id") or "") == PLAUD_ACTION


def is_text(event: dict[str, Any]) -> bool:
    """Shaxsiy chatdagi, thread'dan tashqaridagi oddiy matn (odam yozgan)."""
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
        return False
    return not event.get("thread_ts") and bool(str(event.get("text") or "").strip()) and not event.get("files")


def on_open(client: Any, event: dict[str, Any]) -> None:
    """`app_home_opened`: "Home" - varaqni yozish; "Messages" - chat bo'sh bo'lsa xush kelibsiz
    xabari (tugma bilan). Xato odamga ko'rinmaydi."""
    user, tab = event.get("user"), event.get("tab")
    if not user:
        return
    try:
        if tab in (None, "home"):
            client.views_publish(user_id=user, view=view())
        elif tab == "messages" and event.get("channel"):
            found = client.conversations_history(channel=event["channel"], limit=1)
            if not found.get("messages"):
                client.chat_postMessage(channel=event["channel"], text=PROMPT, blocks=prompt_blocks())
    except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
        log.warning("Slack Home/xush kelibsiz yozilmadi: %s", exc)


def on_text(client: Any, event: dict[str, Any]) -> None:
    """Thread'dan tashqaridagi matn -> yo'riqnoma va tugma (chatga `TEXT_EVERY` da bir marta)."""
    channel = event.get("channel")
    if not channel:
        return
    now = time.monotonic()
    with _hint_lock:
        if now - _hint_at.get(channel, -TEXT_EVERY) < TEXT_EVERY:
            return
        _hint_at[channel] = now
        if len(_hint_at) > 2000:
            _hint_at.clear()
    try:
        client.chat_postMessage(channel=channel, text=PROMPT, blocks=prompt_blocks())
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack Plaud yo'riqnomasi yuborilmadi: %s", exc)


def on_command(client: Any, body: dict[str, Any]) -> None:
    """`/plaud` -> yo'riqnoma va tugma shu chatga (buyruq matni Slack'da ko'rinmaydi)."""
    channel = body.get("channel_id") or body.get("user_id")
    if not channel:
        return
    try:
        client.chat_postMessage(channel=channel, text=PROMPT, blocks=prompt_blocks())
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack /plaud javobi yuborilmadi: %s", exc)


def on_plaud(client: Any, body: dict[str, Any]) -> None:
    """«🎙 Plaud» bosildi: chatda - faqat bosgan odamga eslatma (ephemeral), Home'dan -
    odamning chatiga yo'riqnoma."""
    user = (body.get("user") or {}).get("id")
    channel = (body.get("channel") or {}).get("id")
    if not user:
        return
    try:
        if channel:
            client.chat_postEphemeral(channel=channel, user=user,
                                      text="🎙 Audioni shu chatga yuboring: mikrofon bilan yozing yoki fayl yuklang.")
        else:
            client.chat_postMessage(channel=user, text=PROMPT, blocks=prompt_blocks())
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack Plaud yo'riqnomasi yuborilmadi: %s", exc)

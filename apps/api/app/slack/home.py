"""Slack App Home - Barno AI ochilganda chiqadigan "Home" varag'i va «🎙 Plaud» tugmasi.

Varaq `app_home_opened` hodisasida `views.publish` bilan yoziladi (hodisaga obuna manifestda
bor, ruxsat kerak emas): Barno nima qila olishi va «🎙 Plaud» tugmasi. Tugma odamning
Barno bilan chatiga "audio yuboring" yo'riqnomasini yozadi (`chat.postMessage` ga
foydalanuvchi id'si - `chat:write` bilan DM ochiladi).

HOZIRCHA audio REJIMSIZ ishlanadi: Slack'dagi Barno faqat audio va thread savoli bilan
ishlaydi, ya'ni Telegram'dagi kabi "bu yozuv" deb belgilash shart emas. Tugma - nom
("Plaud") va yo'riqnoma uchun; Slack'ka HR chat qo'shilganda (ega rejasi, 2026-11-04) aynan
shu tugma Telegram'dagi kabi rejimni yoqadi (`app/bot/plaud.py`).
"""

from __future__ import annotations

import logging

from typing import Any

from . import render

log = logging.getLogger(__name__)

PLAUD_ACTION = "barno_plaud"

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
    "Xulosa ostida: vazifalar, boshqa shablon, eksport, boshqa til. Savol bo'lsa — xulosa xabarining "
    "thread'ida yozing."
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


def is_plaud(body: dict[str, Any]) -> bool:
    """Tugma bosilishi «🎙 Plaud» mi (Home varag'idan yoki xabardan)."""
    action = (body.get("actions") or [{}])[0]
    return str(action.get("action_id") or "") == PLAUD_ACTION


def on_open(client: Any, event: dict[str, Any]) -> None:
    """`app_home_opened` -> varaqni yozish. Xato odamga ko'rinmaydi (varaq shunchaki bo'sh qoladi)."""
    user = event.get("user")
    if not user or event.get("tab") not in (None, "home"):
        return
    try:
        client.views_publish(user_id=user, view=view())
    except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
        log.warning("Slack Home varag'i yozilmadi: %s", exc)


def on_plaud(client: Any, body: dict[str, Any]) -> None:
    """«🎙 Plaud» -> odamning Barno bilan chatiga yo'riqnoma."""
    user = (body.get("user") or {}).get("id")
    if not user:
        return
    try:
        client.chat_postMessage(channel=user, text=PROMPT, blocks=render.sections(PROMPT))
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack Plaud yo'riqnomasi yuborilmadi: %s", exc)

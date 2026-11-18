"""Slack'da «🎙 Plaud» - chatning ichida (Telegram'dagi tugmaga o'xshab); "Home" varag'ida faqat shior.

Slack'da Telegram'dagi kabi doimiy pastki klaviatura yo'q, shuning uchun tugma CHATDA ikki
yo'l bilan qo'l ostida turadi:
  * xush kelibsiz xabari - odam Barno chatini ("Messages" varag'i) birinchi marta ochganda
    (chat bo'sh), yo'riqnoma va tugma chatning o'zida;
  * `/plaud` buyrug'i (Bolt `command`, Socket Mode'da ishlaydi) - manifestda slash command
    bo'lsa; bo'lmasa shunchaki chaqirilmaydi.
Thread'dan tashqaridagi oddiy matn - HR/CRM yordamchisiga (`assistant.on_text`; dispetcher shu yerdagi
`is_text` bilan ajratadi).
"Home" varag'ida shior va - shaxsiy hisob majburiy bo'lsa (`link.py`) - hisob holati: ulangan bo'lsa
ism va «Uzish», aks holda «Connect Barno AI account» (`app_home_opened` -> `views.publish`, ruxsat
kerak emas). Ulanmagan odamga xush kelibsiz xabaridan keyin, `/plaud` va «🎙 Plaud» o'rniga ulash
xabari chiqadi.
Tugma bosilganda: chatda - faqat bosgan odamga ko'rinadigan (ephemeral) eslatma, Home'dan -
odamning chatiga xabar (`chat.postMessage` ga foydalanuvchi id'si, `chat:write` bilan DM
ochiladi).

REJIM YO'Q (ega qarori 2026-11-13, "thread qoidasi"): audio - yozuv (Plaud), yozuv va bayonnoma savollari -
o'sha xabarning thread'ida (`meeting.question`), chatning o'ziga yozilgan matn - HR/CRM yordamchisi
(`assistant.py`). Shuning uchun Telegram'dagi kabi "Plaud rejimini" yoqish shart emas; tugma - nom ("Plaud") va
yo'riqnoma uchun.
"""

from __future__ import annotations

import logging

from typing import Any

from . import link, render

log = logging.getLogger(__name__)

PLAUD_ACTION = "barno_plaud"
#: Oddiy matnga yo'riqnoma bitta chatga shundan tez takrorlanmaydi (soniya).

TAGLINE = "BRB-TECHning foydali, aniq va xavfsiz AI yordamchisi"
PROMPT = (
    "🎙 *Plaud* — audio yuboring, matnga o'girib, qisqa xulosa beraman.\n"
    "• mikrofon tugmasi bilan ovozli xabar yozing, yoki\n"
    "• audio fayl yuklang: mp3, m4a, aac, wav, ogg — 3 soat yoki 150 MB gacha.\n"
    "Audio kelgach Barno uning tilini so'raydi (o'zbek, rus, ingliz) - tanlang. Xulosa ostida: yuklab olish, "
    "vazifalar, 📄 Bayonnoma (rasmiy hujjat, Word/PDF) va eksport. "
    "Yozuv haqidagi savolni — o'sha yozuv xabarining thread'iga yozing: Barno suhbatni eslab qoladi. 📄 Bayonnoma "
    "uchun ko'rsatma va o'zgartirishlar — bayonnoma xabari yoki faylining thread'ida, Barno yangi versiyasini "
    "yuboradi.\n\n"
    "💬 *Barno AI yordamchisi* — chatning o'ziga yozing: HR hujjatlari va qoidalari, HRM (ta'til, xodimlar) va CRM "
    "(mijozlar, vazifalar) bo'yicha javob beradi; CRM dagi o'zgarishni siz tasdiqlaganingizdan keyingina bajaradi."
)


def view(team: str | None = None, user: str | None = None) -> dict[str, Any]:
    """"Home" varag'i (Block Kit `home` view): shior (ega so'rovi, 2026-11-12 - tugma va imkoniyatlar
    ro'yxati olib tashlandi; yo'riqnoma chatdagi xabarda, `prompt_blocks`) va hisob holati
    (`link.home_blocks` - shaxsiy hisob majburiy bo'lmasa bo'sh)."""
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": TAGLINE}}]
    try:
        account = link.home_blocks(team, user)
    except Exception:  # noqa: BLE001 - katalog yoki fayl xatosi varaqni buzmasin
        log.exception("Slack Home: hisob holati o'qilmadi")
        account = []
    if account:
        blocks += [{"type": "divider"}, *account]
    # «🗣 Ovoz namunasi» (ega qarori 2026-11-18) - yig'ilishlarda ism-familiya chiqishi uchun.
    from . import voice

    blocks += [{"type": "divider"}, *voice.home_blocks()]
    return {"type": "home", "blocks": blocks}


def prompt_blocks() -> list[dict[str, Any]]:
    """Yo'riqnoma va «🎙 Plaud» tugmasi - chatdagi xabar uchun."""
    from . import voice

    return render.sections(PROMPT + "\n\n" + voice.HOME_TEXT) + [
        {"type": "actions", "block_id": "barno:plaud",
         "elements": [render.button("🎙 Plaud", PLAUD_ACTION, "plaud"), voice.start_button()]}]


def is_plaud(body: dict[str, Any]) -> bool:
    """Tugma bosilishi «🎙 Plaud» mi (Home varag'idan yoki xabardan)."""
    action = (body.get("actions") or [{}])[0]
    return str(action.get("action_id") or "") == PLAUD_ACTION


def is_text(event: dict[str, Any]) -> bool:
    """Shaxsiy chatdagi, thread'dan tashqaridagi oddiy matn (odam yozgan) - dispetcher uni HR/CRM yordamchisiga beradi
    (`assistant.on_text`)."""
    if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
        return False
    return not event.get("thread_ts") and bool(str(event.get("text") or "").strip()) and not event.get("files")


def on_open(client: Any, event: dict[str, Any]) -> None:
    """`app_home_opened`: "Home" - varaqni yozish; "Messages" - chat bo'sh bo'lsa xush kelibsiz
    xabari (tugma bilan). Xato odamga ko'rinmaydi."""
    user, tab = event.get("user"), event.get("tab")
    if not user:
        return
    team = link.team_of(event)
    try:
        if tab in (None, "home"):
            client.views_publish(user_id=user, view=view(team, user))
        elif tab == "messages" and event.get("channel"):
            found = client.conversations_history(channel=event["channel"], limit=1)
            if not found.get("messages"):
                client.chat_postMessage(channel=event["channel"], text=PROMPT, blocks=prompt_blocks())
                # Birinchi ochilish: nima qila olishi (yuqorida) va - ulanmagan bo'lsa - ulash tugmasi.
                link.gate(client, team, user, event["channel"])
    except Exception as exc:  # noqa: BLE001 - SlackApiError, tarmoq
        log.warning("Slack Home/xush kelibsiz yozilmadi: %s", exc)


def on_command(client: Any, body: dict[str, Any]) -> None:
    """`/plaud` -> yo'riqnoma va tugma shu chatga (buyruq matni Slack'da ko'rinmaydi)."""
    channel = body.get("channel_id") or body.get("user_id")
    if not channel:
        return
    if not link.gate(client, body.get("team_id"), body.get("user_id"), body.get("channel_id"), force=True):
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
    if not link.gate(client, link.team_of(body), user, channel, force=True):
        return
    try:
        if channel:
            client.chat_postEphemeral(channel=channel, user=user,
                                      text="🎙 Audioni shu chatga yuboring: mikrofon bilan yozing yoki fayl yuklang.")
        else:
            client.chat_postMessage(channel=user, text=PROMPT, blocks=prompt_blocks())
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack Plaud yo'riqnomasi yuborilmadi: %s", exc)

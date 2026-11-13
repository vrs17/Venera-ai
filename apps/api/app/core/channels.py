"""Kanal: so'rov qaysi interfeysdan keldi.

    web       veb ilova (`apps/web`)
    miniapp   Telegram mini app (`apps/tg`, `/tg/` ostida)
    bot       Telegram bot - chatning o'zida (`app/bot/`)
    slack     Slack'dagi Barno AI - shaxsiy chat (`app/slack/assistant.py`, 2026-11-13)
    desktop   desktop klient
    mobile    mobil ilova "Venera Yozuv" (`apps/mobile`, yig'ilish yozuvchisi)
    api       boshqa hamma narsa (curl, skript, eski build)

NEGA KLIENT O'ZI AYTADI. Server tomonida web va mini app so'rovi bir xil
ko'rinadi: ikkalasi ham shu domendan, shu token bilan keladi. Shuning uchun
klient `X-Venera-Client` sarlavhasini yuboradi (web - `web`, mini app -
`miniapp`); nginx maxsus sarlavhalarni o'zgarishsiz o'tkazadi.

Sarlavha yo'q bo'lsa (eski build hali keshda) - mini app sahifasi `/tg/`
ostida turadi, ya'ni `Referer` yo'li buni aytadi. Qolgani `api`.

`bot` va `slack` SARLAVHA ORQALI QABUL QILINMAYDI: ular HTTP'dan kelmaydi,
kanalni kod ichida o'zi beradi. Sarlavhadagi `bot` / `slack` - soxta, va
statistikani buzmasligi uchun e'tiborga olinmaydi.

Bu faqat STATISTIKA uchun. Kanalga qarab huquq berilmaydi - sarlavhani har
kim yoza oladi.
"""

from __future__ import annotations

import urllib.parse

from typing import Any

#: Hamma kanallar - admin panel filtrlari shu tartibda.
CHANNELS: tuple[str, ...] = ("web", "miniapp", "bot", "slack", "desktop", "mobile", "api")

#: Klient sarlavhasi.
HEADER = "X-Venera-Client"

#: Sarlavha orqali e'lon qilinishi mumkin bo'lgan kanallar (`bot` va `slack` yo'q).
#: `mobile` - yig'ilish yozuvchisi: uning audio va xulosa chaqiruvlari (GAPI,
#: Ollama) hisobda alohida ko'rinsin, `api` ga aralashib ketmasin.
CLIENT_CHANNELS = frozenset({"web", "miniapp", "desktop", "mobile"})

#: Boshqacha yozilishlar - bitta nomga keltiriladi.
_ALIASES = {
    "mini-app": "miniapp",
    "mini_app": "miniapp",
    "tg": "miniapp",
    "webapp": "miniapp",
    "telegram": "bot",
    "tg-bot": "bot",
    "tgbot": "bot",
}

#: Mini app sahifalari shu yo'llar ostida: `/tg/` (eski `apps/tg`, almashtirishdan
#: keyin - yangisi) va `/tg-beta/` (yangi Mini App sinovda; almashtirishdan keyin
#: ham sinovchilarning eski tugmalari uchun qoladi). Sarlavhasiz so'rov (audio,
#: rasm, eski build) shu `Referer` bilan keladi - statistikada `api` bo'lmasin.
_MINIAPP_PREFIXES = ("/tg/", "/tg-beta/")

_DEFAULT = "api"


def normalize(value: Any, default: str | None = _DEFAULT) -> str | None:
    """Ixtiyoriy yozilishni kanal nomiga keltiradi; tanilmasa `default`."""
    if not isinstance(value, str):
        return default
    key = value.strip().lower()[:32]
    key = _ALIASES.get(key, key)
    return key if key in CHANNELS else default


def channel_of(request: Any) -> str:
    """So'rovning kanali. Tartib:

      1. `X-Venera-Client` - `web`, `miniapp`, `desktop` yoki `mobile` bo'lsa, o'sha;
      2. aks holda `Referer` / `Origin` yo'li `/tg/` yoki `/tg-beta/` bilan
         boshlansa - `miniapp`;
      3. aks holda `api`.

    `request` - Starlette `Request` yoki `.headers` i bor istalgan obyekt.
    Hech qachon xato bermaydi.
    """
    try:
        headers = getattr(request, "headers", None)
        if headers is None:
            return _DEFAULT
        declared = normalize(_header(headers, HEADER), default=None)
        if declared in CLIENT_CHANNELS:
            return declared
        for name in ("Referer", "Origin"):
            raw = _header(headers, name)
            if raw and _is_miniapp(raw):
                return "miniapp"
    except Exception:                                       # noqa: BLE001
        pass
    return _DEFAULT


def _header(headers: Any, name: str) -> str | None:
    """Sarlavha qiymati. Starlette `Headers` registrga qaramaydi; oddiy lug'at
    (testlar, bot) uchun kichik harfli nom ham sinab ko'riladi."""
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return value if isinstance(value, str) else None


def _is_miniapp(url: str) -> bool:
    path = urllib.parse.urlsplit(url.strip()).path or ""
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in _MINIAPP_PREFIXES)

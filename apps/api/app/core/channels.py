"""Kanal: so'rov qaysi interfeysdan keldi.

    web       veb ilova (`apps/web`)
    miniapp   Telegram mini app (`apps/tg`, `/tg/` ostida)
    bot       Telegram bot - chatning o'zida (`app/bot/`)
    desktop   desktop klient
    api       boshqa hamma narsa (curl, skript, eski build)

NEGA KLIENT O'ZI AYTADI. Server tomonida web va mini app so'rovi bir xil
ko'rinadi: ikkalasi ham shu domendan, shu token bilan keladi. Shuning uchun
klient `X-Venera-Client` sarlavhasini yuboradi (web - `web`, mini app -
`miniapp`); nginx maxsus sarlavhalarni o'zgarishsiz o'tkazadi.

Sarlavha yo'q bo'lsa (eski build hali keshda) - mini app sahifasi `/tg/`
ostida turadi, ya'ni `Referer` yo'li buni aytadi. Qolgani `api`.

`bot` SARLAVHA ORQALI QABUL QILINMAYDI: bot HTTP'dan kelmaydi, u kanalni
kod ichida o'zi beradi. Sarlavhadagi `bot` - soxta, va statistikani
buzmasligi uchun e'tiborga olinmaydi.

Bu faqat STATISTIKA uchun. Kanalga qarab huquq berilmaydi - sarlavhani har
kim yoza oladi.
"""

from __future__ import annotations

import urllib.parse

from typing import Any

#: Hamma kanallar - admin panel filtrlari shu tartibda.
CHANNELS: tuple[str, ...] = ("web", "miniapp", "bot", "desktop", "api")

#: Klient sarlavhasi.
HEADER = "X-Venera-Client"

#: Sarlavha orqali e'lon qilinishi mumkin bo'lgan kanallar (`bot` yo'q).
CLIENT_CHANNELS = frozenset({"web", "miniapp", "desktop"})

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

#: Mini app sahifasi shu yo'l ostida (`apps/tg`, nginx `location /tg/`).
_MINIAPP_PREFIX = "/tg/"

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

      1. `X-Venera-Client` - `web`, `miniapp` yoki `desktop` bo'lsa, o'sha;
      2. aks holda `Referer` / `Origin` yo'li `/tg/` bilan boshlansa -
         `miniapp`;
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
    return path == _MINIAPP_PREFIX.rstrip("/") or path.startswith(_MINIAPP_PREFIX)

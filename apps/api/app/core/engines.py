"""HR yordamchisining DVIGATELI (engine): savol qaysi versiyalangan yo'lga ketadi.

    v1   POST /api/v1/chat/stream   barqaror: tasdiqlangan da'volardan yig'ilgan
                                    javob, hujjat iqtiboslari `[n]`
    v2   POST /api/v2/chat/stream   yangi: javobni model yozadi, Mehnat kodeksi
                                    moddalari LEX.UZ havolasi bilan, "Pro" rejimi
    ""   POST /api/chat/stream      xizmatning default'i (bugun = v1) - eski,
                                    versiyasiz yo'l (prod hozir shunda)

Manba: yuqoridagi jamoaning o'zgarishlar xati (2026-10-02). Qoida: "xulq
o'zgarishi yangi versiya bo'lib chiqadi, integratsiya qilingan versiya
ishlashda davom etadi" - ya'ni versiyani BIZ tanlaymiz va u o'z-o'zidan
almashmaydi.

NEGA DEFAULT v2. Foydalanuvchi aytgan: "v1 - eski ko'rinish uchun, v2 - yangi
ko'rinish uchun". Bu shox (`venera-integration`) - yangi ko'rinish.

NEGA KANAL BO'YICHA. Yangi dvigatelni hamma kanalga birdan yoqish shart emas:
xatda ham "ikkinchi yo'lni flag yoki guruh orqali qo'shing, solishtiring"
deyilgan. `HRM_ASSISTANT_ENGINE_BY_CHANNEL=miniapp=v1,bot=v1` - mini app va
bot eski dvigatelda qoladi, web esa umumiy `HRM_ASSISTANT_ENGINE` da.
Kanal - `core/channels.py` dagi nom (web | miniapp | bot | desktop | api).

VERSIYASIZ QOLADIGANLAR: suhbatlar tarixi (`/api/chats`), yozuv amallari,
ariza fayllari, hujjat PDF'lari va `/api/pro/quota` - xat bo'yicha ular
ikkala dvigatel uchun bitta.

"PRO" FAQAT v2 DA. Boshqa dvigatelda `mode=pro` yuqoriga YUBORILMAYDI
(`chat.open_stream`), `GET /api/v1/pro/quota` esa `available: false` qaytaradi
- yuqoriga bormasdan.

NOTO'G'RI QIYMAT server'ni yiqitmaydi: jurnalga (bir marta) va
`/api/health/detail` ga yoziladi, o'rniga kod default'i (`v2`) yoki umumiy
qiymat ishlaydi. Bitta harf xatosi tufayli chat butunlay to'xtashi
dvigatelni noto'g'ri tanlashdan yomonroq.
"""

from __future__ import annotations

import logging
import threading

from .channels import normalize as normalize_channel
from .config import settings

log = logging.getLogger(__name__)

#: Ruxsat etilgan dvigatellar. `""` - versiyasiz (xizmat default'i).
ENGINES: tuple[str, ...] = ("v1", "v2", "")

#: "Pro" rejimi faqat shu dvigatelda bor (xat, 3-bo'lim).
PRO_ENGINE = "v2"

#: Kod default'i - sozlama noto'g'ri bo'lsa shu ishlaydi.
DEFAULT_ENGINE = "v2"

#: "Versiyasiz" ning boshqacha yozilishlari - `.env` da bo'sh qiymat
#: ko'rinmay qolishi oson, so'z bilan yozish aniqroq.
_LEGACY_WORDS = frozenset({"", "default", "legacy", "none", "unversioned"})

_warned: set[str] = set()
_warned_lock = threading.Lock()


def normalize(value: object) -> str | None:
    """Yozilishni dvigatel nomiga keltiradi: `"V2 "` -> `"v2"`, `"legacy"` -> `""`.
    Tanilmasa `None`."""
    text = str(value if value is not None else "").strip().lower()
    if text in _LEGACY_WORDS:
        return ""
    return text if text in ENGINES else None


def _warn_once(message: str) -> None:
    """Noto'g'ri sozlama har savolda jurnalni to'ldirmasin - bir marta."""
    with _warned_lock:
        if message in _warned:
            return
        _warned.add(message)
    log.warning(message)


def default_engine() -> str:
    """Umumiy dvigatel (`HRM_ASSISTANT_ENGINE`)."""
    raw = getattr(settings, "hrm_assistant_engine", DEFAULT_ENGINE)
    found = normalize(raw)
    if found is None:
        _warn_once(f"HRM_ASSISTANT_ENGINE={raw!r} tanilmadi (v1 | v2 | bo'sh) - "
                   f"{DEFAULT_ENGINE} ishlatiladi")
        return DEFAULT_ENGINE
    return found


def channel_overrides() -> tuple[dict[str, str], list[str]]:
    """`HRM_ASSISTANT_ENGINE_BY_CHANNEL` -> ({kanal: dvigatel}, muammolar).

    Har chaqiruvda qayta o'qiladi (bir necha qator matn - arzon): testlar va
    `.env` sozlamani ishga tushgandan keyin ham o'zgartira olsin.
    """
    raw = str(getattr(settings, "hrm_assistant_engine_by_channel", "") or "")
    found: dict[str, str] = {}
    problems: list[str] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, value = part.partition("=")
        channel = normalize_channel(name, default=None)
        engine = normalize(value)
        if not sep or channel is None or engine is None:
            problems.append(f"HRM_ASSISTANT_ENGINE_BY_CHANNEL: {part!r} tanilmadi "
                            "(kanal=v1|v2|legacy) - e'tiborsiz qoldirildi")
            continue
        found[channel] = engine
    return found, problems


def engine_for(channel: str | None) -> str:
    """Shu kanal uchun dvigatel: kanalga alohida berilgan bo'lsa o'sha,
    bo'lmasa umumiy (`HRM_ASSISTANT_ENGINE`)."""
    overrides, problems = channel_overrides()
    for problem in problems:
        _warn_once(problem)
    name = normalize_channel(channel, default=None)
    if name is not None and name in overrides:
        return overrides[name]
    return default_engine()


def pro_available(engine: str) -> bool:
    """"Pro" shu dvigatelda bormi."""
    return engine == PRO_ENGINE


def config_state() -> dict[str, object]:
    """`/api/health/detail` uchun: umumiy dvigatel, har kanalniki va muammolar.
    Sirlar yo'q - faqat versiya nomlari."""
    from .channels import CHANNELS

    overrides, problems = channel_overrides()
    raw = getattr(settings, "hrm_assistant_engine", DEFAULT_ENGINE)
    if normalize(raw) is None:
        problems = [f"HRM_ASSISTANT_ENGINE={raw!r} tanilmadi - {DEFAULT_ENGINE} ishlatiladi",
                    *problems]
    default = default_engine()
    return {
        "default": default,
        "byChannel": {name: overrides.get(name, default) for name in CHANNELS},
        "problems": problems,
    }

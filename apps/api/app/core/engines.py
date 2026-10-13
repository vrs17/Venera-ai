"""HR yordamchisining DVIGATELI (engine): savol qaysi versiyalangan yo'lga ketadi.

    v1   POST /api/v1/chat/stream   barqaror: tasdiqlangan da'volardan yig'ilgan
                                    javob, hujjat iqtiboslari `[n]`
    v2   POST /api/v2/chat/stream   yangi: javobni model yozadi, Mehnat kodeksi
                                    moddalari LEX.UZ havolasi bilan, "Pro" rejimi
    v3   POST /api/v3/chat/stream   "Venera Core" (2026-10-08, API 3.3): hamma
                                    imkoniyat (HRM, CRM, hujjatlar, bilim, "Pro")
                                    BITTA vazifa-sikli; vazifa holati xabarlar
                                    orasida saqlanadi, yozishdan oldin nomlar
                                    aniqlanadi. So'rov va kadrlar v2 bilan bir
                                    xil, `done` ga vazifa holati va iz kaliti
                                    (`task`, `trace_id`) qo'shiladi
    v4   POST /api/v4/chat/stream   agentning v4 dvigateli (2026-10-13): o'sha Core
                                    + yangi imkoniyatlar. v1-v3 agent tomonida
                                    MUZLATILGAN - har yangilik faqat v4 ga tushadi.
                                    Shartnoma 4.0 (`X-Barno-Contract`, `purpose`),
                                    qolgani v3 bilan bir xil - `assistant.py`
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

"PRO" FAQAT `pro: True` DVIGATELLARDA (v2, v3, v4). Boshqasida `mode=pro` yuqoriga YUBORILMAYDI
(`chat.open_stream`), `GET /api/v1/pro/quota` esa `available: false` qaytaradi
- yuqoriga bormasdan.

NOTO'G'RI QIYMAT server'ni yiqitmaydi: jurnalga (bir marta) va
`/api/health/detail` ga yoziladi, o'rniga kod default'i (`v2`) yoki umumiy
qiymat ishlaydi. Bitta harf xatosi tufayli chat butunlay to'xtashi
dvigatelni noto'g'ri tanlashdan yomonroq.

ADMIN PANEL USTUN (2026-10-04). `.env` - faqat BOSHLANG'ICH qiymat: admin
panelda siyosat saqlangach (`engine_policy`) va odamga alohida versiya
berilgach (`engine_access`) o'shalar ishlaydi -
`services/engine_control.effective_engine`. Bu fayl faqat KATALOG (`ENGINES`)
va `.env` o'qishini beradi: `core` analitika omboriga bog'lanmaydi.
"""

from __future__ import annotations

import logging
import threading

from .channels import normalize as normalize_channel
from .config import settings

log = logging.getLogger(__name__)

#: KATALOG - admin panelda tanlanadigan dvigatellar, tartibi ham shu.
#:
#: Faqat kalit va imkoniyatlar: nomi va tavsifi frontend tarjimalarida
#: (`i18n`) - matn uch tilda, server esa tilni bilmaydi. `pro` - "Pro"
#: rejimi bor, `law` - javobda LEX.UZ qonunchilik manbalari bor.
#:
#: Versiyasiz yo'l (`""`, `legacy`) bu yerda ATAYLAB YO'Q: u faqat `.env`
#: orqali yoqiladigan favqulodda chiqish (xizmat versiyali yo'llarni
#: buzsa). Admin panelda tanlansa, "qaysi versiya javob beradi" degan
#: savolga javob xizmatning default'iga bog'lanib qolardi - u esa bizdan
#: so'ramasdan o'zgarishi mumkin.
ENGINES: tuple[dict[str, object], ...] = (
    {"id": "v1", "pro": False, "law": False},
    {"id": "v2", "pro": True, "law": True},
    # v3 avval odamlarga ALOHIDA (admin panel) beriladi; hammaga - sinovdan keyin.
    {"id": "v3", "pro": True, "law": True},
    # v4 - xuddi shu tartib: avval bitta odamga, keyin hammaga. "Pro" va qonun manbasi
    # v3 niki bilan BIR XIL yo'ldan (agentda v3 va v4 - bitta Core), ya'ni `True` halol.
    {"id": "v4", "pro": True, "law": True},
)

#: Katalogdagi kalitlar - admin va klient tanlovi faqat shulardan.
CATALOG_IDS: tuple[str, ...] = tuple(str(item["id"]) for item in ENGINES)

#: Yuqoriga ochiladigan YO'LLAR: katalog + versiyasiz (`""`, xizmat
#: default'i). Klient (`assistant.py`) faqat shularni qabul qiladi.
ROUTES: tuple[str, ...] = (*CATALOG_IDS, "")

#: "Pro" rejimi bor dvigatellar - katalogdan (`pro: True`), qo'lda emas: yangi
#: versiya qo'shilganda shu ro'yxatni ham eslash shart bo'lmasin.
PRO_ENGINES: frozenset[str] = frozenset(str(item["id"]) for item in ENGINES if item["pro"])

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
    return text if text in ROUTES else None


def catalog_id(value: object) -> str | None:
    """Klient yoki admin tanlovi -> katalog kaliti (`" V2"` -> `"v2"`), aks
    holda `None`. Versiyasiz yo'l (`legacy`, `""`) bu yerda TANILMAYDI -
    u faqat `.env` orqali (`ENGINES` izohi)."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()[:16]
    return text if text in CATALOG_IDS else None


def catalog() -> list[dict[str, object]]:
    """Katalog NUSXASI - javobga beriladi, asl ro'yxat o'zgarmasin."""
    return [dict(item) for item in ENGINES]


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
        _warn_once(f"HRM_ASSISTANT_ENGINE={raw!r} tanilmadi (v1 | v2 | v3 | v4 | bo'sh) - "
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
                            "(kanal=v1|v2|v3|v4|legacy) - e'tiborsiz qoldirildi")
            continue
        found[channel] = engine
    return found, problems


def engine_for(channel: str | None) -> str:
    """Shu kanal uchun `.env` dagi dvigatel: kanalga alohida berilgan bo'lsa
    o'sha, bo'lmasa umumiy (`HRM_ASSISTANT_ENGINE`).

    Bu - zanjirning OXIRGI bo'g'ini (admin hali siyosat saqlamagan yoki
    ombor o'qilmadi). So'rov yo'llari buni emas,
    `services/engine_control.effective_engine` ni chaqiradi."""
    overrides, problems = channel_overrides()
    for problem in problems:
        _warn_once(problem)
    name = normalize_channel(channel, default=None)
    if name is not None and name in overrides:
        return overrides[name]
    return default_engine()


def pro_available(engine: str) -> bool:
    """"Pro" shu dvigatelda bormi."""
    return engine in PRO_ENGINES


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

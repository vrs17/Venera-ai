"""Ko'p tillilik: `t()`, `phrase()`, `active()`, `bind()`, `codes()`.

BUTUN TIZIM shu moduldan tilni oladi: STT so'rovi, javob iboralari, intent
qoidalari va interfeys matni. Foydalanuvchi tilni sozlamalarda tanlaydi
(`config.language`), avtomatik ANIQLANMAYDI.

THREAD MODELI - ehtiyot bo'ling:
    `_active` BITTA modul atributi. CPython'da atribut yozuvi atomik va
    `LanguagePack` frozen=True, shuning uchun `t()` ni PortAudio callback
    thread'idan ham, Tk thread'idan ham, orchestrator korutinasidan ham
    QULFSIZ chaqirish mumkin. `bind()` yangi paketni to'liq yig'ib bo'lgach
    bitta yozuv bilan almashtiradi - yarim yuklangan holat ko'rinmaydi.

    QULF QO'SHMANG va LAZY-LOAD QO'SHMANG. Audio callback 32 ms ichida
    qaytishi kerak; qulf kutish yoki YAML o'qish o'sha yerda oqimni uzadi.
    Shu sababli etalon paket MODUL IMPORT QILINGANDA yuklanadi.

FALLBACK ETALONI - `uz`, `en` EMAS. Manba til o'zbekcha: dasturchi yangi
kalitni avval `uz/ui.yaml` ga yozadi. Etalon `en` bo'lsa, yangi kalit hech
qayerda ushlanmasdan xom holida ekranga chiqib ketardi.

TIPIK ISHLATILISH:

    from venera import i18n
    i18n.bind(config.language)              # ishga tushishda bir marta
    window.title(i18n.t("window.title"))
    tts.say(i18n.phrase("open_app_ok", app="Chrome"))
    intent = i18n.grammar().match(text)
    stt.set_language(i18n.stt_code())
"""

from __future__ import annotations

import logging
from typing import Any

from .locale import FALLBACK_CODE, SECTIONS, LocaleSpec
from .pack import LanguagePack, empty as _empty_pack
from .registry import LocaleRegistry
from . import script

log = logging.getLogger(__name__)

__all__ = [
    "FALLBACK_CODE", "SECTIONS", "LanguagePack", "LocaleRegistry", "LocaleSpec",
    "active", "bind", "code", "codes", "describe", "grammar", "names", "phrase",
    "problems", "raw", "registry", "reload", "script", "spec", "stt_code", "t",
    "words",
]

_registry = LocaleRegistry()

#: Etalon paket. Import vaqtida bir marta yuklanadi - keyin hech qachon
#: qayta o'qilmaydi (`reload()` dan tashqari).
_fallback: LanguagePack = _empty_pack(FALLBACK_CODE)

#: FAOL paket. Yagona o'zgaruvchan holat. Faqat `bind()` yozadi.
_active: LanguagePack = _fallback


def _boot() -> None:
    """Import vaqtidagi bir martalik yuklash. Xato bo'lsa ham exception yo'q."""
    global _fallback, _active
    try:
        pack = _registry.load_fallback()
    except Exception:  # noqa: BLE001 - i18n ilovani yiqitmasin
        log.exception("Etalon til paketi yuklanmadi - bo'sh paket ishlatilmoqda")
        return
    _fallback = pack
    _active = pack


_boot()


# --- boshqaruv --------------------------------------------------------------


def bind(language: str) -> LanguagePack:
    """Faol tilni o'rnatadi va yangi paketni qaytaradi.

    Paket to'liq yig'ilib bo'lgandan KEYIN bitta atribut yozuvi bilan
    almashtiriladi - boshqa thread'lar yarim yuklangan holatni ko'rmaydi.

    Til paketi topilmasa (masalan `zh` - STT ishlaydi, UI tarjimasi yo'q)
    faol paket zaxira tilga tushadi va bu `problems()` da ko'rinadi.
    """
    global _active
    wanted = str(language or "").strip().lower() or FALLBACK_CODE

    if wanted == _fallback.code and _fallback.ok:
        _active = _fallback
        log.info("Interfeys tili: %s", _fallback.code)
        return _fallback

    pack = _registry.load(wanted, fallback=_fallback)
    if not pack.ui and not pack.grammar.rules:
        log.warning("%r tili uchun paket yo'q - interfeys %s tilida qoladi",
                    wanted, _fallback.code)
    _active = pack     # <- yagona yozuv
    log.info("Interfeys tili: %s (%s)", pack.code, pack.spec.display)
    return pack


def reload() -> LanguagePack:
    """Til papkalarini qaytadan o'qiydi (tray'dagi "qayta yuklash" uchun)."""
    global _fallback
    current = _active.code
    _registry.discover(force=True)
    _fallback = _registry.load_fallback()
    return bind(current)


def registry() -> LocaleRegistry:
    return _registry


# --- o'qish -----------------------------------------------------------------


def active() -> LanguagePack:
    """Faol til paketi. HECH QACHON None qaytarmaydi."""
    return _active


def code() -> str:
    return _active.code


def spec() -> LocaleSpec:
    return _active.spec


def stt_code() -> str:
    """STT serveriga yuboriladigan til kodi."""
    return _active.spec.stt_code or _active.code or FALLBACK_CODE


def codes() -> tuple[str, ...]:
    """Til paketi MAVJUD kodlar (etalon birinchi)."""
    return _registry.codes()


def names() -> dict[str, str]:
    """kod -> tilning o'z tilidagi nomi. Sozlamalar ro'yxati uchun."""
    return _registry.names()


def t(key: str, **kwargs: Any) -> str:
    """Interfeys matni. Kalit topilmasa zaxira tildan, u ham yo'q bo'lsa kalit."""
    return _active.text(key, **kwargs)


def phrase(key: str, **kwargs: Any) -> str:
    """Ovozli javob shabloni."""
    return _active.phrase(key, **kwargs)


def raw(section: str, key: str, default: Any = None) -> Any:
    """Formatlanmagan qiymat - ro'yxatlar uchun (weekdays, months)."""
    return _active.raw(section, key, default)


def words():
    """Faol tilning so'z boyligi (`nlu.words.WordBook`)."""
    return _active.words


def grammar():
    """Faol tilning kompilyatsiya qilingan qoidalari (`nlu.grammar.Grammar`)."""
    return _active.grammar


def problems() -> tuple[str, ...]:
    """Faol paket va katalogdagi barcha muammolar (`--check` uchun)."""
    return tuple(_registry.problems) + tuple(_active.problems)


def describe() -> dict[str, Any]:
    """`--check` uchun qisqacha holat."""
    data = _active.describe()
    data["available"] = list(codes())
    data["registry_problems"] = len(_registry.problems)
    return data

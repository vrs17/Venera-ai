"""`locale.yaml` - til paketining pasporti.

Har bir til papkasida BITTA kichik `locale.yaml` bo'ladi. U ataylab kichik:
`discover()` ishga tushishda BARCHA tillarning aynan shu faylini o'qiydi, qolgan
beshta fayl esa faqat FAOL til uchun yuklanadi. Shuning uchun bu yerga katta
ma'lumot (matnlar, qoidalar) yozilmaydi.

Yangi til qo'shish = `resources/i18n/<kod>/` papkasi + shu pasport. Kodda hech
qanday qattiq ro'yxat yo'q.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

#: Fallback etaloni. `en` EMAS - manba til o'zbekcha: dasturchi yangi kalitni
#: avval `uz/ui.yaml` ga yozadi. Agar etalon `en` bo'lsa, yangi kalit hech
#: qayerda ushlanmasdan xom holida ekranga chiqib ketardi.
FALLBACK_CODE = "uz"

#: Til paketidagi bo'limlar (`<bo'lim>.yaml`).
SECTIONS = ("ui", "phrases", "rules", "words", "apps")


@dataclass(frozen=True)
class LocaleSpec:
    """`locale.yaml` mazmuni.

    Maydonlar:
      code           papka nomi bilan bir xil bo'lishi kerak ("uz", "ru", ...)
      name           tilning O'Z tilidagi nomi - foydalanuvchi hozirgi til
                     noto'g'ri bo'lsa ham o'zinikini tanib oladi
      english_name   loglar va nosozliklarni tekshirish uchun
      fallback       kalit topilmasa qaysi tildan olinadi (odatda "uz")
      script         "latin" | "cyrillic" | "han" - `i18n.script` shunga qaraydi
      direction      "ltr" | "rtl"
      stt            STT serveriga yuboriladigan kod. Bo'sh bo'lsa `code`.
      number_parser  `nlu.numbers.PARSERS` dagi nom
      complete       UI to'liq tarjima qilinganmi. False bo'lsa `--check`
                     ogohlantiradi va yetishmagan kalitlar fallback'dan olinadi.
      note           erkin izoh (masalan "zh: faqat STT, UI tarjima qilinmagan")
    """

    code: str
    name: str = ""
    english_name: str = ""
    version: int = 1
    fallback: str = FALLBACK_CODE
    script: str = "latin"
    direction: str = "ltr"
    stt: str = ""
    number_parser: str = "decimal_words"
    complete: bool = False
    note: str = ""

    @property
    def stt_code(self) -> str:
        """STT serveri kutayotgan til kodi."""
        return self.stt or self.code

    @property
    def display(self) -> str:
        """UI ro'yxatida ko'rsatiladigan nom."""
        return self.name or self.english_name or self.code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "name": self.name, "english_name": self.english_name,
            "version": self.version, "fallback": self.fallback, "script": self.script,
            "direction": self.direction, "stt": self.stt_code,
            "number_parser": self.number_parser, "complete": self.complete,
            "note": self.note,
        }


_SCRIPTS = ("latin", "cyrillic", "han", "arabic", "other")
_DIRECTIONS = ("ltr", "rtl")


def parse(code: str, data: Any) -> tuple[LocaleSpec, list[str]]:
    """`locale.yaml` dan LocaleSpec. HECH QACHON exception tashlamaydi.

    `(spec, muammolar)` qaytaradi - `config.load()` bilan bir xil naqsh.
    Buzuq pasport butun ilovani yiqitmaydi, faqat shu til nuqsonli bo'lib
    ro'yxatda qoladi.
    """
    problems: list[str] = []
    code = str(code or "").strip().lower()
    if not code:
        return LocaleSpec(code=""), ["locale: kod bo'sh"]

    if not isinstance(data, Mapping):
        problems.append(f"{code}/locale.yaml: mapping kutilgan edi, "
                        f"{type(data).__name__} keldi - default'lar ishlatildi")
        data = {}

    def _str(key: str, default: str = "") -> str:
        value = data.get(key, default)
        if value is None:
            return default
        if not isinstance(value, (str, int, float)):
            problems.append(f"{code}/locale.yaml: {key} matn bo'lishi kerak - e'tiborsiz")
            return default
        return str(value).strip()

    declared = _str("code", code).lower()
    if declared and declared != code:
        problems.append(f"{code}/locale.yaml: code={declared!r} papka nomiga mos emas "
                        f"- papka nomi ({code}) ustun")

    script = _str("script", "latin").lower() or "latin"
    if script not in _SCRIPTS:
        problems.append(f"{code}/locale.yaml: script={script!r} noma'lum ({list(_SCRIPTS)}) "
                        "- 'other' ga qaytarildi")
        script = "other"

    direction = _str("direction", "ltr").lower() or "ltr"
    if direction not in _DIRECTIONS:
        problems.append(f"{code}/locale.yaml: direction={direction!r} noma'lum - 'ltr'")
        direction = "ltr"

    try:
        version = int(data.get("version", 1))
    except (TypeError, ValueError):
        problems.append(f"{code}/locale.yaml: version butun son bo'lishi kerak - 1")
        version = 1

    fallback = _str("fallback", FALLBACK_CODE).lower() or FALLBACK_CODE
    if fallback == code:
        # O'zini o'ziga fallback qilish - cheksiz halqa. Etalon tilning o'zi.
        fallback = ""

    spec = LocaleSpec(
        code=code,
        name=_str("name") or code,
        english_name=_str("english_name") or _str("name") or code,
        version=version,
        fallback=fallback,
        script=script,
        direction=direction,
        stt=_str("stt").lower(),
        number_parser=_str("number_parser", "decimal_words") or "decimal_words",
        complete=bool(data.get("complete", False)),
        note=_str("note"),
    )
    return spec, problems


def empty(code: str) -> LocaleSpec:
    """Fayl umuman o'qilmaganda ishlatiladigan minimal pasport."""
    return replace(LocaleSpec(code=code), name=code, english_name=code)

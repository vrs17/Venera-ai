"""Slot qiymatini tozalovchi funksiyalar registri.

`rules.yaml` da har slot qaysi transformatsiyadan o'tishini AYTADI:

    slots:
      level: {transform: number, clamp: [0, 100], required: true}
      app:   {transform: strip_affixes}

Shu tufayli yangi til uchun Python kodi yozish SHART EMAS - mavjud
transformatsiyalar nomi bilan chaqiriladi. Agar biror tilga o'ziga xos
tozalash kerak bo'lsa (masalan ruscha predloglar), u shu yerga
`@register("...")` bilan qo'shiladi va boshqa tillarga ta'sir qilmaydi.

SHARTNOMA: transformatsiya HECH QACHON exception tashlamaydi. Qiymat
yaroqsiz bo'lsa `None` qaytaradi - grammatika buni "bu qoida mos kelmadi"
deb tushunadi va keyingi qoidaga o'tadi.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # faqat tip tekshirish uchun - halqali import bo'lmasin
    from .grammar import SlotSpec
    from .words import WordBook

#: (xom_qiymat, so'zlik, slot_tavsifi) -> tozalangan qiymat | None
TransformFn = Callable[[str, "WordBook", "SlotSpec"], Any]

TRANSFORMS: dict[str, TransformFn] = {}


def register(name: str) -> Callable[[TransformFn], TransformFn]:
    def decorator(fn: TransformFn) -> TransformFn:
        TRANSFORMS[name] = fn
        return fn
    return decorator


def get(name: str) -> TransformFn | None:
    return TRANSFORMS.get(name)


def names() -> tuple[str, ...]:
    return tuple(sorted(TRANSFORMS))


@register("text")
def _text(raw: str, book: "WordBook", slot: "SlotSpec") -> str:  # noqa: ARG001
    """Ortiqcha bo'shliqlarni olib tashlaydi. Default transformatsiya."""
    return (raw or "").strip()


@register("lower")
def _lower(raw: str, book: "WordBook", slot: "SlotSpec") -> str:  # noqa: ARG001
    return (raw or "").strip().lower()


@register("number")
def _number(raw: str, book: "WordBook", slot: "SlotSpec") -> int | None:  # noqa: ARG001
    """So'z yoki raqamdan butun son. Son topilmasa None -> qoida o'tkazib yuboriladi."""
    return book.number(raw or "")


@register("strip_affixes")
def _strip_affixes(raw: str, book: "WordBook", slot: "SlotSpec") -> str:  # noqa: ARG001
    """Dastur nomidan kelishik qo'shimchasi va alohida yuklamani olib tashlaydi.

    "google chrome ni" -> "google chrome",  "chromeni" -> "chrome".
    Alias bilan solishtirish uchun kerak: katalogda "chrome" turadi.
    """
    return book.strip_affixes(raw or "")


@register("strip_suffix")
def _strip_suffix(raw: str, book: "WordBook", slot: "SlotSpec") -> str:  # noqa: ARG001
    """Faqat oxirgi so'zning qo'shimchasini kesadi (bir so'zli slotlar uchun)."""
    return book.strip_suffix((raw or "").strip())


_TRAILING_PUNCT = re.compile(r"[.,;:!?]+$")


@register("url")
def _url(raw: str, book: "WordBook", slot: "SlotSpec") -> str | None:  # noqa: ARG001
    """Manzilni tozalaydi. Bo'shliq qolsa - bu manzil emas, qoida mos kelmadi."""
    value = _TRAILING_PUNCT.sub("", (raw or "").strip())
    return value or None

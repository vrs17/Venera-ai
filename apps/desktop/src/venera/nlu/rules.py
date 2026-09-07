"""Qoidaga asoslangan intent aniqlash - YUPQA MOSLIK QATLAMI.

Ilgari bu faylda 20 ta qoida Python regexlari va `build` funksiyalari bilan
yozilgan edi, ya'ni yangi til = yangi Python kodi. Endi qoidalar til
paketining ichida - `resources/i18n/<kod>/rules.yaml` - va ularni
`nlu.grammar` kompilyatsiya qiladi.

Bu modul FAQAT eski chaqiruv nuqtasini saqlab qoladi:

    from venera.nlu.rules import parse
    intent = parse("chromeni och")

`parse()` FAOL tilning grammatikasiga delegatsiya qiladi. Foydalanuvchi
sozlamalarda ruschani tanlasa, aynan shu funksiya ruscha qoidalarni
ishlatadi - chaqiruvchi kodda hech narsa o'zgarmaydi.

Step 3 da LLM qo'shilganda bu yo'l o'chirilmaydi - u "fastpath" bo'lib
qoladi: eng ko'p ishlatiladigan buyruqlar serverga bormasdan, ~0 ms da
bajariladi.
"""

from __future__ import annotations

import logging

from .. import i18n
from .grammar import CompiledRule, Grammar
from .intents import Intent, IntentName

log = logging.getLogger(__name__)


def grammar() -> Grammar:
    """Faol tilning kompilyatsiya qilingan grammatikasi."""
    return i18n.grammar()


def rules() -> tuple[CompiledRule, ...]:
    """Faol tildagi qoidalar - TARTIBI bilan (nosozlik tekshirish uchun)."""
    return grammar().rules


def parse(text: str) -> Intent:
    """Xom matndan Intent. Hech qanday qoida mos kelmasa UNKNOWN.

    Matn tozalash, uyg'otish so'zini kesish va slotlarni to'ldirish
    `Grammar.match()` ichida bo'ladi - u faol tilning `words.yaml` iga
    tayanadi.
    """
    active = grammar()
    if not active.rules:
        # Til paketi topilmadi yoki buzuq. Buyruq tanilmaydi, lekin ilova
        # ishlashda davom etadi va foydalanuvchi "Tushunmadim" javobini oladi.
        log.debug("Grammatika bo'sh (%s) - buyruq tanilmadi", active.code or "?")
        return Intent(name=IntentName.UNKNOWN, raw_text=(text or "").strip(), source="rules")
    return active.match(text)

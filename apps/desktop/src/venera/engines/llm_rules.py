"""Step 1 uchun "LLM": o'zbekcha qoidalar.

Step 3 da haqiqiy LLM qo'shilganda bu modul o'chirilmaydi - u fastpath bo'lib
qoladi: eng ko'p ishlatiladigan buyruqlar serverga bormasdan bajariladi.
"""

from __future__ import annotations

import logging

from ..nlu.intents import Intent
from ..nlu.rules import parse
from .base import HealthStatus, LlmEngine

log = logging.getLogger(__name__)


class RulesLlm(LlmEngine):
    name = "rules"

    async def understand(self, text: str) -> Intent:
        intent = parse(text)
        log.debug("Qoidalar: %r -> %s", text, intent.describe())
        return intent

    async def health(self) -> HealthStatus:
        return HealthStatus(True, "qoidalar - server kerak emas")

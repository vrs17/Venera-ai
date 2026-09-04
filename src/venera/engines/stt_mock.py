"""Step 1 uchun soxta STT.

Haqiqiy tanib olish yo'q - matn oynadagi kiritish maydonidan keladi.
Maqsad: butun pipeline (aktivatsiya -> matn -> intent -> harakat -> ovoz)
serversiz ishlashi va Step 2 da faqat shu fayl almashtirilishi.
"""

from __future__ import annotations

import asyncio
import logging

from .base import HealthStatus, SttEngine

log = logging.getLogger(__name__)


class MockStt(SttEngine):
    name = "mock"

    def __init__(self) -> None:
        self._pending: str = ""

    def submit_text(self, text: str) -> None:
        """UI matn kiritganda chaqiriladi - keyingi transcribe shuni qaytaradi."""
        self._pending = text or ""

    async def transcribe(self, wav_bytes: bytes) -> str:  # noqa: ARG002
        await asyncio.sleep(0)  # haqiqiy STT kabi asinxron bo'lib qolishi uchun
        text, self._pending = self._pending, ""
        if not text:
            log.info("Mock STT: matn yo'q (Step 1 da ovoz tanilmaydi)")
        return text

    async def health(self) -> HealthStatus:
        return HealthStatus(True, "mock - server kerak emas")

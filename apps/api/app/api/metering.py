"""Hisob konteksti: har HTTP so'rovga KANAL qo'yiladi (`X-Venera-Client`).

NEGA MIDDLEWARE. "Kim" (`actorId`) sessiyadan keladi va uni `current_user`
qo'yadi (`deps.py`). Lekin kirish (`/auth/login`) kabi sessiyasiz yo'llarda
ham tashqi chaqiruvlar bor - Keycloak paroli, HRM ulanishi - va ular ham
hisobda qaysi interfeysdan kelgani bilan turishi kerak. Kanal esa faqat
sarlavhaga bog'liq, ya'ni uni so'rov BOSHIDA, hamma narsadan oldin qo'yish
mumkin.

SOF ASGI, `BaseHTTPMiddleware` EMAS: u javob tanasini alohida vazifada
uzatadi va oqimli javoblarda (chat, TTS) o'z muammolari bor. Bu yerda
faqat kontekst o'zgaruvchisi qo'yiladi va so'rov oxirida qaytariladi -
so'rov yo'liga qo'shiladigan ish bitta sarlavha o'qish.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import HTTPConnection

from ..core.channels import channel_of
from ..services.analytics import bind


class ChannelMiddleware:
    """`current_channel` ni so'rov davomida qo'yadi (`analytics.meter`)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        binding = bind(channel=channel_of(HTTPConnection(scope)))
        try:
            await self.app(scope, receive, send)
        finally:
            binding.reset()

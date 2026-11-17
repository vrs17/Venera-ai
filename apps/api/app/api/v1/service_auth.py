"""Boshqa TIZIMLAR (servislar) uchun kalit: `X-Service-Key` sarlavhasi.

Odam tokeni emas - servis chaqiradi (birinchisi: HRM). Serverda kalitning O'ZI saqlanmaydi, faqat
SHA-256 izi (`nom:sha256hex`, vergul bilan): `.env` sizib chiqsa ham kalit ochilmaydi.
Iste'molchilar: STT (`STT_SERVICE_KEYS`, ovozli xabar) va HRM kechikish qarori
(`HRM_LATE_SERVICE_KEYS`, bo'sh bo'lsa STT kalitlari).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque
from typing import Awaitable, Callable

from fastapi import Request

from ...core.errors import unauthorized
from ...services.analytics import bind as _meter_bind


def parse_service_keys(raw: str) -> list[tuple[str, str]]:
    """`nom:sha256hex,...` -> `[(nom, sha256hex)]`; noto'g'ri yozilgan juftlik tashlanadi."""
    out: list[tuple[str, str]] = []
    for item in (raw or "").split(","):
        name, _, digest = item.strip().partition(":")
        name, digest = name.strip(), digest.strip().lower()
        if name and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            out.append((name, digest))
    return out


def match_service_key(presented: str, keys: list[tuple[str, str]]) -> str | None:
    """Kalit -> servis nomi yoki `None`. Hamma iz bilan solishtiriladi (to'xtamasdan) - vaqt farqi
    qaysi kalit "yaqin" ekanini aytmasin."""
    if not presented:
        return None
    digest = hashlib.sha256(presented.encode()).hexdigest()
    name = None
    for candidate, expected in keys:
        if hmac.compare_digest(expected, digest):
            name = candidate
    return name


def service_caller_for(keys: Callable[[], list[tuple[str, str]]]) -> Callable[[Request], Awaitable[str]]:
    """FastAPI bog'liqligi: `X-Service-Key` -> servis nomi; kalit yo'q yoki noto'g'ri - 401.

    `async`, `current_user` dagi sabab bilan: hisob konteksti (`analytics.bind`) so'rov vazifasining
    o'zida qo'yilishi kerak. Odam yo'q (`actor_id=None`), kanal `api` - sarf hisobida servis Barno
    foydalanuvchilariga aralashmaydi. `keys` har so'rovda chaqiriladi (sozlama jonli)."""

    async def caller(request: Request) -> str:
        key = request.headers.get("x-service-key", "").strip()
        if not key:
            raise unauthorized("Servis kaliti yuborilmadi")
        name = match_service_key(key, keys())
        if name is None:
            raise unauthorized("Servis kaliti noto'g'ri")
        _meter_bind(None, "api")
        return name

    return caller


class PerMinuteRate:
    """Servis nomi bo'yicha daqiqalik chegara (60 s sirpanuvchi oyna). Chegara - funksiyadan
    (sozlama jonli). Oshgan so'rov ichki xizmatga TUSHMAYDI - chaqiruvchi 429 oladi."""

    def __init__(self, limit: Callable[[], int]) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._stamps: dict[str, deque[float]] = {}

    def allow(self, name: str) -> bool:
        now = time.monotonic()
        with self._lock:
            stamps = self._stamps.setdefault(name, deque())
            while stamps and now - stamps[0] > 60.0:
                stamps.popleft()
            if len(stamps) >= self._limit():
                return False
            stamps.append(now)
            return True

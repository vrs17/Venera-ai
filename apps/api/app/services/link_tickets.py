"""Bir martalik ulash chiptalari - Slack va Telegram hisobini Barno hisobiga brauzerda ulash.

OQIM (ikkala kanalda bir xil): kanal (Slack ilovasi yoki Telegram Mini App) chipta yasaydi va
odamga brauzer havolasini beradi -> odam Barno'ga kiradi (BRB-Tech ID yoki login + parol) ->
tasdiq sahifasi KIM ulanayotganini ko'rsatadi -> "Ulash" bosilganda ulanish yoziladi. Kanal
identifikatori chiptaning SERVERDAGI yozuvida turadi (Slack hodisasi yoki Telegram imzosidan),
havolada emas.

Chipta tasodifiy (`secrets.token_urlsafe(32)`), `ttl` yashaydi, faqat API jarayoni xotirasida:
jarayon qayta ishga tushsa odam tugmani yana bosadi.
"""

from __future__ import annotations

import secrets
import threading
import time

from typing import Generic, Protocol, TypeVar


class _Created(Protocol):
    created: float


T = TypeVar("T", bound=_Created)

#: Xotira chegarasi (`oidc._MAX_ENTRIES` kabi): oshsa eng eskilarining yarmi tashlanadi.
MAX_TICKETS = 5000


class TicketStore(Generic[T]):
    """`{chipta: yozuv}` - TTL bilan. `peek` yoqmaydi (tasdiq sahifasi ma'lumoti), `pop` yoqadi."""

    def __init__(self, ttl: float, *, max_items: int = MAX_TICKETS) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._lock = threading.Lock()
        self._items: dict[str, T] = {}

    def new(self, ticket: T) -> str:
        """Yangi chipta -> uning qiymati (havolaga shu qo'yiladi)."""
        value = secrets.token_urlsafe(32)
        self.put(value, ticket)
        return value

    def put(self, value: str, ticket: T) -> None:
        with self._lock:
            self._prune()
            self._items[value] = ticket

    def peek(self, value: str) -> T | None:
        if not value:
            return None
        with self._lock:
            self._prune()
            return self._items.get(value)

    def pop(self, value: str) -> T | None:
        if not value:
            return None
        with self._lock:
            self._prune()
            return self._items.pop(value, None)

    def swap(self, value: str, expected: T, ticket: T) -> bool:
        """Almashtiradi - faqat chipta hali AYNAN `expected` bo'lsa (tekshiruv va yozish bitta
        qulf ostida): ikki so'rov bir chiptani bir vaqtda tasdiqlay olmasin."""
        with self._lock:
            self._prune()
            if self._items.get(value) != expected:
                return False
            self._items[value] = ticket
            return True

    def replace(self, value: str, ticket: T) -> bool:
        """Faqat chipta hali bor bo'lsa almashtiradi (muddati o'tgan yoki yoqilganni tiriltirmaydi)."""
        with self._lock:
            self._prune()
            if value not in self._items:
                return False
            self._items[value] = ticket
            return True

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            self._prune()
            return len(self._items)

    def _prune(self) -> None:
        now = time.time()
        for value in [v for v, t in self._items.items() if now - t.created > self.ttl]:
            self._items.pop(value, None)
        if len(self._items) > self.max_items:
            oldest = sorted(self._items.items(), key=lambda kv: kv[1].created)[: len(self._items) // 2]
            for value, _ in oldest:
                self._items.pop(value, None)

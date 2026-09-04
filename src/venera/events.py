"""Thread'lar orasida uzatiladigan xabarlar.

Qoida: UI -> core `loop.call_soon_threadsafe`, core -> UI `queue.put_nowait`.
To'g'ridan-to'g'ri metod chaqiruvi yo'q.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActivationRequested:
    """Hotkey bosildi (Step 5 da: wake word eshitildi)."""

    source: str = "hotkey"


@dataclass(frozen=True)
class TextSubmitted:
    """Foydalanuvchi oynaga matn yozdi - Step 1 da bu STT o'rnini bosadi."""

    text: str
    source: str = "window"


@dataclass(frozen=True)
class CancelRequested:
    source: str = "user"


@dataclass(frozen=True)
class ShutdownRequested:
    pass


@dataclass(frozen=True)
class SessionLocked:
    pass


@dataclass(frozen=True)
class SessionUnlocked:
    pass


@dataclass(frozen=True)
class DeviceLost:
    reason: str = ""


# --- core -> UI ---------------------------------------------------------------

@dataclass(frozen=True)
class StateChanged:
    state: str
    detail: str = ""


@dataclass(frozen=True)
class MicLevel:
    """0.0 .. 1.0 oralig'idagi RMS daraja."""

    level: float
    peak: float = 0.0


@dataclass(frozen=True)
class TurnFinished:
    text: str
    intent: str
    spoken: str
    ok: bool
    elapsed_ms: int = 0


@dataclass(frozen=True)
class Notice:
    """Foydalanuvchiga ko'rsatiladigan qisqa xabar."""

    message: str
    level: str = "info"     # info | warning | error
    extra: dict[str, Any] = field(default_factory=dict)

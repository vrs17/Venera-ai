"""Almashtiriladigan komponentlar interfeysi.

BU FAYL KEYINGI STEPLARDA O'ZGARMAYDI. Step 2-5 da faqat yangi
implementatsiya fayli qo'shiladi va config.yaml dagi bitta qator o'zgaradi:

    Step 2:  engines.stt: mock  -> onprem     (stt_onprem.py)
    Step 3:  engines.llm: rules -> onprem     (llm_onprem.py)
    Step 4:  engines.tts: sapi  -> onprem     (tts_onprem.py)
    Step 5:  engines.activator: hotkey -> wakeword  (activator_wakeword.py)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..nlu.intents import Intent


@dataclass(frozen=True)
class AudioClip:
    """Ijroga tayyor ovoz."""

    pcm: np.ndarray          # int16 mono
    sample_rate: int

    @property
    def duration(self) -> float:
        return self.pcm.size / float(self.sample_rate) if self.sample_rate else 0.0

    @property
    def empty(self) -> bool:
        return self.pcm is None or self.pcm.size == 0

    @classmethod
    def silence(cls) -> "AudioClip":
        return cls(pcm=np.zeros(0, dtype=np.int16), sample_rate=16000)


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str = ""

    def __str__(self) -> str:
        return f"{'ishlayapti' if self.ok else 'ishlamayapti'}: {self.detail}" if self.detail \
            else ("ishlayapti" if self.ok else "ishlamayapti")


class SttEngine(ABC):
    """Ovoz -> matn. Step 2 da on-prem server implementatsiyasi qo'shiladi."""

    name: str = "stt"

    @abstractmethod
    async def transcribe(self, wav_bytes: bytes) -> str:
        ...

    async def health(self) -> HealthStatus:
        return HealthStatus(True)

    async def close(self) -> None:
        return None


class LlmEngine(ABC):
    """Matn -> Intent. Step 3 da vLLM (strict JSON) implementatsiyasi qo'shiladi."""

    name: str = "llm"

    @abstractmethod
    async def understand(self, text: str) -> Intent:
        ...

    async def health(self) -> HealthStatus:
        return HealthStatus(True)

    async def close(self) -> None:
        return None


class TtsEngine(ABC):
    """Matn -> ovoz. Step 4 da on-prem TTS implementatsiyasi qo'shiladi."""

    name: str = "tts"

    @abstractmethod
    async def synthesize(self, text: str) -> AudioClip:
        ...

    async def health(self) -> HealthStatus:
        return HealthStatus(True)

    async def close(self) -> None:
        return None


class Activator(ABC):
    """Ilovani uyg'otuvchi. Step 1: hotkey. Step 5: wake word ("Venera AI Assistant")."""

    name: str = "activator"

    @abstractmethod
    def start(self, on_activate: Callable[[], None]) -> bool:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    def describe(self) -> str:
        return self.name

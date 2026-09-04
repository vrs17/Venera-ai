"""Signal tovushlari (earcon).

Binar fayl saqlamaymiz - hammasi numpy bilan generatsiya qilinadi.
Shunday qilib PyInstaller'ga qo'shimcha resurs kerak emas.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

SAMPLE_RATE = 16000


def _tone(freq: float, ms: int, volume: float = 0.25, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    count = int(sample_rate * ms / 1000)
    t = np.arange(count, dtype=np.float32) / sample_rate
    wave = np.sin(2.0 * np.pi * freq * t)
    # Chertillashning oldini olish uchun kirish/chiqish yumshatiladi
    fade = max(1, int(sample_rate * 0.008))
    envelope = np.ones(count, dtype=np.float32)
    envelope[:fade] = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return (wave * envelope * volume * 32767.0).astype(np.int16)


def _silence(ms: int, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    return np.zeros(int(sample_rate * ms / 1000), dtype=np.int16)


@lru_cache(maxsize=8)
def wake() -> np.ndarray:
    """Tinglashga tayyor: past -> baland."""
    return np.concatenate([_tone(660, 70), _tone(990, 90)])


@lru_cache(maxsize=8)
def done() -> np.ndarray:
    """Buyruq bajarildi: qisqa bitta signal."""
    return _tone(880, 90, volume=0.2)


@lru_cache(maxsize=8)
def error() -> np.ndarray:
    """Xato: baland -> past."""
    return np.concatenate([_tone(440, 90, volume=0.28), _silence(30), _tone(300, 140, volume=0.28)])


@lru_cache(maxsize=8)
def tick() -> np.ndarray:
    """Hech narsa eshitilmadi: juda qisqa, jim."""
    return _tone(520, 45, volume=0.12)

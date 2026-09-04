"""Ovoz ijrosi (TTS javobi va signal tovushlari).

Ijro bekor qilinadigan bo'lishi kerak: foydalanuvchi javob o'rtasida yangi
buyruq bersa (barge-in, Step 5), ijro darhol to'xtaydi.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

try:
    import sounddevice as _sd
except Exception:  # noqa: BLE001
    _sd = None


class AudioPlayer:
    """Bir vaqtda faqat bitta ijro. Yangi ijro eskisini to'xtatadi."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_flag = threading.Event()
        self._playing = False

    @property
    def playing(self) -> bool:
        return self._playing

    def stop(self) -> None:
        self._stop_flag.set()
        if _sd is not None:
            try:
                _sd.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("Ijroni to'xtatishda xato: %s", exc)

    def play(self, pcm: np.ndarray, sample_rate: int, timeout: float = 30.0) -> bool:
        """int16 mono massivni ijro etadi. To'liq ijro bo'lsa True.

        Bu metod bloklaydi - uni asyncio'dan `run_in_executor` bilan chaqiring.
        """
        if _sd is None:
            log.warning("Ovoz chiqarish mumkin emas: sounddevice yo'q")
            return False
        if pcm is None or pcm.size == 0:
            return True

        with self._lock:
            self._stop_flag.clear()
            self._playing = True
            try:
                _sd.play(pcm, samplerate=sample_rate, blocking=False)
            except Exception as exc:  # noqa: BLE001
                log.warning("Ijro boshlanmadi: %s", exc)
                self._playing = False
                return False

            deadline = time.monotonic() + timeout
            try:
                while time.monotonic() < deadline:
                    if self._stop_flag.is_set():
                        _sd.stop()
                        return False
                    try:
                        stream = _sd.get_stream()
                        if stream is None or not stream.active:
                            return True
                    except Exception:  # noqa: BLE001 - oqim allaqachon yopilgan
                        return True
                    time.sleep(0.02)
                log.warning("Ijro %.1f s ichida tugamadi - to'xtatildi", timeout)
                _sd.stop()
                return False
            finally:
                self._playing = False

"""Mikrofondan yozib olish (sounddevice / PortAudio).

Talablar:
  * 16 kHz, mono, int16 - STT serveri (Step 2) aynan shuni kutadi;
  * callback thread'ida hech qanday og'ir ish qilinmaydi (faqat nusxa + queue);
  * qurilma uzilsa yoki kompyuter uyqudan uyg'onsa - qayta ochish;
  * audio qurilmasi umuman yo'q muhitda (WSL, CI) import ham, ishga tushirish ham
    yiqilmasligi kerak - shunchaki "mavjud emas" holati.

WASAPI ustunlik beriladi: MME qurilma nomlarini 31 belgida kesadi.
Exclusive mode HECH QACHON ishlatilmaydi - u mikrofonni Teams/Zoom'dan tortib oladi.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .wav import resample_linear, rms_level

log = logging.getLogger(__name__)

try:  # PortAudio bo'lmasa ham modul import bo'lishi kerak
    import sounddevice as _sd
    SOUNDDEVICE_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001
    _sd = None
    SOUNDDEVICE_ERROR = str(exc)


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    channels: int
    default_samplerate: float
    is_default: bool = False

    def label(self) -> str:
        mark = " (default)" if self.is_default else ""
        return f"[{self.index}] {self.name} - {self.hostapi}, {self.channels}ch{mark}"


def available() -> bool:
    return _sd is not None


def rescan_devices() -> None:
    """PortAudio qurilma ro'yxati init paytidagi snapshot - hotplug uchun qayta skan."""
    if _sd is None:
        return
    try:
        _sd._terminate()
        _sd._initialize()
        log.info("PortAudio qurilma ro'yxati qayta skanerlandi")
    except Exception as exc:  # noqa: BLE001
        log.warning("PortAudio qayta skanerlanmadi: %s", exc)


def list_input_devices() -> list[DeviceInfo]:
    """Kirish qurilmalari ro'yxati. Xato bo'lsa bo'sh ro'yxat."""
    if _sd is None:
        return []
    try:
        devices = _sd.query_devices()
        hostapis = _sd.query_hostapis()
        try:
            default_in = _sd.default.device[0]
        except Exception:  # noqa: BLE001
            default_in = None
    except Exception as exc:  # noqa: BLE001
        log.warning("Qurilmalar ro'yxati olinmadi: %s", exc)
        return []

    result: list[DeviceInfo] = []
    for index, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) < 1:
            continue
        api = hostapis[dev["hostapi"]]["name"] if dev.get("hostapi") is not None else "?"
        result.append(DeviceInfo(
            index=index,
            name=str(dev.get("name", "?")).strip(),
            hostapi=api,
            channels=int(dev.get("max_input_channels", 0)),
            default_samplerate=float(dev.get("default_samplerate", 0.0)),
            is_default=(index == default_in),
        ))
    return result


def pick_device(name_hint: str | None) -> DeviceInfo | None:
    """Qurilma tanlash: nom bo'yicha, WASAPI ustunligi bilan, aks holda default."""
    devices = list_input_devices()
    if not devices:
        return None

    if name_hint:
        hint = name_hint.strip().lower()
        matches = [d for d in devices if hint in d.name.lower()]
        if matches:
            matches.sort(key=lambda d: (0 if "wasapi" in d.hostapi.lower() else 1, d.index))
            return matches[0]
        log.warning("'%s' nomli mikrofon topilmadi - default ishlatiladi", name_hint)

    default = next((d for d in devices if d.is_default), None)
    if default is not None:
        # Windows default qurilmasini odatda MME sifatida qaytaradi, lekin MME
        # nomlarni 31 belgida kesadi va kechikishi kattaroq. Shu qurilmaning
        # WASAPI varianti bo'lsa - o'shani olamiz.
        if "wasapi" not in default.hostapi.lower():
            stem = default.name.split("(")[0].strip().lower() or default.name.lower()
            same = [
                d for d in devices
                if "wasapi" in d.hostapi.lower()
                and (stem in d.name.lower() or d.name.lower().startswith(default.name.lower()[:20]))
            ]
            if same:
                log.debug("Default qurilmaning WASAPI varianti tanlandi: %s", same[0].name)
                return same[0]
        return default

    wasapi = [d for d in devices if "wasapi" in d.hostapi.lower()]
    return (wasapi or devices)[0]


class AudioCapture:
    """Doimiy ochiq mikrofon oqimi + navbat."""

    def __init__(
        self,
        sample_rate: int = 16000,
        blocksize: int = 512,
        device_hint: str | None = None,
        on_level: Callable[[float], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        queue_seconds: float = 30.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.device_hint = device_hint
        self.on_level = on_level
        self.on_error = on_error

        max_blocks = max(8, int(queue_seconds * sample_rate / max(1, blocksize)))
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_blocks)
        self._stream = None
        self._device: DeviceInfo | None = None
        self._native_rate = sample_rate
        self._lock = threading.RLock()
        self._last_callback = 0.0
        self._running = False
        self._overflow_count = 0

    # --- holat ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def device(self) -> DeviceInfo | None:
        return self._device

    def seconds_since_audio(self) -> float:
        if not self._last_callback:
            return float("inf")
        return time.monotonic() - self._last_callback

    def is_alive(self, tolerance: float = 2.0) -> bool:
        """Oqim ochiq, lekin callback kelmayapti -> o'lgan (uyqudan keyin tez-tez uchraydi)."""
        return self._running and self.seconds_since_audio() <= tolerance

    # --- boshqaruv -----------------------------------------------------------

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            if _sd is None:
                self._fail(f"Audio kutubxonasi mavjud emas: {SOUNDDEVICE_ERROR}")
                return False

            device = pick_device(self.device_hint)
            if device is None:
                self._fail("Mikrofon topilmadi")
                return False

            for rate in self._candidate_rates(device):
                try:
                    stream = _sd.InputStream(
                        samplerate=rate,
                        blocksize=self.blocksize,
                        device=device.index,
                        channels=1,
                        dtype="int16",
                        callback=self._callback,
                        extra_settings=self._wasapi_settings(device),
                    )
                    stream.start()
                except Exception as exc:  # noqa: BLE001
                    log.debug("Mikrofon %s @%d Hz ochilmadi: %s", device.name, rate, exc)
                    continue

                self._stream = stream
                self._device = device
                self._native_rate = rate
                self._running = True
                self._last_callback = time.monotonic()
                log.info(
                    "Mikrofon ochildi: %s (%s) @ %d Hz%s",
                    device.name, device.hostapi, rate,
                    "" if rate == self.sample_rate else f" -> {self.sample_rate} Hz resample",
                )
                return True

            self._fail(f"Mikrofon ochilmadi: {device.name}")
            return False

    def stop(self) -> None:
        with self._lock:
            self._running = False
            stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("Mikrofonni yopishda xato: %s", exc)
            else:
                log.info("Mikrofon yopildi")

    def reopen(self, rescan: bool = True) -> bool:
        """Qurilma uzilgan yoki uyqudan keyin o'lgan oqimni tiklaydi."""
        log.info("Mikrofon qayta ochilmoqda (rescan=%s)", rescan)
        self.stop()
        if rescan:
            rescan_devices()
        self.drain()
        return self.start()

    # --- ma'lumot olish ------------------------------------------------------

    def drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def record(self, seconds: float, drain_first: bool = True) -> np.ndarray:
        """Berilgan vaqt davomida yozib oladi va yagona int16 massiv qaytaradi."""
        if drain_first:
            self.drain()
        wanted = int(seconds * self.sample_rate)
        chunks: list[np.ndarray] = []
        collected = 0
        deadline = time.monotonic() + seconds + 2.0

        while collected < wanted and time.monotonic() < deadline:
            chunk = self.read(timeout=0.5)
            if chunk is None:
                continue
            chunks.append(chunk)
            collected += chunk.size

        if not chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(chunks)[:wanted]

    # --- ichki ---------------------------------------------------------------

    def _candidate_rates(self, device: DeviceInfo) -> list[int]:
        rates = [self.sample_rate]
        native = int(device.default_samplerate or 0)
        if native and native != self.sample_rate:
            rates.append(native)
        for fallback in (48000, 44100):
            if fallback not in rates:
                rates.append(fallback)
        return rates

    @staticmethod
    def _wasapi_settings(device: DeviceInfo):
        """WASAPI'da 16 kHz ni shared mode'da avtomatik konvertatsiya qildiramiz."""
        if _sd is None or "wasapi" not in device.hostapi.lower():
            return None
        try:
            return _sd.WasapiSettings(auto_convert=True)
        except Exception:  # noqa: BLE001 - eski sounddevice'da bo'lmasligi mumkin
            return None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        """PortAudio thread'i. Faqat nusxa olish - boshqa hech narsa."""
        if status and status.input_overflow:
            self._overflow_count += 1
        self._last_callback = time.monotonic()
        chunk = np.asarray(indata, dtype=np.int16).reshape(-1).copy()
        if self._native_rate != self.sample_rate:
            chunk = resample_linear(chunk, self._native_rate, self.sample_rate)
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(chunk)
            except queue.Empty:
                pass
        if self.on_level is not None:
            try:
                self.on_level(rms_level(chunk))
            except Exception:  # noqa: BLE001 - UI xatosi audio oqimini to'xtatmasin
                pass

    def _fail(self, message: str) -> None:
        log.warning("%s", message)
        if self.on_error is not None:
            try:
                self.on_error(message)
            except Exception:  # noqa: BLE001
                pass

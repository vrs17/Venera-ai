"""int16 PCM <-> WAV bayt.

STT serveri (Step 2) 16 kHz mono 16-bit PCM WAV kutadi, shuning uchun WAV
sarlavhasi qo'lda yoziladi - `wave` moduli ham ishlaydi, lekin bu yerda
formatni to'liq nazorat qilish muhim.
"""

from __future__ import annotations

import io
import struct
import wave

import numpy as np

RIFF_HEADER_SIZE = 44


def encode_wav(pcm: np.ndarray, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """int16 PCM massivini WAV baytlarga aylantiradi (44 baytlik RIFF sarlavha)."""
    if pcm.dtype != np.int16:
        raise TypeError(f"int16 kutilgan edi, {pcm.dtype} keldi")
    data = pcm.tobytes()
    bits = 16
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8

    header = b"".join((
        b"RIFF",
        struct.pack("<I", 36 + len(data)),
        b"WAVE",
        b"fmt ",
        struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits),
        b"data",
        struct.pack("<I", len(data)),
    ))
    assert len(header) == RIFF_HEADER_SIZE, len(header)
    return header + data


def decode_wav(payload: bytes) -> tuple[np.ndarray, int]:
    """WAV baytlardan (int16 mono massiv, sample_rate) qaytaradi.

    Stereo bo'lsa kanallar o'rtachasi olinadi. 8/24/32-bit ham qo'llab-quvvatlanadi.
    """
    with wave.open(io.BytesIO(payload), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.int32)
    elif width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.int32) - 128) << 8
    elif width == 4:
        samples = (np.frombuffer(frames, dtype="<i4") >> 16).astype(np.int32)
    elif width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        samples = (raw[:, 2] << 8) | raw[:, 1]
        samples = np.where(samples >= 32768, samples - 65536, samples)
    else:
        raise ValueError(f"qo'llab-quvvatlanmaydigan namuna kengligi: {width} bayt")

    if channels > 1:
        usable = (len(samples) // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)

    return np.clip(samples, -32768, 32767).astype(np.int16), rate


def resample_linear(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Oddiy chiziqli resample.

    Qo'shimcha kutubxonasiz ishlaydi. Sifat sezilarli emas, chunki bu faqat
    mikrofon 16 kHz'ni qo'llab-quvvatlamagan holat uchun zaxira yo'l.
    """
    if src_rate == dst_rate or pcm.size == 0:
        return pcm.astype(np.int16, copy=False)
    duration = pcm.size / float(src_rate)
    dst_count = max(1, int(round(duration * dst_rate)))
    src_idx = np.linspace(0.0, pcm.size - 1, num=dst_count, dtype=np.float64)
    out = np.interp(src_idx, np.arange(pcm.size, dtype=np.float64), pcm.astype(np.float64))
    return np.clip(np.rint(out), -32768, 32767).astype(np.int16)


def rms_level(pcm: np.ndarray) -> float:
    """0.0..1.0 oralig'ida RMS daraja (UI ko'rsatkichi uchun)."""
    if pcm.size == 0:
        return 0.0
    values = pcm.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(np.square(values))))


def peak_level(pcm: np.ndarray) -> float:
    if pcm.size == 0:
        return 0.0
    return float(np.max(np.abs(pcm.astype(np.float32))) / 32768.0)


def duration_seconds(pcm: np.ndarray, sample_rate: int) -> float:
    return pcm.size / float(sample_rate) if sample_rate else 0.0

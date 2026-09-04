"""WAV kodlash - Step 2 da STT serveri aynan shu formatni kutadi."""

import struct

import numpy as np
import pytest

from venera.audio.wav import (
    decode_wav, duration_seconds, encode_wav, peak_level, resample_linear, rms_level,
)


@pytest.fixture
def tone():
    t = np.linspace(0, 1, 16000, endpoint=False)
    return (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)


def test_sarlavha_44_bayt_va_togri(tone):
    data = encode_wav(tone, 16000)
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    assert data[12:16] == b"fmt "
    assert data[36:40] == b"data"
    assert len(data) == 44 + tone.nbytes

    fmt = struct.unpack("<IHHIIHH", data[16:36])
    size, audio_format, channels, rate, byte_rate, block_align, bits = fmt
    assert (size, audio_format, channels, rate, bits) == (16, 1, 1, 16000, 16)
    assert byte_rate == 16000 * 2
    assert block_align == 2


def test_roundtrip(tone):
    back, rate = decode_wav(encode_wav(tone, 16000))
    assert rate == 16000
    assert np.array_equal(back, tone)


def test_int16_talab_qilinadi():
    with pytest.raises(TypeError):
        encode_wav(np.zeros(10, dtype=np.float32), 16000)


def test_bosh_massiv():
    data = encode_wav(np.zeros(0, dtype=np.int16), 16000)
    assert len(data) == 44
    back, _ = decode_wav(data)
    assert back.size == 0


def test_resample(tone):
    out = resample_linear(tone, 16000, 8000)
    assert out.dtype == np.int16
    assert abs(out.size - 8000) <= 1
    assert np.array_equal(resample_linear(tone, 16000, 16000), tone)


def test_darajalar(tone):
    assert 0.0 < rms_level(tone) < 1.0
    assert 0.0 < peak_level(tone) <= 1.0
    assert rms_level(np.zeros(100, dtype=np.int16)) == 0.0
    assert duration_seconds(tone, 16000) == pytest.approx(1.0)


def test_stereo_monoga_aylanadi():
    left = np.full(100, 1000, dtype=np.int16)
    right = np.full(100, 3000, dtype=np.int16)
    stereo = np.empty(200, dtype=np.int16)
    stereo[0::2], stereo[1::2] = left, right
    payload = encode_wav(stereo, 16000, channels=2)
    mono, _ = decode_wav(payload)
    assert mono.size == 100
    assert np.allclose(mono, 2000, atol=1)

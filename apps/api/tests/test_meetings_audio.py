"""Audio yordamchilari: ADTS o'lchash, MP4 `mvhd`, bo'lish va m4a remux (spetsifikatsiya 5.6)."""

from __future__ import annotations

import struct

from app.services.meetings import audio
from meetings_fakes import adts_bytes


def _boxes(data: bytes, start: int = 0, end: int | None = None) -> list[tuple[str, int, int]]:
    end = len(data) if end is None else end
    out, pos = [], start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        out.append((kind.decode(), pos, size))
        pos += size
    return out


def _find(data: bytes, path: list[str]) -> tuple[int, int]:
    start, end = 0, len(data)
    pos = size = 0
    for name in path:
        for kind, pos, size in _boxes(data, start, end):
            if kind == name:
                break
        else:
            raise AssertionError(f"{name} yo'q")
        header = 8
        if name == "stsd":
            header = 16
        elif name == "mp4a":
            header = 36
        start, end = pos + header, pos + size
    return pos, size


def test_adts_davomiylik_va_kesilgan_oxir(tmp_path):
    path = tmp_path / "a.aac"
    frames = b"".join(audio.adts_frame(100) for _ in range(250))
    path.write_bytes(frames + audio.adts_frame(80)[:30])          # yiqilishda kesilgan kadr
    info = audio.adts_info(path)
    assert info.frames == 250 and info.sampleRate == 16000 and info.channels == 1
    assert info.durationSec == round(250 * 1024 / 16000, 2)
    assert info.validBytes == len(frames)
    assert audio.measure(path, "audio/aac") == info.durationSec


def test_adts_crc_sarlavha_va_yaroqsiz(tmp_path):
    path = tmp_path / "c.aac"
    path.write_bytes(b"".join(audio.adts_frame(50, crc=True) for _ in range(10)))
    assert audio.adts_info(path).frames == 10
    bad = tmp_path / "bad.aac"
    bad.write_bytes(b"not audio at all")
    assert audio.adts_info(bad) is None


def test_sniff():
    assert audio.sniff(audio.adts_frame(10), "audio/aac")
    assert not audio.sniff(b"RIFF....", "audio/aac")
    assert audio.sniff(b"\0\0\0\x18ftypM4A ", "audio/mp4")
    assert not audio.sniff(b"\xff\xf1", "audio/mp4")


def test_split_adts(tmp_path):
    path = tmp_path / "long.aac"
    path.write_bytes(adts_bytes(25.0))
    pieces = audio.split_adts(path, 10.0, tmp_path)
    durations = [audio.adts_info(p).durationSec for p in pieces]
    assert len(pieces) == 3 and all(d <= 10.0 for d in durations)
    assert abs(sum(durations) - audio.adts_info(path).durationSec) < 0.01
    assert b"".join(p.read_bytes() for p in pieces) == path.read_bytes()


def test_adts_to_m4a_qutilar_va_davomiylik(tmp_path):
    src = tmp_path / "a.aac"
    src.write_bytes(b"".join(audio.adts_frame(100 + i % 7, crc=(i % 3 == 0)) for i in range(160)))
    dst = tmp_path / "a.m4a"
    result = audio.adts_to_m4a(src, dst)
    assert result == {"samples": 160, "durationSec": 10.24, "sampleRate": 16000}
    data = dst.read_bytes()
    top = [k for k, _, _ in _boxes(data)]
    assert top == ["ftyp", "moov", "mdat"]                       # faststart: moov mdat dan oldin
    assert audio.mp4_duration(dst) == 10.24
    pos, size = _find(data, ["moov", "trak", "mdia", "minf", "stbl", "stsz"])
    count = struct.unpack(">I", data[pos + 16:pos + 20])[0]
    assert count == 160
    pos, _ = _find(data, ["moov", "trak", "mdia", "minf", "stbl", "stco"])
    offset = struct.unpack(">I", data[pos + 16:pos + 20])[0]
    mdat = [p for k, p, _ in _boxes(data) if k == "mdat"][0]
    assert offset == mdat + 8
    # mdat da sarlavhasiz xom AAC - hajmi kadrlar yig'indisi.
    expected = sum((100 + i % 7) for i in range(160))
    assert len(data) - (mdat + 8) == expected
    pos, size = _find(data, ["moov", "trak", "mdia", "minf", "stbl", "stsd", "mp4a", "esds"])
    assert size > 20
    assert audio.measure(dst, "audio/mp4") == 10.24

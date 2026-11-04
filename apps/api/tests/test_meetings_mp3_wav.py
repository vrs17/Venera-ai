"""MP3 va WAV yozuvlar (ega, 2026-10-22: "serverga mp3 va wav ham qabul qilinsin").

Kompyuterdagi tayyor yozuvlar (diktofon, Zoom, Telegram) ko'pincha mp3 yoki wav. Server
ularni ffmpeg'siz taniydi, o'lchaydi, GAPI ga to'g'ri nom bilan yuboradi, Router (ru/en)
uchun kadr/blok chegarasida bo'ladi va pleyerga asl formatda beradi.

MP3 kodlovchisi yo'q - test kadrlari HAQIQIY sarlavhali, ichi nol (o'lchov faqat sarlavhani o'qiydi).
"""

from __future__ import annotations

import io
import struct
import wave

import pytest

from app.services.meetings import audio, transcribe
from meetings_fakes import adts_bytes, complete, create_meeting, enable, run_all, upload_all

#: MPEG-1 Layer III, 128 kbit/s, 44,1 kHz: 417 bayt (+1 to'ldirish), 1152 namuna.
MPEG1_LEN = 144 * 128000 // 44100
#: MPEG-2 Layer III, 64 kbit/s, 22,05 kHz: 208 bayt, 576 namuna.
MPEG2_LEN = 72 * 64000 // 22050


def mp3_frame(*, mpeg2: bool = False, pad: int = 0, body: bytes = b"") -> bytes:
    if mpeg2:
        head, length = bytes([0xFF, 0xF3, 0x80 | (pad << 1), 0xC4]), MPEG2_LEN + pad
    else:
        head, length = bytes([0xFF, 0xFB, 0x90 | (pad << 1), 0x64]), MPEG1_LEN + pad
    return head + (body + bytes(length))[:length - 4]


def syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def mp3_bytes(frames: int, *, id3: bool = True, xing: bool = False, mpeg2: bool = False) -> bytes:
    out = b""
    if id3:
        tag = b"TIT2" + struct.pack(">I", 9) + b"\0\0" + b"\x03Majlis\0\0"
        out += b"ID3" + bytes([4, 0, 0]) + syncsafe(len(tag)) + tag
    if xing:
        out += mp3_frame(mpeg2=mpeg2, body=bytes(32) + b"Xing")
    for i in range(frames):
        out += mp3_frame(mpeg2=mpeg2, pad=1 if i % 3 == 0 else 0)
    return out


def wav_bytes(seconds: float, *, rate: int = 16000, channels: int = 1, trailer: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate * channels))
    return buf.getvalue() + trailer


LIST_CHUNK = b"LIST" + struct.pack("<I", 26) + b"INFO" + b"ISFT" + struct.pack("<I", 14) + b"Lavf60.16.100\0"


def _write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_turlar_taxalluslari():
    assert audio.canonical_type("audio/mp3") == "audio/mpeg"
    assert audio.canonical_type(" Audio/X-WAV; codecs=1 ") == "audio/wav"
    assert audio.canonical_type("audio/x-m4a") == "audio/mp4"
    assert audio.canonical_type("audio/aac") == "audio/aac"
    assert audio.canonical_type("audio/ogg") == "audio/ogg"          # noma'lum - o'zgarmaydi, keyin rad etiladi


def test_mp3_sarlavha_va_adts_aralashmaydi():
    frame = mp3_frame()
    assert audio.sniff(frame, "audio/mpeg") and audio.sniff(b"ID3\x04\0\0", "audio/mp3")
    adts = adts_bytes(2)
    # ADTS ham 0xFFF bilan boshlanadi, lekin qatlam bitlari 00 - MP3 emas (va aksincha).
    assert not audio.sniff(adts[:64], "audio/mpeg") and audio.mp3_header(adts[:4]) is None
    assert not audio.sniff(frame[:64], "audio/aac")
    assert not audio.sniff(b"RIFF\0\0\0\0WAVE", "audio/mpeg")
    assert audio.sniff(wav_bytes(0.1)[:64], "audio/wav") and not audio.sniff(frame[:64], "audio/wav")


def test_mp3_davomiyligi(tmp_path):
    # 100 kadr MPEG-1 + ID3 teg: 100 * 1152 / 44100.
    path = _write(tmp_path, "a.mp3", mp3_bytes(100))
    assert audio.measure(path, "audio/mpeg") == round(100 * 1152 / 44100, 2)
    # Xing/Info kadri ovoz emas - sanalmaydi.
    xing = _write(tmp_path, "x.mp3", mp3_bytes(100, xing=True))
    info = audio.mp3_info(xing)
    assert info.frames == 100 and info.durationSec == round(100 * 1152 / 44100, 2)
    # MPEG-2 (22,05 kHz) - kadrda 576 namuna.
    low = _write(tmp_path, "l.mp3", mp3_bytes(200, id3=False, mpeg2=True))
    assert audio.measure(low, "audio/mpeg") == round(200 * 576 / 22050, 2)
    # O'rtadagi axlat: keyingi haqiqiy kadr topiladi, HAMMA ovoz o'lchanadi (kvota aylanib o'tilmasin).
    broken = _write(tmp_path, "b.mp3", mp3_bytes(50) + b"\x13\x37" * 101 + mp3_bytes(150, id3=False))
    assert audio.measure(broken, "audio/mpeg") == round(200 * 1152 / 44100, 2)
    # Oxirida ID3v1 "TAG" - kadr emas.
    tagged = _write(tmp_path, "t.mp3", mp3_bytes(100) + b"TAG" + bytes(125))
    assert audio.measure(tagged, "audio/mpeg") == round(100 * 1152 / 44100, 2)
    # MP3 emas (bitta tasodifiy 0xFF) - o'lchov yo'q -> `unsupported_format`.
    assert audio.measure(_write(tmp_path, "n.mp3", b"\xff\xfb\x90\x64" + bytes(50)), "audio/mpeg") is None


def test_wav_davomiyligi(tmp_path):
    assert audio.measure(_write(tmp_path, "a.wav", wav_bytes(3)), "audio/wav") == 3.0
    stereo = audio.wav_info(_write(tmp_path, "s.wav", wav_bytes(2, rate=44100, channels=2)))
    assert stereo.durationSec == 2.0 and stereo.byteRate == 44100 * 4 and stereo.blockAlign == 4
    # `data` dan keyingi LIST bo'lagi ovoz emas.
    assert audio.measure(_write(tmp_path, "l.wav", wav_bytes(3, trailer=LIST_CHUNK)), "audio/wav") == 3.0
    # Oqim yozuvi (hajm noma'lum: 0xFFFFFFFF) - faylning qolgani.
    raw = bytearray(wav_bytes(4))
    at = raw.index(b"data")
    raw[at + 4:at + 8] = b"\xff\xff\xff\xff"
    assert audio.measure(_write(tmp_path, "o.wav", bytes(raw)), "audio/wav") == 4.0
    assert audio.measure(_write(tmp_path, "x.wav", b"RIFF\0\0\0\0WAVEjunk"), "audio/wav") is None


def test_router_uchun_bolaklash(tmp_path):
    wav = _write(tmp_path, "w.wav", wav_bytes(25))
    pieces = audio.split_plain(wav, "audio/wav", 10, tmp_path / "p" if (tmp_path / "p").mkdir() is None else None)
    assert [round(length, 1) for _, length in pieces] == [10.0, 10.0, 5.0]
    for piece, length in pieces:
        with wave.open(str(piece)) as w:                      # har bo'lak o'zi to'liq WAV
            assert w.getframerate() == 16000 and w.getnframes() == int(length * 16000)
    # Bayt chegarasi: sifatli WAV bo'lagi Router'ning 25 MB chegarasidan oshmasin.
    big = audio.split_plain(_write(tmp_path, "b.wav", wav_bytes(6, rate=44100, channels=2)), "audio/wav", 540,
                            tmp_path / "p", max_bytes=400_000)
    assert len(big) > 1 and all(p.stat().st_size <= 400_000 for p, _ in big)
    assert round(sum(length for _, length in big), 2) == 6.0
    mp3 = _write(tmp_path, "m.mp3", mp3_bytes(1000))
    parts = audio.split_plain(mp3, "audio/mpeg", 10, tmp_path / "p")
    assert len(parts) == 3 and all(length <= 10 for _, length in parts)
    assert round(sum(length for _, length in parts), 2) == round(1000 * 1152 / 44100, 2)
    for piece, _ in parts:
        data = piece.read_bytes()
        assert audio.mp3_header(data[:4]) is not None and not data.startswith(b"ID3")


def test_api_mp3_va_wav_qabul_qilinadi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    rt = _isolated_meetings
    mp3 = mp3_bytes(2000)                          # ~52 s
    wav = wav_bytes(40)
    made = {}
    for ct, data, canonical, ext in (("audio/mp3", mp3, "audio/mpeg", ".mp3"), ("audio/x-wav", wav, "audio/wav", ".wav")):
        m = create_meeting(client, auth, contentType=ct)
        upload_all(client, auth, m["id"], data, chunk=64 * 1024)
        res = complete(client, auth, m["id"], data)
        assert res.status_code == 202, res.text
        row = rt.store.meeting_any(m["id"])
        assert row["content_type"] == canonical and row["audio_path"].endswith(ext)
        made[canonical] = (m["id"], res.json()["durationSec"])
    assert made["audio/mpeg"][1] == round(2000 * 1152 / 44100, 2) and made["audio/wav"][1] == 40.0
    run_all(rt)
    # O'zbekcha - GAPI: asl format, to'g'ri kontent turi bilan.
    assert sorted(s["contentType"] for s in rt.gapi.submits) == ["audio/mpeg", "audio/wav"]
    for canonical, (mid, _) in made.items():
        assert rt.store.meeting_any(mid)["status"] == "ready"
        played = client.get(f"/api/v1/meetings/{mid}/audio", headers=auth)
        assert played.status_code == 200 and played.headers["content-type"].startswith(canonical)
        saved = client.get(f"/api/v1/meetings/{mid}/audio?download=1", headers=auth)
        assert audio.EXTENSIONS[canonical] in saved.headers["content-disposition"]
    # Konfiguratsiya ilovaga yangi turlarni aytadi; noma'lum tur - 415.
    cfg = client.get("/api/v1/meetings/config", headers=auth).json()
    assert {"audio/mpeg", "audio/wav"} <= set(cfg["acceptedContentTypes"])
    bad = client.post("/api/v1/meetings", headers=auth, json={
        "clientId": "6f2c1d0e-1b1a-4c55-9a7e-0e8a1b2c3d4e", "recordedAt": "2026-10-22T10:00:00Z", "contentType": "audio/flac"})
    assert bad.status_code == 415


def test_api_soxta_mp3_rad_etiladi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    m = create_meeting(client, auth, contentType="audio/mpeg")
    # Birinchi bo'lak MP3 ga o'xshamaydi (ADTS) - darhol 415.
    data = adts_bytes(5)
    res = client.put(f"/api/v1/meetings/{m['id']}/audio?offset=0", content=data,
                     headers={**auth, "Content-Type": "application/octet-stream"})
    assert res.status_code == 415


def test_ruscha_mp3_va_wav_router_ga_bolaklab(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    monkeypatch.setattr(transcribe, "ROUTER_PIECE_SEC", 20)
    rt = _isolated_meetings
    for ct, data in (("audio/wav", wav_bytes(50)), ("audio/mpeg", mp3_bytes(2000))):
        m = create_meeting(client, auth, contentType=ct, language="ru")
        upload_all(client, auth, m["id"], data, chunk=64 * 1024)
        assert complete(client, auth, m["id"], data).status_code == 202
    run_all(rt)
    types = [c["contentType"] for c in rt.router.calls]
    # 50 s wav -> 3 bo'lak, ~52 s mp3 -> 3 bo'lak; har biri o'z formatida.
    assert types == ["audio/wav"] * 3 + ["audio/mpeg"] * 3
    assert not rt.gapi.submits

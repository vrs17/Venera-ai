"""OGG (Opus) - Telegram ovozli xabari: tanish, davomiylik, Router uchun sahifa bo'yicha bo'lish,
yig'ilish yaratish va GAPI fayl nomi."""

from __future__ import annotations

import struct

import pytest

from app.services.meetings import audio
from app.services.meetings.audio import iter_ogg_pages, ogg_crc, ogg_info, split_ogg
from meetings_fakes import create_meeting, enable, ogg_opus_bytes, put_chunk, sha


def test_ogg_tanish_va_davomiylik(tmp_path):
    data = ogg_opus_bytes(64.0, pre_skip=312)
    path = tmp_path / "v.ogg"
    path.write_bytes(data)
    assert audio.sniff(data[:16], "audio/ogg") and not audio.sniff(data[:16], "audio/aac")
    assert audio.canonical_type("audio/opus") == audio.canonical_type("application/ogg") == "audio/ogg"
    info = ogg_info(path)
    assert info is not None and info.durationSec == 64.0 and info.preSkip == 312 and info.headerPages == 2
    assert audio.measure(path, "audio/ogg") == 64.0
    # Oxiri yarim sahifa (yiqilgan yozuv) - to'liq sahifalargacha o'lchanadi.
    (tmp_path / "cut.ogg").write_bytes(data[:-40])
    assert 0 < audio.measure(tmp_path / "cut.ogg", "audio/ogg") < 64.0
    (tmp_path / "x.ogg").write_bytes(b"OggS" + b"\0" * 40)
    assert ogg_info(tmp_path / "x.ogg") is None


def test_ogg_crc_har_sahifada_togri():
    data = ogg_opus_bytes(3.0)
    offset = 0
    while offset < len(data):
        count = data[offset + 26]
        length = 27 + count + sum(data[offset + 27:offset + 27 + count])
        page = bytearray(data[offset:offset + length])
        stored = struct.unpack("<I", page[22:26])[0]
        page[22:26] = b"\0\0\0\0"
        assert ogg_crc(bytes(page)) == stored
        offset += length


def test_ogg_bolaklar_sarlavhali_va_ketma_ket(tmp_path):
    path = tmp_path / "long.ogg"
    path.write_bytes(ogg_opus_bytes(30.0, per_page=50))          # 1 s li sahifalar
    pieces = split_ogg(path, 10, tmp_path)
    assert [round(sec) for _, sec in pieces] == [10, 10, 10]
    assert sum(sec for _, sec in pieces) == 30.0
    for piece, _ in pieces:
        pages = list(iter_ogg_pages(piece))
        assert [p.flags & 0x02 for p in pages][:2] == [2, 0] and pages[-1].flags & 0x04
        assert [p.offset for p in pages] == sorted(p.offset for p in pages)
        data = piece.read_bytes()
        assert data[:4] == b"OggS" and ogg_info(piece).headerPages == 2
        # Tartib raqamlari 0 dan ketma-ket, CRC har sahifada to'g'ri.
        seqs = [struct.unpack("<I", data[p.offset + 18:p.offset + 22])[0] for p in pages]
        assert seqs == list(range(len(pages)))
    # Bayt chegarasi ham ishlaydi.
    small = split_ogg(path, 600, tmp_path / "b", max_bytes=400) if (tmp_path / "b").mkdir() is None else []
    assert len(small) > 3 and all(piece.stat().st_size <= 400 for piece, _ in small)


def test_ogg_yigilish_yaratiladi_va_olchanadi(client, auth, monkeypatch, _isolated_meetings):
    from app.services.integrations.gapi_stt import _MEETING_FILENAMES

    enable(monkeypatch)
    data = ogg_opus_bytes(12.0)
    meeting = create_meeting(client, auth, contentType="audio/ogg", source="share")
    assert put_chunk(client, auth, meeting["id"], 0, data).status_code == 200
    done = client.post(f"/api/v1/meetings/{meeting['id']}/complete", json={"totalBytes": len(data), "sha256": sha(data)},
                       headers=auth)
    assert done.status_code in (200, 202), done.text
    assert done.json()["durationSec"] == 12.0
    assert _MEETING_FILENAMES["audio/ogg"] == "meeting.ogg"
    bad = create_meeting(client, auth, contentType="audio/ogg")
    assert put_chunk(client, auth, bad["id"], 0, b"RIFF" + b"\0" * 100).status_code == 415


def test_router_ogg_bolaklab_yuboradi(client, auth, monkeypatch, _isolated_meetings):
    from app.services.meetings import transcribe
    from meetings_fakes import run_all

    rt = _isolated_meetings
    enable(monkeypatch)
    monkeypatch.setattr(transcribe, "ROUTER_PIECE_SEC", 10)
    data = ogg_opus_bytes(30.0, per_page=50)
    meeting = create_meeting(client, auth, contentType="audio/ogg", language="ru", source="share")
    put_chunk(client, auth, meeting["id"], 0, data)
    client.post(f"/api/v1/meetings/{meeting['id']}/complete", json={"totalBytes": len(data), "sha256": sha(data)},
                headers=auth)
    run_all(rt)
    row = rt.store.meeting_any(meeting["id"])
    assert row["stt_engine"] == "router" and int(row["transcript_rev"] or 0) >= 1
    assert [c["contentType"] for c in rt.router.calls] == ["audio/ogg"] * 3
    assert all(c["size"] > 0 for c in rt.router.calls)

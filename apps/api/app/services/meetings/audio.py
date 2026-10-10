"""Audio yordamchilari - SOF PYTHON, ffmpeg'siz (spetsifikatsiya 5.6).

NEGA ffmpeg EMAS. Serverda ffmpeg yo'q va yangi tizim bog'liqligi qo'shish
deploy'ni murakkablashtiradi. Bizga kerak bo'lgan ish esa oddiy:

  * ADTS (`.aac`) - har kadrning 7 (yoki 9) baytli sarlavhasi bor va uzunligi
    13 bitda yozilgan. Kadrlarni sanash = davomiylik (`kadr * 1024 / chastota`).
    Ilova yiqilganda fayl oxiri yarim kadr bo'lib qoladi - o'sha yerda to'xtaydi.
    O'RTADA buzilgan bayt bo'lsa esa keyingi haqiqiy kadr QIDIRILADI (resync):
    STT dekoderi ham shunday qiladi, ya'ni GAPI ga ketadigan HAMMA audio
    o'lchanadi. Aks holda "20 s + 3 bayt axlat + 3 soat" fayl 20 s deb
    hisoblanib, kvota va `max_minutes` cheklovlaridan o'tib ketardi.
  * MP4 davomiyligi - `mvhd` (ilova yozgan sarlavha) VA audio trekning o'zi
    (`stsz` kadrlar soni * 1024 / chastota, `stts` yig'indisi): kattasi olinadi.
    Sarlavhadagi raqamni o'zgartirib kvotani aylanib o'tib bo'lmasin.
  * ADTS -> m4a (`adts_to_m4a`): telefon pleyeri ADTS da ixtiyoriy joyga
    o'ta olmaydi (indeks yo'q), m4a da `stts/stsz/stco` jadvallari bor - tap
    qilib kerakli soniyaga sakrash shunga tayanadi. `moov` boshida
    (faststart): pleyer butun faylni yuklamay o'ynay boshlaydi.
"""

from __future__ import annotations

import os
import struct

from dataclasses import dataclass
from pathlib import Path

#: ADTS `sampling_frequency_index` -> Hz.
SAMPLE_RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)


@dataclass
class AdtsFrame:
    offset: int          # fayldagi boshlanishi (sarlavha bilan)
    length: int          # sarlavha bilan
    header: int          # 7 yoki 9 (CRC bilan)
    blocks: int          # raw_data_block soni (odatda 1)


@dataclass
class AdtsInfo:
    frames: int
    sampleRate: int
    channels: int
    durationSec: float
    profile: int            # MPEG-4 audio object type - 1 (AAC-LC = 1)
    sampleRateIndex: int
    validBytes: int         # oxirgi to'liq kadrgacha
    skippedBytes: int = 0   # kadrlar orasidagi tashlab o'tilgan (buzilgan) baytlar

    def as_dict(self) -> dict:
        return {"frames": self.frames, "sampleRate": self.sampleRate, "channels": self.channels,
                "durationSec": self.durationSec, "profile": self.profile}


def _parse_header(buf: bytes) -> tuple[int, int, int, int, int, int] | None:
    """(length, header_len, profile, sr_index, channels, blocks) yoki `None`."""
    if len(buf) < 7 or buf[0] != 0xFF or (buf[1] & 0xF0) != 0xF0:
        return None
    if (buf[1] >> 1) & 0x03:          # layer har doim 0
        return None
    protection_absent = buf[1] & 0x01
    profile = (buf[2] >> 6) & 0x03
    sr_index = (buf[2] >> 2) & 0x0F
    channels = ((buf[2] & 0x01) << 2) | ((buf[3] >> 6) & 0x03)
    length = ((buf[3] & 0x03) << 11) | (buf[4] << 3) | ((buf[5] >> 5) & 0x07)
    blocks = (buf[6] & 0x03) + 1
    header = 7 if protection_absent else 9
    if sr_index >= len(SAMPLE_RATES) or length <= header:
        return None
    return length, header, profile, sr_index, channels, blocks


def _frame_at(fh, offset: int, size: int, params: tuple[int, int, int] | None):
    """`offset` da shu oqimga mos kadr sarlavhasi bo'lsa - uni o'qiydi."""
    fh.seek(offset)
    parsed = _parse_header(fh.read(9))
    if parsed is None:
        return None
    length, header, profile, sr_index, channels, blocks = parsed
    if params is not None and (profile, sr_index, channels) != params:
        return None
    return parsed


def _resync(fh, start: int, size: int, params: tuple[int, int, int] | None) -> int | None:
    """Buzilgan joydan keyingi HAQIQIY kadrni qidiradi: sinxro so'z, bir xil
    parametrlar VA uning ortidan yana kadr (yoki fayl oxiri) - tasodifiy 0xFFF
    audio ichida ham uchrashadi, ikki ketma-ket sarlavha esa yo'q."""
    block = 64 * 1024
    pos = start
    while pos + 7 <= size:
        fh.seek(pos)
        buf = fh.read(block + 8)
        if len(buf) < 7:
            return None
        i = buf.find(b"\xff")
        while 0 <= i < min(len(buf) - 1, block):
            if (buf[i + 1] & 0xF6) == 0xF0:
                candidate = pos + i
                parsed = _frame_at(fh, candidate, size, params)
                if parsed is not None:
                    nxt = candidate + parsed[0]
                    if nxt == size or (nxt + 7 <= size and _frame_at(fh, nxt, size, params) is not None):
                        return candidate
            i = buf.find(b"\xff", i + 1)
        pos += block
    return None


def iter_frames(path: Path | str, stats: dict | None = None):
    """Kadrlarni ketma-ket beradi. Fayl oxiridagi yarim kadrda TO'XTAYDI; o'rtadagi
    buzilgan baytlardan keyin keyingi haqiqiy kadrni topib DAVOM etadi.
    `stats["skipped"]` - tashlab o'tilgan baytlar."""
    size = os.path.getsize(path)
    params: tuple[int, int, int] | None = None
    skipped = 0
    with open(path, "rb") as fh:
        offset = 0
        while offset + 7 <= size:
            parsed = _frame_at(fh, offset, size, params)
            if parsed is not None and offset + parsed[0] > size:
                break                  # yiqilishda kesilgan oxirgi kadr
            if parsed is None:
                found = _resync(fh, offset + 1, size, params)
                if found is None:
                    break
                skipped += found - offset
                offset = found
                continue
            length, header, profile, sr_index, channels, blocks = parsed
            params = (profile, sr_index, channels)
            yield AdtsFrame(offset, length, header, blocks), params
            offset += length
    if stats is not None:
        stats["skipped"] = skipped


def adts_info(path: Path | str) -> AdtsInfo | None:
    """ADTS fayl haqida. Birorta to'liq kadr bo'lmasa `None`."""
    frames = samples = valid = 0
    first: tuple[int, int, int] | None = None
    stats: dict = {}
    for frame, params in iter_frames(path, stats):
        if first is None:
            first = params
        frames += 1
        samples += 1024 * frame.blocks
        valid = frame.offset + frame.length
    if not frames or first is None:
        return None
    profile, sr_index, channels = first
    rate = SAMPLE_RATES[sr_index]
    return AdtsInfo(frames=frames, sampleRate=rate, channels=channels,
                    durationSec=round(samples / rate, 2), profile=profile,
                    sampleRateIndex=sr_index, validBytes=valid, skippedBytes=int(stats.get("skipped") or 0))


def sniff(first: bytes, content_type: str) -> bool:
    """Birinchi bo'lak e'lon qilingan formatga mosmi (`PUT /audio`, offset 0)."""
    if content_type == "audio/aac":
        return len(first) >= 2 and first[0] == 0xFF and (first[1] & 0xF0) == 0xF0
    if content_type == "audio/mp4":
        return len(first) >= 8 and first[4:8] == b"ftyp"
    return False


# --- MP4 o'qish -------------------------------------------------------------------


def _boxes(fh, start: int, end: int):
    """(type, payload_start, box_end) - `start..end` oralig'idagi qutilar."""
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        head = fh.read(8)
        if len(head) < 8:
            return
        size, kind = struct.unpack(">I4s", head)
        payload = pos + 8
        if size == 1:
            ext = fh.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            payload = pos + 16
        elif size == 0:
            size = end - pos
        if size < 8 or pos + size > end:
            return
        yield kind.decode("latin-1"), payload, pos + size
        pos += size


def _child(fh, start: int, end: int, name: str) -> tuple[int, int] | None:
    for kind, payload, box_end in _boxes(fh, start, end):
        if kind == name:
            return payload, box_end
    return None


def _track_seconds(fh, trak: tuple[int, int]) -> float | None:
    """Audio trekning HAQIQIY davomiyligi: `stsz` kadrlar soni * 1024 / chastota
    (AAC kadri doim 1024 namuna) va `stts` yig'indisi / `mdhd` vaqt shkalasi - kattasi."""
    mdia = _child(fh, *trak, "mdia")
    if mdia is None:
        return None
    hdlr = _child(fh, *mdia, "hdlr")
    if hdlr is not None:
        fh.seek(hdlr[0] + 8)
        if fh.read(4) != b"soun":
            return None
    timescale = None
    mdhd = _child(fh, *mdia, "mdhd")
    if mdhd is not None:
        fh.seek(mdhd[0])
        version = fh.read(4)[:1]
        data = fh.read(20 if version == b"\x01" else 8)
        if len(data) >= 8:
            timescale = struct.unpack(">I", data[16:20] if version == b"\x01" else data[4:8])[0] or None
    minf = _child(fh, *mdia, "minf")
    stbl = _child(fh, *minf, "stbl") if minf else None
    if stbl is None:
        return None
    best = 0.0
    stts = _child(fh, *stbl, "stts")
    if stts is not None and timescale:
        fh.seek(stts[0] + 4)
        entries = struct.unpack(">I", fh.read(4) or b"\0\0\0\0")[0]
        total = 0
        for _ in range(min(entries, 1_000_000)):
            pair = fh.read(8)
            if len(pair) < 8:
                break
            count, delta = struct.unpack(">II", pair)
            total += count * delta
        best = max(best, total / timescale)
    rate = None
    stsd = _child(fh, *stbl, "stsd")
    if stsd is not None:
        # stsd: 4 (versiya) + 4 (soni) + yozuv: 8 (o'lcham+tur) + 16 + 2+2+4 + chastota (16.16).
        fh.seek(stsd[0] + 8 + 8 + 16 + 8)
        raw = fh.read(4)
        if len(raw) == 4:
            rate = struct.unpack(">I", raw)[0] >> 16 or None
    rate = rate or timescale
    stsz = _child(fh, *stbl, "stsz")
    if stsz is not None and rate:
        fh.seek(stsz[0] + 4)
        head = fh.read(8)
        if len(head) == 8:
            count = struct.unpack(">II", head)[1]
            best = max(best, count * 1024 / rate)
    return best or None


def mp4_duration(path: Path | str) -> float | None:
    """Davomiylik (soniya): `mvhd` va audio trekning o'zi - KATTASI. Topilmasa `None`."""
    size = os.path.getsize(path)
    header = _mvhd_duration(path)
    tracks: list[float] = []
    with open(path, "rb") as fh:
        moov = next(((p, e) for k, p, e in _boxes(fh, 0, size) if k == "moov"), None)
        if moov is not None:
            for kind, payload, end in list(_boxes(fh, *moov)):
                if kind == "trak":
                    seconds = _track_seconds(fh, (payload, end))
                    if seconds:
                        tracks.append(seconds)
    values = [v for v in [header, *tracks] if v]
    return round(max(values), 2) if values else None


def _mvhd_duration(path: Path | str) -> float | None:
    """`moov/mvhd` dan davomiylik (soniya). Topilmasa `None`."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        for kind, payload, end in _boxes(fh, 0, size):
            if kind != "moov":
                continue
            for sub, sub_payload, _ in _boxes(fh, payload, end):
                if sub != "mvhd":
                    continue
                fh.seek(sub_payload)
                version = fh.read(1)
                if not version:
                    return None
                fh.read(3)
                if version[0] == 1:
                    data = fh.read(28)
                    if len(data) < 28:
                        return None
                    timescale, duration = struct.unpack(">IQ", data[16:28])
                else:
                    data = fh.read(16)
                    if len(data) < 16:
                        return None
                    timescale, duration = struct.unpack(">II", data[8:16])
                if not timescale:
                    return None
                return round(duration / timescale, 2)
    return None


def measure(path: Path | str, content_type: str) -> float | None:
    """Server o'lchagan davomiylik - u ilova aytganidan USTUN."""
    if content_type == "audio/mp4":
        return mp4_duration(path)
    info = adts_info(path)
    return info.durationSec if info else None


# --- ADTS bo'lish ----------------------------------------------------------------


def split_adts(path: Path | str, max_sec: float, out_dir: Path | str | None = None) -> list[Path]:
    """ADTS ni kadr chegarasida `max_sec` dan oshmaydigan bo'laklarga bo'ladi.

    Router (ru/en) 600 s dan keyin kesadi va 25 MB dan kattasini olmaydi -
    shuning uchun uzun yozuv ketma-ket bo'laklarda yuboriladi."""
    src = Path(path)
    out = Path(out_dir) if out_dir else src.parent
    pieces: list[Path] = []
    current = None
    samples = 0
    limit = None
    with open(src, "rb") as fh:
        for frame, params in iter_frames(src):
            if limit is None:
                limit = max_sec * SAMPLE_RATES[params[1]]
            if current is None or samples + 1024 * frame.blocks > limit:
                if current is not None:
                    current.close()
                piece = out / f"{src.stem}.part{len(pieces) + 1:03d}.aac"
                fd = os.open(piece, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
                current = os.fdopen(fd, "wb")
                pieces.append(piece)
                samples = 0
            fh.seek(frame.offset)
            current.write(fh.read(frame.length))
            samples += 1024 * frame.blocks
    if current is not None:
        current.close()
    return pieces


# --- ADTS -> m4a -----------------------------------------------------------------


def _box(kind: bytes, *parts: bytes) -> bytes:
    payload = b"".join(parts)
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _full(kind: bytes, version: int, flags: int, *parts: bytes) -> bytes:
    return _box(kind, struct.pack(">I", (version << 24) | flags), *parts)


def _descriptor(tag: int, payload: bytes) -> bytes:
    """MPEG-4 deskriptori; uzunlik 4 baytli kengaytirilgan shaklda (har doim to'g'ri)."""
    n = len(payload)
    size = bytes([0x80 | ((n >> 21) & 0x7F), 0x80 | ((n >> 14) & 0x7F), 0x80 | ((n >> 7) & 0x7F), n & 0x7F])
    return bytes([tag]) + size + payload


class RemuxError(Exception):
    pass


def adts_to_m4a(src: Path | str, dst: Path | str) -> dict:
    """ADTS -> faststart m4a. `{samples, durationSec, sampleRate}` qaytaradi.

    Kadrlar sarlavhasiz (`mdat` da xom AAC), CRC (9 baytli sarlavha) ham
    tashlanadi. Bir kadrda bir nechta blok bo'lsa (MediaRecorder bunday
    yozmaydi) - `RemuxError`, chaqiruvchi asl faylni beradi."""
    sizes: list[int] = []
    spans: list[tuple[int, int]] = []
    params: tuple[int, int, int] | None = None
    for frame, p in iter_frames(src):
        if frame.blocks != 1:
            raise RemuxError("bir kadrda bir nechta blok")
        if params is None:
            params = p
        elif p[1] != params[1] or p[2] != params[2]:
            raise RemuxError("kadrlar parametri o'zgardi")
        spans.append((frame.offset + frame.header, frame.length - frame.header))
        sizes.append(frame.length - frame.header)
    if not sizes or params is None:
        raise RemuxError("ADTS kadri yo'q")
    profile, sr_index, channels = params
    rate = SAMPLE_RATES[sr_index]
    count = len(sizes)
    media_duration = count * 1024
    movie_scale = 1000
    movie_duration = int(round(media_duration * movie_scale / rate))
    data_len = sum(sizes)
    bitrate = int(data_len * 8 * rate / media_duration) if media_duration else 0

    # AudioSpecificConfig: objectType(5) srIndex(4) channels(4) + 3 nol bit.
    object_type = profile + 1
    asc = struct.pack(">H", (object_type << 11) | (sr_index << 7) | (channels << 3))
    decoder_specific = _descriptor(0x05, asc)
    decoder_config = _descriptor(0x04, bytes([0x40, 0x15]) + (0).to_bytes(3, "big")
                                 + struct.pack(">II", bitrate, bitrate) + decoder_specific)
    sl_config = _descriptor(0x06, b"\x02")
    es = _descriptor(0x03, struct.pack(">HB", 1, 0) + decoder_config + sl_config)
    esds = _full(b"esds", 0, 0, es)
    mp4a = _box(b"mp4a", b"\x00" * 6, struct.pack(">H", 1), b"\x00" * 8,
                struct.pack(">HHHH", max(1, channels), 16, 0, 0),
                struct.pack(">I", (rate if rate < 65536 else 0) << 16), esds)
    stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1), mp4a)
    stts = _full(b"stts", 0, 0, struct.pack(">III", 1, count, 1024))
    stsc = _full(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, count, 1))
    stsz = _full(b"stsz", 0, 0, struct.pack(">II", 0, count), struct.pack(f">{count}I", *sizes))

    def build(offset: int) -> tuple[bytes, bytes]:
        if offset + data_len > 0xFFFFFFFF:
            chunk = _full(b"co64", 0, 0, struct.pack(">IQ", 1, offset))
        else:
            chunk = _full(b"stco", 0, 0, struct.pack(">II", 1, offset))
        stbl = _box(b"stbl", stsd, stts, stsc, stsz, chunk)
        dinf = _box(b"dinf", _full(b"dref", 0, 0, struct.pack(">I", 1), _full(b"url ", 0, 1)))
        minf = _box(b"minf", _full(b"smhd", 0, 0, struct.pack(">HH", 0, 0)), dinf, stbl)
        hdlr = _full(b"hdlr", 0, 0, struct.pack(">I", 0), b"soun", b"\x00" * 12, b"SoundHandler\x00")
        mdhd = _full(b"mdhd", 0, 0, struct.pack(">IIII", 0, 0, rate, media_duration),
                     struct.pack(">HH", 0x55C4, 0))
        mdia = _box(b"mdia", mdhd, hdlr, minf)
        matrix = struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
        tkhd = _full(b"tkhd", 0, 0x7, struct.pack(">IIIII", 0, 0, 1, 0, movie_duration),
                     b"\x00" * 8, struct.pack(">hhhH", 0, 0, 0x0100, 0), matrix, struct.pack(">II", 0, 0))
        trak = _box(b"trak", tkhd, mdia)
        mvhd = _full(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, movie_scale, movie_duration),
                     struct.pack(">IH", 0x00010000, 0x0100), b"\x00" * 10, matrix, b"\x00" * 24,
                     struct.pack(">I", 2))
        moov = _box(b"moov", mvhd, trak)
        ftyp = _box(b"ftyp", b"M4A ", struct.pack(">I", 0), b"M4A ", b"mp42", b"isom")
        return ftyp, moov

    ftyp, moov = build(0)
    mdat_header = 8 if data_len + 8 <= 0xFFFFFFFF else 16
    ftyp, moov = build(len(ftyp) + len(moov) + mdat_header)

    dst = Path(dst)
    tmp = dst.with_name(dst.name + ".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as fh:
            out.write(ftyp)
            out.write(moov)
            if mdat_header == 8:
                out.write(struct.pack(">I4s", 8 + data_len, b"mdat"))
            else:
                out.write(struct.pack(">I4sQ", 1, b"mdat", 16 + data_len))
            for start, length in spans:
                fh.seek(start)
                out.write(fh.read(length))
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {"samples": count, "durationSec": round(media_duration / rate, 2), "sampleRate": rate}


def adts_frame(payload_len: int, *, sr_index: int = 8, channels: int = 1, profile: int = 1,
               crc: bool = False) -> bytes:
    """Sintetik ADTS kadri (testlar va jonli tekshiruv uchun): sarlavha + nol bayt."""
    header = 9 if crc else 7
    length = header + payload_len
    b0 = 0xFF
    b1 = 0xF0 | (0 if crc else 1)
    b2 = (profile << 6) | (sr_index << 2) | ((channels >> 2) & 0x01)
    b3 = ((channels & 0x03) << 6) | ((length >> 11) & 0x03)
    b4 = (length >> 3) & 0xFF
    b5 = ((length & 0x07) << 5) | 0x1F
    b6 = 0xFC
    head = bytes([b0, b1, b2, b3, b4, b5, b6]) + (b"\x00\x00" if crc else b"")
    return head + bytes(payload_len)

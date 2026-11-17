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
  * m4a -> ADTS (`mp4_to_adts`): teskari yo'l - Router (ru/en) uzun m4a ni
    olmaydi, ADTS esa kadr chegarasida bo'linadi (telefon qo'ng'irog'i yozuvlari).
  * MP3 va WAV (2026-10-22): kompyuterdagi tayyor yozuvlar. MP3 - kadr sarlavhalari
    (`mp3_info`), WAV - `fmt `/`data` (`wav_info`); Router uchun `split_plain`.
  * OGG (2026-11-04): Telegram ovozli xabari (Opus). Davomiylik - oxirgi sahifaning
    `granule_position` i (`ogg_info`), Router uchun sahifa chegarasida bo'linadi
    (`split_ogg`): har bo'lak = sarlavha sahifalari (OpusHead, OpusTags) + o'z sahifalari,
    tartib raqamlari qayta yozilib, CRC qayta hisoblanadi.
  * VIDEO (2026-11-17, ega qarori): MP4/MOV/M4V/3GP - m4a bilan bir xil konteyner (ISO BMFF),
    faqat yana video trek bor. `video_to_adts` AAC audio trekni `mp4_to_adts` bilan ajratadi (video
    trek o'qilmaydi ham), video fayl esa saqlanmaydi. Audio treki yo'q - `NoAudioTrack` ("Videoda ovoz
    yo'q"); audio AAC emas (PCM, AC-3, Opus...), fragmentlangan MP4 yoki boshqa konteyner (WebM, MKV,
    AVI) - `UnsupportedAudio` ("MP4 yuboring"): ularni ffmpeg'siz o'qib bo'lmaydi.
"""

from __future__ import annotations

import contextlib
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
    """Birinchi bo'lak e'lon qilingan formatga mosmi (`PUT /audio`, offset 0). MP3 - ID3 tegi yoki
    kadr sarlavhasi (haqiqiyligini `complete` dagi o'lchov tekshiradi), WAV - RIFF/WAVE."""
    content_type = canonical_type(content_type)
    if content_type == "audio/mpeg":
        return first[:3] == b"ID3" or mp3_header(first[:4]) is not None
    if content_type == "audio/wav":
        return len(first) >= 12 and first[:4] == b"RIFF" and first[8:12] == b"WAVE"
    if content_type == "audio/aac":
        # Sinxro 0xFFF VA qatlam bitlari 00 (`_parse_header` kabi): MP3 kadri ham 0xFFF bilan boshlanadi.
        return len(first) >= 2 and first[0] == 0xFF and (first[1] & 0xF6) == 0xF0
    if content_type == "audio/mp4":
        return len(first) >= 8 and first[4:8] == b"ftyp"
    if content_type == VIDEO_TYPE:
        return is_iso_media(first)
    if content_type == "audio/ogg":
        return first[:4] == b"OggS"
    return False


#: ISO BMFF (MP4/MOV) faylining birinchi qutisi: odatda `ftyp`; eski QuickTime MOV `ftyp` siz -
#: `moov`, `mdat`, `wide` yoki `free` bilan boshlanadi.
_ISO_FIRST_BOXES = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot")


def is_iso_media(first: bytes) -> bool:
    """Fayl boshi MP4/MOV konteyneriga o'xshaydimi (video sifatida kelgan fayl uchun)."""
    return len(first) >= 8 and first[4:8] in _ISO_FIRST_BOXES


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


#: Bitta MP4 namunasining ENG KAM davomiyligi kodek bo'yicha - `stsz` dagi namunalar soni shunga
#: ko'paytiriladi. AAC kadri doim 1024 namuna (chastotaga bo'linadi); AMR kadri 20 ms (3GPP
#: namunasida bir nechta kadr bo'lishi mumkin - shuning uchun bu PASTKI chegara).
#: NEGA kodek bo'yicha (2026-10-10, qo'ng'iroq importi): ilgari HAR trek uchun "1024 / chastota"
#: olinardi - eski Samsung `.3gp` (AMR-NB, 8 kHz) yozuvi 6.4 barobar uzun o'lchanib,
#: bekorga `too_long` yoki kvota tugashiga olib kelardi.
_FRAME_SAMPLES = {"mp4a": 1024}
_FRAME_SECONDS = {"samr": 0.02, "sawb": 0.02}


def _mdhd_timescale(fh, mdia: tuple[int, int]) -> int | None:
    """`mdhd` vaqt shkalasi. v0: yaratilgan(4) + o'zgartirilgan(4) + SHKALA(4); v1: 8 + 8 + SHKALA(4).
    NEGA alohida: ilgari v0 da `o'zgartirilgan` vaqti o'qilardi - bizning remux u yerga 0 yozgani
    uchun sezilmagan, telefon yozgan haqiqiy faylda esa `stts` yo'li noto'g'ri shkala olardi."""
    mdhd = _child(fh, *mdia, "mdhd")
    if mdhd is None:
        return None
    fh.seek(mdhd[0])
    version = fh.read(4)[:1]
    need = 20 if version == b"\x01" else 12
    data = fh.read(need)
    if len(data) < need:
        return None
    return struct.unpack(">I", data[16:20] if version == b"\x01" else data[8:12])[0] or None


def _sample_entry(fh, stbl: tuple[int, int]) -> tuple[str, int | None, int, int] | None:
    """`stsd` dagi birinchi yozuv: (kodek, chastota yoki None, yozuv boshi, yozuv oxiri).

    stsd: 4 (versiya) + 4 (soni), keyin yozuv: 8 (o'lcham+tur) + 8 (SampleEntry) + 8 (zaxira)
    + 2+2+2+2 + chastota (16.16) = 36 bayt, ichki qutilar (`esds`) shundan keyin."""
    stsd = _child(fh, *stbl, "stsd")
    if stsd is None:
        return None
    start = stsd[0] + 8
    fh.seek(start)
    head = fh.read(8)
    if len(head) < 8:
        return None
    size, kind = struct.unpack(">I4s", head)
    end = start + size
    if size < 36 or end > stsd[1]:
        return None
    fh.seek(start + 32)
    raw = fh.read(4)
    rate = (struct.unpack(">I", raw)[0] >> 16 or None) if len(raw) == 4 else None
    return kind.decode("latin-1"), rate, start, end


def _track_seconds(fh, trak: tuple[int, int]) -> float | None:
    """Audio trekning HAQIQIY davomiyligi: `stsz` namunalar soni * kodek kadri (AAC: 1024 / chastota)
    va `stts` yig'indisi / `mdhd` vaqt shkalasi - kattasi."""
    mdia = _child(fh, *trak, "mdia")
    if mdia is None:
        return None
    hdlr = _child(fh, *mdia, "hdlr")
    if hdlr is not None:
        fh.seek(hdlr[0] + 8)
        if fh.read(4) != b"soun":
            return None
    timescale = _mdhd_timescale(fh, mdia)
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
    entry = _sample_entry(fh, stbl)
    # `stsd` o'qilmasa - AAC deb (avvalgi xulq): bu yo'l kvotani aylanib o'tishga qarshi qo'riqchi.
    codec = entry[0] if entry else "mp4a"
    rate = (entry[1] if entry else None) or timescale
    per_sample = None
    if codec in _FRAME_SAMPLES and rate:
        per_sample = _FRAME_SAMPLES[codec] / rate
    elif codec in _FRAME_SECONDS:
        per_sample = _FRAME_SECONDS[codec]
    stsz = _child(fh, *stbl, "stsz")
    if stsz is not None and per_sample:
        fh.seek(stsz[0] + 4)
        head = fh.read(8)
        if len(head) == 8:
            count = struct.unpack(">II", head)[1]
            best = max(best, count * per_sample)
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
    content_type = canonical_type(content_type)
    if content_type in ("audio/mp4", VIDEO_TYPE):
        return mp4_duration(path)
    if content_type == "audio/mpeg":
        mp3 = mp3_info(path)
        return mp3.durationSec if mp3 else None
    if content_type == "audio/wav":
        wav = wav_info(path)
        return wav.durationSec if wav else None
    if content_type == "audio/ogg":
        ogg = ogg_info(path)
        return ogg.durationSec if ogg else None
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


def adts_header(payload_len: int, *, sr_index: int, channels: int, profile: int, crc: bool = False) -> bytes:
    """ADTS sarlavhasi (7 yoki CRC bilan 9 bayt); bufer to'liqligi 0x7FF - o'zgaruvchan bitreyt."""
    header = 9 if crc else 7
    length = header + payload_len
    b0 = 0xFF
    b1 = 0xF0 | (0 if crc else 1)
    b2 = (profile << 6) | (sr_index << 2) | ((channels >> 2) & 0x01)
    b3 = ((channels & 0x03) << 6) | ((length >> 11) & 0x03)
    b4 = (length >> 3) & 0xFF
    b5 = ((length & 0x07) << 5) | 0x1F
    b6 = 0xFC
    return bytes([b0, b1, b2, b3, b4, b5, b6]) + (b"\x00\x00" if crc else b"")


def adts_frame(payload_len: int, *, sr_index: int = 8, channels: int = 1, profile: int = 1,
               crc: bool = False) -> bytes:
    """Sintetik ADTS kadri (testlar va jonli tekshiruv uchun): sarlavha + nol bayt."""
    return adts_header(payload_len, sr_index=sr_index, channels=channels, profile=profile,
                       crc=crc) + bytes(payload_len)


# --- m4a -> ADTS (Router uchun) -----------------------------------------------------

#: ADTS kadri uzunligi 13 bitda (sarlavha bilan).
_ADTS_MAX_FRAME = 0x1FFF
#: Namunalar jadvali xotirada: 3 soat 48 kHz ~ 510K namuna - undan ancha ko'pi buzilgan fayl.
_MAX_SAMPLES = 5_000_000


def _descriptor_at(buf: bytes, pos: int) -> tuple[int, int, int]:
    """MPEG-4 deskriptori `pos` da: (teg, ichi boshi, oxiri). Uzunlik 1-4 bayt, har baytda 7 bit."""
    tag = buf[pos]
    pos += 1
    size = 0
    for _ in range(4):
        byte = buf[pos]
        pos += 1
        size = (size << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    if pos + size > len(buf):
        raise RemuxError("esds deskriptori kesilgan")
    return tag, pos, pos + size


def _audio_config(esds: bytes) -> tuple[int, int, int]:
    """`esds` ichidan AudioSpecificConfig -> ADTS uchun (profil, chastota indeksi, kanallar).

    HE-AAC (SBR/PS, aniq belgilangan) - ASOSIY AAC-LC qatlami va uning chastotasi olinadi:
    dekoder SBR ni ADTS da o'zi topadi. Boshqa kodek (MP3 `mp4a` ichida, ALS, ...) - `RemuxError`."""
    tag, pos, _ = _descriptor_at(esds, 4)            # 4 bayt - esds versiya/bayroqlari
    if tag != 0x03:
        raise RemuxError("ES deskriptori yo'q")
    flags = esds[pos + 2]
    pos += 3
    if flags & 0x80:                                 # streamDependenceFlag
        pos += 2
    if flags & 0x40:                                 # URL_Flag
        pos += 1 + esds[pos]
    if flags & 0x20:                                 # OCRstreamFlag
        pos += 2
    tag, pos, _ = _descriptor_at(esds, pos)
    if tag != 0x04:
        raise RemuxError("DecoderConfig yo'q")
    # 0x40 - MPEG-4 audio, 0x66-0x68 - MPEG-2 AAC; 0x69/0x6B (MP3) ADTS ga sig'maydi.
    if esds[pos] not in (0x40, 0x66, 0x67, 0x68):
        raise RemuxError(f"AAC emas (objectType 0x{esds[pos]:02x})")
    tag, pos, end = _descriptor_at(esds, pos + 13)
    if tag != 0x05 or end - pos < 2:
        raise RemuxError("AudioSpecificConfig yo'q")
    bits = int.from_bytes(esds[pos:end], "big")
    total = (end - pos) * 8
    used = 0

    def take(n: int) -> int:
        nonlocal used
        used += n
        if used > total:
            raise RemuxError("AudioSpecificConfig kesilgan")
        return (bits >> (total - used)) & ((1 << n) - 1)

    def object_type() -> int:
        value = take(5)
        return 32 + take(6) if value == 31 else value

    def rate_index() -> int:
        index = take(4)
        if index == 15:
            freq = take(24)
            if freq not in SAMPLE_RATES:
                raise RemuxError(f"ADTS da yo'q chastota: {freq}")
            index = SAMPLE_RATES.index(freq)
        return index

    aot = object_type()
    sr_index = rate_index()
    channels = take(4)
    if aot in (5, 29):
        rate_index()                                 # SBR chiqish chastotasi - ADTS ga kerak emas
        aot = object_type()
    if not 1 <= aot <= 4:
        raise RemuxError(f"ADTS ga sig'maydigan AAC turi: {aot}")
    if not 1 <= channels <= 7 or sr_index >= len(SAMPLE_RATES):
        raise RemuxError("kanallar yoki chastota noto'g'ri")
    return aot - 1, sr_index, channels


def _u32_table(fh, box: tuple[int, int], width: int, skip: int = 4) -> list[int]:
    """`stco`/`co64`/`stsz` kabi jadval: (versiya + `skip`) dan keyin soni va qiymatlar."""
    fh.seek(box[0] + skip)
    count = struct.unpack(">I", fh.read(4))[0]
    if count > _MAX_SAMPLES:
        raise RemuxError("jadval juda katta")
    raw = fh.read(width * count)
    if len(raw) < width * count:
        raise RemuxError("jadval kesilgan")
    return list(struct.unpack(f">{count}{'Q' if width == 8 else 'I'}", raw))


def _aac_track(fh, trak: tuple[int, int]) -> tuple[tuple[int, int, int], list[tuple[int, int]]] | None:
    """AAC audio trek: ((profil, chastota indeksi, kanallar), [(fayldagi joyi, uzunligi), ...]).
    Tovush yoki AAC bo'lmasa - `None` (keyingi trek tekshiriladi)."""
    mdia = _child(fh, *trak, "mdia")
    if mdia is None:
        return None
    hdlr = _child(fh, *mdia, "hdlr")
    if hdlr is not None:
        fh.seek(hdlr[0] + 8)
        if fh.read(4) != b"soun":
            return None
    minf = _child(fh, *mdia, "minf")
    stbl = _child(fh, *minf, "stbl") if minf else None
    entry = _sample_entry(fh, stbl) if stbl else None
    if stbl is None or entry is None or entry[0] != "mp4a":
        return None
    start, end = entry[2], entry[3]
    esds = None
    # ISO yozuvi - 36 bayt; QuickTime v1/v2 tovush yozuvi - yana 16/36 bayt va `esds` ba'zan `wave` ichida.
    for skip in (36, 52, 72):
        if start + skip + 8 > end:
            break
        box = _child(fh, start + skip, end, "esds")
        if box is None:
            wave = _child(fh, start + skip, end, "wave")
            box = _child(fh, *wave, "esds") if wave else None
        if box is not None:
            fh.seek(box[0])
            esds = fh.read(box[1] - box[0])
            break
    if esds is None:
        raise RemuxError("esds yo'q")
    config = _audio_config(esds)

    stsz = _child(fh, *stbl, "stsz")
    if stsz is None:
        raise RemuxError("stsz yo'q")
    fh.seek(stsz[0] + 4)
    fixed, count = struct.unpack(">II", fh.read(8))
    if fixed:
        # Hamma namuna bir xil o'lchamda - jadval yo'q (AAC da deyarli bo'lmaydi, lekin ruxsat).
        if count > _MAX_SAMPLES:
            raise RemuxError("jadval juda katta")
        sizes = [fixed] * count
    else:
        sizes = _u32_table(fh, stsz, 4, skip=8)
    stco = _child(fh, *stbl, "stco")
    co64 = None if stco else _child(fh, *stbl, "co64")
    if stco is None and co64 is None:
        raise RemuxError("stco/co64 yo'q")
    offsets = _u32_table(fh, stco, 4) if stco else _u32_table(fh, co64, 8)
    stsc = _child(fh, *stbl, "stsc")
    if stsc is None:
        raise RemuxError("stsc yo'q")
    fh.seek(stsc[0] + 4)
    runs = struct.unpack(">I", fh.read(4))[0]
    if runs > _MAX_SAMPLES:
        raise RemuxError("stsc juda katta")
    raw = fh.read(12 * runs)
    if len(raw) < 12 * runs:
        raise RemuxError("stsc kesilgan")
    table = [struct.unpack(">III", raw[i * 12:i * 12 + 12])[:2] for i in range(runs)]

    spans: list[tuple[int, int]] = []
    index = 0
    for i, (first_chunk, per_chunk) in enumerate(table):
        last_chunk = table[i + 1][0] - 1 if i + 1 < len(table) else len(offsets)
        for chunk in range(max(1, first_chunk), min(last_chunk, len(offsets)) + 1):
            pos = offsets[chunk - 1]
            for _ in range(per_chunk):
                if index >= len(sizes):
                    break
                spans.append((pos, sizes[index]))
                pos += sizes[index]
                index += 1
    if not spans:
        raise RemuxError("AAC namunalari yo'q")
    return config, spans


def mp4_to_adts(src: Path | str, dst: Path | str) -> dict:
    """m4a (AAC) -> ADTS. `{frames, durationSec, sampleRate}` qaytaradi.

    NEGA (2026-10-10, qo'ng'iroq importi): Router (ru/en) bitta so'rovda ~10 daqiqadan uzun
    m4a ni olmaydi, m4a ni esa kadr chegarasida kesib bo'lmaydi (indeks bir butun). Telefon
    qo'ng'irog'i yozuvi (Samsung `.m4a`) ko'pincha 10 daqiqadan uzun - xom AAC kadrlariga
    ADTS sarlavhasi qo'yilib, odatdagi `split_adts` bilan bo'linadi. Asl fayl o'zgarmaydi.
    Fayl kesilgan bo'lsa (oxirgi namunalar diskda yo'q) - borigacha yoziladi."""
    src, dst = Path(src), Path(dst)
    size = os.path.getsize(src)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        with open(src, "rb") as fh:
            moov = next(((p, e) for k, p, e in _boxes(fh, 0, size) if k == "moov"), None)
            if moov is None:
                raise RemuxError("moov yo'q")
            track = None
            for kind, payload, end in list(_boxes(fh, *moov)):
                if kind == "trak":
                    track = _aac_track(fh, (payload, end))
                    if track is not None:
                        break
            if track is None:
                raise RemuxError("AAC audio trek yo'q")
            (profile, sr_index, channels), spans = track
            frames = 0
            fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out:
                for pos, length in spans:
                    if length <= 0 or pos + length > size:
                        break                        # kesilgan fayl - borigacha
                    if length + 7 > _ADTS_MAX_FRAME:
                        raise RemuxError("kadr ADTS uchun juda katta")
                    fh.seek(pos)
                    out.write(adts_header(length, sr_index=sr_index, channels=channels, profile=profile))
                    out.write(fh.read(length))
                    frames += 1
        if not frames:
            raise RemuxError("yozilgan kadr yo'q")
        os.replace(tmp, dst)
    except (struct.error, IndexError, ValueError, RemuxError) as exc:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        if isinstance(exc, RemuxError):
            raise
        raise RemuxError(f"m4a o'qilmadi: {exc}") from exc
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    rate = SAMPLE_RATES[sr_index]
    return {"frames": frames, "durationSec": round(frames * 1024 / rate, 2), "sampleRate": rate}


# --- Video (2026-11-17) -----------------------------------------------------------


class NoAudioTrack(RemuxError):
    """Videoda audio trek yo'q (yoki trek bor, lekin bitta ham namunasi yo'q)."""


class UnsupportedAudio(RemuxError):
    """Videodan audioni ffmpeg'siz ajratib bo'lmaydi: AAC emas, fragmentlangan MP4, konteyner buzilgan."""


def _handler(fh, trak: tuple[int, int]) -> bytes | None:
    """Trek turi: `soun` (audio), `vide` (video), ... yoki topilmasa `None`."""
    mdia = _child(fh, *trak, "mdia")
    hdlr = _child(fh, *mdia, "hdlr") if mdia else None
    if hdlr is None:
        return None
    fh.seek(hdlr[0] + 8)
    return fh.read(4)


def _tracks(path: Path | str) -> tuple[list[tuple[bytes | None, str | None]], bool]:
    """MP4 treklari: [(tur, birinchi kodek)] va fragmentlangan-mi (`moov/mvex`). `moov` yo'q - `UnsupportedAudio`."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        moov = next(((p, e) for k, p, e in _boxes(fh, 0, size) if k == "moov"), None)
        if moov is None:
            raise UnsupportedAudio("moov yo'q")
        tracks = []
        for kind, payload, end in list(_boxes(fh, *moov)):
            if kind != "trak":
                continue
            handler = _handler(fh, (payload, end))
            mdia = _child(fh, payload, end, "mdia")
            minf = _child(fh, *mdia, "minf") if mdia else None
            stbl = _child(fh, *minf, "stbl") if minf else None
            entry = _sample_entry(fh, stbl) if stbl else None
            tracks.append((handler, entry[0] if entry else None))
        return tracks, _child(fh, *moov, "mvex") is not None


def has_video_track(path: Path | str) -> bool:
    """MP4 ichida video trek bormi (`audio/mp4` deb kelgan, aslida video fayl uchun)."""
    try:
        tracks, _ = _tracks(path)
    except (OSError, struct.error, ValueError, RemuxError):
        return False
    return any(handler == b"vide" for handler, _ in tracks)


def video_to_adts(src: Path | str, dst: Path | str) -> dict:
    """MP4/MOV videodan AAC audio -> ADTS (`dst`). `{frames, durationSec, sampleRate, codecs}` qaytaradi.

    Video trek o'qilmaydi: faqat audio namunalarining joylari (`stsz/stco/stsc`) bo'yicha baytlar
    ko'chiriladi, ya'ni 1 GB video ham bir necha soniyada, kodlashsiz. Asl fayl o'zgarmaydi -
    uni o'chirish chaqiruvchining ishi. Xato: `NoAudioTrack` yoki `UnsupportedAudio`."""
    try:
        tracks, fragmented = _tracks(src)
    except (OSError, struct.error, ValueError) as exc:
        raise UnsupportedAudio(f"video o'qilmadi: {exc}") from exc
    codecs = [codec or "?" for handler, codec in tracks if handler == b"soun"]
    if not codecs:
        raise NoAudioTrack("audio trek yo'q")
    if fragmented:
        # Namunalar `moof` larda - `moov` jadvallari bo'sh: ffmpeg'siz o'qilmaydi.
        raise UnsupportedAudio("fragmentlangan MP4")
    if "mp4a" not in codecs:
        raise UnsupportedAudio(f"audio AAC emas ({', '.join(codecs)})")
    try:
        result = mp4_to_adts(src, dst)
    except NoAudioTrack:
        raise
    except RemuxError as exc:
        if "namunalari yo'q" in str(exc) or "yozilgan kadr yo'q" in str(exc):
            raise NoAudioTrack(str(exc)) from exc
        raise UnsupportedAudio(str(exc)) from exc
    return {**result, "codecs": codecs}


# --- MP3 va WAV (2026-10-22) ------------------------------------------------------
#
# Ega so'radi: kompyuterdagi tayyor yozuvlar (diktofon, Zoom, Telegram) ko'pincha mp3 yoki
# wav. ffmpeg'siz, ADTS kabi: MP3 - har kadrning 4 baytli sarlavhasi (versiya, qatlam,
# bitreyt, chastota -> kadr uzunligi va namunalar soni); WAV - `fmt `/`data` bo'laklari.
# Kvota qoidasi o'sha: STT ga ketadigan HAMMA audio o'lchanadi (MP3 da buzilgan baytdan
# keyin keyingi haqiqiy kadr qidiriladi, xuddi dekoder kabi).

#: Kanonik kontent turlari. Brauzer, telefon va boshqa klientlar bir formatni har xil atashadi.
TYPE_ALIASES = {
    "audio/mp3": "audio/mpeg", "audio/x-mp3": "audio/mpeg", "audio/x-mpeg": "audio/mpeg",
    "audio/mpeg3": "audio/mpeg", "audio/x-mpeg-3": "audio/mpeg", "audio/mpg": "audio/mpeg",
    "audio/x-wav": "audio/wav", "audio/wave": "audio/wav", "audio/vnd.wave": "audio/wav",
    "audio/x-pn-wav": "audio/wav",
    "audio/x-m4a": "audio/mp4", "audio/m4a": "audio/mp4", "audio/x-aac": "audio/aac", "audio/aacp": "audio/aac",
    "audio/opus": "audio/ogg", "audio/oga": "audio/ogg", "audio/x-ogg": "audio/ogg", "application/ogg": "audio/ogg",
    # Video (2026-11-17): bitta konteyner (ISO BMFF) - audiosi `video_to_adts` bilan ajratiladi.
    "video/quicktime": "video/mp4", "video/x-m4v": "video/mp4", "video/3gpp": "video/mp4",
    "video/3gpp2": "video/mp4",
}
#: Videodan audio ajratiladigan yagona tur (MP4, MOV, M4V, 3GP - `TYPE_ALIASES`).
VIDEO_TYPE = "video/mp4"
#: Saqlanadigan fayl kengaytmasi (STT va pleyer formatni shundan ham taniydi). Video saqlanmaydi -
#: `.mp4` faqat yuklash davomidagi vaqtinchalik nom uchun.
EXTENSIONS = {"audio/aac": ".aac", "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/wav": ".wav",
              "audio/ogg": ".ogg", VIDEO_TYPE: ".mp4"}


def is_video_type(content_type: str | None) -> bool:
    """Klient yoki chat (Slack, Telegram) aytgan tur video-mi (`video/*`, qabul qilinmaydiganlari ham)."""
    return canonical_type(content_type).startswith("video/")


def canonical_type(content_type: str | None) -> str:
    """`Audio/MP3; charset=x` -> `audio/mpeg`. Noma'lum tur o'zgarmaydi (keyin rad etiladi)."""
    value = (content_type or "").strip().lower().split(";", 1)[0].strip()
    return TYPE_ALIASES.get(value, value)


_MP3_BITRATES = {
    (1, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (1, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (1, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
#: MPEG versiyasi (1, 2, 2.5 -> 25) -> chastotalar.
_MP3_RATES = {1: (44100, 48000, 32000), 2: (22050, 24000, 16000), 25: (11025, 12000, 8000)}


def mp3_header(b: bytes) -> tuple[int, int, int, tuple[int, int]] | None:
    """4 bayt -> (kadr uzunligi, namunalar soni, chastota, (versiya, qatlam)) yoki `None`.

    Qatlam bitlari `00` - bu MP3 emas, ADTS (AAC): ikkalasi ham 0xFFF bilan boshlanadi."""
    if len(b) < 4 or b[0] != 0xFF or (b[1] & 0xE0) != 0xE0:
        return None
    ver_bits, layer_bits = (b[1] >> 3) & 3, (b[1] >> 1) & 3
    if ver_bits == 1 or layer_bits == 0:
        return None
    version = {3: 1, 2: 2, 0: 25}[ver_bits]
    layer = 4 - layer_bits
    br_idx, sr_idx, pad = b[2] >> 4, (b[2] >> 2) & 3, (b[2] >> 1) & 1
    if br_idx in (0, 15) or sr_idx == 3:
        return None
    bitrate = _MP3_BITRATES[(1 if version == 1 else 2, layer)][br_idx] * 1000
    rate = _MP3_RATES[version][sr_idx]
    if layer == 1:
        return (12 * bitrate // rate + pad) * 4, 384, rate, (version, layer)
    if layer == 2:
        return 144 * bitrate // rate + pad, 1152, rate, (version, layer)
    coef, samples = (144, 1152) if version == 1 else (72, 576)
    return coef * bitrate // rate + pad, samples, rate, (version, layer)


def _id3_size(head: bytes) -> int:
    """Boshdagi ID3v2 tegi hajmi (sarlavha bilan) yoki 0."""
    if len(head) >= 10 and head[:3] == b"ID3" and all(x < 0x80 for x in head[6:10]):
        size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        return 10 + size + (10 if head[5] & 0x10 else 0)
    return 0


@dataclass(frozen=True)
class Mp3Frame:
    offset: int
    length: int
    samples: int


@dataclass(frozen=True)
class Mp3Info:
    durationSec: float
    frames: int
    sampleRate: int


def iter_mp3_frames(path: Path | str):
    """MP3 kadrlari (`Mp3Frame`). ID3v2 teglar o'tkazib yuboriladi; birinchi kadr KEYINGISI bilan
    tasdiqlanadi (tasodifiy 0xFF tasvir ichida ham uchraydi). O'rtadagi axlatdan keyin - qidiruv."""
    import mmap

    with open(path, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        if size < 4:
            return
        with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            pos = 0
            while pos + 10 <= size:
                tag = _id3_size(mm[pos:pos + 10])
                if not tag:
                    break
                pos += tag
            key = None
            while pos + 4 <= size:
                hdr = mp3_header(mm[pos:pos + 4])
                if hdr and pos + hdr[0] <= size and (key is None or (hdr[3], hdr[2]) == key):
                    if key is None:
                        after = pos + hdr[0]
                        nxt = mp3_header(mm[after:after + 4]) if after + 4 <= size else None
                        confirmed = (nxt is not None and (nxt[3], nxt[2]) == (hdr[3], hdr[2])) or after == size
                        if not confirmed:
                            hdr = None
                    if hdr:
                        key = (hdr[3], hdr[2])
                        yield Mp3Frame(pos, hdr[0], hdr[1])
                        pos += hdr[0]
                        continue
                found = mm.find(b"\xff", pos + 1)
                if found < 0:
                    return
                pos = found


def mp3_info(path: Path | str) -> Mp3Info | None:
    """Davomiylik HAMMA kadrdan (VBR ham). Birinchi kadr Xing/Info/VBRI bo'lsa - u ovoz emas."""
    frames = samples = rate = 0
    with open(path, "rb") as fh:
        for frame in iter_mp3_frames(path):
            if frames == 0:
                fh.seek(frame.offset)
                body = fh.read(min(frame.length, 64))
                rate = mp3_header(body[:4])[2]
                if b"Xing" in body or b"Info" in body or b"VBRI" in body:
                    frames = -1
            frames += 1
            if frames > 0:
                samples += frame.samples
    if frames < 2 or not rate:
        return None
    return Mp3Info(durationSec=round(samples / rate, 2), frames=frames, sampleRate=rate)


@dataclass(frozen=True)
class WavInfo:
    durationSec: float
    fmt: bytes
    dataStart: int
    dataBytes: int
    byteRate: int
    blockAlign: int
    sampleRate: int
    channels: int


def wav_info(path: Path | str) -> WavInfo | None:
    """RIFF/WAVE: `fmt ` va `data` bo'laklari. Davomiylik = e'lon qilingan `data` hajmi (fayldan
    oshmasa) / bayt tezligi - STT dekoderi ham aynan shu hajmni o'qiydi."""
    with open(path, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        head = fh.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return None
        pos, fmt = 12, None
        while pos + 8 <= size:
            fh.seek(pos)
            cid, csize = struct.unpack("<4sI", fh.read(8))
            if cid == b"fmt ":
                fmt = fh.read(min(csize, 256))
            elif cid == b"data":
                if fmt is None or len(fmt) < 16:
                    return None
                tag, channels, rate, byte_rate, align, bits = struct.unpack("<HHIIHH", fmt[:16])
                if not channels or not rate:
                    return None
                width = max(int(bits), 8) // 8
                byte_rate = byte_rate or rate * channels * width
                align = align or channels * width
                start = pos + 8
                remaining = size - start
                data = csize if 0 < csize < 0xFFFFFFFF else remaining
                data = min(data, remaining)
                if data <= 0 or byte_rate <= 0:
                    return None
                return WavInfo(durationSec=round(data / byte_rate, 2), fmt=bytes(fmt), dataStart=start,
                               dataBytes=data, byteRate=byte_rate, blockAlign=align, sampleRate=rate,
                               channels=channels)
            pos += 8 + csize + (csize & 1)
    return None


def _wav_header(fmt: bytes, data_len: int) -> bytes:
    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt)) + fmt + (b"\0" if len(fmt) & 1 else b"")
    return (b"RIFF" + struct.pack("<I", 4 + len(fmt_chunk) + 8 + data_len) + b"WAVE" + fmt_chunk
            + b"data" + struct.pack("<I", data_len))


def split_plain(path: Path | str, content_type: str, max_sec: float, out_dir: Path | str | None = None,
                *, max_bytes: int = 20 * 1024 * 1024) -> list[tuple[Path, float]]:
    """MP3 yoki WAV ni Router (ru/en) uchun bo'laklarga bo'ladi -> [(fayl, soniya)].

    Bo'lak `max_sec` dan ham, `max_bytes` dan ham oshmaydi: Router 25 MB dan kattasini olmaydi,
    sifatli WAV esa (44,1 kHz stereo) 540 s da ~95 MB bo'lardi. MP3 - kadr chegarasida (ID3 tegsiz),
    WAV - blok chegarasida, har bo'lakka o'z sarlavhasi bilan."""
    src = Path(path)
    out = Path(out_dir) if out_dir else src.parent
    kind = canonical_type(content_type)
    pieces: list[tuple[Path, float]] = []

    def open_piece(ext: str):
        piece = out / f"{src.stem}.part{len(pieces) + 1:03d}{ext}"
        fd = os.open(piece, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        return piece, os.fdopen(fd, "wb")

    if kind == "audio/wav":
        info = wav_info(src)
        if info is None:
            return []
        step = int(min(max_sec * info.byteRate, max_bytes - 1024) // info.blockAlign) * info.blockAlign
        if step <= 0:
            return []
        with open(src, "rb") as fh:
            done = 0
            while done < info.dataBytes:
                take = min(step, info.dataBytes - done)
                fh.seek(info.dataStart + done)
                piece, handle = open_piece(".wav")
                with handle:
                    handle.write(_wav_header(info.fmt, take))
                    handle.write(fh.read(take))
                pieces.append((piece, round(take / info.byteRate, 3)))
                done += take
        return pieces
    if kind == "audio/mpeg":
        current = None
        samples = written = 0
        rate = 0
        with open(src, "rb") as fh:
            for frame in iter_mp3_frames(src):
                if not rate:
                    fh.seek(frame.offset)
                    rate = mp3_header(fh.read(4))[2]
                if current is None or samples + frame.samples > max_sec * rate or written + frame.length > max_bytes:
                    if current is not None:
                        current[1].close()
                        pieces.append((current[0], round(samples / rate, 3)))
                    current = open_piece(".mp3")
                    samples = written = 0
                fh.seek(frame.offset)
                current[1].write(fh.read(frame.length))
                samples += frame.samples
                written += frame.length
        if current is not None:
            current[1].close()
            pieces.append((current[0], round(samples / rate, 3)))
        return pieces
    raise ValueError(f"split_plain: {content_type}")


# --- OGG (Opus) -----------------------------------------------------------------
#
# Telegram ovozli xabari - Ogg konteynerida Opus. Sahifa: `OggS` + 27 baytli sarlavha
# (`granule_position` - shu sahifagacha dekodlangan namunalar, Opus uchun HAR DOIM 48 kHz
# da) + segmentlar jadvali + paketlar. Birinchi paket `OpusHead` (`pre_skip` - boshidagi
# tashlab yuboriladigan namunalar), ikkinchisi `OpusTags`; audio shundan keyin.

#: Opus granule'lari 48 kHz da (RFC 7845), konteyner chastotasidan qat'i nazar.
_OPUS_RATE = 48000
_OGG_HEADER = 27


@dataclass(frozen=True)
class OggPage:
    offset: int          # fayldagi boshlanishi
    length: int          # sarlavha + segmentlar jadvali + paketlar
    granule: int         # -1 - shu sahifada birorta paket tugamaydi
    flags: int           # 0x01 davom, 0x02 BOS, 0x04 EOS
    packets_end: int     # shu sahifada TUGAGAN paketlar soni


@dataclass(frozen=True)
class OggInfo:
    durationSec: float
    preSkip: int
    rate: int            # granule chastotasi
    headerPages: int     # sarlavha paketlari (OpusHead, OpusTags) joylashgan sahifalar
    pages: int


def iter_ogg_pages(path: Path | str):
    """Fayldagi sahifalar tartib bilan. Buzilgan joyda to'xtaydi (oxiri yarim sahifa)."""
    with open(path, "rb") as fh:
        offset = 0
        while True:
            fh.seek(offset)
            head = fh.read(_OGG_HEADER)
            if len(head) < _OGG_HEADER or head[:4] != b"OggS":
                return
            flags = head[5]
            granule = struct.unpack("<q", head[6:14])[0]
            count = head[26]
            table = fh.read(count)
            if len(table) < count:
                return
            body = sum(table)
            length = _OGG_HEADER + count + body
            fh.seek(offset + length - 1)
            if length > 0 and not fh.read(1):
                return                                   # yarim sahifa
            yield OggPage(offset=offset, length=length, granule=granule, flags=flags,
                          packets_end=sum(1 for lace in table if lace < 255))
            offset += length


def _ogg_first_packet(path: Path | str) -> bytes:
    with open(path, "rb") as fh:
        head = fh.read(_OGG_HEADER)
        if len(head) < _OGG_HEADER or head[:4] != b"OggS":
            return b""
        table = fh.read(head[26])
        size = 0
        for lace in table:
            size += lace
            if lace < 255:
                break
        return fh.read(size)


def ogg_info(path: Path | str) -> OggInfo | None:
    """Davomiylik = (oxirgi granule - pre_skip) / chastota. Opus bo'lmasa (Vorbis) - sarlavhadagi
    chastota, pre_skip 0. Sahifasiz yoki audio sahifasiz fayl - `None`."""
    first = _ogg_first_packet(path)
    if first.startswith(b"OpusHead") and len(first) >= 12:
        rate, pre_skip, headers = _OPUS_RATE, struct.unpack("<H", first[10:12])[0], 2
    elif first.startswith(b"\x01vorbis") and len(first) >= 16:
        rate, pre_skip, headers = struct.unpack("<I", first[12:16])[0] or _OPUS_RATE, 0, 3
    else:
        return None
    pages = header_pages = 0
    done = 0
    last = -1
    for page in iter_ogg_pages(path):
        pages += 1
        if done < headers:
            header_pages += 1
            done += page.packets_end
            continue
        if page.granule >= 0:
            last = page.granule
    if pages <= header_pages or last < 0:
        return None
    return OggInfo(durationSec=round(max(0, last - pre_skip) / rate, 2), preSkip=pre_skip, rate=rate,
                   headerPages=header_pages, pages=pages)


def _ogg_crc_table() -> list[int]:
    table = []
    for n in range(256):
        value = n << 24
        for _ in range(8):
            value = ((value << 1) ^ 0x04C11DB7) if value & 0x80000000 else (value << 1)
        table.append(value & 0xFFFFFFFF)
    return table


_OGG_CRC = _ogg_crc_table()


def ogg_crc(data: bytes) -> int:
    """Ogg CRC32: polinom 0x04c11db7, boshlang'ich 0, aks ettirishsiz, yakuniy XOR siz."""
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _OGG_CRC[((crc >> 24) ^ byte) & 0xFF]
    return crc


def _ogg_rewrite(raw: bytes, *, sequence: int, flags: int) -> bytes:
    """Sahifa nusxasi: yangi tartib raqami va bayroqlar bilan, CRC qayta hisoblangan."""
    page = bytearray(raw)
    page[5] = flags
    page[18:22] = struct.pack("<I", sequence)
    page[22:26] = b"\0\0\0\0"
    page[22:26] = struct.pack("<I", ogg_crc(bytes(page)))
    return bytes(page)


def split_ogg(path: Path | str, max_sec: float, out_dir: Path | str | None = None,
              *, max_bytes: int = 20 * 1024 * 1024) -> list[tuple[Path, float]]:
    """OGG ni Router (ru/en) uchun bo'laklarga bo'ladi -> [(fayl, soniya)].

    Bo'lak = sarlavha sahifalari + ketma-ket audio sahifalar; tartib raqamlari 0 dan
    qayta yoziladi (dekoder "sahifa yo'qolgan" demasin), oxirgisiga EOS. Granule'lar
    ASL holida qoladi - dekoder uchun bu shunchaki boshlang'ich vaqt. Bo'lak `max_sec`
    dan ham, `max_bytes` dan ham oshmaydi (sahifa ~5 s, ya'ni chegara sahifa aniqligida)."""
    src = Path(path)
    out = Path(out_dir) if out_dir else src.parent
    info = ogg_info(src)
    if info is None:
        return []
    pages = list(iter_ogg_pages(src))
    with open(src, "rb") as fh:
        def raw(page: OggPage) -> bytes:
            fh.seek(page.offset)
            return fh.read(page.length)

        headers = [_ogg_rewrite(raw(p), sequence=i, flags=p.flags & ~0x04)
                   for i, p in enumerate(pages[:info.headerPages])]
        head_bytes = sum(len(h) for h in headers)
        pieces: list[tuple[Path, float]] = []
        group: list[OggPage] = []
        group_bytes = 0
        start = info.preSkip                     # bo'lak boshidagi granule
        last = start

        def flush(final: OggPage) -> None:
            nonlocal group, group_bytes, start, last
            piece = out / f"{src.stem}.part{len(pieces) + 1:03d}.ogg"
            fd = os.open(piece, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as handle:
                for header in headers:
                    handle.write(header)
                for n, page in enumerate(group):
                    flags = (page.flags & ~0x06) | (0x04 if page is final else 0)
                    handle.write(_ogg_rewrite(raw(page), sequence=len(headers) + n, flags=flags))
            end = last if last > start else start
            pieces.append((piece, round(max(0, end - start) / info.rate, 3)))
            start = end
            group, group_bytes = [], 0

        for page in pages[info.headerPages:]:
            if group and page.granule >= 0 and (
                    (page.granule - start) / info.rate > max_sec
                    or head_bytes + group_bytes + page.length > max_bytes):
                flush(group[-1])
            group.append(page)
            group_bytes += page.length
            if page.granule >= 0:
                last = page.granule
        if group:
            flush(group[-1])
    return pieces

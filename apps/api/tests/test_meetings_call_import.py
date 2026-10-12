"""Telefon qo'ng'irog'i yozuvlari va "Ulashish -> Barno AI" importi (2026-10-10).

Telefon (Samsung "Qo'ng'iroqlarni yozish") tayyor `.m4a` yozadi - bizning ilova yozgan
ADTS emas. Shuning uchun bu yerda HAQIQIY telefon fayliga o'xshash m4a yasaladi:
`moov` OXIRIDA (MediaMuxer faststart qilmaydi), `ftyp` - `mp42`, `mvhd`/`mdhd` da noldan farqli
yaratilgan/o'zgartirilgan vaqtlar, namunalar bir necha bo'lakda (`stsc` ikki yozuvli),
8-48 kHz, mono/stereo. Kodlangan ovoz emas (bu yerda AAC kodlovchi yo'q) - lekin konteyner
tuzilishi telefonnikidek, GAPI esa soxta (`meetings_fakes`).
"""

from __future__ import annotations

import json
import struct

from dataclasses import replace

import pytest

from app.services.meetings import audio, prompts, transcribe
from app.services.meetings.summarize import CALL_LONG_SEC, Pipeline, SummaryInput
from meetings_fakes import FakeLLM, complete, create_meeting, enable, run_all, upload_all

#: 2026-10-08 09:30 UTC, 1904-yildan beri soniyalar (MP4 vaqti) - telefon shunday yozadi.
MP4_TIME = 2082844800 + 1791451800


def _box(kind: bytes, *parts: bytes) -> bytes:
    payload = b"".join(parts)
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _full(kind: bytes, version: int, flags: int, *parts: bytes) -> bytes:
    return _box(kind, struct.pack(">I", (version << 24) | flags), *parts)


def _desc(tag: int, payload: bytes) -> bytes:
    # Android MediaMuxer uzunlikni 1 baytda yozadi (127 dan kichik bo'lsa).
    assert len(payload) < 128
    return bytes([tag, len(payload)]) + payload


def asc(aot: int = 2, sr_index: int = 11, channels: int = 1) -> bytes:
    """AAC-LC AudioSpecificConfig (2 bayt)."""
    return struct.pack(">H", (aot << 11) | (sr_index << 7) | (channels << 3))


def esds(config: bytes, oti: int = 0x40) -> bytes:
    dsi = _desc(0x05, config)
    dcd = _desc(0x04, bytes([oti, 0x15]) + b"\0\0\0" + struct.pack(">II", 32000, 32000) + dsi)
    es = _desc(0x03, struct.pack(">HB", 0, 0) + dcd + _desc(0x06, b"\x02"))
    return _full(b"esds", 0, 0, es)


def phone_m4a(seconds: float, *, rate: int = 8000, channels: int = 1, codec: bytes = b"mp4a",
              config: bytes | None = None, oti: int = 0x40, per_chunk: int = 22, co64: bool = False,
              forged_header: bool = False, mvhd_ms: int | None = None) -> tuple[bytes, list[bytes]]:
    """Telefon yozgan m4a ga o'xshash fayl -> (baytlar, namunalar).

    `forged_header` - `mvhd` va `stts` ataylab kichik (kvotani aylanib o'tish urinishi);
    `mvhd_ms` - `mvhd` davomiyligini almashtirish (0 - ba'zi yozuvchilar uni to'ldirmaydi)."""
    spf = {b"mp4a": 1024, b"samr": 160}.get(codec, 960)
    count = max(1, int(round(seconds * rate / spf)))
    samples = [bytes([(i * 7 + k) & 0xFF for k in range(40 + i % 13)]) for i in range(count)]
    ftyp = _box(b"ftyp", b"mp42", struct.pack(">I", 0), b"isom", b"mp42")
    mdat = _box(b"mdat", *samples)
    data_start = len(ftyp) + 8
    offsets, pos = [], data_start
    chunks = [samples[i:i + per_chunk] for i in range(0, count, per_chunk)]
    for chunk in chunks:
        offsets.append(pos)
        pos += sum(len(s) for s in chunk)
    runs = [(1, per_chunk)]
    if count % per_chunk:
        runs = ([(1, per_chunk)] if len(chunks) > 1 else []) + [(len(chunks), count % per_chunk)]
    stsc = _full(b"stsc", 0, 0, struct.pack(">I", len(runs)), *(struct.pack(">III", a, b, 1) for a, b in runs))
    stsz = _full(b"stsz", 0, 0, struct.pack(">II", 0, count), *(struct.pack(">I", len(s)) for s in samples))
    if co64:
        chunk_box = _full(b"co64", 0, 0, struct.pack(">I", len(offsets)), *(struct.pack(">Q", o) for o in offsets))
    else:
        chunk_box = _full(b"stco", 0, 0, struct.pack(">I", len(offsets)), *(struct.pack(">I", o) for o in offsets))
    delta = 1 if forged_header else spf
    stts = _full(b"stts", 0, 0, struct.pack(">III", 1, count, delta))
    if codec == b"mp4a":
        child = esds(config if config is not None else asc(2, audio.SAMPLE_RATES.index(rate), channels), oti)
    elif codec == b"samr":
        child = _box(b"damr", b"SMSG", b"\0", struct.pack(">HB", 0x81FF, 1))
    else:
        child = _box(b"dOps", b"\0" * 11)
    entry = _box(codec, b"\0" * 6, struct.pack(">H", 1), b"\0" * 8,
                 struct.pack(">HHHH", channels, 16, 0, 0), struct.pack(">I", rate << 16), child)
    stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1), entry)
    stbl = _box(b"stbl", stsd, stts, stsc, stsz, chunk_box)
    dinf = _box(b"dinf", _full(b"dref", 0, 0, struct.pack(">I", 1), _full(b"url ", 0, 1)))
    minf = _box(b"minf", _full(b"smhd", 0, 0, b"\0" * 4), dinf, stbl)
    media_duration = count * delta
    mdhd = _full(b"mdhd", 0, 0, struct.pack(">IIII", MP4_TIME, MP4_TIME + 5, rate, media_duration),
                 struct.pack(">HH", 0x55C4, 0))
    hdlr = _full(b"hdlr", 0, 0, b"\0" * 4, b"soun", b"\0" * 12, b"SoundHandle\0")
    ms = 1 if forged_header else int(count * spf * 1000 / rate)
    matrix = struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
    tkhd = _full(b"tkhd", 0, 7, struct.pack(">IIIII", MP4_TIME, MP4_TIME + 5, 1, 0, ms), b"\0" * 8,
                 struct.pack(">hhhH", 0, 0, 0x0100, 0), matrix, struct.pack(">II", 0, 0))
    trak = _box(b"trak", tkhd, _box(b"mdia", mdhd, hdlr, minf))
    mvhd = _full(b"mvhd", 0, 0, struct.pack(">IIII", MP4_TIME, MP4_TIME + 5, 1000, ms if mvhd_ms is None else mvhd_ms),
                 struct.pack(">IH", 0x00010000, 0x0100), b"\0" * 10, matrix, b"\0" * 24, struct.pack(">I", 2))
    udta = _box(b"udta", _box(b"smta", b"\0" * 8))
    return ftyp + mdat + _box(b"moov", mvhd, trak, udta), samples


# --- o'lchash -------------------------------------------------------------------------


@pytest.mark.parametrize("rate,channels", [(8000, 1), (16000, 1), (44100, 2), (48000, 2)])
def test_telefon_m4a_olchanadi(tmp_path, rate, channels):
    data, samples = phone_m4a(64.0, rate=rate, channels=channels)
    path = tmp_path / "Aziz aka_241008_093000.m4a"
    path.write_bytes(data)
    assert audio.sniff(data[:4096], "audio/mp4")
    expected = len(samples) * 1024 / rate
    assert abs(audio.measure(path, "audio/mp4") - expected) < 0.02


def test_soxta_sarlavha_kvotani_aylanib_otmaydi(tmp_path):
    """`mvhd` 1 ms va `stts` kichik - baribir AAC kadrlari soni bo'yicha o'lchanadi."""
    data, samples = phone_m4a(120.0, rate=16000, forged_header=True)
    path = tmp_path / "a.m4a"
    path.write_bytes(data)
    assert abs(audio.measure(path, "audio/mp4") - len(samples) * 1024 / 16000) < 0.02


def test_amr_3gp_olti_barobar_uzun_olchanmaydi(tmp_path):
    """Eski Samsung `.3gp` (AMR-NB, 8 kHz, 20 ms kadr): ilgari "1024 / chastota" 6.4x uzun berardi."""
    data, _ = phone_m4a(30.0, rate=8000, codec=b"samr")
    path = tmp_path / "a.3gp"
    path.write_bytes(data)
    assert abs(audio.measure(path, "audio/mp4") - 30.0) < 0.05


def test_mdhd_v0_vaqt_shkalasi(tmp_path):
    """Noma'lum kodek - faqat `stts` / `mdhd` yo'li. `mdhd` v0 da yaratilgan/o'zgartirilgan vaqtlar
    noldan farqli (telefon fayli): shkala to'g'ri joydan o'qilishi kerak."""
    data, _ = phone_m4a(30.0, rate=48000, codec=b"Opus", mvhd_ms=0)
    path = tmp_path / "a.m4a"
    path.write_bytes(data)
    assert abs(audio.measure(path, "audio/mp4") - 30.0) < 0.05


# --- m4a -> ADTS (Router) ----------------------------------------------------------------


def test_adts_m4a_adts_aynan_qaytadi(tmp_path):
    src = tmp_path / "a.aac"
    original = b"".join(audio.adts_frame(60 + i % 9) for i in range(200))
    src.write_bytes(original)
    audio.adts_to_m4a(src, tmp_path / "a.m4a")
    result = audio.mp4_to_adts(tmp_path / "a.m4a", tmp_path / "b.aac")
    assert (tmp_path / "b.aac").read_bytes() == original
    assert result == {"frames": 200, "durationSec": 12.8, "sampleRate": 16000}


@pytest.mark.parametrize("rate,channels,co64", [(8000, 1, False), (48000, 2, True)])
def test_telefon_m4a_adts_ga(tmp_path, rate, channels, co64):
    data, samples = phone_m4a(50.0, rate=rate, channels=channels, co64=co64)
    (tmp_path / "a.m4a").write_bytes(data)
    out = tmp_path / "a.aac"
    result = audio.mp4_to_adts(tmp_path / "a.m4a", out)
    info = audio.adts_info(out)
    assert info.frames == len(samples) == result["frames"]
    assert info.sampleRate == rate and info.channels == channels and info.profile == 1
    payloads = []
    with open(out, "rb") as fh:
        for frame, _ in audio.iter_frames(out):
            fh.seek(frame.offset + frame.header)
            payloads.append(fh.read(frame.length - frame.header))
    assert payloads == samples
    pieces = audio.split_adts(out, 20, tmp_path)
    assert len(pieces) == 3


def test_he_aac_asosiy_qatlam_va_mp3_rad(tmp_path):
    # HE-AAC (aniq SBR): aot 5, asosiy 24 kHz, stereo, chiqish 48 kHz, ichida AAC-LC.
    he = struct.pack(">I", (5 << 27) | (6 << 23) | (2 << 19) | (3 << 15) | (2 << 10))
    data, samples = phone_m4a(10.0, rate=24000, channels=2, config=he)
    (tmp_path / "he.m4a").write_bytes(data)
    audio.mp4_to_adts(tmp_path / "he.m4a", tmp_path / "he.aac")
    info = audio.adts_info(tmp_path / "he.aac")
    assert (info.profile, info.sampleRate, info.channels, info.frames) == (1, 24000, 2, len(samples))
    mp3, _ = phone_m4a(10.0, rate=44100, oti=0x6B)
    (tmp_path / "mp3.m4a").write_bytes(mp3)
    with pytest.raises(audio.RemuxError):
        audio.mp4_to_adts(tmp_path / "mp3.m4a", tmp_path / "mp3.aac")
    assert not (tmp_path / "mp3.aac").exists() and not (tmp_path / "mp3.aac.tmp").exists()
    whole, _ = phone_m4a(10.0)
    (tmp_path / "cut.m4a").write_bytes(whole[:len(whole) // 2])           # moov yo'q (yarim nusxa)
    with pytest.raises(audio.RemuxError):
        audio.mp4_to_adts(tmp_path / "cut.m4a", tmp_path / "cut.aac")
    amr, _ = phone_m4a(10.0, codec=b"samr")
    (tmp_path / "amr.3gp").write_bytes(amr)
    with pytest.raises(audio.RemuxError):
        audio.mp4_to_adts(tmp_path / "amr.3gp", tmp_path / "amr.aac")


# --- API: yuklash, GAPI, xulosa ---------------------------------------------------------------


def test_qongiroq_yozuvi_yuklanadi_va_xulosa(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    data, samples = phone_m4a(64.0, rate=8000)
    meeting = create_meeting(client, auth, contentType="audio/mp4", source="call",
                             title="Qo'ng'iroq: Aziz aka", recordedAt="2026-10-08T09:30:00Z")
    assert meeting["source"] == "call" and meeting["title"] == "Qo'ng'iroq: Aziz aka"
    assert meeting["titleSource"] == "user"
    upload_all(client, auth, meeting["id"], data)
    done = complete(client, auth, meeting["id"], data, durationSec=None, endedAt=None)
    assert done.status_code == 202, done.text
    assert done.json()["status"] == "uploaded" and done.json()["durationSec"] == 64.0
    assert rt.store.meeting_any(meeting["id"])["audio_path"].endswith(f"{meeting['id']}.m4a")
    run_all(rt)
    assert rt.gapi.submits[0]["contentType"] == "audio/mp4" and rt.gapi.submits[0]["size"] == len(data)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "ready" and detail["summaryStatus"] == "ready"
    # Sarlavha ilova yuborgandek qoladi (AI sarlavhasi uni almashtirmaydi).
    assert detail["title"] == "Qo'ng'iroq: Aziz aka" and detail["source"] == "call"
    assert detail["recordedAt"].startswith("2026-10-08T09:30:00")
    listing = client.get("/api/v1/meetings", headers=auth).json()["items"]
    assert [c["source"] for c in listing if c["id"] == meeting["id"]] == ["call"]
    cards = client.get(f"/api/v1/meetings/{meeting['id']}/summaries", headers=auth).json()["items"]
    assert cards[0]["template"] == "short_call"
    # 64 s qo'ng'iroq - tasniflovchisiz; model qo'ng'iroq ekanini biladi.
    assert "meeting_classify" not in rt.llm.ops()
    extract = next(c for c in rt.llm.calls if c["op"] == "meeting_extract")
    assert prompts.CALL_NOTE.strip() in extract["user"]
    # Yozuvni tinglash: m4a o'zi (remuxsiz) beriladi.
    played = client.get(f"/api/v1/meetings/{meeting['id']}/audio", headers=auth)
    assert played.status_code == 200 and played.headers["content-type"] == "audio/mp4"
    assert played.content == data


def test_ulashish_manbai_va_notogri_manba(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    shared = create_meeting(client, auth, contentType="audio/mp4", source="share", title="Ovozli xabar")
    assert shared["source"] == "share"
    bad = client.post("/api/v1/meetings", headers=auth, json={
        "clientId": "6f1c1d2e-1111-4a4a-8b8b-123456789abc", "recordedAt": "2026-10-09T06:00:00Z",
        "contentType": "audio/mp4", "source": "whatsapp"})
    assert bad.status_code == 422


def test_router_uzun_qongiroq_boleklanadi(client, auth, monkeypatch, _isolated_meetings):
    """Rus tilidagi uzun qo'ng'iroq: m4a -> ADTS -> 3 bo'lak (ilgari `router_too_long`)."""
    rt = _isolated_meetings
    enable(monkeypatch)
    monkeypatch.setattr(transcribe, "ROUTER_M4A_MAX_SEC", 30)
    monkeypatch.setattr(transcribe, "ROUTER_PIECE_SEC", 20)
    data, _ = phone_m4a(50.0, rate=16000, channels=2)
    meeting = create_meeting(client, auth, contentType="audio/mp4", source="call", language="ru",
                             title="Звонок: +998901234567")
    upload_all(client, auth, meeting["id"], data)
    assert complete(client, auth, meeting["id"], data).status_code == 202
    run_all(rt)
    assert len(rt.router.calls) == 3
    assert all(c["contentType"] == "audio/aac" and c["language"] == "ru" for c in rt.router.calls)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth).json()
    assert detail["status"] == "ready" and detail["transcript"]["engine"] == "router"
    segments = client.get(f"/api/v1/meetings/{meeting['id']}/transcript", headers=auth).json()["segments"]
    assert segments and segments[-1]["end"] <= 51.0
    # Vaqtinchalik ADTS va bo'laklar qolmaydi.
    audio_dir = rt.store.audio_dir(1)
    assert sorted(p.name for p in audio_dir.iterdir()) == [f"{meeting['id']}.m4a"]


def test_router_uzun_amr_avvalgidek_xato(client, auth, monkeypatch, _isolated_meetings):
    rt = _isolated_meetings
    enable(monkeypatch)
    monkeypatch.setattr(transcribe, "ROUTER_M4A_MAX_SEC", 20)
    data, _ = phone_m4a(30.0, codec=b"samr")
    meeting = create_meeting(client, auth, contentType="audio/mp4", source="share", language="en")
    upload_all(client, auth, meeting["id"], data)
    assert complete(client, auth, meeting["id"], data).status_code == 202
    run_all(rt)
    assert rt.store.meeting_any(meeting["id"])["error_code"] == "router_too_long"
    assert rt.router.calls == []


# --- shablon: qo'ng'iroq moyilligi ------------------------------------------------------------

LINES = [
    ("S1", "Assalomu alaykum, Aziz aka, kecha yuborgan taklifimiz bo'yicha qo'ng'iroq qilyapman."),
    ("S2", "Ha, ko'rdim, narxi biroz qimmat tuyuldi, chegirma bo'ladimi?"),
    ("S1", "Agar yuzta litsenziya olsangiz, o'n foiz chegirma qilib bera olamiz."),
    ("S2", "Yaxshi, men direktor bilan gaplashib, juma kuni javob beraman."),
    ("S1", "Unda shartnoma loyihasini bugun kechgacha elektron pochtangizga yuboraman."),
]


def call_input(*, repeat: int = 1, template: str = "auto", source: str = "call") -> SummaryInput:
    segments, t = [], 0.0
    for r in range(repeat):
        for speaker, text in LINES:
            segments.append({"id": len(segments) + 1, "start": t, "end": t + 8.0, "speaker": speaker,
                             "text": text if repeat == 1 else f"{text} ({r})"})
            t += 9.0
    return SummaryInput(meeting_id="c1", rev=1, recorded_at=1791451800.0, duration_sec=t, language="uz",
                        template=template, segments=segments,
                        speakers=[{"id": "S1", "name": None, "talk_sec": t / 2},
                                  {"id": "S2", "name": None, "talk_sec": t / 2}],
                        marks=[], speakers_available=True, source=source)


def _classified(reply: dict | None, inp: SummaryInput) -> tuple[str, FakeLLM]:
    llm = FakeLLM()
    if reply is not None:
        llm.script["meeting_classify"] = [json.dumps(reply)]
    return Pipeline(llm, verify=False).run(inp).template, llm


def test_qongiroq_qisqa_bolsa_tasniflovchisiz():
    template, llm = _classified(None, call_input())                 # 45 s
    assert template == "short_call" and "meeting_classify" not in llm.ops()


def test_qongiroq_savdo_shabloniga_moyil():
    # 4 daqiqalik qo'ng'iroq: oddiy yozuvda "5 daqiqadan qisqa -> short_call" bo'lardi, qo'ng'iroqda
    # tasniflovchi so'raladi va savdo qo'ng'irog'i tanlanadi.
    inp = call_input(repeat=6)
    assert 120 < inp.duration_sec < 300
    template, llm = _classified({"template": "sales_call", "confidence": 0.8}, inp)
    assert template == "sales_call"
    classify = next(c for c in llm.calls if c["op"] == "meeting_classify")
    assert classify["system"] == prompts.CALL_CLASSIFY_SYSTEM and prompts.CALL_NOTE.strip() in classify["user"]
    # Xuddi shu yozuv ilovadan (`app`) - avvalgi qoida: short_call, tasniflovchisiz.
    template, llm = _classified(None, replace(inp, source="app"))
    assert template == "short_call" and "meeting_classify" not in llm.ops()
    assert all(prompts.CALL_NOTE.strip() not in c["user"] for c in llm.calls)


@pytest.mark.parametrize("reply,expected", [
    ({"template": "minutes", "confidence": 0.95}, "short_call"),     # yig'ilish shabloni - qo'ng'iroqqa emas
    ({"template": "sales_call", "confidence": 0.3}, "short_call"),   # ishonchsiz
    ({"template": "project_review", "confidence": 0.9}, "project_review"),
])
def test_qongiroq_tanlovi_cheklangan(reply, expected):
    template, _ = _classified(reply, call_input(repeat=6))
    assert template == expected


def test_uzun_qongiroq_general_ga_qaytadi():
    inp = call_input(repeat=30)
    assert inp.duration_sec >= CALL_LONG_SEC
    assert _classified({"template": "short_call", "confidence": 0.9}, inp)[0] == "general"
    assert _classified({"template": "sales_call", "confidence": 0.2}, inp)[0] == "general"
    assert _classified({"template": "sales_call", "confidence": 0.9}, inp)[0] == "sales_call"


def test_qongiroqda_tanlangan_shablon_ozgarmaydi():
    template, llm = _classified(None, call_input(repeat=6, template="general"))
    assert template == "general" and "meeting_classify" not in llm.ops()


# --- qo'ng'iroq roziligi serverda (2026-10-11) -------------------------------------------------


def test_qongiroq_roziligi_serverda_saqlanadi(client, auth, monkeypatch, _isolated_meetings):
    from app.services.meetings import service as meetings_service

    rt = _isolated_meetings
    enable(monkeypatch)
    meeting = create_meeting(client, auth, contentType="audio/mp4", source="call",
                             consentAt="2026-10-08T09:00:00Z", consentVersion="calls-consent-1")
    row = rt.store.rows("SELECT consent_at, consent_version, source FROM meetings WHERE id = ?", (meeting["id"],))[0]
    assert row["consent_version"] == "calls-consent-1" and row["consent_at"] == 1791450000
    assert meetings_service.call_consent(row) == {"at": 1791450000, "version": "calls-consent-1"}
    # Kelajakdagi vaqt (telefon soati) - hozirgiga tushiriladi.
    future = create_meeting(client, auth, contentType="audio/mp4", source="call", consentAt="2099-01-01T00:00:00Z")
    stored = rt.store.rows("SELECT consent_at FROM meetings WHERE id = ?", (future["id"],))[0]["consent_at"]
    assert stored <= int(__import__("time").time())


def test_rozilik_faqat_qongiroqqa(client, auth, monkeypatch, _isolated_meetings):
    from app.services.meetings import service as meetings_service

    rt = _isolated_meetings
    enable(monkeypatch)
    meeting = create_meeting(client, auth, contentType="audio/mp4", source="app", consentAt="2026-10-08T09:00:00Z")
    row = rt.store.rows("SELECT consent_at, consent_version, source FROM meetings WHERE id = ?", (meeting["id"],))[0]
    assert row["consent_at"] is None and meetings_service.call_consent(row) is None
    without = create_meeting(client, auth, contentType="audio/mp4", source="call")
    row = rt.store.rows("SELECT consent_at, source FROM meetings WHERE id = ?", (without["id"],))[0]
    assert meetings_service.call_consent(row) is None

"""Plaud: video -> faqat audio (2026-11-17, ega qarori).

Video (MP4/MOV) yuklansa server AAC audio trekni ajratib oladi (`audio.video_to_adts`), video faylni
o'chiradi va yig'ilish oddiy AAC yozuv bo'lib davom etadi. Audio treki yo'q - "Videoda ovoz yo'q";
audio AAC emas, fragmentlangan MP4 yoki boshqa konteyner (WebM, MKV) - "MP4 yuboring".

Bu yerdagi video - telefon m4a si (`phone_m4a`, `moov` oxirida) + `moov` ga qo'shilgan video trek:
namunalar `mdat` da, `moov` dan OLDIN, ya'ni trek qo'shilsa ham ularning joyi o'zgarmaydi.
"""

from __future__ import annotations

import hashlib
import struct

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.meetings import audio, service
from app.slack import meeting as slack_meeting
from app.slack import transcribe as slack_transcribe
from meetings_fakes import complete, create_meeting, enable, put_chunk, upload_all
from test_meetings_call_import import _box, _full, phone_m4a

VIDEO_TRAK = _box(b"trak", _box(b"mdia", _full(b"hdlr", 0, 0, b"\0" * 4, b"vide", b"\0" * 12, b"VideoHandle\0")))
WEBM = b"\x1aE\xdf\xa3" + b"\0" * 60


def video_mp4(seconds: float = 30.0, *, sound: bool = True, fragmented: bool = False, **m4a) -> bytes:
    """Video + (ixtiyoriy) audio trekli MP4. `sound=False` - faqat video trek."""
    data, _ = phone_m4a(seconds, rate=16000, **m4a)
    moov_at = data.rfind(b"moov") - 4
    moov = data[moov_at:]
    children = moov[8:]
    if not sound:
        # mvhd (birinchi bola) qoladi, audio trek olib tashlanadi.
        mvhd_size = struct.unpack(">I", children[:4])[0]
        children = children[:mvhd_size]
    extra = _box(b"mvex", _full(b"trex", 0, 0, b"\0" * 20)) if fragmented else b""
    return data[:moov_at] + _box(b"moov", VIDEO_TRAK, children, extra)


# --- audio.py ---------------------------------------------------------------------------------


def test_videodan_aac_audio_ajratiladi(tmp_path):
    src, dst = tmp_path / "v.mp4", tmp_path / "v.aac"
    src.write_bytes(video_mp4(30))
    assert audio.has_video_track(src) is True
    info = audio.video_to_adts(src, dst)
    assert info["codecs"] == ["mp4a"] and abs(info["durationSec"] - 30) < 0.2
    assert abs(audio.adts_info(dst).durationSec - 30) < 0.2
    assert src.exists()                                   # asl faylni o'chirish - chaqiruvchining ishi


def test_audiosiz_video_ovoz_yoq(tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(video_mp4(sound=False))
    with pytest.raises(audio.NoAudioTrack):
        audio.video_to_adts(src, tmp_path / "v.aac")
    assert not (tmp_path / "v.aac").exists()


@pytest.mark.parametrize("m4a", [{"codec": b"Opus"}, {"oti": 0x6B}])
def test_aac_bolmagan_audio_mp4_yuboring(tmp_path, m4a):
    src = tmp_path / "v.mp4"
    src.write_bytes(video_mp4(**m4a))
    with pytest.raises(audio.UnsupportedAudio):
        audio.video_to_adts(src, tmp_path / "v.aac")


def test_fragmentlangan_mp4_va_boshqa_konteyner(tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(video_mp4(fragmented=True))
    with pytest.raises(audio.UnsupportedAudio):
        audio.video_to_adts(src, tmp_path / "v.aac")
    src.write_bytes(WEBM)
    with pytest.raises(audio.UnsupportedAudio):
        audio.video_to_adts(src, tmp_path / "v.aac")


def test_video_turlari_va_fayl_boshi(tmp_path):
    assert audio.canonical_type("video/quicktime") == audio.canonical_type("Video/MP4") == "video/mp4"
    assert audio.is_video_type("video/webm") and not audio.is_video_type("audio/mp4")
    assert audio.sniff(video_mp4()[:16], "video/mp4")
    assert audio.sniff(struct.pack(">I", 8) + b"moov" + b"\0" * 8, "video/mp4")      # eski MOV: ftyp siz
    assert not audio.sniff(WEBM[:16], "video/mp4")
    m4a = tmp_path / "a.m4a"
    m4a.write_bytes(phone_m4a(10, rate=16000)[0])
    assert audio.has_video_track(m4a) is False


# --- HTTP (mobil ilova) ------------------------------------------------------------------------


def _meeting(rt, meeting_id):
    return rt.store.meeting(1, meeting_id)


def test_video_yuklanadi_faqat_audio_qoladi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    rt = _isolated_meetings
    data = video_mp4(64)
    view = create_meeting(client, auth, contentType="video/quicktime")
    upload_all(client, auth, view["id"], data)
    done = complete(client, auth, view["id"], data)
    assert done.status_code == 202, done.text
    m = _meeting(rt, view["id"])
    assert m["status"] == "uploaded" and m["content_type"] == "audio/aac"
    assert m["audio_path"].endswith(".aac") and Path(m["audio_path"]).exists()
    assert abs(m["duration_sec"] - 64) < 0.5
    # Video hech qayerda qolmaydi: yuklash papkasi bo'sh, audio papkada faqat .aac.
    assert not rt.store.upload_path(view["id"]).exists()
    assert not any(p.suffix in (".mp4", ".part") for p in rt.store.root.rglob("*") if p.is_file())
    # Takroriy `/complete` (ilova javobni olmadi) - o'sha yig'ilish, xatosiz.
    assert complete(client, auth, view["id"], data).status_code == 200


def test_audio_mp4_deb_kelgan_video_ham_ajratiladi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    data = video_mp4(20)
    view = create_meeting(client, auth, contentType="audio/mp4")
    upload_all(client, auth, view["id"], data)
    assert complete(client, auth, view["id"], data).status_code == 202
    assert _meeting(_isolated_meetings, view["id"])["content_type"] == "audio/aac"


def test_audiosiz_video_422_va_video_ochiriladi(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    data = video_mp4(sound=False)
    view = create_meeting(client, auth, contentType="video/mp4")
    upload_all(client, auth, view["id"], data)
    done = complete(client, auth, view["id"], data)
    assert done.status_code == 422 and done.json()["code"] == "video_no_audio"
    assert done.json()["message"] == "Videoda ovoz yo'q."
    m = _meeting(_isolated_meetings, view["id"])
    assert (m["status"], m["error_code"]) == ("failed", "video_no_audio")
    assert not _isolated_meetings.store.upload_path(view["id"]).exists()


def test_boshqa_video_formatlari_mp4_yuboring(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    payload = {"clientId": "c2c63a6e-3a5b-4c2e-9d3f-111111111111", "recordedAt": "2026-11-17T06:00:00Z",
               "language": "uz", "contentType": "video/webm"}
    bad = client.post("/api/v1/meetings", json=payload, headers={**auth, "X-Venera-Client": "mobile"})
    assert bad.status_code == 415 and bad.json()["code"] == "video_unsupported"
    # `video/mp4` deb e'lon qilingan, ichi esa WebM - birinchi bo'lakda.
    view = create_meeting(client, auth, contentType="video/mp4")
    first = put_chunk(client, auth, view["id"], 0, WEBM)
    assert first.status_code == 415 and first.json()["code"] == "video_unsupported"
    # Fragmentlangan MP4 - yakunlashda.
    data = video_mp4(fragmented=True)
    view = create_meeting(client, auth, contentType="video/mp4")
    upload_all(client, auth, view["id"], data)
    done = complete(client, auth, view["id"], data)
    assert done.status_code == 415 and done.json()["code"] == "video_unsupported"
    assert _meeting(_isolated_meetings, view["id"])["error_code"] == "video_unsupported"


def test_videoning_hajm_chegarasi_alohida(client, auth, monkeypatch, _isolated_meetings):
    enable(monkeypatch)
    monkeypatch.setattr(settings, "meetings_max_upload_mb", 0)      # audio uchun - hech narsa sig'maydi
    data = video_mp4(30)
    audio_view = create_meeting(client, auth, contentType="audio/mp4")
    too_big = put_chunk(client, auth, audio_view["id"], 0, data[:4096])
    assert too_big.status_code == 413 and too_big.json()["code"] == "upload_too_large"
    video_view = create_meeting(client, auth, contentType="video/mp4")
    upload_all(client, auth, video_view["id"], data)              # video - `meetings_max_video_mb` (1 GB)
    assert complete(client, auth, video_view["id"], data).status_code == 202
    assert service.max_upload_bytes("video/quicktime") == 1024 * 1024 * 1024


# --- Slack -------------------------------------------------------------------------------------


def test_slack_videoni_yozuv_deb_oladi(tmp_path, monkeypatch):
    data = video_mp4(30)

    def fake_download(url, dest, limit, **kw):
        assert limit == 1024 * 1024 * 1024 and url == "https://files.slack.com/v.mp4"
        dest.write_bytes(data)
        return len(data), hashlib.sha256(data).hexdigest(), data[:16]

    monkeypatch.setattr(slack_transcribe, "download", fake_download)
    video = {"id": "F1", "name": "yigilish.mov", "mimetype": "video/quicktime",
             "url_private_download": "https://files.slack.com/v.mp4"}
    assert slack_transcribe.is_audio(video) and slack_transcribe.is_video(video)
    path, size, sha, kind = slack_transcribe.fetch(video, tmp_path)
    assert (kind, size) == ("video/mp4", len(data)) and path.read_bytes() == data
    assert slack_meeting.received(video).startswith("🎬 «yigilish.mov» qabul qilindi - videodan faqat audio olinadi")
    with pytest.raises(slack_transcribe.Problem, match="MP4 yuboring"):
        slack_transcribe.fetch({**video, "mimetype": "video/webm"}, tmp_path)
    monkeypatch.setattr(slack_transcribe, "download",
                        lambda url, dest, limit, **kw: (dest.write_bytes(WEBM), (len(WEBM), "x", WEBM[:16]))[1])
    with pytest.raises(slack_transcribe.Problem, match="MP4 yuboring"):
        slack_transcribe.fetch({**video, "mimetype": "video/mp4"}, tmp_path)


def test_boshqa_formatda_yuborilgan_video_xabari():
    # Odam ko'radigan matn uchala joyda bir xil: HTTP (mobil), Slack va Telegram.
    from app.bot import plaud as plaud_mod
    from app.services.meetings.errors import message_for

    assert message_for("video_unsupported") == slack_transcribe.VIDEO_UNSUPPORTED == plaud_mod.VIDEO_UNSUPPORTED
    assert message_for("video_no_audio") == "Videoda ovoz yo'q."

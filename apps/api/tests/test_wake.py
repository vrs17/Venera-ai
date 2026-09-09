"""Uyg'otish so'zi: moslashtirgich va jurnal.

Moslashtirgich SHU YERDA sinaladi, brauzerda emas - qaror serverda qabul
qilinadi. Kutilgan natijalar TAXMIN emas: "salom, venera." va "assalomu
alaykum venera." aynan STT dan qaytgan matnlar (TTS -> STT aylanmasida
o'lchangan).
"""

from __future__ import annotations

import json

import pytest

from app.services.wake import (
    WakeLog,
    distance,
    is_wake_phrase,
    normalize_heard,
)


@pytest.mark.parametrize("text", [
    "salom, venera.",                 # <- STT dan AYNAN shu qaytadi
    "assalomu alaykum venera.",       # <- va shu
    "Salom Venera",
    "salom venera",
    "salom vinera",                   # model bir xil tovushni turlicha yozadi
    "salom venira",
    "salom venere",
    "assalom venera",
    "SALOM VENERA.",
    "salom, venera!",
    "salomvenera",                    # model so'zlarni qo'shib yuboradi
    "venera",                         # salomsiz, lekin YOLG'IZ - bu chaqiriq
    "venera.",
    "venerat",
    "hey venera",
])
def test_uygotadi(text):
    matched, reason = is_wake_phrase(text)
    assert matched, f"{text!r} uyg'otmadi ({reason})"


@pytest.mark.parametrize("text", [
    "venera tizimi haqida malumot bering",   # gap ichida nom
    "salom qanday yordam bera olasan venera menga",
    "menga venera haqida ayting",
    "salom",                                  # nom yo'q
    "salom dunyo",
    "assalomu alaykum",
    "vera bilan gaplashdim",                  # qisqa so'z - noto'g'ri moslik xavfi
    "era boshlandi",
    "",
    "rahmat",
])
def test_uygotmaydi(text):
    matched, reason = is_wake_phrase(text)
    assert not matched, f"{text!r} noto'g'ri uyg'otdi ({reason})"


def test_sabab_aytiladi():
    """"Uyg'onmadi" degan yozuv foydasiz - jurnal NEGA ekanini ko'rsatishi
    kerak, aks holda qoidalarni sozlash taxmin bo'lib qoladi."""
    assert is_wake_phrase("")[1] == "bo'sh"
    assert is_wake_phrase("salom dunyo")[1] == "nom yo'q"
    assert "juda uzun" in is_wake_phrase("bir ikki uch tort besh olti yetti")[1]
    assert is_wake_phrase("menga venera kerak edi")[1] == "salom yo'q"
    assert is_wake_phrase("salom venera")[1] == "salom + nom"
    assert "faqat nom" in is_wake_phrase("venera")[1]


def test_apostroflar_teng():
    """O'zbek imlosida bir necha xil apostrof teng ishlatiladi."""
    assert normalize_heard("o'zbek") == normalize_heard("oʻzbek") == normalize_heard("o’zbek")


def test_distance():
    assert distance("venera", "venera") == 0
    assert distance("venera", "vinera") == 1
    assert distance("venera", "butunlay boshqa") > 3


# --- jurnal -----------------------------------------------------------------


def test_jurnal_audio_va_qatorni_yozadi(tmp_path):
    log = WakeLog(tmp_path)
    entry = log.record(b"RIFF-audio", actor_id=7, language="uz",
                       text="salom venera", matched=True, reason="salom + nom",
                       duration_sec=1.2, backend="uzbek_stt")

    assert (tmp_path / entry.audio).read_bytes() == b"RIFF-audio"
    rows = [json.loads(line) for line in (tmp_path / "wake.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["text"] == "salom venera"
    assert rows[0]["matched"] is True
    assert rows[0]["reason"] == "salom + nom"


def test_jurnal_emailni_saqlamaydi(tmp_path):
    """Ovoz yozuvi allaqachon shaxsiy ma'lumot - yoniga email qo'yish uni
    yanada aniqroq qilardi. Ichki `actor_id` yetarli."""
    log = WakeLog(tmp_path)
    log.record(b"x", actor_id=7, language="uz", text="salom venera",
               matched=True, reason="salom + nom")
    raw = (tmp_path / "wake.jsonl").read_text()
    assert "@" not in raw
    assert '"actor_id": 7' in raw


def test_jurnal_eski_audiolarni_ochiradi(tmp_path):
    """Yozuvlar to'planib qoladi. Qatorlar QOLADI - ular kichkina va
    statistika uchun kerak; audio esa joy egallaydi."""
    log = WakeLog(tmp_path, max_files=3)
    for i in range(6):
        log.record(f"audio{i}".encode(), actor_id=1, language="uz",
                   text=f"urinish {i}", matched=False, reason="nom yo'q")
    assert len(list((tmp_path / "audio").glob("*.wav"))) == 3
    assert len((tmp_path / "wake.jsonl").read_text().splitlines()) == 6


def test_jurnal_yozilmasa_ham_yiqilmaydi(tmp_path, monkeypatch):
    """Bu DIAGNOSTIKA, funksiya emas: disk to'lgan bo'lsa ham uyg'otishning
    o'zi ishlashda davom etishi kerak."""
    log = WakeLog(tmp_path / "yoq")
    monkeypatch.setattr("pathlib.Path.mkdir",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk to'la")))
    entry = log.record(b"x", actor_id=1, language="uz", text="salom venera",
                       matched=True, reason="salom + nom")
    assert entry.matched is True


# --- endpoint ---------------------------------------------------------------


def _clip():
    import io
    return {"file": ("wake.wav", io.BytesIO(b"RIFF" + b"\0" * 2048), "audio/wav")}


def test_tokensiz_rad_etiladi(client):
    response = client.post("/api/v1/stt/wake", files=_clip(), data={"language": "uz"})
    assert response.status_code == 401


def test_qaror_va_matn_qaytadi(client, auth, monkeypatch, tmp_path):
    from app.services.stt import Transcript
    import app.api.v1.stt as module

    monkeypatch.setattr(module._client, "transcribe",
                        lambda audio, **kw: Transcript(text="salom venera", language="uz"))
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))

    body = client.post("/api/v1/stt/wake", files=_clip(),
                       data={"language": "uz"}, headers=auth).json()
    assert body == {"text": "salom venera", "matched": True, "reason": "salom + nom"}
    assert (tmp_path / "wake.jsonl").exists(), "urinish yozilmadi"


def test_stt_xatosi_jim_otadi(client, auth, monkeypatch, tmp_path):
    """Uyg'otish tekshiruvi FON ishi. Hech kim hech narsa so'ramagan, ya'ni
    navbat to'la bo'lsa javob shunchaki "uyg'onmadi" bo'lishi kerak - har
    necha soniyada xato ko'rsatish sukunatdan yomonroq."""
    from app.services.stt import SttError
    import app.api.v1.stt as module

    def busy(audio, **kw):
        raise SttError("navbat to'la", status=503, retryable=True)

    monkeypatch.setattr(module._client, "transcribe", busy)
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))
    response = client.post("/api/v1/stt/wake", files=_clip(),
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 200
    assert response.json()["matched"] is False


def test_katta_audio_rad_etiladi(client, auth):
    """Uyg'otish parchasi qisqa (0.35-2.6 s). Kattasi xato yoki suiiste'mol."""
    import io
    big = {"file": ("wake.wav", io.BytesIO(b"\0" * (2 * 1024 * 1024)), "audio/wav")}
    response = client.post("/api/v1/stt/wake", files=big,
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 400

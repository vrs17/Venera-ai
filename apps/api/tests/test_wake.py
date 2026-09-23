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
    FLAT_LIMIT,
    WakeLog,
    distance,
    is_wake_phrase,
    measure,
    normalize_heard,
)


@pytest.mark.parametrize("text", [
    # Bu ro'yxat TAXMIN emas: hammasi jonli jurnaldan olingan, ya'ni odam
    # "Salom Venera" deganda model AYNAN shunday yozgan.
    "salou minera.",
    "salom verenam.",
    "salom, mener.",
    "salom venera.",
    "venera, venera. salom, venera.",
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
    # Bular ham jonli jurnaldan: model nomni BUTUNLAY yo'qotgan holatlar.
    # Ularda uyg'otish uchun hech qanday asos yo'q - "assalomu alaykum" esa
    # odamlar bir-biriga aytadigan gap, va unga uyg'onish tinimsiz noto'g'ri
    # ochilishga olib kelardi.
    "assalomu alaykum.",
    "salomu alaykum.",
    "salom beringlar.",
    "avvalo beringlar.",
    "salom, o'yinlar.",
    "salomera.",
    "avvaliga yana",
    "musiqa",
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


# --- o'lchov ----------------------------------------------------------------


def _wav(samples: list[int], rate: int = 16000) -> bytes:
    import array
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(array.array("h", samples).tobytes())
    return buf.getvalue()


def _tone(seconds: float = 1.0, hz: int = 200, rate: int = 16000) -> list[int]:
    import math
    return [int(8000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(int(rate * seconds))]


def test_olchov_buzilgan_yozuvni_topadi():
    """Jonli holat: brauzer nutqni alohida impulslarga bo'lib, orasini nol
    bilan to'ldirgan. Odam buni "shovqin" deb eshitadi, model esa hech
    narsa eshitmaydi. Bu raqamsiz muammo moslashtirgichga yuklanardi."""
    tone = _tone()
    # Har 20 ms dan faqat 4 ms qoladi - haqiqiy yozuvlardagi manzara.
    gated = [v if (i % 320) < 64 else 0 for i, v in enumerate(tone)]

    _, _, speech, clean = measure(_wav(tone))
    _, _, _, broken = measure(_wav(gated))

    assert speech > 0.9
    assert clean < 0.05                # uzluksiz to'lqinda tekis nol yo'q
    assert broken > 0.5
    assert clean < FLAT_LIMIT < broken


def test_olchov_jimlikni_nutq_demaydi():
    """Nutq yo'q bo'lsa tekis ulush ham 0 - jimlik "buzilgan" emas."""
    peak, rms, speech, flat = measure(_wav([0] * 16000))
    assert (peak, rms, speech, flat) == (0.0, 0.0, 0.0, 0.0)


def test_olchov_yaroqsiz_wavda_yiqilmaydi():
    assert measure(b"") == (0.0, 0.0, 0.0, 0.0)
    assert measure(b"RIFF" + b"\0" * 100) == (0.0, 0.0, 0.0, 0.0)


def test_jurnal_buzilishni_yozadi(tmp_path):
    """`flat` qatorga tushadi - hisobot shundan "avval yozuvni tuzating"
    deb ayta oladi."""
    tone = _tone()
    gated = [v if (i % 320) < 64 else 0 for i, v in enumerate(tone)]
    log = WakeLog(tmp_path)
    entry = log.record(_wav(gated), actor_id=1, language="uz", text="assalomu alaykum",
                       matched=False, reason="nom yo'q")
    assert entry.flat > FLAT_LIMIT
    row = json.loads((tmp_path / "wake.jsonl").read_text().splitlines()[0])
    assert row["flat"] == entry.flat


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

    monkeypatch.setattr(module._router_client, "transcribe",
                        lambda audio, **kw: Transcript(text="salom venera", language="uz"))
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))

    body = client.post("/api/v1/stt/wake", files=_clip(),
                       data={"language": "uz"}, headers=auth).json()
    assert body == {"text": "salom venera", "matched": True,
                    "reason": "salom + nom", "checked": True, "distorted": False}
    assert (tmp_path / "wake.jsonl").exists(), "urinish yozilmadi"


def test_buzilgan_audio_haqida_aytiladi(client, auth, monkeypatch, tmp_path):
    """Nutq darvoza bilan kesilgan bo'lsa, "uyg'onmadi" ning aybi so'zda
    emas. Javobdagi `distorted` brauzerga buni foydalanuvchiga aytish
    imkonini beradi - darvozani faqat u o'chira oladi."""
    import io
    from app.services.stt import Transcript
    import app.api.v1.stt as module

    monkeypatch.setattr(module._router_client, "transcribe",
                        lambda audio, **kw: Transcript(text="assalomu alaykum", language="uz"))
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))
    tone = _tone()
    gated = _wav([v if (i % 320) < 64 else 0 for i, v in enumerate(tone)])

    body = client.post("/api/v1/stt/wake", files={"file": ("wake.wav", io.BytesIO(gated), "audio/wav")},
                       data={"language": "uz"}, headers=auth).json()
    assert body["matched"] is False
    assert body["distorted"] is True

    clean = client.post("/api/v1/stt/wake", files={"file": ("wake.wav", io.BytesIO(_wav(tone)), "audio/wav")},
                        data={"language": "uz"}, headers=auth).json()
    assert clean["distorted"] is False


def test_stt_xatosi_jim_otadi(client, auth, monkeypatch, tmp_path):
    """Uyg'otish tekshiruvi FON ishi. Hech kim hech narsa so'ramagan, ya'ni
    navbat to'la bo'lsa javob shunchaki "uyg'onmadi" bo'lishi kerak - har
    necha soniyada xato ko'rsatish sukunatdan yomonroq."""
    from app.services.stt import SttError
    import app.api.v1.stt as module

    def busy(audio, **kw):
        raise SttError("navbat to'la", status=503, retryable=True)

    monkeypatch.setattr(module._router_client, "transcribe", busy)
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))
    response = client.post("/api/v1/stt/wake", files=_clip(),
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    # `checked=False` "uyg'otish so'zi emas" EMAS, "tekshirib bo'lmadi"
    # degani. Klient buni ko'rib urinishlar oralig'ini uzaytiradi - o'chgan
    # backend'ni har ikki soniyada urib turishning ma'nosi yo'q.
    assert body["checked"] is False


def _fake_transcript(text: str):
    from app.services.stt import Transcript

    return Transcript(text=text, language="uz", backend="uzbek_stt",
                      model="uzbek_stt_v1", duration_sec=1.2, elapsed_sec=0.1)


def _wake_on_gapi(monkeypatch, module):
    """Uyg'otishni 2-variantga o'tkazadi (conftest hammasini `router` ga
    qadab qo'yadi - bu testlar aynan GAPI yo'lini sinaydi, lekin TARMOQQA
    chiqmaydi: klientlarning `transcribe`'si almashtiriladi)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "stt_wake_provider", "gapi")
    monkeypatch.setattr(module._gapi_client, "_api_key", "gapi_test_kalit")


def test_gapi_berilmasa_uygotish_routerga_tushadi(client, auth, monkeypatch, tmp_path):
    """Uyg'otish 2-variantda, ammo chegara urilganda 1-variant davom ettiradi.

    NEGA BU KERAK. GAPI uyg'otish uchun PULLIK va chegaralangan: kunlik
    480 audio-daqiqa, daqiqasiga 60 yuklash (bitta parcha o'lchangan narxi
    0.03 g). Zahirasiz kvota tugagan kuni uyg'otish YARIM KECHAGACHA
    butunlay ishlamas edi: tinglagich xatolarni ko'rib oraliqni 60
    sekundgacha uzaytiradi, ya'ni odam "Salom Venera" deb chaqirsa ham
    javob bo'lmasdi - va buni hech kim jurnalga qaramasa bilmasdi.
    """
    from app.services.stt import SttError
    import app.api.v1.stt as module

    _wake_on_gapi(monkeypatch, module)
    calls: list[str] = []

    def chegara(audio, **kw):
        calls.append("gapi")
        raise SttError("kunlik chegara tugadi", status=429, retryable=True)

    def router(audio, **kw):
        calls.append("router")
        return _fake_transcript("salom venera")

    monkeypatch.setattr(module._gapi_wake_client, "transcribe", chegara)
    monkeypatch.setattr(module._router_client, "transcribe", router)
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))

    body = client.post("/api/v1/stt/wake", files=_clip(),
                       data={"language": "uz"}, headers=auth).json()
    assert calls == ["gapi", "router"], "zahiraga tushmadi"
    assert body["matched"] is True
    assert body["checked"] is not False


@pytest.mark.parametrize("status", [400, 413, 415])
def test_yaroqsiz_parcha_ikki_marta_yuborilmaydi(client, auth, monkeypatch, tmp_path, status):
    """Yaroqsiz parcha Router'da ham yaroqsiz. Ikkinchi urinish - behuda
    sarf va ikki barobar kechikish, natija esa o'sha."""
    from app.services.stt import SttError
    import app.api.v1.stt as module

    _wake_on_gapi(monkeypatch, module)
    calls: list[str] = []

    def yaroqsiz(audio, **kw):
        calls.append("gapi")
        raise SttError("audio yaroqsiz", status=status)

    def router(audio, **kw):
        calls.append("router")
        return _fake_transcript("salom venera")

    monkeypatch.setattr(module._gapi_wake_client, "transcribe", yaroqsiz)
    monkeypatch.setattr(module._router_client, "transcribe", router)
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))

    body = client.post("/api/v1/stt/wake", files=_clip(),
                       data={"language": "uz"}, headers=auth).json()
    assert calls == ["gapi"], "Router'ga behuda yuborildi"
    assert body["checked"] is False


def test_byudjet_tugasa_routerga_tushadi(client, auth, monkeypatch, tmp_path):
    """Pullik so'rovlar byudjeti tugaganda uyg'otish TO'XTAMAYDI - bepul
    1-variant davom ettiradi.

    Chegara MIJOZDA turgan edi (`COOLDOWN_MS = 2500`), ya'ni o'zgartirilgan
    sahifa yoki bir odamning uchta varag'i hisobni yeb qo'yishi mumkin edi.
    Server tomonidagi byudjet mijozga bog'liq emas.
    """
    import app.api.v1.stt as module
    from app.core.config import settings

    _wake_on_gapi(monkeypatch, module)
    monkeypatch.setattr(settings, "wake_gapi_total_min", 1)
    monkeypatch.setattr(module, "_wake_budget", module._WakeBudget())
    calls: list[str] = []

    def gapi(audio, **kw):
        calls.append("gapi")
        return _fake_transcript("salom venera")

    def router(audio, **kw):
        calls.append("router")
        return _fake_transcript("salom venera")

    monkeypatch.setattr(module._gapi_wake_client, "transcribe", gapi)
    monkeypatch.setattr(module._router_client, "transcribe", router)
    monkeypatch.setattr(module, "_wake_log", WakeLog(tmp_path))

    for _ in range(3):
        body = client.post("/api/v1/stt/wake", files=_clip(),
                           data={"language": "uz"}, headers=auth).json()
        # Har safar ishlaydi - byudjet FAQAT qaysi xizmat ishlashini
        # hal qiladi, ishlash-ishlamaslikni emas.
        assert body["matched"] is True
    assert calls == ["gapi", "router", "router"], calls


def test_uygotish_vaqt_byudjeti_qisqa():
    """Uyg'otish parchasi savol byudjetini olmasligi kerak.

    `gapi_timeout = 60` va `stt_deadline = 100` - SAVOL uchun o'lchangan.
    Uyg'otish parchasi har 2.5 sekundda keladi va brauzer keyingisini
    yuborganda oldingisini bekor qiladi, ya'ni 60 sekund kutish javobsiz
    qoladigan, lekin slotni va threadpool ishchisini band qilib turadigan,
    ustiga PULI ketgan ish bo'lardi.
    """
    import app.api.v1.stt as module

    assert module._gapi_wake_client.timeout <= 8.0
    assert module._gapi_wake_client.deadline <= 10.0


def test_uygotish_savolning_slotini_olmaydi():
    """O'LCHANGAN XAVF. Bitta klientda slotlar umumiy bo'lardi va 4 ta
    parallel so'rovdan to'rtinchisi `503 ilova GAPI chegarasida` olgan
    edi - ya'ni tinglagich har 2.5 sekundda parcha yuborib turganda
    foydalanuvchining SAVOLI "Ovoz xizmati band" xatosini olishi mumkin
    edi. Uyg'otish Router'da turganda bunday bo'lishi mumkin emas edi.

    Shuning uchun uyg'otishning ALOHIDA semafori bor: fon ishi asosiy
    ishning ikki slotiga tegmaydi.
    """
    import app.api.v1.stt as module

    assert module._gapi_wake_client is not module._gapi_client
    assert module._gapi_wake_client.max_concurrent == 1
    assert module._gapi_wake_client._slots is not module._gapi_client._slots
    # Fon ishi kutib qayta urinmaydi: kechikkan uyg'otishning qadri yo'q,
    # va `Retry-After` kutishi threadpool ishchisini ushlab turardi.
    assert module._gapi_wake_client.attempts == 1


def test_katta_audio_rad_etiladi(client, auth):
    """Uyg'otish parchasi qisqa (0.35-2.6 s). Kattasi xato yoki suiiste'mol."""
    import io
    big = {"file": ("wake.wav", io.BytesIO(b"\0" * (2 * 1024 * 1024)), "audio/wav")}
    response = client.post("/api/v1/stt/wake", files=big,
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 400


# --- yuqoridagi xizmatlar holati --------------------------------------------


@pytest.mark.parametrize("status", [402, 429, 502, 503, 504])
def test_savol_ham_kvota_tugasa_routerga_tushadi(client, auth, monkeypatch, status):
    """SAVOL yo'li ham zahirali bo'lishi kerak, nafaqat uyg'otish.

    Avval zahira faqat uyg'otishda edi va assimetriya noto'g'ri edi: kvota
    tugagan kuni mikrofon tugmasi kun oxirigacha xato qaytarardi, holbuki
    ichki Router bepul, chegarasiz va bir qadam narida turgan. Ovoz
    butunlay o'lgandan ko'ra Router'ning matni (kichik harf, tinish
    belgisisiz) aniq afzal.
    """
    from app.services.stt import SttError
    import app.api.v1.stt as module
    from app.core.config import settings

    monkeypatch.setattr(settings, "stt_provider", "gapi")
    monkeypatch.setattr(module._gapi_client, "_api_key", "gapi_test_kalit")
    calls: list[str] = []

    def gapi(audio, **kw):
        calls.append("gapi")
        raise SttError("chegara", status=status, retryable=True)

    def router(audio, **kw):
        calls.append("router")
        return _fake_transcript("bugun kim kechikdi")

    monkeypatch.setattr(module._gapi_client, "transcribe", gapi)
    monkeypatch.setattr(module._router_client, "transcribe", router)

    response = client.post("/api/v1/stt/transcribe", files=_clip(),
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "bugun kim kechikdi"
    # Javob QAYSI variant ishlaganini aytadi - almashish jim emas.
    assert body["backend"] == "uzbek_stt"
    assert calls == ["gapi", "router"], calls


@pytest.mark.parametrize("status", [400, 413, 415, 422])
def test_savolda_yaroqsiz_audio_ikki_marta_yuborilmaydi(client, auth, monkeypatch, status):
    """Yaroqsiz parcha Router'da ham yaroqsiz: ikkinchi urinish kechikishni
    ikki barobar qilib, natijani o'zgartirmaydi."""
    from app.services.stt import SttError
    import app.api.v1.stt as module
    from app.core.config import settings

    monkeypatch.setattr(settings, "stt_provider", "gapi")
    monkeypatch.setattr(module._gapi_client, "_api_key", "gapi_test_kalit")
    calls: list[str] = []

    def gapi(audio, **kw):
        calls.append("gapi")
        raise SttError("yaroqsiz", status=status)

    def router(audio, **kw):
        calls.append("router")
        return _fake_transcript("bo'lmasin")

    monkeypatch.setattr(module._gapi_client, "transcribe", gapi)
    monkeypatch.setattr(module._router_client, "transcribe", router)

    response = client.post("/api/v1/stt/transcribe", files=_clip(),
                           data={"language": "uz"}, headers=auth)
    assert calls == ["gapi"], calls
    assert response.status_code == status


def test_router_ham_yiqilsa_xato_yashirilmaydi(client, auth, monkeypatch):
    """Zahira ham ishlamasa foydalanuvchi ROSTINI ko'rishi kerak - jim
    "matn yo'q" emas."""
    from app.services.stt import SttError
    import app.api.v1.stt as module
    from app.core.config import settings

    monkeypatch.setattr(settings, "stt_provider", "gapi")
    monkeypatch.setattr(module._gapi_client, "_api_key", "gapi_test_kalit")

    def gapi(audio, **kw):
        raise SttError("chegara", status=429, retryable=True)

    def router(audio, **kw):
        raise SttError("navbat to'la", status=503, retryable=True)

    monkeypatch.setattr(module._gapi_client, "transcribe", gapi)
    monkeypatch.setattr(module._router_client, "transcribe", router)

    response = client.post("/api/v1/stt/transcribe", files=_clip(),
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 503
    assert "band" in response.json()["message"].lower()
    # Ichki manzil yoki kalit chiqmasligi kerak.
    assert "10.10.50" not in response.text


def test_kvota_xatosi_rostini_aytadi(client, auth, monkeypatch):
    """Pullik chegara tugaganda foydalanuvchi ROSTINI ko'rishi kerak.

    429 `_MESSAGES` da yo'q bo'lganda status 502 ga tushib, ekranda "Ovoz
    xizmati javob bermadi" chiqardi - holbuki xizmat javob bergan, faqat
    bizning chegaramiz tugagan. Yolg'on xabar muammoni yashiradi va odam
    tarmoqni tekshira boshlaydi.
    """
    from app.services.stt import SttError
    import app.api.v1.stt as module

    def chegara(audio, **kw):
        raise SttError("kunlik chegara", status=429, retryable=True)

    monkeypatch.setattr(module._router_client, "transcribe", chegara)
    response = client.post("/api/v1/stt/transcribe", files=_clip(),
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 429
    assert "chegara" in response.json()["message"]


def test_gapi_da_uz_backend_ogohlantirishi_boshqacha(monkeypatch):
    """Ogohlantirish YOLG'ON aytmasligi kerak: o'zbek yo'llari GAPI da
    bo'lsa, Router'ning uz backend'i o'chgani uyg'otishni to'xtatmaydi."""
    from app.core.config import settings
    from app.services.upstream import warnings_for

    monkeypatch.setattr(settings, "stt_provider", "gapi")
    monkeypatch.setattr(settings, "stt_wake_provider", "gapi")
    warnings = warnings_for({
        "stt": {"status": "degraded", "broken": ["uzbek_stt"]},
        "tts": {"status": "ok"},
    })
    assert len(warnings) == 1
    assert "ISHLAMAYDI" not in warnings[0]
    # Lekin ZAHIRA yo'qolgani aytilishi kerak - bu haqiqiy xavf.
    assert "ZAHIRA" in warnings[0]


def test_uz_backend_ochganda_health_aytadi():
    """Ovoz zanjiri bizdan MUSTAQIL o'chadi va o'chganda ilova o'zi sog'lom
    ko'rinadi. Aynan shunday bo'ldi: uz backend o'chganini faqat log'ni ochib
    ko'rgandagina bilish mumkin edi."""
    from app.services.upstream import warnings_for

    warnings = warnings_for({
        "stt": {"status": "degraded", "broken": ["uzbek_stt"]},
        "tts": {"status": "ok"},
    })
    assert len(warnings) == 1
    # Xabar NIMA ISHLAMASLIGINI aytadi, "degraded" demaydi.
    assert "Salom Venera" in warnings[0] and "ISHLAMAYDI" in warnings[0]


def test_hammasi_sogolom_bolsa_jim():
    from app.services.upstream import warnings_for
    assert warnings_for({"stt": {"status": "ok", "broken": []},
                         "tts": {"status": "ok"}}) == []


def test_router_umuman_javob_bermasa():
    from app.services.upstream import warnings_for
    warnings = warnings_for({"stt": {"status": "unreachable"}, "tts": {"status": "ok"}})
    assert "STT Router javob bermayapti" in warnings[0]


def test_upstream_keshlanadi(monkeypatch):
    """`/api/health` monitoring tomonidan tez-tez so'raladi. Har safar ikkita
    tashqi so'rov yuborish ularni ortiqcha bezovta qilardi."""
    from app.services.upstream import UpstreamHealth

    calls = []
    health = UpstreamHealth("http://stt", "http://tts")
    monkeypatch.setattr(health, "_get", lambda url: calls.append(url) or {"status": "ok"})
    for _ in range(5):
        health.snapshot()
    assert len(calls) == 2, f"{len(calls)} ta so'rov - kesh ishlamadi"


def test_upstream_yiqilsa_health_yiqilmaydi(monkeypatch):
    """Tashqi xizmat javob bermasligi `/api/health` ni buzmasligi kerak -
    aks holda monitoring butun ilovani o'chgan deb ko'rsatardi."""
    from app.services.upstream import UpstreamHealth

    health = UpstreamHealth("http://yoq.invalid", "http://yoq.invalid")
    snapshot = health.snapshot()
    assert snapshot["stt"]["status"] == "unreachable"
    assert snapshot["tts"]["status"] == "unreachable"


def test_gapi_500_da_ham_zahira_ishlaydi(client, auth, monkeypatch):
    """Qoida TESKARI: zahira faqat MIJOZ xatosida ishlamaydi.

    Avval "zahira ishlaydigan kodlar" ro'yxati bor edi va u jimgina
    to'liqsiz chiqdi - GAPI o'z serverida 500 (yoki 507, 409) bersa kod
    ro'yxatda yo'q edi va foydalanuvchiga xato ketardi, holbuki bepul
    Router bir qadam narida turgan.
    """
    from app.services.stt import SttError
    import app.api.v1.stt as module
    from app.core.config import settings

    monkeypatch.setattr(settings, "stt_provider", "gapi")
    monkeypatch.setattr(module._gapi_client, "_api_key", "gapi_test_kalit")
    calls: list[str] = []

    def gapi(audio, **kw):
        calls.append("gapi")
        raise SttError("GAPI 500 internal", status=500)

    def router(audio, **kw):
        calls.append("router")
        return _fake_transcript("bugun kim kechikdi")

    monkeypatch.setattr(module._gapi_client, "transcribe", gapi)
    monkeypatch.setattr(module._router_client, "transcribe", router)

    response = client.post("/api/v1/stt/transcribe", files=_clip(),
                           data={"language": "uz"}, headers=auth)
    assert response.status_code == 200
    assert calls == ["gapi", "router"], calls


def test_zahira_hisoblanadi_va_health_aytadi(client, auth, monkeypatch):
    """Zahira ishlagani KO'RINADIGAN joyda turishi kerak.

    Zahira ishlaganda foydalanuvchi uchun hammasi joyida ko'rinadi - va
    aynan shu xavfli: tizim kun bo'yi 1-variantda ishlab, health esa
    `provider=gapi` deb ko'rsatib turishi mumkin edi.
    """
    from app.services.stt import SttError
    import app.api.v1.stt as module
    from app.core.config import settings

    monkeypatch.setattr(settings, "stt_provider", "gapi")
    monkeypatch.setattr(module._gapi_client, "_api_key", "gapi_test_kalit")
    monkeypatch.setattr(module, "_fallbacks", module._FallbackLog())

    monkeypatch.setattr(module._gapi_client, "transcribe",
                        lambda audio, **kw: (_ for _ in ()).throw(
                            SttError("kvota", status=429, retryable=True)))
    monkeypatch.setattr(module._router_client, "transcribe",
                        lambda audio, **kw: _fake_transcript("javob"))

    client.post("/api/v1/stt/transcribe", files=_clip(),
                data={"language": "uz"}, headers=auth)

    snap = module._fallbacks.snapshot()
    assert snap["total"] == 1
    assert snap["last_5min"] == 1
    assert snap["last_status"] == 429
    assert snap["last_path"] == "Transkripsiya"

    detail = client.get("/api/health/detail", headers=auth).json()
    assert detail["stt"]["fallback"]["last_5min"] == 1
    assert any("zahirasi" in w for w in detail["warnings"]), detail["warnings"]


def test_oxirgi_urinishdan_keyin_uxlamaydi(monkeypatch):
    """`attempts=1` bo'lgan klient ham bekorga uxlardi - shu vaqt davomida
    PULLIK slot va threadpool ishchisi band turardi."""
    import time as _time
    import urllib.request
    from app.services.integrations.gapi_stt import GapiSttClient
    from app.services.stt import SttError
    from tests.test_gapi_stt import FakeGapi, KEY, BASE, AUDIO

    fake = FakeGapi()
    fake.fail = (429, {"error": "rate_limited"}, {"Retry-After": "60"})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    uxlagan: list[float] = []
    monkeypatch.setattr(_time, "sleep", lambda s: uxlagan.append(s))
    import app.services.integrations.gapi_stt as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: uxlagan.append(s))

    client = GapiSttClient(BASE, KEY, timeout=5, deadline=30, attempts=1)
    with pytest.raises(SttError):
        client.transcribe(AUDIO, language="uz")
    assert uxlagan == [], f"bekorga uxladi: {uxlagan}"
    assert len(fake.calls) == 1

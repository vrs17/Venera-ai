"""Kutish ovozi: gaplar jadvali, tasnif, reja va kadrlar.

Ollama'ning O'ZI chaqirilmaydi: u tashqi pullik xizmat. Almashtirish nuqtasi
`urllib.request.urlopen` (tasniflagich testlarida) yoki `_hold_classifier`
(oqim testlarida) - ya'ni ustidagi hamma mantiq haqiqiy kod bo'lib qoladi.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
import urllib.error
import urllib.request
import wave

import pytest

from app.services.hold import (
    MAVZULAR, OHANGLAR, HoldVoices, _GAPLAR, all_clips, clip_key, keyword_topic, pick,
)
from app.services.integrations.assistant import AnswerStream
from app.services.integrations.ollama import HoldClassifier, parse_label

BASE = "https://ollama.test"
KEY = "10353deec7874648981b52bc051b3a59.L5hTO6mDUCJAU0mzAMYc9P1W"


# ================================================================ gaplar jadvali


def _hamma_gaplar():
    return [matn for gaplar in _GAPLAR.values() for matn in gaplar]


@pytest.mark.parametrize("matn", _hamma_gaplar())
def test_gapda_raqam_yoq(matn):
    """ENG MUHIM QOIDA. Kutish gapi javob emas, kutish haqida: unda raqamning
    bironta to'g'ri ma'nosi yo'q. Raqam bo'lsa - u fakt kabi eshitiladi va
    odam uni HRM ma'lumoti deb qabul qiladi."""
    assert not re.search(r"\d", matn), matn


@pytest.mark.parametrize("matn", _hamma_gaplar())
def test_gapda_natija_ham_vada_ham_yoq(matn):
    """"Topdim", "ma'lum bo'ldi" - natija haqida yolg'on. "Hozir tayyor
    bo'ladi", "deyarli" - VA'DA, va u 30 sekundlik kutishda yolg'on chiqadi.
    Kutish gapi faqat rost gapiradi: ishlayapman, kuting, kechirasiz."""
    # `ma'lum bo'ldi` - natija da'vosi. Yolg'iz `ma'lum` EMAS: u
    # "ma'lumotlarni" (ma'lumotlar) so'zini ham ushlab, to'g'ri gapni rad
    # etardi.
    taqiq = (r"topdim|topildi|ma'lum\s+bo'?l|aniqlandi|natija|marta|foiz|"
             r"tayyor\s+bo'?ladi|deyarli|tugay|hozir\s+aytaman")
    assert not re.search(taqiq, matn.lower()), matn


@pytest.mark.parametrize("matn", _hamma_gaplar())
def test_gap_qisqa(matn):
    """Birinchi ovoz tez javobni USHLAB turadi (javob u tugashini kutadi),
    ya'ni har ortiqcha so'z tez javobni kechiktiradi."""
    assert len(matn.split()) <= 10, matn


def test_har_mavzu_va_ohang_uchun_gap_bor():
    """Tasniflagich qaytarishi mumkin bo'lgan HAR yorliq ovozga ega bo'lishi
    kerak - aks holda yangi mavzu qo'shilganda ovoz jimgina yo'qoladi."""
    for mavzu in MAVZULAR:
        for ohang in OHANGLAR:
            for bosqich in ("ilk", "davom"):
                matn, kalit = pick(mavzu, ohang, bosqich, 0)
                assert matn and kalit, (mavzu, ohang, bosqich)


def test_ovoz_kalitlari_takrorlanmaydi():
    kalitlar = [k for k, _ in all_clips()]
    assert len(kalitlar) == len(set(kalitlar))


def test_matn_ozgarsa_kalit_ham_ozgaradi():
    """Ovoz brauzerda `immutable` bilan keshlanadi. Kalit matnga bog'liq
    bo'lmasa, gap tuzatilganda brauzer ESKI ovozni bir kun o'ynatib turardi."""
    assert clip_key("tatil", "oddiy", "ilk", 0, "A.") != clip_key("tatil", "oddiy", "ilk", 0, "B.")


def test_kalit_endpoint_naqshiga_mos():
    """Kalit URL da ketadi. Nuqta yoki `/` bo'lsa - fayl tizimida boshqa
    joyga chiqish yo'li ochiladi."""
    for kalit, _ in all_clips():
        assert re.fullmatch(r"[a-z0-9-]{1,80}", kalit), kalit


def test_ilk_gap_navbat_bilan_almashadi():
    """Kun bo'yi bitta gapni eshitish zeriktiradi."""
    birinchi = pick("kechikish", "oddiy", "ilk")[0]
    ikkinchi = pick("kechikish", "oddiy", "ilk")[0]
    assert birinchi != ikkinchi


def test_bitta_kutishda_davom_gapi_takrorlanmaydi():
    matnlar = [pick("umumiy", "oddiy", "davom", n)[0] for n in range(3)]
    assert len(set(matnlar)) == 3


def test_notanish_mavzu_umumiyga_tushadi():
    matn, kalit = pick("yangi-mavzu", "oddiy", "ilk", 0)
    assert kalit.startswith("umumiy-oddiy-ilk-")


# ======================================================================= tasnif


@pytest.mark.parametrize("raw,kutilgan", [
    ("kechikish|oddiy", ("kechikish", "oddiy")),
    ("tatil|shoshilinch", ("tatil", "shoshilinch")),
    ("  Kechikish | Shoshilinch  ", ("kechikish", "shoshilinch")),
    ('"hujjat|oddiy".', ("hujjat", "oddiy")),
    # Ohang yaroqsiz, mavzu to'g'ri - ohang "oddiy": shoshilmagan odamga
    # qo'pol gapirish xushmuomala gapirishdan yomonroq.
    ("mijoz|jahldor", ("mijoz", "oddiy")),
    ("vazifa", ("vazifa", "oddiy")),
])
def test_yorliq_oqiladi(raw, kutilgan):
    assert parse_label(raw) == kutilgan


@pytest.mark.parametrize("raw", [
    "ob-havo|oddiy",                                   # ro'yxatda yo'q mavzu
    "Mahmud bu oyda 3 marta kechikkan.",               # model JAVOB yozdi
    "kechikish|oddiy\nIzoh: savol davomat haqida",     # ko'p qator
    "",
])
def test_yaroqsiz_yorliq_rad_etiladi(raw):
    """Model ko'rsatmani buzsa - rad etiladi va zahira ishlaydi. Ro'yxatdan
    tashqari narsa HECH QACHON ovozga yo'l topmaydi."""
    assert parse_label(raw) is None


class FakeOllama:
    def __init__(self, content: str = "kechikish|oddiy") -> None:
        self.content = content
        self.calls: list[dict] = []
        self.status: int | None = None

    def __call__(self, request, timeout=None):
        self.calls.append({
            "url": request.full_url,
            "auth": request.get_header("Authorization"),
            "body": json.loads(request.data),
            "timeout": timeout,
        })
        if self.status:
            raise urllib.error.HTTPError(request.full_url, self.status, "err", {},
                                         io.BytesIO(b'{"error":"nope"}'))
        return _Resp(json.dumps({"message": {"content": self.content}}).encode())


class _Resp:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture
def classifier(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return HoldClassifier(BASE, KEY, "gemma4:31b", timeout=2.0), fake


def test_tasnif_qaytadi(classifier):
    c, fake = classifier
    assert c.classify("mahmud bu oyda necha marta kech qoldi?") == ("kechikish", "oddiy")
    call = fake.calls[0]
    assert call["url"] == f"{BASE}/api/chat"
    assert call["auth"] == f"Bearer {KEY}"
    assert call["body"]["model"] == "gemma4:31b"
    # Tasnif - ijod emas: bir xil savolga bir xil yorliq.
    assert call["body"]["options"]["temperature"] == 0.0
    # Qat'iy chegara: model gap yozishga kirishsa ham tez to'xtaydi.
    assert call["body"]["options"]["num_predict"] <= 16


def test_promptda_hamma_yorliqlar_bor(classifier):
    c, fake = classifier
    c.classify("savol")
    system = fake.calls[0]["body"]["messages"][0]["content"]
    for yorliq in list(MAVZULAR) + list(OHANGLAR):
        assert yorliq in system, yorliq
    assert "JAVOB BERMAYSAN" in system


def test_model_javob_yozsa_none(classifier):
    c, fake = classifier
    fake.content = "Mahmud bu oyda 3 marta kechikkan."
    assert c.classify("kim kechikdi?") is None


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_xizmat_xatosi_jim_otadi(classifier, status):
    c, fake = classifier
    fake.status = status
    assert c.classify("savol") is None


def test_sozlanmagan_bolsa_tarmoqqa_chiqmaydi(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    c = HoldClassifier(BASE, "", "gemma4:31b")
    assert c.configured is False
    assert c.classify("savol") is None
    assert not fake.calls


def test_savol_qisqartiriladi(classifier):
    c, fake = classifier
    c.classify("x" * 5000)
    assert len(fake.calls[0]["body"]["messages"][1]["content"]) <= 400


def test_kalit_jurnalga_tushmaydi(classifier, caplog):
    c, fake = classifier
    fake.status = 401
    with caplog.at_level(logging.DEBUG):
        c.classify("savol")
    assert KEY not in "\n".join(r.getMessage() for r in caplog.records)


# ====================================================== zahira: kalit so'zlar


@pytest.mark.parametrize("savol,mavzu", [
    ("mahmud bu oyda necha marta kech qoldi", "kechikish"),
    ("dekret ta'tili necha kun", "tatil"),
    ("DVSIB bo'yicha nima qoida bor", "hujjat"),
    ("Alisher Nazarovning mijozlari qanchta", "mijoz"),
    ("mening tasklarim qanday", "vazifa"),
    ("sentyabr hisobotini chiqar", "hisobot"),
    ("bugun havo qanday", "umumiy"),
])
def test_jadval_mavzuni_topadi(savol, mavzu):
    assert keyword_topic(savol) == mavzu


# ========================================================================= reja


class FakeClassifier:
    def __init__(self, natija=("kechikish", "shoshilinch"), kechikish=0.0):
        self.natija = natija
        self.kechikish = kechikish
        self.configured = True
        self.calls = 0

    def classify(self, question):
        self.calls += 1
        if self.kechikish:
            time.sleep(self.kechikish)
        return self.natija


def _hamma_ovoz_tayyor(module, tmp_path):
    """Test uchun barcha ovozlarni "tayyor" qiladi (haqiqiy TTS siz)."""
    voices = HoldVoices(tmp_path / "hold-tayyor")
    voices.cache_dir.mkdir(parents=True, exist_ok=True)
    for kalit, _ in all_clips():
        (voices.cache_dir / f"{kalit}.wav").write_bytes(b"RIFF" + b"\0" * 40)
    module._hold_voices = voices
    return voices


@pytest.fixture
def chat(monkeypatch, tmp_path):
    import app.api.v1.chat as module
    from app.core.config import settings

    monkeypatch.setattr(module, "_hold_voices", module._hold_voices)
    _hamma_ovoz_tayyor(module, tmp_path)
    monkeypatch.setattr(settings, "hold_first_ms", 1200)
    monkeypatch.setattr(settings, "hold_repeat_ms", 9000)
    monkeypatch.setattr(settings, "hold_max", 4)
    return module


def _kadrlar(plan, module, frames_fn, jami=6.0):
    """Rejani haqiqiy `_with_hold` orqali yurgizadi va kadrlarni yig'adi."""
    answer = AnswerStream(request_id="r", frames=frames_fn(), outcome={})
    t0 = time.monotonic()
    out = []
    for raw in module._with_hold(answer, plan):
        out.append((round(time.monotonic() - t0, 2), json.loads(raw)))
        if time.monotonic() - t0 > jami:
            break
    return out


def test_tasnif_kelishi_bilan_birinchi_ovoz(chat, monkeypatch):
    """Birinchi ovoz TIMEOUT'ni kutmaydi - aynan tasnif tayyor bo'lgan paytda."""
    monkeypatch.setattr(chat, "_hold_classifier", FakeClassifier(kechikish=0.1))

    def sekin():
        time.sleep(0.6)
        yield b'{"type":"token","text":"Javob"}\n'
        yield b'{"type":"done","route":"hrm"}\n'

    plan = chat._HoldPlan("TEZDA AYT! kim kech qoldi", "uz")
    kadrlar = _kadrlar(plan, chat, sekin)
    holds = [(t, k) for t, k in kadrlar if k["type"] == "hold"]
    assert holds, kadrlar
    t, hold = holds[0]
    assert t < 0.5, f"tasnifni emas, timeout'ni kutdi: {t}s"
    assert hold["topic"] == "kechikish" and hold["source"] == "ollama"
    assert hold["clip"].startswith("kechikish-shoshilinch-ilk-")
    # Ovoz javobdan OLDIN keladi.
    turlar = [k["type"] for _, k in kadrlar]
    assert turlar.index("hold") < turlar.index("token")


def test_model_ulgurmasa_jadval_tanlaydi(chat, monkeypatch):
    """Kutish ovozining ma'nosi TEZ tan olishda. Model kechiksa - jadval."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "hold_first_ms", 150)
    monkeypatch.setattr(chat, "_hold_classifier", FakeClassifier(kechikish=2.0))

    def sekin():
        time.sleep(0.5)
        yield b'{"type":"token","text":"Javob"}\n'
        yield b'{"type":"done","route":"rules"}\n'

    plan = chat._HoldPlan("dekret ta'tili qanday hisoblanadi", "uz")
    holds = [k for _, k in _kadrlar(plan, chat, sekin) if k["type"] == "hold"]
    assert holds and holds[0]["source"] == "jadval"
    assert holds[0]["topic"] == "tatil"


def test_jadval_ohangni_doim_oddiy_qiladi(chat, monkeypatch):
    """O'LCHANGAN: jadval ohangni xavfli tomonga yanglishadi - "hozir kim
    ishda yo'q" va "DVSIB" (bosh harflar) "shoshilinch" deb o'qilgan.
    Shoshilmagan odamga qo'pol gapirish - eng yomon xato."""
    monkeypatch.setattr(chat, "_hold_classifier", FakeClassifier(natija=None))
    plan = chat._HoldPlan("TEZDA AYT! kim kech qoldi", "uz")
    plan._model_done.set()
    hold = json.loads(plan.fire())
    assert "-oddiy-" in hold["clip"], hold["clip"]


def test_kech_kelgan_yorliq_keyingi_ovozlarni_yaxshilaydi(chat, monkeypatch):
    fake = FakeClassifier(natija=("hujjat", "oddiy"))
    monkeypatch.setattr(chat, "_hold_classifier", fake)
    plan = chat._HoldPlan("nimadir haqida savol", "uz")
    birinchi = json.loads(plan.fire())                     # model hali yo'q
    assert birinchi["source"] == "jadval"
    plan.start()
    plan._model_done.wait(2)
    ikkinchi = json.loads(plan.fire())
    assert ikkinchi["source"] == "ollama" and ikkinchi["topic"] == "hujjat"


def test_token_kelsa_toxtaydi(chat):
    plan = chat._HoldPlan("savol", "uz")
    plan.saw(b'{"type":"token","text":"Ja"}\n')
    assert plan.next_wait() is None
    assert plan.fire() is None


def test_eng_kopi_hold_max(chat, monkeypatch):
    """Cheksiz gapirish suhbat emas, shovqin."""
    plan = chat._HoldPlan("savol", "uz")
    plan._model_done.set()
    kadrlar = [plan.fire() for _ in range(10)]
    assert sum(1 for k in kadrlar if k) == 4


def test_ovozi_yoq_gap_aytilmaydi_va_osilmaydi(chat, monkeypatch, tmp_path):
    """Ovozi yo'q gap AYTILMAYDI (klientda sintez 1.1 s qo'shardi), lekin
    hisobga kiradi - aks holda `next_wait` 0 qaytarib halqa aylanib qolardi."""
    chat._hold_voices = HoldVoices(tmp_path / "bosh")
    plan = chat._HoldPlan("savol", "uz")
    plan._model_done.set()
    assert plan.fire() is None
    assert plan.fired == 1
    assert plan.next_wait() > 1.0


def test_davom_ovozlari_takrorlanmaydi(chat):
    plan = chat._HoldPlan("savol", "uz")
    plan._model_done.set()
    kliplar = [json.loads(plan.fire())["clip"] for _ in range(4)]
    assert len(set(kliplar)) == 4, kliplar


# ===================================================================== endpoint


def _fake_assistant(monkeypatch, frames):
    import app.api.v1.chat as module

    class Fake:
        def stream(self, *a, **kw):
            return AnswerStream(request_id="req-1", frames=frames, outcome={})

    monkeypatch.setattr(module, "_assistant", Fake())
    return module


def test_ovozli_rejimda_kutish_ovozi_keladi(client, auth, monkeypatch, tmp_path):
    module = _fake_assistant(monkeypatch, None)
    _hamma_ovoz_tayyor(module, tmp_path)
    monkeypatch.setattr(module, "_hold_classifier", FakeClassifier())

    def sekin():
        time.sleep(0.4)
        yield b'{"type":"token","text":"Javob"}\n'
        yield b'{"type":"done","route":"hrm"}\n'

    _fake_assistant(monkeypatch, sekin())
    response = client.post("/api/v1/chat/stream",
                           json={"question": "kim kechikdi?", "voice": True, "locale": "uz"},
                           headers=auth)
    kadrlar = [json.loads(q) for q in response.text.splitlines() if q.strip()]
    turlar = [k["type"] for k in kadrlar]
    assert "hold" in turlar, turlar
    assert turlar.index("hold") < turlar.index("token")
    hold = kadrlar[turlar.index("hold")]
    assert hold["clip"] and hold["text"] and hold["topic"] == "kechikish"


def test_matnli_rejimda_ovoz_ham_tasnif_ham_yoq(client, auth, monkeypatch):
    """Matnli chatda kutish ko'rinib turadi - ovoz shovqin, tasnif esa pul."""
    fake = FakeClassifier()
    module = _fake_assistant(monkeypatch, iter([
        b'{"type":"token","text":"Javob"}\n', b'{"type":"done","route":"hrm"}\n']))
    monkeypatch.setattr(module, "_hold_classifier", fake)
    response = client.post("/api/v1/chat/stream", json={"question": "kim kechikdi?"},
                           headers=auth)
    assert '"type":"hold"' not in response.text
    assert fake.calls == 0


@pytest.mark.parametrize("locale", ["ru", "en"])
def test_ozbekchadan_boshqa_tilda_tasnif_chaqirilmaydi(client, auth, monkeypatch, locale):
    """TTS faqat o'zbekcha - ovoz bo'lmaydi, ya'ni tasnif puli bekor ketardi."""
    fake = FakeClassifier()
    module = _fake_assistant(monkeypatch, iter([b'{"type":"done","route":"hrm"}\n']))
    monkeypatch.setattr(module, "_hold_classifier", fake)
    client.post("/api/v1/chat/stream",
                json={"question": "savol", "voice": True, "locale": locale}, headers=auth)
    assert fake.calls == 0


def test_javob_tasnifdan_oldin_kelsa_ovoz_yoq(client, auth, monkeypatch, tmp_path):
    """`clarify` 0.2 sekundda qaytadi. Javob allaqachon kelgan bo'lsa,
    "tekshirayapman" deyish - ma'nosiz."""
    module = _fake_assistant(monkeypatch, iter([
        b'{"type":"token","text":"Qaysi oy?"}\n', b'{"type":"done","route":"clarify"}\n']))
    _hamma_ovoz_tayyor(module, tmp_path)
    monkeypatch.setattr(module, "_hold_classifier", FakeClassifier(kechikish=0.3))
    response = client.post("/api/v1/chat/stream",
                           json={"question": "kech qoldimi?", "voice": True, "locale": "uz"},
                           headers=auth)
    assert '"type":"hold"' not in response.text


# ============================================================== tayyor ovozlar


def test_ovoz_yoli_tokensiz_rad_etiladi(client):
    assert client.get(f"/api/v1/tts/hold/{all_clips()[0][0]}.wav").status_code == 401


def test_tayyor_bolmagan_ovoz_404(client, auth):
    assert client.get(f"/api/v1/tts/hold/{all_clips()[0][0]}.wav",
                      headers=auth).status_code == 404


def test_ovoz_keshdan_beriladi(client, auth, tmp_path):
    import app.api.v1.chat as module

    _hamma_ovoz_tayyor(module, tmp_path)
    kalit = all_clips()[0][0]
    response = client.get(f"/api/v1/tts/hold/{kalit}.wav", headers=auth)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert "immutable" in response.headers.get("cache-control", "")


def test_ovoz_nomi_tekshiriladi(client, auth):
    """Yo'l nomidan fayl tizimiga chiqib bo'lmasligi kerak."""
    for yomon in ("..%2F..%2Fetc%2Fpasswd", "a.b", "UMUMIY", "a" * 200):
        r = client.get(f"/api/v1/tts/hold/{yomon}.wav", headers=auth)
        assert r.status_code in (404, 422), f"{yomon} -> {r.status_code}"


def test_qizdirish_yasaydi_va_eskisini_tozalaydi(tmp_path):
    voices = HoldVoices(tmp_path)
    (tmp_path / "eski-gap-0-deadbeef.wav").write_bytes(b"RIFF")
    kliplar = all_clips()[:3]
    voices.warm(kliplar, lambda text: b"RIFF" + text.encode()[:8])
    assert voices.snapshot(kliplar) == {"tayyor": 3, "jami": 3}
    # Matn o'zgarganda kalit o'zgaradi, ya'ni eski fayl endi hech qachon
    # ishlatilmaydi - u qolib ketmasligi kerak.
    assert not (tmp_path / "eski-gap-0-deadbeef.wav").exists()


def test_qizdirish_tts_yiqilsa_yiqilmaydi(tmp_path):
    voices = HoldVoices(tmp_path)

    def yiqilgan(text):
        raise RuntimeError("TTS o'chgan")

    kliplar = all_clips()[:2]
    voices.warm(kliplar, yiqilgan)
    assert voices.snapshot(kliplar)["tayyor"] == 0


def test_tasnif_ulanishdan_oldin_boshlanadi(client, auth, monkeypatch, tmp_path):
    """O'LCHANGAN: yuqoridagi xizmat ulanishni ochguncha 0-2 sekund o'tadi.
    Tasnif oqim ICHIDA boshlanganda birinchi ovoz klientda 2.86 s da
    eshitildi, holbuki tasnifning o'zi 0.8 s. Tasnif ulanish bilan PARALLEL
    ketishi kerak."""
    import app.api.v1.chat as module

    _hamma_ovoz_tayyor(module, tmp_path)
    tartib: list[str] = []

    class Classifier(FakeClassifier):
        def classify(self, question):
            tartib.append("tasnif")
            return super().classify(question)

    class Assistant:
        def stream(self, *a, **kw):
            time.sleep(0.3)                 # ulanish ochilishi
            tartib.append("ulanish")

            def frames():
                time.sleep(0.3)
                yield b'{"type":"token","text":"Javob"}\n'
                yield b'{"type":"done","route":"hrm"}\n'

            return AnswerStream(request_id="r", frames=frames(), outcome={})

    monkeypatch.setattr(module, "_hold_classifier", Classifier())
    monkeypatch.setattr(module, "_assistant", Assistant())
    response = client.post("/api/v1/chat/stream",
                           json={"question": "kim kechikdi?", "voice": True, "locale": "uz"},
                           headers=auth)
    assert tartib[0] == "tasnif", tartib
    # Tasnif ulanish paytida tayyor bo'lgan - ovoz oqimning BIRINCHI kadri.
    birinchi = json.loads(response.text.splitlines()[0])
    assert birinchi["type"] == "hold", birinchi


# ================================================== tanlangan ovozdagi kutish ovozi
#
# Mobil ilovada odam ovozni tanlaydi (ayol/erkak). Ishga tushishda faqat
# asosiy ovoz qizdiriladi; boshqasi birinchi so'rovda yasalib keshlanadi.


@pytest.fixture
def ovozlar(monkeypatch, tmp_path):
    """Kutish ovozlari papkasi vaqtinchalik, TTS - soxta transport ustida."""
    import app.api.v1.tts as module
    from app.core.config import settings
    from app.services.tts import TtsClient
    from test_tts import FakeServer

    fake = FakeServer()

    class Opener:
        def open(self, request, timeout=None):
            return fake.open(request, timeout)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: Opener())
    monkeypatch.setattr(settings, "hold_voice_dir", tmp_path / "hold")
    monkeypatch.setattr(settings, "tts_voice", "uz_female_calm")
    monkeypatch.setattr(module, "_client",
                        TtsClient("http://tts", "frontend", "s3cret", queue_wait=0.05))
    return fake


def _sintezlar(fake) -> list[dict]:
    return [c[1] for c in fake.calls if c[0] == "/api/v1/tts/stream"]


def _boshqa_ovoz(client, auth, kalit, ovoz="uz_male_news"):
    return client.get(f"/api/v1/tts/hold/{kalit}.wav", params={"voice": ovoz}, headers=auth)


def test_hold_boshqa_ovoz_birinchi_sorovda_sintez_qilinadi_keyin_keshdan(
        client, auth, ovozlar, tmp_path):
    import app.api.v1.tts as module
    from test_tts import PCM

    kalit, matn = all_clips()[0]
    birinchi = _boshqa_ovoz(client, auth, kalit)
    assert birinchi.status_code == 200, birinchi.text
    assert birinchi.headers["content-type"] == "audio/wav"
    assert "immutable" in birinchi.headers["cache-control"]
    with wave.open(io.BytesIO(birinchi.content)) as w:
        assert w.readframes(w.getnframes()) == PCM * 3
    sintez = _sintezlar(ovozlar)
    assert len(sintez) == 1
    assert sintez[0]["voice_profile"] == "uz_male_news"
    # Matn kalitdan olinadi (URL dan emas) - va `for_speech` dan o'tadi.
    assert sintez[0]["text"].rstrip(".") in matn
    assert (tmp_path / "hold" / "uz_male_news" / f"{kalit}.wav").read_bytes() == birinchi.content

    ikkinchi = _boshqa_ovoz(client, auth, kalit)
    assert ikkinchi.status_code == 200 and ikkinchi.content == birinchi.content
    assert len(_sintezlar(ovozlar)) == 1, "keshdagi ovoz qayta sintez qilindi"

    # Xizmat qayta ishga tushdi (xotira bo'sh) - ovoz DISKDAN, sintezsiz.
    module._voice_caches.clear()
    uchinchi = _boshqa_ovoz(client, auth, kalit)
    assert uchinchi.status_code == 200 and uchinchi.content == birinchi.content
    assert len(_sintezlar(ovozlar)) == 1


def test_hold_default_ovoz_ozgarmagan(client, auth, ovozlar, tmp_path, monkeypatch):
    """`?voice=<asosiy>` - AYNAN avvalgi yo'l: tayyor bo'lmasa 404, sintez YO'Q
    (asosiy ovozni ishga tushishdagi qizdirish yasaydi)."""
    import app.api.v1.chat as chat_module

    kalit = all_clips()[0][0]
    monkeypatch.setattr(chat_module, "_hold_voices", HoldVoices(tmp_path / "asosiy-bosh"))
    for params in ({}, {"voice": "uz_female_calm"}):
        r = client.get(f"/api/v1/tts/hold/{kalit}.wav", params=params, headers=auth)
        assert r.status_code == 404, params
    assert not ovozlar.calls, "asosiy ovoz so'rov ichida sintez qilindi"

    tayyor = _hamma_ovoz_tayyor(chat_module, tmp_path)
    javoblar = [client.get(f"/api/v1/tts/hold/{kalit}.wav", params=params, headers=auth)
                for params in ({}, {"voice": "uz_female_calm"})]
    assert [r.status_code for r in javoblar] == [200, 200]
    assert javoblar[0].content == javoblar[1].content == tayyor.get(kalit)
    assert javoblar[0].headers["cache-control"] == javoblar[1].headers["cache-control"]
    assert not ovozlar.calls


def test_hold_nomalum_kalit_404(client, auth, ovozlar):
    """Noma'lum kalit sintezga BORMAYDI: aks holda URL orqali TTS ga
    ixtiyoriy so'rov yuborib bo'lardi."""
    r = _boshqa_ovoz(client, auth, "umumiy-oddiy-ilk-0-00000000")
    assert r.status_code == 404
    assert not ovozlar.calls


def test_hold_tts_yiqilsa_404(client, auth, ovozlar, tmp_path):
    """Kutish ovozi - xushmuomalalik: TTS yiqilsa klient uni jimgina o'tkazib
    yuboradi. 502 emas, 404 - xuddi "hali tayyor emas" kabi."""
    ovozlar.stream_status = 500
    kalit = all_clips()[0][0]
    r = _boshqa_ovoz(client, auth, kalit)
    assert r.status_code == 404
    assert r.json()["message"] == "Bu ovoz hali tayyor emas"
    assert not (tmp_path / "hold" / "uz_male_news" / f"{kalit}.wav").exists()
    # Keyingi so'rov qayta urinadi (xato keshlanmaydi).
    ovozlar.stream_status = None
    assert _boshqa_ovoz(client, auth, kalit).status_code == 200


def test_hold_sirsiz_404_sintezsiz(client, auth, ovozlar, monkeypatch):
    import app.api.v1.tts as module
    from app.services.tts import TtsClient

    monkeypatch.setattr(module, "_client", TtsClient("http://tts", "frontend", ""))
    r = _boshqa_ovoz(client, auth, all_clips()[0][0])
    assert r.status_code == 404
    assert not ovozlar.calls


@pytest.mark.parametrize("ovoz", ["bosqa", "uz_male_news/../x", "UZ_MALE_NEWS"])
def test_hold_notogri_ovoz_422(client, auth, ovozlar, ovoz):
    """Ovoz nomi papka yo'liga tushadi - faqat ikki ma'lum qiymat."""
    r = _boshqa_ovoz(client, auth, all_clips()[0][0], ovoz=ovoz)
    assert r.status_code == 422
    assert not ovozlar.calls


def test_hold_boshqa_ovoz_tokensiz_401(client, ovozlar):
    r = client.get(f"/api/v1/tts/hold/{all_clips()[0][0]}.wav", params={"voice": "uz_male_news"})
    assert r.status_code == 401
    assert not ovozlar.calls


def test_hold_boshqa_ovoz_eskisini_tozalaydi(client, auth, ovozlar, tmp_path):
    """Gap matni o'zgarsa kaliti o'zgaradi - eski fayl hech qachon
    ishlatilmaydi va qolib ketmasligi kerak (`warm` dagi kabi)."""
    papka = tmp_path / "hold" / "uz_male_news"
    papka.mkdir(parents=True)
    (papka / "eski-gap-0-deadbeef.wav").write_bytes(b"RIFF")
    assert _boshqa_ovoz(client, auth, all_clips()[0][0]).status_code == 200
    assert not (papka / "eski-gap-0-deadbeef.wav").exists()


def test_hold_bir_vaqtdagi_sorovlar_bitta_sintez(ovozlar):
    """Ikki odam bir vaqtda so'rasa ham bitta sintez: umumiy ikki TTS sloti
    bir xil ish bilan band bo'lmasin."""
    import threading

    import app.api.v1.tts as module

    real = ovozlar.open

    def sekin(request, timeout=None):
        if request.full_url.endswith("/tts/stream"):
            time.sleep(0.2)
        return real(request, timeout)

    ovozlar.open = sekin                         # type: ignore[method-assign]
    kalit = all_clips()[0][0]
    natijalar: list[bytes | None] = []
    iplar = [threading.Thread(target=lambda: natijalar.append(
        module._hold_in_voice(kalit, "uz_male_news"))) for _ in range(3)]
    for ip in iplar:
        ip.start()
    for ip in iplar:
        ip.join(5)
    assert len(natijalar) == 3 and all(natijalar)
    assert len(set(natijalar)) == 1
    assert len(_sintezlar(ovozlar)) == 1


def test_hold_boshqa_ovoz_hisobda_hold(client, auth, ovozlar, _isolated_analytics):
    """Admin tahlilida talab bo'yicha yasalgan kutish ovozi javob
    bo'laklaridan ajralib ko'rinsin."""
    from app.services import analytics

    assert _boshqa_ovoz(client, auth, all_clips()[0][0]).status_code == 200
    assert analytics.flush(5.0)
    ops = [r["op"] for r in _isolated_analytics.rows(
        "SELECT op FROM api_calls WHERE service='tts' AND op != 'token'")]
    assert ops == ["hold"]


def test_put_atomar_va_xotirada(tmp_path):
    voices = HoldVoices(tmp_path / "yangi" / "papka")
    assert voices.put("a-b-c-0-12345678", b"RIFFdata") is True
    assert (voices.cache_dir / "a-b-c-0-12345678.wav").read_bytes() == b"RIFFdata"
    assert not list(voices.cache_dir.glob("*.part")), ".part qolib ketdi"
    assert voices.get("a-b-c-0-12345678") == b"RIFFdata"


def test_put_disk_xatosida_false_va_xotiraga_yozmaydi(tmp_path):
    """`warm` dagi avvalgi tartib: diskka tushmagan ovoz `ready` emas."""
    fayl = tmp_path / "papka-emas"
    fayl.write_bytes(b"x")
    voices = HoldVoices(fayl)
    assert voices.put("a-b-c-0-12345678", b"RIFF") is False
    assert not voices.ready("a-b-c-0-12345678")


def test_hold_boshqa_ovoz_eskirgan_fayl_berilmaydi(client, auth, ovozlar, tmp_path):
    """Diskda qolgan, lekin endi ro'yxatda yo'q kalit - eskirgan gapning ovozi."""
    papka = tmp_path / "hold" / "uz_male_news"
    papka.mkdir(parents=True)
    (papka / "umumiy-oddiy-ilk-0-00000000.wav").write_bytes(b"RIFF")
    assert _boshqa_ovoz(client, auth, "umumiy-oddiy-ilk-0-00000000").status_code == 404
    assert not ovozlar.calls

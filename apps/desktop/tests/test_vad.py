"""EnergyVad - adaptiv shovqin poli, gisterezis va hangover.

Bu testlar `wav.rms_level` ni VAD sifatida ishlatib bo'lmasligining uchta
sababini qo'riqlaydi: qattiq chegara (adaptivlik), chegara atrofidagi titrash
(gisterezis) va so'z ichidagi pauzada uzilish (hangover).

Signal SUN'IY, lekin soxta emas: har segment o'lchangan RMS darajasi bilan
quriladi (fon shovqini + sinus), shuning uchun hodisa QAYSI freymda kelishini
oldindan hisoblab, aynan shu freymni tekshirish mumkin.
"""

import math

import numpy as np
import pytest

from venera.audio.vad import (
    FORCED_CUTS_BEFORE_RECALIBRATE,
    SPEECH_ABS_MIN, THRESHOLD_OFF, THRESHOLD_ON, WARMUP_SECONDS, EnergyVad, VadEvent,
)

RATE = 16000
FRAME = 512
FDUR = FRAME / RATE          # 0.032 s
MIN_SPEECH = 0.25
MIN_SILENCE = 0.50

#: Tinch xona: ~-52 dBFS. Isitish uchun 80 freym = 2.56 s (WARMUP dan uzun).
QUIET = 0.0025
LEAD = 80
#: Nutq o'rnidagi sinus.
SPEECH = 0.12


def frames_for(seconds: float) -> int:
    """Shuncha davomiylik uchun kerakli TO'LIQ freymlar soni."""
    return math.ceil(seconds / FDUR)


def make(rng, plan) -> np.ndarray:
    """plan: [(freymlar soni, sinus_rms|None, shovqin_rms), ...] -> int16 PCM.

    Sinus fazasi segmentlar orasida uzluksiz - segment chegarasida sun'iy
    "chert" paydo bo'lib, VAD ni bejiz uyg'otmasligi uchun.
    """
    blocks = []
    pos = 0
    for count, tone_rms, noise_rms in plan:
        size = count * FRAME
        block = rng.normal(0.0, noise_rms * 32768.0, size) if noise_rms else np.zeros(size)
        if tone_rms:
            t = np.arange(pos, pos + size, dtype=np.float64) / RATE
            block = block + np.sin(2 * np.pi * 220.0 * t) * (tone_rms * 32768.0 * math.sqrt(2.0))
        blocks.append(block)
        pos += size
    return np.clip(np.concatenate(blocks), -32768, 32767).astype(np.int16)


def run(vad, pcm, offset: int = 0):
    """[(freym indeksi, hodisa), ...] - faqat NONE bo'lmaganlari."""
    events = []
    for i in range(pcm.size // FRAME):
        event = vad.process(pcm[i * FRAME:(i + 1) * FRAME])
        if event is not VadEvent.NONE:
            events.append((offset + i, event))
    return events


@pytest.fixture
def rng():
    return np.random.default_rng(20250907)


@pytest.fixture
def vad():
    return EnergyVad(sample_rate=RATE, frame_size=FRAME,
                     min_speech=MIN_SPEECH, min_silence=MIN_SILENCE, max_speech=10.0)


def test_hodisa_qiymatlari_shartnomaga_mos():
    assert VadEvent.NONE == "none"
    assert VadEvent.SPEECH_START == "speech_start"
    assert VadEvent.SPEECH_END == "speech_end"


def test_nutq_boshi_va_oxiri_freym_aniqligida(rng, vad):
    speech, tail = 50, 60
    pcm = make(rng, [(LEAD, None, QUIET), (speech, SPEECH, QUIET), (tail, None, QUIET)])

    events = run(vad, pcm)

    assert [event for _, event in events] == [VadEvent.SPEECH_START, VadEvent.SPEECH_END]
    # SPEECH_START tovush boshlangan freymdan min_speech keyin
    assert events[0][0] == LEAD + frames_for(MIN_SPEECH) - 1
    # SPEECH_END jimlik boshlangan freymdan min_silence keyin (hangover)
    assert events[1][0] == LEAD + speech + frames_for(MIN_SILENCE) - 1
    assert vad.speaking is False
    # Pol tinch xonaga sozlangan va nutq uni o'zi bilan olib ketmagan
    assert QUIET * 0.5 < vad.noise_floor < QUIET * 1.5


def test_qisqa_tovush_nutq_deb_hisoblanmaydi(rng, vad):
    """Yo'tal / eshik taqillashi: min_speech dan qisqa portlash."""
    burst = frames_for(MIN_SPEECH) - 1
    pcm = make(rng, [(LEAD, None, QUIET), (burst, SPEECH, QUIET), (60, None, QUIET)])

    assert run(vad, pcm) == []
    assert vad.speaking is False


def test_soz_ichidagi_pauza_uzmaydi(rng, vad):
    """ENG MUHIM: plosiv oldidagi pauza SPEECH_END bermasligi kerak."""
    first, gap, second, tail = 30, frames_for(MIN_SILENCE) - 1, 30, 60
    pcm = make(rng, [
        (LEAD, None, QUIET),
        (first, SPEECH, QUIET),
        (gap, None, QUIET),        # 0.448 s - min_silence dan qisqa
        (second, SPEECH, QUIET),
        (tail, None, QUIET),
    ])

    events = run(vad, pcm)

    assert [event for _, event in events] == [VadEvent.SPEECH_START, VadEvent.SPEECH_END]
    assert events[0][0] == LEAD + frames_for(MIN_SPEECH) - 1
    # Yakun faqat OXIRGI jimlikdan hisoblanadi - o'rtadagi pauza sanoqni
    # nolga qaytargan bo'lishi kerak.
    assert events[1][0] == LEAD + first + gap + second + frames_for(MIN_SILENCE) - 1


def test_uzun_pauza_esa_ikkiga_boladi(rng, vad):
    """Yuqoridagi test bo'sh bo'lmasin: min_silence dan uzun pauza UZADI."""
    first, gap, second = 30, frames_for(MIN_SILENCE) + 10, 30
    pcm = make(rng, [
        (LEAD, None, QUIET),
        (first, SPEECH, QUIET),
        (gap, None, QUIET),
        (second, SPEECH, QUIET),
        (60, None, QUIET),
    ])

    events = run(vad, pcm)

    assert [event for _, event in events] == [
        VadEvent.SPEECH_START, VadEvent.SPEECH_END,
        VadEvent.SPEECH_START, VadEvent.SPEECH_END,
    ]
    assert events[1][0] == LEAD + first + frames_for(MIN_SILENCE) - 1
    assert events[2][0] == LEAD + first + gap + frames_for(MIN_SPEECH) - 1


def test_gisterezis_chegara_atrofida_titratmaydi(rng, vad):
    """Pol x 2.5 - yoqish (x3.0) dan past, o'chirish (x1.8) dan yuqori."""
    lead = make(rng, [(LEAD, None, QUIET)])
    assert run(vad, lead) == []
    floor = vad.noise_floor
    assert floor * THRESHOLD_ON > SPEECH_ABS_MIN  # mutlaq chegara aralashmasin

    mid = 2.5 * floor
    # 1) Yoqish chegarasidan past daraja nutqni BOSHLAMAYDI...
    quiet_ramp = make(rng, [(40, mid, 0.0)])
    assert run(vad, quiet_ramp) == []
    assert vad.speaking is False

    # 2) ...lekin baland tovush boshlagan nutqni USHLAB turadi.
    loud = make(rng, [(20, 8.0 * floor, 0.0)])
    events = run(vad, loud)
    assert [event for _, event in events] == [VadEvent.SPEECH_START]

    sustain = make(rng, [(40, mid, 0.0)])  # 1.28 s - min_silence dan uzun
    assert run(vad, sustain) == []
    assert vad.speaking is True
    assert vad.noise_floor * THRESHOLD_OFF < mid < vad.noise_floor * THRESHOLD_ON


def test_max_speech_majburiy_yakun_beradi(rng):
    """Shovqinda qolgan mikrofon soatlab bitta "nutq" bermasligi kerak."""
    limit = 2.0
    vad = EnergyVad(sample_rate=RATE, frame_size=FRAME, min_speech=MIN_SPEECH,
                    min_silence=MIN_SILENCE, max_speech=limit)
    pcm = make(rng, [(LEAD, None, QUIET), (400, SPEECH, QUIET)])  # 12.8 s uzluksiz

    events = run(vad, pcm)

    assert events[0][1] is VadEvent.SPEECH_START
    assert events[1][1] is VadEvent.SPEECH_END
    assert events[1][0] == LEAD + frames_for(limit) - 1
    assert vad.speaking is False


def test_max_speech_uzun_nutqni_yoqotmaydi(rng):
    """AVVAL YIQILGAN: majburiy uzilishdan keyin VAD gap oxirigacha KAR bo'lardi.

    Sabab: uzilishda pol darhol qayta kalibrlanardi, ya'ni u NUTQ darajasiga
    tortilardi. Nutq davom etayotgani uchun pol o'sha yerda qotib qolardi va
    45 soniyalik diktovkadan faqat birinchi 10 soniyasi eshitilardi.

    To'g'ri xatti-harakat: uzluksiz nutq KETMA-KET segmentlarga bo'linadi.
    """
    limit = 2.0
    vad = EnergyVad(sample_rate=RATE, frame_size=FRAME, min_speech=MIN_SPEECH,
                    min_silence=MIN_SILENCE, max_speech=limit)
    # ~12.8 s uzluksiz nutq: limit 2 s bo'lgani uchun bir nechta segment kutamiz.
    events = run(vad, make(rng, [(LEAD, None, QUIET), (400, SPEECH, QUIET)]))

    starts = [i for i, e in events if e is VadEvent.SPEECH_START]
    ends = [i for i, e in events if e is VadEvent.SPEECH_END]

    # Eski xatti-harakat: AYNAN 1 ta segment, keyin gap oxirigacha jimlik.
    # Yangi: FORCED_CUTS_BEFORE_RECALIBRATE ta to'liq segment.
    assert len(starts) == FORCED_CUTS_BEFORE_RECALIBRATE, f"segmentlar: {starts}"
    assert len(ends) == len(starts), events

    # Segmentlar KETMA-KET keladi. Orasidagi bo'shliq aynan `min_speech`
    # tasdiqlash davri: SPEECH_END dan keyin yangi nutq qayta tasdiqlanishi
    # kerak. Bu audio YO'QOLGANI degani emas - iste'molchi (AudioBus) uni
    # pre-roll bilan qaytarib oladi.
    tasdiq = frames_for(MIN_SPEECH) + 1
    for boshi, oxiri in zip(starts[1:], ends[:-1]):
        assert 0 < boshi - oxiri <= tasdiq, f"segmentlar orasida bo'shliq: {events}"

    # ATAYLAB QABUL QILINGAN CHEGARA: shundan keyin pol qayta kalibrlanadi va
    # VAD jim bo'ladi. Default max_speech=10 s bilan bu 30 soniyalik uzluksiz
    # nutqni qamrab oladi - ovozli buyruq uchun ("chromeni och" ~1.5 s) bu
    # yetarlidan ko'p. Chegara shovqinda qolgan mikrofon uchun mavjud.
    assert vad.speaking is False


def test_shovqinli_xonaga_moslashadi(rng):
    """Fon 10x ko'tarilsa VAD moslashadi va doimiy "nutq" demaydi."""
    vad = EnergyVad(sample_rate=RATE, frame_size=FRAME, min_speech=MIN_SPEECH,
                    min_silence=MIN_SILENCE, max_speech=2.0)
    assert run(vad, make(rng, [(LEAD, None, QUIET)])) == []
    quiet_floor = vad.noise_floor

    loud = 700  # 22.4 s uzluksiz baland shovqin
    events = run(vad, make(rng, [(loud, None, QUIET * 10)]), offset=LEAD)

    # Sakrash paytida yolg'on ishga tushish kechiriladi: u nutq boshlanishidan
    # farq qilmaydi. Lekin pol qayta kalibrlangunga qadar ketma-ket
    # FORCED_CUTS_BEFORE_RECALIBRATE ta segmentdan ko'p bo'lmasligi va undan
    # keyin VAD BUTUNLAY jim bo'lishi kerak.
    starts = [i for i, event in events if event is VadEvent.SPEECH_START]
    assert len(starts) <= FORCED_CUTS_BEFORE_RECALIBRATE, starts
    settled = (LEAD + FORCED_CUTS_BEFORE_RECALIBRATE * frames_for(2.0)
               + frames_for(WARMUP_SECONDS) + 4)
    assert all(i < settled for i, _ in events), events
    assert vad.speaking is False
    assert vad.noise_floor > 5 * quiet_floor
    assert vad.noise_floor == pytest.approx(QUIET * 10, rel=0.4)


def test_pol_uzun_nutq_davomida_kotarilmaydi(rng):
    """ASIMMETRIYA: 10 s gap polni o'zi bilan olib ketmasligi kerak."""
    vad = EnergyVad(sample_rate=RATE, frame_size=FRAME, min_speech=MIN_SPEECH,
                    min_silence=MIN_SILENCE, max_speech=60.0)
    assert run(vad, make(rng, [(LEAD, None, QUIET)])) == []
    before = vad.noise_floor

    events = run(vad, make(rng, [(frames_for(10.0), SPEECH, QUIET)]))

    assert [event for _, event in events] == [VadEvent.SPEECH_START]
    assert vad.speaking is True
    # Pol nutq darajasiga (SPEECH = 48x pol) emas, o'z joyida qoldi.
    assert vad.noise_floor < 1.5 * before


def test_isitish_davrida_yolgon_speech_start_yoq(rng, vad):
    """Mikrofon darhol baland ochilsa ham birinchi freymlar hodisa bermaydi."""
    pcm = make(rng, [(frames_for(WARMUP_SECONDS) + 90, SPEECH, QUIET)])

    events = run(vad, pcm)

    assert events == []
    # Boshlanishdagi daraja SHOVQIN deb qabul qilindi - pol o'shanga sozlandi.
    assert vad.noise_floor == pytest.approx(SPEECH, rel=0.3)


def test_isitish_ochilish_sakrashini_yutadi(rng, vad):
    """Oqim ochilganda birinchi bloklar ko'pincha JIM keladi (qurilma hali
    ishga tushmagan), keyin xona shovqini birdan "sakrab" paydo bo'ladi.
    Isitishsiz pol shu jim bloklarga sozlanib qolardi va sakrash yolg'on
    SPEECH_START berardi - eng ko'p uchraydigan yolg'on ijobiy shu.
    """
    pcm = np.concatenate([
        np.zeros(2 * FRAME, dtype=np.int16),
        make(rng, [(120, None, QUIET)]),
    ])

    assert run(vad, pcm) == []
    assert vad.noise_floor == pytest.approx(QUIET, rel=0.3)


def test_reset_holatni_tozalaydi(rng, vad):
    pcm = make(rng, [(LEAD, None, QUIET), (30, SPEECH, QUIET)])
    assert [event for _, event in run(vad, pcm)] == [VadEvent.SPEECH_START]
    assert vad.speaking is True

    vad.reset()

    assert vad.speaking is False
    assert vad.noise_floor == 0.0
    # Isitish ham qaytadan boshlanadi
    assert run(vad, make(rng, [(frames_for(WARMUP_SECONDS) + 30, SPEECH, QUIET)])) == []


def test_bosh_va_notogri_freymlar_yiqitmaydi(vad):
    assert vad.process(np.zeros(0, dtype=np.int16)) is VadEvent.NONE
    assert vad.process(np.zeros(3, dtype=np.int16)) is VadEvent.NONE
    assert vad.process(np.full(7, 12000, dtype=np.int16)) is VadEvent.NONE
    assert vad.process(np.array([np.nan, np.inf], dtype=np.float32)) is VadEvent.NONE
    assert vad.process([0, 0, 0]) is VadEvent.NONE
    assert math.isfinite(vad.noise_floor) and vad.noise_floor >= 0.0

    # Butunlay raqamli jimlik (o'chirilgan mikrofon) hech qachon nutq emas
    assert run(vad, np.zeros(200 * FRAME, dtype=np.int16)) == []
    assert vad.speaking is False


def test_boshqa_olchamli_freym_vaqtni_ozgartirmaydi(rng, vad):
    """Freym 2x katta bo'lsa ham hodisa o'sha VAQTda kelishi kerak."""
    big = 2 * FRAME
    pcm = make(rng, [(LEAD, None, QUIET), (50, SPEECH, QUIET)])

    events = []
    for i in range(pcm.size // big):
        event = vad.process(pcm[i * big:(i + 1) * big])
        if event is not VadEvent.NONE:
            events.append((i, event))

    assert [event for _, event in events] == [VadEvent.SPEECH_START]
    onset = LEAD // 2
    assert events[0][0] == onset + math.ceil(MIN_SPEECH / (big / RATE)) - 1


# --- adversarial revyuda topilgan nuqsonlar uchun regressiya testlari --------

def test_mutedan_qaytganda_yolgon_nutq_bermaydi(rng):
    """AVVAL YIQILGAN: mikrofon mute'dan qaytganda ~10 s yolg'on "nutq".

    Sessiya o'rtasida raqamli jimlik kelsa (mute, qurilma almashishi, drayver
    nol blok berishi) pol FLOOR_MIN ga cho'kadi. Signal qaytganda chegaralangan
    ko'tarilish polga o'z joyiga qaytish uchun ~3 s beradi va shu vaqt ichida
    ODDIY XONA SHOVQINI chegaradan yuqori bo'lib qoladi -> VAD "nutq" deb
    hisoblab butun shovqinni STT ga yuboradi.
    """
    vad = EnergyVad(sample_rate=RATE, frame_size=FRAME, min_speech=MIN_SPEECH,
                    min_silence=MIN_SILENCE, max_speech=10.0)
    # Isitish + tinch shovqin: pol sozlanadi.
    run(vad, make(rng, [(LEAD, None, QUIET)]))

    # Mikrofon mute: RAQAMLI jimlik (aniq nol), 150 freym ~4.8 s.
    run(vad, np.zeros(150 * FRAME, dtype=np.int16))

    # Shovqin qaytdi - NUTQ EMAS, o'sha eski tinch fon.
    events = run(vad, make(rng, [(300, None, QUIET)]))

    starts = [e for _, e in events if e is VadEvent.SPEECH_START]
    assert starts == [], f"mute'dan qaytishda yolg'on nutq: {events}"


def test_2d_stereo_freym_vaqtni_ikki_barobar_sanamaydi(rng):
    """sounddevice (N, channels) beradi.

    `samples.size` u holda N*channels bo'lib, barcha vaqt chegaralari
    (min_speech, min_silence, max_speech) 2x buziladi.
    """
    mono = EnergyVad(sample_rate=RATE, frame_size=FRAME)
    stereo = EnergyVad(sample_rate=RATE, frame_size=FRAME)

    pcm = make(rng, [(LEAD, None, QUIET), (60, SPEECH, QUIET), (40, None, QUIET)])
    mono_events = run(mono, pcm)
    stereo_events = [
        (i, stereo.process(np.repeat(pcm[i * FRAME:(i + 1) * FRAME, None], 2, axis=1)))
        for i in range(pcm.size // FRAME)
    ]
    stereo_events = [(i, e) for i, e in stereo_events if e is not VadEvent.NONE]

    assert stereo_events == mono_events, "stereo freym mono'dan boshqacha ishlandi"


@pytest.mark.parametrize("nosoz", [None, float("nan"), "salom", 0, -1])
def test_nosoz_konstruktor_qiymati_yiqitmaydi(nosoz):
    """Qiymatlar config.yaml dan keladi - `null` va `.nan` real holat."""
    vad = EnergyVad(sample_rate=nosoz, frame_size=nosoz)
    assert vad.sample_rate == RATE and vad.frame_size == FRAME
    assert vad.process(np.zeros(FRAME, dtype=np.int16)) is VadEvent.NONE


def test_kirish_freymi_ozgartirilmaydi(rng):
    """process() freymni O'ZGARTIRMASLIGI shart - u bus'ning nusxasi."""
    vad = EnergyVad(sample_rate=RATE, frame_size=FRAME)
    frame = (rng.normal(0, SPEECH, FRAME) * 32767).astype(np.int16)
    oldin = frame.copy()
    vad.process(frame)
    assert np.array_equal(frame, oldin)

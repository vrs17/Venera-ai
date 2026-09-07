"""AudioListener - mikrofon oqimining yagona iste'molchisi.

Haqiqiy mikrofon YO'Q: `SoxtaCapture` oldindan tayyorlangan bloklarni beradi,
shuning uchun testlar deterministik. Vaqt bo'yicha yagona shart - `cancel` va
`timeout` ning DARHOL ishlashi, ular soat bilan o'lchanadi.

Signal sun'iy, lekin soxta emas: jimlik o'rnida past shovqin (mutlaq nol emas -
raqamli jimlik VAD da alohida yo'l), nutq o'rnida sinus. Nutqning ENG BIRINCHI
namunalariga takrorlanmas IMZO qo'yiladi: agar segment o'sha imzoni o'z ichiga
olsa, demak so'z boshi kesilmagan.
"""

import threading
import time

import numpy as np
import pytest

from venera.audio import listener as listener_mod
from venera.audio.listener import AudioListener
from venera.audio.wav import decode_wav

RATE = 16000
BLOCK = 512
BLOK_DUR = BLOCK / RATE          # 0.032 s

#: Nutq boshini belgilovchi imzo. Bunday ketma-ketlik jimlikda ham, sinusda
#: ham uchramaydi, shuning uchun uni baytlar ichidan izlash mumkin.
IMZO = np.array([32000, -32000, 32000, -32000, 31000, -31000, 31000, -31000],
                dtype=np.int16)
#: Pauzagacha bo'lgan audio uchun ikkinchi imzo (u segmentga TUSHMASLIGI kerak).
IMZO_2 = np.array([30000, -30000, 30000, -30000, 29000, -29000, 29000, -29000],
                  dtype=np.int16)


# --- signal yasash -----------------------------------------------------------

def jimlik(n: int, seed: int = 7) -> list[np.ndarray]:
    """Tinch xona: ~-66 dBFS shovqin. Mutlaq nol EMAS."""
    rng = np.random.default_rng(seed)
    return [rng.integers(-25, 26, size=BLOCK).astype(np.int16) for _ in range(n)]


def nutq(n: int, amplitude: int = 8000, imzo: np.ndarray | None = None) -> list[np.ndarray]:
    """Uzluksiz fazali sinus. `imzo` birinchi blok boshiga yoziladi."""
    t = np.arange(n * BLOCK) / RATE
    wave = np.rint(amplitude * np.sin(2 * np.pi * 220.0 * t)).astype(np.int16)
    blocks = [wave[i * BLOCK:(i + 1) * BLOCK].copy() for i in range(n)]
    if imzo is not None and blocks:
        blocks[0][:imzo.size] = imzo
    return blocks


def imzo_joyi(pcm: np.ndarray, imzo: np.ndarray) -> int:
    """Imzo boshlanadigan namuna indeksi, topilmasa -1."""
    pos = pcm.tobytes().find(imzo.tobytes())
    if pos < 0:
        return -1
    assert pos % 2 == 0, "imzo namuna chegarasida emas - test signali buzilgan"
    return pos // 2


# --- soxta mikrofon ----------------------------------------------------------

class SoxtaCapture:
    """`AudioCapture` ning test o'rinbosari: bloklarni ro'yxatdan beradi.

    `hold_at(i)` - i-blokdan oldin oqimni to'xtatib turadigan darvoza. U test
    va listener thread'ini sinxronlashtiradi: darvozasiz bloklar mikrosoniyada
    oqib ketardi va "chaqiruvdan OLDIN kelgan audio" holatini yasab bo'lmasdi.
    """

    def __init__(self, blocks, tail: bool = True, pace: float = 0.001) -> None:
        self._blocks = list(blocks)
        self._tail = np.random.default_rng(3).integers(
            -25, 26, size=BLOCK).astype(np.int16) if tail else None
        self._index = 0
        self._pace = pace
        self._gates: dict[int, threading.Event] = {}

        self.consumed = 0
        self.reads = 0
        self.reopens = 0
        self.running = True
        self.alive = True
        self.on_level = None

    # sinxronlash
    def hold_at(self, index: int) -> threading.Event:
        gate = threading.Event()
        self._gates[index] = gate
        return gate

    # AudioCapture shartnomasi
    def read(self, timeout: float = 0.25):
        self.reads += 1
        gate = self._gates.get(self._index)
        if gate is not None and not gate.is_set():
            gate.wait(timeout)
            return None
        if self._pace:
            time.sleep(self._pace)
        if self._index < len(self._blocks):
            block = self._blocks[self._index]
            self._index += 1
            self.consumed += 1
            return block
        if self._tail is None:
            time.sleep(min(timeout, 0.05))
            return None
        self.consumed += 1
        return self._tail

    def is_alive(self, tolerance: float = 2.0) -> bool:
        return self.alive

    def reopen(self, rescan: bool = True) -> bool:
        self.reopens += 1
        self.alive = True
        return True

    def start(self) -> bool:
        self.running = True
        return True

    def stop(self) -> None:
        self.running = False

    def drain(self) -> None:
        pass


def kut(shart, limit: float = 3.0) -> bool:
    """Shart bajarilishini kutadi (poll). Test osilib qolmasligi uchun limit bor."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if shart():
            return True
        time.sleep(0.002)
    return False


@pytest.fixture
def tinglovchi():
    """Yaratilgan listenerlarni test oxirida albatta to'xtatadi."""
    created: list[AudioListener] = []

    def make(capture, **kwargs):
        params = dict(sample_rate=RATE, frame_size=BLOCK, min_speech=0.25,
                      min_silence=0.5, max_speech=10.0, pre_roll=0.3)
        params.update(kwargs)
        obj = AudioListener(capture, **params)
        created.append(obj)
        return obj

    yield make
    for obj in created:
        obj.stop()


def kechikib(event: threading.Event, delay: float = 0.05) -> threading.Thread:
    """`delay` dan keyin event'ni qo'yadigan thread (chaqiruvchini bloklamaydi)."""
    thread = threading.Thread(target=lambda: (time.sleep(delay), event.set()),
                              daemon=True)
    thread.start()
    return thread


# --- segmentlash -------------------------------------------------------------

def test_jimlik_nutq_jimlik_segment_chegaralanadi(tinglovchi):
    """Nutq jimlik bilan o'ralganda segment aynan nutq atrofida kesiladi."""
    capture = SoxtaCapture(jimlik(50) + nutq(20, imzo=IMZO) + jimlik(40))
    obj = tinglovchi(capture)
    assert obj.start() is True

    wav = obj.capture_utterance(timeout=5.0, cancel=threading.Event())

    assert wav, "segment umuman qaytmadi"
    pcm, rate = decode_wav(wav)
    assert rate == RATE
    duration = pcm.size / RATE
    # 20 blok nutq = 0.64 s; unga pre_roll (0.3) va hangover (min_silence 0.5)
    # qo'shiladi. Yuqori chegara - butun 110 blokdan (3.5 s) sezilarli kam.
    assert 0.6 < duration < 2.5, duration
    assert imzo_joyi(pcm, IMZO) >= 0, "nutq boshi segmentga tushmadi"
    assert obj.stats["segments"] == 1


def test_pre_roll_soz_boshini_kesmaydi(tinglovchi):
    """ENG MUHIM: chaqiruvdan OLDIN aytilgan bo'g'in ham segmentga kiradi.

    Foydalanuvchi Ctrl+Alt+Space ni bosib darhol gapira boshlaydi - hotkey va
    executor kechikishi tufayli so'zning boshi `capture_utterance()` gacha
    kelib ulguradi. Bu yerda aynan shu holat yasaladi: 5 blok nutq (0.16 s)
    chaqiruvdan oldin oqadi, qolgani keyin.
    """
    blocks = jimlik(45) + nutq(25, imzo=IMZO) + jimlik(40)
    capture = SoxtaCapture(blocks, pace=0.002)
    gate = capture.hold_at(50)          # 45 jimlik + 5 blok NUTQ o'tgach to'xtaydi
    obj = tinglovchi(capture)
    assert obj.start() is True

    assert kut(lambda: capture.consumed >= 50), "darvozaga yetib borilmadi"
    assert not obj.vad.speaking, "min_speech to'lmagan - VAD hali tasdiqlamasligi kerak"

    kechikib(gate, 0.05)                # chaqiruv marker qo'ygandan keyin ochamiz
    wav = obj.capture_utterance(timeout=5.0, cancel=threading.Event())

    assert wav, "segment qaytmadi"
    pcm, _ = decode_wav(wav)
    joy = imzo_joyi(pcm, IMZO)
    # Imzo chaqiruvdan OLDIN kelgan: u faqat pre-roll (va SPEECH_START ning
    # min_speech kechikishini qoplash) tufayli segmentda bo'lishi mumkin.
    assert joy >= 0, "so'z boshi kesilib ketdi - pre-roll ishlamayapti"
    assert joy > 0, "segment aynan nutqdan boshlangan - oldindagi audio yo'q"


def test_qaytgan_bayt_haqiqiy_wav(tinglovchi):
    """STT serveri 16 kHz mono int16 RIFF kutadi - shuni qaytarayotganimizni tekshiramiz."""
    capture = SoxtaCapture(jimlik(50) + nutq(15, imzo=IMZO) + jimlik(40))
    obj = tinglovchi(capture)
    obj.start()

    wav = obj.capture_utterance(timeout=5.0, cancel=threading.Event())

    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    pcm, rate = decode_wav(wav)
    assert pcm.dtype == np.int16
    assert rate == RATE
    assert pcm.size * 2 + 44 == len(wav)


def test_max_speech_cheksiz_yozishni_to_xtatadi(tinglovchi):
    """Shovqinda qolgan mikrofon soatlab yozib, STT ga megabaytlar yubormasligi kerak."""
    capture = SoxtaCapture(jimlik(45) + nutq(300))     # 9.6 s uzluksiz tovush
    obj = tinglovchi(capture, max_speech=0.5)
    obj.start()

    wav = obj.capture_utterance(timeout=5.0, cancel=threading.Event())

    assert wav, "majburiy uzilishda ham segment qaytishi kerak"
    pcm, _ = decode_wav(wav)
    duration = pcm.size / RATE
    # max_speech (0.5) + pre_roll (0.3) + min_speech kompensatsiyasi (0.25).
    assert duration < 1.5, f"max_speech cheklamadi: {duration:.2f} s"


# --- to'xtatish yo'llari -----------------------------------------------------

def test_timeout_da_bosh_bayt_qaytadi(tinglovchi):
    """Jimlik: bloklanib qolmaydi, b"" qaytaradi."""
    capture = SoxtaCapture(jimlik(60))
    obj = tinglovchi(capture)
    obj.start()

    start = time.monotonic()
    wav = obj.capture_utterance(timeout=0.4, cancel=threading.Event())
    elapsed = time.monotonic() - start

    assert wav == b""
    assert 0.3 < elapsed < 1.5, elapsed


def test_cancel_darhol_qaytaradi(tinglovchi):
    """Bekor qilish soniyalab kutmaydi - qayta aktivatsiya shunga tayanadi."""
    capture = SoxtaCapture(jimlik(60))
    obj = tinglovchi(capture)
    obj.start()

    cancel = threading.Event()
    kechikib(cancel, 0.05)

    start = time.monotonic()
    wav = obj.capture_utterance(timeout=10.0, cancel=cancel)
    elapsed = time.monotonic() - start

    assert wav == b""
    assert elapsed < 1.0, f"cancel {elapsed:.2f} s dan keyin ishladi"


def test_oldindan_qo_yilgan_cancel_umuman_yozmaydi(tinglovchi):
    capture = SoxtaCapture(jimlik(50) + nutq(20, imzo=IMZO))
    obj = tinglovchi(capture)
    obj.start()

    cancel = threading.Event()
    cancel.set()
    assert obj.capture_utterance(timeout=5.0, cancel=cancel) == b""


def test_ishlamayotgan_listener_bloklamaydi(tinglovchi):
    """start() chaqirilmagan bo'lsa - darhol b"" (so'rovga xizmat qiluvchi yo'q)."""
    obj = tinglovchi(SoxtaCapture(jimlik(10)))

    start = time.monotonic()
    assert obj.capture_utterance(timeout=5.0, cancel=threading.Event()) == b""
    assert time.monotonic() - start < 0.5


# --- pauza / davom etish -----------------------------------------------------

def test_pause_paytida_segment_chiqmaydi(tinglovchi):
    """TTS ijrosida Venera o'z ovozini buyruq deb yozib olmasligi kerak."""
    capture = SoxtaCapture(jimlik(45) + nutq(25, imzo=IMZO) + jimlik(40))
    obj = tinglovchi(capture)
    obj.pause()
    obj.start()

    wav = obj.capture_utterance(timeout=0.5, cancel=threading.Event())

    assert wav == b""
    assert capture.consumed > 10, "pauzada bloklar baribir o'qilishi kerak (navbat to'lmasin)"
    assert obj.bus.total_samples == 0, "pauzada audio busga tushmasligi kerak"


def test_resume_tinglashni_tiklaydi_va_eski_audioni_kiritmaydi(tinglovchi):
    """resume() dan keyin nutq eshitiladi, pauzagacha bo'lgan audio esa kirmaydi."""
    oldin = jimlik(44) + nutq(1, imzo=IMZO_2)      # pauzadan avvalgi BALAND blok
    keyin = jimlik(30) + nutq(20, imzo=IMZO) + jimlik(40)
    capture = SoxtaCapture(oldin + keyin, pace=0.002)
    gate1 = capture.hold_at(45)                    # pauza uchun to'xtash
    gate2 = capture.hold_at(75)                    # resume uchun to'xtash
    obj = tinglovchi(capture)
    obj.start()

    assert kut(lambda: capture.consumed >= 45), "birinchi darvozaga yetib borilmadi"
    obj.pause()
    gate1.set()
    assert kut(lambda: capture.consumed >= 75), "ikkinchi darvozaga yetib borilmadi"

    obj.resume()
    kechikib(gate2, 0.05)
    wav = obj.capture_utterance(timeout=5.0, cancel=threading.Event())

    assert wav, "resume() dan keyin listener kar bo'lib qoldi"
    pcm, _ = decode_wav(wav)
    assert imzo_joyi(pcm, IMZO) >= 0, "resume() dan keyingi nutq yozilmadi"
    assert imzo_joyi(pcm, IMZO_2) < 0, "pre-roll pauzadan oldingi audioni tortib keldi"


# --- hayotiylik va telemetriya ----------------------------------------------

def test_stop_idempotent(tinglovchi):
    capture = SoxtaCapture(jimlik(20))
    obj = tinglovchi(capture)
    obj.start()
    assert obj.running is True

    obj.stop()
    obj.stop()          # ikkinchi marta - yiqilmasligi kerak
    assert obj.running is False


def test_start_ikki_marta_bitta_thread(tinglovchi):
    capture = SoxtaCapture(jimlik(20))
    obj = tinglovchi(capture)
    assert obj.start() is True
    thread = obj._thread
    assert obj.start() is True
    assert obj._thread is thread


def test_mikrofon_ochilmasa_start_false(tinglovchi):
    capture = SoxtaCapture(jimlik(5))
    capture.running = False
    capture.start = lambda: False
    obj = tinglovchi(capture)

    assert obj.start() is False
    assert obj.running is False
    assert obj.error


def test_olik_mikrofon_qayta_ochiladi(monkeypatch, tinglovchi):
    """Oqim o'lgan (uyqudan keyin) - listener uni o'zi tiklaydi."""
    monkeypatch.setattr(listener_mod, "REOPEN_INTERVAL", 0.05)
    capture = SoxtaCapture([], tail=False)      # audio umuman kelmaydi
    capture.alive = False
    obj = tinglovchi(capture)
    obj.start()

    assert kut(lambda: capture.reopens >= 1, limit=2.0), "reopen() chaqirilmadi"
    assert obj.stats["reopens"] >= 1


def test_on_level_capture_callbackidan_olinadi(tinglovchi):
    """Daraja LISTENER thread'idan xabar qilinadi, PortAudio callback'idan emas."""
    darajalar: list[float] = []
    threadlar: set[str] = set()

    def on_level(value: float) -> None:
        darajalar.append(value)
        threadlar.add(threading.current_thread().name)

    eski = lambda value: None
    capture = SoxtaCapture(jimlik(40) + nutq(10))
    capture.on_level = eski
    obj = tinglovchi(capture, on_level=on_level)
    obj.start()

    assert capture.on_level is None, "listener capture.on_level ni o'ziga olishi kerak"
    assert kut(lambda: len(darajalar) > 5)
    assert threadlar == {"audio-listener"}
    assert max(darajalar) > 0.0

    obj.stop()
    assert capture.on_level is eski, "stop() eski callback'ni qaytarishi kerak"


def test_stats_telemetriya(tinglovchi):
    capture = SoxtaCapture(jimlik(50) + nutq(20, imzo=IMZO) + jimlik(40))
    obj = tinglovchi(capture)
    obj.start()
    obj.capture_utterance(timeout=5.0, cancel=threading.Event())

    stats = obj.stats
    for kalit in ("dropped", "overflow", "segments", "last_level"):
        assert kalit in stats, kalit
    assert stats["segments"] == 1
    assert stats["dropped"] == 0
    assert stats["overflow"] == 0
    assert stats["last_level"] > 0.0


def test_nosoz_sozlama_yiqitmaydi(tinglovchi):
    """config.yaml da `null` / `.nan` bo'lsa ham listener ishlashi kerak."""
    capture = SoxtaCapture(jimlik(50) + nutq(20, imzo=IMZO) + jimlik(40))
    obj = tinglovchi(capture, sample_rate=None, frame_size=float("nan"),
                     pre_roll=None, min_speech=None)

    assert obj.sample_rate == RATE
    assert obj.frame_size == BLOCK
    assert obj.start() is True
    wav = obj.capture_utterance(timeout=5.0, cancel=threading.Event())
    assert wav, "default'ga tushgan sozlama bilan ham segment qaytishi kerak"

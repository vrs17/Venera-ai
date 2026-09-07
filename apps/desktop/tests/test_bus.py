"""AudioBus - fan-out va pre-roll.

Bu testlar mavjud `capture.py` dagi ikki nuqsonni qaytib kelmasligini qo'riqlaydi:
navbatdan o'qish bloklarni o'g'irlashi va `drain()` so'z boshini kesishi.
Shuning uchun har test SOXTA emas, haqiqiy namunalar bilan ishlaydi: ma'lumot
o'sib boruvchi naqsh (`ramp`), demak qaytgan massivning QAYSI qismi ekanini
aniq tekshirish mumkin.
"""

import threading

import numpy as np
import pytest

from venera.audio.bus import AudioBus

RATE = 16000


def ramp(start: int, count: int) -> np.ndarray:
    """[start, start+count) indekslarga mos takrorlanmas int16 naqsh."""
    # 30011 - tub son: 10 s bufer ichida qiymat takrorlanmaydi.
    return (np.arange(start, start + count, dtype=np.int64) % 30011).astype(np.int16)


@pytest.fixture
def bus():
    return AudioBus(sample_rate=RATE, seconds=1.0, frame_size=512)


def test_freym_olchami_va_qoldiq_saqlanadi(bus):
    bus.push(ramp(0, 700))
    got = bus.frames()
    assert len(got) == 1
    assert got[0].size == 512
    assert got[0].dtype == np.int16
    assert np.array_equal(got[0], ramp(0, 512))

    # 188 namuna qoldiq - u yo'qolmasligi, keyingi push bilan qo'shilishi kerak
    assert bus.frames() == []

    bus.push(ramp(700, 400))
    got = bus.frames()
    assert len(got) == 1
    assert np.array_equal(got[0], ramp(512, 512))
    assert bus.frames() == []


def test_turli_uzunlikdagi_pushlar(bus):
    sizes = [1, 171, 512, 5000]
    collected = []
    offset = 0
    for size in sizes:
        bus.push(ramp(offset, size))
        offset += size
        collected.extend(bus.frames())

    assert all(f.size == 512 for f in collected)
    assert len(collected) == offset // 512
    # Freymlar UZLUKSIZ va tartibda bo'lishi shart - naqsh buni ochib beradi
    assert np.array_equal(np.concatenate(collected), ramp(0, len(collected) * 512))
    assert bus.total_samples == offset


def test_bir_martalik_push_freymga_teng(bus):
    bus.push(ramp(0, 512))
    got = bus.frames()
    assert len(got) == 1 and got[0].size == 512
    assert bus.frames() == []


def test_halqa_aylanishi_eng_eskisi_yoqoladi(bus):
    cap = bus.capacity
    assert cap == RATE  # 1 s

    nbytes_before = cap * 2
    total = 3 * cap
    for i in range(0, total, 4000):
        bus.push(ramp(i, 4000))

    # Xotira O'SMAYDI
    assert bus.capacity == cap
    assert bus._ring.nbytes == nbytes_before

    assert bus.total_samples == total
    # Kursor 0 da qolgan edi, halqa ikki marta aylandi -> aniq 2*cap yo'qoldi
    assert bus.dropped == total - cap

    # Buferda faqat OXIRGI cap namuna qolgan
    assert np.array_equal(bus.snapshot(1.0), ramp(total - cap, cap))

    got = bus.frames()
    assert all(f.size == 512 for f in got)
    assert np.array_equal(np.concatenate(got), ramp(total - cap, len(got) * 512))


def test_take_since_pre_roll_soz_boshini_saqlaydi(bus):
    bus.push(ramp(0, RATE // 2))          # uyg'otgichdan oldingi audio
    marker = bus.mark()
    assert marker == RATE // 2
    bus.push(ramp(marker, 8000))          # buyruqning o'zi

    exact = bus.take_since(marker)
    assert np.array_equal(exact, ramp(marker, 8000))

    pre = bus.take_since(marker, pre_roll=0.3)
    assert pre.size == 4800 + 8000
    assert np.array_equal(pre, ramp(marker - 4800, 4800 + 8000))

    # take_since KAMAYTIRMAYDI: fan-out shu bilan ishlaydi
    assert np.array_equal(bus.take_since(marker, pre_roll=0.3), pre)


def test_take_since_pre_roll_bor_qismini_beradi(bus):
    """Bufer boshida 1 s pre-roll so'ralsa - bori qaytadi, yiqilmaydi."""
    bus.push(ramp(0, 100))
    marker = bus.mark()
    bus.push(ramp(100, 100))
    got = bus.take_since(marker, pre_roll=5.0)
    assert np.array_equal(got, ramp(0, 200))


def test_eskirgan_marker_yiqilmaydi(bus):
    """ENG NOZIK JOY: marker qo'yilgach halqa to'liq aylanib ketdi."""
    bus.push(ramp(0, RATE))
    marker = bus.mark()                   # = 16000
    for i in range(2):
        bus.push(ramp(RATE + i * RATE, RATE))

    before = bus.dropped
    got = bus.take_since(marker, pre_roll=0.5)

    assert got.size == bus.capacity                      # bor qismi
    assert np.array_equal(got, ramp(3 * RATE - RATE, RATE))
    assert bus.dropped - before == 2 * RATE - RATE       # marker'dan yo'qolgani
    # Takroriy chaqiruv ham yiqilmaydi
    assert bus.take_since(marker).size == bus.capacity


def test_snapshot_nusxa_qaytaradi(bus):
    bus.push(ramp(0, RATE))
    shot = bus.snapshot(0.5)
    assert shot.size == 8000
    assert np.array_equal(shot, ramp(RATE - 8000, 8000))

    # Halqa ustidan to'liq yozamiz - qaytarilgan massiv O'ZGARMASLIGI kerak
    keep = shot.copy()
    bus.push(np.full(2 * RATE, 123, dtype=np.int16))
    assert np.array_equal(shot, keep)
    assert shot.base is not bus._ring


def test_snapshot_buferdan_uzun_sorov(bus):
    bus.push(ramp(0, 5000))
    got = bus.snapshot(30.0)
    assert np.array_equal(got, ramp(0, 5000))
    assert bus.snapshot(0.0).size == 0
    assert bus.snapshot(-1.0).size == 0


def test_bosh_bufer_va_notogri_marker(bus):
    assert bus.frames() == []
    assert bus.total_samples == 0
    assert bus.dropped == 0
    assert bus.snapshot(1.0).size == 0
    assert bus.take_since(0).size == 0
    assert bus.take_since(0, pre_roll=1.0).size == 0

    bus.push(ramp(0, 1000))
    assert bus.take_since(10 ** 9).size == 0          # marker kelajakda
    assert bus.take_since(-500).size == 1000          # marker manfiy
    assert bus.take_since(None).size == 0             # umuman son emas

    bus.push(np.zeros(0, dtype=np.int16))             # bo'sh push
    bus.push(None)
    assert bus.total_samples == 1000


def test_int16_bolmagan_kirish_yiqitmaydi(bus):
    bus.push([1, 2, 3])
    bus.push(np.array([70000, -70000], dtype=np.int32))   # to'lib ketish
    got = bus.snapshot(1.0)
    assert got.dtype == np.int16
    assert got.tolist() == [1, 2, 3, 32767, -32768]


def test_ikki_ouvchi_bir_birini_ogirlamaydi(bus):
    """capture.read() dagi asosiy nuqson: bu yerda TAKRORLANMASLIGI kerak."""
    marker = bus.mark()
    bus.push(ramp(0, 2048))

    detektor = bus.frames()                       # wake word tinglovchisi
    yozuvchi = bus.take_since(marker)             # buyruq yozuvchisi

    assert np.array_equal(np.concatenate(detektor), ramp(0, 2048))
    assert np.array_equal(yozuvchi, ramp(0, 2048))


def test_total_samples_monoton_osadi(bus):
    oldingi = bus.total_samples
    for size in (1, 5000, 171, 40000, 512):
        bus.push(ramp(0, size))
        hozir = bus.total_samples
        assert hozir == oldingi + size            # halqadan katta push ham sanaladi
        oldingi = hozir


def test_thread_safe_push_va_take_since():
    bus = AudioBus(sample_rate=RATE, seconds=0.5, frame_size=512)
    xatolar: list[BaseException] = []
    tugadi = threading.Event()
    ITER = 1000

    def yozuvchi():
        try:
            for i in range(ITER):
                bus.push(ramp(i, 171 if i % 3 else 512))
        except BaseException as exc:  # noqa: BLE001 - testda xatoni ushlaymiz
            xatolar.append(exc)
        finally:
            tugadi.set()

    def ouvchi():
        try:
            marker = bus.mark()
            for _ in range(ITER):
                bus.take_since(marker, pre_roll=0.2)
                bus.snapshot(0.3)
                bus.frames()
                marker = bus.mark()
        except BaseException as exc:  # noqa: BLE001
            xatolar.append(exc)

    threads = [threading.Thread(target=yozuvchi), threading.Thread(target=ouvchi)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert tugadi.is_set()
    assert not any(t.is_alive() for t in threads)
    assert xatolar == []
    assert bus.total_samples == sum(171 if i % 3 else 512 for i in range(ITER))
    assert bus.capacity == RATE // 2               # xotira o'smadi


# --- adversarial revyuda topilgan nuqsonlar uchun regressiya testlari --------
# Bu bo'limdagi har bir test AVVAL yiqilgan va tuzatishdan keyin yashil bo'lgan.
# Ular yo'q bo'lsa nuqsonlar jimgina qaytib keladi.

import time  # noqa: E402


def test_float_pcm_shkalasi_saqlanadi():
    """float PCM konvensiyasi [-1.0, 1.0].

    Shkalasiz `astype(int16)` 0.8 ni 1 ga aylantiradi va bus JIMLIK uzatadi.
    sounddevice'da `dtype="float32"` keng tarqalgan, ya'ni bu nazariy holat emas.
    """
    bus = AudioBus(sample_rate=RATE, seconds=1.0)
    t = np.arange(4000) / RATE
    bus.push((np.sin(2 * np.pi * 300 * t) * 0.8).astype(np.float32))

    olingan = bus.snapshot(1.0)
    assert np.abs(olingan).max() > 20000, "float shkalasi yo'qolgan - signal nolga aylandi"
    # Nollar ulushi: buzuq holatda namunalarning ~42% i nol bo'lardi.
    assert np.count_nonzero(olingan == 0) < olingan.size * 0.1


def test_stereo_blok_kanallarni_aralashtirmaydi():
    """sounddevice (frames, channels) beradi.

    Oddiy reshape(-1) uni L,R,L,R qilib mono halqaga yozadi: natija ikki
    barobar tezlashgan shovqin va total_samples ham 2x noto'g'ri.
    """
    bus = AudioBus(sample_rate=RATE, seconds=1.0)
    chap = np.full((100, 1), 1000, dtype=np.int16)
    ong = np.full((100, 1), 3000, dtype=np.int16)
    bus.push(np.hstack([chap, ong]))

    assert bus.total_samples == 100, "kanallar namuna sifatida sanaldi"
    olingan = bus.snapshot(1.0)
    assert olingan.size == 100
    assert np.all(olingan == 2000), "kanallar o'rtachasi olinmadi"


def test_bir_kanalli_2d_blok_ham_ishlaydi():
    bus = AudioBus(sample_rate=RATE, seconds=1.0)
    bus.push(np.full((64, 1), 777, dtype=np.int16))
    assert bus.total_samples == 64
    assert np.all(bus.snapshot(1.0) == 777)


@pytest.mark.parametrize("nosoz", [None, float("inf"), float("-inf"), float("nan"), "salom"])
def test_nosoz_soniya_qiymati_yiqitmaydi(nosoz):
    """Qiymatlar config.yaml dan keladi - `null` va `.nan` real holat.

    `int(nan * rate)` -> ValueError, `int(inf * rate)` -> OverflowError:
    ikkalasi ham audio thread'ini o'ldirardi.
    """
    bus = AudioBus(sample_rate=RATE, seconds=1.0)
    bus.push(np.ones(1000, dtype=np.int16))
    marker = bus.mark()

    assert bus.take_since(marker, pre_roll=nosoz).size >= 0
    assert bus.snapshot(nosoz).size == 0


def test_take_since_takrorlanganda_dropped_shishmaydi():
    """take_since - O'QISH metodi.

    Retry/timeout yo'lida u bir xil marker bilan bir necha marta chaqiriladi.
    Har chaqiruvda yo'qotishni qayta sanasa telemetriya butunlay ishonchsiz
    bo'lib qoladi.
    """
    bus = AudioBus(sample_rate=RATE, seconds=1.0)
    bus.push(ramp(0, RATE // 2))
    marker = bus.mark()
    bus.push(ramp(RATE // 2, RATE + RATE // 2))    # halqa aylanib ketdi

    birinchi = (bus.take_since(marker), bus.dropped)[1]
    assert birinchi > 0, "eskirgan marker qayd etilmadi"
    for _ in range(4):
        bus.take_since(marker)
    assert bus.dropped == birinchi, "ayni yo'qotish qayta sanaldi"

    # Yangi yo'qotish esa BARIBIR sanalishi kerak.
    bus.push(ramp(0, RATE // 2))
    bus.take_since(marker)
    assert bus.dropped > birinchi


def test_lock_ozaro_istisnoni_taminlaydi():
    """`Lock` ni butunlay olib tashlasa ham qolgan testlar o'tadi.

    Sabab: GIL numpy slice yozuvini amalda atomik qiladi, shuning uchun
    ma'lumot buzilishini ko'rsatib bo'lmaydi. Yagona ishonchli yo'l -
    o'zaro istisnoni BEVOSITA o'lchash.
    """
    bus = AudioBus(sample_rate=RATE, seconds=1.0)
    asl = bus._write_locked
    bus._write_locked = lambda d: (time.sleep(0.20), asl(d))[1]

    boshlandi = threading.Event()

    def yozuvchi():
        boshlandi.set()
        bus.push(np.ones(10, dtype=np.int16))

    t = threading.Thread(target=yozuvchi)
    t.start()
    boshlandi.wait()
    time.sleep(0.05)                    # yozuvchi kritik seksiyada

    t0 = time.perf_counter()
    bus.total_samples                   # lock bor bo'lsa - kutadi
    kutildi = time.perf_counter() - t0
    t.join()

    assert kutildi > 0.05, "o'qish yozuv bilan bir vaqtda ketdi - lock ishlamayapti"


def test_nosoz_sozlama_ogohlantirish_bilan_tuzatiladi(caplog):
    """frame_size=0 jimgina 1 ga tushsa, keyin diagnostika qilib bo'lmaydi."""
    with caplog.at_level("WARNING"):
        bus = AudioBus(sample_rate=0, frame_size=0)
    assert bus.sample_rate == 16000 and bus.frame_size == 512
    assert any("nosoz sozlama" in r.message for r in caplog.records)

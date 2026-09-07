"""Holatli resampler - mikrofon 16 kHz bermaganda STT sifatini shu modul saqlaydi."""

import numpy as np
import pytest

from venera.audio.resample import Resampler
from venera.audio.wav import resample_linear


def _sinus(freq, rate, sekund=1.0, amp=8000.0):
    n = int(rate * sekund)
    t = np.arange(n, dtype=np.float64) / rate
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.int16)


def _spektr(pcm, rate, chekka=400):
    """Amplituda spektri. Chekkalar tashlanadi - u yerda filtr hali "ochilmagan"."""
    x = pcm[chekka:-chekka].astype(np.float64)
    oyna = np.hanning(x.size)
    # 2/sum(oyna) - Hann oynasining koherent kuchayishini qoplaydi.
    spec = np.abs(np.fft.rfft(x * oyna)) * 2.0 / oyna.sum()
    return np.fft.rfftfreq(x.size, 1.0 / rate), spec


def _amplituda(pcm, chekka=400):
    """Toza sinusning amplitudasi = RMS * sqrt(2).

    TUZOQ: buni FFT tepaligidan olish mumkin emas - ton bin markaziga tushmasa
    Hann oynasi qiymatni 15% gacha pasaytiradi (scalloping) va test resampler
    aybsiz bo'lsa ham yiqiladi.
    """
    x = pcm[chekka:-chekka].astype(np.float64)
    return float(np.sqrt(2.0) * np.sqrt(np.mean(np.square(x))))


def test_1khz_sinus_48k_dan_16k_ga_saqlanadi():
    out = Resampler(48000, 16000).process(_sinus(1000, 48000))
    assert out.dtype == np.int16

    freqs, spec = _spektr(out, 16000)
    assert abs(freqs[int(np.argmax(spec))] - 1000.0) < 20.0
    assert abs(_amplituda(out) - 8000.0) < 8000.0 * 0.01


def test_aliasing_yoq_10khz_soxta_tepalik_bermaydi():
    pcm = _sinus(10000, 48000)  # 16 kHz chiqishda 6 kHz ga aylanib qaytardi
    out = Resampler(48000, 16000).process(pcm)

    freqs, spec = _spektr(out, 16000)
    assert _amplituda(out) < 8000.0 * 0.01, "10 kHz butunlay filtrlanishi kerak edi"
    assert spec[(freqs > 5000) & (freqs < 7000)].max() < 8000.0 * 0.01

    # Aynan shu joyda chiziqli interpolyatsiya yiqiladi: 6 kHz da baland soxta ton.
    lin = resample_linear(pcm, 48000, 16000)
    lf, ls = _spektr(lin, 16000)
    assert ls[(lf > 5000) & (lf < 7000)].max() > 8000.0 * 0.3


@pytest.mark.parametrize("src", [48000, 44100, 22050, 32000])
def test_bloklarga_bolinganda_uzluksiz(src):
    """TUZOQ: faqat 48000 da sinash YETARLI EMAS.

    48000 -> 16000 da gcd = 16000, ya'ni `dst // gcd == 1` va kasr faza HAR
    DOIM nol. Shuning uchun "faza bloklar orasida saqlanadi" da'vosi bu
    tezlikda umuman sinalmaydi: `self._phase = 0` deb qo'ysa ham test o'tadi.
    44100 (gcd = 300, 160 ta faza) esa buni darhol ushlaydi.
    """
    pcm = _sinus(440, src, 0.5)

    bir_martada = Resampler(src).process(pcm)

    r = Resampler(src)
    bolaklar = [r.process(pcm[i:i + 512]) for i in range(0, pcm.size, 512)]
    ketma_ket = np.concatenate(bolaklar)

    assert ketma_ket.size == bir_martada.size
    assert np.array_equal(ketma_ket, bir_martada)

    # Blok chegarasida sakrash bo'lsa qo'shni namunalar farqi sinusning eng tik
    # joyidagidan oshib ketardi.
    farq = np.abs(np.diff(ketma_ket[400:].astype(np.int32)))
    assert farq.max() < 2.0 * np.pi * 440.0 / 16000.0 * 8000.0 * 1.1 + 2


@pytest.mark.parametrize("src", [44100, 22050])
def test_reset_kasr_fazani_ham_tozalaydi(src):
    """48000 da `_phase` doim 0 - bu tekshiruv faqat notekis nisbatda ma'noli."""
    pcm = _sinus(300, src, 0.05)
    r = Resampler(src)
    r.process(pcm[:1024])
    assert r._phase != 0, "notekis nisbatda faza nolda qolmasligi kerak"
    r.reset()
    assert np.array_equal(r.process(pcm), Resampler(src).process(pcm))


@pytest.mark.parametrize("src", [48000, 44100])
def test_drift_yoq_1000_blokdan_keyin(src):
    """Xatoni N va 2N da solishtiramiz - DOIMIY filtr kechikishi qisqaradi.

    Oddiy "kutilgandan +-0.1%" tekshiruvi 48000 da +-170 namuna beradi, ya'ni
    haqiqiy 0.05% lik drift ham bemalol o'tib ketardi.
    """
    def jami(n: int) -> float:
        r = Resampler(src)
        blok = np.zeros(512, dtype=np.int16)
        return sum(r.process(blok).size for _ in range(n))

    x1 = jami(1000) - 1000 * 512 * 16000 / src
    x2 = jami(2000) - 2000 * 512 * 16000 / src
    # Xato faqat doimiy kechikish bo'lsa N bilan O'SMAYDI.
    assert abs(x2 - x1) <= 2.0, (x1, x2)


def test_passthrough_aynan_bir_xil():
    r = Resampler(16000, 16000)
    assert r.passthrough is True

    pcm = _sinus(440, 16000, 0.1)
    out = r.process(pcm)
    assert np.array_equal(out, pcm)
    assert out is not pcm  # nusxa: chaquruvchi buferni qayta ishlatishi mumkin

    assert Resampler(48000, 16000).passthrough is False


def test_nosoz_tezlik_passthrough_ga_tushadi():
    assert Resampler(0, 16000).passthrough is True
    assert Resampler(-1).passthrough is True
    assert Resampler(None).passthrough is True  # type: ignore[arg-type]
    assert Resampler(0).process(np.arange(5, dtype=np.int16)).size == 5


def test_bosh_massiv_va_bitta_namuna_yiqitmaydi():
    r = Resampler(48000)
    assert r.process(np.zeros(0, dtype=np.int16)).size == 0

    for _ in range(500):
        out = r.process(np.array([2000], dtype=np.int16))
        assert out.dtype == np.int16
    assert r.process(np.zeros(0, dtype=np.int16)).size == 0


def test_reset_holatni_tozalaydi():
    pcm = _sinus(300, 48000, 0.05)
    r = Resampler(48000)

    birinchi = r.process(pcm)
    r.reset()
    ikkinchi = r.process(pcm)

    assert np.array_equal(birinchi, ikkinchi)
    assert np.array_equal(birinchi, Resampler(48000).process(pcm))


def test_44100_dan_16000_ga():
    pcm = _sinus(1000, 44100)
    r = Resampler(44100)
    assert r.passthrough is False

    bolaklar = [r.process(pcm[i:i + 512]) for i in range(0, pcm.size, 512)]
    out = np.concatenate(bolaklar)

    assert abs(out.size - 16000) < 16000 * 0.01
    freqs, spec = _spektr(out, 16000)
    assert abs(freqs[int(np.argmax(spec))] - 1000.0) < 20.0
    assert abs(_amplituda(out) - 8000.0) < 8000.0 * 0.01


def test_yuqoriga_namunalash_8k_dan_16k():
    out = Resampler(8000, 16000).process(_sinus(1000, 8000))
    assert abs(out.size - 16000) < 16000 * 0.01

    freqs, spec = _spektr(out, 16000)
    assert abs(freqs[int(np.argmax(spec))] - 1000.0) < 20.0
    assert abs(_amplituda(out) - 8000.0) < 8000.0 * 0.01


def test_toliq_amplitudada_tolib_ketmaydi():
    pcm = _sinus(200, 48000, 0.2, amp=32767.0)
    out = Resampler(48000).process(pcm)

    assert out.dtype == np.int16
    assert out.max() > 30000 and out.min() < -30000
    # Overflow bo'lsa +32767 -> -32768 ga o'girilib, qo'shni namunalar orasida
    # ~65000 lik sakrash paydo bo'lardi.
    assert np.abs(np.diff(out.astype(np.int32))).max() < 5000


def test_transientda_tolib_ketmaydi():
    """SOF SINUS clip'ni SINAMAYDI - FIR unda umuman oshib ketmaydi.

    `np.clip` ni olib tashlasa ham yuqoridagi test o'tadi. Haqiqiy oshib ketish
    O'TKINCHIDA (transient) bo'ladi: to'liq amplitudali qadamda Gibbs halqasi
    xom float qiymatni ~38700 ga chiqaradi va clip'siz int16 ga o'ralib ketadi.
    """
    step = np.concatenate([np.full(2400, -32768, dtype=np.int16),
                           np.full(2400, 32767, dtype=np.int16)])
    out = Resampler(48000).process(step)

    assert out.dtype == np.int16
    assert out.max() == 32767 and out.min() == -32768
    # Wraparound bo'lsa qo'shni farq 65535 ga chiqardi.
    assert np.abs(np.diff(out.astype(np.int32))).max() < 50000


def test_chiqish_uzunligi_nisbatga_mos():
    for src, dst in ((48000, 16000), (44100, 16000), (32000, 16000), (22050, 16000)):
        r = Resampler(src, dst)
        jami = sum(r.process(np.zeros(1024, dtype=np.int16)).size for _ in range(100))
        kutilgan = 100 * 1024 * dst / src
        assert abs(jami - kutilgan) <= kutilgan * 0.005, (src, dst, jami, kutilgan)

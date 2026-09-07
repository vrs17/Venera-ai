"""Mikrofon oqimi - navbat, callback va xato xabarlari.

sounddevice YO'Q muhitda ham ishlashi shart, shuning uchun PortAudio o'rniga
soxta modul qo'yiladi (`venera.audio.capture._sd`).
"""

import queue
import types

import numpy as np
import pytest

from venera.audio import capture as cap
from venera.audio.capture import AudioCapture, xato_izohi, xato_sababi


# --- soxta sounddevice -------------------------------------------------------

class SoxtaOqim:
    def __init__(self, **kw):
        self.kw = kw
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


class SoxtaSd:
    """Faqat AudioCapture ishlatadigan API."""

    def __init__(self, qollab=(48000,), xato="", qurilmalar=None, rate=48000.0):
        self.qollab = tuple(qollab)
        self.xato = xato
        self.oqimlar: list[SoxtaOqim] = []
        self.default = types.SimpleNamespace(device=(0, 1))
        if qurilmalar is None:
            qurilmalar = [{
                "name": "Soxta Mikrofon",
                "hostapi": 0,
                "max_input_channels": 1,
                "default_samplerate": rate,
            }]
        self._qurilmalar = qurilmalar

    def query_devices(self):
        return self._qurilmalar

    def query_hostapis(self):
        return [{"name": "ALSA"}]

    def InputStream(self, **kw):  # noqa: N802 - sounddevice nomi
        if kw["samplerate"] not in self.qollab:
            raise RuntimeError(self.xato or f"Invalid sample rate: {kw['samplerate']}")
        oqim = SoxtaOqim(**kw)
        self.oqimlar.append(oqim)
        return oqim


@pytest.fixture
def soxta(monkeypatch):
    def qoy(**kw):
        sd = SoxtaSd(**kw)
        monkeypatch.setattr(cap, "_sd", sd)
        return sd
    return qoy


def blok(n=512, qiymat=1000):
    return np.full(n, qiymat, dtype=np.int16)


# --- record() nuqsoni --------------------------------------------------------

def test_record_nol_soniya_navbatdagini_qaytaradi():
    """Ilgari wanted=0 bo'lgani uchun doim bo'sh massiv qaytardi (debug WAV o'lik edi)."""
    c = AudioCapture()
    c._queue.put_nowait(blok(100, 5))
    c._queue.put_nowait(blok(100, 7))

    out = c.record(0.0, drain_first=False)

    assert out.dtype == np.int16
    assert out.size == 200
    assert out[0] == 5 and out[-1] == 7


def test_record_nol_soniya_drain_first_ni_mensimaydi():
    """drain_first=True bo'lsa ham 0 soniya 'hammasini ber' degani (aks holda doim bo'sh)."""
    c = AudioCapture()
    c._queue.put_nowait(blok(64, 3))
    assert c.record(0.0).size == 64


def test_record_manfiy_soniya_ham_navbatdagini_beradi():
    c = AudioCapture()
    c._queue.put_nowait(blok(32, 9))
    assert c.record(-1.0, drain_first=False).size == 32


def test_record_bosh_navbatda_bosh_massiv():
    c = AudioCapture()
    out = c.record(0.0)
    assert out.size == 0 and out.dtype == np.int16


def test_record_musbat_soniya_kesib_beradi():
    c = AudioCapture(sample_rate=16000)
    for _ in range(3):
        c._queue.put_nowait(blok(100, 4))
    out = c.record(0.01, drain_first=False)  # 160 namuna
    assert out.size == 160


# --- navbat sig'imi ----------------------------------------------------------

def test_navbat_sigimi_48k_da_nativ_kadrlarda(soxta):
    """48 kHz da sig'im nativ bloklarda hisoblanadi - ilgari ~3x qisqarardi."""
    sd = soxta(qollab=(48000,))
    c = AudioCapture(sample_rate=16000, blocksize=512, queue_seconds=30.0)

    assert c.start() is True
    assert c.native_rate == 48000
    assert c.queue_capacity == int(30.0 * 48000 / 512)
    # Eski (noto'g'ri) hisob 16 kHz bo'yicha edi:
    assert c.queue_capacity == pytest.approx(int(30.0 * 16000 / 512) * 3, abs=2)
    assert sd.oqimlar[0].started is True
    c.stop()


def test_navbat_sigimi_16k_da_ozgarmaydi(soxta):
    soxta(qollab=(16000,), rate=16000.0)
    c = AudioCapture(sample_rate=16000, blocksize=512, queue_seconds=30.0)
    assert c.start() is True
    assert c.native_rate == 16000
    assert c.queue_capacity == int(30.0 * 16000 / 512)
    c.stop()


def test_navbat_obyekti_almashtirilmaydi(soxta):
    """Listener `_queue` ga ishora saqlaydi - obyekt bir xil qolishi shart."""
    soxta(qollab=(48000,))
    c = AudioCapture()
    oldingi = c._queue
    c.start()
    assert c._queue is oldingi
    c.stop()


def test_navbat_sigimi_hech_qachon_juda_kichik_emas():
    c = AudioCapture(blocksize=4096, queue_seconds=0.01)
    assert c.queue_capacity >= 8


# --- _callback ---------------------------------------------------------------

def test_callback_rms_hisoblamaydi():
    """RMS va on_level listener thread'ining ishi - audio callback'da bo'lmasin."""
    assert not hasattr(cap, "rms_level"), "rms_level import capture.py dan olib tashlanishi kerak"

    chaqirildi = []
    c = AudioCapture(on_level=lambda lvl: chaqirildi.append(lvl))
    c._callback(blok(512), 512, None, None)

    assert chaqirildi == []
    assert c._queue.qsize() == 1


def test_callback_on_level_none_bolsa_ham_ishlaydi():
    c = AudioCapture(on_level=None)
    c._callback(blok(512), 512, None, None)
    assert c._queue.get_nowait().size == 512


def test_callback_on_level_yiqilsa_ham_tegmaydi():
    """on_level chaqirilmagani uchun undagi xato audio yo'liga umuman ta'sir qilmaydi."""
    def portlaydi(_):
        raise RuntimeError("UI o'ldi")

    c = AudioCapture(on_level=portlaydi)
    c._callback(blok(512), 512, None, None)
    assert c._queue.qsize() == 1


def test_callback_nusxa_oladi():
    c = AudioCapture()
    manba = blok(64, 100)
    c._callback(manba, 64, None, None)
    manba[:] = 0
    assert c._queue.get_nowait()[0] == 100


def test_callback_eng_eskisini_tashlaydi():
    c = AudioCapture()
    c._queue.maxsize = 2
    for qiymat in (1, 2, 3):
        c._callback(blok(8, qiymat), 8, None, None)

    qolgan = [int(c._queue.get_nowait()[0]) for _ in range(c._queue.qsize())]
    assert qolgan == [2, 3]
    assert c.dropped_blocks == 1


def test_callback_overflow_hisoblaydi():
    c = AudioCapture()
    assert c.overflow_count == 0
    status = types.SimpleNamespace(input_overflow=True)
    c._callback(blok(8), 8, None, status)
    c._callback(blok(8), 8, None, status)
    c._callback(blok(8), 8, None, types.SimpleNamespace(input_overflow=False))
    assert c.overflow_count == 2


def test_callback_tiriklik_belgisini_yangilaydi():
    c = AudioCapture()
    assert c.seconds_since_audio() == float("inf")
    c._callback(blok(8), 8, None, None)
    assert c.seconds_since_audio() < 1.0


def test_callback_resample_qiladi(soxta):
    """Resample callback'da qoladi (iste'mol modeli o'zgarmasin) - 48->16 = 1/3."""
    soxta(qollab=(48000,))
    c = AudioCapture(sample_rate=16000, blocksize=512)
    c.start()

    jami = 0
    for _ in range(20):
        c._callback(blok(512, 500), 512, None, None)
    while c._queue.qsize():
        jami += c._queue.get_nowait().size

    assert jami == pytest.approx(20 * 512 / 3, rel=0.05)
    c.stop()


# --- xato matnlari -----------------------------------------------------------

@pytest.mark.parametrize("matn, kutilgan", [
    ("Error opening InputStream: Permission denied", "ruxsat"),
    ("Microphone access is denied by privacy settings", "ruxsat"),
    ("Error opening InputStream: Device unavailable [PaErrorCode -9985]", "band"),
    ("Device is busy", "band"),
    ("Error querying device -1: Invalid device", "yo'q"),
    ("No such device", "yo'q"),
    ("Invalid sample rate", ""),
    ("", ""),
])
def test_xato_sababi_farqlanadi(matn, kutilgan):
    assert xato_sababi(matn) == kutilgan


def test_xato_izohlari_har_xil():
    izohlar = {
        xato_izohi("Permission denied"),
        xato_izohi("Device unavailable"),
        xato_izohi("Invalid device"),
        xato_izohi("Invalid sample rate"),
    }
    assert len(izohlar) == 4


def _start_xatosi(soxta, matn) -> str:
    soxta(qollab=(), xato=matn)
    xabarlar: list[str] = []
    c = AudioCapture(on_error=xabarlar.append)
    assert c.start() is False
    assert xabarlar, "on_error chaqirilishi shart"
    return xabarlar[-1]


def test_start_ruxsat_xatosini_aytadi(soxta):
    xabar = _start_xatosi(soxta, "Error opening InputStream: Permission denied")
    assert "ruxsat" in xabar.lower()
    assert "Permission denied" in xabar, "asl PortAudio matni yo'qolmasin"


def test_start_band_xatosini_aytadi(soxta):
    xabar = _start_xatosi(soxta, "Error opening InputStream: Device unavailable")
    assert "band" in xabar.lower()


def test_start_qurilma_yoq_xatosini_aytadi(soxta):
    xabar = _start_xatosi(soxta, "Error querying device: Invalid device")
    assert "topilmadi" in xabar.lower() or "uzilgan" in xabar.lower()


def test_start_nomalum_xatoda_asl_matn_qoladi(soxta):
    xabar = _start_xatosi(soxta, "Something odd happened")
    assert "Something odd happened" in xabar


def test_start_eng_aniq_sababni_tanlaydi(monkeypatch):
    """Birinchi urinish 'invalid sample rate' bersa ham sabab keyingisidan olinadi."""
    sd = SoxtaSd(qollab=())
    xatolar = iter([
        RuntimeError("Invalid sample rate"),
        RuntimeError("Permission denied"),
        RuntimeError("Invalid sample rate"),
        RuntimeError("Invalid sample rate"),
    ])
    sd.InputStream = lambda **kw: (_ for _ in ()).throw(next(xatolar))
    monkeypatch.setattr(cap, "_sd", sd)

    xabarlar: list[str] = []
    assert AudioCapture(on_error=xabarlar.append).start() is False
    assert "ruxsat" in xabarlar[-1].lower()
    assert "Permission denied" in xabarlar[-1]


def test_start_qurilmalar_royxati_bosh(soxta):
    soxta(qurilmalar=[])
    xabarlar: list[str] = []
    c = AudioCapture(on_error=xabarlar.append)
    assert c.start() is False
    assert "topilmadi" in xabarlar[-1].lower()


def test_start_kutubxona_yoq(monkeypatch):
    monkeypatch.setattr(cap, "_sd", None)
    xabarlar: list[str] = []
    c = AudioCapture(on_error=xabarlar.append)
    assert c.start() is False
    assert "kutubxona" in xabarlar[-1].lower()


def test_on_error_yiqilsa_start_yiqilmaydi(monkeypatch):
    monkeypatch.setattr(cap, "_sd", None)

    def portlaydi(_):
        raise RuntimeError("UI o'ldi")

    assert AudioCapture(on_error=portlaydi).start() is False


# --- reopen ------------------------------------------------------------------

def test_reopen_default_rescan_qilmaydi(soxta, monkeypatch):
    """rescan_devices() global _terminate() chaqiradi va AudioPlayer ijrosini buzadi."""
    soxta(qollab=(48000,))
    chaqiruvlar = []
    monkeypatch.setattr(cap, "rescan_devices", lambda: chaqiruvlar.append(1))

    c = AudioCapture()
    assert c.start() is True
    assert c.reopen() is True
    assert chaqiruvlar == []
    c.stop()


def test_reopen_rescan_true_bolganda_skanerlaydi(soxta, monkeypatch):
    soxta(qollab=(48000,))
    chaqiruvlar = []
    monkeypatch.setattr(cap, "rescan_devices", lambda: chaqiruvlar.append(1))

    c = AudioCapture()
    c.start()
    assert c.reopen(rescan=True) is True
    assert chaqiruvlar == [1]
    c.stop()


def test_reopen_navbatni_tozalaydi(soxta):
    soxta(qollab=(48000,))
    c = AudioCapture()
    c.start()
    c._queue.put_nowait(blok(8))
    c.reopen()
    assert c._queue.qsize() == 0
    c.stop()


# --- holat -------------------------------------------------------------------

def test_native_rate_ochiq_atribut(soxta):
    """Listener freym vaqtini shu bo'yicha hisoblaydi."""
    soxta(qollab=(44100,), rate=44100.0)
    c = AudioCapture(sample_rate=16000)
    assert c.native_rate == 16000  # ochilmagunicha - taxmin
    assert c.start() is True
    assert c.native_rate == 44100
    c.stop()


def test_stop_idempotent(soxta):
    soxta(qollab=(48000,))
    c = AudioCapture()
    c.start()
    c.stop()
    c.stop()
    assert c.running is False


def test_start_ikki_marta_bir_oqim(soxta):
    sd = soxta(qollab=(48000,))
    c = AudioCapture()
    assert c.start() is True
    assert c.start() is True
    assert len(sd.oqimlar) == 1
    c.stop()


def test_is_alive_oqim_yopiq_bolsa_false():
    c = AudioCapture()
    assert c.is_alive() is False


def test_drain_va_read():
    c = AudioCapture()
    c._queue.put_nowait(blok(8))
    c.drain()
    assert c._queue.qsize() == 0
    assert c.read(timeout=0.01) is None


def test_navbat_toliq_bolsa_read_ishlaydi():
    c = AudioCapture()
    c._callback(blok(8, 42), 8, None, None)
    got = c.read(timeout=0.1)
    assert got is not None and got[0] == 42
    assert isinstance(c._queue, queue.Queue)

"""Mikrofon oqimini yutadigan YAGONA thread: bus + VAD + nutq segmenti.

Nima uchun bu modul kerak - `capture.read()` navbatdan blokni OLIB TASHLAYDI.
Agar ikki joy (doimiy tinglash va buyruq yozish) bir vaqtda `read()` chaqirsa,
bloklar ular o'rtasida TASODIFIY bo'linadi: har biri audioning taxminan yarmini
ko'radi va ikkalasi ham ishlamaydi. Shuning uchun `capture._queue` ning
iste'molchisi ROPPA-ROSA BITTA bo'lishi shart - u shu yerdagi thread.

Vazifalar taqsimoti:

    capture  ->  listener thread  ->  AudioBus (aylanma bufer, pre-roll)
                                  ->  EnergyVad (nutq chegaralari)
                                  ->  on_level (UI ko'rsatkichi)

`capture_utterance()` esa BOSHQA thread'dan (odatda `run_in_executor`)
chaqiriladi va listener thread'i bilan bitta "so'rov" obyekti orqali gaplashadi.
So'rov `_req_lock` ostida almashtiriladi, natija `threading.Event` bilan
uzatiladi - poyga yo'q, `cancel` esa `WAIT_TICK` ichida ishlaydi.

UCH NOZIK JOY, ular dizaynni belgilagan:

1. SO'Z BOSHI KESILMASLIGI. VAD `SPEECH_START` ni `min_speech` to'lgandan KEYIN
   beradi, ya'ni tovushning birinchi 0.25 soniyasi allaqachon o'tib ketgan.
   Foydalanuvchi esa Ctrl+Alt+Space ni bosib DARHOL gapira boshlaydi - hotkey
   va executor kechikishi tufayli so'zning boshi `capture_utterance()`
   chaqiruvidan ham OLDIN kelishi mumkin. Shuning uchun segment boshi uchta
   nomzodning eng ERTASI qilib olinadi:
       * chaqiruv paytidagi marker;
       * `SPEECH_START` markeri MINUS `min_speech`;
       * ularning yana `pre_roll` soniya oldi (`take_since` beradi).

2. `on_level` ENDI AUDIO CALLBACK'DAN CHAQIRILMAYDI. PortAudio callback'i
   real-time thread: u yerdagi har qanday sekin ish (UI yangilash) audioni
   uzadi. Listener `capture.on_level` ni o'ziga oladi va darajani o'z
   thread'idan xabar qiladi. `stop()` da eski qiymat qaytariladi.

3. `pause()` TTS ijrosi uchun. Dinamikdan mikrofonga qaytish (AEC yo'q)
   Venera'ning o'z ovozini "buyruq" deb yozib olardi. Pauzada bloklar
   O'QILADI (navbat to'lib ketmasligi uchun) lekin busga TUSHMAYDI. Pauzagacha
   bo'lgan audio halqada qolgani uchun `resume()` marker qo'yadi - `pre_roll`
   o'sha markerdan orqaga o'ta olmaydi va Venera'ning o'z ovozi segmentga
   kirmaydi. VAD ning shovqin poli esa SAQLANADI (`pause()` docstring'iga
   qarang) - aks holda javob beruvchi foydalanuvchi bir soniya "eshitilmasdi".
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from .bus import AudioBus
from .vad import EnergyVad, VadEvent
from .wav import encode_wav, rms_level

log = logging.getLogger(__name__)

#: Bitta `capture.read()` kutish vaqti. Kichik bo'lsa - `stop()` tez ishlaydi,
#: katta bo'lsa - bo'sh aylanishlar kamayadi.
READ_TIMEOUT = 0.25

#: Mikrofon o'lgan deb qaralganda qayta ochishlar orasidagi eng kichik oraliq.
#: Modul darajasida - testlar buni almashtira oladi.
REOPEN_INTERVAL = 2.0

#: `capture_utterance()` ning kutish qadami: `cancel` shu oraliqda seziladi.
WAIT_TICK = 0.02

#: Aylanma buferning uzunligi (soniya). Xotira = 10 s * 16 kHz * 2 bayt = 320 KB.
BUS_SECONDS = 10.0

#: `start()` thread tayyorligini shuncha kutadi.
START_TIMEOUT = 5.0


def _float(value: object, default: float) -> float:
    """config.yaml dan kelgan `null` / `.nan` / matn qiymatdan himoya."""
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _butun(value: object, default: int) -> int:
    """Musbat butun son yoki default. `int(nan)` ValueError berardi."""
    try:
        out = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return out if out > 0 else default


class _Request:
    """Bitta `capture_utterance()` chaqiruvi - ikki thread o'rtasidagi kelishuv.

    Maydonlar `AudioListener._req_lock` ostida o'zgartiriladi; `done` va
    `cancel` - `threading.Event`, ular lock talab qilmaydi.
    """

    __slots__ = ("marker", "cancel", "deadline", "started",
                 "speech_marker", "finished", "wav", "done")

    def __init__(self, marker: int, cancel: threading.Event | None, deadline: float) -> None:
        self.marker = marker
        self.cancel = cancel
        self.deadline = deadline
        self.started = False
        self.speech_marker: int | None = None
        self.finished = False
        self.wav = b""
        self.done = threading.Event()


class AudioListener:
    """Mikrofon oqimini yutadigan YAGONA thread.

    capture._queue ning yagona iste'molchisi. Har blokni busga beradi,
    VAD dan o'tkazadi va nutq segmenti tayyor bo'lganda uni qaytaradi.
    """

    def __init__(
        self,
        capture,
        sample_rate: int = 16000,
        frame_size: int = 512,
        on_level: Callable[[float], None] | None = None,
        min_speech: float = 0.25,
        min_silence: float = 0.5,
        max_speech: float = 10.0,
        pre_roll: float = 0.3,
    ) -> None:
        self.capture = capture
        self.sample_rate = _butun(sample_rate, 16000)
        self.frame_size = _butun(frame_size, 512)
        self.pre_roll = max(0.0, _float(pre_roll, 0.3))
        self._on_level = on_level

        self.bus = AudioBus(
            sample_rate=self.sample_rate,
            seconds=BUS_SECONDS,
            frame_size=self.frame_size,
        )
        # EnergyVad butun sonli sozlamalarni o'zi tozalaydi, lekin suzuvchi
        # nuqtalilarini emas: `float(None)` TypeError beradi va bu qiymatlar
        # to'g'ridan-to'g'ri config.yaml dan kelishi mumkin. Shuning uchun
        # tozalash SHU YERDA.
        self.vad = EnergyVad(
            sample_rate=self.sample_rate,
            frame_size=self.frame_size,
            min_speech=max(0.0, _float(min_speech, 0.25)),
            min_silence=max(0.0, _float(min_silence, 0.5)),
            max_speech=_float(max_speech, 10.0),
        )
        # VAD sozlamani o'zi tozalaydi (manfiy/None qiymatlar) - shuning uchun
        # "min_speech qancha orqaga qaytish kerak" ni undan o'qiymiz.
        self._min_speech_samples = int(self.vad.min_speech * self.sample_rate)
        self._pre_roll_samples = int(self.pre_roll * self.sample_rate)

        self._thread: threading.Thread | None = None
        #: Thread avlodi. `_stop` YAGONA bayroq bo'lgani uchun uni keyingi
        #: `start()` tozalashi bilan JOIN'dan omon qolgan eski thread qayta
        #: yurib ketardi - natijada `capture._queue` ning IKKITA iste'molchisi
        #: paydo bo'lardi va bloklar ular orasida tasodifiy bo'linardi
        #: (fayl boshidagi "ROPPA-ROSA BITTA" shartnomasi buziladi).
        #: Har thread o'z avlodini oladi va `self._gen` o'zgarishi bilan chiqadi.
        self._gen = 0
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._ready = threading.Event()
        self._ok = False
        self._error = ""

        self._req_lock = threading.Lock()
        self._request: _Request | None = None

        # `resume()` dan keyingi chegara: pauzagacha yozilgan audio (Venera'ning
        # o'z ovozi) yangi segmentga kirib qolmasligi uchun.
        self._resume_at = 0
        self._want_reset = False

        self._prev_on_level = None
        self._level_target: Callable[[float], None] | None = None

        self._segments = 0
        self._reopens = 0
        self._last_level = 0.0
        self._last_reopen = 0.0

    # --- holat ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and not self._stop.is_set())

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def error(self) -> str:
        return self._error

    @property
    def stats(self) -> dict:
        """Telemetriya: dropped, overflow, segments, last_level."""
        return {
            "dropped": self.bus.dropped,
            "overflow": self._overflow(),
            "segments": self._segments,
            "last_level": self._last_level,
            "reopens": self._reopens,
            "running": self.running,
            "paused": self.paused,
            "zombie": self.zombie,
        }

    @property
    def zombie(self) -> bool:
        """Eski thread join'dan omon qolganmi. Jim o'tmasligi uchun statistikada."""
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and self._stop.is_set())

    def _overflow(self) -> int:
        """capture ichidagi PortAudio overflow hisoblagichi (bo'lmasa 0)."""
        for name in ("overflow_count", "_overflow_count"):
            value = getattr(self.capture, name, None)
            if isinstance(value, int):
                return value
        return 0

    # --- boshqaruv -----------------------------------------------------------

    def start(self) -> bool:
        """Threadni ko'taradi. Bloklamaydi. Muvaffaqiyatni qaytaradi."""
        if self.running:
            return self._ok
        # Eski thread `stop()` dagi join'dan omon qolgan bo'lsa (odatda
        # PortAudio `reopen()` ichida qotib), YANGISINI ko'tarmaymiz: ikkita
        # thread bitta navbatdan o'qib, ikkalasi ham buzilgan audio olardi.
        previous = self._thread
        if previous is not None and previous.is_alive():
            self._error = "eski tinglovchi thread'i hali to'xtamadi"
            log.error("%s - qayta ishga tushirilmadi", self._error)
            return False
        self._thread = None
        self._stop.clear()
        self._ready.clear()
        self._ok = False
        self._error = ""

        # `on_level` ni O'ZIMIZGA olamiz: PortAudio callback'ida UI ishi
        # qilinmasligi kerak. Chaqiruvchi o'z callback'ini bermagan bo'lsa
        # capture'dagisini davom ettiramiz - UI ulanishi uzilib qolmasin.
        self._prev_on_level = getattr(self.capture, "on_level", None)
        self._level_target = self._on_level or self._prev_on_level
        try:
            self.capture.on_level = None
        except Exception:  # noqa: BLE001 - soxta/qattiq obyektlar uchun
            log.debug("capture.on_level o'rnatilmadi")

        self._gen += 1
        thread = threading.Thread(target=self._run, args=(self._gen,),
                                  name="audio-listener", daemon=True)
        self._thread = thread
        thread.start()
        self._ready.wait(timeout=START_TIMEOUT)
        if not self._ok:
            log.warning("AudioListener ishga tushmadi: %s", self._error or "noma'lum sabab")
        return self._ok

    def stop(self) -> None:
        """Idempotent."""
        self._stop.set()
        # Avlodni oshiramiz: keyingi `start()` dagi `_stop.clear()` endi eski
        # thread'ni tiriltira olmaydi - u sikl boshida o'z avlodi eskirganini
        # ko'rib o'zi chiqib ketadi.
        self._gen += 1
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=READ_TIMEOUT * 4 + 1.0)
        if thread is None or not thread.is_alive():
            self._thread = None
        else:
            # Havolani SAQLAYMIZ - `start()` shu orqali qayta ishga tushirishni
            # rad etadi. Uni None qilsak zombi ko'rinmas bo'lib qolardi.
            log.error("audio-listener thread'i to'xtamadi - tinglovchi qayta "
                      "ishga tushirilmaydi")

        # Kutayotgan so'rovni osilib qolishga qoldirmaymiz.
        with self._req_lock:
            request, self._request = self._request, None
        if request is not None and not request.finished:
            request.finished = True
            request.done.set()

        if self._prev_on_level is not None or getattr(self.capture, "on_level", None) is None:
            try:
                self.capture.on_level = self._prev_on_level
            except Exception:  # noqa: BLE001
                pass
        self._prev_on_level = None
        self._level_target = None
        self._ok = False

    def pause(self) -> None:
        """TTS ijrosi paytida mikrofonni "eshitmaydigan" qiladi. Idempotent.

        Bloklar baribir o'qiladi (navbat to'lib ketmasligi uchun), lekin busga
        tushmaydi - ya'ni Venera o'z ovozini buyruq deb yozib olmaydi.

        VAD holati ATAYLAB MUZLATILADI, tozalanmaydi: shovqin poli bir necha
        soniya oldin AYNI SHU xonada o'lchangan va u hali ham to'g'ri. Uni
        tashlab yuborsak `resume()` dan keyin VAD `WARMUP_SECONDS` davomida kar
        bo'lardi - aynan foydalanuvchi javob berayotgan paytda.

        Yagona istisno - pauza nutq O'RTASIDA tushsa: u holda VAD "gapiryapti"
        holatida qotib qoladi va uyg'ongach yolg'on SPEECH_END beradi. Faqat
        shu holatda qayta kalibrlaymiz.
        """
        if not self._paused.is_set():
            log.debug("AudioListener pauzada")
        self._paused.set()
        if self.vad.speaking:
            self._want_reset = True

    def resume(self) -> None:
        """Pauzadan chiqadi. Pauzagacha bo'lgan audio segmentga kirmaydi."""
        if not self._paused.is_set():
            return
        # Tartib muhim: avval chegara, keyin pauzani ochamiz - aks holda
        # listener thread'i marker qo'yilguncha bir necha blok qo'shib ulgurardi.
        self._resume_at = self.bus.mark()
        self._paused.clear()
        log.debug("AudioListener pauzadan chiqdi")

    # --- nutq segmenti -------------------------------------------------------

    def capture_utterance(self, timeout: float, cancel: threading.Event) -> bytes:
        """BLOKLOVCHI: bitta nutq segmentini yozib WAV bayt qaytaradi.

        Chaqiruvchi buni run_in_executor ichida chaqiradi.
        * pre_roll bilan: chaqiruv paytidan OLDINGI audio ham kiradi,
          shuning uchun so'z boshi kesilmaydi;
        * VAD SPEECH_END berganda to'xtaydi;
        * timeout tugasa yoki cancel qo'yilsa DARHOL to'xtaydi;
        * nutq umuman bo'lmasa b"" qaytaradi.
        """
        if not self.running:
            log.warning("capture_utterance: listener ishlamayapti")
            return b""
        if cancel is not None and cancel.is_set():
            return b""

        limit = max(0.0, _float(timeout, 0.0))
        request = _Request(
            marker=self.bus.mark(),
            cancel=cancel,
            deadline=time.monotonic() + limit,
        )
        with self._req_lock:
            # VAD allaqachon nutq holatida bo'lsa, SPEECH_START biz so'rov
            # qo'yishdan OLDIN kelgan: uni boshlangan deb qabul qilamiz, aks
            # holda SPEECH_END "bizniki emas" deb tashlanib, foydalanuvchi
            # ikkinchi marta gapirishga majbur bo'lardi.
            request.started = bool(self.vad.speaking)
            previous, self._request = self._request, request
        if previous is not None and not previous.finished:
            # Bir vaqtda ikkita so'rov bo'lishi kutilmaydi (chaqiruvchi bitta),
            # lekin eskisini osilib qolishiga qoldirmaymiz.
            previous.finished = True
            previous.done.set()

        try:
            while True:
                if cancel is not None and cancel.is_set():
                    log.debug("capture_utterance bekor qilindi")
                    return b""
                if request.done.wait(WAIT_TICK):
                    return request.wav
                if self._stop.is_set():
                    return b""
                if time.monotonic() >= request.deadline:
                    break
        finally:
            with self._req_lock:
                if self._request is request:
                    self._request = None

        with self._req_lock:
            if request.done.is_set():
                return request.wav
            if request.started:
                # Vaqt tugadi, lekin odam gapirayotgan edi: bor qismini
                # beramiz - jimlikni kutib turgandan ko'ra STT ga yuborgan
                # ma'qul.
                log.debug("capture_utterance: timeout, qisman segment beriladi")
                self._finish(request)
                return request.wav
            request.finished = True
        return b""

    # --- listener thread'i ---------------------------------------------------

    def _run(self, gen: int = 0) -> None:
        try:
            if not self._ensure_capture():
                self._ok = False
                return
        except Exception as exc:  # noqa: BLE001 - thread jim o'lmasin
            self._error = f"mikrofon ochilmadi: {exc}"
            self._ok = False
            log.exception("AudioListener ishga tushmadi")
            return
        finally:
            self._ready.set()

        self._last_reopen = time.monotonic()
        log.info("AudioListener ishga tushdi (%d Hz, freym %d)",
                 self.sample_rate, self.frame_size)
        try:
            while not self._stop.is_set() and gen == self._gen:
                self._tick()
        except Exception:  # noqa: BLE001
            log.exception("AudioListener sikli to'xtadi")
        finally:
            log.info("AudioListener to'xtadi (segmentlar: %d)", self._segments)

    def _ensure_capture(self) -> bool:
        running = bool(getattr(self.capture, "running", False))
        if not running:
            starter = getattr(self.capture, "start", None)
            running = bool(starter()) if callable(starter) else False
        if not running:
            self._error = "mikrofon ochilmadi"
            return False
        self._ok = True
        return True

    def _tick(self) -> None:
        chunk = self._read()
        if self._want_reset:
            self._want_reset = False
            self.vad.reset()
        if chunk is None or getattr(chunk, "size", 0) == 0:
            self._check_alive()
            return
        if self._paused.is_set():
            return  # blok o'qildi, lekin busga ham VAD ga ham bermaymiz

        self.bus.push(chunk)
        self._report_level(chunk)
        for frame in self.bus.frames():
            event = self.vad.process(frame)
            if event is not VadEvent.NONE:
                self._on_event(event)

    def _read(self) -> np.ndarray | None:
        try:
            return self.capture.read(timeout=READ_TIMEOUT)
        except Exception:  # noqa: BLE001
            log.exception("capture.read xatosi")
            self._stop.wait(0.05)  # xato siklini aylantirib yubormaslik uchun
            return None

    def _report_level(self, chunk: np.ndarray) -> None:
        try:
            level = float(rms_level(np.asarray(chunk)))
        except Exception:  # noqa: BLE001
            return
        self._last_level = level
        target = self._level_target
        if target is None:
            return
        try:
            target(level)
        except Exception:  # noqa: BLE001 - UI xatosi audio oqimini to'xtatmasin
            log.debug("on_level xatosi", exc_info=True)

    def _on_event(self, event: VadEvent) -> None:
        with self._req_lock:
            request = self._request
            if request is None or request.finished:
                return
            if event is VadEvent.SPEECH_START:
                request.started = True
                if request.speech_marker is None:
                    # Aynan shu payt kerak: undan `min_speech` ni ayirsak
                    # tovushning HAQIQIY boshiga tushamiz.
                    request.speech_marker = self.bus.mark()
                return
            if event is VadEvent.SPEECH_END and request.started:
                self._finish(request)

    def _finish(self, request: _Request) -> None:
        """Segmentni yig'adi. `_req_lock` ushlangan holda chaqiriladi."""
        if request.finished:
            return
        request.finished = True
        request.wav = self._build(request)
        if request.wav:
            self._segments += 1
        if self._request is request:
            self._request = None
        request.done.set()

    def _build(self, request: _Request) -> bytes:
        """Segment chegaralarini hisoblab WAV yasaydi.

        Boshni CHAQIRUV markeridan emas, TOVUSH boshidan olamiz. Chaqiruv
        markeri nutqdan ancha oldin qo'yilgan bo'lishi mumkin (foydalanuvchi
        tugmani bosib o'ylanib turdi) - o'sha markerdan boshlasak segment
        boshida soniyalab jimlik bo'lardi: STT uni bekorga tinglaydi va
        chalg'ishi ham mumkin.
        """
        if request.speech_marker is not None:
            # VAD tasdig'i `min_speech` KECHIKKAN - tovushning haqiqiy boshi
            # shuncha orqada. Bu ayirma chaqiruv markeridan OLDINGA ham o'tishi
            # mumkin: aynan shu tufayli tugma bosilgunicha aytilgan bo'g'in
            # segmentga kiradi.
            start = request.speech_marker - self._min_speech_samples
        else:
            # Nutq tasdiqlanmagan (qisman segment) - boshqa mo'ljal yo'q.
            start = request.marker

        # pre-roll'ni O'ZIMIZ ayiramiz. `take_since(pre_roll=...)` uni
        # chegaralashdan KEYIN qo'llaydi, ya'ni quyidagi `_resume_at` to'sig'i
        # ostidan o'tib, pauzagacha bo'lgan audioni (Venera'ning O'Z OVOZI)
        # segmentga tortib kelardi.
        begin = max(start - self._pre_roll_samples, self._resume_at, 0)
        pcm = self.bus.take_since(begin)
        if pcm.size == 0:
            return b""
        return encode_wav(pcm, self.sample_rate)

    def _check_alive(self) -> None:
        """Audio kelmayapti - oqim o'lgan bo'lishi mumkin (uyqu, qurilma uzilishi)."""
        now = time.monotonic()
        if now - self._last_reopen < REOPEN_INTERVAL:
            return
        alive = getattr(self.capture, "is_alive", None)
        try:
            if callable(alive) and alive():
                return
        except Exception:  # noqa: BLE001
            pass
        self._last_reopen = now
        reopen = getattr(self.capture, "reopen", None)
        if not callable(reopen):
            return
        self._reopens += 1
        log.warning("Mikrofon javob bermayapti - qayta ochilmoqda (%d-marta)", self._reopens)
        try:
            ok = bool(reopen())
        except Exception:  # noqa: BLE001
            log.exception("Mikrofonni qayta ochib bo'lmadi")
            return
        if ok:
            # Yangi oqim - eski shovqin poli endi to'g'ri kelmaydi.
            self._want_reset = True
        else:
            log.warning("Mikrofon qayta ochilmadi - %.0f s dan keyin yana urinamiz",
                        REOPEN_INTERVAL)

    def __repr__(self) -> str:  # pragma: no cover - faqat log/debug uchun
        return (f"AudioListener(running={self.running}, paused={self.paused}, "
                f"segments={self._segments})")

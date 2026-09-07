"""Ovoz aktivligini aniqlash (VAD) - energiyaga asoslangan, adaptiv.

Nima uchun bu modul kerak: `audio/wav.py` dagi `rms_level()` o'z docstring'ida
aytganidek FAQAT UI ko'rsatkichi uchun. Uni VAD sifatida ishlatib bo'lmaydi:

  1. QATTIQ CHEGARA ISHLAMAYDI. Noutbuk mikrofoni jimlikda ~0.002, arzon USB
     mikrofon esa ~0.02 beradi - bitta raqam ikkalasiga ham to'g'ri kelmaydi.
     Xona shovqini (konditsioner, ko'cha) buni yana o'zgartiradi. Shuning uchun
     bu yerda chegara ADAPTIV shovqin polidan hosil qilinadi.
  2. BITTA CHEGARA TITRAYDI. Daraja chegara atrofida bo'lganda VAD "chertadi" -
     bir freym nutq, keyingisi jimlik. Shuning uchun GISTEREZIS: yoqish
     chegarasi (pol x 3.0) o'chirishdan (pol x 1.8) yuqori.
  3. NUTQ UZLUKSIZ EMAS. Plosiv tovushlar (p, t, k) oldida 50-150 ms tabiiy
     jimlik bor. Darajani to'g'ridan-to'g'ri o'qish so'zni o'rtasidan bo'lib
     yuboradi. Shuning uchun HANGOVER (`min_silence`).

Yana ikki tuzoq, ular dizaynni belgilagan:

  * MIKROFON AGC. Pauzada avtomatik kuchaytirish oshadi va shovqin ko'tariladi -
    mutlaq RMS suzib ketadi. Pol ham u bilan birga suzishi kerak.
  * UZUN GAP POLNI O'ZI BILAN OLIB KETADI. Agar pol nutq paytida ham tez
    yangilansa, 10 soniyalik gap oxirida pol nutq darajasiga yetadi va VAD
    nutqni "yo'qotadi". Shuning uchun pol ASIMMETRIK: jimlikda tez pastga,
    nutq paytida esa deyarli qotib turadi (`TAU_UP_ACTIVE` 60 s).

R2 da yoniga silero-VAD qo'shiladi, shuning uchun shartnoma modelga bog'liq
emas: `process(freym) -> VadEvent` ni neyron VAD ham xuddi shunday bajaradi.
Iste'molchi (orchestrator) faqat hodisalarni ko'radi, ichkarida nima
ishlayotganini bilmaydi.
"""

from __future__ import annotations

import logging
import math
from enum import Enum

import numpy as np

from .wav import rms_level

log = logging.getLogger(__name__)

#: Yoqish/o'chirish chegaralari polning karralari sifatida. Ular orasidagi
#: farq - gisterezis. O'chirish chegarasi HAR DOIM yoqishdan past bo'lishi
#: shart, aks holda VAD chegara atrofida titraydi.
THRESHOLD_ON = 3.0
THRESHOLD_OFF = 1.8

#: Shovqin poli EMA vaqt doimiylari (soniya). Asimmetriya shu yerda:
#: pastga tushish tez, nutq paytida ko'tarilish esa deyarli yo'q.
TAU_DOWN = 0.20
TAU_UP_IDLE = 1.00
TAU_UP_ACTIVE = 60.0

#: Isitish (warm-up) va majburiy uzilishdan keyingi qayta kalibrlash tezligi.
TAU_CALIBRATE = 0.30

#: Ko'tarilishda pol bir qadamda o'zidan ko'pi bilan shuncha baland MAQSADni
#: quvadi. Busiz baland gap polni bir necha freymda o'ziga tortib olardi.
MAX_RISE_RATIO = 2.0

#: Pol shundan pastga tushmaydi (~-80 dBFS). Raqamli jimlikda (o'chirilgan yoki
#: uzilgan mikrofon) pol 0 bo'lib qolsa, chegaralar ham 0 bo'ladi va HAR QANDAY
#: son "nutq" bo'lib ko'rinadi.
FLOOR_MIN = 1e-4

#: Nutq uchun mutlaq quyi chegara (~-56 dBFS). O'lik jim xonada pol juda past
#: bo'lib, ADC dizeri "nutq" deb o'qilishi mumkin - shuni to'sadi.
SPEECH_ABS_MIN = 0.0015

#: Ishga tushgandan keyin pol hali sozlanmagan. Shu davrda hodisa BERILMAYDI.
#: Narxi: ilova ochilgan payt aytilgan birinchi so'z o'tkazib yuboriladi;
#: foydasi: mikrofon oqimining birinchi shovqinli freymlari yolg'on
#: SPEECH_START bermaydi.
WARMUP_SECONDS = 1.0

#: Ketma-ket shuncha majburiy uzilishdan keyin pol qayta kalibrlanadi.
#: Haqiqiy uzun gap tabiiy pauza bilan tugab hisoblagichni nolga qaytaradi;
#: shovqinda qolgan mikrofon esa hech qachon tugatmaydi - farq shunda.
FORCED_CUTS_BEFORE_RECALIBRATE = 3

#: Suzuvchi nuqta yig'indisi uchun bo'shashma (0.032 * 8 = 0.25600000000000006).
_EPS = 1e-9


class VadEvent(str, Enum):
    """VAD holati o'zgarishi. `str` merosi - log va JSON uchun qulay."""

    NONE = "none"
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


def _frame_level(frame) -> float:
    """Freymning 0..1 oralig'idagi RMS darajasi.

    TUZOQ: `rms_level` int16 shkalasini kutadi (32768 ga bo'ladi). Agar
    kimdir -1..1 oralig'idagi float bersa, daraja juda kichik chiqadi va
    freym jimlik deb qabul qilinadi - bu XAVFSIZ default, ilova yiqilmaydi.
    NaN/inf ham 0.0 ga aylanadi: aks holda ular polni buzib, VAD ni butunlay
    o'lik holatga olib borardi.
    """
    try:
        samples = np.asarray(frame)
        if samples.size == 0:
            return 0.0
        level = float(rms_level(samples))
    except Exception:  # noqa: BLE001 - noto'g'ri ma'lumot VAD ni yiqitmasin
        return 0.0
    if not math.isfinite(level) or level <= 0.0:
        return 0.0
    return min(level, 1.0)


class EnergyVad:
    """Adaptiv, gisterezisli va hangoverli energiya VAD'i.

    Har `process()` chaqiruvi bitta freym qabul qiladi va holat o'zgarganda
    hodisa qaytaradi. Hodisalar KECHIKADI va bu ataylab:

      * SPEECH_START `min_speech` to'lgach beriladi - shuning uchun audio
        buferi (`AudioBus.take_since`) pre-roll bilan ishlashi shart, aks
        holda so'z boshi yo'qoladi;
      * SPEECH_END `min_silence` to'lgach beriladi - so'z ichidagi pauza
        yozuvni uzib yubormasligi uchun.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: int = 512,
        min_speech: float = 0.25,
        min_silence: float = 0.50,
        max_speech: float = 10.0,
    ) -> None:
        # Sozlamalar konfiguratsiya faylidan keladi - foydalanuvchi u yerga
        # 0 yoki manfiy son yozsa ham VAD ishlashda davom etishi kerak.
        # int(nan) -> ValueError, int(None) -> TypeError. Qiymat config.yaml
        # dan kelgani uchun `null` real holat - aynan shu guard mo'ljallagan.
        def _butun(value: object, default: int) -> int:
            try:
                out = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default
            return out if out > 0 else default

        self.sample_rate = _butun(sample_rate, 16000)
        self.frame_size = _butun(frame_size, 512)
        self.min_speech = max(0.0, float(min_speech))
        self.min_silence = max(0.0, float(min_silence))

        nominal = self.frame_size / self.sample_rate
        if float(max_speech) > 0.0:
            # max_speech har doim min_speech dan katta bo'lishi shart, aks
            # holda SPEECH_START va majburiy SPEECH_END bitta freymga tushadi
            # va ulardan biri yo'qoladi (process bitta hodisa qaytaradi).
            self.max_speech = max(float(max_speech), self.min_speech + nominal)
        else:
            self.max_speech = math.inf  # chegara o'chirilgan

        self._nominal_alphas = self._alphas(nominal)
        self.reset()

    # --- holat ---------------------------------------------------------------

    @property
    def speaking(self) -> bool:
        """Tasdiqlangan nutq holati (nomzod davri hali `False`)."""
        return self._speaking

    @property
    def noise_floor(self) -> float:
        """Hozirgi adaptiv shovqin poli (diagnostika uchun).

        Birinchi freymgacha 0.0 - "hali o'lchanmagan".
        """
        return 0.0 if self._floor is None else self._floor

    def reset(self) -> None:
        """Butun holatni tozalaydi: pol, hisoblagichlar va isitish davri."""
        self._floor: float | None = None
        self._speaking = False
        self._speech_time = 0.0    # nomzod tovush davomiyligi (min_speech uchun)
        self._silence_time = 0.0   # nutq ichidagi jimlik (min_silence uchun)
        self._speech_elapsed = 0.0  # tovush BOSHIDAN beri (max_speech uchun)
        self._warm_left = WARMUP_SECONDS
        self._forced_cuts = 0

    # --- asosiy ish ----------------------------------------------------------

    def process(self, frame: np.ndarray) -> VadEvent:
        """Bitta freym. Holat o'zgarganda hodisa qaytaradi."""
        samples = np.asarray(frame) if frame is not None else np.zeros(0)
        if samples.size == 0:
            return VadEvent.NONE  # bo'sh freym vaqtni ham surmaydi

        # sounddevice (N, channels) beradi. `size` u holda N*channels bo'lib,
        # `duration` ikki barobar noto'g'ri chiqadi va BARCHA vaqt chegaralari
        # (min_speech, min_silence, max_speech) 2x buziladi. `capture.py`
        # reshape qiladi, lekin shartnoma buni talab qilmaydi.
        if samples.ndim > 1:
            samples = samples[..., 0] if samples.shape[-1] == 1 else samples.mean(axis=-1)

        level = _frame_level(samples)
        duration = samples.size / self.sample_rate
        alphas = (
            self._nominal_alphas if samples.size == self.frame_size
            else self._alphas(duration)
        )
        a_down, a_idle, a_active, a_calib = alphas

        if self._floor is None:
            self._floor = max(level, FLOOR_MIN)
        elif self._floor <= FLOOR_MIN and level > FLOOR_MIN * THRESHOLD_ON:
            # Pol eng tagida qolgan = oldingi freymlar RAQAMLI JIMLIK edi
            # (mikrofon mute qilingan, qurilma almashgan, drayver nol blok
            # bergan). Signal qaytganda chegaralangan ko'tarilish polga o'z
            # joyiga qaytish uchun ~3 s beradi va shu vaqt ichida ODDIY XONA
            # SHOVQINI chegaradan yuqori bo'lib qoladi: VAD "nutq" deb hisoblab
            # max_speech gacha davom etadi va butun shovqinni STT ga yuboradi.
            # Shuning uchun bunday sakrashda qayta kalibrlaymiz.
            log.debug("Raqamli jimlikdan qaytish aniqlandi - pol qayta kalibrlanadi")
            self._end_speech()
            self._warm_left = WARMUP_SECONDS

        # Isitish: pol hali sozlanmagan, hodisa berish mumkin emas. Bu davrda
        # daraja qanday bo'lsa ham u SHOVQIN deb qabul qilinadi.
        if self._warm_left > 0.0:
            self._warm_left -= duration
            self._track_noise(level, a_calib, a_calib, bounded=False)
            return VadEvent.NONE

        # thr_off ni polning alohida karrasi sifatida emas, thr_on dan hosil
        # qilamiz: shunda mutlaq quyi chegara ishlab ketganda ham gisterezis
        # saqlanadi (aks holda ikkala chegara bir joyga yopishib qolardi).
        thr_on = max(self._floor * THRESHOLD_ON, SPEECH_ABS_MIN)
        thr_off = thr_on * (THRESHOLD_OFF / THRESHOLD_ON)

        # Gisterezis: kirish uchun thr_on, ushlab turish uchun thr_off.
        holding = self._speaking or self._speech_time > 0.0
        active = level >= thr_off if holding else level >= thr_on

        event = VadEvent.NONE
        if not self._speaking:
            if active:
                self._speech_time += duration
                if self._speech_time >= self.min_speech - _EPS:
                    self._speaking = True
                    # max_speech tovush BOSHIDAN sanaladi, tasdiqdan emas:
                    # yuqoridagi bufer ham aynan o'sha paytdan yozib oladi.
                    self._speech_elapsed = self._speech_time
                    self._silence_time = 0.0
                    event = VadEvent.SPEECH_START
            else:
                # Yo'tal, eshik taqillashi - min_speech ga yetmadi, unutamiz.
                self._speech_time = 0.0
        else:
            self._speech_elapsed += duration
            if active:
                self._silence_time = 0.0
            else:
                self._silence_time += duration
                if self._silence_time >= self.min_silence - _EPS:
                    # Tabiiy yakun: gap o'z pauzasi bilan tugadi. Majburiy
                    # uzilishlar hisoblagichi nolga qaytadi.
                    self._forced_cuts = 0
                    self._end_speech()
                    event = VadEvent.SPEECH_END

            if event is VadEvent.NONE and self._speech_elapsed >= self.max_speech - _EPS:
                # Ikki xil sabab bir xil ko'rinadi: (a) mikrofon shovqinda
                # qolgan, (b) foydalanuvchi haqiqatan uzoq gapiryapti.
                #
                # Darhol qayta kalibrlash (a) ni tuzatadi, lekin (b) ni
                # O'LDIRADI: pol nutq darajasiga tortiladi va nutq davom
                # etayotgani uchun o'sha yerda QOTIB qoladi - VAD gapiruvchi
                # to'xtaguncha kar bo'ladi, ya'ni 45 soniyalik diktovkadan
                # faqat birinchi 10 soniyasi eshitiladi.
                #
                # Shuning uchun uchinchi KETMA-KET majburiy uzilishdan keyin
                # kalibrlaymiz: haqiqiy gap tabiiy pauza bilan tugab
                # hisoblagichni nolga qaytaradi, shovqinda qolgan mikrofon esa
                # hech qachon tugatmaydi. Narxi: shovqinda 1 emas, 3 ta
                # yolg'on segment.
                self._forced_cuts += 1
                log.debug(
                    "max_speech (%.1f s) to'ldi - majburiy SPEECH_END (%d-marta ketma-ket)",
                    self.max_speech, self._forced_cuts,
                )
                self._end_speech()
                if self._forced_cuts >= FORCED_CUTS_BEFORE_RECALIBRATE:
                    log.debug("Ketma-ket %d majburiy uzilish - pol qayta kalibrlanadi",
                              self._forced_cuts)
                    self._warm_left = WARMUP_SECONDS
                event = VadEvent.SPEECH_END

        if level < thr_off:
            # Shovqinga o'xshash freym: pastga tez, yuqoriga o'rtacha.
            self._track_noise(level, a_down, a_idle, bounded=True)
        else:
            # Chegaradan yuqori freym. U nutq bo'lishi mumkin, shuning uchun
            # pol deyarli qimirlamaydi - ASIMMETRIYANING MOHIYATI shu.
            self._track_noise(level, a_down, a_active, bounded=True)
        return event

    # --- ichki ---------------------------------------------------------------

    def _end_speech(self) -> None:
        self._speaking = False
        self._speech_time = 0.0
        self._silence_time = 0.0
        self._speech_elapsed = 0.0

    def _alphas(self, duration: float) -> tuple[float, float, float, float]:
        """Freym uzunligiga mos EMA koeffitsientlari.

        Vaqt doimiylaridan hisoblanadi, shuning uchun freym o'lchami
        o'zgarsa ham VAD ning VAQT xatti-harakati o'zgarmaydi.
        """
        step = max(duration, 1e-6)
        return (
            1.0 - math.exp(-step / TAU_DOWN),
            1.0 - math.exp(-step / TAU_UP_IDLE),
            1.0 - math.exp(-step / TAU_UP_ACTIVE),
            1.0 - math.exp(-step / TAU_CALIBRATE),
        )

    def _track_noise(self, level: float, a_down: float, a_up: float, bounded: bool) -> None:
        """Asimmetrik EMA.

        `bounded` - maqsad polning MAX_RISE_RATIO karrasidan oshmaydi. Shu
        tufayli baland tovush polni bir sakrashda o'ziga tortib ololmaydi,
        faqat asta-sekin ko'tara oladi.

        Diqqat: tez pastga tushish polni o'rtacha shovqindan bir oz PASTGA
        cho'ktiradi (u minimumga intiladi). Bu ataylab - chegara shovqin
        cho'qqilaridan emas, uning tagidan hisoblangani ma'qul.
        """
        floor = self._floor if self._floor is not None else level
        if level < floor:
            floor += a_down * (level - floor)
        else:
            target = min(level, floor * MAX_RISE_RATIO) if bounded else level
            floor += a_up * (target - floor)
        self._floor = max(floor, FLOOR_MIN)

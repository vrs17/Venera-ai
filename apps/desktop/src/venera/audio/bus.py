"""Bitta mikrofon oqimini bir nechta iste'molchiga bo'lish (fan-out) + pre-roll.

Nima uchun bu modul kerak - `audio/capture.py` dagi ikki nuqson:

1. `AudioCapture.read()` blokni navbatdan OLIB TASHLAYDI (`Queue.get`). Bitta
   o'quvchi uchun to'g'ri, lekin bizda ikkitasi bor: wake word tinglovchisi
   DOIM tinglaydi, buyruq yozuvchisi esa uyg'otgichdan keyin yozadi. Ikkalasi
   bir vaqtda `read()` chaqirsa bloklar ular o'rtasida TASODIFIY bo'linadi -
   har biri audioning taxminan yarmini ko'radi va ikkalasi ham ishlamaydi.

2. So'z boshi kesiladi. `record()` avval `drain()` qiladi, ya'ni "Venera" dan
   keyin darhol aytilgan so'zning birinchi bo'g'ini navbatda qolib o'chiriladi:
   "Venera, chromeni och" -> STT ga "romeni och" boradi. Uyg'otgichni aniqlash
   ham vaqt oladi, shuning uchun O'TMISHGA qarash imkoni bo'lishi shart.

Yechim - yozuvchi bitta (audio-pump thread'i `push()` qiladi), o'quvchilar ko'p
va ular buferni KAMAYTIRMAYDI, faqat nusxa oladi:

  * `frames()`     - wake word detektori uchun sobit uzunlikdagi freymlar.
                     Yagona "iste'mol qiluvchi" metod: detektor har freymni
                     roppa-rosa bir marta ko'rishi kerak.
  * `mark()` + `take_since()` - buyruq yozuvchisi uchun. Uyg'otgich aniqlangan
                     payt belgilanadi, keyin o'sha paytdan VA undan oldingi
                     `pre_roll` soniyadan boshlab audio olinadi.
  * `snapshot()`   - "oxirgi N soniya" ni darhol olish.

Xotira SOBIT: aylanma bufer 10 s @ 16 kHz int16 = 320 KB va o'smaydi.
Iste'molchi sekinlashsa eng eski namunalar ustiga yoziladi - ilova yiqilmaydi,
faqat `dropped` telemetriyasi oshadi.
"""

from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)


def _seconds(value: object, default: float = 0.0) -> float:
    """None / NaN / cheksizlik / son bo'lmagan qiymatni xavfsiz soniyaga aylantiradi.

    Qiymatlar config.yaml dan kelishi mumkin, ya'ni `null` yoki `.nan` bo'lishi
    real holat. `int(nan * rate)` esa ValueError, `int(inf * rate)` OverflowError
    beradi - ikkalasi ham audio thread'ini o'ldirardi.
    """
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out

#: Halqaning eng kichik uzunligi (soniya). Nosoz sozlamadan himoya.
MIN_SECONDS = 0.1


class AudioBus:
    """Bitta yozuvchi, ko'p o'quvchi: aylanma bufer, sobit xotira, pre-roll.

    Barcha metodlar thread-safe: `push()` audio callback thread'idan,
    qolganlari core/UI thread'idan chaqiriladi.

    Ichki hisob ABSOLYUT namuna indeksida yuritiladi (`total_samples` -
    boshidan beri kelgan namunalar soni). Halqadagi joy = indeks % capacity.
    Shu sabab marker - bu shunchaki son, u halqa aylanganda ham "eskirgan"
    ekanini bilish uchun yetarli.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        seconds: float = 10.0,
        frame_size: int = 512,
    ) -> None:
        # Nosoz sozlama ilovani yiqitmasligi kerak - xavfsiz minimumga tushiramiz.
        # Lekin JIMGINA emas: frame_size=0 dan kelib chiqqan "har biri 1 namunali
        # minglab freym" holatini keyin diagnostika qilib bo'lmaydi.
        try:
            rate, frame = int(sample_rate), int(frame_size)
        except (TypeError, ValueError):
            rate, frame = 0, 0
        if rate < 1 or frame < 1:
            log.warning("AudioBus: nosoz sozlama (rate=%r, frame=%r) - default'ga tushirildi",
                        sample_rate, frame_size)
            rate = rate if rate >= 1 else 16000
            frame = frame if frame >= 1 else 512
        self.sample_rate = rate
        self.frame_size = frame
        span = max(_seconds(seconds, MIN_SECONDS), MIN_SECONDS)
        self._capacity = max(self.frame_size, int(self.sample_rate * span))

        self._ring = np.zeros(self._capacity, dtype=np.int16)
        self._total = 0      # qabul qilingan namunalar (monoton)
        self._cursor = 0     # frames() qayerdan davom etadi (absolyut indeks)
        self._dropped = 0
        # take_since() ni takror chaqirganda ayni yo'qotish qayta sanalmasligi
        # uchun: oxirgi sanalgan marker va u uchun sanalgan chegara.
        self._counted_marker = -1
        self._counted_to = 0

        # DIQQAT: oddiy Lock REENTRANT EMAS. Ichki `_*_locked` yordamchilari
        # lockni O'ZI olmaydi - chaqiruvchi uni ushlab turgan bo'lishi shart.
        # Public metod ichidan boshqa public metodni chaqirmaymiz (deadlock).
        self._lock = threading.Lock()

    # --- telemetriya ---------------------------------------------------------

    @property
    def total_samples(self) -> int:
        """Boshidan beri qabul qilingan namunalar soni (monoton o'sadi)."""
        with self._lock:
            return self._total

    @property
    def dropped(self) -> int:
        """Halqa to'lib ketgani uchun YO'QOLGAN namunalar soni.

        "Yo'qolgan" = iste'molchi ko'rmay qolgan: freym kursori ortda qolib
        ustiga yozilgan yoki `take_since()` eskirgan markerdan so'ralgan.
        Ikki iste'molchi bir xil namunani yo'qotsa ikki marta sanaladi - bu
        telemetriya, aniq buxgalteriya emas.
        """
        with self._lock:
            return self._dropped

    @property
    def capacity(self) -> int:
        """Halqa sig'imi (namuna). Xotira = capacity * 2 bayt, o'zgarmaydi."""
        return self._capacity

    # --- yozish --------------------------------------------------------------

    def push(self, pcm: np.ndarray) -> None:
        """int16 namunalar. Ixtiyoriy uzunlikda kelishi mumkin."""
        if pcm is None:
            return
        try:
            data = np.asarray(pcm)
        except (TypeError, ValueError) as exc:
            log.debug("push: massivga aylantirib bo'lmadi: %s", exc)
            return

        # Shkala qarori ASL turdan olinadi: kanallarni o'rtachalash int16 ni
        # float64 ga aylantiradi va keyingi shox uni [-1,1] float PCM deb
        # hisoblab 32767 ga ko'paytirib yuborardi (2000 -> to'yingan 32767).
        float_pcm = data.dtype.kind == "f"

        # sounddevice callback (frames, channels) shaklida beradi. Oddiy
        # reshape(-1) stereo blokni L,R,L,R qilib mono halqaga yozadi -
        # natija ikki barobar tezlashgan shovqin va total_samples ham 2x
        # noto'g'ri bo'ladi. Shuning uchun avval kanallarni yig'amiz.
        if data.ndim > 1:
            data = data[..., 0] if data.shape[-1] == 1 else data.mean(axis=-1)
        data = np.ascontiguousarray(data).reshape(-1)
        if data.size == 0:
            return

        if float_pcm:
            # float PCM konvensiyasi [-1.0, 1.0]. Shkalasiz astype butun
            # signalni yo'q qiladi: 0.8 -> 1, ya'ni namunalarning yarmi nol
            # bo'ladi va bus JIMLIK uzatadi. sounddevice'da dtype="float32"
            # keng tarqalgan, shuning uchun bu shox majburiy.
            data = np.clip(data.astype(np.float64) * 32767.0, -32768.0, 32767.0)
            data = np.rint(data).astype(np.int16)
        elif data.dtype != np.int16:
            # Butun sonli boshqa tur (int32...). astype() o'zi TO'LIB KETSA
            # aylanib ketadi (32768 -> -32768), ya'ni baland tovush shovqinga
            # aylanadi; clip buni oldini oladi.
            try:
                data = np.clip(data.astype(np.float64), -32768.0, 32767.0)
                data = np.rint(data).astype(np.int16)
            except (TypeError, ValueError) as exc:
                log.debug("push: int16 ga o'girilmadi (%s): %s", data.dtype, exc)
                return

        with self._lock:
            self._write_locked(data)

    # --- o'qish --------------------------------------------------------------

    def frames(self) -> list[np.ndarray]:
        """push() dan keyin to'plangan TO'LIQ freymlar (har biri frame_size).

        Chaqirilgach ular ichki navbatdan olib tashlanadi. To'liq bo'lmagan
        qoldiq keyingi push gacha saqlanadi.
        """
        with self._lock:
            self._forget_overwritten_locked()
            count = (self._total - self._cursor) // self.frame_size
            if count <= 0:
                return []
            end = self._cursor + count * self.frame_size
            block = self._read_locked(self._cursor, end)
            self._cursor = end

        # `block` - halqadan olingan NUSXA, shuning uchun uning bo'laklari
        # ustidan keyingi push() yozib yubormaydi (view qaytarsak yozardi).
        return list(block.reshape(count, self.frame_size))

    def mark(self) -> int:
        """Hozirgi pozitsiyani belgilaydi va uni qaytaradi (= total_samples)."""
        with self._lock:
            return self._total

    def take_since(self, marker: int, pre_roll: float = 0.0) -> np.ndarray:
        """marker dan hozirgacha bo'lgan audio + undan OLDINGI pre_roll soniya.

        Halqadan chiqib ketgan qism bo'lsa - bor qismini qaytaradi.

        ENG NOZIK JOY: marker qo'yilgandan keyin core thread band bo'lsa halqa
        aylanib ketishi mumkin. Bunday holatda YIQILMAYMIZ va bo'sh ham
        qaytarmaymiz - qolgan audio bilan STT baribir ko'p hollarda to'g'ri
        matn beradi. Yo'qotish `dropped` da qayd etiladi.
        """
        try:
            start = int(marker)
        except (TypeError, ValueError):
            return np.zeros(0, dtype=np.int16)

        with self._lock:
            # Marker kelajakda (boshqa bus'dan kelgan yoki reset bo'lgan) yoki
            # manfiy bo'lishi mumkin - ikkalasini ham chegaraga qisamiz.
            start = min(max(start, 0), self._total)
            oldest = max(0, self._total - self._capacity)
            if start < oldest:
                # take_since - O'QISH metodi, lekin yo'qotishni ham qayd etadi.
                # Bir xil marker bilan takror chaqirilsa (retry/timeout yo'li)
                # ayni yo'qotish qayta-qayta sanalib, telemetriya shishib
                # ketardi. Shuning uchun faqat HALI sanalmagan qismini qo'shamiz.
                seen = self._counted_to if self._counted_marker == start else start
                if oldest > seen:
                    self._dropped += oldest - seen
                self._counted_marker, self._counted_to = start, oldest
                start = oldest

            pre = max(0, int(_seconds(pre_roll) * self.sample_rate))
            # pre-roll - "bor bo'lsa yaxshi": yetmagani yo'qotish hisoblanmaydi.
            begin = max(oldest, start - pre)
            return self._read_locked(begin, self._total)

    def snapshot(self, seconds: float) -> np.ndarray:
        """Oxirgi N soniya (pre-roll uchun DARHOL nusxa olish)."""
        wanted = int(_seconds(seconds) * self.sample_rate)
        if wanted <= 0:
            return np.zeros(0, dtype=np.int16)

        with self._lock:
            count = min(wanted, self._capacity, self._total)
            return self._read_locked(self._total - count, self._total)

    # --- ichki (lock CHAQIRUVCHIDA bo'lishi shart) ---------------------------

    def _write_locked(self, data: np.ndarray) -> None:
        cap = self._capacity
        size = data.size
        if size > cap:
            # Bitta push halqadan katta: faqat oxirgi cap namuna qoladi.
            # `total` esa to'liq oshadi - u "qabul qilingan", "saqlangan" emas.
            data = data[-cap:]

        self._total += size
        begin = (self._total - data.size) % cap
        end = begin + data.size
        if end <= cap:
            self._ring[begin:end] = data
        else:
            split = cap - begin
            self._ring[begin:] = data[:split]
            self._ring[:end - cap] = data[split:]

        self._forget_overwritten_locked()

    def _forget_overwritten_locked(self) -> None:
        """Freym kursori ustiga yozilgan bo'lsa - uni eng eskisiga surib qo'yamiz."""
        oldest = self._total - self._capacity
        if self._cursor < oldest:
            self._dropped += oldest - self._cursor
            self._cursor = oldest

    def _read_locked(self, start: int, end: int) -> np.ndarray:
        """[start, end) absolyut oralig'ining NUSXASI. Chegaradan chiqsa qisiladi."""
        start = max(start, self._total - self._capacity, 0)
        end = min(end, self._total)
        count = end - start
        if count <= 0:
            return np.zeros(0, dtype=np.int16)

        cap = self._capacity
        begin = start % cap
        if begin + count <= cap:
            return self._ring[begin:begin + count].copy()
        # Halqa chetidan o'tib ketdi - ikki bo'lakni ulaymiz.
        # concatenate allaqachon yangi massiv beradi, qo'shimcha copy() shart emas.
        return np.concatenate((self._ring[begin:], self._ring[:begin + count - cap]))

    def __repr__(self) -> str:  # pragma: no cover - faqat log/debug uchun
        return (
            f"AudioBus(sample_rate={self.sample_rate}, "
            f"capacity={self._capacity}, frame_size={self.frame_size}, "
            f"total={self._total}, dropped={self._dropped})"
        )

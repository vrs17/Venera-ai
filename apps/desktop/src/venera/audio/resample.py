"""Mikrofon oqimini 16 kHz ga keltirish - holatli va anti-aliasing bilan.

NEGA BU MODUL BOR:
  STT ham, wake word ham aynan 16 kHz kutadi, lekin ko'pchilik noutbuk mikrofoni
  44.1 yoki 48 kHz da ishlaydi. Mavjud `wav.resample_linear()` bir martalik yozuv
  uchun yozilgan va OQIM uchun yaroqsiz:

    * har blokni MUSTAQIL qayta namunalaydi - `linspace` ikkala chekkani ham
      qamragani uchun blok chegarasida namuna takrorlanadi/uziladi (chertillash);
    * blok uzunligi `int(round(...))` bilan yaxlitlangani uchun namuna soni
      blokdan blokka suzadi va uzun seansda vaqt DRIFT qiladi;
    * anti-aliasing filtri umuman yo'q - 48->16 da 8 kHz dan yuqori har qanday
      chastota soxta tovush bo'lib pastga qaytadi (10 kHz -> 6 kHz). Xonadagi
      "s"/"sh" tovushlari va shovqin aynan shu yo'l bilan nutq diapazoniga
      aralashadi va STT aniqligini tushiradi.

  `Resampler` esa oqim uchun: FIR filtr tarixi (`_tail`) va kasr faza (`_phase`)
  bloklar orasida saqlanadi. Shuning uchun 512 namunali bloklarni ketma-ket berish
  butun yozuvni bir marta qayta namunalash bilan bir xil natija beradi.

USUL:
  Blackman oynali sinc (windowed-sinc) yadro. scipy yo'q, shuning uchun
  koeffitsiyentlar shu yerda hisoblanadi. Yadro bir marta yuqori zichlikda
  jadvalga yoziladi (`_yadro_jadvali`) va undan har bir kasr faza uchun FIR
  koeffitsiyentlari qurilib qo'yiladi (`_faza_jadvali`). Ish vaqtida faqat
  ko'paytir-qo'sh qoladi: 48 kHz oqim bitta yadroning ~2 foizini oladi.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

DST_RATE_DEFAULT = 16000

# Yadroning bir tomonidagi nol kesishmalar soni. 32 -> pastki chastotada 64 ta
# samarali tap: Blackman oynasi bilan to'siq zonasi ~-74 dB, o'tish zonasi esa
# Nyquist ichiga sig'adi. Kattalashtirish sifatni deyarli oshirmaydi, CPU ni esa
# chiziqli oshiradi.
_YARIM_TAP = 32
# Jadval zichligi: bitta nol kesishmaga nechta nuqta. Chiziqli interpolyatsiya
# xatosi ~(1/_ZICHLIK)^2, ya'ni 512 da -110 dB dan past - eshitilmaydi.
_ZICHLIK = 512
# Kesish chastotasi Nyquist'ning 90% ida. 100% qilinsa o'tish zonasining yarmi
# Nyquist'dan oshib ketadi va aynan biz kurashayotgan aliasing qaytib keladi.
_ROLLOFF = 0.90
# Bir martada hisoblanadigan matritsa hajmi (element). Uzun yozuvni bir marta
# uzatganda (n_out x taps) matritsa yuzlab MB bo'lib ketmasligi uchun cheklov.
_MAX_ELEM = 1 << 18
# Oldindan hisoblab qo'yiladigan faza jadvalining eng katta hajmi (element).
# Odatdagi tezliklarda jadval kichik (48000->16000 da atigi 1 ta faza,
# 44100->16000 da 160 ta), lekin "notekis" tezlikda u o'sib ketishi mumkin -
# o'shanda jadvalsiz, har blokda hisoblab ishlaymiz.
_MAX_FAZA_ELEM = 1 << 20


@lru_cache(maxsize=1)
def _yadro_jadvali() -> np.ndarray:
    """Blackman oynali sinc yadroning bir tomonlama jadvali.

    Argument `u = |x| * 2 * fc` - ya'ni yadro kesish chastotasiga nisbatan
    o'lchangan. Shu tufayli jadval BARCHA namuna chastotalari uchun bitta.
    """
    n = _YARIM_TAP * _ZICHLIK
    # Oxirida +2 nuqta: chiziqli interpolyatsiya har doim [j, j+1] juftini o'qiydi.
    u = np.arange(n + 2, dtype=np.float64) / _ZICHLIK
    oyna = 0.42 + 0.5 * np.cos(np.pi * u / _YARIM_TAP) + 0.08 * np.cos(2.0 * np.pi * u / _YARIM_TAP)
    jadval = np.sinc(u) * oyna
    jadval[u >= _YARIM_TAP] = 0.0
    return jadval


class Resampler:
    """int16 mono oqimni `src_rate` dan `dst_rate` ga uzluksiz keltiradi.

    Bitta qurilma uchun bitta nusxa saqlanadi. Qurilma qayta ochilganda
    `reset()` chaqirilishi shart, aks holda eski qurilmaning filtr tarixi
    yangi oqimning boshiga "sizib" o'tadi.
    """

    def __init__(self, src_rate: int, dst_rate: int = DST_RATE_DEFAULT) -> None:
        try:
            src = int(src_rate)
            dst = int(dst_rate)
        except (TypeError, ValueError):  # qurilma ma'lumoti buzuq bo'lsa ham yiqilmaymiz
            src, dst = 0, 0

        self.src_rate = src
        self.dst_rate = dst
        # Nosoz yoki bir xil tezlik - ishlov bermaymiz.
        self._passthrough = src <= 0 or dst <= 0 or src == dst

        if self._passthrough:
            self._fc2 = 1.0
            self._hw = 0
            self._offsets = np.zeros(0, dtype=np.int64)
            self._batch = 1
        else:
            # Kesish chastotasi kirish namunasiga nisbatan (sikl/namuna).
            # Pastga tushirishda chiqish Nyquist'i, yuqoriga ko'tarishda esa
            # kirish Nyquist'i cheklovchi bo'ladi - shuning uchun min().
            self._fc2 = _ROLLOFF * min(1.0, dst / src)
            # Yadro tayanchining yarmi, kirish namunalarida.
            self._hw = int(math.ceil(_YARIM_TAP / self._fc2))
            self._offsets = np.arange(-self._hw + 1, self._hw + 1, dtype=np.int64)
            self._batch = max(1, _MAX_ELEM // (2 * self._hw))

        # Kasr faza (n*src) % dst faqat gcd(src, dst) ga karrali qiymatlarni
        # oladi, ya'ni jami dst/gcd ta xil faza bor.
        self._faza_qadam = math.gcd(src, dst) if not self._passthrough else 1
        self._fazalar = self._faza_jadvali()
        self.reset()

    @property
    def passthrough(self) -> bool:
        """src_rate == dst_rate (yoki tezlik nosoz) bo'lsa True."""
        return self._passthrough

    def reset(self) -> None:
        """Qurilma qayta ochilganda holat tozalanadi."""
        # Oqim boshida yadroning chap yelkasi uchun kontekst yo'q, shuning uchun
        # nol bilan to'ldiramiz - natijada birinchi ~_hw namuna sekin "ochiladi".
        self._tail = np.zeros(self._hw, dtype=np.float64)
        # Vaqt BUTUN SONLARDA yuritiladi: t = _pos + _phase/dst (kirish namunasida).
        # float bilan qo'shib borilsa uzun seansda yaxlitlash xatosi to'planib
        # drift beradi - butun son arifmetikasi buni tamoman yo'q qiladi.
        self._pos = self._hw
        self._phase = 0

    def process(self, chunk: np.ndarray) -> np.ndarray:
        """int16 mono kirish -> int16 mono chiqish. Bloklar orasida uzluksiz."""
        data = np.asarray(chunk)
        if data.size == 0:
            return np.zeros(0, dtype=np.int16)

        if self._passthrough:
            # Eng keng tarqalgan holat va u tekin bo'lishi kerak: faqat nusxa.
            return np.array(data.ravel(), dtype=np.int16, copy=True)

        buf = np.concatenate((self._tail, data.astype(np.float64).ravel()))
        n_out = self._chiqish_soni(buf.size)

        out = np.empty(n_out, dtype=np.float64)
        for boshi in range(0, n_out, self._batch):
            oxiri = min(boshi + self._batch, n_out)
            out[boshi:oxiri] = self._hisobla(buf, boshi, oxiri)

        self._holatni_surish(n_out, buf)
        # Avval clip, keyin astype: teskari tartibda float->int16 o'girilishida
        # to'lib ketish (masalan +33000 -> -32536) sodir bo'lardi.
        return np.clip(np.rint(out), -32768.0, 32767.0).astype(np.int16)

    def _chiqish_soni(self, buf_size: int) -> int:
        """Mavjud buferdan nechta chiqish namunasi to'liq hisoblanishini topadi.

        Yadro markazlashgan, ya'ni t vaqtdagi chiqish uchun t + _hw gacha KELAJAK
        kirish kerak. Shuning uchun har blokdan keyin ~_hw namuna buferda qoladi
        (kechikish 48 kHz da ~2 ms).
        """
        chegara = buf_size - self._hw - 1 - self._pos
        if chegara < 0:
            return 0
        # (_phase + n*src) // dst <= chegara  ->  n < ((chegara+1)*dst - _phase)/src
        qoldiq = (chegara + 1) * self.dst_rate - self._phase
        if qoldiq <= 0:
            return 0
        return (qoldiq + self.src_rate - 1) // self.src_rate

    def _faza_jadvali(self) -> np.ndarray | None:
        """Barcha mumkin bo'lgan kasr fazalar uchun FIR koeffitsiyentlari.

        48000->16000 da bu ATIGI BITTA faza, 44100->16000 da 160 ta. Shuning
        uchun koeffitsiyentlarni har blokda qayta hisoblash sof isrof edi
        (profilda ishlov berish vaqtining ~90 foizi shunga ketardi).
        """
        if self._passthrough:
            return None
        soni = self.dst_rate // self._faza_qadam
        if soni * 2 * self._hw > _MAX_FAZA_ELEM:
            return None  # g'alati tezlik: jadval juda katta, har blokda hisoblaymiz
        return self._taplar(np.arange(soni, dtype=np.float64) * self._faza_qadam / self.dst_rate)

    def _taplar(self, kasr: np.ndarray) -> np.ndarray:
        """Kasr fazalar uchun (n x 2*_hw) koeffitsiyent matritsasi."""
        # Yadro argumenti faqat KASR fazaga bog'liq (x = t - i = kasr - offset),
        # butun qism indeksga ketadi - shuning uchun bu yerda pos kerak emas.
        x = np.abs(kasr[:, None] - self._offsets[None, :]) * self._fc2

        ichida = x < _YARIM_TAP
        p = np.where(ichida, x * _ZICHLIK, 0.0)
        j = p.astype(np.int64)
        fr = p - j
        jadval = _yadro_jadvali()
        h = jadval[j] + fr * (jadval[j + 1] - jadval[j])
        h *= ichida

        # Har faza uchun yig'indini 1 ga keltiramiz: oynalash tufayli DC kuchayish
        # 1 dan bir oz farq qiladi va bu doimiy signalda amplituda "to'lqinlanishi"
        # bo'lib chiqadi.
        summa = h.sum(axis=1, keepdims=True)
        np.copyto(summa, 1.0, where=(summa == 0.0))
        return h / summa

    def _hisobla(self, buf: np.ndarray, boshi: int, oxiri: int) -> np.ndarray:
        nomer = self._phase + np.arange(boshi, oxiri, dtype=np.int64) * self.src_rate
        qoldiq = nomer % self.dst_rate
        pos = self._pos + nomer // self.dst_rate

        if self._fazalar is not None:
            h = self._fazalar[qoldiq // self._faza_qadam]
        else:
            h = self._taplar(qoldiq / float(self.dst_rate))

        idx = pos[:, None] + self._offsets[None, :]
        return np.einsum("ij,ij->i", h, buf[idx])

    def _holatni_surish(self, n_out: int, buf: np.ndarray) -> None:
        jami = self._phase + n_out * self.src_rate
        self._pos += jami // self.dst_rate
        self._phase = jami % self.dst_rate

        # Keyingi chiqishga eng erta kerak bo'ladigan indeks - shundan oldingisini
        # tashlaymiz. `.copy()` shart: slice butun buferni tirik ushlab turadi.
        saqlash = self._pos - self._hw + 1
        if saqlash > 0:
            self._tail = buf[saqlash:].copy()
            self._pos -= saqlash
        else:
            self._tail = buf

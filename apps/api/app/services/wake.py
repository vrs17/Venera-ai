"""Uyg'otish so'zi: "Salom Barno" (o'tish davrida eski "Salom Venera" ham qabul qilinadi).

MOSLASHTIRGICH SHU YERDA, brauzerda emas. Uchta sabab:

  1. Qaror audio va matn bilan BIR JOYDA yoziladi. Brauzer qaror qilsa,
     server nima uchun uyg'onmaganini hech qachon bilmasdi.
  2. Sozlash uchun frontend obrazini qayta yig'ish shart emas - qoidalar
     o'zgarsa faqat API qayta ishga tushadi.
  3. Bitta amalga oshirish. Ikki tilda ikki nusxa vaqt o'tib albatta
     ajralib ketardi, va qaysi biri "haqiqiy" ekani ma'lum bo'lmasdi.

`is_wake_phrase` SABABNI ham qaytaradi. "Uyg'onmadi" degan yozuv foydasiz;
"nom topildi, lekin salom yo'q" degani esa aynan nimani tuzatish kerakligini
aytadi.
"""

from __future__ import annotations

import array
import contextlib
import io
import json
import logging
import math
import re
import threading
import unicodedata
import uuid
import wave

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

NAME = "barno"
#: O'tish davri: eski "Salom Venera" ham JIM qabul qilinadi - uning qoidasi
#: (`_is_legacy`) o'zgarmagan.
LEGACY_NAME = "venera"
#: Nomni tanish uchun ruxsat etilgan Levenshtein masofasi. Model bir xil
#: tovushni "venera", "vinera", "venira" deb yozadi.
NAME_DISTANCE = 2
#: Nomzod so'z uchun eng kam uzunlik: usiz masofa<=2 "vera", "era" kabi
#: keng tarqalgan qisqa so'zlarni ham nom deb qabul qilardi.
NAME_MIN_LEN = 5

#: O'zbekcha salomlar, "assalomu alaykum" bo'linadigan bo'laklari bilan.
GREETINGS = ("salom", "assalom", "assalomu", "alaykum", "aleykum", "salomlar",
             "salomatsizmi", "hello", "hey")
#: Nomga yopishib keladigan salom boshlari - model so'zlarni qo'shadi ("salombarno").
_GREETING_STEMS = ("assalomu", "assalom", "salom", "hello", "hey")

#: Kirill -> lotin. "uz-Cyrl" da STT "Салом Барно" deb yozishi mumkin. Faqat
#: yangi nom va salom uchun ishlatiladi - eski nom qoidasi aynan avvalgidek.
_TO_LATIN = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
})

#: Undan uzun gap chaqiriq emas - "Venera tizimi haqida ayting" ham nomni
#: o'z ichiga oladi, lekin panelni ochish kerak emas.
MAX_WORDS = 5
#: Shuncha yoki undan kam so'zdan iborat gapda NOMNING O'ZI yetarli.
#:
#: Nega: uyg'otish tinglagichi allaqachon faqat qisqa (0.35-2.6 s) parchalarni
#: yuboradi, ya'ni "venera" yolg'iz kelgan bo'lsa - bu chaqiriq. Salomni
#: MAJBURIY qilish esa amalda ko'p o'tkazib yuborishga olib keldi: VAD
#: salomning boshini kesib qoladi yoki model uni yutib yuboradi.
NAME_ONLY_WORDS = 2

#: Nutq ichidagi "tekis nol" ulushi shundan oshsa yozuv BUZILGAN: brauzer
#: nutqni alohida impulslarga bo'lib, orasini nol bilan to'ldirgan. O'LCHANGAN:
#: buzilgan yozuvlarda 0.22-0.29, toza nutqda 0.06. Bunday audioni hech
#: qanday model o'qiy olmaydi - moslashtirgichni sozlash foydasiz, yozuv
#: zanjirini tuzatish kerak.
FLAT_LIMIT = 0.15


def distance(a: str, b: str, max_distance: int = 3) -> int:
    """Levenshtein, ahamiyati qolmagach to'xtaydi."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        best = i
        for j, cb in enumerate(b, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1,
                           previous[j - 1] + (ca != cb)))
            best = min(best, row[j])
        if best > max_distance:
            return max_distance + 1
        previous = row
    return previous[len(b)]


#: O'zbek imlosida bir necha xil apostrof teng ishlatiladi (o' / oʻ / o’).
_APOSTROPHES = dict.fromkeys(map(ord, "'`ʻʼ‘’´"), None)


def normalize_heard(text: str) -> str:
    """Kichik harf, apostroflarsiz, faqat so'zlar."""
    folded = unicodedata.normalize("NFKC", text or "").lower()
    folded = folded.translate(_APOSTROPHES)
    folded = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    return re.sub(r"\s+", " ", folded).strip()


def _is_barno(word: str) -> bool:
    """Shu so'z "barno" mi? QAT'IY: butun so'z, masofa <=1, uzunligi 5-6 -
    yoki salomga yopishgan nom ("salombarno").

    Eski nomdagi keng chegara (masofa 2-3, uzun so'z ichida qidirish) bu
    nomda XAVFLI: "barcha", "barda", "barmoq", "xabarni" ham nom bo'lib
    qolardi - "salom barcha" esa guruhdagi eng ko'p salom.
    """
    if len(word) in (len(NAME), len(NAME) + 1) and distance(word, NAME, 1) <= 1:
        return True
    for stem in _GREETING_STEMS:
        rest = word[len(stem):]
        if word.startswith(stem) and len(rest) in (len(NAME), len(NAME) + 1) and distance(rest, NAME, 1) <= 1:
            return True
    return False


def _is_legacy(word: str) -> bool:
    """Shu so'z "venera" mi?

    Chegara so'z uzunligiga qarab o'sadi. Sabab jonli yozuvlardan: model
    nomni "minera", "mener", "verenam", "venira" deb qaytaradi - qancha uzun
    bo'lsa, shuncha ko'p qo'shimcha harf qo'shadi, lekin qisqa so'zda esa
    kengroq chegara "vera", "era" kabi oddiy so'zlarni ham nom deb qabul
    qilardi.

    Uzun so'z ICHIDA ham qidiriladi: model so'zlarni qo'shib yuboradi
    ("salomvenera"), va bunday holatda butun so'z bilan taqqoslash hech
    qachon mos kelmasdi.
    """
    if len(word) < NAME_MIN_LEN:
        return False
    limit = 2 if len(word) <= len(LEGACY_NAME) else 3
    if distance(word, LEGACY_NAME, limit) <= limit:
        return True
    if len(word) > len(LEGACY_NAME) + 1:
        for size in (len(LEGACY_NAME), len(LEGACY_NAME) + 1):
            if distance(word[-size:], LEGACY_NAME, 1) <= 1 or distance(word[:size], LEGACY_NAME, 1) <= 1:
                return True
    return False


def is_wake_phrase(text: str, trace: dict[str, object] | None = None) -> tuple[bool, str]:
    """(uyg'otadimi, sabab). Sabab log uchun - "nega uyg'onmadi" degan savol
    aynan shu yerda javob topadi.

    `trace` (ixtiyoriy) - admin "Tizim xaritasi" sinovi: oraliq qiymatlar (tozalangan
    matn, lotin so'zlar, nom qaysi shaklda topildi, salom qaysi so'zlar ichida
    qidirildi) shu lug'atga yoziladi - sinov ularni o'zicha qayta hisoblamaydi.
    `None` da xulq o'zgarmaydi."""
    note: dict[str, object] = trace if trace is not None else {}
    heard = normalize_heard(text)
    words = heard.split()
    note.update(heard=heard, words=words)
    if not words:
        return False, "bo'sh"
    if len(words) > MAX_WORDS:
        return False, f"juda uzun ({len(words)} so'z)"
    latin = heard.translate(_TO_LATIN).split()
    # "bar no" - model nomni ikkiga bo'lib yozadi.
    barno = any(_is_barno(word) for word in latin) or any(a + b == NAME for a, b in zip(latin, latin[1:]))
    note.update(latin=latin, barno=barno)
    if not barno and not any(_is_legacy(word) for word in words):
        return False, "nom yo'q"
    pool = latin if barno else words
    note["pool"] = "latin" if barno else "heard"
    if any(distance(word, greeting, 2) <= 2 for word in pool for greeting in GREETINGS):
        return True, "salom + nom"
    if len(words) <= NAME_ONLY_WORDS:
        return True, "faqat nom (qisqa chaqiriq)"
    return False, "salom yo'q"


def measure(wav: bytes, *, floor: float = 0.015) -> tuple[float, float, float, float]:
    """WAV -> (eng baland nuqta, o'rtacha quvvat, nutq soniyalari, tekis ulush).

    Bu SERVERDA hisoblanadi, klientdan so'ralmaydi: klient yuborgan raqamga
    ishonish uni tekshirib bo'lmaydigan qiladi, va aynan shu raqamlar
    keyinchalik qaror qabul qilishga asos bo'ladi.

    TEKIS ULUSH - nutq oralig'idagi 1 ms bo'laklardan nechtasi amalda nol.
    Haqiqiy nutqda unli tovush uzluksiz to'lqin, ya'ni 1 ms ichida nol
    bo'lib qolmaydi. Bu raqam katta bo'lsa, yozuv modelga yetguncha
    buzilgan: transkript "noto'g'ri" emas, audio yo'q.
    """
    empty = 0.0, 0.0, 0.0, 0.0
    try:
        with wave.open(io.BytesIO(wav)) as source:
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
        if source.getsampwidth() != 2 or not rate:
            return empty
        samples = array.array("h")
        samples.frombytes(frames[: len(frames) - len(frames) % 2])
    except (wave.Error, EOFError, ValueError):
        return empty
    if not samples:
        return empty

    peak = max(abs(s) for s in samples) / 32768
    total = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768

    # Nutq: 50 ms oynalar ichida chegaradan yuqori bo'lgan birinchi va
    # oxirgi oyna orasi. Jimlikni hisobga olmaydi.
    window = max(1, rate // 20)
    loud = [
        i for i in range(0, len(samples) - window, window)
        if math.sqrt(sum(s * s for s in samples[i:i + window]) / window) / 32768 > floor
    ]
    if not loud:
        return peak, total, 0.0, 0.0
    begin, end = loud[0], loud[-1] + window
    speech = (end - begin) / rate

    # 1 ms bo'lak butunlay 33/32768 (~0.001) dan past bo'lsa - tekis nol.
    step = max(1, rate // 1000)
    blocks = range(begin, end - step + 1, step)
    flat_blocks = sum(1 for i in blocks if max(abs(s) for s in samples[i:i + step]) < 33)
    flat = flat_blocks / len(blocks) if len(blocks) else 0.0
    return peak, total, speech, flat


# --- Yozib borish -----------------------------------------------------------


@dataclass(frozen=True)
class WakeAttempt:
    """Bitta urinish. `audio` - papkaga nisbatan yo'l."""

    id: str
    at: str
    actor_id: int
    language: str
    text: str
    matched: bool
    reason: str
    duration_sec: float
    backend: str
    audio: str
    #: Eng baland nuqta va o'rtacha quvvat (0..1). Muvaffaqiyatsizlik
    #: sababini AYNAN shu ikki son ochib berdi: nom salomdan ancha past
    #: aytilganda model uni o'zining eng ehtimolli taxminiga almashtiradi.
    peak: float = 0.0
    rms: float = 0.0
    #: Nutq qismi (soniya) - jimlikni hisobga olmagan holda. Kesilish
    #: bo'lganini shu ko'rsatadi: muvaffaqiyatsizlarda 0.65-0.85 s edi,
    #: muvaffaqiyatlilarda 1.05-1.70 s.
    speech_sec: float = 0.0
    #: Nutq ichidagi tekis nol ulushi (0..1), `measure` ga qarang. FLAT_LIMIT
    #: dan yuqorisi - yozuv brauzerdayoq buzilgan; "shovqin" deb eshitiladi.
    flat: float = 0.0


class WakeLog:
    """Urinishlarni diskka yozadi: audio + JSONL qatori.

    NEGA JSONL: har qator mustaqil, ya'ni yozish atomik qo'shish bo'ladi va
    fayl o'sganda ham hech narsa qayta yozilmaydi. Bitta katta JSON bo'lsa,
    har yozuvda butun fayl qayta yozilishi va yarim yo'lda uzilib qolishi
    mumkin edi.

    Ovoz yozuvlari SHAXSIY MA'LUMOT. Papka `.gitignore` da, va bu yerda
    email emas, ichki `actor_id` saqlanadi.
    """

    def __init__(self, directory: Path, *, max_files: int = 500) -> None:
        self.directory = directory
        self.audio_dir = directory / "audio"
        self.index = directory / "wake.jsonl"
        self.max_files = max(1, max_files)
        self._lock = threading.Lock()

    def record(
        self,
        audio: bytes,
        *,
        actor_id: int,
        language: str,
        text: str,
        matched: bool,
        reason: str,
        duration_sec: float = 0.0,
        backend: str = "",
    ) -> WakeAttempt:
        peak, rms, speech, flat = measure(audio)
        if flat > FLAT_LIMIT:
            # Bu holatda transkriptni o'rganish vaqt isrofi - nutqning o'zi
            # yetib kelmagan. Sababi klient tomonida, log shuni aytsin.
            log.warning(
                "Uyg'otish audiosi buzilgan: nutqning %d%% qismi tekis nol - "
                "brauzer yozuv zanjiri (getUserMedia sozlamalari) tekshirilsin",
                round(flat * 100),
            )
        attempt_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        name = f"{attempt_id}.wav"
        entry = WakeAttempt(
            id=attempt_id,
            at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            actor_id=actor_id,
            language=language,
            text=text,
            matched=matched,
            reason=reason,
            duration_sec=round(duration_sec, 2),
            backend=backend,
            audio=f"audio/{name}",
            peak=round(peak, 3),
            rms=round(rms, 4),
            speech_sec=round(speech, 2),
            flat=round(flat, 3),
        )
        with self._lock:
            try:
                self.audio_dir.mkdir(parents=True, exist_ok=True)
                (self.audio_dir / name).write_bytes(audio)
                with self.index.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
                self._prune()
            except OSError as exc:
                # Yozib bo'lmasa ham uyg'otishning O'ZI ishlashi kerak -
                # bu diagnostika, funksiya emas.
                log.warning("Uyg'otish jurnali yozilmadi: %s", exc)
        return entry

    def _prune(self) -> None:
        """Eng eski audiolarni o'chiradi. JSONL qatorlari QOLADI - ular
        kichkina va statistika uchun kerak, audio esa joy egallaydi."""
        files = sorted(self.audio_dir.glob("*.wav"))
        for path in files[:-self.max_files]:
            with contextlib.suppress(OSError):
                path.unlink()

"""Uyg'otish so'zi: "Salom Venera".

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

NAME = "venera"
#: Nomni tanish uchun ruxsat etilgan Levenshtein masofasi. Model bir xil
#: tovushni "venera", "vinera", "venira" deb yozadi.
NAME_DISTANCE = 2
#: Nomzod so'z uchun eng kam uzunlik: usiz masofa<=2 "vera", "era" kabi
#: keng tarqalgan qisqa so'zlarni ham nom deb qabul qilardi.
NAME_MIN_LEN = 5

#: O'zbekcha salomlar, "assalomu alaykum" bo'linadigan bo'laklari bilan.
GREETINGS = ("salom", "assalom", "assalomu", "alaykum", "aleykum", "salomlar",
             "salomatsizmi", "hello", "hey")

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


def _is_name(word: str) -> bool:
    """Shu so'z "venera" mi?

    Uzun so'z ichida ham qidiriladi: model ba'zan so'zlarni qo'shib yuboradi
    ("salomvenera"), va bunday holatda butun so'z bilan taqqoslash hech qachon
    mos kelmasdi.
    """
    if len(word) >= NAME_MIN_LEN and distance(word, NAME, NAME_DISTANCE) <= NAME_DISTANCE:
        return True
    if len(word) > len(NAME) + 2:
        for size in (len(NAME), len(NAME) + 1):
            if distance(word[-size:], NAME, 1) <= 1 or distance(word[:size], NAME, 1) <= 1:
                return True
    return False


def is_wake_phrase(text: str) -> tuple[bool, str]:
    """(uyg'otadimi, sabab). Sabab log uchun - "nega uyg'onmadi" degan savol
    aynan shu yerda javob topadi."""
    words = normalize_heard(text).split()
    if not words:
        return False, "bo'sh"
    if len(words) > MAX_WORDS:
        return False, f"juda uzun ({len(words)} so'z)"
    if not any(_is_name(word) for word in words):
        return False, "nom yo'q"
    if any(distance(word, greeting, 2) <= 2 for word in words for greeting in GREETINGS):
        return True, "salom + nom"
    if len(words) <= NAME_ONLY_WORDS:
        return True, "faqat nom (qisqa chaqiriq)"
    return False, "salom yo'q"


def measure(wav: bytes, *, floor: float = 0.015) -> tuple[float, float, float]:
    """WAV -> (eng baland nuqta, o'rtacha quvvat, nutq soniyalari).

    Bu SERVERDA hisoblanadi, klientdan so'ralmaydi: klient yuborgan raqamga
    ishonish uni tekshirib bo'lmaydigan qiladi, va aynan shu raqamlar
    keyinchalik qaror qabul qilishga asos bo'ladi.
    """
    try:
        with wave.open(io.BytesIO(wav)) as source:
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
        if source.getsampwidth() != 2 or not rate:
            return 0.0, 0.0, 0.0
        samples = array.array("h")
        samples.frombytes(frames[: len(frames) - len(frames) % 2])
    except (wave.Error, EOFError, ValueError):
        return 0.0, 0.0, 0.0
    if not samples:
        return 0.0, 0.0, 0.0

    peak = max(abs(s) for s in samples) / 32768
    total = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768

    # Nutq: 50 ms oynalar ichida chegaradan yuqori bo'lgan birinchi va
    # oxirgi oyna orasi. Jimlikni hisobga olmaydi.
    window = max(1, rate // 20)
    loud = [
        i for i in range(0, len(samples) - window, window)
        if math.sqrt(sum(s * s for s in samples[i:i + window]) / window) / 32768 > floor
    ]
    speech = ((loud[-1] + window) - loud[0]) / rate if loud else 0.0
    return peak, total, speech


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
        peak, rms, speech = measure(audio)
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

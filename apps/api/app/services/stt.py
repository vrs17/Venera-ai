"""STT Router klienti - ovozni matnga o'giradi.

Router `10.10.50.4:8006` da turadi va uchta narsani talab qiladi:
  * `multipart/form-data`, maydon nomi `file`
  * `language` MAJBURIY - avtomatik aniqlash YO'Q (uz | en | ru | zh)
  * bitta vaqtda BUTUN park uchun ~10 ta parallel so'rov

NEGA STDLIB `urllib`, `httpx` EMAS: `httpx` faqat test bog'liqligi
(`pyproject.toml` dagi `dev`). Ishlab chiqarish uchun yangi paket qo'shmaslik
uchun multipart qo'lda yig'iladi - desktop ilovasidagi `stt_onprem.py` ham
aynan shu yo'ldan boradi.

Bu modul BLOKLAYDI. Endpoint ataylab `async def` emas, oddiy `def` - FastAPI
uni threadpool'da ishlatadi va event loop to'silmaydi.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.request
import uuid

from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Router qo'llab-quvvatlaydigan tillar. Boshqasi yuborilsa 400.
LANGUAGES = ("uz", "en", "ru", "zh")

#: Frontend tillari -> STT tillari. OVOZ FAQAT UI TILIDA: foydalanuvchi
#: tizimda qaysi tilni tanlagan bo'lsa, STT ham shu tilda - avtomatik aniqlash
#: yoki almashtirish YO'Q (mahsulot qarori). `uz-Cyrl` alohida STT tili EMAS:
#: yozuv tizimi boshqa, til bir xil. Router `zh` ni ham biladi, lekin tizimda
#: xitoy tili yo'q - shuning uchun bu yerda ham yo'q (400 qaytadi).
LOCALE_TO_STT = {
    "uz": "uz",
    "uz-Cyrl": "uz",
    "uz-cyrl": "uz",
    "ru": "ru",
    "en": "en",
}

#: 503 = navbat to'la. Bu XATO EMAS, "keyinroq urin" degani.
_RETRYABLE = frozenset({502, 503, 504})
_BACKOFF_BASE = 0.4


class SttError(Exception):
    """`status` - klientga qaytariladigan HTTP kodi."""

    def __init__(self, message: str, *, status: int = 502, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class Transcript:
    text: str = ""
    language: str = ""
    backend: str = ""
    model: str = ""
    duration_sec: float = 0.0
    elapsed_sec: float = 0.0
    #: Audio Router limitidan uzun bo'lib KESILGAN (uz 300 s, boshqalar 600 s).
    truncated: bool = False
    #: Sifat bayroqlari FAQAT multilang (en/ru) backend'da bor; uz backend
    #: ularni `null` qaytaradi. Shuning uchun `is None` emas, ROSTLIK bo'yicha
    #: o'qiladi va bu yerda doim bool.
    low_confidence: bool = False
    #: Router "audio boshqa tilda" dedi. FAQAT LOG UCHUN: tizim tilni
    #: almashtirmaydi va bu klientga ham chiqmaydi. Log'da ko'rinishi esa
    #: foydali - "foydalanuvchilar UI tilida gapirmayapti" degan signal.
    language_mismatch: bool = False
    detected_language: str | None = None


def _multipart(file_bytes: bytes, filename: str, content_type: str, language: str) -> tuple[bytes, str]:
    """`multipart/form-data` tanasini qo'lda yig'adi."""
    boundary = f"----venera{uuid.uuid4().hex}"
    dash = f"--{boundary}".encode()
    lines: list[bytes] = [
        dash,
        b'Content-Disposition: form-data; name="language"',
        b"",
        language.encode(),
        dash,
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"'
        ).encode(),
        f"Content-Type: {content_type}".encode(),
        b"",
    ]
    body = b"\r\n".join(lines) + b"\r\n" + file_bytes + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class SttClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 150.0,
        attempts: int = 3,
        max_concurrent: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.attempts = max(1, attempts)
        # Router BUTUN park uchun ~10 parallel ko'taradi. Bu semafora shu
        # ilovaning ulushi: oshsa Router'ga bormasdan 503 qaytaramiz - Router
        # navbatini boshqa klientlar uchun to'ldirib qo'ymaslik uchun.
        self._slots = threading.BoundedSemaphore(max(1, max_concurrent))
        self.max_concurrent = max(1, max_concurrent)

    def transcribe(
        self,
        audio: bytes,
        *,
        language: str,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
    ) -> Transcript:
        """Audio -> matn, AYNAN so'ralgan tilda.

        Router hujjati `language_mismatch` da `detected_language` bilan qayta
        yuborishni tavsiya qiladi. Bu yerda ATAYLAB qilinmaydi: mahsulot
        qarori - ovoz foydalanuvchi tizimda tanlagan tilda ishlaydi, tizim
        tilni o'zi almashtirmaydi. Mismatch faqat log'ga tushadi.
        """
        if language not in LANGUAGES:
            raise SttError(f"til qo'llab-quvvatlanmaydi: {language}", status=400)
        if not audio:
            raise SttError("audio bo'sh", status=400)

        # Semafora: 2 s kutamiz (navbatdagi so'rov tez bo'shashi mumkin),
        # keyin taslim - Router 503 si bilan bir xil ma'noda.
        if not self._slots.acquire(timeout=2.0):
            raise SttError(
                f"ilova STT chegarasida ({self.max_concurrent} parallel)",
                status=503, retryable=True,
            )
        try:
            return self._with_retries(audio, filename, content_type, language)
        finally:
            self._slots.release()

    def _with_retries(self, audio: bytes, filename: str, content_type: str, language: str) -> Transcript:
        body, ctype = _multipart(audio, filename, content_type, language)
        last: SttError | None = None

        for attempt in range(self.attempts):
            try:
                return self._once(body, ctype)
            except SttError as exc:
                last = exc
                if not exc.retryable or attempt == self.attempts - 1:
                    raise
                # Jitter MAJBURIY: usiz bir vaqtda band bo'lgan klientlar
                # AYNAN bir vaqtda qayta urinadi va navbatni yana to'ldiradi.
                delay = _BACKOFF_BASE * (2 ** attempt) * (0.5 + random.random())
                log.warning("STT %s - %.1f s dan keyin qayta urinish (%d/%d)",
                            exc, delay, attempt + 1, self.attempts)
                time.sleep(delay)

        raise last or SttError("STT javob bermadi")

    def _once(self, body: bytes, content_type: str) -> Transcript:
        request = urllib.request.Request(
            f"{self.base_url}/transcribe",
            data=body,
            method="POST",
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        )
        # Ichki manzil korporativ proksi orqali KETMASLIGI kerak.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = exc.code
            detail = _detail(exc)
            raise SttError(
                f"STT xatosi {status}: {detail}",
                status=503 if status in _RETRYABLE else status,
                retryable=status in _RETRYABLE,
            ) from exc
        except urllib.error.URLError as exc:
            raise SttError(f"STT serveriga ulanib bo'lmadi: {exc.reason}",
                           status=503, retryable=True) from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise SttError(f"STT javobi o'qilmadi: {exc}", status=502, retryable=True) from exc

        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict) -> Transcript:
        """Router javobi -> Transcript. Alohida, chunki testlar Router'siz aynan
        hujjatdagi JSON shaklini shu yerga beradi."""
        detected = payload.get("detected_language")
        result = Transcript(
            text=str(payload.get("text") or "").strip(),
            language=str(payload.get("language") or ""),
            backend=str(payload.get("backend") or ""),
            model=str(payload.get("model") or ""),
            duration_sec=float(payload.get("duration_sec") or 0.0),
            elapsed_sec=float(payload.get("elapsed_sec") or 0.0),
            truncated=bool(payload.get("truncated")),
            low_confidence=bool(payload.get("low_confidence")),
            language_mismatch=bool(payload.get("language_mismatch")),
            detected_language=str(detected) if detected else None,
        )
        # `backend` hujjat bo'yicha debug uchun - qaysi servis ishlaganini
        # keyin faqat shu log'dan bilib bo'ladi.
        log.info("STT %s/%s: %.1fs audio, %.2fs, %d belgi%s%s%s",
                 result.backend or "?", result.model or "?", result.duration_sec,
                 result.elapsed_sec, len(result.text),
                 " LOW_CONF" if result.low_confidence else "",
                 " TRUNCATED" if result.truncated else "",
                 f" MISMATCH(eshitildi={result.detected_language or '?'})" if result.language_mismatch else "")
        return result


def _detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", "replace")[:300]
    except Exception:  # noqa: BLE001
        return exc.reason or ""
    try:
        return str(json.loads(raw).get("detail") or raw)
    except Exception:  # noqa: BLE001
        return raw

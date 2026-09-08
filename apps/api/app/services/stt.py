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
import time
import urllib.error
import urllib.request
import uuid

from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Router qo'llab-quvvatlaydigan tillar. Boshqasi yuborilsa 400.
LANGUAGES = ("uz", "en", "ru", "zh")

#: Frontend tillari -> STT tillari. `uz-Cyrl` alohida STT tili EMAS:
#: yozuv tizimi boshqa, til bir xil. Buni tashlab qo'ysak router 400 berardi.
LOCALE_TO_STT = {
    "uz": "uz",
    "uz-Cyrl": "uz",
    "uz-cyrl": "uz",
    "ru": "ru",
    "en": "en",
    "zh": "zh",
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
    duration_sec: float = 0.0
    #: Router `null` qaytarishi mumkin (uz backend aynan shunday qiladi),
    #: shuning uchun `is None` emas, ROSTLIK bo'yicha tekshiriladi.
    low_confidence: bool = False


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
        timeout: float = 30.0,
        attempts: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.attempts = max(1, attempts)

    def transcribe(
        self,
        audio: bytes,
        *,
        language: str,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
    ) -> Transcript:
        if language not in LANGUAGES:
            raise SttError(f"til qo'llab-quvvatlanmaydi: {language}", status=400)
        if not audio:
            raise SttError("audio bo'sh", status=400)

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

        return Transcript(
            text=str(payload.get("text") or "").strip(),
            language=str(payload.get("language") or ""),
            backend=str(payload.get("backend") or ""),
            duration_sec=float(payload.get("duration_sec") or 0.0),
            low_confidence=bool(payload.get("low_confidence")),
        )


def _detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", "replace")[:300]
    except Exception:  # noqa: BLE001
        return exc.reason or ""
    try:
        return str(json.loads(raw).get("detail") or raw)
    except Exception:  # noqa: BLE001
        return raw

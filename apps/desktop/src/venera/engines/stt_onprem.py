"""On-prem STT Router orqali ovozni matnga o'girish (Step 2).

Server shartnomasi (STT Router API):

    POST {base}/transcribe
    multipart/form-data:  file=<audio>  language=<uz|en|ru|zh>

`language` MAJBURIY va uni biz beramiz - `/detect-language` ISHLATILMAYDI.
Sabab ikkita: (1) u >=3 s audio talab qiladi, bizning buyruqlarimiz esa
("chromeni och") 1-2 s; (2) foydalanuvchi tilni sozlamalarda o'zi tanlaydi,
shuning uchun til allaqachon ma'lum. Har so'rovga qo'shimcha aniqlash so'rovi
serverga yukni ikki barobar oshirardi.

Nima uchun `requests` emas, `urllib`: butun kodbazada tashqi HTTP kutubxonasi
yo'q (`update/source.py` ham stdlib ishlatadi). Bitta POST uchun 3 MB lik
bog'liqlik va PyInstaller muammosi qo'shishga arzimaydi.

MUHIM tafsilotlar (server hujjatidan):
  * 503 = navbat to'lgan, XATO EMAS. Jitter bilan qayta urinamiz. Jitter
    shart: 50 ta kompyuter bir vaqtda 503 olib bir xil kutsa, ikkinchi to'lqin
    ham 503 bo'ladi (thundering herd).
  * Parallellik <=10 - butun park uchun. Bitta mashina buni yolg'iz yeb
    qo'ymasligi kerak, shuning uchun klientda ham semaphore va daqiqalik
    chegara bor: mikrofoni shovqinda qolgan bitta PC parkni yiqitmasin.
  * `uz` backend sifat maydonlarini `null` qaytaradi -> `is True` bilan emas,
    truthy tekshiruv bilan ishlash kerak.
  * HTTPS variantida sertifikat o'z-o'zidan imzolangan.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import ssl
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from .base import HealthStatus, SttEngine

log = logging.getLogger(__name__)

USER_AGENT = "Venera-AI-Assistant"

#: Server qabul qiladigan tillar. Boshqasini yuborsak 400 qaytadi.
LANGUAGES = ("uz", "en", "ru", "zh")

#: 503 va tarmoq uzilishida shuncha marta qayta urinamiz.
DEFAULT_ATTEMPTS = 3

#: Qayta urinishlar orasidagi asosiy kutish (soniya). Har urinishda ikkilanadi.
BACKOFF_BASE = 0.5


class SttError(Exception):
    """STT so'rovi bajarilmadi."""

    def __init__(self, message: str, *, retryable: bool = False, status: int = 0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class Transcript:
    """`/transcribe` javobining bizga keraklik qismi."""

    text: str = ""
    language: str = ""
    backend: str = ""
    duration_sec: float = 0.0
    elapsed_sec: float = 0.0
    #: `uz` backend bu maydonlarni null qaytaradi - shuning uchun default False.
    low_confidence: bool = False
    language_mismatch: bool = False
    detected_language: str = ""
    truncated: bool = False

    @classmethod
    def from_json(cls, data: dict) -> "Transcript":
        def number(key: str) -> float:
            value = data.get(key)
            return float(value) if isinstance(value, (int, float)) else 0.0

        return cls(
            text=str(data.get("text") or "").strip(),
            language=str(data.get("language") or ""),
            backend=str(data.get("backend") or ""),
            duration_sec=number("duration_sec"),
            elapsed_sec=number("elapsed_sec"),
            # null -> False (uzbek_stt backend sifat maydonlarini bermaydi)
            low_confidence=bool(data.get("low_confidence")),
            language_mismatch=bool(data.get("language_mismatch")),
            detected_language=str(data.get("detected_language") or ""),
            truncated=bool(data.get("truncated")),
        )


def encode_multipart(wav_bytes: bytes, language: str,
                     filename: str = "command.wav") -> tuple[bytes, str]:
    """`file` + `language` maydonlarini multipart/form-data ga o'raydi.

    Chegara (boundary) tasodifiy: audio ichida tasodifan uchrab qolmasligi kerak.
    """
    boundary = f"----VeneraBoundary{uuid.uuid4().hex}"
    dashes = f"--{boundary}\r\n".encode("ascii")
    body = bytearray()

    body += dashes
    body += b'Content-Disposition: form-data; name="file"; filename="'
    body += filename.encode("ascii", "ignore")
    body += b'"\r\nContent-Type: audio/wav\r\n\r\n'
    body += wav_bytes
    body += b"\r\n"

    body += dashes
    body += b'Content-Disposition: form-data; name="language"\r\n\r\n'
    body += language.encode("ascii")
    body += b"\r\n"

    body += f"--{boundary}--\r\n".encode("ascii")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class _RateLimiter:
    """Daqiqasiga N ta so'rov - buzilgan mashina parkni yiqitmasligi uchun.

    Server sig'imi BUTUN park uchun ~4-5 so'rov/s. Mikrofoni doimiy shovqinda
    qolgan bitta kompyuter cheksiz siklga tushsa, boshqa hamma uchun xizmatni
    o'ldiradi. Bu chegara shuni oldini oladi.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(0, int(per_minute))
        self._stamps: list[float] = []

    def allow(self) -> bool:
        if self.per_minute <= 0:      # 0 = chegara yo'q
            return True
        now = time.monotonic()
        self._stamps = [t for t in self._stamps if now - t < 60.0]
        if len(self._stamps) >= self.per_minute:
            return False
        self._stamps.append(now)
        return True


class OnpremStt(SttEngine):
    """STT Router klienti."""

    name = "onprem"

    def __init__(
        self,
        base_url: str,
        language: str = "uz",
        timeout: float = 30.0,
        attempts: int = DEFAULT_ATTEMPTS,
        no_proxy: bool = True,
        verify_tls: bool = False,
        max_concurrent: int = 2,
        max_per_minute: int = 20,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.language = language if language in LANGUAGES else "uz"
        self.timeout = max(1.0, float(timeout))
        self.attempts = max(1, int(attempts))
        self.no_proxy = bool(no_proxy)
        self.verify_tls = bool(verify_tls)
        # Bitta mashina serverning 10 lik parallellik byudjetining kichik
        # qismidan ko'pini olmasin.
        self._slots = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._limiter = _RateLimiter(max_per_minute)
        self._opener: urllib.request.OpenerDirector | None = None

    # --- sozlash -------------------------------------------------------------

    def set_language(self, language: str) -> None:
        """Foydalanuvchi UI dan tilni o'zgartirganda chaqiriladi."""
        if language in LANGUAGES and language != self.language:
            log.info("STT tili: %s -> %s", self.language, language)
            self.language = language

    @property
    def transcribe_url(self) -> str:
        return f"{self.base_url}/transcribe"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/health"

    # --- SttEngine -----------------------------------------------------------

    async def transcribe(self, wav_bytes: bytes) -> str:
        result = await self.transcribe_detailed(wav_bytes)
        return result.text

    async def transcribe_detailed(self, wav_bytes: bytes,
                                  language: str = "") -> Transcript:
        """To'liq javob - sifat bayroqlari bilan.

        Chaqiruvchi `low_confidence` va `language_mismatch` ni ko'rib qaror
        qabul qilishi mumkin (masalan "qayta ayting" deyish).
        """
        if not wav_bytes:
            return Transcript()
        if not self.base_url:
            raise SttError("STT manzili sozlanmagan (stt.url)")
        if not self._limiter.allow():
            raise SttError("juda ko'p so'rov - klient chegarasi", retryable=False)

        target = language if language in LANGUAGES else self.language
        async with self._slots:
            data = await self._post_with_retry(wav_bytes, target)
        result = Transcript.from_json(data)

        if result.truncated:
            log.warning("STT: audio kesildi (%.1f s)", result.duration_sec)
        if result.language_mismatch:
            # Bu ogohlantirish - foydalanuvchi noto'g'ri tilni tanlagan bo'lishi
            # mumkin. Avtomatik almashtirmaymiz: til foydalanuvchining qarori.
            log.warning("STT: audio %s tilida ko'rinadi, so'ralgan til %s",
                        result.detected_language or "noma'lum", target)
        if result.low_confidence:
            log.warning("STT: past ishonch - matn ishonchsiz: %r", result.text)
        log.info("STT: %r (%s, %.2f s)", result.text, result.backend, result.elapsed_sec)
        return result

    async def health(self) -> HealthStatus:
        """`--check` uchun. O'z timeout'i bor - bu yerda osilib qolmaslik shart."""
        if not self.base_url:
            return HealthStatus(False, "manzil sozlanmagan (stt.url)")
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._get, self.health_url, 8.0),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            return HealthStatus(False, f"javob bermadi: {self.base_url}")
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(False, f"{self.base_url} - {exc}")

        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return HealthStatus(True, f"{self.base_url} (javob o'qilmadi)")
        status = str(data.get("status") or "?")
        return HealthStatus(status == "ok", f"{self.base_url} - {status}, til={self.language}")

    async def close(self) -> None:
        self._opener = None

    # --- ichki qism ----------------------------------------------------------

    async def _post_with_retry(self, wav_bytes: bytes, language: str) -> dict:
        last: Exception | None = None
        for attempt in range(self.attempts):
            try:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(self._post, wav_bytes, language),
                    timeout=self.timeout,
                )
                return json.loads(raw.decode("utf-8", "replace"))
            except asyncio.CancelledError:
                # Foydalanuvchi bekor qildi - YUTMAYMIZ, orchestrator shunga tayanadi.
                raise
            except SttError as exc:
                last = exc
                if not exc.retryable or attempt == self.attempts - 1:
                    raise
            except asyncio.TimeoutError as exc:
                last = SttError(f"javob kutish vaqti tugadi ({self.timeout:.0f} s)")
                if attempt == self.attempts - 1:
                    raise last from exc
            except json.JSONDecodeError as exc:
                raise SttError(f"server javobi o'qilmadi: {exc}") from exc

            # Jitter MAJBURIY: aks holda 503 olgan hamma mashina bir vaqtda
            # qayta uradi va ikkinchi to'lqin ham 503 bo'ladi.
            delay = BACKOFF_BASE * (2 ** attempt) * (0.5 + random.random())
            log.info("STT qayta urinish %d/%d, %.1f s dan keyin (%s)",
                     attempt + 2, self.attempts, delay, last)
            await asyncio.sleep(delay)

        raise last or SttError("STT bajarilmadi")

    def _build_opener(self) -> urllib.request.OpenerDirector:
        if self._opener is not None:
            return self._opener
        handlers: list = []
        if self.no_proxy:
            # Server ichki tarmoqda (10.10.50.x) - korporativ proksi orqali
            # bormaydi.
            handlers.append(urllib.request.ProxyHandler({}))
        if not self.verify_tls:
            # HTTPS variantida sertifikat o'z-o'zidan imzolangan.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self._opener = urllib.request.build_opener(*handlers)
        return self._opener

    def _post(self, wav_bytes: bytes, language: str) -> bytes:
        """Bloklovchi POST - `to_thread` ichida chaqiriladi."""
        body, content_type = encode_multipart(wav_bytes, language)
        request = urllib.request.Request(
            self.transcribe_url,
            data=body,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": content_type,
                "Content-Length": str(len(body)),
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._open(request, self.timeout)

    def _get(self, url: str, timeout: float) -> bytes:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        return self._open(request, timeout)

    def _open(self, request: urllib.request.Request, timeout: float) -> bytes:
        opener = self._build_opener()
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except urllib.error.URLError as exc:
            # Tarmoq uzilishi - VPN uzilgan bo'lishi mumkin. Qayta urinishga arziydi.
            raise SttError(f"ulanmadi ({exc.reason})", retryable=True) from exc
        except OSError as exc:
            raise SttError(f"tarmoq xatosi ({exc})", retryable=True) from exc

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> SttError:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            detail = str(payload.get("detail") or "")
        except Exception:  # noqa: BLE001
            pass

        # 503 = navbat to'lgan (backpressure), nosozlik emas.
        # 502/504 = backend vaqtincha yo'q, bir urinishga arziydi.
        # 400/413 = bizning xatomiz, qayta urinish yordam bermaydi.
        retryable = exc.code in (502, 503, 504)
        if exc.code == 503:
            message = detail or "server band - navbat to'lgan"
        else:
            message = detail or f"server javobi {exc.code}"
        return SttError(message, retryable=retryable, status=exc.code)

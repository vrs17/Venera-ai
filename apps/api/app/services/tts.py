"""TTS klienti - matnni o'zbekcha ovozga o'giradi.

Server `10.10.50.4:8200` da turadi. STT Router'dan uchta jihati bilan farq
qiladi va shu farqlar bu modulning butun shaklini belgilaydi:

  1. AUTENTIFIKATSIYA BOR. `client_id`/`client_secret` -> 24 soatlik token.
     Token keshlanadi, aks holda har sintezdan oldin ortiqcha so'rov ketardi.
  2. GPU `Lock` OSTIDA, KETMA-KET. Bitta uvicorn ishchisi, bitta GPU: so'rovlar
     navbatda kutadi va server 429 QAYTARMAYDI - shunchaki javob kechikadi.
     Ya'ni ortiqcha yukni O'ZIMIZ to'xtatishimiz kerak (semafora), aks holda
     navbat cheksiz o'sadi va hamma timeout'ga uchraydi.
  3. AUDIO IKKINCHI SO'ROVDA. `generate` faqat yo'lni qaytaradi, faylni
     alohida olish kerak.

`urllib` STT klientidagi kabi - ishlab chiqarish uchun yangi paket qo'shilmaydi.
Modul BLOKLAYDI; endpoint ataylab oddiy `def` bo'lib, FastAPI uni threadpool'da
ishlatadi.
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass
from socket import timeout as socket_timeout

log = logging.getLogger(__name__)

#: Server bilgan ovozlar (`/health` -> `voice_profiles`).
VOICES = ("uz_female_calm", "uz_male_news")

#: Frontend tillari -> TTS. HOZIRCHA FAQAT O'ZBEK LOTIN. Model o'zbek uchun
#: o'rgatilgan; `uz-Cyrl` bu yerda ATAYLAB yo'q - kirill matn lotin o'quvchiga
#: berilsa harf-baharf noto'g'ri o'qiladi, translit esa alohida ish va u hali
#: qilinmagan. `ru`/`en` uchun bu serverda umuman ovoz yo'q.
LOCALE_TO_TTS = {"uz": "uz"}

#: Normalizator YIQILADIGAN naqshlar (jonli tekshirilgan, hujjatdagi jadval).
#: Bunday matnda normalizatsiyani O'ZIMIZ o'chiramiz: xato javobdan ko'ra
#: raqamni model o'zicha o'qigani afzal.
#:
#: 1) 16+ xonali raqam (karta, hisob raqami) -> HTTP 500. Ajratgichlar bilan
#:    yozilgani ham SHU YERGA kiradi: hujjat bo'yicha server bo'sh joy bilan
#:    ajratilgan guruhlarni bitta songa qo'shib yuboradi ("1234 567" ->
#:    1234567), ya'ni "8600 1234 5678 9012" ham o'sha 16 xonaga aylanadi.
_DIGIT_RUN = re.compile(r"\d[\d\s\u00a0.,-]{10,}\d")
#: 2) Nuqta bilan uch va undan ko'p guruh: `1.000.000`, `10.10.50.4`, `v1.2.3`
#:    -> HTTP 422. SANA BUNDAN MUSTASNO: `25.06.2026` hujjatda ISHLAYDIGAN
#:    holat, va uni ham tuzoq deb hisoblasak bitta sana butun gapdagi
#:    raqamlarni (`2450000 som`, `15%`) normalizatsiyasiz qoldirardi.
_DOTTED_GROUPS = re.compile(r"\d+(?:\.\d+){2,}")
_LOOKS_LIKE_DATE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")

#: Fayl nomi javobdan keladi, lekin URL'ga qo'yishdan oldin tekshiriladi:
#: `../../etc/passwd` ko'rinishidagi nom serverdan kelgan taqdirda ham
#: bizning so'rovimiz orqali kengaytirilib ketmasin.
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,120}\.wav$")


class TtsError(Exception):
    """`status` - klientga qaytariladigan HTTP kodi."""

    def __init__(self, message: str, *, status: int = 502, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class Speech:
    audio: bytes
    #: WAV, 8000 Hz, mono, 16-bit - telefoniya sifati, hi-fi emas.
    content_type: str = "audio/wav"
    duration_sec: float = 0.0
    #: Modelga AYNAN nima berilgani. Faqat log va debug uchun.
    normalized_text: str = ""
    voice: str = ""
    #: Matn chegaradan uzun bo'lib qisqartirilgan.
    truncated: bool = False


def risky_for_normalizer(text: str) -> bool:
    """Normalizator shu matnda yiqiladimi?

    ATAYLAB TOR: har bir noto'g'ri "ha" butun gapdagi raqamlarni
    normalizatsiyasiz qoldiradi, ya'ni ishlaydigan holatlarni ham buzadi.
    """
    for run in _DIGIT_RUN.finditer(text):
        if len(re.sub(r"\D", "", run.group())) >= 16:
            return True
    return any(
        not _LOOKS_LIKE_DATE.match(match.group())
        for match in _DOTTED_GROUPS.finditer(text)
    )


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Matnni chegaraga sig'diradi, so'z chegarasida.

    NEGA XATO EMAS: matn foydalanuvchi endigina AYTGAN gapi. "Juda uzun"
    deyish o'rniga boricha o'qib berish tushunarliroq - ayniqsa GPU ketma-ket
    ishlaganda, uzun matn butun navbatni ushlab turadi.
    """
    text = text.strip()
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-"), True


class TtsClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        timeout: float = 60.0,
        max_concurrent: int = 2,
        queue_wait: float = 1.0,
        deadline: float = 100.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.max_concurrent = max(1, max_concurrent)
        self.queue_wait = queue_wait
        self.deadline = deadline
        self._slots = threading.BoundedSemaphore(self.max_concurrent)
        self._token_lock = threading.Lock()
        self._token: str | None = None
        self._token_expires = 0.0

    # --- token ---------------------------------------------------------

    @property
    def configured(self) -> bool:
        """Sir berilganmi. Berilmagan bo'lsa endpoint 503 qaytaradi - ovoz
        sintezi ixtiyoriy imkoniyat, usiz ham butun ilova ishlaydi."""
        return bool(self.client_id and self.client_secret)

    def _fetch_token(self) -> str:
        body = json.dumps(
            {"client_id": self.client_id, "client_secret": self.client_secret}
        ).encode("utf-8")
        payload = self._json_request("/api/v1/auth/token", body=body, authorized=False)
        token = str(payload.get("access_token") or "")
        if not token:
            raise TtsError("TTS tokeni bo'sh keldi", status=502)
        # 60 s zaxira: uzoq sintez o'rtasida token eskirib qolmasin. Zaxira
        # TTL dan katta bo'lsa kesh muddati NOLGA emas, 30 s ga tushadi -
        # `max(60, ttl) - 60` nol berardi va har so'rov token so'rardi.
        ttl = float(payload.get("expires_in") or 3600)
        self._token = token
        self._token_expires = time.time() + max(30.0, ttl - 60.0)
        log.info("TTS: yangi token olindi (%.0f s)", ttl)
        return token

    def _valid_token(self) -> str:
        # Qulf butun blokni qamraydi: usiz bir vaqtda kelgan ikki so'rov
        # ikkita token so'rardi va ikkinchisi birinchisini almashtirib
        # yuborardi - zararsiz, lekin serverga ortiqcha yuk.
        with self._token_lock:
            if self._token and time.time() < self._token_expires:
                return self._token
            return self._fetch_token()

    def _drop_token(self) -> None:
        with self._token_lock:
            self._token = None
            self._token_expires = 0.0

    # --- sintez ---------------------------------------------------------

    def synthesize(
        self,
        text: str,
        *,
        user_id: str,
        voice: str = "uz_female_calm",
        speed: float | None = None,
        normalize_numbers: bool = True,
        max_chars: int = 600,
    ) -> Speech:
        """Matn -> WAV baytlari.

        `user_id` FAYL NOMIGA kiradi va server fayllarni hech qachon
        o'chirmaydi, shuning uchun bu yerga email yoki telefon EMAS, faqat
        ichki raqamli id beriladi.
        """
        if not self.configured:
            # 503 EMAS: 503 "band, keyinroq urinib ko'ring" degani va klientni
            # cheksiz qayta urinishga chorlaydi. Sozlanmagan xizmat esa
            # kutish bilan tuzalmaydi - 501 "hali yoqilmagan".
            raise TtsError("TTS sozlanmagan (client_secret yo'q)", status=501)
        if voice not in VOICES:
            raise TtsError(f"noma'lum ovoz: {voice}", status=400)
        clean, truncated = clip(text, max_chars)
        if not clean:
            raise TtsError("matn bo'sh", status=400)

        # Normalizator ba'zi raqamlarda yiqiladi - bunday matnni OLDINDAN
        # tanib, normalizatsiyasiz yuboramiz (500/422 dan ko'ra shu yaxshi).
        if normalize_numbers and risky_for_normalizer(clean):
            log.info("TTS: xavfli raqam naqshi - normalize_numbers o'chirildi")
            normalize_numbers = False

        if not self._slots.acquire(timeout=self.queue_wait):
            # Server bitta GPU'da KETMA-KET ishlaydi va 429 qaytarmaydi:
            # navbatni o'zimiz cheklamasak, u cheksiz o'sadi.
            raise TtsError(
                f"ilova TTS chegarasida ({self.max_concurrent} parallel)",
                status=503, retryable=True,
            )
        # Devor-soat. BITTA so'rov uchun timeout YETMAYDI: `/speak` ikkita
        # KETMA-KET so'rov qiladi (generate, keyin faylni olish), ya'ni
        # 60 s + 60 s = 120 s - nginx aynan 120 s da uzadi va javob brauzerga
        # yetib bormaydi, slot esa hali band turadi. Shuning uchun ikkinchi
        # so'rovga qolgan byudjet beriladi.
        started = time.monotonic()
        try:
            payload = self._generate(clean, user_id, voice, speed, normalize_numbers)
            audio = self._download(payload, self._left(started))
        finally:
            self._slots.release()

        return Speech(
            audio=audio,
            duration_sec=float(payload.get("duration_sec") or 0.0),
            normalized_text=str(payload.get("normalized_text") or clean),
            voice=voice,
            truncated=truncated,
        )

    def _left(self, started: float) -> float:
        """Byudjetdan qolgan vaqt. Tugagan bo'lsa 504 - kutishning ma'nosi
        yo'q, javobni endi hech kim ko'rmaydi."""
        remaining = self.deadline - (time.monotonic() - started)
        if remaining < 1.0:
            raise TtsError("TTS byudjeti tugadi", status=504)
        return min(self.timeout, remaining)

    def _generate(
        self,
        text: str,
        user_id: str,
        voice: str,
        speed: float | None,
        normalize_numbers: bool,
    ) -> dict:
        body = json.dumps(
            {
                "user_id": user_id,
                # Server majburiy qiladi, lekin bizda telefon yo'q va kerak
                # ham emas - u faqat javobga qaytadi (passthrough).
                "phone": "-",
                "text": text,
                "voice_profile": voice,
                "speed": speed,
                "normalize_numbers": normalize_numbers,
            }
        ).encode("utf-8")
        payload = self._json_request("/api/v1/tts/generate", body=body)
        status = str(payload.get("status") or "")
        if status and status != "success":
            raise TtsError(f"TTS: {payload.get('error') or status}", status=502)
        log.info("TTS: %.2f s audio, ovoz=%s, normalize=%s",
                 float(payload.get("duration_sec") or 0.0), voice, normalize_numbers)
        return payload

    def _download(self, payload: dict, timeout: float) -> bytes:
        """Aynan shu sintezning faylini oladi.

        JAVOBDAGI `download_url` ISHLATILMAYDI. U `user_id` bo'yicha ENG
        SO'NGGI faylni beradi, ya'ni ikki so'rov bir vaqtda ketsa (yoki bitta
        batch ichida bir xil `user_id` ikki marta bo'lsa) ikkalasi ham bitta
        faylga ishora qiladi va kimdir boshqasining audiosini eshitadi.
        `audio_path` dagi nom esa har sintez uchun UNIKAL (`{user_id}__{uuid}`).
        """
        raw = str(payload.get("audio_path") or "")
        filename = raw.rsplit("/", 1)[-1]
        if not _SAFE_FILENAME.match(filename):
            raise TtsError(f"TTS fayl nomi kutilmagan: {filename[:60]!r}", status=502)
        data = self._raw_request(f"/api/v1/tts/file/{urllib.parse.quote(filename)}", timeout)
        if not data:
            raise TtsError("TTS bo'sh fayl qaytardi", status=502)
        return data

    # --- transport ------------------------------------------------------

    def _json_request(self, path: str, *, body: bytes | None = None, authorized: bool = True) -> dict:
        raw = self._send(path, body=body, authorized=authorized, accept="application/json")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TtsError(f"TTS javobi o'qilmadi: {exc}", status=502) from exc
        # Tur tekshiruvi MAJBURIY: 200 bilan `null`, `[]` yoki satr kelsa
        # keyingi `.get()` AttributeError berardi, u esa TtsError EMAS va
        # butun so'rovni 500 ga aylantirardi.
        if not isinstance(payload, dict):
            raise TtsError(f"TTS javobi kutilmagan turda: {type(payload).__name__}", status=502)
        return payload

    def _raw_request(self, path: str, timeout: float | None = None) -> bytes:
        return self._send(path, body=None, authorized=True, accept="*/*", timeout=timeout)

    def _send(self, path: str, *, body: bytes | None, authorized: bool, accept: str,
              timeout: float | None = None) -> bytes:
        """Bitta so'rov. 401 da token bir marta yangilanib qayta yuboriladi.

        NEGA QAYTA URINISH SHU YERDA: token 24 soat yashaydi, ya'ni u
        odatda so'rovlar ORASIDA eskiradi. Server qayta ishga tushsa ham
        (imzo kaliti yangilansa) eski token yaroqsiz bo'ladi. Ikkala holatda
        ham foydalanuvchi buni ko'rmasligi kerak.
        """
        for attempt in (0, 1):
            headers = {"Accept": accept}
            if body is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(body))
            if authorized:
                headers["Authorization"] = f"Bearer {self._valid_token()}"
            try:
                return self._open(path, body, headers, timeout or self.timeout)
            except TtsError as exc:
                if exc.status == 401 and authorized and attempt == 0:
                    log.info("TTS: token rad etildi, yangilanmoqda")
                    self._drop_token()
                    continue
                raise
        raise TtsError("TTS javob bermadi", status=502)

    def _open(self, path: str, body: bytes | None, headers: dict[str, str],
              timeout: float | None = None) -> bytes:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method="POST" if body is not None else "GET",
            headers=headers,
        )
        # Ichki manzil korporativ proksi orqali KETMASLIGI kerak.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout or self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            # Sir REDAKSIYA qilinadi: server 422 da so'rov tanasini o'zicha
            # qaytarishi mumkin (FastAPI validatsiya xatosi `input` ni aynan
            # ko'chiradi), va u token so'rovi tanasi - ya'ni `client_secret`.
            # U yerdan xabar log'ga va keyin xato zanjiriga tushardi.
            detail = _redact(_detail(exc), self.client_secret)
            # 401 yuqorida tutiladi (token yangilash). 422 - matn
            # normalizatordan o'tmadi, 500 - GPU/model xatosi: ikkalasi ham
            # qayta urinishdan tuzalmaydi.
            mapped = status if status in (400, 401, 403, 422, 503) else 502
            raise TtsError(f"TTS {status}: {detail}", status=mapped) from exc
        except urllib.error.URLError as exc:
            raise TtsError(f"TTS serveriga ulanib bo'lmadi: {exc.reason}",
                           status=503, retryable=True) from exc
        except (TimeoutError, socket_timeout) as exc:
            raise TtsError("TTS javob bermadi (timeout)", status=504) from exc
        except (http.client.HTTPException, OSError) as exc:
            raise TtsError(f"TTS ulanishi uzildi: {exc}", status=503, retryable=True) from exc


def _redact(text: str, secret: str) -> str:
    """Sirni xato matnidan olib tashlaydi. Ikki belgidan uzun sir uchun -
    qisqa qiymat tasodifiy mos kelib, matnni buzib yuborishi mumkin."""
    return text.replace(secret, "***") if secret and len(secret) > 2 else text


def _detail(exc: urllib.error.HTTPError) -> str:
    """`{"detail": "..."}` dan matn. Sir HECH QACHON bu yerga tushmaydi -
    faqat server javobi o'qiladi."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return str(exc.reason or "")
    try:
        text = str(json.loads(raw).get("detail") or raw)
    except Exception:  # noqa: BLE001
        text = raw
    return text[:300]

"""GAPI STT - ikkinchi variant (console.gapi.uz).

BIRINCHI VARIANT QOLADI. Ichki STT Router (`services/stt.py`) hech qayerga
ketmaydi: bu modul uning O'RNINI EMAS, YONINI oladi. Tanlov `.env` dagi
`STT_PROVIDER` bilan qilinadi, ya'ni orqaga qaytarish bitta qatorni
o'chirish va xizmatni qayta ishga tushirish - kod o'zgarmaydi.

INTERFEYS ATAYLAB BIR XIL: `transcribe(audio, language=..., content_type=...)`
-> `Transcript`, xatolar esa `SttError`. Shu sababli `api/v1/stt.py` dagi
endpoint mantiqi - navbat, jurnal, uyg'otish qarori - umuman tegilmaydi.

FAQAT O'ZBEK TILI. GAPI o'zbek uchun qilingan va matnni FAQAT LOTIN
yozuvida qaytaradi. `ru`/`en`/`zh` uchun unda umuman model yo'q, shuning
uchun tanlovchi (`api/v1/stt.py`) bu tillarni baribir Router'ga yuboradi -
ya'ni GAPI ga o'tish rus yoki ingliz interfeysini buzmaydi.

NARX TUZOG'I - ENG MUHIM DETAL. Yangi loyihada `emotion` va `pii`
YOQIQ turadi va har bir yozuv ×2.2 tarifga tushadi, ya'ni ikki
barobardan qimmat. Biz ularni HAR SO'ROVDA ataylab `false` qilib
yuboramiz (`_SETTINGS`). Bizga na hissiyot, na shaxsiy ma'lumot
belgilash kerak - bizga bitta gapning matni kerak.

NOTO'G'RI SOZLAMA KALITI butun yuklashni rad etadi (`400 unknown_setting`).
Shuning uchun `_SETTINGS` da faqat hujjatda nomi aytilgan uchta kalit bor
va ular qo'lda yoziladi, foydalanuvchidan kelmaydi.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from typing import Any

from ..stt import SttError, Transcript, safe_filename

log = logging.getLogger(__name__)

#: Yig'ilish vazifasi uchun fayl nomi - kontent turidan (GAPI formatni kengaytmadan ham taniydi).
_MEETING_FILENAMES = {"audio/aac": "meeting.aac", "audio/mp4": "meeting.m4a", "audio/mpeg": "meeting.mp3",
                      "audio/wav": "meeting.wav", "audio/ogg": "meeting.ogg"}

#: Har so'rovda yuboriladigan sozlamalar - loyiha sozlamalari USTIDAN.
#:
#: `emotion`/`pii` - narx tuzog'i (yuqoridagi izohga qara). `diarization`
#: esa bizga keraksiz: biz bitta odamning bitta gapini o'giramiz, so'zlovchi
#: ajratish bo'sh ish va natijani chalkashtiradi.
_SETTINGS = {"diarization": False, "emotion": False, "pii": False}

#: LUG'AT YUBORILMAYDI - O'LCHANGAN QAROR.
#:
#: GAPI `vocabulary` maydonini qabul qiladi (1-20 atama) va u domen
#: so'zlarini tuzatishi kutilardi. Jonli o'lchov (2026-09-22) buni
#: TASDIQLAMADI: `["Venera","task","tasklar","CRM","HRM","DVSIB",...]`
#: bilan va usiz natija AYNAN BIR XIL chiqdi ("tasklarim" -> "darslarim"
#: ikkalasida ham), lekin so'rov 2-4 BAROBAR sekinlashdi: 1.19 s -> 4.51 s.
#:
#: Ya'ni bu yerda lug'at faqat kechikish qo'shadi. Qayta sinab ko'rmoqchi
#: bo'lsangiz - avval o'lchang, keyin qo'shing.

#: Qayta urinish MUMKIN bo'lgan HTTP kodlari (hujjat: "kutib qayta urinish
#: mumkin"). Qolganlari yo so'rovni tuzatishni talab qiladi (400/401/413/422),
#: yo umuman qaytmaydi (404/410) - ularni takrorlash zarar.
_RETRYABLE = {409, 429, 503, 507}

#: `/transcribe` 3 daqiqada ulgurmasa natija o'rniga `202` va `job_id`
#: qaytaradi. Bizning bo'laklar 30 sekunddan qisqa, ya'ni bu amalda
#: bo'lmaydi - lekin hujjat aytgan holat va uni ishlov bermaslik
#: "javobda segments topilmadi" degan tushunarsiz xatoga olib kelardi.
_POLL_EVERY = 2.0

#: Kalit jurnalga tushmasligi uchun - `Bearer` dan keyingi hamma narsa.
_KEY_LIKE = "gapi_"

#: Kalitning balansi tugadi - GAPI `429 insufficient_balance` (`docs/plans/meeting-recorder.md`).
_NO_BALANCE = "insufficient_balance"

#: Balansi tugagan kalit shuncha vaqt CHETLAB o'tiladi, keyin yana sinaladi - lekin Toshkent
#: yarim kechasidan (kunlik to'ldirish) kechiktirilmaydi. Oraliq qisqa, chunki balans kun
#: o'rtasida ham qaytishi mumkin: yo'ldagi vazifalar band qilgan qism bo'shaydi yoki hisob
#: qo'lda to'ldiriladi. Rad etilgan so'rov esa darhol qaytadi.
_EMPTY_RECHECK_SEC = 30 * 60

#: Kunlik balans Toshkent vaqti bilan to'ldiriladi. `zoneinfo` emas, QAT'IY +5: O'zbekistonda
#: yozgi vaqt yo'q, va bu `tzdata` paketiga bog'liq bo'lmaydi.
_TASHKENT = timezone(timedelta(hours=5))


def out_of_balance(exc: BaseException) -> bool:
    """Xato "shu kalitning balansi yetmaydi" degani (`429 insufficient_balance`)."""
    return getattr(exc, "gapi_code", "") == _NO_BALANCE


def _safe(text: str, key: str = "") -> str:
    """Matndan API kalitini olib tashlaydi.

    IKKI TO'R, va tartibi muhim:

      1. `key` - SOZLANGAN kalitning aynan o'zi. Asosiy himoya shu:
         qiymatni bilib turib olib tashlash taxminga bog'liq emas.
      2. `gapi_` prefiksi - ikkinchi to'r. Bu faqat EVRISTIKA: kalit shu
         prefiks bilan boshlanishiga tayanadi. Bugungi kalit shunday, lekin
         xizmat formatini o'zgartirsa bu to'r JIMGINA ishlamay qoladi -
         shuning uchun u yolg'iz qolmasligi kerak.
    """
    if not text:
        return ""
    if key:
        text = text.replace(key, "<key>")
    if _KEY_LIKE not in text:
        return text
    return " ".join("<key>" if _KEY_LIKE in word else word for word in text.split())


def _multipart(audio: bytes, filename: str, content_type: str,
               settings: dict[str, Any] | None = None) -> tuple[bytes, str]:
    """`file` + `settings` - boshqa hech narsa. `settings` berilmasa - chat diktovkasiniki (`_SETTINGS`).

    `language` maydoni ATAYLAB YUBORILMAYDI: GAPI o'zbek uchun bitta
    model, va hujjatda bunday maydon yo'q. Noma'lum narsa yuborish esa
    bu API da butun yuklashni rad etishga olib kelishi mumkin.
    """
    boundary = f"----venera{uuid.uuid4().hex}"
    head = f"--{boundary}\r\n".encode()
    body = bytearray()
    body += head
    body += (f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f"Content-Type: {content_type}\r\n\r\n").encode()
    body += audio
    body += b"\r\n"
    body += head
    body += b'Content-Disposition: form-data; name="settings"\r\n\r\n'
    body += json.dumps(_SETTINGS if settings is None else settings).encode()
    body += f"\r\n--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


#: YIG'ILISH sozlamalari (`services/meetings/`). Chat diktovkasining
#: `_SETTINGS` iga TEGILMAYDI - u boshqa vazifa (bitta odamning bitta gapi).
#:
#: HAR KALIT ATAYLAB YOZILGAN. Yuborilmagan kalit GAPI loyihasining
#: sozlamasidan olinadi, yangi loyihada esa pullik va BIOMETRIK opsiyalar
#: yoqiq turadi: `speaker_identification` - ovoz izi (biometrik ma'lumot,
#: rozilik kerak), `emotion`/`pii` - narx x2.2 tuzog'i (modul izohi),
#: `gender` - odam haqida taxmin. Bizga faqat "kim qachon gapirdi" kerak:
#: `diarization`. `max_speakers` - 0 (model o'zi aniqlaydi) yoki
#: `meeting_settings()` dagi kutilgan son (GAPI 4 dan ortig'ini ajratmaydi).
#: Testi: `tests/test_gapi_meeting.py` - kalitlar to'plami aynan shu.
_MEETING_SETTINGS = {"diarization": True, "max_speakers": 0, "speaker_roles": False,
                     "call_outcome": False, "stereo_channels_as_speakers": False,
                     "speaker_identification": False, "gender": False,
                     "language_detection": True, "word_timestamps": False,
                     "emotion": False, "pii": False}

#: GAPI ajrata oladigan eng ko'p ovoz.
MAX_MEETING_SPEAKERS = 4


def meeting_settings(expected_speakers: int | None = None, *, identify: bool = False) -> dict[str, Any]:
    """Yig'ilish uchun sozlamalar NUSXASI; `max_speakers` = min(kutilgan, 4).

    `identify` - "ovoz bo'yicha tanish" (`speaker_identification`, ega qarori 2026-11-18: hamma xodim rozi).
    GAPI har spikerning ovoz izini loyihadagi ovozlar bilan solishtiradi: tanish ovoz o'z doimiy raqamini oladi,
    10 s dan ko'p gapirgan yangi ovoz ro'yxatga olinadi (mehmon ham - ega talabi: ovozi saqlansin, ID bo'lsin,
    ismi bo'lmasin). Tarif o'zgarmaydi (x1). `enroll` ATAYLAB yuborilmaydi - GAPI'ning standarti (`auto`)."""
    out = dict(_MEETING_SETTINGS)
    if expected_speakers:
        out["max_speakers"] = max(1, min(int(expected_speakers), MAX_MEETING_SPEAKERS))
    if identify:
        out["speaker_identification"] = True
    return out


#: OVOZ NAMUNASI sozlamalari (`services/meetings/voice.py`): xodim yozgan ~45 s lik namuna sinxron
#: `/transcribe` ga. `diarization` - namunada BIR odam ekanini tekshirish uchun (ikkinchi ovoz bo'lsa
#: rad etiladi), `speaker_identification` - ovoz izi va loyihadagi ovoz bilan solishtirish. Qolganlari
#: yig'ilishdagidek ATAYLAB o'chiq (narx va ortiqcha taxmin). Kalitlar yig'ilishnikidan olinadi: GAPI
#: noma'lum kalitni `400 unknown_setting` bilan rad etadi.
_SAMPLE_SETTINGS = {**_MEETING_SETTINGS, "diarization": True, "max_speakers": 0, "speaker_identification": True,
                    "language_detection": False}


class _StreamBody:
    """`multipart/form-data` tanasi - fayl DISKDAN bo'laklab o'qiladi.

    NEGA. 3 soatlik yozuv ~65 MB. `_multipart` uni xotiraga butunligicha
    yig'ardi: server 3 GB RAM, ustida jonli Venera turadi, va ikkita
    yig'ilish bir vaqtda yuborilsa xotira bir lahzada 130+ MB ga sakraydi.
    Bu yerda xotirada faqat bosh va oxir (bir necha yuz bayt) turadi,
    `Content-Length` esa oldindan hisoblanadi (bosh + fayl + oxir) -
    urllib bo'laklangan uzatishga o'tmaydi.

    `http.client` tanani `read(blocksize)` bilan o'qiydi.
    """

    def __init__(self, head: bytes, path: Path, tail: bytes, *, chunk: int = 64 * 1024) -> None:
        self._head = head
        self._tail = tail
        self._path = Path(path)
        self._chunk = max(1024, int(chunk))
        self._stage = 0
        self._pos = 0
        self._fh = None
        self.length = len(head) + self._path.stat().st_size + len(tail)
        #: Eng katta bitta o'qish (testlar "fayl butunligicha o'qilmadi" deb tekshiradi).
        self.max_read = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0 or size > self._chunk:
            size = self._chunk
        while True:
            if self._stage == 0:
                if self._pos < len(self._head):
                    data = self._head[self._pos:self._pos + size]
                    self._pos += len(data)
                    return data
                self._stage, self._pos = 1, 0
                self._fh = open(self._path, "rb")
            if self._stage == 1:
                data = self._fh.read(size)
                if data:
                    self.max_read = max(self.max_read, len(data))
                    return data
                self._fh.close()
                self._fh = None
                self._stage, self._pos = 2, 0
            if self._stage == 2:
                if self._pos < len(self._tail):
                    data = self._tail[self._pos:self._pos + size]
                    self._pos += len(data)
                    return data
                self._stage = 3
            return b""

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def _multipart_stream(path: Path, filename: str, content_type: str,
                      settings: dict[str, Any]) -> tuple[_StreamBody, str]:
    """`file` + `settings` - `_multipart` bilan bir xil shakl, lekin oqimli."""
    boundary = f"----venera{uuid.uuid4().hex}"
    head = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="settings"\r\n\r\n'
            f"{json.dumps(settings)}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return _StreamBody(head, path, tail), f"multipart/form-data; boundary={boundary}"


@dataclass
class MeetingTranscript:
    """GAPI vazifa natijasi - XOM shaklda (normallashtirish:
    `services/meetings/transcribe.normalize`)."""

    segments: list[dict[str, Any]] = field(default_factory=list)
    audio_seconds: float = 0.0
    language: Any = None
    diarization_error: bool = False
    speakers: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)
    #: "Ovoz bo'yicha tanish" yoqiq bo'lsa: har spiker xulosasi (`identity` - kim ekani) va
    #: "yozuv spikeri -> loyiha ovozi" bog'lanishi. Ovoz izining O'ZI javobda hech qachon yo'q.
    speaker_info: list[dict[str, Any]] = field(default_factory=list)
    voices: list[dict[str, Any]] = field(default_factory=list)


def parse_meeting_result(payload: Any) -> MeetingTranscript:
    """`GET /jobs/{id}/result` javobi -> `MeetingTranscript`. Hech qachon xato bermaydi:
    hujjatda yo'q shakl kelsa ham bo'sh ro'yxat qaytadi, va ishchi buni
    "segment yo'q" deb aniq aytadi."""
    if not isinstance(payload, dict):
        return MeetingTranscript()
    # Ba'zi javoblar natijani `result` ichiga o'raydi.
    if not isinstance(payload.get("segments"), list) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    segments = [s for s in (payload.get("segments") or []) if isinstance(s, dict)]
    try:
        audio_seconds = float(payload.get("audio_seconds") or payload.get("duration") or 0.0)
    except (TypeError, ValueError):
        audio_seconds = 0.0
    speakers = payload.get("speakers")
    if isinstance(speakers, list):
        speakers = len(speakers)
    return MeetingTranscript(
        segments=segments,
        audio_seconds=audio_seconds,
        language=payload.get("language"),
        diarization_error=bool(payload.get("diarization_error")),
        speakers=speakers if isinstance(speakers, int) and not isinstance(speakers, bool) else None,
        options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
        keys=sorted(str(k) for k in payload.keys()),
        speaker_info=[s for s in (payload.get("speaker_info") or []) if isinstance(s, dict)]
        if isinstance(payload.get("speaker_info"), list) else [],
        voices=[v for v in (payload.get("voices") or []) if isinstance(v, dict)]
        if isinstance(payload.get("voices"), list) else [],
    )


class GapiSttClient:
    """`console.gapi.uz` ustidagi klient. `SttClient` bilan bir xil yuz.

    IKKI HISOB. Har GAPI hisobining o'z kunlik balansi bor (480 g). `api_key2`
    (`GAPI_API_KEY2`) berilsa, birinchi kalitning balansi tugaganda so'rov darhol
    ikkinchisiga ketadi, birinchisi esa `_EMPTY_RECHECK_SEC` davomida chetlab
    o'tiladi - yarim kechada to'lgach yana birinchisi ishlatiladi. Hisob raqami:
    1 - `GAPI_API_KEY`, 2 - `GAPI_API_KEY2`. Yig'ilish vazifasi QAYSI hisobda
    yaratilgan bo'lsa, holati va natijasi ham o'sha kalit bilan so'raladi
    (`account=`): boshqa hisob uchun u vazifa yo'q.
    """

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 60.0,
                 max_concurrent: int = 2, deadline: float = 100.0,
                 attempts: int = 2, api_key2: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._api_key2 = api_key2 or ""
        self.timeout = timeout
        self.max_concurrent = max(1, max_concurrent)
        self.deadline = deadline
        self.attempts = max(1, attempts)
        self._slots = threading.BoundedSemaphore(self.max_concurrent)
        # KUNLIK SARF. Xizmat audio daqiqasi uchun pul oladi (kunlik 480)
        # va kvota tugaganda foydalanuvchi buni XATO ko'rinishida biladi -
        # ya'ni eng kech payt. Jurnalda har so'rov bor, lekin hech narsa
        # ularni QO'SHMAYDI; bu hisoblagich `/api/health/detail` da
        # ko'rinadi, ya'ni kvota tugashi oldindan sezilади.
        #
        # Kun chegarasi Toshkent vaqti bilan (xizmat 00:00 Asia/Tashkent
        # da to'ldiradi). `zoneinfo` emas, QAT'IY +5: O'zbekistonda yozgi
        # vaqt yo'q, va bu `tzdata` paketiga bog'liq bo'lmaydi.
        self._spend_lock = threading.Lock()
        self._spend_day = ""
        self._spend_sec = 0.0
        self._spend_calls = 0
        # YUBORILGAN urinishlar - javob kelmaganlari ham.
        #
        # O'lchangan: chegaradan oshgan portlashda 40 so'rovdan 8 tasi javob
        # berdi, lekin hisobdan ~34 tasining puli ketdi. Ya'ni faqat
        # muvaffaqiyatli javoblarni qo'shish sarfni KAM ko'rsatadi - aynan
        # hamma narsa buzilgan paytda, ya'ni ogohlantirish eng kerak
        # bo'lganda. Bu ikki son orasidagi farq "pul ketdi, natija yo'q"
        # degan signal.
        self._spend_sent = 0
        # Balansi tugagan hisoblar: raqam -> shu vaqtgacha chetlab o'tiladi. `_warned` - qaysi
        # kuni jurnalga ogohlantirish yozilgani (har 30 daqiqalik qayta tekshiruvda emas).
        self._empty_lock = threading.Lock()
        self._empty: dict[int, float] = {}
        self._warned: dict[int, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.accounts)

    # --- hisoblar (kalitlar) ------------------------------------------------

    def _key_of(self, account: int) -> str:
        return self._api_key if account == 1 else self._api_key2 if account == 2 else ""

    @staticmethod
    def _name(account: int) -> str:
        return "GAPI_API_KEY" if account == 1 else f"GAPI_API_KEY{account}"

    @property
    def accounts(self) -> list[int]:
        """Sozlangan hisoblar, ishlatilish tartibida."""
        return [n for n in (1, 2) if self._key_of(n)]

    def usable_accounts(self) -> list[int]:
        """Sozlangan va balansi tugagan deb belgilanmagan hisoblar."""
        now = time.time()
        with self._empty_lock:
            return [n for n in self.accounts if self._empty.get(n, 0.0) <= now]

    def mark_out_of_balance(self, account: int) -> None:
        """Shu hisobning balansi tugadi - keyingi so'rovlar boshqa kalitga."""
        now, day = time.time(), self._today()
        midnight = datetime.now(_TASHKENT).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        with self._empty_lock:
            self._empty[account] = min(midnight.timestamp(), now + _EMPTY_RECHECK_SEC)
            first = self._warned.get(account) != day
            self._warned[account] = day
        rest = [n for n in self.usable_accounts() if n != account]
        (log.warning if first else log.info)(
            "GAPI: %s balansi tugadi - %s", self._name(account),
            f"{self._name(rest[0])} ishlatiladi" if rest else "boshqa kalit yo'q")

    def _key(self, account: int) -> str:
        key = self._key_of(account)
        if not key:
            raise SttError(f"GAPI STT sozlanmagan ({self._name(account)})", status=501)
        return key

    def _redact(self, text: str) -> str:
        """`_safe` - ikkala kalit bilan."""
        if self._api_key2:
            text = (text or "").replace(self._api_key2, "<key>")
        return _safe(text, self._api_key)

    def _all_empty(self) -> SttError:
        error = SttError("GAPI: hamma kalitlarning balansi tugagan", status=429, retryable=True)
        error.gapi_status = 429
        error.gapi_code = _NO_BALANCE
        return error

    # --- kunlik sarf ------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return datetime.now(_TASHKENT).date().isoformat()

    def _account(self, seconds: float) -> None:
        day = self._today()
        with self._spend_lock:
            if day != self._spend_day:
                self._spend_day, self._spend_sec, self._spend_calls = day, 0.0, 0
            self._spend_sec += max(0.0, seconds)
            self._spend_calls += 1

    def spend(self) -> dict[str, object]:
        """Bugun shu jarayon GAPI da qancha audio sarflagani.

        Bu XIZMATNING hisobi emas - faqat shu jarayon ko'rgani. Haqiqiy
        balans `GET /usage` da, lekin u tashqi so'rov talab qiladi;
        bu esa tekin va darhol.
        """
        with self._spend_lock:
            return {
                "day": self._spend_day or self._today(),
                "audio_sec": round(self._spend_sec, 1),
                "calls": self._spend_calls,
                # `sent` - `calls` dan katta bo'lsa: pul ketgan, natija yo'q.
                "sent": self._spend_sent,
            }

    # --- asosiy yo'l ------------------------------------------------------

    def transcribe(self, audio: bytes, *, language: str,
                   content_type: str = "audio/wav",
                   budget: float | None = None) -> Transcript:
        """Audio -> matn. Imzo `SttClient.transcribe` bilan AYNAN bir xil.

        `budget` - SHU CHAQIRUV uchun devor-soat chegarasi (soniya). Zahira
        yo'lida kerak: GAPI o'z vaqtini yeb bo'lgach Router'ga QOLGAN vaqt
        beriladi, aks holda ikki klientning byudjeti qo'shilib nginx'ning
        120 sekundidan oshib ketardi va javob o'lgan ulanishga yozilardi.
        """
        if not self.configured:
            raise SttError("GAPI STT sozlanmagan (GAPI_API_KEY)", status=501)
        if language != "uz":
            # Tanlovchi bu holatni oldin ushlashi kerak. Bu yerda ham
            # tekshiriladi, chunki jim ishlab noto'g'ri tilda matn
            # qaytargandan ko'ra aniq xato afzal.
            raise SttError(f"GAPI faqat o'zbek tilini biladi: {language}", status=400)
        if not audio:
            raise SttError("audio bo'sh", status=400)

        if not self._slots.acquire(timeout=1.0):
            raise SttError(f"ilova GAPI chegarasida ({self.max_concurrent} parallel)",
                           status=503, retryable=True)
        try:
            return self._any_account(audio, content_type, budget)
        finally:
            self._slots.release()

    def _any_account(self, audio: bytes, content_type: str,
                     budget: float | None = None) -> Transcript:
        """Hisoblar tartib bilan: balansi tugagani belgilanadi va DARHOL keyingisi
        sinaladi. Boshqa xato avvalgidek yuqoriga ketadi (chatda zahira - Router)."""
        accounts = self.usable_accounts()
        if not accounts:
            raise self._all_empty()
        started = time.monotonic()
        for account in accounts:
            left = None if budget is None else max(0.0, budget - (time.monotonic() - started))
            try:
                return self._with_retries(audio, content_type, left, account=account)
            except SttError as exc:
                if not out_of_balance(exc):
                    raise
                self.mark_out_of_balance(account)
                if account == accounts[-1]:
                    raise
        raise self._all_empty()

    def _with_retries(self, audio: bytes, content_type: str,
                      budget: float | None = None, *, account: int = 1) -> Transcript:
        body, ctype = _multipart(audio, safe_filename(content_type), content_type)
        started = time.monotonic()
        deadline = self.deadline if budget is None else min(self.deadline, budget)

        for attempt in range(self.attempts):
            try:
                return self._once(body, ctype, started, account)
            except SttError as exc:
                # OXIRGI urinishdan keyin kutish - sof zarar. Avval bu
                # qo'riqchi yo'q edi va `attempts=1` bo'lgan klient ham
                # bekorga 1 sekund uxlardi: shu vaqt davomida PULLIK slot va
                # `def` endpoint'ining threadpool ishchisi band turardi.
                # (`services/stt.py` da bu qo'riqchi boshidan bor.)
                # Balans tugagan bo'lsa kutish ham yordam bermaydi - keyingi kalit kerak.
                if not exc.retryable or out_of_balance(exc) or attempt == self.attempts - 1:
                    raise
                # 429 da xizmat `Retry-After` beradi - o'shancha kutamiz.
                pause = getattr(exc, "retry_after", None) or 1.0
                # Keyingi urinish O'Z `timeout` ini ham yeydi - shuni
                # qo'shmasa byudjet e'lon qilingandan oshib ketadi: ikki
                # marta 60 s timeout = 121 s, nginx esa 120 s da ulanishni
                # uzadi va javob hech kimga yetmaydi.
                if time.monotonic() - started + pause + self.timeout > deadline:
                    raise
                time.sleep(min(pause, 5.0))
        raise SttError("GAPI javob bermadi", status=502)

    def _once(self, body: bytes, ctype: str, started: float, account: int = 1) -> Transcript:
        with self._spend_lock:
            self._spend_sent += 1
        payload, job_id = self._post("/transcribe", body, ctype, account)
        # `202` - natija hali yo'q, faqat `job_id`. Uzun yozuvlar uchun.
        if payload.get("state") and not payload.get("text"):
            payload = self._await_job(payload.get("id") or job_id, started, account)
        result = self._parse(payload, started, job_id)
        self._account(result.duration_sec)
        return result

    # --- vazifa yo'li (faqat 202 bo'lganda) -------------------------------

    def _await_job(self, job_id: str, started: float, account: int = 1) -> dict[str, Any]:
        """Vazifa tugashini kutadi. Faqat `/transcribe` 202 qaytarganda.

        SSE ham, webhook ham ISHLATILMAYDI: ikkalasi ham bizning holatga
        yaramaydi. Webhook uchun tashqi manzil kerak (Venera ichki
        tarmoqda), SSE esa uzun ulanish talab qiladi - 30 sekundlik
        bo'lak uchun 2 sekundda bir so'rash arzonroq va oddiyroq
        (o'qish limiti daqiqasiga 3000, ya'ni bemalol).
        """
        if not job_id:
            raise SttError("GAPI vazifa raqamini bermadi", status=502)
        while True:
            if time.monotonic() - started > self.deadline:
                raise SttError("GAPI javobi juda uzoq cho'zildi", status=504)
            state, _ = self._get(f"/jobs/{job_id}", account)
            current = str(state.get("state") or "")
            if current == "done":
                result, _ = self._get(f"/jobs/{job_id}/result", account)
                return result
            if current in ("failed", "cancelled"):
                raise SttError(f"GAPI vazifasi {current}", status=502)
            time.sleep(_POLL_EVERY)

    # --- transport --------------------------------------------------------

    def _headers(self, account: int = 1) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key(account)}", "Accept": "application/json"}

    def _post(self, path: str, body: bytes, ctype: str, account: int = 1) -> tuple[dict[str, Any], str]:
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, method="POST",
            headers={**self._headers(account), "Content-Type": ctype},
        )
        return self._send(request)

    def _get(self, path: str, account: int = 1) -> tuple[dict[str, Any], str]:
        request = urllib.request.Request(f"{self.base_url}{path}", headers=self._headers(account))
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> tuple[dict[str, Any], str]:
        # Proksi ATAYLAB chetlab o'tilmaydi (Router klientidan farqli):
        # `console.gapi.uz` TASHQI manzil, ya'ni muhitdagi proksi sozlamasi
        # to'g'ri bo'lishi kerak.
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                job_id = response.headers.get("X-Job-Id") or ""
        except urllib.error.HTTPError as exc:
            raise self._from_http(exc) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SttError(f"GAPI ga ulanib bo'lmadi: {self._redact(str(exc))}",
                           status=503, retryable=True) from exc
        if not raw:
            return {}, job_id
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SttError(f"GAPI javobi o'qilmadi: {self._redact(str(exc))}",
                           status=502) from exc
        if not isinstance(payload, dict):
            raise SttError("GAPI javobi obyekt emas", status=502)
        return payload, job_id

    def _from_http(self, exc: urllib.error.HTTPError) -> SttError:
        """`{"error": "<kod>", "hint": "..."}` -> `SttError`.

        Uch guruh (hujjat): so'rovni tuzatish kerak, kutib qayta urinish
        mumkin, va qaytmaydi. Faqat ikkinchisi takrorlanadi.
        """
        status = exc.code
        code, hint = "", ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            if isinstance(payload, dict):
                code = str(payload.get("error") or "")
                hint = str(payload.get("hint") or "")
        except Exception:
            pass
        retryable = status in _RETRYABLE
        error = SttError(
            self._redact(f"GAPI {status} {code}: {hint}".strip()),
            # 401 - BIZNING kalitimiz noto'g'ri, ya'ni SOZLAMA xatosi.
            # Brauzerga 401 qaytarish "sessiyangiz tugadi" degan ma'no
            # berardi, holbuki foydalanuvchi sessiyasi mutlaqo joyida.
            status=502 if status in (401, 403) else status,
            retryable=retryable,
        )
        if retryable:
            try:
                error.retry_after = float(exc.headers.get("Retry-After") or 0) or None
            except (TypeError, ValueError):
                error.retry_after = None
        # Yig'ilish ishchisi uchun (`services/meetings/transcribe.py`): xatoning
        # ASL kodi va GAPI nomi. `status` 401/403 da 502 ga almashtirilgan
        # (chat uchun to'g'ri), ishchi esa `stt_auth`, `insufficient_balance`,
        # `result_not_ready` larni ajratishi kerak. Chat bu maydonlarni o'qimaydi.
        error.gapi_status = status
        error.gapi_code = code
        return error

    # --- yig'ilish vazifalari (asinxron, `services/meetings/`) ---------------
    #
    # Chat yo'li (`transcribe`) BU YERGA TEGMAYDI. Yig'ilish uzun (3 soatgacha):
    # audio `POST /jobs` bilan yuboriladi, javob darhol `202` + vazifa raqami,
    # natija esa ishchi tomonidan keyin so'raladi. Qayta urinish va kutish
    # ISHCHINING ishi (`attempts=1` klient) - u holatni diskda saqlaydi va
    # xizmat qayta ishga tushsa ham vazifani yo'qotmaydi.

    def submit_job(self, path: Path | str, content_type: str,
                   settings: dict[str, Any], *, account: int = 1) -> dict[str, Any]:
        """Audio faylni (diskdan, oqim bilan) yuboradi -> `{id, state, estimatedSeconds, resultUrl}`.

        Fayl nomi `meeting.aac` / `.m4a` / `.mp3` / `.wav` - odamning ismi ham, id si
        ham GAPI ga ketmaydi (spetsifikatsiya 4.4); kengaytma formatni aytadi.
        `account` - qaysi kalit bilan (hisobni ishchi balansga qarab tanlaydi)."""
        if not self.configured:
            raise SttError("GAPI STT sozlanmagan (GAPI_API_KEY)", status=501)
        headers = self._headers(account)
        filename = _MEETING_FILENAMES.get((content_type or "").split(";", 1)[0].strip().lower(), "meeting.aac")
        body, ctype = _multipart_stream(Path(path), filename, content_type, settings)
        request = urllib.request.Request(
            f"{self.base_url}/jobs", data=body, method="POST",
            headers={**headers, "Content-Type": ctype,
                     "Content-Length": str(body.length)},
        )
        if not self._slots.acquire(timeout=1.0):
            busy = SttError(f"ilova GAPI chegarasida ({self.max_concurrent} parallel)",
                            status=503, retryable=True)
            # So'rov KETMAGAN (o'z slotimiz band): ishchi buni urinish deb sanamaydi.
            busy.local = True
            raise busy
        try:
            # YUBORILGAN urinish - javob kelmasa ham pul ketishi mumkin (`spend`).
            with self._spend_lock:
                self._spend_sent += 1
            payload, header_id = self._send_any(request)
        finally:
            body.close()
            self._slots.release()
        if not isinstance(payload, dict):
            payload = {}
        job_id = str(payload.get("id") or payload.get("job_id") or header_id or "")
        if not job_id:
            raise SttError("GAPI vazifa raqamini bermadi", status=502)
        return {
            "id": job_id,
            "state": str(payload.get("state") or "queued"),
            "estimatedSeconds": _num(payload.get("estimated_seconds")),
            "resultUrl": str(payload.get("result_url") or "") or None,
        }

    def get_job(self, job_id: str, *, account: int = 1) -> dict[str, Any]:
        """Vazifa holati (`state`, `progress_seconds`, `audio_seconds`, ...) - xom."""
        payload, _ = self._send_any(self._get_request(f"/jobs/{urllib.parse.quote(job_id, safe='')}", account))
        return payload if isinstance(payload, dict) else {}

    def list_jobs(self, limit: int = 20, *, account: int = 1) -> list[dict[str, Any]]:
        """Oxirgi vazifalar - `POST` va `202` orasida uzilgan yuborishni topish uchun."""
        payload, _ = self._send_any(self._get_request(f"/jobs?limit={int(limit)}", account))
        if isinstance(payload, dict):
            for key in ("jobs", "items", "data", "results"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        return [j for j in payload if isinstance(j, dict)] if isinstance(payload, list) else []

    def get_result(self, job_id: str, result_url: str | None = None, *, account: int = 1) -> dict[str, Any]:
        """Natija. `result_url` FAQAT sozlangan GAPI manzili bilan boshlansa
        ishlatiladi: aks holda javobdagi istalgan manzilga KALITIMIZ bilan
        so'rov ketardi (token boshqa hostga oqib chiqadi)."""
        prefix = self.base_url.rstrip("/") + "/"
        if result_url and str(result_url).startswith(prefix):
            request = urllib.request.Request(str(result_url), headers=self._headers(account))
        else:
            request = self._get_request(f"/jobs/{urllib.parse.quote(job_id, safe='')}/result", account)
        payload, _ = self._send_any(request)
        return payload if isinstance(payload, dict) else {}

    def cancel_job(self, job_id: str, *, account: int = 1) -> bool:
        """`DELETE /jobs/{id}` - eng yaxshi urinish. GAPI ma'lumotni baribir
        30 kun saqlaydi, bu faqat yashiradi. Xato BERMAYDI."""
        try:
            request = urllib.request.Request(
                f"{self.base_url}/jobs/{urllib.parse.quote(job_id, safe='')}",
                method="DELETE", headers=self._headers(account))
            self._send_any(request)
            return True
        except SttError as exc:
            log.info("GAPI vazifasini o'chirib bo'lmadi: %s", exc)
            return False

    def usage(self, *, account: int = 1) -> dict[str, Any]:
        """`GET /usage` (bepul) - shu kalitning balansi: `available_g`, `topup_target_g`."""
        payload, _ = self._send_any(self._get_request("/usage", account))
        return payload if isinstance(payload, dict) else {}

    def note_meeting_audio(self, seconds: float) -> None:
        """Yig'ilish natijasi keldi - kunlik sarfga qo'shiladi (`spend`)."""
        self._account(seconds)

    # --- loyiha ovozlari va ovoz namunasi (`services/meetings/voice.py`) ----------
    #
    # OVOZLAR GAPI LOYIHASIDA saqlanadi, ya'ni HAR HISOBDA ALOHIDA (`account`): 1-hisobdagi #100 va
    # 2-hisobdagi #100 - boshqa-boshqa odam. API kaliti ovozning `speaker_id` si (natijada
    # `speaker_info[].identity.speaker_id`, ro'yxatda `id`), raqam (`voice_id` / `number`) - ko'rinish uchun.
    # Ovoz izining O'ZI hech qaysi javobda kelmaydi.

    def transcribe_sample(self, audio: bytes, content_type: str, *, account: int = 1) -> tuple[dict[str, Any], str]:
        """Ovoz namunasi -> GAPI natijasi XOM (`speaker_info`, `voices`, `speech_seconds`) va vazifa raqami
        (`enroll_speaker` uchun). Sinxron `/transcribe` (5 daqiqagacha), `202` bo'lsa kutiladi.
        Hisob AYNAN berilgani - balans tugasa ham boshqasiga o'tmaydi: ovoz har hisobga alohida yoziladi."""
        if not self.base_url or not self._key_of(account):
            raise SttError(f"GAPI STT sozlanmagan ({self._name(account)})", status=501)
        if not audio:
            raise SttError("audio bo'sh", status=400)
        body, ctype = _multipart(audio, safe_filename(content_type), content_type, _SAMPLE_SETTINGS)
        if not self._slots.acquire(timeout=30.0):
            busy = SttError(f"ilova GAPI chegarasida ({self.max_concurrent} parallel)", status=503, retryable=True)
            busy.local = True
            raise busy
        try:
            started = time.monotonic()
            with self._spend_lock:
                self._spend_sent += 1
            payload, job_id = self._post("/transcribe", body, ctype, account)
            if payload.get("state") and not isinstance(payload.get("segments"), list):
                job_id = str(payload.get("id") or payload.get("job_id") or job_id)
                payload = self._await_job(job_id, started, account)
        finally:
            self._slots.release()
        job_id = job_id or str(payload.get("job_id") or payload.get("id") or "")
        self._account(_num(payload.get("audio_seconds")) or 0.0)
        return payload, job_id

    def speakers(self, *, account: int = 1) -> list[dict[str, Any]]:
        """`GET /speakers` - loyihaning ovozlari: `id`, `number`, `name`, `kind`, `seen_count`, ..."""
        payload, _ = self._send_any(self._get_request("/speakers", account))
        if isinstance(payload, dict):
            for key in ("speakers", "items", "data", "voices"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        return [s for s in payload if isinstance(s, dict)] if isinstance(payload, list) else []

    def create_speaker(self, name: str, *, account: int = 1) -> dict[str, Any]:
        """`POST /speakers {"name"}` - izsiz ovoz (izi keyin `enroll_speaker` bilan)."""
        return self._json("POST", "/speakers", {"name": name}, account)

    def rename_speaker(self, speaker_id: str, name: str, *, account: int = 1) -> dict[str, Any]:
        """`PATCH /speakers/{id} {"name"}`. Nom qo'yilgan ovoz (`named`) muddatsiz saqlanadi."""
        return self._json("PATCH", f"/speakers/{urllib.parse.quote(speaker_id, safe='')}", {"name": name}, account)

    def delete_speaker(self, speaker_id: str, *, account: int = 1) -> bool:
        """`DELETE /speakers/{id}` - ovoz barcha izlari bilan. Allaqachon yo'q (404) - ham muvaffaqiyat."""
        try:
            self._json("DELETE", f"/speakers/{urllib.parse.quote(speaker_id, safe='')}", None, account)
        except SttError as exc:
            if getattr(exc, "gapi_status", None) == 404:
                return True
            raise
        return True

    def enroll_speaker(self, speaker_id: str, job_id: str, *, speaker_index: int | None = None,
                       segment_indexes: list[int] | None = None, account: int = 1) -> dict[str, Any]:
        """`POST /speakers/{id}/enroll` - tugagan vazifadagi spiker (yoki gaplar) izini shu ovozga qo'shadi.
        Iz GAPI tomonida saqlangan yozuvdan hisoblanadi (bir ovozda ko'pi bilan 10 ta iz)."""
        body: dict[str, Any] = {"job_id": job_id}
        if segment_indexes:
            body["segment_indexes"] = [int(i) for i in segment_indexes]
        else:
            body["speaker_index"] = int(speaker_index or 0)
        return self._json("POST", f"/speakers/{urllib.parse.quote(speaker_id, safe='')}/enroll", body, account)

    def _json(self, method: str, path: str, body: dict[str, Any] | None, account: int) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = self._headers(account)
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        payload, _ = self._send_any(request)
        return payload if isinstance(payload, dict) else {}

    def _get_request(self, path: str, account: int = 1) -> urllib.request.Request:
        return urllib.request.Request(f"{self.base_url}{path}", headers=self._headers(account))

    def _send_any(self, request: urllib.request.Request) -> tuple[Any, str]:
        """`_send` kabi, lekin javob ro'yxat ham bo'lishi mumkin (`GET /jobs`).
        `_send` ning o'ziga tegilmaydi - chat yo'li o'zgarmasin."""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                job_id = response.headers.get("X-Job-Id") or ""
        except urllib.error.HTTPError as exc:
            raise self._from_http(exc) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SttError(f"GAPI ga ulanib bo'lmadi: {self._redact(str(exc))}",
                           status=503, retryable=True) from exc
        if not raw:
            return {}, job_id
        try:
            return json.loads(raw.decode("utf-8")), job_id
        except (ValueError, UnicodeDecodeError) as exc:
            raise SttError(f"GAPI javobi o'qilmadi: {self._redact(str(exc))}",
                           status=502) from exc

    # --- javobni o'qish ---------------------------------------------------

    @staticmethod
    def _parse(payload: dict[str, Any], started: float, job_id: str) -> Transcript:
        text = str(payload.get("text") or "").strip()
        try:
            duration = float(payload.get("audio_seconds") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        result = Transcript(
            text=text,
            language="uz",
            backend="gapi",
            # Model nomi javobda yo'q - audit uchun vazifa raqami
            # foydaliroq: xizmat jurnalida shu kalit bo'yicha izlanadi.
            model=f"gapi:{job_id}" if job_id else "gapi",
            duration_sec=duration,
            elapsed_sec=round(time.monotonic() - started, 3),
        )
        # Router har transkripsiyani jurnalga yozadi (`services/stt.py`),
        # GAPI esa yozmasdi - ya'ni jurnalga qarab qaysi VARIANT ishlaganini
        # bilib bo'lmasdi. Sinov davrida qaror aynan shunga tayanadi.
        #
        # Ustiga bu xizmat audio DAQIQASI uchun pul oladi, ya'ni `%.1fs
        # audio` - hisobning o'zi: kunlik 480 daqiqa shu sonlardan yig'iladi.
        # Format Router bilan AYNAN bir xil, shuning uchun bitta `grep STT`
        # ikkala variantni ham topadi va ularni yonma-yon solishtirish
        # mumkin.
        #
        # Matnning O'ZI yozilmaydi: u xodim aytgan gap - shaxsiy ma'lumot.
        # Router ham faqat uzunligini yozadi.
        log.info("STT %s/%s: %.1fs audio, %.2fs, %d belgi",
                 result.backend, result.model, result.duration_sec,
                 result.elapsed_sec, len(result.text))
        return result


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

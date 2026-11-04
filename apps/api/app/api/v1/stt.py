"""Ovozni matnga o'girish.

Brauzer mikrofondan yozib, shu yerga yuboradi; biz STT Router'ga uzatamiz.

NEGA TO'G'RIDAN-TO'G'RI EMAS: brauzer `10.10.50.4:8006` ga o'zi bora olmaydi.
Sayt HTTPS'da bo'lsa aralash-kontent bloklanadi, HTTP'da bo'lsa CORS to'sadi,
va ikkala holatda ham ichki manzil brauzerga ochilgan bo'lardi. Proksi bilan
STT serveri tashqariga umuman ko'rinmaydi va so'rov autentifikatsiyadan
o'tadi.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
from collections import deque

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ...core.config import settings
from ...core.errors import bad_request, error_status
from ...schemas.auth import AuthUser
from ...schemas.stt import TranscriptResponse, WakeResponse
from ...services.analytics import begin
from ...services.integrations.gapi_stt import GapiSttClient
from ...services.stt import LOCALE_TO_STT, SttClient, SttError, Transcript
from ...services.wake import FLAT_LIMIT, WakeLog, is_wake_phrase, measure
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/stt", tags=["stt"])

_router_client = SttClient(
    settings.stt_base_url,
    timeout=settings.stt_timeout,
    attempts=settings.stt_attempts,
    max_concurrent=settings.stt_max_concurrent,
    deadline=settings.stt_deadline,
)

#: 2-variant. Kalit bo'sh bo'lsa `configured` False bo'ladi va tanlovchi
#: uni hech qachon tanlamaydi - ya'ni sozlanmagan holat xato emas.
#: `attempts=1` - va bu ZAHIRA bor joyda majburiy.
#:
#: Default 2 edi, va `_RETRYABLE` ga 429 kiradi - ya'ni "kvota tugadi"
#: javobini olgan so'rov aynan o'sha tugagan kvotaga YANA urilardi, oldin
#: `Retry-After` bo'yicha 5 sekundgacha kutib. Ikkinchi urinish daqiqa
#: oynasi yangilanmasdan ketardi, ya'ni javobi ham aynan o'sha 429 bo'lardi:
#: sof zarar - 5 sekund kechikish, ikkinchi (ba'zan pullik) yuklash va
#: chegaraning yana buzilishi.
#:
#: Qayta urinishning o'rnini zahira oladi: bir urinish, keyin Router - u
#: bepul, chegarasiz va o'zining qayta urinishlari bor.
_gapi_client = GapiSttClient(
    settings.gapi_base_url,
    settings.gapi_api_key,
    timeout=settings.gapi_timeout,
    max_concurrent=settings.gapi_max_concurrent,
    deadline=settings.stt_deadline,
    attempts=1,
    api_key2=settings.gapi_api_key2,
)

#: UYG'OTISH uchun ALOHIDA GAPI klienti - va sababi o'lchangan.
#:
#: Bitta klientda slotlar UMUMIY bo'lardi (`gapi_max_concurrent = 2`).
#: O'lchov: 4 ta parallel so'rovdan to'rtinchisi `503 ilova GAPI
#: chegarasida` oldi. Ya'ni tinglagich har 2.5 sekundda parcha yuborib
#: turganda foydalanuvchining SAVOLI slot topmay qolishi va ekranda
#: "Ovoz xizmati band" chiqishi mumkin edi - uyg'otish Router'da
#: turganda bunday bo'lishi MUMKIN emas edi.
#:
#: Alohida klient = alohida semafor: uyg'otish o'zining bitta slotidan
#: nariga o'tolmaydi, savolning ikki sloti esa tegilmay qoladi. Fon ishi
#: asosiy ishni bo'g'masligi kerak.
#:
#: `attempts=1`: kutib qayta urinish bu yerda zarar. Uyg'otish parchasi
#: har 2.5 sekundda keladi, ya'ni kechikkan javobning qadri yo'q; ustiga
#: `Retry-After` uchun kutish `def` endpoint'ining threadpool ishchisini
#: ushlab turadi. Zahira esa pastda - Router.
#: VAQT BYUDJETI HAM ALOHIDA, va transkripsiyadan ancha qisqa.
#:
#: `gapi_timeout = 60` va `stt_deadline = 100` - bu SAVOL uchun o'lchangan
#: byudjetlar: uzun yozuvni kutish mantiqiy. Uyg'otish parchasi esa har
#: 2.5 sekundda keladi va brauzer keyingisini yuborganda oldingisini
#: bekor qiladi - ya'ni 60 sekund kutish javobsiz qoladigan, lekin
#: SLOTNI va threadpool ishchisini band qilib turadigan, ustiga PULI
#: ketgan ish bo'lardi.
#:
#: 5 s / 8 s: o'lchangan mediana 1.2 s, yuklama ostida 3.6 s. Ya'ni
#: sog'lom GAPI bunga bemalol sig'adi, sekinlashgani esa darhol Router'ga
#: tushadi - bepul va 0.1 sekundda.
_gapi_wake_client = GapiSttClient(
    settings.gapi_base_url,
    settings.gapi_api_key,
    timeout=5.0,
    max_concurrent=1,
    deadline=8.0,
    attempts=1,
    api_key2=settings.gapi_api_key2,
)


class _WakeBudget:
    """Uyg'otish uchun PULLIK so'rovlar byudjeti: aktor va jami bo'yicha.

    Chegaradan oshgan parcha RAD ETILMAYDI - 1-variantga (bepul Router)
    tushadi. Ya'ni bu chegara xizmatni emas, HISOBNI cheklaydi:
    foydalanuvchi uchun hech narsa o'zgarmaydi, uyg'otish ishlashda davom
    etadi.

    Sonlar va sabablari `core/config.py` da yozilgan.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._per_actor: dict[str, deque[float]] = {}
        self._total: deque[float] = deque()

    @staticmethod
    def _trim(stamps: "deque[float]", now: float) -> None:
        while stamps and now - stamps[0] > 60.0:
            stamps.popleft()

    def allow(self, actor_id: str) -> bool:
        """GAPI ga yuborish mumkinmi? Yo'q bo'lsa - chaqiruvchi Router oladi."""
        now = time.monotonic()
        with self._lock:
            self._trim(self._total, now)
            if len(self._total) >= settings.wake_gapi_total_min:
                return False
            mine = self._per_actor.get(actor_id)
            if mine is None:
                mine = self._per_actor[actor_id] = deque()
            self._trim(mine, now)
            if len(mine) >= settings.wake_gapi_per_actor_min:
                return False
            # Yopilgan varaqlar to'planmasligi uchun bo'shlarini tashlaymiz.
            if len(self._per_actor) > 64:
                for key in [k for k, v in self._per_actor.items() if not v]:
                    del self._per_actor[key]
            mine.append(now)
            self._total.append(now)
            return True

    def snapshot(self) -> dict[str, int]:
        """`/api/health/detail` uchun - oxirgi daqiqadagi holat."""
        now = time.monotonic()
        with self._lock:
            self._trim(self._total, now)
            return {
                "gapi_last_min": len(self._total),
                "gapi_limit_min": settings.wake_gapi_total_min,
                "actors": sum(1 for v in self._per_actor.values() if v),
            }


_wake_budget = _WakeBudget()

#: Zahira ISHLAMAYDIGAN holatlar - ya'ni qoida TESKARI yozilgan, va bu
#: ataylab.
#:
#: Avval "zahira ishlaydigan kodlar" ro'yxati bor edi va u jimgina
#: to'liqsiz chiqdi: GAPI o'z serverida 500 bersa, yoki 507 (quvvat) yoki
#: 409 qaytarsa, kod ro'yxatda yo'q edi va zahira ISHLAMASDAN
#: foydalanuvchiga xato ketardi - holbuki bepul Router bir qadam narida
#: turgan. Ro'yxat har yangi kod bilan yana to'liqsiz bo'lardi.
#:
#: Teskari qoida bunday buzilmaydi: zahira MIJOZ xatosida ishlamaydi -
#: yaroqsiz audio, juda katta fayl, qo'llab-quvvatlanmaydigan format.
#: Bular Router'da ham aynan shunday xato beradi, ya'ni ikkinchi urinish
#: faqat vaqtni va pulni yeydi. QOLGAN hamma narsada Router sinaladi.
_NO_FALLBACK = frozenset({400, 413, 415, 422})


class _FallbackLog:
    """Zahira qachon va nechta marta ishlagani.

    NEGA KERAK. Zahira ishlaganda foydalanuvchi uchun hammasi joyida
    ko'rinadi - va aynan shu xavfli: tizim kun bo'yi 1-variantda ishlab
    turishi, `/api/health/detail` esa `wake_provider=gapi` deb ko'rsatib
    turishi mumkin. Jurnaldagi bitta INFO satridan boshqa hech narsa buni
    aytmaydi, jurnalga esa hech kim qaramaydi.

    Bu hisoblagich "sizning 2-variantingiz amalda ishlamayapti" degan
    gapni ko'rinadigan joyga chiqaradi.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recent: deque[tuple[float, str, int]] = deque(maxlen=200)
        self._total = 0

    def record(self, yol: str, status: int) -> None:
        with self._lock:
            self._recent.append((time.monotonic(), yol, status))
            self._total += 1

    def snapshot(self) -> dict[str, object]:
        now = time.monotonic()
        with self._lock:
            oxirgi = [r for r in self._recent if now - r[0] <= 300.0]
            son = len(oxirgi)
            return {
                "total": self._total,
                "last_5min": son,
                "last_status": oxirgi[-1][2] if oxirgi else None,
                "last_path": oxirgi[-1][1] if oxirgi else None,
            }


_fallbacks = _FallbackLog()


def _upstream_status(exc: BaseException) -> int | None:
    """Xizmatning HAQIQIY HTTP statusi (`SttError.status` - foydalanuvchiniki:
    GAPI ning 401 i u yerda 502). GAPI xatoni `from None` bilan ko'taradi,
    shuning uchun `__context__` ham qaraladi."""
    for cause in (exc.__cause__, exc.__context__):
        if isinstance(cause, urllib.error.HTTPError):
            return cause.code
    return None


def _metered_transcribe(client, op: str, audio: bytes, language: str,
                        content_type: str, budget: float, trace: list | None = None) -> Transcript:
    """Bitta variantga murojaat - hisob bilan (`api_calls`).

    NEGA SHU YERDA, klientlar ichida emas: amal nomi (`transcribe` yoki
    `wake`) faqat shu yerda ma'lum, va ikkala variant ham, zahira ham,
    Telegram bot ham shu yo'ldan o'tadi. Uyg'otish parchalari har 2.5
    sekundda keladi - ular savol bilan aralashsa sarf statistikasi
    ma'nosiz bo'lardi. Birlik - audio soniyasi (GAPI shu uchun pul oladi)
    va yuborilgan bayt.
    """
    service = "stt_gapi" if isinstance(client, GapiSttClient) else "stt_router"
    call = begin(service, op, units={"bytes": len(audio)})
    started = time.monotonic()
    try:
        result = client.transcribe(audio, language=language, content_type=content_type,
                                   budget=budget)
    except SttError as exc:
        call.end("error", http_status=_upstream_status(exc), error=exc)
        _traced(trace, service, started, ok=False, status=exc.status,
                upstream=_upstream_status(exc), error=str(exc)[:200])
        raise
    except BaseException as exc:
        call.end("error", error=exc)
        raise
    call.end(http_status=200, units={"audioSec": float(result.duration_sec or 0.0)})
    _traced(trace, service, started, ok=True, backend=result.backend, model=result.model,
            audioSec=result.duration_sec)
    return result


def _traced(trace: list | None, step: str, started: float, **detail) -> None:
    """Admin sinovi (`admin_probe.py`) uchun qadam yozuvi; `trace` yo'q bo'lsa hech narsa.
    Matn yozilmaydi - faqat holat va vaqt (transkript javobning o'zida qaytadi)."""
    if trace is not None:
        trace.append({"step": step, "ms": round((time.monotonic() - started) * 1000.0, 1),
                      "detail": detail})


def _transcribe_with_fallback(client, audio: bytes, language: str,
                              content_type: str, *, yol: str,
                              budget: float, op: str = "transcribe",
                              trace: list | None = None) -> Transcript:
    """Transkripsiya - 2-variant berilmasa 1-variant (Router) bilan.

    NEGA ZAHIRA KERAK. 2-variant (GAPI) PULLIK va chegaralangan: kunlik
    480 audio-daqiqa, daqiqasiga 60 yuklash. 1-variant esa ichki, bepul va
    chegarasiz. Ya'ni kvota tugashi VAQTINCHA holat, ovozni butunlay
    ishdan chiqarish uchun sabab emas - ayniqsa ishlaydigan, isbotlangan
    yo'l bir qadam narida turganda.

    IKKALA yo'l uchun ham:
      * uyg'otish so'zi - zahirasiz kvota tugagan kuni "Salom Venera"
        yarim kechagacha ishlamas edi (tinglagich xatolarni ko'rib
        oralig'ini 60 sekundgacha uzaytiradi), va buni hech kim jurnalga
        qaramasa bilmasdi;
      * foydalanuvchi savoli - zahirasiz mikrofon tugmasi kun oxirigacha
        xato qaytarardi, holbuki matn chat orqali ishlashda davom etardi.
        Ovoz butunlay o'lgandan ko'ra Router'ning matni (kichik harf,
        tinish belgisisiz) ANIQ afzal.

    QAYSI XATODA TUSHADI. Faqat TRANSPORT va CHEGARA xatolari
    (`_ROUTER_FALLBACK`). 400/413/415/422 ATAYLAB yo'q: yaroqsiz parcha
    Router'da ham yaroqsiz, ya'ni ikkinchi urinish kechikishni ikki
    barobar qilib, natijani o'zgartirmaydi.

    Javobdagi `backend` maydoni qaysi variant ishlaganini aytadi, ya'ni bu
    almashish jim emas: jurnalda ham, javobda ham ko'rinadi.

    `trace` - admin "Tizim xaritasi" sinovi: qaysi variant, necha ms, zahira
    ishladimi. Sinov AYNAN shu funksiyani chaqiradi (nusxa emas); `None` da
    xulq o'zgarmaydi.
    """
    started = time.monotonic()
    try:
        return _metered_transcribe(client, op, audio, language, content_type, budget, trace)
    except SttError as gapi_exc:
        if client is _router_client or gapi_exc.status in _NO_FALLBACK:
            raise
        _fallbacks.record(yol, gapi_exc.status)
        # Bitta satr - jurnalda 2-variantning qachon berilmaganini ko'rish
        # uchun. Sarf va chegara muammolari aynan shu satrdan ko'rinadi.
        log.info("%s: GAPI berilmadi (%s) - 1-variant bilan davom etildi", yol, gapi_exc)
        # QOLGAN vaqt beriladi, to'liq byudjet emas: 2-variant allaqachon
        # vaqtning bir qismini yeb bo'ldi va ikki byudjet qo'shilsa jami
        # nginx chegarasidan (120 s) oshib ketardi - javob esa o'lgan
        # ulanishga yozilardi. Eng kami 2 s: Router 0.13 sekundda javob
        # beradi, ya'ni bu unga yetib ortadi.
        qolgan = max(2.0, budget - (time.monotonic() - started))
        _traced(trace, "fallback", started, reason=gapi_exc.status, budgetSec=round(qolgan, 1))
        try:
            return _metered_transcribe(_router_client, op, audio, language, content_type,
                                       qolgan, trace)
        except SttError as router_exc:
            # IKKISI HAM yiqildi. Endpoint faqat OXIRGI xatoni yozadi, ya'ni
            # jurnalda Router aybdor bo'lib ko'rinardi va asl sabab (kvota,
            # kalit, chegara) INFO satrida qolib ketardi. Sabab zanjiri
            # ko'rinadigan joyda turishi kerak.
            log.warning("%s: ikkala variant ham yiqildi - 2-variant: %s | 1-variant: %s",
                        yol, gapi_exc, router_exc)
            raise


def _pick(language: str, provider: str, *, wake: bool = False):
    """Qaysi STT klienti ishlatiladi.

    UCHTA shart, va uchalasi ham KERAK:

      1. `provider == "gapi"` - `.env` da shunday tanlangan;
      2. `language == "uz"` - GAPI da boshqa til uchun model YO'Q, ya'ni
         rus yoki ingliz interfeysi baribir Router'ga boradi va 2-variantga
         o'tish ularni buzmaydi;
      3. `configured` - kalit bor. Bo'lmasa jimgina 1-variant ishlaydi:
         sozlanmagani uchun ovozni butunlay ishdan chiqarish noto'g'ri.

    Shartlardan biri bajarilmasa - Router. Ya'ni ZAHIRA HAR DOIM bor.
    """
    if provider == "gapi" and language == "uz" and _gapi_client.configured:
        # Uyg'otish o'zining alohida slotli klientini oladi (yuqoridagi
        # izohga qarang) - shunda fon ishi savolning slotini olmaydi.
        return _gapi_wake_client if wake else _gapi_client
    return _router_client

#: Foydalanuvchiga ko'rinadigan xabarlar - status bo'yicha, ichki matnsiz.
#: 503 = band (qayta urinsa bo'ladi), 504 = juda uzoq, 413 = katta,
#: 415 = format, 400/422 = audio qabul qilinmadi, 502 = xizmat javob bermadi.
_wake_log = WakeLog(settings.wake_log_dir, max_files=settings.wake_log_max_files)

#: Uyg'otish parchasi qisqa (0.35-2.6 s). Undan kattasi tinglagichdan
#: kelmaydi, ya'ni bu chegara xato yoki suiiste'mol belgisi.
_WAKE_MAX_BYTES = 1024 * 1024

_MESSAGES = {
    503: "Ovoz xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Ovozni qayta ishlash juda uzoq cho'zildi - qisqaroq gapirib ko'ring",
    413: "Audio juda katta",
    415: "Bu audio formati qabul qilinmaydi",
    400: "Audio qabul qilinmadi",
    422: "Audio qabul qilinmadi",
    502: "Ovoz xizmati javob bermadi",
    # 429/402 - 2-variant (GAPI) PULLIK va chegaralangan: daqiqasiga 60
    # yuklash, kunlik 480 audio-daqiqa. Bu kodlar `_MESSAGES` da yo'q
    # bo'lganda status 502 ga tushib, foydalanuvchiga "Ovoz xizmati javob
    # bermadi" deb ko'rsatilardi - holbuki xizmat javob bergan, faqat
    # bizning chegaramiz tugagan. Yolg'on xabar muammoni yashiradi.
    429: "Ovoz xizmati chegarasiga yetdi - biroz kutib qayta urinib ko'ring",
    402: "Ovoz xizmatining kunlik chegarasi tugadi",
}


def upload_bytes(file: UploadFile) -> bytes:
    """Yuklangan audio baytlari - hajm chegarasi va bo'sh tekshiruvi bilan.

    `/transcribe` va admin sinovi (`admin_probe.py`) BIR XIL qoidadan o'tsin:
    sinov chegarani o'zicha tekshirsa, katta faylni sinovda "o'tadi" deb
    ko'rsatib, jonli yo'lda rad etilishi mumkin edi."""
    audio = file.file.read()
    limit = int(settings.stt_max_upload_mb * 1024 * 1024)
    if len(audio) > limit:
        raise bad_request(f"audio juda katta ({len(audio) // 1024} KB, chegara {settings.stt_max_upload_mb} MB)")
    if not audio:
        raise bad_request("audio bo'sh")
    return audio


def public_error(exc: SttError) -> tuple[int, str]:
    """Status -> foydalanuvchi xabari (`_MESSAGES`); ro'yxatda yo'q status 502 bo'ladi.
    Admin sinovi ham aynan shu xabarni ko'rsatadi - odam ko'radigan matn bilan bir xil."""
    status = exc.status if exc.status in _MESSAGES else 502
    return status, _MESSAGES[status]


@router.post("/transcribe", response_model=TranscriptResponse)
def transcribe(
    file: UploadFile = File(description="Audio (webm/ogg/wav)"),
    language: str = Form(description="uz | uz-Cyrl | ru | en - UI tili"),
    user: AuthUser = Depends(current_user),
) -> TranscriptResponse:
    """Audio -> matn.

    `async def` EMAS, ataylab: STT klienti bloklaydigan `urllib` ishlatadi.
    Oddiy `def` bilan FastAPI uni threadpool'da ishlatadi va event loop
    to'silmaydi - aks holda bitta uzun transkripsiya butun serverni
    to'xtatib qo'yardi.
    """
    stt_language = LOCALE_TO_STT.get(language)
    if stt_language is None:
        raise bad_request(f"til qo'llab-quvvatlanmaydi: {language}")

    audio = upload_bytes(file)

    try:
        result = _transcribe_with_fallback(
            _pick(stt_language, settings.stt_provider),
            audio,
            stt_language,
            file.content_type or "application/octet-stream",
            yol="Transkripsiya",
            # Butun so'rov uchun bitta byudjet - ikki klientga BO'LINADI.
            budget=settings.stt_deadline,
        )
    except SttError as exc:
        log.warning("STT (%s, %s): %s", user.email, stt_language, exc)
        status, message = public_error(exc)
        raise error_status(status, message) from exc

    return TranscriptResponse(
        text=result.text,
        language=result.language or stt_language,
        durationSec=result.duration_sec,
        lowConfidence=result.low_confidence,
        truncated=result.truncated,
        backend=result.backend,
    )


@router.post("/wake", response_model=WakeResponse)
def wake(
    file: UploadFile = File(description="Qisqa audio parcha (WAV 16 kHz mono)"),
    language: str = Form(description="uz | uz-Cyrl - UI tili"),
    user: AuthUser = Depends(current_user),
) -> WakeResponse:
    """Uyg'otish so'zi tekshiruvi.

    `/transcribe` DAN ALOHIDA, garchi ikkalasi ham STT ga borsa ham:

      * QAROR shu yerda qabul qilinadi. Brauzerda qolsa, server nima uchun
        uyg'onmaganini bilmasdi va moslashtirgichni sozlash uchun frontend
        obrazini har safar qayta yig'ish kerak bo'lardi.
      * Urinish YOZIB BORILADI - audio, transkript va sabab bir joyda.
        Aynan shu ma'lumot "juda aniq aytmasa uyg'onmaydi" degan muammoni
        taxmin bilan emas, dalil bilan tuzatish imkonini beradi.
      * Xato JIM. Hech kim hech narsa so'ramagan: navbat to'la bo'lsa yoki
        audio yaroqsiz bo'lsa, javob shunchaki "uyg'onmadi" bo'ladi. Har
        necha soniyada ekranda xato chiqishi sukunatdan yomonroq.
    """
    stt_language = LOCALE_TO_STT.get(language)
    if stt_language is None:
        raise bad_request(f"til qo'llab-quvvatlanmaydi: {language}")

    audio = file.file.read()
    if not audio or len(audio) > _WAKE_MAX_BYTES:
        raise bad_request("audio yaroqsiz")

    client = _pick(stt_language, settings.stt_wake_provider, wake=True)
    if client is _gapi_wake_client and not _wake_budget.allow(user.actorId):
        # Byudjet tugadi - RAD ETMAYMIZ, 1-variant bilan davom etamiz.
        # Foydalanuvchi buni sezmaydi: Router uyg'otishni bepul va tezroq
        # tekshiradi. Sezilishi kerak bo'lgan joy - `/api/health/detail`.
        client = _router_client

    try:
        result = _transcribe_with_fallback(
            client,
            audio,
            stt_language,
            file.content_type or "audio/wav",
            yol="Uyg'otish",
            # Uyg'otish uchun ATAYLAB qisqa: parcha har 2.5 sekundda keladi,
            # ya'ni 100 sekundlik byudjetning bu yerda ma'nosi yo'q. 12 s =
            # GAPI ning 8 s deadline'i + Router uchun zaxira.
            budget=12.0,
            op="wake",
        )
    except SttError as exc:
        # Uyg'otish tekshiruvi FON ishi: 503 (navbat to'la) bu yerda odatiy
        # hol va uni xato sifatida ko'rsatish noto'g'ri bo'lardi.
        # `actorId`, `email` EMAS: uyg'otish yo'li shaxsiy ma'lumotni
        # ataylab eng kam saqlaydigan yo'l (uyg'otish jurnali ham faqat
        # `actor_id` yozadi), bu satr esa istisno bo'lib qolgan edi.
        log.info("Uyg'otish tekshiruvi o'tmadi (%s): %s", user.actorId, exc)
        # `checked=False`: bu "uyg'otish so'zi emas" degani EMAS, "tekshirib
        # bo'lmadi" degani. Klient buni ko'rib urinishlar oralig'ini
        # uzaytiradi - o'chgan backend'ni har ikki soniyada urib turishning
        # ma'nosi yo'q.
        return WakeResponse(text="", matched=False, reason="stt xatosi", checked=False)

    matched, reason = is_wake_phrase(result.text)
    if settings.wake_log_enabled:
        entry = _wake_log.record(
            audio,
            actor_id=user.actorId,
            language=stt_language,
            text=result.text,
            matched=matched,
            reason=reason,
            duration_sec=result.duration_sec,
            backend=result.backend,
        )
        flat = entry.flat
    else:
        flat = measure(audio)[3]
    # Buzilgan yozuvda "uyg'onmadi" ning aybi so'zda emas. Brauzer buni
    # foydalanuvchiga aytadi - darvozani (OS/drayver) faqat u o'chira oladi,
    # bizning hech qanday sozlamamiz unga yetmaydi.
    distorted = flat > FLAT_LIMIT
    # Matnning O'ZI jurnalga tushmaydi: u xodim aytgan gap, ya'ni shaxsiy
    # ma'lumot - jurnal esa `journalctl` orqali kengroq ko'rinadi va uzoq
    # saqlanadi. Ikkala STT klienti ham shu qoidaga amal qiladi (faqat
    # uzunlik yozadi), bu satr esa istisno bo'lib qolgan edi.
    #
    # Sozlash uchun kerakli transkript ALLAQACHON boshqariladigan joyda
    # turadi: `data/wake/wake.jsonl` (gitignore'da, faqat `actor_id`
    # bilan, eski yozuvlar o'chiriladi), va u `tools/wake_report.py` bilan
    # o'qiladi. `DEBUG=true` bo'lsa matn ko'rinadi - sozlash seansi uchun.
    shown = repr(result.text) if settings.debug else f"{len(result.text)} belgi"
    log.info("Uyg'otish: %s -> %s (%s)%s", shown, "HA" if matched else "yo'q", reason,
             f" BUZILGAN tekis={flat:.0%}" if distorted else "")
    return WakeResponse(text=result.text, matched=matched, reason=reason, distorted=distorted)

"""Chat endpointi.

Ikki yo'l bor va ular BIR-BIRINI ALMASHTIRMAYDI:

    POST /chat/stream   HR Assistant javobini OQIM bilan (asosiy yo'l)
    POST /chat/ask      quvur skeleti, bitta JSON (`services/pipeline.py`)

`/stream` - haqiqiy javob: yuqoridagi HR Assistant xizmatiga boradi, u
hujjatlar bo'yicha RAG va HRM ma'lumotini birlashtiradi. `/ask` esa
quvurning bosqichli ko'rinishini beradi va Assistant sozlanmagan muhitda
(masalan lokal ishlab chiqishda) frontend to'liq ishlashi uchun qoladi.

`/stream` yordamchining qaysi DVIGATELIGA borishini admin panel hal qiladi
(`services/engine_control.py`): odamga berilgan versiya, kanal siyosati,
umumiy siyosat, oxiri `.env`. Klient tanlovi (`engine`) faqat odamga
ruxsat berilgan bo'lsa ishlaydi - `GET /chat/engines` nima tanlash mumkinligini
aytadi. Kadrlar O'ZGARISHSIZ o'tadi; `done` da `engine` va (so'ralgan
bo'lsa) `pro`.

Mantiq bu faylda YO'Q: `services/integrations/assistant.py` da.
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import re
import threading
import time
import unicodedata
import urllib.parse
from collections import deque
from collections.abc import Callable, Iterator

import jwt
from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ...core import engines as _engines
from ...core.channels import channel_of
from ...core.config import ollama_key_now, platform_tokens, settings
from ...core.errors import bad_request, error_status
from ...schemas.auth import AuthUser
from ...schemas.chat import AskRequest, FileLink, FileLinkRequest, PipelineResponse, StreamRequest
from ...schemas.engines import EngineChoice
from ...services import engine_control as _engine_control
from ...services.analytics import TurnRecorder, bind, carry, redact
from ...services.integrations.assistant import (
    ARTIFACT_KINDS,
    AnswerStream,
    AssistantClient,
    AssistantError,
    artifact_ref_ok,
)
from ...services import contacts_chat
from ...services.hold import HoldVoices, keyword_topic, pick
from ...services.integrations.crm_auth import CrmAuth
from ...services.integrations.ollama import HoldClassifier
from ...services.pipeline import pipeline
from . import connectors as _connectors
from ..deps import current_user

#: Javob sarlavhasi: Venera'ning SAVOL kaliti (`turns.id`). Klient uni
#: shikoyatga (`/reports` `turnId`) va ovozga (`/tts/speak`) qo'shadi -
#: admin panelda savol, javob, ovoz va shikoyat bitta kalit bilan bog'lanadi.
TURN_HEADER = "X-Venera-Turn"

log = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

#: CRM sessiyasi - o'zini o'zi yangilab turadi (`crm_auth.py`).
#:
#: Bitta obyekt: refresh_token ROTATSIYA qiladi, ya'ni ikki nusxa
#: bo'lsa ular bir-birining tokenini bekor qilib, har savolda paroldan
#: login qilishga tushib qolardi. Hujjat ham shuni aytadi: "one login
#: per agent process".
_crm = CrmAuth(
    settings.crm_base_url,
    settings.crm_username,
    settings.crm_password,
    settings.crm_refresh_file,
    timeout=settings.crm_timeout,
)

_assistant = AssistantClient(
    settings.hrm_assistant_base_url,
    settings.hrm_assistant_client_id,
    settings.hrm_assistant_client_secret,
    timeout=settings.hrm_assistant_timeout,
    max_concurrent=settings.hrm_assistant_max_concurrent,
    max_stream_seconds=settings.hrm_assistant_max_stream_seconds,
)

#: Ochilmagan oqimning ICHKI sababi -> savol izidagi `error_code`. Uchalasi
#: ham foydalanuvchiga bir xil "xizmat band" (503), admin esa farqini
#: ko'radi: BIZNING navbat to'la (yuqoriga borilmagan), xizmatga ulanib
#: bo'lmadi, yoki xizmatning o'zi 503 qaytardi. Qolgan sabablar -
#: avvalgidek umumiy `open_failed` (http statusi bilan).
OPEN_ERROR_CODES = frozenset({"queue_full", "upstream_unreachable", "upstream_busy"})


def open_error_code(exc: AssistantError) -> str:
    """Ochilmagan oqim uchun izdagi xato kodi."""
    reason = getattr(exc, "reason", None)
    return reason if reason in OPEN_ERROR_CODES else "open_failed"

#: Foydalanuvchiga ko'rinadigan xabarlar - status bo'yicha, ichki matnsiz.
#: Ichki host (`10.10.50.x`) va `X-Client-Secret` bu xabarlarga HECH QACHON
#: tushmaydi.
#:
#: 401/403 bu yerda ATAYLAB YO'Q. Ular "bizning ilova kredensialimiz
#: noto'g'ri" degani, ya'ni SOZLAMA xatosi; brauzerga 401 qaytarish
#: "sessiyangiz tugadi" degan ma'no berib, foydalanuvchini mutlaqo joyida
#: bo'lgan sessiyasidan chiqarib yuborardi. Ular 502 ga tushadi.
_MESSAGES = {
    400: "Savol qabul qilinmadi",
    404: "So'ralgan hujjat topilmadi",
    422: "Bu savolga javob berib bo'lmadi",
    501: "Savol-javob xizmati hali sozlanmagan",
    503: "Savol-javob xizmati band, biroz kutib qayta urinib ko'ring",
    504: "Javob juda uzoq cho'zildi",
    502: "Savol-javob xizmati javob bermadi",
}


#: Savolni tasniflaydigan model va tayyor ovozlar keshi.
#:
#: Ikkisi ham SHU MODULDA: kutish ovozi javob oqimining bir qismi, ya'ni vaqt
#: hisoblanadigan joyda turishi kerak. Klient tomonida bo'lsa, mantiq web va
#: Telegram uchun IKKI MARTA yozilardi - holbuki ikkisi ham ayni shu oqimni
#: o'qiydi. Klientlarning ishi faqat ovozni o'ynatish va javobni u tugaguncha
#: navbatda ushlab turish.
_hold_classifier = HoldClassifier(
    settings.ollama_base_url,
    ollama_key_now(),
    settings.ollama_model,
    timeout=settings.ollama_timeout,
    max_concurrent=settings.ollama_max_concurrent,
)
_hold_voices = HoldVoices(settings.hold_voice_dir)

#: Kutish ovozi faqat shu interfeys tillarida: TTS serverida faqat o'zbek
#: ovozlari bor. Rus va ingliz tilida tasnif ham chaqirilmaydi - pul bekor
#: ketmasin.
_HOLD_LOCALES = frozenset({"uz", "uz-Cyrl"})

#: Tasnif tayyor bo'lganini navbatga bildiruvchi belgi. Birinchi ovoz aynan
#: shu paytda aytiladi - timeout'ni kutmasdan.
_TASNIF_TAYYOR = object()


class _HoldLog:
    """Kutish ovozi nechta marta aytilgani va yorliq qayerdan kelgani.

    `/api/health/detail` uchun. Bu hisoblagich bo'lmaganda "ovoz aytilyaptimi"
    degan savolga faqat kodni o'qib taxmin qilish mumkin edi.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recent: deque[tuple[float, str]] = deque(maxlen=500)
        self._total = 0

    def record(self, manba: str) -> None:
        with self._lock:
            self._recent.append((time.monotonic(), manba))
            self._total += 1

    def snapshot(self) -> dict[str, object]:
        now = time.monotonic()
        with self._lock:
            oxirgi = [r for r in self._recent if now - r[0] <= 3600.0]
            out: dict[str, object] = {"total": self._total, "last_hour": len(oxirgi)}
            for manba in ("ollama", "jadval"):
                out[manba] = sum(1 for r in oxirgi if r[1] == manba)
            return out


_holds = _HoldLog()


class _HoldPlan:
    """Bitta ovozli savol uchun kutish ovozlari.

    TARTIB:
      * so'rov boshlanishi bilan tasnif PARALLEL ketadi (`start`);
      * tasnif kelishi bilan - BIRINCHI ovoz. Model `hold_first_ms` ichida
        ulgurmasa - kalit so'z jadvali tanlaydi va ovoz baribir aytiladi;
      * javob hali yo'q bo'lsa - har `hold_repeat_ms` da keyingi ovoz, eng
        ko'pi `hold_max` ta;
      * javobning birinchi `token` kadri kelishi bilan - to'xtaydi.

    Ovozni YARMIDA KESMASLIK klientning ishi: javob tayyor bo'lsa ham u joriy
    ovoz tugashini kutadi. Avvalgi versiyada aynan shu muammo o'lchangan edi -
    HRM javobi 3-4 sekundda kelardi, ovozning o'zi esa 2.5-3.3 sekund, va u
    yarmida kesilardi. Yarim kesilgan gap jimlikdan yomonroq.
    """

    def __init__(self, question: str, locale: str, recorder: TurnRecorder | None = None) -> None:
        self.question = question
        self.locale = locale
        self.started = time.monotonic()
        self.fired = 0
        self.stopped = False
        # (mavzu, ohang) va qayerdan kelgani: "ollama" yoki "jadval".
        self.label: tuple[str, str] | None = None
        self.source = ""
        self._model_done = threading.Event()
        self._started_model = False
        self._wake = None
        #: Savol izi (admin panel): tasnif qancha vaqt olgani va nima
        #: tanlagani. Kutish kadrlarining o'zini oqim qobig'i (`wrap`) yozadi.
        self.recorder = recorder

    # --- tasnif ------------------------------------------------------------

    def start(self) -> None:
        """Tasnifni PARALLEL boshlaydi - yuqoridagi xizmatga ULANISHDAN OLDIN.

        NEGA SHU QADAR ERTA. O'lchangan (2026-09-23): xizmat ulanishni ochib
        javob sarlavhalarini berguncha 0-2 sekund o'tadi, bizning oqim esa
        faqat undan KEYIN boshlanadi. Tasnif oqim ichida boshlanganda birinchi
        ovoz klientda 2.86 s da eshitildi, holbuki tasnifning o'zi 0.8 s.
        Ya'ni tasnif shu ulanish vaqtida parallel ishlashi kerak.

        Ikki marta chaqirilsa zarar yo'q.
        """
        if self._started_model:
            return
        self._started_model = True
        if not _hold_classifier.configured:
            if self.recorder is not None:
                self.recorder.point("hold.classify", skipped="not_configured")
            self._model_done.set()
            return

        def run() -> None:
            boshlandi = time.monotonic()
            natija = _hold_classifier.classify(self.question)
            if natija is not None:
                # Kech kelgan yorliq ham foydali: birinchi ovoz jadval bilan
                # aytilgan bo'lsa ham, KEYINGILARI endi aniqroq bo'ladi.
                self.label, self.source = natija, "ollama"
            if self.recorder is not None:
                mavzu, ohang = natija or (None, None)
                self.recorder.record_span(
                    "hold.classify", boshlandi, model=getattr(_hold_classifier, "model", None),
                    ok=natija is not None, topic=mavzu, tone=ohang)
            self._model_done.set()
            wake = self._wake
            if wake is not None:
                wake(_TASNIF_TAYYOR)

        # `carry`: yangi ip kontekstni meros olmaydi - usiz Ollama chaqiruvi
        # hisobda egasiz (kim, qaysi kanal, qaysi savol) qolardi.
        threading.Thread(target=carry(run), name="hold-classify", daemon=True).start()

    def attach(self, wake) -> None:
        """Navbatga ulanadi: tasnif tayyor bo'lganda `wake(belgi)` chaqiriladi.

        Uyg'otish YO'QOLMAYDI: tasnif `attach` dan oldin tugagan bo'lsa ham
        `next_wait` `_model_done` ni ko'rib darhol ovoz beradi.
        """
        self._wake = wake

    # --- oqimni kuzatish -----------------------------------------------------

    def saw(self, raw: bytes) -> None:
        """Javob boshlandimi? Faqat BAYT ichida qaraladi, JSON emas: bu har
        kadr uchun chaqiriladi, `token` kadrlari esa yuzlab bo'ladi."""
        if b'"type":"token"' in raw:
            self.stopped = True

    # --- vaqt ------------------------------------------------------------------

    def next_wait(self) -> float | None:
        """Keyingi ovozgacha qancha qoldi (soniya), yoki `None`."""
        if self.stopped or self.fired >= settings.hold_max:
            return None
        if self.fired == 0:
            if self._model_done.is_set():
                chegara = 0.0
            else:
                chegara = settings.hold_first_ms / 1000.0
        else:
            chegara = self.fired * settings.hold_repeat_ms / 1000.0
        return max(0.01, chegara - (time.monotonic() - self.started))

    def fire(self) -> bytes | None:
        """Kutish kadri (baytlar) yoki `None`."""
        if self.stopped or self.fired >= settings.hold_max:
            return None
        if self.label is None:
            # Model ulgurmadi yoki ishlamadi - ZAHIRA. Ohang ATAYLAB "oddiy":
            # jadval ohangni yomon o'qiydi va xavfli tomonga ("hozir",
            # bosh harfli qisqartma = "shoshilinch"), ya'ni shoshilmagan
            # odamga Venera'ni qo'pol qilib qo'yardi.
            self.label, self.source = (keyword_topic(self.question), "oddiy"), "jadval"
        orin = self.fired
        self.fired += 1
        mavzu, ohang = self.label
        if orin == 0:
            matn, kalit = pick(mavzu, ohang, "ilk")
        else:
            matn, kalit = pick(mavzu, ohang, "davom", orin - 1)
        if not _hold_voices.ready(kalit):
            # Ovozi yo'q gap AYTILMAYDI: matnni klientda sintez qilish 1.1
            # sekund qo'shadi, tayyor ovozning ma'nosi esa aynan kechikishning
            # yo'qligida. Bu faqat qayta ishga tushgandan keyingi ~50 sekundda
            # bo'ladi (ovozlar fonda sintez qilinayotganda).
            log.info("Kutish ovozi %d o'tkazib yuborildi: %s hali tayyor emas",
                     self.fired, kalit)
            if self.recorder is not None:
                self.recorder.point("hold.skip", at=self.fired, clip=kalit, reason="not_ready")
            return None
        _holds.record(self.source)
        # Matnning o'zi yozilmaydi (u kodda turadi) - faqat nima tanlangani.
        log.info("Kutish ovozi %d: %s|%s (%s), %.1f s kutildi",
                 self.fired, mavzu, ohang, self.source, time.monotonic() - self.started)
        payload = {
            "type": "hold",
            "text": matn,
            "clip": kalit,
            "at": self.fired,
            "topic": mavzu,
            "source": self.source,
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"


def _with_hold(answer, plan: _HoldPlan):
    """Kadrlarni uzatadi va JIMLIK paytida kutish ovozini qo'shadi.

    NEGA NAVBAT VA ALOHIDA IP. `for raw in answer.frames` kadr kelmaguncha
    bloklaydi - kutish ovozi esa aynan KADR KELMAGANDA kerak. Navbatda
    uchta manba uchrashadi: javob kadrlari, "tasnif tayyor" belgisi va
    timeout (jimlik). Timeout aynan "hali javob yo'q" signali.

    Xato navbatdan O'TIB chaqiruvchida ko'tariladi: xato kadri va `done` ni
    yozadigan mantiq allaqachon o'sha yerda.
    """
    navbat: queue.Queue = queue.Queue()
    TUGADI = object()

    def pump() -> None:
        try:
            for raw in answer.frames:
                navbat.put(raw)
        except BaseException as exc:                         # noqa: BLE001
            navbat.put(exc)
        finally:
            navbat.put(TUGADI)

    # `carry` - hisob konteksti (kim, kanal, savol) ipga ham o'tsin.
    threading.Thread(target=carry(pump), name="chat-stream", daemon=True).start()
    # AVVAL ulanish, keyin (hali boshlanmagan bo'lsa) tasnif - aks holda
    # tasnif ulanishdan oldin tugab, uyg'otish yo'qolardi. `next_wait` baribir
    # `_model_done` ni tekshiradi, ya'ni bu ikkinchi to'r.
    plan.attach(navbat.put)
    plan.start()
    while True:
        try:
            element = navbat.get(timeout=plan.next_wait())
        except queue.Empty:
            kadr = plan.fire()
            if kadr:
                yield kadr
            continue
        if element is TUGADI:
            return
        if element is _TASNIF_TAYYOR:
            # Birinchi ovoz hali aytilmagan bo'lsa - DARHOL. Keyingilari
            # o'z vaqtida (timeout orqali) aytiladi.
            if plan.fired == 0:
                kadr = plan.fire()
                if kadr:
                    yield kadr
            continue
        if isinstance(element, BaseException):
            raise element
        plan.saw(element)
        yield element


def _hold_plan(body: StreamRequest, recorder: TurnRecorder | None = None) -> _HoldPlan | None:
    """Kutish rejasi kerakmi?

    To'rt shart, to'rttasi ham kerak: sozlama yoqilgan; klient OVOZLI
    rejimda (matnli chatda kutish ko'rinib turadi, ovoz shovqin bo'lardi);
    interfeys o'zbekcha (TTS faqat o'zbekcha); va savol bor.
    """
    if not settings.hold_enabled or not body.voice:
        return None
    if body.locale not in _HOLD_LOCALES or not body.question.strip():
        return None
    return _HoldPlan(body.question, body.locale, recorder)


def assistant_user_id(user: AuthUser) -> str:
    """Yuqoridagi xizmat uchun kimlik: `venera:{actorId}`.

    BITTA JOYDA, ataylab: suhbat xotirasi (`/chat/stream`), taklifni
    tasdiqlash (`/actions`) va suhbatlar tarixi (`/chats`) hammasi shu
    kalit bilan ishlaydi. Biri farq qilsa, odam o'z suhbatini ko'rmay
    qolardi yoki taklifini tasdiqlay olmasdi. Prefiks bilan: xizmat bir
    nechta ilovaga xizmat qiladi va `user_id` lar aralashib ketmasligi kerak.
    """
    return f"venera:{user.actorId}"


def _live_tokens(user: AuthUser) -> dict[str, str]:
    """Yuboriladigan platforma token'lari.

    USTUNLIK: foydalanuvchining O'Z ulanishi (`/api/v1/connectors`, "+"
    menyusi) HAMMASIDAN USTUN. U HRM yoki CRM ga o'z logini bilan kirgan
    va kalit yoqiq bo'lsa, o'sha platforma uchun FAQAT uning tokeni ketadi
    - shunda "men" degani haqiqatan o'sha odam. Kalit o'chiq, ulanmagan
    yoki muddati tugagan bo'lsa platforma xaritada bo'lmaydi va pastdagi
    UMUMIY manbalar ishlaydi (ular VAQTINCHALIK, `core/config.py`).

    Umumiy CRM tokeni ikki manbadan kelishi mumkin, va sozlangan bo'lsa
    `CrmAuth` UNI TO'LIQ EGALLAYDI:

      1. `CrmAuth` sozlangan (`CRM_BASE_URL` + login/parol) - CRM tokeni
         FAQAT undan olinadi. U 300 sekundlik tokenni o'zi yangilaydi,
         ya'ni qo'l tegmaydi.
      2. Sozlanmagan - `.env` dagi qo'lda yozilgan `crm_token` ishlatiladi.
         U amalda ishlamaydi (yopishtirib bo'lguncha 5 daqiqasi tugaydi),
         lekin sozlama to'lmaguncha butunlay ishsiz qolishdan yaxshiroq.

    NEGA ZAHIRAGA TUSHMAYMIZ. Avval "CrmAuth token bermasa `.env`
    dagisini ishlatamiz" deb yozilgan edi, va jonli tekshiruvda bu ALDAB
    QO'YDI: CRM login xatosi ("Account is not fully set up") o'rniga
    foydalanuvchi eskirgan `.env` tokeni tufayli `auth_expired` oldi -
    ya'ni "sessiyangiz tugagan" degan butunlay boshqa sabab ko'rsatildi.
    Token YUBORMASLIK esa halol `auth_missing` beradi ("CRM tizimiga
    kiring"), va haqiqiy sabab `/api/health` da turadi.
    """
    tokens = platform_tokens()
    if _crm.configured:
        crm = _crm.token()
        # Egalik TO'LIQ: sessiya yiqilgan bo'lsa ham `.env` dagi eskirgan
        # qiymat ishlatilmaydi.
        tokens.pop("crm", None)
        if crm:
            tokens["crm"] = crm
    # Odamning o'z tokenlari - CRM niki shu yerda, so'rov oldidan
    # yangilanadi (300 s yashaydi), HRM niki muddati yetarli bo'lsagina.
    tokens.update(_connectors.hub.tokens(str(user.actorId)))
    return tokens


def effective_engine(user: AuthUser | None, channel: str | None,
                     requested: object = None) -> str:
    """Shu odam va kanal uchun yordamchi dvigateli. Web, mini app, bot,
    `/chat/ask` va `/pro/quota` BITTA qoidadan foydalanadi -
    `services/engine_control.py` (admin panel qarorlari, keyin `.env`)."""
    return _engine_control.effective_engine(user, channel, requested)


def engine_for(channel: str | None) -> str:
    """Kanalning "hamma uchun" dvigateli (odamga alohida versiya berilmagan
    bo'lsa). Eski chaqiruvchilar uchun; yangi kod `effective_engine` ni
    odam bilan chaqiradi."""
    return _engine_control.effective_engine(None, channel)


@router.get("/engines", response_model=EngineChoice)
def engines(request: Request, user: AuthUser = Depends(current_user)) -> EngineChoice:
    """Shu odam, shu kanalda (`X-Venera-Client`) qaysi dvigatel ishlaydi va
    u nimani tanlay oladi. Tanlov `selectable` bo'lsagina ko'rsatiladi;
    tanlangan qiymat `/chat/stream` tanasidagi `engine` bilan yuboriladi.

    `async def` EMAS: qoida analitika omboridan o'qiladi (SQLite bloklaydi).
    """
    return EngineChoice(**_engine_control.client_view(user, channel_of(request)))


def open_stream(question: str, user: AuthUser, chat_id: str | None, *,
                mode: str = "standard", recorder: TurnRecorder | None = None,
                before_upstream: Callable[[], None] | None = None,
                channel: str | None = "api", engine: str | None = None) -> AnswerStream:
    """Savol -> javob oqimi: web, mini app va Telegram bot BITTA yo'ldan.

    Avval xodimlar ma'lumotnomasi (`services/contacts_chat.py`): kontakt
    savoli yoki tahriri bo'lsa javob shu yerda tayyorlanadi va yuqoridagi
    xizmatga BORMAYDI. Qolgan hamma savol - yordamchiga, SHU ODAM VA KANAL
    uchun tanlangan dvigatelga (`effective_engine`: odamga berilgan versiya,
    admin siyosati, oxiri `.env`).

    Qo'shimchalar (hammasi ixtiyoriy - bot ularsiz chaqiradi):

      * `channel` - so'rov kanali (web | miniapp | bot | desktop | api);
        dvigatel shundan tanlanadi;
      * `engine` - klient tanlagan dvigatel. Faqat odamga ruxsat berilgan
        bo'lsa ishlaydi, aks holda JIMGINA e'tiborsiz (xato emas);
      * `mode` - "Pro" (`/chat/stream` da klient aytadi). Kontakt javobiga
        TEGMAYDI: ma'lumotnoma javobi byudjetdan yemaydi va `pro` bloki
        bo'lmaydi. "Pro" FAQAT `v2` da: boshqa dvigatelda u JIMGINA
        tashlanadi (yuqoriga yuborilmaydi) va izga "so'ralgan, berilmagan,
        sabab `engine`" bo'lib yoziladi;
      * `recorder` - savol izi (admin panel): `contacts`, `tokens`,
        `assistant.open` oraliqlari shu yerda o'lchanadi;
      * `before_upstream` - savol yordamchiga ketishi ANIQ bo'lganda,
        ulanishdan OLDIN chaqiriladi. Web kutish rejasini shu yerda
        boshlaydi: tasnif ulanish bilan parallel ketadi, kontakt javobida
        esa kutish ovozi umuman kerak emas.

    Ulanish SHU YERDA ochiladi, generator ichida emas: 400/501/503 shunda
    oddiy `AssistantError` bo'lib chaqiruvchiga chiqadi.
    """
    with _span(recorder, "contacts") as info:
        local = contacts_chat.answer(question, user)
        info["answered"] = local is not None
    if local is not None:
        return local
    requested = engine
    choice = _engine_control.choose(user, channel, requested)
    engine = choice.engine
    if recorder is not None and choice.ignored:
        # Klient so'ragan versiya bu odamga berilmagan - izda ko'rinsin:
        # "nega men tanlagan versiya ishlamadi" degan savolga javob shu.
        recorder.point("engine.ignored", requested=str(requested)[:16], used=engine)
    if mode == "pro" and not _engines.pro_available(engine):
        # "Pro" bu dvigatelda yo'q: JIMGINA standart rejim. Klient buni
        # oldindan biladi (`/pro/quota` -> `available: false`) va tugmani
        # ko'rsatmaydi; bu yerga kelgani eski klient yoki qo'lda so'rov.
        # Izda xuddi yuqoridagi xizmat "bermadi" degandek, sababi bilan -
        # admin panel uni o'sha belgida ko'rsatadi.
        log.info("Pro so'raldi, lekin dvigatel %s (%s) - standart rejim",
                 engine or "versiyasiz", channel)
        mode = "standard"
        if recorder is not None:
            recorder.pro_result({"requested": True, "used": False, "calls": 0,
                                 "reason": "engine"})
    if recorder is not None:
        # TANLANGAN dvigatel (admin qarori / klient tanlovi qo'llangandan
        # KEYINGI - yuqoriga aynan shu ketadi). Javobning `done.engine` i
        # kelsa o'sha ustun bo'ladi; ochilmay qolgan savolda ham qaysi yo'lga
        # borilgani ko'rinsin.
        recorder.update(engine=engine)
    if before_upstream is not None:
        before_upstream()
    # PLATFORMA TOKENLARI: avval odamning O'Z ulanishi ("+" menyusi,
    # `/api/v1/connectors`), u yo'q bo'lsa `.env` dagi umumiy token / agent
    # sessiyasi - `_live_tokens` va `stream()` izohiga qara.
    #
    # Alohida oraliq: CRM sessiyasi shu yerda yangilanishi mumkin (yuzlab
    # ms) - izda "javob nega kech boshlandi" shu bilan ko'rinadi.
    with _span(recorder, "tokens") as info:
        tokens = _live_tokens(user)
        # Faqat NOMLAR - token qiymati izga HECH QACHON tushmaydi.
        info["platforms"] = sorted(tokens)
    with _span(recorder, "assistant.open") as info:
        answer = _assistant.stream(
            question,
            # KIMLIK TOKEN'DAN (`assistant_user_id`) - suhbat xotirasi va
            # tarixi shu kalit bo'yicha.
            user_id=assistant_user_id(user),
            chat_id=chat_id,
            tokens=tokens,
            # "PRO" - shu xabar uchun (klient aytadi, default `standard`).
            # KESHLANMAYDI va QAYTA URINILMAYDI: har bir "pro" savol
            # pulga tushadi va odamning byudjetidan yeydi (hujjat
            # talabi). Javobdagi `pro` bloki `done` kadrida o'zgarishsiz
            # brauzerga o'tadi - `_clean_frame` notanish maydonlarga
            # tegmaydi.
            mode=mode,
            max_chars=settings.hrm_assistant_max_question_chars,
            engine=engine,
        )
        info["requestId"] = answer.request_id
        info["engine"] = engine
    return answer


@contextlib.contextmanager
def _span(recorder: TurnRecorder | None, name: str) -> Iterator[dict]:
    """`recorder.span(name)` - yozib oluvchi bo'lmasa (bot) bo'sh lug'at."""
    if recorder is None:
        yield {}
        return
    with recorder.span(name) as info:
        yield info


def _fail(exc: AssistantError, user: AuthUser | str, what: str):
    """Xatoni log'ga yozadi va foydalanuvchiga xabarga o'giradi. `user` -
    sessiya egasi yoki (tokensiz havolada) havola egasining `actorId` si.

    Jurnalda ICHKI sabab ham (`[queue_full]`, `[upstream_busy]`, ...):
    foydalanuvchi uchun hammasi "xizmat band", jurnal o'qiydigan odam esa
    "bizning navbat to'la" va "xizmat 503 berdi" ni ajrata olishi kerak."""
    who = user if isinstance(user, str) else user.email
    log.warning("Assistant %s (%s) [%s]: %s", what, who,
                getattr(exc, "reason", None) or "-", exc)
    status = _user_status(exc)
    return error_status(status, _MESSAGES[status])


def _user_status(exc: AssistantError) -> int:
    """Foydalanuvchiga qaytadigan status - `_MESSAGES` da bo'lmasa 502."""
    return exc.status if exc.status in _MESSAGES else 502


@router.post(
    "/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/x-ndjson": {}},
                     "description": "Kadrlar oqimi: stage, sources, artifact, token, done"}},
)
def stream(body: StreamRequest, request: Request,
           user: AuthUser = Depends(current_user)) -> StreamingResponse:
    """Savol -> javob oqimi (NDJSON, har qatorda bitta JSON kadri).

    `async def` EMAS, ataylab: klient bloklaydigan `urllib` ishlatadi.
    Oddiy `def` bilan FastAPI uni threadpool'da bajaradi va event loop
    bo'sh qoladi - aks holda bitta uzun javob butun serverni to'xtatib
    qo'yardi.

    SAVOL IZI (admin panel) shu yerda boshlanadi - oqim ochilishidan OLDIN:
    ochilmasa ham (501/503) savol "xato" bo'lib, statusi bilan ko'rinsin.
    Iz yozish faqat navbatga qo'yadi - disk kutilmaydi, kadrlar kechikmaydi.
    """
    channel = channel_of(request)
    rec = TurnRecorder(user, channel, "chat", body.question,
                       chat_id=body.chatId, locale=body.locale,
                       # Qanday kiritilgani (`input`), bo'lmasa ovozli rejim -
                       # `StreamRequest.input` izohiga qara.
                       input_mode=body.input or body.voice)
    if body.mode == "pro":
        # "Pro" so'ralgani izda: yuqoridagi xizmat haqiqatan bergani va
        # byudjet qoldig'i esa `done` kadridagi `pro` blokidan (`pro` kadri).
        rec.point("pro.requested", mode=body.mode)
    # Shu ipdagi hamma hisob (tokenlar yangilanishi, ulanish, tasnif ipi)
    # shu savolga yoziladi. Oqim qadamlarini esa `rec.wrap` o'zi bog'laydi.
    binding = rec.bind()
    plan: _HoldPlan | None = None

    def start_hold() -> None:
        # Kutish rejasi va tasnif ENG BOSHIDA, yuqoridagi xizmatga ulanishdan
        # OLDIN: ulanishning o'zi 0-2 sekund oladi va tasnif shu vaqtda parallel
        # ishlaydi (`_HoldPlan.start` izohida o'lchov). Kontakt javobida
        # chaqirilmaydi - javob darhol, kutish ovozi kerak emas.
        nonlocal plan
        plan = _hold_plan(body, rec)
        if plan is not None:
            plan.start()

    try:
        try:
            # Web, mini app va bot BITTA yo'ldan (`open_stream`): avval xodimlar
            # ma'lumotnomasi, keyin yordamchi.
            #
            # PLATFORMA TOKENLARI: avval odamning O'Z ulanishi ("+"
            # menyusi, `/api/v1/connectors`), u yo'q bo'lsa `.env` dagi
            # umumiy token / agent sessiyasi - `_live_tokens` ga qara.
            # Umumiy token VAQTINCHALIK va oqibati bor: xizmat hujjatiga
            # ko'ra token bilan "men" degani TOKEN EGASI. O'z hisobi bilan
            # kirgan odam uchun bu muammo yo'q.
            #
            # HAMMA token yuboriladi, tanlab emas: hujjat talabi - "send
            # every token the user has, the assistant decides per question
            # which platform it needs". Savol HRM haqidami yoki CRM
            # haqidami, buni yuqoridagi xizmat o'zi hal qiladi (`route`).
            #
            # `platform_tokens()`, `settings` EMAS: sessiyalar bir necha
            # daqiqada tugaydi, ya'ni tokenlar tez-tez almashadi. Sozlama
            # obyekti faylni faqat import paytida o'qigan bo'lardi va
            # yangi qiymat uchun restart kerak bo'lardi - har necha
            # daqiqada restart esa oqib turgan javoblarni kesardi.
            #
            # Token yo'q platforma haqidagi savol `auth_missing` bilan
            # qaytadi ("CRM tizimiga kiring"), qolgani esa ishlaydi.
            #
            # Oqim SHU YERDA ochiladi, generator ichida emas: 400/501/503
            # shunda ODDIY HTTP javobi bo'lib chiqadi. Generator ichida
            # ochilsa, 200 allaqachon ketgan bo'lardi va xato brauzerga
            # "uzilgan oqim" bo'lib ko'rinardi.
            #
            # DVIGATEL - odam va kanal bo'yicha (`effective_engine`): admin
            # panel qarori, klient tanlovi (`engine`, faqat ruxsat bo'lsa),
            # oxiri `.env`. Mini App ham shu yo'ldan (kanal `miniapp`).
            answer = open_stream(body.question, user, body.chatId, mode=body.mode,
                                 recorder=rec, before_upstream=start_hold, channel=channel,
                                 engine=body.engine)
        except AssistantError as exc:
            # Sabab bo'yicha kod: `queue_full` / `upstream_unreachable` /
            # `upstream_busy`, qolgani `open_failed` (`open_error_code`).
            rec.error_code = open_error_code(exc)
            rec.finish("error", http_status=_user_status(exc), error=exc)
            failure = _fail(exc, user, "savol")
            # Xato javobida ham savol kaliti: klient shikoyatga qo'sha oladi.
            failure.headers = {**(failure.headers or {}), TURN_HEADER: rec.turn_id}
            raise failure from exc
        except BaseException as exc:
            rec.finish("error", error=exc)
            raise
    finally:
        binding.reset()
    rec.update(request_id=answer.request_id)

    def frames():
        # OQIM IKKI MANBADAN: yuqoridagi xizmatning kadrlari va BIZNING
        # vaqt bo'yicha qo'shadigan kutish kadrlarimiz (`_with_hold`).
        try:
            if plan is None:
                # Kutish gapi kerak emas (matnli rejim yoki o'chirilgan) -
                # eski, sodda yo'l. Ip ham, navbat ham yaratilmaydi: bu
                # yo'l hamma matnli savollar uchun ishlaydi va unga
                # keraksiz murakkablik qo'shishning ma'nosi yo'q.
                yield from answer.frames
            else:
                yield from _with_hold(answer, plan)
        except AssistantError as exc:
            # Oqim o'rtasida uzildi. Statusni endi o'zgartirib bo'lmaydi
            # (200 ketib bo'lgan), shuning uchun brauzerga XATO KADRI
            # yuboriladi: u shu shaklni allaqachon tushunadi, ya'ni
            # "javob yarim qoldi" holati uchun alohida yo'l kerak emas.
            log.warning("Assistant oqimi (%s): %s", user.email, exc)
            status = _user_status(exc)
            # Izga ICHKI sabab (timeout, uzilish) - foydalanuvchi faqat
            # umumiy xabarni ko'radi, admin esa nima bo'lganini.
            rec.point("assistant.broken", status=exc.status, error=redact(exc))
            yield (b'{"type":"error","code":"stream_broken","text":'
                   + _json_text(_MESSAGES[status]) + b'}\n')
            yield b'{"type":"done","route":null}\n'
        finally:
            # Slot va ulanish SHU YERDA ham qaytadi (idempotent): klient
            # uzilib, ichki oqim hali BOSHLANMAGAN bo'lsa uning o'z `finally`
            # si hech qachon ishlamaydi - `AnswerStream.close` izohi.
            close = getattr(answer, "close", None)
            if callable(close):
                close()
            log.info("Assistant javobi (%s): request_id=%s natija=%s",
                     user.email, answer.request_id, answer.outcome or "-")

    return StreamingResponse(
        # `wrap` - kadrlarni O'ZGARTIRMASDAN va BUFERSIZ uzatadi, yo'l-yo'lakay
        # izga yozadi (kutish kadrlari ham, xato kadri ham) va oxirida savolni
        # yakunlaydi: klient uzilsa `cancelled`, xato kadri bo'lsa `error`.
        rec.wrap(frames()),
        media_type="application/x-ndjson",
        headers={
            # Javob shu odamga xos - proksi yoki brauzer keshiga tushmasin.
            "Cache-Control": "no-store",
            # Audit kaliti: aynan shu qiymat yuqoridagi xizmat jurnalida
            # ham turadi, ya'ni "shu javob nega bunday" degan savolni
            # ikki tizimda BITTA kalit bilan izlash mumkin.
            "X-Venera-Request-Id": answer.request_id,
            TURN_HEADER: rec.turn_id,
            # nginx uchun: bu yo'lda buferlash O'CHIQ bo'lishi kerak, aks
            # holda kadrlar to'planib, bir yo'la beriladi va oqimning
            # ma'nosi qolmaydi. `location` sozlamasi asosiy, bu qo'shimcha.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/artifact/{token}/{kind}", response_class=StreamingResponse)
def artifact(
    token: str = Path(max_length=256, description="Xizmat bergan bir martalik kalit"),
    kind: str = Path(description=" | ".join(ARTIFACT_KINDS)),
    user: AuthUser = Depends(current_user),
) -> StreamingResponse:
    """Yaratilgan ariza fayli (DOCX/PDF).

    NEGA PROKSI. Fayl yuqoridagi xizmatning ICHKI manzilida turadi -
    brauzer unga yetib bormaydi. Havolani o'z yo'limizga o'girib
    (`_rewrite_artifact`), faylni o'zimiz olib beramiz. Yon foydasi:
    yuklab olish Venera sessiyasini talab qiladi.
    """
    return _file(lambda: _assistant.fetch_artifact(token, kind), user, "artifact")


@router.get("/doc/{doc_id}", response_class=StreamingResponse)
def doc(
    doc_id: str = Path(max_length=128, description="Iqtibos qilingan hujjat kaliti"),
    user: AuthUser = Depends(current_user),
) -> StreamingResponse:
    """Javobda `[1]`, `[2]` deb iqtibos qilingan hujjatning PDF'i.

    Bank muhitida bu majburiy: xodim javobga ishonmasa, ASL hujjatni
    o'sha yerda ocha olishi kerak.
    """
    return _file(lambda: _assistant.fetch_doc(doc_id), user, "doc")


def _file(open_it, user: AuthUser | str, what: str, *,
          disposition: str | None = None, headers: dict[str, str] | None = None) -> StreamingResponse:
    """Fayl oqimi uchun umumiy qobiq - uchala endpoint uchun bir xil."""
    who = user if isinstance(user, str) else user.email
    try:
        content_type, filename, chunks = open_it()
    except AssistantError as exc:
        raise _fail(exc, user, what) from exc

    def body():
        try:
            yield from chunks
        except AssistantError as exc:
            # 200 ketib bo'lgan - ulanishni tugatamiz, brauzer buni
            # tugallanmagan yuklab olish deb ko'radi. Sabab log'da.
            log.warning("Assistant fayl oqimi (%s): %s", who, exc)

    return StreamingResponse(
        body(),
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            # `inline` EMAS, `attachment`: fayl yuqoridagi xizmatdan
            # keladi va uni Venera originida sahifa sifatida ochish
            # ortiqcha xavf bo'lardi. Nomi `_filename` da tozalangan.
            "Content-Disposition": disposition or f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            **(headers or {}),
        },
    )


# --- Telegram: tokensiz yuklab olish havolasi --------------------------------
#
# NEGA KERAK. Telegram mini app'da faylni Telegram ilovasining O'ZI yuklaydi
# (`WebApp.downloadFile`, Bot API 8.0) - va u bizning `Authorization`
# sarlavhamizni yubora olmaydi. WebView ichida `blob:` + `<a download>` esa
# ishonchsiz: iOS uni umuman bajarmaydi. Shuning uchun sessiya egasi avval
# QISQA MUDDATLI imzolangan havola oladi, Telegram esa faylni shu havoladan
# tokensiz yuklaydi.
#
# HAVOLA KIRISH TOKENI EMAS. U boshqa `aud` bilan imzolanadi: `verify_token`
# `aud` li tokenni rad etadi (API'ga kira olmaydi), bu yerdagi tekshiruv esa
# `aud` siz kirish tokenini rad etadi. Havola FAQAT bitta fayl, bitta tur va
# `_FILE_LINK_TTL` soniya uchun.

#: Odam "yuklab olish" ni bosadi, Telegram o'z oynasini ko'rsatadi, rozi
#: bo'lgach faylni oladi - bu soniyalar ishi. 10 daqiqa chalg'igan odamga
#: ham yetadi, havola esa jurnalda yoki ekran rasmida qolsa uzoq yashamaydi.
_FILE_LINK_TTL = 600
_FILE_AUDIENCE = "venera:file"
#: Faqat haqiqiy fayllar: `preview` - sahifa ichidagi ko'rinish, yuklanmaydi.
_LINK_KINDS = ("docx", "pdf")
#: Telegram Web (`web.telegram.org/k`, `/a`) faylni brauzer ichida `fetch`
#: bilan oladi, ya'ni CORS kerak - rasmiy hujjat talabi.
_TELEGRAM_WEB = "https://web.telegram.org"


def _download_name(requested: str | None, kind: str) -> str:
    """Saqlanadigan nom: klient taklifi (sarlavhadan), TOZALANGAN; kengaytma
    TUR bo'yicha - klientdan kelgani hisobga olinmaydi."""
    base = re.sub(r"\.(docx|pdf)$", "", (requested or "").strip(), flags=re.IGNORECASE)
    base = re.sub(r"[^\w.' -]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip(" .-_'")[:80]
    return f"{base or 'hujjat'}.{kind}"


def _attachment(filename: str) -> str:
    """`Content-Disposition` - RFC 6266: ASCII nom + `filename*` (UTF-8).

    Faqat `filename="..."` yetmaydi: sarlavhalar latin-1 da ketadi va
    o'zbekcha `ʻ` yoki kirill harfli nom javobni 500 ga aylantirardi.
    """
    stem, _, ext = filename.rpartition(".")
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    # Kirillcha nomdan ASCII da hech narsa qolmaydi - `.docx` (yashirin fayl
    # ko'rinishi) o'rniga "hujjat.docx".
    ascii_stem = re.sub(r"[^A-Za-z0-9.' _-]+", "_", ascii_stem).strip(" ._") or "hujjat"
    ascii_name = f"{ascii_stem}.{ext}"
    return (f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{urllib.parse.quote(filename, safe='')}")


@router.post("/artifact/{token}/{kind}/link", response_model=FileLink)
def artifact_link(
    body: FileLinkRequest | None = None,
    token: str = Path(max_length=256, description="Xizmat bergan kalit"),
    kind: str = Path(description=" | ".join(_LINK_KINDS)),
    user: AuthUser = Depends(current_user),
) -> FileLink:
    """Telegram uchun: tokensiz ochiladigan, 10 daqiqalik yuklab olish havolasi.

    Fayl bu yerda OLINMAYDI - faqat havola imzolanadi. Kalit yaroqsiz yoki
    muddati o'tgan bo'lsa, buni yuklab olishning o'zi aytadi (404).
    """
    if kind not in _LINK_KINDS or not artifact_ref_ok(token, kind):
        raise bad_request("Bu faylni yuklab bo'lmaydi")
    filename = _download_name(body.filename if body else None, kind)
    now = int(time.time())
    signed = jwt.encode(
        {"aud": _FILE_AUDIENCE, "iat": now, "exp": now + _FILE_LINK_TTL,
         "art": token, "kind": kind, "fn": filename, "uid": user.actorId},
        settings.secret_key, algorithm="HS256",
    )
    log.info("Fayl havolasi (%s): %s, %d s", user.actorId, kind, _FILE_LINK_TTL)
    return FileLink(url=f"/api/v1/chat/file/{signed}", filename=filename, expiresIn=_FILE_LINK_TTL)


@router.api_route("/file/{signed}", methods=["GET", "HEAD"], response_class=StreamingResponse)
def file_by_link(signed: str = Path(max_length=4096, description="`/link` bergan imzo")) -> StreamingResponse:
    """Imzolangan havola bo'yicha fayl - SESSIYASIZ (Telegram yuklab olgichi uchun).

    HEAD ham qabul qilinadi: ba'zi yuklab olgichlar avval hajmni so'raydi.
    """
    try:
        claims = jwt.decode(signed, settings.secret_key, algorithms=["HS256"],
                            audience=_FILE_AUDIENCE,
                            options={"require": ["exp", "aud", "art", "kind"]})
    except jwt.ExpiredSignatureError as exc:
        raise error_status(410, "Havola muddati tugagan - chatdan qayta yuklab oling") from exc
    except jwt.PyJWTError as exc:
        # Buzilgan, boshqa kalit bilan imzolangan yoki kirish tokeni - farqi
        # tashqariga aytilmaydi.
        raise error_status(404, "Fayl topilmadi") from exc
    kind, token = str(claims["kind"]), str(claims["art"])
    if kind not in _LINK_KINDS:
        raise error_status(404, "Fayl topilmadi")
    filename = _download_name(str(claims.get("fn") or ""), kind)
    who = f"havola:{claims.get('uid', '?')}"
    log.info("Fayl havola orqali (%s): %s", who, kind)
    # Sessiya yo'q, lekin kimligi imzoda (`uid`), havolani esa faqat mini app
    # so'raydi - yuklab olish hisobda egasi va kanali bilan tursin.
    with bind(claims.get("uid"), "miniapp"):
        return _file(
            lambda: _assistant.fetch_artifact(token, kind), who, "artifact",
            disposition=_attachment(filename),
            headers={
                "Access-Control-Allow-Origin": _TELEGRAM_WEB,
                "Access-Control-Expose-Headers": "Content-Disposition",
                # Havola manzilda turadi - u boshqa saytga Referer bilan chiqmasin.
                "Referrer-Policy": "no-referrer",
            },
        )


def _json_text(text: str) -> bytes:
    """Matnni JSON satriga o'giradi - qo'lda yasalgan kadr uchun."""
    return json.dumps(text, ensure_ascii=False).encode("utf-8")


@router.post("/ask", response_model=PipelineResponse)
async def ask(
    data: AskRequest,
    request: Request,
    response: Response,
    user: AuthUser = Depends(current_user),
) -> PipelineResponse:
    """Savol -> quvur -> javob (bosqichli, bitta JSON).

    Foydalanuvchi TOKEN'dan olinadi, so'rov tanasidan emas: `access`
    bosqichi shu shaxs bo'yicha huquq tekshiradi.

    Bu yo'l ham izga yoziladi (`kind=ask`): Assistant sozlanmagan muhitda
    frontend shu yerdan ishlaydi va admin panel u yerdagi savollarni ham
    ko'rishi kerak.

    `engine` - `/stream` dagi AYNI qoida (`effective_engine`): quvur
    yordamchiga bormaydi, lekin savol izida odam qaysi versiyada ekani
    turadi - klient ikkala yo'lga bir xil tana yuboradi va admin panel
    dvigatellar statistikasi ikki xil ma'noga ega bo'lmasin.
    """
    channel = channel_of(request)
    rec = TurnRecorder(user, channel, "ask", data.question)
    response.headers[TURN_HEADER] = rec.turn_id
    # Threadpool'da: kesh eskirgan bo'lsa qoida SQLite'dan o'qiladi, bu esa
    # `async` endpointda voqealar siklini to'xtatardi.
    rec.update(engine=await run_in_threadpool(effective_engine, user, channel, data.engine))
    try:
        with rec.bind(), rec.span("pipeline") as info:
            result = await pipeline.ask(data.question, user)
            info["finalStatus"] = result.finalStatus
    except BaseException as exc:
        rec.finish("error", error=exc)
        raise
    _record_pipeline(rec, result)
    return result


def _record_pipeline(rec: TurnRecorder, result: PipelineResponse) -> None:
    """Quvur natijasi izga: bosqichlar qarori (nuqta), manbalar va javob.

    Manbalar `sources` kadri shaklida beriladi - `turn_sources` ga oqimdagi
    kabi yassilanadi (`documentId`, `rerankScore` ni recorder taniydi).
    """
    orchestrator = result.orchestrator
    rec.point(
        "pipeline.result",
        finalStatus=result.finalStatus,
        domain=result.domain,
        guard=result.guard.decision if result.guard else None,
        intent=result.intent.intent if result.intent else None,
        target=orchestrator.targetModule if orchestrator else None,
        access=result.access.decision if result.access else None,
    )
    chunks = result.retrieval.results if result.retrieval else []
    if chunks:
        rec.observe({"type": "sources",
                     "items": [chunk.model_dump(exclude_none=True) for chunk in chunks]})
    rec.update(route=(orchestrator.route or None) if orchestrator else None,
               answer=result.answer or "")
    rec.finish("ok")

"""HR Assistant klienti - savol -> javob OQIMI (NDJSON).

Yuqoridagi xizmat: BRB-TECH HR Assistant API 3.1 (`/api/chat/stream`). U
o'z ichida hujjatlar bo'yicha RAG va HRM connector'ini birlashtiradi, ya'ni
Venera uchun bu BITTA endpoint - savolni yuboramiz, javobni bo'lak-bo'lak
olamiz.

NEGA OQIM VA `/api/chat` EMAS. Bitta javob to'liq yozilishini kutish LLM
uchun o'n soniyalar. Oqimda birinchi so'z darhol keladi va odam javob
yozilayotganini KO'RADI. Hujjat ham shuni talab qiladi: "proxy it
pass-through: no redirect, no buffering, no compression".

NEGA BRAUZER TO'G'RIDAN-TO'G'RI BORMAYDI. Uch sabab, har biri yetarli:

  1. `X-Client-Secret` - ILOVANING siri. Frontend o'zi yuborsa, sir JS
     bundle'ida va tarmoq panelida ochiq turardi.
  2. `10.10.50.4` ICHKI manzil. Brauzer unga umuman yetib bormaydi
     (foydalanuvchi `llm.brb-tech.uz` orqali keladi), va ichki topologiya
     tashqariga chiqmasligi kerak.
  3. KIMLIK. `user_id` server tomonidan, Venera token'idan qo'yiladi -
     aks holda klient o'zini boshqa xodim deb tanishtirib, o'sha odamning
     suhbat tarixiga kirardi (xotira `(user_id, chat_id)` bo'yicha).

KADRLAR (frames), hujjat bo'yicha shu tartibda:

    stage     -> o'tkinchi holat ("hujjatlar qidirilmoqda"), bir nechta
    sources   -> iqtiboslar va HRM chaqiruvlari, bitta
    artifact  -> yaratilgan ariza fayli (bo'lishi shart emas)
    token     -> javob matni bo'laklari, ko'p
    done      -> yakun: `route`, `request_id`
    error     -> tokenlar O'RNIGA keladi, keyin `done`

FAYL HAVOLALARI QAYTA YOZILADI. `artifact` kadridagi `docx_url` yuqoridagi
serverning ICHKI manzilini ko'rsatadi - brauzer uni ocholmaydi. Shuning
uchun ular Venera'ning o'z yo'llariga o'giriladi (`_rewrite_artifact`), va
faylni Venera o'zi olib beradi (`fetch_artifact`). Xuddi shu narsa
iqtibos qilingan hujjat PDF'i uchun ham (`fetch_doc`).
"""

from __future__ import annotations

import base64
import contextlib
import http.client
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from dataclasses import dataclass, field
from socket import timeout as socket_timeout
from typing import Any, Iterator

log = logging.getLogger(__name__)

#: Kadr turlari. Notanish turlar O'TKAZILADI (yuqoridagi xizmat yangi kadr
#: qo'shsa, Venera'ni qayta yozmasdan ishlashi kerak) - lekin faqat shakli
#: to'g'ri bo'lsa: `type` maydoni bor JSON obyekti.
FRAME_TYPES = frozenset({"stage", "sources", "artifact", "token", "done", "error"})

#: Ariza fayli turlari. Yuqoridagi xizmatda `/api/hr/artifacts/{token}/<kind>`.
ARTIFACT_KINDS = ("preview", "docx", "pdf")

#: `{token}` - yuqoridagi xizmat bergan bir martalik kalit. Uni URL'dan shu
#: naqsh bilan ajratamiz: absolyut ham, nisbiy havola ham mos keladi.
#:
#: `\w` pastki chiziqni ham qamraydi, va bu MUHIM: jonli xizmat hujjat
#: kalitlarini `HR_045` ko'rinishida beradi. Undan avvalgi tor ro'yxatda
#: pastki chiziq yo'q edi, ya'ni haqiqiy hujjatlarning HECH BIRIGA havola
#: qo'yilmasdi - va buni faqat jonli javobni ko'rib bilish mumkin edi.
_ARTIFACT_URL = re.compile(r"/api/hr/artifacts/(?P<token>[\w.~-]{1,256})/(?P<kind>\w+)")

#: Yo'lga qo'yiladigan kalit uchun ruxsat etilgan belgilar. Yo'l ajratgichi
#: va nuqtali ketma-ketlik yo'q, ya'ni papkadan chiqib bo'lmaydi.
_SAFE_KEY = re.compile(r"[\w.~:-]{1,128}")

#: Bitta kadr uchun eng ko'p uzunlik. `sources` kadri eng kattasi, lekin
#: undan ham kattasi kelishi xizmat nosozligini bildiradi va butun
#: xotirani yeb qo'yishiga yo'l qo'yilmaydi.
_MAX_LINE_BYTES = 512 * 1024

#: Butun oqim uchun chegara. Cheksiz oqim (nosozlik yoki tsikl) brauzerni
#: ham, serverni ham qulflab qo'yardi.
_MAX_STREAM_BYTES = 4 * 1024 * 1024

#: Fayl yuklab olishda bir marta o'qiladigan hajm.
_DOWNLOAD_CHUNK = 64 * 1024

#: Yuklab olinadigan fayl uchun chegara (ariza DOCX/PDF va hujjat PDF'i).
_MAX_FILE_BYTES = 25 * 1024 * 1024


class AssistantError(Exception):
    """Yuqoridagi xizmat bilan bog'liq xato.

    `status` - FOYDALANUVCHIGA ko'rsatiladigan HTTP status (HTTP qatlami
    uni xabarga o'giradi), yuqoridagi xizmatning statusi emas: 401 bizning
    sozlama xatomiz, foydalanuvchi sessiyasi esa joyida.
    """

    def __init__(self, message: str, *, status: int = 502, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class AnswerStream:
    """Ochilgan oqim.

    `frames` - generator: har element bitta NDJSON qatori (baytlar, `\\n`
    bilan). Uni AYNAN shu ko'rinishda brauzerga uzatish mumkin.

    `request_id` - audit kaliti. Yuqoridagi xizmat uni javob sarlavhasida
    qaytaradi va o'z jurnaliga yozadi; biz ham log'ga yozamiz, shu tufayli
    "shu javob nega bunday bo'ldi" degan savolni ikki tizimda bir kalit
    bilan izlash mumkin.
    """

    request_id: str
    frames: Iterator[bytes]
    #: Oqim o'qilgach to'ladi - shu sababli `field(default_factory=dict)`.
    #: `pump()` yakunda `route` va kadr sonini shu yerga yozadi.
    outcome: dict[str, Any] = field(default_factory=dict)


class AssistantClient:
    """`/api/chat/stream` ustidagi yupqa qatlam.

    Bloklaydigan `urllib` ishlatadi (loyihada yangi bog'liqlik yo'q), shu
    sababli chaqiruvchi ODDIY `def` bo'lishi kerak - FastAPI uni
    threadpool'da ishlatadi va event loop bo'sh qoladi. `async def` da
    bitta uzun oqim butun serverni to'xtatib qo'yardi.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        timeout: float = 120.0,
        max_concurrent: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        #: Kadrlar ORASIDAGI eng uzun tanaffus, butun javob vaqti emas:
        #: LLM javobi bir daqiqadan oshishi normal, lekin bir daqiqa
        #: JIMLIK - nosozlik.
        self.timeout = timeout
        self.max_concurrent = max(1, max_concurrent)
        #: Yuqoridagi xizmatda bitta LLM turadi. Bu semafora - bizning
        #: ulushimiz: oshsa xizmatga BORMASDAN 503 qaytaramiz, ya'ni
        #: navbatni boshqa chaqiruvchilar uchun to'ldirib qo'ymaymiz.
        self._slots = threading.BoundedSemaphore(self.max_concurrent)

    @property
    def configured(self) -> bool:
        """Kredensiallar berilganmi. Berilmasa savol umuman yuborilmaydi -
        yuqoridagi xizmat 401 qaytarardi, va bu foydalanuvchiga
        "sessiyangiz tugadi" bo'lib ko'rinardi."""
        return bool(self.base_url and self.client_id and self.client_secret)

    # --- savol -> oqim -------------------------------------------------------

    def stream(
        self,
        question: str,
        *,
        user_id: str,
        chat_id: str | None = None,
        hrm_token: str | None = None,
        hrm_employee: str | None = None,
        max_chars: int = 2000,
    ) -> AnswerStream:
        """Savolni yuboradi va kadr generatorini qaytaradi.

        Ulanish SHU YERDA ochiladi, generator ichida emas: 401/422/503
        kabi xatolar shunda ODDIY HTTP javobi bo'lib chiqadi. Generator
        ichida ochilsa, biz allaqachon 200 yuborib bo'lgan bo'lardik va
        xato brauzerga "uzilgan oqim" bo'lib ko'rinardi.
        """
        if not self.configured:
            raise AssistantError("HR Assistant sozlanmagan", status=501)
        question = (question or "").strip()
        if not question:
            raise AssistantError("savol bo'sh", status=400)
        if len(question) > max_chars:
            raise AssistantError(f"savol juda uzun ({len(question)} > {max_chars})", status=400)

        request_id = uuid.uuid4().hex
        payload: dict[str, Any] = {"question": question, "user_id": user_id}
        # `None` maydonlar YUBORILMAYDI: yuqoridagi xizmat `chat_id` yo'q
        # bo'lsa turni xotirasiz bajaradi, bo'sh satr esa "shu nomli
        # suhbat" bo'lib qolardi.
        if chat_id:
            payload["chat_id"] = chat_id
        if hrm_token:
            # `tokens` XARITASI, `hrm_token` qisqa shakli EMAS - O'LCHANGAN.
            #
            # Hujjatda "hrm_token is the shorthand for tokens['hrm']" deb
            # yozilgan, lekin jonli xizmatda (2026-09-11) qisqa shakl
            # ISHLAMAYDI: aynan bir xil token bilan `hrm_token` yuborilsa
            # `auth_missing` qaytadi, `tokens: {"hrm": ...}` yuborilsa esa
            # to'liq javob keladi. Token o'zi joyida edi - HRM ning
            # `/api/account` i o'sha token bilan 200 qaytardi.
            #
            # Ikkalasini birga yuborish YO'Q: buzuq yo'l ustun kelib
            # qolsa, muammo yana qaytardi.
            payload["tokens"] = {"hrm": hrm_token}
        if hrm_employee:
            payload["hrm_employee"] = hrm_employee

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # Slot oqim TUGAGANDA bo'shatiladi (`finally` ichida), javob
        # kelganda emas: oqim davomida yuqoridagi LLM hali band.
        if not self._slots.acquire(blocking=False):
            raise AssistantError("navbat to'la", status=503, retryable=True)
        released = False
        try:
            with _mapped_errors(self.client_secret):
                response = self._open("/api/chat/stream", body, accept="application/x-ndjson",
                                      request_id=request_id)
            # Xizmat o'z `X-Request-Id` ini qaytarsa - AUDIT kaliti o'shanikisi.
            served = (response.headers.get("X-Request-Id") or "").strip()
            outcome: dict[str, Any] = {}

            def pump() -> Iterator[bytes]:
                total = 0
                frames = 0
                try:
                    while True:
                        try:
                            line = response.readline(_MAX_LINE_BYTES + 1)
                        except (TimeoutError, socket_timeout) as exc:
                            raise AssistantError("javob to'xtab qoldi (timeout)",
                                                 status=504) from exc
                        except (http.client.HTTPException, OSError) as exc:
                            # Ulanish javob O'RTASIDA uzildi. Buni AYNAN shu
                            # yerda tutish kerak: bu xato tipi chaqiruvchiga
                            # yetib borsa, u faqat `AssistantError` ni
                            # kutayotgani uchun oqim brauzerga kutilmagan
                            # uzilish bo'lib ko'rinardi.
                            raise AssistantError(f"javob oqimi uzildi: {exc}",
                                                 status=503, retryable=True) from exc
                        if not line:
                            break
                        if len(line) > _MAX_LINE_BYTES:
                            # Bitta kadr chegaradan katta: qolgan qismi
                            # keyingi o'qishda kelib, buzuq JSON bo'lib
                            # tashlanardi - ya'ni oqimning qolgani ham
                            # ishonchsiz. To'xtaymiz.
                            log.warning("Assistant kadri chegaradan katta: %d bayt", len(line))
                            break
                        total += len(line)
                        if total > _MAX_STREAM_BYTES:
                            log.warning("Assistant oqimi chegaradan oshdi (%s): %d bayt",
                                        served or request_id, total)
                            break
                        out = _clean_frame(line, self.base_url)
                        if out is None:
                            continue
                        frames += 1
                        if out.get("type") == "done":
                            outcome["route"] = out.get("route")
                        elif out.get("type") == "error":
                            outcome["error"] = out.get("code")
                        yield json.dumps(out, ensure_ascii=False).encode("utf-8") + b"\n"
                finally:
                    outcome["frames"] = frames
                    nonlocal released
                    if not released:
                        released = True
                        self._slots.release()
                    with contextlib.suppress(Exception):
                        response.close()

            stream = AnswerStream(request_id=served or request_id, frames=pump(), outcome=outcome)
            return stream
        except BaseException:
            # Oqim ochilmadi - slotni DARHOL qaytaramiz, aks holda birinchi
            # nosozlik navbatni abadiy egallab qolardi.
            if not released:
                released = True
                self._slots.release()
            raise

    def ask(self, question: str, **kwargs) -> dict[str, Any]:
        """Oqimni to'liq yig'ib, bitta javob qaytaradi.

        Test va `tools/` uchun. Ishlab chiqishda ham qulay: `/api/chat`
        ga alohida borish shart emas, ya'ni ikki yo'l o'rniga bitta yo'l
        sinaladi.
        """
        stream = self.stream(question, **kwargs)
        answer: list[str] = []
        sources: list[Any] = []
        artifact: Any = None
        stages: list[str] = []
        error: dict[str, Any] | None = None
        for raw in stream.frames:
            frame = json.loads(raw)
            kind = frame.get("type")
            if kind == "token":
                answer.append(str(frame.get("text") or ""))
            elif kind == "sources":
                sources = frame.get("sources") or frame.get("items") or []
            elif kind == "artifact":
                artifact = frame.get("artifact") or {k: v for k, v in frame.items() if k != "type"}
            elif kind == "stage":
                stages.append(str(frame.get("text") or frame.get("stage") or ""))
            elif kind == "error":
                error = {"code": frame.get("code"), "text": frame.get("text")}
        return {
            "requestId": stream.request_id,
            "route": stream.outcome.get("route"),
            "answer": "".join(answer),
            "sources": sources,
            "artifact": artifact,
            "stages": stages,
            "error": error,
        }

    # --- fayllar -------------------------------------------------------------

    def fetch_artifact(self, token: str, kind: str) -> tuple[str, str, Iterator[bytes]]:
        """Ariza fayli: (content_type, fayl nomi, baytlar generatori).

        Kalit yuqoridagi xizmatdan kelgan bir martalik `token`; biz uni
        tekshirmaymiz va tekshira olmaymiz - haqiqiy tekshiruv o'sha
        yerda. Bizning ishimiz: brauzer yetib bormaydigan ichki manzilni
        o'z yo'limiz orqali ochib berish.
        """
        if kind not in ARTIFACT_KINDS:
            raise AssistantError(f"noma'lum fayl turi: {kind}", status=400)
        if not _ARTIFACT_URL.fullmatch(f"/api/hr/artifacts/{token}/{kind}"):
            raise AssistantError("fayl kaliti yaroqsiz", status=400)
        return self._download(f"/api/hr/artifacts/{urllib.parse.quote(token, safe='')}/{kind}")

    def fetch_doc(self, doc_id: str) -> tuple[str, str, Iterator[bytes]]:
        """Iqtibos qilingan hujjat PDF'i."""
        if not doc_id or not _SAFE_KEY.fullmatch(doc_id):
            raise AssistantError("hujjat kaliti yaroqsiz", status=400)
        return self._download(f"/doc/{urllib.parse.quote(doc_id, safe='')}")

    def _download(self, path: str) -> tuple[str, str, Iterator[bytes]]:
        if not self.configured:
            raise AssistantError("HR Assistant sozlanmagan", status=501)
        with _mapped_errors(self.client_secret):
            response = self._open(path, None, accept="*/*", request_id=uuid.uuid4().hex)
        content_type = (response.headers.get("Content-Type") or "application/octet-stream").strip()
        filename = _filename(response.headers.get("Content-Disposition") or "", path)

        def pump() -> Iterator[bytes]:
            total = 0
            try:
                while True:
                    chunk = response.read(_DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_FILE_BYTES:
                        log.warning("Assistant fayli chegaradan oshdi: %s", path)
                        break
                    yield chunk
            finally:
                with contextlib.suppress(Exception):
                    response.close()

        return content_type, filename, pump()

    # --- past qatlam ---------------------------------------------------------

    def _open(self, path: str, body: bytes | None, *, accept: str, request_id: str):
        headers = {
            # Ilovaning kredensiallari. HUJJAT BO'YICHA: usiz 401.
            "X-Client-Id": self.client_id,
            "X-Client-Secret": self.client_secret,
            # Audit kaliti - javob sarlavhasida qaytadi.
            "X-Request-Id": request_id,
            "Accept": accept,
            # Siqishni ATAYLAB so'ramaymiz: gzip oqimni bufer bilan
            # bo'g'ib, kadrlarni to'plab beradi va oqimning ma'nosi
            # qolmaydi (hujjat ham "no compression" deydi).
            "Accept-Encoding": "identity",
        }
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers,
            method="POST" if body is not None else "GET",
        )
        # Muhit proksisi CHETLAB o'tiladi: manzil ichki, va tashqi proksi
        # orqali yuborish so'rovni sirtga chiqarib qo'yardi.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=self.timeout)


# --- kadrlar --------------------------------------------------------------


def _clean_frame(line: bytes, base_url: str) -> dict[str, Any] | None:
    """Bitta NDJSON qatorini tekshiradi va havolalarini qayta yozadi.

    `None` - qatorni o'tkazib yuborish kerak (bo'sh, buzuq yoki obyekt
    emas). Buzuq qatorni O'ZGARTIRMASDAN uzatish oson yo'l bo'lardi, lekin
    brauzerdagi tahlilchi keyin har kadrda xatoga tayyor turishi kerak
    edi; bir joyda to'sish arzonroq.
    """
    line = line.strip()
    if not line:
        return None
    try:
        frame = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        log.warning("Assistant kadri JSON emas (%d bayt)", len(line))
        return None
    if not isinstance(frame, dict):
        log.warning("Assistant kadri obyekt emas: %s", type(frame).__name__)
        return None
    kind = frame.get("type")
    if not isinstance(kind, str):
        return None
    if kind == "artifact":
        _rewrite_artifact(frame, base_url)
    elif kind == "sources":
        _rewrite_sources(frame)
    return frame


def _rewrite_artifact(frame: dict[str, Any], base_url: str) -> None:
    """Ichki fayl havolalarini Venera yo'llariga o'giradi.

    Kadr shakli hujjatda `{title, doc_id, docx_url, pdf_url, preview_url,
    ...}`, lekin u `artifact` kaliti ostida ham kelishi mumkin - ikkalasi
    ham qo'llanadi, aks holda xizmat kadrni bir daraja pastga tushirsa
    havolalar jimgina ishlamay qo'yardi.
    """
    for holder in (frame, frame.get("artifact")):
        if not isinstance(holder, dict):
            continue
        for key in ("preview_url", "docx_url", "pdf_url", "url"):
            value = holder.get(key)
            if not isinstance(value, str):
                continue
            match = _ARTIFACT_URL.search(value)
            if match and match.group("kind") in ARTIFACT_KINDS:
                holder[key] = (f"/api/v1/chat/artifact/{match.group('token')}"
                               f"/{match.group('kind')}")
            elif base_url and value.startswith(base_url):
                # Tanimadik, lekin ICHKI manzil - havolani olib tashlaymiz.
                # Ochilmaydigan havola ko'rsatishdan ko'ra ko'rsatmaslik
                # yaxshi, va ichki topologiya tashqariga chiqmaydi.
                log.warning("Assistant artifact havolasi tanilmadi: %s", key)
                holder[key] = None


def _rewrite_sources(frame: dict[str, Any]) -> None:
    """Iqtibos qilingan hujjatga Venera orqali havola qo'shadi.

    Xizmatning o'z `doc_id` si saqlanadi (frontend uni ko'rsatadi), yoniga
    `docUrl` qo'shiladi - brauzer AYNAN shu yo'l bilan PDF'ni ocha oladi.
    """
    for key in ("sources", "items"):
        items = frame.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            doc_id = item.get("doc_id")
            if item.get("kind") == "doc" and isinstance(doc_id, str) and doc_id:
                if _SAFE_KEY.fullmatch(doc_id):
                    item["docUrl"] = f"/api/v1/chat/doc/{urllib.parse.quote(doc_id, safe='')}"
                page = item.get("page")
                if isinstance(page, int) and page > 0 and item.get("docUrl"):
                    item["docUrl"] = f"{item['docUrl']}#page={page}"


def _filename(disposition: str, path: str) -> str:
    """`Content-Disposition` dan fayl nomi, bo'lmasa yo'lning oxirgi bo'lagi.

    Nom TOZALANADI: yuqoridagi xizmat bergan matn to'g'ridan-to'g'ri
    sarlavhaga qo'yilsa, unda `"` yoki yangi qator bo'lsa javob
    sarlavhasini buzib yuborardi.
    """
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)"?', disposition)
    raw = match.group(1) if match else path.rstrip("/").rsplit("/", 1)[-1]
    with contextlib.suppress(Exception):
        raw = urllib.parse.unquote(raw)
    clean = re.sub(r"[^\w.\- ]+", "_", raw).strip(" .") or "hujjat"
    return clean[:120]


# --- HRM token holati ------------------------------------------------------


def token_seconds_left(token: str) -> int | None:
    """JWT tugashigacha qolgan soniya. `None` - o'qib bo'lmadi.

    Imzo TEKSHIRILMAYDI va tekshirilmasligi kerak: bizda HRM ning ochiq
    kaliti yo'q, va bu yerda qaror ham qabul qilinmaydi. Haqiqiy tekshiruv
    HRM ning o'zida; bu faqat "nega ishlamayapti" degan savolga bir
    qatorda javob berish uchun - token muddati tugaganini bilmasdan
    odam nosozlikni boshqa joyda izlaydi.

    Token MAZMUNI hech qayerga yozilmaydi - faqat `exp` o'qiladi.
    """
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:  # noqa: BLE001 - buzuq token diagnostikani buzmasin
        return None
    exp = data.get("exp") if isinstance(data, dict) else None
    if not isinstance(exp, (int, float)):
        return None
    return int(exp - time.time())


def token_warning(token: str) -> str | None:
    """`/api/health` uchun bir qatorli holat. `None` - aytishga hojat yo'q.

    `exp` HAQIQIY umr emas, faqat TOKEN AYTGAN muddat: HRM sessiyani
    o'zidan oldin ham bekor qilishi mumkin (jonli o'lchov: `exp` 10 soat
    ko'rsatgan token amalda bir necha daqiqada yaroqsiz bo'ldi). Shuning
    uchun xabarda "exp bo'yicha" deb aytiladi - aks holda odam "hali 9
    soat bor" deb, muammoni butunlay boshqa joyda izlardi.
    """
    if not token:
        return None
    shared = ("umumiy token: jonli HRM javoblari har kim uchun TOKEN EGASI "
              "haqida bo'ladi")
    left = token_seconds_left(token)
    if left is None:
        return f"hrm_token o'qib bo'lmadi (JWT emas?) - jonli HRM ishlamaydi; {shared}"
    if left <= 0:
        return (f"hrm_token MUDDATI TUGAGAN ({-left} s oldin) - jonli HRM savollari "
                "ishlamaydi, .env dagi qiymatni yangilang")
    return (f"hrm_token o'rnatilgan (exp bo'yicha {left // 60} daq qoldi, lekin HRM "
            f"sessiyani oldin ham bekor qilishi mumkin) - vaqtincha, {shared}")


@contextlib.contextmanager
def _mapped_errors(secret: str):
    """`urllib` xatolarini `AssistantError` ga o'giradi.

    401/403 ATAYLAB 502 ga tushadi: ular "bizning `X-Client-Secret`
    noto'g'ri" degani, ya'ni SOZLAMA xatosi. Brauzerga 401 qaytarish
    "sessiyangiz tugadi" degan ma'no berardi va foydalanuvchi o'zining
    mutlaqo joyida bo'lgan sessiyasidan chiqib ketardi.
    """
    try:
        yield
    except urllib.error.HTTPError as exc:
        status = exc.code
        detail = _redact(_detail(exc), secret)
        mapped = status if status in (400, 404, 422, 503) else 502
        raise AssistantError(f"Assistant {status}: {detail}", status=mapped) from exc
    except urllib.error.URLError as exc:
        raise AssistantError(f"Assistant serveriga ulanib bo'lmadi: {exc.reason}",
                             status=503, retryable=True) from exc
    except (TimeoutError, socket_timeout) as exc:
        raise AssistantError("Assistant javob bermadi (timeout)", status=504) from exc
    except (http.client.HTTPException, OSError) as exc:
        raise AssistantError(f"Assistant ulanishi uzildi: {exc}",
                             status=503, retryable=True) from exc


def _redact(text: str, secret: str) -> str:
    """Sirni xato matnidan olib tashlaydi. Qisqa sir tasodifiy mos kelib
    matnni buzishi mumkin, shuning uchun faqat uzunlari almashtiriladi."""
    return text.replace(secret, "***") if secret and len(secret) > 2 else text


def _detail(exc: urllib.error.HTTPError) -> str:
    """`{"detail": "..."}` dan matn."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return str(exc.reason or "")
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw[:300]
    if isinstance(parsed, dict):
        for key in ("detail", "message", "error", "text"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    return raw[:300]

"""HR Assistant klienti - savol -> javob OQIMI (NDJSON).

Yuqoridagi xizmat: BRB-TECH HR Assistant API 3.1 (`/api/chat/stream`). U
o'z ichida hujjatlar bo'yicha RAG va HRM connector'ini birlashtiradi, ya'ni
Venera uchun bu BITTA endpoint - savolni yuboramiz, javobni bo'lak-bo'lak
olamiz.

IKKI DVIGATEL (2026-10-02 dan, `core/engines.py`): `/api/v1/chat/stream`
(barqaror) va `/api/v2/chat/stream` (yangi: Mehnat kodeksi moddalari LEX.UZ
havolasi bilan, "Pro" rejimi). Versiyasiz `/api/chat/stream` - xizmat
default'i (bugun = v1). So'rov va javob shakli bir xil; qaysi yo'lga borishni
chaqiruvchi aytadi (`stream(engine=...)`), klient o'zi tanlamaydi. Tarix,
amallar, fayllar va `/api/pro/quota` VERSIYASIZ.

v4 (2026-10-13, `/api/v4/chat/stream`) - agentning SHARTNOMA 4.0 yo'li. Agentda v3
va v4 - bitta Core, lekin v1-v3 muzlatilgan: har yangilik faqat v4 ga tushadi.
Farqi uchta, qolgani v3 bilan bir xil (kimlik, tokenlar, `chat_id`, "Pro", xatolar):

  1. SO'ROV: `X-Barno-Contract: 4.0` sarlavhasi va u bilan MAJBURIY `purpose`.
     Oddiy suhbat - `purpose: "chat"`, `store: true`, `chat_visibility:
     "personal"` (suhbat odamning ro'yxatida ko'rinadi va xotirasi bor - v3 dagi
     kabi). Tarix `(user_id, chat_id)` bo'yicha, dvigatelsiz: v3 da boshlangan
     suhbat v4 da davom etadi. Gapirilgan savolda `style: "voice"` (`_V4_VOICE`).
     Telegram GURUHIDAGI CRM so'rovi (`audience="group"`) - `_V4_GROUP`: agent
     shaxsiy xotirani ishlatmaydi, guruhdan o'rganmaydi va faqat CRM vositalari
     (v4 ning yangi `work_activity` i ham yo'q - javobni guruhdagi hamma ko'radi);
  2. KADRLAR: `ping` (15 s jimlikda) va `result` (`response_format` so'ralganda,
     biz so'ramaymiz) - XIZMAT kadrlari, klientga O'TMAYDI. `done` dagi `meta`
     (model nomi, navbat) va `cited_ids` (biz kontekst yubormaymiz) olib
     tashlanadi - klient v3 ning `done` ini oladi (`_from_v4`);
  3. JIMLIK: `ping` jimlik hisobini YANGILAMAYDI - aks holda osilib qolgan agent
     ishchisi har 15 s da "tirik" deb, `timeout` o'rniga oqim muddatigacha (600 s)
     slotni ushlardi. v3 dagi kabi `timeout` soniya javobsiz - 504.

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
    proposal  -> TAKLIF qilingan yozuv amali (bo'lishi shart emas): hech
                 narsa o'zgarmagan, odam tasdiqlasa `confirm_action` bajaradi
    token     -> javob matni bo'laklari, ko'p
    done      -> yakun: `route`, `request_id`. MAJBURIY: usiz EOF - uzilish.
                 Versiyalangan yo'lda `engine`, "Pro" so'ralganda `pro` bloki
    error     -> tokenlar O'RNIGA keladi, keyin `done`

QONUNCHILIK MANBASI (v2): `sources` ichida `kind: "law"` - `url` LEX.UZ dagi
moddaga olib boradi, `doc_id` yo'q. Havola brauzerga TO'G'RIDAN-TO'G'RI
boradi, shuning uchun tekshiriladi (`safe_source_url`): faqat `https://`,
`javascript:`/`data:`/`http:` va login-parolli manzil o'tmaydi.

FAYL HAVOLALARI QAYTA YOZILADI. `artifact` kadridagi `docx_url` yuqoridagi
serverning ICHKI manzilini ko'rsatadi - brauzer uni ocholmaydi. Shuning
uchun ular Venera'ning o'z yo'llariga o'giriladi (`_rewrite_artifact`), va
faylni Venera o'zi olib beradi (`fetch_artifact`). Xuddi shu narsa
iqtibos qilingan hujjat PDF'i uchun ham (`fetch_doc`).

SUHBATLAR TARIXI ham shu xizmatda (`/api/chats`, 3.3 dan boshlab): har
`chat_id` bo'yicha xabarlar, nom va yumshoq o'chirish. Venera'da suhbat
saqlanmaydi - `list_chats` va `get_chat` o'sha yerdan o'qiydi.
"""

from __future__ import annotations

import base64
import contextlib
import gc
import http.client
import itertools
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import weakref

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from socket import timeout as socket_timeout
from typing import Any, Iterator

from ...core.engines import PRO_ENGINES, ROUTES
from ..analytics.meter import Call, begin

log = logging.getLogger(__name__)

#: Kadr turlari. Notanish turlar O'TKAZILADI (yuqoridagi xizmat yangi kadr
#: qo'shsa, Venera'ni qayta yozmasdan ishlashi kerak) - lekin faqat shakli
#: to'g'ri bo'lsa: `type` maydoni bor JSON obyekti.
FRAME_TYPES = frozenset({"stage", "sources", "artifact", "proposal", "token", "done", "error"})

#: Shartnoma 4.0 bilan ochiladigan dvigatellar (modul izohi, v4). v5 (2026-11-25) - AYNAN
#: shu shartnoma: so'rov tanasi, sarlavha, kadrlar, tasdiq va bekor qilish yo'llari, tarix
#: v4 niki; `done` da `engine: "v5"`. Farqi agent tomonida (ovozda gap javob to'liq tayyor
#: bo'lganda keladi, ariza fayli hali yo'q) - bu klientda kod talab qilmaydi.
CONTRACT_ENGINES = frozenset({"v4", "v5"})

#: `X-Barno-Contract` qiymati. Asosiy raqami 4 bo'lishi SHART: agent boshqasini
#: `unsupported_field` bilan rad etadi.
V4_CONTRACT = "4.0"

#: v4 so'roviga qo'shiladigan maydonlar - ODDIY suhbat. `purpose` sarlavha bilan
#: majburiy; `store` va `chat_visibility` agentning `chat` uchun default'i, lekin ochiq
#: yoziladi: default o'zgarsa suhbatlar jimgina saqlanmay yoki ro'yxatdan yo'qolmasin.
_V4_CHAT = {"purpose": "chat", "store": True, "chat_visibility": "personal"}

#: Telegram guruhidagi CRM so'rovi (`bot/runner.py: stream_group`) - `_V4_CHAT` ustiga.
#: v3 da buni aytib bo'lmaydi: u yerda faqat HRM tokeni olib tashlanadi (`platforms`).
#: v4 da esa agentning o'zi kodda to'sadi (agentning `engine/privacy.py`):
#:   * `audience: group` - HRM vositalari yo'q, shaxsiy xotira yo'q, guruhdan o'rganmaydi;
#:   * `tools` - FAQAT CRM o'qish va taklif. Ro'yxatsiz v4 so'roviga agent o'zining yangi
#:     `work_activity` vositasini ham beradi (GitLab va CRM dagi kim nima qilgani; ruxsatli
#:     odamga - HAMMANIKI) - guruhda u javob bo'lib hammaga chiqardi;
#:   * `purpose: group_crm` - agentning hisobida shaxsiy suhbat emas, guruh ishi.
#: `store` (`_V4_CHAT` dan, `true`) qoladi: guruhdagi davomi ("shuni ham qo'sh") tarixga
#: tayanadi, suhbatni `group_actions.sweep` o'zi o'chiradi. Shakl W1 dagi guruh so'rovi
#: bilan bir xil (`services/brain/group_crm.py: request`), faqat kontekst blokisiz.
_V4_GROUP = {"purpose": "group_crm", "audience": "group", "tools": ["crm.read", "crm.propose"],
             "memory_scopes": []}

#: Ovozli suhbat uslubi (agentning `docs/VOICE_MODE.md`): javob quloq uchun yoziladi,
#: har `token` - bitta tugal gap. FAQAT v4 da: v1-v3 da odamlar bugungi xulqda qolsin.
_V4_VOICE = "voice"

#: v4 ning XIZMAT kadrlari - klientga O'TMAYDI: `ping` - agent bilan bizning orada
#: tiriklik belgisi, `result` - biz so'ramaydigan `response_format` javobi.
_V4_SERVICE_FRAMES = frozenset({"ping", "result"})

#: v4 `done` idagi qo'shimchalar - klientga O'TMAYDI: `meta` ichki (model nomi, navbat,
#: tokenlar), `cited_ids` - kontekst bandlari (biz kontekst yubormaymiz, doim bo'sh).
_V4_DONE_EXTRA = ("meta", "cited_ids")

#: Yuqoridagi xizmatning yozuv amallari (`/api/actions/{token}/...`).
ACTION_VERBS = ("confirm", "cancel")

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
#: yo'q, va FAQAT nuqtadan iborat kalit (`.`, `..`) ham rad etiladi: `quote()`
#: nuqtani kodlamaydi, oraliq proksi (nginx `proxy_pass` URI bilan, shlyuz)
#: esa `/api/chats/..` ni `/api/` ga "normallashtirib", boshqa yo'lga olib
#: borardi. `\w` - Unicode (eski hujjat kalitlari uchun shunday qoldirilgan).
_SAFE_KEY = re.compile(r"(?!\.+\Z)[\w.~:-]{1,128}")
#: Xotira bandi kaliti (`m12`, `h3f2a...`): faqat ASCII, harf/raqam bilan
#: boshlanadi. `_SAFE_KEY` dan TORROQ, chunki `DELETE /api/memory/{id}` ning
#: qo'shnisi `DELETE /api/memory` - HAMMASINI unutish: `.` kabi kalit biror
#: hopda `/api/memory/` ga aylanib, tasdiqsiz tozalashga yetib bormasin.
_MEMORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", re.ASCII)
#: Platforma kaliti (`hrm`, `biznes247_kb`, ...): xizmat ro'yxatidagi kichik
#: harfli nomlar. Yo'lga to'g'ridan-to'g'ri tushadi, shuning uchun torroq.
_PLATFORM_ID = re.compile(r"[a-z0-9_]{1,40}")

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

#: Bitta JSON javob uchun chegara (suhbat ro'yxati, ochilgan suhbat).
#: Ochilgan suhbat 1000 tagacha xabar bo'lishi mumkin - kadr chegarasi
#: (512 KB) unga torlik qiladi; oqim chegarasi bilan bir xil.
_MAX_JSON_BYTES = _MAX_STREAM_BYTES

#: Qonunchilik manbasi havolasi shu domenlarda (xat: "LEX.UZ dagi moddaga
#: olib boradi"). Boshqa `https` manzil ham O'TADI (xizmat keyin boshqa
#: rasmiy manba qo'shishi mumkin), lekin jurnalga yoziladi - kutilmagan
#: domen ko'rinsa, bilib turish kerak.
LAW_HOSTS = ("lex.uz",)

#: Manba havolasining eng katta uzunligi - undan uzuni nosozlik yoki hiyla.
_MAX_URL_CHARS = 2048

#: Navbat to'lganda yetib bo'lmaydigan oqimlarni yig'ish (`gc.collect`) shu
#: soniyada ko'pi bilan bir marta: to'liq yig'ish barcha iplarni bir lahza
#: to'xtatadi, to'lib turgan navbatda har savolda qayta-qayta qilinmasin.
_GC_EVERY = 10.0

#: Band joy "jim" (o'qilmayotgan) yoki "qari" deb topilishidan oldingi
#: qo'shimcha zahira (soniya) - chegaraning o'zida tirik oqim kesilmasin.
_LEASE_GRACE = 30.0


class AssistantError(Exception):
    """Yuqoridagi xizmat bilan bog'liq xato.

    `status` - FOYDALANUVCHIGA ko'rsatiladigan HTTP status (HTTP qatlami
    uni xabarga o'giradi), yuqoridagi xizmatning statusi emas: 401 bizning
    sozlama xatomiz, foydalanuvchi sessiyasi esa joyida.

    `reason` - ICHKI sabab, mashina o'qiydigan: foydalanuvchi uchun uchalasi
    ham bir xil "xizmat band" (503), admin esa farqini ko'rishi kerak -
    29-sentabrda aynan shu farq ko'rinmagani uchun bir soat davomida
    "yordamchi band" deb o'ylandi, holbuki so'rov unga umuman bormagan edi:

        queue_full            BIZNING navbat to'la - yuqoriga BORILMADI
        upstream_unreachable  ulanib bo'lmadi (tarmoq, port yopiq, DNS)
        upstream_busy         xizmatning O'ZI 503 qaytardi
        upstream_timeout      javob kelmadi (vaqt tugadi)
        upstream_http         xizmatning boshqa HTTP xatosi (401, 422, 500 ...)
    """

    def __init__(self, message: str, *, status: int = 502, retryable: bool = False,
                 reason: str | None = None, upstream_status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.reason = reason
        #: Yuqoridagi xizmatning O'Z HTTP statusi (`_mapped_errors`), `status` dan farqli
        #: foydalanuvchiga ko'rsatilmaydi. Masalan 409 - taklif allaqachon yakunlangan
        #: (`actions._settled`): foydalanuvchi uchun u 502 bo'lib qolardi.
        self.upstream_status = upstream_status


@dataclass
class AnswerStream:
    """Ochilgan oqim.

    `frames` - generator: har element bitta NDJSON qatori (baytlar, `\\n`
    bilan). Uni AYNAN shu ko'rinishda brauzerga uzatish mumkin.

    `request_id` - audit kaliti. Yuqoridagi xizmat uni javob sarlavhasida
    qaytaradi va o'z jurnaliga yozadi; biz ham log'ga yozamiz, shu tufayli
    "shu javob nega bunday bo'ldi" degan savolni ikki tizimda bir kalit
    bilan izlash mumkin.

    YAKUN `close()` bilan - IDEMPOTENT va istalgan holatda: oxirigacha
    o'qilgan, o'rtada tashlangan yoki UMUMAN BOSHLANMAGAN oqim. Oxirgisi
    muhim: boshlanmagan generatorning `close()` i uning `finally` sini
    ishlatmaydi, ya'ni slot faqat shu yerdan qaytadi.
    """

    request_id: str
    frames: Iterator[bytes]
    #: Oqim o'qilgach to'ladi - shu sababli `field(default_factory=dict)`.
    #: `pump()` yakunda `route` va kadr sonini shu yerga yozadi.
    outcome: dict[str, Any] = field(default_factory=dict)
    #: So'ralgan dvigatel (`v1` ... `v5` | `""`). Yordamchiga bormagan javob
    #: (xodimlar ma'lumotnomasi) - `None`. Javobning `done.engine` i bo'lsa
    #: haqiqatda qaysi dvigatel javob bergani - o'sha (`outcome["engine"]`).
    engine: str | None = None
    #: Slot va ulanishni qaytaradigan yakun (`_StreamEnd`) - faqat klient
    #: ochgan oqimda; testlardagi soxta oqimlarda yo'q.
    _end: Callable[[BaseException | None], None] | None = field(
        default=None, repr=False, compare=False)

    def close(self) -> None:
        """Oqimni yopadi va slotni qaytaradi. Necha marta chaqirilsa ham bir xil."""
        close = getattr(self.frames, "close", None)
        if callable(close):
            try:
                close()
            except ValueError:
                # "generator already executing": oqimni HOZIR boshqa ip
                # o'qiyapti (kutish ovozi ipi, `chat._with_hold`). Uni
                # bu yerdan to'xtatib bo'lmaydi - u tugaganda o'zi yakunlaydi.
                return
        if self._end is not None:
            self._end(_ABANDONED)


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
        max_stream_seconds: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        #: Kadrlar ORASIDAGI eng uzun tanaffus, butun javob vaqti emas:
        #: LLM javobi bir daqiqadan oshishi normal, lekin bir daqiqa
        #: JIMLIK - nosozlik.
        self.timeout = timeout
        self.max_concurrent = max(1, max_concurrent)
        #: Bitta javobning eng uzun umri - undan oshsa oqim uziladi (504).
        #: Navbatning o'zini davolashi shu chegaraga tayanadi (`_SlotPool`).
        self.max_stream_seconds = max(1.0, float(max_stream_seconds))
        #: Monoton soat - oqim muddati va navbat shu bilan o'lchanadi (testda soxta).
        self._clock = clock
        #: Yuqoridagi xizmatda bitta LLM turadi. Bu - bizning ulushimiz:
        #: oshsa xizmatga BORMASDAN 503 qaytaramiz, ya'ni navbatni boshqa
        #: chaqiruvchilar uchun to'ldirib qo'ymaymiz.
        #:
        #: Jim band joy chegarasi - `timeout` (yuqoridan o'qish undan ortiq
        #: kutmaydi); qari joy chegarasi - butun oqim umri + bitta o'qish.
        self._slots = _SlotPool(
            self.max_concurrent,
            idle_after=float(timeout) + _LEASE_GRACE,
            max_age=self.max_stream_seconds + float(timeout) + _LEASE_GRACE,
            clock=clock,
        )

    @property
    def configured(self) -> bool:
        """Kredensiallar berilganmi. Berilmasa savol umuman yuborilmaydi -
        yuqoridagi xizmat 401 qaytarardi, va bu foydalanuvchiga
        "sessiyangiz tugadi" bo'lib ko'rinardi."""
        return bool(self.base_url and self.client_id and self.client_secret)

    def busy(self) -> int:
        """Hozir band joylar soni (ochiq oqimlar)."""
        return self._slots.busy()

    def slots_state(self) -> dict[str, Any]:
        """`/api/health/detail` uchun: band / chegara, eng eski va eng jim
        joy, qaytarib olinganlar soni (ishga tushgandan beri)."""
        return self._slots.state()

    # --- savol -> oqim -------------------------------------------------------

    def stream(
        self,
        question: str,
        *,
        user_id: str,
        chat_id: str | None = None,
        tokens: Mapping[str, str] | None = None,
        hrm_employee: str | None = None,
        max_chars: int = 2000,
        mode: str = "standard",
        engine: str = "",
        op: str = "stream",
        style: str = "standard",
        audience: str = "private",
    ) -> AnswerStream:
        """Savolni yuboradi va kadr generatorini qaytaradi.

        Ulanish SHU YERDA ochiladi, generator ichida emas: 401/422/503
        kabi xatolar shunda ODDIY HTTP javobi bo'lib chiqadi. Generator
        ichida ochilsa, biz allaqachon 200 yuborib bo'lgan bo'lardik va
        xato brauzerga "uzilgan oqim" bo'lib ko'rinardi.

        `engine` - `v1` ... `v5` | `""` (versiyasiz, xizmat default'i). Default
        `""`: klient o'zi tanlamaydi - qaysi dvigatel ekanini chaqiruvchi
        (`chat.open_stream`, kanal bo'yicha) aytadi.

        `op` - hisobdagi amal nomi (`assistant / <op>`). Chat - `stream`; yig'ilish
        xulosasi o'z nomlari bilan (`meeting_extract`, ...) - admin panelda chat
        savollari va fondagi xulosa yuki ajralib ko'rinsin.

        `style` - `voice`: savol GAPIRILGAN (ovozli suhbat, `chat.voice_style`). Faqat
        shartnoma 4.0 dvigatellariga (v4, v5) yuboriladi (`_V4_VOICE`); boshqasida e'tiborsiz.

        `audience` - `group`: javob Telegram GURUHIDA hammaga ko'rinadi (`_V4_GROUP`).
        Faqat v4 / v5 da ma'noli - v1-v3 da cheklov tokenlar bilan (`chat.open_stream`).
        """
        if engine not in ROUTES:
            # Dasturchi xatosi: `core/engines.py` faqat shu qiymatlarni beradi.
            raise ValueError(f"noma'lum dvigatel: {engine!r}")
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
        # `tokens` XARITASI, `hrm_token` qisqa shakli EMAS - O'LCHANGAN.
        #
        # Hujjatda "hrm_token is the shorthand for tokens['hrm']" deb
        # yozilgan, lekin jonli xizmatda (2026-09-11) qisqa shakl
        # ISHLAMAYDI: aynan bir xil token bilan `hrm_token` yuborilsa
        # `auth_missing` qaytadi, `tokens: {"hrm": ...}` yuborilsa esa
        # to'liq javob keladi. Token o'zi joyida edi - HRM ning
        # `/api/account` i o'sha token bilan 200 qaytardi.
        #
        # Qisqa shaklni birga yuborish YO'Q: buzuq yo'l ustun kelib
        # qolsa, muammo yana qaytardi.
        #
        # BO'SH qiymatlar tashlanadi: bo'sh satr "sessiya bor, lekin
        # yaroqsiz" bo'lib tushunilishi mumkin, yo'qligi esa aniq
        # `auth_missing` beradi va foydalanuvchi tushunarli xabar oladi.
        live = {name: value for name, value in (tokens or {}).items() if value}
        if live:
            payload["tokens"] = live
        if hrm_employee:
            payload["hrm_employee"] = hrm_employee
        # `standard` YUBORILMAYDI: u xizmatning o'z default'i, va uni
        # ochiq yozish eski nusxalar uchun ortiqcha maydon bo'lardi.
        # `pro` esa faqat odam shu xabar uchun yoqqanda keladi - va FAQAT
        # "Pro" bor dvigatelga (v2, v3; katalogdagi `pro`). `chat.py`
        # buni oldinroq hal qiladi va izga yozadi; bu yer - ikkinchi to'r,
        # pulli rejim noto'g'ri yo'lga hech qachon ketmasin.
        pro_sent = mode == "pro" and engine in PRO_ENGINES
        if pro_sent:
            payload["mode"] = "pro"
        elif mode == "pro":
            log.info("Assistant: 'pro' tashlandi - dvigatel %s ('pro' faqat %s da)",
                     engine or "versiyasiz", ", ".join(sorted(PRO_ENGINES)))
        contract = engine in CONTRACT_ENGINES
        headers: dict[str, str] = {}
        if contract:
            # Shartnoma 4.0: sarlavha bilan `purpose` MAJBURIY (usiz 400). Qolgan
            # maydonlar v3 niki - agent ularni o'sha ma'noda o'qiydi.
            headers["X-Barno-Contract"] = V4_CONTRACT
            payload.update(_V4_CHAT)
            if audience == "group":
                # Ovoz guruhda yo'q: "ha" so'zi bilan bajarish faqat shaxsiy suhbatda.
                payload.update(_V4_GROUP)
            elif style == _V4_VOICE:
                payload["style"] = _V4_VOICE

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        path = stream_path(engine)

        # Slot oqim TUGAGANDA bo'shatiladi (`finally` ichida), javob
        # kelganda emas: oqim davomida yuqoridagi LLM hali band.
        lease = self._slots.acquire()
        if lease is None:
            state = self._slots.state()
            # ALOHIDA sabab bilan: foydalanuvchi "xizmat band" ko'radi, lekin
            # bu BIZNING navbatimiz - yuqoridagi xizmatga umuman borilmagan.
            log.warning("Assistant navbati to'la (%d/%d band, eng eskisi %s s, eng jimi %s s) - "
                        "yuqoriga BORILMADI [queue_full]", state["busy"], state["limit"],
                        state["oldestSec"], state["idlestSec"])
            raise AssistantError("navbat to'la", status=503, retryable=True, reason="queue_full")
        # Hisob: chaqiruv ULANISHDAN boshlanadi va oqim TUGAGANDA yopiladi,
        # ya'ni davomiyligi - butun javob. Kim/qaysi savol - `begin` shu
        # paytdagi kontekstdan oladi (oqim keyin boshqa ipda o'qilsa ham).
        end = _StreamEnd(begin("assistant", op or "stream"), lease)
        try:
            with _mapped_errors(self.client_secret):
                response = self._open(path, body, accept="application/x-ndjson",
                                      request_id=request_id, extra_headers=headers)
            end.response = response
            end.call.http_status = _http_status(response)
            # Xizmat o'z `X-Request-Id` ini qaytarsa - AUDIT kaliti o'shanikisi.
            served = (response.headers.get("X-Request-Id") or "").strip()
            outcome: dict[str, Any] = {}
            opened_at = self._clock()
            deadline = self.max_stream_seconds

            def pump() -> Iterator[bytes]:
                total = 0
                frames = 0
                # `done` kadri keldimi - oqim TO'LIQ tugaganining YAGONA
                # belgisi. Ulanish ikki kadr ORASIDA yopilsa `http.client`
                # ning chunked o'quvchisi `b''` qaytaradi - bu toza EOF
                # bilan bir xil ko'rinadi va xato ko'tarilmaydi. `done` ni
                # sanamasak, yarim javob brauzerga TO'LIQ javob bo'lib
                # borardi (`mock:cut` stsenariysi, `tools/dev_mock_upstream.py`).
                finished = False
                failure: BaseException | None = None
                # v4: oxirgi HAQIQIY kadr vaqti (`ping` emas) va javob matni boshlanganmi
                # (ovozli gaplar orasiga bo'shliq) - modul izohi, v4.
                heard = opened_at
                said = False
                try:
                    while True:
                        # "Tirik" belgisi: oqim o'qilyapti. O'qilmay qolgan
                        # (tashlab ketilgan) joyni navbat shu belgi bo'yicha
                        # taniydi va qaytarib oladi (`_SlotPool`).
                        lease.touch()
                        try:
                            line = response.readline(_MAX_LINE_BYTES + 1)
                        except (TimeoutError, socket_timeout) as exc:
                            raise AssistantError("javob to'xtab qoldi (timeout)",
                                                 status=504, reason="upstream_timeout") from exc
                        except (http.client.HTTPException, OSError) as exc:
                            # Ulanish javob O'RTASIDA uzildi. Buni AYNAN shu
                            # yerda tutish kerak: bu xato tipi chaqiruvchiga
                            # yetib borsa, u faqat `AssistantError` ni
                            # kutayotgani uchun oqim brauzerga kutilmagan
                            # uzilish bo'lib ko'rinardi.
                            raise AssistantError(f"javob oqimi uzildi: {exc}",
                                                 status=503, retryable=True) from exc
                        lease.touch()
                        if not line:
                            break
                        if not finished and self._clock() - opened_at > deadline:
                            # Butun javob umri chegaradan oshdi. Chegarasiz oqim
                            # slotni abadiy ushlab turardi - va navbatning o'zini
                            # davolashi aynan shu chegaraga tayanadi.
                            log.warning("Assistant oqimi %d s dan oshdi (%s) - uzildi",
                                        int(deadline), served or request_id)
                            raise AssistantError("javob juda uzoq cho'zildi (oqim muddati)",
                                                 status=504, reason="stream_deadline")
                        if len(line) > _MAX_LINE_BYTES:
                            # Bitta kadr chegaradan katta: qolgan qismi
                            # keyingi o'qishda kelib, buzuq JSON bo'lib
                            # tashlanardi - ya'ni oqimning qolgani ham
                            # ishonchsiz. To'xtaymiz.
                            log.warning("Assistant kadri chegaradan katta: %d bayt", len(line))
                            if finished:
                                break
                            # `done` hali kelmagan - javob YARIM. Jim
                            # `break` uni to'liq javob qilib ko'rsatardi.
                            raise AssistantError("javob oqimi uzildi (kadr chegaradan katta)",
                                                 status=502)
                        total += len(line)
                        if total > _MAX_STREAM_BYTES:
                            log.warning("Assistant oqimi chegaradan oshdi (%s): %d bayt",
                                        served or request_id, total)
                            if finished:
                                break
                            raise AssistantError("javob oqimi uzildi (oqim chegaradan katta)",
                                                 status=502)
                        out = _clean_frame(line, self.base_url)
                        if out is None:
                            continue
                        if contract:
                            if out.get("type") == "ping":
                                # Agent tirik, lekin JAVOB yo'q. v3 dagi kabi `timeout`
                                # soniyadan keyin uziladi - `ping` jimlikni uzaytirmaydi.
                                if self._clock() - heard > self.timeout:
                                    raise AssistantError("javob to'xtab qoldi (timeout)",
                                                         status=504, reason="upstream_timeout")
                                continue
                            heard = self._clock()
                            out = _from_v4(out, said)
                            if out is None:
                                continue
                            said = said or (out.get("type") == "token" and bool(out.get("text")))
                        frames += 1
                        if out.get("type") == "done":
                            outcome["route"] = out.get("route")
                            # Haqiqatda javob bergan dvigatel (versiyalangan yo'lda).
                            if isinstance(out.get("engine"), str) and out["engine"]:
                                outcome["engine"] = out["engine"]
                            if not pro_sent:
                                # "Pro" so'ralmagan (yoki bu dvigatelda yo'q) -
                                # blok brauzerga O'TMAYDI: aks holda klient
                                # "Pro ishlatildi" belgisini ko'rsatardi.
                                out.pop("pro", None)
                            elif isinstance(out.get("pro"), dict):
                                outcome["pro"] = out["pro"]
                            finished = True
                        elif out.get("type") == "error":
                            outcome["error"] = out.get("code")
                        yield json.dumps(out, ensure_ascii=False).encode("utf-8") + b"\n"
                    if not finished:
                        # EOF, lekin `done` yo'q: yuqoridagi xizmat yoki
                        # oradagi proksi ulanishni kadrlar orasida yopdi.
                        # Xato SHU YERDA ko'tariladi - `chat.py` uni allaqachon
                        # xato kadri + `done` ga o'giradi va savol izda
                        # `error` bo'lib qoladi. `error` kadri kelgan bo'lsa
                        # ham `done` shart: hujjat bo'yicha u `error` dan
                        # KEYIN keladi, kelmasa oqim baribir chala.
                        raise AssistantError("javob oqimi uzildi (done kadri kelmadi)",
                                             status=503, retryable=True)
                except BaseException as exc:
                    failure = exc
                    raise
                finally:
                    outcome["frames"] = frames
                    end.call.units.update(frames=frames, bytes=total)
                    end(failure)

            frames_iter = pump()
            # Generator HECH BOSHLANMAY tashlab ketilsa (brauzer sarlavhadan
            # keyin, tanadan oldin uzildi) uning `finally` si ishlamaydi -
            # slot mangu band qolardi. Yakun UCH YO'LDAN, qaysi biri birinchi:
            # `pump` ning `finally` si, `AnswerStream.close()` va obyekt
            # yig'ilganda `weakref.finalize`. Uchalasi ham tushmay qolsa
            # (generator tsiklda yoki biror joyda abadiy ushlanib qolgan) -
            # navbatning o'zi uni eskirgan deb qaytarib oladi (`_SlotPool`).
            weakref.finalize(frames_iter, end, _ABANDONED)
            return AnswerStream(request_id=served or request_id, frames=frames_iter,
                                outcome=outcome, engine=engine, _end=end)
        except BaseException as exc:
            # Oqim ochilmadi - slotni DARHOL qaytaramiz, aks holda birinchi
            # nosozlik navbatni abadiy egallab qolardi.
            end(exc)
            if isinstance(exc, AssistantError):
                log.warning("Assistant oqimi ochilmadi [%s] (%s): %s",
                            exc.reason or "?", path, exc)
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
            # Javob bergan dvigatel (`done.engine`), bo'lmasa so'ralgani.
            "engine": stream.outcome.get("engine") or stream.engine or None,
            "pro": stream.outcome.get("pro"),
            "answer": "".join(answer),
            "sources": sources,
            "artifact": artifact,
            "stages": stages,
            "error": error,
        }

    # --- yozuv amallari ------------------------------------------------------

    def confirm_action(self, token: str, *, user_id: str,
                       tokens: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Taklif qilingan yozuv amalini BAJARADI - faqat odam bosgandan keyin.

        Bajariladigan reja taklif paytida xizmatda saqlangan - ya'ni nima
        bo'lsa, odam ko'rgan narsa bo'ladi; biz faqat kalitni, o'sha odamning
        `user_id` sini (taklif kim uchun bo'lsa, o'sha tasdiqlaydi) va uning
        platforma tokenini yuboramiz (taklif tokenni saqlamagan).
        """
        return self._action(token, "confirm", user_id=user_id, tokens=tokens)

    def cancel_action(self, token: str, *, user_id: str,
                      tokens: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Taklifni bekor qiladi - endi tasdiqlab bo'lmaydi. Hech narsa
        o'zgarmagan edi, bu faqat tartib."""
        return self._action(token, "cancel", user_id=user_id, tokens=tokens)

    def get_action(self, token: str) -> dict[str, Any]:
        """Taklifning holati: pending | executed | failed | cancelled | expired."""
        return self._action(token, None)

    def _action(self, token: str, verb: str | None, *, user_id: str = "",
                tokens: Mapping[str, str] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise AssistantError("HR Assistant sozlanmagan", status=501)
        if not _SAFE_KEY.fullmatch(token or ""):
            raise AssistantError("amal kaliti yaroqsiz", status=400)
        path = f"/api/actions/{token}" + (f"/{verb}" if verb else "")
        body: dict[str, Any] | None = None
        if verb:
            body = {"user_id": user_id}
            live = {name: value for name, value in (tokens or {}).items() if value}
            if live:
                body["tokens"] = live
        return self._json(path, method="POST" if verb else "GET", body=body,
                          limit=_MAX_LINE_BYTES, what="amal", op=f"action.{verb or 'get'}")

    def pro_quota(self, *, user_id: str) -> dict[str, Any]:
        """Odamning "Pro" byudjeti: qolgani, chegarasi va sarflangani.

        Uchta oyna: oxirgi 24 soat / 7 kun / 30 kun (SURILADIGAN, ya'ni
        "kun boshida nollanadi" EMAS).

        CHEGARALAR QOTIRILMAYDI: hujjat aniq aytadi - ular rolga qarab
        keyinroq pasayadi, va yagona haqiqat manbai shu endpoint.
        """
        return self._json("/api/pro/quota", query={"user_id": user_id}, what="Pro byudjeti",
                          op="pro.quota")

    # --- suhbatlar tarixi ----------------------------------------------------
    #
    # Suhbatlar yuqoridagi xizmatda `(ilova, user_id)` bo'yicha saqlanadi:
    # boshqa odamning yoki boshqa ilovaning suhbati ro'yxatga TUSHMAYDI va
    # kaliti ma'lum bo'lsa ham 404 beradi. Ya'ni ajratish shu yerda emas,
    # xizmatda - bizning ishimiz to'g'ri `user_id` yuborish (`chat.py`
    # dagi `assistant_user_id`), boshqa hech narsa.

    def list_chats(self, *, user_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Odamning suhbatlari: oxirgi faollik bo'yicha, yangisi birinchi.
        O'chirilganlar ro'yxatga kirmaydi."""
        return self._json("/api/chats",
                          query={"user_id": user_id, "limit": limit, "offset": offset},
                          what="suhbatlar ro'yxati", op="chats.list")

    def get_chat(self, chat_id: str, *, user_id: str, limit: int = 200) -> dict[str, Any]:
        """Bitta suhbat xabarlari bilan - eskisi birinchi, oxirgi `limit` tasi."""
        return self._json(self._chat_path(chat_id), query={"user_id": user_id, "limit": limit},
                          what="suhbat", op="chats.get")

    def rename_chat(self, chat_id: str, *, user_id: str, title: str) -> dict[str, Any]:
        """Nomini o'zgartiradi. Shundan keyin model nomga BOSHQA TEGMAYDI
        (`title_source` = `user`)."""
        return self._json(self._chat_path(chat_id), method="PATCH",
                          query={"user_id": user_id}, body={"title": title}, what="suhbat nomi",
                          op="chats.rename")

    def delete_chat(self, chat_id: str, *, user_id: str) -> dict[str, Any]:
        """YUMSHOQ o'chirish: suhbat ro'yxatdan chiqadi va ochilmaydi, lekin
        hech narsa o'chmaydi - `restore_chat` yoki o'sha `chat_id` bilan
        yangi savol uni qaytaradi. Takroriy chaqiruv xato emas."""
        return self._json(self._chat_path(chat_id), method="DELETE",
                          query={"user_id": user_id}, what="suhbatni o'chirish",
                          op="chats.delete")

    def restore_chat(self, chat_id: str, *, user_id: str) -> dict[str, Any]:
        """O'chirishni bekor qiladi - nomi va xabarlari bilan qaytadi."""
        return self._json(self._chat_path(chat_id) + "/restore", method="POST",
                          query={"user_id": user_id}, what="suhbatni tiklash",
                          op="chats.restore")

    @staticmethod
    def _chat_path(chat_id: str) -> str:
        """`/api/chats/{chat_id}` - kalit tekshirilgan va yo'lga mos qilingan.

        Kalitni brauzer yaratadi (UUID), lekin unga ishonilmaydi: yo'l
        ajratgichi yoki nuqtali ketma-ketlik bo'lsa so'rov xizmatga umuman
        bormaydi.
        """
        if not _SAFE_KEY.fullmatch(chat_id or ""):
            raise AssistantError("suhbat kaliti yaroqsiz", status=400)
        return f"/api/chats/{urllib.parse.quote(chat_id, safe='')}"

    # --- xotira va platforma kalitlari (3.3, 2026-10-10) ---------------------
    #
    # Ikkalasi ham suhbatlar kabi `(ilova, user_id)` bo'yicha: odam faqat O'Z
    # xotirasini ko'radi va o'chiradi, boshqa odamning kaliti 404 beradi. Bizning
    # ishimiz yana bitta - to'g'ri `user_id` (`chat.assistant_user_id`).
    #
    # Beshala yo'l ham `quiet=True`: xizmat xato tanasida odam haqidagi gapni
    # qaytarsa ham u jurnalga va hisobga tushmaydi. Platforma javobida xotira
    # yo'q, lekin xizmatdagi xato chat yoki xotira kontekstini xato matniga
    # "aks ettirsa" ham - `/assistant/*` ning hammasiga BITTA qoida. Muvaffaqiyatli
    # javob esa umuman yozilmaydi - faqat soni.
    #
    # "connectors" NOMI BIZDA BAND: `/api/v1/connectors` - odamning HRM/CRM
    # LOGIN tokenlari. Xizmatning `/api/connectors` i esa boshqa narsa -
    # "Barno shu manbadan foydalansinmi" kalitlari. Chalkashmasin deb bizda ular
    # "platformalar" (`platforms.*`).

    def list_memory(self, *, user_id: str, timeout: float | None = None) -> dict[str, Any]:
        """Odamning uzoq muddatli xotirasi: o'zi "eslab qol" degani, so'rashidan
        o'rganilgan odatlar va tasdiqlagan CRM vazifalaridan o'rganilgan tartib."""
        return self._json("/api/memory", query={"user_id": _owner(user_id)}, what="xotira",
                          op="memory.list", timeout=timeout, quiet=True)

    def delete_memory_item(self, item_id: str, *, user_id: str,
                           timeout: float | None = None) -> dict[str, Any]:
        """Bitta xotira bandini butunlay o'chiradi. Boshqa odamniki yoki yo'q - 404."""
        if not _MEMORY_ID.fullmatch(item_id or ""):
            raise AssistantError("xotira kaliti yaroqsiz", status=400)
        return self._json(f"/api/memory/{urllib.parse.quote(item_id, safe='')}", method="DELETE",
                          query={"user_id": _owner(user_id)}, what="xotira bandi",
                          op="memory.delete", timeout=timeout, quiet=True)

    def clear_memory(self, *, user_id: str, timeout: float | None = None) -> dict[str, Any]:
        """HAMMASINI unutadi (CRM dan o'rganilgan tartib ham). Suhbatlarga
        tegmaydi. Tasdiqni chaqiruvchi so'raydi - bu yerda faqat bajarish."""
        return self._json("/api/memory", method="DELETE", query={"user_id": _owner(user_id)},
                          what="xotirani tozalash", op="memory.clear", timeout=timeout,
                          quiet=True)

    def list_platforms(self, *, user_id: str, timeout: float | None = None) -> dict[str, Any]:
        """Barno o'qiydigan platformalar (HRM, CRM, DWH, Biznes 24/7, ...) va
        odamning har biri uchun kaliti. Odam o'chirmaguncha hammasi yoqiq."""
        return self._json("/api/connectors", query={"user_id": _owner(user_id)},
                          what="platformalar", op="platforms.list", timeout=timeout,
                          quiet=True)

    def set_platform(self, platform_id: str, *, user_id: str, enabled: bool,
                     timeout: float | None = None) -> dict[str, Any]:
        """Odam uchun platformani yoqadi/o'chiradi. Server o'chirgan platforma
        (`available: false`) odam nima desa ham ishlamaydi. Noma'lum id - 404."""
        if not _PLATFORM_ID.fullmatch(platform_id or ""):
            raise AssistantError("platforma kaliti yaroqsiz", status=400)
        return self._json(f"/api/connectors/{platform_id}", method="PUT",
                          query={"user_id": _owner(user_id)}, body={"enabled": bool(enabled)},
                          what="platforma kaliti", op="platforms.set", timeout=timeout,
                          quiet=True)

    def _json(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        limit: int = _MAX_JSON_BYTES,
        what: str = "javob",
        op: str = "json",
        timeout: float | None = None,
        quiet: bool = False,
    ) -> dict[str, Any]:
        """JSON so'rov -> JSON obyekt. Yozuv amallari va suhbatlar tarixi
        uchun umumiy qatlam; oqim (`stream`) va fayllar (`_download`) bundan
        o'tmaydi - ular javobni bo'lak-bo'lak beradi.

        `what` - xato matnida "qaysi javob" ekani (`amal`, `suhbat`); jurnal
        o'qiydigan odam uchun. `op` - hisobdagi amal nomi (`chats.list`,
        `action.confirm`): admin panel xizmat yukini amal bo'yicha ajratadi.

        `timeout` - shu chaqiruv uchun (berilmasa `self.timeout`, oqimniki):
        sozlamalar ekrani 120 s kutib turmasligi kerak. `quiet` - xato matniga
        xizmat javobining TANASI qo'shilmaydi (faqat status): xotira yo'llarida
        tana odam haqidagi gapni qaytarishi mumkin, xato matni esa jurnalga va
        hisobga (`api_calls.error`) tushadi.
        """
        if not self.configured:
            raise AssistantError("HR Assistant sozlanmagan", status=501)
        if query:
            path = f"{path}?{urllib.parse.urlencode(query)}"
        raw_body = (json.dumps(body, ensure_ascii=False).encode("utf-8")
                    if body is not None else None)
        request_id = uuid.uuid4().hex
        call = begin("assistant", op)
        try:
            with _mapped_errors(self.client_secret, quiet=quiet):
                response = self._open(path, raw_body, accept="application/json",
                                      request_id=request_id, method=method,
                                      timeout=timeout, follow_redirects=False)
                with contextlib.closing(response):
                    raw = response.read(limit + 1)
                    served = (response.headers.get("X-Request-Id") or "").strip()
            call.http_status = _http_status(response)
            call.units["bytes"] = len(raw)
            if len(raw) > limit:
                # Qisqartirib tahlil qilish buzuq JSON berardi; sabab aniq aytiladi.
                raise AssistantError(f"Assistant {what} javobi chegaradan katta", status=502)
            try:
                result = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise AssistantError(f"Assistant {what} javobi o'qilmadi", status=502) from exc
            if not isinstance(result, dict):
                raise AssistantError(f"Assistant {what} javobi obyekt emas", status=502)
        except BaseException as exc:
            call.end("error", http_status=_upstream_status(exc), error=exc)
            raise
        call.end()
        # Audit kaliti: xizmatniki ustun, bo'lmasa biznikini yozamiz.
        result.setdefault("request_id", served or request_id)
        return result

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
        if not artifact_ref_ok(token, kind):
            raise AssistantError("fayl kaliti yaroqsiz", status=400)
        return self._download(f"/api/hr/artifacts/{urllib.parse.quote(token, safe='')}/{kind}",
                              op="artifact")

    def fetch_doc(self, doc_id: str) -> tuple[str, str, Iterator[bytes]]:
        """Iqtibos qilingan hujjat PDF'i."""
        if not doc_id or not _SAFE_KEY.fullmatch(doc_id):
            raise AssistantError("hujjat kaliti yaroqsiz", status=400)
        return self._download(f"/doc/{urllib.parse.quote(doc_id, safe='')}", op="doc")

    def _download(self, path: str, *, op: str = "download") -> tuple[str, str, Iterator[bytes]]:
        if not self.configured:
            raise AssistantError("HR Assistant sozlanmagan", status=501)
        # Hisob oqimdagi kabi: ochilishdan fayl oxirigacha, birligi - bayt.
        end = _StreamEnd(begin("assistant", op))
        try:
            with _mapped_errors(self.client_secret):
                response = self._open(path, None, accept="*/*", request_id=uuid.uuid4().hex)
        except BaseException as exc:
            end(exc)
            raise
        end.response = response
        end.call.http_status = _http_status(response)
        content_type = (response.headers.get("Content-Type") or "application/octet-stream").strip()
        filename = _filename(response.headers.get("Content-Disposition") or "", path)

        def pump() -> Iterator[bytes]:
            total = 0
            failure: BaseException | None = None
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
            except BaseException as exc:
                failure = exc
                raise
            finally:
                end.call.units["bytes"] = total
                end(failure)

        chunks = pump()
        weakref.finalize(chunks, end, _ABANDONED)
        return content_type, filename, chunks

    # --- past qatlam ---------------------------------------------------------

    def _open(self, path: str, body: bytes | None, *, accept: str, request_id: str,
              method: str | None = None, timeout: float | None = None,
              follow_redirects: bool = True, extra_headers: Mapping[str, str] | None = None):
        """So'rovni ochadi. `method` berilmasa tanasi borligiga qarab POST/GET:
        suhbatlar tarixi PATCH, DELETE va tanasiz POST ham ishlatadi.
        `timeout` berilmasa - `self.timeout` (oqim uchun tanlangan).
        `extra_headers` - yo'lga xos sarlavhalar (v4: `X-Barno-Contract`); asosiylarni
        (kalit, `X-Request-Id`) almashtira OLMAYDI.

        `follow_redirects=False` (JSON yo'llari): `urllib` 30x ga ergashganda
        BIZNING sarlavhalarimizni - `X-Client-Secret` ni ham - yangi manzilga,
        hatto boshqa hostga ko'chirib yuboradi. JSON yo'llariga yo'naltirish
        hech qachon kerak emas, shuning uchun 30x - xato (`_mapped_errors` da
        502), sir esa joyida qoladi. Fayl va oqim yo'llari hozircha avvalgidek
        (hujjat PDF'i yo'naltirilishi mumkinligi tekshirilmagan)."""
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
        for name, value in (extra_headers or {}).items():
            headers.setdefault(name, value)
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers,
            method=method or ("POST" if body is not None else "GET"),
        )
        # Muhit proksisi CHETLAB o'tiladi: manzil ichki, va tashqi proksi
        # orqali yuborish so'rovni sirtga chiqarib qo'yardi.
        handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
        if not follow_redirects:
            handlers.append(_NoRedirect())
        opener = urllib.request.build_opener(*handlers)
        return opener.open(request, timeout=self.timeout if timeout is None else timeout)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """30x ga ergashmaydi: `redirect_request` `None` qaytarsa, `urllib` javobni
    `HTTPError` (status 30x) qilib ko'taradi - sarlavhalar hech qayerga ketmaydi."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


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
    elif kind == "proposal":
        _strip_proposal_urls(frame)
    return frame


def _strip_proposal_urls(frame: dict[str, Any]) -> None:
    """`confirm_url` / `cancel_url` OLIB TASHLANADI.

    Ular yuqoridagi xizmatning ICHKI manzilini ko'rsatadi va ilova sirini
    talab qiladi - brauzer ularni baribir chaqira olmaydi. Tasdiqlash
    Venera'ning o'z yo'li orqali: `POST /api/v1/actions/{token}/confirm`.
    Maydonlar `proposal` ostida ham, yassi ham kelishi mumkin (ariza kadri
    kabi) - ikkalasi tozalanadi.
    """
    for holder in (frame, frame.get("proposal")):
        if isinstance(holder, dict):
            holder.pop("confirm_url", None)
            holder.pop("cancel_url", None)


def artifact_ref_ok(token: str, kind: str) -> bool:
    """Kalit va tur yuklab olish yo'liga mosmi - `fetch_artifact` va
    Telegram havolasi (`chat.py`) BIR XIL qoida bilan tekshiradi."""
    return kind in ARTIFACT_KINDS and bool(_ARTIFACT_URL.fullmatch(f"/api/hr/artifacts/{token}/{kind}"))


def doc_ref_ok(doc_id: str) -> bool:
    """Iqtibos hujjati kaliti yo'lga qo'yishga yaroqlimi - `fetch_doc` bilan
    BIR XIL qoida (`_SAFE_KEY`). Telegram havolasi (`chat.py`) imzolashdan
    oldin shu bilan tekshiradi: yaroqsiz kalitga havola berilmasin."""
    return isinstance(doc_id, str) and bool(_SAFE_KEY.fullmatch(doc_id))


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
    """Iqtibos qilingan hujjatga Venera orqali havola qo'shadi va tashqi
    havolalarni tekshiradi.

    Xizmatning o'z `doc_id` si saqlanadi (frontend uni ko'rsatadi), yoniga
    `docUrl` qo'shiladi - brauzer AYNAN shu yo'l bilan PDF'ni ocha oladi.

    QONUNCHILIK (`kind: "law"`, v2) - `url` LEX.UZ dagi moddaga, `docUrl`
    BERILMAYDI: hujjat ko'ruvchisi (`/doc/...`) faqat `doc_id` uchun, xat ham
    "do not try to open it in the document viewer" deydi. `url` HAR QANDAY
    manbada tekshiriladi (`safe_source_url`): u brauzerda havola bo'lib
    ochiladi, ya'ni `javascript:` yoki `data:` o'tib ketsa - bu XSS.
    """
    for key in ("sources", "items"):
        items = frame.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if "url" in item:
                item["url"] = safe_source_url(item["url"])
            if item.get("kind") == "law":
                # Xizmat adashib `doc_id` yoki o'z `docUrl` ini qo'shsa ham -
                # qonun moddasi hujjat ko'ruvchisiga yo'naltirilmaydi.
                item.pop("docUrl", None)
                continue
            doc_id = item.get("doc_id")
            if item.get("kind") == "doc" and isinstance(doc_id, str) and doc_id:
                if _SAFE_KEY.fullmatch(doc_id):
                    item["docUrl"] = f"/api/v1/chat/doc/{urllib.parse.quote(doc_id, safe='')}"
                page = item.get("page")
                if isinstance(page, int) and page > 0 and item.get("docUrl"):
                    item["docUrl"] = f"{item['docUrl']}#page={page}"


def _from_v4(frame: dict[str, Any], said: bool) -> dict[str, Any] | None:
    """v4 kadri -> klientlar biladigan (v3) shakl; `None` - klientga O'TMAYDI.

    XIZMAT kadrlari (`ping`, `result`) tashlanadi, `done` dan v4 qo'shimchalari
    (`meta`, `cited_ids`) olinadi - modul izohi, v4. Notanish YANGI kadrlar
    (`action` - ovozda "ha" bilan bajarilgan amal) avvalgidek o'tadi: klientlar
    ularni e'tiborsiz qoldiradi, iz esa yozib oladi.

    OVOZLI USLUBDA (`style: voice`) har `token` - TUGAL gap (`sentence: n`), agent
    hujjati "gaplarni bo'shliq bilan qo'shing" deydi. Bizning klientlar (web, Mini App,
    Android, bot) bo'laklarni TO'G'RIDAN-TO'G'RI qo'shadi - bo'shliqsiz "...o'tgan.Qolgan"
    bo'lib qolardi. `said` - shu javobda oldin matn bo'lgan: bo'shliq SHU YERDA, bitta
    joyda qo'shiladi (to'rt klientni o'zgartirish o'rniga).
    """
    kind = frame.get("type")
    if kind in _V4_SERVICE_FRAMES:
        return None
    if kind == "token" and said and "sentence" in frame:
        text = frame.get("text")
        if isinstance(text, str) and text and not text[0].isspace():
            frame["text"] = " " + text
    elif kind == "done":
        for key in _V4_DONE_EXTRA:
            frame.pop(key, None)
    return frame


def stream_path(engine: str) -> str:
    """Dvigatel -> oqim yo'li: `v2` -> `/api/v2/chat/stream`, `""` -> `/api/chat/stream`."""
    if engine not in ROUTES:
        raise ValueError(f"noma'lum dvigatel: {engine!r}")
    return f"/api/{engine}/chat/stream" if engine else "/api/chat/stream"


def is_law_host(host: str) -> bool:
    """`lex.uz` yoki uning quyi domeni (`www.lex.uz`)."""
    host = (host or "").lower().rstrip(".")
    return any(host == name or host.endswith("." + name) for name in LAW_HOSTS)


def safe_source_url(value: Any) -> str | None:
    """Manba havolasi brauzerga berilsa bo'ladimi: bo'lsa (tozalangan) manzil,
    bo'lmasa `None` (havola ko'rsatilmaydi, manbaning o'zi qoladi).

    QOIDA - FAQAT `https://`:
      * `javascript:`, `data:`, `vbscript:`, `file:` va sxemasiz (`//...`)
        manzil - YO'Q: brauzerda bosilganda kod bajarardi yoki noma'lum
        joyga olib ketardi;
      * `http://` - YO'Q, faqat LEX.UZ uchun `https://` ga ko'tariladi
        (sayt https da ishlaydi, shifrsiz havola esa yo'lda almashtirilishi
        mumkin);
      * login-parolli manzil (`https://lex.uz@boshqa.sayt/`) - YO'Q: ko'zga
        LEX.UZ bo'lib ko'rinadi, aslida boshqa saytga olib boradi;
      * bo'shliq, boshqaruv belgilari yoki 2048 dan uzun - YO'Q.

    LEX.UZ dan boshqa `https` domen O'TADI, lekin jurnalga yoziladi.
    """
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or len(url) > _MAX_URL_CHARS or any(
            ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        if url:
            log.warning("Manba havolasi rad etildi (yaroqsiz belgilar yoki uzun)")
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        has_login = parts.username is not None or parts.password is not None
        _ = parts.port                      # buzuq port ValueError beradi
    except ValueError:
        log.warning("Manba havolasi rad etildi (o'qilmadi)")
        return None
    scheme = parts.scheme.lower()
    if not host or has_login:
        log.warning("Manba havolasi rad etildi (%s: domen yo'q yoki login bilan)",
                    scheme or "sxemasiz")
        return None
    if scheme == "http" and is_law_host(host):
        url = "https" + url[len(parts.scheme):]
        scheme = "https"
    if scheme != "https":
        # Sxemaning O'ZI yoziladi, manzil emas - u jurnalga hiyla matn
        # olib kirishi mumkin.
        log.warning("Manba havolasi rad etildi (sxema %s)", scheme[:16] or "yo'q")
        return None
    if not is_law_host(host):
        log.warning("Manba havolasi LEX.UZ emas: %s - o'tkazildi", host[:100])
    return url


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


def token_warning(token: str, *, key: str = "hrm_token") -> str | None:
    """`/api/health` uchun bir qatorli holat. `None` - aytishga hojat yo'q.

    `key` - `.env` dagi kalit nomi (`hrm_token` yoki `crm_token`). Xabarda
    AYNAN shu nom ko'rsatiladi, chunki uni tuzatadigan odam faylda o'sha
    qatorni izlaydi.

    `exp` HAQIQIY umr emas, faqat TOKEN AYTGAN muddat: HRM sessiyani
    o'zidan oldin ham bekor qilishi mumkin (jonli o'lchov: `exp` 10 soat
    ko'rsatgan token amalda bir necha daqiqada yaroqsiz bo'ldi). Shuning
    uchun xabarda "exp bo'yicha" deb aytiladi - aks holda odam "hali 9
    soat bor" deb, muammoni butunlay boshqa joyda izlardi.
    """
    if not token:
        return None
    platform = key.removesuffix("_token").upper() or key
    shared = (f"umumiy token: jonli {platform} javoblari har kim uchun TOKEN EGASI "
              "haqida bo'ladi")
    left = token_seconds_left(token)
    if left is None:
        return f"{key} o'qib bo'lmadi (JWT emas?) - jonli {platform} ishlamaydi; {shared}"
    if left <= 0:
        return (f"{key} MUDDATI TUGAGAN ({-left} s oldin) - jonli {platform} savollari "
                "ishlamaydi, .env dagi qiymatni yangilang")
    return (f"{key} o'rnatilgan (exp bo'yicha {left // 60} daq qoldi, lekin {platform} "
            f"sessiyani oldin ham bekor qilishi mumkin) - vaqtincha, {shared}")


def _owner(user_id: str) -> str:
    """Xotira/platforma egasi. BO'SH `user_id` xizmatga HECH QACHON ketmaydi:
    "hammasini unut" chaqiruvi egasiz ketsa nima bo'lishini xizmatning
    tekshiruviga qoldirib bo'lmaydi."""
    value = (user_id or "").strip()
    if not value:
        raise AssistantError("foydalanuvchi kimligi bo'sh", status=400)
    return value


@contextlib.contextmanager
def _mapped_errors(secret: str, *, quiet: bool = False):
    """`urllib` xatolarini `AssistantError` ga o'giradi.

    401/403 ATAYLAB 502 ga tushadi: ular "bizning `X-Client-Secret`
    noto'g'ri" degani, ya'ni SOZLAMA xatosi. Brauzerga 401 qaytarish
    "sessiyangiz tugadi" degan ma'no berardi va foydalanuvchi o'zining
    mutlaqo joyida bo'lgan sessiyasidan chiqib ketardi.

    Har xatoga ICHKI sabab (`reason`) qo'yiladi: foydalanuvchi uchun
    "ulanib bo'lmadi" ham, "xizmat 503 qaytardi" ham bir xil 503, admin esa
    qaysi biri ekanini bilishi kerak (`AssistantError` izohi).

    `quiet` - javob tanasi matnga QO'SHILMAYDI (xotira yo'llari: tana odam
    haqidagi gapni qaytarishi mumkin, matn esa jurnal va hisobga tushadi).
    """
    try:
        yield
    except urllib.error.HTTPError as exc:
        status = exc.code
        detail = "-" if quiet else _redact(_detail(exc), secret)
        # 410 - taklifning muddati o'tgan (`/api/actions/...`, 2026-10 dan): uni
        # 502 ga ("xizmat javob bermadi") aylantirish odamni chalg'itardi.
        mapped = status if status in (400, 404, 410, 422, 503) else 502
        raise AssistantError(f"Assistant {status}: {detail}", status=mapped,
                             reason="upstream_busy" if status == 503 else "upstream_http",
                             upstream_status=status) from exc
    except urllib.error.URLError as exc:
        raise AssistantError(f"Assistant serveriga ulanib bo'lmadi: {exc.reason}",
                             status=503, retryable=True, reason="upstream_unreachable") from exc
    except (TimeoutError, socket_timeout) as exc:
        raise AssistantError("Assistant javob bermadi (timeout)", status=504,
                             reason="upstream_timeout") from exc
    except (http.client.HTTPException, OSError) as exc:
        raise AssistantError(f"Assistant ulanishi uzildi: {exc}",
                             status=503, retryable=True, reason="upstream_unreachable") from exc


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
        nested = parsed.get("error")
        if isinstance(nested, dict):
            # v4 xato shakli: `{"error": {"code", "message", ...}}` - xabar kirishimizni
            # qaytarmaydi (agent shartnomasi); kod admin uchun sababni aytadi.
            code = str(nested.get("code") or "")[:48]
            message = str(nested.get("message") or "")
            return (f"{code}: {message}" if code else message)[:300] or raw[:300]
        for key in ("detail", "message", "error", "text"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value[:300]
    return raw[:300]


# --- hisob (`api_calls`) ------------------------------------------------------

#: "Oqim o'qilmay tashlab ketildi" belgisi. `GeneratorExit` - hisobda
#: `cancelled` bo'lib yoziladi va XATO sanalmaydi: yuqoridagi xizmat
#: o'z ishini qilgan, klient ketib qolgan.
_ABANDONED = GeneratorExit("abandoned")


class _Lease:
    """Navbatdagi BITTA band joy. `release()` IDEMPOTENT: ikkinchi chaqiruv,
    yoki navbat joyni allaqachon qaytarib olgandan keyingi kech chaqiruv,
    hech narsa qilmaydi - boshqa birovning joyini bo'shatib yubormaydi."""

    __slots__ = ("_pool", "id", "acquired", "seen")

    def __init__(self, pool: "_SlotPool", lease_id: int, now: float) -> None:
        self._pool = pool
        self.id = lease_id
        #: Qachon olingan va oxirgi marta qachon "tirik" bo'lgan (o'qilgan).
        self.acquired = now
        self.seen = now

    def touch(self) -> None:
        """Oqim o'qilyapti - joy tashlab ketilmagan."""
        self.seen = self._pool.clock()

    def release(self) -> bool:
        """Joyni qaytaradi; `True` - haqiqatan qaytdi (birinchi chaqiruv)."""
        return self._pool._release(self)


class _SlotPool:
    """Yuqoridagi xizmatga bir vaqtda ketadigan oqimlar ulushi - O'ZINI DAVOLAYDI.

    NEGA ODDIY `BoundedSemaphore` EMAS. 29-sentabrda prod bir soatdan ko'p
    har savolga 503 "Savol-javob xizmati band" qaytardi - yordamchiga BIRORTA
    so'rov bormagan holda (yuqoridagi jamoa xati, 6-bo'lim). Semafora joyi
    faqat oqim generatorining `finally` sida qaytardi; brauzer sarlavhadan
    keyin, tanadan OLDIN uzilsa generator hech boshlanmaydi va joy abadiy
    band qoladi - `max_concurrent` ta shunday hodisadan keyin navbat mangu
    "to'la". Semafora kim qachon olganini bilmaydi, ya'ni buni o'zi
    tuzata olmaydi.

    BU YERDA HAR JOY - IJARA (`_Lease`): qachon olingani va oxirgi marta
    qachon o'qilgani ma'lum. Navbat TO'LGANDA (faqat shunda - oddiy yo'l
    arzon qoladi) ikki bosqich:

      1. `gc.collect()` (`_GC_EVERY` da ko'pi bilan bir marta): tsiklda
         qolgan, yetib bo'lmaydigan oqimlar yig'iladi va ularning
         `weakref.finalize` / `finally` si joyni HALOL qaytaradi (ulanish
         yopiladi, hisob yoziladi). Tsikl oson paydo bo'ladi: uzilgan klient
         istisnosining traceback'i oqim generatorini ushlab turadi, to'liq
         yig'ish esa jim serverda soatlab kelmasligi mumkin;
      2. ESKIRGAN ijaralar majburan qaytarib olinadi, ERROR bilan: `idle_after`
         dan ko'p o'qilmagan (tirik oqim yuqoridan o'qishda `timeout` dan ko'p
         kutmaydi) yoki `max_age` dan qari (oqim umri chegaralangan,
         `max_stream_seconds`). Bunday joy ANIQ tashlab ketilgan.

    Qaytarib olingan ijaraning egasi keyinroq `release()` qilsa - hech narsa
    bo'lmaydi (kalit bo'yicha), ya'ni hisob hech qachon manfiyga ketmaydi.
    """

    def __init__(self, size: int, *, idle_after: float, max_age: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.size = max(1, int(size))
        self.idle_after = float(idle_after)
        self.max_age = float(max_age)
        self.clock = clock
        self._lock = threading.Lock()
        self._leases: dict[int, _Lease] = {}
        self._ids = itertools.count(1)
        self._gc_at: float | None = None
        #: Ishga tushgandan beri majburan qaytarib olingan joylar.
        self.reclaimed = 0

    def busy(self) -> int:
        with self._lock:
            return len(self._leases)

    def state(self) -> dict[str, Any]:
        now = self.clock()
        with self._lock:
            leases = list(self._leases.values())
        return {
            "busy": len(leases),
            "limit": self.size,
            "oldestSec": int(max((now - lease.acquired for lease in leases), default=0)),
            "idlestSec": int(max((now - lease.seen for lease in leases), default=0)),
            "reclaimed": self.reclaimed,
        }

    def acquire(self) -> _Lease | None:
        """Bo'sh joy (ijara) yoki `None` - navbat haqiqatan to'la."""
        lease = self._take()
        if lease is not None:
            return lease
        if self._collect():
            lease = self._take()
            if lease is not None:
                log.warning("Assistant navbati: yig'ishdan keyin joy bo'shadi - "
                            "tashlab ketilgan oqim(lar) bor edi")
                return lease
        if self._reclaim():
            return self._take()
        return None

    def _take(self) -> _Lease | None:
        with self._lock:
            if len(self._leases) >= self.size:
                return None
            lease = _Lease(self, next(self._ids), self.clock())
            self._leases[lease.id] = lease
            return lease

    def _release(self, lease: _Lease) -> bool:
        with self._lock:
            return self._leases.pop(lease.id, None) is not None

    def _collect(self) -> bool:
        """`gc.collect()` - tez-tez emas. QULFSIZ: yig'ish paytida finalizer'lar
        `_release` ni chaqiradi va o'sha qulfni oladi."""
        now = self.clock()
        with self._lock:
            if self._gc_at is not None and now - self._gc_at < _GC_EVERY:
                return False
            self._gc_at = now
        gc.collect()
        return True

    def _reclaim(self) -> int:
        """Eskirgan ijaralarni qaytarib oladi; nechtasi qaytgani."""
        now = self.clock()
        with self._lock:
            stale = [lease for lease in self._leases.values()
                     if now - lease.seen > self.idle_after or now - lease.acquired > self.max_age]
            for lease in stale:
                del self._leases[lease.id]
            self.reclaimed += len(stale)
        if stale:
            log.error(
                "Assistant navbati: %d ta oqib ketgan joy qaytarib olindi (eng eskisi %d s, "
                "eng uzoq o'qilmagani %d s; chegaralar %d / %d s). Oqim yopilmay tashlab "
                "ketilgan - shu paytgacha klient uzilishlariga qarang",
                len(stale), int(max(now - lease.acquired for lease in stale)),
                int(max(now - lease.seen for lease in stale)), int(self.idle_after),
                int(self.max_age))
        return len(stale)


class _StreamEnd:
    """Oqim yakuni - BIR MARTA: slot qaytadi, ulanish yopiladi, hisob yoziladi.

    To'rt yo'ldan chaqiriladi, qaysi biri birinchi bo'lsa o'sha ishlaydi:
    generatorning `finally` si (oddiy tugash va o'rtada uzilish), ochilish
    xatosi, `AnswerStream.close()` va `weakref.finalize` - generator HECH
    BOSHLANMAY tashlab ketilganda. Oxirgilari bo'lmasa slot mangu band
    qolardi: TTS da aynan shu jonli tizimda o'lchangan (`services/tts.py`,
    `_Slot`), yordamchida esa 29-sentabr hodisasi (`_SlotPool`).
    """

    def __init__(self, call: Call, lease: _Lease | None = None) -> None:
        self.call = call
        self.response: Any = None
        self._lease = lease
        self._lock = threading.Lock()
        self._done = False

    def __call__(self, error: BaseException | None = None) -> None:
        with self._lock:
            if self._done:
                return
            self._done = True
        if self._lease is not None:
            self._lease.release()
        if self.response is not None:
            with contextlib.suppress(Exception):
                self.response.close()
        if error is None or isinstance(error, GeneratorExit):
            self.call.end("ok", error=error)
        else:
            self.call.end("error", http_status=_upstream_status(error), error=error)


def _http_status(response: Any) -> int:
    """Javob statusi (`http.client` da `.status`); bilinmasa 200 - bu yerga
    faqat muvaffaqiyatli ochilgan javob keladi."""
    status = getattr(response, "status", None)
    return status if isinstance(status, int) and 100 <= status <= 599 else 200


def _upstream_status(exc: BaseException) -> int | None:
    """Yuqoridagi xizmatning HAQIQIY statusi (`HTTPError.code`).

    `AssistantError.status` - FOYDALANUVCHIGA ko'rsatiladigani: xizmatning
    401 i u yerda 502. Admin esa aynan 401 ni ko'rishi kerak - "bizning
    ilova siri noto'g'ri" degani. HTTP javobi umuman bo'lmagan bo'lsa
    (`None`) hisob o'zi `AssistantError.status` ni oladi.
    """
    cause = exc.__cause__
    return cause.code if isinstance(cause, urllib.error.HTTPError) else None

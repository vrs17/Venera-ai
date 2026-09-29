"""Chat quvuri (pipeline) sxemalari.

`apps/web/src/types.ts` dagi `PipelineResponse` ning aynan nusxasi.

QUVUR NIMA UCHUN SHUNDAY BO'LINGAN. Frontend har bosqichni ALOHIDA
ko'rsatadi (`components/TraceStages.vue`) - ya'ni "nima uchun bunday javob
keldi" degan savolga javob beradi. Bu bank muhitida majburiy: xodim
javobga ishonmasa, qaysi hujjatdan olinganini va qaysi qoida bo'yicha
ruxsat berilganini ko'ra olishi kerak.

Shuning uchun yangi integratsiya (CRM, HRM) qo'shilganda ham SHU shakl
saqlanadi: `orchestrator.targetModule` qaysi tizimga borilgani, `access`
esa nima uchun ruxsat berilgani/berilmaganini aytadi.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BaseStage(BaseModel):
    """Har bir bosqichda umumiy maydonlar.

    `rawAnswer` - modelning tahlil qilinishidan OLDINGI chiqishi. Diagnostika
    uchun; RAG_ADMIN roli uni UI da ko'radi.
    """

    rawAnswer: str = ""
    model: str = ""
    adapter: str = ""
    seconds: float = 0.0


class GuardStage(BaseStage):
    """Xavfsizlik: so'rov umuman qayta ishlanishi mumkinmi."""

    safe: bool = True
    decision: str = ""
    reason: str = ""
    guardJson: Any = None


class IntentStage(BaseStage):
    """Foydalanuvchi nima demoqchi."""

    intent: str = ""
    confidence: str = ""
    intentJson: Any = None


class OrchestratorStage(BaseStage):
    """Qaysi tizimga yo'naltirish kerak.

    YANGI TIZIM (CRM, HRM, ...) QO'SHILADIGAN JOY AYNAN SHU:
    `targetModule` yangi qiymat oladi, qolgan hamma narsa o'zgarmaydi.
    """

    routeType: str = ""
    route: str = ""
    targetModule: str = ""
    requiresAccessCheck: bool = False
    reason: str = ""
    orchestratorJson: Any = None


class AccessStage(BaseStage):
    """Shu foydalanuvchining shu ma'lumotga huquqi bormi."""

    allowed: bool = True
    decision: str = ""
    reason: str = ""
    requiredRole: str = ""
    resourceScope: str = ""
    accessJson: Any = None


class RetrievalSource(BaseModel):
    documentId: str | None = None
    documentTitle: str | None = None
    documentType: str | None = None
    version: str | None = None
    page: int | None = None
    uri: str | None = None


class RetrievalChunk(BaseModel):
    chunkId: str
    text: str
    pointId: str | None = None
    documentId: str | None = None
    source: RetrievalSource | None = None
    metadata: dict[str, Any] | None = None
    vectorScore: float | None = None
    rerankScore: float | None = None
    rank: int | None = None


class RetrievalStage(BaseModel):
    """Topilgan manbalar. Frontend ularni javob ostida havola qilib ko'rsatadi."""

    status: str | None = None
    collection: str | None = None
    results: list[RetrievalChunk] = Field(default_factory=list)
    seconds: float | None = None
    error: str | None = None


class AskRequest(BaseModel):
    """types.ts: `askAi(question)` faqat shuni yuboradi.

    Foydalanuvchi KIMLIGI so'rov tanasida EMAS, `Authorization` sarlavhasidagi
    token'dan olinadi. Aks holda klient o'zini boshqa xodim deb tanishtira
    olardi.
    """

    question: str


class StreamRequest(BaseModel):
    """`POST /chat/stream` tanasi.

    KIMLIK BU YERDA YO'Q, va bu ataylab: `user_id` server tomonidan
    `Authorization` token'idan qo'yiladi. Klient uni o'zi yuborsa, boshqa
    xodimning suhbat tarixiga kirib olardi - yuqoridagi xizmatda xotira
    `(user_id, chat_id)` bo'yicha saqlanadi.
    """

    question: str
    #: Suhbat kaliti. Bir xil kalitli savollar bir-birini ESLAYDI. Klient
    #: o'zi yaratadi (brauzerdagi suhbat oynasi), va u `user_id` bilan
    #: birga ishlatilgani uchun boshqa odamning suhbatiga tushib qolmaydi.
    chatId: str | None = Field(default=None, max_length=64)
    #: Klient OVOZLI rejimdami. Faqat shunda `hold` (kutish) kadrlari
    #: yuboriladi.
    #:
    #: NEGA KLIENT AYTADI. Kutish gapi OVOZ uchun: jimlikni to'ldiradi.
    #: Matnli chatda esa kutish ko'rinib turadi (nuqtalar, "yozmoqda"),
    #: ya'ni "Bir soniya, tekshirayapman" degan qator faqat shovqin
    #: bo'lardi. Server klientning rejimini bilmaydi - shuning uchun
    #: buni klient aytadi, va default `false`: kadr QO'SHILGANI bilan
    #: eski klientlarning xatti-harakati o'zgarmaydi.
    voice: bool = False
    #: Savol QANDAY kiritilgan: `voice` - mikrofondan (STT), `text` - yozib.
    #: FAQAT savol izi uchun (admin panel: "ovozli" belgisi va ulushi).
    #: Berilmasa `voice` dan olinadi - web'da ovoz paneli ochiq bo'lsa savol
    #: gapirilgan, ya'ni ikkalasi bir narsa.
    #:
    #: NEGA ALOHIDA MAYDON. `voice` - "klient ovozli REJIMDA" (javob ovoz
    #: chiqarib o'qiladi, kutish gaplari shunga qarab yuboriladi), savol qanday
    #: kiritilgani emas. Mini App'da javobni o'qish default YOQIQ, ya'ni YOZIB
    #: berilgan savol ham `voice: true` bilan keladi - izda hamma Mini App
    #: savoli "ovozli" bo'lib ko'rinardi. Eski Mini App build'i bu maydonni
    #: yubormaydi - u uchun avvalgi xulq.
    input: Literal["text", "voice"] | None = None
    #: Interfeys tili - kutish gapi shu tilda bo'ladi.
    #: `uz-Cyrl` uchun gap lotin yozuvida keladi: u ESHITILADI, va TTS
    #: lotin yozuvida ishlaydi.
    locale: str = Field(default="uz", max_length=16)
    #: "Pro" rejimi - SHU savol uchun (2026-09-29 dagi API).
    #:
    #: `pro` bo'lsa yuqoridagi yordamchi tashqi (hosted) modeldan
    #: maslahat oladi - bu PULGA tushadi va odamning kunlik/haftalik/
    #: oylik byudjetidan yeydi. Shuning uchun u HAR XABAR uchun alohida
    #: va default `standard`: klient aytmasa hech narsa o'zgarmaydi va
    #: savol tarmoqdan tashqariga chiqmaydi.
    #:
    #: `Literal` bilan qotirilgan: notanish qiymat 422 beradi va
    #: yuqoridagi xizmatga bormaydi.
    mode: Literal["standard", "pro"] = "standard"

    # `hrmEmployee` ATAYLAB YO'Q.
    #
    # Yuqoridagi xizmat shu maydon bilan savoldagi "men" kim ekanini
    # almashtirishga ruxsat beradi. Maydon bu yerda turganda esa u
    # KLIENT QO'LIDA bo'lardi: har qanday tizimga kirgan foydalanuvchi
    # `{"question": "...", "hrmEmployee": "BOSHQA XODIM"}` yuborib,
    # o'sha odam haqidagi javobni olardi - token egasining ko'rish
    # huquqi doirasida. Frontend bu maydonni hech qachon yubormagan,
    # ya'ni bu faqat ochiq qolgan hujum yuzasi edi.
    #
    # Klient tanlagan kimlik SERVER tomonidan qo'yilishi kerak (yuqoridagi
    # `user_id` kabi). Kelajakda kerak bo'lsa - masalan rahbar o'z
    # bo'ysunuvchisi haqida so'rasa - u huquq tekshiruvi bilan birga
    # qaytariladi, so'rov tanasidan emas.


class FileLinkRequest(BaseModel):
    """Telegram uchun yuklab olish havolasi so'rovi.

    `filename` - klient taklif qilgan nom (javobdagi hujjat sarlavhasidan,
    veb ilovadagi kabi). Server uni TOZALAYDI va kengaytmani fayl turiga
    qarab O'ZI qo'yadi: klient `ariza.exe` so'rasa ham `ariza.docx` bo'ladi.
    """

    filename: str | None = Field(default=None, max_length=160)


class FileLink(BaseModel):
    """Tokensiz ochiladigan, qisqa muddatli havola - `WebApp.downloadFile` uchun."""

    #: Nisbiy yo'l; klient o'z originini qo'shadi (Telegram HTTPS manzil so'raydi).
    url: str
    #: Telegram oynasida ko'rinadigan va saqlanadigan nom.
    filename: str
    #: Havola necha soniya yashaydi.
    expiresIn: int


class PipelineResponse(BaseModel):
    """types.ts: PipelineResponse

    Bosqichlarning har biri `None` bo'lishi mumkin - quvur o'rtada to'xtasa
    (masalan `guard` xavfli deb topsa) keyingi bosqichlar bajarilmaydi va
    frontend ularni "o'tkazib yuborilgan" deb ko'rsatadi.
    """

    finalStatus: str
    domain: str | None = None
    domainReason: str | None = None
    guard: GuardStage | None = None
    intent: IntentStage | None = None
    orchestrator: OrchestratorStage | None = None
    access: AccessStage | None = None
    retrieval: RetrievalStage | None = None
    answer: str | None = None

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

from typing import Any

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

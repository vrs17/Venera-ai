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

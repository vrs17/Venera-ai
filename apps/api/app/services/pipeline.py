"""Chat quvuri: savol -> javob.

╔══════════════════════════════════════════════════════════════════════════╗
║ BU FAYL - LOYIHANING KENGAYADIGAN NUQTASI.                               ║
║ CRM, HRM va kelajakdagi tizimlar AYNAN shu yerga ulanadi.                ║
╚══════════════════════════════════════════════════════════════════════════╝

Quvur bosqichlari va ularning ma'nosi:

    guard        -> so'rov umuman qayta ishlanishi mumkinmi (xavfsizlik)
    intent       -> foydalanuvchi nima demoqchi
    orchestrator -> QAYSI TIZIMGA yo'naltirish kerak  <-- yangi tizim shu yerda
    access       -> shu xodimning shu ma'lumotga huquqi bormi
    retrieval    -> tizimdan ma'lumot olish
    answer       -> matnli javob

Nima uchun bosqichlar ALOHIDA qaytariladi: frontend ularni ko'rsatadi
(`components/TraceStages.vue`). Bank muhitida xodim javobga ishonmasa,
qaysi manbadan olinganini va qaysi qoida bo'yicha ruxsat berilganini
ko'ra olishi SHART.

HOZIRGI HOLAT: bu SKELET. Har bosqich to'g'ri shaklda javob qaytaradi,
lekin haqiqiy mantiq yo'q - `answer` da nima qilish kerakligi yozilgan.
Shu tufayli frontend TO'LIQ ishlaydi va integratsiyalar birma-bir
qo'shiladi, hammasini birdan yozish shart emas.

YANGI TIZIM QO'SHISH (masalan CRM):
    1. `app/services/integrations/crm.py` yarat - o'sha tizimning klienti
    2. `_ROUTES` ga bitta qator qo'sh: qaysi intent -> qaysi modul
    3. `_dispatch()` ga shox qo'sh
    Boshqa HECH QAYERGA tegilmaydi: schemas ham, router ham, frontend ham.
"""

from __future__ import annotations

import logging
import time

from ..schemas.auth import AuthUser
from ..schemas.chat import (
    AccessStage,
    GuardStage,
    IntentStage,
    OrchestratorStage,
    PipelineResponse,
    RetrievalStage,
)

log = logging.getLogger(__name__)

#: Intent -> qaysi tizim javob beradi.
#: YANGI TIZIM SHU YERGA QO'SHILADI. Hozir hammasi `PENDING` - ya'ni
#: yo'naltirish qarori qabul qilinadi, lekin bajaruvchi hali yo'q.
_ROUTES: dict[str, str] = {
    # "hr_vacation":  "HRM",
    # "crm_customer": "CRM",
}

#: Hali hech qanday tizim ulanmaganini bildiruvchi holat. Frontend uni
#: `finalStatus` sifatida oladi va noma'lum qiymatlar uchun zaxira
#: ko'rsatkichni chizadi (types.ts: FinalStatus `(string & {})`).
_NOT_READY = "RAG_DOMAIN_NOT_READY"


class Pipeline:
    """Savolni bosqichma-bosqich qayta ishlaydi.

    Holatsiz (stateless): har chaqiruv mustaqil. Shu sababli uni bitta
    nusxada saqlash ham, har so'rovda yaratish ham xavfsiz.
    """

    async def ask(self, question: str, user: AuthUser) -> PipelineResponse:
        started = time.monotonic()
        question = (question or "").strip()

        guard = self._guard(question)
        if not guard.safe:
            return PipelineResponse(
                finalStatus="STOP_UNSAFE",
                domain=None,
                domainReason=guard.reason,
                guard=guard,
                answer=None,
            )

        intent = self._intent(question)
        orchestrator = self._orchestrate(intent)
        access = self._access(orchestrator, user)

        if not access.allowed:
            return PipelineResponse(
                finalStatus="STOP_ACCESS_DENIED",
                domain=orchestrator.targetModule or None,
                domainReason=access.reason,
                guard=guard,
                intent=intent,
                orchestrator=orchestrator,
                access=access,
                answer=None,
            )

        retrieval, answer, final = await self._dispatch(question, orchestrator, user)

        log.info(
            "Quvur: %r -> %s (%.0f ms)",
            question[:60], final, (time.monotonic() - started) * 1000,
        )
        return PipelineResponse(
            finalStatus=final,
            domain=orchestrator.targetModule or None,
            domainReason=orchestrator.reason or None,
            guard=guard,
            intent=intent,
            orchestrator=orchestrator,
            access=access,
            retrieval=retrieval,
            answer=answer,
        )

    # --- bosqichlar ----------------------------------------------------------

    def _guard(self, question: str) -> GuardStage:
        """Xavfsizlik. Hozir faqat bo'sh so'rovni to'sadi.

        KEYIN: prompt injection, maxfiy ma'lumot so'rovi, siyosat buzilishi.
        """
        if not question:
            return GuardStage(
                safe=False,
                decision="BLOCK",
                reason="So'rov bo'sh",
                adapter="skelet",
            )
        return GuardStage(safe=True, decision="ALLOW", reason="", adapter="skelet")

    def _intent(self, question: str) -> IntentStage:
        """Foydalanuvchi nima demoqchi.

        KEYIN: LLM yoki klassifikator. Hozir intent aniqlanmaydi - shuning
        uchun `confidence` bo'sh va `intent` "unknown".
        """
        return IntentStage(
            intent="unknown",
            confidence="",
            adapter="skelet",
            rawAnswer="",
        )

    def _orchestrate(self, intent: IntentStage) -> OrchestratorStage:
        """Qaysi tizim javob beradi. YANGI TIZIM `_ROUTES` ga qo'shiladi."""
        target = _ROUTES.get(intent.intent, "")
        return OrchestratorStage(
            routeType="DIRECT" if target else "NONE",
            route=target,
            targetModule=target,
            requiresAccessCheck=bool(target),
            reason=(
                f"{target} moduliga yo'naltirildi" if target
                else "Hali hech qanday tizim ulanmagan"
            ),
            adapter="skelet",
        )

    def _access(self, orchestrator: OrchestratorStage, user: AuthUser) -> AccessStage:
        """Huquq tekshiruvi.

        Yo'naltirish bo'lmasa tekshiruv ham kerak emas - `allowed=True`
        qaytariladi va quvur `_dispatch` ga o'tadi (u "hali ulanmagan"
        javobini beradi).

        KEYIN: har modul o'z `requiredRole` ini e'lon qiladi va bu yerda
        `user.roles` bilan solishtiriladi.
        """
        if not orchestrator.requiresAccessCheck:
            return AccessStage(
                allowed=True, decision="SKIP",
                reason="Yo'naltirish yo'q - tekshiruv kerak emas",
                adapter="skelet",
            )
        return AccessStage(
            allowed=True, decision="ALLOW",
            reason=f"{user.email} uchun ruxsat berildi",
            resourceScope=orchestrator.targetModule,
            adapter="skelet",
        )

    async def _dispatch(
        self, question: str, orchestrator: OrchestratorStage, user: AuthUser,
    ) -> tuple[RetrievalStage | None, str | None, str]:
        """Tanlangan tizimdan javob oladi.

        YANGI TIZIM QO'SHILGANDA SHU YERGA SHOX QO'SHILADI:

            if orchestrator.targetModule == "CRM":
                return await crm.answer(question, user)
        """
        if not orchestrator.targetModule:
            return (
                None,
                "Venera hozircha sozlanmoqda: savolga javob beradigan tizim hali "
                "ulanmagan. Ulanish tugagach shu savolingiz ishlaydi.",
                _NOT_READY,
            )

        # Bu yerga faqat `_ROUTES` da modul bor bo'lsa kelinadi, ya'ni
        # kod qo'shilmasdan yo'nalish qo'shib qo'yilgan holat.
        log.warning("Modul %r yo'naltirilgan, lekin bajaruvchisi yo'q",
                    orchestrator.targetModule)
        return (
            None,
            f"{orchestrator.targetModule} moduli hali bajarilmagan.",
            _NOT_READY,
        )


#: Ilova bo'ylab bitta nusxa. Holatsiz bo'lgani uchun bu xavfsiz.
pipeline = Pipeline()

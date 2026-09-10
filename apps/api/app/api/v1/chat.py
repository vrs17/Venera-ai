"""Chat endpointi.

Ikki yo'l bor va ular BIR-BIRINI ALMASHTIRMAYDI:

    POST /chat/stream   HR Assistant javobini OQIM bilan (asosiy yo'l)
    POST /chat/ask      quvur skeleti, bitta JSON (`services/pipeline.py`)

`/stream` - haqiqiy javob: yuqoridagi HR Assistant xizmatiga boradi, u
hujjatlar bo'yicha RAG va HRM ma'lumotini birlashtiradi. `/ask` esa
quvurning bosqichli ko'rinishini beradi va Assistant sozlanmagan muhitda
(masalan lokal ishlab chiqishda) frontend to'liq ishlashi uchun qoladi.

Mantiq bu faylda YO'Q: `services/integrations/assistant.py` da.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Path
from fastapi.responses import StreamingResponse

from ...core.config import settings
from ...core.errors import error_status
from ...schemas.auth import AuthUser
from ...schemas.chat import AskRequest, PipelineResponse, StreamRequest
from ...services.integrations.assistant import (
    ARTIFACT_KINDS,
    AssistantClient,
    AssistantError,
)
from ...services.pipeline import pipeline
from ..deps import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_assistant = AssistantClient(
    settings.assistant_base_url,
    settings.assistant_client_id,
    settings.assistant_client_secret,
    timeout=settings.assistant_timeout,
    max_concurrent=settings.assistant_max_concurrent,
)

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


def _fail(exc: AssistantError, user: AuthUser, what: str):
    """Xatoni log'ga yozadi va foydalanuvchiga xabarga o'giradi."""
    log.warning("Assistant %s (%s): %s", what, user.email, exc)
    status = exc.status if exc.status in _MESSAGES else 502
    return error_status(status, _MESSAGES[status])


@router.post(
    "/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/x-ndjson": {}},
                     "description": "Kadrlar oqimi: stage, sources, artifact, token, done"}},
)
def stream(body: StreamRequest, user: AuthUser = Depends(current_user)) -> StreamingResponse:
    """Savol -> javob oqimi (NDJSON, har qatorda bitta JSON kadri).

    `async def` EMAS, ataylab: klient bloklaydigan `urllib` ishlatadi.
    Oddiy `def` bilan FastAPI uni threadpool'da bajaradi va event loop
    bo'sh qoladi - aks holda bitta uzun javob butun serverni to'xtatib
    qo'yardi.
    """
    try:
        # Oqim SHU YERDA ochiladi, generator ichida emas: 400/501/503
        # shunda ODDIY HTTP javobi bo'lib chiqadi. Generator ichida
        # ochilsa, 200 allaqachon ketgan bo'lardi va xato brauzerga
        # "uzilgan oqim" bo'lib ko'rinardi.
        answer = _assistant.stream(
            body.question,
            # KIMLIK TOKEN'DAN. Prefiks bilan: yuqoridagi xizmat bir
            # nechta ilovaga xizmat qiladi va `user_id` lar aralashib
            # ketmasligi kerak - suhbat xotirasi shu kalit bo'yicha.
            user_id=f"venera:{user.actorId}",
            chat_id=body.chatId,
            # HRM TOKENI HOZIRCHA YO'Q. Venera kimligi (users.yaml) HRM
            # kimligidan alohida, ya'ni foydalanuvchining HRM sessiyasi
            # bizda yo'q. Usiz "jonli" HRM savoliga xizmat `auth_missing`
            # kodli xato kadri qaytaradi va frontend buni tushunarli
            # xabarga o'giradi - hujjatlar bo'yicha savollar esa ISHLAYDI.
            # HRM hisobini ulash qo'shilganda faqat shu qator o'zgaradi.
            hrm_token=None,
            hrm_employee=body.hrmEmployee,
            max_chars=settings.assistant_max_question_chars,
        )
    except AssistantError as exc:
        raise _fail(exc, user, "savol") from exc

    def frames():
        try:
            yield from answer.frames
        except AssistantError as exc:
            # Oqim o'rtasida uzildi. Statusni endi o'zgartirib bo'lmaydi
            # (200 ketib bo'lgan), shuning uchun brauzerga XATO KADRI
            # yuboriladi: u shu shaklni allaqachon tushunadi, ya'ni
            # "javob yarim qoldi" holati uchun alohida yo'l kerak emas.
            log.warning("Assistant oqimi (%s): %s", user.email, exc)
            status = exc.status if exc.status in _MESSAGES else 502
            yield (b'{"type":"error","code":"stream_broken","text":'
                   + _json_text(_MESSAGES[status]) + b'}\n')
            yield b'{"type":"done","route":null}\n'
        finally:
            log.info("Assistant javobi (%s): request_id=%s natija=%s",
                     user.email, answer.request_id, answer.outcome or "-")

    return StreamingResponse(
        frames(),
        media_type="application/x-ndjson",
        headers={
            # Javob shu odamga xos - proksi yoki brauzer keshiga tushmasin.
            "Cache-Control": "no-store",
            # Audit kaliti: aynan shu qiymat yuqoridagi xizmat jurnalida
            # ham turadi, ya'ni "shu javob nega bunday" degan savolni
            # ikki tizimda BITTA kalit bilan izlash mumkin.
            "X-Venera-Request-Id": answer.request_id,
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


def _file(open_it, user: AuthUser, what: str) -> StreamingResponse:
    """Fayl oqimi uchun umumiy qobiq - ikki endpoint uchun bir xil."""
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
            log.warning("Assistant fayl oqimi (%s): %s", user.email, exc)

    return StreamingResponse(
        body(),
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            # `inline` EMAS, `attachment`: fayl yuqoridagi xizmatdan
            # keladi va uni Venera originida sahifa sifatida ochish
            # ortiqcha xavf bo'lardi. Nomi `_filename` da tozalangan.
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _json_text(text: str) -> bytes:
    """Matnni JSON satriga o'giradi - qo'lda yasalgan kadr uchun."""
    return json.dumps(text, ensure_ascii=False).encode("utf-8")


@router.post("/ask", response_model=PipelineResponse)
async def ask(
    data: AskRequest,
    user: AuthUser = Depends(current_user),
) -> PipelineResponse:
    """Savol -> quvur -> javob (bosqichli, bitta JSON).

    Foydalanuvchi TOKEN'dan olinadi, so'rov tanasidan emas: `access`
    bosqichi shu shaxs bo'yicha huquq tekshiradi.
    """
    return await pipeline.ask(data.question, user)

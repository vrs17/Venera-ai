"""Chat endpointi.

Frontend `askAi(question)` faqat shu bittasini chaqiradi va javobning
HAR BOSQICHINI ko'rsatadi. Mantiq `services/pipeline.py` da - bu fayl
faqat HTTP qatlami.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...schemas.auth import AuthUser
from ...schemas.chat import AskRequest, PipelineResponse
from ...services.pipeline import pipeline
from ..deps import current_user

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/ask", response_model=PipelineResponse)
async def ask(
    data: AskRequest,
    user: AuthUser = Depends(current_user),
) -> PipelineResponse:
    """Savol -> quvur -> javob.

    Foydalanuvchi TOKEN'dan olinadi, so'rov tanasidan emas: `access`
    bosqichi shu shaxs bo'yicha huquq tekshiradi.
    """
    return await pipeline.ask(data.question, user)

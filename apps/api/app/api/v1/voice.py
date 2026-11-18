"""Ovoz namunasi - `/api/v1/voice-sample` (spikerni ovozidan tanish, `services/meetings/voice.py`).

Mobil ilova shu yerga yozadi; Telegram va Slack xizmatni to'g'ridan-to'g'ri chaqiradi (HTTP siz).
Router'da MANTIQ YO'Q. Bo'lim eshigi - yig'ilishlarniki (`meetings_access`): Plaud o'chiq bo'lsa 404.

`POST` - tana XOM audio (`Content-Type: audio/aac | audio/mp4 | audio/ogg | ...`), `PUT /audio` kabi:
`Content-Length` tanani o'qishdan OLDIN tekshiriladi, ko'pi bilan `VOICE_SAMPLE_MAX_BYTES` o'qiladi.
Javob darhol (`202`, `processing`); natija - `GET /{sampleId}` (tekshiruv 5-60 s).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from starlette.concurrency import run_in_threadpool

from ...core.channels import channel_of
from ...core.config import settings
from ..deps import require_roles
from ...schemas import meetings as schemas
from ...schemas.auth import AuthUser
from ...services.meetings import voice
from ...services.meetings.errors import MeetingProblem
from .meetings import meetings_access

router = APIRouter(prefix="/voice-sample", tags=["voice"])


@router.get("", response_model=schemas.VoiceStatus)
def get_status(user: AuthUser = Depends(meetings_access)) -> dict:
    return voice.status(user)


@router.post("", response_model=schemas.VoiceSampleView, status_code=status.HTTP_202_ACCEPTED)
async def post_sample(request: Request, user: AuthUser = Depends(meetings_access)) -> dict:
    limit = int(settings.voice_sample_max_bytes)
    try:
        declared = int(request.headers.get("content-length") or -1)
    except ValueError:
        declared = -1
    if declared > limit:
        raise MeetingProblem(413, "sample_too_large", "Namuna juda katta - 1 daqiqagacha yozing")
    body = bytearray()
    async for piece in request.stream():
        body += piece
        if len(body) > limit:
            raise MeetingProblem(413, "sample_too_large", "Namuna juda katta - 1 daqiqagacha yozing")
    return await run_in_threadpool(voice.submit, user, bytes(body), request.headers.get("content-type"),
                                   channel_of(request))


@router.delete("", response_model=schemas.VoiceDeleted)
def delete_voice(user: AuthUser = Depends(meetings_access)) -> dict:
    return voice.delete(user)


@router.get("/coverage", response_model=schemas.VoiceCoverage)
def get_coverage(user: AuthUser = Depends(meetings_access), _admin: AuthUser = Depends(require_roles("ADMIN"))) -> dict:
    return voice.coverage()


@router.get("/{sample_id}", response_model=schemas.VoiceSampleView)
def get_sample(sample_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return voice.sample(user, sample_id)

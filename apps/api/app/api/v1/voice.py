"""Ovoz namunasi - `/api/v1/voice-sample` (spikerni ovozidan tanish, `services/meetings/voice.py`).

Mobil ilova shu yerga yozadi; Telegram va Slack xizmatni to'g'ridan-to'g'ri chaqiradi (HTTP siz).
Router'da MANTIQ YO'Q. Bo'lim eshigi - yig'ilishlarniki (`meetings_access`): Plaud o'chiq bo'lsa 404.

`POST` - MULTIPART (`file` maydoni, mobil ilova - chat diktovkasi kabi `postForm`) yoki XOM audio
(`Content-Type: audio/aac | audio/mp4 | audio/ogg | ...`). NEGA MULTIPART: `llm.brb-tech.uz` oldidagi nginx
(administratorniki, 10.10.50.10) xom tanali POST ni (audio/*, octet-stream) 403 bilan to'xtatadi - so'rov
serverga yetmaydi (1.3.17 dagi "Request failed (403)", 2026-11-18). Multipart va JSON o'tadi.
`Content-Length` tanani o'qishdan OLDIN tekshiriladi, fayldan ko'pi bilan `VOICE_SAMPLE_MAX_BYTES` o'qiladi.
Javob darhol (`202`, `processing`); natija - `GET /{sampleId}` (tekshiruv 5-60 s).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse
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


#: Multipart konvert (chegara, sarlavhalar) uchun tananing fayldan ortiq qismi.
_FORM_OVERHEAD = 64 * 1024
_TOO_LARGE = "Namuna juda katta - 1 daqiqagacha yozing"


@router.post("", response_model=schemas.VoiceSampleView, status_code=status.HTTP_202_ACCEPTED)
async def post_sample(request: Request, user: AuthUser = Depends(meetings_access)) -> dict:
    limit = int(settings.voice_sample_max_bytes)
    content_type = request.headers.get("content-type") or ""
    multipart = content_type.lower().startswith("multipart/form-data")
    try:
        declared = int(request.headers.get("content-length") or -1)
    except ValueError:
        declared = -1
    if declared > limit + (_FORM_OVERHEAD if multipart else 0):
        raise MeetingProblem(413, "sample_too_large", _TOO_LARGE)
    if multipart:
        form = await request.form(max_files=1, max_fields=4)
        try:
            part = form.get("file")
            if part is None or isinstance(part, str):
                raise MeetingProblem(400, "empty_audio", "Audio fayli yuborilmadi")
            data = await part.read(limit + 1)
            kind = part.content_type or ""
        finally:
            await form.close()
    else:
        body = bytearray()
        async for piece in request.stream():
            body += piece
            if len(body) > limit:
                raise MeetingProblem(413, "sample_too_large", _TOO_LARGE)
        data, kind = bytes(body), content_type
    if len(data) > limit:
        raise MeetingProblem(413, "sample_too_large", _TOO_LARGE)
    return await run_in_threadpool(voice.submit, user, data, kind, channel_of(request))


@router.delete("", response_model=schemas.VoiceDeleted)
def delete_voice(user: AuthUser = Depends(meetings_access)) -> dict:
    return voice.delete(user)


@router.get("/coverage", response_model=schemas.VoiceCoverage)
def get_coverage(user: AuthUser = Depends(meetings_access), _admin: AuthUser = Depends(require_roles("ADMIN"))) -> dict:
    return voice.coverage()


@router.get("/{sample_id}/audio")
def get_sample_audio(sample_id: str, user: AuthUser = Depends(meetings_access)) -> FileResponse:
    """Xodimning O'Z namunasi - eshitish uchun (mobil pleer `{uri, headers}` bilan oqimda o'ynatadi; Range ishlaydi).
    Mobil ilova yozgan ADTS - m4a ko'rinishida (`voice.playable`)."""
    path, kind, name = voice.sample_audio(user, sample_id)
    return FileResponse(path, media_type=kind, filename=name, content_disposition_type="inline")


@router.get("/{sample_id}", response_model=schemas.VoiceSampleView)
def get_sample(sample_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return voice.sample(user, sample_id)

"""Yig'ilishlar bo'limi - `/api/v1/meetings` (spetsifikatsiya 3.2, 1-28; bayonnoma 32-35; chat - `/{id}/chat`).

Router'da MANTIQ YO'Q: har endpoint `services/meetings/service.py` ga (bayonnoma -
`services/meetings/minutes/` ga) uzatadi.

KIRISH ESHIGI (`meetings_access`):
  * `MEETINGS_ENABLED` o'chiq - 404 (bo'lim umuman ko'rinmaydi). `.env` dan
    JONLI o'qiladi - yoqish/o'chirish restartsiz;
  * odam ADMIN ham, `MEETINGS_LOGINS` da ham bo'lmasa - 403.

STATIK YO'LLAR (`/config`, `/action-items`) `/{id}` DAN OLDIN e'lon qilinadi -
aks holda FastAPI "config" ni yig'ilish id si deb oladi.

`PUT /audio` - YAGONA `async def`: tanani o'qishdan OLDIN `Content-Length`
tekshiriladi (katta tana threadpool ishchisini band qilmasin), ko'pi bilan
`maxChunkBytes` o'qiladi, diskka yozish esa threadpool'da (`fsync`).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ...core import config as _config
from ...core.channels import channel_of
from ...core.config import settings
from ...schemas.auth import AuthUser
from ...schemas import meetings as schemas
from ...services.meetings import minutes, service
from ...services.meetings.errors import MeetingProblem
from ..deps import current_user, get_identity_store

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _login_of(user: AuthUser) -> str:
    """SSO hisobi - logini, `users.yaml` hisobi - emaili (`admin_logins` qoidasi)."""
    identity = get_identity_store().by_actor_id(user.actorId)
    return (identity.username if identity is not None else user.email or "").strip().lower()


def meetings_allowed(user: AuthUser, login: str | None = None) -> bool:
    """Sinov guruhidami: ADMIN yoki `MEETINGS_LOGINS` da. Qurilma sessiyasi ham
    shu qoidadan o'tadi (`devices.py`) - ro'yxatdan chiqarilgan odamning telefoni
    30 kun to'liq Venera sessiyasini yangilab yurmasin."""
    if "ADMIN" in (user.roles or []):
        return True
    who = (login if login is not None else _login_of(user)).strip().lower()
    return who in _config.meetings_logins_now()


def meetings_access(user: AuthUser = Depends(current_user)) -> AuthUser:
    """Bo'lim eshigi. Bayroq o'chiq - 404 (yo'q bo'lim bilan bir xil), ruxsat yo'q - 403."""
    if not _config.meetings_enabled_now():
        raise MeetingProblem(404, "not_found", "Not Found")
    if meetings_allowed(user):
        return user
    raise MeetingProblem(403, "forbidden", "Bu bo'lim uchun ruxsat yo'q")


# --- statik yo'llar ------------------------------------------------------------------


@router.get("/config", response_model=schemas.MeetingsConfig)
def get_config(request: Request, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.config(user, service.accept_language(request.headers.get("Accept-Language")))


@router.get("/action-items", response_model=schemas.MyActionItemList)
def my_action_items(status_: str = Query("open", alias="status", pattern="^(open|done|all)$"),
                    limit: int = Query(100, ge=1, le=500),
                    user: AuthUser = Depends(meetings_access)) -> dict:
    return service.my_action_items(user, status_, limit)


@router.post("", response_model=schemas.Meeting, status_code=status.HTTP_201_CREATED)
def create_meeting(body: schemas.CreateMeetingRequest, request: Request, response: Response,
                   user: AuthUser = Depends(meetings_access)) -> dict:
    view, created = service.create(user, body, channel_of(request))
    if not created:
        response.status_code = status.HTTP_200_OK
    return view


@router.get("", response_model=schemas.MeetingList)
def list_meetings(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                  q: str = Query("", max_length=200), status_: str = Query("", alias="status", max_length=20),
                  origin: schemas.MeetingOrigin | None = Query(None),
                  sort: Literal["recorded", "listed"] = Query("recorded"),
                  user: AuthUser = Depends(meetings_access)) -> dict:
    """`origin` - Plaud filtri (manba); `sort=listed` - tayyor fayl kelgan kuniga (mobil 1.3.8+),
    default `recorded` - yozilgan vaqti (eski ilovalar kunlarga shunga guruhlaydi)."""
    return service.list_meetings(user, limit=limit, offset=offset, q=q, status=status_, origin=origin or "",
                                 sort=sort)


# --- yuklash ---------------------------------------------------------------------------


@router.get("/{meeting_id}/upload", response_model=schemas.UploadState)
def upload_state(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.upload_state(user, meeting_id)


@router.put("/{meeting_id}/audio", response_model=schemas.UploadReceived)
async def put_audio(meeting_id: str, request: Request, offset: int = Query(..., ge=0),
                    user: AuthUser = Depends(meetings_access)) -> dict:
    limit = int(settings.meetings_chunk_bytes)
    try:
        declared = int(request.headers.get("content-length") or -1)
    except ValueError:
        declared = -1
    if declared > limit:
        raise MeetingProblem(413, "chunk_too_large", "Bo'lak juda katta")
    body = bytearray()
    async for piece in request.stream():
        body += piece
        if len(body) > limit:
            raise MeetingProblem(413, "chunk_too_large", "Bo'lak juda katta")
    return await run_in_threadpool(service.append_chunk, user, meeting_id, offset, bytes(body),
                                   request.headers.get("X-Chunk-Sha256"))


@router.post("/{meeting_id}/complete", response_model=schemas.Meeting,
             status_code=status.HTTP_202_ACCEPTED)
def complete_upload(meeting_id: str, body: schemas.CompleteRequest, response: Response,
                    user: AuthUser = Depends(meetings_access)) -> dict:
    view, code = service.complete(user, meeting_id, body)
    response.status_code = code
    return view


# --- yig'ilish ----------------------------------------------------------------------------


@router.get("/{meeting_id}", response_model=schemas.Meeting)
def get_meeting(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.detail(user, meeting_id)


@router.patch("/{meeting_id}", response_model=schemas.Meeting)
def patch_meeting(meeting_id: str, body: schemas.PatchMeetingRequest,
                  user: AuthUser = Depends(meetings_access)) -> dict:
    return service.patch(user, meeting_id, body)


@router.delete("/{meeting_id}", response_model=schemas.Deleted)
def delete_meeting(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.delete(user, meeting_id)


@router.post("/{meeting_id}/retry", response_model=schemas.Meeting, status_code=status.HTTP_202_ACCEPTED)
def retry_meeting(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.retry(user, meeting_id)


@router.post("/{meeting_id}/retranscribe", response_model=schemas.Meeting,
             status_code=status.HTTP_202_ACCEPTED)
def retranscribe(meeting_id: str, body: schemas.RetranscribeRequest,
                 user: AuthUser = Depends(meetings_access)) -> dict:
    return service.retranscribe(user, meeting_id, body)


# --- transkript va spikerlar -----------------------------------------------------------------


@router.get("/{meeting_id}/transcript", response_model=schemas.Transcript)
def get_transcript(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.transcript(user, meeting_id)


@router.get("/{meeting_id}/transcript/export")
def export_transcript(meeting_id: str, format: str = Query("txt", pattern="^(txt|srt)$"),
                      speakers: int = Query(1, ge=0, le=1), timestamps: int = Query(1, ge=0, le=1),
                      user: AuthUser = Depends(meetings_access)) -> Response:
    text, media, name = service.export_transcript(user, meeting_id, format, with_speakers=bool(speakers),
                                                  with_timestamps=bool(timestamps))
    return Response(content=text, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.patch("/{meeting_id}/speakers/{speaker_id}", response_model=schemas.SpeakersOut)
def rename_speaker(meeting_id: str, speaker_id: str, body: schemas.SpeakerRenameRequest,
                   user: AuthUser = Depends(meetings_access)) -> dict:
    return service.rename_speaker(user, meeting_id, speaker_id, body.name)


@router.post("/{meeting_id}/speakers/merge", response_model=schemas.SpeakersMerged)
def merge_speakers(meeting_id: str, body: schemas.SpeakerMergeRequest,
                   user: AuthUser = Depends(meetings_access)) -> dict:
    return service.merge_speakers(user, meeting_id, body.from_, body.into)


@router.patch("/{meeting_id}/segments/{segment_id}", response_model=schemas.SegmentOut)
def edit_segment(meeting_id: str, segment_id: int, body: schemas.SegmentPatchRequest,
                 user: AuthUser = Depends(meetings_access)) -> dict:
    return service.edit_segment(user, meeting_id, segment_id, body)


# --- xulosalar --------------------------------------------------------------------------------


@router.get("/{meeting_id}/summaries", response_model=schemas.SummaryList)
def list_summaries(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.summaries(user, meeting_id)


@router.post("/{meeting_id}/summaries", response_model=schemas.SummaryCard,
             status_code=status.HTTP_202_ACCEPTED)
def create_summary(meeting_id: str, body: schemas.SummaryRequest, response: Response,
                   user: AuthUser = Depends(meetings_access)) -> dict:
    card, code = service.create_summary(user, meeting_id, body)
    response.status_code = code
    return card


@router.get("/{meeting_id}/summaries/{summary_id}", response_model=schemas.Summary)
def get_summary(meeting_id: str, summary_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.get_summary(user, meeting_id, summary_id)


@router.delete("/{meeting_id}/summaries/{summary_id}", response_model=schemas.Deleted)
def delete_summary(meeting_id: str, summary_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.delete_summary(user, meeting_id, summary_id)


@router.get("/{meeting_id}/summaries/{summary_id}/export")
def export_summary(meeting_id: str, summary_id: str, format: str = Query("md", pattern="^(md|txt)$"),
                   user: AuthUser = Depends(meetings_access)) -> Response:
    text, media, name = service.export_summary(user, meeting_id, summary_id, format)
    return Response(content=text, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- vazifalar ---------------------------------------------------------------------------------


@router.get("/{meeting_id}/action-items", response_model=schemas.ActionItemList)
def list_action_items(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.action_items(user, meeting_id)


@router.post("/{meeting_id}/action-items", response_model=schemas.ActionItem,
             status_code=status.HTTP_201_CREATED)
def add_action_item(meeting_id: str, body: schemas.ActionItemCreate,
                    user: AuthUser = Depends(meetings_access)) -> dict:
    return service.add_action_item(user, meeting_id, body)


@router.patch("/{meeting_id}/action-items/{item_id}", response_model=schemas.ActionItem)
def patch_action_item(meeting_id: str, item_id: str, body: schemas.ActionItemPatch,
                      user: AuthUser = Depends(meetings_access)) -> dict:
    return service.patch_action_item(user, meeting_id, item_id, body)


@router.post("/{meeting_id}/action-items/{item_id}/crm", response_model=schemas.CrmResult)
def action_item_to_crm(meeting_id: str, item_id: str, body: schemas.CrmRequest | None = None,
                       user: AuthUser = Depends(meetings_access)) -> dict:
    """Vazifa -> v3 -> CRM TAKLIFI. Hech narsa o'zgarmaydi: tasdiqlash chatdagi AYNI
    yo'l bilan - `POST /api/v1/actions/{token}/confirm`. `async` EMAS: agentni kutish
    (o'nlab soniya) threadpool'da."""
    return service.action_item_to_crm(user, meeting_id, item_id, body)


# --- yig'ilish chati (bitta audio - bitta suhbat), savol-javob va audio ----------------------------------


@router.get("/{meeting_id}/chat", response_model=schemas.ChatHistory)
def chat_history(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    """Faol suhbat navbatlari (eskisi birinchi) va javob beradigan model nomi."""
    return service.chat_history(user, meeting_id)


@router.post("/{meeting_id}/chat", response_model=schemas.ChatTurn)
def chat_send(meeting_id: str, body: schemas.ChatRequest, user: AuthUser = Depends(meetings_access)) -> dict:
    """Xabar -> Barno javobi (transkript, xulosa va shu suhbat xotirasi bilan). `async` EMAS: modelni kutish
    (o'nlab soniya) threadpool'da. `clientId` - idempotentlik: o'sha kalit bilan qayta yuborish takror navbat
    yaratmaydi. Xatolar `/ask` dagidek: 404, 409 `not_ready`, 429, 503 `llm_unavailable` (429 / 503 - faqat model
    javob beradigan navbatda).

    Bayonnoma ham shu chatda: ko'rsatma, "tayyorla", tayyor hujjatdagi o'zgartirish (`turn.kind`, `turn.minutes`).
    `intent` - aniq kirish nuqtasi (modelsiz), `minutesLanguage` - odam qarab turgan hujjat tili. Navbat saqlansa -
    doim 200: bayonnoma ishi boshlanmasa sababi `turn.minutes.error` da; hujjat tayyor bo'lishini ilova
    `GET .../minutes/{turn.minutes.id}` bilan kutadi."""
    return service.chat_send(user, meeting_id, body.message, body.language, channel=body.channel or "api",
                             client_id=body.clientId, intent=body.intent, minutes_lang=body.minutesLanguage)


@router.delete("/{meeting_id}/chat", response_model=schemas.ChatReset)
def chat_reset(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    """Yangi suhbat: faol navbatlar arxivga (yumshoq - bazada qoladi, modelga va ro'yxatga bormaydi)."""
    return service.chat_reset(user, meeting_id)


@router.post("/{meeting_id}/ask", response_model=schemas.AskAnswer)
def ask(meeting_id: str, body: schemas.AskRequest, request: Request,
        user: AuthUser = Depends(meetings_access)) -> dict:
    """Eski ilovalar va web: endi chat navbati (suhbat xotirasi bilan), javob shakli o'zgarmagan."""
    return service.ask(user, meeting_id, body.question, body.language, channel=channel_of(request))


@router.get("/{meeting_id}/questions", response_model=schemas.QuestionList)
def questions(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return service.questions(user, meeting_id)


@router.get("/{meeting_id}/audio")
def get_audio(meeting_id: str, download: int = Query(0, ge=0, le=1),
              user: AuthUser = Depends(meetings_access)) -> FileResponse:
    """Tinglash: m4a (Range bilan - pleyer istalgan joyga sakraydi). `?download=1` - ulashish
    uchun o'sha fayl `attachment` va yig'ilish nomi bilan (alohida `/audio/file` kerak emas)."""
    path, media, headers = service.audio_file(user, meeting_id, download=bool(download))
    return FileResponse(path, media_type=media, headers=headers or None)


# --- to'liq hujjat eksporti -----------------------------------------------------------------------


@router.get("/{meeting_id}/export", responses={200: {"content": {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}, "application/pdf": {},
    "text/markdown": {}, "text/plain": {}}}})
def export_meeting(meeting_id: str, request: Request,
                   format: str = Query("pdf", pattern="^(docx|pdf|md|txt)$"),
                   summary_id: str | None = Query(None, alias="summaryId", max_length=64),
                   parts: str | None = Query(None, max_length=100),
                   user: AuthUser = Depends(meetings_access)) -> Response:
    """Plaud'dagidek bitta fayl: "Qisqa xulosa", xulosa, vazifalar jadvali, aqliy xarita, transkript.
    `parts=brief,summary,actions,mindmap,transcript` (bo'sh - tayyor bo'lgan hammasi; `brief` yolg'iz -
    faqat ulashiladigan qisqa xulosa), bo'lim
    sarlavhalari `Accept-Language` tilida. `async` EMAS: PDF chizish CPU ishi - threadpool'da
    (shuning uchun bir odam - bir vaqtda bitta eksport: ikkinchisi 429 `export_busy`)."""
    data, media, disposition = service.export_meeting(
        user, meeting_id, format, summary_id=summary_id, parts=parts,
        lang=service.accept_language(request.headers.get("Accept-Language")))
    # Shaxsiy hujjat: oraliq kesh (proksi, brauzer) saqlab qolmasin.
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store"})


# --- bayonnoma (rasmiy hujjat, `services/meetings/minutes/`) ------------------------------------


@router.get("/{meeting_id}/minutes", response_model=schemas.MinutesList)
def list_minutes(meeting_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return minutes.listing(user, meeting_id)


@router.post("/{meeting_id}/minutes", response_model=schemas.MinutesView, status_code=status.HTTP_202_ACCEPTED,
             responses={200: {"model": schemas.MinutesView,
                              "description": "Tayyori bor yoki xuddi shu hujjat hozir yozilmoqda"}})
def create_minutes(meeting_id: str, response: Response, body: schemas.MinutesRequest | None = None,
                   user: AuthUser = Depends(meetings_access)) -> dict:
    """Hujjat FONDA yoziladi (1-3 daqiqa): 202 `running` - ilova `GET .../minutes/{id}` ni so'rab turadi.
    202 - yangi hujjat yoki - shu tilda tayyor hujjat bor-u, chatdagi ko'rsatmalardan ba'zilari unda hali yo'q
    (`pendingNotes`) - uning TAHRIRI (`kind` revise: avvalgi o'zgartirishlar saqlanadi). 200 - tayyori bor va hamma
    ko'rsatma unda (`force` bo'lmasa) yoki xuddi shu hujjat hozir yozilmoqda (ikkinchi bosish birinchisiga qo'shiladi:
    model ham, soatlik chegara ham ikkinchi marta sarflanmaydi). 409 `minutes_busy` - shu tilda oldingi o'zgarishlar
    hali navbatda."""
    body = body or schemas.MinutesRequest()
    view, started = minutes.start(user, meeting_id, body.language, force=body.force)
    if not started:
        response.status_code = status.HTTP_200_OK
    return view


@router.get("/{meeting_id}/minutes/{minutes_id}", response_model=schemas.MinutesDetail)
def get_minutes(meeting_id: str, minutes_id: str, user: AuthUser = Depends(meetings_access)) -> dict:
    return minutes.get(user, meeting_id, minutes_id)


@router.get("/{meeting_id}/minutes/{minutes_id}/export", responses={200: {"content": {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}, "application/pdf": {},
    "text/markdown": {}}}})
def export_minutes(meeting_id: str, minutes_id: str, format: str = Query("docx", pattern="^(docx|pdf|md)$"),
                   user: AuthUser = Depends(meetings_access)) -> Response:
    """Tayyor hujjat fayli: Word (asosiy - kotib «________» joylarini to'ldiradi), PDF (nusxa), MD.
    `async` EMAS: chizish CPU ishi - threadpool'da (`_export_slot`: bir odam - bir vaqtda bitta)."""
    data, media, disposition = minutes.export_file(user, meeting_id, minutes_id, format)
    # Shaxsiy hujjat: oraliq kesh (proksi, brauzer) saqlab qolmasin.
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store"})


__all__ = ["router", "meetings_access"]

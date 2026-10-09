"""Yig'ilishlar bo'limi sxemalari - mobil `apps/mobile/src/api/types.ts` ning AYNAN nusxasi.

Shartnoma: `docs/plans/meeting-recorder.md`, 3.1-3.2. Maydon nomi yoki turi
farq qilsa ilova jimgina buziladi - shuning uchun `tests/test_meetings_api.py`
javoblarning maydon to'plamini tekshiradi.

So'rov modellari QAT'IY (noto'g'ri qiymat - 422), javob modellari esa
xizmat qatlami yig'gan lug'atni hujjatlaydi.
"""

from __future__ import annotations

import uuid

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Lang = Literal["uz", "ru", "en"]
TemplateId = Literal["auto", "general", "minutes", "standup", "one_on_one", "project_review", "brainstorm",
                     "sales_call", "interview", "lecture", "short_call", "follow_up"]
MeetingStatus = Literal["uploading", "uploaded", "transcribing", "summarizing", "ready", "failed",
                        "waiting_quota"]
SummaryStatus = Literal["none", "queued", "running", "ready", "failed", "skipped"]
EntrySource = Literal["app", "tile", "launcher", "shortcut", "notification", "link"]


# --- so'rovlar ---------------------------------------------------------------------


class CreateMeetingRequest(BaseModel):
    clientId: str
    title: str | None = Field(default=None, max_length=120)
    recordedAt: str
    language: Lang = "uz"
    template: TemplateId = "auto"
    expectedSpeakers: int | None = Field(default=None, ge=1, le=20)
    #: Tekshiruv xizmatda: noma'lum tur 415 `unsupported_format` (422 emas).
    contentType: str = "audio/aac"
    source: EntrySource = "app"
    appVersion: str | None = Field(default=None, max_length=40)
    device: str | None = Field(default=None, max_length=80)

    @field_validator("clientId")
    @classmethod
    def _uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(str(value)))
        except ValueError:
            raise ValueError("clientId UUID bo'lishi kerak") from None

    @field_validator("template")
    @classmethod
    def _not_follow_up(cls, value: str) -> str:
        if value == "follow_up":
            raise ValueError("follow_up faqat qo'shimcha xulosa tabi")
        return value


class Mark(BaseModel):
    t: float = Field(ge=0)
    note: str | None = Field(default=None, max_length=200)


class CompleteRequest(BaseModel):
    totalBytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    durationSec: float | None = None
    endedAt: str | None = None
    marks: list[Mark] = Field(default_factory=list, max_length=200)


class PatchMeetingRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    template: TemplateId | None = None
    expectedSpeakers: int | None = Field(default=None, ge=1, le=20)


class RetranscribeRequest(BaseModel):
    language: Lang
    expectedSpeakers: int | None = Field(default=None, ge=1, le=20)
    confirmCharge: bool = False


class SpeakerRenameRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class SpeakerMergeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: list[str] = Field(alias="from", min_length=1, max_length=10)
    into: str


class SegmentPatchRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    speaker: str | None = None


class SummaryRequest(BaseModel):
    template: TemplateId
    language: Lang | None = None
    force: bool = False
    makePrimary: bool | None = None


class ActionItemCreate(BaseModel):
    task: str = Field(min_length=1, max_length=300)
    ownerSpeaker: str | None = None
    ownerName: str | None = Field(default=None, max_length=80)
    dueDate: str | None = None
    dueTime: str | None = None
    priority: Literal["high", "normal", "low"] | None = None


class ActionItemPatch(BaseModel):
    status: Literal["open", "done", "dismissed"] | None = None
    task: str | None = Field(default=None, min_length=1, max_length=300)
    ownerSpeaker: str | None = None
    ownerName: str | None = Field(default=None, max_length=80)
    dueDate: str | None = None
    dueTime: str | None = None
    priority: Literal["high", "normal", "low"] | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    language: Lang | None = None


# --- javoblar ----------------------------------------------------------------------


class Speaker(BaseModel):
    id: str
    name: str | None = None
    suggestedName: str | None = None
    talkSec: float
    mergedInto: str | None = None


class Segment(BaseModel):
    id: int
    speaker: str | None = None
    start: float
    end: float
    text: str
    edited: bool


class MeetingError(BaseModel):
    code: str
    message: str
    stage: str
    retryable: bool
    retryAt: str | None = None


class DetectedLanguage(BaseModel):
    code: str | None = None
    share: dict[str, float] = Field(default_factory=dict)


class UploadInfo(BaseModel):
    receivedBytes: int
    totalBytes: int | None = None
    maxChunkBytes: int
    complete: bool


class TranscriptInfo(BaseModel):
    available: bool
    engine: Literal["gapi", "router"] | None = None
    speakersAvailable: bool
    timing: Literal["exact", "approximate"] | None = None
    segmentCount: int
    transcriptRev: int


class Meeting(BaseModel):
    id: str
    clientId: str
    title: str
    titleSource: Literal["auto", "user"]
    status: MeetingStatus
    progress: float | None = None
    pollAfterSec: int | None = None
    language: Lang
    detectedLanguage: DetectedLanguage | None = None
    languageWarning: Literal["mostly_other_language"] | None = None
    template: TemplateId
    expectedSpeakers: int | None = None
    source: EntrySource
    recordedAt: str
    durationSec: float | None = None
    createdAt: str
    updatedAt: str
    upload: UploadInfo
    transcript: TranscriptInfo
    speakers: list[Speaker]
    summaryStatus: SummaryStatus
    primarySummaryId: str | None = None
    openActionItems: int
    audioAvailable: bool
    error: MeetingError | None = None


class MeetingCard(BaseModel):
    id: str
    clientId: str
    title: str
    status: MeetingStatus
    progress: float | None = None
    recordedAt: str
    durationSec: float | None = None
    language: Lang
    template: TemplateId
    summaryStatus: SummaryStatus
    openActionItems: int
    overview: str | None = None
    error: MeetingError | None = None


class MeetingList(BaseModel):
    items: list[MeetingCard]
    limit: int
    offset: int
    total: int


class UploadState(BaseModel):
    receivedBytes: int
    maxChunkBytes: int
    complete: bool


class UploadReceived(BaseModel):
    receivedBytes: int


class Deleted(BaseModel):
    id: str
    status: Literal["deleted"] = "deleted"


class Transcript(BaseModel):
    meetingId: str
    transcriptRev: int
    engine: Literal["gapi", "router"] | None = None
    speakersAvailable: bool
    timing: Literal["exact", "approximate"] | None = None
    language: Lang
    detectedLanguage: DetectedLanguage | None = None
    speakers: list[Speaker]
    segments: list[Segment]


class SpeakersOut(BaseModel):
    speakers: list[Speaker]


class SpeakersMerged(BaseModel):
    speakers: list[Speaker]
    transcriptRev: int


class SegmentOut(BaseModel):
    segment: Segment
    transcriptRev: int


class SummaryErrorOut(BaseModel):
    code: str
    message: str


class SummaryCard(BaseModel):
    id: str
    template: TemplateId
    language: Lang
    status: SummaryStatus
    primary: bool
    stale: bool
    transcriptRev: int
    createdAt: str
    finishedAt: str | None = None
    error: SummaryErrorOut | None = None


class SummaryList(BaseModel):
    items: list[SummaryCard]


class LayoutEntry(BaseModel):
    key: str
    title: str


class Summary(SummaryCard):
    promptVersion: str
    model: str
    layout: list[LayoutEntry]
    speakers: list[Speaker]
    #: `SummaryContent` (spetsifikatsiya 6.2) - `null`, agar holat `ready` bo'lmasa.
    content: dict[str, Any] | None = None


class ActionOwner(BaseModel):
    speaker: str | None = None
    name: str | None = None
    kind: Literal["person", "team", "role", "unknown"]


class ActionDue(BaseModel):
    date: str | None = None
    time: str | None = None
    raw: str | None = None


class ActionItem(BaseModel):
    id: str
    meetingId: str
    summaryItemId: str | None = None
    task: str
    owner: ActionOwner
    due: ActionDue
    priority: Literal["high", "normal", "low"] | None = None
    status: Literal["open", "done", "dismissed"]
    origin: Literal["ai", "user"]
    edited: bool
    needsConfirmation: bool
    sourceSegmentIds: list[int]
    start: float | None = None
    quote: str | None = None
    createdAt: str
    updatedAt: str


class ActionItemList(BaseModel):
    items: list[ActionItem]


class MyActionItem(ActionItem):
    meetingTitle: str
    recordedAt: str | None = None


class MyActionItemList(BaseModel):
    items: list[MyActionItem]


class Citation(BaseModel):
    segmentId: int
    start: float
    speaker: str | None = None
    text: str


class AskAnswer(BaseModel):
    id: str
    question: str
    answer: str
    citations: list[Citation]
    followUps: list[str]
    createdAt: str


class QuestionList(BaseModel):
    items: list[AskAnswer]


class TemplateInfo(BaseModel):
    id: TemplateId
    title: str
    description: str
    auto: bool
    extraTab: bool


class RecordingPreset(BaseModel):
    format: str
    sampleRate: int
    bitRate: int
    channels: int
    audioSource: str


class MeetingsConfig(BaseModel):
    enabled: bool
    maxMinutes: int
    maxUploadBytes: int
    maxChunkBytes: int
    acceptedContentTypes: list[str]
    languages: list[Lang]
    defaultLanguage: Lang
    maxDistinctSpeakers: int
    userDailyMinutes: int
    userTodayMinutes: float
    recording: RecordingPreset
    templates: list[TemplateInfo]

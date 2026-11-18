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
#: Yozuv qayerdan keldi. `call` - telefonning o'z qo'ng'iroq yozuvi (Samsung "Qo'ng'iroqlarni yozish",
#: ilova MediaStore'dan topadi), `share` - boshqa ilovadan "Ulashish -> Barno AI". Ikkalasi ham tayyor
#: fayl (odatda `audio/mp4`); `call` da `auto` shablon telefon qo'ng'irog'i shablonlariga moyil.
EntrySource = Literal["app", "tile", "launcher", "volume", "shortcut", "notification", "link", "call", "share"]
#: Plaud filtri - yozuv qaysi kanaldan kelgani (`store.ORIGINS`, `store.ORIGIN_SQL`).
MeetingOrigin = Literal["recording", "upload", "slack", "telegram", "miniapp", "web", "desktop", "api"]


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
    #: Qo'ng'iroq yozuvi (`source: call`) uchun: odam ilovada "suhbatdoshni ogohlantiring"
    #: eslatmasini QACHON qabul qilgani (ISO) va matn versiyasi. Serverda saqlanadi - qo'ng'iroq
    #: agentga (AI) faqat shu yozuv va egasining alohida qarori bilan ketadi (migratsiya rejasi).
    consentAt: str | None = Field(default=None, max_length=40)
    consentVersion: str | None = Field(default=None, max_length=32)

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


#: Chat xabari qaysi klientdan (`questions.channel`). Slack va Telegram bu yerda yo'q - ular HTTP'dan emas,
#: server ichidan (`service.chat_send(..., channel=...)`) keladi.
ChatChannel = Literal["mobile", "web", "miniapp", "desktop", "api"]

#: Bayonnoma (rasmiy hujjat) tili - `minutes.LANGS`; xulosa tilidan (`Lang`) farqli, o'zbekcha ikki yozuvda.
MinutesLang = Literal["uz-latn", "uz-cyrl", "ru", "en"]
#: `running` - fonda yozilmoqda, `ready` - tayyor, `failed` - yozilmadi (`error.code`: `llm_failed`,
#: `llm_busy`, `llm_rate_limited`, `llm_not_configured`, `internal`, `interrupted`; tahrirda yana `no_change` -
#: so'rov hujjatni o'zgartirmadi, yangi versiya yo'q, `minutes_outdated` / `minutes_missing` - navbatda turganda
#: tahrir asosi yo'qoldi).
MinutesStatus = Literal["running", "ready", "failed"]


class ChatRequest(BaseModel):
    """`POST /meetings/{id}/chat` tanasi - yig'ilish chatiga xabar (bitta audio - bitta suhbat)."""

    message: str = Field(min_length=1, max_length=1000)
    #: Javob tili. `null` - yig'ilish tilida.
    language: Lang | None = None
    #: `null` - `api`.
    channel: ChatChannel | None = None
    #: Xabarning klient kaliti (IDEMPOTENTLIK): ilova har xabarga tasodifiy kalit beradi va «Qayta yuborish»da
    #: O'SHANI yuboradi. Shu yig'ilishda shu kalitli FAOL navbat bor - o'sha qaytadi (modelga so'rov ham, soatlik
    #: chegara ham yo'q); shu kalitli xabar hali javob kutyapti - birinchisi kutiladi. Xabar matni solishtirilmaydi.
    #: `null` - kalitsiz (har so'rov yangi navbat). 8-64 belgi, faqat `A-Z a-z 0-9 _ -`; boshqasi - 422.
    clientId: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    #: Bayonnomaning ANIQ kirish nuqtasi (ilova rejim chipi): `note` - ko'rsatma, `revise` - tayyor hujjatdagi
    #: o'zgartirish. Chat modeli chaqirilmaydi va "ask" soatlik chegarasi olinmaydi. `null` - amalni Barno o'zi
    #: tanlaydi (savol, ko'rsatma, "tayyorla", o'zgartirish). Boshqa qiymat - 422.
    intent: Literal["note", "revise"] | None = None
    #: Odam qaysi til hujjatiga qarab yozyapti (ilova bayonnoma oynasi) - o'zgartirish shu tildagi hujjatga.
    minutesLanguage: MinutesLang | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Xabar bo'sh bo'lmasin")
        return value


class CrmRequest(BaseModel):
    """`POST /meetings/{id}/action-items/{itemId}/crm` tanasi - ixtiyoriy."""

    #: Loyiha ishorasi (odam bilsa). Bo'lmasa - yig'ilish sarlavhasi va kalit so'zlari.
    project: str | None = Field(default=None, max_length=120)
    #: Muddati o'tmagan taklif bo'lsa ham yangisini so'rash.
    force: bool = False


class MinutesRequest(BaseModel):
    """`POST /meetings/{id}/minutes` tanasi - ixtiyoriy (bo'sh tana = default'lar)."""

    #: Hujjat tili (`MinutesLang`). `null` - yig'ilish tilidan (`uz` -> `uz-cyrl`, bank hujjati). Tekshiruv
    #: xizmatda: noma'lum til 400 `invalid_language` (422 emas) - Slack/Telegram bilan bir xil xato.
    language: str | None = Field(default=None, max_length=16)
    #: Tayyori bo'lsa ham qayta yozish. Xuddi shu hujjat hozir yozilayotgan bo'lsa - unga qo'shiladi (200).
    force: bool = False


# --- javoblar ----------------------------------------------------------------------


class Speaker(BaseModel):
    id: str
    name: str | None = None
    suggestedName: str | None = None
    talkSec: float
    mergedInto: str | None = None
    #: Doimiy spiker raqami (ovozidan tanilgan, `voice.py`): ismsiz bo'lsa - «Noma'lum #<personId>».
    personId: int | None = None
    #: `voice` - ism ovozdan (namuna yozgan xodim), `manual` - odam qo'ygan; ism yo'q bo'lsa `None`.
    nameSource: str | None = None
    #: GAPI o'xshashlik bali (0-1).
    voiceScore: float | None = None


class VoiceSampleView(BaseModel):
    id: str
    status: str
    reason: str | None = None
    message: str
    speechSeconds: float | None = None
    channel: str | None = None
    createdAt: int
    doneAt: int | None = None


class VoiceInstructions(BaseModel):
    intro: str
    steps: list[str]
    text: str
    freeSpeech: str
    recommendedSeconds: int
    minSpeechSeconds: float
    maxBytes: int
    acceptedContentTypes: list[str]


class VoiceStatus(BaseModel):
    enabled: bool
    enrolled: bool
    personId: int | None = None
    name: str | None = None
    samples: int
    lastSampleAt: int | None = None
    latest: VoiceSampleView | None = None
    instructions: VoiceInstructions


class VoiceDeleted(BaseModel):
    deleted: int
    samples: int
    message: str


class VoiceCoveragePerson(BaseModel):
    personId: int | None = None
    actorId: int | None = None
    name: str | None = None
    voices: int = 0
    samples: int = 0
    lastSampleAt: int | None = None


class VoiceCoverage(BaseModel):
    enrolled: list[VoiceCoveragePerson]
    missing: list[VoiceCoveragePerson]
    guests: int


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
    #: 2026-10-10: ro'yxatda qo'ng'iroq / ulashilgan fayl belgisini ko'rsatish uchun (eski ilova e'tiborsiz qoldiradi).
    source: EntrySource = "app"
    #: 2026-11-11: Plaud filtri (`GET /meetings?origin=`).
    origin: MeetingOrigin = "api"
    #: 2026-11-11: ro'yxatdagi o'rni (`?sort=listed`, kunlarga shu bilan guruhlanadi): tayyor fayl - kelgan
    #: vaqti, ilovada yozilgani - `recordedAt`.
    listedAt: str


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


class GeneratedBy(BaseModel):
    """Xulosani yozgan model: `v3` (Venera Core) | `openai` | `claude` (Sonnet 5.5, 2026-11-04 dan) |
    `ollama` va model nomi."""

    provider: Literal["v3", "openai", "claude", "ollama"]
    model: str | None = None


class Summary(SummaryCard):
    promptVersion: str
    model: str
    #: `null` - xulosa tayyor emas.
    generatedBy: GeneratedBy | None = None
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


class ActionCrm(BaseModel):
    """Vazifaning CRM taklifi (v3). Tasdiqlash - `POST /api/v1/actions/{token}/confirm`."""

    token: str
    #: pending | executed | failed | cancelled | expired (xizmat yangi holat qo'shsa ham o'tadi).
    status: str
    #: Web `ActionCard` kutgan taklif obyekti (token, connector, operation, summary, target,
    #: changes, warnings, expires_at) - xizmatnikidek, snake_case.
    proposal: dict[str, Any] | None = None
    expiresAt: str | None = None
    #: Tasdiqlangandan keyin CRM qaytargani, masalan {"key": "DVSIB-231"}.
    result: dict[str, Any] | None = None
    updatedAt: str | None = None


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
    #: `null` - CRM ga yuborilmagan.
    crm: ActionCrm | None = None


class ActionItemList(BaseModel):
    items: list[ActionItem]


class MyActionItem(ActionItem):
    meetingTitle: str
    recordedAt: str | None = None


class MyActionItemList(BaseModel):
    items: list[MyActionItem]


class CrmResult(BaseModel):
    """`POST .../crm` javobi. `proposed` - taklif (`proposal`, tasdiqlash `/api/v1/actions`),
    `answered` - agent matn bilan javob berdi (aniqlik so'radi), `failed` - sabab kodi:
    `crm_not_connected` | `assistant_not_configured` | `assistant_busy` | `assistant_unavailable` |
    `timeout` | `assistant_error` | `empty`."""

    status: Literal["proposed", "answered", "failed"]
    proposal: dict[str, Any] | None = None
    text: str | None = None
    reason: str | None = None
    #: Yangilangan vazifa (`crm` holati bilan).
    item: ActionItem | None = None


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


class ChatMinutes(BaseModel):
    """Chat navbatidagi bayonnoma amali (`ChatTurn.minutes`): nima qilindi va hujjatning JONLI holati."""

    #: `note` - ko'rsatma eslab qolindi, `create` - hujjat so'raldi, `revise` - o'zgartirish so'raldi.
    action: Literal["note", "create", "revise"]
    language: MinutesLang | None = None
    #: Bayonnoma qatori (`GET .../minutes/{id}`): shu navbat boshlagan yoki qayta yuborilgan tayyor hujjat.
    id: str | None = None
    #: Jonli holat (`GET /chat` da ham).
    status: MinutesStatus | None = None
    version: int | None = None
    #: Faqat `note` navbatida: faol ko'rsatmalar soni.
    notes: int | None = None
    #: Ish boshlanmadi (`id` yo'q: navbat to'la, chegara, hujjat yo'q yoki eskirgan, model sozlanmagan) yoki qator
    #: `failed` - kod va odamga sabab.
    error: SummaryErrorOut | None = None


class ChatTurn(AskAnswer):
    """Yig'ilish chatining bitta navbati: savol (`question`) va Barno javobi - `AskAnswer` maydonlari bilan."""

    #: Qaysi klientdan: mobile | web | miniapp | desktop | api | slack | telegram; `null` - chatdan oldingi qator.
    channel: str | None = None
    #: Javobni yozgan model (masalan `claude-sonnet-5-5`); `null` - chatdan oldingi qator yoki modelsiz navbat
    #: (aniq bayonnoma niyati).
    model: str | None = None
    #: Xabarning klient kaliti (`ChatRequest.clientId`) - ilova kutilayotgan xabarini shu bilan tanib oladi;
    #: `null` - kalitsiz (botlar, eski qator).
    clientId: str | None = None
    #: Navbat turi: `chat` - savol-javob, `note` - bayonnoma ko'rsatmasi, `create` - hujjat so'rovi, `revise` -
    #: o'zgartirish so'rovi.
    kind: Literal["chat", "note", "create", "revise"] = "chat"
    #: Bayonnoma amali va hujjatning jonli holati; `chat` navbatida `null`.
    minutes: ChatMinutes | None = None


class ChatHistory(BaseModel):
    """`GET /meetings/{id}/chat`: faol navbatlar, ESKISI birinchi ("Yangi suhbat" dan keyingilari)."""

    items: list[ChatTurn]
    #: Hozir javob beradigan model (zanjirdagi birinchi sozlangani); `""` - sozlanmagan.
    model: str


class ChatReset(BaseModel):
    """`DELETE /meetings/{id}/chat` ("Yangi suhbat"): nechta navbat arxivga o'tdi (qatorlar o'chmaydi)."""

    archived: int


class MinutesHeader(BaseModel):
    """Hujjat sarlavha qismining EGA aytgan qiymatlari (`content.header`, faqat to'ldirilganlari keladi; qolgani
    Word da «________»)."""

    organization: str | None = None
    #: Sarlavhadagi "<...> huzurida o'tkazilgan yig'ilish" qatoriga.
    chairedBy: str | None = None
    city: str | None = None
    chair: str | None = None
    attendees: list[str] = Field(default_factory=list)
    #: Ega aytgan yig'ilish sanasi (YYYY-MM-DD): Word dagi sana va fayl nomi shu (aytilmagan - yozuv sanasi).
    date: str | None = None


class MinutesChangeSet(BaseModel):
    """Bandlar yoki kun tartibi masalalari raqamlari (Word dagidek): o'zgargan va qo'shilgan - yangi versiyadagi,
    olib tashlangan - ota-versiyadagi raqamlar."""

    changed: list[int] = Field(default_factory=list)
    added: list[int] = Field(default_factory=list)
    removed: list[int] = Field(default_factory=list)


class MinutesChanges(BaseModel):
    """Tahrir ota-versiyaga nisbatan nimani o'zgartirdi (`minutes.diff.changes`)."""

    items: MinutesChangeSet
    agenda: MinutesChangeSet
    #: O'zgargan sarlavha qiymatlari: organization | chairedBy | city | chair | attendees | date.
    header: list[str] = Field(default_factory=list)
    #: Boshqa qismlar: title | preamble | controller | notes.
    other: list[str] = Field(default_factory=list)


class MinutesView(BaseModel):
    """Bayonnoma holati, mazmunsiz (`minutes.view`)."""

    id: str
    meetingId: str
    language: MinutesLang
    status: MinutesStatus
    createdAt: str
    finishedAt: str | None = None
    #: Yozgan model: `claude` | `openai` | `ollama` va model nomi (tayyor hujjatda).
    provider: str | None = None
    model: str | None = None
    transcriptRev: int
    #: Transkript hujjatdan keyin tahrirlangan - yangi versiya bo'yicha qayta yozish mumkin.
    stale: bool
    agendaCount: int
    sectionCount: int
    itemCount: int
    #: Modelning "Aniqlashtirish kerak" izohlari - hujjatdagidek (`[S#]` o'rniga ism yoki "3-иштирокчи").
    notes: list[str]
    #: Tekshiruv ogohlantirishlari: `ungrounded_name:<ism>`, `unverified_number:<raqam>`, `script_mismatch`,
    #: `header_dropped:<kalit>`, `superseded_revisions:<n>` (matn tahrirlangani uchun yangidan yozildi - avvalgi n ta
    #: tahrir kirmagan), `guidance_truncated:<n>` (eng eski n ta ko'rsatma sig'madi), ...
    warnings: list[str]
    #: `{code, message}` - faqat `failed` da.
    error: SummaryErrorOut | None = None
    #: `generate` - transkriptdan yozilgan asl hujjat, `revise` - tahrir (chatdagi so'rov yoki yangi ko'rsatmalar).
    kind: Literal["generate", "revise"] = "generate"
    #: Odamga ko'rinadigan versiya (1 - asl; tahrir - ota + 1).
    version: int = 1
    #: Tahrirning ota-versiyasi (`kind` revise).
    parentId: str | None = None
    #: O'zgartirish so'rovi - egasining o'z so'zlari; `null` - asl hujjat yoki yangi ko'rsatmalarni qo'llash.
    request: str | None = None
    #: Shu hujjatga berilgan ko'rsatmalar soni.
    notesApplied: int = 0
    #: Faqat `ready` da: so'rovchining shu hujjatda hali yo'q faol ko'rsatmalari soni (`POST .../minutes` ularni
    #: qo'llaydi - tahrir, qaytadan yozish emas).
    pendingNotes: int = 0
    #: Ega aytgan sarlavha qiymatlari (bo'lmasa `null`).
    header: MinutesHeader | None = None
    #: Tahrirda - ota-versiyaga nisbatan o'zgarishlar; asl hujjatda `null`.
    changes: MinutesChanges | None = None


class MinutesList(BaseModel):
    items: list[MinutesView]
    #: Hisob egasining faol bayonnoma ko'rsatmalari soni (chatda berilgan).
    notes: int = 0


class MinutesDetail(MinutesView):
    #: Hujjat mazmuni (`minutes/validate.py` shakli + `version`, `language`, `meeting`, `quality`) - `null`,
    #: agar holat `ready` bo'lmasa. Fayl - `.../minutes/{id}/export`.
    content: dict[str, Any] | None = None


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
    #: Video (`video/mp4`: MP4/MOV) uchun chegara - audiodan katta; server audiosini ajratib, videoni o'chiradi.
    maxVideoUploadBytes: int
    maxChunkBytes: int
    acceptedContentTypes: list[str]
    languages: list[Lang]
    defaultLanguage: Lang
    maxDistinctSpeakers: int
    userDailyMinutes: int
    userTodayMinutes: float
    recording: RecordingPreset
    templates: list[TemplateInfo]

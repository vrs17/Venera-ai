"""Admin panel javoblari: umumiy ko'rinish, savollar izi, suhbatlar, xabarlar
(shikoyatlar), foydalanish, tizim, qidiruv - `apps/web/src/types.ts` dagi
bir xil nomli interfeyslarning AYNAN nusxasi (nomi har sinf docstring'ida);
mosligini `tests/test_contract.py` tekshiradi.

BIRLIKLAR. Vaqtlar ISO-8601 UTC (`Z` bilan), davomiyliklar millisekund
(`...Ms`), ulushlar 0..1 (`errorRate`). Formatlash (til, vaqt zonasi, `%`)
brauzerning ishi - server foydalanuvchining zonasini bilmaydi.

`ReportSummary` / `ReportDetail` SHU YERDA, foydalanuvchi tomoni
(`schemas/reports.py`) ham shu yerdagini oladi: bitta shakl ikki joyda
yozilsa, bir kun ular albatta ajralib ketadi. `AdminUser` va `AuditEntry`
esa `schemas/admin_users.py` da (katalog va audit o'sha bo'limniki).
IMPORT FAQAT BIR TOMONGA: bu fayl `admin_users` dan oladi, `admin_users`
bu fayldan OLMAYDI (u yerda `recentTurns` - `dict`), aks holda aylanma
import bo'lardi.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .admin_users import AdminUser, AuditEntry
from .auth import AuthUser

#: KPI qiymati: soni butun, ulush yoki millisekund - kasr bo'lishi mumkin.
Number = int | float


# --- savollar -----------------------------------------------------------------------


class TurnSummary(BaseModel):
    """types.ts: TurnSummary - ro'yxatdagi bitta savol."""

    id: str
    startedAt: str | None = None
    actorId: int | None = None
    userName: str | None = None
    userLogin: str | None = None
    #: web | miniapp | bot | desktop | api
    channel: str
    #: chat (`/chat/stream`) | ask (`/chat/ask`) | bot
    kind: str
    #: text | voice
    inputMode: str
    chatId: str | None = None
    #: Birinchi 240 belgi (to'liq matn - `TurnDetail`).
    question: str
    #: Qaysi tomon javob berdi: rules | hrm | crm | live | both | clarify, yoki
    #: `contacts` - xodimlar ma'lumotnomasi (yordamchiga bormagan savol).
    route: str | None = None
    #: running | ok | error | cancelled
    status: str
    errorCode: str | None = None
    #: Birinchi so'zgacha (foydalanuvchi "javob keldi" deb sezgan payt).
    ttftMs: int | None = None
    totalMs: int | None = None
    #: Hujjat manbalari va platforma (HRM/CRM) chaqiruvlari - alohida.
    sourcesCount: int = 0
    toolCalls: int = 0
    hasProposal: bool = False
    #: pending | executed | cancelled | failed | expired
    proposalStatus: str | None = None
    hasArtifact: bool = False
    #: Shu savolga (yoki `turnId` siz - butun suhbatiga) xabar berilgan.
    reported: bool = False


class TurnEvent(BaseModel):
    """types.ts: TurnEvent - vaqt chizig'idagi bitta nuqta yoki oraliq."""

    seq: int
    #: Savol boshidan (ms).
    tMs: int
    #: Oraliqda bor (`span`), nuqtada `null`.
    durMs: int | None = None
    #: span (Venera bosqichi) | frame (yuqoridagi xizmat kadri) | note
    type: str
    #: assistant.open, stage, sources, first_token, done, hold.classify, ...
    name: str
    payload: Any = None


class TurnSource(BaseModel):
    """types.ts: TurnSource - topilgan hujjat parchasi yoki HRM/CRM chaqiruvi."""

    idx: int
    #: doc | hrm | crm | tool | ...
    kind: str | None = None
    #: Hujjat kaliti yoki chaqiruv nomi (`hrm_today_late`).
    ref: str | None = None
    title: str | None = None
    page: int | None = None
    score: float | None = None
    snippet: str | None = None
    status: str | None = None
    digest: str | None = None
    #: Javobdagi `[n]` / `[Tn]` raqami.
    citation: int | None = None


class ApiCall(BaseModel):
    """types.ts: ApiCall - bitta tashqi xizmat chaqiruvi."""

    id: int
    ts: str | None = None
    #: assistant | stt_router | stt_gapi | tts | ollama | hrm | crm | keycloak | telegram
    service: str
    op: str
    #: ok | error
    status: str
    httpStatus: int | None = None
    durationMs: int = 0
    actorId: int | None = None
    channel: str | None = None
    turnId: str | None = None
    #: audioSec | chars | bytes | frames - faqat borlari.
    units: dict[str, Number] = Field(default_factory=dict)
    #: Sirlardan tozalangan, 300 belgigacha.
    error: str | None = None


class ChatTurn(BaseModel):
    """types.ts: ChatTurn - savol izida shu suhbatning boshqa savollari."""

    id: str
    startedAt: str | None = None
    question: str
    status: str


# --- xabarlar (shikoyatlar) ------------------------------------------------------------


class ReportSummary(BaseModel):
    """types.ts: ReportSummary - xabarlar qutisidagi bitta qator."""

    id: str
    createdAt: str | None = None
    actorId: int | None = None
    userName: str | None = None
    channel: str | None = None
    chatId: str | None = None
    turnId: str | None = None
    #: wrong | incomplete | outdated | unsafe | other | null
    reason: str | None = None
    #: Izohning birinchi qatori; izoh bo'lmasa - xabar berilgan savol.
    commentPreview: str | None = None
    #: new | reviewing | resolved | dismissed
    status: str
    #: Suhbat nusxasidagi xabarlar soni.
    messages: int = 0


class ReportDetail(ReportSummary):
    """types.ts: ReportDetail - izoh, suhbat nusxasi, admin izohi bilan."""

    comment: str | None = None
    #: `{source: telemetry | upstream | client, messages: ReportMessage[]}`
    snapshot: dict[str, Any] = Field(default_factory=dict)
    adminNote: str | None = None
    updatedAt: str | None = None
    updatedBy: str | None = None


class ReportCounts(BaseModel):
    """types.ts: ReportCounts - qutidagi yorliqlar soni."""

    new: int = 0
    reviewing: int = 0
    resolved: int = 0
    dismissed: int = 0


class ReportPage(BaseModel):
    """types.ts: ReportPage"""

    items: list[ReportSummary] = Field(default_factory=list)
    counts: ReportCounts = Field(default_factory=ReportCounts)
    nextCursor: str | None = None


class ReportUpdate(BaseModel):
    """types.ts: ReportUpdate - `PATCH /admin/reports/{id}` tanasi.

    Yuborilmagan maydon O'ZGARMAYDI; `adminNote: null` yoki `""` - izohni
    o'chirish. Noma'lum maydon - 422: xato yozilgan nom jimgina e'tiborsiz
    qolmasin.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["new", "reviewing", "resolved", "dismissed"] | None = None
    adminNote: str | None = Field(default=None, max_length=2000)


# --- savol izi --------------------------------------------------------------------------


class TurnDetail(TurnSummary):
    """types.ts: TurnDetail - bitta savolning to'liq izi."""

    answer: str | None = None
    requestId: str | None = None
    locale: str | None = None
    endedAt: str | None = None
    httpStatus: int | None = None
    errorText: str | None = None
    events: list[TurnEvent] = Field(default_factory=list)
    sources: list[TurnSource] = Field(default_factory=list)
    apiCalls: list[ApiCall] = Field(default_factory=list)
    #: Shu suhbatning savollari (joriysi ham), eskisi birinchi.
    chatTurns: list[ChatTurn] = Field(default_factory=list)
    reports: list[ReportSummary] = Field(default_factory=list)


class TurnPage(BaseModel):
    """types.ts: TurnPage - `nextCursor` bo'lsa keyingi sahifa bor."""

    items: list[TurnSummary] = Field(default_factory=list)
    nextCursor: str | None = None


# --- suhbatlar -------------------------------------------------------------------------


class AdminChatSummary(BaseModel):
    """types.ts: AdminChatSummary - `chat_id` bo'yicha guruhlangan savollar.

    Nomi `ChatSummary` EMAS: u nom foydalanuvchining suhbatlar tarixida band.
    """

    chatId: str
    actorId: int | None = None
    userName: str | None = None
    channel: str | None = None
    firstAt: str | None = None
    lastAt: str | None = None
    turns: int = 0
    errors: int = 0
    reported: bool = False
    #: Suhbatning birinchi savoli (80 belgi).
    title: str = ""


class ChatPage(BaseModel):
    """types.ts: AdminChatPage"""

    items: list[AdminChatSummary] = Field(default_factory=list)
    nextCursor: str | None = None


# --- umumiy ko'rinish ---------------------------------------------------------------------


class OverviewRange(BaseModel):
    """types.ts: OverviewRange - so'ralgan va taqqoslanadigan oldingi oraliq."""

    model_config = ConfigDict(populate_by_name=True)

    #: `from` Python'da band so'z - JSON'da baribir `from`.
    from_: str = Field(alias="from")
    to: str
    prevFrom: str
    prevTo: str
    #: hour (≤ 2 kun) | day
    bucket: Literal["hour", "day"]


class Kpi(BaseModel):
    """types.ts: Kpi - qiymat, oldingi davr va 14 nuqtali kichik chiziq."""

    value: Number | None = None
    prev: Number | None = None
    spark: list[Number | None] = Field(default_factory=list)


class OverviewKpis(BaseModel):
    """types.ts: OverviewKpis"""

    turns: Kpi
    activeUsers: Kpi
    #: Birinchi so'zgacha, mediana (ms).
    medianTtftMs: Kpi
    #: Xato bilan tugagan savollar ulushi (0..1).
    errorRate: Kpi
    #: Shu oraliqda KELGAN xabarlar.
    newReports: Kpi


class ActivityPoint(BaseModel):
    """types.ts: ActivityPoint - bitta soat/kundagi savollar, kanal bo'yicha."""

    t: str
    web: int = 0
    miniapp: int = 0
    bot: int = 0
    desktop: int = 0
    api: int = 0


class ChannelStat(BaseModel):
    """types.ts: ChannelStat"""

    channel: str
    turns: int = 0
    users: int = 0
    errors: int = 0


class RouteStat(BaseModel):
    """types.ts: RouteStat - `route: null` - yo'nalishsiz (xato, bekor)."""

    route: str | None = None
    turns: int = 0
    errors: int = 0


class LatencyPoint(BaseModel):
    """types.ts: LatencyPoint - birinchi so'zgacha, p50 va p95 (ms)."""

    t: str
    p50: int | None = None
    p95: int | None = None


class DocStat(BaseModel):
    """types.ts: DocStat - hujjat va uni manba qilgan savollar soni."""

    ref: str
    title: str | None = None
    citations: int = 0


class ToolStat(BaseModel):
    """types.ts: ToolStat - HRM/CRM chaqiruvi."""

    ref: str
    calls: int = 0
    errors: int = 0


class AdminOverview(BaseModel):
    """types.ts: AdminOverview - `GET /admin/overview`."""

    range: OverviewRange
    kpis: OverviewKpis
    activity: list[ActivityPoint] = Field(default_factory=list)
    channels: list[ChannelStat] = Field(default_factory=list)
    routes: list[RouteStat] = Field(default_factory=list)
    latency: list[LatencyPoint] = Field(default_factory=list)
    topDocs: list[DocStat] = Field(default_factory=list)
    tools: list[ToolStat] = Field(default_factory=list)
    recentReports: list[ReportSummary] = Field(default_factory=list)
    slowTurns: list[TurnSummary] = Field(default_factory=list)


# --- foydalanish -----------------------------------------------------------------------------


class UsageService(BaseModel):
    """types.ts: UsageService - bitta tashqi xizmat."""

    service: str
    requests: int = 0
    errors: int = 0
    errorRate: float | None = None
    p50Ms: int | None = None
    p95Ms: int | None = None
    #: audioSec | chars | bytes | frames - faqat borlari (yig'indi).
    units: dict[str, Number] = Field(default_factory=dict)
    #: So'rovlar, oraliq 14 ta teng bo'lakka bo'lingan.
    spark: list[int] = Field(default_factory=list)


class UsageSeries(BaseModel):
    """types.ts: UsageSeries - `points[i] = {t, <service>: so'rovlar, ...}`."""

    bucket: Literal["hour", "day"]
    points: list[dict[str, Any]] = Field(default_factory=list)


class UsageOp(BaseModel):
    """types.ts: UsageOp - xizmatning bitta amali (eng sekini birinchi)."""

    service: str
    op: str
    requests: int = 0
    errors: int = 0
    p95Ms: int | None = None


class AdminUsage(BaseModel):
    """types.ts: AdminUsage - `GET /admin/usage`.

    `byChannel[i] = {channel, <service>: so'rovlar, ...}`; `channel: "system"`
    - hech bir foydalanuvchi so'roviga bog'lanmagan chaqiruvlar.
    """

    services: list[UsageService] = Field(default_factory=list)
    series: UsageSeries
    byChannel: list[dict[str, Any]] = Field(default_factory=list)
    ops: list[UsageOp] = Field(default_factory=list)


# --- tizim --------------------------------------------------------------------------------


class SystemConfig(BaseModel):
    """types.ts: SystemConfig - sozlamalar, qiymatlarsiz (faqat yoqilgan/o'chiq)."""

    ssoEnabled: bool = False
    localLoginEnabled: bool = False
    #: polling | webhook (bot ishlaydi, botning o'zi aytgan rejim) | off
    telegramMode: str = "off"
    telegramBotEnabled: bool = False
    retentionDays: int = 0
    analyticsEnabled: bool = True


class StorageStats(BaseModel):
    """types.ts: StorageStats - analitika ombori."""

    dbBytes: int = 0
    turns: int = 0
    events: int = 0
    apiCalls: int = 0
    reports: int = 0
    #: Navbat to'lgani uchun tashlangan yozuvlar (ishga tushgandan beri).
    dropped: int = 0


class AdminSystem(BaseModel):
    """types.ts: AdminSystem - `GET /admin/system`."""

    #: `/api/health/detail` bilan bir xil tashxis.
    health: dict[str, Any] = Field(default_factory=dict)
    config: SystemConfig
    storage: StorageStats
    audit: list[AuditEntry] = Field(default_factory=list)


# --- qidiruv va nishon ------------------------------------------------------------------------


class AdminSearch(BaseModel):
    """types.ts: AdminSearch - buyruqlar oynasi (⌘K), har turdan 5 tagacha."""

    users: list[AdminUser] = Field(default_factory=list)
    turns: list[TurnSummary] = Field(default_factory=list)
    reports: list[ReportSummary] = Field(default_factory=list)


class AdminMe(BaseModel):
    """types.ts: AdminMe - kim kirgan va ko'rilmagan xabarlar soni (nishon)."""

    user: AuthUser
    newReports: int = 0

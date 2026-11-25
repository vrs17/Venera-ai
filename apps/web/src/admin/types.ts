// Admin panel API javoblari - backend shartnomasining (backend-spec §7) aynan nusxasi.
// Manba: `apps/api/app/schemas/admin.py`, `admin_users.py`, `reports.py`; har bir
// interfeys nomi o'sha yerdagi sinf docstring'idagi `types.ts: X` bilan bir xil.
//
// BIRLIKLAR: vaqtlar ISO-8601 UTC satr (`Z` bilan), davomiyliklar millisekund
// (`...Ms`), ulushlar 0..1 (`errorRate`). Formatlash (til, zona, %) - brauzerda.
//
// Server `str` deb e'lon qilgan maydonlar (kanal, holat, xizmat...) ma'lum qiymatlar
// ittifoqi + `(string & {})`: tahrirlovchi takliflarni ko'rsatadi, lekin serverga yangi
// qiymat qo'shilsa (masalan, yangi kanal) tur buzilmaydi - UI uni "noma'lum" deb chizadi.

import type { AuthUser, EngineInfo } from '../types'
import type { ReportMessage, ReportReason } from '../features/report/report.api'

export type { ReportMessage, ReportReason, EngineInfo }

/* ------------------------------------------------------------------ lug'atlar */

/** Kanallar - rang ham shunga bog'langan (`--ch-web` ...). Tartib - UI tartibi. */
export const CHANNELS = ['web', 'miniapp', 'bot', 'desktop', 'api'] as const
export type Channel = (typeof CHANNELS)[number]
/** Global filtr qiymati: `all` - filtrsiz. */
export type ChannelFilter = Channel | 'all'

export const TURN_STATUSES = ['ok', 'error', 'running', 'cancelled'] as const
export type TurnStatus = (typeof TURN_STATUSES)[number]

export type TurnKind = 'chat' | 'ask' | 'bot'
export type InputMode = 'text' | 'voice'

/** Qaysi tomon javob berdi (yuqoridagi yordamchining `done.route`). `none` - faqat filtrda.
 *  `contacts` - yordamchi EMAS, xodimlar ma'lumotnomasi javob bergan (`services/contacts_chat.py`).
 *  2026-10-10 (yordamchi 3.3): `biznes247_kpi` (Biznes 24/7 ko'rsatkichlari), `biznes247_kb`
 *  (qo'llanmalar), `biznes247_help` (Biznes Help), `memory` (Barno xotirasidan javob).
 *  2026-11-25: `agent` - v5 dvigateli har javobda shuni beradi (yoki `error`). */
export const ROUTES = [
  'rules',
  'hrm',
  'crm',
  'live',
  'both',
  'clarify',
  'contacts',
  'biznes247_kpi',
  'biznes247_kb',
  'biznes247_help',
  'memory',
  'agent',
] as const
export type Route = (typeof ROUTES)[number]

/** Yordamchi dvigateli (2026-10-02): `v1` - barqaror, `v2` - yangi (qonun, "Pro").
 *  Filtrda faqat shu ikkitasi; `null` (eski yozuvlar, versiyasiz yo'l) - filtrsiz. */
export const ENGINES = ['v1', 'v2', 'v3', 'v4', 'v5'] as const
export type Engine = (typeof ENGINES)[number]

export type ProposalStatus = 'pending' | 'executed' | 'cancelled' | 'failed' | 'expired'

export const REPORT_STATUSES = ['new', 'reviewing', 'resolved', 'dismissed'] as const
export type ReportStatus = (typeof REPORT_STATUSES)[number]

export const SERVICES = [
  'assistant',
  'stt_router',
  'stt_gapi',
  'tts',
  'ollama',
  'hrm',
  'crm',
  'keycloak',
  'telegram',
] as const
export type UpstreamService = (typeof SERVICES)[number]

/** Panelda beriladigan rollar (manbadan kelgan boshqa rollar ham bo'lishi mumkin). */
export const KNOWN_ROLES = ['ADMIN', 'RAG_ADMIN', 'USER'] as const
export type KnownRole = (typeof KNOWN_ROLES)[number]

export type Bucket = 'hour' | 'day'

/** Tashqi chaqiruv birliklari - faqat borlari keladi. */
export interface ApiUnits {
  audioSec?: number
  chars?: number
  bytes?: number
  frames?: number
}

/* ------------------------------------------------------------------ savollar */

/** types.ts: TurnSummary - ro'yxatdagi bitta savol. */
export interface TurnSummary {
  id: string
  startedAt: string | null
  actorId: number | null
  userName: string | null
  userLogin: string | null
  channel: Channel | (string & {})
  kind: TurnKind | (string & {})
  inputMode: InputMode | (string & {})
  chatId: string | null
  /** Birinchi 240 belgi (to'liq matn - `TurnDetail.question`). */
  question: string
  route: Route | (string & {}) | null
  /** Qaysi dvigatel javob berdi (`done.engine`, bo'lmasa so'ralgani). `null` - migratsiyadan
   *  oldingi yozuv yoki dvigatel aytilmagan. */
  engine: Engine | (string & {}) | null
  status: TurnStatus | (string & {})
  errorCode: string | null
  /** Birinchi so'zgacha. */
  ttftMs: number | null
  totalMs: number | null
  sourcesCount: number
  toolCalls: number
  hasProposal: boolean
  proposalStatus: ProposalStatus | (string & {}) | null
  hasArtifact: boolean
  reported: boolean
}

/** types.ts: TurnEvent - vaqt chizig'idagi nuqta (`durMs: null`) yoki oraliq. */
export interface TurnEvent {
  seq: number
  /** Savol boshidan, ms. */
  tMs: number
  durMs: number | null
  /** span - Venera bosqichi, frame - yordamchi kadri, note - izoh. */
  type: 'span' | 'frame' | 'note' | (string & {})
  /** assistant.open, stage, sources, first_token, done, hold.classify, stt, tts ... */
  name: string
  payload: unknown
}

/** types.ts: TurnSource - topilgan hujjat parchasi yoki HRM/CRM chaqiruvi. */
export interface TurnSource {
  idx: number
  /** doc | hrm | crm | tool ... */
  kind: string | null
  /** Hujjat kaliti yoki chaqiruv nomi (`hrm_today_late`). */
  ref: string | null
  title: string | null
  page: number | null
  score: number | null
  snippet: string | null
  status: string | null
  digest: string | null
  /** Javobdagi `[n]` raqami. */
  citation: number | null
}

/** types.ts: ApiCall - bitta tashqi xizmat chaqiruvi. */
export interface ApiCall {
  id: number
  ts: string | null
  service: UpstreamService | (string & {})
  op: string
  status: 'ok' | 'error' | (string & {})
  httpStatus: number | null
  durationMs: number
  actorId: number | null
  channel: Channel | (string & {}) | null
  turnId: string | null
  units: ApiUnits
  /** Sirlardan tozalangan, 300 belgigacha. */
  error: string | null
}

/** types.ts: ChatTurn - savol izida shu suhbatning savollari (eskisi birinchi). */
export interface ChatTurn {
  id: string
  startedAt: string | null
  question: string
  status: TurnStatus | (string & {})
}

/* ------------------------------------------------------------------ xabarlar */

/** types.ts: ReportSummary - xabarlar qutisidagi bitta qator. */
export interface ReportSummary {
  id: string
  createdAt: string | null
  actorId: number | null
  userName: string | null
  channel: Channel | (string & {}) | null
  chatId: string | null
  turnId: string | null
  reason: ReportReason | null
  /** Izohning birinchi qatori; izoh bo'lmasa - xabar berilgan savol. */
  commentPreview: string | null
  status: ReportStatus
  /** Suhbat nusxasidagi xabarlar soni. */
  messages: number
}

/** Suhbat nusxasi qayerdan olingani. */
export type ReportSnapshotSource = 'telemetry' | 'upstream' | 'client'

export interface ReportSnapshot {
  source?: ReportSnapshotSource | (string & {})
  messages?: ReportMessage[]
}

/** types.ts: ReportDetail */
export interface ReportDetail extends ReportSummary {
  comment: string | null
  snapshot: ReportSnapshot
  adminNote: string | null
  updatedAt: string | null
  updatedBy: string | null
}

/** types.ts: ReportCounts - holat yorliqlari (status filtrisiz, qolgan filtrlar bilan). */
export interface ReportCounts {
  new: number
  reviewing: number
  resolved: number
  dismissed: number
}

/** types.ts: ReportPage */
export interface ReportPage {
  items: ReportSummary[]
  counts: ReportCounts
  nextCursor: string | null
}

/** types.ts: ReportUpdate - yuborilmagan maydon o'zgarmaydi; `adminNote: null` - o'chirish. */
export interface ReportUpdate {
  status?: ReportStatus
  adminNote?: string | null
}

/* ------------------------------------------------------------------ savol izi */

/** types.ts: TurnDetail - bitta savolning to'liq izi. */
export interface TurnDetail extends TurnSummary {
  answer: string | null
  requestId: string | null
  locale: string | null
  endedAt: string | null
  httpStatus: number | null
  errorText: string | null
  events: TurnEvent[]
  sources: TurnSource[]
  apiCalls: ApiCall[]
  chatTurns: ChatTurn[]
  reports: ReportSummary[]
}

/** types.ts: TurnPage - `nextCursor` bo'lsa keyingi sahifa bor. */
export interface TurnPage {
  items: TurnSummary[]
  nextCursor: string | null
}

/* ------------------------------------------------------------------ suhbatlar */

/** types.ts: AdminChatSummary - `chat_id` bo'yicha guruhlangan savollar. */
export interface AdminChatSummary {
  chatId: string
  actorId: number | null
  userName: string | null
  channel: Channel | (string & {}) | null
  firstAt: string | null
  lastAt: string | null
  turns: number
  errors: number
  reported: boolean
  /** Birinchi savol (80 belgi). */
  title: string
}

/** types.ts: AdminChatPage */
export interface AdminChatPage {
  items: AdminChatSummary[]
  nextCursor: string | null
}

/* ------------------------------------------------------------------ umumiy ko'rinish */

/** types.ts: OverviewRange - so'ralgan va taqqoslanadigan oldingi oraliq. */
export interface OverviewRange {
  from: string
  to: string
  prevFrom: string
  prevTo: string
  bucket: Bucket
}

/** types.ts: Kpi - qiymat, oldingi davr va 14 nuqtali trend. */
export interface Kpi {
  value: number | null
  prev: number | null
  spark: (number | null)[]
}

/** types.ts: OverviewKpis */
export interface OverviewKpis {
  turns: Kpi
  activeUsers: Kpi
  /** Birinchi so'zgacha, mediana (ms). */
  medianTtftMs: Kpi
  /** 0..1 */
  errorRate: Kpi
  newReports: Kpi
}

/** types.ts: ActivityPoint - bitta soat/kundagi savollar, kanal bo'yicha. */
export interface ActivityPoint {
  t: string
  web: number
  miniapp: number
  bot: number
  desktop: number
  api: number
}

/** types.ts: ChannelStat */
export interface ChannelStat {
  channel: Channel | (string & {})
  turns: number
  users: number
  errors: number
}

/** types.ts: RouteStat - `route: null` - yo'nalishsiz (xato, bekor). */
export interface RouteStat {
  route: Route | (string & {}) | null
  turns: number
  errors: number
}

/** types.ts: LatencyPoint - birinchi so'zgacha, ms. */
export interface LatencyPoint {
  t: string
  p50: number | null
  p95: number | null
}

/** types.ts: DocStat */
export interface DocStat {
  ref: string
  title: string | null
  citations: number
}

/** types.ts: ToolStat */
export interface ToolStat {
  ref: string
  calls: number
  errors: number
}

/** types.ts: EngineStat - dvigatel bo'yicha savollar. `engine: "default"` - dvigateli
 *  yozilmagan savollar (eski yozuvlar, versiyasiz yo'l). */
export interface EngineStat {
  engine: Engine | 'default' | (string & {})
  turns: number
  errors: number
  /** Birinchi so'zgacha, mediana (ms). */
  medianTtftMs: number | null
}

/** types.ts: AdminOverview - `GET /admin/overview`. */
export interface AdminOverview {
  range: OverviewRange
  kpis: OverviewKpis
  activity: ActivityPoint[]
  channels: ChannelStat[]
  routes: RouteStat[]
  latency: LatencyPoint[]
  topDocs: DocStat[]
  tools: ToolStat[]
  recentReports: ReportSummary[]
  slowTurns: TurnSummary[]
  engines: EngineStat[]
}

/* ------------------------------------------------------------------ foydalanish */

/** types.ts: UsageService - bitta tashqi xizmat. */
export interface UsageService {
  service: UpstreamService | (string & {})
  requests: number
  errors: number
  errorRate: number | null
  p50Ms: number | null
  p95Ms: number | null
  units: ApiUnits
  /** So'rovlar, oraliq 14 bo'lakka bo'lingan. */
  spark: number[]
}

/** `{t, <service>: so'rovlar, ...}` */
export type UsageSeriesPoint = { t: string } & { [service: string]: number | string }

/** types.ts: UsageSeries */
export interface UsageSeries {
  bucket: Bucket
  points: UsageSeriesPoint[]
}

/** `{channel, <service>: so'rovlar, ...}`; `channel: "system"` - foydalanuvchisiz chaqiruvlar. */
export type UsageChannelRow = { channel: string } & { [service: string]: number | string }

/** types.ts: UsageOp - xizmatning bitta amali (eng sekini birinchi). */
export interface UsageOp {
  service: UpstreamService | (string & {})
  op: string
  requests: number
  errors: number
  p95Ms: number | null
}

/** types.ts: AdminUsage - `GET /admin/usage`. */
export interface AdminUsage {
  services: UsageService[]
  series: UsageSeries
  byChannel: UsageChannelRow[]
  ops: UsageOp[]
}

/* ------------------------------------------------------------------ foydalanuvchilar */

/** types.ts: AdminUser - ro'yxatdagi bitta odam. */
export interface AdminUser {
  actorId: number
  name: string
  /** SSO login; zahira hisobda - email. */
  login: string | null
  email: string | null
  department: string | null
  position: string | null
  /** telemetry - hisob manbadan olib tashlangan, faqat savollar tarixida qolgan. */
  source: 'sso' | 'local' | 'both' | 'telemetry' | (string & {})
  /** SAMARALI rollar. */
  roles: string[]
  rolesSource: 'admin' | 'source' | (string & {})
  /** `admin_logins` da: ADMIN ni olib ham, bloklab ham bo'lmaydi. */
  rolesLocked: boolean
  disabled: boolean
  lastSeenAt: string | null
  lastLoginAt: string | null
  /** Tanlangan oraliq bo'yicha. */
  turns: number
  channels: (Channel | (string & {}))[]
  reports: number
}

/** types.ts: AdminUserList */
export interface AdminUserList {
  items: AdminUser[]
}

/** types.ts: AdminUserStats - tanlangan oraliq bo'yicha. */
export interface AdminUserStats {
  turns: number
  errors: number
  medianTtftMs: number | null
  reports: number
  voiceTurns: number
}

/** types.ts: AdminConnector - HRM/CRM ulanishi, TOKENSIZ. */
export interface AdminConnector {
  platform: 'hrm' | 'crm' | (string & {})
  connected: boolean
  enabled: boolean
  login: string | null
  expiresAt: string | null
  state: 'disconnected' | 'connected' | 'expired' | (string & {})
}

/** types.ts: AdminTelegram */
export interface AdminTelegram {
  links: number
  lastSeenAt: string | null
}

/** types.ts: AuditEntry - kim, qachon, nimani o'zgartirdi. */
export interface AuditEntry {
  id: number
  createdAt: string | null
  adminActorId: number | null
  adminName: string | null
  /** user.roles | user.block | user.unblock | user.note | user.signout |
   *  user.connector.disconnect | user.telegram.unlink | report.status | report.note |
   *  engine.policy | engine.access.set | engine.access.remove */
  action: string
  targetType: string | null
  targetId: string | null
  detail: Record<string, unknown> | null
}

/** types.ts: AdminUserDetail - foydalanuvchi varag'i. */
export interface AdminUserDetail extends AdminUser {
  stats: AdminUserStats
  connectors: AdminConnector[]
  telegram: AdminTelegram
  /** Oxirgi 10 ta. */
  recentTurns: TurnSummary[]
  audit: AuditEntry[]
  note: string | null
  /** Shu odamga hozir qaysi versiya ishlaydi va unga alohida nima berilgan.
   *  Ixtiyoriy: versiyalar boshqaruvidan oldingi server bermaydi - bo'lim chizilmaydi. */
  engine?: UserEngine | null
}

/** types.ts: AdminUserUpdate - yuborilmagan maydon o'zgarmaydi.
 *  `roles: null` - manba rollariga qaytarish ("rollar bo'sh" `[]` dan boshqa narsa). */
export interface AdminUserUpdate {
  roles?: string[] | null
  disabled?: boolean
  /** Bo'sh satr - o'chirish. */
  note?: string
}

/** types.ts: SignoutResult */
export interface SignoutResult {
  tokenVersion: number
}

/** types.ts: TelegramUnlinked */
export interface TelegramUnlinked {
  unlinked: number
}

/* ------------------------------------------------------------------ versiyalar */

/** "Versiyalar" sahifasidagi kanallar - server `effective` ni aynan shular uchun beradi.
 *  `desktop` va `api` siyosatda bor, lekin bugun ulardan savol deyarli kelmaydi. */
export const ENGINE_CHANNELS = ['web', 'miniapp', 'bot'] as const
export type EngineChannel = (typeof ENGINE_CHANNELS)[number]

/** types.ts: EnginePolicy - admin saqlagan umumiy siyosat. `channels` da faqat admin
 *  AYTGAN kanallar; yo'q kanal - `default` ga, u ham bo'lmasa `.env` ga tushadi.
 *  `source: env` - admin hali hech narsa saqlamagan. */
export interface EnginePolicy {
  default: string | null
  channels: Partial<Record<Channel | (string & {}), string>>
  /** Hamma chatda TANLAY oladigan versiyalar (default o'zgarmaydi, hech kim o'z-o'zidan ko'chmaydi). */
  selectable?: string[]
  source: 'admin' | 'env' | (string & {})
  updatedAt: string | null
  updatedBy: string | null
}

/** types.ts: EnvDefaults - `.env` dagi boshlang'ich qiymatlar. `default: ''` -
 *  versiyasiz yo'l (favqulodda chiqish, panelda tanlanmaydi). */
export interface EnvDefaults {
  default: string
  channels: Partial<Record<Channel | (string & {}), string>>
}

/** types.ts: EffectiveEngines - alohida versiya berilmagan odam uchun HOZIR nima ishlaydi. */
export interface EffectiveEngines {
  web: string
  miniapp: string
  bot: string
}

/** types.ts: EngineUsage - oxirgi 7 kun. `engine: "default"` - versiyasi yozilmagan savollar. */
export interface EngineUsage {
  engine: Engine | 'default' | (string & {})
  turns: number
  errors: number
  medianTtftMs: number | null
  users: number
}

/** types.ts: EngineAccessRow - odamga alohida berilgan versiyalar. */
export interface EngineAccessRow {
  actorId: number
  name: string
  login: string | null
  /** Kamida bitta; bir nechta bo'lsa odam chatda o'zi tanlaydi. */
  engines: string[]
  /** `null` - tanlamasa umumiy siyosat (ro'yxat ichida bo'lsa) yoki ro'yxatning birinchisi. */
  defaultEngine: string | null
  note: string | null
  updatedAt: string | null
  updatedBy: string | null
}

/** types.ts: AdminEngines - `GET /admin/engines` va `PUT .../policy` javobi. */
export interface AdminEngines {
  catalog: EngineInfo[]
  policy: EnginePolicy
  envDefaults: EnvDefaults
  effective: EffectiveEngines
  stats: EngineUsage[]
  access: EngineAccessRow[]
}

/** types.ts: EnginePolicyUpdate - QO'SHILADIGAN o'zgarish: yuborilmagan maydon va kanal
 *  o'zgarmaydi, `null` - kalitni o'chiradi (keyingi bo'g'inga qaytadi). */
export interface EnginePolicyUpdate {
  default?: string | null
  channels?: Partial<Record<Channel | (string & {}), string | null>>
  /** Berilsa - "hamma tanlay oladi" ro'yxati shuning o'zi (`[]` - hech biri). */
  selectable?: string[]
}

/** types.ts: EngineAccessUpdate. `note` yuborilmasa eskisi qoladi, `null`/`""` - o'chiriladi. */
export interface EngineAccessUpdate {
  engines: string[]
  defaultEngine: string | null
  note?: string | null
}

/** types.ts: EngineAccessRemoved - qator yo'q bo'lsa `false` (xato emas). */
export interface EngineAccessRemoved {
  removed: boolean
}

/** types.ts: UserEngineAccess */
export interface UserEngineAccess {
  engines: string[]
  defaultEngine: string | null
}

/** types.ts: UserEngine - `AdminUserDetail.engine`. */
export interface UserEngine {
  effective: EffectiveEngines
  access: UserEngineAccess | null
}

/* ------------------------------------------------------------------ tizim */

/** `/api/health/detail` tashxisi (server bilan birga o'zgaradi - faqat ma'lum qismi turlangan). */
export interface HealthDetail {
  status?: 'ok' | 'degraded' | (string & {})
  version?: string
  upstream?: {
    stt?: { status: string; broken?: string[] }
    tts?: { status: string }
    [service: string]: unknown
  }
  users?: number
  tts_slots?: { busy: number; limit: number }
  connectors?: { hrm: boolean; crm: boolean; users: number }
  login?: { sso: boolean; local: boolean; identities: number }
  warnings?: string[]
  [key: string]: unknown
}

/** types.ts: SystemConfig - faqat yoqilgan/o'chiq, qiymatlarsiz. */
export interface SystemConfig {
  ssoEnabled: boolean
  localLoginEnabled: boolean
  /** polling | webhook | off */
  telegramMode: string
  telegramBotEnabled: boolean
  retentionDays: number
  analyticsEnabled: boolean
}

/** types.ts: StorageStats - analitika ombori. */
export interface StorageStats {
  dbBytes: number
  turns: number
  events: number
  apiCalls: number
  reports: number
  /** Navbat to'lgani uchun tashlangan yozuvlar (ishga tushgandan beri). */
  dropped: number
}

/** types.ts: AdminSystem - `GET /admin/system`. */
export interface AdminSystem {
  health: HealthDetail
  config: SystemConfig
  storage: StorageStats
  audit: AuditEntry[]
}

/* ------------------------------------------------------------------ qidiruv, nishon */

/** types.ts: AdminSearch - ⌘K, har turdan 5 tagacha. */
export interface AdminSearch {
  users: AdminUser[]
  turns: TurnSummary[]
  reports: ReportSummary[]
}

/** types.ts: AdminMe - kim kirgan va yangi xabarlar soni (nishon). */
export interface AdminMe {
  user: AuthUser
  newReports: number
}

/* ------------------------------------------------------------------ so'rov parametrlari */

/** Global filtr (`useAdminFilters().params`) - deyarli har bir so'rovga qo'shiladi. */
export interface RangeParams {
  /** ISO-8601 (kiradi). */
  from?: string
  /** ISO-8601 (kirmaydi). */
  to?: string
  /** Berilmasa - hamma kanallar. */
  channel?: Channel
}

export interface TurnQuery extends RangeParams {
  /** Savol, javob, ism yoki login; id - aynan. */
  q?: string
  actorId?: number
  /** `none` - yo'nalishsiz savollar. */
  route?: Route | 'none' | (string & {})
  /** Faqat shu dvigatel javob bergan savollar (`/admin/turns` va `/admin/chats`). */
  engine?: Engine
  status?: TurnStatus
  /** true - faqat xabar berilganlar. */
  reported?: boolean
  /** To'liq vaqt kamida, ms. */
  minMs?: number
  chatId?: string
  cursor?: string
  /** 1..100, standart 50. */
  limit?: number
}

export interface ReportQuery extends RangeParams {
  status?: ReportStatus
  q?: string
  actorId?: number
  cursor?: string
  limit?: number
}

export interface UserQuery extends RangeParams {
  q?: string
  role?: string
  status?: 'active' | 'blocked'
}

/* ---- AI ko'chirish (miya flag'lari, agentga migratsiya) ---- */

export type BrainState = 'local' | 'shadow' | 'agent'

/** `GET /api/v1/admin/engines/brain` - bitta funksiya. */
export interface BrainFeatureRow {
  feature: string
  label: string
  ops: string[]
  /** Sozlangan holat (admin yoki `.env`). */
  state: BrainState
  source: 'admin' | 'env' | 'default' | string
  sampleRate: number
  envState: BrainState
  /** Hozir HAQIQATAN ishlayotgani (agent tayyor bo'lmasa `local`). */
  effective: BrainState
  /** Nega pastroq: `agent_disabled`, `not_in_network`, `capability_missing:<nom>` ... */
  reason: string | null
  note: string | null
  updatedAt: string | null
  updatedBy: string | null
}

export interface AdminBrain {
  states: BrainState[]
  features: BrainFeatureRow[]
  agent: {
    enabled?: boolean
    configured?: boolean
    usable?: boolean
    reason?: string | null
    capabilities?: Record<string, unknown>
    circuit?: Record<string, unknown>
  }
  shadow: Record<string, unknown>
  holdClassifier: string
}

export interface BrainFeatureUpdate {
  state?: BrainState | null
  sampleRate?: number | null
  note?: string | null
}

/** `GET /api/v1/admin/engines/brain/shadow` - taqqoslash natijalari (faqat sonlar). */
export interface BrainShadowStats {
  count: number
  ok: number
  errors: number
  timeouts: number
  similarityAvg: number | null
  localP50: number | null
  localP95: number | null
  agentP50: number | null
  agentP95: number | null
  lastAt: number
}

export interface BrainShadow {
  days: number
  features: Record<string, BrainShadowStats>
}

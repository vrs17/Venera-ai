// Types mirror Final_API_Contracts_for_Front_End.docx verbatim.
// Changes here require updating the contract first.

export type ActorType = 'CUSTOMER' | 'EMPLOYEE'

// finalStatus values from POST /api/v1/chat/ask. Kept open with (string & {})
// so an unknown value renders via the fallback badge instead of crashing.
export type FinalStatus =
  | 'READY_FOR_HR_RAG'
  | 'READY_FOR_PUBLIC_RAG'
  | 'READY_FOR_OPENAI'
  | 'PUBLIC_RAG_NO_RELEVANT_CONTEXT'
  | 'RAG_DOMAIN_NOT_READY'
  | 'STOP_ACCESS_DENIED'
  | 'STOP_UNSAFE'
  | (string & {})

/** Routing domain reported alongside finalStatus. */
export type Domain = 'HR' | 'PUBLIC_DOMAIN' | 'PUBLIC_GENERAL' | 'FUTURE_DOMAIN' | (string & {})

interface BaseStage {
  /** Raw model output before parsing; useful for the RAG_ADMIN trace view. */
  rawAnswer: string
  model: string
  adapter: string
  seconds: number
}

export interface GuardStage extends BaseStage {
  safe: boolean
  decision: string
  reason: string
  guardJson: unknown
}

export interface IntentStage extends BaseStage {
  intent: string
  confidence: string
  intentJson: unknown
}

export interface OrchestratorStage extends BaseStage {
  routeType: string
  route: string
  targetModule: string
  requiresAccessCheck: boolean
  reason: string
  orchestratorJson: unknown
}

export interface AccessStage extends BaseStage {
  allowed: boolean
  decision: string
  reason: string
  requiredRole: string
  resourceScope: string
  accessJson: unknown
}

export interface RetrievalSource {
  documentId?: string
  documentTitle?: string
  documentType?: string | null
  version?: string | null
  page?: number | null
  uri?: string | null
}

export interface RetrievalChunk {
  pointId?: string
  chunkId: string
  documentId?: string
  text: string
  source?: RetrievalSource
  metadata?: Record<string, unknown>
  vectorScore?: number
  rerankScore?: number
  rank?: number
}

/** Backend may attach the reranked chunks here once retrieval is wired up. */
export interface RetrievalStage {
  status?: string
  collection?: string
  results: RetrievalChunk[]
  seconds?: number
  error?: string | null
}

export interface PipelineResponse {
  finalStatus: FinalStatus
  /** Routing domain (HR / PUBLIC_DOMAIN / PUBLIC_GENERAL) from /ask. */
  domain?: Domain | null
  domainReason?: string | null
  guard: GuardStage | null
  intent: IntentStage | null
  orchestrator: OrchestratorStage | null
  access: AccessStage | null
  retrieval: RetrievalStage | null
  /** Final answer text from /ask. */
  answer?: string | null
}

/* ---- UI-side state ---- */

export type Phase = 'idle' | 'sending'

/* ---- Streamed answer (POST /api/v1/chat/stream) ----
 *
 * The backend proxies the HR Assistant's NDJSON frames: one JSON object per
 * line. Field names are the assistant's own (snake_case) — renaming them here
 * would mean maintaining a translation table for a contract we do not own,
 * and every new field would silently go missing. The two exceptions are
 * added by our backend, so they are ours to name.
 */

/** One proof item under an answer: a cited document, or one platform lookup
 *  (HRM or CRM — `crm` arrived 2026-09-14 and behaves exactly like `hrm`). */
export interface AnswerSource {
  kind?: 'doc' | 'hrm' | 'crm' | (string & {})
  /** The [n] marker in the answer text (documents). */
  citation_index?: number
  doc_id?: string
  title?: string
  section?: string
  page?: number
  /** The [Tn] marker in the answer text (platform lookups). */
  marker?: string
  /** Platform tool that was called, e.g. hrm_today_late, crm_my_issues.
   *  The prefix says which platform, so the row needs no separate field. */
  tool?: string
  status?: string
  /** Short code-built summary of what the call returned. */
  digest?: string
  /** ADDED BY OUR BACKEND: the path this browser can actually open. The
   *  assistant's own URL points at an internal host the browser cannot reach. */
  docUrl?: string | null
}

/** A generated application file (leave request), when the answer produced one. */
export interface AnswerArtifact {
  title?: string
  doc_id?: string
  /** ADDED BY OUR BACKEND: proxied paths, see AnswerSource.docUrl. */
  docx_url?: string | null
  pdf_url?: string | null
  preview_url?: string | null
  expires_at?: string
}

/** One NDJSON line. `type` is open: the assistant may add frames, and an
 *  unknown one must be ignored rather than crash the reader. */
export interface ChatFrame {
  type: 'stage' | 'sources' | 'artifact' | 'proposal' | 'token' | 'done' | 'error' | (string & {})
  /** stage: human status text. token: the piece of answer to append. error: user-safe message. */
  text?: string
  stage?: string
  /** The live service sends the citations under `items`; the documented
   *  one-shot response calls the same list `sources`. Both are read - the
   *  difference is invisible until a real answer comes back, and picking
   *  one meant the proof list was silently always empty. */
  sources?: AnswerSource[]
  items?: AnswerSource[]
  artifact?: AnswerArtifact
  /** artifact frames may carry the fields inline instead of nested. */
  docx_url?: string | null
  pdf_url?: string | null
  preview_url?: string | null
  title?: string
  doc_id?: string
  /** proposal: the proposed write action, nested or inline like artifact. */
  proposal?: ActionProposal
  /** done: which side answered. */
  route?: string | null
  /** error: machine-readable cause, e.g. auth_missing. */
  code?: string
  request_id?: string
}

export interface UIExchange {
  id: string
  question: string
  /** null while the request is in-flight. */
  response: PipelineResponse | null
  error: string | null
  /** True when the user clicked Stop before the response arrived. */
  cancelled?: boolean
  /** Wall-clock duration measured client-side; the per-stage `seconds` come from the server. */
  durationMs: number | null
  /** Live status from the assistant while the answer is still coming
   *  ("searching documents"). Cleared once the first token arrives. */
  stage?: string | null
  /** Citations and platform lookups behind the answer. */
  sources?: AnswerSource[]
  /** The generated application file, when there is one. */
  artifact?: AnswerArtifact | null
  /** A write action the assistant proposed; shown with Confirm / Reject. */
  proposal?: ActionProposal | null
  /** When the question was sent and when the answer finished (epoch ms).
   *  Shown on hover, like a chat app; reopened chats take the stored time. */
  askedAt?: number | null
  answeredAt?: number | null
  /** rules | hrm | crm | live | both | clarify — shown in developer mode. */
  route?: string | null
  /** Audit key: the same value is in the assistant's own log. */
  requestId?: string | null
  /** An `error` frame that arrived AFTER some of the answer. The answer is
   *  kept and this is shown under it — discarding a partial answer because
   *  its last step failed throws away the part that was useful. */
  warning?: string | null
}

/* ---- Backend auth contract (handoff doc) ---- */

/** Authenticated user from /auth/login, /auth/me, etc. Identity is derived from
 *  the session token server-side — the frontend never sends these fields. */
export interface AuthUser {
  actorId: number
  actorType: 'EMPLOYEE' | 'CUSTOMER' | (string & {})
  email: string
  fullName: string
  position?: string | null
  department?: string | null
  roles: string[]
  passwordChangeRequired: boolean
}

export interface SignupRequest {
  email: string
  fullName: string
  position?: string
  department?: string
}
export interface SignupResponse {
  status: string
  message: string
  user: AuthUser
  /** Always null in production — never display. */
  temporaryPasswordForLocalOnly?: string | null
}

export interface LoginRequest {
  email: string
  password: string
}
export interface LoginResponse {
  token: string
  tokenType: string
  expiresAt: string
  passwordChangeRequired: boolean
  user: AuthUser
}

export interface ChangePasswordRequest {
  currentPassword: string
  newPassword: string
}
export interface ChangePasswordResponse {
  status: string
  message: string
  passwordChangeRequired: boolean
  user: AuthUser
}

export interface LogoutResponse {
  status: string
  message: string
}

/** Uniform backend error envelope returned on every failure. */
export interface ApiErrorResponse {
  timestamp: string
  status: number
  error: string
  message: string
  path: string
}

/* ── Voice ─────────────────────────────────────────────────────────────── */

/** POST /api/v1/stt/transcribe. Mirrors `app/schemas/stt.py` exactly —
 *  `tests/test_contract.py` guards the pair. */
export interface Transcript {
  text: string
  language: string
  durationSec: number
  /** The router is unsure (measured WER ~60–70% when set). The uz backend
   *  sends `null` for this, which the backend normalises to `false`, so it is
   *  always a boolean here. The router docs say: do not act on it
   *  automatically — the panel asks the user to confirm instead. */
  lowConfidence: boolean
  /** Longer than the router's limit; the tail was dropped. */
  truncated: boolean
  /** `uzbek_stt` or `multilang` — which service answered. Debug only. */
  backend: string
}

/* ── Connectors (HRM / CRM - the user's own account) ───────────────────── */

export type ConnectorId = 'hrm' | 'crm'
/** disconnected: hech qachon ulanmagan yoki uzilgan; expired: qayta kirish kerak. */
export type ConnectorState = 'disconnected' | 'connected' | 'expired'

/** schemas/connectors.py: ConnectorStatus. TOKEN BU YERDA YO'Q - faqat holat. */
export interface ConnectorStatus {
  id: ConnectorId
  label: string
  /** Serverda sozlanganmi (`.env`). Sozlanmagan bo'lsa "+" bosilmaydi. */
  configured: boolean
  state: ConnectorState
  /** Ulangan hisobning logini. */
  login: string | null
  /** Ulangan tizim chatda ishlatiladi (kalit). */
  enabled: boolean
  /** HRM tokenining muddati (ISO-8601). CRM da null - u o'zi yangilanadi. */
  expiresAt: string | null
}

/** schemas/connectors.py: ConnectorsResponse */
export interface ConnectorsResponse {
  connectors: ConnectorStatus[]
}

/** schemas/connectors.py: ConnectRequest - platformaning O'Z logini va paroli. */
export interface ConnectRequest {
  username: string
  password: string
}

/** schemas/connectors.py: ConnectorUpdate */
export interface ConnectorUpdate {
  enabled: boolean
}

/* ── Write actions: the assistant proposes, the person confirms ─────────── */

/** One field the proposed action would change. */
export interface ActionChange {
  field?: string
  from?: unknown
  to?: unknown
}

/** A write action the assistant PROPOSED in a `proposal` frame. NOTHING has
 *  changed yet: it runs only after POST /api/v1/actions/{token}/confirm.
 *  The fields are the assistant's own and open — only `token` is required. */
export interface ActionProposal {
  token: string
  summary?: string
  operation?: string | null
  connector?: string | null
  target?: string | Record<string, unknown> | null
  changes?: ActionChange[]
  warnings?: string[]
  expires_at?: string
}

/** schemas/actions.py: ActionResult. `status`: pending | executed | failed |
 *  cancelled | expired. */
export interface ActionResult {
  token: string
  status: 'pending' | 'executed' | 'failed' | 'cancelled' | 'expired' | (string & {})
  summary?: string
  operation?: string | null
  connector?: string | null
  ok?: boolean | null
  error?: string | null
  request_id?: string | null
  result?: Record<string, unknown> | null
}

/* ── Chat history (GET/PATCH/DELETE /api/v1/chats) ──────────────────────── */
/*
 * Conversations live on the assistant, keyed by the `chatId` the browser
 * sends with every turn; our backend proxies the history routes and adds the
 * identity itself. Field names are the assistant's own (snake_case), passed
 * through unchanged like ActionResult. `schemas/chats.py` mirrors these and
 * `tests/test_contract.py` guards the pair.
 */

/** "auto": named by the service (the first words, then the model's short
 *  title); "user": renamed by the person — the model never overwrites it. */
export type TitleSource = 'auto' | 'user' | (string & {})

/** schemas/chats.py: ChatSummary — one sidebar row. */
export interface ChatSummary {
  chat_id: string
  /** Plain text, in the user's own script. Never Markdown. */
  title: string
  title_source: TitleSource
  /** ISO-8601 UTC. Null for legacy chats the service cannot date. */
  created_at: string | null
  /** Last activity — the sort key of the list. */
  updated_at: string | null
  /** Stored messages, user + assistant (divide by two for turns). */
  messages?: number | null
}

/** schemas/chats.py: ChatMessage */
export interface ChatMessage {
  role: 'user' | 'assistant' | (string & {})
  /** The text as shown; may contain [1] / [T1] citation markers. */
  content: string
  created_at: string | null
}

/** schemas/chats.py: ChatDetail — an opened chat with its messages. */
export interface ChatDetail extends Omit<ChatSummary, 'messages'> {
  /** Oldest first; the last `limit` messages. */
  messages: ChatMessage[]
}

/** schemas/chats.py: ChatList */
export interface ChatList {
  items: ChatSummary[]
  limit: number
  offset: number
}

/** schemas/chats.py: ChatDeleted — DELETE is soft; restore brings it back. */
export interface ChatDeleted {
  chat_id: string
  status: 'deleted' | (string & {})
}

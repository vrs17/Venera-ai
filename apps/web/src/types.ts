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
  /** The router is unsure. The uz backend sends `null` for this, which the
   *  backend normalises to `false`, so it is always a boolean here. */
  lowConfidence: boolean
}

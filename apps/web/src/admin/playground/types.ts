// Agent playground (`/api/v1/admin/playground/*`). Bosqich ichi (prompt, xabarlar, vositalar)
// agentniki - shakli agent shartnomasida (`/api/v4/debug/*`), shuning uchun bu yerda erkin:
// agent bosqich yoki maydon qo'shsa, sahifa buzilmaydi va noma'lum maydonlarni JSON bo'lib ko'rsatadi.

export interface PgStatus {
  available: boolean
  code: string | null
  message: string | null
  models: string[]
  default_model?: string | null
  providers?: Record<string, string | null>
}

export interface PgMessage {
  role: string
  content: string
  [key: string]: unknown
}

export interface PgInput {
  system?: string
  messages?: PgMessage[]
  tools?: unknown
  extra?: unknown
  [key: string]: unknown
}

export interface PgOutput {
  text?: string
  json?: unknown
  [key: string]: unknown
}

export interface PgStage {
  id: string
  name: string
  model?: string | null
  ms?: number | null
  tokens_in?: number | null
  tokens_out?: number | null
  input: PgInput
  output?: PgOutput | null
}

export interface PgCapture {
  request_id: string
  engine?: string | null
  route?: string | null
  stages: PgStage[]
}

export interface PgTurnRow {
  id: string
  started_at: number
  user_login: string | null
  channel: string | null
  chat_id: string | null
  request_id: string | null
  question: string | null
  answer: string | null
  route: string | null
  engine: string | null
  status: string | null
  ttft_ms: number | null
  total_ms: number | null
}

export interface PgProblem {
  code: string
  message: string
}

export interface PgTurn {
  turn: PgTurnRow
  capture: PgCapture | null
  problem: PgProblem | null
}

export interface PgRunResult {
  model: string | null
  ok: boolean
  output?: unknown
  ms?: number | null
  tokens_in?: number | null
  tokens_out?: number | null
  tool_calls?: unknown[] | null
  code?: string
  message?: string
}

export interface PgRunResponse {
  runs: PgRunResult[]
  cost_note: string
}

export interface PgRunBody {
  stage: string
  input: PgInput
  model?: string | null
  compare_model?: string | null
  params?: { temperature?: number | null; max_tokens?: number | null }
  confirm_cost: boolean
}

export interface PgPromptBody {
  stage: string
  question: string
  lang?: string
  platforms?: string[]
}

export interface PgCase {
  id: string
  created_at: number
  created_by: string | null
  title: string
  area: string
  needs: 'none' | 'owner'
  turn_id: string | null
  stage: string | null
  note: string | null
  dialog: string[]
  expect: string[]
}

export interface PgCaseBody {
  title: string
  dialog: string[]
  expect: string[]
  turn_id?: string | null
  stage?: string | null
  area?: string
  needs?: 'none' | 'owner'
  note?: string | null
}

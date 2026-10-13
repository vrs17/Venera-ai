// "Tizim xaritasi" ma'lumoti (`GET /api/v1/admin/osmap`) va jonli sinov javobi
// (`/api/v1/admin/probe/*`). Shakl xarita yig'uvchisi (build.py) chiqaradigan JSON bilan
// bir xil - maydon qo'shilsa ixtiyoriy (`?`) bo'lib qo'shiladi: eski fayl ham ochilsin.

export type OsKind =
  | 'user'
  | 'channel'
  | 'ui'
  | 'endpoint'
  | 'service'
  | 'decision'
  | 'llm'
  | 'tool'
  | 'store'
  | 'external'
  | 'job'
  | 'config'

/** Kod parchasi: qaysi xostda, qaysi faylning qaysi qatori (`line` - asosiy qator). */
export interface OsCode {
  host: string
  path: string
  line: number
  symbol?: string
  snippet?: string
  /** `snippet` ning birinchi qatori raqami. */
  snip_start: number
}

/** Prompt - koddan so'zma-so'z (sirlar yashirilgan bo'lsa `redacted`). */
export interface OsPrompt {
  title: string
  host: string
  path: string
  start: number
  end: number
  text: string
  redacted?: boolean
}

/** "Bu qadamni qanday sinash" - xarita yig'uvchisi tekshirgan yo'riqnoma. */
export interface OsTestHook {
  callable: string
  inputs: string
  outputs: string
  side_effects: string
  safe_to_run_in_prod: boolean
}

/** Jonli sinov turi: `stt`, `tts-text`, `tts-speak`, `wake`, `hold`, `mask`, `agent`,
 *  `health` yoki `brain:<funksiya>` (masalan `brain:group_summary`). */
export type ProbeKind = string

export interface OsNode {
  id: string
  label: string
  kind: OsKind | string
  /** Ustun (chapdan o'ngga oqim tartibi). */
  col: number
  summary: string
  details?: string
  model?: string
  flags?: string[]
  /** Ikki marta bosilganda ochiladigan oqim id si. */
  subflow?: string
  code?: OsCode[]
  prompts?: OsPrompt[]
  test_hook?: OsTestHook
  probe?: ProbeKind
}

export interface OsEdge {
  /** Faylda bo'lmasa sahifa o'zi beradi (`<flow>#e<n>`). */
  id?: string
  from: string
  to: string
  label?: string
  condition?: string
  payload?: string
  code?: OsCode[]
}

export interface OsStreamingRow {
  segment: string
  streams: boolean
  how: string
  code?: OsCode[]
}

export interface OsFlow {
  id: string
  title: string
  summary?: string
  group?: string
  repo_state?: string
  gaps?: string[]
  streaming?: OsStreamingRow[]
  nodes: OsNode[]
  edges: OsEdge[]
}

export interface OsMapData {
  meta: { snapshot?: string; barno?: string; agent?: string; built?: string }
  flows: OsFlow[]
}

/* ---- jonli sinov ---- */

export interface ProbeStep {
  step: string
  ms: number
  detail: Record<string, unknown>
}

export interface ProbeResult {
  ok: boolean
  trace: ProbeStep[]
  /** Sinov turiga qarab erkin shakl (backend `admin_probe.py`). */
  result: unknown
  cost_note: string | null
}

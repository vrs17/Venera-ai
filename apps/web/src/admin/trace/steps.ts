// Savol izining vaqt chizig'i: `TurnEvent[]` -> VWaterfall qatorlari.
//
// Yozuvchi (`services/analytics/recorder.py`) uch xil hodisa beradi:
//   span  - Venera bosqichi, davomiyligi bor (`tokens`, `assistant.open`, `hold.classify`,
//           `pipeline`, `telegram.deliver`)
//   frame - yordamchi oqimidagi kadr, lahza (`stage`, `sources`, `done`, `error`, `hold`,
//           `artifact`, `proposal`, noma'lum turlar ham)
//   note  - Venera lahzasi (`first_token`, `first_frame`, `stt`, `hold.skip`,
//           `assistant.broken`, `pipeline.result`)
// Kadrlar bir "oqim" ichida bo'lgani uchun ular ustiga sun'iy "Oqim" oralig'i qo'yiladi
// (birinchi kadrdan oxirgisigacha) - spec §4.5.3 dagi ierarxiya shu.
//
// Ranglar tur bo'yicha (--viz-*), holat ranglari faqat xato uchun (VWaterfall o'zi belgi
// bilan chizadi). Nomlar `admin.trace.span.*` dan; notanish nom - o'zi, o'qiladigan qilib.

import type { WaterfallRow } from '../../ui/VWaterfall.vue'
import { proBadge } from '../../components/chat/pro'
import type { TurnDetail, TurnEvent } from '../types'

export interface TraceStep extends WaterfallRow {
  /** Manba hodisa (sun'iy qatorlarda - yo'q). */
  event: TurnEvent | null
}

/** Tur -> rang. Kanal (Telegram yetkazish) - kanalning DOIMIY rangi. */
export const STEP_COLORS: Record<string, string> = {
  venera: '--viz-7',
  model: '--viz-4',
  assistant: '--viz-1',
  stage: '--viz-1',
  sources: '--viz-3',
  token: '--viz-2',
  done: '--viz-6',
  voice: '--viz-5',
  channel: '--ch-bot',
}

// Hodisa nomi -> `admin.trace.span.*` kaliti. Nuqtali nomlar i18n'da ichma-ich obyekt,
// shuning uchun `hold` (kadr) va `hold.classify` (oraliq) bir kalitga tusha olmaydi.
const LABEL_KEYS: Record<string, string> = {
  request: 'request',
  auth: 'auth',
  tokens: 'tokens',
  stt: 'stt',
  tts: 'tts',
  'hold.classify': 'hold.classify',
  'hold.skip': 'hold.skip',
  hold: 'hold.clip',
  'assistant.open': 'assistant.open',
  'assistant.stream': 'assistant.stream',
  'assistant.broken': 'assistant.broken',
  pipeline: 'pipeline.run',
  'pipeline.result': 'pipeline.result',
  'telegram.deliver': 'telegram.deliver',
  stage: 'stage',
  sources: 'sources',
  first_token: 'first_token',
  first_frame: 'first_frame',
  done: 'done',
  error: 'error',
  artifact: 'artifact',
  proposal: 'proposal',
  // v4 ovozli suhbat: odam "ha" deb AYTDI va agent taklifni o'zi bajardi (`action` kadri).
  action: 'action',
  // Prod'dan: xodimlar ma'lumotnomasi (`open_stream` dagi birinchi oraliq) va
  // "Pro" rejimi (`pro.requested` nuqtasi, `done.pro` dan `pro` kadri).
  contacts: 'contacts',
  'pro.requested': 'pro.requested',
  pro: 'pro.result',
}

type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string
type Exists = (key: string) => boolean

export function stepLabel(name: string, t: Translate, te: Exists): string {
  const key = LABEL_KEYS[name]
  if (key && te(`admin.trace.span.${key}`)) return t(`admin.trace.span.${key}`)
  const text = name.replace(/[._]+/g, ' ').trim()
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : name
}

function kindOf(e: TurnEvent): string {
  const n = e.name
  if (e.type === 'frame') {
    if (n === 'sources') return 'sources'
    if (n === 'done') return 'done'
    if (n === 'hold') return 'voice'
    return 'stage'
  }
  if (n === 'first_token') return 'token'
  if (n === 'first_frame') return 'stage'
  if (n.startsWith('hold')) return 'model'
  if (n.startsWith('assistant') || n.startsWith('pipeline')) return 'assistant'
  if (n === 'stt' || n.startsWith('stt.') || n === 'tts' || n.startsWith('tts.')) return 'voice'
  if (n.startsWith('telegram')) return 'channel'
  return 'venera'
}

function obj(payload: unknown): Record<string, unknown> {
  return payload && typeof payload === 'object' && !Array.isArray(payload) ? (payload as Record<string, unknown>) : {}
}

function text(v: unknown, max = 120): string | null {
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (typeof v !== 'string') return null
  const s = v.replace(/\s+/g, ' ').trim()
  if (!s) return null
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

function joined(parts: unknown[]): string | undefined {
  const out = parts.map((p) => text(p, 60)).filter((p): p is string => !!p)
  return out.length ? out.join(' · ') : undefined
}

function isFailure(e: TurnEvent): boolean {
  const p = obj(e.payload)
  if (e.type === 'frame' && e.name === 'error') return true
  if (e.name === 'assistant.broken') return true
  if (typeof p.error === 'string' && p.error) return true
  return p.ok === false
}

function subOf(e: TurnEvent, routeLabel: (r: string) => string, t: Translate): string | undefined {
  const p = obj(e.payload)
  if (typeof p.error === 'string' && p.error) return text(p.error) ?? undefined
  switch (e.name) {
    case 'stage':
      return text(p.text) ?? text(p.stage) ?? undefined
    case 'sources': {
      const refs = Array.isArray(p.refs) ? p.refs.filter((r) => typeof r === 'string') : []
      const count = typeof p.count === 'number' ? p.count : refs.length
      if (!refs.length) return count ? String(count) : undefined
      const head = refs.slice(0, 2).join(', ')
      return count > 2 ? `${head} +${count - 2}` : head
    }
    case 'done':
      // Yo'nalish va (versiyali yo'lda) dvigatel: "Hujjatlar · v2".
      return joined([typeof p.route === 'string' && p.route ? routeLabel(p.route) : null, p.engine])
    case 'error':
      return joined([p.code, p.text])
    case 'hold':
      return text(p.text) ?? joined([p.topic, p.clip])
    case 'artifact':
      return text(p.title) ?? undefined
    case 'proposal':
      return text(p.summary) ?? text(p.operation) ?? undefined
    case 'action':
      // Holati (`executed`, `failed` ...) va nima edi - qaysi taklif tugmasiz bajarilgani.
      return joined([p.status, p.summary])
    case 'hold.classify':
      return p.skipped ? (text(p.skipped) ?? undefined) : joined([p.model, p.topic])
    case 'hold.skip':
      return joined([p.reason, p.clip])
    case 'first_frame':
      return text(p.type) ?? undefined
    case 'assistant.broken':
      return joined([p.status, p.error])
    case 'pipeline.result':
      return joined([p.finalStatus, p.domain, p.intent])
    case 'contacts':
      // Har savolda o'lchanadi: javob berdimi yoki savol yordamchiga o'tdimi.
      return typeof p.answered === 'boolean'
        ? t(p.answered ? 'admin.trace.contactsHit' : 'admin.trace.contactsMiss')
        : undefined
    case 'pro':
      // Chatdagi belgining AYNAN o'zi (`chat/pro.ts`): byudjet faqat "ishlatildi" da
      // yeyiladi; "berilmadi" sababi bilan (limit, foydalanuvchi yo'q, dvigatel v2 emas).
      // "Ishlatildi" - qisqasi (murojaatlar soni bilan), qolgani - to'liq gap.
      return ((b) => (b?.state === 'used' ? b.text : b?.detail))(proBadge(p, t))
    default:
      return joined([p.model, p.provider, p.engine, p.source])
  }
}

export interface BuildOptions {
  t: Translate
  te: Exists
  routeLabel: (r: string) => string
}

/** Vaqt chizig'i qatorlari: so'rov (butun savol) -> bosqichlar -> oqim -> kadrlar. */
export function buildSteps(turn: TurnDetail, { t, te, routeLabel }: BuildOptions): TraceStep[] {
  const events = [...turn.events].sort((a, b) => a.tMs - b.tMs || a.seq - b.seq)
  const lastEnd = events.reduce((m, e) => Math.max(m, e.tMs + (e.durMs ?? 0)), 0)
  const total = Math.max(turn.totalMs ?? 0, lastEnd)

  const rows: TraceStep[] = [
    {
      id: 'request',
      label: stepLabel('request', t, te),
      sub: turn.inputMode === 'voice' ? t('admin.conversations.voice') : undefined,
      startMs: 0,
      durMs: total > 0 ? total : null,
      kind: 'request',
      status: turn.status === 'error' ? 'error' : undefined,
      depth: 0,
      event: null,
    },
  ]

  // Oqim: yordamchi kadrlari (va birinchi kadr/so'z lahzalari) oralig'i.
  const inStream = (e: TurnEvent) => e.type === 'frame' || e.name === 'first_frame' || e.name === 'first_token'
  const streamEvents = events.filter(inStream)
  const streamStart = streamEvents.length ? streamEvents[0].tMs : 0
  const streamEnd = streamEvents.length ? streamEvents[streamEvents.length - 1].tMs : 0
  const hasStream = streamEvents.length > 1 && streamEnd > streamStart
  let streamAdded = false

  for (const e of events) {
    const stream = inStream(e)
    if (stream && hasStream && !streamAdded) {
      streamAdded = true
      rows.push({
        id: 'assistant.stream',
        label: stepLabel('assistant.stream', t, te),
        startMs: streamStart,
        durMs: streamEnd - streamStart,
        kind: 'assistant',
        status: streamEvents.some(isFailure) ? 'error' : undefined,
        depth: 1,
        event: null,
      })
    }
    const isSpan = typeof e.durMs === 'number' && e.durMs > 0
    rows.push({
      id: `e${e.seq}`,
      label: stepLabel(e.name, t, te),
      sub: subOf(e, routeLabel, t),
      startMs: Math.max(0, e.tMs),
      durMs: isSpan ? e.durMs : null,
      kind: kindOf(e),
      status: isFailure(e) ? 'error' : undefined,
      depth: stream && hasStream ? 2 : 1,
      event: e,
    })
  }
  return rows
}

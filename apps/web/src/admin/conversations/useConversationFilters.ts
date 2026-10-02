// "Suhbatlar" sahifasining o'z filtrlari - global filtr (sana, kanal) ustiga:
//   ?q=ta'til&actor=12&route=hrm&engine=v2&status=error&reported=1&minMs=3000&chat=<id>&view=chats
//
// YAGONA MANBA - URL, xuddi `useAdminFilters` kabi: havola ulashilsa hamkasb aynan shu
// ro'yxatni ochadi, savol izidan "Orqaga" esa filtrlar bilan qaytadi. Umumiy
// ko'rinishdagi havolalar ham shu kalitlarni yozadi (`?status=error`, `?route=none`).
//
// KANAL HAM SHU YERDAN YOZILADI (o'qishda `useAdminFilters` bilan bir xil qoida):
// "Hammasini tozalash" bir tikda bir nechta chip'ni bo'shatadi - agar kanal boshqa
// composable orqali, qolganlari bu yerdan yozilsa, ikkinchi `router.replace` birinchisini
// eski `route.query` bilan bosib ketardi. Hamma o'zgarish bitta navbatdan o'tadi.

import { computed, shallowRef } from 'vue'
import type { ComputedRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { LocationQuery, LocationQueryRaw, LocationQueryValue } from 'vue-router'
import { CHANNELS, ENGINES, ROUTES, TURN_STATUSES } from '../types'
import type { Channel, ChannelFilter, Engine, RangeParams, TurnQuery, TurnStatus } from '../types'

export type ConversationView = 'turns' | 'chats'

export interface ConversationFilterState {
  /** Qidiruv maydonidagi matn (API ga qirqilgan holda ketadi). */
  q: string
  actor: number | null
  /** `ROUTES` yoki `none` (yo'nalishsiz). */
  route: string | null
  /** Yordamchi dvigateli (v1 | v2). */
  engine: Engine | null
  status: TurnStatus | null
  reported: boolean
  /** To'liq javob vaqti kamida, ms. */
  minMs: number | null
  /** Bitta suhbatning savollari. */
  chat: string | null
  view: ConversationView
  channel: ChannelFilter
}

/** Faqat shu sahifaning kalitlari (global filtr kalitlari - `useAdminFilters` da). */
export const CONVERSATION_KEYS = ['q', 'actor', 'route', 'engine', 'status', 'reported', 'minMs', 'chat', 'view'] as const
type Key = (typeof CONVERSATION_KEYS)[number] | 'channel'

/** Ro'yxatni aniqlaydigan HAMMA kalitlar (ko'rinishdan tashqari) - oldingi/keyingi
 *  savol navigatsiyasi shu kalitlar bir xil bo'lgandagina ishlaydi. */
export const LIST_KEYS = ['from', 'to', 'preset', 'channel', 'q', 'actor', 'route', 'engine', 'status', 'reported', 'minMs', 'chat'] as const

const ROUTE_RE = /^[a-z_]{1,32}$/

function first(v: LocationQueryValue | LocationQueryValue[] | undefined): string | null {
  return Array.isArray(v) ? (v[0] ?? null) : (v ?? null)
}

function positiveInt(v: string | null): number | null {
  if (!v || !/^\d{1,12}$/.test(v)) return null
  const n = Number(v)
  return Number.isSafeInteger(n) && n > 0 ? n : null
}

function parse(query: LocationQuery): ConversationFilterState {
  const route = first(query.route)
  const engine = first(query.engine)
  const status = first(query.status)
  const chat = first(query.chat)?.trim() ?? ''
  const channel = first(query.channel)
  return {
    q: (first(query.q) ?? '').slice(0, 200),
    actor: positiveInt(first(query.actor)),
    // Noma'lum, lekin "toza" yo'nalish ham o'tadi: server yangi yo'nalish qo'shsa,
    // umumiy ko'rinishdagi havola bo'sh ro'yxatga emas, to'g'ri filtrga olib kelsin.
    route: route && ((ROUTES as readonly string[]).includes(route) || route === 'none' || ROUTE_RE.test(route)) ? route : null,
    // Faqat ma'lum qiymat: notanish `?engine=` serverga ketsa 422 bo'lardi.
    engine: engine && (ENGINES as readonly string[]).includes(engine) ? (engine as Engine) : null,
    status: status && (TURN_STATUSES as readonly string[]).includes(status) ? (status as TurnStatus) : null,
    reported: ['1', 'true'].includes(first(query.reported) ?? ''),
    minMs: positiveInt(first(query.minMs)),
    chat: chat && chat.length <= 128 ? chat : null,
    view: first(query.view) === 'chats' ? 'chats' : 'turns',
    channel: channel && (CHANNELS as readonly string[]).includes(channel) ? (channel as Channel) : 'all',
  }
}

/** Holat -> URL qiymati; standart qiymat - kalit umuman yozilmaydi (URL toza). */
function encode(key: Key, value: unknown): string | null {
  if (value === null || value === undefined || value === false || value === '') return null
  if (key === 'view') return value === 'chats' ? 'chats' : null
  if (key === 'channel') return value === 'all' ? null : String(value)
  if (key === 'reported') return value ? '1' : null
  if (key === 'q') return String(value).trim() ? String(value) : null
  return String(value)
}

function sameQuery(a: LocationQuery, b: LocationQuery): boolean {
  const norm = (q: LocationQuery) =>
    JSON.stringify(
      Object.keys(q)
        .filter((k) => q[k] !== undefined && q[k] !== null)
        .sort()
        .map((k) => [k, q[k]]),
    )
  return norm(a) === norm(b)
}

// Hali tugamagan navigatsiya: bir tikdagi bir nechta o'zgarish bir-birining ustiga
// yig'ilsin (modul darajasida - filtr qatori va sahifa bitta navbatni ko'radi).
const pending = shallowRef<{ path: string; query: LocationQuery } | null>(null)

export type ConversationPatch = Partial<ConversationFilterState>

export interface ConversationFilters {
  state: ComputedRef<ConversationFilterState>
  /** URL'ning to'liq so'rovi (global + shu sahifa) - kutilayotgan o'zgarish bilan. */
  query: ComputedRef<LocationQuery>
  set: (patch: ConversationPatch) => void
  /** Global filtrdan tashqari biror filtr faolmi (kanal ham hisoblanadi). */
  hasFilters: ComputedRef<boolean>
  /** Savol izi uchun havola so'rovi: ro'yxat filtrlari saqlanadi, ko'rinish tashlanadi. */
  listQuery: ComputedRef<LocationQueryRaw>
  /** API parametrlari: global oraliq + shu sahifa filtrlari. */
  apiParams: (range: RangeParams) => TurnQuery
}

export function useConversationFilters(): ConversationFilters {
  const route = useRoute()
  const router = useRouter()

  const query = computed<LocationQuery>(() => {
    const p = pending.value
    return p && p.path === route.path ? p.query : route.query
  })
  const state = computed(() => parse(query.value))

  function set(patch: ConversationPatch) {
    const next: LocationQuery = { ...query.value }
    for (const [key, value] of Object.entries(patch) as [Key, unknown][]) {
      const encoded = encode(key, value)
      if (encoded === null) delete next[key]
      else next[key] = encoded
    }
    if (sameQuery(next, query.value)) return
    const target = { path: route.path, query: next, hash: route.hash }
    const entry = { path: route.path, query: router.resolve(target).query }
    pending.value = entry
    router.replace(target).finally(() => {
      if (pending.value === entry) pending.value = null
    })
  }

  const hasFilters = computed(() => {
    const s = state.value
    return !!(s.q.trim() || s.actor || s.route || s.engine || s.status || s.reported || s.minMs || s.chat || s.channel !== 'all')
  })

  const listQuery = computed<LocationQueryRaw>(() => {
    const out: LocationQueryRaw = {}
    for (const key of LIST_KEYS) {
      const v = query.value[key]
      if (v !== undefined && v !== null) out[key] = v
    }
    return out
  })

  function apiParams(range: RangeParams): TurnQuery {
    const s = state.value
    const out: TurnQuery = { ...range }
    const q = s.q.trim()
    if (q) out.q = q
    if (s.actor) out.actorId = s.actor
    if (s.route) out.route = s.route
    if (s.engine) out.engine = s.engine
    if (s.status) out.status = s.status
    if (s.reported) out.reported = true
    if (s.minMs) out.minMs = s.minMs
    if (s.chat) out.chatId = s.chat
    return out
  }

  return { state, query, set, hasFilters, listQuery, apiParams }
}

/** Ro'yxat kaliti - ikki sahifa (ro'yxat va iz) bir xil filtrdami. */
export function listKey(query: LocationQuery | LocationQueryRaw): string {
  return JSON.stringify(
    LIST_KEYS.map((k) => {
      const v = query[k]
      return [k, Array.isArray(v) ? (v[0] ?? null) : (v ?? null)]
    }),
  )
}

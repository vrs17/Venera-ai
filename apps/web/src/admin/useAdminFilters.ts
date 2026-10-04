// Admin panelning global filtri: sana oralig'i + kanal (spec §4.5).
//
// YAGONA MANBA - URL (`?preset=7d&channel=bot` yoki `?from=2026-09-01&to=2026-09-29`):
// havolani yuborsangiz, hamkasb aynan shu ko'rinishni ochadi; sahifalar orasida o'tganda
// ham filtr saqlanadi. Shu sababli bu yerda o'z holati yo'q - hamma qiymat
// `route.query` dan hisoblanadi va o'zgarish `router.replace` bilan yoziladi (tarixga
// yangi qadam qo'shilmaydi: "Orqaga" filtrlarni emas, sahifani qaytaradi).
//
// URL'da MAHALLIY kalendar kunlari (o'qish oson, ulashish uchun), API ga esa aniq
// lahzalar (ISO, `to` kirmaydi) ketadi - server foydalanuvchining soat mintaqasini
// bilmaydi, Toshkentdagi "bugun" UTC yarim tunidan emas, mahalliy yarim tundan boshlanadi.
//
// Oraliq qiymati VDateRange bilan BIR XIL shaklda (`{from, to, preset}`, `YYYY-MM-DD`):
//   <VDateRange v-model="range" />  <VSegmented v-model="channel" :options="..." />

import { computed, reactive, shallowRef } from 'vue'
import type { ComputedRef, WritableComputedRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { LocationQuery, LocationQueryRaw, LocationQueryValue, RouteLocationRaw } from 'vue-router'
import { DATE_PRESETS, presetRange, resolveDateRange } from '../ui/VDateRange.vue'
import type { DatePreset, DateRangeValue, FixedDatePreset } from '../ui/VDateRange.vue'
import { addDays, fromISODate, toISODate } from '../ui/format'
import { CHANNELS } from './types'
import type { Channel, ChannelFilter, RangeParams } from './types'

export const DEFAULT_PRESET: FixedDatePreset = '30d'
export const DEFAULT_CHANNEL: ChannelFilter = 'all'

/** Server 2 yildan uzun oraliqni rad etadi (422) - URL'dagi xatoni shu yerda tuzatamiz. */
const MAX_DAYS = 730
const FILTER_KEYS = ['from', 'to', 'preset', 'channel'] as const
const MINUTE = 60_000

/** Oraliq (preset doim aniq) + kanal. */
export interface AdminFilterState {
  preset: DatePreset
  /** Mahalliy kun `YYYY-MM-DD` (kiradi). */
  from: string
  /** Mahalliy kun `YYYY-MM-DD` (shu kun ham kiradi). */
  to: string
  channel: ChannelFilter
}

function isFixedPreset(v: unknown): v is FixedDatePreset {
  return typeof v === 'string' && (DATE_PRESETS as readonly string[]).includes(v)
}

function isChannel(v: unknown): v is Channel {
  return typeof v === 'string' && (CHANNELS as readonly string[]).includes(v)
}

function first(v: LocationQueryValue | LocationQueryValue[] | undefined): string | null {
  return Array.isArray(v) ? (v[0] ?? null) : (v ?? null)
}

/** Qo'lda berilgan oraliq: kelajak - bugun bilan, 2 yildan uzuni - kesiladi.
 *  (Teskari tartib va buzuq sanalarni `resolveDateRange` allaqachon tuzatgan.) */
function clampCustom(from: string, to: string, now: Date = new Date()): { from: string; to: string } {
  const today = toISODate(now)
  let b = to > today ? today : to
  let a = from > b ? b : from
  const bDate = fromISODate(b)
  if (bDate) {
    const min = toISODate(addDays(bDate, -(MAX_DAYS - 1)))
    if (a < min) a = min
  } else {
    a = b = today
  }
  return { from: a, to: b }
}

function parseQuery(query: LocationQuery): AdminFilterState {
  const rawChannel = first(query.channel)
  const channel: ChannelFilter = isChannel(rawChannel) ? rawChannel : DEFAULT_CHANNEL

  const rawPreset = first(query.preset)
  if (isFixedPreset(rawPreset)) return { ...presetRange(rawPreset), preset: rawPreset, channel }

  const rawFrom = first(query.from)
  const rawTo = first(query.to)
  if (rawFrom && rawTo) {
    // URL'dagi aniq sanalar - ATAYLAB `custom`: ulashilgan havola ertaga ham aynan shu
    // kunlarni ko'rsatsin (tayyor oraliq bilan tasodifan mos kelsa ham "suzib" ketmasin).
    const r = resolveDateRange({ from: rawFrom, to: rawTo, preset: 'custom' }, DEFAULT_PRESET)
    if (r.preset === 'custom') return { ...clampCustom(r.from, r.to), preset: 'custom', channel }
  }
  return { ...presetRange(DEFAULT_PRESET), preset: DEFAULT_PRESET, channel }
}

/** Holat -> URL'ning filtr qismi. Standart qiymatlar yozilmaydi (URL toza qoladi). */
function toQuery(state: AdminFilterState): LocationQueryRaw {
  const q: LocationQueryRaw = {}
  if (state.preset === 'custom') {
    q.from = state.from
    q.to = state.to
  } else if (state.preset !== DEFAULT_PRESET) {
    q.preset = state.preset
  }
  if (state.channel !== DEFAULT_CHANNEL) q.channel = state.channel
  return q
}

/**
 * Holat -> API parametrlari (ISO lahzalar). `to` - oxirgi kunning ertasi, lekin
 * hozirdan keyin emas: "bugun" yarim bo'lsa, server oldingi davrni ham shu uzunlikda
 * oladi va taqqoslash adolatli bo'ladi.
 */
export function toRangeParams(state: AdminFilterState, nowMs: number = Date.now()): RangeParams {
  const fromDate = fromISODate(state.from) ?? new Date(nowMs)
  const toDate = fromISODate(state.to) ?? new Date(nowMs)
  const from = fromDate.getTime()
  const endOfLastDay = addDays(toDate, 1).getTime()
  // Daqiqaga yaxlitlaymiz: bir daqiqa ichidagi bir xil so'rovlar aynan bir xil URL.
  const now = Math.ceil(nowMs / MINUTE) * MINUTE
  const to = Math.max(Math.min(endOfLastDay, now), from + MINUTE)
  const out: RangeParams = { from: new Date(from).toISOString(), to: new Date(to).toISOString() }
  // "Hammasi" - kalit umuman yo'q (undefined emas): obyekt toza, JSON/log'da shovqin yo'q.
  if (state.channel !== 'all') out.channel = state.channel
  return out
}

function sameQuery(a: LocationQueryRaw, b: LocationQuery): boolean {
  const norm = (q: LocationQueryRaw | LocationQuery) =>
    JSON.stringify(
      Object.keys(q)
        .filter((k) => q[k] !== undefined)
        .sort()
        .map((k) => [k, q[k]]),
    )
  return norm(a) === norm(b)
}

// Hali tugamagan `router.replace`: bir tik ichidagi ikki o'zgarish (kanal va sana)
// bir-birini eski `route.query` bilan bosib ketmasin, UI esa navigatsiyani kutmay
// darhol yangilansin. Modul darajasida - layout va sahifa bir vaqtda shu composable'ni
// ishlatadi, navigatsiya esa bitta.
const pending = shallowRef<{ path: string; query: LocationQuery } | null>(null)

export interface AdminFilters {
  /** Hammasi bitta obyektda, yoziladigan: `v-model="filters.channel"`. */
  filters: AdminFilterState
  /** VDateRange uchun: `v-model="range"`. */
  range: WritableComputedRef<DateRangeValue>
  preset: WritableComputedRef<DatePreset>
  from: WritableComputedRef<string>
  to: WritableComputedRef<string>
  channel: WritableComputedRef<ChannelFilter>
  /** API parametrlari: `getOverview(params.value)`; filtr o'zgarganda yangi obyekt. */
  params: ComputedRef<RangeParams>
  /** Xuddi shu, lekin "hozir" - ayni lahza (Yangilash tugmasi uchun). */
  freshParams: () => RangeParams
  /** URL'ning faqat filtr qismi - boshqa admin sahifasiga havola filtrni saqlasin. */
  filterQuery: ComputedRef<LocationQueryRaw>
  withFilters: (path: string, extra?: LocationQueryRaw) => RouteLocationRaw
  isDefault: ComputedRef<boolean>
  setPreset: (preset: FixedDatePreset) => void
  setRange: (from: string, to: string) => void
  setChannel: (channel: ChannelFilter) => void
  reset: () => void
}

export function useAdminFilters(): AdminFilters {
  const route = useRoute()
  const router = useRouter()

  const query = computed<LocationQuery>(() => {
    const p = pending.value
    return p && p.path === route.path ? p.query : route.query
  })
  const state = computed<AdminFilterState>(() => parseQuery(query.value))

  function commit(next: AdminFilterState) {
    const rest: LocationQueryRaw = { ...query.value }
    for (const k of FILTER_KEYS) delete rest[k]
    const q: LocationQueryRaw = { ...toQuery(next), ...rest }
    if (sameQuery(q, query.value)) return
    const target = { path: route.path, query: q, hash: route.hash }
    const entry = { path: route.path, query: router.resolve(target).query }
    pending.value = entry
    router.replace(target).finally(() => {
      if (pending.value === entry) pending.value = null
    })
  }

  function setPreset(preset: FixedDatePreset) {
    commit({ ...state.value, ...presetRange(preset), preset })
  }
  function setRange(from: string, to: string) {
    const r = resolveDateRange({ from, to, preset: 'custom' }, DEFAULT_PRESET)
    commit({ ...state.value, ...clampCustom(r.from, r.to), preset: 'custom' })
  }
  function setChannel(channel: ChannelFilter) {
    commit({ ...state.value, channel: channel === 'all' || isChannel(channel) ? channel : DEFAULT_CHANNEL })
  }
  function reset() {
    commit({ ...presetRange(DEFAULT_PRESET), preset: DEFAULT_PRESET, channel: DEFAULT_CHANNEL })
  }

  const range = computed<DateRangeValue>({
    get: () => ({ from: state.value.from, to: state.value.to, preset: state.value.preset }),
    set: (v) => {
      if (isFixedPreset(v.preset)) setPreset(v.preset)
      else setRange(v.from, v.to)
    },
  })
  const preset = computed<DatePreset>({
    get: () => state.value.preset,
    // "custom" - joriy kunlarni qo'lda tahrirlashga o'tish (sanalar o'zgarmaydi).
    set: (p) => (isFixedPreset(p) ? setPreset(p) : setRange(state.value.from, state.value.to)),
  })
  const from = computed<string>({
    get: () => state.value.from,
    set: (d) => setRange(d, state.value.to),
  })
  const to = computed<string>({
    get: () => state.value.to,
    set: (d) => setRange(state.value.from, d),
  })
  const channel = computed<ChannelFilter>({
    get: () => state.value.channel,
    set: setChannel,
  })

  // Filtr QIYMATLARI o'zgarmasa - o'sha obyekt. `state` URL'ning istalgan o'zgarishida
  // (xabar yoki odam tanlandi, `?status=`) qayta hisoblanadi, `toRangeParams` esa "hozir"
  // ni oladi: daqiqa almashgan bo'lsa `to` boshqacha chiqib, ro'yxat keraksiz qayta
  // so'ralardi va "Yana yuklash" bilan ochilgan sahifalar tashlanardi.
  const settled = computed<AdminFilterState>((prev) => {
    const s = state.value
    return prev && prev.preset === s.preset && prev.from === s.from && prev.to === s.to && prev.channel === s.channel
      ? prev
      : s
  })
  const params = computed(() => toRangeParams(settled.value))
  const freshParams = () => toRangeParams(state.value, Date.now())
  const filterQuery = computed(() => toQuery(settled.value))
  const withFilters = (path: string, extra: LocationQueryRaw = {}): RouteLocationRaw => ({
    path,
    query: { ...filterQuery.value, ...extra },
  })
  const isDefault = computed(
    () => state.value.preset === DEFAULT_PRESET && state.value.channel === DEFAULT_CHANNEL,
  )

  // Writable computed'lar reactive ichida ham yozilganda setter'ni chaqiradi.
  const filters: AdminFilterState = reactive({ preset, from, to, channel })

  return {
    filters,
    range,
    preset,
    from,
    to,
    channel,
    params,
    freshParams,
    filterQuery,
    withFilters,
    isDefault,
    setPreset,
    setRange,
    setChannel,
    reset,
  }
}

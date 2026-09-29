// "Foydalanuvchilar" sahifasining o'z filtrlari - global filtr (sana) ustiga:
//   ?q=ali&role=ADMIN&status=blocked&channel=bot
//
// YAGONA MANBA - URL: varaqdan ro'yxatga yopib qaytganda, savol izidan "Orqaga"
// bosilganda va havola ulashilganda ro'yxat aynan shu filtrlar bilan ochiladi.
//
// KANAL HAM SHU YERDAN YOZILADI (o'qish qoidasi `useAdminFilters` bilan bir xil, kalit
// ham bitta - `channel`, boshqa sahifalarga o'tganda saqlanadi). Sabab: "Hammasini
// tozalash" bir tikda bir nechta chip'ni bo'shatadi; kanal boshqa composable orqali,
// qolganlari bu yerdan yozilsa, ikkinchi `router.replace` birinchisini eski
// `route.query` bilan bosib ketardi. Hamma o'zgarish bitta navbatdan o'tadi.

import { computed, shallowRef } from 'vue'
import type { ComputedRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { LocationQuery, LocationQueryValue } from 'vue-router'
import { CHANNELS } from '../types'
import type { Channel, RangeParams, UserQuery } from '../types'

export type UserStatusFilter = 'active' | 'blocked'

export interface UserFilterState {
  /** Qidiruv maydonidagi matn (API ga qirqilgan holda ketadi). */
  q: string
  role: string | null
  status: UserStatusFilter | null
  channel: Channel | null
}

type Key = keyof UserFilterState

/** Rol nomi: server `max_length=64`; bo'shliq va boshqa belgilar - URL'dagi xato. */
const ROLE_RE = /^[A-Za-z0-9_.-]{1,64}$/

function first(v: LocationQueryValue | LocationQueryValue[] | undefined): string | null {
  return Array.isArray(v) ? (v[0] ?? null) : (v ?? null)
}

function parse(query: LocationQuery): UserFilterState {
  const role = first(query.role)
  const status = first(query.status)
  const channel = first(query.channel)
  return {
    q: (first(query.q) ?? '').slice(0, 200),
    role: role && ROLE_RE.test(role) ? role : null,
    status: status === 'active' || status === 'blocked' ? status : null,
    channel: channel && (CHANNELS as readonly string[]).includes(channel) ? (channel as Channel) : null,
  }
}

function encode(key: Key, value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null
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
// yig'ilsin (modul darajasida - sahifa va filtr qatori bitta navbatni ko'radi).
const pending = shallowRef<{ path: string; query: LocationQuery } | null>(null)

export interface UserFilters {
  state: ComputedRef<UserFilterState>
  /** URL'ning to'liq so'rovi (global + shu sahifa) - kutilayotgan o'zgarish bilan. */
  query: ComputedRef<LocationQuery>
  set: (patch: Partial<UserFilterState>) => void
  /** Sanadan tashqari biror filtr faolmi. */
  hasFilters: ComputedRef<boolean>
  /** API parametrlari: global oraliq (kanalsiz) + shu sahifa filtrlari. */
  apiParams: (range: RangeParams) => UserQuery
}

export function useUserFilters(): UserFilters {
  const route = useRoute()
  const router = useRouter()

  const query = computed<LocationQuery>(() => {
    const p = pending.value
    return p && p.path === route.path ? p.query : route.query
  })
  const state = computed(() => parse(query.value))

  function set(patch: Partial<UserFilterState>) {
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
    return !!(s.q.trim() || s.role || s.status || s.channel)
  })

  function apiParams(range: RangeParams): UserQuery {
    const s = state.value
    // Kanal global parametrlardan EMAS, shu yerdagi holatdan: chip bosilganda URL hali
    // yangilanmagan bo'lsa ham so'rov darhol to'g'ri kanal bilan ketsin.
    const out: UserQuery = { from: range.from, to: range.to }
    const q = s.q.trim()
    if (q) out.q = q
    if (s.role) out.role = s.role
    if (s.status) out.status = s.status
    if (s.channel) out.channel = s.channel
    return out
  }

  return { state, query, set, hasFilters, apiParams }
}

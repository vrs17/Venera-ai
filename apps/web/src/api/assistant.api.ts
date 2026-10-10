// Barno XOTIRASI va PLATFORMA KALITLARI (yordamchi 3.3, 2026-10-10) - faqat HTTP.
//
// Brauzer yordamchiga HECH QACHON to'g'ridan-to'g'ri bormaydi: bizning backend proksi
// qiladi (`/api/v1/assistant/*`) va `user_id` ni O'ZI qo'yadi (sessiyadan). Shuning
// uchun bu yerda `user_id` yo'q va bo'lishi ham kerak emas - boshqa odamning xotirasini
// so'rashning yo'li yo'q.
//
// NOMLAR. Bizda `/api/v1/connectors` allaqachon BAND - u odamning HRM/CRM LOGIN
// tokenlari (`connectors.api.ts`). Yordamchining `/api/connectors` i esa boshqa narsa:
// "Barno shu manbadan foydalansinmi" kalitlari. Chalkashmasin deb bizda ular
// PLATFORMALAR (`/api/v1/assistant/platforms`).
//
// SHAKLLAR - yordamchining o'z sxemasi (MemoryItem, ConnectorItem; snake_case), backend
// ularni o'zgartirmay uzatadi. Shunga qaramay javob "tolerant" o'qiladi (`toMemoryItem`,
// `toPlatform`): ro'yxat kaliti `platforms` yoki `connectors`, maydon `user_enabled` yoki
// `userEnabled` - backend tomonda nom o'zgarsa ekran bo'sh qolmasin, buzuq yozuv esa
// jim tashlansin (butun ro'yxatni yiqitmasin). Kontrakt BITTA joyda - shu faylda.

import { ApiError, apiFetch } from './http'

/* ── Kontrakt ───────────────────────────────────────────────────────────── */

/** Proksi yo'llari. Backend bilan kelishilgan (`app/api/v1/assistant_*`). */
export const ASSISTANT_ROUTES = {
  memory: '/api/v1/assistant/memory',
  memoryItem: (id: string) => `/api/v1/assistant/memory/${encodeURIComponent(id)}`,
  platforms: '/api/v1/assistant/platforms',
  platform: (id: string) => `/api/v1/assistant/platforms/${encodeURIComponent(id)}`,
} as const

/** Upstream `MemoryItem`. `kind`/`source` ochiq: xizmat yangi qiymat qo'shsa ham chiziladi. */
export interface MemoryItem {
  /** "m12" (eslab qolingan / o'rganilgan) yoki "h3f2a…" (CRM vazifalaridan o'rganilgan tartib). */
  id: string
  /** Barno saqlagan gap - foydalanuvchi tilida, bitta jumla. */
  text: string
  kind: 'preference' | 'fact' | 'routine' | (string & {})
  /** `user` - odam o'zi "eslab qol" degan; `learned` - so'rash/ishlash uslubidan o'rganilgan. */
  source: 'user' | 'learned' | (string & {})
  /** ISO vaqt; vazifalardan o'rganilgan tartibda bo'sh. */
  created_at: string | null
  updated_at: string | null
}

/** Upstream `MemoryListResp`. */
export interface MemoryList {
  items: MemoryItem[]
  count: number
}

/** Upstream `MemoryDeleteResp`: `status` - "deleted" yoki "empty" (o'chiradigan narsa yo'q edi). */
export interface MemoryDeleteResult {
  deleted: string[]
  status: 'deleted' | 'empty' | (string & {})
}

/** Upstream `ConnectorItem` - bizda "platforma". */
export interface Platform {
  /** "hrm", "crm", "dwh", "biznes247", "superapp", "biznes247_kb", "biznes247_help". */
  id: string
  /** Ko'rsatiladigan nom ("Biznes 24/7") - bizda tarjima bo'lmasa ishlatiladi. */
  name: string
  /** Sozlamalar uchun bir qator (o'zbekcha) - bizda tarjima bo'lmasa ishlatiladi. */
  description: string
  /** `live` - odamning o'z hisobi, `data` - bank raqamlari, `knowledge` - qo'llanmalar. */
  kind: 'live' | 'data' | 'knowledge' | (string & {})
  /** Chatda shu tizim tokeni kerak (HRM/CRM) - login holati "Tizimga kirish" bo'limida. */
  needs_login: boolean
  /** Serverda yoqilgan. `false` - kulrang, odam yoqa olmaydi. */
  available: boolean
  /** Odamning o'z kaliti (o'chirmaguncha `true`). */
  user_enabled: boolean
  /** available && user_enabled - Barno shu odam uchun ishlatadi. */
  enabled: boolean
}

/** "Hammasini unutish" tasdig'i (`?confirm=forget-all`, backend `assistant_extras.FORGET_ALL`).
 *  Backend usiz chaqiruvni 400 `confirm_required` bilan RAD ETADI va xizmatga bormaydi:
 *  umumiy DELETE yordamchisi yoki tasodifiy so'rov xotirani o'chirib yubormasin. `true`
 *  emas - aniq ibora, boshqa joydan ko'chirilgan `?confirm=true` ishlamasin. */
export const FORGET_ALL_CONFIRM = 'forget-all'

/* ── Tolerant o'qish ────────────────────────────────────────────────────── */

type Raw = Record<string, unknown>

const isObj = (v: unknown): v is Raw => !!v && typeof v === 'object' && !Array.isArray(v)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)
const bool = (v: unknown, fallback: boolean): boolean => (typeof v === 'boolean' ? v : fallback)

export function toMemoryItem(raw: unknown): MemoryItem | null {
  if (!isObj(raw)) return null
  const id = str(raw.id) ?? (typeof raw.id === 'number' ? String(raw.id) : null)
  const text = str(raw.text)
  if (!id || !text) return null
  return {
    id,
    text: text.trim(),
    kind: str(raw.kind) ?? 'fact',
    source: str(raw.source) ?? 'learned',
    created_at: str(raw.created_at) ?? str(raw.createdAt),
    updated_at: str(raw.updated_at) ?? str(raw.updatedAt),
  }
}

export function toPlatform(raw: unknown): Platform | null {
  if (!isObj(raw)) return null
  const id = str(raw.id)
  if (!id) return null
  const available = bool(raw.available, true)
  const userEnabled = bool(raw.user_enabled ?? raw.userEnabled, true)
  return {
    id: id.trim().toLowerCase(),
    name: str(raw.name) ?? id,
    description: str(raw.description) ?? '',
    kind: str(raw.kind) ?? 'live',
    needs_login: bool(raw.needs_login ?? raw.needsLogin, false),
    available,
    user_enabled: userEnabled,
    enabled: bool(raw.enabled, available && userEnabled),
  }
}

function toDeleteResult(raw: unknown): MemoryDeleteResult {
  const o = isObj(raw) ? raw : {}
  const deleted = Array.isArray(o.deleted) ? o.deleted.filter((x): x is string => typeof x === 'string') : []
  return { deleted, status: str(o.status) ?? (deleted.length ? 'deleted' : 'empty') }
}

/* ── Chaqiruvlar ────────────────────────────────────────────────────────── */

export async function listMemory(): Promise<MemoryList> {
  const raw = await apiFetch<unknown>(ASSISTANT_ROUTES.memory)
  const o = isObj(raw) ? raw : {}
  const items = (Array.isArray(o.items) ? o.items : []).map(toMemoryItem).filter((x): x is MemoryItem => x !== null)
  return { items, count: typeof o.count === 'number' ? o.count : items.length }
}

/** Bitta bandni butunlay o'chiradi. Qaytarib bo'lmaydi. */
export async function deleteMemoryItem(id: string): Promise<MemoryDeleteResult> {
  return toDeleteResult(await apiFetch<unknown>(ASSISTANT_ROUTES.memoryItem(id), { method: 'DELETE' }))
}

/** HAMMASINI unutadi (CRM vazifalaridan o'rganilgan tartib ham). Suhbatlarga tegmaydi. */
export async function forgetAllMemory(): Promise<MemoryDeleteResult> {
  const raw = await apiFetch<unknown>(`${ASSISTANT_ROUTES.memory}?confirm=${FORGET_ALL_CONFIRM}`, { method: 'DELETE' })
  return toDeleteResult(raw)
}

export async function listPlatforms(): Promise<Platform[]> {
  const raw = await apiFetch<unknown>(ASSISTANT_ROUTES.platforms)
  const o = isObj(raw) ? raw : {}
  const list = Array.isArray(o.platforms) ? o.platforms : Array.isArray(o.connectors) ? o.connectors : Array.isArray(raw) ? raw : []
  return list.map(toPlatform).filter((x): x is Platform => x !== null)
}

/** Kalit. Tana FAQAT `{enabled}` (backend ortiqcha maydonni 422 bilan rad etadi - kimlik
 *  so'rovdan olinmaydi). Javob - yangilangan platforma (bo'lmasa `null`). */
export async function setPlatform(id: string, enabled: boolean): Promise<Platform | null> {
  const raw = await apiFetch<unknown>(ASSISTANT_ROUTES.platform(id), {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  })
  return toPlatform(raw)
}

/* ── Xatolar ────────────────────────────────────────────────────────────── */

export type AssistantErrorKind = 'unavailable' | 'rateLimited' | 'network' | 'notFound' | 'generic'

/** Backend "bunday narsa yo'q" degan 404 kodlari (`assistant_extras._MESSAGES`). */
const NOT_FOUND_CODES: ReadonlySet<string> = new Set(['memory_not_found', 'platform_not_found'])

/**
 * Xato turi - ekran o'z tilidagi matnni ko'rsatadi (`assistant.errors.*`). Backend
 * yordamchi xatolarini 502/503/504 ga o'giradi (konvertda `code`: upstream_unavailable,
 * upstream_timeout, rate_limited, memory_not_found, ...) - bu yerda status yetarli; nginx
 * esa JSON'siz "Request failed (502)" qaytarishi mumkin - status matndan ham o'qiladi.
 *
 * 404 - FAQAT backend kodi bilan (`memory_not_found`) "yo'q" (`notFound`). Kodsiz 404 -
 * yo'l topilmadi: web API'dan oldin chiqarilgan, API qaytarilgan (rollback) yoki nginx
 * yo'li mos emas. Uni "allaqachon unutilgan" deb o'qisak, odamga "unutildi" deyilardi,
 * aslida hech narsa o'chmagan - shuning uchun u "xizmat ishlamayapti" (`unavailable`).
 */
export function assistantErrorKind(err: unknown): AssistantErrorKind {
  if (err instanceof ApiError) {
    const status = err.status ?? Number(/\((\d{3})\)\s*$/.exec(err.message)?.[1] ?? 0)
    if (status === 404) return NOT_FOUND_CODES.has(err.body?.code ?? '') ? 'notFound' : 'unavailable'
    if (status === 429) return 'rateLimited'
    if (status === 501 || status >= 500) return 'unavailable'
    return 'generic'
  }
  // fetch() tarmoqqa chiqa olmadi ("Failed to fetch").
  if (err instanceof TypeError) return 'network'
  return 'generic'
}

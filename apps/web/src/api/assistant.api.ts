// Barno XOTIRASI (yordamchi 3.3, 2026-10-10) - faqat HTTP.
//
// Brauzer yordamchiga HECH QACHON to'g'ridan-to'g'ri bormaydi: bizning backend proksi
// qiladi (`/api/v1/assistant/*`) va `user_id` ni O'ZI qo'yadi (sessiyadan). Shuning
// uchun bu yerda `user_id` yo'q va bo'lishi ham kerak emas - boshqa odamning xotirasini
// so'rashning yo'li yo'q.
//
// SHAKLLAR - yordamchining o'z sxemasi (MemoryItem; snake_case), backend ularni
// o'zgartirmay uzatadi. Shunga qaramay javob "tolerant" o'qiladi (`toMemoryItem`): maydon
// `created_at` yoki `createdAt` - backend tomonda nom o'zgarsa ekran bo'sh qolmasin, buzuq
// yozuv esa jim tashlansin (butun ro'yxatni yiqitmasin). Kontrakt BITTA joyda - shu faylda.
//
// Platforma kalitlari 2026-11-12 da olib tashlandi (ega qarori): endi kalit yo'q, ulangan
// tizim ishlatiladi. Proksining `/assistant/platforms` yo'li faqat eski mobil ilova uchun
// qoldi - web va Mini App uni chaqirmaydi.

import { ApiError, apiFetch } from './http'

/* ── Kontrakt ───────────────────────────────────────────────────────────── */

/** Proksi yo'llari. Backend bilan kelishilgan (`app/api/v1/assistant_*`). */
export const ASSISTANT_ROUTES = {
  memory: '/api/v1/assistant/memory',
  memoryItem: (id: string) => `/api/v1/assistant/memory/${encodeURIComponent(id)}`,
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

/** "Hammasini unutish" tasdig'i (`?confirm=forget-all`, backend `assistant_extras.FORGET_ALL`).
 *  Backend usiz chaqiruvni 400 `confirm_required` bilan RAD ETADI va xizmatga bormaydi:
 *  umumiy DELETE yordamchisi yoki tasodifiy so'rov xotirani o'chirib yubormasin. `true`
 *  emas - aniq ibora, boshqa joydan ko'chirilgan `?confirm=true` ishlamasin. */
export const FORGET_ALL_CONFIRM = 'forget-all'

/* ── Tolerant o'qish ────────────────────────────────────────────────────── */

type Raw = Record<string, unknown>

const isObj = (v: unknown): v is Raw => !!v && typeof v === 'object' && !Array.isArray(v)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)

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

/* ── Xatolar ────────────────────────────────────────────────────────────── */

export type AssistantErrorKind = 'unavailable' | 'rateLimited' | 'network' | 'notFound' | 'generic'

/** Backend "bunday narsa yo'q" degan 404 kodi (`assistant_extras._MESSAGES`). */
const NOT_FOUND_CODE = 'memory_not_found'

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
    if (status === 404) return err.body?.code === NOT_FOUND_CODE ? 'notFound' : 'unavailable'
    if (status === 429) return 'rateLimited'
    if (status === 501 || status >= 500) return 'unavailable'
    return 'generic'
  }
  // fetch() tarmoqqa chiqa olmadi ("Failed to fetch").
  if (err instanceof TypeError) return 'network'
  return 'generic'
}

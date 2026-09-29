// Admin panel HTTP qatlami - faqat so'rovlar, holat yo'q (holat sahifalarda).
// Hamma yo'llar `/api/v1/admin/*` (backend `require_roles("ADMIN")`: boshqalarga 403).
//
// Har bir o'qish funksiyasi ixtiyoriy `signal` oladi: filtr tez-tez o'zgaradi
// (sana, kanal, qidiruv) va eski so'rovning javobi yangisidan KEYIN kelib, ekranni
// eski ma'lumot bilan bosib qo'ymasligi kerak - sahifa oldingisini bekor qiladi.

import { apiFetch } from '../api/http'
import type {
  AdminChatPage,
  AdminConnector,
  AdminMe,
  AdminOverview,
  AdminSearch,
  AdminSystem,
  AdminUsage,
  AdminUser,
  AdminUserDetail,
  AdminUserList,
  AdminUserUpdate,
  RangeParams,
  ReportDetail,
  ReportPage,
  ReportQuery,
  ReportUpdate,
  SignoutResult,
  TelegramUnlinked,
  TurnDetail,
  TurnPage,
  TurnQuery,
  UserQuery,
} from './types'

const BASE = '/api/v1/admin'

type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[]

/**
 * `?a=1&b=x` - bo'sh qiymatlar (undefined, null, '') tashlab yuboriladi: backend
 * "berilmagan" va "bo'sh" ni farqlaydi (`?q=` - 422 bo'lishi mumkin), URL ham toza.
 * `false` saqlanadi - u ma'noli qiymat (`reported=false`).
 */
export function buildQuery(params: object = {}): string {
  const sp = new URLSearchParams()
  for (const [key, raw] of Object.entries(params as Record<string, QueryValue>)) {
    if (raw === undefined || raw === null || raw === '') continue
    if (Array.isArray(raw)) {
      for (const v of raw) if (v !== '' && v !== null && v !== undefined) sp.append(key, String(v))
      continue
    }
    if (typeof raw === 'number' && !Number.isFinite(raw)) continue
    sp.append(key, String(raw))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

const seg = (v: string | number) => encodeURIComponent(String(v))

function get<T>(path: string, params?: object, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(`${BASE}${path}${buildQuery(params)}`, { signal })
}

function send<T>(method: 'POST' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(`${BASE}${path}`, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

/* ---- umumiy ko'rinish ---- */

/** KPI, faollik, kanallar, yo'nalishlar, kechikish, top hujjatlar, so'nggi xabarlar. */
export function getOverview(params: RangeParams = {}, signal?: AbortSignal): Promise<AdminOverview> {
  return get<AdminOverview>('/overview', params, signal)
}

/* ---- savollar va suhbatlar ---- */

/** Savollar - yangisi birinchi; keyingi sahifa: `{ ...params, cursor: page.nextCursor }`. */
export function listTurns(params: TurnQuery = {}, signal?: AbortSignal): Promise<TurnPage> {
  return get<TurnPage>('/turns', params, signal)
}

/** Bitta savolning to'liq izi. */
export function getTurn(id: string, signal?: AbortSignal): Promise<TurnDetail> {
  return get<TurnDetail>(`/turns/${seg(id)}`, undefined, signal)
}

/** Suhbatlar (chat_id bo'yicha guruh) - savollar bilan bir xil filtrlar. */
export function listChats(params: TurnQuery = {}, signal?: AbortSignal): Promise<AdminChatPage> {
  return get<AdminChatPage>('/chats', params, signal)
}

/* ---- xabarlar ---- */

/** `counts` - holat yorliqlari uchun, `status` filtrisiz. */
export function listReports(params: ReportQuery = {}, signal?: AbortSignal): Promise<ReportPage> {
  return get<ReportPage>('/reports', params, signal)
}

export function getReport(id: string, signal?: AbortSignal): Promise<ReportDetail> {
  return get<ReportDetail>(`/reports/${seg(id)}`, undefined, signal)
}

/** Holat va/yoki admin izohi (auditga yoziladi). */
export function updateReport(id: string, body: ReportUpdate): Promise<ReportDetail> {
  return send<ReportDetail>('PATCH', `/reports/${seg(id)}`, body)
}

/* ---- foydalanuvchilar ---- */

/** Katalog: SSO ∪ users.yaml ∪ tarixdagi odamlar; statistika tanlangan oraliq bo'yicha. */
export function listUsers(params: UserQuery = {}, signal?: AbortSignal): Promise<AdminUserList> {
  return get<AdminUserList>('/users', params, signal)
}

/** Varaq: statistika, ulanishlar, Telegram, so'nggi savollar, audit. */
export function getUser(
  actorId: number,
  params: Pick<RangeParams, 'from' | 'to'> = {},
  signal?: AbortSignal,
): Promise<AdminUserDetail> {
  return get<AdminUserDetail>(`/users/${seg(actorId)}`, params, signal)
}

/** Rollar (`null` - manbaga qaytarish), bloklash, izoh. Himoyalar serverda (409). */
export function updateUser(actorId: number, body: AdminUserUpdate): Promise<AdminUser> {
  return send<AdminUser>('PATCH', `/users/${seg(actorId)}`, body)
}

/** Barcha sessiyalarni tugatadi (token versiyasi +1) va Telegram ulanishlarini uzadi. */
export function signOutUser(actorId: number): Promise<SignoutResult> {
  return send<SignoutResult>('POST', `/users/${seg(actorId)}/signout`)
}

export function disconnectUserConnector(actorId: number, platform: string): Promise<AdminConnector> {
  return send<AdminConnector>('DELETE', `/users/${seg(actorId)}/connectors/${seg(platform)}`)
}

export function unlinkUserTelegram(actorId: number): Promise<TelegramUnlinked> {
  return send<TelegramUnlinked>('DELETE', `/users/${seg(actorId)}/telegram`)
}

/* ---- foydalanish, tizim ---- */

export function getUsage(params: RangeParams = {}, signal?: AbortSignal): Promise<AdminUsage> {
  return get<AdminUsage>('/usage', params, signal)
}

export function getSystem(signal?: AbortSignal): Promise<AdminSystem> {
  return get<AdminSystem>('/system', undefined, signal)
}

/* ---- qidiruv, nishon ---- */

/** ⌘K: odamlar, savollar, xabarlar - har biridan 5 tagacha. */
export function searchAdmin(q: string, signal?: AbortSignal): Promise<AdminSearch> {
  return get<AdminSearch>('/search', { q: q.trim() }, signal)
}

/** Arzon so'rov: menyudagi "yangi xabarlar" nishoni uchun davriy chaqiriladi. */
export function getAdminMe(signal?: AbortSignal): Promise<AdminMe> {
  return get<AdminMe>('/me', undefined, signal)
}

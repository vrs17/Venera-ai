// Admin panel HTTP qatlami - faqat so'rovlar, holat yo'q (holat sahifalarda).
// Hamma yo'llar `/api/v1/admin/*` (backend `require_roles("ADMIN")`: boshqalarga 403).
//
// Har bir o'qish funksiyasi ixtiyoriy `signal` oladi: filtr tez-tez o'zgaradi
// (sana, kanal, qidiruv) va eski so'rovning javobi yangisidan KEYIN kelib, ekranni
// eski ma'lumot bilan bosib qo'ymasligi kerak - sahifa oldingisini bekor qiladi.

import { apiFetch } from '../api/http'
import type {
  AdminBrain,
  BrainFeatureUpdate,
  BrainShadow,
  AdminChatPage,
  AdminConnector,
  AdminEngines,
  AdminMe,
  AdminOverview,
  AdminSearch,
  AdminSystem,
  AdminUsage,
  AdminUser,
  AdminUserDetail,
  AdminUserList,
  AdminUserUpdate,
  EngineAccessRemoved,
  EngineAccessRow,
  EngineAccessUpdate,
  EnginePolicyUpdate,
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
import type { OsMapData, ProbeResult } from './osmap/types'

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

function send<T>(method: 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(`${BASE}${path}`, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

/* ---- AI ko'chirish (miya flag'lari) ---- */

/** Har funksiya: sozlangan va hozir ishlayotgan holat, agent holati. `refresh` - imkoniyatlar darhol. */
export function getBrain(refresh = false, signal?: AbortSignal): Promise<AdminBrain> {
  return get<AdminBrain>('/engines/brain', refresh ? { refresh: true } : undefined, signal)
}

export function putBrain(feature: string, body: BrainFeatureUpdate): Promise<AdminBrain> {
  return send<AdminBrain>('PUT', `/engines/brain/${seg(feature)}`, body)
}

export function getBrainShadow(days = 7, signal?: AbortSignal): Promise<BrainShadow> {
  return get<BrainShadow>('/engines/brain/shadow', { days }, signal)
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

/* ---- yordamchi versiyalari ---- */

/** Katalog, umumiy siyosat (va `.env` boshlang'ichi), hozir nima ishlaydi, 7 kunlik
 *  statistika va alohida ruxsatlar - bitta so'rovda (sahifa kichik, filtr yo'q). */
export function getEngines(signal?: AbortSignal): Promise<AdminEngines> {
  return get<AdminEngines>('/engines', undefined, signal)
}

/** "Hammaga" va kanal sozlamalari. Javob - yangi to'liq holat (sahifa shu bilan yangilanadi). */
export function putEnginePolicy(body: EnginePolicyUpdate): Promise<AdminEngines> {
  return send<AdminEngines>('PUT', '/engines/policy', body)
}

/** Odamga versiyalar (yaratish ham, o'zgartirish ham). Katalogda yo'q odam - 404. */
export function putEngineAccess(actorId: number, body: EngineAccessUpdate): Promise<EngineAccessRow> {
  return send<EngineAccessRow>('PUT', `/engines/access/${seg(actorId)}`, body)
}

/** Odam umumiy siyosatga qaytadi. Ikki marta bosish zararsiz (`removed: false`). */
export function deleteEngineAccess(actorId: number): Promise<EngineAccessRemoved> {
  return send<EngineAccessRemoved>('DELETE', `/engines/access/${seg(actorId)}`)
}

/* ---- foydalanish, tizim ---- */

export function getUsage(params: RangeParams = {}, signal?: AbortSignal): Promise<AdminUsage> {
  return get<AdminUsage>('/usage', params, signal)
}

export function getSystem(signal?: AbortSignal): Promise<AdminSystem> {
  return get<AdminSystem>('/system', undefined, signal)
}

/* ---- tizim xaritasi va jonli sinovlar ---- */

/** Xarita: oqimlar, qadamlar, kod va promptlar (ichki - faqat ADMIN, statik fayl emas). */
export function getOsMap(signal?: AbortSignal): Promise<OsMapData> {
  return get<OsMapData>('/osmap', undefined, signal)
}

/** O'qiydigan sinovlar (`agent`, `health`) - GET, tanasiz. */
export function getProbe(name: 'agent' | 'health', signal?: AbortSignal): Promise<ProbeResult> {
  return get<ProbeResult>(`/probe/${name}`, undefined, signal)
}

/** JSON tanali sinov (`tts-text`, `wake`, `hold`, `mask`, `brain/<funksiya>`). */
export function runProbe(path: string, body: unknown, signal?: AbortSignal): Promise<ProbeResult> {
  return apiFetch<ProbeResult>(`${BASE}/probe/${path}`, { method: 'POST', body: JSON.stringify(body), signal })
}

/** STT sinovi - multipart: ovoz paneli yuboradigan AYNI fayl (16 kHz WAV). */
export function runSttProbe(form: FormData, signal?: AbortSignal): Promise<ProbeResult> {
  return apiFetch<ProbeResult>(`${BASE}/probe/stt`, { method: 'POST', body: form, signal })
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

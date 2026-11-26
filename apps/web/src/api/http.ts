// Generic backend client for the Venera AI contract. A single fetch wrapper that
// attaches the Bearer session token and turns the backend's uniform error
// envelope ({timestamp,status,error,message,path}) into a typed ApiError.
//
// BASE_URL is empty by default so requests are relative and a proxy forwards
// /api to Spring Boot — Vite's dev proxy locally, nginx in production (see
// deploy/nginx.conf). Matches the repo's existing VITE_API_BASE convention
// (src/api.ts). Set VITE_API_BASE to an absolute origin only for direct/CORS mode.

import { appToken, forgetAppToken } from '../appBridge'
import type { ApiErrorResponse } from '../types'

export const BASE_URL = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/+$/, '')

// Opaque session token (not a JWT). Stored in localStorage so the session is
// shared across tabs/windows and survives until explicit logout — the contract
// suggested sessionStorage, but that's per-tab, so opening the app in a new
// window would force a needless re-login. The `storage` event (App.vue) keeps
// other tabs in sync on login/logout. Wrapped in try/catch because storage can
// throw in private-mode / sandboxed contexts.
export const TOKEN_KEY = 'venera_token'

export function getToken(): string | null {
  // Mobil ilova ichida (/barno, `appBridge.ts`): ilova bergan token - faqat xotirada, localStorage'dan ustun.
  const fromApp = appToken()
  if (fromApp) return fromApp
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}
export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* storage unavailable */
  }
}
export function clearToken(): void {
  forgetAppToken()
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

// Kanal: backend analitikasi va DVIGATEL tanlovi (`HRM_ASSISTANT_ENGINE_BY_CHANNEL`)
// so'rovni shu sarlavha bo'yicha ajratadi. Web - `web`; Telegram Mini App
// (`src/tg/main.ts`) ishga tushganda `setClientChannel('miniapp')` chaqiradi.
// Bitta joyda: Mini App ham ishlatadigan to'g'ridan-to'g'ri fetch'lar (`chat.api.ts`,
// `tts.api.ts`) ham shuni o'qiydi - aks holda ular Mini App'dan "web" bo'lib ketardi.
export const CLIENT_HEADER = 'X-Venera-Client'
let channel = 'web'

export function setClientChannel(value: 'web' | 'miniapp' | 'desktop'): void {
  channel = value
}

export function clientChannel(): string {
  return channel
}

export class ApiError extends Error {
  status?: number
  /** Machine-readable code from the envelope's `error` field (e.g. ACTOR_ACCESS_CONFLICT). */
  code?: string
  path?: string
  body?: ApiErrorResponse
  constructor(message: string, body?: ApiErrorResponse) {
    super(message)
    this.name = 'ApiError'
    this.body = body
    this.status = body?.status
    this.code = body?.error
    this.path = body?.path
  }
}

// Current UI locale for the Accept-Language header. The backend ignores it
// today (always English), but sending it means error messages localize for free
// once the backend honours it. Reads the locale vue-i18n persisted.
function acceptLanguage(): string {
  try {
    return localStorage.getItem('venera_locale') || 'uz'
  } catch {
    return 'uz'
  }
}

async function request(path: string, options: RequestInit, accept: string): Promise<Response> {
  const token = getToken()
  const headers: Record<string, string> = {
    Accept: accept,
    'Accept-Language': acceptLanguage(),
    // Kanal: backend analitikasi so'rovni shu sarlavha bo'yicha "web" deb yozadi
    // (Mini App `miniapp` yuboradi). Chaqiruvchi o'z qiymatini berishi mumkin.
    [CLIENT_HEADER]: channel,
    ...((options.headers as Record<string, string>) || {}),
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json; charset=utf-8'
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers })

  if (!response.ok) {
    let body: ApiErrorResponse | undefined
    try {
      body = (await response.json()) as ApiErrorResponse
    } catch {
      /* non-JSON / empty error body */
    }
    throw new ApiError(body?.message || `Request failed (${response.status})`, body)
  }
  return response
}

/** Matn qaytaradigan yo'llar (masalan yig'ilish xulosasining Markdown eksporti). */
export async function apiText(path: string, options: RequestInit = {}): Promise<string> {
  return (await request(path, options, 'text/markdown, text/plain, */*')).text()
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await request(path, options, 'application/json')

  // Some endpoints (logout, downloads) may return no JSON body.
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) return undefined as T
  return (await response.json()) as T
}

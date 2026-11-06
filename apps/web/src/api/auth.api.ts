// Auth endpoint wrappers — pure HTTP, no state side effects. Token storage and
// routing live in the auth store/composable that consumes these.

import { BASE_URL, apiFetch } from './http'
import type {
  AuthUser,
  ChangePasswordRequest,
  ChangePasswordResponse,
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  SignupRequest,
  SignupResponse,
  SsoConfig,
} from '../types'

/** Kirish sahifasi uchun: SSO yoqilganmi, parol shakli bormi. Ochiq endpoint. */
export function ssoConfig(): Promise<SsoConfig> {
  return apiFetch<SsoConfig>('/api/v1/auth/sso/config')
}

/** Brauzerni Keycloak'ga yuboradigan to'liq manzil. `returnTo` - kirishdan keyin
 *  qaytiladigan ilova yo'li (server faqat `/...` ko'rinishini qabul qiladi). */
export function ssoStartUrl(startPath: string, returnTo: string | null, channel: string): string {
  const params = new URLSearchParams({ channel })
  if (returnTo && returnTo !== '/') params.set('return', returnTo)
  return `${BASE_URL}${startPath}?${params.toString()}`
}

/** Callback bergan bir martalik kodni sessiyaga almashtirish. Kod ikki marta ishlamaydi. */
export function ssoExchange(code: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/v1/auth/sso/exchange', { method: 'POST', body: JSON.stringify({ code }) })
}

/** Create an account. Backend emails a temporary password; no password is sent here. */
export function signup(data: SignupRequest): Promise<SignupResponse> {
  return apiFetch<SignupResponse>('/api/v1/auth/signup', { method: 'POST', body: JSON.stringify(data) })
}

/** Authenticate. Returns the session token + whether a forced password change is pending. */
export function login(data: LoginRequest): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(data) })
}

/** Replace the temporary password with the user's own (first-login flow). */
export function changePassword(data: ChangePasswordRequest): Promise<ChangePasswordResponse> {
  return apiFetch<ChangePasswordResponse>('/api/v1/auth/change-password', { method: 'POST', body: JSON.stringify(data) })
}

/** Verify the token and restore the current user (app bootstrap / route guard). */
export function me(): Promise<AuthUser> {
  return apiFetch<AuthUser>('/api/v1/auth/me')
}

/** Revoke the server session. Callers clear the local token regardless of outcome. */
export function logout(): Promise<LogoutResponse> {
  return apiFetch<LogoutResponse>('/api/v1/auth/logout', { method: 'POST' })
}

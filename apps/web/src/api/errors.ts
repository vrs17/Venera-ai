// Backend error envelopes are English-only today (the API ignores
// Accept-Language). This shim maps the known, stable server messages to
// localized strings so common auth/document failures match the UI language.
// Unmapped errors fall back to the server's own message (better an accurate
// English string than a wrong localized guess). Remove once the backend
// localizes its messages.

import { ApiError } from './http'
import type { MsgKey } from '../i18n'

type Translate = (key: MsgKey) => string

export function localizeApiError(err: unknown, t: Translate): string {
  if (err instanceof ApiError) {
    const raw = err.body?.message || err.message || ''
    const m = raw.toLowerCase()
    if (m.includes('invalid email or password')) return t('invalidCredentials')
    if (m.includes('already exists')) return t('errEmailExists')
    if (m.includes('password change is required')) return t('errPasswordChangeRequired')
    if (m.includes('invalid or expired session')) return t('errSessionExpired')
    if (m.includes('invalid json') || m.includes('missing or invalid')) return t('errInvalidRequest')
    if (m.includes('unsupported document type')) return t('errUnsupportedDocument')
    return raw || t('networkError')
  }
  if (err instanceof Error && err.message) return err.message
  return t('networkError')
}

/** Kirish/parol sahifalari tanib, o'z matnini ko'rsatadigan xatolar. Nomlari
 *  `shell.auth.*` kalitlari bilan bir xil. */
export type AuthErrorKind = 'wrongCredentials' | 'blocked' | 'accountSetup' | 'network' | 'unavailable'

/**
 * Backend kirish xatolarini O'ZBEKCHA qaytaradi (`api/v1/auth.py`, `services/sso.py`),
 * ya'ni boshqa tillarda ham o'zbekcha matn chiqardi. Barqaror bo'laklarini taniymiz va
 * sahifa tilida ko'rsatamiz. Tanilmagani `null` - chaqiruvchi `localizeApiError` ga
 * qaytadi (server matni o'zgarishsiz ko'rinadi, avvalgidek).
 */
export function authErrorKind(err: unknown): AuthErrorKind | null {
  if (err instanceof ApiError) {
    const m = (err.body?.message || err.message || '').toLowerCase()
    // Keycloak: parol to'g'ri, lekin hisobda tugallanmagan amal bor.
    if (m.includes('not fully set up') || m.includes('tugallanmagan')) return 'accountSetup'
    if (m.includes('login yoki parol') || m.includes('invalid email or password')) return 'wrongCredentials'
    if (m.includes('bloklangan')) return 'blocked'
    // nginx 502/503/504 - JSON konvert yo'q, faqat "Request failed (502)" qoladi.
    if (!err.body && /^request failed \(5\d\d\)$/.test(m)) return 'unavailable'
    return null
  }
  // fetch() tarmoqqa chiqa olmadi: brauzerning xom "Failed to fetch" / "Load failed"
  // matni foydalanuvchiga hech narsa demaydi.
  if (err instanceof TypeError) return 'network'
  return null
}

/** Kirish sahifalari uchun: tanilgan xato - `shell.auth.*`, qolgani - `localizeApiError`. */
export function localizeAuthError(err: unknown, t: (key: string) => string): string {
  const kind = authErrorKind(err)
  return kind ? t(`shell.auth.${kind}`) : localizeApiError(err, t)
}

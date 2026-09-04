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

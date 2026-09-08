// Speech-to-text. The browser records audio and posts it here; the backend
// proxies to the on-prem STT router.
//
// Why through our backend and not straight to the router: the router lives on
// an internal address the browser cannot reach — over HTTPS it is blocked as
// mixed content, over HTTP it is blocked by CORS, and either way the internal
// host would be exposed to the browser. The proxy also means the request
// carries the session token.

import { apiFetch } from './http'
import type { Transcript } from '../types'

/** The microphone needs a secure context: HTTPS, or localhost. Plain HTTP on a
 *  LAN address does NOT qualify, and there `navigator.mediaDevices` is simply
 *  `undefined` — no prompt, no error. Callers must check this first, otherwise
 *  the failure looks like a bug in our code. */
export function micAvailable(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function' &&
    (window.isSecureContext ?? false)
  )
}

/** The same page over HTTPS, for the "microphone needs HTTPS" hint. */
export function secureUrl(): string {
  return window.location.href.replace(/^http:/, 'https:')
}

export async function transcribe(
  audio: Blob,
  language: string,
  signal?: AbortSignal,
): Promise<Transcript> {
  const form = new FormData()
  // The extension matters: the router picks its decoder from the filename when
  // the content type is generic.
  const ext = audio.type.includes('ogg') ? 'ogg' : audio.type.includes('wav') ? 'wav' : 'webm'
  form.append('file', audio, `speech.${ext}`)
  form.append('language', language)
  // apiFetch leaves FormData alone so the browser sets the multipart boundary.
  return apiFetch<Transcript>('/api/v1/stt/transcribe', { method: 'POST', body: form, signal })
}

/** True when the page's Permissions-Policy forbids the microphone. Then
 *  getUserMedia() rejects with NotAllowedError WITHOUT ever showing a prompt,
 *  and no browser setting can override it — it is a server header, so the
 *  only fix is on the server. Telling the user to check the padlock menu in
 *  that case sends them on an errand that cannot succeed. */
export function micBlockedByPolicy(): boolean {
  type Policy = { allowsFeature(feature: string): boolean }
  const doc = document as Document & { permissionsPolicy?: Policy; featurePolicy?: Policy }
  const policy = doc.permissionsPolicy ?? doc.featurePolicy
  if (!policy) return false // browser cannot tell us; let getUserMedia decide
  try {
    return !policy.allowsFeature('microphone')
  } catch {
    return false
  }
}

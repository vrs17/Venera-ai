// Speech-to-text. The browser records audio and posts it here; the backend
// proxies to the on-prem STT router.
//
// Why through our backend and not straight to the router: the router lives on
// an internal address the browser cannot reach — over HTTPS it is blocked as
// mixed content, over HTTP it is blocked by CORS, and either way the internal
// host would be exposed to the browser. The proxy also means the request
// carries the session token.

import { ApiError, apiFetch } from './http'
import { toWav16k } from './wav'
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

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const id = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => { clearTimeout(id); reject(signal.reason ?? new DOMException('aborted', 'AbortError')) }, { once: true })
  })

export interface WakeVerdict {
  matched: boolean
  text: string
  reason: string
  /** False when the check could not be performed at all — STT down, network
   *  gone. That is NOT "not the wake word", and callers must not treat it as
   *  a normal negative: it means try less often, not try again immediately. */
  checked: boolean
  /** The clip reached the server with speech cut into pulses and exact-zero
   *  gaps between them — a noise gate somewhere before the browser (OS audio
   *  enhancement, microphone driver, headset software). "Not the wake word"
   *  then says nothing about the word; only the person can switch that gate
   *  off, so the UI has to tell them. */
  distorted: boolean
}

/** One wake-word check. The verdict comes from the server, which also records
 *  the clip, the transcript and the reason — so "it only wakes if you say it
 *  perfectly" can be studied from real data rather than guessed at.
 *
 *  Never throws (except on abort): nobody asked for anything yet, so a full
 *  queue or a bad clip is simply "did not wake". */
export async function checkWake(
  wav: Blob,
  language: string,
  signal?: AbortSignal,
): Promise<WakeVerdict> {
  const form = new FormData()
  form.append('file', wav, 'wake.wav')
  form.append('language', language)
  try {
    return await apiFetch<WakeVerdict>('/api/v1/stt/wake', { method: 'POST', body: form, signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    return { matched: false, text: '', reason: 'network', checked: false, distorted: false }
  }
}

export async function transcribe(
  audio: Blob,
  language: string,
  signal?: AbortSignal,
): Promise<Transcript> {
  // Always upload WAV: the uz backend rejects WebM by extension and cannot
  // decode it; WAV works on every route. Fall back to the raw blob only when
  // the browser itself cannot decode what it recorded.
  let upload = audio
  let name = 'speech.wav'
  try {
    upload = await toWav16k(audio)
  } catch {
    name = audio.type.includes('ogg') ? 'speech.ogg' : audio.type.includes('mp4') ? 'speech.m4a' : 'speech.webm'
  }
  signal?.throwIfAborted()
  return post(upload, name, language, signal)
}

async function post(
  upload: Blob,
  name: string,
  language: string,
  signal?: AbortSignal,
): Promise<Transcript> {
  const form = new FormData()
  form.append('file', upload, name)
  form.append('language', language)

  // 503 means "queue full, try shortly" (router contract). One quiet retry
  // covers the common case where a slot frees within a second; the user only
  // sees an error if it is still busy after that.
  for (let attempt = 0; ; attempt++) {
    try {
      return await apiFetch<Transcript>('/api/v1/stt/transcribe', { method: 'POST', body: form, signal })
    } catch (err) {
      if (attempt === 0 && err instanceof ApiError && err.status === 503) {
        await sleep(1500, signal)
        continue
      }
      throw err
    }
  }
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

// Text-to-speech. The text goes to our backend, which returns a WAV.
//
// Why through our backend and not straight to the TTS server: the same reasons
// as STT (internal address, mixed content, CORS) plus one that is specific to
// this service — it needs a `client_secret`. If the browser fetched its own
// token, that secret would sit in the JS bundle and in every network log, and
// anyone who opened devtools could drive the whole TTS fleet.
//
// The audio is WAV 8000 Hz mono — telephony grade. It plays natively in every
// browser, so no decoding is needed here.

import { ApiError, BASE_URL, getToken } from './http'
import type { ApiErrorResponse } from '../types'

/** Locales that have a voice today. The model is Uzbek-Latin only: `uz-Cyrl`
 *  would be read letter-by-letter without transliteration, and there is no
 *  ru/en voice on this server at all. Callers check this before offering
 *  playback, so no request is sent that can only fail. */
export const TTS_LOCALES: readonly string[] = ['uz']

export function canSpeak(locale: string): boolean {
  return TTS_LOCALES.includes(locale)
}

/** Text → WAV blob. Throws ApiError, so callers can map 503/504 like they do
 *  for transcription. */
export async function speak(text: string, language: string, signal?: AbortSignal): Promise<Blob> {
  const token = getToken()
  const response = await fetch(`${BASE_URL}/api/v1/tts/speak`, {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      Accept: 'audio/wav',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ text, language }),
  })

  if (!response.ok) {
    // The error path IS JSON (the uniform envelope); only the success path is
    // audio, so this parse is safe and gives the localized message.
    let body: ApiErrorResponse | undefined
    try {
      body = (await response.json()) as ApiErrorResponse
    } catch {
      /* nginx 413/504 pages have no envelope */
    }
    throw new ApiError(body?.message || `Request failed (${response.status})`, body)
  }
  return await response.blob()
}

/**
 * Plays a blob and resolves when it finishes.
 *
 * Autoplay: browsers allow playback only after a user gesture on the page. The
 * voice flow always starts with a tap on the orb, so the gesture is there — but
 * it is not guaranteed (a policy change, an embedded context), and a rejected
 * `play()` must not look like a broken feature. The rejection is reported so
 * the caller can offer a play button instead of failing silently.
 *
 * The object URL is revoked in every exit path; leaking one pins the whole WAV
 * in memory for the life of the tab.
 */
export function play(blob: Blob): { audio: HTMLAudioElement; done: Promise<void>; stop: () => void } {
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  let settled = false
  let finish: (err?: unknown) => void = () => {}

  const done = new Promise<void>((resolve, reject) => {
    finish = (err?: unknown) => {
      // Guarded: `ended` then `error` (or a stop during playback) would
      // otherwise revoke twice and settle an already-settled promise.
      if (settled) return
      settled = true
      audio.onended = null
      audio.onerror = null
      URL.revokeObjectURL(url)
      if (err) reject(err)
      else resolve()
    }
    audio.onended = () => finish()
    audio.onerror = () => finish(new Error('audio playback failed'))
    audio.play().catch(finish)
  })

  // Stopping must go through the SAME finish(), otherwise the caller can
  // pause the element, drop the reference, and leak the object URL — which
  // pins the whole WAV in memory for the life of the tab.
  const stop = () => {
    audio.pause()
    finish()
  }
  return { audio, done, stop }
}

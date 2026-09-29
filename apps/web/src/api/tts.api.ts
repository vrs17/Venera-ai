// Text-to-speech, streamed.
//
// Why through our backend and not straight to the TTS server: the same reasons
// as STT (internal address, mixed content, CORS) plus one that is specific to
// this service — it needs a `client_secret`. If the browser fetched its own
// token, that secret would sit in the JS bundle and in every network log, and
// anyone who opened devtools could drive the whole TTS fleet.
//
// WHY STREAMING. Synthesising a 19-second message takes ~11 s end to end; the
// streaming route delivers its first bytes in ~1.1 s and stays ahead of
// playback from there. The difference is the difference between an assistant
// that answers and one that appears to have hung.
//
// WHY RAW PCM AND A HAND-BUILT PLAYER. The obvious approach — point an <audio>
// element at the response — cannot work here. `<audio src>` issues a GET and
// cannot carry the Authorization header, and MediaSource (the usual way to feed
// an element progressively) does not accept PCM or WAV at all, only segmented
// mp4/webm. Asking the server for `format=wav` instead does not help: it does
// not know the total length when the stream opens, so it writes 0xFFFFFFFF into
// both size fields and players report a 74-hour file. So the bytes arrive as
// headerless 16-bit PCM and are scheduled by hand on an AudioContext, which
// wants exactly that anyway.

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

/** Fallback if the server does not say. The current deployment is 8 kHz
 *  (telephony), but that is a deployment choice, not a constant. */
const FALLBACK_RATE = 8000
/** Jitter buffer before the first buffer starts. Long enough that a late
 *  second chunk does not produce an immediate gap, short enough not to give
 *  back the latency the streaming route just won. */
const LEAD_S = 0.12

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (err: unknown) => void
}

/** A promise whose settle functions are needed outside its executor. Written
 *  out rather than assigned from inside `new Promise`, which TypeScript
 *  cannot see as a definite assignment. */
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

export interface Playback {
  /** Resolves when the last audio has finished, or when stopped. Rejects only
   *  if the stream fails before any audio played. */
  done: Promise<void>
  /** Stops playback and releases the audio context. Safe to call twice. */
  stop: () => void
  /** The full audio as a WAV blob once the stream finishes — for a replay
   *  button. Null if the stream was stopped or failed. */
  recorded: Promise<Blob | null>
}

/**
 * Speaks `text`, starting as soon as the first bytes arrive.
 *
 * Resolves once the response headers are in, which is also the point where
 * every server-side error has already surfaced: the TTS service validates and
 * synthesises the first chunk BEFORE sending headers, so a bad voice, an empty
 * text or a GPU failure arrives as an ordinary HTTP status rather than as a
 * truncated 200. Failures after that point can only cut the connection, and
 * those are reported through `done`.
 */
export async function speakStream(
  text: string,
  language: string,
  signal?: AbortSignal,
  /** Playback starts only after this settles — the REQUEST does not wait.
   *
   *  Used to queue the answer behind a holding clip without paying for it:
   *  the TTS request goes out the moment the answer is ready and its audio
   *  buffers in the response body while the clip finishes, so playback can
   *  start the instant the clip ends instead of ~1.1 s (measured TTS time to
   *  first audio) after it. */
  after?: Promise<unknown>,
  /** O'qilayotgan javobning savol kaliti (`X-Venera-Turn`) - admin izida ovoz shu
   *  savolga bog'lanadi. Yo'q bo'lsa server alohida yozuv ochadi. */
  turnId?: string | null,
): Promise<Playback> {
  const token = getToken()
  const response = await fetch(`${BASE_URL}/api/v1/tts/speak`, {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      Accept: 'audio/L16, */*',
      // Kanal statistikasi: sarlavhasiz so'rovni server "API" deb hisoblaydi.
      'X-Venera-Client': 'web',
      ...(turnId ? { 'X-Venera-Turn': turnId } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ text, language }),
  })

  if (!response.ok || !response.body) {
    // The error path IS JSON (the uniform envelope); only the success path is
    // audio, so this parse is safe and gives the localized message.
    let body: ApiErrorResponse | undefined
    try {
      body = (await response.json()) as ApiErrorResponse
    } catch {
      /* nginx 502/504 pages have no envelope */
    }
    throw new ApiError(body?.message || `Request failed (${response.status})`, body)
  }

  const rate = rateOf(response)
  // The body keeps buffering while we wait; a failed gate must not cost the
  // answer, so its rejection is swallowed here.
  if (after) await after.catch(() => undefined)
  return playPcmStream(response.body, rate, signal)
}

function rateOf(response: Response): number {
  const header = Number(response.headers.get('X-Venera-Sample-Rate'))
  if (Number.isFinite(header) && header > 0) return header
  // `audio/L16; rate=8000; channels=1`
  const fromType = /rate=(\d+)/.exec(response.headers.get('Content-Type') || '')
  return fromType ? Number(fromType[1]) : FALLBACK_RATE
}

/**
 * Schedules incoming PCM back to back on an AudioContext.
 *
 * Each chunk becomes its own AudioBuffer started at an absolute time, rather
 * than played on arrival: `start(when)` is sample-accurate, so consecutive
 * buffers join without the click a "play it now" loop produces. The running
 * `nextAt` is clamped to the current time, so a chunk that arrives too late
 * leaves an audible gap instead of playing over its predecessor.
 */
function playPcmStream(body: ReadableStream<Uint8Array>, rate: number, signal?: AbortSignal): Playback {
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  const ctx = new Ctor()
  // Created without a click in the wake-word path. Autoplay policy allows this
  // once microphone permission is granted, which that path always has, but
  // resume() is still needed to leave the 'suspended' state.
  void ctx.resume()

  const reader = body.getReader()
  const sources = new Set<AudioBufferSourceNode>()
  const collected: Int16Array[] = []
  let nextAt = 0
  let stopped = false
  // A holder rather than a bare `let`: the only assignment happens inside
  // `schedule()`, and TypeScript narrows a `let` to its initializer when it
  // cannot see the nested function run.
  const latest: { source: AudioBufferSourceNode | null } = { source: null }
  /** One trailing byte when a 16-bit sample straddles two chunks. */
  let odd: Uint8Array | null = null

  const doneGate = deferred<void>()
  const recordedGate = deferred<Blob | null>()
  const { promise: done, resolve: resolveDone, reject: rejectDone } = doneGate
  const { promise: recorded, resolve: resolveRecorded } = recordedGate

  function stop() {
    if (stopped) return
    stopped = true
    void reader.cancel().catch(() => {})
    for (const source of sources) {
      source.onended = null
      try { source.stop() } catch { /* not started, or already stopped */ }
    }
    sources.clear()
    if (ctx.state !== 'closed') void ctx.close()
    resolveRecorded(null)
    resolveDone()
  }

  signal?.addEventListener('abort', stop, { once: true })

  function schedule(pcm: Int16Array) {
    if (!pcm.length || stopped) return
    const buffer = ctx.createBuffer(1, pcm.length, rate)
    const channel = buffer.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)
    const at = Math.max(nextAt, ctx.currentTime + (nextAt === 0 ? LEAD_S : 0))
    source.start(at)
    nextAt = at + buffer.duration
    sources.add(source)
    source.onended = () => sources.delete(source)
    latest.source = source
  }

  void (async () => {
    try {
      for (;;) {
        const { done: finished, value } = await reader.read()
        if (finished || stopped) break
        if (!value?.length) continue

        // Re-join a sample split across chunk boundaries; dropping the odd
        // byte instead would shift every following sample by one byte and
        // turn the rest of the stream into noise.
        let bytes = value
        if (odd) {
          const merged = new Uint8Array(odd.length + value.length)
          merged.set(odd, 0)
          merged.set(value, odd.length)
          bytes = merged
          odd = null
        }
        const usable = bytes.length - (bytes.length % 2)
        if (usable < bytes.length) odd = bytes.slice(usable)
        if (!usable) continue

        // A copy, not a view: `bytes` may share a buffer the reader reuses,
        // and the samples are kept for the replay blob.
        const pcm = new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + usable))
        collected.push(pcm)
        schedule(pcm)
      }
      if (stopped) return
      resolveRecorded(toWav(collected, rate))
      const last = latest.source
      if (!last) {
        // The stream ended without a single sample.
        resolveDone()
        if (ctx.state !== 'closed') void ctx.close()
        return
      }
      last.onended = () => {
        sources.delete(last)
        if (ctx.state !== 'closed') void ctx.close()
        resolveDone()
      }
    } catch (err) {
      if (stopped) return
      resolveRecorded(collected.length ? toWav(collected, rate) : null)
      const last = latest.source
      if (last) {
        // Some audio is already playing and scheduled; let it finish rather
        // than cutting the sentence off for an error the person cannot act on.
        last.onended = () => {
          if (ctx.state !== 'closed') void ctx.close()
          resolveDone()
        }
      } else {
        if (ctx.state !== 'closed') void ctx.close()
        rejectDone(err)
      }
    }
  })()

  return { done, stop, recorded }
}

/** Wraps collected PCM in a real WAV header, for the replay button. */
function toWav(parts: Int16Array[], rate: number): Blob {
  let samples = 0
  for (const part of parts) samples += part.length
  const bytes = samples * 2
  const out = new ArrayBuffer(44 + bytes)
  const view = new DataView(out)
  const ascii = (at: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(at + i, text.charCodeAt(i))
  }
  ascii(0, 'RIFF')
  view.setUint32(4, 36 + bytes, true)
  ascii(8, 'WAVE')
  ascii(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)          // PCM
  view.setUint16(22, 1, true)          // mono
  view.setUint32(24, rate, true)
  view.setUint32(28, rate * 2, true)   // byte rate
  view.setUint16(32, 2, true)          // block align
  view.setUint16(34, 16, true)         // bits
  ascii(36, 'data')
  view.setUint32(40, bytes, true)
  const pcm = new Int16Array(out, 44)
  let at = 0
  for (const part of parts) {
    pcm.set(part, at)
    at += part.length
  }
  return new Blob([out], { type: 'audio/wav' })
}

/**
 * Plays a complete blob and resolves when it finishes. Used for the prepared
 * greeting and the replay button, where the whole file is already in hand.
 *
 * Autoplay: browsers allow playback only after a user gesture on the page, or
 * once microphone permission is granted — both hold on the paths that call
 * this. A rejected `play()` is still reported so the caller can offer a button
 * instead of failing silently. The object URL is revoked in every exit path;
 * leaking one pins the whole file in memory for the life of the tab.
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
  // pause the element, drop the reference, and leak the object URL.
  const stop = () => {
    audio.pause()
    finish()
  }
  return { audio, done, stop }
}


/**
 * Fetches a ready-made holding clip (`hold` frame's `clip`).
 *
 * WHY THIS EXISTS. A holding phrase is only worth saying if it costs no
 * wait. Synthesising it here would add the measured ~1.1 s of TTS, and by
 * then a fast answer has already arrived — so the backend pre-synthesises a
 * small fixed set at startup and this just plays the bytes.
 *
 * Returns null instead of throwing: a missing clip is NOT an error (the
 * service may have just restarted), and the caller falls back to speaking
 * the text. A holding phrase must never turn into a visible failure.
 */
export async function holdClip(clip: string, signal?: AbortSignal): Promise<Blob | null> {
  const token = getToken()
  try {
    const response = await fetch(`${BASE_URL}/api/v1/tts/hold/${encodeURIComponent(clip)}.wav`, {
      headers: { 'X-Venera-Client': 'web', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      signal,
      // The clip never changes (the text is in the source), so let the
      // browser keep it: after the first wait it plays from disk.
      cache: 'force-cache',
    })
    if (!response.ok) return null
    return await response.blob()
  } catch {
    return null
  }
}

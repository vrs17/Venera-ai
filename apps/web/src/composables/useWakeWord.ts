// Wake word: "Salom Venera" opens the voice panel without touching the screen.
//
// THE CONSTRAINT THAT SHAPES ALL OF THIS. Wake-word detection means the
// microphone is open the whole time the chat page is, and every scrap of speech
// is a candidate. Sending all of it to the STT router would be ruinous: the
// router carries ~10 concurrent requests for the ENTIRE fleet (web, desktop,
// call-centre), so a handful of idle browsers left open would starve everyone
// who is actually working. It would also ship every word spoken near the
// machine to a server, which is not what someone consents to by logging in.
//
// So the network is the LAST resort, behind three local gates:
//   1. Energy. Silence never leaves the browser — RMS is measured locally.
//   2. Length. "Salom Venera" is about a second. Anything under MIN_MS or over
//      MAX_MS is discarded WITHOUT a request: that single rule drops ordinary
//      conversation, phone calls and background TV, which are all far longer
//      than a wake phrase.
//   3. Cooldown. At most one request per COOLDOWN_MS, so even continuous
//      wake-length chatter cannot exceed a fixed, low request rate.
// A quiet room therefore costs exactly zero requests, and a loud one costs at
// most ~24/minute per tab rather than one per utterance.
//
// WHY RAW PCM AND NOT MediaRecorder. A wake phrase is short, and MediaRecorder
// cannot give us the audio from BEFORE we noticed the speech — by the time RMS
// crosses the threshold, "Sa-" is already gone, and a recorder started at that
// moment loses the first syllable of a two-word phrase. A ring buffer of raw
// samples keeps a pre-roll, so the clip starts before the speaker did.
// The AudioContext runs at the STT rate, so `encodeWavBytes` produces exactly
// the 16 kHz mono WAV the uz backend wants, with no decode/resample step.
//
// WHY ScriptProcessorNode, WHICH IS DEPRECATED. Its replacement, AudioWorklet,
// loads its processor from a separate module URL. Our CSP is `script-src
// 'self'` and the usual worklet trick is a blob: URL — which that policy
// blocks, silently, in production only. The deprecated node has no such
// problem and is supported everywhere we run.

import { onBeforeUnmount, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { encodeWavBytes, TARGET_RATE } from '../api/wav'
import { micAvailable, transcribeWav } from '../api/stt.api'

/** Locales whose speakers say the Uzbek wake phrase. The phrase itself is the
 *  same in both scripts — only the transcript's spelling differs, and the
 *  matcher is tolerant of that. */
export const WAKE_LOCALES: readonly string[] = ['uz', 'uz-Cyrl']

export const WAKE_STORAGE_KEY = 'venera_wake_word'

const PREROLL_S = 0.45        // samples kept from before speech was noticed
const SILENCE_MS = 700        // silence that ends an utterance
const MIN_MS = 350            // shorter than this is a cough, a click, a door
const MAX_MS = 2600           // longer than this is conversation, not a wake phrase
const COOLDOWN_MS = 2500      // hard ceiling on the request rate
const RMS_ON = 0.045          // hysteresis: a single threshold chatters at the
const RMS_OFF = 0.022         // boundary and slices one utterance into many

/** How close a word must be to count as the name. Uzbek STT will produce
 *  "vinera", "venira", "venera" for the same sound. */
const NAME = 'venera'
const NAME_DISTANCE = 2
/** Uzbek greetings, including the pieces "assalomu alaykum" breaks into. The
 *  name ALONE is deliberately not enough: "Venera" appears in ordinary
 *  sentences about the system, and opening a full-screen panel is disruptive
 *  enough that a false positive costs more than a missed wake. */
const GREETINGS = ['salom', 'assalom', 'assalomu', 'alaykum', 'aleykum', 'salomlar']

/** Levenshtein, bailing out once the distance can no longer matter. */
export function distance(a: string, b: string, max = 3): number {
  if (a === b) return 0
  if (Math.abs(a.length - b.length) > max) return max + 1
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i++) {
    const row = [i]
    let best = i
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)
      best = Math.min(best, row[j])
    }
    if (best > max) return max + 1
    prev = row
  }
  return prev[b.length]
}

/** Lowercase, drop the several apostrophes Uzbek orthography uses
 *  interchangeably (o' / oʻ / o’), and reduce to words. */
export function normalizeHeard(text: string): string {
  return text
    .toLowerCase()
    .replace(/[''`ʻʼ‘’]/g, '')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Is this transcript the wake phrase?
 *
 * Requires BOTH a greeting and the name, and rejects anything longer than a
 * short phrase — a sentence that merely mentions Venera is not a summons.
 */
export function isWakePhrase(text: string): boolean {
  const words = normalizeHeard(text).split(' ').filter(Boolean)
  if (words.length === 0 || words.length > 4) return false
  // Length floor on the candidate: without it, distance<=2 from "venera"
  // also admits "vera", "era" and other common short words.
  const named = words.some((w) => w.length >= 5 && distance(w, NAME, NAME_DISTANCE) <= NAME_DISTANCE)
  if (!named) return false
  return words.some((w) => GREETINGS.some((g) => distance(w, g, 2) <= 2))
}

export interface WakeWordOptions {
  /** The user turned the feature on. */
  enabled: Ref<boolean>
  /** Current UI locale — the wake phrase is Uzbek only. Read-only, so a
   *  `computed()` can be passed straight in. */
  locale: Readonly<Ref<string>>
  /** True while the voice panel is open; the panel owns the microphone then. */
  paused: Readonly<Ref<boolean>>
  /** Called once when the phrase is heard. */
  onWake: () => void
}

export function useWakeWord(options: WakeWordOptions) {
  const { enabled, locale, paused, onWake } = options
  /** Live and listening right now. Drives the sidebar indicator. */
  const active = ref(false)
  /** getUserMedia was refused, or there is no microphone. The toggle turns
   *  itself off rather than pretending to listen. */
  const blocked = ref(false)

  let stream: MediaStream | null = null
  let ctx: AudioContext | null = null
  let node: ScriptProcessorNode | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let aborter: AbortController | null = null

  // Ring buffer of pre-roll samples, plus the utterance being collected.
  let ring: Float32Array = new Float32Array(0)
  let ringLen = 0
  let capturing = false
  let captured: Float32Array[] = []
  let capturedLen = 0
  let quietFrames = 0
  let lastRequest = 0
  let overlong = false

  function shouldRun(): boolean {
    return (
      enabled.value &&
      !paused.value &&
      WAKE_LOCALES.includes(locale.value) &&
      micAvailable() &&
      typeof document !== 'undefined' &&
      document.visibilityState === 'visible'
    )
  }

  async function start() {
    if (active.value || !shouldRun()) return
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
    } catch {
      // Refused, or no device. Do not retry in a loop — the browser will not
      // change its mind without another user gesture.
      blocked.value = true
      enabled.value = false
      return
    }
    blocked.value = false
    try {
      // Ask for the STT rate directly: the browser resamples once, in native
      // code, and everything downstream is already in the right format.
      ctx = new AudioContext({ sampleRate: TARGET_RATE })
      const rate = ctx.sampleRate
      ring = new Float32Array(Math.ceil(PREROLL_S * rate))
      ringLen = 0
      source = ctx.createMediaStreamSource(stream)
      node = ctx.createScriptProcessor(4096, 1, 1)
      node.onaudioprocess = (event) => onFrame(event.inputBuffer.getChannelData(0), rate)
      source.connect(node)
      // A ScriptProcessorNode only runs while connected to a destination. Zero
      // gain keeps the microphone out of the speakers — connecting it directly
      // would put the room on a loop through itself.
      const mute = ctx.createGain()
      mute.gain.value = 0
      node.connect(mute)
      mute.connect(ctx.destination)
      active.value = true
    } catch {
      stop()
    }
  }

  function stop() {
    active.value = false
    capturing = false
    captured = []
    capturedLen = 0
    ringLen = 0
    overlong = false
    aborter?.abort()
    aborter = null
    if (node) {
      node.onaudioprocess = null
      node.disconnect()
      node = null
    }
    source?.disconnect()
    source = null
    if (ctx && ctx.state !== 'closed') void ctx.close()
    ctx = null
    // Every track must stop, or the browser keeps the recording indicator lit
    // and the user believes they are still being listened to.
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  function onFrame(input: Float32Array, rate: number) {
    let sum = 0
    for (const sample of input) sum += sample * sample
    const rms = Math.sqrt(sum / input.length)
    const frameMs = (input.length / rate) * 1000

    if (!capturing) {
      pushRing(input)
      if (rms > RMS_ON) {
        capturing = true
        overlong = false
        quietFrames = 0
        // Start from the pre-roll so the clip contains the whole first word.
        captured = [ringSnapshot()]
        capturedLen = captured[0].length
      }
      return
    }

    captured.push(new Float32Array(input))
    capturedLen += input.length

    if (capturedLen / rate > MAX_MS / 1000) {
      // Too long to be the wake phrase. Drop it and wait for silence before
      // arming again — this is the gate that keeps ordinary conversation off
      // the network entirely.
      overlong = true
      captured = []
      capturedLen = 0
    }

    if (rms < RMS_OFF) {
      quietFrames += frameMs
      if (quietFrames >= SILENCE_MS) {
        const clip = overlong ? null : merge(captured, capturedLen)
        capturing = false
        captured = []
        capturedLen = 0
        overlong = false
        ringLen = 0
        if (clip) void consider(clip, rate)
      }
    } else {
      quietFrames = 0
    }
  }

  function pushRing(input: Float32Array) {
    if (input.length >= ring.length) {
      ring.set(input.subarray(input.length - ring.length))
      ringLen = ring.length
      return
    }
    if (ringLen + input.length > ring.length) {
      const drop = ringLen + input.length - ring.length
      ring.copyWithin(0, drop, ringLen)
      ringLen -= drop
    }
    ring.set(input, ringLen)
    ringLen += input.length
  }

  function ringSnapshot(): Float32Array {
    return ring.slice(0, ringLen)
  }

  function merge(parts: Float32Array[], total: number): Float32Array {
    const out = new Float32Array(total)
    let at = 0
    for (const part of parts) {
      out.set(part, at)
      at += part.length
    }
    return out
  }

  async function consider(clip: Float32Array, rate: number) {
    const seconds = clip.length / rate
    if (seconds * 1000 < MIN_MS) return
    const now = performance.now()
    if (now - lastRequest < COOLDOWN_MS) return
    lastRequest = now

    aborter?.abort()
    aborter = new AbortController()
    const signal = aborter.signal
    try {
      const wav = new Blob([encodeWavBytes(clip, rate)], { type: 'audio/wav' })
      const result = await transcribeWav(wav, locale.value, signal)
      if (signal.aborted || !shouldRun()) return
      if (isWakePhrase(result.text)) {
        stop()          // release the microphone BEFORE the panel asks for it
        onWake()
      }
    } catch {
      // A failed wake check is not worth telling anyone about: the person did
      // not ask for anything yet. Errors here are also the common case when
      // the STT queue is full, and a visible error every few seconds would be
      // worse than silence.
    }
  }

  function sync() {
    if (shouldRun()) void start()
    else stop()
  }

  watch([enabled, locale, paused], sync, { immediate: true })

  const onVisibility = () => sync()
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility)
  }
  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibility)
    stop()
  })

  return { active, blocked }
}

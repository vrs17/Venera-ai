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
import { checkWake, micAvailable } from '../api/stt.api'

/** Locales whose speakers say the Uzbek wake phrase. The phrase itself is the
 *  same in both scripts — only the transcript's spelling differs, and the
 *  matcher is tolerant of that. */
export const WAKE_LOCALES: readonly string[] = ['uz', 'uz-Cyrl']

export const WAKE_STORAGE_KEY = 'venera_wake_word'

const PREROLL_S = 0.45        // samples kept from before speech was noticed
/** Silence that ends an utterance.
 *
 *  MEASURED, not guessed. With 700 ms the recorded speech in failed attempts
 *  was 0.65-0.85 s against 1.05-1.70 s in successful ones: the timer was
 *  starting during the quiet second half of "Salom Venera" and the clip was
 *  ending while the person still spoke. */
const SILENCE_MS = 950
const MIN_MS = 350            // shorter than this is a cough, a click, a door
/** Longer than this is conversation, not a wake phrase. Raised with
 *  SILENCE_MS so a fully captured phrase still fits under the gate — the two
 *  must move together, or the fix above would be undone by this one. */
const MAX_MS = 3200
const COOLDOWN_MS = 2500      // hard ceiling on the request rate
/** When the check cannot run at all — the STT backend is down — sending a
 *  clip every few seconds achieves nothing and keeps a broken service busy.
 *  The gap doubles per consecutive failure up to this ceiling, and resets the
 *  moment one check succeeds, so recovery is noticed within a minute. */
const MAX_BACKOFF_MS = 60_000
const RMS_ON = 0.045          // hysteresis: a single threshold chatters at the
/** The level below which we start counting silence.
 *
 *  MEASURED: the trailing syllables of "Venera" sit between 0.015 and 0.022,
 *  so the old 0.022 counted live speech as silence and cut the phrase in
 *  half. Lower is safe here — RMS_ON still decides when to START, so a quiet
 *  room never triggers anything; this only decides when to STOP. */
const RMS_OFF = 0.013

/** Whether a transcript is the wake phrase is decided SERVER-SIDE
 *  (`app/services/wake.py`). Two implementations of the same rules would
 *  drift, and only the server can record the clip next to its verdict —
 *  which is what makes the rules tunable from evidence instead of guesswork.
 *  Tuning them there also needs no frontend rebuild.
 */

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
  let failures = 0
  let overlong = false

  function shouldRun(): boolean {
    return (
      enabled.value &&
      !blocked.value &&
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
        audio: {
          // Noise suppression and echo cancellation are OFF on purpose.
          // They are tuned to make speech comfortable for a human on a phone
          // call, and they do that by removing exactly what a recogniser
          // needs most: low-energy consonants and the quiet ends of words.
          // "Venera" ends in one, and it is the half that kept disappearing —
          // the transcripts came back as "assalomu alaykum", the model's most
          // likely completion when the second word is gone.
          // Echo cancellation has nothing to cancel here either: the panel is
          // closed while this listens, so nothing is playing.
          echoCancellation: false,
          noiseSuppression: false,
          // Auto-gain is off for the same family of reasons. It reacts inside
          // a single word, so it lifts the quiet tail of one phrase and
          // flattens the loud start of the next, and it was pushing peaks to
          // 1.0 — measured at 0.996-1.000 on real clips, right against the
          // ceiling. The per-clip normalisation below does the same job
          // deterministically, after the fact, where it can see the whole
          // phrase and can guarantee it never clips.
          autoGainControl: false,
        },
      })
    } catch {
      // Refused, or no device. Stop trying for this session — the browser will
      // not change its mind on its own. The stored preference is deliberately
      // LEFT ON: turning it off here would mean a single accidental "Block"
      // silently disables the feature forever, even after the person fixes
      // the permission in site settings.
      blocked.value = true
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
    failures = 0
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

  /**
   * Removes what is below speech: mains hum, fan rumble, desk thumps.
   *
   * With the browser's noise suppression off (it was eating the ends of
   * words) this is what is left to do about noise, and it is the half worth
   * removing: nothing in Uzbek speech lives under ~80 Hz, so cutting there
   * costs no intelligibility while taking out the energy that both dominates
   * the noise floor and gets multiplied by the normalisation below.
   *
   * One pole, in place of a proper filter: it is a few lines, runs once per
   * clip, and the steeper response a biquad would give buys nothing here.
   */
  function highpass(clip: Float32Array, rate: number): Float32Array {
    const rc = 1 / (2 * Math.PI * 80)
    const dt = 1 / rate
    const a = rc / (rc + dt)
    const out = new Float32Array(clip.length)
    let previous = 0
    for (let i = 1; i < clip.length; i++) {
      out[i] = a * (out[i - 1] + clip[i] - previous)
      previous = clip[i]
    }
    return out
  }

  /**
   * Scales the clip so its loudest point is near full scale.
   *
   * MEASURED: in the failed attempts the name was spoken far more quietly
   * than the greeting before it, and the model replaced the quiet half with
   * its most likely guess — "Salom Venera" came back as "assalomu alaykum".
   * getUserMedia's own auto-gain adapts far too slowly for a one-second
   * phrase. Silence is left alone: amplifying room noise to full scale would
   * hand the recogniser a clip full of confident nonsense.
   */
  function normalize(clip: Float32Array): Float32Array {
    let peak = 0
    for (const sample of clip) {
      const level = Math.abs(sample)
      if (level > peak) peak = level
    }
    // 0.8, not 0.9: a little headroom means rounding on the way to 16-bit
    // never touches the ceiling. The gain ceiling matters more — at 8x a
    // clip with a quiet speaker came back with its room noise amplified
    // just as hard, which is what made the recordings unpleasant to listen
    // to without making the words any clearer.
    if (peak < 0.02 || peak >= 0.8) return clip.slice()
    const gain = Math.min(0.8 / peak, 4)
    const out = new Float32Array(clip.length)
    for (let i = 0; i < clip.length; i++) out[i] = clip[i] * gain
    return out
  }

  /**
   * Cuts the silence around the phrase, keeping a short pad.
   *
   * A clip is roughly a third speech and two thirds silence: 0.45 s of
   * pre-roll in front and up to 0.95 s of the silence that ended the turn
   * behind. Handing the recogniser that much emptiness invites it to fill
   * the space, and a wake phrase is short enough that the padding dominates.
   *
   * The threshold here is deliberately far below the VAD's: this only decides
   * where to CUT, so being too eager would clip the very syllables the change
   * above is trying to preserve.
   */
  function trim(clip: Float32Array, rate: number): Float32Array {
    const pad = Math.round(rate * 0.2)
    const win = Math.max(1, Math.round(rate * 0.02))
    let first = -1
    let last = -1
    for (let at = 0; at + win <= clip.length; at += win) {
      let sum = 0
      for (let i = at; i < at + win; i++) sum += clip[i] * clip[i]
      if (Math.sqrt(sum / win) > 0.008) {
        if (first < 0) first = at
        last = at + win
      }
    }
    if (first < 0) return clip
    return clip.subarray(Math.max(0, first - pad), Math.min(clip.length, last + pad))
  }

  async function consider(raw: Float32Array, rate: number) {
    const clip = normalize(trim(highpass(raw, rate), rate))
    const seconds = clip.length / rate
    if (seconds * 1000 < MIN_MS) return
    const now = performance.now()
    const gap = failures
      ? Math.min(COOLDOWN_MS * 2 ** failures, MAX_BACKOFF_MS)
      : COOLDOWN_MS
    if (now - lastRequest < gap) return
    lastRequest = now

    aborter?.abort()
    aborter = new AbortController()
    const signal = aborter.signal
    try {
      const wav = new Blob([encodeWavBytes(clip, rate)], { type: 'audio/wav' })
      const verdict = await checkWake(wav, locale.value, signal)
      if (signal.aborted || !shouldRun()) return
      failures = verdict.checked ? 0 : failures + 1
      if (!verdict.checked) {
        console.debug('[wake] tekshirib bo`lmadi, keyingi urinish kechroq', failures)
        return
      }
      // Useful while tuning: the console shows what was actually heard, which
      // is usually nothing like what the person thinks they said.
      if (verdict.text) console.debug('[wake]', verdict.text, '->', verdict.reason)
      if (verdict.matched) {
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

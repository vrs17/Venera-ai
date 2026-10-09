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
//
// THE CAPTURE SETTINGS ARE THE VOICE PANEL'S, DELIBERATELY. The panel's
// recordings (browser processing on, native sample rate, resampled offline)
// are the one route proven to transcribe on real machines, and Firefox
// refuses the alternative (a 16 kHz context fed by a live stream). This file
// once diverged from it — processing off — on the theory that the browser's
// noise filter was eating the quiet end of the phrase. That theory was wrong.
//
// WHAT THE RECORDINGS ACTUALLY SHOWED, AND WHAT THIS CODE CANNOT FIX. On one
// Windows/Chrome machine, quietly spoken phrases arrived GATED: speech cut
// into isolated pulses with runs of EXACT zero between them (22-59% of the
// samples inside a vowel, against 0-6% in clean speech), which the person
// heard as "very noisy" and which no recogniser can read. It happened with
// browser processing off AND on, and vanished when the same person spoke
// louder — so the gate sits upstream of the browser (OS "audio enhancement",
// microphone driver, headset software), and no getUserMedia constraint
// reaches it. The Uzbek model itself copes with genuine noise down to 0 dB
// SNR; it cannot cope with speech that is not there. What we CAN do is
// notice: the server measures that flat share on every clip (`flat` in the
// wake log) and reports it back, and `distorted` below turns it into a hint
// for the person, who is the only one able to switch the gate off.
//
// WHY ScriptProcessorNode, WHICH IS DEPRECATED. Its replacement, AudioWorklet,
// loads its processor from a separate module URL. Our CSP is `script-src
// 'self'` and the usual worklet trick is a blob: URL — which that policy
// blocks, silently, in production only. The deprecated node has no such
// problem and is supported everywhere we run.

import { onBeforeUnmount, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { encodeWavBytes, resampleTo16k, TARGET_RATE } from '../api/wav'
import { checkWake, micAvailable } from '../api/stt.api'

/** Locales whose speakers say the Uzbek wake phrase. The phrase itself is the
 *  same in both scripts — only the transcript's spelling differs, and the
 *  matcher is tolerant of that. */
export const WAKE_LOCALES: readonly string[] = ['uz', 'uz-Cyrl']

/** `_v2`: the default changed to OFF (ChatView). A new key, so a stored "on"
 *  from the on-by-default era does not keep the microphone open for anyone. */
export const WAKE_STORAGE_KEY = 'venera_wake_word_v2'

const PREROLL_S = 0.45        // samples kept from before speech was noticed
/** Silence that ends an utterance.
 *
 *  MEASURED, twice. At 700 ms the recorded speech in failed attempts ran
 *  0.65-0.85 s against 1.05-1.70 s in successful ones. At 950 ms it was still
 *  0.3-0.5 s of actual speech — one word — because people say "Salom" and
 *  pause before "Venera", and the pause ended the turn. The second half then
 *  became its own utterance and was thrown away by the cooldown below, which
 *  is why the log only ever showed "salom ..." and never the name.
 *
 *  1.4 s comfortably spans a natural pause between two words. The cost is
 *  latency after the phrase ends, and for a wake word that is the right
 *  trade: hearing it late beats not hearing it. */
const SILENCE_MS = 1400
const MIN_MS = 350            // shorter than this is a cough, a click, a door
/** Longer than this is conversation, not a wake phrase.
 *
 *  Measured on the TRIMMED clip, i.e. on speech, not on the silence that
 *  ended the turn. Measuring the raw capture instead made this fight the
 *  setting above: every extra millisecond of pause tolerance ate into the
 *  budget, so a phrase with a slightly long pause was thrown away for being
 *  "conversation" when it was mostly silence. */
const MAX_MS = 3000
/** Hard bound on how much audio one utterance may hold, so a room that never
 *  goes quiet cannot grow the buffer without limit. Deliberately far above
 *  MAX_MS: this is a memory guard, not the wake-phrase rule. */
const CAPTURE_MAX_MS = 6000
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
  /** The last clip the server saw was gated (see the header). Follows the
   *  latest verdict, so the hint disappears as soon as a clean clip arrives —
   *  which is how the person learns that whatever they changed worked. */
  const distorted = ref(false)

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

  /** Resumes a context the autoplay policy parked. Bound once per start. */
  function unlock() {
    if (ctx && ctx.state !== 'running') void ctx.resume().catch(() => {})
  }

  async function start() {
    // Guard on the stream, not on `active`: a context the browser has left
    // suspended is started but not active, and must not be started twice.
    if (stream || !shouldRun()) return
    try {
      // IDENTICAL to VoicePanel.vue, and keep it that way. Departures from
      // this line were tried and measured against the wake log and none
      // helped: turning processing off did not remove the gating described at
      // the top of this file, and turning auto-gain off buried the quieter
      // second word. The panel's transcripts are the standard; the wake path
      // has no reason to differ.
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
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
      // Native rate, resampled to 16 kHz per clip (see `consider`). A context
      // pinned to 16 kHz made the browser resample the live microphone stream
      // instead — the one step the panel never takes, and one Firefox refuses
      // altogether, throwing on the rate mismatch.
      ctx = new AudioContext()
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
      // A context created without a user gesture can be left 'suspended' by
      // the browser's autoplay policy — then onaudioprocess never fires and
      // nothing is heard, silently. So the indicator follows the REAL state
      // rather than our intent, and the first gesture on the page resumes
      // the context. On most machines a context fed by getUserMedia starts
      // running at once and none of this is needed; it is here for the rest.
      const context = ctx
      const reflect = () => { active.value = context.state === 'running' }
      context.onstatechange = reflect
      reflect()
      if (context.state !== 'running') {
        void context.resume().catch(() => {})
        document.addEventListener('pointerdown', unlock, { once: true })
        document.addEventListener('keydown', unlock, { once: true })
      }
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
    document.removeEventListener('pointerdown', unlock)
    document.removeEventListener('keydown', unlock)
    if (ctx) {
      ctx.onstatechange = null
      if (ctx.state !== 'closed') void ctx.close()
    }
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

    if (capturedLen / rate > CAPTURE_MAX_MS / 1000) {
      // Far past any wake phrase — someone is talking. Drop what we have and
      // wait for silence before arming again, so a continuous conversation
      // cannot grow this buffer without limit.
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
   * A clip is mostly silence: 0.45 s of pre-roll in front and up to 1.4 s of
   * the silence that ended the turn behind. Handing the recogniser that much
   * emptiness invites it to fill the space, and a wake phrase is short enough
   * that the padding dominates.
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
    // The cooldown is checked FIRST, before the `await` below. Two reasons.
    // It must stay a synchronous gate: with an await in front of it, two
    // utterances could both read `lastRequest` before either wrote it and
    // both go out, defeating the one rule that bounds our share of a router
    // the whole fleet depends on. And a clip inside the window is dropped
    // anyway, so resampling it first would be work for nothing.
    const now = performance.now()
    const gap = failures
      ? Math.min(COOLDOWN_MS * 2 ** failures, MAX_BACKOFF_MS)
      : COOLDOWN_MS
    if (now - lastRequest < gap) {
      // Dropped here means the server never sees it, so it leaves no trace in
      // the wake log — which is exactly how a phrase split into two turns
      // stayed invisible for so long. Say so in the console.
      console.debug('[wake] sovish oynasida, yuborilmadi')
      return
    }

    let resampled: Float32Array
    try {
      resampled = await resampleTo16k(raw, rate)
    } catch (err) {
      // No OfflineAudioContext, or a rate it will not take. Nothing to send.
      console.debug('[wake] qayta namunalab bo`lmadi', err)
      return
    }
    const clip = normalize(trim(resampled, TARGET_RATE))
    const seconds = clip.length / TARGET_RATE
    if (seconds * 1000 < MIN_MS) {
      console.debug('[wake] juda qisqa, yuborilmadi', Math.round(seconds * 1000), 'ms')
      return
    }
    if (seconds * 1000 > MAX_MS) {
      // Conversation, not a summons. This is the gate that keeps ordinary
      // speech off the network entirely.
      console.debug('[wake] juda uzun, yuborilmadi', Math.round(seconds * 1000), 'ms')
      return
    }
    // Claimed only now that the clip is really going out: a clip dropped for
    // length must not spend the next 2.5 s of budget.
    lastRequest = performance.now()

    // DO NOT cancel a check that is still running. This used to be
    // `aborter?.abort()`, which was harmless only because the internal
    // Router answers in 0.13 s — a verdict always beat the 2.5 s cooldown,
    // so there was never a request to cancel. The second STT variant (GAPI)
    // answers in 1.2 s, and 3.6 s under load, which opened two holes at once:
    //
    //   * the phrase was heard, PAID FOR, and then thrown away. The documented
    //     case is the common one: people say "Salom", pause, then "Venera" —
    //     two turns 1.4 s apart, and the second one cancelled the first one's
    //     verdict.
    //   * an aborted request never reached the `failures` line below, so the
    //     backoff was never armed: a slow backend kept getting a clip every
    //     2.5 s while its worker threads piled up.
    //
    // Skipping the new clip instead is strictly better: a wake phrase that is
    // already being checked does not need checking twice, and the in-flight
    // request still carries a verdict. `stop()` still aborts.
    if (aborter) {
      console.debug('[wake] oldingi so`rov hali javob bermadi, yuborilmadi')
      return
    }
    aborter = new AbortController()
    const signal = aborter.signal
    try {
      const wav = new Blob([encodeWavBytes(clip, TARGET_RATE)], { type: 'audio/wav' })
      const verdict = await checkWake(wav, locale.value, signal)
      if (signal.aborted || !shouldRun()) return
      failures = verdict.checked ? 0 : failures + 1
      if (!verdict.checked) {
        console.debug('[wake] tekshirib bo`lmadi, keyingi urinish kechroq', failures)
        return
      }
      distorted.value = verdict.distorted === true
      // Useful while tuning: the console shows what was actually heard, which
      // is usually nothing like what the person thinks they said.
      if (verdict.text) console.debug('[wake]', verdict.text, '->', verdict.reason, distorted.value ? '(yozuv buzilgan)' : '')
      if (verdict.matched) {
        stop()          // release the microphone BEFORE the panel asks for it
        onWake()
      }
    } catch {
      // A failed wake check is not worth telling anyone about: the person did
      // not ask for anything yet. Errors here are also the common case when
      // the STT queue is full, and a visible error every few seconds would be
      // worse than silence.
      //
      // The backoff still has to be armed here, or a backend that fails by
      // THROWING (timeout, network) would look free of charge to the gate
      // above and keep getting a clip every 2.5 s.
      failures += 1
    } finally {
      // Releases the in-flight guard above. Without this the guard would latch
      // after the first request and the wake word would stop working entirely —
      // so it belongs in `finally`, not on the happy path.
      //
      // The identity check matters: `stop()` also clears `aborter`, so a
      // stop/start cycle can hand the guard to a NEWER request while this one
      // is still unwinding. Clearing it blindly would release someone else's
      // guard and let two checks run at once — the exact thing this guard
      // exists to prevent.
      if (aborter?.signal === signal) aborter = null
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

  return { active, blocked, distorted }
}

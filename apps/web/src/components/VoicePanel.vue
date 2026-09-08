<script setup lang="ts">
/**
 * Voice conversation. Tap the orb, speak, pause — the pause ends the turn.
 *
 * The flow is: microphone → MediaRecorder → our /api/v1/stt/transcribe proxy →
 * the chat pipeline. Nothing here talks to the STT server directly; see
 * `api/stt.api.ts` for why.
 *
 * VISUALS. The reference is `assets/voice.gif`: a glowing sphere on near-black,
 * glass-like colour sheets drifting inside it, a thin white rim with a bright
 * spot travelling around it, and smoky violet loops outside. It is rebuilt here
 * in CSS rather than shipped as the GIF — the GIF is 10 MB and cannot react to
 * the microphone; the CSS version is a few hundred bytes and does.
 *
 * THEMING. The reference is black, and the dark theme reproduces it. The light
 * theme is not the same picture on a white page — a white rim and a white bloom
 * vanish there. Instead the sphere gets a pale base, the colour sheets blend
 * with `multiply` (glass on paper rather than light in a dark room), the rim
 * turns violet and the glow becomes a soft coloured shadow. Every colour is a
 * `--vp-*` variable set once per theme below; nothing else in the stylesheet
 * knows which theme it is in.
 *
 * The single most surprising failure this component has to explain is the
 * secure-context rule: over plain HTTP on a LAN address `navigator.mediaDevices`
 * is simply `undefined`. No prompt appears and no error is raised, so an
 * unguarded version looks like a broken button. That case gets its own state
 * and its own message.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { micAvailable, micBlockedByPolicy, secureUrl, transcribe } from '../api/stt.api'
import { localizeApiError } from '../api/errors'
import { LOCALES } from '../i18n'
import { MicIcon, MicOffIcon, XIcon } from '../icons'

const props = defineProps<{
  open: boolean
  /** Sends the recognised text through the normal chat pipeline. Returns false
   *  if the pipeline is busy, so the panel can say so instead of losing it. */
  send: (text: string) => boolean
  /** True while the chat pipeline is running — drives the "thinking" state. */
  busy: boolean
  /** The most recent answer text, shown under the orb once it arrives. */
  answer?: string | null
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { t, locale } = useI18n({ useScope: 'global' })

type State = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'error'
const state = ref<State>('idle')
const level = ref(0)          // 0..1, drives the orb
const heard = ref('')
const errorText = ref('')
const errorHint = ref('')

// Imperative audio handles — plain lets, never refs: making them reactive would
// have Vue deep-proxy live MediaStream objects for no benefit.
let stream: MediaStream | null = null
let recorder: MediaRecorder | null = null
let audioCtx: AudioContext | null = null
let analyser: AnalyserNode | null = null
let rafId = 0
let chunks: Blob[] = []
let silenceSince = 0
let speechSeen = false

/** Speech must be seen before silence can end the turn, otherwise the recorder
 *  stops instantly in a quiet room. */
const SPEECH_RMS = 0.045
const SILENCE_MS = 1400
const MAX_TURN_MS = 30_000

const supported = computed(() => micAvailable())

const langLabel = computed(
  () => LOCALES.find((l) => l.code === locale.value)?.label ?? String(locale.value),
)

const statusText = computed(() => {
  if (!supported.value) return t('voiceNeedsHttps')
  switch (state.value) {
    case 'listening': return t('voiceListening')
    case 'transcribing': return t('voiceTranscribing')
    case 'thinking': return t('voiceThinking')
    case 'error': return errorText.value
    default: return t('voiceTapToSpeak')
  }
})

/** Pick a container the browser can actually record. Safari has no webm. */
function pickMime(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  for (const type of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) return type
  }
  return ''
}

function fail(message: string, hint = '') {
  errorText.value = message
  errorHint.value = hint
  state.value = 'error'
  teardown()
}

/** Release every audio resource. Called on stop, on error, on close and on
 *  unmount — a missed path leaves the browser's recording indicator lit. */
function teardown() {
  cancelAnimationFrame(rafId)
  rafId = 0
  if (recorder && recorder.state !== 'inactive') {
    recorder.onstop = null
    try { recorder.stop() } catch { /* already stopping */ }
  }
  recorder = null
  stream?.getTracks().forEach((track) => track.stop())
  stream = null
  analyser = null
  if (audioCtx && audioCtx.state !== 'closed') void audioCtx.close()
  audioCtx = null
  level.value = 0
}

function meter() {
  if (!analyser) return
  const buffer = new Float32Array(analyser.fftSize)
  const tick = () => {
    if (!analyser) return
    analyser.getFloatTimeDomainData(buffer)
    let sum = 0
    for (const sample of buffer) sum += sample * sample
    const rms = Math.sqrt(sum / buffer.length)
    // Ease upward fast, decay slowly — a meter that tracks raw RMS flickers.
    level.value = Math.max(Math.min(rms * 6, 1), level.value * 0.9)

    if (state.value === 'listening') {
      const now = performance.now()
      if (rms > SPEECH_RMS) {
        speechSeen = true
        silenceSince = now
      } else if (speechSeen && now - silenceSince > SILENCE_MS) {
        stopListening()
        return
      }
    }
    rafId = requestAnimationFrame(tick)
  }
  rafId = requestAnimationFrame(tick)
}

async function startListening() {
  if (!supported.value || state.value === 'listening') return
  heard.value = ''
  errorText.value = ''
  errorHint.value = ''
  chunks = []
  speechSeen = false
  silenceSince = performance.now()

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
  } catch (err) {
    const name = (err as DOMException)?.name
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      // Same error name for "the user clicked Block" and "the server header
      // forbids it" - but the second has no prompt and no fix in the browser.
      if (micBlockedByPolicy()) fail(t('voiceBlockedPolicy'), t('voiceBlockedPolicyHow'))
      else fail(t('voiceDenied'), t('voiceDeniedHow'))
    } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
      fail(t('voiceNoMic'))
    } else {
      fail(t('voiceError'))
    }
    return
  }

  try {
    audioCtx = new AudioContext()
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 1024
    audioCtx.createMediaStreamSource(stream).connect(analyser)

    const mimeType = pickMime()
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
    recorder.onstop = () => void handleRecorded()
    recorder.start()
    state.value = 'listening'
    meter()
    window.setTimeout(() => { if (state.value === 'listening') stopListening() }, MAX_TURN_MS)
  } catch {
    fail(t('voiceError'))
  }
}

function stopListening() {
  if (state.value !== 'listening' || !recorder) return
  state.value = 'transcribing'
  cancelAnimationFrame(rafId)
  rafId = 0
  try { recorder.stop() } catch { fail(t('voiceError')) }
}

async function handleRecorded() {
  const type = recorder?.mimeType || 'audio/webm'
  const blob = new Blob(chunks, { type })
  chunks = []
  // Keep the stream alive no longer than needed — the browser shows a recording
  // indicator for as long as a track is live.
  stream?.getTracks().forEach((track) => track.stop())
  stream = null

  // A blob this small holds only container headers: the turn had no audio.
  if (blob.size < 1200) {
    fail(t('voiceNoSpeech'))
    return
  }

  try {
    const result = await transcribe(blob, String(locale.value))
    teardown()
    const text = result.text.trim()
    if (!text) {
      fail(t('voiceNoSpeech'))
      return
    }
    heard.value = text
    state.value = props.send(text) ? 'thinking' : 'idle'
  } catch (err) {
    fail(localizeApiError(err, t))
  }
}

function close() {
  teardown()
  state.value = 'idle'
  emit('close')
}

function onOrbClick() {
  if (state.value === 'listening') stopListening()
  else if (state.value === 'idle' || state.value === 'error') void startListening()
}

// The pipeline finishing is what ends the "thinking" state.
watch(() => props.busy, (busy) => { if (!busy && state.value === 'thinking') state.value = 'idle' })
// Closing the panel must release the microphone even if `close()` wasn't used.
watch(() => props.open, (open) => { if (!open) { teardown(); state.value = 'idle' } })
onBeforeUnmount(teardown)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.preventDefault(); close() }
  if (e.key === ' ' && supported.value) { e.preventDefault(); onOrbClick() }
}

/** One CSS variable carries the microphone level into the stylesheet; every
 *  reactive part of the orb (scale, rim glow, halo, wisp opacity) reads it
 *  there. Keeping the maths in CSS means no per-frame style object churn. */
const orbVars = computed(() => ({ '--lvl': level.value.toFixed(3) }))
</script>

<template>
  <div
    v-if="open"
    class="vp"
    :data-state="supported ? state : 'unsupported'"
    :style="orbVars"
    role="dialog"
    aria-modal="true"
    :aria-label="t('voiceTitle')"
    tabindex="-1"
    @keydown="onKeydown"
  >
    <button class="vp-close" :aria-label="t('voiceClose')" :title="t('voiceClose')" @click="close">
      <XIcon :size="18" />
    </button>

    <div class="vp-stage">
      <!-- Soft violet light behind everything; breathes with the voice. -->
      <div class="vp-halo" aria-hidden="true" />

      <!-- Smoky loops drifting outside the sphere, deliberately off-centre. -->
      <div class="vp-wisp vp-wisp-a" aria-hidden="true" />
      <div class="vp-wisp vp-wisp-b" aria-hidden="true" />
      <div class="vp-wisp vp-wisp-c" aria-hidden="true" />

      <button
        class="vp-orb"
        :disabled="!supported || state === 'transcribing' || state === 'thinking'"
        :aria-label="state === 'listening' ? t('voiceStopListening') : t('voiceTapToSpeak')"
        @click="onOrbClick"
      >
        <!-- Glass sheets: large blurred colour fields orbiting the centre at
             different speeds, overlapping with `screen` so they read as
             translucent layers rather than opaque shapes. -->
        <span class="vp-sheets" aria-hidden="true">
          <span class="vp-sheet vp-sheet-cyan" />
          <span class="vp-sheet vp-sheet-blue" />
          <span class="vp-sheet vp-sheet-violet" />
          <span class="vp-sheet vp-sheet-magenta" />
        </span>
        <!-- Thin white rim and its bloom. -->
        <span class="vp-rim" aria-hidden="true" />
        <!-- The bright spot that travels around the rim. -->
        <span class="vp-spark" aria-hidden="true" />
        <span class="vp-icon" aria-hidden="true">
          <MicOffIcon v-if="!supported" :size="30" />
          <MicIcon v-else />
        </span>
      </button>
    </div>

    <div class="vp-text">
      <p class="vp-status" :class="{ 'vp-status--bad': state === 'error' || !supported }">{{ statusText }}</p>

      <p v-if="!supported" class="vp-sub">
        {{ t('voiceNeedsHttpsHow') }}<br />
        <a class="vp-link" :href="secureUrl()">{{ secureUrl() }}</a>
      </p>
      <p v-else-if="errorHint" class="vp-sub">{{ errorHint }}</p>
      <p v-else-if="state === 'idle' && !heard" class="vp-sub">{{ t('voiceHint') }}</p>

      <p v-if="heard" class="vp-heard">
        <span class="vp-heard-label">{{ t('voiceHeard') }}</span>
        {{ heard }}
      </p>
      <p v-if="answer && state === 'idle'" class="vp-answer">{{ answer }}</p>

      <button v-if="state === 'error'" class="vp-retry" @click="onOrbClick">{{ t('voiceRetry') }}</button>
    </div>

    <p v-if="supported" class="vp-foot">{{ t('voiceLangNote', { lang: langLabel }) }}</p>
  </div>
</template>

<style scoped>
/* ── Theme ─────────────────────────────────────────────────────────────── */
/* Light is the default (matches :root); dark overrides below. Numeric `-k`
   values scale glow/halo/wisp strength — light needs far less of all three. */
.vp {
  --vp-bg: var(--bg);
  --vp-fg: var(--text);
  --vp-fg-2: var(--text-muted);
  --vp-fg-3: var(--text-secondary);
  --vp-bad: var(--bad-fg);
  --vp-link: #4f6de6;
  --vp-btn-bg: rgba(20, 20, 20, 0.06);
  --vp-btn-bg-hover: rgba(20, 20, 20, 0.12);
  --vp-btn-fg: var(--text-muted);
  --vp-btn-fg-hover: var(--text);
  --vp-btn-border: rgba(20, 20, 20, 0.14);
  --vp-orb-base: #f1f2ff;
  --vp-blend: multiply;
  --vp-rim: rgba(96, 88, 232, 0.85);
  --vp-icon: rgba(40, 36, 90, 0.7);
  --vp-glow: 118, 104, 255;
  --vp-glow-k: 0.5;
  --vp-halo-k: 0.45;
  --vp-wisp-k: 0.55;
  --accent-a: #7fd4f8; /* cyan    */
  --accent-b: #6f9cf0; /* blue    */
  --accent-c: #9b8cf0; /* violet  */
  --accent-d: #d46ae6; /* magenta */
}
:root[data-theme='dark'] .vp {
  --vp-bg: #040109;
  --vp-fg: #f2f0fb;
  --vp-fg-2: rgba(233, 230, 245, 0.62);
  --vp-fg-3: rgba(233, 230, 245, 0.42);
  --vp-bad: #ff8a80;
  --vp-link: #9fb5ff;
  --vp-btn-bg: rgba(255, 255, 255, 0.06);
  --vp-btn-bg-hover: rgba(255, 255, 255, 0.14);
  --vp-btn-fg: rgba(255, 255, 255, 0.72);
  --vp-btn-fg-hover: #fff;
  --vp-btn-border: rgba(255, 255, 255, 0.22);
  --vp-orb-base: #0a0a2a;
  --vp-blend: screen;
  --vp-rim: rgba(255, 255, 255, 0.95);
  --vp-icon: rgba(255, 255, 255, 0.8);
  --vp-glow: 150, 160, 255;
  --vp-glow-k: 1;
  --vp-halo-k: 1;
  --vp-wisp-k: 1;
  --accent-a: #90d7f8;
  --accent-b: #2954b4;
  --accent-c: #5a59be;
  --accent-d: #c02fd6;
}

/* ── Stage ─────────────────────────────────────────────────────────────── */
.vp {
  position: absolute;
  inset: 0;
  z-index: 40;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  background: var(--vp-bg);
  color: var(--vp-fg);
  font-family: Figtree, sans-serif;
  animation: fadeUp 0.32s ease both;
  overflow: hidden;
  --orb: clamp(180px, 34vmin, 260px);
}
.vp-close {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 50%;
  background: var(--vp-btn-bg);
  color: var(--vp-btn-fg);
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}
.vp-close:hover {
  background: var(--vp-btn-bg-hover);
  color: var(--vp-btn-fg-hover);
}

.vp-stage {
  position: relative;
  width: calc(var(--orb) * 2.4);
  height: calc(var(--orb) * 2.4);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

/* ── Halo ──────────────────────────────────────────────────────────────── */
.vp-halo {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(var(--vp-glow), calc((0.22 + var(--lvl) * 0.35) * var(--vp-halo-k))) 0%,
    rgba(90, 60, 200, calc((0.12 + var(--lvl) * 0.2) * var(--vp-halo-k))) 32%,
    transparent 68%
  );
  filter: blur(6px);
  transform: scale(calc(0.92 + var(--lvl) * 0.28));
  transition: transform 0.12s linear;
}

/* ── Wisps ─────────────────────────────────────────────────────────────── */
.vp-wisp {
  position: absolute;
  border-radius: 50%;
  border: 14px solid transparent;
  filter: blur(14px);
  opacity: calc((0.35 + var(--lvl) * 0.4) * var(--vp-wisp-k));
  mix-blend-mode: var(--vp-blend);
  pointer-events: none;
}
.vp-wisp-a {
  width: calc(var(--orb) * 1.55);
  height: calc(var(--orb) * 1.35);
  border-color: rgba(120, 100, 235, 0.55) transparent rgba(70, 60, 170, 0.5) transparent;
  animation: wispA 9s linear infinite;
}
.vp-wisp-b {
  width: calc(var(--orb) * 1.9);
  height: calc(var(--orb) * 1.6);
  border-color: transparent rgba(95, 80, 215, 0.4) transparent rgba(140, 110, 255, 0.35);
  animation: wispB 13s linear infinite reverse;
}
.vp-wisp-c {
  width: calc(var(--orb) * 1.25);
  height: calc(var(--orb) * 1.7);
  border-color: rgba(60, 50, 160, 0.45) transparent transparent rgba(150, 120, 255, 0.3);
  animation: wispC 7s ease-in-out infinite;
}
@keyframes wispA {
  from { transform: translate(-6%, 3%) rotate(0deg); }
  to   { transform: translate(-6%, 3%) rotate(360deg); }
}
@keyframes wispB {
  from { transform: translate(5%, -4%) rotate(0deg); }
  to   { transform: translate(5%, -4%) rotate(360deg); }
}
@keyframes wispC {
  0%   { transform: translate(-3%, 5%) rotate(0deg) scale(1); }
  50%  { transform: translate(4%, -3%) rotate(180deg) scale(1.08); }
  100% { transform: translate(-3%, 5%) rotate(360deg) scale(1); }
}

/* ── Orb ───────────────────────────────────────────────────────────────── */
.vp-orb {
  position: relative;
  width: var(--orb);
  height: var(--orb);
  border-radius: 50%;
  border: none;
  padding: 0;
  background: var(--vp-orb-base);
  cursor: pointer;
  overflow: hidden;
  isolation: isolate;
  transform: scale(calc(1 + var(--lvl) * 0.14));
  transition: transform 0.1s linear;
  box-shadow:
    0 0 calc(20px + var(--lvl) * 40px) rgba(var(--vp-glow), calc((0.45 + var(--lvl) * 0.4) * var(--vp-glow-k))),
    0 0 calc(60px + var(--lvl) * 60px) rgba(110, 90, 255, calc((0.25 + var(--lvl) * 0.3) * var(--vp-glow-k)));
}
.vp-orb:disabled {
  cursor: default;
}
.vp-sheets {
  position: absolute;
  inset: -20%;
  animation: sheetsSpin 22s linear infinite;
}
.vp-sheet {
  position: absolute;
  width: 78%;
  height: 78%;
  border-radius: 46% 54% 52% 48% / 55% 45% 55% 45%;
  filter: blur(6px);
  mix-blend-mode: var(--vp-blend);
  opacity: 0.92;
}
.vp-sheet-cyan    { top: -6%;  left: 22%; background: var(--accent-a); animation: sheetA 8s ease-in-out infinite; }
.vp-sheet-blue    { top: 26%;  left: 30%; background: var(--accent-b); animation: sheetB 11s ease-in-out infinite; }
.vp-sheet-violet  { top: 18%;  left: -4%; background: var(--accent-c); animation: sheetC 9.5s ease-in-out infinite; }
.vp-sheet-magenta { top: 4%;   left: 2%;  background: var(--accent-d); width: 58%; height: 58%; opacity: 0.8; animation: sheetD 7s ease-in-out infinite; }
@keyframes sheetsSpin { to { transform: rotate(360deg); } }
@keyframes sheetA {
  0%, 100% { transform: translate(0, 0) rotate(0deg) scale(1); }
  50%      { transform: translate(-10%, 12%) rotate(40deg) scale(1.1); }
}
@keyframes sheetB {
  0%, 100% { transform: translate(0, 0) rotate(0deg) scale(1.05); }
  50%      { transform: translate(12%, -8%) rotate(-35deg) scale(0.95); }
}
@keyframes sheetC {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  50%      { transform: translate(8%, 10%) rotate(55deg); }
}
@keyframes sheetD {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50%      { transform: translate(14%, 6%) scale(1.25); }
}

/* Thin rim + bloom, drawn above the sheets. */
.vp-rim {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  box-shadow:
    inset 0 0 0 2px var(--vp-rim),
    inset 0 0 calc(10px + var(--lvl) * 14px) rgba(var(--vp-glow), calc(0.9 * var(--vp-glow-k))),
    inset 0 0 28px rgba(var(--vp-glow), calc(0.35 * var(--vp-glow-k)));
  pointer-events: none;
}
/* The travelling highlight: a conic gradient masked down to the rim. */
.vp-spark {
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    transparent 0deg,
    rgba(255, 255, 255, 0) 250deg,
    rgba(255, 255, 255, 0.95) 300deg,
    rgba(var(--vp-glow), 0.8) 330deg,
    transparent 360deg
  );
  -webkit-mask: radial-gradient(circle, transparent calc(50% - 6px), #000 calc(50% - 4px), #000 50%, transparent 51%);
  mask: radial-gradient(circle, transparent calc(50% - 6px), #000 calc(50% - 4px), #000 50%, transparent 51%);
  filter: blur(1.2px);
  animation: sparkSpin 4s linear infinite;
  pointer-events: none;
}
@keyframes sparkSpin { to { transform: rotate(360deg); } }

.vp-icon {
  position: relative;
  z-index: 2;
  display: grid;
  place-items: center;
  color: var(--vp-icon);
  filter: drop-shadow(0 0 6px rgba(0, 0, 0, 0.25));
  transition: opacity 0.3s;
}
.vp-icon :deep(svg) {
  width: 26px;
  height: 26px;
}

/* ── State tuning ──────────────────────────────────────────────────────── */
.vp[data-state='listening'] .vp-sheets { animation-duration: 9s; }
.vp[data-state='listening'] .vp-spark  { animation-duration: 1.6s; }
.vp[data-state='listening'] .vp-icon   { opacity: 0.35; }
.vp[data-state='transcribing'] .vp-orb,
.vp[data-state='thinking'] .vp-orb {
  animation: breathe 1.6s ease-in-out infinite;
}
@keyframes breathe {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.06); }
}
/* Error / unsupported: the colour drains out. */
.vp[data-state='error'] .vp-sheet,
.vp[data-state='unsupported'] .vp-sheet { filter: blur(6px) saturate(0.25); opacity: 0.5; }
.vp[data-state='error'] .vp-rim,
.vp[data-state='unsupported'] .vp-rim {
  box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--vp-rim) 50%, transparent);
}
.vp[data-state='unsupported'] .vp-spark,
.vp[data-state='unsupported'] .vp-wisp { animation-play-state: paused; opacity: 0.2; }

/* ── Text ──────────────────────────────────────────────────────────────── */
.vp-text {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  max-width: 460px;
  text-align: center;
  z-index: 1;
}
.vp-status {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: var(--vp-fg);
  letter-spacing: 0.01em;
}
.vp-status--bad {
  color: var(--vp-bad);
}
.vp-sub {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--vp-fg-2);
}
.vp-link {
  color: var(--vp-link);
  word-break: break-all;
}
.vp-heard {
  margin: 6px 0 0;
  font-size: 15px;
  line-height: 1.5;
  color: var(--vp-fg);
}
.vp-heard-label {
  display: block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--vp-fg-3);
  margin-bottom: 2px;
}
.vp-answer {
  margin: 4px 0 0;
  font-size: 14px;
  line-height: 1.55;
  color: var(--vp-fg-2);
  max-height: 120px;
  overflow-y: auto;
}
.vp-retry {
  margin-top: 6px;
  border: 1px solid var(--vp-btn-border);
  background: var(--vp-btn-bg);
  color: var(--vp-fg);
  border-radius: 999px;
  padding: 7px 18px;
  font-size: 13.5px;
  cursor: pointer;
}
.vp-retry:hover {
  background: var(--vp-btn-bg-hover);
}
.vp-foot {
  position: absolute;
  bottom: 18px;
  margin: 0;
  font-size: 12px;
  color: var(--vp-fg-3);
}

@media (prefers-reduced-motion: reduce) {
  .vp-sheets, .vp-sheet, .vp-spark, .vp-wisp { animation-duration: 60s; }
  .vp-orb { transition: none; }
}
</style>

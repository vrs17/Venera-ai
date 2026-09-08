<script setup lang="ts">
/**
 * Voice conversation. Tap the orb, speak, pause — the pause ends the turn.
 *
 * The flow is: microphone → MediaRecorder → our /api/v1/stt/transcribe proxy →
 * the chat pipeline. Nothing here talks to the STT server directly; see
 * `api/stt.api.ts` for why.
 *
 * The single most surprising failure this component has to explain is the
 * secure-context rule: over plain HTTP on a LAN address `navigator.mediaDevices`
 * is simply `undefined`. No prompt appears and no error is raised, so an
 * unguarded version looks like a broken button. That case gets its own state
 * and its own message.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CSSProperties } from 'vue'
import { micAvailable, secureUrl, transcribe } from '../api/stt.api'
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
      fail(t('voiceDenied'), t('voiceDeniedHow'))
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

const orbStyle = computed<CSSProperties>(() => {
  const active = state.value === 'listening'
  const scale = active ? 1 + level.value * 0.22 : 1
  return {
    width: '132px',
    height: '132px',
    borderRadius: '50%',
    border: 'none',
    cursor: supported.value ? 'pointer' : 'not-allowed',
    display: 'grid',
    placeItems: 'center',
    color: active ? 'var(--accent-contrast)' : 'var(--text-secondary)',
    background: active
      ? 'var(--accent)'
      : state.value === 'error'
        ? 'var(--bad-bg)'
        : 'var(--surface-hover)',
    transform: `scale(${scale})`,
    transition: 'background 0.3s, color 0.3s, transform 0.08s linear',
    boxShadow: active
      ? `0 0 ${18 + level.value * 46}px rgba(225, 25, 0, ${0.25 + level.value * 0.45}), var(--glass-shadow)`
      : 'var(--glass-shadow)',
  }
})
</script>

<template>
  <div
    v-if="open"
    class="voice-overlay"
    role="dialog"
    aria-modal="true"
    :aria-label="t('voiceTitle')"
    tabindex="-1"
    @keydown="onKeydown"
  >
    <div class="voice-sheet glass">
      <header class="voice-head">
        <span class="voice-title">{{ t('voiceTitle') }}</span>
        <button class="voice-x" :aria-label="t('voiceClose')" :title="t('voiceClose')" @click="close">
          <XIcon :size="17" />
        </button>
      </header>

      <div class="voice-body">
        <button
          class="voice-orb"
          :style="orbStyle"
          :disabled="!supported || state === 'transcribing' || state === 'thinking'"
          :aria-label="state === 'listening' ? t('voiceStopListening') : t('voiceTapToSpeak')"
          @click="onOrbClick"
        >
          <MicOffIcon v-if="!supported" :size="34" />
          <MicIcon v-else />
        </button>

        <p class="voice-status" :class="{ 'voice-status--bad': state === 'error' || !supported }">
          {{ statusText }}
        </p>

        <p v-if="!supported" class="voice-sub">
          {{ t('voiceNeedsHttpsHow') }}<br />
          <a class="voice-link" :href="secureUrl()">{{ secureUrl() }}</a>
        </p>
        <p v-else-if="errorHint" class="voice-sub">{{ errorHint }}</p>
        <p v-else class="voice-sub">{{ t('voiceHint') }}</p>

        <div v-if="heard" class="voice-heard">
          <span class="voice-heard-label">{{ t('voiceHeard') }}</span>
          <p class="voice-heard-text">{{ heard }}</p>
        </div>

        <p v-if="answer && state === 'idle'" class="voice-answer">{{ answer }}</p>
      </div>

      <footer class="voice-foot">
        <span v-if="supported">{{ t('voiceLangNote', { lang: langLabel }) }}</span>
        <button v-if="state === 'error'" class="voice-retry" @click="onOrbClick">{{ t('voiceRetry') }}</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.voice-overlay {
  position: absolute;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: 24px;
  background: color-mix(in srgb, var(--bg) 72%, transparent);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  animation: fadeUp 0.28s ease both;
}
.voice-sheet {
  width: 100%;
  max-width: 460px;
  border-radius: 26px;
  padding: 16px 22px 18px;
  box-shadow: var(--glass-shadow);
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.voice-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.voice-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.01em;
}
.voice-x {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--icon-muted);
  cursor: pointer;
}
.voice-x:hover {
  background: var(--surface-hover);
  color: var(--text);
}
.voice-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 10px 0 4px;
  text-align: center;
}
.voice-orb {
  /* sizing and colour come from :style so they can follow the live mic level */
  margin-bottom: 4px;
}
.voice-orb:disabled {
  cursor: default;
}
.voice-status {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.voice-status--bad {
  color: var(--bad-fg);
}
.voice-sub {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-muted);
  max-width: 340px;
}
.voice-link {
  color: var(--accent);
  word-break: break-all;
}
.voice-heard {
  width: 100%;
  margin-top: 4px;
  padding: 10px 14px;
  border-radius: 14px;
  background: var(--surface-sunken);
  text-align: left;
}
.voice-heard-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}
.voice-heard-text {
  margin: 4px 0 0;
  font-size: 15px;
  color: var(--text);
}
.voice-answer {
  margin: 2px 0 0;
  font-size: 14px;
  line-height: 1.55;
  color: var(--text-muted);
  text-align: left;
  max-height: 132px;
  overflow-y: auto;
}
.voice-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 20px;
  font-size: 12px;
  color: var(--text-secondary);
}
.voice-retry {
  border: none;
  background: var(--accent);
  color: var(--accent-contrast);
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
}
@media (max-width: 520px) {
  .voice-sheet {
    max-width: none;
  }
}
</style>

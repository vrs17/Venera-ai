<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, FlaskConical, Mic, Play, Square, TriangleAlert, Upload } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VSegmented from '../../ui/VSegmented.vue'
import type { SegmentedOption } from '../../ui/VSegmented.vue'
import VSwitch from '../../ui/VSwitch.vue'
import VTextarea from '../../ui/VTextarea.vue'
import { ApiError } from '../../api/http'
import { micAvailable } from '../../api/stt.api'
import { holdClip, play, speakStream } from '../../api/tts.api'
import { toWav16k } from '../../api/wav'
import { prepareSpeech } from '../../components/chat/readAloud'
import { getProbe, runProbe, runSttProbe } from '../api'
import ProbeResultView from './ProbeResultView.vue'
import ProbeTrace from './ProbeTrace.vue'
import { BRAIN, SAMPLES } from './samples'
import type { ProbeResult, ProbeStep } from './types'

/**
 * "Sinab ko'rish": qadamni JONLI serverda, ishlab chiqarishdagi AYNI kod bilan ishga
 * tushiradi va qadamlar ro'yxatini (vaqti bilan) ko'rsatadi. Backend: `admin_probe.py`.
 *
 * Brauzer qismi ham AYNI yo'ldan: STT uchun yozuv `toWav16k` dan o'tadi (ovoz paneli
 * kabi), TTS uchun matn avval `prepareSpeech` dan (javobni o'qish tugmasi kabi) - bu
 * "0-bosqich" bo'lib ko'rsatiladi; `tts-speak` esa ovozni AYNI `speakStream` bilan
 * o'ynatadi va birinchi ovoz hamda umumiy vaqtni o'lchaydi.
 *
 * Pullik sinov (GAPI, gemma, model `execute`) - avval sahifaning o'zida tasdiq
 * (`window.confirm` emas): narx yozuvi tugma ustida turadi.
 *
 * Props: `probe` - `stt | tts-text | tts-speak | wake | hold | mask | agent | health |
 * brain:<funksiya>`.
 */
const props = defineProps<{ probe: string }>()
const { t } = useI18n({ useScope: 'global' })

const kind = computed(() => (props.probe.startsWith('brain:') ? 'brain' : props.probe))
const feature = computed(() => (props.probe.startsWith('brain:') ? props.probe.slice(6) : ''))
const brain = computed(() => BRAIN[feature.value] ?? { question: true, input: true, execute: false })
const KNOWN = ['stt', 'tts-text', 'tts-speak', 'wake', 'hold', 'mask', 'agent', 'health', 'brain']
const supported = computed(() => KNOWN.includes(kind.value) && (kind.value !== 'brain' || feature.value in BRAIN))

/* ---------------------------------------------------------------- forma */

const text = ref('')
const question = ref('')
const language = ref<'uz' | 'ru' | 'en'>('uz')
const provider = ref<'auto' | 'gapi' | 'router'>('auto')
const mode = ref<'speak' | 'clip'>('speak')
const useLlm = ref(false)
const execute = ref(false)
const briefKind = ref<'project' | 'support'>('project')

function reset() {
  const sample = SAMPLES[props.probe] ?? { text: '' }
  text.value = sample.text
  question.value = sample.question ?? ''
  useLlm.value = false
  execute.value = false
  result.value = null
  error.value = null
  confirming.value = false
  stage0.value = null
  speakTimes.value = null
  audio.value = null
}

const langOptions: SegmentedOption<'uz' | 'ru' | 'en'>[] = [
  { value: 'uz', label: 'uz' },
  { value: 'ru', label: 'ru' },
  { value: 'en', label: 'en' },
]
const providerOptions = computed<SegmentedOption<'auto' | 'gapi' | 'router'>[]>(() => [
  { value: 'auto', label: t('admin.osmap.probe.providerAuto') },
  { value: 'gapi', label: 'GAPI' },
  { value: 'router', label: 'Router' },
])
const modeOptions: SegmentedOption<'speak' | 'clip'>[] = [
  { value: 'speak', label: '/tts/speak' },
  { value: 'clip', label: '/tts/clip' },
]
const kindOptions = computed<SegmentedOption<'project' | 'support'>[]>(() => [
  { value: 'project', label: t('admin.osmap.probe.kindProject') },
  { value: 'support', label: t('admin.osmap.probe.kindSupport') },
])

/* ---------------------------------------------------------------- audio (STT) */

interface Audio {
  blob: Blob
  name: string
}
const audio = shallowRef<Audio | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const recording = ref(false)
const recordSec = ref(0)
const canRecord = micAvailable()
let recorder: MediaRecorder | null = null
let micStream: MediaStream | null = null
let recordTimer: ReturnType<typeof setInterval> | undefined

function onFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (file) audio.value = { blob: file, name: file.name }
}

/** Ovoz paneli (`VoicePanel.pickMime`) bilan bir xil tanlov - brauzer qaysi formatda yozsa. */
function pickMime(): string {
  for (const type of ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) return type
  }
  return ''
}

async function startRecord() {
  error.value = null
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch {
    error.value = t('admin.osmap.probe.micDenied')
    return
  }
  const mimeType = pickMime()
  const chunks: Blob[] = []
  try {
    recorder = new MediaRecorder(micStream, mimeType ? { mimeType } : undefined)
  } catch {
    // Brauzer yozuvchini yarata olmadi - mikrofon ochiq qolmasin.
    stopMic()
    error.value = t('admin.osmap.probe.micDenied')
    return
  }
  recorder.ondataavailable = (e) => {
    if (e.data.size) chunks.push(e.data)
  }
  recorder.onstop = () => {
    const type = recorder?.mimeType || mimeType || 'audio/webm'
    audio.value = { blob: new Blob(chunks, { type }), name: t('admin.osmap.probe.recordedName', { sec: recordSec.value }) }
    stopMic()
  }
  recorder.start()
  recording.value = true
  recordSec.value = 0
  recordTimer = setInterval(() => (recordSec.value += 1), 1000)
}

function stopRecord() {
  if (recorder && recorder.state !== 'inactive') recorder.stop()
  recording.value = false
  clearInterval(recordTimer)
}

function stopMic() {
  micStream?.getTracks().forEach((track) => track.stop())
  micStream = null
}

/** `transcribe()` (stt.api.ts) bilan AYNI: 16 kHz WAV, brauzer ocholmasa - asl fayl. */
async function uploadOf(a: Audio, steps: ProbeStep[]): Promise<{ blob: Blob; name: string }> {
  const started = performance.now()
  try {
    const wav = await toWav16k(a.blob)
    steps.push({ step: 'toWav16k', ms: performance.now() - started, detail: { from: a.blob.type || '?', bytes: wav.size } })
    return { blob: wav, name: 'speech.wav' }
  } catch {
    const type = a.blob.type
    const name = type.includes('ogg') ? 'speech.ogg' : type.includes('mp4') ? 'speech.m4a' : type.includes('wav') ? 'speech.wav' : 'speech.webm'
    steps.push({ step: 'toWav16k', ms: performance.now() - started, detail: { skipped: 'decode failed', sent: name } })
    return { blob: a.blob, name }
  }
}

/* ---------------------------------------------------------------- narx va tasdiq */

const paid = computed(() => {
  if (kind.value === 'stt') return language.value === 'uz' && provider.value !== 'router'
  if (kind.value === 'hold') return useLlm.value
  if (kind.value === 'brain') return execute.value
  return false
})
const costHint = computed(() => {
  if (kind.value === 'stt') return paid.value ? t('admin.osmap.probe.sttCost') : t('admin.osmap.probe.sttFree')
  if (kind.value === 'hold') return useLlm.value ? t('admin.osmap.probe.holdCost') : ''
  if (kind.value === 'brain') return execute.value ? t('admin.osmap.probe.brainCost') : t('admin.osmap.probe.brainDry')
  if (kind.value === 'tts-speak') return t('admin.osmap.probe.ttsNote')
  return ''
})
const confirming = ref(false)

/* ---------------------------------------------------------------- ishga tushirish */

const busy = ref(false)
const error = ref<string | null>(null)
const result = shallowRef<ProbeResult | null>(null)
const stage0 = ref<{ text: string; shortened: boolean; ms: number } | null>(null)
const speakTimes = ref<{ firstMs: number | null; totalMs: number | null; playing: boolean } | null>(null)
let controller: AbortController | null = null
let stopPlayback: (() => void) | null = null

const canRun = computed(() => {
  if (!supported.value || busy.value || recording.value) return false
  if (kind.value === 'stt') return !!audio.value
  if (['tts-text', 'tts-speak', 'hold', 'mask'].includes(kind.value)) return !!text.value.trim()
  if (kind.value === 'brain') {
    if (brain.value.input && !text.value.trim()) return false
    if (!brain.value.input && !question.value.trim()) return false
  }
  return true
})

function onRun() {
  if (!canRun.value) return
  if (paid.value && !confirming.value) {
    confirming.value = true
    return
  }
  confirming.value = false
  void run()
}

function message(err: unknown): string {
  if (err instanceof ApiError) return err.status ? `${err.status}: ${err.message}` : err.message
  return err instanceof Error ? err.message : String(err)
}

/** Brauzer bosqichi: `prepareSpeech` (javobni o'qish tugmasi bilan AYNI). */
function browserStage(): string {
  const started = performance.now()
  const prepared = prepareSpeech(text.value)
  stage0.value = { ...prepared, ms: performance.now() - started }
  return prepared.text
}

async function run() {
  controller?.abort()
  stopPlayback?.()
  controller = new AbortController()
  const signal = controller.signal
  busy.value = true
  error.value = null
  result.value = null
  stage0.value = null
  speakTimes.value = null
  try {
    switch (kind.value) {
      case 'stt': {
        const steps: ProbeStep[] = []
        const upload = await uploadOf(audio.value!, steps)
        const form = new FormData()
        form.append('file', upload.blob, upload.name)
        form.append('language', language.value)
        form.append('provider', provider.value)
        const res = await runSttProbe(form, signal)
        result.value = { ...res, trace: [...steps, ...res.trace] }
        break
      }
      case 'tts-text': {
        const prepared = browserStage()
        result.value = await runProbe('tts-text', { text: prepared || ' ', language: 'uz', mode: mode.value }, signal)
        break
      }
      case 'tts-speak':
        await speak(signal)
        break
      case 'wake':
        result.value = await runProbe('wake', { text: text.value }, signal)
        break
      case 'hold':
        result.value = await runProbe('hold', { question: text.value, use_llm: useLlm.value }, signal)
        break
      case 'mask':
        result.value = await runProbe('mask', { text: text.value }, signal)
        break
      case 'agent':
      case 'health':
        result.value = await getProbe(kind.value, signal)
        break
      case 'brain':
        result.value = await runProbe(
          `brain/${encodeURIComponent(feature.value)}`,
          { input: text.value, question: question.value, kind: briefKind.value, execute: execute.value },
          signal,
        )
        break
    }
  } catch (err) {
    if (!(err instanceof DOMException && err.name === 'AbortError')) error.value = message(err)
  } finally {
    busy.value = false
  }
}

/** Ovoz: AYNI `speakStream` (ovoz paneli va 🔊). Server matn bosqichlari - parallel `tts-text`. */
async function speak(signal: AbortSignal) {
  const prepared = browserStage()
  const textProbe = runProbe('tts-text', { text: prepared || ' ', language: 'uz', mode: 'speak' }, signal).catch(() => null)
  speakTimes.value = { firstMs: null, totalMs: null, playing: false }
  const started = performance.now()
  const playback = await speakStream(prepared, 'uz', signal)
  stopPlayback = playback.stop
  speakTimes.value = { firstMs: performance.now() - started, totalMs: null, playing: true }
  const server = await textProbe
  const steps: ProbeStep[] = [
    { step: 'prepareSpeech', ms: stage0.value?.ms ?? 0, detail: { chars: prepared.length, shortened: stage0.value?.shortened ?? false } },
    { step: 'first_audio', ms: speakTimes.value.firstMs ?? 0, detail: { endpoint: '/api/v1/tts/speak' } },
  ]
  result.value = { ok: true, trace: steps, result: server?.result ?? null, cost_note: null }
  try {
    await playback.done
  } finally {
    const total = performance.now() - started
    speakTimes.value = { firstMs: speakTimes.value?.firstMs ?? null, totalMs: total, playing: false }
    result.value = {
      ok: true,
      trace: [...steps, { step: 'playback_done', ms: total - (speakTimes.value.firstMs ?? 0), detail: {} }],
      result: server?.result ?? null,
      cost_note: null,
    }
    stopPlayback = null
  }
}

function stopAll() {
  controller?.abort()
  stopPlayback?.()
  stopPlayback = null
  busy.value = false
}

/** Kutish ovozini o'ynatish - AYNI `holdClip` (chat oqimidagi kabi). Oldingi ovoz to'xtatiladi,
 *  varaq yopilsa ham (`stopAll`) - ovoz ustma-ust yoki sahifadan keyin eshitilmasin. */
async function playClip(clip: string) {
  stopPlayback?.()
  stopPlayback = null
  const blob = await holdClip(clip)
  if (!blob) {
    error.value = t('admin.osmap.probe.notReady')
    return
  }
  const playback = play(blob)
  stopPlayback = playback.stop
  // Brauzer o'ynatmasa (avtoijro taqiqi, buzuq fayl) - ishlanmagan rad etish qolmasin;
  // kutish ovozi chatda ham jim o'tkazib yuboriladi.
  playback.done
    .catch(() => undefined)
    .finally(() => {
      if (stopPlayback === playback.stop) stopPlayback = null
    })
}

watch(() => props.probe, reset, { immediate: true })

onBeforeUnmount(() => {
  stopAll()
  if (recording.value) stopRecord()
  stopMic()
  clearInterval(recordTimer)
})
</script>

<template>
  <section class="pp" :aria-label="t('admin.osmap.sec.run')">
    <p class="pp__intro">
      <FlaskConical :size="14" :stroke-width="1.75" aria-hidden="true" />
      {{ t('admin.osmap.probe.intro') }}
      <span class="pp__chip">{{ probe }}</span>
    </p>

    <p v-if="!supported" class="pp__muted">{{ t('admin.osmap.probe.unsupported', { probe }) }}</p>

    <template v-else>
      <!-- forma -->
      <div class="pp__form">
        <template v-if="kind === 'stt'">
          <div class="pp__row">
            <VButton size="sm" :icon="Upload" @click="fileInput?.click()">{{ t('admin.osmap.probe.chooseFile') }}</VButton>
            <input ref="fileInput" class="pp__file" type="file" accept="audio/*" @change="onFile" />
            <VButton v-if="canRecord && !recording" size="sm" :icon="Mic" @click="startRecord">
              {{ t('admin.osmap.probe.record') }}
            </VButton>
            <VButton v-if="recording" size="sm" variant="danger" :icon="Square" @click="stopRecord">
              {{ t('admin.osmap.probe.stopRecord', { sec: recordSec }) }}
            </VButton>
          </div>
          <p v-if="audio" class="pp__muted">{{ audio.name }} · {{ Math.round(audio.blob.size / 1024) }} KB</p>
          <div class="pp__row">
            <span class="pp__label">{{ t('admin.osmap.probe.language') }}</span>
            <VSegmented v-model="language" size="sm" :options="langOptions" :aria-label="t('admin.osmap.probe.language')" />
          </div>
          <div class="pp__row">
            <span class="pp__label">{{ t('admin.osmap.probe.provider') }}</span>
            <VSegmented v-model="provider" size="sm" :options="providerOptions" :aria-label="t('admin.osmap.probe.provider')" />
          </div>
        </template>

        <template v-else-if="kind === 'brain'">
          <VTextarea
            v-if="brain.input"
            v-model="text"
            :label="t('admin.osmap.probe.input')"
            :hint="t(`admin.osmap.probe.inputHint.${feature.startsWith('meeting_') && feature !== 'meeting_crm' ? 'meeting' : feature === 'brief_crm' || feature === 'meeting_crm' ? 'tasks' : 'group'}`)"
            :rows="5"
            :max-rows="12"
          />
          <VTextarea v-if="brain.question" v-model="question" :label="t('admin.osmap.probe.question')" :rows="1" :max-rows="4" />
          <div v-if="brain.kind" class="pp__row">
            <span class="pp__label">{{ t('admin.osmap.probe.groupKind') }}</span>
            <VSegmented v-model="briefKind" size="sm" :options="kindOptions" :aria-label="t('admin.osmap.probe.groupKind')" />
          </div>
          <VSwitch
            v-model="execute"
            size="sm"
            :disabled="!brain.execute"
            :label="t('admin.osmap.probe.execute')"
            :description="brain.execute ? undefined : t('admin.osmap.probe.executeOff')"
          />
        </template>

        <template v-else-if="kind !== 'agent' && kind !== 'health'">
          <VTextarea
            v-model="text"
            :label="kind === 'hold' ? t('admin.osmap.probe.question') : t('admin.osmap.probe.text')"
            :rows="kind === 'wake' ? 1 : 3"
            :max-rows="10"
          />
          <div v-if="kind === 'tts-text'" class="pp__row">
            <span class="pp__label">{{ t('admin.osmap.probe.mode') }}</span>
            <VSegmented v-model="mode" size="sm" :options="modeOptions" :aria-label="t('admin.osmap.probe.mode')" />
          </div>
          <VSwitch v-if="kind === 'hold'" v-model="useLlm" size="sm" :label="t('admin.osmap.probe.useLlm')" />
        </template>
      </div>

      <!-- narx - ishga tushirishdan OLDIN ko'rinadi -->
      <p v-if="costHint" class="pp__cost" :class="{ 'is-paid': paid }">
        <TriangleAlert v-if="paid" :size="14" :stroke-width="1.75" aria-hidden="true" />
        {{ costHint }}
      </p>

      <div v-if="confirming" class="pp__confirm" role="alertdialog" :aria-label="t('admin.osmap.probe.costTitle')">
        <p class="pp__confirm-title">{{ t('admin.osmap.probe.costTitle') }}</p>
        <p class="pp__confirm-body">{{ costHint }}</p>
        <div class="pp__row">
          <VButton size="sm" variant="primary" :icon="Play" @click="onRun">{{ t('admin.osmap.probe.confirm') }}</VButton>
          <VButton size="sm" variant="ghost" @click="confirming = false">{{ t('admin.osmap.probe.cancel') }}</VButton>
        </div>
      </div>

      <div v-else class="pp__row">
        <VButton size="sm" variant="primary" :icon="Play" :loading="busy" :disabled="!canRun" @click="onRun">
          {{ result ? t('admin.osmap.probe.again') : t('admin.osmap.probe.run') }}
        </VButton>
        <VButton v-if="busy || speakTimes?.playing" size="sm" variant="ghost" :icon="Square" @click="stopAll">
          {{ t('admin.osmap.probe.stop') }}
        </VButton>
      </div>

      <p v-if="error" class="pp__err" role="alert">
        <CircleAlert :size="14" :stroke-width="1.75" aria-hidden="true" />
        {{ error }}
      </p>

      <!-- natija -->
      <div v-if="result" class="pp__out" aria-live="polite">
        <div class="pp__status">
          <VBadge :tone="result.ok ? 'good' : 'crit'" size="sm" dot>
            {{ result.ok ? t('admin.osmap.probe.ok') : t('admin.osmap.probe.failed') }}
          </VBadge>
          <span v-if="speakTimes" class="pp__muted">
            {{ t('admin.osmap.probe.firstAudio') }}: {{ speakTimes.firstMs != null ? `${Math.round(speakTimes.firstMs)} ms` : '—' }}
            · {{ t('admin.osmap.probe.totalTime') }}:
            {{ speakTimes.totalMs != null ? `${(speakTimes.totalMs / 1000).toFixed(1)} s` : t('admin.osmap.probe.playing') }}
          </span>
        </div>
        <p v-if="result.cost_note" class="pp__cost is-paid">{{ result.cost_note }}</p>
        <h5 class="pp__h">{{ t('admin.osmap.probe.trace') }}</h5>
        <ProbeTrace :steps="result.trace" />
        <h5 class="pp__h">{{ t('admin.osmap.probe.result') }}</h5>
        <ProbeResultView :kind="kind" :result="result.result" :stage0="stage0" @play="playClip" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.pp {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--bg-subtle);
}
.pp__intro {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.5;
}
.pp__chip {
  padding: 1px 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  background: var(--surface);
  font-family: var(--font-mono);
  font-size: 12px;
}
.pp__form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.pp__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.pp__label {
  min-width: 72px;
  color: var(--text-3);
  font-size: 12px;
}
.pp__file {
  display: none;
}
.pp__muted {
  margin: 0;
  color: var(--text-3);
  font-size: 12.5px;
}
.pp__cost {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 0;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.5;
}
.pp__cost.is-paid {
  padding: 8px 10px;
  border-radius: var(--r-sm);
  background: var(--warn-soft);
  color: var(--warn-text);
  font-weight: 500;
}
.pp__confirm {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--warn);
  border-radius: var(--r-sm);
  background: var(--surface);
}
.pp__confirm-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}
.pp__confirm-body {
  margin: 0;
  color: var(--text-2);
  font-size: 12.5px;
}
.pp__err {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--crit-text);
  font-size: 13px;
}
.pp__out {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}
.pp__status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.pp__h {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
</style>

<script setup lang="ts">
/**
 * Voice conversation. Tap the orb, speak, pause — the pause ends the turn.
 *
 * The flow is: microphone → MediaRecorder → our /api/v1/stt/transcribe proxy →
 * the chat pipeline. Nothing here talks to the STT server directly; see
 * `api/stt.api.ts` for why.
 *
 * VISUALS (spec §4.3). A full-bleed `--bg` overlay with one brand orb in the
 * middle, a status caption under it and a single close button. The orb is one
 * element painted from tokens (so light/dark come for free); the microphone
 * level reaches it through a single CSS variable, `--lvl`, which drives its
 * scale and a soft ring. No blur layers, no blend modes: office laptops render
 * it without a GPU fan spinning up.
 *
 * The single most surprising failure this component has to explain is the
 * secure-context rule: over plain HTTP on a LAN address `navigator.mediaDevices`
 * is simply `undefined`. No prompt appears and no error is raised, so an
 * unguarded version looks like a broken button. That case gets its own state
 * and its own message.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Globe, Mic, MicOff, Volume2, X } from 'lucide-vue-next'
import { micAvailable, micBlockedByPolicy, secureUrl, transcribe } from '../api/stt.api'
import { canSpeak, holdClip, play, speakStream } from '../api/tts.api'
import { prepareSpeech } from './chat/readAloud'
import { preparedGreeting } from '../api/greeting'
import { localizeApiError } from '../api/errors'
import { ApiError } from '../api/http'
import { LOCALES } from '../i18n'
import VButton from '../ui/VButton.vue'
import VIconButton from '../ui/VIconButton.vue'
import { useFocusTrap } from '../ui/composables/useFocusTrap'

const props = defineProps<{
  open: boolean
  /** Sends the recognised text through the normal chat pipeline. Returns false
   *  if the pipeline is busy, so the panel can say so instead of losing it. */
  send: (text: string) => boolean
  /** True while the chat pipeline is running — drives the "thinking" state. */
  busy: boolean
  /** The most recent answer text, shown under the orb once it arrives. */
  answer?: string | null
  /** O'sha javobning savol kaliti (`X-Venera-Turn`) - ovoz admin izida unga bog'lanadi. */
  answerTurn?: string | null
  /** A holding phrase to say while the answer is still being worked out.
   *
   *  WHY THIS EXISTS. HRM/CRM lookups are not instant: measured, the rules
   *  route answers in 15.7 s at the median and 38.7 s at p90. The panel used
   *  to stand silent for all of it, and silence reads as "it did not hear
   *  me" — people repeat the question or close the panel. The backend times
   *  the wait and sends the phrase; this panel only has to say it.
   *
   *  `clip` is audio synthesised on the server ahead of time, picked by
   *  classifying the question (topic + tone) - so it plays with no TTS wait
   *  at all, and it can never contain anything the model made up. */
  hold?: { text?: string; clip?: string; at?: number } | null
  /** Spoken once when the panel opens, before listening starts.
   *
   *  Both ways in get it — the wake word and the button. Opening a voice
   *  panel and being met with silence reads as broken, and the person then
   *  has to guess whether to speak; hearing who answered settles that. The
   *  recording is prepared ahead of time, so it costs no wait either way. */
  greeting?: string | null
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { t, locale } = useI18n({ useScope: 'global' })

type State = 'idle' | 'listening' | 'transcribing' | 'confirm' | 'thinking' | 'error'
const state = ref<State>('idle')
const level = ref(0)          // 0..1, drives the orb
const heard = ref('')
// A note under the heard text: "recognised as Russian", "audio was cut".
const note = ref('')
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
// One turn = one recording + one upload. The id lets a late result from an
// earlier turn (closed panel, new tap) be ignored instead of sent to chat.
let turnId = 0
let turnTimer = 0
let aborter: AbortController | null = null

// --- Ovoz javobi (TTS) ------------------------------------------------------
// Birinchi bosqich ATAYLAB aks-sado: tanilgan matnning O'ZI o'qib beriladi.
// Shu tarzda STT va TTS zanjirini bitta gap bilan tekshirib bo'ladi - keyingi
// bosqichda o'qiladigan matn suhbat javobiga almashadi.
//
// Alohida `AbortController`: `aborter` transkripsiya tugashi bilan
// `teardown()` da bekor qilinadi, ya'ni undan keyin boshlangan sintez darhol
// uzilib ketardi.
// `<audio>` ning o'ziga havola SAQLANMAYDI - `play()` qaytargan `stop()`
// ijroni to'xtatish bilan birga object URL ni ham bo'shatadi, ya'ni element
// bilan to'g'ridan-to'g'ri ishlash uchun sabab qolmaydi.
let stopHandle: (() => void) | null = null
let speechAborter: AbortController | null = null
const speaking = ref(false)
/** Oxirgi tayyor audio - qayta tinglash uchun saqlanadi. */
const speech = ref<Blob | null>(null)
/** Brauzer avtomatik ijroga ruxsat bermadi: tugma ko'rsatiladi. */
const speechBlocked = ref(false)

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
    case 'confirm': return t('voiceUnsure')
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
  stopSpeaking()
}

/** Release every audio resource. Called on stop, on error, on close and on
 *  unmount — a missed path leaves the browser's recording indicator lit. */
/** Faqat IJRONI to'xtatadi. `stopHandle` orqali - `pause()` ning o'zi
 *  yetmaydi: object URL `play()` ichidagi `finish()` da bo'shatiladi, va uni
 *  chetlab o'tsak butun WAV tab yopilguncha xotirada qolib ketadi. */
function stopAudio() {
  stopHandle?.()
  stopHandle = null
  speaking.value = false
}

/** Ijroni ham, KETAYOTGAN so'rovni ham to'xtatadi.
 *
 *  Ikkisi ATAYLAB ajratilgan: qayta tinglash uchun ijroni to'xtatish kerak,
 *  lekin shu paytda ketayotgan yangi sintezni bekor qilish KERAK EMAS -
 *  aks holda "qayta tinglash" tugmasi joriy turnning javobini o'ldirardi. */
function stopSpeaking() {
  speechAborter?.abort()
  speechAborter = null
  stopAudio()
}

function teardown() {
  cancelAnimationFrame(rafId)
  rafId = 0
  clearTimeout(turnTimer)
  turnTimer = 0
  aborter?.abort()
  aborter = null
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
  // MAJBURIY: oldingi turnning javobi hali yangrayotgan bo'lishi mumkin
  // (masalan 'confirm' holatida sfera bosiladigan bo'lib qoladi). To'xtatmasak
  // karnaydan chiqayotgan ovoz mikrofonga qaytadan yozilardi va sukunat
  // o'lchagichini ham o'zi boshqarardi - ya'ni panel o'zini eshitardi.
  stopSpeaking()
  // Oldingi javob endi ekrandagi hech narsaga tegishli emas: tugma qolsa,
  // u boshqa gapning audiosini taklif qilardi.
  speech.value = null
  speechBlocked.value = false
  heard.value = ''
  note.value = ''
  errorText.value = ''
  errorHint.value = ''
  chunks = []
  speechSeen = false
  silenceSince = performance.now()
  clearTimeout(turnTimer)
  aborter?.abort()
  aborter = new AbortController()
  const turn = ++turnId

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
    // Guarded by the turn id: a timer left over from a previous turn must not
    // cut the next one short.
    turnTimer = window.setTimeout(() => {
      if (turn === turnId && state.value === 'listening') stopListening()
    }, MAX_TURN_MS)
  } catch {
    fail(t('voiceError'))
  }
}

function stopListening() {
  if (state.value !== 'listening' || !recorder) return
  state.value = 'transcribing'
  cancelAnimationFrame(rafId)
  rafId = 0
  clearTimeout(turnTimer)
  try { recorder.stop() } catch { fail(t('voiceError')) }
}

async function handleRecorded() {
  const turn = turnId
  const type = recorder?.mimeType || 'audio/webm'
  const blob = new Blob(chunks, { type })
  chunks = []
  // Keep the stream alive no longer than needed — the browser shows a recording
  // indicator for as long as a track is live.
  stream?.getTracks().forEach((track) => track.stop())
  stream = null

  // Nothing above the speech threshold during the whole turn (the 30 s timer
  // fired on a silent room): do not upload. The uz backend has no confidence
  // flag and will happily "hear" a word in room noise, which would then be
  // sent to chat as a question.
  if (!speechSeen || blob.size < 1200) {
    fail(t('voiceNoSpeech'))
    return
  }

  try {
    const result = await transcribe(blob, String(locale.value), aborter?.signal)
    // A newer turn started, or the panel closed, while this one was in flight.
    if (turn !== turnId || !props.open) return
    teardown()
    const text = result.text.trim()
    if (!text) {
      fail(t('voiceNoSpeech'))
      return
    }
    heard.value = text
    note.value = noteFor(result)
    // AKS-SADO OLIB TASHLANDI. Avval shu yerda tanilgan matnning O'ZI o'qib
    // berilardi - STT va TTS zanjirini bitta gap bilan tekshirish uchun.
    // Endi o'qiladigan matn SUHBAT JAVOBI (`speakAnswer`), va ikkisini birga
    // qoldirish odamga o'z savolini eshittirib, keyin javobni yana ~15 s
    // kutishga majbur qilardi.
    // Router docs: a low-confidence transcript has ~60-70% word error rate.
    // Do not act on it — show it and let the user decide.
    if (result.lowConfidence) {
      state.value = 'confirm'
      return
    }
    if (props.send(text)) {
      state.value = 'thinking'
    } else {
      // The chat pipeline is still answering the previous question. Keep the
      // text and let the person send it when it is free — never drop it.
      note.value = t('voicePipelineBusy')
      state.value = 'confirm'
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return
    if (turn !== turnId || !props.open) return
    fail(voiceErrorText(err))
  }
}

/** Errors from the proxy path (nginx 413/504) have no message envelope;
 *  map by status so the user never sees "Request failed (504)". */
function voiceErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 503: return t('voiceBusy')
      case 504: return t('voiceTooLong')
      case 413: return t('voiceTooLarge')
      case 415: return t('voiceFormat')
    }
  }
  return localizeApiError(err, t)
}

/**
 * Matnni ovoz bilan o'qib beradi: suhbat javobi, yoki tayyor yozuv
 * bo'lmaganda salomlashuv matni.
 *
 * Bu turnning ASOSIY ishi EMAS. Sintez yiqilsa javob EKRANDA qoladi - ya'ni
 * kelgan javob ishlamayotgan TTS tufayli yo'qolmaydi.
 */
async function speak(text: string, turn: number, after?: Promise<unknown>, turnKey?: string | null) {
  if (!canSpeak(String(locale.value))) return
  speechAborter?.abort()
  speechAborter = new AbortController()
  try {
    // Streamed: playback starts on the first chunk (~1 s) instead of after the
    // whole sentence is synthesised (~11 s for a long one). `speakStream`
    // resolves once the headers are in, which is also where every server-side
    // error has already surfaced — so a failure here is still a plain error,
    // not a silently truncated answer.
    const playback = await speakStream(text, String(locale.value), speechAborter.signal, after, turnKey)
    if (turn !== turnId || !props.open) {
      playback.stop()
      return
    }
    stopAudio()
    stopHandle = playback.stop
    speaking.value = true
    speechBlocked.value = false
    // The replay blob only exists once the stream has finished; wiring it up
    // here rather than awaiting it keeps the button from appearing early.
    void playback.recorded.then((blob) => {
      if (blob && turn === turnId) speech.value = blob
    })
    try {
      await playback.done
    } finally {
      speaking.value = false
      stopHandle = null
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return
    if (turn !== turnId || !props.open) return
    // 501 = ovoz serverda hali yoqilmagan (sir sozlanmagan). Bu nosozlik
    // EMAS, shuning uchun foydalanuvchiga xato ko'rsatilmaydi - u shunchaki
    // ovozsiz ishlaydi.
    if (err instanceof ApiError && err.status === 501) return
    // `note` ni BOSIB O'TMAYMIZ: u yerda "quvur band, o'zingiz yuboring"
    // yoki "yozuv kesildi" turgan bo'lishi mumkin, va ular ovoz
    // yiqilganidan ko'ra muhimroq.
    if (!note.value) note.value = t('voiceSpeakFailed')
  }
}

/**
 * Suhbat javobini o'qib beradi - ovozli turnning OXIRGI qadami.
 *
 * NEGA BUTUN JAVOB BIRGA, gap-gapga bo'lib emas: yuqoridagi xizmat
 * tokenlarni ~15 s jimlikdan keyin 0.02 s ichida BIRDAN yuboradi (jonli
 * o'lchangan, `docs/deploy-api.md`). Ya'ni "kelgan gapni darhol o'qish"
 * hech narsa tejamaydi - o'qish boshlanadigan payt baribir javob to'liq
 * kelgan payt bo'ladi, kod esa ikki barobar murakkab bo'lardi.
 */
/** The holding clip that is playing right now, if any.
 *
 *  The answer WAITS for it. That rule came from a measurement: HRM answered
 *  in 3-4 s while the clip itself is 2.5-3.3 s long, and cutting the clip the
 *  moment the answer arrived left people hearing half a sentence — which
 *  reads as broken, worse than silence. */
let holdPlaying: Promise<void> | null = null

/** Plays a ready-made holding clip while HRM/CRM works on the answer.
 *
 *  Guards, each one earned:
 *    * only while `thinking` and only for this turn — a clip that surfaces
 *      after the answer (or during the next question) talks over it;
 *    * one at a time — a follow-up that arrives while the previous clip still
 *      plays is dropped, never stacked;
 *    * clips only, never synthesised text — the point of a holding clip is
 *      that it costs no wait, and synthesising adds ~1.1 s;
 *    * failures are silent — it is a courtesy, not a feature to report.
 */
async function speakHold(cue: { clip?: string }, turn: number) {
  if (state.value !== 'thinking' || turn !== turnId || !props.open) return
  if (holdPlaying || !cue.clip || !canSpeak(String(locale.value))) return
  const blob = await holdClip(cue.clip)
  if (!blob || turn !== turnId || state.value !== 'thinking' || !props.open) return
  const playing = playBlob(blob)
  holdPlaying = playing
  try {
    await playing
  } finally {
    if (holdPlaying === playing) holdPlaying = null
  }
}

watch(() => props.hold, (cue) => {
  if (!cue?.clip) return
  void speakHold(cue, turnId)
})

async function speakAnswer(turn: number) {
  const { text, shortened } = prepareSpeech(props.answer || '')
  // Javob kelmadi (xato yoki bo'sh): JIM qolamiz. Xato matni suhbatda
  // ko'rinadi, va uni ovoz bilan takrorlash hech kimga yordam bermaydi.
  if (!text) return
  if (shortened && !note.value) note.value = t('voiceAnswerShortened')
  // A holding clip still playing is NEVER cut. The answer's TTS request goes
  // out now and buffers; playback starts the instant the clip ends.
  await speak(text, turn, holdPlaying ?? undefined, props.answerTurn)
}

/** Ijro. Rad etilishi XATO EMAS: brauzer avtomatik ijroga ruxsat bermasligi
 *  mumkin (foydalanuvchi harakati bo'lmasa), va bunda tugma ko'rsatiladi. */
async function playBlob(blob: Blob) {
  stopAudio()                 // stopSpeaking() EMAS - so'rov tirik qolsin
  const handle = play(blob)
  stopHandle = handle.stop
  speaking.value = true
  speechBlocked.value = false
  try {
    await handle.done
  } catch {
    speechBlocked.value = true
  } finally {
    speaking.value = false
    stopHandle = null
  }
}

/** "Qayta tinglash" / avtomatik ijro rad etilganda "Tinglash". */
function replay() {
  if (speech.value) void playBlob(speech.value)
}

/** Notes shown under the heard text. Language is never mentioned here: voice
 *  always runs in the UI language and the system does not detect or switch. */
function noteFor(r: { truncated: boolean }): string {
  return r.truncated ? t('voiceTruncatedNote') : ''
}

/** "Send anyway" after a low-confidence transcript. */
function confirmSend() {
  if (state.value !== 'confirm' || !heard.value) return
  if (props.send(heard.value)) {
    note.value = ''
    state.value = 'thinking'
  } else {
    note.value = t('voicePipelineBusy')
  }
}

function close() {
  teardown()
  stopSpeaking()
  speech.value = null
  speechBlocked.value = false
  turnId++          // anything still in flight is now stale
  state.value = 'idle'
  heard.value = ''
  note.value = ''
  emit('close')
}

function onOrbClick() {
  if (state.value === 'listening') stopListening()
  else if (state.value === 'idle' || state.value === 'error' || state.value === 'confirm') void startListening()
}

// Quvurning tugashi = javob KELDI: "thinking" holati shunda tugaydi va
// javob AYNAN shu paytda o'qiladi.
//
// NEGA `answer` KUZATILMAYDI: ChatView javobni token-token yig'adi va har
// tokenda `answer` ni yangilaydi, ya'ni uni kuzatish har token uchun yangi
// sintez so'rovi bo'lardi. `busy` esa turn oxirida BIR MARTA o'zgaradi.
//
// `state === 'thinking'` sharti: savol SHU PANELdan ketgani. Pastdagi
// maydonga qo'lda yozilgan savol ovoz bilan o'qilmaydi - odam o'zi o'qiyapti.
//
// `flush: 'post'`: `answer` hisoblanadigan qiymat va `busy` bilan bir tikda
// yangilanadi, post bosqichida u ANIQ oxirgi holatda bo'ladi.
watch(() => props.busy, (busy) => {
  if (busy || state.value !== 'thinking') return
  state.value = 'idle'
  void speakAnswer(turnId)
}, { flush: 'post' })
/** Greets, then listens. The order matters: the greeting comes out of the
 *  speakers, and `startListening()` stops any playback before opening the
 *  microphone, so the assistant never records itself saying hello. */
async function greetThenListen(text: string) {
  // The state is already 'idle' here: the `open` watcher resets it on close.
  // Assigning it again would narrow its type and hide the check below.
  const turn = turnId
  // The prepared recording first: the greeting is fixed, so synthesising it
  // again would make the person wait ~2 s in a GPU queue for a sentence we
  // already know. Live synthesis stays as the fallback, so a missing or
  // unreachable asset costs latency, never the greeting itself.
  const prepared = await preparedGreeting(String(locale.value))
  if (turn !== turnId || !props.open) return
  if (prepared) {
    speech.value = prepared
    await playBlob(prepared)
  } else {
    await speak(text, turn)
  }
  // The panel may have been closed, or the person may have tapped the orb
  // themselves while the greeting played — either way this turn is stale.
  if (turn !== turnId || !props.open || state.value === 'listening') return
  void startListening()
}

// Opening with a greeting is the wake-word path.
watch(() => props.open, (open) => {
  if (!open) return
  const greeting = props.greeting
  if (greeting) void greetThenListen(greeting)
}, { flush: 'post' })

// Closing the panel must release the microphone even if `close()` wasn't used.
watch(() => props.open, (open) => {
  if (open) return
  teardown()
  stopSpeaking()
  turnId++
  state.value = 'idle'
  heard.value = ''
  note.value = ''
  speech.value = null
  speechBlocked.value = false
})
onBeforeUnmount(() => { teardown(); stopSpeaking() })

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.preventDefault(); close() }
  // Space faqat panelning o'zida (fokus ochilganda shu yerda) sharni bosadi. Tugma
  // ustida Space o'sha tugmaniki: "Yopish" yoki "Baribir yuborish" tinglashni yoqib
  // yubormasin, shar tugmasi esa o'zi bosiladi (ikki marta emas).
  if (e.key === ' ' && supported.value && e.target === e.currentTarget) { e.preventDefault(); onOrbClick() }
}

// Ochilganda fokus panelga (Space / Esc darhol ishlasin), ichida aylanadi, yopilganda
// ochgan tugmaga (mikrofon) qaytadi. Panel <body> ga teleport - butun ekranni qoplaydi.
const rootRef = ref<HTMLElement | null>(null)
useFocusTrap(rootRef, () => props.open, { initialFocus: () => rootRef.value })

/** One CSS variable carries the microphone level into the stylesheet; every
 *  reactive part of the orb (scale, rim glow, halo, wisp opacity) reads it
 *  there. Keeping the maths in CSS means no per-frame style object churn. */
const orbVars = computed(() => ({ '--lvl': level.value.toFixed(3) }))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      ref="rootRef"
      class="vp"
      :data-state="supported ? state : 'unsupported'"
      :style="orbVars"
      role="dialog"
      aria-modal="true"
      :aria-label="t('voiceTitle')"
      tabindex="-1"
      @keydown="onKeydown"
    >
      <VIconButton class="vp-close" :label="t('voiceClose')" :icon="X" size="lg" tooltip-placement="bottom" @click="close" />

      <div class="vp-stage">
        <button
          type="button"
          class="vp-orb"
          :disabled="!supported || state === 'transcribing' || state === 'thinking'"
          :aria-label="state === 'listening' ? t('voiceStopListening') : t('voiceTapToSpeak')"
          @click="onOrbClick"
        >
          <span class="vp-icon" aria-hidden="true">
            <MicOff v-if="!supported" :size="28" :stroke-width="1.75" />
            <Mic v-else :size="28" :stroke-width="1.75" />
          </span>
        </button>
      </div>

      <div class="vp-text">
        <p class="vp-status" :class="{ 'vp-status--bad': state === 'error' || !supported }" role="status">{{ statusText }}</p>

        <p v-if="!supported" class="vp-sub">
          {{ t('voiceNeedsHttpsHow') }}<br />
          <a class="vp-link" :href="secureUrl()">{{ secureUrl() }}</a>
        </p>
        <p v-else-if="errorHint" class="vp-sub">{{ errorHint }}</p>
        <p v-else-if="state === 'idle' && !heard" class="vp-sub">{{ t('composer.voiceHint') }}</p>

        <p v-if="heard" class="vp-heard">
          <span class="vp-heard-label">{{ t('voiceHeard') }}</span>
          {{ heard }}
        </p>
        <p v-if="note" class="vp-note">{{ note }}</p>

        <!-- Ovoz javobi. Ijro davom etayotgani ko'rinib turadi, chunki panel
             o'zi jim: shar esa mikrofonga qaraydi, karnayga emas. -->
        <p v-if="speaking" class="vp-speaking">
          <Volume2 :size="16" :stroke-width="1.75" aria-hidden="true" />
          {{ t('voiceSpeaking') }}
        </p>
        <div v-else-if="speech" class="vp-actions">
          <VButton variant="ghost" size="sm" :icon="Volume2" @click="replay">
            {{ speechBlocked ? t('voicePlay') : t('voiceReplay') }}
          </VButton>
        </div>

        <div v-if="state === 'confirm'" class="vp-actions">
          <VButton variant="secondary" @click="onOrbClick">{{ t('voiceRetry') }}</VButton>
          <VButton variant="primary" @click="confirmSend">{{ t('voiceSendAnyway') }}</VButton>
        </div>
        <p v-if="answer && state === 'idle'" class="vp-answer">{{ answer }}</p>

        <div v-if="state === 'error'" class="vp-actions">
          <VButton variant="secondary" @click="onOrbClick">{{ t('voiceRetry') }}</VButton>
        </div>
      </div>

      <!-- Tanish tili: kichik belgi; to'liq izoh ekran o'quvchi uchun. -->
      <p v-if="supported" class="vp-foot">
        <Globe :size="14" :stroke-width="1.75" aria-hidden="true" />
        <span aria-hidden="true">{{ langLabel }}</span>
        <span class="sr-only">{{ t('voiceLangNote', { lang: langLabel }) }}</span>
      </p>
    </div>
  </Teleport>
</template>

<style scoped>
/* Butun ekran, sahifa foni - hech qanday "sahna" rangi yo'q: mavzu tokenlardan. */
.vp {
  --orb: clamp(136px, 26vmin, 200px);
  position: fixed;
  inset: 0;
  z-index: var(--z-dialog);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-6);
  padding:
    max(var(--s-16), env(safe-area-inset-top, 0px)) var(--s-6)
    max(var(--s-16), calc(env(safe-area-inset-bottom, 0px) + var(--s-12)));
  overflow-y: auto;
  background: var(--bg);
  color: var(--text);
  outline: none;
  animation: vp-in var(--dur-3) var(--ease-out) both;
}
.vp:focus-visible {
  outline: none;
}
@keyframes vp-in {
  from {
    opacity: 0;
  }
}

.vp-close {
  position: absolute;
  top: max(var(--s-4), env(safe-area-inset-top, 0px));
  right: max(var(--s-4), env(safe-area-inset-right, 0px));
}

/* ── Shar ──────────────────────────────────────────────────────────────── */
/* Sahna sharning nafasini ko'taradi (tinch holatda sekin, "o'ylayapti"da tezroq);
   sharning o'zi esa ovoz balandligi (--lvl) bilan kattalashadi - ikki transform
   bir elementda to'qnashmasin. */
.vp-stage {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: calc(var(--orb) * 1.5);
  height: calc(var(--orb) * 1.5);
  animation: vp-breathe 6s ease-in-out infinite;
}
@keyframes vp-breathe {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.04);
  }
}

.vp-orb {
  position: relative;
  display: grid;
  place-items: center;
  width: var(--orb);
  height: var(--orb);
  padding: 0;
  border-radius: var(--r-full);
  background:
    radial-gradient(circle at 34% 28%, color-mix(in srgb, var(--brand-soft) 85%, transparent) 0%, transparent 36%),
    radial-gradient(120% 120% at 30% 25%, var(--brand-2) 0%, var(--brand) 55%, var(--serious-text) 100%);
  box-shadow:
    0 0 0 calc(var(--lvl) * 20px) color-mix(in srgb, var(--brand) 12%, transparent),
    0 calc(16px + var(--lvl) * 12px) calc(48px + var(--lvl) * 40px) -12px color-mix(in srgb, var(--brand) 55%, transparent);
  transform: scale(calc(1 + var(--lvl) * 0.1));
  transition:
    transform 90ms linear,
    box-shadow 90ms linear,
    filter var(--dur-3) var(--ease-out),
    opacity var(--dur-3) var(--ease-out);
}
.vp-orb:disabled {
  cursor: default;
}
.vp-orb:focus-visible {
  outline-offset: 6px;
}
/* Tinglayotganda - ovozga ergashuvchi yupqa halqa: "sizni eshityapman". */
.vp-orb::after {
  content: '';
  position: absolute;
  inset: -10px;
  border: 1.5px solid color-mix(in srgb, var(--brand) 40%, transparent);
  border-radius: inherit;
  opacity: 0;
  transform: scale(calc(1 + var(--lvl) * 0.22));
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform 90ms linear;
  pointer-events: none;
}
.vp-icon {
  display: grid;
  place-items: center;
  color: var(--on-ink);
  transition: opacity var(--dur-3) var(--ease-out);
}

/* ── Holatlar ──────────────────────────────────────────────────────────── */
.vp[data-state='listening'] .vp-stage {
  animation: none;
}
.vp[data-state='listening'] .vp-orb::after {
  opacity: calc(0.35 + var(--lvl));
}
.vp[data-state='listening'] .vp-icon {
  opacity: 0.4;
}
.vp[data-state='transcribing'] .vp-stage,
.vp[data-state='thinking'] .vp-stage {
  animation-duration: 1.6s;
}
/* Tasdiq: shar kutadi, xiraroq - odam qaror qilguncha. */
.vp[data-state='confirm'] .vp-orb {
  opacity: 0.7;
}
/* Xato / qo'llab-quvvatlanmaydi: rang oqib ketadi. */
.vp[data-state='error'] .vp-orb,
.vp[data-state='unsupported'] .vp-orb {
  filter: grayscale(1);
  opacity: 0.45;
}
.vp[data-state='error'] .vp-stage,
.vp[data-state='unsupported'] .vp-stage {
  animation: none;
}

/* ── Matn ──────────────────────────────────────────────────────────────── */
.vp-text {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  width: 100%;
  max-width: 440px;
  text-align: center;
}
.vp-status {
  color: var(--text);
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.vp-status--bad {
  color: var(--crit-text);
}
.vp-sub {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-wrap: pretty;
}
.vp-link {
  color: var(--text);
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
  word-break: break-all;
}
.vp-heard {
  margin-top: var(--s-2);
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
}
.vp-heard-label {
  display: block;
  margin-bottom: 2px;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.vp-note {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.vp-speaking {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  animation: vp-speak 1.6s ease-in-out infinite;
}
@keyframes vp-speak {
  0%,
  100% {
    opacity: 0.6;
  }
  50% {
    opacity: 1;
  }
}
.vp-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--s-2);
  margin-top: var(--s-2);
}
.vp-answer {
  max-height: 120px;
  margin-top: var(--s-2);
  overflow-y: auto;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  text-align: start;
}
.vp-foot {
  position: absolute;
  bottom: max(var(--s-5), env(safe-area-inset-bottom, 0px));
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

@media (prefers-reduced-motion: reduce) {
  .vp,
  .vp-stage,
  .vp-speaking {
    animation: none;
  }
  /* Ovoz darajasi baribir ko'rinadi (halqa), lekin shar o'zi silkinmaydi. */
  .vp-orb,
  .vp-orb::after {
    transform: none;
    transition: none;
  }
}
</style>

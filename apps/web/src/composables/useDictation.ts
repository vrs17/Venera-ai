// Ovoz bilan yozish (diktovka): kompozerdagi mikrofon tugmasi.
//
// NIMA QILADI. Mikrofon -> MediaRecorder -> /api/v1/stt/transcribe -> matn
// yozish maydoniga QO'YILADI. Hech narsa o'zi yuborilmaydi: odam matnni ko'radi,
// tuzatadi va o'zi yuboradi. Jonli ovozli suhbat (VoicePanel) - boshqa narsa, u
// keyinroq qaytadi; bu fayl unga tegmaydi.
//
// QAYTA ISHLATILGANI, ATAYLAB. Yozib olish yo'li VoicePanel bilan bir xil
// (MediaRecorder, keyin `transcribe()` ichidagi `toWav16k`): bu real mashinalarda
// matnga aylanishi isbotlangan yagona yo'l. getUserMedia sozlamalari ham AYNAN
// o'sha - useWakeWord.ts boshidagi izohga qarang: brauzer ishlovini o'chirib
// ko'rilgan, o'lchangan va hech narsa yutmagan.
//
// HOLATLAR: idle -> starting (ruxsat so'ralyapti) -> recording -> transcribing
// -> idle. Har qanday holatdan `cancel()` - darhol idle. Natija (matn, bo'sh,
// bekor, xato) BITTA yo'ldan - `onOutcome` - keladi: 120 s chegarasida yozuv
// o'zi tugaydi va natija tugma bosilmasa ham shu yerga tushishi kerak.
//
// TO'LQIN. Har BAR_MS da bitta ustun: shu oynadagi RMS, quloqqa mos shkalada
// (`levelOf` - chiziqli RMS'da past ovoz ko'rinmay qolardi, chiziqli desibelda
// esa oddiy gap ham shiftga yaqin turardi). Darajalar reaktiv EMAS: ular
// sekundiga ~14 marta keladi va canvas ularni o'zi o'qiydi - Vue'ga har biri
// uchun qayta chizish kerak emas.

import { getCurrentScope, markRaw, nextTick, onScopeDispose, readonly, ref } from 'vue'
import { micAvailable, micBlockedByPolicy, transcribe } from '../api/stt.api'

export type DictationState = 'idle' | 'starting' | 'recording' | 'transcribing'

/** Mikrofon nega ochilmadi - chaqiruvchi buni odam tilidagi matnga aylantiradi. */
export type DictationStartFailure = 'insecure' | 'policy' | 'denied' | 'noDevice' | 'error'

export type DictationOutcome =
  | { kind: 'text'; text: string; truncated: boolean }
  | { kind: 'empty' }
  /** `silent` - juda qisqa bosish (adashib bosilgan): odamga hech narsa aytilmaydi. */
  | { kind: 'cancelled'; silent: boolean }
  | { kind: 'error'; error: unknown }

/** To'lqin ustunlari: 0..1, eng yangisi oxirida. Reaktiv emas (yuqoridagi izoh). */
export interface LevelStream {
  bars: number[]
  /** Jami qo'shilgan ustunlar - chizuvchi yangisi kelganini shundan biladi. */
  count: number
  /** Oxirgi ustun qo'shilgan payt (`performance.now()`) - silliq siljish uchun. */
  pushedAt: number
}

/** Bitta ustun oynasi. 60-80 ms: undan qisqasi bo'g'in ichida titraydi,
 *  uzunrog'i so'zlarni bitta do'ngga qo'shib yuboradi. */
export const BAR_MS = 70
/** Undan uzun gap - diktovka emas; yuklash ham (WAV ~3.8 MB) chegarada. */
const MAX_MS = 120_000
/** Undan qisqasi - adashib bosilgan tugma: yuklanmaydi, jim bekor qilinadi. */
const MIN_MS = 400
/** VoicePanel'dagi bilan BIR XIL chegara va bir xil o'lchov (1024 namunalik
 *  oyna). Butun yozuvda undan baland narsa bo'lmasa - yuklanmaydi: uz backend
 *  ishonch belgisini bermaydi va xona shovqinidan ham "so'z eshitib" qo'yadi. */
const SPEECH_RMS = 0.045
const SPEECH_WINDOW = 1024
/** Ustun bo'yi shkalasi. -56 dB va undan pasti - jim xona (nuqta); -6 dB -
 *  to'liq ustun. O'LCHANGAN (Chromium, soxta mikrofonda haqiqiy o'zbekcha gap,
 *  shu getUserMedia sozlamalari bilan): avto-kuchaytirgich gapni -18 dB atrofiga
 *  (p50) tortadi, p90 -14 dB, boshidagi bir-ikki soniyada esa -7 dB gacha
 *  "otib" yuboradi. Oldingi chiziqli desibel shkalasi (-56..-10) bilan oddiy gap
 *  0.83-0.91 da, boshlanishi esa shiftda turardi - to'lqin bir xil baland
 *  "panjara" bo'lib qolardi. */
const DB_FLOOR = -56
const DB_FULL = -6
/** Ustun bo'yi = amplitudaning kvadrat ildizi (desibelda: har 40 dB - 10 marta).
 *  Bo'g'inlar orasidagi 4-6 dB farq ustunda 15-20% bo'lib ko'rinadi; oddiy gap
 *  yarim bo'yda, baland bo'g'in ~0.8-0.9 da, past ovoz (-33 dB) ham ko'rinadi.
 *  Pastdagi ayirma - jimlik aynan nuqta bo'lsin (0), xira ustuncha emas. */
const LEVEL_ZERO = 10 ** ((DB_FLOOR - DB_FULL) / 40)
/** Eng keng ekranni ham to'ldiradi (6 px qadam * 480 = 2880 px). */
const MAX_BARS = 480

/** RMS -> 0..1, quloqqa mos (yuqoridagi izoh). */
export function levelOf(rms: number): number {
  if (!(rms > 0)) return 0
  const db = 20 * Math.log10(rms)
  const amp = 10 ** ((db - DB_FULL) / 40)
  return Math.min(1, Math.max(0, (amp - LEVEL_ZERO) / (1 - LEVEL_ZERO)))
}

/** Brauzer yoza oladigan konteyner. Safari'da webm yo'q. VoicePanel'dagi ro'yxat
 *  bilan bir xil - o'sha yerdan import qilib bo'lmaydi (SFC ichida). */
function pickMime(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  for (const type of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) return type
  }
  return ''
}

function newAudioContext(): AudioContext | null {
  const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctx) return null
  try {
    return new Ctx()
  } catch {
    return null
  }
}

export interface DictationOptions {
  /** Tanish tili - UI tili (VoicePanel kabi: tizim tilni o'zi aniqlamaydi). */
  language: () => string
  onOutcome: (outcome: DictationOutcome) => void
}

export function useDictation(options: DictationOptions) {
  const state = ref<DictationState>('idle')
  /** Yozuv davomiyligi, butun soniya - faqat soniya almashganda yangilanadi. */
  const elapsed = ref(0)
  const levels: LevelStream = markRaw({ bars: [], count: 0, pushedAt: 0 })

  // Jonli audio obyektlari - oddiy o'zgaruvchilar, ref EMAS: Vue jonli
  // MediaStream'ni chuqur proxy qilib o'tirmasin.
  let stream: MediaStream | null = null
  let ctx: AudioContext | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let analyser: AnalyserNode | null = null
  let buffer: Float32Array<ArrayBuffer> | null = null
  let windowSize = 0
  let recorder: MediaRecorder | null = null
  let chunks: Blob[] = []
  let timer = 0
  let startedAt = 0
  let speechSeen = false
  let aborter: AbortController | null = null
  // Har yozuv - yangi raqam. Kech kelgan natija (bekor qilingan yozuvning
  // javobi, ruxsat oynasi yopilgandan keyin kelgan oqim) shu bilan tashlanadi.
  let session = 0

  function resetLevels() {
    levels.bars.length = 0
    levels.count = 0
    levels.pushedAt = 0
  }

  function push(level: number) {
    levels.bars.push(level)
    if (levels.bars.length > MAX_BARS) levels.bars.splice(0, levels.bars.length - MAX_BARS)
    levels.count++
    levels.pushedAt = performance.now()
  }

  /** Mikrofonni bo'shatadi. Bitta yo'l ham qolib ketsa brauzerning "yozilyapti"
   *  belgisi yonib qoladi va odam hali ham tinglanyapman deb o'ylaydi. */
  function releaseMic() {
    window.clearInterval(timer)
    timer = 0
    source?.disconnect()
    source = null
    analyser = null
    buffer = null
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    if (ctx && ctx.state !== 'closed') void ctx.close().catch(() => {})
    ctx = null
  }

  function teardown() {
    aborter?.abort()
    aborter = null
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null
      try {
        recorder.stop()
      } catch {
        /* allaqachon to'xtayapti */
      }
    }
    recorder = null
    chunks = []
    releaseMic()
  }

  function settle(outcome: DictationOutcome) {
    teardown()
    state.value = 'idle'
    options.onOutcome(outcome)
  }

  /** Bitta ustun: oxirgi BAR_MS dagi RMS. Taymer ham shu yerda yuradi. */
  function sample() {
    if (state.value !== 'recording') return
    const ms = performance.now() - startedAt
    const seconds = Math.floor(ms / 1000)
    if (seconds !== elapsed.value) elapsed.value = seconds
    if (ms >= MAX_MS) {
      finish()
      return
    }
    if (!analyser || !buffer) {
      push(0)
      return
    }
    analyser.getFloatTimeDomainData(buffer)
    const from = buffer.length - windowSize
    let sum = 0
    let part = 0
    let partLen = 0
    for (let i = from; i < buffer.length; i++) {
      const square = buffer[i] * buffer[i]
      sum += square
      part += square
      if (++partLen === SPEECH_WINDOW) {
        if (Math.sqrt(part / SPEECH_WINDOW) > SPEECH_RMS) speechSeen = true
        part = 0
        partLen = 0
      }
    }
    const rms = Math.sqrt(sum / windowSize)
    if (rms > SPEECH_RMS) speechSeen = true
    push(levelOf(rms))
  }

  /** Mikrofonni ochib yozishni boshlaydi. Xato sababini QAYTARADI (odamga nima
   *  deyish - chaqiruvchining ishi); muvaffaqiyat yoki oraliqdagi bekor - null. */
  async function start(): Promise<DictationStartFailure | null> {
    if (state.value !== 'idle') return null
    // HTTP + LAN manzilda `navigator.mediaDevices` umuman yo'q: na so'rov, na
    // xato. Tekshirmasak tugma "buzuq" ko'rinardi.
    if (!micAvailable()) return 'insecure'
    const mine = ++session
    resetLevels()
    elapsed.value = 0
    speechSeen = false
    chunks = []
    state.value = 'starting'
    // AudioContext - SHU bosishning ichida, birinchi `await` dan oldin: Safari
    // foydalanuvchi harakatidan tashqarida yaratilgan kontekstni 'suspended'
    // qoldiradi va analyser jim turadi - to'lqin "o'lik" ko'rinardi.
    ctx = newAudioContext()
    // Bir tik kutiladi: ota-komponent `state` ga qarab "Salom Venera"
    // tinglovchisini to'xtatadi va mikrofonni bo'shatadi (VoicePanel bilan
    // bir xil kelishuv - `paused`). Aks holda u diktovkani ham eshitib, uni
    // serverga "uyg'otish so'zi" deb yuborardi.
    await nextTick()
    if (mine !== session) return null

    let media: MediaStream
    try {
      // AYNAN VoicePanel va useWakeWord dagidek - yuqoridagi izohga qarang.
      media = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
    } catch (err) {
      if (mine !== session) return null
      teardown()
      state.value = 'idle'
      const name = (err as DOMException)?.name
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        // Bir xil xato nomi: "odam Bloklash'ni bosdi" va "server sarlavhasi
        // taqiqlaydi". Ikkinchisida so'rov ham, brauzerda tuzatish ham yo'q.
        return micBlockedByPolicy() ? 'policy' : 'denied'
      }
      if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'noDevice'
      return 'error'
    }
    // Ruxsat oynasi turganda odam bekor qildi: kech kelgan oqim darhol yopiladi.
    if (mine !== session) {
      media.getTracks().forEach((track) => track.stop())
      return null
    }
    stream = media

    try {
      if (!ctx) ctx = newAudioContext()
      if (ctx) {
        if (ctx.state !== 'running') void ctx.resume().catch(() => {})
        // Oyna BAR_MS ni to'liq qamrasin: fftSize - ikkining darajasi, undan
        // oxirgi `windowSize` namuna olinadi (48 kHz da 4096 dan 3360).
        windowSize = Math.max(SPEECH_WINDOW, Math.round((ctx.sampleRate * BAR_MS) / 1000))
        analyser = ctx.createAnalyser()
        analyser.fftSize = Math.min(32768, 2 ** Math.ceil(Math.log2(windowSize)))
        windowSize = Math.min(windowSize, analyser.fftSize)
        buffer = new Float32Array(analyser.fftSize)
        source = ctx.createMediaStreamSource(media)
        source.connect(analyser)
      } else {
        // Darajani o'lchab bo'lmaydi - "gap bo'lmadi" deb yozuvni tashlamaylik.
        speechSeen = true
      }
      const mimeType = pickMime()
      recorder = new MediaRecorder(media, mimeType ? { mimeType } : undefined)
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data)
      }
      recorder.start()
    } catch {
      teardown()
      state.value = 'idle'
      return 'error'
    }
    startedAt = performance.now()
    state.value = 'recording'
    timer = window.setInterval(sample, BAR_MS)
    return null
  }

  /** "Tayyor": yozuvni to'xtatib matnga aylantiradi. */
  function finish() {
    // Hali hech narsa yozilmagan (ruxsat kutilyapti) - aylantiradigan narsa yo'q.
    if (state.value === 'starting') {
      cancel(true)
      return
    }
    if (state.value !== 'recording' || !recorder) return
    if (performance.now() - startedAt < MIN_MS) {
      cancel(true)
      return
    }
    state.value = 'transcribing'
    window.clearInterval(timer)
    timer = 0
    const mine = session
    const rec = recorder
    rec.onstop = () => void upload(mine, rec.mimeType)
    try {
      rec.stop()
    } catch (err) {
      settle({ kind: 'error', error: err })
    }
  }

  async function upload(mine: number, type: string) {
    if (mine !== session) return
    const blob = new Blob(chunks, { type: type || 'audio/webm' })
    chunks = []
    recorder = null
    // Mikrofon kerak bo'lgandan bir lahza ham ortiq ochiq turmasin.
    releaseMic()
    if (!speechSeen || blob.size < 1200) {
      settle({ kind: 'empty' })
      return
    }
    aborter = new AbortController()
    try {
      const result = await transcribe(blob, options.language(), aborter.signal)
      if (mine !== session) return
      const text = result.text.trim()
      settle(text ? { kind: 'text', text, truncated: result.truncated } : { kind: 'empty' })
    } catch (err) {
      if (mine !== session) return
      if (err instanceof DOMException && err.name === 'AbortError') return
      settle({ kind: 'error', error: err })
    }
  }

  /** Bekor qilish: yozuv ham, ketayotgan so'rov ham tashlanadi. */
  function cancel(silent = false) {
    if (state.value === 'idle') return
    session++
    settle({ kind: 'cancelled', silent })
  }

  // Komponent yo'qolsa (chiqish, sahifa almashishi) - mikrofon albatta yopiladi.
  // Natija e'lon qilinmaydi: uni ko'rsatadigan joy ham qolmadi.
  if (getCurrentScope()) {
    onScopeDispose(() => {
      session++
      teardown()
      state.value = 'idle'
    })
  }

  return {
    state: readonly(state),
    elapsed: readonly(elapsed),
    levels,
    start,
    finish,
    cancel: () => cancel(false),
  }
}

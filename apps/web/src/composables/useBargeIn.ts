// Bo'lib gapirish ("barge-in"): Barno javobni o'qiyotganda odam gapirib qolsa,
// o'qish to'xtaydi va yangi turn boshlanadi. Jonli suhbat (VoicePanel) uchun.
//
// QANDAY. Javob yangrayotganda mikrofonning ALOHIDA, arzon tinglagichi ochiladi:
// faqat AnalyserNode, yozuv yo'q, serverga hech narsa ketmaydi. Odam gapirgani
// aniqlanganda o'sha oqim (MediaStream) chaqiruvchiga BERILADI - u yangi turnni
// shu oqimdan yozadi. Qayta getUserMedia kutilmaydi, birinchi so'zlar yo'qolmaydi.
//
// AKS-SADO. Karnaydan chiqqan Barno ovozi mikrofonga qaytadi; brauzerning
// echoCancellation'i uni hamma joyda ham olib tashlamaydi. Shuning uchun ijro
// boshidagi CALIBRATE_MS davomida aks-sado darajasi o'rganiladi (odam bu
// oynada deyarli hech qachon gapirmaydi) va chegara undan ECHO_FACTOR baravar
// baland qo'yiladi. Quloqchinda aks-sado yo'q - chegara MIN_RMS ga tushadi.
//
// BIR MARTALIK YO'TAL HISOBLANMAYDI: oxirgi WINDOW_MS ichidagi kadrlarning
// HIT_RATIO qismi chegaradan baland bo'lishi kerak. Gap so'zlar orasidagi
// pauzalar bilan keladi - "hamma kadr baland" talabi hech qachon bajarilmasdi.
//
// TIMER, requestAnimationFrame EMAS: rAF yashirin vkladkada to'xtaydi, javob
// esa o'qilishda davom etadi.

import { getCurrentScope, onScopeDispose, readonly, ref } from 'vue'

/** Aks-sado bo'lmaganda ham shundan past ovoz gap deb olinmaydi (panelda 0.045). */
const MIN_RMS = 0.06
const ECHO_FACTOR = 2.2
const CALIBRATE_MS = 500
const WINDOW_MS = 400
const HIT_RATIO = 0.6
/** Shuncha qismi baland - "gap yig'ilyapti": tuman rangi o'zgaradi. */
const BUILDING_RATIO = 0.3
const TICK_MS = 30

export interface BargeInOptions {
  /** Odam gapirdi. Oqim endi CHAQIRUVCHINIKI - u to'xtatishi shart. */
  onBarge: (stream: MediaStream) => void
  /** Mikrofon darajasi 0..1 (panel shari va tumani uchun). */
  onLevel?: (level: number) => void
}

export function useBargeIn(options: BargeInOptions) {
  /** Tinglagich ishlayapti - "gapirsangiz to'xtaydi" yozuvi shunda ko'rinadi. */
  const armed = ref(false)
  const building = ref(false)

  let stream: MediaStream | null = null
  let ctx: AudioContext | null = null
  let timer = 0
  // Har start() yangi avlod: kechikib ochilgan mikrofon eski chaqiruvga tegishli
  // bo'lsa (o'qish allaqachon tugagan) - darhol yopiladi.
  let generation = 0

  function release() {
    clearInterval(timer)
    timer = 0
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    if (ctx && ctx.state !== 'closed') void ctx.close()
    ctx = null
    armed.value = false
    building.value = false
  }

  function stop() {
    generation++
    release()
  }

  async function start() {
    stop()
    const mine = generation
    let opened: MediaStream
    try {
      opened = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
    } catch {
      // Qulaylik, asosiy ish emas: mikrofon ochilmasa javob baribir o'qiladi.
      return
    }
    if (mine !== generation) {
      opened.getTracks().forEach((track) => track.stop())
      return
    }
    stream = opened
    try {
      ctx = new AudioContext()
      void ctx.resume().catch(() => {})
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      ctx.createMediaStreamSource(opened).connect(analyser)
      const buffer = new Float32Array(analyser.fftSize)
      const startedAt = performance.now()
      let echo = 0
      let level = 0
      const frames: { at: number; hit: boolean }[] = []

      timer = window.setInterval(() => {
        if (mine !== generation) return
        analyser.getFloatTimeDomainData(buffer)
        let sum = 0
        for (const sample of buffer) sum += sample * sample
        const rms = Math.sqrt(sum / buffer.length)
        level = Math.max(Math.min(rms * 6, 1), level * 0.9)
        options.onLevel?.(level)

        const now = performance.now()
        if (now - startedAt < CALIBRATE_MS) {
          echo = Math.max(echo, rms)
          return
        }
        const threshold = Math.max(MIN_RMS, echo * ECHO_FACTOR)
        frames.push({ at: now, hit: rms > threshold })
        while (frames.length && now - frames[0].at > WINDOW_MS) frames.shift()
        const hits = frames.filter((f) => f.hit).length
        const ratio = frames.length ? hits / frames.length : 0
        building.value = ratio >= BUILDING_RATIO
        // Oyna to'lmaguncha qaror yo'q: ikki kadrning ikkalasi baland = 100%.
        const span = frames.length ? now - frames[0].at : 0
        if (span >= WINDOW_MS - TICK_MS * 2 && ratio >= HIT_RATIO) {
          const handed = stream
          stream = null           // egalik chaqiruvchiga o'tadi - release() uni yopmasin
          stop()
          if (handed) options.onBarge(handed)
        }
      }, TICK_MS)
      armed.value = true
    } catch {
      release()
    }
  }

  if (getCurrentScope()) onScopeDispose(stop)

  return { armed: readonly(armed), building: readonly(building), start, stop }
}

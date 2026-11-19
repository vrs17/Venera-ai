// Jonli qo'ng'iroq holati: mikrofon, uning balandligi, transport, taymer va xatolar.
//
// HOLATLAR: idle -> mic (brauzer ruxsat so'rayapti) -> connecting -> live -> ended (rahmat
// sahifasi). Ruxsat yoki ulanish o'xshamasa - yana idle, `error` bilan (bosh sahifada
// tushuntirish va "Qayta urinish"). Bog'lanish paytida "Tugatish" - shunchaki bekor qilish.
//
// MIKROFON HAQIQIY (demo rejimda ham): shar odamning ovoziga javob beradi, "mikrofon
// eshitilmayapti" ogohlantirishi ham haqiqiy o'lchovdan. Ovoz hech qayerga yuborilmaydi -
// faqat `AnalyserNode` dan balandlik o'qiladi.
//
// Mikrofon faqat HTTPS (yoki localhost) da bor: oddiy HTTP da `navigator.mediaDevices` yo'q,
// brauzer hech narsa so'ramaydi - shu holat alohida xato (`insecure`) va HTTPS havolasi bilan.

import { getCurrentScope, onScopeDispose, ref, shallowRef } from 'vue'
import { micAvailable, micBlockedByPolicy } from '../../api/stt.api'
import type { LivePersona } from './personas'
import { createDemoTransport } from './transport'
import type { AgentPhase, DemoScript, LiveHandlers, LiveTransport, TransportFactory } from './transport'

export type CallStatus = 'idle' | 'mic' | 'connecting' | 'live' | 'ended'
export type CallError = 'insecure' | 'blocked' | 'denied' | 'no-mic' | 'mic' | 'connect' | 'dropped'

/** Shuncha soniya ichida mikrofondan deyarli hech narsa kelmasa - ogohlantirish. */
const NO_INPUT_SEC = 7
/** Jimlik shovqini (RMS) - undan pasti "ovoz yo'q". */
const SILENT_RMS = 0.0012

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)

export function useLiveCall(factory: TransportFactory = createDemoTransport) {
  const status = ref<CallStatus>('idle')
  const error = ref<CallError | null>(null)
  const persona = shallowRef<LivePersona | null>(null)
  const phase = ref<AgentPhase>('listening')
  const muted = ref(false)
  const elapsed = ref(0)
  const userLevel = ref(0)
  const agentLevel = ref(0)
  const agentCaption = ref('')
  const userCaption = ref('')
  const captionFinal = ref(false)
  const poorNetwork = ref(false)
  const noInput = ref(false)
  const callId = ref('')

  let stream: MediaStream | null = null
  let audio: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let transport: LiveTransport | null = null
  let abort: AbortController | null = null
  let meterFrame = 0
  let clock = 0
  let startedAt = 0
  let peakRms = 0

  const handlers: LiveHandlers = {
    onPhase(next) {
      phase.value = next
      if (next === 'speaking') { agentCaption.value = ''; captionFinal.value = false }
    },
    onCaption(c) {
      if (c.role === 'agent') { agentCaption.value = c.text; captionFinal.value = c.final }
      else userCaption.value = c.text
    },
    onAgentLevel(level) { agentLevel.value = clamp01(level) },
    onNetwork(quality) { poorNetwork.value = quality === 'poor' },
    onEnded(reason) {
      if (reason === 'dropped') { teardown(); error.value = 'dropped'; status.value = 'idle' }
      else finish()
    },
  }

  function onBeforeUnload(e: BeforeUnloadEvent) {
    e.preventDefault()
    e.returnValue = ''
  }
  const onOffline = () => { poorNetwork.value = true }
  const onOnline = () => { poorNetwork.value = false }
  const onPageHide = () => { if (status.value !== 'idle' && status.value !== 'ended') teardown() }

  function listen(on: boolean) {
    const fn = on ? window.addEventListener : window.removeEventListener
    fn('beforeunload', onBeforeUnload)
    fn('offline', onOffline)
    fn('online', onOnline)
    fn('pagehide', onPageHide)
  }

  function teardown() {
    abort?.abort()
    abort = null
    transport?.close()
    transport = null
    cancelAnimationFrame(meterFrame)
    window.clearInterval(clock)
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    analyser = null
    void audio?.close().catch(() => {})
    audio = null
    userLevel.value = 0
    agentLevel.value = 0
    listen(false)
  }

  function resetCall() {
    phase.value = 'listening'
    muted.value = false
    elapsed.value = 0
    agentCaption.value = ''
    userCaption.value = ''
    captionFinal.value = false
    poorNetwork.value = false
    noInput.value = false
    callId.value = ''
    peakRms = 0
  }

  function meter() {
    if (!analyser) return
    const buffer = new Float32Array(analyser.fftSize)
    let last = performance.now()
    const tick = () => {
      if (!analyser) return
      const now = performance.now()
      const dt = Math.min(100, now - last)
      last = now
      analyser.getFloatTimeDomainData(buffer)
      let sum = 0
      for (let i = 0; i < buffer.length; i++) sum += buffer[i] * buffer[i]
      const rms = Math.sqrt(sum / buffer.length)
      const raw = muted.value ? 0 : clamp01((rms - 0.006) * 11)
      // Tez ko'tariladi, sekin tushadi: shar so'z bilan birga "nafas oladi", titramaydi.
      const k = 1 - Math.exp(-dt / (raw > userLevel.value ? 40 : 180))
      userLevel.value += (raw - userLevel.value) * k
      transport?.feedUserLevel?.(userLevel.value, dt)
      if (status.value === 'live' && !muted.value) {
        peakRms = Math.max(peakRms, rms)
        if (rms > SILENT_RMS * 2.5) noInput.value = false
        else if (elapsed.value >= NO_INPUT_SEC && peakRms < SILENT_RMS) noInput.value = true
      }
      meterFrame = requestAnimationFrame(tick)
    }
    meterFrame = requestAnimationFrame(tick)
  }

  async function openMic(): Promise<MediaStream | null> {
    if (!window.isSecureContext) { error.value = 'insecure'; return null }
    if (!micAvailable()) { error.value = 'no-mic'; return null }
    if (micBlockedByPolicy()) { error.value = 'blocked'; return null }
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
    } catch (e) {
      const name = (e as DOMException)?.name
      error.value = name === 'NotAllowedError' || name === 'SecurityError'
        ? 'denied'
        : name === 'NotFoundError' || name === 'OverconstrainedError' ? 'no-mic' : 'mic'
      return null
    }
  }

  async function start(who: LivePersona, script: DemoScript, locale: string) {
    if (status.value === 'mic' || status.value === 'connecting' || status.value === 'live') return
    teardown()
    resetCall()
    error.value = null
    persona.value = who
    status.value = 'mic'
    listen(true)

    const mic = await openMic()
    if (status.value !== 'mic') { mic?.getTracks().forEach((t) => t.stop()); return }   // bekor qilindi
    if (!mic) { teardown(); status.value = 'idle'; return }
    stream = mic

    try {
      audio = new AudioContext()
      analyser = audio.createAnalyser()
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0.15
      audio.createMediaStreamSource(mic).connect(analyser)
      void audio.resume().catch(() => {})
    } catch {
      analyser = null   // balandliksiz ham ishlaydi - shar shunchaki jimroq
    }

    status.value = 'connecting'
    meter()
    transport = factory()
    abort = new AbortController()
    try {
      const result = await transport.connect({
        persona: who, mic, locale, handlers, signal: abort.signal, script,
      })
      callId.value = result.callId
    } catch (e) {
      if ((e as DOMException)?.name === 'AbortError' || status.value !== 'connecting') return
      teardown()
      error.value = 'connect'
      status.value = 'idle'
      return
    }
    status.value = 'live'
    startedAt = performance.now()
    clock = window.setInterval(() => {
      elapsed.value = Math.floor((performance.now() - startedAt) / 1000)
    }, 250)
  }

  /** Suhbat tugadi (odam yoki server): rahmat sahifasi. */
  function finish() {
    if (status.value === 'live') {
      elapsed.value = Math.floor((performance.now() - startedAt) / 1000)
      teardown()
      status.value = 'ended'
      return
    }
    teardown()
    status.value = 'idle'
  }

  /** "Tugatish": jonli suhbatda - rahmat sahifasi; ruxsat yoki ulanish paytida - bekor qilish. */
  function end() {
    finish()
  }

  function toggleMute() {
    muted.value = !muted.value
    stream?.getAudioTracks().forEach((track) => { track.enabled = !muted.value })
    transport?.setMuted(muted.value)
    if (muted.value) noInput.value = false
  }

  /** Bosh sahifaga: xato va oldingi suhbat izi tozalanadi. */
  function reset() {
    teardown()
    resetCall()
    error.value = null
    status.value = 'idle'
  }

  if (getCurrentScope()) onScopeDispose(teardown)

  return {
    status, error, persona, phase, muted, elapsed, userLevel, agentLevel,
    agentCaption, userCaption, captionFinal, poorNetwork, noInput, callId,
    start, end, toggleMute, reset,
  }
}

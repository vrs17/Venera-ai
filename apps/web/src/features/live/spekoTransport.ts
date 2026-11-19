// Speko'dagi «Barno AI» agenti bilan jonli suhbat - `LiveTransport` ning amalga oshiruvi.
//
// OQIM: (1) serverimizdan sessiya (`POST /api/v1/live/session` - platforma kaliti serverda qoladi);
// (2) Speko'ning brauzer SDK si `@spekoai/client` shu sessiyaning bir martalik tokeni bilan agentga ulanadi
// (LiveKit, WebRTC): mikrofonni o'zi oladi, agent ovozini o'zi ijro etadi. Ovoz bizning server orqali o'tmaydi.
// SDK faqat qo'ng'iroq boshlanganda yuklanadi (dinamik import) - sahifaning o'zi yengil qoladi.
//
// SDK BERMAYDIGAN IKKI NARSA shu yerda:
//   * "O'ylamoqda". SDK faqat `listening` / `speaking` ni biladi. Odamning gapi tugagani (yakuniy transkript)
//     bilan agent gapira boshlashi orasi - o'ylash; agent gapira boshlasa, odam yana gapirsa yoki
//     `THINK_TIMEOUT_MS` o'tsa - tugaydi.
//   * Agent ovozining balandligi (shar shundan "gapiradi"). SDK ovozni <body> ga qo'shadigan yashirin <audio>
//     elementlari orqali ijro etadi - ularning oqimi `AnalyserNode` ga ulanadi. Brauzer o'lchashga bermasa
//     (balandlik nol, agent esa gapiryapti) - sun'iy bo'g'in ritmi: shar baribir jonli ko'rinadi.

import { ApiError } from '../../api/http'
import { createLiveSession } from '../../api/live.api'
import { abortError, LiveConnectError } from './transport'
import type { AgentPhase, ConnectOptions, LiveHandlers, LiveTransport } from './transport'

/** `@spekoai/client` dan kerakli qism (turlar paketning o'zidan - faqat tur importi, bundlega tushmaydi). */
type SpekoSdk = typeof import('@spekoai/client')
type Conversation = Awaited<ReturnType<SpekoSdk['VoiceConversation']['create']>>
type Transcript = Parameters<NonNullable<Parameters<SpekoSdk['VoiceConversation']['create']>[0]['onTranscript']>>[0]

/** Odam gapini tugatgach agent shuncha vaqt jim tursa - "o'ylamoqda" yozuvi olib tashlanadi. */
const THINK_TIMEOUT_MS = 12_000

/** Agent gaplar orasida shuncha jim tursa ham "gapirmoqda" deb turiladi: SDK holatni ovoz balandligidan oladi
 *  va jumlalar orasidagi pauzada yarim soniyaga "tinglamoqda" ga o'tib qaytardi (yozuv va shar miltillardi). */
const SPEAK_HOLD_MS = 700

/** SDK ni oldindan yuklash (karta ustiga kelinganda): qo'ng'iroq bosilganda ulanish shuncha tez boshlanadi. */
export function preloadSpeko(): void {
  void import('@spekoai/client').catch(() => {})
}

export function createSpekoTransport(): LiveTransport {
  let handlers: LiveHandlers | null = null
  let conversation: Conversation | null = null
  let closed = false
  let mode: 'listening' | 'speaking' = 'listening'
  let awaitingReply = false
  let thinkTimer = 0
  let listenTimer = 0
  /** SDK ning xom holati (kechiktirilmagan): agent AYNI damda ovoz chiqaryaptimi. */
  let agentAudible = false
  let phase: AgentPhase = 'listening'

  // --- holat ---------------------------------------------------------------------------------
  function publishPhase() {
    const next: AgentPhase = mode === 'speaking' ? 'speaking' : awaitingReply ? 'thinking' : 'listening'
    if (next === phase) return
    phase = next
    handlers?.onPhase(next)
  }

  function setAwaiting(value: boolean) {
    window.clearTimeout(thinkTimer)
    awaitingReply = value
    if (value) thinkTimer = window.setTimeout(() => { awaitingReply = false; publishPhase() }, THINK_TIMEOUT_MS)
    publishPhase()
  }

  function onTranscript(list: Transcript) {
    const last = list[list.length - 1]
    if (!last || !last.text.trim()) return
    handlers?.onCaption({ role: last.source, text: last.text.trim(), final: last.isFinal })
    // Navbat: odamning yakuniy gapi -> agent o'ylaydi; odam hali gapiryapti -> tinglaydi.
    if (last.source === 'user') setAwaiting(last.isFinal)
  }

  // --- agent ovozining balandligi ---------------------------------------------------------------
  let audio: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let observer: MutationObserver | null = null
  let frame = 0
  const tapped = new Map<HTMLMediaElement, MediaStreamAudioSourceNode>()

  function scanAudioElements() {
    if (!audio || !analyser) return
    for (const el of Array.from(document.querySelectorAll<HTMLAudioElement>('body > audio'))) {
      const stream = el.srcObject
      if (tapped.has(el) || !(stream instanceof MediaStream) || !stream.getAudioTracks().length) continue
      try {
        const node = audio.createMediaStreamSource(stream)
        node.connect(analyser)
        tapped.set(el, node)
      } catch {
        /* brauzer bu oqimni o'lchashga bermadi - sun'iy ritm ishlaydi */
      }
    }
    for (const [el, node] of tapped) {
      if (el.isConnected) continue
      node.disconnect()
      tapped.delete(el)
    }
  }

  function watchAgentAudio() {
    try {
      audio = new AudioContext()
      analyser = audio.createAnalyser()
      analyser.fftSize = 512
      analyser.smoothingTimeConstant = 0.2
      void audio.resume().catch(() => {})
    } catch {
      audio = null
      analyser = null
    }
    observer = new MutationObserver(scanAudioElements)
    observer.observe(document.body, { childList: true })
    scanAudioElements()

    const buffer = new Float32Array(analyser?.fftSize ?? 512)
    let level = 0
    let last = performance.now()
    /** O'lchov bir marta bo'lsa ham ovoz ko'rsatdi - demak ishlayapti va sun'iy ritm kerak emas. */
    let measures = false
    const tick = () => {
      if (closed) return
      const now = performance.now()
      const dt = Math.min(100, now - last)
      last = now
      let measured = 0
      if (analyser && tapped.size) {
        analyser.getFloatTimeDomainData(buffer)
        let sum = 0
        for (let i = 0; i < buffer.length; i++) sum += buffer[i] * buffer[i]
        measured = Math.min(1, Math.sqrt(sum / buffer.length) * 4.2)
      }
      if (measured > 0.02) measures = true
      let target = measured
      if (!measures && agentAudible) {
        const s = now / 1000
        const syllable = 0.5 + 0.5 * Math.sin(s * Math.PI * 2 * 4.3 + Math.sin(s * 1.7) * 2.2)
        target = (0.2 + 0.55 * syllable * syllable) * (0.8 + 0.2 * Math.sin(s * 0.9))
      }
      level += (target - level) * (1 - Math.exp(-dt / (target > level ? 45 : 160)))
      handlers?.onAgentLevel(level < 0.004 ? 0 : level)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
  }

  function stopAgentAudio() {
    cancelAnimationFrame(frame)
    observer?.disconnect()
    observer = null
    for (const node of tapped.values()) node.disconnect()
    tapped.clear()
    void audio?.close().catch(() => {})
    audio = null
    analyser = null
  }

  // --- ulanish -----------------------------------------------------------------------------------
  function failure(error: unknown): Error {
    if ((error as DOMException)?.name === 'AbortError') return abortError()
    if (error instanceof LiveConnectError) return error
    if (error instanceof ApiError) {
      if (error.status === 401) return new LiveConnectError('auth')
      if (error.status === 429) return new LiveConnectError('busy')
      return new LiveConnectError('unavailable')
    }
    const code = (error as { code?: string })?.code
    return new LiveConnectError(code === 'MICROPHONE_FAILED' ? 'mic' : 'unavailable')
  }

  return {
    async connect({ persona, handlers: h, signal }: ConnectOptions) {
      handlers = h
      try {
        const session = await createLiveSession(persona.id, signal)
        if (signal.aborted || closed) throw abortError()
        const { VoiceConversation } = await import('@spekoai/client')
        const created = await VoiceConversation.create({
          transport: session.transport === 'daily' ? 'daily' : 'livekit',
          transportToken: session.transportToken,
          transportUrl: session.transportUrl,
          onModeChange: (next) => {
            agentAudible = next === 'speaking'
            window.clearTimeout(listenTimer)
            if (next === 'speaking') {
              mode = 'speaking'
              // Agent gapira boshladi - odamning savoliga javob shu: "o'ylash" tugadi.
              setAwaiting(false)
              return
            }
            listenTimer = window.setTimeout(() => { mode = 'listening'; publishPhase() }, SPEAK_HOLD_MS)
          },
          onTranscript,
          onAudioPlaybackBlocked: () => handlers?.onAudioBlocked(),
          onDisconnect: ({ reason }) => {
            if (closed || reason === 'user') return
            handlers?.onEnded(reason === 'agent' ? 'remote' : 'dropped')
          },
          onError: (error) => {
            // Halokatli bo'lmagan xatolar (masalan mikrofon qurilmasi almashdi): suhbat davom etadi,
            // uzilish esa `onDisconnect` orqali keladi.
            console.warn('[live] Speko:', (error as { code?: string })?.code ?? error.message)
          },
        })
        // Ulanish paytida odam bekor qilgan bo'lsa - sessiya ochiq qolmasin (daqiqa hisobi to'xtasin).
        if (signal.aborted || closed) {
          void created.endSession().catch(() => {})
          throw abortError()
        }
        conversation = created
        watchAgentAudio()
        if (!created.canPlaybackAudio) handlers.onAudioBlocked()
        return { callId: session.sessionId || created.getId() }
      } catch (error) {
        throw failure(error)
      }
    },

    setMuted(muted) {
      void conversation?.setMicMuted(muted).catch(() => {})
    },

    async resumeAudio() {
      await conversation?.startAudioPlayback()
      void audio?.resume().catch(() => {})
      scanAudioElements()
    },

    close() {
      if (closed) return
      closed = true
      window.clearTimeout(thinkTimer)
      window.clearTimeout(listenTimer)
      stopAgentAudio()
      // Sessiya yopilmasa Speko'da daqiqa hisobi davom etishi mumkin.
      void conversation?.endSession().catch(() => {})
      conversation = null
      handlers = null
    },
  }
}

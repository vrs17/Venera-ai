// Jonli suhbat TRANSPORTI - sahifa (`LiveView.vue`) va ovoz manbai orasidagi yagona chegara.
//
// HOZIR (front bosqichi, 2026-11-19): faqat `createDemoTransport` - server yo'q, ovoz yo'q.
// U suhbatning hamma holatini ko'rsatadi: bog'lanish, salomlashish (sun'iy ovoz balandligi va
// so'zma-so'z subtitr), tinglash, odam gapirib to'xtagach "o'ylash" va javob, odam uning
// ustidan gapirsa to'xtash (barge-in). Mikrofon HAQIQIY: shar odamning ovoziga javob beradi.
//
// INTEGRATSIYA: haqiqiy transport (WebSocket / WebRTC - Barno serveri yoki tashqi ovozli agent)
// shu interfeysni amalga oshiradi va `useLiveCall(createXTransport)` ga beriladi - sahifa
// o'zgarmaydi. Kelishuv:
//   * `connect` mikrofon oqimini oladi, ulanib bo'lgach `callId` qaytaradi; `signal` bekor
//     qilinsa (odam "Tugatish"ni bosdi) - darhol `AbortError` bilan to'xtaydi;
//   * agent holati `onPhase`, gapi `onCaption` (so'zma-so'z, oxirida `final`), ovozining
//     balandligi `onAgentLevel` (0..1, har kadrda - shar shundan chiziladi);
//   * aloqa sifati `onNetwork`, serverdan tugash `onEnded`.

import type { LivePersona } from './personas'

export type AgentPhase = 'listening' | 'thinking' | 'speaking'
export type NetworkQuality = 'good' | 'poor'

export interface LiveCaption {
  role: 'agent' | 'user'
  text: string
  /** Gap tugadi (subtitr shu matn bilan qoladi). */
  final: boolean
}

export interface LiveHandlers {
  onPhase(phase: AgentPhase): void
  onCaption(caption: LiveCaption): void
  onAgentLevel(level: number): void
  onNetwork(quality: NetworkQuality): void
  /** Suhbat server tomonidan tugadi: `remote` - odatdagidek, `dropped` - aloqa uzildi. */
  onEnded(reason: 'remote' | 'dropped'): void
}

/** Demo matnlari - sahifa tilida (`live.demo*`). Haqiqiy transportda kerak emas. */
export interface DemoScript {
  greeting: string
  replies: string[]
}

export interface ConnectOptions {
  persona: LivePersona
  mic: MediaStream
  locale: string
  handlers: LiveHandlers
  signal: AbortSignal
  script: DemoScript
}

export interface LiveTransport {
  connect(options: ConnectOptions): Promise<{ callId: string }>
  setMuted(muted: boolean): void
  /** Mikrofon balandligi (0..1) va kadr davomiyligi - faqat demo navbat almashishini shundan sezadi. */
  feedUserLevel?(level: number, dtMs: number): void
  close(): void
}

export type TransportFactory = () => LiveTransport

const abortError = () => new DOMException('aborted', 'AbortError')

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError())
    const id = window.setTimeout(resolve, ms)
    signal.addEventListener('abort', () => { window.clearTimeout(id); reject(abortError()) }, { once: true })
  })
}

function shortId(): string {
  const raw = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Math.random().toString(16).slice(2) + Date.now().toString(16)
  return raw.replace(/-/g, '').slice(0, 10)
}

/** Odam gapiryapti deb hisoblanadigan mikrofon balandligi (0..1, `useLiveCall` shkalasi). */
const TALK_LEVEL = 0.16
/** Gap boshlandi: shuncha ms tinmay ovoz. */
const TALK_START_MS = 260
/** Gap tugadi: shuncha ms jimlik - navbat agentga o'tadi. */
const TURN_SILENCE_MS = 900
/** Agent gapirayotganda odam shuncha ms gapirsa - agent to'xtaydi (barge-in). */
const BARGE_MS = 380

/**
 * Demo transport: tarmoqsiz, ovozsiz. Agentning "ovozi" - sun'iy balandlik egri chizig'i
 * (bo'g'in ritmi ~4.3 Hz va gap konturi), subtitr esa shu vaqt ichida so'zma-so'z ochiladi.
 */
export function createDemoTransport(): LiveTransport {
  let handlers: LiveHandlers | null = null
  let script: DemoScript = { greeting: '', replies: [] }
  let phase: AgentPhase = 'listening'
  let muted = false
  let talkMs = 0
  let silenceMs = 0
  let heard = false
  let replyIndex = 0
  let frame = 0
  const timers = new Set<number>()

  function later(ms: number, fn: () => void) {
    const id = window.setTimeout(() => { timers.delete(id); fn() }, ms)
    timers.add(id)
  }

  function setPhase(next: AgentPhase) {
    phase = next
    handlers?.onPhase(next)
  }

  function stopSpeaking() {
    cancelAnimationFrame(frame)
    handlers?.onAgentLevel(0)
  }

  function speak(text: string) {
    if (!handlers) return
    // Oldingi navbatdagi ovoz hisobi yangi gapga o'tmasin: aks holda odam endigina tugatgan gap
    // agentning salomini darhol "bo'lib" qo'yardi.
    talkMs = 0
    silenceMs = 0
    heard = false
    setPhase('speaking')
    const words = text.split(/\s+/).filter(Boolean)
    const total = Math.max(1800, text.length * 58)
    const started = performance.now()
    let shown = -1
    const tick = () => {
      if (!handlers || phase !== 'speaking') return
      const ms = performance.now() - started
      const p = Math.min(1, ms / total)
      const s = ms / 1000
      const syllable = 0.5 + 0.5 * Math.sin(s * Math.PI * 2 * 4.3 + Math.sin(s * 1.7) * 2.2)
      const contour = Math.min(1, p * 7) * Math.min(1, (1 - p) * 7)
      const drift = 0.78 + 0.22 * Math.sin(s * 0.9 + 1.1)
      handlers.onAgentLevel(Math.max(0, Math.min(1, (0.22 + 0.62 * syllable * syllable) * contour * drift)))
      const count = p >= 1 ? words.length : Math.min(words.length, Math.floor(p * words.length) + 1)
      if (count !== shown) {
        shown = count
        handlers.onCaption({ role: 'agent', text: words.slice(0, count).join(' '), final: count === words.length && p >= 1 })
      }
      if (p >= 1) {
        stopSpeaking()
        setPhase('listening')
        return
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
  }

  return {
    async connect(options) {
      handlers = options.handlers
      script = options.script
      await sleep(1100 + Math.random() * 500, options.signal)
      handlers.onNetwork('good')
      later(500, () => speak(script.greeting))
      return { callId: shortId() }
    },

    setMuted(value) {
      muted = value
      if (value) { talkMs = 0; silenceMs = 0; heard = false }
    },

    feedUserLevel(level, dtMs) {
      if (!handlers || muted) return
      const talking = level > TALK_LEVEL
      if (phase === 'speaking') {
        talkMs = talking ? talkMs + dtMs : Math.max(0, talkMs - dtMs * 2)
        if (talkMs > BARGE_MS) {
          stopSpeaking()
          setPhase('listening')
          heard = true
          silenceMs = 0
        }
        return
      }
      if (phase !== 'listening') return
      if (talking) {
        talkMs += dtMs
        silenceMs = 0
        if (talkMs > TALK_START_MS) heard = true
        return
      }
      talkMs = Math.max(0, talkMs - dtMs)
      if (!heard) return
      silenceMs += dtMs
      if (silenceMs < TURN_SILENCE_MS) return
      heard = false
      talkMs = 0
      silenceMs = 0
      setPhase('thinking')
      const reply = script.replies[replyIndex++ % Math.max(1, script.replies.length)] ?? ''
      later(1100 + Math.random() * 400, () => speak(reply))
    },

    close() {
      for (const id of timers) window.clearTimeout(id)
      timers.clear()
      cancelAnimationFrame(frame)
      handlers = null
    },
  }
}

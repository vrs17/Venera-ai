// Jonli suhbat TRANSPORTI - sahifa (`views/LiveView.vue`, `useLiveCall.ts`) va ovozli agent orasidagi yagona
// chegara. Amalga oshiruvchi: `spekoTransport.ts` (Speko agenti, `@spekoai/client`).
//
// Kelishuv:
//   * `connect` agentga ulanadi va `callId` qaytaradi. Ulanmasa - `LiveConnectError` (sababi `kind` da);
//     `signal` bekor qilinsa (odam "Bekor qilish"ni bosdi) - `AbortError`;
//   * agent holati `onPhase`, oxirgi gap `onCaption` (so'zma-so'z o'sadi, oxirida `final`), agent ovozining
//     balandligi `onAgentLevel` (0..1, har kadrda - shar shundan chiziladi);
//   * brauzer agent ovozini ijro etishni to'ssa (autoplay siyosati) - `onAudioBlocked`: sahifa "Ovozni yoqish"
//     tugmasini ko'rsatadi va bosilganda `resumeAudio()` ni chaqiradi;
//   * suhbat server tomonidan tugasa - `onEnded`.

import type { LivePersona } from './personas'

export type AgentPhase = 'listening' | 'thinking' | 'speaking'

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
  onAudioBlocked(): void
  /** Suhbat server tomonidan tugadi: `remote` - agent yakunladi, `dropped` - aloqa uzildi. */
  onEnded(reason: 'remote' | 'dropped'): void
}

export interface ConnectOptions {
  persona: LivePersona
  handlers: LiveHandlers
  signal: AbortSignal
}

export interface LiveTransport {
  connect(options: ConnectOptions): Promise<{ callId: string }>
  setMuted(muted: boolean): void
  /** Autoplay to'sig'idan keyin - foydalanuvchi bosgan tugma ishlovchisidan chaqiriladi. */
  resumeAudio(): Promise<void>
  close(): void
}

export type TransportFactory = () => LiveTransport

/** Nega ulanmadi: `auth` - tizimga kirilmagan (yoki sessiya eskirgan), `busy` - urinishlar chegarasi,
 *  `mic` - mikrofon olinmadi, `unavailable` - agent hozir javob bermayapti. */
export type ConnectFailure = 'auth' | 'busy' | 'mic' | 'unavailable'

export class LiveConnectError extends Error {
  readonly kind: ConnectFailure
  constructor(kind: ConnectFailure, message = kind) {
    super(message)
    this.name = 'LiveConnectError'
    this.kind = kind
  }
}

export const abortError = () => new DOMException('aborted', 'AbortError')

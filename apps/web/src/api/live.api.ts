// Jonli ovozli suhbat (`/barno`) so'rovlari. Server: `apps/api/app/api/v1/live.py`.
//
// Brauzer Speko platforma kalitini HECH QACHON ko'rmaydi: server sessiyani o'zi ochadi va bu yerga faqat shu
// suhbatning bir martalik transport tokeni keladi. Ikkala so'rov ham tizimga kirgan odamniki (Bearer token).

import { apiFetch } from './http'

export interface LiveSession {
  sessionId: string
  /** `livekit` (hozir) yoki `daily`. */
  transport: string
  transportToken: string
  transportUrl: string
  expiresAt?: string | null
}

export interface LiveFeedback {
  sessionId: string
  persona: string
  /** 1..5 */
  rating: number
  reasons: string[]
  comment: string
  durationSec: number
}

/** Yangi suhbat sessiyasi. 401 - kirilmagan, 429 - urinishlar chegarasi, 502/503 - agent hozir ishlamayapti. */
export function createLiveSession(persona: string, signal?: AbortSignal): Promise<LiveSession> {
  return apiFetch<LiveSession>('/api/v1/live/session', {
    method: 'POST',
    body: JSON.stringify({ persona }),
    signal,
  })
}

/** Suhbatdan keyingi baho. */
export function sendLiveFeedback(feedback: LiveFeedback): Promise<void> {
  return apiFetch<void>('/api/v1/live/feedback', { method: 'POST', body: JSON.stringify(feedback) })
}

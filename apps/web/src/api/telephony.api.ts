// Telefon qo'ng'iroqlari (`/barno` sahifasidagi admin paneli). Server: `apps/api/app/api/v1/telephony.py`.
//
// Barno mijozga bankning telefon tizimi (FreePBX) orqali qo'ng'iroq qiladi: brauzer faqat raqamni yuboradi va
// holatni so'raydi. Hamma so'rov - tizimga kirgan ADMIN niki (Bearer token); boshqa rolga server 403 beradi.

import { apiFetch } from './http'

export interface TelephonyStatus {
  /** Qo'ng'iroq boshlash yoqilganmi (serverdagi `TELEPHONY_ENABLED`). */
  enabled: boolean
  /** FreePBX manzili, tokeni va sertifikat barmoq izi berilganmi. */
  configured: boolean
  dailyCap: number
  used24h: number
}

export interface PhoneCallBridge {
  endReason?: string | null
  seconds?: number | null
  sessionId?: string | null
  agentSeconds?: number | null
  costUsd?: number | null
  agentEndReason?: string | null
}

export interface PhoneCall {
  callId: string
  /** 9 raqam, `+998` siz. */
  phone: string
  /** placing | queued | rejected | failed | completed | unknown */
  status: string
  /** no_answer | busy | congestion | rejected | failed | talked | gateway_failed | '' */
  outcome: string
  /** FreePBX javobidagi sabab (disabled, barno_max, trunk, lock...) yoki xato turi (cert_mismatch, no_response...). */
  detail: string
  httpStatus: number | null
  note: string
  createdAt: number
  placedAt: number | null
  resultAt: number | null
  answerTime: number | null
  endTime: number | null
  talkSec: number | null
  gatewayStatus: string | null
  hangupCause: string | null
  bridge?: PhoneCallBridge | null
}

/** Qo'ng'iroq boshlash mumkinmi. 403 - admin emas. */
export function telephonyStatus(): Promise<TelephonyStatus> {
  return apiFetch<TelephonyStatus>('/api/v1/telephony/status')
}

/** Qo'ng'iroq boshlash. 422 - raqam noto'g'ri, 429 - chegara, 503 - o'chiq yoki sozlanmagan. */
export function placePhoneCall(phone: string): Promise<PhoneCall> {
  return apiFetch<PhoneCall>('/api/v1/telephony/calls', { method: 'POST', body: JSON.stringify({ phone }) })
}

export function getPhoneCall(callId: string): Promise<PhoneCall> {
  return apiFetch<PhoneCall>(`/api/v1/telephony/calls/${encodeURIComponent(callId)}`)
}

export function recentPhoneCalls(limit = 5): Promise<PhoneCall[]> {
  return apiFetch<PhoneCall[]>(`/api/v1/telephony/calls?limit=${limit}`)
}

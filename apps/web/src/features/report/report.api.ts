// "Xabar berish" (spec §4.4) - foydalanuvchi suhbatni yoki bitta javobni jamoaga
// yuboradi. Backend shartnomasi: `POST /api/v1/reports` (backend-spec §7,
// `apps/api/app/schemas/reports.py`).
//
// Suhbat nusxasini server O'ZI yig'adi (telemetriya → yordamchidagi tarix); brauzer
// yuboradigan `messages` - faqat zahira: masalan, telemetriya o'chiq bo'lsa yoki suhbat
// hali yordamchida saqlanmagan bo'lsa ham shikoyat bo'sh qolmasin.

import { apiFetch } from '../../api/http'

/** Sabab kodlari - chiplar shu tartibda chiziladi (backend `REASONS` bilan bir xil). */
export const REPORT_REASONS = ['wrong', 'incomplete', 'outdated', 'unsafe', 'other'] as const
export type ReportReason = (typeof REPORT_REASONS)[number]

/** Chegaralar - backend bilan bir xil; oshsa server kesadi yoki 422 qaytaradi. */
export const REPORT_COMMENT_MAX = 2000
export const REPORT_MESSAGES_MAX = 200
export const REPORT_CONTENT_MAX = 20_000

/** types.ts: ReportMessage - suhbat nusxasidagi bitta xabar. */
export interface ReportMessage {
  role: 'user' | 'assistant'
  content: string
  /** ISO-8601. */
  createdAt?: string | null
  /** Javobning `X-Venera-Turn` izi (bo'lsa). */
  turnId?: string | null
  /** Javob manbalari - klientdagi shaklda; server faqat tanish maydonlarni oladi. */
  sources?: unknown[] | null
  /** Faqat server nusxasida (telemetriyadan): ok | error | cancelled. */
  status?: string | null
}

/** types.ts: ReportCreate - kamida bittasi kerak: `chatId`, `turnId` yoki `messages`. */
export interface ReportCreate {
  chatId?: string | null
  /** Berilsa - aynan shu javob belgilangan; suhbatning qolgani baribir ilova qilinadi. */
  turnId?: string | null
  reason?: ReportReason | null
  comment?: string | null
  messages?: ReportMessage[] | null
}

/** types.ts: ReportCreated - 201 javobi. */
export interface ReportCreated {
  id: string
  /** Har doim `new`. */
  status: string
  createdAt: string
}

/**
 * Shikoyat yuborish. Xatolar `ApiError` sifatida qaytadi - 429 (soatiga 20 tadan
 * ko'p) uchun chaqiruvchi `report.rateLimited` matnini ko'rsatadi.
 *
 * Tana shu yerda tozalanadi: bo'sh izoh yuborilmaydi, uzun matnlar va ro'yxat
 * chegaraga keltiriladi (oxirgi xabarlar qoladi - odatda muammo o'shalarda).
 */
export function createReport(body: ReportCreate, signal?: AbortSignal): Promise<ReportCreated> {
  const comment = body.comment?.trim().slice(0, REPORT_COMMENT_MAX) || null
  const messages = body.messages?.length
    ? body.messages.slice(-REPORT_MESSAGES_MAX).map((m) => ({
        ...m,
        content: m.content.length > REPORT_CONTENT_MAX ? m.content.slice(0, REPORT_CONTENT_MAX) : m.content,
      }))
    : null
  const payload: ReportCreate = {
    chatId: body.chatId || null,
    turnId: body.turnId || null,
    reason: body.reason ?? null,
    comment,
    messages,
  }
  return apiFetch<ReportCreated>('/api/v1/reports', {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  })
}

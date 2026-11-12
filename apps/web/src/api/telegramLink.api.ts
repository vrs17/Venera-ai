// Telegram hisobini Barno hisobiga ulash - tasdiq sahifasining so'rovlari
// (`views/LinkAccountView.vue`; server: `apps/api/app/api/v1/telegram.py`, "BRB-Tech ID orqali ulash").
//
// Brauzer faqat CHIPTANI yuboradi (Mini App ochgan havoladagi `t`). Telegram hisobi serverda
// chiptaning yozuvidan (Telegram imzosidan), Barno hisobi shu sessiyadan olinadi.

import { apiFetch } from './http'

export interface TelegramLinkInfo {
  telegramName: string | null
  telegramUsername: string | null
  accountName: string
  accountLogin: string
  expiresIn: number
}

/** Kim kimga ulanyapti. Chiptani yoqmaydi. */
export function telegramLinkInfo(ticket: string): Promise<TelegramLinkInfo> {
  return apiFetch<TelegramLinkInfo>(`/api/v1/telegram/link-ticket/${encodeURIComponent(ticket)}`)
}

/** Ulash: Telegram hisobi shu Barno hisobiga ulanadi, Mini App sessiyani o'zi oladi. */
export function confirmTelegramLink(ticket: string): Promise<unknown> {
  return apiFetch('/api/v1/telegram/link-ticket/confirm', { method: 'POST', body: JSON.stringify({ ticket }) })
}

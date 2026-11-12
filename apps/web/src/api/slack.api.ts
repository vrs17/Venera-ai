// Slack hisobini Barno hisobiga ulash - tasdiq sahifasining so'rovlari
// (`views/SlackLinkView.vue`; server: `apps/api/app/api/v1/slack.py`).
//
// Brauzer faqat CHIPTANI yuboradi (Slack'dagi tugma havolasidagi `t`). Slack
// hisobi serverda chiptaning yozuvidan, Barno hisobi shu sessiyadan olinadi -
// bu yerdan hech qanday id ketmaydi.

import { apiFetch } from './http'

export interface SlackLinkInfo {
  /** Slack'dagi ism; Slack uni bermagan bo'lsa `null`. */
  slackName: string | null
  accountName: string
  accountLogin: string
  expiresIn: number
}

export interface SlackLinkResult {
  linked: boolean
  status: 'new' | 'refreshed' | 'switched'
  slackName: string | null
  days: number
}

/** Kim kimga ulanyapti. Chiptani yoqmaydi - sahifa qayta yuklansa ham ishlaydi. */
export function slackLinkInfo(ticket: string): Promise<SlackLinkInfo> {
  return apiFetch<SlackLinkInfo>(`/api/v1/slack/link/${encodeURIComponent(ticket)}`)
}

/** Ulash. Chipta bir martalik: ikkinchi so'rov 404. */
export function confirmSlackLink(ticket: string): Promise<SlackLinkResult> {
  return apiFetch<SlackLinkResult>('/api/v1/slack/link', { method: 'POST', body: JSON.stringify({ ticket }) })
}

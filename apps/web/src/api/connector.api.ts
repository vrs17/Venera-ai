// Barno konnektori (Claude / ChatGPT) - rozilik sahifasi va "Ulangan ilovalar" so'rovlari
// (`views/ConnectView.vue`; server: `apps/api/app/api/v1/connector.py`).
//
// Brauzer faqat SO'ROV kalitini (`/connect?request=`) yuboradi. Ilova va qaytish manzili
// serverda so'rovning yozuvidan olinadi - bu yerdan hech qanday manzil ketmaydi, va
// qaytish manzilini ham server beradi (`redirect`).

import { apiFetch } from './http'

export interface ConnectRequest {
  id: string
  /** `Claude` | `ChatGPT` | `Claude Code` - qaytish manzilidan, ilova aytgani emas. */
  client: string
  /** Kod qaytadigan host (`claude.ai`). */
  host: string
  scopes: { id: string }[]
  expiresAt: string
}

export interface ConnectedApp {
  id: string
  client: string
  scopes: string[]
  createdAt: string
  lastUsedAt: string | null
}

export function connectRequest(id: string): Promise<ConnectRequest> {
  return apiFetch<ConnectRequest>(`/api/v1/connector/requests/${encodeURIComponent(id)}`)
}

/** Ruxsat. Javobdagi `redirect` ga brauzer o'tadi (kod bilan ilovaga qaytish). */
export function approveConnect(id: string, scopes: string[]): Promise<{ redirect: string }> {
  return apiFetch<{ redirect: string }>(`/api/v1/connector/requests/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ scopes }),
  })
}

export function denyConnect(id: string): Promise<{ redirect: string }> {
  return apiFetch<{ redirect: string }>(`/api/v1/connector/requests/${encodeURIComponent(id)}/deny`, {
    method: 'POST',
  })
}

export interface ConnectedApps {
  /** Bosh kalit: o'chiq bo'lsa sahifa "manzilni qo'shing" demaydi (ro'yxat baribir ko'rinadi). */
  enabled: boolean
  apps: ConnectedApp[]
}

export function connectedApps(): Promise<ConnectedApps> {
  return apiFetch<ConnectedApps>('/api/v1/connector/apps')
}

export function disconnectApp(id: string): Promise<{ revoked: boolean }> {
  return apiFetch<{ revoked: boolean }>(`/api/v1/connector/apps/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

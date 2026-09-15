// Ulanishlar (HRM, CRM) holati - "+" menyusidagi ro'yxat va ulanish oynasi uchun.
//
// MANBA - SERVER (`/api/v1/connectors`): tokenlar u yerda turadi, brauzer
// faqat holatni ko'radi (ulanmagan / ulangan / muddati tugagan) va uchta
// amalni so'raydi: ulanish (login + parol), kalit, uzish. Parol serverga
// ketadi va hech qayerda saqlanmaydi.
//
// Modul darajasidagi holat: menyu har ochilganda qaytadan yaratiladi, holat
// esa qolishi kerak; va ro'yxat, yon panel, oyna - hammasi bir manbadan o'qiydi.
// Menyu ochilganda `load()` chaqiriladi - HRM tokeni 10 soatda tugaydi, ya'ni
// holat sahifa ochilgandan beri o'zgargan bo'lishi mumkin.

import { reactive, readonly, ref } from 'vue'
import { connectConnector, disconnectConnector, listConnectors, updateConnector } from '../api/connectors.api'
import type { ConnectorId, ConnectorStatus } from '../types'

export type { ConnectorId, ConnectorStatus }

// Server javobi kelguncha ko'rinadigan qatorlar: nomlar ma'lum, holat esa
// "ulanmagan" - menyu bo'sh ochilmasin.
function placeholder(id: ConnectorId, label: string): ConnectorStatus {
  return { id, label, configured: true, state: 'disconnected', login: null, enabled: false, expiresAt: null }
}

const connectors = reactive<ConnectorStatus[]>([placeholder('hrm', 'HRM'), placeholder('crm', 'CRM')])
const loading = ref(false)
const loaded = ref(false)
const loadFailed = ref(false)
let inflight: Promise<void> | null = null

function apply(status: ConnectorStatus) {
  const i = connectors.findIndex((c) => c.id === status.id)
  if (i >= 0) connectors.splice(i, 1, status)
  else connectors.push(status)
}

/** Holatni serverdan oladi. Bir vaqtda ikki chaqiruv bitta so'rovni bo'lishadi. */
function load(): Promise<void> {
  if (inflight) return inflight
  loading.value = true
  inflight = (async () => {
    try {
      const { connectors: list } = await listConnectors()
      list.forEach(apply)
      loaded.value = true
      loadFailed.value = false
    } catch {
      // Ro'yxat baribir ko'rinadi (eski/placeholder holat bilan); qatorlar
      // ostida "holat yuklanmadi" chiqadi.
      loadFailed.value = true
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

export function useConnectors() {
  /** Login/parol bilan ulanish. Xato bo'lsa reject qiladi (ApiError) - oyna
   *  serverning xabarini ko'rsatadi. */
  async function connect(id: ConnectorId, username: string, password: string): Promise<void> {
    apply(await connectConnector(id, { username, password }))
  }

  async function disconnect(id: ConnectorId): Promise<void> {
    apply(await disconnectConnector(id))
  }

  /** Kalit: darhol ko'rinadi (optimistik), server rad etsa qaytariladi. */
  async function toggle(id: ConnectorId): Promise<void> {
    const c = connectors.find((x) => x.id === id)
    if (!c || c.state !== 'connected') return
    const wanted = !c.enabled
    c.enabled = wanted
    try {
      apply(await updateConnector(id, { enabled: wanted }))
    } catch {
      c.enabled = !wanted
    }
  }

  return { connectors: readonly(connectors), loading, loaded, loadFailed, load, connect, disconnect, toggle }
}

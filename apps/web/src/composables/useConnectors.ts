// Ulanishlar holati - "+" menyusidagi ulanish oynasi uchun. Odam boshqaradigan
// yagona tizim - HRM: u SSO sessiyasini hali qabul qilmaydi, shuning uchun qo'lda
// (login + parol) ulanadi. CRM bu yerda YO'Q (ega qarori, 2026-11-12): u BRB-Tech ID
// bilan kirishda o'zi ulanadi va odamga ko'rsatilmaydi. Yoqish/o'chirish kaliti ham
// yo'q - ulangan tizim ishlatiladi.
//
// MANBA - SERVER (`/api/v1/connectors`): tokenlar u yerda turadi, brauzer
// faqat holatni ko'radi (ulanmagan / ulangan / muddati tugagan) va ikkita
// amalni so'raydi: ulanish (login + parol) va uzish. Parol serverga
// ketadi va hech qayerda saqlanmaydi.
//
// Modul darajasidagi holat: menyu har ochilganda qaytadan yaratiladi, holat
// esa qolishi kerak; va ro'yxat, yon panel, oyna - hammasi bir manbadan o'qiydi.
// Menyu ochilganda `load()` chaqiriladi - HRM tokeni 10 soatda tugaydi, ya'ni
// holat sahifa ochilgandan beri o'zgargan bo'lishi mumkin.

import { reactive, readonly, ref, watch } from 'vue'
import { connectConnector, disconnectConnector, listConnectors } from '../api/connectors.api'
import { useAuth } from './useAuth'
import type { ConnectorId, ConnectorStatus } from '../types'

export type { ConnectorId, ConnectorStatus }

// Server javobi kelguncha ko'rinadigan qatorlar: nomlar ma'lum, holat esa
// "ulanmagan" - oyna bo'sh ochilmasin. Ro'yxat SHU YERDA belgilanadi: server
// qo'shimcha tizim qaytarsa ham (eski API CRM ni ham berardi) - u ko'rsatilmaydi.
function placeholders(): ConnectorStatus[] {
  return [{ id: 'hrm', label: 'HRM', configured: true, state: 'disconnected', login: null, enabled: false, expiresAt: null }]
}

const connectors = reactive<ConnectorStatus[]>(placeholders())
const loading = ref(false)
const loaded = ref(false)
const loadFailed = ref(false)
let inflight: Promise<void> | null = null
/** Sessiya avlodi: chiqish/boshqa odam kirganda oshadi - eski sessiyaning kech
 *  kelgan javobi yangi odamning ro'yxatiga yozilmaydi. */
let generation = 0

/** Faqat ro'yxatdagi qator yangilanadi - notanish tizim qo'shilmaydi. */
function apply(status: ConnectorStatus) {
  const i = connectors.findIndex((c) => c.id === status.id)
  if (i >= 0) connectors.splice(i, 1, status)
}

/** Holatni serverdan oladi. Bir vaqtda ikki chaqiruv bitta so'rovni bo'lishadi. */
function load(): Promise<void> {
  if (inflight) return inflight
  loading.value = true
  const gen = generation
  inflight = (async () => {
    try {
      const { connectors: list } = await listConnectors()
      if (gen !== generation) return
      list.forEach(apply)
      loaded.value = true
      loadFailed.value = false
    } catch {
      // Ro'yxat baribir ko'rinadi (eski/placeholder holat bilan); qatorlar
      // ostida "holat yuklanmadi" chiqadi.
      if (gen === generation) loadFailed.value = true
    } finally {
      if (gen === generation) {
        loading.value = false
        inflight = null
      }
    }
  })()
  return inflight
}

/** Boshlang'ich holat. Holat modul darajasida yashaydi, ya'ni chiqib boshqa
 *  hisob bilan kirilsa (yoki boshqa tabda chiqilsa) oldingi odamning logini
 *  birinchi yuklash tugaguncha menyuda ko'rinib turardi. */
export function resetConnectors(): void {
  generation++
  inflight = null
  loading.value = false
  loaded.value = false
  loadFailed.value = false
  connectors.splice(0, connectors.length, ...placeholders())
}

// Kim kirgani o'zgarsa (chiqish, boshqa tabda chiqish, boshqa hisob) - tozalanadi.
watch(
  () => useAuth().user.value?.actorId ?? null,
  (now, before) => {
    if (now !== before) resetConnectors()
  },
)

export function useConnectors() {
  /** Login/parol bilan ulanish. Xato bo'lsa reject qiladi (ApiError) - oyna
   *  serverning xabarini ko'rsatadi. */
  async function connect(id: ConnectorId, username: string, password: string): Promise<void> {
    apply(await connectConnector(id, { username, password }))
  }

  async function disconnect(id: ConnectorId): Promise<void> {
    apply(await disconnectConnector(id))
  }

  return { connectors: readonly(connectors), loading, loaded, loadFailed, load, connect, disconnect }
}

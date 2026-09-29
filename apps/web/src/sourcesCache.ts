// Javob manbalari (MANBALAR) - brauzerda eslab qolinadi.
//
// NEGA. Yordamchining suhbat tarixi (`GET /api/chats/{id}`) har xabar uchun
// faqat rol, matn va vaqtni saqlaydi - iqtiboslar (`sources`) YO'Q. Ya'ni
// suhbat qayta ochilganda yoki sahifa yangilanganda javob ostidagi manbalar
// ro'yxati va matndagi [1] chiplari o'z ma'nosini yo'qotardi. Server
// tomonida tuzatilguncha bu yerda: har javobning manbalari suhbat kaliti
// bo'yicha localStorage'ga yoziladi, qayta ochilganda matn boshiga qarab
// (birinchi 120 belgi) o'z javobiga qaytariladi. Faqat SHU brauzerda -
// boshqa qurilmada ochilgan suhbatda manbalar bo'lmaydi.

import type { AnswerArtifact, AnswerSource } from './types'

const KEY = 'venera_sources_v1'
const KEY_LEN = 120
/** Shuncha suhbatdan ortig'i - eng eskisi o'chiriladi (localStorage ~5 MB). */
const MAX_CHATS = 120

interface Turn {
  /** Javob matnining boshi - qayta ochilganda moslash kaliti. */
  key: string
  sources: AnswerSource[]
  artifact?: AnswerArtifact | null
}
interface Entry {
  at: number
  turns: Turn[]
}
type Store = Record<string, Entry>

function load(): Store {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? (parsed as Store) : {}
  } catch {
    return {}
  }
}

function save(store: Store) {
  try {
    localStorage.setItem(KEY, JSON.stringify(store))
  } catch {
    /* localStorage yo'q yoki to'lgan - manbalar shunchaki eslanmaydi */
  }
}

function keyOf(answer: string): string {
  return answer.trim().slice(0, KEY_LEN)
}

/** Javob keldi - manbalarini shu suhbat ostida eslab qol. */
export function rememberSources(chatId: string, answer: string, sources: AnswerSource[], artifact?: AnswerArtifact | null) {
  const key = keyOf(answer)
  if (!key || (!sources.length && !artifact)) return
  const store = load()
  const entry = store[chatId] ?? { at: 0, turns: [] }
  const turn: Turn = { key, sources, ...(artifact ? { artifact } : {}) }
  const i = entry.turns.findIndex((t) => t.key === key)
  if (i >= 0) entry.turns[i] = turn
  else entry.turns.push(turn)
  entry.at = Date.now()
  store[chatId] = entry
  const ids = Object.keys(store)
  if (ids.length > MAX_CHATS) {
    ids.sort((a, b) => (store[a]?.at ?? 0) - (store[b]?.at ?? 0))
    for (const id of ids.slice(0, ids.length - MAX_CHATS)) delete store[id]
  }
  save(store)
}

/** Qayta ochilgan javob uchun manbalar, bo'lsa. */
export function recallSources(chatId: string, answer: string): Turn | null {
  const entry = load()[chatId]
  if (!entry) return null
  const key = keyOf(answer)
  return entry.turns.find((t) => t.key === key) ?? null
}

export function forgetSources(chatId: string) {
  const store = load()
  if (chatId in store) {
    delete store[chatId]
    save(store)
  }
}

/** Chiqishda: manbalar ro'yxatida HRM/CRM qisqa javoblari (xodim ma'lumoti) bo'lishi
 *  mumkin - keyingi odam shu brauzerda ularni ko'rmasin. */
export function clearSources() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* localStorage yo'q - tozalaydigan narsa ham yo'q */
  }
}

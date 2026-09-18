// Suhbatlar tarixi holati - yon paneldagi ro'yxat uchun.
//
// MANBA - SERVER (`/api/v1/chats`): suhbatlar yuqoridagi yordamchida turadi,
// brauzer faqat ro'yxatni ko'radi va to'rtta amalni so'raydi: ochish,
// nomini o'zgartirish, o'chirish (yumshoq), tiklash. Modul darajasidagi
// holat: yon panel yig'ilganda ro'yxat komponenti yo'q bo'lib ketadi,
// holat esa qolishi kerak; ChatView va ro'yxat bir manbadan o'qiydi.
//
// OPTIMISTIK: nom va o'chirish darhol ko'rinadi, server rad etsa
// qaytariladi. Bu yerda hech qanday saqlash yo'q - tiklash uchun ham server
// bor (`restoreChat`), ya'ni "Bekor qilish" hech narsani yo'qotmaydi.

import { readonly, ref } from 'vue'
import { deleteChat, listChats, openChat, renameChat, restoreChat } from '../api/chats.api'
import { ApiError } from '../api/http'
import type { ChatSummary } from '../types'

const chats = ref<ChatSummary[]>([])
/** Hozir ochiq suhbatning kaliti - ro'yxatda belgilanadi. Yangi (hali
 *  javobsiz) suhbat ro'yxatda yo'q, shuning uchun hech narsa belgilanmaydi. */
const activeId = ref<string | null>(null)
const loading = ref(false)
const loaded = ref(false)
const loadFailed = ref(false)
/** Oxirgi o'chirilgan suhbat - "Bekor qilish" bir necha soniya turadi. */
const lastDeleted = ref<ChatSummary | null>(null)

/** Ro'yxat kimniki. Boshqa odam kirsa eski ro'yxat bir lahza ham ko'rinmasin. */
let owner: string | null = null
let inflight: Promise<void> | null = null
let undoTimer: ReturnType<typeof setTimeout> | null = null
const titleTimers = new Map<string, ReturnType<typeof setTimeout>[]>()

/** "Bekor qilish" qancha turadi. */
const UNDO_MS = 8000
/** Model nomini olish uchun qayta so'rash vaqtlari. Xizmat nomni FONDA
 *  yozadi (javobdan bir necha soniya keyin); hujjat "bitta kechiktirilgan
 *  so'rov yetadi, so'rab turmang" deydi. Ikkitasi: LLM navbatda bo'lsa
 *  birinchisi erta kelib qolishi mumkin, uchinchisi endi so'rab turish. */
const TITLE_REFRESH_MS = [5000, 20000]

function stamp(iso: string | null | undefined): number {
  const t = iso ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? t : 0
}

function sortByActivity(): void {
  chats.value.sort((a, b) => stamp(b.updated_at) - stamp(a.updated_at))
}

function find(id: string): ChatSummary | undefined {
  return chats.value.find((c) => c.chat_id === id)
}

function upsert(summary: ChatSummary): void {
  const i = chats.value.findIndex((c) => c.chat_id === summary.chat_id)
  if (i >= 0) chats.value.splice(i, 1, summary)
  else chats.value.push(summary)
  sortByActivity()
}

function drop(id: string): void {
  const i = chats.value.findIndex((c) => c.chat_id === id)
  if (i >= 0) chats.value.splice(i, 1)
}

function cancelTitleRefresh(id: string): void {
  for (const timer of titleTimers.get(id) ?? []) clearTimeout(timer)
  titleTimers.delete(id)
}

/** Xizmat qoidasining nusxasi: birinchi 7 so'z, 60 belgigacha. Model nom
 *  bergunicha shu ko'rinadi. */
export function provisionalTitle(question: string): string {
  const words = question.trim().replace(/\s+/g, ' ').split(' ').slice(0, 7).join(' ')
  return words.length > 60 ? `${words.slice(0, 60).trimEnd()}…` : words
}

/** Model nomini olib kelish: bir-ikki marta, so'ng to'xtaydi. Har urinishda
 *  nom yangilanadi (xizmat avval o'zining "birinchi so'zlar" nomini beradi,
 *  keyin modelnikini); odam o'zi nom bergan bo'lsa (`user`) tegilmaydi. */
function scheduleTitleRefresh(id: string): void {
  cancelTitleRefresh(id)
  const timers = TITLE_REFRESH_MS.map((ms) =>
    setTimeout(async () => {
      const row = find(id)
      if (!row || row.title_source === 'user') {
        cancelTitleRefresh(id)
        return
      }
      try {
        // limit=1: faqat nom kerak, xabarlar emas.
        const fresh = await openChat(id, 1)
        const current = find(id)
        if (!current || current.title_source === 'user') return
        current.title = fresh.title
        current.title_source = fresh.title_source
        if (fresh.title_source === 'user') cancelTitleRefresh(id)
      } catch {
        // Hali saqlanmagan (404) yoki tarmoq - keyingi urinish yoki sahifa
        // yangilanganda ro'yxat baribir to'g'ri keladi.
      }
    }, ms),
  )
  titleTimers.set(id, timers)
}

/** Ro'yxatni serverdan oladi. `forUser` - kirgan odamning kaliti: boshqa
 *  odam bo'lsa eski ro'yxat avval tozalanadi. Parallel chaqiruvlar bitta
 *  so'rovni bo'lishadi. */
function load(forUser: string): Promise<void> {
  if (owner !== forUser) {
    reset()
    owner = forUser
  }
  if (inflight) return inflight
  loading.value = true
  inflight = (async () => {
    try {
      const { items } = await listChats()
      chats.value = items
      sortByActivity()
      loaded.value = true
      loadFailed.value = false
    } catch {
      loadFailed.value = true
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

/** "Qayta urinish" - o'sha odam uchun yana yuklash. Kirmagan bo'lsa hech narsa. */
function reload(): Promise<void> {
  return owner ? load(owner) : Promise.resolve()
}

/** Chiqishda: boshqa odam kirsa uning ro'yxati toza boshlansin. */
function reset(): void {
  for (const id of [...titleTimers.keys()]) cancelTitleRefresh(id)
  if (undoTimer) clearTimeout(undoTimer)
  undoTimer = null
  chats.value = []
  activeId.value = null
  loaded.value = false
  loadFailed.value = false
  lastDeleted.value = null
  owner = null
}

function select(id: string | null): void {
  activeId.value = id
}

/** Javob keldi. Suhbat ro'yxatda bo'lmasa - endi bor (xizmat uni birinchi
 *  javob bilan yaratdi): vaqtinchalik nom bilan tepaga qo'yiladi va model
 *  nomi keyinroq olib kelinadi. Bo'lsa - tepaga ko'tariladi. */
function noteTurn(chatId: string, question: string): void {
  const now = new Date().toISOString()
  const existing = find(chatId)
  if (existing) {
    existing.updated_at = now
    if (typeof existing.messages === 'number') existing.messages += 2
    sortByActivity()
    return
  }
  upsert({
    chat_id: chatId,
    title: provisionalTitle(question),
    title_source: 'auto',
    created_at: now,
    updated_at: now,
    messages: 2,
  })
  scheduleTitleRefresh(chatId)
}

/** Nomini o'zgartirish - darhol ko'rinadi, server rad etsa qaytariladi va
 *  xato tashlanadi (ApiError - ro'yxat serverning xabarini ko'rsatadi). */
async function rename(id: string, title: string): Promise<void> {
  const row = find(id)
  if (!row) return
  const clean = title.replace(/\s+/g, ' ').trim()
  if (!clean || clean === row.title) return
  const before = { title: row.title, title_source: row.title_source }
  row.title = clean
  row.title_source = 'user'
  cancelTitleRefresh(id)
  try {
    upsert(await renameChat(id, clean))
  } catch (err) {
    Object.assign(row, before)
    throw err
  }
}

/** O'chirish - darhol ro'yxatdan chiqadi, serverda yumshoq o'chiriladi va
 *  "Bekor qilish" ochiladi. Server rad etsa qator qaytariladi. */
async function remove(id: string): Promise<void> {
  const row = find(id)
  if (!row) return
  drop(id)
  cancelTitleRefresh(id)
  if (activeId.value === id) activeId.value = null
  try {
    await deleteChat(id)
  } catch (err) {
    upsert(row)
    throw err
  }
  lastDeleted.value = row
  if (undoTimer) clearTimeout(undoTimer)
  undoTimer = setTimeout(() => {
    lastDeleted.value = null
    undoTimer = null
  }, UNDO_MS)
}

/** "Bekor qilish": suhbat nomi va xabarlari bilan qaytadi. */
async function undoDelete(): Promise<void> {
  const row = lastDeleted.value
  if (!row) return
  dismissUndo()
  try {
    upsert(await restoreChat(row.chat_id))
  } catch (err) {
    // 404: hech qachon bo'lmagan - qaytaradigan narsa yo'q, jim.
    if (err instanceof ApiError && err.status === 404) return
    throw err
  }
}

function dismissUndo(): void {
  if (undoTimer) clearTimeout(undoTimer)
  undoTimer = null
  lastDeleted.value = null
}

/** Ochilganda 404: boshqa qurilmadan o'chirilgan yoki boshqa odamniki -
 *  ro'yxatdan tushiriladi. */
function forget(id: string): void {
  drop(id)
  cancelTitleRefresh(id)
  if (activeId.value === id) activeId.value = null
}

export function useChats() {
  return {
    chats: readonly(chats),
    activeId: readonly(activeId),
    loading,
    loaded,
    loadFailed,
    lastDeleted: readonly(lastDeleted),
    load,
    reload,
    reset,
    select,
    noteTurn,
    rename,
    remove,
    undoDelete,
    dismissUndo,
    forget,
  }
}

// Suhbatlar tarixi - faqat HTTP; holat `composables/useChats.ts` da.
//
// Suhbatlar yuqoridagi yordamchida saqlanadi (har savol bilan ketadigan
// `chatId` bo'yicha), Venera backend'i esa proksi qiladi va KIMLIKNI O'ZI
// qo'yadi: brauzer `user_id` yubormaydi. Shu sababli boshqa odamning
// suhbatiga - kalitini bilgan holda ham - kirib bo'lmaydi (404).
//
// Suhbat yaratadigan chaqiruv yo'q: yangi `chatId` bilan birinchi savol
// (`streamAsk`) uni yaratadi. Ro'yxatga u birinchi javob kelgach tushadi.

import { apiFetch } from './http'
import type { ChatDeleted, ChatDetail, ChatList, ChatSummary } from '../types'

function chatPath(id: string): string {
  return `/api/v1/chats/${encodeURIComponent(id)}`
}

/** Oxirgi faollik bo'yicha, yangisi birinchi. O'chirilganlar chiqmaydi. */
export function listChats(limit = 50, offset = 0): Promise<ChatList> {
  return apiFetch<ChatList>(`/api/v1/chats?limit=${limit}&offset=${offset}`)
}

/** Nom va xabarlar (eskisi birinchi, oxirgi `limit` tasi, 1000 gacha). */
export function openChat(id: string, limit = 200): Promise<ChatDetail> {
  return apiFetch<ChatDetail>(`${chatPath(id)}?limit=${limit}`)
}

/** 1-80 belgi. Shundan keyin model nomni qayta yozmaydi. */
export function renameChat(id: string, title: string): Promise<ChatSummary> {
  return apiFetch<ChatSummary>(chatPath(id), { method: 'PATCH', body: JSON.stringify({ title }) })
}

/** YUMSHOQ o'chirish - `restoreChat` qaytaradi. Takroriy chaqiruv xato emas. */
export function deleteChat(id: string): Promise<ChatDeleted> {
  return apiFetch<ChatDeleted>(chatPath(id), { method: 'DELETE' })
}

export function restoreChat(id: string): Promise<ChatSummary> {
  return apiFetch<ChatSummary>(`${chatPath(id)}/restore`, { method: 'POST' })
}

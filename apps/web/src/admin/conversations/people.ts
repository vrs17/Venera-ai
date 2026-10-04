// Tanish odamlar va suhbatlar nomlari - filtr chip'ida "Foydalanuvchi: Ali Valiyev"
// deb yozish uchun. URL'da faqat id turadi (`?actor=12`, `?chat=...`); nom esa
// ro'yxat qatorlari, qidiruv natijalari va bosilgan suhbatdan yig'iladi. Modul
// darajasida: savol iziga o'tib qaytganda ham nom yo'qolmasin.

import { reactive } from 'vue'

export interface Person {
  actorId: number
  name: string
  login: string | null
}

const people = reactive(new Map<number, Person>())
const chats = reactive(new Map<string, string>())

export function rememberPerson(actorId: number | null | undefined, name: string | null | undefined, login?: string | null) {
  if (!actorId) return
  const clean = name?.trim() || login?.trim() || ''
  if (!clean) return
  const old = people.get(actorId)
  if (old && old.name === clean && (old.login ?? null) === (login ?? null)) return
  people.set(actorId, { actorId, name: clean, login: login?.trim() || old?.login || null })
}

export function personName(actorId: number | null | undefined): string | null {
  return actorId ? (people.get(actorId)?.name ?? null) : null
}

export function rememberChat(chatId: string | null | undefined, title: string | null | undefined) {
  const clean = title?.trim()
  if (chatId && clean && chats.get(chatId) !== clean) chats.set(chatId, clean)
}

export function chatTitle(chatId: string | null | undefined): string | null {
  return chatId ? (chats.get(chatId) ?? null) : null
}

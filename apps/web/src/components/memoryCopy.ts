// Barno XOTIRASI matnlaridan biri - web (MemoryDialog) va Mini App (MemorySheet) uchun bitta
// joyda, chunki ikkalasi bir xil gapni aytishi shart.

import type { MemoryItem } from '../api/assistant.api'

type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string

/**
 * "Hammasini unutish" tasdig'ining izohi: nechta narsa unutiladi va suhbatlar qolishi.
 * "Qaytarib bo'lmaydi" bu yerda YO'Q - u "Tushundim" katakchasida (bir ekranda ikki marta
 * aytilmasin). CRM vazifalaridan o'rganilgan tartib haqidagi gap FAQAT shunday band bo'lsa:
 * aks holda odam "menda CRM tartibi bormi?" deb o'ylab qolardi (UX ko'rigi, 2026-10-10).
 */
export function forgetAllHint(items: readonly MemoryItem[], t: Translate): string {
  const n = items.length
  const base = t('assistant.memory.forgetAllHint', { n }, n)
  return items.some((m) => m.kind === 'routine') ? `${base} ${t('assistant.memory.forgetAllRoutines')}` : base
}

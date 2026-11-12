// Barno jonli ma'lumot oladigan PLATFORMALAR (HRM, CRM) - web, Mini App va admin uchun
// BITTA ro'yxat: belgi, nom (`assistant.platform.*`) va manba turi bo'yicha qaror.
//
// 2026-11-12 (ega qarori): vaqtinchalik namoyish manbalari olib tashlandi - ro'yxatda faqat
// haqiqiy tizimlar. Yangi platforma - shu yerga bitta yozuv + `i18n/assistant.ts` da nom.
//
// ESKI JAVOBLAR. Brauzer keshida (`sourcesCache.ts`) va admin izida olib tashlangan
// manbalarning turlari hali uchraydi. Ular NOTANISH tur sifatida chiziladi: umumiy belgi
// (vilka) va umumiy nom (`assistant.platform.other`). Xom kalit odamga ko'rinmaydi, sahifa
// yiqilmaydi - shuning uchun bu yerdagi har funksiya notanish qiymatga chidamli.

import type { Component } from 'vue'
import { Plug, SquareKanban, Users } from 'lucide-vue-next'
import type { AnswerSource } from '../../types'

/** Ma'lum platformalar. Hammasi JONLI: so'rov `[T1]` bo'lib keladi, ochiladigan fayli yo'q. */
export const PLATFORM_IDS = ['hrm', 'crm'] as const
export type PlatformId = (typeof PLATFORM_IDS)[number]

const KNOWN = new Set<string>(PLATFORM_IDS)

export function isPlatformId(value: unknown): value is PlatformId {
  return typeof value === 'string' && KNOWN.has(value)
}

/** Belgilar: HRM - odamlar, CRM - kanban. Notanish tur - vilka (ulanish). */
const ICONS: Record<PlatformId, Component> = {
  hrm: Users,
  crm: SquareKanban,
}

export function platformIcon(id: string | null | undefined): Component {
  const key = String(id ?? '').toLowerCase()
  return isPlatformId(key) ? ICONS[key] : Plug
}

type Translate = (key: string) => string

/** Platforma nomi - tarjimadan. Notanish tur - umumiy nom ("Boshqa manba"), xom kalit emas. */
export function platformName(id: string | null | undefined, t: Translate): string {
  const key = String(id ?? '').toLowerCase()
  return t(`assistant.platform.${isPlatformId(key) ? key : 'other'}`)
}

/** Asbob nomidan platforma: `crm_my_issues` -> `crm`. */
function platformFromTool(tool: string | null | undefined): PlatformId | null {
  const name = String(tool ?? '').toLowerCase()
  return PLATFORM_IDS.find((id) => name === id || name.startsWith(`${id}_`)) ?? null
}

/** Manba qaysi platformadan: avval `kind`, bo'lmasa asbob nomining prefiksi. */
export function platformOfSource(source: AnswerSource): PlatformId | null {
  const kind = String(source.kind ?? '').toLowerCase()
  if (isPlatformId(kind)) return kind
  return platformFromTool(source.tool)
}

/**
 * Manba JONLI SO'ROVMI (hujjatlar ro'yxatiga emas, "tizimdan" qatoriga tushadimi).
 * Ma'lum platforma - doim. Notanish tur (eski javoblardagi olib tashlangan manba) - vosita
 * belgisi (`tool` yoki `[T1]`) bor va `[n]` raqami yo'q bo'lsa: aks holda u hujjat bo'lib,
 * mavjud bo'lmagan faylga "ochish" tugmasi chiqardi. Backend ham shu qoidada
 * (`answer_sources.is_lookup`).
 */
export function isLookupSource(source: AnswerSource): boolean {
  if (isPlatformId(String(source.kind ?? '').toLowerCase())) return true
  return source.citation_index == null && !!(source.tool || source.marker)
}

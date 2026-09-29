// Javob manbalari bo'yicha umumiy yordamchilar (matndagi chiplar va manbalar qatori).

import type { AnswerSource } from '../../types'

/** HUJJAT emas, JONLI SO'ROV bo'lgan turlar. `crm` 2026-09-14 da qo'shildi - undan
 *  oldin CRM manbasi hujjatlar ro'yxatiga tushib, mavjud bo'lmagan fayl sifatida
 *  "ochiladigan" bo'lib chiqardi. Yangi platforma - shu yerga bitta yozuv. */
export const LOOKUP_KINDS = new Set(['hrm', 'crm'])

export function isLookup(source: AnswerSource): boolean {
  return LOOKUP_KINDS.has(String(source.kind))
}

/** Matndagi marker (`T1`), qavslarsiz. Xizmat uni ba'zan `[T1]` deb yuboradi. */
export function lookupMarker(source: AnswerSource, index: number): string {
  return (source.marker?.trim() || `T${index + 1}`).replace(/^\[|\]$/g, '')
}

/**
 * So'rovning odamga tushunarli nomi: `hrm_today_late` -> "HRM · Today late".
 * Xom asbob nomi - dasturchi tili; to'liq nom admin izida ko'rinadi.
 */
export function lookupLabel(source: AnswerSource, fallback = ''): string {
  const tool = source.tool?.trim()
  if (!tool) return String(source.kind ?? fallback).toUpperCase() || fallback
  const [prefix, ...rest] = tool.split('_')
  const platform = LOOKUP_KINDS.has(prefix.toLowerCase()) ? prefix.toUpperCase() : ''
  const words = (platform ? rest : [prefix, ...rest]).join(' ').trim()
  const text = words ? words.charAt(0).toLocaleUpperCase() + words.slice(1) : ''
  return [platform, text].filter(Boolean).join(' · ') || tool
}

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

/* ── Qonunchilik (`kind: "law"`, v2 dvigatel, 2026-10-02) ──────────────────
 *
 * Yordamchi Mehnat kodeksi moddasini hujjat kabi `[n]` bilan belgilaydi, lekin u
 * BIZNING hujjatimiz emas: `doc_id` yo'q, ko'ruvchida ochilmaydi - LEX.UZ dagi
 * moddaga havola (`url`) bilan keladi va yangi oynada ochiladi.
 */
export function isLaw(source: AnswerSource): boolean {
  return String(source.kind ?? '').toLowerCase() === 'law'
}

/** LEX.UZ'dan boshqa xost ham `https` bo'lsa ruxsat - backend uni jurnalga yozadi. */
const LAW_HOST = /(^|\.)lex\.uz$/i

/**
 * Havola qilib bo'ladigan manzil yoki `null`. FAQAT `https://`: manzil yuqoridagi
 * xizmatdan keladi va `<a href>` ga tushadi - `javascript:` / `data:` yoki oddiy
 * `http` (o'rtadagi odam almashtira oladi) havola bo'lmaydi, matn bo'lib qoladi.
 * Backend ham shuni qiladi; bu yerda - eski kesh (`sourcesCache`) va admin nusxalari
 * uchun ikkinchi qavat.
 */
export function lawUrl(source: AnswerSource): string | null {
  return safeHttps(source.url)
}

export function safeHttps(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const value = raw.trim()
  if (!/^https:\/\//i.test(value)) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname ? url.href : null
  } catch {
    return null
  }
}

/** Izohdagi sayt nomi: LEX.UZ - shunday; boshqa `https` xost - o'z nomi bilan
 *  (u yerga "LEX.UZ" deb yozish odamni aldagan bo'lardi). Havola yo'q - LEX.UZ:
 *  xizmat qonunni faqat shu yerdan oladi. */
export function lawSite(url: string | null): string {
  if (!url) return 'LEX.UZ'
  try {
    const host = new URL(url).hostname
    return LAW_HOST.test(host) ? 'LEX.UZ' : host.replace(/^www\./i, '')
  } catch {
    return 'LEX.UZ'
  }
}

/** Ro'yxatdagi nom: modda sarlavhasi, bo'lmasa - manzil. */
export function lawTitle(source: AnswerSource, fallback: string): string {
  return source.title?.trim() || lawUrl(source) || fallback
}

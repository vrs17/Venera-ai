// Javob manbalari bo'yicha umumiy yordamchilar (matndagi chiplar va manbalar qatori).

import type { AnswerSource } from '../../types'
import { KNOWN_TOOLS } from '../../i18n/tools'
import { isLookupSource, platformName, platformOfSource, KNOWLEDGE_PLATFORMS, LIVE_PLATFORMS } from './platforms'

/** HUJJAT emas, JONLI SO'ROV bo'lgan turlar. `crm` 2026-09-14 da qo'shildi - undan
 *  oldin CRM manbasi hujjatlar ro'yxatiga tushib, mavjud bo'lmagan fayl sifatida
 *  "ochiladigan" bo'lib chiqardi. 2026-10-10: DWH, Biznes 24/7, Superapp (jonli) va
 *  qo'llanmalar (raqamsiz kelsa) - ro'yxat `platforms.ts` da, bu yerda faqat qayta eksport. */
export const LOOKUP_KINDS: ReadonlySet<string> = LIVE_PLATFORMS

export function isLookup(source: AnswerSource): boolean {
  return isLookupSource(source)
}

/** Matndagi marker (`T1`), qavslarsiz. Xizmat uni ba'zan `[T1]` deb yuboradi. */
export function lookupMarker(source: AnswerSource, index: number): string {
  return (source.marker?.trim() || `T${index + 1}`).replace(/^\[|\]$/g, '')
}

/**
 * FOYDALANUVCHIGA ko'rinadigan so'rov nomi - web chat va Mini App uchun BITTA qoida
 * (2026-10-10, UX ko'rigi):
 *   * asbob nomining tarjimasi bor (`tools.*`) - "CRM · Vazifa maʼlumoti";
 *   * yo'q - faqat platforma nomi ("DWH", "Biznes 24/7"); nima topilgani ostida (`digest`).
 * Xom asbob nomi ("Branch kpi", "Users") HECH QACHON - u dasturchi tili, admin izida qoladi
 * (`lookupLabel`). Platforma ham noma'lum bo'lsa - `kind` katta harfda (avvalgidek).
 */
export function lookupTitle(source: AnswerSource, t: (key: string) => string): string {
  const platform = platformOfSource(source)
  const name = platform ? platformName(platform, t) : String(source.kind ?? '').trim().toUpperCase() || 'HRM'
  const tool = source.tool?.trim().toLowerCase() ?? ''
  if (KNOWN_TOOLS.has(tool)) return `${name} · ${t(`tools.${tool}`)}`
  // Qo'llanmadan raqamsiz so'rov: maqola nomi odam tilida - u ko'rsatiladi (xom nom emas).
  const title = platform && KNOWLEDGE_PLATFORMS.has(platform) ? source.title?.trim() : ''
  return title ? `${name} · ${title}` : name
}

/**
 * ADMIN izi uchun so'rov nomi (asbob nomi ko'rinadi): `hrm_today_late` -> "HRM · Today late",
 * `biznes247_kb_search` -> "Biznes 24/7 qo'llanmalari · Search". Platforma `kind` dan
 * (bo'lmasa asbob prefiksidan); `t` berilsa - tarjima qilingan nom (`assistant.platform.*`),
 * berilmasa - id katta harfda. Xom asbob nomi - dasturchi tili; to'liq nom admin izida.
 */
export function lookupLabel(source: AnswerSource, fallback = '', t?: (key: string) => string): string {
  const tool = source.tool?.trim() ?? ''
  const platform = platformOfSource(source)
  const name = platform ? (t ? platformName(platform, t) : platform.toUpperCase()) : ''
  if (!tool) return name || String(source.kind ?? fallback).toUpperCase() || fallback
  const lower = tool.toLowerCase()
  const rest = platform && lower === platform ? '' : platform && lower.startsWith(`${platform}_`) ? tool.slice(platform.length + 1) : tool
  const words = rest.split('_').join(' ').trim()
  const text = words ? words.charAt(0).toLocaleUpperCase() + words.slice(1) : ''
  return [name, text].filter(Boolean).join(' · ') || tool
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

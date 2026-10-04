// Javob manbalari -> Mini App qatori va oynasi uchun bitta ro'yxat.
//
// Turlari va qoidalari web bilan BIR XIL (`components/chat/sources.ts`): hujjat `[1]`,
// qonun moddasi (`law`, LEX.UZ) ham `[n]` - raqamlash umumiy, jonli so'rov (HRM/CRM)
// `[T1]`. Bu yerda faqat telefon uchun tartib: avval iqtiboslar raqam bo'yicha, keyin
// jonli so'rovlar - odam matnda ko'rgan raqamni ro'yxatda o'sha tartibda topadi.
//
// NOMLAR XODIM TILIDA. "T1" va "CRM · Issue get" (xom asbob nomi) odamga hech narsa
// demaydi: matndagi chip tizim nomi bilan ("CRM"), ro'yxatda - "CRM · Vazifa
// ma'lumoti" (`tg.tools.*`). Notanish asbob - "Tizim ma'lumoti", xom nom emas.
// "3.4" bo'limi - "3.4-band": yalang'och raqam sana yoki summa bo'lib o'qilardi.

import type { AnswerSource } from '../../types'
import { isLaw, isLookup, lawSite, lawTitle, lawUrl, lookupMarker } from '../../components/chat/sources'
import { KNOWN_TOOLS } from '../i18n'
import { uzApostrophes } from './polish'

type Translate = (key: string, named?: Record<string, unknown>) => string

export interface SourceItem {
  /** Matndagi belgi: "1", "T1" - chip va oyna shu bilan bog'lanadi. */
  marker: string
  kind: 'doc' | 'law' | 'lookup'
  /** Odamga ko'rinadigan qisqa belgi: hujjat/qonun - raqam, so'rov - "HRM"/"CRM". */
  badge: string
  title: string
  /** Bir qator izoh: sahifa/bo'lim, "LEX.UZ · qonunchilik" yoki so'rov natijasi. */
  meta: string
  /** Xizmat yuborsa - hujjatdan parcha (jonli xizmatda bo'lmasligi mumkin). */
  snippet: string
  /** Faqat qonun: tekshirilgan `https://` havola. */
  url: string | null
  failed: boolean
  source: AnswerSource
}

/** So'rov tizimi: "HRM" / "CRM" (asbob nomining prefiksi yoki `kind`). */
export function connectorOf(source: AnswerSource): string {
  const kind = String(source.kind ?? '').trim()
  if (kind) return kind.toUpperCase()
  const prefix = source.tool?.split('_')[0] ?? ''
  return prefix.toUpperCase() || 'HRM'
}

/** "CRM · Vazifa ma'lumoti" - tanish asbob tarjimadan, notanishi umumiy nom bilan. */
export function toolLabel(source: AnswerSource, t: Translate): string {
  const tool = source.tool?.trim().toLowerCase() ?? ''
  const name = KNOWN_TOOLS.has(tool) ? t(`tg.tools.${tool}`) : t('tg.tools.fallback')
  return `${connectorOf(source)} · ${name}`
}

/** "3.4" -> "3.4-band"; matnli bo'lim nomi o'zgarishsiz. */
function sectionLabel(section: string | null | undefined, t: Translate): string {
  const value = section?.trim() ?? ''
  if (!value) return ''
  return /^\d+(\.\d+)*\.?$/.test(value) ? t('tg.sources.section', { n: value.replace(/\.$/, '') }) : value
}

/** Matndagi `[T1]` -> chipda ko'rinadigan tizim nomi (polish.ts). */
export function lookupBadges(sources: AnswerSource[] | undefined): Map<string, string> {
  const map = new Map<string, string>()
  const calls = (sources ?? []).filter(isLookup)
  calls.forEach((s, i) => map.set(lookupMarker(s, i), connectorOf(s)))
  return map
}

/** `uzLatin` - hujjat nomi va parchasidagi `'` ham `ʻ`/`ʼ` ga (javob matni bilan bir xil). */
export function sourceItems(sources: AnswerSource[] | undefined, t: Translate, uzLatin = false): SourceItem[] {
  const cites: SourceItem[] = []
  const lookups: SourceItem[] = []
  ;(sources ?? []).forEach((source, i) => {
    if (isLookup(source)) {
      lookups.push({
        marker: lookupMarker(source, lookups.length),
        kind: 'lookup',
        badge: connectorOf(source),
        title: toolLabel(source, t),
        meta: source.digest?.trim() ?? '',
        snippet: '',
        url: null,
        failed: !!source.status && !/^(ok|success|200)$/i.test(String(source.status)),
        source,
      })
      return
    }
    const marker = String(source.citation_index ?? i + 1)
    const snippet = String((source as { snippet?: unknown }).snippet ?? '').trim()
    if (isLaw(source)) {
      const url = lawUrl(source)
      cites.push({
        marker,
        kind: 'law',
        badge: marker,
        title: lawTitle(source, t('sourceDocument')),
        meta: t('chat.lawCaption', { site: lawSite(url) }),
        snippet,
        url,
        failed: false,
        source,
      })
      return
    }
    const parts = [source.page ? t('sourcePage', { n: source.page }) : '', sectionLabel(source.section, t)].filter(Boolean)
    cites.push({
      marker,
      kind: 'doc',
      badge: marker,
      title: source.title?.trim() || source.doc_id || t('sourceDocument'),
      meta: parts.join(' · '),
      snippet,
      url: null,
      failed: false,
      source,
    })
  })
  cites.sort((a, b) => Number(a.marker) - Number(b.marker) || 0)
  const all = [...cites, ...lookups]
  if (!uzLatin) return all
  return all.map((item) => ({
    ...item,
    title: uzApostrophes(item.title),
    meta: uzApostrophes(item.meta),
    snippet: uzApostrophes(item.snippet),
  }))
}

// Javob manbalari -> Mini App qatori va oynasi uchun bitta ro'yxat.
//
// Turlari va qoidalari web bilan BIR XIL (`components/chat/sources.ts`): hujjat `[1]`,
// qonun moddasi (`law`, LEX.UZ) ham `[n]` - raqamlash umumiy, jonli so'rov (HRM/CRM)
// `[T1]`. Bu yerda faqat telefon uchun tartib: avval iqtiboslar raqam bo'yicha, keyin
// jonli so'rovlar - odam matnda ko'rgan raqamni ro'yxatda o'sha tartibda topadi.
//
// NOMLAR XODIM TILIDA. "T1" va "CRM · Issue get" (xom asbob nomi) odamga hech narsa
// demaydi: `[T1]` matnda ko'rinmaydi (2026-10-10), ro'yxatda - "CRM · Vazifa
// ma'lumoti" (`tools.*`). Notanish asbob - faqat platforma nomi ("CRM"), natijasi
// ostida: web bilan BITTA qoida (`lookupTitle`, components/chat/sources.ts).
// "3.4" bo'limi - "3.4-band": yalang'och raqam sana yoki summa bo'lib o'qilardi.
//
// PLATFORMALAR - HRM va CRM (`components/chat/platforms.ts`): nom tarjimadan, belgi -
// platformaniki (`platform` maydoni). Eski javobdagi notanish tizim - umumiy nom va belgi.

import type { AnswerSource } from '../../types'
import { isLaw, isLookup, lawSite, lawTitle, lawUrl, lookupMarker, lookupTitle } from '../../components/chat/sources'
import { platformName, platformOfSource } from '../../components/chat/platforms'
import type { PlatformId } from '../../components/chat/platforms'
import { uzApostrophes } from './polish'

type Translate = (key: string, named?: Record<string, unknown>) => string

export interface SourceItem {
  /** Matndagi belgi: "1", "T1" - chip va oyna shu bilan bog'lanadi. */
  marker: string
  kind: 'doc' | 'law' | 'lookup'
  /** So'rov: qaysi platformadan (chip belgisi shunga qarab); notanish tizim - `null`. */
  platform: PlatformId | null
  /** Odamga ko'rinadigan qisqa belgi: hujjat/qonun - raqam, so'rov - "HRM"/"CRM". */
  badge: string
  title: string
  /** Bir qator izoh: sahifa/bo'lim, "LEX.UZ · qonunchilik" yoki so'rov natijasi. */
  meta: string
  /** Xizmat yuborsa - hujjatdan parcha (jonli xizmatda bo'lmasligi mumkin). */
  snippet: string
  /** Qonun: tekshirilgan `https://` havola. */
  url: string | null
  failed: boolean
  source: AnswerSource
}

/** So'rov tizimi: "HRM", "CRM" (`kind`, bo'lmasa asbob prefiksi). Notanish tur - umumiy
 *  nom (`platformName`), xom kalit emas. */
export function connectorOf(source: AnswerSource, t: Translate): string {
  return platformName(platformOfSource(source), t)
}

/** "CRM · Vazifa ma'lumoti" - tanish asbob tarjimadan; notanishi - faqat platforma nomi
 *  ("CRM"). Web bilan bir xil (`lookupTitle`). */
export function toolLabel(source: AnswerSource, t: Translate): string {
  return lookupTitle(source, t)
}

/** "3.4" -> "3.4-band"; matnli bo'lim nomi o'zgarishsiz. */
function sectionLabel(section: string | null | undefined, t: Translate): string {
  const value = section?.trim() ?? ''
  if (!value) return ''
  return /^\d+(\.\d+)*\.?$/.test(value) ? t('tg.sources.section', { n: value.replace(/\.$/, '') }) : value
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
        platform: platformOfSource(source),
        badge: connectorOf(source, t),
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
        platform: null,
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
      platform: null,
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

// Yordamchi versiyasi -> nom, tavsif va "umumiy" qiymatlar. "Versiyalar" sahifasi,
// alohida ruxsat oynasi va foydalanuvchi varag'i BIR XIL gapirsin: bir joyda "v2 · Yangi",
// boshqasida "v2 (new)" bo'lsa admin ikkisini ikki xil narsa deb o'ylab qoladi.
//
// Nomlar serverda YO'Q (u faqat kalit va imkoniyat beradi) - shu yerda, tarjimadan.
// Noma'lum versiya (ertaga "v3") - faqat kaliti: yashirgandan ko'ra xom ko'rsatgan yaxshi.

import { ENGINES } from '../types'
import type { AdminEngines, EngineChannel } from '../types'

type Translate = (key: string, named?: Record<string, unknown>) => string
type Exists = (key: string) => boolean

/** "Barqaror" / "Yangi"; noma'lum - bo'sh satr. */
export function engineName(id: string, t: Translate, te: Exists): string {
  if (!id) return ''
  const key = `admin.versions.${id}`
  return te(key) ? t(key) : ''
}

/** Bitta qator tavsif; noma'lum - bo'sh satr. */
export function engineDesc(id: string, t: Translate, te: Exists): string {
  if (!id) return ''
  const key = `admin.versions.${id}Desc`
  return te(key) ? t(key) : ''
}

/** "v2 · Yangi". Bo'sh kalit - `.env` dagi versiyasiz yo'l ("Versiyasiz"). */
export function engineLabel(id: string | null | undefined, t: Translate, te: Exists): string {
  if (id === null || id === undefined) return '—'
  if (id === '') return t('admin.engine.default')
  const name = engineName(id, t, te)
  return name ? `${id} · ${name}` : id
}

/** Hamma uchun versiya: admin aytgani, aytmagan bo'lsa `.env`. Kanal sozlamalari bundan
 *  ustun (kanal bo'yicha `effective` da). */
export function publicDefault(data: AdminEngines): string {
  return data.policy.default ?? data.envDefaults.default ?? ''
}

/** Kanalda "Umumiy" tanlansa nima ishlaydi (backend `_public` tartibi): admin default'i,
 *  bo'lmasa `.env` ning shu kanal qiymati, u ham bo'lmasa `.env` default'i. */
export function inheritedFor(data: AdminEngines, channel: EngineChannel): string {
  return data.policy.default ?? (data.envDefaults.channels[channel] || data.envDefaults.default || '')
}

/** Katalog kalitlari; server bo'sh bersa - ma'lum ikkitasi (oyna baribir ishlasin). */
export function catalogIds(data: Pick<AdminEngines, 'catalog'> | null | undefined): string[] {
  const ids = (data?.catalog ?? []).map((e) => e.id).filter((id) => !!id)
  return ids.length ? ids : [...ENGINES]
}

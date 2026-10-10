// Barno o'qiydigan PLATFORMALAR - web, Mini App va admin uchun BITTA ro'yxat: belgi,
// nom va bir qatorlik vazifa (`assistant.platform.*`), manba turi bo'yicha qaror.
//
// 2026-10-10 (yordamchi 3.3): HRM va CRM ga DWH, Biznes 24/7, Superapp, Biznes 24/7
// qo'llanmalari va Biznes Help qo'shildi. Ular ikki joyda ko'rinadi:
//   * javob manbalarida (`sources[].kind`) - chip belgisi va nomi;
//   * sozlamalarda (platforma kalitlari) - belgi, nom, vazifasi va kalit.
// Yangi platforma - shu yerga bitta yozuv + `i18n/assistant.ts` da nom va vazifa.
//
// NEGA ID BO'YICHA O'Z TARJIMAMIZ. Xizmat `name` va `description` beradi, lekin faqat
// o'zbekcha; interfeys esa 4 tilda. Tarjima yo'q (yangi, bizga notanish) platforma -
// xizmatning o'z matni bilan ko'rinadi, bo'sh qolmaydi.

import type { Component } from 'vue'
import { BookOpenText, BriefcaseBusiness, Database, LifeBuoy, Plug, Smartphone, SquareKanban, Users } from 'lucide-vue-next'
import type { Platform } from '../../api/assistant.api'
import type { AnswerSource, ConnectorStatus } from '../../types'

/** Ma'lum platformalar - sozlamalardagi tartib ham shu. */
export const PLATFORM_IDS = ['hrm', 'crm', 'dwh', 'biznes247', 'superapp', 'biznes247_kb', 'biznes247_help'] as const
export type PlatformId = (typeof PLATFORM_IDS)[number]

const KNOWN = new Set<string>(PLATFORM_IDS)

export function isPlatformId(value: unknown): value is PlatformId {
  return typeof value === 'string' && KNOWN.has(value)
}

/**
 * JONLI so'rov (`[T1]`) bo'ladigan turlar - hujjat emas, ochiladigan fayli yo'q.
 * Qo'llanmalar (`biznes247_kb`, `biznes247_help`) BILIM manbai: `[n]` raqami bilan
 * kelsa - iqtibos (hujjatlar qatorida, havolasi bo'lsa tashqi sahifa), raqamsiz kelsa -
 * so'rov sifatida ko'rsatiladi (`isLookupSource`).
 */
export const LIVE_PLATFORMS: ReadonlySet<string> = new Set(['hrm', 'crm', 'dwh', 'biznes247', 'superapp'])
export const KNOWLEDGE_PLATFORMS: ReadonlySet<string> = new Set(['biznes247_kb', 'biznes247_help'])

/**
 * Belgilar: HRM - odamlar, CRM - kanban, DWH - ma'lumotlar ombori, Biznes 24/7 - biznes
 * portfeli (bankning biznes ilovasi), Superapp - telefon, qo'llanmalar - kitob, Help -
 * qutqaruv halqasi ("yordam"). Notanish platforma - vilka (ulanish).
 */
const ICONS: Record<PlatformId, Component> = {
  hrm: Users,
  crm: SquareKanban,
  dwh: Database,
  biznes247: BriefcaseBusiness,
  superapp: Smartphone,
  biznes247_kb: BookOpenText,
  biznes247_help: LifeBuoy,
}

export function platformIcon(id: string | null | undefined): Component {
  const key = String(id ?? '').toLowerCase()
  return isPlatformId(key) ? ICONS[key] : Plug
}

type Translate = (key: string) => string

/** "Biznes 24/7 qo'llanmalari" - tarjimadan; notanishi - xizmat nomi yoki id (katta harf). */
export function platformName(id: string | null | undefined, t: Translate, fallback?: string | null): string {
  const key = String(id ?? '').toLowerCase()
  if (isPlatformId(key)) return t(`assistant.platform.${key}.name`)
  return fallback?.trim() || key.toUpperCase()
}

/** Bir qator: Barno undan nima oladi. Notanishi - xizmatning `description` i. */
export function platformPurpose(id: string | null | undefined, t: Translate, fallback?: string | null): string {
  const key = String(id ?? '').toLowerCase()
  if (isPlatformId(key)) return t(`assistant.platform.${key}.purpose`)
  return fallback?.trim() ?? ''
}

/** Asbob nomidan platforma: `biznes247_kb_search` -> `biznes247_kb` (eng uzun mos prefiks). */
function platformFromTool(tool: string | null | undefined): PlatformId | null {
  const name = String(tool ?? '').toLowerCase()
  if (!name) return null
  let best: PlatformId | null = null
  for (const id of PLATFORM_IDS) {
    if ((name === id || name.startsWith(`${id}_`)) && (!best || id.length > best.length)) best = id
  }
  return best
}

/** Manba qaysi platformadan: avval `kind`, bo'lmasa asbob nomining prefiksi. */
export function platformOfSource(source: AnswerSource): PlatformId | null {
  const kind = String(source.kind ?? '').toLowerCase()
  if (isPlatformId(kind)) return kind
  return platformFromTool(source.tool)
}

/**
 * Manba JONLI SO'ROVMI (hujjatlar ro'yxatiga emas, "tizimdan" qatoriga tushadimi).
 * Jonli platforma - doim; bilim platformasi - faqat `[n]` raqamisiz kelsa.
 */
export function isLookupSource(source: AnswerSource): boolean {
  const kind = String(source.kind ?? '').toLowerCase()
  if (LIVE_PLATFORMS.has(kind)) return true
  if (KNOWLEDGE_PLATFORMS.has(kind)) return source.citation_index == null
  return false
}

/** Bilim platformasidan (`[n]` raqami bilan) kelgan iqtibos - qo'llanma maqolasi. */
export function isGuideSource(source: AnswerSource): boolean {
  return KNOWLEDGE_PLATFORMS.has(String(source.kind ?? '').toLowerCase()) && source.citation_index != null
}

/**
 * Login kerak bo'lgan platforma (HRM/CRM) YOQIQ, lekin Barno undan foydalana olmaydi:
 *   `missing`    - hisob ulanmagan yoki muddati tugagan (token yo'q);
 *   `offForChat` - hisob ulangan, lekin bizning "Chatda ishlatish" kaliti (`/api/v1/connectors`,
 *                  `enabled`) o'chiq - chatga token yuborilmaydi.
 * NEGA IKKINCHISI ALOHIDA: platforma kaliti (yordamchida) va token kaliti (bizda) - ikki xil
 * joyda. Avval token kalitini o'chirgan odamga "Manbalar" HRM ni YOQIQ ko'rsatardi, Barno esa
 * HRM ga kira olmasdi - ogohlantirishsiz. Web ham, Mini App ham shu bitta qoidani ishlatadi.
 */
export type LoginIssue = 'missing' | 'offForChat' | null

export function loginIssue(
  platform: Pick<Platform, 'id' | 'needs_login' | 'enabled'>,
  connector: Pick<ConnectorStatus, 'configured' | 'state' | 'enabled'> | null | undefined,
): LoginIssue {
  if (!platform.needs_login || !platform.enabled || !connector || !connector.configured) return null
  if (connector.state !== 'connected') return 'missing'
  return connector.enabled ? null : 'offForChat'
}

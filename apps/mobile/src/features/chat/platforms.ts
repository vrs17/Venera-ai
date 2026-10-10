/**
 * Barno o'qiydigan PLATFORMALAR - chat manbalari va Sozlamalar > Ulanishlar > "Manbalar"
 * uchun BITTA ro'yxat: belgi, nom, bir qatorlik vazifa, manba turi bo'yicha qaror va
 * jonli so'rovning odamga ko'rinadigan nomi. Web `components/chat/platforms.ts`,
 * `components/chat/sources.ts` (`lookupTitle`) va `i18n/tools.ts` bilan BIR XIL qoida -
 * bir javob telefonda, web'da va Mini App'da bir xil nomlansin.
 *
 * 2026-10-10 (yordamchi 3.3): HRM va CRM ga DWH, Biznes 24/7, Superapp, Biznes 24/7
 * qo'llanmalari va Biznes Help qo'shildi. Yangi platforma - shu yerga bitta yozuv +
 * `i18n/parts/settings.ts` da `set.platform.<id>.name/purpose` (uz/ru/en).
 *
 * NEGA ID BO'YICHA O'Z TARJIMAMIZ: xizmat `name`/`description` ni faqat o'zbekcha beradi,
 * ilova esa 3 tilda. Bizga notanish platforma - xizmatning o'z matni bilan, bo'sh qolmaydi.
 */
import {
  BookOpenText,
  BriefcaseBusiness,
  Database,
  LifeBuoy,
  Plug,
  Smartphone,
  SquareKanban,
  Users,
  type LucideIcon,
} from 'lucide-react-native';

import type { Platform } from '@/api/assistant';
import type { AnswerSource, ConnectorStatus } from '@/api/chat';
import type { TFn, TKey } from '@/i18n';
import { uz } from '@/i18n/uz';

/** Ma'lum platformalar - sozlamalardagi tartib ham shu. */
export const PLATFORM_IDS = ['hrm', 'crm', 'dwh', 'biznes247', 'superapp', 'biznes247_kb', 'biznes247_help'] as const;
export type PlatformId = (typeof PLATFORM_IDS)[number];

const KNOWN = new Set<string>(PLATFORM_IDS);

export function isPlatformId(value: unknown): value is PlatformId {
  return typeof value === 'string' && KNOWN.has(value);
}

/**
 * JONLI so'rov (`[T1]`) bo'ladigan turlar - hujjat emas, ochiladigan fayli yo'q.
 * Qo'llanmalar BILIM manbai: `[n]` raqami bilan kelsa - iqtibos (havolasi bo'lsa tashqi
 * sahifa), raqamsiz kelsa - so'rov sifatida ko'rsatiladi (`isLookupSource`).
 */
export const LIVE_PLATFORMS: ReadonlySet<string> = new Set(['hrm', 'crm', 'dwh', 'biznes247', 'superapp']);
export const KNOWLEDGE_PLATFORMS: ReadonlySet<string> = new Set(['biznes247_kb', 'biznes247_help']);

/**
 * Belgilar (web bilan bir xil): HRM - odamlar, CRM - kanban, DWH - ma'lumotlar ombori,
 * Biznes 24/7 - biznes portfeli, Superapp - telefon, qo'llanmalar - kitob, Help - qutqaruv
 * halqasi. Notanish platforma - vilka (ulanish).
 */
const ICONS: Record<PlatformId, LucideIcon> = {
  hrm: Users,
  crm: SquareKanban,
  dwh: Database,
  biznes247: BriefcaseBusiness,
  superapp: Smartphone,
  biznes247_kb: BookOpenText,
  biznes247_help: LifeBuoy,
};

const norm = (id: string | null | undefined) => String(id ?? '').trim().toLowerCase();

export function platformIcon(id: string | null | undefined): LucideIcon {
  const key = norm(id);
  return isPlatformId(key) ? ICONS[key] : Plug;
}

/** "Biznes 24/7 qo'llanmalari" - tarjimadan; notanishi - xizmat nomi yoki id (katta harf). */
export function platformName(id: string | null | undefined, t: TFn, fallback?: string | null): string {
  const key = norm(id);
  if (isPlatformId(key)) return t(`set.platform.${key}.name` as TKey);
  return fallback?.trim() || key.toUpperCase();
}

/** Bir qator: Barno undan nima oladi. Notanishi - xizmatning `description` i. */
export function platformPurpose(id: string | null | undefined, t: TFn, fallback?: string | null): string {
  const key = norm(id);
  if (isPlatformId(key)) return t(`set.platform.${key}.purpose` as TKey);
  return fallback?.trim() ?? '';
}

/** Asbob nomidan platforma: `biznes247_kb_search` -> `biznes247_kb` (eng uzun mos prefiks). */
function platformFromTool(tool: string | null | undefined): PlatformId | null {
  const name = norm(tool);
  if (!name) return null;
  let best: PlatformId | null = null;
  for (const id of PLATFORM_IDS) {
    if ((name === id || name.startsWith(`${id}_`)) && (!best || id.length > best.length)) best = id;
  }
  return best;
}

/** Manba qaysi platformadan: avval `kind`, bo'lmasa asbob nomining prefiksi. */
export function platformOfSource(source: AnswerSource): PlatformId | null {
  const kind = norm(source.kind);
  if (isPlatformId(kind)) return kind;
  return platformFromTool(source.tool);
}

/** Jonli so'rovmi: jonli platforma - doim; bilim platformasi - faqat `[n]` raqamisiz kelsa. */
export function isLookupSource(source: AnswerSource): boolean {
  const kind = norm(source.kind);
  if (LIVE_PLATFORMS.has(kind)) return true;
  if (KNOWLEDGE_PLATFORMS.has(kind)) return source.citation_index == null;
  return false;
}

/** Bilim platformasidan `[n]` raqami bilan kelgan iqtibos - qo'llanma maqolasi. */
export function isGuideSource(source: AnswerSource): boolean {
  return KNOWLEDGE_PLATFORMS.has(norm(source.kind)) && source.citation_index != null;
}

/** Asbob nomining tarjima kaliti (`set.tool.*`) - tarjimasi yo'q bo'lsa `null`. */
export function toolKey(tool: string | null | undefined): TKey | null {
  const name = norm(tool);
  if (!name) return null;
  const key = `set.tool.${name}`;
  return key in uz ? (key as TKey) : null;
}

/**
 * FOYDALANUVCHIGA ko'rinadigan so'rov nomi (web `lookupTitle` bilan bitta qoida):
 *   * asbob nomining tarjimasi bor - "CRM · Vazifa ma'lumoti";
 *   * yo'q - faqat platforma nomi ("DWH", "Biznes 24/7"); nima topilgani ostida (`digest`);
 *   * qo'llanmadan raqamsiz so'rov - maqola nomi bilan ("Biznes 24/7 qo'llanmalari · Karta ochish").
 * Xom asbob nomi ("Branch kpi") HECH QACHON - u dasturchi tili. Platforma ham noma'lum
 * bo'lsa - `kind` katta harfda.
 */
export function lookupTitle(source: AnswerSource, t: TFn): string {
  const platform = platformOfSource(source);
  const name = platform ? platformName(platform, t) : String(source.kind ?? '').trim().toUpperCase() || 'HRM';
  const key = toolKey(source.tool);
  if (key) return `${name} · ${t(key)}`;
  const title = platform && KNOWLEDGE_PLATFORMS.has(platform) ? source.title?.trim() : '';
  return title ? `${name} · ${title}` : name;
}

/**
 * Login kerak bo'lgan platforma (HRM/CRM) YOQIQ, lekin Barno undan foydalana olmaydi:
 *   `missing`    - hisob ulanmagan yoki muddati tugagan (token yo'q);
 *   `offForChat` - hisob ulangan, lekin bizning "Chatda ishlatish" kaliti (`/api/v1/connectors`,
 *                  `enabled`) o'chiq - chatga token yuborilmaydi.
 * NEGA ALOHIDA: platforma kaliti (yordamchida) va token kaliti (bizda) ikki xil joyda. Avval
 * token kalitini o'chirgan odamga "Manbalar" HRM ni YOQIQ ko'rsatardi, Barno esa HRM ga kira
 * olmasdi - ogohlantirishsiz. Web, Mini App va telefon shu bitta qoidani ishlatadi.
 */
export type LoginIssue = 'missing' | 'offForChat' | null;

export function loginIssue(
  platform: Pick<Platform, 'id' | 'needs_login' | 'enabled'>,
  connector: Pick<ConnectorStatus, 'configured' | 'state' | 'enabled'> | null | undefined,
): LoginIssue {
  if (!platform.needs_login || !platform.enabled || !connector || !connector.configured) return null;
  if (connector.state !== 'connected') return 'missing';
  return connector.enabled ? null : 'offForChat';
}

/** Sozlamalardagi tartib - `PLATFORM_IDS`; notanishi oxirida, server tartibida. */
export function orderPlatforms<T extends { id: string }>(list: readonly T[]): T[] {
  const rank = (id: string) => {
    const i = (PLATFORM_IDS as readonly string[]).indexOf(id);
    return i < 0 ? PLATFORM_IDS.length : i;
  };
  return list
    .map((p, i) => ({ p, i }))
    .sort((a, b) => rank(a.p.id) - rank(b.p.id) || a.i - b.i)
    .map((x) => x.p);
}

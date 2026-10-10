/**
 * Javob manbalari -> manbalar oynasi va "N manba" tugmasi uchun tur, belgi, nom va izoh.
 * Web/Mini App `tg/chat/sources.ts` bilan bir xil qoida:
 *
 *   doc     hujjat `[1]` - bosilsa imzolangan havola (PDF);
 *   law     qonun moddasi (`kind: "law"`, LEX.UZ) - faqat `https://` havola ochiladi;
 *   guide   qo'llanma (`biznes247_kb`, `biznes247_help`) `[n]` raqami bilan - maqola, havolasi bo'lsa;
 *   lookup  jonli so'rov (HRM, CRM, DWH, Biznes 24/7, Superapp; qo'llanmadan raqamsiz) - fayli yo'q.
 *
 * NOMLAR XODIM TILIDA: "T1" va "CRM · Issue get" odamga hech narsa demaydi - so'rov nomi
 * `lookupTitle` dan ("CRM · Vazifa ma'lumoti"), belgi esa platformaniki (HRM odamlar, DWH ombor).
 */
import { BookOpen, BookOpenText, Database, Landmark, type LucideIcon } from 'lucide-react-native';

import type { AnswerSource } from '@/api/chat';
import type { TFn } from '@/i18n';

import { isGuideSource, isLookupSource, lookupTitle, platformIcon, platformName, platformOfSource } from './platforms';

export type SourceKind = 'doc' | 'law' | 'guide' | 'lookup';

export function sourceKind(src: AnswerSource): SourceKind {
  if (String(src.kind ?? '').trim().toLowerCase() === 'law') return 'law';
  if (isGuideSource(src)) return 'guide';
  // Eski qoida ham qoladi: notanish turdagi `tool`/`marker` li manba - jonli so'rov (ochiladigan
  // fayli yo'q), aks holda mavjud bo'lmagan hujjat "ochiladigan" bo'lib chiqardi.
  if (isLookupSource(src) || src.tool || src.marker) return 'lookup';
  return 'doc';
}

/** Belgi va uning kaliti (tugmadagi belgilar bir xil platforma uchun takrorlanmasin). */
export function sourceMark(src: AnswerSource): { key: string; Icon: LucideIcon } {
  const kind = sourceKind(src);
  if (kind === 'law') return { key: 'law', Icon: Landmark };
  if (kind === 'doc') return { key: 'doc', Icon: BookOpen };
  const platform = platformOfSource(src);
  if (platform) return { key: platform, Icon: platformIcon(platform) };
  return kind === 'guide' ? { key: 'guide', Icon: BookOpenText } : { key: 'data', Icon: Database };
}

/** "N manba" tugmasidagi belgilar: tartib bo'yicha, takrorsiz, ko'pi bilan `max` ta. */
export function sourceMarks(sources: readonly AnswerSource[], max = 3): { key: string; Icon: LucideIcon }[] {
  const out: { key: string; Icon: LucideIcon }[] = [];
  for (const src of sources) {
    const mark = sourceMark(src);
    if (!out.some((m) => m.key === mark.key)) out.push(mark);
    if (out.length >= max) break;
  }
  return out;
}

/** Ro'yxatdagi nom: so'rov - "CRM · Vazifa ma'lumoti"; qo'llanma va hujjat - o'z sarlavhasi. */
export function sourceTitle(src: AnswerSource, t: TFn): string {
  const kind = sourceKind(src);
  if (kind === 'lookup') return lookupTitle(src, t);
  if (kind === 'guide') return src.title?.trim() || platformName(platformOfSource(src), t);
  // Qonun moddasi sarlavhasiz kelsa - manzili (web `lawTitle` kabi).
  if (kind === 'law') return src.title?.trim() || safeHttps(src.url) || t('chat.sourceLaw');
  return src.title?.trim() || src.doc_id || '-';
}

/** Bir qator izoh: qo'llanma - platforma nomi; qonun - "Qonunchilik"; hujjat - bo'lim/bet. */
export function sourceMeta(src: AnswerSource, t: TFn): string {
  const kind = sourceKind(src);
  if (kind === 'lookup') {
    // Platforma nomi sarlavhada bor; notanish turda "Tizim ma'lumoti" - bu fayl emasligini aytadi.
    return platformOfSource(src) ? '' : t('chat.sourceData');
  }
  if (kind === 'guide') return platformName(platformOfSource(src), t);
  return [kind === 'law' ? t('chat.sourceLaw') : null, src.section, src.page ? t('chat.sourcePage', { n: src.page }) : null]
    .filter(Boolean)
    .join(' · ');
}

/** Tashqi havola faqat `https://` - `javascript:`/`http` havola bo'lmaydi (web `safeHttps`). */
export function safeHttps(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const value = raw.trim();
  return /^https:\/\/[^\s/]+/i.test(value) ? value : null;
}

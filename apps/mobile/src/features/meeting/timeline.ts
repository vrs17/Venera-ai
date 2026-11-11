/**
 * Yozuvlar ro'yxati = bitta vaqt chizig'i (spec 3.1): serverdagi kartalar va
 * telefonda turgan (hali yuklanmagan) yozuvlar BIRGA, eng yangisi tepada,
 * Toshkent kuni bo'yicha guruhlangan ("Bugun", "Kecha", "8-oktabr").
 *
 * NIMA UCHUN birlashtiriladi: eskisida lokal yozuvlar alohida blokda tepada
 * turardi - foydalanuvchi bitta yig'ilishni ikki joyda ko'rardi va qaysi biri
 * eshitiladigan ekanini tushunmasdi. Endi bitta yozuv = bitta karta: server
 * kartasi yutadi va telefondagi qatorni (`local`) o'zi bilan olib yuradi -
 * pill yuklash holatini ko'rsatadi.
 *
 * QAYSI VAQT (2026-11-11, ega talabi): ilovada yozilgan yozuv - YOZILGAN vaqti bilan, tayyor fayl
 * ("Audio yuklash", "Ulashish", qo'ng'iroq, Slack, Telegram) - Barno'ga KELGAN vaqti bilan. 8-noyabrdagi
 * fayl bugun yuklansa - u bugungi ish: "Bugun" ostida, eng tepada; 8-noyabr ostiga tushib yo'qolmaydi.
 * Server ham shu tartibda beradi (`sort=listed`, `listedAt`) - sahifalar orasida sakrash bo'lmaydi.
 */
import type { EntrySource, Lang, MeetingCard, MeetingOrigin } from '@/api/types';
import type { QueueRow } from '@/features/upload/queueStore';

import { formatDay, tashkentDayKey } from './formatDate';
import { normalizeForSearch } from './groupBubbles';

export type TimelineItem =
  | { kind: 'server'; key: string; at: string; card: MeetingCard; local: QueueRow | null }
  | { kind: 'local'; key: string; at: string; row: QueueRow };

export interface TimelineSection {
  /** `YYYY-MM-DD` (Toshkent). */
  key: string;
  data: TimelineItem[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

function time(iso: string): number {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : 0;
}

/** Tayyor fayl (telefondan yuborilgan, server ham `share` deb biladi): ro'yxatda KELGAN vaqti bilan turadi. */
export function isFileSource(source: EntrySource | undefined): boolean {
  return source === 'share' || source === 'call';
}

/** Telefondagi qatorning manbasi - server `ORIGIN_SQL` bilan bir xil qoida (`mobile` kanali). */
export function rowOrigin(row: Pick<QueueRow, 'source'>): MeetingOrigin {
  return isFileSource(row.source) ? 'upload' : 'recording';
}

/** Telefondagi qatorning ro'yxatdagi vaqti: tayyor fayl - navbatga qo'shilgan, yozuv - boshlangan. */
export function rowListedAt(row: Pick<QueueRow, 'source' | 'startedAt' | 'queuedAt'>): string {
  return isFileSource(row.source) && row.queuedAt ? row.queuedAt : row.startedAt;
}

/** Server kartasining ro'yxatdagi vaqti (eski server `listedAt` bermaydi - unda `recordedAt`). */
export function cardListedAt(card: Pick<MeetingCard, 'listedAt' | 'recordedAt'>): string {
  return card.listedAt || card.recordedAt;
}

/**
 * Server kartalari + navbat qatorlari -> bitta ro'yxat (yangisi birinchi, `cardListedAt`/`rowListedAt` bo'yicha).
 *
 * - `done` qatorlar ko'rsatilmaydi (server kartasi bor).
 * - clientId bo'yicha takror yo'q: server kartasi yutadi va qatorni `local` sifatida oladi
 *   (yuklanmagan yoki yiqilgan bo'lsa ham - kartaning pill'i shuni aytadi).
 * - `hideClientId`: hozir yozilayotgan qator - u tepadagi jonli kartada, ro'yxatda takrorlanmaydi.
 * - `origin`: Plaud filtri. Server kartalarni o'zi filtrlaydi (`?origin=`); bu yerda telefondagi qatorlar
 *   va filtr almashgan lahzada ko'rinib turgan eski sahifa (boshqa manbaniki) olib tashlanadi.
 */
export function mergeTimeline(
  cards: MeetingCard[],
  rows: QueueRow[],
  opts: { hideClientId?: string | null; origin?: MeetingOrigin | null } = {},
): TimelineItem[] {
  const pending = rows.filter((r) => r.state !== 'done' && r.clientId !== opts.hideClientId);
  const byClient = new Map(pending.map((r) => [r.clientId, r]));
  const seen = new Set<string>();
  const items: TimelineItem[] = [];
  for (const card of cards) {
    if (seen.has(card.id)) continue; // sahifalar orasida siljish (yangi yozuv qo'shildi) - takror bo'lmasin
    seen.add(card.id);
    if (opts.origin && card.origin && card.origin !== opts.origin) continue;
    items.push({ kind: 'server', key: `s-${card.id}`, at: cardListedAt(card), card, local: byClient.get(card.clientId) ?? null });
  }
  const serverClientIds = new Set(cards.map((c) => c.clientId));
  for (const row of pending) {
    if (serverClientIds.has(row.clientId)) continue;
    if (opts.origin && rowOrigin(row) !== opts.origin) continue;
    items.push({ kind: 'local', key: `l-${row.clientId}`, at: rowListedAt(row), row });
  }
  return items.sort((a, b) => time(b.at) - time(a.at));
}

/** Kunlarga bo'lish (kirish allaqachon tartiblangan bo'lishi kerak - `mergeTimeline`). */
export function groupByDay(items: TimelineItem[]): TimelineSection[] {
  const sections: TimelineSection[] = [];
  for (const item of items) {
    const key = tashkentDayKey(item.at) || 'unknown';
    const last = sections[sections.length - 1];
    if (last && last.key === key) last.data.push(item);
    else sections.push({ key, data: [item] });
  }
  return sections;
}

/** Lokal qator sarlavhasi bo'yicha qidiruv (server o'zi `q` bilan qidiradi). */
export function matchesQuery(title: string, query: string): boolean {
  const q = normalizeForSearch(query);
  if (!q) return true;
  return normalizeForSearch(title).includes(q);
}

export type DayLabel = { kind: 'today' } | { kind: 'yesterday' } | { kind: 'date'; text: string };

/** Bo'lim sarlavhasi: bugun / kecha / sana (joriy yil bo'lmasa yil bilan). */
export function dayLabel(key: string, now: number, lang: Lang): DayLabel {
  if (key === tashkentDayKey(now)) return { kind: 'today' };
  if (key === tashkentDayKey(now - DAY_MS)) return { kind: 'yesterday' };
  const year = tashkentDayKey(now).slice(0, 4);
  return { kind: 'date', text: formatDay(key, lang, { withYear: !key.startsWith(year) }) };
}

/**
 * Yozuvlar ro'yxati = bitta vaqt chizig'i (spec 3.1): serverdagi kartalar va
 * telefonda turgan (hali yuklanmagan) yozuvlar BIRGA, eng yangisi tepada,
 * Toshkent kuni bo'yicha guruhlangan ("Bugun", "Kecha", "8-oktyabr").
 *
 * NIMA UCHUN birlashtiriladi: eskisida lokal yozuvlar alohida blokda tepada
 * turardi - foydalanuvchi bitta yig'ilishni ikki joyda ko'rardi va qaysi biri
 * eshitiladigan ekanini tushunmasdi. Endi bitta yozuv = bitta karta: server
 * kartasi yutadi va telefondagi qatorni (`local`) o'zi bilan olib yuradi -
 * pill yuklash holatini ko'rsatadi.
 */
import type { Lang, MeetingCard } from '@/api/types';
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

/**
 * Server kartalari + navbat qatorlari -> bitta ro'yxat (yangisi birinchi).
 *
 * - `done` qatorlar ko'rsatilmaydi (server kartasi bor).
 * - clientId bo'yicha takror yo'q: server kartasi yutadi va qatorni `local` sifatida oladi
 *   (yuklanmagan yoki yiqilgan bo'lsa ham - kartaning pill'i shuni aytadi).
 * - `hideClientId`: hozir yozilayotgan qator - u tepadagi jonli kartada, ro'yxatda takrorlanmaydi.
 */
export function mergeTimeline(cards: MeetingCard[], rows: QueueRow[], opts: { hideClientId?: string | null } = {}): TimelineItem[] {
  const pending = rows.filter((r) => r.state !== 'done' && r.clientId !== opts.hideClientId);
  const byClient = new Map(pending.map((r) => [r.clientId, r]));
  const seen = new Set<string>();
  const items: TimelineItem[] = [];
  for (const card of cards) {
    if (seen.has(card.id)) continue; // sahifalar orasida siljish (yangi yozuv qo'shildi) - takror bo'lmasin
    seen.add(card.id);
    items.push({ kind: 'server', key: `s-${card.id}`, at: card.recordedAt, card, local: byClient.get(card.clientId) ?? null });
  }
  const serverClientIds = new Set(cards.map((c) => c.clientId));
  for (const row of pending) {
    if (serverClientIds.has(row.clientId)) continue;
    items.push({ kind: 'local', key: `l-${row.clientId}`, at: row.startedAt, row });
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

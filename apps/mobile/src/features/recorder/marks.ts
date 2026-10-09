/**
 * "Muhim" belgilari (spec 2.3): `{t, note}`; t - yozuv vaqt chizig'ida
 * (pauza vaqti KIRMAYDI), izoh 200 belgigacha, jami 200 tagacha.
 * `/complete` bilan yuboriladi va xulosa shu joylarni albatta qamraydi.
 */
import type { Mark } from '@/api/types';

export const MAX_MARKS = 200;
export const MAX_NOTE_CHARS = 200;

export function normalizeNote(note: string | null | undefined): string | null {
  const s = (note ?? '').replace(/\s+/g, ' ').trim();
  if (!s) return null;
  return Array.from(s).slice(0, MAX_NOTE_CHARS).join('');
}

/** Yangi ro'yxat (o'zgarmas). Limitga yetgan bo'lsa - o'sha ro'yxat qaytadi. */
export function addMark(marks: Mark[], tSec: number, note?: string | null): Mark[] {
  if (marks.length >= MAX_MARKS) return marks;
  const t = Math.max(0, Math.round(tSec * 100) / 100);
  return [...marks, { t, note: normalizeNote(note) }];
}

/** Oxirgi belgiga izoh qo'shish (tugma bosilgandan keyin yozilgan izoh). */
export function setLastNote(marks: Mark[], note: string | null): Mark[] {
  if (!marks.length) return marks;
  const copy = marks.slice();
  copy[copy.length - 1] = { ...copy[copy.length - 1], note: normalizeNote(note) };
  return copy;
}

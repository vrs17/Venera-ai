/**
 * Transkriptni chat ko'rinishiga keltirish (spec 3.2 #12, 7.4): ketma-ket
 * bir spikerning segmentlari BITTA pufakchaga yig'iladi.
 *
 * Juda uzun monolog (ma'ruza) bitta ulkan pufakcha bo'lib qolmasin -
 * `maxChars` dan oshsa yangi pufakcha boshlanadi. Spikersiz (router) rejimda
 * hamma segment `speaker=null` - xuddi shu qoida bilan bo'linadi.
 */
import type { Segment, Speaker } from '@/api/types';

import { resolveSpeakerId, speakerNumber } from './renderTokens';

export interface Bubble {
  key: string;
  speaker: string | null;
  start: number;
  end: number;
  segmentIds: number[];
  segments: Segment[];
  text: string;
  edited: boolean;
}

export interface GroupOptions {
  speakers?: Speaker[];
  maxChars?: number;
}

export function groupBubbles(segments: Segment[], opts: GroupOptions = {}): Bubble[] {
  const speakers = opts.speakers ?? [];
  const maxChars = opts.maxChars ?? 1200;
  const sorted = [...segments].sort((a, b) => a.start - b.start || a.id - b.id);
  const out: Bubble[] = [];
  let cur: Bubble | null = null;

  for (const seg of sorted) {
    const speaker = seg.speaker ? resolveSpeakerId(seg.speaker, speakers) : null;
    const text = seg.text.trim();
    if (!text) continue;
    if (cur && cur.speaker === speaker && cur.text.length + 1 + text.length <= maxChars) {
      cur.segments.push(seg);
      cur.segmentIds.push(seg.id);
      cur.text = `${cur.text} ${text}`;
      cur.end = Math.max(cur.end, seg.end);
      cur.edited = cur.edited || seg.edited;
      continue;
    }
    cur = {
      key: `b${seg.id}`,
      speaker,
      start: seg.start,
      end: seg.end,
      segmentIds: [seg.id],
      segments: [seg],
      text,
      edited: seg.edited,
    };
    out.push(cur);
  }
  return out;
}

/** `t` vaqtni o'z ichiga olgan (yoki undan oldingi oxirgi) pufakcha indeksi. */
export function bubbleIndexAt(bubbles: Bubble[], t: number): number {
  let idx = -1;
  for (let i = 0; i < bubbles.length; i++) {
    if (bubbles[i].start <= t + 0.01) idx = i;
    else break;
  }
  return Math.max(0, idx);
}

/** Segment id -> pufakcha indeksi (dalil chipi bosilganda). */
export function bubbleIndexOfSegment(bubbles: Bubble[], segmentId: number): number {
  return bubbles.findIndex((b) => b.segmentIds.includes(segmentId));
}

/** Qidiruv: katta-kichik harf va apostrof turlariga befarq. */
export function normalizeForSearch(s: string): string {
  return s.toLowerCase().replace(/[ʻʼ’‘`´']/g, "'").replace(/\s+/g, ' ').trim();
}

export function searchBubbles(bubbles: Bubble[], query: string): number[] {
  const q = normalizeForSearch(query);
  if (!q) return [];
  const out: number[] = [];
  bubbles.forEach((b, i) => {
    if (normalizeForSearch(b.text).includes(q)) out.push(i);
  });
  return out;
}

/** Spiker rangi: S1..S8 barqaror, null - kulrang. */
export const SPEAKER_COLORS = ['#2563EB', '#D97706', '#059669', '#9333EA', '#DC2626', '#0891B2', '#65A30D', '#DB2777'];
export const NULL_SPEAKER_COLOR = '#6B7280';

export function speakerColor(id: string | null): string {
  const n = speakerNumber(id);
  if (n == null) return NULL_SPEAKER_COLOR;
  return SPEAKER_COLORS[(n - 1) % SPEAKER_COLORS.length];
}

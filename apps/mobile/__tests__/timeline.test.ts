/**
 * Yozuvlar vaqt chizig'i (spec 3.1): server + telefon birlashadi, clientId bo'yicha
 * takror yo'q, Toshkent kuni bo'yicha guruhlanadi, sarlavha "Bugun/Kecha/sana".
 */
import type { MeetingCard } from '@/api/types';
import { formatDay, formatTime, tashkentDayKey } from '@/features/meeting/formatDate';
import { dayLabel, groupByDay, matchesQuery, mergeTimeline } from '@/features/meeting/timeline';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';

import { card as baseCard } from './fixtures/server';

const card = (over: Partial<MeetingCard>): MeetingCard => ({ ...baseCard, status: 'ready', progress: null, ...over });
const row = (over: Partial<QueueRow> & { clientId: string; startedAt: string }): QueueRow =>
  newQueueRow({ fileUri: `file:///doc/recordings/${over.clientId}.aac`, language: 'uz', template: 'auto', expectedSpeakers: null, source: 'app', state: 'stopped', ...over });

describe('formatTime / tashkentDayKey', () => {
  it('uses Tashkent time (UTC+5), across midnight', () => {
    expect(formatTime('2026-10-10T09:05:00Z', 'uz')).toBe('14:05');
    expect(tashkentDayKey('2026-10-10T09:05:00Z')).toBe('2026-10-10');
    // 20:30 UTC = ertasi kuni 01:30 Toshkentda.
    expect(formatTime('2026-10-09T20:30:00Z')).toBe('01:30');
    expect(tashkentDayKey('2026-10-09T20:30:00Z')).toBe('2026-10-10');
    expect(tashkentDayKey('garbage')).toBe('');
    expect(formatTime('garbage')).toBe('');
  });

  it('formatDay can add the year', () => {
    expect(formatDay('2025-12-31', 'uz', { withYear: true })).toBe('2025-yil 31-dekabr');
    expect(formatDay('2025-12-31', 'ru', { withYear: true })).toBe('31 декабря 2025');
    expect(formatDay('2025-12-31', 'en', { withYear: true })).toBe('December 31, 2025');
  });
});

describe('mergeTimeline', () => {
  const A = card({ id: 'A', clientId: 'cA', recordedAt: '2026-10-10T06:00:00Z', title: 'Server A' });
  const B = card({ id: 'B', clientId: 'cB', recordedAt: '2026-10-09T06:00:00Z', title: 'Server B', status: 'uploading' });

  it('merges server cards and local rows, newest first', () => {
    const local = row({ clientId: 'cL', startedAt: '2026-10-10T09:00:00Z' });
    const items = mergeTimeline([A, B], [local]);
    expect(items.map((i) => i.key)).toEqual(['l-cL', 's-A', 's-B']);
  });

  it('dedupes by clientId: the server card wins and carries the unfinished local row', () => {
    const uploading = row({ clientId: 'cB', startedAt: '2026-10-09T06:00:00Z', state: 'uploading', serverId: 'B' });
    const items = mergeTimeline([A, B], [uploading]);
    expect(items).toHaveLength(2);
    const b = items.find((i) => i.key === 's-B');
    expect(b).toMatchObject({ kind: 'server', local: { clientId: 'cB', state: 'uploading' } });
    expect(items.find((i) => i.key === 's-A')).toMatchObject({ local: null });
  });

  it('a failed row with a server card is shown once (on the card), not twice', () => {
    const failed = row({ clientId: 'cB', startedAt: '2026-10-09T06:00:00Z', state: 'failed', lastError: 'too_large', serverId: 'B' });
    const items = mergeTimeline([B], [failed]);
    expect(items.map((i) => i.key)).toEqual(['s-B']);
    expect(items[0]).toMatchObject({ local: { state: 'failed' } });
  });

  it('hides done rows, the live recording row and repeated server cards across pages', () => {
    const done = row({ clientId: 'cD', startedAt: '2026-10-10T07:00:00Z', state: 'done', serverId: 'D' });
    const live = row({ clientId: 'cR', startedAt: '2026-10-10T10:00:00Z', state: 'recording' });
    const items = mergeTimeline([A, A], [done, live], { hideClientId: 'cR' });
    expect(items.map((i) => i.key)).toEqual(['s-A']);
    // Boshqa (eski, tiklanmagan) yozilayotgan qator yashirilmaydi.
    expect(mergeTimeline([], [live]).map((i) => i.key)).toEqual(['l-cR']);
  });
});

describe('groupByDay / dayLabel', () => {
  it('groups by the Tashkent day, not the UTC day', () => {
    const late = row({ clientId: 'late', startedAt: '2026-10-09T20:30:00Z' }); // 10-oktyabr 01:30 Toshkent
    const morning = card({ id: 'M', clientId: 'cM', recordedAt: '2026-10-10T04:00:00Z' }); // 10-oktyabr 09:00
    const prev = card({ id: 'P', clientId: 'cP', recordedAt: '2026-10-09T18:00:00Z' }); // 9-oktyabr 23:00
    const sections = groupByDay(mergeTimeline([morning, prev], [late]));
    expect(sections.map((s) => [s.key, s.data.map((d) => d.key)])).toEqual([
      ['2026-10-10', ['s-M', 'l-late']],
      ['2026-10-09', ['s-P']],
    ]);
  });

  it('labels today / yesterday / dates (with the year only when it differs)', () => {
    const now = Date.parse('2026-10-10T08:00:00Z');
    expect(dayLabel('2026-10-10', now, 'uz')).toEqual({ kind: 'today' });
    expect(dayLabel('2026-10-09', now, 'uz')).toEqual({ kind: 'yesterday' });
    expect(dayLabel('2026-10-01', now, 'uz')).toEqual({ kind: 'date', text: '1-oktabr' });
    expect(dayLabel('2025-12-31', now, 'en')).toEqual({ kind: 'date', text: 'December 31, 2025' });
    // Toshkentda yarim tundan keyin "bugun" ham almashadi (UTC hali kechagi kun).
    expect(dayLabel('2026-10-11', Date.parse('2026-10-10T19:30:00Z'), 'uz')).toEqual({ kind: 'today' });
  });

  it('matches local titles case- and apostrophe-insensitively', () => {
    expect(matchesQuery("Yozuv, 14:05 - Ko'rik", 'KO’RIK')).toBe(true);
    expect(matchesQuery('Narxlar', 'hisobot')).toBe(false);
    expect(matchesQuery('Narxlar', '  ')).toBe(true);
  });
});

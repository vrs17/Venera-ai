/**
 * Yozuvlar vaqt chizig'i (spec 3.1): server + telefon birlashadi, clientId bo'yicha
 * takror yo'q, Toshkent kuni bo'yicha guruhlanadi, sarlavha "Bugun/Kecha/sana".
 */
import type { MeetingCard } from '@/api/types';
import { formatDay, formatTime, tashkentDayKey } from '@/features/meeting/formatDate';
import { cardListedAt, dayLabel, groupByDay, matchesQuery, mergeTimeline, rowListedAt, rowOrigin } from '@/features/meeting/timeline';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';

import { card as baseCard } from './fixtures/server';

// Ilovada yozilgan karta: server `listedAt` = `recordedAt` beradi (boshqasi berilmasa).
const card = (over: Partial<MeetingCard>): MeetingCard => ({
  ...baseCard,
  status: 'ready',
  progress: null,
  ...over,
  listedAt: over.listedAt ?? over.recordedAt ?? baseCard.listedAt,
});
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

describe('qaysi vaqt va manba filtri (ega talabi 2026-11-11)', () => {
  const keys = (items: { key: string }[]) => items.map((i) => i.key);

  it('8-noyabrdagi fayl bugun yuklansa - "Bugun" ostida va eng tepada (listedAt), yozilgan kuniga emas', () => {
    const recording = card({ id: 'R', clientId: 'cR', recordedAt: '2026-11-11T04:00:00Z' }); // bugun 09:00
    const uploaded = card({
      id: 'U',
      clientId: 'cU',
      source: 'share',
      origin: 'upload',
      title: "Qo'ng'iroq, 13:46",
      recordedAt: '2026-11-08T08:46:00Z',
      listedAt: '2026-11-11T05:22:00Z', // bugun 10:22 yuklangan
    });
    const items = mergeTimeline([recording, uploaded], []);
    expect(keys(items)).toEqual(['s-U', 's-R']);
    expect(groupByDay(items).map((s) => s.key)).toEqual(['2026-11-11']);
    expect(formatTime(items[0].at)).toBe('10:22');
  });

  it("telefondagi tayyor fayl - navbatga qo'shilgan vaqti; yozuv va 1.3.8 dan oldingi qator - startedAt", () => {
    const imported = row({ clientId: 'cI', source: 'share', startedAt: '2026-11-08T08:46:00Z', queuedAt: '2026-11-11T05:22:00Z' });
    const oldCall = row({ clientId: 'cC', source: 'call', startedAt: '2026-11-01T08:00:00Z' }); // queuedAt yo'q
    const recording = row({ clientId: 'cR', source: 'app', startedAt: '2026-11-11T04:00:00Z', queuedAt: '2026-11-11T09:00:00Z' });
    expect(rowListedAt(imported)).toBe('2026-11-11T05:22:00Z');
    expect(rowListedAt(oldCall)).toBe('2026-11-01T08:00:00Z');
    expect(rowListedAt(recording)).toBe('2026-11-11T04:00:00Z');
    expect(keys(mergeTimeline([], [oldCall, recording, imported]))).toEqual(['l-cI', 'l-cR', 'l-cC']);
  });

  it('eski server listedAt bermasa - recordedAt', () => {
    expect(cardListedAt({ recordedAt: '2026-10-10T06:00:00Z' })).toBe('2026-10-10T06:00:00Z');
    expect(cardListedAt({ recordedAt: '2026-10-10T06:00:00Z', listedAt: '2026-11-11T05:00:00Z' })).toBe('2026-11-11T05:00:00Z');
  });

  it('telefondagi qator manbasi server qoidasi bilan bir xil: tayyor fayl - upload, qolgani - recording', () => {
    expect(rowOrigin({ source: 'share' })).toBe('upload');
    expect(rowOrigin({ source: 'call' })).toBe('upload');
    for (const source of ['app', 'tile', 'launcher', 'volume', 'shortcut', 'notification', 'link'] as const) {
      expect(rowOrigin({ source })).toBe('recording');
    }
  });

  it("filtr: telefondagi qatorlar o'z manbasi bilan; filtr almashgan lahzadagi boshqa manba kartasi chiqmaydi", () => {
    const slack = card({ id: 'S', clientId: 'cS', origin: 'slack', recordedAt: '2026-11-11T06:00:00Z' });
    const upload = card({ id: 'U', clientId: 'cU', origin: 'upload', recordedAt: '2026-11-11T05:00:00Z' });
    // Eski server `origin` bermaydi - u filtrni o'zi qo'llagan deb hisoblanadi.
    const legacy = card({ id: 'L', clientId: 'cL', origin: undefined, recordedAt: '2026-11-11T04:00:00Z' });
    const rec = row({ clientId: 'r1', source: 'app', startedAt: '2026-11-11T03:00:00Z' });
    const file = row({ clientId: 'f1', source: 'share', startedAt: '2026-11-11T02:00:00Z' });
    expect(keys(mergeTimeline([slack, upload, legacy], [rec, file], { origin: 'upload' }))).toEqual(['s-U', 's-L', 'l-f1']);
    expect(keys(mergeTimeline([slack], [rec, file], { origin: 'recording' }))).toEqual(['l-r1']);
    expect(keys(mergeTimeline([slack], [rec, file], { origin: 'slack' }))).toEqual(['s-S']);
    expect(keys(mergeTimeline([slack, upload], [rec, file], { origin: null }))).toEqual(['s-S', 's-U', 'l-r1', 'l-f1']);
  });
});

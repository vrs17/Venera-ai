import { formatClock, formatDateTime, formatDay, formatDue, tashkentParts } from '@/features/meeting/formatDate';
import { bubbleIndexAt, bubbleIndexOfSegment, groupBubbles, normalizeForSearch, searchBubbles, speakerColor } from '@/features/meeting/groupBubbles';
import { isProcessing, pollInterval } from '@/features/meeting/queries';
import { renderTokens, resolveSpeakerId, speakerLabel, visibleSpeakers } from '@/features/meeting/renderTokens';
import type { Segment, Speaker } from '@/api/types';

import { meeting, speakers, transcript } from './fixtures/server';

describe('renderTokens', () => {
  it('replaces [S#] with names, follows mergedInto, falls back per language', () => {
    expect(renderTokens('[S1] va [S2] gaplashdi, [S3] rozi.', speakers, 'uz')).toBe('Aziz va 2-ishtirokchi gaplashdi, Aziz rozi.');
    expect(renderTokens('[S2]', speakers, 'ru')).toBe('Участник 2');
    expect(renderTokens('[S2]', speakers, 'en')).toBe('Speaker 2');
    expect(renderTokens('[S7] keldi', [], 'uz')).toBe('7-ishtirokchi keldi');
    expect(renderTokens(null, speakers, 'uz')).toBe('');
    expect(renderTokens('[X1] [s1]', speakers, 'uz')).toBe('[X1] [s1]');
  });

  it('survives merge cycles and hides merged speakers', () => {
    const cyc: Speaker[] = [
      { id: 'S1', name: null, suggestedName: null, talkSec: 1, mergedInto: 'S2' },
      { id: 'S2', name: null, suggestedName: null, talkSec: 1, mergedInto: 'S1' },
    ];
    expect(['S1', 'S2']).toContain(resolveSpeakerId('S1', cyc));
    expect(visibleSpeakers(speakers).map((s) => s.id)).toEqual(['S1', 'S2']);
    expect(speakerLabel(null, speakers, 'uz')).toBe("Noma'lum");
  });
});

describe('groupBubbles', () => {
  it('groups consecutive same-speaker segments (merged speakers included) into one bubble', () => {
    const b = groupBubbles(transcript.segments, { speakers });
    // S1, S1 -> bitta; S2 -> bitta; S3 (S1 ga birlashtirilgan) -> S1 pufakchasi.
    expect(b.map((x) => [x.speaker, x.segmentIds])).toEqual([
      ['S1', [1, 2]],
      ['S2', [3]],
      ['S1', [4]],
    ]);
    expect(b[0]).toMatchObject({ start: 0, end: 9, text: "Assalomu alaykum, boshlaymiz. Bugun narxlarni ko'ramiz.", edited: false });
    expect(b[2].edited).toBe(true);
  });

  it('sorts by start, drops empty text and splits very long monologues', () => {
    const segs: Segment[] = [
      { id: 3, speaker: null, start: 20, end: 25, text: 'c'.repeat(30), edited: false },
      { id: 1, speaker: null, start: 0, end: 5, text: 'a'.repeat(30), edited: false },
      { id: 2, speaker: null, start: 10, end: 15, text: '   ', edited: false },
      { id: 4, speaker: null, start: 30, end: 35, text: 'd'.repeat(30), edited: false },
    ];
    const b = groupBubbles(segs, { maxChars: 62 });
    expect(b.map((x) => x.segmentIds)).toEqual([[1, 3], [4]]);
    expect(b.every((x) => x.speaker === null)).toBe(true);
  });

  it('finds bubbles by time, segment and search (apostrophe-insensitive)', () => {
    const b = groupBubbles(transcript.segments, { speakers });
    expect(bubbleIndexAt(b, 0)).toBe(0);
    expect(bubbleIndexAt(b, 12)).toBe(1);
    expect(bubbleIndexAt(b, 999)).toBe(2);
    expect(bubbleIndexOfSegment(b, 4)).toBe(2);
    expect(searchBubbles(b, "KO’RAMIZ")).toEqual([0]);
    expect(searchBubbles(b, '  ')).toEqual([]);
    expect(normalizeForSearch("Xo‘p  Ko`p")).toBe("xo'p ko'p");
  });

  it('assigns stable colours per speaker and grey for unknown', () => {
    expect(speakerColor('S1')).not.toBe(speakerColor('S2'));
    expect(speakerColor('S1')).toBe(speakerColor('S1'));
    expect(speakerColor(null)).toBe('#6B7280');
  });
});

describe('formatDate', () => {
  it('formats in Asia/Tashkent regardless of device zone', () => {
    // 11:00 UTC = 16:00 Toshkent.
    expect(formatDateTime('2026-10-10T11:00:00Z', 'uz')).toBe('10-oktabr, 16:00');
    expect(formatDateTime('2026-10-10T11:00:00Z', 'ru')).toBe('10 октября, 16:00');
    expect(formatDateTime('2026-10-10T11:00:00Z', 'en')).toBe('October 10, 16:00');
    // Yarim tundan keyin kun almashadi.
    expect(formatDateTime('2026-10-09T20:30:00Z', 'uz')).toBe('10-oktabr, 01:30');
    expect(formatDateTime('2026-01-05T04:00:00Z', 'ru', { withYear: true })).toBe('5 января 2026, 09:00');
    expect(tashkentParts('garbage')).toBeNull();
    expect(formatDateTime('garbage', 'uz')).toBe('');
  });

  it('formats days, due dates and clocks', () => {
    expect(formatDay('2026-12-31', 'uz')).toBe('31-dekabr');
    expect(formatDay('2026-12-31', 'en')).toBe('December 31');
    expect(formatDay('bad', 'uz')).toBe('bad');
    expect(formatDue('2026-10-10', '15:00', 'ertaga', 'uz')).toBe('10-oktabr, 15:00');
    expect(formatDue(null, null, 'tez orada', 'uz')).toBe('tez orada');
    expect(formatDue(null, null, null, 'uz')).toBeNull();
    expect(formatClock(754.2)).toBe('12:34');
    expect(formatClock(65)).toBe('01:05');
    expect(formatClock(3725.9)).toBe('1:02:05');
    expect(formatClock(null)).toBe('--:--');
  });
});

describe('polling interval (spec 3.2 #7)', () => {
  it('follows pollAfterSec and stops when ready/failed', () => {
    expect(pollInterval(meeting({ status: 'transcribing', pollAfterSec: 3 }))).toBe(3000);
    expect(pollInterval(meeting({ status: 'summarizing', pollAfterSec: 5 }))).toBe(5000);
    expect(pollInterval(meeting({ status: 'waiting_quota', pollAfterSec: 600 }))).toBe(600_000);
    expect(pollInterval(meeting({ status: 'ready', pollAfterSec: null, summaryStatus: 'ready' }))).toBe(false);
    expect(pollInterval(meeting({ status: 'failed', pollAfterSec: null }))).toBe(false);
    expect(pollInterval(meeting({ status: 'uploading', pollAfterSec: null }))).toBe(10_000);
    expect(pollInterval(undefined)).toBe(false);
    expect(isProcessing(meeting({ status: 'ready', summaryStatus: 'running' }))).toBe(true);
    expect(isProcessing(meeting({ status: 'ready', summaryStatus: 'ready' }))).toBe(false);
  });
});

describe('error texts and sharing limits', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { errorText, shareableText, MAX_SHARE_CHARS } = require('@/ui/errors') as typeof import('@/ui/errors');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { ApiError } = require('@/api/client') as typeof import('@/api/client');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { makeT } = require('@/i18n') as typeof import('@/i18n');

  it('maps queue codes and ApiError codes through i18n, never showing a bare known code', () => {
    expect(errorText(makeT('ru'), 'network')).toBe(makeT('ru')('err.network'));
    expect(errorText(makeT('en'), 'too_long')).toBe('The recording is too long');
    expect(errorText(makeT('uz'), new ApiError(409, 'not_retryable', 'x'))).toBe(makeT('uz')('err.not_retryable'));
    expect(errorText(makeT('en'), new ApiError(418, 'teapot', 'x'))).toBe(`${makeT('en')('common.error')} (teapot)`);
    expect(errorText(makeT('uz'), new Error('boom'))).toBe(makeT('uz')('common.error'));
  });

  it('caps text handed to Share/Clipboard below the Android binder limit', () => {
    const t = makeT('uz');
    expect(shareableText('abc', t)).toEqual({ text: 'abc', truncated: false });
    const long = shareableText('x'.repeat(MAX_SHARE_CHARS + 10), t);
    expect(long.truncated).toBe(true);
    expect(long.text.length).toBeLessThan(MAX_SHARE_CHARS + 200);
    expect(long.text.endsWith(t('err.share_truncated'))).toBe(true);
  });
});

describe('my action items grouping', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { groupByMeeting } = require('@/app/action-items') as typeof import('@/app/action-items');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { actionItem } = require('./fixtures/server') as typeof import('./fixtures/server');

  it('sorts newest meeting first and survives a null recordedAt (backend MyActionItem.recordedAt is optional)', () => {
    const items = [
      { ...actionItem, id: 'a', meetingId: 'm1', meetingTitle: 'Old', recordedAt: '2026-10-01T06:00:00Z' },
      { ...actionItem, id: 'b', meetingId: 'm2', meetingTitle: 'No date', recordedAt: null },
      { ...actionItem, id: 'c', meetingId: 'm3', meetingTitle: 'New', recordedAt: '2026-10-09T06:00:00Z' },
    ];
    expect(groupByMeeting(items).map((g) => g.title)).toEqual(['New', 'Old', 'No date']);
  });
});

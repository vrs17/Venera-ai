/**
 * "Qisqa xulosa" - mobil ilova va server AYNAN bir xil matn bersin (2026-10-10 sharhi).
 *
 * Namuna `packages/fixtures/meeting-brief.json` da; server tomonda xuddi shu fayl
 * `apps/api/tests/test_meetings_brief_golden.py` da tekshiriladi. NEGA umumiy fayl: ilovadagi
 * "Nusxa olish"/"Ulashish" matni va yuklab olingan fayl ikki xil kodda yig'iladi - biri
 * o'zgarib, ikkinchisi qolib ketsa, shu test ikkala tomonda ham yiqiladi.
 */
import { readFileSync } from 'fs';
import { resolve } from 'path';

import type { ActionItem, Speaker, SummaryContent } from '@/api/types';
import { briefToMarkdown, briefToText, buildBrief, type BriefMeeting } from '@/features/meeting/brief';

interface GoldenCase {
  name: string;
  meeting: BriefMeeting;
  speakers: { id: string; name: string | null; mergedInto: string | null }[];
  content: unknown;
  liveActions?: { task: string; owner: ActionItem['owner']; due: ActionItem['due']; status: ActionItem['status']; needsConfirmation: boolean }[];
  expectedText: string;
  expectedMarkdown?: string;
}

const GOLDEN = resolve(__dirname, '../../../packages/fixtures/meeting-brief.json');
const cases = (JSON.parse(readFileSync(GOLDEN, 'utf8')) as { cases: GoldenCase[] }).cases;

const speakersOf = (c: GoldenCase): Speaker[] => c.speakers.map((s) => ({ ...s, suggestedName: null, talkSec: 0 }));

const liveOf = (c: GoldenCase): ActionItem[] | null =>
  c.liveActions
    ? c.liveActions.map((a, i) => ({
        id: `L${i + 1}`,
        meetingId: 'm',
        summaryItemId: null,
        task: a.task,
        owner: a.owner,
        due: a.due,
        priority: null,
        status: a.status,
        origin: 'ai',
        edited: false,
        needsConfirmation: a.needsConfirmation,
        sourceSegmentIds: [],
        start: null,
        quote: null,
        createdAt: '2026-10-10T00:00:00Z',
        updatedAt: '2026-10-10T00:00:00Z',
        crm: null,
      }))
    : null;

describe('short summary golden fixture (shared with the server export)', () => {
  it('has cases', () => expect(cases.length).toBeGreaterThanOrEqual(3));

  it.each(cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    const brief = buildBrief(c.content as SummaryContent, c.meeting, speakersOf(c), { actions: liveOf(c) });
    expect(brief).not.toBeNull();
    expect(briefToText(brief!)).toBe(c.expectedText);
    if (c.expectedMarkdown) expect(briefToMarkdown(brief!)).toBe(c.expectedMarkdown);
  });
});

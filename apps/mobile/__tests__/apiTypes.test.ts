/**
 * Server JSON namunalari `src/api/types.ts` ga mos (fixtures/server.ts dagi
 * `satisfies` tsc'da tekshiradi). Bu yerda esa spec 3.1 maydon to'plamlari
 * aynan bir xil ekanini runtime'da qayd etamiz - kimdir types.ts ga maydon
 * qo'shib, serverni unutsa, shu test eslatadi.
 */
import { actionItem, askAnswer, card, config, crmProposal, crmState, meeting, speakers, summary, summaryCard, transcript } from './fixtures/server';

const keys = (o: object) => Object.keys(o).sort();

describe('API contract field sets (spec 3.1)', () => {
  it('Meeting', () => {
    expect(keys(meeting())).toEqual(
      [
        'id', 'clientId', 'title', 'titleSource', 'status', 'progress', 'pollAfterSec', 'language', 'detectedLanguage',
        'languageWarning', 'template', 'expectedSpeakers', 'source', 'recordedAt', 'durationSec', 'createdAt', 'updatedAt',
        'upload', 'transcript', 'speakers', 'summaryStatus', 'primarySummaryId', 'openActionItems', 'audioAvailable', 'error',
      ].sort(),
    );
    expect(keys(meeting().upload)).toEqual(['complete', 'maxChunkBytes', 'receivedBytes', 'totalBytes']);
    expect(keys(meeting().transcript)).toEqual(['available', 'engine', 'segmentCount', 'speakersAvailable', 'timing', 'transcriptRev']);
  });

  it('MeetingCard, Speaker, Segment, SummaryCard, ActionItem, Ask, config', () => {
    expect(keys(card)).toEqual(
      ['id', 'clientId', 'title', 'status', 'progress', 'recordedAt', 'durationSec', 'language', 'template', 'summaryStatus', 'openActionItems', 'overview', 'error'].sort(),
    );
    expect(keys(speakers[0])).toEqual(['id', 'mergedInto', 'name', 'suggestedName', 'talkSec']);
    expect(keys(transcript.segments[0])).toEqual(['edited', 'end', 'id', 'speaker', 'start', 'text']);
    expect(keys(summaryCard)).toEqual(['createdAt', 'error', 'finishedAt', 'id', 'language', 'primary', 'stale', 'status', 'template', 'transcriptRev']);
    expect(keys(summary())).toEqual([...keys(summaryCard), 'content', 'generatedBy', 'layout', 'model', 'promptVersion', 'speakers'].sort());
    expect(keys(actionItem)).toEqual(
      ['id', 'meetingId', 'summaryItemId', 'task', 'owner', 'due', 'priority', 'status', 'origin', 'edited', 'needsConfirmation', 'sourceSegmentIds', 'start', 'quote', 'createdAt', 'updatedAt', 'crm'].sort(),
    );
    expect(keys(askAnswer)).toEqual(['answer', 'citations', 'createdAt', 'followUps', 'id', 'question']);
    expect(config.recording.format).toBe('aac_adts');
  });

  it('CRM: ActionCrm and the proposal card fields (backend ActionCrm, crm.PROPOSAL_KEYS)', () => {
    expect(keys(crmState())).toEqual(['expiresAt', 'proposal', 'result', 'status', 'token', 'updatedAt']);
    expect(keys(crmProposal())).toEqual(['changes', 'connector', 'expires_at', 'operation', 'summary', 'target', 'token', 'warnings']);
    expect(keys(summary().generatedBy!)).toEqual(['model', 'provider']);
  });

  it('SummaryContent has every section of spec 6.2', () => {
    expect(keys(summary().content!)).toEqual(
      [
        'schemaVersion', 'template', 'language', 'meeting', 'title', 'meetingType', 'overview', 'purpose', 'participants', 'topics',
        'keyPoints', 'decisions', 'actionItems', 'openQuestions', 'risks', 'numbers', 'dates', 'nextSteps', 'nextMeeting',
        'highlights', 'userMarks', 'keywords', 'sentiment', 'templateSections', 'followUpMessage', 'quality',
      ].sort(),
    );
  });
});

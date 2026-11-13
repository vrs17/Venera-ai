/**
 * Server JSON namunalari `src/api/types.ts` ga mos (fixtures/server.ts dagi
 * `satisfies` tsc'da tekshiradi). Bu yerda esa spec 3.1 maydon to'plamlari
 * aynan bir xil ekanini runtime'da qayd etamiz - kimdir types.ts ga maydon
 * qo'shib, serverni unutsa, shu test eslatadi.
 */
import {
  actionItem,
  askAnswer,
  card,
  chatBackend,
  chatMinutes,
  chatTurn,
  config,
  crmProposal,
  crmState,
  meeting,
  minutesChanges,
  minutesHeader,
  minutesView,
  revisionId,
  speakers,
  summary,
  summaryCard,
  transcript,
} from './fixtures/server';

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
      [
        'id', 'clientId', 'title', 'status', 'progress', 'recordedAt', 'durationSec', 'language', 'template', 'summaryStatus',
        'openActionItems', 'overview', 'error', 'source', 'origin', 'listedAt',
      ].sort(),
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

  it('Yozuv chati: ChatTurn = AskAnswer + channel + model + clientId + kind + minutes; GET {items, model}; DELETE {archived}', () => {
    expect(keys(chatTurn())).toEqual([...keys(askAnswer), 'channel', 'clientId', 'kind', 'minutes', 'model'].sort());
    const chat = chatBackend();
    expect(keys(chat.history('x'))).toEqual(['items', 'model']);
    expect(keys(chat.send('x', { message: 'q', channel: 'mobile' }))).toEqual(keys(chatTurn()));
    expect(keys(chat.send('x', { message: 'q', channel: 'mobile', clientId: 'k'.repeat(16) }))).toEqual(keys(chatTurn()));
    expect(keys(chat.reset('x'))).toEqual(['archived']);
  });

  it('Yozuv chati: soxta server ham `clientId` bo\'yicha takrorni qaytaradi (R3-1) - faqat shu yozuvning FAOL qatorlari ichida', () => {
    const chat = chatBackend();
    const first = chat.send('A', { message: 'Narx qancha?', channel: 'mobile', clientId: 'kalit-1-000000000000' });
    expect(first.clientId).toBe('kalit-1-000000000000');
    // O'sha kalit - o'sha savol-javob (matn boshqacha bo'lsa ham), yangi qator yo'q.
    expect(chat.send('A', { message: 'Narx qancha?!', channel: 'mobile', clientId: 'kalit-1-000000000000' })).toBe(first);
    expect(chat.history('A').items).toHaveLength(1);
    // Boshqa kalit, kalitsiz (bot) yoki boshqa yozuv - alohida savol-javob.
    expect(chat.send('A', { message: 'Narx qancha?', channel: 'mobile', clientId: 'kalit-2-000000000000' }).id).not.toBe(first.id);
    expect(chat.send('A', { message: 'Narx qancha?', channel: 'mobile' }).clientId).toBeNull();
    expect(chat.send('B', { message: 'Narx qancha?', channel: 'mobile', clientId: 'kalit-1-000000000000' }).id).not.toBe(first.id);
    expect(chat.history('A').items).toHaveLength(3);
    // Arxivlangan ("Yangi suhbat") qator takrorni to'xtatmaydi.
    chat.reset('A');
    const again = chat.send('A', { message: 'Narx qancha?', channel: 'mobile', clientId: 'kalit-1-000000000000' });
    expect(again.id).not.toBe(first.id);
    expect(chat.history('A').items.map((x) => x.id)).toEqual([again.id]);
  });

  it('Bayonnoma: MinutesView field set (server `minutes.view`, chatdagi tahrir maydonlari bilan)', () => {
    expect(keys(minutesView())).toEqual(
      [
        'id', 'meetingId', 'language', 'status', 'createdAt', 'finishedAt', 'provider', 'model', 'transcriptRev', 'stale',
        'agendaCount', 'sectionCount', 'itemCount', 'notes', 'warnings', 'error',
        'kind', 'version', 'parentId', 'request', 'notesApplied', 'pendingNotes', 'header', 'changes',
      ].sort(),
    );
    expect(keys(minutesHeader())).toEqual(['attendees', 'chair', 'chairedBy', 'city', 'organization']);
    expect(keys(minutesChanges())).toEqual(['agenda', 'header', 'items', 'other']);
    expect(keys(minutesChanges().items)).toEqual(['added', 'changed', 'removed']);
  });

  it('Bayonnoma chatda: ChatMinutes field set; soxta server aniq niyatni server kabi qaytaradi (modelsiz, manbasiz)', () => {
    expect(keys(chatMinutes())).toEqual(['action', 'error', 'id', 'language', 'notes', 'status', 'version']);
    const chat = chatBackend();
    const plain = chat.send('x', { message: 'Narx qancha?', channel: 'mobile' });
    expect([plain.kind, plain.minutes]).toEqual(['chat', null]);
    const note = chat.send('x', { message: 'Rais - A.Karimov', channel: 'mobile', intent: 'note' });
    expect(note).toMatchObject({ kind: 'note', citations: [], followUps: [], minutes: { action: 'note', id: null, notes: 1, error: null } });
    expect(chat.send('x', { message: 'Kredit qismiga e\'tibor', channel: 'mobile', intent: 'note' }).minutes?.notes).toBe(2);
    const edit = chat.send('x', { message: '3-bandda muddat 1-dekabr', channel: 'mobile', intent: 'revise', minutesLanguage: 'ru' });
    expect(edit).toMatchObject({ kind: 'revise', minutes: { action: 'revise', language: 'ru', id: revisionId(4), status: 'running', version: 2 } });
    expect(keys(edit)).toEqual(keys(chatTurn()));
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

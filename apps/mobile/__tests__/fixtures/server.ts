/**
 * Server JSON namunalari - spec 3.1/3.2/6.2 dagi misollardan. `satisfies`
 * maydon nomi yoki turi `src/api/types.ts` dan farq qilsa tsc'da yiqiladi.
 */
import type {
  ActionCrm,
  ActionItem,
  ActionProposal,
  AskAnswer,
  ChatHistory,
  ChatRequest,
  ChatReset,
  ChatTurn,
  GlobalActionItem,
  LoginResponse,
  Meeting,
  MeetingCard,
  MeetingList,
  MeetingsConfig,
  MinutesView,
  RegisterDeviceResponse,
  Speaker,
  Summary,
  SummaryCard,
  Transcript,
  UploadPosition,
} from '@/api/types';

export const speakers = [
  { id: 'S1', name: 'Aziz', suggestedName: null, talkSec: 600.5, mergedInto: null },
  { id: 'S2', name: null, suggestedName: 'Dilnoza', talkSec: 420, mergedInto: null },
  { id: 'S3', name: null, suggestedName: null, talkSec: 30, mergedInto: 'S1' },
] satisfies Speaker[];

export const config = {
  enabled: true,
  maxMinutes: 180,
  maxUploadBytes: 157286400,
  maxChunkBytes: 4194304,
  acceptedContentTypes: ['audio/aac', 'audio/mp4'],
  languages: ['uz', 'ru', 'en'],
  defaultLanguage: 'uz',
  maxDistinctSpeakers: 4,
  userDailyMinutes: 240,
  userTodayMinutes: 37.5,
  recording: { format: 'aac_adts', sampleRate: 16000, bitRate: 48000, channels: 1, audioSource: 'voice_recognition' },
  templates: [{ id: 'general', title: "Umumiy yig'ilish", description: '...', auto: true, extraTab: false }],
} satisfies MeetingsConfig;

export function meeting(over: Partial<Meeting> = {}): Meeting {
  return {
    id: 'a'.repeat(32),
    clientId: '6f1c2a3b-1111-4222-8333-444455556666',
    title: "Yig'ilish 9-oktyabr, 11:00",
    titleSource: 'auto',
    status: 'ready',
    progress: null,
    pollAfterSec: null,
    language: 'uz',
    detectedLanguage: { code: 'uz', share: { uz: 0.82, ru: 0.18 } },
    languageWarning: null,
    template: 'auto',
    expectedSpeakers: null,
    source: 'launcher',
    recordedAt: '2026-10-09T06:00:00Z',
    durationSec: 3600.4,
    createdAt: '2026-10-09T06:00:05Z',
    updatedAt: '2026-10-09T07:10:00Z',
    upload: { receivedBytes: 21600000, totalBytes: 21600000, maxChunkBytes: 4194304, complete: true },
    transcript: { available: true, engine: 'gapi', speakersAvailable: true, timing: 'exact', segmentCount: 4, transcriptRev: 1 },
    speakers,
    summaryStatus: 'ready',
    primarySummaryId: 'b'.repeat(32),
    openActionItems: 2,
    audioAvailable: true,
    error: null,
    ...over,
  } satisfies Meeting;
}

export const card = {
  id: 'a'.repeat(32),
  clientId: '6f1c2a3b-1111-4222-8333-444455556666',
  title: 'Narxlar',
  status: 'transcribing',
  progress: 42,
  recordedAt: '2026-10-09T06:00:00Z',
  durationSec: 3600.4,
  language: 'uz',
  template: 'auto',
  summaryStatus: 'none',
  openActionItems: 0,
  overview: null,
  error: null,
  source: 'launcher',
  origin: 'recording',
  listedAt: '2026-10-09T06:00:00Z',
} satisfies MeetingCard;

export const list = { items: [card], limit: 20, offset: 0, total: 57 } satisfies MeetingList;

export const uploadPosition = { receivedBytes: 8388608, maxChunkBytes: 4194304, complete: false } satisfies UploadPosition;

export const transcript = {
  meetingId: 'a'.repeat(32),
  transcriptRev: 1,
  engine: 'gapi',
  speakersAvailable: true,
  timing: 'exact',
  language: 'uz',
  detectedLanguage: { code: 'uz', share: { uz: 0.82, ru: 0.18 } },
  speakers,
  segments: [
    { id: 1, speaker: 'S1', start: 0, end: 4.2, text: 'Assalomu alaykum, boshlaymiz.', edited: false },
    { id: 2, speaker: 'S1', start: 4.3, end: 9, text: "Bugun narxlarni ko'ramiz.", edited: false },
    { id: 3, speaker: 'S2', start: 9.5, end: 15, text: 'Men ertaga hisobotni yuboraman.', edited: false },
    { id: 4, speaker: 'S3', start: 15.2, end: 18, text: 'Xo\'p, kelishdik.', edited: true },
  ],
} satisfies Transcript;

export const summaryCard = {
  id: 'b'.repeat(32),
  template: 'general',
  language: 'uz',
  status: 'ready',
  primary: true,
  stale: false,
  transcriptRev: 1,
  createdAt: '2026-10-09T07:00:00Z',
  finishedAt: '2026-10-09T07:01:00Z',
  error: null,
} satisfies SummaryCard;

const ev = (ids: number[], start: number | null) => ({ sourceSegmentIds: ids, start });

export function summary(over: Partial<Summary> = {}): Summary {
  return {
    ...summaryCard,
    promptVersion: 'meeting-1',
    model: 'gemma4:31b',
    generatedBy: { provider: 'ollama', model: 'gemma4:31b' },
    layout: [
      { key: 'title', title: 'Sarlavha' },
      { key: 'overview', title: 'Qisqacha' },
      { key: 'actionItems', title: 'Vazifalar' },
      { key: 'decisions', title: 'Qarorlar' },
      { key: 'topics', title: 'Mavzular' },
      { key: 'openQuestions', title: 'Ochiq savollar' },
      { key: 'risks', title: 'Xavflar' },
      { key: 'numbers', title: 'Raqamlar' },
      { key: 'dates', title: 'Sanalar' },
      { key: 'nextSteps', title: 'Keyingi qadamlar' },
      { key: 'nextMeeting', title: "Keyingi yig'ilish" },
      { key: 'highlights', title: 'Muhim lahzalar' },
      { key: 'participants', title: 'Ishtirokchilar' },
      { key: 'keyPoints', title: 'Asosiy fikrlar' },
      { key: 'keywords', title: "Kalit so'zlar" },
      { key: 'sentiment', title: 'Kayfiyat' },
      { key: 'objections', title: "E'tirozlar" },
      { key: 'quality', title: 'Sifat' },
    ],
    speakers,
    content: {
      schemaVersion: 'meeting-summary/1',
      template: 'general',
      language: 'uz',
      meeting: { date: '2026-10-09', weekday: 'juma', timezone: 'Asia/Tashkent', durationSec: 3600.4, speakerCount: 2 },
      title: 'Narxlar va hisobot',
      meetingType: { value: 'general', confidence: 0.8 },
      overview: "[S1] narxlarni ko'rib chiqdi. [S2] hisobot yuboradi. [S3] rozi bo'ldi.",
      purpose: "Narxlarni kelishish",
      participants: [
        { speaker: 'S1', suggestedName: null, nameEvidence: [], role: 'rahbar', talkSec: 600.5, talkShare: 0.58 },
        { speaker: 'S2', suggestedName: 'Dilnoza', nameEvidence: [3], role: null, talkSec: 420, talkShare: 0.42 },
      ],
      topics: [
        {
          id: 'T1',
          title: 'Narxlar',
          summary: "[S1] narxni so'radi",
          outcome: 'decided',
          startSegmentId: 1,
          endSegmentId: 4,
          start: 0,
          end: 18,
          keyPoints: [{ text: 'Narx 15 mln', ...ev([2], 4.3) }],
        },
      ],
      keyPoints: [{ id: 'K1', text: 'Narx kelishildi', ...ev([4], 15.2) }],
      decisions: [
        {
          id: 'D1',
          text: 'Narx 15 mln so\'m',
          status: 'final',
          condition: null,
          rationale: 'Bozor narxi',
          proposedBy: ['S1'],
          agreedBy: ['S2', 'S3'],
          topicId: 'T1',
          quote: 'kelishdik',
          needsConfirmation: false,
          verified: true,
          ...ev([4], 15.2),
        },
        {
          id: 'D2',
          text: 'Chegirma berilmaydi',
          status: 'tentative',
          condition: null,
          rationale: null,
          proposedBy: [],
          agreedBy: [],
          topicId: null,
          quote: 'balki',
          needsConfirmation: false,
          verified: false,
          ...ev([2], 4.3),
        },
      ],
      actionItems: [
        {
          id: 'A1',
          task: 'Hisobotni yuborish',
          deliverable: 'PDF hisobot',
          owner: { speaker: 'S2', name: null, kind: 'person', basis: 'self_commitment' },
          assignedBy: null,
          due: { raw: 'ertaga', date: '2026-10-10', time: null, basis: 'relative_resolved' },
          priority: 'high',
          status: 'open',
          origin: 'implicit_commitment',
          dependsOn: [],
          topicId: 'T1',
          quote: 'Men ertaga hisobotni yuboraman',
          confidence: 0.9,
          needsConfirmation: false,
          verified: true,
          ...ev([3], 9.5),
        },
        {
          id: 'A2',
          task: 'Shartnomani tekshirish',
          deliverable: null,
          owner: { speaker: null, name: null, kind: 'team', basis: 'unclear' },
          assignedBy: 'S1',
          due: { raw: 'tez orada', date: null, time: null, basis: 'vague' },
          priority: null,
          status: 'open',
          origin: 'explicit',
          dependsOn: ['A1'],
          topicId: null,
          quote: 'tekshirib ko\'ring',
          confidence: 0.5,
          needsConfirmation: true,
          verified: null,
          ...ev([2], 4.3),
        },
      ],
      openQuestions: [
        { id: 'Q1', text: 'Yetkazib berish qachon?', raisedBy: 'S3', directedTo: 'S2', whyOpen: 'no_answer', ...ev([4], 15.2) },
      ],
      risks: [
        { id: 'R1', text: 'Kurs oshishi', kind: 'risk', raisedBy: 'S1', severity: 'high', mitigation: 'Avans olish', ...ev([2], 4.3) },
      ],
      numbers: [{ id: 'N1', value: '15 mln', unit: "so'm", what: 'narx', ...ev([2], 4.3) }],
      dates: [{ id: 'E1', date: '2026-10-25', time: null, raw: '25-oktyabrgacha', what: 'muddat', ...ev([3], 9.5) }],
      nextSteps: [{ id: 'X1', text: '[S2] hisobot yuboradi', ...ev([3], 9.5) }],
      nextMeeting: { date: '2026-10-13', time: '10:00', raw: 'keyingi seshanba', agenda: ['Natijalar'], ...ev([4], 15.2) },
      highlights: [{ id: 'H1', quote: 'kelishdik', speaker: 'S3', segmentId: 4, start: 15.2, why: 'Qaror', fromMark: 'm1' }],
      userMarks: [{ id: 'm1', t: 16, note: 'narx', segmentIds: [4], coveredBy: ['H1'] }],
      keywords: ['narx', 'hisobot'],
      sentiment: { overall: 'positive', note: '[S1] mamnun', ...ev([], null) },
      templateSections: [{ key: 'objections', items: [{ text: 'Qimmat', speaker: 'S2', ...ev([3], 9.5) }] }],
      followUpMessage: null,
      quality: {
        warnings: [],
        droppedItems: 1,
        flaggedItems: 1,
        chunks: 1,
        coverageOk: true,
        speakersAvailable: true,
        languageWarning: null,
      },
    },
    ...over,
  } satisfies Summary;
}

export const actionItem = {
  id: 'c'.repeat(32),
  meetingId: 'a'.repeat(32),
  summaryItemId: 'A1',
  task: 'Hisobotni yuborish',
  owner: { speaker: 'S2', name: null, kind: 'person' },
  due: { date: '2026-10-10', time: null, raw: 'ertaga' },
  priority: 'high',
  status: 'open',
  origin: 'ai',
  edited: false,
  needsConfirmation: false,
  sourceSegmentIds: [3],
  start: 9.5,
  quote: 'Men ertaga hisobotni yuboraman',
  createdAt: '2026-10-09T07:01:00Z',
  updatedAt: '2026-10-09T07:01:00Z',
  crm: null,
} satisfies ActionItem;

/**
 * v3 taklifi (backend `crm.proposal_view` - web `ActionCard` maydonlari). `expiresInMs` -
 * hozirdan qancha keyin muddati tugaydi (manfiy - allaqachon o'tgan).
 */
export function crmProposal(over: Partial<ActionProposal> = {}, expiresInMs = 15 * 60_000): ActionProposal {
  return {
    token: 'tok-1',
    connector: 'crm',
    operation: 'crm_create_issue',
    summary: 'DVSIB loyihasida yangi vazifa: Hisobotni yuborish',
    target: { kind: 'new_issue', key: null },
    changes: [
      { field: 'title', to: 'Hisobotni yuborish' },
      { field: 'project', to: { key: 'DVSIB', name: 'Raqamli savdo' } },
      { field: 'assignee', to: { id: 42, name: 'Dilnoza Karimova' } },
      { field: 'due_date', from: null, to: '2026-10-10' },
      { field: 'priority', from: 'Normal', to: 'High' },
    ],
    warnings: ["Mas'ul ismi bo'yicha 2 ta odam topildi - Dilnoza Karimova tanlandi"],
    expires_at: new Date(Date.now() + expiresInMs).toISOString(),
    ...over,
  };
}

/** Vazifada saqlangan CRM holati (backend `ActionCrm`). */
export function crmState(over: Partial<ActionCrm> = {}, proposal: ActionProposal = crmProposal()): ActionCrm {
  return {
    token: proposal.token,
    status: 'pending',
    proposal,
    expiresAt: proposal.expires_at ?? null,
    result: null,
    updatedAt: '2026-10-09T07:10:00Z',
    ...over,
  };
}

export const globalItem = { ...actionItem, meetingTitle: 'Narxlar', recordedAt: '2026-10-09T06:00:00Z' } satisfies GlobalActionItem;

export const askAnswer = {
  id: 'd'.repeat(32),
  question: 'Kim hisobot yuboradi?',
  answer: '[S2] ertaga yuboradi.',
  citations: [{ segmentId: 3, start: 9.5, speaker: 'S2', text: 'Men ertaga hisobotni yuboraman.' }],
  followUps: ['Qachon?', 'Qaysi format?', 'Kimga?'],
  createdAt: '2026-10-09T07:05:00Z',
} satisfies AskAnswer;

/** Chatdagi savol-javob (backend `ChatTurn`): `AskAnswer` + kanal, javob bergan model va xabar kaliti. */
export function chatTurn(over: Partial<ChatTurn> = {}): ChatTurn {
  return { ...askAnswer, channel: 'mobile', model: 'claude-sonnet-5-5', clientId: null, ...over } satisfies ChatTurn;
}

/**
 * `/meetings/{id}/chat` GET/POST/DELETE - xotirada, backend qoidasi bilan: har yozuvning O'Z
 * suhbati (eskidan yangiga), POST savol-javobni oxiriga qo'shadi, DELETE ("Yangi suhbat") faol
 * qatorlarni arxivlaydi - ro'yxatdan chiqadi, lekin `archived` da qoladi (o'chirilmaydi).
 * Javob savoldan yasaladi: `[S2]` tokeni, bitta manba va aynan 3 ta keyingi savol.
 *
 * `clientId` (R3-1 idempotentlik): shu yozuvda shu kalitli FAOL savol-javob bo'lsa POST yangisini
 * yaratmaydi - o'shani qaytaradi. Arxivlangani hisobga olinmaydi, boshqa yozuvniki ham.
 */
export function chatBackend(seed: Record<string, ChatTurn[]> = {}) {
  const live = new Map<string, ChatTurn[]>(Object.entries(seed).map(([id, turns]) => [id, [...turns]]));
  const archived: ChatTurn[] = [];
  const model = 'claude-sonnet-5-5';
  let n = 0;
  return {
    archived,
    history(id: string): ChatHistory {
      return { items: [...(live.get(id) ?? [])], model };
    },
    send(id: string, body: ChatRequest): ChatTurn {
      const same = body.clientId ? (live.get(id) ?? []).find((x) => x.clientId === body.clientId) : undefined;
      if (same) return same;
      n += 1;
      const turn = chatTurn({
        id: `t${n}`.padEnd(32, '0'),
        question: body.message,
        answer: `[S2] javobi: ${body.message}`,
        citations: [{ segmentId: 3, start: 9.5, speaker: 'S2', text: 'Men ertaga hisobotni yuboraman.' }],
        followUps: [`Taklif ${n}a`, `Taklif ${n}b`, `Taklif ${n}c`],
        channel: body.channel ?? 'api',
        model,
        clientId: body.clientId ?? null,
        createdAt: `2026-10-09T08:${String(n).padStart(2, '0')}:00Z`,
      });
      live.set(id, [...(live.get(id) ?? []), turn]);
      return turn;
    },
    reset(id: string): ChatReset {
      const turns = live.get(id) ?? [];
      archived.push(...turns);
      live.set(id, []);
      return { archived: turns.length };
    },
  };
}

export const loginResponse = {
  token: 'jwt-1',
  tokenType: 'Bearer',
  expiresAt: '2026-10-09T18:00:00Z',
  passwordChangeRequired: false,
  user: {
    actorId: 7,
    actorType: 'EMPLOYEE',
    email: 'a@brb.uz',
    fullName: 'Aziz Karimov',
    position: null,
    department: null,
    roles: ['USER'],
    passwordChangeRequired: false,
  },
} satisfies LoginResponse;

export const deviceResponse = {
  deviceId: 'e'.repeat(32),
  deviceToken: 'x'.repeat(43),
  expiresAt: '2026-11-08T06:00:00Z',
} satisfies RegisterDeviceResponse;

/** Bayonnoma qatori (`GET /meetings/{id}/minutes`, server `minutes.view`) - tayyor, eskirmagan. */
export function minutesView(over: Partial<MinutesView> = {}): MinutesView {
  return {
    id: 'f'.repeat(32),
    meetingId: 'a'.repeat(32),
    language: 'uz-cyrl',
    status: 'ready',
    createdAt: '2026-11-06T06:00:00Z',
    finishedAt: '2026-11-06T06:01:30Z',
    provider: 'claude',
    model: 'claude-sonnet-5-5',
    transcriptRev: 1,
    stale: false,
    agendaCount: 2,
    sectionCount: 2,
    itemCount: 5,
    notes: ['Muddat aniq aytilmagan - 2-band'],
    warnings: [],
    error: null,
    ...over,
  } satisfies MinutesView;
}

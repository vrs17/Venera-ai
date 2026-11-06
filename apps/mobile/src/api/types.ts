/**
 * Server shartnomasi (spec 3.1, 3.2, 6.2) - AYNAN nusxa.
 *
 * NIMA UCHUN qo'lda: TypeScript serverdan kelgan JSON'ni tekshira olmaydi.
 * Maydon nomi farq qilsa ekran jimgina bo'sh qoladi. Shuning uchun bu fayl
 * spec bilan qatorma-qator mos va `__tests__/apiTypes.test.ts` server JSON
 * namunasini `satisfies` bilan tekshiradi.
 */

export type Lang = 'uz' | 'ru' | 'en';
export type TemplateId =
  | 'auto'
  | 'general'
  | 'minutes'
  | 'standup'
  | 'one_on_one'
  | 'project_review'
  | 'brainstorm'
  | 'sales_call'
  | 'interview'
  | 'lecture'
  | 'short_call'
  | 'follow_up';
export type MeetingStatus =
  | 'uploading'
  | 'uploaded'
  | 'transcribing'
  | 'summarizing'
  | 'ready'
  | 'failed'
  | 'waiting_quota';
export type SummaryStatus = 'none' | 'queued' | 'running' | 'ready' | 'failed' | 'skipped';
/**
 * Yozuv qayerdan kelgan. `call` - Samsung Telefon yozgan qo'ng'iroq (MediaStore), `share` -
 * "Ulashish -> Barno AI". Bular yozish kirish nuqtasi EMAS (deep link `src=` ularni qabul qilmaydi),
 * server esa `call` uchun qo'ng'iroq shablonlarini afzal ko'radi.
 */
export type EntrySource = 'app' | 'tile' | 'launcher' | 'volume' | 'shortcut' | 'notification' | 'link' | 'call' | 'share';

export interface Speaker {
  id: string; // 'S1'..'S4' (order of first appearance)
  name: string | null; // user-confirmed name
  suggestedName: string | null; // from the summary, never auto-applied
  talkSec: number;
  mergedInto: string | null; // set after a merge; clients hide merged speakers
}

export interface Segment {
  id: number; // 1..N, the grounding id
  speaker: string | null; // 'S1'.. or null (no diarization / router)
  start: number; // seconds
  end: number;
  text: string;
  edited: boolean;
}

export interface MeetingError {
  code: string;
  message: string;
  stage: string;
  retryable: boolean;
  retryAt: string | null;
}

export interface MeetingUpload {
  receivedBytes: number;
  totalBytes: number | null;
  maxChunkBytes: number;
  complete: boolean;
}

export interface MeetingTranscriptInfo {
  available: boolean;
  engine: 'gapi' | 'router' | null;
  speakersAvailable: boolean;
  timing: 'exact' | 'approximate' | null;
  segmentCount: number;
  transcriptRev: number;
}

export interface DetectedLanguage {
  code: string | null;
  share: Record<string, number>;
}

export interface Meeting {
  id: string;
  clientId: string;
  title: string;
  titleSource: 'auto' | 'user';
  status: MeetingStatus;
  progress: number | null;
  pollAfterSec: number | null;
  language: Lang;
  detectedLanguage: DetectedLanguage | null;
  languageWarning: 'mostly_other_language' | null;
  template: TemplateId;
  expectedSpeakers: number | null;
  source: EntrySource;
  recordedAt: string;
  durationSec: number | null;
  createdAt: string;
  updatedAt: string;
  upload: MeetingUpload;
  transcript: MeetingTranscriptInfo;
  speakers: Speaker[];
  summaryStatus: SummaryStatus;
  primarySummaryId: string | null;
  openActionItems: number;
  audioAvailable: boolean;
  error: MeetingError | null;
}

export interface MeetingCard {
  id: string;
  clientId: string;
  title: string;
  status: MeetingStatus;
  progress: number | null;
  recordedAt: string;
  durationSec: number | null;
  language: Lang;
  template: TemplateId;
  summaryStatus: SummaryStatus;
  openActionItems: number;
  overview: string | null; // <=200 chars
  error: MeetingError | null;
}

// ---------------------------------------------------------------- endpoint 1
export interface TemplateInfo {
  id: TemplateId;
  title: string;
  description: string;
  auto: boolean;
  extraTab: boolean;
}

export interface RecordingConfig {
  format: string; // 'aac_adts'
  sampleRate: number;
  bitRate: number;
  channels: number;
  audioSource: string; // 'voice_recognition' | 'mic' | 'camcorder' ...
}

export interface MeetingsConfig {
  enabled: boolean;
  maxMinutes: number;
  maxUploadBytes: number;
  maxChunkBytes: number;
  acceptedContentTypes: string[];
  languages: Lang[];
  defaultLanguage: Lang;
  maxDistinctSpeakers: number;
  userDailyMinutes: number;
  userTodayMinutes: number;
  recording: RecordingConfig;
  templates: TemplateInfo[];
}

// ---------------------------------------------------------------- endpoints 2-5
export type AudioContentType = 'audio/aac' | 'audio/mp4';

export interface CreateMeetingRequest {
  clientId: string;
  title: string | null;
  recordedAt: string;
  language: Lang;
  template: TemplateId;
  expectedSpeakers: number | null;
  contentType: AudioContentType;
  source: EntrySource;
  appVersion: string;
  device: string;
  /**
   * Faqat qo'ng'iroq yozuvi (`source: 'call'`): rozilik eslatmasi qabul qilingan vaqt (ISO) va
   * matn versiyasi. Server saqlaydi - qo'ng'iroq AI agentga faqat shu belgi bilan ketishi mumkin.
   */
  consentAt?: string;
  consentVersion?: string;
}

export interface UploadPosition {
  receivedBytes: number;
  maxChunkBytes: number;
  complete: boolean;
}

export interface ChunkResponse {
  receivedBytes: number;
}

export interface Mark {
  t: number; // seconds on the recording timeline (pause excluded)
  note: string | null;
}

export interface CompleteRequest {
  totalBytes: number;
  sha256: string;
  durationSec: number;
  endedAt: string;
  marks: Mark[];
}

// ---------------------------------------------------------------- endpoints 6-11
export interface MeetingList {
  items: MeetingCard[];
  limit: number;
  offset: number;
  total: number;
}

export interface MeetingListQuery {
  limit?: number;
  offset?: number;
  q?: string;
  status?: MeetingStatus | '';
}

export interface PatchMeetingRequest {
  title?: string;
  template?: TemplateId;
  expectedSpeakers?: number | null;
}

export interface DeletedResponse {
  id: string;
  status: 'deleted';
}

export interface RetranscribeRequest {
  language: Lang;
  expectedSpeakers?: number | null;
  confirmCharge: true;
}

// ---------------------------------------------------------------- endpoints 12-15
export interface Transcript {
  meetingId: string;
  transcriptRev: number;
  engine: 'gapi' | 'router' | null;
  speakersAvailable: boolean;
  timing: 'exact' | 'approximate' | null;
  language: Lang;
  detectedLanguage: DetectedLanguage | null;
  speakers: Speaker[];
  segments: Segment[];
}

export interface SpeakersResponse {
  speakers: Speaker[];
}

export interface MergeSpeakersRequest {
  from: string[];
  into: string;
}

export interface MergeSpeakersResponse {
  speakers: Speaker[];
  transcriptRev: number;
}

export interface PatchSegmentRequest {
  text?: string;
  speaker?: string | null;
}

export interface PatchSegmentResponse {
  segment: Segment;
  transcriptRev: number;
}

// ---------------------------------------------------------------- endpoints 16-21
export interface SummaryCard {
  id: string;
  template: TemplateId;
  language: Lang;
  status: SummaryStatus;
  primary: boolean;
  stale: boolean;
  transcriptRev: number;
  createdAt: string;
  finishedAt: string | null;
  error: { code: string; message: string } | null;
}

export interface SummaryLayoutEntry {
  key: string;
  title: string;
}

/** Xulosani yozgan model (`summary.generatedBy`): v3 - Barno Core, openai - GPT, claude - Claude, ollama - Gemma. */
export type SummaryProvider = 'v3' | 'openai' | 'claude' | 'ollama';

export interface GeneratedBy {
  provider: SummaryProvider;
  model: string | null;
}

export interface Summary extends SummaryCard {
  promptVersion: string;
  model: string;
  /** null - xulosa tayyor emas (yoki eski server). */
  generatedBy: GeneratedBy | null;
  layout: SummaryLayoutEntry[];
  speakers: Speaker[];
  content: SummaryContent | null;
}

export interface CreateSummaryRequest {
  template: TemplateId;
  language?: Lang;
  force?: boolean;
  makePrimary?: boolean;
}

export type SummaryExportFormat = 'md' | 'txt';
export type TranscriptExportFormat = 'txt' | 'srt';

// ---------------------------------------------------------------- 6.2 SummaryContent
export interface Ev {
  sourceSegmentIds: number[];
  start: number | null;
}

/** `alsoIn.section`: fakt yana qaysi bo'limda bor edi (server `compact.py`). */
export type AlsoInSection =
  | 'decisions'
  | 'openQuestions'
  | 'risks'
  | 'keyPoints'
  | 'nextSteps'
  | 'template'
  | 'topics'
  | 'highlights'
  | (string & {});

/**
 * Server bir xil faktlarni birlashtirgan (har fakt BIR marta, 2026-10-15): qolgan bandga -
 * fakt yana qayerda edi. `label` - XULOSA tilida tayyor chip matni ("Tanlangan", "Xavf");
 * `key` - shablon bo'limi kaliti (`section === 'template'` bo'lsa, masalan 'shortlist').
 * Eski xulosalarda yo'q.
 */
export interface AlsoIn {
  section: AlsoInSection;
  key?: string | null;
  label: string;
}

/** Birlashtirilgan bandlarda ixtiyoriy `alsoIn`. */
export interface Merged {
  alsoIn?: AlsoIn[] | null;
}

/**
 * "Hal qilinmagan masalalar" (server `summarize._follow_ups`, modelsiz): o'z bandiga havola
 * (`ref` - A1/D1/Q1/R1) va sabab kodlari. Vazifa, qaror va ochiq savolga havola qilganlari
 * serverda olib tashlanadi (ular "Qisqa xulosa" kartasida holati bilan bor).
 */
export type FollowUp = {
  id: string; // F1
  kind: 'openQuestion' | 'decision' | 'actionItem' | 'risk' | (string & {});
  ref: string;
  text: string;
  reasons: string[];
} & Ev;

export interface SummaryParticipant {
  speaker: string;
  suggestedName: string | null;
  nameEvidence: number[];
  role: string | null;
  talkSec: number;
  talkShare: number;
}

export type TopicOutcome = 'decided' | 'open' | 'info';

export interface SummaryTopic {
  id: string; // T1
  title: string;
  summary: string;
  outcome: TopicOutcome;
  startSegmentId: number;
  endSegmentId: number;
  start: number;
  end: number;
  keyPoints: ({ text: string } & Ev & Merged)[];
}

export type KeyPoint = { id: string; text: string } & Ev & Merged;

export type DecisionStatus = 'final' | 'tentative' | 'conditional' | 'reversed';

export type Decision = {
  id: string; // D1
  text: string;
  status: DecisionStatus;
  condition: string | null;
  rationale: string | null;
  proposedBy: string[];
  agreedBy: string[];
  topicId: string | null;
  quote: string;
  needsConfirmation: boolean;
  verified: boolean | null;
} & Ev & Merged;

export type OwnerKind = 'person' | 'team' | 'role' | 'unknown';
export type OwnerBasis =
  | 'self_commitment'
  | 'assigned_and_accepted'
  | 'assigned_no_reply'
  | 'volunteered'
  | 'unclear';
export type DueBasis = 'explicit' | 'relative_resolved' | 'vague' | 'none';
export type Priority = 'high' | 'normal' | 'low';

export type SummaryActionItem = {
  id: string; // A1
  task: string;
  deliverable: string | null;
  /** Shartli majburiyat ("agar mijoz rozi bo'lsa"); eski xulosalarda yo'q. */
  condition?: string | null;
  owner: { speaker: string | null; name: string | null; kind: OwnerKind; basis: OwnerBasis };
  assignedBy: string | null;
  due: { raw: string | null; date: string | null; time: string | null; basis: DueBasis };
  priority: Priority | null;
  status: 'open' | 'done_in_meeting';
  origin: 'explicit' | 'implicit_commitment';
  dependsOn: string[];
  topicId: string | null;
  quote: string;
  confidence: number;
  needsConfirmation: boolean;
  verified: boolean | null;
} & Ev & Merged;

export type OpenQuestion = {
  id: string; // Q1
  text: string;
  raisedBy: string | null;
  directedTo: string | null;
  whyOpen: 'no_answer' | 'no_owner' | 'deferred';
} & Ev & Merged;

export type Risk = {
  id: string; // R1
  text: string;
  kind: 'risk' | 'blocker' | 'objection' | 'concern';
  raisedBy: string | null;
  severity: 'high' | 'medium' | 'low' | null;
  mitigation: string | null;
} & Ev & Merged;

export type NumberFact = { id: string; value: string; unit: string | null; what: string } & Ev;
export type DateFact = { id: string; date: string | null; time: string | null; raw: string; what: string } & Ev;
export type NextStep = { id: string; text: string } & Ev & Merged;
export type NextMeeting = {
  date: string | null;
  time: string | null;
  raw: string | null;
  agenda: string[];
} & Ev;

export interface Highlight {
  id: string; // H1
  quote: string;
  speaker: string | null;
  segmentId: number;
  start: number;
  why: string;
  fromMark: string | null;
}

export interface UserMark {
  id: string; // m1
  t: number;
  note: string | null;
  segmentIds: number[];
  coveredBy: string[];
}

export type Sentiment = {
  overall: 'positive' | 'neutral' | 'mixed' | 'negative' | 'tense';
  note: string | null;
} & Ev;

export interface TemplateSection {
  key: string;
  items: ({ text: string; speaker: string | null } & Ev & Merged)[];
}

export interface SummaryQuality {
  warnings: string[];
  droppedItems: number;
  flaggedItems: number;
  chunks: number;
  coverageOk: boolean;
  speakersAvailable: boolean;
  languageWarning: string | null;
}

export interface SummaryContent {
  schemaVersion: 'meeting-summary/1';
  template: TemplateId;
  language: Lang;
  meeting: {
    date: string;
    weekday: string;
    timezone: 'Asia/Tashkent';
    durationSec: number;
    speakerCount: number;
  };
  title: string;
  meetingType: { value: TemplateId; confidence: number };
  overview: string;
  purpose: string | null;
  participants: SummaryParticipant[];
  topics: SummaryTopic[];
  keyPoints: KeyPoint[];
  decisions: Decision[];
  actionItems: SummaryActionItem[];
  openQuestions: OpenQuestion[];
  risks: Risk[];
  numbers: NumberFact[];
  dates: DateFact[];
  nextSteps: NextStep[];
  nextMeeting: NextMeeting | null;
  highlights: Highlight[];
  userMarks: UserMark[];
  keywords: string[];
  sentiment: Sentiment | null;
  templateSections: TemplateSection[];
  followUpMessage: { subject: string | null; body: string } | null;
  quality: SummaryQuality;
  /** Kuzatish kerak bo'lganlar - ilovada alohida bo'lim emas, o'z bandida chip. Eski serverda yo'q. */
  followUps?: FollowUp[];
  /** Server takrorlarni birlashtirgan bo'lsa: ko'rinish versiyasi va nechta band qo'shildi. */
  view?: { compact: number; merged: number } | null;
}

// ---------------------------------------------------------------- endpoints 22-25
export type ActionItemStatus = 'open' | 'done' | 'dismissed';

export interface ActionItem {
  id: string;
  meetingId: string;
  summaryItemId: string | null; // 'A3' in the primary summary
  task: string;
  owner: { speaker: string | null; name: string | null; kind: OwnerKind };
  due: { date: string | null; time: string | null; raw: string | null };
  priority: Priority | null;
  status: ActionItemStatus;
  origin: 'ai' | 'user';
  edited: boolean;
  needsConfirmation: boolean;
  sourceSegmentIds: number[];
  start: number | null;
  quote: string | null;
  createdAt: string;
  updatedAt: string;
  /** CRM taklifi (v3). null - CRM ga yuborilmagan. */
  crm: ActionCrm | null;
}

/** Backend `MyActionItem`: `recordedAt: str | None`. */
export type GlobalActionItem = ActionItem & { meetingTitle: string; recordedAt: string | null };

export interface CreateActionItemRequest {
  task: string;
  ownerSpeaker?: string | null;
  ownerName?: string | null;
  dueDate?: string | null;
  dueTime?: string | null;
  priority?: Priority | null;
}

export interface PatchActionItemRequest extends Partial<CreateActionItemRequest> {
  status?: ActionItemStatus;
}

// ---------------------------------------------------------------- endpoint 32 + /api/v1/actions
/**
 * Yordamchi (v3) TAKLIF qilgan yozuv amali - web `ActionProposal` (`apps/web/src/types.ts`)
 * nusxasi, maydonlar xizmatnikidek snake_case. HECH NARSA O'ZGARMAGAN: faqat
 * `POST /api/v1/actions/{token}/confirm` dan keyin.
 */
export interface ActionChange {
  field?: string;
  from?: unknown;
  to?: unknown;
}

export interface ActionProposal {
  token: string;
  connector?: string | null;
  operation?: string | null;
  summary?: string;
  target?: string | Record<string, unknown> | null;
  changes?: ActionChange[];
  warnings?: string[];
  expires_at?: string;
}

/** pending | executed | failed | cancelled | expired (xizmat yangisini qo'shsa ham o'tadi). */
export type ActionStatus = 'pending' | 'executed' | 'failed' | 'cancelled' | 'expired' | (string & {});

/** Vazifada saqlangan CRM taklifi (backend `ActionCrm`). */
export interface ActionCrm {
  token: string;
  status: ActionStatus;
  proposal: ActionProposal | null;
  expiresAt: string | null;
  /** Tasdiqlangandan keyin CRM qaytargani, masalan {"key": "DVSIB-231"}. */
  result: Record<string, unknown> | null;
  updatedAt: string | null;
}

export interface CrmRequest {
  project?: string | null;
  /** Muddati o'tmagan taklif bo'lsa ham yangisini so'rash. */
  force?: boolean;
}

/** `failed` sabablari (backend `services/meetings/crm.py`). */
export type CrmFailReason =
  | 'crm_not_connected'
  | 'assistant_not_configured'
  | 'assistant_busy'
  | 'assistant_unavailable'
  | 'timeout'
  | 'assistant_error'
  | 'empty'
  | (string & {});

/** `POST .../action-items/{itemId}/crm` javobi (backend `CrmResult`). */
export interface CrmResult {
  status: 'proposed' | 'answered' | 'failed';
  proposal: ActionProposal | null;
  text: string | null;
  reason: CrmFailReason | null;
  /** Yangilangan vazifa (`crm` holati bilan). */
  item: ActionItem | null;
}

/** `/api/v1/actions/{token}/confirm|cancel` javobi (backend `schemas/actions.py`). */
export interface ActionResult {
  token: string;
  status: ActionStatus;
  summary?: string;
  operation?: string | null;
  connector?: string | null;
  ok?: boolean | null;
  error?: string | null;
  request_id?: string | null;
  result?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------- endpoints 26-27
export interface Citation {
  segmentId: number;
  start: number;
  speaker: string | null;
  text: string;
}

export interface AskAnswer {
  id: string;
  question: string;
  answer: string; // markdown with [S#] tokens
  citations: Citation[];
  followUps: string[];
  createdAt: string;
}

export interface AskRequest {
  question: string;
  language?: Lang;
}

// ---------------------------------------------------------------- auth (existing + 29-31)
export interface AuthUser {
  actorId: number;
  actorType: string;
  email: string;
  fullName: string;
  position: string | null;
  department: string | null;
  roles: string[];
  passwordChangeRequired: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  tokenType: string;
  expiresAt: string;
  passwordChangeRequired: boolean;
  user: AuthUser;
}

export interface RegisterDeviceRequest {
  deviceName: string;
  platform: 'android' | 'ios';
  appVersion: string;
}

export interface RegisterDeviceResponse {
  deviceId: string;
  deviceToken: string;
  expiresAt: string;
}

export interface StatusOk {
  status: string;
}

/** Standart xato konverti (`app/core/errors.py`) + ixtiyoriy `code` va boshqalar. */
export interface ErrorEnvelope {
  timestamp?: string;
  status?: number;
  error?: string;
  message?: string;
  path?: string;
  code?: string;
  receivedBytes?: number;
  [extra: string]: unknown;
}

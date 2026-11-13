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
 * server esa `call` uchun qo'ng'iroq shablonlarini afzal ko'radi. `volume` - olib tashlangan ovoz
 * tugmasi (2026-11-09): faqat yangilanishdan oldin yozilib, hali yuklanmagan qatorlar va server
 * tarixi uchun qoldi (server ham qabul qiladi); yangi yozuvda ishlatilmaydi.
 */
export type EntrySource = 'app' | 'tile' | 'launcher' | 'volume' | 'shortcut' | 'notification' | 'link' | 'call' | 'share';
/**
 * Plaud filtri - yozuv qaysi kanaldan kelgan (server `store.ORIGIN_SQL`, 2026-11-11). `recording` - shu
 * ilovada yozilgan, `upload` - telefondan yuborilgan tayyor fayl ("Audio yuklash", "Ulashish -> Barno AI",
 * qo'ng'iroq yozuvi), `slack`/`telegram` - bot orqali, `miniapp`/`web`/`desktop` - o'sha klient, `api` - qolgani.
 */
export type MeetingOrigin = 'recording' | 'upload' | 'slack' | 'telegram' | 'miniapp' | 'web' | 'desktop' | 'api';

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
  /** Server 2026-10-10 dan beradi. */
  source?: EntrySource;
  /** Plaud filtri (server 2026-11-11 dan; eski server bermaydi). */
  origin?: MeetingOrigin;
  /**
   * Ro'yxatdagi o'rni va kun guruhi (`sort=listed`): tayyor fayl - serverga KELGAN vaqti, ilovada
   * yozilgani - `recordedAt`. Eski server bermaydi - unda `recordedAt`.
   */
  listedAt?: string;
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
/**
 * Server `ACCEPTED_TYPES` (kanonik nomlar - taxalluslar `lib/audioTypes`). Yozuvchi doim
 * `audio/aac`; qo'ng'iroq va "Ulashish" - aac/mp4; Plaud'dagi "Audio yuklash" - beshalasi.
 */
export type AudioContentType = 'audio/aac' | 'audio/mp4' | 'audio/mpeg' | 'audio/wav' | 'audio/ogg';

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
  /**
   * Ma'lumot uchun: server davomiylikni o'zi o'lchaydi (`audio.measure`) va `null` ni ham oladi.
   * Hajmdan taxmin faqat bitreyti ma'lum yozuvda (AAC/MP4); mp3/wav/ogg da - `null`.
   */
  durationSec: number | null;
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
  /** Plaud filtri: shu manbadan kelganlar. */
  origin?: MeetingOrigin | null;
  /** `listed` - `listedAt` bo'yicha (Plaud ro'yxati); server default `recorded` - `recordedAt` bo'yicha. */
  sort?: 'recorded' | 'listed';
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

// ---------------------------------------------------------------- 34. Bayonnoma (rasmiy hujjat)
/** Hujjat tili - transkript tilidan farq qilishi mumkin (server o'giradi). */
export type MinutesLanguage = 'uz-latn' | 'uz-cyrl' | 'ru' | 'en';
/** Yiqilgan yozish ham `failed` bo'ladi (`error.code = 'interrupted'`). */
export type MinutesStatus = 'running' | 'ready' | 'failed';
export type MinutesExportFormat = 'docx' | 'pdf' | 'md';

/**
 * Hujjat sarlavhasidagi faktlar - FAQAT egasi (chatdagi ko'rsatma yoki o'zgartirish so'rovida) aytgani
 * (server `content.header`, bo'sh qiymatlarsiz). Aytilmagani Word'da «________» bo'lib qoladi.
 */
export interface MinutesHeader {
  organization: string | null;
  chairedBy: string | null;
  city: string | null;
  /** Rais: lavozim va ism - egasi aytganidek (`[S#]` tokeni bo'lishi mumkin). */
  chair: string | null;
  attendees: string[];
}

/** Bandlar yoki kun tartibi bo'yicha o'zgarish: raqamlar Word'dagidek (olib tashlangani - eski raqami). */
export interface MinutesChangeSet {
  changed: number[];
  added: number[];
  removed: number[];
}

/** Tahrir ota-versiyaga nisbatan nimani o'zgartirdi (server `minutes.diff.changes`). */
export interface MinutesChanges {
  items: MinutesChangeSet;
  agenda: MinutesChangeSet;
  /** O'zgargan sarlavha kalitlari (`MinutesHeader` nomlari). */
  header: string[];
  /** `title`, `preamble`, `controller`, `notes` dan o'zgarganlari. */
  other: string[];
}

/** `GET /meetings/{id}/minutes` qatori va `POST` javobi (mazmunsiz). */
export interface MinutesView {
  id: string;
  meetingId: string;
  language: MinutesLanguage;
  status: MinutesStatus;
  createdAt: string;
  finishedAt: string | null;
  provider: string | null;
  model: string | null;
  transcriptRev: number;
  /** Hujjat yozilgandan keyin transkript tahrirlangan. */
  stale: boolean;
  agendaCount: number;
  sectionCount: number;
  itemCount: number;
  /** Model izohlari ("Aniqlashtirish kerak") - faqat ko'rsatish uchun; `minutesNotes` himoyalangan o'qiydi. */
  notes: string[];
  /** Tekshiruv ogohlantirishlari (kodlar) - varaqda faqat soni. */
  warnings: string[];
  /** Xato bilan tugaganda: kod bo'yicha matn (`message` - texnik sabab, odamga ko'rsatilmaydi). */
  error: { code: string; message: string } | null;
  // Quyidagilar - chatdagi bayonnoma (ko'rsatma va tahrir) bilan qo'shilgan; eski serverda yo'q.
  /** `revise` - chatda so'ralgan tahrir yoki yangi ko'rsatmalar qo'llangan versiya (ota-versiya bor). */
  kind?: 'generate' | 'revise';
  /** Odamga ko'rinadigan versiya: 1 - asl hujjat, har tahrir +1. */
  version?: number;
  parentId?: string | null;
  /** Shu versiyani boshlagan o'zgartirish so'rovi (egasining so'zlari); ko'rsatmalar tahririda `null`. */
  request?: string | null;
  /** Yozishda qo'llangan ko'rsatmalar soni. */
  notesApplied?: number;
  /** Faqat tayyor qatorda: egasining shu hujjatda hali yo'q ko'rsatmalari soni («Qo'llash»). */
  pendingNotes?: number;
  header?: MinutesHeader | null;
  /** Tahrirda ota-versiyaga nisbatan o'zgarishlar; asl hujjatda `null`. */
  changes?: MinutesChanges | null;
}

/** `GET /meetings/{id}/minutes/{minutesId}`: ko'rinish + mazmun (tayyor bo'lsa). */
export interface MinutesDetail extends MinutesView {
  content: Record<string, unknown> | null;
}

/** `GET /meetings/{id}/minutes`: qatorlar (eskidan yangiga) + egasining chatdagi faol ko'rsatmalari soni. */
export interface MinutesList {
  items: MinutesView[];
  /** Eski serverda yo'q (0 deb o'qiladi). */
  notes?: number;
}

export interface CreateMinutesRequest {
  language?: MinutesLanguage;
  /** Tayyori bo'lsa ham qayta yozish ("Qayta yozish"). */
  force?: boolean;
}

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

// ---------------------------------------------------------------- endpoints 26a-26c (yozuv bo'yicha chat)
export interface Citation {
  segmentId: number;
  start: number;
  speaker: string | null;
  text: string;
}

/** Bitta savol-javob (backend `AskAnswer`; `/ask` va `/questions` ham shu ko'rinishda). */
export interface AskAnswer {
  id: string;
  question: string;
  answer: string; // markdown with [S#] tokens
  citations: Citation[];
  followUps: string[];
  createdAt: string;
}

/** Savol qaysi kanaldan berilgan (backend `questions.channel`). */
export type ChatChannel = 'mobile' | 'web' | 'miniapp' | 'desktop' | 'api' | 'slack' | 'telegram';

/**
 * Chat navbatining turi: oddiy savol-javob (`chat`) yoki bayonnoma amali - ko'rsatma (`note`), hujjatni
 * tayyorlash (`create`) yoki tayyor hujjatni o'zgartirish so'rovi (`revise`).
 */
export type ChatTurnKind = 'chat' | 'note' | 'create' | 'revise';

/**
 * Navbat boshlagan bayonnoma amali (backend `ChatMinutes`). `id` bor - ish boshlangan: `status`/`version`
 * shu qatorning holati (tarix o'qilgan paytdagi), kartaning o'zi `GET /minutes/{id}` bilan kuzatadi.
 * `id` yo'q va `error` bor - ish boshlanmadi (sababi kodi bilan).
 */
export interface ChatMinutesRef {
  action: 'note' | 'create' | 'revise';
  language: MinutesLanguage | null;
  id: string | null;
  status: MinutesStatus | null;
  version: number | null;
  /** Faqat `note` navbatida: egasining faol ko'rsatmalari soni. */
  notes: number | null;
  error: { code: string; message: string } | null;
}

/**
 * Chatdagi bitta savol-javob: `AskAnswer` + kanal va javob bergan model. Suhbat bitta yozuvga
 * tegishli va egasining kanallarida BITTA - Telegram'da berilgan savol ilovada ham ko'rinadi.
 * Slack'da (umumiy hisob) har odamning suhbati alohida - `GET /chat` ularni bermaydi.
 */
export interface ChatTurn extends AskAnswer {
  /** `null` - kanal yozilmagan eski qator. */
  channel: ChatChannel | (string & {}) | null;
  /** Masalan `claude-sonnet-5-5`; eski qatorda `null`. */
  model: string | null;
  /**
   * Shu savol-javobni yaratgan xabarning kaliti (`ChatRequest.clientId`) - ilova javobi yo'lda yo'qolgan
   * xabarini shu bilan taniydi. Botlar (Slack, Telegram) va kalitsiz yuborilgan qatorlarda `null`.
   */
  clientId: string | null;
  /** Eski serverda yo'q - oddiy savol-javob (`chat`). */
  kind?: ChatTurnKind;
  /** Bayonnoma amali (javob ostidagi karta); oddiy savol-javobda va eski serverda yo'q. */
  minutes?: ChatMinutesRef | null;
}

/** `GET /meetings/{id}/chat`: faol (arxivlanmagan) savol-javoblar ESKIDAN YANGIGA. */
export interface ChatHistory {
  items: ChatTurn[];
  /** Hozir javob beradigan model (`claude-sonnet-5-5`); sozlanmagan bo'lsa bo'sh. */
  model: string;
}

/** `POST /meetings/{id}/chat` tanasi. */
export interface ChatRequest {
  /** 1-1000 belgi. */
  message: string;
  language?: Lang | null;
  /** Server analitikasi uchun; yo'q - `api`. */
  channel?: 'mobile' | 'web' | 'miniapp' | 'desktop' | 'api' | null;
  /**
   * Idempotentlik kaliti: 8-64 belgi, faqat `[A-Za-z0-9_-]` (aks holda 422). Shu yozuvda shu kalitli
   * faol savol-javob bo'lsa server uni qaytaradi (modelga qayta bormaydi, soatlik limitdan ham
   * yemaydi); shu kalit bilan urinish hali yo'lda bo'lsa - o'shani kutadi. Ilova uni har xabarga
   * beradi, "Qayta yuborish" o'sha kalitni qayta yuboradi.
   */
  clientId?: string | null;
  /**
   * Aniq kirish nuqtasi (bayonnoma varag'idan ochilgan rejim chipi): server chat modelini chaqirmaydi -
   * xabar bayonnoma uchun ko'rsatma (`note`) yoki tayyor hujjatni o'zgartirish so'rovi (`revise`).
   * Yo'q - server xabarni o'zi tasniflaydi (savol, ko'rsatma, tayyorlash yoki o'zgartirish).
   */
  intent?: 'note' | 'revise' | null;
  /** Odam qaysi tildagi hujjat haqida yozyapti (rejim chipidagi til). */
  minutesLanguage?: MinutesLanguage | null;
}

/** `DELETE /meetings/{id}/chat` ("Yangi suhbat"): nechta savol-javob arxivlandi (o'chirilmaydi). */
export interface ChatReset {
  archived: number;
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

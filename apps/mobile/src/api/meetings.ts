/**
 * Spec 3.2 dagi HAR BIR endpoint uchun tiplangan funksiya (1-31) va
 * mavjud `/auth/login`, `/auth/logout`.
 *
 * Bu yerda mantiq yo'q - faqat yo'l, metod va tana. Qaror qabul qilish
 * (retry, backoff, resync) uploader va ekranlarda. Istisno - fayl yuklash
 * (`downloadWithAuth`): JSON emas, diskka yoziladi, shuning uchun 401/xato
 * konvertini `ApiClient` o'rniga o'zi o'qiydi.
 */
import {
  AI_TIMEOUT_MS,
  ApiClient,
  ApiError,
  AuthRequiredError,
  CHUNK_TIMEOUT_MS,
  CLIENT_HEADER,
  CLIENT_NAME,
  type ApiResponse,
  type TokenProvider,
} from './client';
import type {
  ActionItem,
  AuthUser,
  ChatHistory,
  ChatRequest,
  ChatReset,
  ChatTurn,
  ChunkResponse,
  CompleteRequest,
  CreateActionItemRequest,
  CreateMeetingRequest,
  CreateMinutesRequest,
  CreateSummaryRequest,
  CrmRequest,
  CrmResult,
  DeletedResponse,
  GlobalActionItem,
  LoginRequest,
  LoginResponse,
  Meeting,
  MeetingList,
  MeetingListQuery,
  MeetingsConfig,
  MergeSpeakersRequest,
  MergeSpeakersResponse,
  MinutesDetail,
  MinutesExportFormat,
  MinutesList,
  MinutesView,
  PatchActionItemRequest,
  PatchMeetingRequest,
  PatchSegmentRequest,
  PatchSegmentResponse,
  RegisterDeviceRequest,
  RegisterDeviceResponse,
  RetranscribeRequest,
  SpeakersResponse,
  StatusOk,
  Summary,
  SummaryCard,
  SummaryExportFormat,
  Transcript,
  TranscriptExportFormat,
  UploadPosition,
} from './types';

export const API_PREFIX = '/api/v1';
const M = `${API_PREFIX}/meetings`;
const enc = encodeURIComponent;

export interface TranscriptExportOptions {
  format: TranscriptExportFormat;
  speakers?: boolean;
  timestamps?: boolean;
}

// --- 33. To'liq hujjat eksporti (fayl) ------------------------------------------------------------

/** Server `GET /meetings/{id}/export?format=` qabul qiladigan formatlar. */
export type MeetingExportFormat = 'pdf' | 'docx' | 'md' | 'txt';
/** Hujjat qismlari - server tartibida (`export.PARTS`): fayl "Qisqa xulosa" bilan boshlanadi. */
export type MeetingExportPart = 'brief' | 'summary' | 'actions' | 'mindmap' | 'transcript';
export const MEETING_EXPORT_PARTS: readonly MeetingExportPart[] = ['brief', 'summary', 'actions', 'mindmap', 'transcript'];
/** Tayyor xulosa kerak bo'lgan qismlar (transkript xulosasiz ham eksport qilinadi). */
export const SUMMARY_EXPORT_PARTS: readonly MeetingExportPart[] = ['brief', 'summary', 'actions', 'mindmap'];

export interface MeetingExportOptions {
  format: MeetingExportFormat;
  /** Bo'sh yoki yo'q - server "nima tayyor bo'lsa hammasi"ni beradi. */
  parts?: readonly MeetingExportPart[] | null;
  /** Yo'q - asosiy xulosa. */
  summaryId?: string | null;
}

/** Ulashiladigan fayl turi: kengaytma va MIME (ulashish oynasi ilovalarni shunga qarab tanlaydi). */
export const SHARE_FILE_TYPES = {
  pdf: { ext: 'pdf', mime: 'application/pdf' },
  docx: { ext: 'docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
  md: { ext: 'md', mime: 'text/markdown' },
  txt: { ext: 'txt', mime: 'text/plain' },
  // Subtitr: server `application/x-subrip` beradi (`export_transcript`).
  srt: { ext: 'srt', mime: 'application/x-subrip' },
  audio: { ext: 'm4a', mime: 'audio/mp4' },
} as const;
export type ShareFileKind = keyof typeof SHARE_FILE_TYPES;

/**
 * `POST /chat` tanasi: bayonnoma maydonlari (`intent`, `minutesLanguage`) FAQAT berilganda - oddiy
 * savolning tanasi avvalgidek qoladi (eski server ham, aniq tanani tekshiradigan test ham buzilmaydi).
 */
export function chatBody(body: ChatRequest): ChatRequest {
  const { intent, minutesLanguage, ...rest } = body;
  return { ...rest, ...(intent ? { intent } : null), ...(minutesLanguage ? { minutesLanguage } : null) };
}

/** `parts` -> `brief,summary,...` (server tartibida, takrorsiz); bo'sh - parametr yuborilmaydi. */
export function exportPartsParam(parts?: readonly MeetingExportPart[] | null): string | undefined {
  if (!parts?.length) return undefined;
  const picked = MEETING_EXPORT_PARTS.filter((p) => parts.includes(p));
  return picked.length ? picked.join(',') : undefined;
}

export function createMeetingsApi(client: ApiClient) {
  return {
    // 1
    config: () => client.request<MeetingsConfig>(`${M}/config`),
    // 2 - 201 yangi, 200 shu clientId bilan avval yaratilgan (idempotent)
    create: (body: CreateMeetingRequest): Promise<ApiResponse<Meeting>> =>
      client.send<Meeting>(M, { method: 'POST', body }),
    // 3
    uploadPosition: (id: string) => client.request<UploadPosition>(`${M}/${enc(id)}/upload`),
    // 4
    putChunk: (id: string, offset: number, bytes: Uint8Array, sha256: string) =>
      client.request<ChunkResponse>(`${M}/${enc(id)}/audio`, {
        method: 'PUT',
        query: { offset },
        rawBody: bytes,
        headers: { 'Content-Type': 'application/octet-stream', 'X-Chunk-Sha256': sha256 },
        timeoutMs: CHUNK_TIMEOUT_MS,
      }),
    // 5 - 202 navbatga qo'yildi, 200 avval shu sha bilan tugatilgan
    complete: (id: string, body: CompleteRequest): Promise<ApiResponse<Meeting>> =>
      client.send<Meeting>(`${M}/${enc(id)}/complete`, { method: 'POST', body }),
    // 6
    list: (query: MeetingListQuery = {}) =>
      client.request<MeetingList>(M, {
        query: {
          limit: query.limit ?? 20,
          offset: query.offset ?? 0,
          q: query.q || undefined,
          status: query.status || undefined,
          origin: query.origin || undefined,
          sort: query.sort,
        },
      }),
    // 7
    get: (id: string) => client.request<Meeting>(`${M}/${enc(id)}`),
    // 8
    patch: (id: string, body: PatchMeetingRequest) =>
      client.request<Meeting>(`${M}/${enc(id)}`, { method: 'PATCH', body }),
    // 9
    remove: (id: string) => client.request<DeletedResponse>(`${M}/${enc(id)}`, { method: 'DELETE' }),
    // 10
    retry: (id: string) => client.request<Meeting>(`${M}/${enc(id)}/retry`, { method: 'POST' }),
    // 11
    retranscribe: (id: string, body: RetranscribeRequest) =>
      client.request<Meeting>(`${M}/${enc(id)}/retranscribe`, { method: 'POST', body }),
    // 12
    transcript: (id: string) => client.request<Transcript>(`${M}/${enc(id)}/transcript`),
    // 13
    renameSpeaker: (id: string, speakerId: string, name: string | null) =>
      client.request<SpeakersResponse>(`${M}/${enc(id)}/speakers/${enc(speakerId)}`, { method: 'PATCH', body: { name } }),
    // 14
    mergeSpeakers: (id: string, body: MergeSpeakersRequest) =>
      client.request<MergeSpeakersResponse>(`${M}/${enc(id)}/speakers/merge`, { method: 'POST', body }),
    // 15
    patchSegment: (id: string, segmentId: number, body: PatchSegmentRequest) =>
      client.request<PatchSegmentResponse>(`${M}/${enc(id)}/segments/${segmentId}`, { method: 'PATCH', body }),
    // 16
    summaries: (id: string) => client.request<{ items: SummaryCard[] }>(`${M}/${enc(id)}/summaries`),
    // 17
    createSummary: (id: string, body: CreateSummaryRequest) =>
      client.request<SummaryCard>(`${M}/${enc(id)}/summaries`, { method: 'POST', body }),
    // 18
    summary: (id: string, summaryId: string) => client.request<Summary>(`${M}/${enc(id)}/summaries/${enc(summaryId)}`),
    // 19
    deleteSummary: (id: string, summaryId: string) =>
      client.request<DeletedResponse>(`${M}/${enc(id)}/summaries/${enc(summaryId)}`, { method: 'DELETE' }),
    // 20
    exportSummary: (id: string, summaryId: string, format: SummaryExportFormat) =>
      client.request<string>(`${M}/${enc(id)}/summaries/${enc(summaryId)}/export`, { query: { format }, responseType: 'text' }),
    // 21
    exportTranscript: (id: string, o: TranscriptExportOptions) =>
      client.request<string>(`${M}/${enc(id)}/transcript/export`, {
        query: { format: o.format, speakers: o.speakers ?? true, timestamps: o.timestamps ?? true },
        responseType: 'text',
      }),
    // 21b - o'sha transkript FAYL bo'lib (ulashish varag'i, "Subtitr (SRT)"): `downloadWithAuth`
    // bilan keshga - matn JS xotirasi va `Share.share` chegarasidan o'tmaydi.
    transcriptExportUrl: (id: string, format: TranscriptExportFormat) =>
      client.url(`${M}/${enc(id)}/transcript/export`, { format }),
    // 22
    actionItems: (id: string) => client.request<{ items: ActionItem[] }>(`${M}/${enc(id)}/action-items`),
    // 23
    addActionItem: (id: string, body: CreateActionItemRequest) =>
      client.request<ActionItem>(`${M}/${enc(id)}/action-items`, { method: 'POST', body }),
    // 24
    patchActionItem: (id: string, itemId: string, body: PatchActionItemRequest) =>
      client.request<ActionItem>(`${M}/${enc(id)}/action-items/${enc(itemId)}`, { method: 'PATCH', body }),
    // 25
    myActionItems: (status: 'open' | 'done' | 'all' = 'open', limit = 100) =>
      client.request<{ items: GlobalActionItem[] }>(`${M}/action-items`, { query: { status, limit } }),
    // 26a - yozuv bo'yicha chat (bir martalik Savol #26-27 o'rniga): faol savol-javoblar eskidan yangiga
    chatHistory: (id: string) => client.request<ChatHistory>(`${M}/${enc(id)}/chat`),
    // 26b - javobni Claude yozadi: shu yozuv matni, xulosasi va suhbatning oldingi qismi bilan (o'nlab soniya).
    // `clientId` - idempotentlik kaliti: o'sha kalit bilan qayta yuborish takror savol-javob yaratmaydi.
    // Bayonnoma amali (ko'rsatma, tayyorlash, o'zgartirish) javobdagi `minutes` da; hujjat fonda yoziladi.
    sendChat: (id: string, body: ChatRequest) =>
      client.request<ChatTurn>(`${M}/${enc(id)}/chat`, { method: 'POST', body: chatBody(body), timeoutMs: AI_TIMEOUT_MS }),
    // 26c - "Yangi suhbat": faol savol-javoblar arxivlanadi (serverda qoladi, modelga boshqa bormaydi)
    resetChat: (id: string) => client.request<ChatReset>(`${M}/${enc(id)}/chat`, { method: 'DELETE' }),
    // 28 - pleer `{uri, headers: {Authorization}}` bilan o'zi oladi
    audioUrl: (id: string) => client.url(`${M}/${enc(id)}/audio`),
    // 28b - ulashish uchun o'sha audio: `attachment` va odamga tushunarli nom bilan
    audioDownloadUrl: (id: string) => client.url(`${M}/${enc(id)}/audio`, { download: 1 }),
    // 33 - to'liq hujjat (DOCX/PDF/MD/TXT). JSON emas, FAYL: ilova uni `downloadWithAuth`
    // bilan keshga yuklab, ulashish oynasiga beradi (bo'lim sarlavhalari `Accept-Language` tilida).
    exportUrl: (id: string, o: MeetingExportOptions) =>
      client.url(`${M}/${enc(id)}/export`, {
        format: o.format,
        parts: exportPartsParam(o.parts),
        summaryId: o.summaryId || undefined,
      }),
    // 34a - bayonnomalar (rasmiy hujjat loyihasi): har til, transkript versiyasi va tahrir uchun qatorlar
    // + egasining chatdagi faol ko'rsatmalari soni (`notes`)
    minutesList: (id: string) => client.request<MinutesList>(`${M}/${enc(id)}/minutes`),
    // 34b - 200 tayyor (yoki allaqachon yozilmoqda), 202 `running` - holat 34c bilan so'raladi
    createMinutes: (id: string, body: CreateMinutesRequest) =>
      client.request<MinutesView>(`${M}/${enc(id)}/minutes`, { method: 'POST', body }),
    // 34c
    minutes: (id: string, minutesId: string) => client.request<MinutesDetail>(`${M}/${enc(id)}/minutes/${enc(minutesId)}`),
    // 34d - FAYL (Word/PDF): ExportSheet kabi `downloadWithAuth` bilan keshga, so'ng ulashish oynasi
    minutesExportUrl: (id: string, minutesId: string, format: MinutesExportFormat) =>
      client.url(`${M}/${enc(id)}/minutes/${enc(minutesId)}/export`, { format }),
    // 32 - vazifa -> v3 -> CRM TAKLIFI (hech narsa o'zgarmaydi; tasdiqlash - actions.ts)
    actionItemToCrm: (id: string, itemId: string, body: CrmRequest = {}) =>
      client.request<CrmResult>(`${M}/${enc(id)}/action-items/${enc(itemId)}/crm`, {
        method: 'POST',
        body,
        timeoutMs: AI_TIMEOUT_MS,
      }),
  };
}

export type MeetingsApi = ReturnType<typeof createMeetingsApi>;

export function createAuthApi(client: ApiClient) {
  return {
    login: (body: LoginRequest) =>
      client.request<LoginResponse>(`${API_PREFIX}/auth/login`, { method: 'POST', body, auth: false }),
    logout: () => client.request<StatusOk>(`${API_PREFIX}/auth/logout`, { method: 'POST' }),
    // Mavjud endpoint: sozlamalarda ism ko'rsatish uchun (avtomatik kirishdan keyin).
    me: () => client.request<AuthUser>(`${API_PREFIX}/auth/me`),
    // 29 - login'dan keyin darhol, hali sessiya saqlanmagan: token aniq beriladi
    registerDevice: (body: RegisterDeviceRequest, token: string) =>
      client.request<RegisterDeviceResponse>(`${API_PREFIX}/auth/devices`, {
        method: 'POST',
        body,
        auth: false,
        headers: { Authorization: `Bearer ${token}` },
      }),
    // 30
    deviceSession: (deviceToken: string) =>
      client.request<LoginResponse>(`${API_PREFIX}/auth/devices/session`, {
        method: 'POST',
        body: { deviceToken },
        auth: false,
      }),
    // 31
    revokeDevice: (deviceToken: string) =>
      client.request<StatusOk>(`${API_PREFIX}/auth/devices/revoke`, {
        method: 'POST',
        body: { deviceToken },
        auth: false,
      }),
  };
}

export type AuthApi = ReturnType<typeof createAuthApi>;

// --- Faylni yuklab olish (eksport va audio ulashish) ------------------------------------------------

/** Native yuklash natijasi: tana `uri` dagi faylda (XATO statusda ham - server konverti shu yerda). */
export interface RawDownload {
  status: number;
  uri: string;
  headers: Record<string, string>;
}

export interface DownloadProgress {
  written: number;
  /** Server aytmasa (chunked) - 0 yoki manfiy. */
  total: number;
}

export interface DownloadControl {
  /** Har yozilgan bo'lakdan keyin (native tomonda siyraklashtirilgan). */
  onProgress?: (p: DownloadProgress) => void;
  /** Bekor qilish: native yuklash ham to'xtatiladi (fayl keshda yozilib qolmasin). */
  signal?: AbortSignal;
}

/**
 * Faylni to'g'ridan-to'g'ri diskka yozadigan native qatlam (ilovada `expo-file-system/legacy`,
 * testlarda soxtasi). NIMA UCHUN JS `fetch` emas: audio o'nlab MB - JS xotirasidan va
 * ko'prikdan o'tkazmasdan, OkHttp tanani darhol faylga oqizadi.
 */
export interface FileDownloader {
  /** Xato statusda REJECT qilmaydi - `status` qaytaradi (409/503 kodini o'qish uchun). */
  download(url: string, fileUri: string, headers: Record<string, string>, control?: DownloadControl): Promise<RawDownload>;
  readText(uri: string): Promise<string>;
  remove(uri: string): Promise<void>;
}

/** Server faylni chizguncha (PDF - CPU ishi) birinchi baytni kutish chegarasi. */
export const DOWNLOAD_FIRST_BYTE_MS = 90_000;
/** Baytlar orasidagi jimlik chegarasi: shundan uzoq yangi bayt kelmasa - "to'xtab qoldi". */
export const DOWNLOAD_STALL_MS = 30_000;

export interface DownloadWithAuthOptions extends DownloadControl {
  tokens: TokenProvider;
  io: FileDownloader;
  /** `Accept-Language`: hujjatdagi bo'lim sarlavhalari shu tilda. */
  language?: string;
  firstByteMs?: number;
  stallMs?: number;
}

/** Sarlavha nomi katta-kichik harfga qaramaydi (HTTP/2 da hammasi kichik harf bilan keladi). */
export function headerOf(headers: Record<string, string> | null | undefined, name: string): string | null {
  if (!headers) return null;
  const want = name.toLowerCase();
  for (const [k, v] of Object.entries(headers)) if (k.toLowerCase() === want) return v;
  return null;
}

const DOWNLOAD_CODES: Record<number, string> = {
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  409: 'not_ready',
  410: 'gone',
  429: 'rate_limited',
  500: 'internal',
  502: 'bad_gateway',
  503: 'unavailable',
  504: 'gateway_timeout',
};

/** Xato javob tanasi (server konverti `{code, message, missing, available}`) -> `ApiError`. */
function downloadError(status: number, text: string, retryAfter: string | null): ApiError {
  let envelope: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = text ? JSON.parse(text) : null;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) envelope = parsed as Record<string, unknown>;
  } catch {
    // nginx HTML sahifasi va h.k. - kod statusdan olinadi.
    envelope = null;
  }
  const code = (typeof envelope?.code === 'string' && envelope.code) || DOWNLOAD_CODES[status] || `http_${status}`;
  const message =
    (typeof envelope?.message === 'string' && envelope.message) ||
    (typeof envelope?.detail === 'string' && envelope.detail) ||
    `Request failed (${status})`;
  const wait = retryAfter != null && retryAfter !== '' && Number.isFinite(Number(retryAfter)) ? Math.max(0, Number(retryAfter)) : null;
  return new ApiError(status, code, message, envelope, wait);
}

/**
 * Native yuklash + qo'riqchi. NIMA UCHUN: native yuklash oqim o'rtasida uzilsa (mobil tarmoq,
 * to'lgan disk) va'da ba'zan HECH QACHON tugamaydi - varaq abadiy "tayyorlanmoqda" bo'lib
 * qolardi. Birinchi bayt `firstByteMs`, keyingilari orasida `stallMs` dan ko'p jimlik bo'lsa -
 * native yuklash bekor qilinadi va `ApiError(0, 'stalled')` (qayta urinsa bo'ladi). Tashqi
 * `signal` (varaq yopildi) - `ApiError(0, 'aborted')`.
 */
function guardedDownload(o: DownloadWithAuthOptions, url: string, fileUri: string, headers: Record<string, string>): Promise<RawDownload> {
  const ctl = new AbortController();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let fail: (e: ApiError) => void = () => {};
  const guard = new Promise<never>((_, reject) => {
    fail = reject;
  });
  const arm = (ms: number) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      ctl.abort();
      fail(new ApiError(0, 'stalled', "Yuklash to'xtab qoldi"));
    }, ms);
  };
  const onOuterAbort = () => {
    ctl.abort();
    fail(new ApiError(0, 'aborted', 'Bekor qilindi'));
  };
  arm(o.firstByteMs ?? DOWNLOAD_FIRST_BYTE_MS);
  if (o.signal?.aborted) onOuterAbort();
  else o.signal?.addEventListener('abort', onOuterAbort);
  const onProgress = (p: DownloadProgress) => {
    arm(o.stallMs ?? DOWNLOAD_STALL_MS);
    o.onProgress?.(p);
  };
  const work = o.io.download(url, fileUri, headers, { onProgress, signal: ctl.signal }).catch((e: unknown) => {
    throw e instanceof ApiError ? e : new ApiError(0, 'network', e instanceof Error ? e.message : 'Tarmoq xatosi');
  });
  return Promise.race([work, guard]).finally(() => {
    if (timer) clearTimeout(timer);
    o.signal?.removeEventListener('abort', onOuterAbort);
  });
}

/**
 * Himoyalangan faylni `fileUri` ga yuklaydi: `Authorization: Bearer`, `X-Venera-Client: mobile`.
 * 401 - token BIR MARTA yangilanib qayta so'raladi (`ApiClient` bilan bir xil qoida).
 * 2xx bo'lmasa fayl o'chiriladi va `ApiError` (server `code`i bilan) tashlanadi; serverga
 * yetib bo'lmasa - `ApiError(0, 'network')`; uzilib qolsa - `ApiError(0, 'stalled')`.
 */
export async function downloadWithAuth(url: string, fileUri: string, o: DownloadWithAuthOptions): Promise<RawDownload> {
  const attempt = async (token: string): Promise<RawDownload> => {
    const headers: Record<string, string> = {
      Accept: '*/*',
      [CLIENT_HEADER]: CLIENT_NAME,
      'Accept-Language': o.language ?? 'uz',
      Authorization: `Bearer ${token}`,
    };
    let res: RawDownload;
    try {
      res = await guardedDownload(o, url, fileUri, headers);
    } catch (e) {
      await o.io.remove(fileUri).catch(() => {});
      throw e;
    }
    if (res.status >= 200 && res.status < 300) return res;
    let text = '';
    try {
      text = await o.io.readText(res.uri || fileUri);
    } catch {
      text = '';
    }
    await o.io.remove(res.uri || fileUri).catch(() => {});
    throw downloadError(res.status, text, headerOf(res.headers, 'Retry-After'));
  };
  const token = await o.tokens.getToken();
  try {
    return await attempt(token);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401 && !(e instanceof AuthRequiredError)) {
      return attempt(await o.tokens.refreshToken());
    }
    throw e;
  }
}

/** Fayl tizimi va ulashish oynasi ko'tarmaydigan belgilar (`/`, `:`, `*`, boshqaruv belgilari). */
const UNSAFE_NAME = /[\\/:*?"<>|\u0000-\u001f\u007f]+/g;
const MAX_NAME = 100;

/** Odamga ko'rinadigan fayl nomi: xavfsiz belgilar, `.ext` bilan, 100 belgidan oshmaydi. */
export function safeFileName(name: string | null | undefined, ext: string): string {
  const dotExt = `.${ext}`;
  let base = (name ?? '').replace(UNSAFE_NAME, ' ').replace(/\s+/g, ' ').trim();
  if (base.toLowerCase().endsWith(dotExt.toLowerCase())) base = base.slice(0, -dotExt.length);
  base = base.replace(/^[.\s]+|[.\s]+$/g, '').slice(0, MAX_NAME - dotExt.length).trim();
  return `${base || 'Barno AI'}${dotExt}`;
}

/**
 * `Content-Disposition` -> fayl nomi. Server ikkalasini beradi (RFC 6266): `filename*=UTF-8''...`
 * (haqiqiy o'zbekcha/kirill nom) va `filename="..."` (ASCII). Telefon odamga haqiqiysini
 * ko'rsatsin - Telegram'da "haftalik-reja.pdf" emas, "Haftalik reja 2026-10-10.pdf".
 */
export function fileNameFromDisposition(value: string | null | undefined, fallback: string, ext: string): string {
  const v = value ?? '';
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(v);
  if (star) {
    try {
      return safeFileName(decodeURIComponent(star[1].trim().replace(/^"|"$/g, '')), ext);
    } catch {
      /* buzilgan foiz kodi - oddiy nomga o'tamiz */
    }
  }
  const plain = /filename\s*=\s*"([^"]*)"|filename\s*=\s*([^;]+)/.exec(v);
  const name = plain ? (plain[1] ?? plain[2] ?? '').trim() : '';
  return safeFileName(name || fallback, ext);
}

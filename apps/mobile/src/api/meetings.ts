/**
 * Spec 3.2 dagi HAR BIR endpoint uchun tiplangan funksiya (1-31) va
 * mavjud `/auth/login`, `/auth/logout`.
 *
 * Bu yerda mantiq yo'q - faqat yo'l, metod va tana. Qaror qabul qilish
 * (retry, backoff, resync) uploader va ekranlarda.
 */
import { AI_TIMEOUT_MS, ApiClient, CHUNK_TIMEOUT_MS, type ApiResponse } from './client';
import type {
  ActionItem,
  AuthUser,
  AskAnswer,
  AskRequest,
  ChunkResponse,
  CompleteRequest,
  CreateActionItemRequest,
  CreateMeetingRequest,
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
        query: { limit: query.limit ?? 20, offset: query.offset ?? 0, q: query.q || undefined, status: query.status || undefined },
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
    // 26 - javobni v3 yozadi (o'nlab soniya)
    ask: (id: string, body: AskRequest) =>
      client.request<AskAnswer>(`${M}/${enc(id)}/ask`, { method: 'POST', body, timeoutMs: AI_TIMEOUT_MS }),
    // 27
    questions: (id: string) => client.request<{ items: AskAnswer[] }>(`${M}/${enc(id)}/questions`),
    // 28 - pleer `{uri, headers: {Authorization}}` bilan o'zi oladi
    audioUrl: (id: string) => client.url(`${M}/${enc(id)}/audio`),
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

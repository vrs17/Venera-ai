/** Ekran testlari uchun soxta servislar: API jest.fn, navbat xotirada, tarmoq yo'q. */
import type { ChatApi } from '@/api/chat';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import type { ActionsApi } from '@/api/actions';
import { ApiClient } from '@/api/client';
import type { MeetingsApi } from '@/api/meetings';
import type { ChatRequest } from '@/api/types';
import type { Session } from '@/features/auth/session';
import { createTokenStore, memoryKV } from '@/features/auth/tokenStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import type { Uploader } from '@/features/upload/uploader';
import { ServicesProvider, type Services } from '@/services';

import { actionItem, chatBackend, chatTurn, meeting, minutesView, summary, summaryCard, transcript } from './server';

/** Xotiradagi chat (`chatBackend`) -> `MeetingsApi` ning uch chat funksiyasi (jest.fn - chaqiruvlar tekshiriladi). */
export function chatEndpoints(chat: ReturnType<typeof chatBackend> = chatBackend()) {
  return {
    chatHistory: jest.fn(async (id: string) => chat.history(id)),
    sendChat: jest.fn(async (id: string, body: ChatRequest) => chat.send(id, body)),
    resetChat: jest.fn(async (id: string) => chat.reset(id)),
  };
}

export function fakeMeetingsApi(over: Partial<MeetingsApi> = {}): jest.Mocked<MeetingsApi> {
  const api = {
    config: jest.fn(),
    create: jest.fn(),
    uploadPosition: jest.fn(),
    putChunk: jest.fn(),
    complete: jest.fn(),
    list: jest.fn(async () => ({ items: [], limit: 20, offset: 0, total: 0 })),
    get: jest.fn(async () => meeting()),
    patch: jest.fn(async () => meeting()),
    remove: jest.fn(),
    retry: jest.fn(async () => meeting()),
    retranscribe: jest.fn(async () => meeting()),
    transcript: jest.fn(async () => transcript),
    renameSpeaker: jest.fn(async () => ({ speakers: transcript.speakers })),
    mergeSpeakers: jest.fn(),
    patchSegment: jest.fn(),
    summaries: jest.fn(async () => ({ items: [summaryCard] })),
    createSummary: jest.fn(async () => ({ ...summaryCard, id: 'new', status: 'queued' as const, primary: false })),
    summary: jest.fn(async () => summary()),
    deleteSummary: jest.fn(),
    exportSummary: jest.fn(async () => '# Narxlar'),
    exportTranscript: jest.fn(async () => '[00:00:00] Aziz: salom'),
    actionItems: jest.fn(async () => ({ items: [actionItem] })),
    addActionItem: jest.fn(async () => ({ ...actionItem, id: 'new', origin: 'user' as const })),
    patchActionItem: jest.fn(async () => ({ ...actionItem, status: 'done' as const })),
    myActionItems: jest.fn(async () => ({ items: [] })),
    // Har API o'z chat xotirasi bilan (testlar bir-biriga aralashmaydi); yozuvda bitta savol-javob bor.
    ...chatEndpoints(chatBackend({ [meeting().id]: [chatTurn()] })),
    audioUrl: jest.fn((id: string) => `https://x.uz/api/v1/meetings/${id}/audio`),
    actionItemToCrm: jest.fn(async () => ({ status: 'failed' as const, proposal: null, text: null, reason: 'empty', item: null })),
    transcriptExportUrl: jest.fn((id: string, format: string) => `https://x.uz/api/v1/meetings/${id}/transcript/export?format=${format}`),
    minutesList: jest.fn(async () => ({ items: [], notes: 0 })),
    createMinutes: jest.fn(async () => minutesView({ status: 'running', finishedAt: null, sectionCount: 0, itemCount: 0, notes: [] })),
    minutes: jest.fn(async () => ({ ...minutesView(), content: null })),
    minutesExportUrl: jest.fn((id: string, mid: string, format: string) => `https://x.uz/api/v1/meetings/${id}/minutes/${mid}/export?format=${format}`),
    ...over,
  };
  return api as unknown as jest.Mocked<MeetingsApi>;
}

export function fakeActionsApi(over: Partial<ActionsApi> = {}): jest.Mocked<ActionsApi> {
  const api = {
    confirm: jest.fn(async (token: string) => ({ token, status: 'executed', ok: true, result: { key: 'DVSIB-231' } })),
    cancel: jest.fn(async (token: string) => ({ token, status: 'cancelled', ok: true })),
    get: jest.fn(async (token: string) => ({ token, status: 'pending' })),
    ...over,
  };
  return api as unknown as jest.Mocked<ActionsApi>;
}

export function fakeChatApi(over: Partial<ChatApi> = {}): ChatApi {
  return {
    stream: jest.fn(async () => {}),
    list: jest.fn(async () => ({ items: [], limit: 50, offset: 0 })),
    get: jest.fn(async (id: string) => ({ chat_id: id, title: '', created_at: null, updated_at: null, messages: [] })),
    rename: jest.fn(async (id: string, title: string) => ({ chat_id: id, title, created_at: null, updated_at: null })),
    remove: jest.fn(async () => ({})),
    connectors: jest.fn(async () => ({ connectors: [] })),
    proQuota: jest.fn(async () => ({ remaining: { day: 5, week: 20, month: 50 }, limits: { day: 5, week: 20, month: 50 }, used: { day: 0, week: 0, month: 0 }, engine: 'v3', available: false })),
    docLink: jest.fn(async () => ({ url: '/api/v1/files/x', filename: 'x.pdf', expiresIn: 600 })),
    artifactLink: jest.fn(async () => ({ url: '/api/v1/files/y', filename: 'y.docx', expiresIn: 600 })),
    transcribe: jest.fn(async () => ({ text: 'Salom', truncated: false })),
    absolute: (path: string) => `https://x.uz${path}`,
    ...over,
  } as ChatApi;
}

export function fakeServices(over: { meetings?: MeetingsApi; actions?: ActionsApi; chat?: ChatApi; installKey?: string } = {}): Services {
  const kv = memoryKV(over.installKey ? { 'venera.installKey': over.installKey } : {});
  const tokens = createTokenStore(kv);
  const session: Session = {
    getToken: jest.fn(async () => 'jwt'),
    refreshToken: jest.fn(async () => 'jwt2'),
    login: jest.fn(),
    loginWith: jest.fn(),
    logout: jest.fn(async () => {}),
    hasSession: jest.fn(async () => true),
    subscribe: jest.fn(() => () => {}),
    adoptToken: jest.fn(async () => 'adopted' as const),
    ensureDevice: jest.fn(async () => true),
    webToken: jest.fn(async () => null),
  };
  const uploader: Uploader = { runOnce: jest.fn(async () => {}), retry: jest.fn(async () => {}), isRunning: () => false };
  return {
    apiBaseUrl: 'https://x.uz',
    client: new ApiClient({ baseUrl: 'https://x.uz' }),
    chat: over.chat ?? fakeChatApi(),
    meetings: over.meetings ?? fakeMeetingsApi(),
    actions: over.actions ?? fakeActionsApi(),
    auth: {} as Services['auth'],
    session,
    tokens,
    queue: createMemoryQueueStore(),
    uploader,
    files: { size: async () => null, read: async () => new Uint8Array(), remove: async () => {} },
    appVersion: '1.0.0',
    deviceName: 'SM-S921B',
  };
}

export function Providers({ services, children }: { services: Services; children: ReactNode }) {
  // Mutatsiyalar ham gcTime: Infinity - aks holda har mutatsiya 5 daqiqalik tozalash taymerini
  // qoldiradi va bitta faylni alohida (in-band) yurgizganda Jest chiqmay osilib qoladi.
  const [qc] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false, gcTime: Infinity } } }));
  return (
    <QueryClientProvider client={qc}>
      <ServicesProvider services={services}>{children}</ServicesProvider>
    </QueryClientProvider>
  );
}

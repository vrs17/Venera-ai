/**
 * Chat (yordamchi bilan suhbat) API - Mini App/web bilan AYNI yo'llar va shakllar
 * (`apps/web/src/api/chat.api.ts`, `chats.api.ts`, `types.ts`):
 *
 *   POST   /api/v1/chat/stream          savol -> NDJSON kadrlar (stage, sources, artifact,
 *                                       proposal, token, error, done)
 *   GET    /api/v1/chats                suhbatlar ro'yxati (tarix)
 *   GET    /api/v1/chats/{id}           ochilgan suhbat xabarlari
 *   PATCH  /api/v1/chats/{id}           nomini o'zgartirish
 *   DELETE /api/v1/chats/{id}           o'chirish
 *   GET    /api/v1/connectors           HRM/CRM ulanish holati
 *   GET    /api/v1/pro/quota            "Pro" bormi va qancha qoldi
 *   POST   /api/v1/stt/transcribe       ovoz -> matn (diktovka)
 *   POST   .../link                     hujjat/ariza uchun 10 daqiqalik imzolangan havola
 *
 * Kanal (`X-Venera-Client: mobile`) har so'rovda client.ts qo'yadi - server dvigatelni
 * shu kanal bo'yicha tanlaydi (prod: mobile=v3).
 */
import type { ApiClient } from './client';
import type { ActionProposal } from './types';

const V1 = '/api/v1';
const enc = encodeURIComponent;

export interface ProWindows {
  day: number;
  week: number;
  month: number;
}

export interface ProInfo {
  requested?: boolean;
  used?: boolean;
  calls?: number;
  remaining?: ProWindows;
  limits?: ProWindows;
  reason?: string;
}

export interface ProQuota {
  remaining: ProWindows;
  limits: ProWindows;
  used: ProWindows;
  engine: string;
  available: boolean;
}

export interface AnswerSource {
  kind?: 'doc' | 'law' | 'hrm' | 'crm' | (string & {});
  citation_index?: number;
  doc_id?: string | null;
  title?: string;
  section?: string;
  page?: number | null;
  preview_available?: boolean | null;
  url?: string | null;
  marker?: string;
  tool?: string;
  status?: string;
  digest?: string;
  docUrl?: string | null;
}

export interface AnswerArtifact {
  title?: string;
  doc_id?: string;
  docx_url?: string | null;
  pdf_url?: string | null;
  preview_url?: string | null;
  expires_at?: string;
}

export interface ChatFrame {
  type: string;
  text?: string;
  stage?: string;
  sources?: AnswerSource[];
  items?: AnswerSource[];
  artifact?: AnswerArtifact;
  docx_url?: string | null;
  pdf_url?: string | null;
  preview_url?: string | null;
  title?: string;
  doc_id?: string;
  proposal?: ActionProposal;
  token?: string;
  route?: string | null;
  engine?: string | null;
  pro?: ProInfo;
  code?: string;
  request_id?: string;
  [key: string]: unknown;
}

export interface ChatSummary {
  chat_id: string;
  title: string;
  title_source?: string;
  created_at: string | null;
  updated_at: string | null;
  messages?: number | null;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | (string & {});
  content: string;
  created_at: string | null;
}

export interface ChatDetail extends Omit<ChatSummary, 'messages'> {
  messages: ChatMessage[];
}

export interface ChatList {
  items: ChatSummary[];
  limit: number;
  offset: number;
}

export type ConnectorState = 'disconnected' | 'connected' | 'expired';

export interface ConnectorStatus {
  id: string;
  label: string;
  configured: boolean;
  state: ConnectorState;
  login: string | null;
  enabled: boolean;
  expiresAt: string | null;
}

export interface TranscriptResponse {
  text: string;
  language?: string;
  durationSec?: number | null;
  lowConfidence?: boolean;
  truncated?: boolean;
}

export interface FileLink {
  url: string;
  filename: string;
  expiresIn: number;
}

export interface StreamOptions {
  chatId?: string | null;
  mode?: 'standard' | 'pro';
  locale?: string;
  signal?: AbortSignal;
  onTurn?: (turnId: string) => void;
}

/**
 * NDJSON -> kadrlar. Bo'lak qatorning o'rtasida uzilishi mumkin: oxirgi to'liq
 * bo'lmagan qism keyingi bo'lakkacha kutadi. Buzuq qator tashlanadi - butun
 * javobni yiqitgandan ko'ra bitta kadrni yo'qotgan yaxshi (web bilan bir xil).
 */
export function createNdjsonParser(onFrame: (frame: ChatFrame) => void) {
  let buffer = '';
  const emit = (line: string) => {
    const text = line.trim();
    if (!text) return;
    try {
      const frame = JSON.parse(text) as ChatFrame;
      if (frame && typeof frame.type === 'string') onFrame(frame);
    } catch {
      /* buzuq kadr */
    }
  };
  return {
    push(chunk: string) {
      buffer += chunk;
      let cut = buffer.indexOf('\n');
      while (cut >= 0) {
        emit(buffer.slice(0, cut));
        buffer = buffer.slice(cut + 1);
        cut = buffer.indexOf('\n');
      }
    },
    end() {
      emit(buffer);
      buffer = '';
    },
  };
}

export function createChatApi(client: ApiClient) {
  return {
    /** Savol -> kadrlar. `error` kadri reject EMAS - u tugagan so'rovning oddiy natijasi. */
    async stream(question: string, onFrame: (frame: ChatFrame) => void, opts: StreamOptions = {}): Promise<void> {
      const parser = createNdjsonParser(onFrame);
      await client.stream(`${V1}/chat/stream`, {
        body: {
          question,
          mode: opts.mode === 'pro' ? 'pro' : undefined,
          chatId: opts.chatId ?? undefined,
          locale: opts.locale ?? undefined,
        },
        signal: opts.signal,
        onHeaders: (get) => {
          const turn = get('X-Venera-Turn')?.trim();
          if (turn) opts.onTurn?.(turn);
        },
        onChunk: (text) => parser.push(text),
      });
      parser.end();
    },

    list: (limit = 50, offset = 0) => client.request<ChatList>(`${V1}/chats`, { query: { limit, offset } }),
    get: (id: string) => client.request<ChatDetail>(`${V1}/chats/${enc(id)}`, { query: { limit: 200 } }),
    rename: (id: string, title: string) =>
      client.request<ChatSummary>(`${V1}/chats/${enc(id)}`, { method: 'PATCH', body: { title } }),
    remove: (id: string) => client.request<unknown>(`${V1}/chats/${enc(id)}`, { method: 'DELETE' }),

    connectors: () => client.request<{ connectors: ConnectorStatus[] }>(`${V1}/connectors`),
    proQuota: () => client.request<ProQuota>(`${V1}/pro/quota`),

    /** Iqtibos qilingan hujjat - imzolangan havola (tashqi brauzerda ochiladi). */
    docLink: (docId: string, filename: string) =>
      client.request<FileLink>(`${V1}/chat/doc/${enc(docId)}/link`, { method: 'POST', body: { filename } }),
    /** Ariza fayli (DOCX/PDF): `path` - kadrdagi `docx_url`/`pdf_url`. */
    artifactLink: (path: string, filename: string) =>
      client.request<FileLink>(`${path.replace(/\/+$/, '')}/link`, { method: 'POST', body: { filename } }),

    /** Diktovka: fayl (AAC, ADTS) -> matn. `language` - UI tili (uz | ru | en). */
    transcribe: (uri: string, mime: string, language: string, signal?: AbortSignal) =>
      client.postForm<TranscriptResponse>(`${V1}/stt/transcribe`, {
        signal,
        timeoutMs: 90_000,
        form: () => {
          const form = new FormData();
          // RN FormData fayl obyekti: {uri, name, type} - native o'qiydi.
          form.append('file', { uri, name: `dictation${mime === 'audio/aac' ? '.aac' : '.m4a'}`, type: mime } as unknown as Blob);
          form.append('language', language);
          return form;
        },
      }),

    /** Server yo'li (`/api/...`) -> to'liq manzil (tashqi brauzer uchun). */
    absolute: (path: string) => (/^https?:\/\//i.test(path) ? path : `${client.baseUrl}${path.startsWith('/') ? '' : '/'}${path}`),
  };
}

export type ChatApi = ReturnType<typeof createChatApi>;

/**
 * Suhbat dvigateli: savol -> oqim -> javob, tarixdan ochish.
 *
 * MANTIQ Mini App'niki bilan BIR XIL (`apps/web/src/tg/chat/useTgChat.ts`, jonli sinalgan):
 * kadrlar tartibi (stage... sources, artifact?, proposal?, token..., done), xato kadri
 * tokenlardan KEYIN kelsa javob saqlanib izoh bo'lib chiqadi, "Pro" rejimi savol
 * yuborilgan paytda qotiriladi, 404 da (boshqa qurilmada o'chirilgan) yangi suhbat.
 *
 * Bitta suhbat - bitta kalit (`chatId`): yordamchi xotirasi shu kalit bo'yicha, ya'ni
 * "va o'tgan oyda?" kabi davomli savollar kalit o'zgarmaguncha ishlaydi.
 */
import * as Crypto from 'expo-crypto';
import { create } from 'zustand';

import type { AnswerArtifact, AnswerSource, ChatApi, ChatFrame, ChatMessage, ProInfo } from '@/api/chat';
import { ApiError, StreamAbortedError } from '@/api/client';
import type { ActionProposal } from '@/api/types';
import { currentT } from '@/features/settings/settingsStore';
import { errorText } from '@/ui/errors';

export type ExchangeStatus = 'pending' | 'streaming' | 'done' | 'error' | 'stopped' | 'cancelled';
/** Savol qanday kiritilgan: yozib yoki jonli ovozli rejimda (ovozli ekran). */
export type ExchangeInput = 'text' | 'voice';

/** Server "kutish" kadri (faqat ovozli savolda): tayyor ovoz klipi javob kelguncha aytiladi. */
export interface HoldCue {
  text: string;
  clip: string | null;
  at: number;
  topic: string | null;
}

/** `ChatApi.stream` shakli - ovozli savol o'z oqimini beradi (`createVoiceChatStream`). */
export type ChatStreamFn = ChatApi['stream'];

export interface Exchange {
  id: string;
  question: string;
  answer: string;
  status: ExchangeStatus;
  stage: string | null;
  sources: AnswerSource[];
  artifact: AnswerArtifact | null;
  proposal: ActionProposal | null;
  error: string | null;
  errorCode: string | null;
  /** Qisman javobdan keyin kelgan xato - javob ostida izoh. */
  warning: string | null;
  proRequested: boolean;
  pro: ProInfo | null;
  engine: string | null;
  askedAt: number | null;
  answeredAt: number | null;
  turnId: string | null;
  input: ExchangeInput;
  /** Kelgan kutish kadrlari (birinchi tokengacha). */
  holds: HoldCue[];
}

export interface ChatDeps {
  api: ChatApi;
  locale: () => string;
  /** Pro shu savol uchun (yoqiq va bor bo'lsa). */
  proActive: () => boolean;
  /** `done` kadridagi Pro natijasi - qoldiqni yangilash uchun. */
  onPro?: (info: ProInfo) => void;
  /** Savol javob oldi - tarix ro'yxati yangilansin. */
  onTurn?: (chatId: string, question: string) => void;
  /** Suhbat boshqa qurilmada o'chirilgan (404) - ro'yxatdan olib tashlash. */
  onForget?: (chatId: string) => void;
}

export function newId(prefix = 'c'): string {
  try {
    return Crypto.randomUUID();
  } catch {
    return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
}

/** HRM/CRM tokeni yo'q yoki eskirgan - "Qayta urinish" foyda bermaydi, qayta kirish kerak. */
export function isAuthCode(code: string | null | undefined): boolean {
  return code === 'auth_missing' || code === 'auth_expired';
}

function isoToMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

function blank(id: string, question: string, proRequested: boolean, input: ExchangeInput = 'text'): Exchange {
  return {
    id,
    question,
    answer: '',
    status: 'pending',
    stage: null,
    sources: [],
    artifact: null,
    proposal: null,
    error: null,
    errorCode: null,
    warning: null,
    proRequested,
    pro: null,
    engine: null,
    askedAt: Date.now(),
    answeredAt: null,
    turnId: null,
    input,
    holds: [],
  };
}

/** Xizmatning O'Z matni yutadi; istisno - token yo'qligi (u yerda "qayta kiring" deymiz). */
export function frameErrorText(frame: ChatFrame): string {
  const t = currentT();
  const own = (frame.text ?? '').trim();
  if (isAuthCode(frame.code)) {
    const system = /\bCRM\b/i.test(own) && !/\bHRM\b/i.test(own) ? 'CRM' : 'HRM';
    return t('chat.notConnected', { system });
  }
  return own || t('chat.failed');
}

/** Saqlangan xabarlar -> savol-javob juftlari (Mini App `exchangesFrom` bilan bir xil). */
export function exchangesFrom(messages: ChatMessage[]): Exchange[] {
  const out: Exchange[] = [];
  let current: Exchange | null = null;
  for (const m of messages) {
    const content = m.content ?? '';
    if (m.role === 'assistant') {
      if (current && current.status !== 'done') {
        current.answer = content;
        current.status = 'done';
        current.answeredAt = isoToMs(m.created_at);
      } else if (current) {
        current.answer = `${current.answer}\n\n${content}`;
      } else {
        current = { ...blank(newId('ex'), '', false), answer: content, status: 'done', askedAt: null, answeredAt: isoToMs(m.created_at) };
        out.push(current);
      }
      continue;
    }
    current = { ...blank(newId('ex'), content, false), status: 'cancelled', askedAt: isoToMs(m.created_at) };
    out.push(current);
  }
  return out;
}

interface ChatState {
  chatId: string;
  exchanges: Exchange[];
  phase: 'idle' | 'sending';
  historyLoading: boolean;
  historyError: string | null;
  /** Yangi suhbat/tarix almashganda o'zgaradi - ekran pastga aylantiradi. */
  epoch: number;
  bind(deps: ChatDeps): void;
  send(text: string): boolean;
  /**
   * Ovozli savol: `send` bilan AYNI suhbat (chatId) va qoidalar - javob oddiy chatda ham
   * ko'rinadi, davomli savollar xotirasi ishlaydi. `stream` - ovoz maydonli oqim
   * (`voice: true` -> server kutish kadrlarini yuboradi). Qabul qilinmasa null.
   */
  sendVoice(text: string, stream?: ChatStreamFn): string | null;
  stop(): void;
  regenerate(id: string): void;
  newChat(): void;
  openHistory(id: string, force?: boolean): Promise<void>;
  abort(): void;
  setProposalSettled(id: string): void;
}

let deps: ChatDeps | null = null;
let controller: AbortController | null = null;
let historyRequest = 0;

export const useChat = create<ChatState>((set, get) => {
  const patch = (id: string, p: Partial<Exchange>) =>
    set((s) => ({ exchanges: s.exchanges.map((e) => (e.id === id ? { ...e, ...p } : e)) }));

  function run(id: string, question: string, mode: 'standard' | 'pro', stream?: ChatStreamFn) {
    const d = deps;
    if (!d) return;
    const mine = new AbortController();
    controller = mine;
    const turnChat = get().chatId;
    let answer = '';
    let failure: string | null = null;
    let failureCode: string | null = null;
    let proposed = false;
    set({ phase: 'sending' });

    const onFrame = (frame: ChatFrame) => {
      if (mine.signal.aborted) return;
      switch (frame.type) {
        case 'stage':
          patch(id, { stage: (frame.text ?? '').trim() || frame.stage || null });
          break;
        case 'sources':
          patch(id, { sources: frame.sources ?? frame.items ?? [] });
          break;
        case 'artifact': {
          const { type: _type, ...inline } = frame;
          void _type;
          patch(id, { artifact: (frame.artifact ?? inline) as AnswerArtifact });
          break;
        }
        case 'proposal': {
          const { type: _type, ...inline } = frame;
          void _type;
          const proposal = (frame.proposal ?? inline) as ActionProposal;
          if (proposal?.token) {
            patch(id, { proposal });
            proposed = true;
          }
          break;
        }
        case 'hold': {
          // Kutish kadri faqat javob boshlanmaguncha ma'noli (server ham birinchi tokenda to'xtatadi).
          if (answer) break;
          const cur = get().exchanges.find((e) => e.id === id);
          if (!cur) break;
          const cue: HoldCue = {
            text: String(frame.text ?? ''),
            clip: typeof frame.clip === 'string' && frame.clip ? frame.clip : null,
            at: Number(frame.at) || 0,
            topic: typeof frame.topic === 'string' ? frame.topic : null,
          };
          patch(id, { holds: [...cur.holds, cue] });
          break;
        }
        case 'token':
          answer += frame.text ?? '';
          patch(id, { answer, status: 'streaming', stage: null, error: null });
          break;
        case 'error':
          failure = frameErrorText(frame);
          failureCode = frame.code ?? null;
          break;
        case 'done':
          patch(id, { stage: null, engine: frame.engine ? String(frame.engine) : null });
          if (frame.pro) {
            patch(id, { pro: frame.pro });
            d.onPro?.(frame.pro);
          } else if (mode === 'pro') {
            // "Pro" so'raldi, lekin dvigatel uni ishlatmadi - jim qolsak odam "ishladi" deb o'ylaydi.
            patch(id, { pro: { requested: true, used: false, calls: 0, reason: 'engine' } });
          }
          break;
        default:
          break;
      }
    };

    // Ovozli savol o'z oqimini beradi (tanada `voice: true`); matnli savol - odatiy API.
    const streamFn = stream ?? d.api.stream;
    streamFn(question, onFrame, {
      chatId: turnChat,
      mode,
      locale: d.locale(),
      signal: mine.signal,
      onTurn: (turnId) => !mine.signal.aborted && patch(id, { turnId }),
    })
      .then(() => {
        if (mine.signal.aborted) return;
        if (failure && !answer) {
          patch(id, { status: 'error', error: failure, errorCode: failureCode, stage: null, answeredAt: Date.now() });
        } else {
          patch(id, { status: 'done', answer, warning: failure, error: null, stage: null, answeredAt: Date.now() });
          if (answer || proposed) d.onTurn?.(turnChat, question);
        }
        if (controller === mine) controller = null;
        set({ phase: 'idle' });
      })
      .catch((err: unknown) => {
        if (err instanceof StreamAbortedError || mine.signal.aborted) return;
        const t = currentT();
        patch(id, { status: 'error', error: errorText(t, err), errorCode: err instanceof ApiError ? err.code : null, stage: null, answeredAt: Date.now() });
        if (controller === mine) controller = null;
        set({ phase: 'idle' });
      });
  }

  return {
    chatId: newId('c'),
    exchanges: [],
    phase: 'idle',
    historyLoading: false,
    historyError: null,
    epoch: 0,

    bind(next) {
      deps = next;
    },

    send(text) {
      const trimmed = text.trim();
      if (!trimmed || get().phase !== 'idle' || !deps) return false;
      const id = newId('ex');
      // Rejim SHU YERDA qotiriladi: javob kelguncha Pro bosilsa ham bu savol o'z rejimida.
      const mode = deps.proActive() ? 'pro' : 'standard';
      set((s) => ({ exchanges: [...s.exchanges, blank(id, trimmed, mode === 'pro')] }));
      run(id, trimmed, mode);
      return true;
    },

    sendVoice(text, stream) {
      const trimmed = text.trim();
      if (!trimmed || get().phase !== 'idle' || !deps) return null;
      const id = newId('ex');
      // Pro rejimi `send` dagidek shu yerda qotiriladi.
      const mode = deps.proActive() ? 'pro' : 'standard';
      set((s) => ({ exchanges: [...s.exchanges, blank(id, trimmed, mode === 'pro', 'voice')] }));
      run(id, trimmed, mode, stream);
      return id;
    },

    stop() {
      if (get().phase !== 'sending') return;
      controller?.abort();
      controller = null;
      set((s) => ({
        phase: 'idle',
        exchanges: s.exchanges.map((e) =>
          e.status === 'pending' ? { ...e, status: 'cancelled', stage: null } : e.status === 'streaming' ? { ...e, status: 'stopped', stage: null } : e,
        ),
      }));
    },

    regenerate(id) {
      if (get().phase !== 'idle') return;
      const ex = get().exchanges.find((e) => e.id === id);
      if (!ex || !ex.question) return;
      const mode = ex.proRequested && deps?.proActive() ? 'pro' : 'standard';
      // Qayta yaratish - matnli turn: belgisi qoladi, lekin ovoz/kutish kadrlari yo'q.
      patch(id, { ...blank(id, ex.question, mode === 'pro', ex.input), askedAt: ex.askedAt });
      run(id, ex.question, mode);
    },

    newChat() {
      controller?.abort();
      controller = null;
      historyRequest++;
      set((s) => ({ chatId: newId('c'), exchanges: [], phase: 'idle', historyLoading: false, historyError: null, epoch: s.epoch + 1 }));
    },

    async openHistory(id, force = false) {
      const s = get();
      if (!force && id === s.chatId && !s.historyLoading && !s.historyError && s.exchanges.length) return;
      controller?.abort();
      controller = null;
      const request = ++historyRequest;
      set((st) => ({ chatId: id, exchanges: [], phase: 'idle', historyLoading: true, historyError: null, epoch: st.epoch + 1 }));
      try {
        const detail = await deps!.api.get(id);
        if (request !== historyRequest) return;
        set((st) => ({ exchanges: exchangesFrom(detail.messages ?? []), historyLoading: false, epoch: st.epoch + 1 }));
      } catch (err) {
        if (request !== historyRequest) return;
        if (err instanceof ApiError && err.status === 404) {
          deps?.onForget?.(id);
          get().newChat();
          return;
        }
        set({ historyLoading: false, historyError: errorText(currentT(), err) });
      }
    },

    abort() {
      controller?.abort();
      controller = null;
    },

    setProposalSettled(id) {
      patch(id, { proposal: null });
    },
  };
});

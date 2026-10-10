/**
 * Suhbatlar tarixi (chap panel / ro'yxat): serverdan, yangi savoldan keyin yangilanadi.
 *
 * Yangi suhbat birinchi javobdan keyin ro'yxatda DARHOL vaqtinchalik nom bilan
 * ko'rinadi (savolning boshi), server qisqa nomni bir necha soniyada yozadi -
 * shuning uchun bir ozdan keyin ro'yxat qayta olinadi (Mini App `useChats` kabi).
 */
import { create } from 'zustand';

import type { ChatApi, ChatSummary } from '@/api/chat';
import { currentT } from '@/features/settings/settingsStore';
import { errorText } from '@/ui/errors';

/** Savolning boshi - server nom bergunicha. */
export function provisionalTitle(question: string): string {
  const one = question.replace(/\s+/g, ' ').trim();
  return one.length > 48 ? `${one.slice(0, 47).trimEnd()}…` : one;
}

export type HistoryGroup = 'today' | 'yesterday' | 'week' | 'earlier';

/** Ro'yxat bo'limlari: bugun, kecha, shu hafta (7 kun), oldinroq. */
export function groupOf(iso: string | null, now = new Date()): HistoryGroup {
  if (!iso) return 'earlier';
  const at = new Date(iso);
  if (!Number.isFinite(at.getTime())) return 'earlier';
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(now) - day(at)) / 86_400_000);
  if (diff <= 0) return 'today';
  if (diff === 1) return 'yesterday';
  if (diff < 7) return 'week';
  return 'earlier';
}

interface ChatsState {
  items: ChatSummary[];
  loading: boolean;
  error: string | null;
  loaded: boolean;
  load(api: ChatApi): Promise<void>;
  noteTurn(api: ChatApi, chatId: string, question: string): void;
  forget(chatId: string): void;
  rename(api: ChatApi, chatId: string, title: string): Promise<void>;
  remove(api: ChatApi, chatId: string): Promise<void>;
  reset(): void;
}

let refreshTimer: ReturnType<typeof setTimeout> | null = null;

export const useChats = create<ChatsState>((set, get) => ({
  items: [],
  loading: false,
  error: null,
  loaded: false,

  async load(api) {
    set({ loading: true, error: null });
    try {
      const list = await api.list(50, 0);
      set({ items: list.items ?? [], loading: false, loaded: true });
    } catch (err) {
      set({ loading: false, error: errorText(currentT(), err) });
    }
  },

  noteTurn(api, chatId, question) {
    const now = new Date().toISOString();
    const known = get().items.find((c) => c.chat_id === chatId);
    const rest = get().items.filter((c) => c.chat_id !== chatId);
    const row: ChatSummary = known
      ? { ...known, updated_at: now }
      : { chat_id: chatId, title: provisionalTitle(question), title_source: 'auto', created_at: now, updated_at: now, messages: 2 };
    set({ items: [row, ...rest] });
    if (refreshTimer) clearTimeout(refreshTimer);
    // Server nomni javobdan keyin yozadi - bir ozdan keyin haqiqiy nom bilan almashtiramiz.
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      void get().load(api);
    }, known ? 1500 : 4000);
  },

  forget(chatId) {
    set({ items: get().items.filter((c) => c.chat_id !== chatId) });
  },

  async rename(api, chatId, title) {
    const clean = title.trim();
    if (!clean) return;
    const before = get().items;
    set({ items: before.map((c) => (c.chat_id === chatId ? { ...c, title: clean, title_source: 'user' } : c)) });
    try {
      await api.rename(chatId, clean);
    } catch (err) {
      set({ items: before });
      throw err;
    }
  },

  async remove(api, chatId) {
    const before = get().items;
    set({ items: before.filter((c) => c.chat_id !== chatId) });
    try {
      await api.remove(chatId);
    } catch (err) {
      set({ items: before });
      throw err;
    }
  },

  reset() {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = null;
    set({ items: [], loading: false, error: null, loaded: false });
  },
}));

/**
 * Barno XOTIRASI va MANBALAR (platforma kalitlari) holati - Sozlamalar hub'i, "Xotira"
 * sahifasi va "Ulanishlar" sahifasi uchun bitta mantiq. Web `useAssistantMemory.ts`,
 * `usePlatforms.ts` va `memoryCopy.ts` bilan bir xil qoidalar; holat esa React Query'da
 * (ilovaning qolgan qismi kabi): hub'dagi "N ta" va "Xotira" sahifasi BITTA keshni ko'radi -
 * band unutilsa hub soni ham darhol kamayadi. Chiqishda kesh tozalanadi (`_layout` Bootstrap),
 * boshqa odam kirsa oldingi xotira bir lahza ham ko'rinmaydi.
 *
 * O'CHIRISH OPTIMISTIK EMAS (qaytarib bo'lmaydi): server "o'chirdim" demaguncha band ro'yxatda.
 * KALIT OPTIMISTIK: darhol o'zgaradi, server rad etsa avvalgisiga qaytadi va xabar chiqadi -
 * jimgina qaytsa odam bosgani "yutilib ketdi" deb o'ylaydi.
 *
 * MAXFIYLIK: band matni hech qayerga yozilmaydi (console ham) - faqat ekranda.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useMemo, useRef, useState } from 'react';

import { createAssistantApi, type AssistantErrorKind, type MemoryItem, type MemoryList, type Platform } from '@/api/assistant';
import type { ConnectorStatus } from '@/api/chat';
import type { TFn, TKey } from '@/i18n';
import { useServices } from '@/services';

export const MEMORY_KEY = ['assistant', 'memory'] as const;
export const PLATFORMS_KEY = ['assistant', 'platforms'] as const;
/** Hub va Ulanishlar sahifasi bilan bir xil kalit (`services.chat.connectors`). */
export const CONNECTORS_KEY = ['connectors'] as const;

/** Servislardagi umumiy `ApiClient` ustida (token, til, kanal sarlavhasi - client.ts). */
export function useAssistantApi() {
  const { client } = useServices();
  return useMemo(() => createAssistantApi(client), [client]);
}

/** Yangisi birinchi (sanasizi - oxirida, server tartibida). */
export function byRecent(items: readonly MemoryItem[]): MemoryItem[] {
  const at = (m: MemoryItem) => Date.parse(m.updated_at ?? m.created_at ?? '') || 0;
  return items
    .map((item, i) => ({ item, i, t: at(item) }))
    .sort((a, b) => b.t - a.t || a.i - b.i)
    .map((x) => x.item);
}

/** Bandning kelib chiqishi: odam o'zi so'ragan / CRM vazifalaridan / savollaridan. */
export function memoryOriginKey(item: MemoryItem): TKey {
  if (item.source === 'user') return 'set.memory.sourceUser';
  if (item.kind === 'routine') return 'set.memory.sourceRoutine';
  return 'set.memory.sourceLearned';
}

/**
 * "Hammasini unutish" izohi: nechta narsa unutiladi va suhbatlar qolishi. CRM tartibi haqidagi
 * gap FAQAT shunday band bo'lsa - aks holda odam "menda CRM tartibi bormi?" deb o'ylab qolardi.
 * "Qaytarib bo'lmaydi" bu yerda yo'q - u "Tushundim" katakchasida (bir oynada ikki marta emas).
 */
export function forgetAllHint(items: readonly MemoryItem[], t: TFn): string {
  const base = t('set.memory.forgetAllHint', { n: items.length });
  return items.some((m) => m.kind === 'routine') ? `${base} ${t('set.memory.forgetAllRoutines')}` : base;
}

/** Xato turi -> odam tilidagi matn. `notFound` bu yerga yetib kelmaydi (u "allaqachon yo'q"). */
export function assistantErrorText(t: TFn, kind: AssistantErrorKind | null | undefined): string {
  const k = !kind || kind === 'notFound' ? 'generic' : kind;
  return t(`set.assistantErr.${k}` as TKey);
}

/**
 * Xotira ro'yxati. Hub soni uchun `staleTime` uzun (har ochilishda so'rov emas); "Xotira"
 * sahifasi esa 0 bilan - odam chatda "eslab qol" deb yangisini qo'shgan bo'lishi mumkin.
 */
export function useMemoryQuery(staleTime: number) {
  const api = useAssistantApi();
  return useQuery({
    queryKey: MEMORY_KEY,
    queryFn: async (): Promise<MemoryList> => {
      const list = await api.listMemory();
      return { items: byRecent(list.items), count: list.items.length };
    },
    staleTime,
  });
}

export function usePlatformsQuery() {
  const api = useAssistantApi();
  return useQuery({
    queryKey: PLATFORMS_KEY,
    queryFn: async () => api.listPlatforms(),
    staleTime: 30_000,
  });
}

export type ToggleResult = 'saved' | 'failed' | 'skipped';
/** `toggle` - platforma kaliti saqlanmadi (qaytarildi); `chat` - kalit saqlandi, token kaliti yoqilmadi. */
export type ToggleFailure = 'toggle' | 'chat';

/**
 * Platforma kaliti (optimistik + qaytarish) va "Chatda ishlatish" (HRM/CRM token kaliti).
 * Bir platforma uchun bir vaqtda bitta so'rov: javob kelguncha kalit band (`pending`) - tez-tez
 * bosishda javoblar tartibsiz kelib, ekran va server farq qilib qolmasin.
 */
export function usePlatformToggle({ onError }: { onError: (platform: Platform, what: ToggleFailure) => void }) {
  const api = useAssistantApi();
  const qc = useQueryClient();
  // Ref - bir kadr ichidagi ikkinchi bosishni ham to'xtatadi; state - ekranni yangilaydi.
  const busy = useRef(new Set<string>());
  const [pending, setPending] = useState<ReadonlySet<string>>(() => new Set());
  const [enabling, setEnabling] = useState<string | null>(null);
  // Kalitni yoqish va "Yoqish" bir vaqtda bosilsa - bitta PATCH (web `enabling` qoidasi). Ikkinchisi
  // `true` qaytaradi: natijani (xato bo'lsa xabarni) birinchi so'rov aytadi, ikki xabar chiqmaydi.
  const enablingNow = useRef(new Set<string>());

  const mark = useCallback((id: string, on: boolean) => {
    if (on) busy.current.add(id);
    else busy.current.delete(id);
    setPending(new Set(busy.current));
  }, []);

  // Kesh bo'lmasa (chiqib ketilgan) - yangi yozuv yaratilmaydi: undefined qaytsa React Query tegmaydi.
  const patch = useCallback(
    (id: string, next: Partial<Platform>) =>
      qc.setQueryData<Platform[]>(PLATFORMS_KEY, (old) => (old ? old.map((p) => (p.id === id ? { ...p, ...next } : p)) : old)),
    [qc],
  );

  /** "Chatda ishlatish" ni yoqadi - hisob ulangan, lekin kalit o'chiq bo'lsa. `false` - xato. */
  const enableForChat = useCallback(
    async (platformId: string): Promise<boolean> => {
      const list = qc.getQueryData<{ connectors: ConnectorStatus[] }>(CONNECTORS_KEY)?.connectors ?? [];
      const c = list.find((x) => String(x.id) === platformId);
      if (!c || c.state !== 'connected' || c.enabled || enablingNow.current.has(platformId)) return true;
      enablingNow.current.add(platformId);
      setEnabling(platformId);
      try {
        const next = await api.setConnectorEnabled(c.id, true);
        qc.setQueryData<{ connectors: ConnectorStatus[] }>(CONNECTORS_KEY, (old) =>
          old ? { ...old, connectors: old.connectors.map((x) => (x.id === next.id ? next : x)) } : old,
        );
        return true;
      } catch {
        return false;
      } finally {
        enablingNow.current.delete(platformId);
        setEnabling(null);
      }
    },
    [api, qc],
  );

  const toggle = useCallback(
    async (p: Platform): Promise<ToggleResult> => {
      if (!p.available || busy.current.has(p.id)) return 'skipped';
      mark(p.id, true);
      const before = { user_enabled: p.user_enabled, enabled: p.enabled };
      const wanted = !p.user_enabled;
      // Fondagi yuklash optimistik holatni eski javob bilan bosib ketmasin.
      await qc.cancelQueries({ queryKey: PLATFORMS_KEY });
      patch(p.id, { user_enabled: wanted, enabled: wanted && p.available });
      try {
        const saved = await api.setPlatform(p.id, wanted);
        if (saved) patch(p.id, saved);
      } catch {
        patch(p.id, before);
        mark(p.id, false);
        onError(p, 'toggle');
        return 'failed';
      }
      mark(p.id, false);
      // Platformani yoqqan odam Barno undan foydalanishini kutadi - token kaliti ham yoqiladi
      // (HRM uchun bitta kalit, web va Mini App kabi).
      if (wanted && !(await enableForChat(p.id))) onError(p, 'chat');
      return 'saved';
    },
    [api, qc, patch, mark, enableForChat, onError],
  );

  return { pending, enabling, toggle, enableForChat };
}

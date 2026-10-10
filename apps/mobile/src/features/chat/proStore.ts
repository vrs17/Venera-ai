/**
 * "Pro" rejimi: faqat dvigatel ruxsat bersa (`/pro/quota` -> available) ko'rinadi.
 * Kalitning o'zi sozlamada (`proOn`) - ilova qayta ochilganda ham eslab qoladi.
 * Qoldiq (kunlik) javobning `done` kadridagi `pro` blokidan yangilanadi.
 */
import { create } from 'zustand';

import type { ChatApi, ProInfo } from '@/api/chat';
import { useSettings } from '@/features/settings/settingsStore';

interface ProState {
  available: boolean;
  /** Kunlik qoldiq (null - noma'lum). */
  remaining: number | null;
  load(api: ChatApi): Promise<void>;
  note(info: ProInfo): void;
  reset(): void;
}

export const usePro = create<ProState>((set) => ({
  available: false,
  remaining: null,
  async load(api) {
    try {
      const q = await api.proQuota();
      set({ available: !!q.available, remaining: q.remaining?.day ?? null });
    } catch {
      set({ available: false, remaining: null });
    }
  },
  note(info) {
    if (info.remaining && typeof info.remaining.day === 'number') set({ remaining: info.remaining.day });
  },
  reset() {
    set({ available: false, remaining: null });
  },
}));

/** Keyingi savol Pro bilan ketadimi: kalit yoqiq, dvigatelda bor va qoldiq tugamagan. */
export function proActiveNow(): boolean {
  const { available, remaining } = usePro.getState();
  return available && useSettings.getState().proOn && (remaining === null || remaining > 0);
}

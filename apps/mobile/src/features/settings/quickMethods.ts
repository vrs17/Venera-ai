/**
 * "Tez yozish" usullari holati: hub'dagi "N ta usul yoqilgan" va Tez yozish sahifasi.
 *
 * Hisob: ilova yorlig'i (app shortcut) JS'da o'rnatiladi - DOIM bor (1). "Yozish"
 * belgisi faqat native modul bo'lsa va foydalanuvchi yoqqan bo'lsa qo'shiladi. Panel
 * plitkasi sanalmaydi: Android uning qo'shilganini ilovaga aytmaydi, yolg'on "yoqilgan"
 * demaylik. (Ovoz tugmasi bilan yozish 2026-11-09 da olib tashlandi - Play Protect.)
 */
import { useCallback, useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { isAvailable, isLauncherEnabled } from '@/features/entry/nativeEntry';

export interface QuickState {
  /** Native modul (VeneraEntry) bormi - yo'q bo'lsa (iOS, Jest) faqat yorliq ishlaydi. */
  available: boolean;
  /** "Yozish" launcher belgisi yoqilganmi. */
  launcher: boolean;
}

/** Toza hisob (test uchun alohida). */
export function quickMethodCount(s: QuickState): number {
  if (!s.available) return 1;
  return 1 + (s.launcher ? 1 : 0);
}

export function readQuickState(): QuickState {
  const available = isAvailable();
  return {
    available,
    launcher: available && isLauncherEnabled(),
  };
}

/**
 * Holat + qayta o'qish: ilovaga qaytganda (AppState `active`) holat yangidan o'qiladi -
 * belgi tizim tomonidan o'chirilgan bo'lsa (ilova yangilandi, launcher tozalandi) eski
 * "yoqilgan" qolmasin. Sahifaga qaytish (fokus) uchun chaqiruvchi `refresh`ni o'zi ulaydi.
 */
export function useQuickState(): QuickState & {
  refresh: () => void;
  /** Switch bosilgandan keyin: native holat kechikib yangilansa ham tanlov ko'rinsin. */
  setLauncher: (on: boolean) => void;
} {
  const [state, setState] = useState<QuickState>(readQuickState);
  const refresh = useCallback(() => setState(readQuickState()), []);
  const setLauncher = useCallback((on: boolean) => setState((s) => ({ ...s, launcher: on })), []);
  useEffect(() => {
    const sub = AppState.addEventListener('change', (st) => {
      if (st === 'active') refresh();
    });
    return () => sub.remove();
  }, [refresh]);
  return { ...state, refresh, setLauncher };
}

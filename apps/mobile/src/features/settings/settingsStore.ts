/**
 * Foydalanuvchi sozlamalari (spec 7.4 Settings): UI tili, lokal nusxani
 * saqlash muddati, dev uchun audio manba, bir martalik eslatmalar.
 *
 * Saqlash: expo-sqlite/kv-store (sinxron) - ilova ochilishi bilan til
 * darhol to'g'ri bo'lsin. Bu maxfiy emas, shuning uchun SecureStore emas.
 * Saqlab bo'lmasa (Jest, buzilgan DB) - xotirada ishlayveradi.
 */
import { useMemo } from 'react';
import { create } from 'zustand';

import type { Lang } from '@/api/types';
import { isUiLang, makeT, type TFn, type UiLang } from '@/i18n';

export type ThemePref = 'system' | 'light' | 'dark';

export interface Settings {
  uiLang: UiLang;
  /** Mavzu: tizimga ergashadi yoki qo'lda tanlanadi (Mini App sozlamasi kabi). */
  themePref: ThemePref;
  /** Chatda "Pro" kaliti (dvigatel ruxsat bersa) - keyingi savollar uchun. */
  proOn: boolean;
  keepDays: 0 | 7;
  /** Faqat dev: serverning `recording.audioSource` ni bosib o'tadi. */
  audioSourceOverride: string | null;
  consentSeen: boolean;
  batteryHintSeen: boolean;
  lastLanguage: Lang;
  lastSpeakers: number | null;
}

export const DEFAULT_SETTINGS: Settings = {
  uiLang: 'uz',
  themePref: 'system',
  proOn: false,
  keepDays: 0,
  audioSourceOverride: null,
  consentSeen: false,
  batteryHintSeen: false,
  lastLanguage: 'uz',
  lastSpeakers: null,
};

export interface KVSync {
  getItemSync(key: string): string | null;
  setItemSync(key: string, value: string): void;
}

const STORAGE_KEY = 'venera.settings.v1';
let storage: KVSync | null = null;

function loadStorage(): KVSync | null {
  if (storage) return storage;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('expo-sqlite/kv-store') as { Storage: KVSync };
    storage = mod.Storage;
  } catch {
    storage = null;
  }
  return storage;
}

export function parseSettings(raw: string | null): Settings {
  if (!raw) return { ...DEFAULT_SETTINGS };
  try {
    const v = JSON.parse(raw) as Partial<Settings>;
    return {
      ...DEFAULT_SETTINGS,
      ...v,
      uiLang: isUiLang(v.uiLang) ? v.uiLang : DEFAULT_SETTINGS.uiLang,
      keepDays: v.keepDays === 7 ? 7 : 0,
      themePref: v.themePref === 'light' || v.themePref === 'dark' ? v.themePref : 'system',
      proOn: v.proOn === true,
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function readInitial(): Settings {
  try {
    return parseSettings(loadStorage()?.getItemSync(STORAGE_KEY) ?? null);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

interface SettingsState extends Settings {
  set(patch: Partial<Settings>): void;
}

export const useSettings = create<SettingsState>((set, get) => ({
  ...readInitial(),
  set(patch) {
    set(patch);
    const { set: _omit, ...rest } = { ...get(), ...patch };
    void _omit;
    try {
      loadStorage()?.setItemSync(STORAGE_KEY, JSON.stringify(rest));
    } catch {
      /* xotirada qoladi */
    }
  },
}));

/** Test va background task uchun: KV ni almashtirish. */
export function __setSettingsStorage(kv: KVSync | null): void {
  storage = kv;
}

export function useT(): TFn {
  const lang = useSettings((s) => s.uiLang);
  return useMemo(() => makeT(lang), [lang]);
}

export function currentT(): TFn {
  return makeT(useSettings.getState().uiLang);
}

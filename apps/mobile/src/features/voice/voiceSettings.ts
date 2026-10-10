/**
 * Ovozli rejim sozlamalari: ovoz (ayol/erkak), tezlik, matnni ko'rsatish, quloqqa/karnay.
 *
 * Saqlash `settingsStore.ts` bilan bir xil yo'l: expo-sqlite/kv-store (sinxron) - ekran
 * ochilishi bilan to'g'ri ovoz tanlangan bo'lsin. Saqlab bo'lmasa (Jest, buzilgan DB) -
 * xotirada ishlayveradi.
 *
 * NIMA UCHUN alohida store: umumiy `settingsStore.ts` ga tegmasdan, ovoz sozlamalari
 * bitta joyda; noma'lum qiymat (eski versiya, qo'lda buzilgan) har doim default'ga qaytadi.
 */
import { create } from 'zustand';

import type { VoiceId } from '@/api/voice';
import { VOICE_IDS } from '@/api/voice';

import type { VoiceSettings, VoiceSpeed } from './types';

export { VOICE_IDS };

export const DEFAULT_VOICE_SETTINGS: VoiceSettings = { voice: 'uz_female_calm', speed: 'normal', showText: true, earpiece: false };

/** `normal` = serverning o'z default'i (0.95) - aniq yuboriladi, natija bir xil bo'lsin. */
export const SPEED_VALUE: Record<VoiceSpeed, number> = { slow: 0.85, normal: 0.95, fast: 1.1 };

const SPEEDS: readonly VoiceSpeed[] = ['slow', 'normal', 'fast'];
const STORAGE_KEY = 'venera.voice.v1';

interface KVSync {
  getItemSync(key: string): string | null;
  setItemSync(key: string, value: string): void;
}

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

function isVoiceId(v: unknown): v is VoiceId {
  return typeof v === 'string' && (VOICE_IDS as readonly string[]).includes(v);
}

export function parseVoiceSettings(raw: string | null): VoiceSettings {
  if (!raw) return { ...DEFAULT_VOICE_SETTINGS };
  try {
    const v = JSON.parse(raw) as Partial<VoiceSettings> | null;
    if (!v || typeof v !== 'object') return { ...DEFAULT_VOICE_SETTINGS };
    return {
      voice: isVoiceId(v.voice) ? v.voice : DEFAULT_VOICE_SETTINGS.voice,
      speed: SPEEDS.includes(v.speed as VoiceSpeed) ? (v.speed as VoiceSpeed) : DEFAULT_VOICE_SETTINGS.speed,
      showText: typeof v.showText === 'boolean' ? v.showText : DEFAULT_VOICE_SETTINGS.showText,
      earpiece: v.earpiece === true,
    };
  } catch {
    return { ...DEFAULT_VOICE_SETTINGS };
  }
}

function readInitial(): VoiceSettings {
  try {
    return parseVoiceSettings(loadStorage()?.getItemSync(STORAGE_KEY) ?? null);
  } catch {
    return { ...DEFAULT_VOICE_SETTINGS };
  }
}

interface VoiceSettingsState extends VoiceSettings {
  set(patch: Partial<VoiceSettings>): void;
}

export const useVoiceSettings = create<VoiceSettingsState>((set, get) => ({
  ...readInitial(),
  set(patch) {
    set(patch);
    const { voice, speed, showText, earpiece } = get();
    try {
      loadStorage()?.setItemSync(STORAGE_KEY, JSON.stringify({ voice, speed, showText, earpiece }));
    } catch {
      /* xotirada qoladi */
    }
  },
}));

/** Test uchun: KV ni almashtirish. */
export function __setVoiceSettingsStorage(kv: KVSync | null): void {
  storage = kv;
}

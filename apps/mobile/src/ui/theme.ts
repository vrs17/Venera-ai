/**
 * Ranglar: yorug' va qorong'i rejim - Mini App tokenlari bilan BIR XIL
 * (`apps/web/src/styles/tokens.css`): ilova va Telegram'dagi Barno bir xil ko'rinsin.
 * Yozish tugmasi doim qizil (Plaud kabi - "bir qarashda topiladi").
 *
 * Mavzu sozlamadan (`themePref`): tizim / yorug' / qorong'i.
 */
import { useColorScheme } from 'react-native';

import type { Tone } from '@/features/meeting/summaryModel';
import { useSettings } from '@/features/settings/settingsStore';

export interface Theme {
  dark: boolean;
  bg: string;
  surface: string;
  /** Kichik to'ldirilgan yuzalar (chip, tugma foni) - Mini App `--fill`. */
  surfaceAlt: string;
  border: string;
  borderStrong: string;
  text: string;
  /** Ikkinchi darajali matn (`--text-2`). */
  textSoft: string;
  /** Izoh, placeholder (`--text-3`). */
  textMuted: string;
  /** Eng xira (`--text-4`). */
  textFaint: string;
  /** Asosiy tugma: "siyoh" - yorug'da qora, qorong'ida oq (Mini App kabi). */
  primary: string;
  primaryText: string;
  brand: string;
  brandSoft: string;
  /** Kompozer kartasi va undagi doira tugmalar (Claude ilovasidagi zina). */
  composerBg: string;
  composerLine: string;
  composerBtn: string;
  /** Foydalanuvchi xabari pufakchasi. */
  bubble: string;
  record: string;
  danger: string;
  tones: Record<Tone, { bg: string; fg: string }>;
}

export const lightTheme: Theme = {
  dark: false,
  bg: '#FFFFFF',
  surface: '#FFFFFF',
  surfaceAlt: '#F4F4F2',
  border: '#ECECE9',
  borderStrong: '#DDDDD8',
  text: '#111110',
  textSoft: '#5C5B57',
  textMuted: '#6B6A64',
  textFaint: '#A3A29C',
  primary: '#111110',
  primaryText: '#FFFFFF',
  brand: '#EE5A24',
  brandSoft: '#FFF1EA',
  composerBg: '#FFFFFF',
  composerLine: '#DDDDD8',
  composerBtn: '#F4F4F2',
  bubble: '#F4F4F2',
  record: '#E11D48',
  danger: '#B91C1C',
  tones: {
    neutral: { bg: '#F4F4F2', fg: '#3F3E3A' },
    good: { bg: '#DCFCE7', fg: '#166534' },
    warn: { bg: '#FEF3C7', fg: '#92400E' },
    bad: { bg: '#FEE2E2', fg: '#991B1B' },
    info: { bg: '#E8F0FE', fg: '#1E40AF' },
    accent: { bg: '#FFF1EA', fg: '#B5410F' },
  },
};

export const darkTheme: Theme = {
  dark: true,
  bg: '#0E0E0F',
  surface: '#161618',
  surfaceAlt: '#1E1E20',
  border: '#26262A',
  borderStrong: '#34343A',
  text: '#F4F4F3',
  textSoft: '#B6B5AF',
  textMuted: '#8E8D88',
  textFaint: '#5F5E5A',
  primary: '#F4F4F3',
  primaryText: '#111110',
  brand: '#FF7A45',
  brandSoft: 'rgba(255, 122, 69, 0.14)',
  composerBg: '#1E1E20',
  composerLine: '#2A2A2D',
  composerBtn: '#2D2D30',
  bubble: '#1E1E20',
  record: '#FB7185',
  danger: '#F87171',
  tones: {
    neutral: { bg: '#1E1E20', fg: '#D6D5D0' },
    good: { bg: '#14321F', fg: '#86EFAC' },
    warn: { bg: '#3A2A0A', fg: '#FCD34D' },
    bad: { bg: '#3B1212', fg: '#FCA5A5' },
    info: { bg: '#132A4A', fg: '#93C5FD' },
    accent: { bg: 'rgba(255, 122, 69, 0.14)', fg: '#FFB38F' },
  },
};

export function useTheme(): Theme {
  const system = useColorScheme();
  const pref = useSettings((s) => s.themePref);
  const dark = pref === 'system' ? system === 'dark' : pref === 'dark';
  return dark ? darkTheme : lightTheme;
}

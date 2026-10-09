/**
 * Ilova darajasidagi kirish holati (zustand). Haqiqiy tokenlar SecureStore'da
 * (tokenStore.ts) - bu yerda faqat UI uchun "kirganmi" belgisi.
 */
import { create } from 'zustand';

import type { AuthUser, MeetingsConfig } from '@/api/types';

export type AuthStatus = 'unknown' | 'signedIn' | 'signedOut';

interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
  config: MeetingsConfig | null;
  /** Sessiya kutilmaganda tugadi (device token bekor) - ro'yxatda banner. */
  expired: boolean;
  setSignedIn(user?: AuthUser | null): void;
  setSignedOut(expired?: boolean): void;
  setConfig(config: MeetingsConfig | null): void;
}

export const useAuth = create<AuthState>((set) => ({
  status: 'unknown',
  user: null,
  config: null,
  expired: false,
  setSignedIn: (user) => set((s) => ({ status: 'signedIn', user: user ?? s.user, expired: false })),
  setSignedOut: (expired = false) => set({ status: 'signedOut', user: null, expired }),
  setConfig: (config) => set({ config }),
}));

/**
 * installKey (spec 2.2): birinchi ishga tushishda 32 tasodifiy bayt (hex),
 * SecureStore'da saqlanadi va har ishga tushishda native tomonga beriladi
 * (plitka/launcher deep link'ga `k=` qo'shadi). Kalit mos kelmasa yozish
 * avtomatik boshlanmaydi.
 */
import { hexKey } from '@/lib/uuid';

import type { TokenStore } from '../auth/tokenStore';
import { KEY_RE } from './deepLink';

export interface TrustedKeyDeps {
  store: Pick<TokenStore, 'getInstallKey' | 'setInstallKey'>;
  randomBytes: (n: number) => Uint8Array;
  setNativeKey?: (key: string) => void;
}

let cached: string | null = null;

export async function ensureInstallKey(deps: TrustedKeyDeps): Promise<string> {
  let key = await deps.store.getInstallKey();
  if (!key || !KEY_RE.test(key)) {
    key = hexKey(deps.randomBytes, 32);
    await deps.store.setInstallKey(key);
  }
  cached = key;
  deps.setNativeKey?.(key);
  return key;
}

/** Sinxron o'qish (deep link qarori uchun). ensureInstallKey'dan keyin. */
export function getCachedInstallKey(): string | null {
  return cached;
}

export function __resetInstallKeyCache(): void {
  cached = null;
}

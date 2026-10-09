/**
 * Deep link tozalovchi (spec 2.2). Har qanday tashqi URL shu yerdan o'tadi:
 * `venera-rec://record?...` dan faqat `src`, `k`, `action`, `n` qoladi; boshqa
 * parametrlar va tanimagan yo'llar tashlanadi.
 */
import { sanitizeIncomingPath } from '@/features/entry/deepLink';

export function redirectSystemPath({ path }: { path: string; initial: boolean }): string {
  try {
    return sanitizeIncomingPath(path);
  } catch {
    return '/';
  }
}

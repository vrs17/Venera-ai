/**
 * Deep link tozalovchi (spec 2.2). Har qanday tashqi URL shu yerdan o'tadi:
 * `venera-rec://record?...` dan faqat `src`, `k`, `action`, `n` qoladi;
 * `venera-rec://import?...` ("Ulashish -> Barno AI") dan faqat tekshirilgan `files`,
 * `skipped`, `n`, `k`; boshqa parametrlar va tanimagan yo'llar tashlanadi.
 */
import { sanitizeIncomingPath } from '@/features/entry/deepLink';

export function redirectSystemPath({ path }: { path: string; initial: boolean }): string {
  try {
    return sanitizeIncomingPath(path);
  } catch {
    return '/';
  }
}

/**
 * Xato kodi -> foydalanuvchi tilidagi matn, va qisqa toast.
 *
 * NIMA UCHUN: server `message` faqat o'zbekcha, navbatdagi `lastError` esa
 * xom kod (`network`, `timeout`, `too_long`). Ekranlar xato matnini o'zi
 * yasamasin - hammasi shu yerdan o'tadi (`err.<code>` kalitlari, i18n).
 */
import { Alert, Platform, ToastAndroid } from 'react-native';

import { ApiError } from '@/api/client';
import { makeT, type TFn, type TKey } from '@/i18n';
import { uz } from '@/i18n/uz';

export function errorKey(code: string | null | undefined): TKey | null {
  if (!code) return null;
  const k = `err.${code}`;
  return k in uz ? (k as TKey) : null;
}

/** Kod (navbat `lastError`) yoki xato obyekti -> matn. Noma'lum kod qavsda qoladi (yordam uchun). */
export function errorText(t: TFn, err: unknown): string {
  const code = typeof err === 'string' ? err : err instanceof ApiError ? err.code : null;
  const key = errorKey(code);
  if (key) return t(key);
  return code ? `${t('common.error')} (${code})` : t('common.error');
}

export function showToast(text: string): void {
  try {
    if (Platform.OS === 'android') ToastAndroid.show(text, ToastAndroid.LONG);
    else Alert.alert(text);
  } catch {
    /* toast ko'rsatib bo'lmasa ham ilova ishlashda davom etadi */
  }
}

/** Global mutatsiya xatosi (React Query `MutationCache.onError`). */
export function toastError(err: unknown, lang: Parameters<typeof makeT>[0]): void {
  showToast(errorText(makeT(lang), err));
}

/**
 * Android `Share.share({message})` matni Binder orqali o'tadi (~1 MB chegara,
 * UTF-16 da belgi 2 bayt) - undan katta matn TransactionTooLargeException
 * beradi. Shuning uchun ulashish matni cheklanadi.
 */
export const MAX_SHARE_CHARS = 100_000;

export function shareableText(text: string, t: TFn): { text: string; truncated: boolean } {
  if (text.length <= MAX_SHARE_CHARS) return { text, truncated: false };
  return { text: `${text.slice(0, MAX_SHARE_CHARS)}\n\n... ${t('err.share_truncated')}`, truncated: true };
}

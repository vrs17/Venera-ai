/**
 * Ilova belgisini bosib turganda chiqadigan "Yozishni boshlash" yorlig'i
 * (spec 2.2, expo-quick-actions dynamic shortcut). Foydalanuvchi uni bosh
 * ekranga sudrab qo'yishi mumkin.
 */
import * as QuickActions from 'expo-quick-actions';

import { buildRecordPath } from './deepLink';

export const RECORD_ACTION_ID = 'venera.record';

export function recordShortcutHref(installKey: string): string {
  return buildRecordPath({ src: 'shortcut', k: installKey, action: null });
}

export async function installRecordShortcut(installKey: string, title = 'Yozishni boshlash'): Promise<boolean> {
  try {
    if (!(await QuickActions.isSupported())) return false;
    await QuickActions.setItems([
      { id: RECORD_ACTION_ID, title, icon: null, params: { href: recordShortcutHref(installKey) } },
    ]);
    return true;
  } catch {
    return false;
  }
}

/**
 * Har bosishga noyob `n` (spec 2.2): Record ekrani ochiq turganda bir xil
 * havola expo-router'da qayta render bermaydi va yozish boshlanmasdi.
 */
export function withEntryNonce(href: string, n: number = Date.now()): string {
  return `${href}${href.includes('?') ? '&' : '?'}n=${Math.max(0, Math.floor(n))}`;
}

/** Yorliq bosilganda qaysi yo'lga o'tish. Begona action e'tiborsiz. */
export function hrefFromAction(action: QuickActions.Action | null | undefined): string | null {
  if (!action || action.id !== RECORD_ACTION_ID) return null;
  const href = action.params?.href;
  return typeof href === 'string' && href.startsWith('/record?') ? href : null;
}

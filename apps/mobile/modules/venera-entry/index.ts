/**
 * venera-entry - Android'dagi "tez yozish" kirish nuqtalari uchun JS o'rami
 * (spec 2.2): Quick Settings plitkasi, "Yozish" launcher belgisi, ishonchli
 * kalit.
 *
 * MUHIM: native modul YO'Q bo'lsa (iOS, Jest, yoki Kotlin kompilyatsiya
 * bo'lmay `autolinking.exclude` qilingan) hamma funksiya jimgina no-op.
 * Ilova bu modulsiz ham ishlashi SHART - deep link va app shortcut JS'da.
 */
import { requireOptionalNativeModule } from 'expo';
import { Platform } from 'react-native';

export type AddTileResult = 'added' | 'already' | 'denied' | 'unsupported';

interface VeneraEntryNative {
  setRecordingState(recording: boolean): void;
  requestAddTile(): Promise<AddTileResult>;
  setLauncherEnabled(enabled: boolean): void;
  isLauncherEnabled(): boolean;
  setTrustedKey(key: string): void;
  isKeyServiceEnabled(): boolean;
  openAccessibilitySettings(): void;
}

let native: VeneraEntryNative | null = null;
try {
  native = Platform.OS === 'android' ? requireOptionalNativeModule<VeneraEntryNative>('VeneraEntry') : null;
} catch {
  native = null;
}

export function isAvailable(): boolean {
  return native != null;
}

/** Plitka holati (yozilmoqda / bo'sh) - native SharedPreferences'ga. */
export function setRecordingState(recording: boolean): void {
  try {
    native?.setRecordingState(recording);
  } catch {
    /* no-op */
  }
}

/** Android 13+: tizim "plitka qo'shish" oynasi. */
export async function requestAddTile(): Promise<AddTileResult> {
  if (!native) return 'unsupported';
  try {
    return await native.requestAddTile();
  } catch {
    return 'unsupported';
  }
}

/** "Yozish" launcher belgisi (RecordLauncherActivity) yoqish/o'chirish. */
export function setLauncherEnabled(enabled: boolean): void {
  try {
    native?.setLauncherEnabled(enabled);
  } catch {
    /* no-op */
  }
}

export function isLauncherEnabled(): boolean {
  try {
    return native?.isLauncherEnabled() ?? false;
  } catch {
    return false;
  }
}

/** installKey native tomonga: plitka va launcher deep link'ga `k=` qo'shadi. */
export function setTrustedKey(key: string): void {
  try {
    native?.setTrustedKey(key);
  } catch {
    /* no-op */
  }
}

/** Ovoz tugmasi bilan yozish (RecordKeyService) Android sozlamasida yoqilganmi. */
export function isKeyServiceEnabled(): boolean {
  try {
    return native?.isKeyServiceEnabled() ?? false;
  } catch {
    return false;
  }
}

/** Android "Maxsus imkoniyatlar" sozlamasi - xizmatni foydalanuvchi o'zi yoqadi. */
export function openAccessibilitySettings(): void {
  try {
    native?.openAccessibilitySettings();
  } catch {
    /* no-op */
  }
}

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

import { contentTypeFor, isImportFileName, type CallContentType } from './importNames';

export type AddTileResult = 'added' | 'already' | 'denied' | 'unsupported';

interface VeneraEntryNative {
  setRecordingState(recording: boolean): void;
  requestAddTile(): Promise<AddTileResult>;
  setLauncherEnabled(enabled: boolean): void;
  isLauncherEnabled(): boolean;
  setTrustedKey(key: string): void;
  // Qo'ng'iroq yozuvlari (2026-10-10). Ixtiyoriy: eski APK'da bu funksiyalar yo'q.
  hasAudioReadPermission?(): boolean;
  listCallRecordings?(sinceMs: number, limit: number): Promise<unknown[]>;
  copyToAppStorage?(uri: string, destFileName: string): Promise<string>;
  getImportMeta?(fileName: string): Promise<unknown>;
  removeImport?(fileName: string): boolean;
  clearImports?(): void;
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

// ---------------------------------------------------------------------------
// Qo'ng'iroq yozuvlari (2026-10-10). Native: CallImport.kt, ImportActivity.kt.
// Modul yoki funksiya yo'q bo'lsa (Jest, iOS, eski APK): ro'yxat bo'sh, ruxsat
// yo'q, nusxa ERR_UNAVAILABLE bilan rad etiladi - ilova yiqilmaydi.
// ---------------------------------------------------------------------------

export {
  contentTypeFor,
  IMPORT_NAME_RE,
  IMPORTS_DIR,
  isImportFileName,
  MAX_SHARED_FILES,
  parseImportFiles,
  type CallContentType,
} from './importNames';

/** Samsung Telefon yozgan qo'ng'iroq (MediaStore, Recordings/Call/ yoki Call/). */
export interface CallRecording {
  /** content://media/external/audio/media/<id> - copyToAppStorage'ga shu beriladi. */
  uri: string;
  /** Asl nom, masalan "Call recording Alisher_241010_143012.m4a" (kirill bo'lishi mumkin). */
  displayName: string;
  /** "Recordings/Call/" (One UI 4+) yoki "Call/" (eski). */
  relativePath: string;
  sizeBytes: number;
  /** 0 - noma'lum (MediaStore hali o'lchamagan). */
  durationMs: number;
  /** Fayl o'zgargan vaqt, ms - taxminan qo'ng'iroq OXIRI (boshi: dateMs - durationMs). */
  dateMs: number;
  mimeType: string | null;
  /** null - server qabul qilmaydigan format (ro'yxatda "format mos emas"). */
  contentType: CallContentType | null;
}

/** "Ulashish -> Barno AI" bilan kelgan fayl (filesDir/imports/<fileName> + .json meta). */
export interface ImportMeta {
  fileName: string;
  /** Absolyut yo'l; expo-file-system uchun `toFileUri(path)` (src/lib/paths.ts). */
  path: string;
  /** Asl nom (kirill/raqam bilan) - sarlavha va suhbatdoshni ajratish uchun. */
  displayName: string;
  contentType: CallContentType | null;
  sizeBytes: number;
  durationMs: number;
  /** Manba bergan o'zgarish sanasi, ms; noma'lum bo'lsa null (fayl nomidan yoki hozirgi vaqt). */
  dateMs: number | null;
  source: 'share';
}

export type CallImportErrorCode =
  | 'ERR_UNAVAILABLE'
  | 'ERR_BAD_URI'
  | 'ERR_PERMISSION'
  | 'ERR_READ'
  | 'ERR_EMPTY'
  | 'ERR_TOO_LARGE'
  | 'ERR_NO_SPACE'
  | 'ERR_IO';

export type CallImportError = Error & { code: CallImportErrorCode };

const IMPORT_ERROR_CODES: readonly string[] = [
  'ERR_UNAVAILABLE',
  'ERR_BAD_URI',
  'ERR_PERMISSION',
  'ERR_READ',
  'ERR_EMPTY',
  'ERR_TOO_LARGE',
  'ERR_NO_SPACE',
  'ERR_IO',
];

function importError(code: CallImportErrorCode, cause?: unknown): CallImportError {
  const message = cause instanceof Error && cause.message ? cause.message : code;
  return Object.assign(new Error(message), { code });
}

function importErrorCode(e: unknown): CallImportErrorCode {
  const code = e && typeof e === 'object' ? (e as { code?: unknown }).code : undefined;
  return typeof code === 'string' && IMPORT_ERROR_CODES.includes(code) ? (code as CallImportErrorCode) : 'ERR_IO';
}

const posNum = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0);
const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const asContentType = (v: unknown): CallContentType | null => (v === 'audio/mp4' || v === 'audio/aac' ? v : null);

// Native qatorini tekshiramiz: eski/yangi APK farqi yoki kutilmagan qiymat UI'ni buzmasin.
function toCallRecording(raw: unknown): CallRecording | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const uri = str(r.uri);
  if (!uri.startsWith('content://')) return null;
  const displayName = str(r.displayName);
  const mimeType = typeof r.mimeType === 'string' ? r.mimeType : null;
  return {
    uri,
    displayName,
    relativePath: str(r.relativePath),
    sizeBytes: posNum(r.sizeBytes),
    durationMs: posNum(r.durationMs),
    dateMs: posNum(r.dateMs),
    mimeType,
    contentType: asContentType(r.contentType) ?? contentTypeFor(displayName, mimeType),
  };
}

function toImportMeta(raw: unknown): ImportMeta | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const fileName = str(r.fileName);
  const path = str(r.path);
  if (!isImportFileName(fileName) || !path.startsWith('/')) return null;
  const dateMs = posNum(r.dateMs);
  return {
    fileName,
    path,
    displayName: str(r.displayName) || fileName,
    contentType: asContentType(r.contentType) ?? contentTypeFor(fileName),
    sizeBytes: posNum(r.sizeBytes),
    durationMs: posNum(r.durationMs),
    dateMs: dateMs > 0 ? dateMs : null,
    source: 'share',
  };
}

/** Qo'ng'iroq importi shu APK'da bormi (eski APK'da Kotlin funksiyalari yo'q). */
export function isCallImportAvailable(): boolean {
  return typeof native?.listCallRecordings === 'function';
}

/**
 * `PermissionsAndroid.request(...)` uchun ruxsat nomi: Android 13+ READ_MEDIA_AUDIO,
 * undan pastda READ_EXTERNAL_STORAGE. Android bo'lmasa null.
 */
export function audioReadPermission(): 'android.permission.READ_MEDIA_AUDIO' | 'android.permission.READ_EXTERNAL_STORAGE' | null {
  if (Platform.OS !== 'android') return null;
  return Number(Platform.Version) >= 33 ? 'android.permission.READ_MEDIA_AUDIO' : 'android.permission.READ_EXTERNAL_STORAGE';
}

/** Audio fayllarni o'qish ruxsati berilganmi (native tekshiradi; modul yo'q bo'lsa false). */
export function hasAudioReadPermission(): boolean {
  try {
    return native?.hasAudioReadPermission?.() ?? false;
  } catch {
    return false;
  }
}

/**
 * Samsung qo'ng'iroq yozuvlari, eng yangisi birinchi; `sinceMs` - fayl o'zgargan vaqt
 * bo'yicha (ms, 0 = hammasi). Ruxsat yo'q / modul yo'q / xato - bo'sh ro'yxat
 * (ruxsatni `hasAudioReadPermission()` bilan alohida tekshiring).
 */
export async function listCallRecordings(sinceMs = 0, limit = 100): Promise<CallRecording[]> {
  const m = native;
  if (!m?.listCallRecordings) return [];
  try {
    const since = Number.isFinite(sinceMs) && sinceMs > 0 ? Math.floor(sinceMs) : 0;
    const max = Number.isFinite(limit) ? Math.min(500, Math.max(1, Math.floor(limit))) : 100;
    const rows: unknown = await m.listCallRecordings(since, max);
    if (!Array.isArray(rows)) return [];
    return rows.map(toCallRecording).filter((r): r is CallRecording => r !== null);
  } catch {
    return [];
  }
}

/**
 * content:// faylni `filesDir/recordings/<xavfsiz nom>` ga oqim bilan nusxalaydi va
 * ABSOLYUT yo'lni qaytaradi (nom band bo'lsa `-1` qo'shiladi - qaytgan yo'lni ishlating).
 * Xato: `CallImportError` (`error.code`: ERR_PERMISSION, ERR_TOO_LARGE, ERR_NO_SPACE ...).
 */
export async function copyToAppStorage(uri: string, destFileName: string): Promise<string> {
  const m = native;
  if (!m?.copyToAppStorage) throw importError('ERR_UNAVAILABLE');
  let path: unknown;
  try {
    path = await m.copyToAppStorage(uri, destFileName);
  } catch (e) {
    throw importError(importErrorCode(e), e);
  }
  if (typeof path !== 'string' || !path.startsWith('/')) throw importError('ERR_IO');
  return path;
}

/** imports/<fileName> haqida (asl nom, tur, hajm, davomiylik, sana); yo'q bo'lsa null. */
export async function getImportMeta(fileName: string): Promise<ImportMeta | null> {
  const m = native;
  if (!m?.getImportMeta || !isImportFileName(fileName)) return null;
  try {
    return toImportMeta(await m.getImportMeta(fileName));
  } catch {
    return null;
  }
}

/** imports/<fileName> va uning .json meta'sini o'chiradi (bekor qilindi / navbatga ko'chirildi). */
export function removeImport(fileName: string): boolean {
  if (!isImportFileName(fileName)) return false;
  try {
    return native?.removeImport?.(fileName) ?? false;
  } catch {
    return false;
  }
}

/** Butun imports/ papkasini o'chiradi - chiqishda (umumiy telefon). */
export function clearImports(): void {
  try {
    native?.clearImports?.();
  } catch {
    /* no-op */
  }
}

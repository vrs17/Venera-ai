/**
 * "Ulashish -> Barno" va Plaud'dagi "Audio yuklash": `imports/` dagi fayllar bilan ishlash -
 * meta o'qish, holat (yuborsa bo'ladimi), navbatga ko'chirish va tashlab yuborish.
 *
 * Ikki manba, bitta papka: native ImportActivity (m4a/aac) va JS tanlash oynasi (yana mp3/wav/ogg).
 * Native qo'llaydigan nomlar (m4a/mp4/aac) native orqali (Kotlin `readImportMeta`/`removeImport`);
 * mp3/wav/ogg ni Kotlin tanimaydi (modul bu serverda qayta yig'ilmaydi) - ular uchun JS manba:
 * `<nom>.json` expo-file-system bilan o'qiladi va fayllar JS'da o'chiriladi. 24 soatlik tozalash
 * (native `removeStale` ham, JS `sweep` ham) papkadagi HAMMA faylga qaraydi - bu turlar ham qolmaydi;
 * chiqishda native `clearImports` butun papkani o'chiradi.
 *
 * Tasdiqlanmagan fayl `imports/` da qoladi: "Bekor qilish" va yuborilmay qolganlar shu yerda
 * o'chiriladi, chiqishda esa butun papka (integratsiya eslatmasi).
 */
import * as Crypto from 'expo-crypto';
import { File } from 'expo-file-system';

import { getImportMeta, removeImport } from '@/features/entry/nativeEntry';
import { audioTypeFor, isAudioContentType, isVideoContentType } from '@/lib/audioTypes';
import { recordingFile, toFileUri } from '@/lib/paths';
import { uuidV4 } from '@/lib/uuid';
import type { Services } from '@/services';

import { isNativeImportName } from './importNames';
import { appImportsDir, type ImportsDir } from './pickAudio';
import type { ImportFileMeta, ImportSendDeps } from './send';

export type { ImportFileMeta } from './send';

export type ImportItemStatus = 'ok' | 'missing' | 'unsupported' | 'too_large';

export interface ImportItem {
  name: string;
  meta: ImportFileMeta | null;
}

/** Shu fayl uchun server chegarasi: video (`maxVideoBytes`) - alohida, audio - `maxBytes`. */
export function importLimitFor(it: ImportItem, maxBytes: number | null, maxVideoBytes: number | null = null): number | null {
  return isVideoContentType(it.meta?.contentType) ? maxVideoBytes : maxBytes;
}

export function importItemStatus(it: ImportItem, maxBytes: number | null, maxVideoBytes: number | null = null): ImportItemStatus {
  if (!it.meta || it.meta.sizeBytes <= 0) return 'missing';
  if (!it.meta.contentType) return 'unsupported';
  const limit = importLimitFor(it, maxBytes, maxVideoBytes);
  if (limit && it.meta.sizeBytes > limit) return 'too_large';
  return 'ok';
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const posNum = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0);

/**
 * JS yozgan fayl ma'lumoti - Kotlin `readImportMeta` bilan bir xil qoidalar: tur meta'dan (beshta
 * turdan biri bo'lsa) yoki nomdan, hajm - faylning o'zidan, nom bo'sh bo'lsa - fayl nomi.
 */
export function readJsImportMeta(dir: ImportsDir, name: string): ImportFileMeta | null {
  const st = dir.stat(name);
  if (!st || !st.path.startsWith('/')) return null;
  const json = dir.readMeta(name);
  const displayName = str(json?.displayName);
  const declared = json?.contentType;
  const dateMs = posNum(json?.dateMs);
  return {
    fileName: name,
    path: st.path,
    displayName: displayName.trim() ? displayName : name,
    contentType: isAudioContentType(declared) ? declared : audioTypeFor(name),
    sizeBytes: st.size,
    durationMs: posNum(json?.durationMs),
    dateMs: dateMs > 0 ? dateMs : null,
    source: 'share',
  };
}

/** JS papka faqat kerak bo'lganda (native nomlar uchun expo-file-system chaqirilmaydi). */
function lazyDir(): () => ImportsDir {
  let dir: ImportsDir | null = null;
  return () => {
    if (!dir) dir = appImportsDir();
    return dir;
  };
}

export async function loadImportItems(names: string[]): Promise<ImportItem[]> {
  const jsDir = lazyDir();
  return Promise.all(
    names.map(async (name) => {
      if (isNativeImportName(name)) return { name, meta: await getImportMeta(name).catch(() => null) };
      try {
        return { name, meta: readJsImportMeta(jsDir(), name) };
      } catch {
        return { name, meta: null };
      }
    }),
  );
}

/** `imports/<nom>` va `.json` i: native nom - Kotlin `removeImport`, mp3/wav/ogg - JS (Kotlin ularni rad etadi). */
function removeOne(name: string, jsDir: () => ImportsDir): boolean {
  if (isNativeImportName(name)) return removeImport(name);
  try {
    jsDir().remove(name);
    return true;
  } catch {
    return false;
  }
}

/** Yuborilmaydigan fayllarni `imports/` dan o'chiradi (begona ilovadan kelgan audio telefonda qolib ketmasin). */
export function discardImports(names: string[]): void {
  const jsDir = lazyDir();
  for (const n of names) removeOne(n, jsDir);
}

export function importSendDeps(services: Pick<Services, 'queue'>): ImportSendDeps {
  const jsDir = lazyDir();
  return {
    queue: services.queue,
    moveIntoRecordings(meta, clientId, ext) {
      const dst = recordingFile(clientId, ext);
      new File(toFileUri(meta.path)).moveSync(dst);
      return dst.uri;
    },
    removeImport: (fileName) => removeOne(fileName, jsDir),
    newClientId: () => uuidV4((n) => Crypto.getRandomBytes(n)),
  };
}

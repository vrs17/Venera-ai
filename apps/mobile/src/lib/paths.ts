/**
 * Fayl yo'llari (spec 2.3): yozuvlar `Paths.document/recordings/<clientId>.aac`.
 *
 * NIMA UCHUN cache emas: Android cache papkasini joy kam bo'lganda O'ZI
 * tozalaydi - yuklanmagan yig'ilish yo'qoladi. document papkasi faqat ilova
 * o'chirilganda tozalanadi (allowBackup=false, shuning uchun zaxiraga ham
 * tushmaydi).
 */
import { Directory, File, Paths } from 'expo-file-system';

export const RECORDINGS_DIR = 'recordings';
/** Yozishni boshlash uchun minimal bo'sh joy (spec 2.3 "Limits"). */
export const MIN_FREE_BYTES = 200 * 1024 * 1024;

export function recordingsDir(): Directory {
  const dir = new Directory(Paths.document, RECORDINGS_DIR);
  if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
  return dir;
}

export function recordingFile(clientId: string, extension = '.aac'): File {
  return new File(recordingsDir(), `${clientId}${extension}`);
}

/** expo-audio ba'zan `file://`siz yo'l qaytaradi - File() uchun bir xil ko'rinish. */
export function toFileUri(pathOrUri: string): string {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(pathOrUri)) return pathOrUri;
  return `file://${pathOrUri.startsWith('/') ? '' : '/'}${pathOrUri}`;
}

export function availableDiskBytes(): number | null {
  try {
    return Paths.availableDiskSpace;
  } catch {
    return null;
  }
}

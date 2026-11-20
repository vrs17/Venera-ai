/**
 * `imports/` dagi fayl nomlari - "Ulashish -> Barno" (native) va Plaud'dagi "Audio yuklash" (JS).
 *
 * Native ImportActivity faqat m4a/aac yozadi; uning qoidalari Kotlin `CallImport.kt` bilan AYNAN
 * bir xil (`modules/venera-entry/importNames`) va O'ZGARMAYDI. "Audio yuklash" esa yana mp3/wav/ogg
 * ham yozadi. NIMA UCHUN bu turlar faqat JS'da: native modulni bu serverda qayta yig'ib, telefonda
 * sinab bo'lmaydi - shuning uchun Kotlin `readImportMeta`/`removeImport` ularni tanimaydi va meta
 * o'qish hamda o'chirish JS'da (`importFiles.ts`). Nom qoidasi bir xil: ASCII, `..` yo'q, 120 belgi.
 *
 * Sof modul (native'siz): deep link tozalovchi (`deepLink.ts`) ham shuni ishlatadi.
 */
import { audioTypeFor } from '@/lib/audioTypes';

import { IMPORT_NAME_RE, isImportFileName, MAX_SHARED_FILES } from '../../../modules/venera-entry/importNames';

/** Native (Kotlin `readImportMeta`/`removeImport`) taniydigan nom: m4a/mp4/aac. */
export function isNativeImportName(name: string): boolean {
  return isImportFileName(name);
}

/** `imports/` dagi nom sifatida yaroqlimi: native nomlar + JS yozgan mp3/wav/ogg. */
export function isImportName(name: string): boolean {
  return IMPORT_NAME_RE.test(name) && !name.includes('..') && audioTypeFor(name) !== null;
}

/**
 * `/import?files=a.m4a,b.mp3` dagi `files` -> tekshirilgan nomlar (native `parseImportFiles` kabi:
 * yaroqsizi tashlanadi, takrorsiz, ko'pi bilan 20). Begona havola `imports/` dan tashqariga
 * ishora qila olmaydi va hech narsa tasdiqsiz yuborilmaydi.
 */
export function parseImportNames(raw: string | string[] | null | undefined): string[] {
  const joined = Array.isArray(raw) ? raw.join(',') : (raw ?? '');
  const out: string[] = [];
  for (const part of joined.split(',')) {
    const name = part.trim();
    if (name && isImportName(name) && !out.includes(name)) out.push(name);
    if (out.length >= MAX_SHARED_FILES) break;
  }
  return out;
}

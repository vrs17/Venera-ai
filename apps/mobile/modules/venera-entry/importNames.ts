/**
 * Qo'ng'iroq yozuvi / "Ulashish -> Barno AI" importi uchun SOF yordamchilar.
 *
 * NIMA UCHUN alohida fayl: native modulga bog'liq emas - deep link tozalovchi
 * (`deepLink.ts`) va testlar buni `nativeEntry` mock'idan qat'i nazar ishlata
 * oladi. Qoidalar Kotlin `CallImport.kt` dagi bilan AYNAN bir xil bo'lishi shart.
 */

/** Server qabul qiladigan turlar (apps/api meetings ACCEPTED_TYPES). */
export type CallContentType = 'audio/mp4' | 'audio/aac';

/** ImportActivity nusxalari: `Paths.document/imports/<nom>` (+ `<nom>.json` meta). */
export const IMPORTS_DIR = 'imports';

/** Bir ulashishda ko'pi bilan shuncha fayl (ImportActivity ham shuncha oladi). */
export const MAX_SHARED_FILES = 20;

/** Xavfsiz fayl nomi: faqat ASCII harf/raqam . _ - ; 120 belgigacha. */
export const IMPORT_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/;

// Kengaytma aniq boshqa format bo'lsa MIME'ga ishonmaymiz (yuboruvchi noto'g'ri MIME berishi mumkin).
const OTHER_AUDIO_EXT = new Set(['mp3', 'ogg', 'oga', 'opus', 'wav', 'amr', 'awb', '3gp', '3ga', 'flac', 'wma', 'mid', 'midi', 'webm']);
const MP4_MIME = new Set(['audio/mp4', 'audio/m4a', 'audio/x-m4a']);
const AAC_MIME = new Set(['audio/aac', 'audio/x-aac', 'audio/aacp', 'audio/aac-adts']);

/**
 * Yuklash turi: avval kengaytma (m4a/mp4 -> audio/mp4, aac -> audio/aac), keyin MIME.
 * `null` - server qabul qilmaydi (mp3, ogg, wav ...): ro'yxatda "format mos emas".
 */
export function contentTypeFor(name: string | null | undefined, mimeType?: string | null): CallContentType | null {
  const n = name ?? '';
  const dot = n.lastIndexOf('.');
  const ext = dot >= 0 && dot < n.length - 1 ? n.slice(dot + 1).toLowerCase() : '';
  if (ext === 'm4a' || ext === 'mp4') return 'audio/mp4';
  if (ext === 'aac') return 'audio/aac';
  if (OTHER_AUDIO_EXT.has(ext)) return null;
  const mime = (mimeType ?? '').split(';')[0].trim().toLowerCase();
  if (MP4_MIME.has(mime)) return 'audio/mp4';
  if (AAC_MIME.has(mime)) return 'audio/aac';
  return null;
}

/** imports/ dagi fayl nomi sifatida yaroqlimi (deep link'dan kelgan nomni tekshirish). */
export function isImportFileName(name: string): boolean {
  return IMPORT_NAME_RE.test(name) && !name.includes('..') && contentTypeFor(name) !== null;
}

/**
 * `venera-rec://import?files=a.m4a,b.aac` dagi `files` qiymati -> tekshirilgan nomlar.
 * Yaroqsiz nom tashlanadi, takror olib tashlanadi, ko'pi bilan MAX_SHARED_FILES.
 */
export function parseImportFiles(raw: string | string[] | null | undefined): string[] {
  const joined = Array.isArray(raw) ? raw.join(',') : (raw ?? '');
  const out: string[] = [];
  for (const part of joined.split(',')) {
    const name = part.trim();
    if (name && isImportFileName(name) && !out.includes(name)) out.push(name);
    if (out.length >= MAX_SHARED_FILES) break;
  }
  return out;
}

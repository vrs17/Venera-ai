/**
 * "Audio yuklash" (Plaud ro'yxati): tizim fayl oynasidan tanlangan audio fayl(lar)ni "Ulashish ->
 * Barno AI" bilan AYNAN bir yo'lga qo'yadi. Fayl `Paths.document/imports/` ga (Android
 * `filesDir/imports/` - native `CallImport.readImportMeta` o'qiydigan o'sha papka) ImportActivity
 * beradigan nom va `<nom>.json` meta bilan nusxalanadi, so'ng mavjud tasdiq ekrani (`/import`):
 * suhbat tili, "Yuborish"/"Bekor qilish" -> navbat (source `share` - server tekshiradigan o'sha
 * qiymat) -> rezyumli yuklash.
 *
 * Turlar - serverning beshtasi (2026-11-09, ega roziligi): m4a, aac, mp3, wav, ogg/oga/opus
 * (avval kengaytma, keyin MIME taxalluslari bilan - `lib/audioTypes`) va VIDEO (2026-11-17, ega qarori):
 * mp4/mov/m4v - server audiosini ajratib oladi, video saqlanmaydi; chegarasi alohida
 * (`MAX_VIDEO_COPY_BYTES`, server `maxVideoUploadBytes` - 1 GB); WebM/MKV/AVI - `video_unsupported`
 * ("MP4 yuboring"). Video nusxasi `.m4v` nomli - native uni tanimaydi, meta JS'da. Native "Ulashish -> Barno AI"
 * esa avvalgidek faqat m4a/aac: Kotlin modulini bu serverda qayta yig'ib, sinab bo'lmaydi - shuning
 * uchun mp3/wav/ogg FAQAT shu JS yo'lida (meta o'qish va tozalash ham JS'da - `importFiles.ts`).
 *
 * Qolgan cheklovlar native bilan bir xil (`CallImport.kt`): mazmun boshi e'lon qilingan turga mos
 * (server birinchi bo'lakda xuddi shuni tekshiradi - `matchesAudioType`), 160 MB dan katta
 * nusxalanmaydi (server 150 MB oladi - tasdiq ekrani `maxUploadBytes` bilan aytadi), joy kam bo'lsa
 * nusxalanmaydi, bir martada 20 tagacha. Qabul qilinmaganlar `skipped` - tasdiq ekranidagi
 * "N ta fayl qo'shilmadi" banneri.
 *
 * NIMA UCHUN JS nusxa (Kotlin emas): tanlash oynasi o'qish ruxsatini asosiy activity'ga beradi -
 * expo-file-system `content://` ni fon oqimida (`File.copy`) o'zi nusxalaydi; native modulga yangi
 * funksiya (va qayta yig'ish) kerak emas. Davomiylik o'lchanmaydi (0 - noma'lum): native o'lchay
 * olmaganda ham shunday, server audioni o'zi o'lchaydi.
 */
import { Platform } from 'react-native';

import type { AudioContentType } from '@/api/types';
import { isCallImportAvailable } from '@/features/entry/nativeEntry';
import { AUDIO_EXTENSIONS, audioTypeFor, isUnsupportedVideo, isVideoContentType, matchesAudioType, sniffAudioType } from '@/lib/audioTypes';

// Sof yordamchilar native'siz (`nativeEntry` testlarda mock qilinadi) - deepLink.ts kabi to'g'ridan-to'g'ri.
import { IMPORTS_DIR, MAX_SHARED_FILES } from '../../../modules/venera-entry/importNames';

/** Bitta fayl nusxasi chegarasi - Kotlin `CallImport.MAX_COPY_BYTES` bilan bir xil. */
export const MAX_COPY_BYTES = 160 * 1024 * 1024;
/**
 * Video nusxasi chegarasi: server 1 GB oladi (`maxVideoUploadBytes`) - ozgina ortig'i ham nusxalanadi,
 * tasdiq ekrani serverning aniq chegarasi bilan "juda katta" deydi (audio 160/150 MB kabi).
 */
export const MAX_VIDEO_COPY_BYTES = 1100 * 1024 * 1024;

/** Shu tur uchun nusxa chegarasi (video - alohida). */
export function maxCopyBytes(contentType: AudioContentType): number {
  return isVideoContentType(contentType) ? MAX_VIDEO_COPY_BYTES : MAX_COPY_BYTES;
}
/** Nusxadan keyin ham shuncha joy qolsin (yangi yig'ilish yozuvi uchun) - Kotlin `RESERVE_BYTES`. */
export const RESERVE_BYTES = 50 * 1024 * 1024;
/** Tasdiqlanmay qolgan nusxa shuncha vaqtdan keyin o'chiriladi - Kotlin `STALE_IMPORT_MS`. */
export const STALE_IMPORT_MS = 24 * 60 * 60 * 1000;
/** Yarim qolgan `.part` - Kotlin `STALE_PART_MS` (parallel nusxaga tegilmaydi). */
export const STALE_PART_MS = 60 * 60 * 1000;
/** Mazmun boshidan shuncha bayt tekshiriladi (RIFF....WAVE - 12 bayt; `ftyp`, ADTS, MP3 kadri, OggS). */
const HEADER_BYTES = 12;
/**
 * Tanlash oynasidagi turlar. `application/ogg` - ba'zi manbalar Opus/Vorbis'ni shunday ataydi va u
 * `audio/*` ga tushmaydi (server ham uni `audio/ogg` deb oladi). `video/*` - 2026-11-17 dan (audiosi olinadi).
 */
export const PICK_MIME_TYPES: readonly string[] = ['audio/*', 'application/ogg', 'video/*'];
/** Asl nom (meta .json) chegarasi - Kotlin `MAX_DISPLAY_NAME`. */
const MAX_DISPLAY_NAME = 200;

/** Tanlash oynasi qaytargan fayl (expo-document-picker `DocumentPickerAsset` dan kerakli qism). */
export interface PickedAudio {
  uri: string;
  name?: string | null;
  size?: number | null;
  mimeType?: string | null;
  /** Fayl o'zgargan vaqt (ms); noma'lum bo'lsa tanlash oynasi hozirgi vaqtni beradi. */
  lastModified?: number | null;
}

/** `<nom>.json` - native `writeMeta` bilan bir xil maydonlar (`readImportMeta`/`readJsImportMeta` o'qiydi). */
export interface ImportMetaFile {
  displayName: string;
  contentType: AudioContentType;
  sizeBytes: number;
  durationMs: number;
  dateMs: number | null;
  source: 'share';
}

/** `imports/` papkasi bilan ishlash (ilovada expo-file-system, testlarda soxtasi). */
export interface ImportsDir {
  exists(name: string): boolean;
  /** `src` ni `imports/<name>.part` ga nusxalab `imports/<name>` ga o'tkazadi; haqiqiy hajmni qaytaradi. */
  copyIn(src: string, name: string): Promise<number>;
  /** `imports/<name>` boshidagi ko'pi bilan `n` bayt. */
  head(name: string, n: number): Uint8Array;
  writeMeta(name: string, meta: ImportMetaFile): void;
  /** `<name>.json` (yo'q yoki buzilgan bo'lsa null) - tasdiq ekrani mp3/wav/ogg uchun o'qiydi. */
  readMeta(name: string): Record<string, unknown> | null;
  /** `imports/<name>` ning absolyut yo'li va hajmi; fayl yo'q bo'lsa null. */
  stat(name: string): { path: string; size: number } | null;
  /** Fayl, uning `.json` va `.part` i (yo'q bo'lsa jim). */
  remove(name: string): void;
  /** Bo'sh joy (bayt); aniqlab bo'lmasa null - tekshiruv o'tkazib yuboriladi. */
  freeBytes(): number | null;
  /** Eskirgan tasdiqlanmagan nusxalarni o'chiradi (Kotlin `removeStale`). */
  sweep(now: number): void;
}

/**
 * `mismatch` - fayl boshi kengaytmasi aytgan formatga zid (masalan ".mp3" ichida WAV);
 * `video_unsupported` - MP4/MOV bo'lmagan video ("MP4 yuboring"); `video_too_large` - video chegarasidan katta.
 */
export type PickSkipReason = 'unsupported' | 'mismatch' | 'too_large' | 'no_space' | 'read' | 'video_unsupported' | 'video_too_large';

export interface PickImportResult {
  /** `imports/` dagi nomlar - `/import?files=` ga shu. */
  files: string[];
  /** Qabul qilinmaganlar soni (format, hajm, joy, o'qish, 20 dan ortig'i). */
  skipped: number;
  /** Birinchi qabul qilinmagan faylning sababi - hech biri o'tmasa toast shuni aytadi. */
  reason: PickSkipReason | null;
}

/** Kotlin `asciiOnly`: [A-Za-z0-9._-] dan boshqasi `_`, ketma-ket `_` bittaga. */
function asciiOnly(s: string): string {
  return s.replace(/[^A-Za-z0-9._-]/g, '_').replace(/_{2,}/g, '_');
}

/** Fayl nomining o'zagi (kengaytmasiz, 40 belgi) - Kotlin `safeStem`; kirill nom bo'lsa "audio". */
export function importStem(displayName: string | null | undefined): string {
  const base = (displayName ?? '').split('/').pop() ?? '';
  const dot = base.lastIndexOf('.');
  const stem = asciiOnly(dot > 0 ? base.slice(0, dot) : base)
    .replace(/\./g, '_')
    .replace(/^[_-]+|[_-]+$/g, '');
  return stem.slice(0, 40).replace(/[_-]+$/, '') || 'audio';
}

/**
 * `share_<to'plam>_<tartib>_<o'zak>.<kengaytma>` - ImportActivity nomi bilan bir xil (`IMPORT_NAME_RE`
 * dan o'tadi); kengaytma turdan (server `EXTENSIONS`): .m4a, .aac, .mp3, .wav, .ogg.
 */
export function importFileName(batch: number, index: number, displayName: string | null | undefined, contentType: AudioContentType): string {
  return `share_${batch}_${index}_${importStem(displayName)}${AUDIO_EXTENSIONS[contentType]}`;
}

/** Nom band bo'lsa `-1`, `-2` ... - Kotlin `uniqueFile` (navbatdagi boshqa fayl ustidan yozilmasin). */
export function uniqueImportName(name: string, exists: (n: string) => boolean): string {
  if (!exists(name)) return name;
  const dot = name.lastIndexOf('.');
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : '';
  for (let i = 1; i <= 999; i++) {
    const candidate = `${stem}-${i}${ext}`;
    if (!exists(candidate)) return candidate;
  }
  throw new Error('no free file name');
}

/**
 * Mazmun boshi e'lon qilingan turga mosmi (server birinchi bo'lakda xuddi shuni tekshiradi):
 * mos - null; boshqa qabul qilinadigan formatga o'xshaydi - `mismatch`; hech biriga - `unsupported`.
 */
export function headerProblem(head: Uint8Array, contentType: AudioContentType): PickSkipReason | null {
  if (matchesAudioType(head, contentType)) return null;
  return sniffAudioType(head) ? 'mismatch' : 'unsupported';
}

/** Nusxa yaroqlimi: bo'sh emas, chegaradan katta emas, mazmun boshi turga mos. */
function checkCopy(dir: ImportsDir, name: string, bytes: number, contentType: AudioContentType): PickSkipReason | null {
  const video = isVideoContentType(contentType);
  if (!(bytes > 0)) return 'read';
  if (bytes > maxCopyBytes(contentType)) return video ? 'video_too_large' : 'too_large';
  try {
    // Kengaytma/MIME'ni fayl manbai aytadi - mazmun ham shu format ekani tekshiriladi.
    const bad = headerProblem(dir.head(name, HEADER_BYTES), contentType);
    // ".mp4" ichida WebM/MKV - odamga aniq sabab: "MP4 yuboring".
    return bad && video ? 'video_unsupported' : bad;
  } catch {
    return 'read';
  }
}

/** Bitta fayl: tur -> hajm -> joy -> nusxa -> mazmun -> meta (native `importShared` tartibi). */
async function importOne(dir: ImportsDir, asset: PickedAudio, batch: number, index: number): Promise<{ name: string } | { skip: PickSkipReason }> {
  const contentType = audioTypeFor(asset.name, asset.mimeType);
  if (!contentType) return { skip: isUnsupportedVideo(asset.name, asset.mimeType) ? 'video_unsupported' : 'unsupported' };
  const size = typeof asset.size === 'number' && asset.size > 0 ? asset.size : null;
  if (size != null && size > maxCopyBytes(contentType)) return { skip: isVideoContentType(contentType) ? 'video_too_large' : 'too_large' };
  const free = dir.freeBytes();
  if (size != null && free != null && free < size + RESERVE_BYTES) return { skip: 'no_space' };
  let name: string;
  let bytes: number;
  try {
    name = uniqueImportName(importFileName(batch, index, asset.name, contentType), (n) => dir.exists(n));
    bytes = await dir.copyIn(asset.uri, name);
  } catch {
    return { skip: 'read' };
  }
  const bad = checkCopy(dir, name, bytes, contentType);
  if (bad) {
    dir.remove(name);
    return { skip: bad };
  }
  try {
    dir.writeMeta(name, {
      displayName: (asset.name || name).slice(0, MAX_DISPLAY_NAME),
      contentType,
      sizeBytes: bytes,
      durationMs: 0,
      dateMs: typeof asset.lastModified === 'number' && asset.lastModified > 0 ? asset.lastModified : null,
      source: 'share',
    });
  } catch {
    // Meta bo'lmasa ham fayl yaroqli - tasdiq ekrani fayl nomini ko'rsatadi (native kabi).
  }
  return { name };
}

/**
 * Tanlangan fayllarni `imports/` ga qo'yadi; yiqilgani o'chiriladi va `skipped` ga sanaladi
 * (20 dan ortig'i ham - native kabi). Hech narsa yuborilmaydi - faqat tasdiq ekraniga tayyorlanadi.
 */
export async function importPickedAudio(dir: ImportsDir, picked: readonly PickedAudio[], o: { now?: () => number } = {}): Promise<PickImportResult> {
  const batch = (o.now ?? Date.now)();
  // Tasdiqlanmay qolgan eski nusxalar (orqaga bosildi) - imports/ cheksiz o'smasin (native ham shunday qiladi).
  try {
    dir.sweep(batch);
  } catch {
    /* tozalab bo'lmasa ham import davom etadi */
  }
  const files: string[] = [];
  let skipped = Math.max(0, picked.length - MAX_SHARED_FILES);
  let reason: PickSkipReason | null = null;
  for (let i = 0; i < Math.min(picked.length, MAX_SHARED_FILES); i++) {
    const r = await importOne(dir, picked[i], batch, i);
    if ('name' in r) {
      files.push(r.name);
    } else {
      skipped++;
      reason = reason ?? r.skip;
    }
  }
  return { files, skipped, reason };
}

/**
 * "Audio yuklash" shu ilovada ishlaydimi: tasdiq ekrani faylni native `getImportMeta` bilan o'qiydi
 * (qo'ng'iroq importi bilan bir APK funksiyasi). Modul yo'q bo'lsa (iOS, Jest, `autolinking.exclude`)
 * tugma ko'rsatilmaydi - aks holda har fayl "topilmadi" bo'lib chiqardi.
 */
export function audioUploadSupported(): boolean {
  try {
    return Platform.OS === 'android' && isCallImportAvailable() === true;
  } catch {
    return false;
  }
}

/**
 * Ilovadagi `imports/` (expo-file-system). `require` - native modul faqat tanlashdan keyin yuklanadi
 * (ekran va testlar ularsiz). Nusxa `.part` ga, oxirida nom almashadi: yarim nusxa (ilova
 * o'ldirildi) hech qachon tayyor fayl bo'lib ko'rinmaydi.
 */
export function appImportsDir(): ImportsDir {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const FS = require('expo-file-system') as typeof import('expo-file-system');
  const dir = new FS.Directory(FS.Paths.document, IMPORTS_DIR);
  const file = (name: string) => new FS.File(dir, name);
  const quietDelete = (f: InstanceType<typeof FS.File>) => {
    try {
      if (f.exists) f.delete();
    } catch {
      /* yo'q yoki allaqachon o'chirilgan */
    }
  };
  return {
    exists: (name) => file(name).exists,
    async copyIn(src, name) {
      if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
      const part = file(`${name}.part`);
      quietDelete(part);
      try {
        await new FS.File(src).copy(part);
        part.rename(name);
      } catch (e) {
        quietDelete(part);
        throw e;
      }
      return file(name).size;
    },
    head(name, n) {
      const handle = file(name).open(FS.FileMode.ReadOnly);
      try {
        return handle.readBytes(n);
      } finally {
        handle.close();
      }
    },
    writeMeta(name, meta) {
      file(`${name}.json`).write(JSON.stringify(meta));
    },
    readMeta(name) {
      try {
        const meta = file(`${name}.json`);
        if (!meta.exists) return null;
        const value: unknown = JSON.parse(meta.textSync());
        return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
      } catch {
        return null;
      }
    },
    stat(name) {
      const f = file(name);
      if (!f.exists) return null;
      // Nomlar faqat [A-Za-z0-9._-] - URI'dan yo'l oddiy kesish bilan (native `ImportMeta.path` kabi absolyut).
      return { path: f.uri.replace(/^file:\/\//, ''), size: f.size };
    },
    remove(name) {
      for (const f of [file(name), file(`${name}.json`), file(`${name}.part`)]) quietDelete(f);
    },
    freeBytes() {
      try {
        return FS.Paths.availableDiskSpace;
      } catch {
        return null;
      }
    },
    sweep(at) {
      if (!dir.exists) return;
      for (const entry of dir.list()) {
        if (!(entry instanceof FS.File)) continue;
        const age = at - (entry.modificationTime ?? at);
        if (age > (entry.name.endsWith('.part') ? STALE_PART_MS : STALE_IMPORT_MS)) quietDelete(entry);
      }
    },
  };
}

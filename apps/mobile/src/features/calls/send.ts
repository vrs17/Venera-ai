/**
 * Qo'ng'iroq yozuvini / ulashilgan faylni yig'ilishlar navbatiga qo'shish.
 *
 * Yangi yuklash yo'li YO'Q: fayl ilova xotirasiga (`recordings/`) nusxalanadi va oddiy
 * navbat qatori yoziladi (`source` call/share; `contentType` - qo'ng'iroq va native ulashishda
 * audio/mp4 yoki audio/aac, Plaud'dagi "Audio yuklash" da yana audio/mpeg, audio/wav, audio/ogg) -
 * keyin yozuvlar bilan bir xil rezyumli uploader, oflayn kutish, xato pill'lari, xulosa.
 *
 * Takror yubormaslik ikki qavat:
 *  1. `sent` ro'yxati (callsStore) - ro'yxatda "Yuborildi", avtomatik yuborish o'tkazib yuboradi.
 *  2. clientId DETERMINISTIK (egasi + yozuv kaliti): ro'yxat yozilmay crash bo'lsa ham qayta
 *     yuborishda server o'sha yig'ilishni qaytaradi (`POST /meetings` clientId bo'yicha idempotent).
 *
 * Toza mantiq: native nusxa, navbat va uploader tashqaridan beriladi (Jest'da tekshiriladi).
 */
import type { AudioContentType, Lang } from '@/api/types';
import type { CallRecording, CallImportErrorCode, ImportMeta } from '@/features/entry/nativeEntry';
import { formatTime } from '@/features/meeting/formatDate';
import { newQueueRow, type QueueStore } from '@/features/upload/queueStore';
import type { Uploader } from '@/features/upload/uploader';
import type { TFn } from '@/i18n';
import { AUDIO_EXTENSIONS, type AudioExtension } from '@/lib/audioTypes';
import { sha256Hex } from '@/lib/sha256';
import { uuidV4 } from '@/lib/uuid';

import { importTitle, parseCallFileName, recordedAtMs, uploadTitle } from './fileName';

/**
 * Yozuv kaliti: MediaStore id'si qayta indekslashda o'zgarishi mumkin - shuning uchun yo'l +
 * nom + hajm. Hajm ham kalitda: Samsung faylni qo'ng'iroq davomida yozadi, tugallanmagan
 * nusxa yakuniy yozuv bilan adashtirilmasin.
 */
export function callKey(r: Pick<CallRecording, 'relativePath' | 'displayName' | 'sizeBytes'>): string {
  return `${r.relativePath}${r.displayName}|${r.sizeBytes}`;
}

function utf8(s: string): Uint8Array {
  let enc: string;
  try {
    enc = encodeURIComponent(s);
  } catch {
    // Juft bo'lmagan surrogat - faqat kalit uchun, baribir deterministik.
    return Uint8Array.from(Array.from(s, (ch) => ch.charCodeAt(0) & 0xff));
  }
  const out: number[] = [];
  for (let i = 0; i < enc.length; i++) {
    if (enc[i] === '%') {
      out.push(parseInt(enc.slice(i + 1, i + 3), 16));
      i += 2;
    } else {
      out.push(enc.charCodeAt(i));
    }
  }
  return Uint8Array.from(out);
}

/** Egasi + kalitdan UUID (v4 ko'rinishida - server faqat UUID ekanini tekshiradi). */
export function callClientId(owner: string | null, key: string): string {
  const hex = sha256Hex(utf8(`barno-call|${owner ?? ''}|${key}`));
  const bytes = new Uint8Array(16);
  for (let i = 0; i < 16; i++) bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return uuidV4(() => bytes);
}

/**
 * Fayl oxirgi o'zgarishdan keyin shuncha vaqt "tinch" tursin - shundan keyingina yuboriladi.
 * NIMA UCHUN: Samsung faylni qo'ng'iroq DAVOMIDA yozadi; erta yuborilsa kesilgan yozuv ketadi,
 * tugagan fayl esa boshqa hajm (= boshqa kalit) bilan yana "yuborilmagan" bo'lib chiqadi.
 */
export const QUIET_MS = 60_000;

/**
 * Yozuv hali yozilayotgan bo'lishi mumkinmi (oxirgi o'zgarishdan QUIET_MS o'tmagan).
 * Uzoq kelajakdagi sana (noto'g'ri soat) - "yozilmoqda" emas, aks holda yozuv abadiy qulflanardi.
 */
export function isStillWriting(rec: Pick<CallRecording, 'dateMs'>, now: number): boolean {
  if (!(rec.dateMs > 0)) return false;
  const age = now - rec.dateMs;
  return age < QUIET_MS && age > -QUIET_MS;
}

/** `recordings/<clientId><ext>`: kengaytma turga mos - pleer (ExoPlayer) formatni shundan ham taniydi. */
export function extensionFor(contentType: AudioContentType): AudioExtension {
  return AUDIO_EXTENSIONS[contentType];
}

export type SendOutcome =
  | { kind: 'queued'; clientId: string }
  /** Navbatda allaqachon bor (yoki oldin yuborilgan) - qayta qo'shilmadi. */
  | { kind: 'already'; clientId: string }
  | { kind: 'unsupported' }
  /** Server chegarasidan katta (`maxBytes` - xabarda "150 MB dan katta" deyish uchun). */
  | { kind: 'too_large'; maxBytes: number }
  | { kind: 'missing' }
  /** Samsung hali yozmoqda (oxirgi o'zgarishdan 60 s o'tmagan) - birozdan keyin. */
  | { kind: 'not_ready' }
  | { kind: 'error'; code: CallImportErrorCode | 'queue' };

export interface SendOptions {
  /** actorId (callsStore.owner). */
  owner: string | null;
  language: Lang;
  /** Server cheklovi (`config.maxUploadBytes`); noma'lum bo'lsa null - server o'zi 413 qaytaradi. */
  maxBytes: number | null;
  t: TFn;
}

export interface CallSendDeps {
  queue: Pick<QueueStore, 'get' | 'insert'>;
  uploader: Pick<Uploader, 'runOnce'>;
  /** Native `copyToAppStorage`: ABSOLYUT yo'l qaytaradi. */
  copy(uri: string, destFileName: string): Promise<string>;
  /** Nusxani o'chirish (navbatga yozib bo'lmasa). */
  removeFile(uri: string): Promise<void>;
  markSent(key: string, clientId: string): void;
  toFileUri(path: string): string;
  now?: () => number;
}

const MIN_BYTES = 1;

/**
 * Hozir nusxalanayotgan clientId'lar: qo'lda "Yuborish" va avtomatik skan bir vaqtda
 * bir yozuvga tushsa, ikkinchisi ikkinchi nusxa olmaydi (navbatda hali qator yo'q payt).
 */
const copying = new Set<string>();

function errorCode(e: unknown): CallImportErrorCode {
  const code = e && typeof e === 'object' ? (e as { code?: unknown }).code : undefined;
  return typeof code === 'string' && code.startsWith('ERR_') ? (code as CallImportErrorCode) : 'ERR_IO';
}

/** Samsung yozgan qo'ng'iroqni navbatga qo'shadi (nusxa + qator + uploader turtkisi). */
export async function sendCallRecording(deps: CallSendDeps, rec: CallRecording, opts: SendOptions): Promise<SendOutcome> {
  const key = callKey(rec);
  const clientId = callClientId(opts.owner, key);
  if (!rec.contentType) return { kind: 'unsupported' };
  if (rec.sizeBytes < MIN_BYTES) return { kind: 'missing' };
  if (opts.maxBytes && rec.sizeBytes > opts.maxBytes) return { kind: 'too_large', maxBytes: opts.maxBytes };
  // Qo'lda ham, avtomatik ham bir xil qoida: yozilayotgan fayl ketmasin (kesilgan yozuv + takror yig'ilish).
  if (isStillWriting(rec, (deps.now ?? Date.now)())) return { kind: 'not_ready' };
  if (copying.has(clientId)) return { kind: 'already', clientId };
  copying.add(clientId);
  try {
    return await copyAndQueue(deps, rec, opts, key, clientId, rec.contentType);
  } finally {
    copying.delete(clientId);
  }
}

async function copyAndQueue(
  deps: CallSendDeps,
  rec: CallRecording,
  opts: SendOptions,
  key: string,
  clientId: string,
  contentType: AudioContentType,
): Promise<SendOutcome> {
  const now = deps.now ?? Date.now;
  if (await deps.queue.get(clientId)) {
    deps.markSent(key, clientId);
    return { kind: 'already', clientId };
  }

  let path: string;
  try {
    path = await deps.copy(rec.uri, `${clientId}${extensionFor(contentType)}`);
  } catch (e) {
    return { kind: 'error', code: errorCode(e) };
  }
  const fileUri = deps.toFileUri(path);
  const parsed = parseCallFileName(rec.displayName);
  const startMs = recordedAtMs(parsed, rec.dateMs || null, rec.durationMs, now());
  const endMs = rec.dateMs > 0 ? Math.max(rec.dateMs, startMs) : startMs + rec.durationMs;
  try {
    await deps.queue.insert(
      newQueueRow({
        clientId,
        fileUri,
        contentType,
        language: opts.language,
        template: 'auto',
        // Telefon qo'ng'irog'i - odatda ikki kishi: spikerlarni ajratish aniqroq.
        expectedSpeakers: 2,
        source: 'call',
        title: importTitle(opts.t, { ...parsed, looksLikeCall: true }, formatTime(startMs)),
        startedAt: new Date(startMs).toISOString(),
        endedAt: new Date(endMs).toISOString(),
        // Plaud ro'yxatida qo'ng'iroq bo'lgan kunga emas, yuborilgan kunga tushadi (`timeline.rowListedAt`).
        queuedAt: new Date(now()).toISOString(),
        durationSec: rec.durationMs > 0 ? Math.round(rec.durationMs / 10) / 100 : null,
        totalBytes: rec.sizeBytes,
        state: 'stopped',
      }),
    );
  } catch {
    // Qator yozilmadi - nusxa yetim qolmasin (keyingi urinish yangidan nusxalaydi).
    await deps.removeFile(fileUri).catch(() => {});
    return { kind: 'error', code: 'queue' };
  }
  deps.markSent(key, clientId);
  void deps.uploader.runOnce().catch(() => {});
  return { kind: 'queued', clientId };
}

/**
 * Tasdiq ekranidagi fayl: native `ImportMeta` (m4a/aac - Kotlin `readImportMeta`) yoki JS o'qigan
 * meta ("Audio yuklash" yozgan mp3/wav/ogg - native ularni tanimaydi). Tur - serverning beshta
 * turidan biri (`null` - qabul qilinmaydi).
 */
export type ImportFileMeta = Omit<ImportMeta, 'contentType'> & { contentType: AudioContentType | null };

export interface ImportSendDeps {
  queue: Pick<QueueStore, 'insert'>;
  /**
   * `imports/<nom>` ni `recordings/<clientId><ext>` ga ko'chiradi va file:// URI qaytaradi.
   * NIMA UCHUN ko'chirish: recordings/ dagi fayllar yuklangach o'chadi va chiqishda tozalanadi.
   */
  moveIntoRecordings(meta: ImportFileMeta, clientId: string, ext: AudioExtension): string;
  /** `imports/` dan olib tashlash (native nom - Kotlin `removeImport`, qolgani - JS): `.json` meta ham ketadi. */
  removeImport(fileName: string): boolean;
  newClientId(): string;
  now?: () => number;
}

/** "Ulashish -> Barno AI" bilan kelgan bitta faylni navbatga qo'shadi (uploader'ni chaqiruvchi turtadi). */
export async function sendImportedFile(deps: ImportSendDeps, meta: ImportFileMeta, opts: SendOptions): Promise<SendOutcome> {
  const now = deps.now ?? Date.now;
  if (!meta.contentType) return { kind: 'unsupported' };
  if (meta.sizeBytes < MIN_BYTES) return { kind: 'missing' };
  if (opts.maxBytes && meta.sizeBytes > opts.maxBytes) return { kind: 'too_large', maxBytes: opts.maxBytes };
  const clientId = deps.newClientId();
  let fileUri: string;
  try {
    fileUri = deps.moveIntoRecordings(meta, clientId, extensionFor(meta.contentType));
  } catch {
    return { kind: 'error', code: 'ERR_IO' };
  }
  const parsed = parseCallFileName(meta.displayName);
  const startMs = recordedAtMs(parsed, meta.dateMs, meta.durationMs, now());
  try {
    await deps.queue.insert(
      newQueueRow({
        clientId,
        fileUri,
        contentType: meta.contentType,
        language: opts.language,
        template: 'auto',
        expectedSpeakers: parsed.looksLikeCall ? 2 : null,
        source: 'share',
        // Sarlavha - fayl nomi o'zgarishsiz (ega qarori 2026-11-12): qo'ng'iroq yozuviga o'xshagan nom ham
        // "Qo'ng'iroq, 16:02" ga aylantirilmaydi. Nom - odam tanlagan narsa, server AI sarlavhasi bilan almashtirmaydi.
        // Asl nom noma'lum bo'lsa meta ichki nomni ("share_<n>_<i>_..." - native va JS bir xil) beradi: u sarlavha
        // emas - `null`, server AI sarlavhasini qo'yadi.
        title: meta.displayName === meta.fileName ? null : uploadTitle(meta.displayName),
        startedAt: new Date(startMs).toISOString(),
        endedAt: meta.durationMs > 0 ? new Date(startMs + meta.durationMs).toISOString() : null,
        // 8-noyabrdagi fayl bugun yuklansa - Plaud'da "Bugun" ostida (`timeline.rowListedAt`).
        queuedAt: new Date(now()).toISOString(),
        durationSec: meta.durationMs > 0 ? Math.round(meta.durationMs / 10) / 100 : null,
        totalBytes: meta.sizeBytes,
        state: 'stopped',
      }),
    );
  } catch {
    // Fayl allaqachon recordings/ da - chiqishda tozalanadi; foydalanuvchiga xato ko'rsatiladi.
    return { kind: 'error', code: 'queue' };
  }
  deps.removeImport(meta.fileName);
  return { kind: 'queued', clientId };
}

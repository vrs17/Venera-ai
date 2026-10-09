/**
 * Rezyumli, bo'lakli yuklovchi (spec 7.5). Toza mantiq: fetch (api), fayl
 * (FileAccess), hash va soat tashqaridan beriladi - shuning uchun to'liq
 * Jest'da tekshiriladi (`__tests__/uploader.test.ts`).
 *
 * Qadamlar:
 *  1. `POST /meetings` - clientId bo'yicha idempotent, server id doim tiklanadi.
 *  2. 4 MiB bo'lak `receivedBytes` dan, `X-Chunk-Sha256` bilan `PUT /audio?offset`.
 *     409 offset_mismatch -> serverning `receivedBytes` qabul qilinadi va davom.
 *  3. Hammasi yetganda `POST /complete` butun fayl sha256 bilan.
 *     409 sha_mismatch -> server faylni 0 ga qirqqan, 0 dan qayta.
 *  4. `upload.complete=true` -> `done`; lokal fayl HOZIR yoki `keepUntil` da o'chadi.
 *     Undan OLDIN fayl hech qachon o'chirilmaydi.
 *
 * Qoidalar: single-flight; xato -> backoff 5s*2^n (+-20%, 15 daq. tom);
 * 401 -> client o'zi bir marta yangilaydi, baribir bo'lmasa navbat to'xtaydi
 * (qatorlar saqlanadi); 413/415 -> `failed`, foydalanuvchiga ko'rsatiladi.
 *
 * Backoff O'ZI qayta qurollanadi: har ishlashdan keyin eng yaqin
 * `nextAttemptAt` ga bitta taymer qo'yiladi (ilova ekranda bo'lganda JS
 * taymeri ishlaydi; fonda esa ilova ochilishi, tarmoq qaytishi va
 * expo-background-task baribir chaqiradi). Aks holda bitta 5xx/timeout'dan
 * keyin yuklash tashqi hodisa bo'lmaguncha turib qolardi.
 *
 * 404 ma'lum server id bilan (server 72 soatlik tugallanmagan yuklashni
 * tozalagan yoki qator o'chirilgan): server id unutiladi va clientId bilan
 * qayta yaratiladi (clientId - idempotentlik kaliti; bayroq vaqtincha o'chiq
 * bo'lsa ham shu: `create` server holatini qaytaradi).
 */
import { ApiError, AuthRequiredError } from '@/api/client';
import type { MeetingsApi } from '@/api/meetings';
import type { Meeting } from '@/api/types';
import { Sha256 } from '@/lib/sha256';

import { backoffMs } from './backoff';
import { DEFAULT_CHUNK_BYTES, nextChunk } from './chunker';
import type { QueuePatch, QueueRow, QueueStore } from './queueStore';

export const DAY_MS = 24 * 60 * 60 * 1000;
/** Bitta ishga tushishda serverga moslashish (409) chegarasi - cheksiz aylanmaslik uchun. */
const MAX_RESYNCS = 6;
/** Butun-fayl sha mos kelmasa necha marta 0 dan qayta yuklanadi. */
const MAX_SHA_RESTARTS = 1;
/** Taxminiy davomiylik (crash'dan tiklangan, durationSec yo'q qator uchun). Server baribir o'zi o'lchaydi. */
const FALLBACK_BITRATE = 48_000;
/** Qayta qurollangan taymer bundan tez ishlamaydi (tor aylanish bo'lmasin). */
export const MIN_REARM_MS = 1000;
/** Butun-fayl hash'ida bir sinxron bo'lak (Hermes'da JIT yo'q - ~50-100 ms). */
export const HASH_SLICE_BYTES = 512 * 1024;

export interface FileAccess {
  /** Bayt hajmi, fayl yo'q bo'lsa null. */
  size(uri: string): Promise<number | null>;
  read(uri: string, offset: number, length: number): Promise<Uint8Array>;
  remove(uri: string): Promise<void>;
}

export interface UploaderDeps {
  store: QueueStore;
  api: Pick<MeetingsApi, 'create' | 'uploadPosition' | 'putChunk' | 'complete' | 'get'>;
  files: FileAccess;
  /** Bitta chunk sha256 hex (ilovada expo-crypto). */
  chunkSha256(bytes: Uint8Array): Promise<string>;
  now?: () => number;
  random?: () => number;
  /** Sozlama: lokal nusxani necha kun saqlash (0 yoki 7). */
  keepDays?: () => number;
  appVersion: string;
  device: string;
  /** Sessiya tugadi - ilova login ekraniga o'tadi, navbat saqlanadi. */
  onAuthRequired?: () => void;
  onUploaded?: (row: QueueRow, meeting: Meeting) => void;
  /**
   * Qatordagi yo'l yo'q bo'lsa tekshiriladigan kanonik yo'l (recordings/<clientId>.aac):
   * finalize faylni ko'chirib, qatorni yangilashga ulgurmay crash bo'lgan holat.
   */
  canonicalUri?: (clientId: string) => string;
  /** Uzun sinxron hash bo'laklari orasida UI'ga navbat (ilovada `yieldToUi`). */
  yieldToUi?: () => Promise<void>;
  /** Taymer (testda soxta). Bekor qilish funksiyasini qaytaradi. */
  schedule?: (fn: () => void, ms: number) => () => void;
}

export type RowOutcome = 'done' | 'retry' | 'failed' | 'auth' | 'skipped';

export interface Uploader {
  /** Single-flight: ishlayotgan bo'lsa o'sha va'dani qaytaradi va oxirida yana bir aylanadi. */
  runOnce(): Promise<void>;
  /** Failed qatorni qayta navbatga qo'yish (foydalanuvchi "Qayta urinish" bosganda). */
  retry(clientId: string): Promise<void>;
  isRunning(): boolean;
}

export function isPending(row: QueueRow): boolean {
  return row.state === 'stopped' || row.state === 'creating' || row.state === 'uploading' || row.state === 'completing';
}

function estimateDuration(bytes: number): number {
  return Math.round(((bytes * 8) / FALLBACK_BITRATE) * 100) / 100;
}

export function createUploader(deps: UploaderDeps): Uploader {
  const now = deps.now ?? Date.now;
  const random = deps.random ?? Math.random;
  const hashers = new Map<string, Sha256>();
  let running: Promise<void> | null = null;
  let again = false;
  let cancelTimer: (() => void) | null = null;
  const schedule =
    deps.schedule ??
    ((fn: () => void, ms: number) => {
      const h = setTimeout(fn, ms);
      return () => clearTimeout(h);
    });
  const pause = deps.yieldToUi ?? (() => Promise.resolve());

  const update = async (row: QueueRow, patch: QueuePatch): Promise<QueueRow> =>
    (await deps.store.update(row.clientId, patch)) ?? { ...row, ...patch };

  async function wholeFileSha(row: QueueRow, size: number, maxChunk: number): Promise<string> {
    const h = hashers.get(row.clientId);
    if (h && h.length === size) {
      hashers.delete(row.clientId);
      return h.hex();
    }
    // Crash'dan keyin yoki server bizni oldinga surgan - fayl qayta o'qiladi.
    // Sof TS hash: kichik bo'laklar va orada UI'ga navbat (3 soatlik fayl ~65 MB).
    const fresh = new Sha256();
    for (let off = 0; off < size; off += maxChunk) {
      const bytes = await deps.files.read(row.fileUri, off, Math.min(maxChunk, size - off));
      for (let i = 0; i < bytes.length; i += HASH_SLICE_BYTES) {
        fresh.update(bytes.subarray(i, Math.min(bytes.length, i + HASH_SLICE_BYTES)));
        await pause();
      }
    }
    hashers.delete(row.clientId);
    return fresh.hex();
  }

  function feedHasher(clientId: string, offset: number, bytes: Uint8Array): void {
    let h = hashers.get(clientId);
    if (!h && offset === 0) {
      h = new Sha256();
      hashers.set(clientId, h);
    }
    if (!h) return;
    if (h.length === offset) h.update(bytes);
    else if (h.length < offset) hashers.delete(clientId); // tuynuk - oxirida qayta hisoblanadi
  }

  async function finishDone(row: QueueRow, meeting: Meeting): Promise<RowOutcome> {
    const keepDays = Math.max(0, deps.keepDays?.() ?? 0);
    // Qator kamida 1 kun qoladi: ro'yxat/batafsil ekran lokal clientId -> server id ni topadi.
    const keepUntil = now() + Math.max(keepDays, 1) * DAY_MS;
    const done = await update(row, {
      state: 'done',
      serverId: meeting.id,
      receivedBytes: meeting.upload.receivedBytes,
      lastError: null,
      nextAttemptAt: null,
      keepUntil,
    });
    hashers.delete(row.clientId);
    if (keepDays === 0) {
      // Server audioni oldi (upload.complete=true) - endi va faqat endi o'chiramiz.
      await deps.files.remove(row.fileUri);
    }
    deps.onUploaded?.(done, meeting);
    return 'done';
  }

  async function fail(row: QueueRow, code: string): Promise<RowOutcome> {
    await update(row, { state: 'failed', lastError: code, nextAttemptAt: null });
    return 'failed';
  }

  async function scheduleRetry(row: QueueRow, err: unknown): Promise<RowOutcome> {
    const attempts = row.attempts + 1;
    let delay = backoffMs(attempts, random);
    if (err instanceof ApiError && err.retryAfterSec != null) delay = Math.max(delay, err.retryAfterSec * 1000);
    const code = err instanceof ApiError ? err.code : 'internal';
    await update(row, { attempts, nextAttemptAt: now() + delay, lastError: code });
    return 'retry';
  }

  async function handleError(row: QueueRow, err: unknown): Promise<RowOutcome> {
    if (err instanceof AuthRequiredError) {
      deps.onAuthRequired?.();
      return 'auth';
    }
    if (err instanceof ApiError) {
      if (err.status === 413 || err.status === 415) return fail(row, err.code);
      if (err.status === 404 && row.serverId) {
        // Server qatorni unutgan - eski id bilan har urinish yana 404 bo'lardi. Qaytadan yaratamiz.
        hashers.delete(row.clientId);
        const reset = await update(row, { serverId: null, receivedBytes: 0, state: 'stopped' });
        return scheduleRetry(reset, err);
      }
      if (err.status === 410) return fail(row, err.code);
    }
    return scheduleRetry(row, err);
  }

  /** Fayl hajmi; qatordagi yo'l yo'q bo'lsa kanonik yo'l (va qator tuzatiladi). */
  async function locate(row: QueueRow): Promise<{ row: QueueRow; size: number | null }> {
    const size = await deps.files.size(row.fileUri);
    if (size != null || !deps.canonicalUri) return { row, size };
    const alt = deps.canonicalUri(row.clientId);
    if (alt === row.fileUri) return { row, size };
    const altSize = await deps.files.size(alt);
    if (altSize == null) return { row, size };
    return { row: await update(row, { fileUri: alt }), size: altSize };
  }

  async function processRow(initial: QueueRow): Promise<RowOutcome> {
    let row = initial;
    try {
      const located = await locate(row);
      row = located.row;
      const size = located.size;
      if (size == null) return fail(row, 'file_missing');
      if (size === 0) return fail(row, 'empty_file');
      let maxChunk = DEFAULT_CHUNK_BYTES;

      if (!row.serverId) {
        row = await update(row, { state: 'creating', totalBytes: size });
        const res = await deps.api.create({
          clientId: row.clientId,
          title: row.title,
          recordedAt: row.startedAt,
          language: row.language,
          template: row.template,
          expectedSpeakers: row.expectedSpeakers,
          contentType: row.contentType,
          source: row.source,
          appVersion: deps.appVersion,
          device: deps.device,
        });
        const m = res.data;
        maxChunk = m.upload.maxChunkBytes || DEFAULT_CHUNK_BYTES;
        row = await update(row, { serverId: m.id, receivedBytes: m.upload.receivedBytes, state: 'uploading' });
        if (m.upload.complete) return finishDone(row, m);
      } else {
        // Resume: lokal receivedBytes eskirgan bo'lishi mumkin (crash) - serverdan so'raymiz.
        const pos = await deps.api.uploadPosition(row.serverId);
        maxChunk = pos.maxChunkBytes || DEFAULT_CHUNK_BYTES;
        if (pos.complete) return finishDone(row, await deps.api.get(row.serverId));
        row = await update(row, { receivedBytes: pos.receivedBytes, state: 'uploading', totalBytes: size });
      }

      const serverId = row.serverId as string;
      let resyncs = 0;
      let shaRestarts = 0;

      for (;;) {
        // ---- 2. bo'laklar
        let chunk = nextChunk(row.receivedBytes, size, maxChunk);
        while (chunk) {
          const bytes = await deps.files.read(row.fileUri, chunk.offset, chunk.length);
          const sha = await deps.chunkSha256(bytes);
          try {
            const res = await deps.api.putChunk(serverId, chunk.offset, bytes, sha);
            feedHasher(row.clientId, chunk.offset, bytes);
            row = await update(row, { receivedBytes: res.receivedBytes, lastError: null });
          } catch (e) {
            if (e instanceof ApiError && e.status === 409 && e.code === 'offset_mismatch' && typeof e.body?.receivedBytes === 'number') {
              if (++resyncs > MAX_RESYNCS) throw e;
              row = await update(row, { receivedBytes: e.body.receivedBytes });
            } else if (e instanceof ApiError && e.status === 409 && e.code === 'upload_closed') {
              // Oldingi /complete o'tgan, lekin javobi yo'qolgan (crash) - holatni serverdan olamiz.
              const m = await deps.api.get(serverId);
              if (m.upload.complete) return finishDone(row, m);
              throw e;
            } else {
              throw e;
            }
          }
          chunk = nextChunk(row.receivedBytes, size, maxChunk);
        }

        // ---- 3. complete
        row = await update(row, { state: 'completing' });
        const sha256 = await wholeFileSha(row, size, maxChunk);
        try {
          const res = await deps.api.complete(serverId, {
            totalBytes: size,
            sha256,
            durationSec: row.durationSec ?? estimateDuration(size),
            endedAt: row.endedAt ?? new Date(now()).toISOString(),
            marks: row.marks,
          });
          if (res.data.upload.complete) return finishDone(row, res.data);
          throw new ApiError(0, 'not_complete', 'Server yuklashni tugallanmagan deb qaytardi');
        } catch (e) {
          if (e instanceof ApiError && e.status === 409 && e.code === 'upload_incomplete') {
            if (++resyncs > MAX_RESYNCS) throw e;
            const rb = typeof e.body?.receivedBytes === 'number' ? e.body.receivedBytes : row.receivedBytes;
            row = await update(row, { receivedBytes: rb, state: 'uploading' });
            continue;
          }
          if (e instanceof ApiError && e.status === 409 && e.code === 'sha_mismatch') {
            // Server qism faylni 0 ga qirqdi (spec 3.2 #5) - 0 dan qayta yuklaymiz.
            if (++shaRestarts > MAX_SHA_RESTARTS) return fail(row, 'sha_mismatch');
            hashers.delete(row.clientId);
            row = await update(row, { receivedBytes: 0, state: 'uploading' });
            continue;
          }
          throw e;
        }
      }
    } catch (e) {
      return handleError(row, e);
    }
  }

  async function cleanup(rows: QueueRow[]): Promise<void> {
    const t = now();
    for (const r of rows) {
      if (r.state === 'done' && r.keepUntil != null && r.keepUntil <= t) {
        await deps.files.remove(r.fileUri);
        await deps.store.remove(r.clientId);
      }
    }
  }

  /** true - sessiya yo'q (auth), qolgan qatorlar o'tkazib yuborildi. */
  async function runAll(): Promise<boolean> {
    const rows = await deps.store.list();
    await cleanup(rows);
    for (const row of rows) {
      if (!isPending(row)) continue;
      if (row.nextAttemptAt != null && row.nextAttemptAt > now()) continue;
      const fresh = await deps.store.get(row.clientId);
      if (!fresh || !isPending(fresh)) continue;
      const outcome = await processRow(fresh);
      if (outcome === 'auth') return true; // sessiya yo'q - qolganlari ham o'tmaydi
    }
    return false;
  }

  function clearTimer(): void {
    cancelTimer?.();
    cancelTimer = null;
  }

  /** Eng yaqin `nextAttemptAt` ga bitta taymer (spec 7.5 backoff jadvali haqiqatan bajarilsin). */
  async function rearm(): Promise<void> {
    clearTimer();
    let next: number | null = null;
    for (const r of await deps.store.list()) {
      if (!isPending(r) || r.nextAttemptAt == null) continue;
      next = next == null ? r.nextAttemptAt : Math.min(next, r.nextAttemptAt);
    }
    if (next == null) return;
    cancelTimer = schedule(
      () => {
        cancelTimer = null;
        void runOnce().catch(() => {});
      },
      Math.max(MIN_REARM_MS, next - now()),
    );
  }

  function runOnce(): Promise<void> {
    if (running) {
      again = true;
      return running;
    }
    clearTimer();
    running = (async () => {
      let authStopped = false;
      do {
        again = false;
        authStopped = await runAll();
      } while (again); // runOnce ish paytida chaqirilgan (masalan, login) - yana bir aylanish
      // Sessiya yo'q bo'lsa taymer qo'yilmaydi - login yoki ilova ochilishi o'zi chaqiradi.
      if (!authStopped) await rearm();
    })().finally(() => {
      running = null;
    });
    return running;
  }

  return {
    runOnce,
    isRunning: () => running !== null,
    async retry(clientId) {
      const row = await deps.store.get(clientId);
      if (!row || (row.state !== 'failed' && !isPending(row))) return;
      // Eski versiya 404 ni `failed/not_found` qilgan: eski server id bilan qayta urinish yana 404.
      const forget = row.lastError === 'not_found';
      await deps.store.update(clientId, {
        state: row.serverId && !forget ? 'uploading' : 'stopped',
        attempts: 0,
        nextAttemptAt: null,
        lastError: null,
        ...(forget ? { serverId: null, receivedBytes: 0 } : {}),
      });
      if (forget) hashers.delete(clientId);
      await runOnce();
    },
  };
}

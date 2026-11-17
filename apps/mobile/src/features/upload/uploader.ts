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
 *
 * EGA (2026-11-16, `owner` berilganda - ilovada doim; kalit - Barno `actorId`). Qator faqat EGASI
 * kirgan holatda yuklanadi: telefon boshqa xodimga o'tsa (admin "hamma joydan chiqarish" yoki blokdan
 * keyin), oldingi odamning yuklanmagan yozuvi yangi odamning hisobiga tushmaydi - u qatorlarga
 * tegilmaydi, egasi qaytib kirganda yuklanadi. Server buni bilolmaydi: `create` (aktor, clientId)
 * bo'yicha, 404 esa "boshqa odamniki" ni "server tozalagan" dan ajratmaydi. Shuning uchun:
 *  - qat'iy ega (`owner`) faqat server o'sha sessiyani qabul qilganda yoziladi (`session.stamp`, shu yerda
 *    `create`/`uploadPosition` muvaffaqiyatidan keyin). Undan oldin - taxmin (`ownerHint`);
 *  - taxmin BOSHQA hisob (kirmasdan yoki tasdiqlanmagan sessiyada yozilgan, `UNKNOWN_OWNER` ham) -
 *    yuklanmaydi, `owner_unknown` bilan to'xtab unga ko'rinadi: yozuvni u o'zi yozgan bo'lsa «Qayta
 *    urinish» bilan o'ziga oladi. Taxmin qilingan hisob keyin kirsa - qaytadi;
 *  - taxminsiz egasiz qator (hech kim kirmagan telefonda yozilgan) kirgan odamga o'tadi; server id bo'lsa -
 *    faqat server uni SHU hisobniki deb tasdiqlasa (`uploadPosition` 200); 404 bo'lsa qayta yaratilmaydi,
 *    `owner_unknown` (odam o'zi "Qayta urinish" bossa - o'ziga oladi);
 *  - ega noma'lum sessiya (1.3.13 dan qolgan token) har ishlashdan oldin `prepare` (`session.identify`)
 *    bilan aniqlanadi; aniqlanmaguncha egali va taxminli qatorlarga tegilmaydi;
 *  - 404 dan keyin qayta yaratish va har `create` dan oldin ega YANA tekshiriladi (ish o'rtasida
 *    boshqa hisob kirgan bo'lsa qator unga o'tmaydi).
 */
import { ApiError, AuthRequiredError } from '@/api/client';
import type { MeetingsApi } from '@/api/meetings';
import type { AudioContentType, Meeting } from '@/api/types';
import { Sha256 } from '@/lib/sha256';

import { backoffMs } from './backoff';
import { DEFAULT_CHUNK_BYTES, nextChunk } from './chunker';
import { uploadableBy, type QueuePatch, type QueueRow, type QueueStore } from './queueStore';

export const DAY_MS = 24 * 60 * 60 * 1000;
/** Bitta ishga tushishda serverga moslashish (409) chegarasi - cheksiz aylanmaslik uchun. */
const MAX_RESYNCS = 6;
/** Butun-fayl sha mos kelmasa necha marta 0 dan qayta yuklanadi. */
const MAX_SHA_RESTARTS = 1;
/**
 * Taxminiy davomiylik (crash'dan tiklangan, durationSec yo'q qator uchun) - yozuvchining AAC
 * bitreyti. Server baribir o'zi o'lchaydi (`audio.measure`) va `null` ni ham oladi.
 */
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
  /**
   * Fayl hozir pleerda ochiqmi. keepDays=0 bo'lsa ham bunday fayl darhol o'chirilmaydi
   * (tinglash o'rtasida siljitish yiqilmasin) - `keepUntil` da tozalanadi.
   */
  fileInUse?: (uri: string) => boolean;
  appVersion: string;
  device: string;
  /**
   * Qo'ng'iroq yozuvining rozilik belgisi (`source: 'call'` qatorlar uchun so'raladi); `null` -
   * yuborilmaydi. Server uni yozuv yonida saqlaydi (AI agentga ko'chirish sharti).
   */
  callConsent?: () => { consentAt: string; consentVersion: string } | null;
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
  /**
   * Hozir kim kirgan (`session.owner()`). Berilsa qator faqat egasiga yuklanadi (yuqoridagi "EGA").
   * Berilmasa - eski xulq (hamma qator joriy sessiyaga).
   */
  owner?: () => Promise<string | null>;
  /**
   * Server tasdiqlagan sessiya hisobi (`session.stamp().owner`): egasiz qatorlarni so'rovsiz darhol shu
   * odamga bog'lash uchun. Berilmasa - qatorlar faqat server javobidan keyin bog'lanadi.
   */
  confirmedOwner?: () => Promise<string | null>;
  /** Har ishlashdan oldin (ilovada: egasi noma'lum sessiyani aniqlash). Xatosi yutiladi. */
  prepare?: () => Promise<void>;
}

/** Server tugallanmagan yuklashni unutgan (404 ma'lum id bilan) - qator 0 dan qayta yaratiladi. */
export const SERVER_RESET = 'server_reset';
/**
 * Egasiz eski qatorning server id si bu hisobda yo'q (404): kimniki ekani noma'lum - avtomatik qayta
 * yaratilmaydi (boshqa odamning yozuvi bo'lishi mumkin). "Qayta urinish" - odam o'zi oladi.
 */
export const OWNER_UNKNOWN = 'owner_unknown';

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

/**
 * Hajmdan davomiylik faqat bitreyti bizga ma'lum formatda (yozuvchi/qo'ng'iroq: AAC, MP4).
 * mp3/wav/ogg ("Audio yuklash") bitreyti har xil - 48 kbps bilan 100 MB WAV "4,6 soat" bo'lardi;
 * yolg'on son o'rniga `null` (server o'lchaydi).
 */
function estimateDuration(bytes: number, contentType: AudioContentType): number | null {
  if (contentType !== 'audio/aac' && contentType !== 'audio/mp4') return null;
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

  /** Hozir kirgan hisob; o'qib bo'lmasa null (null hech kimning qatoriga teng emas). */
  async function currentOwner(): Promise<string | null> {
    try {
      return (await deps.owner?.()) ?? null;
    } catch {
      return null;
    }
  }

  /** `owner` berilmagan (eski xulq) - hamma qator; berilgan - `uploadableBy` qoidasi. */
  const uploadable = (row: QueueRow, me: string | null | undefined): boolean => me === undefined || uploadableBy(row, me);

  /**
   * Egasiz qatorlar va `me` (har ishlashda, kutayotgani ham): taxmini BOSHQA hisob - yuklanmaydi,
   * `owner_unknown` bilan to'xtab ko'rinadi (qo'lda oladi). Taxmini yo'q yoki aynan `me` - shu sabab
   * to'xtagani qaytadi; server tasdiqlagan sessiyada (`confirmed`) darhol uniki bo'ladi, shunda sessiya
   * keyin tashqaridan tugasa ham u yozuvlar shu odamda qoladi (server id li qator - faqat server javobida).
   */
  async function adopt(rows: QueueRow[], me: string, confirmed: string | null): Promise<void> {
    for (const r of rows) {
      if (r.owner != null || r.state === 'done') continue;
      if (r.ownerHint != null && r.ownerHint !== me) {
        if (isPending(r)) await update(r, { state: 'failed', lastError: OWNER_UNKNOWN, nextAttemptAt: null });
        continue;
      }
      // Server id li qator faqat taxmini aynan shu hisob bo'lsa qaytadi (aks holda 404 - yana `owner_unknown`).
      const revive = r.state === 'failed' && r.lastError === OWNER_UNKNOWN && (!r.serverId || r.ownerHint === me);
      const claim = confirmed === me && !r.serverId;
      if (!revive && !claim) continue;
      await update(r, {
        ...(claim ? { owner: me, ownerHint: null } : {}),
        ...(revive ? { state: r.serverId ? 'uploading' : 'stopped', lastError: null, attempts: 0, nextAttemptAt: null } : {}),
      });
    }
  }

  /** Server shu so'rovni qabul qildi: egasiz qator endi so'rov paytidagi hisobniki (hisob almashmagan bo'lsa). */
  async function claimAfterServer(row: QueueRow, before: string | null | undefined): Promise<QueueRow> {
    if (!deps.owner || row.owner != null || before == null || !uploadableBy(row, before)) return row;
    if ((await currentOwner()) !== before) return row;
    return update(row, { owner: before, ownerHint: null });
  }

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
    if (keepDays === 0 && !deps.fileInUse?.(row.fileUri)) {
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

  async function scheduleRetry(row: QueueRow, err: unknown, codeOverride?: string): Promise<RowOutcome> {
    const attempts = row.attempts + 1;
    let delay = backoffMs(attempts, random);
    if (err instanceof ApiError && err.retryAfterSec != null) delay = Math.max(delay, err.retryAfterSec * 1000);
    const code = codeOverride ?? (err instanceof ApiError ? err.code : 'internal');
    await update(row, { attempts, nextAttemptAt: now() + delay, lastError: code });
    return 'retry';
  }

  async function handleError(row: QueueRow, err: unknown): Promise<RowOutcome> {
    if (err instanceof AuthRequiredError) {
      deps.onAuthRequired?.();
      return 'auth';
    }
    if (err instanceof ApiError) {
      // 422 `video_no_audio` (2026-11-17): videoda ovoz yo'q - qayta urinish befoyda.
      if (err.status === 413 || err.status === 415 || (err.status === 422 && err.code === 'video_no_audio')) return fail(row, err.code);
      if (err.status === 404 && row.serverId) {
        if (deps.owner) {
          // 404 "boshqa hisobniki" ham bo'lishi mumkin: faqat egasi aniq va hozir AYNAN u kirgan bo'lsa
          // qayta yaratamiz. Egasiz eski qator - to'xtaydi; ega boshqa (ish o'rtasida hisob almashgan) -
          // qatorga tegmaymiz, egasi qaytganda davom etadi.
          const now = await currentOwner();
          if (row.owner == null) {
            // Taxmin aynan shu hisob (u yozuv shu hisob tokeni ostida yozilgan va yaratilgan) - 404 = server
            // tozalagan: uniki qilib qayta yaratamiz. Taxminsiz yoki boshqaniki - kimniki noma'lum, to'xtaydi.
            if (now == null || row.ownerHint !== now) return fail(row, OWNER_UNKNOWN);
            row = await update(row, { owner: now, ownerHint: null });
          } else if (row.owner !== now) {
            return 'skipped';
          }
        }
        // Server qatorni unutgan - eski id bilan har urinish yana 404 bo'lardi. Qaytadan yaratamiz.
        hashers.delete(row.clientId);
        const reset = await update(row, { serverId: null, receivedBytes: 0, state: 'stopped' });
        // Alohida kod: `not_found` + server id'siz qator UI'da "bo'lim yoqilmagan" deb
        // o'qilardi (yolg'on). Bu esa oddiy kutish - keyingi urinish qayta yaratadi.
        return scheduleRetry(reset, err, SERVER_RESET);
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
        const before = deps.owner ? await currentOwner() : undefined;
        // `create` qatorni SHU so'rov tokenining hisobiga yozadi - ega boshqa bo'lsa yubormaymiz.
        if (before !== undefined && !uploadableBy(row, before)) return 'skipped';
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
          ...(row.source === 'call' ? (deps.callConsent?.() ?? {}) : {}),
        });
        const m = res.data;
        maxChunk = m.upload.maxChunkBytes || DEFAULT_CHUNK_BYTES;
        row = await update(row, { serverId: m.id, receivedBytes: m.upload.receivedBytes, state: 'uploading' });
        row = await claimAfterServer(row, before);
        if (m.upload.complete) return finishDone(row, m);
      } else {
        // Resume: lokal receivedBytes eskirgan bo'lishi mumkin (crash) - serverdan so'raymiz.
        const knownId = row.serverId;
        const before = deps.owner ? await currentOwner() : undefined;
        const pos = await deps.api.uploadPosition(knownId);
        // Egasiz qator: server bu yig'ilishni so'rov paytidagi hisobniki deb qaytardi - endi uniki.
        row = await claimAfterServer(row, before);
        maxChunk = pos.maxChunkBytes || DEFAULT_CHUNK_BYTES;
        if (pos.complete) return finishDone(row, await deps.api.get(knownId));
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
            durationSec: row.durationSec ?? estimateDuration(size, row.contentType),
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
    // Avval `prepare` (egasi noma'lum sessiyani aniqlash): u '?' taxminli qatorlarni shu hisobga o'tkazadi -
    // navbat SHUNDAN KEYIN o'qiladi, aks holda `adopt` eski nusxadagi '?' ni "boshqa hisob" deb to'xtatardi.
    if (deps.prepare) {
      try {
        await deps.prepare();
      } catch {
        /* masalan, tarmoq yo'q - keyingi ishlashda yana */
      }
    }
    let rows = await deps.store.list();
    await cleanup(rows);
    const me = deps.owner ? await currentOwner() : undefined;
    if (me) {
      let confirmed: string | null = null;
      try {
        confirmed = (await deps.confirmedOwner?.()) ?? null;
      } catch {
        confirmed = null;
      }
      await adopt(rows, me, confirmed);
      rows = await deps.store.list();
    }
    for (const row of rows) {
      if (!isPending(row)) continue;
      if (!uploadable(row, me)) continue; // boshqa odamning yozuvi - egasi kirganda
      if (row.nextAttemptAt != null && row.nextAttemptAt > now()) continue;
      const fresh = await deps.store.get(row.clientId);
      if (!fresh || !isPending(fresh) || !uploadable(fresh, me)) continue;
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
    const me = deps.owner ? await currentOwner() : undefined;
    for (const r of await deps.store.list()) {
      // Boshqa odamning qatori taymer qo'ymaydi (aks holda o'tgan `nextAttemptAt` har soniyada uyg'otardi).
      if (!isPending(r) || r.nextAttemptAt == null || !uploadable(r, me)) continue;
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
      const me = deps.owner ? await currentOwner() : undefined;
      // Boshqa odamning qatori (ro'yxatda ko'rinmaydi) - qo'lda ham boshqa hisobga yuborilmaydi.
      if (me !== undefined && row.owner != null && row.owner !== me) return;
      // Egasiz qatorni kirgan odam O'ZI bosdi - endi uniki: kimniki noma'lum deb to'xtagan (`owner_unknown`)
      // yoki serverga hali yetmagan yozuv. Server id li boshqa holat (masalan "server javob bermadi") -
      // bosish uni egalamaydi: server tasdiqlaganda (`uploadPosition`) bog'lanadi.
      const claim = me != null && row.owner == null && (row.lastError === OWNER_UNKNOWN || !row.serverId);
      // Eski versiya 404 ni `failed/not_found` qilgan: eski server id bilan qayta urinish yana 404.
      // `owner_unknown` + server id: u id boshqa hisobniki bo'lishi mumkin - 0 dan shu odamning hisobida.
      const forget = row.lastError === 'not_found' || (claim && row.lastError === OWNER_UNKNOWN);
      await deps.store.update(clientId, {
        state: row.serverId && !forget ? 'uploading' : 'stopped',
        attempts: 0,
        nextAttemptAt: null,
        lastError: null,
        ...(forget ? { serverId: null, receivedBytes: 0 } : {}),
        ...(claim ? { owner: me, ownerHint: null } : {}),
      });
      if (forget) hashers.delete(clientId);
      await runOnce();
    },
  };
}

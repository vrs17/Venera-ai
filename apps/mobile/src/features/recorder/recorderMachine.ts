/**
 * Yozuvchi holat mashinasi (spec 2.3 "States") - TOZA funksiya, React va
 * native'siz; `__tests__/recorderMachine.test.ts` to'liq tekshiradi.
 *
 *   idle -> preparing -> recording <-> paused -> stopping -> stopped
 *   xatolar: permission_denied | notifications_denied | disk_low | not_foreground | recorder_error
 *
 * Vaqt chizig'i: davomiylik va belgilar vaqti PAUZANI HISOBGA OLMAYDI -
 * audio faylda pauza yo'q, demak "12:34" belgisi fayldagi 12:34 ga to'g'ri
 * kelishi kerak.
 */
import type { EntrySource, Mark } from '@/api/types';
import type { QueuePatch, QueueRow } from '@/features/upload/queueStore';

import { addMark } from './marks';

export type RecorderStatus =
  | 'idle'
  | 'preparing'
  | 'recording'
  | 'paused'
  | 'stopping'
  | 'stopped'
  | 'permission_denied'
  | 'notifications_denied'
  | 'disk_low'
  | 'not_foreground'
  | 'recorder_error';

export type RecorderErrorStatus = 'permission_denied' | 'notifications_denied' | 'disk_low' | 'not_foreground' | 'recorder_error';

export interface RecorderState {
  status: RecorderStatus;
  clientId: string | null;
  source: EntrySource;
  /** Yozuv boshlangan devor vaqti (ms) - `recordedAt`. */
  startedAt: number | null;
  /** Oldingi (pauzagacha bo'lgan) qismlar yig'indisi, ms. */
  accumulatedMs: number;
  /** Joriy qism boshlangan devor vaqti; pauzada null. */
  segmentStartedAt: number | null;
  marks: Mark[];
  /** Maksimal davomiylik, soniya (config `maxMinutes*60`). */
  maxSec: number;
  /** Limitdan 10 daqiqa oldingi ogohlantirish ko'rsatildimi. */
  warned: boolean;
  /** Limit tufayli avtomatik to'xtadi. */
  autoStopped: boolean;
  endedAt: number | null;
  error: string | null;
}

export type RecorderEvent =
  | { type: 'PREPARE'; clientId: string; maxSec: number; source: EntrySource }
  | { type: 'STARTED'; at: number }
  | { type: 'PAUSE'; at: number }
  | { type: 'RESUME'; at: number }
  | { type: 'MARK'; at: number; note?: string | null }
  | { type: 'TICK'; at: number }
  | { type: 'STOP'; at: number; auto?: boolean }
  | { type: 'STOPPED' }
  | { type: 'FAIL'; status: RecorderErrorStatus; message?: string; at?: number }
  | { type: 'RESET' };

export const WARN_BEFORE_SEC = 10 * 60;
export const DEFAULT_MAX_SEC = 180 * 60;

export const initialRecorderState: RecorderState = {
  status: 'idle',
  clientId: null,
  source: 'app',
  startedAt: null,
  accumulatedMs: 0,
  segmentStartedAt: null,
  marks: [],
  maxSec: DEFAULT_MAX_SEC,
  warned: false,
  autoStopped: false,
  endedAt: null,
  error: null,
};

export function isActive(s: RecorderState): boolean {
  return s.status === 'recording' || s.status === 'paused' || s.status === 'preparing' || s.status === 'stopping';
}

/** Yozuv vaqt chizig'idagi joriy davomiylik (pauza chiqarilgan), ms. */
export function elapsedMs(s: RecorderState, now: number): number {
  const running = s.segmentStartedAt != null ? Math.max(0, now - s.segmentStartedAt) : 0;
  return s.accumulatedMs + running;
}

export type LimitState = 'ok' | 'warn' | 'limit';

export function limitState(s: RecorderState, now: number): LimitState {
  const sec = elapsedMs(s, now) / 1000;
  if (sec >= s.maxSec) return 'limit';
  if (sec >= s.maxSec - WARN_BEFORE_SEC) return 'warn';
  return 'ok';
}

export function reduce(s: RecorderState, e: RecorderEvent): RecorderState {
  switch (e.type) {
    case 'PREPARE':
      // Idempotent: yozuv ketayotgan bo'lsa ikkinchi deep link hech narsa qilmaydi.
      if (isActive(s)) return s;
      return { ...initialRecorderState, status: 'preparing', clientId: e.clientId, maxSec: e.maxSec, source: e.source };

    case 'STARTED':
      if (s.status !== 'preparing') return s;
      return { ...s, status: 'recording', startedAt: e.at, segmentStartedAt: e.at, accumulatedMs: 0 };

    case 'PAUSE':
      if (s.status !== 'recording') return s;
      return { ...s, status: 'paused', accumulatedMs: elapsedMs(s, e.at), segmentStartedAt: null };

    case 'RESUME':
      if (s.status !== 'paused') return s;
      return { ...s, status: 'recording', segmentStartedAt: e.at };

    case 'MARK':
      if (s.status !== 'recording' && s.status !== 'paused') return s;
      return { ...s, marks: addMark(s.marks, elapsedMs(s, e.at) / 1000, e.note) };

    case 'TICK': {
      if (s.status !== 'recording') return s;
      const ls = limitState(s, e.at);
      if (ls === 'warn' && !s.warned) return { ...s, warned: true };
      return s;
    }

    case 'STOP':
      if (s.status !== 'recording' && s.status !== 'paused') return s;
      return {
        ...s,
        status: 'stopping',
        accumulatedMs: Math.min(elapsedMs(s, e.at), s.maxSec * 1000 + 30_000),
        segmentStartedAt: null,
        endedAt: e.at,
        autoStopped: !!e.auto,
      };

    case 'STOPPED':
      if (s.status !== 'stopping') return s;
      return { ...s, status: 'stopped' };

    case 'FAIL':
      return {
        ...s,
        status: e.status,
        error: e.message ?? null,
        accumulatedMs: e.at != null ? elapsedMs(s, e.at) : s.accumulatedMs,
        segmentStartedAt: null,
        endedAt: e.at ?? s.endedAt,
      };

    case 'RESET':
      if (isActive(s)) return s;
      return { ...initialRecorderState };
  }
}

/** expo-audio `recordingStatusUpdate` hodisasining bizga kerak qismi. */
export interface NativeRecorderEvent {
  isFinished?: boolean;
  hasError?: boolean;
  error?: string | null;
  url?: string | null;
}

/**
 * Native hodisa nimani bildiradi (expo-audio 57 Android, AudioRecorder.kt):
 *  - `limit`    - MAX_FILESIZE_REACHED: `{isFinished, hasError:true, error:null, url}`.
 *                 Bu XATO EMAS - native hajm chegarasi (preset `maxFileSize`) yozuvni
 *                 o'zi to'xtatgan; fayl yaroqli, avtomatik to'xtash sifatida saqlanadi.
 *  - `error`    - MediaRecorder onError (`error` matni bor, `url` yo'q) yoki stop() xatosi.
 *  - `finished` - bildirishnomadagi Stop: `{isFinished, hasError:false, url}`.
 *  - `ignore`   - yozuv ketmayapti (o'zimiz chaqirgan stop() ning aks-sadosi va h.k.).
 */
export type NativeEventKind = 'ignore' | 'finished' | 'limit' | 'error';

export function classifyNativeEvent(e: NativeRecorderEvent, status: RecorderStatus): NativeEventKind {
  if (status !== 'recording' && status !== 'paused') return 'ignore';
  if (e.hasError) return !e.error && e.url ? 'limit' : 'error';
  if (e.isFinished) return 'finished';
  return 'ignore';
}

/** Davomiylik soniyada, 2 xona (server formati). */
export function durationSec(s: RecorderState, now: number): number {
  return Math.round(elapsedMs(s, now) / 10) / 100;
}

/**
 * Crash tiklash (spec 2.3): ishga tushganda `recording` holatidagi, lekin
 * hozir faol yozuvchiga tegishli bo'lmagan qatorlar `stopped` bo'ladi.
 * Fayl yaroqli ADTS - server haqiqiy davomiylikni o'zi o'lchaydi.
 */
export function recoverRows(rows: QueueRow[], activeClientId: string | null, nowIso: string): { clientId: string; patch: QueuePatch }[] {
  return rows
    .filter((r) => r.state === 'recording' && r.clientId !== activeClientId)
    .map((r) => ({ clientId: r.clientId, patch: { state: 'stopped' as const, endedAt: r.endedAt ?? nowIso } }));
}

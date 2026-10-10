/**
 * Oflayn yuklash navbati (spec 7.5): `recordings` jadvali, expo-sqlite.
 *
 * NIMA UCHUN SQLite: yozuv boshlanishidan OLDIN qator yoziladi (crash
 * safety, spec 2.3). Ilova o'ldirilsa ham fayl yo'li va metadata qoladi,
 * keyingi ishga tushishda yuklash davom etadi.
 *
 * Interfeys orqali: uploader va recorder testlarda `queueStore.memory.ts`
 * bilan ishlaydi (bir xil shartnoma, `__tests__/queueStore.test.ts`).
 */
import type { AudioContentType, EntrySource, Lang, Mark, TemplateId } from '@/api/types';

export type QueueState = 'recording' | 'stopped' | 'creating' | 'uploading' | 'completing' | 'done' | 'failed';

export interface QueueRow {
  clientId: string;
  fileUri: string;
  /**
   * Yozuvchi doim `audio/aac` (ADTS) yozadi; import qilingan qo'ng'iroq / ulashilgan fayl
   * (`source` = `call` | `share`, 2026-10-10) ko'pincha `audio/mp4` (.m4a). Server ikkalasini qabul qiladi.
   */
  contentType: AudioContentType;
  language: Lang;
  template: TemplateId;
  expectedSpeakers: number | null;
  source: EntrySource;
  title: string | null;
  state: QueueState;
  serverId: string | null;
  receivedBytes: number;
  totalBytes: number | null;
  durationSec: number | null;
  marks: Mark[];
  startedAt: string; // ISO UTC
  endedAt: string | null;
  attempts: number;
  nextAttemptAt: number | null; // epoch ms
  lastError: string | null;
  keepUntil: number | null; // epoch ms; done qatorning lokal fayli shu vaqtgacha
}

export type QueuePatch = Partial<Omit<QueueRow, 'clientId'>>;

export interface QueueStore {
  insert(row: QueueRow): Promise<void>;
  get(clientId: string): Promise<QueueRow | null>;
  update(clientId: string, patch: QueuePatch): Promise<QueueRow | null>;
  /** startedAt bo'yicha o'sish tartibida (eski yozuv birinchi yuklanadi). */
  list(): Promise<QueueRow[]>;
  remove(clientId: string): Promise<void>;
  clear(): Promise<void>;
  subscribe(listener: () => void): () => void;
}

export function newQueueRow(p: Pick<QueueRow, 'clientId' | 'fileUri' | 'language' | 'template' | 'expectedSpeakers' | 'source' | 'startedAt'> & Partial<QueueRow>): QueueRow {
  return {
    contentType: 'audio/aac',
    title: null,
    state: 'recording',
    serverId: null,
    receivedBytes: 0,
    totalBytes: null,
    durationSec: null,
    marks: [],
    endedAt: null,
    attempts: 0,
    nextAttemptAt: null,
    lastError: null,
    keepUntil: null,
    ...p,
  };
}

// ------------------------------------------------------------------ SQLite

/** expo-sqlite `SQLiteDatabase` ning bizga kerak qismi (testda soxtalashtirish oson). */
export interface SqlDb {
  execAsync(source: string): Promise<void>;
  runAsync(source: string, ...params: (string | number | null)[]): Promise<unknown>;
  getAllAsync<T>(source: string, ...params: (string | number | null)[]): Promise<T[]>;
  getFirstAsync<T>(source: string, ...params: (string | number | null)[]): Promise<T | null>;
}

const COLUMNS = [
  'clientId',
  'fileUri',
  'contentType',
  'language',
  'template',
  'expectedSpeakers',
  'source',
  'title',
  'state',
  'serverId',
  'receivedBytes',
  'totalBytes',
  'durationSec',
  'marks',
  'startedAt',
  'endedAt',
  'attempts',
  'nextAttemptAt',
  'lastError',
  'keepUntil',
] as const;

export const CREATE_SQL = `
CREATE TABLE IF NOT EXISTS recordings (
  clientId TEXT PRIMARY KEY NOT NULL,
  fileUri TEXT NOT NULL,
  contentType TEXT NOT NULL,
  language TEXT NOT NULL,
  template TEXT NOT NULL,
  expectedSpeakers INTEGER,
  source TEXT NOT NULL,
  title TEXT,
  state TEXT NOT NULL,
  serverId TEXT,
  receivedBytes INTEGER NOT NULL DEFAULT 0,
  totalBytes INTEGER,
  durationSec REAL,
  marks TEXT NOT NULL DEFAULT '[]',
  startedAt TEXT NOT NULL,
  endedAt TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  nextAttemptAt INTEGER,
  lastError TEXT,
  keepUntil INTEGER
);`;

type DbRow = Record<(typeof COLUMNS)[number], string | number | null>;

function toDb(row: QueueRow): (string | number | null)[] {
  return COLUMNS.map((c) => {
    const v = row[c];
    if (c === 'marks') return JSON.stringify(v ?? []);
    return (v ?? null) as string | number | null;
  });
}

function fromDb(r: DbRow): QueueRow {
  let marks: Mark[] = [];
  try {
    marks = JSON.parse(String(r.marks ?? '[]'));
  } catch {
    marks = [];
  }
  return {
    clientId: String(r.clientId),
    fileUri: String(r.fileUri),
    // Noma'lum qiymat (qo'lda buzilgan DB) serverda 415 bo'lardi - eski standart turga qaytamiz.
    contentType: r.contentType === 'audio/mp4' ? 'audio/mp4' : 'audio/aac',
    language: r.language as Lang,
    template: r.template as TemplateId,
    expectedSpeakers: r.expectedSpeakers == null ? null : Number(r.expectedSpeakers),
    source: r.source as EntrySource,
    title: r.title == null ? null : String(r.title),
    state: r.state as QueueState,
    serverId: r.serverId == null ? null : String(r.serverId),
    receivedBytes: Number(r.receivedBytes ?? 0),
    totalBytes: r.totalBytes == null ? null : Number(r.totalBytes),
    durationSec: r.durationSec == null ? null : Number(r.durationSec),
    marks,
    startedAt: String(r.startedAt),
    endedAt: r.endedAt == null ? null : String(r.endedAt),
    attempts: Number(r.attempts ?? 0),
    nextAttemptAt: r.nextAttemptAt == null ? null : Number(r.nextAttemptAt),
    lastError: r.lastError == null ? null : String(r.lastError),
    keepUntil: r.keepUntil == null ? null : Number(r.keepUntil),
  };
}

export async function createSqliteQueueStore(db: SqlDb): Promise<QueueStore> {
  await db.execAsync(CREATE_SQL);
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach((l) => l());

  const store: QueueStore = {
    async insert(row) {
      await db.runAsync(
        `INSERT OR REPLACE INTO recordings (${COLUMNS.join(',')}) VALUES (${COLUMNS.map(() => '?').join(',')})`,
        ...toDb(row),
      );
      notify();
    },
    async get(clientId) {
      const r = await db.getFirstAsync<DbRow>('SELECT * FROM recordings WHERE clientId = ?', clientId);
      return r ? fromDb(r) : null;
    },
    async update(clientId, patch) {
      const cur = await store.get(clientId);
      if (!cur) return null;
      const next: QueueRow = { ...cur, ...patch, clientId };
      const cols = COLUMNS.filter((c) => c !== 'clientId');
      const values = toDb(next).slice(1);
      await db.runAsync(`UPDATE recordings SET ${cols.map((c) => `${c} = ?`).join(', ')} WHERE clientId = ?`, ...values, clientId);
      notify();
      return next;
    },
    async list() {
      const rows = await db.getAllAsync<DbRow>('SELECT * FROM recordings ORDER BY startedAt ASC');
      return rows.map(fromDb);
    },
    async remove(clientId) {
      await db.runAsync('DELETE FROM recordings WHERE clientId = ?', clientId);
      notify();
    },
    async clear() {
      await db.runAsync('DELETE FROM recordings');
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  return store;
}

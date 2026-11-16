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
import { isAudioContentType } from '@/lib/audioTypes';

export type QueueState = 'recording' | 'stopped' | 'creating' | 'uploading' | 'completing' | 'done' | 'failed';

export interface QueueRow {
  clientId: string;
  fileUri: string;
  /**
   * Yozuvchi doim `audio/aac` (ADTS) yozadi; import qilingan qo'ng'iroq / ulashilgan fayl
   * (`source` = `call` | `share`, 2026-10-10) ko'pincha `audio/mp4` (.m4a); Plaud'dagi "Audio yuklash"
   * (2026-11-09) yana `audio/mpeg`, `audio/wav`, `audio/ogg`. Server beshalasini qabul qiladi.
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
  /**
   * Navbatga qo'shilgan vaqt (ISO UTC) - tayyor fayl (`call`, `share`) uchun: Plaud ro'yxatida u shu
   * kunga tushadi, faylning `startedAt` (asl yozilgan vaqti) ga emas (2026-11-11). Ilovadagi yozuvda va
   * 1.3.8 dan oldingi qatorlarda `null` - unda `startedAt`.
   */
  queuedAt: string | null;
  /**
   * Yozuv KIMNIKI - yozilgan paytda kirgan Barno hisobining `actorId` si (`session.owner()`). Yuklovchi
   * faqat shu hisob kirganda yuklaydi, ro'yxat ham faqat unga ko'rsatadi (2026-11-16: telefon boshqa
   * xodimga o'tsa, oldingi odamning yuklanmagan yozuvi yangi odamning hisobiga tushmasin).
   * `null` - kirmasdan yozilgan (unda `ownerHint`) yoki 1.3.14 dan oldingi qator.
   */
  owner: string | null;
  /**
   * Kirmasdan yozilgan yozuvning TAXMINIY egasi - telefondagi oxirgi hisob (`session.lastOwner()`).
   * O'sha hisob kirsa yozuv avtomatik uniki bo'ladi; boshqa odam kirsa yuklanmaydi, lekin unga
   * ko'rinadi va «Qayta urinish» bilan o'ziga oladi (yozuvni u yozgan bo'lishi mumkin). `null` - taxmin yo'q.
   */
  ownerHint: string | null;
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
    queuedAt: null,
    owner: null,
    ownerHint: null,
    ...p,
  };
}

/**
 * `ownerHint` qiymati: yozilgan paytda token bor edi, lekin uning hisobi noma'lum (1.3.13 dan qolgan token)
 * yoki qator 1.3.13 navbatidan qolgan. Hech bir `actorId` ga teng emas - avtomatik yuklanmaydi; o'sha
 * sessiyaning hisobi aniqlansa (`resolveUnknownOwner`) unga o'tadi, aks holda kirgan odam qo'lda oladi.
 */
export const UNKNOWN_OWNER = '?';

/** Yangi navbat qatori kimniki: qat'iy ega yoki faqat taxmin (`session.stamp`). */
export interface OwnerStamp {
  owner: string | null;
  ownerHint: string | null;
}

/**
 * Navbat qatoriga EGA qo'yadigan o'ram: `insert` da (qatorda ega ham taxmin ham bo'lmasa) `session.stamp()`
 * yoziladi - server tasdiqlagan sessiyada qat'iy ega, aks holda taxmin. Hamma qo'shish joylari (yozuvchi,
 * qo'ng'iroq importi, "Audio yuklash") shu orqali o'tadi - har birida alohida eslash shart emas.
 */
export function withOwner<S extends QueueStore>(store: S, who: { stamp(): Promise<OwnerStamp> }): S {
  return {
    ...store,
    async insert(row: QueueRow) {
      if (row.owner != null || row.ownerHint != null) return store.insert(row);
      let stamp: OwnerStamp = { owner: null, ownerHint: null };
      try {
        stamp = await who.stamp();
      } catch {
        // O'qib bo'lmadi - kimniki noma'lum: hech kimga avtomatik berilmaydi.
        stamp = { owner: null, ownerHint: UNKNOWN_OWNER };
      }
      await store.insert({ ...row, owner: stamp.owner, ownerHint: stamp.ownerHint });
    },
  };
}

/**
 * Egasi noma'lum sessiyaning hisobi aniqlandi (`session` `onOwnerLearned`): `UNKNOWN_OWNER` taxminli qatorlar
 * shu hisobga taxmin bo'lib o'tadi (yuklovchi server qabul qilganda qat'iy qiladi); shu sabab to'xtatilgani qaytadi.
 */
export async function resolveUnknownOwner(store: QueueStore, owner: string): Promise<void> {
  for (const r of await store.list()) {
    if (r.owner != null || r.ownerHint !== UNKNOWN_OWNER) continue;
    const held = r.state === 'failed' && r.lastError === 'owner_unknown';
    await store.update(r.clientId, {
      ownerHint: owner,
      ...(held ? { state: r.serverId ? 'uploading' : 'stopped', lastError: null, attempts: 0, nextAttemptAt: null } : {}),
    });
  }
}

/** Ro'yxatda `viewer` ga ko'rinadimi: egasiz (kirmasdan yozilgan yoki eski) yoki aynan uniki. */
export function belongsTo(row: Pick<QueueRow, 'owner'>, viewer: string | null): boolean {
  return row.owner == null || row.owner === viewer;
}

/** `me` sessiyasida AVTOMATIK yuklanadimi: uniki yoki egasiz va taxmini yo'q/u. */
export function uploadableBy(row: Pick<QueueRow, 'owner' | 'ownerHint'>, me: string | null): boolean {
  if (row.owner != null) return row.owner === me;
  return row.ownerHint == null || row.ownerHint === me;
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
  'queuedAt',
  'owner',
  'ownerHint',
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
  keepUntil INTEGER,
  queuedAt TEXT,
  owner TEXT,
  ownerHint TEXT
);`;

/**
 * `CREATE_SQL` dan keyin qo'shilgan ustunlar: eski telefondagi jadvalga (`CREATE TABLE IF NOT EXISTS` uni
 * o'zgartirmaydi) ochilishda qo'shiladi. Faqat bo'sh qoldirsa bo'ladigan ustun (eski qatorda `NULL`).
 */
export const ADDED_COLUMNS: readonly { name: (typeof COLUMNS)[number]; sql: string; after?: string }[] = [
  // 1.3.8: tayyor fayl Plaud ro'yxatida navbatga qo'shilgan kuniga tushadi.
  { name: 'queuedAt', sql: 'ALTER TABLE recordings ADD COLUMN queuedAt TEXT' },
  // 1.3.14: qator egasi (telefon boshqa xodimga o'tsa yozuv oldingi egasida qoladi).
  { name: 'owner', sql: 'ALTER TABLE recordings ADD COLUMN owner TEXT' },
  {
    name: 'ownerHint',
    sql: 'ALTER TABLE recordings ADD COLUMN ownerHint TEXT',
    // 1.3.13 dan qolgan yuklanmagan qatorlar kimniki - noma'lum (`UNKNOWN_OWNER`): kirgan sessiya hisobi
    // aniqlansa unga o'tadi, aks holda keyingi kirgan odam qo'lda oladi (avtomatik emas).
    after: `UPDATE recordings SET ownerHint = '${UNKNOWN_OWNER}' WHERE owner IS NULL AND state != 'done'`,
  },
];

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
    // Beshta tur o'zgarmay qaytadi. Noma'lum qiymat (qo'lda buzilgan DB) serverda 415 bo'lardi -
    // yozuvchining standart turiga qaytamiz.
    contentType: isAudioContentType(r.contentType) ? r.contentType : 'audio/aac',
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
    queuedAt: r.queuedAt == null ? null : String(r.queuedAt),
    owner: r.owner == null || r.owner === '' ? null : String(r.owner),
    ownerHint: r.ownerHint == null || r.ownerHint === '' ? null : String(r.ownerHint),
  };
}

export async function createSqliteQueueStore(db: SqlDb): Promise<QueueStore> {
  await db.execAsync(CREATE_SQL);
  const have = new Set((await db.getAllAsync<{ name: string }>('PRAGMA table_info(recordings)')).map((c) => c.name));
  for (const col of ADDED_COLUMNS) {
    if (have.has(col.name)) continue;
    await db.execAsync(col.sql);
    if (col.after) await db.execAsync(col.after);
  }
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

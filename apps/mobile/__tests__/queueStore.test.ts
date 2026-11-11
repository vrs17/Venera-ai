/**
 * QueueStore shartnomasi: xotiradagi nusxa va SQLite nusxasi bir xil
 * ishlashi kerak. SQLite Node'ning o'rnatilgan `node:sqlite` moduli orqali
 * (expo-sqlite bilan bir xil SQL) tekshiriladi.
 */
import { CREATE_SQL, createSqliteQueueStore, newQueueRow, type QueueStore, type SqlDb } from '@/features/upload/queueStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';

type Params = (string | number | null)[];

function nodeSqliteDb(): SqlDb | null {
  let DatabaseSync: new (p: string) => {
    exec(sql: string): void;
    prepare(sql: string): { run(...p: Params): unknown; all(...p: Params): unknown[]; get(...p: Params): unknown };
  };
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    ({ DatabaseSync } = require('node:sqlite'));
  } catch {
    return null;
  }
  const db = new DatabaseSync(':memory:');
  return {
    execAsync: async (sql) => db.exec(sql),
    runAsync: async (sql, ...p) => db.prepare(sql).run(...p),
    getAllAsync: async <T,>(sql: string, ...p: Params) => db.prepare(sql).all(...p) as T[],
    getFirstAsync: async <T,>(sql: string, ...p: Params) => (db.prepare(sql).get(...p) as T | undefined) ?? null,
  };
}

const base = (id: string, startedAt: string) =>
  newQueueRow({
    clientId: id,
    fileUri: `file:///doc/recordings/${id}.aac`,
    language: 'uz',
    template: 'auto',
    expectedSpeakers: 3,
    source: 'launcher',
    startedAt,
  });

const impls: [string, () => Promise<QueueStore | null>][] = [
  ['memory', async () => createMemoryQueueStore()],
  [
    'sqlite',
    async () => {
      const db = nodeSqliteDb();
      return db ? createSqliteQueueStore(db) : null;
    },
  ],
];

describe.each(impls)('QueueStore (%s)', (_name, make) => {
  it('inserts, reads, updates and orders rows by startedAt', async () => {
    const store = await make();
    if (!store) return; // node:sqlite yo'q (eski Node) - memory baribir tekshiriladi
    await store.insert(base('b', '2026-10-09T07:00:00Z'));
    await store.insert(base('a', '2026-10-09T06:00:00Z'));
    expect((await store.list()).map((r) => r.clientId)).toEqual(['a', 'b']);

    const a = await store.get('a');
    expect(a).toMatchObject({ state: 'recording', receivedBytes: 0, expectedSpeakers: 3, marks: [], serverId: null });

    const updated = await store.update('a', {
      state: 'uploading',
      serverId: 'srv',
      receivedBytes: 4194304,
      totalBytes: 9000000,
      marks: [{ t: 1.5, note: 'muhim' }],
      nextAttemptAt: 123,
    });
    expect(updated).toMatchObject({ clientId: 'a', state: 'uploading', serverId: 'srv' });
    expect(await store.get('a')).toMatchObject({
      state: 'uploading',
      serverId: 'srv',
      receivedBytes: 4194304,
      totalBytes: 9000000,
      marks: [{ t: 1.5, note: 'muhim' }],
      nextAttemptAt: 123,
      source: 'launcher',
    });
    expect(await store.update('missing', { state: 'done' })).toBeNull();
  });

  it('returns copies (callers cannot mutate stored rows) and notifies subscribers', async () => {
    const store = await make();
    if (!store) return;
    const listener = jest.fn();
    const unsub = store.subscribe(listener);
    await store.insert(base('a', '2026-10-09T06:00:00Z'));
    const r = (await store.get('a'))!;
    r.marks.push({ t: 1, note: null });
    expect((await store.get('a'))!.marks).toEqual([]);
    await store.update('a', { state: 'stopped' });
    await store.remove('a');
    expect(listener).toHaveBeenCalledTimes(3);
    unsub();
    await store.insert(base('b', '2026-10-09T06:00:00Z'));
    expect(listener).toHaveBeenCalledTimes(3);
  });

  it('removes and clears', async () => {
    const store = await make();
    if (!store) return;
    await store.insert(base('a', '2026-10-09T06:00:00Z'));
    await store.insert(base('b', '2026-10-09T06:00:01Z'));
    await store.remove('a');
    expect((await store.list()).map((r) => r.clientId)).toEqual(['b']);
    await store.clear();
    expect(await store.list()).toEqual([]);
  });

  it('keeps every server audio type (aac, mp4, mp3, wav, ogg) through insert, update and reads', async () => {
    const store = await make();
    if (!store) return;
    const types = ['audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/wav', 'audio/ogg'] as const;
    for (let i = 0; i < types.length; i++) await store.insert({ ...base(`t${i}`, `2026-11-09T06:00:0${i}Z`), contentType: types[i] });
    expect((await store.list()).map((r) => r.contentType)).toEqual([...types]);
    await store.update('t2', { state: 'uploading', receivedBytes: 10 });
    expect(await store.get('t2')).toMatchObject({ contentType: 'audio/mpeg', state: 'uploading' });
  });

  it("keeps queuedAt (tayyor fayl Plaud'da qo'shilgan kuniga tushadi); default null", async () => {
    const store = await make();
    if (!store) return;
    await store.insert({ ...base('f', '2026-11-08T08:46:00Z'), source: 'share', queuedAt: '2026-11-11T05:22:00Z' });
    await store.insert(base('r', '2026-11-11T04:00:00Z'));
    expect(await store.get('f')).toMatchObject({ source: 'share', startedAt: '2026-11-08T08:46:00Z', queuedAt: '2026-11-11T05:22:00Z' });
    expect((await store.get('r'))?.queuedAt).toBeNull();
    await store.update('f', { state: 'uploading' });
    expect((await store.get('f'))?.queuedAt).toBe('2026-11-11T05:22:00Z');
  });
});

describe('QueueStore (sqlite) content type safety', () => {
  it('a corrupted contentType falls back to the recorder type instead of a certain 415', async () => {
    const db = nodeSqliteDb();
    if (!db) return;
    const store = await createSqliteQueueStore(db);
    await store.insert({ ...base('x', '2026-11-09T06:00:00Z'), contentType: 'audio/flac' as never });
    expect((await store.get('x'))?.contentType).toBe('audio/aac');
  });
});

describe('QueueStore (sqlite) upgrade from an older app', () => {
  it("1.3.7 dagi jadvalga queuedAt ustuni qo'shiladi: eski qatorlar joyida (queuedAt null), yangisi yoziladi", async () => {
    const db = nodeSqliteDb();
    if (!db) return;
    const oldSql = CREATE_SQL.replace(',\n  queuedAt TEXT', '');
    expect(oldSql).not.toContain('queuedAt');
    await db.execAsync(oldSql);
    await db.runAsync(
      "INSERT INTO recordings (clientId, fileUri, contentType, language, template, source, state, startedAt) VALUES ('old', 'file:///o.aac', 'audio/aac', 'uz', 'auto', 'call', 'stopped', '2026-11-01T08:00:00Z')",
    );
    const store = await createSqliteQueueStore(db);
    expect(await store.get('old')).toMatchObject({ clientId: 'old', source: 'call', queuedAt: null, marks: [] });
    await store.insert({ ...base('new', '2026-11-08T08:46:00Z'), source: 'share', queuedAt: '2026-11-11T05:22:00Z' });
    expect((await store.get('new'))?.queuedAt).toBe('2026-11-11T05:22:00Z');
    // Ikkinchi ochilish: ustun bor - qayta qo'shilmaydi (xato bermaydi).
    const again = await createSqliteQueueStore(db);
    expect((await again.list()).map((r) => r.clientId)).toEqual(['old', 'new']);
  });
});

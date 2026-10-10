/**
 * QueueStore shartnomasi: xotiradagi nusxa va SQLite nusxasi bir xil
 * ishlashi kerak. SQLite Node'ning o'rnatilgan `node:sqlite` moduli orqali
 * (expo-sqlite bilan bir xil SQL) tekshiriladi.
 */
import { createSqliteQueueStore, newQueueRow, type QueueStore, type SqlDb } from '@/features/upload/queueStore';
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
});

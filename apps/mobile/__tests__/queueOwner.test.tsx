/**
 * Navbat qatorining EGASI (2026-11-16): telefon boshqa xodimga o'tsa (admin "hamma joydan chiqarish",
 * blok, qurilma tokeni muddati), oldingi odamning yuklanmagan yozuvi yangi odamning hisobiga tushmasin.
 *
 * Soxta server har hisobni alohida ko'radi (haqiqiy server kabi): `create` (hisob, clientId) bo'yicha,
 * boshqa hisobning yig'ilishi - 404. Shuning uchun "noto'g'ri hisobga yuklandi" bu yerda ko'rinadi.
 * Ega kaliti - Barno `actorId` (JWT `sub` emas: bitta odamning `sub` i kirish yo'liga qarab o'zgaradi).
 */
import { render, screen, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';

import { ApiClient, ApiError, AuthRequiredError } from '@/api/client';
import { actorKey, createSession } from '@/features/auth/session';
import { createTokenStore, KEYS, memoryKV } from '@/features/auth/tokenStore';
import { belongsTo, newQueueRow, resolveUnknownOwner, UNKNOWN_OWNER, uploadableBy, withOwner, type QueueRow } from '@/features/upload/queueStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import { createUploader, OWNER_UNKNOWN, type FileAccess, type UploaderDeps } from '@/features/upload/uploader';
import { useQueueRows } from '@/features/upload/useQueue';

import { fakeServices, Providers } from './fixtures/fakeServices';
import { fakeFetch } from './fixtures/fakeFetch';
import { jwt } from './fixtures/jwt';
import { deviceResponse, loginResponse, meeting } from './fixtures/server';

const CHUNK = 1000;
const SIZE = 2500;
const NOW = Date.parse('2026-11-16T06:00:00Z');

interface ServerRec {
  id: string;
  owner: string;
  clientId: string;
  received: number;
  complete: boolean;
}

/** Hisoblarni ajratadigan soxta server. `current` - so'rov qaysi hisob tokeni bilan ketadi. */
class Accounts {
  current: string | null = 'A';
  recs = new Map<string, ServerRec>();
  calls: { op: string; as: string | null; id?: string }[] = [];
  private n = 0;

  private json(m: ServerRec) {
    return meeting({
      id: m.id,
      clientId: m.clientId,
      status: m.complete ? 'uploaded' : 'uploading',
      upload: { receivedBytes: m.received, totalBytes: m.complete ? m.received : null, maxChunkBytes: CHUNK, complete: m.complete },
    });
  }

  private own(id: string): ServerRec {
    const m = this.recs.get(id);
    if (!m || m.owner !== this.current) throw new ApiError(404, 'not_found', 'Not Found');
    return m;
  }

  private who(): string {
    if (this.current == null) throw new AuthRequiredError();
    return this.current;
  }

  seed(owner: string, clientId: string, received: number): string {
    const id = `m-${owner}-${++this.n}`;
    this.recs.set(id, { id, owner, clientId, received, complete: false });
    return id;
  }

  ownersOf(clientId: string): string[] {
    return [...this.recs.values()].filter((m) => m.clientId === clientId).map((m) => m.owner);
  }

  api: UploaderDeps['api'] = {
    create: (async (body: { clientId: string }) => {
      const as = this.who();
      this.calls.push({ op: 'create', as });
      let m = [...this.recs.values()].find((r) => r.owner === as && r.clientId === body.clientId);
      if (!m) m = this.recs.get(this.seed(as, body.clientId, 0))!;
      return { data: this.json(m), created: true };
    }) as unknown as UploaderDeps['api']['create'],
    uploadPosition: (async (id: string) => {
      this.calls.push({ op: 'position', as: this.current, id });
      const m = this.own(id);
      return { receivedBytes: m.received, maxChunkBytes: CHUNK, complete: m.complete };
    }) as unknown as UploaderDeps['api']['uploadPosition'],
    putChunk: (async (id: string, offset: number, bytes: Uint8Array) => {
      this.calls.push({ op: 'put', as: this.current, id });
      const m = this.own(id);
      m.received = offset + bytes.length;
      return { receivedBytes: m.received };
    }) as unknown as UploaderDeps['api']['putChunk'],
    complete: (async (id: string) => {
      this.calls.push({ op: 'complete', as: this.current, id });
      const m = this.own(id);
      m.complete = true;
      return { data: this.json(m) };
    }) as unknown as UploaderDeps['api']['complete'],
    get: (async (id: string) => this.json(this.own(id))) as unknown as UploaderDeps['api']['get'],
  };
}

/** Har yozuv fayli joyida (SIZE bayt), o'chirilgunicha. */
function files(): FileAccess {
  const removed = new Set<string>();
  const bytes = new Uint8Array(SIZE).fill(7);
  return {
    size: async (uri) => (removed.has(uri) ? null : SIZE),
    read: async (_uri, offset, length) => bytes.slice(offset, offset + length),
    remove: async (uri) => {
      removed.add(uri);
    },
  };
}

function rec(id: string, over: Partial<QueueRow> = {}): QueueRow {
  return newQueueRow({
    clientId: id,
    fileUri: `file:///doc/recordings/${id}.aac`,
    language: 'uz',
    template: 'auto',
    expectedSpeakers: null,
    source: 'tile',
    startedAt: '2026-11-16T05:00:00.000Z',
    state: 'stopped',
    durationSec: 60,
    endedAt: '2026-11-16T05:01:00.000Z',
    ...over,
  });
}

function setup(
  rows: QueueRow[],
  owner?: () => Promise<string | null>,
  extra: { confirmed?: () => Promise<string | null>; prepare?: () => Promise<void> } = {},
) {
  const server = new Accounts();
  const store = createMemoryQueueStore(rows);
  const timers: { ms: number; cancelled: boolean }[] = [];
  const uploader = createUploader({
    store,
    api: server.api,
    files: files(),
    chunkSha256: async () => 'x',
    now: () => NOW,
    random: () => 0.5,
    keepDays: () => 0,
    appVersion: '1.3.14',
    device: 'SM-S921B',
    owner: owner ?? (async () => server.current),
    confirmedOwner: extra.confirmed,
    prepare: extra.prepare,
    schedule: (_fn, ms) => {
      const t = { ms, cancelled: false };
      timers.push(t);
      return () => {
        t.cancelled = true;
      };
    },
  });
  return { server, store, uploader, armed: () => timers.filter((t) => !t.cancelled) };
}

describe('uploader: recordings stay with their owner', () => {
  it("another person's unsent recording is never created under the new account; it uploads when the owner returns", async () => {
    const s = setup([rec('c1', { owner: 'A' })]);
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(s.server.calls).toEqual([]);
    expect(await s.store.get('c1')).toMatchObject({ owner: 'A', state: 'stopped', serverId: null, lastError: null });

    s.server.current = 'A';
    await s.uploader.runOnce();
    expect(await s.store.get('c1')).toMatchObject({ owner: 'A', state: 'done' });
    expect(s.server.ownersOf('c1')).toEqual(['A']);
  });

  it("a half-uploaded recording of A is left alone while B is signed in (no 404 reset, no re-create)", async () => {
    const s = setup([]);
    const id = s.server.seed('A', 'c2', 1000);
    await s.store.insert(rec('c2', { owner: 'A', state: 'uploading', serverId: id, receivedBytes: 1000 }));
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(s.server.calls).toEqual([]);
    expect(await s.store.get('c2')).toMatchObject({ serverId: id, receivedBytes: 1000, state: 'uploading', owner: 'A' });

    s.server.current = 'A';
    await s.uploader.runOnce();
    expect(s.server.calls.filter((c) => c.op === 'put').every((c) => c.as === 'A')).toBe(true);
    expect(await s.store.get('c2')).toMatchObject({ state: 'done', serverId: id });
    expect(s.server.ownersOf('c2')).toEqual(['A']);
  });

  it('account switches in the middle of a run: the 404 under the new account does not move the row to it', async () => {
    let calls = 0;
    // Navbat A bilan boshlandi, so'rov esa allaqachon B tokeni bilan ketdi.
    const s = setup([], async () => (calls++ === 0 ? 'A' : 'B'));
    const id = s.server.seed('A', 'c3', 1000);
    await s.store.insert(rec('c3', { owner: 'A', state: 'uploading', serverId: id, receivedBytes: 1000 }));
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(s.server.calls.map((c) => c.op)).toEqual(['position']);
    expect(await s.store.get('c3')).toMatchObject({ serverId: id, owner: 'A', state: 'uploading' });
    expect(s.server.ownersOf('c3')).toEqual(['A']);
  });

  it('a row without an owner (recorded before anyone signed in, or from 1.3.13) goes to the person who signs in', async () => {
    const s = setup([rec('c4')]);
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(await s.store.get('c4')).toMatchObject({ owner: 'B', state: 'done' });
    expect(s.server.ownersOf('c4')).toEqual(['B']);
  });

  it("an old ownerless row with a server id is kept only when the server confirms it is this account's", async () => {
    const s = setup([]);
    const mine = s.server.seed('B', 'c5', 1000);
    await s.store.insert(rec('c5', { state: 'uploading', serverId: mine, receivedBytes: 1000 }));
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(await s.store.get('c5')).toMatchObject({ owner: 'B', state: 'done', serverId: mine });
  });

  it("an old ownerless row whose server id is someone else's stops (owner_unknown); only an explicit Retry takes it", async () => {
    const s = setup([]);
    const theirs = s.server.seed('A', 'c6', 1000);
    await s.store.insert(rec('c6', { state: 'uploading', serverId: theirs, receivedBytes: 1000 }));
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(await s.store.get('c6')).toMatchObject({ state: 'failed', lastError: OWNER_UNKNOWN, owner: null, serverId: theirs });
    expect(s.server.calls.map((c) => c.op)).toEqual(['position']);
    expect(s.server.ownersOf('c6')).toEqual(['A']);

    // Odam o'zi "Qayta urinish" ni bosdi - yozuv endi uniki, 0 dan uning hisobida.
    await s.uploader.retry('c6');
    expect(await s.store.get('c6')).toMatchObject({ owner: 'B', state: 'done' });
    expect(s.server.ownersOf('c6').sort()).toEqual(['A', 'B']);
  });

  it("someone else's row never arms the retry timer (no wake-up every second)", async () => {
    const s = setup([rec('c7', { owner: 'A', nextAttemptAt: NOW - 5000, attempts: 2, lastError: 'network' })]);
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(s.armed()).toEqual([]);
    expect(s.server.calls).toEqual([]);
  });

  it("retry() on someone else's row does nothing", async () => {
    const s = setup([rec('c8', { owner: 'A', state: 'failed', lastError: 'network' })]);
    s.server.current = 'B';
    await s.uploader.retry('c8');
    expect(await s.store.get('c8')).toMatchObject({ owner: 'A', state: 'failed', lastError: 'network' });
    expect(s.server.calls).toEqual([]);
  });

  it('recorded while signed out: the hinted account gets it automatically', async () => {
    const s = setup([rec('h1', { ownerHint: 'A' })]);
    s.server.current = 'A';
    await s.uploader.runOnce();
    expect(await s.store.get('h1')).toMatchObject({ owner: 'A', state: 'done' });
    expect(s.server.ownersOf('h1')).toEqual(['A']);
  });

  it("recorded while signed out, then someone else signs in: not uploaded, shown as owner_unknown; Retry makes it theirs", async () => {
    const s = setup([rec('h2', { ownerHint: 'A' })]);
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(s.server.calls).toEqual([]);
    expect(await s.store.get('h2')).toMatchObject({ owner: null, ownerHint: 'A', state: 'failed', lastError: OWNER_UNKNOWN });

    // B shu yozuvni o'zi yozgan - "Qayta urinish".
    await s.uploader.retry('h2');
    expect(await s.store.get('h2')).toMatchObject({ owner: 'B', ownerHint: null, state: 'done' });
    expect(s.server.ownersOf('h2')).toEqual(['B']);
  });

  it('a held owner_unknown row comes back by itself when the hinted account signs in', async () => {
    const s = setup([rec('h3', { ownerHint: 'A' })]);
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect((await s.store.get('h3'))?.state).toBe('failed');
    s.server.current = 'A';
    await s.uploader.runOnce();
    expect(await s.store.get('h3')).toMatchObject({ owner: 'A', state: 'done', lastError: null });
    expect(s.server.ownersOf('h3')).toEqual(['A']);
  });

  it('session whose account is not known yet (token from 1.3.13): only old ownerless rows upload, owned and hinted rows wait', async () => {
    const s = setup([rec('u1'), rec('u2', { owner: 'A' }), rec('u3', { ownerHint: 'A' })], async () => null);
    s.server.current = 'A';
    await s.uploader.runOnce();
    expect(s.server.ownersOf('u1')).toEqual(['A']);
    expect((await s.store.get('u1'))?.owner).toBeNull();
    expect(s.server.ownersOf('u2')).toEqual([]);
    expect(s.server.ownersOf('u3')).toEqual([]);
    expect(await s.store.get('u3')).toMatchObject({ state: 'stopped', lastError: null });
  });

  it('ownerless rows waiting on backoff are tied right away to a session the server has confirmed (a later remote sign-out cannot move them)', async () => {
    let s: ReturnType<typeof setup>;
    s = setup([rec('w1', { nextAttemptAt: NOW + 60_000, attempts: 1, lastError: 'network' })], undefined, {
      confirmed: async () => s.server.current,
    });
    s.server.current = 'A';
    await s.uploader.runOnce();
    expect(s.server.calls).toEqual([]); // hali vaqti emas
    expect((await s.store.get('w1'))?.owner).toBe('A');
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect((await s.store.get('w1'))?.owner).toBe('A');
    expect(s.server.ownersOf('w1')).toEqual([]);
  });

  it('not confirmed by the server yet: ownerless rows are not tied early; they become theirs only when the server accepts an upload', async () => {
    const s = setup([rec('w2', { nextAttemptAt: NOW + 60_000, attempts: 1, lastError: 'network' })], undefined, {
      confirmed: async () => null,
    });
    s.server.current = 'A';
    await s.uploader.runOnce();
    expect((await s.store.get('w2'))?.owner).toBeNull();
  });

  it("Retry on a 'server did not respond' card does not claim an ownerless row that has someone's server id", async () => {
    const s = setup([]);
    const theirs = s.server.seed('A', 'r1', 1000);
    await s.store.insert(rec('r1', { state: 'uploading', serverId: theirs, receivedBytes: 1000, lastError: 'timeout', attempts: 1 }));
    s.server.current = 'B';
    await s.uploader.retry('r1');
    // Server B uchun 404 berdi - egasi noma'lum, qayta yaratilmadi.
    expect(await s.store.get('r1')).toMatchObject({ owner: null, state: 'failed', lastError: OWNER_UNKNOWN, serverId: theirs });
    expect(s.server.ownersOf('r1')).toEqual(['A']);
  });

  it("rows whose account is unknown ('?') never upload by themselves, not even for a signed-in account", async () => {
    const s = setup([rec('q1', { ownerHint: UNKNOWN_OWNER })]);
    s.server.current = 'B';
    await s.uploader.runOnce();
    expect(s.server.calls).toEqual([]);
    expect(await s.store.get('q1')).toMatchObject({ state: 'failed', lastError: OWNER_UNKNOWN });
  });

  it('prepare runs before every upload run (identify for a 1.3.13 session), and its failure does not stop uploads', async () => {
    const prepare = jest.fn(async () => {
      throw new Error('offline');
    });
    const s = setup([rec('p1', { owner: 'A' })], undefined, { prepare });
    await s.uploader.runOnce();
    expect(prepare).toHaveBeenCalledTimes(1);
    expect((await s.store.get('p1'))?.state).toBe('done');
  });

  it('the same person signing back in uploads their own recording', async () => {
    const s = setup([rec('c9', { owner: 'A' })]);
    s.server.current = null; // sessiya tugagan: kutadi
    await s.uploader.runOnce();
    expect((await s.store.get('c9'))?.state).not.toBe('done');
    s.server.current = 'A';
    await s.uploader.runOnce();
    expect(await s.store.get('c9')).toMatchObject({ owner: 'A', state: 'done' });
  });
});

describe('withOwner / belongsTo / uploadableBy', () => {
  it('writes what session.stamp() says; a row that already has an owner or hint is kept; a failing stamp means unknown', async () => {
    let next: { owner: string | null; ownerHint: string | null } | 'boom' = { owner: 'A', ownerHint: null };
    const store = withOwner(createMemoryQueueStore(), {
      stamp: async () => {
        if (next === 'boom') throw new Error('x');
        return next;
      },
    });
    await store.insert(rec('r1'));
    await store.insert(rec('r2', { owner: 'Z' }));
    next = { owner: null, ownerHint: 'A' };
    await store.insert(rec('r3'));
    next = { owner: null, ownerHint: null };
    await store.insert(rec('r4'));
    next = 'boom';
    await store.insert(rec('r5'));
    expect((await store.list()).map((r) => [r.clientId, r.owner, r.ownerHint])).toEqual([
      ['r1', 'A', null],
      ['r2', 'Z', null],
      ['r3', null, 'A'],
      ['r4', null, null],
      ['r5', null, UNKNOWN_OWNER],
    ]);
  });

  it("resolveUnknownOwner: '?' rows move to the learned account as a hint, and held ones come back", async () => {
    const store = createMemoryQueueStore([
      rec('k1', { ownerHint: UNKNOWN_OWNER }),
      rec('k2', { ownerHint: UNKNOWN_OWNER, state: 'failed', lastError: OWNER_UNKNOWN }),
      rec('k3', { ownerHint: 'B' }),
      rec('k4', { owner: 'C' }),
    ]);
    await resolveUnknownOwner(store, 'A');
    expect((await store.list()).map((r) => [r.clientId, r.owner, r.ownerHint, r.state, r.lastError])).toEqual([
      ['k1', null, 'A', 'stopped', null],
      ['k2', null, 'A', 'stopped', null],
      ['k3', null, 'B', 'stopped', null],
      ['k4', 'C', null, 'stopped', null],
    ]);
  });

  it('belongsTo (list): ownerless rows show to anyone; owned rows only to their owner', () => {
    expect(belongsTo({ owner: null }, 'B')).toBe(true);
    expect(belongsTo({ owner: null }, null)).toBe(true);
    expect(belongsTo({ owner: 'B' }, 'B')).toBe(true);
    expect(belongsTo({ owner: 'A' }, 'B')).toBe(false);
    expect(belongsTo({ owner: 'A' }, null)).toBe(false);
  });

  it("uploadableBy (automatic upload): own rows, and ownerless rows whose hint is empty or this account", () => {
    expect(uploadableBy({ owner: 'B', ownerHint: null }, 'B')).toBe(true);
    expect(uploadableBy({ owner: 'A', ownerHint: null }, 'B')).toBe(false);
    expect(uploadableBy({ owner: null, ownerHint: null }, 'B')).toBe(true);
    expect(uploadableBy({ owner: null, ownerHint: 'B' }, 'B')).toBe(true);
    expect(uploadableBy({ owner: null, ownerHint: 'A' }, 'B')).toBe(false);
    expect(uploadableBy({ owner: null, ownerHint: 'A' }, null)).toBe(false);
    expect(uploadableBy({ owner: null, ownerHint: null }, null)).toBe(true);
  });
});

describe('session.owner / lastOwner / identify', () => {
  const as = (actorId: number, token: string) => ({ ...loginResponse, token, user: { ...loginResponse.user, actorId } });

  function make(initial: Record<string, string> = {}, onOwnerLearned?: (o: string) => void) {
    const kv = memoryKV(initial);
    let refresh: () => Promise<unknown> = async () => {
      throw new ApiError(401, 'invalid_device_token', 'Sessiya yakunlangan');
    };
    let register: () => Promise<unknown> = async () => deviceResponse;
    const api = {
      login: jest.fn(async () => loginResponse),
      logout: jest.fn(async () => ({ status: 'OK' })),
      registerDevice: jest.fn(async () => register()),
      deviceSession: jest.fn(async () => refresh()),
      revokeDevice: jest.fn(async () => ({ status: 'OK' })),
    };
    const session = createSession({ store: createTokenStore(kv), authApi: api as never, now: () => NOW, onOwnerLearned });
    return {
      kv,
      session,
      onRefresh: (f: () => Promise<unknown>) => (refresh = f),
      onRegister: (f: () => Promise<unknown>) => (register = f),
    };
  }
  const device = { deviceName: 'x', platform: 'android' as const, appVersion: '1.3.14' };

  it('actorKey: the Barno account number as text', () => {
    expect(actorKey({ actorId: 7 })).toBe('7');
    expect(actorKey(null)).toBeNull();
    expect(actorKey({ actorId: Number.NaN })).toBeNull();
  });

  it('is the signed-in account number; after a remote sign-out only the last account remains; a wiping logout clears it', async () => {
    const s = make();
    expect(await s.session.owner()).toBeNull();
    await s.session.loginWith(as(7, 'jwt-7'), device);
    expect(await s.session.owner()).toBe('7');
    expect(await s.session.lastOwner()).toBe('7');

    // Admin "hamma joydan chiqarish": qurilma sessiyasi 401 - token (va uning egasi) o'chadi, oxirgi hisob qoladi.
    await s.session.refreshToken().catch(() => {});
    expect(s.kv.data.has(KEYS.token)).toBe(false);
    expect(await s.session.owner()).toBeNull();
    expect(await s.session.lastOwner()).toBe('7');

    await s.session.logout(async () => {});
    expect(await s.session.lastOwner()).toBeNull();
    expect(s.kv.data.has(KEYS.owner)).toBe(false);
  });

  it('the same person keeps the same owner whichever way they sign in (password vs BRB-Tech ID: different sub, same account)', async () => {
    const s = make();
    await s.session.loginWith(as(7, jwt({ sub: 'aziz@brb.uz', exp: 2e9 })), device);
    s.onRefresh(async () => as(7, jwt({ sub: 'kc-uuid-aziz', exp: 2e9 })));
    await s.session.refreshToken();
    expect(await s.session.owner()).toBe('7');
    expect(await s.session.lastOwner()).toBe('7');
  });

  it("'Reconnect' (logout without wiping) keeps the last account, so later recordings stay with them", async () => {
    const s = make();
    await s.session.loginWith(as(7, 'jwt-7'), device);
    await s.session.logout();
    expect(await s.session.owner()).toBeNull();
    expect(await s.session.lastOwner()).toBe('7');
  });

  it('a sign-in that fails at device registration does not make the new person the last account', async () => {
    const s = make();
    await s.session.loginWith(as(7, 'jwt-7'), device);
    await s.session.refreshToken().catch(() => {}); // A tashqaridan chiqarildi
    s.onRegister(async () => {
      throw new ApiError(503, 'unavailable', 'x');
    });
    await expect(s.session.loginWith(as(9, 'jwt-9'), device)).rejects.toBeInstanceOf(ApiError);
    expect(await s.session.owner()).toBeNull();
    expect(await s.session.lastOwner()).toBe('7');
  });

  it('identify: a token left by 1.3.13 (no owner stored) learns its account once; skipped when known or when the token changed', async () => {
    const s = make({ [KEYS.token]: 'old-jwt', [KEYS.tokenExpiresAt]: new Date(NOW + 3600_000).toISOString() });
    expect(await s.session.owner()).toBeNull();
    const me = jest.fn(async () => ({ ...loginResponse.user, actorId: 11 }));
    await s.session.identify(me);
    expect(await s.session.owner()).toBe('11');
    expect(await s.session.lastOwner()).toBe('11');
    await s.session.identify(me);
    expect(me).toHaveBeenCalledTimes(1);

    const t = make({ [KEYS.token]: 'old-jwt', [KEYS.tokenExpiresAt]: new Date(NOW + 3600_000).toISOString() });
    await t.session.identify(async () => {
      t.kv.data.set(KEYS.token, 'someone-else'); // so'rov paytida boshqa odam kirdi
      return { ...loginResponse.user, actorId: 11 };
    });
    expect(await t.session.owner()).toBeNull();
    expect(await t.session.lastOwner()).toBeNull();
  });

  it('stamp: a firm owner only while the server has confirmed this token since the app came to the front', async () => {
    const s = make();
    expect(await s.session.stamp()).toEqual({ owner: null, ownerHint: null }); // hech kim kirmagan
    await s.session.loginWith(as(7, 'jwt-7'), device);
    expect(await s.session.stamp()).toEqual({ owner: '7', ownerHint: null });
    s.session.unconfirm(); // orqa fonga o'tdi
    expect(await s.session.stamp()).toEqual({ owner: null, ownerHint: '7' });
    s.session.confirm('jwt-7'); // server javob berdi
    expect(await s.session.stamp()).toEqual({ owner: '7', ownerHint: null });
    s.session.confirm('boshqa-token');
    expect(await s.session.stamp()).toEqual({ owner: null, ownerHint: '7' });
    await s.session.refreshToken().catch(() => {}); // admin chiqarib yubordi
    expect(await s.session.stamp()).toEqual({ owner: null, ownerHint: '7' });
  });

  it("stamp: a 1.3.13 token whose account is unknown gives the '?' hint", async () => {
    const s = make({ [KEYS.token]: 'old-jwt', [KEYS.tokenExpiresAt]: new Date(NOW + 3600_000).toISOString() });
    expect(await s.session.stamp()).toEqual({ owner: null, ownerHint: UNKNOWN_OWNER });
  });

  it('onOwnerLearned fires when the same session learns its account (identify, or a refresh with the same device token), never on a new sign-in', async () => {
    const learned: string[] = [];
    const s = make(
      { [KEYS.token]: 'old-jwt', [KEYS.tokenExpiresAt]: new Date(NOW + 3600_000).toISOString(), [KEYS.deviceToken]: 'dev' },
      (o) => learned.push(o),
    );
    s.onRefresh(async () => as(11, 'jwt-11'));
    await s.session.refreshToken();
    expect(learned).toEqual(['11']);
    await s.session.refreshToken(); // ega allaqachon ma'lum
    expect(learned).toEqual(['11']);

    const t = make({ [KEYS.token]: 'old-jwt', [KEYS.tokenExpiresAt]: new Date(NOW + 3600_000).toISOString() }, (o) => learned.push(o));
    await t.session.identify(async () => ({ ...loginResponse.user, actorId: 12 }));
    expect(learned).toEqual(['11', '12']);

    const u = make({}, (o) => learned.push(o));
    await u.session.loginWith(as(13, 'jwt-13'), device);
    expect(learned).toEqual(['11', '12']);
  });

  it('ApiClient tells the session when the server accepted a token (2xx), not on errors', async () => {
    let status = 200;
    const ff = fakeFetch(() => (status === 200 ? { status: 200, json: { ok: true } } : { status, json: { status, message: 'x' } }));
    const confirm = jest.fn();
    const client = new ApiClient({
      baseUrl: 'https://x.uz',
      fetch: ff.fetch,
      tokens: { getToken: async () => 'tok-1', refreshToken: async () => 'tok-2', confirm },
    });
    await client.request('/api/v1/x');
    expect(confirm).toHaveBeenCalledWith('tok-1');
    status = 500;
    await expect(client.request('/api/v1/x')).rejects.toBeInstanceOf(ApiError);
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("another person's Mini App token has no known owner until identify", async () => {
    const s = make();
    await s.session.loginWith(as(7, jwt({ sub: 'kc-aziz', exp: 2e9 })), device);
    expect(await s.session.adoptToken(jwt({ sub: 'kc-bobur', exp: 2e9 }))).toBe('switched');
    expect(await s.session.owner()).toBeNull();
  });
});

function Rows({ all }: { all?: boolean }) {
  const rows = useQueueRows({ all });
  return <Text testID="rows">{rows.map((r) => r.clientId).join(',')}</Text>;
}

describe('useQueue: the list shows only this account and ownerless recordings', () => {
  it("hides another account's recordings; the logout warning view sees all of them", async () => {
    const services = fakeServices();
    (services.session.owner as jest.Mock).mockResolvedValue('B');
    await services.queue.insert(rec('a1', { owner: 'A', startedAt: '2026-11-16T01:00:00.000Z' }));
    await services.queue.insert(rec('b1', { owner: 'B', startedAt: '2026-11-16T02:00:00.000Z' }));
    await services.queue.insert(rec('n1', { owner: null, startedAt: '2026-11-16T03:00:00.000Z' }));

    await render(
      <Providers services={services}>
        <Rows />
      </Providers>,
    );
    await waitFor(() => expect(screen.getByTestId('rows').props.children).toBe('b1,n1'));
    await screen.unmount();

    await render(
      <Providers services={services}>
        <Rows all />
      </Providers>,
    );
    await waitFor(() => expect(screen.getByTestId('rows').props.children).toBe('a1,b1,n1'));
    await screen.unmount();
  });

  it('signed out: shows the last account recordings (and ownerless ones)', async () => {
    const services = fakeServices();
    (services.session.owner as jest.Mock).mockResolvedValue(null);
    (services.session.lastOwner as jest.Mock).mockResolvedValue('A');
    await services.queue.insert(rec('a1', { owner: 'A', startedAt: '2026-11-16T01:00:00.000Z' }));
    await services.queue.insert(rec('b1', { owner: 'B', startedAt: '2026-11-16T02:00:00.000Z' }));
    await services.queue.insert(rec('n1', { owner: null, ownerHint: 'A', startedAt: '2026-11-16T03:00:00.000Z' }));
    await render(
      <Providers services={services}>
        <Rows />
      </Providers>,
    );
    await waitFor(() => expect(screen.getByTestId('rows').props.children).toBe('a1,n1'));
    await screen.unmount();
  });
});

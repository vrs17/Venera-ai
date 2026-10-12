import { ApiClient, AuthRequiredError, type TokenProvider } from '@/api/client';
import { createMeetingsApi } from '@/api/meetings';
import { newQueueRow, type QueueRow } from '@/features/upload/queueStore';
import { createMemoryQueueStore } from '@/features/upload/queueStore.memory';
import { createUploader, DAY_MS, type FileAccess } from '@/features/upload/uploader';
import { sha256Hex } from '@/lib/sha256';

import { FakeServer, fileBytes, sha } from './fixtures/fakeServer';

const CHUNK = 1000;
const URI = 'file:///doc/recordings/c1.aac';

function fakeFiles(initial: Record<string, Uint8Array>) {
  const data = new Map(Object.entries(initial));
  const removed: string[] = [];
  const files: FileAccess = {
    size: async (uri) => (data.has(uri) ? data.get(uri)!.length : null),
    read: async (uri, offset, length) => {
      const d = data.get(uri);
      if (!d) throw new Error('missing');
      return d.slice(offset, offset + length);
    },
    remove: async (uri) => {
      removed.push(uri);
      data.delete(uri);
    },
  };
  return { files, removed, data };
}

function tokenProvider(): TokenProvider & { refreshes: number; fail: boolean } {
  let cur = 't1';
  const tp = {
    refreshes: 0,
    fail: false,
    async getToken() {
      return cur;
    },
    async refreshToken() {
      if (tp.fail) throw new AuthRequiredError();
      tp.refreshes += 1;
      cur = `t${tp.refreshes + 1}`;
      return cur;
    },
  };
  return tp;
}

function row(over: Partial<QueueRow> = {}): QueueRow {
  return newQueueRow({
    clientId: '6f1c2a3b-1111-4222-8333-444455556666',
    fileUri: URI,
    language: 'uz',
    template: 'auto',
    expectedSpeakers: null,
    source: 'tile',
    startedAt: '2026-10-09T06:00:00.000Z',
    state: 'stopped',
    durationSec: 61.5,
    endedAt: '2026-10-09T06:01:01.500Z',
    marks: [{ t: 12.5, note: 'narx' }],
    ...over,
  });
}

interface FakeTimer {
  fn: () => void;
  ms: number;
  cancelled: boolean;
}

function setup(
  opts: {
    size?: number;
    rows?: QueueRow[];
    keepDays?: number;
    canonicalUri?: (id: string) => string;
    fileInUse?: (uri: string) => boolean;
    callConsent?: () => { consentAt: string; consentVersion: string } | null;
  } = {},
) {
  const server = new FakeServer(CHUNK);
  const tp = tokenProvider();
  const client = new ApiClient({ baseUrl: 'https://llm.brb-tech.uz', fetch: server.fetch, tokens: tp });
  const api = createMeetingsApi(client);
  const content = fileBytes(opts.size ?? 2500);
  const fs = fakeFiles({ [URI]: content });
  const store = createMemoryQueueStore(opts.rows ?? [row()]);
  let now = Date.parse('2026-10-09T06:02:00Z');
  const onAuthRequired = jest.fn();
  const timers: FakeTimer[] = [];
  const uploader = createUploader({
    store,
    api,
    files: fs.files,
    chunkSha256: async (b) => sha256Hex(b),
    now: () => now,
    random: () => 0.5, // jitter 0
    keepDays: () => opts.keepDays ?? 0,
    appVersion: '1.0.0',
    device: 'SM-S921B',
    onAuthRequired,
    canonicalUri: opts.canonicalUri,
    fileInUse: opts.fileInUse,
    callConsent: opts.callConsent,
    schedule: (fn, ms) => {
      const t: FakeTimer = { fn, ms, cancelled: false };
      timers.push(t);
      return () => {
        t.cancelled = true;
      };
    },
  });
  return {
    server,
    tp,
    store,
    uploader,
    fs,
    content,
    onAuthRequired,
    timers,
    /** Hozir qurollangan (bekor qilinmagan) taymerlar. */
    armed: () => timers.filter((t) => !t.cancelled),
    /** Qurollangan taymerni "vaqti keldi" deb ishga tushirish. */
    fire: () => {
      const t = timers.filter((x) => !x.cancelled)[0];
      t.cancelled = true;
      t.fn();
    },
    advance: (ms: number) => {
      now += ms;
    },
    now: () => now,
    get: async () => (await store.list())[0],
  };
}

describe('uploader', () => {
  it("call recording: the consent mark goes to the server; other sources never send it", async () => {
    const consent = { consentAt: '2026-10-08T09:00:00.000Z', consentVersion: 'calls-consent-1' };
    const call = setup({ rows: [row({ source: 'call' })], callConsent: () => consent });
    await call.uploader.runOnce();
    expect([...call.server.meetings.values()][0].createBody).toMatchObject({ source: 'call', ...consent });

    const app = setup({ rows: [row({ source: 'app' })], callConsent: () => consent });
    await app.uploader.runOnce();
    const body = [...app.server.meetings.values()][0].createBody ?? {};
    expect(body.consentAt).toBeUndefined();
    expect(body.consentVersion).toBeUndefined();

    // Rozilik hali yo'q (eski o'rnatish) - qo'ng'iroq baribir yuklanadi, belgisiz.
    const none = setup({ rows: [row({ source: 'call' })], callConsent: () => null });
    await none.uploader.runOnce();
    expect([...none.server.meetings.values()][0].createBody?.consentAt).toBeUndefined();
  });

  it('creates, uploads 4-MiB-style chunks in order, completes with whole-file sha, then deletes the local file', async () => {
    const s = setup();
    await s.uploader.runOnce();
    const m = [...s.server.meetings.values()][0];
    expect(s.server.putOffsets()).toEqual([0, 1000, 2000]);
    expect(Array.from(m.data)).toEqual(Array.from(s.content));
    expect(m.completeBody).toMatchObject({
      totalBytes: 2500,
      sha256: sha(s.content),
      durationSec: 61.5,
      endedAt: '2026-10-09T06:01:01.500Z',
      marks: [{ t: 12.5, note: 'narx' }],
    });
    const create = s.server.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/meetings');
    expect(create?.body).toMatchObject({ clientId: row().clientId, source: 'tile', contentType: 'audio/aac', device: 'SM-S921B' });
    const r = await s.get();
    expect(r.state).toBe('done');
    expect(r.serverId).toBe(m.id);
    expect(s.fs.removed).toEqual([URI]);
    // Qator kamida 1 kun qoladi (clientId -> server id).
    expect(r.keepUntil).toBe(s.now() + DAY_MS);
  });

  it('keeps the local copy for 7 days when asked, then cleans it up', async () => {
    const s = setup({ keepDays: 7 });
    await s.uploader.runOnce();
    expect(s.fs.removed).toEqual([]);
    expect((await s.get()).keepUntil).toBe(s.now() + 7 * DAY_MS);
    s.advance(7 * DAY_MS + 1);
    await s.uploader.runOnce();
    expect(s.fs.removed).toEqual([URI]);
    expect(await s.store.list()).toEqual([]);
  });

  it('keepDays=0 but the file is playing right now: not deleted mid-listen, cleaned up with the row later', async () => {
    // Tinglash paytida yuklash tugadi - Android pleeri keyingi siljitishda faylni qayta ochadi.
    const s = setup({ fileInUse: (uri) => uri === URI });
    await s.uploader.runOnce();
    expect((await s.get()).state).toBe('done');
    expect(s.fs.removed).toEqual([]);
    s.advance(DAY_MS + 1);
    await s.uploader.runOnce();
    expect(s.fs.removed).toEqual([URI]);
    expect(await s.store.list()).toEqual([]);
  });

  it('resyncs on 409 offset_mismatch from the server receivedBytes', async () => {
    const s = setup();
    // Birinchi PUT dan oldin server 1000 baytni allaqachon olgan (boshqa urinishdan).
    s.server.inject(
      (r) => r.method === 'PUT' && r.query.offset === '0',
      (r) => {
        const m = [...s.server.meetings.values()][0];
        m.data = s.content.slice(0, 1000);
        void r;
        return { status: 409, json: { status: 409, message: 'offset', code: 'offset_mismatch', receivedBytes: 1000 } };
      },
    );
    await s.uploader.runOnce();
    expect(s.server.putOffsets()).toEqual([0, 1000, 2000]);
    const m = [...s.server.meetings.values()][0];
    expect(m.complete).toBe(true);
    // Hasher uzilgan - butun fayl qayta o'qilib to'g'ri sha yuborildi.
    expect(m.completeBody?.sha256).toBe(sha(s.content));
    expect((await s.get()).state).toBe('done');
  });

  it('a lost response is resumed from the server position; a duplicate replay returns 200 and continues', async () => {
    const s = setup();
    // Server birinchi bo'lakni saqlaydi, lekin javob yo'qoladi.
    s.server.inject((r) => r.method === 'PUT' && r.query.offset === '0', { networkError: true }, { storeFirst: true });
    await s.uploader.runOnce();
    let r = await s.get();
    expect(r.state).toBe('uploading');
    expect(r.attempts).toBe(1);
    expect(s.fs.removed).toEqual([]);

    // Pozitsiya eskirgan (replika orqada) - klient 0 ni qayta yuboradi, server 200 (takror) qaytaradi.
    s.server.positionLag = 1000;
    s.advance(10_000);
    await s.uploader.runOnce();
    expect(s.server.putOffsets()).toEqual([0, 0, 1000, 2000]);
    r = await s.get();
    expect(r.state).toBe('done');
    expect([...s.server.meetings.values()][0].completeBody?.sha256).toBe(sha(s.content));
  });

  it('restarts from 0 after a whole-file sha_mismatch on /complete', async () => {
    const s = setup();
    s.server.inject(
      (r) => r.method === 'POST' && r.path.endsWith('/complete'),
      () => {
        const m = [...s.server.meetings.values()][0];
        m.data = new Uint8Array(); // server qism faylni 0 ga qirqadi
        return { status: 409, json: { status: 409, message: 'sha', code: 'sha_mismatch', receivedBytes: 0 } };
      },
    );
    await s.uploader.runOnce();
    expect(s.server.putOffsets()).toEqual([0, 1000, 2000, 0, 1000, 2000]);
    expect((await s.get()).state).toBe('done');
    expect(s.fs.removed).toEqual([URI]);
  });

  it('goes back to uploading on 409 upload_incomplete', async () => {
    const s = setup();
    s.server.inject(
      (r) => r.method === 'POST' && r.path.endsWith('/complete'),
      () => {
        const m = [...s.server.meetings.values()][0];
        m.data = m.data.slice(0, 2000);
        return { status: 409, json: { status: 409, message: 'x', code: 'upload_incomplete', receivedBytes: 2000 } };
      },
    );
    await s.uploader.runOnce();
    expect(s.server.putOffsets()).toEqual([0, 1000, 2000, 2000]);
    expect((await s.get()).state).toBe('done');
  });

  it('on 401 refreshes the token once via the device session and retries', async () => {
    const s = setup();
    s.server.rejectTokens.add('t1');
    await s.uploader.runOnce();
    expect(s.tp.refreshes).toBe(1);
    expect((await s.get()).state).toBe('done');
  });

  it('stops the queue and keeps rows when the session is gone (AuthRequired)', async () => {
    const second = row({ clientId: '7f1c2a3b-1111-4222-8333-444455556666', startedAt: '2026-10-09T07:00:00.000Z' });
    const s = setup({ rows: [row(), second] });
    s.server.rejectTokens.add('t1');
    s.tp.fail = true;
    await s.uploader.runOnce();
    expect(s.onAuthRequired).toHaveBeenCalledTimes(1);
    const rows = await s.store.list();
    expect(rows.map((r) => r.state)).toEqual(['creating', 'stopped']);
    expect(rows.every((r) => r.attempts === 0)).toBe(true);
    // Faqat bitta so'rov - ikkinchi qatorga o'tilmadi.
    expect(s.server.calls).toHaveLength(1);
    expect(s.fs.removed).toEqual([]);
  });

  it('backs off 5 s * 2^n (capped at 15 min) and honours Retry-After', async () => {
    const s = setup();
    s.server.inject((r) => r.method === 'POST', { status: 503, json: { status: 503, message: 'busy' } }, { once: false });
    const delays: number[] = [];
    for (let i = 0; i < 10; i++) {
      await s.uploader.runOnce();
      const r = await s.get();
      delays.push(r.nextAttemptAt! - s.now());
      // Muddatdan oldin hech narsa yuborilmaydi.
      const before = s.server.calls.length;
      await s.uploader.runOnce();
      expect(s.server.calls.length).toBe(before);
      s.advance(r.nextAttemptAt! - s.now());
    }
    expect(delays).toEqual([5_000, 10_000, 20_000, 40_000, 80_000, 160_000, 320_000, 640_000, 900_000, 900_000]);
    expect((await s.get()).lastError).toBe('unavailable');

    s.server.injections = [];
    s.server.inject((r) => r.method === 'POST', { status: 429, json: { status: 429, message: 'x', code: 'rate_limited' }, headers: { 'Retry-After': '3600' } });
    await s.uploader.runOnce();
    const r = await s.get();
    expect(r.nextAttemptAt! - s.now()).toBe(3_600_000);
  });

  it('is single-flight: concurrent triggers share one run', async () => {
    const s = setup();
    await Promise.all([s.uploader.runOnce(), s.uploader.runOnce(), s.uploader.runOnce()]);
    const m = [...s.server.meetings.values()][0];
    expect(m.creates).toBe(1);
    expect(s.server.putOffsets()).toEqual([0, 1000, 2000]);
  });

  it('never deletes the local file before upload.complete', async () => {
    const s = setup();
    s.server.inject((r) => r.method === 'POST' && r.path.endsWith('/complete'), { status: 500, json: { status: 500, message: 'boom' } });
    await s.uploader.runOnce();
    expect((await s.get()).state).toBe('completing');
    expect(s.fs.removed).toEqual([]);
    s.advance(60_000);
    await s.uploader.runOnce();
    expect((await s.get()).state).toBe('done');
    expect(s.fs.removed).toEqual([URI]);
  });

  it('marks 413/415 as failed (shown to the user), keeps the file, and retry() requeues', async () => {
    const s = setup();
    s.server.inject((r) => r.method === 'PUT', { status: 415, json: { status: 415, message: 'format', code: 'unsupported_format' } });
    await s.uploader.runOnce();
    let r = await s.get();
    expect(r.state).toBe('failed');
    expect(r.lastError).toBe('unsupported_format');
    expect(s.fs.removed).toEqual([]);
    await s.uploader.retry(r.clientId);
    r = await s.get();
    expect(r.state).toBe('done');
  });

  it('recovers when /complete succeeded but its reply was lost (position says complete)', async () => {
    const s = setup();
    s.server.inject((r) => r.method === 'POST' && r.path.endsWith('/complete'), { networkError: true }, { storeFirst: true });
    await s.uploader.runOnce();
    expect((await s.get()).state).toBe('completing');
    s.advance(10_000);
    await s.uploader.runOnce();
    expect((await s.get()).state).toBe('done');
    expect(s.fs.removed).toEqual([URI]);
  });

  it('fails rows whose file is missing and skips rows still recording', async () => {
    const recording = row({ clientId: '8f1c2a3b-1111-4222-8333-444455556666', state: 'recording', startedAt: '2026-10-09T05:00:00.000Z' });
    const missing = row({ clientId: '9f1c2a3b-1111-4222-8333-444455556666', fileUri: 'file:///nope.aac', startedAt: '2026-10-09T05:30:00.000Z' });
    const s = setup({ rows: [recording, missing] });
    await s.uploader.runOnce();
    const rows = await s.store.list();
    expect(rows.find((r) => r.clientId === recording.clientId)?.state).toBe('recording');
    expect(rows.find((r) => r.clientId === missing.clientId)).toMatchObject({ state: 'failed', lastError: 'file_missing' });
    expect(s.server.calls).toHaveLength(0);
  });

  it('estimates durationSec for crash-recovered rows without one (server measures the real value)', async () => {
    const s = setup({ rows: [row({ durationSec: null, endedAt: null })] });
    await s.uploader.runOnce();
    const body = [...s.server.meetings.values()][0].completeBody!;
    expect(body.durationSec).toBeCloseTo((2500 * 8) / 48000, 2);
    expect(typeof body.endedAt).toBe('string');
  });

  it('re-arms its own backoff: one timer at the nearest nextAttemptAt retries and finishes the upload', async () => {
    const s = setup();
    s.server.inject((r) => r.method === 'POST' && r.path === '/api/v1/meetings', { status: 503, json: { status: 503, message: 'busy' } });
    await s.uploader.runOnce();
    const r = await s.get();
    expect(r).toMatchObject({ state: 'creating', lastError: 'unavailable' });
    expect(s.armed()).toHaveLength(1);
    expect(s.armed()[0].ms).toBe(r.nextAttemptAt! - s.now()); // 5 s (jitter 0)
    expect(s.armed()[0].ms).toBe(5000);
    // Taymer ishlaydi (ilova ekranda) - tashqi hodisasiz qayta urinadi.
    s.advance(5000);
    s.fire();
    await s.uploader.runOnce();
    expect((await s.get()).state).toBe('done');
    expect(s.armed()).toHaveLength(0); // kutadigan qator yo'q - taymer ham yo'q
  });

  it('keeps at most one timer and never re-arms after the session is gone', async () => {
    const s = setup();
    s.server.inject((r) => r.method === 'POST', { status: 500, json: { status: 500, message: 'x' } }, { once: false });
    await s.uploader.runOnce();
    await s.uploader.runOnce(); // muddat kelmagan - qator o'tkaziladi, taymer yangilanadi
    expect(s.armed()).toHaveLength(1);
    s.server.injections = [];
    s.tp.fail = true;
    s.server.rejectTokens.add('t1');
    s.advance(10 * 60_000);
    await s.uploader.runOnce();
    expect(s.onAuthRequired).toHaveBeenCalled();
    expect(s.armed()).toHaveLength(0);
  });

  it('a 404 for a known server id (server purged the upload) forgets the id and recreates by clientId', async () => {
    const s = setup({ rows: [row({ serverId: 'gone0000000000000000000000000000', receivedBytes: 1000, state: 'uploading' })] });
    await s.uploader.runOnce();
    const r = await s.get();
    expect(r).toMatchObject({ serverId: null, receivedBytes: 0, state: 'stopped', lastError: 'server_reset' });
    expect(r.nextAttemptAt).not.toBeNull();
    s.advance(r.nextAttemptAt! - s.now());
    await s.uploader.runOnce();
    const done = await s.get();
    expect(done.state).toBe('done');
    const m = [...s.server.meetings.values()][0];
    expect(m.clientId).toBe(row().clientId);
    expect(Array.from(m.data)).toEqual(Array.from(s.content));
  });

  it('retry() of a row an older build failed with not_found drops the stale server id', async () => {
    const s = setup({ rows: [row({ serverId: 'gone0000000000000000000000000000', state: 'failed', lastError: 'not_found' })] });
    await s.uploader.retry(row().clientId);
    expect((await s.get()).state).toBe('done');
    expect(s.server.calls.some((c) => c.path.includes('gone'))).toBe(false);
  });

  it('finds the file at recordings/<clientId>.aac when a crash hit between the move and the row update', async () => {
    const s = setup({ rows: [row({ fileUri: 'file:///doc/Audio/recording-x.aac' })], canonicalUri: () => URI });
    await s.uploader.runOnce();
    const r = await s.get();
    expect(r.state).toBe('done');
    expect(r.fileUri).toBe(URI);
  });
});

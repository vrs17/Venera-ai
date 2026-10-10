import { ApiError, AuthRequiredError } from '@/api/client';
import type { AuthApi } from '@/api/meetings';
import { createSession, REFRESH_WINDOW_MS, WEB_TOKEN_TTL_MS } from '@/features/auth/session';
import { createTokenStore, KEYS, memoryKV } from '@/features/auth/tokenStore';

import { jwt } from './fixtures/jwt';
import { deviceResponse, loginResponse } from './fixtures/server';

const NOW = Date.parse('2026-10-09T06:00:00Z');
const iso = (ms: number) => new Date(ms).toISOString();

function setup(initial: Record<string, string> = {}) {
  const kv = memoryKV(initial);
  const store = createTokenStore(kv);
  let n = 0;
  const api = {
    login: jest.fn(async () => loginResponse),
    logout: jest.fn(async () => ({ status: 'OK' })),
    registerDevice: jest.fn(async () => deviceResponse),
    deviceSession: jest.fn(async () => {
      n += 1;
      await new Promise((r) => setTimeout(r, 5));
      return { ...loginResponse, token: `fresh-${n}`, expiresAt: iso(NOW + 12 * 3600_000) };
    }),
    revokeDevice: jest.fn(async () => ({ status: 'OK' })),
  } satisfies Pick<AuthApi, 'login' | 'logout' | 'registerDevice' | 'deviceSession' | 'revokeDevice'>;
  const session = createSession({ store, authApi: api, now: () => NOW });
  const events: string[] = [];
  session.subscribe((e) => events.push(e));
  return { kv, store, api, session, events };
}

describe('session', () => {
  it('login stores the JWT and the device token, registering with the fresh JWT', async () => {
    const s = setup();
    await s.session.login(' aziz ', 'pw', { deviceName: 'SM-S921B', platform: 'android', appVersion: '1.0.0' });
    expect(s.api.login).toHaveBeenCalledWith({ username: 'aziz', password: 'pw' });
    expect(s.api.registerDevice).toHaveBeenCalledWith({ deviceName: 'SM-S921B', platform: 'android', appVersion: '1.0.0' }, 'jwt-1');
    expect(s.kv.data.get(KEYS.token)).toBe('jwt-1');
    expect(s.kv.data.get(KEYS.deviceToken)).toBe(deviceResponse.deviceToken);
    expect(await s.session.hasSession()).toBe(true);
    expect(s.events).toEqual(['signedIn']);
  });

  it('meetings off (403/404 on device registration) -> still signed in for chat, token only', async () => {
    const s = setup();
    s.api.registerDevice.mockRejectedValueOnce(new ApiError(404, 'not_found', 'Not Found'));
    await s.session.login('a', 'b', { deviceName: 'd', platform: 'android', appVersion: '1' });
    expect(s.kv.data.get(KEYS.deviceToken)).toBeUndefined();
    expect(s.kv.data.get(KEYS.token)).toBeTruthy();
    expect(await s.session.hasSession()).toBe(true);
    expect(s.events).toEqual(['signedIn']);
  });

  it('device registration network error -> login fails and nothing stays stored', async () => {
    const s = setup();
    s.api.registerDevice.mockRejectedValueOnce(new ApiError(0, 'network', 'offline'));
    await expect(s.session.login('a', 'b', { deviceName: 'd', platform: 'android', appVersion: '1' })).rejects.toBeInstanceOf(ApiError);
    expect(s.kv.data.get(KEYS.token)).toBeUndefined();
  });

  it('returns the stored token while it has more than 10 minutes left', async () => {
    const s = setup({ [KEYS.token]: 'cur', [KEYS.tokenExpiresAt]: iso(NOW + REFRESH_WINDOW_MS + 60_000), [KEYS.deviceToken]: 'dt' });
    await expect(s.session.getToken()).resolves.toBe('cur');
    expect(s.api.deviceSession).not.toHaveBeenCalled();
  });

  it('refreshes inside the expiry window, single-flight for concurrent callers', async () => {
    const s = setup({ [KEYS.token]: 'old', [KEYS.tokenExpiresAt]: iso(NOW + 5 * 60_000), [KEYS.deviceToken]: 'dt' });
    const tokens = await Promise.all([s.session.getToken(), s.session.getToken(), s.session.refreshToken()]);
    expect(tokens).toEqual(['fresh-1', 'fresh-1', 'fresh-1']);
    expect(s.api.deviceSession).toHaveBeenCalledTimes(1);
    expect(s.api.deviceSession).toHaveBeenCalledWith('dt');
    expect(s.kv.data.get(KEYS.token)).toBe('fresh-1');
    // Keyingi chaqiruv yangi so'rov qiladi (inflight tozalangan).
    await s.session.refreshToken();
    expect(s.api.deviceSession).toHaveBeenCalledTimes(2);
  });

  it('a revoked/expired device token clears auth (queue untouched) and emits expired', async () => {
    const s = setup({ [KEYS.token]: 'old', [KEYS.tokenExpiresAt]: iso(NOW - 1), [KEYS.deviceToken]: 'dt', [KEYS.installKey]: 'k' });
    s.api.deviceSession.mockRejectedValueOnce(new ApiError(401, 'unauthorized', 'Token bekor'));
    await expect(s.session.getToken()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(s.kv.data.has(KEYS.token)).toBe(false);
    expect(s.kv.data.has(KEYS.deviceToken)).toBe(false);
    expect(s.kv.data.get(KEYS.installKey)).toBe('k');
    expect(s.events).toEqual(['expired']);
  });

  it('never signed in -> AuthRequired without an expired event; network errors are not logouts', async () => {
    const s = setup();
    await expect(s.session.getToken()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(s.events).toEqual([]);

    const s2 = setup({ [KEYS.deviceToken]: 'dt' });
    s2.api.deviceSession.mockRejectedValueOnce(new ApiError(0, 'network', 'offline'));
    await expect(s2.session.getToken()).rejects.toMatchObject({ code: 'network' });
    expect(s2.kv.data.get(KEYS.deviceToken)).toBe('dt');
  });

  it('logout revokes, logs out, runs the wipe and clears tokens (best effort offline)', async () => {
    const s = setup({ [KEYS.token]: 'cur', [KEYS.tokenExpiresAt]: iso(NOW + 3600_000), [KEYS.deviceToken]: 'dt', [KEYS.installKey]: 'k' });
    s.api.revokeDevice.mockRejectedValueOnce(new ApiError(0, 'network', 'offline'));
    const wipe = jest.fn(async () => {});
    await s.session.logout(wipe);
    expect(s.api.revokeDevice).toHaveBeenCalledWith('dt');
    expect(s.api.logout).toHaveBeenCalled();
    expect(wipe).toHaveBeenCalled();
    expect([...s.kv.data.keys()]).toEqual([KEYS.installKey]);
    expect(s.events).toEqual(['signedOut']);
  });
});

describe('session.peekToken (in-memory token for latency-sensitive requests)', () => {
  it('is null until the store was read; then returns the token synchronously while it has > 10 min left', async () => {
    const s = setup({ [KEYS.token]: 'cur', [KEYS.tokenExpiresAt]: iso(NOW + REFRESH_WINDOW_MS + 60_000), [KEYS.deviceToken]: 'dt' });
    expect(s.session.peekToken?.()).toBeNull();
    await s.session.getToken();
    expect(s.session.peekToken?.()).toBe('cur');
  });

  it('inside the refresh window it is null (getToken() refreshes); after the refresh it is the fresh token', async () => {
    const s = setup({ [KEYS.token]: 'old', [KEYS.tokenExpiresAt]: iso(NOW + 5 * 60_000), [KEYS.deviceToken]: 'dt' });
    const p = s.session.getToken();
    expect(s.session.peekToken?.()).toBeNull();
    await expect(p).resolves.toBe('fresh-1');
    expect(s.session.peekToken?.()).toBe('fresh-1');
  });

  it('follows login, Mini App token adoption, expiry (401 on refresh) and logout', async () => {
    const s = setup();
    await s.session.login('a', 'b', { deviceName: 'd', platform: 'android', appVersion: '1' });
    expect(s.session.peekToken?.()).toBe(loginResponse.token);
    const other = jwt({ sub: 'u-2', exp: Math.floor((NOW + 3 * 3600_000) / 1000) });
    await s.session.adoptToken(other);
    expect(s.session.peekToken?.()).toBe(other);
    await s.session.logout();
    expect(s.session.peekToken?.()).toBeNull();

    const e = setup({ [KEYS.token]: 'old', [KEYS.tokenExpiresAt]: iso(NOW + 5 * 60_000), [KEYS.deviceToken]: 'dt' });
    e.api.deviceSession.mockRejectedValueOnce(new ApiError(401, 'unauthorized', 'Token bekor'));
    await expect(e.session.refreshToken()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(e.session.peekToken?.()).toBeNull();
  });

  it('a slow read that started before a write does not overwrite the newer token', async () => {
    const s = setup({ [KEYS.token]: 'old', [KEYS.tokenExpiresAt]: iso(NOW + 3600_000) });
    // Birinchi o'qish qo'lda qo'yib yuboriladi (sekin Keystore), yozuv esa shu orada tugaydi.
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const slowStore = {
      ...s.store,
      getToken: jest.fn(async () => {
        const stored = await s.store.getToken();
        await gate;
        return stored;
      }),
    };
    const session = createSession({ store: slowStore, authApi: s.api, now: () => NOW });
    const read = session.getToken();
    await new Promise((r) => setImmediate(r));
    slowStore.getToken.mockImplementation(() => s.store.getToken());
    await session.adoptToken(jwt({ sub: 'u-9', exp: Math.floor((NOW + 3 * 3600_000) / 1000) }));
    const fresh = session.peekToken?.();
    expect(fresh).not.toBe('old');
    release();
    await expect(read).resolves.toBe('old');
    expect(session.peekToken?.()).toBe(fresh);
  });
});

describe('session <- Mini App token (venera:auth)', () => {
  const DEVICE = { deviceName: 'SM-S921B', platform: 'android' as const, appVersion: '1.0.0' };
  const web = (sub: string, hours = 12) => jwt({ sub, exp: (NOW + hours * 3600_000) / 1000 });

  it('stores the token with its JWT expiry, signs in, then registers the device with it', async () => {
    const s = setup();
    const tok = web('u1');
    await expect(s.session.adoptToken(tok)).resolves.toBe('adopted');
    expect(s.kv.data.get(KEYS.token)).toBe(tok);
    expect(s.kv.data.get(KEYS.tokenExpiresAt)).toBe(iso(NOW + 12 * 3600_000));
    expect(s.events).toEqual(['signedIn']);
    expect(await s.session.hasSession()).toBe(true);
    // Meetings API'si shu tokenni ishlatadi.
    await expect(s.session.getToken()).resolves.toBe(tok);

    await expect(s.session.ensureDevice(DEVICE)).resolves.toBe(true);
    expect(s.api.registerDevice).toHaveBeenCalledWith(DEVICE, tok);
    expect(s.kv.data.get(KEYS.deviceToken)).toBe(deviceResponse.deviceToken);
    // Ikkinchi marta - tarmoqqa chiqmaydi.
    await s.session.ensureDevice(DEVICE);
    expect(s.api.registerDevice).toHaveBeenCalledTimes(1);
  });

  it('the same token again is a no-op; expired or empty tokens are refused', async () => {
    const tok = web('u1');
    const s = setup({ [KEYS.token]: tok, [KEYS.tokenExpiresAt]: iso(NOW + 3600_000) });
    await expect(s.session.adoptToken(tok)).resolves.toBe('unchanged');
    expect(s.events).toEqual([]);
    await expect(s.session.adoptToken(web('u1', -1))).resolves.toBe('invalid');
    await expect(s.session.adoptToken('')).resolves.toBe('invalid');
    expect(s.kv.data.get(KEYS.token)).toBe(tok);
  });

  it('opaque (non-JWT) token falls back to the server default lifetime', async () => {
    const s = setup();
    await s.session.adoptToken('opaque-session-token');
    expect(s.kv.data.get(KEYS.tokenExpiresAt)).toBe(iso(NOW + WEB_TOKEN_TTL_MS));
  });

  it("another person's token drops (and revokes) the old device token; same person keeps it", async () => {
    const s = setup({ [KEYS.token]: web('u1', 1), [KEYS.tokenExpiresAt]: iso(NOW + 3600_000), [KEYS.deviceToken]: 'dt-u1', [KEYS.installKey]: 'k' });
    await expect(s.session.adoptToken(web('u1', 12))).resolves.toBe('adopted');
    expect(s.kv.data.get(KEYS.deviceToken)).toBe('dt-u1');
    expect(s.api.revokeDevice).not.toHaveBeenCalled();

    const other = web('u2');
    await expect(s.session.adoptToken(other)).resolves.toBe('switched');
    expect(s.kv.data.get(KEYS.token)).toBe(other);
    expect(s.kv.data.has(KEYS.deviceToken)).toBe(false);
    expect(s.api.revokeDevice).toHaveBeenCalledWith('dt-u1');
    expect(s.kv.data.get(KEYS.installKey)).toBe('k');
  });

  it('feature off (403/404): token-only session, registration not retried; network error is retried', async () => {
    const s = setup();
    await s.session.adoptToken(web('u1'));
    s.api.registerDevice.mockRejectedValueOnce(new ApiError(403, 'forbidden', 'Yoqilmagan'));
    await expect(s.session.ensureDevice(DEVICE)).resolves.toBe(false);
    await expect(s.session.ensureDevice(DEVICE)).resolves.toBe(false);
    expect(s.api.registerDevice).toHaveBeenCalledTimes(1);
    await expect(s.session.getToken()).resolves.toBeTruthy();

    const n = setup();
    await n.session.adoptToken(web('u1'));
    n.api.registerDevice.mockRejectedValueOnce(new ApiError(0, 'network', 'offline'));
    await expect(n.session.ensureDevice(DEVICE)).resolves.toBe(false);
    await expect(n.session.ensureDevice(DEVICE)).resolves.toBe(true);
  });

  it('device registered for a session that changed meanwhile is revoked, not stored', async () => {
    const s = setup();
    await s.session.adoptToken(web('u1'));
    s.api.registerDevice.mockImplementationOnce(async () => {
      await s.session.adoptToken(web('u2'));
      return deviceResponse;
    });
    await expect(s.session.ensureDevice(DEVICE)).resolves.toBe(false);
    expect(s.kv.data.has(KEYS.deviceToken)).toBe(false);
    expect(s.api.revokeDevice).toHaveBeenCalledWith(deviceResponse.deviceToken);
  });

  it('token-only session: used until it expires, then "expired" (not a silent failure)', async () => {
    const tok = web('u1');
    const s = setup({ [KEYS.token]: tok, [KEYS.tokenExpiresAt]: iso(NOW + 5 * 60_000) });
    // 10 daqiqadan kam qolgan, lekin yangilab bo'lmaydi - muddati tugaguncha ishlatiladi.
    await expect(s.session.getToken()).resolves.toBe(tok);

    const dead = setup({ [KEYS.token]: tok, [KEYS.tokenExpiresAt]: iso(NOW - 1) });
    expect(await dead.session.hasSession()).toBe(false);
    await expect(dead.session.getToken()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(dead.kv.data.has(KEYS.token)).toBe(false);
    expect(dead.events).toEqual(['expired']);
  });

  it('webToken: refreshes early through the device token, never throws', async () => {
    const s = setup({ [KEYS.token]: 'old', [KEYS.tokenExpiresAt]: iso(NOW + 30 * 60_000), [KEYS.deviceToken]: 'dt' });
    await expect(s.session.webToken()).resolves.toBe('old');
    await expect(s.session.webToken(60 * 60_000)).resolves.toBe('fresh-1');

    const off = setup({ [KEYS.deviceToken]: 'dt' });
    off.api.deviceSession.mockRejectedValueOnce(new ApiError(0, 'network', 'offline'));
    await expect(off.session.webToken()).resolves.toBeNull();
    await expect(setup().session.webToken()).resolves.toBeNull();
  });
});


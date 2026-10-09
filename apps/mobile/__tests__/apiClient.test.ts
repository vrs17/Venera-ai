import { ApiClient, ApiError, AuthRequiredError, CHUNK_TIMEOUT_MS, buildQuery, type TokenProvider } from '@/api/client';

import { envelope, fakeFetch } from './fixtures/fakeFetch';

function tokens(initial = 't1'): TokenProvider & { refreshes: number } {
  let cur = initial;
  const tp = {
    refreshes: 0,
    getToken: jest.fn(async () => cur),
    refreshToken: jest.fn(async () => {
      tp.refreshes += 1;
      cur = `t${tp.refreshes + 1}`;
      return cur;
    }),
  };
  return tp;
}

describe('ApiClient', () => {
  it('sends Bearer, X-Venera-Client and Accept-Language, parses JSON', async () => {
    const { fetch, calls } = fakeFetch(() => ({ json: { ok: 1 } }));
    const c = new ApiClient({ baseUrl: 'https://x.uz/', fetch, tokens: tokens(), getLanguage: () => 'ru' });
    await expect(c.request('/api/v1/meetings', { query: { limit: 20, q: undefined } })).resolves.toEqual({ ok: 1 });
    expect(calls[0].url).toBe('https://x.uz/api/v1/meetings?limit=20');
    expect(calls[0].headers.Authorization).toBe('Bearer t1');
    expect(calls[0].headers['X-Venera-Client']).toBe('mobile');
    expect(calls[0].headers['Accept-Language']).toBe('ru');
  });

  it('auth:false sends no Bearer and needs no token provider', async () => {
    const { fetch, calls } = fakeFetch(() => ({ json: {} }));
    const c = new ApiClient({ baseUrl: 'https://x.uz', fetch });
    await c.request('/api/v1/auth/login', { method: 'POST', body: { username: 'a' }, auth: false });
    expect(calls[0].headers.Authorization).toBeUndefined();
    expect(calls[0].headers['Content-Type']).toBe('application/json');
    expect(calls[0].body).toEqual({ username: 'a' });
  });

  it('without a session an authed call throws AuthRequiredError (no network)', async () => {
    const { fetch, calls } = fakeFetch(() => ({ json: {} }));
    const c = new ApiClient({ baseUrl: 'https://x.uz', fetch });
    await expect(c.request('/api/v1/meetings')).rejects.toBeInstanceOf(AuthRequiredError);
    expect(calls).toHaveLength(0);
  });

  it('maps the error envelope to ApiError{status, code, message, body}', async () => {
    const { fetch } = fakeFetch(() => envelope(409, 'Offset mos emas', { code: 'offset_mismatch', receivedBytes: 42 }));
    const c = new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: tokens() });
    const err = await c.request<never>('/x').catch((e: unknown) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe('offset_mismatch');
    expect(err.message).toBe('Offset mos emas');
    expect(err.body?.receivedBytes).toBe(42);
  });

  it('falls back to a status-derived code and parses Retry-After', async () => {
    const { fetch } = fakeFetch(() => ({ status: 429, text: 'busy', headers: { 'Retry-After': '30' } }));
    const c = new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: tokens() });
    const err: ApiError = await c.request<never>('/x').catch((e: unknown) => e as ApiError);
    expect(err.code).toBe('rate_limited');
    expect(err.message).toBe('Request failed (429)');
    expect(err.retryAfterSec).toBe(30);
  });

  it('on 401 refreshes once via the token provider and retries once', async () => {
    let n = 0;
    const { fetch, calls } = fakeFetch(() => (++n === 1 ? envelope(401, 'expired') : { json: { ok: true } }));
    const tp = tokens();
    const c = new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: tp });
    await expect(c.request('/x')).resolves.toEqual({ ok: true });
    expect(tp.refreshes).toBe(1);
    expect(calls.map((r) => r.headers.Authorization)).toEqual(['Bearer t1', 'Bearer t2']);
  });

  it('a second 401 after refresh is returned (no loop)', async () => {
    const { fetch, calls } = fakeFetch(() => envelope(401, 'nope'));
    const tp = tokens();
    const c = new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: tp });
    await expect(c.request('/x')).rejects.toMatchObject({ status: 401 });
    expect(calls).toHaveLength(2);
    expect(tp.refreshes).toBe(1);
  });

  it('turns network failures and timeouts into status 0 errors', async () => {
    const net = fakeFetch(() => ({ networkError: true }));
    const c1 = new ApiClient({ baseUrl: 'https://x.uz', fetch: net.fetch, tokens: tokens() });
    await expect(c1.request('/x')).rejects.toMatchObject({ status: 0, code: 'network' });

    const hang = fakeFetch(() => ({ hang: true }));
    const c2 = new ApiClient({ baseUrl: 'https://x.uz', fetch: hang.fetch, tokens: tokens() });
    const err: ApiError = await c2.request<never>('/x', { timeoutMs: 20 }).catch((e: unknown) => e as ApiError);
    expect(err.code).toBe('timeout');
    expect(err.isNetwork).toBe(true);
  });

  it('sends raw bytes as octet-stream and returns text responses as-is', async () => {
    const { fetch, calls } = fakeFetch((r) => (r.raw ? { json: { receivedBytes: r.raw.length } } : { text: '# Sarlavha' }));
    const c = new ApiClient({ baseUrl: 'https://x.uz', fetch, tokens: tokens() });
    await expect(c.request('/a', { method: 'PUT', rawBody: new Uint8Array([1, 2, 3]), timeoutMs: CHUNK_TIMEOUT_MS })).resolves.toEqual({
      receivedBytes: 3,
    });
    expect(calls[0].headers['Content-Type']).toBe('application/octet-stream');
    await expect(c.request('/b', { responseType: 'text' })).resolves.toBe('# Sarlavha');
  });

  it('buildQuery encodes booleans as 1/0 and skips nullish', () => {
    expect(buildQuery({ format: 'srt', speakers: true, timestamps: false, q: null, z: undefined })).toBe('?format=srt&speakers=1&timestamps=0');
    expect(buildQuery({})).toBe('');
  });
});

/**
 * XHR transporti: timeout native bo'lishi uchun `xhr.timeout` (RN -> OkHttp
 * callTimeout) qo'yiladi. JS taymeri fonda to'xtaydi - shuning uchun bu test
 * JS taymerisiz ham "timeout" xatosi kelishini tekshiradi.
 */
describe('XHR transport (native timeout)', () => {
  type Mode = 'load' | 'error' | 'timeout' | 'hang';
  const sent: FakeXhr[] = [];
  let mode: Mode = 'load';

  class FakeXhr {
    method = '';
    url = '';
    headers: Record<string, string> = {};
    timeout = 0;
    status = 0;
    responseText = '';
    body: unknown = null;
    aborted = false;
    responseHeaders: Record<string, string> = {};
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    onabort: (() => void) | null = null;
    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(k: string, v: string) {
      this.headers[k] = v;
    }
    getResponseHeader(name: string) {
      return this.responseHeaders[name.toLowerCase()] ?? null;
    }
    abort() {
      this.aborted = true;
      this.onabort?.();
    }
    send(body: unknown) {
      this.body = body;
      sent.push(this);
      queueMicrotask(() => {
        if (mode === 'load') {
          this.status = 200;
          this.responseText = JSON.stringify({ receivedBytes: 3 });
          this.responseHeaders['retry-after'] = '7';
          this.onload?.();
        } else if (mode === 'error') this.onerror?.();
        else if (mode === 'timeout') this.ontimeout?.();
      });
    }
  }

  beforeEach(() => {
    sent.length = 0;
    mode = 'load';
  });

  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { createXhrTransport } = require('@/api/xhrTransport') as typeof import('@/api/xhrTransport');
  const client = () =>
    new ApiClient({ baseUrl: 'https://x.uz', fetch: createXhrTransport(FakeXhr as unknown as new () => XMLHttpRequest), tokens: tokens() });

  it('sets xhr.timeout per request (chunk PUT 120 s, JSON 30 s) and passes raw bytes through', async () => {
    const c = client();
    const bytes = new Uint8Array([1, 2, 3]);
    await expect(c.request('/a', { method: 'PUT', rawBody: bytes, timeoutMs: CHUNK_TIMEOUT_MS })).resolves.toEqual({ receivedBytes: 3 });
    await c.request('/b');
    expect(sent[0]).toMatchObject({ method: 'PUT', url: 'https://x.uz/a', timeout: CHUNK_TIMEOUT_MS, body: bytes });
    expect(sent[0].headers['Content-Type']).toBe('application/octet-stream');
    expect(sent[0].headers.Authorization).toBe('Bearer t1');
    expect(sent[1].timeout).toBe(30_000);
  });

  it('a native timeout becomes ApiError(0, "timeout") without any JS timer firing', async () => {
    mode = 'timeout';
    await expect(client().request('/a', { timeoutMs: 120_000 })).rejects.toMatchObject({ status: 0, code: 'timeout' });
  });

  it('a network failure becomes ApiError(0, "network")', async () => {
    mode = 'error';
    await expect(client().request('/a')).rejects.toMatchObject({ status: 0, code: 'network' });
  });

  it('the JS fallback timer still aborts the request in the foreground', async () => {
    jest.useFakeTimers();
    try {
      mode = 'hang';
      const p = client().request('/a', { timeoutMs: 1000 });
      const assertion = expect(p).rejects.toMatchObject({ status: 0, code: 'timeout' });
      await Promise.resolve();
      jest.advanceTimersByTime(1000);
      await assertion;
      expect(sent[0].aborted).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });
});

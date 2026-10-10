/** Soxta fetch: so'rovlarni yozib oladi, javobni handler beradi. Tarmoqqa chiqmaydi. */
import type { FetchLike } from '@/api/client';

export interface FakeRequest {
  method: string;
  url: string;
  path: string;
  query: Record<string, string>;
  headers: Record<string, string>;
  body: unknown;
  raw: Uint8Array | null;
}

export interface FakeReply {
  status?: number;
  json?: unknown;
  text?: string;
  headers?: Record<string, string>;
  /** true - tarmoq xatosi (fetch reject). */
  networkError?: boolean;
  /** abort signal'ni kutib turish (timeout testi). */
  hang?: boolean;
}

export type Handler = (req: FakeRequest) => FakeReply | Promise<FakeReply>;

export function fakeFetch(handler: Handler): { fetch: FetchLike; calls: FakeRequest[] } {
  const calls: FakeRequest[] = [];
  const fetch: FetchLike = async (input, init) => {
    const u = new URL(input);
    const query: Record<string, string> = {};
    u.searchParams.forEach((v, k) => (query[k] = v));
    const headers = (init.headers ?? {}) as Record<string, string>;
    let body: unknown = null;
    let raw: Uint8Array | null = null;
    if (init.body instanceof Uint8Array) raw = init.body;
    else if (typeof init.body === 'string') body = JSON.parse(init.body);
    const req: FakeRequest = { method: init.method ?? 'GET', url: input, path: u.pathname, query, headers, body, raw };
    calls.push(req);
    const r = await handler(req);
    if (r.hang) {
      await new Promise<never>((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });
    }
    if (r.networkError) throw new TypeError('Network request failed');
    const status = r.status ?? 200;
    const text = r.text ?? (r.json !== undefined ? JSON.stringify(r.json) : '');
    const h = Object.fromEntries(Object.entries(r.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: (n: string) => h[n.toLowerCase()] ?? null },
      text: async () => text,
    } as unknown as Response;
  };
  return { fetch, calls };
}

export function envelope(status: number, message: string, extra: Record<string, unknown> = {}): FakeReply {
  return {
    status,
    json: { timestamp: '2026-10-09T06:00:00Z', status, error: 'Error', message, path: '/x', ...extra },
  };
}

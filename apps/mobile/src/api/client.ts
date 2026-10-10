/**
 * Venera API uchun fetch o'rami (spec 7.6).
 *
 * Har so'rovda:
 *  - `Authorization: Bearer <JWT>` (auth=false bo'lmasa) - token `TokenProvider`dan;
 *  - `X-Venera-Client: mobile` - server analitikasi kanalni shundan biladi;
 *  - `Accept-Language: <UI tili>` - shablon nomlari shu tilda keladi.
 *
 * Xato bo'lsa server konverti `{timestamp,status,error,message,path,code?}`
 * `ApiError{status, code, message, body}` ga aylanadi. Ekranlar faqat
 * `code` bo'yicha qaror qiladi (matn tarjima qilinishi mumkin).
 *
 * 401: token bir marta yangilanadi (device session) va so'rov BIR MARTA
 * qaytariladi. Yana 401 bo'lsa - xato yuqoriga chiqadi (login ekrani).
 *
 * Timeout: transport XMLHttpRequest (`xhrTransport.ts`) - `xhr.timeout` OkHttp
 * `callTimeout` bo'lib native ishlaydi, ilova fonda bo'lsa ham. JS taymeri
 * (AbortController) faqat zaxira: fonda u to'xtab turadi.
 */
import type { ErrorEnvelope } from './types';
import { createXhrTransport, TransportTimeoutError, type ResponseLike, type TransportInit } from './xhrTransport';

export const CLIENT_HEADER = 'X-Venera-Client';
export const CLIENT_NAME = 'mobile';
export const JSON_TIMEOUT_MS = 30_000;
export const CHUNK_TIMEOUT_MS = 120_000;
/**
 * AI dvigatel v3 javobini kutadigan so'rovlar (Savol, vazifani CRM ga): server o'zi
 * 120 s gacha kutadi (`MEETINGS_CRM_TIMEOUT`, Ask'da v3 deadline) - telefon undan
 * oldin uzib qo'ymasin, aks holda tayyor taklif "timeout" bo'lib ko'rinardi.
 */
export const AI_TIMEOUT_MS = 150_000;
/** Taklifni tasdiqlash: CRM ga yozish bir necha soniya - lekin JSON'dan uzoqroq kutamiz. */
export const ACTION_TIMEOUT_MS = 60_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly body: ErrorEnvelope | null;
  readonly retryAfterSec: number | null;

  constructor(status: number, code: string, message: string, body: ErrorEnvelope | null = null, retryAfterSec: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.body = body;
    this.retryAfterSec = retryAfterSec;
  }

  /** Tarmoq yoki timeout - serverga yetib bormadi. */
  get isNetwork(): boolean {
    return this.status === 0;
  }
}

/** Sessiya tugagan, qayta login kerak (device token ham o'tmadi). */
export class AuthRequiredError extends ApiError {
  constructor(message = 'Qayta kirish kerak') {
    super(401, 'auth_required', message);
    this.name = 'AuthRequiredError';
  }
}

export interface TokenProvider {
  /** Amaldagi JWT (kerak bo'lsa yangilab). Login bo'lmasa AuthRequiredError. */
  getToken(): Promise<string>;
  /**
   * Xotirada turgan va hali uzoq yashaydigan token - SINXRON (SecureStore'ga bormaydi), yo'q
   * bo'lsa null (unda `getToken()`). Ixtiyoriy: kechikishga sezgir so'rovlar uchun (ovoz).
   */
  peekToken?(): string | null;
  /** 401 dan keyin: tokenni majburan yangilash. */
  refreshToken(): Promise<string>;
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: HttpMethod;
  query?: Record<string, QueryValue>;
  /** JSON tana. */
  body?: unknown;
  /** Xom baytlar (audio chunk). `body` bilan birga berilmaydi. */
  rawBody?: Uint8Array;
  headers?: Record<string, string>;
  /** default true. false - Bearer yuborilmaydi (login, device session). */
  auth?: boolean;
  timeoutMs?: number;
  responseType?: 'json' | 'text';
}

export interface ApiResponse<T> {
  status: number;
  data: T;
  headers: { get(name: string): string | null };
}

export type FetchLike = (input: string, init: TransportInit) => Promise<ResponseLike>;

function defaultTransport(): FetchLike {
  if (typeof XMLHttpRequest !== 'undefined') return createXhrTransport();
  return (input, init) => fetch(input, init as RequestInit) as Promise<ResponseLike>;
}

export interface ClientOptions {
  baseUrl: string | (() => string);
  fetch?: FetchLike;
  tokens?: TokenProvider | null;
  getLanguage?: () => string;
  /** Oqim va forma uchun XHR (testlarda soxtasi). */
  xhr?: XhrCtor;
}

export function buildQuery(query?: Record<string, QueryValue>): string {
  if (!query) return '';
  const parts: string[] = [];
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(typeof v === 'boolean' ? (v ? '1' : '0') : String(v))}`);
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  if (Number.isFinite(n) && n >= 0) return n;
  const at = Date.parse(value);
  if (Number.isFinite(at)) return Math.max(0, Math.round((at - Date.now()) / 1000));
  return null;
}

const DEFAULT_CODES: Record<number, string> = {
  400: 'bad_request',
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  410: 'gone',
  413: 'too_large',
  415: 'unsupported_format',
  422: 'validation_error',
  429: 'rate_limited',
  500: 'internal',
  502: 'bad_gateway',
  503: 'unavailable',
  504: 'gateway_timeout',
};

/** Chat javobi oqimi: v3 ko'p bosqichli javobni 2-3 daqiqagacha yozishi mumkin. */
export const STREAM_TIMEOUT_MS = 330_000;

/** XHR konstruktori - testlarda soxtasi beriladi. */
export type XhrCtor = new () => XMLHttpRequest;

export interface StreamRequest {
  /** JSON tana. */
  body: unknown;
  /** Har kelgan matn bo'lagi (UTF-8 allaqachon dekodlangan). */
  onChunk: (text: string) => void;
  /** Javob sarlavhalari kelishi bilan (birinchi bo'lakdan oldin). */
  onHeaders?: (get: (name: string) => string | null) => void;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface FormRequest {
  /** Har urinishda yangi FormData (401 dan keyin qayta yuborish uchun). */
  form: () => FormData;
  timeoutMs?: number;
  signal?: AbortSignal;
}

/** Bekor qilingan oqim (foydalanuvchi "To'xtatish" ni bosdi). */
export class StreamAbortedError extends Error {
  constructor() {
    super('aborted');
    this.name = 'AbortError';
  }
}

function errorFromBody(status: number, text: string, retryAfter: string | null): ApiError {
  let envelope: ErrorEnvelope | null = null;
  try {
    const parsed: unknown = text ? JSON.parse(text) : null;
    if (parsed && typeof parsed === 'object') envelope = parsed as ErrorEnvelope;
  } catch {
    envelope = null;
  }
  const code = (typeof envelope?.code === 'string' && envelope.code) || DEFAULT_CODES[status] || `http_${status}`;
  const message =
    (typeof envelope?.message === 'string' && envelope.message) ||
    (typeof envelope?.detail === 'string' && (envelope.detail as string)) ||
    `Request failed (${status})`;
  return new ApiError(status, code, message, envelope, parseRetryAfter(retryAfter));
}

export class ApiClient {
  private readonly opts: ClientOptions;
  private tokens: TokenProvider | null;
  private transport: FetchLike | null = null;

  constructor(opts: ClientOptions) {
    this.opts = opts;
    this.tokens = opts.tokens ?? null;
  }

  private fetchImpl(): FetchLike {
    if (this.opts.fetch) return this.opts.fetch;
    this.transport = this.transport ?? defaultTransport();
    return this.transport;
  }

  /** Session client'dan keyin yaratiladi (aylana bog'liqlik) - shu orqali ulanadi. */
  setTokenProvider(tokens: TokenProvider | null): void {
    this.tokens = tokens;
  }

  get baseUrl(): string {
    const b = typeof this.opts.baseUrl === 'function' ? this.opts.baseUrl() : this.opts.baseUrl;
    return b.replace(/\/+$/, '');
  }

  url(path: string, query?: Record<string, QueryValue>): string {
    return `${this.baseUrl}${path}${buildQuery(query)}`;
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return (await this.send<T>(path, options)).data;
  }

  async send<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
    const auth = options.auth !== false;
    let token: string | null = null;
    if (auth) {
      if (!this.tokens) throw new AuthRequiredError();
      token = await this.tokens.getToken();
    }
    try {
      return await this.once<T>(path, options, token);
    } catch (e) {
      if (auth && e instanceof ApiError && e.status === 401 && this.tokens && !(e instanceof AuthRequiredError)) {
        // Spec 7.5/7.6: device session orqali yangilab, BIR MARTA qaytaramiz.
        const fresh = await this.tokens.refreshToken();
        return this.once<T>(path, options, fresh);
      }
      throw e;
    }
  }

  private async once<T>(path: string, options: RequestOptions, token: string | null): Promise<ApiResponse<T>> {
    const fetchImpl = this.fetchImpl();
    const headers: Record<string, string> = {
      Accept: options.responseType === 'text' ? 'text/plain, text/markdown, */*' : 'application/json',
      [CLIENT_HEADER]: CLIENT_NAME,
      'Accept-Language': this.opts.getLanguage?.() ?? 'uz',
      ...options.headers,
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    let body: string | Uint8Array | undefined;
    if (options.rawBody) {
      body = options.rawBody;
      headers['Content-Type'] = headers['Content-Type'] ?? 'application/octet-stream';
    } else if (options.body !== undefined) {
      body = JSON.stringify(options.body);
      headers['Content-Type'] = 'application/json';
    }

    const controller = new AbortController();
    const timeoutMs = options.timeoutMs ?? JSON_TIMEOUT_MS;
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    let res: ResponseLike;
    try {
      res = await fetchImpl(this.url(path, options.query), {
        method: options.method ?? 'GET',
        headers,
        body,
        signal: controller.signal,
        timeoutMs,
      });
    } catch (e) {
      clearTimeout(timer);
      if (timedOut || e instanceof TransportTimeoutError) {
        throw new ApiError(0, 'timeout', `So'rov vaqti tugadi (${Math.round(timeoutMs / 1000)} s)`);
      }
      throw new ApiError(0, 'network', e instanceof Error ? e.message : 'Tarmoq xatosi');
    }

    let text: string;
    try {
      text = await res.text();
    } catch (e) {
      clearTimeout(timer);
      if (timedOut) throw new ApiError(0, 'timeout', `So'rov vaqti tugadi (${Math.round(timeoutMs / 1000)} s)`);
      throw new ApiError(0, 'network', e instanceof Error ? e.message : 'Tarmoq xatosi');
    }
    clearTimeout(timer);

    if (!res.ok) {
      let envelope: ErrorEnvelope | null = null;
      try {
        const parsed: unknown = text ? JSON.parse(text) : null;
        if (parsed && typeof parsed === 'object') envelope = parsed as ErrorEnvelope;
      } catch {
        envelope = null;
      }
      const code = (typeof envelope?.code === 'string' && envelope.code) || DEFAULT_CODES[res.status] || `http_${res.status}`;
      const message =
        (typeof envelope?.message === 'string' && envelope.message) ||
        (typeof envelope?.detail === 'string' && (envelope.detail as string)) ||
        `Request failed (${res.status})`;
      throw new ApiError(res.status, code, message, envelope, parseRetryAfter(res.headers.get('Retry-After')));
    }

    let data: unknown = text;
    if (options.responseType !== 'text') {
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        throw new ApiError(res.status, 'bad_json', 'Server javobi JSON emas');
      }
    }
    return { status: res.status, data: data as T, headers: res.headers };
  }

  private headersFor(token: string | null, accept: string): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: accept,
      [CLIENT_HEADER]: CLIENT_NAME,
      'Accept-Language': this.opts.getLanguage?.() ?? 'uz',
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  /**
   * NDJSON oqimi (chat javobi). NEGA XHR: React Native `fetch` javob tanasini oqim
   * qilib bermaydi - butun javob tugaguncha kutardi. XHR `onprogress` da esa
   * `responseText` bo'lak-bo'lak o'sadi (RN `onprogress` bor bo'lsa incremental
   * rejimni yoqadi) - har yangi qism darhol `onChunk` ga.
   *
   * 401 - token BIR MARTA yangilanib qayta yuboriladi (faqat hali hech narsa
   * kelmagan bo'lsa - yarim javobni ikki marta ko'rsatmaslik uchun).
   */
  async stream(path: string, req: StreamRequest): Promise<void> {
    if (!this.tokens) throw new AuthRequiredError();
    const token = await this.tokens.getToken();
    try {
      await this.streamOnce(path, req, token);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && !(e instanceof AuthRequiredError) && this.tokens) {
        const fresh = await this.tokens.refreshToken();
        await this.streamOnce(path, req, fresh);
        return;
      }
      throw e;
    }
  }

  private streamOnce(path: string, req: StreamRequest, token: string): Promise<void> {
    const Xhr = this.opts.xhr ?? XMLHttpRequest;
    return new Promise<void>((resolve, reject) => {
      const xhr = new Xhr();
      let seen = 0;
      let ok = false;
      let settled = false;
      const signal = req.signal ?? null;
      const onAbort = () => xhr.abort();
      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        signal?.removeEventListener('abort', onAbort);
        fn();
      };
      const pump = () => {
        if (!ok) return;
        const text = typeof xhr.responseText === 'string' ? xhr.responseText : '';
        if (text.length > seen) {
          const part = text.slice(seen);
          seen = text.length;
          req.onChunk(part);
        }
      };
      xhr.open('POST', this.url(path), true);
      const headers = { ...this.headersFor(token, 'application/x-ndjson'), 'Content-Type': 'application/json; charset=utf-8' };
      for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
      xhr.timeout = req.timeoutMs ?? STREAM_TIMEOUT_MS;
      xhr.onreadystatechange = () => {
        if (xhr.readyState === 2) {
          ok = xhr.status >= 200 && xhr.status < 300;
          if (ok) req.onHeaders?.((name) => xhr.getResponseHeader(name));
        }
      };
      xhr.onprogress = pump;
      xhr.onload = () =>
        settle(() => {
          ok = xhr.status >= 200 && xhr.status < 300;
          if (!ok) {
            reject(errorFromBody(xhr.status, typeof xhr.responseText === 'string' ? xhr.responseText : '', xhr.getResponseHeader('Retry-After')));
            return;
          }
          pump();
          resolve();
        });
      xhr.onerror = () => settle(() => reject(new ApiError(0, 'network', 'Tarmoq xatosi')));
      xhr.ontimeout = () => settle(() => reject(new ApiError(0, 'timeout', 'Javob kutish vaqti tugadi')));
      xhr.onabort = () => settle(() => reject(new StreamAbortedError()));
      if (signal) {
        if (signal.aborted) {
          settle(() => reject(new StreamAbortedError()));
          return;
        }
        signal.addEventListener('abort', onAbort);
      }
      xhr.send(JSON.stringify(req.body));
    });
  }

  /** multipart/form-data (ovoz -> matn). RN FormData `{uri, name, type}` faylni o'zi o'qiydi. */
  async postForm<T>(path: string, req: FormRequest): Promise<T> {
    if (!this.tokens) throw new AuthRequiredError();
    const token = await this.tokens.getToken();
    try {
      return await this.formOnce<T>(path, req, token);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && !(e instanceof AuthRequiredError) && this.tokens) {
        return this.formOnce<T>(path, req, await this.tokens.refreshToken());
      }
      throw e;
    }
  }

  private formOnce<T>(path: string, req: FormRequest, token: string): Promise<T> {
    const Xhr = this.opts.xhr ?? XMLHttpRequest;
    return new Promise<T>((resolve, reject) => {
      const xhr = new Xhr();
      let settled = false;
      const signal = req.signal ?? null;
      const onAbort = () => xhr.abort();
      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        signal?.removeEventListener('abort', onAbort);
        fn();
      };
      xhr.open('POST', this.url(path), true);
      for (const [k, v] of Object.entries(this.headersFor(token, 'application/json'))) xhr.setRequestHeader(k, v);
      xhr.timeout = req.timeoutMs ?? CHUNK_TIMEOUT_MS;
      xhr.onload = () =>
        settle(() => {
          const text = typeof xhr.responseText === 'string' ? xhr.responseText : '';
          if (xhr.status < 200 || xhr.status >= 300) {
            reject(errorFromBody(xhr.status, text, xhr.getResponseHeader('Retry-After')));
            return;
          }
          try {
            resolve((text ? JSON.parse(text) : null) as T);
          } catch {
            reject(new ApiError(xhr.status, 'bad_json', 'Server javobi JSON emas'));
          }
        });
      xhr.onerror = () => settle(() => reject(new ApiError(0, 'network', 'Tarmoq xatosi')));
      xhr.ontimeout = () => settle(() => reject(new ApiError(0, 'timeout', "So'rov vaqti tugadi")));
      xhr.onabort = () => settle(() => reject(new StreamAbortedError()));
      if (signal) {
        if (signal.aborted) {
          settle(() => reject(new StreamAbortedError()));
          return;
        }
        signal.addEventListener('abort', onAbort);
      }
      xhr.send(req.form());
    });
  }
}

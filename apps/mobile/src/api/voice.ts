/**
 * Ovoz chiqarish (TTS) API - jonli ovozli suhbat va "Tinglash" uchun:
 *
 *   POST /api/v1/tts/clip                 bitta bo'lak (1-3 gap) -> TO'LIQ WAV
 *   GET  /api/v1/tts/hold/{clip}.wav?voice=  tayyor "kutish" ovozi (server oldindan sintez qilgan)
 *   POST /api/v1/chat/stream (voice:true)  ovozli savol - server `hold` kadrlarini ham yuboradi
 *
 * NIMA UCHUN to'liq WAV (web'dagi PCM oqimi emas): expo-audio faqat TAYYOR faylni ijro
 * qiladi, xom PCM oqimini o'ynata olmaydi. Kechikishni gap-gap bo'lib so'rash qaytaradi:
 * birinchi qisqa bo'lak (<=60 belgi) ~1.2-2.2 s da tayyor, keyingilari oldingisi yangrayotganda
 * sintez qilinadi (`features/voice/chunker.ts` - o'lchovlar o'sha yerda).
 *
 * NIMA UCHUN o'z XHR'i (`client.request` emas): umumiy klient javobni MATN qilib o'qiydi -
 * WAV baytlari UTF-8 dekodlashda buziladi. Bu yerda `responseType = 'arraybuffer'`
 * (RN native'dan base64 qilib olib, o'zi ArrayBuffer'ga aylantiradi).
 *
 * `onHeaders` (klip): server sarlavhani sintez TUGAGACH yuboradi (`clip_wav` to'liq WAV ni
 * yig'ib qaytaradi, TTS o'rni shu paytda bo'shaydi). Tana (77-440 KB) esa hali yo'lda. Gap
 * navbati keyingi bo'lakni SHU PAYTDA so'raydi - tana yuklanishini kutmaydi (`speaker.ts`).
 */
import {
  ApiError,
  AuthRequiredError,
  CLIENT_HEADER,
  CLIENT_NAME,
  JSON_TIMEOUT_MS,
  StreamAbortedError,
  type ApiClient,
  type QueryValue,
  type TokenProvider,
  type XhrCtor,
} from './client';
import { createNdjsonParser, type ChatApi } from './chat';
import type { ErrorEnvelope } from './types';

export type VoiceId = 'uz_female_calm' | 'uz_male_news';
export const VOICE_IDS: readonly VoiceId[] = ['uz_female_calm', 'uz_male_news'];

/** Server bitta so'rovda shundan ko'pini qabul qilmaydi (klient <=350 yuboradi). */
export const CLIP_MAX_CHARS = 600;
export const CLIP_TIMEOUT_MS = 20_000;
/** Kutish ovozi kechiksa ma'nosi qolmaydi - o'tkazib yuboriladi. */
export const HOLD_TIMEOUT_MS = 4_000;

const V1 = '/api/v1';
const TURN_RE = /^[0-9a-f]{32}$/;
const CLIP_KEY_RE = /^[a-z0-9-]{1,80}$/;

export interface WavBytes {
  bytes: Uint8Array;
  sampleRate: number | null;
  durationMs: number | null;
  truncated: boolean;
}

export interface ClipHeaders {
  durationMs: number | null;
  sampleRate: number | null;
}

export interface ClipOptions {
  voice?: VoiceId;
  speed?: number;
  turnId?: string | null;
  signal?: AbortSignal;
  /** 200 sarlavhasi keldi (sintez tugadi), tana hali yuklanmoqda. Bir marta chaqiriladi. */
  onHeaders?: (info: ClipHeaders) => void;
  /** So'rov tarmoqqa jo'nadi (token olingandan keyin) - faqat kechikish izi uchun. */
  onSent?: () => void;
}

export interface BinaryRequest {
  method?: 'GET' | 'POST';
  query?: Record<string, QueryValue>;
  /** JSON tana. */
  body?: unknown;
  headers?: Record<string, string>;
  /** default 'audio/wav, *\/*' */
  accept?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** 2xx sarlavhalari keldi (tana hali kelmagan) - bir marta. */
  onHeaders?: (get: (name: string) => string | null) => void;
  /** `xhr.send()` dan keyin (har urinishda). */
  onSent?: () => void;
}

export interface BinaryResponse {
  status: number;
  bytes: Uint8Array;
  headers: { get(name: string): string | null };
}

export interface VoiceApiDeps {
  client: ApiClient;
  /** Ilovada `services.session` (TokenProvider). */
  tokens: TokenProvider | null;
  language?: () => string;
  /** Testlarda soxta XHR. */
  xhr?: XhrCtor;
}

const DEFAULT_CODES: Record<number, string> = {
  400: 'bad_request',
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  422: 'validation_error',
  429: 'rate_limited',
  500: 'internal',
  501: 'not_implemented',
  502: 'bad_gateway',
  503: 'unavailable',
  504: 'gateway_timeout',
};

/**
 * Kichik UTF-8 dekoder - xato konverti uchun (bir necha yuz bayt JSON).
 * NIMA UCHUN o'zimizniki: Hermes versiyasiga qarab `TextDecoder` bo'lmasligi mumkin.
 */
export function decodeUtf8(bytes: Uint8Array): string {
  let out = '';
  let i = 0;
  while (i < bytes.length) {
    const b = bytes[i++];
    let cp: number;
    if (b < 0x80) cp = b;
    else if (b >= 0xc0 && b < 0xe0 && i < bytes.length) cp = ((b & 0x1f) << 6) | (bytes[i++] & 0x3f);
    else if (b >= 0xe0 && b < 0xf0 && i + 1 < bytes.length) {
      cp = ((b & 0x0f) << 12) | ((bytes[i] & 0x3f) << 6) | (bytes[i + 1] & 0x3f);
      i += 2;
    } else if (b >= 0xf0 && i + 2 < bytes.length) {
      cp = ((b & 0x07) << 18) | ((bytes[i] & 0x3f) << 12) | ((bytes[i + 1] & 0x3f) << 6) | (bytes[i + 2] & 0x3f);
      i += 3;
    } else cp = 0xfffd;
    out += String.fromCodePoint(cp);
  }
  return out;
}

function retryAfterSec(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function errorFrom(status: number, bytes: Uint8Array, retryAfter: string | null): ApiError {
  let envelope: ErrorEnvelope | null = null;
  try {
    const parsed: unknown = bytes.length ? JSON.parse(decodeUtf8(bytes)) : null;
    if (parsed && typeof parsed === 'object') envelope = parsed as ErrorEnvelope;
  } catch {
    envelope = null;
  }
  const code = (typeof envelope?.code === 'string' && envelope.code) || DEFAULT_CODES[status] || `http_${status}`;
  const message = (typeof envelope?.message === 'string' && envelope.message) || `Request failed (${status})`;
  return new ApiError(status, code, message, envelope, retryAfterSec(retryAfter));
}

function toBytes(response: unknown): Uint8Array {
  if (response instanceof ArrayBuffer) return new Uint8Array(response);
  if (ArrayBuffer.isView(response)) return new Uint8Array(response.buffer, response.byteOffset, response.byteLength);
  return new Uint8Array(0);
}

function numberHeader(value: string | null): number | null {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function wavFrom(res: BinaryResponse): WavBytes {
  return {
    bytes: res.bytes,
    sampleRate: numberHeader(res.headers.get('X-Venera-Sample-Rate')),
    durationMs: numberHeader(res.headers.get('X-Venera-Duration-Ms')),
    truncated: res.headers.get('X-Venera-Truncated') === '1',
  };
}

export function createVoiceApi(deps: VoiceApiDeps) {
  const { client } = deps;

  function once(path: string, req: BinaryRequest, token: string): Promise<BinaryResponse> {
    const Xhr = deps.xhr ?? XMLHttpRequest;
    return new Promise<BinaryResponse>((resolve, reject) => {
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
      xhr.open(req.method ?? 'GET', client.url(path, req.query), true);
      const headers: Record<string, string> = {
        Accept: req.accept ?? 'audio/wav, */*',
        [CLIENT_HEADER]: CLIENT_NAME,
        'Accept-Language': deps.language?.() ?? 'uz',
        Authorization: `Bearer ${token}`,
        ...req.headers,
      };
      if (req.body !== undefined) headers['Content-Type'] = 'application/json; charset=utf-8';
      for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
      xhr.responseType = 'arraybuffer';
      xhr.timeout = req.timeoutMs ?? JSON_TIMEOUT_MS;
      const onHeaders = req.onHeaders;
      if (onHeaders) {
        let seen = false;
        xhr.onreadystatechange = () => {
          // HEADERS_RECEIVED (2): RN native (OkHttp) sarlavhani tanani o'qishdan OLDIN yuboradi.
          if (seen || xhr.readyState !== 2 || settled) return;
          seen = true;
          if (xhr.status < 200 || xhr.status >= 300) return;
          try {
            onHeaders((name) => xhr.getResponseHeader(name));
          } catch {
            // Chaqiruvchi xatosi so'rovni buzmasin - tana baribir onload'da keladi.
          }
        };
      }
      xhr.onload = () =>
        settle(() => {
          const bytes = toBytes(xhr.response);
          if (xhr.status < 200 || xhr.status >= 300) {
            reject(errorFrom(xhr.status, bytes, xhr.getResponseHeader('Retry-After')));
            return;
          }
          resolve({ status: xhr.status, bytes, headers: { get: (name) => xhr.getResponseHeader(name) } });
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
      xhr.send(req.body !== undefined ? JSON.stringify(req.body) : null);
      try {
        req.onSent?.();
      } catch {
        // Iz yozuvchisi xatosi so'rovni buzmasin.
      }
    });
  }

  /**
   * 401 - token BIR MARTA yangilanib qayta yuboriladi (umumiy klient bilan bir xil qoida).
   *
   * Xotiradagi yaroqli token (`peekToken`) bo'lsa SecureStore KUTILMAYDI va so'rov shu
   * chaqiruv ichida (sinxron) jo'naydi. NIMA UCHUN: javob kadrlari kelayotganda JS oqimi har
   * kadrda chatni qayta chizadi; `await getToken()` (Android Keystore) so'rovni o'sha
   * navbatning ORQASIGA surib qo'yadi. Bu birinchi ovozdan oldingi ~1.8 s ning BIR sababi
   * bo'lishi mumkin - TAXMIN, telefonda o'lchanmagan (dev build'dagi `[voice]` izi:
   * `speak` -> `req` -> `sent` -> `headers` - qaysi qadam sekinligini ko'rsatadi).
   */
  async function binary(path: string, req: BinaryRequest = {}): Promise<BinaryResponse> {
    const tokens = deps.tokens;
    if (!tokens) throw new AuthRequiredError();
    const token = tokens.peekToken?.() ?? (await tokens.getToken());
    try {
      return await once(path, req, token);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && !(e instanceof AuthRequiredError)) {
        return once(path, req, await tokens.refreshToken());
      }
      throw e;
    }
  }

  return {
    binary,

    /** POST /api/v1/tts/clip -> to'liq WAV. text > CLIP_MAX_CHARS -> Error (klient xatosi, so'rov ketmaydi). */
    async clip(text: string, opts: ClipOptions = {}): Promise<WavBytes> {
      if (text.length > CLIP_MAX_CHARS) throw new Error(`clip text too long (${text.length})`);
      const headers: Record<string, string> = {};
      if (opts.turnId && TURN_RE.test(opts.turnId)) headers['X-Venera-Turn'] = opts.turnId;
      const onClipHeaders = opts.onHeaders;
      const res = await binary(`${V1}/tts/clip`, {
        method: 'POST',
        body: { text, language: 'uz', voice: opts.voice ?? undefined, speed: opts.speed ?? undefined },
        headers,
        signal: opts.signal,
        timeoutMs: CLIP_TIMEOUT_MS,
        onSent: opts.onSent,
        onHeaders: onClipHeaders
          ? (get) =>
              onClipHeaders({ durationMs: numberHeader(get('X-Venera-Duration-Ms')), sampleRate: numberHeader(get('X-Venera-Sample-Rate')) })
          : undefined,
      });
      return wavFrom(res);
    },

    /**
     * GET /api/v1/tts/hold/{clip}.wav?voice= ; 404 yoki har qanday xato -> null (jim).
     * Kutish ovozi - xushmuomalalik, xato bo'lib ko'rinmasligi kerak.
     */
    async hold(clip: string, voice: VoiceId, signal?: AbortSignal): Promise<WavBytes | null> {
      if (!CLIP_KEY_RE.test(clip)) return null;
      try {
        const res = await binary(`${V1}/tts/hold/${encodeURIComponent(clip)}.wav`, { query: { voice }, signal, timeoutMs: HOLD_TIMEOUT_MS });
        return res.bytes.length ? wavFrom(res) : null;
      } catch {
        return null;
      }
    },
  };
}

export type VoiceApi = ReturnType<typeof createVoiceApi>;

/**
 * Ovozli savol uchun chat oqimi: `ChatApi.stream` bilan AYNI shakl, tanada qo'shimcha
 * `voice: true` (server `hold` kadrlarini yuboradi, faqat uz) va `input: 'voice'` (admin izi).
 *
 * NIMA UCHUN alohida funksiya: matnli savolning tanasi o'zgarmay qolsin (server izi va
 * mavjud testlar aynan shu tanaga tayanadi) - ovoz maydonlari faqat ovozli savolda.
 */
export function createVoiceChatStream(client: ApiClient): ChatApi['stream'] {
  return async (question, onFrame, opts = {}) => {
    const parser = createNdjsonParser(onFrame);
    await client.stream(`${V1}/chat/stream`, {
      body: {
        question,
        mode: opts.mode === 'pro' ? 'pro' : undefined,
        chatId: opts.chatId ?? undefined,
        locale: opts.locale ?? undefined,
        voice: true,
        input: 'voice',
      },
      signal: opts.signal,
      onHeaders: (get) => {
        const turn = get('X-Venera-Turn')?.trim();
        if (turn) opts.onTurn?.(turn);
      },
      onChunk: (text) => parser.push(text),
    });
    parser.end();
  };
}

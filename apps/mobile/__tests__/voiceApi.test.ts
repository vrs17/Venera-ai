/**
 * Ovoz API (soxta XHR): `/tts/clip` to'liq WAV baytlarini qaytaradi va sarlavhalarni o'qiydi;
 * 401 da token bir marta yangilanadi; xato konverti ApiError bo'ladi; kutish klipi har
 * qanday xatoda jim (null); ovozli chat oqimi tanaga `voice: true, input: 'voice'` qo'shadi.
 */
import type { ChatFrame } from '@/api/chat';
import { ApiClient, ApiError, AuthRequiredError, StreamAbortedError, type TokenProvider } from '@/api/client';
import { CLIP_MAX_CHARS, createVoiceApi, createVoiceChatStream, decodeUtf8 } from '@/api/voice';

function tokens(): TokenProvider {
  let n = 1;
  return { getToken: jest.fn(async () => `t${n}`), refreshToken: jest.fn(async () => `t${++n}`) };
}

const enc = (s: string) => new Uint8Array(Buffer.from(s, 'utf8'));

interface Step {
  status?: number;
  body?: Uint8Array;
  headers?: Record<string, string>;
  fail?: 'error' | 'timeout';
  /** Sarlavha (readyState 2) va tana (onload) orasidagi kechikish, ms. */
  bodyDelayMs?: number;
}

/** Soxta binar XHR: `responseType = 'arraybuffer'`, javob - `response` (ArrayBuffer). */
function fakeXhr(script: Step[]) {
  const sent: { method: string; url: string; headers: Record<string, string>; body: unknown; responseType: string; timeout: number }[] = [];
  let call = 0;
  class X {
    readyState = 0;
    status = 0;
    response: ArrayBuffer | null = null;
    responseType = '';
    timeout = 0;
    onreadystatechange: (() => void) | null = null;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    onabort: (() => void) | null = null;
    private method = '';
    private url = '';
    private h: Record<string, string> = {};
    private res: Record<string, string> = {};
    private aborted = false;
    open(m: string, url: string) {
      this.method = m;
      this.url = url;
    }
    setRequestHeader(k: string, v: string) {
      this.h[k] = v;
    }
    getResponseHeader(name: string) {
      return this.res[name] ?? null;
    }
    abort() {
      this.aborted = true;
      this.onabort?.();
    }
    send(body: unknown) {
      sent.push({ method: this.method, url: this.url, headers: this.h, body, responseType: this.responseType, timeout: this.timeout });
      const step = script[Math.min(call, script.length - 1)];
      call += 1;
      setTimeout(() => {
        if (this.aborted) return;
        if (step.fail === 'error') return this.onerror?.();
        if (step.fail === 'timeout') return this.ontimeout?.();
        this.status = step.status ?? 200;
        this.res = step.headers ?? {};
        this.readyState = 2;
        this.onreadystatechange?.();
        setTimeout(() => {
          if (this.aborted) return;
          const b = step.body ?? new Uint8Array(0);
          this.response = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
          this.readyState = 4;
          this.onload?.();
        }, step.bodyDelayMs ?? 0);
      }, 0);
    }
  }
  return { Xhr: X as unknown as new () => XMLHttpRequest, sent };
}

const client = () => new ApiClient({ baseUrl: 'https://x.uz/', tokens: tokens() });
const WAV = new Uint8Array([0x52, 0x49, 0x46, 0x46, 1, 2, 3, 0xff, 0x00]);

describe('createVoiceApi.clip', () => {
  it('posts the chunk and returns the raw WAV bytes plus header metadata', async () => {
    const { Xhr, sent } = fakeXhr([{ body: WAV, headers: { 'X-Venera-Sample-Rate': '8000', 'X-Venera-Duration-Ms': '1250', 'X-Venera-Truncated': '0' } }]);
    const api = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr, language: () => 'uz' });
    const turn = 'ab'.repeat(16);
    const res = await api.clip('Bugun uch kishi kechikdi.', { voice: 'uz_male_news', speed: 1.1, turnId: turn });
    expect(Array.from(res.bytes)).toEqual(Array.from(WAV));
    expect(res).toMatchObject({ sampleRate: 8000, durationMs: 1250, truncated: false });
    expect(sent[0].method).toBe('POST');
    expect(sent[0].url).toBe('https://x.uz/api/v1/tts/clip');
    expect(sent[0].responseType).toBe('arraybuffer');
    expect(sent[0].timeout).toBe(20_000);
    expect(sent[0].headers).toMatchObject({
      Authorization: 'Bearer t1',
      'X-Venera-Client': 'mobile',
      'X-Venera-Turn': turn,
      Accept: 'audio/wav, */*',
      'Content-Type': 'application/json; charset=utf-8',
    });
    expect(JSON.parse(String(sent[0].body))).toEqual({ text: 'Bugun uch kishi kechikdi.', language: 'uz', voice: 'uz_male_news', speed: 1.1 });
  });

  it('only a 32-hex turn id is sent; defaults are left to the server', async () => {
    const { Xhr, sent } = fakeXhr([{ body: WAV }]);
    const api = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr });
    await api.clip('Salom.', { turnId: 'turn-1' });
    expect(sent[0].headers['X-Venera-Turn']).toBeUndefined();
    expect(JSON.parse(String(sent[0].body))).toEqual({ text: 'Salom.', language: 'uz' });
  });

  it('rejects text over the server limit without a request', async () => {
    const { Xhr, sent } = fakeXhr([{ body: WAV }]);
    const api = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr });
    await expect(api.clip('a'.repeat(CLIP_MAX_CHARS + 1))).rejects.toThrow();
    expect(sent).toHaveLength(0);
  });

  it('401 -> refresh once and retry', async () => {
    const tp = tokens();
    const { Xhr, sent } = fakeXhr([{ status: 401, body: enc('{"message":"expired"}') }, { body: WAV }]);
    const api = createVoiceApi({ client: client(), tokens: tp, xhr: Xhr });
    await api.clip('Salom.');
    expect(tp.refreshToken).toHaveBeenCalledTimes(1);
    expect(sent[1].headers.Authorization).toBe('Bearer t2');
  });

  it('error envelopes become ApiError (503 keeps Retry-After, 501 has its own code)', async () => {
    const { Xhr } = fakeXhr([
      { status: 503, body: enc('{"code":"unavailable","message":"Ovoz xizmati band, biroz kutib qayta urinib ko\'ring"}'), headers: { 'Retry-After': '1' } },
      { status: 501, body: enc('{"message":"Ovoz javobi hali yoqilmagan"}') },
    ]);
    const api = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr });
    const busy = await api.clip('a').catch((e: unknown) => e);
    expect(busy).toBeInstanceOf(ApiError);
    expect(busy).toMatchObject({ status: 503, code: 'unavailable', retryAfterSec: 1, message: "Ovoz xizmati band, biroz kutib qayta urinib ko'ring" });
    await expect(api.clip('a')).rejects.toMatchObject({ status: 501, code: 'not_implemented', message: 'Ovoz javobi hali yoqilmagan' });
  });

  it('network, timeout and abort map to the usual errors', async () => {
    const net = createVoiceApi({ client: client(), tokens: tokens(), xhr: fakeXhr([{ fail: 'error' }]).Xhr });
    await expect(net.clip('a')).rejects.toMatchObject({ status: 0, code: 'network' });
    const slow = createVoiceApi({ client: client(), tokens: tokens(), xhr: fakeXhr([{ fail: 'timeout' }]).Xhr });
    await expect(slow.clip('a')).rejects.toMatchObject({ status: 0, code: 'timeout' });
    const ab = createVoiceApi({ client: client(), tokens: tokens(), xhr: fakeXhr([{ body: WAV }]).Xhr });
    const ctl = new AbortController();
    const p = ab.clip('a', { signal: ctl.signal });
    ctl.abort();
    await expect(p).rejects.toBeInstanceOf(StreamAbortedError);
    const none = createVoiceApi({ client: client(), tokens: null, xhr: fakeXhr([{ body: WAV }]).Xhr });
    await expect(none.clip('a')).rejects.toBeInstanceOf(AuthRequiredError);
  });
});

describe('createVoiceApi.clip - latency', () => {
  it('onHeaders fires when the 200 headers arrive, before the body (once, with duration)', async () => {
    jest.useFakeTimers();
    try {
      const { Xhr } = fakeXhr([{ body: WAV, bodyDelayMs: 5000, headers: { 'X-Venera-Duration-Ms': '4840', 'X-Venera-Sample-Rate': '8000' } }]);
      const api = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr });
      const onHeaders = jest.fn();
      let done = false;
      const p = api.clip('Salom.', { onHeaders }).then(() => {
        done = true;
      });
      await jest.advanceTimersByTimeAsync(1);
      expect(onHeaders).toHaveBeenCalledTimes(1);
      expect(onHeaders).toHaveBeenCalledWith({ durationMs: 4840, sampleRate: 8000 });
      expect(done).toBe(false);
      await jest.advanceTimersByTimeAsync(5000);
      await p;
      expect(done).toBe(true);
      expect(onHeaders).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });

  it('onHeaders is not called for an error status', async () => {
    const { Xhr } = fakeXhr([{ status: 503, body: enc('{}') }]);
    const api = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr });
    const onHeaders = jest.fn();
    await expect(api.clip('a', { onHeaders })).rejects.toMatchObject({ status: 503 });
    expect(onHeaders).not.toHaveBeenCalled();
  });

  it('a cached token (peekToken) sends the request synchronously, without awaiting SecureStore', () => {
    const { Xhr, sent } = fakeXhr([{ body: WAV }]);
    const tp: TokenProvider = { getToken: jest.fn(async () => 'slow'), refreshToken: jest.fn(async () => 'r'), peekToken: () => 'mem' };
    const api = createVoiceApi({ client: client(), tokens: tp, xhr: Xhr });
    void api.clip('Salom.');
    // Hech qanday await'siz: so'rov shu chaqiruv ichida ketdi.
    expect(sent).toHaveLength(1);
    expect(sent[0].headers.Authorization).toBe('Bearer mem');
    expect(tp.getToken).not.toHaveBeenCalled();
  });

  it('onSent fires right after the request is sent (latency trace)', () => {
    const { Xhr, sent } = fakeXhr([{ body: WAV }]);
    const tp: TokenProvider = { getToken: jest.fn(async () => 'slow'), refreshToken: jest.fn(async () => 'r'), peekToken: () => 'mem' };
    const api = createVoiceApi({ client: client(), tokens: tp, xhr: Xhr });
    const onSent = jest.fn(() => {
      expect(sent).toHaveLength(1);
    });
    void api.clip('Salom.', { onSent });
    expect(onSent).toHaveBeenCalledTimes(1);
  });

  it('no cached token -> falls back to getToken()', async () => {
    const { Xhr, sent } = fakeXhr([{ body: WAV }]);
    const tp: TokenProvider = { getToken: jest.fn(async () => 'stored'), refreshToken: jest.fn(async () => 'r'), peekToken: () => null };
    const api = createVoiceApi({ client: client(), tokens: tp, xhr: Xhr });
    await api.clip('Salom.');
    expect(sent[0].headers.Authorization).toBe('Bearer stored');
  });
});

describe('createVoiceApi.hold', () => {
  it('GETs the clip in the chosen voice', async () => {
    const { Xhr, sent } = fakeXhr([{ body: WAV }]);
    const api = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr });
    const res = await api.hold('kutish-ilk-1a2b', 'uz_male_news');
    expect(res?.bytes.length).toBe(WAV.length);
    expect(sent[0].method).toBe('GET');
    expect(sent[0].url).toBe('https://x.uz/api/v1/tts/hold/kutish-ilk-1a2b.wav?voice=uz_male_news');
    expect(sent[0].timeout).toBe(4_000);
    expect(sent[0].body).toBeNull();
  });

  it('is silent (null) on 404, on any failure and for a malformed key', async () => {
    const api404 = createVoiceApi({ client: client(), tokens: tokens(), xhr: fakeXhr([{ status: 404, body: enc('{}') }]).Xhr });
    expect(await api404.hold('kutish-1', 'uz_female_calm')).toBeNull();
    const net = createVoiceApi({ client: client(), tokens: tokens(), xhr: fakeXhr([{ fail: 'error' }]).Xhr });
    expect(await net.hold('kutish-1', 'uz_female_calm')).toBeNull();
    const { Xhr, sent } = fakeXhr([{ body: WAV }]);
    const bad = createVoiceApi({ client: client(), tokens: tokens(), xhr: Xhr });
    expect(await bad.hold('../secret', 'uz_female_calm')).toBeNull();
    expect(sent).toHaveLength(0);
  });
});

describe('createVoiceChatStream', () => {
  /** NDJSON oqimi uchun matnli XHR (chatStream.test.ts dagidek). */
  function textXhr(chunks: string[], headers: Record<string, string> = {}) {
    const sent: { url: string; body: unknown }[] = [];
    class X {
      readyState = 0;
      status = 0;
      responseText = '';
      timeout = 0;
      onreadystatechange: (() => void) | null = null;
      onprogress: (() => void) | null = null;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      ontimeout: (() => void) | null = null;
      onabort: (() => void) | null = null;
      private url = '';
      open(_m: string, url: string) {
        this.url = url;
      }
      setRequestHeader() {}
      getResponseHeader(n: string) {
        return headers[n] ?? null;
      }
      abort() {
        this.onabort?.();
      }
      send(body: unknown) {
        sent.push({ url: this.url, body });
        setTimeout(() => {
          this.status = 200;
          this.readyState = 2;
          this.onreadystatechange?.();
          for (const c of chunks) {
            this.responseText += c;
            this.onprogress?.();
          }
          this.onload?.();
        }, 0);
      }
    }
    return { Xhr: X as unknown as new () => XMLHttpRequest, sent };
  }

  it('adds voice:true and input:"voice" to the normal chat body and parses hold frames', async () => {
    const { Xhr, sent } = textXhr(
      ['{"type":"hold","text":"Bir daqiqa","clip":"kutish-1","at":1,"topic":"hrm"}\n{"type":"tok', 'en","text":"Javob."}\n{"type":"done"}\n'],
      { 'X-Venera-Turn': 'cd'.repeat(16) },
    );
    const stream = createVoiceChatStream(new ApiClient({ baseUrl: 'https://x.uz', tokens: tokens(), xhr: Xhr }));
    const frames: ChatFrame[] = [];
    const onTurn = jest.fn();
    await stream('Bugun kim kechikdi?', (f) => frames.push(f), { chatId: 'c1', mode: 'pro', locale: 'uz', onTurn });
    expect(sent[0].url).toBe('https://x.uz/api/v1/chat/stream');
    expect(JSON.parse(String(sent[0].body))).toEqual({ question: 'Bugun kim kechikdi?', mode: 'pro', chatId: 'c1', locale: 'uz', voice: true, input: 'voice' });
    expect(frames.map((f) => f.type)).toEqual(['hold', 'token', 'done']);
    expect(frames[0]).toMatchObject({ clip: 'kutish-1', at: 1 });
    expect(onTurn).toHaveBeenCalledWith('cd'.repeat(16));
  });
});

describe('decodeUtf8', () => {
  it('decodes multi-byte text (Uzbek, Cyrillic, emoji)', () => {
    const s = "Oʻzbekiston - Ташкент 👍";
    expect(decodeUtf8(enc(s))).toBe(s);
  });
});

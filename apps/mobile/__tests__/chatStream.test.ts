/**
 * Chat oqimi: NDJSON bo'laklari qatorning o'rtasida uzilsa ham kadrlar to'g'ri yig'iladi;
 * ApiClient.stream XHR `onprogress` dagi o'sib boruvchi `responseText` ni bo'laklarga
 * ajratadi, 401 da tokenni bir marta yangilaydi, xato konvertini ApiError qiladi.
 */
import { createChatApi, createNdjsonParser, type ChatFrame } from '@/api/chat';
import { ApiClient, ApiError, StreamAbortedError, type TokenProvider } from '@/api/client';

function tokens(): TokenProvider {
  let n = 1;
  return { getToken: jest.fn(async () => `t${n}`), refreshToken: jest.fn(async () => `t${++n}`) };
}

/** Soxta XHR: `script` - har yuborishda qaytariladigan javob (holat + bo'laklar). */
function fakeXhr(script: { status: number; chunks: string[]; headers?: Record<string, string> }[]) {
  const sent: { url: string; headers: Record<string, string>; body: unknown }[] = [];
  let call = 0;
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
    private h: Record<string, string> = {};
    private resHeaders: Record<string, string> = {};
    open(_m: string, url: string) {
      this.url = url;
    }
    setRequestHeader(k: string, v: string) {
      this.h[k] = v;
    }
    getResponseHeader(name: string) {
      return this.resHeaders[name] ?? null;
    }
    abort() {
      this.onabort?.();
    }
    send(body: unknown) {
      sent.push({ url: this.url, headers: this.h, body });
      const step = script[Math.min(call, script.length - 1)];
      call += 1;
      setTimeout(() => {
        this.status = step.status;
        this.resHeaders = step.headers ?? {};
        this.readyState = 2;
        this.onreadystatechange?.();
        for (const c of step.chunks) {
          this.responseText += c;
          this.onprogress?.();
        }
        this.readyState = 4;
        this.onload?.();
      }, 0);
    }
  }
  return { Xhr: X as unknown as new () => XMLHttpRequest, sent };
}

describe('createNdjsonParser', () => {
  it('joins lines split across chunks and skips broken lines', () => {
    const frames: ChatFrame[] = [];
    const p = createNdjsonParser((f) => frames.push(f));
    p.push('{"type":"stage","text":"Qidir');
    p.push('yapman"}\n{"type":"tok');
    p.push('en","text":"Sa"}\nnot json\n{"type":"token","text":"lom"}');
    p.end();
    expect(frames.map((f) => f.type)).toEqual(['stage', 'token', 'token']);
    expect(frames[0].text).toBe('Qidiryapman');
    expect(frames.map((f) => f.text).slice(1).join('')).toBe('Salom');
  });
});

describe('chat stream over XHR', () => {
  it('streams frames as they arrive, sends mobile channel + chatId, reads the turn header', async () => {
    const { Xhr, sent } = fakeXhr([
      {
        status: 200,
        headers: { 'X-Venera-Turn': 'turn-1' },
        chunks: ['{"type":"token","text":"Bugun "}\n{"type":"tok', 'en","text":"kechikmadingiz."}\n', '{"type":"done","engine":"v3"}\n'],
      },
    ]);
    const client = new ApiClient({ baseUrl: 'https://x.uz', tokens: tokens(), xhr: Xhr, getLanguage: () => 'uz' });
    const api = createChatApi(client);
    const frames: ChatFrame[] = [];
    const onTurn = jest.fn();
    await api.stream('Bugun kechikdimmi?', (f) => frames.push(f), { chatId: 'c1', mode: 'standard', locale: 'uz', onTurn });
    expect(frames.map((f) => f.type)).toEqual(['token', 'token', 'done']);
    expect(onTurn).toHaveBeenCalledWith('turn-1');
    expect(sent[0].url).toBe('https://x.uz/api/v1/chat/stream');
    expect(sent[0].headers['X-Venera-Client']).toBe('mobile');
    expect(sent[0].headers.Authorization).toBe('Bearer t1');
    expect(JSON.parse(String(sent[0].body))).toEqual({ question: 'Bugun kechikdimmi?', chatId: 'c1', locale: 'uz' });
  });

  it('401 before any data -> refreshes once and retries', async () => {
    const { Xhr, sent } = fakeXhr([
      { status: 401, chunks: ['{"message":"expired"}'] },
      { status: 200, chunks: ['{"type":"token","text":"ok"}\n'] },
    ]);
    const tp = tokens();
    const api = createChatApi(new ApiClient({ baseUrl: 'https://x.uz', tokens: tp, xhr: Xhr }));
    const frames: ChatFrame[] = [];
    await api.stream('q', (f) => frames.push(f));
    expect(tp.refreshToken).toHaveBeenCalledTimes(1);
    expect(sent[1].headers.Authorization).toBe('Bearer t2');
    expect(frames).toHaveLength(1);
  });

  it('HTTP error envelope -> ApiError with the server code', async () => {
    const { Xhr } = fakeXhr([{ status: 429, chunks: ['{"code":"rate_limited","message":"Juda ko\'p so\'rov"}'] }]);
    const api = createChatApi(new ApiClient({ baseUrl: 'https://x.uz', tokens: tokens(), xhr: Xhr }));
    await expect(api.stream('q', () => {})).rejects.toMatchObject({ status: 429, code: 'rate_limited' });
  });

  it('abort -> StreamAbortedError', async () => {
    const { Xhr } = fakeXhr([{ status: 200, chunks: ['{"type":"token","text":"a"}\n'] }]);
    const api = createChatApi(new ApiClient({ baseUrl: 'https://x.uz', tokens: tokens(), xhr: Xhr }));
    const ctl = new AbortController();
    const p = api.stream('q', () => {}, { signal: ctl.signal });
    ctl.abort();
    await expect(p).rejects.toBeInstanceOf(StreamAbortedError);
    expect(ApiError).toBeDefined();
  });
});

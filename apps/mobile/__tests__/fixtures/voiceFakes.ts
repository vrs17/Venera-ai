/**
 * Ovozli rejim testlari uchun soxtalar: boshqariladigan soat, mikrofon (dB ssenariysi),
 * pleer, fayllar, TTS API va chat oqimi. Hech biri tarmoq yoki native modulga tegmaydi.
 */
import { ApiError, StreamAbortedError } from '@/api/client';
import type { ChatFrame, StreamOptions } from '@/api/chat';
import type { WavBytes } from '@/api/voice';
import type { ChatStreamFn } from '@/features/chat/chatStore';
import type { AudioFiles, AudioModePort, ClipPlayer, Clock, MicFrame, MicPort } from '@/features/voice/ports';

/** Python `wave` moduli yozgan haqiqiy fayl: 8 kHz, mono, 16-bit, 50 ms (25 ms 440 Hz + 25 ms jimlik). */
export const PY_WAV_B64 = 'UklGRkQDAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YSADAAAAAOAP4R1YKAsuTC4TKf8eQRF4AYTxRuNt2EHSf9E81urfY+0P/RMNjRvEJmYtqi5pKiUh9RNpBFj0p+UU2v3SONH71NXdueoh+jkKHRkJJZQs2i6VKykjlRZVBzj3JOji2+bTINHm0+LbJOg491UHlRYpI5Ur2i6ULAklHRk5CiH6uerV3fvUONH90hTap+VY9GkE9RMlIWkqqi5mLcQmjRsTDQ/9Y+3q3zzWf9FB0m3YRuOE8XgBQRH/HhMpTC4LLlgo4R3gDwAAIPAf4qjX9dG00e3WAeG/7oj+fA66HJMnvy2BLsQpFiCdEvEC7fJz5DzZmtJW0ZfV294L7Jf7qAtZGuwlAy3ILgUrKyJHFd8Fx/Xj5vfabNMm0WvU19xr6av4yAjcFx4kGizgLhosHiTcF8gIq/hr6dfca9Qm0WzT99rj5sf13wVHFSsiBSvILgMt7CVZGqgLl/sL7Nvel9VW0ZrSPNlz5O3y8QKdEhYgxCmBLr8tkye6HHwOiP6/7gHh7da00fXRqNcf4iDwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==';

export function b64ToBytes(b64: string): Uint8Array {
  return new Uint8Array(Buffer.from(b64, 'base64'));
}

/** Oddiy 44 baytli WAV: doimiy amplitudali sinus (`amp` 0 - jimlik). */
export function makeWav(ms: number, amp = 8000, rate = 8000): Uint8Array {
  const n = Math.round((rate * ms) / 1000);
  const out = new Uint8Array(44 + n * 2);
  const v = new DataView(out.buffer);
  const ascii = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) out[at + i] = s.charCodeAt(i);
  };
  ascii(0, 'RIFF');
  v.setUint32(4, 36 + n * 2, true);
  ascii(8, 'WAVE');
  ascii(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  ascii(36, 'data');
  v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.round(amp * Math.sin((2 * Math.PI * 440 * i) / rate)), true);
  return out;
}

/** Bitta ADTS kadri (16 kHz, 1 blok = 64 ms); `payload` - sarlavhadan keyingi baytlar. */
export function adtsFrame(payload = 20, sfIndex = 8, blocks = 1, fill = 0): Uint8Array {
  const len = 7 + payload;
  const f = new Uint8Array(len);
  f[0] = 0xff;
  f[1] = 0xf1;
  f[2] = (1 << 6) | (sfIndex << 2);
  f[3] = (1 << 6) | ((len >> 11) & 0x03);
  f[4] = (len >> 3) & 0xff;
  f[5] = ((len & 0x07) << 5) | 0x1f;
  f[6] = 0xfc | ((blocks - 1) & 0x03);
  f.fill(fill, 7);
  return f;
}

/** `count` ta kadr; har kadr to'ldiruvchisi - uning tartib raqami (kesilganini tekshirish uchun). */
export function adtsStream(count: number): Uint8Array {
  const parts = Array.from({ length: count }, (_, i) => adtsFrame(20, 8, 1, i % 256));
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

export async function flush(times = 3): Promise<void> {
  for (let i = 0; i < times; i++) await new Promise((r) => setImmediate(r));
}

interface Timer {
  id: number;
  at: number;
  fn: () => void;
  every: number | null;
}

/** Qo'lda suriladigan soat: `advance` taymerlarni tartib bilan bajaradi va promise'larni bo'shatadi. */
export class FakeClock implements Clock {
  t = 0;
  private seq = 0;
  private timers: Timer[] = [];
  now = () => this.t;
  setTimeout = (fn: () => void, ms: number) => {
    const id = ++this.seq;
    this.timers.push({ id, at: this.t + Math.max(0, ms), fn, every: null });
    return id;
  };
  clearTimeout = (h: unknown) => {
    this.timers = this.timers.filter((x) => x.id !== h);
  };
  setInterval = (fn: () => void, ms: number) => {
    const id = ++this.seq;
    this.timers.push({ id, at: this.t + ms, fn, every: ms });
    return id;
  };
  clearInterval = (h: unknown) => this.clearTimeout(h);
  get pending(): number {
    return this.timers.length;
  }
  async advance(ms: number): Promise<void> {
    const target = this.t + ms;
    for (;;) {
      const due = this.timers.filter((x) => x.at <= target).sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) break;
      this.t = Math.max(this.t, due.at);
      if (due.every) due.at += due.every;
      else this.timers = this.timers.filter((x) => x !== due);
      due.fn();
      await flush(1);
    }
    this.t = target;
    await flush();
  }
}

/** Mikrofon: `dbAt(mutlaq ms)` ssenariysi; segment fayli - davomiyligiga mos ADTS. */
export class FakeMic implements MicPort {
  recording = false;
  starts = 0;
  stops = 0;
  failNextStart = false;
  /** Mikrofon ochilish kechikishi: fayl `record()` dan shuncha ms keyin boshlanadi (Android). */
  captureLatencyMs = 0;
  /** `start()` shuncha ms (soxta soat bo'yicha) davom etadi (prepare + record). */
  startDelayMs = 0;
  dbAt: (absMs: number) => number = () => -55;
  /** Har segment boshlangan mutlaq vaqt (kadr i - fayl vaqti i*64 ms). */
  segStarts: number[] = [];
  private segStart = 0;
  private uri: string | null = null;
  constructor(
    private clock: FakeClock,
    private files: FakeFiles,
  ) {}
  async start() {
    if (this.failNextStart) {
      this.failNextStart = false;
      throw new Error('prepare failed');
    }
    if (this.startDelayMs) await new Promise<void>((r) => this.clock.setTimeout(r, this.startDelayMs));
    this.recording = true;
    this.starts++;
    this.segStart = this.clock.now();
    this.segStarts.push(this.segStart);
    this.uri = `file:///cache/recording-${this.starts}.aac`;
  }
  poll(): MicFrame | null {
    if (!this.recording) return null;
    return { tMs: this.clock.now() - this.segStart, db: this.dbAt(this.clock.now()) };
  }
  async stop() {
    if (!this.recording) return null;
    this.recording = false;
    this.stops++;
    const frames = Math.max(1, Math.ceil((this.clock.now() - this.segStart - this.captureLatencyMs) / 64));
    if (this.uri) this.files.store.set(this.uri, adtsStream(frames));
    return this.uri;
  }
}

export class FakeFiles implements AudioFiles {
  store = new Map<string, Uint8Array>();
  removed: string[] = [];
  write(dir: string, name: string, bytes: Uint8Array) {
    const uri = `file:///cache/${dir}/${name}`;
    this.store.set(uri, bytes);
    return uri;
  }
  async read(uri: string) {
    const b = this.store.get(uri);
    if (!b) throw new Error(`no file ${uri}`);
    return b;
  }
  find(dir: string, name: string) {
    const uri = `file:///cache/${dir}/${name}`;
    return this.store.has(uri) ? uri : null;
  }
  remove(uri: string | null | undefined) {
    if (!uri) return;
    this.removed.push(uri);
    this.store.delete(uri);
  }
  clear(dir: string) {
    for (const k of [...this.store.keys()]) if (k.startsWith(`file:///cache/${dir}/`)) this.store.delete(k);
  }
}

export class FakePlayer implements ClipPlayer {
  plays: string[] = [];
  current: string | null = null;
  stops = 0;
  paused = false;
  disposed = false;
  private startedAt = 0;
  private ends = new Set<() => void>();
  constructor(private clock: FakeClock) {}
  play(uri: string) {
    this.plays.push(uri);
    this.current = uri;
    this.paused = false;
    this.startedAt = this.clock.now();
  }
  pause() {
    this.paused = true;
  }
  resume() {
    this.paused = false;
  }
  stop() {
    this.stops++;
    this.current = null;
  }
  positionMs() {
    return this.current ? this.clock.now() - this.startedAt : 0;
  }
  onEnd(cb: () => void) {
    this.ends.add(cb);
    return () => this.ends.delete(cb);
  }
  dispose() {
    this.disposed = true;
  }
  /** Joriy klip tabiiy tugadi. */
  finish() {
    this.current = null;
    for (const cb of [...this.ends]) cb();
  }
}

interface ClipCall {
  text: string;
  opts: { voice?: string; speed?: number; turnId?: string | null; signal?: AbortSignal };
  resolve: (w?: Uint8Array) => void;
  reject: (e: unknown) => void;
}

/** TTS API: har `clip` so'rovi test qo'lda yakunlaguncha kutib turadi. */
export class FakeVoiceApi {
  calls: ClipCall[] = [];
  holdCalls: { clip: string; voice: string }[] = [];
  holdBytes: Uint8Array | null = makeWav(2500, 6000);
  clipWav: Uint8Array = makeWav(2000, 8000);
  clip = jest.fn(
    (text: string, opts: ClipCall['opts'] = {}) =>
      new Promise<WavBytes>((resolve, reject) => {
        const call: ClipCall = {
          text,
          opts,
          resolve: (w) => resolve({ bytes: w ?? this.clipWav, sampleRate: 8000, durationMs: null, truncated: false }),
          reject,
        };
        opts.signal?.addEventListener('abort', () => reject(new StreamAbortedError()));
        this.calls.push(call);
      }),
  );
  hold = jest.fn(async (clip: string, voice: string) => {
    this.holdCalls.push({ clip, voice });
    return this.holdBytes ? { bytes: this.holdBytes, sampleRate: 8000, durationMs: null, truncated: false } : null;
  });
  get inFlight(): number {
    return this.calls.filter((c) => !(c as { done?: boolean }).done).length;
  }
  /** i-chi so'rovni muvaffaqiyatli yakunlash. */
  ok(i: number, wav?: Uint8Array) {
    (this.calls[i] as { done?: boolean }).done = true;
    this.calls[i].resolve(wav);
  }
  fail(i: number, status: number) {
    (this.calls[i] as { done?: boolean }).done = true;
    this.calls[i].reject(new ApiError(status, status === 501 ? 'not_implemented' : 'unavailable', 'x'));
  }
}

export class FakeMode implements AudioModePort {
  log: string[] = [];
  enter = jest.fn(async ({ earpiece }: { earpiece: boolean }) => {
    this.log.push(`enter:${earpiece}`);
  });
  setEarpiece = jest.fn(async (on: boolean) => {
    this.log.push(`earpiece:${on}`);
  });
  playbackOnly = jest.fn(async () => {
    this.log.push('playback');
  });
  restore = jest.fn(async () => {
    this.log.push('restore');
  });
}

export interface StreamCall {
  question: string;
  onFrame: (f: ChatFrame) => void;
  opts: StreamOptions;
  resolve: () => void;
  reject: (e: unknown) => void;
}

/** Chat oqimi: test kadrlarni o'zi yuboradi va oqimni yakunlaydi. */
export function controllableStream() {
  const calls: StreamCall[] = [];
  const fn: ChatStreamFn = (question, onFrame, opts = {}) =>
    new Promise<void>((resolve, reject) => {
      calls.push({ question, onFrame, opts, resolve, reject });
      opts.signal?.addEventListener('abort', () => reject(new StreamAbortedError()));
    });
  return { fn: jest.fn(fn), calls };
}

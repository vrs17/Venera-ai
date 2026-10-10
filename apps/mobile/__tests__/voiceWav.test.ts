/**
 * WAV: Python `wave` yozgan haqiqiy sarlavha o'qiladi; egri chiziq uzunligi = ceil(davomiylik/20);
 * PCM bo'lmagan fayl xato beradi (speaker buni "failed" deb oladi).
 */
import { envelopeAt, envelopeMaxDb, envelopeOf, parseWav } from '@/features/voice/wav';

import { b64ToBytes, makeWav, PY_WAV_B64 } from './fixtures/voiceFakes';

describe('parseWav', () => {
  it('parses a header written by Python wave', () => {
    const pcm = parseWav(b64ToBytes(PY_WAV_B64));
    expect(pcm.sampleRate).toBe(8000);
    expect(pcm.samples).toHaveLength(400);
    expect(pcm.durationMs).toBeCloseTo(50);
    // birinchi yarmi ovoz, ikkinchi yarmi jimlik
    expect(Math.max(...Array.from(pcm.samples.slice(0, 200)))).toBeGreaterThan(10000);
    expect(Math.max(...Array.from(pcm.samples.slice(200)).map(Math.abs))).toBe(0);
  });

  it('walks chunks (extra LIST chunk before data) and tolerates a streaming size field', () => {
    const base = makeWav(100);
    const list = new Uint8Array([0x4c, 0x49, 0x53, 0x54, 4, 0, 0, 0, 1, 2, 3, 4]);
    const bytes = new Uint8Array(base.length + list.length);
    bytes.set(base.slice(0, 36));
    bytes.set(list, 36);
    bytes.set(base.slice(36), 36 + list.length);
    expect(parseWav(bytes).samples).toHaveLength(800);
    const streamed = makeWav(100);
    new DataView(streamed.buffer).setUint32(40, 0xffffffff, true);
    expect(parseWav(streamed).samples).toHaveLength(800);
  });

  it('throws on non-PCM, stereo or garbage', () => {
    const notPcm = makeWav(20);
    new DataView(notPcm.buffer).setUint16(20, 3, true);
    expect(() => parseWav(notPcm)).toThrow();
    const stereo = makeWav(20);
    new DataView(stereo.buffer).setUint16(22, 2, true);
    expect(() => parseWav(stereo)).toThrow();
    expect(() => parseWav(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]))).toThrow();
  });
});

describe('envelope', () => {
  it('has ceil(duration / 20) hops and follows loudness', () => {
    const env = envelopeOf(parseWav(b64ToBytes(PY_WAV_B64)));
    expect(env.db).toHaveLength(Math.ceil(50 / 20));
    expect(env.db[0]).toBeGreaterThan(-15);
    expect(env.db[2]).toBeLessThan(-90);
    expect(envelopeAt(env, 5).level).toBeGreaterThan(0.3);
  });

  it('max dB over a window, null outside the clip', () => {
    const env = envelopeOf(parseWav(makeWav(1000, 8000)));
    const max = envelopeMaxDb(env, 200, 360) as number;
    // 8000/32768 sinus RMS ~ -15.2 dBFS
    expect(max).toBeGreaterThan(-16.5);
    expect(max).toBeLessThan(-14);
    expect(envelopeMaxDb(env, -500, -10)).toBeNull();
    expect(envelopeMaxDb(env, 5000, 6000)).toBeNull();
  });
});

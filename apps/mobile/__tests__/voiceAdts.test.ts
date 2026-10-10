/**
 * ADTS kesish: 16 kHz, 1 blokli kadr = 64 ms; oraliqqa tegadigan kadrlar qoladi;
 * buzuq dum (uzilgan yozuv) tahlilni to'xtatadi, butun faylni emas.
 */
import { adtsDurationMs, parseAdts, trimAdts } from '@/features/voice/adts';

import { adtsFrame, adtsStream } from './fixtures/voiceFakes';

describe('parseAdts', () => {
  it('16 kHz single-block frames are 64 ms each', () => {
    const frames = parseAdts(adtsStream(5));
    expect(frames).toHaveLength(5);
    expect(frames[1].startMs).toBeCloseTo(64);
    expect(frames[4].durMs).toBeCloseTo(64);
    expect(adtsDurationMs(adtsStream(10))).toBeCloseTo(640);
  });

  it('multi-block and other sample rates change the duration', () => {
    // sfIndex 11 = 8000 Hz, 2 blok -> 2048/8000 s = 256 ms
    const f = parseAdts(adtsFrame(10, 11, 2));
    expect(f[0].durMs).toBeCloseTo(256);
  });

  it('stops at the first invalid header (truncated / garbage tail)', () => {
    const good = adtsStream(3);
    const tail = new Uint8Array([0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc, 0xde, 0xf0, 0x00]);
    const bytes = new Uint8Array(good.length + tail.length);
    bytes.set(good);
    bytes.set(tail, good.length);
    expect(parseAdts(bytes)).toHaveLength(3);
    // Oxirgi kadr yarmida uzilgan
    expect(parseAdts(good.slice(0, good.length - 5))).toHaveLength(2);
  });
});

describe('trimAdts', () => {
  it('keeps exactly the frames touching the window', () => {
    const bytes = adtsStream(20); // 0..1280 ms
    const out = trimAdts(bytes, 300, 700) as Uint8Array;
    const frames = parseAdts(out);
    // 300 ms 4-kadr ichida (256..320), 700 ms 10-kadr ichida (640..704) -> 4..10 = 7 kadr
    expect(frames).toHaveLength(7);
    // Har kadr to'ldiruvchisi - asl tartib raqami
    expect(out[frames[0].offset + 7]).toBe(4);
    expect(out[frames[6].offset + 7]).toBe(10);
  });

  it('open end keeps everything after fromMs; empty window gives null', () => {
    expect(parseAdts(trimAdts(adtsStream(10), 500) as Uint8Array)).toHaveLength(3);
    expect(trimAdts(adtsStream(10), 5000, 6000)).toBeNull();
    expect(trimAdts(new Uint8Array([1, 2, 3]), 0, 100)).toBeNull();
  });
});

import { createHash } from 'crypto';

import { Sha256, sha256Hex } from '@/lib/sha256';

const nodeSha = (b: Uint8Array) => createHash('sha256').update(b).digest('hex');

describe('sha256', () => {
  it('matches known vectors', () => {
    expect(sha256Hex(new Uint8Array())).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    expect(sha256Hex(new TextEncoder().encode('abc'))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });

  it('matches node crypto for many sizes, incrementally', () => {
    for (const size of [1, 55, 56, 63, 64, 65, 127, 128, 1000, 4099, 70_001]) {
      const data = new Uint8Array(size).map((_, i) => (i * 31 + 7) & 0xff);
      const h = new Sha256();
      // Tasodifiy bo'laklarga bo'lib beramiz - natija bir xil bo'lishi kerak.
      let off = 0;
      let step = 1;
      while (off < size) {
        h.update(data.subarray(off, Math.min(size, off + step)));
        off += step;
        step = (step * 7 + 3) % 97 || 1;
      }
      expect(h.length).toBe(size);
      expect(h.hex()).toBe(nodeSha(data));
    }
  });

  it('refuses use after finalize', () => {
    const h = new Sha256();
    h.hex();
    expect(() => h.update(new Uint8Array([1]))).toThrow();
  });
});

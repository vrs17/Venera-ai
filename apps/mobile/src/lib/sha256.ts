/**
 * Toza TypeScript SHA-256, BOSQICHMA-BOSQICH (incremental) hisoblash bilan.
 *
 * NIMA UCHUN o'zimizniki: `/complete` butun faylning sha256'ini so'raydi
 * (spec 3.2 #5). 3 soatlik yozuv ~65 MB - uni xotiraga bir butun o'qib
 * bo'lmaydi, expo-crypto esa faqat bir martalik `digest()` beradi. Shuning
 * uchun chunk yuklanayotganda hash shu yerda yig'ib boriladi.
 * Chunk'ning o'z hash'i (`X-Chunk-Sha256`) native expo-crypto bilan olinadi.
 */

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const HEX = Array.from({ length: 256 }, (_, i) => i.toString(16).padStart(2, '0'));

export function toHex(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i++) out += HEX[bytes[i]];
  return out;
}

export class Sha256 {
  private h = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  private block = new Uint8Array(64);
  private blockLen = 0;
  private total = 0; // bytes
  private w = new Uint32Array(64);
  private finished = false;

  /** Hash'langan baytlar soni (resume paytida tekshirish uchun). */
  get length(): number {
    return this.total;
  }

  update(data: Uint8Array): this {
    if (this.finished) throw new Error('sha256: already finalized');
    let pos = 0;
    this.total += data.length;
    if (this.blockLen > 0) {
      const take = Math.min(64 - this.blockLen, data.length);
      this.block.set(data.subarray(0, take), this.blockLen);
      this.blockLen += take;
      pos = take;
      if (this.blockLen === 64) {
        this.compress(this.block, 0);
        this.blockLen = 0;
      }
    }
    while (pos + 64 <= data.length) {
      this.compress(data, pos);
      pos += 64;
    }
    if (pos < data.length) {
      this.block.set(data.subarray(pos), 0);
      this.blockLen = data.length - pos;
    }
    return this;
  }

  digest(): Uint8Array {
    if (this.finished) throw new Error('sha256: already finalized');
    this.finished = true;
    const bitLenHi = Math.floor(this.total / 0x20000000);
    const bitLenLo = (this.total << 3) >>> 0;
    const pad = new Uint8Array(this.blockLen < 56 ? 64 : 128);
    pad.set(this.block.subarray(0, this.blockLen));
    pad[this.blockLen] = 0x80;
    const end = pad.length;
    pad[end - 8] = (bitLenHi >>> 24) & 0xff;
    pad[end - 7] = (bitLenHi >>> 16) & 0xff;
    pad[end - 6] = (bitLenHi >>> 8) & 0xff;
    pad[end - 5] = bitLenHi & 0xff;
    pad[end - 4] = (bitLenLo >>> 24) & 0xff;
    pad[end - 3] = (bitLenLo >>> 16) & 0xff;
    pad[end - 2] = (bitLenLo >>> 8) & 0xff;
    pad[end - 1] = bitLenLo & 0xff;
    for (let off = 0; off < pad.length; off += 64) this.compress(pad, off);
    const out = new Uint8Array(32);
    for (let i = 0; i < 8; i++) {
      out[i * 4] = (this.h[i] >>> 24) & 0xff;
      out[i * 4 + 1] = (this.h[i] >>> 16) & 0xff;
      out[i * 4 + 2] = (this.h[i] >>> 8) & 0xff;
      out[i * 4 + 3] = this.h[i] & 0xff;
    }
    return out;
  }

  hex(): string {
    return toHex(this.digest());
  }

  private compress(data: Uint8Array, off: number): void {
    const w = this.w;
    for (let i = 0; i < 16; i++) {
      const j = off + i * 4;
      w[i] = ((data[j] << 24) | (data[j + 1] << 16) | (data[j + 2] << 8) | data[j + 3]) >>> 0;
    }
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15];
      const b = w[i - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = this.h[0];
    let b = this.h[1];
    let c = this.h[2];
    let d = this.h[3];
    let e = this.h[4];
    let f = this.h[5];
    let g = this.h[6];
    let h = this.h[7];
    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    this.h[0] = (this.h[0] + a) >>> 0;
    this.h[1] = (this.h[1] + b) >>> 0;
    this.h[2] = (this.h[2] + c) >>> 0;
    this.h[3] = (this.h[3] + d) >>> 0;
    this.h[4] = (this.h[4] + e) >>> 0;
    this.h[5] = (this.h[5] + f) >>> 0;
    this.h[6] = (this.h[6] + g) >>> 0;
    this.h[7] = (this.h[7] + h) >>> 0;
  }
}

export function sha256Hex(data: Uint8Array): string {
  return new Sha256().update(data).hex();
}

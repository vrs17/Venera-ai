/**
 * UUID v4 - `clientId` (server idempotentlik kaliti, spec 3.2 #2).
 *
 * Tasodifiy baytlar tashqaridan beriladi: ilovada expo-crypto
 * (`getRandomBytes`), testda deterministik generator. Shu sababli bu modul
 * native kodga bog'liq emas.
 */
export function uuidV4(randomBytes: (n: number) => Uint8Array): string {
  const b = randomBytes(16);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function hexKey(randomBytes: (n: number) => Uint8Array, n = 32): string {
  return Array.from(randomBytes(n), (x) => x.toString(16).padStart(2, '0')).join('');
}

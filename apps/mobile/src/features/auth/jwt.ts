/**
 * Venera JWT'ning ochiq qismi (payload) - FAQAT o'qish, imzo tekshirilmaydi.
 *
 * NIMA UCHUN: Mini App (WebView) tokenni muddatisiz yuboradi
 * (`{type:'venera:auth', token}`). `exp` - qachon yangilash kerakligi, `sub` -
 * Mini App boshqa odam bilan kirganini bilish (eski odamning qurilma tokeni
 * bilan yangi odamning sessiyasi yangilanmasin). Ishonch qarori bu yerda YO'Q -
 * server har so'rovda imzoni o'zi tekshiradi.
 *
 * `atob` ga tayanmaymiz: Hermes/Jest/eski WebView'da bir xil ishlashi uchun
 * base64url o'zimizda dekodlanadi.
 */
export interface JwtClaims {
  sub: string | null;
  /** epoch ms (JWT `exp` soniyada keladi). */
  expiresAt: number | null;
}

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

/** base64url -> UTF-8 matn. Buzuq kirish - null. */
export function base64UrlDecode(input: string): string | null {
  const s = input.replace(/-/g, '+').replace(/_/g, '/').replace(/=+$/, '');
  if (!/^[A-Za-z0-9+/]*$/.test(s) || s.length % 4 === 1) return null;
  const bytes: number[] = [];
  let acc = 0;
  let bits = 0;
  for (const ch of s) {
    acc = ((acc << 6) | ALPHABET.indexOf(ch)) & 0xffffff;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((acc >> bits) & 0xff);
    }
  }
  try {
    return decodeURIComponent(bytes.map((b) => `%${b.toString(16).padStart(2, '0')}`).join(''));
  } catch {
    return null;
  }
}

/** JWT bo'lmasa yoki payload o'qilmasa - null. */
export function decodeJwtClaims(token: string): JwtClaims | null {
  const parts = token.split('.');
  if (parts.length !== 3 || !parts[1]) return null;
  const json = base64UrlDecode(parts[1]);
  if (json === null) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(json);
  } catch {
    return null;
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const p = payload as Record<string, unknown>;
  const exp = typeof p.exp === 'number' && Number.isFinite(p.exp) && p.exp > 0 ? Math.round(p.exp * 1000) : null;
  return { sub: typeof p.sub === 'string' && p.sub ? p.sub : null, expiresAt: exp };
}

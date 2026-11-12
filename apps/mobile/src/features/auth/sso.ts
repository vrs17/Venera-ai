/**
 * BRB-Tech ID (Keycloak SSO) bilan kirish - tizim brauzerida (RFC 8252).
 *
 * OQIM: ilova PKCE verifier va challenge yasaydi -> verifier'ni SecureStore'ga yozadi ->
 * brauzerda `GET /api/v1/auth/sso/start?channel=mobile&return=venera-rec://sso&app_challenge=..`
 * ni ochadi -> odam Keycloak'da kiradi -> server ilovaga `venera-rec://sso?sso=<kod>` bilan
 * qaytaradi (`app/sso.tsx`) -> ilova `POST /auth/sso/exchange {code, verifier}` -> sessiya.
 *
 * NEGA PKCE: `venera-rec://` sxemasini telefondagi boshqa ilova ham ro'yxatdan o'tkazishi
 * mumkin va kodni ushlab olishi mumkin. Server kodni faqat challenge'ga mos verifier bilan
 * almashtiradi - verifier esa shu ilovaning SecureStore'idan chiqmaydi.
 *
 * Bu fayl sof: kripto va xotira tashqaridan beriladi (testlar uchun).
 */
import type { SsoConfig } from '@/api/types';

/** Server qaytaradigan manzil - serverdagi `SSO_MOBILE_REDIRECT` bilan BIR XIL. */
export const SSO_RETURN = 'venera-rec://sso';
/** Verifier shuncha yashaydi: server kirishni 10 daqiqa kutadi (`PENDING_TTL`). */
export const VERIFIER_TTL_MS = 10 * 60 * 1000;
/** SecureStore kaliti (tokenlardan alohida). */
export const VERIFIER_KEY = 'barno.ssoVerifier';

export interface PkceCrypto {
  getRandomBytes(count: number): Uint8Array;
  /** SHA-256 -> base64 (standart, `+/=` bilan). */
  sha256Base64(data: string): Promise<string>;
}

export interface Kv {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
}

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** Baytlar -> base64url (`=` siz). Hermes'da `btoa` ga tayanmaymiz. */
export function bytesToBase64Url(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i];
    const b = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const c = i + 2 < bytes.length ? bytes[i + 2] : 0;
    const n = (a << 16) | (b << 8) | c;
    out += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63];
    if (i + 1 < bytes.length) out += ALPHABET[(n >> 6) & 63];
    if (i + 2 < bytes.length) out += ALPHABET[n & 63];
  }
  return out;
}

/** Standart base64 -> base64url (`=` siz). */
export function base64ToBase64Url(value: string): string {
  return value.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** RFC 7636: verifier 64 belgi (48 tasodifiy bayt), challenge = base64url(SHA-256(verifier)). */
export async function createPkce(crypto: PkceCrypto): Promise<{ verifier: string; challenge: string }> {
  const verifier = bytesToBase64Url(crypto.getRandomBytes(48));
  const challenge = base64ToBase64Url(await crypto.sha256Base64(verifier));
  return { verifier, challenge };
}

/** Brauzerda ochiladigan manzil. `startPath` - `GET /auth/sso/config` aytgani. */
export function ssoStartUrl(baseUrl: string, config: Pick<SsoConfig, 'startPath'>, challenge: string): string {
  const query = [
    ['channel', 'mobile'],
    ['return', SSO_RETURN],
    ['app_challenge', challenge],
  ]
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&');
  return `${baseUrl.replace(/\/+$/, '')}${config.startPath}?${query}`;
}

interface StoredVerifier {
  verifier: string;
  created: number;
}

export async function saveVerifier(kv: Kv, verifier: string, now = Date.now()): Promise<void> {
  const value: StoredVerifier = { verifier, created: now };
  await kv.setItemAsync(VERIFIER_KEY, JSON.stringify(value));
}

/** Saqlangan verifier - BIR MARTALIK (o'qilgach o'chiriladi); eskirgan yoki buzuq - `null`. */
export async function takeVerifier(kv: Kv, now = Date.now()): Promise<string | null> {
  let raw: string | null = null;
  try {
    raw = await kv.getItemAsync(VERIFIER_KEY);
  } finally {
    await kv.deleteItemAsync(VERIFIER_KEY).catch(() => {});
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredVerifier>;
    if (typeof parsed.verifier !== 'string' || typeof parsed.created !== 'number') return null;
    if (now - parsed.created > VERIFIER_TTL_MS || now < parsed.created - 60_000) return null;
    return parsed.verifier;
  } catch {
    return null;
  }
}

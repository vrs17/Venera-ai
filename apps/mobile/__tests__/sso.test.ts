import { createHash, randomBytes } from 'crypto';

import { buildSsoPath, sanitizeIncomingPath } from '@/features/entry/deepLink';
import {
  base64ToBase64Url,
  bytesToBase64Url,
  createPkce,
  saveVerifier,
  SSO_RETURN,
  ssoStartUrl,
  takeVerifier,
  VERIFIER_KEY,
  VERIFIER_TTL_MS,
  type Kv,
} from '@/features/auth/sso';

function memoryKv(): Kv & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItemAsync: async (k) => data.get(k) ?? null,
    setItemAsync: async (k, v) => void data.set(k, v),
    deleteItemAsync: async (k) => void data.delete(k),
  };
}

/** Server bilan BIR XIL hisob (`app/services/oidc.py: s256`). */
function serverS256(verifier: string): string {
  return createHash('sha256').update(verifier, 'ascii').digest('base64url');
}

describe('BRB-Tech ID (PKCE)', () => {
  it('encodes base64url like Node', () => {
    for (const n of [0, 1, 2, 3, 31, 32, 48, 65]) {
      const bytes = new Uint8Array(randomBytes(n));
      expect(bytesToBase64Url(bytes)).toBe(Buffer.from(bytes).toString('base64url'));
    }
    expect(base64ToBase64Url('+/+/ab==')).toBe('-_-_ab');
  });

  it('makes a verifier the server accepts and the matching S256 challenge', async () => {
    const { verifier, challenge } = await createPkce({
      getRandomBytes: (n) => new Uint8Array(randomBytes(n)),
      sha256Base64: async (data) => createHash('sha256').update(data).digest('base64'),
    });
    // Server: 43-128 belgi, `[A-Za-z0-9._~-]` (schemas/auth.py SsoExchangeRequest.verifier).
    expect(verifier).toMatch(/^[A-Za-z0-9._~-]{43,128}$/);
    // Server: app_challenge `^[A-Za-z0-9_-]{43}$` va S256(verifier).
    expect(challenge).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(challenge).toBe(serverS256(verifier));
  });

  it('builds the start URL with the mobile return address and the challenge only', () => {
    const url = ssoStartUrl('https://llm.test/', { startPath: '/api/v1/auth/sso/start' }, 'c'.repeat(43));
    const parsed = new URL(url);
    expect(`${parsed.origin}${parsed.pathname}`).toBe('https://llm.test/api/v1/auth/sso/start');
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      channel: 'mobile',
      return: SSO_RETURN,
      app_challenge: 'c'.repeat(43),
    });
  });

  it('keeps the verifier one-time and short-lived', async () => {
    const kv = memoryKv();
    await saveVerifier(kv, 'v'.repeat(64), 1000);
    expect(await takeVerifier(kv, 2000)).toBe('v'.repeat(64));
    expect(await takeVerifier(kv, 2000)).toBeNull();
    expect(kv.data.has(VERIFIER_KEY)).toBe(false);

    await saveVerifier(kv, 'v'.repeat(64), 1000);
    expect(await takeVerifier(kv, 1000 + VERIFIER_TTL_MS + 1)).toBeNull();
    kv.data.set(VERIFIER_KEY, 'not json');
    expect(await takeVerifier(kv, 1000)).toBeNull();
  });
});

describe('BRB-Tech ID return link', () => {
  const code = 'A'.repeat(43);

  it('passes only a well-formed code or error', () => {
    expect(sanitizeIncomingPath(`venera-rec://sso?sso=${code}&evil=1`)).toBe(`/sso?sso=${code}`);
    expect(sanitizeIncomingPath('venera-rec://sso?sso_error=blocked')).toBe('/sso?sso_error=blocked');
    expect(sanitizeIncomingPath('venera-rec://sso?sso=short')).toBe('/login');
    expect(sanitizeIncomingPath('venera-rec://sso?sso=%3Cscript%3E')).toBe('/login');
    expect(sanitizeIncomingPath('https://evil.example/sso?sso=' + code)).toBe('/');
    expect(buildSsoPath({ sso_error: 'Bad Thing' })).toBe('/login');
  });
});

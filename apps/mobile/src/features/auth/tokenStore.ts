/**
 * SecureStore kalitlari (spec 7.6). Faqat shu modul SecureStore'ga yozadi.
 *
 * NIMA UCHUN interfeys orqali: session.ts testlarda xotiradagi KV bilan
 * ishlaydi; ilovada expo-secure-store (Android Keystore bilan shifrlangan).
 */
export const KEYS = {
  token: 'venera.token',
  tokenExpiresAt: 'venera.tokenExpiresAt',
  deviceToken: 'venera.deviceToken',
  installKey: 'venera.installKey',
} as const;

export interface SecureKV {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
}

export interface StoredToken {
  token: string;
  expiresAt: number; // epoch ms
}

export interface TokenStore {
  getToken(): Promise<StoredToken | null>;
  setToken(token: string, expiresAtIso: string): Promise<void>;
  getDeviceToken(): Promise<string | null>;
  setDeviceToken(deviceToken: string): Promise<void>;
  /** Token + device token o'chadi. installKey QOLADI - u kirishga emas, deep link ishonchiga tegishli. */
  clearAuth(): Promise<void>;
  getInstallKey(): Promise<string | null>;
  setInstallKey(key: string): Promise<void>;
}

export function createTokenStore(kv: SecureKV): TokenStore {
  return {
    async getToken() {
      const [token, exp] = await Promise.all([kv.getItemAsync(KEYS.token), kv.getItemAsync(KEYS.tokenExpiresAt)]);
      if (!token) return null;
      const expiresAt = exp ? Date.parse(exp) : NaN;
      return { token, expiresAt: Number.isFinite(expiresAt) ? expiresAt : 0 };
    },
    async setToken(token, expiresAtIso) {
      await kv.setItemAsync(KEYS.token, token);
      await kv.setItemAsync(KEYS.tokenExpiresAt, expiresAtIso);
    },
    getDeviceToken: () => kv.getItemAsync(KEYS.deviceToken),
    setDeviceToken: (deviceToken) => kv.setItemAsync(KEYS.deviceToken, deviceToken),
    async clearAuth() {
      await kv.deleteItemAsync(KEYS.token);
      await kv.deleteItemAsync(KEYS.tokenExpiresAt);
      await kv.deleteItemAsync(KEYS.deviceToken);
    },
    getInstallKey: () => kv.getItemAsync(KEYS.installKey),
    setInstallKey: (key) => kv.setItemAsync(KEYS.installKey, key),
  };
}

/** Testlar va Jest uchun xotiradagi KV. */
export function memoryKV(initial: Record<string, string> = {}): SecureKV & { data: Map<string, string> } {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItemAsync: async (k) => data.get(k) ?? null,
    setItemAsync: async (k, v) => {
      data.set(k, v);
    },
    deleteItemAsync: async (k) => {
      data.delete(k);
    },
  };
}

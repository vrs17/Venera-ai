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
  /** Saqlangan token QAYSI Barno hisobiniki (`actorId`) - token bilan birga yoziladi va o'chadi. */
  tokenOwner: 'venera.tokenOwner',
  /** Telefondagi OXIRGI hisob (`actorId`) - sessiya tugasa ham qoladi, faqat tozalovchi chiqishda o'chadi. */
  owner: 'venera.owner',
} as const;

export interface SecureKV {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
}

export interface StoredToken {
  token: string;
  expiresAt: number; // epoch ms
  /** Token egasining `actorId` si (matn); noma'lum (1.3.13 dan qolgan token, Mini App tokeni) - null. */
  owner?: string | null;
}

export interface TokenStore {
  getToken(): Promise<StoredToken | null>;
  /** `owner` - tokenning Barno hisobi (`actorId`); berilmasa yoki null - noma'lum. */
  setToken(token: string, expiresAtIso: string, owner?: string | null): Promise<void>;
  getDeviceToken(): Promise<string | null>;
  setDeviceToken(deviceToken: string): Promise<void>;
  /**
   * Token (va uning egasi) + device token o'chadi. installKey QOLADI - u kirishga emas, deep link
   * ishonchiga tegishli. Oxirgi hisob (`owner`) ham QOLADI (`session.lastOwner`).
   */
  clearAuth(): Promise<void>;
  getInstallKey(): Promise<string | null>;
  setInstallKey(key: string): Promise<void>;
  /** Telefondagi oxirgi hisob (`actorId`) - maxfiy emas; `null` - o'chirish. */
  getOwner(): Promise<string | null>;
  setOwner(owner: string | null): Promise<void>;
}

export function createTokenStore(kv: SecureKV): TokenStore {
  return {
    async getToken() {
      const [token, exp, owner] = await Promise.all([
        kv.getItemAsync(KEYS.token),
        kv.getItemAsync(KEYS.tokenExpiresAt),
        kv.getItemAsync(KEYS.tokenOwner),
      ]);
      if (!token) return null;
      const expiresAt = exp ? Date.parse(exp) : NaN;
      return { token, expiresAt: Number.isFinite(expiresAt) ? expiresAt : 0, owner: owner || null };
    },
    async setToken(token, expiresAtIso, owner = null) {
      // Avval eski ega o'chadi: yozish o'rtasida o'qilsa yangi token ESKI egasi bilan ko'rinmasin.
      await kv.deleteItemAsync(KEYS.tokenOwner);
      await kv.setItemAsync(KEYS.token, token);
      await kv.setItemAsync(KEYS.tokenExpiresAt, expiresAtIso);
      if (owner) await kv.setItemAsync(KEYS.tokenOwner, owner);
    },
    getDeviceToken: () => kv.getItemAsync(KEYS.deviceToken),
    setDeviceToken: (deviceToken) => kv.setItemAsync(KEYS.deviceToken, deviceToken),
    async clearAuth() {
      await kv.deleteItemAsync(KEYS.tokenOwner);
      await kv.deleteItemAsync(KEYS.token);
      await kv.deleteItemAsync(KEYS.tokenExpiresAt);
      await kv.deleteItemAsync(KEYS.deviceToken);
    },
    getInstallKey: () => kv.getItemAsync(KEYS.installKey),
    setInstallKey: (key) => kv.setItemAsync(KEYS.installKey, key),
    getOwner: () => kv.getItemAsync(KEYS.owner),
    setOwner: (owner) => (owner ? kv.setItemAsync(KEYS.owner, owner) : kv.deleteItemAsync(KEYS.owner)),
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

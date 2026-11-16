/**
 * Sessiya: "bir marta kirasiz, keyin avtomatik" (spec 7.4, 7.6, 3.2 #29-31).
 *
 * Venera JWT 12 soat yashaydi va refresh yo'q. Shuning uchun login'dan keyin
 * qurilma ro'yxatdan o'tadi va uzoq muddatli `deviceToken` oladi. JWT eskirsa
 * (10 daqiqadan kam qolsa) `POST /auth/devices/session` yangisini beradi.
 *
 * Single-flight: bir vaqtda 5 ta so'rov 401 olsa ham yangilash BITTA bo'ladi -
 * aks holda server rate-limit (6/min) qurilmani bloklaydi.
 *
 * QURILMA TOKENI FAQAT YIG'ILISHLAR BO'LIMI YOQILGANLARGA (server 403/404 beradi).
 * Chat esa hammaga kerak: bo'lim yoqilmagan odam ham kiradi - JWT muddati
 * (12 soat) tugaguncha ishlatiladi, keyin qayta kirish so'raladi.
 * `adoptToken`/`ensureDevice` - tashqaridan kelgan tokenni sessiyaga aylantirish.
 */
import { ApiError, AuthRequiredError, type TokenProvider } from '@/api/client';
import type { AuthApi } from '@/api/meetings';
import type { AuthUser, LoginResponse, RegisterDeviceRequest } from '@/api/types';

import { UNKNOWN_OWNER, type OwnerStamp } from '@/features/upload/queueStore';

import { decodeJwtClaims } from './jwt';
import type { StoredToken, TokenStore } from './tokenStore';

/**
 * Yozuv egasi kaliti - Barno hisobining `actorId` si (matn). NIMA UCHUN JWT `sub` EMAS: bitta odamning
 * `sub` i kirish yo'liga qarab har xil (login + parol - email, BRB-Tech ID va qurilma sessiyasi - Keycloak
 * id), server esa yig'ilishni `actorId` bo'yicha saqlaydi. `sub` bilan odam O'Z yozuvini yo'qotardi.
 */
export function actorKey(user: Pick<AuthUser, 'actorId'> | null | undefined): string | null {
  const id = user?.actorId;
  return typeof id === 'number' && Number.isFinite(id) ? String(id) : null;
}


/** Token shundan kam qolgan bo'lsa oldindan yangilanadi. */
export const REFRESH_WINDOW_MS = 10 * 60 * 1000;
/** Qurilma tokenisiz (Mini App bergan) token shundan kam qolsa ishlatilmaydi - so'rov yo'lda o'lardi. */
export const MIN_USABLE_MS = 60 * 1000;
/** Token `exp` i o'qilmasa - server default'i (`token_ttl_hours` = 12). */
export const WEB_TOKEN_TTL_MS = 12 * 60 * 60 * 1000;

export class FeatureDisabledError extends Error {
  constructor(message = "Bu funksiya siz uchun hali yoqilmagan") {
    super(message);
    this.name = 'FeatureDisabledError';
  }
}

/** expired - device token o'tmadi (server bekor qilgan); signedOut - foydalanuvchi o'zi chiqdi. */
export type SessionEvent = 'signedIn' | 'signedOut' | 'expired';

/**
 * adopted - yangi token saqlandi (avval token yo'q edi yoki o'sha odamniki);
 * switched - saqlandi, lekin oldingi token BOSHQA (yoki noma'lum) odamniki edi -
 * chaqiruvchi keshni va ismni tozalashi kerak; unchanged - aynan shu token
 * allaqachon bor; invalid - muddati o'tgan/buzuq.
 */
export type AdoptResult = 'adopted' | 'switched' | 'unchanged' | 'invalid';

export interface SessionDeps {
  store: TokenStore;
  authApi: Pick<AuthApi, 'login' | 'logout' | 'registerDevice' | 'deviceSession' | 'revokeDevice'>;
  now?: () => number;
  /**
   * Egasi noma'lum token (1.3.13 dan qolgan) hisobi aniqlandi - `identify` yoki o'sha qurilma tokeni bilan
   * yangilash orqali (ya'ni O'SHA sessiya). `UNKNOWN_OWNER` taxminli qatorlar shu hisobga o'tkaziladi.
   * Yangi kirish (`loginWith`) buni chaqirmaydi: u boshqa odam bo'lishi mumkin.
   */
  onOwnerLearned?: (owner: string) => Promise<void> | void;
}

export interface Session extends TokenProvider {
  /** Login + qurilmani ro'yxatdan o'tkazish. 403/404 -> FeatureDisabledError, tokenlar o'chadi. */
  login(username: string, password: string, device: RegisterDeviceRequest): Promise<LoginResponse>;
  /** Tayyor kirish javobi (BRB-Tech ID: `POST /auth/sso/exchange`) -> sessiya va qurilma, `login` dagi kabi. */
  loginWith(res: LoginResponse, device: RegisterDeviceRequest): Promise<LoginResponse>;
  /** Server tomonda revoke + logout (best effort), keyin `wipe` (navbat, fayllar), keyin tokenlar. */
  logout(wipe?: () => Promise<void>): Promise<void>;
  /** Kirgan holatmi: device token bor YOKI yaroqli (Mini App bergan) token bor. Tarmoqqa chiqmaydi. */
  hasSession(): Promise<boolean>;
  subscribe(listener: (event: SessionEvent) => void): () => void;
  /**
   * Mini App bergan token (`venera:auth`). Tarmoqsiz: SecureStore'ga yoziladi va
   * darhol ishlatiladi. Boshqa odamning tokeni (JWT `sub` boshqa yoki noma'lum)
   * bo'lsa eski qurilma tokeni tashlanadi - aks holda yangilash OLDINGI odamning
   * sessiyasini qaytarardi; serverda bekor qilish fon rejimida (best effort).
   */
  adoptToken(token: string): Promise<AdoptResult>;
  /** Qurilma tokeni yo'q bo'lsa - joriy token bilan ro'yxatdan o'tkazish (best effort, single-flight). */
  ensureDevice(device: RegisterDeviceRequest): Promise<boolean>;
  /** WebView'ga beriladigan token: kamida `minValidityMs` yashaydigan (kerak bo'lsa yangilab). Yo'q - null, xato tashlamaydi. */
  webToken(minValidityMs?: number): Promise<string | null>;
  /**
   * HOZIRGI sessiya kimniki (`actorId`, navbat qatorining `owner` i bilan solishtiriladi): saqlangan token
   * bilan birga yozilgan ega. Token yo'q yoki egasi noma'lum (1.3.13 dan qolgan token) - null: bunday
   * holatda hech kimning yozuvi yuklanmaydi. Tarmoqqa chiqmaydi.
   */
  owner(): Promise<string | null>;
  /**
   * Telefondagi OXIRGI hisob (`actorId`): sessiya tashqaridan tugasa ham ("hamma joydan chiqarish", blok,
   * "Qayta ulanish") qoladi; faqat tozalovchi chiqishda (`logout(wipe)`) o'chadi. Kirmasdan yozilgan
   * yozuvning taxminiy egasi (`ownerHint`) va kirmagan holatda ro'yxatda ko'rinadigan yozuvlar shundan.
   */
  lastOwner(): Promise<string | null>;
  /**
   * Token bor, lekin egasi noma'lum (1.3.13 dan yangilangan telefon) bo'lsa - `fetchMe` (`GET /auth/me`)
   * bilan aniqlaydi va token yoniga yozadi. Ega ma'lum yoki token yo'q - tarmoqqa chiqmaydi. So'rov
   * paytida token almashgan bo'lsa natija tashlanadi (yangi tokenga eski odam yozilmasin).
   */
  identify(fetchMe: () => Promise<AuthUser>): Promise<void>;
  /**
   * Hozir yozilayotgan yozuv kimniki. Qat'iy ega - faqat server shu tokenni ilova oldinga chiqqandan beri
   * qabul qilgan bo'lsa (kirish, yangilash, yoki 2xx javob - `confirm`). Aks holda faqat taxmin: tokenning
   * hisobi (noma'lum bo'lsa `UNKNOWN_OWNER`), token yo'q bo'lsa oxirgi hisob. NIMA UCHUN: admin
   * "hamma joydan chiqarish" qilgandan keyin telefon boshqa odamga o'tsa, ilova buni birinchi 401 gacha
   * bilmaydi - shu oraliqda yozilgan yozuv eski hisobga qat'iy yozilsa, uni yozgan odam ololmasdi.
   */
  stamp(): Promise<OwnerStamp>;
  /**
   * Server shu tokenni qabul qildi (`TokenProvider.confirm`). Faqat ilova OLDINDA bo'lganda va so'rov shu
   * oldinga chiqishda boshlangan bo'lsa (`epoch`) hisobga olinadi - orqa fondagi yuklash tasdiqlamaydi.
   */
  confirm(token: string, epoch?: number): void;
  /** Hozirgi oldinga/orqaga son (`ApiClient` so'rov boshida oladi). */
  epoch(): number;
  /**
   * Ilova oldinga (true) yoki orqa fonga (false) o'tdi. Har o'tishda tasdiq bekor: qaytganda server qayta
   * qabul qilguncha yangi yozuvlar faqat taxmin bilan (shu orada telefon boshqa xodimga o'tgan bo'lishi mumkin).
   */
  setForeground(active: boolean): void;
}

export function createSession(deps: SessionDeps): Session {
  const now = deps.now ?? Date.now;
  const listeners = new Set<(e: SessionEvent) => void>();

  /**
   * Token nusxasi XOTIRADA (`peekToken` uchun). NIMA UCHUN: har `getToken()` ikki marta
   * SecureStore (Android Keystore) o'qiydi va natija JS navbatining oxirida keladi. Ovozli
   * javobda birinchi TTS so'rovi shu kutish orqasida turib qolishi mumkin - prod'dagi ~1.8 s
   * ning bir sababi deb TAXMIN qilingan, telefonda o'lchanmagan (dev build'dagi `[voice]` izi).
   *
   * Xavfsizlik: nusxa FAQAT shu modul orqali yangilanadi - token SecureStore'ga faqat shu yerda
   * yoziladi/o'chiriladi. `version` - o'qish paytida yozuv/o'chirish bo'lsa, kechikkan eski
   * o'qish yangi qiymatni bosib ketmasin.
   */
  let memo: StoredToken | null = null;
  let version = 0;
  const store: TokenStore = {
    async getToken() {
      const v = version;
      const stored = await deps.store.getToken();
      if (v === version) memo = stored;
      return stored;
    },
    async setToken(token, expiresAtIso, owner = null) {
      version++;
      memo = null;
      await deps.store.setToken(token, expiresAtIso, owner);
      version++;
      const expiresAt = Date.parse(expiresAtIso);
      memo = { token, expiresAt: Number.isFinite(expiresAt) ? expiresAt : 0, owner: owner ?? null };
    },
    async clearAuth() {
      version++;
      memo = null;
      await deps.store.clearAuth();
      version++;
      memo = null;
    },
    getDeviceToken: () => deps.store.getDeviceToken(),
    setDeviceToken: (deviceToken) => deps.store.setDeviceToken(deviceToken),
    getInstallKey: () => deps.store.getInstallKey(),
    setInstallKey: (key) => deps.store.setInstallKey(key),
    getOwner: () => deps.store.getOwner(),
    setOwner: (sub) => deps.store.setOwner(sub),
  };
  let inflight: Promise<string> | null = null;
  /** Server qabul qilgan token (shu jarayonda, ilova oxirgi marta oldinga chiqqandan beri). */
  let confirmed: string | null = null;
  let active = true;
  let fgEpoch = 0;
  /** `at` - jarayon boshlangandagi `fgEpoch`: o'shandan beri ilova orqaga/oldinga o'tmagan va hozir oldinda bo'lsa. */
  const markConfirmed = (token: string, at: number) => {
    if (active && at === fgEpoch) confirmed = token;
  };

  let registering: Promise<boolean> | null = null;
  /** Bo'lim yoqilmagan (403/404) tokenlar - shu jarayonda qayta urinilmaydi. */
  const refusedTokens = new Set<string>();

  const emit = (e: SessionEvent) => listeners.forEach((l) => l(e));

  async function doRefresh(): Promise<string> {
    const deviceToken = await store.getDeviceToken();
    if (!deviceToken) {
      if (await store.getToken()) {
        // Mini App bergan token (qurilma tokenisiz) tugadi yoki server rad etdi:
        // yangilab bo'lmaydi - bu haqiqatan "sessiya tugadi".
        await store.clearAuth();
        emit('expired');
      }
      // Hech qachon kirmagan (yoki chiqqan) - "sessiya tugadi" deyish noto'g'ri.
      throw new AuthRequiredError();
    }
    try {
      const at = fgEpoch;
      const prev = memo ?? (await store.getToken());
      const res = await deps.authApi.deviceSession(deviceToken);
      const owner = actorKey(res.user);
      await store.setToken(res.token, res.expiresAt, owner);
      markConfirmed(res.token, at);
      if (owner) {
        await store.setOwner(owner);
        // O'sha qurilma tokeni - o'sha sessiya: noma'lum bo'lgan hisob endi aniq.
        if (prev && !prev.owner) await deps.onOwnerLearned?.(owner);
      }
      return res.token;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        // Token bekor qilingan / muddati o'tgan / admin bloklagan.
        // Navbat SAQLANADI (spec 7.6) - faqat sessiya ma'lumotlari o'chadi.
        await store.clearAuth();
        emit('expired');
        throw new AuthRequiredError(e.message);
      }
      throw e;
    }
  }

  function refreshToken(): Promise<string> {
    if (!inflight) {
      inflight = doRefresh().finally(() => {
        inflight = null;
      });
    }
    return inflight;
  }

  async function tokenValidFor(minMs: number): Promise<string> {
    const stored = await store.getToken();
    if (stored && stored.expiresAt - now() > minMs) return stored.token;
    if (stored && stored.expiresAt - now() > MIN_USABLE_MS && !(await store.getDeviceToken())) {
      // Qurilma tokenisiz (Mini App bergan) - yangilab bo'lmaydi, muddati tugaguncha ishlatiladi.
      return stored.token;
    }
    return refreshToken();
  }

  const getToken = () => tokenValidFor(REFRESH_WINDOW_MS);

  const api: Session = {
    getToken,
    refreshToken,

    peekToken() {
      // `getToken()` ning tez yo'li bilan AYNI shart: yangilash oynasiga kirgan token null -
      // u holda chaqiruvchi `getToken()` ga boradi (yangilash shu yerda).
      if (memo && memo.expiresAt - now() > REFRESH_WINDOW_MS) return memo.token;
      return null;
    },

    async login(username, password, device) {
      const res = await deps.authApi.login({ username: username.trim(), password });
      return api.loginWith(res, device);
    },

    async loginWith(res, device) {
      const at = fgEpoch;
      const owner = actorKey(res.user);
      await store.setToken(res.token, res.expiresAt, owner);
      try {
        const reg = await deps.authApi.registerDevice(device, res.token);
        await store.setDeviceToken(reg.deviceToken);
      } catch (e) {
        if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
          // Yig'ilishlar bo'limi bu odam uchun yoqilmagan - chat baribir ishlaydi
          // (qurilma tokenisiz, JWT muddati tugaguncha).
          refusedTokens.add(res.token);
        } else {
          await store.clearAuth();
          throw e;
        }
      }
      // Oxirgi hisob FAQAT kirish muvaffaqiyatli bo'lganda (ro'yxatdan o'tish yiqilsa - oldingisi qoladi).
      if (owner) await store.setOwner(owner);
      markConfirmed(res.token, at);
      emit('signedIn');
      return res;
    },

    async logout(wipe) {
      // Chiqish boshlandi - yangi so'rovlar xotiradagi tokenni olmasin.
      version++;
      memo = null;
      const deviceToken = await store.getDeviceToken();
      // To'g'ridan-to'g'ri (nusxasiz): chiqish paytida xotiradagi nusxa qayta to'lmasin.
      const stored = await deps.store.getToken();
      // Server chaqiruvlari best effort: tarmoq bo'lmasa ham telefon tozalanadi.
      if (deviceToken) {
        try {
          await deps.authApi.revokeDevice(deviceToken);
        } catch {
          /* best effort */
        }
      }
      if (stored && stored.expiresAt > now()) {
        try {
          await deps.authApi.logout();
        } catch {
          /* best effort */
        }
      }
      if (wipe) await wipe();
      await store.clearAuth();
      // Tozalovchi chiqish - telefon endi hech kimniki emas (navbat ham `wipe` da o'chdi). "Qayta ulanish"
      // (wipe'siz) navbatni saqlaydi - oxirgi hisob ham qoladi, aks holda keyingi yozuvlar egasiz qolardi.
      if (wipe) await store.setOwner(null);
      emit('signedOut');
    },

    async hasSession() {
      if (await store.getDeviceToken()) return true;
      const stored = await store.getToken();
      return !!stored && stored.expiresAt - now() > MIN_USABLE_MS;
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    async adoptToken(token) {
      const claims = decodeJwtClaims(token);
      const expiresAt = claims?.expiresAt ?? now() + WEB_TOKEN_TTL_MS;
      if (!token || expiresAt - now() <= MIN_USABLE_MS) return 'invalid';
      const stored = await store.getToken();
      if (stored?.token === token) return 'unchanged';
      const deviceToken = await store.getDeviceToken();
      const prevSub = stored ? (decodeJwtClaims(stored.token)?.sub ?? null) : null;
      const sameUser = !!claims?.sub && claims.sub === prevSub;
      if (deviceToken && !sameUser) {
        await store.clearAuth();
        deps.authApi.revokeDevice(deviceToken).catch(() => {
          /* best effort: token telefondan allaqachon o'chdi */
        });
      }
      // Ega faqat o'sha odamning tokeni bo'lsa saqlanadi; boshqa odam - noma'lum (`identify` aniqlaydi).
      await store.setToken(token, new Date(expiresAt).toISOString(), sameUser ? (stored?.owner ?? null) : null);
      emit('signedIn');
      return stored && !sameUser ? 'switched' : 'adopted';
    },

    ensureDevice(device) {
      if (!registering) {
        registering = (async () => {
          if (await store.getDeviceToken()) return true;
          const stored = await store.getToken();
          if (!stored || stored.expiresAt - now() <= MIN_USABLE_MS || refusedTokens.has(stored.token)) return false;
          try {
            const reg = await deps.authApi.registerDevice(device, stored.token);
            // Shu orada chiqilgan yoki boshqa odam kirgan bo'lsa - qurilma eski sessiyaga bog'lanmasin.
            if ((await store.getToken())?.token !== stored.token) {
              deps.authApi.revokeDevice(reg.deviceToken).catch(() => {});
              return false;
            }
            await store.setDeviceToken(reg.deviceToken);
            return true;
          } catch (e) {
            // 403/404 - bo'lim bu odam uchun yoqilmagan: Mini App tokeni bilan qolamiz.
            if (e instanceof ApiError && (e.status === 403 || e.status === 404)) refusedTokens.add(stored.token);
            return false;
          }
        })().finally(() => {
          registering = null;
        });
      }
      return registering;
    },

    async webToken(minValidityMs = REFRESH_WINDOW_MS) {
      try {
        return await tokenValidFor(minValidityMs);
      } catch {
        return null;
      }
    },

    async owner() {
      // Xotiradagi nusxa (`memo`) - kirgan holatda SecureStore'ga bormaymiz (navbat har o'zgarishda so'raydi).
      const stored = memo ?? (await store.getToken());
      return stored?.owner ?? null;
    },

    async lastOwner() {
      return (await store.getOwner()) || null;
    },

    async identify(fetchMe) {
      const at = fgEpoch;
      const before = memo ?? (await store.getToken());
      if (!before || before.owner) return;
      const owner = actorKey(await fetchMe());
      const current = await store.getToken();
      if (!owner || !current || current.token !== before.token) return;
      await store.setToken(current.token, new Date(current.expiresAt).toISOString(), owner);
      await store.setOwner(owner);
      markConfirmed(current.token, at);
      await deps.onOwnerLearned?.(owner);
    },

    async stamp() {
      const stored = memo ?? (await store.getToken());
      if (stored) {
        if (stored.owner && confirmed === stored.token) return { owner: stored.owner, ownerHint: null };
        return { owner: null, ownerHint: stored.owner ?? UNKNOWN_OWNER };
      }
      return { owner: null, ownerHint: (await store.getOwner()) || null };
    },

    confirm(token, at = fgEpoch) {
      markConfirmed(token, at);
    },

    epoch() {
      return fgEpoch;
    },

    setForeground(next) {
      if (next === active) return;
      active = next;
      fgEpoch++;
      confirmed = null;
    },
  };
  return api;
}

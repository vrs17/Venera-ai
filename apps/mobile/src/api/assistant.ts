/**
 * Barno XOTIRASI va PLATFORMA KALITLARI (yordamchi 3.3, 2026-10-10) - faqat HTTP.
 * Web `apps/web/src/api/assistant.api.ts` bilan AYNI yo'llar, shakllar va xato qoidasi:
 *
 *   GET    /api/v1/assistant/memory                       {items, count}
 *   DELETE /api/v1/assistant/memory/{id}                  {deleted, status}; 404 `memory_not_found` - allaqachon yo'q
 *   DELETE /api/v1/assistant/memory?confirm=forget-all    HAMMASINI unutish
 *   GET    /api/v1/assistant/platforms                    {platforms: [...]}
 *   PUT    /api/v1/assistant/platforms/{id}               {enabled} -> yangilangan platforma
 *   PATCH  /api/v1/connectors/{id}                        {enabled} - "Chatda ishlatish" (HRM/CRM tokeni)
 *
 * Telefon yordamchiga HECH QACHON to'g'ridan-to'g'ri bormaydi: backend proksi qiladi va
 * `user_id` ni O'ZI qo'yadi (sessiyadan). Shuning uchun bu yerda `user_id` yo'q - boshqa
 * odamning xotirasini so'rashning yo'li ham yo'q.
 *
 * NOMLAR. `/api/v1/connectors` bizda BAND - u odamning HRM/CRM LOGIN tokenlari. Yordamchining
 * "Barno shu manbadan foydalansinmi" kalitlari esa PLATFORMALAR - ikki narsa bir nom olmasin.
 *
 * Javob "tolerant" o'qiladi (`toMemoryItem`, `toPlatform`): ro'yxat kaliti `platforms` yoki
 * `connectors`, maydon `user_enabled` yoki `userEnabled` - backend tomonda nom o'zgarsa ekran
 * bo'sh qolmasin, buzuq yozuv esa jim tashlansin (butun ro'yxatni yiqitmasin).
 */
import type { ConnectorStatus } from './chat';
import { ApiError, type ApiClient } from './client';

const V1 = '/api/v1';
const enc = encodeURIComponent;

export const ASSISTANT_ROUTES = {
  memory: `${V1}/assistant/memory`,
  memoryItem: (id: string) => `${V1}/assistant/memory/${enc(id)}`,
  platforms: `${V1}/assistant/platforms`,
  platform: (id: string) => `${V1}/assistant/platforms/${enc(id)}`,
  connector: (id: string) => `${V1}/connectors/${enc(id)}`,
} as const;

/**
 * "Hammasini unutish" tasdig'i (backend `assistant_extras.FORGET_ALL`). `true` emas - aniq
 * ibora: boshqa joydan ko'chirilgan `?confirm=true` xotirani o'chirib yubormasin. Usiz
 * backend 400 `confirm_required` bilan rad etadi va xizmatga bormaydi.
 */
export const FORGET_ALL_CONFIRM = 'forget-all';

export interface MemoryItem {
  /** "m12" (eslab qolingan / o'rganilgan) yoki "h3f2a..." (CRM vazifalaridan o'rganilgan tartib). */
  id: string;
  /** Barno saqlagan gap - foydalanuvchi tilida. UI uni MATN sifatida ko'rsatadi. */
  text: string;
  kind: 'preference' | 'fact' | 'routine' | (string & {});
  /** `user` - odam "eslab qol" degan; `learned` - so'rash/ishlash uslubidan o'rganilgan. */
  source: 'user' | 'learned' | (string & {});
  /** ISO vaqt; vazifalardan o'rganilgan tartibda yo'q. */
  created_at: string | null;
  updated_at: string | null;
}

export interface MemoryList {
  items: MemoryItem[];
  count: number;
}

export interface MemoryDeleteResult {
  deleted: string[];
  /** "deleted" yoki "empty" (o'chiradigan narsa yo'q edi). */
  status: 'deleted' | 'empty' | (string & {});
}

export interface Platform {
  /** "hrm", "crm", "dwh", "biznes247", "superapp", "biznes247_kb", "biznes247_help". */
  id: string;
  /** Xizmatning o'z nomi - bizda tarjima bo'lmasa ishlatiladi. */
  name: string;
  /** Xizmatning bir qatorlik izohi (o'zbekcha) - bizda tarjima bo'lmasa. */
  description: string;
  /** `live` - odamning o'z hisobi, `data` - bank raqamlari, `knowledge` - qo'llanmalar. */
  kind: 'live' | 'data' | 'knowledge' | (string & {});
  /** Chatda shu tizim tokeni kerak (HRM/CRM). */
  needs_login: boolean;
  /** Serverda yoqilgan. `false` - kulrang, odam yoqa olmaydi. */
  available: boolean;
  /** Odamning o'z kaliti. */
  user_enabled: boolean;
  /** available && user_enabled - Barno shu odam uchun ishlatadi. */
  enabled: boolean;
}

type Raw = Record<string, unknown>;

const isObj = (v: unknown): v is Raw => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null);
const bool = (v: unknown, fallback: boolean): boolean => (typeof v === 'boolean' ? v : fallback);

export function toMemoryItem(raw: unknown): MemoryItem | null {
  if (!isObj(raw)) return null;
  const id = str(raw.id) ?? (typeof raw.id === 'number' ? String(raw.id) : null);
  const text = str(raw.text);
  // Kalitsiz band o'chirib bo'lmaydi, matnsizi ko'rsatib bo'lmaydi - ikkalasi ham tashlanadi.
  if (!id || !text) return null;
  return {
    id,
    text: text.trim(),
    kind: str(raw.kind) ?? 'fact',
    source: str(raw.source) ?? 'learned',
    created_at: str(raw.created_at) ?? str(raw.createdAt),
    updated_at: str(raw.updated_at) ?? str(raw.updatedAt),
  };
}

export function toPlatform(raw: unknown): Platform | null {
  if (!isObj(raw)) return null;
  const id = str(raw.id);
  if (!id) return null;
  const available = bool(raw.available, true);
  const userEnabled = bool(raw.user_enabled ?? raw.userEnabled, true);
  return {
    id: id.trim().toLowerCase(),
    name: str(raw.name) ?? id,
    description: str(raw.description) ?? '',
    kind: str(raw.kind) ?? 'live',
    needs_login: bool(raw.needs_login ?? raw.needsLogin, false),
    available,
    user_enabled: userEnabled,
    enabled: bool(raw.enabled, available && userEnabled),
  };
}

function toDeleteResult(raw: unknown): MemoryDeleteResult {
  const o = isObj(raw) ? raw : {};
  const deleted = Array.isArray(o.deleted) ? o.deleted.filter((x): x is string => typeof x === 'string') : [];
  return { deleted, status: str(o.status) ?? (deleted.length ? 'deleted' : 'empty') };
}

export function createAssistantApi(client: ApiClient) {
  return {
    async listMemory(): Promise<MemoryList> {
      const raw = await client.request<unknown>(ASSISTANT_ROUTES.memory);
      const o = isObj(raw) ? raw : {};
      const items = (Array.isArray(o.items) ? o.items : []).map(toMemoryItem).filter((x): x is MemoryItem => x !== null);
      return { items, count: typeof o.count === 'number' ? o.count : items.length };
    },

    /** Bitta bandni butunlay o'chiradi. Qaytarib bo'lmaydi. */
    async deleteMemoryItem(id: string): Promise<MemoryDeleteResult> {
      return toDeleteResult(await client.request<unknown>(ASSISTANT_ROUTES.memoryItem(id), { method: 'DELETE' }));
    },

    /** HAMMASINI unutadi (CRM vazifalaridan o'rganilgan tartib ham). Suhbatlarga tegmaydi. */
    async forgetAllMemory(): Promise<MemoryDeleteResult> {
      const raw = await client.request<unknown>(ASSISTANT_ROUTES.memory, { method: 'DELETE', query: { confirm: FORGET_ALL_CONFIRM } });
      return toDeleteResult(raw);
    },

    async listPlatforms(): Promise<Platform[]> {
      const raw = await client.request<unknown>(ASSISTANT_ROUTES.platforms);
      const o = isObj(raw) ? raw : {};
      const list = Array.isArray(o.platforms) ? o.platforms : Array.isArray(o.connectors) ? o.connectors : Array.isArray(raw) ? raw : [];
      return list.map(toPlatform).filter((x): x is Platform => x !== null);
    },

    /**
     * Kalit. Tana FAQAT `{enabled}` (backend ortiqcha maydonni 422 bilan rad etadi - kimlik
     * so'rovdan olinmaydi). Javob - yangilangan platforma (buzuq bo'lsa `null`).
     */
    async setPlatform(id: string, enabled: boolean): Promise<Platform | null> {
      return toPlatform(await client.request<unknown>(ASSISTANT_ROUTES.platform(id), { method: 'PUT', body: { enabled } }));
    },

    /** "Chatda ishlatish" - bizning HRM/CRM token kaliti (web `updateConnector`). */
    setConnectorEnabled: (id: string, enabled: boolean) =>
      client.request<ConnectorStatus>(ASSISTANT_ROUTES.connector(id), { method: 'PATCH', body: { enabled } }),
  };
}

export type AssistantApi = ReturnType<typeof createAssistantApi>;

export type AssistantErrorKind = 'unavailable' | 'rateLimited' | 'network' | 'notFound' | 'generic';

/** Backend "bunday narsa yo'q" degan 404 kodlari (`assistant_extras._MESSAGES`). */
const NOT_FOUND_CODES: ReadonlySet<string> = new Set(['memory_not_found', 'platform_not_found']);

/**
 * Xato turi - ekran o'z tilidagi matnni ko'rsatadi (`set.assistantErr.*`).
 *
 * 404 - FAQAT backend kodi bilan (`memory_not_found`) "yo'q" (`notFound`). Kodsiz 404 - yo'l
 * topilmadi (ilova API'dan oldin chiqdi, API qaytarildi yoki nginx yo'li mos emas). Uni
 * "allaqachon unutilgan" desak odamga "unutildi" deyilardi, aslida hech narsa o'chmagan -
 * shuning uchun u "xizmat ishlamayapti" (`unavailable`). Web bilan bir xil qoida.
 */
export function assistantErrorKind(err: unknown): AssistantErrorKind {
  if (!(err instanceof ApiError)) return 'generic';
  // client.ts kodsiz 404 ga `not_found` qo'yadi - shuning uchun faqat aniq kodlar "yo'q".
  if (err.status === 404) return NOT_FOUND_CODES.has(err.code) ? 'notFound' : 'unavailable';
  // Vaqt tugashi - internet bor, Barno javob bermadi; qolgan 0 - tarmoqqa chiqib bo'lmadi.
  if (err.status === 0) return err.code === 'timeout' ? 'unavailable' : 'network';
  if (err.status === 429) return 'rateLimited';
  if (err.status >= 500) return 'unavailable';
  return 'generic';
}

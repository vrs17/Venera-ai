/**
 * Qo'ng'iroq yozuvlari importi holati: aniqlash yoqilganmi, avtomatik yuborish, rozilik
 * eslatmasi ko'rilganmi, suhbat tili va ALLAQACHON yuborilgan yozuvlar (takror yubormaslik).
 *
 * Saqlash `settingsStore` bilan bir xil yo'l (expo-sqlite/kv-store, sinxron), lekin ALOHIDA
 * kalit: bu bo'lim parallel qurildi va umumiy sozlamalar shakliga tegmaydi.
 *
 * Egasi (`owner` = actorId): holat bitta foydalanuvchiga tegishli. Telefonda boshqa odam
 * kirsa (owner boshqa) - holat tozalanadi: avtomatik yuborish va yuborilganlar ro'yxati
 * oldingi odamniki, yangi hisobga o'tib ketmasin.
 */
import { create } from 'zustand';

import type { Lang } from '@/api/types';

export interface SentMark {
  /** Navbat qatorining clientId'si. */
  c: string;
  /** Qachon yuborildi (epoch ms) - eski yozuvlarni kesish uchun. */
  at: number;
  /**
   * Serverdagi yig'ilish id'si (navbat qatoridan, yuklash boshlangach). NIMA UCHUN: qator
   * telefonda bir necha kundan keyin tozalanadi - "Yuborildi" kartasi baribir xulosaga ochilsin.
   */
  s?: string;
}

export interface CallsPrefs {
  owner: string | null;
  /** "Qo'ng'iroqlarni aniqlash" - foydalanuvchi rozilik eslatmasini ko'rib yoqqan. */
  enabled: boolean;
  autoSend: boolean;
  /**
   * Avtomatik yuborish yoqilgan vaqt (ms). NIMA UCHUN: yoqilganda telefondagi ESKI
   * shaxsiy qo'ng'iroqlar (yuzlab) jimgina serverga ketib qolmasin - faqat shundan keyingilari.
   */
  autoSendSince: number | null;
  /** Rozilik eslatmasi ko'rilgan vaqt (bir marta). */
  consentAt: number | null;
  /** Suhbat tili (transkripsiya); null - yozish ekranidagi oxirgi til. */
  language: Lang | null;
  /** callKey -> yuborilgan qator. */
  sent: Record<string, SentMark>;
}

export const DEFAULT_CALLS: CallsPrefs = {
  owner: null,
  enabled: false,
  autoSend: false,
  autoSendSince: null,
  consentAt: null,
  language: null,
  sent: {},
};

/** Yuborilganlar ro'yxati chegarasi - kv qiymati cheksiz o'smasin (eng eskisi tushadi). */
export const MAX_SENT = 1000;

const STORAGE_KEY = 'venera.calls.v1';

interface KVSync {
  getItemSync(key: string): string | null;
  setItemSync(key: string, value: string): void;
}

let storage: KVSync | null | undefined;

function loadStorage(): KVSync | null {
  if (storage !== undefined) return storage;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    storage = (require('expo-sqlite/kv-store') as { Storage: KVSync }).Storage ?? null;
  } catch {
    storage = null;
  }
  return storage;
}

const LANGS: readonly Lang[] = ['uz', 'ru', 'en'];
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function parseCallsPrefs(raw: string | null): CallsPrefs {
  if (!raw) return { ...DEFAULT_CALLS, sent: {} };
  try {
    const v = JSON.parse(raw) as Partial<CallsPrefs>;
    const sent: Record<string, SentMark> = {};
    if (v.sent && typeof v.sent === 'object') {
      for (const [k, m] of Object.entries(v.sent)) {
        if (m && typeof m.c === 'string' && typeof m.at === 'number') sent[k] = typeof m.s === 'string' && m.s ? { c: m.c, at: m.at, s: m.s } : { c: m.c, at: m.at };
      }
    }
    const enabled = v.enabled === true;
    return {
      owner: typeof v.owner === 'string' ? v.owner : null,
      enabled,
      autoSend: enabled && v.autoSend === true,
      autoSendSince: num(v.autoSendSince),
      consentAt: num(v.consentAt),
      language: LANGS.includes(v.language as Lang) ? (v.language as Lang) : null,
      sent,
    };
  } catch {
    return { ...DEFAULT_CALLS, sent: {} };
  }
}

function readInitial(): CallsPrefs {
  try {
    return parseCallsPrefs(loadStorage()?.getItemSync(STORAGE_KEY) ?? null);
  } catch {
    return { ...DEFAULT_CALLS, sent: {} };
  }
}

/** Eng eski belgilarni tashlab, ko'pi bilan MAX_SENT ta qoldiradi. */
export function pruneSent(sent: Record<string, SentMark>, max = MAX_SENT): Record<string, SentMark> {
  const keys = Object.keys(sent);
  if (keys.length <= max) return sent;
  const keep = keys.sort((a, b) => sent[b].at - sent[a].at).slice(0, max);
  const out: Record<string, SentMark> = {};
  for (const k of keep) out[k] = sent[k];
  return out;
}

interface CallsState extends CallsPrefs {
  set(patch: Partial<CallsPrefs>): void;
  markSent(key: string, clientId: string, at?: number): void;
  /** Yuborilgan yozuvlarga server id'sini yozib qo'yadi (clientId -> serverId). O'zgarish bo'lmasa yozmaydi. */
  linkServerIds(byClientId: ReadonlyMap<string, string>): void;
  /** Kirgan foydalanuvchi: boshqa odam bo'lsa holat tozalanadi. */
  adoptOwner(actorId: string): void;
  /** Chiqishda: hammasi boshlang'ich holatga. */
  reset(): void;
}

function persist(p: CallsPrefs): void {
  try {
    loadStorage()?.setItemSync(STORAGE_KEY, JSON.stringify(p));
  } catch {
    /* xotirada qoladi */
  }
}

function prefsOf(s: CallsState): CallsPrefs {
  return {
    owner: s.owner,
    enabled: s.enabled,
    autoSend: s.autoSend,
    autoSendSince: s.autoSendSince,
    consentAt: s.consentAt,
    language: s.language,
    sent: s.sent,
  };
}

export const useCalls = create<CallsState>((set, get) => {
  const commit = (patch: Partial<CallsPrefs>) => {
    set(patch);
    persist(prefsOf(get()));
  };
  return {
    ...readInitial(),
    set(patch) {
      const next = { ...patch };
      // Aniqlash o'chsa avtomatik yuborish ham o'chadi (ro'yxatsiz yuborish - kutilmagan xatti-harakat).
      if (next.enabled === false) next.autoSend = false;
      commit(next);
    },
    markSent(key, clientId, at = Date.now()) {
      commit({ sent: pruneSent({ ...get().sent, [key]: { c: clientId, at } }) });
    },
    linkServerIds(byClientId) {
      const cur = get().sent;
      let next: Record<string, SentMark> | null = null;
      for (const [k, m] of Object.entries(cur)) {
        const sid = byClientId.get(m.c);
        if (!sid || m.s === sid) continue;
        next ??= { ...cur };
        next[k] = { ...m, s: sid };
      }
      if (next) commit({ sent: next });
    },
    adoptOwner(actorId) {
      const cur = get().owner;
      if (cur === actorId) return;
      if (cur == null) commit({ owner: actorId });
      else commit({ ...DEFAULT_CALLS, sent: {}, owner: actorId });
    },
    reset() {
      commit({ ...DEFAULT_CALLS, sent: {} });
    },
  };
});

/** Chiqishda chaqiriladi (settings `doLogout`): yuborilganlar va tanlovlar keyingi odamga o'tmasin. */
export function resetCallsState(): void {
  useCalls.getState().reset();
}

/** Test uchun: KV ni almashtirish va holatni qayta o'qish. */
export function __setCallsStorage(kv: KVSync | null): void {
  storage = kv;
  useCalls.setState(readInitial());
}

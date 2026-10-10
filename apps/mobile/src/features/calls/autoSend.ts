/**
 * Avtomatik yuborish qarori (sof mantiq) va bitta skan (ro'yxat -> tanlash -> yuborish).
 *
 * XAVFSIZLIK qoidalari (har biri sababli):
 *  - Faqat `autoSendSince` dan keyingi qo'ng'iroqlar: yoqilgan zahoti telefondagi eski
 *    shaxsiy qo'ng'iroqlar jimgina serverga ketmasin.
 *  - Fayl "tinch" bo'lsin: Samsung faylni qo'ng'iroq DAVOMIDA yozadi. Oxirgi o'zgarishdan
 *    kamida 60 s o'tgan VA ikki ketma-ket skanda hajm bir xil - aks holda yarim yozuv ketardi.
 *  - Bir skanda ko'pi bilan MAX_PER_RUN ta (kutilmagan holatda ham tarmoq/server to'lib ketmasin).
 *  - Format mos emas / server chegarasidan katta - o'tkazib yuboriladi (ro'yxatda sababi ko'rinadi).
 */
import type { CallRecording } from '@/features/entry/nativeEntry';

import { callKey, QUIET_MS, type SendOutcome } from './send';

export { QUIET_MS };
export const MAX_PER_RUN = 10;
/** Bir skanda o'qiladigan eng ko'p yozuv (native chegara 500). */
export const SCAN_LIMIT = 100;

/** Skanlar orasidagi xotira: uri -> oxirgi ko'rilgan hajm. */
export type SizeMemory = Map<string, number>;

export interface AutoSendState {
  autoSendSince: number | null;
  sent: Record<string, unknown>;
}

export interface AutoSendPick {
  /** Hozir yuboriladiganlar (eskisi birinchi). */
  ready: CallRecording[];
  /** Nomzod bor, lekin hali "tinch" emas - birozdan keyin qayta skan kerak. */
  waiting: boolean;
}

export function pickAutoSend(recs: CallRecording[], state: AutoSendState, memory: SizeMemory, now: number, maxBytes: number | null): AutoSendPick {
  const ready: CallRecording[] = [];
  let waiting = false;
  const since = state.autoSendSince;
  if (since == null) return { ready, waiting };
  for (const r of recs) {
    if (!r.contentType || r.sizeBytes <= 0) continue;
    if (maxBytes && r.sizeBytes > maxBytes) continue;
    if (r.dateMs < since) continue;
    if (state.sent[callKey(r)]) continue;
    const stable = memory.get(r.uri) === r.sizeBytes && now - r.dateMs >= QUIET_MS;
    if (stable) ready.push(r);
    else waiting = true;
  }
  ready.sort((a, b) => a.dateMs - b.dateMs);
  if (ready.length > MAX_PER_RUN) {
    ready.length = MAX_PER_RUN;
    waiting = true;
  }
  return { ready, waiting };
}

/** Xotirani joriy skan bilan almashtiradi (o'chirilgan fayllar unutiladi). */
export function rememberSizes(memory: SizeMemory, recs: CallRecording[]): void {
  memory.clear();
  for (const r of recs) memory.set(r.uri, r.sizeBytes);
}

export interface AutoSendDeps {
  list(sinceMs: number, limit: number): Promise<CallRecording[]>;
  state(): AutoSendState;
  send(rec: CallRecording): Promise<SendOutcome>;
  memory: SizeMemory;
  maxBytes: number | null;
  now?: () => number;
}

export interface AutoSendResult {
  sent: number;
  /** true - "tinch" bo'lishini kutayotgan yozuv bor: chaqiruvchi qayta skanlasin. */
  recheck: boolean;
}

export async function runAutoSendOnce(deps: AutoSendDeps): Promise<AutoSendResult> {
  const now = deps.now ?? Date.now;
  const since = deps.state().autoSendSince;
  if (since == null) return { sent: 0, recheck: false };
  const recs = await deps.list(since, SCAN_LIMIT);
  const { ready, waiting } = pickAutoSend(recs, deps.state(), deps.memory, now(), deps.maxBytes);
  rememberSizes(deps.memory, recs);
  let sent = 0;
  let failed = false;
  let again = waiting;
  for (const r of ready) {
    const out = await deps.send(r);
    if (out.kind === 'queued') sent++;
    // Soat farqi tufayli yuborish "hali yozilmoqda" desa - keyinroq qayta skan.
    else if (out.kind === 'not_ready') again = true;
    // Nusxa xatosi (joy yo'q, o'qib bo'lmadi) - keyingi skanda qayta urinamiz, bu safar to'xtaymiz.
    else if (out.kind === 'error') {
      failed = true;
      break;
    }
  }
  return { sent, recheck: again && !failed };
}

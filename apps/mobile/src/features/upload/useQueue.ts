/** Navbat qatorlari (UI uchun), o'zgarishga obuna. */
import { useEffect, useState } from 'react';

import { useServices } from '@/services';

import { belongsTo, type QueueRow } from './queueStore';

async function viewerOf(session: { owner(): Promise<string | null>; lastOwner(): Promise<string | null> }): Promise<string | null> {
  try {
    return (await session.owner()) ?? (await session.lastOwner());
  } catch {
    return null;
  }
}

export interface QueueViewOptions {
  /**
   * true - telefondagi HAMMA qator (boshqa hisobniki ham). Faqat qo'lda chiqish ogohlantirishi uchun:
   * chiqish ularni ham o'chiradi. Qolgan hamma ekran - faqat joriy hisobniki va egasizlar.
   */
  all?: boolean;
}

export function useQueueRows(opts: QueueViewOptions = {}): QueueRow[] {
  return useQueue(opts).rows;
}

/**
 * Qatorlar + birinchi o'qish tugadimi. NIMA UCHUN `loaded`: birinchi renderda ro'yxat
 * bo'sh - "yozuv topilmadi" degan xulosani faqat navbat haqiqatan o'qilgandan keyin
 * chiqarish mumkin (aks holda har ochilishda bir lahza "topilmadi" ko'rinardi).
 *
 * Boshqa hisobning yozuvi (telefon boshqa xodimga o'tgan, `QueueRow.owner`) ko'rsatilmaydi -
 * u egasi qaytib kirganda yuklanadi. Egasiz (kirmasdan yozilgan) yozuv hammaga ko'rinadi: uni yozgan
 * odam «Qayta urinish» bilan o'ziga oladi. Hisob almashsa (sessiya hodisasi) ro'yxat qayta o'qiladi.
 */
export function useQueue(opts: QueueViewOptions = {}): { rows: QueueRow[]; loaded: boolean } {
  const { queue, session } = useServices();
  const all = opts.all === true;
  const [state, setState] = useState<{ rows: QueueRow[]; loaded: boolean }>({ rows: [], loaded: false });
  useEffect(() => {
    let alive = true;
    let seq = 0;
    const load = () => {
      const mine = ++seq;
      // Kirgan bo'lsa - o'sha hisob; kirilmagan bo'lsa - telefondagi oxirgi hisob (o'z yozuvlarini ko'rsin).
      const me = all ? Promise.resolve(null) : viewerOf(session);
      Promise.all([queue.list(), me])
        .then(([r, owner]) => {
          // Kechikkan eski o'qish yangisini bosib ketmasin (hisob almashgan paytda).
          if (alive && mine === seq) setState({ rows: all ? r : r.filter((row) => belongsTo(row, owner)), loaded: true });
        })
        .catch(() => alive && setState((s) => (s.loaded ? s : { ...s, loaded: true })));
    };
    load();
    const unsub = queue.subscribe(load);
    const unsubSession = session.subscribe(load);
    return () => {
      alive = false;
      unsub();
      unsubSession();
    };
  }, [queue, session, all]);
  return state;
}

/** Ro'yxat tepasida ko'rsatiladigan (serverda hali to'liq bo'lmagan) yozuvlar. */
export function pendingRows(rows: QueueRow[]): QueueRow[] {
  return rows.filter((r) => r.state !== 'done').sort((a, b) => b.startedAt.localeCompare(a.startedAt));
}

export function uploadPercent(r: QueueRow): number | null {
  if (!r.totalBytes) return null;
  return Math.min(100, Math.round((r.receivedBytes / r.totalBytes) * 100));
}

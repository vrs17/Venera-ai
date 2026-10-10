/** Navbat qatorlari (UI uchun), o'zgarishga obuna. */
import { useEffect, useState } from 'react';

import { useServices } from '@/services';

import type { QueueRow } from './queueStore';

export function useQueueRows(): QueueRow[] {
  return useQueue().rows;
}

/**
 * Qatorlar + birinchi o'qish tugadimi. NIMA UCHUN `loaded`: birinchi renderda ro'yxat
 * bo'sh - "yozuv topilmadi" degan xulosani faqat navbat haqiqatan o'qilgandan keyin
 * chiqarish mumkin (aks holda har ochilishda bir lahza "topilmadi" ko'rinardi).
 */
export function useQueue(): { rows: QueueRow[]; loaded: boolean } {
  const { queue } = useServices();
  const [state, setState] = useState<{ rows: QueueRow[]; loaded: boolean }>({ rows: [], loaded: false });
  useEffect(() => {
    let alive = true;
    const load = () =>
      queue
        .list()
        .then((r) => alive && setState({ rows: r, loaded: true }))
        .catch(() => alive && setState((s) => (s.loaded ? s : { ...s, loaded: true })));
    load();
    const unsub = queue.subscribe(load);
    return () => {
      alive = false;
      unsub();
    };
  }, [queue]);
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

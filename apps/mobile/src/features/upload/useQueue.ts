/** Navbat qatorlari (UI uchun), o'zgarishga obuna. */
import { useEffect, useState } from 'react';

import { useServices } from '@/services';

import type { QueueRow } from './queueStore';

export function useQueueRows(): QueueRow[] {
  const { queue } = useServices();
  const [rows, setRows] = useState<QueueRow[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () =>
      queue
        .list()
        .then((r) => alive && setRows(r))
        .catch(() => {});
    load();
    const unsub = queue.subscribe(load);
    return () => {
      alive = false;
      unsub();
    };
  }, [queue]);
  return rows;
}

/** Ro'yxat tepasida ko'rsatiladigan (serverda hali to'liq bo'lmagan) yozuvlar. */
export function pendingRows(rows: QueueRow[]): QueueRow[] {
  return rows.filter((r) => r.state !== 'done').sort((a, b) => b.startedAt.localeCompare(a.startedAt));
}

export function uploadPercent(r: QueueRow): number | null {
  if (!r.totalBytes) return null;
  return Math.min(100, Math.round((r.receivedBytes / r.totalBytes) * 100));
}

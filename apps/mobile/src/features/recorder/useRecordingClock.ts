/**
 * Yozuv soati ("Yozilmoqda 12:34") - chat qizil chizig'i, drawer "Yozish" tugmasi va
 * yozuvlar ro'yxatidagi jonli karta bitta manbadan o'qisin.
 *
 * Har soniya faqat `recording` holatida yangilanadi: pauzada vaqt to'xtagan (taymer
 * bekorga ishlamasin), yozuv yo'q paytda umuman taymer yo'q. Vaqt mashinadagi
 * `elapsedMs` dan - pauza chiqarilgan, fayldagi vaqtga mos.
 */
import { useNow } from '@/features/crm/useNow';
import { formatClock } from '@/features/meeting/formatDate';

import { useRecorderStore } from './RecorderProvider';
import { elapsedMs } from './recorderMachine';

export interface RecordingClock {
  /** `recording` yoki `paused` - qizil chiziq/jonli karta ko'rinadi. */
  live: boolean;
  paused: boolean;
  /** `12:34` yoki `1:02:10`. */
  label: string;
}

export function useRecordingClock(): RecordingClock {
  const machine = useRecorderStore((s) => s.machine);
  const recording = machine.status === 'recording';
  const paused = machine.status === 'paused';
  const now = useNow(recording);
  return {
    live: recording || paused,
    paused,
    label: formatClock(elapsedMs(machine, now) / 1000),
  };
}

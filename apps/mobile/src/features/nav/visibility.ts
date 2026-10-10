/**
 * "Yozuvlar" kirish nuqtalari (chat tepa paneli, drawer, Sozlamalardagi "Yozish va
 * xotira") qachon ko'rinadi.
 *
 * NIMA UCHUN faqat `config` emas: ilova internetsiz ochilsa server konfigi kelmaydi
 * (`config === null`), lekin telefonda yozuv bo'lishi mumkin - u holda ham yozuvlar
 * TOPILADIGAN bo'lsin (egasining "yozuvlarni qayerdan ko'raman?" shikoyati).
 */
import { useAuth } from '@/features/auth/authStore';
import { useRecorderStore } from '@/features/recorder/RecorderProvider';
import { isActive } from '@/features/recorder/recorderMachine';
import { useQueueRows } from '@/features/upload/useQueue';

/** Toza qoida (testlar uchun alohida). */
export function meetingsVisible(s: { configured: boolean; live: boolean; localRows: number }): boolean {
  return s.configured || s.live || s.localRows > 0;
}

export function useMeetingsVisible(): boolean {
  const configured = useAuth((s) => s.config !== null);
  const live = useRecorderStore((s) => isActive(s.machine));
  const rows = useQueueRows();
  return meetingsVisible({ configured, live, localRows: rows.length });
}

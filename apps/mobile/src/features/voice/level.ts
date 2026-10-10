/**
 * Tuman darajasi (0..1): mikrofon (foydalanuvchi) va Barno ovozi uchun bitta shkala.
 */

/**
 * Mikrofon dBFS -> 0..1. Nol nuqta - gap boshlanish chegarasidan 10 dB past: xona
 * shovqini tumanni "qimirlatmaydi", odatiy gap esa yarmidan yuqori ko'taradi.
 */
export function micLevel(db: number | null | undefined, startDb: number): number {
  if (db == null || !Number.isFinite(db) || db <= -100) return 0;
  return Math.min(1, Math.max(0, (db - (startDb - 10)) / 30));
}

/** Tez ko'tariladi, sekin tushadi - 30 Hz da ham silliq. */
export function smoothLevel(prev: number, target: number): number {
  return prev + (target - prev) * (target > prev ? 0.5 : 0.12);
}

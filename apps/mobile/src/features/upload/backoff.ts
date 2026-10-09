/**
 * Qayta urinish oralig'i (spec 7.5): 5 s * 2^n, +-20% jitter, 15 daqiqa tom.
 *
 * Jitter NIMA UCHUN: tarmoq qaytganda ko'p telefon bir vaqtda urinmasin.
 * `random` tashqaridan - testda deterministik.
 */
export const BASE_MS = 5_000;
export const CAP_MS = 15 * 60 * 1000;
export const JITTER = 0.2;

/** `attempt` - nechanchi muvaffaqiyatsiz urinish (1 dan). */
export function backoffMs(attempt: number, random: () => number = Math.random): number {
  const n = Math.max(0, attempt - 1);
  const base = Math.min(CAP_MS, BASE_MS * 2 ** Math.min(n, 20));
  const factor = 1 + (random() * 2 - 1) * JITTER;
  return Math.min(CAP_MS, Math.round(base * factor));
}

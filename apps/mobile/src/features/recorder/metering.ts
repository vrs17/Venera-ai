/**
 * Ovoz darajasi (spec 2.3): metering har 150 ms; -50 dBFS dan past 60 s
 * davom etsa "mikrofon jim" ogohlantiriladi (telefon cho'ntakda, mikrofon
 * boshqa ilovada band va h.k.).
 */
export const METERING_INTERVAL_MS = 150;
export const SILENCE_DB = -50;
export const SILENCE_MS = 60_000;
const FLOOR_DB = -60;

/** dBFS -> 0..1 (daraja ustunlari uchun). */
export function levelFromDb(db: number | null | undefined): number {
  if (db == null || !Number.isFinite(db)) return 0;
  const clamped = Math.max(FLOOR_DB, Math.min(0, db));
  return (clamped - FLOOR_DB) / -FLOOR_DB;
}

export interface SilenceDetector {
  /** Yangi o'lchov; jimlik `durationMs` dan uzoq bo'lsa true. */
  push(db: number | null | undefined, now: number): boolean;
  reset(now?: number): void;
}

export function createSilenceDetector(thresholdDb = SILENCE_DB, durationMs = SILENCE_MS): SilenceDetector {
  let quietSince: number | null = null;
  return {
    push(db, now) {
      const quiet = db == null || !Number.isFinite(db) || db < thresholdDb;
      if (!quiet) {
        quietSince = null;
        return false;
      }
      if (quietSince == null) quietSince = now;
      return now - quietSince >= durationMs;
    },
    reset(now) {
      quietSince = now ?? null;
    },
  };
}

/** So'nggi N darajani saqlaydigan halqa (ekrandagi ustunlar). */
export function pushLevel(levels: number[], level: number, max = 24): number[] {
  const next = levels.length >= max ? levels.slice(levels.length - max + 1) : levels.slice();
  next.push(level);
  return next;
}

/**
 * Pleerning joriy joyi (spec 3.2 P2): transkript hozir eshitilayotgan pufakchani
 * ajratib ko'rsatadi.
 *
 * NIMA UCHUN alohida store (prop emas): pleer har 250 ms da yangilanadi - vaqtni
 * prop qilib bersak butun sahifa (xulosa, transkript) har chorak soniyada qayta
 * chiziladi. Transkript esa faqat FAOL PUFAKCHA KALITINI tanlaydi va faqat u
 * o'zgarganda qayta chiziladi.
 */
import { create } from 'zustand';

export interface PlaybackState {
  /** Qaysi yozuv (yig'ilish id) ijro etilmoqda; null - pleer yo'q. */
  key: string | null;
  /** Joriy joy, soniya. */
  t: number;
  playing: boolean;
  /** Foydalanuvchi bir marta ijro etdimi (0:00 da turgan pleer birinchi pufakchani bo'yamasin). */
  started: boolean;
}

export const initialPlayback: PlaybackState = { key: null, t: 0, playing: false, started: false };

export const usePlayback = create<PlaybackState>(() => ({ ...initialPlayback }));

/** Pleer yozadi (status yangilanishida, ~250 ms). */
export function reportPlayback(key: string, t: number, playing: boolean): void {
  const cur = usePlayback.getState();
  const started = cur.key === key ? cur.started || playing : playing;
  if (cur.key === key && cur.t === t && cur.playing === playing && cur.started === started) return;
  usePlayback.setState({ key, t, playing, started });
}

/** Pleer yopilganda - eski joy boshqa yozuvda ko'rinib qolmasin. */
export function clearPlayback(key: string): void {
  if (usePlayback.getState().key === key) usePlayback.setState({ ...initialPlayback });
}

/**
 * Pleer ochib turgan telefondagi fayllar (hisoblagich bilan).
 *
 * NIMA UCHUN: "yuklangach o'chirish" (keepDays=0) rejimida uploader yuklash tugashi
 * bilan faylni o'chiradi. Foydalanuvchi aynan shu paytda yozuvni tinglayotgan bo'lsa,
 * Android pleeri keyingi siljitishda (±15 s, chiziq) faylni qayta ochadi va yiqiladi.
 * Ishlatilayotgan fayl hozir o'chirilmaydi - qator `keepUntil` (1 kun) da tozalanadi.
 */
const filesInUse = new Map<string, number>();

/** Pleer faylni ushlab turadi; qaytgan funksiya qo'yib yuboradi. */
export function holdFile(uri: string): () => void {
  filesInUse.set(uri, (filesInUse.get(uri) ?? 0) + 1);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const n = (filesInUse.get(uri) ?? 1) - 1;
    if (n <= 0) filesInUse.delete(uri);
    else filesInUse.set(uri, n);
  };
}

export function isFileInUse(uri: string): boolean {
  return (filesInUse.get(uri) ?? 0) > 0;
}

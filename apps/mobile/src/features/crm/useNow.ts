/**
 * Hozirgi vaqt (ms) - taymer bilan yangilanadi, `active` bo'lmasa to'xtaydi (yakunlangan
 * karta taymer ushlab turmasin).
 *
 * `deadline` berilsa (taklif muddati): undan uzoqda har 15 s, oxirgi ~75 s da har soniya
 * (pill soniyalarni ko'rsatadi), muddat yetgach - to'xtaydi. Berilmasa - har soniya
 * (kutish hisoblagichi). Ilova fondan qaytganda darhol yangilanadi: fonda taymer
 * uxlaydi, qolgan vaqt esa eskirgan bo'lib ko'rinmasin.
 */
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

const FAST_WITHIN_MS = 75_000;

function delayFor(now: number, deadline: number | null): number | null {
  if (deadline == null) return 1000;
  const left = deadline - now;
  if (left <= 0) return null;
  return left > FAST_WITHIN_MS ? Math.min(15_000, left - FAST_WITHIN_MS + 1000) : Math.min(1000, left);
}

export function useNow(active: boolean, deadline: number | null = null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = (from: number) => {
      const delay = delayFor(from, deadline);
      if (delay != null) timer = setTimeout(tick, delay);
    };
    const tick = () => {
      const at = Date.now();
      setNow(at);
      schedule(at);
    };
    schedule(Date.now());
    const sub = AppState.addEventListener('change', (st) => {
      if (st !== 'active') return;
      clearTimeout(timer);
      tick();
    });
    return () => {
      clearTimeout(timer);
      sub.remove();
    };
  }, [active, deadline]);
  return now;
}

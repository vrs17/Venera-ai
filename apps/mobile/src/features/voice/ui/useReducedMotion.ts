/**
 * Tizimdagi "Harakatni kamaytirish" (Android: animatsiyalarni o'chirish) sozlamasi.
 *
 * NIMA UCHUN: tuman doimiy suzib turadi - bosh aylanishi yoki diqqat muammosi bor odam
 * uchun bu noqulay. Sozlama yoqilsa tuman faqat shaffofligi bilan "gapiradi".
 * O'qib bo'lmasa (Jest, eski qurilma) - oddiy harakat.
 */
import { useEffect, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    let alive = true;
    try {
      AccessibilityInfo.isReduceMotionEnabled()
        .then((v) => {
          if (alive) setReduced(!!v);
        })
        .catch(() => {});
    } catch {
      /* API yo'q - oddiy harakat */
    }
    let sub: { remove(): void } | null = null;
    try {
      sub = AccessibilityInfo.addEventListener('reduceMotionChanged', (v) => setReduced(!!v));
    } catch {
      sub = null;
    }
    return () => {
      alive = false;
      sub?.remove();
    };
  }, []);
  return reduced;
}

/**
 * Ekran o'quvchi (TalkBack) yoqilganmi.
 *
 * NIMA UCHUN: ovozli rejimda ikki ovoz bor - Barno va odamning o'zi. TalkBack har holat
 * o'zgarishini ("Eshityapman…", "O'ylayapman…") karnaydan aytsa, u Barno ustidan gapiradi
 * va mikrofonga tushib savol bo'lib ketishi mumkin. TalkBack yoqilganda faqat muhim
 * narsalar (xato, eslatma, "navbat sizda") e'lon qilinadi. O'qib bo'lmasa - o'chiq deb olinadi.
 */
import { useEffect, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

export function useScreenReader(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let alive = true;
    try {
      AccessibilityInfo.isScreenReaderEnabled()
        .then((v) => {
          if (alive) setOn(!!v);
        })
        .catch(() => {});
    } catch {
      /* API yo'q */
    }
    let sub: { remove(): void } | null = null;
    try {
      sub = AccessibilityInfo.addEventListener('screenReaderChanged', (v) => setOn(!!v));
    } catch {
      sub = null;
    }
    return () => {
      alive = false;
      sub?.remove();
    };
  }, []);
  return on;
}

/** E'lon (faqat ekran o'quvchi yoqilganda) - xato bo'lsa jim. */
export function announce(text: string): void {
  try {
    AccessibilityInfo.announceForAccessibility(text);
  } catch {
    /* no-op */
  }
}

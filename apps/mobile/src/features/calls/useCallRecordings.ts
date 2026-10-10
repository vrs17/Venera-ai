/**
 * Telefondagi Samsung qo'ng'iroq yozuvlari ro'yxati (MediaStore) + ruxsat holati.
 *
 * Qachon o'qiladi: bo'lim ko'ringanda (fokus), ilova oldinga chiqqanda (ruxsat tizim
 * sozlamasida berilgan yoki yangi qo'ng'iroq bo'lgan bo'lishi mumkin) va tortib yangilashda.
 * Ruxsat yo'q bo'lsa native ro'yxat bo'sh qaytaradi - "yozuv yo'q" emas, "ruxsat kerak" deymiz.
 */
import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { hasAudioReadPermission, listCallRecordings, type CallRecording } from '@/features/entry/nativeEntry';

/** Ro'yxatda ko'rsatiladigan eng yangi yozuvlar soni. */
export const LIST_LIMIT = 100;

export interface CallRecordingsState {
  items: CallRecording[];
  /** Birinchi o'qish tugadimi ("yozuv yo'q" faqat shundan keyin). */
  loaded: boolean;
  loading: boolean;
  permitted: boolean;
  /**
   * Ro'yxat o'qilgan vaqt (ms). "Hali yozilmoqda" holati shunga nisbatan hisoblanadi - render
   * paytida `Date.now()` chaqirilmaydi (toza render), yangilanganda holat ham yangilanadi.
   */
  readAt: number;
  refresh(): Promise<void>;
}

export function useCallRecordings(active: boolean): CallRecordingsState {
  const [items, setItems] = useState<CallRecording[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [permitted, setPermitted] = useState(() => hasAudioReadPermission());
  const [readAt, setReadAt] = useState(() => Date.now());
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    const ok = hasAudioReadPermission();
    setPermitted(ok);
    if (!ok) {
      setItems([]);
      setLoaded(true);
      return;
    }
    setLoading(true);
    try {
      const recs = await listCallRecordings(0, LIST_LIMIT);
      if (alive.current) {
        setItems(recs);
        setReadAt(Date.now());
      }
    } finally {
      if (alive.current) {
        setLoading(false);
        setLoaded(true);
      }
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      if (active) void refresh();
    }, [active, refresh]),
  );

  useEffect(() => {
    if (!active) return;
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') void refresh();
    });
    return () => sub.remove();
  }, [active, refresh]);

  return { items, loaded, loading, permitted, readAt, refresh };
}

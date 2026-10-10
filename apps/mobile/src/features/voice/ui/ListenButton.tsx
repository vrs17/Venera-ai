/**
 * 🔊 "Tinglash" - javob ostidagi amallar qatorida (nusxalashdan oldin).
 *
 *   bo'sh        🔊 (xira)
 *   tayyorlanmoqda  aylanuvchi belgi
 *   o'qilmoqda   ■ (bosilsa to'xtaydi)
 *
 * NIMA UCHUN alohida komponent va o'zi obuna bo'ladi: `ExchangeView` `memo` - o'qish
 * holati o'zgarganda faqat SHU tugma qayta chiziladi, boshqa javoblar emas.
 * Chat ekrani ichida - expo-router hook'lari yo'q, barrel emas (`readAloud` to'g'ridan).
 */
import * as Haptics from 'expo-haptics';
import { Square, Volume2 } from 'lucide-react-native';
import { ActivityIndicator, Pressable, StyleSheet } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import { useReadAloud, useReadAloudControls } from '@/features/voice/readAloud';
import { useTheme } from '@/ui/theme';

export interface ListenButtonProps {
  id: string;
  markdown: string;
  turnId: string | null;
}

export function ListenButton({ id, markdown, turnId }: ListenButtonProps) {
  const th = useTheme();
  const t = useT();
  // Faqat O'Z holati: boshqa javob o'qilayotganda bu tugma 'idle' ko'rinadi (qayta chizilmaydi).
  const mine = useReadAloud((s) => (s.key === id ? s.phase : 'idle'));
  const controls = useReadAloudControls();

  const active = mine === 'playing' || mine === 'paused';
  const loading = mine === 'loading';

  return (
    <Pressable
      testID="answer-listen"
      accessibilityRole="button"
      accessibilityLabel={t(active || loading ? 'nav.voice.listenStop' : 'nav.voice.listen')}
      accessibilityState={{ busy: loading }}
      hitSlop={8}
      onPress={() => {
        void Haptics.selectionAsync().catch(() => {});
        controls.toggle(id, markdown, turnId);
      }}
      style={({ pressed }) => [s.btn, pressed ? { backgroundColor: th.surfaceAlt } : null]}>
      {loading ? (
        <ActivityIndicator size="small" color={th.textMuted} />
      ) : active ? (
        <Square size={14} color={th.text} fill={th.text} strokeWidth={0} />
      ) : (
        <Volume2 size={17} color={th.textMuted} strokeWidth={1.9} />
      )}
    </Pressable>
  );
}

const s = StyleSheet.create({
  btn: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center', borderRadius: 18 },
});

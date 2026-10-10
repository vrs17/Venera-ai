/**
 * Sarlavhadagi ⋮ menyusi: pastdan chiqadigan varaq, har amal = belgi + nom
 * (Claude ilovasidagi kabi). NIMA UCHUN `PickerModal` emas: u faqat matnli ro'yxat,
 * bu yerda esa "O'chirish" qizil va belgili bo'lishi kerak - xavfli amal bir
 * qarashda ajralib tursin.
 */
import type { LucideIcon } from 'lucide-react-native';
import { useEffect, useRef } from 'react';
import { Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { useT } from '@/features/settings/settingsStore';
import { useSafeInsets } from '@/ui/insets';
import { ListRow } from '@/ui/list';
import { useTheme } from '@/ui/theme';
import { radius, type as typeScale } from '@/ui/tokens';

export interface MenuItem {
  key: string;
  title: string;
  icon: LucideIcon;
  onPress: () => void;
  destructive?: boolean;
  disabled?: boolean;
}

/**
 * Android'da Modal (Dialog) yopilish animatsiyasi shuncha davom etadi. Keyingi oyna
 * (nomlash PromptModal, Alert) undan keyin ochiladi - aks holda u yopilayotgan
 * dialog ostida fokusni olmay qolishi va klaviatura chiqmasligi mumkin.
 */
const DISMISS_MS = Platform.OS === 'android' ? 200 : 0;

export function ActionMenu({ visible, title, items, onClose }: { visible: boolean; title?: string; items: MenuItem[]; onClose: () => void }) {
  const th = useTheme();
  const t = useT();
  const insets = useSafeInsets();
  // Tanlangan amal menyu yopilgandan KEYIN bajariladi (yuqoridagi sabab).
  const pending = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (visible || !pending.current) return;
    const run = pending.current;
    pending.current = null;
    const h = setTimeout(run, DISMISS_MS);
    return () => clearTimeout(h);
  }, [visible]);
  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent onRequestClose={onClose}>
      {/* Fon va varaq aka-uka: fon bosilsa yopiladi, varaqdagi qatorlar esa TalkBack'ga alohida ko'rinadi. */}
      <View style={s.root}>
        <Pressable testID="menu-backdrop" style={[StyleSheet.absoluteFill, s.backdrop]} onPress={onClose} accessibilityRole="button" accessibilityLabel={t('common.close')} />
        <View style={[s.sheet, { backgroundColor: th.bg, paddingBottom: insets.bottom + 12 }]}>
          <View style={[s.grabber, { backgroundColor: th.borderStrong }]} />
          {title ? <Text style={[typeScale.label, s.title, { color: th.textMuted }]}>{title}</Text> : null}
          {items.map((it) => (
            <ListRow
              key={it.key}
              testID={`menu-${it.key}`}
              variant="plain"
              icon={it.icon}
              title={it.title}
              destructive={it.destructive}
              disabled={it.disabled}
              right={{ kind: 'none' }}
              onPress={() => {
                // Avval yopamiz: keyingi Alert/Prompt modal ustida qolib ketmasin.
                pending.current = it.onPress;
                onClose();
              }}
            />
          ))}
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: { borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, paddingTop: 8, paddingHorizontal: 8 },
  grabber: { alignSelf: 'center', width: 36, height: 4, borderRadius: 2, marginBottom: 8 },
  title: { paddingHorizontal: 16, paddingVertical: 8 },
});

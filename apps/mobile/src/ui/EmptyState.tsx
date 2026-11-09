/**
 * Bo'sh holat: belgi + sarlavha + qisqa izoh + bitta asosiy amal (+ ixtiyoriy muqobil
 * tugma va ikkinchi matnli tugma). NIMA UCHUN: "Yozuv yo'q" degan quruq matn o'rniga
 * foydalanuvchi keyingi qadamni darhol ko'rsin (masalan "Yozishni boshlash" yoki "Audio yuklash").
 *
 * `compact` - kartaning ichida (ekranni to'ldirmaydi, kichikroq belgi).
 */
import type { LucideIcon } from 'lucide-react-native';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, type ButtonVariant } from './components';
import { IconTile, type IconTileTone } from './IconTile';
import { useTheme } from './theme';
import { hit, type as typeScale } from './tokens';

export interface EmptyStateAction {
  title: string;
  onPress: () => void;
  variant?: ButtonVariant;
  icon?: LucideIcon;
  testID?: string;
  /** Amal davom etmoqda (masalan fayllar tayyorlanmoqda) - tugma aylanma, qayta bosilmaydi. */
  loading?: boolean;
}

export function EmptyState({
  icon,
  tone = 'plain',
  title,
  body,
  action,
  altAction,
  secondary,
  compact,
  testID,
}: {
  icon: LucideIcon;
  tone?: IconTileTone;
  title: string;
  body?: string | null;
  action?: EmptyStateAction;
  /** Asosiy amalga teng muqobil yo'l (default `secondary` uslubida) - masalan yozish o'rniga fayl yuklash. */
  altAction?: EmptyStateAction;
  secondary?: { title: string; onPress: () => void; testID?: string };
  compact?: boolean;
  testID?: string;
}) {
  const th = useTheme();
  return (
    <View testID={testID} style={compact ? s.compact : s.full}>
      <IconTile icon={icon} tone={tone} size={compact ? 'md' : 'lg'} />
      <Text style={[typeScale.headline, s.center, { color: th.text, marginTop: compact ? 8 : 12 }]}>{title}</Text>
      {body ? (
        <Text numberOfLines={3} style={[typeScale.sub, s.center, { color: th.textMuted, marginTop: compact ? 4 : 6 }]}>
          {body}
        </Text>
      ) : null}
      {action ? (
        <Button
          pill
          testID={action.testID}
          title={action.title}
          icon={action.icon}
          variant={action.variant ?? 'primary'}
          onPress={action.onPress}
          loading={action.loading}
          small={compact}
          style={{ marginTop: compact ? 12 : 16 }}
        />
      ) : null}
      {altAction ? (
        <Button
          pill
          testID={altAction.testID}
          title={altAction.title}
          icon={altAction.icon}
          variant={altAction.variant ?? 'secondary'}
          onPress={altAction.onPress}
          loading={altAction.loading}
          small={compact}
          style={{ marginTop: action ? 8 : compact ? 12 : 16 }}
        />
      ) : null}
      {secondary ? (
        <Pressable
          testID={secondary.testID}
          accessibilityRole="button"
          onPress={secondary.onPress}
          hitSlop={4}
          style={({ pressed }) => [s.secondary, { marginTop: compact ? 4 : 8, opacity: pressed ? 0.6 : 1 }]}>
          <Text style={[typeScale.label, { color: th.textSoft, fontSize: 15 }]}>{secondary.title}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  full: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  compact: { alignItems: 'center', paddingVertical: 16, paddingHorizontal: 16 },
  center: { textAlign: 'center', maxWidth: 320 },
  secondary: { minHeight: hit.min, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
});

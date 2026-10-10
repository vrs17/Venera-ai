/**
 * Faqat belgidan iborat tugma (tepa panel, sarlavha o'ng tomoni). Ko'rinishi
 * ixcham, lekin bosish nishoni 44x44 - barmoq bilan aniq tegish uchun.
 * `label` majburiy: TalkBack belgini o'qiy olmaydi, nomni aytadi.
 */
import type { LucideIcon } from 'lucide-react-native';
import { Pressable, StyleSheet } from 'react-native';

import { useTheme } from './theme';
import { hit, iconSize, stroke } from './tokens';

export function IconButton({
  icon: Icon,
  label,
  onPress,
  color,
  size = iconSize.row,
  disabled,
  testID,
}: {
  icon: LucideIcon;
  label: string;
  onPress?: () => void;
  color?: string;
  size?: number;
  disabled?: boolean;
  testID?: string;
}) {
  const th = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      hitSlop={4}
      style={({ pressed }) => [s.btn, { backgroundColor: pressed ? th.surfaceAlt : 'transparent', opacity: disabled ? 0.45 : 1 }]}>
      <Icon size={size} color={color ?? th.textSoft} strokeWidth={size <= 16 ? stroke.small : stroke.regular} />
    </Pressable>
  );
}

const s = StyleSheet.create({
  btn: { width: hit.min, height: hit.min, borderRadius: hit.min / 2, alignItems: 'center', justifyContent: 'center' },
});

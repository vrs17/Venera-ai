/**
 * Holat belgisi ("Ulangan", "Internet yo'q", "Yozilmoqda") va ingichka progress chizig'i.
 *
 * NIMA UCHUN `Chip`dan alohida: Chip bosiladigan tanlov (shablon, filtr) - pill esa
 * faqat HOLATNI aytadi, balandligi qat'iy 24 dp (qator ichida tekis turadi), belgi
 * yoki nuqta oladi. `record` toni - qizil yozuv holati.
 *
 * Ustun ichida ishlatilsa `style={{ alignSelf: 'flex-start' }}` bering (aks holda
 * kenglik bo'ylab cho'ziladi); qator ichida hech narsa kerak emas.
 */
import type { LucideIcon } from 'lucide-react-native';
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import type { Tone } from '@/features/meeting/summaryModel';

import { toneColors } from './IconTile';
import { useTheme } from './theme';
import { iconSize, radius, stroke, type as typeScale } from './tokens';

export type PillTone = Tone | 'record';

export function StatusPill({
  label,
  tone = 'neutral',
  icon: Icon,
  dot,
  testID,
  textTestID,
  style,
}: {
  label: string;
  tone?: PillTone;
  icon?: LucideIcon;
  dot?: boolean;
  testID?: string;
  /** Ichki Text'ga - eski testlar (`volume-status`) matnni to'g'ridan-to'g'ri o'qiydi. */
  textTestID?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const th = useTheme();
  const c = toneColors(th, tone);
  return (
    <View testID={testID} style={[s.pill, { backgroundColor: c.bg }, style]}>
      {dot ? <View style={[s.dot, { backgroundColor: c.fg }]} /> : null}
      {Icon ? <Icon size={iconSize.xs} color={c.fg} strokeWidth={stroke.small} /> : null}
      <Text testID={textTestID} numberOfLines={1} style={[typeScale.micro, { color: c.fg }]}>
        {label}
      </Text>
    </View>
  );
}

/**
 * `value` 0..1. `null` - foiz noma'lum (hajm hali hisoblanmagan): 30% xira chiziq,
 * "bir narsa bo'lyapti" degan ma'no, soxta foiz emas.
 */
export function ProgressBar({ value, tone, testID }: { value: number | null; tone?: Tone; testID?: string }) {
  const th = useTheme();
  const known = value != null && Number.isFinite(value);
  const ratio = known ? Math.max(0, Math.min(1, value)) : 0.3;
  const fill = tone ? th.tones[tone].fg : th.primary;
  return (
    <View
      testID={testID}
      accessibilityRole="progressbar"
      accessibilityValue={known ? { min: 0, max: 100, now: Math.round(ratio * 100) } : undefined}
      style={[s.track, { backgroundColor: th.border }]}>
      <View style={[s.fill, { width: `${ratio * 100}%`, backgroundColor: fill, opacity: known ? 1 : 0.5 }]} />
    </View>
  );
}

const s = StyleSheet.create({
  pill: {
    height: 24,
    paddingHorizontal: 10,
    borderRadius: radius.pill,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    maxWidth: '100%',
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  track: { height: 4, borderRadius: 2, overflow: 'hidden', alignSelf: 'stretch' },
  fill: { height: 4, borderRadius: 2 },
});

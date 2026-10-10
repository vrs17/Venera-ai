/**
 * Kichik UI to'plami. Tashqi UI kutubxonasi yo'q (APK hajmi va build
 * xavfini kamaytirish uchun) - faqat React Native primitivlari.
 */
import type { LucideIcon } from 'lucide-react-native';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import type { MeetingStatus } from '@/api/types';
import { formatClock } from '@/features/meeting/formatDate';
import type { Tone } from '@/features/meeting/summaryModel';
import { useT } from '@/features/settings/settingsStore';

import { useTheme } from './theme';

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const th = useTheme();
  return <View style={[styles.card, { backgroundColor: th.surface, borderColor: th.border }, style]}>{children}</View>;
}

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'record';

export function Button(props: {
  title: string;
  onPress?: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  small?: boolean;
  /** Matn chap tomonidagi belgi (16 px) - tugma nima qilishi bir qarashda ko'rinsin. */
  icon?: LucideIcon;
  /** To'liq yumaloq (999) - asosiy chaqiruv tugmalari (bo'sh holat, "Yozish"). */
  pill?: boolean;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  accessibilityLabel?: string;
}) {
  const th = useTheme();
  const v = props.variant ?? 'primary';
  const Icon = props.icon;
  const bg =
    v === 'primary' ? th.primary : v === 'danger' ? th.danger : v === 'record' ? th.record : v === 'secondary' ? th.surfaceAlt : 'transparent';
  const fg = v === 'secondary' || v === 'ghost' ? th.text : th.primaryText;
  const disabled = props.disabled || props.loading;
  return (
    <Pressable
      testID={props.testID}
      accessibilityRole="button"
      accessibilityLabel={props.accessibilityLabel ?? props.title}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={props.onPress}
      // Kichik tugma ko'zga ixcham, lekin barmoq uchun 48 dp (Android minimal nishoni).
      hitSlop={props.small ? 6 : undefined}
      style={({ pressed }) => [
        styles.button,
        props.small && styles.buttonSmall,
        props.pill && (props.small ? styles.buttonPillSmall : styles.buttonPill),
        { backgroundColor: bg, opacity: disabled ? 0.5 : pressed ? 0.8 : 1 },
        v === 'ghost' && { borderWidth: 1, borderColor: th.border },
        props.style,
      ]}>
      {props.loading ? (
        <ActivityIndicator color={fg} />
      ) : Icon ? (
        <View style={styles.buttonRow}>
          <Icon size={16} color={fg} strokeWidth={2} />
          <Text style={[styles.buttonText, props.small && styles.buttonTextSmall, { color: fg }]}>{props.title}</Text>
        </View>
      ) : (
        <Text style={[styles.buttonText, props.small && styles.buttonTextSmall, { color: fg }]}>{props.title}</Text>
      )}
    </Pressable>
  );
}

/**
 * `selected` berilsa chip tanlanadigan (shablon, ishtirokchilar soni, tab):
 * tanlov TalkBack'ga ham aytiladi - faqat rang bilan emas.
 */
export function Chip({
  label,
  tone = 'neutral',
  onPress,
  testID,
  selected,
}: {
  label: string;
  tone?: Tone;
  onPress?: () => void;
  testID?: string;
  selected?: boolean;
}) {
  const th = useTheme();
  const c = th.tones[tone];
  const body = <Text style={[styles.chipText, { color: c.fg }]}>{label}</Text>;
  if (!onPress) return <View style={[styles.chip, { backgroundColor: c.bg }]}>{body}</View>;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={selected === undefined ? undefined : { selected }}
      onPress={onPress}
      style={[styles.chip, { backgroundColor: c.bg }]}>
      {body}
    </Pressable>
  );
}

/** Dalil chipi: `12:34`, bosilsa audio/transkript shu joyga. */
export function EvidenceChip({ start, onSeek }: { start: number | null; onSeek?: (t: number) => void }) {
  if (start == null) return null;
  return <Chip testID={`ev-${start}`} label={`▶ ${formatClock(start)}`} tone="info" onPress={onSeek ? () => onSeek(start) : undefined} />;
}

const STATUS_TONES: Record<MeetingStatus, Tone> = {
  uploading: 'info',
  uploaded: 'neutral',
  transcribing: 'info',
  summarizing: 'accent',
  ready: 'good',
  failed: 'bad',
  waiting_quota: 'warn',
};

export function StatusChip({ status, progress }: { status: MeetingStatus; progress?: number | null }) {
  const t = useT();
  const label = t(`status.${status}`);
  return <Chip label={progress != null && status !== 'ready' && status !== 'failed' ? `${label} ${Math.round(progress)}%` : label} tone={STATUS_TONES[status]} />;
}

export function Banner({ text, tone = 'warn', action, testID }: { text: string; tone?: Tone; action?: { title: string; onPress: () => void }; testID?: string }) {
  const th = useTheme();
  const c = th.tones[tone];
  return (
    <View testID={testID} style={[styles.banner, { backgroundColor: c.bg }]}>
      <Text style={[styles.bannerText, { color: c.fg }]}>{text}</Text>
      {action ? <Button small variant="ghost" title={action.title} onPress={action.onPress} style={styles.bannerAction} /> : null}
    </View>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  const th = useTheme();
  return <Text style={[styles.sectionTitle, { color: th.text }]}>{children}</Text>;
}

export function Muted({ children, style, testID }: { children: ReactNode; style?: StyleProp<TextStyle>; testID?: string }) {
  const th = useTheme();
  return (
    <Text testID={testID} style={[styles.muted, { color: th.textMuted }, style]}>
      {children}
    </Text>
  );
}

export function Body({ children, selectable }: { children: ReactNode; selectable?: boolean }) {
  const th = useTheme();
  return (
    <Text selectable={selectable} style={[styles.body, { color: th.text }]}>
      {children}
    </Text>
  );
}

export function Field(props: TextInputProps & { label?: string }) {
  const th = useTheme();
  const { label, style, ...rest } = props;
  return (
    <View style={styles.field}>
      {label ? <Text style={[styles.fieldLabel, { color: th.textMuted }]}>{label}</Text> : null}
      <TextInput
        placeholderTextColor={th.textMuted}
        accessibilityLabel={label ?? rest.placeholder}
        {...rest}
        style={[styles.input, { color: th.text, borderColor: th.border, backgroundColor: th.surface }, style]}
      />
    </View>
  );
}

export function Segmented<T extends string>(props: {
  options: { value: T; label: string; icon?: LucideIcon }[];
  value: T;
  onChange: (v: T) => void;
  testIDPrefix?: string;
  /**
   * Belgi joyi: `left` (default) yoki `top`. 4 ta tab tor telefonda (360 dp) yonma-yon
   * belgi bilan sig'maydi ("Vazifalar 2" kesiladi) - u holda `top`.
   */
  iconPosition?: 'left' | 'top';
}) {
  const th = useTheme();
  const top = props.iconPosition === 'top';
  return (
    <View style={[styles.segmented, { backgroundColor: th.surfaceAlt }]}>
      {props.options.map((o) => {
        const active = o.value === props.value;
        const color = active ? th.text : th.textMuted;
        const Icon = o.icon;
        return (
          <Pressable
            key={o.value}
            testID={props.testIDPrefix ? `${props.testIDPrefix}-${o.value}` : undefined}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            onPress={() => props.onChange(o.value)}
            style={[styles.segment, Icon && (top ? styles.segmentTop : styles.segmentLeft), active && { backgroundColor: th.surface }]}>
            {Icon ? <Icon size={16} color={color} strokeWidth={2} /> : null}
            <Text numberOfLines={1} style={[styles.segmentText, Icon && !top && styles.shrink, { color }]}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Checkbox({ checked, onPress, testID, label }: { checked: boolean; onPress: () => void; testID?: string; label?: string }) {
  const th = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="checkbox"
      accessibilityLabel={label}
      accessibilityState={{ checked }}
      onPress={onPress}
      hitSlop={10}
      style={[styles.checkbox, { borderColor: checked ? th.primary : th.border, backgroundColor: checked ? th.primary : 'transparent' }]}>
      {checked ? <Text style={{ color: th.primaryText, fontWeight: '700' }}>✓</Text> : null}
    </Pressable>
  );
}

export function Loading() {
  const th = useTheme();
  return (
    <View style={styles.center}>
      <ActivityIndicator color={th.primary} />
    </View>
  );
}

export function Empty({ text }: { text: string }) {
  const th = useTheme();
  return (
    <View style={styles.center}>
      <Text style={[styles.muted, { color: th.textMuted, textAlign: 'center' }]}>{text}</Text>
    </View>
  );
}

export const styles = StyleSheet.create({
  card: { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, padding: 14, marginBottom: 10 },
  button: { borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center' },
  buttonSmall: { minHeight: 36, paddingVertical: 6, paddingHorizontal: 10, borderRadius: 8 },
  buttonPill: { borderRadius: 999, paddingHorizontal: 22 },
  buttonPillSmall: { borderRadius: 999, paddingHorizontal: 14 },
  buttonRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  buttonText: { fontSize: 16, fontWeight: '600' },
  buttonTextSmall: { fontSize: 13 },
  chip: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3, marginRight: 6, marginTop: 4, alignSelf: 'flex-start' },
  chipText: { fontSize: 12, fontWeight: '600' },
  banner: { borderRadius: 10, padding: 12, marginBottom: 10 },
  bannerText: { fontSize: 14, lineHeight: 20 },
  bannerAction: { marginTop: 8, alignSelf: 'flex-start' },
  sectionTitle: { fontSize: 17, fontWeight: '700', marginBottom: 8 },
  muted: { fontSize: 13, lineHeight: 18 },
  body: { fontSize: 15, lineHeight: 22 },
  field: { marginBottom: 12 },
  fieldLabel: { fontSize: 13, marginBottom: 4 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16 },
  segmented: { flexDirection: 'row', borderRadius: 10, padding: 3 },
  segment: { flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center' },
  segmentLeft: { flexDirection: 'row', justifyContent: 'center', gap: 6, paddingHorizontal: 4 },
  segmentTop: { paddingVertical: 6, gap: 2, paddingHorizontal: 2 },
  segmentText: { fontSize: 13, fontWeight: '600' },
  shrink: { flexShrink: 1 },
  checkbox: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  row: { flexDirection: 'row', alignItems: 'center' },
  wrap: { flexDirection: 'row', flexWrap: 'wrap' },
});

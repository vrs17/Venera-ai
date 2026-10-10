/**
 * Claude uslubidagi ro'yxat: guruhlangan kartalar ichida qatorlar. Har qator =
 * belgi + sarlavha + ko'pi bilan BITTA xira qiymat qatori ("HRM, CRM ulangan",
 * "Tizim") + o'ng tomonda holat (chevron, switch, belgi, pill, qiymat).
 *
 * NIMA UCHUN: egasi "hamma joyda matn, hammasi bir joyda, belgi yo'q" dedi.
 * Sozlamalar hub'i, uning ichki sahifalari va drawer shu bitta komponentdan
 * yig'iladi - har ekran o'z "qatorini" qayta ixtiro qilmasin.
 *
 * Variantlar:
 * - `grouped` (default): `surfaceAlt` fon, `ListGroup` ichida (orasida 2 dp ingichka bo'shliq).
 * - `plain`: shaffof, burchak 12 - drawer qatorlari; `selected` - kulrang "pill".
 */
import { Check, ChevronRight, type LucideIcon } from 'lucide-react-native';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Switch, Text, View, type AccessibilityRole, type StyleProp, type ViewStyle } from 'react-native';

import type { Tone } from '@/features/meeting/summaryModel';

import { StatusPill, type PillTone } from './StatusPill';
import { useTheme } from './theme';
import { hit, iconSize, radius, stroke, type as typeScale } from './tokens';

export type ListRowRight =
  | { kind: 'chevron' }
  | { kind: 'switch'; value: boolean; onChange: (v: boolean) => void; disabled?: boolean; testID?: string }
  | { kind: 'check'; checked: boolean }
  /** `testID` ichki Text'ga tushadi (StatusPill `textTestID`) - matnni to'g'ridan-to'g'ri tekshirish uchun. */
  | { kind: 'pill'; label: string; tone?: PillTone; testID?: string }
  | { kind: 'value'; text: string }
  | { kind: 'node'; node: ReactNode }
  | { kind: 'none' };

export interface ListRowProps {
  title: string;
  /** BITTA qator, caption uslubi, `textMuted` (qiymat yoki holat - yo'riqnoma emas). */
  subtitle?: string | null;
  /** Subtitle rangini `tones[tone].fg` qiladi (masalan `warn` - "qayta kirish kerak"). */
  subtitleTone?: Tone;
  icon?: LucideIcon;
  iconColor?: string;
  /** Belgi o'rniga (Avatar, IconTile). */
  leading?: ReactNode;
  /** Default: `onPress` bo'lsa chevron, aks holda hech narsa (destructive - chevronsiz). */
  right?: ListRowRight;
  onPress?: () => void;
  onLongPress?: () => void;
  /** Sarlavha va belgi `th.danger`, chevron yo'q. */
  destructive?: boolean;
  /** Xira (0.45) va bosilmaydi. */
  disabled?: boolean;
  /** `plain` variantda: `surfaceAlt` fon + qalin sarlavha (joriy suhbat). */
  selected?: boolean;
  variant?: 'grouped' | 'plain';
  /** Default 1. */
  titleLines?: number;
  /** Qiymatni bosib turib nusxalash (email, server manzili) - u holda qator cheklanmaydi. */
  selectableSubtitle?: boolean;
  testID?: string;
  accessibilityLabel?: string;
}

export function ListRow(p: ListRowProps) {
  const th = useTheme();
  const variant = p.variant ?? 'grouped';
  const right: ListRowRight = p.right ?? (p.onPress && !p.destructive ? { kind: 'chevron' } : { kind: 'none' });
  const sw = right.kind === 'switch' ? right : null;
  // Switch qatori: butun qator bosilsa ham almashadi (katta nishon, Claude kabi).
  const onPress = p.onPress ?? (sw && !sw.disabled ? () => sw.onChange(!sw.value) : undefined);
  const interactive = !!(onPress || p.onLongPress);
  const Icon = p.icon;
  const titleColor = p.destructive ? th.danger : th.text;
  const iconColor = p.iconColor ?? (p.destructive ? th.danger : th.textSoft);
  const subColor = p.subtitleTone ? th.tones[p.subtitleTone].fg : th.textMuted;
  const baseBg = variant === 'grouped' ? th.surfaceAlt : p.selected ? th.surfaceAlt : 'transparent';
  const pressedBg = variant === 'grouped' ? th.border : th.surfaceAlt;

  const role: AccessibilityRole | undefined =
    right.kind === 'switch' ? 'switch' : right.kind === 'check' ? 'radio' : interactive ? 'button' : undefined;
  const a11yState = {
    disabled: !!p.disabled || (!!sw?.disabled && !p.onPress),
    ...(sw ? { checked: sw.value } : null),
    ...(right.kind === 'check' ? { checked: right.checked } : null),
    ...(variant === 'plain' && p.selected ? { selected: true } : null),
  };

  const lead = p.leading ?? (Icon ? <Icon size={iconSize.row} color={iconColor} strokeWidth={stroke.regular} /> : null);
  const content = (
    <>
      {/* O'chiq qatorda faqat belgi va sarlavha xiralashadi: subtitle ko'pincha SABABni aytadi
          ("Avval yozuvni to'xtating") - u o'qilishi kerak. */}
      {lead ? <View style={p.disabled ? s.disabled : null}>{lead}</View> : null}
      <View style={s.text}>
        <Text
          numberOfLines={p.titleLines ?? 1}
          style={[typeScale.rowTitle, { color: titleColor }, p.selected && variant === 'plain' ? s.bold : null, p.disabled ? s.disabled : null]}>
          {p.title}
        </Text>
        {p.subtitle ? (
          <Text
            numberOfLines={p.selectableSubtitle ? undefined : 1}
            selectable={p.selectableSubtitle}
            style={[typeScale.caption, { color: subColor }]}>
            {p.subtitle}
          </Text>
        ) : null}
      </View>
      <RowRight right={right} />
    </>
  );

  const box: StyleProp<ViewStyle> = [
    s.row,
    variant === 'plain' && s.plain,
    { minHeight: p.subtitle ? 64 : hit.row },
  ];

  if (!interactive) {
    return (
      <View
        testID={p.testID}
        accessible={role ? true : undefined}
        accessibilityRole={role}
        accessibilityLabel={p.accessibilityLabel}
        accessibilityState={role ? a11yState : undefined}
        style={[box, { backgroundColor: baseBg }]}>
        {content}
      </View>
    );
  }

  return (
    <Pressable
      testID={p.testID}
      accessibilityRole={role}
      accessibilityLabel={p.accessibilityLabel}
      accessibilityState={a11yState}
      disabled={p.disabled}
      onPress={onPress}
      onLongPress={p.onLongPress}
      android_ripple={{ color: th.border }}
      style={({ pressed }) => [box, { backgroundColor: pressed ? pressedBg : baseBg }]}>
      {content}
    </Pressable>
  );
}

function RowRight({ right }: { right: ListRowRight }) {
  const th = useTheme();
  switch (right.kind) {
    case 'chevron':
      return <ChevronRight size={iconSize.md} color={th.textFaint} strokeWidth={stroke.regular} />;
    case 'switch':
      return (
        <Switch
          testID={right.testID}
          value={right.value}
          disabled={right.disabled}
          onValueChange={right.onChange}
          trackColor={{ false: th.borderStrong, true: th.brand }}
          thumbColor="#FFFFFF"
          // Qatorning o'zi `switch` roli bilan o'qiladi - TalkBack ikki marta to'xtamasin.
          importantForAccessibility="no"
        />
      );
    case 'check':
      return right.checked ? (
        <Check size={iconSize.md} color={th.brand} strokeWidth={2} />
      ) : (
        <View style={s.checkSpace} />
      );
    case 'pill':
      return <StatusPill label={right.label} tone={right.tone} textTestID={right.testID} />;
    case 'value':
      return (
        <Text numberOfLines={1} style={[typeScale.sub, s.value, { color: th.textMuted }]}>
          {right.text}
        </Text>
      );
    case 'node':
      return <>{right.node}</>;
    default:
      return null;
  }
}

export function ListGroup({
  children,
  header,
  footer,
  style,
  testID,
}: {
  children: ReactNode;
  header?: string;
  footer?: string;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}) {
  const th = useTheme();
  return (
    <View testID={testID} style={[s.group, style]}>
      {header ? <Text style={[typeScale.label, s.groupHeader, { color: th.textMuted }]}>{header}</Text> : null}
      {/* 2 dp bo'shliq orqali sahifa foni ko'rinadi - qatorlar orasida ingichka ajratgich. */}
      <View style={[s.groupBody, { backgroundColor: th.bg }]}>{children}</View>
      {footer ? <Text style={[typeScale.caption, s.groupFooter, { color: th.textMuted }]}>{footer}</Text> : null}
    </View>
  );
}

export function ListDivider({ style }: { style?: StyleProp<ViewStyle> }) {
  const th = useTheme();
  return <View style={[s.divider, { backgroundColor: th.border }, style]} />;
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 16, paddingVertical: 12 },
  plain: { borderRadius: radius.md },
  disabled: { opacity: 0.45 },
  text: { flex: 1, minWidth: 0, gap: 1 },
  bold: { fontWeight: '600' },
  value: { maxWidth: '50%' },
  checkSpace: { width: iconSize.md, height: iconSize.md },
  group: { marginBottom: 24 },
  groupHeader: { paddingHorizontal: 4, marginBottom: 8 },
  groupBody: { borderRadius: radius.lg, overflow: 'hidden', gap: 2 },
  groupFooter: { paddingHorizontal: 4, marginTop: 8 },
  divider: { height: StyleSheet.hairlineWidth, marginVertical: 8 },
});

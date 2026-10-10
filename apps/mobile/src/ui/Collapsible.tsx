/**
 * Yig'iladigan bo'lim ("Qanday sozlash ⌄", "Cheklovlar ⌄") va qadamlar ro'yxati.
 *
 * NIMA UCHUN: egasi "hamma joyda matn" dedi - yo'riqnomalar sahifada doim ochiq
 * turmasin, faqat so'ralganda ochilsin. Mazmun YOPIQ paytda umuman chizilmaydi
 * (LayoutAnimation yo'q - Android'da eski qurilmalarda sakraydi).
 *
 * Boshqariladigan (`open` + `onToggle`) yoki o'zi holat saqlaydigan (`initiallyOpen`).
 */
import { ChevronDown, ChevronUp } from 'lucide-react-native';
import { useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useTheme } from './theme';
import { hit, iconSize, stroke, type as typeScale } from './tokens';

export function Collapsible({
  title,
  children,
  initiallyOpen = false,
  open,
  onToggle,
  testID,
}: {
  title: string;
  children: ReactNode;
  initiallyOpen?: boolean;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  /** Sarlavha (bosiladigan) qatoriga; mazmun - `${testID}-content`. */
  testID?: string;
}) {
  const th = useTheme();
  const [own, setOwn] = useState(initiallyOpen);
  const isOpen = open ?? own;
  const Chevron = isOpen ? ChevronUp : ChevronDown;
  const toggle = () => {
    const next = !isOpen;
    if (open === undefined) setOwn(next);
    onToggle?.(next);
  };
  return (
    <View>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={title}
        accessibilityState={{ expanded: isOpen }}
        onPress={toggle}
        style={({ pressed }) => [s.header, { opacity: pressed ? 0.6 : 1 }]}>
        <Text style={[typeScale.label, { color: th.textSoft }]}>{title}</Text>
        <Chevron size={iconSize.sm} color={th.textSoft} strokeWidth={stroke.small} />
      </Pressable>
      {isOpen ? (
        <View testID={testID ? `${testID}-content` : undefined} style={s.content}>
          {children}
        </View>
      ) : null}
    </View>
  );
}

/** Qadamlar: raqamli doiracha (yoki nuqta) + bir qatorli matn. */
export function StepList({ items, numbered = true, testID }: { items: string[]; numbered?: boolean; testID?: string }) {
  const th = useTheme();
  return (
    <View testID={testID} style={s.list}>
      {items.map((text, i) => (
        <View key={i} style={s.item}>
          {numbered ? (
            <View style={[s.num, { backgroundColor: th.surfaceAlt, borderColor: th.borderStrong }]}>
              <Text allowFontScaling={false} style={[typeScale.micro, { color: th.textSoft }]}>
                {i + 1}
              </Text>
            </View>
          ) : (
            <View style={[s.bullet, { backgroundColor: th.textMuted }]} />
          )}
          <Text style={[typeScale.sub, s.itemText, { color: th.textSoft }]}>{text}</Text>
        </View>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  header: { minHeight: hit.min, flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start' },
  content: { paddingBottom: 4 },
  list: { gap: 10 },
  item: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  num: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 0.5,
  },
  // Nuqta matnning birinchi qatori o'rtasida turadi (sub: lineHeight 19).
  bullet: { width: 6, height: 6, borderRadius: 3, marginTop: 6.5, marginHorizontal: 6 },
  itemText: { flex: 1 },
});

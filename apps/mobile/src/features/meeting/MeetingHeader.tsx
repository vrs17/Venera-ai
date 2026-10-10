/**
 * Yozuv sahifasi tepasi: sarlavha (2 qator) va bitta meta qatori - sana, davomiylik
 * (kichik belgilar bilan) va kerak bo'lsa holat pill'i.
 *
 * NIMA UCHUN alohida: server yig'ilishi va telefondagi (yuklanmagan) yozuv bir xil
 * ko'rinsin - foydalanuvchi ikki xil sahifa borligini sezmasin, faqat holat farq qilsin.
 */
import { Calendar, Clock } from 'lucide-react-native';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Lang } from '@/api/types';
import { useTheme } from '@/ui/theme';
import { iconSize, stroke, type as typeScale } from '@/ui/tokens';

import { formatDateTime, formatDuration } from './formatDate';

export function MeetingHeader({
  title,
  at,
  durationSec,
  lang,
  pill,
  onTitlePress,
  titleA11y,
}: {
  title: string;
  at: string;
  durationSec: number | null;
  lang: Lang;
  /** Holat (faqat "tayyor" bo'lmaganda) - meta qatori oxirida. */
  pill?: ReactNode;
  /** Sarlavhani bosish = nomini o'zgartirish (server yozuvi). */
  onTitlePress?: () => void;
  titleA11y?: string;
}) {
  const th = useTheme();
  const when = formatDateTime(at, lang);
  const dur = formatDuration(durationSec);
  const titleText = (
    <Text testID="meeting-title" numberOfLines={2} style={[typeScale.title, { color: th.text }]}>
      {title}
    </Text>
  );
  return (
    <View style={s.wrap}>
      {onTitlePress ? (
        // TalkBack sarlavhaning o'zini o'qiydi, "nomini o'zgartirish" - maslahat sifatida.
        <Pressable onPress={onTitlePress} accessibilityRole="button" accessibilityLabel={title} accessibilityHint={titleA11y}>
          {titleText}
        </Pressable>
      ) : (
        titleText
      )}
      <View style={s.meta}>
        {when ? (
          <View style={s.item}>
            <Calendar size={iconSize.xs} color={th.textMuted} strokeWidth={stroke.small} />
            <Text style={[typeScale.caption, { color: th.textMuted }]}>{when}</Text>
          </View>
        ) : null}
        {dur ? (
          <View style={s.item}>
            <Clock size={iconSize.xs} color={th.textMuted} strokeWidth={stroke.small} />
            <Text style={[typeScale.caption, s.tabular, { color: th.textMuted }]}>{dur}</Text>
          </View>
        ) : null}
        {pill}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: 6 },
  meta: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: 12, rowGap: 6 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  tabular: { fontVariant: ['tabular-nums'] },
});

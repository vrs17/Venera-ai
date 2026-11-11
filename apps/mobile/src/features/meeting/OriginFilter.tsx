/**
 * Plaud ro'yxati filtri (2026-11-11, ega talabi): yozuv QAYERDAN kelgani bo'yicha - shu ilovada yozilgan,
 * telefondan yuklangan fayl, Slack, Telegram bot, Telegram Mini App, web. Bitta tanlov: "Hammasi" - filtrsiz,
 * tanlangan chipni yana bosish ham filtrni olib tashlaydi.
 *
 * Gorizontal aylanadigan bitta qator (tor telefonda ham ro'yxatni pastga surmaydi). Chip balandligi 36 dp +
 * `hitSlop` - tegish maydoni `hit.min` (44 dp). Tanlov TalkBack'ga `selected` holati bilan aytiladi.
 *
 * Kompyuter (`desktop`) va skript (`api`) manbalari chipga chiqarilmaydi - ular faqat "Hammasi" da.
 */
import { AppWindow, Globe, Hash, Mic, Send, Upload, type LucideIcon } from 'lucide-react-native';
import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';

import type { MeetingOrigin } from '@/api/types';
import { useT } from '@/features/settings/settingsStore';
import { useTheme } from '@/ui/theme';
import { hit, iconSize, radius, stroke, type as typeScale } from '@/ui/tokens';

/** Chiplar tartibi. Slack'ning o'z belgisi lucide'da yo'q - kanal belgisi `#`. */
export const ORIGIN_FILTERS: readonly { value: MeetingOrigin; icon: LucideIcon }[] = [
  { value: 'recording', icon: Mic },
  { value: 'upload', icon: Upload },
  { value: 'slack', icon: Hash },
  { value: 'telegram', icon: Send },
  { value: 'miniapp', icon: AppWindow },
  { value: 'web', icon: Globe },
];

const CHIP_HEIGHT = 36;
const SLOP = Math.ceil((hit.min - CHIP_HEIGHT) / 2);

export function OriginFilter({ value, onChange }: { value: MeetingOrigin | null; onChange: (next: MeetingOrigin | null) => void }) {
  const t = useT();
  const th = useTheme();

  const chip = (key: string, label: string, selected: boolean, onPress: () => void, Icon?: LucideIcon) => {
    const fg = selected ? th.primaryText : th.text;
    return (
      <Pressable
        key={key}
        testID={`origin-${key}`}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ selected }}
        onPress={onPress}
        hitSlop={{ top: SLOP, bottom: SLOP }}
        style={({ pressed }) => [s.chip, { backgroundColor: selected ? th.primary : th.surfaceAlt, opacity: pressed ? 0.8 : 1 }]}>
        {Icon ? <Icon size={iconSize.sm} color={selected ? th.primaryText : th.textMuted} strokeWidth={stroke.small} /> : null}
        <Text numberOfLines={1} style={[typeScale.label, { color: fg }]}>
          {label}
        </Text>
      </Pressable>
    );
  };

  return (
    <ScrollView
      testID="origin-filter"
      horizontal
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      accessibilityLabel={t('recs.origin.label')}
      contentContainerStyle={s.row}>
      {chip('all', t('recs.origin.all'), value === null, () => onChange(null))}
      {ORIGIN_FILTERS.map((o) =>
        chip(o.value, t(`recs.origin.${o.value}`), value === o.value, () => onChange(value === o.value ? null : o.value), o.icon),
      )}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  row: { gap: 8, paddingVertical: SLOP },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    height: CHIP_HEIGHT,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
  },
});

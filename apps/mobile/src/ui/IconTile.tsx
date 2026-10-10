/**
 * Yumaloq kvadrat ichida belgi (karta, bo'sh holat, yozuv kartasi). Rang - holat
 * tili: `record` qizil (yozuv), `ink` asosiy, tonlar - holat (ogohlantirish, xato...).
 */
import type { LucideIcon } from 'lucide-react-native';
import { View } from 'react-native';

import type { Tone } from '@/features/meeting/summaryModel';

import { type Theme, useTheme } from './theme';
import { stroke } from './tokens';

/** `raised` - `surfaceAlt` karta ICHIDA: sahifa foni (`bg`), aks holda plitka ko'rinmaydi. */
export type IconTileTone = Tone | 'plain' | 'raised' | 'record' | 'ink';
export type IconTileSize = 'sm' | 'md' | 'lg';

const SIZES: Record<IconTileSize, { box: number; icon: number; radius: number }> = {
  sm: { box: 32, icon: 16, radius: 10 },
  md: { box: 40, icon: 20, radius: 12 },
  lg: { box: 56, icon: 28, radius: 18 },
};

/** Fon va belgi rangi: bitta joyda, karta/pill/plitka bir xil ma'noda bo'yalsin. */
export function toneColors(th: Theme, tone: IconTileTone): { bg: string; fg: string } {
  if (tone === 'plain') return { bg: th.surfaceAlt, fg: th.textSoft };
  if (tone === 'raised') return { bg: th.bg, fg: th.textSoft };
  if (tone === 'record') return { bg: th.tones.bad.bg, fg: th.record };
  if (tone === 'ink') return { bg: th.primary, fg: th.primaryText };
  return th.tones[tone];
}

export function IconTile({
  icon: Icon,
  tone = 'plain',
  size = 'md',
  testID,
}: {
  icon: LucideIcon;
  tone?: IconTileTone;
  size?: IconTileSize;
  testID?: string;
}) {
  const th = useTheme();
  const d = SIZES[size];
  const c = toneColors(th, tone);
  return (
    <View
      testID={testID}
      style={{ width: d.box, height: d.box, borderRadius: d.radius, backgroundColor: c.bg, alignItems: 'center', justifyContent: 'center' }}>
      <Icon size={d.icon} color={c.fg} strokeWidth={d.icon <= 16 ? stroke.small : stroke.regular} />
    </View>
  );
}

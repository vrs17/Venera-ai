/**
 * Doira ichida bosh harflar (rasm yo'q - HRM rasm bermaydi). Chat, drawer
 * pastki qismi va Sozlamalar profili bir xil ko'rinishda bo'lsin.
 */
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from './theme';

/** "Yusuf Mamajonov" -> "YM"; bo'sh ism -> "·" (doira bo'sh qolmasin). */
export function initialsOf(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '·';
  return (parts[0][0] + (parts[1]?.[0] ?? '')).toUpperCase();
}

export function Avatar({ name, size = 36, testID }: { name: string | null | undefined; size?: number; testID?: string }) {
  const th = useTheme();
  return (
    <View
      testID={testID}
      style={[s.box, { width: size, height: size, borderRadius: size / 2, backgroundColor: th.surfaceAlt, borderColor: th.border }]}>
      {/* Shrift kattalashtirilsa ham harflar doiradan chiqmasin. */}
      <Text allowFontScaling={false} style={{ color: th.text, fontSize: Math.round(size * 0.36), fontWeight: '700' }}>
        {initialsOf(name)}
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  box: { alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
});

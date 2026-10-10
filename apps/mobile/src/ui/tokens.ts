/**
 * Dizayn o'lchamlari (Claude ilovasi uslubi): oraliq, burchak, belgi o'lchami,
 * bosish nishoni va matn shkalasi. Ranglar BU YERDA EMAS - faqat `useTheme()`
 * (yorug'/qorong'i rejim bitta joyda boshqarilsin).
 *
 * NIMA UCHUN alohida fayl: ekranlar raqamlarni o'zicha yozsa (12, 13, 14...)
 * har sahifa boshqacha ko'rinadi - egasining "hamma joyda matn, tartib yo'q"
 * shikoyatining bir sababi shu edi.
 */
import type { TextStyle } from 'react-native';

export const space = { xxs: 2, xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

export const radius = { sm: 8, md: 12, lg: 16, xl: 24, pill: 999 } as const;

export const iconSize = { xs: 14, sm: 16, md: 20, row: 22, lg: 24, xl: 28 } as const;

/** 16 px va undan kichik belgilar 2 bilan chiziladi - ingichka chiziq kichikda yo'qolib ketadi. */
export const stroke = { regular: 1.75, small: 2 } as const;

/** Android minimal bosish nishoni 44-48 dp; ro'yxat qatori kamida 52 dp. */
export const hit = { min: 44, row: 52 } as const;

/** Matn shkalasi (rangsiz - rang mavzudan olinadi). */
export const type = {
  display: { fontSize: 26, lineHeight: 32, fontWeight: '700' },
  title: { fontSize: 20, lineHeight: 26, fontWeight: '700' },
  headline: { fontSize: 17, lineHeight: 22, fontWeight: '600' },
  body: { fontSize: 16, lineHeight: 22, fontWeight: '400' },
  rowTitle: { fontSize: 16, lineHeight: 21, fontWeight: '500' },
  sub: { fontSize: 14, lineHeight: 19, fontWeight: '400' },
  caption: { fontSize: 13, lineHeight: 18, fontWeight: '400' },
  label: { fontSize: 13, lineHeight: 18, fontWeight: '600' },
  micro: { fontSize: 12, lineHeight: 16, fontWeight: '600' },
} as const satisfies Record<string, TextStyle>;

/**
 * `type` bilan bir xil obyekt. NIMA UCHUN taxallus: `import { type } from ...`
 * ba'zi vositalarda "type-only import" bilan adashtiriladi - `typography` nomi xavfsiz.
 */
export const typography = type;

/**
 * Ilovaning o'z belgilari - lucide uslubida (24×24 maydon, chiziqli). `createLucideIcon` bilan qurilgan, shuning
 * uchun lucide belgilari kabi ishlaydi: `size`, `color`, `strokeWidth` bir xil, `IconButton`, `ListRow`,
 * `EmptyState` ga to'g'ridan-to'g'ri beriladi.
 *
 * `MeetingsIcon` - Plaud (yig'ilish yozuvlari) bo'limi: tepada nutq pufagi, ostida uch kishi (yig'ilish).
 * Ega so'rovi (2026-11-19): avval bu yerda `AudioLines` turardi va u chatdagi jonli suhbat (ovozli rejim)
 * tugmasi bilan bir xil ko'rinardi. Endi `AudioLines` faqat ovoz va audio uchun: jonli suhbat, audio fayl,
 * eksportdagi audio, TTS ovoz sozlamasi, yozuv kartasi. Plaud'ga olib boradigan har joyda - shu belgi.
 */
import { createLucideIcon } from 'lucide-react-native';

export const MeetingsIcon = createLucideIcon('meetings', [
  // Nutq pufagi, dumi o'ng pastda.
  ['path', { d: 'M7 2h10a2 2 0 0 1 2 2v2.5a2 2 0 0 1-2 2l.5 2L14 8.5H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z', key: 'bubble' }],
  ['path', { d: 'M9 5.25h6', key: 'bubble-line' }],
  // O'rtadagi kishi - oldinda.
  ['circle', { cx: '12', cy: '14', r: '2.25', key: 'head-center' }],
  ['path', { d: 'M7.5 22a4.5 4.5 0 0 1 9 0', key: 'body-center' }],
  // Yon tomondagilar - orqada (yelkasi o'rtadagining ortiga kiradi).
  ['circle', { cx: '5', cy: '15', r: '2', key: 'head-left' }],
  ['path', { d: 'M1.5 22a3.5 3.5 0 0 1 4.6-3.32', key: 'body-left' }],
  ['circle', { cx: '19', cy: '15', r: '2', key: 'head-right' }],
  ['path', { d: 'M22.5 22a3.5 3.5 0 0 0-4.6-3.32', key: 'body-right' }],
]);

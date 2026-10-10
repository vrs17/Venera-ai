/**
 * Ovoz kechikishi izi - faqat dev build'da (release'da `undefined`, hech narsa yozilmaydi).
 *
 * NIMA UCHUN: prod log'ida javob tugashi bilan birinchi bo'lak so'rovi orasida ~1.8 s
 * (2026-10-10) - bu vaqt telefonda qayerga ketayotganini (kadr yetkazish, chizish, token,
 * ulanish) server ko'rmaydi. Vaqt UTC va millisekundgacha - server log'i bilan yonma-yon
 * qo'yish uchun. O'qish: `adb logcat -s ReactNativeJS | grep '\[voice\]'` yoki Metro konsoli.
 */
import type { SpeakerTraceEvent } from './speaker';

export function devVoiceTrace(scope: 'live' | 'read'): ((event: SpeakerTraceEvent, detail: string) => void) | undefined {
  // Jest ham __DEV__ - testlar chiqishini iz bilan to'ldirmaymiz.
  if (!__DEV__ || process.env.NODE_ENV === 'test') return undefined;
  return (event, detail) => {
    console.log(`[voice] ${new Date().toISOString().slice(11, 23)} ${scope} ${event} ${detail}`);
  };
}

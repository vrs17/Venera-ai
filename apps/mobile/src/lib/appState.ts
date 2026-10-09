/**
 * Ilova ekrandami (AppState) - yozish va yuklash uchun kichik yordamchilar.
 *
 * NIMA UCHUN alohida: React Native Android'da ilova fonda bo'lsa JS
 * taymerlari (setTimeout/setInterval) TO'XTAYDI (JavaTimerManager). Shuning
 * uchun bu yerda taymerga tayanadigan kutishlar devor soati bilan ham
 * tekshiriladi va fonda hech qachon taymer kutilmaydi.
 */
import { AppState } from 'react-native';

export function isForeground(): boolean {
  return AppState.currentState === 'active';
}

/**
 * Ilova ekranga chiqishini `timeoutMs` gacha kutadi.
 *
 * Android 14+ mikrofon foreground service'ini faqat ilova ekranda bo'lganda
 * boshlashga ruxsat beradi; aks holda expo-audio xatoni yutib yuboradi va
 * yozuv ekran o'chishi bilan jim to'xtaydi. Ruxsat oynasi yopilgandan keyin
 * AppState bir lahzaga `background` bo'lib turadi - shuning uchun kutamiz.
 * Fonda taymer ishlamaydi: ilova ancha keyin qaytsa ham (devor soati bo'yicha
 * muddat o'tgan) `false` - foydalanuvchi kutmagan paytda yozuv boshlanmaydi.
 */
export function waitForForeground(timeoutMs: number, now: () => number = Date.now): Promise<boolean> {
  if (isForeground()) return Promise.resolve(true);
  const started = now();
  return new Promise((resolve) => {
    let done = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let sub: { remove(): void } | null = null;
    const finish = (ok: boolean) => {
      if (done) return;
      done = true;
      if (timer) clearTimeout(timer);
      sub?.remove();
      resolve(ok);
    };
    sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') finish(now() - started <= timeoutMs);
    });
    timer = setTimeout(() => finish(isForeground()), timeoutMs);
  });
}

/**
 * Uzoq sinxron ish (butun fayl SHA-256) bo'laklari orasida UI'ga navbat berish.
 * Faqat ilova ekranda bo'lganda (u yerda taymer ishlaydi va UI qotishi
 * seziladi); fonda darhol qaytadi - aks holda yuklash ilova qaytguncha osilib qoladi.
 */
export function yieldToUi(): Promise<void> {
  if (!isForeground()) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      sub.remove();
      resolve();
    };
    const sub = AppState.addEventListener('change', (s) => {
      if (s !== 'active') finish();
    });
    const timer = setTimeout(finish, 0);
  });
}

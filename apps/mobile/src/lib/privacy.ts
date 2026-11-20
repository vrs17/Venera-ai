/**
 * Maxfiylik siyosati - Google Play talabi (User Data siyosati): havola Play Console'dagi
 * maydonda HAM, ilovaning ICHIDA HAM bo'lishi shart. Ilovada ikki joyda: kirish ekrani
 * (kirmagan odam ham o'qiy olsin) va Sozlamalar.
 *
 * Sahifa web'da, kirishsiz ochiladi (`apps/web/src/views/PrivacyView.vue`); uz/ru/en
 * tanlovi sahifaning o'zida.
 *
 * Manzil QAT'IY - `apiBaseUrl` dan olinmaydi: ichki yoki dev build boshqa serverga ulansa
 * ham siyosat bitta va Play Console'dagi manzil bilan aynan bir xil bo'lishi kerak.
 */
import { Linking } from 'react-native';

export const PRIVACY_URL = 'https://llm.brb-tech.uz/privacy';

/** Tizim brauzerida ochadi. Brauzer topilmasa jim qoladi - qiladigan boshqa ish yo'q. */
export function openPrivacyPolicy(): Promise<void> {
  return Linking.openURL(PRIVACY_URL).then(
    () => undefined,
    () => undefined,
  );
}

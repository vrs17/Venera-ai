/**
 * Sozlamalar hub'idagi "Qo'ng'iroq yozuvlari" qatori uchun QIYMAT (spec: subtitle holatni
 * aytadi): "O'chiq" / "Ruxsat kerak" / "Qo'lda yuborish" / "Avtomatik yuborish". Qator faqat
 * qo'ng'iroq importi bor qurilmada ko'rsatiladi (`callsSupported()`).
 *
 * NIMA UCHUN "Ruxsat kerak": yoqilgan, lekin audio ruxsati yo'q bo'lsa hech narsa ishlamaydi -
 * hub "Qo'lda yuborish" deb ishlayotgandek ko'rsatmasin (Qo'ng'iroqlar bo'limi esa ruxsat so'raydi).
 */
import { hasAudioReadPermission } from '@/features/entry/nativeEntry';
import type { TFn } from '@/i18n';

import { useCalls, type CallsPrefs } from './callsStore';
import { callsSupported } from './permission';

export function callsHubValue(t: TFn, p: Pick<CallsPrefs, 'enabled' | 'autoSend'>, permitted = true): string {
  if (!p.enabled) return t('calls.valueOff');
  if (!permitted) return t('calls.permTitle');
  return p.autoSend ? t('calls.valueAuto') : t('calls.valueManual');
}

function safePermitted(): boolean {
  try {
    return hasAudioReadPermission() === true;
  } catch {
    return false;
  }
}

/** Hub qatori: `{ visible, value, tone }` - ko'rinmasa qator chizilmaydi; `tone` - ListRow subtitleTone. */
export function useCallsHubRow(t: TFn): { visible: boolean; value: string; tone: 'warn' | undefined } {
  const enabled = useCalls((s) => s.enabled);
  const autoSend = useCalls((s) => s.autoSend);
  const visible = callsSupported();
  const permitted = visible && enabled ? safePermitted() : true;
  return { visible, value: callsHubValue(t, { enabled, autoSend }, permitted), tone: permitted ? undefined : 'warn' };
}

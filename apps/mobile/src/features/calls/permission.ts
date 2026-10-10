/**
 * Audio fayllarni o'qish ruxsati (Android 13+ READ_MEDIA_AUDIO, undan past
 * READ_EXTERNAL_STORAGE) va bir martalik rozilik eslatmasi.
 *
 * NIMA UCHUN yangi kutubxonasiz: React Native `PermissionsAndroid` yetarli; ruxsat nomini
 * native modul (SDK versiyasi bo'yicha) beradi. "Boshqa so'ralmasin" tanlangan bo'lsa tizim
 * oynasi umuman chiqmaydi - u holda ilova sozlamasini ochishni taklif qilamiz.
 */
import { Alert, Linking, PermissionsAndroid, Platform, type Permission } from 'react-native';

import { audioReadPermission, hasAudioReadPermission, isCallImportAvailable } from '@/features/entry/nativeEntry';
import type { TFn } from '@/i18n';

import { useCalls } from './callsStore';

export type AudioPermission = 'granted' | 'denied' | 'blocked' | 'unavailable';

/**
 * Qo'ng'iroq importi shu qurilmada umuman bormi (Android + yangi APK). try/catch: boshqa
 * ekran testlari `nativeEntry` ni bu funksiyasiz mock qiladi - hub qatori ularni yiqitmasin.
 */
export function callsSupported(): boolean {
  try {
    return Platform.OS === 'android' && isCallImportAvailable() === true;
  } catch {
    return false;
  }
}

/**
 * Tizim sozlamasidagi ruxsat nomi: Android 13+ "Musiqa va audio" (READ_MEDIA_AUDIO), undan
 * pastda "Fayllar va media" (READ_EXTERNAL_STORAGE). NIMA UCHUN: foydalanuvchi sozlamada
 * aynan ko'rinadigan nomni qidiradi - yo'q nomni aytsak adashadi.
 */
export function audioPermissionLabel(t: TFn): string {
  return audioReadPermission() === 'android.permission.READ_EXTERNAL_STORAGE' ? t('calls.permNameFiles') : t('calls.permNameAudio');
}

export async function requestAudioPermission(t: TFn): Promise<AudioPermission> {
  const perm = audioReadPermission();
  if (!perm || !callsSupported()) return 'unavailable';
  if (hasAudioReadPermission()) return 'granted';
  try {
    // "Bekor qilish" tugmasi YO'Q: RN tushuntirishdan keyin qaysi tugma bosilsa ham tizim oynasini
    // ochadi - "bekor" deb yozib, baribir so'rash aldov bo'lardi.
    const r = await PermissionsAndroid.request(perm as Permission, {
      title: t('calls.permRationaleTitle'),
      message: t('calls.permRationale'),
      buttonPositive: t('calls.permContinue'),
    });
    if (r === PermissionsAndroid.RESULTS.GRANTED) return 'granted';
    if (r === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN) return 'blocked';
    return 'denied';
  } catch {
    return 'denied';
  }
}

export function openAppSettings(): void {
  try {
    void Promise.resolve(Linking.openSettings()).catch(() => {});
  } catch {
    /* sozlama ochilmasa ham ilova ishlashda davom etadi */
  }
}

/** Ruxsat butunlay yopilgan: nima qilishni aytib, ilova sozlamasini ochish taklifi. */
export function explainBlocked(t: TFn): void {
  Alert.alert(t('calls.permTitle'), t('calls.permBlocked', { perm: audioPermissionLabel(t) }), [
    { text: t('common.cancel'), style: 'cancel' },
    { text: t('calls.permOpenSettings'), onPress: openAppSettings },
  ]);
}

/**
 * Bir martalik rozilik eslatmasi (kompaniya qoidasi: suhbatdosh ogohlantirilgan bo'lsin).
 * Allaqachon ko'rilgan bo'lsa darhol true.
 */
export function confirmCallConsent(t: TFn): Promise<boolean> {
  if (useCalls.getState().consentAt != null) return Promise.resolve(true);
  return new Promise((resolve) => {
    let done = false;
    const finish = (ok: boolean) => {
      if (done) return;
      done = true;
      if (ok) useCalls.getState().set({ consentAt: Date.now() });
      resolve(ok);
    };
    Alert.alert(
      t('calls.consentTitle'),
      t('calls.consentBody'),
      [
        { text: t('common.cancel'), style: 'cancel', onPress: () => finish(false) },
        { text: t('calls.consentOk'), onPress: () => finish(true) },
      ],
      // Oynadan tashqariga bosib yopilsa - rozilik YO'Q.
      { cancelable: true, onDismiss: () => finish(false) },
    );
  });
}

/**
 * Avtomatik yuborishni yoqishdan oldin HAR SAFAR: endi shaxsiy qo'ng'iroqlar ham o'zi ketadi.
 * NIMA UCHUN alohida: bir martalik rozilik "suhbatdoshni ogohlantiring" haqida - u qo'lda
 * yuborishda yetarli, lekin hamma yangi yozuvni serverga yuborish boshqa, kattaroq qaror.
 * Bu oyna kompaniya qoidasini ham aytadi - tasdiqlansa rozilik ham ko'rilgan hisoblanadi.
 */
export function confirmAutoSend(t: TFn): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false;
    const finish = (ok: boolean) => {
      if (done) return;
      done = true;
      resolve(ok);
    };
    Alert.alert(
      t('calls.autoConfirmTitle'),
      t('calls.autoConfirmBody'),
      [
        { text: t('common.cancel'), style: 'cancel', onPress: () => finish(false) },
        { text: t('calls.enable'), onPress: () => finish(true) },
      ],
      { cancelable: true, onDismiss: () => finish(false) },
    );
  });
}

/** Avtomatik yuborishni yoqish (tasdiqdan keyin); faqat SHU paytdan keyingi qo'ng'iroqlar ketadi. */
export async function enableAutoSend(t: TFn): Promise<boolean> {
  if (!(await confirmAutoSend(t))) return false;
  const now = Date.now();
  useCalls.getState().set({ autoSend: true, autoSendSince: now, consentAt: useCalls.getState().consentAt ?? now });
  return true;
}

export type EnableResult = 'enabled' | 'no_permission' | 'cancelled' | 'unavailable';

/**
 * "Yoqish": rozilik eslatmasi -> ruxsat -> aniqlash yoqiladi. Ruxsat berilmasa ham aniqlash
 * yoqiladi (ro'yxat "Ruxsat kerak" holatini ko'rsatadi) - foydalanuvchi qarorini unutmaymiz.
 */
export async function enableCallDetection(t: TFn): Promise<EnableResult> {
  if (!callsSupported()) return 'unavailable';
  if (!(await confirmCallConsent(t))) return 'cancelled';
  useCalls.getState().set({ enabled: true });
  const perm = await requestAudioPermission(t);
  if (perm === 'granted') return 'enabled';
  if (perm === 'blocked') explainBlocked(t);
  return 'no_permission';
}

/** "Ruxsat berish" tugmasi: so'raydi; yopilgan bo'lsa sozlamani ochishni taklif qiladi. */
export async function askAudioPermission(t: TFn): Promise<AudioPermission> {
  const perm = await requestAudioPermission(t);
  if (perm === 'blocked') explainBlocked(t);
  return perm;
}

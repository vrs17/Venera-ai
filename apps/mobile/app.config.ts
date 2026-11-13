/**
 * Barno AI (mobil ilova) - Expo konfiguratsiyasi (spec 7.2).
 *
 * Ilova nomi "Barno AI" (2026-10-09: mahsulot "Venera AI" dan "Barno AI" ga o'zgardi):
 * asosiy ekran - Mini App'ning o'zi, Telegram'dagi bilan bir xil. Texnik nomlar
 * O'ZGARMAYDI - slug, paket (`uz.brbtech.venera.meetings`), sxema (`venera-rec`), env
 * (`VENERA_*`): o'rnatilgan ilova ustidan yangilanadi, yorliq va havolalar ishlayveradi.
 *
 * NIMA UCHUN app.json emas, app.config.ts: API manzili va dev/prod farqi
 * (cleartext HTTP faqat dev'da) build paytida env'dan olinadi. Prod APK'da
 * oddiy HTTP hech qachon yoqilmasligi kerak.
 *
 * Env:
 *   APP_VARIANT     development | preview | production (default production)
 *   VENERA_API_URL  API manzili, default https://llm.brb-tech.uz
 *   VENERA_WEB_URL  (ixtiyoriy) Mini App manzili (`<url>/tg/` - asosiy ekran).
 *                   Default - VENERA_API_URL; dev'da API (:8001) Mini App'ni bermasa
 *                   Vite manziliga qaratiladi.
 *
 * DIQQAT: bu fayl HAR Expo CLI buyrug'ida qayta o'qiladi (prebuild, run:android,
 * start). Dev client `extra.apiBaseUrl` ni Metro bergan manifestdan oladi -
 * o'zgaruvchilar faqat prebuild'ga berilsa dev client PROD'ga ulanadi. Shuning
 * uchun ularni gitga tushmaydigan `apps/mobile/.env.local` ga yozing (Expo CLI
 * .env fayllarini o'zi yuklaydi) - README 3.
 */
import type { ConfigContext, ExpoConfig } from 'expo/config';

const variant = process.env.APP_VARIANT ?? 'production';
const isDev = variant === 'development';
const apiBaseUrl = (process.env.VENERA_API_URL ?? 'https://llm.brb-tech.uz').replace(/\/+$/, '');

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'Barno AI',
  slug: 'venera-yozuv',
  version: '1.3.12',
  scheme: 'venera-rec',
  orientation: 'portrait',
  userInterfaceStyle: 'automatic',
  // Ikonka: Barno AI yulduzchasi - Slack/Telegram'dagi Barno AI ikonkasi va web favicon.svg bilan bir xil
  // shakl, rang theme.ts `brand` (#EE5A24). Ilgari ikonka berilmagan edi - APK'da Android'ning standart robotchasi turardi.
  icon: './assets/icon.png',
  android: {
    package: 'uz.brbtech.venera.meetings',
    versionCode: 17,
    // Adaptive ikonka (Android 8+): oq fon + yulduzcha (qatlamning 50% - har qanday niqobda uchlari kesilmaydi).
    // monochromeImage - Android 13+ "mavzuli ikonkalar" yoqilganda rangni tizim beradi.
    adaptiveIcon: {
      foregroundImage: './assets/adaptive-icon.png',
      monochromeImage: './assets/adaptive-icon-mono.png',
      backgroundColor: '#FFFFFF',
    },
    // Yozuvlar va tokenlar Google zaxirasiga tushmasligi kerak (spec 2.3, 4.4).
    allowBackup: false,
    // Mikrofon/bildirishnoma ruxsatlarini expo-audio plagini qo'shadi.
    // Bu ruxsatlar bizga KERAK EMAS - kutubxonalar o'zi qo'shib yuborsa olib tashlanadi.
    // READ_EXTERNAL_STORAGE bu ro'yxatda YO'Q (2026-10-10): Android 8-12 da Samsung qo'ng'iroq
    // yozuvlarini MediaStore'dan o'qish uchun kerak (venera-entry manifesti, maxSdkVersion 32).
    // Bloklansa tools:node="remove" uni ham o'chiradi - ruxsat so'ralmay, ro'yxat doim bo'sh qoladi.
    blockedPermissions: [
      'android.permission.SYSTEM_ALERT_WINDOW',
      'android.permission.WRITE_EXTERNAL_STORAGE',
      'android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK',
      // Google Play Protect (2026-11-09, ega qarori): "kuchaytirilgan firibgarlikdan himoya"
      // sideload qilingan ilovani o'rnatishning O'ZIDA to'sadi, agar u SMS (o'qish/qabul),
      // qo'ng'iroqlar jurnali, boshqa ilova o'rnatish yoki hamma ilovalarni ko'rish ruxsatini
      // e'lon qilsa - bank kodlarini o'g'irlovchi zararli ilovalarning belgilari. Barno bularning
      // hech birini ishlatmaydi; bu yerda ular kelajakdagi kutubxona qo'shib yuborsa ham
      // birlashtirilgan manifestdan olib tashlanadi (tools:node="remove"). Testi: playProtect.test.ts.
      'android.permission.RECEIVE_SMS',
      'android.permission.READ_SMS',
      'android.permission.SEND_SMS',
      'android.permission.RECEIVE_MMS',
      'android.permission.RECEIVE_WAP_PUSH',
      'android.permission.READ_CALL_LOG',
      'android.permission.WRITE_CALL_LOG',
      'android.permission.PROCESS_OUTGOING_CALLS',
      'android.permission.REQUEST_INSTALL_PACKAGES',
      'android.permission.QUERY_ALL_PACKAGES',
      // 1.3.5 APK auditi: kutubxona qo'shadi, ilova ishlatmaydi (keraksiz ruxsat - ortiqcha shubha).
      // androidx.biometric (expo-secure-store): faqat `requireAuthentication`/`canUseBiometricAuthentication`
      // bilan ishlaydi - biz SecureStore'ni oddiy get/set/delete bilan chaqiramiz.
      'android.permission.USE_BIOMETRIC',
      'android.permission.USE_FINGERPRINT',
      // installreferrer (expo-application): faqat `getInstallReferrerAsync` uchun - chaqirilmaydi.
      'com.google.android.finsky.permission.BIND_GET_INSTALL_REFERRER_SERVICE',
    ],
    permissions: ['android.permission.RECORD_AUDIO', 'android.permission.POST_NOTIFICATIONS', 'android.permission.VIBRATE'],
  },
  ios: {
    // iOS v1'da yig'ilmaydi (spec 1, non-goals); kod platformaga bog'liq emas.
    bundleIdentifier: 'uz.brbtech.venera.meetings',
    supportsTablet: false,
  },
  plugins: [
    'expo-router',
    [
      // Ochilish ekrani: theme.ts fonlari (#FFFFFF / #0E0E0F) va brend rangidagi yulduzcha.
      'expo-splash-screen',
      {
        image: './assets/splash-icon.png',
        imageWidth: 120,
        backgroundColor: '#FFFFFF',
        dark: { image: './assets/splash-icon-dark.png', backgroundColor: '#0E0E0F' },
      },
    ],
    [
      'expo-audio',
      {
        microphonePermission: "Barno AI yig'ilishlarni yozib olish va ovozli savollar uchun mikrofondan foydalanadi.",
        recordAudioAndroid: true,
        // microphone turidagi foreground service + FOREGROUND_SERVICE_MICROPHONE.
        enableBackgroundRecording: true,
        // Ijro uchun FGS kerak emas - MEDIA_PLAYBACK ruxsati bloklangan.
        enableBackgroundPlayback: false,
      },
    ],
    ['expo-secure-store', { configureAndroidBackup: false }],
    [
      'expo-build-properties',
      {
        android: {
          compileSdkVersion: 36,
          targetSdkVersion: 36,
          minSdkVersion: 26,
          enableMinifyInReleaseBuilds: true,
          enableShrinkResourcesInReleaseBuilds: true,
          // Dev API http://<LAN>:8001 - faqat development build'da.
          ...(isDev ? { usesCleartextTraffic: true } : {}),
        },
      },
    ],
    'expo-quick-actions',
    // Release faqat o'z kalitimiz bilan (debug kalit bilan pilot APK chiqmasin) - README 4.
    './plugins/withReleaseSigning',
  ],
  experiments: {
    typedRoutes: false,
  },
  extra: {
    apiBaseUrl,
    appVariant: variant,
  },
});

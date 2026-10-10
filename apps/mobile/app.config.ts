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
  version: '1.3.0',
  scheme: 'venera-rec',
  orientation: 'portrait',
  userInterfaceStyle: 'automatic',
  android: {
    package: 'uz.brbtech.venera.meetings',
    versionCode: 5,
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

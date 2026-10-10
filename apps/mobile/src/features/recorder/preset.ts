/**
 * Yozish sozlamasi (spec 2.3 "Format"): AAC-LC, ADTS oqimi (.aac), mono,
 * 16 kHz, 48 kbps (~21.6 MB/soat).
 *
 * NIMA UCHUN ADTS (m4a emas): ilova yoki telefon o'chib qolsa ham fayl
 * o'qiladi - `moov` bo'limi yo'q, yo'qoladigan narsa yo'q. Server ADTS'ni
 * ffmpeg'siz o'zi parse qiladi va m4a'ga o'giradi.
 *
 * audioSource/sampleRate/bitRate serverdan (`GET /meetings/config` ->
 * `recording`) olinadi - shunda voice_recognition / mic / camcorder'ni
 * APK qayta yig'masdan sinab ko'ramiz.
 */
// Faqat tiplar: bu modul toza qolsin (Jest'da native expo-audio yuklanmaydi).
import type { RecordingOptions, RecordingSource } from 'expo-audio';

import type { RecordingConfig } from '@/api/types';

export const RECORDING_SOURCES: RecordingSource[] = [
  'voice_recognition',
  'mic',
  'camcorder',
  'voice_communication',
  'unprocessed',
  'default',
];

export const MEETING_PRESET: RecordingOptions = {
  extension: '.aac',
  sampleRate: 16000,
  numberOfChannels: 1,
  bitRate: 48000,
  isMeteringEnabled: true,
  directory: 'document',
  android: {
    extension: '.aac',
    outputFormat: 'aac_adts',
    audioEncoder: 'aac',
    audioSource: 'voice_recognition',
  },
  ios: {
    // iOS v1'da yig'ilmaydi; m4a (AAC) - server mvhd orqali o'qiydi.
    extension: '.m4a',
    outputFormat: 'aac ', // IOSOutputFormat.MPEG4AAC
    audioQuality: 96, // AudioQuality.HIGH
    sampleRate: 16000,
  },
  web: {
    mimeType: 'audio/webm',
    bitsPerSecond: 48000,
  },
};

function isSource(v: unknown): v is RecordingSource {
  return typeof v === 'string' && (RECORDING_SOURCES as string[]).includes(v);
}

function inRange(v: unknown, min: number, max: number): v is number {
  return typeof v === 'number' && Number.isFinite(v) && v >= min && v <= max;
}

/** ADTS sarlavhasi har AAC kadrida 7 bayt (CRC'siz); kadr = 1024 namuna. */
export const ADTS_HEADER_BYTES = 7;
export const AAC_FRAME_SAMPLES = 1024;
/**
 * Native limit server chegarasidan shuncha soniya OLDIN ishlaydi: enkoder
 * bitrate'ni aniq ushlamasa ham (bit rezervuari) fayl `maxMinutes*60+30` dan
 * oshib ketmasin - aks holda server butun yozuvni `too_long` deb rad etadi.
 */
export const NATIVE_LIMIT_MARGIN_SEC = 60;
/** expo-audio `maxFileSize` Kotlin'da Int. */
const INT32_MAX = 2_147_483_647;

/** Kutilgan fayl o'sishi, bayt/s: AAC bitrate + ADTS sarlavhalari (16 kHz da ~1.8%). */
export function adtsBytesPerSec(bitRate: number, sampleRate: number): number {
  return bitRate / 8 + (ADTS_HEADER_BYTES * sampleRate) / AAC_FRAME_SAMPLES;
}

/**
 * MediaRecorder `setMaxFileSize` uchun bayt (spec 2.3 "Limits").
 *
 * NIMA UCHUN: avtomatik to'xtash JS taymerida edi, React Native esa Android'da
 * ilova fonda / ekran o'chiq bo'lsa JS taymerlarini to'xtatadi. Cho'ntakdagi
 * telefon limitdan keyin ham yozishda davom etardi va server butun yig'ilishni
 * rad etardi. Fayl hajmi chegarasi native'da ishlaydi: MediaRecorder
 * MAX_FILESIZE_REACHED beradi, expo-audio yozuvni to'xtatib hodisa yuboradi.
 * Pauza faylni o'stirmaydi - limit pauzani to'g'ri hisobga oladi.
 */
export function maxFileSizeFor(maxSec: number, bitRate: number, sampleRate: number): number {
  const sec = Math.max(60, maxSec - NATIVE_LIMIT_MARGIN_SEC);
  return Math.min(INT32_MAX, Math.floor(adtsBytesPerSec(bitRate, sampleRate) * sec));
}

/**
 * Server konfigi + (dev) qo'lda tanlangan manba -> yakuniy preset.
 * Noto'g'ri qiymat kelsa jimgina default qoladi - yozish hech qachon
 * konfig xatosi tufayli ishlamay qolmasligi kerak. `maxSec` berilsa
 * Android'da native hajm chegarasi (`maxFileSize`) qo'yiladi.
 */
export function presetFromConfig(
  rec: Partial<RecordingConfig> | null | undefined,
  sourceOverride?: string | null,
  maxSec?: number | null,
): RecordingOptions {
  const sampleRate = inRange(rec?.sampleRate, 8000, 48000) ? rec!.sampleRate! : MEETING_PRESET.sampleRate;
  const bitRate = inRange(rec?.bitRate, 16000, 256000) ? rec!.bitRate! : MEETING_PRESET.bitRate;
  const source = isSource(sourceOverride) ? sourceOverride : isSource(rec?.audioSource) ? rec!.audioSource : 'voice_recognition';
  const limit = typeof maxSec === 'number' && Number.isFinite(maxSec) && maxSec > 0 ? { maxFileSize: maxFileSizeFor(maxSec, bitRate, sampleRate) } : {};
  return {
    ...MEETING_PRESET,
    sampleRate,
    bitRate,
    android: { ...MEETING_PRESET.android, sampleRate, audioSource: source as RecordingSource, ...limit },
    ios: { ...MEETING_PRESET.ios, sampleRate },
  };
}

/**
 * Server qabul qiladigan audio turlari (`ACCEPTED_TYPES`: aac, mp4, mpeg, wav, ogg) - taxalluslar,
 * saqlanadigan kengaytmalar va fayl boshi tekshiruvi. Server bilan AYNAN bir xil bo'lishi shart:
 * `apps/api/app/services/meetings/audio.py` (`TYPE_ALIASES`, `EXTENSIONS`, `sniff`, `mp3_header`).
 *
 * NIMA UCHUN fayl boshi tekshiriladi: server birinchi bo'lakda (`PUT /audio`, offset 0) xuddi shu
 * qoidani qo'llaydi va mos kelmasa 415 qaytaradi. Telefonda oldindan aytsak, odam katta faylni
 * befoyda yuklamaydi va navbatda "yuklanmadi" qatori qolmaydi.
 *
 * Sof modul (native'siz): import nomlari, navbat, uploader va eksport varag'i bir manbadan o'qiydi.
 */
import type { AudioContentType } from '@/api/types';

export const AUDIO_CONTENT_TYPES: readonly AudioContentType[] = ['audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/wav', 'audio/ogg'];

export function isAudioContentType(v: unknown): v is AudioContentType {
  return typeof v === 'string' && (AUDIO_CONTENT_TYPES as readonly string[]).includes(v);
}

export type AudioExtension = '.aac' | '.m4a' | '.mp3' | '.wav' | '.ogg';

/** Tur -> saqlanadigan kengaytma (server `EXTENSIONS`; pleer va STT formatni shundan ham taniydi). */
export const AUDIO_EXTENSIONS: Readonly<Record<AudioContentType, AudioExtension>> = {
  'audio/aac': '.aac',
  'audio/mp4': '.m4a',
  'audio/mpeg': '.mp3',
  'audio/wav': '.wav',
  'audio/ogg': '.ogg',
};

/**
 * Bir formatning boshqa nomlari -> kanonik tur (server `TYPE_ALIASES` nusxasi). `audio/aac-adts` -
 * serverda yo'q, lekin native import ham uni AAC deb taniydi (faqat KIRUVCHI MIME uchun).
 * Map - `Object` emas: "constructor" kabi kalit prototipdan qiymat qaytarmasin.
 */
const TYPE_ALIASES: ReadonlyMap<string, AudioContentType> = new Map<string, AudioContentType>([
  ['audio/mp3', 'audio/mpeg'],
  ['audio/x-mp3', 'audio/mpeg'],
  ['audio/x-mpeg', 'audio/mpeg'],
  ['audio/mpeg3', 'audio/mpeg'],
  ['audio/x-mpeg-3', 'audio/mpeg'],
  ['audio/mpg', 'audio/mpeg'],
  ['audio/x-wav', 'audio/wav'],
  ['audio/wave', 'audio/wav'],
  ['audio/vnd.wave', 'audio/wav'],
  ['audio/x-pn-wav', 'audio/wav'],
  ['audio/x-m4a', 'audio/mp4'],
  ['audio/m4a', 'audio/mp4'],
  ['audio/x-aac', 'audio/aac'],
  ['audio/aacp', 'audio/aac'],
  ['audio/aac-adts', 'audio/aac'],
  ['audio/opus', 'audio/ogg'],
  ['audio/oga', 'audio/ogg'],
  ['audio/x-ogg', 'audio/ogg'],
  ['application/ogg', 'audio/ogg'],
]);

/** `Audio/MP3; charset=x` -> `audio/mpeg` (server `canonical_type`); qabul qilinmaydigan tur - null. */
export function canonicalAudioType(mime: string | null | undefined): AudioContentType | null {
  const value = (mime ?? '').trim().toLowerCase().split(';')[0].trim();
  const canonical = TYPE_ALIASES.get(value) ?? value;
  return isAudioContentType(canonical) ? canonical : null;
}

/** Kengaytma -> tur. Opus/Vorbis ham Ogg konteyneri (`.oga`, `.opus`). */
const EXT_TYPES: ReadonlyMap<string, AudioContentType> = new Map<string, AudioContentType>([
  ['m4a', 'audio/mp4'],
  ['mp4', 'audio/mp4'],
  ['aac', 'audio/aac'],
  ['mp3', 'audio/mpeg'],
  ['wav', 'audio/wav'],
  ['ogg', 'audio/ogg'],
  ['oga', 'audio/ogg'],
  ['opus', 'audio/ogg'],
]);

/** Aniq boshqa (server olmaydigan) audio kengaytmalari - bunda MIME'ga ishonilmaydi. */
const OTHER_AUDIO_EXT = new Set(['amr', 'awb', '3gp', '3ga', 'flac', 'wma', 'mid', 'midi', 'webm']);

/**
 * Fayl turi: avval kengaytma, keyin MIME (taxalluslar bilan). NIMA UCHUN kengaytma birinchi:
 * fayl manbai (Telegram, fayl menejeri) MIME'ni ko'pincha noto'g'ri yoki umumiy beradi.
 * `null` - server qabul qilmaydi (flac, amr, webm ...).
 */
export function audioTypeFor(name: string | null | undefined, mimeType?: string | null): AudioContentType | null {
  const n = name ?? '';
  const dot = n.lastIndexOf('.');
  const ext = dot >= 0 && dot < n.length - 1 ? n.slice(dot + 1).toLowerCase() : '';
  const byExt = EXT_TYPES.get(ext);
  if (byExt) return byExt;
  if (OTHER_AUDIO_EXT.has(ext)) return null;
  return canonicalAudioType(mimeType);
}

function asciiAt(b: Uint8Array, at: number, text: string): boolean {
  if (at + text.length > b.length) return false;
  for (let i = 0; i < text.length; i++) if (b[at + i] !== text.charCodeAt(i)) return false;
  return true;
}

/** AAC ADTS: sinx 0xFFF VA qatlam bitlari 00 (MP3 kadri ham 0xFFF bilan boshlanadi, qatlami esa 00 emas). */
function isAdts(b: Uint8Array): boolean {
  return b.length >= 2 && b[0] === 0xff && (b[1] & 0xf6) === 0xf0;
}

/**
 * MPEG audio (MP3) kadr sarlavhasi - server `mp3_header`: 11 bitli sinx, versiya bitlari 01
 * (zahira) emas, qatlam bitlari 00 emas (00 - bu ADTS/AAC), bitreyt indeksi 0/15 emas, chastota 3 emas.
 */
export function isMp3FrameHeader(b: Uint8Array): boolean {
  if (b.length < 4 || b[0] !== 0xff || (b[1] & 0xe0) !== 0xe0) return false;
  const version = (b[1] >> 3) & 3;
  const layer = (b[1] >> 1) & 3;
  if (version === 1 || layer === 0) return false;
  const bitrate = b[2] >> 4;
  const rate = (b[2] >> 2) & 3;
  return bitrate !== 0 && bitrate !== 15 && rate !== 3;
}

/** Fayl boshi e'lon qilingan turga mosmi - server `sniff` (birinchi bo'lak) bilan AYNAN bir xil. */
export function matchesAudioType(head: Uint8Array, type: AudioContentType): boolean {
  switch (type) {
    case 'audio/mpeg':
      return asciiAt(head, 0, 'ID3') || isMp3FrameHeader(head);
    case 'audio/wav':
      return asciiAt(head, 0, 'RIFF') && asciiAt(head, 8, 'WAVE');
    case 'audio/aac':
      return isAdts(head);
    case 'audio/mp4':
      return asciiAt(head, 4, 'ftyp');
    case 'audio/ogg':
      return asciiAt(head, 0, 'OggS');
    default:
      return false;
  }
}

/** Fayl boshiga ko'ra haqiqiy tur (kengaytma bilan solishtirish uchun); hech biriga mos kelmasa null. */
export function sniffAudioType(head: Uint8Array): AudioContentType | null {
  return AUDIO_CONTENT_TYPES.find((type) => matchesAudioType(head, type)) ?? null;
}

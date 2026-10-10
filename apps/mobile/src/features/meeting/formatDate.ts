/**
 * Sana/vaqt formatlari. Vaqt zonasi DOIM Asia/Tashkent (UTC+5, yozgi vaqt
 * yo'q) - yig'ilish Toshkentda bo'lgan, telefon zonasi boshqa bo'lsa ham
 * "16:00" o'zgarmasligi kerak (server export bilan bir xil, spec 3.2 #20).
 *
 * Intl'ga tayanmaymiz: Hermes'da `uz` lokali yo'q va oy nomlari ingliz
 * tilida chiqadi.
 */
import type { Lang } from '@/api/types';

const TZ_OFFSET_MS = 5 * 60 * 60 * 1000;

const MONTHS: Record<Lang, string[]> = {
  uz: ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentyabr', 'oktyabr', 'noyabr', 'dekabr'],
  ru: ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'],
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
};

const pad = (n: number) => String(n).padStart(2, '0');

export interface TashkentParts {
  year: number;
  month: number; // 1-12
  day: number;
  hour: number;
  minute: number;
}

export function tashkentParts(input: string | number | Date): TashkentParts | null {
  const ms = input instanceof Date ? input.getTime() : typeof input === 'number' ? input : Date.parse(input);
  if (!Number.isFinite(ms)) return null;
  const d = new Date(ms + TZ_OFFSET_MS);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
  };
}

function dayMonth(day: number, month: number, lang: Lang, year?: number): string {
  const name = MONTHS[lang][month - 1];
  if (lang === 'ru') return `${day} ${name}${year ? ` ${year}` : ''}`;
  if (lang === 'en') return `${name} ${day}${year ? `, ${year}` : ''}`;
  return `${year ? `${year}-yil ` : ''}${day}-${name}`;
}

/** `10-oktyabr, 16:00` | `10 октября, 16:00` | `October 10, 16:00`. */
export function formatDateTime(input: string | number | Date, lang: Lang, opts: { withYear?: boolean } = {}): string {
  const p = tashkentParts(input);
  if (!p) return '';
  return `${dayMonth(p.day, p.month, lang, opts.withYear ? p.year : undefined)}, ${pad(p.hour)}:${pad(p.minute)}`;
}

/** Faqat sana ('YYYY-MM-DD', vaqt zonasiz) -> `10-oktyabr` (`withYear` - `2025-yil 10-oktyabr`). */
export function formatDay(isoDate: string, lang: Lang, opts: { withYear?: boolean } = {}): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!m) return isoDate;
  return dayMonth(Number(m[3]), Number(m[2]), lang, opts.withYear ? Number(m[1]) : undefined);
}

/**
 * Faqat soat `HH:MM` (Toshkent). Yozuvlar ro'yxatida kun bo'lim sarlavhasida
 * ("Bugun"), kartada esa faqat soat - sana ikki marta takrorlanmasin.
 * `lang` - kelajakda 12 soatlik format kerak bo'lsa imzo o'zgarmasin.
 */
export function formatTime(input: string | number | Date, _lang?: Lang): string {
  const p = tashkentParts(input);
  if (!p) return '';
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

/** Toshkent kuni kaliti `YYYY-MM-DD` (ro'yxatni kunlarga guruhlash uchun); noto'g'ri sana -> ''. */
export function tashkentDayKey(input: string | number | Date): string {
  const p = tashkentParts(input);
  if (!p) return '';
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

/** Muddat: aniq sana bo'lsa formatlangan, aks holda aytilgan ibora. */
export function formatDue(date: string | null, time: string | null, raw: string | null, lang: Lang): string | null {
  if (date) return time ? `${formatDay(date, lang)}, ${time}` : formatDay(date, lang);
  if (raw) return time ? `${raw}, ${time}` : raw;
  return time;
}

/** Dalil chipi va transkript: `12:34` yoki `1:02:10`. */
export function formatClock(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return '--:--';
  const total = Math.floor(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

/** Davomiylik: `1:02:10` / `12:34`; null -> ''. */
export function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return '';
  return formatClock(sec);
}

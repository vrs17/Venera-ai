/**
 * Samsung qo'ng'iroq yozuvi nomidan suhbatdosh va vaqt (sof funksiyalar, native'siz).
 *
 * Samsung Telefon nomlari (One UI versiyasi va tiliga qarab):
 *   "Call recording Alisher_241010_143012.m4a"   (One UI 4+, Recordings/Call/)
 *   "Запись вызова Алишер_241010_143012.m4a"     (rus tilidagi telefon)
 *   "+998901234567_241010_143012.m4a"            (kontaktda yo'q raqam)
 *   "Alisher_20241010_143012.m4a", "Alisher 2024-10-10 14-30-12.m4a" (eski/boshqa ilovalar)
 *
 * NIMA UCHUN nomdan: MediaStore'da suhbatdosh yo'q, fayl vaqti (mtime) esa qo'ng'iroq
 * OXIRI va nusxalanganda (messenjer orqali ulashilgan fayl) o'zgaradi. Nomdagi vaqt -
 * qo'ng'iroq BOSHI, telefonning mahalliy vaqtida. Nom tanilmasa - fayl sanasi.
 */
import type { TFn } from '@/i18n';

export interface ParsedCallName {
  /** Kontakt nomi yoki raqam; ajratib bo'lmasa null. */
  counterpart: string | null;
  /** `counterpart` raqammi (kontaktda yo'q). */
  isNumber: boolean;
  /** Nomdagi boshlanish vaqti (epoch ms, telefon mahalliy vaqti); yo'q bo'lsa null. */
  startedAtMs: number | null;
  /** Nom qo'ng'iroq yozuviga o'xshaydimi (prefiks yoki sana-vaqt qolipi topildi). */
  looksLikeCall: boolean;
}

/** Samsung (va boshqa) tillardagi "qo'ng'iroq yozuvi" prefikslari - suhbatdosh nomidan olib tashlanadi. */
const CALL_PREFIXES = [
  'call recording',
  'recorded call',
  'запись вызова',
  'запись звонка',
  'запись разговора',
  "qo'ng'iroq yozuvi",
  'qongiroq yozuvi',
  'anrufaufnahme',
  'call',
];

// Sana-vaqt qoliplari (oxirida). Tartib muhim: 8 xonali yil oldin, aks holda "20241010" ning
// oxirgi 6 raqami "241010" deb o'qilardi.
const DATE_PATTERNS: { re: RegExp; fullYear: boolean }[] = [
  // ..._2024-10-10 14-30-12 | 2024-10-10_14.30.12
  { re: /^(?:(.*?)[\s_-]+)?(\d{4})-(\d{2})-(\d{2})[\s_](\d{2})[-.:](\d{2})[-.:](\d{2})$/, fullYear: true },
  // ..._20241010_143012 | 20241010143012
  { re: /^(?:(.*?)[\s_-]+)?(\d{4})(\d{2})(\d{2})[_\s-]?(\d{2})(\d{2})(\d{2})$/, fullYear: true },
  // ..._241010_143012 (Samsung)
  { re: /^(?:(.*?)[\s_-]+)?(\d{2})(\d{2})(\d{2})[_\s-](\d{2})(\d{2})(\d{2})$/, fullYear: false },
];

const NUMBER_RE = /^\+?[\d\s()-]{3,}$/;

function stripExtension(name: string): string {
  return name.replace(/\.[A-Za-z0-9]{1,5}$/, '');
}

function localTime(y: number, mo: number, d: number, h: number, mi: number, s: number): number | null {
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 59) return null;
  // Telefon mahalliy vaqti: Samsung nomni qurilma soati bilan yozadi.
  const dt = new Date(y, mo - 1, d, h, mi, s);
  // 31-fevral kabi sana keyingi oyga "toshib" o'tadi - bunday nom ishonchsiz.
  if (dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
  return dt.getTime();
}

function stripPrefix(text: string): { rest: string; matched: boolean } {
  const lower = text.toLowerCase();
  for (const p of CALL_PREFIXES) {
    if (lower.startsWith(p)) {
      const rest = text.slice(p.length);
      // "Call" faqat alohida so'z bo'lsa prefiks ("Callum" - ism).
      if (rest && !/^[\s_-]/.test(rest)) continue;
      return { rest: rest.replace(/^[\s_-]+/, ''), matched: true };
    }
  }
  return { rest: text, matched: false };
}

function cleanName(text: string): string {
  return text.replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
}

export function parseCallFileName(displayName: string | null | undefined): ParsedCallName {
  const base = stripExtension((displayName ?? '').trim()).trim();
  let head = base;
  let startedAtMs: number | null = null;
  for (const { re, fullYear } of DATE_PATTERNS) {
    const m = re.exec(base);
    if (!m) continue;
    const [, prefix, a, b, c, h, mi, s] = m;
    const year = fullYear ? Number(a) : 2000 + Number(a);
    const ms = localTime(year, Number(b), Number(c), Number(h), Number(mi), Number(s));
    if (ms == null) continue;
    startedAtMs = ms;
    head = prefix ?? '';
    break;
  }
  const { rest, matched } = stripPrefix(head);
  const name = cleanName(rest);
  const isNumber = !!name && NUMBER_RE.test(name) && (name.match(/\d/g)?.length ?? 0) >= 3;
  return {
    counterpart: name || null,
    isNumber,
    startedAtMs,
    looksLikeCall: matched || startedAtMs != null,
  };
}

/** Serverdagi sarlavha chegarasi (`CreateMeetingRequest.title` max_length). */
export const MAX_TITLE = 120;

/**
 * Navbat qatori / yig'ilish sarlavhasi: "Qo'ng'iroq: Alisher". Qo'ng'iroqqa o'xshamagan
 * ulashilgan fayl - o'z nomi ("Mijoz bilan uchrashuv"), nom yo'q bo'lsa vaqt bilan.
 */
export function importTitle(t: TFn, parsed: ParsedCallName, fallbackTime: string): string {
  let title: string;
  if (parsed.looksLikeCall) {
    title = parsed.counterpart ? t('calls.title', { name: parsed.counterpart }) : t('calls.titleNoName', { time: fallbackTime });
  } else {
    title = parsed.counterpart ?? t('calls.titleNoName', { time: fallbackTime });
  }
  return title.length > MAX_TITLE ? title.slice(0, MAX_TITLE).trimEnd() : title;
}

/** Bir kunlik kelajak chegarasi: undan keyingi "sana" - noto'g'ri soat yoki noto'g'ri o'qilgan nom. */
const FUTURE_SKEW_MS = 24 * 60 * 60 * 1000;

/**
 * Yozuv boshlangan vaqt (ms): avval nomdagi vaqt, keyin fayl vaqti - davomiylik
 * (mtime qo'ng'iroq oxiri), oxirida `now`.
 */
export function recordedAtMs(parsed: ParsedCallName, fileDateMs: number | null, durationMs: number, now: number): number {
  if (parsed.startedAtMs != null && parsed.startedAtMs <= now + FUTURE_SKEW_MS) return parsed.startedAtMs;
  return fileStartMs(fileDateMs, durationMs) ?? now;
}

function fileStartMs(fileDateMs: number | null, durationMs: number): number | null {
  return fileDateMs != null && fileDateMs > 0 ? Math.max(0, fileDateMs - Math.max(0, durationMs)) : null;
}

/**
 * Ro'yxatda ko'rsatish uchun boshlanish vaqti (soatsiz - render toza bo'lsin): nomdagi vaqt,
 * bo'lmasa fayl vaqti - davomiylik; ikkalasi ham yo'q bo'lsa null (sana ko'rsatilmaydi).
 */
export function displayStartMs(parsed: ParsedCallName, fileDateMs: number | null, durationMs: number): number | null {
  return parsed.startedAtMs ?? fileStartMs(fileDateMs, durationMs);
}

/** "2,4 MB" / "850 KB" (uz/ru - o'nli vergul). */
export function formatSize(bytes: number, t: TFn, lang: string): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  if (bytes < 1024 * 1024) return t('calls.sizeKb', { n: Math.max(1, Math.round(bytes / 1024)) });
  const mb = (bytes / (1024 * 1024)).toFixed(1);
  return t('calls.sizeMb', { n: lang === 'en' ? mb : mb.replace('.', ',') });
}

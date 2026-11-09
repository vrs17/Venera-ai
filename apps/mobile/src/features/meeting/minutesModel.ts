/**
 * Bayonnoma (yig'ilish yozuvidan RASMIY hujjat loyihasi) varag'i uchun SOF mantiq: hujjat tili
 * default'i, ro'yxatdan tanlangan tilning holati, server xatosini sababga aylantirish va
 * yozilayotgan hujjatni so'rab turish (polling).
 *
 * Server oqimi Slack va Telegram'dagi «📄 Bayonnoma» bilan bir xil (`apps/api/app/services/
 * meetings/minutes`): hujjat tili + transkript versiyasi bo'yicha takrorlanmaydi, `force` - qayta
 * yozish. NIMA UCHUN alohida fayl: varaq (`MinutesSheet`) faqat chizadi - qoidalar Jest'da
 * native'siz tekshiriladi (ExportSheet'dagi `shareProblem` kabi).
 */
import { ApiError } from '@/api/client';
import type { Lang, MinutesLanguage, MinutesView } from '@/api/types';
import type { TFn, TKey } from '@/i18n';
import { errorText } from '@/ui/errors';

/** Varaqdagi tartib: bank hujjati odatda kirillda - birinchi (tanlov baribir odamniki). */
export const MINUTES_LANGS: readonly MinutesLanguage[] = ['uz-cyrl', 'uz-latn', 'ru', 'en'];

/**
 * Hujjat tili nomi O'Z yozuvida (endonim) - `settings/langNames` dagi sabab bilan i18n'da emas:
 * "Русский"ni rus tilini biladigan odam interfeys tilidan qat'i nazar taniydi, `uz` lug'atida
 * esa kirill harfi bo'lishi mumkin emas (i18n testi).
 */
export const MINUTES_LANG_NAME: Record<MinutesLanguage, string> = {
  'uz-cyrl': "O'zbekcha (kirill)",
  'uz-latn': "O'zbekcha (lotin)",
  ru: 'Русский',
  en: 'English',
};

/** Ulashiladigan format: Word - asosiy (kotib bo'sh joylarni shu faylda to'ldiradi), PDF - nusxa. */
export type MinutesShareFormat = 'docx' | 'pdf';

/**
 * Yig'ilish tili -> hujjat tili. Server qoidasi bilan AYNAN bir xil (`minutes.text.default_lang`):
 * o'zbekcha yig'ilish - kirill (bank hujjati), rus - rus, ingliz - ingliz, noma'lum - kirill.
 */
export function defaultMinutesLang(meetingLanguage: Lang | string | null | undefined): MinutesLanguage {
  if (meetingLanguage === 'ru') return 'ru';
  if (meetingLanguage === 'en') return 'en';
  return 'uz-cyrl';
}

// --- Tanlangan tilning holati ---------------------------------------------------------------------

export interface MinutesSlot {
  /** Shu tilda eng yangi TAYYOR va eskirmagan hujjat - "Ulashish". */
  ready: MinutesView | null;
  /** Hozir yozilayotgan hujjat (eng yangi tayyoridan KEYIN boshlangan) - har 3 s da so'raladi. */
  running: MinutesView | null;
  /** Eng oxirgi urinish xato bilan tugagan (undan keyin hech narsa boshlanmagan). */
  failed: MinutesView | null;
  /** Tayyor hujjat bor, lekin matn keyin tahrirlangan (eskirgan) - yangisini tayyorlash kerak. */
  staleOnly: boolean;
}

function createdMs(v: MinutesView): number {
  const ms = Date.parse(v.createdAt);
  return Number.isFinite(ms) ? ms : 0;
}

/**
 * Ro'yxat -> tanlangan tilning holati. Server tartibi eskidan yangiga, lekin unga tayanmaymiz:
 * yaratilgan vaqt bo'yicha (teng bo'lsa - ro'yxatdagi joyi bo'yicha) eng yangisi birinchi.
 * Tayyoridan ESKI "running" qator (masalan qayta ishga tushgan serverdan qolgan) e'tiborsiz.
 */
export function minutesSlot(items: readonly MinutesView[] | null | undefined, lang: MinutesLanguage): MinutesSlot {
  const mine = (items ?? [])
    .map((v, i) => ({ v, i }))
    .filter(({ v }) => v.language === lang)
    .sort((a, b) => createdMs(b.v) - createdMs(a.v) || b.i - a.i)
    .map(({ v }) => v);
  const readyAt = mine.findIndex((v) => v.status === 'ready' && !v.stale);
  const ready = readyAt >= 0 ? mine[readyAt] : null;
  const newer = readyAt >= 0 ? mine.slice(0, readyAt) : mine;
  const running = newer.find((v) => v.status === 'running') ?? null;
  const latest = mine[0] ?? null;
  return {
    ready,
    running,
    failed: !running && latest?.status === 'failed' ? latest : null,
    staleOnly: !ready && mine.some((v) => v.status === 'ready' && v.stale),
  };
}

/** Ro'yxatdagi qatorni yangilaydi yoki qo'shadi (POST va so'rash javobi). */
export function upsertMinutes(items: readonly MinutesView[] | null, v: MinutesView): MinutesView[] {
  const list = items ?? [];
  return list.some((x) => x.id === v.id) ? list.map((x) => (x.id === v.id ? v : x)) : [...list, v];
}

// --- Izohlar va ogohlantirishlar ------------------------------------------------------------------

const MAX_NOTES = 10;

/**
 * Model izohlari ("Aniqlashtirish kerak") - faqat ko'rsatish uchun. Shartnoma bo'yicha `string[]`,
 * lekin himoyalangan o'qiymiz (eski/yangi server farqi varaqni buzmasin): matn ham, `{text}` ham
 * qabul qilinadi, ko'p qatorli matn qatorlarga bo'linadi, boshidagi "-"/"•" va bo'shlar tashlanadi,
 * takrorsiz, 10 tagacha.
 */
export function minutesNotes(notes: unknown): string[] {
  const raw: unknown[] = typeof notes === 'string' ? notes.split(/\r?\n/) : Array.isArray(notes) ? notes : [];
  const out: string[] = [];
  for (const n of raw) {
    const text =
      typeof n === 'string'
        ? n
        : n && typeof n === 'object' && typeof (n as { text?: unknown }).text === 'string'
          ? (n as { text: string }).text
          : '';
    const clean = text
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/^[-•*]\s*/, '');
    if (clean && !out.includes(clean)) out.push(clean);
    if (out.length >= MAX_NOTES) break;
  }
  return out;
}

/**
 * Odamga tegishli tekshiruv ogohlantirishlari (varaqda faqat SONI). `provider_failed:*` hujjat
 * sifati haqida emas (birinchi model yiqilib, zanjirdagi keyingisi yozgan) - Slack/Telegram ham
 * uni ko'rsatmaydi, shuning uchun sanalmaydi.
 */
export function minutesWarnings(warnings: unknown): string[] {
  if (!Array.isArray(warnings)) return [];
  return warnings.filter((w): w is string => typeof w === 'string' && w.trim() !== '' && !w.startsWith('provider_failed:'));
}

/** Xato bilan tugagan qator kodi -> matn (server `minutes._failed` kodlari). */
const FAILED_TEXT: Record<string, TKey> = {
  llm_failed: 'minutes.writeFailed',
  llm_busy: 'minutes.busy',
  llm_rate_limited: 'minutes.modelLimited',
  llm_not_configured: 'minutes.notConfigured',
  internal: 'minutes.internal',
  // Yozish yiqilgan yoki tashlab ketilgan (server ~45 daqiqadan keyin belgilaydi).
  interrupted: 'minutes.interrupted',
};

/**
 * Xato bilan tugagan qator -> qisqa matn FAQAT `error.code` bo'yicha. NIMA UCHUN `message` emas:
 * model xatolarida u texnik sabab ("bayonnoma: javob kesildi (max tokens)", "429") - odamga
 * tushunarsiz va faqat o'zbekcha. Noma'lum kod - umumiy "yozilmadi".
 */
export function failedText(t: TFn, v: Pick<MinutesView, 'error'>): string {
  const key = FAILED_TEXT[v.error?.code ?? ''];
  return key ? t(key) : t('minutes.failedNoReason');
}

// --- Xatoni sababga aylantirish ------------------------------------------------------------------

/** Qaysi so'rov yiqildi: ro'yxat, tayyorlash (POST), holatni so'rash yoki faylni yuklash. */
export type MinutesStage = 'list' | 'create' | 'poll' | 'export';

export type MinutesProblem =
  | { kind: 'offline' }
  | { kind: 'stalled' }
  /** 429 `rate_limited` - soatlik bayonnoma chegarasi (`Retry-After` soniyada). */
  | { kind: 'rateLimited'; retryAfterSec: number | null }
  /** Model band (503 `llm_busy`, 429 `llm_rate_limited`). */
  | { kind: 'busy' }
  /** Fayl chizilmoqda: 429 - shu odamning oldingi fayli, 503 - server navbati to'la (`export_busy`). */
  | { kind: 'exportBusy'; server: boolean }
  /** Eksportda 409: hujjat hali tayyor emas - holatini qayta tekshirish kerak. */
  | { kind: 'docNotReady' }
  | { kind: 'transcriptEmpty' }
  | { kind: 'transcriptNotReady' }
  | { kind: 'notConfigured' }
  /** Model hujjatni yozolmadi (502 `llm_failed`). */
  | { kind: 'writeFailed' }
  | { kind: 'pdfUnavailable' }
  | { kind: 'docxUnavailable' }
  /** Aniq bir hujjat yo'q (404 `minutes_not_found` yoki uning so'rovida 404) - ro'yxat yangilanadi. */
  | { kind: 'gone' }
  /**
   * Ro'yxat yoki tayyorlashda 404: yig'ilish ochilgan (u bor), demak serverda bayonnoma yo'llari
   * hali yo'q - eski backend. Qayta urinish befoyda: server yangilangach ishlaydi.
   */
  | { kind: 'notOnServer' }
  | { kind: 'cannotShare' }
  /** Qayta urinish yordam bermaydi (401/403/410): faqat sababi. */
  | { kind: 'final'; err: unknown }
  | { kind: 'error'; err: unknown };

/** Server javobi (`ApiError.status`/`code`) -> varaqda nima deyish. */
export function minutesProblem(err: unknown, stage: MinutesStage): MinutesProblem {
  if (!(err instanceof ApiError)) return { kind: 'error', err };
  if (err.status === 0) return err.code === 'stalled' ? { kind: 'stalled' } : { kind: 'offline' };
  // `export_busy` 429 bilan ham keladi (shu odam allaqachon fayl olmoqda) - soatlik chegara emas.
  if (err.code === 'export_busy') return { kind: 'exportBusy', server: err.status !== 429 };
  if (err.status === 429) return err.code === 'rate_limited' ? { kind: 'rateLimited', retryAfterSec: err.retryAfterSec } : { kind: 'busy' };
  if (err.code === 'transcript_empty') return { kind: 'transcriptEmpty' };
  // Eksportda 409 - hujjat (hali) tayyor emas; ro'yxat/tayyorlash/so'rashda - transkript tayyor emas.
  if (err.status === 409) return stage === 'export' ? { kind: 'docNotReady' } : { kind: 'transcriptNotReady' };
  if (err.code === 'llm_not_configured') return { kind: 'notConfigured' };
  if (err.code === 'llm_busy') return { kind: 'busy' };
  if (err.code === 'llm_failed') return { kind: 'writeFailed' };
  if (err.code === 'pdf_unavailable') return { kind: 'pdfUnavailable' };
  if (err.code === 'docx_unavailable') return { kind: 'docxUnavailable' };
  if (err.code === 'minutes_not_found') return { kind: 'gone' };
  // Varaq faqat yuklangan yig'ilishdan ochiladi: ro'yxat/POST dagi 404 - yo'l yo'q (eski server);
  // aniq hujjatni so'rash yoki yuklashdagi 404 - o'sha hujjat yo'q.
  if (err.status === 404) return stage === 'list' || stage === 'create' ? { kind: 'notOnServer' } : { kind: 'gone' };
  if (err.status === 401 || err.status === 403 || err.status === 410) return { kind: 'final', err };
  return { kind: 'error', err };
}

/** `Retry-After` -> "5 daqiqa" / "40 soniya"; noma'lum yoki 0 - null (umumiy "keyinroq"). */
export function retryWaitText(t: TFn, sec: number | null | undefined): string | null {
  if (sec == null || !Number.isFinite(sec) || sec <= 0) return null;
  return sec < 60 ? t('minutes.waitSec', { n: Math.ceil(sec) }) : t('minutes.waitMin', { n: Math.ceil(sec / 60) });
}

export function minutesProblemText(t: TFn, p: MinutesProblem): string {
  switch (p.kind) {
    case 'offline':
      return t('minutes.offline');
    case 'stalled':
      return t('share.stalled');
    case 'rateLimited': {
      const wait = retryWaitText(t, p.retryAfterSec);
      return wait ? t('minutes.rateLimitedIn', { wait }) : t('minutes.rateLimited');
    }
    case 'busy':
      return t('minutes.busy');
    case 'exportBusy':
      return p.server ? t('share.serverBusy') : t('share.busy');
    case 'docNotReady':
      return t('minutes.docNotReady');
    case 'transcriptEmpty':
      return t('minutes.transcriptEmpty');
    case 'transcriptNotReady':
      return t('minutes.transcriptNotReady');
    case 'notConfigured':
      return t('minutes.notConfigured');
    case 'writeFailed':
      return t('minutes.writeFailed');
    case 'pdfUnavailable':
      return t('share.pdfUnavailable');
    case 'docxUnavailable':
      return t('share.docxUnavailable');
    case 'gone':
      return t('minutes.gone');
    case 'notOnServer':
      return t('minutes.notOnServer');
    case 'cannotShare':
      return t('share.unavailable');
    default:
      return errorText(t, p.err);
  }
}

/**
 * Xatodan keyin taklif qilinadigan BITTA keyingi qadam (yoki yo'q - qayta urinish befoyda):
 * xuddi shu so'rovni qaytarish, boshqa formatda ulashish yoki holatni qayta tekshirish (ro'yxat).
 */
export type MinutesNextStep = 'retry' | 'useDocx' | 'usePdf' | 'recheck';

export function minutesProblemAction(p: MinutesProblem | null): MinutesNextStep | null {
  if (!p) return null;
  switch (p.kind) {
    case 'offline':
    case 'stalled':
    case 'busy':
    case 'exportBusy':
    case 'writeFailed':
    case 'error':
      return 'retry';
    case 'pdfUnavailable':
      return 'useDocx';
    case 'docxUnavailable':
      return 'usePdf';
    case 'docNotReady':
      return 'recheck';
    default:
      return null;
  }
}

// --- Holatni so'rab turish -----------------------------------------------------------------------

/** Yozilayotgan hujjat shuncha vaqtda bir so'raladi. */
export const MINUTES_POLL_MS = 3000;
/** Shundan keyin so'rash to'xtaydi (server ishi davom etadi) - "odatdagidan uzoq, keyinroq qarang". */
export const MINUTES_POLL_LIMIT_MS = 10 * 60 * 1000;

export interface MinutesPollCallbacks {
  /** Har muvaffaqiyatli javob (hali yozilayotgan bo'lsa ham) - ro'yxatdagi qator yangilanadi. */
  onUpdate(v: MinutesView): void;
  /** O'tkinchi xato (internet, 5xx, 429): so'rash davom etadi. */
  onTransient(err: unknown): void;
  /** Davom etib bo'lmaydigan xato (404, 403, 401 ...): so'rash to'xtaydi. */
  onFatal(err: unknown): void;
  /** Muddat tugadi, hujjat hali yozilmoqda: so'rash to'xtaydi. */
  onTimeout(): void;
}

/** Internet, server (5xx) yoki chegara (429) - keyingi so'rashda o'tib ketishi mumkin. */
export function isTransientMinutesError(err: unknown): boolean {
  if (!(err instanceof ApiError)) return true;
  return err.status === 0 || err.status === 429 || err.status >= 500;
}

/**
 * `get` har `intervalMs` da chaqiriladi - holat `running` dan chiqquncha, davom etib bo'lmaydigan
 * xatogacha yoki `limitMs` tugaguncha. Birinchi so'rov ham `intervalMs` dan keyin (ro'yxat yoki
 * POST javobi hozirgina keldi). Qaytgan funksiya to'xtatadi (varaq yopildi, til almashdi) - undan
 * keyin kelgan javob hech narsani o'zgartirmaydi.
 */
export function pollMinutes(
  get: () => Promise<MinutesView>,
  cb: MinutesPollCallbacks,
  o: { intervalMs?: number; limitMs?: number; now?: () => number } = {},
): () => void {
  const interval = o.intervalMs ?? MINUTES_POLL_MS;
  const limit = o.limitMs ?? MINUTES_POLL_LIMIT_MS;
  const now = o.now ?? Date.now;
  const started = now();
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const tick = async () => {
    timer = null;
    if (stopped) return;
    try {
      const v = await get();
      if (stopped) return;
      cb.onUpdate(v);
      if (v.status !== 'running') {
        stopped = true;
        return;
      }
    } catch (e) {
      if (stopped) return;
      if (!isTransientMinutesError(e)) {
        stopped = true;
        cb.onFatal(e);
        return;
      }
      cb.onTransient(e);
    }
    if (now() - started >= limit) {
      stopped = true;
      cb.onTimeout();
      return;
    }
    timer = setTimeout(() => void tick(), interval);
  };
  timer = setTimeout(() => void tick(), interval);
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}

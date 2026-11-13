/**
 * Bayonnoma (yig'ilish yozuvidan RASMIY hujjat loyihasi) varag'i uchun SOF mantiq: hujjat tili
 * default'i, ro'yxatdan tanlangan tilning holati, server xatosini sababga aylantirish va
 * yozilayotgan hujjatni so'rab turish (polling).
 *
 * Server oqimi Slack va Telegram'dagi «📄 Bayonnoma» bilan bir xil (`apps/api/app/services/
 * meetings/minutes`): hujjat tili + transkript versiyasi bo'yicha takrorlanmaydi, `force` - qayta
 * yozish. NIMA UCHUN alohida fayl: varaq (`MinutesSheet`) faqat chizadi - qoidalar Jest'da
 * native'siz tekshiriladi (ExportSheet'dagi `shareProblem` kabi).
 *
 * Chatdagi bayonnoma (ega so'rovi, 2026-11-12): ko'rsatma va o'zgartirish so'rovlari yozuv chatida
 * yoziladi; har tahrir - yangi versiya (yangi qator). Shu yerda: chatdagi karta holati
 * (`minutesCardState`), "nima o'zgardi" matni (`changesText`), sarlavha qatorlari va karta so'rovi.
 */
import { ApiError } from '@/api/client';
import type { ChatMinutesRef, Lang, MinutesChanges, MinutesChangeSet, MinutesHeader, MinutesLanguage, MinutesView } from '@/api/types';
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

function finishedMs(v: MinutesView): number {
  const ms = v.finishedAt ? Date.parse(v.finishedAt) : Number.NaN;
  return Number.isFinite(ms) ? ms : createdMs(v);
}

/**
 * Joriy tayyor hujjat - serverdagi bilan BIR XIL qoida (`rows.newest_ready`): zanjir uchi (boshqa tayyor hujjatning
 * ota-versiyasi emas), ulardan eng keyin tayyor bo'lgani. Navbatdagi tahrirlar tartibsiz bajarilsa (oldin so'ralgani
 * keyingisining ustiga yoziladi) yaratilish tartibi noto'g'ri hujjatni ko'rsatardi. `mine` - eng yangi yaratilgani
 * birinchi: teng vaqtda o'sha (yangirog'i) qoladi.
 */
function currentReady(mine: readonly MinutesView[]): MinutesView | null {
  const ready = mine.filter((v) => v.status === 'ready' && !v.stale);
  const parents = new Set(ready.map((v) => v.parentId).filter((id): id is string => !!id));
  const tips = ready.filter((v) => !parents.has(v.id));
  return (tips.length ? tips : ready).reduce<MinutesView | null>(
    (best, v) => (best === null || finishedMs(v) > finishedMs(best) ? v : best),
    null,
  );
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
  const ready = currentReady(mine);
  const readyAt = ready ? mine.indexOf(ready) : -1;
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
 * Soniga qo'shilmaydigan ogohlantirishlar. `provider_failed:*` hujjat sifati haqida emas (birinchi
 * model yiqilib, zanjirdagi keyingisi yozgan) - Slack/Telegram ham uni ko'rsatmaydi. Qolgan ikkitasi
 * varaqda O'Z qatori bilan chiqadi (`warningNumber`): matn tahrirlangani uchun hujjat yangidan
 * yozilib avvalgi tahrirlar tushib qoldi; ko'rsatmalar juda ko'p - eng eskilari hisobga olinmadi.
 */
const UNCOUNTED_WARNINGS = ['provider_failed:', 'superseded_revisions:', 'guidance_truncated:'];

/** Odamga tegishli tekshiruv ogohlantirishlari (varaqda faqat SONI). */
export function minutesWarnings(warnings: unknown): string[] {
  if (!Array.isArray(warnings)) return [];
  return warnings.filter(
    (w): w is string => typeof w === 'string' && w.trim() !== '' && !UNCOUNTED_WARNINGS.some((p) => w.startsWith(p)),
  );
}

/** `<prefix>:<n>` ogohlantirishidagi son (`superseded_revisions:2` -> 2); yo'q yoki buzuq - null. */
export function warningNumber(warnings: unknown, prefix: 'superseded_revisions' | 'guidance_truncated'): number | null {
  if (!Array.isArray(warnings)) return null;
  const head = `${prefix}:`;
  const found = warnings.find((w): w is string => typeof w === 'string' && w.startsWith(head));
  const n = found ? Number(found.slice(head.length)) : NaN;
  return Number.isInteger(n) && n > 0 ? n : null;
}

/** Xato bilan tugagan qator kodi -> matn (server `minutes.FAILURES` kodlari). */
const FAILED_TEXT: Record<string, TKey> = {
  llm_failed: 'minutes.writeFailed',
  llm_busy: 'minutes.busy',
  llm_rate_limited: 'minutes.modelLimited',
  llm_not_configured: 'minutes.notConfigured',
  internal: 'minutes.internal',
  // Yozish yiqilgan yoki tashlab ketilgan (server ~45 daqiqadan keyin belgilaydi).
  interrupted: 'minutes.interrupted',
  // Tahrir: model hech narsani o'zgartirmadi (yangi versiya yo'q), yozuv qayta o'girilgan (eski hujjatni
  // tahrirlab bo'lmaydi), shu tilda tayyor hujjat yo'q, oldingi tahrirlar navbati to'la.
  no_change: 'minutes.noChange',
  minutes_outdated: 'minutes.outdated',
  minutes_missing: 'minutes.missing',
  minutes_busy: 'minutes.editBusy',
};

/**
 * Xato bilan tugagan qator -> qisqa matn FAQAT `error.code` bo'yicha. NIMA UCHUN `message` emas:
 * model xatolarida u texnik sabab ("bayonnoma: javob kesildi (max tokens)", "429") - odamga
 * tushunarsiz va faqat o'zbekcha. Noma'lum kod - umumiy "yozilmadi". Tahrir (`kind: 'revise'`)
 * yozilmasa - "tahrirlay olmadi" (server ham shunday deydi).
 */
export function failedText(t: TFn, v: Pick<MinutesView, 'error' | 'kind'>): string {
  const code = v.error?.code ?? '';
  if (code === 'llm_failed' && v.kind === 'revise') return t('minutes.reviseFailed');
  const key = FAILED_TEXT[code];
  return key ? t(key) : t('minutes.failedNoReason');
}

/** Ish umuman boshlanmaganda (chat so'rovi rad etildi) - qator xatolaridan tashqari kodlar. */
const NOT_STARTED_TEXT: Record<string, TKey> = {
  transcript_empty: 'minutes.transcriptEmpty',
  not_ready: 'minutes.transcriptNotReady',
};

/**
 * Chatdagi so'rov bayonnoma ishini boshlay olmadi (`ChatMinutesRef.error`, `id` yo'q) -> "Bayonnoma ishi
 * boshlanmadi: <sabab>". Sabab kod bo'yicha: soatlik chegara (tahrirda - tahrir chegarasi), navbat to'la,
 * eski yoki yo'q hujjat, transkript; noma'lum kod - umumiy `err.<code>` matni.
 */
export function notStartedText(t: TFn, code: string, revise: boolean): string {
  const key =
    code === 'rate_limited' ? (revise ? 'minutes.editRateLimited' : 'minutes.rateLimited') : (FAILED_TEXT[code] ?? NOT_STARTED_TEXT[code]);
  return t('mchat.minutes.notStarted', { reason: key ? t(key) : errorText(t, code) });
}

// --- Tahrir: nima o'zgardi, sarlavha -------------------------------------------------------------

/** Raqamlar (musbat butun, takrorsiz, o'sish tartibida) - buzuq qiymat varaqni buzmasin. */
function numbers(v: unknown): number[] {
  if (!Array.isArray(v)) return [];
  return [...new Set(v.filter((n): n is number => Number.isInteger(n) && n > 0))].sort((a, b) => a - b);
}

function changeSet(v: unknown): MinutesChangeSet {
  const o = v && typeof v === 'object' ? (v as Partial<Record<keyof MinutesChangeSet, unknown>>) : {};
  return { changed: numbers(o.changed), added: numbers(o.added), removed: numbers(o.removed) };
}

function filledStrings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x.trim() !== '').map((x) => x.trim()) : [];
}

/**
 * Tahrirning ota-versiyaga nisbatan o'zgarishlari -> bitta qator: "O'zgarishlar: 3, 7-bandlar;
 * qo'shildi: 8; olib tashlandi: 1 ta; kun tartibi; sarlavha qismi". Raqamlar Word'dagidek. Hech narsa
 * o'zgarmagan tayyor tahrir (ko'rsatmalar allaqachon aks etgan) - "matn o'zgarmadi". Asl hujjat
 * (`changes` yo'q) - null.
 */
export function changesText(t: TFn, changes: MinutesChanges | null | undefined): string | null {
  if (!changes || typeof changes !== 'object') return null;
  const items = changeSet(changes.items);
  const agenda = changeSet(changes.agenda);
  const parts: string[] = [];
  if (items.changed.length) {
    parts.push(t(items.changed.length === 1 ? 'minutes.changes.item' : 'minutes.changes.items', { list: items.changed.join(', ') }));
  }
  if (items.added.length) parts.push(t('minutes.changes.added', { list: items.added.join(', ') }));
  if (items.removed.length) parts.push(t('minutes.changes.removed', { n: items.removed.length }));
  if (agenda.changed.length || agenda.added.length || agenda.removed.length) parts.push(t('minutes.changes.agenda'));
  if (filledStrings(changes.header).length) parts.push(t('minutes.changes.header'));
  if (filledStrings(changes.other).length) parts.push(t('minutes.changes.other'));
  return t('minutes.changes', { list: parts.length ? parts.join('; ') : t('minutes.changes.none') });
}

export interface MinutesHeaderInfo {
  chair: string | null;
  attendees: string[];
  /** Biror sarlavha qiymati to'ldirilgan - "qolgan «________» joylari" deyiladi. */
  filled: boolean;
}

/** Sarlavha (egasi aytgan faktlar) -> varaqdagi rais va qatnashchilar qatorlari; himoyalangan o'qiladi. */
export function minutesHeaderInfo(header: MinutesHeader | null | undefined): MinutesHeaderInfo {
  const h = header && typeof header === 'object' ? header : null;
  const text = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : null);
  const chair = text(h?.chair);
  const attendees = filledStrings(h?.attendees);
  const filled = [h?.organization, h?.chairedBy, h?.city].some((v) => text(v) != null) || chair != null || attendees.length > 0;
  return { chair, attendees, filled };
}

// --- Chatdagi bayonnoma kartasi --------------------------------------------------------------------

/** Chat navbati ostidagi bayonnoma kartasi (`MinutesActionCard`) nima ko'rsatadi. */
export type MinutesCardState =
  | { kind: 'note'; n: number }
  /** Ish boshlanmadi (chegara, navbat, eski hujjat...) - sababi kod bo'yicha. */
  | { kind: 'notStarted'; code: string; revise: boolean }
  /** `slow` - qator yaratilganiga 10 daqiqa bo'ldi, karta so'rashni to'xtatdi (natija varaqda chiqadi). */
  | { kind: 'running'; revise: boolean; slow: boolean }
  | { kind: 'ready'; version: number; language: MinutesLanguage | null }
  | { kind: 'failed'; code: string; revise: boolean }
  /** Qator serverda yo'q (404 yoki tarixda holatsiz havola). */
  | { kind: 'gone' };

/** Kartaning o'z so'rovi (`useMinutesDoc`): javob, xato va oxirgi javob vaqti (`dataUpdatedAt`, ms). */
export interface MinutesDocState {
  view?: MinutesView | null;
  error?: unknown;
  at?: number;
}

/** Qator yaratilganiga `MINUTES_POLL_LIMIT_MS` bo'ldi (`at` - oxirgi javob vaqti, telefon soati). */
function pastPollLimit(v: MinutesView, at: number): boolean {
  return at - createdMs(v) >= MINUTES_POLL_LIMIT_MS;
}

/**
 * Navbatdagi havola (`ChatTurn.minutes`, tarix o'qilgan paytdagi) + kartaning so'rovi -> karta holati.
 * Yozilayotgan havolada so'rov javobi ustun: tarix qayta o'qilmasa ham "tayyorlanmoqda" -> "tayyor".
 * Tarix yakunni (tayyor/xato) bilsa - havola ustun: qator ortga qaytmaydi, keshdagi eski "yozilmoqda"
 * javobi (so'rash endi o'chiq) uni bosmasin. Ko'rsatmalar tahriri ham (2-versiyadan) "yangi versiya".
 * Karta yo'q - null.
 */
export function minutesCardState(ref: ChatMinutesRef | null | undefined, doc: MinutesDocState = {}): MinutesCardState | null {
  if (!ref) return null;
  if (ref.action === 'note') return { kind: 'note', n: Math.max(1, ref.notes ?? 1) };
  const live = ref.status !== 'ready' && ref.status !== 'failed';
  const v = live ? (doc.view ?? null) : null;
  const revise = ref.action === 'revise' || v?.kind === 'revise' || (v?.version ?? ref.version ?? 1) >= 2;
  if (!ref.id) return ref.error ? { kind: 'notStarted', code: ref.error.code, revise } : null;
  if (live && doc.error != null && minutesProblem(doc.error, 'poll').kind === 'gone') return { kind: 'gone' };
  const status = v?.status ?? ref.status;
  if (status === 'ready') return { kind: 'ready', version: Math.max(1, v?.version ?? ref.version ?? 1), language: v?.language ?? ref.language };
  if (status === 'failed') return { kind: 'failed', code: (v ? v.error : ref.error)?.code ?? '', revise };
  if (status === 'running') return { kind: 'running', revise, slow: v != null && doc.at != null && pastPollLimit(v, doc.at) };
  return { kind: 'gone' };
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
  /** 409 `minutes_busy`: shu tilda oldingi tahrirlar hali yozilmoqda (navbat to'la) - holatni qayta tekshirish. */
  | { kind: 'editBusy' }
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
  // «Qo'llash» (yangi ko'rsatmalar - tahrir) navbatga sig'madi: transkript emas, oldingi tahrirlar sababi.
  if (err.code === 'minutes_busy') return { kind: 'editBusy' };
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
    case 'editBusy':
      return t('minutes.editBusy');
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
    case 'editBusy':
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
 * Chatdagi karta so'rayotgan qatorning keyingi so'rovi (ms) yoki `false` - to'xtash: tayyor/xato bo'ldi,
 * davom etib bo'lmaydigan xato (404 `gone`, 403...) yoki qator yaratilganiga `MINUTES_POLL_LIMIT_MS`
 * bo'ldi (server ishi davom etadi - natija varaqda chiqadi). Javob hali yo'q yoki o'tkinchi xato
 * (internet, 5xx) - har `MINUTES_POLL_MS` da. `at` - oxirgi javob vaqti (`dataUpdatedAt`).
 */
export function minutesDocPollMs(v: MinutesView | null | undefined, err: unknown, at: number): number | false {
  if (err != null && !isTransientMinutesError(err)) return false;
  if (!v) return MINUTES_POLL_MS;
  return v.status === 'running' && !pastPollLimit(v, at) ? MINUTES_POLL_MS : false;
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

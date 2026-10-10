/**
 * Gap navbati: javob markdown'i (oqimda o'sib boradi) -> TTS bo'laklari (tozalangan).
 *
 * NIMA UCHUN bo'laklash SHART (web'da emas): expo-audio faqat to'liq faylni o'ynatadi.
 * `/tts/clip` javobi sintez TUGAGANDAN keyin keladi, shuning uchun birinchi ovoz = birinchi
 * bo'lakning to'liq sintezi. Keyingi bo'laklar oldingisi yangrayotganda tayyorlanadi.
 *
 * O'LCHOV (prod, 2026-10-10, jonli suhbat): ovoz ~78 ms/belgi; TTS serveri matnni ~2.3-3.1 s
 * ovozli bo'laklarga bo'lib KETMA-KET sintez qiladi, har biri ~1.1 s. Ya'ni sintez real
 * vaqtdan atigi ~2.2x tez (eski izohdagi "4.7x" NOTO'G'RI edi):
 *   44 belgi -> 1.19 s, 60 -> 2.24 s, 88 -> 2.28 s, 164 -> 6.50 s, 254 -> 9.74 s, 334 -> 10.04 s.
 *
 * Birinchi bo'lak (`FIRST_*`): <=60 belgi (TTS'ning ~2 bo'lagi, ~2.2 s). Uzunroq gap avval
 * ibora chegarasida (vergul, `:` ...) bo'linadi; chegara bo'lmasa 100 belgigacha gap BUTUN
 * olinadi - so'z o'rtasidan kesilgan ovoz buzuq eshitiladi, 1 ta qo'shimcha TTS bo'lagi (~1.1 s)
 * arzonroq. Juda qisqa ochilish ("Albatta!") keyingi gap bilan qo'shiladi: 8 belgilik birinchi
 * bo'lak 0.6 s yangraydi, ikkinchisini esa bu vaqtda sintez qilib bo'lmaydi - jimlik qolardi.
 * Kutish ikki tomondan chegaralangan: oqayotgan matn FIRST_MAX dan oshsa yoki oqim 0.5 s
 * o'smasa (`openerWait` / `releaseOpener`, taymer `speaker.ts` da) ochilish yolg'iz aytiladi.
 *
 * Bo'lak o'sishi: har keyingi bo'lak oldingisidan ko'pi bilan 1.5 baravar uzun (kamida 60).
 * NIMA UCHUN 1.5 (2 emas): keyingi bo'lak sintezi (~35 ms/belgi + bo'lak yaxlitlash ~1.1 s)
 * oldingisi yangrab bo'lguncha (78 ms/belgi) tugashi kerak. 2x da zaxira ~10%, GPU boshqa odam
 * bilan bo'lingan (1.3x sekin) paytda gaplar orasida 1.5-2.5 s jimlik qolardi; 1.5x da ~0.1 s.
 * Bo'lish qisqa dum qoldirsa (< CLAUSE_MIN) gap butun olinadi: 28 belgilik dum 2.2 s yangraydi,
 * undan keyingi bo'lak esa bu vaqtda tayyor bo'lmaydi.
 *
 * Tortish modeli: `push(to'liq matn, done)` istalgancha chaqiriladi (har token), `take()`
 * keyingi tayyor bo'lakni beradi yoki null (hali to'liq gap yo'q). Yuqori oqim haqiqiy
 * token oqimini bersa gaplar kelishi bilan o'qiladi; bir yo'la bersa ham xuddi shu yo'l.
 */
import { cleanForSpeech, isLowerLetter, TRAIL_LINE } from './speechText';

export const CHUNK = {
  FIRST_MAX: 60,
  FIRST_MIN: 40,
  FIRST_SOFT_MAX: 100,
  MAX: 350,
  CLAUSE_MIN: 40,
  TOTAL_LIMIT: 3000,
  GROW: 1.5,
  GROW_MIN: 60,
} as const;

export interface ChunkLimits {
  /** Birinchi bo'lak maqsadi: shundan uzun gap ibora chegarasida bo'linadi. */
  FIRST_MAX: number;
  /** Birinchi bo'lak shundan qisqa bo'lsa keyingi gap(lar) bilan qo'shiladi (FIRST_MAX gacha). */
  FIRST_MIN?: number;
  /** Ibora chegarasi topilmasa birinchi gap shu uzunlikkacha BUTUN olinadi. */
  FIRST_SOFT_MAX?: number;
  MAX: number;
  CLAUSE_MIN: number;
  TOTAL_LIMIT: number;
  /** Keyingi bo'lak oldingisidan ko'pi bilan shuncha baravar uzun. */
  GROW?: number;
  /** ...lekin bundan qisqa chegaralanmaydi (juda qisqa bo'laklar har biri ~1.1 s kutish qo'shadi). */
  GROW_MIN?: number;
}

export interface SentenceQueue {
  /** Hozirgacha kelgan TO'LIQ javob; bir xil matn bilan qayta chaqirish - zararsiz. */
  push(markdown: string, done: boolean): void;
  /** Keyingi TTS bo'lagi (tozalangan) yoki null - hali tayyor emas. */
  take(): string | null;
  /** done va hammasi berib bo'lingan (yoki iz/limit sababli to'xtagan). */
  readonly finished: boolean;
  /** TOTAL_LIMIT ga yetdi - qolgani ekranda. */
  readonly shortened: boolean;
  /** Berilgan bo'laklar soni. */
  readonly taken: number;
  /**
   * Avval aytib bo'lingan qismni o'tkazib yuborish - pauzadan keyin javobni to'xtagan
   * joyidan davom ettirish uchun. `chars` = aytilgan har bo'lak uchun `uzunlik + 1`
   * (bo'lak ichidagi gaplar bitta bo'shliq bilan qo'shilgan). Yarim aytilgan gap boshidan
   * qayta o'qiladi.
   */
  skip(chars: number): void;
  /**
   * `take()` qisqa ochilish ("Albatta!") uchun keyingi gapni kutib null qaytargan bo'lsa -
   * o'sha paytdagi matn uzunligi (o'sish belgisi), aks holda null. Gap navbati shu bilan
   * kutishni VAQT bo'yicha ham chegaralaydi (`speaker.ts`, OPENER_WAIT_MS).
   */
  readonly openerWait: number | null;
  /** Ochilishni kutmasdan aytish (oqim to'xtab qoldi). Shu javob uchun qaytmaydi. */
  releaseOpener(): void;
}

const ENDERS = '.!?…';
const CLOSERS = '"\'»”)]';
/** Nuqtadan oldingi so'z shulardan biri bo'lsa - gap tugamagan ("va h.k. bo'yicha"). */
const ABBREV = new Set([
  'h.k', 't.b', 'mln', 'mlrd', 'sh', 'tel',
  'т.е', 'т.д', 'т.п', 'г', 'гг', 'млн', 'млрд', 'руб',
  'e.g', 'i.e', 'etc', 'vs', 'mr', 'dr',
]);
/** Hali yozilayotgan qator iz markeri bo'lib chiqishi mumkinmi (`[`, `[T`, `[T1`, `[T1]`). */
const TRAIL_PREFIX = /^\s*(?:\[[A-Za-z]{0,4}[_-]?\d{0,6}\]?)?$/;

function isSpace(ch: string | undefined): boolean {
  return ch === ' ' || ch === '\t' || ch === ' ';
}

function isWordChar(ch: string): boolean {
  return ch === '.' || /[0-9A-Za-zÀ-ɏʰ-˿Ѐ-ӿ']/.test(ch);
}

/** `j` - tugatuvchi belgilar boshlanishi; undan oldingi so'z gap chegarasini bekor qiladimi. */
function blocksBoundary(raw: string, j: number): boolean {
  if (raw[j] !== '.') return false;
  let s = j;
  while (s > 0 && isWordChar(raw[s - 1])) s--;
  const word = raw.slice(s, j);
  if (!word) return false;
  // Ism bosh harfi: "A. Karimov".
  if (word.length === 1 && word.toUpperCase() === word && word.toLowerCase() !== word) return true;
  // Qator boshidagi raqam - ro'yxat belgisi ("1. Birinchi").
  if (/^\d{1,3}$/.test(word)) {
    let b = s;
    while (b > 0 && isSpace(raw[b - 1])) b--;
    if (b === 0 || raw[b - 1] === '\n') return true;
  }
  return ABBREV.has(word.toLowerCase());
}

/**
 * `i` dan boshlangan gap qayerda tugaydi (eksklyuziv indeks), yoki -1 - oqimda hali aniq emas.
 * Kod bloki, inline kod va havola ichida chegara qidirilmaydi.
 */
export function nextBoundary(raw: string, i: number, done: boolean): number {
  let j = i;
  // Qator oxiri bir marta topiladi (har belgida qidirish uzun qatorda O(n^2) bo'lardi);
  // faqat kod bloki qatorlardan sakrab o'tganda qayta hisoblanadi.
  let nl = raw.indexOf('\n', j);
  while (j < raw.length) {
    const ch = raw[j];
    if (ch === '\n') return j;
    if (raw.startsWith('```', j)) {
      const close = raw.indexOf('```', j + 3);
      if (close < 0) return done ? raw.length : -1;
      j = close + 3;
      if (nl >= 0 && nl < j) nl = raw.indexOf('\n', j);
      continue;
    }
    const lineDone = nl >= 0 || done;
    if (ch === '`') {
      const close = raw.indexOf('`', j + 1);
      if (close < 0 || (nl >= 0 && close > nl)) {
        if (!lineDone) return -1;
        j++;
        continue;
      }
      j = close + 1;
      continue;
    }
    if (ch === '[') {
      const close = raw.indexOf(']', j + 1);
      if (close < 0 || (nl >= 0 && close > nl)) {
        if (!lineDone) return -1;
        j++;
        continue;
      }
      if (close + 1 >= raw.length && !done) return -1;
      if (raw[close + 1] === '(') {
        const paren = raw.indexOf(')', close + 2);
        if (paren < 0 || (nl >= 0 && paren > nl)) {
          if (!lineDone) return -1;
          j = close + 1;
          continue;
        }
        j = paren + 1;
        continue;
      }
      j = close + 1;
      continue;
    }
    if (ENDERS.includes(ch)) {
      let k = j;
      while (k < raw.length && ENDERS.includes(raw[k])) k++;
      while (k < raw.length && CLOSERS.includes(raw[k])) k++;
      if (k >= raw.length) return done ? k : -1;
      if (raw[k] === '\n') return k;
      if (!isSpace(raw[k])) {
        // "3.5", "25.06.2026" - nuqtadan keyin bo'shliq yo'q, chegara emas.
        j = k;
        continue;
      }
      let m = k;
      while (m < raw.length && isSpace(raw[m])) m++;
      if (m >= raw.length) {
        if (!done) return -1;
        return k;
      }
      if (raw[m] === '\n') return k;
      if (isLowerLetter(raw[m]) || blocksBoundary(raw, j)) {
        j = k;
        continue;
      }
      return k;
    }
    j++;
  }
  return done ? raw.length : -1;
}

/** `s` ichidagi ibora chegarasi (`,;:` yoki " - "), `max` dan oldin va `clauseMin` dan keyin - eng oxirgisi. */
function clauseCut(s: string, max: number, clauseMin: number): { cut: number; dash: boolean } | null {
  for (let i = Math.min(max, s.length) - 1; i >= clauseMin - 1 && i > 0; i--) {
    if (',;:'.includes(s[i]) && s[i + 1] === ' ') return { cut: i + 1, dash: false };
    if (i >= clauseMin && s.startsWith(' - ', i)) return { cut: i, dash: true };
  }
  return null;
}

function cutAt(s: string, cut: number, dash: boolean): [string, string] {
  const head = s.slice(0, cut).trim();
  let rest = s.slice(cut).trim();
  if (dash) rest = rest.replace(/^-\s+/, '');
  return [head, rest];
}

/** Uzun gapni bo'lish: avval vergul/nuqtali vergul/ikki nuqta yoki " - " da, bo'lmasa bo'shliqda. */
export function splitAt(s: string, max: number, clauseMin: number): [string, string] {
  if (s.length <= max) return [s, ''];
  const clause = clauseCut(s, max, clauseMin);
  if (clause) return cutAt(s, clause.cut, clause.dash);
  const sp = s.lastIndexOf(' ', max);
  return cutAt(s, sp > 0 ? sp : max, false);
}

export function createSentenceQueue(limits: ChunkLimits = CHUNK): SentenceQueue {
  let raw = '';
  let done = false;
  /** Shu indeksgacha matn gaplarga ajratib bo'lingan. */
  let pos = 0;
  /** Audit izi boshlandi - qolgani hech qachon o'qilmaydi. */
  let cut = false;
  /** `:` bilan tugagan qator: keyingi qator iz bo'lmasa o'qiladi, iz bo'lsa tashlanadi. */
  let held: string[] | null = null;
  const pending: string[] = [];
  let taken = 0;
  let total = 0;
  let shortened = false;
  let stopped = false;
  let lastLen = 0;
  let skipLeft = 0;
  /** Ochilish keyingi gapni kutyapti: kutish boshlangandagi `raw.length` (yoki null). */
  let waitMark: number | null = null;
  let openerFree = false;

  const add = (piece: string, into: string[]) => {
    let clean = cleanForSpeech(piece);
    if (!clean) return;
    // Ro'yxat bandi yoki sarlavha tinish belgisisiz tugaydi: bo'laklar bitta qilib
    // yig'ilganda ovoz ularni nafas olmay qo'shib o'qimasin - oxiriga pauza qo'yamiz.
    if (!/[.!?\u2026:;,]$/.test(clean)) clean += piece.trim().replace(/[*_]+$/, '').endsWith(':') ? ':' : '.';
    into.push(clean);
  };

  function advance() {
    while (!cut && pos < raw.length) {
      const lineStart = pos === 0 || raw[pos - 1] === '\n';
      if (lineStart) {
        const nl = raw.indexOf('\n', pos);
        const line = raw.slice(pos, nl < 0 ? raw.length : nl);
        const lineComplete = nl >= 0 || done;
        if (!line.trim()) {
          if (nl < 0) break;
          pos = nl + 1;
          continue;
        }
        if (TRAIL_LINE.test(line)) {
          // Iz boshlandi: uni tanishtirgan `...:` qatori ham o'qilmaydi.
          cut = true;
          held = null;
          break;
        }
        // Oqimda `[T` kabi boshlangan qator iz bo'lib chiqishi mumkin - kutamiz.
        if (!lineComplete && TRAIL_PREFIX.test(line)) break;
        if (held) {
          pending.push(...held);
          held = null;
        }
      }
      const end = nextBoundary(raw, pos, done);
      if (end < 0) break;
      const piece = raw.slice(pos, end);
      let next = end;
      while (next < raw.length && isSpace(raw[next])) next++;
      const atNewline = raw[next] === '\n';
      if (atNewline) next++;
      const endsLine = atNewline || (done && next >= raw.length);
      if (endsLine && piece.trim().replace(/[*_]+$/, '').endsWith(':')) {
        // Oqimda iz qatori hali kelmagan bo'lishi mumkin - keyingi qatorni ko'rmaguncha ushlaymiz.
        held = held ?? [];
        add(piece, held);
      } else {
        add(piece, pending);
      }
      pos = next;
    }
    if (done && !cut && pos >= raw.length && held) {
      pending.push(...held);
      held = null;
    }
  }

  /**
   * Birinchi bo'lak: birinchi ovoz shu bo'lakning TO'LIQ sintezini kutadi, shuning uchun qisqa
   * (FIRST_MAX), lekin gap o'rtasidan kesilmagan va keyingi bo'lak tayyorlanishiga yetadigan
   * darajada uzun (FIRST_MIN). Faqat navbatda borini oladi - keyingi tokenlarni kutmaydi.
   */
  function takeFirst(fits: (head: string, next: string, limit: number) => boolean): string {
    const firstMax = limits.FIRST_MAX;
    let chunk = pending.shift() as string;
    if (chunk.length > firstMax) {
      const clause = clauseCut(chunk, firstMax, limits.CLAUSE_MIN);
      let head = chunk;
      let rest = '';
      if (clause) [head, rest] = cutAt(chunk, clause.cut, clause.dash);
      else if (chunk.length > (limits.FIRST_SOFT_MAX ?? CHUNK.FIRST_SOFT_MAX)) [head, rest] = splitAt(chunk, limits.FIRST_SOFT_MAX ?? CHUNK.FIRST_SOFT_MAX, limits.CLAUSE_MIN);
      if (rest) pending.unshift(rest);
      return head;
    }
    const firstMin = limits.FIRST_MIN ?? CHUNK.FIRST_MIN;
    while (chunk.length < firstMin && pending.length) {
      if (fits(chunk, pending[0], firstMax)) {
        chunk += ` ${pending.shift() as string}`;
        continue;
      }
      // Keyingi gap sig'maydi - uning boshini faqat ibora chegarasida qo'shamiz (so'z o'rtasida emas).
      const next = pending[0];
      const clause = clauseCut(next, firstMax - chunk.length - 1, Math.max(1, firstMin - chunk.length - 1));
      if (clause) {
        const [head, rest] = cutAt(next, clause.cut, clause.dash);
        if (head && rest && fits(chunk, head, firstMax)) {
          pending[0] = rest;
          chunk += ` ${head}`;
        }
      }
      break;
    }
    return chunk;
  }

  return {
    push(markdown, isDone) {
      const text = markdown.replace(/\r\n?/g, '\n');
      if (text.length < pos || text.slice(0, pos) !== raw.slice(0, pos)) {
        // Boshqa matn (qayta yaratilgan javob) - noldan.
        pos = 0;
        cut = false;
        held = null;
        pending.length = 0;
      }
      raw = text;
      done = done || isDone;
      advance();
    },

    take() {
      while (skipLeft > 0 && pending.length) {
        // To'liq aytilgan gaplar tashlanadi; yarim aytilgani esa boshidan o'qiladi.
        if (pending[0].length > skipLeft) {
          skipLeft = 0;
          break;
        }
        const s0 = pending.shift() as string;
        skipLeft -= s0.length + 1;
        total += s0.length;
      }
      waitMark = null;
      if (stopped || !pending.length) return null;
      if (taken === 0 && !openerFree && !done && !cut && !held && pending.length === 1 && pending[0].length < (limits.FIRST_MIN ?? CHUNK.FIRST_MIN) && pending[0].length + 1 + (raw.length - pos) <= limits.FIRST_MAX) {
        // Qisqa ochilish ("Albatta!") va javob hali oqyapti: keyingi gap birinchi bo'lakka sig'ishi
        // mumkin - kutamiz. Kutish chegaralangan: oqayotgan qism sig'masdan uzaysa ochilish yolg'iz
        // aytiladi; bir yo'la kelgan javobda keyingi kadrlar shu zahoti keladi. Aks holda 0.6 s lik
        // "Albatta." dan keyin ikkinchi bo'lak sintezi ~1.5-2 s jim kutilardi. Oqim to'xtab qolsa
        // (masalan kirish gapidan keyin agent vosita chaqirdi) gap navbati `releaseOpener()` qiladi.
        waitMark = raw.length;
        return null;
      }
      const fits = (head: string, next: string, limit: number) => head.length + 1 + next.length <= limit && total + head.length + 1 + next.length <= limits.TOTAL_LIMIT;
      let chunk: string;
      let max: number;
      if (taken === 0) {
        chunk = takeFirst(fits);
        max = limits.FIRST_MAX;
      } else {
        // `+ 1` - qo'shilgan gaplar orasidagi bo'shliq: teng uzunlikdagi ikki gap bitta bo'lakka sig'sin.
        const grown = Math.max(limits.GROW_MIN ?? CHUNK.GROW_MIN, Math.round((limits.GROW ?? CHUNK.GROW) * (lastLen + 1)));
        max = Math.min(limits.MAX, grown);
        chunk = pending.shift() as string;
        if (chunk.length > max) {
          const [head, rest] = splitAt(chunk, max, limits.CLAUSE_MIN);
          // Qisqa dum (< CLAUSE_MIN) qoldirmaymiz: u alohida bo'lak bo'lib ~2 s yangraydi va undan
          // keyingi bo'lak shu vaqtda sintez bo'lib ulgurmaydi. Gap biroz uzun bo'lsa ham butun.
          if (rest.length >= limits.CLAUSE_MIN || chunk.length > Math.min(limits.MAX, max + limits.CLAUSE_MIN)) {
            chunk = head;
            if (rest) pending.unshift(rest);
          }
        }
      }
      if (total + chunk.length > limits.TOTAL_LIMIT) {
        // Gap chegarasida to'xtaymiz - qolgani ekranda.
        shortened = true;
        stopped = true;
        pending.length = 0;
        return null;
      }
      if (taken > 0) {
        while (pending.length && fits(chunk, pending[0], max)) {
          chunk += ` ${pending.shift() as string}`;
        }
      }
      total += chunk.length;
      taken++;
      lastLen = chunk.length;
      return chunk;
    },

    skip(chars) {
      if (chars > 0) skipLeft += chars;
    },

    get openerWait() {
      return waitMark;
    },

    releaseOpener() {
      openerFree = true;
      waitMark = null;
    },

    get finished() {
      if (stopped) return true;
      if (pending.length || held) return false;
      return cut || (done && pos >= raw.length);
    },
    get shortened() {
      return shortened;
    },
    get taken() {
      return taken;
    },
  };
}

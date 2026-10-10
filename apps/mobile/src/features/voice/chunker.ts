/**
 * Gap navbati: javob markdown'i (oqimda o'sib boradi) -> TTS bo'laklari (tozalangan).
 *
 * NIMA UCHUN bo'laklash SHART (web'da emas): expo-audio faqat to'liq faylni o'ynatadi.
 * 1000 belgilik javobning to'liq WAV'i 8-12 s sintez qilinadi; birinchi qisqa gap
 * (<=160) alohida so'ralsa birinchi ovoz ~1.2-2 s da chiqadi, keyingi bo'laklar esa
 * oldingisi yangrayotganda tayyorlanadi (sintez real vaqtdan ~4.7x tez).
 *
 * Tortish modeli: `push(to'liq matn, done)` istalgancha chaqiriladi (har token), `take()`
 * keyingi tayyor bo'lakni beradi yoki null (hali to'liq gap yo'q). Yuqori oqim haqiqiy
 * token oqimini bersa gaplar kelishi bilan o'qiladi; bir yo'la bersa ham xuddi shu yo'l.
 *
 * Bo'lak o'sishi: har keyingi bo'lak oldingisidan ko'pi bilan 2 baravar uzun (kamida 80).
 * NIMA UCHUN: javob bir yo'la keladi, ochko'z yig'ish ikkinchi bo'lakni darhol ~350 ga
 * to'ldirardi. O'lchov (66 ms ovoz/belgi, sintez 4.7x tez + ~1.1 s birinchi bayt): 46
 * belgilik birinchi gap 3.0 s yangraydi, 309 belgilik ikkinchisi esa 5.4 s sintez qilinadi -
 * orada 2.4 s jimlik. 2x qoidasi bilan keyingi bo'lak oldingisi yangrab bo'lguncha tayyor.
 */
import { cleanForSpeech, isLowerLetter, TRAIL_LINE } from './speechText';

export const CHUNK = { FIRST_MAX: 160, MAX: 350, CLAUSE_MIN: 40, TOTAL_LIMIT: 3000, GROW: 2, GROW_MIN: 80 } as const;

export interface ChunkLimits {
  FIRST_MAX: number;
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

/** Uzun gapni bo'lish: avval vergul/nuqtali vergul/ikki nuqta yoki " - " da, bo'lmasa bo'shliqda. */
export function splitAt(s: string, max: number, clauseMin: number): [string, string] {
  if (s.length <= max) return [s, ''];
  let cut = -1;
  let dash = false;
  for (let i = Math.min(max, s.length) - 1; i >= clauseMin - 1 && i > 0; i--) {
    if (',;:'.includes(s[i]) && s[i + 1] === ' ') {
      cut = i + 1;
      break;
    }
    if (i >= clauseMin && s.startsWith(' - ', i)) {
      cut = i;
      dash = true;
      break;
    }
  }
  if (cut < 0) {
    const sp = s.lastIndexOf(' ', max);
    cut = sp > 0 ? sp : max;
  }
  const head = s.slice(0, cut).trim();
  let rest = s.slice(cut).trim();
  if (dash) rest = rest.replace(/^-\s+/, '');
  return [head, rest];
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
      if (stopped || !pending.length) return null;
      // `+ 1` - qo'shilgan gaplar orasidagi bo'shliq: teng uzunlikdagi ikki gap bitta bo'lakka sig'sin.
      const grown = Math.max(limits.GROW_MIN ?? CHUNK.GROW_MIN, Math.round((limits.GROW ?? CHUNK.GROW) * (lastLen + 1)));
      const max = taken === 0 ? limits.FIRST_MAX : Math.min(limits.MAX, grown);
      let chunk = pending.shift() as string;
      if (chunk.length > max) {
        const [head, rest] = splitAt(chunk, max, limits.CLAUSE_MIN);
        chunk = head;
        if (rest) pending.unshift(rest);
      }
      if (total + chunk.length > limits.TOTAL_LIMIT) {
        // Gap chegarasida to'xtaymiz - qolgani ekranda.
        shortened = true;
        stopped = true;
        pending.length = 0;
        return null;
      }
      if (taken > 0) {
        while (pending.length && chunk.length + 1 + pending[0].length <= max && total + chunk.length + 1 + pending[0].length <= limits.TOTAL_LIMIT) {
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

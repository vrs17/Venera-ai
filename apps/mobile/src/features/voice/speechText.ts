/**
 * Javob matnini O'QISHGA (TTS) va ovozli ekranda KO'RSATISHGA tayyorlash.
 *
 * Qoidalar web'dagi `apps/web/src/components/chat/readAloud.ts` (`prepareSpeech`) dan
 * 1:1 ko'chirilgan - ikki nusxa bir-biridan ajralib ketmasin. Qo'shimchalar (NEW):
 * yalang URL, vazifa kalitlari (`DVSIB-245`), emoji va strelkalar, o'zbekcha apostrof.
 *
 * NIMA UCHUN: javob markdown bo'lib keladi (`**bo'lim:**`, `* ro'yxat`, `[T1]`, jadval).
 * O'qigichga shundayligicha berilsa u yulduzchani ham, `T1` ni ham gap deb o'qiydi -
 * javob o'rniga "yulduzcha yulduzcha" eshitiladi.
 *
 * Regex'larda `\p{L}` va lookbehind YO'Q: Hermes versiyasiga bog'liq (AnswerMarkdown.tsx
 * bilan bir xil sabab) - harflar aniq oraliq bilan.
 */
import type { UiLang } from '@/i18n';

/** Lotin (o'zbekcha `ʻ`/`ʼ` bilan) va kirill harflari oralig'i. */
const LETTERS = 'A-Za-z\\u00C0-\\u024F\\u02B0-\\u02FF\\u0400-\\u04FF';

/** Audit izi qatori: `[T1] hrm_search_employees - ...` (web `answerBody` bilan bir xil). */
export const TRAIL_LINE = /^\s*\[[A-Za-z]{1,4}[_-]?\d{1,6}\]\s/;

/** Iqtibos markerlari: `[T1]`, `[HR_045]`, `[T1, T2]`, `[T1; 2]`. */
const MARKERS = /\[[A-Za-z]{1,4}[_-]?\d{1,6}(?:\s*[,;]\s*(?:[A-Za-z]{1,4}[_-]?)?\d{1,6})*\]/g;
/** Hujjat iqtiboslari: `[1]`, `[1, 2]`. */
const CITES = /\[\d{1,3}(?:\s*,\s*\d{1,3})*\]/g;
/** Dalil markerlari: `(e4)`, `(e1, e2)` - harf+raqam talab qilinadi ("(21)" band raqami bo'lishi mumkin). */
const EVIDENCE = /\((?:[A-Za-z]{1,2}\d{1,3})(?:\s*,\s*[A-Za-z]{1,2}\d{1,3})*\)/g;

const KEY = '[A-Z][A-Z0-9]{1,9}-\\d{1,6}';
/** `(DVSIB-245)` - qavsi bilan. */
const KEY_PAREN = new RegExp(`\\(\\s*${KEY}\\s*\\)`, 'g');
/** Qator / ro'yxat bandi boshidagi `DVSIB-245: ` yoki `DVSIB-245 - ` - kalit va ajratgich ketadi, nom qoladi. */
const KEY_LEAD = new RegExp(`^(\\s*(?:[-*+\\u2022][ \\t]+|\\d{1,2}[.)][ \\t]+)?)${KEY}(?![${LETTERS}0-9_]|-\\d)\\s*[:\\-\\u2013]\\s*`, 'gm');
/** Qolgan kalitlar (web `TASK_KEY` bilan bir xil chegaralar, `\p` siz). */
const KEY_ANY = new RegExp(`(^|[^${LETTERS}0-9_-])(${KEY})(?![${LETTERS}0-9_]|-\\d)`, 'g');

/** Emoji va piktogrammalar: surrogat juftlar (U+1F000+), Misc Symbols/Dingbats, VS16, ZWJ. */
const EMOJI = /(?:\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|\uD83E[\uDC00-\uDFFF]|[⌀-⏿☀-➿⬀-⯿]|️|‍)/g;

/**
 * Javobning O'QILADIGAN qismi: audit izidan oldingi hammasi (web `answerBody`, 1:1).
 *
 * Iz EKRAN uchun kerak (bank muhitida javob qaysi so'rovdan chiqqani ko'rinishi shart),
 * lekin o'qilganda javobdan bir necha barobar uzun: o'lchangan savolda javob 87 belgi,
 * iz bilan 614. Ajratish NAQSH bo'yicha: iz qatorlari `[T1]` bilan BOSHLANADI, javob
 * ichidagi iqtibos esa gap OXIRIDA turadi. Izni tanishtirgan `...:` qatori ham ketadi.
 */
export function answerBody(markdown: string): string {
  const lines = markdown.split(/\r?\n/);
  let at = lines.findIndex((line) => TRAIL_LINE.test(line));
  if (at < 0) return markdown;
  while (at > 0 && (!lines[at - 1].trim() || lines[at - 1].trim().endsWith(':'))) at--;
  const body = lines.slice(0, at).join('\n').trim();
  // Hammasi iz bo'lib chiqdi: boricha o'qiymiz - jim qolgandan afzal.
  return body || markdown;
}

/**
 * Bitta bo'lak (gap yoki bir necha gap) -> TTS matni. Tartib MUHIM (har qadam izohida).
 */
export function cleanForSpeech(fragment: string): string {
  return (
    fragment
      // 1. Kod bloklari butunlay ketadi (yopilmagani ham); inline kod - mazmuni qoladi.
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/```[\s\S]*$/, ' ')
      .replace(/`([^`\n]*)`/g, '$1')
      // 2. Havola va rasm: matni qoladi, URL ketadi. Iqtibos qoidalaridan OLDIN bo'lishi
      //    shart - aks holda `[matn](url)` ning birinchi qismi marker deb o'chirilardi.
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
      // 3. NEW: yalang URL - o'qilganda "ha-te-te-pe-es" bo'ladi, ma'no bermaydi.
      .replace(/\bhttps?:\/\/\S+/gi, ' ')
      .replace(/\bwww\.\S+/gi, ' ')
      // 4. Iqtibos markerlari EKRAN uchun (hujjatga havola); o'qilganda faqat shovqin.
      //    Naqsh ATAYLAB tor: `[eslatma]` kabi oddiy qavsli so'z matnning o'zi bo'lishi mumkin.
      .replace(MARKERS, ' ')
      .replace(CITES, ' ')
      .replace(EVIDENCE, ' ')
      // 5. NEW: vazifa kalitlari. "DVSIB-245: Hisobotni tayyorlash" -> "Hisobotni tayyorlash":
      //    kalit ekranda turadi, quloq uchun esa vazifa NOMI muhim.
      .replace(KEY_PAREN, ' ')
      .replace(KEY_LEAD, '$1')
      .replace(KEY_ANY, '$1')
      // 6. Sarlavha, jadval, ro'yxat, ajratish belgilari.
      .replace(/^#{1,6}\s*/gm, '')
      .replace(/^[ \t]*\|?[\s:|-]{3,}\|?[ \t]*$/gm, ' ')
      // Ro'yxat belgisi -> gap chegarasi (aks holda hamma band bitta uzun gap bo'lib o'qiladi).
      // `*` ni olib tashlashdan OLDIN.
      .replace(/^[ \t]*[-*+•][ \t]+/gm, '. ')
      .replace(/^[ \t]*\d{1,2}[.)][ \t]+/gm, '. ')
      .replace(/\|/g, ', ')
      .replace(/\*\*|__|~~/g, '')
      .replace(/\*/g, '')
      // 7. NEW: emoji o'qilmaydi; strelka - pauza; uzun tire so'zlar orasida - vergul.
      .replace(EMOJI, '')
      .replace(/[→←⇒]/g, ' ')
      .replace(/ [—–] /g, ', ')
      // 8. NEW: apostroflar ASCII ga - TTS modeli lotin matnni `'` bilan o'rgangan
      //    (ekran uchun sayqal `oʻ` yasagan bo'lishi mumkin).
      .replace(/[ʻʼ‘’`′]/g, "'")
      // 9. Qatorlar -> gap chegarasi, bo'shliq va tinish belgilarini tartiblash (web bilan bir xil).
      .replace(/\r?\n+/g, '. ')
      .replace(/\s+/g, ' ')
      .replace(/\s+([,.;:!?])/g, '$1')
      // TARTIB MUHIM: avval takroriy nuqta bittaga, keyin ":." / ",." juftliklari.
      .replace(/(?:\.\s*){2,}/g, '. ')
      .replace(/,\s*\./g, '.')
      .replace(/([;:])\s*\./g, '$1')
      .replace(/([.:;])\s*,\s*/g, '$1 ')
      .replace(/^[\s.,;:]+/, '')
      .replace(/[\s,;:|-]+$/, '')
      .trim()
  );
}

/** Platforma so'rovi belgilari ekranda yashiriladi (mobil AnswerMarkdown bilan bir xil naqsh). */
const TOOL_MARKS = /[  ]*\[T\d{1,3}(?:\s*[,;]\s*T?\d{1,3})*\]/g;

/**
 * Ovozli ekran transkripti uchun matn: katta shriftda, markdown belgilarisiz, lekin
 * qatorlar (ro'yxat) saqlanadi; hujjat iqtibosi `[1]` va vazifa kaliti QOLADI (ekran uchun).
 */
export function displayText(markdown: string): string {
  return answerBody(markdown)
    .replace(TOOL_MARKS, '')
    .replace(/```/g, '')
    .replace(/\*\*|__/g, '')
    .replace(/`/g, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/^[ \t]*\|?[ \t:|-]{3,}\|?[ \t]*$/gm, '')
    .replace(/^[ \t]*[-*+•][ \t]+/gm, '• ')
    .replace(/[ \t]+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

const CYRILLIC = /[Ѐ-ӿ]/g;
const ANY_LETTER = new RegExp(`[${LETTERS}]`, 'g');

/**
 * O'zbekcha (lotin) ovoz bilan o'qisa bo'ladimi.
 * NIMA UCHUN kirill ulushi: uz interfeysdagi odam ham ruscha javob olishi mumkin - lotin
 * TTS kirillni harfma-harf o'qiydi. Harf yo'q matn (faqat raqam) - to'sqinlik qilmaydi.
 */
export function isSpeakable(text: string, uiLang: UiLang): boolean {
  if (uiLang !== 'uz') return false;
  const letters = text.match(ANY_LETTER)?.length ?? 0;
  if (!letters) return true;
  const cyr = text.match(CYRILLIC)?.length ?? 0;
  return cyr / letters < 0.2;
}

/** Kichik harfmi (lotin va kirill uchun; `\p{Ll}` siz). */
export function isLowerLetter(ch: string | undefined): boolean {
  if (!ch) return false;
  return ch.toLowerCase() === ch && ch.toUpperCase() !== ch;
}

/**
 * Bo'lib gapirish matnini tekshirish: bu Barnoning O'Z ovozi (aks-sado) emasmi va oddiy
 * "to'xta" buyrug'i emasmi.
 *
 * NIMA UCHUN: karnay rejimida AEC har qurilmada ham yaxshi ishlamaydi - Barno gapi
 * mikrofonga qaytib, VAD uni "odam gapirdi" deb olishi mumkin. STT esa uni aniq matnga
 * aylantiradi va u YANGI SAVOL bo'lib ketardi (Barno o'ziga javob beradi). Matn hozir/oldin
 * yangragan bo'lak bilan ko'p mos kelsa - bu aks-sado: savol emas, chegara ko'tariladi.
 *
 * "To'xta", "bas", "stop" - odam faqat ovozni to'xtatmoqchi; agentga savol bo'lib ketmaydi.
 */

/** Tutuq belgisi variantlari bitta (STT va TTS matni turlicha yozishi mumkin). */
function tokens(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[ʻʼ‘’`′]/g, "'")
    .replace(/[^\p{L}\p{N}']+/gu, ' ')
    .split(' ')
    .map((w) => w.replace(/^'+|'+$/g, ''))
    .filter((w) => w.length >= 2);
}

/** Shu ulushdan ko'p so'z yangragan matnda bo'lsa - aks-sado. */
const ECHO_SHARE = 0.6;
/** O'zbekcha qo'shimchalar: so'z boshining 5 harfi mos kelsa ham bir so'z deb olinadi. */
const STEM = 5;

export function isEchoOf(transcript: string, spoken: readonly string[]): boolean {
  const words = tokens(transcript);
  if (!words.length) return false;
  const pool = new Set(spoken.flatMap(tokens));
  if (!pool.size) return false;
  const stems = new Set([...pool].filter((w) => w.length >= STEM).map((w) => w.slice(0, STEM)));
  const hits = words.filter((w) => pool.has(w) || (w.length >= STEM && stems.has(w.slice(0, STEM)))).length;
  return hits / words.length >= ECHO_SHARE;
}

const STOP_WORDS = new Set([
  "to'xta",
  "to'xtang",
  "to'xtat",
  "to'xtating",
  "bo'ldi",
  'bas',
  'basta',
  'yetadi',
  'yetarli',
  'stop',
  'enough',
  'стоп',
  'хватит',
  'достаточно',
  'подожди',
  'погоди',
]);
/** Buyruq yonida kelishi mumkin bo'lgan, ma'no o'zgartirmaydigan so'zlar. */
const FILLER = new Set(['barno', 'iltimos', 'mayli', "xo'p", 'ha', 'ok', 'okay', 'please', 'пожалуйста', 'ладно', 'rahmat', 'спасибо', 'thanks']);

/** Qisqa (<=3 so'z) va faqat to'xtatish so'zlaridan iborat. */
export function isStopCommand(transcript: string): boolean {
  const words = tokens(transcript);
  if (!words.length || words.length > 3) return false;
  return words.some((w) => STOP_WORDS.has(w)) && words.every((w) => STOP_WORDS.has(w) || FILLER.has(w));
}

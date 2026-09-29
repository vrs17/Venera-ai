// Javobni ovoz chiqarib o'qish (javob ostidagi 🔊 tugmasi).
//
// Ovoz yo'li - ovozli panel ishlatadigan AYNI `speakStream` (tts.api.ts): birinchi
// bo'lak ~1 s da keladi, qolgani oqimda. Bir vaqtda BITTA javob o'qiladi - boshqasi
// bosilsa, avvalgisi to'xtaydi (ikki ovoz ustma-ust tushmasin). Holat modul
// darajasida: har javobning tugmasi "hozir men o'qilyapmanmi" ni shu yerdan biladi.

import { readonly, ref } from 'vue'
import { canSpeak, speakStream } from '../../api/tts.api'
import { ApiError } from '../../api/http'

/** Hozir o'qilayotgan javob kaliti (exchange id), yo'q bo'lsa null. */
const current = ref<string | null>(null)
/** Ovoz so'ralgan, lekin hali boshlanmagan (tarmoq). */
const pending = ref<string | null>(null)
let controller: AbortController | null = null
let stopPlayback: (() => void) | null = null

export function stopReading(): void {
  controller?.abort()
  controller = null
  stopPlayback?.()
  stopPlayback = null
  current.value = null
  pending.value = null
}

/**
 * `key` javobini o'qiydi (yoki o'qilayotgan bo'lsa - to'xtatadi).
 * Muvaffaqiyatsizlikda `false` - chaqiruvchi qisqa xabar ko'rsatadi. Ovoz serverda
 * yoqilmagan (501) yoki to'xtatilgan bo'lsa - xato emas, `true`.
 */
export async function toggleReading(
  key: string,
  markdown: string,
  locale: string,
  /** Javobning savol kaliti - ovoz admin izida shu savolga bog'lansin. */
  turnId?: string | null,
): Promise<boolean> {
  if (current.value === key || pending.value === key) {
    stopReading()
    return true
  }
  stopReading()
  const text = forSpeech(markdown)
  if (!text) return true
  const mine = new AbortController()
  controller = mine
  pending.value = key
  try {
    const playback = await speakStream(text, locale, mine.signal, undefined, turnId)
    if (controller !== mine) {
      playback.stop()
      return true
    }
    pending.value = null
    current.value = key
    stopPlayback = playback.stop
    try {
      await playback.done
    } finally {
      if (controller === mine) {
        current.value = null
        stopPlayback = null
        controller = null
      }
    }
    return true
  } catch (err) {
    if (controller === mine) {
      pending.value = null
      current.value = null
      controller = null
    }
    if (err instanceof DOMException && err.name === 'AbortError') return true
    if (err instanceof ApiError && err.status === 501) return true
    return false
  }
}

export function useReadAloud() {
  return { current: readonly(current), pending: readonly(pending), canSpeak, toggleReading, stopReading }
}

/* ---- O'qishga tayyorlash: ovozli panel (VoicePanel) va javob ostidagi 🔊 - BITTA
   qoidalar to'plami, ikki nusxa bir-biridan ajralib ketmasin. ---- */

//: O'qiladigan belgilar chegarasi. Backend ham shu qiymatda kesadi
//: (`tts_max_chars`), lekin u SO'Z chegarasida kesadi, ya'ni gap yarmida
//: to'xtaydi. Shuning uchun qisqartirishni o'zimiz, GAP chegarasida
//: qilamiz - backenddagisi zaxira bo'lib qoladi.
//:
//: 600 EDI va bu javobni yarmida kesardi: mehnat ta'tili bo'yicha 6 bandli
//: javob 1016 belgi bo'lib, ovoz 3-band oxirida to'xtab qolardi.
//:
//: 3000 jonli o'lchovga asoslangan: TTS serveri 5000 belgini ham qabul
//: qiladi va birinchi bayt UZUNLIKDAN QAT'I NAZAR ~1.37 s da keladi, ya'ni
//: uzun matn kechikish qo'shmaydi. Ovoz esa real vaqtdan ~4.7x tez
//: yetkaziladi (3000 belgi = ~198 s ovoz, ~41 s oqim), shuning uchun ijro
//: hech qachon oqimdan o'zib ketmaydi.
const SPEAK_LIMIT = 3000

/**
 * Javobning O'QILADIGAN qismi: audit izidan oldingi hammasi.
 *
 * Javob IKKI qismdan iborat bo'lib keladi - avval javobning O'ZI, keyin
 * "Tekshirilgan HRM ma'lumotlari:" va `[T1] hrm_search_employees - ... ->`
 * ko'rinishidagi iz. Iz EKRAN uchun kerak: bank muhitida xodim javob qaysi
 * so'rovdan chiqqanini ko'rishi shart. Lekin O'QILGANDA u javobdan bir
 * necha barobar uzun: jonli o'lchangan savolda javobning o'zi 87 belgi,
 * iz bilan birga 614 belgi. Ya'ni ovoz javobni aytib bo'lgach, yana yarim
 * daqiqa "employeeId=22, month=9, year=2026" o'qib turardi.
 *
 * Ajratish NAQSH bo'yicha, matn bo'yicha EMAS: iz qatorlari `[T1]` kabi
 * marker bilan BOSHLANADI, javob ichidagi iqtibos esa gap OXIRIDA turadi
 * (`... kech qolmagan [T3].`). Izni tanishtirgan qator (`:` bilan tugaydi)
 * ham tashlanadi - uning MATNI yuqoridagi modelning tilidan kelib chiqadi
 * va o'zgarishi mumkin, shakli esa yo'q.
 */
function answerBody(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  let at = lines.findIndex((line) => /^\s*\[[A-Za-z]{1,4}[_-]?\d{1,6}\]\s/.test(line))
  if (at < 0) return markdown
  while (at > 0 && (!lines[at - 1].trim() || lines[at - 1].trim().endsWith(':'))) at--
  const body = lines.slice(0, at).join('\n').trim()
  // Hammasi iz bo'lib chiqdi (javobning o'zi yo'q): boricha o'qiymiz -
  // jim qolgandan ko'ra afzal.
  return body || markdown
}

/**
 * Javob matnini O'QISHGA tayyorlaydi.
 *
 * Javob markdown bo'lib keladi: `**bo'lim:**`, `* ro'yxat`, `[T1]` iqtibos
 * markerlari, ba'zan jadval. O'qigichga shundayligicha berilsa, u
 * yulduzchani ham, `T1` ni ham gap deb o'qiydi - ya'ni javob eshitilmaydi,
 * "yulduzcha yulduzcha dasturlash bo'limi" eshitiladi.
 *
 * Ro'yxat va jadval qatorlari NUQTAGA aylanadi: aks holda hamma qator bitta
 * uzun gap bo'lib qolib, ovoz nafas olmay o'qiydi.
 */
export function prepareSpeech(markdown: string): { text: string; shortened: boolean } {
  const text = answerBody(markdown)
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    // Havola va rasm: ko'rinadigan matn qoladi, URL ketadi. Iqtibos
    // qoidalaridan OLDIN bo'lishi shart - aks holda `[matn](url)` ning
    // birinchi qismi marker deb o'chirilardi.
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    // Iqtibos markerlari: `[T1]`, `[HR_045]`, `[1]`, `[1, 2]`. Ular EKRAN
    // uchun - hujjatga havola, va o'qilganda faqat shovqin. Naqsh ATAYLAB
    // tor: `[eslatma]` kabi oddiy qavsli so'z matnning o'zi bo'lishi mumkin.
    .replace(/\[[A-Za-z]{1,4}[_-]?\d{1,6}\]/g, ' ')
    .replace(/\[\d{1,3}(?:\s*,\s*\d{1,3})*\]/g, ' ')
    // Qavs ichidagi dalil markerlari: `(e4)`, `(e1, e2)`. Ular hujjat
    // ichidagi parchaga ishora qiladi va `sources` kadrida UMUMAN yo'q,
    // ya'ni ekranda ham tushuntirilmaydi - o'qilganda esa "e to'rt" bo'lib
    // chiqadi. Naqsh harf+raqam TALAB qiladi: "(lavozimi)" va "(sentyabr)"
    // javobning o'z matni, "(21)" esa band raqami bo'lishi mumkin.
    .replace(/\((?:[A-Za-z]{1,2}\d{1,3})(?:\s*,\s*[A-Za-z]{1,2}\d{1,3})*\)/g, ' ')
    .replace(/^#{1,6}\s*/gm, '')
    // Jadval ajratgich qatori (`|---|---|`) - butunlay ketadi.
    .replace(/^[ \t]*\|?[\s:|-]{3,}\|?[ \t]*$/gm, ' ')
    // Ro'yxat belgisi -> gap chegarasi. `*` ni olib tashlashdan OLDIN.
    .replace(/^[ \t]*[-*+\u2022][ \t]+/gm, '. ')
    .replace(/\|/g, ', ')
    .replace(/\*\*|__|~~/g, '')
    .replace(/\*/g, '')
    .replace(/\r?\n+/g, '. ')
    .replace(/\s+/g, ' ')
    // Yuqoridagi almashtirishlardan qolgan bo'shliq va takror tinish
    // belgilari: "kechikdi [T1]:" -> "kechikdi :" -> "kechikdi:".
    .replace(/\s+([,.;:!?])/g, '$1')
    // Ro'yxat va jadval qatorlaridan qolgan qo'shaloq tinish belgilari.
    // TARTIB MUHIM: avval takroriy nuqta bittaga tushadi, keyingina
    // ":." / ",." juftliklari tuzatiladi. Teskari tartibda ":.." ning
    // faqat yarmi tuzalib, ":." qolib ketardi.
    .replace(/(?:\.\s*){2,}/g, '. ')
    .replace(/,\s*\./g, '.')           // "3," + qator oxiri -> "3."
    .replace(/([;:])\s*\./g, '$1')     // "kechikdi:" + ro'yxat -> "kechikdi:"
    .replace(/([.:;])\s*,\s*/g, '$1 ') // gap boshidagi ortiqcha vergul
    .replace(/^[\s.,;:]+/, '')
    .replace(/[\s,;:|-]+$/, '')
    .trim()

  if (text.length <= SPEAK_LIMIT) return { text, shortened: false }
  const cut = text.slice(0, SPEAK_LIMIT)
  const stop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('! '), cut.lastIndexOf('? '))
  // Gap chegarasi juda boshida bo'lsa ishlatilmaydi: javobning uchdan biri
  // o'qilib to'xtagandan ko'ra so'z chegarasida kesish tushunarliroq.
  if (stop > SPEAK_LIMIT / 2) return { text: cut.slice(0, stop + 1), shortened: true }
  const space = cut.lastIndexOf(' ')
  return { text: (space > 0 ? cut.slice(0, space) : cut).replace(/[\s,;:-]+$/, ''), shortened: true }
}

/** Faqat matn - javob ostidagi 🔊 uchun (qisqartirilgani haqida eslatma chiqmaydi). */
export function forSpeech(markdown: string): string {
  return prepareSpeech(markdown).text
}

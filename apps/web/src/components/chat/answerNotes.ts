// "Eslatma: ..." - javob oxiridagi izoh (sana bo'yicha ogohlantirish va h.k.), web chat
// va Mini App uchun UMUMIY (MarkdownMessage).
//
// 2026-10-10, yordamchi 3.3: sanaga oid izoh alohida qatorda keladi - "Eslatma: bugun dam
// olish kuni, ma'lumot juma kungi". U javobning o'zi emas, izoh: oddiy xatboshi bo'lib
// tursa asosiy javob bilan "bahslashadi". Shuning uchun u jim izoh bloki bo'lib chiziladi
// (kichik, xira, chapda ingichka chiziq).
//
// Javob tili interfeys tilidan farq qilishi mumkin (yordamchi inglizcha ham javob beradi),
// shuning uchun HAMMA tildagi so'z taniladi: Eslatma / Эслатма / Примечание / Note.
//
// IKKI BOSQICH:
//   1. Markdown matnida: eslatma (yoki manba) qatori oldingi qatorga yopishgan bo'lsa (bo'sh
//      qatorsiz), markdown uni oldingi xatboshining davomi qilib yuborardi - oldiga bo'sh
//      qator qo'yiladi (kod bloki ichida emas);
//   2. HTML da: shu so'z bilan boshlanadigan YUQORI darajadagi xatboshi `vmd-note` sinfini
//      oladi (ro'yxat, jadval va iqtibos ichidagisi emas - u boshqa narsaning bir qismi).
//
// FAQAT BOSHQA MATNDAN KEYIN (UX ko'rigi): o'zbekchada "Eslatma" - "eslatib qo'yish" ham.
// "Eslatma: ertaga 10:00 da yig'ilish" javobning O'ZI bo'lishi mumkin - u xira va kichik
// bo'lib qolmasin. Shuning uchun izoh faqat oldida boshqa mazmun (xatboshi, sarlavha,
// ro'yxat, jadval) bo'lsa belgilanadi; javob eslatma bilan BOSHLANSA - oddiy matn.
//
// MANBA QATORI (3.3 "hikoya" javoblari): oxirgi xatboshi "Manba: HRM, CRM" -
// u "N manba" tugmasini takrorlaydi va javob bilan bahslashadi. U `vmd-source` - kichik,
// xira izoh (qutisiz). Faqat javob OXIRIDA (undan keyin faqat eslatma izohi bo'lishi
// mumkin - "Manba: ..." keyin "Eslatma: ...") va oldida mazmun bo'lsa.
//
// NEGA lookbehind yo'q: Telegram'ning eski iOS WebView'i uni tanimaydi (answerMarks.ts).

/** Qator boshidagi eslatma: ixtiyoriy qalin/kursiv (`**Eslatma:**`, `**Eslatma**:`),
 *  ixtiyoriy ℹ️, so'z va ikki nuqta. */
const NOTE_LINE = /^[ \t]{0,3}(?:[*_]{1,2})?(?:ℹ️?[ \t]*)?(?:eslatma|эслатма|примечание|note)[ \t]*(?:[*_]{1,2})?[ \t]*:/iu

/** Manba qatori: "Manba:", "Manbalar:", "Манба:", "Источник(и):", "Source(s):" - ixtiyoriy
 *  qalin/kursiv bilan. Qator boshida, chekinishsiz (ro'yxat ichidagisi emas). */
const SOURCE_LINE = /^(?:[*_]{1,2})?(?:manba(?:lar)?|манба(?:лар)?|источники?|sources?)[ \t]*(?:[*_]{1,2})?[ \t]*:/iu

/** Chizilgan xatboshining matni (teglarsiz). */
const NOTE_TEXT = /^\s*(?:ℹ️?\s*)?(?:eslatma|эслатма|примечание|note)\s*:/iu
const SOURCE_TEXT = /^\s*(?:manba(?:lar)?|манба(?:лар)?|источники?|sources?)\s*:/iu

const FENCE = /^[ \t]{0,3}(`{3,}|~{3,})/

/** Eslatma yoki manba qatori oldingi qatorga yopishgan bo'lsa - orasiga bo'sh qator. */
export function separateNotes(markdown: string): string {
  if (!markdown || !/(eslatma|эслатма|примечание|note|manba|манба|источник|source)/iu.test(markdown)) return markdown
  const lines = markdown.split('\n')
  const out: string[] = []
  let fence: string | null = null
  for (const line of lines) {
    const f = FENCE.exec(line)
    if (f) {
      if (!fence) fence = f[1][0]
      else if (f[1][0] === fence) fence = null
    } else if (!fence && (NOTE_LINE.test(line) || SOURCE_LINE.test(line)) && out.length && out[out.length - 1].trim()) {
      out.push('')
    }
    out.push(line)
  }
  return out.join('\n')
}

/** Blokda mazmun bormi (bo'sh xatboshi yoki faqat chiziq emas). */
function hasContent(el: Element): boolean {
  return el.tagName !== 'HR' && (!!el.textContent?.trim() || !!el.querySelector('img, table'))
}

/** Eslatma xatboshisi (yuqori darajadagi `<p>`). */
function isNoteBlock(el: Element): boolean {
  return el.tagName === 'P' && NOTE_TEXT.test(el.textContent ?? '')
}

/**
 * Eslatma xatboshilariga `vmd-note`, oxirgi manba qatoriga `vmd-source` sinfi. DOMPurify'dan
 * KEYIN, o'z hujjatimizda. Faqat yuqori darajadagi `<p>` (ro'yxat, jadval, iqtibos ichidagisi
 * emas) va faqat oldida boshqa mazmun bo'lsa (javob eslatma bilan boshlansa - u javobning o'zi).
 */
export function markNotes(doc: Document): void {
  const blocks = Array.from(doc.body.children)
  let content = false
  blocks.forEach((block, i) => {
    const isP = block.tagName === 'P'
    const text = isP ? (block.textContent ?? '') : ''
    if (isP && isNoteBlock(block)) {
      if (content) block.classList.add('vmd-note')
      else content = true
      return
    }
    if (isP && content && SOURCE_TEXT.test(text) && blocks.slice(i + 1).every((b) => !hasContent(b) || isNoteBlock(b))) {
      block.classList.add('vmd-source')
      return
    }
    if (hasContent(block)) content = true
  })
}

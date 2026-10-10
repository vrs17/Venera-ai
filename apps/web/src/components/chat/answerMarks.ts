// Javob matnidagi texnik belgilar - web chat va Mini App uchun UMUMIY (MarkdownMessage).
//
// 2026-10-10, foydalanuvchi skrinshoti (CRM vazifalari javobi): har band oxirida kulrang
// "T2" qutisi, `DVSIB-245` kabi kalitlar esa vazifa nomidan ko'ra ko'proq ko'zga
// tashlanardi. Qaror:
//   * `[T1]` (jonli HRM/CRM so'rovi) matnda YASHIRILADI - qaysi so'rov ekani "Manbalar"
//     tugmasida qoladi;
//   * `[1]` (hujjat iqtibosi) qoladi, lekin kichik yuqori indeks (MarkdownMessage);
//   * vazifa kaliti - kichik va xira (`.vmd-key`), vazifa nomi asosiy bo'lib qoladi.
//
// NEGA lookbehind (`(?<=...)`) yo'q: Telegram'ning eski iOS WebView'i (16.4 dan oldin)
// uni tanimaydi - regex bo'lak YUKLANGANDA SyntaxError beradi va javob umuman chizilmaydi.

/** Platforma so'rovi belgilari: `[T1]`, `[T1, T2]`, `[T1][T2]` - oldidagi bo'shliq bilan
 *  ("kech qoldi [T2]." -> "kech qoldi."). */
const TOOL_MARKS = /[  ]*\[T\d{1,3}(?:\s*[,;]\s*T?\d{1,3})*\]/g

export function stripToolMarks(text: string): string {
  return text.replace(TOOL_MARKS, '')
}

export function hasToolMarks(text: string): boolean {
  TOOL_MARKS.lastIndex = 0
  const found = TOOL_MARKS.test(text)
  TOOL_MARKS.lastIndex = 0
  return found
}

/** Vazifa kaliti: KATTA harfli loyiha kodi (2-10 belgi) + chiziqcha + raqam (`DVSIB-245`,
 *  `HR2-17`). So'z ichida (`xDVSIB-1`, `DVSIB-245a`, `A-B-12`) - kalit emas. */
const TASK_KEY = /(^|[^\p{L}\p{N}_-])([A-Z][A-Z0-9]{1,9}-\d{1,6})(?![\p{L}\p{N}_]|-\d)/gu

/** Kalitga o'xshagan, lekin vazifa kaliti BO'LMAGAN keng tarqalgan yozuvlar (`COVID-19`, `UTF-8`,
 *  `ISO-9001`, `SHA-256`, `Q3-2026`, `H1-2026`): ular xira bo'lsa javobdagi oddiy ma'lumot "texnik
 *  izoh"dek ko'rinardi. Mobil `AnswerMarkdown.tsx` bilan bir xil ro'yxat. */
const NOT_TASK_PREFIX = /^(?:COVID|SARS|UTF|ISO|IEC|SHA|MD|RFC|TLS|SSL|HTTP|MRZ|GMT|UTC|CVE|EN|GOST|[QH][1-4])$/

export function isTaskKey(key: string): boolean {
  const m = /^([A-Z][A-Z0-9]{1,9})-\d{1,6}$/.exec(key)
  return !!m && !NOT_TASK_PREFIX.test(m[1])
}

export interface TextPart {
  text: string
  key: boolean
}

/** Matnni oddiy bo'laklar va vazifa kalitlariga ajratadi (kalitsiz matn - bitta bo'lak). */
export function splitTaskKeys(text: string): TextPart[] {
  const parts: TextPart[] = []
  let last = 0
  for (const m of text.matchAll(TASK_KEY)) {
    if (!isTaskKey(m[2])) continue
    const start = (m.index ?? 0) + m[1].length
    if (start > last) parts.push({ text: text.slice(last, start), key: false })
    parts.push({ text: m[2], key: true })
    last = start + m[2].length
  }
  if (last < text.length) parts.push({ text: text.slice(last), key: false })
  return parts
}

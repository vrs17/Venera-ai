// Xabar vaqti - sichqoncha ustiga kelganda ko'rinadigan qisqa yozuv.
//
// Bugungi xabar uchun faqat soat ("14:32"), eskisi uchun kun ham ("3-sen,
// 14:32"), o'tgan yilniki uchun yil ham. To'liq sana `title` da - odam
// aniq bilmoqchi bo'lsa. Til - joriy UI tili (`Intl` o'zi tarjima qiladi).

export function formatWhen(ms: number, lang: string): string {
  const date = new Date(ms)
  const now = new Date()
  const time: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }
  const sameDay =
    date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
  if (sameDay) return safeFormat(date, lang, time)
  const sameYear = date.getFullYear() === now.getFullYear()
  return safeFormat(date, lang, { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }), ...time })
}

export function formatFull(ms: number, lang: string): string {
  return safeFormat(new Date(ms), lang, { dateStyle: 'long', timeStyle: 'short' })
}

/** Noma'lum til kodi `Intl` ni yiqitmasin - o'shanda brauzer tili. */
function safeFormat(date: Date, lang: string, options: Intl.DateTimeFormatOptions): string {
  try {
    return new Intl.DateTimeFormat(lang, options).format(date)
  } catch {
    return new Intl.DateTimeFormat(undefined, options).format(date)
  }
}

/** ISO-8601 (serverdan) -> epoch ms, buzuq bo'lsa null. */
export function isoToMs(iso: string | null | undefined): number | null {
  if (!iso) return null
  const ms = Date.parse(iso)
  return Number.isFinite(ms) ? ms : null
}

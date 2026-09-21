// Xabar vaqti - sichqoncha ustiga kelganda ko'rinadigan qisqa yozuv.
//
// Bugungi xabar uchun faqat soat ("14:32"), eskisi uchun kun ham ("3-sen,
// 14:32"), o'tgan yilniki uchun yil ham. To'liq sana `title` da - odam
// aniq bilmoqchi bo'lsa. Til - joriy UI tili (`Intl` o'zi tarjima qiladi).

// O'zbek oy nomlari QO'LDA: brauzerning `Intl` ma'lumotida o'zbek uchun oy
// nomi yo'q va u "M09 18" deb chiqaradi (jonli ko'rildi, Chrome). Sana
// o'zbekcha tartibda - kun oldin: "18-sentabr, 11:39", "18-sentabr,
// 2025-yil, 11:39". Rus va ingliz tilida `Intl` ning o'zi to'g'ri yozadi.
const UZ_MONTHS: Record<string, { months: string[]; year: string }> = {
  'uz-Latn': {
    months: ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'],
    year: 'yil',
  },
  'uz-Cyrl': {
    months: ['январ', 'феврал', 'март', 'апрел', 'май', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр'],
    year: 'йил',
  },
}

function clock(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function formatWhen(ms: number, lang: string): string {
  const date = new Date(ms)
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
  const sameYear = date.getFullYear() === now.getFullYear()
  const uz = UZ_MONTHS[lang]
  if (uz) {
    if (sameDay) return clock(date)
    const day = `${date.getDate()}-${uz.months[date.getMonth()]}`
    return sameYear ? `${day}, ${clock(date)}` : `${day}, ${date.getFullYear()}-${uz.year}, ${clock(date)}`
  }
  const time: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }
  if (sameDay) return safeFormat(date, lang, time)
  return safeFormat(date, lang, { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }), ...time })
}

export function formatFull(ms: number, lang: string): string {
  const date = new Date(ms)
  const uz = UZ_MONTHS[lang]
  if (uz) return `${date.getDate()}-${uz.months[date.getMonth()]}, ${date.getFullYear()}-${uz.year}, ${clock(date)}`
  return safeFormat(date, lang, { dateStyle: 'long', timeStyle: 'short' })
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

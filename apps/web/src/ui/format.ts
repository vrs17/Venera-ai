// Raqam, vaqt, foiz va sana formatlari - admin panel, grafiklar va jadvallar uchun bitta joy.
//
// Nega o'zimiz yozamiz: brauzerlarning `Intl` ma'lumotida o'zbek tili ko'pincha
// "kesilgan" (Chrome `uz` ni qo'llab-quvvatlayman deydi, lekin oy nomi o'rniga
// "M09 18", kasr ajratgichi o'rniga nuqta chiqaradi). Shuning uchun o'zbekcha oy
// nomlari va "5 daq oldin" jadvali QO'LDA, raqam guruhlash esa tekshiruvdan
// (probe) keyin - kerak bo'lsa rus qolipiga (bir xil: "1 234,5") qaytadi.
// Natija hamma brauzerda bir xil.

export type AppLocale = 'uz' | 'uz-Cyrl' | 'ru' | 'en'
export type DateInput = Date | string | number | null | undefined

/** Ilova tili -> Intl tegi. */
const INTL_TAG: Record<AppLocale, string> = {
  uz: 'uz-Latn-UZ',
  'uz-Cyrl': 'uz-Cyrl-UZ',
  ru: 'ru-RU',
  en: 'en-GB',
}

const DASH = '—'
const NBSP = ' '
// O'zbekcha sanadagi chiziqcha - U+2011 (uzilmas defis), oddiy "-" emas: Inter'da
// `tabular-nums` oddiy defisni raqam kengligiga cho'zadi ("29 - sen" bo'lib qoladi),
// U+2011 esa tor qoladi; ustiga "29-" / "sen" ikki qatorga bo'linib ketmaydi.
const NBHY = '‑'

/** Har qanday til kodini ('uz-Latn', 'ru-RU', i18n.locale) ilovaning 4 tilidan biriga keltiradi. */
export function toAppLocale(locale?: string | null): AppLocale {
  const l = (locale ?? '').toLowerCase()
  if (l.startsWith('uz')) return l.includes('cyrl') ? 'uz-Cyrl' : 'uz'
  if (l.startsWith('ru')) return 'ru'
  return 'en'
}

const supportCache = new Map<string, boolean>()
function supported(tag: string): boolean {
  let ok = supportCache.get(tag)
  if (ok === undefined) {
    try {
      ok = Intl.DateTimeFormat.supportedLocalesOf([tag]).length > 0
    } catch {
      ok = false
    }
    supportCache.set(tag, ok)
  }
  return ok
}

/** Ilova tili uchun Intl tegi; brauzer bilmasa - en-GB (24 soat, kun oldin). */
export function intlLocale(locale?: string | null): string {
  const tag = INTL_TAG[toAppLocale(locale)]
  return supported(tag) ? tag : 'en-GB'
}

function isUz(app: AppLocale): boolean {
  return app === 'uz' || app === 'uz-Cyrl'
}

// Raqam uchun teg: o'zbekchada Intl haqiqatan "1 234,5" beradimi - bir marta tekshiramiz.
let uzNumberTag: string | null = null
function numberTag(app: AppLocale): string {
  if (!isUz(app)) return intlLocale(app)
  if (uzNumberTag === null) {
    try {
      const probe = new Intl.NumberFormat(INTL_TAG.uz).format(1234.5)
      uzNumberTag = /,5$/.test(probe) && !probe.includes('.') ? INTL_TAG.uz : 'ru-RU'
    } catch {
      uzNumberTag = 'ru-RU'
    }
  }
  return uzNumberTag
}

const nfCache = new Map<string, Intl.NumberFormat>()
function nf(tag: string, opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = tag + JSON.stringify(opts)
  let f = nfCache.get(key)
  if (!f) {
    f = new Intl.NumberFormat(tag, opts)
    nfCache.set(key, f)
  }
  return f
}

function finite(n: number | null | undefined): n is number {
  return typeof n === 'number' && Number.isFinite(n)
}

/* ------------------------------------------------------------------ raqamlar */

export interface NumberOptions {
  /** Kasr qismi uchun eng ko'p raqam. Berilmasa - kattalikka qarab (12.34 / 123.4 / 1 234). */
  digits?: number
  /** Kasr qismi uchun eng kam raqam (masalan jadval ustunida "1.0"). */
  minDigits?: number
  /** Musbatga ham "+" qo'yish (farqlar uchun). */
  signed?: boolean
}

function autoDigits(n: number): number {
  if (Number.isInteger(n)) return 0
  const a = Math.abs(n)
  return a < 10 ? 2 : a < 100 ? 1 : 0
}

/** Guruhlangan raqam: uz/ru "1 234,5", en "1,234.5". Bo'sh qiymat -> "—". */
export function fmtNumber(n: number | null | undefined, locale?: string | null, opts: NumberOptions = {}): string {
  if (!finite(n)) return DASH
  const digits = opts.digits ?? autoDigits(n)
  return nf(numberTag(toAppLocale(locale)), {
    maximumFractionDigits: digits,
    minimumFractionDigits: Math.min(opts.minDigits ?? 0, digits),
    signDisplay: opts.signed ? 'exceptZero' : 'auto',
  }).format(n)
}

const COMPACT: Record<AppLocale, { sep: string; units: string[] }> = {
  en: { sep: '', units: ['K', 'M', 'B', 'T'] },
  ru: { sep: NBSP, units: ['тыс.', 'млн', 'млрд', 'трлн'] },
  uz: { sep: NBSP, units: ['ming', 'mln', 'mlrd', 'trln'] },
  'uz-Cyrl': { sep: NBSP, units: ['минг', 'млн', 'млрд', 'трлн'] },
}

/** Ixcham raqam: 1.2K / 3.4M (uz: "1,2 ming", ru: "1,2 тыс."). Til berilmasa - K/M/B. */
export function fmtCompact(n: number | null | undefined, locale?: string | null): string {
  if (!finite(n)) return DASH
  const a = Math.abs(n)
  if (a < 1000) return fmtNumber(n, locale ?? 'en', { digits: a < 10 && !Number.isInteger(n) ? 1 : 0 })
  const app = locale ? toAppLocale(locale) : 'en'
  const spec = COMPACT[app]
  // log10 ga ishonmaymiz: Math.log10(1000) ba'zan 2.9999... chiqadi.
  let unit = 1
  while (unit < spec.units.length && a >= 10 ** ((unit + 1) * 3)) unit += 1
  let v = a / 10 ** (unit * 3)
  // 999 950 -> "1000K" bo'lmasin: yaxlitlangach 1000 ga yetsa keyingi birlikka o'tamiz.
  const digits = () => (v < 10 ? 1 : 0)
  if (Number(v.toFixed(digits())) >= 1000 && unit < spec.units.length) {
    unit += 1
    v = a / 10 ** (unit * 3)
  }
  const body = fmtNumber(Math.sign(n) * v, app, { digits: digits() })
  return `${body}${spec.sep}${spec.units[unit - 1]}`
}

/** Ulush (0.123) -> "12.3%" (ru: "12,3 %"). `digits` - kasr qismi, oxirgi nollar tashlanadi. */
export function fmtPercent(x: number | null | undefined, digits = 1, locale?: string | null, signed = false): string {
  if (!finite(x)) return DASH
  const app = toAppLocale(locale ?? 'en')
  if (isUz(app)) {
    // CLDR uz: "12,3%" (bo'shliqsiz); Intl ma'lumoti kesilgan bo'lsa ham bir xil chiqsin.
    return `${fmtNumber(x * 100, app, { digits, signed })}%`
  }
  return nf(intlLocale(app), {
    style: 'percent',
    maximumFractionDigits: digits,
    signDisplay: signed ? 'exceptZero' : 'auto',
  }).format(x)
}

/**
 * Davomiylik: "840 ms", "4.2 ms", "1.2 s", "12 s", "2 min 5 s", "1 h 5 min".
 * Birliklar SI belgilari - hamma tilda bir xil (texnik kontekst); kasr ajratgichi tilga qarab.
 */
export function fmtMs(ms: number | null | undefined, locale?: string | null): string {
  if (!finite(ms)) return DASH
  if (ms < 0) return `-${fmtMs(-ms, locale)}`
  const loc = locale ?? 'en'
  if (ms === 0) return `0${NBSP}ms`
  if (ms < 1) return `<1${NBSP}ms`
  if (Math.round(ms) < 1000) {
    return `${fmtNumber(ms, loc, { digits: ms < 10 ? 1 : 0 })}${NBSP}ms`
  }
  const s = ms / 1000
  if (s < 10 && Number(s.toFixed(1)) < 10) return `${fmtNumber(s, loc, { digits: 1 })}${NBSP}s`
  if (Math.round(s) < 60) return `${fmtNumber(Math.round(s), loc)}${NBSP}s`
  const totalS = Math.round(s)
  if (totalS < 3600) {
    const m = Math.floor(totalS / 60)
    const rest = totalS % 60
    return m < 10 && rest > 0 ? `${m}${NBSP}min ${rest}${NBSP}s` : `${m}${NBSP}min`
  }
  const totalM = Math.round(totalS / 60)
  const h = Math.floor(totalM / 60)
  const rest = totalM % 60
  return rest > 0 ? `${h}${NBSP}h ${rest}${NBSP}min` : `${h}${NBSP}h`
}

/* ------------------------------------------------------------------ sanalar */

/** Server ISO satri, epoch ms yoki Date -> Date; buzuq bo'lsa null. */
export function toDate(v: DateInput): Date | null {
  if (v === null || v === undefined || v === '') return null
  const d = v instanceof Date ? v : new Date(v)
  return Number.isFinite(d.getTime()) ? d : null
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** Mahalliy kun: "2026-09-29" (URL filtri `?from=&to=` shu shaklda). */
export function toISODate(v: DateInput): string {
  const d = toDate(v)
  if (!d) return ''
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

/** "2026-09-29" -> shu kunning mahalliy yarim tuni; noto'g'ri satr -> null. */
export function fromISODate(s: string | null | undefined): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s ?? '')
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  // 2026-02-31 kabi sanalar JS da keyingi oyga "oqib" ketadi - ularni rad etamiz.
  return d.getMonth() === Number(m[2]) - 1 ? d : null
}

export function startOfDay(v: Date): Date {
  return new Date(v.getFullYear(), v.getMonth(), v.getDate())
}

export function endOfDay(v: Date): Date {
  return new Date(v.getFullYear(), v.getMonth(), v.getDate(), 23, 59, 59, 999)
}

export function startOfMonth(v: Date): Date {
  return new Date(v.getFullYear(), v.getMonth(), 1)
}

export function addDays(v: Date, n: number): Date {
  const d = new Date(v)
  d.setDate(d.getDate() + n)
  return d
}

/** Kalendar kunlari farqi (a - b); soat mintaqasi o'zgarishida ham butun son. */
export function diffDays(a: Date, b: Date): number {
  return Math.round((startOfDay(a).getTime() - startOfDay(b).getTime()) / 86_400_000)
}

export function isSameDay(a: Date, b: Date): boolean {
  return diffDays(a, b) === 0
}

const UZ_MONTHS: Record<'uz' | 'uz-Cyrl', { long: string[]; short: string[]; year: string }> = {
  uz: {
    long: ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'],
    short: ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'],
    year: 'yil',
  },
  'uz-Cyrl': {
    long: ['январ', 'феврал', 'март', 'апрел', 'май', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр'],
    short: ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'],
    year: 'йил',
  },
}

const dfCache = new Map<string, Intl.DateTimeFormat>()
function df(tag: string, opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = tag + JSON.stringify(opts)
  let f = dfCache.get(key)
  if (!f) {
    f = new Intl.DateTimeFormat(tag, opts)
    dfCache.set(key, f)
  }
  return f
}

/** "14:32" (yoki "14:32:05"). 24 soatlik - hamma tilda. */
export function fmtTime(v: DateInput, seconds = false): string {
  const d = toDate(v)
  if (!d) return DASH
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  return seconds ? `${hm}:${pad2(d.getSeconds())}` : hm
}

export interface DateOptions {
  month?: 'short' | 'long'
  /** 'auto' - faqat joriy yildan boshqa bo'lsa. */
  year?: 'auto' | 'always' | 'never'
}

/** Kun + oy: uz "18-sen", uz-Cyrl "18-сен", ru "18 сент.", en "18 Sept". */
export function fmtDate(v: DateInput, locale?: string | null, opts: DateOptions = {}): string {
  const d = toDate(v)
  if (!d) return DASH
  const app = toAppLocale(locale)
  const month = opts.month ?? 'short'
  const yearMode = opts.year ?? 'auto'
  const withYear = yearMode === 'always' || (yearMode === 'auto' && d.getFullYear() !== new Date().getFullYear())
  if (app === 'uz' || app === 'uz-Cyrl') {
    const t = UZ_MONTHS[app]
    const day = `${d.getDate()}${NBHY}${t[month][d.getMonth()]}`
    if (!withYear) return day
    return month === 'long' ? `${day}, ${d.getFullYear()}${NBHY}${t.year}` : `${day}, ${d.getFullYear()}`
  }
  return df(intlLocale(app), { day: 'numeric', month, ...(withYear ? { year: 'numeric' } : {}) }).format(d)
}

export type DateTimeStyle = 'short' | 'medium' | 'long'

/**
 * Sana + vaqt.
 * - short: bugun "14:32", shu yil "18-sen, 14:32", eski "18-sen, 2025" (jadval ustuni)
 * - medium: doim kun va soat, "18-sen, 14:32"
 * - long: "18-sentabr, 2026-yil, 14:32" (sarlavha, tooltip)
 */
export function fmtDateTime(v: DateInput, locale?: string | null, style: DateTimeStyle = 'short'): string {
  const d = toDate(v)
  if (!d) return DASH
  const app = toAppLocale(locale)
  const now = new Date()
  if (style === 'short') {
    if (isSameDay(d, now)) return fmtTime(d)
    if (d.getFullYear() !== now.getFullYear()) return fmtDate(d, app, { year: 'always' })
    return `${fmtDate(d, app, { year: 'never' })}, ${fmtTime(d)}`
  }
  if (style === 'medium') return `${fmtDate(d, app)}, ${fmtTime(d)}`
  if (app === 'uz' || app === 'uz-Cyrl') return `${fmtDate(d, app, { month: 'long', year: 'always' })}, ${fmtTime(d)}`
  return df(intlLocale(app), { dateStyle: 'long', timeStyle: 'short', hourCycle: 'h23' }).format(d)
}

/* ------------------------------------------------------------------ nisbiy vaqt */

type RelUnit = 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month' | 'year'

const UZ_REL: Record<
  'uz' | 'uz-Cyrl',
  {
    now: string
    yesterday: string
    tomorrow: string
    ago: string
    after: string
    from: string
    long: Record<RelUnit, string>
    short: Record<RelUnit, string>
  }
> = {
  uz: {
    now: 'hozirgina',
    yesterday: 'kecha',
    tomorrow: 'ertaga',
    ago: 'oldin',
    after: 'keyin',
    from: 'dan',
    long: { second: 'soniya', minute: 'daqiqa', hour: 'soat', day: 'kun', week: 'hafta', month: 'oy', year: 'yil' },
    short: { second: 'son', minute: 'daq', hour: 'soat', day: 'kun', week: 'hafta', month: 'oy', year: 'yil' },
  },
  'uz-Cyrl': {
    now: 'ҳозиргина',
    yesterday: 'кеча',
    tomorrow: 'эртага',
    ago: 'олдин',
    after: 'кейин',
    from: 'дан',
    long: { second: 'сония', minute: 'дақиқа', hour: 'соат', day: 'кун', week: 'ҳафта', month: 'ой', year: 'йил' },
    short: { second: 'сон', minute: 'дақ', hour: 'соат', day: 'кун', week: 'ҳафта', month: 'ой', year: 'йил' },
  },
}

const JUST_NOW: Record<'ru' | 'en', string> = { ru: 'только что', en: 'just now' }

export interface RelativeOptions {
  /** Hisob nuqtasi (sinov va jonli yangilanish uchun). Standart - hozir. */
  now?: DateInput
  /** 'short' - "5 daq oldin" (jadval), 'long' - "5 daqiqa oldin". */
  style?: 'short' | 'long'
}

/** "5 daq oldin", "kecha", "3 soat oldin" / "5 мин. назад" / "5 min ago". */
export function fmtRelative(v: DateInput, locale?: string | null, opts: RelativeOptions = {}): string {
  const d = toDate(v)
  if (!d) return DASH
  const now = toDate(opts.now) ?? new Date()
  const app = toAppLocale(locale)
  const style = opts.style ?? 'short'
  const diffS = (now.getTime() - d.getTime()) / 1000 // musbat = o'tmish
  const abs = Math.abs(diffS)
  const past = diffS >= 0

  let unit: RelUnit
  let n: number
  const days = Math.abs(diffDays(now, d))
  if (abs < 45) {
    return isUz(app) ? UZ_REL[app as 'uz' | 'uz-Cyrl'].now : JUST_NOW[app as 'ru' | 'en']
  } else if (abs < 45 * 60) {
    unit = 'minute'
    n = Math.max(1, Math.round(abs / 60))
  } else if (abs < 22 * 3600 || days === 0) {
    unit = 'hour'
    n = Math.max(1, Math.round(abs / 3600))
  } else if (days < 7) {
    unit = 'day'
    n = Math.max(1, days)
  } else if (days < 30) {
    unit = 'week'
    n = Math.round(days / 7)
  } else if (days < 365) {
    unit = 'month'
    n = Math.max(1, Math.round(days / 30.44))
  } else {
    unit = 'year'
    n = Math.max(1, Math.round(days / 365.25))
  }

  if (isUz(app)) {
    const t = UZ_REL[app as 'uz' | 'uz-Cyrl']
    if (unit === 'day' && n === 1) return past ? t.yesterday : t.tomorrow
    // Kelasi zamon qisqartmasiz: "5 daqiqadan keyin" - "5 daqdan" g'alati o'qiladi.
    return past ? `${n} ${t[style][unit]} ${t.ago}` : `${n} ${t.long[unit]}${t.from} ${t.after}`
  }
  try {
    return new Intl.RelativeTimeFormat(intlLocale(app), { numeric: 'auto', style }).format(past ? -n : n, unit)
  } catch {
    return new Intl.RelativeTimeFormat('en-GB', { numeric: 'auto', style }).format(past ? -n : n, unit)
  }
}

// Grafiklar matematikasi: shkalalar, "chiroyli" belgilar (1-2-5), vaqt belgilar,
// yaqin nuqtani topish, SVG yo'llar va matn o'lchash. Kutubxona yo'q - hammasi shu
// yerda, chunki bizga 6 ta grafik turi kerak, 60 KB lik d3 emas.
//
// Hamma funksiya "sof": piksel kiradi, piksel/satr chiqadi. Vue ga bog'liq qism
// faqat pastdagi `useElementSize` va `fontEpoch` (shrift yuklangach qayta o'lchash).

import { getCurrentScope, onScopeDispose, ref, watch, type Ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

/* ------------------------------------------------------------------ turlar */

/** Chiziq/maydon grafigi uchun qator. `color` - CSS o'zgaruvchi nomi ('--ch-web') yoki var(). */
export interface ChartSeries {
  key: string
  label: string
  color?: string
  values: (number | null)[]
  /** Ma'lumot emas, mo'ljal (maqsad, chegara): uzuq chiziq, stekka qo'shilmaydi. */
  reference?: boolean
}

export type ChartX = string | number | Date
export type ChartView = 'chart' | 'table'
export type MarkKind = 'line' | 'dashed' | 'rect' | 'dot' | 'none'

export interface TooltipRow {
  key: string
  label: string
  value: string
  color?: string
  mark?: MarkKind
}

export interface LegendItem {
  key: string
  label: string
  color?: string
  mark?: MarkKind
  /** Ro'yxat ko'rinishida qiymat va ulush (VStackedBar). */
  value?: string
  share?: string
  hidden?: boolean
}

export interface BarDatum {
  key: string
  label: string
  value: number | null
  color?: string
  /** Tooltipda qiymat ostidagi qo'shimcha satr (masalan ulush). */
  sub?: string
  /** Gorizontal ro'yxatda qator havola bo'lsin. */
  to?: RouteLocationRaw
}

export interface StackPart {
  key: string
  label: string
  value: number
  color?: string
}

export interface ChartTableColumn {
  key: string
  label: string
  align?: 'start' | 'end'
}

/** VLineChart va VAreaChart ning umumiy API si. */
export interface XYChartProps {
  series: ChartSeries[]
  /** ISO satrlar, epoch ms yoki Date - vaqt shkalasi; boshqa satrlar - toifa. */
  x: ChartX[]
  /** Umumiy balandlik (x o'qi bilan birga), px. */
  height?: number
  curve?: 'linear' | 'monotone'
  /** Qiymat formati: tooltip, jadval, oxirgi yorliq. Standart - guruhlangan raqam. */
  yFormat?: (v: number) => string
  /** Y o'qi belgilari. Standart - yFormat, u ham bo'lmasa ixcham (1.2K). */
  yTickFormat?: (v: number) => string
  /** X o'qi belgilari. */
  xFormat?: (d: Date) => string
  /** Tooltip va jadval sarlavhasi (x qiymati). */
  xTitleFormat?: (d: Date) => string
  yMin?: number
  yMax?: number
  /** Qayta yuklanmoqda: kadr saqlanadi, 50% xira. */
  loading?: boolean
  /** Ekran o'quvchi uchun nom (sarlavha odatda kartada). */
  label?: string
  hideLegend?: boolean
  endLabels?: boolean
  tableToggle?: boolean
}

/* ------------------------------------------------------------------ rang */

/** '--viz-1' -> 'var(--viz-1)'; 'var(...)' va boshqalar o'zgarmaydi. */
export function cssColor(c: string | undefined | null, fallback = '--viz-1'): string {
  const v = c || fallback
  return v.startsWith('--') ? `var(${v})` : v
}

/* ------------------------------------------------------------------ chiziqli shkala */

export interface LinearScale {
  (v: number): number
  domain: [number, number]
  range: [number, number]
  invert(px: number): number
}

export function linearScale(domain: [number, number], range: [number, number]): LinearScale {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0 || 1
  const f = ((v: number) => r0 + ((v - d0) / span) * (r1 - r0)) as LinearScale
  f.domain = domain
  f.range = range
  f.invert = (px: number) => d0 + ((px - r0) / (r1 - r0 || 1)) * span
  return f
}

/** 1-2-5 qadam: span ni ~count bo'lakka bo'luvchi eng yaqin "yumaloq" son. */
export function niceStep(span: number, count: number): number {
  const raw = Math.abs(span) / Math.max(1, count)
  if (!Number.isFinite(raw) || raw === 0) return 1
  const p = 10 ** Math.floor(Math.log10(raw))
  const f = raw / p
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p
}

function decimalsOf(step: number): number {
  return Math.max(0, -Math.floor(Math.log10(step) + 1e-9))
}

export interface NiceTicks {
  min: number
  max: number
  step: number
  ticks: number[]
}

/** Chegaralarni yumaloqlab kengaytiradi va shu qadamdagi belgilarni qaytaradi. */
export function niceTicks(min: number, max: number, count = 5): NiceTicks {
  let lo = Number.isFinite(min) ? min : 0
  let hi = Number.isFinite(max) ? max : 1
  if (lo > hi) [lo, hi] = [hi, lo]
  if (lo === hi) {
    // Tekis qator: o'rtada chiziq ko'rinsin, bitta nuqtali o'q bo'lmasin.
    if (hi === 0) hi = 1
    else if (hi > 0) lo = Math.min(0, lo)
    else hi = 0
  }
  const step = niceStep(hi - lo, count)
  const dec = decimalsOf(step)
  const nMin = Math.floor(lo / step + 1e-9) * step
  const nMax = Math.ceil(hi / step - 1e-9) * step
  const ticks: number[] = []
  for (let v = nMin, i = 0; v <= nMax + step / 2 && i < 100; v += step, i++) {
    ticks.push(Number(v.toFixed(dec)))
  }
  return { min: ticks[0], max: ticks[ticks.length - 1], step, ticks }
}

/* ------------------------------------------------------------------ vaqt */

export const MINUTE = 60_000
export const HOUR = 3_600_000
export const DAY = 86_400_000

export type TimeUnit = 'minute' | 'hour' | 'day' | 'week' | 'month' | 'year'

interface TimeStep {
  unit: TimeUnit
  n: number
  ms: number
}

const TIME_STEPS: TimeStep[] = [
  { unit: 'minute', n: 1, ms: MINUTE },
  { unit: 'minute', n: 5, ms: 5 * MINUTE },
  { unit: 'minute', n: 15, ms: 15 * MINUTE },
  { unit: 'minute', n: 30, ms: 30 * MINUTE },
  { unit: 'hour', n: 1, ms: HOUR },
  { unit: 'hour', n: 2, ms: 2 * HOUR },
  { unit: 'hour', n: 3, ms: 3 * HOUR },
  { unit: 'hour', n: 6, ms: 6 * HOUR },
  { unit: 'hour', n: 12, ms: 12 * HOUR },
  { unit: 'day', n: 1, ms: DAY },
  { unit: 'day', n: 2, ms: 2 * DAY },
  { unit: 'week', n: 1, ms: 7 * DAY },
  { unit: 'week', n: 2, ms: 14 * DAY },
  { unit: 'month', n: 1, ms: 30 * DAY },
  { unit: 'month', n: 3, ms: 91 * DAY },
  { unit: 'month', n: 6, ms: 182 * DAY },
  { unit: 'year', n: 1, ms: 365 * DAY },
]

function floorTo(t: number, step: TimeStep): Date {
  const d = new Date(t)
  switch (step.unit) {
    case 'minute':
      d.setSeconds(0, 0)
      d.setMinutes(d.getMinutes() - (d.getMinutes() % step.n))
      break
    case 'hour':
      d.setMinutes(0, 0, 0)
      d.setHours(d.getHours() - (d.getHours() % step.n))
      break
    case 'day':
      d.setHours(0, 0, 0, 0)
      break
    case 'week':
      // Hafta dushanbadan boshlanadi (O'zbekiston, Rossiya, Yevropa).
      d.setHours(0, 0, 0, 0)
      d.setDate(d.getDate() - ((d.getDay() + 6) % 7))
      break
    case 'month':
      d.setHours(0, 0, 0, 0)
      d.setDate(1)
      d.setMonth(d.getMonth() - (d.getMonth() % step.n))
      break
    case 'year':
      d.setHours(0, 0, 0, 0)
      d.setMonth(0, 1)
      break
  }
  return d
}

function advance(d: Date, step: TimeStep): Date {
  const n = new Date(d)
  switch (step.unit) {
    case 'minute':
      n.setMinutes(n.getMinutes() + step.n)
      break
    case 'hour':
      n.setHours(n.getHours() + step.n)
      break
    case 'day':
      n.setDate(n.getDate() + step.n)
      break
    case 'week':
      n.setDate(n.getDate() + 7 * step.n)
      break
    case 'month':
      n.setMonth(n.getMonth() + step.n)
      break
    case 'year':
      n.setFullYear(n.getFullYear() + step.n)
      break
  }
  return n
}

export interface TimeTicks {
  ticks: Date[]
  unit: TimeUnit
  stepMs: number
}

/** Mahalliy chegaralarga (soat boshi, yarim tun, dushanba, oy boshi) tekislangan belgilar. */
export function timeTicks(start: number, end: number, maxCount = 6): TimeTicks {
  const span = Math.max(1, end - start)
  const limit = Math.max(1, maxCount)
  let idx = TIME_STEPS.findIndex((s) => span / s.ms <= limit)
  if (idx < 0) idx = TIME_STEPS.length - 1
  const build = (step: TimeStep): Date[] => {
    const out: Date[] = []
    let d = floorTo(start, step)
    if (d.getTime() < start) d = advance(d, step)
    for (let i = 0; d.getTime() <= end && i < 500; i++) {
      out.push(d)
      d = advance(d, step)
    }
    return out
  }
  let ticks = build(TIME_STEPS[idx])
  // Tor grafikda (1/3 karta) qadam kattalashib oy/hafta bo'ladi va kalendar chegarasi
  // oraliqqa BIR marta tushadi: 30 kunda faqat "1-sen", 7 kunda faqat dushanba. Bitta
  // yozuvdan vaqt yo'nalishi o'qilmaydi - kamida ikkitasi chiqquncha maydaroq qadamga
  // tushamiz (ortiqchasini grafik o'zi to'qnashuv bo'yicha tashlaydi).
  while (ticks.length < 2 && limit >= 2 && idx > 0) {
    idx -= 1
    ticks = build(TIME_STEPS[idx])
  }
  const step = TIME_STEPS[idx]
  return { ticks, unit: step.unit, stepMs: step.ms }
}

/** Qator bir xil qadamli bo'lsa qadamni (ms) qaytaradi; soat mintaqasi siljishiga 1 soat ruxsat. */
export function regularStep(times: number[]): number | null {
  if (times.length < 2) return null
  const step = times[1] - times[0]
  if (step <= 0) return null
  const tol = step >= DAY ? HOUR : step * 0.01
  for (let i = 2; i < times.length; i++) {
    if (Math.abs(times[i] - times[i - 1] - step) > tol) return null
  }
  return step
}

/**
 * Bir xil qadamli qatorda belgilar ma'lumot nuqtalarining o'zida bo'lsin (kunlik
 * nuqta 05:00 da, belgi 00:00 da turib qolmasin). Oxiridan sanaymiz - eng yangi
 * nuqta doim yozuvli.
 */
export function indexTicks(n: number, maxCount: number, stepMs: number | null): number[] {
  if (n <= 0) return []
  const mults =
    stepMs !== null && stepMs >= DAY * 0.9
      ? [1, 2, 7, 14, 28, 56, 91, 182, 364]
      : stepMs !== null && stepMs >= HOUR * 0.9
        ? [1, 2, 3, 6, 12, 24, 48, 72, 168]
        : [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
  const k = mults.find((m) => Math.ceil(n / m) <= Math.max(1, maxCount)) ?? Math.ceil(n / Math.max(1, maxCount))
  const out: number[] = []
  for (let i = n - 1; i >= 0; i -= k) out.unshift(i)
  return out
}

/** Tartiblangan massivda `x` ga eng yaqin element indeksi. */
export function bisect(sorted: number[], x: number): number {
  const n = sorted.length
  if (n === 0) return -1
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (sorted[mid] <= x) lo = mid
    else hi = mid
  }
  return Math.abs(sorted[lo] - x) <= Math.abs(sorted[hi] - x) ? lo : hi
}

/** x qiymatlari hammasi sana bo'lsa - ms massivi, aks holda null (toifa shkalasi). */
export function parseTimes(xs: ChartX[]): number[] | null {
  if (xs.length === 0) return null
  const out: number[] = []
  for (const v of xs) {
    let t: number
    if (v instanceof Date) t = v.getTime()
    else if (typeof v === 'number') t = v
    else if (/^\d{4}-\d{2}-\d{2}/.test(v)) t = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(v) ? `${v}T00:00:00` : v)
    else return null
    if (!Number.isFinite(t)) return null
    out.push(t)
  }
  return out
}

/* ------------------------------------------------------------------ SVG yo'llar */

export interface Pt {
  x: number
  y: number
}

interface Seg {
  p0: Pt
  c1: Pt
  c2: Pt
  p1: Pt
}

const r2 = (v: number) => Math.round(v * 100) / 100

/**
 * Monoton kub egri (Fritsch-Carlson, d3 `curveMonotoneX` bilan bir xil): silliq,
 * lekin hech qachon ma'lumotdan oshib ketmaydi - 0 dan pastga "sho'ng'imaydi".
 */
function monotoneSegs(pts: Pt[]): Seg[] {
  const n = pts.length
  if (n < 2) return []
  if (n === 2) {
    const [a, b] = pts
    return [{ p0: a, c1: { x: a.x + (b.x - a.x) / 3, y: a.y + (b.y - a.y) / 3 }, c2: { x: b.x - (b.x - a.x) / 3, y: b.y - (b.y - a.y) / 3 }, p1: b }]
  }
  const m = new Array<number>(n)
  const sign = (v: number) => (v < 0 ? -1 : 1)
  for (let i = 1; i < n - 1; i++) {
    const h0 = pts[i].x - pts[i - 1].x
    const h1 = pts[i + 1].x - pts[i].x
    const s0 = h0 ? (pts[i].y - pts[i - 1].y) / h0 : 0
    const s1 = h1 ? (pts[i + 1].y - pts[i].y) / h1 : 0
    const p = (s0 * h1 + s1 * h0) / (h0 + h1 || 1)
    m[i] = (sign(s0) + sign(s1)) * Math.min(Math.abs(s0), Math.abs(s1), 0.5 * Math.abs(p)) || 0
  }
  const end = (a: Pt, b: Pt, t: number) => {
    const h = b.x - a.x
    return h ? (3 * (b.y - a.y) / h - t) / 2 : t
  }
  m[0] = end(pts[0], pts[1], m[1])
  m[n - 1] = end(pts[n - 2], pts[n - 1], m[n - 2])
  const segs: Seg[] = []
  for (let i = 0; i < n - 1; i++) {
    const a = pts[i]
    const b = pts[i + 1]
    const dx = (b.x - a.x) / 3
    segs.push({ p0: a, c1: { x: a.x + dx, y: a.y + dx * m[i] }, c2: { x: b.x - dx, y: b.y - dx * m[i + 1] }, p1: b })
  }
  return segs
}

function segsToPath(segs: Seg[], reverse: boolean): string {
  let d = ''
  const list = reverse ? [...segs].reverse() : segs
  for (const s of list) {
    const [c1, c2, p] = reverse ? [s.c2, s.c1, s.p0] : [s.c1, s.c2, s.p1]
    d += `C${r2(c1.x)},${r2(c1.y)} ${r2(c2.x)},${r2(c2.y)} ${r2(p.x)},${r2(p.y)}`
  }
  return d
}

function runPath(pts: Pt[], curve: 'linear' | 'monotone', reverse = false): string {
  const list = reverse ? [...pts].reverse() : pts
  if (curve === 'monotone' && pts.length > 2) return segsToPath(monotoneSegs(pts), reverse)
  return list.slice(1).map((p) => `L${r2(p.x)},${r2(p.y)}`).join('')
}

/** Uzilishlar (null) bo'yicha bo'laklarga ajratish. */
export function splitRuns(pts: (Pt | null)[]): Pt[][] {
  const runs: Pt[][] = []
  let cur: Pt[] = []
  for (const p of pts) {
    if (p) cur.push(p)
    else if (cur.length) {
      runs.push(cur)
      cur = []
    }
  }
  if (cur.length) runs.push(cur)
  return runs
}

/** Chiziq yo'li; null - uzilish (yolg'iz nuqta alohida belgi bilan chiziladi). */
export function linePath(pts: (Pt | null)[], curve: 'linear' | 'monotone' = 'monotone'): string {
  return splitRuns(pts)
    .filter((run) => run.length > 1)
    .map((run) => `M${r2(run[0].x)},${r2(run[0].y)}${runPath(run, curve)}`)
    .join('')
}

/** Maydon: yuqori chegara oldinga, pastki chegara (stekda oldingi qator) orqaga. */
export function areaPath(top: Pt[], bottom: Pt[], curve: 'linear' | 'monotone' = 'monotone'): string {
  if (top.length < 2 || bottom.length !== top.length) return ''
  const last = bottom[bottom.length - 1]
  return (
    `M${r2(top[0].x)},${r2(top[0].y)}${runPath(top, curve)}` +
    `L${r2(last.x)},${r2(last.y)}${runPath(bottom, curve, true)}Z`
  )
}

/**
 * Ustun: ma'lumot uchi 4px yumaloq, asos (baseline) to'g'ri burchak.
 * `dir` - ustun qaysi tomonga o'sadi.
 */
export function barPath(x: number, y: number, w: number, h: number, r: number, dir: 'up' | 'down' | 'right'): string {
  if (w <= 0 || h <= 0) return ''
  const rr = Math.max(0, Math.min(r, dir === 'right' ? h / 2 : w / 2, dir === 'right' ? w : h))
  const X = r2(x)
  const Y = r2(y)
  if (dir === 'up') {
    return `M${X},${r2(y + h)}V${r2(y + rr)}A${rr},${rr} 0 0 1 ${r2(x + rr)},${Y}H${r2(x + w - rr)}A${rr},${rr} 0 0 1 ${r2(x + w)},${r2(y + rr)}V${r2(y + h)}Z`
  }
  if (dir === 'down') {
    return `M${X},${Y}V${r2(y + h - rr)}A${rr},${rr} 0 0 0 ${r2(x + rr)},${r2(y + h)}H${r2(x + w - rr)}A${rr},${rr} 0 0 0 ${r2(x + w)},${r2(y + h - rr)}V${Y}Z`
  }
  return `M${X},${Y}H${r2(x + w - rr)}A${rr},${rr} 0 0 1 ${r2(x + w)},${r2(y + rr)}V${r2(y + h - rr)}A${rr},${rr} 0 0 1 ${r2(x + w - rr)},${r2(y + h)}H${X}Z`
}

/* ------------------------------------------------------------------ matn o'lchash */

/** Grafik yozuvlari shrifti: caption 12/500 (tokens.css bilan bir xil). */
export const LABEL_FONT = `500 12px 'Inter Variable', 'Inter', ui-sans-serif, system-ui, sans-serif`

/** Shrift yuklangach +1 bo'ladi - o'lchovlarga bog'liq computed lar qayta hisoblanadi. */
export const fontEpoch = ref(0)
function bumpFonts() {
  measureCache.clear()
  fontEpoch.value += 1
}
if (typeof document !== 'undefined' && document.fonts) void document.fonts.ready.then(bumpFonts)

// Keyinroq yuklanadigan shriftlar (masalan, mono faqat trace ochilganda) uchun
// `loadingdone` tinglovchisi. U faqat sahifada kamida bitta grafik bor paytda ulanadi
// (hisoblagich `useElementSize` ichida) - grafiksiz sahifada global tinglovchi yo'q.
let fontUsers = 0
function watchFonts(): () => void {
  const fonts = typeof document !== 'undefined' ? document.fonts : undefined
  if (!fonts?.addEventListener) return () => {}
  if (fontUsers++ === 0) fonts.addEventListener('loadingdone', bumpFonts)
  let done = false
  return () => {
    if (done) return
    done = true
    if (--fontUsers === 0) fonts.removeEventListener('loadingdone', bumpFonts)
  }
}

const measureCache = new Map<string, number>()
let ctx: CanvasRenderingContext2D | null | undefined

/** Matn kengligi (px). Canvas yo'q muhitda - taxminiy (belgi boshiga 6.6px). */
export function measureText(text: string, font = LABEL_FONT): number {
  const key = font + '\u0000' + text
  const hit = measureCache.get(key)
  if (hit !== undefined) return hit
  if (ctx === undefined) {
    try {
      ctx = typeof document !== 'undefined' ? document.createElement('canvas').getContext('2d') : null
    } catch {
      ctx = null
    }
  }
  let w: number
  if (ctx) {
    ctx.font = font
    // tabular-nums raqamlari biroz kengroq - 4% zaxira.
    w = Math.ceil(ctx.measureText(text).width * 1.04)
  } else {
    w = Math.ceil(text.length * 6.6)
  }
  measureCache.set(key, w)
  return w
}

/** Joyga sig'masa oxirini "…" bilan qisqartiradi. */
export function fitText(text: string, maxWidth: number, font = LABEL_FONT): string {
  if (measureText(text, font) <= maxWidth) return text
  if (maxWidth < measureText('…', font) * 2) return ''
  let lo = 0
  let hi = text.length
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (measureText(text.slice(0, mid) + '…', font) <= maxWidth) lo = mid
    else hi = mid - 1
  }
  return lo > 0 ? text.slice(0, lo).trimEnd() + '…' : ''
}

/* ------------------------------------------------------------------ o'lcham */

/**
 * Element o'lchami (ResizeObserver). Grafik konteyner kengligiga moslashadi.
 * `watch` bilan - element v-if ortidan keyin paydo bo'lsa ham kuzatiladi.
 */
export function useElementSize(el: Ref<HTMLElement | null>): { width: Ref<number>; height: Ref<number> } {
  const width = ref(0)
  const height = ref(0)
  if (getCurrentScope()) onScopeDispose(watchFonts())
  watch(
    el,
    (node, _old, onCleanup) => {
      if (!node) return
      const rect = node.getBoundingClientRect()
      width.value = Math.round(rect.width)
      height.value = Math.round(rect.height)
      if (typeof ResizeObserver === 'undefined') return
      const ro = new ResizeObserver((entries) => {
        const box = entries[0]?.contentRect
        if (!box) return
        width.value = Math.round(box.width)
        height.value = Math.round(box.height)
      })
      ro.observe(node)
      onCleanup(() => ro.disconnect())
    },
    { immediate: true, flush: 'post' },
  )
  return { width, height }
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}

/** Sochdek chiziq piksel chegarasiga tushsin (xira 2px emas, aniq 1px). */
export function crisp(v: number): number {
  return Math.round(v) + 0.5
}

export interface YAxisTick {
  v: number
  y: number
  label: string
  w: number
}

/**
 * Y o'qi: yumaloq belgilar, shkala va eng keng yozuv (chap chegara uchun).
 * Belgilar soni balandlikka qarab - har ~52px ga bitta, 2..6.
 */
export function yAxis(
  lo: number,
  hi: number,
  top: number,
  bottom: number,
  fmt: (v: number) => string,
): { scale: LinearScale; ticks: YAxisTick[]; labelWidth: number; min: number; max: number } {
  const count = clamp(Math.round((bottom - top) / 52), 2, 6)
  const nice = niceTicks(lo, hi, count)
  const scale = linearScale([nice.min, nice.max], [bottom, top])
  const ticks = nice.ticks.map((v) => {
    const label = fmt(v)
    return { v, y: crisp(scale(v)), label, w: measureText(label) }
  })
  return { scale, ticks, labelWidth: Math.max(0, ...ticks.map((t) => t.w)), min: nice.min, max: nice.max }
}

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChartLine, Table2 } from 'lucide-vue-next'
import VIconButton from '../VIconButton.vue'
import VChartLegend from './VChartLegend.vue'
import VChartTooltip from './VChartTooltip.vue'
import VChartTable from './VChartTable.vue'
import {
  DAY,
  areaPath,
  bisect,
  clamp,
  crisp,
  cssColor,
  fontEpoch,
  indexTicks,
  linePath,
  linearScale,
  measureText,
  niceTicks,
  parseTimes,
  regularStep,
  splitRuns,
  timeTicks,
  useElementSize,
  type ChartSeries,
  type ChartTableColumn,
  type ChartView,
  type LegendItem,
  type Pt,
  type TooltipRow,
  type XYChartProps,
} from './scale'
import { fmtCompact, fmtDate, fmtDateTime, fmtNumber, fmtTime } from '../format'

/**
 * Vaqt bo'yicha chiziq grafigi; `area` bilan maydon, `stacked` bilan ustma-ust maydon
 * (VAreaChart shu komponentning o'rami).
 *
 * Qoidalar (dizayn spek, 3-bo'lim): chiziq 2px, maydon 10% yuvilgan rang, to'r va o'q
 * sochdek ingichka va jim; kursor x ni topadi (vertikal chiziq eng yaqin nuqtaga
 * yopishadi), bitta tooltip shu x dagi hamma qatorni sanaydi; ← → tugmalari ham
 * shunday qiladi. Qayta yuklanishda kadr saqlanadi (50% xira, sakrash yo'q).
 */
const props = withDefaults(defineProps<XYChartProps & { area?: boolean; stacked?: boolean }>(), {
  height: 240,
  curve: 'monotone',
  endLabels: true,
  tableToggle: true,
})
const view = defineModel<ChartView>('view', { default: 'chart' })

const { t, locale } = useI18n({ useScope: 'global' })

const PAD_T = 10 // tepada nuqta halqasi kesilmasin
const AXIS_H = 28 // x o'qi yozuvlari tasmasi (balandlik ichida)
const Y_GAP = 12 // y yozuvlari va chizma orasi
const END_GAP = 10 // oxirgi nuqta va uning yozuvi orasi

const plotEl = ref<HTMLElement | null>(null)
const { width } = useElementSize(plotEl)

/* ---- qatorlar va yashirish ---- */

const hidden = ref<Set<string>>(new Set())
const highlight = ref<string | null>(null)

function toggle(key: string) {
  const next = new Set(hidden.value)
  if (next.has(key)) next.delete(key)
  else {
    // Oxirgi ko'rinib turgan ma'lumot qatorini yashirib bo'lmaydi - bo'sh grafik foydasiz.
    const left = props.series.filter((s) => !s.reference && !next.has(s.key) && s.key !== key)
    const isData = props.series.some((s) => s.key === key && !s.reference)
    if (isData && left.length === 0) return
    next.add(key)
  }
  hidden.value = next
}

const n = computed(() => props.x.length)
const times = computed(() => parseTimes(props.x))
const step = computed(() => (times.value ? regularStep(times.value) : null))
/** Nuqtalar orasidagi odatiy masofa (ms) - yozuv formatini tanlash uchun. */
const grain = computed(() => {
  const ts = times.value
  if (!ts) return DAY
  if (step.value !== null) return step.value
  return ts.length > 1 ? (ts[ts.length - 1] - ts[0]) / (ts.length - 1) : DAY
})

function num(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

interface Layer {
  s: ChartSeries
  /** Chizma balandligi (stekda - yig'indi). */
  top: (number | null)[]
  /** Stekda pastki chegara, aks holda null. */
  base: number[] | null
}

const layers = computed<Layer[]>(() => {
  const len = n.value
  const out: Layer[] = []
  let acc: number[] = new Array(len).fill(0)
  for (const s of props.series) {
    if (hidden.value.has(s.key)) continue
    const vals = Array.from({ length: len }, (_, i) => num(s.values[i]))
    if (props.stacked && !s.reference) {
      const base = acc
      const top = base.map((b, i) => b + (vals[i] ?? 0))
      acc = top
      out.push({ s, top, base })
    } else {
      out.push({ s, top: vals, base: null })
    }
  }
  return out
})

const isEmpty = computed(() => n.value === 0 || layers.value.every((l) => l.top.every((v) => v === null)))

/* ---- y shkalasi ---- */

const plotBottom = computed(() => props.height - AXIS_H)

const yNice = computed(() => {
  let lo = Infinity
  let hi = -Infinity
  for (const l of layers.value) {
    for (const v of l.top) {
      if (v === null) continue
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
  }
  if (!Number.isFinite(lo)) {
    lo = 0
    hi = 1
  }
  // Nol asosi - miqdor va kechikish uchun halol; kerak bo'lsa yMin bilan o'zgartiriladi.
  lo = Math.min(0, lo)
  if (props.yMin !== undefined) lo = props.yMin
  if (props.yMax !== undefined) hi = props.yMax
  const count = clamp(Math.round((plotBottom.value - PAD_T) / 52), 2, 6)
  return niceTicks(lo, hi, count)
})

const yScale = computed(() => linearScale([yNice.value.min, yNice.value.max], [plotBottom.value, PAD_T]))

const valueFmt = computed(() => props.yFormat ?? ((v: number) => fmtNumber(v, locale.value)))
const tickFmt = computed(() => props.yTickFormat ?? props.yFormat ?? ((v: number) => fmtCompact(v, locale.value)))

const yTicks = computed(() => {
  void fontEpoch.value
  return yNice.value.ticks.map((v) => {
    const label = tickFmt.value(v)
    return { v, y: crisp(yScale.value(v)), label, w: measureText(label) }
  })
})

const padL = computed(() => Math.max(8, ...yTicks.value.map((tk) => tk.w)) + Y_GAP)

/* ---- oxirgi nuqta yozuvlari (faqat to'qnashmasa) ---- */

const endMarks = computed(() => {
  void fontEpoch.value
  if (!props.endLabels || n.value < 2) return null
  const cand = layers.value.filter((l) => !l.s.reference)
  if (cand.length < 2 || cand.length > 4) return null
  const last = n.value - 1
  const items: { key: string; label: string; y: number; w: number; color: string }[] = []
  for (const l of cand) {
    const v = l.top[last]
    if (v === null) return null
    items.push({ key: l.s.key, label: l.s.label, y: yScale.value(v), w: measureText(l.s.label), color: cssColor(l.s.color) })
  }
  const ys = items.map((it) => it.y).sort((a, b) => a - b)
  // Yozuvlarni surib ajratmaymiz (chiziqdan uzilib qoladi) - to'qnashsa umuman qo'ymaymiz.
  for (let i = 1; i < ys.length; i++) if (ys[i] - ys[i - 1] < 15) return null
  const need = Math.max(...items.map((it) => it.w)) + END_GAP + 6
  if (width.value <= 0 || need > width.value * 0.22) return null
  return { items, need }
})

const padR = computed(() => endMarks.value?.need ?? 8)

/* ---- x shkalasi ---- */

const xs = computed<number[]>(() => {
  const L = padL.value
  const R = Math.max(L + 1, width.value - padR.value)
  const len = n.value
  if (len === 0) return []
  if (len === 1) return [(L + R) / 2]
  const ts = times.value
  if (ts) {
    const sc = linearScale([ts[0], ts[len - 1]], [L, R])
    return ts.map((tt) => sc(tt))
  }
  return Array.from({ length: len }, (_, i) => L + (i / (len - 1)) * (R - L))
})

const spansYears = computed(() => {
  const ts = times.value
  return !!ts && ts.length > 1 && new Date(ts[0]).getFullYear() !== new Date(ts[ts.length - 1]).getFullYear()
})

function tickLabel(d: Date, stepMs: number): string {
  if (props.xFormat) return props.xFormat(d)
  if (stepMs < DAY) {
    // Soatli o'qda yarim tun - kun nomi: qaysi kunga o'tganimiz ko'rinsin.
    return d.getHours() === 0 && d.getMinutes() === 0 ? fmtDate(d, locale.value, { year: 'never' }) : fmtTime(d)
  }
  return fmtDate(d, locale.value, { year: spansYears.value ? 'auto' : 'never' })
}

function xTitle(i: number): string {
  const ts = times.value
  if (!ts) return String(props.x[i] ?? '')
  const d = new Date(ts[i])
  if (props.xTitleFormat) return props.xTitleFormat(d)
  return grain.value < DAY ? fmtDateTime(d, locale.value, 'medium') : fmtDate(d, locale.value, { year: 'auto' })
}

const xTicks = computed(() => {
  void fontEpoch.value
  const len = n.value
  const W = width.value
  if (!len || W <= 0) return []
  const plotW = W - padL.value - padR.value
  const maxCount = Math.max(2, Math.floor(plotW / 84))
  const ts = times.value
  let cand: { x: number; label: string }[] = []
  if (ts) {
    // Belgilar soat/kalendar chegarasida (00:00, 06:00 ... yoki dushanbalar). Bir xil
    // qadamli qatorda belgi eng yaqin NUQTAGA yopishadi: UTC yarim tunidagi kunlik
    // nuqta (Toshkentda 05:00) belgidan 5 soat siljib qolmasin.
    const tt = timeTicks(ts[0], ts[len - 1], maxCount)
    const unit = Math.max(grain.value, tt.stepMs)
    if (step.value !== null) {
      const seen = new Set<number>()
      for (const d of tt.ticks) {
        const i = bisect(ts, d.getTime())
        if (seen.has(i) || Math.abs(ts[i] - d.getTime()) > step.value / 2) continue
        seen.add(i)
        cand.push({ x: xs.value[i], label: tickLabel(new Date(ts[i]), unit) })
      }
      if (cand.length === 0) {
        cand = indexTicks(len, maxCount, step.value).map((i) => ({ x: xs.value[i], label: tickLabel(new Date(ts[i]), grain.value) }))
      }
    } else {
      const sc = linearScale([ts[0], ts[len - 1]], [padL.value, W - padR.value])
      cand = tt.ticks.map((d) => ({ x: sc(d.getTime()), label: tickLabel(d, unit) }))
    }
  } else {
    cand = indexTicks(len, maxCount, null).map((i) => ({ x: xs.value[i], label: String(props.x[i]) }))
  }
  // Chetdan chiqmasin (yozuv markazini ichkariga suramiz), keyin ustma-ust tushganlarni
  // o'ngdan chapga tashlaymiz - eng yangi sana doim yozuvli qoladi.
  const placed = cand.map((c) => {
    const w = measureText(c.label)
    const cx = clamp(c.x, w / 2, W - w / 2)
    return { ...c, w, cx }
  })
  const kept: typeof placed = []
  let leftEdge = Infinity
  for (let i = placed.length - 1; i >= 0; i--) {
    const p = placed[i]
    if (p.cx + p.w / 2 + 14 <= leftEdge) {
      kept.unshift(p)
      leftEdge = p.cx - p.w / 2
    }
  }
  return kept
})

/* ---- yo'llar ---- */

const baseY = computed(() => crisp(yScale.value(clamp(0, yNice.value.min, yNice.value.max))))
/** Asos chizig'i o'q bilan chiziladi - to'r uni takrorlamasin. */
const gridTicks = computed(() => yTicks.value.filter((tk) => tk.y !== baseY.value))

const shapes = computed(() => {
  const y = yScale.value
  const x = xs.value
  const y0 = yScale.value(clamp(0, yNice.value.min, yNice.value.max))
  return layers.value.map((l) => {
    const pts: (Pt | null)[] = l.top.map((v, i) => (v === null ? null : { x: x[i], y: y(v) }))
    let area = ''
    if (props.area && !l.s.reference) {
      if (l.base) {
        const top = pts.map((p, i) => p ?? { x: x[i], y: y(l.base![i]) })
        const bottom = l.base.map((b, i) => ({ x: x[i], y: y(b) }))
        area = areaPath(top, bottom, props.curve)
      } else {
        area = splitRuns(pts)
          .map((run) => areaPath(run, run.map((p) => ({ x: p.x, y: y0 })), props.curve))
          .join('')
      }
    }
    return {
      key: l.s.key,
      color: cssColor(l.s.color),
      dashed: !!l.s.reference,
      line: linePath(pts, props.curve),
      area,
      // Yolg'iz nuqta (ikki tomoni bo'sh) chiziq bo'lolmaydi - nuqta bilan ko'rsatamiz.
      singles: splitRuns(pts).filter((r) => r.length === 1).map((r) => r[0]),
    }
  })
})

/* ---- kursor, klaviatura ---- */

const active = ref<number | null>(null)
const activeIdx = computed(() => (active.value !== null && active.value < n.value ? active.value : null))
const focused = ref(false)
let lastInput: 'pointer' | 'key' = 'pointer'

function pick(e: PointerEvent) {
  const el = plotEl.value
  if (!el || isEmpty.value) return
  const px = e.clientX - el.getBoundingClientRect().left
  active.value = bisect(xs.value, px)
}

function onPointerDown(e: PointerEvent) {
  lastInput = 'pointer'
  pick(e)
}

function onPointerMove(e: PointerEvent) {
  lastInput = 'pointer'
  pick(e)
}

function onPointerLeave(e: PointerEvent) {
  // Sensorli ekranda barmoq ko'tarilganda ham tooltip qolsin - boshqa joyga
  // tegilganda (blur) yopiladi.
  if (e.pointerType === 'touch') return
  if (!(focused.value && lastInput === 'key')) active.value = null
}

function onFocus() {
  focused.value = true
  if (lastInput === 'key' || active.value === null) {
    lastInput = 'key'
    if (!isEmpty.value) active.value = n.value - 1
  }
}

function onBlur() {
  focused.value = false
  active.value = null
  lastInput = 'pointer'
}

function onKey(e: KeyboardEvent) {
  const len = n.value
  if (!len || isEmpty.value) return
  let i = activeIdx.value ?? len - 1
  const big = Math.max(1, Math.round(len / 10))
  switch (e.key) {
    case 'ArrowRight':
      i = Math.min(len - 1, i + 1)
      break
    case 'ArrowLeft':
      i = Math.max(0, i - 1)
      break
    case 'PageDown':
      i = Math.min(len - 1, i + big)
      break
    case 'PageUp':
      i = Math.max(0, i - big)
      break
    case 'Home':
      i = 0
      break
    case 'End':
      i = len - 1
      break
    case 'Escape':
      active.value = null
      return
    default:
      return
  }
  e.preventDefault()
  lastInput = 'key'
  active.value = i
}

const tipRows = computed<TooltipRow[]>(() => {
  const i = activeIdx.value
  if (i === null) return []
  const fmt = valueFmt.value
  const rows: TooltipRow[] = layers.value.map((l) => {
    const v = num(l.s.values[i])
    return {
      key: l.s.key,
      label: l.s.label,
      value: v === null ? '—' : fmt(v),
      color: l.s.color,
      mark: l.s.reference ? 'dashed' : 'line',
    }
  })
  if (!props.stacked) return rows
  // Stekda tooltip tartibi ko'rinishga mos: yuqoridagi qatlam yuqorida.
  const data = rows.filter((_, k) => !layers.value[k].s.reference).reverse()
  const refs = rows.filter((_, k) => layers.value[k].s.reference)
  const out = [...data, ...refs]
  if (data.length >= 2) {
    const total = layers.value.reduce((sum, l) => (l.s.reference ? sum : sum + (num(l.s.values[i]) ?? 0)), 0)
    out.push({ key: '__total', label: t('ui.total'), value: fmt(total), mark: 'none' })
  }
  return out
})

const activeDots = computed(() => {
  const i = activeIdx.value
  if (i === null) return []
  const out: { key: string; x: number; y: number; color: string }[] = []
  for (const l of layers.value) {
    const v = l.top[i]
    if (v === null) continue
    out.push({ key: l.s.key, x: xs.value[i], y: yScale.value(v), color: cssColor(l.s.color) })
  }
  return out
})

/** Klaviatura bilan yurganda ekran o'quvchiga shu nuqtani o'qib beramiz. */
const liveText = computed(() => {
  const i = activeIdx.value
  if (i === null || lastInput !== 'key') return ''
  return `${xTitle(i)}: ${tipRows.value.map((r) => `${r.label} ${r.value}`).join(', ')}`
})

/* ---- afsona, jadval ---- */

const showLegend = computed(() => !props.hideLegend && props.series.length >= 2)

const legendItems = computed<LegendItem[]>(() =>
  props.series.map((s) => ({
    key: s.key,
    label: s.label,
    color: s.color,
    mark: s.reference ? 'dashed' : props.area ? 'rect' : 'line',
    hidden: hidden.value.has(s.key),
  })),
)

const tableColumns = computed<ChartTableColumn[]>(() => [
  { key: '__x', label: times.value ? t('ui.date') : '' },
  ...props.series.map((s) => ({ key: s.key, label: s.label, align: 'end' as const })),
])

const tableRows = computed(() => {
  const fmt = valueFmt.value
  return Array.from({ length: n.value }, (_, i) => {
    const row: Record<string, string> = { __x: xTitle(i) }
    for (const s of props.series) {
      const v = num(s.values[i])
      row[s.key] = v === null ? '—' : fmt(v)
    }
    return row
  })
})

const viewLabel = computed(() => (view.value === 'table' ? t('ui.chart') : t('ui.table')))
</script>

<template>
  <figure class="vc" :class="{ 'is-loading': loading }" :aria-busy="loading || undefined">
    <div v-if="showLegend || tableToggle" class="vc-head">
      <VChartLegend
        v-if="showLegend"
        :items="legendItems"
        toggleable
        @toggle="toggle"
        @highlight="highlight = $event"
      />
      <span v-else />
      <VIconButton
        v-if="tableToggle"
        class="vc-view"
        size="sm"
        :label="viewLabel"
        :icon="view === 'table' ? ChartLine : Table2"
        :pressed="view === 'table'"
        tooltip-placement="left"
        @click="view = view === 'table' ? 'chart' : 'table'"
      />
    </div>

    <div class="vc-body">
      <VChartTable
        v-if="view === 'table'"
        :columns="tableColumns"
        :rows="tableRows"
        :caption="label"
        :height="height"
      />
      <div
        v-else
        ref="plotEl"
        class="vc-plot"
        :style="{ height: `${height}px` }"
        :tabindex="isEmpty ? -1 : 0"
        role="group"
        :aria-label="label ?? t('ui.chart')"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerleave="onPointerLeave"
        @focus="onFocus"
        @blur="onBlur"
        @keydown="onKey"
      >
        <svg
          v-if="width > 0"
          class="vc-svg"
          :width="width"
          :height="height"
          :viewBox="`0 0 ${width} ${height}`"
          aria-hidden="true"
          focusable="false"
        >
          <!-- to'r: faqat gorizontal, sochdek -->
          <g class="vc-grid">
            <line
              v-for="tk in gridTicks"
              :key="tk.v"
              :x1="padL"
              :x2="width - padR"
              :y1="tk.y"
              :y2="tk.y"
            />
          </g>
          <line class="vc-axis" :x1="padL" :x2="width - padR" :y1="baseY" :y2="baseY" />

          <g v-if="!isEmpty" class="vc-ticks">
            <text
              v-for="tk in yTicks"
              :key="`y${tk.v}`"
              :x="padL - Y_GAP"
              :y="tk.y"
              text-anchor="end"
              dominant-baseline="central"
            >{{ tk.label }}</text>
            <text
              v-for="tk in xTicks"
              :key="`x${tk.x}`"
              :x="tk.cx"
              :y="height - 8"
              text-anchor="middle"
            >{{ tk.label }}</text>
          </g>

          <g
            v-for="sh in shapes"
            :key="sh.key"
            class="vc-series"
            :class="{ 'is-dim': highlight !== null && highlight !== sh.key }"
            :style="{ '--c': sh.color }"
          >
            <path v-if="sh.area" class="vc-area" :d="sh.area" />
            <path v-if="sh.line" class="vc-line" :class="{ 'is-dashed': sh.dashed }" :d="sh.line" />
            <circle v-for="(p, k) in sh.singles" :key="k" class="vc-single" :cx="p.x" :cy="p.y" r="4" />
          </g>

          <g v-if="endMarks" class="vc-end">
            <template v-for="it in endMarks.items" :key="it.key">
              <circle :cx="xs[n - 1]" :cy="it.y" r="4" :style="{ '--c': it.color }" />
              <text :x="xs[n - 1] + END_GAP" :y="it.y" dominant-baseline="central">{{ it.label }}</text>
            </template>
          </g>

          <g v-if="activeIdx !== null" class="vc-cross">
            <line :x1="crisp(xs[activeIdx])" :x2="crisp(xs[activeIdx])" :y1="PAD_T - 4" :y2="plotBottom" />
            <circle
              v-for="d in activeDots"
              :key="d.key"
              :cx="d.x"
              :cy="d.y"
              r="4"
              :style="{ '--c': d.color }"
            />
          </g>
        </svg>

        <p v-if="isEmpty && !loading" class="vc-empty">{{ t('ui.noData') }}</p>

        <VChartTooltip
          :visible="activeIdx !== null"
          :x="activeIdx !== null ? xs[activeIdx] : 0"
          :y="PAD_T"
          :bounds-width="width"
          :bounds-height="height"
          :title="activeIdx !== null ? xTitle(activeIdx) : ''"
          :rows="tipRows"
        />
      </div>
    </div>
    <p class="sr-only" aria-live="polite">{{ liveText }}</p>
  </figure>
</template>

<style scoped>
.vc {
  position: relative;
  min-width: 0;
}
.vc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-4);
  min-height: 32px;
  margin-bottom: var(--s-3);
}
/* Afsona tugmaning o'rtasiga tekislansin (32px tugma, 16px qator). */
.vc-head > :first-child {
  padding-top: var(--s-2);
}
.vc-head :deep(.vc-view) {
  margin: 0 calc(var(--s-1_5) * -1) 0 auto;
  color: var(--text-3);
}

/* Qayta yuklash: kadr joyida, faqat xiralashadi. */
.vc-body {
  transition: opacity var(--dur-2) var(--ease-out);
}
.is-loading .vc-body {
  opacity: 0.5;
}

.vc-plot {
  position: relative;
  width: 100%;
  touch-action: pan-y;
  user-select: none;
  -webkit-user-select: none;
  border-radius: var(--r-xs);
}
.vc-plot:focus-visible {
  outline-offset: 4px;
}
.vc-svg {
  display: block;
  overflow: visible;
}

.vc-grid line {
  stroke: var(--viz-grid);
  stroke-width: 1;
  shape-rendering: crispEdges;
}
.vc-axis {
  stroke: var(--viz-axis);
  stroke-width: 1;
  shape-rendering: crispEdges;
}
.vc-ticks text,
.vc-end text {
  font-family: var(--font-sans);
  font-size: var(--fs-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  fill: var(--text-3);
}
.vc-end text {
  fill: var(--text-2);
}
/* Nuqta: 8px rangli doira + TASHQARIDA 2px sirt halqasi. `paint-order: stroke` -
   chiziq qalinligining ichki yarmi rangni yemasin (r=4, stroke 4 -> halqa 2px). */
.vc-end circle {
  fill: var(--c);
  stroke: var(--surface);
  stroke-width: 4;
  paint-order: stroke;
}

.vc-series {
  transition: opacity var(--dur-1) var(--ease-out);
}
.vc-series.is-dim {
  opacity: 0.2;
}
.vc-area {
  fill: var(--c);
  fill-opacity: 0.1;
  stroke: none;
}
.vc-line {
  fill: none;
  stroke: var(--c);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.vc-line.is-dashed {
  stroke-width: 1.5;
  stroke-dasharray: 4 4;
  stroke-linecap: butt;
}
.vc-single {
  fill: var(--c);
}

.vc-cross line {
  stroke: var(--text-4);
  stroke-width: 1;
  shape-rendering: crispEdges;
}
/* Faol nuqta: 8px + 2px sirt halqasi - chiziqlar kesishgan joyda ham o'qiladi. */
.vc-cross circle {
  fill: var(--c);
  stroke: var(--surface);
  stroke-width: 4;
  paint-order: stroke;
}

.vc-empty {
  position: absolute;
  inset: 0 0 28px;
  text-align: center;
  display: grid;
  place-items: center;
  margin: 0;
  font-size: var(--fs-body-sm);
  color: var(--text-3);
  pointer-events: none;
}
</style>

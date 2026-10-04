<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { ChartColumn, Table2 } from 'lucide-vue-next'
import VIconButton from '../VIconButton.vue'
import VSkeleton from '../VSkeleton.vue'
import VChartTooltip from './VChartTooltip.vue'
import VChartTable from './VChartTable.vue'
import {
  barPath,
  bisect,
  cssColor,
  crisp,
  fitText,
  fontEpoch,
  measureText,
  useElementSize,
  yAxis,
  type BarDatum,
  type ChartTableColumn,
  type ChartView,
  type TooltipRow,
} from './scale'
import { fmtCompact, fmtNumber } from '../format'

/**
 * Ustunli grafik.
 * - horizontal (standart): reyting ro'yxati - nom chapda, ingichka ustun, qiymat uchida.
 *   HTML da chiziladi: uzun nomlar tabiiy qisqaradi, qator havola bo'la oladi.
 * - vertical: SVG, y o'qi va jim to'r bilan; ← → bilan ustunlar bo'ylab yuriladi.
 *
 * Ustun <= 24px (bo'shliq havo bo'lib qoladi), ma'lumot uchi 4px yumaloq, asosi to'g'ri.
 * Qiymat yozuvi faqat sig'sa; sig'masa tooltip va jadval ko'rinishida qoladi.
 */
const props = withDefaults(
  defineProps<{
    data: BarDatum[]
    orientation?: 'horizontal' | 'vertical'
    /** Hamma ustun rangi (d.color bo'lmasa). Bitta qator - bitta rang. */
    color?: string
    valueFormat?: (v: number) => string
    /** Vertikal y o'qi belgilari. */
    tickFormat?: (v: number) => string
    /** Vertikal: umumiy balandlik (x yozuvlari bilan), px. */
    height?: number
    /** Shkala yuqori chegarasi (bir nechta grafikni solishtirish uchun). */
    max?: number
    /** Ustun qalinligi, px (<= 24). */
    thickness?: number
    showValues?: boolean
    /** Gorizontal: nomlar ustunining eng katta kengligi (uzun hujjat nomlari uchun kattaroq). */
    labelMax?: string
    loading?: boolean
    label?: string
    tableToggle?: boolean
  }>(),
  {
    orientation: 'horizontal',
    color: '--viz-1',
    height: 220,
    showValues: true,
    tableToggle: true,
  },
)
const view = defineModel<ChartView>('view', { default: 'chart' })

const { t, locale } = useI18n({ useScope: 'global' })

const fmt = computed(() => props.valueFormat ?? ((v: number) => fmtNumber(v, locale.value)))
const tickFmt = computed(() => props.tickFormat ?? props.valueFormat ?? ((v: number) => fmtCompact(v, locale.value)))

function num(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

const rootEl = ref<HTMLElement | null>(null)
const hover = ref<number | null>(null)
const tip = ref({ x: 0, y: 0 })

const isEmpty = computed(() => props.data.length === 0 || props.data.every((d) => num(d.value) === null))

function tipRowsFor(i: number | null): TooltipRow[] {
  if (i === null) return []
  const d = props.data[i]
  if (!d) return []
  const v = num(d.value)
  return [{ key: d.key, label: d.sub ?? '', value: v === null ? '—' : fmt.value(v), color: d.color ?? props.color, mark: 'rect' }]
}

/* ================================================================ gorizontal */

const hMax = computed(() => {
  const m = Math.max(0, ...props.data.map((d) => num(d.value) ?? 0))
  return props.max !== undefined ? Math.max(props.max, m) : m
})

const hRows = computed(() => {
  const max = hMax.value || 1
  return props.data.map((d) => {
    const v = num(d.value)
    const p = v === null ? 0 : Math.max(0, v) / max
    return {
      d,
      p,
      text: v === null ? '—' : fmt.value(v),
      color: cssColor(d.color ?? props.color),
    }
  })
})

/** Eng keng qiymat yozuvi - shkala undan qolgan joyga sig'adi, eng uzun ustun ham yozuvli. */
const valueW = computed(() => {
  void fontEpoch.value
  if (!props.showValues) return 0
  return Math.max(0, ...hRows.value.map((r) => measureText(r.text))) + 8
})

const hThick = computed(() => Math.min(24, props.thickness ?? 12))

function onRowEnter(i: number, e: PointerEvent) {
  hover.value = i
  const root = rootEl.value
  const bar = (e.currentTarget as HTMLElement).querySelector<HTMLElement>('.vb-bar')
  if (!root || !bar) return
  const r = root.getBoundingClientRect()
  const b = bar.getBoundingClientRect()
  tip.value = { x: b.right - r.left, y: b.top - r.top }
}

/* ================================================================ vertikal */

const PAD_T = 22 // qopqoqdagi qiymat yozuvi uchun joy
const AXIS_H = 28
const Y_GAP = 12

const plotEl = ref<HTMLElement | null>(null)
const { width } = useElementSize(plotEl)

const vAxis = computed(() => {
  void fontEpoch.value
  const vals = props.data.map((d) => num(d.value)).filter((v): v is number => v !== null)
  const lo = Math.min(0, ...vals)
  let hi = Math.max(0, ...vals)
  if (props.max !== undefined) hi = Math.max(hi, props.max)
  if (hi === lo) hi = lo + 1
  return yAxis(lo, hi, PAD_T, props.height - AXIS_H, tickFmt.value)
})

const padL = computed(() => vAxis.value.labelWidth + Y_GAP)

const vBars = computed(() => {
  void fontEpoch.value
  const n = props.data.length
  const W = width.value
  if (!n || W <= 0) return { bars: [], band: 0, labelsFit: false, valuesFit: false }
  const plotW = Math.max(1, W - padL.value - 4)
  const band = plotW / n
  // 24px dan qalin emas; qo'shni ustunlar orasida kamida 2px sirt bo'shlig'i.
  const bw = Math.max(1, Math.min(props.thickness ?? 24, 24, band * 0.62, band - 2))
  const y = vAxis.value.scale
  const y0 = y(Math.max(vAxis.value.min, Math.min(0, vAxis.value.max)))
  const bars = props.data.map((d, i) => {
    const v = num(d.value)
    const cx = padL.value + band * i + band / 2
    const yv = v === null ? y0 : y(v)
    const up = (v ?? 0) >= 0
    const top = up ? yv : y0
    const h = Math.abs(yv - y0)
    const text = v === null ? '—' : fmt.value(v)
    return {
      d,
      i,
      cx,
      x: cx - bw / 2,
      top,
      tipY: top,
      path: v === null || h < 0.5 ? '' : barPath(cx - bw / 2, top, bw, h, 4, up ? 'up' : 'down'),
      color: cssColor(d.color ?? props.color),
      text,
      textY: up ? yv - 7 : yv + 15,
      label: '',
    }
  })
  // Qopqoqdagi qiymat - kam ustunda va sig'sa. 30 ta ustunning har biriga raqam - shovqin:
  // u holda o'q, tooltip va jadval yetadi.
  const valuesFit = props.showValues && n <= 12 && bars.every((b) => measureText(b.text) <= band - 2)
  // x yozuvlari: toifa ustunida har bir ustun nomli bo'lsin - sig'masa "…" bilan
  // qisqaradi (to'liq nomi tooltip va jadvalda). Faqat juda zich qatorda (masalan
  // 30 kunlik ustunlar) har k-chisini qoldiramiz - oxiridan, eng yangisi yozuvli.
  const widest = Math.max(...props.data.map((d) => measureText(d.label)))
  const k = band - 6 >= 36 ? 1 : Math.max(1, Math.ceil((Math.min(widest, 96) + 8) / band))
  for (const b of bars) {
    if ((n - 1 - b.i) % k === 0) b.label = fitText(b.d.label, band * k - 6)
  }
  return { bars, band, labelsFit: k === 1, valuesFit }
})

const vBaseY = computed(() => crisp(vAxis.value.scale(Math.max(vAxis.value.min, Math.min(0, vAxis.value.max)))))
const vGrid = computed(() => vAxis.value.ticks.filter((tk) => tk.y !== vBaseY.value))

const active = ref<number | null>(null)
const focused = ref(false)
let lastInput: 'pointer' | 'key' = 'pointer'

function pick(e: PointerEvent) {
  const el = plotEl.value
  if (!el || isEmpty.value) return
  lastInput = 'pointer'
  const px = e.clientX - el.getBoundingClientRect().left
  active.value = bisect(
    vBars.value.bars.map((b) => b.cx),
    px,
  )
}

function onLeave(e: PointerEvent) {
  if (e.pointerType === 'touch') return
  if (!(focused.value && lastInput === 'key')) active.value = null
}

function onFocus() {
  focused.value = true
  if (lastInput === 'key' || active.value === null) {
    lastInput = 'key'
    if (!isEmpty.value) active.value = props.data.length - 1
  }
}

function onBlur() {
  focused.value = false
  active.value = null
  lastInput = 'pointer'
}

function onKey(e: KeyboardEvent) {
  const n = props.data.length
  if (!n || isEmpty.value) return
  let i = active.value ?? n - 1
  if (e.key === 'ArrowRight') i = Math.min(n - 1, i + 1)
  else if (e.key === 'ArrowLeft') i = Math.max(0, i - 1)
  else if (e.key === 'Home') i = 0
  else if (e.key === 'End') i = n - 1
  else if (e.key === 'Escape') {
    active.value = null
    return
  } else return
  e.preventDefault()
  lastInput = 'key'
  active.value = i
}

const activeBar = computed(() => (active.value !== null ? (vBars.value.bars[active.value] ?? null) : null))

const liveText = computed(() => {
  const b = activeBar.value
  if (!b || lastInput !== 'key') return ''
  return `${b.d.label}: ${b.text}${b.d.sub ? `, ${b.d.sub}` : ''}`
})

/* ================================================================ jadval */

const tableColumns = computed<ChartTableColumn[]>(() => [
  { key: 'label', label: '' },
  { key: 'value', label: props.label ?? '', align: 'end' },
])
const tableRows = computed(() =>
  props.data.map((d) => {
    const v = num(d.value)
    return { label: d.label, value: v === null ? '—' : fmt.value(v) }
  }),
)

const viewLabel = computed(() => (view.value === 'table' ? t('ui.chart') : t('ui.table')))
const isVertical = computed(() => props.orientation === 'vertical')
</script>

<template>
  <figure
    ref="rootEl"
    class="vb"
    :class="[isVertical ? 'is-v' : 'is-h', { 'is-loading': loading }]"
    :aria-busy="loading || undefined"
  >
    <!-- ============ gorizontal ============ -->
    <template v-if="!isVertical">
      <!-- birinchi yuklash: qatorlar o'rnida skelet (keyin sakrash bo'lmasin) -->
      <ul v-if="isEmpty && loading" class="vb-list is-skeleton" aria-hidden="true">
        <li v-for="k in 5" :key="k" class="vb-item">
          <div class="vb-row">
            <VSkeleton :width="[88, 64, 76, 52, 70][k - 1]" :height="12" />
            <VSkeleton :width="`${[86, 58, 34, 18, 9][k - 1]}%`" :height="hThick" radius="xs" />
          </div>
        </li>
      </ul>
      <p v-else-if="isEmpty" class="vb-empty">{{ t('ui.noData') }}</p>
      <ul
        v-else
        class="vb-list"
        role="list"
        :aria-label="label"
        :style="{ '--vw': `${valueW}px`, '--thick': `${hThick}px`, '--vb-label-max': labelMax }"
        @pointerleave="hover = null"
      >
        <li
          v-for="(r, i) in hRows"
          :key="r.d.key"
          class="vb-item"
          :class="{ 'is-dim': hover !== null && hover !== i }"
          @pointerenter="onRowEnter(i, $event)"
        >
          <component :is="r.d.to ? RouterLink : 'div'" :to="r.d.to" class="vb-row" :class="{ 'is-link': !!r.d.to }">
            <span class="vb-label" :title="r.d.label">{{ r.d.label }}</span>
            <span class="vb-track">
              <span
                class="vb-bar"
                :style="{
                  '--c': r.color,
                  width: r.p > 0 ? `max(2px, calc((100% - var(--vw)) * ${r.p}))` : '0px',
                }"
              />
              <span v-if="showValues" class="vb-value">{{ r.text }}</span>
              <!-- Qiymat ko'rsatilmasa ham ekran o'quvchi uni o'qisin (tooltip faqat sichqonchada). -->
              <span v-else class="sr-only">{{ r.text }}</span>
            </span>
          </component>
        </li>
      </ul>
      <VChartTooltip
        :visible="hover !== null"
        :x="tip.x"
        :y="tip.y"
        :bounds-width="rootEl?.clientWidth ?? 0"
        placement="above"
        :offset="8"
        :title="hover !== null ? data[hover]?.label : ''"
        :rows="tipRowsFor(hover)"
      />
    </template>

    <!-- ============ vertikal ============ -->
    <template v-else>
      <div v-if="tableToggle" class="vb-head">
        <VIconButton
          class="vb-view"
          size="sm"
          :label="viewLabel"
          :icon="view === 'table' ? ChartColumn : Table2"
          :pressed="view === 'table'"
          tooltip-placement="left"
          @click="view = view === 'table' ? 'chart' : 'table'"
        />
      </div>
      <div class="vb-body">
        <VChartTable v-if="view === 'table'" :columns="tableColumns" :rows="tableRows" :caption="label" :height="height" />
        <div
          v-else
          ref="plotEl"
          class="vb-plot"
          :style="{ height: `${height}px` }"
          :tabindex="isEmpty ? -1 : 0"
          role="group"
          :aria-label="label ?? t('ui.chart')"
          @pointerdown="pick"
          @pointermove="pick"
          @pointerleave="onLeave"
          @focus="onFocus"
          @blur="onBlur"
          @keydown="onKey"
        >
          <svg
            v-if="width > 0"
            class="vb-svg"
            :width="width"
            :height="height"
            :viewBox="`0 0 ${width} ${height}`"
            aria-hidden="true"
            focusable="false"
          >
            <g class="vb-grid">
              <line v-for="tk in vGrid" :key="tk.v" :x1="padL" :x2="width" :y1="tk.y" :y2="tk.y" />
            </g>
            <g v-if="!isEmpty" class="vb-ticks">
              <text
                v-for="tk in vAxis.ticks"
                :key="`y${tk.v}`"
                :x="padL - Y_GAP"
                :y="tk.y"
                text-anchor="end"
                dominant-baseline="central"
              >{{ tk.label }}</text>
              <template v-for="b in vBars.bars" :key="`x${b.d.key}`">
                <text v-if="b.label" :x="b.cx" :y="height - 8" text-anchor="middle">{{ b.label }}</text>
              </template>
            </g>
            <!-- faol ustun tagida yengil "band" - kursor qayerda ekani ko'rinsin -->
            <rect
              v-if="activeBar"
              class="vb-band"
              :x="activeBar.cx - vBars.band / 2 + 1"
              :y="PAD_T - 6"
              :width="Math.max(0, vBars.band - 2)"
              :height="height - AXIS_H - PAD_T + 6"
              rx="4"
            />
            <g class="vb-bars">
              <path
                v-for="b in vBars.bars"
                :key="b.d.key"
                :d="b.path"
                :class="{ 'is-dim': active !== null && active !== b.i }"
                :style="{ '--c': b.color }"
              />
            </g>
            <line class="vb-axis" :x1="padL" :x2="width" :y1="vBaseY" :y2="vBaseY" />
            <g v-if="vBars.valuesFit" class="vb-values">
              <text v-for="b in vBars.bars" :key="`v${b.d.key}`" :x="b.cx" :y="b.textY" text-anchor="middle">{{ b.text }}</text>
            </g>
          </svg>

          <p v-if="isEmpty && !loading" class="vb-empty is-abs">{{ t('ui.noData') }}</p>

          <VChartTooltip
            :visible="activeBar !== null"
            :x="activeBar?.cx ?? 0"
            :y="activeBar?.tipY ?? 0"
            :bounds-width="width"
            placement="above"
            :offset="vBars.valuesFit ? 22 : 8"
            :title="activeBar?.d.label ?? ''"
            :rows="tipRowsFor(active)"
          />
        </div>
      </div>
      <p class="sr-only" aria-live="polite">{{ liveText }}</p>
    </template>
  </figure>
</template>

<style scoped>
.vb {
  position: relative;
  min-width: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.vb.is-loading {
  opacity: 0.5;
}

.vb-empty {
  margin: 0;
  padding: var(--s-6) 0;
  text-align: center;
  font-size: var(--fs-body-sm);
  color: var(--text-3);
}
.vb-empty.is-abs {
  position: absolute;
  inset: 0 0 28px;
  display: grid;
  place-items: center;
  padding: 0;
  pointer-events: none;
}

/* ---------------- gorizontal ---------------- */
.vb-list {
  display: grid;
  grid-template-columns: fit-content(var(--vb-label-max, 40%)) minmax(0, 1fr);
  column-gap: var(--s-4);
  margin: 0;
  padding: 0;
  list-style: none;
}
.vb-item {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: subgrid;
  transition: opacity var(--dur-1) var(--ease-out);
}
.vb-item.is-dim {
  opacity: 0.45;
}
.vb-row {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: subgrid;
  align-items: center;
  min-height: 32px;
  color: inherit;
  text-decoration: none;
}
.vb-row.is-link {
  margin: 0 calc(var(--s-2) * -1);
  padding: 0 var(--s-2);
  border-radius: var(--r-sm);
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .vb-row.is-link:hover {
    background: var(--fill);
  }
}
.vb-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  color: var(--text);
}
.vb-track {
  display: flex;
  align-items: center;
  min-width: 0;
}
.vb-bar {
  flex: none;
  height: var(--thick);
  /* ma'lumot uchi yumaloq, asos (chap) to'g'ri */
  border-radius: 0 4px 4px 0;
  background: var(--c);
  transition: width var(--dur-3) var(--ease-out);
}
.vb-value {
  flex: none;
  margin-inline-start: var(--s-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-2);
  white-space: nowrap;
}

/* ---------------- vertikal ---------------- */
.vb-head {
  display: flex;
  justify-content: flex-end;
  min-height: 32px;
  margin-bottom: var(--s-3);
}
.vb-head :deep(.vb-view) {
  margin-inline-end: calc(var(--s-1_5) * -1);
  color: var(--text-3);
}
.vb-plot {
  position: relative;
  width: 100%;
  touch-action: pan-y;
  user-select: none;
  -webkit-user-select: none;
  border-radius: var(--r-xs);
}
.vb-plot:focus-visible {
  outline-offset: 4px;
}
.vb-svg {
  display: block;
  overflow: visible;
}
.vb-grid line {
  stroke: var(--viz-grid);
  stroke-width: 1;
  shape-rendering: crispEdges;
}
.vb-axis {
  stroke: var(--viz-axis);
  stroke-width: 1;
  shape-rendering: crispEdges;
}
.vb-ticks text,
.vb-values text {
  font-family: var(--font-sans);
  font-size: var(--fs-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  fill: var(--text-3);
}
.vb-values text {
  fill: var(--text-2);
}
.vb-band {
  fill: var(--fill);
  opacity: 0.7;
}
.vb-bars path {
  fill: var(--c);
  transition: opacity var(--dur-1) var(--ease-out);
}
.vb-bars path.is-dim {
  opacity: 0.45;
}
</style>

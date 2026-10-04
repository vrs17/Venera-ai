<script lang="ts">
export interface WaterfallRow {
  id: string
  label: string
  /** Ikkinchi darajali izoh (model nomi, bosqich matni). */
  sub?: string
  /** So'rov boshidan siljish, ms. */
  startMs: number
  /** Davomiylik, ms. Yo'q bo'lsa - nuqta (hodisa: birinchi token, manbalar keldi). */
  durMs?: number | null
  /** Tur - rang shundan (kindColors). */
  kind: string
  status?: 'ok' | 'warn' | 'error'
  /** Ichma-ichlik darajasi (ichki span biroz surilgan). */
  depth?: number
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, TriangleAlert } from 'lucide-vue-next'
import VChartTooltip from './charts/VChartTooltip.vue'
import VSkeleton from './VSkeleton.vue'
import { cssColor, fontEpoch, niceTicks, useElementSize, type TooltipRow } from './charts/scale'
import { fmtMs } from './format'

/**
 * Trace sharsharasi: har bir bosqich (span) umumiy vaqt o'qida. Davomiyligi borlar -
 * 8px tasma (radius 4), hodisalar - 8px nuqta 2px sirt halqasi bilan. Rang - tur
 * bo'yicha (`kindColors`: kind -> --viz-* yoki --ch-*), xato - holat rangi va belgi bilan.
 *
 * Davomiylik yozuvi tasma yonida (joy bo'lsa) - aniq ms tooltipsiz ham ko'rinadi;
 * sichqoncha yoki fokusda boshlanish va davomiylik tooltipda. Qatorlar ro'yxat-tanlov
 * (listbox): ↑/↓ yuradi, Enter/Probel tanlaydi -> `select`.
 */
const props = withDefaults(
  defineProps<{
    rows: WaterfallRow[]
    kindColors?: Record<string, string>
    /** O'q uzunligi; berilmasa eng oxirgi tugash vaqti. */
    totalMs?: number
    selectedId?: string | null
    /** Chap ustun kengligi, px (tor ekranda o'zi qisqaradi). */
    labelWidth?: number
    label?: string
    loading?: boolean
  }>(),
  { kindColors: () => ({}), selectedId: null, labelWidth: 200 },
)

const emit = defineEmits<{ select: [id: string] }>()

const { t, locale } = useI18n({ useScope: 'global' })

// Konteyner spanlar (butun so'rov) - neytral; noma'lum tur - jim kulrang.
const BASE_KINDS: Record<string, string> = { request: '--line-strong', span: '--line-strong' }

function colorOf(r: WaterfallRow): string {
  if (r.status === 'error') return 'var(--crit)'
  return cssColor(props.kindColors[r.kind] ?? BASE_KINDS[r.kind], '--text-4')
}

const total = computed(() => {
  if (props.totalMs && props.totalMs > 0) return props.totalMs
  let m = 0
  for (const r of props.rows) m = Math.max(m, r.startMs + (r.durMs ?? 0))
  return m > 0 ? m : 1
})

const pct = (ms: number) => Math.max(0, Math.min(100, (ms / total.value) * 100))

const view = computed(() =>
  props.rows.map((r) => {
    const isSpan = typeof r.durMs === 'number' && Number.isFinite(r.durMs) && r.durMs > 0
    const start = pct(r.startMs)
    const end = isSpan ? pct(r.startMs + (r.durMs as number)) : start
    // Davomiylik yozuvi: o'ngda joy bo'lsa - tasmadan keyin, bo'lmasa - oldin, u ham
    // bo'lmasa (butun o'qni egallagan span) - faqat tooltip va aria da.
    const durSide: 'after' | 'before' | null = !isSpan ? null : end <= 78 ? 'after' : start >= 22 ? 'before' : null
    const startText = `+${fmtMs(r.startMs, locale.value)}`
    const durText = isSpan ? fmtMs(r.durMs as number, locale.value) : ''
    return { r, isSpan, start, end, width: end - start, durSide, startText, durText, color: colorOf(r) }
  }),
)

/* ---- o'q ---- */
const axisEl = ref<HTMLElement | null>(null)
const { width: axisW } = useElementSize(axisEl)

const ticks = computed(() => {
  void fontEpoch.value
  const w = axisW.value
  const tot = total.value
  const count = Math.max(2, Math.min(8, Math.floor(w / 88)))
  let values = niceTicks(0, tot, count).ticks.filter((v) => v <= tot + 1e-9)
  // Tor o'qda (telefon) "yaxlit" qadam jamidan oshib ketadi va o'qda yolg'iz "0 ms"
  // qolardi - vaqt shkalasi o'qilmaydi. Shunda 0 · o'rta · jami: uchalasi doim bor,
  // oxirgisi aynan so'rov davomiyligi.
  if (count < 3 || values.length < 3) values = [0, tot / 2, tot]
  return values.map((v) => {
    const p = pct(v)
    return { v, p, label: fmtMs(v, locale.value), align: p < 4 ? 'start' : p > 92 ? 'end' : 'middle' }
  })
})

/* ---- tanlash, klaviatura, hover ---- */
const focusIdx = ref(0)
const hover = ref<number | null>(null)
const rowEls: (HTMLElement | undefined)[] = []
function setRowEl(i: number, el: unknown) {
  rowEls[i] = el instanceof HTMLElement ? el : undefined
}

function focusRow(i: number) {
  const n = props.rows.length
  if (!n) return
  const k = Math.max(0, Math.min(n - 1, i))
  focusIdx.value = k
  rowEls[k]?.focus()
  rowEls[k]?.scrollIntoView?.({ block: 'nearest' })
}

function onKey(i: number, e: KeyboardEvent) {
  switch (e.key) {
    case 'ArrowDown':
      focusRow(i + 1)
      break
    case 'ArrowUp':
      focusRow(i - 1)
      break
    case 'Home':
      focusRow(0)
      break
    case 'End':
      focusRow(props.rows.length - 1)
      break
    case 'Enter':
    case ' ':
      emit('select', props.rows[i].id)
      break
    case 'Escape':
      hover.value = null
      return
    default:
      return
  }
  e.preventDefault()
}

function onFocusRow(i: number) {
  focusIdx.value = i
  hover.value = i
}

function onSelect(i: number) {
  focusIdx.value = i
  emit('select', props.rows[i].id)
}

function tipRows(i: number | null): TooltipRow[] {
  if (i === null) return []
  const v = view.value[i]
  if (!v) return []
  const rows: TooltipRow[] = [{ key: 'start', label: t('ui.start'), value: v.startText, mark: 'none' }]
  if (v.isSpan) rows.push({ key: 'dur', label: t('ui.duration'), value: v.durText, color: v.color, mark: 'rect' })
  return rows
}

function ariaOf(i: number): string {
  const v = view.value[i]
  const parts = [v.r.label]
  if (v.r.sub) parts.push(v.r.sub)
  parts.push(`${t('ui.start')} ${v.startText}`)
  if (v.isSpan) parts.push(`${t('ui.duration')} ${v.durText}`)
  return parts.join(', ')
}

const laneW = computed(() => Math.max(0, axisW.value - 16))

// Tooltip yo'lak (vaqt ustuni) ichida langar qiladi, lekin tor ekranda yo'lak tooltipdan
// torroq - chap chegara butun komponentning chap cheti (nomlar ustuni ustiga suriladi).
const rootEl = ref<HTMLElement | null>(null)
const { width: rootW } = useElementSize(rootEl)
// Yo'lak o'q elementidan 8px ichkarida (`.vw-lane { inset: 0 8px }`), o'q esa o'ng chetda.
const tipLeft = computed(() => -Math.max(0, rootW.value - axisW.value + 8))
</script>

<template>
  <div
    ref="rootEl"
    class="vw"
    :class="{ 'is-loading': loading }"
    :style="{ '--vw-label': `${labelWidth}px` }"
    :aria-busy="loading || undefined"
  >
    <div class="vw-head" aria-hidden="true">
      <span />
      <div ref="axisEl" class="vw-axis">
        <div class="vw-lane">
          <span
            v-for="tk in ticks"
            :key="tk.v"
            class="vw-tick"
            :class="`is-${tk.align}`"
            :style="{ left: `${tk.p}%` }"
          >{{ tk.label }}</span>
        </div>
      </div>
    </div>

    <div class="vw-body">
      <!-- vertikal to'r - faqat vaqt ustunida -->
      <div class="vw-grid" aria-hidden="true">
        <div class="vw-lane">
          <span v-for="tk in ticks" :key="tk.v" class="vw-gl" :style="{ left: `${tk.p}%` }" />
        </div>
      </div>

      <ul v-if="rows.length === 0 && loading" class="vw-rows" aria-hidden="true">
        <li v-for="k in 6" :key="k" class="vw-row is-skeleton">
          <div class="vw-name"><VSkeleton :width="[96, 72, 110, 64, 88, 80][k - 1]" :height="12" /></div>
          <div class="vw-track">
            <div class="vw-lane">
              <span class="vw-skel" :style="{ left: `${[0, 2, 8, 30, 34, 80][k - 1]}%`, width: `${[100, 6, 22, 48, 40, 16][k - 1]}%` }" />
            </div>
          </div>
        </li>
      </ul>
      <p v-else-if="rows.length === 0" class="vw-empty">{{ t('ui.noData') }}</p>
      <ul v-else class="vw-rows" role="listbox" :aria-label="label" @pointerleave="hover = null">
        <li
          v-for="(v, i) in view"
          :key="v.r.id"
          :ref="(el) => setRowEl(i, el)"
          class="vw-row"
          :class="{ 'is-selected': selectedId === v.r.id, 'is-hover': hover === i }"
          role="option"
          :aria-selected="selectedId === v.r.id"
          :aria-label="ariaOf(i)"
          :tabindex="i === focusIdx ? 0 : -1"
          @click="onSelect(i)"
          @keydown="onKey(i, $event)"
          @pointerenter="hover = i"
          @focus="onFocusRow(i)"
          @blur="hover = null"
        >
          <div class="vw-name" :style="{ paddingInlineStart: `calc(var(--vw-indent) * ${v.r.depth ?? 0})` }">
            <CircleAlert v-if="v.r.status === 'error'" class="vw-status is-error" :size="14" :stroke-width="2" aria-hidden="true" />
            <TriangleAlert v-else-if="v.r.status === 'warn'" class="vw-status is-warn" :size="14" :stroke-width="2" aria-hidden="true" />
            <span class="vw-label">{{ v.r.label }}</span>
            <span v-if="v.r.sub" class="vw-sub">{{ v.r.sub }}</span>
          </div>
          <div class="vw-track">
            <div class="vw-lane" :style="{ '--c': v.color }">
              <span v-if="v.isSpan" class="vw-bar" :style="{ left: `${v.start}%`, width: `max(2px, ${v.width}%)` }" />
              <span v-else class="vw-dot" :style="{ left: `${v.start}%` }" />
              <span
                v-if="v.durSide === 'after'"
                class="vw-dur"
                :style="{ left: `calc(${v.end}% + 6px)` }"
                aria-hidden="true"
              >{{ v.durText }}</span>
              <span
                v-else-if="v.durSide === 'before'"
                class="vw-dur"
                :style="{ right: `calc(${100 - v.start}% + 6px)` }"
                aria-hidden="true"
              >{{ v.durText }}</span>
              <VChartTooltip
                v-if="hover === i"
                :visible="true"
                :x="(v.isSpan ? v.end : v.start) * laneW / 100"
                :y="-6"
                :bounds-width="laneW + 8"
                :bounds-left="tipLeft"
                :offset="10"
                :title="v.r.label"
                :note="v.r.sub"
                :rows="tipRows(i)"
              />
            </div>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.vw {
  --vw-row-bg: var(--surface);
  --vw-indent: 12px;
  position: relative;
  min-width: 0;
  container-type: inline-size;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  transition: opacity var(--dur-2) var(--ease-out);
}
.vw.is-loading {
  opacity: 0.5;
}
/* Tor konteynerda (telefon, yon panel) nomlar ustuni ~124px: vaqt o'qi asosiy ma'lumot.
   Izoh (model, bosqich matni) bu kenglikda "S..." bo'lib qolardi - foydasiz, shuning uchun
   yashiriladi; u qator tooltipida (hover/tegish) va tanlangan bosqich panelida bor.
   124 = eng uzun nom (uz-Cyrl "Биринчи кадр" ~95px, ru "Первое слово" ~94px) + 2-daraja
   chekinishi (2 x 8) + chetlar (4 + 4). 112 da ru / uz-Cyrl da bu nomlar kesilib qolardi. */
@container (max-width: 560px) {
  .vw-head,
  .vw-body {
    --vw-label-cur: min(var(--vw-label), 124px);
    --vw-indent: 8px;
  }
}

.vw-head,
.vw-row {
  display: grid;
  grid-template-columns: var(--vw-label-cur, var(--vw-label)) minmax(0, 1fr);
  column-gap: var(--s-3);
}
.vw-head {
  height: 28px;
  align-items: end;
  padding-bottom: var(--s-1_5);
  border-bottom: 1px solid var(--line);
}

/* Yo'lak: foizlar shu ichida - 0% va 100% dagi nuqta chetdan kesilmasin. */
.vw-lane {
  position: absolute;
  inset: 0 8px;
}
.vw-axis {
  position: relative;
  height: 16px;
}
.vw-tick {
  position: absolute;
  top: 0;
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-3);
  white-space: nowrap;
  transform: translateX(-50%);
}
.vw-tick.is-start {
  transform: none;
}
.vw-tick.is-end {
  transform: translateX(-100%);
}

.vw-body {
  position: relative;
}
.vw-grid {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  left: calc(var(--vw-label-cur, var(--vw-label)) + var(--s-3));
  pointer-events: none;
}
.vw-gl {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--viz-grid);
}

.vw-rows {
  position: relative;
  margin: 0;
  padding: var(--s-1) 0 0;
  list-style: none;
}
.vw-row {
  position: relative;
  align-items: center;
  height: 32px;
  border-radius: var(--r-xs);
  cursor: pointer;
  transition: background-color var(--dur-1) var(--ease-out);
}
.vw-row.is-hover {
  --vw-row-bg: color-mix(in srgb, var(--fill) 70%, var(--surface));
  background: var(--vw-row-bg);
}
.vw-row.is-selected {
  --vw-row-bg: var(--fill);
  background: var(--vw-row-bg);
}
.vw-row:focus-visible {
  outline-offset: -2px;
}

.vw-name {
  display: flex;
  align-items: baseline;
  gap: var(--s-2);
  min-width: 0;
  padding-inline-end: var(--s-1);
  margin-inline-start: var(--s-2);
  overflow: hidden;
  white-space: nowrap;
}
.vw-label {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text);
}
.vw-sub {
  flex: 1 1 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: var(--fs-caption);
  color: var(--text-3);
}
.vw-status {
  flex: none;
  align-self: center;
}
.vw-status.is-error {
  color: var(--crit-text);
}
.vw-status.is-warn {
  color: var(--warn-text);
}

.vw-track {
  position: relative;
  height: 100%;
}
.vw-bar {
  position: absolute;
  top: 50%;
  height: 8px;
  margin-top: -4px;
  border-radius: 4px;
  background: var(--c);
}
/* Nuqta: 8px + 2px qator foni rangidagi halqa (hover/tanlovda ham "kesilgan" ko'rinadi). */
.vw-dot {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  margin: -6px 0 0 -6px;
  border-radius: 50%;
  background: var(--c);
  border: 2px solid var(--vw-row-bg);
  transition: border-color var(--dur-1) var(--ease-out);
}
/* Davomiylik - Inter tabular (mono emas): mono'da o'nlik vergul va bo'shliq raqam
   kengligida, "1,8 s" sochilib ko'rinadi. */
.vw-dur {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-3);
  white-space: nowrap;
  pointer-events: none;
}

.vw-row.is-skeleton {
  cursor: default;
}
.vw-skel {
  position: absolute;
  top: 50%;
  height: 8px;
  margin-top: -4px;
  border-radius: 4px;
  background: var(--fill);
}

.vw-empty {
  margin: 0;
  padding: var(--s-8) 0;
  text-align: center;
  color: var(--text-3);
}

/* Tor konteyner: asosiy qoidalardan KEYIN turishi kerak (bir xil aniqlik - oxirgisi yutadi). */
@container (max-width: 560px) {
  .vw-name {
    margin-inline-start: var(--s-1);
  }
  .vw-sub {
    display: none;
  }
}
</style>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import VChartLegend from './VChartLegend.vue'
import VChartTooltip from './VChartTooltip.vue'
import { cssColor, type LegendItem, type StackPart, type TooltipRow } from './scale'
import { fmtNumber, fmtPercent } from '../format'

/**
 * Qism va butun: bitta gorizontal tasma, bo'laklar orasida 2px sirt bo'shlig'i
 * (chegara chizig'i emas - oq joyning o'zi ajratadi). Ostida afsona qiymat va ulush
 * bilan - u shu grafikning jadvali ham, shuning uchun alohida jadval tugmasi yo'q.
 *
 * - percent: tasma butun kenglikni egallaydi (ulushlar).
 * - absolute: tasma uzunligi = yig'indi / max (bir nechta tasmani solishtirish).
 */
const props = withDefaults(
  defineProps<{
    parts: StackPart[]
    mode?: 'percent' | 'absolute'
    /** absolute rejimda shkala chegarasi (standart - yig'indi). */
    max?: number
    thickness?: number
    legend?: 'inline' | 'list' | 'none'
    valueFormat?: (v: number) => string
    label?: string
    loading?: boolean
  }>(),
  { mode: 'percent', thickness: 12, legend: 'inline' },
)

const { t, locale } = useI18n({ useScope: 'global' })

const fmt = computed(() => props.valueFormat ?? ((v: number) => fmtNumber(v, locale.value)))

const clean = computed(() =>
  props.parts.map((p) => ({ ...p, value: Number.isFinite(p.value) && p.value > 0 ? p.value : 0 })),
)
const total = computed(() => clean.value.reduce((s, p) => s + p.value, 0))

const share = (v: number) => (total.value > 0 ? v / total.value : 0)
const shareText = (v: number) => fmtPercent(share(v), share(v) < 0.1 && share(v) > 0 ? 1 : 0, locale.value)

const fillPct = computed(() => {
  if (props.mode === 'percent') return 100
  const max = Math.max(props.max ?? total.value, total.value)
  return max > 0 ? (total.value / max) * 100 : 0
})

const segments = computed(() => clean.value.filter((p) => p.value > 0))

const legendItems = computed<LegendItem[]>(() =>
  clean.value.map((p) => ({
    key: p.key,
    label: p.label,
    color: p.color,
    mark: 'rect',
    value: fmt.value(p.value),
    share: shareText(p.value),
  })),
)

const ariaSummary = computed(() => {
  const body = clean.value.map((p) => `${p.label} ${fmt.value(p.value)} (${shareText(p.value)})`).join(', ')
  return props.label ? `${props.label}: ${body}` : body
})

/* ---- hover ---- */
const root = ref<HTMLElement | null>(null)
const hover = ref<string | null>(null)
const tip = ref({ x: 0, y: 0 })
const fromLegend = ref(false)

function onSegEnter(key: string, e: PointerEvent) {
  fromLegend.value = false
  hover.value = key
  const r = root.value?.getBoundingClientRect()
  const s = (e.currentTarget as HTMLElement).getBoundingClientRect()
  if (r) tip.value = { x: s.left + s.width / 2 - r.left, y: s.top - r.top }
}

function onLegendHighlight(key: string | null) {
  fromLegend.value = true
  hover.value = key
}

const tipRows = computed<TooltipRow[]>(() => {
  const p = clean.value.find((x) => x.key === hover.value)
  if (!p) return []
  return [{ key: p.key, label: shareText(p.value), value: fmt.value(p.value), color: p.color, mark: 'rect' }]
})
const tipTitle = computed(() => clean.value.find((x) => x.key === hover.value)?.label ?? '')
</script>

<template>
  <figure ref="root" class="vsb" :class="{ 'is-loading': loading }" :aria-busy="loading || undefined">
    <div class="vsb-track" :style="{ height: `${thickness}px` }" role="img" :aria-label="ariaSummary">
      <div
        v-if="total > 0"
        class="vsb-bar"
        :class="{ 'is-abs': mode === 'absolute' }"
        :style="{ width: `${fillPct}%` }"
        @pointerleave="hover = null"
      >
        <span
          v-for="s in segments"
          :key="s.key"
          class="vsb-seg"
          :class="{ 'is-dim': hover !== null && hover !== s.key }"
          :style="{ flexGrow: s.value, '--c': cssColor(s.color) }"
          @pointerenter="onSegEnter(s.key, $event)"
        />
      </div>
      <div v-else class="vsb-none" />
    </div>

    <VChartLegend
      v-if="legend !== 'none'"
      class="vsb-legend"
      :items="legendItems"
      :layout="legend === 'list' ? 'list' : 'inline'"
      @highlight="onLegendHighlight"
    />
    <p v-if="total === 0 && !loading && legend === 'none'" class="vsb-empty">{{ t('ui.noData') }}</p>

    <VChartTooltip
      :visible="hover !== null && !fromLegend && tipRows.length > 0"
      :x="tip.x"
      :y="tip.y"
      :bounds-width="root?.clientWidth ?? 0"
      placement="above"
      :offset="8"
      :title="tipTitle"
      :rows="tipRows"
    />
  </figure>
</template>

<style scoped>
.vsb {
  position: relative;
  min-width: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.vsb.is-loading {
  opacity: 0.5;
}
.vsb-track {
  position: relative;
  width: 100%;
}
.vsb-bar {
  display: flex;
  /* 2px sirt bo'shlig'i - chegara chizig'i emas. */
  gap: 2px;
  height: 100%;
  transition: width var(--dur-3) var(--ease-out);
}
.vsb-seg {
  position: relative;
  flex-basis: 0;
  min-width: 2px;
  height: 100%;
  background: var(--c);
  transition: opacity var(--dur-1) var(--ease-out);
}
/* Nishon belgidan kattaroq: 12px tasmani ko'zlab urish shart emas. */
.vsb-seg::before {
  content: '';
  position: absolute;
  inset: -10px 0;
}
/* Ulush tasmasida ikkala tashqi uch yumaloq; mutlaq rejimda asos (chap) to'g'ri. */
.vsb-seg:first-child {
  border-start-start-radius: 4px;
  border-end-start-radius: 4px;
}
.vsb-seg:last-child {
  border-start-end-radius: 4px;
  border-end-end-radius: 4px;
}
.is-abs .vsb-seg:first-child {
  border-start-start-radius: 0;
  border-end-start-radius: 0;
}
.vsb-seg.is-dim {
  opacity: 0.35;
}
.vsb-none {
  height: 100%;
  border-radius: 4px;
  background: var(--fill);
}
.vsb-legend {
  margin-top: var(--s-4);
}
.vsb-legend.is-list {
  margin-top: var(--s-3);
}
.vsb-empty {
  margin: var(--s-2) 0 0;
  font-size: var(--fs-caption);
  color: var(--text-3);
}
</style>

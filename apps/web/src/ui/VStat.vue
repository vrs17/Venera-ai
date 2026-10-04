<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-vue-next'
import VSkeleton from './VSkeleton.vue'
import VSparkline from './charts/VSparkline.vue'
import { fmtNumber, fmtPercent } from './format'

/**
 * Ko'rsatkich kartochkasi: nom, katta qiymat, oldingi davrga nisbatan farq, trend.
 *
 * - Katta raqam proporsional shaklda (tabular-nums emas): "121" katta o'lchamda bo'sh
 *   ko'rinmasin. Jadvallarda esa - tabular.
 * - Farq rangi faqat yo'nalishning MA'NOSI bo'lsa: `positiveIsGood` true - o'sish yashil,
 *   false (xatolar, kechikish) - o'sish qizil, null - doim neytral. Rang yolg'iz emas:
 *   yonida strelka va foiz bor.
 * - Birinchi yuklashda skelet; qayta yuklashda eski qiymat xiralashib turadi.
 * - `to` - butun karta havola (sichqoncha va klaviatura uchun bitta katta nishon).
 */
const props = withDefaults(
  defineProps<{
    label: string
    /** Raqam (format bilan) yoki tayyor satr. */
    value: number | string | null | undefined
    format?: (v: number) => string
    unit?: string
    /** Oldingi davr qiymati - farq shundan hisoblanadi. */
    previous?: number | null
    /** Tayyor farq (ulush: 0.12 = +12%); `previous` dan ustun. */
    delta?: number | null
    positiveIsGood?: boolean | null
    /** Farq nimaga nisbatan ("oldingi 7 kun"). */
    deltaLabel?: string
    trend?: (number | null)[]
    trendColor?: string
    loading?: boolean
    to?: RouteLocationRaw
    variant?: 'card' | 'plain'
  }>(),
  { positiveIsGood: true, variant: 'card', trendColor: '--viz-1' },
)

defineSlots<{
  /** O'z sparkline/grafikingiz (standart - `trend` dan VSparkline). */
  spark?(): unknown
}>()

const { locale } = useI18n({ useScope: 'global' })

const hasValue = computed(() => props.value !== null && props.value !== undefined && props.value !== '')
const skeleton = computed(() => props.loading && !hasValue.value)

const display = computed(() => {
  const v = props.value
  if (typeof v === 'number') return Number.isFinite(v) ? (props.format ? props.format(v) : fmtNumber(v, locale.value)) : '—'
  return v === null || v === undefined || v === '' ? '—' : v
})

const change = computed<number | null>(() => {
  if (typeof props.delta === 'number' && Number.isFinite(props.delta)) return props.delta
  const v = props.value
  const p = props.previous
  if (typeof v !== 'number' || typeof p !== 'number' || !Number.isFinite(v) || !Number.isFinite(p)) return null
  // Noldan o'sish - foizi cheksiz; hech narsa ko'rsatmaymiz, "∞%" yolg'on aniqlik.
  if (p === 0) return v === 0 ? 0 : null
  return (v - p) / Math.abs(p)
})

const deltaInfo = computed(() => {
  const d = change.value
  if (d === null) return null
  const dir: 'up' | 'down' | 'flat' = d > 0.0005 ? 'up' : d < -0.0005 ? 'down' : 'flat'
  let tone: 'good' | 'crit' | 'neutral' = 'neutral'
  if (dir !== 'flat' && props.positiveIsGood !== null) {
    tone = (dir === 'up') === props.positiveIsGood ? 'good' : 'crit'
  }
  const abs = Math.abs(d)
  const text = fmtPercent(abs, abs > 0 && abs < 0.1 ? 1 : 0, locale.value)
  const signed = fmtPercent(d, abs > 0 && abs < 0.1 ? 1 : 0, locale.value, true)
  return { dir, tone, text, signed }
})

const icon = computed(() => {
  const dir = deltaInfo.value?.dir
  return dir === 'up' ? ArrowUpRight : dir === 'down' ? ArrowDownRight : Minus
})

const hasSpark = computed(() => !!props.trend && props.trend.length > 1)
</script>

<template>
  <component
    :is="to ? RouterLink : 'div'"
    :to="to"
    class="vs"
    :class="[`is-${variant}`, { 'is-link': !!to, 'is-busy': loading && hasValue }]"
    :aria-busy="loading || undefined"
  >
    <div class="vs-in" :class="{ 'has-spark': hasSpark || !!$slots.spark }">
      <div class="vs-top">
        <span class="vs-label">{{ label }}</span>
        <ArrowUpRight v-if="to" class="vs-go" :size="14" :stroke-width="1.75" aria-hidden="true" />
      </div>

      <div class="vs-value">
        <VSkeleton v-if="skeleton" :width="96" :height="28" radius="sm" />
        <template v-else>
          <span class="vs-num">{{ display }}</span>
          <span v-if="unit && display !== '—'" class="vs-unit">{{ unit }}</span>
        </template>
      </div>

      <div class="vs-delta" :class="deltaInfo ? `is-${deltaInfo.tone}` : undefined">
        <VSkeleton v-if="skeleton" :width="56" :height="12" />
        <template v-else-if="deltaInfo">
          <span class="vs-delta-val" aria-hidden="true">
            <component :is="icon" :size="14" :stroke-width="2" />
            {{ deltaInfo.text }}
          </span>
          <span class="sr-only">{{ deltaInfo.signed }}</span>
          <span v-if="deltaLabel" class="vs-delta-label">{{ deltaLabel }}</span>
        </template>
      </div>

      <div v-if="hasSpark || $slots.spark" class="vs-spark">
        <VSkeleton v-if="skeleton" width="100%" :height="28" radius="sm" />
        <slot v-else name="spark">
          <VSparkline :values="trend ?? []" fluid muted decorative :color="trendColor" />
        </slot>
      </div>
    </div>
  </component>
</template>

<style scoped>
/* container-type kenglikni kontentdan uzadi - flex qatorda 0 ga tushib qolmasin. */
.vs {
  display: block;
  width: 100%;
  min-width: 0;
  color: inherit;
  text-decoration: none;
  container-type: inline-size;
}
.vs.is-card {
  padding: var(--s-5);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  transition:
    border-color var(--dur-1) var(--ease-out),
    box-shadow var(--dur-2) var(--ease-out);
}
.vs.is-link {
  cursor: pointer;
}
.vs.is-link:focus-visible {
  outline-offset: 2px;
  border-radius: var(--r-lg);
}
@media (hover: hover) {
  .vs.is-card.is-link:hover {
    border-color: var(--line-strong);
    box-shadow: var(--e1);
  }
  .vs.is-link:hover .vs-go {
    opacity: 1;
    transform: none;
  }
}

/* Tor karta: trend pastda butun kenglikda; keng karta: o'ngda, qiymat yonida. */
.vs-in {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    'top'
    'value'
    'delta'
    'spark';
  row-gap: var(--s-1_5);
}
@container (min-width: 260px) {
  .vs-in.has-spark {
    grid-template-columns: minmax(0, 1fr) 96px;
    grid-template-areas:
      'top top'
      'value spark'
      'delta spark';
    column-gap: var(--s-4);
  }
  .vs-in.has-spark .vs-spark {
    align-self: end;
    margin-top: 0;
  }
}

.vs-top {
  grid-area: top;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-2);
  min-width: 0;
  margin-bottom: var(--s-0_5);
}
.vs-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  color: var(--text-3);
}
.vs-go {
  flex: none;
  color: var(--text-3);
  opacity: 0;
  transform: translate(-2px, 2px);
  transition:
    opacity var(--dur-1) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}

.vs-value {
  grid-area: value;
  display: flex;
  align-items: baseline;
  gap: var(--s-1);
  min-width: 0;
  min-height: var(--lh-title-1);
  transition: opacity var(--dur-2) var(--ease-out);
}
.is-busy .vs-value,
.is-busy .vs-delta,
.is-busy .vs-spark {
  opacity: 0.5;
}
.vs-num {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-title-1);
  line-height: var(--lh-title-1);
  font-weight: 600;
  letter-spacing: -0.022em;
  /* proporsional raqamlar - katta alohida son uchun */
  font-variant-numeric: normal;
  color: var(--text);
}
.vs-unit {
  flex: none;
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  font-weight: 500;
  color: var(--text-3);
}

.vs-delta {
  grid-area: delta;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s-0_5) var(--s-2);
  min-height: var(--lh-caption);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  color: var(--text-3);
  transition: opacity var(--dur-2) var(--ease-out);
}
.vs-delta-val {
  display: inline-flex;
  align-items: center;
  gap: var(--s-0_5);
  font-variant-numeric: tabular-nums;
}
.vs-delta.is-good .vs-delta-val {
  color: var(--good-text);
}
.vs-delta.is-crit .vs-delta-val {
  color: var(--crit-text);
}
.vs-delta.is-neutral .vs-delta-val {
  color: var(--text-2);
}
.vs-delta-label {
  color: var(--text-3);
  font-weight: 400;
}

.vs-spark {
  grid-area: spark;
  min-width: 0;
  height: 28px;
  margin-top: var(--s-2);
  transition: opacity var(--dur-2) var(--ease-out);
}
</style>

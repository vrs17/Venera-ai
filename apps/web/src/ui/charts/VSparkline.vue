<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { areaPath, cssColor, linePath, splitRuns, useElementSize, type Pt } from './scale'
import { fmtCompact } from '../format'
import { useId } from '../composables/useId'

/**
 * Kichik trend chizig'i: o'qsiz, to'rsiz, oxirgi nuqtada doira. Stat kartochkada
 * "yo'nalish"ni ko'rsatadi, aniq qiymatni emas (u kartaning o'zida).
 *
 * `muted` - chiziq jim kulrang, faqat oxirgi bo'lak va nuqta rangda: ko'z darhol
 * "hozir"ga tushadi, 5 ta kartadagi 5 ta ko'k chiziq shovqin qilmaydi.
 */
const props = withDefaults(
  defineProps<{
    values: (number | null)[]
    /** px; `fluid` bo'lsa konteyner kengligi. */
    width?: number
    height?: number
    fluid?: boolean
    color?: string
    area?: boolean
    muted?: boolean
    curve?: 'linear' | 'monotone'
    /** Ekran o'quvchi uchun; berilmasa "birinchi → oxirgi" qiymatdan yig'iladi. */
    label?: string
    /** Faqat bezak (qiymat yonida allaqachon yozilgan) - ekran o'quvchidan yashiriladi. */
    decorative?: boolean
  }>(),
  { width: 96, height: 28, color: '--viz-1', curve: 'monotone' },
)

const { locale } = useI18n({ useScope: 'global' })

const el = ref<HTMLElement | null>(null)
const { width: measured } = useElementSize(el)
const W = computed(() => (props.fluid ? measured.value : props.width))

const PAD = 6 // nuqta (r=4) + 2px halqa kesilmasin
const clipId = useId('vsp-tail')

const geo = computed(() => {
  const w = W.value
  const h = props.height
  const vals = props.values.map((v) => (typeof v === 'number' && Number.isFinite(v) ? v : null))
  const nums = vals.filter((v): v is number => v !== null)
  if (w <= 0 || nums.length === 0) return null
  const lo = Math.min(...nums)
  const hi = Math.max(...nums)
  const n = vals.length
  const x = (i: number) => (n === 1 ? w / 2 : PAD + (i / (n - 1)) * (w - PAD * 2))
  // Tekis qator o'rtada yotadi (pastga yopishib "nol" kabi o'qilmasin).
  const y = (v: number) => (hi === lo ? h / 2 : h - PAD - ((v - lo) / (hi - lo)) * (h - PAD * 2))
  const pts: (Pt | null)[] = vals.map((v, i) => (v === null ? null : { x: x(i), y: y(v) }))
  let lastI = n - 1
  while (lastI >= 0 && pts[lastI] === null) lastI--
  const last = pts[lastI] as Pt
  let area = ''
  if (props.area) {
    area = splitRuns(pts)
      .map((run) => areaPath(run, run.map((p) => ({ x: p.x, y: h })), props.curve))
      .join('')
  }
  // muted: oxirgi bo'lak rangda. Egri chiziqning o'zini kesib olamiz (clipPath) -
  // alohida to'g'ri chiziq egri ustiga aniq tushmaydi.
  let prevI = lastI - 1
  while (prevI >= 0 && pts[prevI] === null) prevI--
  const tailX = props.muted && prevI >= 0 && lastI - prevI === 1 ? (pts[prevI] as Pt).x : null
  return { line: linePath(pts, props.curve), area, last, tailX, first: nums[0], lastV: nums[nums.length - 1] }
})

const aria = computed(() => {
  if (props.decorative) return ''
  if (props.label) return props.label
  const g = geo.value
  if (!g) return ''
  return `${fmtCompact(g.first, locale.value)} → ${fmtCompact(g.lastV, locale.value)}`
})
</script>

<template>
  <span
    ref="el"
    class="vsp"
    :class="{ 'is-fluid': fluid, 'is-muted': muted }"
    :style="{ width: fluid ? '100%' : `${width}px`, height: `${height}px`, '--c': cssColor(color) }"
    :role="aria ? 'img' : undefined"
    :aria-label="aria || undefined"
    :aria-hidden="aria ? undefined : 'true'"
  >
    <svg v-if="geo" :width="W" :height="height" :viewBox="`0 0 ${W} ${height}`" aria-hidden="true" focusable="false">
      <path v-if="geo.area" class="vsp-area" :d="geo.area" />
      <path class="vsp-line" :d="geo.line" />
      <template v-if="geo.tailX !== null">
        <clipPath :id="clipId">
          <rect :x="geo.tailX" :y="-PAD" :width="W - geo.tailX + PAD" :height="height + PAD * 2" />
        </clipPath>
        <path class="vsp-tail" :d="geo.line" :clip-path="`url(#${clipId})`" />
      </template>
      <circle class="vsp-dot" :cx="geo.last.x" :cy="geo.last.y" r="4" />
    </svg>
    <span v-else class="vsp-none" />
  </span>
</template>

<style scoped>
.vsp {
  position: relative;
  display: inline-block;
  flex: none;
  vertical-align: middle;
}
.vsp.is-fluid {
  display: block;
}
svg {
  display: block;
  overflow: visible;
}
.vsp-line {
  fill: none;
  stroke: var(--c);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.is-muted .vsp-line {
  stroke: var(--text-4);
}
.vsp-tail {
  fill: none;
  stroke: var(--c);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.vsp-area {
  fill: var(--c);
  fill-opacity: 0.1;
}
.is-muted .vsp-area {
  fill: var(--text-4);
  fill-opacity: 0.12;
}
/* 8px nuqta + tashqarida 2px sirt halqasi (paint-order: stroke - rang yeyilmaydi). */
.vsp-dot {
  fill: var(--c);
  stroke: var(--surface);
  stroke-width: 4;
  paint-order: stroke;
}
.vsp-none {
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  border-top: 1px solid var(--line);
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { cssColor } from './scale'
import { fmtNumber, fmtPercent } from '../format'

/**
 * Qiymat / maksimum tasmasi (retrieval score, kvota, ulush). Iz (track) - to'ldiruvchi
 * rangning o'zidan och qadam: ko'k ustida ko'k, sariq ustida sariq - holat butun
 * tasmada o'qiladi, kulrang iz "bo'sh" bo'lib ko'rinmaydi.
 *
 * Chegara (warnAt / critAt) berilsa rang holatga o'tadi. Holat rangi hech qachon
 * yolg'iz kelmaydi - yonida qiymat matni bo'lishi kerak (chaqiruvchi qo'yadi).
 */
const props = withDefaults(
  defineProps<{
    value: number | null
    max?: number
    min?: number
    color?: string
    /** Shu qiymatdan (yuqori) sariq. `invert` bilan - shu qiymatdan past. */
    warnAt?: number
    critAt?: number
    /** Kam - yomon (masalan moslik bali). */
    invert?: boolean
    size?: 'sm' | 'md'
    label?: string
    /** aria-valuetext; berilmasa raqam. */
    valueText?: string
  }>(),
  { max: 1, min: 0, color: '--viz-1', size: 'md' },
)

const { locale } = useI18n({ useScope: 'global' })

const v = computed(() => (typeof props.value === 'number' && Number.isFinite(props.value) ? props.value : null))

const pct = computed(() => {
  if (v.value === null) return 0
  const span = props.max - props.min || 1
  return Math.max(0, Math.min(1, (v.value - props.min) / span)) * 100
})

const tone = computed<'crit' | 'warn' | null>(() => {
  const x = v.value
  if (x === null) return null
  const hit = (edge: number | undefined) => edge !== undefined && (props.invert ? x <= edge : x >= edge)
  if (hit(props.critAt)) return 'crit'
  if (hit(props.warnAt)) return 'warn'
  return null
})

const fill = computed(() => (tone.value ? `var(--${tone.value})` : cssColor(props.color)))
</script>

<template>
  <span
    class="vm"
    :class="`is-${size}`"
    :style="{ '--c': fill }"
    role="meter"
    :aria-label="label"
    :aria-valuemin="min"
    :aria-valuemax="max"
    :aria-valuenow="v ?? undefined"
    :aria-valuetext="valueText ?? (v === null ? undefined : max === 1 && min === 0 ? fmtPercent(v, 0, locale) : fmtNumber(v, locale))"
  >
    <span class="vm-fill" :style="{ width: pct > 0 ? `max(${size === 'sm' ? 4 : 6}px, ${pct}%)` : '0px' }" />
  </span>
</template>

<style scoped>
.vm {
  position: relative;
  display: block;
  width: 100%;
  min-width: 24px;
  overflow: hidden;
  border-radius: var(--r-full);
  /* Iz - o'sha rangning sirt bilan aralashgan och qadami (tokenlardan, xom rang yo'q). */
  background: color-mix(in srgb, var(--c) 16%, var(--surface));
  transition: background-color var(--dur-2) var(--ease-out);
}
.vm.is-md {
  height: 6px;
}
.vm.is-sm {
  height: 4px;
}
.vm-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: var(--c);
  transition:
    width var(--dur-3) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
</style>

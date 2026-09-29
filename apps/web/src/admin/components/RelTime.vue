<script lang="ts">
import { ref } from 'vue'

// Bitta umumiy soat: sahifada 50 ta RelTime bo'lsa ham bitta taymer. U faqat kamida
// bitta RelTime ekranda turgan paytda ishlaydi.
const now = ref(Date.now())
let users = 0
let timer: ReturnType<typeof setInterval> | undefined

function acquire() {
  if (users++ === 0) {
    now.value = Date.now()
    timer = setInterval(() => (now.value = Date.now()), 30_000)
  }
}
function release() {
  if (--users === 0) clearInterval(timer)
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import VTooltip from '../../ui/VTooltip.vue'
import { fmtDateTime, fmtRelative, toDate } from '../../ui/format'
import type { DateInput } from '../../ui/format'

/**
 * Nisbiy vaqt ("5 daq oldin") - aniq sana va soat tooltipda. O'z-o'zidan yangilanadi
 * (30 soniyada bir): ochiq turgan jadvaldagi "hozir" bir soatdan keyin ham "hozir" qolmasin.
 *
 * Props:
 * - `value` - ISO satr, epoch ms yoki Date; bo'sh - "—".
 * - `long`  - uzun shakl ("5 daqiqa oldin") - sarlavha va meta qatorlar uchun.
 *
 *   <RelTime :value="turn.startedAt" />
 */
const props = defineProps<{
  value: DateInput
  long?: boolean
}>()

const { locale } = useI18n({ useScope: 'global' })

onMounted(acquire)
onBeforeUnmount(release)

const date = computed(() => toDate(props.value))
const relative = computed(() =>
  date.value ? fmtRelative(date.value, locale.value, { now: now.value, style: props.long ? 'long' : 'short' }) : '—',
)
const absolute = computed(() => (date.value ? fmtDateTime(date.value, locale.value, 'long') : ''))
</script>

<template>
  <VTooltip v-if="date" :text="absolute">
    <time class="rt" :datetime="date.toISOString()">{{ relative }}</time>
  </VTooltip>
  <span v-else class="rt is-empty">—</span>
</template>

<style scoped>
.rt {
  color: inherit;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.rt.is-empty {
  color: var(--text-4);
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { fmtMs } from '../../ui/format'
import type { ProbeStep } from './types'

/**
 * Sinov qadamlari - tik ro'yxat: nomi, vaqti (ms) va eng sekin qadamga nisbatan chiziq,
 * ostida tafsilot (`kalit: qiymat`). Uzun qiymat (matn, ro'yxat) qisqartiriladi - to'liq
 * javob natija qismida.
 */
const props = defineProps<{ steps: ProbeStep[] }>()
const { t, locale } = useI18n({ useScope: 'global' })

const max = computed(() => Math.max(1, ...props.steps.map((s) => s.ms || 0)))
const total = computed(() => props.steps.reduce((a, s) => a + (s.ms || 0), 0))

function show(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value.length > 140 ? `${value.slice(0, 139)}…` : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  const json = JSON.stringify(value)
  return json.length > 140 ? `${json.slice(0, 139)}…` : json
}

const ms = (v: number) => fmtMs(v, locale.value)
</script>

<template>
  <ol class="pt" :aria-label="t('admin.osmap.probe.trace')">
    <li v-for="(s, i) in steps" :key="`${i}-${s.step}`" class="pt__step">
      <span class="pt__dot" aria-hidden="true" />
      <div class="pt__main">
        <div class="pt__head">
          <span class="pt__name">{{ s.step }}</span>
          <span class="pt__ms">{{ ms(s.ms) }}</span>
        </div>
        <span class="pt__bar" aria-hidden="true"><span :style="{ width: `${Math.max(2, (s.ms / max) * 100)}%` }" /></span>
        <dl v-if="Object.keys(s.detail || {}).length" class="pt__detail">
          <div v-for="(v, k) in s.detail" :key="k">
            <dt>{{ k }}</dt>
            <dd>{{ show(v) }}</dd>
          </div>
        </dl>
      </div>
    </li>
    <li class="pt__total">
      <span>{{ t('admin.osmap.probe.total') }}</span>
      <span>{{ ms(total) }}</span>
    </li>
  </ol>
</template>

<style scoped>
.pt {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.pt__step {
  position: relative;
  display: flex;
  gap: 10px;
  padding: 0 0 10px;
}
/* Qadamlar orasidagi tik chiziq. */
.pt__step::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 12px;
  bottom: 0;
  width: 2px;
  background: var(--line);
}
.pt__dot {
  position: relative;
  flex: none;
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border: 2px solid var(--brand);
  border-radius: 50%;
  background: var(--surface);
}
.pt__main {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.pt__head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}
.pt__name {
  font-family: var(--font-mono);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.pt__ms {
  flex: none;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.pt__bar {
  display: block;
  height: 3px;
  border-radius: 2px;
  background: var(--fill);
}
.pt__bar > span {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: var(--brand);
}
.pt__detail {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  margin: 0;
  font-size: 12px;
}
.pt__detail div {
  display: flex;
  gap: 4px;
  min-width: 0;
  max-width: 100%;
}
.pt__detail dt {
  color: var(--text-3);
}
.pt__detail dd {
  margin: 0;
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
}
.pt__total {
  display: flex;
  justify-content: space-between;
  padding-top: 6px;
  border-top: 1px solid var(--line);
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>

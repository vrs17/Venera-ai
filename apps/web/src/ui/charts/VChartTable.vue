<script setup lang="ts">
import type { ChartTableColumn } from './scale'

/**
 * Grafikning jadval egizagi (WCAG): har bir qiymat tooltipsiz ham o'qiladi.
 * Grafik bilan bir xil balandlikda turadi va ichida aylanadi - ko'rinish
 * almashganda sahifa sakramaydi.
 */
defineProps<{
  columns: ChartTableColumn[]
  rows: Record<string, string>[]
  caption?: string
  /** Ramka balandligi (grafik balandligi bilan teng), px. */
  height?: number
}>()
</script>

<template>
  <div class="vctab" :style="height ? { height: `${height}px` } : undefined" tabindex="0" role="region" :aria-label="caption">
    <table>
      <caption v-if="caption" class="sr-only">{{ caption }}</caption>
      <thead>
        <tr>
          <th v-for="c in columns" :key="c.key" scope="col" :class="{ 'is-end': c.align === 'end' }">{{ c.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in rows" :key="i">
          <template v-for="(c, ci) in columns" :key="c.key">
            <th v-if="ci === 0" scope="row" :class="{ 'is-end': c.align === 'end' }">{{ r[c.key] }}</th>
            <td v-else :class="{ 'is-end': c.align === 'end' }">{{ r[c.key] }}</td>
          </template>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.vctab {
  overflow: auto;
  overscroll-behavior: contain;
  border-radius: var(--r-xs);
}
.vctab:focus-visible {
  outline-offset: -2px;
}
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
th,
td {
  height: 32px;
  padding: 0 var(--s-3);
  text-align: start;
  white-space: nowrap;
  border-bottom: 1px solid var(--line);
}
th:first-child,
td:first-child {
  padding-inline-start: 0;
}
th:last-child,
td:last-child {
  padding-inline-end: 0;
}
thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  color: var(--text-3);
}
tbody th {
  font-weight: 400;
  color: var(--text-2);
}
td {
  color: var(--text);
}
.is-end {
  text-align: end;
  font-variant-numeric: tabular-nums;
}
tbody tr:last-child > * {
  border-bottom: 0;
}
</style>

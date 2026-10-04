<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Unplug } from 'lucide-vue-next'
import VDataTable from '../../ui/VDataTable.vue'
import type { DataTableColumn } from '../../ui/VDataTable.vue'
import VEmpty from '../../ui/VEmpty.vue'
import type { ApiCall } from '../types'
import DurationText from '../components/DurationText.vue'
import StatusDot from '../components/StatusDot.vue'
import { fmtUnit, unitEntries } from '../components/units'

/**
 * "API" yorlig'i: shu savol davomidagi tashqi chaqiruvlar (xizmat, amal, holat, ms,
 * birliklar) - vaqt tartibida. Xato matni holat nuqtasining tooltipida.
 */
const props = defineProps<{ calls: ApiCall[] }>()

const { t, te, locale } = useI18n({ useScope: 'global' })

const serviceLabel = (s: string) => (te(`admin.usage.service.${s}`) ? t(`admin.usage.service.${s}`) : s)

const columns = computed<DataTableColumn<ApiCall>[]>(() => [
  { key: 'service', label: t('admin.col.service'), width: '30%', format: (c) => serviceLabel(c.service) },
  { key: 'op', label: t('admin.col.op'), mono: true },
  { key: 'status', label: t('admin.col.status'), width: 56, align: 'center' },
  { key: 'durationMs', label: t('admin.col.latency'), width: 80, align: 'end' },
  { key: 'units', label: t('admin.trace.units'), width: 96, align: 'end' },
])

function statusText(c: ApiCall): string | undefined {
  if (c.status !== 'error') return undefined
  const head = c.httpStatus ? `${t('admin.status.error')} ${c.httpStatus}` : t('admin.status.error')
  return c.error ? `${head} · ${c.error}` : head
}

const units = (c: ApiCall) =>
  unitEntries(c.units)
    .map((u) => fmtUnit(u.key, u.value, locale.value))
    .join(' · ')

const hasCalls = computed(() => props.calls.length > 0)
</script>

<template>
  <VEmpty v-if="!hasCalls" compact :icon="Unplug" :title="t('admin.trace.noApiCalls')" />
  <VDataTable
    v-else
    :rows="calls"
    :columns="columns"
    row-key="id"
    dense
    :label="t('admin.trace.apiCalls')"
  >
    <template #cell-status="{ row }">
      <StatusDot :status="row.status" :label="statusText(row)" hide-label />
    </template>
    <template #cell-durationMs="{ row }">
      <DurationText :ms="row.durationMs" />
    </template>
    <template #cell-units="{ row }">
      <span class="tac-units">{{ units(row) || '—' }}</span>
    </template>
  </VDataTable>
</template>

<style scoped>
.tac-units {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
</style>

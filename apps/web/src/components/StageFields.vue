<script setup lang="ts">
import { computed } from 'vue'
import type { AccessStage, GuardStage, IntentStage, OrchestratorStage } from '../types'

/**
 * Bitta pipeline bosqichining kalit/qiymat jadvali (dasturchi izi). Avval tanlangan
 * kalitlar, oxirida DOIM model, adapter va xom javob (mono). Istalgan turdagi qiymat
 * xavfsiz satrga aylanadi.
 */
const props = defineProps<{
  stage: GuardStage | IntentStage | OrchestratorStage | AccessStage
  highlight: string[]
}>()

type Row = { k: string; v: unknown; muted: boolean; code: boolean }

const rows = computed<Row[]>(() => {
  const record = props.stage as unknown as Record<string, unknown>
  return [
    ...props.highlight.map((k) => ({ k, v: record[k], muted: false, code: false })),
    { k: 'model', v: record.model, muted: true, code: false },
    { k: 'adapter', v: record.adapter, muted: true, code: false },
    { k: 'rawAnswer', v: record.rawAnswer, muted: true, code: true },
  ]
})

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}
</script>

<template>
  <dl class="fields">
    <template v-for="row in rows" :key="row.k">
      <dt :class="{ 'is-muted': row.muted }">{{ row.k }}</dt>
      <dd :class="{ 'is-muted': row.muted, 'is-code': row.code }">{{ formatValue(row.v) }}</dd>
    </template>
  </dl>
</template>

<style scoped>
.fields {
  display: grid;
  grid-template-columns: minmax(96px, 120px) 1fr;
  gap: var(--s-1_5) var(--s-3);
  margin: 0;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.fields dt {
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
}
.fields dd {
  margin: 0;
  min-width: 0;
  color: var(--text);
  overflow-wrap: anywhere;
}
.fields .is-muted {
  color: var(--text-3);
}
.fields dd.is-code {
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: var(--lh-mono);
  white-space: pre-wrap;
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import type { CSSProperties } from 'vue'
import type { AccessStage, GuardStage, IntentStage, OrchestratorStage } from '../types'

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

function keyStyle(row: Row): CSSProperties {
  return { color: row.muted ? 'var(--text-muted)' : 'var(--text-secondary)', fontWeight: 500, fontSize: '12px' }
}

function valStyle(row: Row): CSSProperties {
  return {
    color: row.muted ? 'var(--text-secondary)' : 'var(--text)',
    wordBreak: 'break-word',
    fontFamily: row.code ? 'ui-monospace, Consolas, monospace' : undefined,
    fontSize: row.code ? '12px' : '13px',
  }
}
</script>

<template>
  <div :style="{ display: 'grid', gridTemplateColumns: '120px 1fr', rowGap: '6px', columnGap: '12px', fontSize: '13px' }">
    <template v-for="row in rows" :key="row.k">
      <div :style="keyStyle(row)">{{ row.k }}</div>
      <div :style="valStyle(row)">{{ formatValue(row.v) }}</div>
    </template>
  </div>
</template>

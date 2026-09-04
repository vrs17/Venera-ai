<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { CSSProperties } from 'vue'
import type {
  AccessStage,
  GuardStage,
  IntentStage,
  OrchestratorStage,
  PipelineResponse,
  RetrievalStage,
} from '../types'
import { ChevronDownIcon } from '../icons'
import StageFields from './StageFields.vue'
import RetrievalList from './RetrievalList.vue'

type FieldsEntry = {
  key: string
  title: string
  summary: string
  ok: boolean
  seconds: number | null
  kind: 'fields'
  stage: GuardStage | IntentStage | OrchestratorStage | AccessStage
  highlight: string[]
}
type RetrievalEntry = {
  key: string
  title: string
  summary: string
  ok: boolean
  seconds: number | null
  kind: 'retrieval'
  retrieval: RetrievalStage
}
type StageEntry = FieldsEntry | RetrievalEntry

const props = withDefaults(
  defineProps<{
    response: PipelineResponse
    /** When true, expand the first trace stage by default (RAG_ADMIN view). */
    defaultOpen?: boolean
  }>(),
  { defaultOpen: false },
)

function fmtSeconds(s: number | null): string {
  if (s == null) return '—'
  return `${s.toFixed(2)}s`
}

const entries = computed<StageEntry[]>(() => {
  const r = props.response
  const list: StageEntry[] = []
  if (r.guard) {
    list.push({
      key: 'guard',
      title: 'Guard',
      summary: `${r.guard.decision} · ${r.guard.reason}`,
      ok: r.guard.safe,
      seconds: r.guard.seconds,
      kind: 'fields',
      stage: r.guard,
      highlight: ['safe', 'decision', 'reason'],
    })
  }
  if (r.intent) {
    list.push({
      key: 'intent',
      title: 'Intent',
      summary: `${r.intent.intent} (${r.intent.confidence})`,
      ok: true,
      seconds: r.intent.seconds,
      kind: 'fields',
      stage: r.intent,
      highlight: ['intent', 'confidence'],
    })
  }
  if (r.orchestrator) {
    list.push({
      key: 'orchestrator',
      title: 'Orchestrator',
      summary: `${r.orchestrator.routeType} → ${r.orchestrator.route}`,
      ok: true,
      seconds: r.orchestrator.seconds,
      kind: 'fields',
      stage: r.orchestrator,
      highlight: ['routeType', 'route', 'targetModule', 'requiresAccessCheck', 'reason'],
    })
  }
  if (r.access) {
    list.push({
      key: 'access',
      title: 'Access',
      summary: `${r.access.decision} · ${r.access.reason}`,
      ok: r.access.allowed,
      seconds: r.access.seconds,
      kind: 'fields',
      stage: r.access,
      highlight: ['allowed', 'decision', 'requiredRole', 'resourceScope', 'reason'],
    })
  }
  if (r.retrieval) {
    const ret = r.retrieval
    const n = ret.results?.length ?? 0
    list.push({
      key: 'retrieval',
      title: 'Retrieval',
      summary: ret.error ? `Error · ${ret.error}` : `${n} chunk${n === 1 ? '' : 's'} from ${ret.collection ?? '—'}`,
      ok: !ret.error,
      seconds: ret.seconds ?? null,
      kind: 'retrieval',
      retrieval: ret,
    })
  }
  return list
})

const openKey = ref<string | null>(props.defaultOpen && entries.value[0] ? entries.value[0].key : null)

function toggle(key: string) {
  openKey.value = openKey.value === key ? null : key
}

// Dots start dim and "ignite" in sequence once the trace mounts.
const lit = ref(false)
let rafId = 0
onMounted(() => {
  rafId = requestAnimationFrame(() => {
    lit.value = true
  })
})
onBeforeUnmount(() => cancelAnimationFrame(rafId))

const rowButtonStyle: CSSProperties = {
  width: '100%',
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  background: 'transparent',
  border: 'none',
  padding: '12px 16px',
  cursor: 'pointer',
  textAlign: 'left',
  transition: 'background 0.15s',
}

function dotStyle(ok: boolean, i: number): CSSProperties {
  const color = ok ? 'var(--ok-fg)' : 'var(--bad-fg)'
  return {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    flexShrink: 0,
    background: lit.value ? color : 'var(--border-hover)',
    boxShadow: lit.value ? `0 0 6px ${color}` : 'none',
    transition: `background 0.3s ease ${i * 0.12}s, box-shadow 0.3s ease ${i * 0.12}s`,
  }
}
</script>

<template>
  <div
    v-if="entries.length === 0"
    :style="{ fontSize: '13px', color: 'var(--text-secondary)', padding: '4px 2px' }"
  >
    No pipeline trace returned.
  </div>

  <div
    v-else
    :style="{
      position: 'relative',
      background: 'var(--surface-sunken)',
      border: '1px solid var(--border)',
      borderRadius: '14px',
      overflow: 'hidden',
    }"
  >
    <!-- The spine: a faint connector threading every stage dot at x≈20px. -->
    <div
      aria-hidden="true"
      :style="{
        position: 'absolute',
        left: '19px',
        top: '14px',
        bottom: '14px',
        width: '2px',
        background: 'var(--border)',
        borderRadius: '2px',
        zIndex: 0,
      }"
    />
    <div
      v-for="(e, i) in entries"
      :key="e.key"
      :style="{ position: 'relative', zIndex: 1, borderTop: i === 0 ? 'none' : '1px solid var(--border-faint)' }"
    >
      <button class="stage-row" :style="rowButtonStyle" @click="toggle(e.key)">
        <span :style="dotStyle(e.ok, i)" />
        <span :style="{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text)', width: '110px', flexShrink: 0 }">{{
          e.title
        }}</span>
        <span
          :title="e.summary"
          :style="{
            fontSize: '13px',
            color: 'var(--text-secondary)',
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }"
          >{{ e.summary }}</span
        >
        <span
          :style="{ fontSize: '12px', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }"
          >{{ fmtSeconds(e.seconds) }}</span
        >
        <ChevronDownIcon :style="{ transform: openKey === e.key ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }" />
      </button>
      <!-- Spring height-morph: grid 0fr->1fr animates the body open/closed. -->
      <div
        :style="{
          display: 'grid',
          gridTemplateRows: openKey === e.key ? '1fr' : '0fr',
          transition: 'grid-template-rows 0.38s var(--spring)',
        }"
      >
        <div :style="{ overflow: 'hidden' }">
          <div :style="{ padding: '4px 16px 16px', background: 'var(--surface-inset)' }">
            <StageFields v-if="e.kind === 'fields'" :stage="e.stage" :highlight="e.highlight" />
            <RetrievalList v-if="e.kind === 'retrieval'" :retrieval="e.retrieval" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

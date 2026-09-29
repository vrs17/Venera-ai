<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown } from 'lucide-vue-next'
import type {
  AccessStage,
  GuardStage,
  IntentStage,
  OrchestratorStage,
  PipelineResponse,
  RetrievalStage,
} from '../types'
import { useId } from '../ui/composables/useId'
import StageFields from './StageFields.vue'
import RetrievalList from './RetrievalList.vue'

/**
 * Dasturchi rejimi: pipeline izi (Guard, Intent, Orchestrator, Access, Retrieval) -
 * bittadan ochiladigan ro'yxat. Faqat `/ask` javobida bor (oqim yo'lida iz yo'q);
 * to'liq iz endi admin panelning "Savol izi" sahifasida. Bosqich nomlari - texnik
 * atamalar, tarjima qilinmaydi.
 */
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
    /** Birinchi bosqich ochiq turib ochilsin. */
    defaultOpen?: boolean
  }>(),
  { defaultOpen: false },
)

const { t } = useI18n({ useScope: 'global' })
const baseId = useId('trace')

function fmtSeconds(s: number | null): string {
  if (s == null) return '—'
  return `${s.toFixed(2)} s`
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
      summary: ret.error ? `Error · ${ret.error}` : `${n} · ${ret.collection ?? '—'}`,
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
</script>

<template>
  <p v-if="entries.length === 0" class="trace__empty">{{ t('chat.traceEmpty') }}</p>

  <div v-else class="trace">
    <div v-for="e in entries" :key="e.key" class="trace__row">
      <button
        :id="`${baseId}-${e.key}`"
        type="button"
        class="trace__head"
        :aria-expanded="openKey === e.key ? 'true' : 'false'"
        :aria-controls="`${baseId}-${e.key}-body`"
        @click="toggle(e.key)"
      >
        <span class="trace__dot" :class="e.ok ? 'is-ok' : 'is-bad'" aria-hidden="true" />
        <span class="trace__title">{{ e.title }}</span>
        <span class="trace__summary" :title="e.summary">{{ e.summary }}</span>
        <span class="trace__sec">{{ fmtSeconds(e.seconds) }}</span>
        <ChevronDown class="trace__chev" :class="{ 'is-open': openKey === e.key }" :size="16" :stroke-width="1.75" aria-hidden="true" />
      </button>
      <div
        v-show="openKey === e.key"
        :id="`${baseId}-${e.key}-body`"
        class="trace__body"
        role="region"
        :aria-labelledby="`${baseId}-${e.key}`"
      >
        <StageFields v-if="e.kind === 'fields'" :stage="e.stage" :highlight="e.highlight" />
        <RetrievalList v-if="e.kind === 'retrieval'" :retrieval="e.retrieval" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.trace__empty {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}
.trace {
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  overflow: hidden;
}
.trace__row + .trace__row {
  border-top: 1px solid var(--line);
}
.trace__head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  width: 100%;
  min-height: 44px;
  padding: 0 var(--s-4);
  text-align: left;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .trace__head:hover {
    background: var(--fill);
  }
}
.trace__dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: var(--r-full);
}
.trace__dot.is-ok { background: var(--good); }
.trace__dot.is-bad { background: var(--crit); }
.trace__title {
  width: 100px;
  flex-shrink: 0;
  font-size: var(--fs-body-sm);
  font-weight: 600;
}
.trace__summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trace__sec {
  flex-shrink: 0;
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  font-variant-numeric: tabular-nums;
}
.trace__chev {
  flex-shrink: 0;
  color: var(--text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
.trace__chev.is-open {
  transform: rotate(180deg);
}
.trace__body {
  padding: var(--s-1) var(--s-4) var(--s-4);
  background: var(--bg-subtle);
}
</style>

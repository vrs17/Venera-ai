<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import type { UIExchange } from '../types'
import type { MsgKey } from '../i18n'
import { CheckIcon, LockIcon, ShieldIcon } from '../icons'
import ResultShell from './ResultShell.vue'
import TraceSkeleton from './TraceSkeleton.vue'
import TraceStages from './TraceStages.vue'
import ThinkingLoader from './ThinkingLoader.vue'
import MessageActions from './MessageActions.vue'
import MarkdownMessage from './MarkdownMessage.vue'

const props = defineProps<{
  exchange: UIExchange
  /**
   * Developer mode shows the full Guard/Intent/Orchestrator/Access trace, the
   * status badge, a loading skeleton and the round-trip time. User mode hides
   * all of that — a "Thinking" loader while in-flight, then just the answer
   * (plus a badge only when the request was blocked or access-denied).
   */
  devMode: boolean
  /** True while any request is in flight — disables Regenerate. */
  busy?: boolean
}>()
const emit = defineEmits<{ regenerate: [] }>()

const { t } = useI18n({ useScope: 'global' })

// Style/icon per status stays static; the human label is resolved via t() at
// render so it follows the active locale.
type StatusMeta = { labelKey: MsgKey; color: string; bg: string; border: string; icon: Component }
const READY: StatusMeta = { labelKey: 'statusReady', color: 'var(--ok-fg)', bg: 'var(--ok-bg)', border: 'var(--ok-bd)', icon: CheckIcon }
const STATUS_META: Record<string, StatusMeta> = {
  READY_FOR_HR_RAG: READY,
  READY_FOR_PUBLIC_RAG: READY,
  READY_FOR_OPENAI: READY,
  PUBLIC_RAG_NO_RELEVANT_CONTEXT: {
    labelKey: 'statusNoContext',
    color: 'var(--text-secondary)',
    bg: 'var(--surface-hover)',
    border: 'var(--border)',
    icon: CheckIcon,
  },
  RAG_DOMAIN_NOT_READY: {
    labelKey: 'statusModuleNotReady',
    color: 'var(--warn-fg)',
    bg: 'var(--warn-bg)',
    border: 'var(--warn-bd)',
    icon: ShieldIcon,
  },
  STOP_ACCESS_DENIED: {
    labelKey: 'statusAccessDenied',
    color: 'var(--warn-fg)',
    bg: 'var(--warn-bg)',
    border: 'var(--warn-bd)',
    icon: LockIcon,
  },
  STOP_UNSAFE: {
    labelKey: 'statusBlocked',
    color: 'var(--bad-fg)',
    bg: 'var(--bad-bg)',
    border: 'var(--bad-bd)',
    icon: ShieldIcon,
  },
}

const errorBadge = computed(() => ({
  label: t('statusRequestFailed'),
  color: 'var(--bad-fg)',
  bg: 'var(--bad-bg)',
  border: 'var(--bad-bd)',
  icon: ShieldIcon as Component,
}))

const resultBadge = computed(() => {
  const r = props.exchange.response
  if (!r) return null
  // Unknown `READY_*` statuses (e.g. READY_FOR_HR_RAG from /ask) fall through
  // to the generic ready badge instead of crashing on a missing meta entry.
  const m = STATUS_META[r.finalStatus] ?? READY
  return { label: t(m.labelKey), color: m.color, bg: m.bg, border: m.border, icon: m.icon }
})

// Developer mode always shows the status badge. User mode shows it only for the
// blocked / access-denied outcomes (meaningful to the user); a plain "Ready"
// badge is pipeline jargon, so user mode hides it and shows just the answer.
const displayBadge = computed(() => {
  const r = props.exchange.response
  if (!r) return null
  if (props.devMode) return resultBadge.value
  if (
    r.finalStatus === 'STOP_UNSAFE' ||
    r.finalStatus === 'STOP_ACCESS_DENIED' ||
    r.finalStatus === 'RAG_DOMAIN_NOT_READY'
  )
    return resultBadge.value
  return null
})

// Friendly label for the routing domain (dev-mode chip).
const DOMAIN_LABEL: Record<string, MsgKey> = {
  HR: 'domainHR',
  PUBLIC_DOMAIN: 'domainPublic',
  PUBLIC_GENERAL: 'domainGeneral',
  FUTURE_DOMAIN: 'domainFuture',
}
const domainLabel = computed(() => {
  const d = props.exchange.response?.domain
  if (!d) return ''
  const key = DOMAIN_LABEL[d]
  return key ? t(key) : d
})

// The guard/access `reason` strings come from the backend (already localized
// there); the literals are only fallbacks when the backend omits a reason.
const headline = computed<string | null>(() => {
  const r = props.exchange.response
  if (!r) return null
  if (r.finalStatus === 'STOP_UNSAFE') return r.guard?.reason || t('headlineUnsafe')
  if (r.finalStatus === 'STOP_ACCESS_DENIED') return r.access?.reason || t('headlineAccessDenied')
  if (r.answer) return null
  if (r.finalStatus === 'RAG_DOMAIN_NOT_READY') return t('headlineModuleNotReady')
  return t('headlinePending')
})

// Text the Copy button puts on the clipboard: the answer if present, otherwise
// the headline (the blocked / denied / pending message).
const answerCopyText = computed(() => {
  const r = props.exchange.response
  if (!r) return null
  return r.answer || headline.value || null
})
</script>

<template>
  <div class="reveal-down">
    <ResultShell v-if="exchange.error" :badge="errorBadge">
      <div :style="{ fontSize: '14px', color: 'var(--text)' }">{{ exchange.error }}</div>
      <MessageActions :busy="busy" @regenerate="emit('regenerate')" />
    </ResultShell>

    <ResultShell v-else-if="exchange.cancelled" :badge="null">
      <div :style="{ fontSize: '14px', color: 'var(--text-muted)', fontStyle: 'italic' }">{{ t('generationStopped') }}</div>
      <MessageActions :busy="busy" @regenerate="emit('regenerate')" />
    </ResultShell>

    <template v-else-if="!exchange.response">
      <TraceSkeleton v-if="devMode" />
      <ThinkingLoader v-else />
    </template>

    <ResultShell v-else :badge="displayBadge">
      <div
        v-if="devMode && domainLabel"
        :style="{
          display: 'inline-flex',
          alignItems: 'center',
          fontSize: '11px',
          fontWeight: 600,
          color: 'var(--text-secondary)',
          background: 'var(--surface-hover)',
          border: '1px solid var(--border)',
          borderRadius: '999px',
          padding: '2px 8px',
          marginBottom: '10px',
        }"
      >
        {{ domainLabel }}
      </div>
      <div
        v-if="headline"
        :style="{
          fontSize: '14.5px',
          color: 'var(--text)',
          lineHeight: 1.55,
          marginBottom: exchange.response.answer ? '12px' : '0',
        }"
      >
        {{ headline }}
      </div>

      <MarkdownMessage v-if="exchange.response.answer" :source="exchange.response.answer" :style="{ marginBottom: '4px' }" />

      <MessageActions :copy-text="answerCopyText" :busy="busy" @regenerate="emit('regenerate')" />

      <!-- Developer-only: the full pipeline trace and the round-trip timing. -->
      <div v-if="devMode" :style="{ marginTop: '14px' }">
        <TraceStages :response="exchange.response" :default-open="true" />
      </div>

      <div
        v-if="devMode && exchange.durationMs != null"
        :style="{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '10px', textAlign: 'right' }"
      >
        {{ t('roundTrip', { n: (exchange.durationMs / 1000).toFixed(2) }) }}
      </div>
    </ResultShell>
  </div>
</template>

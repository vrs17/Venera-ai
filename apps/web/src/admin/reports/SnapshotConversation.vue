<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Flag, MessageSquareOff, Waypoints } from 'lucide-vue-next'
import MarkdownMessage from '../../components/MarkdownMessage.vue'
import { lawSite, lawTitle, lawUrl, lookupLabel } from '../../components/chat/sources'
import type { AnswerSource } from '../../types'
import VEmpty from '../../ui/VEmpty.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VTooltip from '../../ui/VTooltip.vue'
import { fmtDateTime } from '../../ui/format'
import type { ReportMessage } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import StatusDot from '../components/StatusDot.vue'
import { fromSnapshotSources, isLawSource, isToolSource } from '../trace/answerSources'

/**
 * Xabar berilgan paytdagi suhbat nusxasi - chatdagidek: savol o'ngda pufakchada, javob
 * esa o'sha Markdown chizuvchisi bilan (`[1]` chiplari, hujjatni ochish). Xabar aynan
 * bitta javobga berilgan bo'lsa (`reportedTurnId`) - o'sha javob belgilanadi. Izi bor
 * har bir javob yonida "Izni ochish".
 */
const props = defineProps<{
  messages: ReportMessage[]
  reportedTurnId: string | null
  /** Nusxa hajm chegarasiga yetib, eski xabarlar tashlangan. */
  truncated?: boolean
}>()

const { t, locale } = useI18n({ useScope: 'global' })
const { withFilters } = useAdminFilters()

const isReported = (m: ReportMessage) =>
  m.role === 'assistant' && !!props.reportedTurnId && m.turnId === props.reportedTurnId

const sourcesOf = (m: ReportMessage): AnswerSource[] => fromSnapshotSources(m.sources)
const traceTo = (turnId: string) => withFilters(`/admin/turns/${encodeURIComponent(turnId)}`)

function sourceText(s: AnswerSource, i: number): string {
  if (isToolSource(s.kind)) return lookupLabel(s, `T${i + 1}`, t)
  // Qonun moddasi (v2): nomi va "LEX.UZ · qonunchilik" - hujjat emasligi ko'rinsin.
  if (isLawSource(s.kind)) return `${lawTitle(s, t('sourceDocument'))} · ${t('chat.lawCaption', { site: lawSite(lawUrl(s)) })}`
  const name = s.title?.trim() || s.doc_id || t('sourceDocument')
  return s.page ? `${name}, ${t('sourcePage', { n: s.page })}` : name
}
</script>

<template>
  <VEmpty v-if="!messages.length" compact :icon="MessageSquareOff" :title="t('admin.reports.noSnapshot')" />
  <ol v-else class="sc">
    <li v-if="truncated" class="sc-trunc">{{ t('admin.reports.truncated') }}</li>
    <li
      v-for="(m, i) in messages"
      :key="i"
      class="sc-msg"
      :class="[`is-${m.role}`, { 'is-reported': isReported(m) }]"
    >
      <!-- savol -->
      <template v-if="m.role === 'user'">
        <VTooltip v-if="m.createdAt" :text="fmtDateTime(m.createdAt, locale, 'long')" placement="left">
          <div class="sc-bubble">{{ m.content }}</div>
        </VTooltip>
        <div v-else class="sc-bubble">{{ m.content }}</div>
      </template>

      <!-- javob -->
      <template v-else>
        <p v-if="isReported(m)" class="sc-flag">
          <Flag :size="14" :stroke-width="1.75" aria-hidden="true" />
          {{ t('admin.reports.reportedAnswer') }}
        </p>
        <MarkdownMessage v-if="m.content" class="sc-answer" :source="m.content" :sources="sourcesOf(m)" />
        <p v-else class="sc-none">
          <StatusDot :status="m.status && m.status !== 'ok' ? m.status : 'cancelled'" />
        </p>
        <div class="sc-foot">
          <details v-if="sourcesOf(m).length" class="sc-sources">
            <summary>{{ t('sourcesDocuments') }} · {{ sourcesOf(m).length }}</summary>
            <ol>
              <li v-for="(s, k) in sourcesOf(m)" :key="k">{{ sourceText(s, k) }}</li>
            </ol>
          </details>
          <span class="sc-foot-end">
            <StatusDot v-if="m.content && m.status && m.status !== 'ok'" :status="m.status" hide-label />
            <time v-if="m.createdAt" class="sc-time" :datetime="m.createdAt">{{ fmtDateTime(m.createdAt, locale, 'short') }}</time>
            <VIconButton
              v-if="m.turnId"
              :icon="Waypoints"
              size="sm"
              :label="t('admin.trace.openTrace')"
              :to="traceTo(m.turnId)"
            />
          </span>
        </div>
      </template>
    </li>
  </ol>
</template>

<style scoped>
.sc {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
  margin: 0;
  padding: 0;
  list-style: none;
}
.sc-trunc {
  align-self: center;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}

.sc-msg {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.sc-msg.is-user {
  align-items: flex-end;
}
/* Chatdagi savol pufakchasi: --fill, 20px radius, "dum" burchagi 6px. */
.sc-bubble {
  max-width: min(85%, 560px);
  padding: 10px 16px;
  border-radius: 20px 20px 6px 20px;
  background: var(--fill);
  color: var(--text);
  font-size: var(--fs-body);
  line-height: var(--lh-body);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.sc-msg.is-assistant {
  gap: var(--s-2);
}
/* Xabar berilgan javob - brendning yumshoq foni (spec §1.1: "highlight"). */
.sc-msg.is-reported {
  margin-inline: calc(var(--s-4) * -1);
  padding: var(--s-4);
  border-radius: var(--r-lg);
  background: var(--brand-soft);
}
.sc-flag {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.sc-none {
  color: var(--text-3);
}

.sc-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-2) var(--s-4);
  min-width: 0;
}
.sc-foot-end {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  margin-left: auto;
  color: var(--text-3);
}
.sc-time {
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
}

.sc-sources {
  min-width: 0;
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.sc-sources summary {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 var(--s-2);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
  font-weight: 500;
  cursor: pointer;
  list-style: none;
  transition: background-color var(--dur-1) var(--ease-out);
}
.sc-sources summary::-webkit-details-marker {
  display: none;
}
@media (hover: hover) {
  .sc-sources summary:hover {
    background: var(--fill-hover);
    color: var(--text);
  }
}
.sc-sources ol {
  display: grid;
  gap: var(--s-1);
  margin: var(--s-2) 0 0;
  padding-left: 20px;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}
.sc-sources li::marker {
  color: var(--text-4);
}
</style>

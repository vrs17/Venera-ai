<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Eye, RotateCcw, X } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VTextarea from '../../ui/VTextarea.vue'
import { useId } from '../../ui/composables/useId'
import type { ReportDetail, ReportStatus } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import ChannelBadge from '../components/ChannelBadge.vue'
import RelTime from '../components/RelTime.vue'
import StatusDot from '../components/StatusDot.vue'
import UserCell from '../components/UserCell.vue'
import SnapshotConversation from './SnapshotConversation.vue'

/**
 * Bitta xabar (spec §4.5.4): holat va amallar (yopishqoq sarlavhada), izoh, sabab,
 * kim/qayerdan/qachon, suhbat nusxasi va admin izohi.
 *
 * Holatni o'zgartirish va izohni saqlash - ota sahifada (`status`, `note` hodisalari):
 * ro'yxat va hisoblagichlar ham o'sha yerda, optimistik yangilash ikkalasiga birdan.
 * Izoh maydondan chiqqanda saqlanadi (alohida "Saqlash" tugmasi yo'q).
 */
const props = defineProps<{
  report: ReportDetail
  /** Boshqa xabar yuklanmoqda - bu eskisi (xira, amallar o'chiq). */
  stale?: boolean
  /** Yuborilayotgan holat (tugmada spinner). */
  saving?: ReportStatus | null
}>()

const emit = defineEmits<{
  status: [next: ReportStatus]
  note: [id: string, text: string]
}>()

defineExpose({ focus: () => heading.value?.focus() })

const { t, te } = useI18n({ useScope: 'global' })
const { withFilters } = useAdminFilters()
const headingId = useId('rv-title')
const heading = ref<HTMLElement | null>(null)

/* ---- amallar: holatga qarab ---- */
interface Action {
  to: ReportStatus
  label: string
  variant: 'primary' | 'secondary' | 'ghost'
  icon: Component
}
const actions = computed<Action[]>(() => {
  const dismiss: Action = { to: 'dismissed', label: t('admin.reports.dismiss'), variant: 'ghost', icon: X }
  const resolve: Action = { to: 'resolved', label: t('admin.reports.resolve'), variant: 'primary', icon: Check }
  switch (props.report.status) {
    case 'new':
      return [dismiss, { to: 'reviewing', label: t('admin.reports.review'), variant: 'secondary', icon: Eye }, resolve]
    case 'reviewing':
      return [dismiss, resolve]
    default:
      return [{ to: 'reviewing', label: t('admin.reports.reopen'), variant: 'secondary', icon: RotateCcw }]
  }
})

/* ---- matnlar ---- */
const reasonLabel = computed(() => {
  const r = props.report.reason
  const key = `admin.reason.${r ?? 'none'}`
  return te(key) ? t(key) : (r ?? '')
})
const snapshotSource = computed(() => {
  const s = props.report.snapshot?.source
  return s && te(`admin.reports.snapshot.${s}`) ? t(`admin.reports.snapshot.${s}`) : null
})
const messages = computed(() => props.report.snapshot?.messages ?? [])
const truncated = computed(() => (props.report.snapshot as { truncated?: unknown } | undefined)?.truncated === true)
const userTo = computed(() => (props.report.actorId ? withFilters(`/admin/users/${props.report.actorId}`) : undefined))

/* ---- admin izohi ---- */
const NOTE_MAX = 2000
const note = ref(props.report.adminNote ?? '')
// Faqat BOSHQA xabar ochilganda almashtiriladi: server javobi (holat o'zgargach) yozilayotgan
// matnni bosib ketmasin.
watch(
  () => props.report.id,
  () => (note.value = props.report.adminNote ?? ''),
)
function onNoteBlur() {
  if (note.value.trim() === (props.report.adminNote ?? '').trim()) return
  emit('note', props.report.id, note.value)
}
</script>

<template>
  <article class="rv" :class="{ 'is-stale': stale }" :aria-labelledby="headingId" :aria-busy="stale || undefined">
    <header class="rv-head">
      <div class="rv-state">
        <StatusDot :status="report.status" />
        <span v-if="report.updatedBy" class="rv-by">
          {{ report.updatedBy }} · <RelTime :value="report.updatedAt" />
        </span>
      </div>
      <div class="rv-actions">
        <VButton
          v-for="a in actions"
          :key="a.to"
          :variant="a.variant"
          size="sm"
          :icon="a.icon"
          :loading="saving === a.to"
          :disabled="stale || (!!saving && saving !== a.to)"
          @click="emit('status', a.to)"
        >
          {{ a.label }}
        </VButton>
      </div>
    </header>

    <div class="rv-body">
      <h2 :id="headingId" ref="heading" class="sr-only" tabindex="-1">
        {{ report.userName || t('admin.common.unknownUser') }} · {{ reasonLabel }}
      </h2>

      <blockquote v-if="report.comment" class="rv-comment">{{ report.comment }}</blockquote>
      <p v-else class="rv-nocomment">{{ t('admin.reports.noComment') }}</p>

      <dl class="rv-meta">
        <div class="rv-pair">
          <dt>{{ t('admin.reports.reason') }}</dt>
          <dd>
            <VBadge v-if="report.reason" size="sm">{{ reasonLabel }}</VBadge>
            <span v-else class="rv-dim">{{ reasonLabel }}</span>
          </dd>
        </div>
        <div class="rv-pair">
          <dt>{{ t('admin.reports.reporter') }}</dt>
          <dd><UserCell :name="report.userName" :size="24" :to="userTo" /></dd>
        </div>
        <div class="rv-pair">
          <dt>{{ t('admin.col.channel') }}</dt>
          <dd><ChannelBadge :channel="report.channel" size="sm" /></dd>
        </div>
        <div class="rv-pair">
          <dt>{{ t('admin.col.time') }}</dt>
          <dd><RelTime :value="report.createdAt" long /></dd>
        </div>
      </dl>

      <section class="rv-section" :aria-label="t('admin.reports.conversation')">
        <div class="rv-section-head">
          <h3 class="rv-h3">{{ t('admin.reports.conversation') }}</h3>
          <span v-if="snapshotSource" class="rv-caption">{{ snapshotSource }}</span>
        </div>
        <SnapshotConversation :messages="messages" :reported-turn-id="report.turnId" :truncated="truncated" />
      </section>

      <section class="rv-section rv-note">
        <VTextarea
          v-model="note"
          :label="t('admin.reports.adminNote')"
          :placeholder="t('admin.reports.notePlaceholder')"
          :rows="3"
          :max-rows="10"
          :maxlength="NOTE_MAX"
          :disabled="stale"
          @blur="onNoteBlur"
        />
      </section>
    </div>
  </article>
</template>

<style scoped>
.rv {
  display: flex;
  flex-direction: column;
  min-width: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.rv.is-stale {
  opacity: 0.5;
}

/* Amallar yopishqoq: uzun suhbatni o'qib bo'lgach yuqoriga qaytish shart emas. */
.rv-head {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  padding: var(--s-4) var(--s-6);
  border-bottom: 1px solid var(--line);
  border-radius: var(--r-lg) var(--r-lg) 0 0;
  background: var(--surface);
}
.rv-state {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-width: 0;
}
.rv-by {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.rv-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2);
  margin-left: auto;
}

.rv-body {
  display: flex;
  flex-direction: column;
  gap: var(--s-8);
  padding: var(--s-6);
  min-width: 0;
}

.rv-comment {
  margin: 0;
  padding-left: var(--s-4);
  border-left: 2px solid var(--line-strong);
  color: var(--text);
  font-size: var(--fs-title-3);
  line-height: 26px;
  letter-spacing: -0.011em;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.rv-nocomment {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}

.rv-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: var(--s-4) var(--s-6);
  margin: 0;
}
.rv-pair {
  display: flex;
  flex-direction: column;
  gap: var(--s-1_5);
  min-width: 0;
}
.rv-pair dt {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
}
.rv-pair dd {
  display: flex;
  align-items: center;
  min-height: 24px;
  margin: 0;
  min-width: 0;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.rv-dim {
  color: var(--text-3);
}

.rv-section {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
}
.rv-section-head {
  display: flex;
  align-items: baseline;
  gap: var(--s-3);
}
.rv-h3 {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
  letter-spacing: -0.011em;
}
.rv-caption {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.rv-note {
  padding-top: var(--s-6);
  border-top: 1px solid var(--line);
}

@media (max-width: 767.98px) {
  /* Telefonda yuqorida ilovaning 56px paneli yopishgan - amallar uning ostida. */
  .rv-head {
    top: 56px;
    padding: var(--s-3) var(--s-4);
  }
  .rv-body {
    gap: var(--s-6);
    padding: var(--s-4);
  }
  .rv-actions {
    width: 100%;
    margin-left: 0;
  }
  .rv-actions > * {
    flex: 1 1 auto;
  }
}
@media (prefers-reduced-motion: reduce) {
  .rv {
    transition: none;
  }
}
</style>

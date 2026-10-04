<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ChevronDown, ChevronUp, CircleAlert, Mic, RotateCw, SearchX, X } from 'lucide-vue-next'
import MarkdownMessage from '../../components/MarkdownMessage.vue'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VCard from '../../ui/VCard.vue'
import VCopy from '../../ui/VCopy.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VJson from '../../ui/VJson.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import VTabs from '../../ui/VTabs.vue'
import type { TabItem } from '../../ui/VTabs.vue'
import VTooltip from '../../ui/VTooltip.vue'
import VWaterfall from '../../ui/VWaterfall.vue'
import { isEditableTarget } from '../../ui/useCommandPalette'
import { fmtDateTime, fmtMs } from '../../ui/format'
import { getTurn } from '../api'
import type { TurnDetail, TurnEvent } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import ChannelBadge from '../components/ChannelBadge.vue'
import DurationText from '../components/DurationText.vue'
import RelTime from '../components/RelTime.vue'
import RouteBadge from '../components/RouteBadge.vue'
import StatusDot from '../components/StatusDot.vue'
import UserCell from '../components/UserCell.vue'
import { useAdminQuery } from '../components/useAdminQuery'
import { useBackLink } from '../conversations/backLink'
import { lastVisitedTurn, useTurnNav } from '../conversations/turnNav'
import { useConversationFilters } from '../conversations/useConversationFilters'
import AdminDocViewer from '../trace/AdminDocViewer.vue'
import ArtifactCard from '../trace/ArtifactCard.vue'
import ProposalCard from '../trace/ProposalCard.vue'
import TraceApiCalls from '../trace/TraceApiCalls.vue'
import TraceChat from '../trace/TraceChat.vue'
import TraceSources from '../trace/TraceSources.vue'
import { fromTurnSource } from '../trace/answerSources'
import { STEP_COLORS, buildSteps } from '../trace/steps'
import type { TraceStep } from '../trace/steps'

// "Savol izi" (spec §4.5.3): bitta savol qanday javob topgani - vaqt chizig'i, javob,
// manbalar, tashqi chaqiruvlar, xom kadrlar va suhbatning boshqa savollari.
const props = defineProps<{ id: string }>()

const { t, te, locale } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { withFilters } = useAdminFilters()
const conv = useConversationFilters()

const q = useAdminQuery<TurnDetail, string>((id, signal) => getTurn(id, signal), { params: () => props.id })
const turn = computed(() => q.data.value)
// Boshqa savolga o'tildi, yangisi hali kelmadi - eski kadr xira turadi.
const stale = computed(() => !!turn.value && turn.value.id !== props.id)
const notFound = computed(() => q.errorStatus.value === 404 && (!turn.value || stale.value))

/* ---- havolalar ---- */
// Ro'yxat filtrlari URL'da kelgan: "Orqaga" aynan o'sha ro'yxatga qaytaradi.
const listQuery = computed(() => conv.listQuery.value)
const backTo = computed(() => ({ path: '/admin/conversations', query: listQuery.value }))
const onBack = useBackLink((path) => path === '/admin/conversations')
const chatTo = computed(() =>
  turn.value?.chatId ? { path: '/admin/conversations', query: { ...listQuery.value, chat: turn.value.chatId } } : null,
)
const userTo = computed(() => (turn.value?.actorId ? withFilters(`/admin/users/${turn.value.actorId}`) : undefined))
const reportTo = (id: string) => withFilters(`/admin/reports/${encodeURIComponent(id)}`)

/* ---- oldingi / keyingi savol (ro'yxatdagi tartibda) ---- */
const nav = useTurnNav(
  toRef(props, 'id'),
  computed(() => route.query),
)
const navLoading = ref(false)

function openTurn(id: string) {
  lastVisitedTurn.value = id
  // `replace`: savollarni birma-bir ko'rib chiqish tarixni to'ldirmasin - "Orqaga" ro'yxatga.
  void router.replace({ path: `/admin/turns/${encodeURIComponent(id)}`, query: listQuery.value })
}
function goPrev() {
  if (nav.prev.value) openTurn(nav.prev.value)
}
async function goNext() {
  if (navLoading.value || !nav.hasNext.value) return
  navLoading.value = true
  try {
    const next = await nav.resolveNext()
    if (next) openTurn(next)
  } finally {
    navLoading.value = false
  }
}

function onKeyDown(e: KeyboardEvent) {
  if (!nav.available.value || e.defaultPrevented || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return
  if (isEditableTarget(e.target) || document.querySelector('[aria-modal="true"]')) return
  if (e.key === 'k') {
    e.preventDefault()
    goPrev()
  } else if (e.key === 'j') {
    e.preventDefault()
    void goNext()
  }
}
onMounted(() => window.addEventListener('keydown', onKeyDown))

/* ---- savol almashganda ---- */
const selectedStep = ref<string | null>(null)
const questionOpen = ref(false)
watch(
  () => props.id,
  (id, prev) => {
    lastVisitedTurn.value = id
    selectedStep.value = null
    questionOpen.value = false
    if (prev !== undefined) window.scrollTo({ top: 0 })
  },
  { immediate: true },
)

/* ---- hali tugamagan savol: bir necha soniyada yangilanadi ---- */
let pollTimer: ReturnType<typeof setTimeout> | undefined
watch(
  () => q.data.value,
  (d) => {
    clearTimeout(pollTimer)
    if (d?.status !== 'running') return
    pollTimer = setTimeout(() => {
      if (document.visibilityState === 'visible') void q.refresh()
      else pollTimer = setTimeout(() => void q.refresh(), 10_000)
    }, 3000)
  },
)
onBeforeUnmount(() => {
  clearTimeout(pollTimer)
  window.removeEventListener('keydown', onKeyDown)
})

/* ---- vaqt chizig'i ---- */
const routeLabel = (r: string) => (te(`admin.route.${r}`) ? t(`admin.route.${r}`) : r)
const steps = computed<TraceStep[]>(() => (turn.value ? buildSteps(turn.value, { t, te, routeLabel }) : []))
// Xato bo'lsa - xato bosqichi darhol ochiq: admin aynan shuni izlab kelgan.
const autoStep = computed(() => steps.value.find((s) => s.status === 'error' && s.event)?.id ?? null)
const activeStepId = computed(() => selectedStep.value ?? autoStep.value)
const activeStep = computed(() => steps.value.find((s) => s.id === activeStepId.value) ?? null)

function onStepSelect(id: string) {
  selectedStep.value = activeStepId.value === id ? '' : id
}

const stepPayload = computed<unknown>(() => {
  const s = activeStep.value
  const d = turn.value
  if (!s || !d) return null
  if (s.event) return s.event.payload ?? null
  if (s.id === 'request') {
    return {
      status: d.status,
      httpStatus: d.httpStatus,
      errorCode: d.errorCode,
      errorText: d.errorText,
      requestId: d.requestId,
      locale: d.locale,
      kind: d.kind,
      inputMode: d.inputMode,
      engine: d.engine,
    }
  }
  return null
})

/* ---- javob, taklif, fayl ---- */
const answerSources = computed(() => (turn.value?.sources ?? []).map(fromTurnSource))
const hasError = computed(() => !!turn.value && (turn.value.status === 'error' || !!turn.value.errorText))

function lastFrame(name: string): TurnEvent | undefined {
  const events = turn.value?.events ?? []
  for (let i = events.length - 1; i >= 0; i--) if (events[i].type === 'frame' && events[i].name === name) return events[i]
  return undefined
}
const proposal = computed(() => lastFrame('proposal'))
const artifact = computed(() => lastFrame('artifact'))
const showProposal = computed(() => !!turn.value && (turn.value.hasProposal || !!proposal.value))
const showArtifact = computed(() => !!turn.value && (turn.value.hasArtifact || !!artifact.value))

/* ---- o'ng yorliqlar ---- */
type Tab = 'sources' | 'api' | 'raw' | 'chat'
const tab = ref<Tab>('sources')
const tabs = computed<TabItem<Tab>[]>(() => {
  const d = turn.value
  return [
    { value: 'sources', label: t('admin.trace.sources'), count: d?.sources.length },
    { value: 'api', label: t('admin.trace.apiCalls'), count: d?.apiCalls.length },
    { value: 'raw', label: t('admin.trace.raw') },
    { value: 'chat', label: t('admin.trace.chat'), count: d?.chatTurns.length },
  ]
})
const rawTurn = computed(() => {
  if (!turn.value) return null
  const { events: _events, ...rest } = turn.value
  return rest
})

/* ---- sarlavha: uzun savol (ovozli matn) 3 qatorda kesiladi, "Yana" bilan ochiladi ---- */
const titleEl = ref<HTMLElement | null>(null)
const overflowing = ref(false)
function measureTitle() {
  // Ochiq holatda o'lchab bo'lmaydi (kesilmagan) - oxirgi natija saqlanadi.
  if (questionOpen.value) return
  const el = titleEl.value
  overflowing.value = !!el && el.scrollHeight > el.clientHeight + 1
}
let titleObserver: ResizeObserver | null = null
watch(titleEl, (el) => {
  titleObserver?.disconnect()
  if (!el) return
  measureTitle()
  if (typeof ResizeObserver !== 'undefined') {
    titleObserver = new ResizeObserver(measureTitle)
    titleObserver.observe(el)
  }
})
watch(
  [() => turn.value?.question, questionOpen],
  () => void nextTick(measureTitle),
)
onBeforeUnmount(() => titleObserver?.disconnect())
const statusLabel = computed(() => {
  const d = turn.value
  if (!d?.errorCode) return undefined
  return `${t('admin.status.error')} · ${d.errorCode}`
})
</script>

<template>
  <section class="tp" aria-labelledby="admin-page-title">
    <!-- ============ topilmadi ============ -->
    <template v-if="notFound">
      <VButton class="tp-back" variant="ghost" size="sm" :icon="ArrowLeft" :to="backTo" @click.capture="onBack">
        {{ t('admin.nav.conversations') }}
      </VButton>
      <h1 id="admin-page-title" class="sr-only">{{ t('admin.page.turn.title') }}</h1>
      <VEmpty class="tp-empty" :icon="SearchX" :title="t('admin.trace.notFound')">
        <p class="tp-empty-id t-mono">{{ id }}</p>
      </VEmpty>
    </template>

    <!-- ============ birinchi yuklash ============ -->
    <template v-else-if="!turn && (q.loading.value || !q.error.value)">
      <div class="tp-head" aria-hidden="true">
        <VSkeleton :width="120" :height="28" radius="sm" />
        <VSkeleton width="min(560px, 90%)" :height="24" />
        <VSkeleton width="min(420px, 70%)" :height="14" />
      </div>
      <h1 id="admin-page-title" class="sr-only">{{ t('admin.page.turn.title') }}</h1>
      <div class="tp-grid" aria-hidden="true">
        <VCard><VSkeleton width="100%" height="260px" radius="md" /></VCard>
        <VCard><VSkeleton width="100%" height="260px" radius="md" /></VCard>
      </div>
    </template>

    <!-- ============ xato (ma'lumotsiz) ============ -->
    <template v-else-if="!turn">
      <VButton class="tp-back" variant="ghost" size="sm" :icon="ArrowLeft" :to="backTo" @click.capture="onBack">
        {{ t('admin.nav.conversations') }}
      </VButton>
      <h1 id="admin-page-title" class="sr-only">{{ t('admin.page.turn.title') }}</h1>
      <AdminError :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />
    </template>

    <!-- ============ iz ============ -->
    <template v-else>
      <header class="tp-head">
        <div class="tp-bar">
          <VButton class="tp-back" variant="ghost" size="sm" :icon="ArrowLeft" :to="backTo" @click.capture="onBack">
            {{ t('admin.nav.conversations') }}
          </VButton>
          <div class="tp-tools">
            <template v-if="nav.available.value">
              <VIconButton
                :icon="ChevronUp"
                :label="t('admin.trace.prevTurn')"
                shortcut="k"
                size="md"
                :disabled="!nav.prev.value"
                @click="goPrev"
              />
              <VIconButton
                :icon="ChevronDown"
                :label="t('admin.trace.nextTurn')"
                shortcut="j"
                size="md"
                :disabled="!nav.hasNext.value"
                :loading="navLoading"
                @click="goNext"
              />
            </template>
            <VIconButton
              :icon="RotateCw"
              :label="t('admin.common.refresh')"
              size="md"
              :loading="q.loading.value"
              @click="q.refresh"
            />
          </div>
        </div>

        <div class="tp-titles" :class="{ 'is-stale': stale }">
          <h1 id="admin-page-title" ref="titleEl" class="tp-title" :class="{ 'is-clamped': !questionOpen }">
            <span class="sr-only">{{ t('admin.page.turn.title') }}. </span>{{ turn.question || '—' }}
          </h1>
          <button
            v-if="overflowing || questionOpen"
            type="button"
            class="tp-more"
            :aria-expanded="questionOpen"
            @click="questionOpen = !questionOpen"
          >
            {{ questionOpen ? t('ui.less') : t('ui.more') }}
          </button>

          <div class="tp-meta">
            <UserCell :name="turn.userName" :login="turn.userLogin" :size="24" :to="userTo" />
            <ChannelBadge :channel="turn.channel" size="sm" />
            <VTooltip v-if="turn.startedAt" :text="fmtDateTime(turn.startedAt, locale, 'long')">
              <time class="tp-time" :datetime="turn.startedAt">{{ fmtDateTime(turn.startedAt, locale, 'medium') }}</time>
            </VTooltip>
            <span v-if="turn.inputMode === 'voice'" class="tp-fact">
              <Mic :size="14" :stroke-width="1.75" aria-hidden="true" />
              {{ t('admin.conversations.voice') }}
            </span>
          </div>

          <div class="tp-meta">
            <StatusDot :status="turn.status" :label="statusLabel" />
            <RouteBadge :route="turn.route" size="sm" />
            <!-- "Dvigatel v2": qaysi yordamchi javob berdi (v1 barqaror / v2 yangi). -->
            <span v-if="turn.engine" class="tp-fact">
              <span class="tp-k">{{ t('admin.filter.engine') }}</span>
              <span class="t-mono">{{ turn.engine }}</span>
            </span>
            <span class="tp-fact">
              <span class="tp-k">{{ t('admin.trace.ttft') }}</span>
              <DurationText :ms="turn.ttftMs" />
            </span>
            <span class="tp-fact">
              <span class="tp-k">{{ t('admin.trace.total') }}</span>
              <DurationText :ms="turn.totalMs" />
            </span>
            <span v-if="turn.requestId" class="tp-fact tp-rid">
              <span class="tp-k">{{ t('admin.trace.requestId') }}</span>
              <span class="t-mono tp-rid-v">{{ turn.requestId }}</span>
              <VCopy :text="turn.requestId" />
            </span>
            <VButton v-if="chatTo" variant="ghost" size="sm" :to="chatTo">{{ t('admin.trace.openChat') }}</VButton>
          </div>
        </div>
      </header>

      <AdminError v-if="q.error.value" inline :message="q.errorText.value" :busy="q.loading.value" @retry="q.refresh" />

      <div class="tp-grid" :class="{ 'is-stale': stale }" :aria-busy="stale || undefined">
        <!-- ---- chap: vaqt chizig'i, javob, taklif/fayl ---- -->
        <div class="tp-col">
          <VCard :title="t('admin.trace.waterfall')" :heading-level="2">
            <VEmpty v-if="!turn.events.length" compact :title="t('admin.trace.noEvents')" />
            <template v-else>
              <VWaterfall
                :rows="steps"
                :kind-colors="STEP_COLORS"
                :selected-id="activeStepId"
                :label="t('admin.trace.waterfall')"
                :label-width="220"
                @select="onStepSelect"
              />
              <div v-if="activeStep" class="tp-step">
                <div class="tp-step-head">
                  <span class="tp-step-name">{{ activeStep.label }}</span>
                  <span class="tp-step-time">
                    +{{ fmtMs(activeStep.startMs, locale) }}<template v-if="activeStep.durMs"> · {{ fmtMs(activeStep.durMs, locale) }}</template>
                  </span>
                  <VIconButton class="tp-step-close" :icon="X" size="sm" :label="t('ui.close')" @click="selectedStep = ''" />
                </div>
                <p v-if="activeStep.sub" class="tp-step-sub">{{ activeStep.sub }}</p>
                <VJson
                  v-if="stepPayload !== null && stepPayload !== undefined"
                  :data="stepPayload"
                  :label="activeStep.label"
                  :expand-depth="2"
                  max-height="320px"
                />
              </div>
            </template>
          </VCard>

          <VCard :title="t('admin.trace.answer')" :heading-level="2">
            <template v-if="turn.answer" #actions>
              <VCopy :text="turn.answer" />
            </template>
            <div class="tp-answer">
              <div v-if="hasError" class="tp-error" role="note">
                <CircleAlert :size="16" :stroke-width="1.75" aria-hidden="true" />
                <div class="tp-error-body">
                  <p class="tp-error-head">
                    <span>{{ t('admin.trace.errorText') }}</span>
                    <code v-if="turn.errorCode" class="t-mono">{{ turn.errorCode }}</code>
                    <span v-if="turn.httpStatus" class="t-mono">{{ t('admin.trace.http') }} {{ turn.httpStatus }}</span>
                  </p>
                  <p v-if="turn.errorText" class="tp-error-text">{{ turn.errorText }}</p>
                </div>
              </div>
              <MarkdownMessage v-if="turn.answer" :source="turn.answer" :sources="answerSources" />
              <p v-else-if="!hasError" class="tp-none">{{ t('admin.trace.noAnswer') }}</p>
            </div>
          </VCard>

          <ProposalCard v-if="showProposal" :payload="proposal?.payload" :status="turn.proposalStatus" />
          <ArtifactCard v-if="showArtifact" :payload="artifact?.payload" />

          <VCard v-if="turn.reports.length" :title="t('admin.trace.reports')" :heading-level="2">
            <ul class="tp-reports">
              <li v-for="r in turn.reports" :key="r.id">
                <RouterLink :to="reportTo(r.id)" class="tp-report">
                  <StatusDot :status="r.status" hide-label />
                  <span class="tp-report-text">{{ r.commentPreview || (r.reason ? t(`admin.reason.${r.reason}`) : '—') }}</span>
                  <VBadge v-if="r.reason" size="sm">{{ t(`admin.reason.${r.reason}`) }}</VBadge>
                  <span class="tp-report-time"><RelTime :value="r.createdAt" /></span>
                </RouterLink>
              </li>
            </ul>
          </VCard>
        </div>

        <!-- ---- o'ng: manbalar, API, xom, suhbat ---- -->
        <div class="tp-col">
          <VCard class="tp-tabs">
            <VTabs v-model="tab" :tabs="tabs" size="sm" :aria-label="t('admin.page.turn.title')">
              <template #default="{ value }">
                <div class="tp-panel">
                  <TraceSources v-if="value === 'sources'" :sources="turn.sources" />
                  <TraceApiCalls v-else-if="value === 'api'" :calls="turn.apiCalls" />
                  <div v-else-if="value === 'raw'" class="tp-raw">
                    <VJson :data="turn.events" label="events" :expand-depth="1" max-height="480px" />
                    <VJson :data="rawTurn" label="turn" :expand-depth="1" max-height="480px" />
                  </div>
                  <TraceChat
                    v-else
                    :turns="turn.chatTurns"
                    :current-id="turn.id"
                    :chat-id="turn.chatId"
                    :query="listQuery"
                  />
                </div>
              </template>
            </VTabs>
          </VCard>
        </div>
      </div>
    </template>

    <AdminDocViewer />
  </section>
</template>

<style scoped>
.tp {
  display: flex;
  flex-direction: column;
  gap: var(--s-8);
}
.tp-back {
  align-self: flex-start;
  margin-left: calc(var(--s-2) * -1);
  color: var(--text-2);
}

/* ---- sarlavha ---- */
.tp-head {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
}
.tp-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
}
.tp-tools {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  color: var(--text-2);
}
.tp-titles {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  min-width: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.tp-title {
  max-width: 72ch;
  font-size: var(--fs-title-2);
  line-height: var(--lh-title-2);
  font-weight: 600;
  letter-spacing: -0.016em;
  overflow-wrap: anywhere;
  white-space: pre-line;
}
.tp-title.is-clamped {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}
.tp-more {
  align-self: flex-start;
  margin-top: calc(var(--s-2) * -1);
  padding: 0;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 3px;
}
.tp-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2) var(--s-5);
  min-width: 0;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.tp-time {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.tp-fact {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  min-width: 0;
}
.tp-k {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  white-space: nowrap;
}
.tp-rid {
  max-width: 100%;
}
.tp-rid-v {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
}

/* ---- ikki ustun (≥1120: 7/12 + 5/12) ---- */
.tp-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s-6);
  align-items: start;
  transition: opacity var(--dur-2) var(--ease-out);
}
.is-stale {
  opacity: 0.5;
}
@media (min-width: 1120px) {
  .tp-grid {
    grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  }
}
.tp-col {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
  min-width: 0;
}

/* ---- tanlangan bosqich ---- */
.tp-step {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  margin-top: var(--s-4);
  padding-top: var(--s-4);
  border-top: 1px solid var(--line);
}
.tp-step-head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-width: 0;
}
.tp-step-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
}
/* Vaqt - Inter tabular (mono emas): o'nlik vergul va bo'shliq sochilib ketmasin. */
.tp-step-time {
  flex: none;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.tp-step-close {
  margin-left: auto;
  color: var(--text-3);
}
.tp-step-sub {
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}

/* ---- javob ---- */
.tp-answer {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
.tp-error {
  display: flex;
  gap: var(--s-2);
  padding: var(--s-3);
  border-radius: var(--r-md);
  background: var(--crit-soft);
  color: var(--crit-text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.tp-error > svg {
  flex: none;
  margin-top: 2px;
}
.tp-error-body {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: 0;
}
.tp-error-head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-1) var(--s-2);
  font-weight: 500;
}
.tp-error-text {
  color: var(--text);
  overflow-wrap: anywhere;
}
.tp-none {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
}

/* ---- xabarlar ---- */
.tp-reports {
  display: flex;
  flex-direction: column;
  margin: 0 calc(var(--s-2) * -1);
  padding: 0;
  list-style: none;
}
.tp-report {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-height: 40px;
  padding: var(--s-2);
  border-radius: var(--r-sm);
  color: inherit;
  text-decoration: none;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .tp-report:hover {
    background: var(--fill);
  }
}
.tp-report-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tp-report-time {
  flex: none;
  color: var(--text-3);
  font-size: var(--fs-caption);
}

/* ---- yorliqlar ---- */
.tp-panel {
  padding-top: var(--s-5);
}
.tp-raw {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}

/* ---- bo'sh ---- */
.tp-empty {
  padding-block: var(--s-16);
}
.tp-empty-id {
  color: var(--text-3);
  overflow-wrap: anywhere;
}

@media (max-width: 767.98px) {
  .tp {
    gap: var(--s-6);
  }
  .tp-meta {
    gap: var(--s-2) var(--s-4);
  }
}
@media (prefers-reduced-motion: reduce) {
  .tp-titles,
  .tp-grid {
    transition: none;
  }
}
</style>

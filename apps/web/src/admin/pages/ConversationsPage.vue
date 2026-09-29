<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RouteLocationRaw } from 'vue-router'
import { CircleAlert, FileText, Flag, MessagesSquare, Mic, Zap } from 'lucide-vue-next'
import VButton from '../../ui/VButton.vue'
import VDataTable from '../../ui/VDataTable.vue'
import type { DataTableColumn } from '../../ui/VDataTable.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VTooltip from '../../ui/VTooltip.vue'
import { useIsPhone, useMediaQuery } from '../../ui/composables/useMediaQuery'
import { fmtDate, fmtDateTime, fmtNumber, fmtTime, isSameDay, toDate } from '../../ui/format'
import { listChats, listTurns } from '../api'
import type { AdminChatPage, AdminChatSummary, TurnPage, TurnQuery, TurnSummary } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import AdminError from '../components/AdminError.vue'
import AdminPageHeader from '../components/AdminPageHeader.vue'
import ChannelBadge from '../components/ChannelBadge.vue'
import DurationText from '../components/DurationText.vue'
import RelTime from '../components/RelTime.vue'
import RouteBadge from '../components/RouteBadge.vue'
import StatusDot from '../components/StatusDot.vue'
import UserCell from '../components/UserCell.vue'
import ConversationFilters from '../conversations/ConversationFilters.vue'
import { rememberChat, rememberPerson } from '../conversations/people'
import type { Person } from '../conversations/people'
import { lastVisitedTurn, publishTurnList } from '../conversations/turnNav'
import { useConversationFilters } from '../conversations/useConversationFilters'
import { useKeysetList } from '../conversations/useKeysetList'

// "Suhbatlar" (spec §4.5.2): har bir savol (yoki suhbat) - qator, qator -> savol izi.
// Filtrlar URL'da (`useConversationFilters`), sahifalash - kursor ("Yana yuklash").
const { t, locale } = useI18n({ useScope: 'global' })
const global = useAdminFilters()
const conv = useConversationFilters()
const s = computed(() => conv.state.value)

const isPhone = useIsPhone()
const isXL = useMediaQuery('(min-width: 1440px)')
const isLG = useMediaQuery('(min-width: 1280px)')
const isDesktop = useMediaQuery('(min-width: 1120px)')

const PAGE = 50
const params = computed<TurnQuery>(() => ({ ...conv.apiParams(global.params.value), limit: PAGE }))
const fresh = (): TurnQuery => ({ ...conv.apiParams(global.freshParams()), limit: PAGE })

const turns = useKeysetList<TurnSummary, TurnPage, TurnQuery>(listTurns, {
  params,
  fresh,
  enabled: () => s.value.view === 'turns',
})
const chats = useKeysetList<AdminChatSummary, AdminChatPage, TurnQuery>(listChats, {
  params,
  fresh,
  enabled: () => s.value.view === 'chats',
})
const isChats = computed(() => s.value.view === 'chats')
const list = computed(() => (isChats.value ? chats : turns))

/* ---- nomlar (filtr chip'i uchun) va oldingi/keyingi savol uchun ro'yxat ---- */
watch(
  [() => turns.items.value, () => turns.nextCursor.value],
  ([rows, cursor]) => {
    for (const r of rows) rememberPerson(r.actorId, r.userName, r.userLogin)
    publishTurnList(
      conv.query.value,
      rows.map((r) => r.id),
      cursor,
      // Kursor qaysi so'rovniki bo'lsa - o'shaning parametrlari ("Yangilash" dan keyin ham).
      turns.pageParams() ?? params.value,
    )
  },
  { immediate: true },
)
watch(
  () => chats.items.value,
  (rows) => {
    for (const r of rows) {
      rememberPerson(r.actorId, r.userName)
      rememberChat(r.chatId, r.title)
    }
  },
  { immediate: true },
)

const people = computed<Person[]>(() => {
  const seen = new Map<number, Person>()
  const rows: { actorId: number | null; userName: string | null; userLogin?: string | null }[] = isChats.value
    ? chats.items.value
    : turns.items.value
  for (const r of rows) {
    if (!r.actorId || seen.has(r.actorId)) continue
    const name = r.userName?.trim() || r.userLogin?.trim()
    if (name) seen.set(r.actorId, { actorId: r.actorId, name, login: r.userLogin ?? null })
  }
  return [...seen.values()]
})

/* ---- ustunlar: ekran kengligiga qarab - savol matni hech qachon siqilib qolmasin ----
   Chap menyu ochiq holatda 1120px da kontent ~820px: ikkinchi darajali ustunlar (yo'nalish,
   manbalar, kanal nomi) kenglik oshgan sari qo'shiladi, yo'qolgani filtr chip'ida qoladi. */
const num = (v: number) => fmtNumber(v, locale.value)
const channelIconOnly = computed(() => !isXL.value && !isPhone.value)
const userWidth = computed(() => (isXL.value ? 184 : isDesktop.value ? 160 : 140))

const turnColumns = computed<DataTableColumn<TurnSummary>[]>(() => {
  const time: DataTableColumn<TurnSummary> = { key: 'time', label: t('admin.col.time'), width: 104, value: (r) => r.startedAt }
  const user: DataTableColumn<TurnSummary> = { key: 'user', label: t('admin.col.user'), width: userWidth.value }
  const channel: DataTableColumn<TurnSummary> = {
    key: 'channel',
    label: t('admin.col.channel'),
    width: channelIconOnly.value ? 56 : 112,
  }
  const question: DataTableColumn<TurnSummary> = { key: 'question', label: t('admin.col.question') }
  // 140: eng uzun yo'nalish nomi - uz-Cyrl "Жонли маълумот" - 132 da kesilib qolardi.
  const route: DataTableColumn<TurnSummary> = { key: 'route', label: t('admin.col.route'), width: 140 }
  const sources: DataTableColumn<TurnSummary> = { key: 'sources', label: t('admin.col.sources'), width: 88, align: 'end' }
  // 148: sekin javobda ikki qiymat ham uzun bo'ladi - "36 s / 1 min 18 s" ~110px, 124 lik
  // ustunda (100px matn) oxirgi "s" kesilardi. Endi ~124px matn: "1 min 5 s / 2 min 3 s" ham sig'adi.
  const latency: DataTableColumn<TurnSummary> = { key: 'latency', label: t('admin.col.latency'), width: 148, align: 'end' }
  const status: DataTableColumn<TurnSummary> = { key: 'status', label: t('admin.col.status'), width: 72, align: 'center' }
  // Telefonda kartochka sarlavhasi - birinchi ustun: savolning o'zi.
  if (isPhone.value) return [question, user, channel, time, route, latency, status]
  if (isXL.value) return [time, user, channel, question, route, sources, latency, status]
  if (isLG.value) return [time, user, channel, question, route, latency, status]
  if (isDesktop.value) return [time, user, channel, question, latency, status]
  return [time, user, question, latency, status]
})

const chatColumns = computed<DataTableColumn<AdminChatSummary>[]>(() => {
  const title: DataTableColumn<AdminChatSummary> = { key: 'title', label: t('admin.col.chat') }
  const user: DataTableColumn<AdminChatSummary> = { key: 'user', label: t('admin.col.user'), width: userWidth.value }
  const channel: DataTableColumn<AdminChatSummary> = {
    key: 'channel',
    label: t('admin.col.channel'),
    width: channelIconOnly.value ? 56 : 112,
  }
  const count: DataTableColumn<AdminChatSummary> = { key: 'turns', label: t('admin.col.turns'), width: 96, align: 'end' }
  const errors: DataTableColumn<AdminChatSummary> = { key: 'errors', label: t('admin.col.errors'), width: 88, align: 'end' }
  const last: DataTableColumn<AdminChatSummary> = { key: 'lastAt', label: t('admin.col.lastAt'), width: 136 }
  if (isPhone.value || isDesktop.value) return [title, user, channel, count, errors, last]
  return [title, user, count, last]
})

/* ---- havolalar ---- */
const turnTo = (row: TurnSummary): RouteLocationRaw => ({
  path: `/admin/turns/${encodeURIComponent(row.id)}`,
  query: conv.listQuery.value,
})
// Suhbat qatori -> shu suhbatning savollari. `push` (tarixga yoziladi): "Orqaga"
// suhbatlar ro'yxatiga qaytaradi.
const chatTo = (row: AdminChatSummary): RouteLocationRaw => ({
  path: '/admin/conversations',
  query: { ...conv.listQuery.value, chat: row.chatId },
})

// Vaqt ikki qatorda (foydalanuvchi katagi bilan bir ritmda): soat, ostida - bugun
// bo'lmasa - kun. Bitta qatorli "28 сент., 04:57" tor ustunda kesilib qolardi.
function timeParts(iso: string | null): { time: string; date: string | null } | null {
  const d = toDate(iso)
  if (!d) return null
  const now = new Date()
  if (isSameDay(d, now)) return { time: fmtTime(d), date: null }
  return { time: fmtTime(d), date: fmtDate(d, locale.value, { year: 'auto' }) }
}

function onTurnClick(row: TurnSummary) {
  lastVisitedTurn.value = row.id
}

function statusLabel(row: TurnSummary): string | undefined {
  return row.errorCode ? `${t('admin.status.error')} · ${row.errorCode}` : undefined
}

/* ---- bo'sh holat ---- */
const emptyTitle = computed(() => {
  if (conv.hasFilters.value || !global.isDefault.value) return t('admin.empty.filtered')
  return isChats.value ? t('admin.empty.chats') : t('admin.empty.turns')
})

function clearFilters() {
  conv.set({ q: '', actor: null, route: null, status: null, reported: false, minMs: null, chat: null, channel: 'all' })
}
</script>

<template>
  <section class="cv" aria-labelledby="admin-page-title">
    <AdminPageHeader
      :title="t('admin.page.conversations.title')"
      :subtitle="t('admin.page.conversations.subtitle')"
      filters
      :channel="false"
      :refreshing="list.loading.value"
      @refresh="list.refresh"
    />

    <div class="cv-body">
      <ConversationFilters :people="people" />

      <AdminError
        v-if="list.error.value && !list.data.value"
        class="cv-frame"
        :message="list.errorText.value"
        :busy="list.loading.value"
        @retry="list.refresh"
      />
      <template v-else>
        <AdminError
          v-if="list.error.value"
          inline
          :message="list.errorText.value"
          :busy="list.loading.value"
          @retry="list.refresh"
        />

        <!-- ============ savollar ============ -->
        <div v-if="!isChats" class="cv-frame">
          <VDataTable
            :rows="turns.items.value"
            :columns="turnColumns"
            row-key="id"
            :loading="turns.loading.value"
            :row-to="turnTo"
            :selected-key="lastVisitedTurn"
            :label="t('admin.conversations.viewTurns')"
            :skeleton-rows="10"
            @row-click="onTurnClick"
          >
            <template #cell-time="{ row }">
              <VTooltip v-if="timeParts(row.startedAt)" :text="fmtDateTime(row.startedAt, locale, 'long')">
                <time class="cv-time" :datetime="row.startedAt ?? undefined">
                  <span>{{ timeParts(row.startedAt)?.time }}</span>
                  <span v-if="timeParts(row.startedAt)?.date" class="cv-date">{{ timeParts(row.startedAt)?.date }}</span>
                </time>
              </VTooltip>
              <span v-else class="cv-dim">—</span>
            </template>
            <template #head-channel="{ column }">
              <span :class="{ 'sr-only': channelIconOnly }">{{ column.label }}</span>
            </template>
            <template #cell-user="{ row }">
              <UserCell :name="row.userName" :login="row.userLogin" :size="24" />
            </template>
            <template #cell-channel="{ row }">
              <ChannelBadge :channel="row.channel" size="sm" :icon-only="channelIconOnly" />
            </template>
            <template #cell-question="{ row }">
              <span class="cv-q">
                <span class="cv-q__text">{{ row.question || '—' }}</span>
                <span v-if="row.inputMode === 'voice' || row.hasProposal || row.hasArtifact || row.reported" class="cv-flags">
                  <VTooltip v-if="row.inputMode === 'voice'" :text="t('admin.conversations.voice')">
                    <span class="cv-flag">
                      <Mic :size="14" :stroke-width="1.75" aria-hidden="true" />
                      <span class="sr-only">{{ t('admin.conversations.voice') }}</span>
                    </span>
                  </VTooltip>
                  <VTooltip v-if="row.hasProposal" :text="t('admin.conversations.proposal')">
                    <span class="cv-flag">
                      <Zap :size="14" :stroke-width="1.75" aria-hidden="true" />
                      <span class="sr-only">{{ t('admin.conversations.proposal') }}</span>
                    </span>
                  </VTooltip>
                  <VTooltip v-if="row.hasArtifact" :text="t('admin.conversations.artifact')">
                    <span class="cv-flag">
                      <FileText :size="14" :stroke-width="1.75" aria-hidden="true" />
                      <span class="sr-only">{{ t('admin.conversations.artifact') }}</span>
                    </span>
                  </VTooltip>
                  <VTooltip v-if="row.reported" :text="t('admin.conversations.reported')">
                    <span class="cv-flag is-strong">
                      <Flag :size="14" :stroke-width="1.75" aria-hidden="true" />
                      <span class="sr-only">{{ t('admin.conversations.reported') }}</span>
                    </span>
                  </VTooltip>
                </span>
              </span>
            </template>
            <template #cell-route="{ row }">
              <RouteBadge :route="row.route" size="sm" />
            </template>
            <template #cell-sources="{ row }">
              <span class="cv-num" :class="{ 'cv-dim': !row.sourcesCount }">{{ num(row.sourcesCount) }}</span>
              <VTooltip v-if="row.toolCalls" :text="t('sourcesLookups')">
                <span class="cv-plus">+{{ num(row.toolCalls) }}</span>
              </VTooltip>
            </template>
            <template #cell-latency="{ row }">
              <span class="cv-lat">
                <DurationText :ms="row.ttftMs" />
                <span class="cv-sep" aria-hidden="true">/</span>
                <DurationText :ms="row.totalMs" muted />
              </span>
            </template>
            <template #cell-status="{ row }">
              <StatusDot :status="row.status" :label="statusLabel(row)" :hide-label="!isPhone" />
            </template>

            <template #empty>
              <VEmpty compact :icon="MessagesSquare" :title="emptyTitle">
                <VButton v-if="conv.hasFilters.value" variant="secondary" size="sm" @click="clearFilters">
                  {{ t('ui.clearAll') }}
                </VButton>
              </VEmpty>
            </template>
            <template v-if="turns.nextCursor.value" #footer>
              <VButton variant="ghost" size="sm" :loading="turns.loadingMore.value" @click="turns.loadMore">
                {{ t('ui.loadMore') }}
              </VButton>
            </template>
          </VDataTable>
        </div>

        <!-- ============ suhbatlar ============ -->
        <div v-else class="cv-frame">
          <VDataTable
            :rows="chats.items.value"
            :columns="chatColumns"
            row-key="chatId"
            :loading="chats.loading.value"
            :row-to="chatTo"
            :label="t('admin.conversations.viewChats')"
            :skeleton-rows="10"
          >
            <template #cell-title="{ row }">
              <span class="cv-q">
                <span class="cv-q__text">{{ row.title || '—' }}</span>
                <span v-if="row.reported" class="cv-flags">
                  <VTooltip :text="t('admin.conversations.reported')">
                    <span class="cv-flag is-strong">
                      <Flag :size="14" :stroke-width="1.75" aria-hidden="true" />
                      <span class="sr-only">{{ t('admin.conversations.reported') }}</span>
                    </span>
                  </VTooltip>
                </span>
              </span>
            </template>
            <template #cell-user="{ row }">
              <UserCell :name="row.userName" :size="24" />
            </template>
            <template #head-channel="{ column }">
              <span :class="{ 'sr-only': channelIconOnly }">{{ column.label }}</span>
            </template>
            <template #cell-channel="{ row }">
              <ChannelBadge :channel="row.channel" size="sm" :icon-only="channelIconOnly" />
            </template>
            <template #cell-turns="{ row }">
              <span class="cv-num">{{ num(row.turns) }}</span>
            </template>
            <template #cell-errors="{ row }">
              <span v-if="row.errors" class="cv-err">
                <CircleAlert :size="14" :stroke-width="2" aria-hidden="true" />
                {{ num(row.errors) }}
              </span>
              <span v-else class="cv-num cv-dim">0</span>
            </template>
            <template #cell-lastAt="{ row }">
              <RelTime :value="row.lastAt" />
            </template>

            <template #empty>
              <VEmpty compact :icon="MessagesSquare" :title="emptyTitle">
                <VButton v-if="conv.hasFilters.value" variant="secondary" size="sm" @click="clearFilters">
                  {{ t('ui.clearAll') }}
                </VButton>
              </VEmpty>
            </template>
            <template v-if="chats.nextCursor.value" #footer>
              <VButton variant="ghost" size="sm" :loading="chats.loadingMore.value" @click="chats.loadMore">
                {{ t('ui.loadMore') }}
              </VButton>
            </template>
          </VDataTable>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.cv {
  display: flex;
  flex-direction: column;
  gap: var(--s-8);
}
.cv-body {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  min-width: 0;
}

/* Jadval sirt ustida, soch tolasi ramkada. `overflow: hidden` YO'Q - yopishqoq sarlavha
   sahifa aylanishiga bog'langan; yuqori burchaklarni VDataTable o'zi yumaloqlaydi. */
.cv-frame {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
}
.cv-frame :deep(.vdt) {
  --vdt-radius: calc(var(--r-lg) - 1px);
}

.cv-time {
  display: inline-flex;
  flex-direction: column;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.cv-date {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.cv-dim {
  color: var(--text-4);
}

/* Savol: bitta qator, oxirida kichik belgilar (ovoz, amal, fayl, xabar). */
.cv-q {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 0;
}
.cv-q__text {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cv-flags {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: var(--s-1_5);
  color: var(--text-3);
}
.cv-flag {
  display: inline-flex;
}
.cv-flag.is-strong {
  color: var(--text-2);
}

.cv-num {
  font-variant-numeric: tabular-nums;
}
.cv-plus {
  margin-left: var(--s-1);
  color: var(--text-3);
  font-size: var(--fs-caption);
  font-variant-numeric: tabular-nums;
}
.cv-lat {
  display: inline-flex;
  align-items: baseline;
  gap: var(--s-1);
}
.cv-sep {
  color: var(--text-4);
}
.cv-err {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1);
  color: var(--crit-text);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 767.98px) {
  .cv {
    gap: var(--s-6);
  }
  /* Kartochkada savol - sarlavha: ikki qatorgacha. */
  .cv-q {
    align-items: flex-start;
  }
  .cv-q__text {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    white-space: normal;
  }
  .cv-flags {
    padding-top: 3px;
  }
}
</style>

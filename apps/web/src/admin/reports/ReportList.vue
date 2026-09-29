<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import { CheckCheck, Inbox } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VEmpty from '../../ui/VEmpty.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import type { ReportStatus, ReportSummary } from '../types'
import ChannelBadge from '../components/ChannelBadge.vue'
import RelTime from '../components/RelTime.vue'
import StatusDot from '../components/StatusDot.vue'
import UserCell from '../components/UserCell.vue'

/**
 * Xabarlar qutisining chap ro'yxati: kim, sabab, izohning birinchi qatori, qachon.
 * Har qator - havola (`/admin/reports/:id`): o'rta tugma yangi varaqda ochadi,
 * ↑/↓ qatorlar bo'ylab yuradi, Enter ochadi.
 *
 * Holati joriy yorliqdan farq qiladigan qator (hozirgina "Hal qilindi" deb belgilangan)
 * ro'yxatdan darhol yo'qolmaydi - nuqta bilan belgilanadi, keyingi yuklashda chiqib ketadi.
 */
const props = defineProps<{
  items: ReportSummary[]
  status: ReportStatus
  selectedId: string | null
  loading: boolean
  refetching: boolean
  nextCursor: string | null
  loadingMore: boolean
  linkTo: (item: ReportSummary) => RouteLocationRaw
  /** Tanlash tarixga yozilmasin (yonma-yon ko'rinish). */
  replace?: boolean
}>()

const emit = defineEmits<{ loadMore: [] }>()

const { t, te } = useI18n({ useScope: 'global' })

const firstLoad = computed(() => props.loading && props.items.length === 0)
const reasonLabel = (r: string | null) => {
  const key = `admin.reason.${r ?? 'none'}`
  return te(key) ? t(key) : (r ?? '')
}

/* ---- klaviatura: ↑/↓ Home End ---- */
const listEl = ref<HTMLElement | null>(null)
function rows(): HTMLElement[] {
  return Array.from(listEl.value?.querySelectorAll<HTMLElement>('.rl-row') ?? [])
}
function onKeyDown(e: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) || e.altKey || e.ctrlKey || e.metaKey) return
  const all = rows()
  const i = all.indexOf(document.activeElement as HTMLElement)
  if (i < 0) return
  e.preventDefault()
  const next =
    e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : Math.max(0, Math.min(all.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))
  all[next]?.focus()
}

defineExpose({
  /** Telefonda tafsilotdan qaytganda fokus o'sha qatorga tushsin. */
  focusRow: async (id: string) => {
    await nextTick()
    listEl.value?.querySelector<HTMLElement>(`[data-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: false })
  },
})
</script>

<template>
  <div class="rl" :class="{ 'is-busy': refetching }" :aria-busy="loading || undefined">
    <ul v-if="firstLoad" class="rl-list" aria-hidden="true">
      <li v-for="k in 6" :key="k" class="rl-sk">
        <span class="rl-sk-top"><VSkeleton circle :width="24" /><VSkeleton :width="[120, 96, 140, 88, 110, 130][k - 1]" :height="12" /></span>
        <VSkeleton :width="['88%', '72%', '80%', '64%', '92%', '70%'][k - 1]" :height="12" />
      </li>
    </ul>

    <VEmpty
      v-else-if="!items.length"
      class="rl-empty"
      compact
      :icon="status === 'new' ? CheckCheck : Inbox"
      :title="status === 'new' ? t('admin.empty.reportsNew') : t('admin.empty.reports')"
    />

    <ul v-else ref="listEl" class="rl-list" role="list" @keydown="onKeyDown">
      <li v-for="r in items" :key="r.id">
        <RouterLink
          :to="linkTo(r)"
          :replace="replace"
          class="rl-row"
          :class="{ 'is-selected': r.id === selectedId }"
          :data-id="r.id"
          :aria-current="r.id === selectedId ? 'true' : undefined"
        >
          <span class="rl-top">
            <UserCell :name="r.userName" :size="24" />
            <span class="rl-time"><RelTime :value="r.createdAt" /></span>
          </span>
          <span class="rl-preview">{{ r.commentPreview || '—' }}</span>
          <span class="rl-meta">
            <VBadge size="sm">{{ reasonLabel(r.reason) }}</VBadge>
            <ChannelBadge v-if="r.channel" :channel="r.channel" size="sm" icon-only />
            <StatusDot v-if="r.status !== status" class="rl-moved" :status="r.status" />
          </span>
        </RouterLink>
      </li>
    </ul>

    <div v-if="nextCursor && !firstLoad" class="rl-more">
      <VButton variant="ghost" size="sm" :loading="loadingMore" @click="emit('loadMore')">{{ t('ui.loadMore') }}</VButton>
    </div>
  </div>
</template>

<style scoped>
.rl {
  display: flex;
  flex-direction: column;
  min-width: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.rl.is-busy {
  opacity: 0.5;
}
.rl-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: var(--s-2);
  list-style: none;
}
.rl-row {
  display: flex;
  flex-direction: column;
  gap: var(--s-1_5);
  padding: var(--s-3);
  border-radius: var(--r-md);
  color: inherit;
  text-decoration: none;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .rl-row:hover {
    background: color-mix(in srgb, var(--fill) 70%, transparent);
  }
}
.rl-row.is-selected {
  background: var(--fill);
}
.rl-row:focus-visible {
  outline-offset: -2px;
}
.rl-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  min-width: 0;
}
.rl-time {
  flex: none;
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.rl-preview {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  padding-left: 32px;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}
.rl-meta {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  padding-left: 32px;
}
.rl-moved {
  margin-left: auto;
}

.rl-sk {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  padding: var(--s-3);
}
.rl-sk-top {
  display: flex;
  align-items: center;
  gap: var(--s-2);
}
.rl-empty {
  padding-block: var(--s-12);
}
.rl-more {
  display: flex;
  justify-content: center;
  padding: var(--s-2) var(--s-3) var(--s-4);
}
@media (prefers-reduced-motion: reduce) {
  .rl {
    transition: none;
  }
}
</style>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { LocationQueryRaw } from 'vue-router'
import { MessagesSquare } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VButton from '../../ui/VButton.vue'
import VEmpty from '../../ui/VEmpty.vue'
import { fmtDateTime } from '../../ui/format'
import type { ChatTurn } from '../types'
import StatusDot from '../components/StatusDot.vue'

/**
 * "Suhbat" yorlig'i: shu suhbatning hamma savollari (eskisi birinchi), joriysi
 * belgilangan. Har biri - o'sha savolning izi; ro'yxat filtrlari havolada saqlanadi.
 */
const props = defineProps<{
  turns: ChatTurn[]
  currentId: string
  chatId: string | null
  /** Iz havolalariga qo'shiladigan so'rov (ro'yxat filtrlari). */
  query: LocationQueryRaw
}>()

const { t, locale } = useI18n({ useScope: 'global' })

const turnTo = (id: string) => ({ path: `/admin/turns/${encodeURIComponent(id)}`, query: props.query })
const chatTo = () => ({ path: '/admin/conversations', query: { ...props.query, chat: props.chatId ?? undefined } })
</script>

<template>
  <div class="tch">
    <VEmpty v-if="!turns.length" compact :icon="MessagesSquare" :title="t('ui.noData')" />
    <ol v-else class="tch-list">
      <li v-for="(turn, i) in turns" :key="turn.id">
        <RouterLink
          :to="turnTo(turn.id)"
          class="tch-item"
          :class="{ 'is-current': turn.id === currentId }"
          :aria-current="turn.id === currentId ? 'page' : undefined"
        >
          <span class="tch-n" aria-hidden="true">{{ i + 1 }}</span>
          <span class="tch-main">
            <span class="tch-q">{{ turn.question || '—' }}</span>
            <span class="tch-meta">
              <StatusDot :status="turn.status" hide-label />
              <time v-if="turn.startedAt" :datetime="turn.startedAt">{{ fmtDateTime(turn.startedAt, locale, 'medium') }}</time>
              <VBadge v-if="turn.id === currentId" size="sm">{{ t('admin.trace.current') }}</VBadge>
            </span>
          </span>
        </RouterLink>
      </li>
    </ol>
    <VButton v-if="chatId && turns.length > 1" class="tch-all" variant="ghost" size="sm" :to="chatTo()">
      {{ t('admin.trace.openChat') }}
    </VButton>
  </div>
</template>

<style scoped>
.tch {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.tch-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 calc(var(--s-2) * -1);
  padding: 0;
  list-style: none;
}
.tch-item {
  display: flex;
  gap: var(--s-3);
  padding: var(--s-2);
  border-radius: var(--r-sm);
  color: inherit;
  text-decoration: none;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .tch-item:hover {
    background: color-mix(in srgb, var(--fill) 70%, transparent);
  }
}
.tch-item.is-current {
  background: var(--fill);
}
.tch-item:focus-visible {
  outline-offset: -2px;
}
.tch-n {
  flex: none;
  width: 20px;
  padding-top: 1px;
  color: var(--text-4);
  font-size: var(--fs-caption);
  line-height: var(--lh-body-sm);
  font-variant-numeric: tabular-nums;
  text-align: end;
}
.tch-main {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: 0;
}
.tch-q {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  overflow-wrap: anywhere;
}
.tch-meta {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-variant-numeric: tabular-nums;
}
.tch-all {
  align-self: flex-start;
}
</style>

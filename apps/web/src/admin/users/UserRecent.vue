<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { ArrowRight, MessageSquare, Mic } from 'lucide-vue-next'
import VEmpty from '../../ui/VEmpty.vue'
import VSkeleton from '../../ui/VSkeleton.vue'
import type { TurnSummary } from '../types'
import { useAdminFilters } from '../useAdminFilters'
import { rememberPerson } from '../conversations/people'
import ChannelBadge from '../components/ChannelBadge.vue'
import RelTime from '../components/RelTime.vue'
import StatusDot from '../components/StatusDot.vue'

/**
 * Foydalanuvchi varag'idagi "So'nggi faollik": oxirgi 10 savol, har biri savol iziga
 * havola (`/admin/turns/:id`). Qator butunicha havola - bosish nishoni katta, Tab bilan
 * bitta to'xtash.
 *
 * Props:
 * - `turns`   - null - hali yuklanmoqda (skelet).
 * - `actorId`, `name`, `login` - "Hammasi" havolasi uchun: Suhbatlar sahifasi shu odam
 *   bilan filtrlangan holda ochiladi (`?actor=`), chip'da ism ko'rinsin deb nomi eslanadi.
 */
const props = defineProps<{
  turns: TurnSummary[] | null
  actorId: number
  name?: string | null
  login?: string | null
  labelledby?: string
}>()

const { t } = useI18n({ useScope: 'global' })
const { withFilters } = useAdminFilters()

function rememberActor() {
  rememberPerson(props.actorId, props.name, props.login)
}
</script>

<template>
  <div class="ur">
    <ul v-if="turns === null" class="ur-list" aria-hidden="true">
      <li v-for="i in 4" :key="i" class="ur-sk">
        <VSkeleton :width="8" :height="8" radius="full" />
        <VSkeleton :width="`${[72, 56, 64, 48][i - 1]}%`" :height="12" />
      </li>
    </ul>

    <VEmpty v-else-if="!turns.length" compact :icon="MessageSquare" :title="t('admin.empty.turns')" />

    <template v-else>
      <ul class="ur-list" :aria-labelledby="labelledby">
        <li v-for="turn in turns" :key="turn.id">
          <RouterLink :to="withFilters(`/admin/turns/${encodeURIComponent(turn.id)}`)" class="ur-row">
            <StatusDot :status="turn.status" hide-label />
            <span class="ur-q" :class="{ 'is-empty': !turn.question }">{{ turn.question || '—' }}</span>
            <span class="ur-meta">
              <Mic v-if="turn.inputMode === 'voice'" class="ur-voice" :size="14" :stroke-width="1.75" aria-hidden="true" />
              <span v-if="turn.inputMode === 'voice'" class="sr-only">{{ t('admin.conversations.voice') }}</span>
              <ChannelBadge :channel="turn.channel" icon-only size="sm" />
              <span class="ur-time"><RelTime :value="turn.startedAt" /></span>
            </span>
          </RouterLink>
        </li>
      </ul>
      <RouterLink
        :to="withFilters('/admin/conversations', { actor: String(actorId) })"
        class="ur-all"
        @click="rememberActor"
      >
        {{ t('admin.overview.viewAll') }}
        <ArrowRight :size="14" :stroke-width="1.75" aria-hidden="true" />
      </RouterLink>
    </template>
  </div>
</template>

<style scoped>
.ur {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  min-width: 0;
}
.ur-list {
  display: flex;
  flex-direction: column;
  margin: 0 calc(var(--s-2) * -1);
  padding: 0;
  list-style: none;
}
.ur-sk {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  height: 40px;
  padding: 0 var(--s-2);
}

.ur-row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-width: 0;
  min-height: 40px;
  padding: var(--s-2);
  border-radius: var(--r-sm);
  color: var(--text);
  text-decoration: none;
  transition: background-color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .ur-row:hover {
    background: var(--fill);
  }
}
.ur-row:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
}
.ur-q {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.ur-q.is-empty {
  color: var(--text-4);
}
.ur-meta {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: var(--s-2);
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.ur-voice {
  color: var(--text-3);
}
.ur-time {
  min-width: 52px;
  text-align: end;
}

.ur-all {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  gap: var(--s-1);
  padding: var(--s-1) 0;
  border-radius: var(--r-xs);
  color: var(--text-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  font-weight: 500;
  text-decoration: none;
  transition: color var(--dur-1) var(--ease-out);
}
@media (hover: hover) {
  .ur-all:hover {
    color: var(--text);
  }
}
</style>

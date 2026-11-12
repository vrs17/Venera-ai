<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import { Activity, BookOpen, FileText, Landmark } from 'lucide-vue-next'
import { platformIcon } from '../../components/chat/platforms'
import type { SourceItem } from '../chat/sources'

/**
 * Javob ostidagi manbalar: gorizontal aylanadigan chiplar qatori. Birinchi chip -
 * umumiy son ("3 manba"), keyin har bir manba qisqa nom bilan. Bosilsa - pastdan
 * manbalar oynasi (o'sha manba belgilangan holda).
 *
 * Qator ekran chetigacha chiqadi (manfiy chekka): chiplar kesilib qolmasdan,
 * barmoq bilan surilganda chetdan chetga oqadi.
 *
 * Jonli so'rov chipida "T1" yo'q - "CRM · Vazifa ma'lumoti" (sources.ts): ichki
 * belgi xodimga hech narsa demaydi. Belgi - platformaniki (HRM odamlar, CRM kanban):
 * bir qarashda qaysi tizimdan ekani ko'rinadi.
 */
defineProps<{ items: SourceItem[] }>()
const emit = defineEmits<{ open: [marker: string | null] }>()
const { t } = useI18n({ useScope: 'global' })

const ICON = { doc: FileText, law: Landmark, lookup: Activity }

function iconOf(item: SourceItem): Component {
  return item.kind === 'lookup' && item.platform ? platformIcon(item.platform) : ICON[item.kind]
}
</script>

<template>
  <div class="srow" role="group" :aria-label="t('tg.sources.title')">
    <button type="button" class="srow__chip srow__chip--all" @click="emit('open', null)">
      <BookOpen :size="15" :stroke-width="1.75" aria-hidden="true" />
      <span>{{ t('tg.chat.sourcesShort', { n: items.length }) }}</span>
    </button>
    <button
      v-for="item in items"
      :key="item.kind + item.marker"
      type="button"
      class="srow__chip"
      :class="{ 'is-failed': item.failed }"
      @click="emit('open', item.marker)"
    >
      <component :is="iconOf(item)" class="srow__icon" :size="14" :stroke-width="1.75" aria-hidden="true" />
      <span v-if="item.kind !== 'lookup'" class="srow__n">{{ item.badge }}</span>
      <span class="srow__t">{{ item.title }}</span>
    </button>
  </div>
</template>

<style scoped>
.srow {
  display: flex;
  gap: var(--s-1_5);
  margin: var(--s-3) calc(var(--tg-gutter) * -1) 0;
  padding: 2px var(--tg-gutter);
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scroll-snap-type: x proximity;
  scroll-padding-inline: var(--tg-gutter);
  scrollbar-width: none;
  -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 var(--s-3), #000 calc(100% - var(--s-6)), transparent);
  mask-image: linear-gradient(90deg, transparent 0, #000 var(--s-3), #000 calc(100% - var(--s-6)), transparent);
}
.srow::-webkit-scrollbar {
  display: none;
}
.srow__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--s-1_5);
  flex-shrink: 0;
  max-width: 220px;
  min-height: 36px;
  padding: 0 var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--bg);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  scroll-snap-align: start;
  transition:
    transform var(--dur-1) var(--ease-out),
    background-color var(--dur-1) var(--ease-out);
}
/* Bosish maydoni 44px - ko'rinishi ixcham (36) qoladi. */
.srow__chip {
  position: relative;
}
.srow__chip::after {
  content: '';
  position: absolute;
  inset: -4px 0;
}
.srow__chip:active {
  transform: scale(0.96);
  background: var(--fill);
}
.srow__chip--all {
  border-color: transparent;
  background: var(--fill);
  color: var(--text);
  font-weight: 600;
}
.srow__icon {
  flex-shrink: 0;
  color: var(--text-3);
}
.srow__n {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-3);
}
.srow__t {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.srow__t::first-letter {
  text-transform: uppercase;
}
.srow__chip.is-failed .srow__icon {
  color: var(--warn-text);
}
</style>

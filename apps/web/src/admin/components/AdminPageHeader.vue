<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RotateCw } from 'lucide-vue-next'
import VIconButton from '../../ui/VIconButton.vue'
import AdminFilters from './AdminFilters.vue'

/**
 * Sahifa boshi (spec §4.5): chapda sarlavha (title-1) va bitta qator izoh (text-3),
 * o'ngda global filtr qatori. Telefonda ustma-ust.
 *
 * Props:
 * - `title`      - sahifa nomi (h1).
 * - `subtitle`   - bitta qisqa qator; bo'lmasa chiqmaydi.
 * - `titleId`    - h1 id (standart `admin-page-title`: sahifa `aria-labelledby` bilan ulaydi).
 * - `filters`    - o'ngda <AdminFilters/> (sana + kanal).
 * - `channel`    - filtrda kanal tanlovi (standart: ha).
 * - `refreshing` - "Yangilash" belgisida spinner.
 * - `onRefresh`  - `@refresh` berilsa "Yangilash" tugmasi chiqadi (filtr qatorida yoki yolg'iz).
 *
 * Slotlar:
 * - `leading` - sarlavha ustida (orqaga havola, non-crumbs).
 * - `meta`    - izoh ostida (nishonlar, id, qo'shimcha qator).
 * - `actions` - o'ngda, filtrdan oldin (sahifa tugmalari).
 *
 *   <AdminPageHeader :title="t('admin.page.usage.title')" :subtitle="t('admin.page.usage.subtitle')"
 *                    filters :refreshing="q.refetching.value" @refresh="q.refresh" />
 */
const props = withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    titleId?: string
    filters?: boolean
    channel?: boolean
    refreshing?: boolean
    onRefresh?: () => void
  }>(),
  { titleId: 'admin-page-title', channel: true },
)

defineSlots<{
  leading?(): unknown
  meta?(): unknown
  actions?(): unknown
}>()

const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <header class="aph">
    <div class="aph__titles">
      <div v-if="$slots.leading" class="aph__leading"><slot name="leading" /></div>
      <h1 :id="titleId" class="aph__title t-title-1">{{ title }}</h1>
      <p v-if="subtitle" class="aph__subtitle">{{ subtitle }}</p>
      <div v-if="$slots.meta" class="aph__meta"><slot name="meta" /></div>
    </div>
    <div v-if="filters || $slots.actions || onRefresh" class="aph__side">
      <slot name="actions" />
      <AdminFilters
        v-if="filters"
        :channel="channel"
        :refreshing="refreshing"
        :on-refresh="props.onRefresh"
      />
      <VIconButton
        v-else-if="onRefresh"
        class="aph__refresh"
        :icon="RotateCw"
        :label="t('admin.common.refresh')"
        :loading="refreshing"
        @click="props.onRefresh?.()"
      />
    </div>
  </header>
</template>

<style scoped>
.aph {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s-4) var(--s-8);
  min-width: 0;
}
.aph__titles {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: 0;
  flex: 1 1 280px;
}
.aph__leading {
  margin-bottom: var(--s-2);
}
.aph__title {
  overflow-wrap: anywhere;
}
.aph__subtitle {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.aph__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2) var(--s-3);
  margin-top: var(--s-2);
}
.aph__side {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s-2);
  min-width: 0;
  max-width: 100%;
}
.aph__refresh {
  color: var(--text-3);
}

@media (max-width: 767.98px) {
  .aph {
    align-items: stretch;
  }
  .aph__side {
    justify-content: flex-start;
    width: 100%;
  }
}
</style>

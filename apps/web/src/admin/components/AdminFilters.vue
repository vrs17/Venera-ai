<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RotateCw } from 'lucide-vue-next'
import VDateRange from '../../ui/VDateRange.vue'
import VIconButton from '../../ui/VIconButton.vue'
import VSegmented from '../../ui/VSegmented.vue'
import type { SegmentedOption } from '../../ui/VSegmented.vue'
import { useIsPhone } from '../../ui/composables/useMediaQuery'
import { useAdminFilters } from '../useAdminFilters'
import type { ChannelFilter } from '../types'

/**
 * Global filtr qatori (spec §4.5): sana oralig'i + kanal. Qiymatlar URL'da
 * (`useAdminFilters`) - shu komponentning o'zida holat yo'q, har bir sahifa bir xil
 * filtrni ko'radi va havola ulashilsa hamkasb aynan shu ko'rinishni ochadi.
 *
 * Props:
 * - `channel`    - kanal tanlovini ko'rsatish (standart: ha). Kanal ma'nosiz bo'lgan
 *                  joyda (audit jurnali) `:channel="false"`.
 * - `refreshing` - "Yangilash" tugmasida aylanuvchi belgi.
 * - `onRefresh`  - berilsa (`@refresh`) o'ngda "Yangilash" belgili tugmasi chiqadi.
 *
 *   <AdminFilters :refreshing="q.refetching.value" @refresh="q.refresh" />
 *
 * Telefonda: sana va "Yangilash" birinchi qatorda, kanallar ostida to'liq kenglikda.
 */
const props = withDefaults(
  defineProps<{
    channel?: boolean
    refreshing?: boolean
    onRefresh?: () => void
  }>(),
  { channel: true },
)

const { t } = useI18n({ useScope: 'global' })
const { range, channel: channelModel } = useAdminFilters()
const isPhone = useIsPhone()

// Spec: Hammasi · Web · Mini App · Bot. Desktop/API kam uchraydi - ular faqat URL'da
// tanlangan bo'lsa qo'shiladi (aks holda tanlangan segment ko'rinmay qolardi).
const BASE: ChannelFilter[] = ['all', 'web', 'miniapp', 'bot']
const options = computed<SegmentedOption<ChannelFilter>[]>(() => {
  const list = BASE.includes(channelModel.value) ? BASE : [...BASE, channelModel.value]
  return list.map((value) => ({ value, label: t(`admin.channel.${value}`) }))
})
</script>

<template>
  <div class="af" role="group" :aria-label="t('ui.filters')">
    <div class="af__row">
      <VDateRange v-model="range" :aria-label="t('admin.filter.period')" />
      <VIconButton
        v-if="onRefresh"
        class="af__refresh"
        :icon="RotateCw"
        :label="t('admin.common.refresh')"
        :loading="refreshing"
        size="md"
        @click="props.onRefresh?.()"
      />
    </div>
    <VSegmented
      v-if="channel"
      v-model="channelModel"
      class="af__seg"
      :options="options"
      :block="isPhone"
      :aria-label="t('admin.filter.channel')"
    />
  </div>
</template>

<style scoped>
.af {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s-2);
  min-width: 0;
}
/* Sana chip'i va "Yangilash" - kanal tanlovidan keyin (o'ng chetda) turadi. */
.af__row {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  order: 2;
  min-width: 0;
}
.af__seg {
  order: 1;
  min-width: 0;
}
.af__refresh {
  color: var(--text-3);
}

@media (max-width: 767.98px) {
  .af {
    justify-content: flex-start;
    width: 100%;
  }
  .af__row {
    order: 0;
    width: 100%;
    justify-content: space-between;
  }
  .af__seg {
    width: 100%;
  }
}
</style>

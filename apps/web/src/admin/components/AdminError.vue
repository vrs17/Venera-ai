<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { CircleAlert, RotateCw } from 'lucide-vue-next'
import VButton from '../../ui/VButton.vue'

/**
 * So'rov xatosi: nima bo'lgani bitta jumlada + "Qayta urinish" (spec §5).
 *
 * Props:
 * - `message` - `useAdminQuery().errorText`; bo'lmasa umumiy "Yuklab bo'lmadi".
 * - `inline`  - ma'lumot allaqachon ko'rinib turibdi: sahifa ustidagi ingichka qator
 *               (eski ma'lumot o'chirilmaydi). Aks holda - markazdagi bo'sh holat.
 * - `busy`    - qayta urinish ketmoqda (tugmada spinner).
 * - `onRetry` - `@retry`; berilmasa tugma chiqmaydi.
 *
 *   <AdminError v-if="q.error.value && !q.data.value" :message="q.errorText.value" @retry="q.refresh" />
 */
const props = defineProps<{
  message?: string | null
  inline?: boolean
  busy?: boolean
  onRetry?: () => void
}>()

const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <div class="ae" :class="{ 'ae--inline': inline }" role="alert">
    <span class="ae__icon" aria-hidden="true">
      <CircleAlert :size="inline ? 16 : 18" :stroke-width="1.75" />
    </span>
    <p class="ae__text">{{ message || t('ui.errorLoad') }}</p>
    <VButton
      v-if="onRetry"
      class="ae__retry"
      :variant="inline ? 'ghost' : 'secondary'"
      size="sm"
      :icon="RotateCw"
      :loading="busy"
      @click="props.onRetry?.()"
    >
      {{ t('ui.retry') }}
    </VButton>
  </div>
</template>

<style scoped>
.ae {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-3);
  padding: var(--s-12) var(--s-6);
  text-align: center;
}
.ae__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--r-full);
  background: var(--crit-soft);
  color: var(--crit-text);
}
.ae__text {
  max-width: 44ch;
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}

.ae--inline {
  flex-direction: row;
  justify-content: flex-start;
  gap: var(--s-2);
  padding: var(--s-2) var(--s-2) var(--s-2) var(--s-3);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  text-align: start;
}
.ae--inline .ae__icon {
  width: auto;
  height: auto;
  background: none;
}
.ae--inline .ae__text {
  flex: 1;
  max-width: none;
  min-width: 0;
}
.ae--inline .ae__retry {
  flex: none;
}
</style>

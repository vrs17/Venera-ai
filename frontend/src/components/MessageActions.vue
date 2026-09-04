<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RegenerateIcon } from '../icons'
import CopyButton from './CopyButton.vue'

/**
 * Action bar under an assistant answer: Copy (only when there is text to copy)
 * and Regenerate (always — also offered on a failed request as a retry).
 * `busy` disables Regenerate while another request is in flight.
 */
defineProps<{ copyText?: string | null; busy?: boolean }>()
const emit = defineEmits<{ regenerate: [] }>()

const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <div class="msg-actions">
    <CopyButton v-if="copyText" :text="copyText" :aria-label="t('copy')" />
    <button
      type="button"
      class="msg-action"
      :title="t('regenerate')"
      :aria-label="t('regenerate')"
      :disabled="busy"
      @click="emit('regenerate')"
    >
      <RegenerateIcon :size="15" />
    </button>
  </div>
</template>

<style scoped>
.msg-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-top: 8px;
  margin-left: -7px; /* pull the first icon button back to the text edge */
}
.msg-action:disabled {
  opacity: 0.45;
  cursor: default;
}
.msg-action:disabled:hover {
  background: transparent;
  color: var(--text-muted);
}
</style>

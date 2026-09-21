<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { formatFull, formatWhen } from '../time'
import { RegenerateIcon } from '../icons'
import CopyButton from './CopyButton.vue'

/**
 * Action bar under an assistant answer: Copy (only when there is text to copy)
 * and Regenerate (always — also offered on a failed request as a retry).
 * `busy` disables Regenerate while another request is in flight.
 *
 * `at` - javob tugagan vaqt, qatorning O'NG chetida. Shu qatorda, chunki bu
 * javobning oxiri: yuqori burchakda u matn ustiga tushardi (matn to'liq
 * kenglikda). Ko'rinishi - faqat sichqoncha javob ustida bo'lganda
 * (`Conversation.vue`, `.ex__answer:hover`).
 */
const props = defineProps<{ copyText?: string | null; busy?: boolean; at?: number | null }>()
const emit = defineEmits<{ regenerate: [] }>()

const { t, locale } = useI18n({ useScope: 'global' })
const lang = computed(() => LOCALES.find((l) => l.code === (locale.value as Locale))?.htmlLang ?? 'uz-Latn')
const when = computed(() => (props.at ? formatWhen(props.at, lang.value) : ''))
const full = computed(() => (props.at ? formatFull(props.at, lang.value) : ''))
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
    <time v-if="at" class="msg-time" :datetime="new Date(at).toISOString()" :title="full">{{ when }}</time>
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
.msg-time {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  cursor: default;
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

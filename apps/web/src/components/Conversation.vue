<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { UIExchange } from '../types'
import { LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { formatFull, formatWhen } from '../time'
import PipelineResult from './PipelineResult.vue'
import CopyButton from './CopyButton.vue'

const props = defineProps<{ exchanges: UIExchange[]; devMode: boolean; busy?: boolean }>()
defineEmits<{ regenerate: [id: string] }>()
const { t, locale } = useI18n({ useScope: 'global' })
const scrollerRef = ref<HTMLDivElement | null>(null)

// Vaqt yozuvi UI tilida: `Intl` ga BCP-47 kodi kerak (`uz-Latn`), i18n
// kodi emas (`uz`).
const lang = computed(() => LOCALES.find((l) => l.code === (locale.value as Locale))?.htmlLang ?? 'uz-Latn')
function iso(ms: number): string {
  return new Date(ms).toISOString()
}

// Auto-scroll to the latest message whenever a new exchange is added or the
// pending response resolves. deep:true catches the in-place pending->resolved
// mutation; nextTick waits for the DOM so scrollHeight is current.
watch(
  () => props.exchanges,
  async () => {
    await nextTick()
    const el = scrollerRef.value
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  },
  { deep: true },
)
</script>

<template>
  <div ref="scrollerRef" :style="{ position: 'absolute', inset: 0, overflowY: 'auto', padding: '8px 24px 200px' }">
    <div :style="{ maxWidth: '760px', margin: '0 auto' }">
      <div v-for="ex in exchanges" :key="ex.id">
        <!-- Tarixdan kelgan javob savolsiz bo'lishi mumkin (eski yozuv) -
             bo'sh pufakcha ko'rsatilmaydi. -->
        <div v-if="ex.question" class="ex__user">
          <div
            class="glass reveal-up"
            :style="{
              background: 'var(--glass-bg)',
              border: '1px solid var(--glass-border)',
              borderRadius: '18px 18px 4px 18px',
              padding: '11px 16px',
              fontSize: '15px',
              lineHeight: 1.55,
              maxWidth: '540px',
              color: 'var(--text)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }"
          >
            {{ ex.question }}
          </div>
          <div class="ex__user-tools">
            <!-- Yuborilgan vaqt - nusxa tugmasi bilan bir qatorda, faqat
                 sichqoncha ustida (pastdagi qoida). -->
            <time v-if="ex.askedAt" class="ex__time" :datetime="iso(ex.askedAt)" :title="formatFull(ex.askedAt, lang)">
              {{ formatWhen(ex.askedAt, lang) }}
            </time>
            <CopyButton :text="ex.question" :aria-label="t('copyPrompt')" :size="14" />
          </div>
        </div>
        <!-- Javob vaqti amallar qatorida (`MessageActions`, o'ng chetda);
             bu o'ram faqat sichqoncha ustida ko'rsatish uchun. -->
        <div class="ex__answer">
          <PipelineResult :exchange="ex" :dev-mode="devMode" :busy="busy" @regenerate="$emit('regenerate', ex.id)" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ex__user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  margin: 20px 0 4px;
}
.ex__user-tools {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  margin-right: -9px; /* align the icon button's optical edge with the bubble */
}
.ex__time {
  font-size: 11.5px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  cursor: default;
}
/* On hover-capable devices, keep the prompt copy hidden until hover/focus.
   On touch devices (no hover) it stays visible so it's reachable. */
@media (hover: hover) {
  .ex__user-tools,
  .ex__answer :deep(.msg-time) {
    opacity: 0;
    transform: translateY(-2px);
    transition: opacity 0.15s, transform 0.15s;
  }
  .ex__user:hover .ex__user-tools,
  .ex__user:focus-within .ex__user-tools,
  .ex__answer:hover :deep(.msg-time),
  .ex__answer:focus-within :deep(.msg-time) {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>

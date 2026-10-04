<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { FileText } from 'lucide-vue-next'
import VBadge from '../../ui/VBadge.vue'
import VCard from '../../ui/VCard.vue'
import RelTime from '../components/RelTime.vue'

/**
 * Javob bilan yaratilgan fayl (ariza) - faqat xulosa: nomi, kaliti, qaysi formatlar
 * berilgani va muddati. Yuklab olish havolalari bir martalik kalit bo'lgani uchun
 * izga yozilmaydi (`recorder._on_artifact`) - bu yerdan yuklab bo'lmaydi.
 */
const props = defineProps<{ payload: unknown }>()

const { t } = useI18n({ useScope: 'global' })

const p = computed<Record<string, unknown>>(() =>
  props.payload && typeof props.payload === 'object' && !Array.isArray(props.payload)
    ? (props.payload as Record<string, unknown>)
    : {},
)
const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : null)
const title = computed(() => str(p.value.title) ?? t('artifactReady'))
const docId = computed(() => str(p.value.doc_id))
const expires = computed(() => str(p.value.expires_at))
const files = computed(() =>
  (Array.isArray(p.value.files) ? p.value.files : []).filter((f): f is string => typeof f === 'string' && f !== 'preview'),
)
</script>

<template>
  <VCard :title="t('admin.trace.artifact')" :heading-level="2">
    <div class="ac">
      <span class="ac-icon" aria-hidden="true"><FileText :size="18" :stroke-width="1.75" /></span>
      <div class="ac-main">
        <p class="ac-title">{{ title }}</p>
        <p v-if="docId || expires" class="ac-meta">
          <span v-if="docId" class="t-mono">{{ docId }}</span>
          <span v-if="docId && expires" aria-hidden="true"> · </span>
          <RelTime v-if="expires" :value="expires" />
        </p>
      </div>
      <span v-if="files.length" class="ac-files">
        <VBadge v-for="f in files" :key="f" size="sm">{{ f.toUpperCase() }}</VBadge>
      </span>
    </div>
  </VCard>
</template>

<style scoped>
.ac {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  min-width: 0;
}
.ac-icon {
  display: inline-grid;
  flex: none;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--r-md);
  background: var(--fill);
  color: var(--text-2);
}
.ac-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.ac-title {
  color: var(--text);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.ac-meta {
  color: var(--text-3);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
}
.ac-files {
  display: inline-flex;
  flex: none;
  gap: var(--s-1);
}
</style>

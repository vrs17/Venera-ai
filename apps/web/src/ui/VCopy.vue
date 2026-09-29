<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Copy } from 'lucide-vue-next'
import { copyText } from '../clipboard'
import VButton from './VButton.vue'
import VIconButton from './VIconButton.vue'
import type { Placement } from './composables/useFloating'

/**
 * Nusxa olish: bosilganda matnni buferga yozadi, 1.5 s davomida ✓ va "Nusxa olindi".
 *
 * `label` berilsa - matnli ghost tugma, aks holda belgili tugma (tooltip bilan).
 * `text` funksiya ham bo'lishi mumkin: katta JSON'ni faqat bosilganda yig'amiz.
 * Natija yashirin `status` orqali ekran o'quvchiga ham aytiladi (u tugmadan TASHQARIDA:
 * tugma ichidagi tarkib ARIA bo'yicha "taqdimot" - u yerdagi jonli hudud o'qilmasligi mumkin).
 */
const props = withDefaults(
  defineProps<{
    text: string | (() => string | Promise<string>)
    label?: string
    size?: 'sm' | 'md'
    tooltipPlacement?: Placement
  }>(),
  { size: 'sm', tooltipPlacement: 'top' },
)

const emit = defineEmits<{ copied: [text: string] }>()
const { t } = useI18n({ useScope: 'global' })

const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

const current = computed(() => (copied.value ? t('ui.copied') : (props.label ?? t('ui.copy'))))

async function onCopy() {
  const value = typeof props.text === 'function' ? await props.text() : props.text
  if (!(await copyText(value))) return
  copied.value = true
  emit('copied', value)
  clearTimeout(timer)
  timer = setTimeout(() => (copied.value = false), 1500)
}
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <span class="v-copy" :class="{ 'is-copied': copied }">
    <VButton v-if="label" variant="ghost" :size="size" :icon="copied ? Check : Copy" @click="onCopy">
      {{ current }}
    </VButton>
    <VIconButton
      v-else
      :label="current"
      :icon="copied ? Check : Copy"
      :size="size"
      :tooltip-placement="tooltipPlacement"
      @click="onCopy"
    />
    <span class="sr-only" role="status">{{ copied ? t('ui.copied') : '' }}</span>
  </span>
</template>

<style scoped>
.v-copy {
  display: inline-flex;
  flex-shrink: 0;
  vertical-align: middle;
}
.v-copy.is-copied :deep(svg) {
  animation: v-copy-pop var(--dur-3) var(--ease-out);
}
@keyframes v-copy-pop {
  from {
    transform: scale(0.6);
    opacity: 0;
  }
  to {
    transform: scale(1);
    opacity: 1;
  }
}
</style>

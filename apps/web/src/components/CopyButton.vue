<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Copy } from 'lucide-vue-next'
import { copyText } from '../clipboard'
import VIconButton from '../ui/VIconButton.vue'

/**
 * Nusxa olish tugmasi - javob amallarida va savol pufakchasi ostida.
 *
 * Belgi 1.6 s ga ✓ ga aylanadi - FAQAT nusxa haqiqatan olinganda (buferga yozish rad
 * etilsa, jim qoladi). "Nusxa olindi" ekran o'quvchiga yashirin `status` orqali
 * aytiladi: tugmaning o'zgargan aria-label'i har doim ham o'qilmaydi.
 */
const props = withDefaults(
  defineProps<{
    text: string
    /** Tooltip va aria-label; bo'lmasa "Nusxalash". */
    ariaLabel?: string
    size?: 'sm' | 'md'
  }>(),
  { size: 'sm' },
)

const { t } = useI18n({ useScope: 'global' })
const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

async function onCopy() {
  const ok = await copyText(props.text)
  if (!ok) return
  copied.value = true
  clearTimeout(timer)
  timer = setTimeout(() => (copied.value = false), 1600)
}
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <span class="copy-btn">
    <VIconButton
      :label="copied ? t('copied') : (ariaLabel ?? t('copy'))"
      :icon="copied ? Check : Copy"
      :size="size"
      @click="onCopy"
    />
    <span class="sr-only" role="status">{{ copied ? t('copied') : '' }}</span>
  </span>
</template>

<style scoped>
.copy-btn {
  display: inline-flex;
  flex-shrink: 0;
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Javob kelgunicha: bitta jim qator. Yordamchi nima qilayotganini aytsa ("hujjatlar
 * qidirilmoqda") - o'sha matn, aytmasa - "O'ylayapman".
 *
 * `status` - yordamchining O'Z matni, savol tilida keladi, shuning uchun TARJIMA
 * QILINMAYDI. Birinchi token kelishi bilan bu qator javobning o'zi bilan almashadi.
 *
 * Harakat - matn ustidan sekin o'tadigan yorug'lik (niqob, rang emas); qisqartirilgan
 * harakat rejimida - oddiy, qimirlamaydigan matn.
 */
const props = defineProps<{ status?: string }>()
const { t } = useI18n({ useScope: 'global' })
const word = computed(() => props.status?.trim() || t('thinking'))
</script>

<template>
  <div class="think" role="status" :aria-label="word">
    <Transition name="think-swap" mode="out-in">
      <span :key="word" class="think__text">{{ word }}</span>
    </Transition>
  </div>
</template>

<style scoped>
.think {
  display: flex;
  align-items: center;
  min-height: var(--lh-body-lg);
  color: var(--text-3);
  font-size: var(--fs-body);
  line-height: var(--lh-body-lg);
}
.think__text {
  /* Yorug'lik: niqobning shaffof bo'lagi matn bo'ylab yuradi - rang o'zgarmaydi. */
  -webkit-mask-image: linear-gradient(90deg, #000 0%, #000 35%, rgb(0 0 0 / 0.35) 50%, #000 65%, #000 100%);
  mask-image: linear-gradient(90deg, #000 0%, #000 35%, rgb(0 0 0 / 0.35) 50%, #000 65%, #000 100%);
  -webkit-mask-size: 250% 100%;
  mask-size: 250% 100%;
  animation: think-shimmer 1.8s linear infinite;
}
@keyframes think-shimmer {
  from {
    -webkit-mask-position: 100% 0;
    mask-position: 100% 0;
  }
  to {
    -webkit-mask-position: 0% 0;
    mask-position: 0% 0;
  }
}
.think-swap-enter-active,
.think-swap-leave-active {
  transition: opacity var(--dur-2) var(--ease-out);
}
.think-swap-enter-from,
.think-swap-leave-to {
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .think__text {
    animation: none;
    -webkit-mask-image: none;
    mask-image: none;
  }
}
</style>

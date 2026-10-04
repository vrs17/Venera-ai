<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RotateCw, WifiOff } from 'lucide-vue-next'
import BrandSpark from '../../components/BrandSpark.vue'

/**
 * Birinchi chizish, ikki ko'rinish:
 *
 *   `chat`  - token bor (99% ochilish): chat ekranining SKELETI (yuqori panel, pastdagi
 *             takliflar, kompozer) - ilova "ochildi" deb seziladi, sessiya tekshiruvi
 *             esa orqada. Skelet haqiqiy ekran bilan bir xil joylashuvda: chat
 *             kelganda hech narsa sakramaydi.
 *   `brand` - token yo'q (birinchi ochilish): faqat brend belgisi, aynan KIRISH
 *             ekranidagi koordinatada. Odam chat "ochilib", keyin formaga
 *             almashganini ko'rmaydi - belgi joyida qoladi.
 *
 * `offline` - token bor, lekin server javob bermadi: tokenni tashlamaymiz va parol
 * so'ramaymiz, faqat "qayta urinish".
 */
withDefaults(defineProps<{ offline?: boolean; variant?: 'chat' | 'brand' }>(), { offline: false, variant: 'chat' })
const emit = defineEmits<{ retry: [] }>()
const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <div v-if="variant === 'brand' && !offline" class="boot boot--brand" aria-busy="true">
    <span class="boot__spark" aria-hidden="true"><BrandSpark :size="36" /></span>
    <span class="sr-only" role="status">{{ t('loading') }}</span>
  </div>

  <div v-else class="boot" :aria-busy="!offline">
    <div class="boot__top" aria-hidden="true">
      <span class="tg-skel boot__dot" />
      <span class="tg-skel boot__title" />
      <span class="tg-skel boot__dot" />
    </div>

    <div v-if="offline" class="boot__offline" role="alert">
      <span class="boot__icon"><WifiOff :size="22" :stroke-width="1.75" aria-hidden="true" /></span>
      <p class="boot__head">{{ t('tg.boot.failed') }}</p>
      <p class="boot__hint">{{ t('tg.boot.hint') }}</p>
      <button type="button" class="boot__retry" @click="emit('retry')">
        <RotateCw :size="18" :stroke-width="2" aria-hidden="true" />
        <span>{{ t('retry') }}</span>
      </button>
    </div>

    <div v-else class="boot__body" aria-hidden="true">
      <span class="tg-skel boot__hello" />
      <span class="tg-skel boot__lead" />
      <div class="boot__grid">
        <span v-for="i in 4" :key="i" class="tg-skel boot__card" />
      </div>
    </div>

    <div class="boot__composer" aria-hidden="true">
      <span class="tg-skel boot__field" />
    </div>
    <span v-if="!offline" class="sr-only" role="status">{{ t('loading') }}</span>
  </div>
</template>

<style scoped>
.boot {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  padding-top: var(--tg-safe-top);
}

/* Koordinatalar LoginScreen bilan BIR XIL: .login padding-top (+24px) va
   .login__inner margin-top (clamp). */
.boot--brand {
  align-items: center;
  padding-top: calc(var(--tg-safe-top) + var(--s-6) + clamp(24px, 10vh, 88px));
}
.boot__spark {
  display: grid;
  place-items: center;
  width: 72px;
  height: 72px;
  border-radius: 24px;
  background: var(--brand-soft);
  color: var(--brand);
  animation: boot-breathe 1.8s ease-in-out 400ms infinite;
}
@keyframes boot-breathe {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(0.94);
  }
}

.boot__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  height: 52px;
  padding: 0 var(--tg-chrome);
}
.boot__dot {
  width: 36px;
  height: 36px;
  border-radius: var(--r-full);
}
.boot__title {
  width: 96px;
  height: 14px;
}
.boot__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: flex-end;
  gap: var(--s-2);
  padding: 0 var(--tg-gutter) var(--s-4);
}
.boot__hello {
  width: 52%;
  height: 26px;
  border-radius: var(--r-sm);
}
.boot__lead {
  width: 38%;
  height: 16px;
  margin-bottom: var(--s-3);
}
.boot__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-2);
}
.boot__card {
  height: 64px;
  border-radius: var(--r-lg);
}
.boot__composer {
  padding: var(--s-2) var(--tg-chrome) calc(var(--s-2) + var(--tg-safe-bottom));
}
.boot__field {
  height: 48px;
  border-radius: var(--r-xl);
}

.boot__offline {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  padding: var(--s-6) var(--s-8);
  text-align: center;
}
.boot__icon {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  margin-bottom: var(--s-2);
  border-radius: var(--r-full);
  background: var(--fill);
  color: var(--text-2);
}
.boot__head {
  font-size: var(--fs-title-3);
  line-height: var(--lh-title-3);
  font-weight: 600;
}
.boot__hint {
  color: var(--text-3);
  font-size: var(--fs-body-sm);
  line-height: var(--lh-body-sm);
}
.boot__retry {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  min-height: 48px;
  margin-top: var(--s-4);
  padding: 0 var(--s-6);
  border-radius: var(--r-full);
  background: var(--ink);
  color: var(--on-ink);
  font-weight: 600;
}
.boot__retry:active {
  transform: scale(0.97);
}

@media (prefers-reduced-motion: reduce) {
  .boot__spark {
    animation: none;
  }
}
</style>

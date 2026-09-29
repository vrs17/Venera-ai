<script setup lang="ts">
import { computed } from 'vue'

/**
 * Yuklanish o'rinbosari. Faqat BIRINCHI yuklashda ishlatiladi - keyingi yangilanishlarda
 * eski ma'lumot 50% shaffoflikda qoladi (spec §3 VDataTable), sakrash bo'lmaydi.
 *
 * `lines` - matn bloki: har qator 12px, oxirgisi qisqaroq (tabiiy paragraf ko'rinishi).
 */
const props = withDefaults(
  defineProps<{
    width?: string | number
    height?: string | number
    radius?: 'xs' | 'sm' | 'md' | 'lg' | 'full'
    circle?: boolean
    lines?: number
  }>(),
  { radius: 'xs' },
)

function px(v: string | number | undefined): string | undefined {
  if (v === undefined) return undefined
  return typeof v === 'number' ? `${v}px` : v
}

const style = computed(() => ({
  width: px(props.circle ? (props.width ?? props.height ?? 32) : props.width),
  height: px(props.circle ? (props.height ?? props.width ?? 32) : (props.height ?? 12)),
  borderRadius: props.circle ? 'var(--r-full)' : `var(--r-${props.radius})`,
}))
</script>

<template>
  <span v-if="lines && lines > 1" class="v-skeleton-lines" :style="{ width: px(width) }" aria-hidden="true">
    <span
      v-for="n in lines"
      :key="n"
      class="v-skeleton"
      :style="{ height: px(height ?? 12), width: n === lines ? '62%' : '100%', borderRadius: `var(--r-${radius})` }"
    />
  </span>
  <span v-else class="v-skeleton" :style="style" aria-hidden="true" />
</template>

<style scoped>
.v-skeleton {
  display: block;
  background-color: var(--fill);
  background-image: linear-gradient(
    90deg,
    transparent 0%,
    color-mix(in srgb, var(--fill-hover) 90%, transparent) 50%,
    transparent 100%
  );
  background-size: 200% 100%;
  background-repeat: no-repeat;
  animation: v-shimmer 1.6s var(--ease-out) infinite;
}
.v-skeleton-lines {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
@keyframes v-shimmer {
  from {
    background-position: 150% 0;
  }
  to {
    background-position: -50% 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .v-skeleton {
    animation: none;
    background-image: none;
  }
}
</style>
